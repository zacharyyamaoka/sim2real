# Sim2Real: KPIs, gates and the curriculum

*2026-11-11 · status as of sim2real `main` @ `7fac172b0` · written by `docs/build_kpis_gates_curriculum.py` from `sim2real.rack_results.load(...)` through
`sim2real.tracking.wandb_log.records()`, the same records the W&B runs are made from · angles in degrees, lengths in mm*

## The answer

- **The KPIs are five questions every node of the tree answers in order: Floor → Data → Routines → Twin → Job.** A node's verdict is
  its first "no"; a parent passes a question only if it does at its own output and every child does. Each question has one hard gate;
  the numbers beside it are soft KPIs you push inside the gate.
- **UR wrist today:** CAN 16 *passes all five*. CAN 15 *stops at Job*: it settles
  0.339° from its target against its 0.329° share of the 1 mm tool gate.
  CAN 14 *stops at Twin*: driven it is 1.13× its floor, but its passive
  release is 102.6×. The arm, the holder board and the deployment read
  *stops at Floor*: nothing revisits a tool stop yet.
- **Five-bar today:** J2 and C1 both read *stops at Routines* (only their gravity is graded on a hidden truth). Behind
  that, their twins are 3.69× and 2.36× their floors, and the tool
  settles 2.4 mm from its target against the 1 mm gate.
- **The curriculum is the same five answers climbed in work order:** S0 described → S1 routines recover a hidden truth in sim → S2 real
  floor → S3 coverage → S4 twin ≤ 1.5× floor → S5 job, at every joint; A0–A5 for an arm (tool repeats, the 1 mm tool gate), T0–T5 for
  a tool, D0–D5 for a deployment. A rung passes exactly when its question does.
- **Next rungs:** the wrist's holder board (T1: its TCP and payload graded in sim; T2: one stop revisited, the tool by encoders + FK), then CAN 14's
  passive twin (S4) and CAN 15's settled stop (S5). The five-bar's S1: grade friction, armature and delay in sim at 1× noise (the
  one-click seam the wrist got today), then its twin (S4) and the tool gate.
- **The gates, in Zach's order (2026-11-11 21:50), all from the joint encoders through FK:** target vs sim (the controller) →
  sim vs real (the twin, ≤ 1.5× the same-input floor on the tick clock) → target vs real (the tool ≤ 1 mm at a settled stop). ArUco is a
  flag, never a gate. UR wrist: gate 1 (target vs sim at a stop) **passes**: the twin's tool settles 0.71 mm from its target on gains: pick_sliding · settled stops (multi3); gate 2 (twin) **fails**; gate 3 (tool at a stop) **fails**: 1.05 mm on gains: pick_sliding · settled stops (multi3). Five-bar: gate 1 (target vs sim at a stop) **fails**: the twin's tool settles 1.54 mm from its target on gravity comp: identified + settle integrator (RAM only); gate 2 (twin) **fails**; gate 3 (tool at a stop) **fails**: 2.41 mm on gravity comp: identified + settle integrator (RAM only).
- **W&B, live: one project per rig**, [Sim2Real · wrist rig](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20wrist%20rig), [Sim2Real · five-bar rig](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20five-bar%20rig), on bam_ws's `bam_trackio.bbo` template (Zach's direction, relayed by the W1 sprint),
  with the same gate names on both and `type`, `joint` and `deployment` config on every run; one W&B run per version of what is fitted
  (each twin iteration, each controller configuration). The one-project layout I first recommended (proposal B) stays in `Sim2Real`
  (44 runs; the filter `type = integrated_servo` returns the 5 servo joints of both rigs),
  and its filter-by-type view now lives on as the cross-rig report there.

> [!note] What moved since the brief (its numbers were sim2real `662e64d`)
> - **Wrist Routines:** the one-click seam (sim2real `82f14db`, wired in `7f8d13b`) recovers CAN 14 8/8, CAN 15 6/6, CAN 16 6/6 and the
>   arm's 2/2 identifiable parameters at 1× noise on a sealed truth, so no wrist joint stops at Routines any more.
> - **Joint Job** (`d626be9`): each joint's settled error is now held against its share of the 1 mm tool gate, 1 mm ÷ (lever × √joints)
>   (an RSS split, proposed): CAN 15 0.329°, CAN 16 0.957°, CAN 14
>   0.411°; J2 0.136°, C1 0.144°.
> - **C1 coverage:** 34.1 % → 44.3 % after seven C1 swings (`coverage_real_031652`, `7f8d13b`), so
>   C1 now stops at Routines like J2.
> - **Wrist workspace:** the source says 60.55 % (`multi3/multi_scores.json` real_all); the page prints it to one place as 60.5 %.
> - **Five-bar tool:** 9.6 mm at the 16 settled holds on the nominal gravity compensation → 2.4 mm on the identified comp + settle integrator (`data/fivebar_dwell_settle_2026-11-11.json`; RAM only: the boards' integrator (ki 1000, ilimit 0.58 / 0.66 N·m) is not a board default; written for the run, restored after); the tool's Job reads the newest config in the Job history, the older runs stay beside it as controller versions.
> - **Unchanged:** the floors (0.099 / 0.087 /
>   0.241° wrist, 0.160 / 0.187° five-bar), the twin
>   ratios (1.13× / 1.38× / 0.78×;
>   3.69× / 2.36×).

## 1 · The KPIs and gates (as decided 2026-11-11)

Proposal C of the vault note *Sim2Real KPIs and Gates — 3 Proposals and What Good Looks Like per Type (2026-11-11)*, as `result.py`
and `rack_results.py` implement it tonight.

| # | Question | It asks | Hard gate | Soft numbers beside it | Rule |
|---|---|---|---|---|---|
| 1 | **Floor** | How much does the real thing disagree with itself? | ≥ 5 repeats of one input per run kind; a pair counts only if its commands agree within 0.01° RMS, compared tick for tick when the run carries its plan tick; driven, and passive or N/A with a measured reason; twin ÷ floor never below 0.71 | floor (°), same-input pairs, runs, per run kind | decided; passive N/A proposed |
| 2 | **Data** | Is the data enough? | joint: ≥ 40 % of its reachable (angle, speed, acceleration) cells visited by real runs; arm: joint cube ≥ 90 %, workspace ≥ 50 %, facing or heading ≥ 90 % of the allowed mask; held-out split sealed before fitting; physical runs for a physical deployment | coverage %, samples, minutes logged | thresholds proposed |
| 3 | **Routines** | Does each calibration routine get a hidden truth back, in sim? | every identifiable value within its tolerance of a sealed truth at 1× the real sensor noise, the truth off the search grid; the nominal value fails its own tolerance; then the stress ladder (3×, 10×, delay and quantisation variants) | k of n identifiable recovered; error ÷ tolerance; wall and operator time | decided |
| 4 | **Twin** | Is the twin as good as reality allows? | held-out sim vs real ≤ 1.5× the floor **of the same run kind**, passive and driven (≤ 3× reads "close") | the ratio per run kind; before → after; how many times better than "it follows its target" | decided |
| 5 | **Job** | Does the real thing do its job? | joint: settled stop error within its share of the tool gate; tool: **≤ 1 mm at a stop**, on settled holds, at the tool by the joint encoders through FK (Zach, 21:50) | real vs target; feedback-torque share, RMS(τ − τ_ff) ÷ RMS(τ), falling (≤ 0.3 proposed); the sim predicting its own tracking | 1 mm decided (Zach); joint share proposed |

**How it rolls up**

- **The verdict is the first "no":** "stops at Data" means Floor passed and Data did not; the later answers are still computed and
  shown beside it.
- **A parent passes a question only if it answers yes at its own output (an arm at its tool pose, a deployment at its picks) and every
  child passes it** (`CalibrationResult.verdicts()`). So the deployment's line is the answer for the whole rig, and a joint that is
  twinned on its own cannot make an arm twinned whose coupled moves are not.
- **The numbers roll up softly:** medians of the children, the worst child's twin ratio, the tool in mm.

**The rules behind each gate**

- **Floor, from same-input repeats only** (`metrics.series.repeat_floor`). Repeats are grouped per run kind and controller gains (T1:
  like for like) and compared tick for tick when the run carries its plan tick: on the host's wall clock, ~1 ms of jitter put identical
  five-bar tapes 1.6–3.1° apart. **The floor check:** with each real run = truth + independent noise, floor² = 2σ² and gap² = bias² + σ²,
  so a twin cannot sit below 1/√2 ≈ 0.71× its floor; one that does fails *Floor* (its "repeats" were not repeats), it does not pass Twin.
- **Twin on the floor's own run kind:** the wrist's twin is judged on its repeat campaign's tape (`cycle-s4`, `cycle14-a`), the
  five-bar's on the five repeats of the 0.05 m/s gravity-feed-forward rung, replayed on the after twin.
- **Passive "N/A with a measured reason" (proposed, Zach to confirm):** a joint that cannot move unpowered answers N/A instead of
  failing Floor forever. CAN 15 and 16 carry at most 0.012 N·m of gravity against 0.140 and 0.186 N·m of breakaway; the five-bar's J2
  and C1 rest at the closure fold, where gravity cannot move them, and larger releases fall 40–80° at up to 1,300°/s.
- **Data thresholds (proposed, coordinator 2026-11-11, Zach to confirm):** per joint ≥ 40 % of reachable (angle, speed, acceleration)
  cells; arm: cube ≥ 90 %, workspace ≥ 50 %, facing (wrist) or heading (five-bar) ≥ 90 %. The joint's reachable cells come from its
  committed description; for these joints every cell of the box counts as reachable, so it is the visited share of the full box.
- **Routines means recovering the hidden truth, in sim, within tolerance, under noise:** the oracle's rule (`sysid/acceptance.json`):
  every hidden value within its tolerance at 1× sensor noise, and the nominal fails its own tolerance so "return the description
  unchanged" fails; the noise ladder (`sysid/noise_ladder.json`): 0×, 1×, 3×, 10×, bound min(k × tol, max(tol, |nominal − true|)).
- **Job: the tool gate is 1 mm at a stop** (Zach, 2026-11-11: "we certainly need final tool error sub 1mm", was 5 mm), **measured on
  settled holds**: the five-bar's 16 three-second mass-ID holds, not the raster's turnarounds (median 0.06 s: tracking, not settled). A
  joint's share of it is 1 mm ÷ (lever × √joints), an RSS split (proposed); `tools/tool_levers.py` measures each rig's lever.

**Still sized for 5 mm in code** (to re-derive at 1 mm; not changed here):

- `cards/domain_v3.json`: `arm.tool_error_at_stop.gate`, `pick.grasp_pose_error.gate` and `conveyor.object_position.gate` are ≤ 5 mm.
- `cards/servo_gates.py`: `STOP_ALLOCATION_MRAD` and T4's rule text allocate "the 5 mm tool gate" (about 3 mm RSS inside 5 mm).
- `sysid/acceptance.json`: tolerances are set for "a 5 mm tool budget"; the ur5e examples' held-out tool is 5 mm.

### 1.1 Zach's gate rulings (2026-11-11 21:50) and the same-named gates

- **Every gate and tracking error comes from the joint encoders through FK, never the camera.** The five-bar's tool at a stop is the
  16 settled holds through the encoders and the CAD lever (`encoders_fk_mm`); the D435's number (camera vs the commanded target) is kept
  beside it as a flag only, under a name no gate reads.
- **ArUco is a 6-DOF tracked point logged as a flag, never a gate** (`aruco_vs_fk_mm`: the tag vs the encoders' FK at the same instant;
  a large value says look at the stickers or the as-built geometry, it passes or fails nothing). Not measured yet on either rig.
- **The gate order: target vs sim first, then sim vs real, then target vs real.** Target vs sim is the controller alone (does the
  controller do the job in a sim that is right by construction?); sim vs real is the twin (held-out, ≤ 1.5× the same-input repeat floor
  on the tick clock, the tree's Twin answer); target vs real is the job. A later gate is read only after the earlier ones: a real tool
  error cannot be blamed on the twin until the controller passes in sim.
- **Tool gate 1 mm at a settled stop.** `target_vs_real_at_stop_mm` is the same number as `tool_error_at_stop_mm` under its gate-order
  name; `target_vs_sim_at_stop_mm` holds the controller to the same 1 mm in sim (proposed: the sim must pass before the real rig can).

**The gates, one metric name each on both rig projects** (`sim2real.tracking.rigs.GATES`; "today" is the latest version that measures
it: the latest twin for the twin gate, the last controller configuration that ran for the rest):

| Order | Metric (same name on both rigs) | Role | Limit | UR wrist today | Five-bar today |
|---|---|---|---|---|---|
| 1 · target vs sim (controller) | `target_vs_sim_tracking_deg` | kpi | — | 0.148° · gains: pick_sliding | 0.919° · winners + lumped comp |
| 1 · target vs sim (controller) | `target_vs_sim_at_stop_mm` | gate | ≤ 1 mm (proposed) | 0.71 mm · **passes** · gains: pick_sliding · settled stops (multi3) | 1.54 mm · **fails** (1.5× the gate) · gravity comp: identified + settle integrator (RAM only) |
| 2 · sim vs real (twin) | `heldout_sim_vs_real_deg` | gate | ≤ 1.5× floor, per joint | 0.118° · **fails** (CAN 14 over 1.5× floor) · latest twin (it5 + gravity refit) | 0.559° · **fails** (J2, C1 over 1.5× floor) · latest twin (refit on the tick clock) |
| 3 · target vs real | `tracking_rms_deg` | kpi | — | 0.340° · gains: pick_sliding | 0.785° · winners + lumped comp |
| 3 · target vs real | `tracking_rms_tool_mm` | kpi | — | not measured | 5.65 mm · winners + lumped comp |
| 3 · target vs real | `target_vs_real_at_stop_mm` | gate | ≤ 1 mm | 1.05 mm · **fails** (1.05× the gate) · gains: pick_sliding · settled stops (multi3) | 2.41 mm · **fails** (2.4× the gate) · gravity comp: identified + settle integrator (RAM only) |
| 3 · target vs real | `tool_error_at_stop_mm` | gate | ≤ 1 mm | 1.05 mm · **fails** (1.05× the gate) · gains: pick_sliding · settled stops (multi3) | 2.41 mm · **fails** (2.4× the gate) · gravity comp: identified + settle integrator (RAM only) |
| 3 · target vs real | `home_repeatability_deg` | kpi | — | not measured | not measured |
| flag | `aruco_vs_fk_mm` | flag | — | not measured | not measured |

**Read in that order, today:**

- **UR wrist:** gate 1 (target vs sim at a stop) **passes**: the twin's tool settles 0.71 mm from its target on gains: pick_sliding · settled stops (multi3); gate 2 (twin) **fails**; gate 3 (tool at a stop) **fails**: 1.05 mm on gains: pick_sliding · settled stops (multi3). The controller in sim on the operating gains (pick_sliding) tracks to
  0.148° (worst joint, held-out runs on the twin of
  record), the real joints to 0.340°. At a stop the twin's holder passes 1 mm and the real one
  just misses it (1.05 mm; twin vs real 0.28 mm at the same stops), so the first fix is the twin (CAN 14's passive
  release) and a tool floor, not the controller.
- **Five-bar:** gate 1 (target vs sim at a stop) **fails**: the twin's tool settles 1.54 mm from its target on gravity comp: identified + settle integrator (RAM only); gate 2 (twin) **fails**; gate 3 (tool at a stop) **fails**: 2.41 mm on gravity comp: identified + settle integrator (RAM only). Gate 1 fails first: the controller misses the tool gate in a sim that is right by
  construction (1.54 mm vs the real arm's 2.41 mm), so
  the tool gap is the controller's (gains, compensation, hold logic) before it is the twin's; the twin's tool is
  2.58 mm from the real one at the same holds. Coulomb feed-forward is a controller change, and it shows first in gate 1: target vs sim
  went 1.39° → 0.37°
  (worst joint) and the sim's tool 7.4 → 3.0 mm,
  before the real tool's 9.4 → 6.1 mm.

**Controller versions, UR wrist** (target vs sim: bam_ur_wrist_coverage's own score on the twin of record, held-out runs, CAN 15 and 16
only; target vs real: each coverage run's RMS per joint, averaged):

| # | Controller version | target vs sim, worst joint | target vs real, worst joint | per joint, sim / real | tool tracking, sim / real | tool at a settled stop (encoders + FK) | camera vs commanded (flag) |
|---|---|---|---|---|---|---|---|
| 1 | gains: stock | 10.664° | 10.184° | CAN 15 9.906° / 10.072°, CAN 16 10.664° / 10.184° | — | — | — |
| 2 | gains: ram | 0.359° | 0.446° | CAN 15 0.359° / 0.446°, CAN 16 0.332° / 0.349° | — | — | — |
| 3 | gains: pick_sliding | 0.148° | 0.340° | CAN 15 0.148° / 0.340°, CAN 16 0.119° / 0.279° | — | — | — |
| 4 | gains: pick_sliding · settled stops (multi3) | — | — | — | — | 1.05 mm (fails 1 mm; p95 1.3); sim 0.71 mm (passes), sim vs real 0.28 mm | — |

**Controller versions, five-bar** (tracking: each coverage rung's own metrics, the real run and the sim the ladder ran beside it on the
same plan, averaged over the rungs; the tool at a stop: the 16 three-second holds, last second scored):

| # | Controller version | target vs sim, worst joint | target vs real, worst joint | per joint, sim / real | tool tracking, sim / real | tool at a settled stop (encoders + FK) | camera vs commanded (flag) |
|---|---|---|---|---|---|---|---|
| 1 | gravity comp: nominal | — | — | — | — | 9.56 mm (fails 1 mm; p95 40.1) | 20.73 mm |
| 2 | Coulomb feed-forward: none (stock) | 1.387° | 1.701° | J2 1.387° / 1.701°, C1 1.294° / 1.564° | 7.37 mm / 9.38 mm | — | — |
| 3 | Coulomb feed-forward: 0.70 / 0.78 N·m (winners) | 0.370° | 1.096° | J2 0.370° / 1.096°, C1 0.263° / 0.681° | 2.97 mm / 6.06 mm | — | — |
| 4 | winners + lumped comp | 0.919° | 0.785° | J2 0.919° / 0.785°, C1 0.490° / 0.596° | 4.71 mm / 5.65 mm | — | — |
| 5 | gravity comp: identified | — | — | — | — | 4.34 mm (fails 1 mm; p95 8.9); sim 4.19 mm (fails), sim vs real 3.30 mm | 19.87 mm |
| 6 | gravity comp: identified + settle integrator (RAM only) | — | — | — | — | 2.41 mm (fails 1 mm; p95 7.1); sim 1.54 mm (fails), sim vs real 2.58 mm | — |

## 2 · The curriculum

**How to read it.** The verdict reads the five questions in *check* order (Floor first: a wrong floor makes every later number
meaningless). The ladder is climbed in *work* order: Routines first, because it needs no rig time (prove a routine on a hidden truth in
sim before trusting it on hardware), then the rig rungs from cheapest to dearest. A rung passes exactly when its question passes, so the
two orders read the same answers; "next rung" and "stops at" can name different questions only when more than one is open. Today they
agree on every node. `sim2real.tracking.curriculum` holds the ladders; each W&B run carries its node's rungs.

### 2.1 The ladders

**Joint (every actuator or sensor type; the integrated servo here)**

| Rung | What | Reads | Gate |
|---|---|---|---|
| **S0** | Described | — | a sim2real type with a nominal model, its parameters and their tolerances |
| **S1** | Routines recover the hidden truth in sim | Routines | noise-free, then 1× the real noise with the truth off the search grid, then the stress ladder (3×, 10×, delay and quantisation variants): every identifiable value within its tolerance, and the nominal value fails its own |
| **S2** | Real floor known | Floor | ≥ 5 repeats of one input per run kind (commands within 0.01°, compared tick for tick); driven, and passive or N/A with a measured reason (proposed); twin ÷ floor never below 0.71 |
| **S3** | Coverage | Data | ≥ 40 % of the reachable (angle, speed, acceleration) cells visited by real runs (proposed); the held-out split sealed before fitting |
| **S4** | Twin within 1.5× the floor | Twin | held-out sim vs real on the floor's own run kind ≤ 1.5× the floor, passive and driven |
| **S5** | Does its job | Job | settled stop error within the joint's share of the tool gate (1 mm at a stop); feedback-torque share falling |

**Arm (rigid body chain)**

| Rung | What | Reads | Gate |
|---|---|---|---|
| **A0** | Described | — | the chain, its mounts and a committed reachable mask |
| **A1** | Arm routines recover the truth in sim | Routines | kinematics, mounts, joint zeros, delay and the gravity direction at 1× noise, truth sealed |
| **A2** | Tool repeats | Floor | the same commanded tool pose revisited (ISO 9283 RP: 5 poses × 30 cycles), the tool by the joint encoders through FK |
| **A3** | Arm coverage | Data | joint cube ≥ 90 %, workspace ≥ 50 %, facing or heading ≥ 90 % of the allowed mask (proposed) |
| **A4** | Coupled twin | Twin | twin vs real tool pose ≤ 1.5× the tool floor on coupled multi-joint moves |
| **A5** | Tool gate | Job | tool ≤ 1 mm at a stop, on settled holds (not raster turnarounds), at the tool by the joint encoders through FK |

**Tool (payload + TCP)**

| Rung | What | Reads | Gate |
|---|---|---|---|
| **T0** | Described | — | the TCP and payload, with their tolerances |
| **T1** | Tool routines recover the truth in sim | Routines | payload mass 5 %, centre of mass 3 mm, TCP 0.5 mm across and 1 mm along |
| **T2** | Tool repeats | Floor | the tool at the same commanded stop, revisited, by the joint encoders through FK |
| **T3** | Tool seen widely | Data | the TCP seen from spread poses; payload classes |
| **T4** | Tool twin | Twin | the after twin's tool vs the real tool at stops ≤ 1.5× the tool floor |
| **T5** | Tool gate | Job | real tool vs commanded ≤ 1 mm at a stop, settled, at the tool by the joint encoders through FK |

**Deployment**

| Rung | What | Reads | Gate |
|---|---|---|---|
| **D0** | Described | — | physical or virtual, with its schedule of routines |
| **D1** | Every child's routines pass | Routines | the roll-up of its children's Routines |
| **D2** | Its output repeats | Floor | the deployment's own output repeated: the same scene run twice |
| **D3** | Physical runs, split sealed | Data | runs from every routine in its schedule; for a physical deployment, physical runs |
| **D4** | The sim ranks like reality | Twin | sim ranks policies in the order reality does (rank correlation > 0.9, proposed) |
| **D5** | Picks | Job | real picks, then successful picks per minute; tool ≤ 1 mm at a stop |

### 2.2 What each rung means, per generic type

The rungs are the same for every type; what changes is each gate's number. Tolerances are the oracle's (`sysid/acceptance.json`), hard
gates are `cards/domain_v3.json`'s; *proposed* marks a number no code holds yet.

| Type | S1 · Routines (tolerance at 1× noise) | S2 · Floor (what repeats) | S3 · Data (cells, ≥ 40 %) | S4 · Twin (≤ 1.5× floor) | S5 · Job (hard gate) |
|---|---|---|---|---|---|
| **integrated_servo** | gravity 2 %, gravity zero 0.29°, armature 5 %, Coulomb 10 %, Stribeck drop 25 % and speed 30 %, viscous 20 %, backlash 10 % (pendulum_can11) | one tape ×5, per run kind and gains | (angle, speed, acceleration) at the output | held-out angle, passive and driven; current ≤ 2× its scatter in closed loop (T3) | settled stop within its share of the 1 mm tool gate (T4); feedback share |
| **bldc_motor** | torque per amp, phase resistance (Kt ≤ 2 %, proposed) | dyno shaft torque, or current scatter | (angle, speed, acceleration) at the shaft | shaft torque; winding ≤ 5 °C | Kt within 5 % (T6); share of the datasheet speed-torque curve |
| **gearbox** | backlash 0.033° (2 arcmin) or 10 % | the hysteresis loop's 95 % half-width (T5) | (angle, speed, acceleration) at the output | output angle for the same input (needs an output encoder; a camera tag only as a flag) | lost motion ≤ 0.033° (2 arcmin) |
| **foc_controller** | command delay (≤ 1 ms, proposed); current-loop bandwidth | q-current scatter on one command | (q-current, speed) map | q-current ≤ 2× scatter; board temperature ≤ 5 °C | torque-cap share (≤ 1 %, proposed); loop rate ±10 % |
| **encoder** | quantisation known; eccentricity 10 % (proposed) | standstill spread; homing repeats | (angle, speed) | noise and quantisation spectrum | homing repeatability |
| **rigid_body_chain** | joint zeros 0.029°, armature 10 %, damping 20 %, friction 10 %, mounts 1 mm / 0.057° | the same tool pose revisited (ISO 9283 RP) | joint cube ≥ 90 %, workspace ≥ 50 %, facing ≥ 90 % (proposed) | tool pose ≤ 1.5× the tool floor | tool ≤ 1 mm at a stop, settled, at the tool |
| **gripper** | actuator gain 5 %, finger damping 15 % | the same grasp revisited | the arm's coverage at grasp poses | grasp pose ≤ 1.5× | grasp pose ≤ 5 mm in the card (to re-derive at 1 mm); picks per minute |
| **conveyor** | drum radius 0.1 %, moving mass 10 %, viscous 15 %, Coulomb 10 % | belt position run to run on one profile | (belt speed, load mass) | belt position ≤ 1.5× | object position ≤ 5 mm in the card |
| **camera** | pose 2 mm / 0.11°, focal 0.5 %, principal point 2 px | a static scene frame to frame; corner jitter | distance × incidence × light × material × exposure | sim overlay ≤ 1.5× | reprojection ≤ 0.5 px |
| **depth_camera** | depth scale 0.2 %, depth offset 1 mm, plus the camera's | temporal noise on a flat target | as the camera | cloud vs sim ≤ 1.5× | Z within 1 % of Z, plane RMS ≤ 0.4 % of Z, fill ≥ 99 % |
| **hyperspectral_camera** | focal 1 %, principal point 1 px, height 3 mm, across 1 mm, scan line 1 mm, scan yaw 0.11°, gain 2 %, dark 2 counts | the spectral angle between repeat cubes | × wavelength band × material class | rendered cube ≤ 1.5× | smile and keystone ≤ 1 px |
| **tool** (structural) | mass 5 %, centre of mass 3 mm, TCP 0.5 mm across, 1 mm along | the same stop revisited, encoders + FK | the TCP seen from spread poses | the after twin's tool ≤ 1.5× the tool floor | ≤ 1 mm at a stop, settled |
| **deployment** (structural) | every child's routines | its output repeated: the same scene twice | physical runs from every routine in its schedule | sim ranks policies like reality (r > 0.9, proposed) | picks per minute; tool ≤ 1 mm |

### 2.3 Today, per rig

✓ passes · ✗ no · ~ partial · ? unknown · ↓ its own answer is yes, a child holds it back. Each cell is the question's mark and its
headline number; the full text of every answer is on the result page (`load(...).display()`) and in each W&B run's `<Q>/numbers`.

**UR wrist on the One Dof Test Rack** (twins: twin of record 11-10 → it2 Karnopp refit → it3 refit → it5 + gravity refit)

| Node | Verdict | Floor | Data | Routines | Twin | Job | Next rung |
|---|---|---|---|---|---|---|---|
| UR wrist on the One Dof Test Rack | **stops at Floor** | ✗ no output repeat | ↓ physical runs, split sealed | ↓ roll-up | ↓ roll-up | ? no picks | D1 · Every child's routines pass |
| &nbsp;&nbsp;UR wrist (CAN 14 + 15 + 16) | **stops at Floor** | ✗ no tool-pose repeats | ↓ cube 100.0 %, workspace 60.5 %, facing 100.0 % | ↓ 2/2 at 1× noise | ? coupled moves: twin 0.13–0.35° vs target 0.14–0.31°, no tool floor | ✗ 0.71 mm vs 1 mm (settled holds) | A1 · Arm routines recover the truth in sim |
| &nbsp;&nbsp;&nbsp;&nbsp;CAN 14 wrist joint (revolute 11, moteus servo) | **stops at Twin** | ✓ 0.099° (10 pairs); passive 0.326° | ✓ 45.7 % of 1716 cells | ✓ 8/8 at 1× noise | ✗ 1.13×; passive 102.6× | ✗ 0.132° vs 0.411° share | S4 · Twin within 1.5× the floor |
| &nbsp;&nbsp;&nbsp;&nbsp;CAN 15 wrist joint (moteus servo) | **stops at Job** | ✓ 0.087° (10 pairs); passive N/A | ✓ 73.0 % of 1716 cells | ✓ 6/6 at 1× noise | ✓ 1.38× | ✗ 0.339° vs 0.329° share | S5 · Does its job |
| &nbsp;&nbsp;&nbsp;&nbsp;CAN 16 wrist joint (moteus servo) | **passes all five** | ✓ 0.241° (10 pairs); passive N/A | ✓ 71.2 % of 1716 cells | ✓ 6/6 at 1× noise | ✓ 0.78× | ✓ 0.289° vs 0.957° share | climbed |
| &nbsp;&nbsp;&nbsp;&nbsp;holder board #4-7 (tool) | **stops at Floor** | ✗ no revisit of one tool stop: the tool fl | ? not measured | ? not graded | ? no ratio | ✗ 0.71 mm vs 1 mm (settled holds) | T1 · Tool routines recover the truth in sim |

Held-out sim → real median per twin iteration (held-out runs in brackets): the it3 refit got *worse* on held-out tapes while its all-run
median improved (an overfit), before it5 + gravity brought it to about 0.12°.

| Node | 1 · twin of record 11-10 | 2 · it2 Karnopp refit | 3 · it3 refit | 4 · it5 + gravity refit |
|---|---|---|---|---|
| UR wrist on the One Dof Test Rack | 0.456° (72) | 0.421° (72) | 0.859° (72) | 0.118° (87) |
| CAN 14 wrist joint (revolute 11, moteus servo) | — | — | — | 0.112° (5) |
| CAN 15 wrist joint (moteus servo) | 0.473° (38) | 0.479° (38) | 0.937° (38) | 0.110° (43) |
| CAN 16 wrist joint (moteus servo) | 0.448° (34) | 0.413° (34) | 0.850° (34) | 0.129° (39) |

**Five-bar on the One Dof Test Rack** (twins: study twin (nominal) → + mass-ID gravity → + dynamics refit → refit on the tick clock)

| Node | Verdict | Floor | Data | Routines | Twin | Job | Next rung |
|---|---|---|---|---|---|---|---|
| Five-bar on the One Dof Test Rack | **stops at Floor** | ✗ no output repeat | ↓ physical runs, split sealed | ↓ roll-up | ↓ roll-up | ? no picks | D1 · Every child's routines pass |
| &nbsp;&nbsp;five-bar arm (J2 + C1 driven, J3 / C2 passive) | **stops at Floor** | ✗ no tool-pose repeats | ↓ cube 100.0 %, workspace 85.4 %, heading 100.0 % | ? not graded | ✗ per joint only | ✗ 1.54 mm vs 1 mm (settled holds) | A1 · Arm routines recover the truth in sim |
| &nbsp;&nbsp;&nbsp;&nbsp;J2 shoulder (CAN 12, moteus) | **stops at Routines** | ✓ 0.160° (10 pairs); passive N/A | ✓ 50.4 % of 1694 cells | ~ gravity only | ✗ 3.69× | ✗ 0.170° vs 0.136° share | S1 · Routines recover the hidden truth in sim |
| &nbsp;&nbsp;&nbsp;&nbsp;C1 crank (CAN 13, moteus) | **stops at Routines** | ✓ 0.187° (10 pairs); passive N/A | ✓ 44.3 % of 1694 cells | ~ gravity only | ✗ 2.36× | ✗ 0.247° vs 0.144° share | S1 · Routines recover the hidden truth in sim |
| &nbsp;&nbsp;&nbsp;&nbsp;tool point (L2 tip) | **stops at Floor** | ✗ driven 1.7 / 1.3 mm; no settled tool revisit | ? not measured | ? not graded | ✗ 3.10× | ✗ 1.54 mm vs 1 mm (settled holds) | T1 · Tool routines recover the truth in sim |

Held-out sim → real median per twin iteration (the study twin scored every rung; the refits scored their own held-out rungs, so the
counts differ):

| Node | 1 · study twin (nominal) | 2 · + mass-ID gravity | 3 · + dynamics refit | 4 · refit on the tick clock |
|---|---|---|---|---|
| Five-bar on the One Dof Test Rack | 0.892° (68) | 0.632° (20) | 0.626° (20) | 0.559° (24) |
| J2 shoulder (CAN 12, moteus) | 1.099° (34) | 0.613° (10) | 0.609° (10) | 0.566° (12) |
| C1 crank (CAN 13, moteus) | 0.657° (34) | 0.635° (10) | 0.626° (10) | 0.537° (12) |

### 2.4 The next rung per rig

**UR wrist**

1. **The holder board, T1 and T2.** It is the one node with no evidence at all ("no tool runs: the holder board is not tracked"), and
   it holds back the arm (A1, A2) and the deployment (D1, D2). T1: grade its TCP and payload on a sealed truth in sim, the way the
   one-click seam already grades the joints. T2: revisit one commanded stop ≥ 5 times, the holder's point by the joint encoders through FK (ISO 9283 RP); a tag on it is
   logged beside it as a flag.
2. **CAN 14, S4 (passive twin).** Driven it is 1.13× its floor. On its passive release
   (`release60`: let go near 142°, the real joint swings and rests near 80°) the twin rests 34.5° away from the real joint, which is
   102.6× its 0.326° passive floor: the released
   joint's gravity or breakaway model is wrong.
3. **CAN 15, S5 (settled stop).** 0.339° median on its operating gains (pick_sliding) against its
   0.329° share; on the repeat campaign's gains it settles at 0.311°, inside it.

**Five-bar**

1. **J2 and C1, S1.** Only the gravity is graded on a hidden truth (`bam_fivebar tests/test_massid.py`). Port the wrist's one-click seam
   (`RobotTwin(...).calibrate(on='sim', truth='sealed')` at 1× noise) so friction, armature and delay are graded too; the arm's A1 and
   the tool's T1 come with it.
2. **Then S4.** The after twin is 3.69× (J2) and 2.36× (C1) its floor
   on the floor's own tape; the gate is 1.5×.
3. **Then the tool gate (A5, T5).** The tool settles 2.4 mm from its target by
   encoders + FK against 1 mm. C1 is the bigger term: it settles 0.247° from its target, 1.7× its 0.144° share (J2: 1.2×).

## 3 · Tracking it in W&B: three proposals

**Your question:** "Should we have one weights and biases project per generic type? This could be a lot of projects. But I guess for
each one it's a bit unique, no? OK, having it in one location could work, if we can filter that data to show it for particular types
of models or something…"

**What the question assumes:**

- **"A lot of projects" is the cheap part of the cost.** The dear part is that per-type projects split one rig's tree: the wrist's
  deployment, arm, three joints and holder would land in four projects. "A parent passes only if every child does" would then be
  visible nowhere, and a W&B workspace cannot hold runs from two projects (only a report can).
- **"Each one is a bit unique": less than it looks.** Every node answers the same five questions with the same words; that is the
  point of proposal C. What is unique per type is its Job metric and unit (px, mm, °, %) and its coverage axes: config and summary
  keys, data rather than structure.
- **What a W&B run is.** Not a rig run (the wrist calibration has 400+); those stay in the archive, on the result page and in Rerun
  (the house rule: "we own our data … W&B only ever gets a copy"). A W&B run is one node's evaluation at one twin iteration, so W&B
  tracks the verdicts and their numbers over time.

**Criteria, weighted for now:**

| # | Criterion | Weight | Why it matters now |
|---|---|---:|---|
| 1 | **One place, filterable at a glance** | 25 | your worry, and "at a glance I can look at any level, and navigate that with the tree" |
| 2 | **Like with like, across rigs and within one** | 20 | a servo type is judged across its units (`TYPE_GATES` T1–T8 vs `UNIT_GATES`); a rig across its types (the roll-up) |
| 3 | **Keeps the tree and its roll-up together** | 15 | the verdict rolls up deployment → arm → joint → tool |
| 4 | **Cost of growth** | 15 | 11 generic and 6 structural types today; deployments multiply fastest (every rig, every customer cell) |
| 5 | **Type-specific numbers stay honest** | 10 | px, mm, ° and % must never share an axis |
| 6 | **House conventions** | 10 | entity `zach-yamaoka-independent`; Title Case project names ("Traj Gen", "Grasp Detection"); views and reports built from code |
| 7 | **Sharing one deployment outside** | 5 | W&B permissions are per project; a customer's cell may be shared one day |

**A · One project per generic type** ("Integrated Servo", "Gearbox", "Camera", "Conveyor", "Rigid Body Chain", … up to 17)

- *For:* one schema per project and a clean auto-made workspace; one type compares across rigs natively. It mirrors today's split of
  the pick-place ladder into "Grasp Detection" and "Traj Gen".
- *Against:* a rig's tree is spread over 4–6 projects and its roll-up is visible nowhere; a deployment view needs a cross-project
  report; every new type is a new project with its own views.
- *Scores:* one place 1 · like with like 3 (across rigs 5, within a rig 1) · tree 1 · growth 2 · honest numbers 5 · house 4 · sharing 2.

**B · One project, `Sim2Real`, every run configured and filtered** (recommended on these criteria and built first; superseded as the home by C per rig, below)

- *For:* filter `type = integrated_servo` and get every servo on every rig; `deployment = fivebar` and get its whole tree; group by
  either; one overview over everything. A new type or deployment is a new config value; its view and report are generated from the runs
  present (`build_views`).
- *Against:* one key namespace, so type-specific keys sit sparse beside each other. Kept honest by units in every key name (`_deg`,
  `_mm`, `_pct`) and by per-type views that chart only that type's keys.
- *Scores:* one place 5 · like with like 5 · tree 5 · growth 4 · honest numbers 3 · house 4 · sharing 3.

**C · One project per deployment** ("UR Wrist Test Rig", "Five-bar Test Rig", "Conveyor", …), types as config

- *For:* it mirrors `result.display()`: one tree per project; sharing one customer's cell is clean.
- *Against:* a type across rigs needs a cross-project report; deployments are the fastest-growing count; the house's own deployment
  mirror (bam_ws `bam_deployments`, project `bam-deployments`) is one project grouped by deployment, not one per deployment.
- *Scores:* one place 3 · like with like 2 · tree 5 · growth 2 · honest numbers 3 · house 3 · sharing 5.

| Criterion (weight) | A · per type | B · one project | C · per deployment |
|---|---:|---:|---:|
| One place, filterable (25) | 1 | **5** | 3 |
| Like with like (20) | 3 | **5** | 2 |
| Tree and roll-up together (15) | 1 | **5** | **5** |
| Cost of growth (15) | 2 | **4** | 2 |
| Type numbers honest (10) | **5** | 3 | 3 |
| House conventions (10) | **4** | **4** | 3 |
| Sharing outside (5) | 2 | 3 | **5** |
| **Total (of 100)** | **46** | **89** | **61** |

**My recommendation on these criteria was B** (89), and it was built first. **What is live is C, per rig, with B's config on every
run**, because you set the direction tonight (relayed by the W1 sprint): bottom-up per sub-assembly, each rig introspected through W&B
and Rerun, in projects named "Sim2Real · five-bar rig" and "Sim2Real · wrist rig" on the house black-box template (bam_ws
`bam_trackio.bbo`: one W&B project per black-box family, its versions on leaderboards). Your call outranks my scoring, and the
criteria above did not weigh what it adds:

- **One leaderboard per sub-assembly.** A rig is the black box being optimised; its twin iterations and controller configurations are
  its versions, ranked on the same environment. In one shared project those leaderboards would sit side by side with no owner.
- **What C costs against B, and how it is paid:** a workspace cannot filter across rigs, so "every servo on every rig" is a report, not
  a filter: the cross-rig report in `Sim2Real` takes one runset per rig, each filtered `type = integrated_servo`, and charts the
  same-named gates side by side. Every run carries `type`, `level`, `deployment` and `joint`, so any new cross-rig report is one filter.
- **Decision record:** `docs/decision-wandb-one-project-2026-11-11.md`, amended: B is superseded as the home by C per rig; B's runs stay
  in `Sim2Real` (nothing is deleted) and `wandb_log` still logs that layout.

- **Reversible either way:** the per-rig projects are `rigs.RIGS[...].project`, the one-project layout is `wandb_log.PROJECT`; both are
  written from the same records, so going back to B is one command and no data moves.
- **Steelman for A:** you split the pick-place ladder into two projects today because "we are optimizing them separately". That split
  is between two products with a contract between them and two scoreboards; sim2real has one scoreboard at every level, and splitting it
  by type would break the roll-up the scoreboard is made of.
- **What would change my mind:** a customer who may see only their own cell (C for customer cells); one type's media (camera frames,
  hyperspectral cubes) swamping the shared workspace even with views (that type's media in its own project, its verdict still here);
  W&B filters slowing down at scale (untested past a few hundred runs).

### What is in W&B now

**The per-rig projects (live, proposal C):**

| Project | Runs (latest evaluation) | Saved view | Report |
|---|---|---|---|
| [Sim2Real · wrist rig](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20wrist%20rig) | 24 twin (6 nodes × 4 twin iterations) + 4 controller versions | [view](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20wrist%20rig?nw=wb14q47ug7h) | [report](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20wrist%20rig/reports/Sim2Real-%C2%B7-wrist-rig-%C2%B7-versions-and-gates--VmlldzoxODI5MzczNg==) |
| [Sim2Real · five-bar rig](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20five-bar%20rig) | 20 twin (5 nodes × 4 twin iterations) + 6 controller versions | [view](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20five-bar%20rig?nw=62bp8rsp6h2) | [report](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20five-bar%20rig/reports/Sim2Real-%C2%B7-five-bar-rig-%C2%B7-versions-and-gates--VmlldzoxODI5MzczOA==) |
| [Sim2Real](https://wandb.ai/zach-yamaoka-independent/Sim2Real) (cross-rig) | the one-project runs below | — | [servo joints and the same-named gates across rigs](https://wandb.ai/zach-yamaoka-independent/Sim2Real/reports/Sim2Real-%C2%B7-servo-joints-across-rigs--VmlldzoxODI5Mzc0MA==) |

Each project also holds the rig's Weave evaluations and leaderboards (bam_ws `bam_trackio.bbo`: a version is a Weave model version scored on a fixed environment; one leaderboard per environment: twin versions on the held-out runs, controller versions on the coverage set, and on the five-bar the tool at the 16 settled holds): [UR wrist leaderboards](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20wrist%20rig/weave/leaderboards), [five-bar leaderboards](https://wandb.ai/zach-yamaoka-independent/Sim2Real%20%C2%B7%20five-bar%20rig/weave/leaderboards).

Log both rigs (idempotent; new numbers supersede, nothing is deleted), rebuild the reports and views, read it all back:

```bash
env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra tracking python -m sim2real.tracking.rigs --log --views --verify
```

The read-back through W&B's API (`rigs --verify`), as run for this page:

```text
Sim2Real · wrist rig: 4 twin-version runs -> 0 twin of record 11-10: heldout_sim_vs_real_deg 0.456; 1 it2 Karnopp refit: heldout_sim_vs_real_deg 0.421; 2 it3 refit: heldout_sim_vs_real_deg 0.859; 3 it5 + gravity refit: heldout_sim_vs_real_deg 0.118
  4 controller-version runs -> 1 · gains: stock: tracking_rms_deg 10.184; 2 · gains: ram: tracking_rms_deg 0.446; 3 · gains: pick_sliding: tracking_rms_deg 0.340; 4 · gains: pick_sliding · settled stops (multi3): tool_error_at_stop_mm 1.048
  filter type=integrated_servo: ['CAN 14 wrist joint (revolute 11, moteus servo)', 'CAN 15 wrist joint (moteus servo)', 'CAN 16 wrist joint (moteus servo)']
  gate lines on every deployment run: [9] of 9
Sim2Real · five-bar rig: 4 twin-version runs -> 0 study twin (nominal): heldout_sim_vs_real_deg 0.892; 1 + mass-ID gravity: heldout_sim_vs_real_deg 0.632; 2 + dynamics refit: heldout_sim_vs_real_deg 0.626; 3 refit on the tick clock: heldout_sim_vs_real_deg 0.559
  6 controller-version runs -> 1 · gravity comp: nominal: tool_error_at_stop_mm 9.559; 2 · Coulomb feed-forward: none (stock): tracking_rms_tool_mm 9.380, tracking_rms_deg 1.701; 3 · Coulomb feed-forward: 0.70 / 0.78 N·m (winners): tracking_rms_tool_mm 6.058, tracking_rms_deg 1.096; 4 · winners + lumped comp: tracking_rms_tool_mm 5.648, tracking_rms_deg 0.785; 5 · gravity comp: identified: tool_error_at_stop_mm 4.343; 6 · gravity comp: identified + settle integrator (RAM only): tool_error_at_stop_mm 2.410
  filter type=integrated_servo: ['C1 crank (CAN 13, moteus)', 'J2 shoulder (CAN 12, moteus)']
  gate lines on every deployment run: [9] of 9
  gate keys on both rigs: ['heldout_sim_vs_real_deg', 'heldout_sim_vs_real_pass', 'objective', 'objective_is', 'target_vs_real_at_stop_mm', 'target_vs_real_at_stop_pass', 'target_vs_sim_at_stop_mm', 'target_vs_sim_at_stop_pass', 'target_vs_sim_tracking_deg', 'tool_error_at_stop_mm', 'tool_error_at_stop_p95_mm', 'tool_error_at_stop_pass', 'tracking_rms_deg']
  reports: ['fivebar', 'servo-across-rigs', 'ur_wrist']; saved views: ['fivebar', 'ur_wrist']
VERIFY: PASS
```

**The one-project layout (proposal B), kept in `Sim2Real`:**

- **Project:** [zach-yamaoka-independent/Sim2Real](https://wandb.ai/zach-yamaoka-independent/Sim2Real) (wandb.ai redirects to forge.coreweave.com/wandb/).
- **Runs:** 44 = 24 (ur-wrist-2026-11-10: 6 nodes × 4 twin iterations) + 20 (fivebar-2026-11-11: 5 nodes × 4 twin iterations); one group per evaluation: `ur-wrist-2026-11-10 · 85772c7053`, `fivebar-2026-11-11 · 302ea19eb5`. Runs of earlier evaluations stay in the project as `superseded` (never deleted) and every view filters them out; logging refuses a src/ with uncommitted changes, so each evaluation is a commit.
- **Config on every run** (filter and group on any): `type`, `type_group`, `level`, `deployment`, `deployment_kind`, `rig`, `node`, `instance`, `can_id`, `twin_iteration`, `iteration`, `stage_role` (before / between / after), `model_rung`, `floor_kind`, `gains`, `split`, `evaluation`, `evaluation_state` (latest / superseded), `sim2real_sha`, `result_id`.
- **Summary on each node's last iteration:** `verdict`, `stops_at`, `questions_passed` (0–5), `next_rung`, `rungs`; per question `<Q>/own`, `<Q>/pass`, `<Q>/numbers`, `<Q>/gate`; the numbers `Floor/floor_deg`, `Floor/pairs`, `Data/coverage_pct` (or `Data/cube_pct`, `Data/workspace_pct`, `Data/facing_pct`), `Twin/ratio`, `Twin/sim_real_after_deg`, `Twin/sim_real_before_deg`, `Job/settled_median_deg`, `Job/share_deg`, `Job/tool_settled_mm`; the held-out trend as history (`trend/heldout_median_deg` per `iteration`); W&B Tables `questions`, `curriculum`, `floors`, `models`, `parameters`, and on the deployment's run `tree`, `questions_all`, `curriculum_all`, `trend_all`.
- **Saved views** (the workspace's view menu) and **reports**, one per type and per deployment, plus an overview:

| Slice | Saved view | Report |
|---|---|---|
| deployment = fivebar | [view](https://wandb.ai/zach-yamaoka-independent/Sim2Real?nw=syjerxnd294) | [report](https://wandb.ai/zach-yamaoka-independent/Sim2Real/reports/Sim2Real-·-Deployment-·-Five-bar-on-the-One-Dof-Test-Rack--VmlldzoxODI5MzMyMA==) |
| deployment = ur-wrist | [view](https://wandb.ai/zach-yamaoka-independent/Sim2Real?nw=ony77qilvxw) | [report](https://wandb.ai/zach-yamaoka-independent/Sim2Real/reports/Sim2Real-·-Deployment-·-UR-wrist-on-the-One-Dof-Test-Rack--VmlldzoxODI5MzMxOA==) |
| type = deployment | [view](https://wandb.ai/zach-yamaoka-independent/Sim2Real?nw=vhmhrycy7rk) | [report](https://wandb.ai/zach-yamaoka-independent/Sim2Real/reports/Sim2Real-·-Type-·-deployment--VmlldzoxODI5MzMwOA==) |
| type = integrated_servo | [view](https://wandb.ai/zach-yamaoka-independent/Sim2Real?nw=w6vmu4mj1j2) | [report](https://wandb.ai/zach-yamaoka-independent/Sim2Real/reports/Sim2Real-·-Type-·-integrated_servo--VmlldzoxODI5MzMxMQ==) |
| type = rigid_body_chain | [view](https://wandb.ai/zach-yamaoka-independent/Sim2Real?nw=uddw02334fp) | [report](https://wandb.ai/zach-yamaoka-independent/Sim2Real/reports/Sim2Real-·-Type-·-rigid_body_chain--VmlldzoxODI5MzMxMw==) |
| type = tool | [view](https://wandb.ai/zach-yamaoka-independent/Sim2Real?nw=xiz8q20d78w) | [report](https://wandb.ai/zach-yamaoka-independent/Sim2Real/reports/Sim2Real-·-Type-·-tool--VmlldzoxODI5MzMxNQ==) |
| everything | [project workspace](https://wandb.ai/zach-yamaoka-independent/Sim2Real) | [overview](https://wandb.ai/zach-yamaoka-independent/Sim2Real/reports/Sim2Real-·-Overview--VmlldzoxODI5MzMyMQ==) |

Log a new evaluation (idempotent: the same numbers update the same runs; new numbers supersede them, nothing is deleted), rebuild the views and read it all back:

```bash
env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra tracking python -m sim2real.tracking.wandb_log --backfill --views --verify
```

The read-back through W&B's API (`--verify`), as run for this page:

```text
ur-wrist-2026-11-10: 24 latest runs (want 24 = 6 nodes x 4 twin iterations)
  filter deployment=ur-wrist: 6 runs -> ['CAN 14 wrist joint (revolute 11, moteus servo)', 'CAN 15 wrist joint (moteus servo)', 'CAN 16 wrist joint (moteus servo)', 'UR wrist (CAN 14 + 15 + 16)', 'UR wrist on the One Dof Test Rack', 'holder board #4-7 (tool)']
fivebar-2026-11-11: 20 latest runs (want 20 = 5 nodes x 4 twin iterations)
  filter deployment=fivebar: 5 runs -> ['C1 crank (CAN 13, moteus)', 'Five-bar on the One Dof Test Rack', 'J2 shoulder (CAN 12, moteus)', 'five-bar arm (J2 + C1 driven, J3 / C2 passive)', 'tool point (L2 tip)']
  filter type=deployment: 2 runs -> ['Five-bar on the One Dof Test Rack', 'UR wrist on the One Dof Test Rack']
  filter type=integrated_servo: 5 runs -> ['C1 crank (CAN 13, moteus)', 'CAN 14 wrist joint (revolute 11, moteus servo)', 'CAN 15 wrist joint (moteus servo)', 'CAN 16 wrist joint (moteus servo)', 'J2 shoulder (CAN 12, moteus)']
  filter type=rigid_body_chain: 2 runs -> ['UR wrist (CAN 14 + 15 + 16)', 'five-bar arm (J2 + C1 driven, J3 / C2 passive)']
  filter type=tool: 2 runs -> ['holder board #4-7 (tool)', 'tool point (L2 tip)']
  reports in the project: ['Sim2Real · Deployment · Five-bar on the One Dof Test Rack', 'Sim2Real · Deployment · UR wrist on the One Dof Test Rack', 'Sim2Real · Overview', 'Sim2Real · Type · deployment', 'Sim2Real · Type · integrated_servo', 'Sim2Real · Type · rigid_body_chain', 'Sim2Real · Type · tool', 'Sim2Real · servo joints across rigs']
  registry: 7 reports, 6 saved views
VERIFY: PASS
```

Not done: the reports and views were read back through the API (blocks, panels, filters), not looked at in a signed-in browser; no
run was deleted.

## Sources

- **Decision:** vault `Projects/robot_msgs/Sim2Real KPIs and Gates — 3 Proposals and What Good Looks Like per Type (2026-11-11).md`
  (proposal C, the per-type tables).
- **Code (sim2real):** `src/sim2real/result.py` (`QUESTIONS`, `FLOOR_CHECK`, `RULER_TWINNED` 1.5, `RULER_CLOSE` 3.0, `TOOL_GATE_MM` 1.0,
  `verdicts()`), `src/sim2real/rack_results.py` (both rigs' trees, the passive N/A reasons, the joint shares), `src/sim2real/metrics/series.py`
  (`repeat_floor`, `SAME_INPUT_TOLERANCE_RAD` 0.01°, `FLOOR_MIN_REPEATS` 5), `src/sim2real/cards/servo_gates.py` (T1–T11,
  `MINIMUM_COVERAGE_PCT` 40, `TYPE_GATES`, `UNIT_GATES`), `src/sim2real/cards/schema.py` (`TWINNED_LIMIT`, `DRIFT_THRESHOLD` 1.25),
  `src/sim2real/cards/ladders.py` (`LEARNED_PCT` 95, `LEARNED_SAMPLES` 200, `DEPLOYED_PCT` 99), `src/sim2real/cards/domain_v3.json` (11
  types, their gates and coverage), `src/sim2real/cards/calibration.py` (the routines), `sysid/acceptance.json`, `sysid/noise_ladder.json`.
- **Data (read-only):** `/archive/datasets/bam_rig/rack_2026-11-10/ur_wrist/` (`repeat_floor/floor_scores.json`, `twin_scores.json`,
  `coverage/summary_real.json`, `coverage/multi3/multi_scores.json`, `coverage/refit_rig/it5/refit.json`),
  `/archive/datasets/bam_rig/rack_2026-11-10/fivebar_real/` (the ladders, the refits, `refit_repeats_025953/after_twin.json`),
  `src/sim2real/data/fivebar_dwell_2026-11-11.json`, `ur_wrist_one_click_2026-11-11.json`, `tool_levers_2026-11-11.json`.
- **This page's code:** `src/sim2real/tracking/curriculum.py`, `src/sim2real/tracking/wandb_log.py`, `docs/build_kpis_gates_curriculum.py`,
  `tests/test_tracking.py`.
