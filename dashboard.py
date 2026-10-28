#!/usr/bin/env python3
"""
STL -> STEP dashboard.   Put this file next to stl2step.py, then run:

    python dashboard.py

and open http://localhost:8000  (it opens automatically).
Needs:  pip install numpy cadquery-ocp   (same as stl2step.py)
"""
import ast, base64, contextlib, hmac, io, json, os, re, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stl2step as S

OUT = os.path.join(HERE, "dashboard_output")
os.makedirs(OUT, exist_ok=True)
HIST = os.path.join(OUT, "history.json")
LOCK = threading.Lock()


def load_hist():
    try:
        return json.load(open(HIST))
    except Exception:
        return []


def save_hist(h):
    json.dump(h[-200:], open(HIST, "w"))


def run_job(name, data, o):
    jid = time.strftime("%Y%m%d-%H%M%S")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.splitext(os.path.basename(name))[0]) or "part"
    stl = os.path.join(OUT, "%s_%s.stl" % (base, jid))
    step = os.path.join(OUT, "%s_%s.step" % (base, jid))
    with open(stl, "wb") as f:
        f.write(data)
    buf = io.StringIO()
    t0 = time.time()
    res = {"id": jid, "name": base + ".step", "file": os.path.basename(step), "ok": False,
           "mode": "-", "faces": {}, "curved": {}, "tris": 0, "volume": None, "mesh_volume": None,
           "fmt": o.get("fmt", "step"), "sldprt": None}
    with contextlib.redirect_stdout(buf):
        try:
            tris = S.read_stl(stl)
            res["tris"] = len(tris)
            if o.get("repair", True) and tris:
                tris = S.repair_tris(tris, log=print)
            if not tris:
                print("  No triangles found - is this a valid STL?")
            else:
                done = False
                if o["curves"]:
                    done = S.smart_convert(tris, step, o["tol"], o["ang"], o["min"], 3.0, log=print)
                    if done:
                        res["mode"] = "Curved surfaces"
                    else:
                        print("  falling back to flat-facet STEP")
                if not done:
                    S.write_step(tris, step, base, True, 0.01)
                    res["mode"] = "Flat facets"
                res["ok"] = os.path.exists(step)
                if res["ok"] and o.get("fmt") == "sldprt":
                    make_sldprt(step, res)
        except SystemExit as e:
            print("  error: %s" % e)
        except Exception as e:
            print("  error: %s" % e)
    log = [l for l in buf.getvalue().splitlines() if l.strip() and "***" not in l and "\x1b" not in l]
    txt = "\n".join(log)
    m = re.search(r"wrote .*?faces: (\{.*?\})", txt)
    if m:
        try: res["faces"] = ast.literal_eval(m.group(1))
        except Exception: pass
    m = re.search(r"detected curved surfaces: (\{.*?\})", txt)
    if m:
        try: res["curved"] = ast.literal_eval(m.group(1))
        except Exception: pass
    m = re.search(r"faceted leftovers: ([\d.]+)%", txt)
    res["faceted_pct"] = float(m.group(1)) if m else None
    m = re.search(r"volume ([\d.]+) \(mesh ([\d.]+)\)", txt)
    if m:
        res["volume"], res["mesh_volume"] = float(m.group(1)), float(m.group(2))
    m = re.search(r"\((\d+) faces", txt)
    if m and not res["faces"]:
        res["faces"] = {"plane": int(m.group(1))}
    res["log"] = log
    res["seconds"] = round(time.time() - t0, 1)
    res["size"] = os.path.getsize(step) if res["ok"] else 0
    if res["ok"]:
        with LOCK:
            h = load_hist()
            h.append({k: res[k] for k in ("id", "name", "file", "mode", "tris", "faces", "seconds", "size", "fmt", "sldprt")})
            save_hist(h)
    return res


def sldprt_available():
    """(ok, reason). SolidWorks can only be driven by Python running on the Windows PC that has SolidWorks."""
    if os.name != "nt":
        import platform
        rel = platform.release().lower()
        if "microsoft" in rel or "wsl" in rel:
            where = "WSL (Linux inside Windows)"
        elif os.environ.get("CODESPACES"):
            where = "GitHub Codespaces (Linux in the cloud)"
        elif os.path.exists("/.dockerenv"):
            where = "a Docker container or hosted server"
        else:
            where = platform.system() or "a non-Windows system"
        return False, ("this dashboard is running on %s, not on your Windows PC, and SolidWorks cannot be reached from there. "
                       "Run the dashboard with Windows Python (PowerShell: python dashboard.py) on the PC that has SolidWorks, "
                       "or download the STEP file and open it in SolidWorks (File > Open)." % where)
    try:
        import win32com.client  # noqa
    except ImportError:
        return False, "the pywin32 library is missing. Run:  python -m pip install pywin32  then restart the dashboard."
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "SldWorks.Application"))
    except Exception:
        return False, ("SolidWorks was not found on this PC (SldWorks.Application is not registered). "
                       "Install or repair SolidWorks, or download the STEP file and open it in SolidWorks.")
    return True, ""


def make_sldprt(step, res):
    """Ask SolidWorks (on this PC) to open the STEP and save it as .SLDPRT."""
    sld = step[:-5] + ".SLDPRT"
    ok, why = sldprt_available()
    if not ok:
        print("  SLDPRT not created: " + why + " The STEP file is ready to download.")
        return
    pc = None
    try:
        import pythoncom
        pythoncom.CoInitialize()
        pc = pythoncom
        import win32com.client
        import step2sldprt
        sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = True
        step2sldprt.convert(sw, step, sld)
        res["sldprt"] = os.path.basename(sld)
        print("  SolidWorks part saved: " + os.path.basename(sld))
    except Exception as e:
        print("  SLDPRT failed: %s. The STEP file is ready to download." % e)
    finally:
        if pc:
            try: pc.CoUninitialize()
            except Exception: pass


MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "200")) * 1024 * 1024


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def authed(self):
        """Optional password: set the DASH_PASSWORD environment variable (user name can be anything)."""
        pw = os.environ.get("DASH_PASSWORD")
        if not pw:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                given = base64.b64decode(h[6:]).decode("utf-8").partition(":")[2]
                if hmac.compare_digest(given, pw):
                    return True
            except Exception:
                pass
        self.send(401, "Password required", "text/plain", {"WWW-Authenticate": 'Basic realm="STL dashboard"'})
        return False

    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.authed():
            return
        p = urlparse(self.path).path
        if p == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if p == "/api/env":
            ok, why = sldprt_available()
            return self.send(200, json.dumps({"sldprt": ok, "reason": why}))
        if p == "/api/history":
            return self.send(200, json.dumps(load_hist()[::-1]))
        if p.startswith("/download/"):
            fn = os.path.basename(unquote(p[len("/download/"):]))
            fp = os.path.join(OUT, fn)
            if os.path.isfile(fp) and fn.lower().endswith((".step", ".sldprt")):
                nice = re.sub(r"_\d{8}-\d{6}(\.[A-Za-z]+)$", r"\1", fn)
                return self.send(200, open(fp, "rb").read(), "application/octet-stream",
                                 {"Content-Disposition": 'attachment; filename="%s"' % nice})
        self.send(404, "not found", "text/plain")

    def do_POST(self):
        if not self.authed():
            return
        u = urlparse(self.path)
        if u.path != "/api/convert":
            return self.send(404, "not found", "text/plain")
        q = parse_qs(u.query)
        g = lambda k, d: q.get(k, [d])[0]
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_UPLOAD:
            return self.send(413, json.dumps({"error": "file too large"}))
        data = self.rfile.read(n)
        try:
            o = {"curves": g("curves", "1") == "1", "tol": float(g("tol", "0.0005")),
                 "ang": float(g("ang", "8")), "min": int(g("min", "10")),
                 "repair": g("repair", "1") == "1", "fmt": "sldprt" if g("fmt", "step") == "sldprt" else "step"}
        except ValueError:
            return self.send(400, json.dumps({"error": "bad options"}))
        self.send(200, json.dumps(run_job(g("name", "part.stl"), data, o)))


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>STL to STEP Converter</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
<script>try{var m=localStorage.getItem("theme")||"auto";if(m==="dark"||(m==="auto"&&matchMedia("(prefers-color-scheme:dark)").matches))document.documentElement.classList.add("dark")}catch(e){}</script>
<style>
:root {
  --card: #ffffff; --ring: #6366f1; --input: #d1d5db; --muted: #f3f4f6; --accent: #e0e7ff; --border: #d1d5db;
  --radius: 0.5rem; --chart-1: #6366f1; --chart-2: #4f46e5; --chart-3: #4338ca; --chart-4: #3730a3; --chart-5: #312e81;
  --popover: #ffffff; --primary: #6366f1; --sidebar: #f3f4f6; --font-mono: JetBrains Mono, monospace; --font-sans: Inter, sans-serif;
  --secondary: #e5e7eb; --background: #f8fafc; --font-serif: Merriweather, serif; --foreground: #1e293b; --destructive: #ef4444;
  --shadow-blur: 8px; --shadow-color: hsl(0 0% 0%); --sidebar-ring: #6366f1; --shadow-spread: -1px; --shadow-opacity: 0.1;
  --sidebar-accent: #e0e7ff; --sidebar-border: #d1d5db; --card-foreground: #1e293b; --shadow-offset-x: 0px; --shadow-offset-y: 4px;
  --sidebar-primary: #6366f1; --muted-foreground: #6b7280; --accent-foreground: #374151; --popover-foreground: #1e293b;
  --primary-foreground: #ffffff; --sidebar-foreground: #1e293b; --secondary-foreground: #374151; --destructive-foreground: #ffffff;
  --sidebar-accent-foreground: #374151; --sidebar-primary-foreground: #ffffff;
  --ok: #16a34a; --cd: #0f172a; --ct: #cbd5e1; color-scheme: light;
}
.dark {
  --card: #1e293b; --ring: #818cf8; --input: #4b5563; --muted: #152032; --accent: #374151; --border: #4b5563;
  --radius: 0.5rem; --chart-1: #818cf8; --chart-2: #6366f1; --chart-3: #4f46e5; --chart-4: #4338ca; --chart-5: #3730a3;
  --popover: #1e293b; --primary: #818cf8; --sidebar: #1e293b; --secondary: #2d3748; --background: #0f172a; --foreground: #e2e8f0;
  --destructive: #ef4444; --sidebar-ring: #818cf8; --sidebar-accent: #374151; --sidebar-border: #4b5563; --card-foreground: #e2e8f0;
  --sidebar-primary: #818cf8; --muted-foreground: #9ca3af; --accent-foreground: #d1d5db; --popover-foreground: #e2e8f0;
  --primary-foreground: #0f172a; --sidebar-foreground: #e2e8f0; --secondary-foreground: #d1d5db; --destructive-foreground: #0f172a;
  --sidebar-accent-foreground: #d1d5db; --sidebar-primary-foreground: #0f172a;
  --ok: #34d399; --cd: #0b1220; --ct: #cbd5e1; color-scheme: dark;
}
*{box-sizing:border-box}
body{margin:0;background:var(--background);color:var(--foreground);font:15px/1.5 var(--font-sans),system-ui,"Segoe UI",Roboto,sans-serif;transition:background .2s,color .2s}
header{padding:14px 24px;border-bottom:1px solid var(--border);background:var(--card);display:flex;align-items:center;gap:12px;flex-wrap:wrap}
header h1{font-size:18px;margin:0;font-weight:650}
header .sub{color:var(--muted-foreground);font-size:13px;flex:1;min-width:200px}
.theme{display:flex;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.theme button{background:transparent;color:var(--muted-foreground);border:0;border-radius:0;padding:6px 12px;font-size:12px;font-weight:600}
.theme button.on{background:var(--accent);color:var(--accent-foreground)}
main{max-width:1150px;margin:0 auto;padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:850px){main{grid-template-columns:1fr}}
.card{background:var(--card);color:var(--card-foreground);border:1px solid var(--border);border-radius:var(--radius);padding:16px;
 box-shadow:var(--shadow-offset-x) var(--shadow-offset-y) var(--shadow-blur) var(--shadow-spread) color-mix(in srgb,var(--shadow-color) calc(var(--shadow-opacity)*100%),transparent)}
.card h2{font-size:13px;margin:0 0 12px;color:var(--muted-foreground);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.full{grid-column:1/-1}
#drop{border:2px dashed var(--input);border-radius:var(--radius);padding:34px 16px;text-align:center;cursor:pointer;color:var(--muted-foreground);transition:.15s}
#drop.on,#drop:hover{border-color:var(--ring);color:var(--accent-foreground);background:var(--accent)}
#drop b{display:block;font-size:16px;color:var(--foreground);margin-bottom:4px}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:10px 0}
.row label{font-size:14px}.row small{color:var(--muted-foreground);display:block;font-size:12px}
input[type=number],select{padding:6px 8px;border:1px solid var(--input);border-radius:calc(var(--radius) - 2px);background:var(--background);color:var(--foreground);font:inherit;font-size:14px}
input[type=number]{width:90px}
input:focus,select:focus,button:focus-visible{outline:2px solid var(--ring);outline-offset:1px}
input[type=checkbox]{width:18px;height:18px;accent-color:var(--primary)}
button{background:var(--primary);color:var(--primary-foreground);border:0;border-radius:var(--radius);padding:10px 16px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}
button:hover:not(:disabled){filter:brightness(1.08)}
button:disabled{opacity:.5;cursor:not-allowed}
button.sec{background:transparent;color:var(--primary);border:1px solid var(--border)}
canvas{width:100%;height:280px;display:block;border-radius:var(--radius);background:var(--muted);cursor:grab}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.k{background:var(--muted);border-radius:var(--radius);padding:10px 12px}.k b{display:block;font-size:20px}.k span{font-size:12px;color:var(--muted-foreground)}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;margin:10px 0 6px;background:var(--muted)}
.leg{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:var(--muted-foreground)}.leg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}
pre{background:var(--cd);color:var(--ct);border-radius:var(--radius);padding:12px;margin:0;font:12.5px/1.5 var(--font-mono),ui-monospace,Consolas,monospace;max-height:190px;overflow:auto;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:13.5px}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--border)}th{color:var(--muted-foreground);font-weight:600;font-size:12px}
a.dl{color:var(--primary);text-decoration:none;font-weight:600}
.tag{padding:2px 8px;border-radius:99px;font-size:12px;background:var(--secondary);color:var(--secondary-foreground)}
.good{color:var(--ok)}.bad{color:var(--destructive)}.warn{color:var(--destructive)}
.msg{color:var(--muted-foreground);font-size:13px}
.seg{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.seg button{background:var(--muted);color:var(--foreground);border:2px solid var(--border);text-align:left;padding:10px 12px}
.seg button small{display:block;font-weight:400;color:var(--muted-foreground);font-size:12px;margin-top:2px}
.seg button.on{border-color:var(--primary);background:var(--accent);color:var(--accent-foreground)}
.seg button:disabled{opacity:.45}
.phead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}.phead h2{margin:0}
.pbtns{display:flex;align-items:center;gap:12px}.pbtns label{font-size:13px;color:var(--muted-foreground);display:flex;align-items:center;gap:6px;cursor:pointer}
button.sm{padding:5px 10px;font-size:12px}
canvas{touch-action:none}
#pback{position:fixed;inset:0;background:rgb(0 0 0/.55);backdrop-filter:blur(2px);z-index:40}
#pcard.big{position:fixed;inset:4vh 4vw;z-index:50;display:flex;flex-direction:column;box-shadow:0 20px 60px rgb(0 0 0/.35)}
#pcard.big canvas{flex:1;height:auto;min-height:0;cursor:grab}
#pcard.big .msg{margin-top:8px}
input[type=text],input[type=password]{padding:6px 8px;border:1px solid var(--border);border-radius:8px;background:var(--background);color:var(--foreground);font:inherit;font-size:13px}
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--primary);border-radius:50%;animation:s .8s linear infinite;vertical-align:-2px;margin-right:6px}@keyframes s{to{transform:rotate(360deg)}}
</style></head><body>
<header><h1>STL → STEP Converter</h1><div class="theme" id="theme"><button type="button" data-t="light">Light</button><button type="button" data-t="dark">Dark</button><button type="button" data-t="auto">Auto</button></div></header>
<main>
<section class="card"><h2>1 · Upload</h2>
<div id="drop"><b>Drop an STL here</b>or click to choose a file</div>
<input id="file" type="file" accept=".stl" hidden>
<div class="msg" id="fname" style="margin-top:10px">No file selected</div>
<h2 style="margin-top:18px">2 · Settings</h2>
<div class="row"><label>Recover curved surfaces<small>Holes, fillets, bosses, cones, domes</small></label><input type="checkbox" id="curves" checked></div>
<div class="row"><label>Repair mesh first<small>Closes holes and fixes flipped triangles so you get a solid</small></label><input type="checkbox" id="repair" checked></div>
<div class="row"><label>Smoothing level<small>Higher = merges more small triangles into bigger faces (less mesh lines, slightly less exact)</small></label>
<select id="preset"><option value="0">Exact</option><option value="1">Medium</option><option value="2">High</option></select></div>
<div class="row"><label>Fit tolerance<small>Fraction of part size. Raise for noisy / scanned meshes</small></label><input type="number" id="tol" value="0.0005" step="0.0001" min="0.00001"></div>
<div class="row"><label>Angle tolerance (°)<small>Max surface-normal error for a curved fit</small></label><input type="number" id="ang" value="8" step="1" min="1" max="30"></div>
<div class="row"><label>Min triangles per surface</label><input type="number" id="min" value="10" step="1" min="4"></div>
<button id="go" disabled>Convert to STEP</button>
</section>
<div id="pslot"><section class="card" id="pcard"><div class="phead"><h2>Preview</h2><div class="pbtns"><label id="autol" hidden><input type="checkbox" id="auto" checked> Auto-rotate</label><button type="button" class="sec sm" id="enl" disabled>⤢ Enlarge</button></div></div><canvas id="cv" width="560" height="280"></canvas><div class="msg" id="pinfo">Drag to rotate</div></section></div><div id="pback" hidden></div>
<section class="card full" id="res" hidden><h2>Result</h2>
<div id="state"></div>
<div class="kpis" id="kpis"></div>
<div class="msg" id="advice" style="margin:10px 0"></div>
<div class="bar" id="bar"></div><div class="leg" id="leg"></div>
<div style="margin:14px 0 10px;display:flex;gap:10px;flex-wrap:wrap" id="dls"></div>
<pre id="log"></pre></section>
<section class="card full"><h2>History</h2><table><thead><tr><th>File</th><th>Mode</th><th>Triangles</th><th>Faces</th><th>Time</th><th>Size</th><th></th></tr></thead><tbody id="hist"></tbody></table><div class="msg" id="hnone">No conversions yet.</div></section>
</main>
<script>
const $=id=>document.getElementById(id);let FILE=null,TRIS=null,rx=-0.6,ry=0.6;
const PRE=[[0.0005,8],[0.002,10],[0.005,15]];
$('preset').onchange=()=>{const p=PRE[+$('preset').value];$('tol').value=p[0];$('ang').value=p[1]};
const CV=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const colr=k=>({plane:CV('--muted-foreground'),cyl:CV('--chart-1'),cone:CV('--chart-3'),sphere:CV('--ok'),torus:CV('--chart-5')})[k]||'#888';
const NAME={plane:'Flat',cyl:'Cylinder',cone:'Cone',sphere:'Sphere',torus:'Rounded edge'};
const fmt=n=>n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':n;
const sz=b=>b>1e6?(b/1e6).toFixed(1)+' MB':Math.max(1,Math.round(b/1e3))+' KB';
function pick(f){if(!f)return;FILE=f;$('fname').textContent=f.name+' · '+sz(f.size);$('go').disabled=false;f.arrayBuffer().then(parse)}
$('drop').onclick=()=>$('file').click();$('file').onchange=e=>pick(e.target.files[0]);
['dragover','dragenter'].forEach(t=>$('drop').addEventListener(t,e=>{e.preventDefault();$('drop').classList.add('on')}));
['dragleave','drop'].forEach(t=>$('drop').addEventListener(t,e=>{e.preventDefault();$('drop').classList.remove('on')}));
$('drop').addEventListener('drop',e=>pick(e.dataTransfer.files[0]));
function parse(buf){const dv=new DataView(buf);let tris=[];
 const n=buf.byteLength>=84?dv.getUint32(80,true):0;
 if(84+n*50===buf.byteLength){for(let i=0;i<n;i++){const o=84+i*50+12;const t=[];for(let k=0;k<9;k++)t.push(dv.getFloat32(o+k*4,true));tris.push(t)}}
 else{const tx=new TextDecoder().decode(buf);const re=/vertex\s+(\S+)\s+(\S+)\s+(\S+)/g;let m,v=[];while((m=re.exec(tx)))v.push(+m[1],+m[2],+m[3]);for(let i=0;i+8<v.length;i+=9)tris.push(v.slice(i,i+9))}
 if(!tris.length){$('pinfo').textContent='Could not read triangles';TRIS=null;$('enl').disabled=true;return}
 let mn=[1e30,1e30,1e30],mx=[-1e30,-1e30,-1e30];
 for(const t of tris)for(let k=0;k<9;k++){const a=k%3;mn[a]=Math.min(mn[a],t[k]);mx[a]=Math.max(mx[a],t[k])}
 const c=mn.map((v,i)=>(v+mx[i])/2),s=2/Math.max(mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2],1e-9);
 const step=Math.max(1,Math.ceil(tris.length/7000));
 TRIS=tris.filter((_,i)=>i%step===0).map(t=>t.map((v,k)=>(v-c[k%3])*s));
 $('pinfo').textContent=fmt(tris.length)+' triangles'+(step>1?' (preview shows a sample)':'')+' · drag to rotate · Enlarge to auto-rotate';$('enl').disabled=false;draw()}
function draw(){const cv=$('cv'),g=cv.getContext('2d'),W=cv.width,Hh=cv.height;g.clearRect(0,0,W,Hh);if(!TRIS)return;
 const cx=Math.cos(rx),sx=Math.sin(rx),cy=Math.cos(ry),sy=Math.sin(ry),sc=Math.min(W,Hh)*0.36;
 const P=[];for(const t of TRIS){const v=[];for(let k=0;k<3;k++){let x=t[k*3],y=t[k*3+1],z=t[k*3+2];
  let x1=x*cy+z*sy,z1=-x*sy+z*cy;let y2=y*cx-z1*sx,z2=y*sx+z1*cx;v.push([W/2+x1*sc,Hh/2-y2*sc,z2])}
  const ux=v[1][0]-v[0][0],uy=v[1][1]-v[0][1],vx=v[2][0]-v[0][0],vy=v[2][1]-v[0][1];
  P.push({v,z:(v[0][2]+v[1][2]+v[2][2])/3,f:Math.abs(ux*vy-uy*vx)})}
 P.sort((a,b)=>a.z-b.z);const dark=document.documentElement.classList.contains('dark');
 for(const p of P){const l=Math.max(0.25,Math.min(1,0.35+p.f/Math.max(1,(p.v[0][0]-p.v[1][0])**2+(p.v[0][1]-p.v[1][1])**2)*0.5+(p.z+1)*0.25));
  const b=dark?Math.round(70+150*l):Math.round(80+130*l);g.fillStyle='rgb('+Math.round(b*0.55)+','+Math.round(b*0.72)+','+b+')';g.strokeStyle=g.fillStyle;
  g.beginPath();g.moveTo(p.v[0][0],p.v[0][1]);g.lineTo(p.v[1][0],p.v[1][1]);g.lineTo(p.v[2][0],p.v[2][1]);g.closePath();g.fill();g.stroke()}}
let drag=null;const cv=$('cv');cv.onpointerdown=e=>{drag=[e.clientX,e.clientY];cv.setPointerCapture(e.pointerId)};
cv.onpointerup=()=>drag=null;cv.onpointermove=e=>{if(!drag)return;ry+=(e.clientX-drag[0])*0.01;rx+=(e.clientY-drag[1])*0.01;drag=[e.clientX,e.clientY];draw()};
let BIG=false,raf=0,lastT=0,PINFO='';
if(matchMedia('(prefers-reduced-motion:reduce)').matches)$('auto').checked=false;
function fit(){const r=cv.getBoundingClientRect(),d=Math.min(window.devicePixelRatio||1,2);cv.width=Math.max(300,Math.round(r.width*d));cv.height=Math.max(150,Math.round(r.height*d));draw()}
function spin(t){if(!BIG){raf=0;return}
 if(!lastT)lastT=t;if($('auto').checked&&!drag&&TRIS){const dt=Math.min(64,t-lastT);if(dt>=28){ry+=0.0006*dt;lastT=t;draw()}}else lastT=t;
 raf=requestAnimationFrame(spin)}
function setBig(on){if(on&&!TRIS)return;if(on===BIG)return;BIG=on;const c=$('pcard');
 $('pslot').style.height=on?c.offsetHeight+'px':'';
 c.classList.toggle('big',on);$('pback').hidden=!on;$('autol').hidden=!on;$('enl').textContent=on?'✕ Close':'⤢ Enlarge';
 document.body.style.overflow=on?'hidden':'';
 if(on){PINFO=$('pinfo').textContent;$('pinfo').textContent='Drag to rotate · Esc or click outside to close'}else{$('pinfo').textContent=PINFO||'Drag to rotate'}
 requestAnimationFrame(()=>{fit();if(on&&!raf){lastT=0;raf=requestAnimationFrame(spin)}})}
$('enl').onclick=()=>setBig(!BIG);$('pback').onclick=()=>setBig(false);cv.ondblclick=()=>setBig(!BIG);
addEventListener('keydown',e=>{if(e.key==='Escape'&&BIG)setBig(false)});addEventListener('resize',fit);fit();
$('go').onclick=async()=>{if(!FILE)return;$('go').disabled=true;$('res').hidden=false;
 $('state').innerHTML='<span class="spin"></span>Converting… large meshes can take a minute';$('kpis').innerHTML='';$('advice').innerHTML='';$('bar').innerHTML='';$('leg').innerHTML='';$('log').textContent='';$('dls').innerHTML='';
 const q=new URLSearchParams({name:FILE.name,curves:$('curves').checked?1:0,repair:$('repair').checked?1:0,tol:$('tol').value,ang:$('ang').value,min:$('min').value});
 try{const r=await fetch('/api/convert?'+q,{method:'POST',body:FILE});const d=await r.json();show(d);loadHist()}
 catch(e){$('state').innerHTML='<b class="bad">Could not reach the converter. Is dashboard.py still running?</b>'}
 $('go').disabled=false};
let LAST=null;
function show(d){LAST=d;let st=d.ok?'<b class="good">Done</b> · '+d.mode+' · '+d.seconds+' s':'<b class="bad">Conversion failed</b> · see log';
 $('state').innerHTML=st;
 $('log').textContent=(d.log||[]).join('\n');
 if(!d.ok)return;
 const tot=Object.values(d.faces).reduce((a,b)=>a+b,0),cur=Object.values(d.curved||{}).reduce((a,b)=>a+b,0);
 const kp=[['Triangles in',fmt(d.tris)],['Faces out',fmt(tot)],['Curved surfaces',cur||'0'],['STEP size',sz(d.size)]];
 if(d.faceted_pct!=null)kp.push(['Faceted area',d.faceted_pct.toFixed(1)+'%']);
 $('advice').innerHTML=d.faceted_pct==null?'':d.faceted_pct<1?'<b class="good">Clean:</b> almost no mesh lines will show in SolidWorks.':'<b class="bad">'+d.faceted_pct.toFixed(1)+'% of the surface is still small flat facets</b> and will show mesh lines. Try Smoothing level Medium or High. If it stays high, those areas are freeform (organic) and need SolidWorks Surface Wizard or a NURBS tool.';
 if(d.volume)kp.push(['Volume match',(100-Math.abs(d.volume-d.mesh_volume)/d.mesh_volume*100).toFixed(2)+'%']);
 $('kpis').innerHTML=kp.map(a=>'<div class="k"><b>'+a[1]+'</b><span>'+a[0]+'</span></div>').join('');
 if(tot){$('bar').innerHTML=Object.entries(d.faces).map(([k,v])=>'<div title="'+k+'" style="width:'+v/tot*100+'%;background:'+colr(k)+'"></div>').join('');
  $('leg').innerHTML=Object.entries(d.faces).map(([k,v])=>'<span><i style="background:'+colr(k)+'"></i>'+(NAME[k]||k)+' '+v+'</span>').join('')}
 $('dls').innerHTML='<a class="dl" href="/download/'+d.file+'"><button>Download STEP</button></a>''}
async function loadHist(){const h=await (await fetch('/api/history')).json();$('hnone').style.display=h.length?'none':'';
 $('hist').innerHTML=h.map(x=>{const tot=Object.values(x.faces||{}).reduce((a,b)=>a+b,0);return '<tr><td>'+x.name+'</td><td><span class="tag">'+x.mode+'</span></td><td>'+fmt(x.tris)+'</td><td>'+fmt(tot)+'</td><td>'+x.seconds+' s</td><td>'+sz(x.size)+'</td><td><a class="dl" href="/download/'+x.file+'">STEP</a>'+'</td></tr>'}).join('')}
function applyTheme(){let m='auto';try{m=localStorage.getItem('theme')||'auto'}catch(e){}
 const dark=m==='dark'||(m==='auto'&&matchMedia('(prefers-color-scheme:dark)').matches);
 document.documentElement.classList.toggle('dark',dark);
 document.querySelectorAll('#theme button').forEach(b=>b.classList.toggle('on',b.dataset.t===m));
 draw();if(LAST&&LAST.ok)show(LAST)}
document.querySelectorAll('#theme button').forEach(b=>b.onclick=()=>{try{localStorage.setItem('theme',b.dataset.t)}catch(e){}applyTheme()});
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',applyTheme);
applyTheme();
loadHist();
</script></body></html>'''


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    fixed = "PORT" in os.environ
    port = int(os.environ.get("PORT", 8000))
    srv = None
    while srv is None and port < 8020 + (100000 if fixed else 0):
        try:
            srv = ThreadingHTTPServer((host, port), H)
        except OSError:
            if fixed:
                sys.exit("Port %d is busy." % port)
            port += 1
    if srv is None:
        sys.exit("No free port found.")
    url = "http://localhost:%d" % port
    print("STL dashboard version 7 running on %s:%d   (press Ctrl+C to stop)" % (host, port))
    if host == "127.0.0.1" and not os.environ.get("NO_BROWSER"):
        print("Open " + url)
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    if host != "127.0.0.1" and not os.environ.get("DASH_PASSWORD"):
        print("WARNING: no DASH_PASSWORD set. Anyone who can reach this address can use the dashboard.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
