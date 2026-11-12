"""The wrist's one-click calibration as sim2real.result's page: the description's typed tree (rig -> wrist -> CAN 14 / 15 / 16 -> the
holder), each joint with its held-out runs before (the description's nominal twin) and after (the fitted twin), its floor (the sim's own
repeat spread), its parameters (nominal -> recovered, beside the hidden truth and the tolerance), and the holder with the 1 mm tool gate.

Every number on the page is in degrees, arcminutes, milliseconds or millimetres (sim2real.result's rule); the calibration keeps SI.
"""

from __future__ import annotations

import math

import numpy as np

from sim2real import rig as seam
from sim2real.result import CalibrationResult, Node

STAGES = ["nominal (the description)", "fitted (one click)"]
DISPLAY_UNIT = {"deg": "°", "arcmin": "′", "ms": "ms", "mm": "mm"}


def _shown(value, display):
    if value is None:
        return None
    scale = seam.DISPLAY[display][0]
    return float(value) * scale


def _parameter_rows(rows):
    out = []
    for r in rows:
        tol = r["tolerance"]
        out.append({"parameter": r["title"], "key": r["key"], "unit": DISPLAY_UNIT.get(r["display"], r["unit"]),
                    "before": _shown(r["nominal"], r["display"]), "after": _shown(r["recovered"], r["display"]),
                    "truth": _shown(r["true"], r["display"]),
                    "tolerance": None if tol is None else (f"{tol['value'] * 100:g} %" if tol["kind"] == "rel" else seam.shown(tol["value"], r["display"], r["unit"])),
                    "verdict": "pass" if r["pass"] else ("FAIL" if r["pass"] is False else "not identified"),
                    "source": r["routine"] or r["why_not"]})
    return out


def build(rig, description, calibration, report, state) -> CalibrationResult:
    from . import rig as wr  # noqa: PLC0415

    held = state.get("held_out", {})
    measured = held.get("measured", {})
    root = Node("rig", description.title, "deployment", "Deployment", "structure",
                note=f"sim oracle: {calibration.noise.summary()}; the world is world.json's sealed truth, never read by a fit")
    wrist = Node("rig/wrist", "UR wrist (CAN 14 + 15 + 16)", "arm", "rigid_body_chain", "arm_subassembly", parent=root.id,
                 note="CAN 14 held by Zach's cable rule: its terms are not identified")
    rows = calibration.rows
    wrist.parameters = _parameter_rows([r for r in rows if r["key"].startswith("wrist.")])
    joints = {}
    for can in wr.CANS:
        joint = wr.INSTANCE[can]
        node = Node(f"rig/wrist/{joint}", f"CAN {can} wrist joint (moteus servo){' — held' if can not in wr.MOVING else ''}", "joint",
                    "integrated_servo", "moteus_servo", parent=wrist.id)
        node.parameters = _parameter_rows([r for r in rows if r["key"].startswith(f"{joint}.")])
        floor = report.floor.get(joint)
        node.floor_deg = None if floor is None else math.degrees(floor)
        for label, stage in (("nominal", STAGES[0]), ("fitted", STAGES[1])):
            error = report.errors[label].get(joint)
            node.models.append({"model": stage, "rung": 0 if label == "nominal" else 1,
                                "held_out_deg": None if error is None else round(math.degrees(error), 4), "picked": label == "fitted",
                                "note": f"held-out RMS of the board's angle; {report.ratios[label].get(joint) or 0:.3g}x the floor" if error is not None else ""})
        for run, rec in sorted(measured.items()):
            if wr.INSTANCE[rec["can"]] != joint:
                continue
            target = np.asarray(rec["commands"]["board_target"], float)
            keep = np.isfinite(target)
            target_real = math.degrees(float(np.sqrt(np.mean((target[keep] - np.asarray(rec["q"])[keep]) ** 2)))) if keep.any() else None
            values = {}
            for label, stage in (("nominal", STAGES[0]), ("fitted", STAGES[1])):
                e = report.per_run[label].get(run, {}).get(joint)
                values[stage] = None if e is None else math.degrees(e)
                node.errors.append({"run": run, "stage": stage, "held_out": True, "sim_real_deg": values[stage], "target_real_deg": target_real,
                                    "phase": "before" if label == "nominal" else "after"})
            floor_run = report.per_run["floor"].get(run, {}).get(joint)
            node.runs.append({"run": run.replace("/", "-"), "label": run, "held_out": True, "gains": "ram", "tape": run.split("/", 1)[1],
                              "target_real_deg": None if target_real is None else round(target_real, 4),
                              "sim_real_deg": None if values[STAGES[1]] is None else round(values[STAGES[1]], 4),
                              "sim_real_before_deg": None if values[STAGES[0]] is None else round(values[STAGES[0]], 4),
                              "floor_deg": None if floor_run is None else round(math.degrees(floor_run), 4), "run_view": None})
        if can not in wr.MOVING:
            node.note = "held (Zach's cable rule): no routine moves it, no held-out run scores it"
        joints[can] = node
    tool = Node("rig/wrist/holder", "holder (the tool: its first ArUco board's origin)", "tool", "Tool (payload + TCP)", "tool", parent=wrist.id)
    fitted_tool = report.tool_stop_m.get("fitted")
    if fitted_tool is not None:
        gate_mm = seam.TOOL_GATE_M * 1e3
        tool.gate = {"gate_mm": gate_mm, "sim_real_mm": fitted_tool * 1e3,
                     "target_real_mm": None if report.tool_stop_m.get("floor") is None else report.tool_stop_m["floor"] * 1e3,
                     "verdict": ("pass" if fitted_tool * 1e3 <= gate_mm else "fail") + f" (twin vs world p95 at stops ≤ {gate_mm:g} mm)"}
        tool.note = (f"the fitted twin's tool vs the world's where the command rests, p95 {fitted_tool * 1e3:.3f} mm; the nominal twin's "
                     f"{(report.tool_stop_m.get('nominal') or float('nan')) * 1e3:.1f} mm; two draws of the world {(report.tool_stop_m.get('floor') or float('nan')) * 1e3:.3f} mm")
        root.gate = tool.gate
    notes = [f"Routines, in order: {', '.join(step['routine'] for step in calibration.routines)} ({calibration.seconds:.0f} s).",
             f"Recovered {sum(r['pass'] is True for r in rows)}/{sum(r['pass'] is not None for r in rows)} identified values within tolerance of the "
             f"hidden truth; not identified: {len(calibration.unidentified)} ({'; '.join(sorted({r['why_not'] for r in calibration.unidentified}))}).",
             "Floors: the sim's own repeat spread, two noise draws of every held-out run (sim2real.rig, eval_twin).",
             "Before = the description's nominal twin replaying each held-out run's commands; after = the fitted twin."]
    return CalibrationResult(f"{rig.name}-one-click", f"{description.title} · one-click calibration (sim oracle)", list(STAGES),
                             [root, wrist, joints[14], joints[15], joints[16], tool], source=f"sysid/examples/{rig.name}", notes=notes)
