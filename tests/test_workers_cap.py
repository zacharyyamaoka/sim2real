"""A twin's `workers` caps every pool its calibration opens (2026-11-17, red first).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_workers_cap.py

WHY: RobotTwin.from_robot_description(rd, workers=2).calibrate() opened an 8-worker pool beside the powered arm (host load 35, the rig
coordinator's report, 2026-11-17 18:58): SimRunner.calibrate called the pendulum's identify() without workers, so its friction polish
took identify's default of 8. Zach's rule while the rig is powered is at most 2 workers across every lane. The real backend already passed
it (sim2real.real, 2026-11-15); the sim backend and sysid's own pendulum callers did not.
"""

from __future__ import annotations

import inspect

import pytest

import sim2real
from sim2real import twin as twin_module


class _Stop(Exception):
    pass


def test_the_sim_backend_hands_its_workers_to_identify(monkeypatch):
    twin = sim2real.examples.pendulum_can11(workers=2)
    seen = {}

    class World:
        truth, noise, seed = {}, {}, 0

        def __init__(self, d, *, workers):
            seen["RealWorld"] = workers

        def measure(self, plan):
            return type("Measured", (), {"train": {}})()

    class Module:
        RealWorld = World

        @staticmethod
        def plan(d):
            return object()

        @staticmethod
        def identify(d, train, **options):
            seen["identify"] = options.get("workers")
            raise _Stop

    monkeypatch.setattr(twin.runner, "pipeline", lambda: Module)
    monkeypatch.setattr(twin.runner, "sysid_description", lambda: object())
    with pytest.raises(_Stop):
        twin.runner.calibrate()
    assert seen == {"RealWorld": 2, "identify": 2}


def test_the_pendulum_identify_still_takes_workers():
    twin_module._sysid()  # puts this checkout (sysid's home) on the path
    from sysid.examples.pendulum_can11 import pipeline  # noqa: PLC0415

    assert "workers" in inspect.signature(pipeline.identify).parameters


@pytest.mark.parametrize("path, needle", [
    ("sysid/drift.py", "commissioned_values = P.identify(description, measured.train, workers=workers)"),
    ("sysid/ladder.py", "P.identify(description, measured.train, workers=workers)"),
])
def test_sysids_own_pendulum_callers_pass_workers(path, needle):
    assert needle in (twin_module.REPO / path).read_text(encoding="utf-8")
