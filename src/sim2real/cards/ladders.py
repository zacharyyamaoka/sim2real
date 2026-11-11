"""The v2 content per type card (Zach, PROJECT - Sim2Real, "Proposed Work Flow Nov 5 2026"): the ladder of models, the
diagnostics and gates over the black-box metrics, the drift diagnostic, and the test types. `build(reg)` returns the cards with
it; registry.py calls it once, so `reg.CARDS` is the only place a consumer reads.

How the ladders are made (CONTRACT.md has the rules):
- physics rungs are nested and reuse today's Parameter objects, so the current rung IS today's model;
- actuator keys are robotparts' layers (M0 ideal, M2 Coulomb + viscous, M3 Stribeck / load, M4 ripple + backlash, M5 electrics;
  WHY: docs/decision-rung-keys-2026-11-05.md);
  the other types count their own from M0, the nominal model a robot description gives;
- the top physics rung's wear variant (`.wear`) gives the known wear parameters a usage input and a rate;
- residual (grey box) and learned (black box) rungs sit on top, always M6 and M7 (the same meaning on every card); they need far
  more coverage and never extrapolate.
WHY a function over the registry module and not module-level cards: the content reuses the v1 cards' own Parameter objects, and a
function keeps the import one way (registry -> ladders -> schema / references), never circular.
"""

from __future__ import annotations

from dataclasses import replace

from sim2real.metrics.gate import rule_of

from . import references as R
from . import servo_gates
from .schema import DRIFT_MESSAGE, DRIFT_THRESHOLD, Architecture, CoverageNeed, Diagnostic, Forecast, Gate, Limit, Rung, TestType, Wear

LEARNED_PCT = 95.0       # % of reachable cells a learned rung's train split must fill
LEARNED_SAMPLES = 200    # train samples a cell needs (2 s at 100 Hz)
DEPLOYED_PCT = 99.0      # % of deployed samples that must fall in such cells
# WHY these numbers: the servo test schedule note's stricter targets (Servo Test Schedule — Prior Art and a Recommended v1,
# 2026-10-29: ">= 95 % of reachable cells hold >= 200 train samples"; ">= 99 % of H2's samples fall in cells with >= 200 train
# samples"), which schedule.py reports but does not gate in v1. A physics rung only needs the type's gate (visited once).
HISTORY_DT_S = 0.01      # Hwangbo et al. 2019's spacing: t, t - 10 ms, t - 20 ms
CALIBRATED = "its held-out fidelity at calibration (the held-out step's scores.json)"


# --- helpers ---------------------------------------------------------------------------------------------------------------

def pick(params, *names):
    by = {p.name: p for p in params}
    missing = [n for n in names if n not in by]
    if missing:
        raise KeyError(f"no parameters {missing}")
    return tuple(by[n] for n in names)


def grow(below: Rung | tuple, *more) -> tuple:
    base = below.parameters if isinstance(below, Rung) else tuple(below)
    return base + tuple(more)


def worn(params, name: str, wear: Wear) -> tuple:
    return tuple(replace(p, wear=wear) if p.name == name else p for p in params)


def need_physics(card) -> CoverageNeed:
    return CoverageNeed(card.coverage.gate_pct, 1, True, note="visited once: the type's coverage gate; physics extrapolates between cells")


def need_residual() -> CoverageNeed:
    return CoverageNeed(LEARNED_PCT, LEARNED_SAMPLES, False,
                        note="outside its trained cells the residual is off: the base rung answers there, flagged out of coverage")


def need_learned() -> CoverageNeed:
    return CoverageNeed(LEARNED_PCT, LEARNED_SAMPLES, False, DEPLOYED_PCT,
                        note="outside its trained cells it has no answer: flagged out of coverage, never scored")


def phys(card, key, name, params, refs, equation="", robotparts=None, implemented="", current=False, note="") -> Rung:
    return Rung(key, name, tuple(params), tuple(refs), equation, "physics", None, "", need_physics(card), robotparts, implemented, current, note)


def residual(key, base: Rung, arch: Architecture, refs, note="") -> Rung:
    return Rung(key, f"Grey-box residual on {base.key}", base.parameters, tuple(refs),
                f"{base.key} + MLP residual ({arch.output}) from {arch.history} samples of {', '.join(arch.inputs)}",
                "residual", arch, base.key, need_residual(), None, "proposed: no residual net is trained in bam_ws yet", False, note)


def learned(key, name, arch: Architecture, refs, note="") -> Rung:
    return Rung(key, name, (), tuple(refs), f"{arch.family} over {arch.history} samples of {', '.join(arch.inputs)} → {arch.output}",
                "learned", arch, "", need_learned(), None, "proposed: no actuator net is trained in bam_ws yet", False, note)


def mlp(inputs, output, hidden, history=3, activation="softsign", n_outputs=1) -> Architecture:
    return Architecture("MLP", tuple(inputs), output, history, HISTORY_DT_S, tuple(hidden), activation, n_outputs)


def dx(metric, op, value, unit, note="", robotdx=None, level="warning") -> Diagnostic:
    return Diagnostic(f"{metric}.dx", metric, Limit(op, value, unit, note), level, f"{metric} past its threshold ({op} {value if value is not None else note} {unit})",
                      robotdx=robotdx, note=note)


def gate(metric, op, value, unit, acceptance="", note="") -> Gate:
    return Gate(f"{metric}.gate", f"{metric}.dx", Limit(op, value, unit, note), acceptance, note)


def drift(card_id, metric, forecast=None, robotdx=None, note="") -> Diagnostic:
    return Diagnostic(f"{card_id}.drift", metric, Limit("<=", DRIFT_THRESHOLD, "× calibrated"), "warning", DRIFT_MESSAGE, "drift", CALIBRATED,
                      True, forecast, robotdx, note)


def T(card_id, key, title, setting, identifies, how, needs=(), recalibration=False, exists="", duration="") -> TestType:
    return TestType(f"{card_id}.{key}", title, setting, tuple(identifies), how, tuple(needs), recalibration, exists, duration)


def P(reg, *args, **kw):
    return reg.P(*args, **kw)


NOT_TRAINED = "proposed: no usage counter is logged yet, so no rate has been regressed"
HOURS = ("deployment hours", "h")
VIBRATION = ("vibration hours", "h")


# --- servo (integrated) ----------------------------------------------------------------------------------------------------

def servo(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Ideal: rigid inertia under the board's PD", pick(m, "armature_kg_m2", "gravity_nm", "kp_nm_rad", "kd_nm_s_rad"),
              (R.SICILIANO_2009, R.MUJOCO_ARMATURE), "J q̈ = kp (q* − q) + kd (q̇* − q̇) + τ_ff − G sin(q − q_bottom)",
              "models/actuator/ideal", "robotparts models/actuator/ideal (model.py); bam_rack_twin twin.py with armature alone")
    m2 = phys(card, "M2", "Coulomb + viscous friction", grow(m0, *pick(m, "frictionloss_nm", "damping_nm_s_rad")), (R.ARMSTRONG_1994, R.OLSSON_1998),
              "M0 − Fc sign(q̇) − b q̇", "models/actuator/coulomb_viscous", "robotparts models/actuator/coulomb_viscous; bam_rack_twin identify.py (friction fit)")
    m3 = phys(card, "M3", "Stribeck, weakening and capture", grow(m2, *pick(m, "friction_weakening_nm_s_rad", "friction_stribeck_drop_nm", "friction_capture_nm")),
              (R.ARMSTRONG_1994, R.CANUDAS_1995), "level(v) = Fs − w·min(|v|, limit) − drop·(1 − exp(−(v/vs)²)); the capture level while just slowed",
              "models/actuator/stribeck", "robotparts models/actuator/stribeck; bam_rack_twin TwinParameters (layer 3 terms)")
    m4 = phys(card, "M4", "Rack twin: + cogging, delay, backlash, drive and heat (today's model)", m, (R.JAHNS_1996, R.NORDIN_2002, R.TUTTLE_1996, R.KRISHNAN_2010),
              card.model.equation, "lab/models/actuator/twin", "bam_rack_twin TwinParameters (bam_ws src/dev/bam_rack_twin/bam_rack_twin/twin.py)", current=True,
              note="the drive's terms (torque scale, current loop, delay) are the board's: robotparts keeps them as the backend's driver, never a rung term")
    m5 = phys(card, "M5", "+ drive ceilings and motor electrics", grow(m4,
              P(reg, "voltage_available_v", "V", None, "bam_rack_twin TwinParameters.voltage_limit[0] (V_avail = fw max_V_factor × bus)",
                "top-speed plateaus at the bus voltage (T7)", "yes", "CAN 14 and CAN 15 on the c1 bus top out at ~17.9 V", role="driver"),
              P(reg, "kt_out_nm_a", "N·m/A", None, "bam_rack_twin TwinParameters.voltage_limit[1] (N × rotor Kt); robotparts:dcmotor.motorconst",
                "a known mass (T6) and the top-speed plateaus", "partial"),
              P(reg, "phase_resistance_ohm", "Ω", None, "bam_rack_twin TwinParameters.voltage_limit[2]; robotparts:dcmotor.resistance",
                "board calibration, measure-only (moteus_tool --calibrate --cal-no-update)", "yes"),
              P(reg, "max_current_a", "A", None, "bam_rack_twin TwinParameters.current_limit[1] (servo.max_current_A)", "read from the config receipt", "yes",
                role="config")),
              (R.KRAUSE_2013, R.MUJOCO_DCMOTOR, R.MOTEUS_REFERENCE), "motoring torque ≤ kt_out (V_avail − |ω| kt_out / 1.5) / R; any torque ≤ kt_out · I_max",
              "models/actuator/dcmotor", "bam_rack_twin TwinParameters.voltage_limit / current_limit (the envelope ladder, 2026-10-24)")
    wear_backlash = Wear("torque-weighted output revolutions", "N·m·rev", "archard", "backlash_wear_rad_per_nm_rev",
                         "the gear flanks wear with the torque they carry times the distance they slide")
    wear_friction = Wear(*HOURS, "linear", "friction_growth_nm_per_h", "seal and grease ageing raise the static level")
    m5w = phys(card, "M5.wear", "+ wear: backlash and friction grow with use",
               worn(worn(m5.parameters, "backlash_rad", wear_backlash), "frictionloss_nm", wear_friction) + (
                   P(reg, "backlash_wear_rad_per_nm_rev", "rad/(N·m·rev)", None, "unknown: regressed over deployment", "the wear regression of re-identified backlash",
                     "no", "encoder-blind, like backlash itself"),
                   P(reg, "friction_growth_nm_per_h", "N·m/h", None, "unknown: regressed over deployment", "the wear regression of live re-identification (T10)", "yes")),
               (R.ARCHARD_1953, R.FLODIN_1997, R.LU_MEEKER_1993), "backlash(u) = b0 + k_b·Σ|τ|·Δrev (Archard); Fs(h) = Fs0 + k_f·h (linear)",
               "models/actuator/dcmotor", "proposed: bam_rack_twin takes no usage input yet",
               note="RobotDx gearbox.wear (K6) flags a 20 % friction change between re-identifications: the same drift seen as parameters")
    res = residual("M6", m5w, mlp(("position error", "velocity", "torque command"), "residual torque (N·m)", (32, 32)),
                   (R.NGUYEN_TUONG_2010, R.ZENG_2020, R.KOVALEV_2026))
    net = learned("M7", "Actuator network (black box)", mlp(("position error", "velocity"), "torque (N·m)", (32, 32, 32)),
                  (R.HWANGBO_2019, R.HWANGBO_2019_ARXIV, R.ZHU_2025),
                  note="Hwangbo et al. 2019's ANYmal net: 3 × 32 softsign over t, t − 10 ms, t − 20 ms; a longer history when ripple or backlash matter (Zhu 2025)")
    rungs = (m0, m2, m3, m4, m5, m5w, res, net)
    diagnostics = (
        dx("servo.stop_error", "<=", None, "mrad", "the joint's share of the 5 mm tool gate (STOP_ALLOCATION_MRAD: 3.6 / 6.7 / 10 mrad)", "servo.stop_error"),
        dx("servo.twin_fidelity", "<=", 2.0, "× floor", "T2's per-class limit (FIDELITY_CLASS): warn before the 1.5× tape limit fails", "servo.twin_fidelity"),
        dx("servo.torque_fidelity", "<=", 2.0, "× scatter", "", "servo.torque_fidelity"),
        dx("servo.warm_cold", "<=", 1.5, "× floor", "", "servo.warm_cold"),
        dx("servo.envelope", "<=", 5.0, "%", "", "servo.envelope"),
        dx("servo.thermal", "<=", 5.0, "°C", "", "servo.thermal"),
        drift("servo", "servo.twin_fidelity", Forecast(*HOURS, "linear", ("frictionloss_nm", "backlash_rad"),
                                                       "fit the drift ratio's history on deployment hours, solve for the threshold (backlash's "
                                                       "torque-weighted revolutions convert at the station's duty)"),
              robotdx="gearbox.wear", note="RobotDx's gearbox.wear watches the same drift through re-identified parameters (K6)"),
    )
    gates = (
        gate("servo.stop_error", "<=", None, "mrad", "T4", "the joint's allocation of the 5 mm tool gate, per station (STOP_ALLOCATION_MRAD)"),
        # WHY the acceptance targets themselves (2026-11-10, proposal 2 step 4): these were literals beside bam_rack_twin's own constants;
        # servo_gates holds each once and bam_rack_twin's gates read it too
        gate("servo.twin_fidelity", *rule_of(servo_gates.FIDELITY_TAPES), "× floor", "T2"),
        gate("servo.torque_fidelity", *rule_of(servo_gates.TORQUE_RATIO), "× scatter", "T3"),
        gate("servo.warm_cold", *rule_of(servo_gates.FIDELITY_TAPES), "× floor", "T9"),
        gate("servo.envelope", *rule_of(servo_gates.SPEED_PCT), "%", "T7"),
        gate("servo.thermal", *rule_of(servo_gates.THERMOCOUPLE_C), "°C", "T8"),
    )
    tests = (
        T("servo", "plateaus", "Velocity plateaus", "bench",
          ("frictionloss_nm", "damping_nm_s_rad", "friction_weakening_nm_s_rad", "friction_stribeck_drop_nm", "ripple_harmonics"),
          "6-8 constant speeds each way, each over more than one rotor turn", exists="bam_rack_twin schedule.py family plateaus (F2); identify.py's friction fit"),
        T("servo", "gravity", "Slow gravity sweeps", "bench", ("gravity_nm",), "slow position sweeps both ways over the range",
          exists="bam_rack_twin schedule.py family gravity; identify.py fit_gravity"),
        T("servo", "chirp", "Chirps", "bench", ("armature_kg_m2", "current_loop_hz"), "position chirps across the closed-loop band",
          exists="bam_rack_twin schedule.py family chirp (F3r); inertia.py fit_inertia_by_replay"),
        T("servo", "stop_hold", "Stop-and-hold tapes", "bench", ("friction_capture_nm",), "stops followed by holds of varied rest",
          exists="proposed: no schedule family varies the rest yet (robotparts' twin names the experiment)"),
        T("servo", "steps", "Step targets", "bench", ("command_delay_s",), "steps; cross-correlate the command with the q-current",
          exists="proposed: no fit of the delay yet"),
        T("servo", "staircase", "Staircase holds + clamp", "bench", ("backlash_rad", "gear_stiffness_nm_rad"),
          "a staircase with the camera on the output tag; a clamp (output locked) for the stiffness", ("D405 / D435 + ArUco on the output", "output clamp"),
          exists="bam_rack_twin schedule.py family staircase (F7); backlash.py (gap from staircase holds); the clamp is proposed"),
        T("servo", "known_mass", "Known mass", "bench", ("torque_scale", "kt_out_nm_a"), "gravity sweeps bare and with a weighed mass at a known radius",
          ("a weighed mass",), exists="bam_rack_twin drive_gain.py (T6)"),
        T("servo", "board_calibration", "Board calibration (measure-only)", "bench", ("phase_resistance_ohm",), "moteus_tool --calibrate --cal-no-update",
          exists="moteus_tool (mjbots)"),
        T("servo", "top_speed", "Top-speed plateaus", "bench", ("voltage_available_v", "kt_out_nm_a"), "plateaus up to the speed the bus allows",
          exists="bam_rack_twin envelope.py (T7)"),
        T("servo", "heating", "Heating run", "bench", ("thermal_r_c",), "a long hold at high current with a thermocouple on the winding", ("thermocouple",),
          exists="bam_rack_twin hardware/thermal.py + thermal_model.py (T8)"),
        T("servo", "full_schedule", "Full schedule re-run", "bench",
          ("armature_kg_m2", "gravity_nm", "frictionloss_nm", "damping_nm_s_rad", "friction_weakening_nm_s_rad", "friction_stribeck_drop_nm"),
          "the frozen schedule's train split again, then identify.py, then the held-out score", recalibration=True,
          exists="bam_rack_twin schedule.py build + hardware session --plan + identify.py", duration="~25 min (CAN 11's runnable schedule)"),
        T("servo", "live_reid", "Live re-identification", "deployed", ("armature_kg_m2", "frictionloss_nm", "damping_nm_s_rad", "gravity_nm"),
          "RLS with forgetting on the board's own q, qd and torque while the joint works; a 60 s routine restores T2", recalibration=True,
          exists="bam_rack_twin live_reid.py (T10); pidtuna identify.Rls", duration="60 s"),
        T("servo", "shift_staircase", "Shift-start staircase", "deployed", ("backlash_rad",), "a 2-minute staircase at shift start, the cell camera on the output tag",
          ("a tag on the output in the cell camera's view",), recalibration=True, exists="proposed", duration="2 min"),
        T("servo", "wear_regression", "Wear regression", "deployed", ("backlash_wear_rad_per_nm_rev", "friction_growth_nm_per_h"),
          "regress each re-identified backlash and friction on the usage logged since commissioning", exists=NOT_TRAINED),
    )
    return rungs, diagnostics, gates, tests


# --- motor ------------------------------------------------------------------------------------------------------------------------

def motor(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Ideal torque source", pick(m, "motorconst", "rotor_inertia"), (R.KRAUSE_2013, R.SICILIANO_2009), "τ = Kt i; J_r ω̇ = τ − τ_load",
              "models/actuator/ideal", "robotparts models/actuator/ideal (as a 1:1 actuator)")
    m4 = phys(card, "M4", "+ cogging (rotor-periodic ripple)", grow(m0, *pick(m, "cogging")), (R.JAHNS_1996,), "τ = Kt i − Σ a_k sin(k θ + φ_k)",
              "models/actuator/ripple", "robotparts models/actuator/ripple")
    m5 = phys(card, "M5", "DC motor electrics and heat (today's model)", m, (R.KRAUSE_2013, R.MUJOCO_DCMOTOR, R.KRISHNAN_2010), card.model.equation,
              "models/actuator/dcmotor", "robotparts models/actuator/dcmotor (MuJoCo 3.16's dcmotor)", current=True)
    m5w = phys(card, "M5.wear", "+ bearing friction that grows with hours", grow(m5,
               P(reg, "bearing_friction_nm", "N·m", None, "unknown (a new motor's no-load current × Kt)", "no-load current at constant speed", "partial",
                 wear=Wear(*HOURS, "linear", "bearing_friction_growth_nm_per_h", "bearing wear")),
               P(reg, "bearing_friction_growth_nm_per_h", "N·m/h", None, "unknown: regressed over deployment", "no-load current re-measured over hours", "partial")),
               (R.LU_MEEKER_1993, R.ARMSTRONG_1994), "τ_loss(h) = τ_b0 + k·h", "models/actuator/dcmotor", "proposed")
    res = residual("M6", m5w, mlp(("q-axis current", "rotor speed", "winding temperature"), "residual shaft torque (N·m)", (32, 32)),
                   (R.NGUYEN_TUONG_2010, R.ZENG_2020))
    net = learned("M7", "Motor network (black box)", mlp(("q-axis current command", "rotor speed"), "shaft torque (N·m)", (32, 32, 32)),
                  (R.HWANGBO_2019, R.HWANGBO_2019_ARXIV))
    diagnostics = (dx("motor.twin_torque", "<=", 2.0, "× floor"), dx("motor.winding_temp", "<=", 5.0, "°C", "T8's limit at the motor"),
                   drift("motor", "motor.twin_torque", Forecast(*HOURS, "linear", ("bearing_friction_nm",))))
    gates = (gate("motor.twin_torque", "<=", 1.5, "× floor"), gate("motor.winding_temp", "<=", 5.0, "°C"))
    tests = (
        T("motor", "board_calibration", "Board calibration", "bench", ("resistance", "inductance", "motorconst"), "moteus_tool --calibrate (R, L, Kv)",
          exists="moteus_tool (mjbots)"),
        T("motor", "rotor_sweep", "Rotor-angle sweep", "bench", ("cogging",), "a slow sweep over more than one rotor turn", exists="proposed: alone; inside a servo, the plateaus"),
        T("motor", "dyno_map", "Dyno torque-speed map", "bench", ("motorconst", "rotor_inertia", "bearing_friction_nm"), "torque sensor between the motor and a load motor",
          ("dyno with a torque sensor",), recalibration=True, exists="proposed: needs a dyno"),
        T("motor", "heating", "Heating run", "bench", ("thermal",), "a long run at rated current with a thermocouple", ("thermocouple",), exists="proposed"),
        T("motor", "no_load", "No-load current", "deployed", ("bearing_friction_nm", "motorconst"), "current at a constant speed while idle between picks",
          recalibration=True, exists="proposed"),
        T("motor", "wear_regression", "Wear regression", "deployed", ("bearing_friction_growth_nm_per_h",), "no-load friction against hours", exists=NOT_TRAINED),
    )
    return (m0, m4, m5, m5w, res, net), diagnostics, gates, tests


# --- gearbox -------------------------------------------------------------------------------------------------------------------------

def gearbox(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Ideal ratio", pick(m, "gear_ratio", "gearbox_input_inertia"), (R.SICILIANO_2009, R.MUJOCO_ARMATURE),
              "q_out = q_in / N; J_reflected = N² J_in", "models/actuator/ideal", "robotparts models/actuator/ideal")
    m3 = phys(card, "M3", "+ load-dependent mesh friction (efficiency)", grow(m0, *pick(m, "mesh_efficiency_eta", "output_friction_fraction")),
              (R.KIRCANSKI_1997, R.OLSSON_1998), "τ_out = η N τ_in; Coulomb grows with the transmitted load", "models/actuator/load", "robotparts models/actuator/load")
    m4 = phys(card, "M4", "+ backlash and torsional stiffness (today's model)", m, (R.NORDIN_2002, R.TUTTLE_1996, R.KIRCANSKI_1997), card.model.equation,
              "lab/models/actuator/twin", "robotparts lab/models/actuator/twin (M4.twin.backlash); bam_ws gear_backlash (MuJoCo)", current=True)
    m4w = phys(card, "M4.wear", "+ backlash that opens with use (Archard)",
               worn(m4.parameters, "backlash_rad", Wear("torque-weighted output revolutions", "N·m·rev", "archard", "backlash_wear_rad_per_nm_rev")) + (
                   P(reg, "backlash_wear_rad_per_nm_rev", "rad/(N·m·rev)", None, "unknown: regressed over deployment", "repeated backlash measurements over usage", "no"),),
               (R.ARCHARD_1953, R.FLODIN_1997), "backlash(u) = b0 + k·Σ|τ|·Δrev", "lab/models/actuator/twin", "proposed")
    res = residual("M6", m4w, mlp(("input angle", "output torque", "input speed"), "residual transmission error (rad)", (32, 32)), (R.NGUYEN_TUONG_2010, R.ZENG_2020))
    net = learned("M7", "Transmission network (black box)", mlp(("input angle", "input speed", "output torque"), "output angle error (rad)", (32, 32, 32), history=5),
                  (R.HWANGBO_2019, R.ZHU_2025), note="5 history samples: hysteresis and backlash need a longer memory (Zhu 2025)")
    diagnostics = (dx("gearbox.lost_motion", "<=", 2.0, "arcmin", "T5 judges the estimate's 95 % CI half-width, not the gap itself", "gearbox.backlash"),
                   dx("gearbox.twin_transmission", "<=", 2.0, "× floor"),
                   drift("gearbox", "gearbox.twin_transmission", Forecast("torque-weighted output revolutions", "N·m·rev", "archard", ("backlash_rad",)),
                         robotdx="gearbox.wear", note="RobotDx's gearbox.wear flags a 20 % friction change between re-identifications (K6)"))
    gates = (gate("gearbox.lost_motion", "<=", 2.0, "arcmin", "T5"), gate("gearbox.twin_transmission", "<=", 1.5, "× floor"))
    tests = (
        T("gearbox", "full_turn", "Full-turn ratio on camera", "bench", ("gear_ratio",), "one slow output turn: camera angle vs encoder count",
          ("D405 / D435 + ArUco on the output",), exists="bam_rack_twin ratio_checks.py"),
        T("gearbox", "clamp", "Clamp test", "bench", ("backlash_rad", "gear_stiffness_nm_rad"), "output locked, torque ramped both ways: the hysteresis loop",
          ("output clamp",), recalibration=True, exists="proposed on the rack; bam_rack_twin backlash.py reads the gap from staircase holds"),
        T("gearbox", "dyno_efficiency", "Dyno efficiency map", "bench", ("mesh_efficiency_eta", "output_friction_fraction", "gearbox_input_inertia"),
          "input and output torque over speed and load", ("dyno with input and output torque",), exists="proposed: needs a dyno"),
        T("gearbox", "shift_staircase", "Shift-start staircase", "deployed", ("backlash_rad",), "a staircase at shift start, the cell camera on the output",
          recalibration=True, exists="proposed"),
        T("gearbox", "wear_regression", "Wear regression", "deployed", ("backlash_wear_rad_per_nm_rev",), "backlash against torque-weighted revolutions", exists=NOT_TRAINED),
    )
    return (m0, m3, m4, m4w, res, net), diagnostics, gates, tests


# --- driver -----------------------------------------------------------------------------------------------------------------------------

def driver(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Ideal: the commanded current, capped", pick(m, "torque_cap_nm", "telemetry_rate_hz"), (R.MOTEUS_REFERENCE,), "i_q = clamp(i_cmd, ±cap)",
              implemented="the runner's --cap-nm (config)")
    m1 = phys(card, "M1", "+ transport delay and a first-order current loop", grow(m0, *pick(m, "command_delay_s", "current_loop_hz")),
              (R.KRISHNAN_2010, R.MOTEUS_REFERENCE), "i_q = LPF(current_loop_hz)[delay(i_cmd)]", implemented="bam_rack_twin TwinParameters.current_loop_hz / command_delay_s")
    m2 = phys(card, "M2", "+ voltage ceiling and board heating (today's model)", m, (R.KRAUSE_2013, R.MOTEUS_REFERENCE), card.model.equation,
              implemented="bam_rack_twin TwinParameters (drive terms) + the config receipt", current=True)
    m2w = phys(card, "M2.wear", "+ board cooling that ages with hours",
               worn(m2.parameters, "board_thermal", Wear(*HOURS, "linear", "board_thermal_growth_per_h", "thermal interface and fan ageing")) + (
                   P(reg, "board_thermal_growth_per_h", "K/W per h", None, "unknown: regressed over deployment", "board temperature rise per watt against hours", "yes"),),
               (R.LU_MEEKER_1993, R.MEEKER_1998), "R_th(h) = R_th0 + k·h", implemented="proposed")
    res = residual("M6", m2w, mlp(("current command", "rotor speed", "bus voltage"), "residual q-current (A)", (32, 32)), (R.NGUYEN_TUONG_2010,))
    net = learned("M7", "Drive network (black box)", mlp(("current command", "rotor speed", "bus voltage", "board temperature"), "q-current (A)", (32, 32, 32)),
                  (R.HWANGBO_2019,))
    diagnostics = (dx("driver.saturation", "<=", 2.0, "%", "RobotDx: limiter share warn 0.02", "driver.saturation"),
                   dx("driver.loop_rate", ">=", None, "Hz", "the expected rate − 10 % (RobotDx tolerance 0.1)", "driver.loop_rate"),
                   dx("driver.twin_current", "<=", 2.0, "× scatter", "T3's rule on the same quantity"),
                   dx("driver.twin_board_temp", "<=", 5.0, "°C"),
                   drift("driver", "driver.twin_current", Forecast(*HOURS, "linear", ("board_thermal",))))
    gates = (gate("driver.twin_current", "<=", 2.0, "× scatter"), gate("driver.twin_board_temp", "<=", 5.0, "°C"))
    tests = (
        T("driver", "torque_chirp", "Torque chirp, open loop", "bench", ("current_loop_hz", "command_delay_s"), "a current chirp with kp = kd = 0",
          exists="proposed: bam_rack_twin.schedule has open-loop torque commands, no loop fit"),
        T("driver", "heating", "Heating run", "bench", ("board_thermal",), "a long hold at high current; the board reports its temperature", exists="proposed"),
        T("driver", "config_receipt", "Config receipt + chirp", "bench", ("max_voltage_factor", "torque_cap_nm", "telemetry_rate_hz", "current_loop_hz"),
          "re-read the board's config and re-run the chirp", recalibration=True, exists="bam_rack_twin hardware/configcheck.py"),
        T("driver", "telemetry_reid", "Telemetry re-fit", "deployed", ("current_loop_hz", "command_delay_s"), "command vs reported current during work",
          recalibration=True, exists="proposed"),
        T("driver", "thermal_trend", "Thermal trend", "deployed", ("board_thermal", "board_thermal_growth_per_h"), "temperature rise per watt over the shift",
          exists=NOT_TRAINED),
    )
    return (m0, m1, m2, m2w, res, net), diagnostics, gates, tests


# --- encoder ------------------------------------------------------------------------------------------------------------------------

def encoder(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Ideal quantiser", pick(m, "counts_per_rev"), (R.WIDROW_2008,), "q_reported = round(q / lsb) lsb")
    m1 = phys(card, "M1", "+ noise and latency", grow(m0, *pick(m, "noise_sigma", "latency_s")), (R.MERRY_2010,), "q_reported(t) = round((q(t − d) + n) / lsb) lsb")
    m2 = phys(card, "M2", "+ eccentricity harmonics (today's model)", m, (R.ZHAO_2024,), card.model.equation, current=True)
    m2w = phys(card, "M2.wear", "+ a mount that loosens over vibration hours",
               worn(m2.parameters, "eccentricity_harmonics", Wear(*VIBRATION, "sqrt", "eccentricity_growth_mrad_per_sqrt_h", "the magnet or its mount working loose")) + (
                   P(reg, "eccentricity_growth_mrad_per_sqrt_h", "mrad/√h", None, "unknown: regressed over deployment", "camera vs encoder over a turn, repeated over hours", "partial"),),
               (R.JUNKER_1969, R.WHITMORE_1995), "e(h) = e0 + k √h")
    diagnostics = (dx("encoder.twin_noise", "<=", 2.0, "× floor"),
                   drift("encoder", "encoder.twin_noise", Forecast(*VIBRATION, "sqrt", ("eccentricity_harmonics",))))
    gates = (gate("encoder.twin_noise", "<=", 1.5, "× floor"),)
    tests = (
        T("encoder", "standstill", "Standstill capture", "bench", ("noise_sigma",), "the joint held still, 40 s of samples", exists="RobotDx encoder.standstill_noise (io-diagnostics)"),
        T("encoder", "camera_turn", "Camera vs encoder over a turn", "bench", ("counts_per_rev", "eccentricity_harmonics", "latency_s"),
          "a slow full turn with a tag on the output; cross-correlate for the delay", ("D405 / D435 + ArUco",), recalibration=True,
          exists="bam_rack_twin tag_track.py + ratio_checks.py"),
        T("encoder", "tag_in_service", "A tag in service", "deployed", ("eccentricity_harmonics", "latency_s"), "a fixed output tag in the cell camera during normal moves",
          recalibration=True, exists="proposed"),
        T("encoder", "wear_regression", "Wear regression", "deployed", ("eccentricity_growth_mrad_per_sqrt_h",), "eccentricity against vibration hours", exists=NOT_TRAINED),
    )
    return (m0, m1, m2, m2w), diagnostics, gates, tests


# --- arm sub-assembly ----------------------------------------------------------------------------------------------------------------

def arm_sub(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Nominal kinematics (CAD)", pick(m, "link_lengths"), (R.DH_1955, R.SICILIANO_2009), "tip = FK(q; CAD links)")
    m1 = phys(card, "M1", "+ joint zero offsets", grow(m0, *pick(m, "joint_offsets")), (R.HOLLERBACH_WAMPLER_1996,), "tip = FK(q + δq; links)")
    m2 = phys(card, "M2", "+ link inertials and loop closure (today's model)", m, (R.ATKESON_1986, R.GAUTIER_1990, R.SWEVERS_1997), card.model.equation, current=True,
              implemented="bam_calibration arm_model.py (kinematics; five-bar closure inside FK)")
    m2w = phys(card, "M2.wear", "+ joint zeros that drift over vibration hours",
               worn(m2.parameters, "joint_offsets", Wear(*VIBRATION, "sqrt", "joint_offset_drift_rad_per_sqrt_h", "homing datum and couplings working loose")) + (
                   P(reg, "joint_offset_drift_rad_per_sqrt_h", "rad/√h", None, "unknown: regressed over deployment", "tag checks repeated over hours", "yes"),),
               (R.JUNKER_1969, R.WHITMORE_1995), "δq(h) = δq0 + k √h")
    joints = ("joint 1 error", "joint 2 error", "joint 3 error", "joint 1 speed", "joint 2 speed", "joint 3 speed")
    res = residual("M6", m2w, mlp(joints + ("joint 1 torque", "joint 2 torque", "joint 3 torque"), "residual joint torques (N·m)", (64, 64), n_outputs=3),
                   (R.NGUYEN_TUONG_2010, R.ZENG_2020))
    net = learned("M7", "Sub-assembly network (black box)", mlp(joints, "joint torques (N·m)", (64, 64, 64), n_outputs=3), (R.HWANGBO_2019,))
    diagnostics = (dx("sub.tip_error_at_stop", "<=", None, "mm", "its share of the 5 mm tool gate, split across its joints by lever", "arm.tool_error_at_stop"),
                   dx("sub.twin_fidelity", "<=", 2.0, "× floor", robotdx="arm.sim_vs_real"),
                   drift("arm_subassembly", "sub.twin_fidelity", Forecast(*VIBRATION, "sqrt", ("joint_offsets",)), robotdx="arm.calibration_drift",
                         note="RobotDx's arm.calibration_drift re-measures the tool pose against tags in service"))
    gates = (gate("sub.tip_error_at_stop", "<=", None, "mm", note="its share of the 5 mm tool gate"), gate("sub.twin_fidelity", "<=", 1.5, "× floor"))
    tests = (
        T("arm_subassembly", "closed_chain", "Closed-chain kinematic calibration", "bench", ("link_lengths", "joint_offsets", "closure_tolerance"),
          "couple to a partner arm, move through the self-motion, joint encoders only", recalibration=True,
          exists="bam_ws bam_calibration calibrate.py (UR-style dual-arm closed chain)"),
        T("arm_subassembly", "excitation", "Excitation trajectories", "bench", ("link_inertials",), "periodic excitation (Swevers 1997) and a least-squares fit",
          exists="proposed"),
        T("arm_subassembly", "tag_check", "Tip tag check", "deployed", ("joint_offsets",), "a tag on the tip seen by the cell camera at known poses",
          recalibration=True, exists="proposed (RobotDx arm.calibration_drift is the check)"),
        T("arm_subassembly", "wear_regression", "Wear regression", "deployed", ("joint_offset_drift_rad_per_sqrt_h",), "joint-zero drift against vibration hours",
          exists=NOT_TRAINED),
    )
    return (m0, m1, m2, m2w, res, net), diagnostics, gates, tests


# --- 6-DOF arm ----------------------------------------------------------------------------------------------------------------------------

def arm(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Nominal kinematics (URDF / DH)", pick(m, "base_frame", "tool_frame"), (R.DH_1955, R.UR_DH), "tool = base · FK(q; nominal DH) · tool frame",
              implemented="the UR5e URDF (MuJoCo Menagerie) via pin_utils")
    m1 = phys(card, "M1", "+ joint zero offsets", grow(m0, *pick(m, "joint_zero_offsets")), (R.HOLLERBACH_WAMPLER_1996,), "FK(q + δq)")
    m2 = phys(card, "M2", "+ geometric (DH) errors", grow(m1, *pick(m, "dh_errors")), (R.HAYATI_1983, R.OKAMURA_1996, R.HOLLERBACH_2016), "FK(q + δq; DH + δDH)",
              implemented="bam_calibration (closed chain); the multi-arm study's 58-parameter chain (branch)")
    m3 = phys(card, "M3", "+ joint compliance and link inertials (today's model)", m, (R.SPONG_1987, R.ATKESON_1986, R.GAUTIER_1990, R.SWEVERS_1997),
              card.model.equation, current=True)
    m3w = phys(card, "M3.wear", "+ joint compliance that grows with use (Archard)",
               worn(m3.parameters, "joint_compliance", Wear("torque-weighted joint revolutions", "N·m·rev", "archard", "compliance_wear_per_nm_rev")) + (
                   P(reg, "compliance_wear_per_nm_rev", "rad/N·m per N·m·rev", None, "unknown: regressed over deployment", "loaded poses repeated over usage", "partial"),),
               (R.ARCHARD_1953, R.FLODIN_1997), "c(u) = c0 + k·Σ|τ|·Δrev")
    joints = tuple(f"joint {i} {s}" for s in ("error", "speed") for i in range(1, 7))
    res = residual("M6", m3w, mlp(joints + tuple(f"joint {i} torque" for i in range(1, 7)), "residual joint torques (N·m)", (64, 64), n_outputs=6),
                   (R.NGUYEN_TUONG_2010, R.ZENG_2020))
    net = learned("M7", "Arm network (black box)", mlp(joints, "joint torques (N·m)", (64, 64, 64), n_outputs=6), (R.HWANGBO_2019,),
                  note="one net per joint (Hwangbo) is the cheaper start; a whole-arm net learns coupling and needs the most coverage")
    diagnostics = (dx("arm.tool_error_at_stop", "<=", 5.0, "mm", "RobotDx: 5 mm ('within 5mm should be ok for grasping'); Zach to confirm 5 vs 1 mm", "arm.tool_error_at_stop"),
                   dx("arm.sim_vs_real", "<=", 2.0, "× floor", robotdx="arm.sim_vs_real"),
                   drift("arm_6dof", "arm.sim_vs_real", Forecast("torque-weighted joint revolutions", "N·m·rev", "archard", ("joint_compliance",)),
                         robotdx="arm.calibration_drift"))
    gates = (gate("arm.tool_error_at_stop", "<=", 5.0, "mm"), gate("arm.sim_vs_real", "<=", 1.5, "× floor"))
    tests = (
        T("arm_6dof", "kinematic_calibration", "Kinematic calibration", "bench", ("base_frame", "tool_frame", "joint_zero_offsets", "dh_errors"),
          "many poses with a tracked tool (or a coupled partner arm)", recalibration=True,
          exists="bam_ws bam_calibration; the separate UR kinematic calibration package Zach plans"),
        T("arm_6dof", "loaded_poses", "Loaded poses", "bench", ("joint_compliance",), "the tool pose under known payloads at several poses", exists="proposed"),
        T("arm_6dof", "excitation", "Excitation trajectories", "bench", ("link_inertials",), "periodic excitation and the base-parameter fit", exists="proposed"),
        T("arm_6dof", "tool_tag", "Tool tag check", "deployed", ("joint_zero_offsets", "tool_frame", "base_frame"), "a tag on the tool seen in service",
          recalibration=True, exists="proposed (RobotDx arm.calibration_drift is the check)"),
        T("arm_6dof", "wear_regression", "Wear regression", "deployed", ("compliance_wear_per_nm_rev",), "compliance against torque-weighted revolutions",
          exists=NOT_TRAINED),
    )
    return (m0, m1, m2, m3, m3w, res, net), diagnostics, gates, tests


# --- 6-DOF arm + gripper -------------------------------------------------------------------------------------------------------------

def arm_gripper(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Rigid gripper at the TCP", pick(m, "tcp_offset"), (R.SICILIANO_2009,), "tool = arm · tcp_offset")
    m1 = phys(card, "M1", "+ finger width map", grow(m0, *pick(m, "finger_width_map")), (R.PRATTICHIZZO_2016,), "width = f(command)")
    m2 = phys(card, "M2", "+ grip force and contact friction (today's model)", m, (R.PRATTICHIZZO_2016, R.MUJOCO_CONTACT), card.model.equation, current=True)
    m2w = phys(card, "M2.wear", "+ finger pads that glaze with grasps",
               worn(m2.parameters, "contact_friction", Wear("grasp cycles", "cycles", "linear", "contact_friction_change_per_cycle", "pad wear and glazing")) + (
                   P(reg, "contact_friction_change_per_cycle", "1/cycle", None, "unknown: regressed over deployment", "pull-out tests repeated over cycles", "partial"),),
               (R.LU_MEEKER_1993, R.ARCHARD_1953), "μ(n) = μ0 + k·n")
    res = residual("M6", m2w, mlp(("width command", "measured width", "finger current"), "residual width (m)", (32, 32)), (R.NGUYEN_TUONG_2010,))
    net = learned("M7", "Gripper network (black box)", mlp(("width command", "width", "finger current"), "finger force (N)", (32, 32, 32), history=5),
                  (R.HWANGBO_2019,))
    diagnostics = (dx("pick.grasp_pose_error", "<=", 5.0, "mm", "RobotDx: limits 5 mm", "pick.grasp_pose_error"),
                   dx("pick.twin_grasp_fidelity", "<=", 2.0, "× floor"),
                   drift("arm_6dof_gripper", "pick.twin_grasp_fidelity", Forecast("grasp cycles", "cycles", "linear", ("contact_friction",))))
    gates = (gate("pick.grasp_pose_error", "<=", 5.0, "mm"), gate("pick.twin_grasp_fidelity", "<=", 1.5, "× floor"))
    tests = (
        T("arm_6dof_gripper", "tcp_tag", "TCP tag", "bench", ("tcp_offset",), "a tag on the fingers at known arm poses", recalibration=True, exists="proposed"),
        T("arm_6dof_gripper", "open_close", "Open / close cycles", "bench", ("finger_width_map",), "width command steps, width measured", exists="proposed"),
        T("arm_6dof_gripper", "force_gauge", "Force gauge", "bench", ("grip_force_map",), "a force gauge in the jaws at each command", ("force gauge",), exists="proposed"),
        T("arm_6dof_gripper", "pull_out", "Pull-out tests", "bench", ("contact_friction",), "pull a gripped object per material", exists="proposed"),
        T("arm_6dof_gripper", "grasp_outcomes", "Live grasp outcomes", "deployed", ("contact_friction",), "refit friction from slips in live picks per material",
          recalibration=True, exists="proposed"),
        T("arm_6dof_gripper", "wear_regression", "Wear regression", "deployed", ("contact_friction_change_per_cycle",), "friction against grasp cycles",
          exists=NOT_TRAINED),
    )
    return (m0, m1, m2, m2w, res, net), diagnostics, gates, tests


# --- cameras -------------------------------------------------------------------------------------------------------------------------------

def camera_rgb(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Pinhole", pick(m, "fx_fy", "cx_cy", "extrinsics"), (R.ZHANG_2000,), "p = K [R | t] X")
    m1 = phys(card, "M1", "+ Brown-Conrady distortion", grow(m0, *pick(m, "distortion")), (R.BROWN_1966, R.HEIKKILA_1997, R.ZHANG_2000),
              "radial (k1, k2, k3) and tangential (p1, p2) distortion")
    m2 = phys(card, "M2", "+ exposure response and latency (today's model)", m, (R.ZHANG_2000,), card.model.equation, current=True)
    m3 = phys(card, "M3", "Rolling shutter: + line delay", grow(m2, P(reg, "line_delay_s", "s", None, "unknown (sensor datasheet readout time / rows)",
                                                                    "a moving target at known speed", "yes")),
              (R.OTH_2013, R.MEINGAST_2005), "row v exposed at t0 + v · line_delay")
    m3w = phys(card, "M3.wear", "+ a mount that loosens over vibration hours",
               worn(m3.parameters, "extrinsics", Wear(*VIBRATION, "sqrt", "extrinsic_drift_mm_per_sqrt_h", "the camera's mount working loose")) + (
                   P(reg, "extrinsic_drift_mm_per_sqrt_h", "mm/√h", None, "unknown: regressed over deployment", "a fixed tag's pose repeated over hours", "yes"),),
               (R.JUNKER_1969, R.WHITMORE_1995), "pose offset(h) = e0 + k √h")
    res = residual("M6", m3w, Architecture("B-spline grid", ("pixel u", "pixel v"), "residual ray offset (px)", 1, None, (), "", 2, 3000), (R.SCHOPS_2020,),
                   note="a 50 × 30 control-point grid of 2-D offsets (Schöps et al. 2020's generic model); no black-box rung: a camera model must stay "
                        "projective to measure")
    diagnostics = (dx("camera.intrinsics", "<=", 0.5, "px", "RobotDx's proposed warn level", "camera.intrinsics"),
                   dx("camera.frame_rate", ">=", None, "Hz", "the set rate − 10 %", "camera.frame_rate"),
                   dx("camera.sim_overlay", "<=", 2.0, "× floor", robotdx="camera.sim_overlay"),
                   drift("camera_rgb", "camera.sim_overlay", Forecast(*VIBRATION, "sqrt", ("extrinsics",)), robotdx="camera.extrinsic_drift",
                         note="RobotDx's camera.extrinsic_drift watches a fixed tag move from where calibration put it (D405 6036 moved 28 px, Oct 21)"))
    gates = (gate("camera.intrinsics", "<=", 0.5, "px"), gate("camera.sim_overlay", "<=", 1.5, "× floor"))
    tests = (
        T("camera_rgb", "charuco", "ChArUco views", "bench", ("fx_fy", "cx_cy", "distortion"), "a board in 20+ poses across the image", recalibration=True,
          exists="bam_rack_twin calib.py (bundle adjustment); bam_calibration docs/ref camera_calibration_v2.py"),
        T("camera_rgb", "tag_poses", "Tags at known poses", "bench", ("extrinsics",), "the rack's tags at CAD poses", exists="bam_rack_twin calib.py"),
        T("camera_rgb", "grey_card", "Exposure sweep on a grey card", "bench", ("exposure_response",), "DN against lux × exposure", exists="proposed"),
        T("camera_rgb", "led_blink", "LED blink", "bench", ("latency_s",), "an LED switched on a stamped clock", exists="proposed"),
        T("camera_rgb", "moving_target", "Moving target", "bench", ("line_delay_s",), "a target at known speed across the rows (Oth 2013)", exists="proposed"),
        T("camera_rgb", "fixed_tag", "Fixed tag in service", "deployed", ("extrinsics",), "re-solve the pose when a fixed tag moves", recalibration=True,
          exists="RobotDx marker_drift (io-diagnostics stock/camera.py) is the check; the re-solve is proposed"),
        T("camera_rgb", "wear_regression", "Wear regression", "deployed", ("extrinsic_drift_mm_per_sqrt_h",), "pose drift against vibration hours", exists=NOT_TRAINED),
    )
    return (m0, m1, m2, m3, m3w, res), diagnostics, gates, tests


def camera_rgbd(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Ideal stereo", pick(m, "baseline_m", "depth_scale", "depth_to_color"), (R.KHOSHELHAM_2012,), "z = f b / d")
    m1 = phys(card, "M1", "+ disparity noise (today's model)", m, (R.KHOSHELHAM_2012,), card.model.equation, current=True)
    m2 = phys(card, "M2", "+ depth bias", grow(m1, P(reg, "depth_bias_coeffs", "mm", None, "unknown", "a flat target at measured distances over the range", "yes",
                                                  "a bias that grows with z and varies across the image")),
              (R.HERRERA_2012,), "z_true = z + b(u, v, z)")
    m2w = phys(card, "M2.wear", "+ a depth-to-colour mount that loosens over vibration hours",
               worn(m2.parameters, "depth_to_color", Wear(*VIBRATION, "sqrt", "depth_to_color_drift_mm_per_sqrt_h")) + (
                   P(reg, "depth_to_color_drift_mm_per_sqrt_h", "mm/√h", None, "unknown: regressed over deployment", "the colour-to-depth residual of a tag, over hours", "yes"),),
               (R.JUNKER_1969, R.WHITMORE_1995), "offset(h) = e0 + k √h")
    res = residual("M6", m2w, Architecture("B-spline grid", ("pixel u", "pixel v", "measured depth"), "depth correction (mm)", 1, None, (), "", 1, 3840),
                   (R.HERRERA_2012, R.SCHOPS_2020), note="40 × 24 control points × 4 depth bands; no black-box rung (the depth must stay geometric)")
    diagnostics = (dx("depth.z_accuracy", "<=", 2.0, "% of Z", "RobotDx: > 2 % poor", "depth.z_accuracy"),
                   dx("depth.plane_rms", "<=", 1.0, "% of Z", "RobotDx: > 1 % poor", "depth.plane_rms"),
                   dx("depth.fill_rate", ">=", 98.0, "%", "RobotDx: < 98 % poor", "depth.fill_rate"),
                   dx("depth.cloud_vs_sim", "<=", 2.0, "× floor", robotdx="depth.cloud_vs_sim"),
                   drift("camera_rgbd", "depth.cloud_vs_sim", Forecast(*VIBRATION, "sqrt", ("depth_to_color",)), robotdx="depth.health_check",
                         note="RobotDx's depth.health_check reads the RealSense self-calibration score (recalibrate at >= 0.75)"))
    gates = (gate("depth.z_accuracy", "<=", 1.0, "% of Z", note="RobotDx: < 1 % good"), gate("depth.plane_rms", "<=", 0.4, "% of Z", note="RobotDx: < 0.4 % good"),
             gate("depth.fill_rate", ">=", 99.0, "%", note="RobotDx: > 99 % good"), gate("depth.cloud_vs_sim", "<=", 1.5, "× floor"))
    tests = (
        T("camera_rgbd", "factory", "Factory calibration read", "bench", ("baseline_m", "depth_scale", "depth_to_color"), "read per frame from the device",
          exists="intel_rgbd real.py"),
        T("camera_rgbd", "flat_target", "Flat target at distances", "bench", ("subpixel_sigma", "depth_bias_coeffs"), "a flat target at measured distances",
          recalibration=True, exists="RobotDx depth_plane (io-diagnostics) measures it; the fit is proposed"),
        T("camera_rgbd", "self_calibration", "On-chip self-calibration", "deployed", ("depth_bias_coeffs", "depth_to_color"),
          "the device's own self-calibration on a textured wall, when its health score falls", recalibration=True,
          exists="proposed (RobotDx depth.health_check is the trigger)"),
        T("camera_rgbd", "wear_regression", "Wear regression", "deployed", ("depth_to_color_drift_mm_per_sqrt_h",), "offset against vibration hours", exists=NOT_TRAINED),
    )
    return (m0, m1, m2, m2w, res), diagnostics, gates, tests


def camera_hsi(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Ideal spectral bands", pick(m, "band_centres", "dark_white_refs"), (R.BURGER_2011,), "R(λ) = (DN − dark) / (white − dark)")
    m1 = phys(card, "M1", "+ band widths", grow(m0, *pick(m, "band_fwhm")), (R.BURGER_2011, R.KRUSE_1993), "each band a Gaussian of its FWHM")
    m2 = phys(card, "M2", "+ smile and keystone (today's model)", m, (R.MOUROULIS_2000,), card.model.equation, current=True)
    m3 = phys(card, "M3", "+ pushbroom line geometry", grow(m2, P(reg, "line_geometry", "m, rad", None, "unknown", "a target of known size carried on the belt", "yes",
                                                              "the line's pose and the belt distance per line")),
              (R.GUPTA_1997,), "a line camera swept by the belt")
    m3w = phys(card, "M3.wear", "+ references that drift with hours",
               worn(m3.parameters, "dark_white_refs", Wear(*HOURS, "linear", "reference_drift_per_h", "lamp ageing and dark current")) + (
                   P(reg, "reference_drift_per_h", "DN/h", None, "unknown: regressed over deployment", "the white tile's DN over hours", "yes"),),
               (R.LU_MEEKER_1993,), "white(h) = w0 + k·h")
    diagnostics = (dx("hsi.snr", ">=", 200.0, "dB", "RobotDx: proposed > 200 (HISUI spec)", "hsi.snr"),
                   dx("hsi.smile_keystone", "<=", 1.0, "px", "RobotDx: < 1 px", "hsi.smile_keystone"),
                   dx("hsi.twin_cube", "<=", 2.0, "× floor"),
                   drift("camera_hsi", "hsi.twin_cube", Forecast(*HOURS, "linear", ("dark_white_refs",))))
    gates = (gate("hsi.smile_keystone", "<=", 1.0, "px"), gate("hsi.twin_cube", "<=", 1.5, "× floor"))
    tests = (
        T("camera_hsi", "lamp_lines", "Spectral lamp lines", "bench", ("band_centres", "band_fwhm"), "a mercury-argon lamp's known lines", exists="proposed"),
        T("camera_hsi", "bar_targets", "Bar targets", "bench", ("smile_keystone_map",), "spectral and spatial bars across the field", exists="proposed"),
        T("camera_hsi", "belt_target", "Belt target", "bench", ("line_geometry",), "a target of known size carried at known speed", exists="proposed"),
        T("camera_hsi", "references", "Dark and white references", "bench", ("dark_white_refs",), "shutter closed, then a white tile", recalibration=True,
          exists="proposed"),
        T("camera_hsi", "reference_tile", "White tile each shift", "deployed", ("dark_white_refs",), "a white tile at the belt's edge, read every shift",
          recalibration=True, exists="proposed"),
        T("camera_hsi", "wear_regression", "Wear regression", "deployed", ("reference_drift_per_h",), "white DN against hours", exists=NOT_TRAINED),
    )
    return (m0, m1, m2, m3, m3w), diagnostics, gates, tests


# --- conveyor ---------------------------------------------------------------------------------------------------------------------------

def conveyor(reg, card):
    m = card.model.parameters
    m0 = phys(card, "M0", "Ideal belt: kinematics and a rigid mass", pick(m, "drum_radius_m", "gear_ratio", "moving_mass_kg", "load_mass_kg", "encoder_counts_per_m"),
              (R.ZHANG_XIA_2011,), "x = θ_motor r / N; (m + m_load) ẍ = F", "models/actuator/ideal", "pidtuna plants/conveyor_truths.py (the nominal model)")
    m2 = phys(card, "M2", "Coulomb + viscous friction", grow(m0, *pick(m, "coulomb_n", "viscous_n_s_m")), (R.ARMSTRONG_1994, R.ZHANG_XIA_2011),
              "− Fc sign(ẋ) − b ẋ", "models/actuator/coulomb_viscous", "pidtuna conveyor nominal (coulomb, viscous)")
    m3 = phys(card, "M3", "+ static friction (Stribeck)", grow(m2, *pick(m, "static_n")), (R.ARMSTRONG_1994,), "breakaway Fs falling to Fc", "models/actuator/stribeck",
              "pidtuna servo_sim Truth (static, stribeck speed)")
    m4 = phys(card, "M4", "+ belt stretch: drum and load as two masses", m, (R.HE_2017, R.SPONG_1987), card.model.equation, current=True,
              implemented="pidtuna plants/conveyor_truths.py (hidden truth: stretch as a spring between drum and load)")
    m4w = phys(card, "M4.wear", "+ friction that grows with belt distance",
               worn(m4.parameters, "coulomb_n", Wear("belt distance", "km", "linear", "coulomb_growth_n_per_km", "idler bearings and slider bed wear")) + (
                   P(reg, "coulomb_growth_n_per_km", "N/km", None, "unknown: regressed over deployment", "live re-identification against belt distance", "yes"),),
               (R.LU_MEEKER_1993, R.ZHANG_XIA_2011), "Fc(s) = Fc0 + k·s")
    res = residual("M6", m4w, mlp(("belt speed error", "belt speed", "motor current"), "residual drive force (N)", (32, 32)), (R.NGUYEN_TUONG_2010, R.ZENG_2020))
    net = learned("M7", "Belt network (black box)", mlp(("position error", "belt speed"), "drive force (N)", (32, 32, 32)), (R.HWANGBO_2019, R.HWANGBO_2019_ARXIV))
    diagnostics = (dx("conveyor.object_position", "<=", 5.0, "mm", "the arm's 5 mm tool gate: the object must be where the arm reaches"),
                   dx("conveyor.twin_fidelity", "<=", 2.0, "× floor"),
                   drift("conveyor", "conveyor.twin_fidelity", Forecast("belt distance", "km", "linear", ("coulomb_n",))))
    gates = (gate("conveyor.object_position", "<=", 5.0, "mm"), gate("conveyor.twin_fidelity", "<=", 1.5, "× floor"))
    tests = (
        T("conveyor", "tag_metre", "A tag carried a metre", "bench", ("drum_radius_m", "gear_ratio"), "drum turns against the camera's distance", exists="proposed"),
        T("conveyor", "speed_steps", "Speed steps with and without load", "bench", ("moving_mass_kg", "load_mass_kg", "stretch_stiffness_n_m", "stretch_damping_n_s_m"),
          "speed steps, a camera on a belt tag for the stretch", exists="pidtuna identify.py on the conveyor plant (sim)"),
        T("conveyor", "plateaus", "Velocity plateaus", "bench", ("coulomb_n", "viscous_n_s_m", "static_n"), "constant belt speeds both ways",
          recalibration=True, exists="pidtuna identify.py (linear axis)"),
        T("conveyor", "live_reid", "Live re-identification", "deployed", ("coulomb_n", "viscous_n_s_m", "load_mass_kg"), "RLS on drive current during production",
          recalibration=True, exists="pidtuna identify.Rls (recursive)"),
        T("conveyor", "wear_regression", "Wear regression", "deployed", ("coulomb_growth_n_per_km",), "friction against belt distance", exists=NOT_TRAINED),
    )
    return (m0, m2, m3, m4, m4w, res, net), diagnostics, gates, tests


LADDERS = {"servo": servo, "motor": motor, "gearbox": gearbox, "driver": driver, "encoder": encoder, "arm_subassembly": arm_sub, "arm_6dof": arm,
           "arm_6dof_gripper": arm_gripper, "camera_rgb": camera_rgb, "camera_rgbd": camera_rgbd, "camera_hsi": camera_hsi, "conveyor": conveyor}
GATE_PCT = servo_gates.MINIMUM_COVERAGE_PCT  # the schedule's coverage gate: visiting a cell once is what a schedule can promise before it runs


def build(reg) -> dict:
    """The v2 cards: every v1 card (and the conveyor) with its coverage gate, rungs, diagnostics, gates and test types."""
    out = {}
    for cid, card in reg.V1_CARDS.items():
        card = replace(card, coverage=replace(card.coverage, gate_pct=GATE_PCT))
        rungs, diagnostics, gates, tests = LADDERS[cid](reg, card)
        out[cid] = replace(card, rungs=tuple(rungs), diagnostics=tuple(diagnostics), gates=tuple(gates), tests=tuple(tests))
    return out
