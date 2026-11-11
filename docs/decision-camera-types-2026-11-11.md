# Decision: the camera types made executable; "configure" is its own routine kind; fidelity divides by a session floor (2026-11-11)

**Status:** accepted (the camera types agent, at Zach's request in chat, 2026-11-11).

## Context

Zach: "associate a lot of this information under the generic types of Hyperspectral Camera, RGBD Camera, RGB Camera ... robot types I
can assign those generic types and then they get all of the stuff for those types kinda like automatically". He asked for:

1. a rung of models per camera, each with its internal parameters;
2. routines that identify those models;
3. "calibration routines ... like homing ... we are not identifying a model so much as automatically configuring it";
4. per type, treated as a black box, the success metrics for how good the model of the camera is.

The cards already held the three camera types as data (parameters, rung names M0..M3, tests, gates). No code stood behind them, except
sysid's linescan_cell and dual_arm_cell examples, and bam_ws's exposure lock (bam_camera_calibration, on bam_ws main 5b0ccf1c).

## Decisions

- **The kits live in `sim2real.models.camera`**: `kit(type_id)` and `kits_for(type_ids)` (members included: an RGBD camera brings its
  colour camera_rgb). The equations and fits are in `fit/camera_{rgb,rgbd,hsi}.py`, the metrics in `metrics/camera.py` and the
  configure procedures in `schedule/camera_configure.py`, each layer importing only the ones to its left. `tests/test_camera_types.py`
  holds every kit to its card: rung keys, parameter names, routine ids and on-card metric ids.
- **"configure" is a routine kind, not an "identify" with no parameters.** A configure routine writes device settings
  (`CalibrationRoutine.configures`). Settings are the inputs a model is evaluated at; they are not model parameters. Mixing the two
  would make "which routines identify fx_fy" answer with exposure locks. Alternative not taken: config-role parameters on the camera
  cards. That would have grown every camera rung and the site's parameter tables with settings the twin never fits.
- **Fidelity = model error ÷ a session floor.** The floor is σ·√(1/n_calibration + 1/n_held-out): how far a second real calibration
  session's estimate would land from the held-out capture's. The first version divided by the held-out capture's standard error alone.
  The hidden-truth tests failed every correct calibration with it as soon as the held-out capture was averaged long enough, because a
  fitted model carries its calibration capture's noise. Real against real at the same sample sizes is the servo's rule (T1) said for a
  statistic.
- **Every fidelity test has a model that must fail it.** The nominal (datasheet) model fails, and so does the rung below where that
  rung's term matters (M0 without distortion, M1 without depth bias). This keeps the ruler able to go red.
- **numpy-only fits**: sim2real's runtime is robot_msgs. Zhang's calibration is held to OpenCV's `calibrateCamera` where OpenCV is
  installed (test skips otherwise).
- **RGB/RGBD exposure lock stays in bam_ws** beside the RealSense driver it writes to; its card routine's CodeHome points there.
  Revisit when a second RGB camera driver needs the same search (move the numpy core down, keep the adapters in bam_ws).

## Undo

`git revert` the code merge; the cards barrier (cce0862) is additive and can stay.
