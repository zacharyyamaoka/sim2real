# sysid: the system-ID oracle

A robot description in, a better model out, checked against a hidden truth. Zach, PROJECT - Sim2Real, Nov 5 2026: "if we assumed
the simulator data was real, we should check that our system ID can match the real values!!!! (this is super important as the base
oracle check for all of this...)".

| example | description in | what calibration finds |
|---|---|---|
| `pendulum_can11` | bam_rack_twin's twin-of-record hinge + CAN 11's joint description | gravity, bottom, axis inertia, Stribeck friction, viscous, the gear gap (servo M2 → M4), and the gap's wear rate |
| `ur5e` | Menagerie `ur5e.xml` | joint zeros (arm M1), each joint servo's inertia, viscous and Coulomb (servo M2) |
| `ur5e_2f85` | `ur5e.xml` + `2f85.xml` (bam_arm.cell's attach) | the above, the tool's mass and centre of mass, the TCP, the gripper's drive |
| `conveyor` | `sysid/examples/conveyor/conveyor.xml` (new) | drum radius, moving mass, viscous and Coulomb drag |
| `dual_arm_cell` | 2 × UR5e + 2F-85 on a torso, the conveyor, a head camera | both arms' base frames, the camera's K and pose; a knocked camera |
| `linescan_cell` | the conveyor, a SWIR line-scan camera, a D435 | the line's geometry, 16 bands' gain and dark, the D435's K, pose, depth scale and offset |

Each folder: `description.json` (schema `sysid.description/1`: the model file or its composition, typed components, sensors, every
nominal value's source), `world.json` (the hidden truth, read only through `sysid.world.load`; identification runs inside
`world.sealed()`), `pipeline.py` (`plan`, `RealWorld`, `identify`, `score`, `assemble`). The ruler is `acceptance.json` (tolerances
and held-out factors, pinned by digest in `tests/test_oracle.py`); results are `results/<id>.json` (what the site's landing page
shows), held to the code by the same test.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid run --all --write
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid drift all --write
    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/sysid/tests

The CAN 11 example and its drift demo take several minutes each (the
rack twin replays at 30 kHz); the others take seconds.

Stock parts used in place, never copied: bam_rack_twin (schedule, twin, replayer, smoother, bootstrap, stock identification),
MuJoCo Menagerie's UR5e and 2F-85, bam_scan_tunnel's `PinholeCamera` (the real pixels), intel_rgbd's D435 constants and stereo-noise
law, type_cards (typing, ladders, wear laws, drift checks, selection rule, coverage functions).

Why the truth is sealed, the ruler pinned, the results committed and bam_ws imported live: `docs/decision-sysid-oracle-2026-11-05.md`.
