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

// One binary bundle per system (data/mesh/<system>.bin): each structure is
// float32 positions[v*3] followed by uint32 indices[t*3] at byte offset `o`
// (see tools/build_data.py). Bundles are fetched once per toggle-on; the
// browser HTTP cache makes re-enabling a system cheap.
async function fetchBundle(systemKey) {
  const res = await fetch(`data/mesh/${systemKey}.bin`);
  if (!res.ok) throw new Error(`${systemKey}.bin: HTTP ${res.status}`);
  return res.arrayBuffer();
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
  applyOpacity(material);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.userData.organ = organ;
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

const loadingEl = document.getElementById("loadingIndicator");
let pendingLoads = 0;
function trackLoading(label, promise) {
  pendingLoads++;
  loadingEl.textContent = `Loading ${label}…`;
  loadingEl.hidden = false;
  return promise.finally(() => {
    pendingLoads--;
    if (pendingLoads <= 0) loadingEl.hidden = true;
  });
}

const systemToken = new Map(); // guards against a fast on→off→on race
async function setSystemVisible(systemKey, visible) {
  const organs = Organs.filter((o) => o.system === systemKey);
  const token = Symbol();
  systemToken.set(systemKey, token);
  if (visible) {
    const def = SYSTEMS.find((s) => s.key === systemKey);
    try {
      const buffer = await trackLoading(def.label, fetchBundle(systemKey));
      if (systemToken.get(systemKey) !== token) return; // toggled again while loading
      organs.forEach((o) => addOrgan(o, buffer));
      fitCameraToScene();
    } catch (e) {
      console.error(systemKey, e);
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
function clearSelection() {
  if (selectedId && loadedMeshes.has(selectedId)) {
    loadedMeshes.get(selectedId).material.emissive.setHex(0x000000);
  }
  selectedId = null;
  infoPanel.innerHTML = `<h2>Selection</h2><p class="info-empty">Click any structure to select it.</p>`;
}
function selectOrgan(mesh) {
  if (selectedId && loadedMeshes.has(selectedId)) {
    loadedMeshes.get(selectedId).material.emissive.setHex(0x000000);
  }
  selectedId = mesh.userData.organ.id;
  mesh.material.emissive.setHex(0x1a4a48);
  const o = mesh.userData.organ;
  infoPanel.innerHTML = `
    <h2>Selection</h2>
    <h3>${o.name}</h3>
    <div class="info-meta">${o.id} · ${o.systemLabel}</div>
    <span class="info-kind">${o.kind}</span>
    <div class="info-meta" style="margin-top:6px">${o.t.toLocaleString()} triangles (decimated)</div>`;
}

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
function pickAt(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects([...loadedMeshes.values()], false);
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
function fitCameraToScene() {
  root.updateMatrixWorld(true);
  const box = new THREE.Box3();
  let any = false;
  // Use geometry bounds only: expandByObject would also include the (hidden)
  // flow-pulse sprites, which sit at each mesh's local origin and drag the
  // fit box out to the world origin.
  loadedMeshes.forEach((mesh) => {
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
  const dir = new THREE.Vector3(0.5, 0.35, 1).normalize();
  camera.position.copy(center).add(dir.multiplyScalar(dist));
  camera.near = Math.max(1, dist / 100);
  camera.far = dist * 10;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}
document.getElementById("resetViewBtn").addEventListener("click", fitCameraToScene);

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
