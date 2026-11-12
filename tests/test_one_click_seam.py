"""The one-click seam (sim2real.rig, docs/one-click-seam.md): what a rig supplies so RobotTwin(...).calibrate(on="sim", truth="sealed")
runs its whole calibration sequence against a sealed hidden truth, and eval() scores the fitted twin held out.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_one_click_seam.py

Zach (2026-11-11): "verify that you can basically get perfect calibration by applying noise to the sim vs sim w/ noise ... my goal is to
just export then have the one click .calibrate() and then just see the results." His success rule: a routine recovers the hidden values to
within a tolerance. The UR wrist is the first rig on the seam; the five-bar lane builds on this contract, so it is frozen here on a toy rig
that needs nothing but numpy (a gain and an offset behind white noise), never on the wrist.

The rules held here, each one a way the oracle could lie:
- the fit never sees the truth: every routine's fit runs inside sysid.world.sealed(), so a fit that reaches for the truth raises;
- the ruler is the committed truth (world.json) moved only by the noise model's truth_offset, never by move_truth: a moved world turns its
  row red (the mutation test of the ruler);
- every parameter the rig carries is a row: identified ones with a routine from cards.calibration ROUTINES and a tolerance, the others with
  the reason nothing identifies them (never a made-up number);
- the noise model is explicit, seeded and set by level: level 0 is noise-free, k scales every term, the same seed draws the same noise;
- eval scores held-out runs only; its floor is the sim's own repeat spread under the same noise (two draws of each held-out run).
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np
import pytest

from sim2real import rig as seam
from sim2real.twin import Description, Instance

pytest.importorskip("robot_msgs", reason="Values are robot_msgs'")

TRUTH = {"toy.gain": 2.5, "toy.offset": -0.4, "toy.hidden": 7.0}
NOMINAL = {"toy.gain": 2.0, "toy.offset": 0.0, "toy.hidden": 5.0}


def toy_description() -> Description:
    from robot_msgs.space import Basis, Value  # noqa: PLC0415

    params = {name.split(".", 1)[1]: Value(v, "1", basis=Basis.ASSUMED, source="the toy's datasheet") for name, v in NOMINAL.items()}
    return Description("toy", "Toy rig", model=None, instances=(
        Instance("cell", "Cell", None, None, structural="deployment"),
        Instance("toy", "Toy servo", "integrated_servo", "cell", params, {k: False for k in params})), source="tests")


def world_doc() -> dict:
    """The toy's world.json, read through the same seal sysid.world uses: inside sealed() it raises."""
    from sysid import world as hidden  # noqa: PLC0415

    if hidden.is_sealed():
        raise hidden.SealedWorld("the toy's world is sealed while identification runs")
    return {"truth": dict(TRUTH), "seed": 11}


def _inputs(run_id: str) -> np.ndarray:
    return np.random.default_rng(zlib.crc32(run_id.encode())).uniform(-1.0, 1.0, 400)


@dataclass
class ToyFit:
    id: str = "servo.dynamics_regression"
    identifies: tuple[str, ...] = ("toy.gain", "toy.offset")
    reach_for_truth: bool = False

    def runs(self, values):
        return [seam.Run(f"train{k}", "train", None) for k in range(4)]

    def fit(self, measured, values, twin):
        if self.reach_for_truth:
            world_doc()
        u = np.concatenate([m["u"] for m in measured.values()])
        y = np.concatenate([m["y"] for m in measured.values()])
        design = np.column_stack([u, np.ones_like(u)])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        sigma = float(np.std(y - design @ coef))
        cov = sigma ** 2 * np.linalg.inv(design.T @ design)
        half = 1.96 * np.sqrt(np.diag(cov))
        return {"toy.gain": seam.Estimate(float(coef[0]), (coef[0] - half[0], coef[0] + half[0]), "least squares"),
                "toy.offset": seam.Estimate(float(coef[1]), (coef[1] - half[1], coef[1] + half[1]), "least squares")}


class ToyRig:
    """y = gain u + offset + noise; `hidden` is never excited (no routine reaches it)."""
    name = "toy"

    def __init__(self, *, reach_for_truth: bool = False):
        self.routine = ToyFit(reach_for_truth=reach_for_truth)
        self.measured_with: list[dict] = []

    def parameters(self):
        return (seam.Parameter("toy.gain", "1", ("rel", 0.02), "proposed: the toy's use", self.routine.id),
                seam.Parameter("toy.offset", "1", ("abs", 0.02), "proposed: the toy's use", self.routine.id),
                seam.Parameter("toy.hidden", "1", None, "", None, why_not="no run excites it: no routine identifies it on this rig"))

    def noise(self):
        return seam.NoiseModel(torque_noise_nm=0.05, sources={"torque_noise_nm": "the toy's datasheet"})

    def routines(self):
        return (self.routine,)

    def held_out(self, values=None):
        return [seam.Run(f"held{k}", "held_out", None) for k in range(3)]

    def measure(self, runs, values, noise, stream, *, workers=1):
        self.measured_with.append(dict(values))
        sigma = noise.effective()["torque_noise_nm"]
        out = {}
        for run in runs:
            u = _inputs(run.id)
            rng = noise.rng(stream, run.id)
            out[run.id] = {"u": u, "y": values["toy.gain"] * u + values["toy.offset"] + rng.normal(0.0, sigma, u.size)}
        return out

    def predict(self, measured, values, *, workers=1):
        return {rid: {"u": m["u"], "y": values["toy.gain"] * m["u"] + values["toy.offset"]} for rid, m in measured.items()}

    def score(self, predicted, measured):
        per_run = {rid: {"toy": float(np.sqrt(np.mean((predicted[rid]["y"] - m["y"]) ** 2)))} for rid, m in measured.items()}
        pooled = float(np.sqrt(np.mean(np.concatenate([(predicted[rid]["y"] - m["y"]) ** 2 for rid, m in measured.items()]))))
        return seam.Score({"toy": pooled}, per_run)


def runner(rig=None, **options) -> seam.RigRunner:
    return seam.RigRunner(toy_description(), rig or ToyRig(), world=world_doc, **options)


# --- the noise model -------------------------------------------------------------------------------------------------------------------


def test_the_noise_model_is_explicit_seeded_and_set_by_level():
    noise = seam.NoiseModel(encoder_quantum_rad=1e-4, encoder_noise_rad=2e-5, velocity_noise_rad_s=1e-3, torque_noise_nm=0.01,
                            period_overrun_s=7e-4, latency_jitter_s=4e-4)
    assert set(noise.effective()) == set(seam.NoiseModel.TERMS)
    assert all(v == 0.0 for v in noise.at(0.0).effective().values()), "level 0 is noise-free"
    assert noise.at(3.0).effective()["torque_noise_nm"] == pytest.approx(0.03)
    assert noise.at(3.0).effective()["encoder_quantum_rad"] == pytest.approx(3e-4)
    one = noise.with_terms(torque_noise_nm=0.2)
    assert one.effective()["torque_noise_nm"] == pytest.approx(0.2) and one.effective()["encoder_noise_rad"] == pytest.approx(2e-5)
    a, b = noise.rng("measure", "r1").normal(size=5), noise.rng("measure", "r1").normal(size=5)
    assert np.array_equal(a, b), "the same seed and stream draw the same noise"
    assert not np.array_equal(a, noise.rng("repeat", "r1").normal(size=5)), "another stream draws independently"
    assert not np.array_equal(a, seam.NoiseModel(seed=1).rng("measure", "r1").normal(size=5))
    assert seam.NoiseModel.from_dict(noise.at(2.0).to_dict()) == noise.at(2.0)
    with pytest.raises(ValueError):
        noise.at(-1.0)
    with pytest.raises(KeyError):
        noise.with_terms(not_a_term=1.0)


def test_truth_offset_scales_the_hidden_truth_from_nominal_and_the_ruler_follows_it():
    noise = seam.NoiseModel(truth_offset=0.5)
    ruler = seam.ruler(TRUTH, NOMINAL, noise)
    assert ruler["toy.gain"] == pytest.approx(2.0 + 0.5 * (2.5 - 2.0))
    assert seam.ruler(TRUTH, NOMINAL, seam.NoiseModel())["toy.gain"] == pytest.approx(2.5), "at 1 the ruler is world.json's"
    assert seam.ruler(TRUTH, NOMINAL, seam.NoiseModel(truth_offset=0.0))["toy.offset"] == pytest.approx(0.0)


# --- calibrate: the sequence against the sealed truth --------------------------------------------------------------------------------


def test_calibrate_recovers_the_sealed_truth_within_tolerance_and_says_what_it_cannot_identify():
    cal, _ = runner().calibrate()
    rows = {r["key"]: r for r in cal.rows}
    assert set(rows) == set(TRUTH), "every parameter the rig carries is a row"
    assert rows["toy.gain"]["pass"] and rows["toy.offset"]["pass"], cal.summary()
    assert rows["toy.gain"]["ci95"][0] <= rows["toy.gain"]["recovered"] <= rows["toy.gain"]["ci95"][1]
    assert rows["toy.gain"]["routine"] == "servo.dynamics_regression"
    hidden = rows["toy.hidden"]
    assert hidden["recovered"] is None and hidden["pass"] is None and "no routine" in hidden["why_not"]
    assert [r["key"] for r in cal.unidentified] == ["toy.hidden"]
    assert cal.passed and not cal.failing
    assert cal.values["toy.gain"].basis.name == "MEASURED"


def test_the_fit_runs_sealed_a_fit_that_reaches_for_the_truth_raises():
    from sysid import world as hidden  # noqa: PLC0415

    with pytest.raises(hidden.SealedWorld):
        runner(ToyRig(reach_for_truth=True)).calibrate()


def test_the_world_plays_the_truth_and_the_fit_starts_from_nominal():
    toy = ToyRig()
    runner(toy).calibrate()
    assert toy.measured_with and all(v["toy.gain"] == TRUTH["toy.gain"] for v in toy.measured_with), "measure() is handed the truth"


def test_move_truth_moves_the_world_never_the_ruler_and_turns_its_row_red():
    cal, _ = runner().calibrate(truth={"toy.gain": 2.5 * 1.10})
    rows = {r["key"]: r for r in cal.rows}
    assert rows["toy.gain"]["true"] == pytest.approx(2.5), "the ruler stays world.json's"
    assert rows["toy.gain"]["pass"] is False and "toy.gain" in cal.failing and not cal.passed
    assert cal.truth_moved == {"toy.gain": pytest.approx(2.75)}
    with pytest.raises(KeyError):
        runner().calibrate(truth={"toy.nope": 1.0})


def test_noise_level_zero_recovers_exactly():
    cal, _ = runner().calibrate(noise=seam.NoiseModel(torque_noise_nm=0.05).at(0.0))
    rows = {r["key"]: r for r in cal.rows}
    assert rows["toy.gain"]["recovered"] == pytest.approx(2.5, abs=1e-12)


def test_a_rig_must_say_why_a_parameter_is_unidentified_and_name_real_routines():
    class Silent(ToyRig):
        def parameters(self):
            return (*super().parameters()[:2], seam.Parameter("toy.hidden", "1", None, "", None))

    with pytest.raises(ValueError, match="why"):
        runner(Silent()).calibrate()

    class Invented(ToyRig):
        def __init__(self):
            super().__init__()
            self.routine = ToyFit(id="servo.made_up")

        def parameters(self):
            return tuple(seam.Parameter(p.key, p.unit, p.tolerance, p.tolerance_source, "servo.made_up" if p.routine else None, p.why_not)
                         for p in super().parameters())

    with pytest.raises(KeyError, match="servo.made_up"):
        runner(Invented()).calibrate()


# --- eval: held out, over the sim's own repeat floor -----------------------------------------------------------------------------------


def test_a_routine_may_set_a_value_for_the_twin_without_claiming_it():
    """`adjusts`: a value the twin needs that the routine sets but does not identify (a chain's masses on their visible subspace). The twin
    uses it; its row stays "not identified" with no verdict, so nothing unidentified is ever reported as found."""

    class Nuisance(ToyFit):
        adjusts = ("toy.hidden",)

        def fit(self, measured, values, twin):
            return {**super().fit(measured, values, twin), "toy.hidden": seam.Estimate(6.0, None, "set for the twin")}

    toy = ToyRig()
    toy.routine = Nuisance()
    cal, state = runner(toy).calibrate()
    row = {r["key"]: r for r in cal.rows}["toy.hidden"]
    assert row["recovered"] is None and row["pass"] is None and row["set_for_twin"] == 6.0
    assert state["values"]["toy.hidden"] == 6.0 and "toy.hidden" not in cal.values

    class Undeclared(ToyFit):
        def fit(self, measured, values, twin):
            return {**super().fit(measured, values, twin), "toy.hidden": seam.Estimate(6.0)}

    toy = ToyRig()
    toy.routine = Undeclared()
    with pytest.raises(KeyError, match="does not declare"):
        runner(toy).calibrate()


def test_eval_scores_held_out_runs_over_the_repeat_floor():
    r = runner()
    cal, state = r.calibrate()
    fitted = seam.RigRunner(r.description, r.rig, world=world_doc, state=state)
    report = fitted.eval()
    # two noise draws of one run differ by sqrt(2) sigma; a perfect twin misses a draw by sigma: the ratio sits near 1/sqrt(2)
    assert report.floor["toy"] == pytest.approx(math.sqrt(2) * 0.05, rel=0.15)
    assert report.ratios["fitted"]["toy"] == pytest.approx(1 / math.sqrt(2), rel=0.15)
    assert report.ratios["nominal"]["toy"] > 5 * report.ratios["fitted"]["toy"]
    gates = {g.id: g for g in report.gates}
    assert gates["twinned"].passed and gates["recovery"].passed and report.passed, report.summary()


def test_the_fitted_twins_description_carries_what_the_routines_identified():
    from robot_msgs.space import Basis  # noqa: PLC0415

    from sim2real.twin import RobotTwin  # noqa: PLC0415

    twin = RobotTwin(toy_description().instances, name="toy")
    twin.runner, twin.model = runner(), "toy twin"  # the toy ships no sysid/examples/toy/rig.py: its runner is handed in
    fitted = twin.calibrate(on="sim")
    params, prior = fitted.parameters["toy"], twin.parameters["toy"]
    for key in ("gain", "offset"):
        row = {r["key"]: r for r in fitted.calibration_.rows}[f"toy.{key}"]
        assert float(params[key]) == row["recovered"] and params[key].basis == Basis.MEASURED
        assert params[key].source.startswith("sim2real calibrate · on=sim · toy twin · ")
        assert (params[key].low, params[key].high) == tuple(row["ci95"])
    # the unidentified parameter keeps its prior; the loaded toy is untouched
    assert params["hidden"] is prior["hidden"] and float(prior["gain"]) == NOMINAL["toy.gain"]


def test_eval_needs_a_fitted_twin_and_refuses_a_training_run():
    with pytest.raises(RuntimeError, match="calibrate"):
        runner().eval()

    class Leaky(ToyRig):
        def held_out(self, values=None):
            return [seam.Run("train0", "held_out", None), *super().held_out(values)]

    r = runner(Leaky())
    _, state = r.calibrate()
    with pytest.raises(ValueError, match="held-out runs only"):
        seam.RigRunner(r.description, r.rig, world=world_doc, state=state).eval()
