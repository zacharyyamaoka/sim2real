"""The oracle examples as ready-made twins: fixtures, not a registry (docs/decision-types-seam-2026-11-11.md, addendum 2).

    import sim2real
    twin = sim2real.examples.pendulum_can11()      # CAN 11 on the One Dof Test Rack swung as a pendulum: the one-DOF oracle
    twin = sim2real.examples.ur_wrist_test_rig()   # the UR wrist test rig on the one-click seam (sim2real.rig)

WHY fixtures and not a load(name) (Zach, 2026-11-11: "Sim2real just knows about the twin"): sim2real sits below robot_description and
keeps no registry of robots. A robot's twin comes from its description, description.to_robot_twin() (robot_description side: not built
yet), or is built directly, sim2real.RobotTwin(instances, name=...). Until robot_description can carry typed instances, each example's
instances come from its sysid manifest (sysid/examples/<name>/description.json) through twin.describe, the internal adapter: the
manifest's own units and sources on robot_msgs Values.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping

from . import paths
from .twin import RobotTwin, describe

RACK_PYTHON = paths.RACK_TWIN / ".venv" / "bin" / "python"  # bam_rack_twin's venv: the pendulum tracer's runtime


def pendulum_can11(*, models: Mapping[str, str] | None = None, workers: int = 6) -> RobotTwin:
    """CAN 11 on the One Dof Test Rack swung as a pendulum: seven typed instances, the servo's eight parameters as priors set apart from a
    hidden truth (sysid/examples/pendulum_can11/world.json). `models` picks the servo's rung ({"can11": "M3.dynamics.stribeck"}).

    Its runtime is bam_rack_twin's venv (the schedule, the twin of record and the replays are bam_rack_twin's; sysid's runtime), never
    sim2real's own env, which cannot carry bam_rack_twin (it depends on sim2real: the extra would be a cycle). From anywhere:
        env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sim2real.real --transport twin --out <folder>"""
    try:
        import bam_rack_twin  # noqa: F401, PLC0415
    except ModuleNotFoundError as error:
        # WHY a named way through instead of the bare error (2026-11-15: plan(pendulum_can11()) died in sim2real's own env with
        # "No module named 'bam_rack_twin'"): the description reads CAN 11's joint from bam_rack_twin, so the twin cannot be built without it
        raise ModuleNotFoundError(
            f"sim2real.examples.pendulum_can11() reads CAN 11 from bam_rack_twin, which this interpreter ({sys.executable}) cannot import. Run it "
            f"under bam_rack_twin's venv, e.g. env -u VIRTUAL_ENV {RACK_PYTHON} -m sim2real.real --transport twin --out <folder> "
            "(docs/CALIBRATE.md, \"on='real'\")", name="bam_rack_twin") from error
    return _twin("pendulum_can11", models=models, workers=workers)


def ur_wrist_test_rig(*, workers: int = 6) -> RobotTwin:
    """The UR wrist test rig: three servos calibrated by the rig's routine sequence (sysid/examples/ur_wrist_test_rig/rig.py)."""
    return _twin("ur_wrist_test_rig", workers=workers)


def _twin(name: str, *, models: Mapping[str, str] | None = None, workers: int = 6) -> RobotTwin:
    """The twin of a sysid/examples/<name> manifest, built directly (each fixture above)."""
    d = describe(name)
    return RobotTwin(d.instances, name=d.id, model_file=d.model, models=models, title=d.title, source=d.source, workers=workers)
