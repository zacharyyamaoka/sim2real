"""W&B refuses a tag over 64 characters (pass 7, 2026-11-13: 'recover_first(fed)+single_touch_c1seek+gff · real form · CAD mass · ff
nominal' is 76); every tag records() writes must fit, and the full procedure stays in the config and the run name."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("coal", reason="bench.expand needs robot_models' contact extra")

PASS7 = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "homing_fivebar_mujoco_pass7_2026-11-13.json"


@pytest.mark.skipif(not PASS7.is_file(), reason="the pass-7 results file is not in this checkout")
def test_every_tag_fits_wandbs_64_characters():
    from sim2real.tracking.homing import records

    out = records(json.loads(PASS7.read_text()))
    assert max(len(t) for r in out for t in r["tags"]) <= 64
    long = [r for r in out if len(r["config"]["procedure"]) > 64]
    assert long and all(r["config"]["procedure"] in r["name"] for r in long)
    assert len({tuple(r["tags"]) for r in out}) == len(out), "the shortened tags still tell the runs apart"
