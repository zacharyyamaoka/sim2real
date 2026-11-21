"""Gap C: PID tuna is a calibration routine of kind "tune": the planner schedules it after the fits, sim2real runs it (sim2real -> pidtuna,
one way) on the fitted twin, it proposes the board's feedback gains as settings (never model values), and a hidden-truth test grades it
on the performance it gains (2026-11-18, red first).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_pid_tune_routine.py

Run it on a cloud VM while the arm is powered: in sim2real's venv (fast), in bam_rack_twin's venv (the pendulum tests; SIM2REAL_REQUIRE_RACK=1
turns their skip into a failure), and the slow grade (SIM2REAL_SLOW=1, ~1200 tapes on pidtuna's ServoSim). The orchestrator, never the
implementer, runs the grade with SIM2REAL_WRITE_LADDERS=1 and commits sysid/results/routine_ladders/pid.pidtuna.json; the VM needs pidtuna
(no remote: carried by the cut, SIM2REAL_PIDTUNA pointing at it).

Zach: "PID Tuna is the backend for one of the routines certaintily...." (2026-11-17); PID tuning is "calibration or like tune beacuse there
is not a real to reference it off of its just like tuning for another metric..." and PID tuna stays "its own standalone thing"
(2026-11-11); "So feedback control / We have basically like PID Tuna to do the calibration" and ".calibrate() ... Kinematics. Dynamics, etc.
PID" (2026-11-18). Real arm = PD + feed-forward only, never an integrator (2026-11-13).

The ruler (written before the code; whoever turns it green may not edit it):
1. Catalog: pid.pidtuna is kind "tune" by a recorded decision; it identifies nothing; it configures the servo's feedback gains (kp, kd); it
   requires the fitted inertia and friction; its code homes and ladder are named; its catalog time is what runs today, the SIM tier on the
   fitted twin: no robot time.
2. Planner: every integrated servo wants it (options.SETUP), after the routines that find what it requires; the gains stay "not
   identified" and their reason says they are read from the board's config receipt and pid.pidtuna proposes new ones; exclude= and a
   deployed-only budget drop it by name; a tune whose requirements were all dropped is dropped too, naming them.
3. Seam: a TUNE's outputs are settings: recorded in its step and on the fitted twin (settings_), handed to later routines in their own
   channel (handle.settings), never in the values a routine fits with, never replayed at, never a parameter row's owner. A CONFIGURE
   routine's outputs still enter the values (later measurements run at them). A tune's proposal (pidtuna.config.proposal) is kept
   (fitted.proposals_).
4. Wrapper: importing it imports no pidtuna, pidtuna imports no sim2real; it plays no robot time; it hands PID tuna the board with its
   integrator off (ilimit 0, the bam_ws 9de804493 rule), so the gains it writes describe the controller that is graded.
5. Grade: performance gained on a moved hidden CAN 11 (truth in no file the routine may read: world.json is refused during the fit),
   handed values at the edge of a passing dynamics fit (x 0 / 1 / 3 of sysid/acceptance.json's tolerance, signed to mislead), scored by
   sim2real.metrics.actuator against the best admissible PD + feed-forward on a grid with the TRUE model's feed-forward:
   regret = cost / oracle - 1 <= 0.15 passes (bam_pid_tunning K6). Admissible is pidtuna's oracle rule (its CONTRACT amendments 1 and 3):
   inside the caller's damping band on the truth AND inside every analytic bound on the TRUE loop; the grid is pidtuna's oracle grid
   since amendment 3 (6c6c4a9): its coarse band around the closed form's bandwidth on the true model and loop, no relative gain range, so
   the pool tops out at the analytic ceiling on the true loop. Where no grid gains are, the pool is the as-found kp / kd under each
   feed-forward (what PID tuna keeps), and the tuned gains are held to the same rules. The ruler fails the board's own
   as-found controller (else it cannot grade a gain) and a deliberately bad corner. The ladder is written BEFORE the pass asserts (a
   FAIL is recorded, not lost) and carries the hashes of the wrapper and this file, so a hand-written ladder cannot stand in for the run.
6. The pendulum's one-click schedule holds it after the regression (or drops it by name where pidtuna cannot be imported); slow:
   calibrate() plays it, settings_ carries the gains, the fit still passes, pools never exceed the twin's workers.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import zlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))  # sysid (the seal on the hidden truth) lives at the checkout's root

SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
WRITE = os.environ.get("SIM2REAL_WRITE_LADDERS") == "1"
WORKERS = int(os.environ.get("SIM2REAL_WORKERS", "2"))  # WHY 2: the powered rig's cap; a cloud VM may raise it, every pool obeys it
TAU = 2.0 * math.pi

ROUTINE = "pid.pidtuna"
PICKED = {"j1": ("integrated_servo", "M2.dynamics.coulomb_viscous")}
GAINS = ("kp_nm_rad", "kd_nm_s_rad")   # the board's feedback gains: the settings (feed-forward is the fitted model's, in the proposal)
REQUIRES = {"armature_kg_m2", "frictionloss_nm"}
WRAPPER = REPO / "src" / "sim2real" / "calibration" / "pid_tune.py"

LADDER = REPO / "sysid" / "results" / "routine_ladders" / f"{ROUTINE}.json"
GENERATED_BY = "tests/test_pid_tune_routine.py"
LEVELS = ("0x", "1x", "3x")
SCALE = {"0x": 0.0, "1x": 1.0, "3x": 3.0}
REGRET_MAX = 0.15  # bam_pid_tunning K6: regret = cost(tuned) / cost(oracle) - 1
TOLERANCE = {"closed_loop_cost": {"kind": "rel_to_oracle",
                                  "value": "regret <= 0.15 against the best admissible PD + feed-forward controller on the hidden truth "
                                           "(cost = stop p90 / as found + tracking RMS / as found, held-out tapes); the level scales how "
                                           "far the handed fitted values sit from the truth, in units of the dynamics fit's acceptance "
                                           "tolerance (sysid/acceptance.json), not sensor noise"}}
ENTRY_KEYS = {"pass", "worst_error_over_tolerance", "regret", "gain", "admissible", "cost_tuned", "cost_oracle", "stop_p90_mrad"}
WORLD = REPO / "sysid" / "examples" / "pendulum_can11" / "world.json"
ACCEPTANCE = REPO / "sysid" / "acceptance.json"
MOVE = {"can11.armature_kg_m2": 1.08, "can11.frictionloss_nm": 0.93, "can11.damping_nm_s_rad": 1.15, "can11.gravity_nm": 0.98}
MISLEAD = {"can11.armature_kg_m2": +1, "can11.frictionloss_nm": -1, "can11.damping_nm_s_rad": +1, "can11.gravity_nm": +1,
           "can11.gravity_bottom_rad": +1, "can11.friction_stribeck_drop_nm": -1, "can11.friction_stribeck_speed_rad_s": +1}
SEED = 7
DWELL_MIN_S, SETTLE_S, RING_WINDOW_S = 0.25, 0.05, 0.25
RINGING_CAP_MRAD = 2.0
MAX_SATURATION = 0.02
REFUSED = {"admissible": False, "stop_p90_mrad": math.inf, "tracking_rms_mrad": math.inf, "ringing_mrad": math.inf, "saturation": 1.0}


def _calibration():
    """WHY imported per test and never importorskip: a missing back end must FAIL here, not skip."""
    import sim2real.calibration as module  # noqa: PLC0415

    return module


def _reg():
    from sim2real.cards import registry as reg  # noqa: PLC0415

    return reg


def _need_rack():
    if os.environ.get("SIM2REAL_REQUIRE_RACK") == "1":
        import bam_rack_twin  # noqa: F401, PLC0415
    else:
        pytest.importorskip("bam_rack_twin", reason="the CAN 11 pendulum runs in bam_rack_twin's venv")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pidtuna_importable() -> bool:
    from sim2real import paths  # noqa: PLC0415

    return importlib.util.find_spec("pidtuna") is not None or (paths.PIDTUNA / "src" / "pidtuna").is_dir()


# --- 1. the catalog ------------------------------------------------------------------------------------------------------------------------


def test_pid_tuna_is_a_tune_routine_that_configures_the_feedback_gains_and_identifies_nothing():
    reg = _reg()
    r = reg.routine(ROUTINE)
    assert r.kind == "tune", f"{ROUTINE} is still kind {r.kind!r}: the planner never schedules a 'use' routine"
    assert r.identifies == (), "a tune claims nothing against a truth"
    servo = [c for c in r.configures if c.card == "servo"]
    assert servo and set(GAINS) <= set(servo[0].settings), r.configures
    assert REQUIRES <= set(r.requires), "it tunes on the fitted plant: after the routines that find its inertia and friction"
    assert r.status == "implemented"
    homes = {h.path for h in r.code}
    assert "src/pidtuna/tune.py" in homes and "src/sim2real/calibration/pid_tune.py" in homes, homes
    assert f"routine_ladders/{ROUTINE}.json" in r.oracle_note, r.oracle_note
    # WHY > 0 (ruler owner, 2026-11-19): type_cards/tests/test_routines.py holds every routine's wall time positive; the SIM tier's
    # time is compute on the fitted twin, and "no robot time" is pinned by runs() being empty (below), not by a zero
    assert r.wall_time.value > 0 and "fitted twin" in r.wall_time.source, ("the SIM tier: compute on the fitted twin", r.wall_time)
    assert ROUTINE in {x.id for x in reg.routines_tuning("servo")}
    assert reg.routine("kinematics.ik_fine_tune").kind == "use", "only PID tuning is re-kinded"


def test_the_re_kind_is_a_recorded_decision_and_the_contract_says_so():
    decisions = sorted((REPO / "docs").glob("decision-pidtuna-tune-*.md"))
    assert decisions, "re-kinding an existing value needs its own decision (cards/CONTRACT.md: additive only)"
    text = decisions[-1].read_text(encoding="utf-8")
    assert ROUTINE in text and "tune" in text and "use" in text and "integrator" in text
    contract = (REPO / "src" / "sim2real" / "cards" / "CONTRACT.md").read_text(encoding="utf-8")
    assert "the IK fine-tune and PID tuning" not in contract, "CONTRACT.md still lists PID tuning among the `use` routines"
    assert any(ROUTINE in line and "tune" in line for line in contract.splitlines()), "a 'Since 2026-11-18' line names the re-kind"


def test_the_generated_projections_carry_the_new_kind():
    doc = json.loads((REPO / "src" / "sim2real" / "cards" / "domain_v3.json").read_text(encoding="utf-8"))
    row = next(r for r in doc["routines"] if r["id"] == ROUTINE)
    assert row["kind"] == "tune", row
    assert any(c["card"] == "servo" and set(GAINS) <= set(c["settings"]) for c in row["configures"]), row["configures"]
    table = json.loads((REPO / "sysid" / "results" / "calibration_routines.json").read_text(encoding="utf-8"))
    assert next(r for r in table["rows"] if r["routine"] == ROUTINE)["kind"] == "tune"


# --- 2. the planner ----------------------------------------------------------------------------------------------------------------------------


def test_every_integrated_servo_wants_pid_tuna_and_its_gains_read_as_proposed_by_it():
    cal = _calibration()
    assert cal.options("integrated_servo").setup == (ROUTINE,)
    sel = cal.select(PICKED)
    assert ROUTINE in sel.setup and ROUTINE not in sel.routines, "a tune joins the plan, never the cover"
    why = sel.why[ROUTINE]
    assert "setup" in why and "tune" in why and "closed-loop performance" in why, why
    assert "before it is fitted" not in why, "PID tuna tunes the fitted plant: it runs after the fit"
    assert {"j1.kp_nm_rad", "j1.kd_nm_s_rad"} <= set(sel.configures[ROUTINE]), sel.configures
    uncovered = {n: w for _i, n, w in sel.uncovered}
    for name in GAINS:
        assert name in uncovered, "still not identified: a tune picks gains, it recovers no hidden value"
        assert "config receipt" in uncovered[name] and ROUTINE in uncovered[name], (name, uncovered[name])


def test_the_plan_runs_pid_tuna_after_the_routines_that_find_what_it_tunes_on():
    cal = _calibration()
    plan = cal.plan(PICKED)
    assert ROUTINE in plan.ids, plan.summary()
    step = next(s for s in plan.steps if s.routine == ROUTINE)
    assert step.kind == "tune"
    providers = {s.routine for s in plan.steps if s.routine != ROUTINE and {"j1.armature_kg_m2", "j1.frictionloss_nm"} & set(s.identifies)}
    assert providers and providers <= set(step.after), (providers, step.after)
    assert all(plan.ids.index(p) < plan.ids.index(ROUTINE) for p in providers), plan.ids
    assert {"j1.kp_nm_rad", "j1.kd_nm_s_rad"} <= set(step.identifies), "a step lists what it writes (identifies + configures)"
    assert step.recovery is not None and step.recovery["level"] == "1x" and step.recovery["pass"] is True, step.recovery


def test_exclude_a_deployed_budget_and_dropped_requirements_drop_pid_tuna_by_name():
    cal = _calibration()
    excluded = cal.plan(PICKED, cal.CalibrationConfig(exclude=(ROUTINE,)))
    assert ROUTINE not in excluded.ids and any(r == ROUTINE and "excluded" in w for r, w in excluded.dropped), excluded.dropped
    deployed = cal.plan(PICKED, cal.CalibrationConfig(budget=cal.Budget(settings=("deployed",))))
    assert ROUTINE not in deployed.ids and any(r == ROUTINE and "bench" in w for r, w in deployed.dropped), deployed.dropped
    providers = tuple(s.routine for s in cal.plan(PICKED).steps if "j1.armature_kg_m2" in s.identifies)
    starved = cal.plan(PICKED, cal.CalibrationConfig(exclude=providers))
    if not any("j1.armature_kg_m2" in s.identifies for s in starved.steps):
        assert ROUTINE not in starved.ids, "a tune never runs on a plant nothing fitted"
        assert any(r == ROUTINE and "armature_kg_m2" in w for r, w in starved.dropped), starved.dropped


def test_the_committed_ladder_is_this_files_run_of_this_wrapper_grading_performance_gained():
    from sim2real.calibration import recovery as rec  # noqa: PLC0415

    assert LADDER.is_file(), f"{LADDER.relative_to(REPO)} is written by this file's grade (SIM2REAL_WRITE_LADDERS=1 SIM2REAL_SLOW=1 -k grade)"
    doc = json.loads(LADDER.read_text(encoding="utf-8"))
    assert (doc["schema"], doc["routine"], doc["generated_by"]) == (rec.LADDER_SCHEMA, ROUTINE, GENERATED_BY)
    assert doc["tolerance"] == TOLERANCE
    assert doc["provenance"]["pid_tune_sha256"] == _sha256(WRAPPER), "the ladder graded another pid_tune.py: run the grade again"
    assert doc["provenance"]["test_sha256"] == _sha256(Path(__file__)), "the ladder was written by another version of this ruler"
    assert set(doc["levels"]) == set(LEVELS)
    for level, e in doc["levels"].items():
        assert ENTRY_KEYS <= set(e), (level, sorted(ENTRY_KEYS - set(e)))
        assert e["worst_error_over_tolerance"] == pytest.approx(e["regret"] / REGRET_MAX), level
        assert e["pass"] == bool(e["admissible"] and e["regret"] <= REGRET_MAX), level
        assert e["gain"] == pytest.approx(2.0 / e["cost_tuned"]), "the as-found controller costs 2 by construction"
        assert e["regret"] == pytest.approx(e["cost_tuned"] / e["cost_oracle"] - 1.0), level
    assert doc["levels"]["0x"]["pass"] and doc["levels"]["1x"]["pass"], doc["levels"]
    rec.ladders.cache_clear()
    assert rec.recovery(ROUTINE, "1x")["pass"] is True
    assert rec.source(ROUTINE) == f"sysid/results/routine_ladders/{ROUTINE}.json"


# --- 4. the wrapper ------------------------------------------------------------------------------------------------------------------------


def test_the_wrapper_declares_a_tune_that_plays_no_robot_time():
    cal = _calibration()
    from sim2real.calibration.pid_tune import PidTune  # noqa: PLC0415

    assert cal.PidTune is PidTune
    routine = PidTune(instance="can11")
    d = cal.declaration(routine)
    assert (d.id, d.kind, d.identifies) == (ROUTINE, "tune", ())
    assert {f"can11.{s}" for s in GAINS} <= set(d.configures), d.configures
    assert {f"can11.{s}" for s in REQUIRES} <= set(d.requires) or REQUIRES <= set(d.requires), d.requires
    assert tuple(routine.runs({})) == (), "the SIM tier tunes on the fitted plant: no run on the robot"
    assert d.wall_time_s > 0.0 and d.operator_time_s == 0.0, "compute on the fitted twin (runs() is empty: no robot time), no hands"


def test_importing_the_wrapper_imports_no_pidtuna_and_pidtuna_imports_no_sim2real():
    code = "import sys, sim2real.calibration, sim2real.calibration.pid_tune; print('pidtuna' in sys.modules)"
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, cwd=str(REPO), env=dict(os.environ))
    assert run.returncode == 0, run.stderr[-2000:]
    words = run.stdout.split()
    assert words and words[-1] == "False", "sim2real imports pidtuna only when the routine runs"
    from sim2real import paths  # noqa: PLC0415

    src = paths.PIDTUNA / "src"
    if not src.is_dir():
        pytest.skip(f"pidtuna is not at {src} (set SIM2REAL_PIDTUNA): the one-way import is checked where it is")
    pattern = re.compile(r"^\s*(?:from|import)\s+sim2real\b", re.M)
    offenders = [str(p) for p in src.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"PID tuna stays its own tool and never imports sim2real: {offenders}"


# --- 3. the seam: a toy rig through RobotTwin.calibrate(config=...) ------------------------------------------------------------------------

TOY_TRUTH = {"toy.gain": 2.5, "toy.offset": -0.4}
TOY_NOMINAL = {"toy.gain": 2.0, "toy.offset": 0.0, "toy.kp_nm_rad": 30.0, "toy.kd_nm_s_rad": 0.4}
TOY_SETTINGS = {"toy.kp_nm_rad": 50.0, "toy.kd_nm_s_rad": 0.5}
TOY_PROPOSAL = {"board": {"kp": 50.0 * TAU, "kd": 0.5 * TAU, "ki": 0.0, "ilimit": 0.0}}


def _toy_inputs(run_id: str) -> np.ndarray:
    return np.random.default_rng(zlib.crc32(run_id.encode())).uniform(-1.0, 1.0, 300)


def _toy_description():
    from robot_msgs.space import Basis, Value  # noqa: PLC0415

    from sim2real.twin import Description, Instance  # noqa: PLC0415

    params = {k.split(".", 1)[1]: Value(v, "1", basis=Basis.ASSUMED, source="the toy's datasheet") for k, v in TOY_NOMINAL.items()}
    return Description("toy", "Toy rig", model=None, instances=(
        Instance("cell", "Cell", None, None, structural="deployment"),
        Instance("toy", "Toy servo", "integrated_servo", "cell", params, {k: False for k in params})), source="tests")


def _toy_world() -> dict:
    from sysid import world as hidden  # noqa: PLC0415

    if hidden.is_sealed():
        raise hidden.SealedWorld("sealed")
    return {"truth": dict(TOY_TRUTH), "seed": 3}


@dataclass
class _ToyOffset:
    id: str = "servo.backlash_reversal_held"
    identifies: tuple = ("toy.offset",)
    requires: tuple = ()

    def runs(self, values):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(f"zero{k}", "train", None) for k in range(3)]

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        y = float(np.mean(np.concatenate([m["y"] - values["toy.gain"] * m["u"] for m in measured.values()])))
        return {"toy.offset": seam.Estimate(y, (y - 0.01, y + 0.01), "mean residual")}


@dataclass
class _ToyGain:
    id: str = "servo.breakaway_two_sided"
    identifies: tuple = ("toy.gain",)
    requires: tuple = ("toy.offset",)

    def runs(self, values):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(f"gain{k}", "train", None) for k in range(4)]

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        u = np.concatenate([m["u"] for m in measured.values()])
        y = np.concatenate([m["y"] for m in measured.values()]) - values["toy.offset"]
        gain = float(u @ y / (u @ u))
        return {"toy.gain": seam.Estimate(gain, (gain - 0.01, gain + 0.01), "least squares through the found offset")}


class _Found(dict):
    """A tune's result: its settings, plus the proposal it was made from."""
    proposal: dict = {}


@dataclass
class _ToyTune:
    """A stand-in tune on the toy (a registered id, as the seam requires): it proposes the two gains and claims nothing."""
    id: str = ROUTINE
    kind: str = "tune"
    identifies: tuple = ()
    configures: tuple = tuple(TOY_SETTINGS)
    requires: tuple = ("toy.gain",)
    uses: tuple = ()
    refines: tuple = ()

    def runs(self, values):
        return ()

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        found = _Found({key: seam.Estimate(value, None, "a stand-in tune") for key, value in TOY_SETTINGS.items()})
        found.proposal = dict(TOY_PROPOSAL)
        return found


@dataclass
class _ToyRuler:
    """A gauge after the tune (the measure stage): it records the values and the settings it is handed."""
    id: str = "servo.camera_dwell_stop_ruler"
    kind: str = "measure"
    identifies: tuple = ()
    requires: tuple = ()
    uses: tuple = ()
    refines: tuple = ()
    saw: list = field(default_factory=list)

    def runs(self, values):
        return ()

    def fit(self, measured, values, twin):
        self.saw.append((dict(values), dict(getattr(twin, "settings", {}) or {})))
        return {}


class _ToyRig:
    name = "toy"

    def __init__(self):
        self.gain, self.offset = _ToyGain(), _ToyOffset()

    def parameters(self):
        from sim2real import rig as seam  # noqa: PLC0415

        return (seam.Parameter("toy.gain", "1", ("rel", 0.05), "proposed", self.gain.id),
                seam.Parameter("toy.offset", "1", ("abs", 0.05), "proposed", self.offset.id))

    def noise(self):
        from sim2real import rig as seam  # noqa: PLC0415

        return seam.NoiseModel(torque_noise_nm=0.02, sources={"torque_noise_nm": "the toy's datasheet"})

    def routines(self):
        return (self.offset, self.gain)

    def held_out(self, values=None):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(f"held{k}", "held_out", None) for k in range(2)]

    def measure(self, runs, values, noise, stream, *, workers=1):
        sigma = noise.effective()["torque_noise_nm"]
        out = {}
        for run in runs:
            u = _toy_inputs(run.id)
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
    from sim2real import rig as seam  # noqa: PLC0415
    from sim2real import twin as twin_module  # noqa: PLC0415

    rig = _ToyRig()
    monkeypatch.setattr(twin_module, "_runner", lambda description, workers: seam.RigRunner(description, rig, workers=1, world=_toy_world))
    return twin_module.RobotTwin(_toy_description().instances, name="toy")


def test_a_rig_runner_records_a_tunes_settings_in_their_own_channel_and_never_fits_or_replays_with_them(toy_twin):
    cal = _calibration()
    tune, ruler = _ToyTune(), _ToyRuler()
    fitted = toy_twin.calibrate(on="sim", config=cal.CalibrationConfig(custom=(tune, ruler)))
    assert fitted.plan_.ids == ("servo.backlash_reversal_held", "servo.breakaway_two_sided", ROUTINE, "servo.camera_dwell_stop_ruler"), \
        "configure -> fit -> tune -> measure"
    step = next(s for s in fitted.plan_.steps if s.routine == ROUTINE)
    assert step.kind == "tune" and step.source == "custom" and set(TOY_SETTINGS) <= set(step.identifies)
    record = fitted.record_.to_dict()
    row = next(r for r in record["routines"] if r["routine"] == ROUTINE)
    assert row["identifies"] == [] and row["found"] == TOY_SETTINGS, row
    assert not [p for p in record["parameters"] if p.get("routine") == ROUTINE], "a setting never owns a parameter row"
    assert fitted.settings_ == TOY_SETTINGS
    assert fitted.proposals_ == {ROUTINE: TOY_PROPOSAL}, "the board proposal PID tuna made is kept beside the settings"
    values_seen, settings_seen = ruler.saw[-1]
    assert values_seen["toy.kp_nm_rad"] == TOY_NOMINAL["toy.kp_nm_rad"], "a later routine fits at the gains its runs ran at"
    assert settings_seen == TOY_SETTINGS, "and sees the proposed gains in their own channel"
    assert fitted.runner.state["values"]["toy.kp_nm_rad"] == TOY_NOMINAL["toy.kp_nm_rad"], "the twin replays at the gains runs ran at"
    assert fitted.values_["toy.kp_nm_rad"].value == TOY_NOMINAL["toy.kp_nm_rad"], "a setting is not a fitted model value"
    assert fitted.values_["toy.gain"].value == pytest.approx(TOY_TRUTH["toy.gain"], rel=0.05), "the tune moved no fit"


def test_a_configure_routines_outputs_still_enter_the_values_later_routines_run_at(toy_twin):
    """Only a tune merely proposes. A configure step (an exposure lock, a counts-per-metre) sets the device, so what follows runs at it."""
    cal = _calibration()
    from sim2real import rig as seam  # noqa: PLC0415

    @dataclass
    class _Lock:
        id: str = "camera.exposure_for_aruco"
        kind: str = "configure"
        identifies: tuple = ()
        configures: tuple = ("toy.kd_nm_s_rad",)
        requires: tuple = ()
        uses: tuple = ()
        refines: tuple = ()

        def runs(self, values):
            return ()

        def fit(self, measured, values, twin):
            return {"toy.kd_nm_s_rad": seam.Estimate(0.9, None, "set on the device")}

    ruler = _ToyRuler()
    toy_twin.calibrate(on="sim", config=cal.CalibrationConfig(custom=(_Lock(), ruler)))
    assert ruler.saw[-1][0]["toy.kd_nm_s_rad"] == 0.9


# --- 3 and 6. the CAN 11 pendulum (bam_rack_twin's venv) ----------------------------------------------------------------------------------


class _Stop(Exception):
    pass


@pytest.fixture(scope="module")
def pendulum():
    _need_rack()
    import sim2real  # noqa: PLC0415

    return sim2real.examples.pendulum_can11(workers=WORKERS)


def test_the_tracer_runner_takes_a_tunes_settings_and_never_fits_with_them(pendulum, monkeypatch):
    from sim2real import rig as seam  # noqa: PLC0415

    seen = {}

    class World:
        truth, noise, seed = {}, {}, 0

        def __init__(self, d, *, workers):
            pass

        def measure(self, plan):
            return SimpleNamespace(train={}, held_out={}, repeat={})

    class Module:
        RealWorld = World

        @staticmethod
        def plan(d):
            return object()

    class Tune:
        id, kind, identifies = ROUTINE, "tune", ()
        configures = ("can11.kp_nm_rad", "can11.kd_nm_s_rad")

        def runs(self, values):
            return ()

        def fit(self, measured, values, twin):
            return {"can11.kp_nm_rad": seam.Estimate(40.0, None, "stub"), "can11.kd_nm_s_rad": seam.Estimate(0.8, None, "stub")}

    class Later:
        id, kind, identifies = "servo.camera_dwell_stop_ruler", "measure", ()

        def runs(self, values):
            return ()

        def fit(self, measured, values, twin):
            seen["values"], seen["settings"] = dict(values), dict(getattr(twin, "settings", {}) or {})
            raise _Stop

    monkeypatch.setattr(pendulum.runner, "pipeline", lambda: Module)
    monkeypatch.setattr(pendulum.runner, "sysid_description", lambda: object())
    with pytest.raises(_Stop):
        pendulum.runner.calibrate(routines=[Tune(), Later()])
    assert seen["values"], "the later routine ran with the description's priors"
    assert seen["values"].get("can11.kp_nm_rad") != 40.0 and seen["values"].get("can11.kd_nm_s_rad") != 0.8, seen["values"]
    assert seen["settings"] == {"can11.kp_nm_rad": 40.0, "can11.kd_nm_s_rad": 0.8}


def test_the_pendulums_one_click_schedule_tunes_pid_after_the_dynamics_fit(pendulum):
    cal = _calibration()
    schedule = cal.plan(pendulum)
    if not _pidtuna_importable():
        assert ROUTINE not in schedule.ids and any(r == ROUTINE and "pidtuna" in w for r, w in schedule.dropped), schedule.dropped
        pytest.skip("pidtuna is not importable here: the schedule drops it by name (checked); the rest needs it")
    assert ROUTINE in schedule.ids, schedule.summary()
    step = next(s for s in schedule.steps if s.routine == ROUTINE)
    assert step.kind == "tune" and "servo.dynamics_regression" in step.after, step
    assert schedule.ids.index(ROUTINE) > schedule.ids.index("servo.dynamics_regression")
    assert step.source == "rig" and callable(getattr(step.routine_object, "fit", None)), "a step that can run, not a catalog stand-in"
    assert step.wall_time_s > 0.0 and tuple(step.routine_object.runs({})) == (), "tunes on the fitted twin: compute time, no robot run"
    assert {"can11.kp_nm_rad", "can11.kd_nm_s_rad"} <= set(step.identifies)
    without = cal.plan(pendulum, cal.CalibrationConfig(exclude=(ROUTINE,)))
    assert ROUTINE not in without.ids and any(r == ROUTINE and "excluded" in w for r, w in without.dropped)


# --- 5. the grade (slow, cloud VM) ------------------------------------------------------------------------------------------------------------


def _pidtuna():
    try:
        import pidtuna  # noqa: F401, PLC0415
    except ModuleNotFoundError:
        from sim2real import paths  # noqa: PLC0415

        sys.path.insert(0, str(paths.PIDTUNA / "src"))
    from pidtuna import analytic, gains, oracle, tapes, types  # noqa: PLC0415
    from pidtuna.plants import servo_sim  # noqa: PLC0415

    return SimpleNamespace(tapes=tapes, types=types, servo_sim=servo_sim, gains=gains, oracle=oracle, analytic=analytic)


def _truth_values() -> dict[str, float]:
    world = json.loads(WORLD.read_text(encoding="utf-8"))["truth"]
    return {k: float(v) * MOVE.get(k, 1.0) for k, v in world.items()}


def _handed(level: str) -> dict[str, float]:
    tolerance = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))["examples"]["pendulum_can11"]["parameters"]
    out = {}
    for key, value in _truth_values().items():
        kind, size = tolerance[key]
        step = SCALE[level] * MISLEAD.get(key, 0) * float(size)
        out[key] = value * (1.0 + step) if kind == "rel" else value + step
    return out


def _servo(pt):
    """CAN 11 as the board runs it today (the record's kp 200, kd 4 N.m/rev, ki 16000, ilimit 0.5) and the rack's envelope."""
    t = pt.types
    return t.Servo("can11", t.Gains.from_moteus(200.0, 4.0, 16000.0, 0.5),
                   t.Envelope(travel_rad=0.3, max_speed_rad_s=2.0, max_torque_nm=2.85, origin_rad=-0.35),
                   torque_limit_nm=2.854, command_rate_hz=100.0, can_id=11, gear_ratio=10.0)


def _gravity(values) -> tuple[float, float]:
    g, bottom = values["can11.gravity_nm"], values["can11.gravity_bottom_rad"]
    return g * math.cos(bottom), -g * math.sin(bottom)


def _truth(pt, values):
    g_sin, g_cos = _gravity(values)
    static = values["can11.frictionloss_nm"]
    noise = float(json.loads(WORLD.read_text(encoding="utf-8"))["noise"]["speed_rad_s"])
    return pt.servo_sim.Truth(inertia_kg_m2=values["can11.armature_kg_m2"], viscous_nm_s_rad=values["can11.damping_nm_s_rad"],
                              coulomb_nm=static - values["can11.friction_stribeck_drop_nm"], static_nm=static,
                              stribeck_speed_rad_s=values["can11.friction_stribeck_speed_rad_s"], gravity_sin_nm=g_sin, gravity_cos_nm=g_cos,
                              torque_bandwidth_hz=200.0, velocity_noise_rad_s=noise)


def _model(pt, values):
    g_sin, g_cos = _gravity(values)
    return pt.types.PlantModel(values["can11.armature_kg_m2"], values["can11.damping_nm_s_rad"],
                               values["can11.frictionloss_nm"] - values["can11.friction_stribeck_drop_nm"], g_sin, g_cos)


def _workload(pt, servo, model) -> list:
    return [pt.tapes.within_torque(tape, servo, model, fraction=0.8) for seed in (2, 3) for tape in pt.tapes.evaluation(servo, seed=seed)]


def _score(traces, cap) -> dict:
    from sim2real.metrics import actuator  # noqa: PLC0415

    stops, errors, ringing, saturated, rows = [], [], [0.0], 0, 0
    for trace in traces:
        if not trace.complete:
            return dict(REFUSED)
        w = trace.window()
        t = w.t - w.t[0]
        e = w.q - w.q_target
        held = actuator.stops(t, w.q, w.q_target, w.qd_target, dwell_min_s=DWELL_MIN_S, settle_window_s=SETTLE_S)
        stops += [s for s, _start, _end in held]
        for _s, _start, end in held:
            inside = (t >= end - RING_WINDOW_S) & (t <= end)
            if int(inside.sum()) >= 3:
                slope, offset = np.polyfit(t[inside], e[inside], 1)
                ringing.append(1e3 * float(np.std(e[inside] - (slope * t[inside] + offset))))
        errors.append(e)
        saturated += int(np.sum(np.abs(w.tau_nm) >= 0.99 * cap))
        rows += len(t)
    if not stops:
        return dict(REFUSED)
    rms = 1e3 * float(np.sqrt(np.mean(np.concatenate(errors) ** 2)))
    p90 = float(actuator.stop_summary(stops)["value"])
    ring, saturation = max(ringing), saturated / max(rows, 1)
    return {"admissible": bool(ring <= RINGING_CAP_MRAD and saturation <= MAX_SATURATION), "stop_p90_mrad": p90, "tracking_rms_mrad": rms,
            "ringing_mrad": ring, "saturation": saturation}


def _inside(servo, controller) -> bool:
    (kp_low, kp_high), (kd_low, kd_high) = servo.gain_bounds()
    g, slack = controller.gains, 1e-9
    return kp_low * (1 - slack) <= g.kp <= kp_high * (1 + slack) and kd_low * (1 - slack) <= g.kd <= kd_high * (1 + slack)


def _play(pt, servo, truth, controllers, workload) -> list[dict]:
    playable = [c for c in controllers if _inside(servo, c)]
    sim = pt.servo_sim.ServoSim(servo, truth, seed=SEED, workers=WORKERS)
    traces = sim.run_many([(tape, c) for c in playable for tape in workload]) if playable else []
    cap = min(servo.envelope.max_torque_nm, servo.torque_limit_nm)
    n = len(workload)
    scored = {id(c): _score(traces[k * n:(k + 1) * n], cap) for k, c in enumerate(playable)}
    return [scored.get(id(c), dict(REFUSED)) for c in controllers]


def _cost(score, found) -> float:
    return score["stop_p90_mrad"] / found["stop_p90_mrad"] + score["tracking_rms_mrad"] / found["tracking_rms_mrad"]


@pytest.fixture(scope="module")
def bench():
    if not SLOW:
        pytest.skip("SIM2REAL_SLOW=1: the grade plays ~1200 tapes on pidtuna's ServoSim (cloud VM only)")
    pt = _pidtuna()
    servo = _servo(pt)
    values = _truth_values()
    truth, model = _truth(pt, values), _model(pt, values)
    workload = _workload(pt, servo, model)
    t = pt.types
    feedforwards = (t.Feedforward(), model.feedforward(0.5), model.feedforward(1.0))
    plant = pt.servo_sim.ServoSim(servo, truth, seed=SEED, workers=WORKERS)
    band = _band(pt)
    # WHY pidtuna's oracle grid (its CONTRACT amendment 3, v2.3; pidtuna 6c6c4a9): no relative gain range holds the oracle. The levels span
    # oracle.COARSE_BAND (1/6 to 3x) around the closed form's bandwidth on the TRUE model and loop (oracle.closed_form_ideal), COARSE_STEP
    # apart, at oracle.COARSE_ZETAS, each a gains.guarded point; a candidate that breaks an analytic bound on the TRUE loop (_obeys_bounds)
    # is never played, so the pool tops out at the analytic ceiling there. WHY the levels are not clipped to that ceiling: pidtuna tried it,
    # and the levels thinned until the lever's narrow admissible window fell between three of them (6c6c4a9)
    true_model = pt.oracle.true_model(plant)
    closed, _info = pt.oracle.closed_form_ideal(plant, servo, _objective(pt))
    floor, ceiling = pt.gains.wn_floor(true_model, servo), pt.gains.wn_ceiling(true_model, servo)
    center = min(max(pt.gains.bandwidth_of(closed, true_model)[0], floor), ceiling)
    low, high = max(floor, center * pt.oracle.COARSE_BAND[0]), min(ceiling, center * pt.oracle.COARSE_BAND[1])
    count = max(1, int(math.floor(math.log(high / low) / math.log(pt.oracle.COARSE_STEP))) + 1) if high > low else 1
    levels = list(np.geomspace(low, high, count)) if count > 1 else [center]
    points = list(dict.fromkeys(pt.gains.guarded(true_model, servo, wn=wn, zeta=zeta)[0] for wn in levels for zeta in pt.oracle.COARSE_ZETAS))
    kept_points = [g for g in points if _obeys_bounds(pt, plant, servo, g)]
    grid = [t.Controller(g, ff, label=f"oracle kp {g.kp:.4g} kd {g.kd:.4g} ff {k}") for g in kept_points for k, ff in enumerate(feedforwards)]
    print(f"{ROUTINE} oracle grid: {len(points)} points (wn {low:.3g}-{high:.3g} rad/s about the closed form's {center:.3g}, zetas "
          f"{pt.oracle.COARSE_ZETAS}); {len(kept_points)} inside every analytic bound on the true loop", flush=True)
    # WHY the band (PID Tuna's owner, 2026-11-20, on pidtuna 85495d4 "Never deliver outside the damping band"; pidtuna docs/CONTRACT.md
    # amendment 1: "ideal" means ideal under the objective and rules the caller set, evaluated on the truth): the oracle is the best
    # controller inside every analytic bound on the true loop AND inside the caller's damping band, the damping read on the TRUE plant the
    # way pidtuna's own oracle reads it (oracle.true_model: true J and b, gravity linearised at the origin as a spring; gains.bandwidth_of).
    # Grading against grid gains the caller's band forbids graded PID tuna against controllers it is told never to deliver.
    zetas = [pt.gains.bandwidth_of(c.gains, pt.oracle.true_model(plant))[1] for c in grid]
    in_band = [k for k, zeta in enumerate(zetas) if band[0] - 1e-6 <= zeta <= band[1] + 1e-6]  # pidtuna oracle.search_ideal's tolerance
    # WHY the as-found fallback (the same ruling): where no gains inside the bounds reach the band, pidtuna keeps the as-found kp and kd
    # (its integrator off, as PidTune hands it the board) and says so; the pool is then those gains under each feed-forward, so the
    # honest grade is how much the tune gains with nothing admissible to improve in kp / kd, not red
    kept = replace(servo.gains, ilimit=0.0)
    fallback = [] if in_band else [t.Controller(kept, ff, label=f"as found kp / kd, integrator off, ff {k}")
                                   for k, ff in enumerate(feedforwards)]
    found, *scores = _play(pt, servo, truth, [servo.as_found, *grid, *fallback], workload)
    assert math.isfinite(found["stop_p90_mrad"]) and found["stop_p90_mrad"] > 0 and found["tracking_rms_mrad"] > 0, found
    pool = [grid[k] for k in in_band] if in_band else fallback
    pool_scores = [scores[k] for k in in_band] if in_band else scores[len(grid):]
    print(f"{ROUTINE} oracle pool: {len(in_band)} of {len(grid)} grid controllers inside the band {band} on the truth (grid zeta "
          f"{min(zetas):.3g}-{max(zetas):.3g}); pool = {'those' if in_band else 'the as-found kp / kd under each feed-forward'}",
          flush=True)
    assert any(s["admissible"] for s in pool_scores), "the ruler admits no PD + feed-forward controller in its pool: the ruler is broken"
    return SimpleNamespace(pt=pt, servo=servo, truth=truth, model=model, workload=workload, found=found, grid=grid, scores=scores,
                           plant=plant, band=band, in_band=in_band, pool=pool, pool_scores=pool_scores)


def _objective(pt):
    """The objective the routine hands PID tuna (PidTune's goal; None = pidtuna's default Objective)."""
    from sim2real.calibration.pid_tune import PidTune  # noqa: PLC0415

    goal = PidTune(instance="can11").goal
    return goal if goal is not None else pt.types.Objective()


def _band(pt) -> tuple[float, float]:
    """The caller's damping band: the objective the routine hands PID tuna."""
    return tuple(_objective(pt).damping_band)


def _obeys_bounds(pt, plant, servo, gains) -> bool:
    """Every analytic bound on the TRUE loop but the damping (the band holds that): pidtuna oracle.search_ideal's broken_rules, at the
    objective's gain margin and band floor (analytic.limits on oracle.true_model / true_loop)."""
    objective = _objective(pt)
    model, loop = pt.oracle.true_model(plant), pt.oracle.true_loop(plant, servo)
    if loop is None:
        return True
    rules = pt.analytic.limits(model, loop, gains, margin=objective.gain_margin, min_damping=objective.damping_band[0])
    return all(ok for name, ok in rules.items() if name != "damping")


def _obeys_band(bench, controller) -> bool:
    """The tuned gains under the oracle's rule: inside the caller's band on the truth and every analytic bound on the true loop, or the
    as-found kp and kd (pidtuna's tune exempts only those: keeping them changes nothing)."""
    g, board = controller.gains, bench.servo.gains
    if math.isclose(g.kp, board.kp, rel_tol=1e-9) and math.isclose(g.kd, board.kd, rel_tol=1e-9):
        return True
    zeta = bench.pt.gains.bandwidth_of(g, bench.pt.oracle.true_model(bench.plant))[1]
    return bench.band[0] - 1e-6 <= zeta <= bench.band[1] + 1e-6 and _obeys_bounds(bench.pt, bench.plant, bench.servo, g)


def _grade(bench, controller) -> dict:
    tuned = _play(bench.pt, bench.servo, bench.truth, [controller], bench.workload)[0]
    # WHY the band on the tuned gains too: the pool and the graded controller obey one rule, so a tune outside the caller's band (which
    # pidtuna's contract forbids it to deliver) cannot pass by beating a pool it was not allowed to join
    admissible = bool(tuned["admissible"] and _obeys_band(bench, controller))
    pool = [_cost(s, bench.found) for s in bench.pool_scores if s["admissible"]] + ([_cost(tuned, bench.found)] if admissible else [])
    oracle, cost = min(pool), _cost(tuned, bench.found)
    regret = cost / oracle - 1.0
    return {"pass": bool(admissible and regret <= REGRET_MAX), "worst_error_over_tolerance": float(regret / REGRET_MAX),
            "regret": float(regret), "gain": float(2.0 / cost), "admissible": admissible, "cost_tuned": float(cost),
            "cost_oracle": float(oracle), "stop_p90_mrad": float(tuned["stop_p90_mrad"]),
            "oracle_pool": f"{len(bench.in_band)} grid controllers inside the band {bench.band}" if bench.in_band else
                           f"the as-found kp / kd under each feed-forward (no grid gains inside the bounds reach the band {bench.band})"}


def _pidtuna_head() -> str:
    from sim2real import paths  # noqa: PLC0415

    run = subprocess.run(["git", "-C", str(paths.PIDTUNA), "rev-parse", "HEAD"], capture_output=True, text=True)
    return run.stdout.strip() or "unknown"


def _ladder(levels: dict[str, dict]) -> None:
    """Write (SIM2REAL_WRITE_LADDERS=1) or compare the committed ladder. Called BEFORE any pass assertion, so a FAIL is recorded too."""
    from sim2real.calibration import recovery as rec  # noqa: PLC0415

    doc = {"schema": rec.LADDER_SCHEMA, "routine": ROUTINE, "generated_by": GENERATED_BY, "tolerance": TOLERANCE, "levels": levels,
           "provenance": {"pid_tune_sha256": _sha256(WRAPPER), "test_sha256": _sha256(Path(__file__)), "pidtuna_head": _pidtuna_head()}}
    if WRITE:
        LADDER.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    committed = json.loads(LADDER.read_text(encoding="utf-8"))
    assert committed["schema"] == doc["schema"] and committed["routine"] == ROUTINE and committed["tolerance"] == TOLERANCE
    for level, entry in levels.items():
        got = committed["levels"][level]
        assert got["pass"] == entry["pass"], (level, got, entry)
        assert got["worst_error_over_tolerance"] == pytest.approx(entry["worst_error_over_tolerance"], rel=1e-3, abs=1e-3), level


@pytest.mark.skipif(not SLOW, reason="SIM2REAL_SLOW=1: three PID tuna tunes and their grades on the hidden CAN 11")
def test_grade_pid_tuna_on_a_hidden_can11_against_the_oracle(bench, monkeypatch):
    from sysid import world as hidden  # noqa: PLC0415

    from sim2real.calibration.pid_tune import PidTune  # noqa: PLC0415

    # WHY by module name (ruler owner, 2026-11-19): pidtuna v2's package exports the tune FUNCTION as pidtuna.tune, so the attribute
    # path gets the function, not the module whose tune() the watch below replaces (the bench fixture put pidtuna on the path)
    backend = importlib.import_module("pidtuna.tune")

    delivered, opened, held = [], [], []
    original_tune, original_pool = backend.tune, bench.pt.servo_sim._pool

    def watched_tune(*args, **kwargs):
        held.append(kwargs.get("feedforward"))  # the feed-forward PID tuna held fixed: the ruler grades with it, never the wrapper's word
        result = original_tune(*args, **kwargs)
        delivered.append(result)
        return result

    def watched_pool(workers):
        opened.append(workers)
        return original_pool(workers)

    real_open, real_read = builtins.open, Path.read_text

    def no_world(name) -> None:
        if Path(str(name)).name == "world.json":
            raise PermissionError(f"the tune read {name}: the hidden truth is never the routine's to open")

    def guarded_open(file, *args, **kwargs):
        no_world(file)
        return real_open(file, *args, **kwargs)

    def guarded_read(self, *args, **kwargs):
        no_world(self)
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(backend, "tune", watched_tune)
    monkeypatch.setattr(bench.pt.servo_sim, "_pool", watched_pool)
    declared = set(PidTune(instance="can11").configures)
    levels = {}
    for level in LEVELS:
        handed = _handed(level)
        ran = len(delivered)
        with hidden.sealed(), monkeypatch.context() as guard:  # sealed, and world.json refused, while the routine runs
            guard.setattr(builtins, "open", guarded_open)
            guard.setattr(Path, "read_text", guarded_read)
            found = PidTune(instance="can11", servo=bench.servo).fit({}, dict(handed), SimpleNamespace(workers=WORKERS))
        assert len(delivered) == ran + 1, "the backend is PID tuna: pidtuna.tune.tune ran once per fit"
        # WHY rebuilt here (ruler owner, 2026-11-19): pidtuna v2 returns Tuning (gains per joint), not v1's TuneResult.tuned; the graded
        # controller is the gains PID tuna delivered plus the feed-forward it was handed, both read off the backend call itself
        (gains,) = delivered[-1].gains.values()
        assert isinstance(held[-1], bench.pt.types.Feedforward), ("the tune held a fitted feed-forward fixed", held[-1])
        tuned = bench.pt.types.Controller(gains, held[-1], label="tuned")
        assert set(found) <= declared, sorted(set(found) - declared)
        assert tuned.gains.ilimit == 0.0, "PD + feed-forward only: PID tuna was handed the board with its integrator off"
        assert found["can11.kp_nm_rad"].value == pytest.approx(tuned.gains.kp, rel=1e-9), "the gains written are the gains PID tuna delivered"
        assert found["can11.kd_nm_s_rad"].value == pytest.approx(tuned.gains.kd, rel=1e-9)
        assert isinstance(getattr(found, "proposal", None), dict), "the board proposal rides with the settings"
        levels[level] = _grade(bench, tuned)
        print(f"{ROUTINE} at {level}: {levels[level]}", flush=True)
    _ladder(levels)  # WHY first: a FAIL lands in the committed ladder, where the planner's recovery reports it truthfully
    assert max(opened, default=0) <= WORKERS, f"pidtuna pools opened with {sorted(set(opened))} workers, cap {WORKERS}"
    assert levels["0x"]["pass"] and levels["1x"]["pass"], levels
    for level in ("0x", "1x"):
        assert levels[level]["gain"] >= 1.0 - 1e-9, (level, "the tune left the joint worse than the board runs it now", levels[level])


@pytest.mark.skipif(not SLOW, reason="SIM2REAL_SLOW=1: the ruler's own mutation test on the hidden CAN 11")
def test_the_grade_fails_the_boards_own_controller_and_a_bad_corner_and_passes_the_grids_best(bench):
    t = bench.pt.types
    as_found = _grade(bench, bench.servo.as_found)
    print(f"{ROUTINE} mutation, the board's as-found controller: {as_found}", flush=True)
    assert not as_found["pass"], \
        "the board's as-found controller passes: the ruler cannot tell a tune that does nothing from one that gains"
    # WHY on the regret too (the band ruling, 2026-11-20): as found is exempt from the band, so only the cost can fail it - it must
    assert as_found["regret"] > REGRET_MAX, as_found
    bad = t.Controller(t.Gains(kp=2.0 * bench.servo.gains.kp, kd=0.25 * bench.servo.gains.kd), t.Feedforward(),
                       label="kp x2, kd x0.25, no feed-forward")
    corner = _grade(bench, bad)
    print(f"{ROUTINE} mutation, the bad corner: {corner}", flush=True)
    assert not corner["pass"], "a ruler that passes the least damped, uncompensated corner cannot fail"
    # WHY on the regret too: the band alone refuses this corner; the cost must refuse it as well, or the metric could not fail anything
    assert corner["regret"] > REGRET_MAX, corner
    # the pool's best (the grid's best inside the band; where none is, the as-found kp / kd under its best feed-forward) passes, regret 0
    costs = [(_cost(s, bench.found), k) for k, s in enumerate(bench.pool_scores) if s["admissible"]]
    entry = _grade(bench, bench.pool[min(costs)[1]])
    assert entry["pass"] and entry["regret"] == pytest.approx(0.0, abs=1e-9), entry


@pytest.mark.skipif(not SLOW, reason="SIM2REAL_SLOW=1: the CAN 11 oracle's calibration takes minutes (cloud VM only)")
def test_pendulum_calibrate_plays_pid_tuna_and_keeps_the_fit(pendulum, monkeypatch):
    cal = _calibration()
    pt = _pidtuna()
    opened = []
    original = pt.servo_sim._pool

    def watched_pool(workers):
        opened.append(workers)
        return original(workers)

    monkeypatch.setattr(pt.servo_sim, "_pool", watched_pool)
    fitted = pendulum.calibrate(on="sim")
    assert ROUTINE in fitted.plan_.ids and fitted.plan_.ids == cal.plan(pendulum).ids
    assert fitted.calibration_.passed, fitted.calibration_.summary()
    settings = fitted.settings_
    assert {f"can11.{s}" for s in GAINS} <= set(settings), settings
    kp, kd = settings["can11.kp_nm_rad"], settings["can11.kd_nm_s_rad"]
    assert 0.0 < kp < math.inf and 0.0 < kd < math.inf, (kp, kd)  # the analytic bounds on the true loop are graded in the bench test
    assert isinstance(fitted.proposals_.get(ROUTINE), dict), "the board proposal PID tuna made is kept for review"
    row = next(r for r in fitted.record_.to_dict()["routines"] if r["routine"] == ROUTINE)
    assert row["identifies"] == [] and {k: row["found"][k] for k in settings} == pytest.approx(settings)
    assert max(opened, default=0) <= WORKERS, f"pidtuna pools opened with {sorted(set(opened))} workers, cap {WORKERS}"
