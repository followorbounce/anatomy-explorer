# Progress

## 2026-09-20
- Project state found: index.html, style.css, js/app.js, js/data/organs.js and 160 STL meshes present; no docs, no git repo.
- Verified `Organs` ids ↔ `data/stl/*.stl` are 1:1 (160 each); WebGL initialises, heart system (23 meshes) loads with no console errors.
- **Fixed**: camera framing bug — `fitCameraToScene` used `Box3.expandByObject`, which counted hidden flow-pulse sprites sitting at mesh-local origin, so the camera targeted a point ~600 mm below the heart and the default view showed a tiny heart. Now unions geometry bounding boxes only. Confirmed via canvas pixel readback (≈470 distinct colours vs 29 before; camera target now at heart).
- Wrote CLAUDE.md and this file.

- User report: "in the browser nothing works". Reproduced: over http everything works (all 160 meshes, all toggles); opened as `file://` the systems list is empty and nothing responds (module/STL loading blocked). Added a file:// banner + 10 s startup-failure banner in `index.html`, and `serve.sh`.

## Known gaps / next
- Not yet a git repo / not pushed (footer already links github.com/followorbounce/anatomy-explorer).
- Selection panel shows only name / FMA id / system / kind — no descriptions or function text.
- Only the visible-system toggle exists; no per-structure show/hide, opacity/x-ray, or search.
- Flow pulse is one dot per vessel/nerve along the longest bbox axis (not anatomically traced); flow sprites start at mesh origin for a frame when first toggled on.
- No mobile/touch layout check yet; not verified in a real (non-headless) browser beyond pixel readback.
