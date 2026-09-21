# Anatomy Explorer

Static, no-build interactive 3D human anatomy viewer. Real organ meshes from BodyParts3D, grouped by body system, with optional animated blood-flow / nerve-signal pulses.

## Structure
- `index.html` — single page: sidebar (structure search, systems checklist, live-signal toggles, opacity slider, hidden/isolated status) + Three.js canvas with a floating selection card (Focus / Hide / Isolate, left-right twin link). Three.js r0.186 loaded via import map from jsDelivr (no bundler).
- `js/app.js` — the whole app (ES module): scene, per-system bundle loading (streamed, with % progress), selection/hover raycasting, per-structure hide/isolate, name search, flow pulses, camera fit/focus, theme toggle.
- `js/data/organs.js` — **generated** (`tools/build_data.py`, never hand-edit). Globals `SystemDefs` (`{key,label,kind,bytes}` in sidebar order) and `Organs` (`{id,name,system,systemLabel,kind,o,v,t}`; `id` = FMA concept id).
- `data/mesh/<system>.bin` — 16 generated binary bundles (~54 MB total). Per structure at byte offset `o`: float32 positions[v*3] then uint32 indices[t*3]. Loaded whole when a system is toggled on.
- `tools/structures.py` — groups element meshes into named structures and classifies them into systems (IS-A ancestry first, then name regexes; see "Classification").
- `tools/build_data.py` — decimates (fast_simplification) + packs bundles + writes organs.js. Source archives are NOT in the repo.
- `style.css` — dark/light themes via CSS variables. `serve.sh` — local static server.

## Data
- Geometry: BodyParts3D **release 4.0** (isa + partof, 99%-reduced OBJ), © DBCLS, CC BY-SA 2.1 Japan — attribution lives in the footer; keep it. Adult male only.
- 1,629 named structures (1,635 in the source; 6 exact-duplicate meshes dropped by `drop_duplicates`; 6.68 M triangles source → 3.0 M after our decimation): skeleton 279, muscles 395, ligaments/fascia 29, heart 43, arteries 387, veins 216, brain 94, nerves 37, respiratory 26, digestive 53, urinary 6, genital 12, glands 4, eye/ear/face 39, skin 3, other 6.
- Build-time cleanups in `tools/build_data.py`: `drop_duplicates` (z-fighting copies), `fix_sides` (swaps left/right in names when the mesh is clearly on the other side — BP3D +x = subject's left), `fit_skin` (pushes skin out locally where thin structures poke through; a few specks still show at knee/neck).
- **Not modelled** (say so, don't claim): peripheral nerve trunks (only cranial-nerve branches near the eye + spinal cord), lymphatic vessels, female anatomy.
- Replaced the earlier v3.0-derived 160-structure STL set on 2026-09-20 (only 106 of its ids matched v4 concepts, so mixing would have duplicated/seamed).

### Rebuilding the data
```
B=https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST
mkdir -p /tmp/bp && cd /tmp/bp
curl -O $B/isa_BP3D_4.0_obj_99.zip -O $B/partof_BP3D_4.0_obj_99.zip   # ~200 MB, slow
curl -O $B/partof_element_parts.txt -O $B/isa_element_parts.txt -O $B/partof_inclusion_relation_list.txt -O $B/isa_inclusion_relation_list.txt
unzip -q isa_BP3D_4.0_obj_99.zip -d isa; unzip -q partof_BP3D_4.0_obj_99.zip -d partof
python3 <repo>/tools/build_data.py /tmp/bp /tmp/bp/isa/isa_BP3D_4.0_obj_99 /tmp/bp/partof/partof_BP3D_4.0_obj_99 [--budget-tris=3000000]
```
Needs numpy + fast_simplification (~40 s). The isa archive is a superset of partof's elements.

### Classification
Each element mesh (FJxxxx) is named after the smallest concept containing it; elements sharing that concept merge into one structure. System = IS-A ancestor (muscle organ / bone organ / artery / vein / nerve / ligament…) → else name regex (`tools/structures.py` RULES/EXTRA) → else PART-OF ancestor → `other`. Heart parts are forced into "heart" before the IS-A check. To fix a misfiled structure, add a pattern to `EXTRA`.

## Conventions / gotchas
- BodyParts3D is **Z-up, millimetres**; `root` group is rotated −π/2 about X to get Y-up. Heart sits around z≈1190–1290. Default view: skeleton only.
- `system` drives colour (+ small per-id lightness jitter); `kind` (`artery`/`vein`/`nerve`) gets a flow-pulse sprite (child of the mesh, shared geometry/material; ~640 of them). Materials are DoubleSide (source meshes aren't guaranteed consistently wound).
- **`Raycaster` ignores `mesh.visible`** — `pickAt` filters to visible meshes itself; keep that when touching picking. Hide/isolate state lives in `hiddenIds` / `isolateIds` (applied by `applyVisibility()`, re-applied to meshes as their system loads).
- Search (`#searchInput`) matches every typed word against structure names; picking a result calls `ensureSystem()` (turns the system on and awaits its bundle), un-hides, selects and focuses it. Left/right twins are found by swapping the word in the name within the same system (`mirrorOf`).
- Opacity slider makes all meshes transparent; picking then skips the skin shell so inner structures stay clickable. Hover picking is throttled to 1 raycast/frame.
- **Never fit the camera with `Box3.expandByObject`** — it includes the hidden flow sprites at each mesh's local origin, which stretches the box to world origin and aims the camera at empty space (heart rendered tiny). `fitCameraToScene` unions `geometry.boundingBox` transformed by `matrixWorld` instead.
- Flow pulses are illustrative (a dot lerping along the mesh's longest bbox axis), not a fluid sim or a traced vessel path — the UI says so; keep that honest.
- Never use Russian in code/UI/docs unless the task explicitly calls for it.

## Running
- **Must be served over http(s)** — opening `index.html` as `file://` cannot work (module scripts + STL loading are blocked); the page shows an explanatory banner. Run `./serve.sh [port]` (default 8000) and open http://localhost:8000/.
- `js/app.js` sets `window.__anatomyReady`; an inline classic script in `index.html` shows a "viewer didn't start" banner if that isn't set after 10 s (e.g. CDN blocked).

## Testing
- Serve statically (`./serve.sh`) and open in a browser. Headless Firefox `--screenshot` does **not** capture the WebGL canvas; to verify rendering, read pixels back (render, `drawImage` the canvas into a 2D canvas, sample) or use a real browser.

## Deploy
GitHub Pages (branch main, /) at https://followorbounce.github.io/anatomy-explorer/ — remote `github.com/followorbounce/anatomy-explorer` (public). Cloudflare Web Analytics beacon already in `index.html`; note it has not been registered for this path/site specifically (shares the followorbounce.github.io token).
