"""Bone exposure audit: how much skeleton shows through the muscle layer.
Orthographic z-buffer of skeleton + muscles (dense surface samples, 1.5 mm pixels) from 8 directions
around the vertical axis. Prints the visible bone area per bone (summed over the views) and saves the
views as PNG (bone cream, muscle red). Needs numpy + Pillow.
usage: python3 tools/bone_audit.py <repo> <outdir> [male|female]"""
import json, re, sys, os
import numpy as np

repo, out = sys.argv[1], sys.argv[2]
sex = sys.argv[3][0] if len(sys.argv) > 3 else "m"
os.makedirs(out, exist_ok=True)
src = open(os.path.join(repo, "js/data/organs.js")).read()
organs = json.loads(re.sub(r",\s*\]$", "]", re.search(r"Organs\s*=\s*(\[.*?\]);", src, re.S).group(1)))
RES = 1.5  # mm per pixel

items = []
for sysk in ("skeleton", "muscles"):
    buf = open(os.path.join(repo, "data/mesh", sysk + ".bin"), "rb").read()
    for o in organs:
        if o["system"] != sysk or (o.get("sex") and o["sex"] != sex):
            continue
        v = np.frombuffer(buf, "<f4", o["v"] * 3, o["o"]).reshape(-1, 3)
        t = np.frombuffer(buf, "<u4", o["t"] * 3, o["o"] + o["v"] * 12).reshape(-1, 3)
        items.append((o["name"], sysk, v, t))
print(len(items), "structures")

# dense surface samples, labelled by structure index
rng = np.random.default_rng(0)
P, L = [], []
for i, (n, s, v, t) in enumerate(items):
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    k = np.maximum(1, np.ceil(area / (RES * RES * 0.25))).astype(int)
    rep = np.repeat(np.arange(len(t)), k)
    r1, r2 = rng.random(len(rep)), rng.random(len(rep))
    sw = r1 + r2 > 1
    r1[sw], r2[sw] = 1 - r1[sw], 1 - r2[sw]
    p = a[rep] + (b[rep] - a[rep]) * r1[:, None] + (c[rep] - a[rep]) * r2[:, None]
    P.append(p.astype(np.float32)); L.append(np.full(len(p), i, np.int32))
P = np.vstack(P); L = np.concatenate(L)
isbone = np.array([s == "skeleton" for _, s, _, _ in items])
print(f"{len(P):,} samples")

# BP3D is Z-up, millimetres; views go around the vertical axis.
exposed = np.zeros(len(items))
from PIL import Image
for ang in range(0, 360, 45):
    th = np.radians(ang)
    d = np.array([np.sin(th), -np.cos(th), 0.0], np.float32)  # view direction (towards viewer)
    u = np.array([np.cos(th), np.sin(th), 0.0], np.float32)
    depth = P @ d
    x = np.floor((P @ u) / RES).astype(np.int64); z = np.floor(P[:, 2] / RES).astype(np.int64)
    x -= x.min(); z -= z.min()
    W, H = x.max() + 1, z.max() + 1
    pix = z * W + x
    order = np.lexsort((-depth, pix))  # per pixel, nearest to viewer first
    first = np.r_[True, pix[order][1:] != pix[order][:-1]]
    win = order[first]
    lab = L[win]
    np.add.at(exposed, lab[isbone[lab]], RES * RES)
    img = np.zeros((H, W, 3), np.uint8)
    col = np.where(isbone[lab][:, None], [235, 225, 200], [170, 60, 55]).astype(np.uint8)
    img.reshape(-1, 3)[pix[win]] = col
    Image.fromarray(img[::-1]).save(os.path.join(out, f"view{ang:03d}.png"))
tot = exposed.sum()
print(f"visible bone area summed over 8 views: {tot/1e4:.1f} dm^2")
rows = sorted(((exposed[i], items[i][0]) for i in range(len(items)) if isbone[i]), reverse=True)
json.dump({n: float(a) for a, n in rows}, open(os.path.join(out, "exposed.json"), "w"), indent=0)
for a, n in rows[:45]:
    print(f"{a/100:8.1f} cm2  {n}")
