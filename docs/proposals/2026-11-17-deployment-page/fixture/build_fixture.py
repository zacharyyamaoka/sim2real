"""The shared fixture every deployment-page proposal renders: the pendulum campaign's round 0 (as found) and round 8 (now).

Reads, never writes, the two scorecards (onedof-pendulum-scorecard/1) and sim2real's committed oracle index, and writes
`fixture.js` (window.S2R_FIXTURE, so every variant opens from file:// without a fetch).

WHY precomputed here and not in the pages: these are the numbers a production backend would compute per node (the five
questions, each metric against its gate); the proposals differ in how they SHOW them and in where the definitions LIVE
(`v*/BACKEND.md`), so all five must read identical values. The gate rule is the frozen campaign contract,
`bam_rack_twin/pendulum_goal.py` (bam_ws branch claude/1dof-rack-sim-to-real-435fc0, `cell_gates`), re-stated below and held
to each scorecard's own `goal.gates_passed` (82 and 151) by `check()`, so a drift from the contract fails the build.

Stdlib only:
    python3 -I /home/bam/sim2real/docs/proposals/2026-11-17-deployment-page/fixture/build_fixture.py
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SCORECARDS = Path("/archive/datasets/bam_rig/onedof_2026-11-15/scorecards")
ROUNDS = (("r0", SCORECARDS / "round0.json", "As found", "round 0 · before any fit"),
          ("r8", SCORECARDS / "latest_real.json", "Now", "round 8 · today"))
ORACLE = REPO / "sysid" / "results" / "index.json"
MEDIA_CACHE = Path.home() / ".cache" / "sim2real" / "media" / "scenes"

STATIONS = ("can1", "can11", "can12", "can13", "can14", "can15")
RUNGS = (0.2, 0.4, 0.6, 0.8, 0.9, 1.0)
GOAL_FRACTION = 0.9
CELL_GATES = ("target_vs_sim_stop", "sim_vs_real", "sim_predicts_tracking", "target_vs_real_tracking", "target_vs_real_stop")

QUESTIONS = (
    {"id": "floor", "n": 1, "name": "Floor", "ask": "How much does the real thing disagree with itself?"},
    {"id": "data", "n": 2, "name": "Data", "ask": "Is there enough data, in the right places?"},
    {"id": "routines", "n": 3, "name": "Routines", "ask": "Does each calibration recover a hidden truth, in sim?"},
    {"id": "twin", "n": 4, "name": "Twin", "ask": "Is held-out sim vs real within 1.5× the floor?"},
    {"id": "job", "n": 5, "name": "Job", "ask": "Does the real thing do its job (1 mm at the tip)?"},
)

# The stations as built (MOC - Sim2Real Success Criteria and Metrics §3 "The six stations"; sim2real deploy_tree titles;
# RobotDx's unit names). Tip lengths are read from each scorecard, never from here.
STATION_FACTS = {
    "can1": {"plain": "GIM43 plate, balanced tag disc", "motor": "SteadyWin GIM4305-10", "family": "GIM", "board": "moteus-c1",
             "gear": "10:1 built in", "load": "balanced tag disc", "gravity_nm": 0.0, "plate": "GIM43 plate"},
    "can14": {"plain": "GIM43 plate, balanced tag disc", "motor": "SteadyWin GIM4305-10", "family": "GIM", "board": "moteus-c1",
              "gear": "10:1 built in", "load": "balanced tag disc", "gravity_nm": 0.0, "plate": "GIM43 plate"},
    "can15": {"plain": "GIM43 plate, the small pendulum arm", "motor": "GIM-family (Kv 98.9, model unconfirmed)", "family": "GIM",
              "board": "moteus-c1", "gear": "10:1 built in (camera 10.5)", "load": "oval link carrying a second motor",
              "gravity_nm": 0.11, "plate": "GIM43 plate"},
    "can11": {"plain": "JMC60 plate, the heavy shoulder arm", "motor": "JMC 60ASM200", "family": "JMC", "board": "moteus-r4.11",
              "gear": "StepperOnline AD60-G10 10:1 planetary", "load": "1.99 kg arm", "gravity_nm": 4.4, "plate": "JMC60 plate"},
    "can12": {"plain": "JMC60 plate, balanced tag hub", "motor": "JMC 60ASM200", "family": "JMC", "board": "moteus-r4.11",
              "gear": "StepperOnline 10:1 planetary", "load": "balanced tag hub", "gravity_nm": 0.0, "plate": "JMC60 plate"},
    "can13": {"plain": "JMC60 plate, balanced stop plate", "motor": "JMC 60ASM200", "family": "JMC", "board": "moteus-r4.11",
              "gear": "StepperOnline 10:1 planetary", "load": "balanced stop plate", "gravity_nm": 0.0, "plate": "JMC60 plate"},
}

# Where each metric's DEFINITION lives today (the backend each proposal moves it to is in v*/BACKEND.md).
SRC_GOAL = "bam_rack_twin/pendulum_goal.py · Thresholds (campaign branch)"
SRC_SCORE = "bam_rack_twin/pendulum_score.py (campaign branch)"
SRC_SERVO = "sim2real cards/servo_gates.py · metrics/servo_gates.py"
SRC_ORACLE = "sim2real sysid/results/index.json (sysid oracle)"


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def le(value, limit):
    number = finite(value)
    return None if number is None else number <= limit


def cell_gates(rung: dict, t: dict) -> dict:
    """pendulum_goal.cell_gates, re-stated (the five gates of one rung)."""

    real, sim = rung.get("real") or {}, rung.get("sim") or {}
    floor, svr = finite(rung.get("floor_deg")), finite(rung.get("sim_vs_real_deg"))
    tracking = None
    if finite(real.get("tracking_rms_deg")) is not None and finite(real.get("tracking_peak_deg")) is not None:
        tracking = (real["tracking_rms_deg"] <= t["tracking_rms_deg"] and real["tracking_peak_deg"] <= t["tracking_peak_deg"]
                    and (finite(real.get("limiter_share")) or 0.0) <= t["limiter_share_max"] and not real.get("faults"))
    stop = None
    if finite(real.get("stop_tool_mm")) is not None:
        stop = real["stop_tool_mm"] <= t["stop_tool_mm"] and (le(real.get("settle_s"), t["settle_s"]) is True)
    twin = None
    if svr is not None and floor is not None and floor > 0.0:
        twin = svr <= t["sim_vs_real_floor_ratio"] * floor
    predicts = None
    if finite(sim.get("tracking_rms_deg")) is not None and finite(real.get("tracking_rms_deg")) is not None:
        allowed = max(t["sim_predicts_rel"] * real["tracking_rms_deg"], t["sim_predicts_abs_deg"])
        predicts = abs(sim["tracking_rms_deg"] - real["tracking_rms_deg"]) <= allowed
    return {"target_vs_sim_stop": le(sim.get("stop_tool_mm"), t["stop_tool_mm"]), "sim_vs_real": twin,
            "sim_predicts_tracking": predicts, "target_vs_real_tracking": tracking, "target_vs_real_stop": stop}


def gate_word(ok):
    return "pass" if ok is True else "fail" if ok is False else "not_run"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def r3(x, n=4):
    x = finite(x)
    return None if x is None else round(x, n)


def rung_rows(station: dict, t: dict) -> list[dict]:
    out = []
    by_fraction = {round(float(r["fraction"]), 3): r for r in station["rungs"]}
    for fraction in RUNGS:
        rung = by_fraction.get(round(fraction, 3)) or {}
        real, sim = rung.get("real") or {}, rung.get("sim") or {}
        floor, svr = finite(rung.get("floor_deg")), finite(rung.get("sim_vs_real_deg"))
        gates = cell_gates(rung, t) if rung else {g: None for g in CELL_GATES}
        out.append({
            "fraction": fraction,
            "speed_rad_s": r3(rung.get("peak_speed_rad_s"), 3),
            "tracking_rms_deg": r3(real.get("tracking_rms_deg")), "tracking_peak_deg": r3(real.get("tracking_peak_deg")),
            "stop_tool_mm": r3(real.get("stop_tool_mm")), "stop_tool_p95_mm": r3(real.get("stop_tool_p95_mm")),
            "settle_s": r3(real.get("settle_s"), 3), "limiter_share": r3(real.get("limiter_share")),
            "tracking_rms_tool_mm": r3(real.get("tracking_rms_tool_mm")),
            "faults": real.get("faults"), "missing": real.get("missing"),
            "sim_tracking_rms_deg": r3(sim.get("tracking_rms_deg")), "sim_stop_tool_mm": r3(sim.get("stop_tool_mm")),
            "floor_deg": r3(floor), "sim_vs_real_deg": r3(svr),
            "twin_ratio": r3(svr / floor, 3) if (svr is not None and floor) else None,
            "repeats": (rung.get("plays_by_kind") or {}).get("repeat"), "held_out": (rung.get("plays_by_kind") or {}).get("held_out"),
            "gates": {g: gate_word(v) for g, v in gates.items()},
            "tracks": bool(gates["target_vs_real_tracking"]) and bool(gates["target_vs_real_stop"]),
        })
    return out


def station_goal(rows: list[dict]) -> tuple[float, bool, int]:
    reached, still = 0.0, True
    twin = []
    for row in rows:
        if still and row["tracks"]:
            reached = row["fraction"]
        else:
            still = False
        if row["gates"]["sim_vs_real"] != "not_run":
            twin.append(row["gates"]["sim_vs_real"] == "pass")
    passed = sum(1 for row in rows for g in CELL_GATES if row["gates"][g] == "pass")
    return reached, bool(twin) and all(twin), passed


def fmt(x, digits=2):
    return "—" if x is None else f"{x:.{digits}f}"


def build_round(rid: str, path: Path, oracle: dict) -> dict:
    card = json.loads(path.read_text())
    t = card["thresholds"]
    stations = {}
    gates_passed = 0
    for sid in STATIONS:
        st = card["stations"][sid]
        rows = rung_rows(st, t)
        reached, twin_ok, passed = station_goal(rows)
        gates_passed += passed
        ch = st.get("children") or {}
        stations[sid] = {"omega_max_rad_s": st["omega_max_rad_s"], "omega_source": st.get("omega_max_source"),
                         "tip_length_m": st["tip_length_m"], "rungs": rows, "max_trackable_fraction": reached,
                         "twin_ok": twin_ok, "gates_passed": passed, "gates_total": len(RUNGS) * len(CELL_GATES),
                         "children": {k: v for k, v in ch.items() if isinstance(v, dict)}}
    return {"id": rid, "round": card["round"], "scored_utc": card["scored_utc"], "controller": card.get("controller"),
            "twin": card.get("twin"), "evidence": card.get("evidence"), "thresholds": t, "goal": card["goal"],
            "gates_passed_recomputed": gates_passed, "stations": stations, "source": str(path), "sha256": sha(path),
            "round_dir": card.get("round_dir")}


def check(rounds: dict) -> None:
    for rid, rd in rounds.items():
        want = rd["goal"]["gates_passed"]
        assert rd["gates_passed_recomputed"] == want, f"{rid}: recomputed {rd['gates_passed_recomputed']} gates, scorecard says {want}"
        for sid in STATIONS:
            assert rd["stations"][sid]["max_trackable_fraction"] == rd["goal"][f"max_trackable_fraction_{sid}"], (rid, sid)
            assert rd["stations"][sid]["twin_ok"] == rd["goal"][f"twin_ok_{sid}"], (rid, sid)


# --- the typed tree and its values ----------------------------------------------------------------------------------------

def metric(mid, name, question, unit, values, gate=None, code=None, defined=SRC_GOAL, kind="gated", note="", better="lower"):
    """One metric of one node. kind: gated (a goal gate) · counted (a gate in the 180, not in the goal) · shown (a child gate,
    shown, not gating: MOC decision 1 default) · observed (no gate) · not_observable (this rack cannot see it)."""
    return {"id": mid, "name": name, "code": code, "question": question, "unit": unit, "gate": gate, "kind": kind,
            "defined": defined, "note": note, "better": better, "values": values}


def status_of(value, gate):
    if value is None:
        return "not_run"
    if gate is None:
        return "observed"
    op, limit = gate["op"], gate["limit"]
    ok = value <= limit if op == "<=" else value >= limit if op == ">=" else abs(value) <= limit
    return "pass" if ok else "fail"


def child_metric(ch: dict, key: str) -> dict:
    c = ch.get(key) or {}
    st = c.get("status")
    return {"value": c.get("value"), "status": {"pass": "pass", "fail": "fail", "not_observable": "not_observable"}.get(st, "not_run"),
            "detail": c.get("detail") or "", "date": c.get("date"), "source": c.get("source")}


def station_nodes(sid: str, rounds: dict, oracle: dict) -> list[dict]:
    f = STATION_FACTS[sid]
    can = sid.replace("can", "CAN ")
    r0, r8 = rounds["r0"]["stations"][sid], rounds["r8"]["stations"][sid]
    tip_mm = round(r8["tip_length_m"] * 1000, 1)
    nodes = []

    def per_round(fn):
        return {rid: fn(rounds[rid]["stations"][sid], rounds[rid]) for rid in rounds}

    def at(rs, fraction, key):
        for row in rs["rungs"]:
            if row["fraction"] == fraction:
                return row[key]
        return None

    def worst_ratio(rs):
        rows = [r for r in rs["rungs"] if r["twin_ratio"] is not None]
        if not rows:
            return None, None
        worst = max(rows, key=lambda r: r["twin_ratio"])
        return worst["twin_ratio"], worst["fraction"]

    def count(rs, gate):
        cells = [r["gates"][gate] for r in rs["rungs"]]
        return sum(1 for c in cells if c == "pass"), sum(1 for c in cells if c != "not_run")

    t = rounds["r8"]["thresholds"]
    # ---- the station: a 1-DOF pendulum arm (the joint as mounted), judged at the link tip
    m = []
    m.append(metric("passes_up_to", "Tracks and stops up to", "job", "of top speed",
                    per_round(lambda rs, rd: {"value": rs["max_trackable_fraction"],
                                              "status": "pass" if rs["max_trackable_fraction"] >= GOAL_FRACTION else "fail",
                                              "detail": f"top speed {rs['omega_max_rad_s']:g} rad/s ({rs['omega_source']})"}),
                    gate={"op": ">=", "limit": GOAL_FRACTION, "text": "≥ 0.9 of top speed"}, better="higher",
                    note="the highest rung with every rung up to it passing tracking and the tip stop"))
    m.append(metric("twin_over_floor", "Twin ÷ floor, worst rung", "twin", "× floor",
                    per_round(lambda rs, rd: (lambda w: {"value": w[0], "status": "pass" if rs["twin_ok"] else ("fail" if w[0] is not None else "not_run"),
                                                         "detail": (f"worst at the {w[1]:g} rung; held-out sim vs real ÷ same-input repeat floor" if w[0] is not None else "no rung has both a floor and a held-out play")})(worst_ratio(rs))),
                    gate={"op": "<=", "limit": 1.5, "text": "≤ 1.5× at every rung"}, note="the agents' 1.5, never confirmed by Zach"))
    m.append(metric("tracking_rms_09", "Tracking RMS at 0.9 of top speed", "job", "°",
                    per_round(lambda rs, rd: {"value": at(rs, 0.9, "tracking_rms_deg"), "status": status_of(at(rs, 0.9, "tracking_rms_deg"), {"op": "<=", "limit": t["tracking_rms_deg"]}), "detail": "target vs encoder, median of the rung's plays"}),
                    gate={"op": "<=", "limit": t["tracking_rms_deg"], "text": "≤ 0.5°"}))
    m.append(metric("tracking_peak_09", "Tracking peak at 0.9 of top speed", "job", "°",
                    per_round(lambda rs, rd: {"value": at(rs, 0.9, "tracking_peak_deg"), "status": status_of(at(rs, 0.9, "tracking_peak_deg"), {"op": "<=", "limit": t["tracking_peak_deg"]}), "detail": "worst instant of the rung"}),
                    gate={"op": "<=", "limit": t["tracking_peak_deg"], "text": "≤ 1.5°"}))
    m.append(metric("tip_stop_09", "Tip stop error at 0.9 of top speed", "job", "mm",
                    per_round(lambda rs, rd: {"value": at(rs, 0.9, "stop_tool_mm"), "status": status_of(at(rs, 0.9, "stop_tool_mm"), {"op": "<=", "limit": t["stop_tool_mm"]}), "detail": f"tip length {rs['tip_length_m'] * 1000:g} mm × angle error, settled"}),
                    gate={"op": "<=", "limit": t["stop_tool_mm"], "text": "≤ 1 mm (Zach)"}))
    m.append(metric("sim_predicts", "Sim predicts tracking", "twin", "rungs",
                    per_round(lambda rs, rd: (lambda c: {"value": c[0], "of": c[1], "status": "pass" if c[1] and c[0] == c[1] else ("fail" if c[1] else "not_run"), "detail": f"{c[0]} of {c[1]} rungs within 20 % or 0.05°"})(count(rs, "sim_predicts_tracking"))),
                    gate={"op": "all", "limit": None, "text": "every rung"}, kind="counted", better="higher",
                    note="a gate in the 180 count, not in the campaign goal"))
    m.append(metric("sim_stop", "Sim's own tip stop", "job", "rungs",
                    per_round(lambda rs, rd: (lambda c: {"value": c[0], "of": c[1], "status": "pass" if c[1] and c[0] == c[1] else ("fail" if c[1] else "not_run"), "detail": f"{c[0]} of {c[1]} rungs ≤ 1 mm in sim (the controller, in sim)"})(count(rs, "target_vs_sim_stop"))),
                    gate={"op": "all", "limit": None, "text": "every rung"}, kind="counted", better="higher",
                    note="a gate in the 180 count, not in the campaign goal"))
    m.append(metric("tip_tracking_09", "Tracking at the tip, 0.9 rung", "job", "mm",
                    per_round(lambda rs, rd: {"value": at(rs, 0.9, "tracking_rms_tool_mm"), "status": "observed", "detail": "tip length × tracking RMS (MOC decision 3)"}),
                    kind="observed", defined=SRC_SCORE))
    m.append(metric("gates_passed", "Gates passed", "job", "of 30",
                    per_round(lambda rs, rd: {"value": rs["gates_passed"], "of": rs["gates_total"], "status": "observed", "detail": "5 gates × 6 rungs"}),
                    kind="observed", better="higher"))
    floor = {rid: child_metric(rounds[rid]["stations"][sid]["children"], "T1") for rid in rounds}
    data = {}
    for rid in rounds:
        rs = rounds[rid]["stations"][sid]
        played = [r for r in rs["rungs"] if r["tracking_rms_deg"] is not None]
        reps = min((r["repeats"] or 0) for r in rs["rungs"])
        held = min((r["held_out"] or 0) for r in rs["rungs"])
        ok = len(played) == len(RUNGS) and reps >= 5 and held >= 2
        data[rid] = {"value": reps, "status": "pass" if ok else "fail",
                     "detail": f"{len(played)} of 6 rungs measured · fewest {reps} repeats + {held} held-out per rung (needs 5 + 2)"}
    m.insert(0, metric("repeat_floor", "Repeat floor (T1)", "floor", "°", floor, gate={"op": "repeats", "limit": 5, "text": "≥ 5 identical repeats at every rung"},
                       code="T1", defined=SRC_SERVO, note="same-input run-to-run spread; the twin's ruler"))
    m.insert(1, metric("rungs_measured", "Fewest same-input repeats per rung", "data", "repeats", data,
                       gate={"op": ">=", "limit": 5, "text": "≥ 5 repeats + 2 held-out at all 6 rungs"}, better="higher",
                       note="coverage bins are not computed for this rig; the ladder IS its coverage"))
    oracle_row = oracle.get("pendulum_can11") if sid == "can11" else None
    if oracle_row:
        v = oracle_row["verdict"]
        routines = {"value": v["parameters_pass"], "of": v["parameters"], "status": v["status"],
                    "detail": f"{v['parameters_pass']} of {v['parameters']} hidden parameters recovered in sim, {v['metrics_pass']} of {v['metrics']} held-out factors (sysid oracle, code {oracle_row['code']}); the same result in both rounds"}
    else:
        routines = {"value": None, "status": "not_run", "detail": "no sysid oracle example for this station yet"}
    m.insert(2, metric("oracle_recovery", "Calibration recovers a hidden truth (sim)", "routines", "parameters",
                       {rid: dict(routines) for rid in rounds}, gate={"op": "all", "limit": None, "text": "every identifiable value within tolerance at 1× noise"},
                       defined=SRC_ORACLE, better="higher"))
    station = {"id": sid, "parent": "rack", "title": f"{can} · {f['plain']}", "short": can, "level": "station",
               "type": {"id": "pendulum_arm_1dof", "name": "1-DOF pendulum arm", "rm": "RigidBodyChain (1 joint)"},
               "judged_at": f"the link tip ({tip_mm:g} mm)", "unit": f"{f['board']} · {can}",
               "facts": [["tip length", f"{tip_mm:g} mm"], ["1 mm at the tip", f"{math.degrees(0.001 / r8['tip_length_m']):.2f}°"],
                         ["top speed, measured", f"{r0['omega_max_rad_s']:g} → {r8['omega_max_rad_s']:g} rad/s" if r0['omega_max_rad_s'] != r8['omega_max_rad_s'] else f"{r8['omega_max_rad_s']:g} rad/s"],
                         ["motor", f["motor"]], ["load", f["load"]]],
               "gating": True, "metrics": m, "plate": f["plate"], "family": f["family"],
               "rungs": {rid: rounds[rid]["stations"][sid]["rungs"] for rid in rounds},
               "omega": {rid: rounds[rid]["stations"][sid]["omega_max_rad_s"] for rid in rounds},
               "tip_length_m": r8["tip_length_m"], "gravity_nm": f["gravity_nm"],
               "health": {rid: {"faults": sum((r["faults"] or 0) for r in rounds[rid]["stations"][sid]["rungs"]),
                                "missing": sum((r["missing"] or 0) for r in rounds[rid]["stations"][sid]["rungs"])} for rid in rounds}}
    if r0["omega_max_rad_s"] != r8["omega_max_rad_s"]:
        station["caveat"] = (f"The ladder moved: round 0's top speed was {r0['omega_max_rad_s']:g} rad/s (the current-limit onset), round 8's is "
                             f"{r8['omega_max_rad_s']:g} rad/s, so a rung is the same fraction but a faster move now.")
    nodes.append(station)

    # ---- the integrated servo (motor + gearbox + driver + encoder as one box), judged at the output angle
    ch = {rid: rounds[rid]["stations"][sid]["children"] for rid in rounds}
    servo_m = [
        metric("T1", "Repeat floor", "floor", "°", {rid: child_metric(ch[rid], "T1") for rid in rounds}, code="T1", defined=SRC_SERVO, kind="shown",
               gate={"op": "repeats", "limit": 5, "text": "≥ 5 identical repeats"}),
        metric("T2", "Twin ÷ floor at the output", "twin", "× floor", {rid: child_metric(ch[rid], "T2") for rid in rounds}, code="T2", defined=SRC_SERVO,
               kind="shown", gate={"op": "<=", "limit": 1.5, "text": "≤ 1.5× the floor"},
               note="on this rack the output IS the arm's joint: the same number as the arm's twin ÷ floor"),
        metric("T4", "Stop error at the output", "job", "°", {rid: {"value": None, "status": "not_run", "detail": "not in this round's children block; the arm's tip stop stands in"} for rid in rounds},
               code="T4", defined=SRC_SERVO, kind="shown", gate={"op": "<=", "limit": None, "text": "its share of the 1 mm tool gate"}),
    ]
    nodes.append({"id": f"{sid}/servo", "parent": sid, "title": f"Integrated servo · {f['motor']} + {f['gear']}", "short": "Integrated servo",
                  "level": "servo", "type": {"id": "integrated_servo", "name": "Integrated servo", "rm": "robot_models.IntegratedServo"},
                  "judged_at": "the output angle (rotor encoder ÷ ratio)", "unit": f"{f['board']} · {can}", "gating": False, "metrics": servo_m,
                  "facts": [["made of", "motor + gearbox + driver + encoder"], ["seen as", "one box: the encoder is on the rotor"]]})
    # ---- its parts
    nodes.append({"id": f"{sid}/servo/driver", "parent": f"{sid}/servo", "title": f"Driver · {f['board']} (FOC board)", "short": "Driver",
                  "level": "part", "type": {"id": "foc_controller", "name": "FOC controller", "rm": "robot_models.FocController"},
                  "judged_at": "its q-current", "unit": f"{f['board']} · {can}", "gating": False,
                  "metrics": [metric("T3", "Current fidelity", "twin", "× scatter", {rid: child_metric(ch[rid], "T3") for rid in rounds}, code="T3",
                                     defined=SRC_SERVO, kind="shown", gate={"op": "<=", "limit": 2.0, "text": "≤ 2× run-to-run scatter"},
                                     note="last known from late-October runs, before the 24 V re-commissioning: the same number in both rounds"),
                              metric("limiter_share", "Limiter share", "job", "of rows", {rid: child_metric(ch[rid], "limiter_share") for rid in rounds},
                                     defined=SRC_GOAL, kind="shown", gate={"op": "<=", "limit": 0.02, "text": "≤ 2 % of rows"})],
                  "facts": [["board", f["board"]], ["reports", "its own q-current, so current fidelity is measurable"]]})
    nodes.append({"id": f"{sid}/servo/motor", "parent": f"{sid}/servo", "title": f"Motor · {f['motor']}", "short": "Motor", "level": "part",
                  "type": {"id": "bldc_motor", "name": "BLDC motor", "rm": "robot_models.BldcMotor"}, "judged_at": "the shaft (seen only through the servo)",
                  "unit": f"{f['board']} · {can}", "gating": False,
                  "metrics": [metric("T7", "Envelope: top speed, twin vs measured", "twin", "%", {rid: child_metric(ch[rid], "T7") for rid in rounds}, code="T7",
                                     defined=SRC_SERVO, kind="shown", gate={"op": "abs", "limit": 5.0, "text": "within 5 %"}),
                              metric("T6", "Torque per amp (Kt)", "twin", "%", {rid: child_metric(ch[rid], "T6") for rid in rounds}, code="T6", defined=SRC_SERVO,
                                     kind="not_observable", gate={"op": "abs", "limit": 5.0, "text": "within 5 % against a known mass"}),
                              metric("T8", "Winding temperature", "twin", "°C", {rid: child_metric(ch[rid], "T8") for rid in rounds}, code="T8", defined=SRC_SERVO,
                                     kind="not_observable", gate={"op": "abs", "limit": 5.0, "text": "within 5 °C of a thermocouple"})],
                  "facts": [["motor", f["motor"]], ["family", f["family"]]]})
    nodes.append({"id": f"{sid}/servo/gearbox", "parent": f"{sid}/servo", "title": f"Gearbox · {f['gear']}", "short": "Gearbox", "level": "part",
                  "type": {"id": "gearbox", "name": "Gearbox", "rm": "robot_models.Gearbox"}, "judged_at": "output vs input angle (not visible here)",
                  "unit": f"{f['board']} · {can}", "gating": False,
                  "metrics": [metric("T5", "Output lost motion (backlash)", "twin", "°", {rid: child_metric(ch[rid], "T5") for rid in rounds}, code="T5",
                                     defined=SRC_SERVO, kind="not_observable", gate={"op": "<=", "limit": 0.033, "text": "CI half-width ≤ 0.033°"})],
                  "facts": [["ratio", f["gear"]]]})
    nodes.append({"id": f"{sid}/servo/encoder", "parent": f"{sid}/servo", "title": "Encoder · the board's rotor encoder", "short": "Encoder", "level": "part",
                  "type": {"id": "encoder", "name": "Encoder", "rm": "robot_models.Encoder"}, "judged_at": "its own reading",
                  "unit": f"{f['board']} · {can}", "gating": False,
                  "metrics": [metric("homing_repeat", "Homing repeatability", "floor", "°", {rid: {"value": None, "status": "not_run", "detail": "needs ≥ 5 homings; not run on the pendulum rack"} for rid in rounds},
                                     defined=SRC_SERVO, kind="shown", gate=None)],
                  "facts": [["noise", "inside the station's repeat floor (T1)"]]})
    nodes.append({"id": f"{sid}/link", "parent": sid, "title": f"Link + load · {f['load']}", "short": "Link + load", "level": "part",
                  "type": {"id": "rigid_link", "name": "Link + load", "rm": "RigidBodyChain link"}, "judged_at": "through the arm's gates",
                  "unit": "", "gating": False, "metrics": [],
                  "facts": [["tip length", f"{tip_mm:g} mm"], ["gravity term m·g·L", f"{f['gravity_nm']:g} N·m" if f["gravity_nm"] else "≈ 0 (balanced)"],
                            ["gates", "none of its own: its m·g·L and inertia are twin terms"]]})
    return nodes


def questions_for(node: dict, rid: str) -> dict:
    """Each question's status at this node in this round. A goal gate that fails makes it fail (red); a child gate that is
    shown, not gating, makes it watch (amber); a counted gate (in the 180, not in the goal) never changes the status, it is
    counted as a miss beside it; observed and not-observable metrics never fail a question."""
    out = {}
    for q in QUESTIONS:
        ms = [m for m in node["metrics"] if m["question"] == q["id"]]
        if not ms:
            out[q["id"]] = {"status": "none", "metric": None, "misses": 0}
            continue
        sts = [(m, m["values"][rid]) for m in ms]
        gated = [(m, v) for m, v in sts if m["kind"] == "gated" and v["status"] in ("pass", "fail")]
        shown = [(m, v) for m, v in sts if m["kind"] == "shown" and v["status"] in ("pass", "fail")]
        misses = [m["id"] for m, v in sts if m["kind"] == "counted" and v["status"] == "fail"]
        if any(v["status"] == "fail" for m, v in gated):
            status = "fail"
        elif any(v["status"] == "fail" for m, v in shown):
            status = "watch"
        elif gated or shown:
            status = "pass"
        elif any(m["kind"] == "counted" and v["status"] == "pass" for m, v in sts):
            status = "pass"
        elif any(v["status"] == "not_observable" for m, v in sts):
            status = "not_observable"
        elif any(v["status"] == "observed" for m, v in sts):
            status = "observed"
        else:
            status = "not_run"
        lead = (next((x for x in gated + shown if x[1]["status"] == "fail"), None) or next(iter(gated + shown), None) or sts[0])
        out[q["id"]] = {"status": status, "metric": lead[0]["id"], "misses": len(misses), "missed": misses}
    return out


def build() -> dict:
    oracle_doc = json.loads(ORACLE.read_text())
    oracle = {row["example"]: row for row in oracle_doc["examples"]}
    rounds = {rid: build_round(rid, path, oracle) for rid, path, _, _ in ROUNDS}
    check(rounds)
    nodes = []
    for sid in STATIONS:
        nodes.extend(station_nodes(sid, rounds, oracle))
    # cameras: in the deployment, flag only (Zach 11-11: gates from joint encoders, ArUco a flag)
    for serial, plate in (("218622276036", "JMC60 plates"), ("218622274411", "GIM43 plate")):
        nodes.append({"id": f"cam-{serial}", "parent": "rack", "title": f"Depth camera · RealSense D405 {serial} ({plate})", "short": f"D405 {serial[-4:]}",
                      "level": "sensor", "type": {"id": "depth_camera", "name": "Depth camera", "rm": "robot_models.DepthCamera"},
                      "judged_at": "a flag only: gates read the joint encoders (Zach, 11-11)", "unit": f"D405 {serial}", "gating": False, "metrics": [],
                      "facts": [["role", "ArUco tags on the links, a cross-check"], ["in this round", "no camera metric scored"]]})
    # the deployment
    dep_m = []
    for rid in rounds:
        pass
    def per_round(fn):
        return {rid: fn(rounds[rid]) for rid in rounds}
    dep_m.append(metric("goal_met", "Campaign goal met", "verdict", "", per_round(lambda rd: {"value": int(rd["goal"]["goal_met"]), "status": "pass" if rd["goal"]["goal_met"] else "fail",
                                                                                          "detail": "every station tracks to ≥ 0.9 of top speed AND its twin passes at every rung"}),
                        gate={"op": ">=", "limit": 1, "text": "all six stations"}, better="higher"))
    dep_m.append(metric("stations_tracking", "Stations tracking to 0.9", "job", "stations",
                        per_round(lambda rd: (lambda n: {"value": n, "of": 6, "status": "pass" if n == 6 else "fail", "detail": "max trackable fraction ≥ 0.9"})(sum(1 for s in STATIONS if rd["goal"][f"max_trackable_fraction_{s}"] >= GOAL_FRACTION))),
                        gate={"op": ">=", "limit": 6, "text": "6 of 6"}, better="higher"))
    dep_m.append(metric("stations_twinned", "Stations twinned", "twin", "stations",
                        per_round(lambda rd: (lambda n: {"value": n, "of": 6, "status": "pass" if n == 6 else "fail", "detail": "twin ≤ 1.5× floor at every measured rung"})(sum(1 for s in STATIONS if rd["goal"][f"twin_ok_{s}"]))),
                        gate={"op": ">=", "limit": 6, "text": "6 of 6"}, better="higher"))
    dep_m.append(metric("floors_known", "Stations with a repeat floor", "floor", "stations",
                        per_round(lambda rd: (lambda n: {"value": n, "of": 6, "status": "pass" if n == 6 else "fail", "detail": "T1: ≥ 5 repeats at every rung"})(sum(1 for s in STATIONS if (rd["stations"][s]["children"].get("T1") or {}).get("status") == "pass"))),
                        gate={"op": ">=", "limit": 6, "text": "6 of 6"}, defined=SRC_SERVO, better="higher"))
    dep_m.append(metric("data_complete", "Stations with the full ladder played", "data", "stations",
                        per_round(lambda rd: (lambda n: {"value": n, "of": 6, "status": "pass" if n == 6 else "fail", "detail": "6 rungs × (5 repeats + 2 held-out)"})(
                            sum(1 for s in STATIONS if all(r["tracking_rms_deg"] is not None and (r["repeats"] or 0) >= 5 and (r["held_out"] or 0) >= 2 for r in rd["stations"][s]["rungs"])))),
                        gate={"op": ">=", "limit": 6, "text": "6 of 6"}, better="higher"))
    dep_m.append(metric("oracle_stations", "Stations with a sim oracle", "routines", "stations",
                        {rid: {"value": 1, "of": 6, "status": "observed", "detail": "only CAN 11 has a sysid example (8 of 8 recovered)"} for rid in rounds},
                        kind="observed", defined=SRC_ORACLE, better="higher"))
    dep_m.append(metric("gates_passed", "Gates passed", "job", "of 180",
                        per_round(lambda rd: {"value": rd["goal"]["gates_passed"], "of": rd["goal"]["gates_total"], "status": "observed", "detail": "5 gates × 6 rungs × 6 stations"}),
                        kind="observed", better="higher"))
    rack = {"id": "rack", "parent": None, "title": "One Dof Test Rack · pendulum campaign", "short": "One Dof Test Rack", "level": "deployment",
            "type": {"id": "deployment", "name": "Deployment", "rm": "sim2real Deployment"}, "judged_at": "the campaign goal",
            "unit": "fdcanusb 272813EF · 24 V", "gating": True, "metrics": dep_m,
            "facts": [["where", "Zach's bench at home"], ["adapter", "fdcanusb 272813EF, 24 V"], ["stations", "6 single-joint pendulums: 3 GIM43, 3 JMC60"],
                      ["ladder", "0.2 · 0.4 · 0.6 · 0.8 · 0.9 · 1.0 of each station's top speed"]]}
    nodes.insert(0, rack)
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        n["children"] = [c["id"] for c in nodes if c["parent"] == n["id"]]
    for n in nodes:
        n["questions"] = {rid: questions_for(n, rid) for rid in rounds}
    # verdict per node per round: the first failing question in order, else pass
    for n in nodes:
        n["verdict"] = {}
        for rid in rounds:
            qs = n["questions"][rid]
            first = next((q["id"] for q in QUESTIONS if qs[q["id"]]["status"] == "fail"), None)
            watch = next((q["id"] for q in QUESTIONS if qs[q["id"]]["status"] == "watch"), None)
            judged = [qs[q["id"]]["status"] for q in QUESTIONS if qs[q["id"]]["status"] in ("pass", "fail", "watch")]
            status = "fail" if first else ("watch" if watch else ("pass" if judged else "none"))
            n["verdict"][rid] = {"status": status, "first": first or watch}
    # roll-up: what is under each node (worst child)
    order = {"fail": 4, "watch": 2, "pass": 1, "none": 0}

    def rollup(nid, rid):
        node = by_id[nid]
        worst = node["verdict"][rid]["status"]
        for c in node["children"]:
            w = rollup(c, rid)
            if order.get(w, 0) > order.get(worst, 0):
                worst = w
        node.setdefault("rollup", {})[rid] = worst
        return worst
    for rid in rounds:
        rollup("rack", rid)

    deployments = [{"id": "one-dof-test-rack", "title": "One Dof Test Rack", "kind": "physical", "where": "Zach's bench at home",
                    "summary": "Six single-joint pendulums on one fdcanusb at 24 V, each run up a speed ladder against its own twin.",
                    "render": "media/one-dof-test-rack.jpg", "root": "rack", "in_fixture": True,
                    "headline": {rid: {"goal_met": rounds[rid]["goal"]["goal_met"], "gates_passed": rounds[rid]["goal"]["gates_passed"],
                                       "gates_total": rounds[rid]["goal"]["gates_total"]} for rid in rounds}}]
    for row in oracle_doc["examples"]:
        v = row["verdict"]
        deployments.append({"id": row["example"], "title": row["title"], "kind": "virtual", "where": row.get("subtitle", ""),
                            "summary": f"sysid oracle: {v['parameters_pass']} of {v['parameters']} hidden parameters recovered, "
                                       f"{v['metrics_pass']} of {v['metrics']} held-out factors",
                            "render": f"media/{row['example']}.jpg", "root": None, "in_fixture": False, "verdict": v["status"]})
    return {
        "schema": "sim2real.deployment-page-fixture/1",
        "built_by": "docs/proposals/2026-11-17-deployment-page/fixture/build_fixture.py",
        "rounds": [{"id": rid, "round": rounds[rid]["round"], "label": label, "long": long, "scored_utc": rounds[rid]["scored_utc"],
                    "controller": rounds[rid]["controller"], "twin": rounds[rid]["twin"], "source": rounds[rid]["source"],
                    "sha256": rounds[rid]["sha256"], "round_dir": rounds[rid]["round_dir"]} for rid, _, label, long in ROUNDS],
        "thresholds": rounds["r8"]["thresholds"],
        "questions": list(QUESTIONS),
        "deployments": deployments,
        "root": "rack",
        "nodes": nodes,
        "oracle_source": str(ORACLE.relative_to(REPO)),
    }


def copy_media(fixture: dict) -> None:
    out = HERE / "media"
    out.mkdir(exist_ok=True)
    for dep in fixture["deployments"]:
        src = MEDIA_CACHE / f"{dep['id']}.jpg"
        dst = out / f"{dep['id']}.jpg"
        if not src.is_file():
            dep["render"] = None
            continue
        # WHY downscaled: the MuJoCo renders are regenerable cache (tools/build_media.py); 640 px is enough for a card
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf", "scale=640:-2", "-q:v", "5", str(dst)], check=True)
    rack = MEDIA_CACHE / "one-dof-test-rack.jpg"
    if rack.is_file():  # the full-size MuJoCo render of the rack's cad2robot payload, for the 3D view's "CAD render" toggle
        shutil.copyfile(rack, out / "one-dof-test-rack-full.jpg")


def main() -> None:
    fixture = build()
    copy_media(fixture)
    (HERE / "fixture.js").write_text("// GENERATED by build_fixture.py from the two pendulum scorecards; do not edit.\nwindow.S2R_FIXTURE = "
                                     + json.dumps(fixture, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    r0, r8 = fixture["rounds"]
    print(f"fixture: {len(fixture['nodes'])} nodes, {len(fixture['deployments'])} deployments; "
          f"gates r0 {82} / r8 {151} held to the scorecards; {r0['source']} · {r8['source']}")


if __name__ == "__main__":
    main()
