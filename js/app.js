import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

window.__anatomyReady = true; // lets index.html's startup check know the module loaded

/* ---------- Color scheme ---------- */
const SYSTEM_COLOR = {
  skeleton: 0xe3d9c0,
  muscles: 0xb4514a,
  connective: 0xd9d0a8,
  heart: 0xb8324a,
  arteries: 0xe0454f,
  veins: 0x3f7cd6,
  brain: 0xb9a7d9,
  nerves: 0xf2c94c,
  respiratory: 0xe08a9a,
  digestive: 0xc98a4b,
  urinary: 0xd8c25a,
  genital: 0xd98cb3,
  endocrine: 0x8fc9a0,
  senses: 0x7fb6d9,
  skin: 0xe8b89a,
  other: 0x9aa4b2,
};
// Small deterministic lightness jitter per structure so neighbouring bones /
// muscles of one system stay visually distinguishable.
function colorFor(organ) {
  const c = new THREE.Color(SYSTEM_COLOR[organ.system] ?? 0x9aa4b2);
  let h = 0;
  for (let i = 0; i < organ.id.length; i++) h = (h * 31 + organ.id.charCodeAt(i)) >>> 0;
  const hsl = {};
  c.getHSL(hsl);
  c.setHSL(hsl.h, hsl.s, Math.min(0.9, Math.max(0.1, hsl.l + ((h % 1000) / 1000 - 0.5) * 0.12)));
  return c;
}

const SYSTEMS = SystemDefs; // { key, label, kind, bytes } in display order
const SYSTEM_COUNT = Object.fromEntries(SYSTEMS.map((s) => [s.key, Organs.filter((o) => o.system === s.key).length]));
const DEFAULT_ON = new Set(["skeleton"]);

/* ---------- Three.js scene ---------- */
const host = document.getElementById("canvasHost");
const scene = new THREE.Scene();
scene.background = new THREE.Color(getComputedStyle(document.body).getPropertyValue("--bg").trim() || "#0a0e14");

const camera = new THREE.PerspectiveCamera(45, host.clientWidth / host.clientHeight, 1, 5000);
camera.position.set(400, 250, 600);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(host.clientWidth, host.clientHeight);
host.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// Space + drag = pan (move the model up/down/sideways). Holding Space while the
// pointer is over the 3D view turns the left mouse button from "rotate" into
// "pan"; releasing it (or leaving the window) restores rotate. Only active over
// the viewport so Space keeps its normal job (toggling a focused checkbox,
// scrolling) everywhere else. Touch keeps OrbitControls' two-finger pan.
let pointerX = -1, pointerY = -1; // last pointer position (window-wide, so overlays on the view don't count as "leaving" it)
let spaceHeld = false;
const panBadge = document.createElement("div");
panBadge.className = "pan-badge";
panBadge.textContent = "Pan mode — drag to move the model";
panBadge.hidden = true;
host.parentElement.appendChild(panBadge);
function pointerOverView() {
  const r = host.getBoundingClientRect();
  return pointerX >= r.left && pointerX <= r.right && pointerY >= r.top && pointerY <= r.bottom;
}
function setPanMode(on) {
  if (spaceHeld === on) return;
  spaceHeld = on;
  controls.mouseButtons.LEFT = on ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
  host.classList.toggle("panning", on);
  panBadge.hidden = !on;
}
window.addEventListener("pointermove", (e) => { pointerX = e.clientX; pointerY = e.clientY; }, true);
function isTypingTarget(el) {
  return el && (el.tagName === "TEXTAREA" || el.tagName === "SELECT" ||
    (el.tagName === "INPUT" && !["checkbox", "radio", "range", "button"].includes(el.type)));
}
const isSpace = (e) => e.code === "Space" || e.key === " ";
document.addEventListener("keydown", (e) => {
  if (!isSpace(e) || isTypingTarget(document.activeElement)) return;
  if (!spaceHeld && !pointerOverView()) return;
  e.preventDefault(); // no page scroll
  // A focused checkbox/button would otherwise be toggled by Space on key-up.
  const a = document.activeElement;
  if (a && a !== document.body && a.blur) a.blur();
  setPanMode(true);
}, true);
document.addEventListener("keyup", (e) => {
  if (!isSpace(e)) return;
  if (spaceHeld) e.preventDefault();
  setPanMode(false);
}, true);
window.addEventListener("blur", () => setPanMode(false));

scene.add(new THREE.HemisphereLight(0xffffff, 0x1a1a2a, 1.1));
const key1 = new THREE.DirectionalLight(0xffffff, 1.4);
key1.position.set(300, 500, 400);
scene.add(key1);
const key2 = new THREE.DirectionalLight(0xffffff, 0.5);
key2.position.set(-300, 100, -400);
scene.add(key2);

// BodyParts3D uses a Z-up (superior/inferior) coordinate frame; rotate into
// Three.js's Y-up convention so OrbitControls' default "up" behaves naturally.
const root = new THREE.Group();
root.rotation.x = -Math.PI / 2;
scene.add(root);

/* ---------- Loading + mesh bookkeeping ---------- */
const loadedMeshes = new Map(); // organ.id -> THREE.Mesh
const flowRigs = []; // { mesh, start, end, sprite, phase, kind }
let selectedId = null;
let meshOpacity = 1; // driven by the opacity slider

// Per-structure visibility: individually hidden ids, plus an optional isolate
// set (when set, ONLY those structures are shown).
const hiddenIds = new Set();
let isolateIds = null;
const isShown = (id) => !hiddenIds.has(id) && (!isolateIds || isolateIds.has(id));

// One binary bundle per system (data/mesh/<system>.bin): each structure is
// float32 positions[v*3] followed by uint32 indices[t*3] at byte offset `o`
// (see tools/build_data.py). Bundles are fetched once per toggle-on; the
// browser HTTP cache makes re-enabling a system cheap.
// Streams the response so the loading pill can show real progress. The total
// comes from SystemDefs (uncompressed size), not Content-Length, which is the
// compressed size when the host gzips.
const loadingEl = document.getElementById("loadingIndicator");
const loadProgress = new Map(); // system label -> 0..1
function renderLoading() {
  if (!loadProgress.size) { loadingEl.hidden = true; return; }
  loadingEl.textContent = "Loading " + [...loadProgress].map(([l, p]) => `${l} ${Math.round(p * 100)}%`).join(" · ") + "…";
  loadingEl.hidden = false;
}
async function fetchBundle(def) {
  loadProgress.set(def.label, 0);
  renderLoading();
  try {
    const res = await fetch(`data/mesh/${def.key}.bin`);
    if (!res.ok) throw new Error(`${def.key}.bin: HTTP ${res.status}`);
    if (!res.body) return await res.arrayBuffer();
    const reader = res.body.getReader();
    const chunks = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      got += value.length;
      loadProgress.set(def.label, Math.min(0.99, got / def.bytes));
      renderLoading();
    }
    const out = new Uint8Array(got);
    let off = 0;
    for (const c of chunks) { out.set(c, off); off += c.length; }
    return out.buffer;
  } finally {
    loadProgress.delete(def.label);
    renderLoading();
  }
}

function applyOpacity(material) {
  material.opacity = meshOpacity;
  material.transparent = meshOpacity < 1;
  material.depthWrite = meshOpacity >= 0.99;
}

function addOrgan(organ, buffer) {
  if (loadedMeshes.has(organ.id)) return;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(buffer, organ.o, organ.v * 3), 3));
  geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(buffer, organ.o + organ.v * 12, organ.t * 3), 1));
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  const material = new THREE.MeshStandardMaterial({
    color: colorFor(organ),
    roughness: 0.55,
    metalness: 0.05,
    emissive: 0x000000,
    side: THREE.DoubleSide, // the source meshes are not guaranteed watertight / consistently wound
  });
  if (organ.system === "skeleton") {
    // Nudge bones back in depth so muscles that touch/overlap them win the z-fight and cover them.
    material.polygonOffset = true;
    material.polygonOffsetFactor = 2;
    material.polygonOffsetUnits = 2;
  }
  applyOpacity(material);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.userData.organ = organ;
  mesh.visible = isShown(organ.id);
  root.add(mesh);
  loadedMeshes.set(organ.id, mesh);
  if (organ.kind === "artery" || organ.kind === "vein" || organ.kind === "nerve") {
    setupFlowRig(mesh, organ);
  }
}

function unloadOrgan(organ) {
  const mesh = loadedMeshes.get(organ.id);
  if (!mesh) return;
  root.remove(mesh);
  mesh.geometry.dispose();
  mesh.material.dispose();
  loadedMeshes.delete(organ.id);
  hiddenIds.delete(organ.id);
  if (isolateIds) { isolateIds.delete(organ.id); if (!isolateIds.size) isolateIds = null; }
  const rigIdx = flowRigs.findIndex((r) => r.mesh === mesh);
  if (rigIdx >= 0) flowRigs.splice(rigIdx, 1); // sprite is a child of mesh; geometry/material are shared
  if (selectedId === organ.id) clearSelection();
}

// Flow-pulse sprites share one sphere geometry and one material per kind —
// with the full body there are ~640 vessels/nerves.
const SPRITE_GEO = new THREE.SphereGeometry(1, 10, 10);
const SPRITE_MAT = {
  artery: new THREE.MeshBasicMaterial({ color: 0xff5d6c }),
  vein: new THREE.MeshBasicMaterial({ color: 0x6fb4ff }),
  nerve: new THREE.MeshBasicMaterial({ color: 0xf2c94c }),
};

function setupFlowRig(mesh, organ) {
  const box = mesh.geometry.boundingBox;
  const size = new THREE.Vector3();
  box.getSize(size);
  const axis = size.x > size.y ? (size.x > size.z ? "x" : "z") : size.y > size.z ? "y" : "z";
  const start = box.min.clone();
  const end = box.max.clone();
  if (axis === "x") { start.y = end.y = box.min.y + size.y / 2; start.z = end.z = box.min.z + size.z / 2; }
  if (axis === "y") { start.x = end.x = box.min.x + size.x / 2; start.z = end.z = box.min.z + size.z / 2; }
  if (axis === "z") { start.x = end.x = box.min.x + size.x / 2; start.y = end.y = box.min.y + size.y / 2; }

  const sprite = new THREE.Mesh(SPRITE_GEO, SPRITE_MAT[organ.kind]);
  sprite.scale.setScalar(Math.max(1.2, Math.min(size.length() * 0.02, 4)));
  sprite.position.copy(start);
  sprite.visible = false;
  mesh.add(sprite);
  flowRigs.push({ mesh, start, end, sprite, phase: Math.random(), kind: organ.kind });
  sprite.visible = organ.kind === "nerve" ? nerveToggle.checked : bloodToggle.checked;
}

/* ---------- Sidebar: systems ---------- */
const systemListEl = document.getElementById("systemList");
const fmtMB = (b) => (b >= 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB");
systemListEl.innerHTML = SYSTEMS.map(
  (s) => `
  <label class="system-row" title="${SYSTEM_COUNT[s.key]} structures · ${fmtMB(s.bytes)} to download">
    <input type="checkbox" data-system="${s.key}" ${DEFAULT_ON.has(s.key) ? "checked" : ""} />
    <span class="sys-swatch" style="background:#${SYSTEM_COLOR[s.key].toString(16).padStart(6, "0")}"></span>
    ${s.label}
    <span class="sys-count">${SYSTEM_COUNT[s.key]}</span>
  </label>`
).join("");

const systemToken = new Map(); // guards against a fast on→off→on race
const systemLoads = new Map(); // key -> in-flight/finished load promise, while the system is on
function setSystemVisible(systemKey, visible) {
  const p = doSetSystemVisible(systemKey, visible);
  if (visible) systemLoads.set(systemKey, p); else systemLoads.delete(systemKey);
  return p;
}
// Turns a system on if needed and resolves once its meshes exist (used by search).
function ensureSystem(systemKey) {
  if (systemLoads.has(systemKey)) return systemLoads.get(systemKey);
  const cb = systemListEl.querySelector(`[data-system="${systemKey}"]`);
  if (cb) cb.checked = true;
  return setSystemVisible(systemKey, true);
}
async function doSetSystemVisible(systemKey, visible) {
  const organs = Organs.filter((o) => o.system === systemKey);
  const token = Symbol();
  systemToken.set(systemKey, token);
  if (visible) {
    const def = SYSTEMS.find((s) => s.key === systemKey);
    try {
      const buffer = await fetchBundle(def);
      if (systemToken.get(systemKey) !== token) return; // toggled again while loading
      organs.forEach((o) => addOrgan(o, buffer));
      updateVisibilityStatus();
      if (!searchReveal) fitCameraToScene();
    } catch (e) {
      console.error(systemKey, e);
      systemLoads.delete(systemKey);
      loadingEl.textContent = `Could not load ${def.label}`;
      loadingEl.hidden = false;
      const cb = systemListEl.querySelector(`[data-system="${systemKey}"]`);
      if (cb) cb.checked = false;
    }
  } else {
    organs.forEach(unloadOrgan);
  }
}

systemListEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
  cb.addEventListener("change", () => setSystemVisible(cb.dataset.system, cb.checked));
});

const opacityEl = document.getElementById("opacityRange");
opacityEl.addEventListener("input", () => {
  meshOpacity = opacityEl.value / 100;
  loadedMeshes.forEach((m) => applyOpacity(m.material));
});

/* ---------- Selection / highlighting ---------- */
const infoPanel = document.getElementById("infoPanel");
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
let searchReveal = false; // true while search is loading a system, so the load doesn't re-frame the whole body
let bothSides = false; // "hide / isolate both sides" checkbox state, kept across selections

// Left/right twins: same name with left<->right swapped, in the same system.
const ORGAN_BY_NAME = new Map(Organs.map((o) => [o.system + "|" + o.name.toLowerCase(), o]));
function mirrorOf(o) {
  const n = o.name.toLowerCase();
  const m = n.match(/\b(left|right)\b/);
  if (!m) return null;
  const swapped = n.replace(/\b(left|right)\b/, m[1] === "left" ? "right" : "left");
  const twin = ORGAN_BY_NAME.get(o.system + "|" + swapped);
  return twin && twin.id !== o.id ? twin : null;
}

function clearSelection() {
  if (selectedId && loadedMeshes.has(selectedId)) {
    loadedMeshes.get(selectedId).material.emissive.setHex(0x000000);
  }
  selectedId = null;
  infoPanel.hidden = true;
  infoPanel.innerHTML = "";
}
function selectOrgan(mesh) {
  if (selectedId && loadedMeshes.has(selectedId)) {
    loadedMeshes.get(selectedId).material.emissive.setHex(0x000000);
  }
  const o = mesh.userData.organ;
  selectedId = o.id;
  mesh.material.emissive.setHex(0x1a4a48);
  const mirror = mirrorOf(o);
  infoPanel.hidden = false;
  infoPanel.innerHTML = `
    <button type="button" class="card-close" data-act="close" aria-label="Clear selection">×</button>
    <h3>${esc(o.name)}</h3>
    <div class="info-meta">${esc(o.id)} · ${esc(o.systemLabel)}</div>
    <span class="info-kind">${esc(o.kind)}</span>
    <div class="info-meta">${o.t.toLocaleString()} triangles (decimated)</div>
    <div class="card-actions">
      <button type="button" class="pill-btn" data-act="focus" title="Zoom to this structure">Focus</button>
      <button type="button" class="pill-btn" data-act="hide" title="Hide this structure">Hide</button>
      <button type="button" class="pill-btn" data-act="isolate" title="Show only this structure">Isolate</button>
    </div>
    ${mirror ? `<div class="card-mirror">Opposite side: <a data-mirror="${esc(mirror.id)}">${esc(mirror.name)}</a>
      <label><input type="checkbox" id="bothSides" ${bothSides ? "checked" : ""} /> Hide / isolate both sides</label></div>` : ""}`;
}

function selectionIds() {
  const o = Organs.find((x) => x.id === selectedId);
  if (!o) return [];
  const ids = [o.id];
  const mirror = bothSides ? mirrorOf(o) : null;
  if (mirror && loadedMeshes.has(mirror.id)) ids.push(mirror.id);
  return ids;
}
infoPanel.addEventListener("click", (e) => {
  const link = e.target.closest("[data-mirror]");
  if (link) {
    const m = loadedMeshes.get(link.dataset.mirror);
    if (m) { selectOrgan(m); focusOn([m]); }
    return;
  }
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (!act) return;
  const ids = selectionIds();
  if (act === "close") clearSelection();
  else if (act === "focus") focusOn(ids.map((id) => loadedMeshes.get(id)));
  else if (act === "hide") { ids.forEach((id) => hiddenIds.add(id)); clearSelection(); applyVisibility(); }
  else if (act === "isolate") {
    isolateIds = new Set(ids);
    hiddenIds.clear();
    applyVisibility();
    focusOn(ids.map((id) => loadedMeshes.get(id)));
  }
});
infoPanel.addEventListener("change", (e) => {
  if (e.target.id === "bothSides") bothSides = e.target.checked;
});

/* ---------- Per-structure visibility ---------- */
const visibilityEl = document.getElementById("visibilityStatus");
const visibilityText = document.getElementById("visibilityText");
function updateVisibilityStatus() {
  const parts = [];
  if (isolateIds) parts.push(`Isolating ${isolateIds.size}`);
  if (hiddenIds.size) parts.push(`${hiddenIds.size} hidden`);
  visibilityEl.hidden = parts.length === 0;
  visibilityText.textContent = parts.join(" · ");
}
function applyVisibility() {
  loadedMeshes.forEach((m, id) => { m.visible = isShown(id); });
  if (selectedId && !isShown(selectedId)) clearSelection();
  updateVisibilityStatus();
}
document.getElementById("showAllBtn").addEventListener("click", () => {
  hiddenIds.clear();
  isolateIds = null;
  applyVisibility();
});

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
function pickAt(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  // Raycaster ignores .visible, so hidden / non-isolated meshes are filtered out here.
  const hits = raycaster.intersectObjects([...loadedMeshes.values()].filter((m) => m.visible), false);
  // With transparency on, look through the skin so inner structures are pickable.
  const hit = meshOpacity < 1 ? hits.find((h) => h.object.userData.organ.system !== "skin") ?? hits[0] : hits[0];
  return hit ? hit.object : null;
}

// A drag that rotates the view must not count as a click.
let downAt = null;
renderer.domElement.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener("click", (event) => {
  if (downAt && Math.hypot(event.clientX - downAt[0], event.clientY - downAt[1]) > 4) return;
  const hit = pickAt(event);
  if (hit) selectOrgan(hit);
  else clearSelection();
});

// Hover picking is throttled to one raycast per animation frame; with the full
// body loaded (1600+ meshes) firing it on every mousemove would be wasteful.
let hoveredMesh = null;
let pendingMove = null;
renderer.domElement.addEventListener("mousemove", (event) => {
  const had = pendingMove !== null;
  pendingMove = event;
  if (had || event.buttons) return; // already scheduled, or mid-drag
  requestAnimationFrame(() => {
    const ev = pendingMove;
    pendingMove = null;
    if (!ev) return;
    const next = pickAt(ev);
    if (hoveredMesh && hoveredMesh !== next && hoveredMesh.userData.organ.id !== selectedId && loadedMeshes.has(hoveredMesh.userData.organ.id)) {
      hoveredMesh.material.emissive.setHex(0x000000);
    }
    if (next && next.userData.organ.id !== selectedId) {
      next.material.emissive.setHex(0x0d2a29);
    }
    hoveredMesh = next;
    renderer.domElement.style.cursor = next ? "pointer" : "grab";
  });
});

/* ---------- Flow toggles ---------- */
const bloodToggle = document.getElementById("bloodFlowToggle");
const nerveToggle = document.getElementById("nerveSignalToggle");
function updateFlowVisibility() {
  flowRigs.forEach((rig) => {
    rig.sprite.visible = rig.kind === "nerve" ? nerveToggle.checked : bloodToggle.checked;
  });
}
bloodToggle.addEventListener("change", updateFlowVisibility);
nerveToggle.addEventListener("change", updateFlowVisibility);

/* ---------- Camera fit ---------- */
// Frames the given meshes (default: everything currently shown). keepDirection
// keeps the current viewing angle, used when zooming to one structure.
function frameMeshes(meshes, keepDirection) {
  root.updateMatrixWorld(true);
  const box = new THREE.Box3();
  let any = false;
  // Use geometry bounds only: expandByObject would also include the (hidden)
  // flow-pulse sprites, which sit at each mesh's local origin and drag the
  // fit box out to the world origin.
  meshes.forEach((mesh) => {
    if (!mesh) return;
    box.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
    any = true;
  });
  if (!any) return;
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);
  const maxDim = Math.max(size.x, size.y, size.z);
  const dist = maxDim * 1.6 + 50;
  const dir = keepDirection
    ? camera.position.clone().sub(controls.target).normalize()
    : new THREE.Vector3(0.5, 0.35, 1).normalize();
  camera.position.copy(center).add(dir.multiplyScalar(dist));
  camera.near = Math.max(0.5, dist / 100);
  camera.far = dist * 10;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}
function fitCameraToScene() {
  frameMeshes([...loadedMeshes.values()].filter((m) => m.visible), false);
}
function focusOn(meshes) {
  frameMeshes(meshes, true);
}
document.getElementById("resetViewBtn").addEventListener("click", fitCameraToScene);

/* ---------- Search ---------- */
const searchInput = document.getElementById("searchInput");
const searchResults = document.getElementById("searchResults");
const SEARCH_INDEX = Organs.map((o) => ({ o, key: o.name.toLowerCase() }));
let searchHits = [];
let searchActive = -1;

function runSearch(query) {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const out = [];
  for (const e of SEARCH_INDEX) {
    if (!terms.every((t) => e.key.includes(t))) continue;
    const score = e.key.startsWith(terms[0]) ? 0 : e.key.includes(" " + terms[0]) ? 1 : 2;
    out.push({ score, len: e.key.length, o: e.o });
  }
  out.sort((a, b) => a.score - b.score || a.len - b.len || a.o.name.localeCompare(b.o.name));
  return out.map((x) => x.o);
}
function renderSearch() {
  const q = searchInput.value;
  searchHits = runSearch(q);
  searchActive = searchHits.length ? 0 : -1;
  if (!q.trim()) { searchResults.hidden = true; searchResults.innerHTML = ""; return; }
  searchResults.hidden = false;
  const shown = searchHits.slice(0, 40);
  searchResults.innerHTML = shown.length
    ? shown.map((o, i) => `<button type="button" class="search-item${i === 0 ? " active" : ""}" data-i="${i}" role="option">
        <span class="si-name">${esc(o.name)}</span><span class="si-sys">${esc(o.systemLabel)}</span></button>`).join("") +
      (searchHits.length > shown.length ? `<div class="search-empty">${searchHits.length - shown.length} more — keep typing to narrow</div>` : "")
    : `<div class="search-empty">No structure matches “${esc(q.trim())}”.</div>`;
}
function setSearchActive(i) {
  const items = searchResults.querySelectorAll(".search-item");
  if (!items.length) return;
  searchActive = (i + items.length) % items.length;
  items.forEach((el, k) => el.classList.toggle("active", k === searchActive));
  items[searchActive].scrollIntoView({ block: "nearest" });
}

// Shows a structure found by search: loads its system if needed, un-hides it,
// selects it and zooms to it.
async function revealOrgan(o) {
  searchReveal = true;
  try { await ensureSystem(o.system); } finally { searchReveal = false; }
  const mesh = loadedMeshes.get(o.id);
  if (!mesh) return;
  hiddenIds.delete(o.id);
  if (isolateIds) isolateIds.add(o.id);
  applyVisibility();
  selectOrgan(mesh);
  focusOn([mesh]);
}
searchInput.addEventListener("input", renderSearch);
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); setSearchActive(searchActive + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); setSearchActive(searchActive - 1); }
  else if (e.key === "Enter" && searchHits[searchActive]) { e.preventDefault(); revealOrgan(searchHits[searchActive]); }
  else if (e.key === "Escape") { searchInput.value = ""; renderSearch(); }
});
searchResults.addEventListener("click", (e) => {
  const btn = e.target.closest(".search-item");
  if (btn) revealOrgan(searchHits[Number(btn.dataset.i)]);
});

// Esc clears the selection (when not typing in the search box).
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && document.activeElement !== searchInput) clearSelection();
});

/* ---------- Theme toggle ---------- */
function setupTheme() {
  const btn = document.getElementById("themeToggle");
  const saved = (() => { try { return localStorage.getItem("anatomy-theme"); } catch { return null; } })();
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  applyBg();
  btn.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("anatomy-theme", next); } catch {}
    applyBg();
  });
}
function applyBg() {
  scene.background = new THREE.Color(getComputedStyle(document.body).getPropertyValue("--bg").trim() || "#0a0e14");
}
setupTheme();

/* ---------- Resize ---------- */
window.addEventListener("resize", () => {
  camera.aspect = host.clientWidth / host.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(host.clientWidth, host.clientHeight);
});

/* ---------- Init: load default systems ---------- */
(async () => {
  for (const key of DEFAULT_ON) {
    await setSystemVisible(key, true);
  }
})();

/* ---------- Render loop ---------- */
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();
  flowRigs.forEach((rig) => {
    if (!rig.sprite.visible) return;
    const speed = rig.kind === "nerve" ? 0.9 : 0.5;
    const p = (t * speed + rig.phase) % 1;
    rig.sprite.position.lerpVectors(rig.start, rig.end, p);
  });
  controls.update();
  renderer.render(scene, camera);
}
animate();
