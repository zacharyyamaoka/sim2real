"""claw_rung's episode cache: a run that loses a worker resumes from the episodes it already has (written before the cache exists).

    env -u VIRTUAL_ENV /home/bam/sim2real/.venv/bin/python -m pytest -q tests/test_homing_claw_rung_cache_1113.py

WHY (2026-11-13, the first claw run): fleet-throttle's memory guard SIGTERMed one pool worker at 07:08 (load ~60, swap full); a
multiprocessing.Pool replaces the worker but its task is lost, so imap_unordered waited forever at 283 of 288 episodes and no results file
was written. Every finished episode now goes to a JSONL cache as it lands; a rerun skips what the cache holds.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("coal", reason="claw_rung imports the homing rung (robot_models' contact extra)")


def _output(start: str) -> tuple:
    return ("claw comp", "claw", 1.0, "B0", start, {"outcome": "done", "start": start}, {"status": "ok"}, 12.5)


def test_an_episode_written_to_the_cache_reads_back_as_done(tmp_path):
    from sim2real.sim.homing import claw_rung

    cache = tmp_path / "episodes.jsonl"
    claw_rung.append_cache(cache, _output("real-00"))
    claw_rung.append_cache(cache, _output("real-01"))
    outputs = claw_rung.load_cache(cache)
    assert [o[4] for o in outputs] == ["real-00", "real-01"]
    assert outputs[0] == _output("real-00")


def test_a_torn_last_line_is_ignored(tmp_path):
    from sim2real.sim.homing import claw_rung

    cache = tmp_path / "episodes.jsonl"
    claw_rung.append_cache(cache, _output("real-00"))
    with cache.open("a") as handle:
        handle.write('{"comp": "claw co')  # the process died mid-write
    assert [o[4] for o in claw_rung.load_cache(cache)] == ["real-00"]


def test_pending_skips_the_jobs_the_cache_holds():
    from sim2real.sim.homing import claw_rung

    class Start:
        def __init__(self, name):
            self.name = name

    jobs = [("claw comp", "path", "claw", 1.0, "B0", Start("real-00"), None), ("claw comp", "path", "claw", 1.0, "B0", Start("real-01"), None),
            ("plate comp", "path", "claw", 1.0, "B0", Start("real-00"), None)]
    left = claw_rung.pending(jobs, [_output("real-00")])
    assert [(job[0], job[5].name) for job in left] == [("claw comp", "real-01"), ("plate comp", "real-00")]


def test_a_missing_cache_is_empty(tmp_path):
    from sim2real.sim.homing import claw_rung

    assert claw_rung.load_cache(tmp_path / "absent.jsonl") == []
    assert json.loads(json.dumps(list(_output("x"))))[4] == "x"
