"""The UR wrist test rig on the one-click seam (sim2real.rig): its parameters, its measured 1x noise, its calibration sequence and its own
MuJoCo twin, so ``sim2real.Twin.load("ur_wrist_test_rig").calibrate(on="sim", truth="sealed")`` recovers a sealed hidden truth.

The sequence (each a cards.calibration routine; each uses what the ones before it found):

1. servo.backlash_reversal_held   per moving joint, at its rest pose: the motor reverses slowly under a torque cap below the output's
                                  breakaway, so the output holds while the motor crosses the gear's gap; the gap is the motor encoder's span
                                  between the two flanks (two-sided by construction), less the gear's give at the cap
2. homing.single_touch            Zach's tview procedure (bam_ur_wrist.homing.tview_home_one, unchanged): seek the stop, relabel; the stall
                                  reads the motor half a gap (and the gear's give) past the stop, corrected by step 1's gap
3. servo.dynamics_regression      the coverage lane's refit (bam_ur_wrist.refit.fit: equation error per joint + the chain's gravity) on the
                                  house schedule's train runs, played in step 2's homed frame, then indirect inference against the twin
                                  (bam_ur_wrist.refit_rig's rule) with step 1's gaps in it
4. servo.command_delay_scan       the twin replayed over the train chirps at a grid of command delays (bam_ur_wrist.delay_scan's rule, on
                                  train runs only), with step 3's dynamics; the output-error minimum

WHY these and not every routine that names a wrist type: the rest need equipment the rig has not got or code that does not exist; the
calibration's ``not_run`` list says which and why (docs/one-click-seam.md).

Every number a person reads is in degrees, arcminutes, milliseconds or millimetres; the values stay SI.
"""

from __future__ import annotations

import contextlib
import functools
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from sim2real import rig as seam

from . import plant as wp

NAME = "ur_wrist_test_rig"
HERE = Path(__file__).resolve().parent
ARCMIN = math.pi / (180.0 * 60.0)
DEG = math.pi / 180.0
TAU = 2.0 * math.pi
CANS = (14, 15, 16)
INSTANCE = {14: "can14", 15: "can15", 16: "can16"}
# WHY all three since 2026-11-11 (the coordinator, from the real lane): CAN 14 is driven now (its real floor was measured driven, 0.100 deg),
# and on its side it carries the wrist's gravity (~0.23 N.m), the signal the gravity direction is recovered from. The coverage lane's own
# plans still hold it (bam_ur_wrist_coverage.rig.HELD); its plans are built here by that lane's builder, CAN 14 let move (_can14_driven)
MOVING = (14, 15, 16)
LINKS = ("hard_stop", "hard_stop_2", "hard_stop_3")   # the bodies CAN 14, 15, 16 turn (the it5 refit's masses)
PLANS = Path("/archive/datasets/bam_rig/rack_2026-11-10/ur_wrist/coverage/plans/plans")
# the house schedule's train families the dynamics fit plays (refit_rig.HIDDEN_TRAIN_FAMILIES, its sim-oracle set, + gravity sweeps and
# velocity plateaus: CAN 15's gravity and the viscous term); held out: the four *_heldout plans per board, as the real lane splits them
# WHY no multisine (2026-11-11): 108 s a board, the schedule's longest, and the chirp already excites the armature; with three boards driven
# the sequence's twin time is the budget (at load ~60 a twin second costs ~2 s of a core)
TRAIN_PLANS = ("gravity", "staircase", "dither", "plateaus", "chirp", "jog", "sweep")   # the coverage plans' families
HELD_OUT_PLANS = ("jog_heldout", "sweep_heldout")
GRAVITY_PLANS = ("gravity", "staircase")
DELAY_PLANS = ("chirp",)
PERIOD_S = 0.01
# the gear's torsional stiffness (estimate: a 43 mm gimbal's 10:1 planetary; none published), the prior every routine uses; known, not hidden
MESH_STIFFNESS_NM_PER_RAD = 2.0 / ARCMIN
STOP_RAD = 0.4583 * TAU   # the physical stops: Zach's tview constant for the fatter hard stop (bam_ur_wrist.plant.PlantTruth.stop_rad)
QUANTUM_RAD = TAU / 65536.0   # the board's reported position step (known configuration: the description's "encoder")
G_NORM = 9.81   # |g|: the real lane's floor-plane fit gives 9.810 m/s^2 (camera/floor_gravity_a/floor.json gravity_base)


def up_vector(polar_rad: float, azimuth_rad: float) -> np.ndarray:
    """Real up in the twin's base frame from its polar angle (from the twin's z, CAN 14's axis) and azimuth (from x, about z)."""
    return np.array([math.sin(polar_rad) * math.cos(azimuth_rad), math.sin(polar_rad) * math.sin(azimuth_rad), math.cos(polar_rad)])


def gravity_vector(values: dict) -> np.ndarray:
    """MuJoCo's opt.gravity for these values: -|g| up. WHY a parameter (the coordinator, 2026-11-11, from the real lane): the rig lies on its
    side, real up 94.7 deg from the twin's z (a D405 floor-plane fit), so CAN 14, vertical in the bundle, carries the wrist's gravity."""
    return -G_NORM * up_vector(float(values["wrist.gravity_polar_rad"]), float(values["wrist.gravity_azimuth_rad"]))


@contextlib.contextmanager
def wrist_models(gravity):
    """bam_ur_wrist's WristModel, in this process only, under this gravity and without self-contact pairs. WHY patched: the wrist lane's fits
    (refit.fit, identify.gravity_regressor) build their own WristModel and read the bundle's (vertical) gravity; this rig's gravity is a
    parameter. WHY no pairs: a fit's model needs the mass matrix and gravity only (the pairs cost ~3 s a build)."""
    from bam_ur_wrist import model as wrist_model  # noqa: PLC0415

    original = wrist_model.WristModel.__init__
    g = np.asarray(gravity, dtype=float).copy()

    def init(self, bundle, *args, **kwargs):
        kwargs.setdefault("self_contact", False)
        original(self, bundle, *args, **kwargs)
        self.model.opt.gravity[:] = g

    wrist_model.WristModel.__init__ = init
    try:
        yield
    finally:
        wrist_model.WristModel.__init__ = original
REVERSAL = {"amplitude_rad": 0.6 * DEG, "speed_rad_s": 0.5 * DEG, "cycles": 3, "cap_fraction": 0.4}
DELAY_GRID_S = (0.0, 0.003, 0.006)
II_ITERATIONS = 4
BOOTSTRAP = 40


# --- the parameter table ----------------------------------------------------------------------------------------------------------------


def _servo_rows(can: int) -> list[seam.Parameter]:
    i = INSTANCE[can]
    held = can not in MOVING
    why = "CAN 14 is held (Zach's cable rule, bam_ur_wrist_coverage.rig.HELD): no routine moves it, so nothing excites it"
    P = seam.Parameter

    def row(name, unit, tol, source, routine, display="", title=""):
        return P(f"{i}.{name}", unit, None if held else tol, "" if held else source, None if held else routine, why if held else "", display, title)

    dyn = "servo.dynamics_regression"
    rows = [
        row("axis_inertia_kg_m2", "kg·m²", ("rel", 0.10), "proposed: 10 % (the it5 refit's own indirect-inference gap closed to < 1 %)", dyn,
            title="axis inertia at the held pose (armature + the links it turns)"),
        P(f"{i}.armature_kg_m2", "kg·m²", title="armature (reflected rotor inertia)",
          why_not=why if held else ("only the axis inertia is seen (armature + the links it turns: {0}.axis_inertia_kg_m2): the CAD links' inertia "
                                    "is a prior the hidden masses move, so any error in it lands in the armature one for one (on CAN 14 the links "
                                    "carry twice its armature); the fit sets it for the twin as the axis inertia less the CAD links").format(i)),
        row("coulomb_nm", "N·m", ("rel", 0.10), "proposed: 10 %, the pendulum oracle's frictionloss tolerance (sysid/acceptance.json)", dyn,
            title="sliding (Coulomb) friction, the M2 frictionloss level"),
        row("static_friction_nm", "N·m", ("rel", 0.10), "proposed: 10 %, as the sliding level", dyn,
            title="breakaway (static) friction, the M3 frictionloss level"),
        row("damping_nm_s_rad", "N·m·s/rad", ("abs", 0.001), "proposed: 1e-3 N.m.s/rad absolute (6 mN.m at the 6 rad/s ceiling; the truth may be 0)", dyn,
            title="viscous friction"),
        row("backlash_rad", "rad", ("rel", 0.10), "proposed: 10 %, the pendulum oracle's backlash tolerance (sysid/acceptance.json)",
            "servo.backlash_reversal_held", "arcmin", "gear backlash (the full lost motion)"),
        row("zero_offset_rad", "rad", ("abs", 0.15 * DEG), "proposed: 0.15 deg, a third of the 1 mm tool gate at the holder's ~0.1 m lever",
            "homing.single_touch", "deg", "joint zero (cad = board + offset, this session's frame)"),
    ]
    if can == 14:
        rows += [row("gravity_nm", "N·m", ("rel", 0.05), "proposed: 5 % (the wrist's whole load, ~0.25 N.m on its side)", dyn,
                     title="gravity torque amplitude at the held pose"),
                 row("gravity_bottom_rad", "rad", ("abs", 2 * DEG), "proposed: 2 deg", dyn, "deg", "gravity's bottom at the held pose")]
    else:
        # WHY not identified (2026-11-11, the rig on its side): under the measured up CAN 15 and 16 carry 1.5-3 mN.m (the real lane: <= 12),
        # a fifth of the torque reading's noise and 1/50 of their breakaway
        reason = ("~2 mN.m at the held pose with the rig on its side: a fifth of the torque reading's noise and 1/50 of the breakaway, so no "
                  "run of the schedule resolves it (its load sits in the chain's masses, below)")
        rows += [P(f"{i}.gravity_nm", "N·m", why_not=reason, title="gravity torque amplitude at the held pose"),
                 P(f"{i}.gravity_bottom_rad", "rad", why_not=reason, display="deg", title="gravity's bottom at the held pose")]
    return rows


def parameter_table() -> tuple[seam.Parameter, ...]:
    rows = [r for can in CANS for r in _servo_rows(can)]
    rows.append(seam.Parameter("wrist.command_delay_s", "s", ("abs", 0.0002), "proposed: one 0.2 ms physics step (the plant's own delay resolution)",
                               "servo.command_delay_scan", display="ms", title="command delay (host -> board, every board)"))
    rows.append(seam.Parameter("wrist.gravity_azimuth_rad", "rad", ("abs", 1.0 * DEG),
                               "proposed: 1 deg (turns CAN 14's ~0.27 N.m load's bottom 1 deg: 5 mN.m, 3 % of its breakaway)",
                               "arm.gravity_direction", display="deg", title="real up's azimuth about the twin's z (CAN 14's axis)"))
    rows.append(seam.Parameter("wrist.gravity_polar_rad", "rad", display="deg", title="real up's angle from the twin's z (CAN 14's axis)",
                               why_not="CAN 14's load goes as sin(polar), flat at 94.7 deg: a 1.5 deg tilt moves it 0.2 %, which a mass does as well; "
                                       "CAN 15 and 16, which would see it, carry ~2 mN.m"))
    masses = ("only their gravity at a driven joint is seen (can14.gravity_nm, gravity_bottom_rad): with one joint moving at a time the "
              "chain's 12 first moments project onto two numbers per joint, and CAN 15's and 16's are below the noise")
    for body in LINKS:
        rows.append(seam.Parameter(f"wrist.mass_{body}_kg", "kg", why_not=masses, title=f"{body} mass"))
        for axis in "xyz":
            rows.append(seam.Parameter(f"wrist.com_{body}_{axis}_m", "m", why_not=masses, display="mm", title=f"{body} centre of mass {axis}"))
    return tuple(rows)


# --- the noise at 1x: the real wrist's, measured ------------------------------------------------------------------------------------------

REAL_RUNS = "/archive/datasets/bam_rig/rack_2026-11-10/ur_wrist/coverage/real/ram (CAN 15/16 floor-dither runs, measured 2026-11-11)"


def noise_1x() -> seam.NoiseModel:
    return seam.NoiseModel(
        encoder_quantum_rad=TAU / 65536.0, encoder_noise_rad=0.0, velocity_noise_rad_s=1e-3, torque_noise_nm=0.01,
        period_overrun_s=0.71e-3, latency_jitter_s=0.0,
        sources={
            "encoder_quantum_rad": f"the smallest position step in the real runs, 9.587e-5 rad = 2 pi / 65536 ({REAL_RUNS})",
            "encoder_noise_rad": "0: the real board's position at rest moves by whole steps only; the step is the encoder's noise",
            "velocity_noise_rad_s": f"the real board's velocity at rest: 1.1e-3 rad/s std ({REAL_RUNS})",
            "torque_noise_nm": f"the real torque at rest: 0.014 N.m std with the loop's own chatter in it ({REAL_RUNS}); bam_ur_wrist.refit's hidden twin used 0.01",
            "torque_disturbance_nm": ("0 at 1x: anchored on the real lane's repeat floors (CAN 14 0.100, CAN 15 0.092, CAN 16 0.241 deg driven, bam_ws "
                                      "claude/ur-wrist-real @ 6e26aa27a), which the host loop's measured timing alone already reproduces to within "
                                      "about 2x (WristRig.floor_check); a disturbance raised CAN 15's floor 2x and left CAN 14's"),
            "period_overrun_s": f"the real host loop: median 10.57 ms, mean 10.71 ms, std 0.53 ms against the plan's 10 ms tick ({REAL_RUNS})",
            "latency_jitter_s": ("0 at 1x, set by the floor anchor (WristRig.floor_check against the real lane's floors, 2026-11-11): the host "
                                 "loop's measured overrun alone gives CAN 14 / 15 / 16 1.70x / 1.62x / 0.53x the real floors (geometric mean 1.13x); "
                                 "0.4 ms of jitter took CAN 14 to 2.06x. Unmeasured on the bus; the term stays for the stress lane"),
        })


# --- the tapes: the house schedule's steps as the runner sends them --------------------------------------------------------------------


@contextlib.contextmanager
def _can14_driven():
    """The coverage lane's rig with CAN 14 let move, in this process only, restored on exit. WHY patched and not edited (that lane's
    rig.HELD is its own rule for its own plans): its plan builder and its runner's table refuse a held board, and this rig drives CAN 14."""
    from bam_ur_wrist_coverage import rig  # noqa: PLC0415

    saved = (rig.MOVING, rig.HELD)
    rig.MOVING, rig.HELD = (14, 15, 16), ()
    try:
        yield
    finally:
        rig.MOVING, rig.HELD = saved


@functools.lru_cache(maxsize=1)
def _steps() -> dict[str, dict]:
    """Every scheduled step of the house schedule's plans, keyed "can15/<schedule run>": CAN 15 and 16's as the real lane ran them (the
    coverage plans), CAN 14's built the same way by the same builder (bam_ur_wrist_coverage.plans: describe, schedule, ladders, plans)."""
    out = {}
    for path in sorted(PLANS.glob("can1[56]_*.json")):
        for step in json.loads(path.read_text()).get("steps", []):
            if "schedule" in step and "can_id" in step:
                out[f"can{step['can_id']}/{step['schedule']['run']}"] = {**step, "plan": path.stem}
    frozen = HERE / "plans_can14.json"
    if frozen.exists():
        # WHY frozen (2026-11-11): building them needs the coverage lane's describe(14), a full WristModel with 948 contact pairs (~1 GB in
        # the parent every worker forks from); the file is that builder's output, stamped with the commit it ran at (can14_plans_built)
        out.update(json.loads(frozen.read_text())["steps"])
        return out
    out.update(can14_plans_built())
    return out


def can14_plans_built() -> dict[str, dict]:
    """CAN 14's scheduled steps as the coverage lane's builder makes them, CAN 14 let move (what plans_can14.json freezes)."""
    from bam_ur_wrist_coverage import describe, plans  # noqa: PLC0415

    out = {}
    with _can14_driven():
        description = describe.describe(14)
        document = plans.schedule(14, description)
        for ladder in plans.ladders_of(document):
            for step in plans.ladder_plan(document, ladder, description).get("steps", []):
                if "schedule" in step and "can_id" in step:
                    out[f"can14/{step['schedule']['run']}"] = {**step, "plan": ladder["name"]}
    return out


def _family(step: dict) -> str:
    return step["plan"].split("_", 2)[2]   # "can15_01_gravity" -> "gravity"; "can15_14_pickplace_heldout" -> "pickplace_heldout"


def _plan_runs(plans, split: str, frame: dict) -> list[seam.Run]:
    runs = []
    for run_id, step in _steps().items():
        if _family(step) in plans and step["schedule"]["split"] == split and int(step["can_id"]) in MOVING:
            runs.append(seam.Run(run_id, split, {"kind": "tape", "step": step, "frame": dict(frame)}))
    return runs


def tape(step: dict) -> dict:
    """The command tape the rack's runner sends for one step (bam_ur_wrist_coverage.twin.play_step's schedule, scales, cap and Coulomb
    feed-forward, unchanged), on the rig's homed board frame, one command per planned 10 ms tick; a swing ends in its coast."""
    from bam_rack_twin.hardware import experiments  # noqa: PLC0415
    from bam_ur_wrist_coverage import describe, rig  # noqa: PLC0415
    from bam_ur_wrist_coverage.twin import step_arguments  # noqa: PLC0415

    can = int(step["can_id"])
    arguments = step_arguments(step)
    origin = step.get("origin_rad")
    q0 = float(origin if origin is not None else rig.rest_board_rad(can))
    with _can14_driven(), describe.proposed_blocks():
        schedule, duration, _travel = experiments.schedule_for(arguments, q0)
        feedforward = experiments.coulomb_feedforward(arguments)
    ticks = int(math.floor(duration / PERIOD_S + 1e-9)) + 1
    q_target, qd_target, ff, commanding = [], [], [], []
    for tick in range(ticks):
        q, qd = schedule(tick * PERIOD_S)
        q_target.append(math.nan if q is None else float(q))
        qd_target.append(float(qd))
        ff.append(float(feedforward(qd)) if feedforward is not None else 0.0)
        commanding.append(True)
    if arguments.kind == "swing":
        for _ in range(int(round(experiments.COAST_S / PERIOD_S))):
            q_target.append(math.nan), qd_target.append(0.0), ff.append(0.0), commanding.append(False)
    return {"can": can, "q0_board": q0, "q_target": np.array(q_target), "qd_target": np.array(qd_target), "ff": np.array(ff),
            "commanding": np.array(commanding), "kp_scale": float(getattr(arguments, "kp_scale_cmd", 1.0) or 1.0),
            "kd_scale": float(getattr(arguments, "kd_scale_cmd", 1.0) or 1.0), "cap": float(arguments.cap_nm)}


# --- the plant from values -------------------------------------------------------------------------------------------------------------


def _vec(values: dict, name: str) -> tuple[float, float, float]:
    return tuple(float(values[f"{INSTANCE[c]}.{name}"]) for c in CANS)


def masses_of(values: dict) -> dict:
    """The chain's masses in the coverage lane's TwinParams.masses form (links_kg, com_m), from the parameter values."""
    return {"links_kg": {b: float(values[f"wrist.mass_{b}_kg"]) for b in LINKS},
            "com_m": {b: [float(values[f"wrist.com_{b}_{a}_m"]) for a in "xyz"] for b in LINKS}}


def build_plant(values: dict, start_cad, *, noise: dict | None = None, seed=None):
    """The wrist at these values: the it5 twin's board seam (RAM gains, 2 A cap, 200 Hz current loop, the physical 165 deg stops), the
    values' friction, armature, viscous, command delay, masses, gaps and joint zeros, and the noise terms given (none: noise-free)."""
    from bam_ur_wrist.plant import BoardGains, PlantTruth  # noqa: PLC0415
    from bam_ur_wrist_coverage import rig, twin  # noqa: PLC0415

    noise = noise or {}
    truth = PlantTruth(gains=tuple(BoardGains(kp=float(rig.RAM_GAINS[c][0]), ki=0.0, kd=float(rig.RAM_GAINS[c][1])) for c in CANS),
                       coulomb_nm=_vec(values, "coulomb_nm"), static_friction_nm=_vec(values, "static_friction_nm"),
                       armature_kg_m2=_vec(values, "armature_kg_m2"), command_delay_s=float(values["wrist.command_delay_s"]),
                       mass=twin.mass_truth(masses_of(values)), stop_rad=STOP_RAD, torque_noise_nm=float(noise.get("torque_noise_nm", 0.0)),
                       seed=0 if seed is None else int(np.random.SeedSequence([int(s) for s in seed]).generate_state(1)[0]))
    rng_seed = None if seed is None else [int(s) for s in seed]
    plant = wp.wrist_plant_class()(truth, start_cad, backlash_rad=_vec(values, "backlash_rad"), stiffness_nm_per_rad=MESH_STIFFNESS_NM_PER_RAD,
                                   viscous_nm_s_rad=_vec(values, "damping_nm_s_rad"), session_offset_rad=_vec(values, "zero_offset_rad"),
                                   noise={k: v for k, v in noise.items() if k != "torque_noise_nm"}, noise_seed=rng_seed)
    plant.model.opt.gravity[:] = gravity_vector(values)
    import mujoco  # noqa: PLC0415

    mujoco.mj_forward(plant.model, plant.data)
    return plant


def _rest_cad() -> np.ndarray:
    from bam_ur_wrist_coverage import rig  # noqa: PLC0415

    return np.asarray(rig.rest_cad_rad(), dtype=float)


def _rig_offset(can: int) -> float:
    from bam_ur_wrist_coverage import rig  # noqa: PLC0415

    return float(rig.OFFSET_RAD[can])


# --- one play (a worker's job) -----------------------------------------------------------------------------------------------------------


def _seed(noise_seed: int, stream: str, run_id: str) -> list[int]:
    import zlib  # noqa: PLC0415

    return [int(noise_seed), zlib.crc32(stream.encode()), zlib.crc32(run_id.encode())]


def play(job: dict) -> dict:
    """One run on a plant at ``job["values"]``: a tape (measured on a fresh world, or replayed from a recording's own commands and clock),
    a held reversal, or a homing seek. Returns the recording: the host's board readings and the commands it sent, plus the world's own
    output angles (``world_link_rad``, the score's tool gate only: no fit reads them)."""
    kind = job["kind"]
    values = job["values"]
    if kind == "replay":
        return _replay(job)
    if kind == "tape":
        return _measure_tape(job)
    if kind == "reversal":
        return _reversal(job)
    if kind == "homing":
        return _homing(job)
    raise ValueError(f"no play kind {kind!r}")


def _command(position, velocity, ff, kp_scale, kd_scale, cap):
    from moteus_servo import MoteusCommand  # noqa: PLC0415

    return MoteusCommand(position_rad=None if not math.isfinite(position) else float(position), velocity_rad_s=float(velocity),
                         feedforward_torque_nm=float(ff), kp_scale=float(kp_scale), kd_scale=float(kd_scale), ilimit_scale=0.0,
                         maximum_torque_nm=float(cap), watchdog_timeout_s=0.1)


def _measure_tape(job: dict) -> dict:
    """A planned tape played on the world: the host sends each command when its (jittered) tick comes, in its own homed frame."""
    spec, values = job["spec"], job["values"]
    t = tape(spec["step"])
    can = t["can"]
    axis = CANS.index(can)
    frame = spec["frame"]                      # the host's servo map: cad = board + offset (the zero homing found)
    shift = _rig_offset(can) - float(frame[INSTANCE[can]])   # rig-frame board target -> the host's board frame
    truth_offset = _vec(values, "zero_offset_rad")
    start = _rest_cad()                        # the held joints rest where they rest
    host = {c: float(frame[INSTANCE[c]]) for c in CANS}
    # the moving joint is where the host's last move put it: where the host believes, plus its zero error (cad_true - cad_host =
    # offset_true - offset_host for one board reading)
    start[axis] = t["q0_board"] + _rig_offset(can) + (truth_offset[axis] - host[can])
    plant = build_plant(values, start, noise=job["noise"], seed=job["seed"])
    board_target = t["q_target"] + shift
    return _drive(plant, axis, board_target, t, None, frame=host)


def _drive(plant, axis: int, board_target, t: dict, stamps, *, frame: dict) -> dict:
    """Send each command, log the reading taken just before it (the runner's reply convention), advance one host period (the plant's own
    jittered period, or the recording's clock when ``stamps`` is given)."""
    n = board_target.size
    rows = np.zeros((n, 4))
    link = np.zeros((n, 3))
    dt = plant.model.opt.timestep
    for k in range(n):
        reading = plant.read()
        rows[k] = (plant.clock_s, reading.position_rad[axis], reading.velocity_rad_s[axis], reading.torque_nm[axis])
        link[k] = plant.link_q()
        commands = [None, None, None]
        if t["commanding"][k]:
            commands[axis] = _command(board_target[k], t["qd_target"][k], t["ff"][k], t["kp_scale"], t["kd_scale"], t["cap"])
        plant.send(commands)
        if stamps is None:
            plant.step()
        else:
            nxt = stamps[k + 1] if k + 1 < n else stamps[k] + PERIOD_S
            plant.advance(max(1, int(round((nxt - stamps[k]) / dt))))
    plant.send([None, None, None])
    return {"kind": "tape", "can": int(CANS[axis]), "axis": axis, "t": rows[:, 0], "q": rows[:, 1], "qd": rows[:, 2], "tau": rows[:, 3],
            "commands": {"board_target": board_target, "qd_target": t["qd_target"], "ff": t["ff"], "commanding": t["commanding"],
                         "kp_scale": t["kp_scale"], "kd_scale": t["kd_scale"], "cap": t["cap"]},
            "frame": dict(frame), "world_link_rad": link, "reason": "complete"}


def _replay(job: dict) -> dict:
    """A recording's own commands at its own clock on the twin at ``job["values"]``, noise-free, from the recording's first reading."""
    rec, values = job["recording"], job["values"]
    axis, can = rec["axis"], rec["can"]
    host = rec["frame"]
    start = _rest_cad()
    start[axis] = float(rec["q"][0]) + float(host[can])
    # the twin's world IS its values: its frame is the values' zero, which the host's estimate is (predict hands the fitted values)
    plant = build_plant(values, start)
    c = rec["commands"]
    t = {"commanding": c["commanding"], "qd_target": c["qd_target"], "ff": c["ff"], "kp_scale": c["kp_scale"], "kd_scale": c["kd_scale"], "cap": c["cap"]}
    out = _drive(plant, axis, np.asarray(c["board_target"], float), t, np.asarray(rec["t"], float), frame=host)
    out["t"] = np.asarray(rec["t"], float)
    return out


def _reversal(job: dict) -> dict:
    """servo.backlash_reversal_held on one joint: at the rest pose, a slow triangle of the position target under a cap below the
    output's breakaway; relative moves only (no absolute frame needed: it runs before homing)."""
    spec, values = job["spec"], job["values"]
    can, axis = spec["can"], CANS.index(spec["can"])
    plant = build_plant(values, _rest_cad(), noise=job["noise"], seed=job["seed"])
    q0 = float(plant.read().position_rad[axis])
    amp, speed, cycles, cap = spec["amplitude_rad"], spec["speed_rad_s"], spec["cycles"], spec["cap_nm"]
    period = 4.0 * amp / speed
    ticks = int(round(cycles * period / PERIOD_S))
    target = np.empty(ticks)
    for k in range(ticks):
        phase = (k * PERIOD_S / period) % 1.0
        target[k] = q0 + amp * (4 * phase if phase < 0.25 else (2 - 4 * phase if phase < 0.75 else 4 * phase - 4))
    t = {"commanding": np.ones(ticks, bool), "qd_target": np.zeros(ticks), "ff": np.zeros(ticks), "kp_scale": 1.0, "kd_scale": 1.0, "cap": cap}
    out = _drive(plant, axis, target, t, None, frame={c: float(values[f"{INSTANCE[c]}.zero_offset_rad"]) for c in CANS})
    out.update(kind="reversal", cap_nm=cap, cycles=cycles, period_s=period)
    return out


def _homing(job: dict) -> dict:
    """homing.single_touch on one joint: bam_ur_wrist.homing.tview_home_one (Zach's procedure, unchanged) on the world, from the rest pose."""
    from bam_ur_wrist import homing  # noqa: PLC0415

    spec, values = job["spec"], job["values"]
    can, axis = spec["can"], CANS.index(spec["can"])
    plant = build_plant(values, _rest_cad(), noise=job["noise"], seed=job["seed"])
    plant.send([None, None, None])
    plant.step()
    relabel = np.zeros(3)
    log: list = []
    receipt = homing.tview_home_one(plant, can, axis, relabel, log=log)
    direction, constant = homing.TVIEW_STEPS[can]
    return {"kind": "homing", "can": can, "axis": axis, "direction": direction, "constant_rev": constant, "receipt": receipt,
            "stall_board_rev": float(receipt["stall_board_rev"]), "stall_tau_nm": float(receipt["stall_tau_nm"]),
            "log": np.array([row[2:] for row in log if row[1] == "seek"], float), "reason": "complete"}


def _pool_map(jobs: list[dict], workers: int) -> list[dict]:
    if workers <= 1 or len(jobs) <= 1:
        return [play(j) for j in jobs]
    import multiprocessing  # noqa: PLC0415

    # WHY fork and not Python 3.14's default forkserver (measured 2026-11-11): forkserver re-imports the caller's __main__ in its server, so a
    # one-click script without a __main__ guard ran its whole calibration again inside the pool and the pool died; a forked worker starts
    # from this process as it is (its imports and compiled wrist shared copy-on-write) and runs only its job. WHY longest first: the pool
    # ends on the short ones
    order = sorted(range(len(jobs)), key=lambda i: -_cost(jobs[i]))
    out: list = [None] * len(jobs)
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=multiprocessing.get_context("fork")) as pool:
        for index, result in zip(order, pool.map(play, [jobs[i] for i in order])):
            out[index] = result
    return out


def _cost(job: dict) -> float:
    if job["kind"] == "replay":
        return float(job["recording"]["t"][-1])
    if job["kind"] == "tape":
        return float(job["spec"]["step"].get("chirp_s") or 30.0)
    return 10.0


# --- the four routines -------------------------------------------------------------------------------------------------------------------


class BacklashReversal:
    id = "servo.backlash_reversal_held"
    identifies = tuple(f"{INSTANCE[c]}.backlash_rad" for c in MOVING)

    def runs(self, values):
        out = []
        for can in MOVING:
            # WHY the cap at 40 % of the description's breakaway prior: below the output's breakaway (less its gravity), so the output holds
            cap = REVERSAL["cap_fraction"] * float(values[f"{INSTANCE[can]}.static_friction_nm"])
            out.append(seam.Run(f"{INSTANCE[can]}/reversal", "train", {"kind": "reversal", "can": can, "cap_nm": cap,
                                                                      **{k: v for k, v in REVERSAL.items() if k != "cap_fraction"}}))
        return out

    def fit(self, measured, values, twin):
        out = {}
        for rec in measured.values():
            key = f"{INSTANCE[rec['can']]}.backlash_rad"
            spans = reversal_spans(rec)
            give = 2.0 * rec["cap_nm"] / MESH_STIFFNESS_NM_PER_RAD   # the gear's give at the cap, both flanks (the stiffness prior)
            gap = float(np.median(spans)) - give
            rng = np.random.default_rng(0)
            boot = [float(np.median(rng.choice(spans, spans.size))) - give for _ in range(200)]
            lo, hi = np.percentile(boot, (2.5, 97.5))
            # WHY widened by the encoder's step: a few spans read in whole steps resample to one value, and an interval of zero width would
            # claim a precision the board's 2 pi / 65536 rad steps do not have
            out[key] = seam.Estimate(gap, (float(lo) - QUANTUM_RAD, float(hi) + QUANTUM_RAD),
                                     f"held reversal: median of {spans.size} flank-to-flank motor spans (each push saturated at the "
                                     f"{rec['cap_nm'] * 1e3:.0f} mN.m cap) less the gear's give 2 cap / k ({give / ARCMIN:.2f} arcmin)")
        return out


def reversal_spans(rec: dict) -> np.ndarray:
    """Each half cycle's flank-to-flank span: the motor's median while pushing at +cap minus its median at the -cap push that follows."""
    tau, q, cap = rec["tau"], rec["q"], rec["cap_nm"]
    side = np.where(tau >= 0.9 * cap, 1, np.where(tau <= -0.9 * cap, -1, 0))
    segments, current, start = [], 0, 0
    for k, s in enumerate(side):
        if s != current:
            if current != 0 and k - start >= 3:
                segments.append((current, float(np.median(q[start:k]))))
            current, start = s, k
    if current != 0 and side.size - start >= 3:
        segments.append((current, float(np.median(q[start:]))))
    spans = [a[1] - b[1] if a[0] > 0 else b[1] - a[1] for a, b in zip(segments, segments[1:]) if a[0] == -b[0]]
    if not spans:
        raise ValueError(f"{rec['can']}: the reversal never pushed both flanks to the cap: no gap to read")
    return np.asarray(spans, float)


class Homing:
    id = "homing.single_touch"
    identifies = tuple(f"{INSTANCE[c]}.zero_offset_rad" for c in MOVING)

    def runs(self, values):
        return [seam.Run(f"{INSTANCE[c]}/homing", "train", {"kind": "homing", "can": c}) for c in MOVING]

    def fit(self, measured, values, twin):
        out = {}
        for rec in measured.values():
            i = INSTANCE[rec["can"]]
            gap = float(values[f"{i}.backlash_rad"])
            # tview's relabel: the stall reads the constant, so offset = 2 pi (constant - stall); at the stall the motor leads the output by
            # half the gap plus the gear's give, in the seek's direction: corrected by step 1's gap and the stiffness prior
            give = abs(rec["stall_tau_nm"]) / MESH_STIFFNESS_NM_PER_RAD
            offset = TAU * (rec["constant_rev"] - rec["stall_board_rev"]) + rec["direction"] * (0.5 * gap + give)
            out[f"{i}.zero_offset_rad"] = seam.Estimate(offset, (offset - QUANTUM_RAD, offset + QUANTUM_RAD),
                                                        f"tview single touch at {'+' if rec['direction'] > 0 else '-'}{abs(rec['constant_rev']) * 360:.1f} deg, "
                                                        f"stall {rec['stall_tau_nm']:+.2f} N.m, corrected by half the gap ({0.5 * gap / ARCMIN:.2f} arcmin) "
                                                        f"and the gear's give ({give / ARCMIN:.2f} arcmin); the interval is the encoder's step")
        return out


MASS_KEYS = tuple([f"wrist.mass_{b}_kg" for b in LINKS] + [f"wrist.com_{b}_{a}_m" for b in LINKS for a in "xyz"])


class GravityDirection:
    """arm.gravity_direction, the five-bar's J1-tilt rule (bam_fivebar.massid.identify_tilt: gravity identified on fixed CAD geometry, the
    tilt from what the joints feel): the dynamics routine identifies the load CAN 14 feels (its gravity torque's amplitude and bottom at the
    held pose); on the description's CAD centres of mass, a rotation of gravity about CAN 14's axis turns that bottom one for one, so the
    azimuth is the description's plus the bottom's difference, and the masses scale to the amplitude.

    WHY the polar angle is not identified (and listed so): CAN 14's load goes as sin(polar), flat at the measured 94.7 deg (a 1.5 deg tilt
    moves it 0.2 %, which a mass does as well), and CAN 15 and 16 carry ~2 mN.m. WHY on the CAD centres of mass: with one joint moving at a
    time, gravity's azimuth about CAN 14 trades one for one against the azimuth of the centre of mass it carries, so one of the two must
    come from the description (the five-bar takes its masses from a vertical ID first); a CoM direction error would bias the azimuth as much."""
    id = "arm.gravity_direction"
    identifies = ("wrist.gravity_azimuth_rad",)
    adjusts = MASS_KEYS

    def runs(self, values):
        return []   # no motion of its own: the dynamics routine's gravity sweeps

    def fit(self, measured, values, twin):
        cad = WristRig.nominal_values()   # the description's CAD masses (never the truth)
        cad_masses = masses_of(cad)
        amplitude, bottom = float(values["can14.gravity_nm"]), float(values["can14.gravity_bottom_rad"])
        azimuth0 = float(values["wrist.gravity_azimuth_rad"])
        polar = float(values["wrist.gravity_polar_rad"])
        cad_amplitude, cad_bottom = gravity_profile(cad_masses, 14, -G_NORM * up_vector(polar, azimuth0))
        turn = math.atan2(math.sin(bottom - cad_bottom), math.cos(bottom - cad_bottom))
        azimuth = azimuth0 + turn
        scale = amplitude / cad_amplitude
        scaled = {"links_kg": {b: scale * m for b, m in cad_masses["links_kg"].items()}, "com_m": cad_masses["com_m"]}
        check_amplitude, check_bottom = gravity_profile(scaled, 14, -G_NORM * up_vector(polar, azimuth))
        method = (f"CAN 14's identified load ({amplitude * 1e3:.1f} mN.m, bottom {math.degrees(bottom):.2f} deg) on the CAD centres of mass: azimuth "
                  f"turned {math.degrees(turn):+.2f} deg from the description's, masses x {scale:.3f} (check: {check_amplitude * 1e3:.1f} mN.m, "
                  f"{math.degrees(check_bottom):.2f} deg)")
        out = {"wrist.gravity_azimuth_rad": seam.Estimate(azimuth, None, method)}
        out.update({k: seam.Estimate(v, None, "the CAD masses x the scale CAN 14's load asks") for k, v in _mass_values(scaled).items()})
        return out


DYN_TERMS = ("coulomb_nm", "static_friction_nm", "armature_kg_m2", "damping_nm_s_rad")
ARMATURE_FLOOR_KG_M2 = 1e-4   # a tenth of the GIM4305's reflected rotor (the bundle's 0.001): the least a geared joint may carry


def _link_inertia(masses) -> dict[int, float]:
    """Each joint's diagonal of the links' mass matrix at the held pose (no armature) under these masses (MuJoCo)."""
    from bam_ur_wrist.model import WristModel  # noqa: PLC0415

    model = WristModel(wp.stripped_bundle(), armature_kg_m2=(0.0, 0.0, 0.0), masses=masses, self_contact=False)
    diagonal = np.diag(model.mass_matrix(_rest_cad()))
    return {can: float(diagonal[CANS.index(can)]) for can in CANS}


class Dynamics:
    id = "servo.dynamics_regression"
    # set for the twin, never claimed: the regression's gravity first moments on their visible subspace, and each armature (the axis
    # inertia less the CAD links': the axis inertia is what is identified)
    adjusts = MASS_KEYS + tuple(f"{INSTANCE[c]}.armature_kg_m2" for c in MOVING) + ("wrist.command_delay_s",)
    identifies = tuple([f"{INSTANCE[c]}.{t}" for c in MOVING for t in DYN_TERMS if t != "armature_kg_m2"]
                       + [f"{INSTANCE[c]}.axis_inertia_kg_m2" for c in MOVING]
                       + [f"{INSTANCE[c]}.gravity_{n}" for c in (14,) for n in ("nm", "bottom_rad")])

    def runs(self, values):
        return _plan_runs(TRAIN_PLANS, "train", {INSTANCE[c]: float(values[f"{INSTANCE[c]}.zero_offset_rad"]) for c in CANS})

    def fit(self, measured, values, twin):
        # the fits' own models under the values' gravity (wrist_models: the wrist lane's WristModel reads the bundle's vertical one)
        with wrist_models(gravity_vector(values)):
            return self._fit(measured, values, twin)

    def _fit(self, measured, values, twin):
        from bam_ur_wrist.refit import fit as refit_fit  # noqa: PLC0415
        from bam_ur_wrist.refit_rig import gravity_masses  # noqa: PLC0415

        b = wp.stripped_bundle()   # the same bodies and joints, no meshes (plant.stripped_bundle's WHY)
        prior = _prior_masses(values)
        names = sorted(measured)
        runs = [as_fit_run(measured[n], n) for n in names]
        first = refit_fit(b, runs, masses=prior)
        masses = gravity_masses(first.gravity_theta, prior)
        current = {**values, **_mass_values(masses)}
        target = _theta(first, {})
        theta = np.maximum(np.nan_to_num(target), 0.0)  # the plain fit is the first guess (refit_rig.indirect_inference)
        chirps = [n for n in names if "/chirp-" in n]
        lag_world = float(np.mean([command_lag_s(measured[n]) for n in chirps])) if chirps else None
        delay = float(values["wrist.command_delay_s"])
        sigmas = reading_noise(measured)   # the readings' own white noise, from the data (never the noise model)
        history = []
        # indirect inference (bam_ur_wrist.refit_rig.indirect_inference's rule): theta += estimate(world) - estimate(twin at theta), the
        # twin replaying each train recording's own commands and clock, with every value the earlier routines found (gaps, zeros) in it.
        # WHY the command delay in the same loop (measured 2026-11-11 on the smoke): the twin's replays at the description's 5.5 ms put the
        # chirps on another trajectory than the world's 0.6 ms, the estimator's bias with them, and the armature stayed 40 % low; the
        # estimator for the delay is the chirps' command-to-response lag, which the twin's lag at its delay is held to the same way.
        # WHY the replays get the readings' noise (estimated from the world's own data): the breakaway is a percentile of onset torques,
        # which white torque noise lifts; a noise-free twin would leave that lift in the fit
        rng = np.random.default_rng(20261111)
        for iteration in range(II_ITERATIONS):
            trial = {**current, **_from_theta(theta), "wrist.command_delay_s": delay}
            for can in MOVING:
                key = f"{INSTANCE[can]}.armature_kg_m2"
                trial[key] = max(trial[key], ARMATURE_FLOOR_KG_M2)
            replays = {n: noisy_like(r, sigmas, rng) for n, r in twin.predict(measured, trial).items()}
            estimate = refit_fit(b, [as_fit_run(replays[n], n) for n in names], masses=prior)
            gap = np.nan_to_num(target - _theta(estimate, {}))
            lag_gap = 0.0 if lag_world is None else lag_world - float(np.mean([command_lag_s(replays[n]) for n in chirps]))
            history.append([*np.round(gap, 6).tolist(), round(lag_gap, 6)])
            theta = np.maximum(theta + gap, 0.0)
            delay = max(0.0, delay + lag_gap)
        found = _from_theta(theta)
        boot = _bootstrap(runs, prior, theta - target, gravity_vector(values), workers=getattr(twin, "workers", 1))
        links = _link_inertia(prior)   # the CAD links' inertia about each axis at the held pose: what the regression's own model holds
        for can in MOVING:
            i = INSTANCE[can]
            found[f"{i}.axis_inertia_kg_m2"] = found[f"{i}.armature_kg_m2"] + links[can]
            if f"{i}.armature_kg_m2" in boot:
                lo, hi = boot[f"{i}.armature_kg_m2"]
                boot[f"{i}.axis_inertia_kg_m2"] = (lo + links[can], hi + links[can])
            # WHY a floor (gear_backlash.wrap: two coincident hinges share one body, only the rotor's armature keeps the mass matrix
            # invertible): a fit that reads the CAD links as heavier than the axis would hand the plant a zero armature and a singular joint
            found[f"{i}.armature_kg_m2"] = max(found[f"{i}.armature_kg_m2"], ARMATURE_FLOOR_KG_M2)
        out = {}
        for key, value in found.items():
            ci = boot.get(key)
            out[key] = seam.Estimate(value, ci, f"bam_ur_wrist.refit.fit (equation error, {first.rows:,} sliding rows of {len(runs)} train runs) "
                                                f"+ {II_ITERATIONS} indirect-inference iterations on the twin (last gap {np.round(history[-1], 6).tolist()})"
                                                + ("; 95 % from a run bootstrap of the equation-error fit, shifted by the inference" if ci else ""))
        out.update({k: seam.Estimate(v, None, "bam_ur_wrist.refit_rig.gravity_masses of the regression's first moments") for k, v in _mass_values(masses).items()})
        out["wrist.command_delay_s"] = seam.Estimate(delay, None, f"the chirps' command-to-response lag, held to the world's by indirect inference "
                                                                  f"(world lag {1e3 * (lag_world or 0):.2f} ms); the delay scan refines it")
        for can in (14,):
            amplitude, bottom = gravity_profile(masses, can, gravity_vector(values))
            out[f"{INSTANCE[can]}.gravity_nm"] = seam.Estimate(amplitude, None, f"the refit's gravity first moments (its visible subspace around the "
                                                               f"583ee39 prior, refit_rig.gravity_masses) as the torque CAN {can} feels at the held pose "
                                                               "under the description's gravity (MuJoCo): the first moments take up "
                                                               "whatever direction error there is, so the load is right either way")
            out[f"{INSTANCE[can]}.gravity_bottom_rad"] = seam.Estimate(bottom, None, f"as {INSTANCE[can]}.gravity_nm: that torque's bottom")
        return out


def command_lag_s(rec: dict, max_lag_s: float = 0.04) -> float:
    """The lag (s) at which the commanded board target best matches the board's reading: argmin over tau of RMS(q(t) - target(t - tau)),
    a grid of 0.5 ms then a parabola through the best three. A data-only estimator (the host knows what it sent and what it read)."""
    t = np.asarray(rec["t"], float)
    q = np.asarray(rec["q"], float)
    target = np.asarray(rec["commands"]["board_target"], float)
    keep = np.isfinite(target)
    t, q, target = t[keep], q[keep], target[keep]
    lags = np.arange(0.0, max_lag_s, 0.0005)
    cost = []
    for lag in lags:
        inside = t - lag >= t[0]
        cost.append(float(np.mean((q[inside] - np.interp(t[inside] - lag, t, target)) ** 2)))
    cost = np.asarray(cost)
    k = int(np.clip(np.argmin(cost), 1, len(lags) - 2))
    a, b, c = cost[k - 1], cost[k], cost[k + 1]
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) > 0 else 0.0
    return float(lags[k] + np.clip(shift, -1.0, 1.0) * 0.0005)


def reading_noise(measured: dict) -> dict[str, float]:
    """The readings' white noise, estimated from the data: 1.4826 MAD of the second differences / sqrt(6) (a white series' second
    difference has six times its variance; the motion is smooth at 100 Hz), for the torque and the velocity."""
    out = {}
    for field in ("tau", "qd"):
        d2 = np.concatenate([np.diff(np.asarray(r[field], float), 2) for r in measured.values() if len(r[field]) > 3])
        out[field] = float(1.4826 * np.median(np.abs(d2 - np.median(d2))) / math.sqrt(6.0))
    return out


def noisy_like(rec: dict, sigmas: dict, rng) -> dict:
    """A replay with the world's reading noise added (torque, velocity) and its position rounded to the board's step."""
    out = dict(rec)
    out["tau"] = np.asarray(rec["tau"], float) + rng.normal(0.0, sigmas["tau"], len(rec["tau"]))
    out["qd"] = np.asarray(rec["qd"], float) + rng.normal(0.0, sigmas["qd"], len(rec["qd"]))
    out["q"] = np.round(np.asarray(rec["q"], float) / QUANTUM_RAD) * QUANTUM_RAD
    return out


def _prior_masses(values):
    """The fit's mass prior: the description's masses (583ee39's pending prior) as a mass_prior.MassModel."""
    from bam_ur_wrist_coverage import twin  # noqa: PLC0415

    return twin.mass_truth(masses_of(values)).base


def _mass_values(masses: dict) -> dict:
    out = {}
    for body in LINKS:
        out[f"wrist.mass_{body}_kg"] = float(masses["links_kg"][body])
        for a, v in zip("xyz", masses["com_m"][body]):
            out[f"wrist.com_{body}_{a}_m"] = float(v)
    return out


def _theta(fitted, values) -> np.ndarray:
    """The fitted terms of the moving joints as one vector (TERMS x MOVING), from a TwinFit (or, with values, from them)."""
    out = []
    for term in DYN_TERMS:
        for can in MOVING:
            if values:
                out.append(float(values[f"{INSTANCE[can]}.{term}"]))
            else:
                field = {"damping_nm_s_rad": "viscous_nm_s_rad"}.get(term, term)
                out.append(float(getattr(fitted, field)[CANS.index(can)]))
    return np.asarray(out, float)


def _from_theta(theta) -> dict:
    out, k = {}, 0
    for term in DYN_TERMS:
        for can in MOVING:
            out[f"{INSTANCE[can]}.{term}"] = float(theta[k])
            k += 1
    return out


def _boot_one(job) -> np.ndarray | None:
    from bam_ur_wrist.refit import fit as refit_fit  # noqa: PLC0415

    sample, prior, gravity = job
    try:
        with wrist_models(gravity):
            return _theta(refit_fit(wp.stripped_bundle(), sample, masses=prior, fit_gravity=True), {})
    except (np.linalg.LinAlgError, ValueError):
        return None


def _bootstrap(runs, prior, shift, gravity, workers: int = 1) -> dict:
    """95 % intervals: the equation-error fit over runs resampled with replacement, each draw shifted by the inference's correction.
    WHY in the worker pool (measured 2026-11-11 at load ~95): forty fits in one process got 5 % of a core and took longer than the replays."""
    import multiprocessing  # noqa: PLC0415

    if BOOTSTRAP <= 0 or len(runs) < 4:
        return {}
    rng = np.random.default_rng(20261111)
    jobs = [([runs[i] for i in rng.integers(0, len(runs), len(runs))], prior, np.asarray(gravity, float)) for _ in range(BOOTSTRAP)]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork")) as pool:
            results = list(pool.map(_boot_one, jobs))
    else:
        results = [_boot_one(job) for job in jobs]
    draws = [r + shift for r in results if r is not None]
    if len(draws) < 10:
        return {}
    draws = np.asarray(draws)
    keys = list(_from_theta(np.zeros(draws.shape[1])))
    return {key: tuple(float(v) for v in np.percentile(np.maximum(draws[:, i], 0.0), (2.5, 97.5))) for i, key in enumerate(keys)}


def as_fit_run(rec: dict, name: str) -> dict:
    """A recording as refit.fit reads a run (refit_rig._as_run's layout): joint-space q in the host's homed frame, the held joints at rest."""
    axis, can = rec["axis"], rec["can"]
    t = np.asarray(rec["t"], float)
    q = np.tile(_rest_cad(), (t.size, 1))
    q[:, axis] = np.asarray(rec["q"], float) + float(rec["frame"][can])
    tau = np.zeros_like(q)
    tau[:, axis] = rec["tau"]
    qd = np.zeros_like(q)
    qd[:, axis] = rec["qd"]
    return {"name": name, "t": t, "q": q, "qd": qd, "tau": tau, "can_id": can, "axis": axis}


@functools.lru_cache(maxsize=4)
def _gravity_model_cached(key):
    from bam_ur_wrist.model import WristModel  # noqa: PLC0415
    from bam_ur_wrist_coverage import twin  # noqa: PLC0415

    masses, gravity = json.loads(key)
    model = WristModel(wp.stripped_bundle(), masses=twin.mass_truth(masses).base, self_contact=False)
    model.model.opt.gravity[:] = gravity
    return model


def gravity_profile(masses: dict, can: int, gravity) -> tuple[float, float]:
    """(amplitude N.m, bottom rad) of the gravity torque joint ``can`` feels at the held pose (the others at rest) under ``gravity``:
    tau(q) = G sin(q - bottom), from MuJoCo."""
    model = _gravity_model_cached(json.dumps([masses, [float(v) for v in gravity]], sort_keys=True))
    axis = CANS.index(can)
    q = _rest_cad()
    samples = []
    for angle in (0.0, math.pi / 2):
        qq = q.copy()
        qq[axis] = angle
        samples.append(float(model.gravity_torque(qq)[axis]))
    cos_term, sin_term = samples
    return math.hypot(sin_term, cos_term), math.atan2(-cos_term, sin_term)


class DelayScan:
    id = "servo.command_delay_scan"
    identifies = ("wrist.command_delay_s",)

    def runs(self, values):
        return _plan_runs(DELAY_PLANS, "train", {INSTANCE[c]: float(values[f"{INSTANCE[c]}.zero_offset_rad"]) for c in CANS})

    def fit(self, measured, values, twin):
        names = sorted(measured)

        def curve(delay):
            replays = twin.predict(measured, {**values, "wrist.command_delay_s": float(delay)})
            return np.array([np.mean((replays[n]["q"] - measured[n]["q"]) ** 2) for n in names]), np.array([measured[n]["q"].size for n in names])

        step = wp.PHYSICS_DT_S
        start = float(values["wrist.command_delay_s"])
        # WHY around the dynamics routine's value, every 0.2 ms physics step (the plant's delay is a whole number of them, so no finer value
        # exists): that routine's lag already put it within a step or two; the grid's coarse points stay as a guard against a wrong start
        grid = sorted({round(start / step + k) * step for k in range(-4, 5)} | set(DELAY_GRID_S))
        errors = {d: curve(d) for d in grid if d >= 0.0}
        pooled = lambda e: float(np.sqrt(np.average(e[0], weights=e[1])))  # noqa: E731
        delays = sorted(errors)
        best = min(delays, key=lambda d: pooled(errors[d]))
        rng = np.random.default_rng(20261111)
        picks = []
        for _ in range(200):
            index = rng.integers(0, len(names), len(names))
            picks.append(min(delays, key=lambda d: float(np.sqrt(np.average(errors[d][0][index], weights=errors[d][1][index])))))
        return {"wrist.command_delay_s": seam.Estimate(best, tuple(float(v) for v in np.percentile(picks, (2.5, 97.5))),
                                                       f"output error of the twin over {len(names)} train chirps at {len(delays)} command delays "
                                                       f"({', '.join(f'{d * 1e3:.1f}' for d in delays)} ms); the minimum, 95 % by a run bootstrap")}


# --- the rig ---------------------------------------------------------------------------------------------------------------------------------


class WristRig:
    name = NAME
    model = "it5 twin of record (Karnopp Coulomb, command delay, gravity) + gear backlash: servo M4.dynamics.twin x3, chain M0.dynamics.rigid"

    def __init__(self) -> None:
        self._routines = (BacklashReversal(), Homing(), Dynamics(), GravityDirection(), DelayScan())

    def parameters(self):
        return parameter_table()

    def noise(self):
        return noise_1x()

    def derived(self, values):
        """The values the rig computes from others: each joint's gravity torque at the held pose from the chain's masses and gravity's
        direction (MuJoCo)."""
        from bam_ur_wrist_coverage import twin  # noqa: PLC0415

        out = {}
        links = _link_inertia(twin.mass_truth(masses_of(values)).base)
        for can in CANS:
            amplitude, bottom = gravity_profile(masses_of(values), can, gravity_vector(values))
            out[f"{INSTANCE[can]}.gravity_nm"], out[f"{INSTANCE[can]}.gravity_bottom_rad"] = amplitude, bottom
            out[f"{INSTANCE[can]}.axis_inertia_kg_m2"] = float(values[f"{INSTANCE[can]}.armature_kg_m2"]) + links[can]
        return out

    def routines(self):
        return self._routines

    def held_out(self, values=None):
        frame = {INSTANCE[c]: float((values or {}).get(f"{INSTANCE[c]}.zero_offset_rad", _rig_offset(c))) for c in CANS}
        return _plan_runs(HELD_OUT_PLANS, "held_out", frame)

    def measure(self, runs, values, noise, stream, *, workers=1):
        terms = noise.effective()
        jobs = [{"kind": r.spec["kind"], "spec": r.spec, "values": dict(values), "noise": terms, "seed": _seed(noise.seed, stream, r.id)} for r in runs]
        out = dict(zip((r.id for r in runs), _pool_map(jobs, workers)))
        if stream.startswith("routine:"):
            # WHY stripped: the world's own output angles exist only in sim (a camera would be needed); no fit may read them
            for rec in out.values():
                rec.pop("world_link_rad", None)
        return out

    def predict(self, measured, values, *, workers=1):
        names = [n for n, r in measured.items() if r["kind"] == "tape"]
        jobs = [{"kind": "replay", "recording": {k: v for k, v in measured[n].items() if k != "world_link_rad"}, "values": dict(values)} for n in names]
        return dict(zip(names, _pool_map(jobs, workers)))

    def score(self, predicted, measured):
        per_run, pooled, stops = {}, {}, []
        for name, rec in measured.items():
            pred = predicted[name]
            joint = INSTANCE[rec["can"]]
            err = np.asarray(pred["q"], float) - np.asarray(rec["q"], float)
            per_run[name] = {joint: float(np.sqrt(np.mean(err ** 2)))}
            pooled.setdefault(joint, []).append(err)
            if "world_link_rad" in rec and "world_link_rad" in pred:
                stops.append(tool_error_at_stops(rec, pred))
        joints = {j: float(np.sqrt(np.mean(np.concatenate(e) ** 2))) for j, e in sorted(pooled.items())}
        stops = np.concatenate(stops) if stops else np.zeros(0)
        return seam.Score(joints, per_run, float(np.percentile(stops, 95)) if stops.size else None)

    def result(self, description, calibration, report, state):
        from .result_tree import build  # noqa: PLC0415

        return build(self, description, calibration, report, state)

    # ---- the checks the tests hold the plant to

    def plant_check(self, seconds: float = 1.5):
        """(KarnoppPlant's readings, this plant's with no gap) on one sine of CAN 15: the twin of record is the backlash plant at zero gap."""
        from bam_ur_wrist.plant import BoardGains, KarnoppPlant, PlantTruth  # noqa: PLC0415
        from bam_ur_wrist_coverage import rig  # noqa: PLC0415

        truth = PlantTruth(stop_rad=None, gains=tuple(BoardGains(kp=rig.RAM_GAINS[c][0], ki=0.0, kd=rig.RAM_GAINS[c][1]) for c in CANS),
                           coulomb_nm=(0.0413, 0.0656, 0.0611), static_friction_nm=(0.175, 0.140, 0.186), armature_kg_m2=(0.001, 0.00135, 0.00111),
                           command_delay_s=0.0006)
        start = rig.rest_cad_rad()
        reference = KarnoppPlant(wp.bundle(), truth, start)
        mine = wp.wrist_plant_class()(truth, start, backlash_rad=(0.0, 0.0, 0.0), stiffness_nm_per_rad=MESH_STIFFNESS_NM_PER_RAD)
        return _sine(reference, seconds), _sine(mine, seconds)

    def reversal_check(self, gap_rad: float) -> float:
        """The reversal's gap on a noise-free world whose CAN 15 gear has this gap (the routine's own play and fit)."""
        values = {**self.nominal_values(), "can15.backlash_rad": float(gap_rad), "can16.backlash_rad": float(gap_rad)}
        run = next(r for r in BacklashReversal().runs(values) if r.spec["can"] == 15)
        rec = play({"kind": "reversal", "spec": run.spec, "values": values, "noise": {}, "seed": None})
        return float(BacklashReversal().fit({run.id: rec}, values, None)["can15.backlash_rad"].value)

    def floor_check(self, noise, *, workers: int = 8, repeats: int = 5) -> dict[str, float]:
        """The sim's own repeat floor per joint (deg): each joint's floor tape (the house schedule's +-10 deg out and back) ``repeats`` times
        on the world under independent draws of ``noise``, the median pairwise RMS on a common clock (sim2real.metrics.series.pair_rms),
        the way the real lane measured its floors (5 same-input repeats, driven)."""
        import itertools  # noqa: PLC0415

        from sim2real.metrics.series import pair_rms  # noqa: PLC0415

        truth = {**self.nominal_values(), **json.loads((HERE / "world.json").read_text())["truth"]}
        frame = {INSTANCE[c]: truth[f"{INSTANCE[c]}.zero_offset_rad"] for c in CANS}
        jobs, owners = [], []
        for run_id, step in sorted(_steps().items()):
            if _family(step) == "floor" and int(step["can_id"]) in MOVING and run_id.endswith(tuple(f"/r{k}" for k in range(1, repeats + 1))):
                spec = {"kind": "tape", "step": step, "frame": frame}
                jobs.append({"kind": "tape", "spec": spec, "values": truth, "noise": noise.effective(), "seed": _seed(noise.seed, "floor", run_id)})
                owners.append(INSTANCE[int(step["can_id"])])
        records = _pool_map(jobs, workers)
        out = {}
        for joint in sorted(set(owners)):
            series = [(r["t"], r["q"]) for o, r in zip(owners, records) if o == joint]
            out[joint] = float(np.median([math.degrees(pair_rms(a, b)) for a, b in itertools.combinations(series, 2)]))
        return out

    @staticmethod
    def nominal_values() -> dict:
        from sim2real.twin import describe  # noqa: PLC0415

        return {k: float(v) for k, v in describe(NAME).values().items() if v is not None}


def _sine(plant, seconds: float) -> np.ndarray:
    rows = []
    q0 = plant.read().position_rad.copy()
    for k in range(int(round(seconds / PERIOD_S))):
        r = plant.read()
        rows.append(np.r_[r.position_rad, r.velocity_rad_s, r.torque_nm])
        commands = [None, None, None]
        commands[1] = _command(q0[1] + 0.3 * math.sin(TAU * 0.8 * k * PERIOD_S), 0.0, 0.0, 1.0, 1.0, 1.0)
        plant.send(commands)
        plant.step()
    return np.array(rows)


def tool_error_at_stops(measured: dict, predicted: dict) -> np.ndarray:
    """|tool(twin) - tool(world)| (m) where the command rests: the holder board's origin (the tool) through the chain's FK at each one's
    output angles, on the rows where the target has not moved for 0.3 s."""
    target = np.asarray(measured["commands"]["board_target"], float)
    qd_target = np.asarray(measured["commands"]["qd_target"], float)
    still = np.isfinite(target) & (np.abs(qd_target) < 1e-6)
    hold = np.convolve(np.r_[0.0, np.abs(np.diff(np.nan_to_num(target)))] < 1e-9, np.ones(30), mode="full")[: target.size] >= 30
    rows = np.flatnonzero(still & hold)[::5]
    if rows.size == 0:
        return np.zeros(0)
    world = np.asarray(measured["world_link_rad"], float)[rows]
    twin = np.asarray(predicted["world_link_rad"], float)[rows]
    # the twin's output angles are in the host's frame (its world is the fitted values); the world's are the truth's: their difference
    # holds the zero error too, as a tool error should
    return np.array([np.linalg.norm(_tool(w) - _tool(t)) for w, t in zip(world, twin)])


@functools.lru_cache(maxsize=1)
def _fk_model():
    from bam_ur_wrist.model import WristModel  # noqa: PLC0415

    return WristModel(wp.stripped_bundle(), self_contact=False)


def _tool(q) -> np.ndarray:
    model = _fk_model()
    board = model.bundle.boards[0]
    return model.board_poses(q)[board.name][:3, 3]


def rig() -> WristRig:
    return WristRig()
