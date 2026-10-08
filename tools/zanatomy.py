#!/usr/bin/env python3
"""Fill BodyParts3D's gaps (peripheral nerves, the neck/head stretch of the big vessels,
spinal nerve roots...) with geometry from Z-Anatomy, warped onto the BodyParts3D skeleton.

Usage:
  python3 tools/zanatomy.py <Z-Anatomy/Startup.blend> <dir with BP3D .txt tables> \
      <dir with isa_BP3D_4.0_obj_99> <out dir>
then pass  --extra=<out dir>  to tools/build_data.py.

Source: https://github.com/Z-Anatomy/Models-of-human-anatomy  (Z-Anatomy.zip -> Startup.blend,
Blender 3.5 file), CC BY-SA 4.0, itself derived from BodyParts3D. Needs numpy, scipy and
blender-asset-tracer (pure-Python .blend reader; Blender itself is not needed).

How it works
1. Every BP3D bone and organ that has a Z-Anatomy twin (matched by name) gets its own
   similarity transform by ICP (median residual < 1 mm). Z-Anatomy re-posed the body slightly,
   so one global transform is off by 10-30 mm in places. A point is moved by the
   inverse-distance blend of its 4 nearest anchors' transforms. Vessels are hand-drawn in
   Z-Anatomy, so even after warping they sit 5-12 mm off BP3D's namesakes (see NAMESAKE_TOL).
2. Nerves and vessels in Z-Anatomy are Bezier curves with a bevel; they are turned into tubes
   here (radius = bevel depth x per-point radius). Ganglia, the dural sac etc. are meshes.
3. Gap filling: a curve sample is "covered" when BP3D already has geometry of the same kind
   within (tube radius + TOL) of it. Only uncovered runs are kept, so nothing is drawn twice
   where BP3D already has the vessel/nerve. For meshes, fully covered triangles are dropped.

Output: <out>/<slug>.obj per structure + <out>/manifest.json [{name, system, file, zname}].
"""
import json
import os
import pathlib
import re
import sys

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(__file__))
import structures as st  # noqa: E402
from build_data import read_obj, weld  # noqa: E402

from blender_asset_tracer import blendfile  # noqa: E402

TOL = 4.0          # mm: warp error allowance when deciding whether BP3D already covers a point
NAMESAKE_TOL = 12.0  # mm: same, against the BP3D structure with the same name. Z-Anatomy's
                     # vessels are hand-drawn curves; after warping they sit 5-12 mm off BP3D's
                     # MRI-derived namesakes (femoral 7, brachial 4.5, great saphenous 12).
MESH_TOL = 2.5     # mm: same, for mesh vertices
SEG_SAMPLES = 4    # samples per Bezier span
MIN_R = 0.35       # mm

# Z-Anatomy collection -> our system ("auto-vessel": by name)
COLLECTIONS = {
    "Peripheral nervous system": "nerves",
    "Central nervous system": "nerves",
    "Systemic arteries": "arteries",
    "Systemic veins": "veins",
    "Pulmonary vessels": "auto-vessel",
    "6: Lymphoid organs": "lymph",   # BP3D has no lymph nodes at all
}
# Objects also linked into these top-level collections are not nerves/vessels (Z-Anatomy
# links e.g. every muscle into "Peripheral nervous system" to show its innervation).
FOREIGN = ["1: Skeletal system", "2: Muscular insertions", "3: Joints", "4: Muscular system",
           "6: Lymphoid organs", "8: Visceral systems", "9: Regions of human body"]
MIN_STEP = 0.8     # mm: thin out curve samples closer than this (some curves are very dense)
# Not lymph nodes, or already in BP3D (thymus -> endocrine, spleen/tonsils -> digestive).
LYMPH_SKIP = re.compile(r"thymus|spleen|splenic|tonsil|bone marrow", re.I)
# Organs used as extra warp anchors (vessels around the kidneys/gut/brain sit far from bone).
ANCHOR_COLLECTIONS = ["8: Visceral systems", "Heart", "Central nervous system"]
# From the central nervous system only the spinal parts; the brain comes from BP3D.
CNS_KEEP = re.compile(r"spinal dura|cauda equina|root of spinal nerve|spinal ganglion|nerve to", re.I)
# BP3D systems a Z structure is checked against for coverage
COVER = {
    "nerves": ("nerves", "brain", "senses"),
    "arteries": ("arteries", "veins", "heart"),
    "veins": ("arteries", "veins", "heart"),
    "lymph": ("endocrine", "digestive", "respiratory"),  # spleen, thymus, tonsils already exist
}


# ---------- .blend reading ----------
def lb(block, field):
    p = block.get_pointer((field, b"first"))
    while p is not None:
        yield p
        p = p.get_pointer(b"next")


def nm(b):
    return b.id_name.decode("utf8", "replace")[2:]


class Blend:
    def __init__(self, path):
        self.bf = blendfile.open_cached(pathlib.Path(path))
        self.order = list(self.bf.blocks)
        self.pos = {id(b): i for i, b in enumerate(self.order)}
        self.ps = self.bf.header.pointer_size

    def local(self, idb):
        """Pointers are only unique among the DATA blocks that follow their ID block
        (that's how Blender resolves them), so never use a file-wide address lookup."""
        i = self.pos[id(idb)] + 1
        m = {}
        while i < len(self.order) and self.order[i].code == b"DATA":
            m.setdefault(self.order[i].addr_old, self.order[i])
            i += 1
        return m

    def deref(self, idb, addr, sname):
        b = self.local(idb).get(addr)
        if b is not None:
            b.refine_type_from_index(self.bf.sdna_index_from_id[sname])
        return b

    def arr(self, block, fields, n):
        stc = block.dna_type
        raw = np.frombuffer(block.raw_data(), dtype=np.uint8)
        n = min(n, len(raw) // stc.size)
        raw = raw[: n * stc.size].reshape(n, stc.size)
        out = {}
        for f, (dt, k) in fields.items():
            _, off = stc.field_from_path(self.ps, f)
            w = np.dtype(dt).itemsize * k
            a = raw[:, off:off + w].copy().view(dt)
            out[f] = a.reshape(n, k) if k > 1 else a.reshape(n)
        return out

    def collection_objects(self, name):
        gr = {}
        for g in self.bf.code_index[b"GR"]:
            gr.setdefault(nm(g), g)
        out, seen = [], set()

        def walk(g):
            for co in lb(g, b"gobject"):
                o = co.get_pointer(b"ob")
                if o is not None and o.addr_old not in seen:
                    seen.add(o.addr_old)
                    out.append(o)
            for c in lb(g, b"children"):
                walk(c.get_pointer(b"collection"))
        walk(gr[name])
        return out

    @staticmethod
    def matrix(o):
        return np.array(o.get(b"obmat"), dtype=float).reshape(4, 4)  # row i = basis vector i, row 3 = translation

    def cd_block(self, me, cd, typ, sname):
        lay = me.get_pointer((cd, b"layers"))
        if lay is None:
            return None
        stc, raw = lay.dna_type, lay.raw_data()
        _, toff = stc.field_from_path(self.ps, b"type")
        _, doff = stc.field_from_path(self.ps, b"data")
        for i in range(me.get((cd, b"totlayer"))):
            r = raw[i * stc.size:(i + 1) * stc.size]
            if int.from_bytes(r[toff:toff + 4], "little") == typ:
                return self.deref(me, int.from_bytes(r[doff:doff + self.ps], "little"), sname)
        return None

    def mesh(self, o):
        """World-space (metres) vertices + triangles of a legacy-format mesh object."""
        me = o.get_pointer(b"data")
        vb = self.cd_block(me, b"vdata", 0, b"MVert")
        pb = self.cd_block(me, b"pdata", 25, b"MPoly")
        lb_ = self.cd_block(me, b"ldata", 26, b"MLoop")
        if vb is None or pb is None or lb_ is None:
            return None, None
        v = self.arr(vb, {b"co": ("<f4", 3)}, me.get(b"totvert"))[b"co"].astype(float)
        p = self.arr(pb, {b"loopstart": ("<i4", 1), b"totloop": ("<i4", 1)}, me.get(b"totpoly"))
        loops = self.arr(lb_, {b"v": ("<u4", 1)}, me.get(b"totloop"))[b"v"].astype(np.int64)
        tris = []
        for s, n in zip(p[b"loopstart"], p[b"totloop"]):
            for k in range(1, n - 1):
                tris.append((loops[s], loops[s + k], loops[s + k + 1]))
        f = np.array(tris, dtype=np.int64).reshape(-1, 3)
        M = self.matrix(o)
        return v @ M[:3, :3] + M[3, :3], f

    def splines(self, o):
        """Bezier splines as (points[n,3] world metres, handles_l, handles_r, radius[n] metres, cyclic)."""
        cu = o.get_pointer(b"data")
        depth = cu.get(b"ext2")
        M = self.matrix(o)
        scale = abs(np.linalg.det(M[:3, :3])) ** (1 / 3)
        out = []
        for n in lb(cu, b"nurb"):
            cnt = n.get(b"pntsu")
            if n.get(b"type") == 1:  # CU_BEZIER
                bz = n.get_pointer(b"bezt")
                if bz is None:
                    continue
                a = self.arr(bz, {b"vec": ("<f4", 9), b"radius": ("<f4", 1)}, cnt)
                vec = a[b"vec"].reshape(-1, 3, 3).astype(float)
                h1, p, h2 = (vec[:, k] @ M[:3, :3] + M[3, :3] for k in range(3))
                rad = a[b"radius"].astype(float)
            else:  # poly / NURBS: use the control polygon
                bp = n.get_pointer(b"bp")
                if bp is None:
                    continue
                a = self.arr(bp, {b"vec": ("<f4", 4), b"radius": ("<f4", 1)}, cnt)
                p = a[b"vec"][:, :3].astype(float) @ M[:3, :3] + M[3, :3]
                h1 = h2 = None
                rad = a[b"radius"].astype(float)
            out.append((p, h1, h2, rad * depth * scale, bool(n.get(b"flagu") & 1)))
        return out


# ---------- names ----------
def clean_name(z):
    """'Internal carotid artery.l' -> 'left internal carotid artery'; keeps '(X)' style labels."""
    n = z.strip().rstrip("'").rstrip(".")
    n = re.sub(r"\s*\(//.*?\)", "", n)
    side = ""
    m = re.search(r"\.(l|r)$", n)
    if m:
        side = "left " if m.group(1) == "l" else "right "
        n = n[:-2]
    n = n.strip()
    head, paren = re.match(r"^(.*?)(\s*\(.*\))?$", n).groups()
    if not head.strip() and paren:  # '(Fibular node)': a label with no TA name -> use the label
        head, paren = paren.strip()[1:-1], None
    head = head[:1].lower() + head[1:]
    if re.match(r"(left|right) ", head):  # 'Right testicular artery.r'
        side = ""
    return (side + head + (paren or "")).strip()


def merge_key(name):
    return re.sub(r"\s*\(.*?\)", "", name).strip().lower()


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]


# ---------- warp ----------
def umeyama(A, B):
    ma, mb = A.mean(0), B.mean(0)
    a, b = A - ma, B - mb
    U, S, Vt = np.linalg.svd(b.T @ a / len(A))
    D = np.eye(3)
    if np.linalg.det(U @ Vt) < 0:
        D[2, 2] = -1
    R = U @ D @ Vt
    s = np.trace(np.diag(S) @ D) / ((a ** 2).sum() / len(A))
    return s, R, mb - s * R @ ma


def icp(Z, P, iters=40):
    tree = cKDTree(P)
    s, R, t = 1.0, np.eye(3), P.mean(0) - Z.mean(0)
    for _ in range(iters):
        d, i = tree.query((s * (R @ Z.T)).T + t)
        keep = d <= np.percentile(d, 90)
        s, R, t = umeyama(Z[keep], P[i[keep]])
    d, _ = tree.query((s * (R @ Z.T)).T + t)
    return (s, R, t), float(np.median(d))


ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth"]
FINGER = {"first": "thumb", "second": "index finger", "third": "middle finger", "fourth": "ring finger", "fifth": "little finger"}
TOE = {"first": "big toe", "second": "second toe", "third": "third toe", "fourth": "fourth toe", "fifth": "little toe"}
CARPAL = ("scaphoid", "lunate", "triquetral", "pisiform", "trapezium", "trapezoid", "capitate", "hamate", "ethmoid")


def bone_key(z):
    """Z-Anatomy bone name -> BP3D bone name (lowercase)."""
    m = re.match(r"Vertebra ([CTL])(\d+)$", z.strip())
    if m:
        return f"{ORD[int(m.group(2)) - 1]} {dict(C='cervical', T='thoracic', L='lumbar')[m.group(1)]} vertebra"
    s = merge_key(clean_name(z))
    side = ""
    for p in ("left ", "right "):
        if s.startswith(p):
            side, s = p, s[len(p):]
    m = re.match(r"(distal|middle|proximal) phalanx of (\w+) finger of (hand|foot)$", s)
    if m:
        return f"{m.group(1)} phalanx of {side}{(FINGER if m.group(3) == 'hand' else TOE)[m.group(2)]}"
    if s.split(" ")[0] in CARPAL:
        s = re.sub(r" bone$", "", s)
    if s == "manubrium of sternum":
        s = "manubrium"
    return side + s


class Warp:
    def __init__(self, pairs, k=4):
        self.T, pts, lab = [], [], []
        errs, skipped = [], []
        for name, Z, P, (max_err, max_scale) in pairs:
            T, err = icp(Z, P)
            if err > max_err or abs(T[0] - 1) > max_scale:  # partial / mismatched twin: don't trust it
                skipped.append(name)
                continue
            errs.append(err)
            self.T.append(T)
            sub = Z[:: max(1, len(Z) // 200)]
            pts.append(sub)
            lab += [len(self.T) - 1] * len(sub)
        print(f"  warp: {len(self.T)} anchors, median ICP residual {np.median(errs):.2f} mm; "
              f"{len(skipped)} rejected (bones: residual > 5 mm or scale off > 15%; organs: 3 mm / 10%): {', '.join(skipped)}")
        self.tree = cKDTree(np.vstack(pts))
        self.lab = np.array(lab)
        self.k = k

    def __call__(self, X):
        d, i = self.tree.query(X, k=48)
        out = np.empty_like(X)
        for r in range(len(X)):
            best = {}
            for dd, ii in zip(d[r], i[r]):
                b = self.lab[ii]
                if b not in best:
                    best[b] = dd
                    if len(best) == self.k:
                        break
            w = np.array([1.0 / max(v, 1.0) ** 2 for v in best.values()])
            w /= w.sum()
            acc = np.zeros(3)
            for wb, b in zip(w, best):
                s, R, t = self.T[b]
                acc += wb * (s * R @ X[r] + t)
            out[r] = acc
        return out


# ---------- geometry ----------
def bezier(p, h1, h2, rad, cyclic):
    n = len(p)
    if h1 is None or n < 2:
        return p, rad
    pts, rs = [], []
    spans = n if cyclic else n - 1
    for i in range(spans):
        j = (i + 1) % n
        for k in range(SEG_SAMPLES):
            t = k / SEG_SAMPLES
            u = 1 - t
            pts.append(u ** 3 * p[i] + 3 * u * u * t * h2[i] + 3 * u * t * t * h1[j] + t ** 3 * p[j])
            rs.append(u * rad[i] + t * rad[j])
    if not cyclic:
        pts.append(p[-1])
        rs.append(rad[-1])
    return np.array(pts), np.array(rs)


def thin(c, r):
    keep, last = [0], c[0]
    for i in range(1, len(c) - 1):
        if np.linalg.norm(c[i] - last) * 1000 >= MIN_STEP:
            keep.append(i)
            last = c[i]
    keep.append(len(c) - 1)
    return c[keep], r[keep]


def tube(c, r):
    """Tube along polyline c (mm) with per-point radius r: parallel-transport frames."""
    keep = np.r_[True, np.linalg.norm(np.diff(c, axis=0), axis=1) > 1e-6]
    c, r = c[keep], r[keep]
    if len(c) < 2:
        return None, None
    sides = 8 if r.max() >= 1.5 else 6
    T = np.gradient(c, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    a = np.array([0.0, 0.0, 1.0]) if abs(T[0][2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    N = np.cross(T[0], a)
    N /= np.linalg.norm(N)
    verts = []
    ang = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    for i in range(len(c)):
        if i:
            N = N - T[i] * (N @ T[i])
            N /= np.linalg.norm(N) + 1e-12
        B = np.cross(T[i], N)
        verts.append(c[i] + r[i] * (np.cos(ang)[:, None] * N + np.sin(ang)[:, None] * B))
    V = np.vstack(verts)
    F = []
    for i in range(len(c) - 1):
        for k in range(sides):
            a0, a1 = i * sides + k, i * sides + (k + 1) % sides
            b0, b1 = a0 + sides, a1 + sides
            F += [(a0, b0, a1), (a1, b0, b1)]
    # end caps (fan)
    for end in (0, len(c) - 1):
        cen = len(V)
        V = np.vstack([V, c[end]])
        base = end * sides
        for k in range(sides):
            F.append((cen, base + k, base + (k + 1) % sides))
    return V, np.array(F, dtype=np.int64)


def runs(mask, min_len=3):
    """Index ranges [a, b) of consecutive True values, widened by one sample each side."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if j - i >= min_len:
                out.append((max(0, i - 1), min(n, j + 1)))
            i = j
        else:
            i += 1
    return out


def struct_points(s, isa_dir):
    pts = []
    for e in s["elements"]:
        p = os.path.join(isa_dir, e + ".obj")
        if os.path.exists(p):
            v, f = read_obj(p)
            pts.append(v)
            if len(f):
                pts.append(v[f].mean(1))  # face centroids densify sparse meshes
    return np.vstack(pts) if pts else None


def unsided(key):
    return re.sub(r"^(left|right) ", "", key)


def main():
    blend, tables, isa_dir, out = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    structs = st.load(tables)

    print("loading BP3D skeleton + reference geometry")
    bones = {}
    for s in structs:
        if s["system"] != "skeleton":
            continue
        vs = [read_obj(os.path.join(isa_dir, e + ".obj"))[0] for e in s["elements"] if os.path.exists(os.path.join(isa_dir, e + ".obj"))]
        if vs:
            bones[s["name"].lower()] = np.vstack(vs)
    pts = {}
    for s in structs:
        if any(s["system"] in v for v in COVER.values()):
            p = struct_points(s, isa_dir)
            if p is not None:
                pts[s["id"]] = (s, p)
    trees = {}
    for key, systems in COVER.items():
        if systems not in trees:
            trees[systems] = cKDTree(np.vstack([p for s, p in pts.values() if s["system"] in systems]))
    namesake = {}  # (merge key, system) -> KD-tree of that BP3D structure (also under the unsided key)
    for s, p in pts.values():
        for k in {merge_key(s["name"]), unsided(merge_key(s["name"]))}:
            namesake.setdefault((k, s["system"]), []).append(p)
    namesake = {k: cKDTree(np.vstack(v)) for k, v in namesake.items()}
    bp_names = {(merge_key(s["name"]), s["system"]) for s in structs}

    print("reading", blend)
    B = Blend(blend)
    pairs = []
    for o in B.collection_objects("Skeletal system"):
        if o.get(b"type") != 1:
            continue
        k = bone_key(nm(o))
        if k in bones:
            V, F = B.mesh(o)
            if V is not None and len(V) >= 50:
                pairs.append((k, V * 1000, bones[k], (5.0, 0.15)))
    print(f"  {len(pairs)} bones paired by name")
    organs = {}
    for s in structs:
        if s["system"] not in ("skeleton", "muscles", "connective"):
            organs.setdefault(merge_key(s["name"]), s)
    seen = set()
    for coll in ANCHOR_COLLECTIONS:
        for o in B.collection_objects(coll):
            k = merge_key(clean_name(nm(o)))
            if o.get(b"type") != 1 or k not in organs or k in seen:
                continue
            V, F = B.mesh(o)
            P = struct_points(organs[k], isa_dir)
            if V is not None and len(V) >= 200 and P is not None:
                seen.add(k)
                pairs.append((k, V * 1000, P, (3.0, 0.10)))
    print(f"  + {len(seen)} organs paired by name as extra anchors")
    warp = Warp(pairs)

    result = {}  # name -> {"system", "zname", "v": [], "f": []}

    def add(name, system, zname, v, f):
        e = result.setdefault(name, {"system": system, "zname": zname, "v": [], "f": [], "n": 0})
        e["f"].append(f + e["n"])
        e["v"].append(v)
        e["n"] += len(v)

    members = {c: {o.addr_old for o in B.collection_objects(c)} for c in FOREIGN}
    skipped = covered = 0
    for coll, system0 in COLLECTIONS.items():
        for o in B.collection_objects(coll):
            z = nm(o)
            if any(o.addr_old in s for c, s in members.items() if c != coll):
                continue
            t = o.get(b"type")
            if t not in (1, 2) or re.search(r"\.(g|j|t|i|s|st)$", z) or "?" in z:
                continue
            if coll == "Central nervous system" and not CNS_KEEP.search(z):
                continue
            if system0 == "lymph" and LYMPH_SKIP.search(z):
                continue
            name = clean_name(z)
            system = system0
            if system == "auto-vessel":
                system = "veins" if re.search(r"vein", z, re.I) else "arteries"
            if system in ("arteries", "veins") and st.classify(name) == "heart":
                continue  # coronary vessels: BP3D's heart already has the full coronary tree
            tree = trees[COVER[system]]
            twin = namesake.get((merge_key(name), system)) or namesake.get((unsided(merge_key(name)), system))
            if t == 2:
                for p, h1, h2, rad, cyc in B.splines(o):
                    c, r = bezier(p, h1, h2, rad, cyc)
                    c, r = thin(c, r)
                    c = warp(c * 1000)
                    r = np.maximum(r * 1000, MIN_R)
                    d, _ = tree.query(c)
                    free = d > r + TOL
                    if twin is not None:
                        free &= twin.query(c)[0] > r + NAMESAKE_TOL
                    covered += int((~free).sum())
                    for a, b in runs(free):
                        V, F = tube(c[a:b], r[a:b])
                        if V is not None:
                            add(name, system, z, V, F)
            else:
                V, F = B.mesh(o)
                if V is None or len(F) < 4:
                    skipped += 1
                    continue
                V = warp(V * 1000)
                d, _ = tree.query(V)
                cov = d <= MESH_TOL
                if twin is not None:
                    cov |= twin.query(V)[0] <= NAMESAKE_TOL
                F = F[~cov[F].all(1)]
                if len(F) >= 4:
                    add(name, system, z, V, F)

    manifest = []
    for name, e in sorted(result.items()):
        v, f = weld(np.vstack(e["v"]), np.vstack(e["f"]), decimals=2)
        if len(f) < 8:
            continue
        fn = slug(name) + ".obj"
        with open(os.path.join(out, fn), "w") as fh:
            fh.write("".join(f"v {a:.3f} {b:.3f} {c:.3f}\n" for a, b, c in v))
            fh.write("".join(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in f))
        merges = (merge_key(name), e["system"]) in bp_names
        manifest.append({"name": name, "system": e["system"], "file": fn, "zname": e["zname"], "mergesInto": merges, "tris": int(len(f))})
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    by = {}
    for m in manifest:
        by.setdefault(m["system"], [0, 0, 0])
        by[m["system"]][0] += 1
        by[m["system"]][1] += m["tris"]
        by[m["system"]][2] += m["mergesInto"]
    print(f"wrote {len(manifest)} structures to {out}  ({covered} curve samples already covered by BP3D, {skipped} empty meshes)")
    for k, (n, t, mg) in by.items():
        print(f"  {k:10s} {n:4d} structures ({mg} extend a BP3D one), {t:,} tris")


if __name__ == "__main__":
    main()
