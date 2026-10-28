"""sim2real dashboard proposals: five page designs x three scales, every page a data-ui `.base` dashboard.

    python3 -I /home/bam/sim2real/dashboards/build.py

Zach (2026-10-27): "make 5 orthogonal dashboard proposals using data-ui for doing Sim to real ... the 1 dof case, a full
6 dof robot case, and even one with like cameras and full sensor suite ... slice this by sensor/actuator ... derived or
higher order things ... like eef position ... a standard dashboard for each type ... a cool home page could be the 3D
view ... and the camera streams ... wipe any of them sim to real ... at a glance you can quickly see if its calibrated".

Stdlib only. Reads (never writes) its inputs, and writes `dashboards/<scale>/` (the datasets and one `.base` per
proposal) and `dashboards/proposals.json` (what the switcher lists):

  rack  (1-DOF, REAL): /archive/datasets/bam_rig/rack_2026-10-24/analysis/acceptance.json (gates T1-T11, floors, twin
        error), source/rack_replays.json (one held-out run per motor, real vs its station twin, replayed by
        bam_rack_twin; the replay reproduces the file's RMS exactly), and data-ui's own sim-to-real case (vendored):
        CAN 14's 10-23 staircase against the 10-23 twin, and its real RealSense clip.
  arm   (6-DOF, SIM STAND-IN) and suite (6-DOF + cameras, IMU, F/T, SIM STAND-IN): source/arm_suite_sim.json and
        source/media/, written by source/arm_suite_sim.py (MuJoCo UR5e; "real" = the same model with four declared
        perturbations and sensor noise). No real UR5e run and no real sensor suite exist; every number from them carries
        basis "stand-in" and every page says so in its first line.

The ruler everywhere (Zach's, the README): one stimulus on the real device and on its twin, an error metric, divided by
the real device's own run-to-run floor; <= 1.5x is twinned.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
VENDOR = REPO / "vendor" / "data-ui"
sys.dont_write_bytecode = True  # WHY: importing the vendored reader must not leave __pycache__ inside vendor/
sys.path.insert(0, str(VENDOR / "dist" / "python"))
import data_ui_base  # noqa: E402  (the vendored stdlib .base reader/writer: data-ui's own house style)

ARCHIVE = pathlib.Path("/archive/datasets/bam_rig")
ACCEPTANCE = ARCHIVE / "rack_2026-10-24" / "analysis" / "acceptance.json"
RACK_REPLAYS = HERE / "source" / "rack_replays.json"
ARM_SIM = HERE / "source" / "arm_suite_sim.json"
SIM_MEDIA = HERE / "source" / "media"
DUI_S2R = VENDOR / "gallery" / "sim-to-real"
GLB = "../../vendor/data-ui/gallery/pid-tuning/media/ur5e_links.glb"  # relative to a scale folder's data files

GATE = 1.5  # twinned when sim-vs-real error <= 1.5x the device's own floor (acceptance.py FIDELITY_TAPES)
TORQUE_GATE = 2.0  # acceptance.py T3: torque within 2x the run-to-run floor
TOOL_GATE_MM = 5.0  # Zach 2024-04-09: "within 5mm should be ok for grasping"; the only number he put on the arm gate
ERROR_SCALE = 20  # the 3D card draws the twin's error against the real device this many times larger (labelled)
DISPLAY_EVERY = 2  # rack runs are logged at 91-95 Hz; every 2nd row (~47 Hz) is plenty for a time series card
PALETTE = {"target": "#8b9099", "real": "#2a78d6", "twin": "#e8743b", "real B": "#8fb8ea", f"twin ×{ERROR_SCALE}": "#e8743b",
           "floor": "#9aa0a6", "floor −": "#9aa0a6"}
TONES = {"pass": "good", "fail": "bad", "partial": "warn", "not_run": "muted"}

# acceptance.py's K2 allocation (agent default, "Zach to confirm"): shoulder 2 mm at 0.55 m, elbow 2 mm at 0.3 m, wrist
# 1 mm at 0.1 m, about 3 mm root-sum-square inside the 5 mm tool gate
CLASS_OF = {11: "shoulder", 12: "shoulder", 13: "shoulder", 4: "elbow", 21: "elbow", 1: "wrist", 14: "wrist", 15: "wrist"}
SHARE_MM = {"shoulder": 2.0, "elbow": 2.0, "wrist": 1.0}
LEVER_M = {"shoulder": 0.55, "elbow": 0.30, "wrist": 0.10}
RACK_ORDER = [14, 15, 1, 4, 21, 11, 12, 13]  # wrist, elbow, shoulder: the KPI report's order


# ---------------------------------------------------------------------------------------------------- small helpers


def rich(value, basis, unit=None, source=None, n=None, note=None, why=None):
    """A data-ui rich cell: the number with its basis badge, unit and provenance one hover away."""

    cell = {"value": value, "basis": basis}
    for key, item in (("unit", unit), ("source", source), ("n", n), ("note", note), ("why", why)):
        if item is not None:
            cell[key] = item
    return cell


def rms(values):
    values = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else None


def percentile(values, fraction):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    position = fraction * (len(values) - 1)
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def r(value, digits=4):
    return None if value is None else round(value, digits)


def infer_type(values) -> str:
    for value in values:
        if isinstance(value, dict):
            return "number" if isinstance(value.get("value"), (int, float)) or value.get("value") is None else "text"
        if isinstance(value, bool):
            return "checkbox"
        if isinstance(value, (int, float)):
            return "number"
        if value is not None:
            return "text"
    return "text"


def write_dataset(folder: pathlib.Path, name: str, title: str, source: str, properties: dict, rows: list[dict], **extra):
    # WHY every column declared: data-ui's checker (and the views' menus) read a file's columns from `properties`
    columns = {}
    for row in rows:
        for key, value in row.items():
            columns.setdefault(key, []).append(value)
    properties = {key: {"type": infer_type(values), **properties.get(key, {})} for key, values in columns.items()}
    document = {"id": f"sim2real-{folder.name}-{name.removesuffix('.json')}", "title": title, "source": source,
                "properties": properties, **extra, "rows": rows}
    (folder / name).write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return len(rows)


# ---------------------------------------------------------------------------------------------------- the rack (real)


def rack_scale() -> dict:
    acceptance = json.loads(ACCEPTANCE.read_text())
    replays = {run["can"]: run for run in json.loads(RACK_REPLAYS.read_text())["runs"]}
    motors_meta = {row["can"]: row for row in json.loads((DUI_S2R / "motors.json").read_text())["rows"]}
    acc_source = f"{ACCEPTANCE} (generated {acceptance['generated_at']})"
    devices, gates, budget, runs = [], [], [], []
    servo_rows, scene_rows = [], []

    for order, can in enumerate(RACK_ORDER):
        station = acceptance["stations"][str(can)]
        facts = {**station["facts"]}
        by_id = {gate["id"]: gate for gate in station["gates"]}
        motor = f"CAN {can}"
        joint_class = CLASS_OF[can]
        floor = facts["floor"]["mrad"]
        twin = facts["twin_mrad"]
        ratio = by_id["T2"]["value"]
        stop_p90 = by_id["T4"]["value"]
        meta = motors_meta.get(can, {})
        devices.append({
            "device": motor, "label": f"{motor} · {joint_class}", "type": "servo", "type_title": "Servo (actuator + encoder)",
            "parent": "One Dof Test Rack", "order": order, "role": "actuator", "class": joint_class,
            "part": meta.get("part"), "board": meta.get("board"),
            "metric": "angle RMS, twin vs real, held-out runs (median)",
            "sim_vs_real": rich(twin, "measured", "mrad", f"{acc_source}: stations.{can}.facts.twin_mrad", note=facts.get("dataset_source")),
            "floor": rich(floor, "measured", "mrad", f"stations.{can}.facts.floor ({facts['floor']['repeats']} identical repeats)"),
            "ratio": rich(ratio, "derived", "×", f"gate T2 value: twin ÷ floor; T2 {by_id['T2']['status']} ({by_id['T2']['detail']})"),
            "gate": GATE,
            # WHY a second number: T2 also needs every dataset class within 2x, so CAN 4 (1.37x on its tapes, 3.14x on
            # its cycles) fails with a ratio under 1.5; the badge shows the clause that binds, so green means pass
            "gate_used": rich(r(max(ratio / GATE, max(facts["class_ratio"].values()) / 2.0), 3), "derived", "of gate",
                              f"max(tapes {ratio:.2f}/{GATE}, worst class {max(facts['class_ratio'].values()):.2f}/2.0): T2 passes at <= 1"),
            "gate_limit": 1,
            "torque_ratio": rich(by_id["T3"]["value"], "derived", "×", "gate T3: torque from current vs twin, ÷ run-to-run") if by_id["T3"]["value"] is not None else None,
            "real_vs_target": rich(stop_p90, "measured", "mrad", "gate T4: stop error p90, encoder side", note=by_id["T4"]["detail"]),
            "verdict": "twinned" if by_id["T2"]["status"] == "pass" else "not twinned",
            "twinned": 1 if by_id["T2"]["status"] == "pass" else 0,
            "basis": "real",
            "note": f"{joint_class} class: stop share {SHARE_MM[joint_class] / LEVER_M[joint_class]:.1f} mrad "
                    f"({SHARE_MM[joint_class]} mm at {LEVER_M[joint_class]} m, agent default)",
        })
        for gate_order, gate in enumerate(station["gates"]):
            value = gate["value"]
            gates.append({
                "id": f"{motor}-{gate['id']}", "device": motor, "type": "servo", "class": joint_class,
                "gate": gate["id"], "gate_title": f"{gate['id']} {gate['name']}", "gate_name": gate["name"], "order": gate_order,
                "status": gate["status"], "passed": 1 if gate["status"] == "pass" else 0, "cell": 1,
                "value": value if isinstance(value, (int, float)) or value is None else str(value),
                "target": gate["target"], "detail": gate["detail"] or None,
                "evidence": f"{ACCEPTANCE}: stations.{can}.gates[{gate_order}]", "basis": "real",
            })
        replay = replays[can]
        samples = replay["samples"]
        run_path = pathlib.Path(replay["run_path"])
        day = run_path.parts[4].split("_")[1][5:]  # rack_2026-10-25 -> 10-25
        run_id = f"{motor} · {run_path.stem.split('_')[0]} · {day}"
        run_set = "8 motors · held-out waypoints"
        runs.append({
            "id": run_id, "parent": run_set, "run": run_id, "run_set": run_set, "label": run_id, "kind": replay["kind"],
            "device": motor, "date": day, "duration_s": r(replay["duration_s"], 2),
            "situations": "target · real · twin", "twin": replay["twin_version"], "basis": "real",
            "rms_q_mrad": rich(r(replay["rms_q_mrad"]), "measured", "mrad", "source/rack_replays.json (bam_rack_twin replay; equals the dataset_twin file)"),
            "source": replay["run_path"],
        })
        t = samples["t"]
        for k in range(0, len(t), DISPLAY_EVERY):
            q_target, q_real, q_twin = samples["q_target"][k], samples["q_real"][k], samples["q_twin"][k]
            base = {"t": r(t[k]), "run": run_id, "run_set": run_set, "device": motor, "type": "servo"}
            if q_target is not None:
                servo_rows.append({**base, "situation": "target", "q_deg": r(math.degrees(q_target))})
            servo_rows.append({**base, "situation": "real", "q_deg": r(math.degrees(q_real)) if q_real is not None else None,
                               "tau_nm": r(samples["tau_real"][k]),
                               **({"i_q_a": r(samples["i_q_real"][k])} if samples.get("i_q_real") else {}),
                               **({"temp_c": r(samples["temp_c_real"][k], 2)} if samples.get("temp_c_real") else {})})
            gap = (q_twin - q_real) * 1e3 if q_twin is not None and q_real is not None else None
            servo_rows.append({**base, "situation": "twin", "q_deg": r(math.degrees(q_twin)) if q_twin is not None else None,
                               "tau_nm": r(samples["tau_twin"][k]), "gap_mrad": r(gap, 3)})
        for edge in (t[0], t[-1]):  # the device's own floor as two flat lines on the gap card: data, so it varies per device
            servo_rows.append({"t": r(edge), "run": run_id, "run_set": run_set, "device": motor, "type": "servo", "situation": "floor", "gap_mrad": r(floor, 3)})
            servo_rows.append({"t": r(edge), "run": run_id, "run_set": run_set, "device": motor, "type": "servo", "situation": "floor −", "gap_mrad": r(-floor, 3)})

    # ---- CAN 14's 10-23 staircase: the one run with a real camera clip (data-ui's sim-to-real case, vendored)
    s2r = json.loads((DUI_S2R / "samples.json").read_text())
    staircase = "CAN 14 · s03 · 10-23"
    stair_set = "CAN 14 · staircase + real camera"
    can14_floor = acceptance["stations"]["14"]["facts"]["floor"]["mrad"]
    stair_rows = [row for row in s2r["rows"] if row["run"] == "staircase 10-23" and row["situation"] in ("target", "real", "sim_identified")]
    for row in stair_rows:
        situation = {"sim_identified": "twin"}.get(row["situation"], row["situation"])
        out = {"t": row["t"], "run": staircase, "run_set": stair_set, "device": "CAN 14", "type": "servo", "situation": situation, "q_deg": row["q_deg"]}
        if situation == "twin":
            out["gap_mrad"] = row.get("gap_mrad")
        servo_rows.append(out)
    stair_t = [row["t"] for row in stair_rows]
    for edge in (min(stair_t), max(stair_t)):
        servo_rows.append({"t": edge, "run": staircase, "run_set": stair_set, "device": "CAN 14", "type": "servo", "situation": "floor", "gap_mrad": r(can14_floor, 3)})
        servo_rows.append({"t": edge, "run": staircase, "run_set": stair_set, "device": "CAN 14", "type": "servo", "situation": "floor −", "gap_mrad": r(-can14_floor, 3)})
    runs.append({"id": staircase, "parent": stair_set, "run": staircase, "run_set": stair_set, "label": staircase, "kind": "staircase",
                 "device": "CAN 14", "date": "10-23", "duration_s": r(max(stair_t), 2), "situations": "target · real · twin (10-23 identified) · camera",
                 "twin": "identified-d58a5583 (the 10-23 twin, older than the station twin)", "basis": "real",
                 "source": s2r["runs"]["staircase 10-23"]})
    runs.insert(0, {"id": "8 motors · held-out waypoints", "parent": "One Dof Test Rack", "run": None, "run_set": "8 motors · held-out waypoints",
                    "label": "8 motors · held-out waypoints", "kind": "run set", "basis": "real",
                    "situations": "one held-out run per motor, each against its station twin"})
    runs.insert(len(runs) - 1, {"id": stair_set, "parent": "One Dof Test Rack", "run": None, "run_set": stair_set, "label": stair_set,
                                "kind": "run set", "basis": "real", "situations": "the only rack run with a usable camera clip"})
    runs.insert(0, {"id": "One Dof Test Rack", "parent": None, "run": None, "label": "One Dof Test Rack", "kind": "rig", "basis": "real",
                    "situations": "rack_2026-10-23 · 10-24 · 10-25"})

    # ---- the camera: a real device with no twin picture
    devices.append({
        "device": "RealSense 218622274411", "label": "RealSense 218622274411 (rack camera)", "type": "camera", "type_title": "Camera",
        "parent": "One Dof Test Rack", "order": 20, "role": "sensor",
        "metric": "reprojection of known points, twin render vs real frame",
        "sim_vs_real": rich(None, "measured", "px", why="no sim render of the rack exists: bam_rack_twin/render.py has never been run, and CAN 14's joint is not in the CAD export"),
        "floor": rich(None, "measured", "px", why="no repeat pair scored"), "ratio": rich(None, "derived", "×", why="no sim render"),
        "gate": GATE, "gate_used": rich(None, "derived", "of gate", why="no sim render"), "gate_limit": 1,
        "verdict": "no evidence", "twinned": 0, "basis": "real",
        "note": "Real footage of CAN 14 exists (10-21, 10-23); the twin side is missing, so it cannot be scored.",
    })
    gates.append({"id": "camera-C1", "device": "RealSense 218622274411", "type": "camera", "gate": "C1", "gate_title": "C1 reprojection",
                  "gate_name": "reprojection", "order": 0, "status": "not_run", "passed": 0, "cell": 1, "value": None,
                  "target": "<= 1.5x the real-vs-real repeat", "detail": "no sim render of the rack exists", "evidence": None, "basis": "real"})

    # ---- 3D: each motor a lever on a post, real solid, twin a ghost with its error drawn ERROR_SCALE times
    scene_rows = rack_scene(replays, stair_rows, staircase, stair_set)

    # ---- error budget: a virtual arm made of the rack's motor classes (agent default shares, Zach to confirm)
    budget = rack_budget(acceptance)

    caption = ("Real frame from CAN 14's 10-23 staircase (not the runs beside it). No sim render of the rack exists, "
               "so there is nothing to wipe it against yet.")
    media = [dict(row, device="RealSense 218622274411", run=staircase, run_set=stair_set, situation="real", device_of="CAN 14", caption=caption)
             for row in json.loads((DUI_S2R / "media.json").read_text())["rows"] if row["run"] == "staircase 10-23"]
    return {"devices": devices, "gates": gates, "servo": servo_rows, "scene": scene_rows, "budget": budget, "runs": runs,
            "media": media, "media_files": [DUI_S2R / row["src"] for row in media] + [DUI_S2R / row["poster"] for row in media]}


def lever_points(index: int, angle_rad: float | None) -> list[float | None]:
    """A motor's post (ground → axis) and lever tip, schematic positions along x (not the rack's CAD)."""

    x = (index - 3.5) * 0.16
    if angle_rad is None:
        return [x, 0.0, 0.0, x, 0.0, 0.25, None, None, None]
    return [x, 0.0, 0.0, x, 0.0, 0.25, x + 0.1 * math.sin(angle_rad), 0.0, 0.25 + 0.1 * math.cos(angle_rad)]


def interpolate(times: list[float], values: list[float | None], t: float) -> float | None:
    """Linear at t inside the run, None outside it (a run that ended is not held: truthful, never a plateau)."""

    if t < times[0] or t > times[-1]:
        return None
    low, high = 0, len(times) - 1
    while high - low > 1:
        mid = (low + high) // 2
        if times[mid] <= t:
            low = mid
        else:
            high = mid
    a, b = values[low], values[high]
    if a is None or b is None:
        return None
    span = times[high] - times[low]
    return a if span <= 0 else a + (b - a) * (t - times[low]) / span


def scene_columns(n_motors: int) -> list[list[str]]:
    skeleton = []
    for i in range(n_motors):
        skeleton += [[f"m{i}_bx", f"m{i}_by", f"m{i}_bz"], [f"m{i}_ax", f"m{i}_ay", f"m{i}_az"], [f"m{i}_tx", f"m{i}_ty", f"m{i}_tz"]]
        if i < n_motors - 1:
            skeleton.append(["gap_x", "gap_y", "gap_z"])  # WHY a null point: it hides the rod that would join two motors
    return skeleton


def rack_scene(replays: dict, stair_rows: list[dict], staircase: str, stair_set: str) -> list[dict]:
    rows = []
    duration = max(run["samples"]["t"][-1] for run in replays.values())
    steps = int(duration / 0.04) + 1
    for step in range(steps):
        t = round(step * 0.04, 3)
        for situation in ("real", f"twin ×{ERROR_SCALE}"):
            row = {"t": t, "run_set": "8 motors · held-out waypoints", "situation": situation, "gap_x": None, "gap_y": None, "gap_z": None}
            for index, can in enumerate(RACK_ORDER):
                samples = replays[can]["samples"]
                real = interpolate(samples["t"], samples["q_real"], t)
                twin = interpolate(samples["t"], samples["q_twin"], t)
                angle = real if situation == "real" else (None if real is None or twin is None else real + ERROR_SCALE * (twin - real))
                points = lever_points(index, angle)
                if real is None:
                    points = [None] * 9  # this motor's run has ended: draw nothing rather than a held pose
                for axis, value in zip(("bx", "by", "bz", "ax", "ay", "az", "tx", "ty", "tz"), points):
                    row[f"m{index}_{axis}"] = r(value, 5) if value is not None else None
            tip = (row["m0_tx"], row["m0_ty"], row["m0_tz"])
            row.update({"px": tip[0], "py": tip[1], "pz": tip[2]})  # the path: CAN 14's tip (the motor with a camera)
            rows.append(row)
    # the staircase: CAN 14 alone (index 0), the others absent
    by_time = {}
    for row in stair_rows:
        by_time.setdefault(row["t"], {})[row["situation"]] = math.radians(row["q_deg"])
    for t in sorted(by_time)[::2]:
        real, twin = by_time[t].get("real"), by_time[t].get("sim_identified")
        for situation in ("real", f"twin ×{ERROR_SCALE}"):
            angle = real if situation == "real" else (None if real is None or twin is None else real + ERROR_SCALE * (twin - real))
            row = {"t": t, "run_set": stair_set, "situation": situation, "gap_x": None, "gap_y": None, "gap_z": None}
            for index in range(len(RACK_ORDER)):
                points = lever_points(index, angle) if index == 0 else [None] * 9
                for axis, value in zip(("bx", "by", "bz", "ax", "ay", "az", "tx", "ty", "tz"), points):
                    row[f"m{index}_{axis}"] = r(value, 5) if value is not None else None
            row.update({"px": row["m0_tx"], "py": row["m0_ty"], "pz": row["m0_tz"]})
            rows.append(row)
    return rows


def rack_budget(acceptance: dict) -> list[dict]:
    """Tool error at a stop, decomposed by joint class into the rack's motors: each motor's angle error x the class
    lever arm, against the class share. Two errors per node (Zach, 2026-07-31): sim vs real (the twin) and real vs
    target (the stop). A class's number is its best-twinned motor: the one you would build the arm from."""

    rows = []
    class_best = {}
    for can in RACK_ORDER:
        station = acceptance["stations"][str(can)]
        joint_class = CLASS_OF[can]
        lever = LEVER_M[joint_class]
        twin_mm = station["facts"]["twin_mrad"] * lever
        stop = next(g for g in station["gates"] if g["id"] == "T4")["value"]
        stop_mm = stop * lever if stop is not None else None
        rows.append({
            "id": f"CAN {can}", "parent": joint_class, "label": f"CAN {can}", "kind": "motor", "order": 10 + RACK_ORDER.index(can),
            "lever_m": lever, "allocation_mm": rich(SHARE_MM[joint_class], "assumed", "mm", "acceptance.py STOP_ALLOCATION_MRAD (K2 default, Zach to confirm)"),
            "sim_vs_real_mm": rich(r(twin_mm, 3), "derived", "mm", f"twin {station['facts']['twin_mrad']:.2f} mrad x {lever} m"),
            "real_vs_target_mm": rich(r(stop_mm, 3), "derived", "mm", f"stop p90 {stop:.2f} mrad (encoder side) x {lever} m") if stop_mm is not None else None,
            "used": rich(r(twin_mm / SHARE_MM[joint_class], 3), "derived", "×"),
            "verdict": "inside share" if twin_mm <= SHARE_MM[joint_class] else "over share", "basis": "real",
        })
        best = class_best.get(joint_class)
        if best is None or twin_mm < best[1]:
            class_best[joint_class] = (f"CAN {can}", twin_mm, stop_mm)
    classes = []
    for order, joint_class in enumerate(("shoulder", "elbow", "wrist")):
        name, twin_mm, stop_mm = class_best[joint_class]
        classes.append((twin_mm, stop_mm))
        rows.append({
            "id": joint_class, "parent": "tool", "label": f"{joint_class.title()} joint · best: {name}", "kind": "joint class", "order": 2 + order,
            "lever_m": LEVER_M[joint_class], "allocation_mm": rich(SHARE_MM[joint_class], "assumed", "mm", "acceptance.py K2 default (Zach to confirm)"),
            "sim_vs_real_mm": rich(r(twin_mm, 3), "derived", "mm", f"{name}, the class's best-twinned motor"),
            "real_vs_target_mm": rich(r(stop_mm, 3), "derived", "mm", f"{name}'s stop p90 x lever") if stop_mm is not None else None,
            "used": rich(r(twin_mm / SHARE_MM[joint_class], 3), "derived", "×"),
            "verdict": "inside share" if twin_mm <= SHARE_MM[joint_class] else "over share", "basis": "real",
        })
    tool_twin = math.sqrt(sum(c[0] ** 2 for c in classes))
    tool_stop = math.sqrt(sum((c[1] or 0) ** 2 for c in classes))
    rows.insert(0, {
        "id": "tool", "parent": None, "label": "Tool at a stop (virtual arm from rack motors)", "kind": "tool", "order": 1,
        "allocation_mm": rich(TOOL_GATE_MM, "chosen", "mm", "Zach 2024-04-09: within 5 mm should be ok for grasping"),
        "sim_vs_real_mm": rich(r(tool_twin, 3), "derived", "mm", "root-sum-square of the three classes (independent errors)"),
        "real_vs_target_mm": rich(r(tool_stop, 3), "derived", "mm", "root-sum-square of the classes' stop p90 x lever"),
        "used": rich(r(tool_twin / TOOL_GATE_MM, 3), "derived", "×"),
        "verdict": "inside share" if tool_twin <= TOOL_GATE_MM else "over share", "basis": "real",
        "note": "There is no real arm: one rack motor per class stands for its joint, levers are acceptance.py's defaults.",
    })
    return sorted(rows, key=lambda row: row["order"])


# ------------------------------------------------------------------------------------ the arm and the suite (stand-in)

JOINT_NAMES = {"shoulder_pan_joint": "J1 shoulder pan", "shoulder_lift_joint": "J2 shoulder lift", "elbow_joint": "J3 elbow",
               "wrist_1_joint": "J4 wrist 1", "wrist_2_joint": "J5 wrist 2", "wrist_3_joint": "J6 wrist 3"}
JOINT_CLASS = ["shoulder", "shoulder", "elbow", "wrist", "wrist", "wrist"]
JOINT_AXIS = ["z", "y", "y", "y", "z", "y"]  # each joint's axis in its own link's frame (Menagerie ur5e.xml)
JOINT_LINK = ["shoulder_link", "upper_arm_link", "forearm_link", "wrist_1_link", "wrist_2_link", "wrist_3_link"]
ARM_RUN = "UR5e · coordinated tape (stand-in)"
STAND_IN_NOTE = "SIM STAND-IN: no real UR5e run exists. 'real' = the same MuJoCo model with declared perturbations and sensor noise."


def rotate(quat_wxyz, vector):
    w, x, y, z = quat_wxyz
    vx, vy, vz = vector
    # v' = v + 2w (q x v) + 2 q x (q x v), q = (x, y, z)
    cx, cy, cz = y * vz - z * vy, z * vx - x * vz, x * vy - y * vx
    ccx, ccy, ccz = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return (vx + 2 * (w * cx + ccx), vy + 2 * (w * cy + ccy), vz + 2 * (w * cz + ccz))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(v):
    return math.sqrt(sum(c * c for c in v))


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def arm_scale(with_suite: bool) -> dict:
    sim = json.loads(ARM_SIM.read_text())
    twin, real_a, real_b = sim["runs"]["twin"], sim["runs"]["real_a"], sim["runs"]["real_b"]
    joints = sim["joints"]
    source = f"source/arm_suite_sim.json ({sim['generated_at']}, MuJoCo {sim['mujoco']}): {sim['basis']}"
    perturbations = "; ".join(p["what"] for p in sim["perturbations"])
    devices, gates, runs = [], [], []
    samples = {"servo": [], "eef": [], "camera": [], "imu": [], "ft": []}
    stops = [k for k in range(1, len(twin)) if max(abs(a - b) for a, b in zip(twin[k]["q_target"], twin[k - 1]["q_target"])) < 1e-6]

    def series(run, key, index=None):
        return [row[key][index] if index is not None else row[key] for row in run]

    def add_device(device, type_, type_title, role, metric, err, floor, unit, order, parent, extra_gates, torque=None, real_vs_target=None, note=None):
        ratio = err / floor if err is not None and floor else None
        devices.append({
            "device": device, "label": device, "type": type_, "type_title": type_title, "parent": parent, "order": order, "role": role,
            "metric": metric, "sim_vs_real": rich(r(err, 5), "stand-in", unit, source), "floor": rich(r(floor, 5), "stand-in", unit, "real_a vs real_b (the stand-in run twice)"),
            "ratio": rich(r(ratio, 3), "derived", "×", "sim_vs_real ÷ floor"), "gate": GATE,
            "gate_used": rich(r(ratio / GATE, 3) if ratio is not None else None, "derived", "of gate", f"ratio / {GATE}: passes at <= 1"),
            "gate_limit": 1,
            "torque_ratio": rich(r(torque, 3), "derived", "×") if torque is not None else None,
            "real_vs_target": real_vs_target, "verdict": "twinned" if ratio is not None and ratio <= GATE else "not twinned",
            "twinned": 1 if ratio is not None and ratio <= GATE else 0, "basis": "stand-in", "note": note or STAND_IN_NOTE,
        })
        for gate_order, (gate_id, name, value, target, ok, detail) in enumerate(extra_gates):
            status = "not_run" if value is None else ("pass" if ok else "fail")
            gates.append({"id": f"{device}-{gate_id}", "device": device, "type": type_, "gate": gate_id, "gate_title": f"{gate_id} {name}",
                          "gate_name": name, "order": gate_order, "status": status, "passed": 1 if status == "pass" else 0, "cell": 1,
                          "value": r(value, 4), "target": target, "detail": detail, "evidence": source, "basis": "stand-in"})

    # ---- servos: angle and torque, twin vs real_a, floor real_a vs real_b
    for j, joint in enumerate(joints):
        name = JOINT_NAMES[joint]
        q_twin, q_a, q_b = series(twin, "q", j), series(real_a, "q", j), series(real_b, "q", j)
        err = rms([a - b for a, b in zip(q_twin, q_a)]) * 1e3
        floor = rms([a - b for a, b in zip(q_a, q_b)]) * 1e3
        tau_err = rms([a - b for a, b in zip(series(twin, "tau", j), series(real_a, "tau", j))])
        tau_floor = rms([a - b for a, b in zip(series(real_a, "tau", j), series(real_b, "tau", j))])
        share_mrad = SHARE_MM[JOINT_CLASS[j]] / LEVER_M[JOINT_CLASS[j]]
        stop_p90 = percentile([abs(real_a[k]["q"][j] - real_a[k]["q_target"][j]) * 1e3 for k in stops], 0.9)
        add_device(name, "servo", "Servo (actuator + encoder)", "actuator", "angle RMS, twin vs real, whole tape", err, floor, "mrad", j, "UR5e (stand-in)", [
            ("S1", "floor", floor, "a run-to-run repeat exists", floor is not None, "real_a vs real_b"),
            ("S2", "angle fidelity", err / floor, f"<= {GATE}x floor", err / floor <= GATE, "twin vs real_a ÷ floor"),
            ("S3", "torque fidelity", tau_err / tau_floor, f"<= {TORQUE_GATE}x floor", tau_err / tau_floor <= TORQUE_GATE, "actuator torque, twin vs real_a ÷ floor"),
            ("S4", "stop accuracy", stop_p90, f"p90 <= {share_mrad:.1f} mrad (class share)", stop_p90 <= share_mrad, "real_a vs target at the tape's stops"),
        ], torque=tau_err / tau_floor, real_vs_target=rich(r(stop_p90, 3), "stand-in", "mrad", "p90 at stops vs target"))
        for k in range(0, len(twin), 2):
            base = {"t": twin[k]["t"], "run": ARM_RUN, "run_set": ARM_RUN, "device": name, "type": "servo"}
            samples["servo"].append({**base, "situation": "target", "q_deg": r(math.degrees(twin[k]["q_target"][j]))})
            samples["servo"].append({**base, "situation": "real", "q_deg": r(math.degrees(q_a[k])), "tau_nm": r(real_a[k]["tau"][j], 3)})
            samples["servo"].append({**base, "situation": "real B", "q_deg": r(math.degrees(q_b[k])), "tau_nm": r(real_b[k]["tau"][j], 3)})
            samples["servo"].append({**base, "situation": "twin", "q_deg": r(math.degrees(q_twin[k])), "tau_nm": r(twin[k]["tau"][j], 3),
                                     "gap_mrad": r((q_twin[k] - q_a[k]) * 1e3, 4)})
        for edge in (twin[0]["t"], twin[-1]["t"]):
            samples["servo"].append({"t": edge, "run": ARM_RUN, "run_set": ARM_RUN, "device": name, "type": "servo", "situation": "floor", "gap_mrad": r(floor, 4)})
            samples["servo"].append({"t": edge, "run": ARM_RUN, "run_set": ARM_RUN, "device": name, "type": "servo", "situation": "floor −", "gap_mrad": r(-floor, 4)})

    # ---- the tool (EEF), derived: "real" = an external tracker's measurement of the stand-in (a laser tracker, say)
    tool_twin, tool_a, tool_b = series(twin, "tool"), series(real_a, "tool"), series(real_b, "tool")
    tool_err = rms([norm(sub(a, b)) for a, b in zip(tool_twin, tool_a)]) * 1e3
    tool_floor = rms([norm(sub(a, b)) for a, b in zip(tool_a, tool_b)]) * 1e3
    tool_stop = percentile([norm(sub(real_a[k]["tool"], twin[k]["tool_target"])) * 1e3 for k in stops], 0.9)
    add_device("Tool (EEF)", "eef", "End effector (derived)", "derived", "tool position RMS, twin vs real (external tracker)", tool_err, tool_floor, "mm", 10,
               "UR5e (stand-in)", [
                   ("E1", "tool fidelity", tool_err / tool_floor, f"<= {GATE}x floor", tool_err / tool_floor <= GATE, "twin vs real_a tool ÷ floor"),
                   ("E2", "tool at a stop", tool_stop, f"p90 <= {TOOL_GATE_MM} mm (Zach's 2024 grasp number)", tool_stop <= TOOL_GATE_MM, "real_a vs FK of the target"),
               ], real_vs_target=rich(r(tool_stop, 3), "stand-in", "mm", "p90 at stops vs FK(target)"),
               note="Derived one level up: computed from all six joints. The stand-in's 'real' tool is its true position, as an external tracker would see it; FK of its encoders would hide J4's offset.")
    for k in range(0, len(twin), 2):
        base = {"t": twin[k]["t"], "run": ARM_RUN, "run_set": ARM_RUN, "device": "Tool (EEF)", "type": "eef"}
        target = twin[k]["tool_target"]
        for situation, position in (("target", target), ("real", tool_a[k]), ("real B", tool_b[k]), ("twin", tool_twin[k])):
            row = {**base, "situation": situation, "x_mm": r(position[0] * 1e3, 3), "y_mm": r(position[1] * 1e3, 3), "z_mm": r(position[2] * 1e3, 3)}
            if situation != "target":
                row["err_mm"] = r(norm(sub(position, target)) * 1e3, 4)
            if situation == "twin":
                row["gap_mm"] = r(norm(sub(position, tool_a[k])) * 1e3, 4)
            samples["eef"].append(row)
    for edge in (twin[0]["t"], twin[-1]["t"]):
        samples["eef"].append({"t": edge, "run": ARM_RUN, "run_set": ARM_RUN, "device": "Tool (EEF)", "type": "eef", "situation": "floor", "gap_mm": r(tool_floor, 4)})

    scene_rows = arm_scene(sim)
    media = []
    budget = arm_budget(sim, tool_err, tool_floor, with_suite)
    camera_mm = {}

    if with_suite:
        # ---- cameras: reprojection of the four table blocks (known points), twin render vs stand-in frame
        for order, (camera, name) in enumerate((("scene_cam", "Scene camera"), ("wrist_cam", "Wrist camera"))):
            def block_errors(run_x, run_y):
                out = []
                for row_x, row_y in zip(run_x, run_y):
                    pairs = [(p, q) for p, q in zip(row_x["pixels"][camera][1:], row_y["pixels"][camera][1:]) if p[0] is not None and q[0] is not None]
                    out.append(rms([math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in pairs]) if pairs else None)
                return out
            per_frame = block_errors(twin, real_a)
            per_frame_floor = block_errors(real_a, real_b)
            err, floor = rms(per_frame), rms(per_frame_floor)
            seen = sum(1 for v in per_frame if v is not None) / len(per_frame)
            add_device(name, "camera", "Camera", "sensor", "reprojection RMS of the four table blocks, twin render vs real frame", err, floor, "px", 20 + order,
                       "UR5e cell (stand-in)", [
                           ("C1", "reprojection", err / floor, f"<= {GATE}x floor", err / floor <= GATE, f"blocks in view {seen:.0%} of frames"),
                       ], note=("Fixed camera; the stand-in's is 7.8 mm and 0.4° off its calibrated pose." if camera == "scene_cam"
                                else "On the tool: it sees the arm's pose error too (J4's encoder-blind offset)."))
            for k in range(0, len(twin), 2):
                base = {"t": twin[k]["t"], "run": ARM_RUN, "run_set": ARM_RUN, "device": name, "type": "camera"}
                samples["camera"].append({**base, "situation": "twin", "reproj_px": r(per_frame[k], 3)})
                samples["camera"].append({**base, "situation": "real B", "reproj_px": r(per_frame_floor[k], 3)})
            for situation in ("twin", "real"):
                stem = f"{camera}_{'twin' if situation == 'twin' else 'real_a'}"
                media.append({"id": stem, "device": name, "run": ARM_RUN, "run_set": ARM_RUN, "situation": situation,
                              "src": f"media/{stem}.mp4", "poster": f"media/{stem}.jpg", "t0": 0.0, "fps": sim["fps"],
                              "duration": round(len(twin) * sim["record_dt_s"], 2), "width": sim["width"], "height": sim["height"],
                              "basis": "sim-render" if situation == "twin" else "illustrative",
                              "note": ("MuJoCo render of the twin." if situation == "twin" else
                                       "SYNTHETIC REAL: a MuJoCo render of the perturbed stand-in plant through the perturbed camera. Not footage.")
                              + " Frames are the first 100 Hz record at or after k/30 s (at most 10 ms late)."})
            camera_mm[name] = err
        # ---- wrist IMU and F/T
        for device, type_, title, keys, unit, order, gate_ids in (
            ("Wrist IMU", "imu", "IMU", ("accel", "gyro"), ("m/s²", "rad/s"), 30, ("I1", "I2")),
            ("Wrist F/T", "ft", "Force/torque sensor", ("force", "torque"), ("N", "N·m"), 31, ("F1", "F2")),
        ):
            primary, secondary = keys
            def vec_err(run_x, run_y, key):
                return rms([norm(sub(a[key], b[key])) for a, b in zip(run_x, run_y)])
            err, floor = vec_err(twin, real_a, primary), vec_err(real_a, real_b, primary)
            err2, floor2 = vec_err(twin, real_a, secondary), vec_err(real_a, real_b, secondary)
            add_device(device, type_, title, "sensor", f"{primary} vector RMS, twin vs real", err, floor, unit[0], order, "UR5e cell (stand-in)", [
                (gate_ids[0], primary, err / floor, f"<= {GATE}x floor", err / floor <= GATE, f"{primary} ({unit[0]}) ÷ floor"),
                (gate_ids[1], secondary, err2 / floor2, f"<= {GATE}x floor", err2 / floor2 <= GATE, f"{secondary} ({unit[1]}) ÷ floor"),
            ], note=("On the tool flange; motion is the same in both plants, so it should match." if type_ == "imu"
                     else "Between flange and tool: it weighs the payload the twin got wrong."))
            for k in range(0, len(twin), 2):
                base = {"t": twin[k]["t"], "run": ARM_RUN, "run_set": ARM_RUN, "device": device, "type": type_}
                for situation, run in (("real", real_a), ("real B", real_b), ("twin", twin)):
                    row = {**base, "situation": situation}
                    for key in keys:
                        for axis, value in zip("xyz", run[k][key]):
                            row[f"{key}_{axis}"] = r(value, 4)
                    if situation == "twin":
                        row[f"gap_{primary}"] = r(norm(sub(twin[k][primary], real_a[k][primary])), 4)
                    samples[type_].append(row)
        budget = arm_budget(sim, tool_err, tool_floor, with_suite, camera_mm)

    runs = [
        {"id": "UR5e (stand-in)", "parent": None, "run": None, "label": "UR5e cell (sim stand-in)" if with_suite else "UR5e (sim stand-in)",
         "kind": "rig", "basis": "stand-in", "situations": perturbations},
        {"id": ARM_RUN, "parent": "UR5e (stand-in)", "run": ARM_RUN, "run_set": ARM_RUN, "label": ARM_RUN, "kind": "run", "date": "sim",
         "duration_s": round(twin[-1]["t"], 2), "situations": "target · real (A) · real B (repeat) · twin", "twin": "Menagerie UR5e + 0.8 kg tool",
         "basis": "stand-in", "source": str(ARM_SIM)},
    ]
    return {"devices": devices, "gates": gates, "servo": samples["servo"], "eef": samples["eef"], "camera": samples["camera"],
            "imu": samples["imu"], "ft": samples["ft"], "scene": scene_rows, "budget": budget, "runs": runs, "media": media,
            "media_files": [SIM_MEDIA / pathlib.Path(m["src"]).name for m in media] + [SIM_MEDIA / pathlib.Path(m["poster"]).name for m in media],
            "perturbations": sim["perturbations"]}


def arm_scene(sim: dict) -> list[dict]:
    """25 Hz rows for data-ui's meshed UR5e: the stand-in's true pose (solid) and the twin with its error x ERROR_SCALE."""

    rows = []
    for k in range(0, len(sim["runs"]["real_a"]), 4):
        for situation, run in (("real", sim["runs"]["real_a"]), (f"twin ×{ERROR_SCALE}", sim["runs"]["twin_x20"])):
            row = {"t": run[k]["t"], "run_set": ARM_RUN, "situation": situation}
            tool = run[k]["tool"]
            row.update({"px": r(tool[0], 5), "py": r(tool[1], 5), "pz": r(tool[2], 5)})
            for link, pose in run[k]["links"].items():
                for name, value in zip(("x", "y", "z", "qw", "qx", "qy", "qz"), pose):
                    row[f"{link}_{name}"] = r(value, 6)
            rows.append(row)
    return rows


def arm_budget(sim: dict, tool_err_mm: float, tool_floor_mm: float, with_suite: bool, camera_mm: dict | None = None) -> list[dict]:
    """The tool's sim-vs-real error split into what each joint causes: J_i (twin q_i - true q_i) at every sample, with
    J_i = axis_i x (tool - origin_i) from the stand-in's link poses, RMS over the tape. The stand-in's TRUE joint angles
    are used (a real arm would need an external tracker for that), which is exactly why J4's encoder-blind offset shows."""

    twin, real = sim["runs"]["twin"], sim["runs"]["real_a"]
    contributions = []
    for j, joint in enumerate(sim["joints"]):
        values = []
        for row_twin, row_real in zip(twin, real):
            pose = row_real["links"][JOINT_LINK[j]]
            axis = rotate(pose[3:7], {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[JOINT_AXIS[j]])
            lever = sub(row_real["tool"], pose[:3])
            dq = row_twin["q_true"][j] - row_real["q_true"][j]
            values.append(norm(cross(axis, lever)) * abs(dq))
        encoder_seen = rms([row_t["q"][j] - row_r["q"][j] for row_t, row_r in zip(twin, real)]) * 1e3
        true_dq = rms([row_t["q_true"][j] - row_r["q_true"][j] for row_t, row_r in zip(twin, real)]) * 1e3
        contributions.append((JOINT_NAMES[joint], JOINT_CLASS[j], rms(values) * 1e3, encoder_seen, true_dq))
    # allocation: acceptance.py's class shares split evenly (root-sum-square) over the joints in each class
    per_class = {c: JOINT_CLASS.count(c) for c in set(JOINT_CLASS)}
    rows = []
    top_allocation = TOOL_GATE_MM
    arm_parent = "tool"
    if with_suite:
        rows.append({"id": "grasp", "parent": None, "label": "Tool vs object at a grasp", "kind": "goal", "order": 0,
                     "allocation_mm": rich(TOOL_GATE_MM, "chosen", "mm", "Zach 2024-04-09: within 5 mm should be ok for grasping"),
                     "sim_vs_real_mm": rich(None, "stand-in", "mm"),  # filled in below, once the camera's share is known
                     "basis": "stand-in", "note": "Arm (where the tool goes) and camera (where the object is), root-sum-square."})
        top_allocation = 4.0
        arm_parent = "grasp"
    rows.append({"id": "tool", "parent": "grasp" if with_suite else None, "label": "Tool position (EEF, derived)", "kind": "tool", "order": 1,
                 "allocation_mm": rich(top_allocation, "assumed" if with_suite else "chosen", "mm",
                                       "4 mm of the 5 mm grasp budget (agent default)" if with_suite else "Zach 2024-04-09: within 5 mm"),
                 "sim_vs_real_mm": rich(r(tool_err_mm, 3), "stand-in", "mm", "twin vs real_a tool position, RMS over the tape"),
                 "floor_mm": rich(r(tool_floor_mm, 3), "stand-in", "mm"), "used": rich(r(tool_err_mm / top_allocation, 3), "derived", "×"),
                 "verdict": "inside share" if tool_err_mm <= top_allocation else "over share", "basis": "stand-in"})
    explained = math.sqrt(sum(c[2] ** 2 for c in contributions))
    for order, (name, joint_class, mm, encoder_mrad, true_mrad) in enumerate(contributions):
        allocation = SHARE_MM[joint_class] / math.sqrt(per_class[joint_class])
        rows.append({"id": name, "parent": "tool", "label": name, "kind": "joint", "order": 10 + order,
                     "allocation_mm": rich(r(allocation, 3), "assumed", "mm", f"{joint_class} share {SHARE_MM[joint_class]} mm split over {per_class[joint_class]} joints (agent default)"),
                     "sim_vs_real_mm": rich(r(mm, 4), "stand-in", "mm", "J_i x (twin - true q_i), RMS"),
                     "encoder_mrad": rich(r(encoder_mrad, 3), "stand-in", "mrad", "what this joint's encoder says (twin - real)"),
                     "true_mrad": rich(r(true_mrad, 3), "stand-in", "mrad", "the joint's true difference"),
                     "used": rich(r(mm / allocation, 3), "derived", "×"),
                     "verdict": "inside share" if mm <= allocation else "over share", "basis": "stand-in",
                     "note": ("encoder-blind: its encoder says it matches; the tool says it does not" if true_mrad > 3 * max(encoder_mrad, 1e-9) else None)})
    rows.append({"id": "residual", "parent": "tool", "label": "Not explained by joint angles", "kind": "residual", "order": 19,
                 "sim_vs_real_mm": rich(r(math.sqrt(max(tool_err_mm ** 2 - explained ** 2, 0.0)), 4), "derived", "mm",
                                        "root-sum-square remainder (link flex, timing; and the linear sum is not exactly RSS)"),
                 "basis": "stand-in"})
    if with_suite and camera_mm:
        # the scene camera locates the object: px -> mm at the table (depth from the camera to the table centre)
        focal = 0.5 * sim["height"] / math.tan(math.radians(42) / 2)
        depth = norm(sub([0.55, -1.25, 0.95], [-0.6, -0.1, 0.135]))
        scene_mm = camera_mm["Scene camera"] * depth / focal * 1e3  # px x m / px = m; the budget is in mm
        rows.append({"id": "camera", "parent": "grasp", "label": "Object location (scene camera)", "kind": "sensor", "order": 30,
                     "allocation_mm": rich(3.0, "assumed", "mm", "3 mm of the 5 mm grasp budget (agent default; 4 and 3 mm make 5 mm RSS)"),
                     "sim_vs_real_mm": rich(r(scene_mm, 3), "stand-in", "mm", f"{camera_mm['Scene camera']:.2f} px x {depth:.2f} m / {focal:.0f} px"),
                     "used": rich(r(scene_mm / 3.0, 3), "derived", "×"), "verdict": "inside share" if scene_mm <= 3.0 else "over share", "basis": "stand-in"})
        rows.append({"id": "not-position", "parent": "grasp", "label": "Wrist camera, IMU, F/T: not in the position budget", "kind": "note", "order": 40,
                     "basis": "stand-in", "note": "They have their own gates (Gate matrix); the wrist camera cross-checks the grasp, it does not set it."})
        grasp = next(row for row in rows if row["id"] == "grasp")
        total = math.sqrt(tool_err_mm ** 2 + scene_mm ** 2)
        grasp["sim_vs_real_mm"] = rich(r(total, 3), "stand-in", "mm", "root-sum-square of tool and object location")
        grasp["used"] = rich(r(total / TOOL_GATE_MM, 3), "derived", "×")
        grasp["verdict"] = "inside share" if total <= TOOL_GATE_MM else "over share"
    return rows


# ---------------------------------------------------------------------------------------------------- the .base pages

SCALES = {
    "rack": {"title": "1-DOF · the rack's 8 motors", "short": "1-DOF rack", "basis": "real",
             "banner": "**Scale: 1-DOF · One Dof Test Rack · REAL data.** 8 motors, real held-out runs (Oct 23-25) against "
                       "each station's twin (bam_rack_twin, replayed; RMS reproduced exactly). One real camera (CAN 14's RealSense); "
                       "no sim render of the rack exists, so no camera can be wiped yet."},
    "arm": {"title": "6-DOF · UR5e arm", "short": "6-DOF arm", "basis": "stand-in",
            "banner": "**Scale: 6-DOF arm · SIM STAND-IN: no real UR5e run exists.** 'Real' is the same MuJoCo UR5e with four "
                      "declared perturbations and sensor noise, run twice for its floor. Chosen to exercise the page, not measured."},
    "suite": {"title": "6-DOF + cameras, IMU, F/T", "short": "Full sensor suite", "basis": "stand-in",
              "banner": "**Scale: full sensor suite · SIM STAND-IN: no real sensor suite exists.** UR5e + scene camera + wrist "
                        "camera + wrist IMU + wrist F/T in MuJoCo; 'real' = the perturbed model (frames say SYNTHETIC REAL)."},
}

PROPOSALS = [
    {"id": "1-visual-home", "title": "Visual home", "axis": "Space: the robot in 3D and its cameras, every view sim vs real, a badge per device",
     "question": "Is it calibrated? (one glance)"},
    {"id": "2-type-catalog", "title": "Type catalog", "axis": "Device type: one standard block per sensor/actuator type; a robot is a list of typed devices",
     "question": "How good is this kind of device?"},
    {"id": "3-gate-matrix", "title": "Gate matrix", "axis": "Acceptance: devices x gates, each cell a pass/fail you can open",
     "question": "Which gates block us?"},
    {"id": "4-run-inspector", "title": "Run inspector", "axis": "Time: pick a run from the tree, every channel real vs twin on one clock",
     "question": "What happened in this run?"},
    {"id": "5-error-budget", "title": "Error budget", "axis": "Consequence: the tool's error at the top, split into what each joint and sensor costs",
     "question": "Where does the tool error come from?"},
]

DEVICE_PROPS = {
    "device": {"displayName": "Device"}, "type": {"displayName": "Type"}, "verdict": {"displayName": "Verdict"},
    "ratio": {"displayName": "Twin ÷ floor"}, "gate_used": {"displayName": "Gate used"}, "gate_limit": {"displayName": "limit"}, "sim_vs_real": {"displayName": "Sim vs real"}, "floor": {"displayName": "Floor"},
    "real_vs_target": {"displayName": "Real vs target"}, "torque_ratio": {"displayName": "Torque ÷ floor"},
    "situation": {"displayName": "Situation"}, "q_deg": {"displayName": "Angle"}, "gap_mrad": {"displayName": "Twin − real"},
    "tau_nm": {"displayName": "Torque"}, "gate_title": {"displayName": "Gate"}, "status": {"displayName": "Status"},
    "allocation_mm": {"displayName": "Allocation"}, "sim_vs_real_mm": {"displayName": "Sim vs real (tool mm)"},
    "real_vs_target_mm": {"displayName": "Real vs target (tool mm)"}, "used": {"displayName": "Used"}, "label": {"displayName": "Node"},
}

STYLE = {"chrome": "minimal", "numbers": {"digits": 3, "compact": True}, "palette": PALETTE}


def head(scale: str, proposal: dict) -> str:
    return (f"# sim2real · proposal {proposal['id']} · scale {scale}: {proposal['axis']}\n"
            f"# Built by dashboards/build.py ({dt.date.today().isoformat()}); data-ui grammar: vendor/data-ui (PEP 0004 dashboards, PEP 0005 cards).\n"
            f"# {'REAL rack data' if SCALES[scale]['basis'] == 'real' else 'SIM STAND-IN: no real run exists at this scale'}.\n")


def banner(scale: str, proposal: dict, extra: str = "") -> dict:
    return {"text": f"## {proposal['title']} · {SCALES[scale]['short']}\n{SCALES[scale]['banner']}{(' ' + extra) if extra else ''}", "w": 12}


def badges_view(devices_dataset="devices", name="Calibrated?"):
    # WHY no groupOrder: data-ui draws the first card of an authored order as a big headline, and no device is the
    # headline here; rows are written in device order, which the groups keep
    return {"type": "kpi", "name": name, "from": devices_dataset, "groupBy": {"property": "device"},
            "kpi": {"value": {"property": "gate_used"}, "compare": {"against": "gate_limit", "better": "lower"}}}


def twinned_gauge(n_devices: int):
    return {"type": "gauge", "name": "Twinned", "from": "devices",
            "gauge": {"value": {"property": "twinned", "summary": "Sum"}, "min": 0, "max": n_devices, "target": n_devices, "shape": "arc",
                      "better": "higher", "label": f"Devices twinned (≤ {GATE}× their floor)",
                      "bands": [{"to": n_devices * 0.5, "tone": "bad"}, {"to": n_devices - 0.5, "tone": "warn"}, {"tone": "good"}]}}


def scene_view(scale: str, name: str):
    if scale == "rack":
        return {"type": "scene3d", "name": name, "from": "scene",
                "scene3d": {"x": "px", "y": "py", "z": "pz", "series": "situation", "target": f"twin ×{ERROR_SCALE}", "t": "t",
                            "skeleton": scene_columns(len(RACK_ORDER))}}
    links = ["base", "shoulder_link", "upper_arm_link", "forearm_link", "wrist_1_link", "wrist_2_link", "wrist_3_link"]
    return {"type": "scene3d", "name": name, "from": "scene",
            "scene3d": {"x": "px", "y": "py", "z": "pz", "series": "situation", "target": f"twin ×{ERROR_SCALE}", "t": "t",
                        "skeleton": [[f"{link}_x", f"{link}_y", f"{link}_z"] for link in links] + [["px", "py", "pz"]],
                        "robot": {"model": GLB, "links": links, "ghost": f"twin ×{ERROR_SCALE}"}}}


def timeseries(name, dataset, y, unit, filters=None, series="situation", dash=None, rules=None, legend="top", extra=None):
    view = {"type": "timeseries", "name": name, "from": dataset,
            "timeseries": {"x": "t", "y": y, "series": series, "unit": unit, "legend": legend}}
    if filters:
        view["filters"] = filters
    if dash:
        view["timeseries"]["dash"] = dash
    if rules:
        view["timeseries"]["rules"] = rules
    if extra:
        view["timeseries"].update(extra)
    return view


def dataset_entries(scale: str, ctx: dict, *, run_rail: bool, device_rails: bool) -> dict:
    """Every dataset a scale has, with the rails a proposal wants (a run picker, a device picker per type)."""

    datasets = {"devices": "devices.json"}
    defaults = ctx["defaults"]
    for type_ in ctx["types"]:
        file = f"samples_{type_}.json"
        entry = {"data": file}
        facets = []
        filters = []
        if run_rail and scale == "rack" and type_ == "servo":
            facets.append({"property": "run_set", "as": "select", "label": "Runs"})
            filters.append(f'run_set == "{defaults["run_set"]}"')
        if device_rails and type_ in ("servo", "camera"):
            facets.append({"property": "device", "as": "select", "label": ctx["type_titles"][type_]})
            filters.append(f'device == "{defaults[type_]}"')
        if facets:
            entry["facets"] = facets
        if filters:
            entry["filters"] = " && ".join(filters)
        datasets[type_] = entry if len(entry) > 1 else file
    return datasets


def page_visual_home(scale: str, ctx: dict, proposal: dict) -> dict:
    n = len(ctx["devices"])
    # WHY one run set per page and no run picker: a dashboard's clock spans every row of its clock dataset, filters or
    # not, so a picker over a 4.5 s set and a 36 s set left a 36 s clock (data-ui gap list)
    datasets = {"devices": "devices.json", "scene": "scene.json", "servo": "samples_servo.json"}
    links = [{"from": "servo.run_set", "to": "scene.run_set"}]
    if ctx["media"]:
        datasets["media"] = "media.json"
        if scale != "rack":
            links.append({"from": "media.run_set", "to": "scene.run_set"})
    if "eef" in ctx["types"]:
        datasets["eef"] = "samples_eef.json"
        links.append({"from": "eef.run_set", "to": "scene.run_set"})
    panels = [banner(scale, proposal, "Green = twin within 1.5× the device's own run-to-run floor. The 3D draws the twin as a ghost with its error ×20.")]
    panels += [{"view": "Twinned", "w": 3, "h": 3},
               {"view": "Calibrated?", "w": 9, "h": 3, "title": "Calibrated? Each device's share of its fidelity gate (≤ 1 passes)"},
               {"view": "Playback", "w": 12}]
    views = [twinned_gauge(n), badges_view()]
    views.append({"type": "playback", "name": "Playback", "playback": {"speeds": [0.25, 0.5, 1, 2], "range": True, "readout": True}})
    scene_name = f"3D · real (solid) vs twin (ghost, error ×{ERROR_SCALE})"
    views.append(scene_view(scale, scene_name))
    if scale == "rack":
        panels += [{"view": scene_name, "w": 7, "h": 5}, {"view": "Camera · CAN 14, real still (no sim render)", "w": 5, "h": 5}]
        views.append({"type": "image", "name": "Camera · CAN 14, real still (no sim render)", "from": "media", "image": "poster", "caption": ["caption"]})
    elif scale == "arm":
        panels += [{"view": scene_name, "w": 12, "h": 5}]
    else:
        panels += [{"view": scene_name, "w": 6, "h": 5}, {"view": "Scene camera · wipe twin ↔ real", "w": 6, "h": 5},
                   {"view": "Wrist camera · wipe twin ↔ real", "w": 6, "h": 4}, {"view": "Tool gap · twin − real", "w": 6, "h": 4}]
        views.append({"type": "video-compare", "name": "Scene camera · wipe twin ↔ real", "from": "media", "filters": 'device == "Scene camera"',
                      "overlay": {"by": "situation", "a": "twin", "b": "real", "mode": "wipe", "split": 0.5}})
        views.append({"type": "video-compare", "name": "Wrist camera · wipe twin ↔ real", "from": "media", "filters": 'device == "Wrist camera"',
                      "overlay": {"by": "situation", "a": "twin", "b": "real", "mode": "wipe", "split": 0.5}})
        views.append(timeseries("Tool gap · twin − real", "eef", "gap_mm", "mm", filters='situation == "twin" || situation == "floor"'))
    panels.append({"view": "Joint gap · twin − real, every servo", "w": 12 if scale != "arm" else 8, "h": 3})
    views.append(timeseries("Joint gap · twin − real, every servo", "servo", "gap_mrad", "mrad",
                            filters=f'situation == "twin" && run_set == "{ctx["defaults"]["run_set"]}"', series="device"))
    if scale == "arm":
        panels.append({"view": "Tool gap · twin − real", "w": 4, "h": 3})
        views.append(timeseries("Tool gap · twin − real", "eef", "gap_mm", "mm", filters='situation == "twin" || situation == "floor"'))
    clock = {"data": "scene", "time": "t", "loop": True}
    return {"data": "devices.json", "properties": DEVICE_PROPS, "style": STYLE, "clock": clock, "datasets": datasets, "links": links,
            "layout": {"panels": panels}, "views": views}


TYPE_BLOCKS = {
    "servo": "Ruler: joint angle RMS, twin vs real, ÷ the device's own run-to-run floor (≤ 1.5×); torque within 2×; stop error p90 against its share of the 5 mm tool gate.",
    "eef": "Derived one level up from every joint. Ruler: tool position RMS, twin vs real, ÷ floor (≤ 1.5×); tool at a stop within 5 mm (Zach, 2024).",
    "camera": "Ruler: reprojection of known points (the table blocks), twin render vs real frame, ÷ the real-vs-real repeat (≤ 1.5×). The wipe is the same thing for your eyes.",
    "imu": "Ruler: acceleration and angular-rate vectors, twin vs real, ÷ floor (≤ 1.5×).",
    "ft": "Ruler: force and torque vectors, twin vs real, ÷ floor (≤ 1.5×). Weighs what the twin thinks the payload is.",
}


def page_type_catalog(scale: str, ctx: dict, proposal: dict) -> dict:
    # WHY no run picker here: a rail filter of two clauses (run set && device) reads as a custom filter, and the device
    # picker then lists only the device already chosen; the rack's run set is a fixed view filter instead
    datasets = dataset_entries(scale, ctx, run_rail=False, device_rails=True)
    in_set = f' && run_set == "{ctx["defaults"]["run_set"]}"' if scale == "rack" else ""
    if ctx["media"]:
        datasets["media"] = "media.json"
    # WHY no link from the samples to devices: the badges and the composition table must keep every device of a type
    # while the rail shows one of them
    links = []
    if ctx["media"] and scale != "rack":
        links.append({"from": "media.device", "to": "camera.device"})
    panels = [banner(scale, proposal, "Each type below is the same standard block at every scale; pick the device in the rail.")]
    views = []
    panels.append({"view": "Robot = typed devices", "w": 12, "h": 3, "title": "Composition: the robot as a list of typed devices"})
    views.append({"type": "table", "name": "Robot = typed devices", "from": "devices", "groupBy": {"property": "type_title"},
                  "order": ["device", "verdict", "gate_used", "ratio", "sim_vs_real", "floor", "real_vs_target", "metric", "basis"]})
    clock_data = "servo"
    for type_ in ["servo", "eef", "camera", "imu", "ft"]:
        if type_ not in ctx["types"] and not (type_ == "camera" and scale == "rack"):
            continue
        title = ctx["type_titles"].get(type_, "Camera")
        panels.append({"text": f"### {title} · standard block\n{TYPE_BLOCKS[type_]}", "w": 12})
        badge_name = f"{title} · each device"
        views.append({**badges_view(name=badge_name), "filters": f'type == "{type_}"'})
        if type_ == "servo":
            panels += [{"view": badge_name, "w": 12}]
            views.append(timeseries("Servo · angle, real vs twin", "servo", "q_deg", "°",
                                    filters='situation != "floor" && situation != "floor −"' + in_set, dash=["target"]))
            views.append(timeseries("Servo · twin − real (lines: ± the device's floor)", "servo", "gap_mrad", "mrad",
                                    filters='(situation == "twin" || situation == "floor" || situation == "floor −")' + in_set, dash=["floor", "floor −"]))
            views.append(timeseries("Servo · torque, real vs twin", "servo", "tau_nm", "N·m", filters='(situation == "real" || situation == "twin")' + in_set))
            panels += [{"view": "Servo · angle, real vs twin", "w": 6, "h": 3}, {"view": "Servo · twin − real (lines: ± the device's floor)", "w": 6, "h": 3},
                       {"view": "Servo · torque, real vs twin", "w": 12, "h": 3}]
        elif type_ == "eef":
            panels += [{"view": badge_name, "w": 4, "h": 2}, {"view": "Tool path · real vs twin (XZ)", "w": 8, "h": 4},
                       {"view": "Tool · twin − real", "w": 4, "h": 2}]
            views.append({"type": "trajectory", "name": "Tool path · real vs twin (XZ)", "from": "eef", "filters": 'situation != "floor"',
                          "trajectory": {"x": "x_mm", "y": "z_mm", "series": "situation", "target": "target", "t": "t", "trail": True}})
            views.append(timeseries("Tool · twin − real", "eef", "gap_mm", "mm", filters='situation == "twin" || situation == "floor"'))
        elif type_ == "camera" and scale == "rack":
            panels += [{"view": badge_name, "w": 4, "h": 2}, {"view": "Camera · real only (no sim render to wipe)", "w": 8, "h": 4}]
            views.append({"type": "video", "name": "Camera · real only (no sim render to wipe)", "from": "media", "video": {"src": "src", "label": "run"}})
        elif type_ == "camera":
            panels += [{"view": badge_name, "w": 12}, {"view": "Camera · wipe twin ↔ real", "w": 6, "h": 4},
                       {"view": "Camera · reprojection error", "w": 6, "h": 4}]
            views.append({"type": "video-compare", "name": "Camera · wipe twin ↔ real", "from": "media",
                          "overlay": {"by": "situation", "a": "twin", "b": "real", "mode": "wipe", "split": 0.5}})
            views.append(timeseries("Camera · reprojection error", "camera", "reproj_px", "px", extra={"legend": "top"}))
        elif type_ == "imu":
            panels += [{"view": badge_name, "w": 4, "h": 2}, {"view": "IMU · vertical acceleration", "w": 8, "h": 3}]
            views.append(timeseries("IMU · vertical acceleration", "imu", "accel_z", "m/s²", filters='situation != "real B"'))
        elif type_ == "ft":
            panels += [{"view": badge_name, "w": 4, "h": 2}, {"view": "F/T · vertical force", "w": 8, "h": 3}]
            views.append(timeseries("F/T · vertical force", "ft", "force_z", "N", filters='situation != "real B"'))
    return {"data": "devices.json", "properties": DEVICE_PROPS, "style": STYLE, "clock": {"data": clock_data, "time": "t", "loop": True},
            "datasets": datasets, "links": links, "layout": {"panels": panels}, "views": views}


def page_gate_matrix(scale: str, ctx: dict, proposal: dict) -> dict:
    datasets = {"gates": {"data": "gates.json", "facets": ["type", "status"]}, "devices": "devices.json"}
    links = [{"from": "gates.device", "to": "devices.device"}]
    n_cells = len(ctx["gates"])
    panels = [banner(scale, proposal, "Rows are devices, blocks are gates in order; hover a block for its value, click it for the evidence."),
              {"view": "Gate cells passing", "w": 3, "h": 2}, {"view": "Devices twinned", "w": 3, "h": 2},
              {"view": "Passing per gate", "w": 6, "h": 2},
              {"text": "**Blocks, left to right:** " + " · ".join(ctx["gate_order"]), "w": 12},
              {"view": "Devices × gates", "w": 12, "h": 4},
              {"view": "Evidence", "w": 12, "h": 5, "toolbar": "full"}]
    views = [
        {"type": "gauge", "name": "Gate cells passing", "from": "gates",
         "gauge": {"value": {"property": "passed", "summary": "Ratio", "per": "cell"}, "min": 0, "max": 1, "target": 1, "shape": "arc", "better": "higher",
                   "label": f"Cells passing, of {n_cells}", "bands": [{"to": 0.5, "tone": "bad"}, {"to": 0.99, "tone": "warn"}, {"tone": "good"}]}},
        twinned_gauge(len(ctx["devices"])) | {"name": "Devices twinned"},
        {"type": "barlist", "name": "Passing per gate", "from": "gates",
         "barlist": {"label": "gate_title", "value": {"property": "passed", "summary": "Sum"}, "better": "higher", "limit": 12}},
        {"type": "tracker", "name": "Devices × gates", "from": "gates", "groupBy": {"property": "device"},
         "groupOrder": [d["device"] for d in ctx["devices"]], "sort": [{"property": "order", "direction": "ASC"}],
         "tracker": {"state": "status", "label": "gate_title", "tones": TONES}},
        {"type": "table", "name": "Evidence", "from": "gates", "groupBy": {"property": "gate_title"},
         "order": ["device", "status", "value", "target", "detail", "evidence", "basis"]},
    ]
    return {"data": "gates.json", "properties": DEVICE_PROPS, "style": STYLE, "datasets": datasets, "links": links,
            "layout": {"panels": panels}, "views": views}


def page_run_inspector(scale: str, ctx: dict, proposal: dict) -> dict:
    datasets = {"runs": "runs.json"}
    for type_ in ctx["types"]:
        datasets[type_] = f"samples_{type_}.json"
    if scale != "rack":
        datasets["servo"] = {"data": "samples_servo.json", "facets": [{"property": "device", "as": "select", "label": "Servo"}],
                             "filters": f'device == "{ctx["defaults"]["servo"]}"'}
    datasets["scene"] = "scene_runs.json" if scale == "rack" else "scene.json"
    links = [{"from": f"{type_}.run", "to": "runs.run"} for type_ in ctx["types"]] + [{"from": "scene.run_set", "to": "runs.run_set"}]
    if ctx["media"]:
        datasets["media"] = "media.json"
        links.append({"from": "media.run", "to": "runs.run"})
    panels = [banner(scale, proposal, "The tree lists every run; click one (it starts on the first) and every card below plays it on one clock."),
              {"view": "Runs", "w": 6, "h": 4, "title": "Runs"}, {"view": "3D", "w": 6, "h": 4},
              {"view": "Playback", "w": 12},
              {"view": "Angle · real vs twin", "w": 6, "h": 3}, {"view": "Twin − real", "w": 6, "h": 3},
              {"view": "Torque · real vs twin", "w": 6, "h": 3}]
    views = [
        {"type": "table", "name": "Runs", "from": "runs", "select": "run", "tree": {"parent": "parent"},
         "order": ["label", "kind", "duration_s", "rms_q_mrad", "twin", "situations", "basis"]},
        {**scene_view(scale, "3D")},
        {"type": "playback", "name": "Playback", "playback": {"speeds": [0.25, 0.5, 1, 2], "range": True, "readout": True}},
        timeseries("Angle · real vs twin", "servo", "q_deg", "°", filters='situation != "floor" && situation != "floor −"', dash=["target"]),
        timeseries("Twin − real", "servo", "gap_mrad", "mrad", filters='situation == "twin" || situation == "floor" || situation == "floor −"', dash=["floor", "floor −"]),
        timeseries("Torque · real vs twin", "servo", "tau_nm", "N·m", filters='situation == "real" || situation == "twin" || situation == "real B"'),
    ]
    if scale == "rack":
        panels += [{"view": "Current (real only)", "w": 6, "h": 3}, {"view": "Camera (only the staircase has one)", "w": 6, "h": 4},
                   {"view": "Winding temperature (real only)", "w": 6, "h": 4}]
        views += [timeseries("Current (real only)", "servo", "i_q_a", "A", filters='situation == "real"'),
                  {"type": "video", "name": "Camera (only the staircase has one)", "from": "media", "video": {"src": "src", "label": "run", "primary": True}},
                  timeseries("Winding temperature (real only)", "servo", "temp_c", "°C", filters='situation == "real"')]
    else:
        panels += [{"view": "Tool · error vs target", "w": 6, "h": 3}]
        views.append(timeseries("Tool · error vs target", "eef", "err_mm", "mm", filters='situation != "floor"', rules=[{"y": TOOL_GATE_MM, "label": "5 mm"}]))
    if scale == "suite":
        panels += [{"view": "Scene camera · twin ↔ real", "w": 6, "h": 4}, {"view": "Wrist camera · twin ↔ real", "w": 6, "h": 4},
                   {"view": "Camera reprojection error", "w": 6, "h": 3}, {"view": "IMU · vertical acceleration", "w": 6, "h": 3},
                   {"view": "F/T · vertical force", "w": 6, "h": 3}, {"view": "F/T · twin − real", "w": 6, "h": 3}]
        views += [{"type": "video-compare", "name": "Scene camera · twin ↔ real", "from": "media", "filters": 'device == "Scene camera"',
                   "overlay": {"by": "situation", "a": "twin", "b": "real", "mode": "difference", "split": 0.5}},
                  {"type": "video-compare", "name": "Wrist camera · twin ↔ real", "from": "media", "filters": 'device == "Wrist camera"',
                   "overlay": {"by": "situation", "a": "twin", "b": "real", "mode": "onion", "split": 0.5}},
                  timeseries("Camera reprojection error", "camera", "reproj_px", "px", series="device", filters='situation == "twin"'),
                  timeseries("IMU · vertical acceleration", "imu", "accel_z", "m/s²", filters='situation != "real B"'),
                  timeseries("F/T · vertical force", "ft", "force_z", "N", filters='situation != "real B"'),
                  timeseries("F/T · twin − real", "ft", "gap_force", "N", filters='situation == "twin"')]
    clock = {"data": "servo", "time": "t"}
    return {"data": "runs.json", "properties": DEVICE_PROPS, "style": STYLE, "clock": clock, "datasets": datasets, "links": links,
            "layout": {"panels": panels}, "views": views}


def page_error_budget(scale: str, ctx: dict, proposal: dict) -> dict:
    top = ctx["budget"][0]
    datasets = {"budget": "budget.json", "devices": "devices.json"}
    panels = [banner(scale, proposal, "Two errors per node (Zach, 2026-07-31): sim vs real, and real vs target. Allocations are "
                                      "acceptance.py's agent defaults (\"Zach to confirm\")."),
              {"view": "Top of the budget", "w": 4, "h": 2}, {"view": "Share used, every node", "w": 8, "h": 4},
              {"view": "Budget tree", "w": 12, "h": 5}]
    views = [
        {"type": "kpi", "name": "Top of the budget", "from": "budget", "filters": f'id == "{top["id"]}"',
         "kpi": {"label": f"{top['label']} · sim vs real", "value": {"property": "sim_vs_real_mm"}, "compare": {"against": "allocation_mm", "better": "lower"}}},
        {"type": "bullet", "name": "Share used, every node", "from": "budget", "filters": 'kind != "note" && kind != "residual"',
         "sort": [{"property": "order", "direction": "ASC"}],
         "bullet": {"value": {"property": "used"}, "target": 1, "max": 4, "label": "label", "better": "lower", "bands": [1, 2, 4]}},
        {"type": "table", "name": "Budget tree", "from": "budget", "tree": {"parent": "parent"}, "sort": [{"property": "order", "direction": "ASC"}],
         "order": ["label", "allocation_mm", "sim_vs_real_mm", "used", "verdict", "real_vs_target_mm"]
                  + (["encoder_mrad", "true_mrad"] if scale != "rack" else ["lever_m"]) + ["basis", "note"]},
    ]
    if scale != "rack":
        panels.append({"view": "Encoder sees vs tool sees", "w": 12, "h": 3})
        datasets["encoder_vs_true"] = "encoder_vs_true.json"
        views.append({"type": "chart", "name": "Encoder sees vs tool sees", "from": "encoder_vs_true",
                      "chart": {"mark": "bar",
                                "encoding": {"y": {"field": "joint", "title": None, "sort": None},
                                             "x": {"field": "mrad", "title": "twin − real, RMS (mrad)"},
                                             "color": {"field": "what", "title": None}, "yOffset": {"field": "what"}}}})
    return {"data": "budget.json", "properties": DEVICE_PROPS, "style": STYLE, "datasets": datasets,
            "layout": {"panels": panels}, "views": views}


def prune_orders(doc: dict, folder: pathlib.Path) -> dict:
    """A table's `order:` keeps only the columns its file has at this scale (the rack has levers, the arm encoders)."""

    files = {name: (entry if isinstance(entry, str) else entry["data"]) for name, entry in doc.get("datasets", {}).items()}
    default = pathlib.Path(doc["data"]).stem
    files.setdefault(default, doc["data"])
    for view in doc["views"]:
        if "order" in view:
            data = json.loads((folder / files[view.get("from", default)]).read_text())
            view["order"] = [column for column in view["order"] if column in data["properties"]]
    return doc


PAGES = {"1-visual-home": page_visual_home, "2-type-catalog": page_type_catalog, "3-gate-matrix": page_gate_matrix,
         "4-run-inspector": page_run_inspector, "5-error-budget": page_error_budget}


# ---------------------------------------------------------------------------------------------------- writing


def write_scale(scale: str, data: dict) -> dict:
    folder = HERE / scale
    folder.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    basis = "REAL rack runs" if scale == "rack" else "SIM STAND-IN (no real run exists)"
    types = [t for t in ("servo", "eef", "camera", "imu", "ft") if data.get(t)]
    counts = {}
    counts["devices"] = write_dataset(folder, "devices.json", f"Devices · {SCALES[scale]['title']}", f"{basis}; built {stamp}", {
        "device": {"type": "text", "note": "One sensor or actuator (or a derived quantity, type eef)."},
        "type": {"type": "text", "display": "badge"}, "verdict": {"type": "text", "display": "badge"},
        "ratio": {"type": "number", "unit": "×", "digits": 3, "note": f"sim-vs-real error ÷ the device's own run-to-run floor; twinned at ≤ {GATE}"},
        "gate": {"type": "number", "unit": "×"}, "twinned": {"type": "number", "note": "1 if twinned, else 0 (for counting)"},
        "basis": {"type": "text", "display": "badge", "note": "real = measured on the rack; stand-in = synthetic (perturbed sim)"},
    }, data["devices"])
    counts["gates"] = write_dataset(folder, "gates.json", f"Gates · {SCALES[scale]['title']}", f"{basis}; built {stamp}", {
        "status": {"type": "text", "display": "badge", "note": "pass · fail · partial (real evidence that cannot settle it) · not_run (no evidence, never a pass)"},
        "passed": {"type": "number"}, "cell": {"type": "number"},
    }, data["gates"])
    unit_props = {"t": {"type": "number", "unit": "s", "digits": 3}, "q_deg": {"type": "number", "unit": "°", "digits": 4},
                  "gap_mrad": {"type": "number", "unit": "mrad", "digits": 3}, "tau_nm": {"type": "number", "unit": "N·m", "digits": 3},
                  "i_q_a": {"type": "number", "unit": "A"}, "temp_c": {"type": "number", "unit": "°C"},
                  "situation": {"type": "text", "display": "badge", "note": "target · real · twin · real B (the stand-in's repeat) · floor (± the device's floor, two points)"}}
    for type_ in types:
        counts[f"samples_{type_}"] = write_dataset(folder, f"samples_{type_}.json", f"{type_} samples · {SCALES[scale]['title']}",
                                                   f"{basis}; built {stamp}", unit_props, data[type_])
    first_set = data["scene"][0]["run_set"]
    counts["scene"] = write_dataset(folder, "scene.json", f"3D rows · {SCALES[scale]['title']} · {first_set}",
                                    f"{basis}; twin drawn with its error x{ERROR_SCALE} (display aid); built {stamp}",
                                    {"situation": {"type": "text"}}, [row for row in data["scene"] if row["run_set"] == first_set])
    if scale == "rack":
        counts["scene_runs"] = write_dataset(folder, "scene_runs.json", f"3D rows · {SCALES[scale]['title']} · every run set",
                                             f"{basis}; twin drawn with its error x{ERROR_SCALE} (display aid); built {stamp}",
                                             {"situation": {"type": "text"}}, data["scene"])
    counts["budget"] = write_dataset(folder, "budget.json", f"Error budget · {SCALES[scale]['title']}", f"{basis}; built {stamp}",
                                     {"verdict": {"type": "text", "display": "badge"}, "kind": {"type": "text", "display": "badge"},
                                      "lever_m": {"type": "number", "unit": "m"}}, data["budget"])
    counts["runs"] = write_dataset(folder, "runs.json", f"Runs · {SCALES[scale]['title']}", f"{basis}; built {stamp}",
                                   {"kind": {"type": "text", "display": "badge"}, "duration_s": {"type": "number", "unit": "s"}}, data["runs"])
    if scale != "rack":
        long_rows = []
        for row in data["budget"]:
            if row.get("kind") == "joint":
                long_rows.append({"joint": row["label"], "what": "its encoder says", "mrad": row["encoder_mrad"]["value"]})
                long_rows.append({"joint": row["label"], "what": "the joint truly is (what the tool feels)", "mrad": row["true_mrad"]["value"]})
        counts["encoder_vs_true"] = write_dataset(folder, "encoder_vs_true.json", "Encoder vs true joint error", f"{basis}; built {stamp}",
                                                  {"mrad": {"type": "number", "unit": "mrad", "digits": 3}}, long_rows)
    if data["media"]:
        (folder / "media").mkdir(exist_ok=True)
        for path in data["media_files"]:
            shutil.copy2(path, folder / "media" / path.name)
        for row in data["media"]:
            row["src"] = f"media/{pathlib.Path(row['src']).name}"
            row["poster"] = f"media/{pathlib.Path(row['poster']).name}"
        counts["media"] = write_dataset(folder, "media.json", f"Camera clips · {SCALES[scale]['title']}", f"{basis}; built {stamp}",
                                        {"src": {"type": "text", "media": "video"}, "poster": {"type": "text", "media": "image"},
                                         "t0": {"type": "number", "unit": "s"}, "basis": {"type": "text", "display": "badge"}}, data["media"])
    titles = {"servo": "Servo", "eef": "End effector", "camera": "Camera", "imu": "IMU", "ft": "F/T"}
    worst = {}
    for device in data["devices"]:
        ratio = device["ratio"]["value"] if isinstance(device.get("ratio"), dict) else None
        if ratio is not None and (device["type"] not in worst or ratio > worst[device["type"]][1]):
            worst[device["type"]] = (device["device"], ratio)
    defaults = {type_: name for type_, (name, _) in worst.items()}
    defaults["run_set"] = data["scene"][0]["run_set"]
    gate_order = []
    for gate in sorted(data["gates"], key=lambda g: g["order"]):
        if gate["gate_title"] not in gate_order and gate["type"] == data["devices"][0]["type"]:
            gate_order.append(gate["gate_title"])
    gate_order.append("(other device types: their own gates, in order)")
    ctx = {"gate_order": gate_order, "devices": data["devices"], "gates": data["gates"], "budget": data["budget"], "types": types, "media": bool(data["media"]),
           "type_titles": titles, "defaults": defaults}
    pages = []
    for proposal in PROPOSALS:
        doc = prune_orders(PAGES[proposal["id"]](scale, ctx, proposal), folder)
        text = head(scale, proposal) + data_ui_base.dumps(doc)
        assert data_ui_base.loads(text) == json.loads(json.dumps(doc)), f"{scale}/{proposal['id']}: the .base does not round-trip"
        (folder / f"{proposal['id']}.base").write_text(text, encoding="utf-8")
        pages.append(f"{scale}/{proposal['id']}.base")
    first_run = next((row["run"] for row in data["runs"] if row.get("run")), None)
    return {"counts": counts, "pages": pages, "first_run": first_run,
            "verdicts": {d["device"]: d["verdict"] for d in data["devices"]}}


def main() -> int:
    built = {"rack": write_scale("rack", rack_scale()), "arm": write_scale("arm", arm_scale(with_suite=False)),
             "suite": write_scale("suite", arm_scale(with_suite=True))}
    manifest = {"built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "default": {"proposal": "1-visual-home", "scale": "rack"},
                "proposals": PROPOSALS, "scales": [{"id": key, **{k: v for k, v in value.items() if k != "banner"}} for key, value in SCALES.items()],
                "first_run": {scale: info["first_run"] for scale, info in built.items()}}
    (HERE / "proposals.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for scale, info in built.items():
        print(scale, info["counts"])
        print("  ", ", ".join(f"{d}: {v}" for d, v in info["verdicts"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
