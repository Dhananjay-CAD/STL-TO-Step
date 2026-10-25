#!/usr/bin/env python3
"""
docs/make_gifs.py - regenerate the README animations.

The mesh, surface detection, repair and numbers in the GIFs come from the real converter
running on examples/sample_part.stl. The dashboard and terminal GIFs are drawn illustrations
(a simplified layout, not screen recordings).

    pip install numpy cadquery-ocp pillow
    python docs/make_gifs.py
"""
import math, os, sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import stl2step as S

SAMPLE = os.path.join(ROOT, "examples", "sample_part.stl")
CAD_VOLUME = 62677.38          # volume of the CAD model the sample STL was exported from

# ---------- look ----------
BG = (248, 250, 252); INK = (30, 41, 59); MUTED = (107, 114, 128); PRIMARY = (99, 102, 241)
NEUTRAL = (210, 219, 231); RED = (239, 68, 68); GREEN = (16, 185, 129); PURPLE = (168, 85, 247)
TYPE_COL = {"plane": (178, 190, 208), "cyl": (99, 102, 241), "torus": (236, 72, 153),
            "cone": (245, 158, 11), "sphere": (16, 185, 129)}
TYPE_NAME = {"plane": "Flat", "cyl": "Cylinder", "torus": "Rounded edge", "cone": "Cone", "sphere": "Sphere"}
FD = "/usr/share/fonts/truetype/dejavu/"
def font(sz, bold=False, mono=False):
    name = "DejaVuSansMono.ttf" if mono else ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(FD + name, sz)
    except Exception:
        return ImageFont.load_default()


# ---------- load + analyse the sample with the real converter ----------
def analyse(tris):
    P, F, N, A, diag = S._prep(np, tris)
    nbr, closed = S._adjacency(np, F, len(P))
    X = P[F].mean(1)
    tol = diag * 5e-4
    curved = S.detect_primitives(np, P, F, N, A, X, nbr, diag, tol, 8.0, 10)
    out = S.build_brep(np, P, F, N, A, X, nbr, curved, diag, tol, 3.0, lambda *a: None)
    regions = out[3]
    vol = out[0][1] if out[0] else None
    lab = -np.ones(len(F), dtype=np.int64)
    for i, r in enumerate(regions):
        lab[r["tris"]] = i
    return dict(P=P, F=F, N=N, A=A, X=X, nbr=nbr, regions=regions, lab=lab, vol=vol, diag=diag)


def smooth_normals(d):
    N, X = d["N"], d["X"]
    Ns = N.copy()
    for r in d["regions"]:
        t, pr = r["tris"], r["prim"]
        ty = pr["type"]
        if ty == "plane":
            v = np.tile(pr["n"], (len(t), 1))
        elif ty == "cyl":
            w = X[t] - pr["c"]; w = w - (w @ pr["a"])[:, None] * pr["a"]
            v = w / np.maximum(np.linalg.norm(w, axis=1), 1e-12)[:, None]
        elif ty == "sphere":
            w = X[t] - pr["c"]; v = w / np.maximum(np.linalg.norm(w, axis=1), 1e-12)[:, None]
        elif ty == "torus":
            v = S._torus_normal(np, pr, X[t])
        else:  # cone
            w = X[t] - pr["c"]; s = w @ pr["a"]; rad = w - s[:, None] * pr["a"]
            rad = rad / np.maximum(np.linalg.norm(rad, axis=1), 1e-12)[:, None]
            v = rad * math.cos(pr["alpha"]) - pr["a"] * math.sin(pr["alpha"]) * np.sign(s.mean() or 1)
        sgn = np.sign((v * N[t]).sum(1)); sgn[sgn == 0] = 1
        Ns[t] = v * sgn[:, None]
    return Ns


# ---------- tiny software renderer ----------
class Scene:
    def __init__(self, P, F, N):
        self.F, self.N = F, N
        c = (P.max(0) + P.min(0)) / 2
        self.Pc = (P - c) / ((P.max(0) - P.min(0)).max() / 2)


def render(sc, yaw, el, size, col, nrm=None, outline=None, lines=(), ss=2, bg=BG, zoom=1.0, edge_col=(71, 85, 105), show_all=None):
    W, H = size
    ca, sa = math.cos(yaw), math.sin(yaw)
    R = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])
    p = sc.Pc @ R.T
    cam = np.array([0, -math.cos(el), math.sin(el)])
    up = np.array([0, math.sin(el), math.cos(el)])
    scale = min(W, H) * 0.47 * zoom * ss
    sx = W * ss / 2 + p[:, 0] * scale
    sy = H * ss / 2 - (p @ up) * scale
    dep = p @ cam
    F = sc.F
    nf_ = (sc.N if nrm is None else nrm)
    facing = (sc.N @ R.T) @ cam > 0.0
    if show_all is not None:
        facing = facing | show_all
    idx = np.nonzero(facing)[0]
    idx = idx[np.argsort(dep[F[idx]].mean(1))]
    L = cam * 0.75 + np.array([-0.55, 0, 0]) + up * 0.45
    L /= np.linalg.norm(L)
    shade = 0.55 + 0.45 * np.clip((nf_ @ R.T) @ L, 0, 1)
    img = Image.new("RGB", (W * ss, H * ss), bg)
    dr = ImageDraw.Draw(img)
    xy = np.stack([sx[F], sy[F]], axis=2)             # (nf,3,2)
    cols = np.clip(col * shade[:, None], 0, 255).astype(np.uint8)
    for t in idx:
        pts = [tuple(v) for v in xy[t].tolist()]
        oc = edge_col if (outline is None or outline[t]) and outline is not False else None
        dr.polygon(pts, fill=tuple(cols[t].tolist()), outline=oc if outline is not None else None)
        for mask, color, width in lines:
            m = mask[t]
            for k in range(3):
                if m[k]:
                    dr.line([pts[k], pts[(k + 1) % 3]], fill=color, width=max(1, int(width * ss)))
    return img.resize((W, H), Image.LANCZOS)


def text(dr, xy, s, f, fill=INK, anchor="la"):
    dr.text(xy, s, font=f, fill=fill, anchor=anchor)


def save_gif(frames, path, durations, colors=128):
    # one shared palette so colours do not flicker
    k = max(1, len(frames) // 8)
    sample = frames[::k][:8]
    w, h = sample[0].size
    sheet = Image.new("RGB", (w * len(sample), h))
    for i, f in enumerate(sample):
        sheet.paste(f, (i * w, 0))
    pal = sheet.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print("  %-22s %3d frames  %5.0f KB" % (os.path.basename(path), len(frames), os.path.getsize(path) / 1024))


def type_colors(d, only=None):
    col = np.tile(np.array(NEUTRAL, float), (len(d["F"]), 1))
    for i, r in enumerate(d["regions"]):
        if only is None or i in only:
            col[r["tris"]] = TYPE_COL[r["prim"]["type"]]
    return col


def boundary_mask(d):
    nbr, lab = d["nbr"], d["lab"]
    return (nbr >= 0) & (lab[np.where(nbr >= 0, nbr, 0)] != lab[:, None])


def header(img, title, sub=None, h=54):
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, img.width, h], fill=(255, 255, 255))
    dr.line([0, h, img.width, h], fill=(226, 232, 240), width=1)
    text(dr, (18, 10), title, font(17, True))
    if sub:
        text(dr, (18, 33), sub, font(12), MUTED)
    return dr


# ---------- GIF 1: before / after ----------
def gif_before_after(d, out):
    sc = Scene(d["P"], d["F"], d["N"]); Ns = smooth_normals(d)
    W, H = 900, 450; PW = W // 2; PH = H - 96
    grey = np.tile(np.array((176, 190, 208), float), (len(d["F"]), 1))
    colr = type_colors(d); bmask = boundary_mask(d)
    frames = []; n = 48
    for i in range(n):
        yaw = 2 * math.pi * i / n
        a = render(sc, yaw, 0.55, (PW, PH), grey, outline=np.ones(len(d["F"]), bool), edge_col=(100, 116, 139))
        b = render(sc, yaw, 0.55, (PW, PH), colr, nrm=Ns, outline=None, lines=[(bmask, (30, 41, 59), 1.1)])
        im = Image.new("RGB", (W, H), BG)
        header(im, "STL mesh  →  STEP solid", "Same part, rotating. Left: what you start with. Right: what you get.")
        im.paste(a, (0, 70)); im.paste(b, (PW, 70))
        dr = ImageDraw.Draw(im)
        dr.line([PW, 70, PW, 70 + PH], fill=(226, 232, 240), width=2)
        text(dr, (PW // 2, H - 24), "%s triangles, every edge shows as a mesh line" % format(len(d["F"]), ","), font(14, True), RED, "mm")
        text(dr, (PW + PW // 2, H - 24), "%d smooth faces, no mesh lines" % len(d["regions"]), font(14, True), GREEN, "mm")
        frames.append(im)
    save_gif(frames, out, [70] * n)


# ---------- GIF 2: pipeline ----------
def gif_pipeline(d, out):
    sc = Scene(d["P"], d["F"], d["N"]); Ns = smooth_normals(d)
    W, H = 760, 520; PH = 360
    nfaces = len(d["F"]); allT = np.ones(nfaces, bool)
    grey = np.tile(np.array((176, 190, 208), float), (nfaces, 1))
    neutral_s = np.tile(np.array((214, 222, 233), float), (nfaces, 1))
    bmask = boundary_mask(d)
    regs = d["regions"]
    curved_idx = [i for i, r in enumerate(regs) if r["prim"]["type"] != "plane"]
    curved_idx.sort(key=lambda i: -d["A"][regs[i]["tris"]].sum())
    plane_idx = [i for i, r in enumerate(regs) if r["prim"]["type"] == "plane"]
    kinds = {}
    for i in curved_idx:
        kinds[regs[i]["prim"]["type"]] = kinds.get(regs[i]["prim"]["type"], 0) + 1
    steps = [("1", "Read the STL", "%s triangles, only flat pieces" % format(nfaces, ",")),
             ("2", "Find the curved surfaces", "cylinders, rounded edges, cones, spheres"),
             ("3", "Merge flat triangles", "thousands of triangles become a few flat faces"),
             ("4", "Rebuild exact edges", "true circles and straight lines (dark)"),
             ("5", "Sew into a STEP solid", "volume %.1f mm³ (CAD original %.1f)" % (d["vol"], CAD_VOLUME))]
    per = 14; frames = []; total = per * len(steps)
    for s in range(len(steps)):
        for k in range(per):
            fi = s * per + k
            yaw = 2 * math.pi * fi / total * 1.0
            if s == 0:
                im_p = render(sc, yaw, 0.55, (W, PH), grey, outline=allT, edge_col=(100, 116, 139))
            elif s == 1:
                m = int(math.ceil((k + 1) / per * len(curved_idx)))
                rev = set(curved_idx[:m]); col = grey.copy(); outl = np.ones(nfaces, bool); nr = d["N"].copy()
                for i in rev:
                    t = regs[i]["tris"]; col[t] = TYPE_COL[regs[i]["prim"]["type"]]; outl[t] = False; nr[t] = Ns[t]
                im_p = render(sc, yaw, 0.55, (W, PH), col, nrm=nr, outline=outl, edge_col=(100, 116, 139))
            elif s == 2:
                m = int(math.ceil((k + 1) / per * len(plane_idx)))
                rev = set(curved_idx) | set(plane_idx[:m]); col = grey.copy(); outl = np.ones(nfaces, bool); nr = d["N"].copy()
                for i in rev:
                    t = regs[i]["tris"]; col[t] = TYPE_COL[regs[i]["prim"]["type"]]; outl[t] = False; nr[t] = Ns[t]
                im_p = render(sc, yaw, 0.55, (W, PH), col, nrm=nr, outline=outl, edge_col=(100, 116, 139))
            elif s == 3:
                w = min(1.0, (k + 1) / (per * 0.6))
                im_p = render(sc, yaw, 0.55, (W, PH), neutral_s, nrm=Ns, outline=None, lines=[(bmask, (79, 70, 229), 0.8 + 1.6 * w)])
            else:
                im_p = render(sc, yaw, 0.55, (W, PH), type_colors(d), nrm=Ns, outline=None, lines=[(bmask, (30, 41, 59), 1.1)])
            im = Image.new("RGB", (W, H), BG)
            header(im, "Step %s of 5: %s" % (steps[s][0], steps[s][1]), steps[s][2], h=56)
            im.paste(im_p, (0, 62))
            dr = ImageDraw.Draw(im)
            for j in range(len(steps)):
                cx = W // 2 - 2 * 34 + j * 34
                dr.ellipse([cx - 7, H - 34, cx + 7, H - 20], fill=PRIMARY if j <= s else (203, 213, 225))
            if s >= 1:
                x0 = 18
                for ty in ("cyl", "torus", "cone", "plane"):
                    if ty == "plane" and s < 2:
                        continue
                    if ty != "plane" and ty not in kinds:
                        continue
                    dr.rounded_rectangle([x0, 74, x0 + 12, 86], 3, fill=TYPE_COL[ty])
                    text(dr, (x0 + 18, 72), TYPE_NAME[ty], font(12), INK)
                    x0 += 28 + int(dr.textlength(TYPE_NAME[ty], font=font(12))) + 8
            frames.append(im)
    save_gif(frames, out, [90] * (len(frames)))


# ---------- GIF 3: repair ----------
def gif_repair(tris, out):
    rng = np.random.default_rng(3)
    P0, F0, N0, A0, diag = S._prep(np, tris)
    # damage: remove the biggest triangles on the top face (small gap) and flip 6 percent of the rest
    top = np.nonzero((np.abs(P0[F0][:, :, 2] - P0[:, 2].max()).max(1) < 1e-3) | ((N0[:, 2] > 0.999) & (P0[F0][:, :, 2].min(1) > P0[:, 2].max() * 0.95)))[0]
    zmid = np.median(P0[F0][:, :, 2].mean(1))
    cand = np.nonzero(N0[:, 2] > 0.999)[0]
    cand = cand[np.argsort(-A0[cand])][:3]
    keep = np.ones(len(F0), bool); keep[cand[:2]] = False
    Fd = F0[keep].copy()
    ctr = [r for r in analyse(tris)['regions'] if r['prim']['type'] == 'torus'][0]['prim']['c']
    Xk = P0[F0[keep]].mean(1)
    flip = np.linalg.norm(Xk - ctr, axis=1) < 11.0
    Fd[flip] = Fd[flip][:, [0, 2, 1]]
    dam = [tuple(map(tuple, t)) for t in P0[Fd].tolist()]
    key = lambda t: tuple(sorted(tuple(np.round(v, 5)) for v in t))
    flipkeys = {key(t) for t, f in zip(dam, flip) if f}
    rep = S.repair_tris(dam, log=lambda *a: None)
    damkeys = {key(t) for t in dam}
    def pack(tr):
        arr = np.array(tr, float); Pp = arr.reshape(-1, 3)
        Fp = np.arange(len(Pp)).reshape(-1, 3)
        Nn = np.cross(arr[:, 1] - arr[:, 0], arr[:, 2] - arr[:, 0]); Nn /= np.maximum(np.linalg.norm(Nn, axis=1), 1e-12)[:, None]
        return Pp, Fp, Nn
    Pd, Fdd, Nd = pack(dam); Pr, Fr, Nr = pack(rep)
    # damaged mesh: shared-vertex adjacency for open edges
    Pw, Fw, Nw, Aw, dg = S._prep(np, dam)
    nbr_d, _ = S._adjacency(np, Fw, len(Pw))
    Pw2, Fw2, Nw2, Aw2, dg2 = S._prep(np, rep)
    sc_d = Scene(Pw, Fw, Nw); sc_r = Scene(Pw2, Fw2, Nw2)
    # keep both views on the same scale: reuse the repaired mesh bounding box
    sc_d.Pc = (Pw - (Pw2.max(0) + Pw2.min(0)) / 2) / ((Pw2.max(0) - Pw2.min(0)).max() / 2)
    kd = [key(tuple(map(tuple, t))) for t in Pw[Fw].tolist()]
    flipM = np.array([k in flipkeys for k in kd])
    colD = np.tile(np.array((176, 190, 208), float), (len(Fw), 1))
    for i, k in enumerate(kd):
        if k in flipkeys:
            colD[i] = PURPLE
    openM = nbr_d < 0
    kr = [key(tuple(map(tuple, t))) for t in Pw2[Fw2].tolist()]
    colR = np.tile(np.array((176, 190, 208), float), (len(Fw2), 1))
    for i, k in enumerate(kr):
        if k not in damkeys:
            colR[i] = GREEN
    W, H = 760, 460; PH = 340; frames = []; n = 40
    for i in range(n):
        yaw = 0.5 + 2 * math.pi * i / n
        stage = 0 if i < n // 2 else 1
        if stage == 0:
            ip = render(sc_d, yaw, 0.7, (W, PH), colD, outline=np.ones(len(Fw), bool), edge_col=(100, 116, 139), lines=[(openM, RED, 2.6)], show_all=flipM)
            t1, t2 = "Before: a gap and flipped triangles", "Red = open edge (can only make a surface). Purple = triangles facing the wrong way."
        else:
            ip = render(sc_r, yaw, 0.7, (W, PH), colR, outline=np.ones(len(Fw2), bool), edge_col=(100, 116, 139))
            t1, t2 = "After repair: a closed solid", "Green = triangles added to close the gap. Flipped triangles turned back."
        im = Image.new("RGB", (W, H), BG)
        header(im, t1, t2, h=56)
        im.paste(ip, (0, 70))
        dr = ImageDraw.Draw(im)
        for j in range(2):
            cx = W // 2 - 17 + j * 34
            dr.ellipse([cx - 7, H - 30, cx + 7, H - 16], fill=PRIMARY if j == stage else (203, 213, 225))
        frames.append(im)
    save_gif(frames, out, [110] * n)


# ---------- GIF 4: curve fit ----------
def gif_curve_fit(d, out):
    P = d["P"]
    # ring of vertices of the first hole wall (real vertices from the sample)
    ring = [r for r in d["regions"] if r["prim"]["type"] == "cyl"][0]
    pr = ring["prim"]; V = P[np.unique(d["F"][ring["tris"]])]
    z0 = V[:, 2].min(); V = V[np.abs(V[:, 2] - z0) < 1e-3]
    u, v = S._basis(np, pr["a"]); ang = np.arctan2((V - pr["c"]) @ v, (V - pr["c"]) @ u)
    V = V[np.argsort(ang)]; ang = np.sort(ang)
    step = max(1, len(V) // 16); Vs = V[::step][:16]
    c = S._circle3d(np, V, d["diag"] * 5e-4, d["diag"])
    R = c[2] if c else pr["R"]
    W, H = 700, 400; cx, cy = 190, 225; sc = 27.0
    to2 = lambda Q: [(cx + ((q - pr["c"]) @ u) * sc, cy - ((q - pr["c"]) @ v) * sc) for q in Q]
    poly = to2(Vs); frames = []; dur = []
    def base(title, sub):
        im = Image.new("RGB", (W, H), BG); header(im, title, sub); return im, ImageDraw.Draw(im)
    for i in range(12):                                           # polygon appears
        im, dr = base("A hole in an STL is a polygon", "%d straight edges in this simplified view (the real file has %d)" % (len(Vs), len(V)))
        m = int(len(poly) * (i + 1) / 12)
        pts = poly[:m + 1] if m < len(poly) else poly + [poly[0]]
        if len(pts) > 1: dr.line(pts, fill=(100, 116, 139), width=3)
        for p in poly[:m]: dr.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=PRIMARY)
        frames.append(im); dur.append(90)
    for i in range(18):                                           # circle grows
        im, dr = base("The converter fits an exact circle", "Least-squares fit through the mesh vertices: R = %.4f mm" % R)
        dr.line(poly + [poly[0]], fill=(203, 213, 225), width=3)
        for p in poly: dr.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=PRIMARY)
        t = (i + 1) / 18
        r_px = R * sc
        dr.arc([cx - r_px, cy - r_px, cx + r_px, cy + r_px], start=-90, end=-90 + 360 * t, fill=(236, 72, 153), width=5)
        dr.line([cx - 8, cy, cx + 8, cy], fill=INK, width=2); dr.line([cx, cy - 8, cx, cy + 8], fill=INK, width=2)
        frames.append(im); dur.append(70)
    for i in range(14):                                           # polygon fades, circle stays
        im, dr = base("One exact circular edge in the STEP file", "No more straight pieces: the mesh line is gone.")
        r_px = R * sc
        a = max(0.0, 1 - i / 8)
        gcol = tuple(int(BG[j] + ((203, 213, 225)[j] - BG[j]) * a) for j in range(3))
        dr.line(poly + [poly[0]], fill=gcol, width=3)
        dr.arc([cx - r_px, cy - r_px, cx + r_px, cy + r_px], start=0, end=360, fill=(236, 72, 153), width=6)
        frames.append(im); dur.append(120 if i < 13 else 1200)
    # side panel text on every frame
    Vall = P[np.unique(d["F"][ring["tris"]])] - pr["c"]
    err = float(np.abs(np.linalg.norm(Vall - (Vall @ pr["a"])[:, None] * pr["a"], axis=1) - pr["R"]).max())
    notes = ["Holes, bosses and bars become", "cylinders; the same idea finds", "cones, spheres and rounded edges.", "", "Fit error: %.6f mm" % err, "worst of all %d wall vertices." % len(Vall)]
    for im in frames:
        dr = ImageDraw.Draw(im)
        for j, s_ in enumerate(notes):
            text(dr, (390, 130 + j * 28), s_, font(15, bold=(j == 4)), INK if j != 4 else GREEN)
    save_gif(frames, out, dur)


# ---------- GIF 5 + 6: dashboard (illustration) and terminal ----------
def rr(dr, box, r, fill, outline=None, w=1):
    dr.rounded_rectangle(box, r, fill=fill, outline=outline, width=w)


def gif_dashboard(d, out):
    sc = Scene(d["P"], d["F"], d["N"]); Ns = smooth_normals(d); bmask = boundary_mask(d)
    W, H = 800, 520; frames = []; dur = []
    thumb_col = np.tile(np.array((176, 190, 208), float), (len(d["F"]), 1))
    def chrome(dark=False):
        bg, card, ink, mut, brd = ((15, 23, 42), (30, 41, 59), (226, 232, 240), (156, 163, 175), (75, 85, 99)) if dark else (BG, (255, 255, 255), INK, MUTED, (209, 213, 219))
        im = Image.new("RGB", (W, H), bg); dr = ImageDraw.Draw(im)
        rr(dr, [0, 0, W, 50], 0, card); dr.line([0, 50, W, 50], fill=brd)
        text(dr, (18, 14), "STL → STEP / SolidWorks", font(16, True), ink)
        text(dr, (260, 17), "Version 7 · runs locally", font(11), mut)
        for j, (s_, on) in enumerate((("Light", not dark), ("Dark", dark), ("Auto", False))):
            x = W - 190 + j * 60; rr(dr, [x, 12, x + 54, 38], 7, PRIMARY if on else card, brd)
            text(dr, (x + 27, 25), s_, font(11), (255, 255, 255) if on else ink, "mm")
        rr(dr, [W - 20 - 0, 0, W, 0], 0, card)
        return im, dr, bg, card, ink, mut, brd
    def left_card(dr, card, ink, mut, brd, filename=None, fmt=0, busy=False, btn=False):
        rr(dr, [18, 66, 388, 502], 12, card, brd)
        text(dr, (34, 80), "1 · UPLOAD", font(10, True), mut)
        rr(dr, [34, 98, 372, 150], 10, card, PRIMARY if filename else brd, 2)
        text(dr, (203, 124), filename or "Drop an STL here", font(13, True), ink if filename else mut, "mm")
        text(dr, (34, 166), "2 · OUTPUT FORMAT", font(10, True), mut)
        for j, (a, b) in enumerate((("STL → STEP", ".step · works everywhere"), ("STL → SolidWorks Part", ".SLDPRT · needs SolidWorks"))):
            x = 34 + j * 172; rr(dr, [x, 184, x + 166, 226], 9, (238, 242, 255) if (j == fmt and card[0] > 200) else card, PRIMARY if j == fmt else brd, 2)
            text(dr, (x + 10, 190), a, font(11, True), ink); text(dr, (x + 10, 208), b, font(9), mut)
        text(dr, (34, 242), "3 · SETTINGS", font(10, True), mut)
        rows = [("Recover curved surfaces", "on"), ("Repair mesh first", "on"), ("Smoothing level", "Exact"), ("Fit tolerance", "0.0005"), ("Angle tolerance (°)", "8")]
        for j, (a, b) in enumerate(rows):
            y = 262 + j * 30; text(dr, (34, y), a, font(12), ink)
            if b == "on":
                rr(dr, [336, y + 1, 366, y + 17], 8, PRIMARY); dr.ellipse([353, y + 3, 365, y + 15], fill=(255, 255, 255))
            else:
                rr(dr, [300, y - 3, 366, y + 19], 6, card, brd); text(dr, (333, y + 8), b, font(11), ink, "mm")
        rr(dr, [34, 428, 372, 468], 9, (129, 140, 248) if busy else PRIMARY)
        text(dr, (203, 448), "Converting…" if busy else "Convert to STEP", font(14, True), (255, 255, 255), "mm")
    def preview_card(im, dr, card, ink, mut, brd, yaw=0.6, show=True, big=False, note=None):
        rr(dr, [404, 66, 782, 276], 12, card, brd)
        text(dr, (420, 80), "PREVIEW", font(10, True), mut)
        rr(dr, [696, 74, 772, 98], 7, card, brd); text(dr, (734, 86), "Enlarge" if not big else "Close", font(10), ink, "mm")
        if show:
            pv = render(sc, yaw, 0.55, (350, 156), thumb_col, outline=np.ones(len(d["F"]), bool), edge_col=(120, 134, 152), bg=card)
            im.paste(pv, (418, 106))
        if note: text(dr, (420, 258), note, font(10), mut)
    def kpi(dr, x, y, big, small, ink, mut, bg):
        rr(dr, [x, y, x + 84, y + 52], 8, bg); text(dr, (x + 10, y + 6), big, font(15, True), ink); text(dr, (x + 10, y + 32), small, font(9), mut)
    def results(dr, card, ink, mut, brd, bg, t=1.0):
        rr(dr, [404, 288, 782, 502], 12, card, brd)
        text(dr, (420, 300), "RESULT", font(10, True), mut)
        text(dr, (420, 318), "Done", font(13, True), GREEN); text(dr, (462, 319), "· Curved surfaces", font(12), ink)
        k = [(format(len(d["F"]), ","), "Triangles in"), (str(len(d["regions"])), "Faces out"), ("5", "Curved surfaces"), ("0.0%", "Faceted area")]
        for j, (a, b) in enumerate(k):
            if j < int(4 * t + 0.001): kpi(dr, 420 + j * 90, 346, a, b, ink, mut, bg)
        tot = len(d["regions"]); x = 420; wbar = 340
        counts = {}
        for r in d["regions"]: counts[r["prim"]["type"]] = counts.get(r["prim"]["type"], 0) + 1
        rr(dr, [420, 412, 420 + wbar, 424], 6, bg)
        for ty in ("cyl", "torus", "cone", "plane"):
            if ty in counts:
                w = int(wbar * counts[ty] / tot * t); rr(dr, [x, 412, x + max(w, 1), 424], 5, TYPE_COL[ty]); x += w
        text(dr, (420, 432), "Clean: almost no mesh lines will show in SolidWorks.", font(11, True), GREEN)
        rr(dr, [420, 456, 560, 486], 8, PRIMARY); text(dr, (490, 471), "Download STEP", font(12, True), (255, 255, 255), "mm")
        text(dr, (580, 470), "Volume match 100.00%", font(11), mut)
    def cursor(im, x, y):
        dr = ImageDraw.Draw(im); dr.polygon([(x, y), (x, y + 18), (x + 5, y + 13), (x + 12, y + 13)], fill=(15, 23, 42), outline=(255, 255, 255))
    def add(im, ms): frames.append(im); dur.append(ms)
    im, dr, bg, card, ink, mut, brd = chrome(); left_card(dr, card, ink, mut, brd); preview_card(im, dr, card, ink, mut, brd, show=False, note="Drop a file to see it here")
    for j in range(3):
        im, dr, bg, card, ink, mut, brd = chrome(); left_card(dr, card, ink, mut, brd); preview_card(im, dr, card, ink, mut, brd, show=False, note="Drop a file to see it here")
        cursor(im, 120 + j * 20, 220 - j * 40); add(im, 250)
    for j in range(4):                                   # file loaded, preview rotates a bit
        im, dr, bg, card, ink, mut, brd = chrome(); left_card(dr, card, ink, mut, brd, filename="sample_part.stl · 499 KB"); preview_card(im, dr, card, ink, mut, brd, yaw=0.3 + j * 0.3, note="%s triangles · drag to rotate" % format(len(d["F"]), ","))
        cursor(im, 300 - j * 15, 380 + j * 15); add(im, 220)
    for j in range(3):                                   # convert
        im, dr, bg, card, ink, mut, brd = chrome(); left_card(dr, card, ink, mut, brd, filename="sample_part.stl · 499 KB", busy=True); preview_card(im, dr, card, ink, mut, brd, yaw=1.2 + j * 0.3, note="Converting…")
        rr(dr, [404, 288, 782, 502], 12, card, brd); text(dr, (593, 395), "Converting… large meshes can take a minute", font(12), mut, "mm"); add(im, 350)
    for j in range(6):                                   # results build up
        im, dr, bg, card, ink, mut, brd = chrome(); left_card(dr, card, ink, mut, brd, filename="sample_part.stl · 499 KB"); preview_card(im, dr, card, ink, mut, brd, yaw=2.1 + j * 0.2)
        results(dr, card, ink, mut, brd, (241, 245, 249), t=min(1, (j + 1) / 4)); add(im, 260 if j < 5 else 1100)
    n_rot = 16                                           # enlarge: auto-rotates
    for j in range(n_rot):
        im, dr, bg, card, ink, mut, brd = chrome()
        ov = Image.new("RGB", (W, H), (15, 23, 42)); im = Image.blend(im, ov, 0.55); dr = ImageDraw.Draw(im)
        rr(dr, [40, 40, W - 40, H - 40], 14, (255, 255, 255)); text(dr, (62, 58), "PREVIEW", font(10, True), MUTED)
        text(dr, (W - 260, 58), "☑ Auto-rotate", font(11), INK); rr(dr, [W - 150, 50, W - 62, 74], 7, (255, 255, 255), (209, 213, 219)); text(dr, (W - 106, 62), "Close", font(10), INK, "mm")
        pv = render(sc, 0.5 + j * 2 * math.pi / n_rot, 0.55, (W - 120, H - 150), type_colors(d), nrm=Ns, outline=None, lines=[(bmask, (30, 41, 59), 1.1)], bg=(255, 255, 255), zoom=1.15)
        im.paste(pv, (60, 84)); dr = ImageDraw.Draw(im)
        text(dr, (W // 2, H - 56), "Enlarged: the model auto-rotates. Drag to take over. Esc closes.", font(12), MUTED, "mm"); add(im, 110)
    for dark in (False, True, True):                     # dark mode
        im, dr, bg, card, ink, mut, brd = chrome(dark=dark); left_card(dr, card, ink, mut, brd, filename="sample_part.stl · 499 KB"); preview_card(im, dr, card, ink, mut, brd, yaw=2.4)
        results(dr, card, ink, mut, brd, (21, 32, 50) if dark else (241, 245, 249)); text(dr, (W // 2, 510), "Light, dark or auto theme", font(11), mut, "mm"); add(im, 900)
    for im in frames:
        ImageDraw.Draw(im).text((W - 8, H - 4), "illustration of the layout", font=font(9), fill=(148, 163, 184), anchor="rb")
    save_gif(frames, out, dur, colors=160)


def gif_terminal(out):
    import subprocess
    cmd = [sys.executable, os.path.join(ROOT, "stl2step.py"), SAMPLE, "-o", "/tmp/_gif_out"]
    try:
        raw = subprocess.run(cmd, capture_output=True, text=True, timeout=300).stdout
        res = [l.rstrip() for l in raw.splitlines() if l.strip() and "***" not in l and "\x1b" not in l]
        res = [l.replace("/tmp/_gif_out/", "").replace(SAMPLE, "examples/sample_part.stl") for l in res]
    except Exception:
        res = ["(run the command to see the log)"]
    res = [("  " + l.strip()) if not l.startswith("Converting") else l for l in res][:9]
    W, H = 800, 340
    script = [("$ ", "pip install -r requirements.txt", ["Successfully installed numpy cadquery-ocp"]),
              ("$ ", "python stl2step.py examples/sample_part.stl", res),
              ("$ ", "python dashboard.py", ["STL dashboard version 7 running at http://localhost:8000"])]
    frames, dur = [], []
    lines = []
    def draw(cur=None):
        im = Image.new("RGB", (W, H), (15, 23, 42)); dr = ImageDraw.Draw(im)
        dr.rectangle([0, 0, W, 30], fill=(30, 41, 59))
        for j, c in enumerate(((239, 68, 68), (245, 158, 11), (16, 185, 129))): dr.ellipse([14 + j * 20, 10, 24 + j * 20, 20], fill=c)
        text(dr, (W // 2, 15), "terminal", font(11), (148, 163, 184), "mm")
        y = 44; f = font(13, mono=True)
        for kind, s_ in (lines + ([cur] if cur else []))[-15:]:
            col = (134, 239, 172) if kind == "cmd" else ((203, 213, 225) if kind == "out" else (148, 163, 184))
            text(dr, (16, y), s_[:96], f, col); y += 21
        dr.text((W - 10, H - 6), "illustration (log is real output)", font=font(9), fill=(100, 116, 139), anchor="rb")
        return im
    for pre, c, outs in script:
        for i in range(0, len(c) + 1, 3):
            frames.append(draw(("cmd", pre + c[:i] + "▌"))); dur.append(40)
        lines.append(("cmd", pre + c)); frames.append(draw()); dur.append(250)
        for o in outs:
            lines.append(("out", o)); frames.append(draw()); dur.append(260)
        dur[-1] = 600
    dur[-1] = 2500
    save_gif(frames, out, dur, colors=32)


def main():
    t0 = time.time()
    tris = S.read_stl(SAMPLE)
    print("analysing", SAMPLE, "(%d triangles)" % len(tris))
    d = analyse(tris)
    print("  %d faces, volume %.2f" % (len(d["regions"]), d["vol"]))
    docs = HERE
    gif_before_after(d, os.path.join(docs, "before_after.gif"))
    gif_pipeline(d, os.path.join(docs, "pipeline.gif"))
    gif_curve_fit(d, os.path.join(docs, "curve_fit.gif"))
    gif_repair(tris, os.path.join(docs, "repair.gif"))
    gif_dashboard(d, os.path.join(docs, "dashboard.gif"))
    gif_terminal(os.path.join(docs, "quickstart.gif"))
    print("done in %.0f s" % (time.time() - t0))


if __name__ == "__main__":
    main()
