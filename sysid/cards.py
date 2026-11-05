"""sysid's adapter over the type cards (type_cards, contract sim2real.type_cards/2): typing, ladders and drift diagnostics.

`from type_cards import registry as reg` is the one import (CONTRACT.md). Three things the cards do not carry yet, adapted here and
listed in the report, never written into type_cards/ (lane A's write set):

- **words** a description uses that `reg.card_for` does not resolve (bam_rack_twin's `moteus_servo`, UR's `ur5e`), and three types
  with no card yet (conveyor, gripper, the tool an arm carries) plus two structural nodes (a deployment, a mount);
- **ladders**: the v2 schema is on main but no card has rungs yet ("content follows"). `ladder(card_id)` returns the card's own
  rungs when it has them and this module's otherwise, built from the same schema classes (reg.Rung, reg.Parameter, reg.Wear) and
  keyed by the contract's rule: actuator ladders follow robotparts' layers (M2 Coulomb + viscous, M3 Stribeck, M4 backlash, never
  an M1: the datasheet is the nominal column); every other type numbers its own layers from M0, the description's nominal model;
- **drift diagnostics**: `drift_diagnostic(card_id)` is the card's own `kind="drift"` diagnostic when it has one, else this
  module's, with reg.DRIFT_MESSAGE, reg.DRIFT_THRESHOLD and a wear Forecast; `check_drift` runs reg's drift_check on it, so the
  verdict, the message and the usage remaining are type_cards' arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from type_cards import registry as reg

# --- typing ---------------------------------------------------------------------------------------------------------------------

STRUCTURAL = {"deployment": "Deployment", "mount": "Mount"}
# WHY words here and not reg.ALIASES: ALIASES is lane A's; these are the description words the examples use that it does not hold
WORDS = {"moteus_servo": "servo", "ur5e": "arm_6dof", "d405": "camera_rgbd"}


@dataclass(frozen=True)
class AdapterCard:
    """A type with no type card yet: just enough to type a component and hold its ladder (proposed for lane A)."""
    id: str
    title: str
    group: str
    note: str
    words: tuple[str, ...] = ()


ADAPTER_CARDS = {
    "conveyor": AdapterCard("conveyor", "Conveyor belt", "actuator",
                            "no card yet (reg.ALIASES already maps 'conveyor belt' and 'belt' to an id 'conveyor' that CARDS lacks)",
                            ("conveyor", "conveyor belt", "belt")),
    "gripper": AdapterCard("gripper", "Gripper", "actuator", "arm_6dof_gripper names 'RobotDx part type gripper (no card yet)' as its member",
                           ("gripper", "parallel gripper", "2f-85")),
    "tool": AdapterCard("tool", "Tool (payload + TCP)", "actuator",
                        "the tool an arm carries: its inertial and TCP (arm_6dof's tool_frame and link_inertials, arm_6dof_gripper's tcp_offset)",
                        ("tool", "payload", "end effector")),
}


@dataclass(frozen=True)
class TypeRef:
    id: str
    title: str
    group: str
    source: str  # "type_cards" | "sysid adapter (no card yet)" | "structural"
    word: str


def card_for(word: str) -> TypeRef:
    """The type a description's word names: a type card first (reg.card_for), then this adapter's words, cards and structure."""
    hit = reg.card_for(word) or (reg.CARDS.get(WORDS[word.strip().lower()]) if word.strip().lower() in WORDS else None)
    if hit is not None:
        return TypeRef(hit.id, hit.title, hit.group, "type_cards", word)
    w = word.strip().lower()
    for card in ADAPTER_CARDS.values():
        if w == card.id or w in card.words:
            return TypeRef(card.id, card.title, card.group, "sysid adapter (no card yet)", word)
    if w in STRUCTURAL:
        return TypeRef(w, STRUCTURAL[w], "structure", "structural", word)
    raise KeyError(f"no type card or adapter type for the description word {word!r}")


# --- ladders ---------------------------------------------------------------------------------------------------------------------

def ref(title: str, url: str = "", doi: str = "", kind: str = "paper", note: str = "") -> reg.Reference:
    return reg.Reference(title=title, url=url, kind=kind, doi=doi, note=note)


ARMSTRONG_1994 = ref("Armstrong-Helouvry, Dupont & Canudas de Wit (1994). A survey of models, analysis tools and compensation methods for "
                     "the control of machines with friction. Automatica 30(7):1083-1138", doi="10.1016/0005-1098(94)90209-7",
                     note="Coulomb + viscous, the Stribeck curve")
BAM_CODE = ref("Rhoban BAM (Better Actuator Models): the M1-M6 actuator friction ladder", url="https://github.com/Rhoban/bam", kind="code",
               note="bam_rack_twin names its Stribeck and load-dependent terms BAM's M2 and M3")
NORDIN_2002 = ref("Nordin & Gutman (2002). Controlling mechanical systems with backlash - a survey. Automatica 38(10):1633-1649",
                  doi="10.1016/S0005-1098(02)00047-X", note="the dead-zone gap model a dual-encoder measurement sees")
SWEVERS_1997 = ref("Swevers, Ganseman, Tukel, De Schutter & Van Brussel (1997). Optimal robot excitation and identification. "
                   "IEEE Transactions on Robotics and Automation 13(5):730-740", doi="10.1109/70.631234",
                   note="periodic Fourier excitation, joint friction regressors")
ZHANG_2000 = ref("Zhang (2000). A flexible new technique for camera calibration. IEEE TPAMI 22(11):1330-1334", doi="10.1109/34.888718",
                 note="pinhole intrinsics and pose from a planar target, refined by reprojection error")
WEAR_REFS = reg.WEAR_LAW_REFERENCES.get("linear", ())


def P(name, unit, nominal, identified_by, observable="yes", note="", wear=None):
    return reg.P(name, unit, nominal, "the description (sysid manifest)", identified_by, observable, note, wear)


SERVO_M2 = (
    P("gravity_nm", "N·m", None, "inverse-dynamics regression on the train split (gravity sweeps, plateaus, chirps, multisines)"),
    P("gravity_bottom_rad", "rad", None, "the same regression (sin and cos terms)"),
    P("armature_kg_m2", "kg·m²", None, "the same regression (the qdd term): the whole axis inertia"),
    P("frictionloss_nm", "N·m", None, "the same regression (sgn qd): Coulomb in M2, the static level in M3 and up"),
    P("damping_nm_s_rad", "N·m·s/rad", None, "the same regression (qd)"),
)
SERVO_M3 = SERVO_M2 + (
    P("friction_stribeck_drop_nm", "N·m", None, "the regression with an exp(-(qd/vs)^2) term, vs by a profiled search"),
    P("friction_stribeck_speed_rad_s", "rad/s", None, "the profiled search over vs"),
)
SERVO_M4 = SERVO_M3 + (
    P("backlash_rad", "rad", None, "the gap between the motor encoder and the link camera (two clusters of motor minus link)",
      observable="partial", note="encoder-blind; seen only with a second sensor after the gear (the camera on tags 8-12)"),
)
SERVO_M4_WEAR = SERVO_M3 + (
    P("backlash_rad", "rad", None, "the dual-encoder gap per deployed check", observable="partial",
      wear=reg.Wear("deployment hours", "h", "linear", "backlash_wear_rad_per_h", note="b(h) = b0 + k h")),
    P("backlash_wear_rad_per_h", "rad/h", None, "least squares of the gap on hours over the early-life checks"),
)

ARM_M1 = (P("zero_offset_rad", "rad", 0.0, "least squares of the tracker's flange pose on FK(q + offset) at static poses"),)
ARM_M2 = ARM_M1 + (
    P("armature_kg_m2", "kg·m²", None, "linear regression of measured joint torque on MuJoCo's rigid-body inverse dynamics plus qdd, qd, sgn qd"),
    P("damping_nm_s_rad", "N·m·s/rad", None, "the same regression"),
    P("frictionloss_nm", "N·m", None, "the same regression"),
)
POSE6 = tuple(P(n, u, 0.0, "bundle adjustment of tag corners (reprojection error)") for n, u in
              (("dx_m", "m"), ("dy_m", "m"), ("dz_m", "m"), ("rx_rad", "rad"), ("ry_rad", "rad"), ("rz_rad", "rad")))
PINHOLE = tuple(P(n, "px", None, "bundle adjustment of tag corners (reprojection error)") for n in ("fx_px", "fy_px", "cx_px", "cy_px"))

ADAPTER_LADDERS: dict[str, tuple[reg.Rung, ...]] = {
    "servo": (
        reg.Rung("M2", "Coulomb + viscous, rigid pendulum", SERVO_M2, (ARMSTRONG_1994, BAM_CODE),
                 "tau = J qdd + G sin(q - bottom) + Fc sgn(qd) + b qd", implemented="sysid/examples/pendulum_can11/pipeline.py",
                 robotparts="M2.twin"),
        reg.Rung("M3", "+ Stribeck (BAM's M2 friction)", SERVO_M3, (ARMSTRONG_1994, BAM_CODE),
                 "friction = sgn(qd) [Fc + (Fs - Fc) exp(-(qd/vs)^2)] + b qd; frictionloss is Fs", implemented="sysid/examples/pendulum_can11/pipeline.py",
                 robotparts="M3.twin"),
        reg.Rung("M4", "+ gear backlash (ripple not fitted)", SERVO_M4, (NORDIN_2002,),
                 "the M3 joint behind a gap of width b (bam_rack_twin's backlash hinge, gear_backlash.BacklashModel)",
                 implemented="sysid/examples/pendulum_can11/pipeline.py", robotparts="M4.twin.backlash",
                 note="robotparts' M4 layer is ripple + backlash; the hidden truth has no ripple, so only the gap is fitted"),
        reg.Rung("M4.wear", "+ backlash wear in deployment hours", SERVO_M4_WEAR, (NORDIN_2002,) + tuple(WEAR_REFS),
                 "b(h) = b0 + k h (type_cards Wear, law linear)", implemented="sysid/drift.py"),
    ),
    "arm_6dof": (
        reg.Rung("M0", "the description as given", (), (), "Menagerie's model, nothing fitted"),
        reg.Rung("M1", "+ joint zero offsets (kinematics)", ARM_M1, (), "tool = FK(q_encoder + offset)", implemented="sysid/arm.py"),
        reg.Rung("M2", "+ joint servo dynamics (reflected inertia, viscous, Coulomb)", ARM_M2, (SWEVERS_1997,),
                 "tau = ID_rigid(q, qd, qdd) + a qdd + b qd + Fc sgn(qd), per joint", implemented="sysid/arm.py"),
    ),
    "tool": (
        reg.Rung("M0", "the description as given", (), (), "Menagerie's gripper inertial and pinch site"),
        reg.Rung("M1", "mass, centre of mass, TCP", (P("mass_kg", "kg", None, "the arm's torque regression (payload columns)"),
                                                     P("com_z_m", "m", None, "the same regression"),
                                                     P("tcp_x_m", "m", None, "the TCP marker at static poses"),
                                                     P("tcp_z_m", "m", None, "the TCP marker at static poses")), (),
                 "the tool's inertial and TCP in the flange frame", implemented="sysid/arm.py"),
    ),
    "gripper": (
        reg.Rung("M0", "the description as given", (), (), "Menagerie's 2F-85 drive"),
        reg.Rung("M1", "drive gain and damping", (P("actuator_gain", "N per count", None, "least squares of simulated finger traces on measured ones"),
                                                  P("damping", "N·s/m", None, "the same fit")), (),
                 "tendon force = gain ctrl - 100 L - damping L'", implemented="sysid/arm.py"),
    ),
    "conveyor": (
        reg.Rung("M0", "the description as given", (), (), "conveyor.xml as drawn"),
        reg.Rung("M1", "+ effective roller radius", (P("roller_radius_m", "m", None, "belt travel (tracker) on roller angle (encoder)"),), (),
                 "x_belt = r theta", implemented="sysid/examples/conveyor/pipeline.py"),
        reg.Rung("M2", "+ moving mass, viscous and Coulomb drag", (P("roller_radius_m", "m", None, "as M1"),
                                                                   P("moving_mass_kg", "kg", None, "least squares of simulated roller speed on measured"),
                                                                   P("viscous_drag_n_s_m", "N·s/m", None, "the same fit"),
                                                                   P("coulomb_drag_n", "N", None, "the same fit")), (ARMSTRONG_1994,),
                 "m x'' = F_drive - b x' - F sgn(x')", implemented="sysid/examples/conveyor/pipeline.py"),
    ),
    "mount": (
        reg.Rung("M0", "the drawing", (), (), "the mount where the description draws it"),
        reg.Rung("M1", "pose correction", POSE6, (ZHANG_2000,), "R = exp([r]) R_drawn, t = t_drawn + d", implemented="sysid/camera.py"),
    ),
    "camera_rgb": (
        reg.Rung("M0", "the description as given", (), (), "a MuJoCo fovy camera at its drawn pose"),
        reg.Rung("M1", "pinhole K + pose", PINHOLE + POSE6, (ZHANG_2000,), "p = K [R | t] X", implemented="sysid/camera.py",
                 note="distortion (the card's k1 k2 p1 p2 k3) is the next layer; the simulated lens has none"),
    ),
    "camera_rgbd": (
        reg.Rung("M0", "the description as given", (), (), "the D435's nominal K at its drawn pose"),
        reg.Rung("M1", "pinhole K + pose + depth scale and offset", PINHOLE + POSE6 + (P("depth_scale", "1", 1.0, "the same fit (depth residuals)"),
                                                                                    P("depth_offset_m", "m", 0.0, "the same fit")), (ZHANG_2000,),
                 "p = K [R | t] X, z_reported = s z + o", implemented="sysid/camera.py"),
    ),
    "camera_hsi": (
        reg.Rung("M0", "the description as given", (), (), "the vendor's lens, drawing and response curve"),
        reg.Rung("M1", "line pinhole + pose + per-band gain and dark", (
            P("focal_px", "px", None, "dot centres on a two-height target (pixel, belt position at the line)"),
            P("principal_px", "px", None, "the same fit"), P("height_m", "m", None, "the same fit"),
            P("across_offset_m", "m", None, "the same fit"), P("scan_line_x_m", "m", None, "the same fit"),
            P("scan_yaw_rad", "rad", None, "the same fit"),
            P("gain", "DN per unit reflectance", None, "per band: least squares on white / grey / black / dark references"),
            P("dark", "DN", None, "the same per-band fit")), (),
                 "u = f (y - y0) / (h - z) + c; DN_b = g_b R_b + d_b", implemented="sysid/examples/linescan_cell/pipeline.py",
                 note="band centres and widths are the vendor's (the card's band_centres / band_fwhm need a lamp, not simulated)"),
    ),
}


def ladder(card_id: str) -> tuple[tuple, str]:
    """(rungs lowest first, source): the card's own ladder once lane A writes it, else this adapter's."""
    own = reg.rungs(card_id) if card_id in reg.CARDS else ()
    if own:
        return own, "type_cards"
    return ADAPTER_LADDERS.get(card_id, ()), "sysid adapter (type_cards has no rungs for this card yet)"


def rung_row(rung) -> dict:
    return {"key": rung.key, "name": rung.name, "n_parameters": rung.n_parameters, "parameters": list(rung.parameter_names),
            "equation": rung.equation, "references": [{"title": r.title, "doi": r.doi, "url": r.url} for r in rung.references],
            "wear": [{"parameter": p.name, "usage": p.wear.usage, "unit": p.wear.unit, "law": p.wear.law, "rate": p.wear.rate} for p in rung.wear_parameters]}


# --- drift --------------------------------------------------------------------------------------------------------------------------

ADAPTER_DRIFT = {
    "servo": reg.Diagnostic("servo.drift", "servo.twin_fidelity", reg.Limit("<=", reg.DRIFT_THRESHOLD, "x calibrated"),
                            message=reg.DRIFT_MESSAGE, kind="drift", baseline="the held-out fidelity at calibration (x floor)",
                            forecast=reg.Forecast("deployment hours", "h", "linear", ("backlash_rad",)),
                            note="sysid adapter: the servo card has no drift diagnostic yet"),
    "camera_rgb": reg.Diagnostic("camera_rgb.drift", "camera.intrinsics", reg.Limit("<=", reg.DRIFT_THRESHOLD, "x calibrated"),
                                 message=reg.DRIFT_MESSAGE, kind="drift", baseline="the reprojection error at calibration",
                                 note="sysid adapter: the camera card has no drift diagnostic yet; a knock is a step, so no wear forecast"),
}


def drift_diagnostic(card_id: str) -> tuple[reg.Diagnostic, str]:
    own = reg.drift_diagnostic(card_id) if card_id in reg.CARDS else None
    if own is not None:
        return own, "type_cards"
    return ADAPTER_DRIFT[card_id], "sysid adapter (type_cards has no drift diagnostic for this card yet)"


def check_drift(card_id: str, live: float, calibrated: float, threshold: float | None = None, history=None):
    """type_cards' drift check (reg.schema.drift_check) on the card's drift diagnostic: DriftResult(status, ratio, threshold,
    message, remaining, unit)."""
    diagnostic, _ = drift_diagnostic(card_id)
    return reg.schema.drift_check(diagnostic, live, calibrated, threshold, history)
