# Anatomy Explorer

Static, no-build interactive 3D human anatomy viewer. Real organ meshes from BodyParts3D, grouped by body system, with optional animated blood-flow / nerve-signal pulses.

## Structure
- `index.html` — single page: sidebar (systems checklist, live-signal toggles, selection panel) + Three.js canvas. Three.js r0.186 loaded via import map from jsDelivr (no bundler).
- `js/app.js` — the whole app (ES module): scene, STL loading per system, selection/hover raycasting, flow pulses, camera fit, theme toggle.
- `js/data/organs.js` — global `Organs` array (plain script, loaded before app.js). Auto-generated; entries `{ id, name, system, systemLabel, kind }`. `id` is the FMA identifier and doubles as the mesh filename `data/stl/<id>.stl`.
- `data/stl/` — 160 decimated STL meshes (~31 MB total), ~6000 triangles each.
- `style.css` — dark/light themes via CSS variables.

## Data
- Geometry: BodyParts3D v3.0, © DBCLS, CC BY-SA 2.1 Japan — attribution lives in the footer; keep it.
- 160 of 934 available structures, curated: digestive 8, respiratory 6, urinary 5, heart 23, brain 73, vessels 42 (32 arteries + the rest veins), nervous_extra 3 (optic nerves / spinal canal). Peripheral nerves are **not** modeled in this release — don't claim them.
- `Organs` ids and `data/stl/*.stl` are 1:1 (verified 2026-09-20). Keep them in sync when adding/removing structures.

## Conventions / gotchas
- BodyParts3D is **Z-up, millimetres**; `root` group is rotated −π/2 about X to get Y-up. Heart sits around z≈1190–1290.
- `kind` drives colour and flow: `artery`/`vein`/`nerve` get a flow-pulse sprite (child of the mesh, at local origin until animated); other kinds don't.
- **Never fit the camera with `Box3.expandByObject`** — it includes the hidden flow sprites at each mesh's local origin, which stretches the box to world origin and aims the camera at empty space (heart rendered tiny). `fitCameraToScene` unions `geometry.boundingBox` transformed by `matrixWorld` instead.
- Flow pulses are illustrative (a dot lerping along the mesh's longest bbox axis), not a fluid sim or a traced vessel path — the UI says so; keep that honest.
- Never use Russian in code/UI/docs unless the task explicitly calls for it.

## Testing
- Serve statically (`python3 -m http.server`) and open in a browser. Headless Firefox `--screenshot` does **not** capture the WebGL canvas; to verify rendering, read pixels back (render, `drawImage` the canvas into a 2D canvas, sample) or use a real browser.

## Deploy
Intended: GitHub Pages from `github.com/followorbounce/anatomy-explorer` (linked in the footer). Cloudflare Web Analytics beacon already in `index.html`.
