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
- 2026-09-21 (later) — Finished the pending work: pan mode now robust (window-wide pointer tracking, blur focused control, on-screen "Pan mode" badge); skeleton `polygonOffset` so muscles cover overlapping bone; `PRE` fixes in `tools/structures.py` (pectoralis major parts → muscles instead of digestive, iliotibial tract → connective) and data rebuilt: skeleton 277, muscles 401, ligaments/fascia 31, digestive 47 (total still 1,629). Bundle offsets/sizes validated against organs.js; headless Firefox render OK (chest muscle, no load errors). Untracked `tools/__pycache__` and added `.gitignore`.

## 2026-10-07
- **Z-Anatomy gap fill** finished (it was half-done: `tools/zanatomy.py` written, not yet wired into the build). Sources had been wiped from /tmp (tmpfs), so re-downloaded to `~/.cache/anatomy-src` (BP3D 4.0 + Z-Anatomy `Startup.blend`).
- `tools/zanatomy.py`: warp = 235 bone/organ anchors, median ICP residual 0.55 mm; 788 pieces written (nerves 248, arteries 232, veins 160, lymph nodes 148). Fixed names that were only a parenthesised label (`right (Fibular node)` → `right fibular node`) — they'd also have collided in the merge key.
- `tools/build_data.py --extra=<dir>`: 69 pieces extend the BP3D structure of the same name/system, 719 become new `ZA-<slug>` structures; organs.js gets `src`. Budget raised to 3.5 M tris so BP3D detail isn't traded away. `tools/structures.py`: new `lymph` system, marginal vein → heart, two generic IS-A names renamed (caudate lobe, pancreas parenchyma).
- App: lymph-node colour; card shows "geometry: Z-Anatomy" (and hides the FMA id for ZA-only ids). Footer/meta credit Z-Anatomy (CC BY-SA 4.0) and say placement is approximate.
- Result: 2,348 structures, 3.5 M tris, 63 MB. Bundles validated (offsets/sizes, finite positions, indices in range, no duplicate ids/names). Skin barely changed (median 0.08 mm vs previous build). Headless Firefox readback: skeleton+arteries+veins+nerves+lymph load with no errors; search "right sciatic nerve" → selected, focused, card + left twin link correct; nerves sit on the skeleton.
- Not checked: real-browser / phone performance with the bigger bundles (arteries and veins ~9.5 MB each now).

## 2026-10-08
- **Male / Female body switch** (user: "we need option to choose male or female"). No complete open female model exists (BodyParts3D and Z-Anatomy are male-only; Z-Anatomy's female collections are empty and a female model is on their TODO list), so the female body = shared BP3D body + the Human Reference Atlas (NIH HuBMAP) Visible Human Female pelvis, uterus, cervix, ovaries, uterine tubes and breasts (CC BY 4.0), fitted to our skeleton (`tools/female.py`, `tools/glb.py`). Pelvis ICP scale 0.814, femoral heads seated < 1 mm; breasts placed by the sternum.
- build_data: `--female`, `mark_male` (27 male-only parts), `female_skin` (penis/scrotum skin solved into a membrane; HRA breast surfaces joined to the skin). Iterations that didn't work, for the record: per-vertex push-out of the male chest (breasts came out boxy/small — nearest-vertex normals underestimate far points), iterated push (unstable), front height-map drape (folded the chest). Using the HRA breast surface directly was the faithful option.
- App: Body segmented control (44 px targets) with an honest note of what is female-specific; counts/search/twins/card follow the body; `?body=female` deep link; switching keeps the camera.
- **Fixed existing bug**: hip bones and kneecaps were labelled "Left/Right hip/knee region" and filed under Other, so the default skeleton view had no pelvis or patellae (`RENAME` in structures.py). Also: Z-Anatomy name "right right testicular artery" → merges into BP3D's right testicular artery; "testi" no longer matches "intestine".
- Verified in headless Firefox (readback): female skin front view (breasts, no male genitalia), female pelvis + uterus/tubes/ovaries close-up via search, live Male→Female switch with systems loaded, male mode regression (prostate search, counts). 2,366 structures, 3.85 M tris, 69 MB.
- Known: the shared `mons pubis` piece is a crumpled sheet poking out of the skin in both bodies (source defect); a small fold remains in the female pubic area; muscles around the iliac crest were fitted to the male pelvis, so they can gap/overlap the female one by ~1–3 cm; breasts have the shape of the (supine) cadaver. Not verified on a real phone.
