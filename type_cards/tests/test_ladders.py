"""The type cards' v2 content, written before it (2026-11-05): Zach's Nov 5 workflow per type.

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs --with pytest pytest -q /home/bam/sim2real/type_cards/tests

What it holds the registry's content to (tests/test_contract.py holds the API):
- the cards: Zach's 7 actuators + 4 sensors, plus a conveyor belt (the landing-page examples need it);
- model rungs per type: a nested physics ladder with growing parameter counts, each rung named, counted and referenced; the one
  current rung IS today's model; actuator keys follow robotparts' published ladder (a robotparts model a rung cites has that
  rung number, read from robotparts' own model.json); learned rungs on top (a grey-box residual on a physics rung and a black-box
  net; the servo's is Hwangbo 2019's actuator net) that need more coverage and never extrapolate;
- wear: every actuator type has a wear rung whose laws are referenced; the servo's backlash wears Archard-style;
- metrics → diagnostics → gates: one drift diagnostic per type in Zach's words (with a forecast where the type wears); the servo's
  gates are bam_rack_twin's own acceptance limits, read from acceptance.py (an oracle outside this registry);
- test types per setting (bench, deployed) with a recalibration method in each, and every model parameter identified by a test;
- coverage: a bin size or a stated reason per axis, a coverage gate per type, the servo's equal to bam_rack_twin.schedule's
  MINIMUM_COVERAGE_PCT (read from schedule.py);
- calibration packages: Zach's six groups, each code path real at its ref;
- references: every DOI resolved at Crossref with a matching title and every URL fetched (references_checked.json).
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
RACK_TWIN = Path("/home/bam/bam_ws/src/dev/bam_rack_twin/bam_rack_twin")
CHECKED = REPO / "type_cards" / "references_checked.json"
ROBOTPARTS_NUMBERED = ("servo", "motor", "gearbox", "conveyor")
ACTUATORS = ("gearbox", "driver", "motor", "servo", "arm_subassembly", "arm_6dof", "arm_6dof_gripper", "conveyor")
SENSORS = ("camera_rgb", "camera_rgbd", "camera_hsi", "encoder")
KEY = re.compile(r"M\d+(\.wear)?")


def physics(card):
    return [r for r in card.rungs if r.kind == "physics"]


def every_reference():
    for card in reg.CARDS.values():
        for r in card.rungs:
            for ref in r.references:
                yield f"{card.id}.{r.key}", ref
    for pkg in reg.CALIBRATION_PACKAGES:
        for ref in pkg.references:
            yield pkg.id, ref
    for law, refs in reg.WEAR_LAW_REFERENCES.items():
        for ref in refs:
            yield f"wear:{law}", ref


# --- the cards -----------------------------------------------------------------------------------------------------------------

def test_zachs_types_plus_the_conveyor():
    assert set(ACTUATORS + SENSORS) == set(reg.CARDS) and list(reg.CARDS) == list(reg.ORDER)
    assert {c.id for c in reg.CARDS.values() if c.group == "actuator"} == set(ACTUATORS)
    assert reg.card_for("conveyor belt").id == "conveyor"
    assert reg.CARDS["conveyor"].model.parameters and reg.CARDS["conveyor"].robotdx_part is None


# --- rungs -----------------------------------------------------------------------------------------------------------------------

def test_every_type_has_a_nested_physics_ladder_that_grows():
    for card in reg.CARDS.values():
        ladder = physics(card)
        assert len(ladder) >= 3, (card.id, [r.key for r in ladder])
        for below, above in zip(ladder, ladder[1:]):
            assert set(below.parameter_names) < set(above.parameter_names), (card.id, below.key, above.key)
            assert above.n_parameters > below.n_parameters, (card.id, above.key)
        for r in card.rungs:
            assert KEY.fullmatch(r.key) and r.name and r.references and r.kind in reg.KINDS, (card.id, r.key)
            assert r.kind != "physics" or r.parameters, (card.id, r.key)
        keys = [r.key for r in card.rungs]
        assert len(keys) == len(set(keys)), card.id
        kinds = [r.kind for r in card.rungs]
        assert kinds == sorted(kinds, key=reg.KINDS.index), (card.id, kinds)  # physics, then residual, then learned


def test_the_one_current_rung_is_todays_model():
    for card in reg.CARDS.values():
        current = [r for r in card.rungs if r.current]
        assert len(current) == 1, (card.id, [r.key for r in current])
        assert current[0].kind == "physics" and current[0].parameters == card.model.parameters, card.id
        assert reg.current_rung(card.id) is current[0]


def test_actuator_keys_are_robotparts_rungs():
    """A physics rung that cites a robotparts actuator model carries that model's rung number (robotparts' own model.json)."""
    for card in reg.CARDS.values():
        for r in physics(card):
            if not r.robotparts:
                continue
            path = reg.ROBOTPARTS_REPO / r.robotparts / "model.json"
            assert path.is_file(), (card.id, r.key, path)
            rung = json.loads(path.read_text())["rung"]
            number = int(r.key[1:].split(".")[0])
            assert rung == "by_terms" and number <= 4 or rung == number, (card.id, r.key, r.robotparts, rung)
    for cid in ROBOTPARTS_NUMBERED:
        keys = {r.key.split(".")[0] for r in physics(reg.CARDS[cid])}
        assert keys <= {"M0", "M2", "M3", "M4", "M5"}, (cid, keys)  # robotparts' M1 is the datasheet: the Nominal column


def test_m6_and_m7_mean_the_same_on_every_card():
    """The coordinator, 2026-11-05: a reader who learns "M6 = residual" on the servo must not misread the arm. M0-M5 are each card's
    physics layers (robotparts' on the actuators); M6 is always the grey-box residual and M7 always the black-box net, gaps allowed."""
    for card in reg.CARDS.values():
        for r in card.rungs:
            number = int(r.key[1:].split(".")[0])
            if r.kind == "physics":
                assert 0 <= number <= 5, (card.id, r.key)
            else:
                assert r.key == {"residual": "M6", "learned": "M7"}[r.kind], (card.id, r.key, r.kind)


def test_the_servo_ladder_is_the_one_zach_described():
    """Ideal inertia, then Coulomb + viscous, then Stribeck, then cogging, delay and backlash as in the rack twin (today's)."""
    servo = reg.CARDS["servo"]
    names = {r.key: set(r.parameter_names) for r in servo.rungs}
    assert "armature_kg_m2" in names["M0"] and not names["M0"] & {"frictionloss_nm", "damping_nm_s_rad"}
    assert {"frictionloss_nm", "damping_nm_s_rad"} <= set(p.name for p in reg.added(servo, "M2"))
    assert "friction_stribeck_drop_nm" in {p.name for p in reg.added(servo, "M3")}
    assert {"ripple_harmonics", "command_delay_s", "backlash_rad"} <= {p.name for p in reg.added(servo, "M4")}
    assert reg.current_rung(servo).key == "M4"


def test_camera_ladders_are_pinhole_then_distortion_then_shutter_or_depth_bias():
    rgb = physics(reg.CARDS["camera_rgb"])
    assert {"fx_fy", "cx_cy"} <= set(rgb[0].parameter_names) and "distortion" not in rgb[0].parameter_names
    assert "distortion" in rgb[1].parameter_names and any("Brown" in ref.title for ref in rgb[1].references)
    assert any("olling" in r.name for r in rgb) and any("olling shutter" in ref.title.lower() or "rolling-shutter" in ref.title.lower()
                                                        for r in rgb for ref in r.references)
    assert any("depth bias" in r.name.lower() and any("Herrera" in ref.title for ref in r.references) for r in physics(reg.CARDS["camera_rgbd"]))


def test_learned_rungs_sit_on_top_and_bind_harder():
    for card in reg.CARDS.values():
        top_physics = physics(card)[-1]
        for r in card.rungs:
            assert r.needs is not None, (card.id, r.key)
            if r.kind == "physics":
                assert r.needs.extrapolates and r.needs.min_pct == card.coverage.gate_pct, (card.id, r.key)
                continue
            assert r.architecture and r.architecture.weights > 0 and r.architecture.history >= 1, (card.id, r.key)
            assert not r.needs.extrapolates, (card.id, r.key)
            assert r.needs.min_pct > top_physics.needs.min_pct and r.needs.min_samples > top_physics.needs.min_samples, (card.id, r.key)
            if r.kind == "learned":
                assert r.parameters == () and r.n_parameters == r.architecture.weights, (card.id, r.key)
            else:
                base = reg.rung(card, r.base)
                assert base.kind == "physics" and r.parameters == base.parameters, (card.id, r.key)
                assert r.n_parameters == base.n_parameters + r.architecture.weights
    for cid in ACTUATORS:
        kinds = [r.kind for r in reg.CARDS[cid].rungs]
        assert kinds.count("residual") == 1 and kinds.count("learned") == 1, (cid, kinds)
    for cid in ("camera_rgb", "camera_rgbd"):
        assert [r.kind for r in reg.CARDS[cid].rungs].count("residual") == 1, cid
    for cid in SENSORS:
        assert "learned" not in [r.kind for r in reg.CARDS[cid].rungs], cid  # a camera model must stay projective to measure


def test_the_servos_actuator_net_is_hwangbos():
    net = reg.rung("servo", "M7")
    a = net.architecture
    assert (a.family, a.history, a.history_dt_s, a.hidden, a.activation, a.n_inputs, a.weights) == ("MLP", 3, 0.01, (32, 32, 32), "softsign", 6, 2369)
    assert any(ref.doi == "10.1126/scirobotics.aau5872" for ref in net.references)


# --- wear --------------------------------------------------------------------------------------------------------------------------

def test_every_actuator_has_a_wear_rung_with_referenced_laws():
    assert set(reg.WEAR_LAW_REFERENCES) == set(reg.WEAR_LAWS) and all(reg.WEAR_LAW_REFERENCES.values())
    for card in reg.CARDS.values():
        worn = [r for r in card.rungs if r.wear_parameters]
        if card.id in ACTUATORS:
            assert worn, card.id
            assert physics(card)[-1].wear_parameters, (card.id, "the top physics rung carries the wear")
        for r in worn:
            names = set(r.parameter_names)
            for p in r.wear_parameters:
                w = p.wear
                assert w.law in reg.WEAR_LAWS and w.usage and w.unit and w.rate in names, (card.id, r.key, p.name)
    laws = {p.name: p.wear.law for p in reg.rung("servo", "M5.wear").wear_parameters}
    assert laws.get("backlash_rad") == "archard" and "frictionloss_nm" in laws


# --- metrics, diagnostics, gates ------------------------------------------------------------------------------------------------

def test_one_drift_diagnostic_per_type_in_zachs_words():
    for card in reg.CARDS.values():
        drifts = [d for d in card.diagnostics if d.kind == "drift"]
        assert len(drifts) == 1, card.id
        d = drifts[0]
        fidelity = {m.id for m in card.metrics if m.family == "fidelity"}
        assert d.metric in fidelity and d.message == reg.DRIFT_MESSAGE and d.settable, card.id
        assert (d.threshold.op, d.threshold.value) == ("<=", reg.DRIFT_THRESHOLD) and d.baseline, card.id
        worn = [p for r in card.rungs for p in r.wear_parameters]
        if worn:
            assert d.forecast and set(d.forecast.parameters) <= {p.name for p in worn} and d.forecast.parameters, card.id
            assert d.forecast.law in {p.wear.law for p in worn}, card.id
        assert reg.check_drift(card.id, 2.0, 1.0).message == reg.DRIFT_MESSAGE and reg.check_drift(card.id, 1.1, 1.0).status == "ok"


def test_diagnostics_read_their_cards_metrics_and_gates_their_diagnostics():
    for card in reg.CARDS.values():
        metrics = {m.id for m in card.metrics}
        dx = {d.id: d for d in card.diagnostics}
        assert len(dx) == len(card.diagnostics) and len({g.id for g in card.gates}) == len(card.gates), card.id
        assert all(d.metric in metrics for d in card.diagnostics), card.id
        assert all(g.diagnostic in dx and g.target.op in ("<=", ">=") for g in card.gates), card.id
        fidelity_gated = [m for m in card.metrics if m.family == "fidelity" and reg.metric_status(card, m.id) == "gated"]
        assert fidelity_gated, (card.id, "every type is held to the twinned ruler somewhere")
        assert {reg.metric_status(card, m.id) for m in card.metrics} <= {"gated", "observed"}


def constants(path: Path, names) -> dict:
    text = path.read_text()
    return {n: float(re.search(rf"^{n}\s*=\s*([0-9.]+)", text, re.M).group(1)) for n in names}


@pytest.mark.skipif(not (RACK_TWIN / "acceptance.py").is_file(), reason="bam_ws is not checked out")
def test_the_servos_gates_are_bam_rack_twins_acceptance_limits():
    k = constants(RACK_TWIN / "acceptance.py", ("FIDELITY_TAPES", "TORQUE_RATIO", "SPEED_PCT", "THERMOCOUPLE_C"))
    servo = reg.CARDS["servo"]
    gates = {g.acceptance: g for g in servo.gates if g.acceptance}
    want = {"T2": k["FIDELITY_TAPES"], "T3": k["TORQUE_RATIO"], "T7": k["SPEED_PCT"], "T8": k["THERMOCOUPLE_C"], "T9": k["FIDELITY_TAPES"]}
    for t, limit in want.items():
        assert t in gates and gates[t].target.value == limit, (t, gates.get(t))
    assert "T4" in gates and gates["T4"].target.value is None and gates["T4"].target.note  # the joint's allocation, per station
    reads = {d.id: d.metric for d in servo.diagnostics}
    assert reads[gates["T2"].diagnostic] == "servo.twin_fidelity" and reads[gates["T3"].diagnostic] == "servo.torque_fidelity"


# --- test types ----------------------------------------------------------------------------------------------------------------

def test_test_types_per_setting_with_recalibration_in_both():
    ids = [t.id for c in reg.CARDS.values() for t in c.tests]
    assert len(ids) == len(set(ids)), "a run is tagged with its test type id: ids are unique across cards"
    for card in reg.CARDS.values():
        assert all(t.id.startswith(card.id + ".") and t.setting in reg.SETTINGS and t.how for t in card.tests), card.id
        for setting in reg.SETTINGS:
            assert reg.tests_for(card, setting), (card.id, setting)
            assert any(t.recalibration for t in reg.tests_for(card, setting)), (card.id, setting, "recalibration")
        named = {p.name for r in card.rungs for p in r.parameters}
        assert all(set(t.identifies) <= named and t.identifies for t in card.tests), card.id
        identified = {n for t in card.tests for n in t.identifies}
        needed = {p.name for r in physics(card) for p in r.parameters if p.role != "config"}
        assert needed <= identified, (card.id, sorted(needed - identified))
    assert any("live_reid" in t.exists for t in reg.tests_for("servo", "deployed") if t.recalibration)


# --- coverage ------------------------------------------------------------------------------------------------------------------

def test_coverage_axes_have_bins_and_every_type_a_gate():
    for card in reg.CARDS.values():
        assert card.coverage.gate_pct is not None and 0 < card.coverage.gate_pct <= 100, card.id
        for a in card.coverage.axes:
            assert (a.bin_size is not None and a.bin_size > 0) or len(a.binning) >= 10, (card.id, a.name)
    axes = {a.name: a for a in reg.CARDS["servo"].coverage.axes}
    assert axes["load torque"].bin_size == cov.TAU_CELL_NM and axes["temperature"].bin_size == 10.0
    assert axes["load torque"].marginal and axes["temperature"].marginal and not axes["q"].marginal and axes["q"].bin_size is None


@pytest.mark.skipif(not (RACK_TWIN / "schedule.py").is_file(), reason="bam_ws is not checked out")
def test_the_servos_coverage_gate_is_schedule_pys():
    assert reg.CARDS["servo"].coverage.gate_pct == constants(RACK_TWIN / "schedule.py", ("MINIMUM_COVERAGE_PCT",))["MINIMUM_COVERAGE_PCT"]


@pytest.mark.skipif(not SCHEDULE.is_file(), reason="the rack archive is not mounted")
def test_can11_passes_the_servo_coverage_gate():
    result = cov.servo_coverage(json.loads(SCHEDULE.read_text()))
    assert result.pct == 66.15 and reg.coverage_gate("servo", result) == "pass"


def test_conveyor_coverage_narrow_vs_broad():
    card = reg.CARDS["conveyor"]
    one = [{"belt speed": 0.2, "load mass": 5.0}]
    broad = [{"belt speed": s, "load mass": m, "position": x, "acceleration": a} for s in (-0.45, -0.2, -0.05, 0.05, 0.2, 0.45)
             for m in (1.0, 7.0, 12.0, 17.0, 25.0) for x in (0.1, 0.6, 1.1, 1.6) for a in (-0.5, 0.5)]
    lo, hi = card.coverage.measure(one), card.coverage.measure(broad)
    assert lo.visited == 1 and lo.pct < 10 and hi.pct > 40 and hi.axes["position"] is not None


# --- calibration packages ----------------------------------------------------------------------------------------------------------

def exists(home) -> bool:
    if home.ref:
        return subprocess.run(["git", "-C", home.repo, "cat-file", "-e", f"{home.ref}:{home.path}"], capture_output=True).returncode == 0
    return (Path(home.repo) / home.path).exists()


def test_calibration_packages_are_zachs_groups_with_real_code_homes():
    groups = {p.group for p in reg.CALIBRATION_PACKAGES}
    assert groups == {"Hand Eye", "Kinematic Length", "Servo Dynamic", "Camera", "PID", "Hardstop / Homing / Rezeroing"}, groups
    assert {p.level for p in reg.CALIBRATION_PACKAGES if p.group == "Servo Dynamic"} == {"arm", "actuator"}
    assert {p.id for p in reg.CALIBRATION_PACKAGES if p.group == "Camera"} == {"camera.rgb", "camera.rgbd", "camera.hsi", "camera.line_area_scan"}
    assert any("UR" in p.note for p in reg.CALIBRATION_PACKAGES if p.group == "Kinematic Length")
    for p in reg.CALIBRATION_PACKAGES:
        assert p.serves and set(p.serves) <= set(reg.CARDS), p.id
        assert p.status in ("exists", "partial", "proposed", "unknown"), p.id
        assert (p.status == "unknown") == (not p.code), p.id
        missing = [f"{h.repo}:{h.ref or 'worktree'}:{h.path}" for h in p.code if not exists(h)]
        assert not missing, (p.id, missing)
    assert all(reg.packages_for(c) for c in ("servo", "arm_6dof", "camera_rgb", "camera_rgbd", "camera_hsi"))


# --- references ------------------------------------------------------------------------------------------------------------------

def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def test_references_are_real_and_checked():
    checked = json.loads(CHECKED.read_text())
    for where, ref in every_reference():
        assert re.search(r"\((1[89]|20)\d\d\)", ref.title) and ref.kind in ("paper", "book", "chapter", "standard", "datasheet", "doc", "code", "preprint"), (where, ref.title)
        if ref.doi:
            hit = checked["doi"].get(ref.doi)
            assert hit and hit["ok"] and norm(hit["title"])[:60] in norm(ref.title), (where, ref.doi, hit and hit["title"])
        if ref.url:
            hit = checked["url"].get(ref.url)
            assert hit and hit["ok"], (where, ref.url, hit)


def test_the_export_carries_the_ladders():
    doc = reg.export()
    servo = next(c for c in doc["cards"] if c["id"] == "servo")
    assert [r["key"] for r in servo["rungs"]] == [r.key for r in reg.CARDS["servo"].rungs]
    assert next(r for r in servo["rungs"] if r["key"] == "M7")["n_parameters"] == 2369
    assert len(doc["calibration_packages"]) == len(reg.CALIBRATION_PACKAGES) >= 10
