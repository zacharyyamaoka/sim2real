"""A recorded run as robot_msgs' JointTrajectory: the one door every reader of the rack's run files goes through.

bam_rack_twin.hardware writes each run as <name>.npz (one 1-D column per channel at the board's own stamps) + <name>.json (its meta,
can_id among it); this repo reads them and never writes them. load_run gives (meta, trajectory), the trajectory built exactly as the
producer's own converter builds it (bam_rack_twin.msgs.run_trajectory, 2026-11-04): positions = q, velocities = qd, effort = tau
(N.m, board frame), every other column a channel (wall among them), t the run's stamps as recorded, header.stamp = wall[0] - t[0] so
stamp + t is the wall clock, frame 'board', units and can_id in header.meta. tools/tests/test_run_files.py holds it equal to the
producer's runs/joint_trajectory/<name>.npz wherever one exists.

WHY build from the npz and not read the producer's file: every run since 10-23 has the npz, only those since 11-04 have the other, and
one rule for both keeps the old runs (and the frozen reports over them) reading the same numbers.
WHY the columns stay float64 (mode and fault too, so they interpolate): the board's log stores them so, and so does the producer's file.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from robot_msgs.std import Header
from robot_msgs.trajectory import JointTrajectory

RUN_FRAME = "board"  # bam_rack_twin.msgs.RUN_FRAME
RUN_UNITS = "t s; positions rad; velocities rad/s; effort N.m (output side when the board's rotor_to_output_ratio is configured)"
# WHY drop_later (bam_rack_twin.msgs.RUN_DUPLICATE_TIMES): two replies at one stamp are two readings and the first is what the loop acted
# on. No run the app reads repeats a stamp (2,239 on 2026-11-10: tools/build_app.py's data came out byte for byte the same through
# this reader, but for its build time), so none loses a row.
DUPLICATE_TIMES = "drop_later"
PRODUCER_DIR = "joint_trajectory"  # bam_rack_twin.msgs.RUN_TRAJECTORY_DIR
FIELDS = {"q": "positions", "qd": "velocities", "tau": "effort"}  # the recorded column -> its JointTrajectory field


def producer_path(npz_path: str | Path) -> Path:
    """Where the producer writes its own JointTrajectory of this run (runs since 2026-11-04)."""
    npz_path = Path(npz_path)
    return npz_path.parent / PRODUCER_DIR / npz_path.name


def trajectory(columns: dict[str, np.ndarray], *, can_id) -> JointTrajectory:
    """The run's columns (equal length, t and q among them) as a JointTrajectory, the producer's way."""
    t = np.asarray(columns["t"], dtype=np.float64)
    wall = columns.get("wall")
    stamp = float(wall[0] - t[0]) if wall is not None and np.isfinite(wall[0] - t[0]) else 0.0
    as_column = lambda name: None if name not in columns else np.asarray(columns[name], dtype=np.float64).reshape(-1, 1)  # noqa: E731
    channels = {name: np.asarray(values, dtype=np.float64) for name, values in columns.items() if name != "t" and name not in FIELDS}
    message, _repair = JointTrajectory.from_samples(
        t=t, joint_names=(f"can{can_id}",), positions=as_column("q"), velocities=as_column("qd"), effort=as_column("tau"), channels=channels,
        header=Header(stamp=stamp, frame_id=RUN_FRAME, meta={"units": RUN_UNITS, "can_id": str(can_id)}), duplicate_times=DUPLICATE_TIMES)
    return message


def load_run(path: str | Path) -> tuple[dict, JointTrajectory] | None:
    """(the run's meta, its JointTrajectory), or None for a file that is not a run: no <name>.json with a can_id beside it, no t or q,
    fewer than two rows, or an npz that does not open (one camera file on 10-23 is not a zip). Columns of another length are not read."""
    path = Path(path)
    meta_path = path.with_suffix(".json")
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get("can_id") is None:
        return None
    try:
        with np.load(path) as archive:
            files = set(archive.files)
            if not {"t", "q"} <= files:
                return None
            columns = {name: np.asarray(archive[name], float) for name in files if archive[name].ndim == 1 and archive[name].size == archive["t"].size}
    except Exception:  # noqa: BLE001 - a truncated npz is not a run
        return None
    if columns["t"].size < 2:
        return None
    try:
        return meta, trajectory(columns, can_id=meta["can_id"])
    except ValueError as error:  # a non-finite stamp: no cleaner can place it, and the build should say which file
        raise ValueError(f"{path}: {error}") from error


def column(traj: JointTrajectory, name: str) -> np.ndarray | None:
    """A recorded column back by its npz name (t, q, qd, tau or a channel), 1-D and read-only; None when the run did not log it."""
    if name == "t":
        return traj.t
    if name in FIELDS:
        values = getattr(traj, FIELDS[name])
        return None if values is None else values[:, 0]
    return traj.channels.get(name)
