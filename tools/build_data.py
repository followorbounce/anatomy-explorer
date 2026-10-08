#!/usr/bin/env python3
"""Build the web data (data/mesh/<system>.bin + js/data/organs.js) from BodyParts3D 4.0.

Usage:
  python3 tools/build_data.py <dir with the dataset .txt tables> <dir with isa_BP3D_4.0_obj_99 (unzipped)> \
      [<dir with partof_BP3D_4.0_obj_99 (unzipped)>] [--budget-tris=N] [--extra=<tools/zanatomy.py out dir>]
      [--female=<tools/female.py out dir>]

--extra adds the Z-Anatomy gap-fill geometry (peripheral nerves, missing vessel stretches, lymph
nodes): a piece whose name matches a BP3D structure of the same system is appended to it, the
rest become new structures with id "ZA-<slug>".
--female adds tools/female.py's structures (id "F-<slug>", sex "f"), tags the male parts they
replace with sex "m" (mark_male), and derives a female skin (female_skin).

Source: https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST/  (CC BY-SA 2.1 Japan)
Needs numpy + fast_simplification.

Bundle format (little endian), one file per system, structures concatenated:
  per structure at byte offset `o`:  float32 positions[v*3]  then  uint32 indices[t*3]
Offsets / counts are listed per structure in js/data/organs.js.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import structures as st  # noqa: E402

try:
    import fast_simplification
except ImportError:  # pragma: no cover
    fast_simplification = None


def read_obj(path):
    verts, faces = [], []
    with open(path, "r", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                verts.append(line.split()[1:4])
            elif line.startswith("f "):
                idx = [int(tok.split("/")[0]) for tok in line.split()[1:]]
                for i in range(1, len(idx) - 1):  # fan-triangulate
                    faces.append((idx[0], idx[i], idx[i + 1]))
    return np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int64) - 1


def weld(v, f, decimals=3):
    key = np.round(v, decimals)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    v2 = v[first]
    f2 = inv[f.reshape(-1)].reshape(-1, 3)
    ok = (f2[:, 0] != f2[:, 1]) & (f2[:, 1] != f2[:, 2]) & (f2[:, 0] != f2[:, 2])
    return v2, f2[ok]


def compact(v, f):
    used = np.unique(f)
    remap = np.full(len(v), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return v[used], remap[f]


SIDE = {"left": "right", "right": "left"}


def fix_sides(structs, loaded):
    """Swap left/right in a name when the mesh sits unmistakably on the other side.
    (BP3D +x = subject's left.) Catches source quirks such as 'left flexor pollicis brevis'."""
    import re
    for s in structs:
        if s["id"] not in loaded:
            continue
        m = re.search(r"\b(left|right)\b", s["name"])
        if not m:
            continue
        cx = loaded[s["id"]][0][:, 0].mean()
        if abs(cx) > 100 and (cx > 0) != (m.group(1) == "left"):
            new = re.sub(r"\b(left|right)\b", lambda k: SIDE[k.group(1)], s["name"], count=1)
            print(f"side fix: {s['name']!r} (x={cx:.0f}) -> {new!r}")
            s["name"] = new


def drop_duplicates(structs, loaded):
    """Remove structures whose geometry is a near-exact copy of another one (same bbox
    within 0.6 mm and similar triangle count) — they z-fight when both are shown.
    The kept one is the earlier system / alphabetically first; a left/right twin pair
    that is really one midline object loses its side word."""
    import re
    order = {k: i for i, (k, _, _) in enumerate(st.SYSTEMS)}
    ids = [s for s in sorted(structs, key=lambda s: (order[s["system"]] if s["system"] != "other" else 99, s["name"])) if s["id"] in loaded]
    bb = np.array([np.r_[loaded[s["id"]][0].min(0), loaded[s["id"]][0].max(0)] for s in ids])
    nt = np.array([len(loaded[s["id"]][1]) for s in ids])
    dropped = set()
    for i, s in enumerate(ids):
        if s["id"] in dropped:
            continue
        near = np.where((np.abs(bb - bb[i]).max(1) < 0.6) & (nt / nt[i] > 0.7) & (nt / nt[i] < 1.43))[0]
        for j in near:
            if j <= i or ids[j]["id"] in dropped:
                continue
            o = ids[j]
            print(f"duplicate: dropping {o['name']!r} ({o['system']}), same geometry as {s['name']!r} ({s['system']})")
            dropped.add(o["id"])
            base = lambda n: re.sub(r"\b(left|right) ", "", n)
            if base(o["name"]) == base(s["name"]):
                s["name"] = base(s["name"])
    return [s for s in structs if s["id"] not in dropped]


def merge_extra(structs, loaded, extra_dir):
    """Append tools/zanatomy.py output to `structs` / `loaded` (see module docstring)."""
    import re
    key = lambda n: re.sub(r"\s*\(.*?\)", "", n).strip().lower()
    by = {(key(s["name"]), s["system"]): s for s in structs if s["id"] in loaded}
    with open(os.path.join(extra_dir, "manifest.json")) as fh:
        man = json.load(fh)
    grown = new = 0
    for m in man:
        v, f = read_obj(os.path.join(extra_dir, m["file"]))
        if not len(f):
            continue
        s = None if m.get("sex") else by.get((key(m["name"]), m["system"]))
        if s is not None:
            v0, f0 = loaded[s["id"]]
            loaded[s["id"]] = (np.vstack([v0, v]), np.vstack([f0, f + len(v0)]))
            s["source"] = "BodyParts3D + Z-Anatomy"
            grown += 1
        else:
            sid = ("F-" if m.get("sex") == "f" else "ZA-") + re.sub(r"[^a-z0-9]+", "-", m["name"].lower()).strip("-")
            structs.append({"id": sid, "name": m["name"], "system": m["system"], "elements": [], "source": m.get("src", "Z-Anatomy"),
                            **({"sex": m["sex"]} if m.get("sex") else {})})
            loaded[sid] = (v, f)
            new += 1
    print(f"extra: {grown} BP3D structures extended, {new} new structures from {extra_dir}")


# Male-only structures once a female set exists (BP3D and Z-Anatomy are both a male body).
MALE_ONLY = r"penis|penile|glans|\btest(is|es)\b|testicular|scrot|prostat|deferent|seminal|epididym|cremaster|spermatic|cavernous organ|^urethra$"


def mark_male(structs):
    """Tag the parts the female set replaces with sex "m" (the app shows sex-less parts in both)."""
    import re
    fem = {(s["system"], s["name"]) for s in structs if s.get("sex") == "f"}
    if not fem:
        return
    n = 0
    for s in structs:
        if s.get("sex"):
            continue
        if s["system"] == "genital" or re.search(MALE_ONLY, s["name"], re.I) or (s["system"], s["name"]) in fem or s["name"] == "skin":
            s["sex"] = "m"
            n += 1
    print(f"sex: {n} structures male-only, {len(fem)} female-only")


def fit_skin(final, structs, margin=1.0, max_push=12.0, reach=20.0, skin=None, points=None, spread_iters=3, soften_iters=2):
    """Push the skin surface outward *locally* wherever another structure touches or
    pokes through it (thin fascia/muscle sitting right under the skin, lips, ears...).
    Uniform inflation would fatten fingers and ears, so displacement is per-vertex.
    `skin` / `points` override which skin (v, f) is fitted and which points it must cover;
    the fitted (v, f) is then returned instead of written into `final`."""
    sk = next((s for s in structs if s["name"] == "skin" and s.get("sex") != "f" and s["id"] in final), None)
    if sk is None:
        return
    v, f = skin if skin is not None else final[sk["id"]]
    v = v.astype(np.float64)
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    vn = np.zeros_like(v)
    for k in range(3):
        np.add.at(vn, f[:, k], fn)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    S = v.astype(np.float32)
    S2 = (S ** 2).sum(1)

    # candidate points: vertices of structures that can sit near the surface
    pts = [] if points is None else [points]
    for s in (structs if points is None else ()):
        if s["id"] not in final or s["id"] == sk["id"] or s["name"] == "hair of head" or s.get("sex") == "f":
            continue
        if s["system"] in ("brain", "heart", "respiratory", "urinary", "endocrine"):
            continue
        if s["system"] == "senses" and not any(k in s["name"] for k in ("lip", "ear", "eyebrow", "cheek", "eyelid")):
            continue
        pts.append(final[s["id"]][0])
    P = np.vstack(pts).astype(np.float32)

    # orientation: interior points (skeleton centroids) must lie *behind* their nearest skin vertex
    inner = np.array([final[s["id"]][0].mean(0) for s in structs if s["system"] == "skeleton" and s["id"] in final], dtype=np.float32)
    d = (inner ** 2).sum(1)[:, None] - 2 * inner @ S.T + S2[None]
    j = d.argmin(1)
    if np.mean(np.einsum("ij,ij->i", inner - S[j], vn[j].astype(np.float32)) > 0) > 0.5:
        vn = -vn

    # cheap prefilter: keep points within ~one grid cell of any skin vertex
    cell = max(15.0, reach / 2)  # the prefilter keeps points within ~2 cells of the skin
    key = lambda a: (np.floor(a / cell).astype(np.int64) + 1000) @ np.array([1, 4001, 4001 * 4001])
    skin_cells = np.unique(key(S))
    keep = np.zeros(len(P), bool)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                off = np.array([dx, dy, dz]) * cell
                keep |= np.isin(key(P + off.astype(np.float32)), skin_cells)
    P = P[keep]
    need = np.zeros(len(S))
    for i in range(0, len(P), 2000):
        q = P[i:i + 2000]
        dd = (q ** 2).sum(1)[:, None] - 2 * q @ S.T + S2[None]
        jj = dd.argmin(1)
        diff = q - S[jj]
        dist = np.sqrt(np.maximum(dd[np.arange(len(q)), jj], 0))
        h = np.einsum("ij,ij->i", diff, vn[jj].astype(np.float32))
        req = h + margin
        ok = (dist < reach) & (req > 0) & (req <= max_push + margin)
        np.maximum.at(need, jj[ok], req[ok])

    # spread to neighbours (so a single vertex doesn't become a spike), then soften
    ei = np.r_[f[:, 0], f[:, 1], f[:, 2], f[:, 1], f[:, 2], f[:, 0]]
    ej = np.r_[f[:, 1], f[:, 2], f[:, 0], f[:, 0], f[:, 1], f[:, 2]]
    spread = need.copy()
    for _ in range(spread_iters):
        nxt = spread.copy()
        np.maximum.at(nxt, ei, spread[ej] * 0.9)
        spread = nxt
    soft = spread.copy()
    deg = np.bincount(ei, minlength=len(S)).astype(float)
    for _ in range(soften_iters):
        acc = np.zeros(len(S))
        np.add.at(acc, ei, soft[ej])
        soft = 0.5 * soft + 0.5 * acc / np.maximum(deg, 1)
    disp = np.maximum(soft, spread * 0.85)
    moved = disp > 0.05
    print(f"skin fit: {moved.sum()} of {len(S)} skin vertices pushed out (mean {disp[moved].mean():.1f} mm, max {disp.max():.1f} mm)")
    if skin is not None:
        return v + vn * disp[:, None], f
    final[sk["id"]] = (v + vn * disp[:, None], f)


MALE_EXTERNAL = r"glans|corpus cavernosum|cavernous organ|testis|epididym"


def female_skin(final, structs):
    """Female body surface derived from the (fitted) BP3D skin: the skin over the penis and
    scrotum is relaxed into a membrane spanning its base (vertices near those organs are
    repeatedly moved to the mean of their neighbours, the rest held fixed), then the skin is
    pushed out where the female pelvis touches it, and the breast surfaces are added. External
    female genitalia are not modelled."""
    import re
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    from scipy.spatial import cKDTree
    sk = next((s for s in structs if s["name"] == "skin" and s.get("sex") == "m" and s["id"] in final), None)
    fem = [s for s in structs if s.get("sex") == "f" and s["id"] in final]
    if sk is None or not fem:
        return
    v, f = final[sk["id"]]
    v = v.astype(np.float64).copy()
    gen = np.vstack([final[s["id"]][0] for s in structs
                     if s.get("sex") == "m" and s["id"] in final and re.search(MALE_EXTERNAL, s["name"])])
    # Skin within reach of the penis/testes is freed (that includes the whole scrotum and penile
    # skin, plus a margin of pubic/perineal/inner-thigh skin, which the solve just smooths).
    free = cKDTree(gen).query(v)[0] < 22.0
    ei = np.r_[f[:, 0], f[:, 1], f[:, 2], f[:, 1], f[:, 2], f[:, 0]]
    ej = np.r_[f[:, 1], f[:, 2], f[:, 0], f[:, 0], f[:, 1], f[:, 2]]
    A = sp.csr_matrix((np.ones(len(ei)), (ei, ej)), shape=(len(v), len(v)))
    A.data[:] = 1.0
    # Membrane: every free vertex = mean of its neighbours, fixed vertices as boundary (L_ff x_f = -L_fb x_b).
    L = sp.diags(np.asarray(A.sum(1)).ravel()) - A
    fi, bi = np.where(free)[0], np.where(~free)[0]
    Lff, Lfb = L[fi][:, fi].tocsc(), L[fi][:, bi]
    for k in range(3):
        v[fi, k] = spla.spsolve(Lff, -(Lfb @ v[bi, k]))
    print(f"female skin: {free.sum()} vertices over the male external genitalia relaxed into a membrane")
    pel = np.vstack([final[s["id"]][0] for s in fem if s["system"] == "skeleton"])
    v, f = fit_skin(final, structs, skin=(v, f), points=pel)  # same limits as the male fit: surface bumps only
    # Breasts: the HRA breast fat (+ nipple/areola) outer surface is the breast's own shape, so it
    # becomes part of the skin; the flat male chest skin underneath stays hidden inside it.
    for s in fem:
        if re.search(r"fatty tissue of breast|nipple", s["name"]):
            bv, bf = final[s["id"]]
            f = np.vstack([f, bf + len(v)])
            v = np.vstack([v, bv])
    structs.append({"id": "F-skin", "name": "skin", "system": "skin", "elements": [], "sex": "f",
                    "source": "BodyParts3D skin reshaped for the female set (breasts, no male genitalia)"})
    final["F-skin"] = (v, f)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    budget = 3_000_000
    extra = female = None
    for a in sys.argv[1:]:
        if a.startswith("--budget-tris="):
            budget = int(a.split("=")[1])
        elif a.startswith("--extra="):
            extra = a.split("=", 1)[1]
        elif a.startswith("--female="):
            female = a.split("=", 1)[1]
    tables, isa_dir = args[0], args[1]
    partof_dir = args[2] if len(args) > 2 else None
    out_root = os.path.join(os.path.dirname(__file__), "..")
    out_mesh = os.path.join(out_root, "data", "mesh")
    os.makedirs(out_mesh, exist_ok=True)

    structs = st.load(tables)
    sysdefs = {k: (label, kind) for k, label, kind in st.SYSTEMS}

    # 1) load + weld every structure
    loaded = {}
    total = 0
    for s in structs:
        vs, fs, off = [], [], 0
        for e in s["elements"]:
            p = os.path.join(isa_dir, e + ".obj")
            if not os.path.exists(p) and partof_dir:
                p = os.path.join(partof_dir, e + ".obj")
            if not os.path.exists(p):
                print("missing element file", e, "for", s["id"], s["name"])
                continue
            v, f = read_obj(p)
            vs.append(v)
            fs.append(f + off)
            off += len(v)
        if not vs:
            continue
        v, f = weld(np.vstack(vs), np.vstack(fs))
        loaded[s["id"]] = (v, f)
        total += len(f)
    print(f"{len(loaded)} structures loaded, {total:,} triangles before decimation")

    structs = drop_duplicates(structs, loaded)
    if extra:
        merge_extra(structs, loaded, extra)
    if female:
        merge_extra(structs, loaded, female)
        mark_male(structs)
    fix_sides(structs, loaded)
    total = sum(len(loaded[s["id"]][1]) for s in structs if s["id"] in loaded)

    # 2) one global reduction factor; small parts keep detail, big parts give up more
    keep = min(1.0, budget / total)
    print(f"{len(structs)} structures after de-duplication, {total:,} tris; target {budget:,} -> keep {keep:.2%}")
    floor = 60  # never decimate tiny parts below this
    final = {}
    for s in structs:
        if s["id"] not in loaded:
            continue
        v, f = loaded[s["id"]]
        target = max(floor, int(len(f) * keep))
        if len(f) > target and fast_simplification is not None:
            v32 = v.astype(np.float32)
            f32 = f.astype(np.int32)
            red = 1.0 - target / len(f)
            v2, f2 = fast_simplification.simplify(v32, f32, target_reduction=red)
            if len(f2) >= 4:
                v, f = compact(np.asarray(v2, dtype=np.float64), np.asarray(f2, dtype=np.int64))
        final[s["id"]] = (v, f)

    fit_skin(final, structs)
    female_skin(final, structs)

    bundles = {}
    manifest = []
    final_tris = 0
    for s in structs:
        if s["id"] not in final:
            continue
        v, f = final[s["id"]]
        pos = v.astype("<f4")
        idx = f.astype("<u4")
        blob = pos.tobytes() + idx.tobytes()
        b = bundles.setdefault(s["system"], bytearray())
        label, kind = sysdefs[s["system"]]
        manifest.append({
            "id": s["id"], "name": s["name"], "system": s["system"], "systemLabel": label,
            "kind": kind, **({"src": s["source"]} if "source" in s else {}), **({"sex": s["sex"]} if "sex" in s else {}), "o": len(b), "v": int(len(pos)), "t": int(len(idx)),
        })
        b += blob
        final_tris += len(idx)

    # 3) write bundles + manifest
    for f in os.listdir(out_mesh):
        if f.endswith(".bin"):
            os.remove(os.path.join(out_mesh, f))
    sizes = {}
    for key, b in bundles.items():
        with open(os.path.join(out_mesh, key + ".bin"), "wb") as fh:
            fh.write(b)
        sizes[key] = len(b)
    order = [k for k, _, _ in st.SYSTEMS if k in bundles]
    sys_meta = [{"key": k, "label": sysdefs[k][0], "kind": sysdefs[k][1], "bytes": sizes[k]} for k in order]
    manifest.sort(key=lambda m: (order.index(m["system"]), m["name"]))
    with open(os.path.join(out_root, "js", "data", "organs.js"), "w") as fh:
        fh.write("/* Auto-generated by tools/build_data.py from BodyParts3D 4.0 (isa + partof, 99% reduced).\n")
        fh.write("   (c) Database Center for Life Science, CC BY-SA 2.1 Japan. Do not edit by hand.\n")
        if extra:
            fh.write("   Structures with src set include Z-Anatomy geometry (CC BY-SA 4.0), warped onto BodyParts3D by tools/zanatomy.py.\n")
        if female:
            fh.write("   sex m/f = shown only for that body (absent = both). Female parts: HRA Visible Human Female (CC BY 4.0), tools/female.py.\n")
        fh.write("   id = FMA concept id; o/v/t = byte offset, vertex count, triangle count inside data/mesh/<system>.bin */\n")
        fh.write("const SystemDefs = " + json.dumps(sys_meta, indent=1) + ";\n")
        fh.write("const Organs = [\n")
        for m in manifest:
            fh.write("  " + json.dumps(m, separators=(", ", ": ")) + ",\n")
        fh.write("];\n")
    print(f"wrote {len(manifest)} structures, {final_tris:,} tris, {sum(sizes.values())/1e6:.1f} MB")
    for k in order:
        print(f"  {k:12s} {sum(1 for m in manifest if m['system']==k):4d} structures  {sizes[k]/1e6:6.2f} MB")


if __name__ == "__main__":
    main()
