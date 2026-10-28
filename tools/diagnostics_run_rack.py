"""Run the stock diagnostics on the real 1-DOF rack (rack_2026-10-24/25) and write what the report and data-ui read.

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/diagnostics_run_rack.py

The library is robotdx.diagnostics in io-diagnostics (lifted from this repo's diagnostics_ref at 1f0eb75, on io-diagnostics main
8c89965); this script stays here because it is sim2real's producer of the report's data.

Writes, under reports/media/diagnostics-catalog-2026-10-28/data/:
- results.json      every Result as a diagnostics-record/0 status line (RobotDx's record, lossless)
- diagnostics.json  the same Results as data-ui PEP 0010 §10 rows (subject, diagnostic, verdict, rank, ... parent, hint)
- gates.json        the rack's gate matrix (stations x T1, T2, T3, T4, T6)
- oracle.json       every number this library computes beside bam_rack_twin's published number for the same runs
- stream.json       the RobotDx consumer: one run evaluated in 1 s windows
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from robotdx.diagnostics import Limits, evaluate
from robotdx.diagnostics.adapters.rack_npz import camera_stamps, load
from robotdx.diagnostics.record import to_record
from robotdx.diagnostics.rollup import GateMatrixConfig, RollupConfig
from robotdx.diagnostics.rows import result_row
from robotdx.diagnostics.stock import (BoxConfig, CoverageConfig, FaultCodesConfig, FidelityRatioConfig, FloorConfig,
                                       KnownLoadConfig, KtConsistencyConfig, ModelErrorConfig, RateConfig, StopErrorConfig,
                                       TrackingErrorConfig)
from robotdx.diagnostics.stock.fidelity import FidelityInput, ModelRow, rows_of
from robotdx.diagnostics.stock.health import Stamps
from robotdx.diagnostics.stock.truthfulness import KnownLoadInput, KtReadings
from robotdx.diagnostics.stream import monitor

RACK = Path("/archive/datasets/bam_rig")
DAY = RACK / "rack_2026-10-24"
A23, A24, A25 = RACK / "rack_2026-10-23" / "analysis", DAY / "analysis", RACK / "rack_2026-10-25" / "analysis"
OUT = Path("/home/bam/sim2real/reports/media/diagnostics-catalog-2026-10-28/data")
DEPLOYMENT = "one-dof-rack"
# bam_rack_twin acceptance.py STOP_ALLOCATION_MRAD: each joint's share of the 5 mm tool gate (agent default, "Zach to confirm")
ALLOCATION = {11: 3.6, 12: 3.6, 13: 3.6, 4: 6.7, 21: 6.7, 1: 10.0, 14: 10.0, 15: 10.0}
ROLE = {11: "shoulder, JMC 10:1", 12: "shoulder, JMC 10:1", 13: "shoulder, JMC 10:1", 4: "elbow, direct drive", 21: "elbow, direct drive",
        1: "wrist class", 14: "wrist class, GIM4305", 15: "wrist class, ~10:1"}
ORDER = (11, 12, 13, 4, 21, 1, 14, 15)
BOARD_TEMP = BoxConfig(channel="temp_c", unit="Cel", max=Limits.at_most(70.0, warn=60.0),
                       mean=Limits(error_low=5.0, warn_low=10.0, warn_high=55.0, error_high=65.0))  # his bam_diagnostics numbers


def _json(path: Path):
    return json.loads(path.read_text())


def subject(can: int) -> str:
    return f"{DEPLOYMENT}/CAN {can}"


def dataset_runs(can: int, classes: dict[str, str]) -> list:
    return [load(path, labels={"class": classes.get(path.name.split("_")[0], "?")})
            for path in sorted((DAY / "dataset" / f"can{can}" / "runs").glob("*.npz"))]


def twin_rows(can: int, classes: dict[str, str]) -> tuple[list[ModelRow], list]:
    """The twin's per-run error, read from bam_rack_twin's file (basis: derived), and the real runs it was scored on."""

    newer = A25 / f"dataset_twin_can{can}.json"
    dataset = _json(newer if newer.is_file() else A24 / f"dataset_twin_can{can}.json")
    rows, runs = [], []
    for row in dataset["rows"]:
        twin = row["twin_q_rms_mrad"]
        path = Path(row["run"]) if row["run"].startswith("/") else DAY / row["run"]
        path = path if path.suffix == ".npz" else path.with_suffix(".npz")
        cls = row.get("class") or classes.get(path.name.split("_")[0], "?")
        rows.append(ModelRow("twin", str(path), cls, twin.get("full + drive limits", twin["full"])))
        runs.append(load(path, labels={"class": cls}))
    return rows, runs


def ff_best(can: int, study: dict) -> tuple[float, list]:
    groups: dict[float, list] = {}
    for folder in (DAY / "floors" / f"can{can}", DAY / "ff" / f"can{can}"):
        for path in sorted((folder / "runs").glob(f"*_can{can}_waypoints.npz")):
            run = load(path)
            ff = run.labels["ff_coulomb_nm"]
            groups.setdefault(round(ff / study["coulomb_nm"], 2) if ff else 0.0, []).append(run)
    return study["best_fraction"], groups


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    index = _json(DAY / "plans" / "dataset" / "index.json")
    floors, stops_pub, ff_pub = _json(A24 / "floors.json"), _json(A24 / "stop_accuracy.json"), _json(A24 / "ff_study.json")
    stations, torque_pub = _json(A24 / "acceptance.json")["stations"], _json(A25 / "twin_torque.json")
    results, rows, oracle, cells = [], [], [], []
    started = time.perf_counter()

    def add(result, parent):
        results.append(result)
        rows.append(result_row(result, parent=parent))
        return result

    for can in ORDER:
        s, key = subject(can), str(can)
        classes = {f"s{row['step']:02d}": row["class"] for row in index["runs"] if row["can_id"] == can}
        floor_runs = [load(p) for p in sorted((Path(floors[key]["session"]) / "runs").glob(f"*_can{can}_*.npz"))]
        stamp = floor_runs[0].labels.get("wall_start")
        data_runs = dataset_runs(can, classes)

        # T1: the floor, on q and on tau
        floor = add(evaluate("stock.repeatability_floor", FloorConfig(), floor_runs, subject=s, stamp=stamp), s)
        tau_floor = add(evaluate("stock.repeatability_floor", FloorConfig(channel="tau_nm", relative_to_target=False, scale=1.0, unit="N.m"),
                                 floor_runs, subject=s, stamp=stamp), s)
        oracle += [("T1 floor q", can, floor.value, floors[key]["floor_mrad"], "mrad", "floors.json"),
                   ("T1 floor tau", can, tau_floor.value, floors[key]["tau_floor_nm"], "N.m", "floors.json")]

        # real vs target on the dataset (plain PD), and the stop error
        tracking = add(evaluate("stock.tracking_error", TrackingErrorConfig(controlled_only=True), data_runs, subject=s, stamp=stamp), s)
        stop_pd = evaluate("stock.stop_error", StopErrorConfig(limits=Limits.at_most(ALLOCATION[can])), [r for r in data_runs if "waypoints" in r.run],
                           subject=s, stamp=stamp)
        oracle.append(("T4 stop p90, plain PD", can, stop_pd.value, stops_pub[key]["p90_mrad"], "mrad", "stop_accuracy.json"))

        # T4 on the best controller the rack actually ran (the Coulomb feed-forward study), else plain PD
        best, groups = ff_best(can, ff_pub[key])
        for fraction, runs in groups.items():
            got_t = evaluate("stock.tracking_error", TrackingErrorConfig(), runs, subject=s).value
            got_s = evaluate("stock.stop_error", StopErrorConfig(), runs, subject=s).value
            oracle += [(f"ff {fraction:g} tracking RMS", can, got_t, ff_pub[key]["fractions"][str(fraction)]["tracking_rms_mrad"], "mrad", "ff_study.json"),
                       (f"ff {fraction:g} stop p90", can, got_s, ff_pub[key]["fractions"][str(fraction)]["p90_mrad"], "mrad", "ff_study.json")]
        if ff_pub[key]["improves"]:
            stop = evaluate("stock.stop_error", StopErrorConfig(limits=Limits.at_most(ALLOCATION[can])), groups[best], subject=s, stamp=stamp)
            stop = replace(stop, message=stop.message + f" (Coulomb feed-forward {best:g} x tau_c)")
        else:
            stop = stop_pd
        add(stop, s)

        # T2: twin / floor per class, beside a perfect-servo baseline (the target as a model) on the same runs
        rows_twin, scored_runs = twin_rows(can, classes)
        perfect = evaluate("stock.model_error", ModelErrorConfig(), [(r, r.as_situation(r.q_target_rad, "perfect servo", "target")) for r in scored_runs],
                           subject=s)
        fidelity_in = FidelityInput(floors[key]["floor_mrad"], rows_twin + rows_of(perfect), "repeats", floors[key]["class"])
        fidelity = evaluate("stock.fidelity_ratio", FidelityRatioConfig(), fidelity_in, subject=s, stamp=stamp)
        fidelity = replace(fidelity, basis="derived")
        add(fidelity, s)
        gate = next(g for g in stations[key]["gates"] if g["id"] == "T2")
        oracle.append(("T2 twin / floor", can, fidelity.value, gate["value"], "x", "acceptance.json"))

        # T3: twin torque / tau floor
        torque_rows = [ModelRow("twin", run["run"], "pickplace", run["tau_rms_nm"]) for run in torque_pub[key]["runs"]]
        torque = evaluate("stock.fidelity_ratio", FidelityRatioConfig(center="median", class_limit=None, limits=Limits.at_most(2.0)),
                          FidelityInput(tau_floor.value, torque_rows, "repeats", "pickplace", unit="N.m"), subject=s, stamp=stamp)
        torque = replace(torque, title="torque fidelity (twin / floor)", basis="derived")
        add(torque, s)
        oracle.append(("T3 twin torque / floor", can, torque.value, stations[key]["facts"]["torque_ratio"], "x", "acceptance.json"))

        # T6: no weighed load on any joint
        drive = add(evaluate("stock.known_load_gain", KnownLoadConfig(), KnownLoadInput([]), subject=s, stamp=stamp), s)

        # health over the dataset
        add(evaluate("stock.box", BOARD_TEMP, data_runs, subject=s, stamp=stamp), s)
        nominal = 36.0 if np.nanmedian(data_runs[0].v_bus_v) > 30 else 24.0
        add(evaluate("stock.box", BoxConfig(channel="v_bus_v", unit="V", headline="min",
                                            min=Limits.at_least(0.85 * nominal, warn=0.9 * nominal), max=Limits.at_most(1.15 * nominal, warn=1.1 * nominal)),
                     data_runs, subject=s, stamp=stamp), s)
        add(evaluate("stock.sample_rate", RateConfig(expected_hz=100.0), [Stamps(r.t, r.run) for r in data_runs], subject=s, stamp=stamp), s)
        add(evaluate("stock.fault_codes", FaultCodesConfig(), data_runs, subject=s, stamp=stamp), s)
        q_all = np.concatenate([r.q_target_rad for r in data_runs])
        qd_all = np.concatenate([r.qd_target_rad_s for r in data_runs])
        span = float(np.nanmax(np.abs(qd_all))) * 1.05
        add(evaluate("stock.coverage", CoverageConfig(x_range=(float(np.nanmin(q_all)), float(np.nanmax(q_all))), y_range=(-span, span), bins=(16, 16)),
                     data_runs, subject=s, stamp=stamp), s)

        for gate_id, result in (("T1 floor", floor), ("T2 fidelity", fidelity), ("T3 torque", torque), ("T4 stop", stop), ("T6 drive gain", drive)):
            cells.append((f"CAN {can}", gate_id, result))
        mine = [r for r in results if r.subject == s]
        add(evaluate("stock.rollup", RollupConfig(title=f"CAN {can} station"), mine, subject=s, stamp=stamp), DEPLOYMENT)

    # CAN 14's Kt artifact (board Kv vs a measure-only calibration)
    kt = _json(A23 / "kt_can14.json")
    kt_result = add(evaluate("stock.kt_consistency", KtConsistencyConfig(),
                             KtReadings(kt["board_reported"]["kv_rotor_rpm_v"], kt["corrected"]["kv_rotor_rpm_v"], str(A23 / "kt_can14.json")),
                             subject=subject(14) + " (before 2026-10-23)"), DEPLOYMENT)
    oracle.append(("Kt: board Kv / measured Kv", 14, 1 / kt_result.value, kt["kt_ratio"], "x", "kt_can14.json"))

    # the two D405s on the floor sessions: frame rate from the hardware clock
    cameras = sorted((DAY / "floors").glob("can*/cameras/cam_*.npz"))
    camera_results = {}
    for serial in sorted({p.stem.split("_")[1] for p in cameras}):
        streams = [camera_stamps(p) for p in cameras if serial in p.name]
        camera_results[serial] = add(evaluate("stock.sample_rate", RateConfig(expected_hz=30.0, stamps_scale=1e-3), streams,
                                              subject=f"{DEPLOYMENT}/D405 {serial}"), DEPLOYMENT)

    station_rollups = [r for r in results if r.diagnostic == "stock.rollup"]
    rack = add(evaluate("stock.rollup", RollupConfig(title="1-DOF rack", tolerate_fail=0), station_rollups + list(camera_results.values()),
                        subject=DEPLOYMENT), "")
    matrix = evaluate("stock.gate_matrix", GateMatrixConfig(title="rack gates", gates=("T1 floor", "T2 fidelity", "T3 torque", "T4 stop", "T6 drive gain"),
                                                            subjects=tuple(f"CAN {c}" for c in ORDER)), cells, subject=DEPLOYMENT)
    add(matrix, "")
    acceptance_t = {("CAN " + k, g["id"]): g["status"] for k, st in stations.items() for g in st["gates"]}
    gate_rows = []
    for (who, gate_id, result) in cells:
        gate_rows.append({"subject": who, "gate": gate_id, "verdict": result.verdict, "value": result.value, "unit": result.unit,
                          "code": result.code, "message": result.message, "acceptance": acceptance_t.get((who, gate_id.split()[0]))})

    # the RobotDx consumer: one CAN 12 dataset run as a live stream, 1 s windows
    run12 = dataset_runs(12, {})[0]
    stream = monitor("stock.box", BOARD_TEMP, run12, subject=subject(12), window_s=1.0, step_s=0.5, wall_start=run12.labels.get("wall_start"))
    stream_rows = [{"t": r.stamp, "verdict": r.verdict, "value": r.value, "record_level": rec["level"], "expected_period_s": rec["expected_period_s"]}
                   for r, rec in stream]
    tracking_stream = monitor("stock.tracking_error", TrackingErrorConfig(controlled_only=True, limits=Limits.at_most(40.0, warn=30.0)), run12,
                              subject=subject(12), window_s=1.0, step_s=0.25, wall_start=run12.labels.get("wall_start"))
    stream_rows_tracking = [{"t": r.stamp, "verdict": r.verdict, "value": r.value} for r, _ in tracking_stream]

    elapsed = time.perf_counter() - started
    (OUT / "results.json").write_text("\n".join(json.dumps(to_record(r)) for r in results) + "\n")
    (OUT / "diagnostics.json").write_text(json.dumps(rows, indent=1))
    (OUT / "gates.json").write_text(json.dumps({"matrix": result_row(matrix), "payload": matrix.payload, "cells": gate_rows}, indent=1))
    (OUT / "oracle.json").write_text(json.dumps([{"check": c, "can": n, "ours": o, "bam_rack_twin": b, "unit": u, "file": f,
                                                   "abs_diff": None if o is None or b is None else abs(o - b)} for c, n, o, b, u, f in oracle], indent=1))
    (OUT / "stream.json").write_text(json.dumps({"run": run12.run, "box": stream_rows, "tracking": stream_rows_tracking}, indent=1))
    (OUT / "payloads.json").write_text(json.dumps({f"{r.subject}|{r.diagnostic}|{r.title}": {"payload": r.payload, "limits": vars(r.limits),
                                                                                              "value": r.value, "verdict": r.verdict, "unit": r.unit}
                                                    for r in results if r.payload}, indent=None))
    worst = max((row["abs_diff"] for row in json.loads((OUT / "oracle.json").read_text()) if row["abs_diff"] is not None), default=None)
    print(f"{len(results)} results, {len(oracle)} oracle comparisons (worst |diff| {worst:.3g}), rack {rack.verdict} ({rack.message}); "
          f"gates {matrix.message}; {elapsed:.1f} s -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
