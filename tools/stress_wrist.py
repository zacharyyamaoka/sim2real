"""The wrist's one-click under stress: Twin.load("ur_wrist_test_rig").calibrate(on="sim", truth="sealed") run on ladders of noise, truth
distance and model mismatch, three fixed seeds a level, to find where recovery breaks and which parameter breaks first.

    # the whole ladder (each cell a subprocess; resumes: a cell already written is kept)
    env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src systemd-run --user --scope -p MemoryMax=24G -p OOMPolicy=continue -- /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python /home/bam/sim2real/tools/stress_wrist.py run --parallel 4 --workers 5
    # one cell, in process
    env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python /home/bam/sim2real/tools/stress_wrist.py cell torque 3 20261112
    # the table and one plot per ladder, from the cells written
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python /home/bam/sim2real/tools/stress_wrist.py report

Zach (2026-11-11): "once you can prove that the entire routine recovers perfectly (and you stress test it with different levels of noise)
then we run that routine in reality." The coordinator's brief, the same evening (the ladders below, 3+ seeds each, ~3 h of wall time).

The ladders (LADDERS), each a one-factor-at-a-time sweep around the rig's measured 1x (sysid/examples/ur_wrist_test_rig/rig.py noise_1x):

    overall    every noise term x level (NoiseModel.at): 0, 1, 2, 3, 5, 10
    torque     the torque reading's noise alone x level, the rest at 1x: 1, 3, 10
    encoder    the encoder's step, its white noise and the velocity's noise alone x level: 1, 3, 10
    timing     the host loop's overrun and the command latency jitter alone x level: 0, 1, 3
    truth      the hidden truth k times as far from nominal as world.json's, held physical (far_truth): 1, 2, 3
    mismatch   a Coulomb friction on each motor hinge (before the gear's gap) in the world only, which the twin lacks: 0-40 mN.m

WHY one factor at a time around 1x and not each term alone on a noise-free world: the question is which term breaks the routine as the real
rig drifts from its measured noise, and the terms act together (a dead band's threshold is crossed by the torque noise on top of the timing's
spread); level 1 of every ladder is then the one-click's own 1x, one shared run per seed.

WHY the truth ladder is not NoiseModel.truth_offset (measured 2026-11-11, sim2real.rig.ruler at 82f14db): that knob moves every value along
nominal + k (truth - nominal), and past ~1.1 it leaves the physical domain: at 2 every joint's viscous damping is negative (CAN 14 -0.001,
CAN 15 -0.004, CAN 16 -0.005 N.m.s/rad; the routine clamps its estimate at 0, so the rows fail by construction) and the command delay is
-4.3 ms; at 3 CAN 15's breakaway (70 mN.m) is below its sliding level (114 mN.m). far_truth is that rule with those three clamped to their
bound, handed to the runner through its own world hook (sim2real.rig.RigRunner(world=...)), so the seal and the ruler are the seam's.

WHY the motor friction is patched into the world's plant here and not added to the rig: it is a truth the model lacks by design (the
stress lane's mismatch), so it lives in the stress tool, applied in the cell's own process (the pool's workers fork from it) and only to
the plays that measure the world (build_plant with a seed); the twin's replays (no seed) never carry it.

Every number a person reads is in degrees, arcminutes, milliseconds, millimetres or mN.m; the values stay SI. SIM ONLY: nothing here opens
a serial port or a CAN bus.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import traceback
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NAME = "ur_wrist_test_rig"
SCHEMA = "sim2real.stress_wrist/1"
SEEDS = (20261111, 20261112, 20261113)   # the one-click lane's own seed first
SLUG = "one-click-stress-2026-11-11"
ARCMIN = math.pi / (180.0 * 60.0)
RIG_MODULE = f"sysid.examples.{NAME}.rig"


def main_checkout() -> Path:
    """The repository's main checkout (the parent of the common git dir), where reports/ lives even when this runs from a worktree."""
    try:
        common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"], check=True,
                                capture_output=True, text=True).stdout.strip()
        return Path(common).parent
    except (OSError, subprocess.CalledProcessError):
        return REPO


def default_out() -> Path:
    return main_checkout() / "reports" / "media" / SLUG / "wrist"


# --- the ladders -------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ladder:
    name: str
    title: str
    levels: tuple
    terms: tuple = ()          # the NoiseModel terms a single-term ladder scales (the rest stay at 1x)
    baseline: float = 1        # the level that is the one-click's own 1x on the committed world
    axis: str = "x the rig's 1x"
    note: str = ""


LADDERS: dict[str, Ladder] = {
    "overall": Ladder("overall", "every noise term together", (0, 1, 2, 3, 5, 10), note="NoiseModel.at(level)"),
    "torque": Ladder("torque", "the torque reading's noise alone", (1, 3, 10), ("torque_noise_nm", "torque_disturbance_nm"),
                     note="torque_noise_nm x level (1x 10 mN.m; the applied-torque disturbance is 0 at 1x, so x level stays 0)"),
    "encoder": Ladder("encoder", "the encoder's step and the velocity's noise alone", (1, 3, 10),
                      ("encoder_quantum_rad", "encoder_noise_rad", "velocity_noise_rad_s"),
                      note="encoder step (1x 2 pi / 65536) and velocity sigma (1x 1e-3 rad/s) x level; the encoder's white noise is 0 at 1x"),
    "timing": Ladder("timing", "the host loop's timing alone", (0, 1, 3), ("period_overrun_s", "latency_jitter_s"),
                     note="the host loop's mean overrun (1x 0.71 ms) x level; the command latency jitter is 0 at 1x (the floor anchor), so x level stays 0"),
    "truth": Ladder("truth", "the hidden truth's distance from nominal", (1, 2, 3), axis="x world.json's offset from nominal",
                    note="far_truth: nominal + level (truth - nominal), damping and delay clamped at 0, breakaway at least the sliding level"),
    "mismatch": Ladder("mismatch", "a motor-side friction the model lacks", (0, 10, 20, 40), baseline=0, axis="mN.m on each motor hinge",
                       note="Coulomb friction (MuJoCo frictionloss, the plant's 2 ms solref) on each geared joint's motor hinge, in the world only"),
}


def noise_for(ladder: str, level: float, seed: int, base):
    """The NoiseModel a cell plays: ``base`` (the rig's 1x) scaled as the ladder says, drawn with ``seed``."""
    spec = LADDERS[ladder]
    if ladder == "overall":
        return base.at(float(level)).with_terms(seed=int(seed))
    if spec.terms:
        return base.with_terms(**{term: float(level) * float(getattr(base, term)) for term in spec.terms}, seed=int(seed))
    return base.with_terms(seed=int(seed))


def variant_for(ladder: str, level: float) -> dict:
    """What a cell changes in the world beyond its noise: the far truth's level, or the motor hinge's friction (N.m). {} = committed."""
    if ladder == "truth" and float(level) != 1.0:
        return {"far_truth": float(level)}
    if ladder == "mismatch" and float(level) != 0.0:
        return {"motor_friction_nm": float(level) * 1e-3}
    return {}


def far_truth(truth: Mapping[str, float], nominal: Mapping[str, float | None], level: float) -> tuple[dict, dict]:
    """world.json's truth ``level`` times as far from nominal (sim2real.rig.ruler's rule at truth_offset=level), with the values that rule
    takes out of their physical domain set on its bound: each viscous damping and the command delay at least 0, each breakaway at least its
    sliding level (raised to it). Returns (values, {key: (the rule's value, the bound's)})."""
    out = {}
    for key, value in truth.items():
        prior = nominal.get(key)
        out[key] = float(value) if prior is None else float(prior) + float(level) * (float(value) - float(prior))
    clamped = {}
    for key in list(out):
        if key.endswith(".damping_nm_s_rad") or key == "wrist.command_delay_s":
            if out[key] < 0.0:
                clamped[key] = (out[key], 0.0)
                out[key] = 0.0
    for key in [k for k in out if k.endswith(".static_friction_nm")]:
        sliding = out[key.replace(".static_friction_nm", ".coulomb_nm")]
        if out[key] < sliding:
            clamped[key] = (out[key], sliding)
            out[key] = sliding
    return out, clamped


@contextlib.contextmanager
def motor_friction(friction_nm: float):
    """Each geared joint's MOTOR hinge given a Coulomb friction (MuJoCo frictionloss, the plant's own 2 ms friction solref) in every plant
    that measures the world (rig.build_plant called with a seed), never in the twin's replays (no seed). In this process only; the pool's
    workers fork from it, so they carry it. Restored on exit.

    WHY on the motor hinge: the truth's friction acts on the OUTPUT (gear_backlash's output_friction: the link tendon), so a crossing of the
    gap is free; a real gearbox also drags on its input side (the rotor's bearings, the first stage's mesh), which turns with the motor
    across the gap. The twin has no such term: a Coulomb level that lumps both is the most it can learn."""
    import importlib  # noqa: PLC0415

    wr = importlib.import_module(RIG_MODULE)
    original = wr.build_plant

    def build_plant(values, start_cad, *, noise=None, seed=None):
        plant = original(values, start_cad, noise=noise, seed=seed)
        if seed is not None:
            motors = plant.wrist.dof_adr[plant.wrist.wrapped]
            plant.model.dof_frictionloss[motors] = float(friction_nm)
            plant.model.dof_solref[motors] = (0.002, 1.0)
        return plant

    wr.build_plant = build_plant
    try:
        yield
    finally:
        wr.build_plant = original


# --- the cells ---------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    ladder: str
    level: float
    seed: int

    def config(self, base) -> dict:
        noise = noise_for(self.ladder, self.level, self.seed, base).to_dict()
        noise.pop("sources", None)
        return {"noise": noise, "variant": variant_for(self.ladder, self.level)}

    def label(self, base) -> str:
        """The file a cell's record lands in. Every ladder's baseline level is one run per seed ("baseline-s<seed>")."""
        if self.config(base) == Cell("overall", 1, self.seed).config(base):
            return f"baseline-s{self.seed}"
        return f"{self.ladder}-{self.level:g}-s{self.seed}"


def _git(*args: str, cwd: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


BAM_WS = Path("/home/bam/bam_ws")
BAM_WS_PACKAGES = ("src/dev/bam_ur_wrist", "src/dev/bam_ur_wrist_coverage", "src/core/mdp/agent/actuators/gear_backlash",
                   "src/core/mdp/setup/bam_homing", "src/dev/bam_fb_test_rig", "src/dev/bam_rack_twin")
CODE_FILES = ("src/sim2real/rig.py", "src/sim2real/twin.py", f"sysid/examples/{NAME}/rig.py", f"sysid/examples/{NAME}/plant.py",
              f"sysid/examples/{NAME}/world.json", f"sysid/examples/{NAME}/description.json", f"sysid/examples/{NAME}/plans_can14.json")


def provenance(workers: int) -> dict:
    """What a cell ran: this checkout's commit and the hash of the files the calibration runs (the seam, the rig, its plant and truth), and
    bam_ws's tree for each package the rig imports in place (a peer's merge mid-ladder shows here)."""
    digest = hashlib.sha256()
    for name in CODE_FILES:
        digest.update(name.encode() + b"\0" + (REPO / name).read_bytes())
    trees = {pkg: _git("rev-parse", f"HEAD:{pkg}", cwd=BAM_WS) for pkg in BAM_WS_PACKAGES}
    dirty = {pkg: bool(_git("status", "--porcelain", "--", pkg, cwd=BAM_WS)) for pkg in BAM_WS_PACKAGES}
    return {"sim2real": _git("rev-parse", "HEAD", cwd=REPO), "checkout": str(REPO), "code_sha256": digest.hexdigest()[:16],
            "bam_ws": _git("rev-parse", "HEAD", cwd=BAM_WS), "bam_ws_trees": trees, "bam_ws_dirty": dirty, "workers": int(workers),
            "host": os.uname().nodename, "python": sys.version.split()[0], "pid": os.getpid(),
            "load_at_start": os.getloadavg()[0], "started": dt.datetime.now().isoformat(timespec="seconds")}


def _raising_routine(tb) -> str | None:
    """The routine RigRunner.calibrate was running when the exception left it (its loop variable), if any."""
    routine = None
    while tb is not None:
        frame = tb.tb_frame
        if frame.f_code.co_name == "calibrate" and "routine" in frame.f_locals:
            routine = getattr(frame.f_locals["routine"], "id", routine)
        tb = tb.tb_next
    return routine


def run_cell(cell: Cell, *, workers: int = 6, out: Path | None = None) -> dict:
    """One cell in this process: calibrate on the sealed world at the cell's noise and variant, then eval_twin. Returns its record (and
    writes it to ``out``/cells/<label>.json); a calibration that raises is a record too, with the routine that raised."""
    import sim2real  # noqa: PLC0415
    from sim2real import rig as seam  # noqa: PLC0415

    started = time.monotonic()
    twin = sim2real.Twin.load(NAME, workers=workers)
    base = twin.noise()
    noise = noise_for(cell.ladder, cell.level, cell.seed, base)
    variant = variant_for(cell.ladder, cell.level)
    record = {"schema": SCHEMA, "cell": dataclasses.asdict(cell), "label": cell.label(base), "variant": variant,
              "ladder_note": LADDERS[cell.ladder].note, "provenance": provenance(workers)}
    if "far_truth" in variant:
        committed = json.loads((REPO / "sysid" / "examples" / NAME / "world.json").read_text())["truth"]
        far, clamped = far_truth(committed, twin.runner.nominal(), variant["far_truth"])
        record["clamped"] = {k: list(v) for k, v in clamped.items()}
        # WHY the runner's own world hook: the runner alone reads the truth and every fit stays inside sysid.world.sealed(); at
        # truth_offset 1 the ruler is exactly these values, the derived ones re-derived from them by the rig
        twin.runner = seam.RigRunner(twin.description, twin.runner.rig, workers=workers, world=lambda: {"truth": dict(far)})
    patch = motor_friction(variant["motor_friction_nm"]) if "motor_friction_nm" in variant else contextlib.nullcontext()
    try:
        with patch:
            t0 = time.monotonic()
            fitted = twin.calibrate(on="sim", truth="sealed", noise=noise)
            t1 = time.monotonic()
            report = fitted.eval_twin()
            t2 = time.monotonic()
        cal = fitted.calibration_
        record.update({"calibration": cal.to_dict(), "report": report.to_dict(),
                       "seconds": {"load": round(t0 - started, 1), "calibrate": round(t1 - t0, 1), "eval": round(t2 - t1, 1),
                                   "total": round(t2 - started, 1)},
                       "summary": cal.summary() + "\n" + report.summary()})
    except Exception as exc:  # noqa: BLE001 - a calibration that raises is a verdict, recorded
        record.update({"error": f"{type(exc).__name__}: {exc}", "routine": _raising_routine(exc.__traceback__),
                       "traceback": traceback.format_exc(), "noise": noise.to_dict(),
                       "seconds": {"total": round(time.monotonic() - started, 1)}})
    import resource  # noqa: PLC0415

    me, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    record["peak_rss_mb"] = {"parent": round(me.ru_maxrss / 1024, 1), "largest_worker": round(kids.ru_maxrss / 1024, 1)}
    # the CPU the cell spent (its pools' workers are joined, so counted): what the ladder's budget is made of
    record["cpu_s"] = {"parent": round(me.ru_utime + me.ru_stime, 1), "workers": round(kids.ru_utime + kids.ru_stime, 1)}
    if out is not None:
        write_record(Path(out), record)
    return record


FRONT = ("servo.backlash_reversal_held", "servo.breakaway_two_sided", "homing.single_touch")


class FrontRig:
    """The rig with only the routines that run before the dynamics (FRONT: backlash, breakaway, homing), on the seam's own runner: the
    same streams, run ids and order as a whole calibration's first three routines, so the same values (front_check holds it); every later
    routine's parameter is said not run. WHY (measured 2026-11-11 at load ~70): a whole sequence took ~1 h a cell, 90 % of it the dynamics'
    replays, while these three take ~2 min and are where the noise ladders break (probe_dead_band)."""

    def __init__(self, rig) -> None:
        self._rig = rig
        self.name = rig.name
        self.model = getattr(rig, "model", "rig twin") + " (front pass: " + ", ".join(FRONT) + ")"

    def routines(self):
        return tuple(r for r in self._rig.routines() if r.id in FRONT)

    def parameters(self):
        keep = {k for r in self.routines() for k in r.identifies}
        return tuple(p if (p.key in keep or p.routine is None) else
                     dataclasses.replace(p, routine=None, tolerance=None, tolerance_source="", why_not="not run: the front pass stops before the dynamics")
                     for p in self._rig.parameters())

    def __getattr__(self, name):
        return getattr(self._rig, name)


def run_front_cell(cell: Cell, *, workers: int = 3, out: Path | None = None) -> dict:
    """One cell's front pass (FrontRig) in this process: the backlash, breakaway and homing routines on the cell's world, no eval_twin.
    Written to ``out``/front/<label>.json."""
    import sim2real  # noqa: PLC0415
    from sim2real import rig as seam  # noqa: PLC0415

    started = time.monotonic()
    twin = sim2real.Twin.load(NAME, workers=workers)
    base = twin.noise()
    noise = noise_for(cell.ladder, cell.level, cell.seed, base)
    variant = variant_for(cell.ladder, cell.level)
    record = {"schema": SCHEMA + "#front", "cell": dataclasses.asdict(cell), "label": cell.label(base), "variant": variant, "front": list(FRONT),
              "provenance": provenance(workers)}
    world = None
    if "far_truth" in variant:
        committed = json.loads((REPO / "sysid" / "examples" / NAME / "world.json").read_text())["truth"]
        far, clamped = far_truth(committed, twin.runner.nominal(), variant["far_truth"])
        record["clamped"] = {k: list(v) for k, v in clamped.items()}
        world = lambda: {"truth": dict(far)}  # noqa: E731
    runner = seam.RigRunner(twin.description, FrontRig(twin.runner.rig), workers=workers, world=world)
    patch = motor_friction(variant["motor_friction_nm"]) if "motor_friction_nm" in variant else contextlib.nullcontext()
    try:
        with patch:
            calibration, _ = runner.calibrate(noise=noise)
        record.update({"calibration": calibration.to_dict(), "seconds": {"total": round(time.monotonic() - started, 1)},
                       "summary": calibration.summary()})
    except Exception as exc:  # noqa: BLE001 - a routine that raises is a verdict, recorded
        record.update({"error": f"{type(exc).__name__}: {exc}", "routine": _raising_routine(exc.__traceback__),
                       "traceback": traceback.format_exc(), "noise": noise.to_dict(), "seconds": {"total": round(time.monotonic() - started, 1)}})
    if out is not None:
        write_record(Path(out), record, folder="front")
    return record


def write_record(out: Path, record: dict, folder: str = "cells") -> Path:
    folder = out / folder
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{record['label']}.json"
    partial = path.with_suffix(f".{os.getpid()}.tmp")
    partial.write_text(json.dumps(record, indent=1, default=_plain))
    partial.replace(path)
    return path


def _plain(value):
    try:
        import numpy as np  # noqa: PLC0415

        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    except ImportError:
        pass
    return str(value)


def read_records(out: Path, folder: str = "cells") -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((Path(out) / folder).glob("*.json"))]


# --- running many cells ------------------------------------------------------------------------------------------------------------------


def _base():
    """The rig's 1x without building a twin (the rig module's own noise_1x)."""
    import importlib  # noqa: PLC0415

    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    return importlib.import_module(RIG_MODULE).noise_1x()


def run_cells(cells: Sequence[Cell], *, out: Path, parallel: int = 3, workers: int = 6, reuse: bool = True,
              python: str | None = None, say=None, front: bool = False) -> list[dict]:
    """Each cell in its own subprocess (``python stress_wrist.py cell ...``), ``parallel`` at a time, ``workers`` pool workers each; its
    stderr (the runner's progress) in cells/<label>.log. Returns the records in ``cells``' order. With ``reuse``, a cell whose record is
    already written with the same configuration and code is not run again.

    WHY subprocesses: each calibration forks its own pools from its own process, and a cell that dies (OOM, a crash in MuJoCo) takes no
    other cell with it."""
    out = Path(out)
    sub = "front" if front else "cells"
    (out / sub).mkdir(parents=True, exist_ok=True)
    say = say or (lambda text: print(text, flush=True))
    base = _base()
    labels = [c.label(base) for c in cells]
    unique: dict[str, Cell] = {}
    for cell, label in zip(cells, labels):
        unique.setdefault(label, cell)
    code = provenance(workers)["code_sha256"]
    todo = []
    for label, cell in unique.items():
        path = out / sub / f"{label}.json"
        if _alive(out / sub / f"{label}.pid"):
            continue   # another runner has it in flight
        if reuse and path.exists():
            old = json.loads(path.read_text())
            noise = {k: v for k, v in old.get("calibration", {}).get("noise", {}).items() if k != "sources"}
            if "error" not in old and old.get("provenance", {}).get("code_sha256") == code and \
                    {"noise": noise, "variant": old.get("variant")} == cell.config(base):
                continue
        todo.append((label, cell))
    say(f"[stress_wrist {time.strftime('%H:%M:%S')}] {len(unique)} cells, {len(todo)} to run, {parallel} at a time x {workers} workers")
    running: list[tuple[str, subprocess.Popen, float]] = []
    queue = list(todo)
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    while queue or running:
        while queue and len(running) < parallel:
            label, cell = queue.pop(0)
            log = open(out / sub / f"{label}.log", "w")  # noqa: SIM115 - closed with the process
            argv = [python or sys.executable, str(Path(__file__).resolve()), "cell", cell.ladder, f"{cell.level:g}", str(cell.seed),
                    "--workers", str(workers), "--out", str(out)] + (["--front"] if front else [])
            proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
            (out / sub / f"{label}.pid").write_text(str(proc.pid))
            running.append((label, proc, time.monotonic()))
            say(f"[stress_wrist {time.strftime('%H:%M:%S')}] start {label} (pid {running[-1][1].pid})")
        time.sleep(5)
        for item in list(running):
            label, proc, began = item
            if proc.poll() is not None:
                running.remove(item)
                (out / sub / f"{label}.pid").unlink(missing_ok=True)
                path = out / sub / f"{label}.json"
                verdict = "missing record" if not path.exists() else _verdict(json.loads(path.read_text()))
                say(f"[stress_wrist {time.strftime('%H:%M:%S')}] done {label} in {time.monotonic() - began:.0f} s (exit {proc.returncode}): {verdict}")
    records = []
    for label in labels:
        path = out / sub / f"{label}.json"
        records.append(json.loads(path.read_text()) if path.exists() else {"label": label, "error": "no record written (see its .log)"})
    return records


def _alive(pid_file: Path) -> bool:
    try:
        os.kill(int(pid_file.read_text()), 0)
        return True
    except (OSError, ValueError):
        return False


def _verdict(record: dict) -> str:
    if "error" in record:
        return f"RAISED in {record.get('routine')}: {record['error'][:160]}"
    cal = record["calibration"]
    if "report" not in record:
        return (f"{'PASS' if cal['passed'] else 'FAIL'} {sum(r['pass'] is True for r in cal['rows'])}/{sum(r['pass'] is not None for r in cal['rows'])}"
                + (f" failing {', '.join(cal['failing'])}" if cal["failing"] else "") + f"; front pass; {record['seconds']['total']:.0f} s")
    rep = record["report"]
    gates = ", ".join(f"{g['id']} {'pass' if g['passed'] else 'FAIL'}" for g in rep["gates"])
    return (f"{'PASS' if cal['passed'] else 'FAIL'} {sum(r['pass'] is True for r in cal['rows'])}/{sum(r['pass'] is not None for r in cal['rows'])}"
            + (f" failing {', '.join(cal['failing'])}" if cal["failing"] else "") + f"; gates {gates}; {record['seconds']['total']:.0f} s")


def plan(ladders: Iterable[str] | None = None, seeds: Sequence[int] = SEEDS) -> list[Cell]:
    """Every cell of the ladders, in the order that answers the most first: the 1x on every seed, then each ladder's nearest stress level,
    then the farther ones. The noise-free level of the overall ladder is one run (no term draws at 0x, so every seed is the same run)."""
    wanted = list(ladders or LADDERS)
    first = {"overall": (2, 3), "torque": (3,), "encoder": (3,), "timing": (0, 3), "truth": (2,), "mismatch": (10,)}
    order: list[Cell] = [Cell("overall", 1, s) for s in seeds]
    # WHY seed-major inside a wave: one seed of every level lands before a second seed of any, so a ladder cut short by the budget still
    # has every level read
    for wave in ("near", "far"):
        for seed in seeds:
            for ladder in wanted:
                spec = LADDERS[ladder]
                for level in spec.levels:
                    if level == spec.baseline or (wave == "near") != (level in first[ladder]):
                        continue
                    if ladder == "overall" and level == 0 and seed != seeds[0]:
                        continue
                    order.append(Cell(ladder, level, seed))
    return order


# --- the verdicts ------------------------------------------------------------------------------------------------------------------------


def _ratio(row: dict) -> float | None:
    """|error| / tolerance of one row (1 = on the tolerance)."""
    tol, err, true = row.get("tolerance"), row.get("error"), row.get("true")
    if tol is None or err is None:
        return None
    limit = tol["value"] if tol["kind"] == "abs" else tol["value"] * abs(true)
    return abs(err) / limit if limit else None


def misses(record: dict) -> dict[str, float | None]:
    """The parameters a record misses: {key: |error| / tolerance} (None when no value came back); a raised calibration is one miss named by
    its routine."""
    if "error" in record:
        return {f"raised in {record.get('routine') or 'the runner'}": None}
    return {r["key"]: _ratio(r) for r in record["calibration"]["rows"] if r["pass"] is False}


def breaking_point(records: Sequence[dict]) -> dict:
    """The first level (ascending) at which any seed misses any parameter, the parameters missed there (most seeds first, then the worst
    |error| / tolerance) and which seeds missed each. ``level`` None: nothing missed at any level run."""
    by_level: dict[float, list[dict]] = {}
    for record in records:
        by_level.setdefault(float(record["cell"]["level"]), []).append(record)
    for level in sorted(by_level):
        seeds: dict[str, list[int]] = {}
        worst: dict[str, float] = {}
        for record in by_level[level]:
            for key, ratio in misses(record).items():
                seeds.setdefault(key, []).append(int(record["cell"]["seed"]))
                worst[key] = max(worst.get(key, 0.0), math.inf if ratio is None else ratio)
        if seeds:
            names = sorted(seeds, key=lambda k: (-len(seeds[k]), -worst[k]))
            return {"level": level, "params": names, "seeds": {k: sorted(v) for k, v in seeds.items()}, "worst": worst,
                    "of": len(by_level[level])}
    return {"level": None, "params": [], "seeds": {}, "worst": {}, "of": 0}


def ladder_records(records: Sequence[dict], ladder: str, base) -> list[dict]:
    """The records that make up one ladder: each level's cells (the baseline level's are the shared baseline runs), relabelled to it."""
    spec = LADDERS[ladder]
    by_label = {r["label"]: r for r in records}
    out = []
    for level in spec.levels:
        for seed in SEEDS:
            label = Cell(ladder, level, seed).label(base)
            if ladder == "overall" and level == 0 and label not in by_label:
                continue
            record = by_label.get(label)
            if record is None:
                continue
            out.append({**record, "cell": {"ladder": ladder, "level": level, "seed": seed}})
    return out


# --- the report: the ladder table and one plot per ladder ---------------------------------------------------------------------------------

# the reference palette's first three categorical slots (validated all-pairs, light), the recessive gray, the chart's ink and surface
# (the dataviz skill's references/palette.md)
EMPHASIS = ("#2a78d6", "#eb6834", "#1baf7a")
QUIET = "#c3c2b7"
INK, INK_2, MUTED, GRID, SURFACE, BAND = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb", "#f0efec"
FLOOR_RATIO = 0.01   # |error| / tolerance below this is drawn on the floor (an exact recovery has no log)


def human_error(row: dict) -> str:
    """A row's signed error as a person reads it: deg / arcmin / ms by the row's display, mN.m for a torque, % for the rest."""
    err, true = row.get("error"), row.get("true")
    if err is None:
        return "no value"
    display, unit = row.get("display") or "", row.get("unit") or ""
    if display == "deg":
        return f"{math.degrees(err):+.3f} deg"
    if display == "arcmin":
        return f"{err / ARCMIN:+.2f} arcmin"
    if display == "ms":
        return f"{err * 1e3:+.2f} ms"
    if display == "mm":
        return f"{err * 1e3:+.3f} mm"
    if unit == "N·m":
        return f"{err * 1e3:+.1f} mN.m"
    if unit == "N·m·s/rad":
        return f"{err * 1e3:+.2f} mN.m.s/rad"
    return f"{100.0 * err / abs(true):+.1f} %" if true else f"{err:+.3g} {unit}"


def cell_metrics(record: dict) -> dict:
    """The numbers one cell is read by: per parameter |error| / tolerance and pass, the gates, held-out / floor, the tool, wall time."""
    if "error" in record:
        return {"raised": record["error"], "routine": record.get("routine"), "seconds": record.get("seconds", {}).get("total")}
    rows = [r for r in record["calibration"]["rows"] if r["pass"] is not None]
    if "report" not in record:   # a front pass: the routines before the dynamics only
        return {"params": {r["key"]: {"ratio": _ratio(r), "pass": r["pass"], "error": human_error(r)} for r in rows},
                "passed": sum(r["pass"] is True for r in rows), "of": len(rows), "front": True, "gates": {}, "heldout_over_floor": {},
                "nominal_over_floor": {}, "floor_deg": {}, "tool_stop_mm": None, "seconds": record["seconds"]}
    rep = record["report"]
    return {"params": {r["key"]: {"ratio": _ratio(r), "pass": r["pass"], "error": human_error(r)} for r in rows},
            "passed": sum(r["pass"] is True for r in rows), "of": len(rows),
            "gates": {g["id"]: g["passed"] for g in rep["gates"]},
            "heldout_over_floor": {j: v for j, v in rep["ratios"]["fitted"].items()},
            "nominal_over_floor": {j: v for j, v in rep["ratios"]["nominal"].items()},
            "floor_deg": {j: math.degrees(v) for j, v in rep["floor"].items()},
            "tool_stop_mm": None if rep["tool_stop_m"].get("fitted") is None else 1e3 * rep["tool_stop_m"]["fitted"],
            "seconds": record["seconds"]}


def summarize(records: Sequence[dict], base) -> dict:
    """Every ladder: its levels, the breaking point and the parameter(s) that broke first, and per level the seeds' verdicts."""
    out = {}
    for name, spec in LADDERS.items():
        mine = ladder_records(records, name, base)
        levels = []
        for level in spec.levels:
            cells = [r for r in mine if float(r["cell"]["level"]) == float(level)]
            metrics = [cell_metrics(r) for r in cells]
            ok = [m for m in metrics if "raised" not in m]
            worst_key, worst = None, -1.0
            for m in ok:
                for key, p in m["params"].items():
                    if p["ratio"] is not None and p["ratio"] > worst:
                        worst_key, worst = key, p["ratio"]
            levels.append({
                "level": level, "seeds": [int(r["cell"]["seed"]) for r in cells], "labels": [r["label"] for r in cells],
                "coverage": ["front" if "front" in r else "full" for r in cells],
                "recovered": [(f"{m['passed']}/{m['of']}" + ("f" if m.get("front") else "")) if "raised" not in m else f"raised in {m['routine']}"
                              for m in metrics],
                "all_recovered": bool(cells) and all("raised" not in m and m["passed"] == m["of"] for m in metrics),
                "worst": {"param": worst_key, "ratio": worst if worst_key else None},
                "gates_passed": [sum(m["gates"].values()) if "raised" not in m else 0 for m in metrics],
                "gates_failed": sorted({g for m in ok for g, v in m["gates"].items() if not v}),
                "heldout_over_floor_worst": max((max(v for v in m["heldout_over_floor"].values() if v is not None)
                                                 for m in ok if any(v is not None for v in m["heldout_over_floor"].values())), default=None),
                "tool_stop_mm_worst": max((m["tool_stop_mm"] for m in ok if m["tool_stop_mm"] is not None), default=None),
                "calibrate_s": [m["seconds"].get("calibrate") for m in ok], "total_s": [m["seconds"].get("total") for m in metrics],
                "cells": {r["label"]: m for r, m in zip(cells, metrics)}})
        out[name] = {"title": spec.title, "levels": list(spec.levels), "axis": spec.axis, "note": spec.note,
                     "breaking_point": breaking_point(mine), "by_level": levels}
        if name == "mismatch":
            out[name]["breaking_point_lumped"] = breaking_point([lumped(r) for r in mine])
            out[name]["lumped_note"] = ("the same cells held to the lumped truth a twin without the term can at best learn: each joint's Coulomb "
                                        "level plus the motor's friction (probe_motor_friction measured the board's sliding torque up by exactly "
                                        "the friction on all three joints, and the breakaway unchanged)")
    return out


def lumped(record: dict) -> dict:
    """A mismatch cell's rows re-held to the lumped truth: each Coulomb row's truth + the motor hinge's friction, its verdict again."""
    friction = float(record.get("variant", {}).get("motor_friction_nm", 0.0))
    if not friction or "error" in record:
        return record
    out = json.loads(json.dumps(record))
    for row in out["calibration"]["rows"]:
        if row["key"].endswith(".coulomb_nm") and row["pass"] is not None and row["recovered"] is not None:
            row["true"] = float(row["true"]) + friction
            row["error"] = float(row["recovered"]) - row["true"]
            limit = row["tolerance"]["value"] * (abs(row["true"]) if row["tolerance"]["kind"] == "rel" else 1.0)
            row["pass"] = abs(row["error"]) <= limit * (1.0 + 1e-9)
    return out


def plot_ladder(name: str, records: Sequence[dict], base, path: Path, tolerance_note: str = "") -> Path:
    """|error| / tolerance against the ladder's level, one line per identified parameter (its median over the seeds, each seed a dot), the
    pass band shaded below 1. Emphasis: the parameters that leave the band in colour (the first three to leave), the rest recessive gray."""
    import matplotlib  # noqa: PLC0415

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    spec = LADDERS[name]
    mine = ladder_records(records, name, base)
    levels = [lv for lv in spec.levels if any(float(r["cell"]["level"]) == float(lv) for r in mine)]
    x_of = {lv: i for i, lv in enumerate(levels)}
    series: dict[str, dict[float, list[float]]] = {}
    hollow: dict[str, dict[float, list[bool]]] = {}
    raised: dict[float, list[str]] = {}
    for r in mine:
        level = r["cell"]["level"]
        if "error" in r:
            raised.setdefault(level, []).append(r.get("routine") or "the runner")
            continue
        for row in r["calibration"]["rows"]:
            if row["pass"] is None:
                continue
            ratio = _ratio(row)
            series.setdefault(row["key"], {}).setdefault(level, []).append(np.inf if ratio is None else ratio)
            hollow.setdefault(row["key"], {}).setdefault(level, []).append("front" in r)
    # who leaves the band, and at which level first
    first_out = {}
    for key, by in series.items():
        for lv in levels:
            if any(v > 1.0 + 1e-9 for v in by.get(lv, [])):
                first_out[key] = x_of[lv]
                break
    leaving = sorted(first_out, key=lambda k: (first_out[k], -max(max(v) for v in series[k].values())))
    # nothing leaves: the two closest to their tolerance at any level are the ones to read
    loud = leaving[:3] or sorted(series, key=lambda k: -max(float(np.median(v)) for v in series[k].values()))[:2]
    fig, ax = plt.subplots(figsize=(9.6, 5.0), dpi=130)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    top = 100.0
    ax.axhspan(FLOOR_RATIO * 0.7, 1.0, color=BAND, zorder=0, lw=0)
    ax.axhline(1.0, color=INK_2, lw=1.0, zorder=1)
    ax.text(len(levels) - 0.5 + 0.02, 1.0, " tolerance", va="center", ha="left", fontsize=8.5, color=INK_2)
    ax.text(-0.45, 0.012, "inside tolerance", va="bottom", ha="left", fontsize=8.5, color=MUTED)
    def draw(key, color, lw, z, label=False):
        by = series[key]
        xs = [x_of[lv] for lv in levels if lv in by]
        med = [float(np.median(np.clip(by[lv], FLOOR_RATIO, top))) for lv in levels if lv in by]
        ax.plot(xs, med, color=color, lw=lw, zorder=z, solid_capstyle="round")
        for lv in levels:
            if lv in by:
                pts = np.clip(by[lv], FLOOR_RATIO, top)
                empty = np.asarray(hollow[key][lv], bool)
                size = 18 if label else 10
                if (~empty).any():
                    ax.scatter([x_of[lv]] * int((~empty).sum()), pts[~empty], s=size, color=color, zorder=z + 0.1, edgecolors=SURFACE, linewidths=0.8)
                if empty.any():
                    ax.scatter([x_of[lv]] * int(empty.sum()), pts[empty], s=size, facecolors=SURFACE, edgecolors=color, linewidths=1.2, zorder=z + 0.1)
        return xs[-1], med[-1]
    for key in series:
        if key not in loud:
            draw(key, QUIET, 1.0, 2)
    ends = {key: draw(key, color, 2.0, 4, label=True) for key, color in zip(loud, EMPHASIS)}
    colour_of = dict(zip(loud, EMPHASIS))
    # direct labels at the right end, spread apart in log space (a quarter decade at least) with a thin leader to each line's end
    placed, gap = [], 0.25
    for key in sorted(ends, key=lambda k: ends[k][1]):
        y = math.log10(ends[key][1])
        if placed and y < placed[-1][1] + gap:
            y = placed[-1][1] + gap
        placed.append((key, y))
    over = placed[-1][1] - math.log10(top) if placed else 0.0
    if over > 0:
        placed = [(k, y - over) for k, y in placed]
    for key, y in placed:
        x_end, y_end = ends[key]
        ax.annotate("", (x_end, y_end), xytext=(x_end + 0.12, 10 ** y), textcoords="data",
                    arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 0.6, "shrinkA": 0, "shrinkB": 3}, annotation_clip=False)
        ax.plot([x_end + 0.12, x_end + 0.22], [10 ** y, 10 ** y], color=colour_of[key], lw=2.4, solid_capstyle="round", clip_on=False, zorder=6)
        ax.text(x_end + 0.25, 10 ** y, key, va="center", ha="left", fontsize=8.5, color=INK, clip_on=False)
    for lv, who in raised.items():
        ax.scatter([x_of[lv]], [top * 0.8], marker="x", s=60, color=INK, zorder=5)
        ax.annotate(f"raised ({len(who)}): {who[0]}", (x_of[lv], top * 0.8), xytext=(6, -2), textcoords="offset points", fontsize=8, color=INK)
    ax.set_yscale("log")
    ax.set_ylim(FLOOR_RATIO * 0.7, top * 1.3)
    ax.set_xlim(-0.5, len(levels) - 0.5)
    ax.set_xticks(range(len(levels)), [f"{lv:g}" for lv in levels])
    ax.set_xlabel(f"level ({spec.axis})", color=INK_2, fontsize=9.5)
    ax.set_ylabel("|error| / tolerance  (log; 1 = on the tolerance)", color=INK_2, fontsize=9.5)
    ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(QUIET)
    ax.tick_params(colors=INK_2, labelsize=8.5)
    broken = breaking_point(mine)
    head = (f"breaks at {broken['level']:g}: {', '.join(broken['params'][:3])}" if broken["level"] is not None
            else "no parameter leaves its tolerance at any level run")
    seeds = sorted({int(r["cell"]["seed"]) for r in mine})
    import textwrap  # noqa: PLC0415

    ax.set_title(f"{spec.title}: {head}", loc="left", fontsize=11, color=INK, pad=30)
    note = (f"{len(series)} identified parameters, the median of {len(seeds)} seeds (each a dot; hollow = the front pass only, the routines "
            f"before the dynamics). Colour = {'the first to leave the band' if leaving else 'the two closest to their tolerance'}, gray = the rest"
            f"{(' (' + str(len(leaving) - 3) + (' more leaves)' if len(leaving) == 4 else ' more leave)')) if len(leaving) > 3 else ''}. {tolerance_note}")
    ax.text(0.0, 1.015, textwrap.fill(note, 150), transform=ax.transAxes, fontsize=7.8, color=MUTED, va="bottom", linespacing=1.3)
    fig.tight_layout()
    fig.subplots_adjust(right=0.80)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def table_markdown(summary: dict) -> str:
    lines = ["| ladder | levels | first fail level | first fail parameter(s) (seeds) | per level: recovered on each seed | worst held-out / floor | worst tool p95 |",
             "|---|---|---|---|---|---|---|"]
    for name, lad in summary.items():
        bp = lad["breaking_point"]
        first = "none" if bp["level"] is None else f"{bp['level']:g}"
        who = "-" if bp["level"] is None else "; ".join(f"{k} ({len(bp['seeds'][k])}/{bp['of']})" for k in bp["params"][:4]) + \
            (f"; +{len(bp['params']) - 4} more" if len(bp["params"]) > 4 else "")
        per = "; ".join(f"{lv['level']:g}: {' '.join(lv['recovered'])}" for lv in lad["by_level"] if lv["seeds"])
        ho = max((lv["heldout_over_floor_worst"] for lv in lad["by_level"] if lv["heldout_over_floor_worst"] is not None), default=None)
        tool = max((lv["tool_stop_mm_worst"] for lv in lad["by_level"] if lv["tool_stop_mm_worst"] is not None), default=None)
        lines.append(f"| {name} | {', '.join(f'{v:g}' for v in lad['levels'])} | {first} | {who} | {per} | "
                     f"{'-' if ho is None else f'{ho:.2f}x'} | {'-' if tool is None else f'{tool:.3f} mm'} |")
    return "\n".join(lines)


def build_report(out: Path) -> dict:
    """ladders.json (every number), ladders.md (the table), plots/<ladder>.png, from the cells written under ``out``."""
    out = Path(out)
    full = {r["label"]: r for r in read_records(out)}
    front = {r["label"]: r for r in read_records(out, "front")}
    records = list(full.values()) + [r for label, r in front.items() if label not in full]
    agreement = front_check(full, front)
    base = _base()
    summary = summarize(records, base)
    plots = {}
    for name in LADDERS:
        if ladder_records(records, name, base):
            note = "Ruler: world.json's truth" + (" moved by far_truth" if name == "truth" else "") + \
                   (" (the output-side friction; the twin can at best lump the motor's in)" if name == "mismatch" else "") + "."
            plots[name] = str(plot_ladder(name, records, base, out / "plots" / f"{name}.png", note))
    walls = [r["seconds"]["calibrate"] for r in full.values() if "error" not in r]
    totals = [r["seconds"]["total"] for r in full.values() if "seconds" in r]
    doc = {"schema": SCHEMA + "#summary", "written": dt.datetime.now().isoformat(timespec="seconds"), "cells": len(records),
           "full_cells": len(full), "front_cells": len(front), "front_check": agreement,
           "seeds": list(SEEDS), "ladders": summary, "plots": plots,
           "wall_s": {"calibrate_median": _median(walls), "calibrate_range": [min(walls, default=None), max(walls, default=None)],
                      "cell_total_median": _median(totals)}}
    (out / "ladders.json").write_text(json.dumps(doc, indent=1, default=_plain))
    (out / "ladders.md").write_text(table_markdown(summary) + "\n")
    (out / "index.html").write_text(index_html(doc, out))
    print(table_markdown(summary))
    print(json.dumps(doc["wall_s"]), "\n" + "\n".join(plots.values()))
    return doc


def _esc(text) -> str:
    import html  # noqa: PLC0415

    return html.escape(str(text))


def _table(head: Sequence[str], rows: Iterable[Sequence]) -> str:
    return ("<div class=wrap><table><thead><tr>" + "".join(f"<th>{_esc(h)}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td class=n>{_esc(c)}</td>" for c in row) + "</tr>" for row in rows) + "</tbody></table></div>")


def probe_tables_html(out: Path) -> str:
    """The probes as tables: dead_band per torque-noise multiplier (worst |error| / tolerance over seeds and joints, four estimators), the
    velocity-noise estimate against the noise drawn, the mismatch world measured, the dynamics fit with the rest-only velocity noise."""
    html_parts = []
    path = out / "probes" / "dead_band.json"
    if path.exists():
        rows = json.loads(path.read_text())
        by = {}
        for r in rows:
            by.setdefault(r["multiplier"], []).append(r)
        def worst(rs, k):
            vals = [x[k]["err_over_tol"] for x in rs]
            return "not observable" if any(v is None for v in vals) else f"{max(vals):.2f}"
        body = [(f"{m:g}x", f"{min(x['sigma_measured_mnm'] for x in rs):.0f}-{max(x['sigma_measured_mnm'] for x in rs):.0f}", worst(rs, "committed"),
                 worst(rs, "mean5"), worst(rs, "mean9"), worst(rs, "adaptive"),
                 f"{min(x['adaptive']['window'] for x in rs)}-{max(x['adaptive']['window'] for x in rs)}") for m, rs in sorted(by.items())]
        html_parts.append("<h2>Probe: the held reversal's dead band against torque noise</h2><p class=m>servo.backlash_reversal_held's own recordings "
                          "(stream and run ids of the torque ladder's cells), 3 seeds x 3 joints a row; worst |error| / tolerance (1 = on the 10 % "
                          "tolerance). committed = dead_band at 0.7 of the 70 mN.m cap, as on main; meanN = the torque smoothed over N samples first; "
                          "adaptive = the window the trace's own measured noise asks (z 4.5 on the threshold, at most 31).</p>"
                          + _table(["torque noise", "measured sigma mN.m", "committed", "mean 5", "mean 9", "adaptive", "adaptive window"], body))
    path = out / "probes" / "reading_noise.json"
    if path.exists():
        rows = json.loads(path.read_text())
        body = [(f"{r['multiplier']:g}x", f"{r['velocity_true'] * 1e3:.2f}", f"{r['velocity_read'] * 1e3:.2f}",
                 "-" if r["velocity_read_over_true"] is None else f"{r['velocity_read_over_true']:.2f}x",
                 "-" if r["velocity_quiet"] is None else f"{r['velocity_quiet'] * 1e3:.3f}", f"{r['torque_true'] * 1e3:.1f}", f"{r['torque_read'] * 1e3:.1f}")
                for r in rows]
        html_parts.append("<h2>Probe: the readings' noise as the dynamics fit estimates it</h2><p class=m>servo.dynamics_regression's 50 train "
                          "recordings (its stream and run ids), the velocity noise x multiplier and the rest at 1x; reading_noise() is the rig's "
                          "(1.4826 MAD of second differences / sqrt 6), rests only = 1.4826 MAD of the velocity where the host holds.</p>"
                          + _table(["velocity noise", "drawn 1e-3 rad/s", "reading_noise()", "read / drawn", "rests only", "torque drawn mN.m",
                                    "torque read mN.m"], body))
    path = out / "probes" / "motor_friction.json"
    if path.exists():
        rows = json.loads(path.read_text())
        zero = {r["can"]: r for r in rows if r["motor_friction_mnm"] == 0}
        body = [(r["motor_friction_mnm"], f"CAN {r['can']}", f"{r['static_truth_mnm']:.0f}", "-" if r["static_read_mnm"] is None else f"{r['static_read_mnm']:.1f}",
                 f"{r['sliding_read_mnm'] - zero[r['can']]['sliding_read_mnm']:+.1f}", " ".join(f"{v:g}" for v in r["pushes"])) for r in rows]
        html_parts.append("<h2>Probe: the mismatch ladder's world, measured noise-free</h2><p class=m>servo.breakaway_two_sided's own play and fit, "
                          "and the board torque that keeps the joint sliding at 0.2 rad/s both ways, with the motor hinge's friction; the sliding "
                          "column is the change from no friction.</p>"
                          + _table(["motor friction mN.m", "joint", "breakaway truth mN.m", "breakaway read mN.m", "sliding torque change mN.m",
                                    "the six pushes mN.m"], body))
    for path in sorted((out / "probes").glob("dynamics_fix-s*.json")):
        doc = json.loads(path.read_text())
        body = [(r["key"], "-" if r["committed_err_over_tol"] is None else f"{r['committed_err_over_tol']:.2f}", f"{r['fixed_err_over_tol']:.2f}")
                for r in doc["rows"]]
        v = doc["velocity_sigma"]
        html_parts.append(f"<h2>Probe: the dynamics fit with the rests' velocity noise (seed {doc['seed']})</h2><p class=m>the very recordings the "
                          f"baseline cell's dynamics routine read; replays' velocity noise {v['quiet'] * 1e3:.3f}e-3 rad/s (rests only) instead of "
                          f"{v['reading_noise'] * 1e3:.2f}e-3 (reading_noise()), drawn {v['true'] * 1e3:.2f}e-3; |error| / tolerance.</p>"
                          + _table(["parameter", "as committed", "rests' velocity noise"], body))
    return "".join(html_parts)


def index_html(doc: dict, out: Path) -> str:
    """One page over the outputs: the ladder table, the six plots, the probes' tables (when written). Relative links only."""
    rows = []
    for name, lad in doc["ladders"].items():
        bp = lad["breaking_point"]
        first = "none" if bp["level"] is None else f"{bp['level']:g}"
        who = "&mdash;" if bp["level"] is None else "<br>".join(f"<code>{_esc(k)}</code> ({len(bp['seeds'][k])}/{bp['of']} seeds)" for k in bp["params"][:5])
        per = "<br>".join(f"{lv['level']:g}: {_esc(' '.join(lv['recovered']))}" for lv in lad["by_level"] if lv["seeds"])
        ho = max((lv["heldout_over_floor_worst"] for lv in lad["by_level"] if lv["heldout_over_floor_worst"] is not None), default=None)
        tool = max((lv["tool_stop_mm_worst"] for lv in lad["by_level"] if lv["tool_stop_mm_worst"] is not None), default=None)
        rows.append(f"<tr><td><b>{_esc(name)}</b><br><span class=m>{_esc(lad['title'])}</span></td><td>{_esc(', '.join(f'{v:g}' for v in lad['levels']))}"
                    f"<br><span class=m>{_esc(lad['axis'])}</span></td><td class=n>{first}</td><td>{who}</td><td class=s>{per}</td>"
                    f"<td class=n>{'&mdash;' if ho is None else f'{ho:.2f}x'}</td><td class=n>{'&mdash;' if tool is None else f'{tool:.3f} mm'}</td></tr>")
    plots = "".join(f"<figure><img src='plots/{_esc(Path(path).name)}' alt='{_esc(name)} ladder: error over tolerance against level'>"
                    f"<figcaption>{_esc(doc['ladders'][name]['note'])}</figcaption></figure>" for name, path in doc["plots"].items())
    probes = probe_tables_html(out)
    wall = doc["wall_s"]
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Wrist one-click stress</title><style>
:root{{--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a}}}}
:root[data-theme=dark]{{--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto}} h1{{font-size:20px;margin:0 0 4px}} .m{{color:var(--muted);font-size:12px}}
table{{border-collapse:collapse;width:100%;background:var(--surface);font-size:13px}} td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
.n{{font-variant-numeric:tabular-nums;white-space:nowrap}} .s{{font-size:12px;color:var(--ink2)}} .wrap{{overflow-x:auto}}
figure{{margin:18px 0;background:var(--surface);padding:8px}} img{{max-width:100%;height:auto}} figcaption{{color:var(--ink2);font-size:12px}}
pre{{white-space:pre-wrap;word-break:break-word;font-size:11px;background:var(--surface);padding:8px;max-height:320px;overflow:auto}}
</style></head><body><main>
<h1>The wrist's one-click, stress-tested</h1>
<p class=m>{doc['cells']} cells, seeds {', '.join(map(str, doc['seeds']))}; written {_esc(doc['written'])} by tools/stress_wrist.py report.
Median calibrate {wall['calibrate_median']} s (range {wall['calibrate_range'][0]}-{wall['calibrate_range'][1]} s), whole cell median {wall['cell_total_median']} s.
A level breaks when any seed misses any identified value's tolerance (the rig's, world.json's truth).</p>
<div class=wrap><table><thead><tr><th>ladder</th><th>levels</th><th>first fail</th><th>first fail parameter(s)</th><th>recovered per seed</th><th>worst held-out / floor</th><th>worst tool p95</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
{plots}
{probes}
</main></body></html>"""


def front_check(full: Mapping[str, dict], front: Mapping[str, dict]) -> dict:
    """Where a cell ran both whole and as a front pass, the front parameters' values must be the same (FrontRig's claim): the largest
    difference over every such cell and parameter, and how many cells were compared."""
    worst, compared = 0.0, 0
    for label, f in front.items():
        g = full.get(label)
        if g is None or "error" in g or "error" in f:
            continue
        mine = {r["key"]: r["recovered"] for r in f["calibration"]["rows"] if r["pass"] is not None}
        theirs = {r["key"]: r["recovered"] for r in g["calibration"]["rows"]}
        for key, value in mine.items():
            if value is not None and theirs.get(key) is not None:
                worst = max(worst, abs(value - theirs[key]))
        compared += 1
    return {"cells_compared": compared, "largest_difference": worst}


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else 0.5 * (values[mid - 1] + values[mid])


# --- probes: the known risks' estimators on the very recordings a cell's routine reads (evidence for a fix, never a change to a routine) ---


def _world(twin) -> tuple[dict, dict]:
    """(the world's values at the committed truth, the description's nominal values), as RigRunner.calibrate builds them at truth_offset 1."""
    rig = twin.runner.rig
    nominal = rig.nominal_values()
    truth = json.loads((REPO / "sysid" / "examples" / NAME / "world.json").read_text())["truth"]
    world = {**nominal, **truth}
    world.update(rig.derived(world))
    return world, nominal


def smoothed(series, window: int):
    """A centred moving average over ``window`` samples (odd; 1 = the series), the ends averaged over what exists."""
    import numpy as np  # noqa: PLC0415

    x = np.asarray(series, float)
    if window <= 1:
        return x
    kernel = np.ones(int(window))
    return np.convolve(x, kernel, mode="same") / np.convolve(np.ones_like(x), kernel, mode="same")


def torque_sigma(tau) -> float:
    """The torque reading's white noise from the trace itself: 1.4826 MAD of its first differences / sqrt(2) (holds and crossings are slow
    against 100 Hz, so a difference is mostly noise)."""
    import numpy as np  # noqa: PLC0415

    d = np.diff(np.asarray(tau, float))
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / math.sqrt(2.0))


def adaptive_window(sigma_nm: float, threshold_nm: float, z: float = 4.5, longest: int = 31) -> int:
    """The fewest samples a moving average needs so the in-gap torque (0 +- noise) stays ``z`` of its smoothed sigma inside the threshold:
    the false-crossing rate, not the flank, is what breaks dead_band (a flank sample below the threshold is only ignored)."""
    need = (z * sigma_nm / threshold_nm) ** 2
    window = max(1, int(math.ceil(need)))
    window += 1 - window % 2
    return min(window, longest)


def probe_dead_band(multipliers=(0, 1, 2, 3, 5, 10), seeds=SEEDS, workers: int = 4) -> list[dict]:
    """servo.backlash_reversal_held's recordings at the torque ladder's noise (stream "routine:servo.backlash_reversal_held", the same run ids:
    the very traces the torque cells' first routine reads), fitted four ways: the routine as committed (dead_band at 0.7 of the cap), and
    dead_band on the torque smoothed over 5 and 9 samples and over the window the trace's own measured noise asks (adaptive_window)."""
    import importlib  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415
    import sim2real  # noqa: PLC0415

    twin = sim2real.Twin.load(NAME, workers=workers)
    wr = importlib.import_module(RIG_MODULE)
    from bam_fb_test_rig.backlash import dead_band  # noqa: PLC0415

    rig, base = twin.runner.rig, twin.noise()
    world, nominal = _world(twin)
    runs = list(wr.BacklashReversal().runs(dict(nominal)))
    out = []
    for m in multipliers:
        for seed in seeds:
            noise = base.with_terms(torque_noise_nm=float(m) * base.torque_noise_nm, seed=int(seed)) if m else \
                base.with_terms(torque_noise_nm=0.0, seed=int(seed))
            measured = rig.measure(runs, world, noise, "routine:servo.backlash_reversal_held", workers=workers)
            for rec in measured.values():
                key = f"{wr.INSTANCE[rec['can']]}.backlash_rad"
                truth, tol = world[key], 0.10 * world[key]
                threshold = wr.DEAD_BAND_THRESHOLD_FRACTION * rec["cap_nm"]
                sigma = torque_sigma(rec["tau"])
                row = {"multiplier": m, "seed": int(seed), "key": key, "truth_arcmin": truth / ARCMIN, "cap_mnm": rec["cap_nm"] * 1e3,
                       "threshold_mnm": threshold * 1e3, "sigma_measured_mnm": sigma * 1e3, "sigma_true_mnm": noise.effective()["torque_noise_nm"] * 1e3}
                try:
                    found = wr.BacklashReversal().fit({"r": rec}, dict(nominal), None)[key].value
                    row["committed"] = {"arcmin": found / ARCMIN, "err_over_tol": abs(found - truth) / tol}
                except ValueError as exc:
                    row["committed"] = {"arcmin": None, "err_over_tol": None, "why": str(exc)[:120]}
                for name, window in (("mean5", 5), ("mean9", 9), ("adaptive", adaptive_window(sigma, threshold))):
                    band = dead_band(rec["q"], smoothed(rec["tau"], window), threshold_nm=threshold,
                                     mesh_stiffness_nm_per_rad=wr.MESH_STIFFNESS_NM_PER_RAD)
                    value = band.backlash_rad
                    row[name] = {"window": window, "arcmin": None if value is None else value / ARCMIN,
                                 "err_over_tol": None if value is None else abs(value - truth) / tol}
                out.append(row)
                print(json.dumps(row, default=_plain), flush=True)
    return out


def quiet_rows(rec: dict, hold_s: float = 0.3):
    """The samples where the host commanded a hold (zero target speed, the target unchanged for ``hold_s``): the joint rests, so its
    reported velocity is its noise (sim2real's tool_error_at_stops rule for a rest, without the stride)."""
    import numpy as np  # noqa: PLC0415

    target = np.asarray(rec["commands"]["board_target"], float)
    qd_target = np.asarray(rec["commands"]["qd_target"], float)
    still = np.isfinite(target) & (np.abs(qd_target) < 1e-9)
    ticks = int(round(hold_s / 0.01))
    steady = np.convolve(np.r_[0.0, np.abs(np.diff(np.nan_to_num(target)))] < 1e-12, np.ones(ticks), mode="full")[: target.size] >= ticks
    return np.flatnonzero(still & steady)


def probe_reading_noise(multipliers=(0, 1, 3, 10), seed: int = SEEDS[0], workers: int = 4) -> list[dict]:
    """servo.dynamics_regression's train recordings (its stream and run ids, the host's frame at the true zeros) at the velocity noise x
    multiplier (the rest at 1x): what the rig's reading_noise() reads for the velocity and the torque against the noise drawn, and what a
    rest-only estimate (quiet_rows: 1.4826 MAD of the velocity where the host holds) reads."""
    import importlib  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415
    import sim2real  # noqa: PLC0415

    twin = sim2real.Twin.load(NAME, workers=workers)
    wr = importlib.import_module(RIG_MODULE)
    rig, base = twin.runner.rig, twin.noise()
    world, nominal = _world(twin)
    runs = list(wr.Dynamics().runs({**nominal, **{k: world[k] for k in world if k.endswith(".zero_offset_rad")}}))
    out = []
    for m in multipliers:
        noise = base.with_terms(velocity_noise_rad_s=float(m) * base.velocity_noise_rad_s, seed=int(seed))
        began = time.monotonic()
        measured = rig.measure(runs, world, noise, "routine:servo.dynamics_regression", workers=workers)
        sig = wr.reading_noise(measured)
        quiet = np.concatenate([np.asarray(r["qd"], float)[quiet_rows(r)] for r in measured.values()])
        quiet_sigma = float(1.4826 * np.median(np.abs(quiet - np.median(quiet)))) if quiet.size else None
        by_family = {}
        for name, r in measured.items():
            family = name.split("/", 1)[1].split("-", 1)[0]
            by_family.setdefault(family, []).append(r)
        row = {"multiplier": m, "seed": int(seed), "runs": len(measured), "seconds": round(time.monotonic() - began, 1),
               "velocity_true": noise.effective()["velocity_noise_rad_s"], "velocity_read": sig["qd"],
               "velocity_read_over_true": sig["qd"] / noise.effective()["velocity_noise_rad_s"] if m else None,
               "velocity_quiet": quiet_sigma, "quiet_samples": int(quiet.size),
               "torque_true": noise.effective()["torque_noise_nm"], "torque_read": sig["tau"],
               "velocity_read_by_family": {f: wr.reading_noise({str(i): r for i, r in enumerate(rs)})["qd"] for f, rs in sorted(by_family.items())}}
        out.append(row)
        print(json.dumps(row, default=_plain), flush=True)
    return out


def _sliding(wr, plant, axis: int, speed_rad_s: float, seconds: float, cap_nm: float) -> float:
    """The board torque that keeps one joint sliding at a steady speed, both ways (half the difference: the load cancels): the joint's
    sliding friction + viscous x speed, as the board reads it. A WristDrive under the position loop, the target ramping at the speed."""
    import numpy as np  # noqa: PLC0415

    drive = wr.WristDrive(plant, axis)
    means = []
    for direction in (+1, -1):
        target = drive.position_rad()
        samples = []
        ticks = int(round(seconds / wr.PERIOD_S))
        for k in range(ticks):
            target += direction * speed_rad_s * wr.PERIOD_S
            drive.command(target, direction * speed_rad_s, cap_nm)
            drive.tick()
            if k > ticks // 3:
                samples.append(drive.torque_nm())
        means.append(float(np.mean(samples)))
        wr.settle(drive, 0.5, cap_nm)
    return 0.5 * (means[0] - means[1])


def probe_motor_friction(levels_mnm=(0, 10, 20, 40), workers: int = 1) -> list[dict]:
    """What the mismatch ladder's world is, measured on it noise-free (a seed given, so motor_friction's patch applies): per joint, the
    breakaway servo.breakaway_two_sided reads (its own play and fit, the description's priors in the run) and the sliding torque at
    0.2 rad/s both ways; against the committed truth's static and Coulomb levels. The lumped truth a twin without the term can at best
    hold is these, not world.json's output-side values."""
    import importlib  # noqa: PLC0415

    import sim2real  # noqa: PLC0415

    twin = sim2real.Twin.load(NAME, workers=1)
    wr = importlib.import_module(RIG_MODULE)
    world, nominal = _world(twin)
    runs = {r.spec["can"]: r for r in wr.Breakaway().runs({**nominal, **{k: world[k] for k in world if k.endswith(".backlash_rad")}})}
    out = []
    for level in levels_mnm:
        patch = motor_friction(level * 1e-3) if level else contextlib.nullcontext()
        with patch:
            for can in wr.MOVING:
                i = wr.INSTANCE[can]
                rec = wr.play({"kind": "breakaway", "spec": runs[can].spec, "values": dict(world), "noise": {}, "seed": [0, 0, can]})
                try:
                    static = wr.Breakaway().fit({"r": rec}, dict(nominal), None)[f"{i}.static_friction_nm"].value
                except ValueError as exc:
                    static = None
                    print(f"CAN {can} at {level} mN.m: {exc}", flush=True)
                plant = wr.build_plant(dict(world), wr._rest_cad(), noise={}, seed=[0, 1, can])
                sliding = _sliding(wr, plant, wr.CANS.index(can), 0.2, 2.0, 1.0)
                row = {"motor_friction_mnm": level, "can": can, "static_truth_mnm": world[f"{i}.static_friction_nm"] * 1e3,
                       "static_read_mnm": None if static is None else static * 1e3,
                       "coulomb_truth_mnm": world[f"{i}.coulomb_nm"] * 1e3,
                       "viscous_at_speed_mnm": world[f"{i}.damping_nm_s_rad"] * 0.2 * 1e3, "sliding_read_mnm": sliding * 1e3,
                       "pushes": [round(p["cap_nm"] * 1e3, 1) for p in rec["pushes"]]}
                out.append(row)
                print(json.dumps(row, default=_plain), flush=True)
    return out


def quiet_velocity_sigma(measured: Mapping[str, dict]) -> float | None:
    """The velocity reading's white noise from the rests only (quiet_rows): 1.4826 MAD of the board's velocity where the host holds."""
    import numpy as np  # noqa: PLC0415

    quiet = np.concatenate([np.asarray(r["qd"], float)[quiet_rows(r)] for r in measured.values()])
    return float(1.4826 * np.median(np.abs(quiet - np.median(quiet)))) if quiet.size else None


def probe_dynamics_fix(seed: int = SEEDS[0], workers: int = 4, out: Path | None = None) -> dict:
    """servo.dynamics_regression's fit again on the very recordings a baseline cell's dynamics routine read (its stream, run ids and the
    values the three routines before it found, from that cell's record), with the replays' velocity noise taken from the rests
    (quiet_velocity_sigma) instead of reading_noise()'s second differences; the rows against the truth beside the cell's own."""
    import importlib  # noqa: PLC0415

    import sim2real  # noqa: PLC0415
    from sim2real import rig as seam  # noqa: PLC0415

    out = Path(out or default_out())
    # the values the first three routines found: the whole run's record, or the front pass's (the same to the bit: front_check)
    whole, front = out / "cells" / f"baseline-s{seed}.json", out / "front" / f"baseline-s{seed}.json"
    cell = json.loads((whole if whole.exists() else front).read_text())
    twin = sim2real.Twin.load(NAME, workers=workers)
    wr = importlib.import_module(RIG_MODULE)
    rig, base = twin.runner.rig, twin.noise()
    world, nominal = _world(twin)
    values = dict(nominal)
    for step in cell["calibration"]["routines"][:3]:
        values.update({k: float(v) for k, v in step["found"].items() if v is not None})
    noise = base.with_terms(seed=int(seed))
    runs = list(wr.Dynamics().runs(dict(values)))
    began = time.monotonic()
    measured = rig.measure(runs, world, noise, "routine:servo.dynamics_regression", workers=workers)
    original = wr.reading_noise
    read = original(measured)
    quiet = quiet_velocity_sigma(measured)

    def fixed(recordings):
        sig = original(recordings)
        sig["qd"] = quiet
        return sig

    wr.reading_noise = fixed
    try:
        hidden = seam._hidden()
        with hidden.sealed():
            found = wr.Dynamics().fit(measured, dict(values), seam.TwinHandle(rig, workers))
    finally:
        wr.reading_noise = original
    params = {p.key: p for p in rig.parameters()}
    theirs = {}
    if whole.exists():
        theirs = {r["key"]: r["recovered"] for r in json.loads(whole.read_text())["calibration"]["rows"]}
    rows = []
    for key in wr.Dynamics.identifies:
        p, truth = params[key], world[key]
        kind, tol = p.tolerance
        limit = tol if kind == "abs" else tol * abs(truth)
        mine = float(found[key].value)
        committed = theirs.get(key)
        rows.append({"key": key, "truth": truth, "committed": committed, "fixed": mine,
                     "committed_err_over_tol": None if committed is None else abs(committed - truth) / limit,
                     "fixed_err_over_tol": abs(mine - truth) / limit})
    doc = {"seed": int(seed), "velocity_sigma": {"true": noise.effective()["velocity_noise_rad_s"], "reading_noise": read["qd"], "quiet": quiet},
           "seconds": round(time.monotonic() - began, 1), "rows": rows}
    print(json.dumps(doc, indent=1, default=_plain), flush=True)
    return doc


# --- the CLI -----------------------------------------------------------------------------------------------------------------------------


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("cell", help="run one cell in this process")
    one.add_argument("ladder", choices=list(LADDERS))
    one.add_argument("level", type=float)
    one.add_argument("seed", type=int)
    one.add_argument("--workers", type=int, default=6)
    one.add_argument("--out", type=Path, default=None)
    one.add_argument("--front", action="store_true", help="only the routines before the dynamics (FrontRig)")
    many = sub.add_parser("run", help="run every cell of the ladders (resumes)")
    many.add_argument("--ladders", nargs="*", default=None, choices=list(LADDERS))
    many.add_argument("--parallel", type=int, default=3)
    many.add_argument("--workers", type=int, default=6)
    many.add_argument("--out", type=Path, default=None)
    many.add_argument("--no-reuse", action="store_true")
    many.add_argument("--only", nargs="*", default=None, help="labels to run, in this order (e.g. torque-10-s20261112)")
    many.add_argument("--exclude-baseline", action="store_true", help="leave the 1x runs to another process (the slow test writes them)")
    many.add_argument("--front", action="store_true", help="only the routines before the dynamics, every cell (FrontRig)")
    rep = sub.add_parser("report", help="the ladder table and one plot per ladder, from the cells written")
    rep.add_argument("--out", type=Path, default=None)
    pro = sub.add_parser("probe", help="the known risks' estimators on a routine's own recordings (dead_band, reading_noise)")
    pro.add_argument("which", choices=["dead_band", "reading_noise", "motor_friction", "dynamics_fix"])
    pro.add_argument("--seed", type=int, default=SEEDS[0])
    pro.add_argument("--multipliers", type=float, nargs="*", default=None, help="dead_band: the torque-noise multipliers (default 0 1 2 3 5 10)")
    pro.add_argument("--name", default=None, help="the probe's file name under probes/ (default: the probe's)")
    pro.add_argument("--workers", type=int, default=4)
    pro.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = args.out or default_out()
    if args.command == "cell":
        level = int(args.level) if float(args.level).is_integer() else args.level
        if args.front:
            record = run_front_cell(Cell(args.ladder, level, args.seed), workers=args.workers, out=out)
            print(record.get("summary") or record.get("traceback"), flush=True)
            return 0 if "error" not in record else 3
        record = run_cell(Cell(args.ladder, level, args.seed), workers=args.workers, out=out)
        print(record.get("summary") or record.get("traceback"), flush=True)
        return 0 if "error" not in record else 3
    if args.command == "run":
        cells = plan(args.ladders)
        base = _base()
        if args.only:
            # in the order given: a budget-cut run spends its full cells where the front pass cannot answer
            by_label = {c.label(base): c for c in cells}
            cells = [by_label[label] for label in args.only if label in by_label]
        if args.exclude_baseline:
            cells = [c for c in cells if not c.label(base).startswith("baseline-")]
        run_cells(cells, out=out, parallel=args.parallel, workers=args.workers, reuse=not args.no_reuse, front=args.front)
        return 0
    if args.command == "report":
        build_report(out)
        return 0
    if args.command == "probe":
        if args.which == "dynamics_fix":
            rows = probe_dynamics_fix(seed=args.seed, workers=args.workers, out=out)
            name = f"dynamics_fix-s{args.seed}"
        elif args.which == "dead_band" and args.multipliers:
            rows = probe_dead_band(multipliers=tuple(args.multipliers), workers=args.workers)
            name = args.name or "dead_band_fine"
        else:
            rows = {"dead_band": probe_dead_band, "reading_noise": probe_reading_noise, "motor_friction": probe_motor_friction}[args.which](workers=args.workers)
            name = args.name or args.which
        (out / "probes").mkdir(parents=True, exist_ok=True)
        (out / "probes" / f"{name}.json").write_text(json.dumps(rows, indent=1, default=_plain))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
