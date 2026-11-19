"""The one ``default=`` sim2real hands json.dumps for what json cannot write itself (numpy scalars and arrays, tuples and sets, paths).

WHY one module (gap E, 2026-11-18): the real backend's submission and record files and a calibration's ledger (sim2real.calibration.
callbacks) write the same values, so they share one rule instead of two copies drifting apart. Moved here from real.py, which still
imports it under its old name. Stdlib only at import (numpy is checked by module name, never imported here).
"""

from __future__ import annotations

import sys
from pathlib import Path


def _json_default(value):
    """numpy scalars as Python numbers, arrays as lists, tuples and sets as lists, paths as text; anything else is refused (TypeError)."""
    np = sys.modules.get("numpy")   # a numpy value exists only once numpy is imported, so it is never imported here
    if np is not None and isinstance(value, (np.generic, np.ndarray)):
        return value.tolist()       # a scalar's tolist() is its Python number, an array's its nested lists
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def json_default_or_text(value):
    """_json_default, else the value's text. WHY a fallback for ledgers only: an observer must never lose a whole event over one value
    json cannot write (a NoiseModel inside a config); the real backend's files keep the strict rule."""
    try:
        return _json_default(value)
    except TypeError:
        return str(value)
