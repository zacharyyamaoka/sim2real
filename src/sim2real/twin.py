"""The front door: a RobotTwin, a digital twin for an electromechanical device, built from typed instances, then .simulate(),
.calibrate() and .eval() (Zach, 2026-11-11).

    import sim2real
    twin = sim2real.RobotTwin.from_robot_description(rd) # a robot's description in (rd = bam_rack_twin.description.station_description(11))
    twin = sim2real.examples.pendulum_can11()            # the same twin, the hand-built fixture: typed instances with robot_msgs Values
    twin.simulate()                                      # MuJoCo, headless: the model swung from off its bottom
    fitted = twin.calibrate(on="sim", truth="sealed")    # the type's routine schedule on a hidden truth; a NEW, fitted twin
    fitted.evaluate().summary()                          # held-out runs only: error / floor, the gates (eval() is its alias)
    fitted.parameters                                    # {instance: {name: Value}}: the calibrated values replace the priors
    twin.calibrate(on="real", transport=sim2real.real.RackTransport(out))   # the same schedule on the rack (sim2real.real; a dry run by default)

Zach: "So you start with a robotDescription. Honestly it should just be like .calibrate() and .eval_twin()... so you set the model, you
calibrate it and then you eval it", plus .simulate(). Each verb is a thin call over a runner (SimRunner: plan, measure, identify, score),
so there is always a level to drop to. eval(), not eval_twin() (Zach, the same evening: "I think twin.eval() no need to do eval_twin()
that's redundant"); evaluate() since 2026-11-17 (his sketch "twin.evaluate()"), eval() kept as its alias.

WHY RobotTwin.from_robot_description(rd) and not description.to_robot_twin() (Zach, 2026-11-17: "twin = RobotTwin.from_robot_description(rd)"):
on 2026-11-11 (docs/decision-types-seam-2026-11-11.md, addenda 2 and 3) sim2real sat BELOW robot_description, so it could not import a
description and the conversion was to live on the description's side ("The robotDescription does .to_twin or from_twin(). Sim2real just
knows about the twin"). The 2026-11-12 and 2026-11-16 rulings put sim2real on top of everything (robot_msgs -> robot_models -> robot_parts
-> robot_descriptions, sim2real outside), so that reason is gone: the twin now owns the conversion, the description stays bare-bones
(it only holds the information), and the one mapping from a description to typed instances lives here. It still imports no description
package: it reads rd by attribute, and binds the calibration world by rd's unit (the sysid example built for it), never by a name string
(no registry of robots here; the oracle examples stay fixtures, sim2real.examples). Renamed RobotTwin on 2026-11-11 ("a digital twin for an
electromechanical device"). The calibrated values come back on the twin, fitted.parameters; writing them into a description is not built
yet. The fit follows
scikit-learn's estimator contract: calibrate() returns a new twin whose learned values end in `_` (values_, intervals_, rungs_), and it
writes nothing anywhere. Sim or real is an argument (on=), not another verb; eval() refuses a training run; guards live in the runner, never
in callbacks.

WHY the calibrated values are a new twin and never an edit in place (Zach, the same evening: "we can almost like update the values of the
RobotDescription in place... with the calibrated twin"): the in-place feel is a functional update. Each fitted value comes back as a
robot_msgs Value, MEASURED, its interval as low/high and its source naming the calibration; the parameters nothing fitted keep their
prior and its source; twin.with_values({...}) is the same update by hand.

WHY over types (docs/decision-types-seam-2026-11-11.md): sim2real owns the generic types (cards.domain: parameters, model ladders,
routines, gates), and a twin is a composition of typed instances with parameter values, wherever those values came from (a
robot_description, a robotparts part, a CAD export, a guess). sim2real imports neither robot_description nor robotparts.

WHY sysid's oracle code in place, not mujoco.sysid and not a rewrite: the tracer is the one-DOF pendulum oracle
(sysid/examples/pendulum_can11), whose plan, hidden-truth world, fit and held-out score are proven there (sysid/tests/test_oracle.py),
and whose twin is bam_rack_twin's moteus PID at 30 kHz with a gear-gap hinge (its Replayer), not a plain MJCF rollout mujoco.sysid can
batch. mujoco.sysid (in the pinned 3.11.0; its extra's packages are not installed) is fit/'s engine for a type whose twin is plain MJCF.
sysid is an app folder beside this package (bam_rack_twin's venv), so it is imported lazily, from this checkout, by the sim runner only.

Layer: this module sits right of every folder: it may import any layer and none may import it (tests/test_layers.py).
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from robot_msgs.space import Basis, Value

from .cards import domain as dm
from .cards import registry as reg
from .metrics.gate import at_least, at_most, gate, required

REPO = Path(__file__).resolve().parents[2]
BACKENDS = ("sim", "real")  # calibrate(on=...)
# the v2 card each sim2real type's oracle rungs are keyed by (sysid's ladders are the cards' own: M0, M2, M3, M4 on "servo")
ORACLE_CARD = {"integrated_servo": "servo"}
STRUCTURAL = ("deployment", "mount")  # a description's untyped nodes (sysid's cards.STRUCTURAL words)
EXAMPLES = REPO / "sysid" / "examples"  # the calibration worlds, one per unit (each manifest's `record` names the unit)


def _sysid():
    """sysid's modules, from this checkout (an app folder beside the package: see the module's WHY)."""
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    from sysid import describe as sysid_describe  # noqa: PLC0415
    from sysid import oracle, result  # noqa: PLC0415
    from sysid import world as hidden  # noqa: PLC0415

    return sysid_describe, oracle, result, hidden


# --- the description: typed instances with parameter values ------------------------------------------------------------------------


@dataclass(frozen=True)
class Instance:
    """One typed instance: a sim2real generic type (cards.domain.TYPE_ORDER) and its parameter values. A structural node (a deployment, a
    mount) has no type. `on_type` says, per parameter, whether the type contract names it (the contract is additive-only: a parameter it
    lacks is carried and said, never dropped)."""
    id: str
    title: str
    type: str | None
    parent: str | None
    parameters: Mapping[str, Value | None] = field(default_factory=dict)
    on_type: Mapping[str, bool] = field(default_factory=dict)
    structural: str | None = None
    word: str = ""                      # the description's own word for it ("moteus_servo")
    binds: Mapping[str, Any] = field(default_factory=dict)
    part: str | None = None             # the robotparts part it is ("jmc-60asm200-5-1024c"), when the description names one


@dataclass(frozen=True)
class Description:
    """A RobotTwin's own record of its typed instances with parameter values (internal: the runners take it; never a robot description's
    own class, which RobotTwin.from_robot_description reads by attribute). `model` is the simulation model file (an MJCF), or None."""
    id: str
    title: str
    model: Path | None
    instances: tuple[Instance, ...]
    source: str

    def instance(self, instance_id: str) -> Instance:
        for i in self.instances:
            if i.id == instance_id:
                return i
        raise KeyError(f"{self.id} has no instance {instance_id!r}")

    def values(self) -> dict[str, Value | None]:
        """Every parameter value by its key, <instance>.<parameter>."""
        return {f"{i.id}.{name}": v for i in self.instances for name, v in i.parameters.items()}

    def with_values(self, values: Mapping[str, Value | None]) -> Description:
        """A NEW description with these parameters replaced, by key <instance>.<parameter> (the keys values() gives); every other
        parameter and instance is carried over as it is. A key the description does not carry is refused, never added."""
        unknown = sorted(set(values) - set(self.values()))
        if unknown:
            raise KeyError(f"{self.id} carries no parameter {unknown}")
        instances = []
        for i in self.instances:
            mine = {key.split(".", 1)[1]: v for key, v in values.items() if key.split(".", 1)[0] == i.id}
            instances.append(dataclasses.replace(i, parameters={**i.parameters, **mine}) if mine else i)
        return dataclasses.replace(self, instances=tuple(instances))

    def summary(self) -> str:
        lines = [f"{self.title} ({self.id}): {len(self.instances)} instances" + (f", model {self.model.name}" if self.model else "")]
        for i in self.instances:
            kind = i.type or f"({i.structural})"
            lines.append(f"  {i.id:14s} {kind:18s} {i.title}" + (f"  [{i.part}]" if i.part else "")
                         + (f"  [{len(i.parameters)} parameters]" if i.parameters else ""))
        return "\n".join(lines)


def _type_of(ref) -> tuple[str | None, str | None]:
    """(sim2real type id, structural word) of a sysid TypeRef: a v2 card maps through cards.domain.CARD_TYPE, sysid's adapter gripper is
    the gripper type, a structural node has none."""
    if ref.source == "structural":
        return None, ref.id
    if ref.source == "type_cards":
        return dm.CARD_TYPE.get(ref.id), None
    return (ref.id if ref.id in dm.TYPES else None), None


def describe(name: str) -> Description:
    """Internal: the adapter behind sim2real.examples (addendum 2), not public API. A sysid description manifest (sysid/examples/<name>/description.json) as typed instances whose
    parameters are robot_msgs Values carrying the manifest's own unit and source. WHY here and not in robot_description: robot_description
    cannot yet name a component's sim2real type or carry parameter Values (its Actuator/Sensor tags are string pairs), and this lane does
    not change its contract."""
    sysid_describe, *_ = _sysid()
    d = sysid_describe.load(name)
    owned = {row["id"]: row["parameters"] for row in d.tree()}
    instances = []
    for c in d.components:
        tid, structural = _type_of(c.type)
        names = {key.split(".", 1)[1]: key for key in owned.get(c.id, [])}
        on_type = {p.name for p in dm.TYPES[tid].parameters} if tid else set()
        values = {}
        for pname, key in names.items():
            n = d.nominal[key]
            # WHY ASSUMED: a description's value is a prior, stated with its source; a fit's value is MEASURED (Calibration.values)
            values[pname] = None if n.value is None else Value(float(n.value), n.unit, basis=Basis.ASSUMED, source=n.source, notes=n.note)
        instances.append(Instance(c.id, c.title, tid, c.parent, values, {p: p in on_type for p in names}, structural, c.word, dict(c.binds)))
    model = sysid_describe.resolve_path(d.manifest["model"]["path"])
    return Description(name, d.title, model, tuple(instances), f"sysid/examples/{name}/description.json")


# --- what the verbs return -----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Simulation:
    trajectory: Any          # robot_msgs JointTrajectory
    model: Path
    offset_rad: float

    def summary(self) -> str:
        q = self.trajectory.positions[:, 0]
        return (f"simulate: {self.model.name}, {self.trajectory.joint_names[0]} released {self.offset_rad:+.3f} rad off its bottom, "
                f"{self.trajectory.t[-1]:.2f} s headless at {len(self.trajectory.t) / max(self.trajectory.t[-1], 1e-9):.0f} Hz: "
                f"q from {q.min():+.4f} to {q.max():+.4f} rad, ends at {q[-1]:+.4f} rad")


@dataclass(frozen=True)
class Calibration:
    """A calibration's outcome: every rung's fitted values (the model's as robot_msgs Values, MEASURED) and, on the sim backend, each against
    the hidden truth (the oracle's rows: true, nominal, recovered, tolerance, pass)."""
    backend: str
    model: str                               # the sim2real model id whose values the twin uses (the type's current model by default)
    rung: str                                # the oracle card's rung key for it
    values: dict[str, Value | None]          # the model's parameters, by name (the servo's: can11.<name>)
    rungs: dict[str, dict[str, float | None]]
    rows: list[dict]                         # sysid.result parameter rows; true is the committed hidden truth
    truth_moved: dict[str, float]
    seconds: float
    plan: dict

    @property
    def failing(self) -> list[str]:
        return [r["key"] for r in self.rows if r["pass"] is False]

    @property
    def passed(self) -> bool:
        # WHY at least one graded (docs/CALIBRATE.md's `passed`; 2026-11-15, the real backend): a run on hardware has no hidden truth, so
        # its rows are not graded (pass None) and nothing has passed; on the sim every row is graded, so this is what it always was
        return any(r["pass"] is True for r in self.rows) and not self.failing

    def summary(self) -> str:
        how = f"transport={self.plan['transport']!r}" if self.plan.get("transport") else "truth='sealed'"
        head = (f"calibrate(on={self.backend!r}, {how}): {self.plan['train_runs']} train runs fitted rungs {', '.join(self.rungs)}"
                + (f" through {' -> '.join(self.plan['routines'])}" if self.plan.get("routines") else "")
                + f"; the fitted twin runs {self.model} ({self.rung}); {self.seconds:.0f} s")
        if self.truth_moved:
            head += f"\n  the hidden truth MOVED for this run: {self.truth_moved} (the ruler stays world.json's)"
        table = [f"  {'parameter':36s} {'nominal':>11s} {'hidden':>11s} {'recovered':>11s} {'error':>9s} {'tol':>9s}  verdict"]
        for r in self.rows:
            err = None if r["recovered"] is None or r["true"] is None else r["recovered"] - r["true"]
            tol = r["tolerance"]
            tol_text = "—" if tol is None else (f"{tol['value'] * 100:g} %" if tol["kind"] == "rel" else f"{tol['value']:g}")
            word = "not graded" if r["pass"] is None else "pass" if r["pass"] else "FAIL"
            table.append(f"  {r['key']:36s} {_g(r['nominal']):>11s} {_g(r['true']):>11s} {_g(r['recovered']):>11s} {_g(err):>9s} {tol_text:>9s}  {word}")
        graded = sum(r["pass"] is not None for r in self.rows)
        if self.rows and not graded:
            verdict = "  => NOT GRADED: real hardware has no hidden truth; eval() judges the twin on held-out runs over the rack's own floor"
            return "\n".join([head, *table, verdict])
        verdict = f"  => {'PASS' if self.passed else 'FAIL'}: {sum(r['pass'] is True for r in self.rows)}/{len(self.rows)} within tolerance of the hidden truth"
        return "\n".join([head, *table, verdict + (f" (failing: {', '.join(self.failing)})" if self.failing else "")])

    def to_dict(self) -> dict:
        return {"backend": self.backend, "model": self.model, "rung": self.rung, "values": {k: _plain(v) for k, v in self.values.items()},
                "rungs": self.rungs, "rows": self.rows, "truth_moved": self.truth_moved, "seconds": self.seconds, "plan": self.plan,
                "passed": self.passed, "failing": self.failing}


@dataclass(frozen=True)
class Gate:
    id: str
    title: str
    value: Any
    rule: str
    passed: bool
    source: str
    violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class TwinReport:
    """eval's report: held-out fidelity per model (link-camera RMS twin vs real ÷ the floor), the selection rule's pick and the gates."""
    model: str
    rung: str
    selected: str | None
    floor_mrad: float
    ratios: dict[str, float | None]
    metrics: dict[str, dict]
    gates: tuple[Gate, ...]
    runs: int
    seconds: float

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def summary(self) -> str:
        lines = [f"eval: {self.runs} held-out runs ({self.seconds:g} s of motion), floor {self.floor_mrad:.3f} mrad (two camera draws of one run)",
                 "  held-out link error / floor: " + ", ".join(f"{k} {_g(v, 3)}x" for k, v in self.ratios.items()),
                 f"  the selection rule picks {self.selected}; the twin is {self.model} ({self.rung})"]
        for g in self.gates:
            lines.append(f"  gate {g.id:24s} {'pass' if g.passed else 'FAIL'}  {g.title}: {g.value} ({g.rule}; {g.source})")
        lines.append(f"  => {'PASS' if self.passed else 'FAIL'}: {sum(g.passed for g in self.gates)}/{len(self.gates)} gates")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {**{k: v for k, v in dataclasses.asdict(self).items() if k != "gates"},
                "gates": [dataclasses.asdict(g) for g in self.gates], "passed": self.passed}


def _g(value, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}g}"


def _plain(value):
    return None if value is None else float(value)


# --- the runners ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineHandle:
    """What a tracer routine's fit may use (the third argument of fit(measured, values, twin)): the pipeline the runner plays, its sysid
    description, the twin's cap on every pool and the rung the twin runs. Never the truth."""
    module: Any
    description: Any
    workers: int
    rung: str


# the run ids a tracer routine names (sysid/examples/<id>/routines.py: TRAIN, one recorded session), each with the split of a measurement
# that fills it: the sim's RealWorld.measure and the real backend's ingest both hand back a `train` split
PLAYED_SPLITS = {"train": "train"}


def _played_from(measured) -> dict[str, Mapping[str, Any]]:
    """A measurement's runs by the run ids the routines name ({"train": measured.train}). WHY one function for both backends: the sim's
    world and the rack's ingest fill the same split, so a routine reads the same runs on either."""
    return {run_id: getattr(measured, split) for run_id, split in PLAYED_SPLITS.items()}


def _play_routines(routines: Sequence[Any], played: Mapping[str, Mapping[str, Any]], values: dict[str, float], handle: PipelineHandle, *,
                   servo: str) -> tuple[Any, list[dict], dict[str, str]]:
    """Play the planned routines in order over what was measured: each reads the runs it names from `played` (by run id), fits them sealed
    from the hidden truth, and hands what it found to the ones after it through `values` (updated in place). Returns (fit, steps, handed):
    the rung ladder one routine returned (routines.Ladder.fit), the steps as they ran (the record's routines) and, by parameter name, the
    method of each value the ladder carries that another routine found.

    WHY one executor for both backends (gap F-real, 2026-11-18): calibrate(on="sim") and calibrate(on="real") play the same schedule
    through this one loop, so their guards (a run nobody measured, an undeclared value, the seal) cannot drift apart."""
    from .calibration.plan import CalibrationPlanError  # noqa: PLC0415

    _refuse_rounds(routines, "this loop plays each routine once over what was measured")   # the routines a runner resolved itself, too
    *_, hidden = _sysid()
    rung = handle.rung
    estimates, steps, fit, ladder = {}, [], None, None
    # WHY the planned routines in the planned order and nothing else (Zach, 2026-11-17: the schedule is "a static description of the
    # routines that will be run"): what plan(twin) shows is what this loop plays
    for routine in routines:
        began = time.monotonic()
        runs = list(routine.runs(dict(values)))
        missing = [run.id for run in runs if run.id not in played]
        if missing:
            raise CalibrationPlanError(f"{routine.id} plays runs {missing}; the world played {sorted(played)}")
        data = {name: run_data for run in runs for name, run_data in played[run.id].items()}
        with hidden.sealed():
            found = routine.fit(data, dict(values), handle)
        extra = sorted(set(found) - set(routine.identifies))
        if extra:
            raise KeyError(f"{routine.id} returned {extra}, which it does not declare (identifies: {routine.identifies})")
        for key, estimate in found.items():
            estimates[key] = (routine.id, estimate)
            if estimate.value is not None and math.isfinite(estimate.value):
                values[key] = float(estimate.value)
        if getattr(found, "fit", None) is not None:
            fit, ladder = found.fit, routine.id
        steps.append({"routine": routine.id, "identifies": list(routine.identifies), "runs": len(data),
                      "seconds": round(time.monotonic() - began, 1),
                      "found": {k: (None if e.value is None else float(e.value)) for k, e in found.items()}})
    if fit is None:
        raise CalibrationPlanError(f"the twin runs a rung of servo.dynamics_regression's ladder ({rung}), and the planned routines "
                                   f"({', '.join(r.id for r in routines) or 'none'}) do not include it")
    # a value the ladder carries that another routine found (M4's gap, servo.backlash_reversals_camera) keeps that routine's interval
    # and method: the ladder was handed it, it did not estimate it
    handed = {}
    for key, (rid, estimate) in estimates.items():
        name = key.split(".", 1)[1] if key.startswith(f"{servo}.") else None
        if rid == ladder or name is None or estimate.value is None:
            continue
        for k in fit.values:
            if fit.values[k].get(name) == estimate.value and estimate.ci95:
                fit.ci95.setdefault(k, {})[name] = tuple(estimate.ci95)
        if fit.values[rung].get(name) == estimate.value:
            handed[name] = estimate.method
    return fit, steps, handed


def _refuse_rounds(routines: Sequence[Any] | None, why: str) -> None:
    """Refuse, by id and before anything is played or sysid is touched, a routine that comes back for more (next_runs: rounds) on a
    runner that plays its schedule once (`why`: how this one plays). WHY refused and never run once (gap A2): an iterating routine played
    for one round would hand back a fit it never judged converged, silently; it runs on a rig on the one-click seam (sim2real.rig)."""
    rounds = [r.id for r in routines or () if callable(getattr(r, "next_runs", None))]
    if rounds:
        raise NotImplementedError(f"{rounds} come back for more (next_runs: collect, fit, then another round made after the fit), and {why}, "
                                  "so a round's new runs cannot be collected; a routine with rounds runs on a rig on the one-click seam "
                                  "(sim2real.rig.RigRunner)")


def _mark_unplanned_rows(rows: list[dict], routines: Sequence[Any], shipped) -> None:
    """Ungrade (pass None, with why) each parameter row whose owning routine (the shipped schedule's parameters()) was left out of the
    plan: the prior or the rung's constant serves, as on the rig seam."""
    ran = {r.id for r in routines}
    owner = {p.key: p.routine for p in shipped.parameters()} if shipped is not None else {}
    for row in rows:
        if owner.get(row["key"]) is not None and owner[row["key"]] not in ran:
            row["pass"], row["why_not"] = None, f"its routine {owner[row['key']]} was not in the plan"


class SimRunner:
    """The sim backend: the description's oracle pipeline (sysid/examples/<id>/pipeline.py: plan, RealWorld, identify, score, assemble)
    played on the simulator at the hidden truth, through the example's routines (sysid/examples/<id>/routines.py, the schedule plan(twin)
    shows: each routine's fit is a step of the pipeline). `truth` moves named hidden values for a run (the mutation test of the ruler: the
    world plays the moved truth, the parameter rows still compare with world.json's). Its guards are its own, never a callback's: every
    routine fits sealed from the truth, and eval scores held-out runs only. `state` is a fitted twin's (plan, measurements, fit)."""

    def __init__(self, description: Description, *, workers: int = 6, state: dict | None = None):
        self.description = description
        self.workers = workers
        self.state: dict = dict(state or {})

    def pipeline(self):
        _, oracle, _, _ = _sysid()
        return oracle.example_module(self.description.id)

    def schedule(self):
        """The routines the example ships (sysid/examples/<id>/routines.py, its schedule(): the planner's half of a RigBackend, `name`,
        `parameters()` and `routines()`), or None: plan() then shows the catalog's routines, which nothing here runs."""
        if not (EXAMPLES / self.description.id / "routines.py").exists():
            return None
        _sysid()  # puts this checkout (sysid's home) on the path
        import importlib  # noqa: PLC0415

        return importlib.import_module(f"sysid.examples.{self.description.id}.routines").schedule()

    def sysid_description(self):
        sysid_describe, *_ = _sysid()
        d = sysid_describe.load(self.description.id)
        # WHY refused rather than ignored: the pipeline reads its priors from the manifest, so a value edited on the instances would not
        # reach the fit or the "before" score; say so instead of scoring a description nobody asked for
        stated = {k: (None if v is None else float(v)) for k, v in self.description.values().items()}
        manifest = {k: (None if n.value is None else float(n.value)) for k, n in d.nominal.items()}
        if stated != manifest:
            edited = sorted(k for k in stated.keys() | manifest.keys() if stated.get(k) != manifest.get(k))
            raise NotImplementedError(f"the sim pipeline reads its priors from {self.description.source}; edited values do not reach it yet: {edited}")
        return d

    def calibrate(self, *, model: str | None = None, truth: Mapping[str, float] | None = None,
                  routines: Sequence[Any] | None = None) -> tuple[Calibration, dict]:
        """`routines`: the planned sequence (sim2real.calibration.plan(twin).routines: ordered, substituted, option copies), else the
        example's own routines in their declared order. The world plays the schedule once (pipeline RealWorld.measure: train, held-out
        and the floor's repeat draws); each routine then reads the runs it names and fits them sealed, in order, each seeing what the ones
        before it found. One of them must return the rung ladder (routines.Ladder: servo.dynamics_regression), the twin's model."""
        from .calibration.plan import order  # noqa: PLC0415

        _refuse_rounds(routines, "the pendulum tracer's world plays its schedule once")
        _, _, result, hidden = _sysid()
        started = time.monotonic()
        module, d = self.pipeline(), self.sysid_description()
        servo = self.typed()
        model = model or dm.current_models(servo.type)[0].id
        rung = self._rung(servo.type, model)
        plan = module.plan(d)
        real = module.RealWorld(d, workers=self.workers)
        moved = dict(truth or {})
        unknown = sorted(set(moved) - set(real.truth))
        if unknown:
            raise KeyError(f"no hidden value {unknown} in {self.description.id}'s world (it has {sorted(real.truth)})")
        real.truth = {**real.truth, **moved}  # the world plays the moved values; RealWorld.twin reads .truth
        # the noise the world plays (world.json's block at the ladder's scale, as RealWorld loaded it): the record's `noise`
        scale = getattr(hidden, "_NOISE_SCALE", [1.0])[-1]
        noise = {**real.noise, "level": scale, "seed": real.seed,
                 "sources": {name: f"sysid/examples/{self.description.id}/world.json noise block x{scale:g} (sysid.hidden.load)" for name in real.noise}}
        measured = real.measure(plan)
        measure_s = round(time.monotonic() - started, 1)
        shipped = self.schedule()
        if routines is None:
            if shipped is None:
                raise NotImplementedError(f"{self.description.id} ships no routines (sysid/examples/{self.description.id}/routines.py): "
                                          "nothing here runs the catalog's routines plan() would show")
            names = {f"{i.id}.{n}": n for i in self.description.instances for n in i.parameters}
            routines = order(shipped.routines(), names)
        # the values each routine sees: the description's priors, then what each routine before it found
        values = {k: float(v) for k, v in self.description.values().items() if v is not None}
        # WHY workers passed (2026-11-17): without it the pendulum's identify() polishes friction on its default 8-worker pool, which
        # opened 8 processes beside the powered arm at host load 35; the runner's workers caps every pool it opens (tests/test_workers_cap.py)
        handle = PipelineHandle(module, d, self.workers, rung)
        fit, steps, handed = _play_routines(routines, _played_from(measured), values, handle, servo=servo.id)
        ruler = json.loads(hidden.path(self.description.id).read_text(encoding="utf-8"))["truth"]  # world.json as committed: the ruler
        recovered = {f"{servo.id}.{name}": {"value": value, "ci95": fit.ci95[rung].get(name), "rung": f"fitted with {rung}",
                                              "method": handed.get(name, fit.methods[rung])} for name, value in fit.values[rung].items()}
        rows = result.parameter_rows(self.description.id, d, ruler, recovered)
        _mark_unplanned_rows(rows, routines, shipped)
        values = {}
        for name, value in fit.values[rung].items():
            unit = d.nominal[f"{servo.id}.{name}"].unit if f"{servo.id}.{name}" in d.nominal else None
            ci = fit.ci95[rung].get(name)
            values[name] = None if value is None else Value(float(value), unit, basis=Basis.MEASURED, measured_by=f"sim2real.RobotTwin.calibrate(on='sim', truth='sealed'), {model}",
                                                           source=handed.get(name, fit.methods[rung]), notes=f"95 % interval [{ci[0]:.6g}, {ci[1]:.6g}]" if ci else "")
        # the rungs the ladder fitted, in its order, each with only the values it estimated (the ones with a bootstrap interval; the rest
        # are a rung's structural constants, such as M0's zero friction): the sysid-shaped view of the fit (state["fits"]); the record's
        # routines are the planned steps as they ran (state["routines"], CalibrationRecord.from_schedule)
        card = ORACLE_CARD[servo.type]
        fits = [{"rung": k, "model": dm.RUNG_MODELS.get((card, k), (k,))[0],
                 "found": {f"{servo.id}.{name}": fit.values[k][name] for name in fit.values[k] if name in fit.ci95.get(k, {})}} for k in fit.values]
        state = {"d": d, "plan": plan, "measured": measured, "fit": fit, "ruler": ruler, "model": model, "rung": rung, "module": module,
                 "servo": servo, "noise": noise, "fits": fits, "noise_level": f"{scale:g}x", "routines": steps, "measure_seconds": measure_s}
        return Calibration("sim", model, rung, values, {k: dict(v) for k, v in fit.values.items()}, rows, moved,
                           round(time.monotonic() - started, 1),
                           {"train_runs": len(plan.train), "held_out_runs": len(plan.held_out), "digest": plan.digest,
                            "coverage_train_pct": plan.coverage["train"]["pct"], "routines": [s["routine"] for s in steps]}), state

    def eval(self) -> TwinReport:
        if not self.state:
            raise RuntimeError("eval needs a fitted twin: fitted = twin.calibrate(...), then fitted.eval()")
        _, _, result, _ = _sysid()
        s = self.state
        # WHY refused, not filtered (the held-out split is the only judge; sklearn's leakage rule): score() replays plan.held_out, so a run
        # there that the fit saw, or one the schedule marks train, would grade the twin on its own training data
        leaked = sorted({r["run"] for r in s["plan"].held_out if r["split"] != "held_out" or r["run"] in s["measured"].train})
        if leaked:
            raise ValueError(f"eval scores held-out runs only; these are training runs: {leaked[:5]}")
        scores = s["module"].score(s["d"], s["plan"], s["fit"], s["measured"], workers=self.workers)
        doc = s["module"].assemble(s["d"], s["plan"], s["fit"], scores, truth=s["ruler"])
        ratios = {k: v["ratio"] for k, v in scores["models"].items()}
        fidelity = next(m for m in doc["metrics"] if m["id"] == "held_out_link_fidelity")
        factor_needed = result.ACCEPTANCE["examples"][self.description.id]["metrics"]["held_out_link_fidelity"]
        gates = []
        verdict = gate(ratios.get(s["rung"]), at_most(reg.TWINNED_LIMIT, "x floor"))
        gates.append(Gate("twinned", f"{s['model']} held-out link error / floor", _g(ratios.get(s["rung"]), 3), f"<= {reg.TWINNED_LIMIT:g}x",
                          verdict.passes, "sim2real.cards.registry.TWINNED_LIMIT", verdict.violations))
        verdict = gate(fidelity["factor"], at_least(factor_needed, "x"))
        gates.append(Gate("held_out_link_fidelity", "held-out link error, nominal / calibrated", _g(fidelity["factor"], 3), f">= {factor_needed:g}x",
                          verdict.passes, "sysid/acceptance.json", verdict.violations))
        failing = [r["key"] for r in doc["parameters"] if r["pass"] is False]
        verdict = gate(not failing and bool(doc["parameters"]), required())
        gates.append(Gate("recovery", "every hidden value within its tolerance (the sim oracle only)",
                          f"{sum(r['pass'] is True for r in doc['parameters'])}/{len(doc['parameters'])}" + (f", failing {', '.join(failing)}" if failing else ""),
                          "all", verdict.passes, "sysid/examples/<id>/world.json + sysid/acceptance.json", verdict.violations))
        return TwinReport(s["model"], s["rung"], doc["selected_rung"], scores["floor_mrad"], ratios,
                          {m["id"]: m for m in doc["metrics"]}, tuple(gates), scores["runs"], scores["seconds"])

    def simulate(self, *, seconds: float = 2.0, offset_rad: float = 0.3, rate_hz: float = 200.0, viewer: bool = False) -> Simulation:
        """The description's model in MuJoCo, released `offset_rad` off its stated gravity bottom with no command (headless unless
        `viewer`): what the description says before anything is fitted."""
        import mujoco  # noqa: PLC0415  (the sim extra)
        import numpy as np  # noqa: PLC0415
        from robot_msgs.trajectory import JointTrajectory  # noqa: PLC0415

        servo = self.typed()
        joint = servo.binds.get("joint")
        model = mujoco.MjModel.from_xml_path(str(self.description.model))
        data = mujoco.MjData(model)
        address = model.joint(joint).qposadr[0]
        data.qpos[address] = float(servo.parameters["gravity_bottom_rad"]) + offset_rad
        mujoco.mj_forward(model, data)
        every = max(1, round(1.0 / (rate_hz * model.opt.timestep)))
        steps = round(seconds / model.opt.timestep)
        t, q, qd = [], [], []
        handle = None
        if viewer:
            import mujoco.viewer  # noqa: PLC0415

            handle = mujoco.viewer.launch_passive(model, data)
        for k in range(steps + 1):
            if k % every == 0:
                t.append(data.time); q.append(data.qpos[address]); qd.append(data.qvel[model.joint(joint).dofadr[0]])
            if k < steps:
                mujoco.mj_step(model, data)
                if handle is not None:
                    handle.sync()
        if handle is not None:
            handle.close()
        trajectory = JointTrajectory(t=np.asarray(t), joint_names=(joint,), positions=np.asarray(q)[:, None], velocities=np.asarray(qd)[:, None])
        return Simulation(trajectory, self.description.model, offset_rad)

    def typed(self) -> Instance:
        """The instance the oracle calibrates: the description's one instance of a type with an oracle ladder (the tracer's servo)."""
        typed = [i for i in self.description.instances if i.type in ORACLE_CARD]
        if len(typed) != 1:
            raise NotImplementedError(f"the sim backend calibrates one instance of {sorted(ORACLE_CARD)}; {self.description.id} has {len(typed)}")
        return typed[0]

    @staticmethod
    def _rung(type_id: str, model_id: str) -> str:
        card = ORACLE_CARD[type_id]
        keys = [k for (c, k), ids in dm.RUNG_MODELS.items() if c == card and model_id in ids]
        if not keys:
            raise KeyError(f"{model_id} is not on {type_id}'s ladder as the oracle fits it ({[m.id for m in dm.models(type_id)]})")
        return keys[0]


class RobotTwin:
    """A digital twin for an electromechanical device: its typed instances (each a sim2real type with parameter Values), the model each runs
    (the type's current model unless `models` picks a rung), and, once calibrated, its learned values (scikit-learn's convention: values_,
    intervals_, rungs_, calibration_ exist only on a fitted twin). Each verb is a thin call into its runner (self.runner), the level to drop
    to. `self.description` is the twin's own record of its instances (sim2real's, internal), never robot_description's RobotDescription."""

    def __init__(self, instances: Sequence[Instance], *, name: str, model_file: str | Path | None = None,
                 models: Mapping[str, str] | None = None, title: str = "", source: str = "", workers: int = 6):
        """Built directly, never loaded by a name from a registry (sim2real has none). `name` binds the runner: calibrate() plays the
        sysid/examples/<name> world, through its rig.py when it ships one. `model_file` is the simulation model (MJCF) simulate() opens.
        `models` picks a rung by instance id ({"can11": "M3.dynamics.stribeck"}); an instance it leaves out runs its type's current model."""
        self.description = Description(name, title or name, None if model_file is None else Path(model_file), tuple(instances), source)
        self.models = dict(models or {})
        self.runner = _runner(self.description, workers)
        if _is_rig(self.runner):
            if self.models:
                raise NotImplementedError(f"{name}'s twin is its rig.py's ({self.runner.default_model()}); "
                                          "models= picks a rung on the tracer only")
            self.model = self.runner.default_model()
        else:
            servo = self.runner.typed()
            self.model = self.models.get(servo.id) or dm.current_models(servo.type)[0].id

    @classmethod
    def from_robot_description(cls, rd, *, models: Mapping[str, str] | None = None, workers: int = 6) -> RobotTwin:
        """The twin of a robot's description (Zach, 2026-11-17: "twin = RobotTwin.from_robot_description(rd)"). Read by attribute, so
        sim2real imports no description package: `rd.name`, `rd.title`, `rd.model` (the MJCF), `rd.source`, `rd.record` (the unit:
        {"path": its deployment record, "component": its id}) and `rd.components`, each with `.id`, `.title`, `.type` (a sim2real type
        id, or "deployment" for the structural root), `.parent`, `.parameters` ({name: robot_msgs Value, or None for "states none"}),
        `.binds` and `.part` (a robotparts id, or None). First description: bam_rack_twin.description.station_description(11).

        The runner world is bound by the unit: the sysid example whose manifest `record` names the same deployment file and component
        (the calibration world built for that unit), so the twin calibrates exactly where the hand-built fixture does."""
        if not hasattr(rd, "components"):
            if hasattr(rd, "elements") or hasattr(rd, "interfaces"):
                raise TypeError(f"{getattr(rd, 'name', rd)!r} is a design-only RobotDescription: it names no unit (which board, which CAN id) "
                                "and no typed priors (robot_msgs Values per sim2real type), so no twin can be built from it alone. Pass a "
                                "description that joins the design with its unit and parts, e.g. "
                                "bam_rack_twin.description.station_description(11)")
            raise TypeError(f"from_robot_description reads rd.components; {type(rd).__name__} has none")
        components = tuple(rd.components)
        ids = [c.id for c in components]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"{rd.name}: component ids must be unique, {repeated} repeat")
        orphans = sorted(c.id for c in components if c.parent is not None and c.parent not in ids)
        if orphans:
            raise ValueError(f"{rd.name}: {orphans} name a parent that is no component")
        instances = []
        for c in components:
            structural = c.type if c.type in STRUCTURAL else None
            if structural is None and c.type not in dm.TYPES:
                raise ValueError(f"{rd.name}: component {c.id!r} has type {c.type!r}, which is no sim2real type "
                                 f"({', '.join(sorted(dm.TYPES))}) nor a structural node ({', '.join(STRUCTURAL)})")
            parameters = dict(c.parameters or {})
            for name, value in parameters.items():
                # WHY refused, not wrapped: a bare number carries no unit and no source, and a prior without them is not a description
                if value is not None and not isinstance(value, Value):
                    raise TypeError(f"{rd.name}: {c.id}.{name} is a {type(value).__name__}, not a robot_msgs Value (unit + source)")
            on_type = {p.name for p in dm.TYPES[c.type].parameters} if structural is None else set()
            instances.append(Instance(c.id, c.title, None if structural else c.type, c.parent, parameters,
                                      {p: p in on_type for p in parameters}, structural, c.type, dict(c.binds or {}),
                                      getattr(c, "part", None)))
        world = _world_for(rd.record)
        return cls(instances, name=world, model_file=rd.model, models=models, title=rd.title, source=rd.source, workers=workers)

    @property
    def fitted(self) -> bool:
        return hasattr(self, "values_")

    @property
    def instances(self) -> tuple[Instance, ...]:
        return self.description.instances

    @property
    def parameters(self) -> dict[str, dict[str, Value | None]]:
        """Every instance's parameter Values, {instance: {name: Value}}. On a loaded twin, the priors. On a fitted twin, the calibrated
        values (MEASURED, the 95 % interval as low/high, a source naming the calibration and the day) and, for what nothing fitted, the
        priors with their own source. A new dict each call: editing it changes nothing (use with_values)."""
        return {i.id: dict(i.parameters) for i in self.description.instances if i.parameters}

    def with_values(self, values: Mapping[str, Mapping[str, Value | None]]) -> RobotTwin:
        """A NEW, unfitted twin with these parameters replaced, {instance: {name: Value}}, everything else carried over; this twin is
        unchanged. A parameter the twin does not carry is refused, never added."""
        d = self.description.with_values({f"{instance}.{name}": v for instance, named in values.items() for name, v in named.items()})
        return RobotTwin(d.instances, name=d.id, model_file=d.model, models=self.models, title=d.title, source=d.source,
                         workers=self.runner.workers)

    def simulate(self, **options) -> Simulation:
        return self.runner.simulate(**options)

    def generate_schedule(self, config=None):
        """The CalibrationSchedule calibrate() plays, without running anything (sim2real.calibration.plan(self, config)): each step in run
        order with its runs bound at the priors, each run's typed command, which commands are known now and which are made after an
        earlier step runs. WHY on the twin (Zach, Daily Note 2026-11-17: "robottwin.calibrate() internall mabye that does
        .generate_schedule() -> CalibrationSchedule and then you can pass that to something thats gonna like dispatch/execute it")."""
        from .calibration.plan import plan  # noqa: PLC0415

        return plan(self, config)

    def calibrate(self, on: str = "sim", *, truth: str = "sealed", move_truth: Mapping[str, float] | None = None, noise=None, config=None,
                  data=None, transport=None) -> RobotTwin:
        """A NEW twin, fitted: the type's routine schedule played `on` the simulator at the hidden truth (`truth="sealed"`: the fit never
        sees it) or on the real hardware through `transport` (sim2real.real: RackTransport, the One Dof Test Rack's session runner, a dry
        run unless it is told to execute; TwinTransport, the rack twin at a sealed hidden truth; docs/CALIBRATE.md "on='real'"). `move_truth`
        moves named hidden values for one run, the ruler unchanged (its mutation test; on the real backend it is the transport's).
        `noise` (a rig on the one-click seam only): None = the rig's measured 1x, a number = every term at that level, or a
        sim2real.rig.NoiseModel. `config` (a sim2real.calibration.CalibrationConfig) steers the run: models, known values, exclusions, an
        order, the budget, per-routine options, injected routines (PEP 0001 §6). `data` (sim2real.calibration.collect(twin)) fits recorded
        runs without measuring. The routines run in the planned order (sim2real.calibration.plan); the fitted twin carries it as plan_ and
        the run as record_ (sim2real.calibration/1, docs/CALIBRATE.md)."""
        if on not in BACKENDS:
            raise ValueError(f"on must be one of {BACKENDS}, not {on!r}")
        if truth != "sealed":
            raise ValueError(f"calibrate fits against a sealed hidden truth (truth='sealed'), not {truth!r}")
        if on == "real":
            return self._calibrate_real(transport, move_truth=move_truth, noise=noise, config=config, data=data)
        if transport is not None:
            raise ValueError("transport= is the real backend's (on='real'); on='sim' plays the simulator itself")
        if _is_rig(self.runner):
            from .rig import RigRunner  # noqa: PLC0415

            from .calibration.collect import fit_rig  # noqa: PLC0415
            from .calibration.record import CalibrationRecord  # noqa: PLC0415

            calibration, state, plan = fit_rig(self, move_truth=move_truth, noise=noise, config=config, data=data)
            fitted = RobotTwin.__new__(RobotTwin)
            fitted.description = self.description.with_values(_identified(calibration, calibration.model))
            fitted.model, fitted.models = self.model, self.models
            fitted.runner = RigRunner(self.description, self.runner.rig, workers=self.runner.workers, state=state)
            fitted.values_ = calibration.values
            fitted.intervals_ = {r["key"]: tuple(r["ci95"]) for r in calibration.rows if r["ci95"]}
            fitted.rungs_ = {step["routine"]: step["found"] for step in calibration.routines}
            fitted.calibration_ = calibration
            fitted.plan_ = plan
            fitted.record_ = CalibrationRecord.from_rig(calibration.to_dict(), description=self.description, plan=plan)
            return fitted
        if data is not None:
            raise NotImplementedError("data= fits recorded runs on a rig on the one-click seam (sim2real.calibration.collect); the pendulum "
                                      "tracer's world plays its schedule itself (recorded runs reach it through on='real')")
        if noise is not None:
            raise NotImplementedError("the pendulum tracer sets its noise through sysid's ladder (sysid.world.noise_scale), not calibrate(noise=)")
        from .calibration.config import CalibrationConfig  # noqa: PLC0415
        from .calibration.record import CalibrationRecord  # noqa: PLC0415

        config = config if config is not None else CalibrationConfig()
        # WHY refused by name rather than ignored: the tracer's config steers which routines run and in what order (plan()); what fixes a
        # value, picks a rung or sets a noise reaches it another way, not yet through the config
        unwired = [name for name, given in (("known", config.known), ("models", config.models), ("noise", config.noise is not None),
                                            ("seed", config.seed is not None)) if given]
        if unwired:
            raise NotImplementedError(f"CalibrationConfig.{', CalibrationConfig.'.join(unwired)} does not reach the pendulum tracer yet: its "
                                      "config picks, orders and excludes routines (plan()); its rung is RobotTwin(models=...), its noise "
                                      "sysid's ladder (sysid.world.noise_scale)")
        # WHY plan first and play exactly its routines (Zach, 2026-11-17: "robottwin.calibrate() internall mabye that does
        # .generate_schedule() -> CalibrationSchedule and then you can pass that to something thats gonna like dispatch/execute it"): the
        # schedule plan(twin) shows is the one that runs, and the fitted twin carries it as plan_
        planned = self.generate_schedule(config)
        calibration, state = self.runner.calibrate(model=self.model, truth=move_truth, routines=list(planned.routines))
        servo = self.runner.typed().id
        fitted = RobotTwin.__new__(RobotTwin)
        fitted.description = self.description.with_values(_identified(calibration, calibration.rung, lambda name: f"{servo}.{name}"))
        fitted.model, fitted.models = self.model, self.models
        # WHY the runner keeps the loaded description: the sim pipeline reads its priors from the manifest and refuses edited values
        fitted.runner = SimRunner(self.description, workers=self.runner.workers, state=state)
        fitted.values_ = calibration.values
        fitted.intervals_ = {k: tuple(r["ci95"]) for k, r in ((r["name"], r) for r in calibration.rows) if r["ci95"]}
        fitted.rungs_ = calibration.rungs
        fitted.calibration_ = calibration
        # WHY only when the runner reports the routines it played (2026-11-12): a record lists what actually ran; a runner that hands back
        # no state (tests/test_one_click.py stubs it) has nothing honest to record, so plan_ / record_ stay None rather than a plan not played
        if not {"routines", "noise", "measured"} <= set(state):
            fitted.plan_ = fitted.record_ = None
            return fitted
        fitted.plan_ = planned
        fitted.record_ = CalibrationRecord.from_schedule(calibration.to_dict(), routines=state["routines"], plan=planned, noise=state["noise"],
                                                         twin=self.description.id, description=self.description)
        return fitted

    def _calibrate_real(self, transport, *, move_truth=None, noise=None, config=None, data=None) -> RobotTwin:
        """on='real' (sim2real.real.calibrate): plan, emit the rack submission, play it through `transport`, ingest the runs as
        JointTrajectory, fit them through the schedule's routines (plan(twin), the same loop the sim plays). WHY each refusal names the way
        through: the real backend plays the pendulum tracer's schedule on recorded runs, so what steers a rig (config, data, noise) has no
        meaning here yet, and the truth to move is the transport's world, never the backend's."""
        if _is_rig(self.runner):
            raise NotImplementedError(f"on='real' runs the pendulum tracer's pipeline on the rack (sim2real.real); {self.description.id}'s rig "
                                      "on the one-click seam has no rack transport yet")
        if transport is None:
            raise TypeError("calibrate(on='real') plays the schedule through a transport: sim2real.real.RackTransport(out) for the One Dof "
                            "Test Rack (writes the rack submission and dry-runs it; only RackTransport(out, execute=True, adapter=...) starts "
                            "the rack's session runner), or sim2real.real.TwinTransport() for the rack twin at a sealed hidden truth")
        if move_truth:
            raise ValueError("on='real' has no truth to move: the world is the transport's (sim2real.real.TwinTransport(move_truth=...))")
        if config is not None or data is not None or noise is not None:
            raise NotImplementedError("config=, data= and noise= steer a rig on the one-click seam; on='real' plays the schedule plan(twin) "
                                      "shows with its default config, over the runs the rack sends back (its noise is the hardware's: "
                                      "eval()'s floor measures it)")
        from . import real  # noqa: PLC0415

        return real.calibrate(self, transport)

    def noise(self):
        """The rig's measured 1x noise model (sim2real.rig.NoiseModel): .at(level) and .with_terms(...) make a stress lane's sweep."""
        if not _is_rig(self.runner):
            raise NotImplementedError("the pendulum tracer's noise is sysid's world.json noise block (sysid.world.noise_scale)")
        return self.runner.noise()

    def result(self):
        """The fitted twin's calibration as one page: sim2real.result.CalibrationResult (its display() serves it)."""
        if not self.fitted:
            raise RuntimeError("result() needs a fitted twin: fitted = twin.calibrate(...), then fitted.result()")
        if not _is_rig(self.runner):
            raise NotImplementedError("the pendulum tracer's page is reports/one-click-tracer-2026-11-11.html")
        return self.runner.result()

    def evaluate(self) -> TwinReport:
        """The fitted twin on held-out runs only: error / floor per model and the gates (TwinReport, or the rig's RigReport).
        WHY evaluate(), with eval() its alias (Zach's 2026-11-17 sketch, twin.evaluate()): Keras names this model.evaluate(); in PyTorch
        model.eval() means "switch to inference mode", not "score me". The Nov 11 call dropped eval_twin()'s "_twin", which still holds."""
        if not self.fitted:
            raise RuntimeError("evaluate needs a fitted twin: fitted = twin.calibrate(...), then fitted.evaluate()")
        return self.runner.eval()

    def eval(self) -> TwinReport:
        """Alias of evaluate()."""
        return self.evaluate()

    def summary(self) -> str:
        return self.calibration_.summary() if self.fitted else self.description.summary()


def _identified(calibration, rung: str, key=lambda name: name) -> dict[str, Value]:
    """A calibration's fitted values as description parameters, by key <instance>.<parameter>: the fitted value and unit, MEASURED, its 95 %
    interval as low/high (kept in the notes instead when it does not bracket the value), and a source naming the calibration and the day.
    `key` maps a calibration's value name to its description key (the tracer's are the servo's parameter names)."""
    stamp = f"sim2real calibrate · on={calibration.backend} · {rung} · {date.today().isoformat()}"
    intervals = {r["key"]: r["ci95"] for r in calibration.rows if r.get("ci95")}
    out = {}
    for name, fitted in calibration.values.items():
        if fitted is None:
            continue
        low, high = intervals.get(key(name)) or (None, None)
        bracketed = low is not None and high is not None and low <= float(fitted) <= high
        notes = "; ".join(filter(None, [fitted.source, fitted.notes if not bracketed else ""]))
        out[key(name)] = Value(float(fitted), fitted.unit, low=low if bracketed else None, high=high if bracketed else None,
                               basis=Basis.MEASURED, source=stamp, measured_by=fitted.measured_by, notes=notes)
    return out


def _world_for(record: Mapping[str, Any] | None) -> str:
    """The calibration world built for a unit: the sysid example whose manifest `record` names the same deployment file (resolved) and
    component. WHY by the unit and not by a name the description carries: the world (its schedule, its hidden truth, its rig) was built
    for one physical unit, so the unit is what binds them; a description never has to know sim2real's example names."""
    if not record or "path" not in record or "component" not in record:
        raise LookupError(f"from_robot_description binds the calibration world by the unit, rd.record = {{'path', 'component'}}; got {record!r}")
    wanted = (Path(record["path"]).resolve(), record["component"])
    worlds = {}
    for manifest in sorted(EXAMPLES.glob("*/description.json")):
        unit = json.loads(manifest.read_text(encoding="utf-8")).get("record") or {}
        if unit.get("path") and unit.get("component"):
            worlds[manifest.parent.name] = (Path(unit["path"]).resolve(), unit["component"])
    found = [name for name, unit in worlds.items() if unit == wanted]
    if not found:
        have = ", ".join(f"{name} ({unit[1]} in {unit[0].name})" for name, unit in worlds.items()) or "none"
        raise LookupError(f"no calibration world for component {record['component']!r} of {record['path']}; the worlds built for a unit: {have}")
    return found[0]


def _runner(description: Description, workers: int):
    """The rig's own runner when its description ships rig.py (the one-click seam, sim2real.rig), else the pendulum tracer's SimRunner.
    WHY by the file and not a flag: a rig opts in by supplying the seam (docs/one-click-seam.md); the tracer's proven path is untouched."""
    from . import rig as seam  # noqa: PLC0415

    backend = seam.load_rig(description.id)
    return SimRunner(description, workers=workers) if backend is None else seam.RigRunner(description, backend, workers=workers)


def _is_rig(runner) -> bool:
    return type(runner).__name__ == "RigRunner"

