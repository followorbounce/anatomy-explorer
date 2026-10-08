"""Minimal glTF-binary reader: world-space triangle meshes per named node (numpy only)."""
import json
import struct

import numpy as np

_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_N = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _mat(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    T = np.eye(4)
    if "scale" in node:
        T = np.diag(list(node["scale"]) + [1.0]) @ T
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        M = np.eye(4)
        M[:3, :3] = R
        T = M @ T
    if "translation" in node:
        M = np.eye(4)
        M[:3, 3] = node["translation"]
        T = M @ T
    return T


def read_glb(path):
    """-> list of (node name, path of node names, vertices[n,3] world, faces[m,3])."""
    raw = open(path, "rb").read()
    magic, _, _ = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67, path
    off, js, binc = 12, None, None
    while off < len(raw):
        ln, typ = struct.unpack_from("<II", raw, off)
        chunk = raw[off + 8: off + 8 + ln]
        if typ == 0x4E4F534A:
            js = json.loads(chunk)
        elif typ == 0x004E4942:
            binc = chunk
        off += 8 + ln

    def acc(i):
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        n, k, dt = a["count"], _N[a["type"]], _CT[a["componentType"]]
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0)
        isz = np.dtype(dt).itemsize * k
        if stride and stride != isz:
            buf = np.frombuffer(binc, np.uint8, stride * (n - 1) + isz, start)
            idx = np.arange(n)[:, None] * stride + np.arange(isz)[None]
            return buf[idx].copy().view(dt).reshape(n, k)
        return np.frombuffer(binc, dt, n * k, start).reshape(n, k) if k > 1 else np.frombuffer(binc, dt, n, start)

    out = []

    def walk(ni, M, names):
        node = js["nodes"][ni]
        M = M @ _mat(node)
        nm = node.get("name", f"node{ni}")
        names = names + [nm]
        if "mesh" in node:
            vs, fs, o = [], [], 0
            for p in js["meshes"][node["mesh"]]["primitives"]:
                if p.get("mode", 4) != 4:
                    continue
                v = acc(p["attributes"]["POSITION"]).astype(float)
                f = acc(p["indices"]).astype(np.int64).reshape(-1, 3) if "indices" in p else np.arange(len(v)).reshape(-1, 3)
                vs.append(v)
                fs.append(f + o)
                o += len(v)
            if vs:
                V = np.vstack(vs)
                V = V @ M[:3, :3].T + M[:3, 3]
                out.append((nm, names, V, np.vstack(fs)))
        for c in node.get("children", []):
            walk(c, M, names)

    for r in js["scenes"][js.get("scene", 0)]["nodes"]:
        walk(r, np.eye(4), [])
    return out
