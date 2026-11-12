"""How well each calibration routine recovers a hidden truth, per noise level: the ONE reader of the recovery ladders, shared by the
planner (its metric) and the docs site (the routines table's 0x / 1x / 3x / 10x columns). Frozen by PEP 0001; lanes read it, never fork it.

Two sources, both committed results held to their code by their own tests:

- ``sysid/results/calibration_routines.json`` (``sysid.calibration_routines/1``, written by sysid/routines.py from the noise ladder):
  one row per catalog routine, ``row["recovery"][level]``.
- ``sysid/results/routine_ladders/<routine id>.json`` (``sim2real.routine_ladder/1``): one file per routine graded OUTSIDE the sysid
  noise ladder (the ArUco marker routines, the camera's ArUco exposure tuning, and any rig routine on the one-click seam), written by the
  hidden-truth test that grades it. A ladder file wins over a calibration_routines.json row for the same routine (it is the newer,
  routine-specific grading).

A level entry is ``{"pass": bool | None, "worst_error_over_tolerance": float | None, ...}``; anything else in it is carried, never read
here. A routine nobody graded returns None: unknown stays unknown, never a guessed number.

WHY stdlib only and no import of cards: the site and the planner both call it at build time; it reads files, and a routine id is an opaque
key (cards/CONTRACT.md: never parse an id).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LEVELS = ("0x", "1x", "3x", "10x")
ROUTINES_JSON = Path("sysid") / "results" / "calibration_routines.json"
LADDER_DIR = Path("sysid") / "results" / "routine_ladders"
LADDER_SCHEMA = "sim2real.routine_ladder/1"


@lru_cache(maxsize=8)
def ladders(root: str | None = None) -> dict[str, dict[str, dict]]:
    """{routine id: {level: entry}} over both sources (a ladder file wins). `root` is the checkout (default: this one)."""
    base = Path(root) if root else REPO
    out: dict[str, dict[str, dict]] = {}
    table = base / ROUTINES_JSON
    if table.is_file():
        for row in json.loads(table.read_text()).get("rows", []):
            levels = {k: v for k, v in (row.get("recovery") or {}).items() if k in LEVELS and isinstance(v, dict)}
            if levels:
                out[row["routine"]] = levels
    folder = base / LADDER_DIR
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            doc = json.loads(path.read_text())
            if doc.get("schema") != LADDER_SCHEMA:
                raise ValueError(f"{path}: schema {doc.get('schema')!r}, expected {LADDER_SCHEMA!r}")
            unknown = sorted(set(doc.get("levels", {})) - set(LEVELS))
            if unknown:
                raise ValueError(f"{path}: levels {unknown} are not {LEVELS}")
            out[doc["routine"]] = {k: dict(v) for k, v in doc["levels"].items()}
    return out


def recovery(routine_id: str, level: str = "1x", *, root: str | None = None) -> dict | None:
    """The routine's recovery entry at `level` ({"pass", "worst_error_over_tolerance", ...}), or None when nobody graded it there."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, not {level!r}")
    return ladders(root).get(routine_id, {}).get(level)


def source(routine_id: str, *, root: str | None = None) -> str | None:
    """Which committed file grades the routine (a path relative to the checkout), or None."""
    base = Path(root) if root else REPO
    if (base / LADDER_DIR / f"{routine_id}.json").is_file():
        return str(LADDER_DIR / f"{routine_id}.json")
    return str(ROUTINES_JSON) if routine_id in ladders(root) else None
