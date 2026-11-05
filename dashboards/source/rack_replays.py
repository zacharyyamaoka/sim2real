"""Real-vs-twin time series for the rack's 8 motors: one held-out run per motor, replayed through the twin its dataset file calls "full".

Software replay only. It reads the archive (/archive/datasets/bam_rig) and the bam_rack_twin package, replays in MuJoCo
in worker processes and writes one JSON next to this file. It never opens a serial port, an fdcanusb or a CAN bus, and
writes nothing under bam_ws or /archive (twin scenes go to --scenes, a temporary directory by default).

Which twin and which run, per motor:
- acceptance.json (rack_2026-10-24/analysis) names each station's dataset_twin_can<N>.json (``facts.dataset_source``);
- that file's held-out rows: the first kind ``waypoints`` row (class ``pickplace`` where the file has classes);
- that file's ``twins.full``, rebuilt exactly as the file's producer built it, and refused when the rebuilt version is not
  the one the file names: envelope_twin's budget full twin (10-24 files: CAN 1, 4, 14, 15), round 7's capture twin
  (CAN 11, 12, 13, via round9_study._deployed_twins) or round 9's encoder-PLL twin (CAN 21, via round10_study._can21_written).

The oracle: each motor's q RMS (real - twin, on scorecard.score_replay's rows) must reproduce the file's
``twin_q_rms_mrad.full`` for that run within 2 %; a motor that does not keeps its row with ``"oracle": "mismatch"``.

Run with the package's own venv (it carries bam_rack_twin, bam_sim and MuJoCo):

    /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -I /home/bam/sim2real/dashboards/source/rack_replays.py
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import json
import math
import os
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# WHY before any package import: this script is read-only over bam_ws, and importing the package and the round studies
# would otherwise refresh their __pycache__ files there (-I does not stop bytecode writes; -B or this flag does).
sys.dont_write_bytecode = True

# WHY before numpy/MuJoCo load: each replay is one single-threaded physics loop, and other sessions share this machine,
# so a worker must not fan out BLAS threads. MuJoCo never opens a window (twin.py sets the same default).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MUJOCO_GL", "egl")

PACKAGE = Path(
    os.environ.get("RACK_REPLAYS_PACKAGE")
    or "/home/bam/bam_ws/src/dev/bam_rack_twin"
)
# WHY the docs folder on the path: the round studies that rebuilt the 10-25 twins live there as scripts, not in the package,
# and reusing them (not a copy) is what makes the rebuilt twin the file's twin. Module level, so worker processes get it too.
sys.path.insert(0, str(PACKAGE / "docs"))

import numpy as np  # noqa: E402
from bam_rack_twin import __version__ as PACKAGE_VERSION  # noqa: E402
from bam_rack_twin.budget import Replayer, parameters_from_json, q_rms_mrad  # noqa: E402
from bam_rack_twin.evidence import MODE_POSITION, OutputRun, load_run, to_output_frame  # noqa: E402
from bam_rack_twin.stations import DEFAULT_RECORD_PATH, load_stations  # noqa: E402
from bam_rack_twin.twin import Replay, TwinParameters  # noqa: E402

SCHEMA = "sim2real.rack_replays/1"
ACCEPTANCE = Path("/archive/datasets/bam_rig/rack_2026-10-24/analysis/acceptance.json")
TWIN_NAME = "full"
MAX_DISPLAY_HZ = 100.0
ORACLE_TOLERANCE = 0.02
MAX_WORKERS = 4  # the brief's ceiling: the machine is shared


@dataclasses.dataclass(frozen=True)
class Pick:
    """One motor's held-out run and the twin its dataset file scored it with."""

    can: int
    station_id: str
    dataset_twin_file: Path
    run_path: Path
    kind: str
    run_class: str | None
    seed: int | None
    expected_q_mrad: float
    expected_tau_nm: float | None
    twin_label: str  # the file's twins["full"] text; the rebuilt twin's version must appear in it
    producer: str  # which code wrote the file, so which code rebuilds its twin


# --------------------------------------------------------------------------- picking


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_path_of(row: dict[str, Any], dataset_twin_file: Path) -> Path:
    """The row's npz: 10-25 files hold absolute npz paths, 10-24 files a run name relative to the day root (analysis/..)."""

    path = Path(row["run"])
    if not path.is_absolute():
        path = dataset_twin_file.parents[1] / path
    return path if path.suffix == ".npz" else path.with_name(path.name + ".npz")


def kind_of(row: dict[str, Any], run_path: Path) -> str:
    """The row's kind, or (CAN 21's file names none) the kind the run's own metadata declares."""

    if row.get("kind"):
        return str(row["kind"])
    real = load_run(run_path.parent, run_path)
    if real is None:
        raise ValueError(f"{run_path} is not a run (no metadata next to it)")
    return real.kind


def producer_of(document: dict[str, Any], station_id: str) -> str:
    source = document.get("source")
    if source is None and document.get("budget"):
        return "envelope_twin"  # 10-24 files: bam_rack_twin.envelope_twin over the dataset session
    if str(source).startswith("docs/round7_study.py"):
        return "round7_capture"
    if str(source).startswith("docs/round9_study.py") and station_id == "can21":
        return "round9_pll"
    raise ValueError(f"{station_id}: no rebuild for a dataset file written by {source!r}")


def pick_run(can: int, dataset_twin_file: Path) -> Pick:
    document = _read_json(dataset_twin_file)
    station_id = f"can{can}"
    rows = document["rows"]
    has_classes = any(row.get("class") for row in rows)
    kinds = [kind_of(row, run_path_of(row, dataset_twin_file)) for row in rows]
    # WHY this order: the brief's preference (waypoints, pickplace where classes exist), then waypoints, then the first row,
    # so a file that changes its rows still yields a run and the JSON says which one.
    preferences: list[Callable[[dict[str, Any], str], bool]] = [
        lambda row, kind: kind == "waypoints" and (not has_classes or row.get("class") == "pickplace"),
        lambda row, kind: kind == "waypoints",
        lambda row, kind: True,
    ]
    for prefer in preferences:
        chosen = next(((row, kind) for row, kind in zip(rows, kinds, strict=True) if prefer(row, kind)), None)
        if chosen is not None:
            break
    if chosen is None:
        raise ValueError(f"{dataset_twin_file} has no held-out rows")
    row, kind = chosen
    expected = row["twin_q_rms_mrad"][TWIN_NAME]
    return Pick(
        can=can,
        station_id=station_id,
        dataset_twin_file=dataset_twin_file,
        run_path=run_path_of(row, dataset_twin_file),
        kind=kind,
        run_class=row.get("class"),
        seed=None if row.get("seed") is None else int(row["seed"]),
        expected_q_mrad=float(expected),
        # WHY twin_tau_rms_nm: the 10-25 files store the full twin's torque error there (the 10-24 baseline's beside it as
        # ..._current_best); the 10-24 files stored no torque error at all.
        expected_tau_nm=None if row.get("twin_tau_rms_nm") is None else float(row["twin_tau_rms_nm"]),
        twin_label=str(document["twins"][TWIN_NAME]),
        producer=producer_of(document, station_id),
    )


# --------------------------------------------------------------------------- rebuilding each file's twin and replaying


def _station(station_id: str):
    return next(station for station in load_stations(DEFAULT_RECORD_PATH) if station.id == station_id)


def replay_envelope_twin(pick: Pick, scenes: Path) -> tuple[TwinParameters, OutputRun, Replay, float]:
    """10-24 files: bam_rack_twin.envelope_twin.replay_rungs's "full" twin, run frame, replayer and frame offset, for one run."""

    reference = _read_json(pick.dataset_twin_file)
    budget = _read_json(Path(reference["budget"]))
    twin = parameters_from_json(budget["full_twin"])
    if twin.version != reference["twins"][TWIN_NAME]:
        raise ValueError(f"{pick.station_id}: rebuilt {twin.version}, the file ran {reference['twins'][TWIN_NAME]}")
    station = _station(pick.station_id)
    # WHY the day root as the evidence root: envelope_twin scanned rack_2026-10-24 whole, so a run's name is relative to it.
    real = load_run(pick.dataset_twin_file.parents[1], pick.run_path)
    run = to_output_frame(real, station)
    identified = _read_json(Path(budget["sources"]["scorecard"]) / "identified" / f"{pick.station_id}.json")
    replayer = Replayer({real.name: run}, f"{pick.station_id}_hinge", station.output_pid(), scenes / pick.station_id, 1,
                        float(identified.get("frame_offset_rad") or 0.0))
    replay = replayer.replays({TWIN_NAME: twin}, [real.name])[(TWIN_NAME, real.name)]
    return twin, run, replay, 0.0


def replay_round7_capture(pick: Pick, scenes: Path) -> tuple[TwinParameters, OutputRun, Replay, float]:
    """CAN 11/12/13 (10-25 files): round 7's capture twin as round9_study._deployed_twins rebuilds and checks it, CAN 13's
    rotor-keyed cogging map phased for this run, replayed on round 7's runs (prelude dropped) with round 4's replayer."""

    import round4_study as r4
    import round9_study as r9

    entry = r9._deployed_twins(check=(pick.station_id,))[pick.station_id]
    if entry["twin"].version not in pick.twin_label:
        raise ValueError(f"{pick.station_id}: rebuilt {entry['twin'].version}, the file's full twin is {pick.twin_label!r}")
    key = str(pick.run_path)
    loaded, replayer = r9._replayer(pick.station_id, [key], scenes, 1)
    twin = r9._base_for(entry, entry["twin"])(key)
    [replay] = r4.replay_pairs(replayer, [(twin, key)])
    return twin, replayer.runs[key], replay, float(loaded[key]["prelude_s"])


def replay_round9_pll(pick: Pick, scenes: Path) -> tuple[TwinParameters, OutputRun, Replay, float]:
    """CAN 21 (10-25 file): round 9's encoder-PLL twin, rebuilt from round 9's fit and checked against the file by
    round10_study._can21_written, replayed on CAN 21's 10-25 dataset runs (prelude dropped)."""

    import round4_study as r4
    import round9_study as r9
    import round10_study as r10

    _, twin = r10._can21_written()
    if twin.version not in pick.twin_label:
        raise ValueError(f"{pick.station_id}: rebuilt {twin.version}, the file's full twin is {pick.twin_label!r}")
    key = str(pick.run_path)
    loaded, replayer = r9._replayer(pick.station_id, [key], scenes, 1)
    [replay] = r4.replay_pairs(replayer, [(twin, key)])
    return twin, replayer.runs[key], replay, float(loaded[key]["prelude_s"])


REPLAYERS = {"envelope_twin": replay_envelope_twin, "round7_capture": replay_round7_capture, "round9_pll": replay_round9_pll}


# --------------------------------------------------------------------------- one motor's record


def logged_channels(run_path: Path, prelude_s: float, rows: int) -> tuple[np.ndarray | None, np.ndarray | None]:
    """(i_q A, temperature C) from the run's npz, with the same prelude rows dropped as the replayed run; None if absent."""

    with np.load(run_path) as archive:
        t_raw = np.asarray(archive["t"], float)
        keep = (t_raw - t_raw[0] >= prelude_s) if prelude_s > 0 else np.ones(t_raw.size, bool)
        channels = [np.asarray(archive[name], float)[keep] if name in archive.files else None for name in ("i_q", "temp_c")]
    # WHY refuse a length mismatch rather than trim: a channel shifted by a row would be drawn against the wrong instant.
    return tuple(None if channel is None or channel.size != rows else channel for channel in channels)  # type: ignore[return-value]


def as_list(values: np.ndarray | None, picks: np.ndarray) -> list[float | None] | None:
    if values is None:
        return None
    return [float(value) if math.isfinite(value) else None for value in np.asarray(values, float)[picks]]


def finite_or_none(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else float(value)


def motor_record(pick: Pick, scenes: Path) -> dict[str, Any]:
    started = time.time()
    twin, run, replay, prelude_s = REPLAYERS[pick.producer](pick, scenes)
    # The score rows are scorecard.score_replay's: the board in position mode AND the twin in position mode.
    score_rows = run.controlled & (replay.mode == MODE_POSITION)
    rms_q_mrad = q_rms_mrad(run, replay)
    rms_tau_nm = float(np.sqrt(np.mean((run.tau[score_rows] - replay.tau[score_rows]) ** 2))) if score_rows.any() else math.nan
    current, temperature = logged_channels(pick.run_path, prelude_s, run.t.size)

    # RMS above is on the native rows; only the exported samples are decimated, by picking rows (no averaging).
    period_s = float(np.median(np.diff(run.t)))
    native_hz = 1.0 / period_s
    stride = max(1, math.ceil(native_hz / MAX_DISPLAY_HZ - 1e-9))
    picks = np.arange(0, run.t.size, stride)

    relative = abs(rms_q_mrad - pick.expected_q_mrad) / pick.expected_q_mrad if math.isfinite(rms_q_mrad) else math.inf
    oracle = "ok" if relative <= ORACLE_TOLERANCE else "mismatch"
    note = None
    if oracle == "mismatch":
        note = (f"replayed q RMS {rms_q_mrad:.4f} mrad vs the file's {pick.expected_q_mrad:.4f} mrad ({100 * relative:.2f} % off, "
                f"tolerance {100 * ORACLE_TOLERANCE:.0f} %) with the same twin version; not tuned")
    return {
        "motor": f"CAN {pick.can}",
        "can": pick.can,
        "run_path": str(pick.run_path),
        "kind": pick.kind,
        "class": pick.run_class,
        "seed": pick.seed,
        "twin_name": TWIN_NAME,
        "twin_version": twin.version,
        "dataset_twin_file": str(pick.dataset_twin_file),
        "rms_q_mrad": finite_or_none(rms_q_mrad),
        "rms_q_mrad_expected": pick.expected_q_mrad,
        "rms_tau_nm": finite_or_none(rms_tau_nm),
        "rms_tau_nm_expected": pick.expected_tau_nm,
        "oracle": oracle,
        "note": note,
        "score_rows": int(score_rows.sum()),
        # WHY carried: the 10-25 producers dropped the runner's prelude (its move to the tape's origin) before replaying,
        # so t = 0 is the tape's first row there and the run file's first row for the 10-24 motors.
        "prelude_dropped_s": prelude_s,
        "duration_s": float(run.t[-1] - run.t[0]),
        "native_rate_hz": native_hz,
        "rate_hz": native_hz / stride,
        "replay_wall_s": round(time.time() - started, 1),
        "samples": {
            "t": as_list(run.t - run.t[0], picks),
            "q_target": as_list(run.q_target, picks),
            "q_real": as_list(run.q, picks),
            "q_twin": as_list(replay.q, picks),
            "tau_real": as_list(run.tau, picks),
            "tau_twin": as_list(replay.tau, picks),
            "i_q_real": as_list(current, picks),
            "temp_c_real": as_list(temperature, picks),
        },
    }


# --------------------------------------------------------------------------- provenance


def worktree_head(package: Path) -> str:
    """HEAD's commit and branch, read from the git files. WHY files and never ``git``: this script only reads the worktree."""

    gitdir = None
    for folder in (package, *package.parents):
        marker = folder / ".git"
        if marker.is_file():
            gitdir = Path(marker.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
            break
        if marker.is_dir():
            gitdir = marker
            break
    if gitdir is None:
        return "unknown"
    head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        return head
    reference = head.split(":", 1)[1].strip()
    common = gitdir / "commondir"
    common_dir = (gitdir / common.read_text(encoding="utf-8").strip()).resolve() if common.is_file() else gitdir
    branch = reference.removeprefix("refs/heads/")
    for base in (gitdir, common_dir):
        loose = base / reference
        if loose.is_file():
            return f"{loose.read_text(encoding='utf-8').strip()} ({branch})"
    packed = common_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + reference):
                return f"{line.split()[0]} ({branch})"
    return f"unknown ({branch})"


# --------------------------------------------------------------------------- main


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".partial")
    staging.write_text(json.dumps(document, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(staging, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().with_name("rack_replays.json"))
    parser.add_argument("--scenes", type=Path, help="where the twin scenes go (default: a temporary directory, removed at exit)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--cans", type=int, nargs="*", help="only these CAN ids (default: every station acceptance.json lists)")
    arguments = parser.parse_args(argv)
    workers = max(1, min(MAX_WORKERS, arguments.workers))

    acceptance = _read_json(ACCEPTANCE)
    picks: list[Pick] = []
    not_replayed: list[dict[str, Any]] = []
    for can_text, station in sorted(acceptance["stations"].items(), key=lambda item: int(item[0])):
        can = int(can_text)
        if arguments.cans and can not in arguments.cans:
            continue
        source = station.get("facts", {}).get("dataset_source")
        try:
            if not source:
                raise ValueError("acceptance.json names no dataset_source")
            picks.append(pick_run(can, Path(source)))
        except (OSError, ValueError, KeyError) as error:
            not_replayed.append({"motor": f"CAN {can}", "can": can, "reason": f"{type(error).__name__}: {error}"})

    with tempfile.TemporaryDirectory(prefix="rack_replays_scenes_") as temporary:
        scenes = (arguments.scenes or Path(temporary)).resolve()
        records: list[dict[str, Any]] = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, min(workers, len(picks)))) as pool:
            futures = {pick.can: (pick, pool.submit(motor_record, pick, scenes)) for pick in picks}
            for can, (pick, future) in futures.items():
                try:
                    records.append(future.result())
                except (Exception, SystemExit) as error:  # WHY SystemExit too: the round studies refuse a wrong twin with it
                    not_replayed.append({"motor": f"CAN {can}", "can": can, "reason": f"{type(error).__name__}: {error}"})

    records.sort(key=lambda record: record["can"])
    not_replayed.sort(key=lambda item: item["can"])
    document = {
        "schema": SCHEMA,
        "generated_at": datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "source": f"bam_rack_twin {PACKAGE_VERSION} at {PACKAGE}, worktree HEAD {worktree_head(PACKAGE)}; read-only replay, no hardware",
        "runs": records,
        "not_replayed": not_replayed,
    }
    write_json(arguments.out, document)

    print(f"{'motor':<8}{'run':<64}{'twin':<22}{'q mrad':>9}{'expected':>10}{'tau N.m':>9}  oracle")
    for record in records:
        print(f"{record['motor']:<8}{Path(record['run_path']).name + ' ' + str(record['class'] or ''):<64}{record['twin_version']:<22}"
              f"{record['rms_q_mrad']:>9.4f}{record['rms_q_mrad_expected']:>10.4f}"
              f"{(record['rms_tau_nm'] if record['rms_tau_nm'] is not None else math.nan):>9.4f}  {record['oracle']}")
    for item in not_replayed:
        print(f"{item['motor']:<8}NOT REPLAYED: {item['reason']}")
    print(f"wrote {arguments.out}")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
