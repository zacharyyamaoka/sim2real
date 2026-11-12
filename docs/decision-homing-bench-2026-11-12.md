# Decision: the homing bench's kinematic rung (2026-11-12)

Steps 3–4 of the homing decision report (`/home/bam/bam_ws/reports/homing-subassembly-proposals-2026-11-12.html`, recommendation B on C's bench with A as a rival row). The pure parts are in robot_models (PEP 0001 stop core, PEP 0002 metrics and seams). The plant, the procedures, the bench and the leaderboard are here, because they need a controller and a rig.

| Where | What |
|---|---|
| `sim2real.sim.homing.geometry` | exact drive stops (robot_models `contact.first_contact`, coal); the C1 stop computed at J2's angle; the exporter's `loops.json` (J2, C1) map for the loop |
| `sim2real.sim.homing.plant` | `KinematicStopPlant` (a robot_models `HomingPlant`): rigid stops, hidden B0/B1/B2, the board's kp, encoder frames |
| `sim2real.sim.homing.procedures` | tview v2, single_touch, repeat_checked_seek, two_level_touch, press_reverse; each is one robot_msgs `JointCommandSequence` |
| `sim2real.sim.homing.bench` | 64 Sobol starts plus 8 named rests × 3 models × 5 procedures; writes `src/sim2real/data/homing_fivebar_kinematic_<date>.json` |
| `sim2real.tracking.homing` | W&B "Homing · five-bar rig": one run per (rung, model, procedure); bbo evaluations and one leaderboard; nothing deleted |

Choices, each with its why:

1. **Drive stops are exact; the loop uses the exporter's map.** The procedures home on the drive stops, so those come from exact mesh contact (≤ 0.003° from CAD). The coupler/L1-tube contact, the shoulder weight and the closure limit only decide whether a start can reach its stops. They come from `loops.json` (2° on the export assembly, 0.25° on the mirrored crank), interpolated bilinearly so a link pressed along the boundary follows it smoothly. Exact loop contact would need the passive joints solved at every tick, and nothing rides on it at 0.01°.
2. **No inertia, so freed drives catch up at 2 rad/s.** A drive released from a contact it was pressing moves toward its setpoint at 2 rad/s, below the sequences' 3 rad/s speed guard. A lunge that trips the guard is dynamics, which the MuJoCo rung judges.
3. **The stored table comes from the bench, not the truth.** single_touch and two_level_touch read the table that press_reverse's fit identified from home on the same plant (B's `identify_backlash`). Their backlash column shows '—', because they did not identify it.
4. **tview v2 runs as typed.** Zach's set-output values are its zero. J1 and J2 are in the CAD frame to his typing precision. C1's 0.66347 rev is in his own crank frame, which sits 41.08° from CAD with nothing else to place it, so it maps by that one constant. His runner's reaches are kept: 20° on the way, 3° at home.
5. **Its own checks are part of a procedure.** bam_homing's checked seek refuses on a rigid stop ("stiffness unresolved"). On B0 and B1 it refuses every start, and the bench reports that as the outcome.
