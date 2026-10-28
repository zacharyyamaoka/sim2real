# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "mujoco==3.17.0"]
# ///
"""The 6-DOF arm and full-sensor-suite stand-ins: a MuJoCo UR5e with a tool, a wrist IMU, a wrist F/T, a scene camera
and a wrist camera, run as a TWIN and as a SYNTHETIC "REAL" plant (the same model with four declared perturbations).

    MUJOCO_GL=egl /home/bam/pidtuna/.venv/bin/python -I /home/bam/sim2real/dashboards/source/arm_suite_sim.py

WHY this exists: no real UR5e run and no real sensor suite exist (2026-10-27). The dashboards still have to be shown at
those scales, so the "real" side here is a stand-in that is visibly marked as one everywhere it lands: every number it
makes carries basis "stand-in", every frame of its video says SYNTHETIC REAL. It is NOT measured data, and the
perturbations below were chosen by the agent to exercise the dashboards (some devices pass, some fail, one fails only
where a derived quantity can see it). Nothing here is evidence about a real arm.

Inputs (read-only):
  - MuJoCo Menagerie's universal_robots_ur5e/ur5e.xml (BSD-3-Clause) at MENAGERIE (the copy data-ui's pid-tuning case
    used); its position actuators (kp 2000 / 500, kv 400 / 100) are the controller for both plants.
  - pidtuna.com's UR5e "coordinated" tape (pidtuna-website site/public/data/ur5e.json, tapes[0].target): the 7.9 s
    six-joint command both plants track.

Writes (into this folder; build.py shapes them into the dashboards' datasets):
  - arm_suite_sim.json: per situation (twin, real_a, real_b = the stand-in run twice for its run-to-run floor) the
    channels at 100 Hz, the link poses for data-ui's meshed UR5e, and each camera's projections of five known points.
  - media/<camera>_<situation>.mp4|jpg: 30 fps renders of the twin and of real_a, labelled in the frame.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import pathlib
import subprocess

os.environ.setdefault("MUJOCO_GL", "egl")

import mujoco
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
MENAGERIE = pathlib.Path(os.environ.get("MENAGERIE", "/home/bam/.cache/lk-gui/library/mujoco_menagerie"))
UR5E = MENAGERIE / "universal_robots_ur5e" / "ur5e.xml"
TAPE = pathlib.Path(os.environ.get("PIDTUNA_DATA", "/home/bam/pidtuna-website/site/public/data")) / "ur5e.json"
OUT = HERE / "arm_suite_sim.json"
MEDIA = HERE / "media"

JOINTS = ["shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint", "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"]
LINKS = ["base", "shoulder_link", "upper_arm_link", "forearm_link", "wrist_1_link", "wrist_2_link", "wrist_3_link"]
RECORD_DT = 0.01          # 100 Hz channels (the tape's own grid)
FPS, WIDTH, HEIGHT = 30, 640, 400
SETTLE_S = 0.6            # hold the first target before the tape starts, so neither plant starts mid-sag
TOOL_MASS_TWIN_KG = 0.8

# The stand-in plant: what makes "real" differ from the twin. Each is a sentence the dashboards print verbatim.
PAYLOAD_EXTRA_KG = 0.2
ELBOW_FRICTION_NM = 6.0
WRIST_1_ENCODER_OFFSET_RAD = 0.004
SCENE_CAM_SHIFT_M = np.array([0.006, -0.004, 0.003])
SCENE_CAM_TILT_RAD = math.radians(0.4)
PERTURBATIONS = [
    {"id": "payload", "devices": ["wrist F/T", "shoulder_lift", "elbow", "wrist_1", "wrist_2"],
     "what": f"tool payload +{PAYLOAD_EXTRA_KG} kg (twin {TOOL_MASS_TWIN_KG} kg, stand-in {TOOL_MASS_TWIN_KG + PAYLOAD_EXTRA_KG} kg)"},
    {"id": "elbow_friction", "devices": ["elbow"], "what": f"elbow Coulomb friction {ELBOW_FRICTION_NM} N·m (twin: none)"},
    {"id": "wrist_1_offset", "devices": ["wrist_1", "tool (EEF)", "wrist camera"],
     "what": f"wrist_1 encoder zero off by +{WRIST_1_ENCODER_OFFSET_RAD * 1e3:.0f} mrad: its encoder reads the target, the link sits "
             f"{WRIST_1_ENCODER_OFFSET_RAD * 1e3:.0f} mrad away (encoder-blind: only the tool and the wrist camera can see it)"},
    {"id": "scene_cam_extrinsic", "devices": ["scene camera"],
     "what": f"scene camera {np.linalg.norm(SCENE_CAM_SHIFT_M) * 1e3:.1f} mm and {math.degrees(SCENE_CAM_TILT_RAD):.1f}° away from its calibrated pose"},
]
# Run-to-run variation of the stand-in (real_a vs real_b): what its floor is made of. Sensor noise per sample (1 sigma).
NOISE = {"q": 2e-5, "tau": 0.15, "force": 0.3, "torque": 0.02, "accel": 0.03, "gyro": 0.002, "tool": 5e-5, "pixel": 0.25}
REPEAT_FRICTION_SCALE = {"real_a": 1.0, "real_b": 1.05}
# WHY a command-timing difference between the two stand-in repeats: on real hardware two runs of one tape never latch
# their commands at the same instant (USB/CAN scheduling), and that jitter, not encoder noise, dominates a moving floor.
REPEAT_COMMAND_DELAY_S = {"twin": 0.0, "real_a": 0.0, "real_b": 0.001}
SEEDS = {"real_a": 1, "real_b": 2}


def look_at_quat(eye: np.ndarray, target: np.ndarray, up=(0.0, 0.0, 1.0)) -> np.ndarray:
    """MuJoCo camera quaternion (wxyz) looking from eye at target: the camera looks along its -z, y up."""

    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, np.asarray(up))
    right = right / np.linalg.norm(right)
    back = -forward
    camera_up = np.cross(back, right)
    rotation = np.column_stack([right, camera_up, back])
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, rotation.flatten())
    return quat


def tilt(quat: np.ndarray, angle_rad: float, axis=(1.0, 1.0, 0.0)) -> np.ndarray:
    axis = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
    delta = np.zeros(4)
    mujoco.mju_axisAngle2Quat(delta, axis, angle_rad)
    out = np.zeros(4)
    mujoco.mju_mulQuat(out, quat, delta)
    return out


SCENE_EYE = np.array([0.55, -1.25, 0.95])
SCENE_TARGET = np.array([-0.35, -0.1, 0.32])
BLOCKS = [  # (name, xyz centre, rgba): known points both cameras can see, on a table under the tape's tool path
    ("block_red", (-0.66, -0.22, 0.135), (0.85, 0.25, 0.2, 1)),
    ("block_green", (-0.52, 0.02, 0.135), (0.25, 0.7, 0.35, 1)),
    ("block_blue", (-0.72, 0.06, 0.135), (0.25, 0.45, 0.85, 1)),
    ("block_yellow", (-0.48, -0.26, 0.135), (0.9, 0.75, 0.2, 1)),
]


def build_model(situation: str) -> mujoco.MjModel:
    """The UR5e + tool + sensors + cameras; `situation` "twin" is nominal, the real_* plants carry the perturbations."""

    stand_in = situation != "twin"
    spec = mujoco.MjSpec.from_file(str(UR5E))
    spec.option.timestep = 0.002
    world = spec.worldbody
    spec.visual.headlight.ambient = [0.35, 0.35, 0.35]
    spec.visual.headlight.diffuse = [0.55, 0.55, 0.55]
    world.add_light(pos=[0.0, -0.5, 2.0], dir=[0.0, 0.2, -1.0], diffuse=[0.5, 0.5, 0.5])
    world.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[3, 3, 0.05], rgba=[0.86, 0.87, 0.89, 1])
    world.add_geom(name="table", type=mujoco.mjtGeom.mjGEOM_BOX, pos=[-0.6, -0.1, 0.05], size=[0.28, 0.32, 0.05],
                   rgba=[0.55, 0.47, 0.38, 1])
    for name, centre, rgba in BLOCKS:
        world.add_geom(name=name, type=mujoco.mjtGeom.mjGEOM_BOX, pos=list(centre), size=[0.035, 0.035, 0.035], rgba=list(rgba))
    world.add_geom(name="base_stand", type=mujoco.mjtGeom.mjGEOM_CYLINDER, pos=[0, 0, -0.001], size=[0.09, 0.001],
                   rgba=[0.3, 0.3, 0.32, 1])
    scene_quat = look_at_quat(SCENE_EYE, SCENE_TARGET)
    scene_pos = SCENE_EYE.copy()
    if stand_in:
        scene_pos = scene_pos + SCENE_CAM_SHIFT_M
        scene_quat = tilt(scene_quat, SCENE_CAM_TILT_RAD)
    world.add_camera(name="scene_cam", pos=list(scene_pos), quat=list(scene_quat), fovy=42)

    wrist_3 = spec.body("wrist_3_link")
    # the tool sits at Menagerie's attachment_site (pos 0 0.1 0, quat -1 1 0 0): its z axis points out of the flange
    tool_mass = TOOL_MASS_TWIN_KG + (PAYLOAD_EXTRA_KG if stand_in else 0.0)
    tool = wrist_3.add_body(name="tool", pos=[0, 0.1, 0], quat=[-1, 1, 0, 0])
    tool.add_geom(type=mujoco.mjtGeom.mjGEOM_CYLINDER, pos=[0, 0, 0.04], size=[0.035, 0.04], rgba=[0.2, 0.22, 0.25, 1],
                  mass=tool_mass, contype=0, conaffinity=0)
    tool.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, pos=[0.02, 0, 0.1], size=[0.006, 0.012, 0.02], rgba=[0.6, 0.6, 0.62, 1],
                  mass=0.001, contype=0, conaffinity=0)
    tool.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, pos=[-0.02, 0, 0.1], size=[0.006, 0.012, 0.02], rgba=[0.6, 0.6, 0.62, 1],
                  mass=0.001, contype=0, conaffinity=0)
    tool.add_site(name="ft_site", pos=[0, 0, 0])
    tool.add_site(name="imu_site", pos=[0, 0, 0.02])
    tool.add_site(name="tcp", pos=[0, 0, 0.12])
    # WHY the wrist camera looks along the tool axis from beside the fingers: an eye-in-hand view of the table blocks
    tool.add_camera(name="wrist_cam", pos=[0.09, 0, 0.0], quat=[0, 1, 0, 0], fovy=58)
    spec.add_sensor(name="ft_force", type=mujoco.mjtSensor.mjSENS_FORCE, objtype=mujoco.mjtObj.mjOBJ_SITE, objname="ft_site")
    spec.add_sensor(name="ft_torque", type=mujoco.mjtSensor.mjSENS_TORQUE, objtype=mujoco.mjtObj.mjOBJ_SITE, objname="ft_site")
    spec.add_sensor(name="imu_accel", type=mujoco.mjtSensor.mjSENS_ACCELEROMETER, objtype=mujoco.mjtObj.mjOBJ_SITE, objname="imu_site")
    spec.add_sensor(name="imu_gyro", type=mujoco.mjtSensor.mjSENS_GYRO, objtype=mujoco.mjtObj.mjOBJ_SITE, objname="imu_site")
    if stand_in:
        spec.joint("elbow_joint").frictionloss = ELBOW_FRICTION_NM * REPEAT_FRICTION_SCALE[situation]
    return spec.compile()


def load_tape() -> tuple[np.ndarray, float]:
    tape = json.loads(TAPE.read_text())["tapes"][0]
    q = np.array([tape["target"][joint]["q"] for joint in JOINTS]).T
    return q, float(tape["dt"])


def project(model, data, camera: str, points: np.ndarray) -> np.ndarray:
    """Pixel (u, v) of each world point through `camera` (pinhole at MuJoCo's fovy; v down), shape (n, 2)."""

    cam = model.camera(camera).id
    focal = 0.5 * HEIGHT / math.tan(math.radians(model.cam_fovy[cam]) / 2)
    rotation = data.cam_xmat[cam].reshape(3, 3)
    local = (points - data.cam_xpos[cam]) @ rotation  # rows: R^T (p - c)
    depth = -local[:, 2]
    pixels = np.column_stack([WIDTH / 2 + focal * local[:, 0] / depth, HEIGHT / 2 - focal * local[:, 1] / depth])
    # WHY NaN off-image: a point behind the camera or outside the frame is not observed, so it never enters an error
    unseen = (depth <= 0.02) | (pixels[:, 0] < 0) | (pixels[:, 0] > WIDTH) | (pixels[:, 1] < 0) | (pixels[:, 1] > HEIGHT)
    pixels[unseen] = np.nan
    return pixels


def simulate(situation: str, tape_q: np.ndarray, tape_dt: float, render: bool) -> dict:
    model = build_model(situation)
    data = mujoco.MjData(model)
    stand_in = situation != "twin"
    rng = np.random.default_rng(SEEDS.get(situation, 0))
    offset = np.zeros(6)
    if stand_in:
        offset[3] = WRIST_1_ENCODER_OFFSET_RAD
    # the physical joint goes where the controller puts the ENCODER: target - offset (the offset is the encoder's)
    data.qpos[:6] = tape_q[0] - offset
    mujoco.mj_forward(model, data)
    steps_per_record = round(RECORD_DT / model.opt.timestep)
    total_s = SETTLE_S + (len(tape_q) - 1) * tape_dt
    tcp = model.site("tcp").id
    sensor = {name: (model.sensor(name).adr[0], model.sensor(name).dim[0]) for name in ("ft_force", "ft_torque", "imu_accel", "imu_gyro")}
    block_points = np.array([centre for _, centre, _ in BLOCKS])
    renderer = mujoco.Renderer(model, height=HEIGHT, width=WIDTH) if render else None
    frames = {"scene_cam": [], "wrist_cam": []}
    next_frame_t = -SETTLE_S
    rows = []

    def target_at(t: float) -> np.ndarray:
        x = min(max(t / tape_dt, 0.0), len(tape_q) - 1.0)
        k = min(int(x), len(tape_q) - 2)
        return tape_q[k] + (x - k) * (tape_q[k + 1] - tape_q[k])

    n_records = int(round(total_s / RECORD_DT)) + 1
    for record in range(n_records):
        t = record * RECORD_DT - SETTLE_S
        if record:
            for _ in range(steps_per_record):
                sim_t = data.time - SETTLE_S
                data.ctrl[:6] = target_at(sim_t - REPEAT_COMMAND_DELAY_S[situation]) - offset
                mujoco.mj_step(model, data)
        measured_q = data.qpos[:6] + offset
        def read(name):
            adr, dim = sensor[name]
            return data.sensordata[adr:adr + dim].copy()
        row = {
            "t": round(t, 4),
            "q_target": target_at(t).tolist(),
            "q": measured_q.tolist(),
            # the plant's true joint angles: a real arm never reports these (its encoders do); the error budget uses them
            # to say how much of the tool error each joint causes, and the stand-in can afford the truth
            "q_true": data.qpos[:6].tolist(),
            "tau": data.actuator_force[:6].tolist(),
            "tool": data.site_xpos[tcp].tolist(),
            "force": read("ft_force").tolist(),
            "torque": read("ft_torque").tolist(),
            "accel": read("imu_accel").tolist(),
            "gyro": read("imu_gyro").tolist(),
            "links": {link: data.xpos[model.body(link).id].tolist() + data.xquat[model.body(link).id].tolist() for link in LINKS},
            "pixels": {cam: project(model, data, cam, np.vstack([data.site_xpos[tcp], block_points])).tolist() for cam in frames},
        }
        if stand_in:  # sensor noise on the stand-in only: the twin is the model, the stand-in plays a measured device
            for key in ("q", "tau", "tool", "force", "torque", "accel", "gyro"):
                row[key] = (np.asarray(row[key]) + rng.normal(0, NOISE[key if key != "tool" else "tool"], len(row[key]))).tolist()
            for cam in row["pixels"]:
                row["pixels"][cam] = (np.asarray(row["pixels"][cam]) + rng.normal(0, NOISE["pixel"], (len(BLOCKS) + 1, 2))).tolist()
        rows.append(row)
        while render and t >= next_frame_t - 1e-9 and t >= 0 - 1e-9:
            for cam in frames:
                renderer.update_scene(data, camera=cam)
                frames[cam].append(renderer.render().copy())
            next_frame_t += 1.0 / FPS
        if render and t < 0:
            next_frame_t = 0.0
    if renderer:
        renderer.close()
    return {"rows": [r for r in rows if r["t"] >= -1e-9], "frames": frames}


ERROR_SCALE = 20.0  # WHY: twin-vs-real differences are ~1 mm at the tool, invisible in a 3D view of a 1 m arm


def kinematics(model, data, q: np.ndarray) -> dict:
    data.qpos[:6] = q
    mujoco.mj_kinematics(model, data)
    return {"tool": data.site_xpos[model.site("tcp").id].tolist(),
            "links": {link: data.xpos[model.body(link).id].tolist() + data.xquat[model.body(link).id].tolist() for link in LINKS}}


def exaggerated_twin(twin_rows: list[dict], real_rows: list[dict]) -> list[dict]:
    """The twin drawn with its joint error against the stand-in scaled ERROR_SCALE times (FEA-style deformation scale):
    q = q_real_true + scale (q_twin - q_real_true), through the twin's own kinematics. A display aid, labelled as one."""

    model = build_model("twin")
    data = mujoco.MjData(model)
    rows = []
    for twin, real in zip(twin_rows, real_rows):
        q = np.asarray(real["q_true"]) + ERROR_SCALE * (np.asarray(twin["q_true"]) - np.asarray(real["q_true"]))
        rows.append({"t": twin["t"], **kinematics(model, data, q)})
    return rows


def tool_targets(rows: list[dict]) -> list[list[float]]:
    model = build_model("twin")
    data = mujoco.MjData(model)
    return [kinematics(model, data, np.asarray(row["q_target"]))["tool"] for row in rows]


def encode(frames: list[np.ndarray], path: pathlib.Path, label: str, colour: str) -> None:
    """H.264 (yuv420p, faststart) with the label burned into every frame, plus the middle frame as a JPEG poster.
    WHY bottom-left: data-ui's overlay card puts its own A/B chips along the top edge."""

    text = label.replace(":", "\\:")
    draw = (f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{text}':x=12:y=h-th-14:fontsize=17:"
            f"fontcolor=white:box=1:boxcolor={colour}@0.85:boxborderw=7")
    command = ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
               "-r", str(FPS), "-i", "-", "-vf", draw, "-c:v", "libx264", "-preset", "slow", "-crf", "27",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
    subprocess.run(command, input=np.stack(frames).astype(np.uint8).tobytes(), check=True)
    middle = len(frames) / 2 / FPS
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{middle:.2f}", "-i", str(path), "-frames:v", "1",
                    "-q:v", "4", str(path.with_suffix(".jpg"))], check=True)


def json_safe(value):
    """NaN (an unseen pixel) as null: JSON has no NaN."""

    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def main() -> int:
    tape_q, tape_dt = load_tape()
    MEDIA.mkdir(exist_ok=True)
    runs = {}
    for situation in ("twin", "real_a", "real_b"):
        result = simulate(situation, tape_q, tape_dt, render=situation in ("twin", "real_a"))
        runs[situation] = result["rows"]
        for cam, frames in result["frames"].items():
            if not frames:
                continue
            label = "SIM TWIN" if situation == "twin" else "SYNTHETIC REAL (perturbed sim stand-in)"
            # WHY real blue, sim orange (Zach, 2026-10-28; the dashboards' one rule): the stand-in plays the real device, so it
            # wears real's blue; white text clears 5:1 on both. Red and green are pass/fail only.
            colour = "0xb04a0e" if situation == "twin" else "0x1f5fbf"
            encode(frames, MEDIA / f"{cam}_{situation}.mp4", label, colour)
            print(f"{cam}_{situation}.mp4: {len(frames)} frames")
        print(situation, len(result["rows"]), "rows")
    for row, target in zip(runs["twin"], tool_targets(runs["twin"])):
        row["tool_target"] = target
    runs["twin_x20"] = exaggerated_twin(runs["twin"], runs["real_a"])
    document = {
        "schema": "sim2real.arm_suite_sim/1",
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "basis": "SIMULATION ONLY. twin = Menagerie UR5e + tool; real_a / real_b = the same model with the perturbations "
                 "below and sensor noise: a synthetic stand-in for a real arm, never measured.",
        "model": str(UR5E), "tape": f"{TAPE} tapes[0] (coordinated), target only", "mujoco": mujoco.__version__,
        "perturbations": PERTURBATIONS, "noise_sigma": NOISE, "repeat_friction_scale": REPEAT_FRICTION_SCALE,
        "repeat_command_delay_s": REPEAT_COMMAND_DELAY_S,
        "joints": JOINTS, "links": LINKS, "error_scale_twin_x20": ERROR_SCALE, "record_dt_s": RECORD_DT, "fps": FPS, "width": WIDTH, "height": HEIGHT,
        "points": ["tcp"] + [name for name, _, _ in BLOCKS],
        "runs": json_safe(runs),
    }
    OUT.write_text(json.dumps(document, separators=(",", ":"), allow_nan=False))
    print(OUT, OUT.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
