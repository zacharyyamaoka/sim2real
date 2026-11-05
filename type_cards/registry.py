"""Sim2Real type cards: one card per part type, as code (the code is the living spec).

Zach, PROJECT - Sim2Real, Journal, Nov 4 2026: "for each type I think we need to define some Objectives or metrics ... Ideally
those are things that don't depend on the model ... We are taking a black box approach ... For each of these makes a table
1. Metrics 2. Models (and the parameters that are part of that model) ... each one needs a standard visualization ... The
general procedure for these I believe is the same ... we need to cover the space ... determine that for each level and
actuator/sensor."

A card holds, for one type:
- **metrics**, black box and output-only, in two families: *performance* (the device's output against the commanded target)
  and *fidelity* (the twin's output against the real output on the same input); each normalised by the device's own
  repeatability floor where one is measurable, so types compare. Model parameters are levers, never metrics.
- **model**: every parameter with its unit, nominal value or source, the experiment that identifies it, and whether the
  type's observable outputs can see it at all (encoder-blind terms like backlash are "no");
- **coverage**: the input axes and a binning rule, and a function that scores a planned set (type_cards/coverage.py);
- **view**: the data-ui gallery template that draws it (at the commit sim2real vendors) or `proposed`;
- **procedure**: the one shared sequence (STEPS), each step a file, with this type's tool for each step or `proposed`;
- **observability** on today's hardware (the One Dof Test Rack) versus the instruments it still needs;
- **members**: what a composite is made of (an arm's joints are servo cards) and its own error budget.

WHY here, in sim2real/type_cards/, and not in RobotDx or robotparts (dispatcher brief, 2026-11-04): sim2real is the app about
these types, and the other repos are cited by id, never forked: metrics name RobotDx stock-catalog entries
(io-diagnostics robotdx/diagnostics/catalog.py at ROBOTDX_COMMIT), parameters name robotparts model terms
("robotparts:<model>.<term>") and bam_rack_twin's TwinParameters, views name data-ui gallery templates at the commit
vendor/data-ui/VENDOR.md records. What they lack is listed as `proposed` with the gap named, so the gap list is generated.
WHY "type_cards" and not "types": a top-level package named `types` shadows Python's stdlib module of that name.
v2 (Zach, PROJECT - Sim2Real, "Proposed Work Flow Nov 5 2026"; type_cards/CONTRACT.md): every card also holds a ladder of model
rungs (type_cards/ladders.py: physics, its wear variant, a grey-box residual and a black-box net, each counted and referenced), the
diagnostics and gates over its metrics (one drift diagnostic each), and its test types by setting; the calibration packages are
type_cards/calibration.py and the references type_cards/references.py, every one checked by type_cards/check_references.py.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import coverage as cov
from . import schema
from .schema import (DRIFT_MESSAGE, DRIFT_THRESHOLD, KINDS, OUT_OF_COVERAGE, ROLES, SCHEMA, SETTINGS, TWINNED_LIMIT, WEAR_LAWS,  # noqa: F401
                     Architecture, CalibrationPackage, CodeHome, CoverageNeed, Diagnostic, DriftResult, Forecast, Gate, Limit, Reference,
                     Rung, RungScore, TestType, Wear, coverage_flag, drift_check, mlp_weights, usage_remaining, wear_usage_at, wear_value)

REPO = Path(__file__).resolve().parents[1]
ROBOTDX_REPO = Path("/home/bam/io-diagnostics")
ROBOTDX_COMMIT = "58644fb"  # io-diagnostics main, 2026-11-04: the catalog every metric id is checked against
ROBOTPARTS_REPO = Path("/home/bam/robotparts")  # main 06795ab: models/actuator/*, lab/models/actuator/twin (robotparts/2.5)
DATA_UI_REPO = Path("/home/bam/data-ui")
RACK_TWIN = "bam_ws main b5600075, src/dev/bam_rack_twin"


def data_ui_commit() -> str:
    """The data-ui commit sim2real vendors (vendor/data-ui/VENDOR.md's Source line)."""
    text = (REPO / "vendor" / "data-ui" / "VENDOR.md").read_text()
    return re.search(r"\*\*Source:\*\*.*?@ `([0-9a-f]+)`", text).group(1)


def robotdx_catalog():
    """RobotDx's stock catalog module at ROBOTDX_COMMIT, read from git (stdlib dataclasses only)."""
    cached = sys.modules.get("_robotdx_catalog_pinned")
    if cached:
        return cached
    source = subprocess.run(["git", "-C", str(ROBOTDX_REPO), "show", f"{ROBOTDX_COMMIT}:robotdx/diagnostics/catalog.py"],
                            check=True, capture_output=True, text=True).stdout
    spec = importlib.util.spec_from_loader("_robotdx_catalog_pinned", loader=None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(source, f"robotdx@{ROBOTDX_COMMIT}/catalog.py", "exec"), module.__dict__)
    return module


# --- the card's parts --------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Metric:
    id: str
    family: str          # performance | fidelity
    title: str
    defined_on: str      # the inputs and outputs it is computed from (never an internal)
    unit: str
    robotdx: str | None  # the RobotDx catalog entry id it is, or None
    proposed: str = ""   # why it is proposed (no RobotDx entry yet), when robotdx is None
    normalised: str = "" # how it is divided by the repeatability floor, or why it cannot be
    gate: str = ""       # the bam_rack_twin acceptance gate it feeds (T1-T11), where one exists
    today: bool = True   # measurable on today's rack


@dataclass(frozen=True)
class Parameter:
    name: str
    unit: str            # "1" for a dimensionless number
    nominal: float | str | None
    source: str          # datasheet / robotparts:<model>.<term> / bam_rack_twin ... / unknown
    identified_by: str   # the experiment that identifies it
    observable: str      # yes | partial | no: can the type's own outputs see it
    note: str = ""
    wear: Wear | None = None  # v2: grows with use (usage, law, rate parameter); None: constant
    role: str = "model"       # v2: model | driver | assembly | config (schema.ROLES)


@dataclass(frozen=True)
class Model:
    name: str
    robotparts: str | None       # the robotparts model kind it is, or None
    proposed: str                # what is missing, when robotparts has none (or what this card adds to it)
    equation: str
    parameters: tuple[Parameter, ...]


@dataclass(frozen=True)
class Axis:
    name: str
    unit: str
    binning: str
    bin_size: float | None = None  # v2: the constant cell width in `unit`; None when log-spaced, set per unit or categorical (see binning)
    marginal: bool = False         # v2: reported beside the headline cells, never folded into them


@dataclass(frozen=True)
class Coverage:
    axes: tuple[Axis, ...]
    rule: str
    measure: Callable
    robotdx: str | None = None   # the RobotDx coverage entry, where one exists
    plan_source: str = ""        # where a planned set comes from today
    gate_pct: float | None = None  # v2: the coverage gate, a plan passes when it visits >= this % of the reachable headline cells


@dataclass(frozen=True)
class View:
    template: str | None         # data-ui gallery/examples/<template> at data_ui_commit()
    panels: tuple[str, ...] = ()
    proposed: str = ""
    site: str = ""               # where sim2real already draws it


@dataclass(frozen=True)
class Observability:
    today: str                   # yes | partial | no, on the One Dof Test Rack
    instruments: tuple[str, ...]
    needs: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class Member:
    card: str
    count: int
    role: str


@dataclass(frozen=True)
class Floor:
    robotdx: str | None
    rule: str


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    artifact: str
    does: str


@dataclass(frozen=True)
class Tool:
    text: str
    status: str  # exists | proposed


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    group: str  # actuator | sensor
    zach: str   # his word for it in the Nov 4 list
    robotdx_part: str | None
    robotdx_gap: str
    inputs: str
    outputs: str
    metrics: tuple[Metric, ...]
    floor: Floor
    model: Model
    coverage: Coverage
    view: View
    observability: Observability
    procedure: dict
    members: tuple[Member, ...] = ()
    error_budget: str = ""
    # v2 (Zach, Nov 5 2026): the ladder of models, the diagnostics and gates over the metrics, and the test types
    rungs: tuple[Rung, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    gates: tuple[Gate, ...] = ()
    tests: tuple[TestType, ...] = ()


# --- the shared procedure ----------------------------------------------------------------------------------------------------

STEPS = (
    Step("describe", "Describe", "description.json", "the unit as built: RobotDescription / joint description, config and firmware hashes, mount"),
    Step("nominal", "Nominal model", "model.nominal.json", "the model with every parameter at its nominal value (datasheet, CAD, robotparts)"),
    Step("schedule", "Schedule (coverage)", "schedule.json", "the planned inputs, train / held-out split, and their coverage % before anything runs"),
    Step("capture", "Capture", "runs/<run>/samples.json", "every planned run recorded real, stamped with the schedule digest and config receipt"),
    Step("identify", "Calibrate / identify", "model.<version>.json", "parameters fitted on the train split only; each with its evidence"),
    Step("held_out", "Held-out score", "scores.json", "every metric on the held-out runs, real and twin, each divided by the floor"),
    Step("gates", "Gates", "acceptance.json", "a verdict per gate against its written limit; the type is twinned when its gates pass"),
)
# WHY one sequence of files (Zach's human-AI parity): any step can be done by a person or an agent, and the next step reads only
# the previous step's file; the same schedule with a new model is a fair comparison.


def P(name, unit, nominal, source, identified_by, observable, note="", wear=None, role="model"):
    return Parameter(name, unit, nominal, source, identified_by, observable, note, wear, role)


def proc(**tools) -> dict:
    """This type's tool per step; a missing step is proposed."""
    out = {}
    for step in STEPS:
        text = tools.get(step.key)
        out[step.key] = Tool(text, "exists") if text and not text.startswith("proposed") else Tool(text or "proposed: no tool yet", "proposed")
    return out


AX_Q = Axis("q", "rad", "12 cells over the joint's range from its origin (the bin size is range / 12, per unit: each station's is on its coverage row)")
AX_QD = Axis("qd", "rad/s", "signed, log-spaced to the speed budget (±1 %, 2.5 %, 5 %, 10 %, 25 %, 50 %, 100 %), a dead cell around 0")
AX_QDD = Axis("qdd", "rad/s²", "signed, log-spaced to the accel envelope (±0.6 %, 2.5 %, 6 %, 19 %, 50 %, 100 %)")
AX_TAU = Axis("load torque", "N·m", "0.25 N·m cells to the torque limit (the planned demand tau_pred); its own marginal", bin_size=0.25, marginal=True)
AX_TEMP = Axis("temperature", "°C", "10 °C bands from 20 to 80 °C; its own marginal (no schedule family varies it yet)", bin_size=10.0, marginal=True)
ACTUATOR_AXES = (AX_Q, AX_QD, AX_QDD, AX_TAU, AX_TEMP)
ACTUATOR_RULE = ("headline: share of the reachable (q, qd, qdd) cells any planned target visits (bam_rack_twin.schedule's rule: a "
                 "cell is reachable when its centre's demand is inside the torque limit and the joint can brake before the range "
                 "ends); load torque and temperature are reported beside it as marginals, never folded in")


def _cam_axes(extra=()):
    return (Axis("distance", "m", "0.1 / 0.3 / 0.6 / 1.2 / 2.5 m edges (log-ish, so no single bin size)"),
            Axis("incidence angle", "°", "0 / 15 / 30 / 45 / 75° from the target normal"),
            Axis("illumination", "lux", "10 / 150 / 600 / 20 000 lux: dim, indoor, bright to daylight"),
            Axis("material", "class", "matte white, black plastic, metal, clear PET, cardboard, film"),
            Axis("exposure", "ms", "0.1 / 3 / 15 / 40 ms")) + tuple(extra)


CAMERA_RULE = "share of the cells of distance × incidence × illumination × material × exposure a planned capture visits; every cell is reachable"


# --- the cards ---------------------------------------------------------------------------------------------------------------

SERVO = Card(
    id="servo", title="Integrated servo", group="actuator", zach="Integrated Servo",
    robotdx_part="servo", robotdx_gap="",
    inputs="position / velocity / torque target, kp / kd scale, feed-forward torque, mode", outputs="output angle and speed (motor encoder through the gear), reported torque (q-current × Kt), temperature, faults",
    metrics=(
        Metric("servo.tracking_rms", "performance", "Tracking error RMS", "output angle vs target angle over a run", "mrad", "servo.tracking_rms",
               normalised="÷ the T1 floor of the same tape: how far from the best the rack can repeat"),
        Metric("servo.stop_error", "performance", "Stop error p90 (at the output)", "output angle vs target at the end of each dwell", "mrad", "servo.stop_error",
               normalised="against the joint's share of the 5 mm tool gate (T4); ÷ floor shown beside", gate="T4"),
        Metric("servo.twin_fidelity", "fidelity", "Twin / floor (position)", "twin output angle vs real output angle on the same held-out targets", "× floor", "servo.twin_fidelity",
               normalised="twin error ÷ the real servo's run-to-run floor; ≤ 1.5× is twinned", gate="T2"),
        Metric("servo.torque_fidelity", "fidelity", "Twin / scatter (torque)", "twin q-current vs real q-current, same input", "× scatter", "servo.torque_fidelity",
               normalised="÷ the run-to-run current scatter", gate="T3"),
        Metric("servo.warm_cold", "fidelity", "Fidelity warm and cold", "T2's ratio on cold and on warm runs, one twin", "× floor", "servo.warm_cold",
               normalised="T2's normalisation at each temperature", gate="T9"),
        Metric("servo.envelope", "fidelity", "Top speed predicted", "predicted vs measured top speed at the bus voltage", "%", "servo.envelope",
               normalised="no floor: % error against the measured speed (its run-to-run spread is < 1 %)", gate="T7"),
        Metric("servo.thermal", "fidelity", "Winding temperature predicted", "model temperature vs a thermocouple on the winding", "°C", "servo.thermal",
               normalised="°C, against the thermocouple's own ±1 °C", gate="T8", today=False),
    ),
    floor=Floor("servo.floor", "median pairwise RMS over ≥ 5 identical repeats of one tape (T1); session or pooled is Zach's open call"),
    model=Model(
        "M*.twin (bam_rack_twin TwinParameters)", "lab/models/actuator/twin (robotparts/2.5)",
        "robotparts' twin terms cover the plant; the drive (torque scale, current loop, delay) and the controller gains are bam_rack_twin's own knobs",
        "J q̈ = τ_motor(τ_cmd, delay, current loop, scale) − τ_r(q, q̇) − G sin(q − q_bottom); τ_r = friction level(v) sign(v) + b v + ripple(r q)",
        (
            P("armature_kg_m2", "kg·m²", 0.12193, "robotparts:lab/models/actuator/twin.armature_kg_m2; CAN 11: twin lugre-d-M1-e37b0e7d", "chirps (or the datasheet)", "yes"),
            P("frictionloss_nm", "N·m", 0.833, "robotparts:lab/models/actuator/twin.frictionloss_nm; CAN 11: model card can11.json (measured Coulomb)", "velocity plateaus, both directions, 6-8 speeds", "yes"),
            P("damping_nm_s_rad", "N·m·s/rad", None, "robotparts:lab/models/actuator/twin.damping_nm_s_rad", "velocity plateaus, both directions, 6-8 speeds", "yes"),
            P("friction_weakening_nm_s_rad", "N·m·s/rad", None, "robotparts:lab/models/actuator/twin.friction_weakening_nm_s_rad", "velocity plateaus", "yes"),
            P("friction_stribeck_drop_nm", "N·m", None, "robotparts:lab/models/actuator/twin.friction_stribeck_drop_nm", "slow plateaus below 0.5 rad/s", "partial", "small next to the floor on the JMC"),
            P("friction_capture_nm", "N·m", None, "robotparts:lab/models/actuator/twin.friction_capture_nm", "stop-and-hold tapes with varied rest", "partial"),
            P("ripple_harmonics", "N·m", None, "robotparts:lab/models/actuator/twin.ripple_harmonics", "a rotor-angle sweep over more than one rotor turn", "yes", "cogging phase drifts ~28° across days (rack-motor-models)"),
            P("backlash_rad", "rad", None, "robotparts:lab/models/actuator/twin.backlash_rad", "full-turn ratio on camera, staircase holds; a clamp for the gap", "no", "encoder-blind: the motor encoder sits before the gear"),
            P("gear_stiffness_nm_rad", "N·m/rad", None, "robotparts:lab/models/actuator/twin.gear_stiffness_nm_rad", "a clamp test (output locked)", "no", "encoder-blind"),
            P("gravity_nm", "N·m", 4.661, "bam_rack_twin TwinParameters.gravity_nm; CAN 11: the pendulum's m g L", "slow sweeps both ways (identify.fit_gravity)", "yes", "the load, not the servo: a rig term",
              role="assembly"),
            P("torque_scale", "1", 1.0, "bam_rack_twin TwinParameters.torque_scale (Kt_true / Kt_board)", "a known mass (T6)", "partial", "needs a weighed mass", role="driver"),
            P("current_loop_hz", "Hz", None, "bam_rack_twin TwinParameters.current_loop_hz", "torque chirp, open loop", "partial", role="driver"),
            P("command_delay_s", "s", None, "bam_rack_twin TwinParameters.command_delay_s", "step targets, cross-correlation of command and current", "yes", role="driver"),
            P("kp_nm_rad", "N·m/rad", 31.831, "the board's config (deployment record), kp × kp_scale", "read from the config receipt", "yes", role="config"),
            P("kd_nm_s_rad", "N·m·s/rad", 0.6366, "the board's config (deployment record), kd × kd_scale", "read from the config receipt", "yes", role="config"),
            P("thermal_r_c", "K/W, s", None, "bam_rack_twin thermal_model (two-node)", "a heating run with a thermocouple (T8)", "no", "needs a thermocouple"),
        )),
    coverage=Coverage(ACTUATOR_AXES, ACTUATOR_RULE, cov.servo_coverage, robotdx="servo.coverage",
                      plan_source="bam_rack_twin.schedule build --can-id N (schedule.json; CAN 11's is in the rack archive)"),
    view=View("robotics-servo-gates", ("Runs", "Playback", "Angle", "Angle error", "Velocity", "Torque", "Angle coverage", "Phase space", "Run checks"),
              site="every rack station's page: Runs (playback), Gates, Why it fails, Coverage, Schedule"),
    observability=Observability("yes", ("moteus motor encoder", "moteus q-current and temperature telemetry", "D405 / D435 + ArUco tag on the output (output truth)"),
                                ("weighed mass (T6)", "thermocouple (T8)", "output clamp (T5)", "output encoder or a camera on tag 7 (CAN 12)"),
                                "the rack is a rig of servos: T1-T4, T7, T9-T11 run today"),
    procedure=proc(describe="bam_rack_twin.schedule describe_station (deployment record)", nominal="bam_rack_twin model_card.py + robotparts lab twin",
                   schedule="bam_rack_twin.schedule build (coverage before running)", capture="bam_rack_twin.hardware session --plan …",
                   identify="bam_rack_twin identify / twin fits (LuGre, integrator, backlash, inertia)", held_out="bam_rack_twin acceptance T2 on the held-out split",
                   gates="bam_rack_twin acceptance.py T1-T11 (+ RobotDx servo.* diagnostics)"),
    members=(Member("motor", 1, "BLDC motor"), Member("driver", 1, "moteus board"), Member("gearbox", 1, "10:1 planetary (JMC) or none (direct drive)"),
             Member("encoder", 1, "the board's rotor encoder")),
    error_budget="its allocation of the 5 mm tool gate at its lever (T4's limit; CAN 11: 3.6 mrad p90)",
)

GEARBOX = Card(
    id="gearbox", title="Gearbox", group="actuator", zach="Gearbox",
    robotdx_part="gearbox", robotdx_gap="RobotDx's gearbox has 6 entries, 3 of them proposed; nothing on efficiency or a twin's transmission",
    inputs="input shaft angle and torque", outputs="output shaft angle and torque",
    metrics=(
        Metric("gearbox.transmission_error", "performance", "Transmission error", "output angle − input angle / N over a slow sweep", "arcmin", "gearbox.transmission_error",
               normalised="÷ the run-to-run spread of the same sweep", today=False),
        Metric("gearbox.lost_motion", "performance", "Lost motion at the output", "output angle at ±3 % rated torque with the input locked (hysteresis loop)", "arcmin", "gearbox.backlash",
               normalised="the loop's CI half-width is the floor (T5: ≤ 2 arcmin)", gate="T5", today=False),
        Metric("gearbox.efficiency", "performance", "Efficiency map", "output power / input power over (speed, torque)", "%", None,
               proposed="no RobotDx entry for efficiency; needs input and output torque (a dyno)", normalised="no floor without a dyno's repeat; % points", today=False),
        Metric("gearbox.twin_transmission", "fidelity", "Twin / floor (transmission)", "twin output angle vs real output angle for the same input angle", "× floor", None,
               proposed="RobotDx has no gearbox fidelity entry; it is stock.fidelity_ratio on the output angle given the input angle",
               normalised="÷ the transmission-error floor", today=False),
    ),
    floor=Floor(None, "proposed: the spread of repeated slow sweeps' transmission error (needs input and output encoders)"),
    model=Model("Gear stage", "models/actuator/datasheet + lab twin backlash terms", "robotparts has the gear's terms only inside the twin; no efficiency model",
                "q_out = q_in / N + lash(τ) + τ / k; τ_out = η N τ_in",
                (
                    P("gear_ratio", "1", 10.0, "robotparts:datasheet.gear_ratio (JMC 60ASM200 + 10:1)", "full-turn ratio on camera", "partial", "seen only with an output camera"),
                    P("backlash_rad", "rad", None, "robotparts:lab/models/actuator/twin.backlash_rad", "clamp test, staircase holds", "no", "needs the output locked or an output encoder"),
                    P("gear_stiffness_nm_rad", "N·m/rad", None, "robotparts:lab/models/actuator/twin.gear_stiffness_nm_rad", "clamp test", "no"),
                    P("output_friction_fraction", "1", None, "robotparts:lab/models/actuator/twin.output_friction_fraction", "plateaus with and without the output", "no"),
                    P("gearbox_input_inertia", "kg·m²", None, "robotparts:datasheet.gearbox_input_inertia", "datasheet", "no"),
                    P("mesh_efficiency_eta", "1", None, "unknown (datasheet often states one point)", "dyno: input and output torque over speed", "no"),
                )),
    coverage=Coverage(ACTUATOR_AXES, ACTUATOR_RULE + " (q, qd, qdd at the output)", cov.actuator_coverage, plan_source="proposed: a dyno schedule; on the rack only through its servo"),
    view=View(None, proposed="no data-ui gearbox template: needs input-vs-output angle, the hysteresis loop (torque vs angle) and an efficiency map"),
    observability=Observability("partial", ("D405 / D435 + ArUco on the output (ratio on camera)",), ("dyno with input and output torque", "output encoder", "output clamp"),
                                "alone it needs a dyno; inside a servo, only ratio (camera) and lost motion (clamp) are visible"),
    procedure=proc(schedule="proposed: a slow-sweep + reversal schedule", identify="bam_ws gear_backlash clamp_test (gap fit)", gates="bam_rack_twin acceptance T5"),
)

MOTOR = Card(
    id="motor", title="Motor", group="actuator", zach="Motor",
    robotdx_part=None, robotdx_gap="RobotDx has no motor type: its Kt, envelope and thermal entries sit under servo",
    inputs="phase voltage / current", outputs="shaft torque and speed, winding temperature",
    metrics=(
        Metric("motor.torque_truth", "performance", "Torque per amp vs calibration", "measured torque per amp vs the board's Kt", "ratio", "servo.torque_truth_kt",
               normalised="ratio; ±5 % band (no floor without a torque sensor's repeat)", today=False),
        Metric("motor.envelope", "performance", "Speed-torque envelope reached", "top speed and torque reached at the bus voltage vs the datasheet curve", "%", "servo.envelope",
               normalised="% of the datasheet curve"),
        Metric("motor.twin_torque", "fidelity", "Twin / floor (shaft torque)", "twin shaft torque vs dyno torque on the same current", "× floor", None,
               proposed="no RobotDx motor entries; stock.fidelity_ratio on torque needs a torque sensor", normalised="÷ the dyno's repeat floor", today=False),
        Metric("motor.winding_temp", "fidelity", "Winding temperature predicted", "model vs thermocouple", "°C", "servo.thermal", normalised="°C against the thermocouple", today=False),
    ),
    floor=Floor(None, "proposed: repeated torque-speed sweeps on a dyno"),
    model=Model("M5.dcmotor", "models/actuator/dcmotor", "robotparts' dcmotor is MuJoCo's DC motor; nothing measured is published for the JMC 60ASM200 (level 1 of 5)",
                "τ = Kt i; V = R i + L di/dt + Ke ω; thermal two-node",
                (
                    P("motorconst", "N·m/A", None, "robotparts:dcmotor.motorconst (datasheet Kt)", "known mass in the servo (T6); dyno", "partial"),
                    P("resistance", "Ω", None, "robotparts:dcmotor.resistance", "measure-only board calibration (moteus_tool --calibrate)", "yes"),
                    P("inductance", "H", None, "robotparts:dcmotor.inductance", "board calibration", "yes"),
                    P("cogging", "N·m", None, "robotparts:dcmotor.cogging", "a rotor-angle sweep", "yes"),
                    P("thermal", "K/W, s", None, "robotparts:dcmotor.thermal", "heating run + thermocouple", "no"),
                    P("rotor_inertia", "kg·m²", None, "robotparts:datasheet.rotor_inertia", "datasheet; chirps reflect it with the gear", "partial"),
                )),
    coverage=Coverage(ACTUATOR_AXES, ACTUATOR_RULE + " (at the shaft)", cov.actuator_coverage, plan_source="proposed: a dyno schedule"),
    view=View("robotics-driver", ("q-axis current i_q", "Board temperature", "Operating map"), site="none yet",
              proposed=""),
    observability=Observability("no", ("moteus calibration (R, L, Kv)",), ("dyno with a torque sensor", "thermocouple"),
                                "alone it needs a dyno; inside the servo only Kt via a known mass"),
    procedure=proc(nominal="robotparts dcmotor + datasheet", identify="moteus_tool --calibrate (R, L, Kv)"),
)

DRIVER = Card(
    id="driver", title="Driver (BLDC board)", group="actuator", zach="Driver",
    robotdx_part="bldc_driver", robotdx_gap="",
    inputs="current / torque command, bus voltage", outputs="phase currents (i_q, i_d), delivered torque, board temperature, faults, telemetry",
    metrics=(
        Metric("driver.current_tracking", "performance", "Current tracking", "i_q vs the commanded i_q", "A RMS", None,
               proposed="RobotDx's driver entries are health (faults, temperature, rate); current tracking is stock.tracking_error on i_q",
               normalised="÷ i_q's run-to-run scatter (T3's scatter)"),
        Metric("driver.saturation", "performance", "Share of rows on the torque cap", "delivered torque vs commanded", "%", "driver.saturation", normalised="a share; no floor"),
        Metric("driver.loop_rate", "performance", "Command / telemetry rate", "achieved rate vs the expected rate", "Hz", "driver.loop_rate", normalised="against the expected rate ±10 %"),
        Metric("driver.twin_current", "fidelity", "Twin / scatter (current)", "twin i_q vs real i_q on the same command", "× scatter", None,
               proposed="stock.model_error on i_q exists as a primitive; no driver entry uses it", normalised="÷ i_q's run-to-run scatter"),
        Metric("driver.twin_board_temp", "fidelity", "Board temperature predicted", "model vs reported board temperature", "°C", None,
               proposed="driver.board_temp is a health box, not a model comparison", normalised="°C"),
    ),
    floor=Floor(None, "proposed: i_q scatter across ≥ 5 repeats of one current command (T3's scatter is the servo-level one)"),
    model=Model("Drive", None, "robotparts has no driver model kind (SCHEMA2: driver ladders are only sketched); the terms are bam_rack_twin's",
                "i_q = LPF(current_loop_hz)[delay(i_cmd)], clamped to the voltage ceiling (V_avail − ω Kt / 1.5) / R",
                (
                    P("current_loop_hz", "Hz", None, "bam_rack_twin TwinParameters.current_loop_hz", "torque chirp", "partial"),
                    P("command_delay_s", "s", None, "bam_rack_twin TwinParameters.command_delay_s", "step commands", "yes"),
                    P("max_voltage_factor", "1", None, "moteus fw max_V_factor (config record)", "read from the config receipt", "yes", role="config"),
                    P("torque_cap_nm", "N·m", 4.0, "the runner's --cap-nm / servo.max_current_A", "config receipt", "yes", role="config"),
                    P("telemetry_rate_hz", "Hz", None, "the host loop (record)", "timestamps", "yes", role="config"),
                    P("board_thermal", "K/W, s", None, "unknown", "heating run", "yes", "the board reports its own temperature"),
                )),
    coverage=Coverage((Axis("current command", "A", "signed, to the current limit (±5, 15, 30, 60, 100 %)"),
                       Axis("speed", "rad/s", "signed rotor speed, to the speed limit"),
                       Axis("bus voltage", "V", "20 / 26 / 32 / 38 / 44 V bands; marginal", bin_size=6.0, marginal=True),
                       Axis("board temperature", "°C", "20 / 40 / 60 / 80 °C; marginal", bin_size=20.0, marginal=True)),
                      "share of the (i_q, speed) operating map's cells visited; bus voltage and temperature as marginals", cov.driver_coverage,
                      plan_source="the servo's schedule, read at the rotor"),
    view=View("robotics-driver-gates", ("Runs", "Playback", "q-axis current i_q", "Bus voltage v_bus", "Board temperature", "Fault", "Operating map")),
    observability=Observability("partial", ("moteus telemetry (i_q, i_d, v_bus, temperature, faults)",), ("current probe or a torque sensor (independent truth)",),
                                "the board reports its own currents: fidelity is against its own sensor, not an independent one"),
    procedure=proc(describe="the deployment record's config receipt", capture="bam_rack_twin.hardware session (telemetry)",
                   gates="RobotDx driver.* diagnostics (tools/diagnostics_run_rack.py)"),
)

ENCODER = Card(
    id="encoder", title="Encoder", group="sensor", zach="(inside the servo)",
    robotdx_part="encoder", robotdx_gap="",
    inputs="true shaft angle", outputs="reported angle, validity flags",
    metrics=(
        Metric("encoder.output_agreement", "performance", "Motor encoder vs output truth", "reported angle (through the ratio) vs the ArUco output angle", "mrad", "encoder.output_agreement",
               normalised="÷ the camera's own tag-angle repeatability"),
        Metric("encoder.homing", "performance", "Homing repeatability", "reported zero across power cycles vs the output truth", "mrad", "encoder.homing", normalised="is itself a floor"),
        Metric("encoder.twin_noise", "fidelity", "Twin noise spectrum", "simulated encoder noise and quantisation vs the real standstill spectrum", "dB", None,
               proposed="RobotDx has encoder.standstill_noise (a box); no model comparison", normalised="÷ the standstill spread"),
    ),
    floor=Floor("encoder.standstill_noise", "the standstill spread"),
    model=Model("Encoder", None, "robotparts has no encoder model", "q_reported = round((q + e(q) + n) / lsb) lsb, delayed",
                (
                    P("counts_per_rev", "1/rev", None, "datasheet (moteus AS5047 14-bit / MA600)", "datasheet", "yes"),
                    P("eccentricity_harmonics", "mrad", None, "unknown", "camera vs encoder over a full turn", "partial"),
                    P("noise_sigma", "mrad", None, "unknown", "standstill capture", "yes"),
                    P("latency_s", "s", None, "unknown", "camera vs encoder cross-correlation", "partial"),
                )),
    coverage=Coverage((Axis("q", "rad", "12 cells over a full turn", bin_size=0.5236), Axis("qd", "rad/s", "signed log-spaced speed (0.01, 0.1, 0.5, 1 of 10 rad/s)")),
                      "share of (angle, speed) cells visited", lambda points: cov.binned([(p["q"], p["qd"]) for p in points],
                      [[-3.1416 + 0.5236 * i for i in range(13)], cov.signed((0.01, 0.1, 0.5, 1.0), 10.0)])),
    view=View("robotics-servo", ("Angle", "Angle error")),
    observability=Observability("partial", ("moteus encoder", "D405 / D435 + ArUco on the output"), ("an output encoder",)),
    procedure=proc(capture="bam_rack_twin.hardware session + camera tag track", identify="bam_rack_twin tag_track / ratio_checks"),
)

ARM_SUB = Card(
    id="arm_subassembly", title="Arm sub-assembly (wrist or arm)", group="actuator", zach="Sub-assembly of robot arm (wrist, or arm)",
    robotdx_part=None, robotdx_gap="RobotDx has arm (2-7+ DOF) but no sub-assembly; its arm.* entries are cited for the sub-assembly's tip",
    inputs="2-3 joint targets", outputs="joint angles, the sub-assembly's tip pose",
    metrics=(
        Metric("sub.tip_error_at_stop", "performance", "Tip error at stop", "tip pose vs commanded at rest", "mm", "arm.tool_error_at_stop", normalised="÷ tip repeatability (ISO 9283 RP)"),
        Metric("sub.path_tracking", "performance", "Tip path error", "tip path vs commanded path", "mm", "arm.path_tracking", normalised="÷ path repeatability (RT)"),
        Metric("sub.twin_fidelity", "fidelity", "Twin / floor (tip)", "twin tip vs real tip on the same joint targets", "× floor", "arm.sim_vs_real", normalised="÷ tip repeatability"),
        Metric("sub.coupling", "fidelity", "Coupling residual", "the twin's joint errors in coupled motion minus the sum of single-joint errors", "mrad", None,
               proposed="no RobotDx entry; the closed-chain / inertial coupling the single servos cannot show", normalised="÷ the joint floors"),
    ),
    floor=Floor(None, "proposed: ISO 9283 RP of the tip over 30 cycles"),
    model=Model("Sub-assembly", None, "composite: its joints' servo twins plus link kinematics and inertias (URDF / CAD); robotparts has no assembly model",
                "tip = FK(q; links); dynamics from the URDF with each joint's servo twin",
                (
                    P("link_lengths", "m", None, "CAD export (cad2robot bundle)", "kinematic calibration (camera)", "partial"),
                    P("joint_offsets", "rad", None, "homing records", "kinematic calibration", "yes"),
                    P("link_inertials", "kg, kg·m²", None, "CAD export", "excitation trajectories", "partial"),
                    P("closure_tolerance", "mm", None, "five-bar geometry (fb_bench)", "loop closure residual", "yes"),
                )),
    coverage=Coverage((Axis("joint space", "rad", "4 cells per joint inside its limits (the bin size is each joint's range / 4)"),
                       Axis("tool pose", "m", "0.1 m voxels over the reach box", bin_size=0.1, marginal=True)),
                      "share of joint cells visited; tool voxels as a marginal", lambda points: cov.arm_coverage(points, ((-1.57, 1.57),) * 3)),
    view=View("robotics-arm", ("Path 3D", "EEF error", "Joint error", "Joint angle", "Reach")),
    observability=Observability("partial", ("fb_bench five-bar (2-DOF, real)", "D405 / D435 + ArUco"), ("a wrist on the rack",)),
    procedure=proc(describe="cad2robot bundle", identify="bam_ws kinematic_calibration (multi-arm study, unmerged)"),
    members=(Member("servo", 3, "a wrist's three joints (a five-bar shoulder is two)"),),
    error_budget="its share of the 5 mm tool gate, split across its joints by lever",
)

ARM = Card(
    id="arm_6dof", title="6-DOF robot arm", group="actuator", zach="6 DOF robot arm",
    robotdx_part="arm", robotdx_gap="",
    inputs="6 joint targets (or a Cartesian path)", outputs="joint angles, tool pose",
    metrics=(
        Metric("arm.tool_error_at_stop", "performance", "Tool error at stop", "tool pose vs commanded at rest", "mm", "arm.tool_error_at_stop", normalised="against the 5 mm tool gate; ÷ RP"),
        Metric("arm.pose_ap_rp", "performance", "ISO 9283 AP / RP", "attained vs commanded poses, 5 poses × 30 cycles", "mm", "arm.pose_ap_rp", normalised="RP is the floor"),
        Metric("arm.path_tracking", "performance", "Path tracking error", "tool path vs commanded path", "mm", "arm.path_tracking", normalised="÷ RT"),
        Metric("arm.completion_time", "performance", "Completion time accuracy", "planned vs actual time of a move", "%", "arm.completion_time", normalised="% of the plan"),
        Metric("arm.sim_vs_real", "fidelity", "Arm twin / floor", "twin tool pose vs real tool pose on the same targets", "× floor", "arm.sim_vs_real", normalised="÷ RP; ≤ 1.5×"),
    ),
    floor=Floor(None, "ISO 9283 RP (l̄ + 3 S_l) of the tool (stock.pose_accuracy computes it)"),
    model=Model("Arm", None, "composite: six servo twins + the kinematic chain; robotparts has no arm model kind (MJCF assets only)",
                "tool = FK(q + δq; DH + δDH) · tool frame; joints are servo twins",
                (
                    P("dh_errors", "m, rad", None, "UR5e URDF nominal (Menagerie)", "multi-arm kinematic calibration (58-parameter chain)", "partial"),
                    P("joint_zero_offsets", "rad", None, "homing records", "kinematic calibration", "yes"),
                    P("joint_compliance", "rad/N·m", None, "unknown", "loaded poses", "partial"),
                    P("base_frame", "m, rad", None, "the cell's layout", "camera on base tags", "yes", role="assembly"),
                    P("tool_frame", "m, rad", None, "the gripper's CAD", "tool-flange tag", "yes", role="assembly"),
                    P("link_inertials", "kg, kg·m²", None, "URDF", "excitation trajectories", "partial"),
                )),
    coverage=Coverage((Axis("joint space", "rad", "4 cells per joint inside its limits (4096 cells; the bin size is each joint's range / 4)"),
                       Axis("tool pose", "m", "0.1 m voxels over the 850 mm reach box", bin_size=0.1, marginal=True),
                       Axis("payload", "kg", "0 / 1 / 3 / 5 kg (unplanned yet)", marginal=True)),
                      "share of the joint cube's cells visited; tool voxels and payload as marginals", cov.arm_coverage, robotdx="arm.workspace_coverage"),
    view=View("robotics-arm-gates", ("Path 3D", "Path top", "EEF error", "Joint error", "Coverage", "Reach", "Joint range")),
    observability=Observability("no", ("none on the rack: the UR5e is sim only",), ("a real 6-DOF arm", "tool-flange tag + calibrated cameras")),
    procedure=proc(identify="proposed: kinematic calibration (study on claude/kinematic-calibration-multi-arm-4645cc)"),
    members=(Member("servo", 6, "joints 1-6"),),
    error_budget="5 mm at the tool (Zach to confirm 5 vs 1 mm), allocated to the joints by lever: each joint's T4 limit",
)

ARM_GRIPPER = Card(
    id="arm_6dof_gripper", title="6-DOF arm + gripper", group="actuator", zach="6 DOF robot arm + gripper",
    robotdx_part="arm_gripper", robotdx_gap="",
    inputs="a pick: object pose, grasp target", outputs="picked or not, tool pose at the grasp, time",
    metrics=(
        Metric("pick.grasp_pose_error", "performance", "Tool error at the grasp", "tool pose at closing vs the planned grasp", "mm", "pick.grasp_pose_error", normalised="÷ RP"),
        Metric("pick.sppm", "performance", "Successful picks per minute", "successes per minute vs the plan", "1/min", "pick.sppm", normalised="Wilson interval, no floor"),
        Metric("pick.sim_vs_real", "fidelity", "Pick outcome agreement", "sim success vs real success on the same scenes", "%", None,
               proposed="RobotDx's pick.vs_human compares with a human, not with the twin; this is stock.agreement on outcomes", normalised="against the real success rate's interval"),
        Metric("pick.twin_grasp_fidelity", "fidelity", "Twin / floor (grasp pose)", "twin tool pose at closing vs the real one on the same scene and targets", "× floor", None,
               proposed="stock.fidelity_ratio on the grasp pose; RobotDx's pick entries compare with a human or the plan, not a twin",
               normalised="÷ RP at the grasp; <= 1.5× is twinned (the drift diagnostic divides this one: it grows when the twin gets worse)", today=False),
    ),
    floor=Floor(None, "the real pick rate's own Wilson interval over repeated scenes"),
    model=Model("Arm + gripper", None, "composite: the arm card + a gripper (RobotDx part type `gripper`, no card yet) + contact",
                "pick = arm(path) ∘ gripper(width, force) ∘ contact(μ, object)",
                (
                    P("tcp_offset", "m", None, "the gripper's CAD", "tool-flange tag", "yes"),
                    P("finger_width_map", "m", None, "gripper datasheet", "open / close cycles", "yes"),
                    P("grip_force_map", "N", None, "unknown", "force gauge in the jaws", "no"),
                    P("contact_friction", "1", None, "unknown", "pull-out tests per material", "partial"),
                )),
    coverage=Coverage((Axis("joint space", "rad", "as the arm: 4 cells per joint inside its limits"), Axis("tool pose", "m", "as the arm: 0.1 m voxels", bin_size=0.1, marginal=True),
                       Axis("payload", "kg", "object mass classes", marginal=True)),
                      "the arm's coverage at the grasp poses; object classes as a marginal (proposed)", cov.arm_coverage),
    view=View("robotics-arm-gripper-gates", ("EEF z", "Gripper width", "Grip width at grasp", "Grip force", "Tool path 3D")),
    observability=Observability("no", ("none: sim only",), ("a real arm + gripper", "scene set with known objects")),
    procedure=proc(),
    members=(Member("arm_6dof", 1, "the arm"), Member("gripper", 1, "RobotDx part type gripper (no card yet)")),
    error_budget="the grasp tolerance of the object class; the arm's 5 mm tool gate inside it",
)

CAMERA_RGB = Card(
    id="camera_rgb", title="RGB camera", group="sensor", zach="RGB Camera",
    robotdx_part="camera_rgb", robotdx_gap="",
    inputs="a scene: targets, light, exposure", outputs="images with stamps",
    metrics=(
        Metric("camera.tag_detect", "performance", "Tag detection rate", "tags detected vs tags in view", "%", "camera.tag_detect", normalised="Wilson interval"),
        Metric("camera.frame_rate", "performance", "Frame rate and drops", "achieved vs set frame rate", "Hz", "camera.frame_rate", normalised="±10 % of the set rate"),
        Metric("camera.latency", "performance", "Timestamp delay", "received − exposure stamp", "ms", "camera.latency", normalised="against the loop's budget"),
        Metric("camera.intrinsics", "fidelity", "Reprojection error", "the calibrated camera model's projected corners vs detected corners", "px", "camera.intrinsics",
               normalised="÷ corner-detection jitter on a static target (the floor)"),
        Metric("camera.sim_overlay", "fidelity", "Sim vs real image", "rendered twin image vs the real image of the same scene", "px / SSIM", "camera.sim_overlay", normalised="÷ frame-to-frame difference of a static scene"),
    ),
    floor=Floor(None, "proposed: corner / tag-pose jitter over 100 frames of a static target"),
    model=Model("Pinhole + distortion", None, "robotparts' camera has datasheet keys only (resolution_h, resolution_v, frame_rate_max, shutter); no calibrated camera model kind",
                "p = K [R | t] X, distorted by (k1, k2, p1, p2, k3)",
                (
                    P("fx_fy", "px", None, "the device's factory calibration (librealsense)", "checkerboard / ChArUco calibration", "yes"),
                    P("cx_cy", "px", None, "factory calibration", "calibration", "yes"),
                    P("distortion", "1", None, "factory calibration", "calibration", "yes"),
                    P("extrinsics", "m, rad", None, "rack CAD (D405 at z = 0.881 m)", "tags at known poses", "yes"),
                    P("exposure_response", "DN / (lux·ms)", None, "unknown", "exposure sweep on a grey card", "yes"),
                    P("latency_s", "s", None, "unknown", "LED blink vs stamp", "partial"),
                )),
    coverage=Coverage(_cam_axes(), CAMERA_RULE, cov.condition_coverage(cov.CAMERA_AXES), plan_source="proposed: a capture plan over the conditions"),
    view=View("robotics-camera-gates", ("Sessions", "Playback", "RGB", "Frame interval", "Dropped frames")),
    observability=Observability("yes", ("D405 / D435 colour streams", "ArUco tags on the rack"), ("lights to set illumination", "material swatches")),
    procedure=proc(describe="intel_rgbd sensor contract", capture="bam_rack_twin camera / tag_track", gates="RobotDx camera.* diagnostics"),
)

CAMERA_RGBD = Card(
    id="camera_rgbd", title="RGBD camera", group="sensor", zach="RGBD Camera",
    robotdx_part="camera_rgbd", robotdx_gap="",
    inputs="a scene", outputs="colour and depth images with stamps",
    metrics=(
        Metric("depth.z_accuracy", "performance", "Z accuracy", "depth of a flat target vs its known distance", "% of Z", "depth.z_accuracy", normalised="÷ temporal noise"),
        Metric("depth.plane_rms", "performance", "Plane-fit RMS", "depth points vs the fitted plane", "% of Z", "depth.plane_rms", normalised="÷ temporal noise"),
        Metric("depth.fill_rate", "performance", "Fill rate", "valid depth pixels in the ROI", "%", "depth.fill_rate", normalised="a share"),
        Metric("depth.cloud_vs_sim", "fidelity", "Point cloud vs sim", "twin point cloud vs real cloud of the same scene", "mm", "depth.cloud_vs_sim", normalised="÷ temporal noise (the floor)"),
    ),
    floor=Floor("depth.temporal_noise", "per-pixel depth std over 40 frames of a static flat target"),
    model=Model("Stereo depth", None, "robotparts has no depth model; the twin's depth noise is not modelled yet",
                "z = f b / d, σ_z = z² σ_d / (f b); RGB terms from camera_rgb",
                (
                    P("baseline_m", "m", None, "datasheet / factory calibration", "factory", "yes"),
                    P("depth_scale", "m/unit", None, "per frame (librealsense)", "read per frame", "yes"),
                    P("subpixel_sigma", "px", None, "unknown", "flat-target noise vs distance", "yes"),
                    P("depth_to_color", "m, rad", None, "factory calibration", "factory", "yes"),
                )),
    coverage=Coverage(_cam_axes(), CAMERA_RULE, cov.condition_coverage(cov.CAMERA_AXES), plan_source="proposed: a flat-target capture plan"),
    view=View("robotics-camera-gates", ("Sessions", "RGB", "Depth", "Frame interval")),
    observability=Observability("yes", ("D405 / D435 depth",), ("a flat target at measured distances", "lights")),
    procedure=proc(describe="intel_rgbd sensor contract", gates="RobotDx depth.* diagnostics"),
    members=(Member("camera_rgb", 1, "its colour stream"),),
)

CAMERA_HSI = Card(
    id="camera_hsi", title="Hyperspectral camera", group="sensor", zach="Hyperspectral Camera",
    robotdx_part="camera_hsi", robotdx_gap="RobotDx's 5 camera_hsi entries are all proposed",
    inputs="a scene under known light, white / dark references", outputs="reflectance cubes",
    metrics=(
        Metric("hsi.snr", "performance", "SNR per band", "repeated cubes of a uniform target", "dB", "hsi.snr", normalised="is the floor's inverse", today=False),
        Metric("hsi.smile_keystone", "performance", "Smile and keystone", "bar targets' spectral and spatial misregistration", "px", "hsi.smile_keystone", normalised="÷ the detector pitch", today=False),
        Metric("hsi.spectral_angle", "performance", "Spectral angle vs library", "measured reflectance vs a reference library spectrum", "rad", "hsi.spectral_angle", normalised="÷ the angle between repeat cubes", today=False),
        Metric("hsi.twin_cube", "fidelity", "Twin cube vs real cube", "spectral angle between the rendered and the real cube of one material", "rad", None,
               proposed="no RobotDx HSI fidelity entry; stock.spectral_angle between twin and real", normalised="÷ the repeat-cube angle", today=False),
    ),
    floor=Floor(None, "spectral angle between repeated cubes of one target"),
    model=Model("Line-scan spectral", None, "robotparts has no spectral model", "R(λ) = (DN − dark) / (white − dark), per band with its centre and width",
                (
                    P("band_centres", "nm", None, "vendor calibration", "spectral lamp lines", "yes"),
                    P("band_fwhm", "nm", None, "vendor calibration", "lamp lines", "partial"),
                    P("smile_keystone_map", "px", None, "unknown", "bar targets", "yes", "the distortion map the cube is resampled with"),
                    P("dark_white_refs", "DN", None, "per session", "reference captures", "yes"),
                )),
    coverage=Coverage(_cam_axes((Axis("wavelength band", "band", "VIS / red edge / SWIR (categorical)"), Axis("material class", "class", "PET, HDPE, PP, PS, PVC, paper, organic, metal, glass (categorical)"))),
                      CAMERA_RULE + " × wavelength band × material class", cov.condition_coverage(cov.HSI_AXES)),
    view=View("robotics-camera", ("Sessions", "Hyperspectral band")),
    observability=Observability("no", ("none on the rack",), ("the hyperspectral camera (Windows-only driver today)", "a reference library and lamp")),
    procedure=proc(),
)


CONVEYOR = Card(
    # WHY a card (the coordinator, 2026-11-05): Zach's landing-page examples include a conveyor belt and two UR arms over one
    id="conveyor", title="Conveyor belt", group="actuator", zach="A conveyor belt (Nov 5, the landing-page examples)",
    robotdx_part=None, robotdx_gap="RobotDx has no conveyor part type: its PARTS stop at servo, driver, gearbox, encoder, cameras, IMU, F/T, gripper and arm; the belt is only a frame in arm.path_tracking",
    inputs="belt speed or position command (motor through a gearbox and a drum)", outputs="belt position and speed (motor encoder through the drum), motor current; a tracked object's position on the belt (camera)",
    metrics=(
        Metric("conveyor.speed_tracking", "performance", "Belt speed tracking", "belt speed vs the commanded speed", "m/s RMS", None,
               proposed="RobotDx has no conveyor entries; it is stock.tracking_error on belt speed", normalised="÷ the run-to-run speed scatter of one profile", today=False),
        Metric("conveyor.object_position", "performance", "Object position along the belt", "a tracked object's camera position vs where the encoder says it is after travel", "mm", None,
               proposed="no RobotDx entry; stock.agreement between a camera track and the encoder-integrated position", normalised="÷ the camera's tag-position repeatability", today=False),
        Metric("conveyor.twin_fidelity", "fidelity", "Twin / floor (belt position)", "twin belt position vs real on the same command", "× floor", None,
               proposed="stock.fidelity_ratio on belt position; no conveyor entry", normalised="÷ the belt's run-to-run floor; <= 1.5× is twinned", today=False),
        Metric("conveyor.slip", "fidelity", "Slip and stretch predicted", "twin vs real object displacement per metre of drum travel", "mm/m", None,
               proposed="no RobotDx entry: the drum encoder cannot see slip, a camera on the belt can", normalised="÷ the camera floor per metre", today=False),
    ),
    floor=Floor(None, "proposed: belt position repeatability over >= 5 identical speed profiles (encoder) and the camera's tag repeatability"),
    model=Model("Belt as a linear axis", None,
                "robotparts has no conveyor model; pidtuna's conveyor plant (src/pidtuna/plants/conveyor_truths.py) is the stock one: belt, drum and reflected rotor mass, Coulomb, viscous and static friction, belt stretch",
                "(m + m_load) ẍ_load = k (x_drum − x_load) + c (ẋ_drum − ẋ_load) − F_f(ẋ); m_drum ẍ_drum = N τ_motor / r − k (x_drum − x_load) − c (ẋ_drum − ẋ_load)",
                (
                    P("drum_radius_m", "m", 0.05, "pidtuna conveyor_truths.DRUM_RADIUS_M (a 50 mm drum)", "a tag carried one metre: drum turns vs camera distance", "partial"),
                    P("gear_ratio", "1", 10.0, "pidtuna conveyor_truths.GEAR", "datasheet; drum turns vs motor turns", "partial"),
                    P("moving_mass_kg", "kg", 10.3, "pidtuna conveyor_truths.NOMINAL_KG (belt 8 + drum 1.5 + reflected rotor 0.8)", "speed steps", "yes"),
                    P("load_mass_kg", "kg", None, "the parcels on the belt: the deployment's", "speed steps with and without load", "yes", role="assembly"),
                    P("encoder_counts_per_m", "1/m", 521527, "pidtuna conveyor_truths.COUNTS_PER_M (2^14 counts x 10 / (2 pi x 0.05 m))", "read from the drive's configuration", "yes", role="config"),
                    P("coulomb_n", "N", 25.0, "pidtuna conveyor nominal (datasheet friction)", "velocity plateaus both ways", "yes"),
                    P("viscous_n_s_m", "N·s/m", 20.0, "pidtuna conveyor nominal", "velocity plateaus", "yes"),
                    P("static_n", "N", None, "unknown (pidtuna's hidden truth uses 45 N)", "slow plateaus: breakaway", "partial"),
                    P("stretch_stiffness_n_m", "N/m", None, "unknown (pidtuna's hidden truth uses 2.5e4 N/m)", "speed steps with a camera on a belt tag", "partial",
                      "the encoder is on the drum: stretch shows only on the camera"),
                    P("stretch_damping_n_s_m", "N·s/m", None, "unknown (pidtuna's hidden truth uses 60 N·s/m)", "speed steps with a camera on a belt tag", "partial"),
                )),
    coverage=Coverage((Axis("belt speed", "m/s", "signed, 5 cells each way to the speed limit (5, 15, 30, 60, 100 %)"),
                       Axis("load mass", "kg", "0 / 5 / 10 / 15 / 20 / 30 kg"),
                       Axis("position", "m", "0.25 m cells along the belt", bin_size=0.25, marginal=True),
                       Axis("acceleration", "m/s²", "signed, to the accel limit; marginal", marginal=True)),
                      "share of the (belt speed, load mass) cells visited; position along the belt and acceleration as marginals", cov.conveyor_coverage,
                      plan_source="proposed: a conveyor schedule (pidtuna's plant runs it in sim)"),
    view=View(None, proposed="no data-ui conveyor template: needs belt position and speed vs command, a tracked object's error along the belt, and slip per metre"),
    observability=Observability("no", ("none on the rack: pidtuna's conveyor plant is sim only",), ("a conveyor with a drum encoder", "a camera over the belt with tags on it")),
    procedure=proc(nominal="pidtuna plants/conveyor_truths.py (the description's nominal model)", identify="pidtuna identify.py (a linear axis: mass, Coulomb, viscous)"),
    members=(Member("motor", 1, "the drive motor"), Member("gearbox", 1, "10:1 gearbox"), Member("driver", 1, "the motor's driver"),
             Member("encoder", 1, "the motor encoder: belt position through the drum")),
    error_budget="the pick's tolerance along the belt at the arm's reach: the arm's 5 mm tool gate",
)

ORDER = ("gearbox", "driver", "motor", "servo", "arm_subassembly", "arm_6dof", "arm_6dof_gripper", "conveyor", "camera_rgb", "camera_rgbd", "camera_hsi", "encoder")
CARDS: dict[str, Card] = {c.id: c for c in sorted((GEARBOX, DRIVER, MOTOR, SERVO, ARM_SUB, ARM, ARM_GRIPPER, CONVEYOR, CAMERA_RGB, CAMERA_RGBD, CAMERA_HSI, ENCODER),
                                                   key=lambda c: ORDER.index(c.id))}


def gaps() -> list[tuple[str, str, str]]:
    """(repo, card, what it would need), generated from the proposals."""
    out = []
    for card in CARDS.values():
        if card.robotdx_gap:
            out.append(("RobotDx", card.id, card.robotdx_gap))
        for m in card.metrics:
            if m.robotdx is None:
                out.append(("RobotDx", card.id, f"{m.title}: {m.proposed}"))
        if not card.model.robotparts:
            out.append(("robotparts", card.id, card.model.proposed))
        if not card.view.template:
            out.append(("data-ui", card.id, card.view.proposed))
    return out


# --- v2: the API lanes code against (type_cards/CONTRACT.md) -------------------------------------------------------------------

from . import calibration as _calibration  # noqa: E402
from . import ladders as _ladders  # noqa: E402
from . import references as _references  # noqa: E402

# Zach's calibration packages (PROJECT - Sim2Real, Nov 5 2026): type_cards/calibration.py
CALIBRATION_PACKAGES: tuple[CalibrationPackage, ...] = _calibration.PACKAGES
# each wear law's references (real, citable): type_cards/references.py
WEAR_LAW_REFERENCES: dict[str, tuple[Reference, ...]] = _references.WEAR_LAW_REFERENCES

# The v1 cards as written above; CARDS becomes them with their v2 content (type_cards/ladders.py). The module-level card names
# follow, so reg.SERVO is reg.CARDS["servo"].
V1_CARDS: dict[str, Card] = CARDS
CARDS = _ladders.build(sys.modules[__name__])
GEARBOX, DRIVER, MOTOR, SERVO, ARM_SUB, ARM, ARM_GRIPPER, CONVEYOR, CAMERA_RGB, CAMERA_RGBD, CAMERA_HSI, ENCODER = (CARDS[k] for k in (
    "gearbox", "driver", "motor", "servo", "arm_subassembly", "arm_6dof", "arm_6dof_gripper", "conveyor", "camera_rgb", "camera_rgbd", "camera_hsi", "encoder"))

SELECTION_RULE = ("pick the lowest rung, in ladder order, whose held-out fidelity reaches the floor (held-out error ÷ the floor <= "
                  f"{TWINNED_LIMIT:g}×); a residual or learned rung is judged only on held-out data inside its covered cells, and "
                  f"held-out samples outside them are flagged '{OUT_OF_COVERAGE}', never scored")


def _card(card: Card | str) -> Card:
    return CARDS[card] if isinstance(card, str) else card


def rungs(card: Card | str) -> tuple[Rung, ...]:
    """A card's ladder, lowest first (physics, then the wear variant, then residual and learned)."""
    return _card(card).rungs


def rung(card: Card | str, key: str) -> Rung:
    for r in _card(card).rungs:
        if r.key == key:
            return r
    raise KeyError(f"{_card(card).id} has no rung {key!r} (it has {[r.key for r in _card(card).rungs]})")


def current_rung(card: Card | str) -> Rung | None:
    """The rung that equals the card's `model` (today's single model); None while a card has no ladder."""
    return next((r for r in _card(card).rungs if r.current), None)


def added(card: Card | str, key: str) -> tuple[Parameter, ...]:
    """The named parameters `key` adds over the rung below it (a learned rung adds none: its size is its weights)."""
    ladder = _card(card).rungs
    i = [r.key for r in ladder].index(key)
    below = set(ladder[i - 1].parameter_names) if i else set()
    return tuple(p for p in ladder[i].parameters if p.name not in below)


def select_rung(card_or_ladder, held_out, limit: float = TWINNED_LIMIT) -> Rung | None:
    """SELECTION_RULE over a card (or a card id, or a ladder of rungs): see schema.select."""
    ladder = card_or_ladder if isinstance(card_or_ladder, (tuple, list)) else _card(card_or_ladder).rungs
    return schema.select(ladder, held_out, limit)


def drift_diagnostic(card: Card | str) -> Diagnostic | None:
    return next((d for d in _card(card).diagnostics if d.kind == "drift"), None)


def check_drift(card: Card | str, live: float, calibrated: float, threshold: float | None = None, history=None) -> DriftResult:
    """The card's drift diagnostic on live data (DRIFT_MESSAGE past the threshold; `threshold` overrides the card's)."""
    dx = drift_diagnostic(card)
    if dx is None:
        raise KeyError(f"{_card(card).id} has no drift diagnostic")
    return drift_check(dx, live, calibrated, threshold, history)


def metric_status(card: Card | str, metric_id: str) -> str:
    """'gated' when a gate's diagnostic reads the metric, else 'observed' (Zach: "if not gated then we just observe it")."""
    c = _card(card)
    reads = {d.id: d.metric for d in c.diagnostics}
    return "gated" if any(reads.get(g.diagnostic) == metric_id for g in c.gates) else "observed"


def gate_status(gate: Gate, value: float | None, limit: float | None = None) -> str:
    """pass | fail against the gate's target, not_run without a value; `limit` supplies a per-unit target (Limit.value None)."""
    return "not_run" if value is None else ("pass" if gate.target.ok(value, limit) else "fail")


def coverage_gate(card: Card | str, result) -> str:
    """pass | fail against the card's coverage gate (>= gate_pct % of the reachable headline cells), observed when it has none."""
    gate = _card(card).coverage.gate_pct
    return "observed" if gate is None else ("pass" if result.pct >= gate else "fail")


def tests_for(card: Card | str, setting: str | None = None) -> tuple[TestType, ...]:
    if setting is not None and setting not in SETTINGS:
        raise ValueError(f"setting {setting!r} is not one of {sorted(SETTINGS)}")
    return tuple(t for t in _card(card).tests if setting is None or t.setting == setting)


def packages_for(card: Card | str) -> tuple[CalibrationPackage, ...]:
    cid = _card(card).id
    return tuple(p for p in CALIBRATION_PACKAGES if cid in p.serves)


ALIASES = {
    "integrated servo": "servo", "integrated_servo": "servo", "joint": "servo", "bldc_driver": "driver", "driver board": "driver",
    "bldc driver": "driver", "moteus": "driver", "rgb": "camera_rgb", "rgb camera": "camera_rgb", "rgbd": "camera_rgbd",
    "rgbd camera": "camera_rgbd", "depth camera": "camera_rgbd", "d405": "camera_rgbd", "d435": "camera_rgbd", "hsi": "camera_hsi",
    "hyperspectral": "camera_hsi", "hyperspectral camera": "camera_hsi", "arm": "arm_6dof", "6 dof robot arm": "arm_6dof", "ur5e": "arm_6dof",
    "arm_gripper": "arm_6dof_gripper", "arm + gripper": "arm_6dof_gripper", "wrist": "arm_subassembly", "sub-assembly": "arm_subassembly",
    "conveyor belt": "conveyor", "belt": "conveyor",
}


def _word(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace("_", " ").replace("-", " "))


def card_for(word: str) -> Card | None:
    """The card a description's word names (a card id, its title, Zach's word, its RobotDx part type or an alias), or None."""
    w = _word(word)
    for c in CARDS.values():
        if w in {_word(c.id), _word(c.title), _word(c.zach), _word(c.robotdx_part or "")} - {""}:
            return c
    hit = {_word(k): v for k, v in ALIASES.items()}.get(w)
    return CARDS.get(hit) if hit else None


def _plain(obj):
    """JSON-able: dataclasses as dicts (a Rung and an Architecture with their computed sizes), tuples as lists, callables dropped."""
    from dataclasses import fields, is_dataclass  # noqa: PLC0415
    if is_dataclass(obj):
        out = {f.name: _plain(getattr(obj, f.name)) for f in fields(obj) if not callable(getattr(obj, f.name))}
        if isinstance(obj, Rung):
            out.update(n_parameters=obj.n_parameters, n_named=obj.n_named, parameter_names=list(obj.parameter_names))
        if isinstance(obj, Architecture):
            out.update(n_inputs=obj.n_inputs, weights=obj.weights)
        return out
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


def export() -> dict:
    """The whole registry as JSON-able data (schema SCHEMA), for pages and lanes that do not import Python."""
    cards = []
    for c in CARDS.values():
        d = _plain(c)
        d["metric_status"] = {m.id: metric_status(c, m.id) for m in c.metrics}
        cards.append(d)
    return {"schema": SCHEMA, "settings": dict(SETTINGS), "kinds": list(KINDS), "roles": list(ROLES), "wear_laws": dict(WEAR_LAWS),
            "drift_message": DRIFT_MESSAGE, "drift_threshold": DRIFT_THRESHOLD, "out_of_coverage": OUT_OF_COVERAGE,
            "twinned_limit": TWINNED_LIMIT, "selection_rule": SELECTION_RULE, "steps": _plain(STEPS), "cards": cards,
            "calibration_packages": _plain(CALIBRATION_PACKAGES)}
