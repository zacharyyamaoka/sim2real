"""The rack's two real calibrations of 2026-11-10/11 as CalibrationResults (sim2real.result): the UR wrist and the five-bar.

    from sim2real.rack_results import load
    load("ur_wrist").display()        # or "fivebar"

WHY assembled from the archive (2026-11-11): Twin.calibrate(on="real") is not wired yet (twin.py says so); these two calibrations were run
by their own lanes on the rack overnight, and what each lane wrote is exactly what calibrate() would return: the twin iterations, the
fitted parameters, the model ladder's held-out scores, the runs. This module only reads them (read-only, /archive/datasets/bam_rig/
rack_2026-11-10) and puts them on the description's tree. No number is fitted here.

- UR wrist (bam_ur_wrist_coverage): twins record -> it2 -> it3 -> it5 (summary_real.json, one score per run per twin on one player);
  parameters refit_rig/it5/refit.json base -> refit (+ its delay scans); models it5's ladder (coulomb, +gravity, stribeck, +gravity)
  beside the twin of record; arm coverage from multi/multi_scores.json (the coverage lane's reachable-set shares).
- Five-bar (bam_fivebar): twins study -> mass-ID gravity -> dynamics refit -> refit on the tick clock (each refit's per-rung held-out
  scores; the study twin's from the ladder's own sim beside each rung); parameters massid gravity_params.json nominal -> identified and
  refit_both's start -> best; models the refits' held-out scores; coverage the ladder's raster.

Floors (the ruler's denominator): the real joint's run-to-run RMS between repeats of one stimulus (sim2real.metrics.series.pair_rms on
a common clock), median over the repeat pairs found in the data.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

from .metrics.series import pair_rms
from .result import TOOL_GATE_MM, CalibrationResult, Node

RACK = Path("/archive/datasets/bam_rig/rack_2026-11-10")
WRIST = RACK / "ur_wrist" / "coverage"
FIVEBAR = RACK / "fivebar_real"
# the classic traj_compare run views built for these runs (bam_ws bam_sim2real_present, one folder per run slug)
RUN_VIEWS = Path("/home/bam/bam_ws/reports/sim2real-presentation-proposals-2026-11-11/runs")
BINS = {"position": 10.0, "speed": 20.0, "acceleration": 200.0}   # degrees, °/s, °/s²
WORKSPACE_CELL_MM = 20.0
# the wrist's twin traces: each real run replayed on the twin of record (it5) by the wrist lane's own player, cached by bam_ws
# bam_sim2real_present.replay_wrist (summary_real.json keeps numbers only)
WRIST_TWIN_CACHE = Path.home() / ".cache" / "bam_sim2real_present" / "wrist_it5"


def _trajectory(t, positions, joints):
    from robot_msgs.trajectory import JointTrajectory

    positions = np.asarray(positions, float).reshape(len(t), -1)
    keep = np.isfinite(t) & np.isfinite(positions).all(axis=1)
    return JointTrajectory(t=np.asarray(t, float)[keep], joint_names=tuple(joints), positions=positions[keep])


def _wrist_target(t, q, q_target, qd_target):
    """The commanded angle; a velocity kind's is the integral of its commanded speed, a coast holds the last command
    (bam_ur_wrist_coverage.pages._target's rule)."""
    target = np.asarray(q_target, float).copy()
    if not np.isfinite(target).any():
        return q[0] + np.cumsum(qd_target * np.diff(t, prepend=t[0]))
    last = target[np.flatnonzero(np.isfinite(target))[0]]
    for index in range(target.size):
        last = target[index] if np.isfinite(target[index]) else last
        target[index] = last
    return target


def _messages(files: dict):
    """run id -> {"target", "sim", "real"} as robot_msgs JointTrajectory, read from the producer's files on demand."""
    def load(run: str) -> dict:
        kind, real_path, sim_path, joints = files[run]
        real = np.load(real_path)
        if kind == "ur_wrist":
            t = real["t"] - real["t"][0]
            out = {"target": _trajectory(t, _wrist_target(t, real["q"], real["q_target"], real["qd_target"]), joints),
                   "real": _trajectory(t, real["q"], joints)}
            if sim_path and Path(sim_path).exists():
                sim = np.load(sim_path)
                out["sim"] = _trajectory(sim["t"] - sim["t"][0], sim["q"], joints)
            return out
        t = real["t"] - real["t"][0]
        sim = np.load(sim_path)
        sim_t = t if sim["t"].size == t.size else sim["t"] - sim["t"][0]
        return {"target": _trajectory(t, real["target_motors"], joints), "sim": _trajectory(sim_t, sim["measured_motors"], joints),
                "real": _trajectory(t, real["measured_motors"], joints)}
    return load


def load(name: str) -> CalibrationResult:
    return {"ur_wrist": ur_wrist, "fivebar": fivebar}[name]()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def deg(rad):
    return None if rad is None or not math.isfinite(rad) else math.degrees(rad)


def mdeg(mrad):
    return None if mrad is None else deg(mrad / 1e3)


def run_view(run_slug: str) -> str | None:
    return f"runs/{run_slug}/report.html" if (RUN_VIEWS / run_slug / "report.html").exists() else None


def histogram(values: np.ndarray, width: float, dt: float, channel: str) -> list[dict]:
    values = values[np.isfinite(values)]
    if not values.size:
        return []
    lo = math.floor(np.percentile(values, 0.2) / width) * width
    hi = math.ceil(np.percentile(values, 99.8) / width) * width
    counts, edges = np.histogram(np.clip(values, lo, hi), np.arange(lo, hi + width, width))
    return [{"channel": channel, "lo": round(float(a), 3), "hi": round(float(b), 3), "seconds": round(float(c) * dt, 3), "zero": 0.0}
            for a, b, c in zip(edges[:-1], edges[1:], counts) if c]


def joint_coverage(q_deg: np.ndarray, qd_deg_s: np.ndarray, qdd_deg_s2: np.ndarray, dt: float) -> tuple[list[dict], list[dict]]:
    rows = (histogram(q_deg, BINS["position"], dt, "position") + histogram(qd_deg_s, BINS["speed"], dt, "speed")
            + histogram(qdd_deg_s2, BINS["acceleration"], dt, "acceleration"))
    finite = lambda a: a[np.isfinite(a)]  # noqa: E731
    q, qd, qdd = finite(q_deg), finite(qd_deg_s), finite(qdd_deg_s2)
    summary = [{"measure": "angle range", "value": f"{q.min():.0f} … {q.max():.0f}", "unit": "°"},
               {"measure": "peak |speed| (p99)", "value": f"{np.percentile(np.abs(qd), 99):.0f}", "unit": "°/s"},
               {"measure": "peak |acceleration| (p99)", "value": f"{np.percentile(np.abs(qdd), 99):.0f}", "unit": "°/s²"},
               {"measure": "time logged", "value": f"{q.size * dt / 60:.1f}", "unit": "min"}]
    return rows, summary


def floor_of(groups: dict, joint_index: int = 0) -> float | None:
    """Median RMS (deg) between repeats of one stimulus on the real device: up to 3 pairs per group of equal-length runs."""
    values = []
    for runs in groups.values():
        for (ta, qa), (tb, qb) in itertools.islice(itertools.combinations(runs, 2), 3):
            if abs(ta[-1] - tb[-1]) > 0.03 * max(ta[-1], tb[-1]):
                continue
            value = pair_rms((ta, qa[:, joint_index] if qa.ndim > 1 else qa), (tb, qb[:, joint_index] if qb.ndim > 1 else qb))
            if math.isfinite(value):
                values.append(math.degrees(value))
    return float(np.median(values)) if values else None


# ------------------------------------------------------------------------------------------------------------------- UR wrist


WRIST_TITLES = {"record": "twin of record 11-10", "it2": "it2 Karnopp refit", "it3": "it3 refit", "it5": "it5 + gravity refit"}
WRIST_BOARD = {15: 1, 16: 2}  # index into refit_rig's per-board arrays (CAN 14, 15, 16)
WRIST_PARAMS = (("coulomb_nm", "Coulomb friction", "N·m", 1.0), ("static_friction_nm", "static (breakaway) friction", "N·m", 1.0),
                ("armature_kg_m2", "armature (reflected inertia)", "kg·m²", 1.0), ("viscous_nm_s_rad", "viscous friction", "N·m·s/rad", 1.0))


def ur_wrist() -> CalibrationResult:
    summary = json.loads((WRIST / "summary_real.json").read_text())
    order = summary["trend"]["order"]
    alias = {name: ("record" if name.startswith("record") else name) for name in order}
    stages = [WRIST_TITLES.get(alias[name], name) for name in order]
    scored = {alias[name]: {(r["session"], r["name"]): r for r in summary["iterations"][name]["scored"]} for name in order}
    refit = json.loads((WRIST / "refit_rig" / "it5" / "refit.json").read_text())
    multi = json.loads((WRIST / "multi" / "multi_scores.json").read_text())["coverage_real_rows"]
    delay = {can: json.loads((WRIST / "refit_rig" / f"it5_delay_scan_can{can}" / "delay_scan.json").read_text()) for can in (15, 16)}

    root = Node("ur-wrist", "UR wrist on the One Dof Test Rack", "deployment", "Deployment", "structure",
                note="CAN 14 (revolute 11) held at ~87.45° for every run (Zach's cable check)")
    arm = Node("ur-wrist/wrist", "UR wrist (CAN 15 + CAN 16)", "arm", "robot arm", "ur wrist", parent=root.id)
    tool = Node("ur-wrist/wrist/holder", "holder board #4-7 (tool)", "tool", "Tool (payload + TCP)", "tool", parent=arm.id,
                note="no tool gate yet: the wrist's runs log the joints; the holder's camera fit is not in these runs")
    joints = {can: Node(f"ur-wrist/wrist/can{can}", f"CAN {can} wrist joint (moteus servo)", "joint", "integrated_servo", "moteus servo",
                        parent=arm.id) for can in (15, 16)}

    files: dict = {}
    groups: dict[int, dict] = {15: defaultdict(list), 16: defaultdict(list)}
    cover: dict[int, list] = {15: [[], [], []], 16: [[], [], []]}
    dt_of = {}
    for (session, name), row in scored[alias[order[-1]]].items():
        gainset = Path(session).parent.name
        session_name, stem = name.split("/")
        match = re.match(r"can(\d+)_(\d+)_(.+)-[0-9a-f]+$", session_name)
        can, tape = int(match.group(1)), match.group(3)
        held_out = tape.endswith("_heldout")
        path = Path(session) / "runs" / f"{stem}.npz"
        data = np.load(path)
        t, q, qd = data["t"] - data["t"][0], data["q"], data["qd"]
        dt = float(np.median(np.diff(t))) if t.size > 1 else 0.01
        dt_of[can] = dt
        cover[can][0].append(np.degrees(q))
        cover[can][1].append(np.degrees(qd))
        cover[can][2].append(np.degrees(np.gradient(qd, t)) if t.size > 2 else np.array([]))
        groups[can][(str(path.parent), stem.split("_", 2)[-1])].append((t, q))
        label = f"CAN {can} {gainset} {session_name.split('-')[0][6:]} {stem.split('_')[0]}"
        run_slug = slug(f"ur_wrist-{label}")
        files[run_slug] = ("ur_wrist", path, WRIST_TWIN_CACHE / f"{gainset}__{session_name}__{stem}.npz", (f"can{can}",))
        values = {}
        for key, stage in zip(order, stages):
            r = scored[alias[key]].get((session, name))
            if not r:
                continue
            values[stage] = (mdeg(r["sim_vs_real"]["q_rms_mrad"]), mdeg(r["target_vs_real"]["pos_rms_mrad"]))
            phase = "before" if stage == stages[0] else ("after" if stage == stages[-1] else "")
            joints[can].errors.append({"run": label, "stage": stage, "held_out": held_out, "sim_real_deg": values[stage][0],
                                       "target_real_deg": values[stage][1], "phase": phase if held_out else ""})
        joints[can].runs.append({"run": run_slug, "label": label, "held_out": held_out, "gains": gainset, "tape": tape.removesuffix("_heldout"),
                                 "target_real_deg": _r(values.get(stages[-1], (None, None))[1]), "sim_real_deg": _r(values.get(stages[-1], (None, None))[0]),
                                 "sim_real_before_deg": _r(values.get(stages[0], (None, None))[0]), "run_view": run_view(run_slug)})

    for can, node in joints.items():
        node.floor_deg = floor_of(groups[can])
        rows, summary_rows = joint_coverage(*(np.concatenate(c) for c in cover[can]), dt_of[can])
        node.coverage, node.coverage_summary = rows, summary_rows
        index = WRIST_BOARD[can]
        for key, title, unit, scale in WRIST_PARAMS:
            node.parameters.append({"parameter": title, "unit": unit, "before": refit["base"][key][index] * scale,
                                    "after": refit["refit"][key][index] * scale, "source": "refit_rig/it5/refit.json base -> refit"})
        held = refit["held_out_before"]["pos_rms_mrad"].get(str(can))
        node.models.append({"model": "nominal (twin of record)", "rung": 0, "held_out_deg": _r(mdeg(held)), "picked": False,
                            "note": "the 11-10 twin, before the refit"})
        for rung, (name, model) in enumerate(refit["models"].items(), 1):
            node.models.append({"model": name.replace("coulomb", "Karnopp Coulomb").replace("stribeck", "Stribeck"), "rung": rung,
                                "held_out_deg": _r(mdeg(model["held_out"]["pos_rms_mrad"].get(str(can)))), "picked": name == refit["picked"],
                                "note": "it5 refit (indirect inference), held-out runs"})
        pick = delay[can]["pick"]
        node.models.append({"model": f"+ command delay {pick['command_ms']:g} ms (scan)", "rung": 9, "held_out_deg": _r(mdeg(pick["held_out_rms_mrad"])),
                            "picked": False, "note": f"refit_rig it5_delay_scan_can{can} on the it3 twin; the twin of record had 5.5 ms"})

    # the arm's workspace panel: the joint plane CAN 15 x CAN 16 (degrees) the multi-joint runs covered, 10 deg cells, real angles
    plane: dict[tuple[int, int], float] = defaultdict(float)
    for trace in sorted((WRIST / "multi" / "twin_traces").glob("*/*.npz")):
        data = np.load(trace)
        step = float(np.median(np.diff(data["t"])))
        # WHY no conversion: the multi lane writes these traces in degrees already (±140° on its columns tape)
        for a, b in zip(data["q_real_can15"], data["q_real_can16"]):
            if math.isfinite(a) and math.isfinite(b):
                plane[(math.floor(a / 10.0), math.floor(b / 10.0))] += step
    arm.coverage = [{"channel": "workspace", "x_lo": a * 10.0, "x_hi": (a + 1) * 10.0, "y_lo": b * 10.0, "y_hi": (b + 1) * 10.0,
                     "seconds": round(v, 2)} for (a, b), v in plane.items()]
    arm.parameters += [
        {"parameter": "command delay", "unit": "ms", "before": 5.5, "after": (refit["refit"].get("command_delay_s") or 0) * 1e3,
         "source": "delay scans (twin of record 5.5 ms) -> it5 refit"},
        {"parameter": "holder (hard_stop_3) mass", "unit": "kg", "before": refit["base"]["masses"]["links_kg"]["hard_stop_3"],
         "after": refit["refit"]["masses"]["links_kg"]["hard_stop_3"], "source": "it5 gravity refit"},
    ]
    both = multi["single_plus_real_multi"]
    single = multi["single_joint_real"]
    arm.coverage_summary = [
        {"measure": "joint cube (r11 held)", "value": f"{single['joint_cube_pct_of_r11_held']:.0f} % → {both['joint_cube_pct_of_r11_held']:.0f} %", "unit": "of reachable"},
        {"measure": "workspace voxels (r11 held)", "value": f"{single['workspace_pct_of_r11_held']:.0f} % → {both['workspace_pct_of_r11_held']:.0f} %", "unit": "of reachable"},
        {"measure": "holder facing", "value": f"{single['facing_pct_of_r11_held']:.0f} % → {both['facing_pct_of_r11_held']:.0f} %", "unit": "of reachable"},
        {"measure": "CAN15 x CAN16 plane", "value": f"{single['plane_pct']:.0f} % → {both['plane_pct']:.0f} %", "unit": "of reachable"},
        {"measure": "workspace panel", "value": "joint plane: x = CAN 15, y = CAN 16", "unit": "° (10° cells, multi-joint runs)"},
    ]
    notes = ["Errors: summary_real.json, every run scored on each twin on one player (bam_ur_wrist_coverage.campaign.real_summary); "
             "held out = the *_heldout tapes. Arm coverage: single-joint runs → + the multi-joint runs (multi/multi_scores.json).",
             "Floors: repeats of one stimulus within a session (sim2real.metrics.series.pair_rms).",
             "Models: refit_rig/it5/refit.json's ladder, held-out RMS per joint; the delay row is the it5 delay scan's pick."]
    return CalibrationResult("ur-wrist-2026-11-10", "UR wrist calibration · One Dof Test Rack · 2026-11-10/11", stages,
                             [root, arm, joints[15], joints[16], tool], source=str(WRIST), notes=notes, messages=_messages(files))


# ------------------------------------------------------------------------------------------------------------------- five-bar


FIVEBAR_LADDERS = {"ladder_real_101015": "stock", "ladder_real_104843": "winners", "ladder_real_113617": "winners",
                   "ladder_real_122045": "winners", "ladder_real_124755": "winners + lumped comp"}
FIVEBAR_STAGES = (("study", "study twin (nominal)", None), ("massid", "+ mass-ID gravity", ("refit_both_111322", "held_out_before")),
                  ("dynamics", "+ dynamics refit", ("refit_both_111322", "held_out_after")),
                  ("tick", "refit on the tick clock", ("refit_breakdown_123729", "held_out_before")))
FIVEBAR_MODELS = (("refit_baseline_104512", "held_out_after", "baseline: armature x4.1, viscous 0.2, no delay"),
                  ("refit_both_111322", "held_out_before", "nominal dynamics + mass-ID gravity"),
                  ("refit_both_111322", "held_out_after", "+ dynamics refit (viscous 0.1, delay 2.5 ms)"),
                  ("refit_asym_113041", "held_out_after", "+ direction-asymmetric Coulomb + backlash (rejected)"),
                  ("refit_breakdown_123729", "held_out_before", "the dynamics refit compared on the tick clock"))


def fivebar() -> CalibrationResult:
    stages = [title for _key, title, _src in FIVEBAR_STAGES]
    refits = {key: json.loads((FIVEBAR / src[0] / "refit.json").read_text())[src[1]]["per_rung"] for key, _t, src in FIVEBAR_STAGES if src}
    train = set(json.loads((FIVEBAR / "refit_both_111322" / "refit.json").read_text())["train"])
    root = Node("fivebar", "Five-bar on the One Dof Test Rack", "deployment", "Deployment", "structure",
                note="plane vertical; J1 held, not compared")
    arm = Node("fivebar/arm", "five-bar arm (J2 + C1 driven, J3 / C2 passive)", "arm", "five-bar arm", "five bar", parent=root.id)
    joints = {"j2": Node("fivebar/arm/j2", "J2 shoulder (CAN 12, moteus)", "joint", "integrated_servo", "moteus servo", parent=arm.id),
              "c1": Node("fivebar/arm/c1", "C1 crank (CAN 13, moteus)", "joint", "integrated_servo", "moteus servo", parent=arm.id)}
    tool = Node("fivebar/arm/tool", "tool point (L2 tip)", "tool", "Tool (payload + TCP)", "tool", parent=arm.id)

    files: dict = {}
    cover = {"j2": [[], [], []], "c1": [[], [], []]}
    workspace: dict[tuple[int, int], float] = defaultdict(float)
    repeats: dict = defaultdict(list)
    stop_sim, stop_target = [], []
    dt_all = []
    for ladder, gainset in FIVEBAR_LADDERS.items():
        summary = json.loads((FIVEBAR / ladder / "ladder" / "summary.json").read_text())
        for step in summary["steps"]:
            if step.get("kind") != "rung" or step.get("result") != "ran":
                continue
            real = np.load(FIVEBAR / ladder / "ladder" / step["real"])
            sim = np.load(FIVEBAR / ladder / "ladder" / step["sim"])
            t = real["t"] - real["t"][0]
            dt = float(np.median(np.diff(t)))
            dt_all.append(dt)
            q, qd = real["measured_motors"], real["measured_motor_rate"]
            for k, joint in enumerate(("j2", "c1")):
                cover[joint][0].append(np.degrees(q[:, k]))
                cover[joint][1].append(np.degrees(qd[:, k]))
                cover[joint][2].append(np.degrees(np.gradient(qd[:, k], t)))
            tool_xy = real["measured_tool"] * 1e3
            for x, y in tool_xy[np.isfinite(tool_xy).all(axis=1)]:
                workspace[(math.floor(x / WORKSPACE_CELL_MM), math.floor(y / WORKSPACE_CELL_MM))] += dt
            # the tool gate at a stop: where the commanded tool point rests (< 2 mm/s)
            target = real["target_tool"] * 1e3
            speed = np.linalg.norm(np.gradient(target, t, axis=0), axis=1)
            still = speed < 2.0
            if sim["measured_tool"].shape == real["measured_tool"].shape:
                stop_sim += list(np.linalg.norm(sim["measured_tool"][still] * 1e3 - tool_xy[still], axis=1))
            stop_target += list(np.linalg.norm(target[still] - tool_xy[still], axis=1))
            repeats[(gainset, step["name"])].append((t, q))
            rung_key = f"{ladder}:{step['name']}"
            held_out = rung_key not in train
            label = f"{ladder[-6:]} {step['speed_m_s']:.2f} m/s {step['ff_mode']}"
            run_slug = slug(f"fivebar-{label}")
            files[run_slug] = ("fivebar", FIVEBAR / ladder / "ladder" / step["real"], FIVEBAR / ladder / "ladder" / step["sim"], ("j2", "c1"))
            study_t = t if sim["t"].size == t.size else sim["t"] - sim["t"][0]
            for k, joint in enumerate(("j2", "c1")):
                study = deg(pair_rms((study_t, sim["measured_motors"][:, k]), (t, q[:, k])))
                target_real = deg(pair_rms((t, real["target_motors"][:, k]), (t, q[:, k])))
                values = {stages[0]: study}
                for key, title, _src in FIVEBAR_STAGES[1:]:
                    rung = refits[key].get(rung_key)
                    if rung:
                        values[title] = mdeg(rung[f"sim_real_{joint}_mrad"])
                for stage, value in values.items():
                    phase = "before" if stage == stages[0] else ("after" if stage == stages[-1] else "")
                    joints[joint].errors.append({"run": label, "stage": stage, "held_out": held_out, "sim_real_deg": value,
                                                 "target_real_deg": target_real, "phase": phase if held_out else ""})
                joints[joint].runs.append({"run": run_slug, "label": label, "held_out": held_out, "gains": gainset,
                                           "tape": f"coverage raster {step['ff_mode']} {step['speed_m_s']:.2f} m/s",
                                           "target_real_deg": _r(target_real), "sim_real_deg": _r(values.get(stages[-1])),
                                           "sim_real_before_deg": _r(values.get(stages[0])), "run_view": run_view(run_slug)})
    dt = float(np.median(dt_all))
    for k, (joint, node) in enumerate(joints.items()):
        node.floor_deg = floor_of({key: runs for key, runs in repeats.items() if len(runs) > 1}, k)
        node.coverage, node.coverage_summary = joint_coverage(*(np.concatenate(c) for c in cover[joint]), dt)
        for rung, (folder, which, title) in enumerate(FIVEBAR_MODELS):
            per_rung = json.loads((FIVEBAR / folder / "refit.json").read_text())[which]["per_rung"]
            values = [mdeg(r[f"sim_real_{joint}_mrad"]) for key, r in per_rung.items() if key not in train]
            node.models.append({"model": title, "rung": rung, "held_out_deg": _r(_median(values)), "picked": folder == "refit_breakdown_123729",
                                "note": f"{folder} {which}: median over its held-out rungs"})
    arm.coverage = [{"channel": "workspace", "x_lo": a * WORKSPACE_CELL_MM, "x_hi": (a + 1) * WORKSPACE_CELL_MM, "y_lo": b * WORKSPACE_CELL_MM,
                     "y_hi": (b + 1) * WORKSPACE_CELL_MM, "seconds": round(s, 2)} for (a, b), s in workspace.items()]
    arm.coverage_summary = [{"measure": "workspace panel", "value": "tool point x, y", "unit": "mm (20 mm cells)"},
                            {"measure": "tool cells visited (20 mm)", "value": str(sum(1 for s in workspace.values() if s >= 0.5)), "unit": "cells ≥ 0.5 s"},
                            {"measure": "tool speeds run", "value": "0.05 … 0.35", "unit": "m/s (raster rungs)"}]
    grav = json.loads((FIVEBAR / "massid_real_093852" / "massid" / "gravity_params.json").read_text())
    for link, values in grav["links"].items():
        arm.parameters.append({"parameter": f"{link} group mass", "unit": "kg", "before": values["nominal_mass_kg"], "after": values["mass_kg"],
                               "source": "massid gravity_params.json nominal -> identified"})
        arm.parameters.append({"parameter": f"{link} CoM y", "unit": "mm", "before": values["nominal_com_m"][1] * 1e3, "after": values["com_m"][1] * 1e3,
                               "source": "massid gravity_params.json"})
    dyn = json.loads((FIVEBAR / "refit_both_111322" / "refit.json").read_text())
    for key, title, unit, scale in (("coulomb_nm", "Coulomb friction (both drives)", "N·m", 1), ("viscous_nm_s_rad", "viscous friction (both drives)", "N·m·s/rad", 1),
                                    ("armature_scale", "armature scale", "×", 1), ("command_delay_s", "command delay", "ms", 1e3)):
        arm.parameters.append({"parameter": title, "unit": unit, "before": dyn["start"][key] * scale, "after": dyn["best"][key] * scale,
                               "source": "refit_both_111322 start -> best"})
    sim_p95 = _pct(stop_sim, 95)
    tool.gate = {"gate_mm": TOOL_GATE_MM, "sim_real_mm": sim_p95, "target_real_mm": _pct(stop_target, 95),
                 "verdict": ("pass" if sim_p95 is not None and sim_p95 <= TOOL_GATE_MM else "fail") + f" (sim→real p95 at stops ≤ {TOOL_GATE_MM:g} mm)"}
    tool.note = "the study twin's tool vs the real tool where the commanded tool point rests (< 2 mm/s), every rung"
    root.gate = tool.gate
    notes = ["Errors: the study twin from each rung's own sim (pair_rms on the tick clock); the refits from their per-rung held-out scores "
             "(refit_both / refit_breakdown). Held out = not in refit_both's train set.",
             "Floors: the 0.05 m/s gravity-ff rung run three times on the winners (ladders 104843, 113617, 122045), pair_rms per joint.",
             "Tool gate: the study twin's tool (bam_fivebar FK, as logged) against the real tool at the stops; the refits kept joint scores only."]
    return CalibrationResult("fivebar-2026-11-11", "Five-bar calibration · One Dof Test Rack · 2026-11-11", stages,
                             [root, arm, joints["j2"], joints["c1"], tool], source=str(FIVEBAR), notes=notes, messages=_messages(files))


def _r(value, digits: int = 3):
    return None if value is None or not math.isfinite(value) else round(float(value), digits)


def _median(values):
    kept = [v for v in values if v is not None and math.isfinite(v)]
    return float(np.median(kept)) if kept else None


def _pct(values, q):
    kept = [v for v in values if v is not None and math.isfinite(v)]
    return float(np.percentile(kept, q)) if kept else None
