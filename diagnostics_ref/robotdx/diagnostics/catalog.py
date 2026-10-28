"""The catalog: which stock diagnostics each robot part type gets, as data.

A part type's diagnostics are (stock primitive, config) pairs, never new code: Zach, 2026-10-28, "for most diaginstics you
don't really need to right any standard code beacuse they are so stock". ``PRIMITIVES`` are the functions (the ones
``implemented`` are in ``stock/``; the rest are specified here and land the same way). ``ENTRIES`` are the per-part
instances with their default config, gate, KPI role, data-ui hint and consumer.

Provenance is explicit on every entry (``prov``):
- ``his``: Zach said it; ``quote`` is verbatim (his spelling) and ``where`` is the vault file and line.
- ``his code``: the number sits in his old bam_diagnostics code; who chose it is not recorded.
- ``agent``: an agent built it on his ask; still marked "Zach to confirm" where it lives (bam_rack_twin acceptance.py).
- ``proposed``: this catalog's proposal; ``where`` is the prior art.
"""

from __future__ import annotations

from dataclasses import dataclass

PARTS = {
    "servo": "Servo (integrated: motor, driver, gearbox, encoder as one joint; a rack station)",
    "bldc_driver": "BLDC driver board (moteus c1 / r4.11, ODrive)",
    "gearbox": "Gearbox (planetary, cycloidal, harmonic)",
    "encoder": "Encoder (rotor magnetic encoder; output encoder)",
    "camera_rgb": "Camera, RGB",
    "camera_rgbd": "Camera, RGBD (D405 / D435): everything RGB has, plus depth",
    "camera_hsi": "Camera, hyperspectral",
    "imu": "IMU",
    "ft_sensor": "Force/torque sensor, load cell",
    "gripper": "Gripper / claw",
    "arm": "Robot arm, 2 to 7+ DOF (five-bar included)",
    "arm_gripper": "Arm + gripper (composite): the pick",
    "deployment": "Rack / deployment (composite): the installed machine",
}


@dataclass(frozen=True)
class Primitive:
    name: str
    family: str
    hint: str
    emits: str
    implemented: bool
    computes: str
    inputs: str
    config: str
    prior_art: str


PRIMITIVES = {p.name: p for p in [
    # ---- implemented in stock/ (the reference) ----
    Primitive("stock.tracking_error", "real_vs_target", "kpi_trend", "scalar", True, "statistic(actual - target) per run (rms | p95 | max | final), combined over runs",
              "Trajectory: t, <x>_<unit>, <x>_target_<unit>, mode", "statistic, channel, across_runs, skip_prelude, controlled_only, limits",
              "MATLAB stepinfo / tracking error; traj_integration_tests metrics.py"),
    Primitive("stock.stop_error", "real_vs_target", "distribution", "series", True, "signed error over the last settle window of every dwell; |e| percentile",
              "Trajectory: t, q_rad, q_target_rad, qd_target_rad_s", "dwell_min_s 0.25, settle_window_s 0.05, percentile 90, side, require_side, limits",
              "ISO 9283 pose accuracy (attained vs commanded at rest); bam_rack_twin stop_accuracy.py"),
    Primitive("stock.repeatability_floor", "repeatability", "evidence", "matrix", True, "median pairwise RMS of the signal over N identical repeats",
              "N Trajectories of one tape", "channel, relative_to_target, clock (common | a), dt 0.002, min_repeats 5",
              "ISO 9283 RP (l + 3 S_l); bam_rack_twin floors.py"),
    Primitive("stock.model_error", "sim_vs_real", "kpi_trend", "scalar", True, "RMS(model - real) per run, any number of models (situations)",
              "(real, model) Trajectory pairs on one clock", "channel, clock (rows | a), controlled_only, across_runs",
              "Rhoban BAM (arXiv 2410.08650) replay error; data-ui PEP 0010 difference(a, b)"),
    Primitive("stock.fidelity_ratio", "sim_vs_real", "threshold_band", "series", True, "model error / floor per (model, tape class); judged model on the floor's class",
              "floor + ModelRows (model, run, class, error)", "model, on_floor_class, center, class_limit 2.0, limits <= 1.5",
              "no standard exists (web sweep 2026-10-28); Zach's 'accuracy vs repeatability' ruler"),
    Primitive("stock.known_load_gain", "truthfulness", "evidence", "series", True, "drive gain from load-on minus load-off slow sweeps vs m g L sin(q - q_hang)",
              "loaded + unloaded Trajectories: q_rad, qd_rad_s, tau_nm, mode", "mass_kg, lever_m, hang_angle_rad, max_speed_rad_s, bins, limits +-5 % / +-2 %",
              "ATI F/T FAQ known-mass check (ati-ia.com FT_FAQ.pdf); Dyno note disc on/off"),
    Primitive("stock.kt_consistency", "truthfulness", "kpi_trend", "scalar", True, "reported / true torque = Kv_reference / Kv_board",
              "KtReadings (board Kv, measured Kv)", "limits 0.95..1.05", "maxon motor constants (Kt = 1/Kv); moteus Kt = 8.27/Kv"),
    Primitive("stock.box", "health", "threshold_band", "series", True, "min / max / mean / std of a channel vs four Limits; worst statistic decides",
              "Trajectories (any channel)", "channel, unit, min, max, mean, std (each Limits), headline",
              "Zach's BoxChartTask (bam_diagnostics v2); ROS diagnostic_updater"),
    Primitive("stock.sample_rate", "health", "threshold_band", "series", True, "achieved rate, median / p99 period, gaps > gap_factor periods",
              "Stamps (t or hw_ms)", "expected_hz, tolerance 0.1, gap_factor 3, max_gaps 0, stamps_scale",
              "ROS FrequencyStatus (tolerance 0.1, window 5); NVIDIA greenwave_monitor"),
    Primitive("stock.fault_codes", "health", "level_history", "series", True, "hard faults and watchdog timeouts fail; a limiter on > 2 % of rows warns",
              "Trajectories: mode, fault", "fault_codes (32, 50), limiter_codes (96, 105), limiter_share_warn 0.02",
              "moteus registers.md 0x00f; ODrive error enums; Zach's ErrorDef table"),
    Primitive("stock.coverage", "coverage", "distribution", "matrix", True, "share of the declared envelope's cells with >= min_samples rows",
              "Trajectories (any two columns)", "x, y, x_range, y_range, bins, min_samples 5, limits >= 0.5 / 0.8",
              "practical identifiability (excite what you model); BAM Reach voxel maps"),
    Primitive("stock.rollup", "rollup", "rollup_tree", "series", True, "a composite's own verdict from its members; caused_by names the non-pass ones",
              "member Results", "title, tolerate_fail (the spider rule), not_run_is", "RobotDx summarize + caused_by (record v0.1); AUTOSAR DEM causal faults"),
    Primitive("stock.gate_matrix", "rollup", "gate_matrix", "matrix", True, "subjects x gates; headline = passing cells",
              "(subject, gate, Result) cells", "gates, subjects", "bam_rack_twin type_gate_cells; Vibe Tracks gate matrix"),
    # ---- specified: land in stock/ the same way ----
    Primitive("stock.feedback_share", "sim_vs_real", "kpi_trend", "scalar", False, "RMS(tau - tau_ff) / RMS(tau) over controlled rows: what feedback still supplies",
              "Trajectories: tau_nm, tau_ff_nm", "rows (controlled), pooled | per_run, limits", "bam_rack_twin vt_kpi.feedback_share"),
    Primitive("stock.share", "real_vs_target", "kpi_trend", "scalar", False, "share of true events in a window with a Wilson 95 % interval; explicit better",
              "Events: (t, ok: bool, labels)", "better (higher | lower), min_events, slice_by, limits",
              "Zach's PercentTask (fixed: lower bound possible); Wilson score interval"),
    Primitive("stock.agreement", "truthfulness", "kpi_trend", "scalar", False, "a reported or predicted scalar vs an independent reference: ratio or % error",
              "Pairs (reported, reference, evidence)", "mode (ratio | percent), limits", "OpenHTF within_percent; bam_rack_twin T7 speed, T8 thermocouple"),
    Primitive("stock.step_response", "real_vs_target", "threshold_band", "series", False, "rise, settling (2 %), overshoot, stabilisation time per move",
              "Trajectory moves", "settle_band 0.02, limits per statistic", "ISO 9283 stabilisation time t and overshoot Ov; MATLAB stepinfo"),
    Primitive("stock.pose_accuracy", "real_vs_target", "distribution", "series", False, "ISO 9283 AP (barycentre vs commanded) and RP (l + 3 S_l) per pose",
              "attained poses: pose id, x_mm, y_mm, z_mm (+ quat), commanded", "poses 5, cycles 30, limits", "ISO 9283:1998 (IS 14533:2005 free text)"),
    Primitive("stock.path_accuracy", "real_vs_target", "path_overlay", "series", False, "Cartesian path error per sample (err_mm, err_rot_mrad), ISO 9283 AT/RT",
              "poses + diff_poses rows (frame declared)", "frame, statistic, tolerance_mm", "ISO 9283 AT_P / RT_P; traj_compare position_rms"),
    Primitive("stock.hysteresis_loop", "characteristic", "evidence", "series", False, "torque vs angle loop with the output locked: gap at zero torque, stiffness K1..K3",
              "clamp-test Trajectory: q_rad (motor side), tau_nm", "torque_range, fit_band, ci 0.95, limits (gap CI half <= 2 arcmin)",
              "Harmonic Drive hysteresis loss / torsional stiffness (CSF catalog); Nabtesco lost motion"),
    Primitive("stock.allan_variance", "characteristic", "evidence", "series", False, "overlapping Allan deviation; ARW at tau = 1 s, bias instability (min / 0.664), RRW",
              "Stamps + gyro_rad_s / accel_m_s2 at rest (hours)", "taus (log-spaced), limits per term", "IEEE 952 / 1554; Kalibr IMU noise model; allan_variance_ros"),
    Primitive("stock.reprojection_error", "truthfulness", "distribution", "series", False, "RMS reprojection error overall and per view (px)",
              "calibration views: detected and projected corners", "limits (px)", "OpenCV calibrateCamera RMS / perViewErrors; Kalibr report"),
    Primitive("stock.depth_plane", "truthfulness", "threshold_band", "series", False, "fill rate, plane-fit RMS (% of Z), Z accuracy, temporal noise on a flat target",
              "depth frames + ROI + ground-truth distance", "roi_fraction 0.4, frames 40, limits", "NIST/Intel depth quality metrics; librealsense depth-quality tool"),
    Primitive("stock.spectral_quality", "characteristic", "distribution", "series", False, "SNR per band; smile and keystone (px) on targets",
              "repeated cubes of a uniform target; bar targets", "bands, limits", "HySIS (arXiv 2411.08917); HISUI SNR spec"),
    Primitive("stock.spectral_angle", "truthfulness", "distribution", "series", False, "spectral angle (rad) between measured and reference spectra",
              "reflectance cube + reference library", "materials, max_angle", "Kruse et al. 1993 SAM"),
    Primitive("stock.stamp_delay", "health", "threshold_band", "series", False, "received - source stamp per message; early, late, zero stamps",
              "Stamps (source, received)", "min_acceptable -1 s, max_acceptable 5 s", "ROS TimeStampStatus; greenwave current_delay_from_realtime_ms"),
    Primitive("stock.image_sharpness", "health", "threshold_band", "series", False, "variance of the Laplacian per frame (blur)", "frames (grey)", "roi, limits (site-calibrated)",
              "Pech-Pacheco 2000; pyimagesearch blur detection"),
    Primitive("stock.marker_drift", "truthfulness", "threshold_band", "series", False, "a fixed tag's pixel / pose offset from its calibrated value",
              "tag detections over time + the calibrated pose", "tag_id, limits (px, mm)", "RealSense on-chip health check; io-diagnostics' 28 px camera move"),
    Primitive("stock.event_interval", "health", "kpi_trend", "scalar", False, "mean time between events (failures, interventions) over operating hours",
              "Events + operating-time intervals", "event codes, min_events", "MTBF / MTTF (reliability); medkit fault history"),
    Primitive("stock.staleness", "health", "level_history", "series", False, "age of each gate's newest evidence vs its validity window",
              "Results with stamps", "valid_for per gate (24 h comms, 7 d motion)", "IEC 61508 proof-test interval; OBD readiness; Rollups note P3"),
]}


@dataclass(frozen=True)
class Entry:
    part: str
    id: str
    title: str
    primitive: str
    checks: str
    config: str  # the defaults that make it this part's diagnostic
    output: str  # value + unit
    role: str  # headline | driver | health
    consumers: str  # robotdx | sim2real | both
    prov: str  # his | his code | agent | proposed
    quote: str  # verbatim (his) or the prior art's claim
    where: str  # vault path:line, code path, or URL
    gate: str = ""  # T1..T11 (bam_rack_twin), K1..K6 (servo-ID ladder / pidtuna), or a part gate
    today: str = ""  # what computes it today, if anything
    hint: str = ""  # overrides the primitive's
    view_extra: str = ""
    family: str = ""  # overrides the primitive's

    @property
    def p(self) -> Primitive:
        return PRIMITIVES[self.primitive]

    @property
    def the_hint(self) -> str:
        return self.hint or self.p.hint

    @property
    def the_family(self) -> str:
        return self.family or self.p.family


ORACLE = "Projects/BAM Robotics/DP - Reality as Oracle.md"
OCT28 = "Sources/Daily Notes/Daily Note - Oct 28 2026.md:368"
ACCEPT = "Projects/BAM Robotics/BAM/FRDPARRC/DP Waste/Sorting Machine/MRF-in-a-box/Arm Control/bam_core/Acceptance Tests.md"
KPIS = "Sources/Notes/BAM KPIs.md"
ROBOT_MOVING = "Sources/Apple Notes/How long before I can actually get a robot moving (APPLE NOTE).md"
ACC = "bam_rack_twin/acceptance.py (claude/sim-to-real-motor-models-f1ee43)"
TORQUE_TRUTH = "for a robot arm, we really are evaluating it on like trackecjtory tracking accuracy... but also like turhtfully of the torque readings"

E = Entry
ENTRIES = [
    # ================================================================ servo
    E("servo", "servo.tracking_rms", "tracking error RMS", "stock.tracking_error", "real vs target over a run: the net tracking a tape got",
      "statistic=rms, channel=q_rad, controlled_only", "mrad", "driver", "both", "his",
      "avg error, max error, (in the various angles), error at stop, etc.", f"{ORACLE}:156", today="vt_kpi tracking_rms; ff_study"),
    E("servo", "servo.tracking_peak", "tracking error p95 / max", "stock.tracking_error", "the worst moment, which an RMS hides",
      "statistic=p95 (or max)", "mrad", "health", "both", "his", "avg error, max error, (in the various angles), error at stop, etc.", f"{ORACLE}:156",
      today="bam_deployments real_tracking_p95"),
    E("servo", "servo.stop_error", "stop error p90", "stock.stop_error", "the error left at every stop; encoder side is only partial",
      "percentile=90, limits = the joint's share of the 5 mm tool gate (3.6 / 6.7 / 10 mrad), require_side=output", "mrad", "driver", "both", "his",
      "avg error, max error, (in the various angles), error at stop, etc.", f"{ORACLE}:156", gate="T4 / K2 (limits: agent, 'Zach to confirm')", today="stop_accuracy.py, vt_kpi stop_p90"),
    E("servo", "servo.hold_effort", "hold convergence", "stock.share", "share of holds that end and stay within 1 mrad",
      "event = a hold, ok = |e| <= 1 mrad to its end, limits >= 0.8", "1", "health", "both", "his",
      "Check that with gravtiy compensation, the PID error to make it stay still is minimal!", f"{ACCEPT}:35", gate="pidtuna K4 (0.8: agent)", today="bam_pid_tunning docs/kpis.py K4"),
    E("servo", "servo.floor", "repeatability floor", "stock.repeatability_floor", "the rig against itself: what a perfect twin would still miss",
      "5 repeats of one dataset tape, same start; clock=common, dt=2 ms", "mrad", "driver", "sim2real", "his",
      "Two aspects accuracy and repeatability...", f"{ORACLE}:412", gate="T1 / K0", today="floors.py (exact match, 8 motors)"),
    E("servo", "servo.twin_fidelity", "twin / floor (position)", "stock.fidelity_ratio", "sim vs real on q, held-out tapes, against the floor",
      "model=twin, on_floor_class, limits <= 1.5, class_limit 2.0", "x (ratio)", "headline", "sim2real", "his",
      "Reduce difference between sim and reality", f"{ORACLE}:164", gate="T2 / K1 (1.5 / 2.0: agent)", today="acceptance T2 (exact match, 8 motors)"),
    E("servo", "servo.torque_fidelity", "twin / floor (torque)", "stock.fidelity_ratio", "sim vs real on the reported torque stream",
      "channel=tau_nm, center=median, limits <= 2.0", "x (ratio)", "driver", "sim2real", "his",
      "so primarily joint position, current, torque (derived from current with Kt) and camera.", "Sources/Daily Notes/Daily Note - Oct 8 2026.md:27",
      gate="T3 (2.0: agent)", today="twin_torque.json / acceptance T3 (exact match)"),
    E("servo", "servo.torque_truth_load", "torque truthfulness: known load", "stock.known_load_gain", "reported torque vs a weighed mass on a measured lever",
      "mass_kg, lever_m; load-on and load-off slow sweeps; limits +-5 % unit, +-2 % type", "% gain error", "driver", "sim2real", "his",
      TORQUE_TRUTH, OCT28, gate="T6 / K4", today="not run on any motor (needs a weighed object)"),
    E("servo", "servo.torque_truth_kt", "torque truthfulness: Kt vs calibration", "stock.kt_consistency", "the board's stored Kv against a measure-only calibration",
      "reference = moteus_tool --calibrate --cal-no-update", "reported / true", "health", "both", "his", TORQUE_TRUTH, OCT28,
      today="kt_can14.json: 1.229 (CAN 14 read 1/1.229 of true until 10-23)"),
    E("servo", "servo.feedback_share", "feedback share", "stock.feedback_share", "how much of the torque the feedback loop still supplies; falls as feed-forward improves",
      "pooled over the best feed-forward runs", "1 (ratio)", "driver", "sim2real", "his",
      "Reduce the size of the feedback term (that improves our feedbforward model)", f"{ORACLE}:163", today="vt_kpi feedback_share (median 0.87)"),
    E("servo", "servo.coverage", "coverage q x qd (x qdd)", "stock.coverage", "did the dataset visit the envelope the model is used in",
      "x=q_rad, y=qd_rad_s (and qd x qdd), envelope = the joint's range and speed limit", "share of cells", "driver", "sim2real", "his",
      "for a single servo I want to see datapoints like accross the full velocitys, acceleration position range.", "Sources/Daily Notes/Daily Note - Oct 24 2026.md:601",
      view_extra="2-D occupancy heatmap (PEP 0010 voxels in 2-D)"),
    E("servo", "servo.envelope", "top speed predicted", "stock.agreement", "the twin reproduces the back-EMF speed limit and the caps",
      "predicted vs measured speed_max, limits <= 5 %", "% error", "health", "sim2real", "agent", "T7 envelope: top speed within 5 %", ACC, gate="T7"),
    E("servo", "servo.thermal", "winding temperature predicted", "stock.model_error", "the thermal model on a heating run (and once vs a thermocouple)",
      "channel=temp_c, limits +-5 Cel", "Cel", "health", "sim2real", "agent", "T8 thermal: within +-5 C on a heating run", ACC, gate="T8"),
    E("servo", "servo.warm_cold", "fidelity warm and cold", "stock.fidelity_ratio", "T2 holds at <= 30 C and at steady-state warm",
      "rows sliced by temperature band", "x (ratio)", "driver", "sim2real", "agent", "T9 warm and cold", ACC, gate="T9 / K5"),
    E("servo", "servo.live_reid", "live re-identification", "stock.fidelity_ratio", "a <= 60 s in-service routine restores T2 after warm-up or a week",
      "the same ratio on the live routine's rows", "x (ratio)", "health", "robotdx", "agent", "T10 live re-ID", ACC, gate="T10 / K6"),
    E("servo", "servo.mttf", "servo mean time to failure", "stock.event_interval", "hours of operation between confirmed faults, per unit and per type",
      "events = confirmed faults (RobotDx Fault records)", "h", "health", "robotdx", "his", "Servo mean time till failure", f"{KPIS}:134 (target 20,000 h at :89-91)"),
    # ================================================================ BLDC driver
    E("bldc_driver", "driver.faults", "fault and limiter codes", "stock.fault_codes", "hard faults (32-50) and watchdog (mode 11) fail; a busy limiter warns",
      "moteus code table; limiter_share_warn 0.02", "count", "health", "both", "his code",
      "ErrorDef table (32-48 ERROR, 96-103 WARN) and fault_count CounterTask warn 1 / error 5", "like_keras lk/archive/actuators/moteus_servos/dx/error_info.py, config/default_diagnostics.py:87",
      today="envelope.py limiters (exact match, 75 runs)"),
    E("bldc_driver", "driver.board_temp", "board temperature", "stock.box", "FET/board temperature stays inside its band",
      "channel=temp_c, max warn 60 / error 70 Cel, mean warn 55 / error 65", "Cel", "health", "both", "his code",
      "board_temp BoxChartTask: max warn 60 / error 70, mean_max warn 55 / error 65", "like_keras lk/archive/actuators/moteus_servos/config/default_diagnostics.py:76",
      today="envelope.py temp_max_c (exact match)"),
    E("bldc_driver", "driver.bus_voltage", "bus voltage", "stock.box", "the supply sags or rises out of band",
      "channel=v_bus_v, min/max +-10 % of nominal (24 V or 36 V)", "V", "health", "both", "proposed",
      "bam_rack_twin preflight refuses outside 30-45 V on the 36 V supply", "bam_rack_twin hardware/board.py PREFLIGHT_VOLTAGE_V", today="envelope.py voltage_min_v (exact match)"),
    E("bldc_driver", "driver.loop_rate", "command / telemetry rate", "stock.sample_rate", "the control loop runs at its rate, without gaps",
      "expected_hz per bus, tolerance 0.1, gap_factor 3", "Hz", "health", "both", "his code",
      "loop period mean_max warn 0.020 s / error 0.100 s (v5 demo; the Hz-shaped default is a unit bug)", "like_keras lk/archive/actuators/moteus_servos/component/v5.py:619",
      today="envelope.py row_rate_hz (exact match)"),
    E("bldc_driver", "driver.link_loss", "CAN reply loss", "stock.share", "share of commands with no reply; transport errors",
      "better=lower, limits warn 1 % (RobotDx P3 'reply_loss < 1 %'); his transport_errors warn 3 / error 10 per window", "%", "health", "robotdx", "his code",
      "transport_error_count CounterTask warn 3 / error 10", "like_keras lk/archive/actuators/moteus_servos/component/v5.py:174"),
    E("bldc_driver", "driver.saturation", "share of rows on the torque cap", "stock.fault_codes", "a run that rides the cap is cap-limited, not tracked",
      "limiter 102 share warn 0.02", "%", "health", "sim2real", "agent", "SATURATION_GATE = 0.02", "bam_rack_twin envelope.py:49"),
    E("bldc_driver", "driver.config", "config matches expected", "stock.agreement", "Kv, ratio, limits and gains equal the deployment's record",
      "per key: expected vs stored", "mismatches", "health", "robotdx", "proposed",
      "RobotDx already reports RatioMismatch; a config change invalidates T1-T2 (T11)", "io-diagnostics expected.py _ratio_checks; acceptance T11"),
    E("bldc_driver", "driver.ripple", "torque ripple (cogging)", "stock.box", "(tau_max - tau_min) / tau_avg on constant-speed plateaus, keyed to rotor angle",
      "plateaus >= 1 rotor turn; limits warn 5 %", "%", "health", "sim2real", "proposed",
      "cogging < 3 % of continuous torque is low, > 5 % high", "drivesandcontrols.ca torque ripple (snippet); servo-ID note A6"),
    # ================================================================ gearbox
    E("gearbox", "gearbox.backlash", "backlash (gap)", "stock.hysteresis_loop", "the gap at zero torque, with the output locked",
      "clamp test, torque ramped both ways; limits CI half-width <= 2 arcmin", "arcmin", "driver", "sim2real", "his",
      "Backlash in servo", "Sources/Notion Import/Notebook (Jul 2025)/April 3 2024 - Positional Innacruaries.md:9", gate="T5 / K3",
      today="model cards backlash (CAN 14 12.2' +-3.9')", view_extra="torque-angle hysteresis loop (xy): the gap and the slopes are the finding"),
    E("gearbox", "gearbox.stiffness", "torsional stiffness", "stock.hysteresis_loop", "slopes K1..K3 of the locked-output torque-angle curve",
      "same clamp run", "N.m/rad", "driver", "sim2real", "proposed", "torsional stiffness approximated by 3 slopes", "Harmonic Drive CSF catalog (harmonicdrive.net csf-csg.pdf)", gate="T5"),
    E("gearbox", "gearbox.ratio", "gear ratio exact", "stock.agreement", "one slow full output turn on camera vs the encoder's count",
      "camera output angle vs q / ratio over 2 pi", "% error", "driver", "sim2real", "his", "Measure output encoder",
      "Sources/Notion Import/Notebook (Jul 2025)/Dealing with Back Lash.md:6", gate="T5", today="ratio_checks.json"),
    E("gearbox", "gearbox.transmission_error", "transmission error", "stock.tracking_error", "output angle minus input angle / ratio over one output turn",
      "target = q_rad / ratio, actual = output encoder or camera", "arcmin", "driver", "sim2real", "proposed",
      "positioning accuracy: max + minus max - deviation over one output turn", "Harmonic Drive CSF catalog"),
    E("gearbox", "gearbox.wear", "backlash and friction drift", "stock.agreement", "the live re-ID's backlash and Coulomb against the commissioning card",
      "flag a 20 % friction change in one pass (K6)", "% change", "health", "robotdx", "his",
      "always be measure and characterisic the performance of the deployment righ tin terms of trajectory tracking etc... models drift and change over time", f"{ORACLE}:289", gate="K6"),
    E("gearbox", "gearbox.flank_changes", "flank changes per move", "stock.share", "how often gravity flips which tooth flank carries the load",
      "count sign changes of the gravity torque per trajectory", "count", "health", "sim2real", "his",
      "Run a trial to find the ideal position to mount the UR like robot above the conveyor belt, that minizes the number of flank changes...",
      "Sources/Daily Notes/Daily Note - Oct 15 2026.md:721"),
    # ================================================================ encoder
    E("encoder", "encoder.output_agreement", "motor encoder vs output truth", "stock.tracking_error", "the joint angle the board reports vs an independent output sensor",
      "target = camera / output-encoder angle, actual = q_rad", "mrad", "driver", "sim2real", "his",
      "I think you likely need two encoders no? to measure output accurate and eliminate backlash no?", "Sources/Notion Import/Notebook (Jul 2025)/Dec 2 -  Planetary Gear Box.md:24",
      family="truthfulness"),
    E("encoder", "encoder.homing", "homing repeatability", "stock.repeatability_floor", "the zero found by N homings, spread",
      "repeats of the homing routine; channel = found offset", "mrad", "health", "both", "his",
      "Verify accuracy and calibration and homing. Do it with diagnostics so can be done continually!!", f"{ROBOT_MOVING}:76"),
    E("encoder", "encoder.standstill_noise", "standstill noise", "stock.box", "RMS of q at rest (std over a still window)",
      "channel=q_rad, std limits from the datasheet (AS5047D 0.068 deg RMS)", "mrad", "health", "both", "proposed",
      "RMS output noise 0.068 deg (1 sigma)", "AS5047D datasheet (sparkfun AS5047D_datasheet.pdf)"),
    E("encoder", "encoder.validity", "validity and field flags", "stock.fault_codes", "encoder-validity bits, magnet too weak / strong, CORDIC overflow",
      "code table per encoder (moteus 0x058, AS5047 DIAAGC, ODrive EncoderFieldStatus)", "count", "health", "robotdx", "proposed",
      "MAGL / MAGH / COF flags; ODrive field 20-120 mT", "AS5047D datasheet; ODrive docs fibre_types"),
    # ================================================================ camera RGB
    E("camera_rgb", "camera.frame_rate", "frame rate and drops", "stock.sample_rate", "frames arrive at the configured fps without gaps",
      "stamps = hardware clock; expected = configured fps; gap_factor 3", "Hz", "health", "both", "proposed",
      "FrequencyStatus: OK within f (1 +- 0.1)", "ROS diagnostic_updater update_functions.hpp; greenwave_monitor", today="run in this reference on the rack's D405 recordings"),
    E("camera_rgb", "camera.latency", "timestamp delay", "stock.stamp_delay", "frames are not late or from the future",
      "min -1 s, max 5 s (ROS); tighter per pipeline", "ms", "health", "robotdx", "proposed", "TimeStampStatus min_acceptable -1 s, max_acceptable 5 s",
      "ROS diagnostic_updater update_functions.hpp"),
    E("camera_rgb", "camera.intrinsics", "calibration residual", "stock.reprojection_error", "intrinsics reproduce the target's corners",
      "RMS px overall and per view; limits proposed 0.5 px warn", "px", "health", "sim2real", "his",
      "You can also test camera intrinsic like this actually!!! And extrinsic which is cool", f"{ROBOT_MOVING}:92"),
    E("camera_rgb", "camera.extrinsic_drift", "extrinsic drift", "stock.marker_drift", "a fixed tag stays where calibration put it",
      "tag_id on the rack frame; limits px and mm", "px", "health", "robotdx", "his",
      "Verify that camera calibration matches real world….", f"{ROBOT_MOVING}:78", today="io-diagnostics saw D405 6036 move 28 px (Oct 21)"),
    E("camera_rgb", "camera.blur", "blur during motion", "stock.image_sharpness", "frames stay sharp enough to detect tags while the arm moves",
      "variance of the Laplacian; limits calibrated on labelled frames", "1", "health", "both", "his",
      "Ok whenver arm is moving. it cannot detect the aruco marker, likey due to motion blur!!",
      "Sources/Notion Import/Notebook & Private Up to Import/One Dof Robot Studies.md:22"),
    E("camera_rgb", "camera.tag_detect", "tag detection rate", "stock.share", "share of frames where the tag is found (by speed band)",
      "slice_by joint speed", "1", "driver", "both", "his",
      "Ok whenver arm is moving. it cannot detect the aruco marker, likey due to motion blur!!", "Sources/Notion Import/Notebook & Private Up to Import/One Dof Robot Studies.md:22"),
    E("camera_rgb", "camera.sim_overlay", "sim vs real image", "stock.fidelity_ratio", "the twin's rendered camera matches the real one (tag pose, overlay)",
      "model = rendered tag pose; floor = repeat-capture spread", "x (ratio)", "driver", "sim2real", "his",
      "Ifs its accurate the camera overlay in sim and reality should match!", "Sources/Daily Notes/Daily Note - Oct 21 2026.md:290"),
    # ================================================================ RGBD
    E("camera_rgbd", "depth.z_accuracy", "Z accuracy", "stock.depth_plane", "depth on a flat target at a known distance",
      "limits < 1 % good, > 2 % poor of Z", "% of Z", "driver", "sim2real", "his",
      "What is the accuracy of our depth perception? on the order of mms usually..", "Sources/Daily Notes/Daily Note - Oct 15 2026.md:778"),
    E("camera_rgbd", "depth.plane_rms", "plane-fit RMS", "stock.depth_plane", "spatial noise about a fitted plane",
      "ROI centre 40 %; limits < 0.4 % good, > 1 % poor", "% of Z", "health", "both", "proposed", "RMS error, plane fit: <0.4 % good, >1 % poor",
      "NIST depth camera image quality slides (nist.gov)"),
    E("camera_rgbd", "depth.fill_rate", "fill rate", "stock.depth_plane", "share of ROI pixels with valid depth", "limits > 99 % good, < 98 % poor", "%", "health", "both",
      "proposed", "fill rate > 99 % good", "NIST depth camera image quality slides"),
    E("camera_rgbd", "depth.temporal_noise", "temporal noise", "stock.depth_plane", "per-pixel std over 40 frames", "limits < 0.2 % good, > 0.5 % poor", "% of Z", "health", "both",
      "proposed", "temporal noise < 0.2 % good", "NIST slides; librealsense depth-quality tool"),
    E("camera_rgbd", "depth.health_check", "on-chip calibration health", "stock.agreement", "RealSense self-calibration score",
      "<= 0.25 ok, 0.25-0.75 recalibrate soon, >= 0.75 recalibrate", "score", "health", "robotdx", "proposed", "health-check score thresholds",
      "RealSense BKM for D400 over lifetime rev 1.31"),
    E("camera_rgbd", "depth.cloud_vs_sim", "point cloud vs sim", "stock.fidelity_ratio", "the measured cloud matches the twin's", "model = rendered depth", "x (ratio)",
      "driver", "sim2real", "his", "Verify that the point clouds match the reality….", f"{ROBOT_MOVING}:86"),
    # ================================================================ hyperspectral
    E("camera_hsi", "hsi.snr", "SNR per band", "stock.spectral_quality", "signal / noise per band on a uniform target", "limits proposed > 200 (HISUI spec)",
      "ratio", "health", "both", "proposed", "SNR > 200 per band (spec, unverified)", "HISUI (imm.dtu.dk dace96a4.pdf, snippet)"),
    E("camera_hsi", "hsi.references", "dark / white reference age", "stock.staleness", "reflectance needs fresh dark and white frames", "valid_for per lighting change",
      "h", "health", "robotdx", "proposed", "reflectance = (raw - dark) / (white - dark)", "plantcv calibrate docs"),
    E("camera_hsi", "hsi.spectral_angle", "spectral angle vs library", "stock.spectral_angle", "known materials read as themselves", "reference spectra per material",
      "rad", "driver", "both", "proposed", "alpha = arccos(t.r / |t||r|)", "Kruse et al. 1993 (NV5 SpectralAngleMapper docs)"),
    E("camera_hsi", "hsi.smile_keystone", "smile and keystone", "stock.spectral_quality", "band-to-band geometry", "limits < 1 px", "px", "health", "sim2real", "proposed",
      "smile and keystone < 1 px (HISUI, unverified)", "HySIS arXiv 2411.08917"),
    E("camera_hsi", "hsi.frame_rate", "line / frame rate", "stock.sample_rate", "the cube arrives at its rate", "expected per scan speed", "Hz", "health", "robotdx", "proposed",
      "FrequencyStatus", "ROS diagnostic_updater"),
    # ================================================================ IMU
    E("imu", "imu.allan", "Allan noise terms", "stock.allan_variance", "ARW, bias instability and RRW vs the datasheet", "hours at rest; limits from the datasheet",
      "deg/sqrt(h), deg/h", "driver", "sim2real", "proposed", "bias instability = Allan minimum / 0.664", "Kalibr IMU-Noise-Model wiki; IEEE 952",
      view_extra="log-log Allan deviation curve with slope guides (-1/2, 0, +1/2)"),
    E("imu", "imu.static_bias", "static bias", "stock.box", "gyro and accel offsets at rest, and their drift with temperature", "mean and std limits", "deg/s", "health",
      "both", "proposed", "bias at rest", "Kalibr IMU noise model"),
    E("imu", "imu.gravity", "gravity norm at rest", "stock.agreement", "|a| at rest equals g: the cheapest truthfulness check", "reference 9.80665 m/s2, limits +-1 %",
      "%", "health", "robotdx", "proposed", "a known reference: gravity", "IEEE 1293 accelerometer test practice (snippet)"),
    E("imu", "imu.rate", "sample rate", "stock.sample_rate", "samples at the configured rate", "expected_hz", "Hz", "health", "robotdx", "proposed", "FrequencyStatus", "ROS diagnostic_updater"),
    # ================================================================ F/T
    E("ft_sensor", "ft.known_mass", "known-mass check", "stock.known_load_gain", "a mass >= 20 % of full scale reads as itself", "after 30-45 min warm-up and bias",
      "% error", "driver", "both", "proposed", "compare the reading to the load, within uncertainty", "ATI FT_FAQ.pdf"),
    E("ft_sensor", "ft.zero_drift", "zero drift", "stock.box", "the unloaded reading after bias, over time", "mean limits in N", "N", "health", "robotdx", "proposed",
      "drift with temperature: warm up and bias before each task", "ATI FT_FAQ.pdf"),
    E("ft_sensor", "ft.noise", "noise at rest", "stock.box", "std of each axis unloaded", "std limits per axis", "N", "health", "both", "proposed", "noise causes: vibration, EMI", "ATI FT_FAQ.pdf"),
    E("ft_sensor", "ft.saturation", "saturation flag", "stock.fault_codes", "any axis out of range invalidates the rows", "status Error bit", "count", "health", "robotdx", "proposed",
      "digital status Error bit on saturation", "ATI FT_FAQ.pdf"),
    # ================================================================ gripper
    E("gripper", "gripper.cycle", "open / close / follow", "stock.tracking_error", "the gripper opens, closes and follows its width trajectory",
      "channel=width_mm vs width_target_mm; final width; cycle time", "mm", "health", "both", "his",
      "Test gripper, open, closes, follows trajectory, detects if object is inside.", f"{ACCEPT}:30"),
    E("gripper", "gripper.detect", "object-inside truthfulness", "stock.share", "the 'object inside' signal agrees with ground truth", "ok = detect == truth",
      "1", "health", "both", "his", "Test gripper, open, closes, follows trajectory, detects if object is inside.", f"{ACCEPT}:30", family="truthfulness"),
    E("gripper", "gripper.grasp_success", "grasp success rate", "stock.share", "share of grasps that hold, sliced by object type and environment",
      "better=higher, Wilson CI, slice_by class / env", "1", "headline", "both", "his", "then a step down we have like grasp success rate",
      "Sources/Daily Notes/Daily Note - Oct 14 2026.md:683"),
    E("gripper", "gripper.compute_time", "grasp computation time", "stock.box", "time to choose a grasp", "channel=compute_s, max limits", "s", "health", "both", "his",
      "and grasp computation time.", "Sources/Daily Notes/Daily Note - Oct 14 2026.md:685"),
    E("gripper", "gripper.force", "grip force tracking", "stock.tracking_error", "measured force vs commanded", "channel=force_n", "N", "driver", "both", "proposed",
      "gripping force (sum of jaw forces)", "Schunk EGI datasheet (snippet)"),
    E("gripper", "gripper.repeat", "repeat accuracy", "stock.repeatability_floor", "final width spread over 100 closes", "100 cycles", "mm", "health", "sim2real",
      "proposed", "repeat accuracy over 100 consecutive closes", "Schunk EGI datasheet (snippet)"),
    # ================================================================ arm
    E("arm", "arm.tool_error_at_stop", "tool error at stop", "stock.stop_error", "the tool's position error at every stop, in mm, the arm gate",
      "Cartesian |p - p_target| at dwells (camera or tracker); limits 5 mm", "mm", "headline", "both", "his",
      "GATE: We prove we have accurate control of the real robot arm to within X distance", "Sources/Daily Notes/Daily Note - Oct 21 2026.md:24",
      gate="arm gate (X = 5 mm: 'within 5mm should be ok for grasping', Aruco Challenges 2024)", today="vt_kpi tool_error_at_stop_mm: catalog only, no arm yet",
      hint="path_overlay"),
    E("arm", "arm.path_tracking", "path tracking error", "stock.path_accuracy", "Cartesian and joint error along the path, coloured on it",
      "frame declared (base, belt); err_mm, err_rot_mrad from difference(real, target)", "mm", "driver", "both", "his", TORQUE_TRUTH, OCT28,
      today="traj_compare position_rms / rotation_rms"),
    E("arm", "arm.pose_ap_rp", "pose accuracy and repeatability (ISO 9283)", "stock.pose_accuracy", "AP and RP at 5 poses in the cube, 30 cycles",
      "poses 5, cycles 30, rated load", "mm", "driver", "sim2real", "his", "Accuracy of Robot Arm", f"{KPIS}:126 (and 'Repeatabiltiy of Robot Arm' at :127)"),
    E("arm", "arm.overshoot", "overshoot and settle", "stock.step_response", "moves end without overshoot, within their time", "settle band = RP", "mm, s", "driver", "both",
      "his", "Verify that motion is accurate, smooth, minium overshoot and within the time limit.", f"{ACCEPT}:21"),
    E("arm", "arm.completion_time", "completion time accuracy", "stock.agreement", "a trajectory finishes when planned", "planned vs actual end", "% error", "health", "both",
      "his", "Time accuracy of trajectory completetion, tracking error, etc.",
      "Projects/BAM Robotics/BAM/FRDPARRC/DP Waste/Sorting Machine/MRF-in-a-box/Arm Control/bam_brain/MDP Agent/Action Client/It should have arm indepdent diagonistics measures.md:4 (FR-038)"),
    E("arm", "arm.sim_vs_real", "arm twin / floor", "stock.fidelity_ratio", "sim vs real per joint and at the tool, against the arm's own repeatability",
      "floor = RP (ISO 9283) or repeats; per joint and Cartesian", "x (ratio)", "headline", "sim2real", "his",
      "Test real vs sim accuracy. the target trajectories should be the same, and then the real trajectories should be similar", f"{ACCEPT}:33"),
    E("arm", "arm.hold_effort", "hold effort under gravity compensation", "stock.feedback_share", "the feedback torque needed to stay still", "rows = holds",
      "N.m", "driver", "both", "his", "Check that with gravtiy compensation, the PID error to make it stay still is minimal!", f"{ACCEPT}:35"),
    E("arm", "arm.workspace_coverage", "workspace coverage", "stock.coverage", "the runs visited the workspace the arm works in", "x_mm, y_mm, z_mm cells in the declared workspace",
      "share of cells", "driver", "sim2real", "his", "At the arm level I want to see things accross the full workspace", "Sources/Daily Notes/Daily Note - Oct 24 2026.md:602",
      view_extra="3-D voxels with 2-D slices (PEP 0010 §5.3 voxels; BAM Reach maps)"),
    E("arm", "arm.calibration_drift", "calibration drift", "stock.marker_drift", "tool pose vs camera / tags, re-measured in service (ISO 9283 drift dAP)",
      "a tag on the tool, periodic", "mm", "health", "robotdx", "his",
      "Very accuracy of eef, calibration and homing, do it with diagonistics so it can be done continually", f"{ACCEPT}:36"),
    E("arm", "arm.closure", "five-bar loop closure", "stock.box", "the closed chain's closure residual stays near zero", "channel=closure_um", "um", "health", "sim2real",
      "agent", "combined stack: 0.46 deg joint / 3.6 mm EE / 1.0 um closure", "traj_integration_tests docs/Logs.md (Jul 29)"),
    E("arm", "arm.joints", "joint rollup", "stock.rollup", "the arm's own verdict from its joints (spider rule)", "tolerate_fail per arm", "joints passing", "health", "robotdx",
      "his", "say a robot with 8 legs, 1 leg says failure, the spider can still report warning",
      "World Model/Chunks & Concepts/C - Diagnostics Record (What We Learned Since ROS DiagnosticStatus).md (Zach in chat, 2026-10-22)"),
    # ================================================================ arm + gripper
    E("arm_gripper", "pick.sppm", "successful picks per minute", "stock.share", "grasp success x picks per minute, across the bench",
      "success share x pick event rate", "picks/min", "headline", "both", "his", "If there was like a single thing I think its succesful picks per minute (across the bench)",
      "Sources/Daily Notes/Daily Note - Oct 14 2026.md:681"),
    E("arm_gripper", "pick.vs_human", "SPPM vs a human", "stock.agreement", "the robot's SPPM over a human's on the same waste stream", "reference = human SPPM",
      "ratio", "headline", "robotdx", "his", "The key metric is successful sorts per minutes, when compared against a human on the same waste stream.",
      "Sources/Apple Notes/Ok here is my new strategy plan of attack (APPLE NOTE).md:42"),
    E("arm_gripper", "pick.rate", "picks per minute", "stock.sample_rate", "pick events per minute (the rate of the pick stream)", "expected 60 PPM (BAM KPIs)",
      "picks/min", "driver", "both", "his", "PPM", f"{KPIS}:68 (target 60)"),
    E("arm_gripper", "pick.mtti", "mean time till intervention", "stock.event_interval", "operating time between human interventions", "events = interventions",
      "min", "driver", "robotdx", "his", "Mean time till intervention", "Sources/Apple Notes/Get $1 (APPLE NOTE).md:24"),
    E("arm_gripper", "pick.grasp_pose_error", "tool error at the grasp", "stock.stop_error", "TCP vs the planned grasp pose at closing", "limits 5 mm", "mm", "driver", "both", "his",
      "I think within 5mm should be ok for grasping…", "Sources/Notion Import/Notebook (Jul 2025)/Aruco Challenges.md:21"),
    # ================================================================ deployment / rack
    E("deployment", "rack.gate_matrix", "hard gates passing", "stock.gate_matrix", "motors x gates (T1-T8): the roll-up of every hard gate",
      "gates T1..T8, subjects = stations", "cells passing", "headline", "both", "his",
      "at the hgihest level I just need to see like a roll up and I want to see all of the hard gates passing", "Sources/Daily Notes/Daily Note - Oct 25 2026.md:48",
      today="vt_kpi type_gate_cells (16 of 64)"),
    E("deployment", "rack.rollup", "rack status", "stock.rollup", "the composite's own verdict; caused_by names the station", "tolerate_fail 0 (acceptance rig)", "stations passing",
      "health", "robotdx", "his", "say a robot with 8 legs, 1 leg says failure, the spider can still report warning",
      "World Model/Chunks & Concepts/C - Diagnostics Record (What We Learned Since ROS DiagnosticStatus).md (Zach in chat, 2026-10-22)", today="io-diagnostics summarize"),
    E("deployment", "rack.evidence_age", "evidence freshness", "stock.staleness", "each gate's newest evidence is inside its validity window",
      "valid_for: comms 24 h, motion 7 d; reset on restart, replug, firmware", "h", "health", "robotdx", "proposed",
      "initiated checks expire after valid_for", "Diagnostics Rollups note (2026-10-23) P3"),
    E("deployment", "rack.uptime", "uptime and MTTF", "stock.event_interval", "hours between system faults; uptime chart", "events = confirmed system faults", "h",
      "driver", "robotdx", "his", "I do like these uptime charts", "Sources/Daily Notes/Daily Note - Oct 24 2026.md:222", hint="level_history"),
    E("deployment", "rack.throughput", "throughput", "stock.sample_rate", "material processed per hour with no pile-up", "expected 1 ton/h (BAM KPIs)", "ton/h", "headline",
      "robotdx", "his", "Throughput - no pile up allowed it needs to sort through it all. this is essential.",
      "Maps & Views/Questions/Q - What metrics (kpis) to track for BAM？ and how to track in simulator？.md:97"),
    E("deployment", "rack.host", "the computer", "stock.box", "cpu, memory, disk, temperature, clock of the host", "ROS diagnostic_common_diagnostics defaults (disk free warn 5 %)",
      "%", "health", "robotdx", "his", "the computer should almost like like its own diaognistics monitoring the wires", "Sources/Daily Notes/Daily Note - Oct 22 2026.md:427",
      today="io-diagnostics host leaf"),
    E("deployment", "rack.links", "link health", "stock.share", "USB link speed, re-enumerations, CAN reply loss per adapter", "per edge", "count", "health", "robotdx", "his",
      "the computer should almost like like its own diaognistics monitoring the wires", "Sources/Daily Notes/Daily Note - Oct 22 2026.md:427", today="io-diagnostics link rows"),
]


def by_part() -> dict[str, list[Entry]]:
    out: dict[str, list[Entry]] = {part: [] for part in PARTS}
    for entry in ENTRIES:
        out[entry.part].append(entry)
    return out


def problems() -> list[str]:
    """The catalog checks itself: known primitives, parts, roles, hints and provenance; every 'his' has a quote and a place."""

    from .core import FAMILIES, HINTS, ROLES

    found = []
    ids = [entry.id for entry in ENTRIES]
    found += [f"duplicate id {i}" for i in set(ids) if ids.count(i) > 1]
    for entry in ENTRIES:
        if entry.primitive not in PRIMITIVES:
            found.append(f"{entry.id}: unknown primitive {entry.primitive}")
            continue
        if entry.part not in PARTS:
            found.append(f"{entry.id}: unknown part {entry.part}")
        if entry.role not in ROLES:
            found.append(f"{entry.id}: role {entry.role}")
        if entry.the_hint not in HINTS:
            found.append(f"{entry.id}: hint {entry.the_hint}")
        if entry.the_family not in FAMILIES:
            found.append(f"{entry.id}: family {entry.the_family}")
        if entry.consumers not in ("robotdx", "sim2real", "both"):
            found.append(f"{entry.id}: consumers {entry.consumers}")
        if entry.prov not in ("his", "his code", "agent", "proposed") or not entry.quote or not entry.where:
            found.append(f"{entry.id}: provenance needs prov, quote and where")
    return found
