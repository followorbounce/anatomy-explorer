# Anatomy Explorer

Static, no-build interactive 3D human anatomy viewer. Real organ meshes from BodyParts3D (gaps filled from Z-Anatomy), male or female body (female parts from the Human Reference Atlas), grouped by body system, with optional animated blood-flow / nerve-signal pulses.

## Structure
- `index.html` — single page: sidebar (Male/Female body switch, structure search, systems checklist, live-signal toggles, opacity slider, hidden/isolated status) + Three.js canvas with a floating selection card (Focus / Hide / Isolate, left-right twin link). Three.js r0.186 loaded via import map from jsDelivr (no bundler).
- `js/app.js` — the whole app (ES module): scene, per-system bundle loading (streamed, with % progress), selection/hover raycasting, per-structure hide/isolate, name search, flow pulses, camera fit/focus, theme toggle.
- `js/data/organs.js` — **generated** (`tools/build_data.py`, never hand-edit). Globals `SystemDefs` (`{key,label,kind,bytes}` in sidebar order) and `Organs` (`{id,name,system,systemLabel,kind,src?,sex?,o,v,t}`; `id` = FMA concept id, `ZA-…` for Z-Anatomy-only, `F-…` for female-set structures; `sex` m/f = that body only).
- `data/mesh/<system>.bin` — 17 generated binary bundles (~63 MB total). Per structure at byte offset `o`: float32 positions[v*3] then uint32 indices[t*3]. Loaded whole when a system is toggled on.
- `tools/structures.py` — groups element meshes into named structures and classifies them into systems (IS-A ancestry first, then name regexes; see "Classification").
- `tools/build_data.py` — decimates (fast_simplification) + packs bundles + writes organs.js; `--extra=<dir>` merges `tools/zanatomy.py` output, `--female=<dir>` merges `tools/female.py` output, tags the male parts it replaces (`mark_male`) and derives the female skin (`female_skin`). Source archives are NOT in the repo.
- `tools/zanatomy.py` — reads Z-Anatomy's `Startup.blend` (blender-asset-tracer, no Blender needed), warps it onto the BP3D skeleton (per-bone/organ ICP, blended), turns nerve/vessel curves into tubes and keeps only the parts BP3D doesn't already cover. Writes OBJs + manifest.json.
- `tools/female.py` — places the HRA Visible Human Female pelvis, uterus, cervix, ovaries, uterine tubes and breasts onto the BP3D body (see Data). `tools/glb.py` — minimal numpy glTF-binary reader it uses.
- `style.css` — dark/light themes via CSS variables. `serve.sh` — local static server.

## Data
- Geometry: BodyParts3D **release 4.0** (isa + partof, 99%-reduced OBJ), © DBCLS, CC BY-SA 2.1 Japan — attribution lives in the footer; keep it. Adult male only.
- Gap fill: **Z-Anatomy** (github.com/Z-Anatomy/Models-of-human-anatomy, CC BY-SA 4.0, derived from BP3D) — peripheral nerves, spinal roots/ganglia, missing artery/vein stretches, lymph nodes. 788 pieces: 69 extend a BP3D structure of the same name+system (organs.js `src: "BodyParts3D + Z-Anatomy"`), 719 are new (`id` = `ZA-<slug>`, `src: "Z-Anatomy"`). Warp residual ~0.5 mm on bones, but Z's hand-drawn vessels sit 5–12 mm off BP3D's, so placement is approximate — the footer says so. The card shows the source.
- **Female body** (`sex` field; no complete open female model exists — BP3D and Z-Anatomy are male-only, Z-Anatomy's female collections are empty labels and a female model is on their TODO): 18 structures from the **Human Reference Atlas** 3D reference organs (NIH HuBMAP, Visible Human Female, CC BY 4.0): female hip bones, sacrum, coccyx, uterus, cervix, ovaries, uterine tubes, breasts (gland, fat, nipple/areola, suspensory ligaments). Placement: similarity ICP of the HRA pelvis onto BP3D's (scale 0.814 — that's what seats both femoral heads in the female acetabula to < 1 mm; the VHF was a large woman), breasts re-translated by fitting the HRA sternum. Male-only (`sex: "m"`, 27): genital system, penile/testicular vessels, urethra, BP3D hip bones + sacrum, male skin. Female skin (`F-skin`) = BP3D skin with the penis/scrotum skin relaxed into a membrane (sparse Laplace solve over skin within 22 mm of those organs) + the HRA breast-fat and nipple/areola surfaces appended (the flat male chest skin stays hidden inside them). Everything else (muscles, vessels, organs, skeleton above/below the pelvis) is shared and male-derived — the UI says so. Not modelled for female: external genitalia, female urethra, ovarian/uterine vessels and nerves.
- 2,366 named structures (BP3D 1,629 + 719 Z-Anatomy + 18 female; 7.5 M tris source → 3.85 M, `--budget-tris=3700000`): skeleton 285 (281 male / 282 female view), muscles 401, ligaments/fascia 31, heart 45, arteries 588, veins 337, brain 93, nerves 283, respiratory 26, digestive 48, urinary 6, genital 26 (12 m / 14 f), glands 4, lymph nodes 148, eye/ear/face 39, skin 4, other 2.
- Hip bones and patellae were filed as "Left/Right hip/knee region" in `other` until 2026-10-08 (the region concepts contain exactly that one mesh and won the smallest-concept tie); `RENAME` in structures.py now maps them to the bones (with the bones' FMA ids).
- Build-time cleanups in `tools/build_data.py`: `drop_duplicates` (z-fighting copies), `fix_sides` (swaps left/right in names when the mesh is clearly on the other side — BP3D +x = subject's left), `fit_skin` (pushes skin out locally where thin structures poke through; a few specks still show at knee/neck).
- **Not modelled** (say so, don't claim): lymphatic vessels; in the female body external genitalia and female-specific vessels/nerves. (Peripheral nerves and lymph nodes exist only via Z-Anatomy.) The shared `mons pubis` structure is a crumpled sheet poking through the skin in both bodies (source defect, not fixed).
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
curl -s https://apps.humanatlas.io/api/v1/reference-organs -o hra-organs.json   # lists every reference organ GLB
mkdir -p hra && cd hra && for o in uterus-female/v1.2/assets/3d-vh-f-uterus ovary-female-left/v1.3/assets/3d-vh-f-ovary-l ovary-female-right/v1.3/assets/3d-vh-f-ovary-r fallopian-tube-female-left/v1.2/assets/3d-vh-f-fallopian-tube-l fallopian-tube-female-right/v1.2/assets/3d-vh-f-fallopian-tube-r mammary-gland-female-left/v1.1/assets/3d-vh-f-mammary-gland-l mammary-gland-female-right/v1.1/assets/3d-vh-f-mammary-gland-r pelvis-female/v1.3/assets/3d-vh-f-pelvis sternum-female/v1.0/assets/3d-vh-f-sternum manubrium-female/v1.0/assets/3d-vh-f-manubrium; do curl -sSfLO https://cdn.humanatlas.io/digital-objects/ref-organ/$o.glb; done; cd ..
python3 <repo>/tools/female.py $S $S/isa/isa_BP3D_4.0_obj_99 $S/hra $S/female-out   # ~15 s
python3 <repo>/tools/build_data.py $S $S/isa/isa_BP3D_4.0_obj_99 $S/partof/partof_BP3D_4.0_obj_99 --budget-tris=3700000 --extra=$S/za-out --female=$S/female-out   # ~5 min
```
Needs numpy, scipy, fast_simplification, blender-asset-tracer (`pip install --user`). When testing in headless Firefox, serve with `Cache-Control: no-store` (or a fresh profile) after a rebuild — a cached `skin.bin` looks like the change didn't work. The isa archive is a superset of partof's elements.

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
- **Body switch**: `sex` ("m"/"f") from `?body=male|female`, else localStorage `anatomy-body`, else male. `inBody(o)` gates loading, counts, search and twins (`ORGAN_BY_NAME` keys include sex). `setBody` unloads the other body's meshes and re-runs `setSystemVisible` for every system that's on (bundles come from the HTTP cache) without re-framing the camera. Female parts live in the same per-system bundles, so no extra requests.
- Never use Russian in code/UI/docs unless the task explicitly calls for it.

## Running
- **Must be served over http(s)** — opening `index.html` as `file://` cannot work (module scripts + STL loading are blocked); the page shows an explanatory banner. Run `./serve.sh [port]` (default 8000) and open http://localhost:8000/.
- `js/app.js` sets `window.__anatomyReady`; an inline classic script in `index.html` shows a "viewer didn't start" banner if that isn't set after 10 s (e.g. CDN blocked).

## Testing
- Serve statically (`./serve.sh`) and open in a browser. Headless Firefox `--screenshot` does **not** capture the WebGL canvas; to verify rendering, read pixels back (render, `drawImage` the canvas into a 2D canvas, sample) or use a real browser.

## Deploy
GitHub Pages (branch main, /) at https://followorbounce.github.io/anatomy-explorer/ — remote `github.com/followorbounce/anatomy-explorer` (public). Cloudflare Web Analytics beacon already in `index.html`; note it has not been registered for this path/site specifically (shares the followorbounce.github.io token).
