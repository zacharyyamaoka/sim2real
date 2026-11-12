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
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from .metrics.series import SAME_INPUT_TOLERANCE_RAD, RepeatFloor, pair_rms, repeat_floor
from .result import FLOOR_CHECK, RULER_TWINNED, TOOL_GATE_MM, CalibrationResult, Node, verdict_of

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


def best_floor(floors: dict) -> tuple[object, RepeatFloor] | tuple[None, None]:
    """The group (run kind x controller config) with the most same-input repeats: known ones first, then by runs and pairs."""
    ranked = sorted(floors.items(), key=lambda kv: (kv[1].known, kv[1].runs, kv[1].pairs), reverse=True)
    return ranked[0] if ranked and ranked[0][1].pairs else (None, None)


def floor_text(floors: dict, key, floor: RepeatFloor | None) -> str:
    tol = math.degrees(SAME_INPUT_TOLERANCE_RAD)
    groups = sum(1 for f in floors.values() if f.pairs)
    if floor is None:
        rejected = sum(f.rejected for f in floors.values())
        return (f"driven: floor unknown, no same-input pair (commands within {tol:g}°) in {len(floors)} groups; {rejected} candidate "
                f"pairs had different inputs; passive: no free-response runs")
    state = "known" if floor.known else f"unknown: {floor.runs} runs < {floor.min_repeats}"
    return (f"driven {math.degrees(floor.value):.3f}° ({state}; {floor.pairs} same-input pairs over {floor.runs} runs, {' / '.join(map(str, key))}; "
            f"{groups} groups had any); passive: no free-response runs")


def twin_ratio(floor: RepeatFloor | None, twin_deg) -> float | None:
    return twin_deg / math.degrees(floor.value) if floor is not None and floor.known and twin_deg else None


PASSIVE_NA_RULE = "proposed, Zach to confirm"   # a joint that cannot move unpowered answers passive "N/A" with its reason


def joint_questions(*, driven: dict, passive: dict, before_deg, target_deg, coverage_text: str, routines: str,
                    routines_own: str = "partial") -> dict:
    """A joint's own answers (proposal C), from its driven and passive evidence.

    driven  = {floor_deg, pairs, runs, known, kind, twin_deg, note}: the floor of ONE run kind and the twin on that same kind (T1).
    passive = {state: known | na | none, floor_deg, twin_deg, reason, note}. WHY "na" (coordinator, 2026-11-11, proposed, Zach to
    confirm): a joint whose gravity torque is under its breakaway cannot move unpowered, so no free response exists to repeat; it
    answers "N/A, with the reason" instead of failing Floor forever. Floor = driven known AND passive known or N/A; a twin below
    1/sqrt(2) of its floor fails Floor (those repeats were not repeats)."""
    tol = math.degrees(SAME_INPUT_TOLERANCE_RAD)
    d_ratio = driven["twin_deg"] / driven["floor_deg"] if driven.get("known") and driven.get("twin_deg") else None
    p_ratio = (passive["twin_deg"] / passive["floor_deg"]) if passive["state"] == "known" and passive.get("twin_deg") else None
    if driven.get("floor_deg") is not None:
        d_text = (f"driven {driven['floor_deg']:.3f}° on {driven['kind']} ({'known' if driven['known'] else 'unknown'}: "
                  f"{driven['pairs']} same-input pairs over {driven['runs']} runs{', ' + driven['note'] if driven.get('note') else ''})")
    else:
        d_text = f"driven: floor unknown ({driven.get('note') or 'no same-input pair within ' + format(tol, 'g') + '°'})"
    p_text = {"known": f"passive {passive.get('floor_deg', 0):.3f}° ({passive.get('note', '')})",
              "na": f"passive N/A: {passive.get('reason', '')} ({PASSIVE_NA_RULE})",
              "none": "passive: no free-response runs"}[passive["state"]]
    too_low = [r for r in (d_ratio, p_ratio) if r is not None and r < FLOOR_CHECK]
    floor_ok = bool(driven.get("known")) and passive["state"] in ("known", "na") and not too_low
    floor_note = d_text + "; " + p_text + ("; twin ÷ floor below 0.71×: those repeats were not repeats" if too_low else "")
    twin_parts = [f"driven {driven['twin_deg']:.3f}°" + (f" = {d_ratio:.2f}× floor ({verdict_of(d_ratio)})" if d_ratio is not None
                                                          else " (no known floor to divide by)") if driven.get("twin_deg") is not None
                  else "driven: no twin on this kind"]
    if before_deg is not None:
        twin_parts.append(f"held-out twin before the refit {before_deg:.3f}°")
    twin_parts.append({"known": (f"passive {passive['twin_deg']:.2f}° = {p_ratio:.1f}× floor ({verdict_of(p_ratio)})" if p_ratio is not None
                                 else "passive: no twin replay"),
                       "na": "passive N/A", "none": "passive: none"}[passive["state"]])
    if d_ratio is None:
        twin_own = "unknown"
    else:
        driven_ok = FLOOR_CHECK <= d_ratio <= RULER_TWINNED
        passive_ok = passive["state"] == "na" or (p_ratio is not None and p_ratio <= RULER_TWINNED)
        twin_own = "yes" if driven_ok and passive_ok else "no"
    skill = target_deg / driven["twin_deg"] if driven.get("twin_deg") and target_deg else None
    return {
        "Floor": {"own": "yes" if floor_ok else "no", "numbers": floor_note,
                  "gate": f"≥ 5 repeats of one input (within {tol:g}°) per run kind, passive and driven (passive N/A when it cannot move unpowered)"},
        "Data": {"own": "unknown", "numbers": coverage_text, "gate": "≥ 40 % of reachable (angle, speed, acceleration) cells; no reachable mask committed"},
        "Routines": {"own": routines_own, "numbers": routines, "gate": "hidden values within tolerance at 1× noise, truth off the grid"},
        "Twin": {"own": twin_own, "numbers": "; ".join(twin_parts), "gate": f"held-out sim→real ≤ {RULER_TWINNED:g}× floor of the same run kind, passive and driven"},
        "Job": {"own": "unknown", "numbers": (f"real vs target {target_deg:.3f}°" if target_deg else "real vs target —")
                + ((f"; the twin predicts the real joint {skill:.1f}× better than its target does" if skill >= 1 else
                    f"; the twin is {1 / skill:.1f}× further from the real joint than its target is (no skill yet)") if skill else ""),
                "gate": "stop error inside this joint's share of the 1 mm tool gate (share not set); feedback share (not logged)"},
    }


def floors_rows(floors: dict, twins: dict, mode: str, source: str) -> list[dict]:
    """The page's per-kind floor table: every group with a same-input pair, its floor, and the twin on that same kind."""
    rows = []
    for key, f in sorted(floors.items(), key=lambda kv: -kv[1].pairs):
        if not f.pairs:
            continue
        floor_deg = math.degrees(f.value)
        twin = twins.get(key)
        rows.append({"kind": " / ".join(map(str, key)), "mode": mode, "floor_deg": _r(floor_deg, 4), "pairs": f.pairs, "runs": f.runs,
                     "known": f.known, "twin_deg": _r(twin), "twin_over_floor": _r(twin / floor_deg, 2) if twin else None,
                     "verdict": verdict_of(twin / floor_deg) if twin and f.known else ("floor unknown" if not f.known else "no twin"),
                     "source": source})
    return rows


# ------------------------------------------------------------------------------------------------------------------- UR wrist

REPEAT_FLOOR = WRIST / ".." / "repeat_floor"
# the one-click calibration of the wrist on a sealed truth at 1x noise (sim2real 82f14db, its green run's rows): the Routines question
ONE_CLICK = Path(__file__).resolve().parent / "data" / "ur_wrist_one_click_2026-11-11.json"


TOOL_LEVERS = Path(__file__).resolve().parent / "data" / "tool_levers_2026-11-11.json"   # tools/tool_levers.py, each rig's own FK
SETTLED_AFTER_S = 0.3   # a row counts as settled once its target has rested this long (the seam's tool_error_at_stops rule)


def joint_share_deg(lever_mm_per_rad: float, joints: int) -> float:
    """The joint's share of the tool gate, an RSS split (proposed, Zach to confirm): TOOL_GATE_MM / (lever x sqrt(n_joints)), in degrees."""
    return math.degrees(TOOL_GATE_MM / (lever_mm_per_rad * math.sqrt(joints)))


def settled_errors_deg(t: np.ndarray, q: np.ndarray, target: np.ndarray) -> np.ndarray:
    """|q - target| (deg) on the rows whose target has not moved for SETTLED_AFTER_S."""
    target = np.asarray(target, float)
    moved = np.r_[True, np.abs(np.diff(np.nan_to_num(target))) > 1e-9] | ~np.isfinite(target)
    since = np.zeros(t.size)
    start = t[0]
    for k in range(t.size):
        if moved[k]:
            start = t[k]
        since[k] = t[k] - start
    keep = (since >= SETTLED_AFTER_S) & np.isfinite(target) & np.isfinite(q)
    return np.degrees(np.abs(q[keep] - target[keep]))


def job_answer(share_deg: float, lever_mm: float, joints: int, settled_deg: list, where: str, soft: str) -> dict:
    """A joint's Job: its settled error vs target (median, p95 beside it) against its share of the 1 mm tool gate. Unknown without data."""
    gate = (f"settled error ≤ {share_deg:.3f}°: its share of the {TOOL_GATE_MM:g} mm tool gate, 1 mm ÷ (lever {lever_mm:.0f} mm/rad × "
            f"√{joints}) (an RSS split, proposed, Zach to confirm)")
    values = np.asarray([v for v in settled_deg if np.isfinite(v)], float)
    if not values.size:
        return {"own": "unknown", "numbers": f"no settled data; share {share_deg:.3f}°; {soft}", "gate": gate}
    med, p95 = float(np.median(values)), float(np.percentile(values, 95))
    return {"own": "yes" if med <= share_deg else "no",
            "numbers": f"settled {med:.3f}° median, {p95:.3f}° p95 over {values.size} {where} vs its share {share_deg:.3f}° "
                       f"({med / share_deg:.1f}×); {soft}", "gate": gate}


def routines_from_rows(rows: list[dict], prefix: str, stress: str = "noise stress: pending (the stress lane is running)") -> dict:
    """A node's Routines answer from the one-click calibration's rows under `prefix` (can15. / wrist.): yes when every IDENTIFIABLE
    row recovers its hidden truth within tolerance at 1x noise; an unidentifiable one is listed "not identifiable (reason)", never a
    fail (coordinator, 2026-11-11)."""
    mine = [r for r in rows if r["key"].startswith(prefix)]
    found = [r for r in mine if r["routine"]]
    missed = [r for r in found if not r["pass"]]
    not_identifiable = [r for r in mine if not r["routine"]]
    if not found:
        return {"own": "unknown", "numbers": "no identifiable parameter at this level", "gate": ""}
    names = ", ".join(r["title"] for r in found)
    text = (f"{len(found) - len(missed)}/{len(found)} identifiable recovered within tolerance at 1x noise, sealed truth ({names})"
            + (f"; MISSED: {', '.join(r['title'] for r in missed)}" if missed else "")
            + ("; not identifiable: " + "; ".join(f"{r['title']} ({(r['why_not'] or '')[:90]})" for r in not_identifiable) if not_identifiable else "")
            + f"; {stress}")
    return {"own": "yes" if not missed else "no", "numbers": text,
            "gate": "every identifiable parameter within its tolerance of the sealed truth at 1x noise (sim2real one-click seam)"}


# the coverage lane's reachable mask (bam_ws claude/ur-wrist-coverage @ eef94b778, schema bam_ur_wrist_coverage.reachable/1): its joint
# descriptions and the PROPOSED good-data thresholds. WHY two places, main first (coordinator, 2026-11-11): bam_ws main's copy once the
# lane lands, so a worktree sweep cannot break the page; the lane's worktree only until then
_REACHABLE = "src/dev/bam_ur_wrist_coverage/bam_ur_wrist_coverage/data/reachable_2026-11-11.json"
REACHABLE_EXPORT_CANDIDATES = (Path("/home/bam/bam_ws") / _REACHABLE, Path("/home/bam/bam_ws-worktrees/ur-wrist-coverage") / _REACHABLE)
REACHABLE_EXPORT = next((path for path in REACHABLE_EXPORT_CANDIDATES if path.exists()), REACHABLE_EXPORT_CANDIDATES[0])
MULTI3 = WRIST / "multi3"


def joint_data(description: dict, samples: list[tuple[np.ndarray, np.ndarray, np.ndarray]], threshold_pct: float, status: str) -> dict:
    """A joint's Data answer: the share of its reachable (q, qd, qdd) cells (sim2real.schedule.joint: edges_of, reachable_cells,
    occupancy) that real samples visited, against the coverage lane's PROPOSED threshold. Caveat (the lane's): reachable_cells marks
    every cell of the box reachable for these joints, so this is the visited share of the full box."""
    from .schedule.joint import JointDescription, edges_of, occupancy, reachable_cells

    edges = edges_of(description)
    reachable = reachable_cells(JointDescription.from_json(description), edges)
    origin = description["origin_rad"]
    # WHY wrapped into the range's own turn: a revolute joint's logged angle may sit a turn away from its description's frame (the
    # five-bar's C1 logs 64..255 deg for a range written -304..-93 deg); wrapping into [low, low + 360) keeps a range wider than +-180
    # (the wrist's CAN 14: -248..+73 deg from its origin) whole, where a plain +-180 wrap pushed real samples out of it
    low = description["range_rad"][0]
    rows = [np.column_stack([low + (q - origin - low) % (2 * np.pi), qd, qdd]) for q, qd, qdd in samples if len(q)]
    counts = occupancy(np.vstack(rows), edges) if rows else np.zeros(reachable.shape, int)
    visited = int(((counts > 0) & reachable).sum())
    pct = 100.0 * visited / max(1, int(reachable.sum()))
    caveat = " (reachable_cells marks the whole box: the visited share of the full box)" if reachable.all() else ""
    return {"own": "yes" if pct >= threshold_pct else "no",
            "numbers": f"{pct:.1f} % of {int(reachable.sum())} reachable (q, qd, qdd) cells visited by {sum(len(r) for r in rows)} real samples{caveat}",
            "gate": f"≥ {threshold_pct:g} % of reachable cells ({status})"}


# WHY N/A (the real lane, 2026-11-11; proposed, Zach to confirm): CAN 15 and 16 carry at most 0.012 N·m of gravity against 0.14-0.19 N·m
# of breakaway (refit_rig it5 static friction), so released they do not move: no passive response exists to repeat
PASSIVE_NA = {15: "it cannot move unpowered: ≤ 0.012 N·m of gravity against 0.140 N·m breakaway (refit_rig it5)",
              16: "it cannot move unpowered: ≤ 0.012 N·m of gravity against 0.186 N·m breakaway (refit_rig it5)"}


def repeat_campaign() -> dict[int, dict]:
    """The real lane's dedicated repeat-floor campaign (ur_wrist/repeat_floor: 5 identical repeats per joint, floor_scores.json and the
    twin of record's replays, twin_scores.json). Driven floors are recomputed with metrics.series.repeat_floor on the lane's own
    same-input window (every run shifted by one constant, never by its own first sample); the passive release's floor is the lane's
    (its input is a release from a start that varies ~1°, which no command check can compare)."""
    root = REPEAT_FLOOR.resolve()
    if not (root / "floor_scores.json").exists():
        return {}
    floor_scores = json.loads((root / "floor_scores.json").read_text())["groups"]
    twin_groups = {(g["can_id"], g["trajectory"], g["mode"]): g for g in json.loads((root / "twin_scores.json").read_text())["groups"]}
    out: dict[int, dict] = defaultdict(lambda: {"rows": [], "errors": [], "runs": []})
    for group in floor_scores:
        can, kind, mode = group["can_id"], group["trajectory"], group["mode"]
        twin_group = twin_groups.get((can, kind, mode), {})
        twin_deg = (twin_group.get("summary") or {}).get("twin_vs_real_deg_median")
        entry = out[can]
        if mode == "driven":
            start = group.get("same_input_from_s", 0.0)
            runs, q_all, qd_all, qdd_all, dts = [], [], [], [], []
            for run in group["runs"]:
                data = np.load(Path(run["file"]).with_suffix(".npz"))
                t = data["t"] - data["t"][0]
                keep = t >= start
                runs.append((t[keep] - start, _wrist_target(t, data["q"], data["q_target"], data["qd_target"])[keep], data["q"][keep]))
                q_all.append(np.degrees(data["q"])); qd_all.append(np.degrees(data["qd"])); qdd_all.append(np.degrees(np.gradient(data["qd"], t)))
                entry.setdefault("samples", []).append((data["q"], data["qd"], np.gradient(data["qd"], t)))
                entry.setdefault("settled", []).append(("repeat campaign", settled_errors_deg(t, data["q"], data["q_target"])))
                dts.append(float(np.median(np.diff(t))))
            floor = repeat_floor(runs)
            floor_deg = math.degrees(floor.value) if floor.value is not None else None
            entry["driven"] = {"floor_deg": floor_deg, "pairs": floor.pairs, "runs": floor.runs, "known": floor.known, "kind": f"{kind} (driven)",
                               "twin_deg": twin_deg, "note": f"the lane's own: {group['floor_rms_deg_median']:.3f}°"}
            entry["coverage"] = joint_coverage(np.concatenate(q_all), np.concatenate(qd_all), np.concatenate(qdd_all), float(np.median(dts)))
            entry["target_deg"] = _median([r.get("target_vs_real_deg") for r in twin_group.get("runs", [])])
            entry["rows"].append({"kind": f"{kind} (repeat campaign)", "mode": "driven", "floor_deg": _r(floor_deg, 4), "pairs": floor.pairs,
                                  "runs": floor.runs, "known": floor.known, "twin_deg": _r(twin_deg),
                                  "twin_over_floor": _r(twin_deg / floor_deg, 2) if twin_deg and floor_deg else None,
                                  "verdict": verdict_of(twin_deg / floor_deg) if twin_deg and floor.known else "floor unknown",
                                  "source": "ur_wrist/repeat_floor (floor: repeat_floor; twin: twin_scores.json, it5)"})
        else:
            floor_deg = group["floor_rms_deg_median"]
            entry["passive"] = {"state": "known", "floor_deg": floor_deg, "twin_deg": twin_deg,
                                "note": f"{group['repeats']} releases of {kind}, the lane's floor; the twin's rest is "
                                        f"{(twin_group.get('summary') or {}).get('rest_deg', {}).get('twin_minus_real_median', float('nan')):.1f}° off"}
            entry["rows"].append({"kind": f"{kind} (repeat campaign)", "mode": "passive", "floor_deg": _r(floor_deg, 4), "pairs": len(group.get("pairs", [])),
                                  "runs": group["repeats"], "known": group["repeats"] >= 5, "twin_deg": _r(twin_deg),
                                  "twin_over_floor": _r(twin_deg / floor_deg, 2) if twin_deg else None,
                                  "verdict": verdict_of(twin_deg / floor_deg) if twin_deg else "no twin",
                                  "source": "ur_wrist/repeat_floor floor_scores.json / twin_scores.json (the lane's)"})
        for run in twin_group.get("runs", []):
            label = f"CAN {can} {kind} {mode} {run['run'].split('/')[-1]}"
            entry["errors"].append({"run": label, "stage": WRIST_TITLES["it5"], "held_out": True, "sim_real_deg": run.get("twin_vs_real_deg"),
                                    "target_real_deg": run.get("target_vs_real_deg"), "phase": "after", "kind": kind})
            entry["runs"].append({"run": slug(f"ur_wrist-{label}"), "label": label, "held_out": True, "gains": "repeat campaign", "tape": f"{kind} ({mode})",
                                  "target_real_deg": _r(run.get("target_vs_real_deg")), "sim_real_deg": _r(run.get("twin_vs_real_deg")),
                                  "sim_real_before_deg": None, "run_view": None})
    for can, reason in PASSIVE_NA.items():
        out[can].setdefault("passive", {"state": "na", "reason": reason})
    return dict(out)



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
    arm = Node("ur-wrist/wrist", "UR wrist (CAN 14 + 15 + 16)", "arm", "robot arm", "ur wrist", parent=root.id)
    tool = Node("ur-wrist/wrist/holder", "holder board #4-7 (tool)", "tool", "Tool (payload + TCP)", "tool", parent=arm.id,
                note="no tool gate yet: the wrist's runs log the joints; the holder's camera fit is not in these runs")
    joints = {can: Node(f"ur-wrist/wrist/can{can}", f"CAN {can} wrist joint (moteus servo)", "joint", "integrated_servo", "moteus servo",
                        parent=arm.id) for can in (14, 15, 16)}
    joints[14].label = "CAN 14 wrist joint (revolute 11, moteus servo)"
    joints[14].note = "held at ~87.45° in the coverage runs; driven and released only in the repeat-floor campaign"

    files: dict = {}
    groups: dict[int, dict] = {can: defaultdict(list) for can in (14, 15, 16)}
    per_run: dict[int, list] = {can: [] for can in (14, 15, 16)}
    cover: dict[int, list] = {can: [[], [], []] for can in (14, 15, 16)}
    samples: dict[int, list] = {can: [] for can in (14, 15, 16)}   # real (q rad board, qd, qdd) for the Data question
    settled: dict[int, list] = {can: [] for can in (14, 15, 16)}   # |q - target| (deg) where the target rests, for the Job question
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
        samples[can].append((q, qd, np.gradient(qd, t) if t.size > 2 else np.zeros_like(qd)))
        settled[can].append((gainset, settled_errors_deg(t, q, data["q_target"])))
        # WHY (gain set, tape): a repeat is the same tape on the same controller config, compared like for like (T1 "per run kind");
        # pooling every tape let low-motion tapes (parks, holds) set a floor 5-20x under the dedicated campaign's (2026-11-11 review)
        kind = tape
        groups[can][(gainset, kind)].append((t, _wrist_target(t, q, data["q_target"], data["qd_target"]), q))
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
        per_run[can].append(((gainset, kind), held_out, values.get(stages[-1], (None, None))[0], values.get(stages[0], (None, None))[0],
                             values.get(stages[-1], (None, None))[1]))
        joints[can].runs.append({"run": run_slug, "label": label, "held_out": held_out, "gains": gainset, "tape": tape.removesuffix("_heldout"),
                                 "target_real_deg": _r(values.get(stages[-1], (None, None))[1]), "sim_real_deg": _r(values.get(stages[-1], (None, None))[0]),
                                 "sim_real_before_deg": _r(values.get(stages[0], (None, None))[0]), "run_view": run_view(run_slug)})

    campaign = repeat_campaign()
    for can, node in joints.items():
        floors = {key: repeat_floor(runs) for key, runs in groups[can].items()}
        twins = {key: _median([r[2] for r in per_run[can] if r[0] == key]) for key in floors}
        node.floors = floors_rows(floors, twins, "driven", "coverage runs (summary_real it5 twin)")
        own = campaign.get(can, {})
        node.floors = own.get("rows", []) + node.floors
        driven = own.get("driven") or {"floor_deg": None, "known": False, "note": "no dedicated repeat campaign"}
        node.floor_deg = driven["floor_deg"] if driven.get("known") else None
        if cover[can][0]:
            rows, summary_rows = joint_coverage(*(np.concatenate(c) for c in cover[can]), dt_of[can])
        else:
            rows, summary_rows = own.get("coverage", ([], [{"value": "—"}] * 4))
        node.coverage, node.coverage_summary = rows, summary_rows
        held_out = [r for r in per_run[can] if r[1]]
        node.questions = joint_questions(
            driven=driven, passive=own.get("passive", {"state": "none"}),
            before_deg=_median([r[3] for r in held_out]), target_deg=own.get("target_deg") or _median([r[4] for r in held_out]),
            coverage_text=f"angle {summary_rows[0]['value']}°, speed p99 {summary_rows[1]['value']}°/s, {summary_rows[3]['value']} min logged",
            routines=("CAN 14's friction is not fitted (refit_rig moved CAN 15 and 16 only)" if can == 14 else
                      "the wrist refit's own test hides the truth on its search grid without noise (bam_ur_wrist_coverage tests/test_refit.py)"),
            routines_own="no" if can == 14 else "partial")
        node.twin_ratio = driven["twin_deg"] / driven["floor_deg"] if driven.get("known") and driven.get("twin_deg") else None
        node.errors += own.get("errors", [])
        node.runs += own.get("runs", [])
        if can not in WRIST_BOARD:
            continue
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
    if REACHABLE_EXPORT.exists():
        export = json.loads(REACHABLE_EXPORT.read_text())
        thresholds = export["good_data_thresholds"]
        status = thresholds["status"]
        # the multi-joint runs (multi3: CAN 14 free) log all three joints in CAD degrees; board = CAD - the export's offset
        for trace in sorted((MULTI3 / "twin_traces").glob("*/*.npz")):
            data = np.load(trace)
            t = data["t"] - data["t"][0]
            for can in (14, 15, 16):
                q = np.radians(data[f"q_real_can{can}"] - export["frames"]["cad_equals_board_plus_deg"][str(can)])
                qd = np.gradient(q, t)
                samples[can].append((q, qd, np.gradient(qd, t)))
        for can, node in joints.items():
            own = campaign.get(can, {})
            node.questions["Data"] = joint_data(export["joint_descriptions"][str(can)], samples[can] + own.get("samples", []),
                                                thresholds["per_joint_reachable_cells_pct"], status)
        real = json.loads((MULTI3 / "multi_scores.json").read_text())["coverage_real_rows"]["real_all"]["allowed"]
        gates = (("joint cube", real["joint_cube_pct"], thresholds["joint_cube_pct_of_allowed"]),
                 ("workspace", real["workspace_pct"], thresholds["workspace_pct_of_allowed"]),
                 ("facing", real["facing_pct"], thresholds["facing_pct_of_allowed"]))
        arm_data = {"own": "yes" if all(value >= limit for _name, value, limit in gates) else "no",
                    "numbers": "; ".join(f"{name} {value:.1f} % of allowed (≥ {limit:g} %)" for name, value, limit in gates)
                    + f" — every real run (multi3 real_all, {export['counts']['allowed']['joint_grid_poses']} allowed grid poses; "
                      f"mask from {REACHABLE_EXPORT.parent.parent.parent.parent.parent.parent})",
                    "gate": f"cube ≥ {thresholds['joint_cube_pct_of_allowed']:g} %, workspace ≥ {thresholds['workspace_pct_of_allowed']:g} %, "
                            f"facing ≥ {thresholds['facing_pct_of_allowed']:g} % of the allowed mask ({status})"}
    else:
        arm_data = None
    levers = json.loads(TOOL_LEVERS.read_text())["rigs"] if TOOL_LEVERS.exists() else {}
    if "ur_wrist" in levers:
        for can, node in joints.items():
            lever = levers["ur_wrist"]["lever_mm_per_rad"][f"can{can}"]
            # WHY per gain set, judged on the operating one (2026-11-11): a joint's Job is the controller in service; the stock kp 2 runs
            # cannot hold a target against stiction (settled p95 ~10 deg) and would grade a controller nobody runs. The operating gains are
            # the twin of record's (pick_sliding: kp 75 / kd 1 + the refit's sliding FF); CAN 14's driven data is its repeat campaign only
            by_gains: dict[str, list] = defaultdict(list)
            for gains, values in settled[can] + campaign.get(can, {}).get("settled", []):
                by_gains[gains].append(values)
            operating = "pick_sliding" if "pick_sliding" in by_gains else "repeat campaign"
            others = "; ".join(f"{g}: {float(np.median(np.concatenate(v))):.3f}° median" for g, v in sorted(by_gains.items())
                               if g != operating and np.concatenate(v).size)
            values = np.concatenate(by_gains.get(operating) or [np.zeros(0)])
            node.questions["Job"] = job_answer(joint_share_deg(lever, 3), lever, 3, values.tolist(),
                                               f"settled rows (the target at rest ≥ 0.3 s) on the operating gains ({operating})",
                                               (f"other gains: {others}; " if others else "") + node.questions["Job"]["numbers"])
    one_click = json.loads(ONE_CLICK.read_text()) if ONE_CLICK.exists() else None
    if one_click:
        rows = one_click["calibration"]["rows"]
        for can, node in joints.items():
            node.questions["Routines"] = routines_from_rows(rows, f"can{can}.")
    tapes = json.loads((WRIST / "multi" / "multi_scores.json").read_text())["tapes"]
    twin_multi = [j["twin_vs_real_deg"] for tape in tapes for j in tape["joints"].values() if j.get("twin_vs_real_deg") is not None]
    target_multi = [j["target_vs_real_deg"] for tape in tapes for j in tape["joints"].values() if j.get("target_vs_real_deg") is not None]
    arm.questions = {
        "Floor": {"own": "no", "numbers": "no tool-pose repeats (ISO 9283 RP) on the arm", "gate": "repeatability at the tool: 5 poses × 30 cycles"},
        "Data": arm_data or {"own": "partial", "numbers": f"joint cube {both['joint_cube_pct_of_r11_held']:.0f} % of reachable with CAN 14 held, "
                 f"{both['joint_cube_pct']:.0f} % of the full cube; workspace {both['workspace_pct_of_r11_held']:.0f} % (CAN 14 held)",
                 "gate": "≥ 40 % of the reachable joint cube"},
        "Routines": (routines_from_rows(one_click["calibration"]["rows"], "wrist.") if one_click else
                     {"own": "unknown", "numbers": "no arm-level routine (kinematics, mounts) graded on a hidden truth", "gate": "per routine"}),
        "Twin": {"own": "unknown", "numbers": f"coupled multi-joint runs: twin vs real {min(twin_multi):.2f}–{max(twin_multi):.2f}°, "
                 f"real vs target {min(target_multi):.2f}–{max(target_multi):.2f}° (no skill over the target yet); no tool floor to divide by",
                 "gate": "twin vs real tool pose ≤ 1.5× the tool floor"},
        "Job": {"own": "unknown", "numbers": "the holder's pose is not measured at stops", "gate": f"tool ≤ {TOOL_GATE_MM:g} mm at a stop, by camera"},
    }
    tool.questions = {q: {"own": "no" if q == "Floor" else "unknown", "numbers": "no tool runs: the holder board is not tracked in these runs",
                          "gate": ""} for q in ("Floor", "Data", "Routines", "Twin", "Job")}
    root.questions = {
        "Floor": {"own": "no", "numbers": "no repeat of the deployment's own output", "gate": "children's floors exist; its output repeated"},
        "Data": {"own": "yes", "numbers": f"physical runs: {sum(len(n.runs) for n in joints.values())}, held-out tapes fixed before the refit",
                 "gate": "physical runs, split sealed"},
        "Routines": {"own": "yes", "numbers": "rolls up its children", "gate": "every child's routines pass"},
        "Twin": {"own": "yes", "numbers": "rolls up its children", "gate": "every child twinned"},
        "Job": {"own": "unknown", "numbers": "no picks on this rig", "gate": f"picks; tool ≤ {TOOL_GATE_MM:g} mm at a stop"},
    }
    notes = ["Errors: summary_real.json, every run scored on each twin on one player (bam_ur_wrist_coverage.campaign.real_summary); "
             "held out = the *_heldout tapes. Arm coverage: single-joint runs → + the multi-joint runs (multi/multi_scores.json).",
             "Floors: same-input repeats only (sim2real.metrics.series.repeat_floor: commands within 0.01° RMS), per run kind and gain set; "
             "the joint's floor is the group with the most repeats, and its twin is judged on held-out runs of that group.",
             "Models: refit_rig/it5/refit.json's ladder, held-out RMS per joint; the delay row is the it5 delay scan's pick."]
    return CalibrationResult("ur-wrist-2026-11-10", "UR wrist calibration · One Dof Test Rack · 2026-11-10/11", stages,
                             [root, arm, joints[14], joints[15], joints[16], tool], source=str(WRIST), notes=notes, messages=_messages(files))


# ------------------------------------------------------------------------------------------------------------------- five-bar


FIVEBAR_LADDERS = {"ladder_real_101015": "stock", "ladder_real_104843": "winners", "ladder_real_113617": "winners",
                   "ladder_real_122045": "winners", "ladder_real_124755": "winners + lumped comp",
                   # five identical repeats of the 0.05 m/s rungs (2026-11-11 night): the floor's repeats
                   **{name: "winners" for name in ("ladder_real_repeat1_012235", "ladder_real_repeat2_013240", "ladder_real_repeat3_014218",
                                                   "ladder_real_repeat4_015157", "ladder_real_repeat5_020134")},
                   # seven C1 swings across C1's range (the lane's coverage tape set, claude/fivebar-guard @ d5213c2a3): C1's Data
                   "coverage_real_031652": "winners"}
FIVEBAR_STAGES = (("study", "study twin (nominal)", None), ("massid", "+ mass-ID gravity", ("refit_both_111322", "held_out_before")),
                  ("dynamics", "+ dynamics refit", ("refit_both_111322", "held_out_after")),
                  ("tick", "refit on the tick clock", ("refit_breakdown_123729", "held_out_before")))
FIVEBAR_MODELS = (("refit_baseline_104512", "held_out_after", "baseline: armature x4.1, viscous 0.2, no delay"),
                  ("refit_both_111322", "held_out_before", "nominal dynamics + mass-ID gravity"),
                  ("refit_both_111322", "held_out_after", "+ dynamics refit (viscous 0.1, delay 2.5 ms)"),
                  ("refit_asym_113041", "held_out_after", "+ direction-asymmetric Coulomb + backlash (rejected)"),
                  ("refit_breakdown_123729", "held_out_before", "the dynamics refit compared on the tick clock"))


# WHY N/A (bam_ws claude/fivebar-guard @ 3d820b08f, docs/fivebar_passive_twin.py; proposed, Zach to confirm): the hanging rest sits at
# the closure fold (margin 0.041); gravity's stiffness there (~9 N.m/rad J2, ~3.5 N.m/rad C1) against 0.74 N.m of friction per drive is a
# +-4.5 deg / +-12 deg band where gravity cannot move the arm; on the CAD twin the safe limp releases move 0.03-0.5 deg, the larger ones
# start at the fold or fall 40-80 deg at up to 1,300 deg/s. No passive response is both safe and alive.
FIVEBAR_PASSIVE_NA = {
    "j2": "no safe passive release moves it: its rest is at the closure fold (margin 0.041); gravity ~9 N·m/rad against 0.74 N·m friction "
          "holds a ±4.5° band, and larger releases fall 40-80° at up to 1,300°/s (CAD twin, fivebar_passive_twin.py)",
    "c1": "no safe passive release moves it: its rest is at the closure fold (margin 0.041); gravity ~3.5 N·m/rad against 0.74 N·m friction "
          "holds a ±12° band, and larger releases fall 40-80° at up to 1,300°/s (CAD twin, fivebar_passive_twin.py)",
}
DWELL = Path(__file__).resolve().parent / "data" / "fivebar_dwell_2026-11-11.json"
# the five-bar lane's reachable mask (bam_ws claude/fivebar-guard @ 6a8818843, schema bam_fivebar.reachable/1): main first, the lane's
# worktree until it lands (as the wrist's)
_FIVEBAR_REACHABLE = "src/dev/bam_fivebar/bam_fivebar/data/reachable_2026-11-11.json"
FIVEBAR_REACHABLE_CANDIDATES = (Path("/home/bam/bam_ws") / _FIVEBAR_REACHABLE, Path("/home/bam/bam_ws-worktrees/fivebar-guard") / _FIVEBAR_REACHABLE)
# the tick-clock refit's twin replayed on the five repeats (bam_fivebar.refit --evaluate --start refit_breakdown_123729)
AFTER_TWIN = FIVEBAR / "refit_repeats_025953" / "after_twin.json"


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
    per_run: dict[str, list] = {"j2": [], "c1": []}
    samples: dict[str, list] = {"j2": [], "c1": []}   # real (q, qd, qdd), every 10th tick, for the Data question
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
            # WHY the tick: the ladder logs one row per plan tick, so the row index is the tape's own clock; its t is host time, whose
            # ~1 ms jitter put identical tapes 1.6-3.1 deg apart on a wall clock (metrics.series.repeat_floor compares per tick)
            # WHY the tape length in the key: like for like (T1) - the three earlier ladders ran this rung on a 19,791-tick tape, the five
            # repeats on a 19,951-tick one; two tapes are two run kinds
            repeats[(gainset, step["name"], t.size)].append((t, real["target_motors"], q, np.arange(t.size)))
            for k, joint in enumerate(("j2", "c1")):
                samples[joint].append((q[::10, k], qd[::10, k], np.gradient(qd[:, k], t)[::10]))
            rung_key = f"{ladder}:{step['name']}"
            held_out = rung_key not in train
            raster = step["name"].startswith("vertical.")
            label = f"{ladder[-6:]} {step['speed_m_s']:.2f} m/s {step['ff_mode']}" if raster else f"{ladder[-6:]} {step['name']}"
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
                per_run[joint].append(((gainset, step["name"], t.size), held_out, values.get(stages[-1]), values.get(stages[0]), target_real))
                joints[joint].runs.append({"run": run_slug, "label": label, "held_out": held_out, "gains": gainset,
                                           "tape": (f"coverage raster {step['ff_mode']} {step['speed_m_s']:.2f} m/s" if raster
                                                    else f"C1 swing {step['name']}"),
                                           "target_real_deg": _r(target_real), "sim_real_deg": _r(values.get(stages[-1])),
                                           "sim_real_before_deg": _r(values.get(stages[0])), "run_view": run_view(run_slug)})
    dt = float(np.median(dt_all))
    after_twin = json.loads(AFTER_TWIN.read_text()) if AFTER_TWIN.exists() else None
    reachable_path = next((path for path in FIVEBAR_REACHABLE_CANDIDATES if path.exists()), None)
    export = json.loads(reachable_path.read_text()) if reachable_path else None
    for k, (joint, node) in enumerate(joints.items()):
        floors = {key: repeat_floor([(t, c[:, k], q[:, k], tick) for t, c, q, tick in runs]) for key, runs in repeats.items() if len(runs) > 1}
        key, floor = best_floor(floors)
        node.floor_deg = math.degrees(floor.value) if floor is not None and floor.known else None
        node.coverage, node.coverage_summary = joint_coverage(*(np.concatenate(c) for c in cover[joint]), dt)
        # WHY the same kind (T1, 2026-11-11 review): the twin is judged on the floor's own tape; only the study (before) twin replayed the
        # repeat rungs, so the driven ratio uses it there and says so; the after twin's held-out rungs stay beside it as soft numbers
        def one_twin(rows):
            """One twin over a whole group, never a blend: the after twin when it replayed every run, else the study twin for all."""
            if rows and all(r[2] is not None for r in rows):
                return _median([r[2] for r in rows]), "after twin"
            return _median([r[3] for r in rows]), "study (before) twin: the after twin did not replay every run of this kind"

        same = [r for r in per_run[joint] if r[0] == key]
        twin_same, which = one_twin(same)
        twins = {k: one_twin([r for r in per_run[joint] if r[0] == k])[0] for k in floors}
        # the after twin replayed on the repeats (coordinator, 2026-11-11): the floor's own tape, judged on the calibrated twin
        if after_twin and key is not None and key[1] in after_twin["rungs"]:
            twin_same = after_twin["rungs"][key[1]][joint]["after_twin_median_deg"]
            which = "after twin (the tick-clock refit) replayed on the five repeats, refit_repeats_025953"
        for k in floors:
            if after_twin and k[1] in after_twin["rungs"] and floors[k].known:
                twins[k] = after_twin["rungs"][k[1]][joint]["after_twin_median_deg"]
        node.floors = floors_rows(floors, twins, "driven", "ladder rungs per plan tick (twin: the after twin on the repeats, after_twin.json; "
                                                             "else the after twin where it scored, else the study twin)")
        held_after = [r for r in per_run[joint] if r[1] and r[2] is not None]
        summary_rows = node.coverage_summary
        driven = {"floor_deg": math.degrees(floor.value) if floor is not None else None, "pairs": floor.pairs if floor else 0,
                  "runs": floor.runs if floor else 0, "known": bool(floor and floor.known), "kind": " / ".join(map(str, key)) if key else "—",
                  "twin_deg": twin_same, "note": f"twin = the {which}; after twin on held-out rungs {_median([r[2] for r in held_after]):.3f}°"}
        node.questions = joint_questions(
            driven=driven, passive={"state": "na", "reason": FIVEBAR_PASSIVE_NA[joint]}, before_deg=_median([r[3] for r in held_after]),
            target_deg=_median([r[4] for r in held_after]),
            coverage_text=f"angle {summary_rows[0]['value']}°, speed p99 {summary_rows[1]['value']}°/s, {summary_rows[3]['value']} min logged",
            routines="the five-bar mass ID's hidden-gravity test (bam_fivebar tests/test_massid.py) grades the gravity only")
        node.twin_ratio = twin_same / driven["floor_deg"] if driven["known"] and twin_same else None
        fb_levers = json.loads(TOOL_LEVERS.read_text())["rigs"].get("fivebar") if TOOL_LEVERS.exists() else None
        if fb_levers and DWELL.exists():
            lever = fb_levers["lever_mm_per_rad"][joint]
            dwell_rows = json.loads(DWELL.read_text())["rows"]
            index = ("j2", "c1").index(joint)   # WHY by name: `k` is reused by the floors loop above
            settled_deg = [abs(r["motor_error_deg"][index]) for r in dwell_rows if r.get("motor_error_deg")]
            node.questions["Job"] = job_answer(joint_share_deg(lever, 2), lever, 2, settled_deg, "dwell holds (3 s, the last second)",
                                               node.questions["Job"]["numbers"])
        if export:
            thresholds = export["good_data_thresholds"]
            can = {"j2": "12", "c1": "13"}[joint]
            node.questions["Data"] = joint_data(export["joint_descriptions"][can], samples[joint], thresholds["per_joint_reachable_cells_pct"],
                                                thresholds["status"])
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
    # WHY split (2026-11-11 review): the old "tool gate" took a MODELLING number (twin vs real, on the before twin) for a PERFORMANCE gate.
    # Twin = the twin's tool vs the real tool at stops; Job = the real tool vs the commanded one at stops, against the tool gate.
    sim_p95, job_p95 = _pct(stop_sim, 95), _pct(stop_target, 95)
    # WHY the dwell holds (coordinator, 2026-11-11): the raster's "stops" are turnarounds (median 0.06 s), tracking at the turn; the
    # mass-ID's 16 three-second holds are the settled accuracy the 1 mm gate asks about
    dwell = json.loads(DWELL.read_text()) if DWELL.exists() else None
    if dwell:
        enc, cam = dwell["summary"]["encoders_fk_mm"], dwell["summary"]["camera_vs_commanded_mm"]
        job = "no" if enc["median"] > TOOL_GATE_MM else "yes"
        job_text = (f"settled at {enc['n']} three-second holds: {enc['median']:.1f} mm median, {enc['p95']:.1f} mm p95 by encoders + FK; "
                    f"{cam['median']:.1f} mm median by the D435 ({cam['n']} holds); raster turnarounds (tracking, not settled) "
                    f"{job_p95:.1f} mm p95 by encoders")
    else:
        job = "no" if job_p95 is not None and job_p95 > TOOL_GATE_MM else ("yes" if job_p95 is not None else "unknown")
        job_text = f"real vs commanded {job_p95:.1f} mm p95 at raster stops, by encoder kinematics"
    tool.gate = {"gate_mm": TOOL_GATE_MM, "sim_real_mm": sim_p95,
                 "target_real_mm": dwell["summary"]["encoders_fk_mm"]["median"] if dwell else job_p95,
                 "verdict": f"Job {job}: " + job_text.split(';')[0] + f" (gate {TOOL_GATE_MM:g} mm)"}
    tool.note = "stops = where the commanded tool point rests (< 2 mm/s); the tool by encoder kinematics (bam_fivebar FK, as logged), not by camera"
    tool.questions = {
        "Floor": {"own": "no", "numbers": "no tool revisits of one commanded stop", "gate": "the tool at the same stop, revisited, by camera"},
        "Data": {"own": "unknown", "numbers": f"{len(stop_target)} stop samples over every rung", "gate": "the TCP seen from spread poses"},
        "Routines": {"own": "unknown", "numbers": "no TCP / payload routine graded", "gate": "mass 5 %, CoM 3 mm, TCP 0.5 / 1 mm"},
        "Twin": {"own": "unknown", "numbers": f"study (before) twin vs real {sim_p95:.1f} mm p95 at stops; the after twin's tool is not computed "
                 "(the refits kept joint scores only); no tool floor to divide by", "gate": "tool twin vs real at stops ÷ the tool floor, on the after twin"},
        "Job": {"own": job, "numbers": job_text + (f" (source: {dwell['source'].split(',')[0]})" if dwell else ""),
                "gate": f"≤ {TOOL_GATE_MM:g} mm at a stop, measured at the tool"},
    }
    if export:
        thresholds, today = export["good_data_thresholds"], export["good_data_thresholds"]["pass_today"]
        gates = (("joint cube", today["joint_cube_pct_of_allowed"], thresholds["joint_cube_pct_of_allowed"]),
                 ("workspace (2 cm tool pixels)", today["workspace_pct_of_allowed"], thresholds["workspace_pct_of_allowed"]),
                 ("heading (15°, for facing)", today["heading_pct_of_allowed"], thresholds["heading_pct_of_allowed"]))
        arm_data = {"own": "yes" if all(v >= limit for _n, v, limit in gates) else "no",
                    "numbers": "; ".join(f"{name} {v:.1f} % of allowed (≥ {limit:g} %)" for name, v, limit in gates)
                    + f" — {today['samples']} samples, {today['runs']}; mask from {reachable_path.parents[5]}",
                    "gate": f"cube ≥ {thresholds['joint_cube_pct_of_allowed']:g} %, workspace ≥ {thresholds['workspace_pct_of_allowed']:g} %, "
                            f"heading ≥ {thresholds['heading_pct_of_allowed']:g} % of the allowed mask ({thresholds['status']})"}
    else:
        arm_data = {"own": "unknown", "numbers": f"{sum(1 for v in workspace.values() if v >= 0.5)} tool cells (20 mm) visited; reachable set not committed",
                    "gate": "≥ 40 % of the reachable joint cube"}
    if after_twin:
        tool_rows = [(rung, statistics.median(r["tool_mm"]["after_twin"]), r["tool_mm"]["floor"]) for rung, r in after_twin["rungs"].items()]
        tool.questions["Twin"] = {"own": "yes" if all(FLOOR_CHECK <= m / f <= RULER_TWINNED for _r, m, f in tool_rows) else "no",
                                  "numbers": "; ".join(f"{rung.split('.')[-1]}: after twin {m:.1f} mm vs tool floor {f:.1f} mm = {m / f:.1f}×"
                                                       for rung, m, f in tool_rows) + " (the five repeats, tick clock)",
                                  "gate": "tool twin vs real ≤ 1.5× the tool floor, on the after twin"}
        tool.questions["Floor"] = {"own": "no", "numbers": "the tool's driven floor is known on the repeats ("
                                   + ", ".join(f"{f:.1f} mm" for _r, _m, f in tool_rows) + "); no settled revisit of one stop by camera",
                                   "gate": "the tool at the same stop, revisited, by camera"}
    arm.questions = {
        "Floor": {"own": "no", "numbers": "no tool-pose repeats (ISO 9283 RP)", "gate": "repeatability at the tool"},
        "Data": arm_data,
        "Routines": {"own": "unknown", "numbers": "no arm-level routine graded on a hidden truth", "gate": "per routine"},
        "Twin": {"own": "unknown", "numbers": "the coupled arm's twin is scored per joint only", "gate": "twin vs real tool pose ≤ 1.5× the tool floor"},
        "Job": {"own": job, "numbers": tool.questions["Job"]["numbers"], "gate": tool.questions["Job"]["gate"]},
    }
    root.questions = {
        "Floor": {"own": "no", "numbers": "no repeat of the deployment's own output", "gate": "children's floors exist; its output repeated"},
        "Data": {"own": "yes", "numbers": "physical ladder runs; held-out rungs fixed by refit_both's split", "gate": "physical runs, split sealed"},
        "Routines": {"own": "yes", "numbers": "rolls up its children", "gate": "every child's routines pass"},
        "Twin": {"own": "yes", "numbers": "rolls up its children", "gate": "every child twinned"},
        "Job": {"own": "unknown", "numbers": "no picks on this rig", "gate": f"picks; tool ≤ {TOOL_GATE_MM:g} mm at a stop"},
    }
    root.gate = tool.gate
    notes = ["Errors: the study twin from each rung's own sim (pair_rms on the tick clock); the refits from their per-rung held-out scores "
             "(refit_both / refit_breakdown). Held out = not in refit_both's train set.",
             "Floors: same-input repeats only (sim2real.metrics.series.repeat_floor), compared per plan tick: the five repeat ladders of the "
             "0.05 m/s rungs (identical tapes); the earlier ladders' runs of those rungs start from other homings and are rejected. The twin "
             "ratio divides the after twin's held-out rungs by that floor (the repeats were scored on the study twin only).",
             "Tool: Twin = the study twin's tool vs the real tool at raster stops; Job = the settled tool at the mass-ID's 16 dwell holds "
             "(data/fivebar_dwell_2026-11-11.json, from the five-bar lane's repeat-floor report), by encoders + FK and by the D435.",
             "Passive: N/A for J2 and C1 (proposed, Zach to confirm): the rest sits at the closure fold, and no limp release is both safe and alive."]
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
