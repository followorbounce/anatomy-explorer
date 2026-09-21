#!/usr/bin/env python3
"""Build the web data (data/mesh/<system>.bin + js/data/organs.js) from BodyParts3D 4.0.

Usage:
  python3 tools/build_data.py <dir with the dataset .txt tables> <dir with isa_BP3D_4.0_obj_99 (unzipped)> \
      [<dir with partof_BP3D_4.0_obj_99 (unzipped)>] [--budget-tris N]

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


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    budget = 3_000_000
    for a in sys.argv[1:]:
        if a.startswith("--budget-tris="):
            budget = int(a.split("=")[1])
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
    print(f"{len(loaded)} structures, {total:,} triangles before decimation")

    # 2) one global reduction factor; small parts keep detail, big parts give up more
    keep = min(1.0, budget / total)
    print(f"target {budget:,} tris -> keep {keep:.2%}")
    floor = 60  # never decimate tiny parts below this
    bundles = {}
    manifest = []
    final_tris = 0
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
        pos = v.astype("<f4")
        idx = f.astype("<u4")
        blob = pos.tobytes() + idx.tobytes()
        b = bundles.setdefault(s["system"], bytearray())
        label, kind = sysdefs[s["system"]]
        manifest.append({
            "id": s["id"], "name": s["name"], "system": s["system"], "systemLabel": label,
            "kind": kind, "o": len(b), "v": int(len(pos)), "t": int(len(idx)),
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
