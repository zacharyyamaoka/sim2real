"""The hidden truth: the only reader of sysid/examples/<id>/world.json.

An example's RealWorld (its simulator playing the hardware) loads the truth through `load`; identification runs inside `sealed()`,
where `load` raises, so a fit that reaches for the truth fails loudly instead of passing quietly.

The noise ladder (sysid/noise_ladder.json, sysid/ladder.py) runs the same RealWorld at other noise: inside `noise_scale(k)` every value
of a world's "noise" block is k times its committed value (the same seeds draw the same normals, so the noise is exactly k times the
1x draw), and inside `perturbed(name, value)` a RealWorld that knows the perturbation (a late channel, a quantised one) applies it.
Outside both, `load` returns world.json unchanged and `perturbation` is None: the oracle's committed numbers do not move.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from . import EXAMPLES_DIR

_SEALED = 0
_NOISE_SCALE = [1.0]
_PERTURBATIONS: list[dict] = [{}]


class SealedWorld(RuntimeError):
    """Raised when the hidden truth is read while identification runs."""


def path(example: str) -> Path:
    return EXAMPLES_DIR / example / "world.json"


def load(example: str) -> dict:
    if _SEALED:
        raise SealedWorld(f"the world of {example} is sealed while identification runs: a fit may read measurements and the description only")
    doc = json.loads(path(example).read_text(encoding="utf-8"))
    scale = _NOISE_SCALE[-1]
    if scale != 1.0 and "noise" in doc:
        doc["noise"] = {name: _scaled(value, scale) for name, value in doc["noise"].items()}
    return doc


def _scaled(value, scale: float):
    if isinstance(value, (list, tuple)):
        return [_scaled(v, scale) for v in value]
    return float(value) * scale


@contextlib.contextmanager
def noise_scale(scale: float):
    """Every world's sensor noise times `scale` while it runs (the noise ladder's level); 1.0 leaves world.json as committed."""
    if not scale >= 0.0:
        raise ValueError(f"a noise scale is >= 0, not {scale!r}")
    _NOISE_SCALE.append(float(scale))
    try:
        yield
    finally:
        _NOISE_SCALE.pop()


@contextlib.contextmanager
def perturbed(name: str | None, value: float | None = None):
    """One named measurement perturbation (a noise-ladder variant: sysid/noise_ladder.json "variants") while it runs; None, nothing."""
    _PERTURBATIONS.append({} if name is None else {name: float(value)})
    try:
        yield
    finally:
        _PERTURBATIONS.pop()


def perturbation(name: str) -> float | None:
    """The active value of a named perturbation, or None: a RealWorld reads it where its measurement would carry it."""
    return _PERTURBATIONS[-1].get(name)


def noise_level() -> float:
    return _NOISE_SCALE[-1]


@contextlib.contextmanager
def sealed():
    global _SEALED
    _SEALED += 1
    try:
        yield
    finally:
        _SEALED -= 1


def is_sealed() -> bool:
    return _SEALED > 0
