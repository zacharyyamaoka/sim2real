"""The servo's acceptance targets T1-T11, the rule each gate states, and the rack stations' stop allocations: data, read by
sim2real.metrics.servo_gates.evaluate. Also the servo schedule's coverage targets, read by sim2real.schedule.joint.

WHY here (Zach, 2026-11-10, proposal 2 step 4: "their targets go into cards/ as data"; "a changed gate target is a cards/ data edit"): the
numbers moved from bam_rack_twin/acceptance.py and schedule.py unchanged, each now a robot_msgs Value whose range is the rule and whose
source names where it comes from. The servo card's own gates (ladders.servo) read these same Values, so a target lives in one place.
Additive (CONTRACT.md): a new module; no v1 / v2 name or field changed.
"""

from __future__ import annotations

from sim2real.metrics.gate import at_least, at_most
from sim2real.metrics.servo_gates import ServoTargets

NOTE = "zach_brain Projects/BAM Robotics/Notes/Servo System Identification -- State of the Art and Our Plan (2026-10-25)"
SCHEDULE_NOTE = "zach_brain Projects/BAM Robotics/Notes/Servo Test Schedule — Prior Art and a Recommended v1 (2026-10-29), section 3.4"
PEPS = "bam_ws docs/peps"

# WHY these allocations (the note's K2 default, Zach to confirm): shoulder 2 mm at 0.55 m, elbow 2 mm at 0.3 m, wrist 1 mm at 0.1 m, about
# 3 mm root-sum-square inside his 5 mm tool gate. Default joint assignment: JMC 10:1 at the shoulder, the direct drives at the elbow, the
# GIM4305s (and CAN 15's ~10:1) at the wrist. Per station of the One Dof Test Rack (its CAN id), in mrad at the output.
STOP_ALLOCATION_MRAD = {11: 3.6, 12: 3.6, 13: 3.6, 4: 6.7, 21: 6.7, 1: 10.0, 14: 10.0, 15: 10.0}

# Each target T1-T11 reads (its range is the rule; its source says where the number comes from)
FLOOR_REPEATS = at_least(5, "repeats", source=f"{NOTE}, T1")
FIDELITY_TAPES = at_most(1.5, "x floor", source=f"{NOTE}, T2 (an agent's default, Zach to confirm)")
FIDELITY_CLASS = at_most(2.0, "x floor", source=f"{NOTE}, T2: every dataset class")
TORQUE_RATIO = at_most(2.0, "x scatter", source=f"{NOTE}, T3")
# WHY T1's repeat minimum (PEP 0007): the count per direction a direct drive's own encoder needs; the schedule note's 20 per direction is a
# coverage target it reports (NOTE_TARGETS), never a gate
STOPS_PER_DIRECTION = at_least(5, "stops", source=f"{PEPS}/0007-t4-direct-drive-output-encoder.md (T1's repeat minimum)")
# WHY a third (PEP 0011, t4_output_camera_1105's gauge rule): a camera gauge's own error and the tag's floor within a third of the allocation
CAMERA_SHARE = at_most(1 / 3, "x allocation", source=f"{PEPS}/0011-t4-geared-output-by-camera-dwell.md; bam_rack_twin stop_camera.ADEQUATE_SHARE")
GAP_CI_HALF_ARCMIN = at_most(2.0, "arcmin", source=f"{NOTE}, T5")
DRIVE_GAIN_PCT = at_most(5.0, "%", source=f"{NOTE}, T6")
SPEED_PCT = at_most(5.0, "%", source=f"{NOTE}, T7")
# WHY 0.9 (PEP 0010): bam_rack_twin envelope.LIMITER_SHARE, the current-limited plateau's own rule
CURRENT_LIMITER_SHARE = at_least(0.9, "share of rows", source=f"{PEPS}/0010-t7-current-limited-plateau.md; bam_rack_twin envelope.LIMITER_SHARE")
THERMOCOUPLE_C = at_most(5.0, "degC", source=f"{NOTE}, T8")


def _n(target):
    """A target's limit as the rule text has always printed it (5, 1.5, 2.0)."""

    return target.low if target.low != -float("inf") else target.high


# The gate table Vibe Tracks shows (id, title, the rule in words); evaluate() is the rule in code. Text unchanged from bam_rack_twin.
GATE_RULES = (
    ("T1", "floor", f"the rack against itself: >= {_n(FLOOR_REPEATS)} identical repeats of one tape"),
    ("T2", "fidelity", f"held-out twin error <= {_n(FIDELITY_TAPES)}x the floor, and <= {_n(FIDELITY_CLASS)}x in every dataset class"),
    ("T3", "torque", f"predicted q-current within {_n(TORQUE_RATIO)}x of the run-to-run current scatter"),
    ("T4", "static accuracy", "p90 stop error at the OUTPUT within the joint's allocation of the 5 mm tool gate (a camera, an output encoder, or a "
                              "verified direct drive's own encoder with stops from both approach directions)"),
    ("T5", "encoder-blind terms", f"gear ratio verified on camera, backlash CI half-width <= {_n(GAP_CI_HALF_ARCMIN)} arcmin, stiffness measured"),
    ("T6", "drive gain", f"known-mass torque within {_n(DRIVE_GAIN_PCT)}%"),
    ("T7", "envelope", f"top speed within {_n(SPEED_PCT)}% and the voltage/current limits reproduced"),
    ("T8", "thermal", f"winding temperature model within {_n(THERMOCOUPLE_C)} degC of a thermocouple"),
    ("T9", "warm and cold", f"one twin holds T2 (<= {_n(FIDELITY_TAPES)}x) cold and warm"),
    ("T10", "live re-identification", "a 60 s live routine restores T2 after drift"),
    ("T11", "provenance", "every model term has a value, grade and evidence, plus firmware and config hash"),
)

SERVO = ServoTargets(floor_repeats=FLOOR_REPEATS, fidelity_tapes=FIDELITY_TAPES, fidelity_class=FIDELITY_CLASS, torque_ratio=TORQUE_RATIO,
                     stops_per_direction=STOPS_PER_DIRECTION, camera_share=CAMERA_SHARE, gap_ci_half_arcmin=GAP_CI_HALF_ARCMIN,
                     drive_gain_pct=DRIVE_GAIN_PCT, speed_pct=SPEED_PCT, current_limiter_share=CURRENT_LIMITER_SHARE, thermocouple_c=THERMOCOUPLE_C,
                     rules={gate_id: rule for gate_id, _name, rule in GATE_RULES})
# A servo TYPE counts as twinned when T1-T8 pass; a UNIT when T1, T2, T5 and T6 pass (the note's G4). T9-T11 are required before field use.
TYPE_GATES = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8")
UNIT_GATES = ("T1", "T2", "T5", "T6")

# --- the servo test schedule's coverage targets (sim2real.schedule.joint.coverage reads them) ---
# WHY 40 % for the gate: visiting a cell once is what a schedule can promise before it runs; the note's stricter targets (>= 200 train samples
# in 95 % of reachable cells, 99 % deployment-weighted) are computed beside it and reported, not gated, in v1.
MINIMUM_COVERAGE_PCT = 40.0
NOTE_TARGETS = {"train_samples_per_cell": 200, "held_out_samples_per_cell": 50, "reachable_pct": 95.0, "deployment_weighted_pct": 99.0,
                "reversals": 50, "reversal_q_cells": 8, "stops_per_direction": 20, "stop_positions": 5, "condition_number": 20.0,
                "ci_half_width_pct": 20.0}

__all__ = ["SERVO", "GATE_RULES", "TYPE_GATES", "UNIT_GATES", "STOP_ALLOCATION_MRAD", "MINIMUM_COVERAGE_PCT", "NOTE_TARGETS", "NOTE",
           "SCHEDULE_NOTE"]
