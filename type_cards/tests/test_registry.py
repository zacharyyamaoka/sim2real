"""The type cards' ruler, written before the registry (2026-11-04).

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs --with pytest pytest -q /home/bam/sim2real/type_cards/tests

What it holds the registry to (Zach's journal, PROJECT - Sim2Real, Nov 4 2026, and the dispatcher's design rules):
- every metric is black-box and cites a RobotDx stock-catalog id at the pinned commit, or says `proposed` and why;
- every card has both metric families: performance (output vs the commanded target) and fidelity (twin vs real, same input);
- every model parameter has a unit, a nominal value or a source, the experiment that identifies it, and whether the outputs see it;
- every card has a coverage spec with the axes its group needs, and a view that is a data-ui template at the vendored commit
  (each named panel in its views.base) or `proposed`;
- the servo card's coverage reproduces bam_rack_twin.schedule's own CAN 11 number on the same schedule (an oracle outside
  the registry: the producer's stored coverage and, when its venv exists, a live call), and a narrow plan scores low;
- composites name member cards that exist; the procedure is one shared sequence whose every step is a file.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from type_cards import coverage as cov  # noqa: E402
from type_cards import registry as reg  # noqa: E402

SCHEDULE = Path("/archive/datasets/bam_rig/schedules/one-dof-test-rack/can11/schedule.json")
RACK_TWIN = Path("/home/bam/bam_ws/src/dev/bam_rack_twin")
CARD_IDS = {"gearbox", "driver", "motor", "servo", "arm_subassembly", "arm_6dof", "arm_6dof_gripper", "camera_rgb", "camera_rgbd", "camera_hsi"}


def robotdx():
    """RobotDx's catalog at the commit the registry pins, read from git (never the working tree, never a fork)."""
    return reg.robotdx_catalog()


def test_the_ten_cards_of_zachs_list_exist():
    assert CARD_IDS <= set(reg.CARDS), sorted(CARD_IDS - set(reg.CARDS))
    # WHY "target" (PEP 0001 §8, Zach 2026-11-11): the ArUco marker card is neither driven nor sensing; a sensor reads it
    assert {c.group for c in reg.CARDS.values()} == {"actuator", "sensor", "target"}
    assert list(reg.CARDS) == list(reg.ORDER)


def test_robotdx_pin_is_a_real_commit():
    out = subprocess.run(["git", "-C", str(reg.ROBOTDX_REPO), "cat-file", "-t", reg.ROBOTDX_COMMIT], capture_output=True, text=True)
    assert out.stdout.strip() == "commit"


def test_every_metric_cites_robotdx_or_is_proposed_with_a_reason():
    entries = {e.id: e for e in robotdx().ENTRIES}
    bad = []
    for card in reg.CARDS.values():
        for m in card.metrics:
            if m.robotdx is not None:
                if m.robotdx not in entries or m.proposed:
                    bad.append((card.id, m.id, m.robotdx))
            elif len(m.proposed.strip()) < 15:
                bad.append((card.id, m.id, "proposed without a reason"))
    assert not bad, bad


def test_every_card_has_performance_and_fidelity_and_nothing_else():
    for card in reg.CARDS.values():
        families = {m.family for m in card.metrics}
        assert families == {"performance", "fidelity"}, (card.id, families)
        for m in card.metrics:
            assert m.defined_on and m.unit and m.normalised, (card.id, m.id)


def test_model_parameters_are_never_metrics():
    for card in reg.CARDS.values():
        params = {p.name for p in card.model.parameters}
        assert not params & {m.id.split(".", 1)[-1] for m in card.metrics}, card.id


def test_every_parameter_has_unit_source_experiment_and_observability():
    bad = []
    for card in reg.CARDS.values():
        assert card.model.parameters, card.id
        assert card.model.robotparts or len(card.model.proposed) >= 15, card.id
        for p in card.model.parameters:
            if not (p.unit and p.source and p.identified_by and p.observable in ("yes", "partial", "no")):
                bad.append((card.id, p.name))
    assert not bad, bad


def test_encoder_blind_terms_are_marked_unobservable():
    servo = {p.name: p for p in reg.CARDS["servo"].model.parameters}
    assert servo["backlash_rad"].observable == "no" and servo["gear_stiffness_nm_rad"].observable == "no"


def test_robotparts_terms_cited_exist():
    """A parameter whose source names a robotparts model term (robotparts:<model>.<term>) names a real one."""
    for card in reg.CARDS.values():
        for p in card.model.parameters:
            for model, term in re.findall(r"robotparts:([\w/]+)\.(\w+)", p.source):
                path = reg.ROBOTPARTS_REPO / (model if model.startswith("lab/") else f"models/actuator/{model}") / "model.json"
                assert path.is_file(), (card.id, p.name, path)
                assert term in json.loads(path.read_text())["terms"], (card.id, p.name, model, term)


REQUIRED_AXES = {
    "actuator": {"q", "qd", "qdd", "load torque", "temperature"},
    "arm": {"joint space", "tool pose"},
    "camera": {"distance", "incidence angle", "illumination", "material", "exposure"},
}


def test_coverage_axes_per_group():
    for card in reg.CARDS.values():
        names = {a.name for a in card.coverage.axes}
        assert card.coverage.rule and callable(card.coverage.measure), card.id
        if card.id in ("gearbox", "motor", "servo"):
            assert REQUIRED_AXES["actuator"] <= names, (card.id, names)
        if card.id.startswith("arm"):
            assert REQUIRED_AXES["arm"] <= names, (card.id, names)
        if card.group == "sensor" and card.id.startswith("camera"):
            assert REQUIRED_AXES["camera"] <= names, (card.id, names)
    assert {"wavelength band", "material class"} <= {a.name for a in reg.CARDS["camera_hsi"].coverage.axes}


def views_base(template: str) -> str:
    out = subprocess.run(["git", "-C", str(reg.DATA_UI_REPO), "show", f"{reg.data_ui_commit()}:gallery/examples/{template}/views.base"],
                         capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def test_views_are_vendored_data_ui_templates_or_proposed():
    assert re.fullmatch(r"[0-9a-f]{7,40}", reg.data_ui_commit())
    for card in reg.CARDS.values():
        v = card.view
        if v.template:
            text = views_base(v.template)
            assert text, (card.id, v.template)
            names = set(re.findall(r"^\s*name:\s*(.+?)\s*$", text, re.M))
            assert v.panels and set(v.panels) <= names, (card.id, set(v.panels) - names)
        else:
            assert len(v.proposed) >= 15, card.id


@pytest.fixture(scope="module")
def can11():
    return json.loads(SCHEDULE.read_text())


def test_servo_coverage_reproduces_schedule_py_on_can11(can11):
    """The oracle is the producer's own number (bam_rack_twin.schedule.coverage, stored in schedule.json when it was built)."""
    for split in ("train", "held_out"):
        got = cov.servo_coverage(can11, split=split)
        want = can11["coverage"][split]
        assert got.reachable == can11["coverage"]["reachable_cells"] == 1616
        assert got.samples == want["samples"]
        assert got.visited == want["visited_reachable"]
        assert got.pct == want["pct_reachable"], (split, got.pct, want["pct_reachable"])


@pytest.mark.skipif(not (RACK_TWIN / ".venv" / "bin" / "python").is_file(), reason="bam_rack_twin's venv is not built on bam_ws main")
def test_servo_coverage_matches_a_live_call_of_schedule_py(can11):
    code = ("import json,sys; from bam_rack_twin import schedule as s; d=json.load(open(sys.argv[1])); "
            "print(json.dumps(s.coverage(d)['train']['pct_reachable']))")
    out = subprocess.run([str(RACK_TWIN / ".venv" / "bin" / "python"), "-c", code, str(SCHEDULE)], capture_output=True, text=True, cwd=RACK_TWIN, check=True)
    assert cov.servo_coverage(can11).pct == json.loads(out.stdout)


def test_a_narrow_servo_plan_scores_low(can11):
    narrow = dict(can11, runs=[r for r in can11["runs"] if r["family"] == "floor"][:1])
    full = cov.servo_coverage(can11)
    low = cov.servo_coverage(narrow, split="all")
    assert 0 < low.pct < 5 < full.pct and low.pct < full.pct / 10, (low.pct, full.pct)


def test_servo_extra_axes_are_reported_not_hidden(can11):
    got = cov.servo_coverage(can11)
    assert got.axes["load torque"] is not None and 0 < got.axes["load torque"] <= 100
    assert got.axes["temperature"] is None and "temperature" in got.unplanned


def test_camera_coverage_narrow_vs_broad():
    card = reg.CARDS["camera_rgbd"]
    one = [{"distance": 0.5, "incidence angle": 0, "illumination": 300, "material": "matte white", "exposure": 10}]
    broad = [{"distance": d, "incidence angle": a, "illumination": l, "material": m, "exposure": x}
             for d in (0.2, 0.5, 1.0, 2.0) for a in (0, 20, 40, 60) for l in (50, 300, 1000) for m in ("matte white", "black plastic", "metal", "clear PET")
             for x in (1, 10, 30)]
    lo, hi = card.coverage.measure(one), card.coverage.measure(broad)
    assert lo.pct < 1 and hi.pct > 40 and lo.visited == 1


def test_arm_coverage_narrow_vs_broad():
    card = reg.CARDS["arm_6dof"]
    home = [{"joint space": (0, -1.57, 0, -1.57, 0, 0)}]
    lo = card.coverage.measure(home)
    assert lo.pct < 1 and lo.visited == 1 and lo.axes["tool pose"] is None


def test_composites_name_cards_that_exist():
    for card in reg.CARDS.values():
        for member in card.members:
            assert member.card in reg.CARDS or member.card in robotdx().PARTS, (card.id, member.card)
    arm = reg.CARDS["arm_6dof"]
    assert sum(m.count for m in arm.members if m.card == "servo") == 6 and "5 mm" in arm.error_budget
    assert {m.card for m in reg.CARDS["servo"].members} >= {"motor", "driver", "gearbox", "encoder"}
    assert "arm_6dof" in {m.card for m in reg.CARDS["arm_6dof_gripper"].members}


def test_one_shared_procedure_every_step_a_file():
    keys = [s.key for s in reg.STEPS]
    assert keys == ["describe", "nominal", "schedule", "capture", "identify", "held_out", "gates"]
    assert all(re.search(r"\.\w+$", s.artifact) for s in reg.STEPS)
    for card in reg.CARDS.values():
        assert list(card.procedure) == keys, card.id
        assert all(t.status in ("exists", "proposed") and t.text for t in card.procedure.values()), card.id


def test_observability_is_honest():
    for card in reg.CARDS.values():
        assert card.observability.today in ("yes", "partial", "no") and card.observability.instruments, card.id
    assert reg.CARDS["gearbox"].observability.today != "yes" and reg.CARDS["motor"].observability.today != "yes"
    assert any("dyno" in n.lower() for n in reg.CARDS["motor"].observability.needs + reg.CARDS["gearbox"].observability.needs)
    assert reg.CARDS["servo"].observability.today == "yes"


def test_robotdx_part_or_a_named_gap():
    parts = robotdx().PARTS
    for card in reg.CARDS.values():
        assert (card.robotdx_part in parts) if card.robotdx_part else len(card.robotdx_gap) >= 15, card.id
    assert reg.CARDS["motor"].robotdx_part is None and reg.CARDS["arm_subassembly"].robotdx_part is None
