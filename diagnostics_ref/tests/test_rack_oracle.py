"""The oracle: the stock diagnostics, run on the real rack runs (rack_2026-10-24/25), reproduce bam_rack_twin's own
published numbers for the same runs. bam_rack_twin is a separate implementation (branch
claude/sim-to-real-motor-models-f1ee43); its outputs are read from the archive's analysis files, never recomputed here.
Skipped when the archive is not mounted."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from robotdx.diagnostics import FAIL, NOT_RUN, PASS, WARN, Limits, evaluate
from robotdx.diagnostics.adapters.rack_npz import load
from robotdx.diagnostics.stock import (BoxConfig, CoverageConfig, FaultCodesConfig, FidelityRatioConfig, FloorConfig,
                                       KnownLoadConfig, KtConsistencyConfig, RateConfig, StopErrorConfig, TrackingErrorConfig)
from robotdx.diagnostics.stock.fidelity import FidelityInput, ModelRow
from robotdx.diagnostics.stock.health import MOTEUS_CODES, Stamps
from robotdx.diagnostics.stock.truthfulness import KnownLoadInput, KtReadings

from conftest import RACK, needs_rack

pytestmark = needs_rack
DAY = RACK / "rack_2026-10-24"
A23, A24, A25 = RACK / "rack_2026-10-23" / "analysis", DAY / "analysis", RACK / "rack_2026-10-25" / "analysis"
EXACT = 1e-9  # same arithmetic, same runs: the numbers agree to float rounding
STOP_ALLOCATION_MRAD = {11: 3.6, 12: 3.6, 13: 3.6, 4: 6.7, 21: 6.7, 1: 10.0, 14: 10.0, 15: 10.0}  # acceptance.py, "Zach to confirm"


def _json(path: Path):
    return json.loads(path.read_text())


@lru_cache(maxsize=None)
def _runs(folder: str, pattern: str) -> tuple:
    return tuple(load(path) for path in sorted(Path(folder).glob(pattern)))


def test_floor_t1_matches_floors_json_for_all_eight_motors():
    for can, published in _json(A24 / "floors.json").items():
        runs = _runs(str(Path(published["session"]) / "runs"), f"*_can{can}_*.npz")
        q = evaluate("stock.repeatability_floor", FloorConfig(), list(runs), subject=f"rack/can{can}")
        tau = evaluate("stock.repeatability_floor", FloorConfig(channel="tau_nm", relative_to_target=False, scale=1.0, unit="N.m"),
                       list(runs), subject=f"rack/can{can}")
        assert q.value == pytest.approx(published["floor_mrad"], abs=EXACT), can
        assert tau.value == pytest.approx(published["tau_floor_nm"], abs=EXACT), can
        assert q.verdict == PASS and {m.key: m.value for m in q.measurements}["repeats"] == published["repeats"] == 5


def test_the_floor_ruler_can_fail():
    # a different clock step is a different ruler: the oracle must notice (mutation check)
    published = _json(A24 / "floors.json")["14"]
    runs = _runs(str(Path(published["session"]) / "runs"), "*_can14_*.npz")
    coarse = evaluate("stock.repeatability_floor", FloorConfig(dt=0.01), list(runs), subject="rack/can14")
    assert abs(coarse.value - published["floor_mrad"]) > 1e-4


def test_stop_error_t4_matches_stop_accuracy_json():
    for can, published in _json(A24 / "stop_accuracy.json").items():
        runs = _runs(str(DAY / "dataset" / f"can{can}" / "runs"), "*waypoints*.npz")
        out = evaluate("stock.stop_error", StopErrorConfig(limits=Limits.at_most(STOP_ALLOCATION_MRAD[int(can)])), list(runs), subject=f"rack/can{can}")
        got = {m.key: m.value for m in out.measurements}
        assert out.value == pytest.approx(published["p90_mrad"], abs=EXACT), can
        assert (got["n"], got["runs"]) == (published["n"], published["runs"])
        assert got["median"] == pytest.approx(published["median_mrad"], abs=EXACT)
        assert got["mean_signed"] == pytest.approx(published["mean_signed_mrad"], abs=EXACT)


def _ff_groups(can: str, coulomb: float) -> dict[float, list]:
    groups: dict[float, list] = {}
    for folder in (DAY / "floors" / f"can{can}", DAY / "ff" / f"can{can}"):
        for run in _runs(str(folder / "runs"), f"*_can{can}_waypoints.npz"):
            ff = run.labels["ff_coulomb_nm"]
            groups.setdefault(round(ff / coulomb, 2) if ff else 0.0, []).append(run)
    return groups


def test_tracking_and_stop_error_match_the_feed_forward_study_per_fraction():
    for can, study in _json(A24 / "ff_study.json").items():
        for fraction, runs in _ff_groups(can, study["coulomb_nm"]).items():
            published = study["fractions"][str(fraction)]
            tracking = evaluate("stock.tracking_error", TrackingErrorConfig(), runs, subject=f"rack/can{can}")
            stop = evaluate("stock.stop_error", StopErrorConfig(), runs, subject=f"rack/can{can}")
            assert tracking.value == pytest.approx(published["tracking_rms_mrad"], abs=EXACT), (can, fraction)
            assert stop.value == pytest.approx(published["p90_mrad"], abs=EXACT), (can, fraction)


def _index_classes(can: str) -> dict[str, str]:
    index = _json(DAY / "plans" / "dataset" / "index.json")
    return {f"s{row['step']:02d}": row["class"] for row in index["runs"] if str(row["can_id"]) == can}


def _twin_rows(can: str) -> tuple[list[ModelRow], dict]:
    newer = A25 / f"dataset_twin_can{can}.json"
    dataset = _json(newer if newer.is_file() else A24 / f"dataset_twin_can{can}.json")
    label = {} if newer.is_file() else _index_classes(can)
    rows = []
    for row in dataset["rows"]:
        twin = row["twin_q_rms_mrad"]
        cls = row.get("class") or label.get(Path(row["run"]).name.split("_")[0], "?")
        rows.append(ModelRow("twin", row["run"], cls, twin.get("full + drive limits", twin["full"])))
    return rows, dataset


def test_fidelity_ratio_t2_matches_acceptance_per_class_and_verdict():
    stations = _json(A24 / "acceptance.json")["stations"]
    floors = _json(A24 / "floors.json")
    for can, station in stations.items():
        rows, _ = _twin_rows(can)
        floor = floors[can]
        out = evaluate("stock.fidelity_ratio", FidelityRatioConfig(), FidelityInput(floor["floor_mrad"], rows, "repeats", floor["class"]),
                       subject=f"rack/can{can}")
        mine = dict(zip(out.payload["x"], out.payload["y"]))
        for cls, published in station["facts"]["class_ratio"].items():
            assert round(mine[cls], 3) == published, (can, cls)
        gate = next(g for g in station["gates"] if g["id"] == "T2")
        assert round(out.value, 3) == pytest.approx(gate["value"], abs=1e-3), can
        assert {"fail": FAIL, "pass": PASS, "partial": WARN}[gate["status"]] == out.verdict, can


def test_real_tracking_rms_matches_the_dataset_rows():
    for can in ("14", "15", "1", "4"):  # the motors whose dataset rows were scored on the rack_2026-10-24 runs themselves
        _, dataset = _twin_rows(can)
        for row in dataset["rows"]:
            run = load(DAY / (row["run"] + ".npz"))
            out = evaluate("stock.tracking_error", TrackingErrorConfig(controlled_only=True), [run], subject=f"rack/can{can}")
            assert out.value == pytest.approx(row["error_rms_mrad"], abs=EXACT), row["run"]


def test_torque_fidelity_t3_matches_twin_torque_json():
    floors, stations = _json(A24 / "floors.json"), _json(A24 / "acceptance.json")["stations"]
    for can, twin in _json(A25 / "twin_torque.json").items():
        rows = [ModelRow("twin", run["run"], "pickplace", run["tau_rms_nm"]) for run in twin["runs"]]
        out = evaluate("stock.fidelity_ratio", FidelityRatioConfig(center="median", class_limit=None, limits=Limits.at_most(2.0)),
                       FidelityInput(floors[can]["tau_floor_nm"], rows, "repeats", "pickplace", unit="N.m"), subject=f"rack/can{can}")
        assert out.value == pytest.approx(stations[can]["facts"]["torque_ratio"], abs=EXACT), can


def test_known_load_is_not_run_on_every_motor_as_t6_is():
    stations = _json(A24 / "acceptance.json")["stations"]
    for can, station in stations.items():
        out = evaluate("stock.known_load_gain", KnownLoadConfig(), KnownLoadInput([]), subject=f"rack/can{can}")
        gate = next(g for g in station["gates"] if g["id"] == "T6")
        assert (out.verdict, gate["status"]) == (NOT_RUN, "not_run")


def test_kt_consistency_reproduces_the_can14_kv_artifact():
    published = _json(A23 / "kt_can14.json")
    out = evaluate("stock.kt_consistency", KtConsistencyConfig(),
                   KtReadings(published["board_reported"]["kv_rotor_rpm_v"], published["corrected"]["kv_rotor_rpm_v"]), subject="rack/can14")
    assert {m.key: m.value for m in out.measurements}["kv_board_over_reference"] == pytest.approx(published["kt_ratio"], abs=5e-4)
    assert out.verdict == FAIL


def test_health_checks_match_the_envelope_rungs():
    rows = _json(A24 / "envelope_rungs.json")["rows"]
    checked = 0
    for row in rows:
        run = load(row["run"])
        faults = evaluate("stock.fault_codes", FaultCodesConfig(), [run], subject="s")
        shares = {MOTEUS_CODES[int(m.key.split("_")[1])]: round(m.value, 4) for m in faults.measurements if m.key.startswith("limiter_")}
        assert shares == row["limiters"], row["run"]
        rate = evaluate("stock.sample_rate", RateConfig(expected_hz=100.0), [Stamps(run.t, row["run"])], subject="s")
        assert rate.value == pytest.approx(row["row_rate_hz"], abs=EXACT)
        assert evaluate("stock.box", BoxConfig(), [run], subject="s").value == pytest.approx(row["temp_max_c"], abs=EXACT)
        assert evaluate("stock.box", BoxConfig(channel="v_bus_v", unit="V", headline="min"), [run], subject="s").value == pytest.approx(row["voltage_min_v"], abs=EXACT)
        tracking = evaluate("stock.tracking_error", TrackingErrorConfig(controlled_only=True), [run], subject="s")
        assert tracking.value == pytest.approx(row["error_rms_mrad"], abs=EXACT)
        if "hardstop" not in row["run"]:  # hard-stop runs log rows with no target; bam_rack_twin drops those from its speed peak
            cover = evaluate("stock.coverage", CoverageConfig(), [run], subject="s")
            assert {m.key: m.value for m in cover.measurements}["qd_rad_s_abs_max"] == pytest.approx(row["speed_peak_rad_s"], abs=EXACT)
        checked += 1
    assert checked == len(rows) == 75
