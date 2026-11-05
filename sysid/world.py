"""The hidden truth: the only reader of sysid/examples/<id>/world.json.

An example's RealWorld (its simulator playing the hardware) loads the truth through `load`; identification runs inside `sealed()`,
where `load` raises, so a fit that reaches for the truth fails loudly instead of passing quietly.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from . import EXAMPLES_DIR

_SEALED = 0


class SealedWorld(RuntimeError):
    """Raised when the hidden truth is read while identification runs."""


def path(example: str) -> Path:
    return EXAMPLES_DIR / example / "world.json"


def load(example: str) -> dict:
    if _SEALED:
        raise SealedWorld(f"the world of {example} is sealed while identification runs: a fit may read measurements and the description only")
    return json.loads(path(example).read_text(encoding="utf-8"))


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
