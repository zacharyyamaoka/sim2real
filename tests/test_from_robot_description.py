"""RobotTwin.from_robot_description(rd): the twin built from a robot's description, not by hand (Zach, 2026-11-17).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_from_robot_description.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_from_robot_description.py

Zach, Daily Note 2026-11-17 "1 click Sim to Real":

    twin = RobotTwin.from_robot_description(rd)
    twin.calibrate()
    twin.evaluate()

The ruler, written before the code (red first): the CAN 11 pendulum's description, `bam_rack_twin.description.station_description(11)`,
joins the station's three layers (its design: the twin of record's model; its unit: the rack's deployment record; its parts: robotparts
user/ part ids), and the twin built from it is the hand-built fixture `sim2real.examples.pendulum_can11()` value for value: the same
instances, types, parents, binds and parameter values with their units, the same model file and runner world. The hand-built fixture is
the oracle here, read through its own path (the sysid manifest), never through the code under test.

The description's shape this file holds the code to (a frozen dataclass; sim2real reads it by attribute and imports none of it):
    rd.name, rd.title, rd.model (the MJCF path), rd.source, rd.record ({"path": deployment.json, "component": "can11"}),
    rd.components: each .id, .title, .type (a sim2real type id, or "deployment" for the structural root), .parent,
    .parameters ({name: robot_msgs Value}), .binds, .part (a robotparts id, or None).
"""

from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

import pytest
from robot_msgs.space import Value

import sim2real
from sim2real import RobotTwin
from sim2real.cards import domain as dm

ROBOTPARTS_USER = Path(os.environ.get("SIM2REAL_ROBOTPARTS", "/home/bam/robotparts")) / "user"
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"


@pytest.fixture(scope="module")
def rd():
    from bam_rack_twin.description import station_description  # noqa: PLC0415

    return station_description(11)


@pytest.fixture(scope="module")
def twin(rd):
    return RobotTwin.from_robot_description(rd, workers=2)


@pytest.fixture(scope="module")
def hand():
    return sim2real.examples.pendulum_can11(workers=2)


def _shape(t: RobotTwin):
    return [(i.id, i.type, i.parent, i.structural, dict(i.binds), dict(i.on_type)) for i in t.instances]


def _values(t: RobotTwin):
    return {f"{i.id}.{name}": (None if v is None else (float(v), v.unit)) for i in t.instances for name, v in i.parameters.items()}


# --- the twin equals the hand-built one -------------------------------------------------------------------------------------------


def test_the_twin_from_the_description_is_the_hand_built_twin(twin, hand):
    assert twin.description.id == hand.description.id == "pendulum_can11"
    assert Path(twin.description.model).resolve() == Path(hand.description.model).resolve()
    assert _shape(twin) == _shape(hand)
    assert _values(twin) == _values(hand)
    assert twin.model == hand.model
    assert not twin.fitted


def test_its_priors_reach_the_sim_pipeline(twin):
    # WHY: SimRunner refuses a twin whose priors differ from what the pipeline reads; the description's must pass that guard untouched
    twin.runner.sysid_description()


def test_every_prior_is_a_value_with_a_source(twin):
    for i in twin.instances:
        for name, v in i.parameters.items():
            if v is not None:
                assert isinstance(v, Value), f"{i.id}.{name} is a {type(v).__name__}, not a robot_msgs Value"
                assert v.source, f"{i.id}.{name} names no source"


# --- the three layers are joined in the description -------------------------------------------------------------------------------


def test_the_unit_is_the_rack_records(rd):
    record = Path(rd.record["path"])
    assert record.name == "deployment.json" and record.exists()
    assert rd.record["component"] == "can11"
    servo = next(c for c in rd.components if c.type == "integrated_servo")
    assert servo.binds.get("station") == 11


def test_the_parts_are_robotparts_user_parts_on_the_rack_build(rd):
    build = (ROBOTPARTS_USER / "builds" / "one-dof-rack.py").read_text(encoding="utf-8")
    listed = set(re.findall(r'Line\("([^"]+)"', build))
    folders = {p.name for p in (ROBOTPARTS_USER / "parts").rglob("*") if p.is_dir()}
    by_type = {c.type: c.part for c in rd.components}
    for type_id in ("bldc_motor", "gearbox", "foc_controller", "depth_camera"):
        part = by_type.get(type_id)
        assert part, f"the {type_id} names no robotparts part"
        assert part in folders, f"{part} is no folder under {ROBOTPARTS_USER / 'parts'}"
        assert part in listed, f"{part} is not a line of user/builds/one-dof-rack.py"


def test_the_twin_carries_the_part_ids(twin, rd):
    parts = {c.id: c.part for c in rd.components}
    assert {i.id: i.part for i in twin.instances} == parts


# --- evaluate() is the verb; eval() stays its alias ---------------------------------------------------------------------------------


def test_evaluate_is_the_verb_and_eval_its_alias(hand):
    assert callable(getattr(RobotTwin, "evaluate", None))
    for verb in ("evaluate", "eval"):
        with pytest.raises(RuntimeError, match="fitted twin"):
            getattr(hand, verb)()


# --- what it refuses, each with the way through -------------------------------------------------------------------------------------


def test_a_design_only_robot_description_is_refused_by_name():
    from bam_robot_descriptions.urdf import RobotDescription  # noqa: PLC0415

    with pytest.raises(TypeError, match="unit"):
        RobotTwin.from_robot_description(RobotDescription(name="design_only"))


def test_an_unknown_type_is_refused(rd):
    bad = [dataclasses.replace(c, type="flux_capacitor") if c.type == "gearbox" else c for c in rd.components]
    with pytest.raises(ValueError, match="flux_capacitor"):
        RobotTwin.from_robot_description(dataclasses.replace(rd, components=tuple(bad)))


def test_a_bare_number_prior_is_refused(rd):
    servo = next(c for c in rd.components if c.type == "integrated_servo")
    name = next(iter(servo.parameters))
    bare = dataclasses.replace(servo, parameters={**servo.parameters, name: 1.0})
    with pytest.raises(TypeError, match=name):
        RobotTwin.from_robot_description(dataclasses.replace(rd, components=tuple(bare if c is servo else c for c in rd.components)))


def test_a_unit_with_no_calibration_world_is_refused(rd):
    with pytest.raises(LookupError, match="can99"):
        RobotTwin.from_robot_description(dataclasses.replace(rd, record={**rd.record, "component": "can99"}))


def test_the_types_are_sim2real_types(rd):
    for c in rd.components:
        assert c.type == "deployment" or c.type in dm.TYPES, c


# --- the three lines, end to end ------------------------------------------------------------------------------------------------


@pytest.mark.skipif(not SLOW, reason="SIM2REAL_SLOW=1: the CAN 11 oracle's calibration takes minutes")
def test_the_three_lines_end_to_end(rd):
    twin = RobotTwin.from_robot_description(rd, workers=2)
    fitted = twin.calibrate()
    report = fitted.evaluate()
    print(report.summary())
    assert fitted.fitted and report.passed, report.summary()
