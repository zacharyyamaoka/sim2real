"""The ruler for full-arm homing routines on bam_fb_v2 (five-bar + UR wrist + crab claw), sim only - FROZEN 2026-11-13, before any routine
was run against it (Zach, 16:50: "Define what metrics look good: accurate, fast, identification of backlash, what percent of starting
configurations does it work in? (discretize possible starting states and check coverage)").

A routine is a black box: a PEP 0002 ``HomingProcedure`` run on ``fullarm_plant.FullArmHomingPlant`` (belt in the scene, the whole arm
settled before power-on) from one start of the grid below, in one environment (a hidden truth). It is scored on its outputs and that truth
only, never by reading its code. Every angle shown is in degrees.

**Per episode: one outcome** (``outcome_class``, most severe first; J1 is held and never homed in the real form, so it is never scored):

==============  =============================================================================================================
infeasible      the twin cannot place the start (the loop does not close, a joint past its stop, the arm in self-contact or through
                the belt): not a start the arm can be found in. Out of coverage's denominator, counted.
silent_wrong    it FINISHED (claimed a home) but a scored joint's zero is more than ``WRONG_STOP_DEG`` off the hidden truth, or a stall
                it used sat more than that off the CAD stop it meant: a wrong stop, an obstacle or a rotor turn. The one unforgivable
                outcome.
tripped         the plant's runaway stop or the controller's guard ended it (a fault, not a home)
refused         the routine itself said no (a witness, a consistency check): safe - the arm holds and a person looks
timeout         a step never finished
inaccurate      finished on the right stops, but a scored zero sits in (``GATE_DEG``, ``WRONG_STOP_DEG``]
homed           finished, every scored zero within ``GATE_DEG`` of the truth
==============  =============================================================================================================

A homed episode is also **clean** when nothing touched the belt after lift-off: a routine that presses the belt again has hit something it
cannot see. **Coverage counts homed AND clean.**

*Amendment 1 (2026-11-13, after one smoke episode on one cell and before any grid run; no target moved):* lift-off was "the first tick
after power-on with nothing on the belt". Leaving a belt rest, the claw drags along the belt for seconds while J2's first seek lifts the
arm, with gaps of a few ticks, and that rule counted 196 ticks of the drag as re-contacts. Lift-off is now the first tick from which the
belt stays clear ``fullarm_check.BELT_LIFTOFF_CLEAR_S`` (2 s); the drag before it is reported (``belt_drag_s``), never a fault.

**Aggregates and targets** (per routine x environment; ``TARGETS``, what "good" means):

=========================  ======================================================================  ==============================
metric                     what                                                                    good
=========================  ======================================================================  ==============================
silent_wrong               episodes                                                                0 (hard gate, every env)
coverage_pct               homed and clean / feasible starts                                       >= 95 nominal, >= 90 each env
zero_error_p95_deg         worst scored joint |zero - truth|, p95 over finished episodes           <= 0.1
repeatability_deg          per scored joint, max - min of the signed zero error over finished      <= 0.02
                           episodes (what re-homing from another start moves the zero); worst joint
backlash_identified_pct    finished episodes whose every wrist gap the routine identified itself   reported (100 % to claim it)
backlash_error_arcmin      worst wrist |identified gap - hidden gap|, p95 over identified episodes  <= max(1', 25 % of the truth)
time_to_home_s             tick clock, first command -> done: median and p95 over homed episodes   median <= 60, p95 <= 90
belt_after_liftoff         episodes that touched the belt after lift-off                           0
self_contact_episodes      episodes with any arm-on-arm primitive contact                          reported (Zach 2026-11-13:
                                                                                                   gripper on forearm <= 1 N.m ok)
peak_speed_ratio           worst powered joint speed / its ceiling (fullarm_check)                 <= 0.8
tripped                    episodes                                                                0
=========================  ======================================================================  ==============================

WHY these numbers: the 0.1 deg gate is the MuJoCo rung's (``fullarm_check.GATE_DEG``; ~0.3 mm at the claw's 0.18 m reach, inside Zach's
1 mm tool gate); 1 deg is robot_models' ``STALL_TOLERANCE_DEG`` (an error past it is a wrong stop, not a sloppy one: obstacle stalls ran
3-68 deg, a rotor turn is 36); 0.8 x the speed ceilings is the dispatcher's margin; 60 s is the full arm's 2026-11-13 median (57-70 s)
held, not bought with accuracy. WHY no weighted sum (robot_models.homing.metrics): rank by silent_wrong, then coverage, then zero error,
then time - time never buys accuracy.

**The start grid** (``grid_cells``): a start is the pose the arm was in when the power went, discretised over all seven joints; the twin
then lets the whole arm fall (onto the belt, its stops or itself, ``settle_all``) before power-on, so "hanging on the belt" is not a
special family - it is where most cells land, as on the rack.

* the five-bar (J2, C1 Craig): ``FIVEBAR_LEVELS`` - READY (where the arm waits between picks), PICK (the claw 30 mm over the tray floor),
  LIFT (150 mm over the tray), UP (raised toward the shoulder);
* the wrist W1 x W2: ``WRIST_LEVELS_DEG`` (6 x 6, 60 deg apart; |W2| 150 is the forearm band);
* W3, the claw and J1 cycle over the 36 wrist cells in a balanced pattern (``_latin``): every level appears equally often.

4 x 36 = 144 cells. The perturbation environments run on ``subset_cells`` (24: one W1 / W2 diagonal per five-bar pose).

*Amendment 5 (2026-11-13 night, Zach: "even in this report I don't see J1 being homed"):* a row that homes J1 (its episodes carry
``homes_j1``) is scored on J1 too - J1 joins ``scored_roles`` for that episode, under the same 0.1 deg / 1 deg gates; rows that hold J1 as
before are scored as before. No metric or target moves.

*Amendment 4 (2026-11-13, a labelling bug):* the controller reports a step that never finished as "aborted: step ... was not done
within", which the first ``outcome_class`` counted as a trip; it is a timeout, as the table above defines. Coverage is unchanged.

*Amendment 3 (2026-11-13, a sampling bug, found in the first perturbed results):* the subset was "every 6th cell", which on a grid ordered
(pose, W1, W2) with 6 W2 levels is every cell with W2 at -150 deg - the folded wrist only, V1's worst case. It is now the diagonal
(W1 index + W2 index + pose index) mod 6 == 0: every W1 and every W2 level once per pose. The folded-wrist cells already run stay in the
cache as ``folded_subset_cells`` and are reported apart, never mixed into a perturbed card.

**The environments** (``ENVIRONMENTS``): the hidden truths a routine never sees - backlash B0 / B1 / B2 (fullarm_plant's gaps), the wrist's
breakaway friction for its sliding one, the 0.50 kg claw, a 1.5 deg error in the rotor-phase calibration the witness uses, and a second
draw of the boards' sub-turn phases (another power-up frame).

*Amendment 2 (2026-11-13, after READY's nominal map; no metric, target or cell moved):* rows added - Zach's V1 order in the perturbed
twins and V1 with the stored table (V1 covered the most of READY); and every single-touch row re-judged by a tight witness (0.5 deg on a
trusted home's own stall reading, the five-bar's drives included), derived from that row's own episodes because a witness never moves the
arm (``routine_check.tight_witness``).

**The routines compared** (``fullarm_routine.ROWS``; tuning is allowed only on ``tuning_cells``, never on the grid): Zach's V1 wrist order;
PEP 0047 as landed (park_first + rotor-phase witness, the wrist homed at the five-bar's home); park_first at READY; a single fast touch;
the 3D-printer double and triple touch (fast locate, back off, slow re-touch); press_reverse (both stops at two levels: the backlash every
home); park_first with the stored identify_backlash table.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence

from ...named_poses import fivebar_craig_deg, named_pose

GATE_DEG = 0.1
WRONG_STOP_DEG = 1.0
SCORED_ROLES = ("J2", "C1", "W1", "W2", "W3", "CLAW")
WRIST_ROLES = ("W1", "W2", "W3")
OUTCOMES = ("homed", "inaccurate", "refused", "timeout", "tripped", "silent_wrong", "infeasible")
SPEED_RATIO_MAX = 0.8

TARGETS = {
    "silent_wrong": ("==", 0),
    "coverage_pct": (">=", 95.0),  # nominal; every other environment >= COVERAGE_ENV_MIN_PCT
    "zero_error_p95_deg": ("<=", GATE_DEG),
    "repeatability_deg": ("<=", 0.02),
    "time_to_home_median_s": ("<=", 60.0),
    "time_to_home_p95_s": ("<=", 90.0),
    "belt_after_liftoff": ("==", 0),
    "tripped": ("==", 0),
    "peak_speed_ratio": ("<=", SPEED_RATIO_MAX),
}
COVERAGE_ENV_MIN_PCT = 90.0
NOMINAL = "nominal"

# -- the start grid ------------------------------------------------------------------------------------------------------------------
# WHY these five-bar poses (bam_rack_twin full_arm, bam_ws main d6c263129: bench_real(), full_arm_cell("cap", 0), full_arm_tool(0) and
# bam_fivebar tool_ik / inverse_pose; tests/test_homing_routine.py re-derives them when bam_rack_twin imports): Craig (J2, C1) deg.
# "READY" here is the description's named pose "homing" (sim2real.named_poses; bam_ws PEP 0056), never a copy: READY's numbers until
# 2026-11-19 (65.246, 122.791; full_arm.ready_motors' TCP 40 mm over the bin's drop), where the homing routine runs and these cells were
# scored. WHY not "ready" since READY moved (2026-11-19): the ruler is the homing routine's, and the homing keeps its posture.
FIVEBAR_LEVELS = {
    "READY": fivebar_craig_deg(named_pose("homing")),  # the homing posture (READY until 2026-11-19): the cells were scored here
    "PICK": (86.31, 166.93),  # TCP (0.434, 0.575): 30 mm over the tray floor (0.605), mid-tray
    "LIFT": (96.65, 150.06),  # TCP (0.434, 0.455): 150 mm over the tray floor, the pick's lift
    "UP": (131.62, 170.70),  # TCP (0.300, 0.300): the arm raised toward the shoulder
}
WRIST_LEVELS_DEG = (-150.0, -90.0, -30.0, 30.0, 90.0, 150.0)
W3_LEVELS_DEG = (-120.0, 0.0, 120.0)
CLAW_LEVELS_DEG = (5.0, 40.0, 75.0)  # closed stop 0, open stop 77.09 (stops.json)
J1_LEVELS_DEG = (0.0, 6.0)  # the plane's tilt at power-on (fivebar_homed.J1_START_MAX_RAD: 8 deg)
SUBSET_EVERY = 6


def _latin(i: int, j: int) -> tuple[float, float, float]:
    """W3, claw and J1 for wrist cell (W1 index i, W2 index j): each level equally often over the 6 x 6, and no level tied to one W1 or W2."""
    return (W3_LEVELS_DEG[(i + j) % 3], CLAW_LEVELS_DEG[(i + 2 * j) % 3], J1_LEVELS_DEG[(i // 3 + j) % 2])


def grid_cells() -> list[dict]:
    """The 144 start cells (module docstring), in a fixed order: each a dict of ``fullarm_plant.ArmStart``'s fields plus ``cell`` (its
    grid index (five-bar level, i, j)). Pure: no simulator needed to list them."""
    out = []
    for level, (j2, c1) in FIVEBAR_LEVELS.items():
        for i, w1 in enumerate(WRIST_LEVELS_DEG):
            for j, w2 in enumerate(WRIST_LEVELS_DEG):
                w3, claw, j1 = _latin(i, j)
                out.append({"name": f"{level} W1 {w1:+.0f} W2 {w2:+.0f} W3 {w3:+.0f} claw {claw:.0f} J1 {j1:.0f}", "j2_deg": j2, "c1_deg": c1,
                            "wrist_deg": (w1, w2, w3), "claw_deg": claw, "knee": -1, "j1_deg": j1, "family": level,
                            "cell": {"fivebar": level, "i": i, "j": j}})
    return out


def subset_cells() -> list[dict]:
    """The perturbation environments' starts (24): per five-bar pose, the W1 / W2 diagonal (i + j + pose) mod 6 == 0 (amendment 3)."""
    levels = list(FIVEBAR_LEVELS)
    return [c for c in grid_cells() if (c["cell"]["i"] + c["cell"]["j"] + levels.index(c["cell"]["fivebar"])) % len(WRIST_LEVELS_DEG) == 0]


def folded_subset_cells() -> list[dict]:
    """Amendment 3's old subset - every 6th cell, i.e. W2 at -150 deg throughout (the folded wrist): reported apart."""
    return grid_cells()[::SUBSET_EVERY]


def tuning_cells(n: int = 6, seed: int = 20261113) -> list[dict]:
    """``n`` starts OFF the grid (uniform draws over the same ranges) - the only starts a routine's parameters may be tuned on."""
    import random  # noqa: PLC0415

    rng = random.Random(seed)
    out = []
    levels = list(FIVEBAR_LEVELS.items())
    for k in range(n):
        level, (j2, c1) = levels[k % len(levels)]
        w = tuple(round(rng.uniform(-160.0, 160.0), 1) for _ in range(3))
        out.append({"name": f"tuning {k} {level}", "j2_deg": j2, "c1_deg": c1, "wrist_deg": w, "claw_deg": round(rng.uniform(5, 75), 1),
                    "knee": -1, "j1_deg": 0.0, "family": f"tuning {level}", "cell": None})
    return out


# -- the environments ------------------------------------------------------------------------------------------------------------------
# plant: FullArmHomingPlant keyword arguments beyond belt / settle_all; prior: arm_prior's; table: identify_backlash's on that truth
SECOND_PHASE_DRAW_DEG = {"revolute_11": -14.2, "revolute_14": 6.6, "revolute_17": 16.1, "revolute_5": 9.8}
ENVIRONMENTS = {
    NOMINAL: {"kind": "B0", "truth": "cad", "why": "B0 (no gaps), CAD masses, the wrist's sliding friction, the calibration exact"},
    "B1": {"kind": "B1", "truth": "cad", "why": "hidden gear gaps, a dead zone (wrist 15 / 18 / 12 arcmin, the five-bar's rung gaps)"},
    "B2": {"kind": "B2", "truth": "cad", "why": "hidden gaps + mesh compliance (passive joint; 0.05 N.m/arcmin on the wrist)"},
    "friction": {"kind": "B0", "truth": "cad", "wrist_friction": "breakaway",
                 "why": "the wrist's breakaway friction (0.14-0.19 N.m) as its sliding one: 2.3-4.2x the twin's"},
    "claw_heavy": {"kind": "B0", "truth": "claw_high", "why": "the claw bracket at 0.50 kg (CAD 0.313, nominal 0.371)"},
    "phase_cal_error": {"kind": "B0", "truth": "cad", "phase_error_deg": 1.5,
                        "why": "the witness's rotor-phase calibration 1.5 deg off on every board"},
    "phase_draw_2": {"kind": "B0", "truth": "cad", "rotor_phase_deg": SECOND_PHASE_DRAW_DEG,
                     "why": "another power-up frame: every board's sub-turn phase redrawn (the calibration follows it)"},
}


# -- scoring -------------------------------------------------------------------------------------------------------------------------


def _p95(values: Sequence[float]) -> float | None:
    """Nearest-rank p95 (robot_models.homing.metrics' rule: a value an episode actually produced)."""
    values = sorted(values)
    if not values:
        return None
    return values[max(0, math.ceil(0.95 * len(values)) - 1)]


def scored_roles(report: dict) -> tuple:
    """The joints an episode is scored on: ``SCORED_ROLES``, plus J1 when its row homes J1 (amendment 5)."""
    return SCORED_ROLES + (("J1",) if report.get("homes_j1") else ())


def scored_errors(report: dict) -> dict:
    return {role: report["zero_error_deg"].get(role) for role in scored_roles(report)}


def wrong_stop(report: dict) -> bool:
    """A finished episode that used a stall more than WRONG_STOP_DEG off its CAD stop, or zeroed a scored joint more than that off."""
    if any(abs(s["link_deg"] - s["cad_deg"]) > WRONG_STOP_DEG for s in report.get("stalls", [])):
        return True
    return any(v is not None and abs(v) > WRONG_STOP_DEG for v in scored_errors(report).values())


def outcome_class(report: dict) -> str:
    """One of ``OUTCOMES`` for an episode report (``fullarm_check.EpisodeReport`` as a dict, or a refused-start row)."""
    if "refused_start" in report:
        return "infeasible"
    if report["finished"]:
        if wrong_stop(report):
            return "silent_wrong"
        errors = [v for v in scored_errors(report).values() if v is not None]
        if len(errors) < len(scored_roles(report)):
            return "silent_wrong"  # WHY: a routine that claims a home but leaves a scored joint unzeroed has not homed the arm
        return "homed" if max(abs(v) for v in errors) <= GATE_DEG else "inaccurate"
    outcome = report["outcome"]
    if outcome.startswith("refused"):
        return "refused"
    if "was not done within" in outcome or "bench limit" in outcome:
        return "timeout"  # amendment 4: the controller's step timeout reads "aborted: step ... was not done within"; it is no trip
    if outcome.startswith("tripped") or outcome.startswith("aborted"):
        return "tripped"
    return "timeout"


def clean(report: dict) -> bool:
    return report.get("belt_after_liftoff_ticks", 0) == 0


def covered(report: dict) -> bool:
    return outcome_class(report) == "homed" and clean(report)


def gap_errors_arcmin(report: dict) -> dict | None:
    """Wrist role -> |identified - hidden| gap (arcmin) when the routine identified every wrist gap itself, else None."""
    out = {}
    for role in WRIST_ROLES:
        found = report["gap_identified_deg"].get(role)
        if found is None:
            return None
        out[role] = abs(found - report["gap_truth_deg"][role]) * 60.0
    return out


def gap_gate_arcmin(truth_deg: float) -> float:
    return max(1.0, 0.25 * truth_deg * 60.0)


def score(reports: Iterable[dict]) -> dict:
    """``(routine, environment)`` -> its card: every aggregate in the module docstring, the outcome counts and the verdict per target."""
    groups: dict = {}
    for r in reports:
        key = (r.get("procedure") or r.get("job", {}).get("procedure_name"), r.get("environment") or r.get("job", {}).get("environment"))
        groups.setdefault(key, []).append(r)
    return {f"{routine} | {environment}": card(rows, environment) for (routine, environment), rows in groups.items()}


def card(rows: Sequence[dict], environment: str = NOMINAL) -> dict:
    counts = {name: 0 for name in OUTCOMES}
    for r in rows:
        counts[outcome_class(r)] += 1
    feasible = [r for r in rows if "refused_start" not in r]
    finished = [r for r in feasible if r["finished"]]
    homed = [r for r in feasible if outcome_class(r) == "homed"]
    out = {"cells": len(rows), "feasible": len(feasible), "outcomes": counts,
           "coverage_pct": round(100.0 * sum(1 for r in feasible if covered(r)) / len(feasible), 2) if feasible else None,
           "homed_pct": round(100.0 * len(homed) / len(feasible), 2) if feasible else None,
           "silent_wrong": counts["silent_wrong"], "tripped": counts["tripped"], "refused": counts["refused"]}
    worst = [max(abs(v) for v in scored_errors(r).values() if v is not None) for r in finished
             if any(v is not None for v in scored_errors(r).values())]
    out["zero_error_p95_deg"] = _p95(worst)
    roles = SCORED_ROLES + (("J1",) if any(r.get("homes_j1") for r in rows) else ())
    out["zero_error_p95_deg_by_joint"] = {role: _p95([abs(r["zero_error_deg"][role]) for r in finished if r["zero_error_deg"].get(role) is not None])
                                          for role in roles}
    spread = {}
    for role in roles:
        values = [r["zero_error_deg"][role] for r in finished if r["zero_error_deg"].get(role) is not None and not wrong_stop(r)]
        spread[role] = round(max(values) - min(values), 5) if len(values) >= 2 else None
    out["repeatability_deg_by_joint"] = spread
    out["repeatability_deg"] = max((v for v in spread.values() if v is not None), default=None)
    gaps = [g for g in (gap_errors_arcmin(r) for r in finished) if g is not None]
    out["backlash_identified_pct"] = round(100.0 * len(gaps) / len(finished), 2) if finished else None
    out["backlash_error_p95_arcmin"] = _p95([max(g.values()) for g in gaps])
    if gaps:
        truth = finished[0]["gap_truth_deg"]
        out["backlash_within_gate_pct"] = round(100.0 * sum(1 for g in gaps if all(g[k] <= gap_gate_arcmin(truth[k]) for k in g)) / len(gaps), 2)
    times = [r["time_s"] for r in homed if r.get("time_s") is not None]
    out["time_to_home_median_s"] = round(statistics.median(times), 2) if times else None
    out["time_to_home_p95_s"] = _p95(times)
    out["belt_after_liftoff"] = sum(1 for r in feasible if r.get("belt_after_liftoff_ticks", 0))
    out["belt_start_episodes"] = sum(1 for r in feasible if r.get("belt_start_bodies"))
    out["self_contact_episodes"] = sum(1 for r in feasible if r.get("self_contact_ticks", 0))
    ratios = []
    for r in feasible:
        for role, peak in (r.get("peak_speed_deg_s") or {}).items():
            ceiling = (r.get("speed_ceiling_deg_s") or {}).get(role)
            if ceiling and role != "J1":
                ratios.append(peak / ceiling)
    out["peak_speed_ratio"] = round(max(ratios), 3) if ratios else None
    out["verdict"] = verdict(out, environment)
    return out


def verdict(card_: dict, environment: str = NOMINAL) -> dict:
    """target -> pass / fail / None (not measured) for one card; ``pass`` overall only when every measured target passes."""
    out = {}
    for name, (op, bound) in TARGETS.items():
        if name == "coverage_pct" and environment != NOMINAL:
            bound = COVERAGE_ENV_MIN_PCT
        value = card_.get(name)
        if value is None:
            out[name] = None
            continue
        out[name] = {"==": value == bound, ">=": value >= bound, "<=": value <= bound}[op]
    out["pass"] = all(v for v in out.values() if v is not None)
    return out


__all__ = ["CLAW_LEVELS_DEG", "ENVIRONMENTS", "FIVEBAR_LEVELS", "GATE_DEG", "folded_subset_cells", "J1_LEVELS_DEG", "NOMINAL", "OUTCOMES", "SCORED_ROLES", "scored_roles", "TARGETS",
           "W3_LEVELS_DEG", "WRIST_LEVELS_DEG", "WRONG_STOP_DEG", "card", "clean", "covered", "grid_cells", "outcome_class", "score",
           "subset_cells", "tuning_cells", "verdict", "wrong_stop"]
