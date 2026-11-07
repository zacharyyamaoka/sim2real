"""UR5e joint backlash: a hidden gear gap on every joint of gear_backlash's UR plant, found by gear_backlash's own gravity-crossing sweep.

A noise-ladder scenario (sysid/noise_ladder.json), not one of the six landing examples (sysid.oracle.EXAMPLES): it exists so backlash is a
hidden, graded parameter on the UR's geared joints too (Zach, 2026-11-07, via the coordinator: "Make backlash a first-class oracle
parameter wherever a joint has gears (the pendulum, UR joints)").

Everything physical and the method are bam_ws main's gear_backlash, imported in place and never copied: the plant (ur/scene.py
DEFAULT_PLANT: Menagerie's UR5e on QDD drivetrains), the gap (BacklashModel, MuJoCo's documented double joint with a tuned stop, built by
ur/run.py build_backlash_model from a SituationConfig), the sweep (ur/calibration.py run_sweep: a +-25 deg sine at 3 deg/s through the
joint's gravity balance, the drive's torque with noise, the motor encoder rounded), the pose it sweeps at (calibration_pose) and the fit
(calibration.identify: each flank's shift of the arm's own gravity curve, with an output-friction term and the datasheet mesh stiffness).
What sysid adds: the hidden gap in world.json (read only here, by RealWorld), the sensing at the noise ladder's level, and the split
between what the drive can see (handed to identify) and what only the simulator knows (the link angle, the twist: kept back).

WHY not inside the ur5e example (2026-11-07): its truth hides joint zeros and servo dynamics behind Menagerie's own servos with no gap;
putting a gap there moves every committed ur5e number and the site's pages with them. The scenario hides the gap on the plant the house
already studies backlash on, and the decision record (docs/decision-calibration-procedures-2026-11-07.md) names folding it into the arm
examples as the next step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from sysid import result
from sysid import world as hidden

EXAMPLE = "ur5e_backlash"
# WHY 2^52 counts per output revolution at the ladder's main levels: run_sweep always rounds the motor angle to 2 pi / counts, and 2 pi / 2^52
# is below a double's resolution of these angles (the rounding returns the angle); the encoder's own quantum is the encoder_14bit_9to1 variant
NO_QUANTISATION = 2 ** 52
SEEN = ("t", "q_motor", "tau", "q_motor_all", "tau_all")  # what the drive logs; run_sweep's q_link, q_link_all and twist are the truth's


def _ur():
    from gear_backlash.ur import calibration, run, scene  # noqa: PLC0415

    return calibration, run, scene


def joint_names() -> list[str]:
    _, _, scene = _ur()
    return [name.removesuffix("_joint") for name in scene.JOINTS]


def sweep_config(description, noise: dict | None = None, seed: int = 7):
    """gear_backlash's SweepConfig with the description's sweep (amplitude, speed, engaged fraction); with `noise`, the world's torque
    noise per joint (big three, small three) and the encoder's quantum while the ladder's encoder variant runs, else none."""
    from gear_backlash.ur.calibration import SweepConfig  # noqa: PLC0415

    s = description.schedule
    torque = (0.0,) * 6 if noise is None else (float(noise["torque_large_nm"]),) * 3 + (float(noise["torque_small_nm"]),) * 3
    quantum = hidden.perturbation("encoder_14bit_9to1")
    counts = NO_QUANTISATION if quantum is None or noise is None else 2 * math.pi / quantum
    return SweepConfig(amplitude_deg=float(s["amplitude_deg"]), speed_deg_s=float(s["speed_deg_s"]), torque_noise_nm=torque,
                       encoder_counts_per_output_rev=counts, engaged_fraction=float(s["engaged_fraction"]), seed=int(seed))


# --- plan ---------------------------------------------------------------------------------------------------------------------

@dataclass
class Plan:
    poses: dict                     # joint index -> the pose its sweep is centred on, or None
    why: dict                       # joint index -> calibration_pose's reason
    coverage: dict = field(default_factory=dict)


def plan(description) -> Plan:
    """A calibration pose per joint from the nominal plant alone (calibration_pose: no gap, no noise read)."""
    calibration, _, scene = _ur()
    from gear_backlash.ur.tasks import UrKinematics  # noqa: PLC0415

    kin = UrKinematics(scene.DEFAULT_PLANT)
    amplitude = math.radians(float(description.schedule["amplitude_deg"]))
    poses, why = {}, {}
    for j in range(len(scene.JOINTS)):
        pose, reason = calibration.calibration_pose(scene.DEFAULT_PLANT, j, amplitude, kin)
        poses[j] = None if pose is None else [float(v) for v in pose]
        why[j] = reason
    swept = [j for j, pose in poses.items() if pose is not None]
    coverage = {"train": {"pct": round(100.0 * len(swept) / len(poses), 2), "visited": len(swept), "reachable": len(poses), "samples": len(swept),
                          "axes": {}, "unplanned": [f"{joint_names()[j]}: {why[j]}" for j in poses if poses[j] is None]},
                "function": "sysid adapter: the joints with a calibration pose (gear_backlash calibration_pose: gravity beats friction 2.5x)",
                "rule": "share of the six joints the sweep can load by gravity at a collision-free pose"}
    return Plan(poses, why, coverage)


# --- the real arm (the hidden gap) -----------------------------------------------------------------------------------------------

@dataclass
class Measured:
    train: dict                     # joint index -> what the drive logged during its sweep
    held_out: dict = field(default_factory=dict)


class RealWorld:
    """The plant with world.json's gap on every joint, swept by gear_backlash's run_sweep at the ladder's sensing."""

    def __init__(self, description, *, workers: int = 6):
        self.description = description
        doc = hidden.load(EXAMPLE)
        self.truth, self.noise, self.seed, self.situation = doc["truth"], doc["noise"], doc["seed"], doc["situation"]
        _, _, scene = _ur()
        gap = math.radians(float(self.situation["gap_arcmin"]) / 60.0)
        if any(not math.isclose(self.truth[f"{name}.backlash_rad"], gap, rel_tol=1e-12) for name in joint_names()):
            raise ValueError("ur5e_backlash: gear_backlash's situation sets one gap on every joint; world.json's truth must agree with it")

    def measure(self, p: Plan) -> Measured:
        calibration, run, scene = _ur()
        situation = run.SituationConfig("sysid-oracle", "the hidden gap", gap_arcmin=float(self.situation["gap_arcmin"]),
                                        method=self.situation["method"], zero=self.situation["zero"])
        config = sweep_config(self.description, self.noise, self.seed)
        logs = {}
        for j, pose in p.poses.items():
            if pose is None:
                continue
            log = calibration.run_sweep(situation, j, np.asarray(pose), scene.DEFAULT_PLANT, config)
            logs[j] = {key: log[key] for key in SEEN}
        return Measured(logs)


# --- identification (measurements and the description only) ------------------------------------------------------------------

@dataclass
class Fit:
    values: dict
    flanks: dict
    methods: dict
    stats: dict


def identify(description, logs: dict) -> Fit:
    """gear_backlash's fit per swept joint, base to tip in passes, each joint at the others' current flank estimates.

    WHY this loop here and not identify_arm: identify_arm sweeps and fits in one call and reads the plant's gap into its report; the loop
    below is its own (pass 1 with the joints nearer the base already estimated, later passes with all), calling the same calibration.identify on
    the drive's logs only, so the fit stays sealed from the gap."""
    calibration, _, scene = _ur()
    config = sweep_config(description)
    stiffness = np.asarray(scene.QDD_MESH_STIFFNESS_NM_PER_ARCMIN, dtype=float) / math.radians(1.0 / 60.0)
    nominal = scene.build_ur_spec(scene.DEFAULT_PLANT).compile()
    names = joint_names()
    estimates, fits = {}, {}
    for pass_index in range(int(description.schedule["passes"])):
        for joint in sorted(logs):
            others = {k: v for k, v in estimates.items() if pass_index > 0 or k < joint}
            fit = calibration.identify(logs[joint], joint, scene.DEFAULT_PLANT, config, others, stiffness, nominal=nominal)
            estimates[joint] = (fit["twist_low"], fit["twist_high"])
            fits[joint] = fit
    values = {f"{names[j]}.backlash_rad": float(fit["gap"]) for j, fit in sorted(fits.items())}
    flanks = {names[j]: {"low_rad": float(fit["twist_low"]), "high_rad": float(fit["twist_high"]), "friction_nm": float(fit["friction_nm"]),
                         "samples": list(fit["samples"])} for j, fit in sorted(fits.items())}
    methods = {"gravity_sweep": "gear_backlash calibration.identify on each swept joint's motor angles and torques: Gauss-Newton on each flank's "
                                "shift of the arm's gravity curve with an output-friction term, the datasheet mesh stiffness removed, "
                                f"{description.schedule['passes']} passes base to tip"}
    return Fit(values, flanks, methods, {"swept": [names[j] for j in sorted(logs)]})


# --- held-out score and the result document --------------------------------------------------------------------------------------

def score(description, p: Plan, fit: Fit, measured: Measured, *, workers: int = 6) -> dict:
    """No held-out motion: the sweep is the whole procedure (its use, compensation, is gear_backlash's study, not re-run here)."""
    return {"models": {}}


def assemble(description, p: Plan, fit: Fit, scores: dict, *, truth: dict) -> dict:
    recovered = {key: {"value": value, "ci95": None, "rung": "gravity_sweep", "method": fit.methods["gravity_sweep"]} for key, value in fit.values.items()}
    return {"title": description.manifest["title"], "subtitle": description.manifest.get("subtitle", ""), "summary": description.manifest.get("summary", ""),
            "tree": description.tree(), "schedule": {"coverage": p.coverage, "why": {joint_names()[j]: w for j, w in p.why.items()}},
            "parameters": result.parameter_rows(EXAMPLE, description, truth, recovered), "metrics": [], "models": [], "flanks": fit.flanks,
            "selected_rung": None, "notes": ["A noise-ladder scenario: its ruler is sysid/noise_ladder.json, not acceptance.json."]}
