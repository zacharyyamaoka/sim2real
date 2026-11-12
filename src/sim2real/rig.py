"""The one-click seam: what a rig supplies so ``Twin.load(name).calibrate(on="sim", truth="sealed")`` runs its whole calibration sequence
against a sealed hidden truth, and ``eval_twin()`` scores the fitted twin held out over the sim's own repeat floor (Zach, 2026-11-11).

    import sim2real
    twin = sim2real.Twin.load("ur_wrist_test_rig")        # sysid/examples/ur_wrist_test_rig: description.json, world.json, rig.py
    fitted = twin.calibrate(on="sim", truth="sealed")      # every routine of the rig's sequence, in order; a NEW, fitted twin
    fitted.calibration_.summary()                          # per parameter: truth / recovered / error / tolerance / pass, and what is not identified
    fitted.eval_twin().summary()                           # held-out error / floor per joint, the tool at stops, the gates
    fitted.result().display()                              # the typed tree as one page (sim2real.result)
    twin.calibrate(noise=twin.noise().at(3.0))             # the stress lane: every noise term x3 (or .with_terms(torque_noise_nm=...))

Zach: "my goal is to just export then have the one click .calibrate() and then just see the results. So get that fully working in sim first,
and once you can prove that the entire routine recovers perfectly (and you stress test it with different levels of noise) then we run that
routine in reality." His success rule: a routine recovers the hidden values to within a tolerance.

The contract (docs/one-click-seam.md, frozen by tests/test_one_click_seam.py on a toy rig) is what a rig must supply, as a ``RigBackend``:
its parameters (each identified by a cards.calibration ROUTINES id with a tolerance, or said why not), its 1x noise (measured on the real
rig, every number with its source), its calibration sequence (each routine: the runs it plays, given what earlier routines found, and a fit
from the measurements and the values so far), its held-out runs, and three plays of its own MuJoCo twin: ``measure`` (the world at given
values, with the noise drawn), ``predict`` (the twin at given values replaying each recording's own commands, noise-free) and ``score``.

WHY a second runner beside twin.SimRunner, and not a rewrite of it (2026-11-11): SimRunner hosts ONE servo through sysid's five-function
pipeline (plan, RealWorld, identify, score, assemble), proven on the pendulum tracer; a rig is a chain of servos calibrated by a SEQUENCE of
routines, each using what the earlier ones found (homing corrects its stall by the backlash the reversal measured; the dynamics run in the
homed frame). The pendulum keeps its proven path untouched; a rig ships rig.py beside its description and the Twin picks this runner.

WHY the guards here and never in a rig (scikit-learn's estimator contract, the API prior-art note): the runner alone reads the truth
(world.json, outside the seal), every fit runs inside sysid.world.sealed(), the ruler is world.json's (moved only by the noise model's
truth_offset, never by move_truth), and eval_twin refuses a run any routine measured.

Layer: like twin.py, right of every folder (tests/test_layers.py); a rig's module is an app folder (sysid/examples/<name>/rig.py), imported
lazily from this checkout, so nothing here imports bam_ws.
"""

from __future__ import annotations

import dataclasses
import importlib
import math
import sys
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol

REPO = Path(__file__).resolve().parents[2]
SEAM = "sim2real.rig/1"
TOOL_GATE_M = 1e-3  # Zach, 2026-11-11: "we certainly need final tool error sub 1 mm" (sim2real.result.TOOL_GATE_MM, the same gate)


# --- the noise model ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NoiseModel:
    """Explicit, seeded and set by level. The terms are their 1x values (the rig measures them on the real hardware and says where each
    came from); ``level`` multiplies every term at once, ``with_terms`` sets one (a stress lane's single-term sweep), ``seed`` draws.

    encoder_quantum_rad    the reported position's step (a moteus output position, rounded)
    encoder_noise_rad      white noise on the reported position, before rounding
    velocity_noise_rad_s   white noise on the reported velocity
    torque_noise_nm        white noise on the reported torque (the board's q-current x Kt)
    torque_disturbance_nm  white noise on the torque a commanded board APPLIES, held over each host period (the current loop's own noise
                           and whatever else moves a joint differently between two runs of one tape: what a real repeat floor is made of)
    period_overrun_s       the host loop's mean overrun past its planned tick (each tick overruns by an exponential draw of this mean)
    latency_jitter_s       each command's extra latency past the plant's own command delay (uniform on [0, this])
    truth_offset           how far the hidden truth sits from nominal, as a multiple of world.json's offset (1: world.json; 0: nominal);
                           NOT scaled by level, and the ruler follows it (``ruler``)
    """

    encoder_quantum_rad: float = 0.0
    encoder_noise_rad: float = 0.0
    velocity_noise_rad_s: float = 0.0
    torque_noise_nm: float = 0.0
    torque_disturbance_nm: float = 0.0
    period_overrun_s: float = 0.0
    latency_jitter_s: float = 0.0
    level: float = 1.0
    truth_offset: float = 1.0
    seed: int = 20261111
    sources: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False)

    TERMS: ClassVar[tuple[str, ...]] = ("encoder_quantum_rad", "encoder_noise_rad", "velocity_noise_rad_s", "torque_noise_nm",
                                        "torque_disturbance_nm", "period_overrun_s", "latency_jitter_s")

    def __post_init__(self) -> None:
        for name in (*self.TERMS, "level", "truth_offset"):
            value = getattr(self, name)
            if not (isinstance(value, (int, float)) and math.isfinite(value) and value >= 0.0):
                raise ValueError(f"NoiseModel.{name} is a finite number >= 0, not {value!r}")

    def at(self, level: float) -> NoiseModel:
        """The same terms at another level (0: noise-free; 3: every term x3)."""
        return dataclasses.replace(self, level=float(level))

    def with_terms(self, **terms: float) -> NoiseModel:
        """One or more terms' 1x values replaced (the others kept): ``noise.with_terms(torque_noise_nm=0.05)``."""
        unknown = sorted(set(terms) - set(self.TERMS) - {"truth_offset", "seed"})
        if unknown:
            raise KeyError(f"no noise term {unknown}; the terms are {self.TERMS} (+ truth_offset, seed)")
        return dataclasses.replace(self, **terms)

    def effective(self) -> dict[str, float]:
        """Each term as the rig applies it: its 1x value x level."""
        return {name: float(getattr(self, name)) * float(self.level) for name in self.TERMS}

    def rng(self, *stream: Any):
        """A generator for one named stream (e.g. ("routine:servo.backlash_reversal_held", "can15")): the same seed and stream draw the same
        numbers, another stream draws independently (sysid's crc32 rule)."""
        import numpy as np  # noqa: PLC0415

        return np.random.default_rng([int(self.seed), *(zlib.crc32(str(s).encode()) for s in stream)])

    def to_dict(self) -> dict:
        return {**{f.name: getattr(self, f.name) for f in dataclasses.fields(self) if f.name != "sources"}, "sources": dict(self.sources)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NoiseModel:
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: (dict(v) if k == "sources" else v) for k, v in data.items() if k in names})

    def summary(self) -> str:
        e = self.effective()
        return (f"noise x{self.level:g} (seed {self.seed}, truth offset x{self.truth_offset:g}): encoder step {math.degrees(e['encoder_quantum_rad']):.4f} deg, "
                f"encoder sigma {math.degrees(e['encoder_noise_rad']):.4f} deg, speed sigma {math.degrees(e['velocity_noise_rad_s']):.3f} deg/s, "
                f"torque sigma {e['torque_noise_nm'] * 1e3:.1f} mN.m, applied-torque disturbance {e['torque_disturbance_nm'] * 1e3:.1f} mN.m, loop overrun {e['period_overrun_s'] * 1e3:.2f} ms mean, "
                f"command latency jitter {e['latency_jitter_s'] * 1e3:.2f} ms")


def ruler(truth: Mapping[str, float], nominal: Mapping[str, float | None], noise: NoiseModel) -> dict[str, float]:
    """The values the world plays and the rows are held to: world.json's truth, moved toward nominal by ``noise.truth_offset`` (1: world.json
    exactly; 0: the nominal). A truth with no nominal stays as committed."""
    out = {}
    for key, value in truth.items():
        prior = nominal.get(key)
        out[key] = float(value) if prior is None else float(prior) + float(noise.truth_offset) * (float(value) - float(prior))
    return out


# --- the records a rig supplies and returns ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Parameter:
    """One parameter the rig's description carries (its key, "<instance>.<name>", is the manifest's). ``routine`` is the cards.calibration
    ROUTINES id that identifies it on this rig, else None and ``why_not`` says why (no excitation, no equipment, below the noise).
    ``tolerance``: ("rel" | "abs", value) in SI; ``tolerance_source``: the routine's or the use's, or "proposed: ..." when nobody stated one.
    ``display``: how a person reads it ("deg", "arcmin", "ms", "mm", "" = as is)."""
    key: str
    unit: str
    tolerance: tuple[str, float] | None = None
    tolerance_source: str = ""
    routine: str | None = None
    why_not: str = ""
    display: str = ""
    title: str = ""


@dataclass(frozen=True)
class Estimate:
    value: float | None
    ci95: tuple[float, float] | None = None
    method: str = ""


@dataclass(frozen=True)
class Run:
    """One run a routine (or the held-out set) plays. ``spec`` is the rig's own (a plan step, a tape, the host's frame); the runner reads
    only ``id`` and ``split``."""
    id: str
    split: str          # "train" | "held_out"
    spec: Any = None


@dataclass(frozen=True)
class Score:
    """``joints``: pooled RMS error per joint (rad, the instance ids); ``runs``: per run per joint; ``tool_stop_m``: p95 tool error where
    the command rests (m), for a rig with a tool point."""
    joints: Mapping[str, float]
    runs: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    tool_stop_m: float | None = None


class TwinHandle:
    """What a fit may play: the rig's twin at candidate values, replaying recorded commands, noise-free. Never the truth."""

    def __init__(self, rig, workers: int) -> None:
        self._rig, self.workers = rig, workers

    def predict(self, measured: Mapping[str, Any], values: Mapping[str, float]) -> Mapping[str, Any]:
        return self._rig.predict(measured, values, workers=self.workers)


class Routine(Protocol):
    id: str                                        # a cards.calibration ROUTINES id
    identifies: tuple[str, ...]                    # the parameter keys its fit returns as found (held to the truth)
    # optional: adjusts: tuple[str, ...]           # keys it SETS for the twin without claiming them (a chain's masses on their visible
    #                                              # subspace): the twin uses them, their rows stay "not identified"

    def runs(self, values: Mapping[str, float]) -> Sequence[Run]: ...

    def fit(self, measured: Mapping[str, Any], values: Mapping[str, float], twin: TwinHandle) -> Mapping[str, Estimate]: ...


class RigBackend(Protocol):
    name: str

    def parameters(self) -> Sequence[Parameter]: ...

    def noise(self) -> NoiseModel: ...

    def routines(self) -> Sequence[Routine]: ...

    def held_out(self, values: Mapping[str, float] | None = None) -> Sequence[Run]: ...

    def measure(self, runs: Sequence[Run], values: Mapping[str, float], noise: NoiseModel, stream: str, *, workers: int = 1) -> Mapping[str, Any]: ...

    def predict(self, measured: Mapping[str, Any], values: Mapping[str, float], *, workers: int = 1) -> Mapping[str, Any]: ...

    def score(self, predicted: Mapping[str, Any], measured: Mapping[str, Any]) -> Score: ...


def load_rig(name: str):
    """The rig a description ships (sysid/examples/<name>/rig.py, its ``rig()``), or None (then the Twin keeps twin.SimRunner)."""
    if not (REPO / "sysid" / "examples" / name / "rig.py").exists():
        return None
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    return importlib.import_module(f"sysid.examples.{name}.rig").rig()


def _hidden():
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    from sysid import world  # noqa: PLC0415

    return world


# --- what the runner returns -----------------------------------------------------------------------------------------------------------


DISPLAY = {"deg": (math.degrees(1.0), "°"), "arcmin": (math.degrees(1.0) * 60.0, "′"), "ms": (1e3, "ms"), "mm": (1e3, "mm"), "": (1.0, "")}


def shown(value: float | None, display: str, unit: str = "") -> str:
    if value is None:
        return "—"
    scale, sign = DISPLAY[display]
    return f"{value * scale:.4g}{sign if display else (' ' + unit if unit else '')}"


@dataclass(frozen=True)
class RigCalibration:
    """A calibration's outcome on the seam: per parameter the ruler (world.json's truth at the noise model's truth offset), nominal,
    recovered and its 95 % interval, error, tolerance and verdict, or why it is not identified; and the routines as they ran."""
    backend: str
    rig: str
    model: str
    noise: NoiseModel
    values: dict[str, Any]                   # identified keys -> robot_msgs Value (MEASURED)
    estimates: dict[str, Estimate]
    rows: list[dict]
    routines: list[dict]
    truth_moved: dict[str, float]
    seconds: float

    @property
    def failing(self) -> list[str]:
        return [r["key"] for r in self.rows if r["pass"] is False]

    @property
    def passed(self) -> bool:
        return any(r["pass"] is True for r in self.rows) and not self.failing

    @property
    def unidentified(self) -> list[dict]:
        return [r for r in self.rows if r["routine"] is None]

    def summary(self) -> str:
        head = (f"calibrate(on={self.backend!r}, truth='sealed') on {self.rig}: {len(self.routines)} routines "
                f"({', '.join(r['routine'] for r in self.routines)}); {self.seconds:.0f} s\n  {self.noise.summary()}")
        if self.truth_moved:
            head += f"\n  the hidden truth MOVED for this run: {self.truth_moved} (the ruler stays world.json's)"
        lines = [head, f"  {'parameter':34s} {'truth':>11s} {'recovered':>11s} {'error':>9s} {'err %':>7s} {'tol':>10s}  verdict   routine"]
        for r in self.rows:
            if r["routine"] is None:
                continue
            err = None if r["recovered"] is None or r["true"] is None else r["recovered"] - r["true"]
            pct = None if err is None or not r["true"] else 100.0 * err / abs(r["true"])
            tol = r["tolerance"]
            tol_text = "—" if tol is None else (f"{tol['value'] * 100:g} %" if tol["kind"] == "rel" else shown(tol["value"], r["display"], r["unit"]))
            lines.append(f"  {r['key']:34s} {shown(r['true'], r['display'], r['unit']):>11s} {shown(r['recovered'], r['display'], r['unit']):>11s} "
                         f"{shown(err, r['display'], r['unit']):>9s} {'—' if pct is None else f'{pct:+.1f}':>7s} {tol_text:>10s}  "
                         f"{'pass' if r['pass'] else ('FAIL' if r['pass'] is False else '—'):7s}   {r['routine']}")
        lines.append(f"  => {'PASS' if self.passed else 'FAIL'}: {sum(r['pass'] is True for r in self.rows)}/"
                     f"{sum(r['pass'] is not None for r in self.rows)} identified values within tolerance of the hidden truth"
                     + (f" (failing: {', '.join(self.failing)})" if self.failing else ""))
        if self.unidentified:
            lines.append(f"  not identified ({len(self.unidentified)}): " + "; ".join(f"{r['key']} ({r['why_not']})" for r in self.unidentified))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"seam": SEAM, "backend": self.backend, "rig": self.rig, "model": self.model, "noise": self.noise.to_dict(),
                "values": {k: (None if v is None else float(v)) for k, v in self.values.items()},
                "estimates": {k: dataclasses.asdict(e) for k, e in self.estimates.items()}, "rows": self.rows, "routines": self.routines,
                "truth_moved": self.truth_moved, "seconds": self.seconds, "passed": self.passed, "failing": self.failing}


@dataclass(frozen=True)
class RigReport:
    """eval_twin on the seam: per joint the held-out RMS error of each twin (nominal, fitted) and the floor (two draws of each held-out
    run under the same noise), their ratios, the tool at stops, and the gates."""
    rig: str
    floor: dict[str, float]
    errors: dict[str, dict[str, float]]
    ratios: dict[str, dict[str, float | None]]
    tool_stop_m: dict[str, float | None]
    gates: tuple
    runs: int
    per_run: dict[str, dict[str, dict[str, float]]]
    seconds: float

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def summary(self) -> str:
        lines = [f"eval_twin on {self.rig}: {self.runs} held-out runs; floor = the sim's own repeat spread (two noise draws of each run)"]
        for joint, floor in self.floor.items():
            fit, nom = self.errors["fitted"].get(joint), self.errors["nominal"].get(joint)
            lines.append(f"  {joint:8s} floor {math.degrees(floor):.4f}°  fitted {math.degrees(fit):.4f}° ({_x(self.ratios['fitted'][joint])}x floor)  "
                         f"nominal {math.degrees(nom):.4f}° ({_x(self.ratios['nominal'][joint])}x)")
        if any(v is not None for v in self.tool_stop_m.values()):
            lines.append("  tool at stops, p95: " + ", ".join(f"{k} {'—' if v is None else f'{v * 1e3:.3f} mm'}" for k, v in self.tool_stop_m.items()))
        for g in self.gates:
            lines.append(f"  gate {g.id:14s} {'pass' if g.passed else 'FAIL'}  {g.title}: {g.value} ({g.rule}; {g.source})")
        lines.append(f"  => {'PASS' if self.passed else 'FAIL'}: {sum(g.passed for g in self.gates)}/{len(self.gates)} gates")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {**{k: v for k, v in dataclasses.asdict(self).items() if k != "gates"}, "gates": [dataclasses.asdict(g) for g in self.gates],
                "passed": self.passed}


def _x(value) -> str:
    return "—" if value is None else f"{value:.3g}"


def _say(text: str) -> None:
    """Progress of a long calibration on stderr (a whole sequence runs tens of minutes)."""
    print(f"[sim2real.rig {time.strftime('%H:%M:%S')}] {text}", file=sys.stderr, flush=True)


# --- the runner ----------------------------------------------------------------------------------------------------------------------------


class RigRunner:
    """The sim backend over a RigBackend. ``world`` returns the world document ({"truth": {...}}); by default sysid.world.load(rig.name),
    whose reads raise inside sysid.world.sealed(). ``state`` is a fitted twin's."""

    def __init__(self, description, rig, *, workers: int = 4, world: Callable[[], Mapping] | None = None, state: Mapping | None = None):
        self.description = description
        self.rig = rig
        self.workers = int(workers)
        self._world = world or (lambda: _hidden().load(rig.name))
        self.state: dict = dict(state or {})

    # ---- the description's values and the rig's table

    def default_model(self) -> str:
        return getattr(self.rig, "model", "rig twin")

    def noise(self) -> NoiseModel:
        return self.rig.noise()

    def nominal(self) -> dict[str, float | None]:
        return {k: (None if v is None else float(v)) for k, v in self.description.values().items()}

    def table(self) -> dict[str, Parameter]:
        """The rig's parameters, checked: every unidentified one says why, every routine is a registered cards.calibration routine, and
        each routine identifies exactly the parameters that name it."""
        from .cards import registry as reg  # noqa: PLC0415

        params = {p.key: p for p in self.rig.parameters()}
        silent = [k for k, p in params.items() if p.routine is None and not p.why_not]
        if silent:
            raise ValueError(f"{self.rig.name}: an unidentified parameter must say why nothing identifies it: {silent}")
        known = {r.id for r in reg.ROUTINES}
        named = sorted({p.routine for p in params.values() if p.routine} | {r.id for r in self.rig.routines()})
        unknown = [r for r in named if r not in known]
        if unknown:
            raise KeyError(f"{self.rig.name}: {unknown} is not a cards.calibration routine (src/sim2real/cards/calibration.py ROUTINES)")
        claimed: dict[str, str] = {}
        for routine in self.rig.routines():
            for key in routine.identifies:
                if key not in params:
                    raise KeyError(f"{routine.id} identifies {key!r}, which {self.rig.name} does not carry")
                claimed[key] = routine.id
            unknown_adjusts = sorted(set(getattr(routine, "adjusts", ())) - set(params))
            if unknown_adjusts:
                raise KeyError(f"{routine.id} adjusts {unknown_adjusts}, which {self.rig.name} does not carry")
        mismatched = [k for k, p in params.items() if p.routine is not None and claimed.get(k) != p.routine]
        if mismatched:
            raise ValueError(f"{self.rig.name}: these parameters name a routine that does not identify them: {mismatched}")
        return params

    def _noise(self, noise) -> NoiseModel:
        if noise is None:
            return self.rig.noise()
        if isinstance(noise, NoiseModel):
            return noise
        return self.rig.noise().at(float(noise))

    # ---- calibrate

    def calibrate(self, *, model: str | None = None, truth: Mapping[str, float] | None = None, noise=None) -> tuple[RigCalibration, dict]:
        from robot_msgs.space import Basis, Value  # noqa: PLC0415

        started = time.monotonic()
        params = self.table()
        noise = self._noise(noise)
        hidden = _hidden()
        committed = dict(self._world()["truth"])           # the runner alone reads the truth, outside the seal
        nominal = self.nominal()
        ruled = ruler(committed, nominal, noise)
        derive = getattr(self.rig, "derived", None)
        if derive is not None:
            # WHY: a value the rig computes from others (a joint's gravity from the chain's masses) is held to what the ruled masses give,
            # not scaled on its own: at truth_offset != 1 the two differ
            ruled.update(derive({**{k: v for k, v in nominal.items() if v is not None}, **ruled}))
        moved = {k: float(v) for k, v in (truth or {}).items()}
        unknown = sorted(set(moved) - set(committed))
        if unknown:
            raise KeyError(f"no hidden value {unknown} in {self.rig.name}'s world (it has {sorted(committed)})")
        if derive is not None and set(moved) & set(derive({**{k: v for k, v in nominal.items() if v is not None}, **ruled})):
            raise KeyError(f"{sorted(moved)}: a derived value cannot be moved on its own; move what it is derived from")
        # the world plays the ruled truth, moved where asked; a parameter world.json does not hide plays at its nominal
        world_values = {**{k: v for k, v in nominal.items() if v is not None}, **ruled, **moved}
        values = {k: v for k, v in nominal.items() if v is not None}
        estimates: dict[str, Estimate] = {}
        adjusted: dict[str, Estimate] = {}
        steps, trained = [], set()
        played: dict[str, Any] = {}
        for routine in self.rig.routines():
            began = time.monotonic()
            runs = list(routine.runs(dict(values)))
            # WHY played once: a run two routines both read (the dynamics fit's chirps are the delay scan's) is one physical run, its data shared
            fresh = [run for run in runs if run.id not in played]
            if fresh:
                played.update(self.rig.measure(fresh, world_values, noise, f"routine:{routine.id}", workers=self.workers))
            measured = {run.id: played[run.id] for run in runs}
            _say(f"{routine.id}: {len(runs)} runs ({len(fresh)} played) in {time.monotonic() - began:.0f} s; fitting")
            with hidden.sealed():
                found = dict(routine.fit(measured, dict(values), TwinHandle(self.rig, self.workers)))
            _say(f"{routine.id}: done in {time.monotonic() - began:.0f} s")
            adjusts = tuple(getattr(routine, "adjusts", ()))
            extra = sorted(set(found) - set(routine.identifies) - set(adjusts))
            if extra:
                raise KeyError(f"{routine.id} returned {extra}, which it does not declare (identifies: {routine.identifies}, adjusts: {adjusts})")
            for key, estimate in found.items():
                if key in routine.identifies:
                    estimates[key] = estimate
                else:
                    adjusted[key] = estimate
                if estimate.value is not None and math.isfinite(estimate.value):
                    values[key] = float(estimate.value)
            trained.update(run.id for run in runs)
            steps.append({"routine": routine.id, "identifies": list(routine.identifies), "runs": len(runs), "seconds": round(time.monotonic() - began, 1),
                          "found": {k: (None if e.value is None else float(e.value)) for k, e in found.items()}})
        rows = self._rows(params, nominal, ruled, estimates)
        for row in rows:
            if row["key"] in adjusted and row["routine"] is None:
                row["set_for_twin"] = adjusted[row["key"]].value   # used by the twin, never claimed: no verdict
        fitted_values = {}
        for key, estimate in estimates.items():
            if estimate.value is None:
                continue
            p = params[key]
            note = f"95 % interval [{estimate.ci95[0]:.6g}, {estimate.ci95[1]:.6g}]" if estimate.ci95 else ""
            fitted_values[key] = Value(float(estimate.value), p.unit, basis=Basis.MEASURED, source=estimate.method,
                                       measured_by=f"sim2real.Twin.calibrate(on='sim', truth='sealed'), {p.routine}", notes=note)
        calibration = RigCalibration("sim", self.rig.name, model or self.default_model(), noise, fitted_values, estimates, rows, steps, moved,
                                     round(time.monotonic() - started, 1))
        state = {"values": values, "nominal": {k: v for k, v in nominal.items() if v is not None}, "world_values": world_values, "noise": noise,
                 "trained": trained, "calibration": calibration}
        return calibration, state

    @staticmethod
    def _rows(params: Mapping[str, Parameter], nominal, ruled, estimates) -> list[dict]:
        rows = []
        for key, p in params.items():
            e = estimates.get(key)
            true = ruled.get(key)
            recovered = None if e is None or e.value is None or not math.isfinite(e.value) else float(e.value)
            gated = p.routine is not None and p.tolerance is not None and true is not None
            ok = None
            if gated:
                kind, tol = p.tolerance
                ok = recovered is not None and abs(recovered - true) <= (tol if kind == "abs" else tol * abs(true))
            rows.append({"key": key, "title": p.title or key, "unit": p.unit, "display": p.display, "nominal": nominal.get(key), "true": true,
                         "recovered": recovered, "ci95": None if e is None or not e.ci95 else [float(v) for v in e.ci95],
                         "error": None if recovered is None or true is None else recovered - true,
                         "tolerance": None if p.tolerance is None else {"kind": p.tolerance[0], "value": float(p.tolerance[1]), "source": p.tolerance_source},
                         "pass": ok, "routine": p.routine, "why_not": p.why_not, "method": "" if e is None else e.method})
        return rows

    # ---- eval_twin

    def eval_twin(self) -> RigReport:
        from .cards import registry as reg  # noqa: PLC0415
        from .metrics.gate import at_most, gate, required  # noqa: PLC0415
        from .twin import Gate  # noqa: PLC0415

        if not self.state:
            raise RuntimeError("eval_twin needs a fitted twin: fitted = twin.calibrate(...), then fitted.eval_twin()")
        s = self.state
        if "report" in s:
            return s["report"]
        started = time.monotonic()
        held = list(self.rig.held_out(dict(s["values"])))
        # WHY refused, not filtered (the held-out split is the only judge; sklearn's leakage rule)
        leaked = sorted({r.id for r in held if r.split != "held_out" or r.id in s["trained"]})
        if leaked:
            raise ValueError(f"eval_twin scores held-out runs only; these are training runs: {leaked[:5]}")
        _say(f"eval_twin: {len(held)} held-out runs, measured twice")
        measured = self.rig.measure(held, s["world_values"], s["noise"], "held_out", workers=self.workers)
        repeat = self.rig.measure(held, s["world_values"], s["noise"], "repeat", workers=self.workers)
        floor = self.rig.score(repeat, measured)
        scores = {label: self.rig.score(self.rig.predict(measured, vals, workers=self.workers), measured)
                  for label, vals in (("nominal", s["nominal"]), ("fitted", s["values"]))}
        errors = {label: dict(sc.joints) for label, sc in scores.items()}
        ratios = {label: {j: (e / floor.joints[j] if floor.joints.get(j) else None) for j, e in errs.items()} for label, errs in errors.items()}
        tool = {"floor": floor.tool_stop_m, **{label: sc.tool_stop_m for label, sc in scores.items()}}
        gates = []
        worst = max((v for v in ratios["fitted"].values() if v is not None), default=None)
        verdict = gate(worst, at_most(reg.TWINNED_LIMIT, "x floor"))
        gates.append(Gate("twinned", "fitted twin's held-out error / floor, worst joint", _x(worst), f"<= {reg.TWINNED_LIMIT:g}x",
                          verdict.passes, "sim2real.cards.registry.TWINNED_LIMIT", verdict.violations))
        calibration = s["calibration"]
        verdict = gate(calibration.passed, required())
        gates.append(Gate("recovery", "every identified hidden value within its tolerance (the sim oracle only)",
                          f"{sum(r['pass'] is True for r in calibration.rows)}/{sum(r['pass'] is not None for r in calibration.rows)}"
                          + (f", failing {', '.join(calibration.failing)}" if calibration.failing else ""), "all", verdict.passes,
                          f"sysid/examples/{self.rig.name}/world.json + the rig's tolerances", verdict.violations))
        if scores["fitted"].tool_stop_m is not None:
            verdict = gate(scores["fitted"].tool_stop_m * 1e3, at_most(TOOL_GATE_M * 1e3, "mm"))
            gates.append(Gate("tool_at_stops", "fitted twin's tool vs the world's where the command rests, p95",
                              f"{scores['fitted'].tool_stop_m * 1e3:.3f} mm", f"<= {TOOL_GATE_M * 1e3:g} mm", verdict.passes,
                              "Zach 2026-11-11: final tool error sub 1 mm", verdict.violations))
        per_run = {"floor": {k: dict(v) for k, v in floor.runs.items()}, **{label: {k: dict(v) for k, v in sc.runs.items()} for label, sc in scores.items()}}
        report = RigReport(self.rig.name, dict(floor.joints), errors, ratios, tool, tuple(gates), len(held), per_run, round(time.monotonic() - started, 1))
        s["report"] = report
        s["held_out"] = {"measured": measured, "runs": held}
        return report

    # ---- the page

    def result(self):
        """The calibration as one page (sim2real.result.CalibrationResult), the description's typed tree with its sections."""
        report = self.eval_twin()
        build = getattr(self.rig, "result", None)
        if build is None:
            raise NotImplementedError(f"{self.rig.name} supplies no result() tree yet")
        return build(self.description, self.state["calibration"], report, self.state)
