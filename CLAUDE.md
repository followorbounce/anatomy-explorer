# Anatomy Explorer

Static, no-build interactive 3D human anatomy viewer. Real organ meshes from BodyParts3D (gaps filled from Z-Anatomy), grouped by body system, with optional animated blood-flow / nerve-signal pulses.

## Structure
- `index.html` — single page: sidebar (structure search, systems checklist, live-signal toggles, opacity slider, hidden/isolated status) + Three.js canvas with a floating selection card (Focus / Hide / Isolate, left-right twin link). Three.js r0.186 loaded via import map from jsDelivr (no bundler).
- `js/app.js` — the whole app (ES module): scene, per-system bundle loading (streamed, with % progress), selection/hover raycasting, per-structure hide/isolate, name search, flow pulses, camera fit/focus, theme toggle.
- `js/data/organs.js` — **generated** (`tools/build_data.py`, never hand-edit). Globals `SystemDefs` (`{key,label,kind,bytes}` in sidebar order) and `Organs` (`{id,name,system,systemLabel,kind,src?,o,v,t}`; `id` = FMA concept id, or `ZA-…` for Z-Anatomy-only structures).
- `data/mesh/<system>.bin` — 17 generated binary bundles (~63 MB total). Per structure at byte offset `o`: float32 positions[v*3] then uint32 indices[t*3]. Loaded whole when a system is toggled on.
- `tools/structures.py` — groups element meshes into named structures and classifies them into systems (IS-A ancestry first, then name regexes; see "Classification").
- `tools/build_data.py` — decimates (fast_simplification) + packs bundles + writes organs.js; `--extra=<dir>` merges `tools/zanatomy.py` output. Source archives are NOT in the repo.
- `tools/zanatomy.py` — reads Z-Anatomy's `Startup.blend` (blender-asset-tracer, no Blender needed), warps it onto the BP3D skeleton (per-bone/organ ICP, blended), turns nerve/vessel curves into tubes and keeps only the parts BP3D doesn't already cover. Writes OBJs + manifest.json.
- `style.css` — dark/light themes via CSS variables. `serve.sh` — local static server.

## Data
- Geometry: BodyParts3D **release 4.0** (isa + partof, 99%-reduced OBJ), © DBCLS, CC BY-SA 2.1 Japan — attribution lives in the footer; keep it. Adult male only.
- Gap fill: **Z-Anatomy** (github.com/Z-Anatomy/Models-of-human-anatomy, CC BY-SA 4.0, derived from BP3D) — peripheral nerves, spinal roots/ganglia, missing artery/vein stretches, lymph nodes. 788 pieces: 69 extend a BP3D structure of the same name+system (organs.js `src: "BodyParts3D + Z-Anatomy"`), 719 are new (`id` = `ZA-<slug>`, `src: "Z-Anatomy"`). Warp residual ~0.5 mm on bones, but Z's hand-drawn vessels sit 5–12 mm off BP3D's, so placement is approximate — the footer says so. The card shows the source.
- 2,348 named structures (BP3D 1,629 after dropping 6 duplicates + 719 Z-Anatomy; 7.15 M tris source → 3.5 M, `--budget-tris=3500000`): skeleton 277, muscles 401, ligaments/fascia 31, heart 45, arteries 589, veins 337, brain 93, nerves 283, respiratory 26, digestive 48, urinary 6, genital 12, glands 4, lymph nodes 148, eye/ear/face 39, skin 3, other 6.
- Build-time cleanups in `tools/build_data.py`: `drop_duplicates` (z-fighting copies), `fix_sides` (swaps left/right in names when the mesh is clearly on the other side — BP3D +x = subject's left), `fit_skin` (pushes skin out locally where thin structures poke through; a few specks still show at knee/neck).
- **Not modelled** (say so, don't claim): lymphatic vessels, female anatomy. (Peripheral nerves and lymph nodes exist only via Z-Anatomy.)
- Replaced the earlier v3.0-derived 160-structure STL set on 2026-09-20 (only 106 of its ids matched v4 concepts, so mixing would have duplicated/seamed).

### Rebuilding the data
Use a disk directory, not /tmp (tmpfs here, ~2 GB, wiped; the warp step needs ~1.2 GB RAM, the build ~1.8 GB).
```
B=https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST
S=~/.cache/anatomy-src; mkdir -p $S && cd $S
curl -O $B/isa_BP3D_4.0_obj_99.zip -O $B/partof_BP3D_4.0_obj_99.zip   # ~200 MB, slow
curl -O $B/partof_element_parts.txt -O $B/isa_element_parts.txt -O $B/partof_inclusion_relation_list.txt -O $B/isa_inclusion_relation_list.txt
unzip -q isa_BP3D_4.0_obj_99.zip -d isa; unzip -q partof_BP3D_4.0_obj_99.zip -d partof
curl -L -o Z-Anatomy.zip https://raw.githubusercontent.com/Z-Anatomy/Models-of-human-anatomy/master/Z-Anatomy.zip   # 87 MB
unzip -q Z-Anatomy.zip -d za
python3 <repo>/tools/zanatomy.py $S/za/Z-Anatomy/Startup.blend $S $S/isa/isa_BP3D_4.0_obj_99 $S/za-out   # ~70 s
python3 <repo>/tools/build_data.py $S $S/isa/isa_BP3D_4.0_obj_99 $S/partof/partof_BP3D_4.0_obj_99 --budget-tris=3500000 --extra=$S/za-out   # ~5 min
```
Needs numpy, scipy, fast_simplification, blender-asset-tracer (`pip install --user`). The isa archive is a superset of partof's elements.

### Classification
Each element mesh (FJxxxx) is named after the smallest concept containing it; elements sharing that concept merge into one structure. System = IS-A ancestor (muscle organ / bone organ / artery / vein / nerve / ligament…) → else name regex (`tools/structures.py` RULES/EXTRA) → else PART-OF ancestor → `other`. Heart parts are forced into "heart" before the IS-A check. To fix a misfiled structure, add a pattern to `EXTRA`.

## Conventions / gotchas
- BodyParts3D is **Z-up, millimetres**; `root` group is rotated −π/2 about X to get Y-up. Heart sits around z≈1190–1290. Default view: skeleton only.
- `system` drives colour (+ small per-id lightness jitter); `kind` (`artery`/`vein`/`nerve`) gets a flow-pulse sprite (child of the mesh, shared geometry/material; ~1,200 of them). Materials are DoubleSide (source meshes aren't guaranteed consistently wound).
- **`Raycaster` ignores `mesh.visible`** — `pickAt` filters to visible meshes itself; keep that when touching picking. Hide/isolate state lives in `hiddenIds` / `isolateIds` (applied by `applyVisibility()`, re-applied to meshes as their system loads).
- Search (`#searchInput`) matches every typed word against structure names; picking a result calls `ensureSystem()` (turns the system on and awaits its bundle), un-hides, selects and focuses it. Left/right twins are found by swapping the word in the name within the same system (`mirrorOf`).
- Skeleton materials use `polygonOffset` so overlapping muscles win the z-fight and cover bone.
- **Mouse controls**: left-click drag = rotate, right-click drag = pan, scroll = zoom (OrbitControls defaults). Touch keeps OrbitControls' two-finger pan.
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
