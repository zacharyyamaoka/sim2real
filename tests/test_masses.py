"""sim2real's copy of bam_fb_v2's measured masses (sim2real.masses): the copy is the file SOURCE names, ``check`` tells a copy that matches
its description from one that does not, and sim2real's ``apply`` is bam_pid_tunning's ``apply_mass_file`` body by body (when bam_ws' copy of
it is importable). bam_ws PEP 0060 and its addendum.

    env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_masses.py
"""

from __future__ import annotations

import copy
import json
import sys

import numpy as np
import pytest

from sim2real import masses
from sim2real.paths import BAM_WS, BAM_WS_SRC
from sim2real.sim.homing import fullarm_home as fh
from sim2real.sim.homing.mujoco_plant import available as twin_available

needs_twin = pytest.mark.skipif(not (twin_available() and fh.CAD_EXPORTER.is_dir()), reason="bam_ws's twin or the cad-exporter clone is not here")


def test_the_copy_is_the_file_source_names():
    data = json.loads(masses.BAM_FB_V2.read_text())
    assert masses.sha256(masses.BAM_FB_V2) == masses.SOURCE["sha256"] and data["schema"] == masses.SCHEMA
    assert masses.SOURCE["path"].endswith(masses.BAM_FB_V2.name.replace("bam_fb_v2", "bam_fb_v2_masses_2026-11-15c"))
    shoulder = data["bodies"]["shoulder"]
    assert shoulder["mass_kg"] == pytest.approx(shoulder["cad_mass_kg"], abs=1e-9)  # J1 never sees the shoulder's mass: the CAD's, kept
    assert abs(shoulder["com_m"][1]) < 0.002 < abs(shoulder["cad_com_m"][1])  # its COM across J1's plane: measured ~0, the CAD's 32 mm


def _fake_bam_ws(root, *, pointer: str | None, payload: bytes):
    record = root / masses.RECORD
    record.parent.mkdir(parents=True)
    record.write_text("from x import MeasuredMasses\nMEASURED_MASSES = MeasuredMasses(path=%r, bodies={})\n" % pointer if pointer else "DESCRIPTION = 1\n")
    if pointer:
        (root / pointer).parent.mkdir(parents=True, exist_ok=True)
        (root / pointer).write_bytes(payload)
    return root


def test_check_tells_same_from_differs_from_no_pointer(tmp_path):
    same = _fake_bam_ws(tmp_path / "a", pointer=masses.SOURCE["path"], payload=masses.BAM_FB_V2.read_bytes())
    assert masses.check(same)["status"] == "same"
    edited = _fake_bam_ws(tmp_path / "b", pointer=masses.SOURCE["path"], payload=masses.BAM_FB_V2.read_bytes() + b" ")
    assert masses.check(edited)["status"] == "differs"
    moved = _fake_bam_ws(tmp_path / "c", pointer="src/x/bam_fb_v2_masses_2026-12-01.json", payload=masses.BAM_FB_V2.read_bytes())
    assert masses.check(moved)["status"] == "differs"
    assert masses.check(_fake_bam_ws(tmp_path / "d", pointer=None, payload=b""))["status"] == "no pointer"


def test_the_copy_matches_the_description_in_the_bam_ws_checkout():
    """The workstation's (or a cloud job's) bam_ws: the copy is the file its description names. Skips while that checkout predates PEP
    0060 (the workstation's default checkout is not kept at origin/main - this module's WHY)."""

    result = masses.check(BAM_WS)
    if result["status"] == "no pointer":
        pytest.skip(result["why"] + f" ({BAM_WS})")
    assert result["status"] == "same", result


@needs_twin
def test_apply_is_bam_pid_tunnings_rule_body_by_body():
    """sim2real.masses.apply against bam_pid_tunning.plants.mass_file.apply_mass_file (bam_ws' copy, when importable) on the twin's own
    MJCF: every body's mass, COM and inertia equal (so the twin and the gravity FF read the same arm)."""

    source = BAM_WS_SRC / "core" / "mdp" / "setup" / "bam_pid_tunning" / "src"
    if not (source / "bam_pid_tunning" / "plants" / "mass_file.py").is_file():
        pytest.skip(f"bam_pid_tunning is not in {BAM_WS_SRC}")
    sys.path.insert(0, str(source))
    try:
        from bam_pid_tunning.plants.mass_file import apply_mass_file
    finally:
        sys.path.remove(str(source))
    base = fh.build_rig(masses="cad").model
    ours, theirs = copy.copy(base), copy.copy(base)
    changed = masses.apply(ours)
    apply_mass_file(theirs, masses.BAM_FB_V2)
    assert set(changed) == set(json.loads(masses.BAM_FB_V2.read_text())["bodies"])
    for field in ("body_mass", "body_ipos", "body_inertia"):
        assert np.array_equal(getattr(ours, field), getattr(theirs, field)), field
