"""Every homing results file says whether its code stamps are clean (``provenance_clean``), not only real_bench's (pass-6 check, 2026-11-13).

The independent check of pass 6 found homing_fivebar_mujoco_pass6_2026-11-13.json has no ``provenance_clean`` key: gff_rung (like bench,
mujoco_bench, wrist and home_button) stamped its shas with ``-dirty`` where due but never said clean or not, so "stamped 520a8ed, clean"
rested on reading the suffixes by hand - and that file's bam_ws stamp is ``b37778bb1-dirty``. What must hold: one rule
(sim2real.provenance.stamps_clean: every code stamp present names a commit with no uncommitted change) and one writer
(provenance.write_results) that every homing results writer goes through, which adds ``provenance_clean`` and never turns a writer's own
false into true; the pass-6 MuJoCo JSON is not re-stamped, it gains the rule's verdict and a provenance_note.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_provenance_clean_1113.py
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data"


def test_the_rule_is_clean_only_when_every_code_stamp_names_a_clean_commit():
    from sim2real.provenance import stamps_clean

    assert stamps_clean({"sim2real_sha": "520a8ed", "robot_models_sha": "17869ad", "bam_ws_sha": "b37778bb1"}) is True
    assert stamps_clean({"sim2real_sha": "520a8ed", "robot_models_sha": "17869ad", "bam_ws_sha": "b37778bb1-dirty"}) is False
    assert stamps_clean({"sim2real_sha": "unknown"}) is False
    assert stamps_clean({"sim2real_sha": "520a8ed", "bam_ws_sha": ["b37778bb1", "d6ed3bed9-dirty"]}) is False  # runs that disagree
    assert stamps_clean({"bundle_sha": "8957130"}) is False  # no code stamp at all: nothing says which code ran
    assert stamps_clean({"sim2real_sha": "520a8ed", "bundle_sha": "8957130-dirty"}) is True  # a CAD bundle id is not a code stamp


def test_write_results_adds_the_verdict_and_never_upgrades_a_writers_false(tmp_path):
    from sim2real.provenance import write_results

    out = tmp_path / "a.json"
    write_results(out, {"sim2real_sha": "520a8ed", "bam_ws_sha": "b37778bb1-dirty", "x": 1.5})
    assert json.loads(out.read_text()) == {"sim2real_sha": "520a8ed", "bam_ws_sha": "b37778bb1-dirty", "x": 1.5, "provenance_clean": False}
    write_results(out, {"sim2real_sha": "520a8ed", "provenance_clean": False})  # e.g. real_bench --allow-dirty
    assert json.loads(out.read_text())["provenance_clean"] is False
    write_results(out, {"sim2real_sha": "520a8ed"}, indent=1, newline=True)
    assert out.read_text() == json.dumps({"sim2real_sha": "520a8ed", "provenance_clean": True}, indent=1) + "\n"


def test_every_homing_results_writer_goes_through_write_results():
    from sim2real.sim.homing import bench, gff_rung, home_button, mujoco_bench, real_bench, wrist

    for writer in (bench.main, gff_rung.main, mujoco_bench.main, wrist.main, home_button.main, real_bench.score):
        source = inspect.getsource(writer)
        assert "write_results(" in source, writer.__qualname__
        assert "write_text(json.dumps(" not in source, f"{writer.__module__}.{writer.__qualname__} writes results around the rule"


def test_the_pass_6_mujoco_json_gains_the_rules_verdict_and_a_note_and_keeps_its_stamps():
    data = json.loads((DATA / "homing_fivebar_mujoco_pass6_2026-11-13.json").read_text())
    assert (data["sim2real_sha"], data["robot_models_sha"], data["bam_ws_sha"]) == ("520a8ed", "17869ad", "b37778bb1-dirty")  # not re-stamped
    assert data["provenance_clean"] is False
    assert "b37778bb1-dirty" in data["provenance_note"] and "bit-identical" in data["provenance_note"]
