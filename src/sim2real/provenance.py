"""Which code produced a result: the short sha of the git commit holding it, ``-dirty`` when the tracked code under it has changes.

WHY (2026-11-13, the homing pass-5 results): homing_fivebar_real_2026-11-12.json was stamped sim2real 8db26c3 while its scorer ran
uncommitted (it landed in 256c538) - the writer read HEAD with no dirty check, so a dirty tree went out as a clean, older commit. A result
names the commit its code is in only when that code has no uncommitted change; otherwise the stamp says ``-dirty``, and a scorer that must
not run dirty refuses (commit first, then run).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path


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


__all__ = ["code_sha", "is_clean"]
