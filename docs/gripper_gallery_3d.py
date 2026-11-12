"""3D payload for the gripper gallery: one gripper's geometry plus a baked open/close cycle, packed for three.js.

Used by docs/build_report_gripper_gallery.py. Per model it returns one gzip+base64 string the page decodes in the
browser (DecompressionStream, so it works from file://). Layout of the decompressed buffer:

    uint32 header_length | header JSON (utf-8, padded to 4 bytes) | binary segments (each padded to 4 bytes)

The header names each segment by (offset, length, dtype); bodies' poses are expressed in the gripper root's own frame,
so an arm that drifts while the fingers move cannot move the gripper off the camera.
"""

from __future__ import annotations

import base64
import gzip
import json

import mujoco
import numpy as np

FPS = 15
CYCLE_S = 3.0  # open -> closed -> open
SETTLE_S = 0.6
VISUAL_TRIANGLE_BUDGET = 9000  # per gripper, across its visual meshes


def _is_collision(model, geom: int) -> bool:
    return bool(model.geom_contype[geom] or model.geom_conaffinity[geom])


def gripper_actuators(model, framed: set[int]) -> list[int]:
    """Actuators whose joint, or a joint in whose tendon, moves a body of the framed gripper."""

    found = []
    for actuator in range(model.nu):
        kind, target = int(model.actuator_trntype[actuator]), int(model.actuator_trnid[actuator, 0])
        if kind in (int(mujoco.mjtTrn.mjTRN_JOINT), int(mujoco.mjtTrn.mjTRN_JOINTINPARENT)):
            if int(model.jnt_bodyid[target]) in framed:
                found.append(actuator)
        elif kind == int(mujoco.mjtTrn.mjTRN_TENDON):
            start, count = int(model.tendon_adr[target]), int(model.tendon_num[target])
            for wrap in range(start, start + count):
                if int(model.wrap_type[wrap]) == int(mujoco.mjtWrap.mjWRAP_JOINT):
                    if int(model.jnt_bodyid[int(model.wrap_objid[wrap])]) in framed:
                        found.append(actuator)
                        break
    return found


def _relative_poses(data, bodies: list[int], root: int) -> np.ndarray:
    """(len(bodies), 7) position + quaternion (w, x, y, z) of each body in the root body's frame."""

    root_rotation = data.xmat[root].reshape(3, 3)
    root_inverse = np.zeros(4)
    mujoco.mju_negQuat(root_inverse, data.xquat[root])
    poses = np.zeros((len(bodies), 7))
    for index, body in enumerate(bodies):
        poses[index, :3] = root_rotation.T @ (data.xpos[body] - data.xpos[root])
        quaternion = np.zeros(4)
        mujoco.mju_mulQuat(quaternion, root_inverse, data.xquat[body])
        poses[index, 3:] = quaternion
    return poses


def bake_cycle(model, root: int, bodies: list[int], framed: set[int], finger_joints_bodies: set[int]):
    """Frames of an open -> closed -> open cycle. Driven through the model's own gripper actuators when it has them
    (so linkages, tendons and couplings move as modelled), gravity off; otherwise by sweeping the finger joints over
    their ranges kinematically. Returns (frames (F, B, 7), how)."""

    data = mujoco.MjData(model)
    if model.nkey:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)
    actuators = [a for a in gripper_actuators(model, framed) if model.actuator_ctrllimited[a]]
    frames: list[np.ndarray] = []
    if actuators:
        gravity = model.opt.gravity.copy()
        model.opt.gravity[:] = 0.0
        low = model.actuator_ctrlrange[actuators, 0].copy()
        high = model.actuator_ctrlrange[actuators, 1].copy()
        step = float(model.opt.timestep)
        per_frame = max(1, int(round(1.0 / (FPS * step))))
        data.ctrl[actuators] = low
        for _ in range(int(SETTLE_S / step)):
            mujoco.mj_step(model, data)
        total = int(round(CYCLE_S * FPS))
        try:
            for index in range(total):
                for _ in range(per_frame):
                    phase = (index + _ / per_frame) / total
                    data.ctrl[actuators] = low + (high - low) * (0.5 - 0.5 * np.cos(2.0 * np.pi * phase))
                    mujoco.mj_step(model, data)
                if not np.all(np.isfinite(data.qpos)):
                    raise FloatingPointError("unstable")
                frames.append(_relative_poses(data, bodies, root))
            how = f"actuated ({len(actuators)} actuator{'s' if len(actuators) > 1 else ''}, gravity off)"
        except FloatingPointError:
            frames = []
        finally:
            model.opt.gravity[:] = gravity
    if not frames:
        joints = [
            joint for joint in range(model.njnt)
            if int(model.jnt_bodyid[joint]) in finger_joints_bodies and model.jnt_limited[joint]
            and int(model.jnt_type[joint]) in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE))
        ]
        mujoco.mj_resetData(model, data)
        if model.nkey:
            mujoco.mj_resetDataKeyframe(model, data, 0)
        total = int(round(CYCLE_S * FPS)) if joints else 1
        for index in range(total):
            share = 0.5 - 0.5 * np.cos(2.0 * np.pi * index / max(total, 1))
            for joint in joints:
                low, high = model.jnt_range[joint]
                data.qpos[model.jnt_qposadr[joint]] = low + (high - low) * share
            mujoco.mj_kinematics(model, data)
            frames.append(_relative_poses(data, bodies, root))
        how = f"kinematic sweep of {len(joints)} finger joint ranges" if joints else "static (no finger actuators or joints)"
    return np.asarray(frames), how


def _simplify(vertices: np.ndarray, faces: np.ndarray, target: int):
    if len(faces) <= target:
        return vertices, faces
    import fast_simplification

    reduction = 1.0 - target / len(faces)
    points, triangles = fast_simplification.simplify(vertices.astype(np.float32), faces.astype(np.int32), reduction)
    return np.asarray(points), np.asarray(triangles)


def _hull(vertices: np.ndarray):
    from scipy.spatial import ConvexHull

    hull = ConvexHull(vertices)
    used = np.unique(hull.simplices)
    remap = {old: new for new, old in enumerate(used)}
    faces = np.array([[remap[i] for i in simplex] for simplex in hull.simplices])
    # Orient every face outward (ConvexHull's simplices are unordered).
    centre = vertices[used].mean(axis=0)
    points = vertices[used]
    for row, (a, b, c) in enumerate(faces):
        if np.dot(np.cross(points[b] - points[a], points[c] - points[a]), points[a] - centre) < 0:
            faces[row] = (a, c, b)
    return points, faces


class _Packer:
    def __init__(self):
        self.chunks: list[bytes] = []
        self.offset = 0

    def add(self, array: np.ndarray, dtype: str) -> list:
        raw = np.ascontiguousarray(array, dtype=dtype).tobytes()
        entry = [self.offset, int(np.asarray(array).size), dtype]
        pad = (-len(raw)) % 4
        self.chunks.append(raw + b"\0" * pad)
        self.offset += len(raw) + pad
        return entry


def _mesh_segment(packer: _Packer, vertices: np.ndarray, faces: np.ndarray) -> dict:
    scale = float(np.abs(vertices).max()) / 32000.0 or 1e-9
    quantised = np.round(vertices / scale).astype(np.int16)
    return {
        "v": packer.add(quantised.reshape(-1), "int16"),
        "scale": scale,
        "f": packer.add(faces.reshape(-1), "uint16" if len(vertices) < 65535 else "uint32"),
    }


def payload(model, root: int, framed: set[int], finger_bodies: set[int], type_colours: dict) -> tuple[str, dict]:
    """(gzip+base64 payload, small summary) for one gripper."""

    bodies = sorted(framed)
    body_index = {body: index for index, body in enumerate(bodies)}
    frames, how = bake_cycle(model, root, bodies, framed, finger_bodies)
    packer = _Packer()
    geoms, meshes = [], {}
    visual_meshes = {
        int(model.geom_dataid[g]) for g in range(model.ngeom)
        if int(model.geom_bodyid[g]) in framed and int(model.geom_type[g]) == int(mujoco.mjtGeom.mjGEOM_MESH)
        and int(model.geom_group[g]) <= 2
    }
    total_faces = sum(int(model.mesh_facenum[m]) for m in visual_meshes) or 1
    for geom in range(model.ngeom):
        body = int(model.geom_bodyid[geom])
        kind = int(model.geom_type[geom])
        if body not in framed or kind in (int(mujoco.mjtGeom.mjGEOM_PLANE), int(mujoco.mjtGeom.mjGEOM_HFIELD)):
            continue
        visual = int(model.geom_group[geom]) <= 2 and model.geom_rgba[geom, 3] > 0
        collision = _is_collision(model, geom)
        if not (visual or collision):
            continue
        matid = int(model.geom_matid[geom])
        rgba = model.mat_rgba[matid] if matid >= 0 else model.geom_rgba[geom]
        entry = {
            "b": body_index[body],
            "t": mujoco.mjtGeom(kind).name.removeprefix("mjGEOM_").lower(),
            "s": [round(float(v), 6) for v in model.geom_size[geom]],
            "p": [round(float(v), 6) for v in model.geom_pos[geom]],
            "q": [round(float(v), 6) for v in model.geom_quat[geom]],
            "rgba": [round(float(v), 3) for v in rgba],
            "vis": bool(visual),
            "col": bool(collision),
            "cc": [round(c, 3) for c in type_colours.get(mujoco.mjtGeom(kind), (0.6, 0.6, 0.62))],
            "finger": body in finger_bodies,
        }
        if kind == int(mujoco.mjtGeom.mjGEOM_MESH):
            mesh = int(model.geom_dataid[geom])
            start, count = int(model.mesh_vertadr[mesh]), int(model.mesh_vertnum[mesh])
            vertices = model.mesh_vert[start:start + count].astype(np.float64)
            face_start, face_count = int(model.mesh_faceadr[mesh]), int(model.mesh_facenum[mesh])
            faces = model.mesh_face[face_start:face_start + face_count].astype(np.int64)
            if visual and f"v{mesh}" not in meshes:
                target = max(120, int(VISUAL_TRIANGLE_BUDGET * face_count / total_faces))
                meshes[f"v{mesh}"] = _mesh_segment(packer, *_simplify(vertices, faces, target))
            if collision and f"h{mesh}" not in meshes:
                # WHY the convex hull: MuJoCo collides a mesh geom as its convex hull, so that is what to show.
                try:
                    meshes[f"h{mesh}"] = _mesh_segment(packer, *_hull(vertices))
                except Exception:  # noqa: BLE001 - degenerate (flat) mesh: show it as is
                    meshes[f"h{mesh}"] = _mesh_segment(packer, *_simplify(vertices, faces, 400))
            entry["m"] = mesh
        geoms.append(entry)
    # Framing over the whole cycle: every geom's centre (in the root frame) +- its bounding radius.
    centres = []
    for geom in range(model.ngeom):
        body = int(model.geom_bodyid[geom])
        if body in framed and float(model.geom_rbound[geom]) < 0.6:
            for frame in frames[:: max(1, len(frames) // 6)]:
                position, quaternion = frame[body_index[body], :3], frame[body_index[body], 3:]
                rotation = np.zeros(9)
                mujoco.mju_quat2Mat(rotation, quaternion)
                centres.append((position + rotation.reshape(3, 3) @ model.geom_pos[geom], float(model.geom_rbound[geom])))
    centre = np.mean([c for c, _ in centres], axis=0) if centres else np.zeros(3)
    radius = max((np.linalg.norm(c - centre) + r for c, r in centres), default=0.1)
    header = {
        "fps": FPS,
        "frames": int(len(frames)),
        "bodies": len(bodies),
        "poses": packer.add(frames.reshape(-1), "float32"),
        "geoms": geoms,
        "meshes": meshes,
        "centre": [round(float(v), 5) for v in centre],
        "radius": round(float(radius), 5),
        "how": how,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode()
    header_bytes += b" " * ((-len(header_bytes)) % 4)
    blob = len(header_bytes).to_bytes(4, "little") + header_bytes + b"".join(packer.chunks)
    encoded = base64.b64encode(gzip.compress(blob, compresslevel=9)).decode()
    return encoded, {"how": how, "frames": int(len(frames)), "payload_kb": round(len(encoded) / 1024, 1)}


VIEWER_JS = r"""
(() => {
const T = window.THREE;
const live = new Map();
let mode = 'both', playing = true;
const DPR = Math.min(window.devicePixelRatio || 1, 2);

async function decode(id) {
  const text = document.getElementById(id).textContent.trim();
  const bytes = Uint8Array.from(atob(text), c => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  const buffer = await new Response(stream).arrayBuffer();
  const n = new DataView(buffer).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, n)));
  const base = 4 + n;
  const view = ([offset, count, dtype]) => {
    const C = {float32: Float32Array, int16: Int16Array, uint16: Uint16Array, uint32: Uint32Array}[dtype];
    return new C(buffer, base + offset, count);
  };
  return {header, view};
}

function primitive(g) {
  const [a, b, c] = g.s;
  switch (g.t) {
    case 'box': return new T.BoxGeometry(2 * a, 2 * b, 2 * c);
    case 'sphere': return new T.SphereGeometry(a, 20, 14);
    case 'ellipsoid': { const s = new T.SphereGeometry(1, 20, 14); s.scale(a, b, c); return s; }
    case 'capsule': { const s = new T.CapsuleGeometry(a, 2 * b, 6, 16); s.rotateX(Math.PI / 2); return s; }
    case 'cylinder': { const s = new T.CylinderGeometry(a, a, 2 * b, 24); s.rotateX(Math.PI / 2); return s; }
  }
  return null;
}

function meshGeometry(entry, view) {
  const q = view(entry.v), f = view(entry.f);
  const positions = new Float32Array(q.length);
  for (let i = 0; i < q.length; i++) positions[i] = q[i] * entry.scale;
  const geometry = new T.BufferGeometry();
  geometry.setAttribute('position', new T.BufferAttribute(positions, 3));
  geometry.setIndex(new T.BufferAttribute(f instanceof Uint32Array ? new Uint32Array(f) : new Uint16Array(f), 1));
  geometry.computeVertexNormals();
  return geometry;
}

function applyMode(state) {
  for (const o of state.visual) { o.visible = mode !== 'collision'; o.material.opacity = 1; o.material.transparent = false; }
  for (const o of state.collision) {
    o.visible = mode !== 'visual';
    const both = mode === 'both';
    o.material.transparent = both; o.material.opacity = both ? 0.62 : 1; o.material.depthWrite = !both;
  }
  if (mode === 'both') for (const o of state.visual) { o.material.transparent = true; o.material.opacity = 0.35; o.material.depthWrite = false; }
}

async function start(card) {
  const id = card.dataset.payload;
  const holder = card.querySelector('.view');
  const {header, view} = await decode(id);
  if (!card.isConnected || !holder.dataset.want) return;
  const renderer = new T.WebGLRenderer({antialias: true, alpha: true});
  renderer.setPixelRatio(DPR);
  renderer.setSize(holder.clientWidth, holder.clientHeight);
  holder.appendChild(renderer.domElement);
  const scene = new T.Scene();
  scene.add(new T.HemisphereLight(0xffffff, 0x8a8f99, 1.6));
  const sun = new T.DirectionalLight(0xffffff, 1.8); sun.position.set(1, -1.4, 2); scene.add(sun);
  const camera = new T.PerspectiveCamera(35, holder.clientWidth / holder.clientHeight, header.radius / 50, header.radius * 50);
  camera.up.set(0, 0, 1);
  const [cx, cy, cz] = header.centre, d = header.radius / Math.tan(17.5 * Math.PI / 180) * 0.8;
  const az = 135 * Math.PI / 180, el = 22 * Math.PI / 180;
  camera.position.set(cx + d * Math.cos(el) * Math.cos(az), cy + d * Math.cos(el) * Math.sin(az), cz + d * Math.sin(el));
  const controls = new window.OrbitControls(camera, renderer.domElement);
  controls.target.set(cx, cy, cz); controls.enableDamping = true; controls.update();
  const bodies = Array.from({length: header.bodies}, () => { const g = new T.Group(); scene.add(g); return g; });
  const state = {visual: [], collision: []};
  const cache = {};
  for (const g of header.geoms) {
    for (const layer of ['vis', 'col']) {
      if (!g[layer]) continue;
      let geometry;
      if (g.t === 'mesh') {
        const key = (layer === 'vis' ? 'v' : 'h') + g.m;
        geometry = cache[key] || (cache[key] = meshGeometry(header.meshes[key], view));
      } else geometry = primitive(g);
      if (!geometry) continue;
      const colour = layer === 'vis' ? new T.Color(g.rgba[0], g.rgba[1], g.rgba[2]) : new T.Color(g.cc[0], g.cc[1], g.cc[2]);
      const material = new T.MeshStandardMaterial({color: colour, roughness: 0.6, metalness: 0.05,
        flatShading: layer === 'col' && g.t === 'mesh'});
      const object = new T.Mesh(geometry, material);
      object.position.set(...g.p);
      object.quaternion.set(g.q[1], g.q[2], g.q[3], g.q[0]);
      bodies[g.b].add(object);
      (layer === 'vis' ? state.visual : state.collision).push(object);
    }
  }
  applyMode(state);
  const poses = view(header.poses);
  const stride = header.bodies * 7;
  let shown = -1, clock = 0, last = performance.now();
  const frameLabel = card.querySelector('.frame');
  function tick(now) {
    if (!live.has(card)) return;
    // WHY clamp: the first rAF timestamp can precede the performance.now() taken at start, giving a negative frame.
    const dt = Math.max(0, (now - last) / 1000); last = now;
    if (playing) clock += dt;
    const frame = ((Math.floor(clock * header.fps) % header.frames) + header.frames) % header.frames;
    if (frame !== shown) {
      for (let b = 0; b < header.bodies; b++) {
        const o = frame * stride + b * 7;
        bodies[b].position.set(poses[o], poses[o + 1], poses[o + 2]);
        bodies[b].quaternion.set(poses[o + 4], poses[o + 5], poses[o + 6], poses[o + 3]);
      }
      shown = frame;
      if (frameLabel) frameLabel.textContent = `${header.how} · frame ${frame + 1}/${header.frames}`;
    }
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  live.set(card, {renderer, state, controls, scene});
  requestAnimationFrame(tick);
}

function stop(card) {
  const entry = live.get(card);
  if (!entry) return;
  live.delete(card);
  entry.controls.dispose();
  entry.scene.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
  entry.renderer.dispose();
  entry.renderer.forceContextLoss();
  entry.renderer.domElement.remove();
}

const observer = new IntersectionObserver(entries => {
  for (const e of entries) {
    const holder = e.target.querySelector('.view');
    if (e.isIntersecting) { holder.dataset.want = '1'; if (!live.has(e.target)) start(e.target).catch(err => { holder.textContent = 'WebGL error: ' + err; }); }
    else { delete holder.dataset.want; stop(e.target); }
  }
}, {rootMargin: '150px'});
document.querySelectorAll('.card[data-payload]').forEach(c => observer.observe(c));

document.getElementById('modes').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.mode) {
    mode = b.dataset.mode;
    document.querySelectorAll('#modes button[data-mode]').forEach(x => x.classList.toggle('on', x === b));
    for (const {state} of live.values()) applyMode(state);
  } else if (b.dataset.play !== undefined) {
    playing = !playing; b.textContent = playing ? 'pause' : 'play'; b.classList.toggle('on', !playing);
  }
});
})();
"""
