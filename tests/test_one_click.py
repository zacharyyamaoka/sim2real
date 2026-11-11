"""The one-click API over types: a twin loaded from a description, then .simulate(), .calibrate() and .eval_twin() (Zach, 2026-11-11).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_one_click.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_one_click.py

Zach: "So you start with a robotDescription. Honestly it should just be like .calibrate() and .eval_twin()... so you set the model, you
calibrate it and then you eval it", plus .simulate(). Decided the same day (docs/decision-types-seam-2026-11-11.md): sim2real owns the
types; a description is a composition of typed instances with parameter values, wherever the values came from. The API prior-art note's
verdict the same day (vault: "Sim2Real API Prior Art (2026-11-11)"): the verbs live on a sim2real Twin, never on the description (that
would be the cycle); calibrate(on="sim"|"real") returns a NEW fitted twin, scikit-learn style (learned values end in `_`); eval_twin()
scores held-out runs only and refuses a training run; guards live in the runner.

The tracer is the one-DOF pendulum oracle (sysid's pendulum_can11): CAN 11's own test schedule played on its twin at a HIDDEN truth set
apart from the description's values, with sensor noise. Zach's rule for robotics algorithms: prove in sim that the fit recovers a hidden
ground truth, committed as the acceptance test, before any hardware. Written before sim2real.load existed (red first); moved onto Twin when the prior-art verdict landed, before any run.

The oracles are read here, never from the code under test: the hidden truth from sysid/examples/pendulum_can11/world.json, the
tolerances and the held-out factor from sysid/acceptance.json (pinned by digest in sysid/tests/test_oracle.py), the units from the
description's own manifest, and the types from sim2real.cards.domain. A recovery that hands the description back unchanged fails (every
nominal value fails its tolerance), and a truth moved past a tolerance must turn calibrate and eval_twin red: the ruler can fail.

The slow half (SIM2REAL_SLOW=1) runs the four calls end to end, twice: on the committed truth (green) and on a truth whose gravity is
moved 10 % (five times its 2 % tolerance; red). Each takes the CAN 11 oracle's minutes (the rack twin replays at 30 kHz).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("bam_rack_twin", reason="the pendulum oracle runs under bam_rack_twin's venv (sysid's runtime)")
pytest.importorskip("mujoco", reason="simulate() needs the sim extra")

from robot_msgs.space import Value  # noqa: E402
from robot_msgs.trajectory import JointTrajectory  # noqa: E402

import sim2real  # noqa: E402
from sim2real.cards import domain as dm  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = "pendulum_can11"
EXAMPLE_DIR = REPO / "sysid" / "examples" / EXAMPLE
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
CAPTURE = os.environ.get("SIM2REAL_CAPTURE")  # a folder: the slow runs write their summaries there (the report reads them)
MOVED = {"can11.gravity_nm": 5.05 * 1.10}  # the red run: gravity 10 % off the committed truth, five times its 2 % tolerance


def manifest() -> dict:
    return json.loads((EXAMPLE_DIR / "description.json").read_text())


def hidden_truth() -> dict:
    return json.loads((EXAMPLE_DIR / "world.json").read_text())["truth"]


def tolerances() -> dict:
    return json.loads((REPO / "sysid" / "acceptance.json").read_text())["examples"][EXAMPLE]


def within(value, truth, rule) -> bool:
    kind, tol = rule
    return value is not None and math.isfinite(value) and abs(value - truth) <= (tol if kind == "abs" else tol * abs(truth))


@pytest.fixture(scope="module")
def robot():
    return sim2real.Twin.load(EXAMPLE)


# --- the description: typed instances with parameter values -------------------------------------------------------------------------


def test_load_gives_a_composition_of_typed_instances(robot):
    d = robot.description
    words = {c["id"]: c["type"] for c in manifest()["components"]}
    assert [i.id for i in d.instances] == list(words)
    want = {"rack": None, "can11": "integrated_servo", "can11_motor": "bldc_motor", "can11_gearbox": "gearbox",
            "can11_driver": "foc_controller", "can11_encoder": "encoder", "link_camera": "depth_camera"}
    assert {i.id: i.type for i in d.instances} == want
    assert all(i.type is None or i.type in dm.TYPE_ORDER for i in d.instances)
    assert d.instance("rack").structural == "deployment"
    assert d.instance("can11").parent == "rack" and d.instance("can11_gearbox").parent == "can11"


def test_the_servo_carries_every_parameter_as_a_robot_msgs_value(robot):
    units = {k: v["unit"] for k, v in manifest()["parameters"].items()}
    servo = robot.description.instance("can11")
    keys = {f"can11.{name}" for name in servo.parameters}
    assert keys == set(units)
    for name, value in servo.parameters.items():
        if name == "friction_stribeck_speed_rad_s":
            assert value is None, "the description states no Stribeck speed: a missing prior stays missing, never a made-up number"
            continue
        assert isinstance(value, Value) and isinstance(value, float), name
        assert value.unit == units[f"can11.{name}"], name
        assert value.source, f"{name} says where it came from"
    truth = hidden_truth()
    rules = tolerances()["parameters"]
    # the priors are the description's, set apart from the hidden truth: each fails its own tolerance (the oracle's premise)
    assert all(not within(servo.parameters[k.split(".", 1)[1]] or 0.0, truth[k], rules[k]) for k in rules)


def test_the_types_name_the_parameters_they_hold(robot):
    servo = robot.description.instance("can11")
    on_type = {p.name for p in dm.TYPES["integrated_servo"].parameters}
    assert set(servo.on_type) == set(servo.parameters)
    assert {n for n, held in servo.on_type.items() if held} == set(servo.parameters) & on_type
    # the two the type contract has no name for are said, not dropped (reported as a contract gap)
    assert {n for n, held in servo.on_type.items() if not held} == {"gravity_bottom_rad", "friction_stribeck_speed_rad_s"}


# --- the verbs' edges ----------------------------------------------------------------------------------------------------------------


def test_the_real_backend_names_the_rack_path(robot):
    with pytest.raises(NotImplementedError, match="rack"):
        robot.calibrate(on="real")


def test_an_unknown_backend_or_an_unsealed_truth_is_refused(robot):
    with pytest.raises(ValueError, match="on must be"):
        robot.calibrate(on="hil")
    with pytest.raises(ValueError, match="sealed"):
        robot.calibrate(on="sim", truth="open")


def test_eval_twin_needs_a_fitted_twin(robot):
    assert not robot.fitted and not hasattr(robot, "values_")
    with pytest.raises(RuntimeError, match="calibrate"):
        robot.eval_twin()
    assert sim2real.load is not None and type(sim2real.load(EXAMPLE)) is sim2real.Twin


def test_eval_twin_refuses_a_training_run(robot):
    from types import SimpleNamespace  # noqa: PLC0415

    plan = SimpleNamespace(held_out=[{"run": "r1", "split": "held_out"}, {"run": "r2", "split": "train"}])
    runner = sim2real.twin.SimRunner(robot.description, state={"plan": plan, "measured": SimpleNamespace(train={"r1": None})})
    with pytest.raises(ValueError, match="held-out runs only") as caught:
        runner.eval_twin()
    assert "r1" in str(caught.value) and "r2" in str(caught.value)


def test_importing_sim2real_loads_no_layer():
    code = ("import sys, sim2real; loaded = sorted(m for m in sys.modules if m.startswith('sim2real.')); "
            "assert sim2real.Twin.load and 'sim2real.twin' in sys.modules; print(loaded)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ}, check=True).stdout
    assert out.strip() == "[]"


# --- simulate: MuJoCo, headless ------------------------------------------------------------------------------------------------------


def test_simulate_drops_the_description_toward_its_bottom_and_friction_holds_it(robot):
    params = robot.description.instance("can11").parameters
    bottom, gravity, friction = (float(params[k]) for k in ("gravity_bottom_rad", "gravity_nm", "frictionloss_nm"))
    sim = robot.simulate(seconds=2.0, offset_rad=0.3)
    traj = sim.trajectory
    assert isinstance(traj, JointTrajectory) and traj.joint_names == ("can11_hinge",)
    t, q, qd = traj.t, traj.positions[:, 0], traj.velocities[:, 0]
    assert t[0] == 0.0 and abs(t[-1] - 2.0) < 0.01 and (t[1:] > t[:-1]).all()
    assert abs(q[0] - (bottom + 0.3)) < 1e-9
    # WHY not "swings through the bottom" (this test's first form, wrong about the physics, corrected on its first run 2026-11-11): the
    # description's MJCF carries the twin of record's LuGre friction, so the link falls toward its bottom and sticks where gravity's torque
    # no longer beats the static friction: inside |q - bottom| <= asin(Fs / G), with the description's own Fs and G (0.18 rad here)
    band = math.asin(friction / gravity)
    assert abs(q[-1] - bottom) < 0.3 - 0.1 and abs(q[-1] - bottom) <= band, (q[-1] - bottom, band)
    assert abs(qd[-1]) < 1e-3, "it has stopped"
    assert "can11_hinge" in sim.summary()


# --- the tracer: load -> simulate -> calibrate -> eval_twin, green on the hidden truth, red on a moved one --------------------------------


def _capture(name: str, cal, report) -> None:
    if not CAPTURE:
        return
    folder = Path(CAPTURE)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"calibration": cal.to_dict(), "report": report.to_dict()}, indent=1, default=str))


@pytest.mark.skipif(not SLOW, reason="the CAN 11 oracle takes minutes: SIM2REAL_SLOW=1")
def test_one_click_recovers_the_hidden_truth_and_the_twin_passes_its_gates():
    twin = sim2real.Twin.load(EXAMPLE)
    print(twin.description.summary(), flush=True)
    print(twin.simulate().summary(), flush=True)
    fitted = twin.calibrate(on="sim", truth="sealed")
    cal = fitted.calibration_
    print(cal.summary(), flush=True)
    report = fitted.eval_twin()
    print(report.summary(), flush=True)
    _capture("green", cal, report)
    truth, rules = hidden_truth(), tolerances()
    assert fitted is not twin and not twin.fitted and fitted.values_ is cal.values  # a NEW twin; the loaded one stays unfitted
    recovered = {f"can11.{k}": float(v) for k, v in fitted.values_.items() if v is not None}
    missed = {k: (recovered.get(k), truth[k]) for k in rules["parameters"] if not within(recovered.get(k), truth[k], rules["parameters"][k])}
    assert not missed, f"outside tolerance of the hidden truth: {missed}"
    assert cal.passed and report.passed, report.summary()
    gates = {g.id: g for g in report.gates}
    assert {"twinned", "held_out_link_fidelity", "recovery"} <= set(gates)
    fidelity = report.metrics["held_out_link_fidelity"]
    assert fidelity["before"] / fidelity["after"] >= rules["metrics"]["held_out_link_fidelity"]
    assert report.selected == rules["selected_rung"]
    assert all(isinstance(v, Value) for v in cal.values.values() if v is not None)


@pytest.mark.skipif(not SLOW, reason="the CAN 11 oracle takes minutes: SIM2REAL_SLOW=1")
def test_a_truth_moved_past_its_tolerance_turns_calibrate_and_eval_twin_red():
    fitted = sim2real.Twin.load(EXAMPLE).calibrate(on="sim", truth="sealed", move_truth=MOVED)
    cal = fitted.calibration_
    print(cal.summary(), flush=True)
    report = fitted.eval_twin()
    print(report.summary(), flush=True)
    _capture("red", cal, report)
    assert not cal.passed and "can11.gravity_nm" in cal.failing
    # WHY "among" (this assertion's first form said recovery alone, a guess the first run disproved, 2026-11-11): the twin fitted on the
    # moved world also missed the twinned gate (M4 at 2.14x the floor); the ruler's own gate must be one of the red ones
    assert not report.passed and "recovery" in [g.id for g in report.gates if not g.passed]
