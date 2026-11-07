"""The noise ladder: every calibration procedure the sysid oracle can run, on the same hidden truth at 0, 1x, 3x and 10x its world's sensor
noise and at 1x plus a delay or a quantisation where one matters, graded by sysid/noise_ladder.json (the ruler, committed before any run).

Zach, 2026-11-07 (via the coordinator): procedures compared "on the same amount of noise"; and his Nov 6 note on kinematic calibration:
"test this in simluation where you have access to the ground truth to see what like perfect would be ... see if you can recover the
perfect values... (you can change the amount of noise you add to the sensor measurements...)".

A level runs an example's own pipeline unchanged (plan, RealWorld.measure, identify sealed, score) inside world.noise_scale(k), so every
noise channel is k times its committed value and draws the same normals; a variant runs at 1x inside world.perturbed(name, value), which
the example's RealWorld applies where its measurement would carry it. Each check reads the values its procedure produced (the example's
fit, the stock fit beside it, T10's routine on the deployed check's runs, the drift demos) and grades them against the world's truth.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid ladder conveyor dual_arm_cell --write
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid ladder pendulum_can11 --levels 3x --write

Results: sysid/results/noise_ladder.json (rows merged by check, level and variant, so levels may run in separate processes), held to the
code by sysid/tests/test_noise_ladder.py.
"""

from __future__ import annotations

import contextlib
import fcntl
import fnmatch
import hashlib
import json
import math
import sys
import time
from pathlib import Path

from . import PACKAGE, RESULTS_DIR, describe, oracle, result
from . import world as hidden

RULER_PATH = PACKAGE / "noise_ladder.json"
RULER = json.loads(RULER_PATH.read_text(encoding="utf-8"))
SCHEMA = "sysid.noise_ladder_result/1"
RESULT_PATH = RESULTS_DIR / "noise_ladder.json"
LEVELS = {level["id"]: float(level["scale"]) for level in RULER["levels"]}
EXACT_FRACTION = float(RULER["exact_fraction"])
ROUND4_DOCS = Path("/home/bam/bam_ws/src/dev/bam_rack_twin/docs")


def ruler_sha256() -> str:
    return hashlib.sha256(RULER_PATH.read_bytes()).hexdigest()


def example_of(check_id: str) -> str:
    return check_id.split(":", 1)[0]


def checks_of(example: str) -> list[str]:
    return [cid for cid in RULER["checks"] if example_of(cid) == example]


def examples() -> list[str]:
    return list(dict.fromkeys(example_of(cid) for cid in RULER["checks"]))


def world_doc(example: str) -> dict:
    """The truth as committed (the grader's own read, outside any noise scale; never handed to a fit)."""
    return json.loads(hidden.path(example).read_text(encoding="utf-8"))


# --- truth, tolerance, nominal ---------------------------------------------------------------------------------------------------

def _drift_entries(doc: dict) -> dict[str, float]:
    """The drift demos' hidden values this world holds, by the ladder's keys (RULER["drift_truth"])."""
    out = {}
    for pattern, entry in RULER.get("drift_truth", {}).items():
        node = doc
        path = entry["world"]
        for part in path[:-1] if path[-1] == "*" else path:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if node is None:
            continue
        if path[-1] == "*":
            prefix = pattern.removesuffix("*")
            out.update({f"{prefix}{name}": float(value) for name, value in node.items()})
        else:
            out[pattern] = float(node)
    return out


def truth_keys(example: str, doc: dict) -> list[str]:
    keys = list(doc.get("truth", {}))
    for key, entry in RULER.get("derived_truth", {}).items():
        if all(op in doc.get("truth", {}) for op in entry["of"][::2]):
            keys.append(key)
    return keys + list(_drift_entries(doc))


def truth_of(example: str, key: str, doc: dict) -> float | None:
    truth = doc.get("truth", {})
    if key in truth:
        return float(truth[key])
    derived = RULER.get("derived_truth", {}).get(key)
    if derived:
        a, op, b = derived["of"]
        if a in truth and b in truth:
            return float(truth[a]) - float(truth[b]) if op == "-" else float(truth[a]) + float(truth[b])
        return None
    return _drift_entries(doc).get(key)


def claimed(check_id: str) -> list[str]:
    """The truth keys a check claims, in the world's order: each of its patterns must match at least one."""
    check = RULER["checks"][check_id]
    keys = truth_keys(example_of(check_id), world_doc(example_of(check_id)))
    out = []
    for pattern in check["parameters"]:
        hits = [k for k in keys if fnmatch.fnmatchcase(k, pattern)]
        if not hits:
            raise KeyError(f"{check_id}: the pattern {pattern!r} matches no hidden value")
        out += [k for k in hits if k not in out]
    return [k for k in keys if k in out]


def tolerance(example: str, key: str) -> tuple[str, float] | None:
    for block in (RULER.get("tolerances", {}).get(example, {}), RULER.get("tolerances", {}).get("drift", {})):
        for pattern, rule in block.items():
            if pattern != "why" and fnmatch.fnmatchcase(key, pattern):
                return rule[0], float(rule[1])
    derived = RULER.get("derived_truth", {}).get(key)
    if derived:
        return derived["tolerance"][0], float(derived["tolerance"][1])
    return result.tolerance(example, key)


def nominal_of(example: str, key: str, description) -> float | None:
    nominal = description.nominal
    if key in nominal:
        return None if nominal[key].value is None else float(nominal[key].value)
    derived = RULER.get("derived_truth", {}).get(key)
    if derived:
        entry = nominal.get(derived["nominal_of"])
        return None if entry is None or entry.value is None else float(entry.value)
    for pattern, entry in RULER.get("drift_truth", {}).items():
        if fnmatch.fnmatchcase(key, pattern):
            return float(entry["nominal"])
    return None


def bound(tol: tuple[str, float], *, truth: float, nominal: float | None, scale: float, exact_fraction: float = EXACT_FRACTION) -> float:
    """The ruler's bound on |recovered - true| at a level: a tenth of the tolerance without noise; k x the tolerance at k x, never wider
    than not calibrating (|nominal - true|) where that is wider than the tolerance itself."""
    limit = tol[1] if tol[0] == "abs" else tol[1] * abs(truth)
    if scale == 0.0:
        return exact_fraction * limit
    cap = math.inf if nominal is None else max(limit, abs(nominal - truth))
    return min(scale * limit, cap)


def grade(example: str, key: str, truth: float, nominal: float | None, recovered, scale: float) -> dict:
    tol = tolerance(example, key)
    limit = tol[1] if tol[0] == "abs" else tol[1] * abs(truth)
    b = bound(tol, truth=truth, nominal=nominal, scale=scale)
    row = {"key": key, "true": truth, "nominal": nominal, "tolerance": {"kind": tol[0], "value": tol[1]}, "bound": b}
    value = None if recovered is None else float(recovered)
    if value is None or not math.isfinite(value):
        return {**row, "recovered": None, "error": None, "error_over_tolerance": None, "pass": False, "within_tolerance": False}
    error = abs(value - truth)
    return {**row, "recovered": value, "error": error, "error_over_tolerance": error / limit if limit else None,
            "pass": error <= b, "within_tolerance": error <= limit}


# --- what each example's procedures produce at one level ---------------------------------------------------------------------------

def _rms(values) -> float:
    import numpy as np  # noqa: PLC0415

    x = np.asarray(values, float)
    return float(np.sqrt(np.mean(x ** 2)))


def _t10(plan, measured) -> dict:
    """The rack's T10 routine on the deployed check's runs (H2 operate, plan order): bam_rack_twin docs/round4_study.live_reid_estimates,
    live_reid.Rls over the first 60 s at forgetting 0.999, on the motor encoder's angle and the board's torque."""
    if str(ROUND4_DOCS) not in sys.path:
        sys.path.append(str(ROUND4_DOCS))
    import round4_study  # noqa: PLC0415

    runs = [measured.held_out[row["run"]].output for row in plan.check]
    estimate = round4_study.live_reid_estimates([{"t": r.t, "q": r.q, "tau": r.tau, "controlled": r.controlled} for r in runs])
    return {"can11.gravity_nm": estimate["gravity_nm"], "can11.gravity_bottom_rad": estimate["gravity_bottom_rad"],
            "can11.armature_kg_m2": estimate["inertia"], "can11.damping_nm_s_rad": estimate["viscous"], "can11.coulomb_sliding_nm": estimate["coulomb"],
            "_notes": [f"{estimate['rows_fed']} rows fed over {estimate['seconds_used']:.1f} s ({estimate['derivatives']}), forgetting {estimate['forgetting']}"]}


STOCK_KEYS = {"gravity_nm": "can11.gravity_nm", "gravity_bottom_rad": "can11.gravity_bottom_rad", "armature_kg_m2": "can11.armature_kg_m2",
              "damping_nm_s_rad": "can11.damping_nm_s_rad", "frictionloss_nm": "can11.coulomb_sliding_nm"}


def _stock(fit) -> dict:
    out, notes = {}, []
    stock = fit.stock or {}
    if "error" in stock:
        notes.append(f"the stock fit raised: {stock['error']}")
    for name, key in STOCK_KEYS.items():
        est = stock.get("estimates", {}).get(name)
        out[key] = None if est is None else est.get("value")
        if est and est.get("refused"):
            notes.append(f"{name}: {est['refused']}")
    out["_notes"] = notes
    return out


def _pendulum(level: str, plan, description, workers: int, wear: bool) -> dict:
    from . import drift  # noqa: PLC0415
    from .examples.pendulum_can11 import pipeline as P  # noqa: PLC0415

    real = P.RealWorld(description, workers=workers)
    measured = real.measure(plan)
    with hidden.sealed():
        fit = P.identify(description, measured.train)
        t10 = _t10(plan, measured)
    scores = P.score(description, plan, fit, measured, workers=workers)
    m4 = {f"can11.{k}": v for k, v in fit.values["M4"].items()}
    held = {"link_mrad": scores["models"]["M4"]["link_mrad"], "link_x_floor": scores["models"]["M4"]["ratio"]}
    out = {"pendulum_can11:servo.dynamics_regression": {"recovered": m4, "held_out": held},
           "pendulum_can11:servo.backlash_reversals_camera": {"recovered": m4, "held_out": {"link_mrad": held["link_mrad"]}},
           "pendulum_can11:servo.stock_quasistatic": {"recovered": _stock(fit), "held_out": {}},
           "pendulum_can11:servo.live_reid_t10": {"recovered": t10, "held_out": {}}}
    if wear:
        doc = drift.run_backlash(workers=workers, commissioned_values=fit.values["M4"])
        actual, predicted = doc["actual_crossing_h"], doc["predicted_crossing_h"]
        gaps = [c["b_hat_rad"] - c["b_true_rad"] for c in doc["checks"]]
        out["pendulum_can11:servo.gap_check_forecast"] = {
            "recovered": {"can11.backlash_wear_rad_per_h": doc["rate_recovered"]},
            "held_out": {"forecast_error_pct": None if not (actual and predicted) else 100.0 * (predicted - actual) / actual,
                         "lead_h": None if actual is None else actual - doc["predicted_at_h"], "gap_rms_mrad": 1e3 * _rms(gaps),
                         "recalibrated_ratio": (doc.get("recalibrated") or {}).get("ratio"), "predicted_crossing_h": predicted, "actual_crossing_h": actual,
                         "detector_alarm_h": doc["detector_alarm_h"]}}
    return out


def _arm(example: str, plan, description, workers: int) -> dict:
    module = oracle.example_module(example)
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    m = module.score(description, plan, fit, measured, workers=workers)["models"]
    out = {f"{example}:kinematics.zero_offsets_tracker": {"recovered": fit.values, "held_out": {"tool_mm": m["kinematics"]["tool_mm"]}},
           f"{example}:arm.dynamics_excitation": {"recovered": fit.values, "held_out": {"torque_nm": m["fitted"]["torque_nm"]}}}
    if example == "ur5e_2f85":
        out[f"{example}:gripper.drive_traces"] = {"recovered": fit.values, "held_out": {"finger_mrad": m["fitted"]["finger_mrad"]}}
    return out


def _conveyor(plan, description, workers: int) -> dict:
    module = oracle.example_module("conveyor")
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    m = module.score(description, plan, fit, measured, workers=workers)["models"]
    return {"conveyor:conveyor.radius_tracker": {"recovered": fit.values, "held_out": {"belt_mm_radius": m["radius"]["belt_mm"]}},
            "conveyor:conveyor.dynamics_profiles": {"recovered": fit.values, "held_out": {"belt_mm": m["fitted"]["belt_mm"]}}}


def _cell(plan, description, workers: int, knock: bool) -> dict:
    from . import drift  # noqa: PLC0415

    module = oracle.example_module("dual_arm_cell")
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    m = module.score(description, plan, fit, measured, workers=workers)["models"]["fitted"]
    out = {"dual_arm_cell:cell.tags_bundle_adjustment": {"recovered": fit.values,
                                                         "held_out": {"reprojection_px": m["reprojection_px"], "pick_mm": m["pick_mm"]}}}
    if knock:
        doc = drift.run_camera(workers=workers)
        out["dual_arm_cell:camera.pose_recal_belt_tags"] = {
            "recovered": {f"camera_knock.{name}": value for name, value in doc["shift_recovered"].items()},
            "held_out": {"alarm_h": doc["alarm_h"], "recalibrated_ratio": (doc.get("recalibrated") or {}).get("ratio")}}
    return out


def _linescan(plan, description, workers: int) -> dict:
    module = oracle.example_module("linescan_cell")
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    m = module.score(description, plan, fit, measured, workers=workers)["models"]["fitted"]
    return {"linescan_cell:linescan.geometry_dot_card": {"recovered": fit.values, "held_out": {"scan_position_mm": m["scan_position_mm"]}},
            "linescan_cell:linescan.radiometry_refs": {"recovered": fit.values, "held_out": {"spectral_angle_mrad": m["spectral_angle_mrad"]}},
            "linescan_cell:rgbd.dot_card": {"recovered": fit.values, "held_out": {"cloud_mm": m["cloud_mm"]}}}


def _ur_backlash(plan, description, workers: int) -> dict:
    module = oracle.example_module("ur5e_backlash")
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    notes = [f"{name}: flanks {1e3 * f['low_rad']:+.4f} / {1e3 * f['high_rad']:+.4f} mrad, friction {f['friction_nm']:.3f} N.m" for name, f in fit.flanks.items()]
    notes += [f"not swept: {line}" for line in plan.coverage["train"]["unplanned"]]
    return {"ur5e_backlash:arm.backlash_gravity_sweep": {"recovered": {**fit.values, "_notes": notes}, "held_out": {}}}


def _plan(example: str, description):
    return oracle.example_module(example).plan(description)


def run_level(example: str, level: str, variant: str | None, *, plan, description, workers: int = 6) -> dict:
    """Every check of `example` at one level (or one variant at 1x): {check id: {recovered, held_out}}, the example's pipeline unchanged."""
    scale = LEVELS[level]
    value = None if variant is None else float(RULER["variants"][variant]["value"])
    wanted = {cid for cid in checks_of(example) if wants(cid, level, variant)}
    with hidden.noise_scale(scale), hidden.perturbed(variant, value):
        if example == "pendulum_can11":
            return _pendulum(level, plan, description, workers, wear="pendulum_can11:servo.gap_check_forecast" in wanted)
        if example in ("ur5e", "ur5e_2f85"):
            return _arm(example, plan, description, workers)
        if example == "conveyor":
            return _conveyor(plan, description, workers)
        if example == "dual_arm_cell":
            return _cell(plan, description, workers, knock="dual_arm_cell:camera.pose_recal_belt_tags" in wanted)
        if example == "linescan_cell":
            return _linescan(plan, description, workers)
        if example == "ur5e_backlash":
            return _ur_backlash(plan, description, workers)
    raise KeyError(f"no ladder runner for {example!r}")


def wants(check_id: str, level: str, variant: str | None) -> bool:
    check = RULER["checks"][check_id]
    if variant is None:
        return level in check.get("levels", list(LEVELS))
    return level == "1x" and variant in check.get("variants", [])


def runs_of(example: str) -> list[tuple[str, str | None]]:
    """The (level, variant) runs the ruler asks of an example's checks, in ruler order."""
    out = [(level, None) for level in LEVELS if any(wants(cid, level, None) for cid in checks_of(example))]
    out += [("1x", v) for v in RULER["variants"] if any(wants(cid, "1x", v) for cid in checks_of(example))]
    return out


def selected(level: str, variant: str | None, levels, variants) -> bool:
    """With neither filter every run; else the main levels named in `levels` and the variants named in `variants`."""
    if levels is None and variants is None:
        return True
    if variant is None:
        return levels is not None and level in levels
    return variants is not None and variant in variants


def _number(value):
    if value is None or isinstance(value, bool):
        return value
    value = float(value)
    return value if math.isfinite(value) else None


def run_example(example: str, levels=None, variants=None, *, workers: int = 6) -> list[dict]:
    """Every check of `example` at every level and variant the ruler declares (or only `levels` / `variants`), graded: the check docs."""
    description = describe.load(example)
    plan = _plan(example, description)
    doc = world_doc(example)
    rows: dict[str, list[dict]] = {cid: [] for cid in checks_of(example)}
    for level, variant in runs_of(example):
        if not selected(level, variant, levels, variants):
            continue
        started = time.monotonic()
        produced = run_level(example, level, variant, plan=plan, description=description, workers=workers)
        seconds = round(time.monotonic() - started, 1)
        provenance = {"identify_sealed": True, **result.provenance(example), "seconds": seconds}
        if example == "pendulum_can11":
            from .examples.pendulum_can11 import pipeline as P  # noqa: PLC0415

            label, record, _ = P._rack()
            provenance.update(twin_of_record=label, twin_of_record_digest=record.digest())
        for cid in rows:
            if not wants(cid, level, variant):
                continue
            got = produced[cid]
            recovered = {k: v for k, v in got["recovered"].items() if not k.startswith("_")}
            params = [grade(example, key, truth_of(example, key, doc), nominal_of(example, key, description), recovered.get(key), LEVELS[level])
                      for key in claimed(cid)]
            limits = [p["error_over_tolerance"] for p in params if p["error_over_tolerance"] is not None]
            rows[cid].append({"level": level, "scale": LEVELS[level], "variant": variant, "parameters": params,
                              "pass": all(p["pass"] for p in params), "usable": all(p["within_tolerance"] for p in params),
                              "worst_error_over_tolerance": max(limits) if len(limits) == len(params) else None,
                              "held_out": {k: _number(v) for k, v in got["held_out"].items()},
                              "notes": list(got["recovered"].get("_notes", [])), "provenance": provenance})
    return [check_doc(cid, rows[cid]) for cid in rows if rows[cid]]


def check_doc(check_id: str, rows: list[dict]) -> dict:
    check = RULER["checks"][check_id]
    order = {(level, None): i for i, level in enumerate(LEVELS)} | {("1x", v): len(LEVELS) + i for i, v in enumerate(RULER["variants"])}
    rows = sorted(rows, key=lambda r: order[(r["level"], r["variant"])])
    codes = sorted({r["provenance"]["code"] for r in rows})
    return {"id": check_id, "example": example_of(check_id), "procedure": check["procedure"], "owner": check["owner"], "structure": check["structure"],
            "parameters": claimed(check_id), "unclaimed": check.get("unclaimed", {}), "not_at": check.get("not_at", {}),
            "realism": check.get("realism", ""), "rows": rows,
            "provenance": {"identify_sealed": all(r["provenance"]["identify_sealed"] for r in rows), "code": codes}}


# --- the results file (merged across processes) ---------------------------------------------------------------------------------------

@contextlib.contextmanager
def _locked():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / ".noise_ladder.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def merge(new_checks: list[dict]) -> dict:
    """Write `new_checks` into the results file: rows replaced by (check, level, variant), every other row kept, checks in ruler order."""
    with _locked():
        old = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.is_file() else {"checks": []}
        by_id = {c["id"]: c for c in old.get("checks", []) if c["id"] in RULER["checks"]}
        for check in new_checks:
            keep = [r for r in by_id.get(check["id"], {}).get("rows", []) if (r["level"], r["variant"]) not in {(n["level"], n["variant"]) for n in check["rows"]}]
            by_id[check["id"]] = check_doc(check["id"], keep + check["rows"])
        doc = {"schema": SCHEMA, "ruler": {"path": "sysid/noise_ladder.json", "sha256": ruler_sha256()},
               "levels": RULER["levels"], "exact_fraction": EXACT_FRACTION, "variants": RULER["variants"],
               "checks": [by_id[cid] for cid in RULER["checks"] if cid in by_id]}
        result.write(doc, "noise_ladder")
        return doc
