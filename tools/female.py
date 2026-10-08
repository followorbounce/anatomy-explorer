#!/usr/bin/env python3
"""Female anatomy for the Male/Female switch, from the Human Reference Atlas (HRA) 3D reference
organs of the Visible Human Female (NIH HuBMAP, CC BY 4.0), placed onto the BodyParts3D body.

Usage:
  python3 tools/female.py <dir with BP3D .txt tables> <dir with isa_BP3D_4.0_obj_99> <hra dir> <out dir>
then pass  --female=<out dir>  to tools/build_data.py.

<hra dir> holds the GLBs listed in HRA_FILES (download URLs in CLAUDE.md). No complete open female
body model exists (BodyParts3D and Z-Anatomy are male-only; HRA has organs, a pelvis and skin but
no full skeleton or muscles), so "female" here means: the shared BP3D body with the female pelvis,
uterus, ovaries, uterine tubes and breasts swapped in for the male pelvis and genitals.
build_data.py also derives a female skin from the BP3D skin (see female_skin there).

Placement
- All HRA female organs share one frame (metres, Y-up, +x = subject's left, +z = anterior).
- Pelvis: similarity ICP of the HRA female hip bones + sacrum onto BP3D's. The fitted scale (~0.81;
  the Visible Human Female was a large woman) is what puts both femoral heads into the female
  acetabula (< 1 mm); proportions — the female shape — are kept. Uterus, ovaries, tubes use it too.
- Breasts: same rotation/scale, translation re-fitted on the sternum (HRA sternum + manubrium onto
  BP3D's), since trunk proportions differ between the two bodies.

Output: <out>/<slug>.obj per structure + <out>/manifest.json [{name, system, file, sex, src, tris}].
"""
import json
import os
import re
import sys

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(__file__))
import glb  # noqa: E402
import structures as st  # noqa: E402
from build_data import compact, read_obj, weld  # noqa: E402
from zanatomy import icp, slug  # noqa: E402

try:
    import fast_simplification
except ImportError:  # pragma: no cover
    fast_simplification = None

SRC = "HRA / Visible Human Female"
MAX_TRIS = 24000  # per structure, before build_data's global decimation (the breast fat is ~590k)

# output structure -> (system, GLB file stem, node-name regex). Nodes of one file that match go in.
STRUCTURES = [
    ("left hip bone",   "skeleton", "pelvis", r"_(ilium|ischium|pubis)_compact_bone_L$"),
    ("right hip bone",  "skeleton", "pelvis", r"_(ilium|ischium|pubis)_compact_bone_R$"),
    ("sacrum",          "skeleton", "pelvis", r"_sacrum$"),
    ("coccyx",          "skeleton", "pelvis", r"_coccyx$"),
    ("uterus",          "genital",  "uterus", r"_(body|fundus|cornua|lower_uterine_segment|posterior_wall|anterior_wall)|abdominal_ostium"),
    ("cervix of uterus", "genital", "uterus", r"cervi"),
    ("left ovary",      "genital",  "ovary-l", r"."),
    ("right ovary",     "genital",  "ovary-r", r"."),
    ("left uterine tube",  "genital", "fallopian-tube-l", r"."),
    ("right uterine tube", "genital", "fallopian-tube-r", r"."),
]
for side, s in (("left", "l"), ("right", "r")):
    STRUCTURES += [
        (f"{side} mammary gland",               "genital", f"mammary-gland-{s}", r"_(mammary_lobes|main_lactiferous_ducts|main_lactiferous_sinuses)_"),
        (f"{side} nipple and areola",           "genital", f"mammary-gland-{s}", r"_(nipple|areola|areolar_tubercles)_"),
        (f"{side} fatty tissue of breast",      "genital", f"mammary-gland-{s}", r"_fat_"),
        (f"{side} suspensory ligaments of breast", "genital", f"mammary-gland-{s}", r"_suspensory_ligaments_"),
    ]
HRA_FILES = sorted({f for _, _, f, _ in STRUCTURES} | {"sternum", "manubrium"})
BREAST = re.compile(r"mammary|nipple|breast")


def hra(hra_dir, stem):
    """{node name: (V mm in BP3D frame, F)}"""
    out = {}
    for nm, _, V, F in glb.read_glb(os.path.join(hra_dir, f"3d-vh-f-{stem}.glb")):
        out[nm] = (np.c_[V[:, 0], -V[:, 2], V[:, 1]] * 1000.0, F)  # Y-up m -> Z-up mm, -y anterior
    return out


def bp(structs, isa_dir, names):
    vs = []
    for s in structs:
        if s["name"] in names:
            vs += [read_obj(os.path.join(isa_dir, e + ".obj"))[0] for e in s["elements"]]
    return np.vstack(vs)


def decimate(v, f, max_tris):
    v, f = weld(v, f, decimals=3)
    if len(f) > max_tris and fast_simplification is not None:
        v2, f2 = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int32), target_reduction=1 - max_tris / len(f))
        v, f = compact(np.asarray(v2, float), np.asarray(f2, np.int64))
    return v, f


def main():
    tables, isa_dir, hra_dir, out = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    structs = st.load(tables)
    files = {stem: hra(hra_dir, stem) for stem in HRA_FILES}

    pel_f = np.vstack([v for n, (v, f) in files["pelvis"].items() if "spongy" not in n])
    pel_m = bp(structs, isa_dir, {"left hip bone", "right hip bone", "sacrum"})
    (s, R, t), err = icp(pel_f, pel_m, iters=80)
    ang = np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1)))
    place = lambda V: (s * (R @ V.T)).T + t
    print(f"pelvis: scale {s:.3f}, rotation {ang:.1f} deg, median residual {err:.2f} mm")
    fem = cKDTree(place(pel_f))
    for side in ("left", "right"):
        fv = bp(structs, isa_dir, {f"{side} femur"})
        head = fv[fv[:, 2] > fv[:, 2].max() - 45]
        print(f"  {side} femoral head to female pelvis: {fem.query(head)[0].min():.1f} mm")

    st_f = place(np.vstack([v for k in ("sternum", "manubrium") for v, f in files[k].values()]))
    st_m = bp(structs, isa_dir, {"Body of sternum", "manubrium"})
    tree, shift = cKDTree(st_m), st_m.mean(0) - st_f.mean(0)
    for _ in range(40):
        d, i = tree.query(st_f + shift)
        shift += (st_m[i] - (st_f + shift)).mean(0)
    print(f"breasts: sternum re-fit shifts them by {np.round(shift, 1)} mm (median residual {np.median(d):.1f} mm)")

    manifest = []
    for name, system, stem, pat in STRUCTURES:
        parts = [(v, f) for n, (v, f) in files[stem].items() if re.search(pat, n)]
        if not parts:
            sys.exit(f"no HRA nodes match {pat!r} in {stem}")
        vs, fs, o = [], [], 0
        for v, f in parts:
            vs.append(place(v) + (shift if BREAST.search(name) else 0))
            fs.append(f + o)
            o += len(v)
        v, f = decimate(np.vstack(vs), np.vstack(fs), MAX_TRIS)
        fn = "f-" + slug(name) + ".obj"
        with open(os.path.join(out, fn), "w") as fh:
            fh.write("".join(f"v {a:.3f} {b:.3f} {c:.3f}\n" for a, b, c in v))
            fh.write("".join(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in f))
        manifest.append({"name": name, "system": system, "file": fn, "sex": "f", "src": SRC, "tris": int(len(f))})
        print(f"  {name:38s} {system:9s} {len(f):6d} tris")
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"wrote {len(manifest)} female structures to {out}")


if __name__ == "__main__":
    main()
