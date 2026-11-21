"""A board's loop as the twin states it: the pieces of pidtuna's ``analytic.LoopModel`` (its rate, command delay, current loop, velocity
filter, one encoder count) that pidtuna's analytic bounds read, each a (value, source), or (None, why it is missing).

Read by sim2real.preflight (the gains check) and by the pendulum's PID tuna step (PidTune's stated loop, which holds the sim tune's climb).
WHY one reader (pidtuna CONTRACT amendment 3: no relative gain range; the climb and the deploy are held by the analytic bounds on the stated
loop): the tune and the check that gates its gains must read the same loop.

The board's own numbers come from its recorded config, copied into sim2real/data/board_configs.json (a moteus dump's lines, held equal to
the dump by tests/test_preflight_analytic_bounds.py): one encoder count is 2 pi x motor_position.rotor_to_output_ratio /
motor_position.sources.0.cpr (the count at the rotor, carried to the output), the velocity filter is motor_position.sources.0.pll_filter_hz
(fw motor_position.h: the PLL's w_n = pll_filter_hz / 2.48 x 2 pi at damping 1, so its -3 dB band is pll_filter_hz; pidtuna's loop models
it as a first-order filter at that corner), the current loop is servo.pid_dq_hz. The loop rate is the driver's robotparts datasheet
control_rate (its low end: the slower loop leaves the smaller margin). Imports nothing outside the standard library and sim2real.paths.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .. import paths

BOARD_CONFIGS = Path(__file__).resolve().parents[1] / "data" / "board_configs.json"
PARTS = ("dist", "site", "v2", "parts")   # robotparts' built part documents
CPR = "motor_position.sources.0.cpr"
RATIO = "motor_position.rotor_to_output_ratio"
PLL = "motor_position.sources.0.pll_filter_hz"
CURRENT_LOOP = "servo.pid_dq_hz"


def board(deployment: str | None, can_id: int | None) -> dict[str, Any] | None:
    """The copied config of one board ({lines, source, driver_part, ...}), or None when sim2real holds none for it."""
    if deployment is None or can_id is None or not BOARD_CONFIGS.is_file():
        return None
    return json.loads(BOARD_CONFIGS.read_text(encoding="utf-8")).get("deployments", {}).get(deployment, {}).get(str(int(can_id)))


def _cited(entry: dict, keys: str) -> str:
    return f"the board's recorded config ({keys}; sim2real/data/board_configs.json, copied from {entry['source']['dump']})"


def encoder_count(entry: dict | None) -> tuple[float | None, str]:
    """One encoder count at the output (rad) from the board's recorded config, or (None, why)."""
    lines = (entry or {}).get("lines", {})
    if CPR not in lines or RATIO not in lines or not float(lines[CPR]):
        return None, "no encoder count in the board's recorded config (sim2real/data/board_configs.json states no " + f"{CPR} / {RATIO})"
    count = 2.0 * math.pi * abs(float(lines[RATIO])) / float(lines[CPR])
    return count, _cited(entry, f"{CPR} {lines[CPR]:g} at the rotor x {RATIO} {lines[RATIO]:g}")


def velocity_filter(entry: dict | None) -> tuple[float | None, str]:
    """The velocity estimate's filter (Hz): moteus' PLL band from the board's recorded config, or (None, why)."""
    lines = (entry or {}).get("lines", {})
    if PLL not in lines:
        return None, f"no velocity filter in the board's recorded config (sim2real/data/board_configs.json states no {PLL})"
    return float(lines[PLL]), _cited(entry, f"{PLL} {lines[PLL]:g}: the PLL's -3 dB band (w_n = pll_filter_hz / 2.48 x 2 pi, damping 1), "
                                            "as pidtuna's first-order velocity filter")


def current_loop(entry: dict | None) -> tuple[float | None, str]:
    """The current loop's bandwidth (Hz) from the board's recorded config, or (None, why)."""
    lines = (entry or {}).get("lines", {})
    if CURRENT_LOOP not in lines:
        return None, f"no current loop in the board's recorded config (sim2real/data/board_configs.json states no {CURRENT_LOOP})"
    return float(lines[CURRENT_LOOP]), _cited(entry, f"{CURRENT_LOOP} {lines[CURRENT_LOOP]:g}")


def control_rate(part: str | None) -> tuple[float | None, str]:
    """The board loop's rate (Hz): the driver part's robotparts datasheet control_rate, the low end of a stated range; or (None, why)."""
    path = None if part is None else Path(paths.ROBOTPARTS, *PARTS, f"{part}.json")
    spec = json.loads(path.read_text(encoding="utf-8")).get("specs", {}).get("control_rate") if path is not None and path.is_file() else None
    raw = None if not spec else spec.get("value")
    scale = {"kHz": 1000.0, "Hz": 1.0}.get((spec or {}).get("unit"))
    if raw is None or scale is None:
        return None, f"no board loop rate: no robotparts datasheet of the driver{'' if part is None else f' {part}'} states its control_rate"
    low = min(raw) if isinstance(raw, (list, tuple)) else raw
    return float(low) * scale, (f"robotparts {part} control_rate {spec.get('raw') or raw} ({spec.get('source_url', 'its datasheet')}): "
                                "the low end, the slower loop")


def loop_model(analytic: Any, pieces: dict[str, tuple], **fixed: float) -> Any | None:
    """A pidtuna ``analytic.LoopModel`` from the five stated pieces (loop_hz, delay_s, torque_bandwidth_hz, velocity_filter_hz,
    encoder_quantum_rad), the rest pidtuna's own rules; None when any of the five is unstated (pidtuna then holds no analytic ceiling)."""
    names = ("loop_hz", "delay_s", "torque_bandwidth_hz", "velocity_filter_hz", "encoder_quantum_rad")
    if any(pieces.get(name, (None,))[0] is None for name in names):
        return None
    stated = {"loop_hz": pieces["loop_hz"][0], "delay_s": pieces["delay_s"][0], "torque_bandwidth_hz": pieces["torque_bandwidth_hz"][0],
              "velocity_filter_hz": pieces["velocity_filter_hz"][0], "position_quantum_rad": pieces["encoder_quantum_rad"][0]}
    return analytic.LoopModel(**{**stated, **fixed})


__all__ = ["BOARD_CONFIGS", "board", "control_rate", "current_loop", "encoder_count", "loop_model", "velocity_filter"]
