"""A result's code stamp names the code that computed it: writing results is not a code change (2026-11-05).

Every example and drift result carries provenance.code, HEAD's short sha, with "+dirty" when the code under it was not committed.
`python -m sysid all --write` writes results/<id>.json one example at a time, so a stamp that counted sysid/results as code read
"+dirty" on every example after the first: the results committed on 2026-11-05 all said 782bd5e+dirty, on every oracle page.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sysid import result

FILES = ("sysid/arm.py", "sysid/examples/ur5e/world.json", "sysid/results/ur5e.json", "type_cards/registry.py", "site/landing.py")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   check=True, capture_output=True)


def committed_repo(root: Path) -> Path:
    for rel in FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("0\n")
    git(root, "init", "-q")
    git(root, "add", "--", *FILES)
    git(root, "commit", "-q", "-m", "base")
    return root


def test_writing_results_is_not_a_code_change(tmp_path):
    repo = committed_repo(tmp_path)
    clean = result.code_version(repo)
    assert clean not in ("", "unknown") and "+dirty" not in clean
    (repo / "sysid/results/ur5e.json").write_text("1\n")
    (repo / "sysid/results/conveyor.json").write_text("1\n")
    assert result.code_version(repo) == clean, "a rewritten or new results file stamped the code dirty"
    (repo / "site/landing.py").write_text("1\n")
    assert result.code_version(repo) == clean, "the site renders results; it does not compute them"


def test_a_change_to_what_computes_results_is_dirty(tmp_path):
    for rel in ("sysid/arm.py", "sysid/examples/ur5e/world.json", "type_cards/registry.py", "sysid/new_module.py"):
        repo = committed_repo(tmp_path / rel.replace("/", "_"))
        clean = result.code_version(repo)
        (repo / rel).write_text("1\n")
        assert result.code_version(repo) == clean + "+dirty", rel
