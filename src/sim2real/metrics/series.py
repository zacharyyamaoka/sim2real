"""The rulers every comparison shares: one RMS, one centre, one clock, for real-vs-real (the floor) and model-vs-real (fidelity).

Moved from RobotDx (robotdx/diagnostics/data.py: rms, difference, on_common_clock, pair_rms, pairwise_rms, center) on 2026-11-10 (Zach,
proposal 2 step 4): RobotDx's stock checks and bam_rack_twin's gates computed T1-T4 from these, so they live once, here, and RobotDx
calls them. Behaviour unchanged to the bit; the RMS of a finite series is robot_msgs.compare.error_stats's own.

A series is ``(t, y)``: seconds from the tape's start and the signal, finite rows only.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from robot_msgs.compare import error_stats

__all__ = ["rms", "center", "difference", "on_common_clock", "pair_rms", "pairwise_rms", "repeat_floor", "RepeatFloor", "command_rms",
           "SAME_INPUT_TOLERANCE_RAD", "SAME_INPUT_TOLERANCE_RAD_S", "SAME_INPUT_TOLERANCE_NM", "FLOOR_MIN_REPEATS"]

# WHY a tolerance on the INPUT (2026-11-11 review, "Sim2Real KPIs and Gates", the floor check): a repeat is the same commanded input run
# again; two runs whose commands differ disagree for that reason, and pooling them made a floor 6-20x too big. 0.01 deg RMS on the
# command is the note's proposal (Zach to confirm).
SAME_INPUT_TOLERANCE_RAD = math.radians(0.01)
# WHY a tolerance per command channel (found in review, 2026-11-12): a position command is its position, its velocity and its feed-forward
# torque; compared on the position alone, five runs with identical position targets and velocity targets 0-4 rad/s apart were taken as
# same-input repeats (10 of 10 pairs) and made a "known" floor. Each channel is judged in its own unit:
# - a velocity target, 1 deg/s RMS: moteus's position loop turns a velocity difference into kd x dv, and on the UR wrist (kp 75 N.m/rev,
#   kd 1 N.m.s/rev) 1 deg/s holds the joint ~0.013 deg off; it also moves the board's setpoint 0.01 deg within one 10 ms tick - the
#   position tolerance either way;
# - a feed-forward torque, 1 mN.m RMS: through the softest wrist joint's position stiffness (75 N.m/rev = 11.9 N.m/rad) 1 mN.m holds it
#   ~0.005 deg off, half the position tolerance. The runners compute both from the plan, so true repeats agree to ~1e-12.
SAME_INPUT_TOLERANCE_RAD_S = math.radians(1.0)
SAME_INPUT_TOLERANCE_NM = 1e-3
FLOOR_MIN_REPEATS = 5  # T1 (cards/servo_gates.FLOOR_REPEATS): at least 5 repeats of one input before the floor is known
SINGLE = "command"  # the one channel of a command given as a single series (and its key in RepeatFloor.rejected_by / command_rms)


def rms(values) -> float:
    """RMS of a series; NaN for an empty one. WHY robot_msgs.compare (Zach, 2026-11-10: "tracking error from robot_msgs.compare"): a finite
    series' RMS is error_stats(...).rms, the one definition. A series holding a NaN or an inf has no RMS over its gap: the plain mean of
    squares answers it (NaN, or inf), exactly as RobotDx's rms always did, where error_stats would skip the gap."""

    values = np.asarray(values, float)
    if not values.size:
        return math.nan
    stats = error_stats(values)
    return stats.rms if stats.n == values.size else float(np.sqrt(np.mean(values ** 2)))


def center(values: Sequence[float | None], how: str = "median") -> float:
    """``median`` or ``median_high`` (the stdlib names) of the finite values; NaN with none. WHY a choice: bam_rack_twin's per-class twin
    ratio takes ``sorted(v)[n // 2]``, which is ``statistics.median_high``; the floor takes ``statistics.median``."""

    kept = [v for v in values if v is not None and math.isfinite(v)]
    if not kept:
        return math.nan
    return float(statistics.median_high(kept) if how == "median_high" else statistics.median(kept))


def difference(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """data-ui PEP 0010 §4.4 ``difference(a, b)``: on a's own samples inside b's span, b(t_i) - a(t_i), b linearly interpolated; no row
    outside b's span (never extrapolates). Returns (t_i, b - a)."""

    (t_a, y_a), (t_b, y_b) = a, b
    inside = (t_a >= t_b[0]) & (t_a <= t_b[-1])
    return t_a[inside], np.interp(t_a[inside], t_b, y_b) - y_a[inside]


def on_common_clock(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray], dt: float) -> tuple[np.ndarray, np.ndarray]:
    """Two (t, signal) series linearly interpolated onto one grid over their overlap: ``arange(max start, min end, dt)``. WHY beside
    ``difference``: bam_rack_twin's floor (gate T1) is defined on this shared clock. WHY max start, not 0 (2026-11-12): a held-out window
    that starts 30 s into a run was gridded from 0, and np.interp held the 30 s sample across 0-30 s, so the "held-out" RMS carried 30 s of
    a constant offset. For series that start at 0 (every floor and twin replay) the grid is unchanged."""

    (t_a, y_a), (t_b, y_b) = a, b
    grid = np.arange(max(t_a[0], t_b[0]), min(t_a[-1], t_b[-1]), dt)
    return np.interp(grid, t_a, y_a), np.interp(grid, t_b, y_b)


def pair_rms(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray], *, clock: str = "common", dt: float = 0.002) -> float:
    """RMS(b - a) on one clock: ``common`` (a shared grid of step dt) or ``a`` (a's own samples, PEP 0010)."""

    if clock == "a":
        return rms(difference(a, b)[1])
    y_a, y_b = on_common_clock(a, b, dt)
    return rms(y_b - y_a)


def pairwise_rms(series: Sequence[tuple[np.ndarray, np.ndarray]], *, clock: str = "common", dt: float = 0.002) -> list[tuple[int, int, float]]:
    """RMS of the difference for every pair (i < j). WHY one function: a fidelity ratio is never a ratio of two different rulers."""

    return [(i, j, pair_rms(a, b, clock=clock, dt=dt)) for (i, a), (j, b) in itertools.combinations(enumerate(series), 2)]


@dataclass(frozen=True)
class RepeatFloor:
    """The real device's run-to-run floor from same-input repeats: the median RMS between two responses to one command. `value` is in the
    signal's unit (rad for an angle) or None with no same-input pair; `known` needs `min_repeats` runs in those pairs. `rejected_by` counts
    the rejected pairs by the first reason: a command channel over its tolerance (``"command"`` for a single series), ``"length"`` or
    ``"channels"`` (the two runs' commands are not the same set of channels)."""

    value: float | None
    pairs: int            # same-input pairs the median is over
    runs: int             # distinct runs in those pairs
    rejected: int         # pairs dropped because their commands differ (or their lengths do)
    min_repeats: int = FLOOR_MIN_REPEATS
    rejected_by: Mapping[str, int] = field(default_factory=dict, hash=False)  # WHY hash=False: a dict cannot be hashed; a RepeatFloor still can

    @property
    def known(self) -> bool:
        return self.value is not None and self.runs >= self.min_repeats


def _channels(command) -> dict[str, np.ndarray]:
    """A run's command as {channel: values}: a mapping as given (each channel in its own unit), a single series as the one channel SINGLE."""
    if isinstance(command, Mapping):
        return {str(name): np.asarray(values, float) for name, values in command.items()}
    return {SINGLE: np.asarray(command, float)}


def _tolerances(tolerance, names) -> dict[str, float]:
    """Each channel's tolerance. WHY no default for a multi-channel command: its channels are in different units, and one number for all of
    them is a tolerance that is right in at most one."""
    if isinstance(tolerance, Mapping):
        missing = sorted(name for name in names if name not in tolerance)
        if missing:
            raise ValueError(f"no same-input tolerance for command channel(s) {missing}: give one per channel, in its own unit")
        return {name: float(tolerance[name]) for name in names}
    if set(names) != {SINGLE}:
        raise ValueError(f"a command with channels {sorted(names)} needs a same-input tolerance per channel (each in its own unit), not one number")
    return {SINGLE: float(tolerance)}


def _common_ticks(a, b) -> tuple[np.ndarray, np.ndarray] | None:
    """The indices of the plan ticks both runs sent (a's, b's); None when either run has no tick clock."""
    if len(a) < 4 or len(b) < 4 or a[3] is None or b[3] is None:
        return None
    _, ia, ib = np.intersect1d(np.asarray(a[3]), np.asarray(b[3]), return_indices=True)
    return ia, ib


def command_rms(a, b, *, dt: float = 0.002) -> dict[str, float] | None:
    """RMS of each command channel's difference between two runs, in the channel's unit: tick for tick on the plan ticks both sent when both
    carry a tick, else on the common clock (``pair_rms``). ``{"command": rms}`` for single-series commands; None when the two runs' commands
    are not the same set of channels. The numbers ``repeat_floor`` judges against its tolerances."""
    c_a, c_b = _channels(a[1]), _channels(b[1])
    if set(c_a) != set(c_b):
        return None
    ticked = _common_ticks(a, b)
    if ticked is not None:
        ia, ib = ticked
        return {name: rms(c_b[name][ib] - c_a[name][ia]) for name in c_a}
    return {name: pair_rms((a[0], c_a[name]), (b[0], c_b[name]), dt=dt) for name in c_a}


def repeat_floor(runs: Sequence[tuple], *, tolerance: float | Mapping[str, float] = SAME_INPUT_TOLERANCE_RAD,
                 min_repeats: int = FLOOR_MIN_REPEATS, dt: float = 0.002, length_tolerance: float = 0.03) -> RepeatFloor:
    """The floor over every pair of `runs` whose commands agree within `tolerance` RMS and whose lengths agree within `length_tolerance`;
    the rest are counted as rejected, never pooled. A run is ``(t from 0, command, response)`` or ``(t, command, response, tick)``.

    `command` is one series (judged against `tolerance`, one number) or ``{channel: series}`` - the whole command, e.g. position, velocity
    and feed-forward - each channel judged in its own unit against ``tolerance[channel]`` (a mapping with every channel; found in review,
    2026-11-12: identical positions with velocity targets 0-4 rad/s apart passed as repeats). Two runs whose commands are not the same set
    of channels are never the same input.

    WHY the tick clock first (2026-11-11, the five-bar's 5 repeats): a run that carries its plan tick (the commanded tape's sample index)
    is compared tick for tick, command and response alike; on the host wall clock, jitter put identical tapes 1.6-3.1 deg apart and
    rejected every true pair. Without a tick, both are aligned on a common wall clock (``pair_rms``)."""

    values, members, rejected, rejected_by = [], set(), 0, {}
    for (i, a), (j, b) in itertools.combinations(enumerate(runs), 2):
        c_a, c_b = _channels(a[1]), _channels(b[1])
        reason = None
        if set(c_a) != set(c_b):
            reason = "channels"
        else:
            limits = _tolerances(tolerance, c_a)
            ticked = _common_ticks(a, b)
            if ticked is not None:
                ia, ib = ticked
                span = max(len(a[3]), len(b[3]))
                same_length = abs(len(a[3]) - len(b[3])) <= length_tolerance * span and len(ia) >= (1 - length_tolerance) * span
            else:
                (t_a, y_a), (t_b, y_b) = (a[0], a[2]), (b[0], b[2])
                same_length = abs(t_a[-1] - t_b[-1]) <= length_tolerance * max(t_a[-1], t_b[-1])
            if not same_length:
                reason = "length"
            else:
                differences = command_rms(a, b, dt=dt)
                reason = next((name for name in c_a if not differences[name] <= limits[name]), None)
        if reason is not None:
            rejected += 1
            rejected_by[reason] = rejected_by.get(reason, 0) + 1
            continue
        if ticked is not None:
            value = rms(np.asarray(b[2])[ib] - np.asarray(a[2])[ia])
        else:
            value = pair_rms((t_a, y_a), (t_b, y_b), dt=dt)
        if math.isfinite(value):
            values.append(value)
            members.update((i, j))
    return RepeatFloor(float(statistics.median(values)) if values else None, len(values), len(members), rejected, min_repeats, rejected_by)
