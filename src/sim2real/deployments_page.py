"""The Deployments page's data for the One Dof Test Rack: the pendulum campaign's scorecards in, its typed tree out, every node with its
metrics per round (round 0 as found, the latest round now) and the five-question verdicts (sim2real.verdicts).

Zach (Daily Note 2026-11-17, "# What is required for me to actually get this working?"): "Even before I fit any data. let me run the
pendulum As it currently it as understand the performance"; "When I click into each deployment I should bring up the 3D viewer of that
deployment AND the tree should be the typed component tree. then If I click on any of the things in that tree than I can see the data
relevant to that level"; "on the part page I want to see basically the current value of its metrics and gates". And, for the two groups
every node page shows apart: "Performance is real/sim vs target. Fidelity is real vs sim."

Round 0 (`round0.json`, scored 2026-11-15) is the controller as found and the twin unfitted: the "as it currently is". "Now" is
`latest_real.json`, which the campaign's scorer rewrites every round (round 8 on 2026-11-17, round 9 on 2026-11-18), labelled from its own
`round` and `scored_utc`, never from a number written here (Zach: "open up that deployment and at a glance see exactly the current
state"). All are onedof-pendulum-scorecard/1 files the campaign's scorer wrote; this module reads them, never writes them.

WHY the cell gates are re-stated here and not imported: the frozen campaign contract is bam_rack_twin/pendulum_goal.py (`Thresholds`,
`cell_gates`) on bam_ws's campaign branch, which sim2real does not import; the five gates below are its rule, the gate NUMBERS are each
scorecard's own `thresholds`, and check() holds the re-scored totals to the scorecard's own goal block (82 of 180 in round 0, 151 in round 8,
153 in round 9), so a drift from
the contract fails the build. Promoted from the proposal round's fixture builder (docs/proposals/2026-11-17-deployment-page/fixture/
build_fixture.py), which stays as the proposals' frozen input. The model-free metric functions themselves moving to robot_models (Zach's
"folder called metrics") is a later step; this module only reads the numbers the campaign's scorer computed.

Each metric carries `family`: performance (real or sim vs the target: does it do the job), fidelity (real vs sim: does the twin match),
or evidence (the ruler and the data the other two stand on: the repeat floor, the data, the routines).

    python -m sim2real.deployments_page --out /tmp/page.json [--now round8.json]    (stdlib only; PYTHONPATH=src from a checkout)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from . import paths, verdicts


def _deg_per_s(rad_per_s: float) -> str:
    """An angular speed for display. WHY: Zach reads angles in degrees, never rad (feedback_angles_in_degrees); data stays SI."""
    return f"{math.degrees(rad_per_s):.0f} °/s"


SCHEMA = "sim2real.deployments-page/1"
DEPLOYMENT = "one-dof-test-rack"
REPO = Path(__file__).resolve().parents[2]
SCORECARDS = paths.RIG_DATA / "onedof_2026-11-15" / "scorecards"
# the page's two columns. "Now" is the campaign's latest scorecard, whichever round that is; build(now=...) pins another (the tests pin
# round8.json, the round their numbers were written against)
AS_FOUND_FILE = "round0.json"
NOW_FILE = "latest_real.json"
AS_FOUND = "r0"
# WHY "r8" means "now", whatever round it holds: the id was round 8's when the page was written, and the workbench's js, its URLs
# (?round=r0, the default dropped) and the tests key on it; every label reads the round's own number from its scorecard instead
NOW = "r8"
ORACLE = REPO / "sysid" / "results" / "index.json"
# the deployments sim2real knows, with each one's W&B project when it has one (wandb_links)
REGISTRY = REPO / "app" / "registry.json"

STATIONS = ("can1", "can11", "can12", "can13", "can14", "can15")
RUNGS = (0.2, 0.4, 0.6, 0.8, 0.9, 1.0)
GOAL_FRACTION = 0.9
CELL_GATES = ("target_vs_sim_stop", "sim_vs_real", "sim_predicts_tracking", "target_vs_real_tracking", "target_vs_real_stop")

# The stations as built (MOC - Sim2Real Success Criteria and Metrics §3 "The six stations"; sim2real deploy_tree titles; RobotDx's unit
# names). Tip lengths come from each scorecard, never from here.
STATION_FACTS = {
    "can1": {"plain": "GIM43 plate, balanced tag disc", "motor": "SteadyWin GIM4305-10", "family": "GIM", "board": "moteus-c1",
             "gear": "10:1 built in", "load": "balanced tag disc", "gravity_nm": 0.0, "plate": "GIM43 plate"},
    "can11": {"plain": "JMC60 plate, the heavy shoulder arm", "motor": "JMC 60ASM200", "family": "JMC", "board": "moteus-r4.11",
              "gear": "StepperOnline AD60-G10 10:1 planetary", "load": "1.99 kg arm", "gravity_nm": 4.4, "plate": "JMC60 plate"},
    "can12": {"plain": "JMC60 plate, balanced tag hub", "motor": "JMC 60ASM200", "family": "JMC", "board": "moteus-r4.11",
              "gear": "StepperOnline 10:1 planetary", "load": "balanced tag hub", "gravity_nm": 0.0, "plate": "JMC60 plate"},
    "can13": {"plain": "JMC60 plate, balanced stop plate", "motor": "JMC 60ASM200", "family": "JMC", "board": "moteus-r4.11",
              "gear": "StepperOnline 10:1 planetary", "load": "balanced stop plate", "gravity_nm": 0.0, "plate": "JMC60 plate"},
    "can14": {"plain": "GIM43 plate, balanced tag disc", "motor": "SteadyWin GIM4305-10", "family": "GIM", "board": "moteus-c1",
              "gear": "10:1 built in", "load": "balanced tag disc", "gravity_nm": 0.0, "plate": "GIM43 plate"},
    "can15": {"plain": "GIM43 plate, the small pendulum arm", "motor": "GIM-family (Kv 98.9, model unconfirmed)", "family": "GIM",
              "board": "moteus-c1", "gear": "10:1 built in (camera 10.5)", "load": "oval link carrying a second motor",
              "gravity_nm": 0.11, "plate": "GIM43 plate"},
}

# Where each metric's DEFINITION lives today (the page's "Defined in" column)
SRC_GOAL = "bam_rack_twin/pendulum_goal.py · Thresholds (campaign branch)"
SRC_SCORE = "bam_rack_twin/pendulum_score.py (campaign branch)"
SRC_SERVO = "sim2real cards/servo_gates.py · metrics/servo_gates.py"
SRC_ORACLE = "sim2real sysid/results/index.json (sysid oracle)"
SRC_ROLLUP = "sim2real deployments_page.py (roll-up of the stations)"

PERFORMANCE, FIDELITY, EVIDENCE = "performance", "fidelity", "evidence"


# ---- small helpers ----------------------------------------------------------------------------------------------------------------

def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def le(value, limit):
    number = finite(value)
    return None if number is None else number <= limit


def rounded(x, n=4):
    x = finite(x)
    return None if x is None else round(x, n)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_word(ok):
    return "pass" if ok is True else "fail" if ok is False else "not_run"


def status_of(value, gate):
    if value is None:
        return "not_run"
    if gate is None:
        return "observed"
    op, limit = gate["op"], gate["limit"]
    ok = value <= limit if op == "<=" else value >= limit if op == ">=" else abs(value) <= limit
    return "pass" if ok else "fail"


# ---- the campaign's rule: five gates per rung --------------------------------------------------------------------------------------

def cell_gates(rung: dict, t: dict) -> dict:
    """pendulum_goal.cell_gates, re-stated: the five gates of one rung, each True, False or None (not measured)."""
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


def rung_rows(station: dict, t: dict) -> list[dict]:
    out = []
    by_fraction = {round(float(r["fraction"]), 3): r for r in station["rungs"]}
    for fraction in RUNGS:
        rung = by_fraction.get(round(fraction, 3)) or {}
        real, sim = rung.get("real") or {}, rung.get("sim") or {}
        floor, svr = finite(rung.get("floor_deg")), finite(rung.get("sim_vs_real_deg"))
        gates = cell_gates(rung, t) if rung else {g: None for g in CELL_GATES}
        plays = rung.get("plays_by_kind") or {}
        out.append({
            "fraction": fraction, "speed_rad_s": rounded(rung.get("peak_speed_rad_s"), 3),
            "tracking_rms_deg": rounded(real.get("tracking_rms_deg")), "tracking_peak_deg": rounded(real.get("tracking_peak_deg")),
            "stop_tool_mm": rounded(real.get("stop_tool_mm")), "stop_tool_p95_mm": rounded(real.get("stop_tool_p95_mm")),
            "stop_tool_max_mm": rounded(real.get("stop_tool_max_mm")), "stops": real.get("stops"),
            "settle_s": rounded(real.get("settle_s"), 3), "limiter_share": rounded(real.get("limiter_share")),
            "tracking_rms_tool_mm": rounded(real.get("tracking_rms_tool_mm")), "faults": real.get("faults"), "missing": real.get("missing"),
            "sim_tracking_rms_deg": rounded(sim.get("tracking_rms_deg")), "sim_stop_tool_mm": rounded(sim.get("stop_tool_mm")),
            "floor_deg": rounded(floor), "sim_vs_real_deg": rounded(svr),
            "twin_ratio": rounded(svr / floor, 3) if (svr is not None and floor) else None,
            "repeats": plays.get("repeat"), "held_out": plays.get("held_out"),
            "gates": {g: gate_word(v) for g, v in gates.items()},
            "tracks": bool(gates["target_vs_real_tracking"]) and bool(gates["target_vs_real_stop"]),
        })
    return out


def station_goal(rows: list[dict]) -> tuple[float, bool, int]:
    """(the highest rung with every rung up to it tracking and stopping, twin passes at every measured rung, gates passed)."""
    reached, still, twin = 0.0, True, []
    for row in rows:
        if still and row["tracks"]:
            reached = row["fraction"]
        else:
            still = False
        if row["gates"]["sim_vs_real"] != "not_run":
            twin.append(row["gates"]["sim_vs_real"] == "pass")
    passed = sum(1 for row in rows for g in CELL_GATES if row["gates"][g] == "pass")
    return reached, bool(twin) and all(twin), passed


def read_round(rid: str, path: Path) -> dict:
    card = json.loads(path.read_text())
    t = card["thresholds"]
    stations, passed_total = {}, 0
    for sid in STATIONS:
        st = card["stations"][sid]
        rows = rung_rows(st, t)
        reached, twin_ok, passed = station_goal(rows)
        passed_total += passed
        children = st.get("children") or {}
        stations[sid] = {"omega_max_rad_s": st["omega_max_rad_s"], "omega_source": st.get("omega_max_source"),
                         "tip_length_m": st["tip_length_m"], "rungs": rows, "max_trackable_fraction": reached, "twin_ok": twin_ok,
                         "gates_passed": passed, "gates_total": len(RUNGS) * len(CELL_GATES),
                         "children": {k: v for k, v in children.items() if isinstance(v, dict)}}
    return {"id": rid, "round": card["round"], "scored_utc": card["scored_utc"], "controller": card.get("controller"),
            "twin": card.get("twin"), "thresholds": t, "goal": card["goal"], "gates_passed_recomputed": passed_total,
            "stations": stations, "source": str(path), "sha256": sha256(path), "round_dir": card.get("round_dir")}


PERF_GATES = {"target_vs_real_tracking": "tracking", "target_vs_real_stop": "stop"}  # real vs the target: the job (performance)


def perf_gates(station: dict) -> tuple[int, int]:
    """(real performance gates passed, of): tracking and the tip stop at every rung."""
    return (sum(1 for r in station["rungs"] for g in PERF_GATES if r["gates"][g] == "pass"), len(station["rungs"]) * len(PERF_GATES))


def performance(rd: dict) -> dict:
    """Where the round stands on performance (real vs the target) across the stations: the gates passed, the failing cells grouped by
    (gate, rung) with the biggest group first (the banner's "top performance gap"), and the stations whose WORST stop at a rung is over
    the 1 mm gate even where the median passes (the gate reads the median: Performance Metrics per Part Type, 2026-11-17)."""
    passed = total = 0
    groups: dict = {}
    for sid in STATIONS:
        st = rd["stations"][sid]
        p, n = perf_gates(st)
        passed, total = passed + p, total + n
        for r in st["rungs"]:
            for g, word in PERF_GATES.items():
                if r["gates"][g] == "fail":
                    cell = {"tracking_rms_deg": r["tracking_rms_deg"], "tracking_peak_deg": r["tracking_peak_deg"], "stop_tool_mm": r["stop_tool_mm"],
                            "limiter_share": r["limiter_share"], "faults": r["faults"]}
                    groups.setdefault((word, r["fraction"]), {})[sid] = cell
    gaps = [{"gate": word, "fraction": fraction, "stations": list(cells), "values": cells} for (word, fraction), cells in groups.items()]
    gaps.sort(key=lambda g: (-len(g["stations"]), -g["fraction"], g["gate"]))
    limit = rd["thresholds"]["stop_tool_mm"]
    # the hidden tail: the median passes, the worst stop does not (a median that fails is already a failing cell above)
    worst = [{"station": sid, "rungs": [r["fraction"] for r in rd["stations"][sid]["rungs"]
                                        if r["stop_tool_mm"] is not None and r["stop_tool_mm"] <= limit < (r["stop_tool_max_mm"] or 0.0)]}
             for sid in STATIONS]
    return {"passed": passed, "of": total, "gaps": gaps, "worst_stops_over": [w for w in worst if w["rungs"]]}


def check(rounds: dict) -> None:
    """The re-scored totals equal each scorecard's own goal block, station by station: a drift from the frozen contract fails here."""
    for rid, rd in rounds.items():
        want = rd["goal"]["gates_passed"]
        if rd["gates_passed_recomputed"] != want:
            raise ValueError(f"{rid}: re-scored {rd['gates_passed_recomputed']} gates, the scorecard says {want} ({rd['source']})")
        for sid in STATIONS:
            st = rd["stations"][sid]
            if st["max_trackable_fraction"] != rd["goal"][f"max_trackable_fraction_{sid}"] or st["twin_ok"] != rd["goal"][f"twin_ok_{sid}"]:
                raise ValueError(f"{rid} {sid}: re-scored goal differs from the scorecard's ({rd['source']})")


# ---- the typed tree and its values ------------------------------------------------------------------------------------------------

def metric(mid, name, question, unit, values, family, gate=None, code=None, defined=SRC_GOAL, kind="gated", note="", better="lower"):
    """One metric of one node. kind: see sim2real.verdicts. family: performance | fidelity | evidence."""
    assert kind in verdicts.KINDS and family in (PERFORMANCE, FIDELITY, EVIDENCE), (mid, kind, family)
    return {"id": mid, "name": name, "code": code, "question": question, "unit": unit, "gate": gate, "kind": kind, "family": family,
            "defined": defined, "note": note, "better": better, "values": values}


def child_value(children: dict, key: str) -> dict:
    c = children.get(key) or {}
    status = {"pass": "pass", "fail": "fail", "not_observable": "not_observable"}.get(c.get("status"), "not_run")
    return {"value": c.get("value"), "status": status, "detail": c.get("detail") or "", "date": c.get("date"), "source": c.get("source")}


def station_nodes(sid: str, rounds: dict, oracle: dict) -> list[dict]:
    f = STATION_FACTS[sid]
    can = sid.replace("can", "CAN ")
    r0, now = rounds[AS_FOUND]["stations"][sid], rounds[NOW]["stations"][sid]
    tip_mm = round(now["tip_length_m"] * 1000, 1)
    t = rounds[NOW]["thresholds"]

    def per_round(fn):
        return {rid: fn(rd["stations"][sid]) for rid, rd in rounds.items()}

    def at(rs, fraction, key):
        return next((row[key] for row in rs["rungs"] if row["fraction"] == fraction), None)

    def worst_ratio(rs):
        rows = [r for r in rs["rungs"] if r["twin_ratio"] is not None]
        if not rows:
            return None, None
        worst = max(rows, key=lambda r: r["twin_ratio"])
        return worst["twin_ratio"], worst["fraction"]

    def count(rs, gate):
        cells = [r["gates"][gate] for r in rs["rungs"]]
        return sum(1 for c in cells if c == "pass"), sum(1 for c in cells if c != "not_run")

    def counted(c, what):
        status = "pass" if c[1] and c[0] == c[1] else ("fail" if c[1] else "not_run")
        return {"value": c[0], "of": c[1], "status": status, "detail": f"{c[0]} of {c[1]} rungs {what}"}

    def twin_value(rs):
        ratio, fraction = worst_ratio(rs)
        status = "pass" if rs["twin_ok"] else ("fail" if ratio is not None else "not_run")
        detail = (f"worst at the {fraction:g} rung; held-out sim vs real ÷ same-input repeat floor" if ratio is not None
                  else "no rung has both a floor and a held-out play")
        return {"value": ratio, "status": status, "detail": detail}

    def data_value(rs):
        played = [r for r in rs["rungs"] if r["tracking_rms_deg"] is not None]
        reps = min((r["repeats"] or 0) for r in rs["rungs"])
        held = min((r["held_out"] or 0) for r in rs["rungs"])
        ok = len(played) == len(RUNGS) and reps >= 5 and held >= 2
        return {"value": reps, "status": "pass" if ok else "fail",
                "detail": f"{len(played)} of 6 rungs measured · fewest {reps} repeats + {held} held-out per rung (needs 5 + 2)"}

    def gated_at(key, limit, detail):
        return lambda rs: {"value": at(rs, 0.9, key), "status": status_of(at(rs, 0.9, key), {"op": "<=", "limit": limit}), "detail": detail(rs)}

    oracle_row = oracle.get("pendulum_can11") if sid == "can11" else None
    if oracle_row:
        v = oracle_row["verdict"]
        routines = {"value": v["parameters_pass"], "of": v["parameters"], "status": v["status"],
                    "detail": f"{v['parameters_pass']} of {v['parameters']} hidden parameters recovered in sim, {v['metrics_pass']} of "
                              f"{v['metrics']} held-out factors (sysid oracle, code {oracle_row['code']}); the same result in both rounds"}
    else:
        routines = {"value": None, "status": "not_run", "detail": "no sysid oracle example for this station yet"}

    m = [
        # evidence: the ruler and the data
        metric("repeat_floor", "Repeat floor (T1)", "floor", "°", {rid: child_value(rd["stations"][sid]["children"], "T1") for rid, rd in rounds.items()},
               EVIDENCE, gate={"op": "repeats", "limit": 5, "text": "≥ 5 identical repeats at every rung"}, code="T1", defined=SRC_SERVO,
               note="same-input run-to-run spread; the twin's ruler"),
        metric("rungs_measured", "Fewest same-input repeats per rung", "data", "repeats", per_round(data_value), EVIDENCE,
               gate={"op": ">=", "limit": 5, "text": "≥ 5 repeats + 2 held-out at all 6 rungs"}, better="higher",
               note="coverage bins are not computed for this rig; the ladder IS its coverage"),
        metric("oracle_recovery", "Calibration recovers a hidden truth (sim)", "routines", "parameters",
               {rid: dict(routines) for rid in rounds}, EVIDENCE,
               gate={"op": "all", "limit": None, "text": "every identifiable value within tolerance at 1× noise"}, defined=SRC_ORACLE, better="higher"),
        # performance: real or sim vs the target
        metric("passes_up_to", "Tracks and stops up to", "job", "of top speed",
               per_round(lambda rs: {"value": rs["max_trackable_fraction"], "status": "pass" if rs["max_trackable_fraction"] >= GOAL_FRACTION else "fail",
                                     "detail": f"top speed {_deg_per_s(rs['omega_max_rad_s'])} ({rs['omega_source']})"}),
               PERFORMANCE, gate={"op": ">=", "limit": GOAL_FRACTION, "text": "≥ 0.9 of top speed"}, better="higher",
               note="the highest rung with every rung up to it passing tracking and the tip stop"),
        metric("tracking_rms_09", "Tracking RMS at 0.9 of top speed", "job", "°",
               per_round(gated_at("tracking_rms_deg", t["tracking_rms_deg"], lambda rs: "target vs encoder, median of the rung's plays")),
               PERFORMANCE, gate={"op": "<=", "limit": t["tracking_rms_deg"], "text": f"≤ {t['tracking_rms_deg']:g}°"}),
        metric("tracking_peak_09", "Tracking peak at 0.9 of top speed", "job", "°",
               per_round(gated_at("tracking_peak_deg", t["tracking_peak_deg"], lambda rs: "worst instant of the rung")),
               PERFORMANCE, gate={"op": "<=", "limit": t["tracking_peak_deg"], "text": f"≤ {t['tracking_peak_deg']:g}°"}),
        metric("tip_stop_09", "Tip stop error at 0.9 of top speed", "job", "mm",
               per_round(gated_at("stop_tool_mm", t["stop_tool_mm"], lambda rs: f"median of the rung's stops; tip {rs['tip_length_m'] * 1000:g} mm × angle error, settled")),
               PERFORMANCE, gate={"op": "<=", "limit": t["stop_tool_mm"], "text": f"≤ {t['stop_tool_mm']:g} mm (Zach)"}),
        metric("tip_stop_worst_09", "Worst tip stop at 0.9 of top speed", "job", "mm",
               per_round(lambda rs: {"value": at(rs, 0.9, "stop_tool_max_mm"), "status": "observed" if at(rs, 0.9, "stop_tool_max_mm") is not None else "not_run",
                                     "detail": f"the worst of the rung's {at(rs, 0.9, 'stops') or '—'} stops; the gate reads the median"}),
               PERFORMANCE, kind="observed", defined=SRC_SCORE,
               note="shown beside the gate: the median can hide a failing stop (Performance Metrics per Part Type, 2026-11-17)"),
        metric("sim_stop", "Sim's own tip stop", "job", "rungs", per_round(lambda rs: counted(count(rs, "target_vs_sim_stop"), "≤ 1 mm in sim (the controller, in sim)")),
               PERFORMANCE, gate={"op": "all", "limit": None, "text": "every rung"}, kind="counted", better="higher",
               note="a gate in the 180 count, not in the campaign goal"),
        metric("tip_tracking_09", "Tracking at the tip, 0.9 rung", "job", "mm",
               per_round(lambda rs: {"value": at(rs, 0.9, "tracking_rms_tool_mm"), "status": "observed", "detail": "tip length × tracking RMS (MOC decision 3)"}),
               PERFORMANCE, kind="observed", defined=SRC_SCORE),
        # fidelity: real vs sim
        metric("twin_over_floor", "Twin ÷ floor, worst rung", "twin", "× floor", per_round(twin_value), FIDELITY,
               gate={"op": "<=", "limit": t["sim_vs_real_floor_ratio"], "text": f"≤ {t['sim_vs_real_floor_ratio']:g}× at every rung"},
               note="the agents' 1.5, never confirmed by Zach"),
        metric("sim_predicts", "Sim predicts tracking", "twin", "rungs", per_round(lambda rs: counted(count(rs, "sim_predicts_tracking"), "within 20 % or 0.05°")),
               FIDELITY, gate={"op": "all", "limit": None, "text": "every rung"}, kind="counted", better="higher",
               note="a gate in the 180 count, not in the campaign goal"),
        metric("perf_gates", "Real performance gates passed", "job", "of 12",
               per_round(lambda rs: {"value": perf_gates(rs)[0], "of": perf_gates(rs)[1], "status": "observed",
                                     "detail": "tracking and tip stop, real vs the target, at each of the 6 rungs"}),
               PERFORMANCE, kind="observed", better="higher", defined=SRC_GOAL),
        # the station's count of all five gates (both groups): observed
        metric("gates_passed", "Gates passed", "job", "of 30",
               per_round(lambda rs: {"value": rs["gates_passed"], "of": rs["gates_total"], "status": "observed", "detail": "5 gates × 6 rungs, performance and fidelity"}),
               PERFORMANCE, kind="observed", better="higher", defined=SRC_GOAL),
    ]
    station = {"id": sid, "parent": "rack", "title": f"{can} · {f['plain']}", "short": can, "line": f["plain"], "level": "station",
               "type": {"id": "pendulum_arm_1dof", "name": "1-DOF pendulum arm", "rm": "RigidBodyChain (1 joint)"},
               "judged_at": f"the link tip ({tip_mm:g} mm)", "unit": f"{f['board']} · {can}", "gating": True, "metrics": m,
               "facts": [["tip length", f"{tip_mm:g} mm"], ["1 mm at the tip", f"{math.degrees(0.001 / now['tip_length_m']):.2f}°"],
                         ["top speed, measured", (f"{_deg_per_s(r0['omega_max_rad_s'])} → {_deg_per_s(now['omega_max_rad_s'])}" if r0["omega_max_rad_s"] != now["omega_max_rad_s"]
                                                  else _deg_per_s(now["omega_max_rad_s"]))],
                         ["motor", f["motor"]], ["load", f["load"]]],
               "plate": f["plate"], "family": f["family"], "device": can,
               "rungs": {rid: rd["stations"][sid]["rungs"] for rid, rd in rounds.items()},
               "omega": {rid: rd["stations"][sid]["omega_max_rad_s"] for rid, rd in rounds.items()},
               "tip_length_m": now["tip_length_m"], "gravity_nm": f["gravity_nm"],
               "health": {rid: {"faults": sum((r["faults"] or 0) for r in rd["stations"][sid]["rungs"]),
                                "missing": sum((r["missing"] or 0) for r in rd["stations"][sid]["rungs"])} for rid, rd in rounds.items()}}
    if r0["omega_max_rad_s"] != now["omega_max_rad_s"]:
        station["caveat"] = (f"The ladder moved: round {rounds[AS_FOUND]['round']}'s top speed was {_deg_per_s(r0['omega_max_rad_s'])} (the current-limit onset), "
                             f"round {rounds[NOW]['round']}'s is {_deg_per_s(now['omega_max_rad_s'])}, so a rung is the same fraction but a faster move now.")

    ch = {rid: rd["stations"][sid]["children"] for rid, rd in rounds.items()}
    unit = f"{f['board']} · {can}"
    servo = {"id": f"{sid}/servo", "parent": sid, "title": f"Integrated servo · {f['motor']} + {f['gear']}", "short": "Integrated servo",
             "line": f"{f['motor']} + {f['gear']}", "level": "servo",
             "type": {"id": "integrated_servo", "name": "Integrated servo", "rm": "robot_models.IntegratedServo"},
             "judged_at": "the output angle (rotor encoder ÷ ratio)", "unit": unit, "gating": False, "device": can,
             "metrics": [
                 metric("T1", "Repeat floor", "floor", "°", {rid: child_value(ch[rid], "T1") for rid in rounds}, EVIDENCE, code="T1",
                        defined=SRC_SERVO, kind="shown", gate={"op": "repeats", "limit": 5, "text": "≥ 5 identical repeats"}),
                 metric("T2", "Twin ÷ floor at the output", "twin", "× floor", {rid: child_value(ch[rid], "T2") for rid in rounds}, FIDELITY,
                        code="T2", defined=SRC_SERVO, kind="shown", gate={"op": "<=", "limit": 1.5, "text": "≤ 1.5× the floor"},
                        note="on this rack the output IS the arm's joint: the same number as the arm's twin ÷ floor"),
                 metric("T4", "Stop error at the output", "job", "°",
                        {rid: {"value": None, "status": "not_run", "detail": "not in this round's children block; the arm's tip stop stands in"} for rid in rounds},
                        PERFORMANCE, code="T4", defined=SRC_SERVO, kind="shown", gate={"op": "<=", "limit": None, "text": "its share of the 1 mm tool gate"}),
             ],
             "facts": [["made of", "motor + gearbox + driver + encoder"], ["seen as", "one box: the encoder is on the rotor"]]}
    parts = [
        {"id": f"{sid}/servo/driver", "parent": f"{sid}/servo", "title": f"Driver · {f['board']} (FOC board)", "short": "Driver",
         "line": f"{f['board']} FOC board", "level": "part", "type": {"id": "foc_controller", "name": "FOC controller", "rm": "robot_models.FocController"},
         "judged_at": "its q-current", "unit": unit, "gating": True, "device": can,
         "metrics": [metric("T3", "Current fidelity", "twin", "× scatter", {rid: child_value(ch[rid], "T3") for rid in rounds}, FIDELITY, code="T3",
                            defined=SRC_SERVO, kind="shown", gate={"op": "<=", "limit": 2.0, "text": "≤ 2× run-to-run scatter"},
                            note="last known from late-October runs, before the 24 V re-commissioning: the same number in both rounds"),
                     metric("limiter_share", "Limiter share", "job", "of rows", {rid: child_value(ch[rid], "limiter_share") for rid in rounds}, PERFORMANCE,
                            defined=SRC_GOAL, kind="shown", gate={"op": "<=", "limit": 0.02, "text": "≤ 2 % of rows"})],
         "facts": [["board", f["board"]], ["reports", "its own q-current, so current fidelity is measurable"]]},
        {"id": f"{sid}/servo/motor", "parent": f"{sid}/servo", "title": f"Motor · {f['motor']}", "short": "Motor", "line": f["motor"], "level": "part",
         "type": {"id": "bldc_motor", "name": "BLDC motor", "rm": "robot_models.BldcMotor"}, "judged_at": "the shaft (seen only through the servo)",
         "unit": unit, "gating": True, "device": can,
         "metrics": [metric("T7", "Envelope: top speed, twin vs measured", "twin", "%", {rid: child_value(ch[rid], "T7") for rid in rounds}, FIDELITY, code="T7",
                            defined=SRC_SERVO, kind="shown", gate={"op": "abs", "limit": 5.0, "text": "within 5 %"}),
                     metric("T6", "Torque per amp (Kt)", "twin", "%", {rid: child_value(ch[rid], "T6") for rid in rounds}, PERFORMANCE, code="T6",
                            defined=SRC_SERVO, kind="not_observable", gate={"op": "abs", "limit": 5.0, "text": "within 5 % against a known mass"}),
                     metric("T8", "Winding temperature", "twin", "°C", {rid: child_value(ch[rid], "T8") for rid in rounds}, FIDELITY, code="T8",
                            defined=SRC_SERVO, kind="not_observable", gate={"op": "abs", "limit": 5.0, "text": "within 5 °C of a thermocouple"})],
         "facts": [["motor", f["motor"]], ["family", f["family"]]]},
        {"id": f"{sid}/servo/gearbox", "parent": f"{sid}/servo", "title": f"Gearbox · {f['gear']}", "short": "Gearbox", "line": f["gear"], "level": "part",
         "type": {"id": "gearbox", "name": "Gearbox", "rm": "robot_models.Gearbox"}, "judged_at": "output vs input angle (not visible here)",
         "unit": unit, "gating": True, "device": can,
         "metrics": [metric("T5", "Output lost motion (backlash)", "twin", "°", {rid: child_value(ch[rid], "T5") for rid in rounds}, PERFORMANCE, code="T5",
                            defined=SRC_SERVO, kind="not_observable", gate={"op": "<=", "limit": 0.033, "text": "CI half-width ≤ 0.033°"})],
         "facts": [["ratio", f["gear"]]]},
        {"id": f"{sid}/servo/encoder", "parent": f"{sid}/servo", "title": "Encoder · the board's rotor encoder", "short": "Encoder",
         "line": "the board's rotor encoder", "level": "part", "type": {"id": "encoder", "name": "Encoder", "rm": "robot_models.Encoder"},
         "judged_at": "its own reading", "unit": unit, "gating": True, "device": can,
         "metrics": [metric("homing_repeat", "Homing repeatability", "floor", "°",
                            {rid: {"value": None, "status": "not_run", "detail": "needs ≥ 5 homings; not run on the pendulum rack"} for rid in rounds},
                            PERFORMANCE, defined=SRC_SERVO, kind="shown", gate=None)],
         "facts": [["noise", "inside the station's repeat floor (T1)"]]},
    ]
    link = {"id": f"{sid}/link", "parent": sid, "title": f"Link + load · {f['load']}", "short": "Link + load", "line": f["load"], "level": "part",
            "type": {"id": "rigid_link", "name": "Link + load", "rm": "RigidBodyChain link"}, "judged_at": "through the arm's gates",
            "unit": "", "gating": False, "metrics": [],
            "facts": [["tip length", f"{tip_mm:g} mm"], ["gravity term m·g·L", f"{f['gravity_nm']:g} N·m" if f["gravity_nm"] else "≈ 0 (balanced)"],
                      ["gates", "none of its own: its m·g·L and inertia are twin terms"]]}
    return [station, servo, *parts, link]


def rack_node(rounds: dict) -> dict:
    def per_round(fn):
        return {rid: fn(rd) for rid, rd in rounds.items()}

    def stations(rd, test):
        n = sum(1 for s in STATIONS if test(rd, s))
        return n

    def of_six(test, detail):
        return per_round(lambda rd: (lambda n: {"value": n, "of": 6, "status": "pass" if n == 6 else "fail", "detail": detail})(stations(rd, test)))

    full_ladder = (lambda rd, s: all(r["tracking_rms_deg"] is not None and (r["repeats"] or 0) >= 5 and (r["held_out"] or 0) >= 2
                                     for r in rd["stations"][s]["rungs"]))
    m = [
        metric("floors_known", "Stations with a repeat floor", "floor", "stations",
               of_six(lambda rd, s: (rd["stations"][s]["children"].get("T1") or {}).get("status") == "pass", "T1: ≥ 5 repeats at every rung"),
               EVIDENCE, gate={"op": ">=", "limit": 6, "text": "6 of 6"}, defined=SRC_SERVO, better="higher"),
        metric("data_complete", "Stations with the full ladder played", "data", "stations",
               of_six(full_ladder, "6 rungs × (5 repeats + 2 held-out)"), EVIDENCE, gate={"op": ">=", "limit": 6, "text": "6 of 6"}, better="higher",
               defined=SRC_ROLLUP),
        metric("oracle_stations", "Stations with a sim oracle", "routines", "stations",
               {rid: {"value": 1, "of": 6, "status": "observed", "detail": "only CAN 11 has a sysid example (8 of 8 recovered)"} for rid in rounds},
               EVIDENCE, kind="observed", defined=SRC_ORACLE, better="higher"),
        metric("stations_tracking", "Stations tracking to 0.9 of top speed", "job", "stations",
               of_six(lambda rd, s: rd["goal"][f"max_trackable_fraction_{s}"] >= GOAL_FRACTION, "max trackable fraction ≥ 0.9"),
               PERFORMANCE, gate={"op": ">=", "limit": 6, "text": "6 of 6"}, better="higher", defined=SRC_ROLLUP),
        metric("perf_gates", "Real performance gates passed", "job", "of 72",
               per_round(lambda rd: (lambda p: {"value": p["passed"], "of": p["of"], "status": "observed",
                                                "detail": "tracking and tip stop, real vs the target, 6 rungs × 6 stations"})(performance(rd))),
               PERFORMANCE, kind="observed", better="higher", defined=SRC_ROLLUP),
        metric("stations_twinned", "Stations twinned", "twin", "stations",
               of_six(lambda rd, s: rd["goal"][f"twin_ok_{s}"], "twin ≤ 1.5× floor at every measured rung"),
               FIDELITY, gate={"op": ">=", "limit": 6, "text": "6 of 6"}, better="higher", defined=SRC_ROLLUP),
        metric("goal_met", "Campaign goal met", "verdict", "",
               per_round(lambda rd: {"value": int(rd["goal"]["goal_met"]), "status": "pass" if rd["goal"]["goal_met"] else "fail",
                                     "detail": "every station tracks to ≥ 0.9 of top speed AND its twin passes at every rung"}),
               PERFORMANCE, gate={"op": ">=", "limit": 1, "text": "all six stations"}, better="higher"),
        metric("gates_passed", "Gates passed", "job", "of 180",
               per_round(lambda rd: {"value": rd["goal"]["gates_passed"], "of": rd["goal"]["gates_total"], "status": "observed",
                                     "detail": "5 gates × 6 rungs × 6 stations, performance and fidelity"}),
               PERFORMANCE, kind="observed", better="higher"),
    ]
    return {"id": "rack", "parent": None, "title": "One Dof Test Rack · pendulum campaign", "short": "One Dof Test Rack", "line": "pendulum campaign",
            "level": "deployment", "type": {"id": "deployment", "name": "Deployment", "rm": "sim2real Deployment"}, "judged_at": "the campaign goal",
            "unit": "fdcanusb 272813EF · 24 V", "gating": True, "metrics": m,
            "facts": [["where", "Zach's bench at home"], ["adapter", "fdcanusb 272813EF, 24 V"], ["stations", "6 single-joint pendulums: 3 GIM43, 3 JMC60"],
                      ["ladder", "0.2 · 0.4 · 0.6 · 0.8 · 0.9 · 1.0 of each station's top speed"]]}


def camera_nodes() -> list[dict]:
    """The rack's two depth cameras: in the tree, never gating (Zach 2026-11-11: gates read the joint encoders, ArUco a flag)."""
    return [{"id": f"cam-{serial}", "parent": "rack", "title": f"Depth camera · RealSense D405 {serial} ({plate})", "short": f"D405 {serial[-4:]}",
             "line": f"RealSense D405 over the {plate}", "level": "sensor", "type": {"id": "depth_camera", "name": "Depth camera", "rm": "robot_models.DepthCamera"},
             "judged_at": "a flag only: gates read the joint encoders (Zach, 11-11)", "unit": f"D405 {serial}", "gating": False, "metrics": [],
             "facts": [["role", "ArUco tags on the links, a cross-check"], ["in this round", "no camera metric scored"]]}
            for serial, plate in (("218622276036", "JMC60 plates"), ("218622274411", "GIM43 plate"))]


# ---- round by round, and every run ------------------------------------------------------------------------------------------------

def scored_rounds(scorecards: Path = SCORECARDS, now: str = NOW_FILE) -> tuple[list[tuple[int, Path]], list[int]]:
    """(every round the campaign scored up to "now", in order, as (round, file); the rounds below it with no file). The rounds below the
    now file's own `round` are round{n}.json; the now file itself is the last, so nothing after it is ever read (round9.json beside a
    round-8 "now" stays out). A round whose file is missing is skipped and listed, never invented."""
    now_path = scorecards / now
    latest = int(json.loads(now_path.read_text())["round"])
    files, missing = [], []
    for n in range(latest):
        path = scorecards / f"round{n}.json"
        if path.is_file():
            files.append((n, path))
        else:
            missing.append(n)
    return files + [(latest, now_path)], missing


def history(scorecards: Path = SCORECARDS, now: str = NOW_FILE) -> list[dict]:
    """Each scored round's performance per station at the goal's rung (0.9 of top speed), for the round-by-round charts with the goal
    line drawn (Zach liked the W&B round-by-round chart's "GOOD <= 0.5 deg" line). A round whose file is missing is left out
    (scored_rounds lists it; build() reports it as history_missing)."""
    out = []
    for n, path in scored_rounds(scorecards, now)[0]:
        rd = read_round(f"r{n}", path)
        stations = {}
        for sid in STATIONS:
            st = rd["stations"][sid]
            at = {r["fraction"]: r for r in st["rungs"]}.get(GOAL_FRACTION) or {}
            ratios = [r["twin_ratio"] for r in st["rungs"] if r["twin_ratio"] is not None]
            stations[sid] = {"tracking_rms_09": at.get("tracking_rms_deg"), "tracking_peak_09": at.get("tracking_peak_deg"),
                             "stop_09": at.get("stop_tool_mm"), "stop_max_09": at.get("stop_tool_max_mm"),
                             "passes_up_to": st["max_trackable_fraction"], "perf_gates": perf_gates(st)[0], "twin_worst": max(ratios) if ratios else None}
        out.append({"round": rd["round"], "scored_utc": rd["scored_utc"], "controller": rd["controller"], "source": str(path),
                    "gates_passed": rd["goal"]["gates_passed"], "perf_gates": performance(rd)["passed"], "stations": stations})
    return out


def rerun_index(rrd_root: Path) -> dict[str, Path]:
    """run (.npz) -> its recording (.rrd), from every index the campaign's pendulum_rerun wrote (bam_rack_twin.pendulum_rerun-index/1),
    keeping only recordings that exist."""
    out = {}
    for idx in sorted(rrd_root.rglob("index.json")) if rrd_root.is_dir() else []:
        try:
            doc = json.loads(idx.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or doc.get("schema") != "bam_rack_twin.pendulum_rerun-index/1":
            continue
        for row in doc.get("runs") or []:
            if row.get("run") and row.get("rrd") and Path(row["rrd"]).is_file():
                out[row["run"]] = Path(row["rrd"])
    return out


def same_bytes(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and sha256(a) == sha256(b)
    except OSError:
        return False


def recording(run: str, index: dict[str, Path], by_name: dict[str, list[str]]) -> tuple[Path | None, str | None]:
    """The .rrd of THIS run: the rerun index's, else the recording of a byte-identical copy of the run in the same round (the campaign
    copied round 8's can12+can14 session to round8/can14/real/ and recorded that copy). Never a recording of another run."""
    if run in index:
        return index[run], "rerun index"
    path = Path(run)
    marker = next((part for part in path.parts if part.startswith("round")), None)
    for other in by_name.get(path.name, []):
        if other != run and marker in Path(other).parts and same_bytes(path, Path(other)):
            return index[other], "identical copy"
    return None, None


def runs(scorecards: Path = SCORECARDS, rrd_root: Path | None = None, now: str = NOW_FILE) -> list[dict]:
    """Every play of every scored round as one row (Zach, 2026-11-17: "Runs are the atomic unit ... drill into a particular run (rerun)"):
    its round, station, rung and speed, kind (repeat or held-out), the scorer's own per-run numbers, whether it meets the tracking gates,
    and its Rerun recording when one exists (`rrd`, how it was found in `rrd_via`; None: no recording yet). The rounds are scored_rounds':
    every one up to "now", none after."""
    rrd_root = rrd_root or scorecards.parent / "rrd"
    index = rerun_index(rrd_root)
    by_name: dict[str, list[str]] = {}
    for run in index:
        by_name.setdefault(Path(run).name, []).append(run)
    rows = []
    for _n, path in scored_rounds(scorecards, now)[0]:
        card = json.loads(path.read_text())
        t = card["thresholds"]
        for sid in STATIONS:
            st = card["stations"][sid]
            for rung in st["rungs"]:
                for play in rung.get("plays") or []:
                    rms, peak = finite(play.get("tracking_rms_deg")), finite(play.get("tracking_peak_deg"))
                    ok = None if rms is None or peak is None else (rms <= t["tracking_rms_deg"] and peak <= t["tracking_peak_deg"] and not play.get("fault"))
                    rrd, via = recording(play["run"], index, by_name)
                    rows.append({"round": card["round"], "station": sid, "fraction": round(float(rung["fraction"]), 3),
                                 "speed_rad_s": rounded(rung.get("peak_speed_rad_s"), 3), "kind": play.get("kind"), "seed": play.get("seed"),
                                 "status": play.get("status"), "name": Path(play["run"]).stem, "run": play["run"],
                                 "tracking_rms_deg": rounded(rms), "tracking_peak_deg": rounded(peak), "tape_rms_deg": rounded(play.get("tape_rms_deg")),
                                 "sim_tracking_rms_deg": rounded(play.get("sim_tracking_rms_deg")), "sim_vs_real_deg": rounded(play.get("sim_vs_real_deg")),
                                 "stops": play.get("stops"), "fault": bool(play.get("fault")), "tracks": gate_word(ok),
                                 "rrd": str(rrd) if rrd else None, "rrd_via": via})
    return rows


def wandb_links(registry: Path = REGISTRY) -> dict[str, dict]:
    """Deployment id -> its W&B backdoor {project, url, report, report_title}, from app/registry.json's `wandb` blocks.

    Zach (Daily Note 2026-11-18, "# Ok back to performance metrics"): "Each deployment in the sim2real app should have a button to open
    within weights and biases, as like a backdoor, so that we can always still support W&B for summary". WHY the registry: the link is
    the deployment's data, kept beside its other producer fields, never written into the page. A deployment without a project, or whose
    url is not a web URL, is left out, so the page draws no dead button. Only the One Dof Test Rack has a project today ("Sim2Real ·
    1-DOF rack"); the virtual deployments are sysid's oracle examples and are logged nowhere."""
    if not registry.is_file():
        return {}
    out = {}
    for entry in json.loads(registry.read_text(encoding="utf-8")).get("deployments", []):
        wb = entry.get("wandb") or {}
        url, report = wb.get("url") or "", wb.get("report") or ""
        if not url.startswith("https://"):
            continue
        out[entry["id"]] = {"project": wb.get("project"), "url": url, "report": report if report.startswith("https://") else None,
                            "report_title": (wb.get("report_title") or None) if report.startswith("https://") else None}
    return out


def columns(rounds: dict) -> list[dict]:
    """The page's two columns, each labelled from its own scorecard: "As found" (round 0, before any fit) and "Now" (the now file's round
    and the day it was scored, e.g. "round 9 · 2026-11-18"; UTC, as the scorecard writes it)."""
    a, b = rounds[AS_FOUND], rounds[NOW]
    return [{"id": AS_FOUND, "label": "As found", "long": f"round {a['round']} · before any fit"},
            {"id": NOW, "label": "Now", "long": f"round {b['round']} · {str(b['scored_utc'])[:10]}"}]


def build(scorecards: Path = SCORECARDS, oracle_index: Path = ORACLE, now: str = NOW_FILE) -> dict:
    """The page's data for the One Dof Test Rack (SCHEMA): its rounds, the five questions, its typed tree with every node's metrics per
    round, the five-question verdicts rolled up (sim2real.verdicts) and, on the rack, what stops the goal. `now`: the scorecard the "Now"
    column reads, a file in `scorecards` (default the campaign's latest)."""
    files = {AS_FOUND: scorecards / AS_FOUND_FILE, NOW: scorecards / now}
    missing = [path for path in files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"no pendulum scorecard at {missing[0]}")
    oracle_doc = json.loads(Path(oracle_index).read_text()) if Path(oracle_index).is_file() else {"examples": []}
    oracle = {row["example"]: row for row in oracle_doc["examples"]}
    rounds = {rid: read_round(rid, path) for rid, path in files.items()}
    check(rounds)
    nodes = [rack_node(rounds)]
    for sid in STATIONS:
        nodes += station_nodes(sid, rounds, oracle)
    nodes += camera_nodes()
    for n in nodes:
        n["children"] = [c["id"] for c in nodes if c["parent"] == n["id"]]
    verdicts.roll_up(nodes, tuple(rounds))
    rack = nodes[0]
    # performance first (Zach, 2026-11-17 "# Ok"): where the deployment stands on real vs the target, and its biggest gap
    rack["performance"] = {rid: performance(rd) for rid, rd in rounds.items()}
    # the rack's first failing question (of the five) and the stations that fail it
    rack["stops"] = {}
    for rid in rounds:
        first = rack["verdict"][rid]["first"] if rack["verdict"][rid]["status"] == "fail" else None
        rack["stops"][rid] = {"question": first, "stations": [n["id"] for n in nodes if n["level"] == "station" and first
                                                              and n["questions"][rid][first]["status"] == "fail"]}
    return {
        "schema": SCHEMA, "deployment": DEPLOYMENT, "built_by": "sim2real.deployments_page",
        "title": "One Dof Test Rack", "kind": "physical", "where": "Zach's bench at home",
        "summary": "Six single-joint pendulums on one fdcanusb at 24 V, each run up a speed ladder against its own twin.",
        "rounds": [{"id": col["id"], "round": rd["round"], "label": col["label"], "long": col["long"], "scored_utc": rd["scored_utc"],
                    "controller": rd["controller"], "twin": rd["twin"], "source": rd["source"], "sha256": rd["sha256"], "round_dir": rd["round_dir"],
                    "gates_passed": rd["goal"]["gates_passed"], "gates_total": rd["goal"]["gates_total"], "goal_met": rd["goal"]["goal_met"]}
                   for col, rd in ((c, rounds[c["id"]]) for c in columns(rounds))],
        "thresholds": rounds[NOW]["thresholds"],
        "questions": list(verdicts.QUESTIONS),
        "families": {PERFORMANCE: "real or sim vs the target: does it do the job", FIDELITY: "real vs sim: does the twin match",
                     EVIDENCE: "the ruler and the data the other two stand on"},
        "root": "rack",
        "nodes": nodes,
        "history": history(scorecards, now),
        # the rounds below "now" whose round{n}.json is missing: skipped in the history and the runs, never invented
        "history_missing": scored_rounds(scorecards, now)[1],
        "oracle_source": str(Path(oracle_index)),
    }


def write(out: Path, scorecards: Path = SCORECARDS, oracle_index: Path = ORACLE, now: str = NOW_FILE) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(scorecards, oracle_index, now), ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="the JSON file to write")
    parser.add_argument("--scorecards", type=Path, default=SCORECARDS, help=f"the campaign's scorecards folder (default {SCORECARDS})")
    parser.add_argument("--now", default=NOW_FILE, help=f"the scorecard the Now column reads, in --scorecards (default {NOW_FILE}, the latest)")
    args = parser.parse_args(argv)
    doc = json.loads(write(args.out, args.scorecards, now=args.now).read_text())
    r0, now = doc["rounds"]
    gap = f"; no scorecard for round(s) {doc['history_missing']}, skipped" if doc["history_missing"] else ""
    print(f"{args.out}: {len(doc['nodes'])} nodes; gates {r0['gates_passed']} ({r0['long']}) -> {now['gates_passed']} of {now['gates_total']} "
          f"({now['long']}), held to the scorecards{gap}")


if __name__ == "__main__":
    main()
