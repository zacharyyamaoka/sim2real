"""RobotTwin.from_robot_description(rd) for ANY exported robot description: the nominal world (step 7 of Zach's 2026-11-19 pipeline,
"RobotDescription -> RobotTwin -> .calibrate()", for any exported robot).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_from_robot_description_nominal.py

The ruler, written before the code (red first). A description whose unit binds no sysid calibration world is no longer refused: its twin's
sim plant is a NOMINAL world, the description's own MJCF at the description's own nominal Values, and calibrate(on="sim") plays the
schedule plan(twin) shows against it. With no move the fit recovers the nominal values; with move_truth it recovers the MOVED values, each
within its routine's tolerance, and every move is wider than two tolerances, so a fit that ignores the move fails here.

The oracles are independent of the code under test: the moved values are this file's own numbers, and the nominal world's physics is
checked through MuJoCo itself (the gravity torque mj_forward computes at several angles against the description's G sin(q - bottom)).

Golden cases:
    the pendulum: CAN 11's description (bam_rack_twin.description.station_description(11)) with its record pointed at a component no
        manifest names (world="nominal") or at no unit at all (record None), calibrated on sim with a moved gravity and damping;
    a CAD-exported chain: the UR wrist test rig's Cad2Robot bundle (cad2robot/1: robot.json + mjcf/scene.xml, three GIM4305 servos),
        read into a description here with typed Values and robotparts parts, calibrated on sim with a moved friction and damping.

The pendulum's bound path (its sysid world wins whenever its record names it) is tests/test_from_robot_description.py, unchanged.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from robot_msgs.space import Basis, Value

import sim2real
from sim2real import RobotTwin
from sim2real.calibration import plan

BUNDLE = Path(os.environ.get("SIM2REAL_UR_WRIST_BUNDLE",
                             "/home/bam/bam_ws/src/dev/bam_ur_wrist/bundles/placeholder/ur_wrist_test_rig"))
ROBOTPARTS_PARTS = Path(os.environ.get("SIM2REAL_ROBOTPARTS", "/home/bam/robotparts")) / "user" / "parts"

PENDULUM_MOVE = {"can11.gravity_nm": 5.2, "can11.damping_nm_s_rad": 0.25}
WRIST_MOVE = {"revolute_14.frictionloss_nm": 0.06, "revolute_17.damping_nm_s_rad": 0.02}


# --- the descriptions -------------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rd():
    from bam_rack_twin.description import station_description  # noqa: PLC0415

    return station_description(11)


@dataclass(frozen=True)
class Component:
    """One component in the description shape from_robot_description reads (tests/test_from_robot_description.py's docstring)."""
    id: str
    title: str
    type: str
    parent: str | None
    parameters: dict[str, Value | None] = field(default_factory=dict)
    binds: dict[str, Any] = field(default_factory=dict)
    part: str | None = None


@dataclass(frozen=True)
class Description:
    name: str
    title: str
    model: str
    source: str
    record: dict | None
    components: tuple[Component, ...]


def wrist_description() -> Description:
    """The UR wrist test rig's Cad2Robot bundle as a description: each exported joint an integrated_servo bound to its MJCF joint and CAN
    id, its armature and friction the bundle's own numbers (robot.json, with the bundle's source line), its damping the MJCF's, its part the
    robotparts folder of the servo the bundle's datasheet names. No unit: a CAD export names no deployment record yet (record None)."""
    doc = json.loads((BUNDLE / "robot.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "cad2robot/1"
    import mujoco  # noqa: PLC0415

    model = mujoco.MjModel.from_xml_path(str(BUNDLE / doc["mjcf"]))
    servo_part = "steadywin-gim4305-10"   # the datasheet steadywin_gim4305_10shs, as a robotparts user/ part folder
    components = [Component("cell", "bench cell", "deployment", None),
                  Component("wrist", doc["design"], "rigid_body_chain", "cell")]
    for joint in doc["joints"]:
        source = f"cad2robot/1 {BUNDLE.name}/robot.json: {joint['source'].get('actuator') or joint['source'].get('all')}"
        damping = float(model.joint(joint["name"]).damping[0])
        components.append(Component(
            joint["name"], joint["station"], "integrated_servo", "wrist",
            {"armature_kg_m2": Value(joint["armature_kg_m2"], "kg·m²", basis=Basis.ASSUMED, source=source),
             "frictionloss_nm": Value(joint["frictionloss_nm"], "N·m", basis=Basis.ASSUMED, source=source),
             "damping_nm_s_rad": Value(damping, "N·m·s/rad", basis=Basis.ASSUMED, source=f"{BUNDLE.name}/{doc['mjcf']} joint damping")},
            {"joint": joint["name"], "station": joint["can_id"]}, servo_part))
    return Description("ur_wrist_test_rig_cad", doc["design"], str(BUNDLE / doc["mjcf"]), f"cad2robot/1 bundle {BUNDLE}", None,
                       tuple(components))


@pytest.fixture(scope="module")
def wrist_rd():
    if not (BUNDLE / "robot.json").exists():
        pytest.skip(f"no Cad2Robot bundle at {BUNDLE} (SIM2REAL_UR_WRIST_BUNDLE)")
    return wrist_description()


@pytest.fixture(scope="module")
def pendulum(rd):
    return RobotTwin.from_robot_description(dataclasses.replace(rd, record={**rd.record, "component": "can11_nominal"}), world="nominal",
                                            workers=1)


@pytest.fixture(scope="module")
def wrist(wrist_rd):
    return RobotTwin.from_robot_description(wrist_rd, workers=1)


@pytest.fixture(scope="module")
def pendulum_fitted(pendulum):
    return pendulum.calibrate(on="sim")


@pytest.fixture(scope="module")
def pendulum_moved(pendulum):
    return pendulum.calibrate(on="sim", move_truth=PENDULUM_MOVE)


@pytest.fixture(scope="module")
def wrist_moved(wrist):
    return wrist.calibrate(on="sim", move_truth=WRIST_MOVE)


def _tolerance(twin: RobotTwin, key: str, true: float) -> float:
    """The routine's tolerance on `key` at the value `true`, from the rig's own parameter table."""
    p = next(p for p in twin.runner.rig.parameters() if p.key == key)
    assert p.routine is not None and p.tolerance is not None, f"{key} is not identified with a tolerance ({p.why_not})"
    kind, value = p.tolerance
    return float(value) if kind == "abs" else float(value) * abs(true)


def _recovered(fitted: RobotTwin, key: str) -> float:
    instance, name = key.split(".", 1)
    return float(fitted.parameters[instance][name])


# --- which world binds -----------------------------------------------------------------------------------------------------------------


def test_a_bound_unit_still_plays_its_sysid_world(rd):
    twin = RobotTwin.from_robot_description(rd, workers=1)
    assert type(twin.runner).__name__ == "SimRunner"
    assert twin.description.id == "pendulum_can11"


def test_an_unknown_unit_is_still_refused_by_default_and_names_the_nominal_world(rd):
    with pytest.raises(LookupError, match="world='nominal'"):
        RobotTwin.from_robot_description(dataclasses.replace(rd, record={**rd.record, "component": "can99"}))


def test_a_description_with_no_unit_builds_a_nominal_world(rd):
    twin = RobotTwin.from_robot_description(dataclasses.replace(rd, record=None), workers=1)
    assert type(twin.runner).__name__ == "RigRunner"
    assert Path(twin.description.model).resolve() == Path(rd.model).resolve()


def test_world_nominal_builds_from_the_description_itself(pendulum, rd):
    assert type(pendulum.runner).__name__ == "RigRunner"
    assert {i.id: i.part for i in pendulum.instances} == {c.id: c.part for c in rd.components}
    assert {f"{i.id}.{n}": (None if v is None else float(v)) for i in pendulum.instances for n, v in i.parameters.items()} == {
        f"{c.id}.{n}": (None if v is None else float(v)) for c in rd.components for n, v in (c.parameters or {}).items()}
    assert not pendulum.fitted


def test_an_unknown_world_word_is_refused(rd):
    with pytest.raises(ValueError, match="world"):
        RobotTwin.from_robot_description(rd, world="hidden")


def test_a_description_with_no_model_is_refused_by_name(rd):
    with pytest.raises(ValueError, match="model"):
        RobotTwin.from_robot_description(dataclasses.replace(rd, record=None, model=None))


# --- the nominal world is the description's MJCF at the description's values ------------------------------------------------------------


def test_the_nominal_world_plays_the_descriptions_gravity_and_inertia(pendulum):
    import mujoco  # noqa: PLC0415

    values = {k: float(v) for k, v in pendulum.description.values().items() if v is not None}
    model = pendulum.runner.rig.model_at(values)
    data = mujoco.MjData(model)
    g, bottom = values["can11.gravity_nm"], values["can11.gravity_bottom_rad"]
    for q in (-1.0, -0.2, 0.3, 1.2):
        data.qpos[:] = q
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data)
        # qfrc_bias is what holds the link still at q: the gravity load, G sin(q - bottom) for the description's lumped one-DOF load
        assert data.qfrc_bias[0] == pytest.approx(g * math.sin(q - bottom), rel=1e-6, abs=1e-9)
    import numpy as np  # noqa: PLC0415

    dense = np.zeros((model.nv, model.nv))
    mujoco.mj_fullM(model, dense, data.qM)
    assert dense[0, 0] == pytest.approx(values["can11.armature_kg_m2"], rel=1e-9)   # the lumped inertia about the hinge
    assert model.dof_damping[0] == pytest.approx(values["can11.damping_nm_s_rad"])
    assert model.dof_frictionloss[0] == pytest.approx(values["can11.frictionloss_nm"])


def test_the_chain_world_sets_each_joints_values(wrist):
    values = {k: float(v) for k, v in wrist.description.values().items() if v is not None}
    moved = {**values, "revolute_14.frictionloss_nm": 0.07, "revolute_17.damping_nm_s_rad": 0.03, "revolute_11.armature_kg_m2": 2e-4}
    model = wrist.runner.rig.model_at(moved)
    assert model.joint("revolute_14").frictionloss[0] == pytest.approx(0.07)
    assert model.joint("revolute_17").damping[0] == pytest.approx(0.03)
    assert model.joint("revolute_11").armature[0] == pytest.approx(2e-4)


# --- the schedule ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["pendulum", "wrist"])
def test_plan_shows_typed_runs_and_the_identified_keys(which, request):
    from robot_msgs.trajectory import JointTrajectory  # noqa: PLC0415

    twin = request.getfixturevalue(which)
    schedule = plan(twin)
    print(f"\n{which}: {schedule.summary()}")
    assert schedule.steps, "the schedule is empty"
    for step in schedule.steps:
        assert step.runs, f"{step.routine} shows no runs"
        for run in step.runs:
            assert isinstance(run.command, JointTrajectory), run
    identified = {k for step in schedule.steps for k in step.routine_object.identifies}
    moves = PENDULUM_MOVE if which == "pendulum" else WRIST_MOVE
    assert set(moves) <= identified


# --- calibrate(on="sim") against the nominal world --------------------------------------------------------------------------------------


def test_with_no_move_the_fit_recovers_the_nominal_values(pendulum, pendulum_fitted):
    print("\n" + pendulum_fitted.calibration_.summary())
    assert pendulum_fitted.fitted
    identified = {k for step in pendulum_fitted.plan_.steps for k in step.routine_object.identifies}
    nominal = {k: float(v) for k, v in pendulum.description.values().items() if v is not None}
    for key in identified:
        got = _recovered(pendulum_fitted, key)
        assert abs(got - nominal[key]) <= _tolerance(pendulum, key, nominal[key]), (key, got, nominal[key])
    assert pendulum_fitted.calibration_.passed


def test_with_a_moved_truth_the_fit_recovers_the_moved_values(pendulum, pendulum_moved):
    print("\n" + pendulum_moved.calibration_.summary())
    nominal = {k: float(v) for k, v in pendulum.description.values().items() if v is not None}
    for key, moved in PENDULUM_MOVE.items():
        tol = _tolerance(pendulum, key, moved)
        # WHY: a move inside two tolerances would pass a fit that ignores it; this file's moves are wider
        assert abs(moved - nominal[key]) > 2 * tol, (key, moved, nominal[key], tol)
        got = _recovered(pendulum_moved, key)
        assert abs(got - moved) <= tol, f"{key}: recovered {got:.6g}, moved to {moved:.6g} (nominal {nominal[key]:.6g}), tolerance {tol:.3g}"


def test_the_chain_recovers_its_moved_values(wrist, wrist_moved):
    print("\n" + wrist_moved.calibration_.summary())
    nominal = {k: float(v) for k, v in wrist.description.values().items() if v is not None}
    for key, moved in WRIST_MOVE.items():
        tol = _tolerance(wrist, key, moved)
        assert abs(moved - nominal[key]) > 2 * tol, (key, moved, nominal[key], tol)
        got = _recovered(wrist_moved, key)
        assert abs(got - moved) <= tol, f"{key}: recovered {got:.6g}, moved to {moved:.6g} (nominal {nominal[key]:.6g}), tolerance {tol:.3g}"


def test_the_wrist_parts_are_robotparts_folders(wrist_rd):
    folders = {p.name for p in ROBOTPARTS_PARTS.rglob("*") if p.is_dir()}
    for c in wrist_rd.components:
        if c.part is not None:
            assert c.part in folders, c.part


def test_the_fitted_twin_evaluates_on_held_out_runs(pendulum_fitted):
    report = pendulum_fitted.evaluate()
    print("\n" + report.summary())
    assert report.passed, report.summary()


def test_the_fitted_twin_carries_its_record_and_data(pendulum_fitted):
    assert pendulum_fitted.plan_ is not None and pendulum_fitted.record_ is not None
    assert pendulum_fitted.data_ is not None and pendulum_fitted.data_.runs


# --- preflight, and the real backend ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["pendulum_fitted", "wrist_moved"])
def test_preflight_runs_on_a_nominal_twin(which, request):
    fitted = request.getfixturevalue(which)
    result = sim2real.preflight(fitted)
    print(f"\n{which}: {result.summary() if hasattr(result, 'summary') else result}")
    assert result.checks
    for check in result.checks:
        assert check.passed in (True, False, None), check


def test_on_real_refuses_by_name(pendulum):
    with pytest.raises(NotImplementedError, match="real"):
        pendulum.calibrate(on="real", transport=object())
