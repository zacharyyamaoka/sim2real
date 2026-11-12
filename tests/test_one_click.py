"""The one-click API over types: a RobotTwin of typed instances, then .simulate(), .calibrate() and .eval() (Zach, 2026-11-11).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_one_click.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_one_click.py

Zach: "So you start with a robotDescription. Honestly it should just be like .calibrate() and .eval_twin()... so you set the model, you
calibrate it and then you eval it", plus .simulate(). Decided the same day (docs/decision-types-seam-2026-11-11.md): sim2real owns the
types; a description is a composition of typed instances with parameter values, wherever the values came from. The API prior-art note's
verdict the same day (vault: "Sim2Real API Prior Art (2026-11-11)"): the verbs live on a sim2real RobotTwin, never on the description (that
would be the cycle); calibrate(on="sim"|"real") returns a NEW fitted twin, scikit-learn style (learned values end in `_`); eval()
scores held-out runs only and refuses a training run; guards live in the runner. Renamed from eval_twin() the same evening (Zach: "I think
twin.eval() no need to do eval_twin() that's redundant"). Addendum 2 the same evening (sim2real below robot_description): sim2real knows
only the twin, built directly, the oracle a fixture (sim2real.examples.pendulum_can11()); fitted.parameters carries the calibrated values
(a new twin; the loaded one is untouched; calibrate() writes nothing) for robot_description's from_robot_twin (not built yet). Twin was
renamed RobotTwin the same evening, no alias.

The tracer is the one-DOF pendulum oracle (sysid's pendulum_can11): CAN 11's own test schedule played on its twin at a HIDDEN truth set
apart from the description's values, with sensor noise. Zach's rule for robotics algorithms: prove in sim that the fit recovers a hidden
ground truth, committed as the acceptance test, before any hardware. Written before sim2real.load existed (red first); moved onto RobotTwin when the prior-art verdict landed, before any run; onto sim2real.examples with addendum 2.

The oracles are read here, never from the code under test: the hidden truth from sysid/examples/pendulum_can11/world.json, the
tolerances and the held-out factor from sysid/acceptance.json (pinned by digest in sysid/tests/test_oracle.py), the units from the
description's own manifest, and the types from sim2real.cards.domain. A recovery that hands the description back unchanged fails (every
nominal value fails its tolerance), and a truth moved past a tolerance must turn calibrate and eval red: the ruler can fail.

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

from robot_msgs.space import Basis, Value  # noqa: E402
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
    return sim2real.examples.pendulum_can11()


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


def test_eval_needs_a_fitted_twin(robot):
    assert not robot.fitted and not hasattr(robot, "values_")
    with pytest.raises(RuntimeError, match="calibrate"):
        robot.eval()
    assert type(sim2real.examples.pendulum_can11()) is sim2real.RobotTwin
    assert not hasattr(sim2real, "load") and not hasattr(sim2real.RobotTwin, "load"), "no loading by a name string (addendum 2)"
    assert not hasattr(sim2real, "Twin"), "renamed RobotTwin, no alias"


def test_eval_refuses_a_training_run(robot):
    from types import SimpleNamespace  # noqa: PLC0415

    plan = SimpleNamespace(held_out=[{"run": "r1", "split": "held_out"}, {"run": "r2", "split": "train"}])
    runner = sim2real.twin.SimRunner(robot.description, state={"plan": plan, "measured": SimpleNamespace(train={"r1": None})})
    with pytest.raises(ValueError, match="held-out runs only") as caught:
        runner.eval()
    assert "r1" in str(caught.value) and "r2" in str(caught.value)


# --- fitted.parameters: the calibrated values on a new twin ------------------------------------------------------------------------


def _stub_calibration():
    """A calibration result the fast tests stand in for the slow fit with: two of the green run's recovered values (reports/media/
    one-click-tracer-2026-11-11/green.json), gravity with its 95 % interval and the Stribeck speed the description states no prior for."""
    measured = {"basis": Basis.MEASURED, "measured_by": "sim2real.RobotTwin.calibrate(on='sim', truth='sealed'), M4.dynamics.twin"}
    values = {"gravity_nm": Value(5.066218703821104, "N·m", source="the gap: ...", **measured),
              "friction_stribeck_speed_rad_s": Value(0.10413582256883064, "rad/s", source="Nelder-Mead ...", **measured)}
    rows = [{"key": "can11.gravity_nm", "name": "gravity_nm", "ci95": [5.063042470338151, 5.076815092995939], "pass": True},
            {"key": "can11.friction_stribeck_speed_rad_s", "name": "friction_stribeck_speed_rad_s", "ci95": None, "pass": True}]
    return sim2real.twin.Calibration("sim", "M4.dynamics.twin", "M4", values, {"M4": {k: float(v) for k, v in values.items()}}, rows, {}, 0.0,
                                     {"train_runs": 0})


def test_the_fitted_twin_carries_the_calibrated_values_and_keeps_the_rest(robot, monkeypatch, tmp_path):
    from datetime import date  # noqa: PLC0415

    before = {i: {n: (v, getattr(v, "source", None)) for n, v in named.items()} for i, named in robot.parameters.items()}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(robot.runner, "calibrate", lambda **_: (_stub_calibration(), {}))
    fitted = robot.calibrate(on="sim")
    assert fitted is not robot and isinstance(fitted, sim2real.RobotTwin)
    servo, prior = fitted.parameters["can11"], robot.parameters["can11"]
    gravity = servo["gravity_nm"]
    assert float(gravity) == 5.066218703821104 and gravity.unit == "N·m"
    assert (gravity.low, gravity.high) == (5.063042470338151, 5.076815092995939)
    assert gravity.basis == Basis.MEASURED, "identified, not taken from a datasheet"
    assert gravity.source == f"sim2real calibrate · on=sim · M4 · {date.today().isoformat()}"
    assert gravity.measured_by and "the gap" in gravity.notes
    stribeck = servo["friction_stribeck_speed_rad_s"]
    assert prior["friction_stribeck_speed_rad_s"] is None and float(stribeck) == 0.10413582256883064 and stribeck.low is None
    # untouched parameters keep their prior and its source; untouched instances are carried over as they are
    assert servo["frictionloss_nm"] is prior["frictionloss_nm"] and servo["frictionloss_nm"].basis == Basis.ASSUMED
    assert set(fitted.parameters) == set(robot.parameters) == {"can11"}
    assert [i.id for i in fitted.instances] == [i.id for i in robot.instances]
    # the loaded twin is unchanged, the fitted runner keeps its priors (the sim pipeline reads them from the manifest), nothing written
    assert {i: {n: (v, getattr(v, "source", None)) for n, v in named.items()} for i, named in robot.parameters.items()} == before
    assert fitted.runner.description is robot.description
    assert list(tmp_path.iterdir()) == [], "calibrate() writes nothing"


def test_with_values_is_a_functional_update(robot):
    assert robot.with_values({}).parameters == robot.parameters
    moved = robot.with_values({"can11": {"gravity_nm": Value(5.0, "N·m", basis=Basis.CHOSEN, source="a test")}})
    assert isinstance(moved, sim2real.RobotTwin) and moved is not robot and not moved.fitted
    assert float(moved.parameters["can11"]["gravity_nm"]) == 5.0 and float(robot.parameters["can11"]["gravity_nm"]) != 5.0
    assert moved.parameters["can11"]["frictionloss_nm"] is robot.parameters["can11"]["frictionloss_nm"]
    with pytest.raises(KeyError, match="can11.no_such_parameter"):
        robot.with_values({"can11": {"no_such_parameter": 1.0}})
    with pytest.raises(KeyError, match="nobody"):
        robot.with_values({"nobody": {"gravity_nm": 1.0}})


def test_a_twin_is_built_directly_from_its_instances(robot):
    d = robot.description
    twin = sim2real.RobotTwin(robot.instances, name=EXAMPLE, model_file=d.model, models={"can11": "M3.dynamics.stribeck"})
    assert twin.parameters == robot.parameters and twin.model == "M3.dynamics.stribeck"
    assert robot.model == dm.current_models("integrated_servo")[0].id


def test_importing_sim2real_loads_no_layer():
    code = ("import sys, sim2real; loaded = sorted(m for m in sys.modules if m.startswith('sim2real.')); "
            "assert sim2real.RobotTwin and sim2real.examples.pendulum_can11 and 'sim2real.twin' in sys.modules; print(loaded)")
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


# --- the tracer: load -> simulate -> calibrate -> eval, green on the hidden truth, red on a moved one -------------------------------------


def _capture(name: str, cal, report) -> None:
    if not CAPTURE:
        return
    folder = Path(CAPTURE)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"calibration": cal.to_dict(), "report": report.to_dict()}, indent=1, default=str))


@pytest.mark.skipif(not SLOW, reason="the CAN 11 oracle takes minutes: SIM2REAL_SLOW=1")
def test_one_click_recovers_the_hidden_truth_and_the_twin_passes_its_gates():
    twin = sim2real.examples.pendulum_can11()
    print(twin.description.summary(), flush=True)
    print(twin.simulate().summary(), flush=True)
    fitted = twin.calibrate(on="sim", truth="sealed")
    cal = fitted.calibration_
    print(cal.summary(), flush=True)
    report = fitted.eval()
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
    # the calibrated values on the fitted twin: every recovered value replaces its prior, with its unit, interval and provenance
    calibrated = fitted.parameters["can11"]
    assert {k: float(v) for k, v in calibrated.items() if v is not None} == {k: float(v) for k, v in fitted.values_.items() if v is not None}
    for name, value in calibrated.items():
        assert value.basis == Basis.MEASURED and value.source.startswith(f"sim2real calibrate · on=sim · {cal.rung} · "), name
        assert value.unit == manifest()["parameters"][f"can11.{name}"]["unit"], name
    assert twin.parameters["can11"]["gravity_nm"].basis == Basis.ASSUMED  # the loaded twin is untouched


@pytest.mark.skipif(not SLOW, reason="the CAN 11 oracle takes minutes: SIM2REAL_SLOW=1")
def test_a_truth_moved_past_its_tolerance_turns_calibrate_and_eval_red():
    fitted = sim2real.examples.pendulum_can11().calibrate(on="sim", truth="sealed", move_truth=MOVED)
    cal = fitted.calibration_
    print(cal.summary(), flush=True)
    report = fitted.eval()
    print(report.summary(), flush=True)
    _capture("red", cal, report)
    assert not cal.passed and "can11.gravity_nm" in cal.failing
    # WHY "among" (this assertion's first form said recovery alone, a guess the first run disproved, 2026-11-11): the twin fitted on the
    # moved world also missed the twinned gate (M4 at 2.14x the floor); the ruler's own gate must be one of the red ones
    assert not report.passed and "recovery" in [g.id for g in report.gates if not g.passed]
