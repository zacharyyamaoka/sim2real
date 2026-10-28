"""Truthfulness: does a sensor report what is really there? A reported quantity against an independent reference.

Zach, 2026-10-28: "for a robot arm, we really are evaluating it on like trackecjtory tracking accuracy... but also like
turhtfully of the torque readings". A moteus board's torque is current x a Kt derived from its stored Kv, so torque
truthfulness has two stock checks:

- ``known_load_gain`` (gate T6, "drive gain"): reported torque vs a weighed mass on a measured lever, on slow up/down
  sweeps with the load on and off. The difference cancels the link's own gravity and the friction, leaving
  m g L sin(q - q_hang); the fitted slope is the drive gain. Prior art: ATI's known-mass check for F/T sensors
  (FT_FAQ.pdf), the Dyno note's disc-on/off run.
- ``kt_consistency``: the board's stored Kv against an independent calibration of the same motor. CAN 14 read 1/1.229 of
  true torque until 2026-10-23 because its Kv was a firmware-conversion artifact (rack_2026-10-23/analysis/kt_can14.json).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..core import Evidence, Limits, Measure, result
from ..data import Trajectory

GRAVITY = 9.80665


@dataclass(frozen=True)
class KnownLoadConfig:
    mass_kg: float | None = None  # the weighed load; None = no known load on this joint -> not run
    lever_m: float | None = None  # its centre of mass from the axis
    hang_angle_rad: float = 0.0  # joint angle at which the load hangs straight down
    sign: float = 1.0  # +1 if positive torque lifts the load at q > hang
    max_speed_rad_s: float = 0.5  # quasi-static rows only (inertia negligible)
    bins: int = 24
    min_rows_per_bin: int = 3
    limits: Limits = field(default_factory=lambda: Limits(warn_low=-2.0, warn_high=2.0, error_low=-5.0, error_high=5.0))
    # WHY +-5 % fail / +-2 % warn: bam_rack_twin T6 is +-5 % per unit and +-2 % per type (servo-ID note, gate K4)


@dataclass(frozen=True)
class KnownLoadInput:
    loaded: Sequence[Trajectory]  # slow sweeps with the known mass on
    unloaded: Sequence[Trajectory] = ()  # the same sweeps with it off


def _binned(runs: Sequence[Trajectory], edges: np.ndarray, config: KnownLoadConfig) -> np.ndarray:
    """Mean reported torque per (direction, q bin); NaN where a bin has too few quasi-static rows."""

    out = np.full((2, len(edges) - 1), np.nan)
    q = np.concatenate([run.channel("q_rad")[run.rows(controlled_only=True)] for run in runs]) if runs else np.zeros(0)
    qd = np.concatenate([run.channel("qd_rad_s")[run.rows(controlled_only=True)] for run in runs]) if runs else np.zeros(0)
    tau = np.concatenate([run.channel("tau_nm")[run.rows(controlled_only=True)] for run in runs]) if runs else np.zeros(0)
    slow = np.isfinite(q) & np.isfinite(tau) & (np.abs(qd) <= config.max_speed_rad_s) & (np.abs(qd) > 1e-4)
    for direction, moving in enumerate((qd > 0, qd < 0)):
        rows = slow & moving
        index = np.digitize(q[rows], edges) - 1
        for b in range(len(edges) - 1):
            mine = tau[rows][index == b]
            if mine.size >= config.min_rows_per_bin:
                out[direction, b] = float(mine.mean())
    return out


def known_load_gain(config: KnownLoadConfig, data: KnownLoadInput):
    """Drive gain k from  tau_loaded - tau_unloaded = k * m g L sin(q - q_hang), least squares through the origin,
    each direction separately then averaged (Coulomb cancels). Value: (k - 1) in %."""

    title = "torque truthfulness (known load)"
    if config.mass_kg is None or config.lever_m is None:
        return result(config, value=None, unit="%", metric="gain_error", limits=config.limits, title=title,
                      message="no weighed load on this joint: drive gain not measured", code="NoKnownLoad")
    if not data.loaded or not data.unloaded:
        return result(config, value=None, unit="%", metric="gain_error", limits=config.limits, title=title,
                      message="needs load-on and load-off sweeps of the same range", code="NoBaselineSweep")
    q_all = np.concatenate([run.channel("q_rad") for run in (*data.loaded, *data.unloaded)])
    edges = np.linspace(np.nanmin(q_all), np.nanmax(q_all), config.bins + 1)
    difference = _binned(data.loaded, edges, config) - _binned(data.unloaded, edges, config)
    centers = 0.5 * (edges[:-1] + edges[1:])
    reference = config.sign * config.mass_kg * GRAVITY * config.lever_m * np.sin(centers - config.hang_angle_rad)
    gains = []
    for direction in range(2):
        ok = np.isfinite(difference[direction])
        if ok.sum() >= 3:
            ref, diff = reference[ok], difference[direction][ok]
            gains.append(float(np.sum(ref * diff) / np.sum(ref * ref)))
    if not gains:
        return result(config, value=None, unit="%", metric="gain_error", limits=config.limits, title=title,
                      message="too few quasi-static rows in both sweeps", code="TooFewRows")
    gain = float(np.mean(gains))
    both = np.nanmean(difference, axis=0)
    ok = np.isfinite(both)
    residual = float(np.sqrt(np.mean((both[ok] - gain * reference[ok]) ** 2)))
    value = 100.0 * (gain - 1.0)
    return result(config, value=value, unit="%", metric="gain_error", limits=config.limits, title=title,
                  message=f"reported torque = {gain:.3f} x the weighed load's ({config.mass_kg:g} kg at {config.lever_m:g} m)",
                  measurements=(Measure("gain", gain), Measure("bins", int(ok.sum())), Measure("residual", residual, "N.m")),
                  payload={"x": reference[ok].tolist(), "y": both[ok].tolist(), "x_label": "m g L sin(q - q_hang) (N.m)",
                           "y_label": "reported torque, load on - off (N.m)"},
                  evidence=tuple(Evidence(run.run, "tau_nm") for run in (*data.loaded, *data.unloaded)))


@dataclass(frozen=True)
class KtReadings:
    kv_board_rpm_per_v: float | None  # what the board stores (it derives Kt = 8.27 / Kv)
    kv_reference_rpm_per_v: float | None  # an independent measurement of the same motor (moteus_tool --calibrate --cal-no-update)
    reference: str = ""  # how the reference was taken: the evidence pointer


@dataclass(frozen=True)
class KtConsistencyConfig:
    limits: Limits = field(default_factory=lambda: Limits(error_low=0.95, warn_low=0.98, warn_high=1.02, error_high=1.05))


def kt_consistency(config: KtConsistencyConfig, data: KtReadings):
    """Reported / true torque = Kt_board / Kt_true = Kv_true / Kv_board (Kt is proportional to 1/Kv)."""

    title = "torque truthfulness (Kt vs calibration)"
    if not data.kv_board_rpm_per_v or not data.kv_reference_rpm_per_v:
        return result(config, value=None, unit="1", metric="reported_over_true", limits=config.limits, title=title,
                      message="needs the board's stored Kv and an independent calibration", code="NoReference")
    ratio = data.kv_reference_rpm_per_v / data.kv_board_rpm_per_v
    return result(config, value=ratio, unit="1", metric="reported_over_true", limits=config.limits, title=title,
                  message=f"board Kv {data.kv_board_rpm_per_v:g} vs measured {data.kv_reference_rpm_per_v:g}: torque reads {ratio:.3f} of true",
                  measurements=(Measure("kv_board_over_reference", data.kv_board_rpm_per_v / data.kv_reference_rpm_per_v),),
                  evidence=(Evidence(data.reference, "kv"),) if data.reference else ())
