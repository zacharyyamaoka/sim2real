"""The model-independent metrics per run (tools/run_metrics.py), written before it (2026-11-07, the metrics lane).

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" --with pytest pytest -q /home/bam/sim2real/tools/tests/test_run_metrics.py

The brief: "Today almost every per-run dot is 'unknown' because no producer writes model-independent diagnostics per run. Write that
producer for the values computable from existing run data". The producer runs RobotDx's own catalog entries (io-diagnostics
robotdx.diagnostics: the ids type_cards' metrics name in `robotdx`) on each run's npz, loaded by RobotDx's rack adapter, the loader and the
dwell scan bam_rack_twin's T4 uses (stop_accuracy.py), so a stop here is T4's stop.

Held here: on synthetic runs worked by hand (dwells with known errors and a prelude that is no stop; a sine with none; fault codes with
the torque cap on a known share of rows), on the rack's real runs against a dwell scan written here from T4's definition (independent of
RobotDx's code), and the table's shape and its entries against type_cards' metrics.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(1, str(REPO))
import run_metrics as rm  # noqa: E402
from type_cards import domain as dm  # noqa: E402

RATE = 100.0


def write_run(folder: Path, name: str, *, t, q, q_target, qd_target, fault=None, mode=None, prelude_s=0.0, can_id=11, kind="waypoints"):
    folder.mkdir(parents=True, exist_ok=True)
    arrays = {"t": np.asarray(t, float), "q": np.asarray(q, float), "q_target": np.asarray(q_target, float),
              "qd_target": np.asarray(qd_target, float), "qd": np.zeros(len(t)), "tau": np.zeros(len(t))}
    if fault is not None:
        arrays["fault"] = np.asarray(fault, float)
    if mode is not None:
        arrays["mode"] = np.asarray(mode, float)
    np.savez(folder / f"{name}.npz", **arrays)
    (folder / f"{name}.json").write_text(json.dumps({"kind": kind, "can_id": can_id, "prelude_s": prelude_s, "args": {}}))
    return folder / f"{name}.npz"


def waypoints(errors_mrad, *, prelude_s=0.3, dwell_s=0.5, move_s=0.4):
    """A tape: a prelude settle at 0 (no stop: it is the runner's), then for each error a move and a dwell at a new target whose last
    50 ms sit `error` mrad off it, then a last move (so every dwell is followed by motion)."""
    t, q, qt, qdt = [], [], [], []
    now, target = 0.0, 0.0

    def hold(seconds, err):
        nonlocal now
        for _ in range(int(round(seconds * RATE))):
            t.append(now)
            q.append(target + err)
            qt.append(target)
            qdt.append(0.0)
            now += 1 / RATE

    def move(seconds):
        nonlocal now, target
        n = int(round(seconds * RATE))
        start = target
        for i in range(n):
            t.append(now)
            target = start + 0.2 * (i + 1) / n
            q.append(target)
            qt.append(target)
            qdt.append(0.5)
            now += 1 / RATE

    hold(prelude_s, 0.01)  # 10 mrad off during the prelude's settle: counted, it would be the p90
    for err in errors_mrad:
        move(move_s)
        hold(dwell_s, err / 1000.0)
    move(move_s)
    return t, q, qt, qdt


def test_a_stop_is_t4s_stop_and_the_value_is_their_p90(tmp_path):
    path = write_run(tmp_path / "runs", "s01_can11_waypoints", **dict(zip(("t", "q", "q_target", "qd_target"), waypoints([1.0, -2.0, 3.0]))),
                     prelude_s=0.3)
    row = rm.run_rows(path)
    stop = next(r for r in row if r["metric"] == "servo.stop_error")
    assert stop["value"] == pytest.approx(float(np.percentile([1.0, 2.0, 3.0], 90)), abs=1e-9)
    assert stop["n"] == 3 and stop["unit"] == "mrad" and stop["robotdx"] == "servo.stop_error" and stop["side"] == "encoder"


def test_a_run_with_no_dwell_has_no_stop_error_and_says_why(tmp_path):
    t = np.arange(0, 4, 1 / RATE)
    target = 0.3 * np.sin(2 * np.pi * 0.5 * t)
    path = write_run(tmp_path / "runs", "s02_can11_sine", t=t, q=target + 0.001, q_target=target, qd_target=np.gradient(target, t), kind="sine")
    stop = next(r for r in rm.run_rows(path) if r["metric"] == "servo.stop_error")
    assert stop["value"] is None and stop["n"] == 0 and "dwell" in stop["why"]


def test_the_saturation_is_the_share_of_rows_on_the_torque_cap(tmp_path):
    t = np.arange(0, 1, 1 / RATE)
    fault = np.zeros(t.size)
    fault[10:15] = 102     # the torque cap: 5 of 100 rows
    fault[40:43] = 104     # flux braking, another limiter: not the torque cap
    path = write_run(tmp_path / "runs", "s03_can11_waypoints", t=t, q=np.zeros(t.size), q_target=np.zeros(t.size), qd_target=np.zeros(t.size),
                     fault=fault, mode=np.full(t.size, 10))
    sat = next(r for r in rm.run_rows(path) if r["metric"] == "driver.saturation")
    assert sat["value"] == pytest.approx(5.0) and sat["unit"] == "%" and sat["n"] == 100 and sat["robotdx"] == "driver.saturation"
    none = write_run(tmp_path / "runs", "s04_can11_waypoints", t=t, q=np.zeros(t.size), q_target=np.zeros(t.size), qd_target=np.zeros(t.size))
    sat = next(r for r in rm.run_rows(none) if r["metric"] == "driver.saturation")
    assert sat["value"] is None and "fault" in sat["why"]


def test_the_table_is_every_run_times_every_entry(tmp_path):
    a = write_run(tmp_path / "arch" / "runs", "s01_can11_waypoints", **dict(zip(("t", "q", "q_target", "qd_target"), waypoints([1.0, 2.0]))),
                  fault=None)
    dep = tmp_path / "data" / "rig"
    dep.mkdir(parents=True)
    (dep / "runs.json").write_text(json.dumps({"rows": [{"run": "r1", "device": "CAN 11", "npz": str(a)},
                                                        {"run": "r2", "device": "CAN 11", "npz": str(tmp_path / "missing.npz")}]}))
    counts = rm.write_all(tmp_path / "data")
    doc = json.loads((dep / "run_metrics.json").read_text())
    assert counts == {"rig": 4} and doc["name"] == "run_metrics" and {f["name"] for f in doc["schema"]["fields"]} >= {"run", "metric", "value"}
    rows = {(r["run"], r["metric"]): r for r in doc["rows"]}
    assert set(rows) == {(run, m) for run in ("r1", "r2") for m in ("servo.stop_error", "driver.saturation")}
    assert rows[("r1", "servo.stop_error")]["device"] == "CAN 11" and rows[("r2", "servo.stop_error")]["value"] is None
    assert "npz" in rows[("r2", "servo.stop_error")]["why"]
    json.dumps(doc, allow_nan=False)


def test_the_entries_are_type_cards_metrics_and_robotdx_ids():
    want = {(t.id, m.id) for t in dm.TYPES.values() for m in t.metrics if m.per_run is not None and m.per_run.table == "run_metrics"}
    got = {(e.type, e.metric) for e in rm.ENTRIES}
    assert got == want, "every metric type_cards reads from run_metrics has a producer entry, and back"
    for e in rm.ENTRIES:
        assert dm.metric(e.type, e.metric).robotdx == e.robotdx, e.metric


# --- on the rack's own runs: RobotDx's dwell scan against one written here from T4's words -------------------------------------------

RUNS = Path("/home/bam/sim2real/app/data/one-dof-test-rack/runs.json")


def t4_stops_mrad(path: Path) -> list[float]:
    """T4's definition (bam_rack_twin stop_accuracy.py, docstring): "a dwell is a stretch of zero commanded velocity at one constant target
    lasting >= 0.25 s and followed by more motion; its stop error is mean(q - q_target) over the dwell's last 50 ms", the prelude to the
    origin dropped (the runner's meta prelude_s). Written here from those words, not from RobotDx's code."""
    meta = json.loads(path.with_suffix(".json").read_text())
    with np.load(path) as a:
        t, q, qt, qdt = (np.asarray(a[k], float) for k in ("t", "q", "q_target", "qd_target"))
    keep = (t - t[0]) >= float(meta.get("prelude_s") or 0.0)
    t, q, qt, qdt = t[keep], q[keep], qt[keep], qdt[keep]
    out, i = [], 0
    while i < len(t):
        if abs(qdt[i]) >= 1e-9:
            i += 1
            continue
        j = i
        while j + 1 < len(t) and abs(qdt[j + 1]) < 1e-9 and abs(qt[j + 1] - qt[i]) < 1e-9:
            j += 1
        if t[j] - t[i] >= 0.25 and j + 1 < len(t):
            w = (t >= t[j] - 0.05) & (t <= t[j])
            out.append(1e3 * float(np.mean(q[w] - qt[w])))
        i = j + 1
    return out


@pytest.mark.skipif(not RUNS.is_file(), reason="the app's data is not built (tools/build_app.py)")
def test_on_the_rack_the_stop_error_is_t4s_and_the_saturation_the_boards_own_codes():
    rows = json.loads(RUNS.read_text())["rows"]
    picked = [r for r in rows if r["kind"] == "waypoints" and Path(r["npz"]).is_file()][:: max(1, len(rows) // 40)][:6]
    assert picked
    for r in picked:
        stops = t4_stops_mrad(Path(r["npz"]))
        got = next(x for x in rm.run_rows(Path(r["npz"])) if x["metric"] == "servo.stop_error")
        if stops:
            assert got["value"] == pytest.approx(float(np.percentile(np.abs(stops), 90)), rel=1e-9, abs=1e-9) and got["n"] == len(stops), r["run"]
        else:
            assert got["value"] is None, r["run"]
    capped = [r for r in rows if Path(r["npz"]).is_file()][:400]
    seen = 0
    for r in capped:
        with np.load(r["npz"]) as a:
            if "fault" not in a.files:
                continue
            share = 100.0 * float(np.mean(np.asarray(a["fault"]).astype(int) == 102))
        got = next(x for x in rm.run_rows(Path(r["npz"])) if x["metric"] == "driver.saturation")
        assert got["value"] == pytest.approx(share, abs=1e-12), r["run"]
        seen += 1
    assert seen > 100
