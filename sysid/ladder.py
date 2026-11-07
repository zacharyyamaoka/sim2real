"""The noise ladder: every Calibration Routine the sysid oracle can run, on the same hidden truth at 0, 1x, 3x and 10x its world's sensor
noise and at 1x plus a delay or a quantisation where one matters, graded by sysid/noise_ladder.json (the ruler, committed before any run).

Zach, 2026-11-07 (via the coordinator): routines compared "on the same amount of noise"; and his Nov 6 note on kinematic calibration:
"test this in simluation where you have access to the ground truth to see what like perfect would be ... see if you can recover the
perfect values... (you can change the amount of noise you add to the sensor measurements...)".

A level runs an example's own pipeline unchanged (plan, RealWorld.measure, identify sealed, score) inside world.noise_scale(k), so every
noise channel is k times its committed value and draws the same normals; a variant runs at 1x inside world.perturbed(name, value), which
the example's RealWorld applies where its measurement would carry it. Each check reads the values its routine produced (the example's
fit, the stock fit beside it, T10's routine on the deployed check's runs, the drift demos) and grades them against the world's truth.

Per parameter a row keeps the true and nominal values, the tolerance and the bound, and every model the routine fitted it with (CAN 11's
regression fits rungs M0, M2, M3 and M4; every other routine one model): its recovered value (the fit's estimate) with the routine's own
95 % interval and how that interval was made, its error and its error in tolerances. The graded model is the routine's own claim (M4 for
the regression). Each parameter is also placed on its type card (card, rung, the card's parameter: sysid.cards.place), which is how a
parameter finds every routine that identifies it (type_cards reg.routines_identifying).

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
# WHY outside the repo: processes merging rows take this lock; a file in sysid/results would sit untracked beside the results
LOCK = Path.home() / ".cache" / "sim2real" / "sysid" / f"noise_ladder-{hashlib.sha256(str(RESULT_PATH).encode()).hexdigest()[:12]}.lock"


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


# Placement of the ladder's own keys that are not an example's result keys (sysid.cards.PLACE holds the rest)
LADDER_PLACE = {"can11.coulomb_sliding_nm": ("servo", "M2", "frictionloss_nm"), "camera_knock.*": ("camera_rgb", "M0", "extrinsics"),
                "*.backlash_rad": ("servo", "M4", "backlash_rad")}


def placement(example: str, key: str) -> dict:
    """Which card, rung and card parameter a ladder key is: sysid.cards.place for the examples' keys, LADDER_PLACE for the ladder's own;
    the card parameter is its bare name (cards.place writes a note beside some)."""
    from . import cards  # noqa: PLC0415

    hit = cards.place(example, key)
    if not hit["card"]:
        for pattern, (card, rung, parameter) in LADDER_PLACE.items():
            if fnmatch.fnmatchcase(key, pattern):
                hit = {"card": card, "rung": rung, "parameter": parameter}
                break
    name = (hit.get("parameter") or "").split(" (")[0] or None
    return {"card": hit.get("card"), "rung": hit.get("rung"), "card_parameter": name}


def unit_of(example: str, key: str, description) -> str:
    if key in description.nominal:
        return description.nominal[key].unit
    if key in RULER.get("derived_truth", {}):
        return RULER["derived_truth"][key]["unit"]
    return "rad/h" if key.endswith("_per_h") else "m" if key.endswith("_m") else "rad" if key.endswith("_rad") else ""


def _scored(value, truth: float, limit: float, bound_: float) -> dict:
    if value is None or not math.isfinite(float(value)):
        return {"error": None, "error_over_tolerance": None, "within_tolerance": False, "pass": False}
    error = abs(float(value) - truth)
    return {"error": error, "error_over_tolerance": error / limit if limit else None, "within_tolerance": error <= limit, "pass": error <= bound_}


def grade(example: str, key: str, truth: float, nominal: float | None, got: dict, scale: float, description) -> dict:
    """One parameter at one level: true, nominal, tolerance, bound, and every model the routine fitted it with, each its recovered value
    (the fit's estimate, the mean) and the routine's 95 % interval, its error and error in tolerances; the graded model's numbers are
    the row's own (recovered, ci95, error, pass)."""
    tol = tolerance(example, key)
    limit = tol[1] if tol[0] == "abs" else tol[1] * abs(truth)
    b = bound(tol, truth=truth, nominal=nominal, scale=scale)
    models = []
    for label, m in got.get("models", {}).items():
        if key not in m["values"]:
            continue
        value = m["values"][key]
        ci = m["ci95"].get(key)
        models.append({"model": label, "rung": m.get("rung"), "graded": label == got.get("graded"),
                       "recovered": {"mean": None if value is None else float(value), "ci95": None if ci is None else [float(ci[0]), float(ci[1])],
                                     "interval": m.get("interval")},
                       **_scored(value, truth, limit, b)})
    graded = next((m for m in models if m["graded"]), None)
    value = None if graded is None else graded["recovered"]["mean"]
    row = {"key": key, **placement(example, key), "unit": unit_of(example, key, description), "true": truth, "nominal": nominal,
           "tolerance": {"kind": tol[0], "value": tol[1]}, "bound": b,
           "recovered": value if value is not None and math.isfinite(value) else None,
           "ci95": None if graded is None else graded["recovered"]["ci95"], **_scored(value, truth, limit, b), "models": models}
    return row


# --- what each example's routines produce at one level ---------------------------------------------------------------------------

def _rms(values) -> float:
    import numpy as np  # noqa: PLC0415

    x = np.asarray(values, float)
    return float(np.sqrt(np.mean(x ** 2)))


def model(values: dict, ci95: dict | None = None, interval: str | None = None, rung: str | None = None) -> dict:
    """One model a routine fitted: its values by ladder key, their 95 % intervals (where the routine makes them) and how they were made."""
    return {"values": {k: v for k, v in values.items() if not k.startswith("_")}, "ci95": dict(ci95 or {}), "interval": interval, "rung": rung}


def produced(models: dict, graded: str, held_out: dict | None = None, notes=()) -> dict:
    return {"models": models, "graded": graded, "held_out": dict(held_out or {}), "notes": list(notes)}


def _failed(why: str) -> dict:
    return produced({}, "", {}, [why])


def _t10(plan, measured) -> dict:
    """The rack's T10 routine on the deployed check's runs (H2 operate, plan order): bam_rack_twin docs/round4_study.live_reid_estimates,
    live_reid.Rls over the first 60 s at forgetting 0.999, on the motor encoder's angle and the board's torque."""
    if str(ROUND4_DOCS) not in sys.path:
        sys.path.append(str(ROUND4_DOCS))
    import round4_study  # noqa: PLC0415

    runs = [measured.held_out[row["run"]].output for row in plan.check]
    estimate = round4_study.live_reid_estimates([{"t": r.t, "q": r.q, "tau": r.tau, "controlled": r.controlled} for r in runs])
    values = {"can11.gravity_nm": estimate["gravity_nm"], "can11.gravity_bottom_rad": estimate["gravity_bottom_rad"],
              "can11.armature_kg_m2": estimate["inertia"], "can11.damping_nm_s_rad": estimate["viscous"], "can11.coulomb_sliding_nm": estimate["coulomb"]}
    note = f"{estimate['rows_fed']} rows fed over {estimate['seconds_used']:.1f} s ({estimate['derivatives']}), forgetting {estimate['forgetting']}"
    return produced({"T10": model(values, interval="none: T10's recursive least squares reports no interval", rung="M2")}, "T10", notes=[note])


STOCK_KEYS = {"gravity_nm": "can11.gravity_nm", "gravity_bottom_rad": "can11.gravity_bottom_rad", "armature_kg_m2": "can11.armature_kg_m2",
              "damping_nm_s_rad": "can11.damping_nm_s_rad", "frictionloss_nm": "can11.coulomb_sliding_nm"}


def _stock(stock: dict | None) -> dict:
    """bam_rack_twin.identify_without_cad's estimates (pipeline.stock_fit), by the ladder's keys, with their own 95 % intervals; a refusal
    is noted beside its value."""
    values, ci95, notes = {}, {}, []
    stock = stock or {}
    if "error" in stock:
        notes.append(f"the stock fit raised: {stock['error']}")
    for name, key in STOCK_KEYS.items():
        est = stock.get("estimates", {}).get(name)
        values[key] = None if est is None else est.get("value")
        if est and est.get("ci95"):
            ci95[key] = tuple(est["ci95"])
        if est and est.get("refused"):
            notes.append(f"{name}: {est['refused']}")
    return produced({"stock": model(values, ci95, "identify_without_cad's own 95 % intervals (each estimate's)", rung="M2")}, "stock", notes=notes)


def _guarded(compute):
    """(value, None), or (None, "raised <type>: <message>") when the routine raises: a routine that breaks down is a failed row with its
    own words, never a crashed ladder (2026-11-07: CAN 11's regression raised at 10x, its friction polish refusing the twin its Stribeck
    fit asked for)."""
    try:
        return compute(), None
    except Exception as error:  # noqa: BLE001 - recorded in the row, never hidden
        return None, f"raised {type(error).__name__}: {error}"


REGRESSION_INTERVAL = "the stock block bootstrap of the regression (bam_rack_twin identify.block_bootstrap, 0.5 s blocks)"


def _pendulum(level: str, plan, description, workers: int, wear: bool) -> dict:
    """CAN 11's four routines, each graded on its own: the sysid regression (its rungs M0, M2, M3 and M4, graded on M4), the gap from
    the camera (the same backlash_from_gaps identify() calls), the stock quasi-static fits (the same stock_fit identify() calls) and T10."""
    from . import drift  # noqa: PLC0415
    from .examples.pendulum_can11 import pipeline as P  # noqa: PLC0415

    real = P.RealWorld(description, workers=workers)
    measured = real.measure(plan)
    with hidden.sealed():
        gap, gap_error = _guarded(lambda: P.backlash_from_gaps([run.output.q - run.q_link for run in measured.train.values()]))
        stock, stock_error = _guarded(lambda: P.stock_fit(measured.train))
        t10, t10_error = _guarded(lambda: _t10(plan, measured))
        fit, fit_error = _guarded(lambda: P.identify(description, measured.train))
    gap_ci = {} if fit_error else {"can11.backlash_rad": tuple(fit.ci95["M4"]["backlash_rad"])}
    gap_interval = ("a bootstrap over runs of the same two-level fit (inside pipeline.identify)" if not fit_error else
                    "none at this level: its bootstrap runs inside pipeline.identify, which raised")
    out = {"pendulum_can11:servo.backlash_reversals_camera": _failed(gap_error) if gap_error else
           produced({"M4": model({"can11.backlash_rad": float(gap)}, gap_ci, gap_interval, rung="M4")}, "M4"),
           "pendulum_can11:servo.stock_quasistatic": _failed(stock_error) if stock_error else _stock(stock),
           "pendulum_can11:servo.live_reid_t10": _failed(t10_error) if t10_error else t10}
    if fit_error:
        out["pendulum_can11:servo.dynamics_regression"] = _failed(fit_error)
        if wear:
            # WHY the gap check still runs (2026-11-07): its alarm and forecast are in the gap's own units, read from commissioning's gap (the
            # reversals routine, the M4 fit's own) and each check's; the regression's failure costs it only the twin (the fidelity ratio, the
            # recalibration)
            out["pendulum_can11:servo.gap_check_forecast"] = (
                _failed(f"not run: its commissioning gap (the reversals routine) {gap_error}") if gap_error else
                _gap_check(drift.run_backlash(workers=workers, commissioned_gap=float(gap)), [f"no twin: the regression's M4 fit {fit_error}"]))
        return out
    scores = P.score(description, plan, fit, measured, workers=workers)
    # each rung's own estimates only (a rung's fixed terms, like M0's zero friction, are not estimates); M4's static level and drop are
    # the polished point, its interval the regression's (pipeline.refine_friction: the polish moves the point, not the spread)
    rungs = {rung: model({f"can11.{k}": fit.values[rung][k] for k in fit.ci95[rung]}, {f"can11.{k}": tuple(v) for k, v in fit.ci95[rung].items()},
                         REGRESSION_INTERVAL + (" (M4's backlash: a bootstrap over runs; its static level and drop are polished, the interval the "
                                                "regression's)" if rung == "M4" else ""), rung=rung)
             for rung in P.RUNGS}
    held = {"link_mrad": scores["models"]["M4"]["link_mrad"], "link_x_floor": scores["models"]["M4"]["ratio"]}
    held.update({f"link_mrad_{rung}": scores["models"][rung]["link_mrad"] for rung in P.RUNGS})
    out["pendulum_can11:servo.dynamics_regression"] = produced(rungs, "M4", held)
    out["pendulum_can11:servo.backlash_reversals_camera"]["held_out"] = {"link_mrad": held["link_mrad"]}
    if wear:
        out["pendulum_can11:servo.gap_check_forecast"] = _gap_check(drift.run_backlash(workers=workers, commissioned_values=fit.values["M4"]))
    return out


def _gap_check(doc: dict, notes=()) -> dict:
    """The deployed gap check's row from its drift demo (sysid.drift.run_backlash): the wear rate graded; held out, the servo's alarm (the
    gap check or the fidelity ratio, whichever warns first), each one's own alarm hour on the same checks, the hour the hidden gap crossed
    its allowance, and the forecast."""
    actual, predicted = doc["actual_crossing_h"], doc["predicted_crossing_h"]
    gaps = [c["b_hat_rad"] - c["b_true_rad"] for c in doc["checks"]]
    return produced(
        {"wear": model({"can11.backlash_wear_rad_per_h": doc["rate_recovered"]}, {"can11.backlash_wear_rad_per_h": tuple(doc["rate_ci95"])},
                       "the gap line's 95 % interval on the checks up to the forecast (drift.line_fit)", rung="M5.wear")}, "wear",
        {"forecast_error_pct": None if not (actual and predicted) else 100.0 * (predicted - actual) / actual,
         "lead_h": None if actual is None else actual - doc["predicted_at_h"], "gap_rms_mrad": 1e3 * _rms(gaps),
         "recalibrated_ratio": (doc.get("recalibrated") or {}).get("ratio"), "predicted_crossing_h": predicted, "actual_crossing_h": actual,
         "detector_alarm_h": doc["detector_alarm_h"], "gap_alarm_h": doc["gap_alarm_h"], "ratio_alarm_h": doc["ratio_alarm_h"], "ratio_crossing_h": doc["ratio_crossing_h"],
         "commissioned_gap_mrad": 1e3 * doc["commissioned_gap_rad"], "allowance_mrad": 1e3 * doc["allowance_rad"]},
        notes)


def _fit_model(fit, interval: str, rung: str | None = None) -> dict:
    return model(fit.values, {k: tuple(v) for k, v in fit.ci95.items() if v is not None}, interval, rung)


def _arm(example: str, plan, description, workers: int) -> dict:
    module = oracle.example_module(example)
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    m = module.score(description, plan, fit, measured, workers=workers)["models"]
    out = {f"{example}:kinematics.zero_offsets_tracker": produced(
               {"fit": _fit_model(fit, "the Levenberg-Marquardt Jacobian at the solution (sysid.arm.fit_kinematics)")}, "fit",
               {"tool_mm": m["kinematics"]["tool_mm"]}),
           f"{example}:arm.dynamics_excitation": produced(
               {"fit": _fit_model(fit, "a moving-block bootstrap, 0.5 s blocks (sysid.arm.fit_dynamics)")}, "fit", {"torque_nm": m["fitted"]["torque_nm"]})}
    if example == "ur5e_2f85":
        out[f"{example}:gripper.drive_traces"] = produced(
            {"fit": _fit_model(fit, "the least-squares Jacobian at the solution (sysid.arm.fit_gripper)")}, "fit", {"finger_mrad": m["fitted"]["finger_mrad"]})
    return out


def _conveyor(plan, description, workers: int) -> dict:
    module = oracle.example_module("conveyor")
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    m = module.score(description, plan, fit, measured, workers=workers)["models"]
    return {"conveyor:conveyor.radius_tracker": produced({"fit": _fit_model(fit, "the least-squares covariance of the travel-on-angle fit")}, "fit",
                                                         {"belt_mm_radius": m["radius"]["belt_mm"]}),
            "conveyor:conveyor.dynamics_profiles": produced({"fit": _fit_model(fit, "the least-squares Jacobian at the solution")}, "fit",
                                                            {"belt_mm": m["fitted"]["belt_mm"]})}


def _cell(plan, description, workers: int, knock: bool) -> dict:
    from . import drift  # noqa: PLC0415

    module = oracle.example_module("dual_arm_cell")
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    m = module.score(description, plan, fit, measured, workers=workers)["models"]["fitted"]
    out = {"dual_arm_cell:cell.tags_bundle_adjustment": produced(
        {"fit": _fit_model(fit, "the Levenberg-Marquardt Jacobian at the solution (sysid.camera.least_squares_with_ci)")}, "fit",
        {"reprojection_px": m["reprojection_px"], "pick_mm": m["pick_mm"]})}
    if knock:
        doc = drift.run_camera(workers=workers)
        out["dual_arm_cell:camera.pose_recal_belt_tags"] = produced(
            {"recalibration": model({f"camera_knock.{name}": value for name, value in doc["shift_recovered"].items()},
                                    interval="none: the shift is the change of the re-fitted pose; its interval is not propagated", rung="M0")},
            "recalibration", {"alarm_h": doc["alarm_h"], "recalibrated_ratio": (doc.get("recalibrated") or {}).get("ratio")})
    return out


def _linescan(plan, description, workers: int) -> dict:
    module = oracle.example_module("linescan_cell")
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    m = module.score(description, plan, fit, measured, workers=workers)["models"]["fitted"]
    return {"linescan_cell:linescan.geometry_dot_card": produced({"fit": _fit_model(fit, "the Levenberg-Marquardt Jacobian at the solution")}, "fit",
                                                                 {"scan_position_mm": m["scan_position_mm"]}),
            "linescan_cell:linescan.radiometry_refs": produced({"fit": _fit_model(fit, "the per-band least-squares covariance")}, "fit",
                                                               {"spectral_angle_mrad": m["spectral_angle_mrad"]}),
            "linescan_cell:rgbd.dot_card": produced({"fit": _fit_model(fit, "the Levenberg-Marquardt Jacobian at the solution")}, "fit",
                                                    {"cloud_mm": m["cloud_mm"]})}


def _ur_backlash(plan, description, workers: int) -> dict:
    module = oracle.example_module("ur5e_backlash")
    measured = module.RealWorld(description, workers=workers).measure(plan)
    with hidden.sealed():
        fit = module.identify(description, measured.train)
    notes = [f"{name}: flanks {1e3 * f['low_rad']:+.4f} / {1e3 * f['high_rad']:+.4f} mrad, friction {f['friction_nm']:.3f} N.m" for name, f in fit.flanks.items()]
    notes += [f"not swept: {line}" for line in plan.coverage["train"]["unplanned"]]
    return {"ur5e_backlash:arm.backlash_gravity_sweep": produced(
        {"fit": model(fit.values, interval="none: gear_backlash's flank fit reports no interval", rung="M4")}, "fit", notes=notes)}


def _plan(example: str, description):
    return oracle.example_module(example).plan(description)


def run_level(example: str, level: str, variant: str | None, *, plan, description, workers: int = 6) -> dict:
    """Every check of `example` at one level (or one variant at 1x): {check id: produced(models, graded, held_out, notes)}, the example's
    pipeline unchanged."""
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
        outputs = run_level(example, level, variant, plan=plan, description=description, workers=workers)
        seconds = round(time.monotonic() - started, 1)
        provenance = {"identify_sealed": True, **result.provenance(example), "seconds": seconds}
        if example == "pendulum_can11":
            from .examples.pendulum_can11 import pipeline as P  # noqa: PLC0415

            label, record, _ = P._rack()
            provenance.update(twin_of_record=label, twin_of_record_digest=record.digest())
        for cid in rows:
            if not wants(cid, level, variant):
                continue
            got = outputs[cid]
            params = [grade(example, key, truth_of(example, key, doc), nominal_of(example, key, description), got, LEVELS[level], description)
                      for key in claimed(cid)]
            limits = [p["error_over_tolerance"] for p in params if p["error_over_tolerance"] is not None]
            rows[cid].append({"level": level, "scale": LEVELS[level], "variant": variant, "parameters": params,
                              "pass": all(p["pass"] for p in params), "usable": all(p["within_tolerance"] for p in params),
                              "worst_error_over_tolerance": max(limits) if len(limits) == len(params) else None,
                              "held_out": {k: _number(v) for k, v in got["held_out"].items()},
                              "graded_model": got.get("graded") or None, "models": list(got.get("models", {})),
                              "notes": list(got.get("notes", [])), "provenance": provenance})
    return [check_doc(cid, rows[cid]) for cid in rows if rows[cid]]


def check_doc(check_id: str, rows: list[dict]) -> dict:
    check = RULER["checks"][check_id]
    order = {(level, None): i for i, level in enumerate(LEVELS)} | {("1x", v): len(LEVELS) + i for i, v in enumerate(RULER["variants"])}
    rows = sorted(rows, key=lambda r: order[(r["level"], r["variant"])])
    codes = sorted({r["provenance"]["code"] for r in rows})
    return {"id": check_id, "example": example_of(check_id), "routine": check["routine"], "owner": check["owner"], "structure": check["structure"],
            "parameters": claimed(check_id), "unclaimed": check.get("unclaimed", {}), "not_at": check.get("not_at", {}),
            "realism": check.get("realism", ""), "rows": rows,
            "provenance": {"identify_sealed": all(r["provenance"]["identify_sealed"] for r in rows), "code": codes}}


# --- the results file (merged across processes) ---------------------------------------------------------------------------------------

@contextlib.contextmanager
def _locked():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
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
