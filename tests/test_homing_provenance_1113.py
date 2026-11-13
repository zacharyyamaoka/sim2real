"""The homing results stamp the code that actually scored (pass 5's provenance, 2026-11-13).

homing_fivebar_real_2026-11-12.json says sim2real 8db26c3 and bam_ws d7d9f1b05, but its scorer (real_bench.score, RealRigPlant) landed
in 256c538 and the runner in bam_ws d6ed3bed9: the scorer ran uncommitted and ``real_bench.git_sha`` read HEAD with no dirty check, so a
dirty tree was stamped as a clean, older commit. What must hold: every homing writer's sha says ``-dirty`` when the tracked code under it
has changes (sim2real.provenance.code_sha); ``real_bench.score`` refuses to write with a dirty scorer (commit first, then score) unless
told ``allow_dirty``, and then says so (``provenance_clean`` false); the pass-5 JSON is not re-stamped, it carries a provenance_note.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_provenance_1113.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "other").mkdir()
    (repo / "pkg" / "a.py").write_text("x = 1\n")
    (repo / "other" / "b.py").write_text("y = 1\n")
    for argv in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "one"]):
        subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)
    return repo


def test_code_sha_says_dirty_only_for_changes_under_its_scope(tmp_path):
    from sim2real.provenance import code_sha

    repo = _repo(tmp_path)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert code_sha(repo / "pkg" / "a.py") == head  # any path inside the repo names it
    (repo / "other" / "b.py").write_text("y = 2\n")
    assert code_sha(repo / "pkg", scope=("pkg",)) == head  # a change outside the code that scored does not dirty it
    assert code_sha(repo / "pkg") == head + "-dirty"
    (repo / "pkg" / "a.py").write_text("x = 2\n")
    assert code_sha(repo / "pkg", scope=("pkg",)) == head + "-dirty"
    assert code_sha(tmp_path / "nowhere") == "unknown"


def test_every_homing_writer_stamps_a_dirty_tree_as_dirty(tmp_path):
    from sim2real.sim.homing import bench, real_bench, recovery_export

    repo = _repo(tmp_path)
    (repo / "pkg" / "a.py").write_text("x = 3\n")
    for module in (real_bench, recovery_export, bench):
        assert module.git_sha(repo).endswith("-dirty"), module.__name__


def test_the_real_score_refuses_a_dirty_scorer_before_it_writes(tmp_path, monkeypatch):
    from sim2real.sim.homing import real_bench

    monkeypatch.setattr(real_bench, "git_sha", lambda path: "8db26c3-dirty")
    out = tmp_path / "results.json"
    with pytest.raises(real_bench.DirtyProvenance, match="commit"):
        real_bench.score([], out=out)
    assert not out.exists()


def test_a_dirty_score_that_is_allowed_says_so(tmp_path, monkeypatch):
    from sim2real.sim.homing import real_bench

    monkeypatch.setattr(real_bench, "git_sha", lambda path: "8db26c3-dirty")
    stamps = real_bench.scorer_provenance(allow_dirty=True)
    assert stamps["provenance_clean"] is False and stamps["sim2real_sha"].endswith("-dirty")


def test_the_pass_5_real_json_carries_its_provenance_note_and_keeps_its_stamps():
    data = json.loads((DATA / "homing_fivebar_real_2026-11-12.json").read_text())
    assert data["sim2real_sha"] == "8db26c3" and data["bam_ws_sha"] == "d7d9f1b05"  # not re-stamped
    note = data["provenance_note"]
    assert "256c538" in note and "d6ed3bed9" in note
