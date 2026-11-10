"""A recorded run as robot_msgs' JointTrajectory (tools/run_files.py), written before it (2026-11-10, the robot_msgs migration).

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" --with-editable /home/bam/robot_msgs --with pytest pytest -q /home/bam/sim2real/tools/tests/test_run_files.py

Zach (2026-11-10, relayed by the robot_msgs maintainer): "migrate its work to use this robot_msgs package"; every package depends on
robot_msgs. The run files on disk do not change: bam_rack_twin.hardware still writes <name>.npz + <name>.json, and sim2real reads every
one of them (10-23 onward) as a JointTrajectory at the one door, tools/run_files.py. Held here:
- a real run recorded before the migration (10-23, no joint_trajectory/ file beside it) loads, and every column comes back bit for bit
  (t as recorded, q / qd / tau as positions / velocities / effort, every other column a channel), through save_npz / to_dict too;
- a run that logged no qd or tau (the 10-24 thermal runs) has no velocities or effort, never zeros;
- since 2026-11-04 the producer writes its own JointTrajectory of each run (bam_rack_twin.msgs, runs/joint_trajectory/<name>.npz): the
  message read here equals the producer's file, header and meta included (the producer is the oracle, not this repo's code);
- a repeated stamp goes through from_samples(duplicate_times="drop_later"), the producer's policy, and says so in header.meta;
- tools/build_app.py's load_run returns the trajectory, so every page the app builds reads the run through it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from robot_msgs import load_npz, save_npz
from robot_msgs.trajectory import JointTrajectory

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import run_files  # noqa: E402

OLD_RUN = Path("/archive/datasets/bam_rig/rack_2026-10-23/session_01a/runs/s01_can14_staircase.npz")
NO_SPEED_RUN = Path("/archive/datasets/bam_rig/rack_2026-10-24/thermal/can12_thermal.npz")
PRODUCER_DAY = Path("/archive/datasets/bam_rig/rack_2026-11-05")


def columns(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as archive:
        return {name: np.asarray(archive[name]) for name in archive.files}


def same(a, b) -> bool:
    """Bit for bit: dtype, shape and bytes."""
    a, b = np.asarray(a), np.asarray(b)
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


def write_run(folder: Path, name: str, arrays: dict, *, can_id=11) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    np.savez(folder / f"{name}.npz", **{k: np.asarray(v, float) for k, v in arrays.items()})
    (folder / f"{name}.json").write_text(json.dumps({"kind": "waypoints", "can_id": can_id, "args": {}}))
    return folder / f"{name}.npz"


@pytest.mark.skipif(not OLD_RUN.is_file(), reason="the rack archive is not on this machine")
def test_a_run_recorded_before_the_migration_loads_as_a_joint_trajectory_bit_for_bit(tmp_path):
    assert not run_files.producer_path(OLD_RUN).is_file(), "the 10-23 run predates the producer's own joint_trajectory/ file"
    raw = columns(OLD_RUN)
    loaded = run_files.load_run(OLD_RUN)
    assert loaded is not None
    meta, traj = loaded
    assert meta == json.loads(OLD_RUN.with_suffix(".json").read_text())
    assert isinstance(traj, JointTrajectory)
    assert traj.joint_names == ("can14",) and traj.header.frame_id == "board"
    assert traj.header.meta["can_id"] == "14" and traj.header.meta["units"] == run_files.RUN_UNITS
    assert traj.header.stamp == float(raw["wall"][0] - raw["t"][0])
    assert same(traj.t, raw["t"])
    assert same(traj.positions[:, 0], raw["q"]) and same(traj.velocities[:, 0], raw["qd"]) and same(traj.effort[:, 0], raw["tau"])
    assert set(traj.channels) == set(raw) - {"t", "q", "qd", "tau"}
    for name, values in raw.items():
        assert same(run_files.column(traj, name), values), name  # every column back by its recorded name
    assert run_files.column(traj, "no_such_column") is None
    # the round trip through robot_msgs' own files: npz and the JSON dict
    save_npz(traj, tmp_path / "run.npz")
    again = load_npz(tmp_path / "run.npz")
    assert again == traj and all(same(run_files.column(again, n), v) for n, v in raw.items())
    assert JointTrajectory.from_dict(json.loads(json.dumps(traj.to_dict()))) == traj


@pytest.mark.skipif(not NO_SPEED_RUN.is_file(), reason="the rack archive is not on this machine")
def test_a_run_that_logged_no_speed_or_torque_has_none_never_zeros():
    raw = columns(NO_SPEED_RUN)
    assert "qd" not in raw and "tau" not in raw
    _, traj = run_files.load_run(NO_SPEED_RUN)
    assert traj.velocities is None and traj.effort is None
    assert run_files.column(traj, "qd") is None and run_files.column(traj, "tau") is None
    assert same(traj.positions[:, 0], raw["q"]) and same(traj.t, raw["t"])


def producer_runs() -> list[Path]:
    return sorted(p for p in PRODUCER_DAY.rglob("*.npz") if run_files.producer_path(p).is_file()) if PRODUCER_DAY.is_dir() else []


@pytest.mark.skipif(not producer_runs(), reason="no run with the producer's own joint_trajectory/ file on this machine")
def test_the_message_equals_the_producers_own_joint_trajectory_file():
    runs = producer_runs()
    for path in runs:
        _, traj = run_files.load_run(path)
        theirs = load_npz(run_files.producer_path(path))
        assert traj == theirs, path  # robot_msgs' == : every array, the header, its meta
    assert len(runs) >= 10


def test_a_repeated_stamp_is_dropped_by_the_producers_policy_and_says_so(tmp_path):
    t = np.array([0.00, 0.01, 0.01, 0.02, 0.03])
    path = write_run(tmp_path, "s01_can11_waypoints", {"t": t, "wall": 1e9 + t, "q": [0.0, 0.1, 0.2, 0.3, 0.4], "qd": np.zeros(5),
                                                        "tau": np.zeros(5), "mode": np.full(5, 10.0)})
    _, traj = run_files.load_run(path)
    assert run_files.DUPLICATE_TIMES == "drop_later"
    assert same(traj.t, [0.00, 0.01, 0.02, 0.03]) and same(traj.positions[:, 0], [0.0, 0.1, 0.3, 0.4])
    assert traj.header.meta["time_repair.dropped"]


def test_what_is_not_a_run_stays_not_a_run(tmp_path):
    assert run_files.load_run(write_run(tmp_path, "one_row", {"t": [0.0], "q": [0.0]})) is None
    no_q = tmp_path / "no_q.npz"
    np.savez(no_q, t=np.arange(3.0))
    no_q.with_suffix(".json").write_text(json.dumps({"can_id": 11}))
    assert run_files.load_run(no_q) is None
    no_can = write_run(tmp_path, "no_can", {"t": [0.0, 0.1], "q": [0.0, 0.1]}, can_id=None)
    assert run_files.load_run(no_can) is None
    no_meta = tmp_path / "no_meta.npz"
    np.savez(no_meta, t=np.arange(3.0), q=np.zeros(3))
    assert run_files.load_run(no_meta) is None
    broken = tmp_path / "broken.npz"
    broken.write_bytes(b"not a zip")
    broken.with_suffix(".json").write_text(json.dumps({"can_id": 11}))
    assert run_files.load_run(broken) is None


def test_the_app_reads_every_run_through_it(tmp_path):
    import build_app  # noqa: PLC0415  (io-diagnostics: this test's environment)

    path = write_run(tmp_path, "s01_can11_waypoints", {"t": [0.0, 0.01, 0.02], "wall": [5.0, 5.01, 5.02], "q": [0.0, 0.1, 0.2],
                                                        "qd": [0.0, 1.0, 1.0], "tau": [0.0, 0.0, 0.0]})
    record = build_app.load_run(path)
    assert isinstance(record["trajectory"], JointTrajectory) and "arrays" not in record
    assert record["trajectory"] == run_files.load_run(path)[1]
