"""Which code produced a result: the short sha of the git commit holding it, ``-dirty`` when the tracked code under it has changes.

WHY (2026-11-13, the homing pass-5 results): homing_fivebar_real_2026-11-12.json was stamped sim2real 8db26c3 while its scorer ran
uncommitted (it landed in 256c538) - the writer read HEAD with no dirty check, so a dirty tree went out as a clean, older commit. A result
names the commit its code is in only when that code has no uncommitted change; otherwise the stamp says ``-dirty``, and a scorer that must
not run dirty refuses (commit first, then run).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

# The keys a results file names its CODE by (a CAD bundle id such as ``bundle_sha`` is content, not code). WHY a fixed list: the pass-6
# check (2026-11-13) found the MuJoCo results stamped ``bam_ws_sha`` "b37778bb1-dirty" while nothing in the file said clean or not.
CODE_STAMPS = ("sim2real_sha", "robot_models_sha", "bam_ws_sha")


def _git(directory: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(directory), *argv], capture_output=True, text=True, check=True).stdout


def code_sha(path: Path | str, *, scope: Sequence[str] | None = None) -> str:
    """The short sha of the commit ``path`` (a file or directory inside a git work tree) is checked out at, plus ``-dirty`` when a tracked
    file has an uncommitted change - anywhere in that tree, or only under ``scope`` (paths relative to its top) when given. "unknown" when
    ``path`` is in no git tree (or git is missing)."""

    path = Path(path)
    directory = path if path.is_dir() else path.parent
    try:
        top = Path(_git(directory, "rev-parse", "--show-toplevel").strip())
        sha = _git(top, "rev-parse", "--short", "HEAD").strip()
        status = _git(top, "status", "--porcelain", "--untracked-files=no", "--", *(scope or ()))
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if status.strip() else "")


def is_clean(sha: str) -> bool:
    """A stamp that names a commit and no uncommitted change."""

    return sha != "unknown" and not sha.endswith("-dirty")


def stamps_clean(results: Mapping[str, Any]) -> bool:
    """The rule: true only when ``results`` names its code (at least one of ``CODE_STAMPS``) and every code stamp present - a sha, or a
    list of them when runs disagree - is clean (:func:`is_clean`)."""

    present = [results[key] for key in CODE_STAMPS if key in results]
    values = [v for value in present for v in (value if isinstance(value, (list, tuple)) else [value])]
    return bool(values) and all(isinstance(v, str) and is_clean(v) for v in values)


def write_results(path: Path | str, results: Mapping[str, Any], *, indent: int | None = None,
                  default: Callable[[Any], Any] | None = None, newline: bool = False) -> dict:
    """Write a results file with ``provenance_clean`` by :func:`stamps_clean` - and a writer's own false (e.g. a dirty score it was told to
    allow) is never turned into true. Returns what was written."""

    out = dict(results)
    out["provenance_clean"] = stamps_clean(out) and out.get("provenance_clean", True) is not False
    Path(path).write_text(json.dumps(out, indent=indent, default=default) + ("\n" if newline else ""))
    return out


__all__ = ["CODE_STAMPS", "code_sha", "is_clean", "stamps_clean", "write_results"]
