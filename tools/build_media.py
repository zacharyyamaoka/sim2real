"""The site's media, built into a cache folder (never git): a MuJoCo render of every card's deployment, each rack station's link as a
GLB for the run page's 3D card, every run's link poses, and, where a run's session recorded its station's camera, that clip cut onto the
run's clock beside the twin's MuJoCo render of the same instants.

Zach, 2026-11-07: "I would like the runs to be a bit more media rich ... video data saved so I could quickly see it (for cameras you
certainly do want to save it) ... remember in traj compare we had the video comparison and the 3D models ... I think we can basically
always have a 3D view ... in these cards I was hoping to see an image of the actual deployment."

    env -u VIRTUAL_ENV MUJOCO_GL=egl /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -I /home/bam/sim2real/tools/build_media.py

Runs in bam_rack_twin's venv (MuJoCo 3.11, numpy, OpenCV, Pillow) with the system's ffmpeg; about 9 minutes the first time on a quiet machine, then only
what changed (each output keeps a stamp of its inputs). Reads, never writes: the app's data (site/adapter.py DATA), sysid's descriptions
(sysid.describe composes each example's MJCF, in place), the rack's deployment record and its cad2robot payload, the station twins' MJCF
(the schedules' twin/scenes), the archive's run npz and session camera recordings, and the replay files that name each model. Writes
MEDIA (--out, else $SIM2REAL_MEDIA, else ~/.cache/sim2real/media); site/build.py serves it at /media/:

    index.json                                 schema sim2real.media/1: what is here, from what, and why a run has no clip
    scenes/<id>.jpg                            a render per card: the six sysid examples and every deployment
    <dep>/stations/<station>.glb               the station's link (glTF 2.0 binary, one node "link") for the 3D card
    <dep>/runs/<run>/links.json                the link's pose per situation and t (data-ui's robotics contract links table)
    <dep>/runs/<run>/media.json                where the session recorded the station's camera: that clip and the twin's render
    <dep>/runs/<run>/real_<serial>.mp4|.jpg    the camera, cut onto the run's clock (H.264, 640 x 360, brightened, the tag boxed)
    <dep>/runs/<run>/sim.mp4|.jpg              MuJoCo's render of the link at each situation's angle, on the same frames

Stock parts: MuJoCo's offscreen Renderer (EGL) and MjSpec; sysid.describe.Description.spec (each example's composed MJCF); bam_rack_twin's
camera map (docs/dataset_clips.py VIEW, parsed, never imported) and its ArUco detector (bam_rack_twin.camera.detector); ffmpeg / H.264; the
cut rule of data-ui's gallery (gallery/examples/sim-to-real/source/build_replays.py: each output frame is the camera frame whose stamp is
nearest a uniform 30 fps grid); glTF 2.0 binary as data-ui's gallery/examples/pid-tuning/source/build_robot.py writes it; Pillow for JPEG.
Ours: a render's staging (floor, sky, light, framing), the station's link drawn from its twin's load, and the links table.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# WHY before any package import: read-only over bam_ws and this repo (-I does not stop bytecode writes), and MuJoCo picks its GL backend
# when it is first imported (headless needs EGL)
sys.dont_write_bytecode = True
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("OMP_NUM_THREADS", "1")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "site"))
sys.path.insert(2, str(REPO / "tools"))

import numpy as np  # noqa: E402

import adapter  # noqa: E402  (stdlib: the app's data folder, station keys)
import archive_roots  # noqa: E402  (the folders a deployment's runs lie under: the rule tools/build_app.py and site/deploy_tree.py read)

SCHEMA = "sim2real.media/1"
# WHY a version and not the file's digest: a comment edit must not re-cut 300 clips; bump it when an output's content changes
VERSION = "4"
MEDIA = Path(os.environ.get("SIM2REAL_MEDIA") or Path.home() / ".cache" / "sim2real" / "media")
RACK_TWIN = Path(os.environ.get("RACK_TWIN_PACKAGE") or "/home/bam/bam_ws/src/dev/bam_rack_twin")
CAMERA_MAP = RACK_TWIN / "docs" / "dataset_clips.py"
SCHEDULES = adapter.SCHEDULES
EXAMPLES = ("pendulum_can11", "ur5e", "ur5e_2f85", "conveyor", "dual_arm_cell", "linescan_cell")
CONTRACT = "data-ui gallery/robotics/CONTRACT.md v1"

FPS = 30
PAD_S = 0.3  # a clip starts 0.3 s before the run's first sample and ends 0.3 s after its last (data-ui gallery build_replays.py)
VIEW_W, VIEW_H = 640, 360  # dataset_clips.py's view: the whole frame, the station's tag boxed (WHY there: a crop missed CAN 11's link)
SCENE_W, SCENE_H = 1280, 800
# the 3D card's rows: every k-th display row, k the smallest that keeps them at or under 30 Hz and 6,000 rows a situation. WHY: the card
# slerps between rows, exact for a turn about one axis (a 1 Hz, 30 degree sine is within 0.2 degree of its 100 Hz samples), and the
# page fetches the file with its samples (a 50 Hz table of the 10-24 thermal runs was 6.7 MB)
LINKS_HZ = 30.0
LINKS_MAX_ROWS = 6000
REAL_RGB = (42, 120, 214)  # data-ui series slot 1 (#2a78d6): real is blue on every page, the tag box too
SIM_RGBA = (0.92, 0.41, 0.2, 0.62)  # slot 2, orange: every model
REAL_RGBA = (0.165, 0.47, 0.84, 1.0)
TARGET_RGBA = (0.55, 0.57, 0.6, 0.35)  # the command: grey, a ghost
TAG_SAMPLE_EVERY = 10  # pass 1 reads every 10th camera frame to find the station's tag
# WHY at least half of a clip's frames new pictures: below that it is a slideshow passed off as motion (data-ui gallery build_replays.py
# refused CAN 14's 10-23 sine, 53 pictures for 195 frames, 25 %); measured over the 317 filmed runs, real clips keep 62 % to 99 %
MIN_NEW = 0.5


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp_of(*paths: Path, extra: str = "") -> str:
    """The inputs' identity (size and mtime, never their bytes: the camera files are a GB) and the code version."""
    parts = [VERSION, extra]
    for p in paths:
        p = Path(p)
        st = p.stat() if p.exists() else None
        parts.append(f"{p}:{st.st_size}:{int(st.st_mtime)}" if st else f"{p}:missing")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def contract_table(name: str, title: str, source: str, fields: list[dict], rows: list[dict]) -> dict:
    return {"name": name, "title": title, "source": source, "contract": CONTRACT, "schema": {"fields": fields}, "rows": rows}


# ------------------------------------------------------------------------------------------------------------- meshes (numpy)

def _cylinder(radius: float, half: float, segments: int = 48) -> tuple[np.ndarray, np.ndarray]:
    """A closed cylinder about z, centred, outward winding."""
    a = np.linspace(0.0, 2 * np.pi, segments, endpoint=False)
    ring = np.c_[radius * np.cos(a), radius * np.sin(a)]
    v = np.vstack([np.c_[ring, np.full(segments, half)], np.c_[ring, np.full(segments, -half)], [[0, 0, half], [0, 0, -half]]])
    top, bot = 2 * segments, 2 * segments + 1
    f = []
    for i in range(segments):
        j = (i + 1) % segments
        f += [[i, segments + i, j], [j, segments + i, segments + j], [top, i, j], [bot, segments + j, segments + i]]
    return v, np.array(f)


def _sphere(radius: float, lat: int = 14, lon: int = 28) -> tuple[np.ndarray, np.ndarray]:
    v = [[0, 0, radius]]
    for i in range(1, lat):
        th = np.pi * i / lat
        for j in range(lon):
            ph = 2 * np.pi * j / lon
            v.append([radius * np.sin(th) * np.cos(ph), radius * np.sin(th) * np.sin(ph), radius * np.cos(th)])
    v.append([0, 0, -radius])
    f, last = [], len(v) - 1
    ring = lambda i, j: 1 + (i - 1) * lon + (j % lon)  # noqa: E731
    for j in range(lon):
        f.append([0, ring(1, j), ring(1, j + 1)])
        f.append([last, ring(lat - 1, j + 1), ring(lat - 1, j)])
    for i in range(1, lat - 1):
        for j in range(lon):
            a, b, c, d = ring(i, j), ring(i, j + 1), ring(i + 1, j), ring(i + 1, j + 1)
            f += [[a, c, b], [b, c, d]]
    return np.array(v, float), np.array(f)


def _box(hx: float, hy: float, hz: float) -> tuple[np.ndarray, np.ndarray]:
    v = np.array([[x, y, z] for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)], float)
    f = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]]
    return v, np.array(f)


def _place(part, yaw: float = 0.0, at=(0.0, 0.0, 0.0)):
    v, f = part
    c, s = math.cos(yaw), math.sin(yaw)
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    return v @ rot.T + np.asarray(at, float), f


def _merge(parts) -> tuple[np.ndarray, np.ndarray]:
    verts, faces, base = [], [], 0
    for v, f in parts:
        verts.append(v)
        faces.append(f + base)
        base += len(v)
    return np.vstack(verts), np.vstack(faces)


# ------------------------------------------------------------------------------------------------------------- the station's link

def twin_load(scene: Path | None) -> dict | None:
    """A twin scene's gravity load (the bare hinge's link inertial under gravity): mass, the centre of mass in the joint frame, G = m g r."""
    if not scene or not scene.is_file():
        return None
    root = ET.parse(scene).getroot()
    gravity = [float(x) for x in (root.find("option").get("gravity") or "0 0 -9.81").split()] if root.find("option") is not None else [0, 0, -9.81]
    inertial = root.find(".//body/inertial")
    if inertial is None or math.hypot(*gravity) < 1e-9:
        return None
    mass = float(inertial.get("mass") or 0)
    com = [float(x) for x in (inertial.get("pos") or "0 0 0").split()]
    r = math.hypot(com[0], com[1])
    if mass < 1e-3 or r < 1e-3:
        return None
    return {"mass_kg": mass, "com_m": com, "radius_m": r, "gravity_nm": mass * math.hypot(*gravity) * r, "gravity_m_s2": gravity}


def link_mesh(load: dict | None) -> tuple[np.ndarray, np.ndarray]:
    """The output link in its joint frame (metres; z the joint axis toward the viewer): the output disc, a spoke to the 100 mm marker the
    poses table follows (tools/build_app.py MARKER_BODY), and, where the twin carries a gravity load, an arm to its centre of mass with a
    bob of steel's density for its mass. A drawing of the twin's numbers, not CAD: the stations' joints are not in the CAD export."""
    parts = [_place(_cylinder(0.025, 0.003), at=(0, 0, 0.003)),
             _place(_box(0.04, 0.0035, 0.0015), at=(0.06, 0, 0.0075)),
             _place(_sphere(0.0065), at=(0.1, 0, 0.0075))]
    if load:
        ux, uy = load["com_m"][0] / load["radius_m"], load["com_m"][1] / load["radius_m"]
        length = 1.12 * load["radius_m"]
        yaw = math.atan2(uy, ux)
        parts.append(_place(_box(length / 2, 0.009, 0.004), yaw=yaw, at=(ux * length / 2, uy * length / 2, 0.016)))
        bob = min(0.045, max(0.011, (3 * load["mass_kg"] / (4 * math.pi * 7800.0)) ** (1 / 3)))
        parts.append(_place(_sphere(bob), at=(load["com_m"][0], load["com_m"][1], 0.016)))
    return _merge(parts)


def write_glb(path: Path, nodes: dict[str, tuple[np.ndarray, np.ndarray]], generator: str) -> dict:
    """glTF 2.0 binary (Khronos spec §4.4: a JSON chunk and one BIN chunk, every bufferView 4-byte aligned), one node per link at its rest
    pose, as data-ui's gallery/examples/pid-tuning/source/build_robot.py writes its UR5e (the card sets each node's pose per row)."""
    blob = bytearray()
    views, accessors, meshes, out_nodes = [], [], [], []

    def view(data: bytes, target: int) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        blob.extend(data)
        return len(views) - 1

    tris = 0
    for name, (v, f) in nodes.items():
        pos = v.astype("<f4")
        accessors.append({"bufferView": view(pos.tobytes(), 34962), "componentType": 5126, "count": len(pos), "type": "VEC3",
                          "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()})
        a_pos = len(accessors) - 1
        idx = f.astype("<u2" if len(pos) < 65536 else "<u4").reshape(-1)
        accessors.append({"bufferView": view(idx.tobytes(), 34963), "componentType": 5123 if len(pos) < 65536 else 5125, "count": int(idx.size), "type": "SCALAR"})
        meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": a_pos}, "indices": len(accessors) - 1, "material": 0, "mode": 4}]})
        out_nodes.append({"name": name, "mesh": len(meshes) - 1, "translation": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0]})
        tris += len(f)
    doc = {"asset": {"version": "2.0", "generator": generator}, "scene": 0, "scenes": [{"nodes": list(range(len(out_nodes)))}], "nodes": out_nodes,
           "meshes": meshes, "materials": [{"name": "link", "pbrMetallicRoughness": {"baseColorFactor": [0.6, 0.62, 0.66, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.6}}],
           "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    while len(blob) % 4:
        blob.append(0)
    text = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    data = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(text) + 8 + len(blob)) + struct.pack("<II", len(text), 0x4E4F534A) + text
            + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"bytes": len(data), "triangles": tris}


# ------------------------------------------------------------------------------------------------------------- MuJoCo staging

def _mujoco():
    import mujoco  # noqa: PLC0415

    return mujoco


def stage(spec, *, floor_z: float | None, sky: bool = True) -> None:
    """A render's staging, added to its own copy of the spec: a light sky, a floor under the model, a headlight and one soft key light.
    WHY the cad2robot payload's look (its c2r_sky / c2r_grid): every card reads as one family of pictures."""
    mujoco = _mujoco()
    spec.visual.headlight.ambient = [0.38, 0.38, 0.38]
    spec.visual.headlight.diffuse = [0.5, 0.5, 0.5]
    spec.visual.headlight.specular = [0.08, 0.08, 0.08]
    spec.visual.global_.offwidth = max(spec.visual.global_.offwidth, SCENE_W)
    spec.visual.global_.offheight = max(spec.visual.global_.offheight, SCENE_H)
    if sky:
        spec.add_texture(name="s2r_sky", type=mujoco.mjtTexture.mjTEXTURE_SKYBOX, builtin=mujoco.mjtBuiltin.mjBUILTIN_GRADIENT,
                         rgb1=[0.95, 0.96, 0.97], rgb2=[0.68, 0.71, 0.76], width=512, height=3072)
    if floor_z is not None:
        spec.add_texture(name="s2r_grid", type=mujoco.mjtTexture.mjTEXTURE_2D, builtin=mujoco.mjtBuiltin.mjBUILTIN_CHECKER,
                         rgb1=[0.86, 0.87, 0.89], rgb2=[0.8, 0.81, 0.84], mark=mujoco.mjtMark.mjMARK_EDGE, markrgb=[0.68, 0.7, 0.74], width=512, height=512)
        material = spec.add_material(name="s2r_floor", texrepeat=[6, 6], texuniform=True, reflectance=0.04)
        material.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = "s2r_grid"
        spec.worldbody.add_geom(name="s2r_floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.05], pos=[0, 0, floor_z], material="s2r_floor",
                                contype=0, conaffinity=0)
    spec.worldbody.add_light(name="s2r_key", pos=[1.5, -2.0, 3.0], dir=[-0.4, 0.55, -0.75], type=mujoco.mjtLightType.mjLIGHT_DIRECTIONAL,
                             diffuse=[0.45, 0.45, 0.45], specular=[0.1, 0.1, 0.1], castshadow=True)


def visible_box(model, data, skip_planes: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """The posed scene's visible geoms as an axis-aligned box (each geom's bounding sphere; planes and invisible geoms left out)."""
    mujoco = _mujoco()
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for g in range(model.ngeom):
        if model.geom_rgba[g][3] < 0.05 or (skip_planes and model.geom_type[g] == mujoco.mjtGeom.mjGEOM_PLANE):
            continue
        if model.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
            m = model.geom_dataid[g]
            v = model.mesh_vert[model.mesh_vertadr[m]: model.mesh_vertadr[m] + model.mesh_vertnum[m]].astype(float)
            pts = v @ data.geom_xmat[g].reshape(3, 3).T + data.geom_xpos[g]
            lo, hi = np.minimum(lo, pts.min(axis=0)), np.maximum(hi, pts.max(axis=0))
            continue
        r = float(model.geom_rbound[g])
        if r <= 0 or r > 50:
            continue
        lo, hi = np.minimum(lo, data.geom_xpos[g] - r), np.maximum(hi, data.geom_xpos[g] + r)
    return lo, hi


def render(model, data, *, azimuth: float, elevation: float, fill: float = 0.92, lookat=None, distance=None, width=SCENE_W, height=SCENE_H,
           cameras: bool = False) -> tuple[np.ndarray, dict]:
    """One offscreen frame from a free camera framing the posed model's visible box (or the lookat and distance given)."""
    mujoco = _mujoco()
    lo, hi = visible_box(model, data)
    centre = (lo + hi) / 2 if lookat is None else np.asarray(lookat, float)
    radius = float(np.linalg.norm(hi - lo) / 2)
    fovy = math.radians(float(model.vis.global_.fovy))
    dist = distance if distance is not None else radius / math.sin(fovy / 2) * fill
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = centre
    cam.distance, cam.azimuth, cam.elevation = dist, azimuth, elevation
    option = mujoco.MjvOption()
    if cameras:
        option.flags[mujoco.mjtVisFlag.mjVIS_CAMERA] = True
    renderer = mujoco.Renderer(model, height, width)
    try:
        renderer.update_scene(data, camera=cam, scene_option=option)
        renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = True
        image = renderer.render().copy()
    finally:
        renderer.close()
    return image, {"azimuth": azimuth, "elevation": elevation, "distance": round(dist, 4), "lookat": [round(float(c), 4) for c in centre],
                   "fovy_deg": float(model.vis.global_.fovy), "width": width, "height": height}


def save_jpeg(image: np.ndarray, path: Path, quality: int = 88) -> int:
    from PIL import Image  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    return path.stat().st_size


# ------------------------------------------------------------------------------------------------------------- the cards' renders

# Each card's view: azimuth, elevation (degrees) and how full the frame is; the arms at their keyframe ("home"), the cell's cameras shown
# (fill < 1 brings the camera in: the distance is the visible box's radius / sin(fovy / 2) x fill)
SCENE_VIEW = {"pendulum_can11": (58, -8, 1.35), "ur5e": (140, -14, 0.82), "ur5e_2f85": (140, -14, 0.82), "conveyor": (128, -24, 0.8),
              "dual_arm_cell": (150, -16, 0.7), "linescan_cell": (122, -24, 0.74), "one-dof-test-rack": (148, -16, 0.5)}
EXAMPLE_WHAT = {
    "pendulum_can11": "CAN 11's twin hinge, the link drawn from the twin's own load (its MJCF has no visual geometry): the joint sysid calibrates.",
    "ur5e": "MuJoCo Menagerie's UR5e at its home keyframe: the arm whose joint zeros and servos sysid calibrates.",
    "ur5e_2f85": "The UR5e with the Robotiq 2F-85 attached at its flange, as bam_arm's cell attaches it.",
    "conveyor": "sysid's conveyor.xml: the belt whose drum radius, moving mass and drag sysid calibrates.",
    "dual_arm_cell": "Two UR5e + 2F-85 on a torso over the conveyor, the head camera's frustum drawn: the cell sysid calibrates.",
    "linescan_cell": "The conveyor under a SWIR line-scan camera and a D435 (their frustums drawn): the sensors sysid calibrates.",
}


def example_scene(example: str) -> tuple[np.ndarray, dict]:
    """sysid's composed MJCF for the example (Description.spec, in place), staged and posed at its first keyframe."""
    mujoco = _mujoco()
    from sysid import describe  # noqa: PLC0415

    description = describe.load(example)
    model_doc = description.manifest["model"]
    files = [model_doc["path"]] if model_doc.get("path") else [p["path"] for p in model_doc.get("parts", [])]
    files += [a["path"] for a in model_doc.get("attach", []) or []] + [a["path"] for p in model_doc.get("parts", []) for a in p.get("attach", []) or []]
    spec = description.spec()
    staging = "a floor, a light sky and a key light added for the picture"
    if example == "pendulum_can11":
        # WHY drawn: the twin's bare hinge carries only an inertial; the picture draws its load (a render-only geom on sysid's own spec)
        load = twin_load(describe.resolve_path(model_doc["path"]))
        v, f = link_mesh(load)
        spec.add_mesh(name="s2r_link", uservert=v.ravel().tolist(), userface=f.ravel().tolist())
        body = spec.worldbody.first_body()
        body.add_geom(name="s2r_link", type=mujoco.mjtGeom.mjGEOM_MESH, meshname="s2r_link", rgba=[0.62, 0.64, 0.68, 1], contype=0, conaffinity=0, group=1)
        body.add_geom(name="s2r_housing", type=mujoco.mjtGeom.mjGEOM_CYLINDER, size=[0.032, 0.022, 0], pos=[0, 0, -0.025],
                      rgba=[0.2, 0.21, 0.23, 1], contype=0, conaffinity=0, group=1)
        # the hinge turned so its gravity (its frame's -y) points down in the picture (MuJoCo's camera is z up), lifted off the floor
        body.quat = [math.cos(math.pi / 4), math.sin(math.pi / 4), 0, 0]
        body.pos = [0, 0, 0.25]
        staging = "the link drawn from the twin's load (its mass at its centre of mass), the hinge turned so its gravity points down, a floor, sky and light"
    model = spec.compile()
    data = mujoco.MjData(model)
    if model.nkey:
        for k in range(model.nkey):
            # every arm at its home: a composed cell keeps one keyframe per attached arm, each setting only its own joints
            key_q = model.key_qpos[k]
            data.qpos[:] = np.where(np.isclose(key_q, model.qpos0), data.qpos, key_q) if k else key_q
    mujoco.mj_forward(model, data)
    lo, _hi = visible_box(model, data)
    qpos = data.qpos.copy()
    # the floor just under the lowest visible geom; the staging adds no degree of freedom, so the pose carries over
    stage(spec, floor_z=float(lo[2]) - 0.002)
    model = spec.compile()
    data = mujoco.MjData(model)
    data.qpos[:] = qpos
    mujoco.mj_forward(model, data)
    az, el, fill = SCENE_VIEW[example]
    image, camera = render(model, data, azimuth=az, elevation=el, fill=fill, cameras=bool(description.cameras))
    return image, {"models": [{"path": str(describe.resolve_path(p)), "sha256": sha256(describe.resolve_path(p))} for p in files],
                   "camera": camera, "staging": staging, "what": EXAMPLE_WHAT[example], "title": description.title}


def deployment_scene(dep: dict) -> tuple[np.ndarray, dict] | None:
    """The deployment's own MJCF: its record's cad2robot payload scene (mjcf/scene.xml), with its own sky and floor."""
    mujoco = _mujoco()
    record = json.loads(Path(dep["record"]).read_text())
    m = re.search(r"(/[^;()]+?)\)\s*$", (record.get("cad") or {}).get("payload") or "")
    if not m:
        return None
    scene = Path(m.group(1)) / "mjcf" / "scene.xml"
    if not scene.is_file():
        return None
    spec = mujoco.MjSpec.from_file(str(scene))
    spec.visual.global_.offwidth = max(spec.visual.global_.offwidth, SCENE_W)
    spec.visual.global_.offheight = max(spec.visual.global_.offheight, SCENE_H)
    spec.worldbody.add_light(name="s2r_key", pos=[1.5, -2.0, 3.0], dir=[-0.4, 0.55, -0.75], type=mujoco.mjtLightType.mjLIGHT_DIRECTIONAL,
                             diffuse=[0.35, 0.35, 0.35], specular=[0.08, 0.08, 0.08], castshadow=True)
    model = spec.compile()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    az, el, fill = SCENE_VIEW.get(dep["id"], (135, -22, 0.7))
    image, camera = render(model, data, azimuth=az, elevation=el, fill=fill)
    return image, {"models": [{"path": str(scene), "sha256": sha256(scene)}], "camera": camera, "title": record.get("title") or dep["id"],
                   "staging": "the payload's own sky and floor, one key light added",
                   "what": f"{dep.get('title') or dep['id']} as its CAD export draws it (cad2robot payload, {scene.parent.parent.name}): the plates and motors; "
                           "the stations' moving links are not in this export yet."}


def build_scenes(media: Path, index: dict, deployments: list[dict], only: set[str] | None) -> None:
    import mujoco  # noqa: PLC0415

    done = {s["id"]: s for s in index.get("scenes", [])}
    out = []
    jobs = [(x, "example") for x in EXAMPLES] + [(d["id"], "deployment") for d in deployments]
    for sid, kind in jobs:
        if only and sid not in only:
            if sid in done:
                out.append(done[sid])
            continue
        started = time.monotonic()
        made = example_scene(sid) if kind == "example" else deployment_scene(next(d for d in deployments if d["id"] == sid))
        if made is None:
            print(f"scene {sid}: no MJCF to render", file=sys.stderr)
            continue
        image, info = made
        src = f"scenes/{sid}.jpg"
        size = save_jpeg(image, media / src)
        files = ", ".join(Path(m["path"]).name for m in info["models"])
        out.append({"id": sid, "kind": kind, "title": info["title"], "src": src, "width": image.shape[1], "height": image.shape[0], "bytes": size,
                    "models": info["models"], "camera": info["camera"], "staging": info["staging"], "what": info["what"],
                    "caption": f"MuJoCo {mujoco.__version__} render of {files} ({info['staging']}).", "written_at": now()})
        print(f"scene {sid}: {image.shape[1]}x{image.shape[0]}, {size:,} bytes in {time.monotonic() - started:.1f} s", file=sys.stderr)
    index["scenes"] = out


# ------------------------------------------------------------------------------------------------------------- stations

def record_twin_scene(dep_id: str, station: str) -> Path | None:
    """The twin of record's scene for a station: the schedule's twin digest (twin/replay.json) when a scene carries it, else the newest."""
    folder = SCHEDULES / dep_id / station / "twin"
    scenes = sorted((folder / "scenes").glob(f"{station}_hinge__*__dt*.xml"), key=lambda p: p.stat().st_mtime) if (folder / "scenes").is_dir() else []
    if not scenes:
        return None
    try:
        digest = json.loads((folder / "replay.json").read_text()).get("twin_digest") or ""
    except (OSError, ValueError):
        digest = ""
    hit = [p for p in scenes if digest and f"__{digest[:8]}__" in p.name]
    return (hit or scenes)[-1]


def build_stations(media: Path, index: dict, site: adapter.Site) -> dict:
    out, meshes = [], {}
    for dep in site.deployments:
        for d in sorted(dep.devices, key=lambda r: r.get("order", 0)):
            key = adapter.station_key(d["device"])
            scene = record_twin_scene(dep.id, key)
            load = twin_load(scene)
            v, f = link_mesh(load)
            rel = f"{dep.id}/stations/{key}.glb"
            info = write_glb(media / rel, {"link": (v, f)}, "sim2real tools/build_media.py")
            drawn = (f"the output disc, a spoke to the 100 mm marker, and an arm to the twin's load: {load['mass_kg']:.3g} kg at {load['radius_m'] * 1e3:.0f} mm "
                     f"from the axis (G = {load['gravity_nm']:.3g} N·m), from {scene.name}" if load else
                     f"the output disc and a spoke to the 100 mm marker ({'the twin carries no gravity load' if scene else 'no twin scene for this station'})")
            out.append({"deployment": dep.id, "station": key, "device": d["device"], "glb": rel, "links": ["link"], "bytes": info["bytes"],
                        "triangles": info["triangles"], "scene": str(scene) if scene else None, "scene_sha256": sha256(scene) if scene else None,
                        "load": load, "drawn_from": drawn})
            meshes[(dep.id, key)] = (v, f, load)
    index["stations"] = out
    return meshes


# ------------------------------------------------------------------------------------------------------------- links

LINK_FIELDS = ([{"name": "t", "type": "number", "unit": "s", "description": "seconds from the run's start (the samples' clock)"},
                {"name": "run", "type": "string"}, {"name": "situation", "type": "string"}, {"name": "source", "type": "string"}]
               + [{"name": "device", "type": "string", "description": "the joint the link turns on: the entity a page scopes the 3D card to"}]
               + [{"name": f"link_{a}", "type": "number", "unit": "mm"} for a in "xyz"] + [{"name": f"link_q{a}", "type": "number"} for a in "wxyz"])


# WHY a stack along the axis (2 mm a series, real in front at 0, every model behind it, the command last): the series' links share one
# plane, and coplanar faces z-fight (the 3D card striped real's disc with the models' orange). The turn about the axis stays exact; the
# offsets are written in the table (stack_mm) and the card's text says so. The MuJoCo clip stacks its links the same way.
LINKS_VERSION = "3"
STACK_MM = 2.0


def stack_of(situations: list[str]) -> dict[str, float]:
    models = sorted(s for s in situations if s not in ("real", "target"))
    stack = {"real": 0.0, **{m: -STACK_MM * (i + 1) for i, m in enumerate(models)}}
    if "target" in situations:
        stack["target"] = -STACK_MM * (len(models) + 1)
    return stack


def links_rows(samples: list[dict]) -> tuple[list[dict], float, dict[str, float]]:
    """Every situation's link pose: a turn about the joint axis (z) by its q at that sample, the link's origin on the axis (at its stack
    offset along it). Rows are every k-th sample of each situation, k the smallest that keeps them at or under LINKS_HZ (the card slerps
    between rows: exact for a turn about one axis)."""
    by: dict[str, list[dict]] = {}
    for s in samples:
        if s.get("q_deg") is None:
            continue
        by.setdefault(s["situation"], []).append(s)
    stack = stack_of(list(by))
    out, hz = [], None
    for situation, rows in by.items():
        if len(rows) > 1:
            dt_med = float(np.median(np.diff([r["t"] for r in rows])))
            rate = 1.0 / dt_med if dt_med > 0 else LINKS_HZ
        else:
            rate = LINKS_HZ
        k = max(1, math.ceil(rate / LINKS_HZ - 1e-9), math.ceil(len(rows) / LINKS_MAX_ROWS))
        hz = rate / k
        picks = list(range(0, len(rows), k))
        if picks[-1] != len(rows) - 1:
            picks.append(len(rows) - 1)
        for r in (rows[i] for i in picks):
            half = math.radians(r["q_deg"]) / 2
            out.append({"t": r["t"], "run": r["run"], "situation": situation, "source": r["source"], "device": r["device"],
                        "link_x": 0.0, "link_y": 0.0, "link_z": stack[situation],
                        "link_qw": round(math.cos(half), 7), "link_qx": 0.0, "link_qy": 0.0, "link_qz": round(math.sin(half), 7)})
    return out, round(hz or 0.0, 3), stack


def build_links(media: Path, index: dict, site: adapter.Site) -> None:
    entries = index.setdefault("runs", {})
    started, made = time.monotonic(), 0
    for dep in site.deployments:
        for r in dep.runs:
            samples_path = site.data / dep.id / "runs" / r["run"] / "samples.json"
            rel = f"{dep.id}/runs/{r['run']}/links.json"
            stamp = stamp_of(samples_path, extra=f"links-{LINKS_VERSION}")
            e = entries.setdefault(r["run"], {"deployment": dep.id})
            if e.get("links_stamp") == stamp and (media / rel).is_file():
                continue
            samples = json.loads(samples_path.read_text())["rows"]
            rows, hz, stack = links_rows(samples)
            doc = contract_table("links", f"Link poses · {r['title']}", f"{samples_path} (tools/build_app.py's samples): a turn about the joint "
                                 "axis by each situation's q; tools/build_media.py", LINK_FIELDS, rows)
            doc["stack_mm"] = stack  # each series' offset along the joint axis (link_z), so equal angles never share a plane
            write_json(media / rel, doc)
            e.update({"links": rel, "links_rows": len(rows), "links_hz": hz, "links_stamp": stamp})
            made += 1
    print(f"links: {made:,} written in {time.monotonic() - started:.1f} s", file=sys.stderr)


# ------------------------------------------------------------------------------------------------------------- the models each run plays

# the pre-sliding study's underscore keys are values it held fixed while it searched the rest (bam_rack_twin docs/presliding_round2.py:
# fixed = {"_sigma0", "_coulomb", "_viscous"} from its direct estimate)
PRIVATE = re.compile(r"^_")


def replay_labels(site: adapter.Site) -> dict[str, dict[str, str]]:
    """{run npz path: {model situation: the replay's own label}} from the files tools/build_app.py reads the models from."""
    out: dict[str, dict[str, str]] = {}
    twin = adapter.DATA / "source" / "twin_replays.json"
    if twin.is_file():
        for run in json.loads(twin.read_text())["runs"]:
            out.setdefault(run["run_path"], {}).update({name: m.get("label") or name for name, m in run["models"].items()})
    rack = REPO / "dashboards" / "source" / "rack_replays.json"
    if rack.is_file():
        for run in json.loads(rack.read_text())["runs"]:
            out.setdefault(run["run_path"], {}).setdefault("twin · full", f"{run.get('twin_name')} ({run.get('twin_version')}; {Path(run.get('dataset_twin_file') or '').name})")
    for entry in json.loads((REPO / "app" / "registry.json").read_text())["deployments"]:
        for root in archive_roots.roots(entry):
            for path in sorted(Path(root).glob("*/analysis/twin_replays.json")):
                doc = json.loads(path.read_text())
                for run in doc.get("runs", []):
                    out.setdefault(run["run_path"], {}).update({name: m.get("label") or name for name, m in run["models"].items()})
    return out


def scene_parameters(scene: Path) -> list[dict]:
    """A twin's parameters as its own MJCF declares them (bam_rack_twin.twin writes these attributes): the axis inertia, viscous damping,
    friction loss, LuGre's five (dcmotor lugre="sigma0 sigma1 Fc Fs vs", MuJoCo's order), the gear gap, and the gravity load."""
    root = ET.parse(scene).getroot()
    rows = []
    joint = root.find(".//joint")
    inertial = root.find(".//body/inertial")
    if joint is not None:
        izz = float((inertial.get("diaginertia") or "0 0 0").split()[2]) if inertial is not None else 0.0
        rows.append({"key": "inertia_kg_m2", "what": "axis inertia (armature + the link's own)", "value": float(joint.get("armature") or 0) + (izz if izz > 1e-8 else 0), "unit": "kg·m²"})
        if joint.get("damping"):
            rows.append({"key": "viscous_nm_s_rad", "what": "viscous damping", "value": float(joint.get("damping")), "unit": "N·m·s/rad"})
        if float(joint.get("frictionloss") or 0) > 0:
            rows.append({"key": "frictionloss_nm", "what": "Coulomb friction (the joint's friction loss)", "value": float(joint.get("frictionloss")), "unit": "N·m"})
    for j in root.iter("joint"):
        if j.get("name", "").endswith("__backlash") and j.get("range"):
            lo, hi = (float(x) for x in j.get("range").split())
            rows.append({"key": "gear_gap_rad", "what": "gear backlash, the whole gap", "value": hi - lo, "unit": "rad"})
    motor = root.find(".//dcmotor")
    if motor is not None and motor.get("lugre"):
        names = [("lugre_sigma0_nm_rad", "LuGre bristle stiffness σ0", "N·m/rad"), ("lugre_sigma1_nm_s_rad", "LuGre bristle damping σ1", "N·m·s/rad"),
                 ("lugre_coulomb_nm", "Coulomb friction Fc", "N·m"), ("lugre_static_nm", "static friction Fs", "N·m"),
                 ("lugre_stribeck_rad_s", "Stribeck speed vs", "rad/s")]
        for (key, what, unit), value in zip(names, (float(x) for x in motor.get("lugre").split())):
            rows.append({"key": key, "what": what, "value": value, "unit": unit})
    load = twin_load(scene)
    if load:
        rows += [{"key": "load_mass_kg", "what": "gravity load's mass", "value": load["mass_kg"], "unit": "kg"},
                 {"key": "load_radius_m", "what": "its centre of mass from the axis", "value": load["radius_m"], "unit": "m"},
                 {"key": "gravity_nm", "what": "gravity torque amplitude G = m g r", "value": load["gravity_nm"], "unit": "N·m"}]
    option = root.find("option")
    if option is not None and option.get("timestep"):
        rows.append({"key": "timestep_s", "what": "physics step", "value": float(option.get("timestep")), "unit": "s"})
    return rows


DIGEST = re.compile(r"(?:@|;\s*)([0-9a-f]{8})\)?")


def model_entry(dep_id: str, device: str, name: str, label: str) -> dict:
    """Where a model's parameters come from: the twin scene its label's digest names (schedules/<station>/twin/scenes), or, for the 10-28
    pre-sliding study's four, the study's identified points (and the fit's start where it kept one)."""
    station = adapter.station_key(device)
    entry = {"device": device, "name": name, "label": label, "parameters": [], "source": None}
    study = {"D round 1", "G LuGre re-identified", "H LuGre + dwell-time static friction", "R LuGre + rate-and-state"}
    if label in study:
        path = Path(f"/archive/datasets/bam_rig/rack_2026-10-28/analysis/presliding_round3_{station}.json")
        if path.is_file():
            doc = json.loads(path.read_text())
            point = doc["points"].get(label) or {}
            # WHY R only: round 3 fitted R, and its file keeps that fit's start; D, G and H were fitted in rounds 1 and 2
            start = doc.get("start") if label.startswith("R ") else None
            for key, value in point.items():
                entry["parameters"].append({"key": key, "what": ("fixed in this fit, not searched (a direct estimate)" if PRIVATE.match(key) else ""), "value": value,
                                            "nominal": (start or {}).get(key), "unit": unit_of(key)})
            entry["source"] = str(path)
            entry["columns"] = "identified"
        return entry
    m = DIGEST.search(label or "")
    if m:
        scenes = list((SCHEDULES / dep_id / station / "twin" / "scenes").glob(f"{station}_hinge__{m.group(1)}__dt*.xml"))
        if scenes:
            entry["parameters"] = scene_parameters(scenes[0])
            entry["source"] = str(scenes[0])
            entry["sha256"] = sha256(scenes[0])
            entry["columns"] = "mjcf"
    return entry


def unit_of(key: str) -> str:
    for suffix, unit in (("_nm_s_rad", "N·m·s/rad"), ("_nm_rad", "N·m/rad"), ("_rad_s", "rad/s"), ("_nm", "N·m"), ("_rad", "rad"), ("_s", "s"), ("_kg_m2", "kg·m²")):
        if key.endswith(suffix):
            return unit
    return ""


def build_models(index: dict, site: adapter.Site) -> None:
    labels = replay_labels(site)
    models, by_run = {}, {}
    for dep in site.deployments:
        for r in dep.runs:
            names = [s for s in r["situations"] if s not in ("real", "target")]
            if not names:
                continue
            own = labels.get(r["npz"], {})
            keys = []
            for name in names:
                label = own.get(name) or name
                key = f"{r['device']}|{name}|{label}"
                if key not in models:
                    models[key] = model_entry(dep.id, r["device"], name, label)
                keys.append(key)
            by_run[r["run"]] = keys
    index["models"] = models
    for run, keys in by_run.items():
        index.setdefault("runs", {}).setdefault(run, {})["models"] = keys
    print(f"models: {len(models)} distinct, {sum(1 for m in models.values() if m['parameters'])} with parameters", file=sys.stderr)


# ------------------------------------------------------------------------------------------------------------- clips

def camera_map() -> dict[int, tuple[str, int]]:
    """{CAN id: (camera serial, tag id)}: bam_rack_twin's literal VIEW (docs/dataset_clips.py), parsed, never imported (it imports cv2)."""
    tree = ast.parse(CAMERA_MAP.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "VIEW" for t in node.targets):
            return {int(k): (str(v[0]), int(v[1])) for k, v in ast.literal_eval(node.value).items()}
    raise SystemExit(f"no VIEW in {CAMERA_MAP}")


def page_shift(npz: dict, samples: list[dict]) -> float:
    """The npz time since its first row at the page clock's 0: found by matching the first real sample's angle and t to the npz (a run
    whose replay dropped a prelude starts its clock later), so a frame at clock t is at wall[0] + t + shift."""
    real = next(s for s in samples if s["situation"] == "real")
    rel = npz["t"] - npz["t"][0]
    score = np.abs(np.degrees(npz["q"]) - real["q_deg"]) * 1e3 + np.abs(rel - real["t"])
    best = int(np.argmin(score))
    return float(rel[best] - real["t"])


def grid_of(npz: dict, samples: list[dict], stamps: np.ndarray) -> dict:
    """The clip's frames: clock t0 + k / FPS from the first sample − PAD_S to the last + PAD_S; each the camera frame whose stamp is nearest
    that instant's wall time (data-ui gallery build_replays.py's rule). t0 is rounded first, so a reader recomputes the same frames."""
    ts = [s["t"] for s in samples]
    shift = page_shift(npz, samples)
    t0 = round(min(ts) - PAD_S, 6)
    n = int(math.floor((max(ts) + PAD_S - t0) * FPS)) + 1
    when = npz["wall"][0] + (t0 + shift) + np.arange(n) / FPS
    j = np.clip(np.searchsorted(stamps, when), 1, len(stamps) - 1)
    left, right = stamps[j - 1], stamps[j]
    idx = np.where(np.abs(when - left) <= np.abs(right - when), j - 1, j)
    gap = np.abs(stamps[idx] - when)
    return {"t0": t0, "n": n, "idx": idx, "max_gap": float(gap.max()), "repeats": int(np.sum(idx[1:] == idx[:-1])), "shift": shift}


def brighten():
    import cv2  # noqa: PLC0415

    lookup = (255.0 * (np.arange(256) / 255.0) ** 0.5).astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    return lambda grey: clahe.apply(cv2.LUT(grey, lookup))


def tag_boxes(mp4: Path, windows: dict[str, tuple[int, int, int]]) -> dict[str, tuple[int, int, int, int] | None]:
    """Pass 1: every TAG_SAMPLE_EVERY-th frame of the session at full resolution, grey and brightened as the detector sees it; each run's
    tag box is the median of its tag's detections inside the run's frames (bam_rack_twin.camera.detector, DICT_4X4_50), padded."""
    import cv2  # noqa: PLC0415

    from bam_rack_twin import camera as camera_truth  # noqa: PLC0415

    w, h = probe_size(mp4)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"select='not(mod(n\\,{TAG_SAMPLE_EVERY}))'", "-fps_mode", "passthrough",
                             "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    finder, light = camera_truth.detector(), brighten()
    found: dict[str, list] = {run: [] for run in windows}
    k = 0
    last = max(hi for _lo, hi, _tag in windows.values())
    while True:
        buf = proc.stdout.read(w * h)
        if len(buf) < w * h:
            break
        n = k * TAG_SAMPLE_EVERY
        k += 1
        busy = [run for run, (lo, hi, _tag) in windows.items() if lo <= n <= hi]
        if busy:
            frame = light(np.frombuffer(buf, np.uint8).reshape(h, w))
            corners, ids, _ = finder.detectMarkers(frame)
            if ids is not None:
                for run in busy:
                    tag = windows[run][2]
                    if tag in ids.ravel():
                        pts = corners[list(ids.ravel()).index(tag)][0]
                        found[run].append((*pts.min(axis=0), *pts.max(axis=0)))
        if n > last:
            break
    proc.stdout.close()
    proc.kill()
    proc.wait()
    out = {}
    for run, boxes in found.items():
        if not boxes:
            out[run] = None
            continue
        x0, y0, x1, y1 = np.median(np.array(boxes), axis=0)
        pad = 0.6 * max(x1 - x0, y1 - y0)
        out[run] = (int(x0 - pad), int(y0 - pad), int(x1 + pad), int(y1 + pad))
    return out


def probe_size(mp4: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(mp4)],
                         capture_output=True, text=True, check=True).stdout.strip().split(",")
    return int(out[0]), int(out[1])


def probe_frames(mp4: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets",
                          "-of", "csv=p=0", str(mp4)], capture_output=True, text=True, check=True).stdout.strip()
    return int(out)


def encoder(path: Path, width: int, height: int, crf: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    # WHY -g FPS: a keyframe every second keeps a browser seek short (bam_rack_twin.render.write_mp4's rule); +faststart: it plays as it loads
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-",
                             "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-g", str(FPS), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                             "-an", str(path)], stdin=subprocess.PIPE)


def draw_box(image: np.ndarray, box, scale: float) -> None:
    if box is None:
        return
    x0, y0, x1, y1 = (int(round(c * scale)) for c in box)
    h, w = image.shape[:2]
    x0, x1, y0, y1 = max(0, x0), min(w - 1, x1), max(0, y0), min(h - 1, y1)
    for b in range(2):
        image[min(h - 1, y0 + b), x0:x1] = REAL_RGB
        image[max(0, y1 - b), x0:x1] = REAL_RGB
        image[y0:y1, min(w - 1, x0 + b)] = REAL_RGB
        image[y0:y1, max(0, x1 - b)] = REAL_RGB


def cut_real(mp4: Path, jobs: list[dict], src_size: tuple[int, int]) -> None:
    """Pass 2: one decode of the session at VIEW_W x VIEW_H, brightened on its luma (as the detector sees it), each run's frames written
    to its own encoder the moment they pass (a run's frame indices never go back), so nothing is held but the current frame."""
    from PIL import Image  # noqa: PLC0415

    import cv2  # noqa: PLC0415

    scale = VIEW_W / src_size[0]
    light = brighten()
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"scale={VIEW_W}:{VIEW_H}", "-fps_mode", "passthrough",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = VIEW_W * VIEW_H * 3
    last = max(int(j["grid"]["idx"][-1]) for j in jobs)
    for j in jobs:
        j["k"], j["enc"] = 0, None
    n = 0
    while n <= last:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        frame = None
        for j in jobs:
            idx = j["grid"]["idx"]
            if j["k"] >= len(idx) or idx[j["k"]] != n:
                continue
            if frame is None:
                # brightened on its luma as the tag detector sees it (dataset_clips.py's gamma 0.5 + CLAHE), the colour kept: the room is dark
                ycc = cv2.cvtColor(np.frombuffer(buf, np.uint8).reshape(VIEW_H, VIEW_W, 3), cv2.COLOR_RGB2YCrCb)
                ycc[:, :, 0] = light(np.ascontiguousarray(ycc[:, :, 0]))
                frame = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB)
                frame_boxed = {}
            if j["enc"] is None:
                j["enc"] = encoder(j["real_path"], VIEW_W, VIEW_H, crf=30)
            key = id(j["box"])
            if key not in frame_boxed:
                img = frame.copy()
                draw_box(img, j["box"], scale)
                frame_boxed[key] = img
            img = frame_boxed[key]
            while j["k"] < len(idx) and idx[j["k"]] == n:
                j["enc"].stdin.write(img.tobytes())
                if j["k"] == len(idx) // 2:
                    Image.fromarray(img).save(j["real_path"].with_suffix(".jpg"), "JPEG", quality=82)
                j["k"] += 1
            if j["k"] >= len(idx):
                j["enc"].stdin.close()
                if j["enc"].wait():
                    raise RuntimeError(f"ffmpeg failed on {j['real_path']}")
                j["enc"] = None
        n += 1
    proc.stdout.close()
    proc.kill()
    proc.wait()
    short = [j["run"] for j in jobs if j["k"] < len(j["grid"]["idx"])]
    for j in jobs:
        if j.get("enc") is not None:
            j["enc"].stdin.close()
            j["enc"].wait()
    if short:
        raise RuntimeError(f"{mp4}: the decode ended before {short[:2]} got every frame")


class StationRenderer:
    """MuJoCo's render of one station: a plate and the motor behind it, and the link once per situation on its own hinge, real blue, each
    model orange, the command a grey ghost; a fixed front camera (the joint's axis toward you, its −y down, as the twin's gravity)."""

    def __init__(self, mesh: tuple[np.ndarray, np.ndarray], situations: list[tuple[str, str]], load: dict | None):
        mujoco = _mujoco()
        self.mujoco = mujoco
        v, f = mesh
        spec = mujoco.MjSpec()
        spec.modelname = "s2r_station"
        spec.option.gravity = [0, 0, 0]
        spec.compiler.inertiafromgeom = 0
        stage(spec, floor_z=None, sky=True)
        spec.visual.global_.offwidth, spec.visual.global_.offheight = max(VIEW_W, SCENE_W), max(VIEW_H, SCENE_H)
        spec.add_mesh(name="link", uservert=v.ravel().tolist(), userface=f.ravel().tolist())
        # joint frame -> world: x stays, y up (z), the axis z toward the camera (world -y)
        display = spec.worldbody.add_body(name="display", quat=[math.cos(math.pi / 4), math.sin(math.pi / 4), 0, 0])
        display.explicitinertial, display.mass, display.inertia = True, 1e-3, [1e-6] * 3
        display.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[0.075, 0.075, 0.0015], pos=[0, 0, -0.0015], rgba=[0.8, 0.81, 0.83, 1], contype=0, conaffinity=0)
        display.add_geom(type=mujoco.mjtGeom.mjGEOM_CYLINDER, size=[0.032, 0.022, 0], pos=[0, 0, -0.025], rgba=[0.2, 0.21, 0.23, 1], contype=0, conaffinity=0)
        self.joints = []
        stack = stack_of([name for name, _source in situations])
        for i, (name, source) in enumerate(situations):
            rgba = {"real": REAL_RGBA, "target": TARGET_RGBA}.get(source, SIM_RGBA)
            # WHY the 3D card's stack along the axis (stack_of): real in front, the models, the command behind, so equal angles never z-fight
            body = display.add_body(name=f"s{i}", pos=[0, 0, stack.get(name, 0.0) / 1000.0])
            body.explicitinertial, body.mass, body.inertia = True, 1e-3, [1e-6] * 3
            body.add_joint(name=f"q{i}", type=mujoco.mjtJoint.mjJNT_HINGE, axis=[0, 0, 1])
            body.add_geom(type=mujoco.mjtGeom.mjGEOM_MESH, meshname="link", rgba=list(rgba), contype=0, conaffinity=0)
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        self.qadr = [self.model.jnt_qposadr[self.model.joint(f"q{i}").id] for i in range(len(situations))]
        reach = max(0.108, (load["radius_m"] * 1.12 + 0.03) if load else 0.108)
        fovy = math.radians(float(self.model.vis.global_.fovy))
        self.cam = mujoco.MjvCamera()
        self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.cam.lookat[:] = [0, 0, 0]
        # WHY 1.2: the 100 mm marker's whole circle (and a load's arm) stays in the picture at any angle, with the elevation's tilt
        self.cam.distance = reach / math.tan(fovy / 2) * 1.2
        self.cam.azimuth, self.cam.elevation = 72.0, -12.0
        self.renderer = mujoco.Renderer(self.model, VIEW_H, VIEW_W)

    def frame(self, angles: list[float]) -> np.ndarray:
        for adr, q in zip(self.qadr, angles):
            self.data.qpos[adr] = q
        self.mujoco.mj_kinematics(self.model, self.data)
        self.renderer.update_scene(self.data, camera=self.cam)
        return self.renderer.render()

    def close(self) -> None:
        self.renderer.close()


def render_sim(job: dict, mesh, load) -> None:
    from PIL import Image  # noqa: PLC0415

    samples = job["samples"]
    by: dict[str, list[tuple[float, float]]] = {}
    source: dict[str, str] = {}
    for s in samples:
        if s.get("q_deg") is not None:
            by.setdefault(s["situation"], []).append((s["t"], math.radians(s["q_deg"])))
            source[s["situation"]] = s["source"]
    names = list(by)
    series = {n: (np.array([a for a, _ in by[n]]), np.array([b for _, b in by[n]])) for n in names}
    renderer = StationRenderer(mesh, [(n, source[n]) for n in names], load)
    enc = encoder(job["sim_path"], VIEW_W, VIEW_H, crf=26)
    n = job["grid"]["n"]
    try:
        for k in range(n):
            t = job["grid"]["t0"] + k / FPS
            angles = [float(np.interp(t, *series[name])) for name in names]  # outside the run its first / last angle is held
            image = renderer.frame(angles)
            enc.stdin.write(np.ascontiguousarray(image).tobytes())
            if k == n // 2:
                Image.fromarray(image).save(job["sim_path"].with_suffix(".jpg"), "JPEG", quality=85)
    finally:
        enc.stdin.close()
        code = enc.wait()
        renderer.close()
    if code:
        raise RuntimeError(f"ffmpeg failed on {job['sim_path']}")


MEDIA_FIELDS = [
    {"name": "src", "type": "string", "description": "the clip, relative to this file"}, {"name": "poster", "type": "string"},
    {"name": "t0", "type": "number", "unit": "s", "description": "the clock's t (the samples' t) at frame 0"},
    {"name": "fps", "type": "number", "unit": "fps"}, {"name": "duration", "type": "number", "unit": "s"},
    {"name": "frames", "type": "integer"}, {"name": "basis", "type": "string"}, {"name": "run", "type": "string"},
    {"name": "device", "type": "string", "description": "the joint the clip is of: the entity a page scopes it to"},
    {"name": "camera", "type": "string"}, {"name": "kind", "type": "string"}, {"name": "situation", "type": "string"}, {"name": "label", "type": "string"},
    {"name": "width", "type": "number", "unit": "px"}, {"name": "height", "type": "number", "unit": "px"},
    {"name": "first_frame", "type": "integer", "description": "the session recording's first frame in the clip (0-based)"},
    {"name": "last_frame", "type": "integer"}, {"name": "repeats", "type": "integer", "description": "output frames that repeat the frame before (camera drops)"},
    {"name": "max_stamp_gap_s", "type": "number", "unit": "s", "description": "the farthest any output frame's picture is from its grid time"},
    {"name": "note", "type": "string"},
]


def session_job(task: dict) -> list[dict]:
    """One session's camera: pass 1 finds each run's tag, pass 2 cuts every run's clip, then each run's MuJoCo render on the same frames."""
    os.environ.setdefault("MUJOCO_GL", "egl")
    mp4, serial = Path(task["mp4"]), task["serial"]
    try:
        stamps = np.asarray(np.load(Path(task["stamps"]))["wall"], float)
    except Exception as error:  # noqa: BLE001 - a truncated recording (one 10-23 camera file is not a zip): its runs say so
        return [{"run": j["run"], "why_none": f"the camera's frame stamps ({Path(task['stamps']).name}) cannot be read ({type(error).__name__})"} for j in task["runs"]]
    frames = probe_frames(mp4)
    if frames != len(stamps):
        return [{"run": j["run"], "why_none": f"the session's {mp4.name} has {frames} frames for {len(stamps)} stamps"} for j in task["runs"]]
    src_size = probe_size(mp4)
    jobs = []
    for j in task["runs"]:
        with np.load(j["npz"]) as archive:
            npz = {k: np.asarray(archive[k], float) for k in ("t", "wall", "q")}
        samples = json.loads(Path(j["samples"]).read_text())["rows"]
        grid = grid_of(npz, samples, stamps)
        new = 1.0 - grid["repeats"] / grid["n"]
        if new < MIN_NEW:
            pictures = len(set(grid["idx"].tolist()))
            jobs.append({**j, "grid_of": {"t0": grid["t0"], "fps": FPS, "frames": grid["n"]},
                         "why_none": (f"the camera kept {pictures} pictures for this run's {grid['n']} clip frames ({100 * new:.0f} % new, the farthest "
                                      f"{grid['max_gap']:.1f} s off): too sparse for a clip, a slideshow and not motion")})
            continue
        out = Path(j["out"])
        jobs.append({**j, "samples": samples, "grid": grid, "real_path": out / f"real_{serial}.mp4", "sim_path": out / "sim.mp4"})
    live = [j for j in jobs if "grid" in j]
    if live:
        boxes = tag_boxes(mp4, {j["run"]: (int(j["grid"]["idx"][0]), int(j["grid"]["idx"][-1]), j["tag"]) for j in live})
        for j in live:
            j["box"] = boxes.get(j["run"])
        cut_real(mp4, live, src_size)
        meshes = {}
        for j in live:
            mesh = meshes.setdefault(j["station"], link_mesh(j["load"]))
            render_sim(j, mesh, j["load"])
    results = []
    for j in jobs:
        if "grid" not in j:
            results.append({"run": j["run"], "why_none": j["why_none"], "grid": j.get("grid_of")})
            # a refused run's clip files from an earlier build are removed, so nothing serves them
            for name in ("media.json", f"real_{serial}.mp4", f"real_{serial}.jpg", "sim.mp4", "sim.jpg"):
                stale = Path(j["out"]) / name
                if stale.is_file():
                    stale.unlink()
            continue
        g = j["grid"]
        common = {"t0": g["t0"], "fps": FPS, "duration": round(g["n"] / FPS, 6), "frames": g["n"], "run": j["run"], "device": j["device"], "kind": "rgb",
                  "width": VIEW_W, "height": VIEW_H}
        boxed = f"the station's tag {j['tag']} boxed in blue" if j.get("box") else f"tag {j['tag']} not found in these frames, so nothing is boxed"
        models = [s for s in j["situations"] if s not in ("real", "target")]
        drawn = ("real (blue) at its encoder angle, " + ("the command as a grey ghost, " if "target" in j["situations"] else "")
                 + (f"and {', '.join(models)} (orange) at their replayed angles" if models else "and no model: none replayed this run"))
        rows = [
            {"src": j["real_path"].name, "poster": j["real_path"].with_suffix(".jpg").name, **common, "basis": "real-camera", "camera": serial,
             "situation": "real", "label": f"Camera {serial} · real", "first_frame": int(g["idx"][0]), "last_frame": int(g["idx"][-1]),
             "repeats": g["repeats"], "max_stamp_gap_s": round(g["max_gap"], 6),
             "note": (f"RealSense D405 {serial}, the session's recording ({Path(task['mp4']).parent.parent.name}) cut onto this run's clock: each frame the camera "
                      f"frame nearest a uniform {FPS} fps grid from {PAD_S} s before the run to {PAD_S} s after it ({g['repeats']} of {g['n']} repeat their "
                      f"neighbour; the farthest is {g['max_gap'] * 1e3:.0f} ms off" + (", so the picture holds through the camera's gap there" if g["max_gap"] > 0.1 else "")
                      + f"). The whole view, brightened, {boxed}. Real footage, not a render.")},
            {"src": j["sim_path"].name, "poster": j["sim_path"].with_suffix(".jpg").name, **common, "basis": "sim-render", "camera": "sim",
             "situation": models[0] if len(models) == 1 else ("twin" if models else "real"), "label": "Twin render · MuJoCo",
             "first_frame": None, "last_frame": None, "repeats": 0, "max_stamp_gap_s": 0.0,
             "note": (f"MuJoCo {_mujoco().__version__} render of the station's link on the same {g['n']} frames: {drawn}. A front view of the joint's own frame "
                      "(its axis toward you, the twin's gravity down), not the camera's calibrated view, so the two pictures can differ by a mirror or a turn.")},
        ]
        write_json(Path(j["out"]) / "media.json", contract_table("media", f"Clips · {j['title']}", f"{task['mp4']} (+ .npz stamps); {j['npz']}; tools/build_media.py",
                                                                 MEDIA_FIELDS, rows))
        results.append({"run": j["run"], "media": f"{j['rel']}/media.json", "camera": serial, "clips": 2, "stamp": j["stamp"],
                        "bytes": sum((Path(j["out"]) / r["src"]).stat().st_size for r in rows)})
    return results


def with_entity(path: Path, device: str) -> None:
    """A clip table written before its rows named their joint gains the column (the clips are unchanged: no re-cut)."""
    doc = json.loads(path.read_text())
    if all(r.get("device") == device for r in doc["rows"]) and any(f["name"] == "device" for f in doc["schema"]["fields"]):
        return
    for r in doc["rows"]:
        r["device"] = device
    if not any(f["name"] == "device" for f in doc["schema"]["fields"]):
        doc["schema"]["fields"].append({"name": "device", "type": "string", "description": "the joint the clip is of: the entity a page scopes it to"})
    write_json(path, doc)


def clip_ok(path: Path) -> bool:
    """A clip cut earlier still meets today's rule (at least MIN_NEW of its frames new pictures)."""
    try:
        real = next(r for r in json.loads(path.read_text())["rows"] if r.get("basis") == "real-camera")
        return 1.0 - real["repeats"] / real["frames"] >= MIN_NEW
    except (OSError, ValueError, StopIteration, KeyError, ZeroDivisionError):
        return False


def build_clips(media: Path, index: dict, site: adapter.Site, stations: dict, workers: int, limit: int | None, only: str | None = None) -> None:
    view = camera_map()
    entries = index.setdefault("runs", {})
    tasks: dict[str, dict] = {}
    skipped = 0
    for dep in site.deployments:
        for r in dep.runs:
            e = entries.setdefault(r["run"], {"deployment": dep.id})
            can = int(r["device"].split()[-1])
            serial, tag = view.get(can, (None, None))
            npz = Path(r["npz"])
            session = npz.parent.parent if npz.parent.name == "runs" else None
            mp4 = session / "cameras" / f"cam_{serial}.mp4" if session and serial else None
            stamps = mp4.with_suffix(".npz") if mp4 else None
            if not mp4 or not mp4.is_file() or not stamps.is_file():
                for k in ("media", "camera", "clips"):
                    e.pop(k, None)
                e["why_none"] = (f"no camera sees {r['device']} in bam_rack_twin's camera map" if not serial else
                                 "this run's session recorded no camera" if not (session and (session / "cameras").is_dir()) else
                                 f"this run's session did not record camera {serial}, the one that sees {r['device']}")
                continue
            rel = f"{dep.id}/runs/{r['run']}"
            samples = site.data / dep.id / "runs" / r["run"] / "samples.json"
            stamp = stamp_of(mp4, samples, npz)
            if e.get("stamp") == stamp and e.get("media") and (media / e["media"]).is_file() and clip_ok(media / e["media"]):
                with_entity(media / e["media"], r["device"])
                skipped += 1
                continue
            key = adapter.station_key(r["device"])
            task = tasks.setdefault(str(mp4), {"mp4": str(mp4), "stamps": str(stamps), "serial": serial, "runs": []})
            task["runs"].append({"run": r["run"], "title": r["title"], "device": r["device"], "npz": str(npz), "samples": str(samples), "out": str(media / rel), "rel": rel,
                                 "tag": tag, "station": key, "load": stations.get((dep.id, key), (None, None, None))[2], "situations": r["situations"],
                                 "stamp": stamp})
    ordered = sorted((t for t in tasks.values() if not only or only in t["mp4"]), key=lambda t: t["mp4"])
    if limit:
        ordered = ordered[:limit]
    print(f"clips: {sum(len(t['runs']) for t in ordered)} runs in {len(ordered)} session recordings to cut ({skipped} up to date)", file=sys.stderr)
    started = time.monotonic()
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(session_job, t): t for t in ordered}
        for future in as_completed(futures):
            task = futures[future]
            try:
                results = future.result()
            except Exception as error:  # noqa: BLE001 - one session's failure is recorded for its runs, the rest go on
                results = [{"run": j["run"], "why_none": f"the cut failed: {type(error).__name__}: {str(error)[:200]}"} for j in task["runs"]]
            for res in results:
                e = entries.setdefault(res["run"], {})
                if res.get("media"):
                    e.update({k: res[k] for k in ("media", "camera", "clips", "stamp", "bytes")})
                    e.pop("why_none", None)
                    e.pop("grid", None)
                else:
                    for k in ("media", "camera", "clips", "stamp", "bytes", "grid"):
                        e.pop(k, None)
                    e["why_none"] = res["why_none"]
                    if res.get("grid"):
                        e["grid"] = res["grid"]  # the clip it would have been: a reader recomputes the refusal from the archive
            done += 1
            print(f"  {done}/{len(ordered)} {Path(task['mp4']).parent.parent.relative_to('/archive/datasets/bam_rig')}: "
                  f"{sum(1 for r in results if r.get('media'))} of {len(results)} clips ({time.monotonic() - started:.0f} s)", file=sys.stderr, flush=True)


# ------------------------------------------------------------------------------------------------------------- main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=adapter.DATA, help=f"the app's data (default {adapter.DATA})")
    parser.add_argument("--out", type=Path, default=MEDIA, help=f"the media folder (default {MEDIA})")
    parser.add_argument("--only", nargs="*", choices=("scenes", "stations", "links", "models", "clips"), help="build only these parts")
    parser.add_argument("--scene", nargs="*", help="render only these scenes (ids)")
    parser.add_argument("--workers", type=int, default=4, help="sessions cut at once (the machine is shared)")
    parser.add_argument("--limit", type=int, help="cut at most this many session recordings (a quick look)")
    parser.add_argument("--session", help="cut only the session recordings whose path holds this text (a quick look)")
    args = parser.parse_args(argv)
    media = args.out.resolve()
    if str(media).startswith(str(REPO.resolve()) + "/"):
        raise SystemExit(f"refusing to write media inside the repo ({media}): media are build outputs, never committed")
    media.mkdir(parents=True, exist_ok=True)
    index_path = media / "index.json"
    index = json.loads(index_path.read_text()) if index_path.is_file() else {}
    if index.get("schema") not in (None, SCHEMA):
        raise SystemExit(f"{index_path} is {index.get('schema')}, not {SCHEMA}")
    import mujoco  # noqa: PLC0415

    site = adapter.load(args.data.resolve())
    registry = {d["id"]: d for d in json.loads((REPO / "app" / "registry.json").read_text())["deployments"]}
    deployments = [registry[d.id] for d in site.deployments if d.id in registry]
    parts = set(args.only or ("scenes", "stations", "links", "models", "clips"))
    index.update({"schema": SCHEMA, "version": VERSION, "renderer": {"mujoco": mujoco.__version__, "gl": os.environ.get("MUJOCO_GL")},
                  "code": "tools/build_media.py", "data": str(args.data.resolve())})
    started = time.monotonic()
    if "scenes" in parts:
        build_scenes(media, index, deployments, set(args.scene) if args.scene else None)
    stations = build_stations(media, index, site) if ("stations" in parts or "clips" in parts) else {}
    if "links" in parts:
        build_links(media, index, site)
    if "models" in parts:
        build_models(index, site)
    if "clips" in parts:
        build_clips(media, index, site, stations, args.workers, args.limit, args.session)
    # runs no longer in the data leave the index (their files stay until the folder is cleared)
    keep = {r["run"] for r in site.runs}
    index["runs"] = {k: v for k, v in index.get("runs", {}).items() if k in keep}
    index["written_at"] = now()
    index["counts"] = {"scenes": len(index.get("scenes", [])), "stations": len(index.get("stations", [])),
                       "runs": len(index["runs"]), "links": sum(1 for e in index["runs"].values() if e.get("links")),
                       "clips": sum(1 for e in index["runs"].values() if e.get("media")),
                       "bytes": sum(p.stat().st_size for p in media.rglob("*") if p.is_file())}
    write_json(index_path, index)
    print(f"media: {index['counts']} -> {media} in {time.monotonic() - started:.0f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
