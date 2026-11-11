"""A 1-DOF joint description in, its whole test schedule out, with the coverage known before anything runs.

Zach (Daily Note, 2026-10-29): "What you pass in is like a robotdescription or description of the servo and then it kinda like
automatically makes the testing schedule ... before even running any tests you can basically see the testing schedule, in some sense
that is like the target ... analyze the testing schedule and make sure we have good coverage ... (train and test set ... a hold out)".

- ``build_schedule(description, player)``: every registered family's trajectories (each a sampled target kept inside the joint's range,
  speed, accel and torque, slowed down the stretch ladder until it is, or rejected with its reasons), and the runs (a trajectory under a
  condition, with its split): whole factor levels are held out, H1 = every excite run at the held-out kp level, H2 = the operate seeds
  held out under every mode; the floor is its own split.
- ``coverage(document)``: (q, qd, qdd) occupancy over the reachable cells per split, (q, tau) beside it, the note's targets, effect
  counters and identifiability, all from the planned targets, before any run.

The ``Player`` is what plays the schedule (the rack's guarded runner, a simulator): the families it can play, its control modes, how one of
its steps samples, the step a trajectory carries and its run time. The generator knows nothing else about it.

Moved from bam_rack_twin/schedule.py on 2026-11-10 (Zach, proposal 2 step 4: "schedule/: description -> test schedule, with coverage known
before running"): the description, the build loop and its split rule, the sampling and limit checks, and the coverage before running. The
rack keeps its families (written in its runner's step kinds), its modes, its session plans, dry runs and replays, and plays them through
this. Behaviour unchanged to the bit: every schedule frozen on /archive gets its own coverage back (tests/test_schedule_joint.py). The
gate and the note's targets are cards/ data (sim2real.cards.servo_gates), passed in.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from robot_msgs.coverage import centres, signed

__all__ = ["JointDescription", "integral_over_bound", "Runner", "Sampled", "TorqueOpenLoop", "Family", "register", "Player", "sides", "two_sided",
           "side", "fade", "sample", "demand", "violations", "build_schedule", "occupancy", "edges_of", "tau_edges", "reachable_cells", "SPLITS",
           "split_samples", "coverage", "effect_counters", "identifiability"]

# WHY 0.05 rad/s: the band of the model's Coulomb term, tanh(qd / band); the rack runner's own feed-forward band
# (bam_rack_twin.hardware.experiments.FF_BAND_RAD_S, pinned equal by bam_rack_twin's tests), so the schedule predicts the torque the runner sends
FF_BAND_RAD_S = 0.05
STRETCHES = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
KP_LEVELS = (1.0, 0.5, 0.25)  # the note's gain sweep (kd x 1)
HELD_OUT_KP = 0.5  # H1: the whole middle level held out (BAM's --validation_kp)
OPERATE_TRAIN_SEEDS = (0, 1, 2)
OPERATE_HELD_OUT_SEEDS = (3, 4, 5)  # H2: the acceptance set, sealed
FLOOR_REPEATS = 5
TRACKING_MODES = ("fb", "ff_fb", "ff_weakfb", "ff")
TORQUE_NOISE_NM = 0.05  # the identifiability prediction's torque noise (one sample), an assumption stated where it is used


# --------------------------------------------------------------------------- the joint description


@dataclass(frozen=True)
class JointDescription:
    """One 1-DOF joint, joint OUTPUT frame. Angles of the schedule are relative to ``origin_rad`` (the board-frame start)."""

    name: str
    can_id: int | None
    origin_rad: float  # absolute output angle trajectories start and end at (a pendulum's gravity bottom)
    range_rad: tuple[float, float]  # (low, high) from the origin
    speed_rad_s: float
    accel_rad_s2: float
    torque_limit_nm: float  # the predicted demand never exceeds this (the player's margin x the drive's torque)
    cap_command_nm: float  # the runner's --cap-nm on every step
    # the drive's own torque at the output: min(cap, the card's current-limited torque); the runner holds the model feed-forward's total under
    # it (experiments.feedforward_limit). None (a description from before 2026-11-04): the cap
    drive_torque_nm: float | None = None
    gravity_nm: float = 0.0  # the motor holds +G sin(q_abs - bottom) (identify.fit_gravity's sign)
    gravity_bottom_rad: float = 0.0
    coulomb_nm: float = 0.0
    inertia_kg_m2: float = 0.0
    kp_nm_rad: float = 0.0
    kd_nm_s_rad: float = 0.0
    integrator_scale: float = 0.0  # the ilimit_scale the board's own T2 command sends (1 where ki > 0 and ilimit is recorded)
    output_per_board: float = 1.0
    window_rad: tuple[float, float] | None = None  # the board-frame window this power cycle proved clear (TAPE_STATIONS)
    overspeed_rad_s: float | None = None
    rotor_rev_rad: float | None = None  # one rotor revolution at the output (2 pi / N): the ripple map's period
    floor_step: Mapping[str, Any] | None = None  # the station's floor tape (T1), a runner step, if it has one
    sources: Mapping[str, str] = field(default_factory=dict)
    # True: the board's integral is under the joint's linear stability bound (integral_over_bound < 1), so ff_fb keeps one scale on every
    # command (HOLD_ONLY_INTEGRAL's scope). Written into the document only when True (to_json), so a description without it reads False
    integral_within_bound: bool = False

    def torque(self, q, qd, qdd) -> np.ndarray:
        """The model's demand for a target relative to the origin: J qdd + G sin(q_abs - bottom) + Fc tanh(qd / band)."""

        absolute = self.origin_rad + np.asarray(q, float)
        return (self.inertia_kg_m2 * np.asarray(qdd, float) + self.gravity_nm * np.sin(absolute - self.gravity_bottom_rad)
                + self.coulomb_nm * np.tanh(np.asarray(qd, float) / FF_BAND_RAD_S))

    @property
    def pendulum_hz(self) -> float | None:
        return math.sqrt(self.gravity_nm / self.inertia_kg_m2) / (2 * math.pi) if self.gravity_nm > 0 and self.inertia_kg_m2 > 0 else None

    @property
    def closed_loop_hz(self) -> float | None:
        return math.sqrt(self.kp_nm_rad / self.inertia_kg_m2) / (2 * math.pi) if self.kp_nm_rad > 0 and self.inertia_kg_m2 > 0 else None

    def to_json(self) -> dict[str, Any]:
        out = dataclasses.asdict(self)
        out["sources"] = dict(self.sources)
        out["floor_step"] = dict(self.floor_step) if self.floor_step else None
        # WHY only when True (2026-11-05): the field came after every station was frozen; a station over its bound (CAN 11, 581ffd3e) or with
        # no integral (CAN 21, CAN 4) keeps its document, and so its digest, byte for byte
        if not self.integral_within_bound:
            out.pop("integral_within_bound")
        return out

    @classmethod
    def from_json(cls, values: Mapping[str, Any]) -> JointDescription:
        names = {item.name for item in dataclasses.fields(cls)}
        out = {key: value for key, value in values.items() if key in names}
        out["range_rad"] = tuple(out["range_rad"])
        out["window_rad"] = tuple(out["window_rad"]) if out.get("window_rad") else None
        return cls(**out)


def integral_over_bound(kp_nm_rad: float, kd_nm_s_rad: float, ki_nm_s_rad: float, inertia_kg_m2: float) -> float | None:
    """The board's integral over the joint's linear stability bound, output units: a PID on a rigid inertia, J s^3 + kd s^2 + kp s + ki, is
    stable for ki < kd kp / J (Routh), so 1 is the edge. None with no integral, no inertia or no damping (nothing to judge).

    WHY this number (2026-11-05, bam_ws docs/peps/0006-hold-only-integral.md): it is the PEP's mechanism. CAN 11 runs ki 16000 at 15.3x it,
    so its integral drives a 2-8 Hz cycle while the joint moves and the hold-only integral removes it; CAN 12 and 13 run the same gains on
    ~40x less inertia, 0.39x and 0.43x."""

    if ki_nm_s_rad <= 0.0 or inertia_kg_m2 <= 0.0 or kd_nm_s_rad <= 0.0 or kp_nm_rad <= 0.0:
        return None
    return float(ki_nm_s_rad / (kd_nm_s_rad * kp_nm_rad / inertia_kg_m2))


# --------------------------------------------------------------------------- the families


@dataclass(frozen=True)
class Runner:
    """A trajectory the player's runner plays as one step (its own fields, relative to the step's origin)."""

    step: dict[str, Any]
    params: dict[str, Any]


@dataclass(frozen=True)
class Sampled:
    """A trajectory with no runner kind (yet): q(t) from the origin, sampled here only."""

    q: Callable[[np.ndarray], np.ndarray]
    duration_s: float
    params: dict[str, Any]


@dataclass(frozen=True)
class TorqueOpenLoop:
    """An open-loop torque command (kp = kd = 0): tau(t) on top of the model's gravity hold at the origin; no position target."""

    tau: Callable[[np.ndarray], np.ndarray]
    duration_s: float
    params: dict[str, Any]


@dataclass(frozen=True)
class Family:
    name: str
    group: str  # "excite" | "operate"
    code: str  # the note's label (F0..F9, O)
    origin: str  # where the shape comes from
    runner: bool  # the player's runner has a kind for it
    make: Callable[..., Runner | Sampled | TorqueOpenLoop | None]
    variants: int = 0  # excite: how many fixed variants; 0: seeded (operate seeds)
    gain_sweep: bool = True  # excite families run at every kp level
    velocity_steps: bool = False  # the runner's kind commands velocity steps (triangle corners, plateaus, ramps): qdd is an impulse
    conditions: tuple[str, ...] = ()  # the modes it runs under ("fb", "release", "open_loop_torque", ...)
    note: str = ""


def register(registry: dict[str, Family], name: str, *, origin: str, runner: bool, group: str = "operate", code: str = "", variants: int = 0,
             gain_sweep: bool = True, velocity_steps: bool = False, conditions: Sequence[str] = (), note: str = ""):
    """A decorator registering ``make(description, rng, stretch[, variant]) -> Runner | Sampled | TorqueOpenLoop | None`` (None: not
    applicable to this joint) as a family in ``registry``. stretch >= 1 must slow it down (time x stretch). WHY a registry: the prior-art
    note's later recommendations are one decorated function each; the player owns its registry (the families it can play)."""

    def decorate(make):
        default_conditions = ("fb",) if group == "excite" else TRACKING_MODES
        registry[name] = Family(name, group, code, origin, runner, make, variants, gain_sweep, velocity_steps, tuple(conditions) or default_conditions, note)
        return make

    return decorate


def sides(description: JointDescription) -> tuple[float, float]:
    low, high = description.range_rad
    return max(0.0, -low), max(0.0, high)


def two_sided(description: JointDescription) -> float:
    return min(sides(description))


def side(description: JointDescription, rng: random.Random | None = None, variant: int | None = None) -> tuple[float, float]:
    below, above = sides(description)
    if below > 0.02 and above > 0.02:
        direction = (1.0 if variant % 2 == 0 else -1.0) if variant is not None else rng.choice((-1.0, 1.0))
    else:
        direction = 1.0 if above >= below else -1.0
    return direction, above if direction > 0 else below


def fade(t, duration: float, ramp: float) -> np.ndarray:
    """A raised-cosine fade in and out over ``ramp`` seconds: 0 at both ends, 1 between."""

    t = np.asarray(t, float)
    rise = 0.5 * (1 - np.cos(np.pi * np.clip(t / ramp, 0.0, 1.0)))
    fall = 0.5 * (1 - np.cos(np.pi * np.clip((duration - t) / ramp, 0.0, 1.0)))
    return np.where((t <= 0) | (t >= duration), 0.0, rise * fall)


# --------------------------------------------------------------------------- the player


@dataclass(frozen=True)
class Player:
    """What plays a schedule: everything the generator needs that the description alone cannot say.

    ``families``: the registry it can play; ``modes(description)``: its control modes, each with ``runner.status`` (runnable or not) and
    what it sends; ``sample(candidate)``: a candidate's target at ``rate_hz`` (``sample`` below, with its grid and its runner's own step
    schedule); ``step_of(description, candidate, q)``: the step a trajectory carries (None when it has none); ``velocity_kinds``: the
    step kinds that command velocity; ``run_time(document)``: seconds per mode; ``schema`` / ``note``: what the document says it is."""

    families: Mapping[str, Family]
    modes: Callable[[JointDescription], Mapping[str, Any]]
    sample: Callable[[Any], dict[str, Any]]
    step_of: Callable[[JointDescription, Any, np.ndarray], dict[str, Any] | None]
    velocity_kinds: Sequence[str]
    run_time: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    rate_hz: float
    schema: str
    note: str = ""


# --------------------------------------------------------------------------- sampling and the limits


def sample(candidate: Runner | Sampled | TorqueOpenLoop, *, fine_s: float, rate_hz: float,
           runner_schedule: Callable[[Mapping[str, Any]], tuple[Callable[[float], tuple[float | None, float]], float]] | None = None) -> dict[str, np.ndarray]:
    """The target at ``rate_hz`` (t, q, qd, qdd) from the step's origin; qdd differentiated on the ``fine_s`` grid, then decimated. A runner
    step is sampled by its player's ``runner_schedule(step) -> (schedule(t) -> (q or None, qd), duration)``: a velocity kind's q (None) is the
    integral of its commanded speed (what the servo servoes to); an open-loop torque run holds q = 0 and carries ``tau``."""

    decimate = int(round(1.0 / (rate_hz * fine_s)))
    if isinstance(candidate, Runner):
        if runner_schedule is None:
            raise TypeError("a Runner candidate is sampled by its player's runner_schedule")
        schedule, duration = runner_schedule(candidate.step)
        count = int(math.floor(duration / fine_s + 1e-9)) + 1
        fine_t = np.arange(count) * fine_s
        points = [schedule(t) for t in fine_t]
        fine_qd = np.array([qd for _, qd in points], float)
        if any(q is None for q, _ in points):
            fine_q = np.concatenate(([0.0], np.cumsum(fine_qd[:-1] * fine_s)))
        else:
            fine_q = np.array([q for q, _ in points], float)
    else:
        count = int(math.floor(candidate.duration_s / fine_s + 1e-9)) + 1
        fine_t = np.arange(count) * fine_s
        if isinstance(candidate, TorqueOpenLoop):
            fine_q = np.zeros(count)
        else:
            fine_q = np.asarray(candidate.q(fine_t), float)
        fine_qd = np.gradient(fine_q, fine_s)
    fine_qdd = np.gradient(fine_qd, fine_s)
    index = np.arange(0, count, decimate)
    out = {"t": np.round(fine_t[index], 9), "q": fine_q[index], "qd": fine_qd[index], "qdd": fine_qdd[index],
           "qdd_fine_peak": float(np.abs(fine_qdd).max()) if count else 0.0}
    if isinstance(candidate, TorqueOpenLoop):
        out["tau_cmd"] = np.asarray(candidate.tau(out["t"]), float)
    return out


def demand(description: JointDescription, target: Mapping[str, np.ndarray], velocity_steps: bool) -> np.ndarray:
    """The predicted torque: for a velocity-step kind the commanded impulse is not an acceleration the joint makes (the PD answers it
    within its cap), so its qdd is clipped to the accel envelope; an open-loop torque run is the command itself plus the gravity hold."""

    if "tau_cmd" in target:
        return target["tau_cmd"] + description.torque(target["q"], target["qd"], np.zeros_like(target["q"]))
    qdd = np.clip(target["qdd"], -description.accel_rad_s2, description.accel_rad_s2) if velocity_steps else target["qdd"]
    return description.torque(target["q"], target["qd"], qdd)


def violations(description: JointDescription, target: Mapping[str, np.ndarray], velocity_steps: bool = False, offset: float = 0.0) -> list[str]:
    """Every limit of the description the target crosses (range, speed, accel, torque), one line each; [] when inside them all."""

    low, high = description.range_rad
    q = target["q"] + offset
    out = []
    if q.min() < low - 1e-9 or q.max() > high + 1e-9:
        out.append(f"range {q.min():+.3f} .. {q.max():+.3f} outside {low:+.3f} .. {high:+.3f}")
    if np.abs(target["qd"]).max() > description.speed_rad_s:
        out.append(f"speed {np.abs(target['qd']).max():.3f} > {description.speed_rad_s:g}")
    if not velocity_steps and max(np.abs(target["qdd"]).max(), target["qdd_fine_peak"]) > description.accel_rad_s2:
        out.append(f"accel {max(np.abs(target['qdd']).max(), target['qdd_fine_peak']):.3f} > {description.accel_rad_s2:g}")
    torque = np.abs(demand(description, {**target, "q": q}, velocity_steps)).max()
    if torque > description.torque_limit_nm:
        out.append(f"torque {torque:.3f} > {description.torque_limit_nm:g}")
    return out


def rounded(values, digits: int = 6) -> list[float]:
    return [round(float(value), digits) for value in values]


def make(registered: Family, description: JointDescription, rng: random.Random, stretch: float, variant: int | None):
    if registered.variants and len(inspect.signature(registered.make).parameters) >= 4:
        return registered.make(description, rng, stretch, variant)
    return registered.make(description, rng, stretch)


# --------------------------------------------------------------------------- the build


def build_schedule(description: JointDescription, player: Player, *, seed: int = 0, families: Sequence[str],
                   operate_train_seeds: Sequence[int] = OPERATE_TRAIN_SEEDS, operate_held_out_seeds: Sequence[int] = OPERATE_HELD_OUT_SEEDS,
                   kp_levels: Sequence[float] = KP_LEVELS, held_out_kp: float | None = HELD_OUT_KP, held_out_families: Sequence[str] = (),
                   floor_repeats: int = FLOOR_REPEATS, minimum_pct: float, note_targets: Mapping[str, float]) -> dict[str, Any]:
    """The schedule document (``player.schema``): trajectories (each a target), and runs (a trajectory under a condition, with its split).

    Seeds: an operate trajectory's seed is ``seed * 1000 + s``; an excite trajectory's is ``seed * 1000 + 900 + variant``. Splits:
    excite runs at ``held_out_kp`` are H1, operate seeds in ``operate_held_out_seeds`` are H2, every run of a held-out family is
    held out; the floor is its own split. ``minimum_pct`` and ``note_targets``: the coverage gate and the note's targets (cards/ data).
    """

    names = list(families)
    unknown = [name for name in names if name not in player.families]
    if unknown:
        raise ValueError(f"unknown families {unknown}; registered: {sorted(player.families)}")
    modes = player.modes(description)
    trajectories, runs, rejected, skipped = [], [], [], []
    for name in names:
        registered = player.families[name]
        if registered.variants:
            items = [(seed * 1000 + 900 + variant, variant, None) for variant in range(registered.variants)]
        else:
            items = [(seed * 1000 + s, None, "train") for s in operate_train_seeds] + [(seed * 1000 + s, None, "held_out") for s in operate_held_out_seeds]
        for trajectory_seed, variant, operate_split in items:
            chosen, reasons, candidate = None, [], None
            for stretch in STRETCHES:
                candidate = make(registered, description, random.Random(f"{seed}:{name}:{trajectory_seed}"), stretch, variant)
                if candidate is None:
                    break
                target = player.sample(candidate)
                offset = origin_offset(description, candidate)
                reasons = violations(description, target, registered.velocity_steps, offset)
                # WHY the floor is kept as recorded: it is the station's T1 tape, already run on this board (10-24 and 10-29 floors); its
                # value is that it never changes, so a limit it passes over in this model is a finding about the model, listed, not a reason to drop it
                if not reasons or (registered.name == "floor" and candidate is not None):
                    chosen = (candidate, target, offset)
                    break
            if candidate is None and chosen is None and not reasons:
                skipped.append({"family": name, "seed": trajectory_seed, "variant": variant, "reason": "not applicable to this joint"})
                continue
            if chosen is None:
                rejected.append({"family": name, "seed": trajectory_seed, "variant": variant, "reasons": reasons})
                continue
            candidate, target, offset = chosen
            trajectory = trajectory_entry(description, registered, candidate, target, offset, trajectory_seed, variant, player)
            trajectory["limit_exceptions"] = reasons if registered.name == "floor" else []
            trajectories.append(trajectory)
            runs += runs_of(trajectory, registered, operate_split, kp_levels, held_out_kp, name in held_out_families, floor_repeats)
    document = {
        "schema": player.schema, "description": description.to_json(), "rate_hz": player.rate_hz, "seed": seed, "note": player.note,
        "families": {name: {"group": player.families[name].group, "code": player.families[name].code, "origin": player.families[name].origin,
                            "runner": player.families[name].runner, "note": player.families[name].note} for name in names},
        "split_rule": {"kp_levels": list(kp_levels), "held_out_kp": held_out_kp, "operate_train_seeds": [seed * 1000 + s for s in operate_train_seeds],
                       "operate_held_out_seeds": [seed * 1000 + s for s in operate_held_out_seeds], "held_out_families": list(held_out_families),
                       "rule": "whole factor levels are held out: H1 = every excite run at the held-out kp level; H2 = the operate seeds held out, "
                               "under every mode (the acceptance set); the floor is neither"},
        "modes": modes, "trajectories": trajectories, "runs": runs, "rejected": rejected, "skipped": skipped,
    }
    document["coverage"] = coverage(document, minimum_pct=minimum_pct, note_targets=note_targets)
    document["run_time"] = player.run_time(document)
    document["digest"] = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()[:16]
    return document


def origin_offset(description: JointDescription, candidate) -> float:
    """Where the step's own origin sits in the description's frame (a floor tape keeps the origin it was recorded from)."""

    if isinstance(candidate, Runner) and candidate.step.get("origin_rad") is not None:
        return float(candidate.step["origin_rad"]) * description.output_per_board - description.origin_rad
    return 0.0


def trajectory_entry(description, registered: Family, candidate, target, offset, trajectory_seed, variant, player: Player) -> dict[str, Any]:
    """One trajectory of the document: its target (rounded as stored), its predicted torque, its peaks and the step it carries."""

    q = target["q"] + offset
    torque = demand(description, {**target, "q": q}, registered.velocity_steps)
    runner_step = player.step_of(description, candidate, q)
    kind = "torque" if isinstance(candidate, TorqueOpenLoop) else ("velocity" if runner_step and runner_step["kind"] in player.velocity_kinds else "position")
    out = {
        "id": f"{registered.name}-s{trajectory_seed}", "family": registered.name, "group": registered.group, "code": registered.code,
        "family_origin": registered.origin, "seed": trajectory_seed, "variant": variant,
        "params": {key: (round(value, 6) if isinstance(value, float) else value) for key, value in candidate.params.items()},
        "runner_step": runner_step, "runner_kind": runner_step["kind"] if runner_step else None, "target_kind": kind,
        "velocity_steps": registered.velocity_steps, "origin_offset_rad": round(offset, 6),
        "returns_to_origin": registered.name != "swing", "counts_for_coverage": kind != "torque", "status": "not run yet",
        "duration_s": round(float(target["t"][-1]), 4), "torque_peak_nm": float(np.abs(torque).max()), "torque_rms_nm": float(np.sqrt(np.mean(torque**2))),
        "peaks": {"q_min": float(q.min()), "q_max": float(q.max()), "qd": float(np.abs(target["qd"]).max()), "qdd": float(np.abs(target["qdd"]).max())},
        "target": {"t": rounded(target["t"], 4), "q": rounded(q), "qd": rounded(target["qd"]), "qdd": rounded(target["qdd"], 5),
                   "tau_pred": rounded(torque, 5)},
    }
    if "tau_cmd" in target:
        out["target"]["tau_cmd"] = rounded(target["tau_cmd"], 5)
    return out


def runs_of(trajectory, registered: Family, operate_split, kp_levels, held_out_kp, held_out_family: bool, floor_repeats: int) -> list[dict[str, Any]]:
    """The runs of one trajectory, each with its split: the split rule (whole factor levels held out)."""

    out = []

    def add(mode, split, kp=1.0, repeat=None):
        run_id = f"{trajectory['id']}/{mode}" + (f"/kp{kp:g}" if registered.group == "excite" and registered.gain_sweep else "") + (f"/r{repeat}" if repeat else "")
        out.append({"run": run_id, "trajectory": trajectory["id"], "family": registered.name, "group": registered.group, "mode": mode,
                    "kp_level": kp, "split": "held_out" if held_out_family and split != "floor" else split,
                    "held_out_set": "family" if held_out_family else ("H1" if split == "held_out" and registered.group == "excite" else
                                                                       "H2" if split == "held_out" else None)})

    if registered.name == "floor":
        for repeat in range(1, floor_repeats + 1):
            add("fb", "floor", repeat=repeat)
    elif registered.group == "excite":
        for condition in registered.conditions:
            if registered.gain_sweep and condition == "fb":
                for kp in kp_levels:
                    add("fb", "held_out" if held_out_kp is not None and math.isclose(kp, held_out_kp) else "train", kp)
            else:
                add(condition, "train")
    else:
        conditions = ("fb",) if operate_split == "train" else registered.conditions
        for condition in conditions:
            add(condition, operate_split)
    return out


# --------------------------------------------------------------------------- coverage, before anything runs


def occupancy(samples: np.ndarray, edges: Sequence[np.ndarray]) -> np.ndarray:
    """Samples per cell as a dense array: robot_msgs.coverage's binning rule (numpy.histogramdd's: each bin [lo, hi), the last [lo, hi];
    samples outside are dropped), cell for cell equal to robot_msgs.coverage.occupancy (tests/test_schedule_joint.py).

    WHY vectorised here and not robot_msgs.coverage.occupancy itself: that is plain Python per point (a few hundred plan rows), and a
    schedule's split holds ~10^5 target samples per call; a dense numpy occupancy belongs in robot_msgs (reported as its gap, 2026-11-10)."""

    samples = np.asarray(samples, float).reshape(-1, len(edges))
    keep = np.ones(samples.shape[0], bool)
    indices = []
    for axis, edge in enumerate(edges):
        edge = np.asarray(edge, float)
        values = samples[:, axis]
        index = np.searchsorted(edge, values, side="right") - 1
        index = np.where(values == edge[-1], len(edge) - 2, index)
        keep &= (index >= 0) & (index < len(edge) - 1)
        indices.append(index)
    counts = np.zeros(tuple(len(edge) - 1 for edge in edges), np.int64)
    np.add.at(counts, tuple(index[keep] for index in indices), 1)
    return counts


QD_EDGE_FRACTIONS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)  # the note's +-{0.02 .. 2} rad/s at a 2 rad/s budget
QDD_EDGE_FRACTIONS = (0.00625, 0.025, 0.0625, 0.1875, 0.5, 1.0)  # the note's +-{0.5 .. 80} rad/s^2 shape, scaled to the accel envelope
Q_BINS = 12
TAU_CELL_NM = 0.25


def edges_of(description: Mapping[str, Any]) -> list[np.ndarray]:
    """(q, qd, qdd) edges: q in Q_BINS cells over the range; qd and qdd signed and log-spaced (the note's, robot_msgs.coverage.signed), a
    dead cell around 0."""

    low, high = description["range_rad"]
    return [np.linspace(low, high, Q_BINS + 1), np.array(signed(QD_EDGE_FRACTIONS, description["speed_rad_s"])),
            np.array(signed(QDD_EDGE_FRACTIONS, description["accel_rad_s2"]))]


def tau_edges(description: Mapping[str, Any]) -> np.ndarray:
    limit = description["torque_limit_nm"]
    cells = int(math.ceil(limit / TAU_CELL_NM))
    return np.arange(-cells, cells + 1) * TAU_CELL_NM


def reachable_cells(description: JointDescription, edges: Sequence[np.ndarray]) -> np.ndarray:
    """Cells whose centre the joint can hold: the demand inside the torque limit, and a speed it can brake from before the range ends."""

    q, qd, qdd = np.meshgrid(*(np.array(centres(list(edge))) for edge in edges), indexing="ij")
    low, high = description.range_rad
    torque_ok = np.abs(description.torque(q, qd, qdd)) <= description.torque_limit_nm
    room = np.where(qd > 0, high - q, q - low)
    braking_ok = qd**2 / (2 * description.accel_rad_s2) <= room + 1e-12
    return torque_ok & braking_ok


SPLITS = {"train": lambda run: run["split"] == "train", "held_out": lambda run: run["split"] == "held_out",
          "h1": lambda run: run["held_out_set"] == "H1", "h2": lambda run: run["held_out_set"] == "H2", "all": lambda run: True}


def split_samples(document: Mapping[str, Any], keep, columns=("q", "qd", "qdd")) -> np.ndarray:
    """Every kept run's target rows (once per run: a repeat counts again), the trajectories that count for coverage only."""

    by_id = {trajectory["id"]: trajectory for trajectory in document["trajectories"]}
    rows = [np.column_stack([by_id[run["trajectory"]]["target"][key] for key in columns]) for run in document["runs"]
            if keep(run) and by_id[run["trajectory"]]["counts_for_coverage"]]
    return np.vstack(rows) if rows else np.zeros((0, len(columns)))


def runnable(document: Mapping[str, Any], run: Mapping[str, Any]) -> bool:
    trajectory = next(item for item in document["trajectories"] if item["id"] == run["trajectory"])
    return trajectory["runner_step"] is not None and document["modes"][run["mode"]]["runner"]["status"] == "runnable"


def coverage(document: Mapping[str, Any], *, minimum_pct: float, note_targets: Mapping[str, float]) -> dict[str, Any]:
    """Occupancy of the target over the envelope, per split, before anything runs; the note's targets beside the v1 gate (``minimum_pct``:
    the share of reachable cells the train runs must visit)."""

    described = document["description"]
    description = JointDescription.from_json(described)
    edges = edges_of(described)
    reachable = reachable_cells(description, edges)
    total_reachable = max(1, int(reachable.sum()))
    out: dict[str, Any] = {"bins": [len(edge) - 1 for edge in edges], "edges": [rounded(edge, 6) for edge in edges],
                           "axes": ["q (rad from origin)", "qd (rad/s)", "qdd (rad/s^2)"], "reachable_cells": int(reachable.sum()),
                           "reachable_rule": "cell centre: |J qdd + G sin + Fc tanh| <= torque limit, and qd^2 / 2a <= the room left toward the "
                                             "range end it moves to", "counted": "every run's target once per run (a repeat counts again)"}
    counts = {}
    for name, keep in SPLITS.items():
        samples = split_samples(document, keep)
        counts[name] = occupancy(samples, edges)
        visited = counts[name] > 0
        out[name] = {"runs": sum(1 for run in document["runs"] if keep(run)), "samples": int(samples.shape[0]),
                     "samples_outside_envelope": int(samples.shape[0] - counts[name].sum()), "visited_cells": int(visited.sum()),
                     "visited_reachable": int((visited & reachable).sum()), "pct_reachable": round(100.0 * float((visited & reachable).sum()) / total_reachable, 2),
                     "visited_unreachable": int((visited & ~reachable).sum())}
    played = split_samples(document, lambda run: runnable(document, run))
    played_counts = occupancy(played, edges)
    out["runnable"] = {"pct_reachable": round(100.0 * float(((played_counts > 0) & reachable).sum()) / total_reachable, 2), "samples": int(played.shape[0])}
    outside = (counts["held_out"] > 0) & (counts["train"] == 0)
    held_samples = int(counts["held_out"].sum())
    out["held_out_outside_train"] = {"n": int(outside.sum()), "cells": [list(map(int, cell)) for cell in zip(*np.nonzero(outside))],
                                     "sample_pct": round(100.0 * float(counts["held_out"][outside].sum()) / max(1, held_samples), 2)}
    rich = counts["train"] >= note_targets["train_samples_per_cell"]
    h2 = int(counts["h2"].sum())
    out["note_targets"] = {
        "reachable_with_200_train_pct": round(100.0 * float((rich & reachable).sum()) / total_reachable, 2),
        "reachable_with_50_held_out_pct": round(100.0 * float(((counts["held_out"] >= note_targets["held_out_samples_per_cell"]) & reachable).sum()) / total_reachable, 2),
        "deployment_weighted_pct": round(100.0 * float(counts["h2"][rich].sum()) / max(1, h2), 2) if h2 else None,
        "targets": {"reachable_pct": note_targets["reachable_pct"], "deployment_weighted_pct": note_targets["deployment_weighted_pct"]},
    }
    out["note_targets"]["passes"] = {
        "reachable": out["note_targets"]["reachable_with_200_train_pct"] >= note_targets["reachable_pct"],
        "deployment_weighted": (out["note_targets"]["deployment_weighted_pct"] or 0.0) >= note_targets["deployment_weighted_pct"]}
    out["gate"] = {"minimum_pct": minimum_pct, "train_pct": out["train"]["pct_reachable"], "passes": out["train"]["pct_reachable"] >= minimum_pct,
                   "rule": "v1: the train runs visit at least this share of the reachable (q, qd, qdd) cells"}
    out["planes"] = planes(document, description, edges, reachable, counts)
    out["effects"] = effect_counters(document, description, note_targets)
    out["identifiability"] = identifiability(document, description, note_targets)
    return out


def planes(document, description, edges, reachable, counts) -> dict[str, list[dict[str, Any]]]:
    """The 2-D projections a schedule view draws: (q, qd) and (qd, qdd) from the 3-D counts, and (q, tau_pred) from the samples."""

    out = {}
    for plane, (a, b) in {"q_qd": (0, 1), "qd_qdd": (1, 2)}.items():
        other = ({0, 1, 2} - {a, b}).pop()
        reach_2d = reachable.any(axis=other)
        rows = []
        for split in ("train", "held_out"):
            projected = counts[split].sum(axis=other)
            for i in range(projected.shape[0]):
                for j in range(projected.shape[1]):
                    if reach_2d[i, j] or projected[i, j]:
                        rows.append({"split": split, "i": i, "j": j, "x0": float(edges[a][i]), "x1": float(edges[a][i + 1]), "y0": float(edges[b][j]),
                                     "y1": float(edges[b][j + 1]), "samples": int(projected[i, j]), "reachable": bool(reach_2d[i, j])})
        out[plane] = rows
    torque_edges = tau_edges(document["description"])
    q_edges = edges[0]
    rows = []
    for split in ("train", "held_out"):
        samples = split_samples(document, SPLITS[split], ("q", "tau_pred"))
        grid = occupancy(samples, [q_edges, torque_edges])
        for i in range(grid.shape[0]):
            for j in range(grid.shape[1]):
                if grid[i, j]:
                    rows.append({"split": split, "i": i, "j": j, "x0": float(q_edges[i]), "x1": float(q_edges[i + 1]), "y0": float(torque_edges[j]),
                                 "y1": float(torque_edges[j + 1]), "samples": int(grid[i, j]), "reachable": True})
    out["q_tau"] = rows
    return out


def effect_counters(document: Mapping[str, Any], description: JointDescription, note_targets: Mapping[str, float]) -> dict[str, Any]:
    """What a histogram cannot see (the note's 3.4 item 3), on the train runs: velocity reversals and the q cells they sit in, settled stops
    per approach direction and their positions, slow travel against one rotor revolution, and where the target's spectral power is."""

    rate_hz = document["rate_hz"]
    by_id = {trajectory["id"]: trajectory for trajectory in document["trajectories"]}
    q_edges = edges_of(document["description"])[0]
    reversals, reversal_cells, stops, stop_cells, slow_travel = 0, set(), {"+": 0, "-": 0}, {"+": set(), "-": set()}, 0.0
    band_power = {"below_1_hz": 0.0, "1_3_hz": 0.0, "3_8_hz": 0.0, "above_8_hz": 0.0}
    for run in document["runs"]:
        if run["split"] != "train":
            continue
        trajectory = by_id[run["trajectory"]]
        if not trajectory["counts_for_coverage"]:
            continue
        q, qd = np.asarray(trajectory["target"]["q"]), np.asarray(trajectory["target"]["qd"])
        moving = np.abs(qd) > 1e-3
        signs = np.sign(qd[moving])
        flips = np.nonzero(np.diff(signs) != 0)[0]
        reversals += flips.size
        reversal_cells |= {int(np.clip(np.searchsorted(q_edges, q[moving][index]) - 1, 0, Q_BINS - 1)) for index in flips}
        still = np.abs(qd) < 1e-6
        index = 0
        while index < still.size:
            if still[index]:
                end = index
                while end < still.size and still[end]:
                    end += 1
                if (end - index) / rate_hz >= 0.5 and index > 0:
                    direction = "+" if qd[index - 1] > 0 or (q[index] - q[max(0, index - 20)]) > 0 else "-"
                    stops[direction] += 1
                    stop_cells[direction].add(round(float(q[index]), 2))
                index = end
            else:
                index += 1
        slow = (np.abs(qd) < 0.1) & (np.abs(qd) > 0.005)
        slow_travel += float(np.sum(np.abs(qd[slow])) / rate_hz)
        if q.size > 8:
            spectrum = np.abs(np.fft.rfft(q - q.mean())) ** 2
            frequency = np.fft.rfftfreq(q.size, 1.0 / rate_hz)
            band_power["below_1_hz"] += float(spectrum[frequency < 1].sum())
            band_power["1_3_hz"] += float(spectrum[(frequency >= 1) & (frequency < 3)].sum())
            band_power["3_8_hz"] += float(spectrum[(frequency >= 3) & (frequency < 8)].sum())
            band_power["above_8_hz"] += float(spectrum[frequency >= 8].sum())
    total_power = sum(band_power.values()) or 1.0
    out = {"reversals": reversals, "reversal_q_cells": len(reversal_cells), "stops_per_direction": stops,
           "stop_positions": {key: len(value) for key, value in stop_cells.items()}, "slow_travel_rad": round(slow_travel, 3),
           "rotor_rev_rad": description.rotor_rev_rad, "band_power_pct": {key: round(100 * value / total_power, 4) for key, value in band_power.items()}}
    out["passes"] = {"reversals": reversals >= note_targets["reversals"] and len(reversal_cells) >= note_targets["reversal_q_cells"],
                     "stops": min(stops.values()) >= note_targets["stops_per_direction"] and min(len(v) for v in stop_cells.values()) >= note_targets["stop_positions"],
                     "rotor_revolution_slow": description.rotor_rev_rad is None or slow_travel >= description.rotor_rev_rad,
                     "power_3_8_hz": band_power["3_8_hz"] > 0}
    return out


def identifiability(document: Mapping[str, Any], description: JointDescription, note_targets: Mapping[str, float]) -> dict[str, Any]:
    """The note's 3.4 item 4 for the linear-in-parameters model tau = J qdd + a sin q_abs + b cos q_abs + Fc tanh(qd / band) + fv qd on
    the planned train targets: the scaled regressor's condition number and each parameter's predicted 95 % CI half-width at TORQUE_NOISE_NM
    per sample (independent samples: optimistic, 100 Hz samples are correlated), for the whole train set and for the operate set alone."""

    def report(keep) -> dict[str, Any] | None:
        samples = split_samples(document, keep)
        if samples.shape[0] < 10:
            return None
        q, qd, qdd = samples[:, 0], samples[:, 1], samples[:, 2]
        absolute = description.origin_rad + q
        columns = {"J": qdd, "Fc": np.tanh(qd / FF_BAND_RAD_S), "fv": qd}
        if description.gravity_nm:
            columns.update({"a_sin": np.sin(absolute), "b_cos": np.cos(absolute)})
        names = list(columns)
        matrix = np.column_stack([columns[name] for name in names])
        norms = np.linalg.norm(matrix, axis=0)
        if np.any(norms == 0):
            return {"condition_number": math.inf, "dead_columns": [name for name, n in zip(names, norms) if n == 0]}
        scaled = matrix / norms
        condition = float(np.linalg.cond(scaled))
        covariance = TORQUE_NOISE_NM**2 * np.linalg.pinv(matrix.T @ matrix)
        half = 1.96 * np.sqrt(np.diag(covariance))
        nominal = {"J": description.inertia_kg_m2, "Fc": description.coulomb_nm, "fv": None,
                   "a_sin": description.gravity_nm * math.cos(description.gravity_bottom_rad),
                   "b_cos": -description.gravity_nm * math.sin(description.gravity_bottom_rad)}
        params = {}
        for name, width in zip(names, half):
            value = nominal.get(name)
            params[name] = {"ci_half_width": float(width), "pct": round(100 * float(width) / abs(value), 3) if value else None}
        return {"samples": int(samples.shape[0]), "condition_number": round(condition, 3), "parameters": params,
                "passes": condition <= note_targets["condition_number"] and all(item["pct"] is None or item["pct"] <= note_targets["ci_half_width_pct"]
                                                                                 for item in params.values())}

    return {"noise_nm": TORQUE_NOISE_NM, "train": report(SPLITS["train"]),
            "operate_train_only": report(lambda run: run["split"] == "train" and run["group"] == "operate")}
