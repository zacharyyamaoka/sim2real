"""PEP 0001's merge gate: the three lanes (backend, aruco, site) together. Red until all three have landed on one branch; each lane's
own tests are green alone. The builders may not edit this file.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_docs_site_merged.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEBSITE = REPO / "website"


def test_one_click_plans_an_aruco_cell_in_dependency_order():
    """A camera reading ArUco stickers: the planner pulls the marker's declared setup (the camera tuned for ArUco accuracy) and orders
    lock -> id confirmation -> ArUco tuning -> bundle adjustment from the catalog's declarations, never a hand-written list."""
    import sim2real.calibration as cal  # noqa: PLC0415

    assert cal.options("aruco_marker").setup == ("camera.exposure_for_aruco",)
    plan = cal.plan({"tag": ("aruco_marker", "M2.kinematics.print_scale"), "cam": ("camera", "M0.measurement.pinhole")})
    ids = list(plan.ids)
    for rid in ("camera.exposure_lock", "aruco.id_confirm", "camera.exposure_for_aruco", "aruco.bundle_adjustment"):
        assert rid in ids, (rid, ids)
    assert ids.index("camera.exposure_lock") < ids.index("camera.exposure_for_aruco") < ids.index("aruco.bundle_adjustment")
    assert ids.index("aruco.id_confirm") < ids.index("camera.exposure_for_aruco")
    if "aruco.caliper_size" in ids:
        assert ids.index("aruco.caliper_size") < ids.index("aruco.bundle_adjustment"), "the bundle uses the caliper's print scale"


def test_the_aruco_routines_recovery_reaches_the_planner_metric():
    import sim2real.calibration as cal  # noqa: PLC0415

    plan = cal.plan({"tag": ("aruco_marker", "M2.kinematics.print_scale")})
    step = next(s for s in plan.steps if s.routine == "aruco.bundle_adjustment")
    assert step.recovery is not None and step.recovery["pass"] is True


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("merged_site")
    env = {**os.environ, "PYTHONPATH": f"{REPO / 'src'}:{REPO}"}
    env.pop("VIRTUAL_ENV", None)
    run = subprocess.run([sys.executable, str(WEBSITE / "build" / "build.py"), "--out", str(out)], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=900)
    assert run.returncode == 0, run.stderr[-3000:]
    return out


def test_the_site_documents_the_aruco_marker_and_the_backend(built):
    for path in ("types/aruco_marker/index.html", "routines/aruco.bundle_adjustment/index.html", "routines/camera.exposure_for_aruco/index.html",
                 "docs/calibrate/index.html", "api/index.html"):
        assert (built / path).is_file(), path
    api = (built / "api" / "index.html").read_text()
    for anchor in ("api-CalibrationConfig", "api-CalibrationRecord", "api-CalibrationPlan", "api-plan", "api-collect"):
        assert f'id="{anchor}"' in api, anchor
    marker = (built / "types" / "aruco_marker" / "index.html").read_text()
    assert 'data-routine="aruco.bundle_adjustment"' in marker
    assert "today&#x27;s model" in marker or "today's model" in marker


def test_the_examples_record_the_stable_calibration_schema():
    for name in ("pendulum_can11", "ur_wrist_test_rig"):
        recorded = json.loads((WEBSITE / "examples" / f"{name}.out.json").read_text())
        assert recorded["schema"] == "sim2real.calibration/1", name
