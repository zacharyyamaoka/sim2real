"""The noise ladder: every Calibration Routine the sysid oracle can run, graded on the same hidden truth at 0, 1x, 3x and 10x its
sensor noise, and with a delay or a quantisation where one matters (2026-11-07), written before the ladder code.

Zach, 2026-11-07 (via the coordinator): any twin error is the models' fidelity or the parameters' accuracy, so the routines that
calibrate the parameters are first-class ("Calibration Routine", his name for them the same day), compared "on the same amount of noise",
and every parameter keeps true, nominal, recovered (its mean and 95 % interval), error and tolerance per model. His note of Nov 6 on kinematic
calibration: "Definetily test this in simluation where you have access to the ground truth to see what like perfect would be type
thing. Also see if you can recover the perfect values... (you can change the amount of noise you add to the sensor measurements...)".

The ruler is sysid/noise_ladder.json, pinned below by digest and committed before any ladder result; the results are
sysid/results/noise_ladder.json (python -m sysid ladder --write); the comparison table is sysid/results/calibration_routines.json
(python -m sysid routines --write), the join of the ladder and type_cards' routine records, routine -> parameters and parameter -> routines.

What it holds:
- the ruler: pinned, and committed before the first ladder result; levels 0 < 1 < 3 < 10; the bound's arithmetic on worked numbers;
  every check names a type-card routine that names it back; every parameter a check claims has a tolerance and a truth;
- the results: every check at every level and variant the ruler declares (a level not run says why); every verdict is the ruler's
  arithmetic on the row's own numbers; every truth is the world's; backlash hidden and graded on every geared joint the oracle has; every
  parameter placed on its card and kept per model (recovered mean and 95 % interval, error), the graded model the row's own numbers;
- the oracle: a check's 1x row is the committed example result (the same code at the same noise gives the same numbers);
- the code: the fast checks re-run here and equal the committed ladder; the slow ones (CAN 11, the UR arms, the wear demo) re-run when
  SYSID_LADDER_SLOW=1 (most of an hour);
- the table: calibration_routines.json is the join recomputed here, in the shape type_cards/CONTRACT.md documents.

Failures at a level are findings, not test failures: the ladder exists to say what breaks where (a routine that raises is a failed row
with its message, never a crashed ladder). What this file fails on is a
verdict that is not the ruler's, a number that is not the code's, or a row the ruler asked for and nobody ran.

    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/sysid/tests/test_noise_ladder.py
"""

from __future__ import annotations

import fnmatch
import hashlib
import inspect
import json
import math
import os
import subprocess
from pathlib import Path

import pytest

SYSID = Path(__file__).resolve().parents[1]
REPO = SYSID.parent
RULER_PATH = SYSID / "noise_ladder.json"
# WHY pinned: the bounds are data the ladder reads; a digest here makes any edit to them an edit of this file, reviewed as a ruler change
RULER_SHA256 = "26c5a78b2b71b8fe85ad1fd26828382220bb783eef78abedabc92e8cc6799fe9"
RULER = json.loads(RULER_PATH.read_text())
ACCEPTANCE = json.loads((SYSID / "acceptance.json").read_text())
RESULTS = SYSID / "results" / "noise_ladder.json"
TABLE = SYSID / "results" / "calibration_routines.json"
SLOW = os.environ.get("SYSID_LADDER_SLOW") == "1"
FAST_EXAMPLES = ("conveyor", "dual_arm_cell", "linescan_cell", "ur5e_backlash")
GEARED = {"pendulum_can11": ["can11.backlash_rad"],
          "ur5e_backlash": ["shoulder_lift.backlash_rad", "elbow.backlash_rad", "wrist_1.backlash_rad", "wrist_2.backlash_rad"]}
TABLE_ROW_KEYS = ("routine", "title", "package", "kind", "setting", "status", "wall_time", "operator_time", "equipment", "equipment_cost",
                  "identifies", "parameters_covered", "excitation", "coverage", "repeats", "oracle", "alternatives", "note")
PARAMETER_KEYS = ("example", "key", "card", "rung", "card_parameter", "unit", "true", "nominal", "tolerance", "routines", "checks", "models")


def committed() -> dict:
    return json.loads(RESULTS.read_text())


def world(example: str) -> dict:
    return json.loads((SYSID / "examples" / example / "world.json").read_text())


def example_of(check_id: str) -> str:
    return check_id.split(":", 1)[0]


def rows(doc: dict | None = None):
    for check in (doc or committed())["checks"]:
        for row in check["rows"]:
            yield check, row


# --- the ruler -------------------------------------------------------------------------------------------------------------------

def test_the_ladder_ruler_is_pinned():
    assert hashlib.sha256(RULER_PATH.read_bytes()).hexdigest() == RULER_SHA256


def test_the_ruler_was_committed_before_any_ladder_result():
    """Declared before any run (the brief): the first commit that adds the ruler precedes the first that adds a ladder result."""
    def first(path: str) -> str | None:
        out = subprocess.run(["git", "-C", str(REPO), "log", "--diff-filter=A", "--format=%H", "--", path], capture_output=True, text=True)
        shas = out.stdout.split()
        return shas[-1] if out.returncode == 0 and shas else None

    ruler, result = first("sysid/noise_ladder.json"), first("sysid/results/noise_ladder.json")
    if ruler is None:
        pytest.skip("not a git checkout with the ruler committed")
    assert result is not None, "no ladder result committed"
    assert ruler != result and subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", ruler, result]).returncode == 0, (
        f"the ruler ({ruler[:8]}) must be committed before the first ladder result ({result[:8]})")


def test_the_levels_and_the_bound_rule():
    from sysid import ladder

    scales = [level["scale"] for level in RULER["levels"]]
    assert scales == [0.0, 1.0, 3.0, 10.0] and [level["id"] for level in RULER["levels"]] == ["0x", "1x", "3x", "10x"]
    f = RULER["exact_fraction"]
    assert 0 < f < 1
    # worked by hand: tol 0.1 (rel) on a truth of 1.0, nominal 1.5 (its error 0.5)
    tol = ("rel", 0.1)
    assert ladder.bound(tol, truth=1.0, nominal=1.5, scale=0.0) == pytest.approx(0.1 * f)
    assert [ladder.bound(tol, truth=1.0, nominal=1.5, scale=k) for k in (1.0, 3.0, 10.0)] == pytest.approx([0.1, 0.3, 0.5])
    # a nominal already inside the tolerance never shrinks the bound below it
    assert ladder.bound(("abs", 0.001), truth=0.0, nominal=0.0, scale=10.0) == pytest.approx(0.001)
    assert ladder.bound(("abs", 0.001), truth=0.0, nominal=None, scale=3.0) == pytest.approx(0.003)
    for name, variant in RULER["variants"].items():
        assert variant["examples"] and variant["unit"] and variant["source"] and variant["value"] > 0, name


def test_every_check_is_a_type_card_routine_and_back():
    from type_cards import registry as reg

    named = {name: r.id for r in reg.ROUTINES for name in r.oracle}
    assert set(named) == set(RULER["checks"]), (sorted(set(named) - set(RULER["checks"])), sorted(set(RULER["checks"]) - set(named)))
    for check_id, check in RULER["checks"].items():
        assert named[check_id] == check["routine"] == check_id.split(":", 1)[1], check_id
        assert check["owner"] in ("sysid", "bam_ws") and check["structure"].split(":")[0] in ("matches", "mismatch"), check_id
        assert set(check.get("variants", [])) <= set(RULER["variants"]), check_id
        assert all(example_of(check_id) in RULER["variants"][v]["examples"] for v in check.get("variants", [])), check_id


def test_every_claimed_parameter_has_a_tolerance_and_a_truth():
    from sysid import ladder

    for check_id, check in RULER["checks"].items():
        example = example_of(check_id)
        keys = ladder.claimed(check_id)
        assert keys, check_id
        for key in keys:
            assert ladder.tolerance(example, key) is not None, (check_id, key)
            assert ladder.truth_of(example, key, world(example)) is not None, (check_id, key)
    # the ladder's own new truths are ones not calibrating fails (acceptance.json's own rule, for what it does not hold)
    from sysid import describe

    nominal = describe.load("ur5e_backlash").nominal
    for key in ladder.claimed("ur5e_backlash:arm.backlash_gravity_sweep"):
        tol = ladder.tolerance("ur5e_backlash", key)
        assert abs(nominal[key].value - world("ur5e_backlash")["truth"][key]) > tol[1], key
    derived = RULER["derived_truth"]["can11.coulomb_sliding_nm"]
    truth = ladder.truth_of("pendulum_can11", "can11.coulomb_sliding_nm", world("pendulum_can11"))
    nominal_value = describe.load("pendulum_can11").nominal[derived["nominal_of"]].value
    assert abs(nominal_value - truth) > derived["tolerance"][1] * abs(truth)


# --- the committed results ---------------------------------------------------------------------------------------------------------

def test_the_committed_ladder_has_every_row_the_ruler_declares():
    doc = committed()
    assert doc["schema"] == "sysid.noise_ladder_result/1" and doc["ruler"]["sha256"] == RULER_SHA256
    checks = {c["id"]: c for c in doc["checks"]}
    assert set(checks) == set(RULER["checks"])
    for check_id, check in RULER["checks"].items():
        levels = check.get("levels", [level["id"] for level in RULER["levels"]])
        got = {(r["level"], r["variant"]) for r in checks[check_id]["rows"]}
        want = {(level, None) for level in levels} | {("1x", v) for v in check.get("variants", [])}
        assert got == want, (check_id, sorted(want - got), sorted(got - want))
        assert set(checks[check_id].get("not_at", {})) == set(check.get("not_at", {})), check_id


def test_every_verdict_is_the_rulers_arithmetic():
    from sysid import ladder

    for check, row in rows():
        example = example_of(check["id"])
        for p in row["parameters"]:
            tol = ladder.tolerance(example, p["key"])
            assert p["tolerance"] == {"kind": tol[0], "value": tol[1]}, (check["id"], p["key"])
            want_bound = ladder.bound(tol, truth=p["true"], nominal=p["nominal"], scale=row["scale"])
            assert p["bound"] == pytest.approx(want_bound, rel=1e-12), (check["id"], row["level"], p["key"])
            if p["recovered"] is None:
                assert p["pass"] is False and p["within_tolerance"] is False and p["error"] is None, (check["id"], p["key"])
                continue
            error = abs(p["recovered"] - p["true"])
            assert p["error"] == pytest.approx(error, rel=1e-12, abs=1e-15), (check["id"], p["key"])
            limit = tol[1] if tol[0] == "abs" else tol[1] * abs(p["true"])
            assert p["pass"] is (error <= want_bound) and p["within_tolerance"] is (error <= limit), (check["id"], row["level"], p["key"])
        assert row["pass"] is all(p["pass"] for p in row["parameters"]), (check["id"], row["level"])


def test_every_rows_truth_is_the_worlds():
    from sysid import ladder

    for check, row in rows():
        example = example_of(check["id"])
        w = world(example)
        for p in row["parameters"]:
            assert p["true"] == ladder.truth_of(example, p["key"], w), (check["id"], p["key"])
        assert {p["key"] for p in row["parameters"]} == set(ladder.claimed(check["id"])), check["id"]


def test_the_1x_rows_are_the_committed_oracle_results():
    """A check's 1x row, no variant, is the oracle's committed result for its example: the ladder adds levels, never a second 1x."""
    for check, row in rows():
        example = example_of(check["id"])
        if row["level"] != "1x" or row["variant"] is not None:
            continue
        if example in ("pendulum_can11", "ur5e", "ur5e_2f85", "conveyor", "dual_arm_cell", "linescan_cell") and check["id"].split(":", 1)[1] in (
                "servo.dynamics_regression", "servo.backlash_reversals_camera", "kinematics.zero_offsets_tracker", "arm.dynamics_excitation",
                "gripper.drive_traces", "conveyor.radius_tracker", "conveyor.dynamics_profiles", "cell.tags_bundle_adjustment",
                "linescan.geometry_dot_card", "linescan.radiometry_refs", "rgbd.dot_card"):
            oracle = {r["key"]: r for r in json.loads((SYSID / "results" / f"{example}.json").read_text())["parameters"]}
            for p in row["parameters"]:
                assert math.isclose(p["recovered"], oracle[p["key"]]["recovered"], rel_tol=1e-9, abs_tol=1e-12), (check["id"], p["key"])
        if check["id"] == "pendulum_can11:servo.gap_check_forecast":
            wear = json.loads((SYSID / "results" / "drift_backlash_wear.json").read_text())
            assert math.isclose(row["parameters"][0]["recovered"], wear["rate_recovered"], rel_tol=1e-9)
            for key in ("detector_alarm_h", "gap_alarm_h", "actual_crossing_h", "predicted_crossing_h", "ratio_alarm_h"):
                x, y = row["held_out"][key], wear[key]
                assert (x is None and y is None) or math.isclose(x, y, rel_tol=1e-9), (key, x, y)
        if check["id"] == "dual_arm_cell:camera.pose_recal_belt_tags":
            knock = json.loads((SYSID / "results" / "drift_camera_knock.json").read_text())
            for p in row["parameters"]:
                assert math.isclose(p["recovered"], knock["shift_recovered"][p["key"].split(".", 1)[1]], rel_tol=1e-9, abs_tol=1e-12), p["key"]


def test_backlash_is_hidden_and_graded_on_every_geared_joint():
    """Zach's brief: backlash a first-class oracle parameter wherever a joint has gears (the pendulum, the UR joints)."""
    by_check = {c["id"]: c for c in committed()["checks"]}
    for example, keys in GEARED.items():
        assert set(keys) <= set(world(example)["truth"]), example
        graded = {p["key"] for c in by_check.values() if example_of(c["id"]) == example for r in c["rows"] for p in r["parameters"]}
        assert set(keys) <= graded, (example, sorted(set(keys) - graded))


def test_the_gap_check_warns_inside_the_horizon_where_the_fidelity_ratio_went_deaf():
    """The finding that moved the servo's drift alarm into the gap's own units (decision-calibration-routines-2026-11-07, its addendum):
    at 3x the camera's noise the fidelity ratio (live / the camera's floor / its hour-0 value) never warns inside the 480 h horizon; the gap
    check on the same checks does, as it does at 1x. Its row needs no twin: at 10x, where the regression raises and commissions none, the
    gap check still runs on the reversals routine's commissioning gap and says so."""
    check = next(c for c in committed()["checks"] if c["id"] == "pendulum_can11:servo.gap_check_forecast")
    by_level = {r["level"]: r for r in check["rows"] if r["variant"] is None}
    horizon = json.loads((SYSID / "examples" / "pendulum_can11" / "description.json").read_text())["monitoring"]["horizon_h"]
    for level in ("1x", "3x"):
        held = by_level[level]["held_out"]
        assert held["detector_alarm_h"] is not None and held["detector_alarm_h"] <= horizon, (level, held)
        assert held["actual_crossing_h"] is not None and held["allowance_mrad"] > 0, (level, held)
    assert by_level["1x"]["held_out"]["ratio_alarm_h"] is not None and by_level["3x"]["held_out"]["ratio_alarm_h"] is None, "the finding"
    ten = by_level["10x"]
    assert ten["parameters"][0]["recovered"] is not None and ten["held_out"]["ratio_alarm_h"] is None, ten["notes"]
    assert any("no twin" in note for note in ten["notes"]), ten["notes"]


def test_the_servo_alarm_is_the_earlier_of_the_gap_check_and_the_ratio_at_every_level():
    """The alarm warns on either check (the addendum's last line): at 1x the ratio is first, at 3x only the gap check warns inside the
    horizon, at 10x (no twin, so no ratio) the gap check alone; at every level the alarm hour is the earlier of the two that came."""
    check = next(c for c in committed()["checks"] if c["id"] == "pendulum_can11:servo.gap_check_forecast")
    by_level = {r["level"]: r["held_out"] for r in check["rows"] if r["variant"] is None}
    for level, held in by_level.items():
        came = [h for h in (held["gap_alarm_h"], held["ratio_alarm_h"]) if h is not None]
        assert held["detector_alarm_h"] == (min(came) if came else None), (level, held)
    assert by_level["1x"]["detector_alarm_h"] == by_level["1x"]["ratio_alarm_h"] < by_level["1x"]["gap_alarm_h"], "1x: the ratio is first"
    assert by_level["3x"]["detector_alarm_h"] == by_level["3x"]["gap_alarm_h"], "3x: the ratio never warned, the gap check did"


def test_the_ur_backlash_fit_never_reads_the_world():
    from sysid import oracle

    module = oracle.example_module("ur5e_backlash")
    source = inspect.getsource(module.identify)
    assert "world" not in source.lower() and "truth" not in source.lower()
    for check in committed()["checks"]:
        assert check["provenance"]["identify_sealed"] is True, check["id"]


# --- this code ------------------------------------------------------------------------------------------------------------------

def same(a: dict, b: dict, check_id: str) -> None:
    ra = {(r["level"], r["variant"]): r for r in a["rows"]}
    rb = {(r["level"], r["variant"]): r for r in b["rows"]}
    assert ra.keys() == rb.keys(), check_id
    for key in ra:
        pa = {p["key"]: p for p in ra[key]["parameters"]}
        pb = {p["key"]: p for p in rb[key]["parameters"]}
        assert pa.keys() == pb.keys(), (check_id, key)
        for k in pa:
            x, y = pa[k]["recovered"], pb[k]["recovered"]
            assert (x is None and y is None) or math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-12), (check_id, key, k, x, y)


def test_the_fresh_result_comparator_sees_every_substantive_field():
    """The v3 audit (2026-11-07, finding 6): same() compared the recovered scalars only, so a fresh ladder result whose intervals, alarms
    or held-out scores had moved still matched the committed one. Every edit below leaves every recovered value as committed and must turn
    the comparison red; one that touches only where and when it ran (the declared volatile provenance) must not, and identification having
    run sealed is compared like any other result."""
    import copy  # noqa: PLC0415

    checks = {c["id"]: c for c in committed()["checks"]}
    regression = checks["pendulum_can11:servo.dynamics_regression"]
    gap = checks["pendulum_can11:servo.gap_check_forecast"]
    sweep = checks["ur5e_backlash:arm.backlash_gravity_sweep"]

    def row(check: dict, level: str = "1x") -> dict:
        return next(r for r in check["rows"] if r["level"] == level and r["variant"] is None)

    def recovered(check: dict) -> list:
        return [(r["level"], r["variant"], p["key"], p["recovered"], [m["recovered"]["mean"] for m in p["models"]])
                for r in check["rows"] for p in r["parameters"]]

    def scaled(cell: dict, key: str, factor: float) -> None:
        cell[key] = cell[key] * factor

    edits = {
        "a parameter's 95 % interval": (regression, lambda c: row(c)["parameters"][0]["ci95"].__setitem__(1, row(c)["parameters"][0]["ci95"][1] * 1.01)),
        "a model's 95 % interval": (regression, lambda c: row(c)["parameters"][0]["models"][0]["recovered"]["ci95"].__setitem__(0, 0.0)),
        "the words of a model's interval": (regression, lambda c: row(c)["parameters"][0]["models"][0]["recovered"].__setitem__("interval", "another bootstrap")),
        "the alarm hour": (gap, lambda c: scaled(row(c)["held_out"], "detector_alarm_h", 1.5)),
        "the gap check's own alarm": (gap, lambda c: row(c)["held_out"].__setitem__("gap_alarm_h", None)),
        "a held-out score (the link's error)": (regression, lambda c: scaled(row(c)["held_out"], "link_mrad", 1.5)),
        "a held-out score (the forecast's error)": (gap, lambda c: scaled(row(c)["held_out"], "forecast_error_pct", 2.0)),
        "a level's verdict": (regression, lambda c: row(c).__setitem__("pass", not row(c)["pass"])),
        "a parameter's within-tolerance": (regression, lambda c: row(c)["parameters"][0].__setitem__("within_tolerance", not row(c)["parameters"][0]["within_tolerance"])),
        "a parameter's bound": (regression, lambda c: scaled(row(c)["parameters"][0], "bound", 2.0)),
        "the graded model": (regression, lambda c: row(c).__setitem__("graded_model", "M3")),
        "a note": (sweep, lambda c: row(c)["notes"].append("a note the code does not write")),
        "the claimed parameters": (sweep, lambda c: c["parameters"].append("wrist_3.backlash_rad")),
        "identification having run sealed": (regression, lambda c: row(c)["provenance"].__setitem__("identify_sealed", False)),
    }
    same(regression, copy.deepcopy(regression), regression["id"])
    for what, (check, edit) in edits.items():
        bad = copy.deepcopy(check)
        edit(bad)
        assert bad != check and recovered(bad) == recovered(check), f"{what}: the edit must leave every recovered value as committed"
        with pytest.raises(AssertionError):
            same(check, bad, check["id"])
            pytest.fail(f"same() did not see {what}")
    # where and when it ran is not a result: the commit, the imported checkouts, the seconds, the twin record's bytes
    moved = copy.deepcopy(regression)
    moved["provenance"]["code"] = ["0000000"]
    for r in moved["rows"]:
        r["provenance"].update(code="0000000", imports=[], seconds=0.1, twin_of_record_digest="0" * 64)
    same(regression, moved, regression["id"])


@pytest.mark.parametrize("example", FAST_EXAMPLES)
def test_the_fast_checks_are_this_code(example):
    from sysid import ladder

    fresh = {c["id"]: c for c in ladder.run_example(example)}
    old = {c["id"]: c for c in committed()["checks"] if example_of(c["id"]) == example}
    assert fresh.keys() == old.keys() and fresh
    for check_id in fresh:
        same(old[check_id], fresh[check_id], check_id)


@pytest.mark.skipif(not SLOW, reason="the CAN 11, UR arm and wear checks take most of an hour: SYSID_LADDER_SLOW=1 runs them")
@pytest.mark.parametrize("example", ("pendulum_can11", "ur5e", "ur5e_2f85"))
def test_the_slow_checks_are_this_code(example):
    from sysid import ladder

    fresh = {c["id"]: c for c in ladder.run_example(example)}
    old = {c["id"]: c for c in committed()["checks"] if example_of(c["id"]) == example}
    assert fresh.keys() == old.keys() and fresh
    for check_id in fresh:
        same(old[check_id], fresh[check_id], check_id)


# --- the comparison table -------------------------------------------------------------------------------------------------------

def test_the_comparison_table_is_the_join_of_the_records_and_the_ladder():
    from sysid import routines

    assert json.loads(TABLE.read_text()) == routines.table(committed())


def test_the_table_has_the_contracts_shape():
    from type_cards import registry as reg

    doc = json.loads(TABLE.read_text())
    assert doc["schema"] == "sysid.calibration_routines/1" and doc["levels"] == [level["id"] for level in RULER["levels"]]
    assert [r["routine"] for r in doc["rows"]] == [r.id for r in reg.ROUTINES]
    for row in doc["rows"]:
        assert all(k in row for k in TABLE_ROW_KEYS), (row["routine"], [k for k in TABLE_ROW_KEYS if k not in row])
        oracle = row["oracle"]
        assert oracle["status"] in ("checked", "not checked") and (oracle["status"] == "checked") == bool(oracle["checks"]), row["routine"]
        for c in oracle["checks"]:
            for level in ("1x", "3x"):
                cell = c["levels"].get(level)
                assert cell is None or {"pass", "worst_error_over_tolerance", "within_tolerance", "parameters", "missing"} <= set(cell), (row["routine"], level)
    assert doc["parameter_routines"] == reg.parameter_routines()
    text = (REPO / "type_cards" / "CONTRACT.md").read_text()
    assert "sysid.calibration_routines/1" in text and "calibration_routines.json" in text


# --- per parameter: per model, and both directions --------------------------------------------------------------------------------

def test_every_parameter_keeps_true_nominal_recovered_interval_error_and_tolerance_per_model():
    """The coordinator, 2026-11-07: for every parameter keep true, nominal, recovered (mean plus a 95 % interval), error and tolerance per
    model, so a site can show one recovered / error column group per model. The graded model's numbers are the row's own; every model's
    error is |mean - true| and its interval, where the routine makes one, an ordered pair."""
    for check, row in rows():
        for p in row["parameters"]:
            assert {"true", "nominal", "tolerance", "recovered", "ci95", "error", "card", "rung", "card_parameter", "unit", "models"} <= set(p), check["id"]
            graded = [m for m in p["models"] if m["graded"]]
            assert len(graded) <= 1 and (graded or p["recovered"] is None), (check["id"], row["level"], p["key"])
            if graded:
                g = graded[0]
                assert g["recovered"]["mean"] == p["recovered"] and g["recovered"]["ci95"] == p["ci95"] and g["error"] == p["error"], p["key"]
            for m in p["models"]:
                mean, ci = m["recovered"]["mean"], m["recovered"]["ci95"]
                assert m["recovered"]["interval"], (check["id"], p["key"], m["model"])
                if mean is not None:
                    assert m["error"] == pytest.approx(abs(mean - p["true"]), rel=1e-12, abs=1e-15), (check["id"], p["key"], m["model"])
                assert ci is None or (len(ci) == 2 and ci[0] <= ci[1]), (check["id"], p["key"], m["model"], ci)
    regression = next(c for c in committed()["checks"] if c["id"] == "pendulum_can11:servo.dynamics_regression")
    one_x = next(r for r in regression["rows"] if r["level"] == "1x" and r["variant"] is None)
    gravity = next(p for p in one_x["parameters"] if p["key"] == "can11.gravity_nm")
    assert [m["model"] for m in gravity["models"]] == ["M0", "M2", "M3", "M4"] and all(m["recovered"]["ci95"] for m in gravity["models"])


def test_parameter_to_routines_and_routine_to_parameters_agree():
    """Both directions (the coordinator, 2026-11-07): every graded parameter is placed on a card parameter, and the routines the table says
    can identify it are exactly type_cards' routines_identifying for that card parameter; the routine graded on it is one of them wherever
    the routine names that card parameter."""
    from type_cards import registry as reg

    doc = json.loads(TABLE.read_text())
    for entry in doc["parameters"]:
        assert all(k in entry for k in PARAMETER_KEYS), entry["key"]
        assert entry["card"] in reg.CARDS and entry["card_parameter"], (entry["example"], entry["key"])
        assert entry["routines"] == [r.id for r in reg.routines_identifying(entry["card"], entry["card_parameter"])], (entry["example"], entry["key"])
        for group in entry["models"]:
            routine = reg.routine(group["routine"])
            if routine.identifies_parameter(entry["card"], entry["card_parameter"]):
                assert group["routine"] in entry["routines"], (entry["key"], group["routine"])
            for level, cell in group["levels"].items():
                assert {"recovered", "error", "error_over_tolerance", "within_tolerance", "pass", "bound"} <= set(cell), (entry["key"], level)
    keys = {(e["example"], e["key"]) for e in doc["parameters"]}
    assert keys == {(c["example"], k) for c in committed()["checks"] for k in c["parameters"]}
