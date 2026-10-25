#!/usr/bin/env python3
"""
sw_bridge.py - SolidWorks bridge.

SolidWorks Part files (.SLDPRT) can only be written by SolidWorks itself. This tiny local server runs on the
Windows PC that has SolidWorks. A dashboard (even one hosted in the cloud) sends it a STEP file through your
browser, SolidWorks on this PC saves the .SLDPRT, and the browser downloads it.

    pip install pywin32
    python sw_bridge.py

It prints an address and a token. Paste both into the dashboard (SolidWorks bridge box) once.

Safety: it only listens on this PC (127.0.0.1) and every conversion needs the token, which web pages cannot guess.
"""
import argparse, json, os, re, secrets, shutil, sys, tempfile, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LOCK = threading.Lock()                     # SolidWorks handles one job at a time
CONFIG = {"token": "", "max_bytes": 300 * 1024 * 1024}
VERSION = 1


def solidworks_ready():
    if os.name != "nt":
        return False, "the bridge must run on the Windows PC that has SolidWorks (this is not Windows)."
    try:
        import win32com.client  # noqa
    except ImportError:
        return False, "the pywin32 library is missing. Run:  python -m pip install pywin32"
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "SldWorks.Application"))
    except Exception:
        return False, "SolidWorks was not found on this PC (SldWorks.Application is not registered)."
    return True, ""


def convert_step_bytes(data, name):
    """STEP bytes in, SLDPRT bytes out (SolidWorks does the work)."""
    ok, why = solidworks_ready()
    if not ok:
        raise RuntimeError(why)
    import pythoncom
    import win32com.client
    import step2sldprt
    td = tempfile.mkdtemp(prefix="swbridge_")
    try:
        sp = os.path.join(td, name + ".step")
        out = os.path.join(td, name + ".SLDPRT")
        with open(sp, "wb") as f:
            f.write(data)
        pythoncom.CoInitialize()
        try:
            sw = win32com.client.Dispatch("SldWorks.Application")
            sw.Visible = True
            step2sldprt.convert(sw, sp, out)
        finally:
            pythoncom.CoUninitialize()
        with open(out, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(td, ignore_errors=True)


def safe_name(raw):
    base = os.path.basename(raw or "part.step")
    stem, ext = os.path.splitext(base)
    if ext.lower() not in (".step", ".stp"):
        return None
    return re.sub(r"[^A-Za-z0-9._-]", "_", stem) or "part"


class H(BaseHTTPRequestHandler):
    server_version = "swbridge/%d" % VERSION

    def log_message(self, fmt, *a):
        print("  " + (fmt % a))

    def cors(self):
        o = self.headers.get("Origin")
        if o:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "X-Bridge-Token, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
        self.send_header("Access-Control-Max-Age", "600")

    def reply(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if urlparse(self.path).path == "/ping":
            ok, why = solidworks_ready()
            return self.reply(200, {"bridge": True, "version": VERSION, "solidworks": ok, "reason": why})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/convert":
            return self.reply(404, {"error": "not found"})
        tok = self.headers.get("X-Bridge-Token", "")
        if not CONFIG["token"] or not secrets.compare_digest(tok.encode(), CONFIG["token"].encode()):
            return self.reply(401, {"error": "wrong or missing token. Copy it from the bridge window."})
        name = safe_name(parse_qs(u.query).get("name", ["part.step"])[0])
        if name is None:
            return self.reply(400, {"error": "only .step / .stp files are accepted"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return self.reply(400, {"error": "empty upload"})
        if n > CONFIG["max_bytes"]:
            return self.reply(413, {"error": "file too large (limit %d MB)" % (CONFIG["max_bytes"] // 1048576)})
        data = self.rfile.read(n)
        if not data.lstrip()[:11].upper().startswith(b"ISO-10303-2"):
            return self.reply(400, {"error": "this does not look like a STEP file"})
        print("  converting %s (%d KB) with SolidWorks ..." % (name, n // 1024))
        try:
            with LOCK:
                out = convert_step_bytes(data, name)
        except Exception as e:
            print("  FAILED: %s" % e)
            return self.reply(500, {"error": str(e)})
        print("  done: %s.SLDPRT (%d KB)" % (name, len(out) // 1024))
        self.reply(200, out, "application/octet-stream", {"Content-Disposition": 'attachment; filename="%s.SLDPRT"' % name})


def load_token(given):
    if given:
        return given
    if os.environ.get("SW_BRIDGE_TOKEN"):
        return os.environ["SW_BRIDGE_TOKEN"]
    path = os.path.join(os.path.expanduser("~"), ".sw_bridge_token")
    try:
        t = open(path).read().strip()
        if t:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(9)
    try:
        open(path, "w").write(t)
    except OSError:
        pass
    return t


def main():
    ap = argparse.ArgumentParser(description="SolidWorks bridge: makes .SLDPRT files for a dashboard.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="leave as 127.0.0.1 unless you know why you change it")
    ap.add_argument("--token", default="")
    ap.add_argument("--max-mb", type=int, default=300)
    a = ap.parse_args()
    CONFIG["token"] = load_token(a.token)
    CONFIG["max_bytes"] = a.max_mb * 1024 * 1024
    srv = ThreadingHTTPServer((a.host, a.port), H)
    ok, why = solidworks_ready()
    print("=" * 62)
    print(" SolidWorks bridge is running")
    print("   Address : http://%s:%d" % (a.host, a.port))
    print("   Token   : %s" % CONFIG["token"])
    print(" Paste both into the dashboard's 'SolidWorks bridge' box.")
    print(" SolidWorks: %s" % ("ready" if ok else "NOT READY - " + why))
    print(" Keep this window open. Press Ctrl+C to stop.")
    print("=" * 62)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
