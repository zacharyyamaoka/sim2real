"""Two UR5e + 2F-85 on a humanoid torso, a head camera on the belt: the deployment calibration (where each arm really is, and the
camera's lens and pose), from tags on the grippers and on the belt.

The arms come calibrated from the bench (the UR5e + 2F-85 example); the belt's travel comes from its calibrated encoder (the conveyor
example). The real pixels are bam_scan_tunnel's PinholeCamera.project at world.json's hidden intrinsics and camera pose, of the
tag corners where the hidden mounts put them; identification is one bundle adjustment of 22 numbers (two mount corrections, the
camera's correction and K) on reprojection error, from the description's drawing. Held-out: reprojection error on other poses and
belt positions, and the error of a belt point the camera sees, expressed in each arm's base frame: what a pick from the belt uses.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field

import numpy as np

from sysid import camera as cam
from sysid import cards, result
from sysid import world as hidden

EXAMPLE = "dual_arm_cell"
ARMS = ("left", "right")
CAMERA = "head_camera"
FRAMES = ("left_mount", "right_mount", CAMERA)
PARAMS = tuple(f"{f}.{n}" for f in FRAMES for n in cam.POSE_NAMES) + tuple(f"{CAMERA}.{n}" for n in cam.K_NAMES)
# WHY this wide: with the arm's base axis pointing outward (the humanoid mount) the reach toward the head camera is no single
# region; about 0.7 % of these show the gripper tag to the camera (measured 2026-11-05), so the plan rejection-samples them
POSE_RANGE = ((-3.14, 3.14), (-3.14, 0.0), (-2.6, 2.6), (-3.14, 3.14), (-3.14, 3.14), (-3.14, 3.14))
BELT_Z = 0.72


def rng_for(seed: int, *names) -> np.random.Generator:
    return np.random.default_rng([seed, *(zlib.crc32(str(n).encode()) for n in names)])


def quat_to_mat(q) -> np.ndarray:
    import mujoco  # noqa: PLC0415

    out = np.zeros(9)
    mujoco.mju_quat2Mat(out, np.asarray(q, float))
    return out.reshape(3, 3)


def mat_to_quat(R) -> np.ndarray:
    import mujoco  # noqa: PLC0415

    out = np.zeros(4)
    mujoco.mju_mat2Quat(out, np.asarray(R, float).ravel())
    return out


class Cell:
    """The composed cell, its drawn poses, and the tags' geometry."""

    def __init__(self, description):
        import mujoco  # noqa: PLC0415

        self.description = description
        self.model = description.spec().compile()
        self.data = mujoco.MjData(self.model)
        mujoco.mj_forward(self.model, self.data)
        m = self.model
        self.base = {a: m.body(f"{a}_base").id for a in ARMS}
        self.grip = {a: m.body(f"{a}_grip_base").id for a in ARMS}
        self.qpos = {a: m.jnt_qposadr[[m.joint(f"{a}_{j}_joint").id for j in ("shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3")]] for a in ARMS}
        self.drawn = {f"{a}_mount": (quat_to_mat(m.body_quat[self.base[a]]), m.body_pos[self.base[a]].copy()) for a in ARMS}
        self.drawn[CAMERA] = cam.mujoco_pose(m, self.data, CAMERA)
        c = description.cameras[CAMERA]
        self.K = {"fx_px": c.fx, "fy_px": c.fy, "cx_px": c.cx, "cy_px": c.cy}
        self.size = c.resolution
        known = description.known
        tag = known["gripper_tag"]
        self.grip_corners = cam.tag_corners(tag["size_m"]) + np.asarray(tag["offset_m"])
        self.belt_tags = np.asarray(known["belt_tags"]["positions_m"], float)
        self.belt_tag_size = float(known["belt_tags"]["size_m"])
        # the conveyor's drawn frame (its part pose): belt x along travel, belt y across, surface at BELT_Z
        part = next(p for p in description.manifest["model"]["parts"] if p["id"] == "conveyor")
        yaw = part["rpy"][2]
        self.conveyor_R = np.array([[math.cos(yaw), -math.sin(yaw), 0.0], [math.sin(yaw), math.cos(yaw), 0.0], [0.0, 0.0, 1.0]])
        self.conveyor_p = np.asarray(part["pos"], float)

    def frame(self, values: dict, name: str) -> tuple[np.ndarray, np.ndarray]:
        R, t = self.drawn[name]
        d, r = cam.correction_of(values, name)
        return cam.corrected(R, t, d, r)

    def pinhole(self, values: dict) -> cam.Pinhole:
        R, t = self.frame(values, CAMERA)
        k = {n: float(values.get(f"{CAMERA}.{n}", self.K[n])) for n in cam.K_NAMES}
        return cam.Pinhole(k["fx_px"], k["fy_px"], k["cx_px"], k["cy_px"], R, t, int(self.size[0]), int(self.size[1]))

    def gripper_tag_in_base(self, arm: str, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The gripper tag's corners and normal in the arm's base frame at joint angles q (the bench-calibrated arm's FK)."""
        import mujoco  # noqa: PLC0415

        d = self.data
        d.qpos[:] = 0.0
        d.qpos[self.qpos[arm]] = q
        mujoco.mj_kinematics(self.model, d)
        Rg, pg = d.xmat[self.grip[arm]].reshape(3, 3), d.xpos[self.grip[arm]]
        Rb, pb = d.xmat[self.base[arm]].reshape(3, 3), d.xpos[self.base[arm]]
        world = self.grip_corners @ Rg.T + pg
        return (world - pb) @ Rb, Rb.T @ (Rg @ np.array([1.0, 0.0, 0.0]))

    def to_world(self, values: dict, arm: str, points_base: np.ndarray) -> np.ndarray:
        R, t = self.frame(values, f"{arm}_mount")
        return points_base @ R.T + t

    def belt_tag_world(self, travel: float) -> list[np.ndarray]:
        """Corners (world) of every belt tag on the top run at belt travel `travel` (m)."""
        h = self.belt_tag_size / 2.0
        out = []
        for x, y in self.belt_tags:
            xb = x + travel
            if abs(xb) > 0.75:
                continue
            local = np.array([[xb - h, y - h, BELT_Z], [xb + h, y - h, BELT_Z], [xb + h, y + h, BELT_Z], [xb - h, y + h, BELT_Z]])
            out.append(local @ self.conveyor_R.T + np.array([self.conveyor_p[0], self.conveyor_p[1], 0.0]) + np.array([0.0, 0.0, 0.0005]))
        return out


# --- plan --------------------------------------------------------------------------------------------------------------------

@dataclass
class Plan:
    poses: dict           # (arm, split) -> list of joint vectors
    belt: dict            # split -> list of belt travels
    picks: list           # held-out belt points (belt frame x, y, travel)
    coverage: dict = field(default_factory=dict)


def plan(description) -> Plan:
    """Arm poses that show the gripper tag to the drawn camera, belt travels that bring the belt tags under it, held-out picks."""
    cell = Cell(description)
    s = description.schedule
    nominal = {k: v.value for k, v in description.nominal.items()}
    pin = cell.pinhole(nominal)
    lo, hi = np.array(POSE_RANGE).T
    poses = {}
    for arm in ARMS:
        rng = rng_for(s["seed"], "poses", arm)
        found = []
        for _ in range(60000):
            q = rng.uniform(lo, hi)
            corners, normal = cell.gripper_tag_in_base(arm, q)
            world = cell.to_world(nominal, arm, corners)
            px, depth = pin.project(world)
            R, _ = cell.frame(nominal, f"{arm}_mount")
            facing = float((R @ normal) @ (pin.t - world.mean(axis=0))) / np.linalg.norm(pin.t - world.mean(axis=0))
            if pin.visible(px, depth, margin=40.0).all() and facing > 0.35:
                found.append(q)
            if len(found) == s["arm_poses_train"] + s["arm_poses_held_out"]:
                break
        poses[(arm, "train")], poses[(arm, "held_out")] = found[: s["arm_poses_train"]], found[s["arm_poses_train"]:]
    rng = rng_for(s["seed"], "belt")
    belt = {"train": list(rng.uniform(-0.45, 0.45, s["belt_positions_train"])), "held_out": list(rng.uniform(-0.45, 0.45, s["belt_positions_held_out"]))}
    rng = rng_for(s["seed"], "picks")
    picks = [(float(x), float(y), 0.0) for x, y in zip(rng.uniform(-0.35, 0.35, 40), rng.uniform(-0.22, 0.22, 40))]
    p = Plan(poses, belt, picks)
    p.coverage = coverage(cell, nominal, p)
    return p


IMAGE_CELLS = (8, 6)


def coverage(cell: Cell, nominal: dict, p: Plan) -> dict:
    """Where the planned corners land in the image (an 8 x 6 grid of cells) and how far away (3 depth bands): the calibration's own
    coverage (sysid adapter), with the camera card's scene-condition rule named beside it (distance and incidence planned, the rest not)."""
    pin = cell.pinhole(nominal)
    out = {}
    for split in ("train", "held_out"):
        pts = []
        for arm in ARMS:
            for q in p.poses[(arm, split)]:
                pts.append(cell.to_world(nominal, arm, cell.gripper_tag_in_base(arm, q)[0]))
        for travel in p.belt[split]:
            pts.extend(cell.belt_tag_world(travel))
        world = np.vstack(pts) if pts else np.zeros((0, 3))
        px, depth = pin.project(world)
        ok = pin.visible(px, depth)
        gx = np.clip((px[ok, 0] / cell.size[0] * IMAGE_CELLS[0]).astype(int), 0, IMAGE_CELLS[0] - 1)
        gy = np.clip((px[ok, 1] / cell.size[1] * IMAGE_CELLS[1]).astype(int), 0, IMAGE_CELLS[1] - 1)
        band = np.digitize(depth[ok], (0.8, 1.1))
        cells = {(int(a), int(b), int(c)) for a, b, c in zip(gx, gy, band)}
        total = IMAGE_CELLS[0] * IMAGE_CELLS[1] * 3
        image_cells = {(int(a), int(b)) for a, b in zip(gx, gy)}
        out[split] = {"pct": round(100.0 * len(cells) / total, 2), "visited": len(cells), "reachable": total, "samples": int(ok.sum()),
                      "axes": {"image cells (8 x 6)": round(100.0 * len(image_cells) / (IMAGE_CELLS[0] * IMAGE_CELLS[1]), 2)},
                      "unplanned": ["illumination", "material", "exposure"]}
    out["function"] = "sysid adapter: the corners' image cells (8 x 6) x depth bands (< 0.8, 0.8-1.1, > 1.1 m)"
    out["rule"] = "share of the 144 (image cell, depth band) cells the planned tag corners fall in; the camera card's scene conditions other than distance are not planned"
    return out


# --- the real cell ------------------------------------------------------------------------------------------------------------

@dataclass
class Observation:
    kind: str                # gripper | belt
    arm: str | None
    points: np.ndarray       # gripper: corners in the arm's base frame; belt: corners in world
    pixels: np.ndarray       # measured (n, 2)
    split: str


@dataclass
class Measured:
    train: list
    held_out: list
    picks: list              # (pixel measured, true point in each arm's true base frame)


class RealWorld:
    def __init__(self, description, *, workers: int = 6):
        self.description = description
        doc = hidden.load(EXAMPLE)
        self.truth, self.noise, self.seed = doc["truth"], doc["noise"], doc["seed"]
        self.drift = doc.get("drift", {})
        self.cell = Cell(description)

    def camera(self, extra: dict | None = None) -> cam.Pinhole:
        values = dict(self.truth)
        if extra:
            R, t = self.cell.frame(values, CAMERA)
            R2, t2 = cam.corrected(R, t, [extra[n] for n in cam.POSE_NAMES[:3]], [extra[n] for n in cam.POSE_NAMES[3:]])
            pin = self.cell.pinhole(values)
            return cam.Pinhole(pin.fx, pin.fy, pin.cx, pin.cy, R2, t2, pin.width, pin.height)
        return self.cell.pinhole(values)

    def observe(self, pin: cam.Pinhole, world: np.ndarray, rng) -> tuple[np.ndarray, np.ndarray]:
        """Pixels of world points through the stock projector (bam_scan_tunnel PinholeCamera.project), the visible ones, with noise."""
        stock = pin.stock()
        px = np.array([stock.project(p)[:2] for p in world])
        depth = pin.camera_points(world)[:, 2]
        ok = pin.visible(px, depth)
        return px + rng.normal(0.0, self.noise["pixel_px"], px.shape), ok

    def measure(self, p: Plan, *, camera_shift: dict | None = None, label: str = "") -> Measured:
        pin = self.camera(camera_shift)
        out = {"train": [], "held_out": []}
        for split in out:
            for arm in ARMS:
                for k, q in enumerate(p.poses[(arm, split)]):
                    corners, _ = self.cell.gripper_tag_in_base(arm, q)
                    px, ok = self.observe(pin, self.cell.to_world(self.truth, arm, corners), rng_for(self.seed, label, split, arm, k))
                    if ok.all():
                        out[split].append(Observation("gripper", arm, corners, px, split))
            for k, travel in enumerate(p.belt[split]):
                for j, corners in enumerate(self.cell.belt_tag_world(travel)):
                    px, ok = self.observe(pin, corners, rng_for(self.seed, label, split, "belt", k, j))
                    if ok.all():
                        out[split].append(Observation("belt", None, corners, px, split))
        picks = []
        for k, (x, y, travel) in enumerate(p.picks):
            world = (np.array([x + travel, y, BELT_Z]) @ self.cell.conveyor_R.T) + np.array([self.cell.conveyor_p[0], self.cell.conveyor_p[1], 0.0])
            px, ok = self.observe(pin, world[None, :], rng_for(self.seed, label, "pick", k))
            if not ok.all():
                continue
            in_bases = {}
            for arm in ARMS:
                R, t = self.cell.frame(self.truth, f"{arm}_mount")
                in_bases[arm] = R.T @ (world - t)
            picks.append((px[0], in_bases))
        return Measured(out["train"], out["held_out"], picks)


# --- identification ---------------------------------------------------------------------------------------------------------

@dataclass
class Fit:
    values: dict
    ci95: dict
    methods: dict
    rms_px: float


def predict(cell: Cell, values: dict, observations: list) -> np.ndarray:
    pin = cell.pinhole(values)
    out = []
    for o in observations:
        world = cell.to_world(values, o.arm, o.points) if o.kind == "gripper" else o.points
        out.append(pin.project(world)[0])
    return np.vstack(out) if out else np.zeros((0, 2))


def identify(description, observations: list, *, only: tuple[str, ...] | None = None, start: dict | None = None) -> Fit:
    """Bundle adjustment from the description's drawing (or `start`): every tag corner's reprojection error over the parameters in
    `only` (default: both mounts, the camera's pose and K)."""
    cell = Cell(description)
    base = {k: v.value for k, v in description.nominal.items()} if start is None else dict(start)
    names = PARAMS if only is None else only
    measured = np.vstack([o.pixels for o in observations])
    cam.check_against_stock(cell.pinhole(base), np.vstack([o.points for o in observations if o.kind == "belt"][:5]))

    def residual(x):
        values = {**base, **dict(zip(names, x))}
        return (predict(cell, values, observations) - measured).ravel()

    x0 = np.array([base[n] for n in names])
    scale = np.array([1.0 if n.endswith("_px") else 0.01 for n in names])
    x, ci, fit = cam.least_squares_with_ci(residual, x0, scale, names=names)
    values = {**base, **dict(zip(names, map(float, x)))}
    return Fit({n: values[n] for n in names}, ci, {"bundle": f"Levenberg-Marquardt on {measured.shape[0]:,} corner pixels "
                                                             f"({sum(o.kind == 'gripper' for o in observations)} gripper views, {sum(o.kind == 'belt' for o in observations)} belt tags), "
                                                             f"{len(names)} parameters; 95 % from the Jacobian"},
               cam.rms(fit.fun))


# --- held-out score ---------------------------------------------------------------------------------------------------------

def pick_errors(cell: Cell, values: dict, picks: list) -> np.ndarray:
    """|twin - true| of each seen belt point in each arm's base frame: the pixel back-projected onto the belt plane, then through
    the twin's mount."""
    pin = cell.pinhole(values)
    errs = []
    for px, in_bases in picks:
        ray = pin.ray(px[None, :])[0]
        s = (BELT_Z - pin.t[2]) / ray[2]
        world = pin.t + s * ray
        for arm in ARMS:
            R, t = cell.frame(values, f"{arm}_mount")
            errs.append(np.linalg.norm(R.T @ (world - t) - in_bases[arm]))
    return np.array(errs)


def score(description, p: Plan, fit: Fit, measured: Measured, *, workers: int = 6) -> dict:
    cell = Cell(description)
    nominal = {k: v.value for k, v in description.nominal.items()}
    after = {**nominal, **fit.values}
    out = {"models": {}}
    held = measured.held_out
    meas = np.vstack([o.pixels for o in held])
    for label, values in (("nominal", nominal), ("fitted", after)):
        out["models"][label] = {"reprojection_px": cam.rms(predict(cell, values, held) - meas),
                                "pick_mm": 1e3 * cam.rms(pick_errors(cell, values, measured.picks))}
    out["picks"] = len(measured.picks)
    out["views"] = {"train": len(measured.train), "held_out": len(held)}
    return out


def assemble(description, p: Plan, fit: Fit, scores: dict, *, truth: dict) -> dict:
    recovered = {k: {"value": v, "ci95": fit.ci95[k], "rung": "bundle adjustment", "method": fit.methods["bundle"]} for k, v in fit.values.items()}
    m = scores["models"]
    md = description.manifest["model"]
    return {
        "title": description.manifest["title"], "subtitle": description.manifest.get("subtitle", ""), "summary": description.manifest.get("summary", ""),
        "description": {"manifest": f"sysid/examples/{EXAMPLE}/description.json", "model": {"format": md["format"], "source": md["source"],
                        "parts": [{"id": pt["id"], "path": pt["path"], "prefix": pt["prefix"]} for pt in md["parts"]], "cameras": md.get("cameras", [])},
                        "sensors": description.manifest.get("sensors", []), "known": description.known, "components": len(description.components)},
        "tree": description.tree(),
        "schedule": {"train": {"views": scores["views"]["train"], "arm_poses": sum(len(p.poses[(a, "train")]) for a in ARMS), "belt_travels": len(p.belt["train"])},
                     "held_out": {"views": scores["views"]["held_out"], "arm_poses": sum(len(p.poses[(a, "held_out")]) for a in ARMS), "belt_travels": len(p.belt["held_out"]),
                                  "picks": scores["picks"]},
                     "coverage": p.coverage},
        "parameters": result.parameter_rows(EXAMPLE, description, truth, recovered),
        "metrics": [result.metric(EXAMPLE, "held_out_reprojection_px", "Tag corners, twin vs detected (held-out views)", "px",
                                  m["nominal"]["reprojection_px"], m["fitted"]["reprojection_px"], after_model="fitted", note="corner detection noise 0.3 px is the floor"),
                    result.metric(EXAMPLE, "held_out_pick_point_mm", "A belt point the camera sees, in each arm's base frame", "mm",
                                  m["nominal"]["pick_mm"], m["fitted"]["pick_mm"], after_model="fitted", note=f"{scores['picks']} held-out belt points x 2 arms")],
        "models": [{"model": label, **row} for label, row in m.items()], "card_ladders": cards.card_ladders(EXAMPLE, fit.values), "selected_rung": None,
        "fit": {"train_rms_px": fit.rms_px},
        "notes": ["The arms' joint zeros and TCPs are the bench calibration's (the UR5e + 2F-85 example); the belt's travel is the conveyor example's.",
                  "The pixels are tag-corner detections simulated as projections plus 0.3 px noise, not rendered images (no detector in the loop)."],
    }
