# Progress

## 2026-09-20
- Project state found: index.html, style.css, js/app.js, js/data/organs.js and 160 STL meshes present; no docs, no git repo.
- Verified `Organs` ids ↔ `data/stl/*.stl` are 1:1 (160 each); WebGL initialises, heart system (23 meshes) loads with no console errors.
- **Fixed**: camera framing bug — `fitCameraToScene` used `Box3.expandByObject`, which counted hidden flow-pulse sprites sitting at mesh-local origin, so the camera targeted a point ~600 mm below the heart and the default view showed a tiny heart. Now unions geometry bounding boxes only. Confirmed via canvas pixel readback (≈470 distinct colours vs 29 before; camera target now at heart).
- Wrote CLAUDE.md and this file.

- User report: "in the browser nothing works". Reproduced: over http everything works (all 160 meshes, all toggles); opened as `file://` the systems list is empty and nothing responds (module/STL loading blocked). Added a file:// banner + 10 s startup-failure banner in `index.html`, and `serve.sh`.

- **Whole body added** (user: "what about legs, arms and everything else?"): rebuilt all data from BodyParts3D 4.0 (isa + partof). 160 → 1,635 structures, 16 systems incl. skeleton, muscles, ligaments, skin, eye/ear, genital, glands; full arms/legs/hands/feet. New pipeline `tools/` (structures.py + build_data.py) → per-system binary bundles `data/mesh/*.bin` (54 MB, ~4× smaller than STL, ~16 requests instead of 1,600). Old `data/stl/` removed.
- app.js: bundle loader, per-system colours, opacity slider, throttled hover, drag≠click, shared flow-sprite geometry, picking skips skin under transparency.
- Verified in headless Firefox via canvas readback: all 1,635 meshes load with no errors; skeleton-only, full-body opaque and full-body 35% opacity all render correctly; click selects (e.g. external oblique, pectoralis major).

## Known gaps / next
- Published 2026-09-20: repo github.com/followorbounce/anatomy-explorer, live at https://followorbounce.github.io/anatomy-explorer/ (index, app.js, STL all 200).
- Selection panel shows only name / FMA id / system / kind / triangle count — no descriptions or function text. (Search box, hide/isolate and L/R twin links have since been added.)
- Only whole-system toggles (plus global opacity); no per-structure hide/isolate. Left/right paired structures are separate meshes with no mirror-toggle.
- Muscles bundle is ~20 MB (largest); no progress bar, just a "Loading…" pill.
- Flow pulse is one dot per vessel/nerve along the longest bbox axis (not anatomically traced); flow sprites start at mesh origin for a frame when first toggled on.
- No mobile/touch layout check yet; not verified in a real (non-headless) browser beyond pixel readback.

## 2026-09-21
- Pushed the app-side work (structure search, per-structure hide/isolate, left/right twin link, load progress, floating selection card).
- Ran the pending data rebuild (tools changes were newer than `data/mesh/*.bin`): 1,635 → 1,629 structures (6 duplicate meshes dropped), left/right name fix for flexor pollicis brevis, skin fitted outward where fascia/muscle poked through, and one misfiled biliary-tree structure moved from brain to digestive (`PRE` rule in `tools/structures.py`). Sources are re-downloaded to /tmp/bp per CLAUDE.md (not kept in repo). Verified in headless Firefox: all 16 systems on, full body renders, no load errors. Remaining: a few specks of structures still poke through skin at knee/neck.
- 2026-09-21 — Added Space + drag pan (move the model up/down/sideways) over the 3D view; hint text updated. Verified in headless Firefox (model moved with the drag; plain drag still rotates).
