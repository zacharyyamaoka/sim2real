"""Many-way twin replays for the sim2real app: every held-out T2 run on CAN 12 and 13 (2026-10-28) played by each of the four
friction models bam_rack_twin compared that day (D, G, H, R); every new held-out tape of the 2026-10-29 calibration round on CAN
1/4/11/14/15/21 played by the station's deployed twin (A) and its calibration-round twin (C), each checked against
calibration_scored.json the same way; plus each station's proven travel window.

Software replay only. Reads the archive (/archive/datasets/bam_rig) and the bam_rack_twin package; never opens a serial port,
an fdcanusb or a CAN bus; writes nothing under bam_ws or /archive (twin scenes go to a temporary directory). Run it with the
package's own venv (it carries bam_rack_twin, bam_sim and MuJoCo):

    /home/bam/bam_ws/.claude/worktrees/sim-to-real-motor-models-f1ee43/src/dev/bam_rack_twin/.venv/bin/python -I /home/bam/sim2real/tools/twin_replays.py

Writes /home/bam/sim2real/app/data/source/twin_replays.json (gitignored; tools/build_app.py reads it).

The models are presliding_round3.py's ``score`` builds, called exactly as it calls them (the same identified points, the same
cogging map phased per run, the same replayer), but without writing its scored file. The oracle: each (model, run) q RMS on
the tape rows must reproduce presliding_round3_scored.json's row within 1e-6 mrad, else the run keeps ``"oracle": "mismatch"``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

# WHY before any package import: read-only over bam_ws, so importing the package and the round studies must not refresh
# their __pycache__ there (-I does not stop bytecode writes)
sys.dont_write_bytecode = True
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MUJOCO_GL", "egl")

PACKAGE = Path(os.environ.get("RACK_TWIN_PACKAGE")
               or "/home/bam/bam_ws/.claude/worktrees/sim-to-real-motor-models-f1ee43/src/dev/bam_rack_twin")
sys.path.insert(0, str(PACKAGE / "docs"))

import numpy as np  # noqa: E402
import presliding_round2 as R2  # noqa: E402
import presliding_round3 as R3  # noqa: E402
import calibration_round as CAL  # noqa: E402
import followup_1029 as FU  # noqa: E402
from bam_rack_twin import __version__ as PACKAGE_VERSION  # noqa: E402
from bam_rack_twin.budget import q_rms_mrad  # noqa: E402
from bam_rack_twin.hardware.tape import TAPE_STATIONS  # noqa: E402

S = R2.S
SCHEMA = "sim2real.twin_replays/1"
OUT = Path("/home/bam/sim2real/app/data/source/twin_replays.json")
SCORED = R3.ANALYSIS / "presliding_round3_scored.json"
ORACLE_TOLERANCE_MRAD = 1e-6
MAX_WORKERS = 4  # the machine is shared
# WHY short names beside the study's labels: they are the series names on screen; the full label stays in the data
SHORT = {"D round 1": "twin D · LuGre", "G LuGre re-identified": "twin G · LuGre re-fit",
         "H LuGre + dwell-time static friction": "twin H · + dwell", "R LuGre + rate-and-state": "twin R · rate-state"}


def floats(values) -> list:
    return [None if not math.isfinite(float(v)) else round(float(v), 7) for v in np.asarray(values, float)]


def station_runs(can: int, scenes: Path, workers: int, scored: dict, log) -> list[dict]:
    """presliding_round3.score's replays for one station, returned as series instead of written as scores."""

    sid = f"can{can}"
    ident = json.loads((R3.ANALYSIS / f"presliding_round3_can{can}.json").read_text(encoding="utf-8"))
    base, a_b = S.deployed(can)
    held = {key: item for key, item in S.load(can, [S.HELD_OUT[can]]).items() if S.t2.class_of(item["label"])}
    replayer = S.r4._replayer(can, {key: item["run"] for key, item in held.items()}, scenes, workers)
    points = ident["points"]
    mapped = lambda key: R2.with_map(base, a_b, held[key], can)  # noqa: E731
    builds = {"D round 1": lambda key: S.lugre_build(mapped(key), points["D round 1"]),
              "G LuGre re-identified": lambda key: R2.g_build(mapped(key), points["G LuGre re-identified"]),
              "H LuGre + dwell-time static friction": lambda key: R2.h_build(mapped(key), points["H LuGre + dwell-time static friction"]),
              "R LuGre + rate-and-state": lambda key: R3.r_build(mapped(key), points["R LuGre + rate-and-state"])}
    floor_mrad = json.loads(S.t2.FLOORS.read_text(encoding="utf-8"))[str(can)]["floor_mrad"]
    stored = {label: {row["run"]: row["q_rms_mrad"] for row in variant["rows"]} for label, variant in scored["stations"][sid]["variants"].items()}
    keys = sorted(held)
    records = {}
    for key in keys:
        item = held[key]
        cls, seed = S.t2.class_of(item["label"])
        records[key] = {"run_path": str(key), "can": can, "device": f"CAN {can}", "label": item["label"], "class": cls, "seed": seed,
                        "prelude_s": float(item["prelude_s"]), "floor_mrad": floor_mrad, "pick": ident["pick"], "models": {}}
    for label, build in builds.items():
        started = time.time()
        replays = dict(zip(keys, S.r4.replay_pairs(replayer, [(build(key), key) for key in keys]), strict=True))
        for key, replay in replays.items():
            item, record = held[key], records[key]
            run_tape, replay_tape = S.t2.tape_rows(item["run"], replay, item["prelude_s"])
            value = q_rms_mrad(run_tape, replay_tape)
            expected = stored.get(label, {}).get(key)
            oracle = "ok" if expected is not None and abs(value - expected) <= ORACLE_TOLERANCE_MRAD else "mismatch"
            if "t" not in record:  # the real run on the tape clock, once (every model replays the same rows)
                record.update({"t": floats(run_tape.t), "q_target_rad": floats(run_tape.q_target), "qd_target_rad_s": floats(run_tape.qd_target),
                               "q_rad": floats(run_tape.q), "qd_rad_s": floats(run_tape.qd), "tau_nm": floats(run_tape.tau),
                               "mode": floats(run_tape.mode), "v_bus_v": floats(run_tape.voltage)})
            record["models"][SHORT[label]] = {"label": label, "version": replay.meta.get("version") if isinstance(replay.meta, dict) else None,
                                              "q_rad": floats(replay_tape.q), "qd_rad_s": floats(replay_tape.qd), "tau_nm": floats(replay_tape.tau),
                                              "q_rms_mrad": value, "expected_q_rms_mrad": expected, "oracle": oracle}
        log(f"{sid} {label:38s} {len(keys)} runs in {time.time() - started:.0f} s; "
            + ", ".join(f"{Path(k).stem} {records[k]['models'][SHORT[label]]['q_rms_mrad']:.2f}" for k in keys))
    return list(records.values())


CAL_SHORT = {"A": "twin A · deployed", "C": "twin C · calibrated"}


def calibration_runs(can: int, scenes: Path, workers: int, scored: dict, direct_doc: dict, log) -> list[dict]:
    """calibration_round.py's ``score`` replays (2026-10-29 round) for one station: every new held-out tape played whole (prelude
    included, the round's ruler) by the deployed twin (A) and this round's fit (C), each rebuilt by ``twins_of`` (it checks the digests)."""

    sid = f"can{can}"
    ident = json.loads((CAL.ANALYSIS / f"calibration_can{can}.json").read_text(encoding="utf-8"))
    held = CAL.held_out(can)
    twins = CAL.twins_of(can, direct_doc, ident)
    keys = sorted(held)
    replayer = S.r4._replayer(can, {key: item["run"] for key, item in held.items()}, scenes, workers)
    floor = scored["stations"][sid]["floor"]
    stored = {label: {row["run"]: row["q_rms_mrad"] for row in variant["rows"]} for label, variant in scored["stations"][sid]["variants"].items()}
    records = {}
    for key in keys:
        item = held[key]
        run = item["run"]
        records[key] = {"run_path": str(key), "can": can, "device": f"CAN {can}", "label": item.get("detail"), "class": item["class"], "seed": item["seed"],
                        "prelude_s": float(item["prelude_s"]), "floor_mrad": floor["floor_mrad"], "pick": scored["stations"][sid]["pick"],
                        "round": "calibration 2026-10-29", "t": floats(run.t - run.t[0]), "q_target_rad": floats(run.q_target), "qd_target_rad_s": floats(run.qd_target),
                        "q_rad": floats(run.q), "qd_rad_s": floats(run.qd), "tau_nm": floats(run.tau), "mode": floats(run.mode), "v_bus_v": floats(run.voltage),
                        "models": {}}
    for label in ("A", "C"):
        started = time.time()
        replays = dict(zip(keys, S.r4.replay_pairs(replayer, [(twins[label], key) for key in keys]), strict=True))
        rows, _ = CAL.D._variant_rows(held, replays)
        for row in rows:
            key, value = row["run"], row["q_rms_mrad"]
            expected = stored[label].get(key)
            replay = replays[key]
            records[key]["models"][CAL_SHORT[label]] = {
                "label": f"{label} ({'the deployed twin before this round' if label == 'A' else 'this round' + chr(39) + 's fit'}; {twins[label].digest()})",
                "q_rad": floats(replay.q), "qd_rad_s": floats(replay.qd), "tau_nm": floats(replay.tau), "q_rms_mrad": value,
                "expected_q_rms_mrad": expected, "oracle": "ok" if expected is not None and abs(value - expected) <= ORACLE_TOLERANCE_MRAD else "mismatch",
                "split": row["split"]}
        log(f"{sid} calibration {label}: {len(keys)} runs in {time.time() - started:.0f} s; "
            + ", ".join(f"{Path(k).stem} {records[k]['models'][CAL_SHORT[label]]['q_rms_mrad']:.2f}" for k in keys))
    return list(records.values())


FU_SHORT = {1: {"C1": "twin C1 · fast inertia"}, 11: {"A": "twin A · deployed", "C": "twin C · calibrated"}}


def followup_runs(can: int, scenes: Path, workers: int, log) -> list[dict]:
    """followup_1029.py's ``score`` replays (2026-10-29 follow-ups): CAN 1's calibration held-out tapes played by C1 (its inertia pinned by the
    fast runs), CAN 11's held-out tapes at its final controller (il0.5) played by A (the declared pick) and C (the held-out-safer pick).
    Each twin is rebuilt by followup_1029.twins_can1/11 (digests checked) and checked against followup_scored_can<N>.json."""

    ident = json.loads(FU._path("identified", can).read_text(encoding="utf-8"))
    scored = json.loads(FU._path("scored", can).read_text(encoding="utf-8"))
    held = CAL.held_out(1) if can == 1 else FU.held_out_can11()
    twins = FU.twins_can1(ident) if can == 1 else FU.twins_can11(ident)
    keys = sorted(held)
    replayer = S.r4._replayer(can, {key: item["run"] for key, item in held.items()}, scenes, workers)
    stored = {label: {row["run"]: row["q_rms_mrad"] for row in variant["rows"]} for label, variant in scored["variants"].items()}
    records = {}
    for key in keys:
        item, run = held[key], held[key]["run"]
        records[key] = {"run_path": str(key), "can": can, "device": f"CAN {can}", "label": item.get("detail"), "class": item["class"], "seed": item["seed"],
                        "prelude_s": float(item["prelude_s"]), "floor_mrad": scored["floor"]["floor_mrad"], "pick": scored["declared_pick"],
                        "round": "follow-up 2026-10-29", "t": floats(run.t - run.t[0]), "q_target_rad": floats(run.q_target),
                        "qd_target_rad_s": floats(run.qd_target), "q_rad": floats(run.q), "qd_rad_s": floats(run.qd), "tau_nm": floats(run.tau),
                        "mode": floats(run.mode), "v_bus_v": floats(run.voltage), "models": {}}
    for label, name in FU_SHORT[can].items():
        replays = dict(zip(keys, S.r4.replay_pairs(replayer, [(twins[label], key) for key in keys]), strict=True))
        rows, _ = CAL.D._variant_rows(held, replays)
        for row in rows:
            expected = stored[label].get(row["run"])
            replay = replays[row["run"]]
            records[row["run"]]["models"][name] = {
                "label": f"{label} (follow-up; {'declared pick' if label == scored['declared_pick'] else ''}{' / ' if label == scored['declared_pick'] and label == scored['safer_pick'] else ''}{'held-out-safer pick' if label == scored['safer_pick'] else ''}; {twins[label].digest()})",
                "q_rad": floats(replay.q), "qd_rad_s": floats(replay.qd), "tau_nm": floats(replay.tau), "q_rms_mrad": row["q_rms_mrad"],
                "expected_q_rms_mrad": expected, "split": row["split"],
                "oracle": "ok" if expected is not None and abs(row["q_rms_mrad"] - expected) <= ORACLE_TOLERANCE_MRAD else "mismatch"}
        log(f"can{can} follow-up {label}: " + ", ".join(f"{Path(k).stem} {records[k]['models'][name]['q_rms_mrad']:.2f}" for k in keys))
    return list(records.values())


def merged(runs: list[dict]) -> list[dict]:
    """One record per run: a run replayed by two rounds (CAN 1's calibration tapes) carries every model."""

    out: dict[str, dict] = {}
    for record in runs:
        if record["run_path"] in out:
            out[record["run_path"]]["models"].update(record["models"])
        else:
            out[record["run_path"]] = record
    return list(out.values())


def envelopes() -> dict:
    """Each station's proven travel window and speed ceiling (bam_rack_twin.hardware.tape.TAPE_STATIONS): the 1-DOF workspace."""

    out = {}
    for can, block in TAPE_STATIONS.items():
        envelope = block.get("envelope", {})
        window = envelope.get("absolute_rad")
        out[f"CAN {can}"] = {"q_min_rad": None if window is None else float(window[0]), "q_max_rad": None if window is None else float(window[1]),
                             "qd_max_rad_s": envelope.get("speed_ceiling_rad_s"), "amplitude_ceiling_rad": envelope.get("amplitude_ceiling_rad")}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--cans", type=int, nargs="*", default=[13, 12])
    parser.add_argument("--calibration-cans", type=int, nargs="*", default=list(CAL.FIT_CANS))
    arguments = parser.parse_args(argv)
    workers = max(1, min(MAX_WORKERS, arguments.workers))
    scored = json.loads(SCORED.read_text(encoding="utf-8"))
    runs = []
    with tempfile.TemporaryDirectory(prefix="sim2real_twin_scenes_") as scenes:
        for can in arguments.cans:
            runs += station_runs(can, Path(scenes), workers, scored, lambda line: print(line, flush=True))
        cal_scored = json.loads(CAL.SCORED.read_text(encoding="utf-8"))
        direct_doc = json.loads(CAL.DIRECT.read_text(encoding="utf-8"))
        for can in arguments.calibration_cans:
            runs += calibration_runs(can, Path(scenes), workers, cal_scored, direct_doc, lambda line: print(line, flush=True))
        for can in (1, 11):
            runs += followup_runs(can, Path(scenes), workers, lambda line: print(line, flush=True))
    runs = merged(runs)
    document = {"schema": SCHEMA, "generated_at": datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(),
                "source": f"bam_rack_twin {PACKAGE_VERSION} at {PACKAGE}; docs/presliding_round3.py score builds; read-only replay, no hardware",
                "scored_file": str(SCORED), "calibration_scored_file": str(CAL.SCORED),
                "followup_scored_files": [str(FU._path("scored", c)) for c in (1, 11)], "envelopes": envelopes(), "runs": runs}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    staging = arguments.out.with_name(arguments.out.name + ".partial")
    staging.write_text(json.dumps(document, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(staging, arguments.out)
    bad = [(r["device"], Path(r["run_path"]).stem, m) for r in runs for m, v in r["models"].items() if v["oracle"] != "ok"]
    print(f"{len(runs)} runs x {len({m for r in runs for m in r['models']})} models -> {arguments.out}; oracle mismatches: {bad or 'none'}")
    return 0 if runs and not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
