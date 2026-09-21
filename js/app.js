import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

window.__anatomyReady = true; // lets index.html's startup check know the module loaded

/* ---------- Color scheme ---------- */
const SYSTEM_COLOR = {
  digestive: 0xc98a4b,
  respiratory: 0xe08a9a,
  urinary: 0xd8c25a,
  heart: 0xd1495b,
  brain: 0xb9a7d9,
  vessels: 0x8c8c8c,
  nervous_extra: 0xf2c94c,
};
const KIND_COLOR = {
  artery: 0xd1495b,
  vein: 0x3f7cd6,
  nerve: 0xf2c94c,
};
function colorFor(organ) {
  return KIND_COLOR[organ.kind] ?? SYSTEM_COLOR[organ.system] ?? 0x9aa4b2;
}

const SYSTEMS = [...new Set(Organs.map((o) => o.system))].map((key) => {
  const sample = Organs.find((o) => o.system === key);
  return { key, label: sample.systemLabel, count: Organs.filter((o) => o.system === key).length };
});
const DEFAULT_ON = new Set(["heart"]);

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
const loader = new STLLoader();
const loadedMeshes = new Map(); // organ.id -> THREE.Mesh
const flowRigs = []; // { mesh, axisStart, axisEnd, sprite, phase }
let selectedId = null;

function loadOrgan(organ) {
  if (loadedMeshes.has(organ.id)) return Promise.resolve(loadedMeshes.get(organ.id));
  return new Promise((resolve, reject) => {
    loader.load(
      `data/stl/${organ.id}.stl`,
      (geometry) => {
        geometry.computeVertexNormals();
        geometry.computeBoundingBox();
        const material = new THREE.MeshStandardMaterial({
          color: colorFor(organ),
          roughness: 0.55,
          metalness: 0.05,
          emissive: 0x000000,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData.organ = organ;
        root.add(mesh);
        loadedMeshes.set(organ.id, mesh);
        if (organ.kind === "artery" || organ.kind === "vein" || organ.kind === "nerve") {
          setupFlowRig(mesh, organ);
        }
        resolve(mesh);
      },
      undefined,
      reject
    );
  });
}

function unloadOrgan(organ) {
  const mesh = loadedMeshes.get(organ.id);
  if (!mesh) return;
  root.remove(mesh);
  mesh.geometry.dispose();
  mesh.material.dispose();
  loadedMeshes.delete(organ.id);
  const rigIdx = flowRigs.findIndex((r) => r.mesh === mesh);
  if (rigIdx >= 0) {
    scene.remove(flowRigs[rigIdx].sprite);
    root.remove(flowRigs[rigIdx].sprite);
    flowRigs.splice(rigIdx, 1);
  }
  if (selectedId === organ.id) clearSelection();
}

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

  const isNerve = organ.kind === "nerve";
  const spriteGeo = new THREE.SphereGeometry(Math.max(1.2, Math.min(size.length() * 0.02, 4)), 12, 12);
  const spriteMat = new THREE.MeshBasicMaterial({ color: isNerve ? 0xf2c94c : organ.kind === "vein" ? 0x6fb4ff : 0xff5d6c });
  const sprite = new THREE.Mesh(spriteGeo, spriteMat);
  sprite.visible = false;
  mesh.add(sprite);
  flowRigs.push({ mesh, start, end, sprite, phase: Math.random(), kind: organ.kind });
}

/* ---------- Sidebar: systems ---------- */
const systemListEl = document.getElementById("systemList");
systemListEl.innerHTML = SYSTEMS.map(
  (s) => `
  <label class="system-row">
    <input type="checkbox" data-system="${s.key}" ${DEFAULT_ON.has(s.key) ? "checked" : ""} />
    <span class="sys-swatch" style="background:#${SYSTEM_COLOR[s.key].toString(16).padStart(6, "0")}"></span>
    ${s.label}
    <span class="sys-count">${s.count}</span>
  </label>`
).join("");

const loadingEl = document.getElementById("loadingIndicator");
let pendingLoads = 0;
function trackLoading(promise) {
  pendingLoads++;
  loadingEl.hidden = false;
  return promise.finally(() => {
    pendingLoads--;
    if (pendingLoads <= 0) loadingEl.hidden = true;
  });
}

async function setSystemVisible(systemKey, visible) {
  const organs = Organs.filter((o) => o.system === systemKey);
  if (visible) {
    await trackLoading(Promise.all(organs.map((o) => loadOrgan(o).catch((e) => console.error(o.id, e)))));
    fitCameraToScene();
  } else {
    organs.forEach(unloadOrgan);
  }
}

systemListEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
  cb.addEventListener("change", () => setSystemVisible(cb.dataset.system, cb.checked));
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
    <span class="info-kind">${o.kind}</span>`;
}

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
function pointerToNDC(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
}
renderer.domElement.addEventListener("click", (event) => {
  pointerToNDC(event);
  raycaster.setFromCamera(pointer, camera);
  const meshes = [...loadedMeshes.values()];
  const hits = raycaster.intersectObjects(meshes, false);
  if (hits.length) selectOrgan(hits[0].object);
  else clearSelection();
});

let hoveredMesh = null;
renderer.domElement.addEventListener("mousemove", (event) => {
  pointerToNDC(event);
  raycaster.setFromCamera(pointer, camera);
  const meshes = [...loadedMeshes.values()];
  const hits = raycaster.intersectObjects(meshes, false);
  const next = hits.length ? hits[0].object : null;
  if (hoveredMesh && hoveredMesh !== next && hoveredMesh.userData.organ.id !== selectedId) {
    hoveredMesh.material.emissive.setHex(0x000000);
  }
  if (next && next.userData.organ.id !== selectedId) {
    next.material.emissive.setHex(0x0d2a29);
  }
  hoveredMesh = next;
  renderer.domElement.style.cursor = next ? "pointer" : "grab";
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
