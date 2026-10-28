#!/usr/bin/env python3
"""
stl2step.py - Convert STL (or OpenSCAD .scad) to STEP. Pure Python, no installs.

Handles big / messy meshes:
  * welds duplicate vertices, drops degenerate + duplicate triangles
  * merges coplanar triangles into single faces (huge reduction on
    mechanical parts: 100,000 triangles -> a few dozen faces)
  * open / non-watertight meshes are written as a surface model instead of failing
  * streams the file to disk, so memory stays low

Usage:
    python stl2step.py part.stl              -> part.step
    python stl2step.py part.scad             -> part.step (needs OpenSCAD)
    python stl2step.py *.stl -o out_folder
Options:
    --no-merge      keep every triangle as its own face
    --angle DEG     max angle to treat neighbours as flat (default 0.003)
    --ocp           use cadquery-ocp if installed (only good for small meshes)
"""
import argparse, math, os, re, shutil, struct, subprocess, sys, tempfile, datetime, time


# ---------------- STL reading ----------------
def read_stl(path):
    data = open(path, "rb").read()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + n * 50 == len(data):
            tris = []
            for v in struct.iter_unpack("<12fH", data[84:84 + n * 50]):
                tris.append(((v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11])))
            return tris
    text = data.decode("utf-8", "ignore")
    vs = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    vs = [(float(a), float(b), float(c)) for a, b, c in vs]
    return [tuple(vs[i:i + 3]) for i in range(0, len(vs) - 2, 3)]


def weld(tris):
    """merge duplicate vertices; returns (points, faces as index triples)"""
    xs = [p[0] for t in tris for p in t]
    ys = [p[1] for t in tris for p in t]
    zs = [p[2] for t in tris for p in t]
    diag = math.sqrt((max(xs)-min(xs))**2 + (max(ys)-min(ys))**2 + (max(zs)-min(zs))**2) or 1.0
    tol = max(diag * 1e-7, 1e-9)
    ids, pts, faces = {}, [], []
    for t in tris:
        f = []
        for p in t:
            k = (round(p[0] / tol), round(p[1] / tol), round(p[2] / tol))
            i = ids.get(k)
            if i is None:
                i = ids[k] = len(pts)
                pts.append(p)
            f.append(i)
        faces.append(tuple(f))
    return pts, faces, diag


def sub(a, b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def cross(u, v): return (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
def dot(u, v): return u[0]*v[0] + u[1]*v[1] + u[2]*v[2]
def norm(v):
    l = math.sqrt(dot(v, v))
    return ((v[0]/l, v[1]/l, v[2]/l), l) if l > 0 else ((0.0, 0.0, 1.0), 0.0)


# ---------------- STEP writer ----------------
def write_step(tris, path, name, merge=True, angle_deg=0.003):
    t0 = time.time()
    pts, F, diag = weld(tris)
    seen, faces = set(), []
    for a, b, c in F:
        if a == b or b == c or a == c:
            continue
        k = tuple(sorted((a, b, c)))
        if k in seen:
            continue
        seen.add(k)
        faces.append((a, b, c))
    N, A = [], []
    keep = []
    for a, b, c in faces:
        cr = cross(sub(pts[b], pts[a]), sub(pts[c], pts[a]))
        n, l = norm(cr)
        if l < diag * diag * 1e-14:
            continue
        keep.append((a, b, c)); N.append(n); A.append(cr)
    faces = keep
    print("  %d triangles after cleanup (%d removed)" % (len(faces), len(tris) - len(faces)))

    # --- merge coplanar neighbours (union-find) ---
    parent = list(range(len(faces)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    emap = {}
    for t, (a, b, c) in enumerate(faces):
        for i, j in ((a, b), (b, c), (c, a)):
            emap.setdefault((i, j) if i < j else (j, i), []).append(t)
    if merge:
        cos_lim = math.cos(math.radians(angle_deg))
        dtol = diag * 1e-6
        for ts in emap.values():
            if len(ts) == 2:
                t1, t2 = ts
                if dot(N[t1], N[t2]) > cos_lim:
                    p = pts[faces[t1][0]]
                    if abs(dot(N[t2], sub(p, pts[faces[t2][0]]))) < dtol:
                        r1, r2 = find(t1), find(t2)
                        if r1 != r2:
                            parent[r1] = r2
    regions = {}
    for t in range(len(faces)):
        regions.setdefault(find(t), []).append(t)
    print("  merged into %d faces" % len(regions))

    # --- stream out ---
    f = open(path, "w")
    cnt = [0]
    def add(s):
        cnt[0] += 1
        f.write("#%d=%s;\n" % (cnt[0], s))
        return cnt[0]
    f.write("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('STL to STEP'),'2;1');\n")
    f.write("FILE_NAME('%s','%s',(''),(''),'stl2step','','');\n"
            % (os.path.basename(path), datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    f.write("FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));\nENDSEC;\nDATA;\n")

    app = add("APPLICATION_CONTEXT('configuration controlled 3d designs of mechanical parts and assemblies')")
    add("APPLICATION_PROTOCOL_DEFINITION('international standard','config_control_design',1994,#%d)" % app)
    mech = add("MECHANICAL_CONTEXT('none',#%d,'mechanical')" % app)
    prod = add("PRODUCT('%s','%s','',(#%d))" % (name, name, mech))
    add("PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(#%d))" % prod)
    form = add("PRODUCT_DEFINITION_FORMATION('1','',#%d)" % prod)
    dctx = add("DESIGN_CONTEXT('',#%d,'design')" % app)
    pdef = add("PRODUCT_DEFINITION('design','',#%d,#%d)" % (form, dctx))
    pshape = add("PRODUCT_DEFINITION_SHAPE('','',#%d)" % pdef)

    ptid, vid = {}, {}
    def point(i):
        if i not in ptid:
            ptid[i] = add("CARTESIAN_POINT('',(%r,%r,%r))" % pts[i])
            vid[i] = add("VERTEX_POINT('',#%d)" % ptid[i])
        return ptid[i]
    edge_id, edge_use = {}, {}
    def oriented(i, j):
        lo, hi = (i, j) if i < j else (j, i)
        k = (lo, hi)
        if k not in edge_id:
            point(lo); point(hi)
            d, ln = norm(sub(pts[hi], pts[lo]))
            dd = add("DIRECTION('',(%r,%r,%r))" % d)
            vec = add("VECTOR('',#%d,%r)" % (dd, ln))
            line = add("LINE('',#%d,#%d)" % (ptid[lo], vec))
            edge_id[k] = add("EDGE_CURVE('',#%d,#%d,#%d,.T.)" % (vid[lo], vid[hi], line))
            edge_use[k] = 0
        edge_use[k] += 1
        return add("ORIENTED_EDGE('',*,*,#%d,%s)" % (edge_id[k], ".T." if i < j else ".F."))

    face_ids = []
    for ts in regions.values():
        # boundary loops
        de = set()
        cr = [0.0, 0.0, 0.0]
        for t in ts:
            a, b, c = faces[t]
            for k in range(3):
                cr[k] += A[t][k]
            for e in ((a, b), (b, c), (c, a)):
                r = (e[1], e[0])
                if r in de:
                    de.remove(r)
                else:
                    de.add(e)
        n, _ = norm(tuple(cr))
        out = {}
        for i, j in de:
            out.setdefault(i, []).append(j)
        loops = []
        while out:
            start = next(iter(out))
            loop, cur = [start], start
            while True:
                nxt = out[cur].pop()
                if not out[cur]:
                    del out[cur]
                if nxt == start:
                    break
                loop.append(nxt)
                cur = nxt
                if cur not in out:
                    break
            if len(loop) >= 3:
                loops.append(loop)
        if not loops:
            continue
        def signed(loop):
            o = pts[loop[0]]
            s = [0.0, 0.0, 0.0]
            for k in range(1, len(loop) - 1):
                c = cross(sub(pts[loop[k]], o), sub(pts[loop[k + 1]], o))
                s[0] += c[0]; s[1] += c[1]; s[2] += c[2]
            return dot(s, n)
        loops.sort(key=lambda l: -signed(l))
        # plane
        l0 = loops[0]
        o = point(l0[0])
        e1 = sub(pts[l0[1]], pts[l0[0]])
        e1 = sub(e1, tuple(dot(e1, n) * x for x in n))
        ref, _ = norm(e1)
        dn = add("DIRECTION('',(%r,%r,%r))" % n)
        dr = add("DIRECTION('',(%r,%r,%r))" % ref)
        ax = add("AXIS2_PLACEMENT_3D('',#%d,#%d,#%d)" % (o, dn, dr))
        pl = add("PLANE('',#%d)" % ax)
        bounds = []
        for idx, loop in enumerate(loops):
            oes = [oriented(loop[k], loop[(k + 1) % len(loop)]) for k in range(len(loop))]
            el = add("EDGE_LOOP('',(%s))" % ",".join("#%d" % x for x in oes))
            bounds.append(add("%s('',#%d,.T.)" % ("FACE_OUTER_BOUND" if idx == 0 else "FACE_BOUND", el)))
        face_ids.append(add("ADVANCED_FACE('',(%s),#%d,.T.)" % (",".join("#%d" % b for b in bounds), pl)))

    closed = all(v == 2 for v in edge_use.values())
    fl = ",".join("#%d" % x for x in face_ids)
    if closed:
        shell = add("CLOSED_SHELL('',(%s))" % fl)
        body = add("MANIFOLD_SOLID_BREP('%s',#%d)" % (name, shell))
    else:
        bad = sum(1 for v in edge_use.values() if v != 2)
        print("  WARNING: mesh is not watertight (%d bad edges). Writing a surface "
              "model instead of a solid. Repair the STL (e.g. Meshmixer / "
              "3D Builder / Netfabb) if you need a solid." % bad)
        shell = add("OPEN_SHELL('',(%s))" % fl)
        body = add("SHELL_BASED_SURFACE_MODEL('%s',(#%d))" % (name, shell))

    ln = add("(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))")
    an = add("(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))")
    sa = add("(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())")
    unc = add("UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-06),#%d,'distance_accuracy_value','')" % ln)
    g = add("(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#%d)) "
            "GLOBAL_UNIT_ASSIGNED_CONTEXT((#%d,#%d,#%d)) REPRESENTATION_CONTEXT('',''))" % (unc, ln, an, sa))
    rep = add("SHAPE_REPRESENTATION('%s',(#%d),#%d)" % (name, body, g))
    add("SHAPE_DEFINITION_REPRESENTATION(#%d,#%d)" % (pshape, rep))
    f.write("ENDSEC;\nEND-ISO-10303-21;\n")
    f.close()
    print("  wrote %s  (%d faces, %.1fs)" % (path, len(face_ids), time.time() - t0))



# ---------------- smart mode: recover true curved surfaces ----------------
# mesh -> detect cylinders / spheres / cones (holes, fillets, bosses, domes)
#      -> rebuild an exact B-rep (real circles + analytic surfaces) with OpenCascade
from collections import defaultdict, deque


def _prep(np, tris):
    T = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    allp = T.reshape(-1, 3)
    diag = float(np.linalg.norm(allp.max(0) - allp.min(0))) or 1.0
    tw = max(diag * 1e-7, 1e-9)
    keys = np.round(allp / tw).astype(np.int64)
    _, first, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    P = allp[first]
    F = inv.reshape(-1, 3)
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    _, ui = np.unique(np.sort(F, axis=1), axis=0, return_index=True)
    F = F[np.sort(ui)]
    cr = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    ln = np.linalg.norm(cr, axis=1)
    ok = ln > diag * diag * 1e-14
    F, cr, ln = F[ok], cr[ok], ln[ok]
    return P, F, cr / ln[:, None], ln * 0.5, diag


def _adjacency(np, F, nv):
    nf = len(F)
    e = np.stack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], axis=1).reshape(-1, 2)
    key = np.minimum(e[:, 0], e[:, 1]).astype(np.int64) * nv + np.maximum(e[:, 0], e[:, 1])
    order = np.argsort(key, kind="stable")
    ks = key[order]
    starts = np.r_[0, np.nonzero(ks[:-1] != ks[1:])[0] + 1]
    sizes = np.diff(np.r_[starts, len(ks)])
    nbr = -np.ones(3 * nf, dtype=np.int64)
    sel = starts[sizes == 2]
    o1, o2 = order[sel], order[sel + 1]
    nbr[o1] = o2 // 3
    nbr[o2] = o1 // 3
    return nbr.reshape(-1, 3), bool((sizes == 2).all())



# ----- mesh repair: consistent orientation + close holes (so you get a SOLID) -----
def _orient(np, F, nbr):
    F = F.copy(); nbr = nbr.copy(); nf = len(F); seen = np.zeros(nf, bool)
    for s0 in range(nf):
        if seen[s0]:
            continue
        seen[s0] = True; st_ = [s0]
        while st_:
            t = st_.pop()
            for k in range(3):
                u = nbr[t, k]
                if u < 0 or seen[u]:
                    continue
                i, j = F[t, k], F[t, (k + 1) % 3]
                fu = F[u]
                if not any(fu[m] == j and fu[(m + 1) % 3] == i for m in range(3)):
                    F[u] = F[u][[0, 2, 1]]
                    nbr[u] = nbr[u][[2, 1, 0]]
                seen[u] = True; st_.append(u)
    return F


def _tri_poly(np, Q):
    m = len(Q)
    n = np.zeros(3)
    for i in range(m):
        n += np.cross(Q[i], Q[(i + 1) % m])
    ln = np.linalg.norm(n)
    if ln < 1e-18:
        return None
    u, v = _basis(np, n / ln)
    pts = np.c_[Q @ u, Q @ v]
    idx = list(range(m)); out = []
    while len(idx) > 3:
        L = len(idx); found = False
        for ii in range(L):
            a, b, c = idx[ii - 1], idx[ii], idx[(ii + 1) % L]
            pa, pb, pc = pts[a], pts[b], pts[c]
            if (pb[0]-pa[0])*(pc[1]-pa[1]) - (pb[1]-pa[1])*(pc[0]-pa[0]) <= 1e-12 * ln:
                continue
            bad = False
            for w in idx:
                if w in (a, b, c):
                    continue
                pw = pts[w]
                if ((pb[0]-pa[0])*(pw[1]-pa[1]) - (pb[1]-pa[1])*(pw[0]-pa[0]) >= 0 and
                        (pc[0]-pb[0])*(pw[1]-pb[1]) - (pc[1]-pb[1])*(pw[0]-pb[0]) >= 0 and
                        (pa[0]-pc[0])*(pw[1]-pc[1]) - (pa[1]-pc[1])*(pw[0]-pc[0]) >= 0):
                    bad = True; break
            if bad:
                continue
            out.append((a, b, c)); idx.pop(ii); found = True; break
        if not found:
            return None
    out.append(tuple(idx))
    return out


def _fill_holes(np, P, F, nbr, log):
    bt, bk = np.nonzero(nbr < 0)
    if len(bt) == 0:
        return P, F, 0
    out = defaultdict(list)
    for t, k in zip(bt, bk):
        out[int(F[t, k])].append(int(F[t, (k + 1) % 3]))
    newP, newF, nv, filled = [], [], len(P), 0
    while out:
        s0 = next(iter(out)); loop = [s0]; cur = s0; ok = True
        while True:
            nxt = out[cur].pop()
            if not out[cur]:
                del out[cur]
            if nxt == s0:
                break
            loop.append(nxt); cur = nxt
            if cur not in out:
                ok = False; break
        if not ok or len(loop) < 3:
            continue
        poly = loop[::-1]
        Q = P[poly]
        tr = _tri_poly(np, Q) if len(poly) <= 400 else None
        if tr is not None:
            for a, b, c in tr:
                newF.append((poly[a], poly[b], poly[c]))
        else:
            ctr = Q.mean(0); newP.append(ctr); ci = nv; nv += 1
            for k in range(len(poly)):
                newF.append((poly[k], poly[(k + 1) % len(poly)], ci))
        filled += 1
    if newP:
        P = np.vstack([P, np.array(newP)])
    if newF:
        F = np.vstack([F, np.array(newF, dtype=F.dtype)])
    return P, F, filled


def repair_tris(tris, log=print):
    """Make the mesh watertight with consistent outward normals. Returns a new triangle list."""
    try:
        import numpy as np
    except ImportError:
        return tris
    try:
        P, F, N, A, diag = _prep(np, tris)
        nbr, closed = _adjacency(np, F, len(P))
        F = _orient(np, F, nbr)
        nopen = int((nbr < 0).sum())
        if nopen:
            P, F, filled = _fill_holes(np, P, F, nbr, log)
            log("  repair: closed %d hole(s) in the mesh (%d open edges)" % (filled, nopen))
            P, F, N, A, diag = _prep2(np, P, F)
            nbr, closed = _adjacency(np, F, len(P))
            F = _orient(np, F, nbr)
        vol = float(np.einsum("ij,ij->", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])) / 6.0)
        if vol < 0:
            F = F[:, [0, 2, 1]]
        nbr, closed = _adjacency(np, F, len(P))
        if not closed:
            log("  repair: mesh still has open or non-manifold edges")
        return [tuple(map(tuple, t)) for t in P[F].tolist()]
    except Exception as e:
        log("  repair skipped (%s)" % e)
        return tris


def _prep2(np, P, F):
    cr = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    ln = np.linalg.norm(cr, axis=1)
    diag = float(np.linalg.norm(P.max(0) - P.min(0))) or 1.0
    ok = ln > diag * diag * 1e-14
    F, cr, ln = F[ok], cr[ok], ln[ok]
    return P, F, cr / ln[:, None], ln * 0.5, diag


# ----- primitive fitting -----
def _basis(np, a):
    t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(a, t); u /= np.linalg.norm(u)
    return u, np.cross(a, u)


def _fit_axis(np, N, X):
    m = N.mean(0)
    C = N - m
    w, v = np.linalg.eigh(C.T @ C / len(N))
    if w[2] < 2e-5 or w[0] > 0.1 * w[1] + 1e-8:
        return None
    return v[:, 0], float(m @ v[:, 0])


def _distinct(np, Ns):
    """number of different facet normals (a flat area full of identical normals must not outvote a curved patch)"""
    return int(np.unique(np.round(Ns * 40).astype(np.int64), axis=0).shape[0])


def fit_cyl(np, tris, F, P, N, X, diag):
    tris = np.asarray(tris)
    Nt = N[tris]
    cands = []
    r = _fit_axis(np, Nt, X[tris])
    if r is not None and abs(r[1]) <= 0.04:
        cands.append(r[0])
    rng = np.random.default_rng(len(tris))
    n = len(tris)
    for _ in range(40):                                # RANSAC: two facet normals of a cylinder give its axis
        i, j = rng.integers(0, n, 2)
        c = np.cross(Nt[i], Nt[j]); l = np.linalg.norm(c)
        if l > 0.02:
            cands.append(c / l)
    best = None
    for a in cands:
        inl = np.abs(Nt @ a) < 0.03
        k = _distinct(np, Nt[inl]) if inl.sum() >= 4 else 0
        if k >= 4 and (best is None or k > best[0]):
            best = (k, a, inl)
    if best is None:
        return None
    a = best[1]
    sub = tris[best[2]]
    w = np.linalg.eigvalsh(np.cov(N[sub].T)) if len(sub) > 3 else np.zeros(3)
    if w[2] < 2e-5:
        return None                                    # normals do not turn: flat, not a cylinder
    Q = P[np.unique(F[sub])]
    u, v = _basis(np, a)
    x, y = Q @ u, Q @ v
    sol = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x * x + y * y, rcond=None)[0]
    k = sol[2] + sol[0] ** 2 + sol[1] ** 2
    if not np.isfinite(k) or k <= 0:
        return None
    R = float(np.sqrt(k))
    if R > 50 * diag:
        return None
    c = sol[0] * u + sol[1] * v + a * float((Q @ a).mean())
    return {"type": "cyl", "a": a, "c": c, "R": R}


def fit_cone(np, tris, F, P, N, X, diag):
    tris = np.asarray(tris)
    Nt, Xt = N[tris], X[tris]
    n = len(tris)
    cands = []
    r = _fit_axis(np, Nt, Xt)
    if r is not None:
        cands.append((r[0], None))
    rng = np.random.default_rng(n + 7)
    for _ in range(120):                               # RANSAC: three facet normals of a cone give its axis
        i, j, k = rng.integers(0, n, 3)
        c = np.cross(Nt[j] - Nt[i], Nt[k] - Nt[i]); l = np.linalg.norm(c)
        if l > 0.02:
            a_ = c / l
            cands.append((a_, float(Nt[i] @ a_)))
    best = None
    for a, cc in cands:
        d = Nt @ a
        if cc is None:
            cc = float(np.median(d))
        if not (0.04 < abs(cc) < 0.995):
            continue
        inl = np.abs(d - cc) < 0.03
        k = _distinct(np, Nt[inl]) if inl.sum() >= 5 else 0
        if k >= 5 and (best is None or k > best[0]):
            best = (k, a, inl)
    if best is None:
        return None
    a, sub = best[1], tris[best[2]]
    Ns, Xs = N[sub], X[sub]
    if np.linalg.eigvalsh(np.cov(Ns.T))[2] < 2e-5:
        return None
    apex = np.linalg.lstsq(Ns, (Ns * Xs).sum(1), rcond=None)[0]
    s_ = (Xs - apex) @ a
    if s_.mean() < 0:
        a, s_ = -a, -s_
    rho = np.linalg.norm((Xs - apex) - s_[:, None] * a, axis=1)
    alpha = float(np.median(np.arctan2(rho, s_)))
    if not (0.03 < alpha < 1.5):
        return None
    return {"type": "cone", "a": a, "c": apex, "alpha": alpha}


def fit_sphere(np, tris, F, P, N, X, diag):
    Nt = N[tris]
    ev = np.linalg.eigvalsh(np.cov(Nt.T)) if len(Nt) > 3 else np.zeros(3)
    if ev[0] < 2e-4:
        return None  # normals span only 2 dims: cylinder/cone-like, not a sphere
    Q = P[np.unique(F[tris])]
    if len(Q) < 5:
        return None
    sol = np.linalg.lstsq(np.c_[2 * Q, np.ones(len(Q))], (Q * Q).sum(1), rcond=None)[0]
    k = sol[3] + sol[:3] @ sol[:3]
    if not np.isfinite(k) or k <= 0:
        return None
    R = float(np.sqrt(k))
    if R > 50 * diag:
        return None
    return {"type": "sphere", "c": sol[:3], "R": R}


def make_torus_fitter(axes):
    """torus (rounded edges) around known axes: profile circle fitted in (rho, z) - linear least squares"""
    def fit_torus(np, tris, F, P, N, X, diag):
        Q = P[np.unique(F[tris])]
        if len(Q) < 6:
            return None
        best = None
        for (a, c0) in axes:
            d = Q - c0
            z = d @ a
            rho = np.linalg.norm(d - z[:, None] * a, axis=1)
            sol = np.linalg.lstsq(np.c_[2 * rho, 2 * z, np.ones(len(z))], rho * rho + z * z, rcond=None)[0]
            R, z0 = sol[0], sol[1]
            k = sol[2] + R * R + z0 * z0
            if not np.isfinite(k) or k <= 0 or R <= 0:
                continue
            r = float(np.sqrt(k))
            if r > 0.3 * diag or r > R:
                continue
            res = float(np.abs(np.sqrt((rho - R) ** 2 + (z - z0) ** 2) - r).max())
            if best is None or res < best[0]:
                best = (res, {"type": "torus", "a": a, "c": c0 + a * z0, "R": float(R), "r": r})
        return best[1] if best else None
    return fit_torus


FITTERS = {"cyl": fit_cyl, "cone": fit_cone, "sphere": fit_sphere}


def prim_dist(np, pr, Q):
    t = pr["type"]
    if t == "cyl":
        w = Q - pr["c"]
        return np.abs(np.linalg.norm(w - (w @ pr["a"])[:, None] * pr["a"], axis=1) - pr["R"])
    if t == "sphere":
        return np.abs(np.linalg.norm(Q - pr["c"], axis=1) - pr["R"])
    if t == "torus":
        w = Q - pr["c"]
        z = w @ pr["a"]
        rho = np.linalg.norm(w - z[:, None] * pr["a"], axis=1)
        return np.abs(np.sqrt((rho - pr["R"]) ** 2 + z * z) - pr["r"])
    w = Q - pr["c"]
    s = w @ pr["a"]
    rho = np.linalg.norm(w - s[:, None] * pr["a"], axis=1)
    return np.abs(rho * np.cos(pr["alpha"]) - s * np.sin(pr["alpha"]))


def _torus_normal(np, pr, X):
    w = X - pr["c"]
    z = w @ pr["a"]
    rad = w - z[:, None] * pr["a"]
    rho = np.maximum(np.linalg.norm(rad, axis=1), 1e-12)
    ring = rad / rho[:, None] * pr["R"] + 0 * z[:, None]
    v = rad + z[:, None] * pr["a"] - ring
    return v / np.maximum(np.linalg.norm(v, axis=1), 1e-12)[:, None]


def prim_tri_ok(np, pr, P, F, N, X, tol, sin_ang):
    ok = (prim_dist(np, pr, P)[F] < tol).all(1)
    t = pr["type"]
    if t == "cyl":
        ok &= np.abs(N @ pr["a"]) < sin_ang
    elif t == "cone":
        ok &= np.abs(np.abs(N @ pr["a"]) - np.sin(pr["alpha"])) < sin_ang * 1.5
    elif t == "torus":
        ok &= np.abs((_torus_normal(np, pr, X) * N).sum(1)) > 0.95
    else:
        r = X - pr["c"]
        r = r / np.maximum(np.linalg.norm(r, axis=1), 1e-12)[:, None]
        ok &= np.abs((r * N).sum(1)) > 0.93
    return ok


def tri_ok_local(np, pr, Pt, Nt, Xt, tol, sin_ang):
    d = prim_dist(np, pr, Pt.reshape(-1, 3)).reshape(-1, 3)
    ok = (d < tol).all(1)
    t = pr["type"]
    if t == "cyl":
        ok &= np.abs(Nt @ pr["a"]) < sin_ang
    elif t == "cone":
        ok &= np.abs(np.abs(Nt @ pr["a"]) - np.sin(pr["alpha"])) < sin_ang * 1.5
    elif t == "torus":
        ok &= np.abs((_torus_normal(np, pr, Xt) * Nt).sum(1)) > 0.95
    else:
        r = Xt - pr["c"]
        r = r / np.maximum(np.linalg.norm(r, axis=1), 1e-12)[:, None]
        ok &= np.abs((r * Nt).sum(1)) > 0.93
    return ok


def detect_primitives(np, P, F, N, A, X, nbr, diag, tol, ang_deg, min_tris, max_seconds=90):
    nf = len(F)
    sin_ang = float(np.sin(np.radians(ang_deg)))
    cosd = (N[:, None, :] * N[nbr]).sum(2)
    cm = ((cosd < np.cos(np.radians(0.05))) & (cosd > np.cos(np.radians(60))) & (nbr >= 0)).any(1)
    remaining = np.ones(nf, bool)
    cos50 = np.cos(np.radians(50))
    rng = np.random.default_rng(1)

    def hood(seed, M):
        seen = {seed}; dq = deque([seed])
        while dq and len(seen) < M:
            t = dq.popleft()
            for u in nbr[t]:
                if u >= 0 and u not in seen and remaining[u] and N[t] @ N[u] > cos50:
                    seen.add(u); dq.append(u)
        return np.fromiter(seen, dtype=np.int64)

    def flood(seed, ok):
        if not ok[seed]:
            return []
        seen = {seed}; dq = deque([seed])
        while dq:
            t = dq.popleft()
            for u in nbr[t]:
                if u >= 0 and u not in seen and ok[u]:
                    seen.add(u); dq.append(u)
        return list(seen)

    def try_seed(seed):
        best = None
        for M in (12, 30, 80, 200):
            nb = hood(seed, M)
            if len(nb) < 6:
                continue
            for name, fn in CF[0].items():
                pr = fn(np, nb, F, P, N, X, diag)
                if pr is None:
                    continue
                okn = tri_ok_local(np, pr, P[F[nb]], N[nb], X[nb], tol, sin_ang)
                if okn.sum() < 6 or not okn[int(np.nonzero(nb == seed)[0][0])]:
                    continue
                reg = []
                for _ in range(3):
                    reg = flood(seed, prim_tri_ok(np, pr, P, F, N, X, tol, sin_ang) & remaining)
                    if len(reg) < min_tris:
                        break
                    p2 = fn(np, np.array(reg), F, P, N, X, diag)
                    if p2 is None:
                        break
                    pr = p2
                reg = flood(seed, prim_tri_ok(np, pr, P, F, N, X, tol, sin_ang) & remaining)
                if len(reg) >= (min_tris if pr["type"] in ("cyl", "cone", "sphere") else max(min_tris, 24)):
                    score = float(A[reg].sum()) * (1 + {'cyl': 2e-3, 'torus': 3e-3, 'cone': 1e-3, 'sphere': 0}[pr['type']])
                    if best is None or score > best[0]:
                        best = (score, pr, reg)
        return best

    out = []
    CF = [FITTERS]
    zero = np.degrees(np.arccos(np.clip(cosd, -1, 1))) < 0.05
    strip = (zero.sum(1) == 1) & cm          # quad-strip triangles: typical of cylinder / cone walls
    t_end = time.time() + max_seconds

    def phase(fitters):
        CF[0] = fitters
        tried = np.zeros(nf, bool)
        cand0 = np.nonzero(cm & remaining)[0]
        order = np.r_[rng.permutation(cand0[strip[cand0]]), rng.permutation(cand0[~strip[cand0]])]
        for sd in order:
            sd = int(sd)
            if tried[sd] or not remaining[sd]:
                continue
            if time.time() > t_end:
                break
            r = try_seed(sd)
            if r:
                reg = np.array(r[2])
                remaining[reg] = False; tried[reg] = True
                out.append({"prim": r[1], "tris": reg})
            else:
                tried[hood(sd, 12)] = True

    phase({"cyl": fit_cyl})                                   # 1) cylinders

    def span_deg(c):
        pr = c["prim"]; u, v = _basis(np, pr["a"])
        Q = P[np.unique(F[c["tris"]])] - pr["c"]
        th = np.sort(np.arctan2(Q @ v, Q @ u))
        return 360.0 - float(np.degrees(np.diff(np.r_[th, th[0] + 2 * np.pi]).max()))
    anchors = [c for c in out if c["prim"]["type"] == "cyl" and span_deg(c) >= 160]   # holes, bosses, round bars
    for c in out:
        if not any(c is a_ for a_ in anchors):
            remaining[c["tris"]] = True                       # thin cylinder-like slivers: may be torus pieces, re-examine
    out[:] = anchors
    axes = []
    for c in out:
        a_, c_ = c["prim"]["a"], c["prim"]["c"]
        if not any(abs(abs(a_ @ b_) - 1) < 1e-4 and np.linalg.norm(np.cross(a_, c_ - bc_)) < tol for b_, bc_ in axes):
            axes.append((a_, c_))
    allf = dict(FITTERS)
    if axes:
        allf["torus"] = make_torus_fitter(axes)
        phase({"torus": allf["torus"], "cone": fit_cone, "sphere": fit_sphere})   # 2) torus (rounded edges) vs cone vs sphere: biggest fit wins
    phase({"cone": fit_cone, "sphere": fit_sphere})           # 3) cones + spheres
    phase({"cyl": fit_cyl})                                   # 4) remaining straight cylinder pieces (fillets etc.)
    out = _refine_boundaries(np, out, P, F, N, nbr, tol)
    out = _attach_slivers(np, out, P, F, N, X, nbr, tol, sin_ang)
    return _merge_regions(np, out, P, F, N, X, nbr, diag, tol, sin_ang, allf)


def _attach_slivers(np, out, P, F, N, X, nbr, tol, sin_ang):
    """stray triangles that lie on a neighbouring curved surface (within tolerance) but were missed: adopt them"""
    if not out:
        return out
    nf = len(F)
    lab = -np.ones(nf, dtype=np.int64)
    for i, r in enumerate(out):
        lab[r["tris"]] = i
    for _ in range(8):
        nbl = np.where(nbr >= 0, lab[np.where(nbr >= 0, nbr, 0)], -1)
        cand = np.nonzero((lab < 0) & (nbl >= 0).any(1))[0]
        moved = 0
        for t in cand:
            best = None
            for b in set(nbl[t].tolist()):
                if b < 0:
                    continue
                pr = out[b]["prim"]
                if tri_ok_local(np, pr, P[F[t]][None], N[t][None], X[t][None], tol, sin_ang)[0]:
                    d = float(prim_dist(np, pr, P[F[t]]).max())
                    if best is None or d < best[0]:
                        best = (d, b)
            if best:
                lab[t] = best[1]; moved += 1
        if not moved:
            break
    res = []
    for i, r in enumerate(out):
        t = np.nonzero(lab == i)[0]
        if len(t):
            res.append({"prim": r["prim"], "tris": t})
    return res


def _refine_boundaries(np, out, P, F, N, nbr, tol):
    """tangent surfaces (cylinder <-> rounded edge) overlap within tolerance: give every border triangle to the
    surface that really contains it, so region borders become exact circles / lines instead of ragged strips"""
    if len(out) < 2:
        return out
    nf = len(F)
    eps = max(tol * 0.02, 1e-9)
    lab = -np.ones(nf, dtype=np.int64)
    for i, r in enumerate(out):
        lab[r["tris"]] = i
    for _ in range(10):
        nb_lab = np.where(nbr >= 0, lab[np.where(nbr >= 0, nbr, 0)], -1)
        border = np.nonzero((lab >= 0) & ((nb_lab >= 0) & (nb_lab != lab[:, None])).any(1))[0]
        moves = []
        for t in border:
            a = lab[t]
            Q = P[F[t]]
            dA = float(prim_dist(np, out[a]["prim"], Q).max())
            best = (dA, a)
            for b in set(nb_lab[t].tolist()):
                if b < 0 or b == a:
                    continue
                dB = float(prim_dist(np, out[b]["prim"], Q).max())
                if dA > eps and dB < tol and dB < 0.5 * best[0]:
                    best = (dB, b)
            if best[1] != a:
                moves.append((t, best[1]))
        if not moves:
            break
        for t, b in moves:
            lab[t] = b
    res = []
    for i, r in enumerate(out):
        t = np.nonzero(lab == i)[0]
        if len(t):
            res.append({"prim": r["prim"], "tris": t})
    return res


def _merge_regions(np, out, P, F, N, X, nbr, diag, tol, sin_ang, fitters=None):
    fitters = fitters or FITTERS
    """join neighbouring pieces that are really one surface (fixes over-segmentation on noisy meshes)"""
    if len(out) < 2:
        return out
    lab = -np.ones(len(F), dtype=np.int64)
    for i, r in enumerate(out):
        lab[r["tris"]] = i
    rep = list(range(len(out)))
    def root(a):
        while rep[a] != a:
            rep[a] = rep[rep[a]]; a = rep[a]
        return a
    for _round in range(6):
        pairs = set()
        for i, r in enumerate(out):
            if r is None:
                continue
            nb = nbr[r["tris"]].ravel(); nb = nb[nb >= 0]
            for j in set(lab[nb].tolist()) - {-1, i}:
                pairs.add((min(i, j), max(i, j)))
        merged = False
        for i, j in sorted(pairs):
            a, b = root(i), root(j)
            if a == b or out[a] is None or out[b] is None:
                continue
            if out[a]["prim"]["type"] != out[b]["prim"]["type"]:
                continue
            tris = np.concatenate([out[a]["tris"], out[b]["tris"]])
            pr = fitters[out[a]["prim"]["type"]](np, tris, F, P, N, X, diag)
            if pr is None:
                continue
            ok = tri_ok_local(np, pr, P[F[tris]], N[tris], X[tris], tol, sin_ang)
            if ok.mean() >= 0.97:
                out[a] = {"prim": pr, "tris": tris[ok]} if ok.all() else {"prim": pr, "tris": tris}
                out[b] = None; rep[b] = a; lab[tris] = a
                merged = True
        if not merged:
            break
    return [r for r in out if r is not None]


# ----- B-rep building (OpenCascade) -----
def _circle3d(np, Q, tol, diag):
    c0 = Q.mean(0)
    U, S, Vt = np.linalg.svd(Q - c0)
    if S[1] < tol:
        return None
    u, v, n = Vt[0], Vt[1], Vt[2]
    x, y = (Q - c0) @ u, (Q - c0) @ v
    sol = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x * x + y * y, rcond=None)[0]
    k = sol[2] + sol[0] ** 2 + sol[1] ** 2
    if not np.isfinite(k) or k <= 0:
        return None
    r = float(np.sqrt(k))
    ctr = c0 + sol[0] * u + sol[1] * v
    dev = max(np.abs(np.linalg.norm(Q - ctr, axis=1) - r).max(), np.abs((Q - c0) @ n).max())
    if dev > tol or r > 100 * diag:
        return None
    w = Q - ctr
    turn = sum(float(np.cross(w[k], w[k + 1]) @ n) for k in range(len(w) - 1))
    if turn < 0:
        n = -n
    return ctr, n, r


def _segment_chain(np, Q, closed, tol, diag):
    out = []
    def line_ok(i, j):
        d = Q[j] - Q[i]; L = np.linalg.norm(d)
        if L < 1e-12:
            return False
        return np.linalg.norm(np.cross(Q[i:j + 1] - Q[i], d / L), axis=1).max() < tol
    def rec(i, j):
        if j - i == 1:
            out.append(("line", i, j)); return
        if line_ok(i, j):
            out.append(("line", i, j)); return
        if j - i >= 3:
            c = _circle3d(np, Q[i:j + 1], tol, diag)
            if c:
                out.append(("circ", i, j, c)); return
        d = Q[j] - Q[i]; L = np.linalg.norm(d)
        dist = np.linalg.norm(np.cross(Q[i:j + 1] - Q[i], d / L), axis=1) if L > 1e-12 else np.linalg.norm(Q[i:j + 1] - Q[i], axis=1)
        k = i + 1 + int(np.argmax(dist[1:-1]))
        rec(i, k); rec(k, j)
    m = len(Q) - 1
    if closed:
        c = _circle3d(np, Q[:m], tol, diag) if m >= 4 else None
        if c:
            return [("ring", 0, m, c)]
        rec(0, m // 2); rec(m // 2, m)
    else:
        rec(0, m)
    return out


def build_brep(np, P, F, N, A, X, nbr, curved, diag, tol, ang_merge_deg, log):
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax3, gp_Pln, gp_Circ
    from OCP.Geom import Geom_Plane, Geom_CylindricalSurface, Geom_SphericalSurface, Geom_ConicalSurface, Geom_ToroidalSurface
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeEdge,
                                    BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace,
                                    BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid)
    from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Shell, ShapeFix_Solid
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopoDS import TopoDS
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    def st(cls, n): return getattr(cls, n + "_s", None) or getattr(cls, n)

    nf = len(F)
    lab = -np.ones(nf, dtype=np.int64)
    regions = []
    for c in curved:
        lab[c["tris"]] = len(regions)
        regions.append({"prim": c["prim"], "tris": c["tris"], "curved": True})

    # grow planar faces over the remaining triangles (tolerance based: also merges slightly noisy flat areas)
    Pl, Fl, Nl, nbl = P.tolist(), F.tolist(), N.tolist(), nbr.tolist()
    labl = lab.tolist()
    cosang = float(np.cos(np.radians(ang_merge_deg)))
    def grow(seed, o, n):
        seen = {seed}; stack = [seed]
        while stack:
            t = stack.pop()
            for u in nbl[t]:
                if u < 0 or u in seen or labl[u] >= 0:
                    continue
                nu = Nl[u]
                if nu[0]*n[0] + nu[1]*n[1] + nu[2]*n[2] < cosang:
                    continue
                good = True
                for v in Fl[u]:
                    p = Pl[v]
                    if abs((p[0]-o[0])*n[0] + (p[1]-o[1])*n[1] + (p[2]-o[2])*n[2]) > tol:
                        good = False; break
                if good:
                    seen.add(u); stack.append(u)
        return list(seen)
    for sd in np.argsort(-A).tolist():
        if labl[sd] >= 0:
            continue
        reg = grow(sd, Pl[Fl[sd][0]], Nl[sd])
        nn = np.array(Nl[sd]); oo = P[Fl[sd][0]]
        if len(reg) > 1:
            idx = np.array(reg)
            v = (N[idx] * A[idx][:, None]).sum(0); v /= np.linalg.norm(v)
            oo = P[np.unique(F[idx])].mean(0); nn = v
            reg = grow(sd, oo.tolist(), nn.tolist())
        rid = len(regions)
        for t in reg:
            labl[t] = rid
        regions.append({"prim": {"type": "plane", "n": nn, "o": oo}, "tris": np.array(reg), "curved": False})
    lab = np.array(labl, dtype=np.int64)

    # region boundary: directed edges + undirected boundary edges
    bdir = defaultdict(list)
    eu = {}
    for t in range(nf):
        for k in range(3):
            u = nbr[t, k]
            if lab[u] != lab[t]:
                i, j = int(F[t, k]), int(F[t, (k + 1) % 3])
                bdir[int(lab[t])].append((i, j))
                eu[(min(i, j), max(i, j))] = (min(lab[t], lab[u]), max(lab[t], lab[u]))
    elist = list(eu.items())
    adj = defaultdict(list)
    for idx, ((i, j), _) in enumerate(elist):
        adj[i].append(idx); adj[j].append(idx)
    corner = {v: (len(es) != 2 or elist[es[0]][1] != elist[es[1]][1]) for v, es in adj.items()}
    visited = [False] * len(elist)
    chains_raw = []
    def walk(sv, e):
        vs = [sv]; cur = sv
        while True:
            visited[e] = True
            (i, j), _ = elist[e]
            cur = j if i == cur else i
            vs.append(cur)
            if corner[cur] or cur == sv:
                break
            e = [x for x in adj[cur] if x != e][0]
            if visited[e]:
                break
        return vs
    for v, es in adj.items():
        if corner[v]:
            for e in es:
                if not visited[e]:
                    chains_raw.append(walk(v, e))
    for e in range(len(elist)):
        if not visited[e]:
            chains_raw.append(walk(elist[e][0][0], e))
    chains, dir2chain = [], {}
    for vs in chains_raw:
        if vs[0] == vs[-1]:
            r = vs[:-1]; s = r.index(min(r)); r = r[s:] + r[:s]
            if len(r) > 2 and r[1] > r[-1]:
                r = [r[0]] + r[:0:-1]
            vs = r + [r[0]]
        elif vs[0] > vs[-1]:
            vs = vs[::-1]
        ci = len(chains); chains.append(vs)
        for a, b in zip(vs[:-1], vs[1:]):
            dir2chain[(a, b)] = (ci, 1); dir2chain[(b, a)] = (ci, -1)

    verts = {}
    def V(i):
        if i not in verts:
            verts[i] = BRepBuilderAPI_MakeVertex(gp_Pnt(*[float(x) for x in P[i]])).Vertex()
        return verts[i]
    def line_edge(i, j):
        me = BRepBuilderAPI_MakeEdge(V(i), V(j))
        return me.Edge()
    chain_edges = {}
    ring_info = {}
    def edges_of(ci):
        if ci in chain_edges:
            return chain_edges[ci]
        vs = chains[ci]; closed = vs[0] == vs[-1]
        Q = P[vs]
        segs = _segment_chain(np, Q, closed, tol, diag)
        es = []
        for s in segs:
            kind, i, j = s[0], s[1], s[2]
            if kind in ("circ", "ring"):
                ctr, n, r = s[3]
                xd = Q[i] - ctr; xd = xd - (xd @ n) * n; xd /= np.linalg.norm(xd)
                circ = gp_Circ(gp_Ax2(gp_Pnt(*[float(x) for x in ctr]), gp_Dir(*[float(x) for x in n]),
                                      gp_Dir(*[float(x) for x in xd])), r)
                me = BRepBuilderAPI_MakeEdge(circ) if kind == "ring" else BRepBuilderAPI_MakeEdge(circ, V(vs[i]), V(vs[j]))
                if me.IsDone():
                    if kind == "ring":
                        ring_info[ci] = (ctr, n, r)
                    es.append(me.Edge()); continue
            for k in range(i, j):
                es.append(line_edge(vs[k], vs[k + 1]))
        chain_edges[ci] = es
        return es

    def surface_of(pr):
        if pr["type"] == "plane":
            return Geom_Plane(gp_Pln(gp_Pnt(*[float(x) for x in pr["o"]]), gp_Dir(*[float(x) for x in pr["n"]])))
        ax = gp_Ax3(gp_Pnt(*[float(x) for x in pr["c"]]), gp_Dir(*[float(x) for x in pr["a"]])) if pr["type"] != "sphere" \
            else gp_Ax3(gp_Pnt(*[float(x) for x in pr["c"]]), gp_Dir(0, 0, 1))
        if pr["type"] == "cyl":
            return Geom_CylindricalSurface(ax, pr["R"])
        if pr["type"] == "torus":
            return Geom_ToroidalSurface(ax, pr["R"], pr["r"])
        if pr["type"] == "sphere":
            return Geom_SphericalSurface(ax, pr["R"])
        # cone: place location at mean height
        a, apex, al = pr["a"], pr["c"], pr["alpha"]
        h = float(((X[pr_tris] - apex) @ a).mean()) if False else 1.0
        return None

    faces, bad = [], set()
    for ri, rg in enumerate(regions):
        pr = rg["prim"]
        # chain uses
        uses = {}
        for (i, j) in bdir[ri]:
            ci, sg = dir2chain[(i, j)]
            uses[ci] = sg
        ulist = []
        for ci, sg in uses.items():
            vs = chains[ci]
            ulist.append((ci, sg, vs[0] if sg > 0 else vs[-1], vs[-1] if sg > 0 else vs[0]))
        bys = defaultdict(list)
        for u in ulist:
            bys[u[2]].append(u)
        loops, used = [], set()
        okloops = True
        for u in ulist:
            if u[0] in used:
                continue
            loop = [u]; used.add(u[0]); cur = u
            while cur[3] != u[2]:
                c = [x for x in bys[cur[3]] if x[0] not in used]
                if not c:
                    okloops = False; break
                cur = c[0]; used.add(cur[0]); loop.append(cur)
            if not okloops:
                break
            loops.append(loop)
        if not okloops:
            bad.add(ri); continue
        # surface
        if pr["type"] == "cone":
            g = rg["tris"]
            h = float(((X[g] - pr["c"]) @ pr["a"]).mean())
            loc = pr["c"] + pr["a"] * h
            surf = Geom_ConicalSurface(gp_Ax3(gp_Pnt(*[float(x) for x in loc]), gp_Dir(*[float(x) for x in pr["a"]])),
                                       pr["alpha"], abs(h) * float(np.tan(pr["alpha"])))
        else:
            surf = surface_of(pr)
        wires = []
        areas = []
        for loop in loops:
            mw = BRepBuilderAPI_MakeWire()
            ptsl = []
            for (ci, sg, sv, ev) in loop:
                es = edges_of(ci)
                for e in (es if sg > 0 else [st(TopoDS, 'Edge')(x.Reversed()) for x in es[::-1]]):
                    mw.Add(e)
                vs = chains[ci]
                ptsl += (vs[:-1] if sg > 0 else vs[:0:-1])
            if not mw.IsDone():
                okloops = False; break
            wires.append(mw.Wire())
            if pr["type"] == "plane":
                Q = P[ptsl]; o = Q[0]
                s = np.zeros(3)
                for k in range(1, len(Q) - 1):
                    s += np.cross(Q[k] - o, Q[k + 1] - o)
                areas.append(float(s @ pr["n"]))
            else:
                areas.append(0.0)
        if not okloops:
            bad.add(ri); continue
        order = sorted(range(len(wires)), key=lambda k: -areas[k])
        face = None
        mesh_area = float(A[rg["tris"]].sum())
        def area_ok(fc):
            if pr["type"] == "plane":
                return True
            g_ = GProp_GProps(); BRepGProp.SurfaceProperties_s(fc, g_)
            return 0.8 <= g_.Mass() / max(mesh_area, 1e-12) <= 1.25
        try:
            combos = [(f_, sw_) for f_ in (False, True) for sw_ in ((False, True) if len(wires) == 2 else (False,))]
            for flip, swap in combos:
                ws = [st(TopoDS, "Wire")(w.Reversed()) if flip else w for w in wires]
                od = order[::-1] if swap else order
                mf = BRepBuilderAPI_MakeFace(surf, ws[od[0]], True)
                for k in od[1:]:
                    mf.Add(ws[k])
                fix = ShapeFix_Face(mf.Face()); fix.SetPrecision(tol); fix.Perform()
                if BRepCheck_Analyzer(fix.Face()).IsValid() and area_ok(fix.Face()):
                    face = fix.Face()
                    break
        except Exception as ex:
            log("  face %d (%s) failed: %s" % (ri, pr["type"], ex))
        if face is None and pr["type"] == "sphere" and len(loops) == 1 and len(loops[0]) == 1 and loops[0][0][0] in ring_info:
            try:
                ctr, n, r = ring_info[loops[0][0][0]]
                sc, R = pr["c"], pr["R"]
                side = float(((X[rg["tris"]] - sc) @ n).mean())
                d = n if side >= 0 else -n
                vlat = float(np.arcsin(max(-1.0, min(1.0, ((ctr - sc) @ d) / R))))
                sph = Geom_SphericalSurface(gp_Ax3(gp_Pnt(*[float(x) for x in sc]), gp_Dir(*[float(x) for x in d])), R)
                mf = BRepBuilderAPI_MakeFace(sph, 0.0, 2 * np.pi, vlat, np.pi / 2, 1e-7)
                fix = ShapeFix_Face(mf.Face()); fix.SetPrecision(tol); fix.Perform()
                if BRepCheck_Analyzer(fix.Face()).IsValid():
                    face = fix.Face()
            except Exception as ex:
                log("  sphere cap failed: %s" % ex)
        if face is None:
            log("  region %d (%s) invalid: loops=%s" % (ri, pr["type"], [len(l) for l in loops]))
            if os.environ.get("STL2STEP_DEBUG"):
                for lp in loops:
                    log("     loop: " + " | ".join("chain%d(%dv, neighbours %s/%s, %d edges)" % (
                        ci, len(chains[ci]), regions[eu[(min(chains[ci][0], chains[ci][1]), max(chains[ci][0], chains[ci][1]))][0]]["prim"]["type"], regions[eu[(min(chains[ci][0], chains[ci][1]), max(chains[ci][0], chains[ci][1]))][1]]["prim"]["type"], len(edges_of(ci))) for (ci, sg, sv, ev) in lp))
            bad.add(ri)
        else:
            faces.append(face)
    if bad:
        return None, set(i for i in bad if regions[i]["curved"]), len(bad), regions
    sew = BRepBuilderAPI_Sewing(tol * 0.2)
    for f in faces:
        sew.Add(f)
    sew.Perform()
    shape = sew.SewedShape()
    ex = TopExp_Explorer(shape, TopAbs_SHELL)
    if not ex.More():
        return None, set(), -1, regions
    shell = st(TopoDS, "Shell")(ex.Current())
    sfs = ShapeFix_Shell(shell); sfs.Perform(); shell = sfs.Shell()
    solid = BRepBuilderAPI_MakeSolid(shell).Solid()
    sfo = ShapeFix_Solid(solid); sfo.Perform()
    solid = sfo.Solid()
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(solid, g)
    return (solid, g.Mass()), set(), 0, regions


def smart_convert(tris, path, tol_frac, ang_deg, min_tris, merge_deg, log=print):
    try:
        import numpy as np
        from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.BRepCheck import BRepCheck_Analyzer
    except ImportError as e:
        log("  curved-surface mode needs:  pip install numpy cadquery-ocp   (%s)" % e)
        return False
    P, F, N, A, diag = _prep(np, tris)
    nbr, closed = _adjacency(np, F, len(P))
    if not closed:
        log("  mesh is not watertight -> curved-surface mode needs a closed mesh")
        return False
    X = P[F].mean(1)
    tol = diag * tol_frac
    t0 = time.time()
    curved = detect_primitives(np, P, F, N, A, X, nbr, diag, tol, ang_deg, min_tris)
    cnt = defaultdict(int)
    for c in curved:
        cnt[c["prim"]["type"]] += 1
    log("  detected curved surfaces: %s (%.1fs)" % (dict(cnt) or "none", time.time() - t0))
    mesh_vol = float(np.einsum("ij,ij->", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])) / 6.0)
    for attempt in range(3):
        try:
            res, bad, nbad, regions = build_brep(np, P, F, N, A, X, nbr, curved, diag, tol, merge_deg, log)
        except Exception as ex:
            log("  build error: %s" % ex)
            return False
        if res is None:
            if bad:
                log("  %d curved region(s) could not be built exactly; keeping them as flat facets" % len(bad))
                curved = [c for i, c in enumerate(curved) if i not in bad]
                # regions index == curved index for curved regions (they come first)
                continue
            if attempt == 0 and curved:
                log("  could not assemble solid; retrying with planes only")
                curved = []
                continue
            return False
        solid, vol = res
        if abs(abs(vol) - abs(mesh_vol)) > 0.05 * abs(mesh_vol):
            log("  volume mismatch (%.1f vs %.1f)" % (vol, mesh_vol))
            if curved:
                curved = []
                continue
            return False
        w = STEPControl_Writer()
        w.Transfer(solid, STEPControl_AsIs)
        if w.Write(path) != IFSelect_RetDone:
            return False
        kinds = defaultdict(int)
        for r in regions:
            kinds[r["prim"]["type"]] += 1
        tot_a = float(A.sum())
        lab_ = -np.ones(len(F), dtype=np.int64)
        for ri_, r in enumerate(regions):
            lab_[r["tris"]] = ri_
        cos35 = np.cos(np.radians(35))
        small_n, fa = 0, 0.0
        for ri_, r in enumerate(regions):
            if r["curved"] or len(r["tris"]) > 6:
                continue
            tot_e = sm_e = 0
            for t in r["tris"]:
                for k in range(3):
                    u = nbr[t, k]
                    if u >= 0 and lab_[u] != ri_:
                        tot_e += 1
                        sm_e += int(N[t] @ N[u] > cos35)
            if tot_e and sm_e >= 0.5 * tot_e:
                small_n += 1; fa += float(A[r["tris"]].sum())
        log("  faceted leftovers: %.1f%% of surface area in %d small flat faces" % (100.0 * fa / tot_a, small_n))
        log("  wrote %s  faces: %s  volume %.2f (mesh %.2f)" % (path, dict(kinds), abs(vol), abs(mesh_vol)))
        return True
    return False

def scad_to_stl(scad, stl):
    exe = shutil.which("openscad") or shutil.which("openscad.com") or shutil.which("openscad.exe")
    if not exe:
        for p in (r"C:\Program Files\OpenSCAD\openscad.exe",
                  "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"):
            if os.path.exists(p):
                exe = p
    if not exe:
        sys.exit("OpenSCAD not found. Install it from openscad.org, or in OpenSCAD "
                 "press F6 then F7 to export an STL and convert that file.")
    subprocess.run([exe, "-o", stl, scad], check=True)



def _convert_step(src, dst, a):
    print("Converting", src)
    tris = read_stl(src)
    if not tris:
        sys.exit("  No triangles found - is this a valid STL?")
    print("  %d triangles read" % len(tris))
    if not a.no_repair:
        tris = repair_tris(tris)
    if not a.no_curves:
        if smart_convert(tris, dst, a.tol, a.ang, a.min_tris, a.angle):
            return
        print("  falling back to flat-facet STEP")
    write_step(tris, dst, os.path.splitext(os.path.basename(dst))[0], not a.no_merge, min(a.angle, 0.05))


def convert(src, dst, a):
    _convert_step(src, dst, a)
    if getattr(a, "sldprt", False) and os.path.exists(dst):
        try:
            import win32com.client
            import step2sldprt
        except ImportError as e:
            print("  SolidWorks Part skipped: needs Windows, SolidWorks and  pip install pywin32  (%s)" % e)
            return
        out = os.path.splitext(dst)[0] + ".SLDPRT"
        try:
            sw = win32com.client.Dispatch("SldWorks.Application")
            sw.Visible = True
            step2sldprt.convert(sw, dst, out)
            print("  saved", out)
        except Exception as e:
            print("  SolidWorks Part failed: %s  (the STEP file is still saved)" % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out")
    ap.add_argument("--sldprt", action="store_true", help="also save a SolidWorks .SLDPRT (Windows + SolidWorks + pywin32)")
    ap.add_argument("--no-curves", action="store_true", help="skip curved-surface recovery")
    ap.add_argument("--tol", type=float, default=5e-4, help="fit tolerance as fraction of part size (raise for noisy meshes)")
    ap.add_argument("--ang", type=float, default=8.0, help="normal tolerance in degrees for curved fits")
    ap.add_argument("--min-tris", type=int, default=10)
    ap.add_argument("--no-repair", action="store_true", help="do not close holes / fix flipped triangles")
    ap.add_argument("--no-merge", action="store_true")
    ap.add_argument("--angle", type=float, default=3.0, help="max angle (deg) to merge neighbouring flat triangles")
    a = ap.parse_args()
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    for src in a.inputs:
        base = os.path.splitext(os.path.basename(src))[0]
        dst = os.path.join(a.out or os.path.dirname(os.path.abspath(src)), base + ".step")
        if src.lower().endswith(".scad"):
            with tempfile.TemporaryDirectory() as td:
                tmp = os.path.join(td, base + ".stl")
                scad_to_stl(src, tmp)
                convert(tmp, dst, a)
        else:
            convert(src, dst, a)


if __name__ == "__main__":
    main()

