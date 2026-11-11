"""The One Dof Test Rack's v3 record: its declared tags, its cameras and its producer's model labels (app/registry.json holds the rest)."""

from sim2real.cards.domain import CameraDecl, ModelLabel, PhysicalDeployment, UnitLimit

VIEW = "bam_ws src/dev/bam_rack_twin/docs/dataset_clips.py VIEW (the camera and the tag that see each CAN id); bam_rack_twin/trajectory_dataset.py CAMERAS"
RT = "bam_ws src/dev/bam_rack_twin"
# WHY every label is the servo's M4.dynamics.twin (read off the producer's own builds, 2026-11-07, in its venv, read-only): each is a
# bam_rack_twin TwinParameters MuJoCo hinge (the ladder's M4, "Rack twin", implemented there) holding the board's drive terms (torque scale,
# current loop, command delay) and on some stations the rotor-angle map or the gear gap: M4 terms. They differ from the ladder's M4 as
# written in their friction law (LuGre in place of M3's Stribeck, weakening and capture, on every twin but the dataset study's) and in
# holding the board's current ceiling (M5's kt_out and max_current: a config read) with no heat term. The coordinator's call ("Twin of
# record is the M4.dynamics twin") and the servo card's own today's model (its nominals are CAN 11's twin lugre-d-M1-e37b0e7d) agree.
# The options and why not M5 (the highest layer a term reaches): docs/decision-models-routines-parameters-2026-11-07.md.
LUGRE = "LuGre (Canudas de Wit, Olsson, Astrom & Lischinsky 1995): bristle stiffness and damping, Coulomb and static levels, a Stribeck speed; plus viscous damping"
CEILING = "it holds the board's current ceiling (M5's kt_out and max_current, a config read) and no heat term (thermal_r_c)"
# Each station's limits its type leaves per unit (2026-11-07, the metrics lane), copied from where the producer keeps them; type_cards/tests/
# test_instances.py reads both constants from bam_rack_twin's source and holds this copy to them.
# WHY the stop allocation: the joint's share of the 5 mm tool gate (T4's limit), bam_rack_twin acceptance.py STOP_ALLOCATION_MRAD (an
# agent's default there, "Zach to confirm"); it is both the stop error diagnostic's warn limit and the T4 gate's target.
STOP_ALLOCATION_MRAD = {11: 3.6, 12: 3.6, 13: 3.6, 4: 6.7, 21: 6.7, 1: 10.0, 14: 10.0, 15: 10.0}
STOP_SOURCE = f"{RT}/bam_rack_twin/acceptance.py STOP_ALLOCATION_MRAD (each joint's share of the 5 mm tool gate, T4)"
# WHY 90 Hz: the runner commands at bam_rack_twin hardware/experiments.py RATE_HZ = 100.0, and the loop rate's warn limit is the expected
# rate less RobotDx's tolerance (RateConfig tolerance 0.1, ROS FrequencyStatus)
RATE_HZ = 100.0
RATE_TOLERANCE = 0.1
RATE_SOURCE = f"{RT}/bam_rack_twin/hardware/experiments.py RATE_HZ = 100.0 less RobotDx RateConfig's tolerance 0.1"
LIMITS = tuple(
    limit
    for can, allocation in STOP_ALLOCATION_MRAD.items()
    for limit in (
        UnitLimit(device=f"CAN {can}", diagnostic="servo.stop_error.dx", warn=allocation, target=allocation, source=STOP_SOURCE),
        UnitLimit(device=f"CAN {can}", diagnostic="driver.loop_rate.dx", warn=round(RATE_HZ * (1 - RATE_TOLERANCE), 9), source=RATE_SOURCE),
    )
)

record = PhysicalDeployment(
    id="one-dof-test-rack",
    tags=(),
    cameras=(
        CameraDecl(
            serial="218622274411",
            model="Intel RealSense D405",
            type="depth_camera",
            sees=(1, 14, 15, 4, 21),
            source=VIEW + "; tags 0, 1, 2, 4, 5",
        ),
        CameraDecl(
            serial="218622276036",
            model="Intel RealSense D405",
            type="depth_camera",
            sees=(13, 12, 11),
            source=VIEW + "; tags 6, 7, 8",
        ),
    ),
    note="The D435 044322072026 RobotDx lists on the same host is not here: no bam_rack_twin map ties it to a station.",
    limits=LIMITS,
    models=(
        ModelLabel(
            label="twin of record",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="the station's twin of record, the acceptance's held-out-safer pick, replaying every run of its schedule sessions: CAN 11 "
                "follow-up C (cal-lugre-d-M1-e37b0e7d), CAN 12 the pre-sliding D on its M2 twin with the board's planner (lugre-M2-c807a2da"
                "+plan100), CAN 21 calibration C with the rotor-angle map and the T2 refit (cal-lugre-d-pll-2f2c5726+map0.5+t2refit)",
            friction=LUGRE,
            differs=f"friction is LuGre's where the ladder's M3 writes Stribeck, weakening and capture; {CEILING}; no gear gap; CAN 12 adds the "
                    "board's trajectory planner and CAN 21 the encoder's PLL, terms of the servo's FOC controller and encoder, not of its ladder",
            source=f"{RT}/docs/can11_frozen_1105.py twin_of_record (followup_1029.twins_can11 C); docs/session_replays_1107.py; each "
                   "session's analysis/twin_replays.json",
        ),
        ModelLabel(
            label="twin A · deployed",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="the station's T2 twin before the 2026-10-29 calibration round (the D pass's LuGre pick), replaying that round's held-out tapes",
            friction=LUGRE,
            differs=f"friction is LuGre's; {CEILING}, and on CAN 1, 14 and 15 the bus voltage ceiling too (M5's V_avail and R); the rotor-angle "
                    "map on CAN 1 and 14, the encoder's PLL on CAN 21",
            source=f"{RT}/docs/calibration_round.py a_twin; followup_1029.twins_can11 A on CAN 11",
        ),
        ModelLabel(
            label="twin C · calibrated",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="the 2026-10-29 calibration round's fit: A with its LuGre, viscous and command delay re-fitted and the station's limiting term",
            friction=LUGRE,
            differs=f"as A: LuGre, {CEILING}; CAN 14's C adds the gear gap (backlash_rad 3.55 mrad, gear_stiffness_nm_rad 100)",
            source=f"{RT}/docs/calibration_round.py c_build (twins_of C); followup_1029.twins_can11 C on CAN 11",
        ),
        ModelLabel(
            label="twin C1 · fast inertia",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="CAN 1's 2026-10-29 follow-up of C: the inertia pinned by the fast runs",
            friction=LUGRE,
            differs=f"as C on CAN 1: LuGre, the rotor-angle map, the bus voltage ceiling; {CEILING}",
            source=f"{RT}/docs/followup_1029.py twins_can1 C1",
        ),
        ModelLabel(
            label="twin D · LuGre",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="round 1 of the 2026-10-28 pre-sliding study on CAN 12 and 13: the deployed twin with its friction written as LuGre, its "
                "cogging map phased per run",
            friction=LUGRE,
            differs=f"LuGre in place of the deployed twin's Stribeck drop and capture; {CEILING}",
            source=f"{RT}/docs/presliding_study.py lugre_build on deployed (presliding_round3_can12.json, _can13.json points)",
        ),
        ModelLabel(
            label="twin G · LuGre re-fit",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="D with its bristle stiffness, Coulomb and viscous re-identified on the pre-sliding study's train runs (CAN 12 and 13)",
            friction=LUGRE,
            differs=f"as D; {CEILING}",
            source=f"{RT}/docs/presliding_round2.py g_build",
        ),
        ModelLabel(
            label="twin H · + dwell",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="D plus dwell-time static friction, identified on the pre-sliding study's train runs (CAN 12 and 13)",
            friction="LuGre whose static level ages with the contact (Armstrong-Helouvry's rising static friction, Dieterich's aging law)",
            differs=f"a friction-aging term no model of the ladder holds; {CEILING}",
            source=f"{RT}/docs/presliding_round2.py h_build",
        ),
        ModelLabel(
            label="twin R · rate-state",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="LuGre with its sliding law swapped for rate-and-state friction, round 3 of the pre-sliding study (CAN 12 and 13)",
            friction="LuGre's bristle in series with a Dieterich-Ruina rate-and-state slider (a direct and an evolution term over a slip distance)",
            differs=f"a rate-and-state level no model of the ladder holds; {CEILING}",
            source=f"{RT}/docs/presliding_round3.py r_build",
        ),
        ModelLabel(
            label="refit R1",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="CAN 11's friction refit on train runs only (2026-11-05), started from C's point; kept for comparison, not picked under the "
                "safer rule",
            friction=LUGRE + " (a Stribeck dip allowed)",
            differs=f"as C on CAN 11: LuGre, {CEILING}",
            source=f"{RT}/docs/can11_friction_refit_1105.py (start R1; calibration_round.c_build on the A base)",
        ),
        ModelLabel(
            label="twin · full",
            type="integrated_servo",
            model="M4.dynamics.twin",
            fit="the 2026-10-24 / 10-25 dataset study's full twin (bam_rack_twin envelope_twin): every term that study identified; on CAN 11, "
                "12 and 13 the round-7 deployed twin with friction at capture",
            friction="the ladder's own form: Coulomb, with velocity weakening (CAN 14, 21) or a Stribeck drop and capture (CAN 11, 12, 13)",
            differs="the closest to M4 as written: drive terms (torque scale, current loop), the rotor-angle map on CAN 1 and 14, the gear gap "
                    "on CAN 14; no heat term; on CAN 11, 12 and 13 also the board's current ceiling (M5's)",
            source=f"{RT}/bam_rack_twin/envelope_twin.py replay_rungs \"full\" (budget_can<N>.json full_twin; dataset_twin_can<N>.json)",
        ),
    ),
)
