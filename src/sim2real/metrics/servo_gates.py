"""The servo acceptance gates T1-T11: a station's facts in, one verdict per gate out, every number judged by gate(value, target).

When does a servo count as "twinned"? T1-T11 of the servo-ID research note (zach_brain Projects/BAM Robotics/Notes/Servo System
Identification -- State of the Art and Our Plan (2026-10-25)). A gate is

- ``pass``: the evidence meets the target;
- ``fail``: the evidence misses it;
- ``partial``: the evidence is real but cannot settle the gate (an encoder-side stop error for an output-side gate, a twin scored on a
  proxy floor, a winding temperature never checked against a thermocouple);
- ``not_run``: no evidence. Never a pass.

A servo TYPE counts as twinned when its type gates pass (T1-T8); a UNIT when its unit gates do (T1, T2, T5, T6). Which gates those are,
and every target, is cards/ data (sim2real.cards.servo_gates); this module reads them as an argument, never imports them.

Moved from bam_rack_twin/acceptance.py (``evaluate`` and its T4 / T7 helpers) on 2026-11-10 (Zach, proposal 2 step 4: "the gates T1-T11
become calls into sim2real.metrics. Their targets go into cards/ as data"). The verdicts are unchanged to the bit: every acceptance file the
rack wrote since 2026-11-05 grades the same from its own facts (tests/test_servo_gates.py). The facts (what a gate reads: a floor, a twin
score, a stop tape ...) are the rack's to collect (bam_rack_twin.acceptance.collect); the WHY of each rule is kept beside it below.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from robot_msgs.space import Value, plain

from .gate import at_least, at_most, gate, required, rule_of

__all__ = ["Gate", "ServoTargets", "judged", "evaluate", "twinned", "GATE_IDS"]

GATE_IDS = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11")
REQUIRED = required(notes="a boolean requirement")


@dataclass(frozen=True)
class ServoTargets:
    """Every target T1-T11 read, as a robot_msgs Value (its range is the rule; its source says where the number comes from). The values
    are cards/ data (sim2real.cards.servo_gates.SERVO); the joint's own stop allocation (T4) is per station and passed to ``evaluate``."""

    floor_repeats: Value  # T1: identical repeats of one tape, at least
    fidelity_tapes: Value  # T2 (and T9, T10): twin error over the floor, at most
    fidelity_class: Value  # T2: in every dataset class, at most
    torque_ratio: Value  # T3: twin torque error over the run-to-run scatter, at most
    stops_per_direction: Value  # T4 (PEP 0007): stops from each approach direction, at least
    camera_share: Value  # T4 (PEP 0011): the camera gauge's error and the tag's floor, at most this share of the allocation
    gap_ci_half_arcmin: Value  # T5: backlash CI half-width, at most
    drive_gain_pct: Value  # T6: |known-mass torque error|, at most
    speed_pct: Value  # T7: top-speed error, at most
    current_limiter_share: Value  # T7 (PEP 0010): rows on the current limit on a current-limited plateau, at least
    thermocouple_c: Value  # T8: |winding model - thermocouple|, at most
    rules: Mapping[str, str] = field(default_factory=dict)  # gate id -> the rule in words (the gate table Vibe Tracks shows)


@dataclass(frozen=True)
class Gate:
    id: str
    name: str
    status: str  # pass | fail | partial | not_run
    value: Any
    target: Any
    detail: str
    # WHY judged + limit (sim2real audit round 2, 2026-10-29): a reader must see the number the verdict actually read beside its own limit.
    # ``value`` stays the headline (CAN 21 T2's overall 1.747) for the roll-ups that already read it; ``judged`` lists every number the
    # verdict reads ({name, value, rule, limit, passes}) and ``limit`` is the gate's numeric limit.
    judged: list[dict[str, Any]] = field(default_factory=list)
    limit: float | None = None


def _limit(target: Value) -> Any:
    return plain(rule_of(target)[1])


def judged(name: str, value: Any, target: Value) -> dict[str, Any]:
    """One number a verdict reads: {name, value, rule, limit, passes}, ``passes`` from gate(value, target) (None never passes)."""

    rule, limit = rule_of(target)
    return {"name": name, "value": value, "rule": rule, "limit": plain(limit), "passes": gate(value, target).passes}


def _gate(gate_id: str, name: str, status: str, value: Any = None, target: Any = None, detail: str = "",
          judgements: list[dict[str, Any]] | None = None, limit: float | None = None) -> Gate:
    return Gate(gate_id, name, status, value, target, detail, list(judgements or []), limit)


def _by_direction(approach: Mapping[str, Any], allocation: float, targets: ServoTargets) -> tuple[list[dict[str, Any]], list[str]]:
    """PEP 0007's per-direction rulers: (each direction's count and p90 judged, the under-covered directions named)."""

    out, short = [], []
    minimum = _limit(targets.stops_per_direction)
    for direction in ("positive", "negative"):
        entry = approach.get(direction) or {}
        n = int(entry.get("n") or 0)
        out.append(judged(f"stops approached from the {direction} side", n, targets.stops_per_direction))
        if entry.get("p90_mrad") is not None:
            out.append(judged(f"p90 stop error from the {direction} side, mrad", round(float(entry["p90_mrad"]), 3), at_most(allocation)))
        if not gate(n, targets.stops_per_direction).passes:
            short.append(f"{direction} side {n} of {minimum} stops" if approach else f"{direction} side not counted")
    return out, short


# WHY a direct drive's encoder settles T4 (2026-11-05, bam_ws docs/peps/0007-t4-direct-drive-output-encoder.md): T4 is "at the OUTPUT", and an
# encoder-side stop was partial because the rotor encoder over the ratio is blind to backlash and gear compliance. A direct drive has no gearbox
# (CAN 21's board "reports rotor radians, which ARE the output"), T5 already passes one on its camera-verified ratio alone, and the servo-ID
# note's K2 accepts "camera or output encoder", with stops from BOTH approach directions. So on a direct drive whose ratio is verified the
# encoder IS the output encoder; the count per direction is T1's repeat minimum. A geared joint's encoder stays partial.
def t4_direct_drive(stop: Mapping[str, Any], allocation: float, targets: ServoTargets) -> Gate:
    """T4 on a direct drive whose ratio is verified on camera: its own encoder is the output encoder. Pass needs ``stop["approach"]``
    with enough stops each way and the p90 within the allocation overall and in each direction; any p90 over it fails; an under-covered
    direction stays partial and is named."""

    p90 = round(stop["p90_mrad"], 3)
    out = [judged("p90 stop error, mrad (output: the direct drive's own encoder)", p90, at_most(allocation))]
    approach = stop.get("approach") or {}
    by_direction, short = _by_direction(approach, allocation, targets)
    out += by_direction
    over = [item for item in out if item["rule"] == "<=" and not item["passes"]]
    status = "fail" if over else "partial" if short else "pass"
    counts = " / ".join(f"{(approach.get(name) or {}).get('n', '?')} {sign}" for name, sign in (("positive", "+"), ("negative", "-")))
    detail = (f"output-side: the direct drive's own encoder (no gearbox; ratio verified on camera), {stop.get('n', '?')} stops ({counts}), "
              f"{stop.get('variant', 'plain PD')}" + (f"; both approach directions needed (K2): {', '.join(short)}" if short and not over else ""))
    return _gate("T4", "static accuracy", status, p90, f"p90 <= {allocation} mrad at the output, both approach directions", detail, out, allocation)


# WHY a geared joint's output from camera dwells, and only under these conditions (2026-11-06, bam_ws docs/peps/0011-t4-geared-output-by-camera-
# dwell.md section 5): a geared joint's rotor encoder cannot see its gearbox, so T4 stays partial there unless something reads the output. The
# camera dwell ruler reads it, but a camera is a gauge with its own error: it may grade only when, in the same lit session, it is proven on a
# direct drive's encoder (held-out p90 |camera - encoder|) and the station's own tag stands still to within the same share of the allocation
# (a third). The grade itself is PEP 0007's: both approach directions, each within the allocation.
def t4_output_camera(camera: Mapping[str, Any], allocation: float, stop: Mapping[str, Any] | None, targets: ServoTargets) -> Gate:
    """T4 at a geared joint's output from a camera stop tape (``camera``: the rack's stop_camera.output_fact). Graded by PEP 0007's direction
    rule when its four conditions hold in one lit session; otherwise partial on the encoder side (``stop``), the unmet conditions named."""

    limit = _limit(targets.camera_share) * allocation
    oracle, tag_floor, stops, light = (camera.get(name) or {} for name in ("oracle", "tag_floor", "stops", "light"))
    sessions = [camera.get("lit_session"), oracle.get("lit_session"), tag_floor.get("lit_session"), stops.get("lit_session")]
    oracle_p90, floor_p90 = oracle.get("p90_mrad"), tag_floor.get("p90_mrad")
    conditions = [
        ("lit", judged("room lit: every needed tag raw in >= 95 % of the light check's frames", bool(light.get("lit")), REQUIRED)),
        ("one lit session", judged("light check, oracle, tag floor and stop tape in one lit session", None not in sessions and len(set(sessions)) == 1,
                                   REQUIRED)),
        ("oracle", judged("oracle: a direct drive's held-out p90 |camera - encoder|, mrad",
                          round(float(oracle_p90), 3) if oracle_p90 is not None else math.inf, at_most(round(limit, 3)))),
        ("floor", judged("the station tag's static floor over the 2 s tail, p90 mrad", round(float(floor_p90), 3) if floor_p90 is not None else math.inf,
                         at_most(round(limit, 3)))),
    ]
    unmet = [word for word, item in conditions if not item["passes"]]
    out = [item for _, item in conditions]
    if not unmet and stops.get("p90_mrad") is None:
        unmet = ["no graded camera stop"]
    if unmet:
        encoder = None if not stop else round(stop["p90_mrad"], 3)
        if encoder is not None:
            out.append(judged(f"p90 stop error, mrad ({stop.get('side')}-side)", encoder, at_most(allocation)))
        detail = (f"the camera cannot grade the output yet ({', '.join(unmet)} not met: a third of {allocation} mrad is {limit:.2f}); "
                  + (f"{stop.get('side')}-side, {stop.get('n', '?')} stops, {stop.get('variant', 'plain PD')}" if stop else "no encoder-side stops"))
        return _gate("T4", "static accuracy", "partial", encoder, f"p90 <= {allocation} mrad at the output", detail, out, allocation)
    p90 = round(float(stops["p90_mrad"]), 3)
    out.append(judged("p90 stop error, mrad (output: the camera's dwell tails)", p90, at_most(allocation)))
    by_direction, short = _by_direction(stops.get("approach") or {}, allocation, targets)
    out += by_direction
    over = [item for item in out if item["rule"] == "<=" and not item["passes"]]
    status = "fail" if over else "partial" if short else "pass"
    counts = " / ".join(f"{((stops.get('approach') or {}).get(name) or {}).get('n', '?')} {sign}" for name, sign in (("positive", "+"), ("negative", "-")))
    detail = (f"output-side: the camera's dwell tails (PEP 0011) in lit session {sessions[0]}, {stops.get('n', '?')} stops ({counts}); oracle "
              f"{oracle_p90:.2f} and tag floor {floor_p90:.2f} mrad within {limit:.2f}" + (f"; both approach directions needed (K2): {', '.join(short)}" if short and not over else ""))
    return _gate("T4", "static accuracy", status, p90, f"p90 <= {allocation} mrad at the output, both approach directions", detail, out, allocation)


# WHY T7 on a current-limited plateau (2026-11-05, bam_ws docs/peps/0010-t7-current-limited-plateau.md): a joint whose current limit binds below
# its back-EMF line (CAN 12 at 4 A: the twin's top speed 21.5 rad/s, its voltage line binding only above 23.2) never reaches the voltage limit
# T7's only evidence path read, so it stayed not_run. Its top speed is the current-limited plateau; T7 grades it there with its own 5 %
# tolerance, and "limits reproduced" means the same limit binds on both sides, judged number by number.
def t7_current_limited(envelope: Mapping[str, Any], targets: ServoTargets) -> Gate:
    """T7 from a current-limited plateau fact: the real plateau, the twin's on its replay of the same run, the shares of their rows on the
    current limit, and the twin's back-EMF line."""

    speed_pct = _limit(targets.speed_pct)
    real, twin = envelope.get("real_top_speed_rad_s"), envelope.get("twin_top_speed_rad_s")
    error = envelope.get("speed_error_pct")
    if error is None and real and twin is not None:
        error = abs(twin - real) / real * 100
    out = [judged("top-speed error, % (the twin's current-limited plateau against the real one)", error if error is not None else math.inf, targets.speed_pct),
           judged("board on its current limiter on the real plateau (share of rows)", envelope.get("board_limiter_share") or 0.0, targets.current_limiter_share),
           judged("twin at its current limit on its own plateau (share of rows)", envelope.get("twin_current_share") or 0.0, targets.current_limiter_share),
           judged("twin's back-EMF line above the real plateau, rad/s", envelope.get("voltage_binds_above_rad_s") or 0.0, at_least(real if real else math.inf))]
    status = "pass" if all(item["passes"] for item in out) else "fail"
    detail = (f"current-limited plateau: real {real if real is not None else '?'} rad/s, twin {twin if twin is not None else '?'} rad/s"
              + (f" ({envelope['run']})" if envelope.get("run") else "") + "; the back-EMF line binds only above "
              f"{envelope.get('voltage_binds_above_rad_s', '?')} rad/s")
    return _gate("T7", "envelope", status, error, f"current-limited top speed within {speed_pct}%, the current limit reproduced", detail, out, speed_pct)


def evaluate(facts: Mapping[str, Any], targets: ServoTargets, *, allocation_mrad: float | None) -> list[Gate]:
    """T1-T11 for one station: ``facts`` as the rack collects them (bam_rack_twin.acceptance.collect / facts_from_metrics), ``targets`` the
    cards' (sim2real.cards.servo_gates.SERVO), ``allocation_mrad`` the joint's share of the 5 mm tool gate (T4; None: no allocation, T4 not run)."""

    floor_repeats, fidelity_tapes, fidelity_class = (_limit(targets.floor_repeats), _limit(targets.fidelity_tapes), _limit(targets.fidelity_class))
    torque_ratio, gap_ci, drive_gain = _limit(targets.torque_ratio), _limit(targets.gap_ci_half_arcmin), _limit(targets.drive_gain_pct)
    speed_pct, thermocouple_c = _limit(targets.speed_pct), _limit(targets.thermocouple_c)
    allocation = allocation_mrad
    gates = []
    floor = facts.get("floor")
    if not floor:
        gates.append(_gate("T1", "floor", "not_run", detail="no repeated identical runs"))
    else:
        ok = floor.get("kind") == "repeats" and gate(floor.get("repeats", 0), targets.floor_repeats).passes
        gates.append(_gate("T1", "floor", "pass" if ok else "fail", floor.get("mrad"), f">= {floor_repeats} identical repeats",
                           f"{floor.get('kind')} floor from {floor.get('repeats', 0)} repeats",
                           [judged("identical repeats", floor.get("repeats", 0) if floor.get("kind") == "repeats" else 0, targets.floor_repeats)],
                           floor_repeats))
    twin = facts.get("twin_mrad")
    classes = facts.get("class_ratio") or {}
    if twin is None or not floor:
        gates.append(_gate("T2", "fidelity", "not_run", detail="no held-out twin score or no floor"))
    else:
        ratio = twin / floor["mrad"]
        worst_class = max(classes.values(), default=None)
        ok = gate(ratio, targets.fidelity_tapes).passes and (worst_class is None or gate(worst_class, targets.fidelity_class).passes)
        if floor.get("kind") != "repeats":
            status, detail = "partial", "scored on a proxy floor: the denominator is not the rack against itself"
        else:
            status, detail = ("pass" if ok else "fail"), f"worst dataset class {worst_class}"
        split = facts.get("t2_split")
        out = [judged("tapes", round(ratio, 3), targets.fidelity_tapes)] + (
            [judged("worst dataset class", worst_class, targets.fidelity_class)] if worst_class is not None else [])
        if split and floor.get("kind") == "repeats":
            out = [judged("moves", split["moves_over_floor"], targets.fidelity_tapes),
                   judged("hold offset", round(split["hold_offset_over_floor"], 3), targets.fidelity_tapes)]
            # WHY judged on the split (2026-10-25, Zach's default pick, auto-taken while he was away and his to overrule): at ki = 0 a stop
            # lands anywhere in the friction band and the rack does not repeat where (twin rounds 8-10), so holds are scored by their
            # offset against the rack's own repeatability and moves by RMS over the floor's moving part; the overall ratio stays visible
            # WHY judged here and not read from split["passes"] (2026-11-10, step 4): the flag was the fact collector's own verdict, so a
            # target moved in cards could not regrade it; every one of the 1,053 splits on the rack archive agrees with this judgement
            status = ("pass" if gate(split["moves_over_floor"], targets.fidelity_tapes).passes
                      and gate(split["hold_offset_over_floor"], targets.fidelity_tapes).passes else "fail")
            detail = (f"split: moves {split['moves_over_floor']:.2f}x, hold offset {split['hold_offset_over_floor']:.2f}x the floor "
                      f"(<= {fidelity_tapes} each); overall {ratio:.1f}x, {detail}")
        target = (f"moves <= {fidelity_tapes}x and hold offset <= {fidelity_tapes}x the floor's parts" if split and floor.get("kind") == "repeats"
                  else f"<= {fidelity_tapes} (tapes), <= {fidelity_class} per class")
        if facts.get("floor_note"):  # WHY (2026-11-04): a verdict over the pooled floor says so; the session floor's text is unchanged
            detail += f"; {facts['floor_note']}"
        gates.append(_gate("T2", "fidelity", status, round(ratio, 3), target, detail, out, fidelity_tapes))
    torque = facts.get("torque_ratio")
    gates.append(_gate("T3", "torque", "not_run" if torque is None else ("pass" if gate(torque, targets.torque_ratio).passes else "fail"), torque,
                       f"<= {torque_ratio}x repeat",
                       judgements=[judged("twin torque error over the run-to-run scatter", torque, targets.torque_ratio)] if torque is not None else [],
                       limit=torque_ratio))
    stop = facts.get("stop")
    blind_t4 = facts.get("encoder_blind") or {}
    direct_drive = bool(blind_t4.get("direct_drive") and blind_t4.get("ratio_verified"))
    if allocation is not None and facts.get("output_camera") and not blind_t4.get("direct_drive"):
        gates.append(t4_output_camera(facts["output_camera"], allocation, stop, targets))
    elif not stop or allocation is None:
        gates.append(_gate("T4", "static accuracy", "not_run", target=allocation))
    elif stop.get("side") == "encoder" and direct_drive:
        gates.append(t4_direct_drive(stop, allocation, targets))
    else:
        within = gate(stop["p90_mrad"], at_most(allocation)).passes
        status = ("pass" if within else "fail") if stop.get("side") == "output" else ("partial" if within else "fail")
        gates.append(_gate("T4", "static accuracy", status, round(stop["p90_mrad"], 3), f"p90 <= {allocation} mrad at the output",
                           f"{stop.get('side')}-side, {stop.get('n', '?')} stops, {stop.get('variant', 'plain PD')}",
                           [judged(f"p90 stop error, mrad ({stop.get('side')}-side)", round(stop["p90_mrad"], 3), at_most(allocation))], allocation))
    blind = facts.get("encoder_blind")
    if not blind:
        gates.append(_gate("T5", "encoder-blind terms", "not_run"))
    elif blind.get("direct_drive"):
        gates.append(_gate("T5", "encoder-blind terms", "pass" if blind.get("ratio_verified") else "partial", detail="direct drive: no gear gap",
                           judgements=[judged("ratio verified", bool(blind.get("ratio_verified")), REQUIRED)]))
    else:
        parts = {
            "ratio": bool(blind.get("ratio_verified")),
            "gap": gate(blind.get("gap_ci_half_arcmin") or math.inf, targets.gap_ci_half_arcmin).passes,
            "stiffness": bool(blind.get("stiffness_measured")),
        }
        status = "pass" if all(parts.values()) else ("partial" if any(parts.values()) or blind.get("gap_ci_half_arcmin") else "fail")
        gates.append(_gate("T5", "encoder-blind terms", status, blind.get("gap_ci_half_arcmin"), f"ratio, gap CI half <= {gap_ci}', stiffness",
                           ", ".join(f"{name} {'ok' if ok else 'missing'}" for name, ok in parts.items()),
                           [judged("ratio verified", parts["ratio"], REQUIRED),
                            judged("gap CI half-width, arcmin", blind.get("gap_ci_half_arcmin"), targets.gap_ci_half_arcmin),
                            judged("stiffness measured", parts["stiffness"], REQUIRED)], gap_ci))
    gain = facts.get("drive_gain_error_pct")
    gates.append(_gate("T6", "drive gain", "not_run" if gain is None else ("pass" if gate(abs(gain), targets.drive_gain_pct).passes else "fail"), gain,
                       f"<= {drive_gain}%",
                       judgements=[judged("|known-mass torque error|, %", abs(gain), targets.drive_gain_pct)] if gain is not None else [], limit=drive_gain))
    envelope = facts.get("envelope")
    if not envelope:
        gates.append(_gate("T7", "envelope", "not_run"))
    elif envelope.get("limit") == "current":
        gates.append(t7_current_limited(envelope, targets))
    else:
        ok = gate(envelope.get("speed_error_pct", math.inf), targets.speed_pct).passes and envelope.get("limits_reproduced", False)
        gates.append(_gate("T7", "envelope", "pass" if ok else "fail", envelope.get("speed_error_pct"), f"speed within {speed_pct}%, limits reproduced",
                           judgements=[judged("top-speed error, %", envelope.get("speed_error_pct", math.inf), targets.speed_pct),
                                       judged("limits reproduced", bool(envelope.get("limits_reproduced", False)), REQUIRED)], limit=speed_pct))
    thermal = facts.get("thermal")
    if not thermal:
        gates.append(_gate("T8", "thermal", "not_run"))
    elif thermal.get("status") != "measured":
        gates.append(_gate("T8", "thermal", "fail", detail="; ".join(thermal.get("why", [])) or "winding fit refused"))
    elif thermal.get("thermocouple_error_c") is None:
        gates.append(_gate("T8", "thermal", "partial", thermal.get("continuous_a"), detail="never checked against a thermocouple"))
    else:
        ok = gate(abs(thermal["thermocouple_error_c"]), targets.thermocouple_c).passes
        gates.append(_gate("T8", "thermal", "pass" if ok else "fail", thermal["thermocouple_error_c"], f"within {thermocouple_c} degC",
                           judgements=[judged("|winding model - thermocouple|, degC", abs(thermal["thermocouple_error_c"]), targets.thermocouple_c)],
                           limit=thermocouple_c))
    # WHY a written limit and the source as detail (sim2real audit round 2): T9 / T10 read "limit: none written" and the app had to fetch an
    # older warm file's numbers to explain them; the study that wrote the fact names its model and the other numbers it saw
    for gate_id, name, key, rule in (("T9", "warm and cold", "warm_cold_ratio", f"twin error warm and cold <= {fidelity_tapes}x the floor"),
                                     ("T10", "live re-identification", "live_reid_restores", f"twin error after the live routine <= {fidelity_tapes}x the floor")):
        value = facts.get(key)
        source = facts.get(key.replace("_ratio", "").replace("_restores", "") + "_source") or ""
        # WHY the warm note first (2026-11-05): T9 is over the warm session's pooled floor, which warm_floor_note names; floor_note is T2's, and
        # once a station's T2 moved to a session of its own (CAN 21's session C) it named the wrong floor
        if gate_id == "T9" and (facts.get("warm_floor_note") or facts.get("floor_note")):
            source += f"; {facts.get('warm_floor_note') or facts['floor_note']}"
        if value is None:
            gates.append(_gate(gate_id, name, "not_run", target=rule, limit=fidelity_tapes))
        else:
            ok = bool(value) if isinstance(value, bool) else gate(value, targets.fidelity_tapes).passes
            out = [judged("restored", bool(value), REQUIRED)] if isinstance(value, bool) else [judged("over the floor", value, targets.fidelity_tapes)]
            gates.append(_gate(gate_id, name, "pass" if ok else "fail", value, rule, source, out, fidelity_tapes))
    provenance = facts.get("provenance")
    if not provenance:
        gates.append(_gate("T11", "provenance", "not_run"))
    else:
        ok = provenance["complete"] == provenance["terms"] and provenance.get("firmware") and provenance.get("config_hash")
        gates.append(_gate("T11", "provenance", "pass" if ok else "partial", f"{provenance['complete']}/{provenance['terms']}",
                           "every term with value, grade and evidence; firmware and config hash",
                           judgements=[judged("terms with value, grade and evidence", provenance["complete"], at_least(provenance["terms"])),
                                       judged("firmware and config hash", bool(provenance.get("firmware") and provenance.get("config_hash")), REQUIRED)],
                           limit=provenance["terms"]))
    # WHY every gate carries its rule and limit (sim2real audit round 2): a not_run or refused cell read "limit: none written", which hides what
    # the gate asks for; the rule text is the cards', the limit the target evaluate() compares against
    limits = {"T1": floor_repeats, "T2": fidelity_tapes, "T3": torque_ratio, "T4": allocation, "T5": gap_ci, "T6": drive_gain, "T7": speed_pct,
              "T8": thermocouple_c, "T9": fidelity_tapes, "T10": fidelity_tapes}
    return [Gate(g.id, g.name, g.status, g.value, g.target or targets.rules[g.id], g.detail, g.judged, g.limit if g.limit is not None else limits.get(g.id))
            for g in gates]


def twinned(gates: Sequence[Gate], required_gates: Sequence[str]) -> bool:
    """True when every gate in ``required_gates`` is present and passes (the cards' TYPE_GATES or UNIT_GATES)."""

    by_id = {item.id: item for item in gates}
    return all(by_id.get(gate_id) is not None and by_id[gate_id].status == "pass" for gate_id in required_gates)
