"""The one-click seam: what a rig supplies so ``RobotTwin(...).calibrate(on="sim", truth="sealed")`` runs its whole calibration sequence
against a sealed hidden truth, and ``eval()`` scores the fitted twin held out over the sim's own repeat floor (Zach, 2026-11-11).

    import sim2real
    twin = sim2real.examples.ur_wrist_test_rig()          # sysid/examples/ur_wrist_test_rig: description.json, world.json, rig.py
    fitted = twin.calibrate(on="sim", truth="sealed")      # every routine of the rig's sequence, in order; a NEW, fitted twin
    fitted.calibration_.summary()                          # per parameter: truth / recovered / error / tolerance / pass, and what is not identified
    fitted.eval().summary()                                # held-out error / floor per joint, the tool at stops, the gates
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
homed frame). The pendulum keeps its proven path untouched; a rig ships rig.py beside its description and the RobotTwin picks this runner.

WHY the guards here and never in a rig (scikit-learn's estimator contract, the API prior-art note): the runner alone reads the truth
(world.json, outside the seal), every fit runs inside sysid.world.sealed(), the ruler is world.json's (moved only by the noise model's
truth_offset, never by move_truth), and eval refuses a run any routine measured.

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


def _command_types() -> tuple[type, type]:
    """The two command types a run may carry (robot_msgs, sim2real's one runtime dependency, imported when first needed)."""
    from robot_msgs.control import JointCommandSequence  # noqa: PLC0415
    from robot_msgs.trajectory import JointTrajectory  # noqa: PLC0415

    return JointTrajectory, JointCommandSequence


def _command_seconds(command: Any) -> tuple[float, float] | None:
    """A command's robot time as (shortest, longest), or None for no command. A JointTrajectory runs its duration. A JointCommandSequence
    runs each step until any of its conditions holds or its timeout aborts it: a step that ends only by time (every condition an Elapsed)
    takes at least the shortest Elapsed, any other step may end at once; and none outlasts min(timeout, shortest Elapsed)."""
    if command is None:
        return None
    from robot_msgs.control import Elapsed, JointCommandSequence  # noqa: PLC0415

    if isinstance(command, JointCommandSequence):
        low = high = 0.0
        for step in command.steps:
            elapsed = [c.duration for c in step.done_when if isinstance(c, Elapsed)]
            low += min(elapsed) if elapsed and len(elapsed) == len(step.done_when) else 0.0
            high += min([float(step.timeout), *elapsed])
        return (float(low), float(high))
    return (float(command.duration), float(command.duration))


@dataclass(frozen=True)
class Run:
    """One run a routine (or the held-out set) plays. ``spec`` is the rig's own (a plan step, a tape, the host's frame). ``command`` is what
    the robot plays, typed: a robot_msgs JointTrajectory (an open-loop tape) or JointCommandSequence (closed-loop steps, each done by its
    conditions or its timeout), or None (the rig's spec says what to play, or nothing is played: a log already recorded). ``seconds`` is its
    robot time when no command states it (None: unknown; 0.0: already on disk); a command's own length wins, and a run has one length.
    The runner reads ``id``, ``split`` and ``command``.

    WHY typed commands (Zach, Daily Note 2026-11-17: "could a routine just be described as as long joint traecjtory? or how about like
    ServoCommandSequence"): the schedule is a static object to look at, and a robot_msgs command is what makes a run something to look at;
    anything else is refused, so a spec is never mistaken for a command."""
    id: str
    split: str          # "train" | "held_out"
    spec: Any = None
    seconds: float | None = None
    command: Any = None

    def __post_init__(self) -> None:
        if self.command is not None and not isinstance(self.command, _command_types()):
            raise TypeError(f"run {self.id!r}: command is a robot_msgs JointTrajectory or JointCommandSequence (or None), not "
                            f"{type(self.command).__name__}; what the rig itself reads goes in spec")
        if self.seconds is None:
            return
        seconds = float(self.seconds)
        if not (math.isfinite(seconds) and seconds >= 0.0):
            raise ValueError(f"run {self.id!r}: seconds is None (unknown) or a finite number >= 0, not {self.seconds!r}")
        object.__setattr__(self, "seconds", seconds)
        bounds = _command_seconds(self.command)
        if bounds is not None and not (bounds[0] - 1e-9 <= seconds <= bounds[1] + 1e-9):
            raise ValueError(f"run {self.id!r}: seconds {seconds:g} disagrees with its {type(self.command).__name__}, which runs "
                             f"{_span(bounds)}: one run has one length, and a command states its own")

    def robot_seconds(self) -> tuple[float, float] | None:
        """The robot time this run takes, (shortest, longest) in s: its command's, else (seconds, seconds), else None (unknown)."""
        bounds = _command_seconds(self.command)
        if bounds is not None:
            return bounds
        return None if self.seconds is None else (self.seconds, self.seconds)

    def to_dict(self) -> dict:
        """JSON: id, split, spec, seconds and the command as robot_msgs writes it (its "_type" names the class). A spec that is not JSON is
        refused by the run's id, never dropped: a run that came back without its spec would be another run."""
        import json  # noqa: PLC0415

        try:
            json.dumps(self.spec)
        except (TypeError, ValueError) as caught:
            raise TypeError(f"run {self.id!r}: its spec is not JSON ({caught}), so the run cannot be written as a dict") from None
        return {"id": self.id, "split": self.split, "spec": self.spec, "seconds": self.seconds,
                "command": None if self.command is None else self.command.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Run:
        command = data.get("command")
        if command is not None:
            from robot_msgs import from_dict  # noqa: PLC0415

            _command_types()  # the message classes registered before robot_msgs reads "_type"
            command = from_dict(command)
        return cls(str(data["id"]), str(data["split"]), data.get("spec"), data.get("seconds"), command)


def _span(bounds: tuple[float, float] | None) -> str:
    if bounds is None:
        return "an unknown time"
    low, high = bounds
    return f"{low:.4g} s" if math.isclose(low, high) else f"{low:.4g}-{high:.4g} s"


def _same(a: Any, b: Any) -> bool:
    """Exact equality that also holds for numpy arrays inside a spec (== on a dict holding an array raises)."""
    import numpy as np  # noqa: PLC0415

    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        if not (isinstance(a, np.ndarray) and isinstance(b, np.ndarray) and a.shape == b.shape):
            return False
        return bool(np.array_equal(a, b, equal_nan=a.dtype.kind in "fc" and b.dtype.kind in "fc"))
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    try:
        return bool(a == b)
    except (TypeError, ValueError):
        return a is b


def _same_run(a: Any, b: Any) -> bool:
    """One run: the same id, split, spec, seconds and command."""
    return (a.id == b.id and a.split == b.split and _same(getattr(a, "spec", None), getattr(b, "spec", None))
            and getattr(a, "seconds", None) == getattr(b, "seconds", None) and _same(getattr(a, "command", None), getattr(b, "command", None)))


def _same_runs(a: Sequence[Any], b: Sequence[Any]) -> bool:
    return len(a) == len(b) and all(_same_run(x, y) for x, y in zip(a, b))


@dataclass(frozen=True)
class Score:
    """``joints``: pooled RMS error per joint (rad, the instance ids); ``runs``: per run per joint; ``tool_stop_m``: p95 tool error where
    the command rests (m), for a rig with a tool point."""
    joints: Mapping[str, float]
    runs: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    tool_stop_m: float | None = None


class TwinHandle:
    """What a fit may play: the rig's twin at candidate values, replaying recorded commands, noise-free. Never the truth. ``settings``:
    every setting the configure / tune steps before it chose ({key: value}, in run order), their own channel (gap C)."""

    def __init__(self, rig, workers: int, settings: Mapping[str, float] | None = None) -> None:
        self._rig, self.workers = rig, workers
        self.settings = dict(settings or {})

    def predict(self, measured: Mapping[str, Any], values: Mapping[str, float]) -> Mapping[str, Any]:
        return self._rig.predict(measured, values, workers=self.workers)


@dataclass(frozen=True)
class Round:
    """One round of a routine that comes back for more: ``k`` (0: the runs ``runs()`` gave, then each ``next_runs()``), the runs that
    round asked for, and what the fit over every run so far found (the ``history`` a routine's ``next_runs`` and ``converged`` read).

    WHY "rounds", not "iterations" (2026-11-18): in sim2real an iteration is a twin's generation (result.py stages, the W&B trend "across
    twin iterations"); a round is one collect -> fit inside one routine."""
    k: int
    runs: tuple[Run, ...]
    found: Mapping[str, Estimate]


@dataclass(frozen=True)
class Stop:
    """What a routine's ``converged()`` returns to stop WITHOUT claiming convergence (``Stop("no improvement in 2 rounds")``); a plain str
    stops it converged, None asks for the next round. Any object with ``why`` and ``converged`` reads the same (and one whose ``stop`` is
    false asks for the next round), so a routine may return its own verdict."""
    why: str
    converged: bool = False


class Routine(Protocol):
    id: str                                        # a cards.calibration ROUTINES id
    identifies: tuple[str, ...]                    # the parameter keys its fit returns as found (held to the truth)
    # optional: kind: str                          # cards.schema ROUTINE_KINDS; not declared: the catalog's for its id
    # optional: configures: tuple[str, ...]        # the device-setting keys a configure / tune step writes (gap C). A CONFIGURE step's
    #                                              # reach the values (what follows runs at them); a TUNE's are settings only: in the
    #                                              # step's found, state["settings"] (fitted.settings_) and the handle's `settings`,
    #                                              # never the values later routines fit with or the twin replays at, never graded. A fit
    #                                              # result with a `proposal` attribute (pidtuna's board change) lands in state["proposals"]
    # optional: unavailable() -> str | None         # why it cannot run on this machine (plan() drops it, naming this), or None
    # optional: adjusts: tuple[str, ...]           # keys it SETS for the twin without claiming them (a chain's masses on their visible
    #                                              # subspace): the twin uses them, their rows stay "not identified"
    # optional: commands_read: tuple[str, ...]     # the keys its runs' commands are made from; the schedule (sim2real.calibration.plan)
    #                                              # shows its commands made after the steps that find them. Not declared: the keys it
    #                                              # requires. runs() must give the same runs for the same values (a schedule is static)
    # optional, a routine that comes back for more (rounds: collect, fit, come back; Zach, Daily Note 2026-11-18):
    #   max_rounds: int                            # its cap on rounds (>= 1; required once next_runs exists)
    #   next_runs(values, history: tuple[Round, ...]) -> Sequence[Run]   # the next round's runs, made after the last fit; () = no more
    #   converged(history, values) -> str | Stop | None                  # its own stop rule, replacing the default (every 95 % interval
    #                                              # inside its tolerance); a tune, or a routine that identifies no key with a tolerance,
    #                                              # must have one

    def runs(self, values: Mapping[str, float]) -> Sequence[Run]: ...

    def fit(self, measured: Mapping[str, Any], values: Mapping[str, float], twin: TwinHandle) -> Mapping[str, Estimate]: ...


def _round_cap(routine: Any) -> int | None:
    """An iterating routine's max_rounds, checked (an int >= 1), or None for a routine that plays one round (no next_runs)."""
    import numbers  # noqa: PLC0415

    if not callable(getattr(routine, "next_runs", None)):
        return None
    cap = getattr(routine, "max_rounds", None)
    if isinstance(cap, bool) or not isinstance(cap, numbers.Integral) or cap < 1:
        from .calibration.plan import CalibrationPlanError  # noqa: PLC0415

        raise CalibrationPlanError(f"{routine.id} comes back for more (next_runs) but states no max_rounds, an int >= 1 (it has {cap!r}): "
                                   "a routine that iterates says how many rounds it may take, so the schedule can show its bound")
    return int(cap)


def _inside_tolerance(found: Mapping[str, Estimate], identifies: Sequence[str], params: Mapping[str, Parameter],
                      known: Mapping[str, float]) -> str | None:
    """The default stop: a reason when every key the routine identifies that has a tolerance (and is not known) has a 95 % interval
    whose half-width is inside it, else None. WHY the interval and never the truth (gap A2): a stop rule that read the hidden values would
    leak them into how much is collected, and it must work the same on the bench, where there is no truth (moving the truth leaves the
    rounds unchanged: tests/test_calibration_rounds.py)."""
    judged = [k for k in identifies if k not in known and params.get(k) is not None and params[k].tolerance is not None]
    if not judged:
        return None
    words = []
    for key in judged:
        estimate = found.get(key)
        if estimate is None or estimate.value is None or not estimate.ci95 or not math.isfinite(estimate.value):
            return None
        kind, tol = params[key].tolerance
        limit = float(tol) if kind == "abs" else float(tol) * abs(float(estimate.value))
        half = (float(estimate.ci95[1]) - float(estimate.ci95[0])) / 2.0
        # WHY the same part in 1e9 of slack as the rows' verdict (_rows): binary floating point never decides a stop
        if not half <= limit * (1.0 + 1e-9):
            return None
        words.append(f"{key} ±{half:.3g} within {limit:.3g}")
    return f"every 95 % interval inside its tolerance ({'; '.join(words)})"


def _kind(routine: Any) -> str:
    """A routine's kind: its own `kind`, else the catalog's for its id, else "identify"."""
    kind = getattr(routine, "kind", None)
    if kind is None:
        from .cards import registry as reg  # noqa: PLC0415

        kind = next((r.kind for r in reg.ROUTINES if r.id == routine.id), "identify")
    return str(kind)


def _settle(routine: Any, found: Mapping[str, Estimate], values: dict[str, float], settings: dict[str, float]) -> None:
    """A step's configures keys (gap C): every one into `settings`; a configure step's into `values` too (later runs run at what it set), a
    tune's never (it proposes; the runs were made at the gains the device ran, so the twin fits and replays at those)."""
    configures = set(getattr(routine, "configures", ()))
    if not configures:
        return
    tune = _kind(routine) == "tune"
    for key, estimate in found.items():
        if key not in configures or estimate.value is None or not math.isfinite(estimate.value):
            continue
        settings[key] = float(estimate.value)
        if not tune:
            values[key] = float(estimate.value)


def _floats(found: Mapping[str, Estimate]) -> dict[str, float | None]:
    return {key: (None if e.value is None else float(e.value)) for key, e in found.items()}


def _stop_of(reason: Any) -> tuple[bool | None, str]:
    """A converged() answer as (converged, why): None asks for the next round (converged None); a str stops it converged; a Stop (or any
    object with `why` and `converged`) stops it as it says, unless its `stop` is false."""
    if reason is None or (not isinstance(reason, str) and getattr(reason, "stop", True) is False):
        return None, ""
    if isinstance(reason, str):
        return True, reason
    return bool(reason.converged), str(reason.why)


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
    """The rig a description ships (sysid/examples/<name>/rig.py, its ``rig()``), or None (then the RobotTwin keeps twin.SimRunner)."""
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
    """eval on the seam: per joint the held-out RMS error of each twin (nominal, fitted) and the floor (two draws of each held-out
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
        lines = [f"eval on {self.rig}: {self.runs} held-out runs; floor = the sim's own repeat spread (two noise draws of each run)"]
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


def _held_to_schedule(routine_id: str, runs: Sequence[Run], step: Any, served: dict[str, tuple[str, Run]]) -> None:
    """Refuse, before anything of it is played, a routine the schedule shows known now (`step`) that plays other runs than it shows, and a
    run id another routine already played with another command. WHY held at play time and never probed at plan time (2026-11-18): the
    schedule takes what a routine declares its commands read; a routine whose commands read more than it declares shows known now, and is
    caught here by name, so what calibrate() plays is what the schedule showed."""
    from .calibration.plan import CalibrationPlanError  # noqa: PLC0415

    if step is not None and not _same_runs(runs, step.runs):
        bound = {r.id: r for r in step.runs}
        differ = [r.id for r in runs if r.id not in bound or not _same_run(r, bound[r.id])]
        differ += [rid for rid in bound if rid not in {r.id for r in runs}]
        raise CalibrationPlanError(
            f"{routine_id}: the schedule shows it known now, playing {[r.id for r in step.runs]} as made at the priors, but here it plays "
            f"{[r.id for r in runs]}, and {differ} differ: its commands read a value an earlier step found. Declare that read "
            f"(commands_read) so the schedule shows it made after that step; refused before it played")
    for run in runs:
        first = served.get(run.id)
        if first is None:
            served[run.id] = (routine_id, run)
        elif not _same(first[1].command, run.command):
            raise CalibrationPlanError(f"{routine_id} plays run {run.id!r} with another command than {first[0]} played under that id: one "
                                       "run id is one command")


def _raw_step(step: Mapping[str, Any], timing: Mapping[str, Any], params: Mapping[str, Parameter], collected: str) -> dict:
    """What RigRunner.calibrate hands on_step for one routine (gap E): its step row's names, plus the split of its time, the runs it read
    and played, and each found value with its interval, method and the unit its Parameter states (SI, never converted)."""
    found = {}
    for key, estimate in timing["found"].items():
        ci = estimate.ci95
        found[key] = {"value": None if estimate.value is None else float(estimate.value),
                      "ci95": None if not ci else [float(ci[0]), float(ci[1])], "method": estimate.method,
                      "unit": params[key].unit if key in params else None}
    raw = {"routine": step["routine"], "identifies": list(step["identifies"]), "runs": list(timing["runs"]), "played": list(timing["played"]),
           "collected": collected, "collect_s": timing["collect_s"], "fit_s": timing["fit_s"], "seconds": timing["seconds"], "found": found,
           "round": step["rounds"][-1]["k"] if step.get("rounds") else 0}
    if step.get("converged") is not None:
        raw.update(rounds=[dict(r) for r in step["rounds"]], converged=step["converged"], stopped=step["stopped"])
    return raw


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

    def with_state(self, state: Mapping) -> RigRunner:
        """The same runner (description, rig, workers and world) holding a fitted state: a fitted twin's. WHY the loaded twin's description
        and world (gap D): every refit then starts from the same priors in the same world, generation after generation."""
        return RigRunner(self.description, self.rig, workers=self.workers, world=self._world, state=state)

    def calibrate(self, *, model: str | None = None, truth: Mapping[str, float] | None = None, noise=None, routines: Sequence[Routine] | None = None,
                  measured: Mapping[str, Any] | None = None, known: Mapping[str, float] | None = None,
                  schedule: Any = None, serves: Mapping[str, str] | None = None,
                  on_step: Callable[[dict], None] | None = None) -> tuple[RigCalibration, dict]:
        """`routines`: the planned sequence (sim2real.calibration.plan: ordered, substituted, option copies), else the rig's own.
        `measured`: pre-collected runs {recording key: measurement} (sim2real.calibration.collect, a fitted twin's data_); a planned run it
        holds nothing for is refused and the rig's measure is never called. `serves` {recording key: the run id it answers}: a key with no
        entry answers its own id; a fit is handed every recording that answers each run it asks for, keyed by recording key (a run
        recorded on two days is two recordings). `known`: {key: value} fixed for every routine (CalibrationConfig.known). `schedule`: the
        CalibrationSchedule the routines were planned in; a step it shows known now must play exactly the runs it shows, or it is refused
        by name before anything of it is played. The state carries `played` ({recording key: recording}, every one the fits read, in play
        order) and `serves`. `on_step` (gap E: calibrate(callbacks=)) is handed each routine's step as it finishes, before the next one
        runs: {routine, identifies, runs (the distinct run ids it read, every round), played (the ones it measured or read fresh),
        collected ("measured" | "recorded"), collect_s, fit_s, seconds, found {key: {value, ci95, method, unit}} (the last fit, the unit
        the rig's Parameter states), round (its last round's k), and a routine with rounds' rounds / converged / stopped}."""
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
        known = {k: float(v) for k, v in (known or {}).items()}
        values.update(known)
        recorded = None if measured is None else dict(measured)  # WHY a name of its own: the loop below rebinds `measured` per routine
        answers = dict(serves or {})
        estimates: dict[str, Estimate] = {}
        adjusted: dict[str, Estimate] = {}
        settings: dict[str, float] = {}   # what configure / tune steps chose, in run order (gap C); a tune's never reach `values`
        proposals: dict[str, Any] = {}    # {routine id: the proposal its fit result carried} (a tune's board change)
        steps, trained = [], set()
        played: dict[str, dict[str, Any]] = {}    # run id -> {recording key: recording}: every recording that answers it
        served: dict[str, tuple[str, Run]] = {}   # run id -> (the routine that first played it, the run as it was played)
        shown = {s.routine: s for s in getattr(schedule, "steps", ()) if s.status == "known now" and s.runs is not None}
        sequence = list(self.rig.routines() if routines is None else routines)

        def play(routine: Routine, fresh: Sequence[Run]) -> None:
            """The fresh runs into `played`: read from the recorded data, every recording that answers each (a run nothing answers is
            refused by name), else measured on the world."""
            if fresh and recorded is not None:
                found = {run.id: {k: recorded[k] for k in recorded if answers.get(k, k) == run.id} for run in fresh}
                missing = [run_id for run_id, keys in found.items() if not keys]
                if missing:
                    from .calibration.plan import CalibrationPlanError  # noqa: PLC0415

                    raise CalibrationPlanError(f"{routine.id} plays runs {missing}, which the recorded data does not hold")
                played.update(found)
            elif fresh:
                out = self.rig.measure(fresh, world_values, noise, f"routine:{routine.id}", workers=self.workers)
                played.update({run.id: {run.id: out[run.id]} for run in fresh})

        for routine in sequence:
            timing: dict | None = {} if on_step is not None else None
            step = self._play_routine(routine, values, play=play, played=played, served=served, shown=shown.get(routine.id), params=params,
                                      known=known, estimates=estimates, adjusted=adjusted, hidden=hidden, timing=timing, settings=settings,
                                      proposals=proposals)
            trained.update(run_id for done in step["rounds"] for run_id in done["runs"])
            trained.update(key for done in step["rounds"] for run_id in done["runs"] for key in played[run_id])
            steps.append(step)
            if on_step is not None:
                on_step(_raw_step(step, timing, params, "recorded" if recorded is not None else "measured"))
        rows = self._rows(params, nominal, ruled, estimates)
        ran = {r.id for r in sequence}
        for row in rows:
            if routines is not None and row["routine"] is not None and (row["key"] in known or row["routine"] not in ran):
                row["pass"] = None  # not graded: fixed by the caller, or its routine was left out of the plan
                row["why_not"] = (f"known: fixed at {known[row['key']]:.6g} by the caller" if row["key"] in known
                                  else f"its routine {row['routine']} was not in the plan")
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
                                       measured_by=f"sim2real.RobotTwin.calibrate(on='sim', truth='sealed'), {p.routine}", notes=note)
        calibration = RigCalibration("sim", self.rig.name, model or self.default_model(), noise, fitted_values, estimates, rows, steps, moved,
                                     round(time.monotonic() - started, 1))
        state = {"values": values, "nominal": {k: v for k, v in nominal.items() if v is not None}, "world_values": world_values, "noise": noise,
                 "trained": trained, "calibration": calibration,
                 "played": {key: recording for group in played.values() for key, recording in group.items()}, "serves": answers,
                 "settings": settings, "proposals": proposals}
        return calibration, state

    def _play_routine(self, routine: Routine, values: dict[str, float], *, play: Callable[[Routine, Sequence[Run]], None],
                      played: Mapping[str, Mapping[str, Any]], served: dict[str, tuple[str, Run]], shown: Any, params: Mapping[str, Parameter],
                      known: Mapping[str, float], estimates: dict[str, Estimate], adjusted: dict[str, Estimate], hidden: Any,
                      timing: dict | None = None, settings: dict[str, float] | None = None,
                      proposals: dict[str, Any] | None = None) -> dict:
        """One routine, round by round: collect (`play` puts the runs no routine has played yet into `played`, {run id: {recording key:
        recording}}), fit SEALED on every recording of every run it has asked for so far (keyed by recording key: a run recorded in two
        sessions is two recordings), and, for a routine that comes back for more (next_runs), stop on its own converged(), else when every 95 %
        interval is inside its tolerance, else at max_rounds, else when next_runs() asks for nothing; runs(), next_runs() and converged()
        run outside the seal. What it finds reaches `values` (and `estimates` / `adjusted`) after each round, so the next round's runs are
        made after the last fit. A configure / tune step's configures keys go to `settings` (_settle: a tune's never reach `values`), and
        a fit result's `proposal` to `proposals` (gap C). Returns its step row: routine, identifies, runs (distinct, every round), seconds,
        found (the last fit), rounds [{k, runs, found}], converged (None: it plays one round) and stopped (and configures, when it has
        any). `timing` (a dict, or None) is filled with what a step event adds (gap E): collect_s and fit_s summed over its rounds, the
        run ids it read and played, the last fit's Estimates, seconds.

        WHY rounds inside one routine, refitted on every run so far (Zach, Daily Note 2026-11-18: "a routine should include datacollection
        and fitting steps, and then iterating things that all goes into it"): each round adds data and the fit always sees all of it, so
        what stops it is the data's own spread, and a round that adds no new run is refused by name rather than spinning to its cap."""
        began = time.monotonic()
        settings = {} if settings is None else settings
        configures = tuple(getattr(routine, "configures", ()))
        cap = _round_cap(routine)
        runs = list(routine.runs(dict(values)))
        _held_to_schedule(routine.id, runs, shown, served)
        so_far: dict[str, Run] = {}
        history: list[Round] = []
        found: dict[str, Estimate] = {}
        collect_s = fit_s = 0.0
        fresh_ids: list[str] = []
        while True:
            k = len(history)
            # WHY played once: a run two routines both read (the dynamics fit's chirps are the delay scan's) is one physical run, its data
            # shared; a later round reads every earlier round's runs from `played`, never measuring them again
            fresh = [run for run in runs if run.id not in played]
            mark = time.monotonic()
            play(routine, fresh)
            collect_s += time.monotonic() - mark
            fresh_ids += [run.id for run in fresh]
            so_far.update((run.id, run) for run in runs)
            measured = {key: recording for run_id in so_far for key, recording in played[run_id].items()}
            label = routine.id if cap is None else f"{routine.id} round {k}"
            _say(f"{label}: {len(runs)} runs ({len(fresh)} played) in {time.monotonic() - began:.0f} s; fitting on {len(measured)}")
            mark = time.monotonic()
            with hidden.sealed():
                result = routine.fit(measured, dict(values), TwinHandle(self.rig, self.workers, settings))
            found = dict(result)
            fit_s += time.monotonic() - mark
            adjusts = tuple(getattr(routine, "adjusts", ()))
            extra = sorted(set(found) - set(routine.identifies) - set(adjusts) - set(configures))
            if extra:
                raise KeyError(f"{routine.id} returned {extra}, which it does not declare (identifies: {routine.identifies}, "
                               f"adjusts: {adjusts}, configures: {configures})")
            for key, estimate in found.items():
                if key in known:
                    continue  # fixed by the caller: never overwritten, never graded
                if key in routine.identifies:
                    estimates[key] = estimate
                elif key in configures:
                    continue  # a setting: _settle below (gap C), never an estimate or a value the twin is set to
                else:
                    adjusted[key] = estimate
                if estimate.value is not None and math.isfinite(estimate.value):
                    values[key] = float(estimate.value)
            _settle(routine, {k: e for k, e in found.items() if k not in known}, values, settings)
            if proposals is not None and getattr(result, "proposal", None) is not None:
                proposals[routine.id] = result.proposal
            history.append(Round(k, tuple(runs), dict(found)))
            if cap is None:
                converged, stopped = None, "ran once"
                break
            # the stop, in order: its own converged() (which replaces the default), the default rule, max_rounds, next_runs() empty
            if callable(getattr(routine, "converged", None)):
                converged, stopped = _stop_of(routine.converged(tuple(history), dict(values)))
            else:
                stopped = _inside_tolerance(found, routine.identifies, params, known) or ""
                converged = True if stopped else None
            if converged is not None:
                break
            if k + 1 >= cap:
                converged, stopped = False, f"max_rounds {cap} reached: it did not converge"
                break
            runs = list(routine.next_runs(dict(values), tuple(history)))
            if not runs:
                converged, stopped = False, f"next_runs() asked for nothing more after round {k}: it did not converge"
                break
            if all(run.id in so_far for run in runs):
                from .calibration.plan import CalibrationPlanError  # noqa: PLC0415

                raise CalibrationPlanError(f"{routine.id}: round {k + 1} asks for {[run.id for run in runs]}, which its earlier rounds already "
                                           "played: a round with no new run adds no data, so it would never converge; next_runs() gives "
                                           "runs with new ids, or () to stop")
            _held_to_schedule(routine.id, runs, None, served)   # one run id is one command, across rounds too
        _say(f"{routine.id}: done in {time.monotonic() - began:.0f} s" + ("" if cap is None else f", {len(history)} rounds ({stopped})"))
        if timing is not None:
            timing.update(collect_s=collect_s, fit_s=fit_s, runs=list(so_far), played=fresh_ids, found=dict(found),
                          seconds=time.monotonic() - began)
        row = {"routine": routine.id, "identifies": list(routine.identifies), "runs": len(so_far),
               "seconds": round(time.monotonic() - began, 1), "found": _floats(found),
               "rounds": [{"k": r.k, "runs": [run.id for run in r.runs], "found": _floats(r.found)} for r in history],
               "converged": converged, "stopped": stopped}
        if configures:
            row["configures"] = list(configures)   # WHY (gap C): the record names no parameter row's owner from a setting
        return row

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
                limit = tol if kind == "abs" else tol * abs(true)
                # WHY a part in 1e9 of slack: a value one tolerance away passes by the rule, and a grid of whole physics steps (0.4 vs 0.6 ms
                # read 2.0000000000000004e-4 against 2e-4) must not have its verdict decided by binary floating point
                ok = recovered is not None and abs(recovered - true) <= limit * (1.0 + 1e-9)
            rows.append({"key": key, "title": p.title or key, "unit": p.unit, "display": p.display, "nominal": nominal.get(key), "true": true,
                         "recovered": recovered, "ci95": None if e is None or not e.ci95 else [float(v) for v in e.ci95],
                         "error": None if recovered is None or true is None else recovered - true,
                         "tolerance": None if p.tolerance is None else {"kind": p.tolerance[0], "value": float(p.tolerance[1]), "source": p.tolerance_source},
                         "pass": ok, "routine": p.routine, "why_not": p.why_not, "method": "" if e is None else e.method})
        return rows

    # ---- eval

    def eval(self) -> RigReport:
        from .cards import registry as reg  # noqa: PLC0415
        from .metrics.gate import at_most, gate, required  # noqa: PLC0415
        from .twin import Gate  # noqa: PLC0415

        if not self.state:
            raise RuntimeError("eval needs a fitted twin: fitted = twin.calibrate(...), then fitted.eval()")
        s = self.state
        if "report" in s:
            return s["report"]
        started = time.monotonic()
        held = list(self.rig.held_out(dict(s["values"])))
        # WHY refused, not filtered (the held-out split is the only judge; sklearn's leakage rule)
        leaked = sorted({r.id for r in held if r.split != "held_out" or r.id in s["trained"]})
        if leaked:
            raise ValueError(f"eval scores held-out runs only; these are training runs: {leaked[:5]}")
        _say(f"eval: {len(held)} held-out runs, measured twice")
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
        report = self.eval()
        build = getattr(self.rig, "result", None)
        if build is None:
            raise NotImplementedError(f"{self.rig.name} supplies no result() tree yet")
        return build(self.description, self.state["calibration"], report, self.state)
