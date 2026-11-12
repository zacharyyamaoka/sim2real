"""The calibrate() back end (PEP 0001, docs/peps/0001-sim2real-docs-site-and-calibrate-backend.md): models picked per part give the
parameters, the catalog's routines that identify them are selected by metric, ordered from their declared dependencies, steered by a
CalibrationConfig, and calibrate() returns one stable, documented record.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_calibration_backend.py

Written by the designer BEFORE the back end (red: sim2real.calibration does not exist yet). The builder may not edit this file. The
ruler for the order is the UR wrist's hand-written routine tuple as it actually ran (src/sim2real/data/ur_wrist_one_click_2026-11-11.json,
its calibration's `routines`), reproduced from the catalog's declarations (cards/calibration.py requires/uses/refines) in every input
order: a planner that sorts by anything else cannot pass. The fast tests need no MuJoCo and no bam_ws.
"""

from __future__ import annotations

import dataclasses
import inspect
import itertools
import json
import math
import random
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
WRIST_RUN = REPO / "src" / "sim2real" / "data" / "ur_wrist_one_click_2026-11-11.json"
FIXTURE = REPO / "tests" / "fixtures" / "calibration_record_v1.json"

def _calibration():
    """WHY imported per test and never importorskip: a missing back end must FAIL here, not skip."""
    import sim2real.calibration as module  # noqa: PLC0415

    return module


# --- the wrist ruler ---------------------------------------------------------------------------------------------------------------------


def wrist_run() -> dict:
    return json.loads(WRIST_RUN.read_text())


def wrist_names() -> dict[str, str]:
    """The wrist's parameter keys -> names, from its own description (structured; no key is parsed)."""
    from sim2real.twin import describe  # noqa: PLC0415

    return {f"{i.id}.{n}": n for i in describe("ur_wrist_test_rig").instances for n in i.parameters}


def wrist_routines() -> list[SimpleNamespace]:
    """Routine-likes carrying what the rig's routine objects carry (id, identifies, adjusts) as they ran, and NO declarations of their
    own: the order must come from the catalog's."""
    out = []
    for step in wrist_run()["calibration"]["routines"]:
        out.append(SimpleNamespace(id=step["routine"], identifies=tuple(step["identifies"]),
                                   adjusts=tuple(sorted(set(step["found"]) - set(step["identifies"])))))
    return out


WRIST_ORDER = ("servo.backlash_reversal_held", "servo.breakaway_two_sided", "homing.single_touch", "servo.dynamics_regression",
               "arm.gravity_direction", "servo.command_delay_scan")


def test_the_ruler_is_the_wrists_hand_order_as_it_ran():
    assert tuple(s["routine"] for s in wrist_run()["calibration"]["routines"]) == WRIST_ORDER


def test_the_catalog_declares_the_wrist_routines_dependencies():
    from sim2real.cards import calibration as cat  # noqa: PLC0415

    by_id = {r.id: r for r in cat.ROUTINES}
    for rid in WRIST_ORDER:
        r = by_id[rid]
        assert isinstance(r.requires, tuple) and isinstance(r.uses, tuple) and isinstance(r.refines, tuple), rid
    assert "backlash_rad" in by_id["servo.breakaway_two_sided"].requires
    assert "command_delay_s" in by_id["servo.command_delay_scan"].refines


def test_the_wrist_order_comes_from_the_declarations_in_every_input_order():
    cal = _calibration()
    names = wrist_names()
    routines = wrist_routines()
    seen = 0
    for perm in itertools.permutations(routines):
        assert tuple(r.id for r in cal.order(list(perm), names=names)) == WRIST_ORDER, [r.id for r in perm]
        seen += 1
    assert seen == 720


def test_order_returns_the_objects_it_was_given():
    cal = _calibration()
    routines = wrist_routines()
    ordered = cal.order(list(reversed(routines)), names=wrist_names())
    assert {id(r) for r in ordered} == {id(r) for r in routines} and len(ordered) == len(routines)


def test_a_cycle_is_refused_naming_the_routines_and_the_keys_on_each_edge():
    cal = _calibration()
    a = SimpleNamespace(id="custom.a", identifies=("p.x",), requires=("p.y",))
    b = SimpleNamespace(id="custom.b", identifies=("p.y",), requires=("p.x",))
    with pytest.raises(cal.CalibrationCycleError) as caught:
        cal.order([a, b])
    message = str(caught.value)
    for word in ("custom.a", "custom.b", "p.x", "p.y", "uses"):
        assert word in message, (word, message)
    assert set(caught.value.cycle) == {"custom.a", "custom.b"}
    assert isinstance(caught.value, ValueError)


def test_instance_declarations_override_the_catalog_and_soft_edges_only_break_ties():
    cal = _calibration()
    first = SimpleNamespace(id="custom.first", identifies=("p.a",), uses=("p.b",))     # would like p.b first ...
    second = SimpleNamespace(id="custom.second", identifies=("p.b",), requires=("p.a",))  # ... but p.b needs p.a: the hard edge wins
    assert [r.id for r in cal.order([second, first])] == ["custom.first", "custom.second"]
    left = SimpleNamespace(id="custom.left", identifies=("p.c",), uses=("p.d",))
    right = SimpleNamespace(id="custom.right", identifies=("p.d",))
    assert [r.id for r in cal.order([left, right])] == ["custom.right", "custom.left"], "a soft edge orders independent routines"


def test_refines_runs_after_every_routine_that_sets_the_key_provisionally():
    cal = _calibration()
    scan = SimpleNamespace(id="custom.scan", identifies=("p.delay",), refines=("p.delay",))
    fit = SimpleNamespace(id="custom.fit", identifies=("p.mass",), adjusts=("p.delay",))
    assert [r.id for r in cal.order([scan, fit])] == ["custom.fit", "custom.scan"]


def test_a_configure_routine_runs_before_every_routine_that_requires_its_settings():
    cal = _calibration()
    lock = SimpleNamespace(id="custom.exposure", identifies=(), configures=("cam.exposure", "cam.gain"))
    bundle = SimpleNamespace(id="custom.bundle", identifies=("tag.pose",), requires=("cam.exposure",))
    intrinsics = SimpleNamespace(id="custom.intrinsics", identifies=("cam.fx_fy",), requires=("cam.gain",))
    out = [r.id for r in cal.order([intrinsics, bundle, lock])]
    assert out[0] == "custom.exposure" and set(out[1:]) == {"custom.bundle", "custom.intrinsics"}


# --- selection: models -> parameters -> routines ------------------------------------------------------------------------------------------


def test_picking_models_gives_the_parameters_and_a_minimal_cover_of_routines():
    cal = _calibration()
    from sim2real.cards import domain as dm  # noqa: PLC0415

    picked = {"cam": ("camera", "M1.measurement.distortion")}
    sel = cal.select(picked)
    names = set(dm.model("camera", "M1.measurement.distortion").parameters)
    assert {(i, n) for i, _t, n in sel.parameters} == {("cam", n) for n in names}
    covered = {n for rid in sel.routines for (_i, n) in sel.covers[rid]}
    assert covered | {n for _i, n, _why in sel.uncovered} == names
    assert "camera.intrinsics_charuco" in sel.routines, "the only routine for distortion"
    for rid in sel.routines:  # minimal: drop any one and something it alone covered goes uncovered
        rest = {n for other in sel.routines if other != rid for (_i, n) in sel.covers[other]}
        assert not {n for (_i, n) in sel.covers[rid]} <= rest, (rid, sel.routines)
    for rid in sel.routines:
        assert sel.why[rid], rid


def test_the_budget_drops_bench_routines_and_says_what_goes_uncovered():
    cal = _calibration()
    from sim2real.cards import calibration as cat  # noqa: PLC0415

    by_id = {r.id: r for r in cat.ROUTINES}
    config = cal.CalibrationConfig(budget=cal.Budget(settings=("deployed",)))
    sel = cal.select({"cam": ("camera", "M1.measurement.distortion")}, config=config)
    assert all(by_id[rid].setting in ("deployed", "both") for rid in sel.routines), sel.routines
    uncovered = {n: why for _i, n, why in sel.uncovered}
    assert "distortion" in uncovered and "bench" in uncovered["distortion"], uncovered
    assert any(rid == "camera.intrinsics_charuco" and "bench" in why for rid, why in sel.dropped), sel.dropped


def test_unimplemented_routines_are_never_selected_and_say_so():
    cal = _calibration()
    sel = cal.select({"cam": ("camera", "M1.measurement.distortion")})
    assert "hand_eye.ax_xb" not in sel.routines
    assert any(rid == "hand_eye.ax_xb" and "not implemented" in why for rid, why in sel.dropped), sel.dropped


def test_known_parameters_are_not_planned():
    cal = _calibration()
    config = cal.CalibrationConfig(known={"cam.fx_fy": 600.0, "cam.cx_cy": 320.0, "cam.distortion": 0.0})
    sel = cal.select({"cam": ("camera", "M1.measurement.distortion")}, config=config)
    assert {n for _i, _t, n in sel.parameters} == {"extrinsics"}
    assert "camera.intrinsics_charuco" not in sel.routines


def test_the_metric_reads_recovery_at_the_configured_noise_level():
    """sysid/results/calibration_routines.json: at 1x the dynamics regression passes and live re-identification fails; at 10x the reverse."""
    cal = _calibration()
    picked = {"j1": ("integrated_servo", "M2.dynamics.coulomb_viscous")}
    at_1x = cal.select(picked, config=cal.CalibrationConfig(level="1x"))
    at_10x = cal.select(picked, config=cal.CalibrationConfig(level="10x"))
    assert "servo.dynamics_regression" in at_1x.routines and "servo.live_reid_t10" not in at_1x.routines
    assert "servo.live_reid_t10" in at_10x.routines and "servo.dynamics_regression" not in at_10x.routines
    uncovered = {n: why for _i, n, why in at_1x.uncovered}
    assert {"kp_nm_rad", "kd_nm_s_rad"} <= set(uncovered), "no catalog routine identifies the gains"


# --- the config ----------------------------------------------------------------------------------------------------------------------------


def test_the_config_is_a_frozen_value_with_a_round_trip():
    cal = _calibration()
    config = cal.CalibrationConfig(models={"can14": "M4.dynamics.twin"}, known={"can14.backlash_rad": 0.003},
                                   exclude=("servo.command_delay_scan",), level="3x", seed=7,
                                   budget=cal.Budget(settings=("bench",), max_wall_time_s=3600.0, max_equipment_usd=500.0))
    assert dataclasses.is_dataclass(config) and config.__dataclass_params__.frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.level = "1x"  # type: ignore[misc]
    tuned = config.with_routine("servo.breakaway_two_sided", cycles=5)
    assert tuned is not config and tuned.routines["servo.breakaway_two_sided"].options == {"cycles": 5}
    assert "servo.breakaway_two_sided" not in config.routines
    back = cal.CalibrationConfig.from_dict(json.loads(json.dumps(tuned.to_dict())))
    assert back == tuned


# --- the seam: a toy rig through RobotTwin.calibrate(config=...) -------------------------------------------------------------------------------


TRUTH = {"toy.gain": 2.5, "toy.offset": -0.4}
NOMINAL = {"toy.gain": 2.0, "toy.offset": 0.0}


def _inputs(run_id: str) -> np.ndarray:
    return np.random.default_rng(zlib.crc32(run_id.encode())).uniform(-1.0, 1.0, 300)


def toy_description():
    from robot_msgs.space import Basis, Value  # noqa: PLC0415

    from sim2real.twin import Description, Instance  # noqa: PLC0415

    params = {k.split(".", 1)[1]: Value(v, "1", basis=Basis.ASSUMED, source="the toy's datasheet") for k, v in NOMINAL.items()}
    return Description("toy", "Toy rig", model=None, instances=(
        Instance("cell", "Cell", None, None, structural="deployment"),
        Instance("toy", "Toy servo", "integrated_servo", "cell", params, {k: False for k in params})), source="tests")


def world_doc() -> dict:
    from sysid import world as hidden  # noqa: PLC0415

    if hidden.is_sealed():
        raise hidden.SealedWorld("sealed")
    return {"truth": dict(TRUTH), "seed": 3}


@dataclass
class OffsetFit:
    """Registered id (the seam refuses others); declares no dependency."""
    id: str = "servo.backlash_reversal_held"
    identifies: tuple[str, ...] = ("toy.offset",)
    requires: tuple[str, ...] = ()

    def runs(self, values):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(f"zero{k}", "train", None) for k in range(3)]

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        y = np.concatenate([m["y"] - values["toy.gain"] * m["u"] for m in measured.values()])
        return {"toy.offset": seam.Estimate(float(np.mean(y)), (float(np.mean(y)) - 0.01, float(np.mean(y)) + 0.01), "mean residual")}


@dataclass
class GainFit:
    id: str = "servo.breakaway_two_sided"
    identifies: tuple[str, ...] = ("toy.gain",)
    requires: tuple[str, ...] = ("toy.offset",)
    options: dict = field(default_factory=lambda: {"runs": 4})
    saw_offset: list = field(default_factory=list)

    def runs(self, values):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(f"gain{k}", "train", None) for k in range(int(self.options["runs"]))]

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        self.saw_offset.append(values["toy.offset"])
        u = np.concatenate([m["u"] for m in measured.values()])
        y = np.concatenate([m["y"] for m in measured.values()]) - values["toy.offset"]
        gain = float(u @ y / (u @ u))
        return {"toy.gain": seam.Estimate(gain, (gain - 0.01, gain + 0.01), "least squares through the found offset")}


class ToyRig:
    name = "toy"

    def __init__(self):
        self.gain, self.offset = GainFit(), OffsetFit()

    def parameters(self):
        from sim2real import rig as seam  # noqa: PLC0415

        return (seam.Parameter("toy.gain", "1", ("rel", 0.05), "proposed", self.gain.id),
                seam.Parameter("toy.offset", "1", ("abs", 0.05), "proposed", self.offset.id))

    def noise(self):
        from sim2real import rig as seam  # noqa: PLC0415

        return seam.NoiseModel(torque_noise_nm=0.02, sources={"torque_noise_nm": "the toy's datasheet"})

    def routines(self):
        return (self.gain, self.offset)   # WRONG on purpose: the gain needs the offset first

    def held_out(self, values=None):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(f"held{k}", "held_out", None) for k in range(2)]

    def measure(self, runs, values, noise, stream, *, workers=1):
        sigma = noise.effective()["torque_noise_nm"]
        out = {}
        for run in runs:
            u = _inputs(run.id)
            out[run.id] = {"u": u, "y": values["toy.gain"] * u + values["toy.offset"] + noise.rng(stream, run.id).normal(0.0, sigma, u.size)}
        return out

    def predict(self, measured, values, *, workers=1):
        return {rid: {"u": m["u"], "y": values["toy.gain"] * m["u"] + values["toy.offset"]} for rid, m in measured.items()}

    def score(self, predicted, measured):
        from sim2real import rig as seam  # noqa: PLC0415

        per_run = {rid: {"toy": float(np.sqrt(np.mean((predicted[rid]["y"] - m["y"]) ** 2)))} for rid, m in measured.items()}
        return seam.Score({"toy": float(np.mean([v["toy"] for v in per_run.values()]))}, per_run)


@pytest.fixture
def toy_twin(monkeypatch):
    pytest.importorskip("robot_msgs")
    from sim2real import rig as seam  # noqa: PLC0415
    from sim2real import twin as twin_module  # noqa: PLC0415

    rig = ToyRig()
    monkeypatch.setattr(twin_module, "_runner", lambda description, workers: seam.RigRunner(description, rig, workers=1, world=world_doc))
    d = toy_description()
    return twin_module.RobotTwin(d.instances, name="toy"), rig


def test_calibrate_takes_a_config():
    from sim2real.twin import RobotTwin  # noqa: PLC0415

    assert "config" in inspect.signature(RobotTwin.calibrate).parameters


def test_calibrate_runs_the_planned_order_and_each_routine_sees_the_earlier_ones_results(toy_twin):
    twin, rig = toy_twin
    fitted = twin.calibrate(on="sim")
    assert fitted.plan_.ids == ("servo.backlash_reversal_held", "servo.breakaway_two_sided"), "automatic: offset before gain"
    ran = [step["routine"] for step in fitted.calibration_.routines]
    assert ran == list(fitted.plan_.ids)
    assert rig.gain.saw_offset and rig.gain.saw_offset[-1] != NOMINAL["toy.offset"], "the gain fit saw the found offset, not the prior"
    assert fitted.values_["toy.gain"].value == pytest.approx(TRUTH["toy.gain"], rel=0.05)


def test_known_values_are_fixed_and_their_routine_dropped(toy_twin):
    cal = _calibration()
    twin, rig = toy_twin
    fitted = twin.calibrate(on="sim", config=cal.CalibrationConfig(known={"toy.offset": TRUTH["toy.offset"]}))
    assert fitted.plan_.ids == ("servo.breakaway_two_sided",)
    assert any(rid == "servo.backlash_reversal_held" and "known" in why for rid, why in fitted.plan_.dropped)
    assert rig.gain.saw_offset[-1] == pytest.approx(TRUTH["toy.offset"])


def test_per_routine_options_reach_a_copy_of_the_routine_and_unknown_options_are_refused(toy_twin):
    cal = _calibration()
    twin, rig = toy_twin
    fitted = twin.calibrate(on="sim", config=cal.CalibrationConfig().with_routine("servo.breakaway_two_sided", runs=6))
    gain_step = next(s for s in fitted.calibration_.routines if s["routine"] == "servo.breakaway_two_sided")
    assert gain_step["runs"] == 6 and rig.gain.options == {"runs": 4}, "the rig's own routine object is not mutated"
    with pytest.raises(KeyError, match="no_such_option"):
        twin.calibrate(on="sim", config=cal.CalibrationConfig().with_routine("servo.breakaway_two_sided", no_such_option=1))


def test_an_injected_routine_replaces_the_rigs_implementation_and_an_unregistered_id_is_refused(toy_twin):
    cal = _calibration()
    twin, rig = toy_twin
    mine = OffsetFit()
    fitted = twin.calibrate(on="sim", config=cal.CalibrationConfig(custom=(mine,)))
    step = next(s for s in fitted.plan_.steps if s.routine == "servo.backlash_reversal_held")
    assert step.source == "custom"
    stranger = OffsetFit(id="custom.not_in_the_catalog")
    with pytest.raises(cal.CalibrationPlanError, match="cards/calibration.py"):
        twin.calibrate(on="sim", config=cal.CalibrationConfig(custom=(stranger,)))


def test_an_explicit_order_that_breaks_a_requirement_is_refused(toy_twin):
    cal = _calibration()
    twin, _rig = toy_twin
    with pytest.raises(cal.CalibrationPlanError, match="toy.offset"):
        twin.calibrate(on="sim", config=cal.CalibrationConfig(order=("servo.breakaway_two_sided", "servo.backlash_reversal_held")))
    fitted = twin.calibrate(on="sim", config=cal.CalibrationConfig(order=("servo.backlash_reversal_held", "servo.breakaway_two_sided")))
    assert fitted.plan_.source == "config.order"


def test_the_budget_refuses_a_plan_over_it(toy_twin):
    cal = _calibration()
    twin, _rig = toy_twin
    over = cal.CalibrationConfig(budget=cal.Budget(max_wall_time_s=1.0), strict=True)
    with pytest.raises(cal.CalibrationPlanError, match="wall"):
        twin.calibrate(on="sim", config=over)


def test_noise_in_two_places_is_refused(toy_twin):
    cal = _calibration()
    twin, _rig = toy_twin
    with pytest.raises(ValueError, match="noise"):
        twin.calibrate(on="sim", noise=3.0, config=cal.CalibrationConfig(noise=1.0))


# --- the record calibrate() returns ----------------------------------------------------------------------------------------------------------


RECORD_KEYS = {"schema", "twin", "backend", "model", "written", "seconds", "noise", "plan", "parameters", "routines", "passed", "failing",
               "evaluation"}
PARAMETER_KEYS = {"key", "instance", "name", "unit", "nominal", "value", "ci95", "true", "error", "tolerance", "pass", "routine",
                  "method", "why_not"}
ROUTINE_KEYS = {"routine", "identifies", "runs", "seconds", "found"}
STEP_KEYS = {"routine", "title", "kind", "setting", "identifies", "requires", "uses", "refines", "after", "why_here", "wall_time_s",
             "operator_time_s", "equipment_usd", "recovery", "source"}


def test_the_record_schema_is_the_frozen_fixture():
    cal = _calibration()
    fixture = json.loads(FIXTURE.read_text())
    assert cal.RECORD_SCHEMA == fixture["schema"] == "sim2real.calibration/1"
    assert set(fixture) == RECORD_KEYS
    assert all(set(p) == PARAMETER_KEYS for p in fixture["parameters"])
    assert all(set(r) == ROUTINE_KEYS for r in fixture["routines"])
    assert all(set(s) == STEP_KEYS for s in fixture["plan"]["steps"])


def test_the_wrist_run_becomes_a_record_losing_nothing():
    cal = _calibration()
    from sim2real.twin import describe  # noqa: PLC0415

    doc = wrist_run()
    record = cal.CalibrationRecord.from_rig(doc["calibration"], report=doc["report"], description=describe("ur_wrist_test_rig"))
    out = record.to_dict()
    assert set(out) == RECORD_KEYS and out["schema"] == "sim2real.calibration/1"
    rows = {r["key"]: r for r in doc["calibration"]["rows"]}
    params = {p["key"]: p for p in out["parameters"]}
    assert set(params) == set(rows)
    for key, row in rows.items():
        p = params[key]
        assert set(p) == PARAMETER_KEYS
        assert p["value"] == row["recovered"] and p["routine"] == row["routine"] and p["pass"] == row["pass"]
        assert (p["ci95"] is None and not row["ci95"]) or list(p["ci95"]) == list(row["ci95"])
        assert p["instance"] + "." + p["name"] == key
    assert [r["routine"] for r in out["routines"]] == list(WRIST_ORDER)
    assert out["passed"] == doc["calibration"]["passed"] and out["failing"] == doc["calibration"]["failing"]
    assert out["evaluation"] is not None and out["evaluation"]["passed"] == doc["report"]["passed"]
    assert cal.CalibrationRecord.from_dict(json.loads(json.dumps(out))).to_dict() == out


def test_a_fitted_twin_carries_the_plan_and_the_record(toy_twin):
    cal = _calibration()
    twin, _rig = toy_twin
    fitted = twin.calibrate(on="sim")
    assert isinstance(fitted.plan_, cal.CalibrationPlan)
    record = fitted.record_.to_dict()
    assert set(record) == RECORD_KEYS and record["plan"]["steps"] and set(record["plan"]["steps"][0]) == STEP_KEYS
    assert [s["routine"] for s in record["plan"]["steps"]] == list(fitted.plan_.ids)
    for p in record["parameters"]:
        assert set(p) == PARAMETER_KEYS
        if p["value"] is not None and p["ci95"] is not None:
            assert p["ci95"][0] <= p["value"] <= p["ci95"][1] or math.isclose(p["ci95"][0], p["ci95"][1])


@pytest.mark.skipif(__import__("os").environ.get("SIM2REAL_SLOW") != "1", reason="the wrist end to end runs tens of minutes (SIM2REAL_SLOW=1)")
def test_slow_the_wrist_calibrates_in_the_planned_order_which_is_its_hand_order():
    import sim2real  # noqa: PLC0415

    twin = sim2real.examples.ur_wrist_test_rig()
    assert tuple(_calibration().plan(twin).ids) == WRIST_ORDER
    assert tuple(r.id for r in twin.runner.rig.routines()) == WRIST_ORDER
    fitted = twin.calibrate(on="sim")
    assert fitted.plan_.ids == WRIST_ORDER and [s["routine"] for s in fitted.record_.to_dict()["routines"]] == list(WRIST_ORDER)


def test_shuffle_seed_is_stable():
    # WHY: the permutation test above is exhaustive; this pins that random.shuffle-based callers get the same answer (no dict-order leak)
    cal = _calibration()
    names = wrist_names()
    routines = wrist_routines()
    rng = random.Random(20261111)
    for _ in range(5):
        rng.shuffle(routines)
        assert tuple(r.id for r in cal.order(routines, names=names)) == WRIST_ORDER


# --- added by the designer on the same base commit (2026-11-12, Zach's reply 2): kinds, collect vs fit, per-type options, the docs ------


def test_with_no_declared_edge_the_kinds_run_configure_fit_tune_measure():
    """Zach, 2026-11-12: "configure -> fit -> tune -> measure" (cards/schema.py KIND_STAGE; "identify" is the catalog's word for fit)."""
    cal = _calibration()
    m = SimpleNamespace(id="custom.m", identifies=(), kind="measure")
    t = SimpleNamespace(id="custom.t", identifies=(), configures=("c.gain",), kind="tune")
    f = SimpleNamespace(id="custom.f", identifies=("p.f",), kind="identify")
    c = SimpleNamespace(id="custom.c", identifies=(), configures=("c.lock",), kind="configure")
    for perm in itertools.permutations([m, t, f, c]):
        assert [r.id for r in cal.order(list(perm))] == ["custom.c", "custom.f", "custom.t", "custom.m"], [r.id for r in perm]
    needs_tune = SimpleNamespace(id="custom.f2", identifies=("p.g",), requires=("c.gain",), kind="identify")
    out = [r.id for r in cal.order([needs_tune, t, c])]
    assert out == ["custom.c", "custom.t", "custom.f2"], "a declared requirement beats the stage: the fit waits for the tuned gain"


def test_a_tune_that_refines_a_configured_setting_runs_after_the_configure():
    cal = _calibration()
    lock = SimpleNamespace(id="custom.lock", identifies=(), configures=("cam.exposure", "cam.gain"), kind="configure")
    tune = SimpleNamespace(id="custom.tune", identifies=(), configures=("cam.exposure", "cam.gain", "cam.fps"), refines=("cam.exposure",),
                           kind="tune")
    assert [r.id for r in cal.order([tune, lock])] == ["custom.lock", "custom.tune"]


def test_collect_then_fit_on_recorded_data_without_measuring_again(toy_twin, monkeypatch):
    """Zach, 2026-11-12: "for deployment stuff ... separate the data collection routine and then fitting which just works on any type of
    data". collect() plays every planned routine's runs once; calibrate(data=...) fits from them and never touches the backend's measure."""
    cal = _calibration()
    twin, rig = toy_twin
    data = cal.collect(twin)
    assert tuple(data.plan.ids) == ("servo.backlash_reversal_held", "servo.breakaway_two_sided")
    assert {f"zero{k}" for k in range(3)} | {f"gain{k}" for k in range(4)} <= set(data.runs)

    def measured_again(*_args, **_kwargs):
        raise AssertionError("calibrate(data=...) measured again")

    monkeypatch.setattr(rig, "measure", measured_again)
    fitted = twin.calibrate(data=data)
    assert fitted.values_["toy.gain"].value == pytest.approx(TRUTH["toy.gain"], rel=0.05)
    assert fitted.values_["toy.offset"].value == pytest.approx(TRUTH["toy.offset"], abs=0.05)
    short = dataclasses.replace(data, runs={k: v for k, v in data.runs.items() if k != "gain0"})
    with pytest.raises(cal.CalibrationPlanError, match="gain0"):
        twin.calibrate(data=short)


def test_each_type_declares_its_model_and_routine_options_default_first():
    """Black-box design (Zach, 2026-11-11): the part's designer offers model options and routine options, a default and alternatives."""
    cal = _calibration()
    from sim2real.cards import calibration as cat  # noqa: PLC0415
    from sim2real.cards import domain as dm  # noqa: PLC0415

    ids = {r.id for r in cat.ROUTINES}
    for tid in dm.TYPE_ORDER:
        o = cal.options(tid)
        assert o.type == tid and o.models, tid
        assert set(o.models) <= {m.id for m in dm.models(tid)}, tid
        assert o.models[0] in {m.id for m in dm.current_models(tid)}, f"{tid}: the default model is today's model"
        assert set(o.routines) | set(o.setup) <= ids, tid
        assert set(o.routines) <= {rid for rids in dm.parameter_routines().get(tid, {}).values() for rid in rids}, tid
    assert cal.options("camera").setup == ("camera.exposure_lock",)


def test_a_types_setup_routines_join_the_plan_but_not_the_cover():
    cal = _calibration()
    picked = {"cam": ("camera", "M1.measurement.distortion")}
    sel = cal.select(picked)
    assert "camera.exposure_lock" in sel.setup and "camera.exposure_lock" not in sel.routines
    assert "setup" in sel.why["camera.exposure_lock"]
    assert "camera.exposure_lock" not in cal.select(picked, config=cal.CalibrationConfig(exclude=("camera.exposure_lock",))).setup


def test_the_record_and_the_order_rule_are_documented_for_readers():
    """docs/CALIBRATE.md is what the docs site renders as "What calibrate() returns" (PEP 0001): every record key, by name."""
    text = (REPO / "docs" / "CALIBRATE.md").read_text()
    for key in sorted(RECORD_KEYS | PARAMETER_KEYS | ROUTINE_KEYS | STEP_KEYS):
        assert f"`{key}`" in text, key
    for word in ("configure", "fit", "tune", "measure", "`requires`", "`uses`", "`refines`", "CalibrationConfig", "collect"):
        assert word in text, word


def test_plan_takes_picked_models_without_a_twin():
    """plan() answers "what would calibrate() run, in what order" for picked models alone (the docs site and a part designer ask it)."""
    cal = _calibration()
    plan = cal.plan({"cam": ("camera", "M1.measurement.distortion")})
    assert isinstance(plan, cal.CalibrationPlan)
    assert plan.ids[0] == "camera.exposure_lock", "the configure stage runs first"
    assert "camera.intrinsics_charuco" in plan.ids
    assert all(hasattr(s, "routine") and hasattr(s, "why_here") for s in plan.steps)
