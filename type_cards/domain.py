"""Domain model v3: the one contract the page lanes build against (type_cards/CONTRACT.md, "Domain model v3").

Zach, PROJECT - Sim2Real, "Feedback on how it is right now" (2026-11-06): "Ok so certainly one thing that is key are Runs ... So now we
have DEPLOYMENTS and RUNS ... a MODEL is associated with a type ... Rigid Body Chain (ie Robot Arm), Integrated Servo, BLDC Motor,
Gearbox, FOC Controller ... We organize all of the models related to a particular part type into a ladder ... the 6 DOF robot arm is not
a type.. the type here is more generic ... MO.kinematics.X MO.dynamics.X ... definetily you can use a robot arm without a dynamics
model ... CALIBRATION ROUTINE or just ROUTINE ... METRICS ... DIAGONISTICS ... metrics + gate that reports warning or error ...
COVERAGE ... Reports".

One import: `from type_cards import domain as dm`. Stdlib only. What lives here (the type level, and the records every level uses):
- the vocabularies (deployment kinds, model families, excitations, offline scopes, diagnostic levels, tags, structural levels);
- the record classes, frozen and keyword-only (Zach's Python ground truth: one keyword per line, JSON is a projection);
- the entity types, generic (TYPES), each built from the v2 type cards (registry.CARDS) by the migration below, which is the record
  of what every v2 id became: CARD_TYPE, RUNG_MODELS, PARAMETER_MAP, METRIC_MAP, DIAGNOSTIC_MAP;
- the queries a page needs at the type level, and export() (type_cards/domain_v3.json, committed; `python3 -m type_cards.domain --write`).
Deployments, runs and the parameters table are type_cards/instances.py; metrics, diagnostics and coverage over any runs are
type_cards/selection.py; frozen reports are type_cards/report.py. The decision: docs/decision-domain-model-v3-2026-11-07.md.

WHY built from the v2 cards and not authored again (the barrier lane's brief: "Keep a mapping from old ids so nothing breaks"): every
equation, reference, note and number of the v2 ladders carries over untouched, v2 stays the API sysid and the type pages read
(`reg.CARDS`, CONTRACT "Rules of the road": additive only), and the map below is the one place a reviewer reads what moved.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Literal, Mapping

from . import registry as reg
from .schema import DRIFT_MESSAGE, Architecture, CoverageNeed, Gate, Limit, Reference, Wear

SCHEMA = "sim2real.domain/3"
DOMAIN_JSON = Path(__file__).resolve().parent / "domain_v3.json"

# --- vocabularies -------------------------------------------------------------------------------------------------------------------

# WHY "virtual" and "physical" (Zach: "Each deployment can be like virtual or like actuall physical (I am not sure what the right words
# to use here is I will leave that up to you)"): his own words, and the digital-twin literature's pair (Grieves: the physical product in
# real space, its virtual twin in virtual space). "real" and "sim" are taken: a run's `environment` already says real (a segment of live
# deployed data) and its `basis` sim, so neither may also name what a deployment is.
DEPLOYMENT_KINDS = {
    "virtual": "exists only in simulation: a robot description and a simulator play the hardware (the system-ID oracle's examples)",
    "physical": "hardware that exists: its runs are recordings of it (the One Dof Test Rack; the arms when they are built)",
}
# WHY families (Zach: "MO.kinematics.X MO.dynamics.X ... You can add like a family of models to make that clearer ... definetily you can
# use a robot arm without a dynamics model"): a family is the part of a type's model one can use without the rest; its layers count
# from M0 on their own.
FAMILIES = {
    "kinematics": "where the parts are: frames, link geometry, joint zeros, transmission ratios, with no force in it",
    "dynamics": "how it moves under commands and loads: inertia, friction, compliance, backlash, the drive, heat",
    "measurement": "how a sensor turns the world into readings: quantisation, noise, latency, projection, depth, spectral response",
}
# WHY tagged (Zach: "all runs should be tagged with the current configuration values and also like if its just natural response or
# driven ... action free response is helpful. so you can just see how it acts without actuation which will always be the same")
EXCITATIONS = {
    "driven": "a command moved it for the whole run (position, velocity or current targets)",
    "free response": "no command acted: it moved (or cooled) on its own, so its data does not depend on the controller",
    "mixed": "a driven segment, then a free one: a swing released to coast; a heating run, then its cool-down with the bridge off",
    "unknown": "the run's own files do not say",
}
# WHY a scope (Zach: "You cannot do offline evaluation of online robot tracking performance ... (but you can do it of models.) (althought
# be careful... if you have feedback control running on the real robot arm and you change it right. you may get different response")
OFFLINE_SCOPES = {
    "any config": "no command acted: replay it to judge a model under any controller config",
    "any feedback gains": "driven with no feedback acting: the feedback gains do not matter; the drive's own config (current loop, limits) does",
    "its own config": "driven closed loop: judge a model by replaying it with the run's own config (config_sha256, kp / ki / kd); it says "
                      "nothing about tracking under other gains",
    "split": "a driven segment (its own config only), then a free one (any config)",
    "unknown": "neither its excitation nor its loop is known",
}
LEVELS = ("ok", "warning", "error", "unknown")
LEVEL_RANK = {"ok": 0, "warning": 1, "unknown": 2, "error": 4}  # RobotDx's ranks, data-ui's STATUS_ORDER (CONTRACT §35)
# WHY these and no other (the brief: "Specify in the contract how the browser can do the same live (data-ui)"): data-ui's own summaries
# (CONTRACT §16 rollup and summaries), so a cross-run value is the same number in Python at build time and in the browser live.
AGGREGATES = ("median", "mean", "min", "max", "sum", "count")
TAGS = {
    "oracle example": "declared: a system-ID oracle example (sysid/), the description in and a better model out against a hidden truth",
    "uses camera": "derived: a camera of any type (camera, depth_camera, hyperspectral_camera) is in its tree",
    "uses arm": "derived: a rigid body chain is in its tree",
    "uses gripper": "derived: a gripper is in its tree",
    "uses conveyor": "derived: a conveyor is in its tree",
    "uses servo": "derived: an integrated servo is in its tree",
}
TAG_OF_TYPE = {"camera": "uses camera", "depth_camera": "uses camera", "hyperspectral_camera": "uses camera", "rigid_body_chain": "uses arm",
               "gripper": "uses gripper", "conveyor": "uses conveyor", "integrated_servo": "uses servo"}
ESTIMATE_FORMS = {
    "single": "one value: a mean and, where the routine gives one, its 95 % interval (in scope)",
    "configuration_dependent": "reserved: a value that varies with a configuration input (depends_on names it); not in scope yet",
    "network": "reserved: a learned model's output distribution; not in scope yet",
}

# --- records ------------------------------------------------------------------------------------------------------------------------

KW = dict(frozen=True, kw_only=True)


@dataclass(**KW)
class Dashboard:
    """The standard dashboard of one level (Zach: "on the page what shows is the standard dashboard for that level with the data that
    was capture from the run"): a data-ui gallery template and its panels, and the media components scoped to the level's entity
    (site/components.py)."""
    template: str | None
    panels: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    proposed: str = ""


@dataclass(**KW)
class Part:
    """What a composite type is made of (an integrated servo holds a motor, a driver, a gearbox and an encoder)."""
    type: str
    count: int
    role: str


@dataclass(**KW)
class Model:
    """One model on a type's ladder: M<k>.<family>.<name>, k the highest layer of terms it holds (decision-rung-keys), its parameters
    cumulative within its family (a learned model holds none: its size is its weights)."""
    id: str
    type: str
    k: int
    family: str
    name: str
    title: str
    kind: str                                  # physics | residual | learned (reg.KINDS)
    parameters: tuple[str, ...]
    adds: tuple[str, ...] = ()
    base: str = ""                             # a residual's physics model; a wear model's plain one
    wear: bool = False
    current: bool = False                      # part of today's model (the primary card's current rung)
    n_parameters: int = 0
    equation: str = ""
    references: tuple[Reference, ...] = ()
    architecture: Architecture | None = None
    needs: CoverageNeed | None = None
    robotparts: str | None = None
    implemented: str = ""
    legacy: tuple[tuple[str, str], ...] = ()   # the v2 (card, rung key)s whose combination holds it
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.type}/{self.id}"


@dataclass(**KW)
class ParameterSpec:
    """A parameter of a type: its unit, family and the models that hold it. Its values (true, nominal, recovered) are per deployment:
    type_cards/instances.py's parameters table."""
    type: str
    name: str
    unit: str
    family: str
    introduced_in: str
    models: tuple[str, ...]
    nominal: float | str | None
    source: str
    identified_by: str
    observable: str
    role: str = "model"
    wear: Wear | None = None
    legacy: tuple[tuple[str, str], ...] = ()   # the v2 (card, parameter)s it is
    note: str = ""


@dataclass(**KW)
class RunSource:
    """Where one run's value of a metric is read: a runs.json column, or RobotDx's per-run diagnostic rows (run_gates.json), one per
    model when `per_model`, divided by the station's T1 floor when `divide_by` is "floor"."""
    table: Literal["runs", "run_diagnostics"]
    column: str = ""
    diagnostic: str = ""
    per_model: bool = False
    divide_by: str = ""
    note: str = ""


@dataclass(**KW)
class MetricSpec:
    """A black-box metric of a type. `pinned`: one of the few to look at first (Zach: "the most important ones we kinda pin to the
    top"). Performance metrics read the hardware alone; fidelity metrics need a model (twin vs real), so their value is per model."""
    id: str
    type: str
    family: str                                # performance | fidelity
    title: str
    unit: str
    defined_on: str
    pinned: bool = False
    model_dependent: bool = False
    aggregate: str = "median"                  # AGGREGATES: how runs combine
    per_run: RunSource | None = None
    why_not: str = ""                          # why no run gives it yet (per_run None)
    robotdx: str | None = None
    normalised: str = ""
    acceptance: str = ""                       # the bam_rack_twin acceptance gate it feeds (T1-T11)
    today: bool = True
    legacy: tuple[tuple[str, str], ...] = ()


@dataclass(**KW)
class DiagnosticSpec:
    """A metric plus limits that report warning or error (Zach: "metrics + gate that reports warning or error"). `warn` and `error` are
    each the fine side (Limit.ok); a value outside `error` is an error, else outside `warn` a warning. units "metric": the metric's own
    value; "ratio": the metric ÷ its calibrated value (v2's drift); "parameter": a re-identified parameter's growth, in its own units."""
    id: str
    type: str
    metric: str
    title: str
    warn: Limit | None = None
    error: Limit | None = None
    kind: str = "threshold"                    # threshold | drift
    units: str = "metric"                      # metric | ratio | parameter
    parameter: str = ""
    message: str = ""
    baseline: str = ""
    robotdx: str | None = None
    note: str = ""
    legacy: tuple[tuple[str, str], ...] = ()


@dataclass(**KW)
class Dimension:
    name: str
    unit: str
    headline: bool                             # counted in the coverage %; else reported beside it (a marginal)
    bin_size: float | None = None
    binning: str = ""


@dataclass(**KW)
class CoverageSpec:
    type: str
    dimensions: tuple[Dimension, ...]
    rule: str
    gate_pct: float | None
    reachable: str
    from_runs: bool = False                    # selection.compute() computes it over recorded runs today
    why_not: str = ""


@dataclass(**KW)
class EntityType:
    """A generic type (Zach: "the type here is more generic"): never an instance (a UR5e, a D405, CAN 11)."""
    id: str
    title: str
    zach: str
    group: str
    covers: str
    families: tuple[str, ...]
    models: tuple[Model, ...]
    parameters: tuple[ParameterSpec, ...]
    metrics: tuple[MetricSpec, ...]
    diagnostics: tuple[DiagnosticSpec, ...]
    gates: tuple[Gate, ...]
    coverage: CoverageSpec
    dashboard: Dashboard
    members: tuple[Part, ...] = ()
    legacy_cards: tuple[str, ...] = ()
    robotdx_part: str | None = None
    note: str = ""


@dataclass(**KW)
class RunTags:
    excitation: str
    closed_loop: bool | None
    offline_scope: str
    why: str


@dataclass(**KW)
class Estimate:
    """A recovered value. Only single values are in scope (Zach: "for now this table is good for parmaters that have a single true
    value"); the other forms are named so a configuration-dependent or learned output has a place to go."""
    mean: float | None
    ci95: tuple[float, float] | None = None
    interval: str = ""                         # how the interval was made, or why there is none
    form: str = "single"

    def __post_init__(self):
        if self.form not in ESTIMATE_FORMS:
            raise ValueError(f"an estimate's form is one of {list(ESTIMATE_FORMS)}, not {self.form!r}")
        if self.form != "single":
            raise ValueError(f"{self.form!r} is reserved, not in scope yet (ESTIMATE_FORMS)")


@dataclass(**KW)
class CameraDecl:
    """A camera of a physical deployment: its serial, model and type, and the stations (CAN ids) it sees, with where that is written."""
    serial: str
    model: str
    type: str
    sees: tuple[int, ...]
    source: str


@dataclass(**KW)
class ModelLabel:
    """A producer's name for a model it replays on a physical deployment (the words before " vs real" in RobotDx's stock.model_error rows:
    selection.model_label) and the ladder model it instantiates. WHY a record and not a parse (Rules of the road: never parse an id): the
    words are the producer's; which model a twin is was read off the producer's own builds and is written here once, with where its terms
    depart from the ladder model's (`differs`), so a page can name the model and never claim more than the twin holds."""
    label: str                                 # exactly as the producer writes it ("twin of record", "twin A · deployed")
    type: str                                  # the v3 entity type it models
    model: str                                 # the model id on that type's ladder (model(type, model) exists)
    fit: str                                   # what set its values: the round and the runs
    friction: str                              # its friction law in words (the ladder's M3 form is Stribeck, weakening and capture)
    differs: str = ""                          # where its terms depart from the ladder model's, as the producer's builds show
    source: str = ""                           # where the producer builds it (bam_ws file and function)


@dataclass(**KW)
class PhysicalDeployment:
    """The v3 part of a physical deployment's record (type_cards/deployments/<id>.py, one per file). Its producer fields (archive days,
    the bam_rack_twin record, the schedule index) stay in app/registry.json, where the producer lanes keep them."""
    id: str
    tags: tuple[str, ...] = ()
    cameras: tuple[CameraDecl, ...] = ()
    note: str = ""
    models: tuple[ModelLabel, ...] = ()        # its producer's model labels and the ladder model each is (2026-11-07, additive)


# --- the migration from the v2 cards --------------------------------------------------------------------------------------------------

TYPE_ORDER = ("rigid_body_chain", "integrated_servo", "bldc_motor", "gearbox", "foc_controller", "encoder", "gripper", "conveyor", "camera",
              "depth_camera", "hyperspectral_camera")
META = {  # title, Zach's word, what it covers, its v2 cards (the primary first), its families
    "rigid_body_chain": ("Rigid Body Chain", "Rigid Body Chain (ie Robot Arm)", "any chain of rigid links and joints, open or closed: a "
                         "6-DOF arm, a wrist, a five-bar shoulder", ("arm_6dof", "arm_subassembly"), ("kinematics", "dynamics")),
    "integrated_servo": ("Integrated Servo", "Integrated Servo", "a joint: a motor, its driver, a gearbox or none, and an encoder in one",
                         ("servo",), ("dynamics",)),
    "bldc_motor": ("BLDC Motor", "BLDC Motor", "a brushless motor alone, at its shaft", ("motor",), ("dynamics",)),
    "gearbox": ("Gearbox", "Gearbox", "a gear stage between a motor and its load", ("gearbox",), ("dynamics",)),
    "foc_controller": ("FOC Controller", "FOC Controller", "a field-oriented-control motor driver board (a moteus)", ("driver",), ("dynamics",)),
    "encoder": ("Encoder", "Encoder", "an angle sensor (a board's rotor encoder)", ("encoder",), ("measurement",)),
    "gripper": ("Gripper", "Gripper", "an end effector that grasps, on a chain's flange (its TCP, its fingers, its contact)",
                ("arm_6dof_gripper",), ("kinematics", "dynamics")),
    "conveyor": ("Conveyor", "Conveyor", "a belt driven through a drum", ("conveyor",), ("kinematics", "dynamics")),
    "camera": ("Camera", "Camera", "a frame camera's colour image: projection, distortion, exposure", ("camera_rgb",), ("measurement",)),
    "depth_camera": ("Depth Camera", "Camera (RGBD)", "a stereo depth camera: depth on top of a colour stream", ("camera_rgbd",), ("measurement",)),
    "hyperspectral_camera": ("Hyperspectral Camera", "Camera (hyperspectral)", "a line-scan spectral camera over a belt", ("camera_hsi",),
                             ("measurement",)),
}
CARD_TYPE = {card: tid for tid, meta in META.items() for card in meta[3]}

# Single-family types: every v2 rung is one v3 model, the layer number kept (robotparts' actuator layers stay where they were).
SINGLE = {
    "servo": {"M0": "ideal", "M2": "coulomb_viscous", "M3": "stribeck", "M4": "twin", "M5": "electrics", "M5.wear": "wear", "M6": "residual",
              "M7": "network"},
    "motor": {"M0": "ideal", "M4": "cogging", "M5": "electrics", "M5.wear": "wear", "M6": "residual", "M7": "network"},
    "gearbox": {"M0": "ideal", "M3": "load_friction", "M4": "backlash", "M4.wear": "wear", "M6": "residual", "M7": "network"},
    "driver": {"M0": "ideal", "M1": "delay_loop", "M2": "ceiling_heat", "M2.wear": "wear", "M6": "residual", "M7": "network"},
    "encoder": {"M0": "quantiser", "M1": "noise_latency", "M2": "eccentricity", "M2.wear": "wear"},
    "camera_rgb": {"M0": "pinhole", "M1": "distortion", "M2": "exposure_latency", "M3": "rolling_shutter", "M3.wear": "wear", "M6": "residual"},
    "camera_rgbd": {"M0": "stereo", "M1": "disparity_noise", "M2": "depth_bias", "M2.wear": "wear", "M6": "residual"},
    "camera_hsi": {"M0": "bands", "M1": "band_widths", "M2": "smile_keystone", "M3": "pushbroom", "M3.wear": "wear"},
}

# v2 parameter names that change; every other keeps its name on its type
PARAMETER_MAP = {
    ("arm_subassembly", "link_lengths"): "link_geometry",
    ("arm_subassembly", "joint_offsets"): "joint_zero_offsets",
    ("arm_subassembly", "joint_offset_drift_rad_per_sqrt_h"): "joint_zero_drift_rad_per_sqrt_h",
}
# v2 metric and diagnostic ids folded into the primary card's (their RobotDx entries are the same); every other keeps its id
METRIC_MAP = {("arm_subassembly", "sub.tip_error_at_stop"): "arm.tool_error_at_stop", ("arm_subassembly", "sub.path_tracking"): "arm.path_tracking",
              ("arm_subassembly", "sub.twin_fidelity"): "arm.sim_vs_real"}
DIAGNOSTIC_MAP = {("arm_subassembly", "sub.tip_error_at_stop.dx"): "arm.tool_error_at_stop.dx",
                  ("arm_subassembly", "sub.twin_fidelity.dx"): "arm.sim_vs_real.dx", ("arm_subassembly", "arm_subassembly.drift"): "arm_6dof.drift"}

# Two-family types: their models, explicitly (id, title, parameters cumulative in the family, the v2 rung its content comes from, base)
CHAIN_K0 = ("base_frame", "tool_frame", "link_geometry", "closure_tolerance")
CHAIN_K1 = CHAIN_K0 + ("joint_zero_offsets",)
CHAIN_K2 = CHAIN_K1 + ("dh_errors",)
CHAIN_D0 = ("link_inertials",)
CHAIN_D1 = CHAIN_D0 + ("joint_compliance",)
BELT_K0 = ("drum_radius_m", "gear_ratio", "encoder_counts_per_m")
BELT_D0 = ("moving_mass_kg", "load_mass_kg")
BELT_D2 = BELT_D0 + ("coulomb_n", "viscous_n_s_m")
BELT_D3 = BELT_D2 + ("static_n",)
BELT_D4 = BELT_D3 + ("stretch_stiffness_n_m", "stretch_damping_n_s_m")
GRIP_K0 = ("tcp_offset",)
GRIP_D0 = ("finger_width_map",)
GRIP_D1 = GRIP_D0 + ("grip_force_map", "contact_friction")
SPLIT = {
    "rigid_body_chain": (
        ("M0.kinematics.nominal", "Nominal kinematics (the description: URDF, DH or CAD)", CHAIN_K0, ("arm_6dof", "M0"), "",
         "tool = base · FK(q; the description's geometry) · tool frame; a closed chain closes its loop inside FK"),
        ("M1.kinematics.zero_offsets", "+ joint zero offsets", CHAIN_K1, ("arm_6dof", "M1"), "", None),
        ("M2.kinematics.geometric", "+ geometric (DH) errors", CHAIN_K2, ("arm_6dof", "M2"), "", None),
        ("M2.kinematics.wear", "+ joint zeros that drift over vibration hours", CHAIN_K2 + ("joint_zero_drift_rad_per_sqrt_h",),
         ("arm_subassembly", "M2.wear"), "M2.kinematics.geometric", "δq(h) = δq0 + k √h, on M2's FK"),
        ("M0.dynamics.rigid", "Rigid links: the description's link inertials", CHAIN_D0, ("arm_6dof", "M3"), "",
         "τ = M(q) q̈ + C(q, q̇) q̇ + g(q) from the links' inertials; each joint's own dynamics are its integrated servo's ladder"),
        ("M1.dynamics.compliance", "+ joint compliance: the tool deflects under load (today's model, with M2.kinematics)", CHAIN_D1,
         ("arm_6dof", "M3"), "", "δq = C τ_load, τ_load from M0's inertials; tool = FK(q + δq)"),
        ("M1.dynamics.wear", "+ joint compliance that grows with use (Archard)", CHAIN_D1 + ("compliance_wear_per_nm_rev",), ("arm_6dof", "M3.wear"),
         "M1.dynamics.compliance", None),
        ("M6.dynamics.residual", "Grey-box residual on M1.dynamics.wear", CHAIN_D1 + ("compliance_wear_per_nm_rev",), ("arm_6dof", "M6"),
         "M1.dynamics.wear", None),
        ("M7.dynamics.network", "Arm network (black box)", (), ("arm_6dof", "M7"), "", None),
    ),
    "conveyor": (
        ("M0.kinematics.belt", "Belt kinematics: drum radius, gear ratio, encoder counts", BELT_K0, ("conveyor", "M0"), "",
         "x = θ_motor r / N = counts / counts_per_m"),
        ("M0.dynamics.rigid_mass", "A rigid moving mass", BELT_D0, ("conveyor", "M0"), "", "(m + m_load) ẍ = F"),
        ("M2.dynamics.coulomb_viscous", "Coulomb + viscous friction", BELT_D2, ("conveyor", "M2"), "", None),
        ("M3.dynamics.stribeck", "+ static friction (Stribeck)", BELT_D3, ("conveyor", "M3"), "", None),
        ("M4.dynamics.stretch", "+ belt stretch: drum and load as two masses (today's model, with M0.kinematics)", BELT_D4, ("conveyor", "M4"), "", None),
        ("M4.dynamics.wear", "+ friction that grows with belt distance", BELT_D4 + ("coulomb_growth_n_per_km",), ("conveyor", "M4.wear"),
         "M4.dynamics.stretch", None),
        ("M6.dynamics.residual", "Grey-box residual on M4.dynamics.wear", BELT_D4 + ("coulomb_growth_n_per_km",), ("conveyor", "M6"),
         "M4.dynamics.wear", None),
        ("M7.dynamics.network", "Belt network (black box)", (), ("conveyor", "M7"), "", None),
    ),
    "gripper": (
        ("M0.kinematics.tcp", "Rigid gripper: its TCP on the flange", GRIP_K0, ("arm_6dof_gripper", "M0"), "", "tool = flange · tcp_offset"),
        ("M0.dynamics.width_drive", "The finger drive: width against command", GRIP_D0, ("arm_6dof_gripper", "M1"), "", "width = f(command)"),
        ("M1.dynamics.contact", "+ grip force and contact friction (today's model, with M0.kinematics)", GRIP_D1, ("arm_6dof_gripper", "M2"), "",
         "grasp = width_drive(command) ∘ contact(force, μ, object)"),
        ("M1.dynamics.wear", "+ finger pads that glaze with grasps", GRIP_D1 + ("contact_friction_change_per_cycle",), ("arm_6dof_gripper", "M2.wear"),
         "M1.dynamics.contact", None),
        ("M6.dynamics.residual", "Grey-box residual on M1.dynamics.wear", GRIP_D1 + ("contact_friction_change_per_cycle",), ("arm_6dof_gripper", "M6"),
         "M1.dynamics.wear", None),
        ("M7.dynamics.network", "Gripper network (black box)", (), ("arm_6dof_gripper", "M7"), "", None),
    ),
}
RUNG_MODELS_SPLIT = {
    ("arm_6dof", "M0"): ("M0.kinematics.nominal",), ("arm_6dof", "M1"): ("M1.kinematics.zero_offsets",),
    ("arm_6dof", "M2"): ("M2.kinematics.geometric",), ("arm_6dof", "M3"): ("M2.kinematics.geometric", "M1.dynamics.compliance"),
    ("arm_6dof", "M3.wear"): ("M2.kinematics.geometric", "M1.dynamics.wear"), ("arm_6dof", "M6"): ("M2.kinematics.geometric", "M6.dynamics.residual"),
    ("arm_6dof", "M7"): ("M7.dynamics.network",),
    ("arm_subassembly", "M0"): ("M0.kinematics.nominal",), ("arm_subassembly", "M1"): ("M1.kinematics.zero_offsets",),
    ("arm_subassembly", "M2"): ("M1.kinematics.zero_offsets", "M0.dynamics.rigid"),
    ("arm_subassembly", "M2.wear"): ("M2.kinematics.wear", "M0.dynamics.rigid"),
    ("arm_subassembly", "M6"): ("M2.kinematics.wear", "M6.dynamics.residual"), ("arm_subassembly", "M7"): ("M7.dynamics.network",),
    ("conveyor", "M0"): ("M0.kinematics.belt", "M0.dynamics.rigid_mass"), ("conveyor", "M2"): ("M0.kinematics.belt", "M2.dynamics.coulomb_viscous"),
    ("conveyor", "M3"): ("M0.kinematics.belt", "M3.dynamics.stribeck"), ("conveyor", "M4"): ("M0.kinematics.belt", "M4.dynamics.stretch"),
    ("conveyor", "M4.wear"): ("M0.kinematics.belt", "M4.dynamics.wear"), ("conveyor", "M6"): ("M0.kinematics.belt", "M6.dynamics.residual"),
    ("conveyor", "M7"): ("M7.dynamics.network",),
    ("arm_6dof_gripper", "M0"): ("M0.kinematics.tcp",), ("arm_6dof_gripper", "M1"): ("M0.kinematics.tcp", "M0.dynamics.width_drive"),
    ("arm_6dof_gripper", "M2"): ("M0.kinematics.tcp", "M1.dynamics.contact"),
    ("arm_6dof_gripper", "M2.wear"): ("M0.kinematics.tcp", "M1.dynamics.wear"),
    ("arm_6dof_gripper", "M6"): ("M0.kinematics.tcp", "M6.dynamics.residual"), ("arm_6dof_gripper", "M7"): ("M7.dynamics.network",),
}
# What a mapped combination holds beyond the v2 rung it stands for, and why (a test holds every extra to this list)
ADDED_IN_V3 = {"rigid_body_chain": {
    "link_geometry": "the description's link geometry, implicit in the arm card's M0 and named by the sub-assembly card (link_lengths); "
                     "its fitted errors are M2's dh_errors",
    "closure_tolerance": "a closed chain's loop closure (the sub-assembly card's five-bar); a serial chain binds none",
}}
LEGACY_EXTRA = {
    ("arm_subassembly", "*"): {"base_frame": "the chain's nominal model names the base and tool frames the sub-assembly card left implicit",
                               "tool_frame": "as base_frame"},
    ("arm_subassembly", "M2.wear"): {"dh_errors": "the chain's kinematic wear model sits on its geometric model (M2)"},
    ("arm_subassembly", "M6"): {"dh_errors": "as M2.wear", "joint_compliance": "the chain's residual sits on its compliance wear model",
                                "compliance_wear_per_nm_rev": "as joint_compliance"},
}
LINK_GEOMETRY = reg.P("link_geometry", "m", None, "the description's link geometry (URDF / DH table / CAD export); the sub-assembly card's "
                      "link_lengths", "kinematic calibration: its errors are M2's dh_errors", "partial",
                      "link lengths and offsets; a DH table's angles ride with them in rad")

PINNED = {
    "integrated_servo": ("servo.tracking_rms", "servo.stop_error", "servo.twin_fidelity"),
    "bldc_motor": ("motor.envelope", "motor.twin_torque"), "gearbox": ("gearbox.lost_motion", "gearbox.twin_transmission"),
    "foc_controller": ("driver.current_tracking", "driver.twin_current"), "encoder": ("encoder.output_agreement", "encoder.twin_noise"),
    "rigid_body_chain": ("arm.tool_error_at_stop", "arm.sim_vs_real"), "gripper": ("pick.sppm", "pick.grasp_pose_error", "pick.twin_grasp_fidelity"),
    "conveyor": ("conveyor.object_position", "conveyor.twin_fidelity"), "camera": ("camera.tag_detect", "camera.intrinsics", "camera.sim_overlay"),
    "depth_camera": ("depth.z_accuracy", "depth.cloud_vs_sim"), "hyperspectral_camera": ("hsi.spectral_angle", "hsi.twin_cube"),
}
# WHY these (Zach: "the most important ones we kinda pin to the top they are the ones we quickly want to look at"): the type's headline
# performance metric (what the robot's job needs: tracking and a stop, the tool at rest, a pick, an object's place, seeing a tag) and its
# twin-fidelity metric (the README's ruler: held-out twin error ÷ the device's own floor).
PER_RUN = {
    ("integrated_servo", "servo.tracking_rms"): RunSource(table="runs", column="tracking_mrad", note="runs.json (tools/build_app.py): RMS of the "
                                                          "output angle against its target over the run, RobotDx stock.tracking_error's value"),
    ("integrated_servo", "servo.twin_fidelity"): RunSource(table="run_diagnostics", diagnostic="stock.model_error", per_model=True, divide_by="floor",
                                                           note="run_gates.json: RobotDx stock.model_error per model (twin vs real RMS, mrad) ÷ "
                                                                "the station's T1 floor (gates.json)"),
    ("foc_controller", "driver.loop_rate"): RunSource(table="runs", column="rate_hz", note="runs.json: the run's achieved sample rate"),
}
WHY_NOT_RUN = "no producer writes it per run yet; the type card says how it is measured"
COMPONENTS = {"integrated_servo": ("joint-3d", "joint-render"), "camera": ("camera-clip",), "depth_camera": ("camera-clip",)}
COVERAGE_FROM_RUNS = {"integrated_servo"}
REACHABLE = {"servo": "computed: the joint can hold the cell's centre and brake before its range ends (coverage.joint_reachable)",
             "arm_6dof": "a committed mask per mount (type_cards/arm_reachable/<mount>.json)",
             "arm_6dof_gripper": "a committed mask per mount (type_cards/arm_reachable/<mount>.json)"}
# The levels that are not a type (Zach's RobotDx tree: a host, a folder, adapters): what their standard dashboard shows
STRUCTURAL = {
    "deployment": Dashboard(template=None, panels=("Runs", "Gates", "Coverage"), proposed="its runs newest first and the gate cells under it "
                            "(data-ui rollup_tree), as the deployment page's Runs and Gates tabs draw them"),
    "adapter": Dashboard(template=None, panels=("Boards",), proposed="the boards it carries, each with its gate cells passing (rollup_tree)"),
    "station": Dashboard(template=None, panels=(), proposed="a station is typed (integrated_servo): its type's dashboard"),
    "assembly": Dashboard(template=None, panels=("Parts",), proposed="its parts' roll-up: an arm with its gripper"),
    "mount": Dashboard(template=None, panels=("Parts",), proposed="the parts it holds and their mounts' parameters"),
    "tool": Dashboard(template=None, panels=("Parameters",), proposed="the tool's frame and mass: parameters of the chain and the gripper it binds"),
}
STRUCTURAL_WORDS = {"deployment": "deployment", "mount": "mount", "tool": "tool", "gripper": None}

# --- the run tags per bam_rack_twin.hardware kind --------------------------------------------------------------------------------------

HW = "bam_ws src/dev/bam_rack_twin/bam_rack_twin/hardware"
RUN_KINDS = {
    "waypoints": ("driven", True, f"{HW}/experiments.py: position targets under the board's PD (position mode, the config's kp and kd)"),
    "sine": ("driven", True, f"{HW}/experiments.py: a position sine under the board's PD"),
    "samples": ("driven", True, f"{HW}/experiments.py: a sampled position target under the board's PD"),
    "chirp": ("driven", True, f"{HW}/experiments.py: a position chirp under the board's PD"),
    "gravity": ("driven", True, f"{HW}/experiments.py: a slow position triangle under the board's PD"),
    "staircase": ("driven", True, f"{HW}/experiments.py: position steps and holds under the board's PD"),
    "friction": ("driven", True, f"{HW}/experiments.py: velocity-mode plateaus, the board's loop holding each speed"),
    "tape": ("driven", True, f"{HW}/tape.py: a position tape under the board's PD"),
    "hardstop": ("driven", True, f"{HW}/stop.py: a seek into the stop at a capped torque in position mode"),
    "impact": ("driven", True, f"{HW}/impact.py: fast approaches into a known stop, press and release, in position mode"),
    "swing": ("mixed", True, f"{HW}/experiments.py: moved to q0 + A and held under the PD, then STOP: the coast is the free oscillation"),
    "thermal": ("mixed", False, f"{HW}/thermal.py: a fixed d-axis current at standstill (fixed_current_override: no position loop acts), "
                                "then the bridge off for the cool-down"),
}


def offline_scope(excitation: str, closed_loop: bool | None) -> str:
    if excitation == "free response":
        return "any config"
    if excitation == "mixed":
        return "split"
    if excitation == "driven":
        return {True: "its own config", False: "any feedback gains"}.get(closed_loop, "unknown")
    return "unknown"


def run_tags(kind: str | None) -> RunTags:
    """A rack run's tags from its kind (the producer's own words, cited). Unknown stays unknown: a kind nobody wrote here is never
    guessed."""
    if kind not in RUN_KINDS:
        return RunTags(excitation="unknown", closed_loop=None, offline_scope="unknown",
                       why=f"kind {kind!r} is not one bam_rack_twin.hardware writes (type_cards/domain.py RUN_KINDS)")
    excitation, loop, why = RUN_KINDS[kind]
    return RunTags(excitation=excitation, closed_loop=loop, offline_scope=offline_scope(excitation, loop), why=why)


# --- building the types ---------------------------------------------------------------------------------------------------------------

def _rename(card: str, name: str) -> str:
    return PARAMETER_MAP.get((card, name), name)


def _v2_parameters(card) -> dict:
    """{v3 name: v2 Parameter} over every rung of a card (the plain object first, its wear from a worn copy)."""
    out: dict = {}
    for rung in card.rungs:
        for p in rung.parameters:
            name = _rename(card.id, p.name)
            if name not in out:
                out[name] = replace(p, name=name, wear=None)
            if p.wear is not None and out[name].wear is None:
                out[name] = replace(out[name], wear=replace(p.wear, rate=_rename(card.id, p.wear.rate)))
    return out


def _models_single(tid: str, card) -> list[Model]:
    family = META[tid][4][0]
    names = SINGLE[card.id]
    ids = {r.key: f"{r.key.split('.')[0]}.{family}.{names[r.key]}" for r in card.rungs}
    out = []
    for r in card.rungs:
        wear = r.key.endswith(".wear")
        base = ids[r.key[:-5]] if wear else (ids[r.base] if r.base else "")
        out.append(Model(id=ids[r.key], type=tid, k=int(r.key.split(".")[0][1:]), family=family, name=names[r.key], title=r.name, kind=r.kind,
                         parameters=tuple(_rename(card.id, n) for n in r.parameter_names), base=base, wear=wear, current=r.current,
                         n_parameters=r.n_parameters, equation=r.equation, references=r.references, architecture=r.architecture, needs=r.needs,
                         robotparts=r.robotparts, implemented=r.implemented, note=r.note))
    return out


def _models_split(tid: str) -> list[Model]:
    out = []
    current_key = reg.current_rung(META[tid][3][0]).key
    current = set(RUNG_MODELS_SPLIT[(META[tid][3][0], current_key)])
    for mid, title, params, (card, key), base, equation in SPLIT[tid]:
        r = reg.rung(card, key)
        k, family, name = mid.split(".")
        arch = r.architecture
        n = len(params) + (arch.weights if arch else 0)
        note = r.note
        if arch is not None and tid == "rigid_body_chain":
            note = (note + "; " if note else "") + "sized for a six-joint chain (the UR5e): a chain of n joints scales its inputs and outputs"
        out.append(Model(id=mid, type=tid, k=int(k[1:]), family=family, name=name, title=title, kind=r.kind, parameters=tuple(params), base=base,
                         wear=name == "wear", current=mid in current, n_parameters=n, equation=equation or r.equation, references=r.references,
                         architecture=arch, needs=r.needs, robotparts=r.robotparts, implemented=r.implemented, note=note))
    return out


def _with_adds_and_legacy(tid: str, models: list[Model], rung_models: dict) -> list[Model]:
    out = []
    for i, m in enumerate(models):
        if m.kind == "physics" and not m.wear:
            below = next((x for x in reversed(models[:i]) if x.family == m.family and x.kind == "physics" and not x.wear), None)
            adds = tuple(n for n in m.parameters if n not in set(below.parameters if below else ()))
        elif m.wear:
            worn = next(x for x in models if x.id == m.base)
            adds = tuple(n for n in m.parameters if n not in set(worn.parameters))
        else:
            adds = ()
        legacy = tuple(k for k, ids in rung_models.items() if CARD_TYPE[k[0]] == tid and m.id in ids)
        out.append(replace(m, adds=adds, legacy=legacy))
    return out


def _metrics(tid: str) -> tuple[MetricSpec, ...]:
    seen: dict[str, MetricSpec] = {}
    for card_id in META[tid][3]:
        for m in reg.CARDS[card_id].metrics:
            mid = METRIC_MAP.get((card_id, m.id), m.id)
            if mid in seen:
                seen[mid] = replace(seen[mid], legacy=seen[mid].legacy + ((card_id, m.id),))
                continue
            src = PER_RUN.get((tid, mid))
            seen[mid] = MetricSpec(id=mid, type=tid, family=m.family, title=m.title, unit=m.unit, defined_on=m.defined_on,
                                   pinned=mid in PINNED[tid], model_dependent=m.family == "fidelity", aggregate="median", per_run=src,
                                   why_not="" if src else WHY_NOT_RUN, robotdx=m.robotdx, normalised=m.normalised, acceptance=m.gate,
                                   today=m.today, legacy=((card_id, m.id),))
    pinned = [seen[i] for i in PINNED[tid]]
    return tuple(pinned + [m for m in seen.values() if not m.pinned])


def _diagnostics(tid: str) -> tuple[DiagnosticSpec, ...]:
    out: dict[str, DiagnosticSpec] = {}
    for card_id in META[tid][3]:
        for d in reg.CARDS[card_id].diagnostics:
            did = DIAGNOSTIC_MAP.get((card_id, d.id), d.id)
            if did in out:
                out[did] = replace(out[did], legacy=out[did].legacy + ((card_id, d.id),))
                continue
            metric = METRIC_MAP.get((card_id, d.metric), d.metric)
            title = next((m.title for m in reg.CARDS[card_id].metrics if m.id == d.metric), d.metric)
            out[did] = DiagnosticSpec(id=did, type=tid, metric=metric, title=("drift: " if d.kind == "drift" else "") + title,
                                      warn=d.threshold if d.level == "warning" else None, error=d.threshold if d.level == "error" else None,
                                      kind=d.kind, units="ratio" if d.kind == "drift" else "metric", message=d.message, baseline=d.baseline,
                                      robotdx=d.robotdx, note=d.note, legacy=((card_id, d.id),))
    if tid == "integrated_servo":
        out["servo.gap_drift"] = GAP_DRIFT
    return tuple(out.values())


# WHY a drift check in the gap's own units (the calibration-routines lane, 2026-11-07: "A drift alarm scaled to the noise floor goes deaf
# as the noise grows ... a threshold in the gap's own units would not move with it"): decided yes by the domain-v3 lane; this is the
# contract and its check. sysid/drift.py adopting it (and re-running the drift demo and the ladder's gap check) is left to the lane that
# owns them: docs/decision-domain-model-v3-2026-11-07.md, "The drift threshold".
GAP_DRIFT = DiagnosticSpec(
    id="servo.gap_drift", type="integrated_servo", metric="", title="drift: the gap's growth over its commissioned value",
    warn=Limit("<=", None, "rad", "the growth the station's budget allows (its T4 / T5 allocation); set per station"), kind="drift",
    units="parameter", parameter="backlash_rad", message=DRIFT_MESSAGE, baseline="the gap measured at commissioning (the same routine)",
    robotdx="gearbox.wear", note="read from each deployed gap check (servo.gap_check_forecast); its sensitivity is the gap's, never the camera's floor")


def _coverage(tid: str) -> CoverageSpec:
    card = reg.CARDS[META[tid][3][0]]
    dims = tuple(Dimension(name=a.name, unit=a.unit, headline=not a.marginal, bin_size=a.bin_size, binning=a.binning) for a in card.coverage.axes)
    from_runs = tid in COVERAGE_FROM_RUNS
    return CoverageSpec(type=tid, dimensions=dims, rule=card.coverage.rule, gate_pct=card.coverage.gate_pct,
                        reachable=REACHABLE.get(card.id, "every cell (a rig can set any condition)"), from_runs=from_runs,
                        why_not="" if from_runs else "no run writes this type's coverage points yet; plans are scored by the card's function")


def _parts(card) -> tuple[Part, ...]:
    return tuple(Part(type=CARD_TYPE.get(m.card, m.card), count=m.count, role=m.role) for m in card.members)


def _build() -> tuple[dict[str, EntityType], dict[tuple[str, str], tuple[str, ...]]]:
    rung_models: dict[tuple[str, str], tuple[str, ...]] = dict(RUNG_MODELS_SPLIT)
    for card_id, names in SINGLE.items():
        family = META[CARD_TYPE[card_id]][4][0]
        for key, name in names.items():
            rung_models[(card_id, key)] = (f"{key.split('.')[0]}.{family}.{name}",)
    types = {}
    for tid in TYPE_ORDER:
        title, zach, covers, cards, families = META[tid]
        primary = reg.CARDS[cards[0]]
        raw = _models_split(tid) if tid in SPLIT else _models_single(tid, primary)
        order = {f: i for i, f in enumerate(families)}
        raw.sort(key=lambda m: order[m.family])  # stable: each family keeps its ladder order
        models = _with_adds_and_legacy(tid, raw, rung_models)
        v2 = {}
        for card_id in cards:
            for name, p in _v2_parameters(reg.CARDS[card_id]).items():
                if name not in v2:
                    v2[name] = p
                elif v2[name].wear is None and p.wear is not None:  # the folded card's wear (the sub-assembly's drifting zeros)
                    v2[name] = replace(v2[name], wear=p.wear)
        if tid in ADDED_IN_V3:
            v2.setdefault("link_geometry", LINK_GEOMETRY)
        params = []
        for name in dict.fromkeys(n for m in models for n in m.parameters):
            p = v2[name]
            holding = tuple(m.id for m in models if name in m.parameters)
            legacy = tuple((c, p2.name) for c in cards for r in reg.CARDS[c].rungs for p2 in r.parameters if _rename(c, p2.name) == name)
            params.append(ParameterSpec(type=tid, name=name, unit=p.unit, family=next(m.family for m in models if name in m.parameters),
                                        introduced_in=holding[0], models=holding, nominal=p.nominal, source=p.source,
                                        identified_by=p.identified_by, observable=p.observable, role=p.role, wear=p.wear,
                                        legacy=tuple(dict.fromkeys(legacy)), note=p.note))
        view = primary.view
        types[tid] = EntityType(id=tid, title=title, zach=zach, group=primary.group, covers=covers, families=families, models=tuple(models),
                                parameters=tuple(params), metrics=_metrics(tid), diagnostics=_diagnostics(tid), gates=primary.gates,
                                coverage=_coverage(tid), dashboard=Dashboard(template=view.template, panels=view.panels,
                                                                             components=COMPONENTS.get(tid, ()), proposed=view.proposed),
                                members=_parts(primary), legacy_cards=cards, robotdx_part=primary.robotdx_part,
                                note=(f"folds in {', '.join(cards[1:])}: " + "; ".join(f"{k[1]} -> {v}" for k, v in PARAMETER_MAP.items() if k[0] in cards[1:]))
                                if len(cards) > 1 else "")
    return types, rung_models


TYPES, RUNG_MODELS = _build()

# --- queries ------------------------------------------------------------------------------------------------------------------------------


def entity_type(word: str) -> EntityType:
    """A type by its id or by a v2 card id."""
    return TYPES[word] if word in TYPES else TYPES[CARD_TYPE[word]]


def models(type_id: str) -> tuple[Model, ...]:
    return entity_type(type_id).models


def model(type_id: str, model_id: str) -> Model:
    for m in entity_type(type_id).models:
        if m.id == model_id:
            return m
    raise KeyError(f"{type_id} has no model {model_id!r}")


def current_models(type_id: str) -> tuple[Model, ...]:
    return tuple(m for m in entity_type(type_id).models if m.current)


def parameter(type_id: str, name: str) -> ParameterSpec:
    for p in entity_type(type_id).parameters:
        if p.name == name:
            return p
    raise KeyError(f"{type_id} has no parameter {name!r}")


def metric(type_id: str, metric_id: str) -> MetricSpec | None:
    return next((m for m in entity_type(type_id).metrics if m.id == metric_id), None)


def pinned(type_id: str) -> tuple[MetricSpec, ...]:
    return tuple(m for m in entity_type(type_id).metrics if m.pinned)


def diagnostic(type_id: str, diagnostic_id: str) -> DiagnosticSpec:
    for d in entity_type(type_id).diagnostics:
        if d.id == diagnostic_id:
            return d
    raise KeyError(f"{type_id} has no diagnostic {diagnostic_id!r}")


def legacy_models(card: str, key: str) -> tuple[str, ...]:
    """The v3 models (one per family) a v2 (card, rung key) is: its combination."""
    return RUNG_MODELS[(card, key)]


def legacy_parameter(card: str, name: str) -> tuple[str, str]:
    return CARD_TYPE[card], _rename(card, name)


def legacy_metric(card: str, metric_id: str) -> str:
    return METRIC_MAP.get((card, metric_id), metric_id)


def legacy_diagnostic(card: str, diagnostic_id: str) -> str:
    return DIAGNOSTIC_MAP.get((card, diagnostic_id), diagnostic_id)


def declared_extra(card: str, key: str) -> dict[str, str]:
    """The parameters a v2 rung's v3 combination holds beyond the rung's own, each with why (ADDED_IN_V3, LEGACY_EXTRA)."""
    return {**ADDED_IN_V3.get(CARD_TYPE[card], {}), **LEGACY_EXTRA.get((card, "*"), {}), **LEGACY_EXTRA.get((card, key), {})}


def routine_parameters(routine_id: str) -> tuple[tuple[str, str, str], ...]:
    """Routine -> parameters: (type, model, parameter) for every parameter the routine identifies; the model is the lowest of the
    parameter's family that holds every parameter the routine claims there (v2's Identifies rung, where v2 was precise)."""
    out = []
    for item in reg.routine(routine_id).identifies:
        tid = CARD_TYPE[item.card]
        names = [_rename(item.card, p) for p in item.parameters]
        for fam in dict.fromkeys(parameter(tid, n).family for n in names):
            want = {n for n in names if parameter(tid, n).family == fam}
            host = next(m for m in entity_type(tid).models if m.family == fam and m.kind == "physics" and want <= set(m.parameters))
            out += [(tid, host.id, n) for n in names if n in want]
    return tuple(dict.fromkeys(out))


def fitted_model(routine_id: str, type_id: str, family: str) -> str | None:
    """The one model a routine's single fit is, on a type and family: the lowest physics model holding every parameter the routine
    identifies there (arm.dynamics_excitation fits armature, friction and damping at once: the servo's M2, one column, never two)."""
    want = {n for t, _m, n in routine_parameters(routine_id) if t == type_id and parameter(t, n).family == family}
    if not want:
        return None
    return next(m.id for m in entity_type(type_id).models if m.family == family and m.kind == "physics" and want <= set(m.parameters))


def routines_identifying(type_id: str, name: str) -> tuple:
    """Parameter -> routines: every v2 CalibrationRoutine that identifies the type's parameter (reg.ROUTINES order)."""
    parameter(type_id, name)
    return tuple(r for r in reg.ROUTINES if any(t == type_id and n == name for t, _m, n in routine_parameters(r.id)))


def parameter_routines() -> dict[str, dict[str, list[str]]]:
    """{type: {parameter: [routine ids]}} over every parameter of every type, [] where nothing reaches it."""
    hits: dict[tuple[str, str], list[str]] = {}
    for r in reg.ROUTINES:
        for t, _m, n in routine_parameters(r.id):
            hits.setdefault((t, n), []).append(r.id)
    return {tid: {p.name: list(dict.fromkeys(hits.get((tid, p.name), []))) for p in t.parameters} for tid, t in TYPES.items()}


def level(diag: DiagnosticSpec, value: float | None, limits: Mapping[str, float] | None = None) -> str:
    """ok | warning | error | unknown for a value against a diagnostic's limits. `limits` supplies a per-unit value ({"warn": v,
    "error": v}) where the spec's is None. Unknown when there is no value or no limit with a value: never a guess."""
    if value is None:
        return "unknown"
    limits = limits or {}
    checked = False
    for name, word in (("error", "error"), ("warn", "warning")):
        lim = getattr(diag, name)
        if lim is None:
            continue
        v = limits.get(name, lim.value)
        if v is None:
            continue
        checked = True
        if not lim.ok(float(value), float(v)):
            return word
    return "ok" if checked else "unknown"


def parameter_drift(diag: DiagnosticSpec, *, commissioned: float | None, measured: float | None, allowance: float | None) -> str:
    """A drift check in the parameter's own units (units "parameter"): its growth over the commissioned value against the allowance.
    Unknown without a measurement or an allowance."""
    if diag.units != "parameter":
        raise ValueError(f"{diag.id} is not a parameter drift check")
    if None in (commissioned, measured, allowance):
        return "unknown"
    return "ok" if diag.warn.ok(float(measured) - float(commissioned), float(allowance)) else "warning"


def _bounds(lim: Limit | None, value: float | None) -> tuple[float | None, float | None]:
    if lim is None or value is None:
        return None, None
    return (value, None) if lim.op == ">=" else (None, value)


def diagnostic_row(diag: DiagnosticSpec, value: float | None, *, subject: str, limits: Mapping[str, float] | None = None, **extra) -> dict:
    """PEP 0010 §10's diagnostic row (data-ui's gate and threshold views read it): the level, its rank, the limits as data."""
    limits = limits or {}
    wv = limits.get("warn", diag.warn.value if diag.warn else None)
    ev = limits.get("error", diag.error.value if diag.error else None)
    warn_lo, warn_hi = _bounds(diag.warn, wv)
    error_lo, error_hi = _bounds(diag.error, ev)
    lv = level(diag, value, limits)
    unit = (diag.warn or diag.error).unit if (diag.warn or diag.error) else ""
    return {"subject": subject, "diagnostic": diag.id, "title": diag.title, "level": lv, "rank": LEVEL_RANK[lv], "value": value, "unit": unit,
            "warn_lo": warn_lo, "warn_hi": warn_hi, "error_lo": error_lo, "error_hi": error_hi, "kind": diag.kind,
            "message": (diag.message or f"{diag.title} past its limit") if lv in ("warning", "error") else "", **extra}


# --- export ---------------------------------------------------------------------------------------------------------------------------

def plain(obj):
    """JSON-able: dataclasses as dicts (a Model with its key, an Architecture with its sizes), tuples as lists."""
    if is_dataclass(obj) and not isinstance(obj, type):
        out = {f.name: plain(getattr(obj, f.name)) for f in fields(obj) if not callable(getattr(obj, f.name))}
        if isinstance(obj, Model):
            out = {"key": obj.key, **out}
        if isinstance(obj, Architecture):
            out.update(n_inputs=obj.n_inputs, weights=obj.weights)
        return out
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    return obj


def export() -> dict:
    """The type level as JSON (type_cards/domain_v3.json): what a page reads without importing Python."""
    back = parameter_routines()
    types = []
    for t in TYPES.values():
        d = plain(t)
        d.update(models=[m.id for m in t.models], parameters=[p.name for p in t.parameters], metrics=[m.id for m in t.metrics],
                 diagnostics=[x.id for x in t.diagnostics], pinned=[m.id for m in t.metrics if m.pinned],
                 current=[m.id for m in t.models if m.current])
        types.append(d)
    return {
        "schema": SCHEMA,
        "note": "Generated by type_cards/domain.py (python3 -m type_cards.domain --write); never edit. Contract: type_cards/CONTRACT.md, "
                "\"Domain model v3\".",
        "deployment_kinds": DEPLOYMENT_KINDS, "families": FAMILIES, "excitations": EXCITATIONS, "offline_scopes": OFFLINE_SCOPES,
        "levels": list(LEVELS), "level_rank": LEVEL_RANK, "aggregates": list(AGGREGATES), "tags": TAGS, "tag_of_type": TAG_OF_TYPE,
        "estimate_forms": ESTIMATE_FORMS, "structural": plain(STRUCTURAL),
        "run_kinds": {k: {"excitation": e, "closed_loop": c, "offline_scope": offline_scope(e, c), "why": w} for k, (e, c, w) in RUN_KINDS.items()},
        "entity_types": types,
        "models": [plain(m) for t in TYPES.values() for m in t.models],
        "parameters": [{"key": f"{p.type}/{p.name}", **plain(p), "routines": back[p.type][p.name]} for t in TYPES.values() for p in t.parameters],
        "metrics": [plain(m) for t in TYPES.values() for m in t.metrics],
        "diagnostics": [plain(d) for t in TYPES.values() for d in t.diagnostics],
        "coverage": [plain(t.coverage) for t in TYPES.values()],
        "routines": [{"id": r.id, "title": r.title, "package": r.package, "kind": r.kind, "setting": r.setting, "status": r.status,
                      "identifies": [{"type": t, "model": m, "parameter": n} for t, m, n in routine_parameters(r.id)],
                      "legacy_identifies": plain(r.identifies)} for r in reg.ROUTINES],
        "parameter_routines": back,
        "migration": {
            "cards": CARD_TYPE,
            "rungs": [{"card": c, "key": k, "type": CARD_TYPE[c], "models": list(v)} for (c, k), v in RUNG_MODELS.items()],
            "parameters": [{"card": c, "name": p.name, "type": CARD_TYPE[c], "parameter": _rename(c, p.name)}
                           for c, card in reg.CARDS.items() for p in dict((x.name, x) for r in card.rungs for x in r.parameters).values()],
            "metrics": [{"card": c, "metric": m, "to": v} for (c, m), v in METRIC_MAP.items()],
            "diagnostics": [{"card": c, "diagnostic": d, "to": v} for (c, d), v in DIAGNOSTIC_MAP.items()],
            "added_in_v3": ADDED_IN_V3, "legacy_extra": [{"card": c, "key": k, "extra": v} for (c, k), v in LEGACY_EXTRA.items()],
        },
    }


def export_text() -> str:
    return json.dumps(export(), indent=1, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = export_text()
    if "--write" in argv:
        DOMAIN_JSON.write_text(text, encoding="utf-8")
        print(f"wrote {DOMAIN_JSON} ({len(text):,} bytes)")
        return 0
    if "--check" in argv:
        same = DOMAIN_JSON.is_file() and DOMAIN_JSON.read_text(encoding="utf-8") == text
        print("type_cards/domain_v3.json is " + ("current" if same else "stale: python3 -m type_cards.domain --write"))
        return 0 if same else 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
