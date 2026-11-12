# Simulating grippers in MuJoCo: best practice (2026-11-11)

**Rule of thumb:**
- Make the pad contact stiff *for the object's mass*: penetration ≈ (F/m)·(1−d)·τ².
- Give each finger several primitive contacts along its gripping surface:
  - a parallel jaw gets ≥ 2 boxes per pad;
  - a curved finger gets a chain of boxes, capsules or spheres that stays inside the mesh.
- Run with an elliptic friction cone and `impratio` 10, condim 4 on the pads, and pad `priority` set so the pad's parameters win.
- Measure penetration and held slip on every run, so a soft contact shows up as a number, not a dropped object.

Evidence behind it:
- bam_ws `src/dev/bam_pick_worlds/research/grasp_contact_2026_11_11/` (R3 crab claw, an 80-run one-knob sweep, then the 96-episode gate);
- the Menagerie gallery `reports/media/gripper-gallery-2026-11-11.html`, built by `docs/build_report_gripper_gallery.py` + `docs/gripper_gallery_3d.py`: 40 distinct set-ups, each an animated 3D view (open/close through its own actuators) toggling visual vs collision, with settings read from the compiled models;
- the MuJoCo docs and issues cited below.

## 1. Stiffness is per unit mass: size `solref` for the lightest object

MuJoCo contacts are soft constraints. Their stiffness is set in acceleration units scaled by the effective mass, so the resting penetration under a squeeze F is roughly

    r ≈ (F / m_eff) · (1 − d) · timeconst² · dampratio²        (modeling#CSolver)

- **Measured on R3:** a 10 N squeeze on the 0.549 g foam cube at `solref (0.004, 1)` and d = 0.99 predicts 2.9 mm. We measured 2.4–3.4 mm. Sunk that deep, the cube rocked and ratcheted 2–3.5 mm along the jaws, and 0 of 23 cubes held.
- **The fix:** the pad time constant at the MuJoCo floor of 2 × timestep (0.5 ms at a 0.25 ms step). Penetration fell to ≤ 0.27 mm and the gate went from 68/93 to **93/93**, at the same run time. R1's 2F-85 learned the same lesson: its creep was proportional to the pad time constant, and 0.2 ms pads at a 0.1 ms step fixed it.
- **The Menagerie norm of `solref` 0.004–0.01** is stiff enough for 50 g–1 kg objects. It is not stiff enough for gram-scale waste such as foam, film or paper. Check r for the *lightest* object in the corpus. If τ has to drop below 2 × dt, shrink dt.
- **Knobs that did NOT fix a soft contact (R3 sweep):**
  - more friction or torsional friction;
  - condim 6;
  - solimp dmax 0.9999 on its own;
  - direct `solref (−2e6, −400)`, which dropped the block in 5/6 picks.

  The one exception: `noslip_iterations` 10 removes the creep (it re-solves the friction rows with zero softness) but leaves the pads about 2 mm deep. Use it on top of a stiff contact, never instead of one.

## 2. Contact geometry: several primitives per finger, inside the mesh

What the Menagerie gallery shows (40 set-ups, Menagerie `370c439`, MuJoCo 4.0.1):

- **31 of 40 put primitives on the fingers.** The 8 models that collide on meshes only are Spot's arm, TALOS, TIAGo (single and dual), the reBot DevArm, Shadow DEX-EE, Lite6 and UMI.
- **Parallel jaws use boxes as pads.** The 2F-85 has 2 per pad ("for more contacts"); the Panda hand has 5 per fingertip. The xArm7's mesh pads could not hold a cube until they became boxes (menagerie #83). The MuJoCo developers' own advice is to "disable the collisions for the mesh and add a layer of (possibly invisible) box primitives" (mujoco #239).
- **Curved fingers use chains of small primitives:**
  - LEAP hand: 57 boxes;
  - Allegro: 16 boxes + 4 capsule tips;
  - TetherIA Aero: 15 boxes;
  - Google robot: 16 capsules;
  - Shadow hand: capsules and cylinders;
  - RB-Y1: 8 spheres;
  - ALOHA: 12 small sphere pads on the mesh fingers.
- **Why it matters:**
  - General convex colliders (GJK/MPR) return one point per pair unless multiccd is on. multiccd is on by default since 3.8, but a rounded hull still gives 1–3 points that jump around: R3's crab claw touched the cube at 2–6 flickering points on its edges.
  - A box face against a box face gives a stable patch of contacts with steady normals.
- **Keep the primitives inside the collision mesh the planner checks.** Then the physics and the planner can't disagree about clearance; R3 holds its two jaw models within 0.2 mm.
- **For a curved jaw, fit N boxes along the gripping contour, but measure before adopting.** Each box's outer face lies on the contour's chord and is as deep as the mesh allows; the chord error per box is about L²/8R, so it shrinks with N². Measured on R3's crab claw (bam_ws `research/box_pads_2026_11_11/`, `fivebar_jaw_collision = "boxes:N"`, main @ `cbdcd6b58`):
  - **Inscribed boxes can't fill a fingertip that rounds off in two directions.** The fingertip gap is 21.7 / 6.0 / 3.5 / 1.9 / 0.9 mm at N = 1 / 2 / 8 / 16 / 32. Small blocks are pinched by the last few mm, so the tip sets N, not the curvature: only N = 32 held all 12 benchmark picks at 0.5 ms pads.
  - **With soft 4 ms pads, boxes alone fix the slip:** about 24 contacts share the squeeze, against about 3.4 for the mesh hull (5/12 → 12/12).
  - **With stiff 0.5 ms pads, the mesh is already 93/93.** N = 32 cut the cube's worst slip (0.64 → 0.38 mm) but turned every block more in the grasp (median 2.7–4.1° vs 0.6–2.7°), and lost one gate episode (92/93, Wilson 0.942 < 0.95).
  - **So the mesh stays R3's default.** Boxes are opt-in, and earn their keep for objects gripped deep in a concave throat, where the hull stands proud of the real surface by up to 6.8 mm.

## 3. The option set (copy this)

| Setting | Value | Why | Seen in |
|---|---|---|---|
| `cone` | `elliptic` | The friction cone is the real cone; high `impratio` is only safe with it | 24/40 Menagerie set-ups; mujoco #786 |
| `impratio` | 10 (manipulation baseline) | Makes friction harder than normal force, so less slip | 22/40 set-ups at ≥ 10; robosuite 20; LEAP and RB-Y1 100 |
| pad `condim` | 4 | Torsional friction resists spin about the squeeze axis | 12/40; dm_control, Meta-World; docs "4 or 6 on grasp pads" |
| torsional friction | ~0.005 m (patch diameter) | A larger value did not help (R3) | Menagerie default |
| pad `priority` | ≥ 1, above the object | The pad's friction, solref and solimp win, instead of a max or mix with the object's | 9/40; 2F-85, xArm7 |
| pad `solref` | ≤ 4 ms, and sized by r above for the lightest object; floor 2 × dt | Penetration ∝ τ²/m | R3 0.5 ms, R1 0.2 ms |
| `noslip_iterations` | 0 by default; 1–5 only for residual creep | Costs compute, makes inverse dynamics ill-defined, can chatter | Stretch 2–3, UMI 2, DEX-EE 5, dm_control 5 |
| timestep | 0.5–2 ms with `implicitfast`; smaller for gram-scale objects | Sets the solref floor | R3 0.25 ms, R1 0.1 ms |
| margin / gap | 0 | Margin without a matching gap makes objects hover | docs |

## 4. Verify it like a sensor: hidden truth, numbers every run

- **Log per episode:**
  - peak pad penetration;
  - held slip in mm and degrees in the jaw frame;
  - jaw–object contacts per tick.

  bam_pick_worlds already does all three (`peak_pad_penetration_mm`, `max_held_slip_mm`). A gate on slip alone hides a soft contact until the object is light enough to slip.
- **Keep a held-object bar** (R3: slip ≤ 1 mm while held) and a penetration bar of about 10 % of the object's smallest dimension.
- **Probe one knob at a time on the same planned tape.** The trajectory hash is identical across variants, so only the contact model changes (bam_ws `research/grasp_contact_2026_11_11/contact_probe.py`).
- **A pass in simulation is not a pass on the claw.** Bench the real gripper on the worst object (R3: the 14 mm cube held only at the jaws' rounded tips) before trusting either world.

## Sources

- MuJoCo docs:
  - [Modeling: solver parameters, tuning, slow slippage](https://mujoco.readthedocs.io/en/stable/modeling.html#csolver)
  - [Computation: multiccd](https://mujoco.readthedocs.io/en/stable/computation/index.html#comulticcd)
  - [Computation: noslip](https://mujoco.readthedocs.io/en/stable/computation/index.html#sonoslip)
- MuJoCo issues:
  - [#239 box primitives over mesh pads](https://github.com/google-deepmind/mujoco/issues/239)
  - [#698 noslip for gripper drops](https://github.com/google-deepmind/mujoco/issues/698)
  - [#786 impratio with elliptic cones](https://github.com/google-deepmind/mujoco/issues/786)
  - [#3328 creep is working as intended](https://github.com/google-deepmind/mujoco/issues/3328)
- Menagerie: [robotiq_2f85 README](https://github.com/google-deepmind/mujoco_menagerie/tree/main/robotiq_2f85) and [#83, xArm7 mesh pads](https://github.com/google-deepmind/mujoco_menagerie/issues/83). Every other model is in the gallery JSON.
- bam_ws: `src/dev/bam_pick_worlds/research/grasp_contact_2026_11_11/` and the README's R3 findings. The R3 commit that applied the fix is on bam_ws main @ `63dd58ab7`.
- Vault: *MuJoCo Grasp Contact — Why Held Blocks Slip and How to Fix It (2026-11-11)*.
