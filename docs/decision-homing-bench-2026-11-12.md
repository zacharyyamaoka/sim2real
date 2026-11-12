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

## The ruling on assembly-mode starts (2026-11-12, the coordinator)

Assembly-mode starts (the flipped crank, and any start on the mirrored assembly of `loops.json`) are judged on the MuJoCo rung. The kinematic rung's reliability gate is 100 % over working-assembly starts. The strict xfail `test_recover_first_homes_from_the_flipped_crank` stays as the kinematic record. Written into robot_models PEP 0002 addendum 1.

WHY: the kinematic plant has no gravity, so nothing carries the loop across the toggle between the two assemblies. A kinematic verdict on those starts measures the plant, not the procedure.

How the bench shows it: `bench.split_scorecards` puts `scorecards_by_scope = {working_assembly, assembly_mode}` beside the all-starts `scorecards`. Each card names where its verdict is taken (`judged_on`). On the kinematic rung the assembly-mode card is kept but has no gate verdict (`reliability_gate_pass: null`). `tests/test_homing_mujoco_rung.py` holds the split.

## The MuJoCo rung (2026-11-12)

| Where | What |
|---|---|
| `sim2real.sim.homing.mujoco_plant` | `MujocoRigPlant`: bam_fb_test_rig's v11 twin (`RigSim` on `bench_rig`, rack mount, gravity, the exporter's stop pairs, the loop `connect`) behind the same `HomingPlant` seam. Hidden backlash is gear_backlash's double joint at J1 3.5′ / J2 2.5′ / C1 4.0′: B1 `deadzone`, B2 `passive_joint`. J2 and C1 carry `bam_fivebar.plant.JMC_COGGING` in their Craig frame; J1 has no fitted cogging. The boards are PDs fed every 10 ms the way `PlantBackend` feeds them (ilimit_scale 0, no velocity target). |
| `sim2real.sim.homing.mujoco_bench` | the procedures (each behind recover_first) × B0/B1/B2 × the 8 named rests + the first 8 Sobol starts. Starts are placed on their assembly by walking the exporter's map, then settled unpowered. The JSON has the kinematic schema plus `verdicts` (the brief's two gates), `recovery_landing` per episode, and `--timed-recovery` DIAGNOSTIC rows. |

Choices, each with its why:

1. **The twin is loaded by path from bam_ws** (`mujoco_plant.bam_ws_path`). The five packages are pure Python over numpy and MuJoCo 3.11.0, which the `sim` extra pins. Taking bam_fb_test_rig's environment as a dependency would bring in ruckig and opencv-contrib. This is the same reason `tracking.rigs.load_bbo` loads bbo by file.
2. **No gravity comp.** A blind homing run does not know its zero, so the host cannot compute a gravity torque. The real home button's comp works because it carries a homed frame by receipt. The boards are bare PDs at the rack record's kp 200 / kd 4 N·m per rev.
3. **Starts settle unpowered.** The real arm powers up where gravity and friction left it, so the bench records the settled pose and its assembly per start.
4. **A start is walked onto its assembly.** Gauss-Newton straight from the export pose does not converge, so the walk follows the exporter's (J2, C1) map, the mirror from its toggle seed. Each pose is checked by the passive dyad's orientation, which is the exporter's branch rule.

## Ground truth first: the real home button on the MuJoCo rung (2026-11-12, third pass)

The second pass failed every row because recover_first's step 3 never completed under gravity, while the real arm's home button (bam_rack_twin `fivebar_home -f`) recovered it repeatedly. Zach's rule is to prove in sim against ground truth, and here reality is the ground truth, so the plant was checked against the real runs before any procedure was judged on it.

| Where | What |
|---|---|
| `tools/extract_home_button_real.py` → `data/fivebar_home_button_real_2026-11-12.json` | every complete real `stage: home` receipt (t1 from the closure fold, gate-1 from a working rest, repeat-floor from home): the start, each step's outcome / seconds / end pose read off the tick rows, the comp each walked on. |
| `sim2real.sim.homing.home_button` | `bam_fivebar_recovery.home.return_home` itself, through `PlantBackend`, on the real bench (`bench_real`), the run's comp and the homed map's home, with `MujocoRigPlant` behind bam_fivebar's `Plant` seam in Craig angles (`RigBoards`). `verdict`: complete, same steps in order, end within the button's own reach (3.44°). |
| `sim2real.sim.homing.sag_proof` | what `RecoverFirst(sag_proof=True)` wraps the whole sequence in on the MuJoCo rung (`mujoco_bench.make`): a `Reached` move may also end still at its target within cap / kp; a seek that begins at a step re-holds first (the home button's settle) and stalls only past cap / kp. |

Findings and choices, each with its why:

1. **The plant was not the gap.** The home button's sequences complete in the sim from all three real starts on B0 / B1 / B2 and end within 1.1° of the real ends (`data/fivebar_home_button_replay_2026-11-12.json`). The real arm never ran blind_recovery: its references are the July bench's. The second pass compared two different sequences.
2. **The boards are now the real record.** The runs' config checks show CAN 12 (J2) at kp 144 / kd 8 N·m per output rev, not 200 / 4 (`mujoco_plant.REAL_BOARD_RECORD`, the default). The integrator never acts on either: `PlantBackend` sends `ilimit_scale` 0, so the real boards are PDs as the sim's were. The coordinator's guess that the real boards carried an integrator does not hold for the home button.
3. **sag_proof is on only where gravity is.** The kinematic rung keeps its results as run (`RecoverFirst.sag_proof` defaults off). sag_proof changes when a seek may call itself stalled and lets a move end short of a target gravity will not let it reach, with the pose recorded per step (`mujoco_bench.step_ends`). It changes no define, press, `Elapsed`, zero arithmetic or gate.
4. **robot_msgs needed one fix.** `JointCommandSequenceController` kept one dwell timer per joint, so a tight `Reached` that never held reset a looser one on the same joint every tick. It now keeps one per (condition, joint) (robot_msgs 9acaa74, regression test red first).
5. **The fold start is replayed on both assemblies.** t1's rest does not close on the real bench, and on the CAD it closes about 2° short of the reading on either side of the fold. Both are replayed from the nearest closed pose (`home_button.nearest_closed_pose`), and the report says how far short.
