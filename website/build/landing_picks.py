"""The sim2real landing page's picks: every source, number, label, row, mode, caption and line of prose the landing shows.

website/data/landing.json is generated from this file by export_landing.py (edit here, never the JSON). The numbers themselves are never
typed here: a Value names a file and a key, and the exporter reads the number out of a byte-for-byte snapshot of that file. A cell with
no measured number is a Status ("not measured yet" / "not built yet") with its reason.

WHY one hand-written Python file (Zach's Python-ground-truth rule): the picks, the prose and the logical roots live in one place a human
reads and edits; the JSON the page and the ruler read is generated from it.

Template grammar (shared with pages.render_template and tests/test_landing_page.py's render): {value-id} is a sourced number,
{=CAN 11} a name, {gate:value-id} that number's verdict against the 1 mm tool gate, {cmp:a:b} a computed comparison, `x` code.
Template prose carries no digit: a number in prose is a {value-id}.

Design: the 2026-11-20 landing design v2 (sections 1-4), from Zach's Daily Note 2026-11-20 "# Sim2Real routines".
"""

from __future__ import annotations

from dataclasses import dataclass, field

# WHY a fixed date: snapshots are written once and never rewritten; a re-export on another day still cites these files
SNAPSHOT_DATE = "2026-11-20"
# Logical roots: landing.json carries only these names (it is public); the exporter resolves them on the workstation
ROOTS = {
    "lab": "/archive/datasets/bam_rig",
    "amb": "/home/bam/arm_motion_bench",
    "rackq": "/home/bam/.local/state/rack/submissions",
    "bamws": "/home/bam/bam_ws",
}
# WHY plain words (review 2026-11-20 B5): "lab archive" and "rack submissions" read as process words on a public page
ROOT_WORDS = {"lab": "lab recordings", "amb": "arm_motion_bench", "rackq": "arm job records", "bamws": "bam_ws", "": "sim2real"}


# ---------------------------------------------------------------------------------------------------------------- the shapes


@dataclass(frozen=True)
class Source:
    sid: str
    ref: str                      # "lab:…", "amb:…", "rackq:…", "bamws:…" (outside the repo: snapshotted) or a sim2real-relative path
    what: str
    kind: str                     # real | sim | pseudo-real | code | setting | mixed
    kind_by_key: dict = field(default_factory=dict)   # a mixed file: the key step that says real or sim
    unit_convention: str | None = None                # arm_motion_bench files: "si" (stored in SI) or "display" (stored as shown)
    moving: bool = False          # a live lane still writes this file; the page cites the snapshot
    dated_key: tuple = ()         # the key holding the file's own date; empty = its commit (in the repo) or its mtime (outside)


@dataclass(frozen=True)
class Value:
    vid: str
    source: str
    key: tuple
    unit: str                     # as stored
    display_unit: str             # as shown (the ruler's FORMATS)
    digits: int
    measure: str                  # the ruler's MEASURES
    derive: dict | None = None
    kind: str | None = None       # declared only where the key path cannot say (a mixed file's fidelity numbers)
    kpi: str | None = None        # arm_motion_bench kpi_names.py name: its unit, display unit and scale


@dataclass(frozen=True)
class Label:
    lid: str
    source: str
    key: tuple
    derive: dict | None = None


@dataclass(frozen=True)
class Cell:
    """A measured cell: its numbers, the one its gate chip judges, and the controller it ran (words + the source's own label)."""

    values: tuple
    gate: str | None = None
    words: str = ""
    label: str = ""
    evidence: tuple = ()


@dataclass(frozen=True)
class Status:
    status: str                   # not_measured | not_built | runs
    why: str


@dataclass(frozen=True)
class Row:
    id: str
    where: str                    # real | pseudo-real
    title: str
    link: str
    target: str
    cells: dict                   # sim | on_real | tuned -> Cell | Status
    same: tuple = ()              # value pairs that prove every cell played the same target
    notes: tuple = ()
    media: str | None = None


@dataclass(frozen=True)
class Robot:
    id: str
    title: str
    rows: tuple


@dataclass(frozen=True)
class Recovery:
    id: str
    robot: str
    title: str
    via: str | None
    measure: str
    recorded: str | None          # the source whose own date stamps the record
    routines: str | None          # a label: the routines it ran
    cells: dict                   # recovered | nominal | fitted | floor -> Cell | Status
    notes: tuple = ()


@dataclass(frozen=True)
class Mode:
    n: int
    title: str
    what: str
    call: str | None
    robots: dict                  # pendulum | ur_arm | bam_arm -> Status


@dataclass(frozen=True)
class Media:
    mid: str
    file: str                     # media/<name>, served at /assets/media/<name>
    ref: str                      # the real recording it is cut from (a logical name)
    report: str                   # the report that recording belongs to (a logical name)
    what: str                     # the caption (a template)
    how: str                      # loop | frame | copy
    filter: str = ""              # the ffmpeg filter, as run
    at_s: float | None = None     # a frame's time in the recording
    quality: int = 0              # webp quality / jpeg qscale


# ---------------------------------------------------------------------------------------------------------------- sources

SOURCES = (
    Source("pendulum-r0", "lab:onedof_2026-11-15/scorecards/round0_measured.json", "1-DOF campaign scorecard, round 0 (the board as found)",
           "mixed", kind_by_key={"real": "real", "sim": "sim"}, dated_key=("scored_utc",)),
    Source("pendulum-r9", "lab:onedof_2026-11-15/scorecards/round9.json", "1-DOF campaign scorecard, round 9 (tuned)",
           "mixed", kind_by_key={"real": "real", "sim": "sim"}, dated_key=("scored_utc",)),
    Source("ur5e-v2", "amb:results/summary_v2.json", "arm_motion_bench summary v2: the UR5e in MuJoCo, held-out workspace tasks",
           "pseudo-real", unit_convention="si"),
    Source("amb-kpi-names", "amb:src/arm_motion_bench/kpi_names.py", "arm_motion_bench KPI names: each number's unit, display unit and scale",
           "code"),
    Source("amb-ur5e-baselines", "amb:src/arm_motion_bench/baselines/ur5e_mujoco.py",
           "arm_motion_bench UR5e controllers (CONTROLLER_DESCRIPTIONS)", "code"),
    Source("urwrist-asfound", "lab:rack_2026-11-10/ur_wrist/gates/gate3_baseline_heldout.json",
           "UR wrist gate 3, held-out tape, the controller as found", "real"),
    Source("urwrist-tuned", "lab:rack_2026-11-10/ur_wrist/gates/gate3_kphold_heldout.json",
           "UR wrist gate 3, held-out tape, hold gain retuned", "real"),
    Source("urwrist-asfound-session", "lab:rack_2026-11-10/ur_wrist/coverage/real/multi3_pick/multi3_shuffle_heldout-407e3359_1112/session.json",
           "UR wrist held-out session plan, as found (its feed-forward)", "setting"),
    Source("urwrist-tuned-session", "lab:rack_2026-11-10/ur_wrist/coverage/real/multi3_pick/multi3_shuffle_heldout_kphold_1112/session.json",
           "UR wrist held-out session plan, tuned (its hold gains)", "setting"),
    Source("bamarm-climb", "amb:outputs/bam_fb/real/climb.json", "BAM arm real speed climb: one row per run on the development tape",
           "real", unit_convention="display", moving=True),
    Source("bamarm-twin", "amb:outputs/bam_fb/real/sim_ab/sim_ab_workspace-dev-000_realgains_kphold.json",
           "BAM arm twin runs on the development tape (real gains, stiffer hold)", "sim", unit_convention="display", moving=True),
    Source("bamarm-sweep", "rackq:1117-034942-537b/runs/real_20261117_105019/score_real.json",
           "PID tuna workspace sweep on the BAM arm: every stop scored", "real", dated_key=("utc",)),
    Source("ex-pendulum", "website/examples/pendulum_can11.out.json", "the pendulum example's recorded output (calibrate on a hidden world)",
           "pseudo-real", dated_key=("recorded",)),
    Source("ex-urwrist", "website/examples/ur_wrist_test_rig.out.json", "the UR wrist example's recorded output (calibrate on a hidden world)",
           "pseudo-real", dated_key=("recorded",)),
    Source("sysid-ur5e", "sysid/results/ur5e.json", "the sysid oracle on the UR5e: a hidden tracker, held-out poses", "pseudo-real"),
    Source("drift-wear", "sysid/results/drift_backlash_wear.json", "drift study: backlash wear on the pendulum_can11 hidden world",
           "pseudo-real"),
    Source("drift-camera", "sysid/results/drift_camera_knock.json", "drift study: a camera knocked in the dual_arm_cell hidden world",
           "pseudo-real"),
    Source("tool-gate", "src/sim2real/result.py", "the tool gate at a stop (TOOL_GATE_MM)", "code"),
)


# ---------------------------------------------------------------------------------------------------------------- numbers

DEG = 1  # (readability only)
R9 = ("stations", "can11", "rungs", {"where": {"fraction": 0.4}})   # round 9: the tuned rung at 114.5 deg/s peak
R0 = ("stations", "can11", "rungs", {"where": {"fraction": 0.8}})   # round 0: the as-found rung commanded to the same peak speed


def _ur5e(controller: str) -> tuple:
    return ("groups", f"ur5e/{controller}/workspace-v1/holdout/s1.0")


ASFOUND_RUN = ("runs", "heldout_1112", "summary", "all_poses")
TUNED_RUN = ("runs", "heldout_kphold_1112", "summary", "all_poses")
BAM_BASELINE = ("rungs", {"where": {"fraction": 0.5, "layout": "baseline"}})
# WHY a stated rule, not a hand pick (review 2026-11-20, A7): the newest run at half speed with model feed-forward and no integrator
BAM_TUNED = ("rungs", {"newest": {"where": {"fraction": 0.5}, "startswith": {"layout": "model-FF"}, "excludes": {"layout": ["integrator"]},
                                  "by": "job"}})
COUNT_PASS = {"count": {"field": "pass", "equals": True}}
COUNT_GRADED = {"count": {"field": "pass", "present": True}}
COUNT_UNGRADED = {"count": {"field": "pass", "present": False}}

VALUES = (
    # the gate
    Value("gate.tool_mm", "tool-gate", ("TOOL_GATE_MM",), "mm", "mm", 0, "gate"),
    # the pendulum: round 9 tuned, round 0 as found, matched by commanded peak speed
    Value("pendulum.target.peak_speed", "pendulum-r9", R9 + ("commanded_peak_rad_s",), "rad/s", "°/s", 1, "peak_speed"),
    Value("pendulum.on_real.peak_speed", "pendulum-r0", R0 + ("commanded_peak_rad_s",), "rad/s", "°/s", 1, "peak_speed"),
    Value("pendulum.on_real.amplitude", "pendulum-r0", R0 + ("amplitude_rad",), "rad", "°", 1, "amplitude"),
    Value("pendulum.tuned.amplitude", "pendulum-r9", R9 + ("amplitude_rad",), "rad", "°", 1, "amplitude"),
    Value("pendulum.sim.stop_worst", "pendulum-r9", R9 + ("sim", "stop_tool_max_mm"), "mm", "mm", 3, "stop_worst"),
    Value("pendulum.sim.stops", "pendulum-r9", R9 + ("sim", "stops"), "", "", 0, "stops"),
    Value("pendulum.sim.joint_rms", "pendulum-r9", R9 + ("sim", "tracking_rms_deg"), "deg", "°", 3, "joint_rms"),
    Value("pendulum.on_real.stop_worst", "pendulum-r0", R0 + ("real", "stop_tool_max_mm"), "mm", "mm", 3, "stop_worst"),
    Value("pendulum.on_real.stops", "pendulum-r0", R0 + ("real", "stops"), "", "", 0, "stops"),
    Value("pendulum.on_real.joint_rms", "pendulum-r0", R0 + ("real", "tracking_rms_deg"), "deg", "°", 3, "joint_rms"),
    Value("pendulum.tuned.stop_worst", "pendulum-r9", R9 + ("real", "stop_tool_max_mm"), "mm", "mm", 3, "stop_worst"),
    Value("pendulum.tuned.stops", "pendulum-r9", R9 + ("real", "stops"), "", "", 0, "stops"),
    Value("pendulum.tuned.joint_rms", "pendulum-r9", R9 + ("real", "tracking_rms_deg"), "deg", "°", 3, "joint_rms"),
    Value("pendulum.fidelity.sim_vs_real", "pendulum-r9", R9 + ("sim_vs_real_deg",), "deg", "°", 3, "fidelity_joint", kind="real"),
    Value("pendulum.fidelity.floor", "pendulum-r9", R9 + ("floor_deg",), "deg", "°", 3, "floor", kind="real"),
    # the UR5e in MuJoCo (arm_motion_bench stores SI; kpi_names says how it is shown)
    Value("ur5e.tasks", "ur5e-v2", _ur5e("ctc_tuned") + ("tasks",), "", "", 0, "tasks"),
    Value("ur5e.on_real.tcp_rms", "ur5e-v2", _ur5e("ctc_model_err") + ("median", "tcp_track_rms_mm"), "m", "mm", 3, "tcp_rms",
          kpi="tcp_track_rms_mm"),
    Value("ur5e.on_real.stop_task_worst", "ur5e-v2", _ur5e("ctc_model_err") + ("median", "stop_error_max_mm"), "m", "mm", 3,
          "stop_task_worst_median", kpi="stop_error_max_mm"),
    Value("ur5e.on_real.stop_pass_rate", "ur5e-v2", _ur5e("ctc_model_err") + ("gate_pass_rate", "stop_error_max_mm"), "fraction", "%", 0,
          "gate_pass_rate"),
    Value("ur5e.tuned.tcp_rms", "ur5e-v2", _ur5e("ctc_tuned") + ("median", "tcp_track_rms_mm"), "m", "mm", 4, "tcp_rms",
          kpi="tcp_track_rms_mm"),
    Value("ur5e.tuned.stop_task_worst", "ur5e-v2", _ur5e("ctc_tuned") + ("median", "stop_error_max_mm"), "m", "mm", 4,
          "stop_task_worst_median", kpi="stop_error_max_mm"),
    Value("ur5e.tuned.stop_pass_rate", "ur5e-v2", _ur5e("ctc_tuned") + ("gate_pass_rate", "stop_error_max_mm"), "fraction", "%", 0,
          "gate_pass_rate"),
    # the UR wrist test rig, held-out tape, park pose
    Value("urwrist.on_real.stop_worst", "urwrist-asfound", ASFOUND_RUN + ("tool_mm_worst",), "mm", "mm", 2, "stop_worst"),
    Value("urwrist.on_real.stop_median", "urwrist-asfound", ASFOUND_RUN + ("tool_mm_median_of_stops",), "mm", "mm", 2, "stop_median"),
    Value("urwrist.on_real.within", "urwrist-asfound", ASFOUND_RUN + ("within_1mm",), "", "", 0, "within_gate"),
    Value("urwrist.on_real.stops", "urwrist-asfound", ASFOUND_RUN + ("stops",), "", "", 0, "stops"),
    Value("urwrist.tuned.stop_worst", "urwrist-tuned", TUNED_RUN + ("tool_mm_worst",), "mm", "mm", 2, "stop_worst"),
    Value("urwrist.tuned.stop_median", "urwrist-tuned", TUNED_RUN + ("tool_mm_median_of_stops",), "mm", "mm", 2, "stop_median"),
    Value("urwrist.tuned.within", "urwrist-tuned", TUNED_RUN + ("within_1mm",), "", "", 0, "within_gate"),
    Value("urwrist.tuned.stops", "urwrist-tuned", TUNED_RUN + ("stops",), "", "", 0, "stops"),
    # WHY all three joints (review 2026-11-20 C6): the as-found plan carries a Coulomb feed-forward on every wrist joint, not one
    Value("urwrist.on_real.coulomb_ff_can14", "urwrist-asfound-session", ("plan", "steps", 0, "ff_coulomb_nm", "14"), "N.m", "N·m", 3,
          "feedforward"),
    Value("urwrist.on_real.coulomb_ff_can15", "urwrist-asfound-session", ("plan", "steps", 0, "ff_coulomb_nm", "15"), "N.m", "N·m", 3,
          "feedforward"),
    Value("urwrist.on_real.coulomb_ff_can16", "urwrist-asfound-session", ("plan", "steps", 0, "ff_coulomb_nm", "16"), "N.m", "N·m", 3,
          "feedforward"),
    Value("urwrist.tuned.kp_hold", "urwrist-tuned-session", ("plan", "steps", 0, "kp_scale_hold", "15"), "x", "×", 0, "gain_scale"),
    # the BAM arm (arm_motion_bench's real climb stores display units)
    Value("bamarm.target.speed", "bamarm-climb", BAM_TUNED + ("fraction",), "fraction", "%", 0, "speed_fraction"),
    Value("bamarm.on_real.speed", "bamarm-climb", BAM_BASELINE + ("fraction",), "fraction", "%", 0, "speed_fraction"),
    Value("bamarm.on_real.tcp_rms", "bamarm-climb", BAM_BASELINE + ("tcp_track_rms_mm",), "mm", "mm", 2, "tcp_rms", kpi="tcp_track_rms_mm"),
    Value("bamarm.on_real.stop_median", "bamarm-climb", BAM_BASELINE + ("stop_error_mm",), "mm", "mm", 2, "stop_median", kpi="stop_error_mm"),
    Value("bamarm.on_real.joint_rms", "bamarm-climb", BAM_BASELINE + ("joint_track_rms_deg",), "deg", "°", 3, "joint_rms",
          kpi="joint_track_rms_deg"),
    Value("bamarm.tuned.tcp_rms", "bamarm-climb", BAM_TUNED + ("tcp_track_rms_mm",), "mm", "mm", 2, "tcp_rms", kpi="tcp_track_rms_mm"),
    Value("bamarm.tuned.stop_median", "bamarm-climb", BAM_TUNED + ("stop_error_mm",), "mm", "mm", 2, "stop_median", kpi="stop_error_mm"),
    Value("bamarm.tuned.joint_rms", "bamarm-climb", BAM_TUNED + ("joint_track_rms_deg",), "deg", "°", 3, "joint_rms",
          kpi="joint_track_rms_deg"),
    Value("bamarm.twin_nearest.tcp_rms", "bamarm-twin", ("rows", "0.5 kp_hold_2", "tcp_track_rms_mm"), "mm", "mm", 2, "tcp_rms",
          kpi="tcp_track_rms_mm"),
    Value("bamarm.twin_nearest.stop_median", "bamarm-twin", ("rows", "0.5 kp_hold_2", "stop_error_mm"), "mm", "mm", 2, "stop_median",
          kpi="stop_error_mm"),
    Value("bamarm.sweep.stop_worst", "bamarm-sweep", ("metrics", "tool_error_mm"), "mm", "mm", 2, "stop_worst"),
    Value("bamarm.sweep.stops", "bamarm-sweep", ("metrics", "tool_error_mm_by_stop"), "", "", 0, "stops", derive={"size": True}),
    # sim2real's own calibrate() against a hidden world (the recorded examples) and the sysid oracle
    Value("rec.pendulum.recovered", "ex-pendulum", ("parameters",), "", "", 0, "recovered", derive=COUNT_PASS),
    Value("rec.pendulum.graded", "ex-pendulum", ("parameters",), "", "", 0, "graded", derive=COUNT_GRADED),
    Value("rec.pendulum.nominal", "ex-pendulum", ("evaluation", "to_dict", "metrics", "held_out_link_fidelity", "before"),
          "x floor", "× floor", 2, "held_out_ratio"),
    Value("rec.pendulum.fitted", "ex-pendulum", ("evaluation", "to_dict", "metrics", "held_out_link_fidelity", "after"),
          "x floor", "× floor", 2, "held_out_ratio"),
    Value("rec.pendulum.floor", "ex-pendulum", ("evaluation", "to_dict", "floor_mrad"), "mrad", "°", 4, "floor"),
    Value("rec.urwrist.recovered", "ex-urwrist", ("parameters",), "", "", 0, "recovered", derive=COUNT_PASS),
    Value("rec.urwrist.graded", "ex-urwrist", ("parameters",), "", "", 0, "graded", derive=COUNT_GRADED),
    Value("rec.urwrist.not_identified", "ex-urwrist", ("parameters",), "", "", 0, "not_identified", derive=COUNT_UNGRADED),
    Value("rec.urwrist.nominal", "ex-urwrist", ("evaluation", "to_dict", "tool_stop_m", "nominal"), "m", "mm", 1, "held_out_tool"),
    Value("rec.urwrist.fitted", "ex-urwrist", ("evaluation", "to_dict", "tool_stop_m", "fitted"), "m", "mm", 3, "held_out_tool"),
    Value("rec.urwrist.floor", "ex-urwrist", ("evaluation", "to_dict", "tool_stop_m", "floor"), "m", "mm", 3, "floor"),
    Value("rec.ur5e.recovered", "sysid-ur5e", ("verdict", "parameters_pass"), "", "", 0, "recovered"),
    Value("rec.ur5e.graded", "sysid-ur5e", ("verdict", "parameters"), "", "", 0, "graded"),
    Value("rec.ur5e.nominal", "sysid-ur5e", ("metrics", {"where": {"id": "held_out_tool_position_mm"}}, "before"), "mm", "mm", 2,
          "held_out_flange"),
    Value("rec.ur5e.fitted", "sysid-ur5e", ("metrics", {"where": {"id": "held_out_tool_position_mm"}}, "after"), "mm", "mm", 3,
          "held_out_flange"),
    # the deployed lifecycle's two sim studies
    Value("life.wear.check_every_h", "drift-wear", ("check_every_h",), "h", "h", 0, "hours"),
    Value("life.wear.ratio_alarm_h", "drift-wear", ("ratio_alarm_h",), "h", "h", 0, "hours"),
    Value("life.wear.gap_alarm_h", "drift-wear", ("gap_alarm_h",), "h", "h", 0, "hours"),
    Value("life.wear.crossing_h", "drift-wear", ("actual_crossing_h",), "h", "h", 1, "hours"),
    Value("life.wear.predicted_at_h", "drift-wear", ("predicted_at_h",), "h", "h", 0, "hours"),
    Value("life.wear.predicted_crossing_h", "drift-wear", ("predicted_crossing_h",), "h", "h", 1, "hours"),
    Value("life.wear.plan_by_h", "drift-wear", ("plan_by_h",), "h", "h", 1, "hours"),
    Value("life.camera.knock_h", "drift-camera", ("knock_h",), "h", "h", 0, "hours"),
    Value("life.camera.alarm_h", "drift-camera", ("alarm_h",), "h", "h", 0, "hours"),
)

LABELS = (
    Label("pendulum.sim.twin", "pendulum-r9", ("twins_used", "can11")),
    Label("pendulum.on_real.controller", "pendulum-r0", ("controller",)),
    Label("pendulum.tuned.controller", "pendulum-r9", ("controller",)),
    Label("ur5e.on_real.controller", "ur5e-v2", _ur5e("ctc_model_err") + ("controller",)),
    Label("ur5e.tuned.controller", "ur5e-v2", _ur5e("ctc_tuned") + ("controller",)),
    Label("ur5e.on_real.description", "amb-ur5e-baselines", ("CONTROLLER_DESCRIPTIONS", "ctc_model_err")),
    Label("ur5e.tuned.description", "amb-ur5e-baselines", ("CONTROLLER_DESCRIPTIONS", "ctc_tuned")),
    Label("urwrist.on_real.run", "urwrist-asfound", ("runs", "heldout_1112", "folder"), {"basename": True}),
    Label("urwrist.tuned.run", "urwrist-tuned", ("runs", "heldout_kphold_1112", "folder"), {"basename": True}),
    Label("bamarm.on_real.layout", "bamarm-climb", BAM_BASELINE + ("layout",)),
    Label("bamarm.tuned.layout", "bamarm-climb", BAM_TUNED + ("layout",)),
    Label("rec.pendulum.routines", "ex-pendulum", ("calibration", "routines"), {"pluck": "routine"}),
    Label("rec.urwrist.routines", "ex-urwrist", ("calibration", "routines"), {"pluck": "routine"}),
)

GATE = "gate.tool_mm"


# ---------------------------------------------------------------------------------------------------------------- the three metrics

# WHY these titles: Zach's own words (Daily Note 2026-11-20); "as found" lives in the definition
METRICS = (
    # WHY "the row's target", not "the same target" (review 2026-11-20 C4): each row says how its cells were matched, and its notes say
    # what still differs (the pendulum's rounds share their peak speed, not their swing)
    ("sim", "Sim", "The controller that ships, played on the robot's fitted twin over the row's target. It is what the robot should do."),
    ("on_real", "Sim on Real", "The row's target on the robot as found: the controller it had before this calibration and tuning (its board "
                               "gains and any feed-forward it already carried), with nothing newly fitted. On a pseudo-real row the robot is a "
                               "hidden simulated world."),
    # WHY no "never an integrator" (review 2026-11-20 C1): one real BAM arm run in a cited file had a rest integrator; what holds is the
    # rows shown, and what sim2real ships (preflight refuses an integrator)
    ("tuned", "Sim on Real (tuned)", "The row's target on the robot after fitting and tuning: feed-forward from the fitted values and retuned "
                                     "PD gains. Every real tuned run shown ran PD and feed-forward only; a pseudo-real row names any integral "
                                     "term its controller has."),
)


# ---------------------------------------------------------------------------------------------------------------- the three robots

# WHY each cell leads with the number its gate chip judges (review 2026-11-20 D1): the page shows that one large and the rest small, so a
# row reads at a glance; the ruler pins the order of a cell's numbers to this tuple.
ROBOTS = (
    Robot("pendulum", "The {=1-DOF} pendulum", (
        Row("pendulum-real", "real", "{=1-DOF} pendulum on the bench", "/examples/pendulum_can11/",
            "Swings to a commanded peak speed of {pendulum.target.peak_speed}; worst tool error at a stop, stops played, joint tracking "
            "RMS. The rounds are matched by peak speed only: the notes say what differs.",
            {
                "sim": Cell(("pendulum.sim.stop_worst", "pendulum.sim.stops", "pendulum.sim.joint_rms"), "pendulum.sim.stop_worst",
                            "the fitted twin under the tuned controller", "pendulum.sim.twin"),
                "on_real": Cell(("pendulum.on_real.stop_worst", "pendulum.on_real.stops", "pendulum.on_real.joint_rms"),
                                "pendulum.on_real.stop_worst", "the board as found", "pendulum.on_real.controller"),
                "tuned": Cell(("pendulum.tuned.stop_worst", "pendulum.tuned.stops", "pendulum.tuned.joint_rms"), "pendulum.tuned.stop_worst",
                              "board PD retuned, with fitted gravity, inertia and friction feed-forward", "pendulum.tuned.controller"),
            },
            same=(("pendulum.target.peak_speed", "pendulum.on_real.peak_speed"),),
            notes=(
                # WHY both differences named (review 2026-11-20 C4): the amplitude and the stop count differ, not only the amplitude
                "The two rounds share only their commanded peak speed ({pendulum.on_real.peak_speed} as found). The as-found plays swing to "
                "{pendulum.on_real.amplitude} and stop {pendulum.on_real.stops} times; the tuned ones swing to {pendulum.tuned.amplitude} "
                "and stop {pendulum.tuned.stops} times.",
                # WHY this reason (review 2026-11-20 C2): round 0 ran the three repeats it planned; its scorer's own why_unknown says no
                # same-input pair survived, each rejected for its length
                "Twin against robot on the same tuned runs: {pendulum.fidelity.sim_vs_real}, against a run-to-run floor of "
                "{pendulum.fidelity.floor}. The as-found round's floor was not measured: its scorer found no pair of repeat runs with the "
                "same input on the tick clock (each candidate pair was rejected for its length).",
                "Scored by bam_rack_twin's pendulum scorer, on a branch that is not merged yet.",
            ),
            media="pendulum-can11-still"),
    )),
    Robot("ur_arm", "The UR arm", (
        Row("ur5e-pseudo", "pseudo-real", "UR5e, in simulation", "#recovery-ur5e-oracle",
            "The held-out workspace tasks at full speed in MuJoCo, where the arm has joint friction its controller's model lacks and inertia "
            "it gets wrong. The share of runs (every repeat counts) with every stop within the gate, then medians over {ur5e.tasks} tasks "
            "of each task's worst stop and of TCP tracking RMS. No joint error is recorded for this row.",
            {
                "sim": Status("not_measured", "arm_motion_bench plays this hidden world only, never a fitted twin of it; its perfect-model "
                                              "run is a frictionless ceiling, not this robot."),
                "on_real": Cell(("ur5e.on_real.stop_pass_rate", "ur5e.on_real.stop_task_worst", "ur5e.on_real.tcp_rms"),
                                "ur5e.on_real.stop_pass_rate", "computed torque on a model with inertia errors and no friction",
                                "ur5e.on_real.controller", evidence=("ur5e.on_real.description",)),
                "tuned": Cell(("ur5e.tuned.stop_pass_rate", "ur5e.tuned.stop_task_worst", "ur5e.tuned.tcp_rms"), "ur5e.tuned.stop_pass_rate",
                              "the same with friction identified, a stiffer loop and an integral term", "ur5e.tuned.controller",
                              evidence=("ur5e.tuned.description",)),
            },
            notes=(
                "No UR5e exists here. Tuned means friction identified and the controller rebuilt in arm_motion_bench, not sim2real's "
                "`calibrate()`; it was tuned on the development tasks and is scored here on held-out ones.",
            )),
        Row("urwrist-real", "real", "UR wrist test rig", "/examples/ur_wrist_test_rig/",
            "Three wrist joints returning to the park pose {urwrist.tuned.stops} times on a held-out tape; worst and median tool error at "
            "a stop, and the stops within the gate. No joint error is recorded for this row.",
            {
                "sim": Status("not_measured", "the twin was never replayed under these two controllers on this tape."),
                "on_real": Cell(("urwrist.on_real.stop_worst", "urwrist.on_real.stop_median", "urwrist.on_real.within",
                                 "urwrist.on_real.stops"), "urwrist.on_real.stop_worst",
                                "gains and Coulomb feed-forward from an earlier fit of this rig", "urwrist.on_real.run"),
                "tuned": Cell(("urwrist.tuned.stop_worst", "urwrist.tuned.stop_median", "urwrist.tuned.within", "urwrist.tuned.stops"),
                              "urwrist.tuned.stop_worst", "the same, with one joint's hold gain at {urwrist.tuned.kp_hold}",
                              "urwrist.tuned.run"),
            },
            same=(("urwrist.on_real.stops", "urwrist.tuned.stops"),),
            notes=(
                "Every stop here is a return to the park pose. The as-found controller was already the product of an earlier fit: its "
                "gains, and a Coulomb feed-forward on all three joints ({urwrist.on_real.coulomb_ff_can14}, "
                "{urwrist.on_real.coulomb_ff_can15} and {urwrist.on_real.coulomb_ff_can16}). Tuning changed only one joint's hold gain.",
                "Retired after this campaign; its design is now the BAM arm's wrist.",
            ),
            media="ur-wrist-rig"),
    )),
    Robot("bam_arm", "The BAM arm", (
        Row("bamarm-track", "real", "BAM arm (five-bar, UR wrist, claw)", "#recovery-bamarm-oracle",
            "The development workspace tape at {bamarm.target.speed} of full speed; median tool error at a stop (the only stop number this "
            "file records per run), TCP tracking RMS, worst-joint tracking RMS.",
            {
                "sim": Status("not_measured", "the twin has not been played with the measured static load at rest that the tuned controller "
                                              "adds."),
                "on_real": Cell(("bamarm.on_real.stop_median", "bamarm.on_real.tcp_rms", "bamarm.on_real.joint_rms"),
                                "bamarm.on_real.stop_median", "the trajectory controller as found: board PD with gravity compensation",
                                "bamarm.on_real.layout"),
                "tuned": Cell(("bamarm.tuned.stop_median", "bamarm.tuned.tcp_rms", "bamarm.tuned.joint_rms"), "bamarm.tuned.stop_median",
                              "model feed-forward with lookahead, the measured static load held at rest, and a stiffer hold; the boards' "
                              "integral gain at zero",
                              "bamarm.tuned.layout"),
            },
            same=(("bamarm.target.speed", "bamarm.on_real.speed"),),
            notes=(
                "Picked by a stated rule, not by hand: the newest run at this speed with model feed-forward and no integrator. It was tuned "
                "on this same tape: the static load it holds at rest was measured on earlier runs of it.",
                # WHY (review 2026-11-20 C1): the old note said "the real arm runs PD and feed-forward only", which this file contradicts
                "The tuned run shown ran PD and feed-forward only: its notes say the boards ran with integral gain zero. One run in the "
                "same file added a rest integrator; it is left out under that rule, but it is one of the earlier runs the static load was "
                "measured on.",
                "The twin's nearest run (the same feed-forward and stiffer hold, without the static load): {bamarm.twin_nearest.tcp_rms} "
                "tracking, {bamarm.twin_nearest.stop_median} median stop ({gate:bamarm.twin_nearest.stop_median}).",
                "This file records only each run's median stop. PID tuna's workspace sweep, a different target, records every stop: worst "
                "{bamarm.sweep.stop_worst} over {bamarm.sweep.stops} stops ({gate:bamarm.sweep.stop_worst}).",
                "A running job still adds rows to this file; the page cites a frozen copy of it.",
            ),
            media="bam-arm-tuned"),
    )),
)


# ---------------------------------------------------------------------------------------------------------------- hidden-truth recovery

RECOVERY = (
    Recovery("pendulum-oracle", "pendulum", "{=1-DOF} pendulum", 'sim2real.examples.pendulum_can11().calibrate(on="sim")',
             "link angle, twin against the hidden world on held-out runs, in multiples of the run-to-run floor",
             "ex-pendulum", "rec.pendulum.routines",
             {"recovered": Cell(("rec.pendulum.recovered", "rec.pendulum.graded")), "nominal": Cell(("rec.pendulum.nominal",)),
              "fitted": Cell(("rec.pendulum.fitted",)), "floor": Cell(("rec.pendulum.floor",))},
             # WHY this order (review 2026-11-20 C9): docs/CALIBRATE.md and docs/API.md run the gear gap first, then the regression
             notes=("Recorded before the pendulum's schedule changed: today it runs `servo.backlash_reversals_camera`, then "
                    "`servo.dynamics_regression`. A re-record on the current schedule is still to do.",)),
    # WHY the not-identified count in the cell (review 2026-11-20 C7): the hero quotes it beside the recovered count, and the hero may
    # only quote this table
    Recovery("urwrist-oracle", "ur_arm", "UR wrist test rig", 'sim2real.examples.ur_wrist_test_rig().calibrate(on="sim")',
             "p95 tool position at stops, twin against the hidden world on held-out runs",
             "ex-urwrist", "rec.urwrist.routines",
             {"recovered": Cell(("rec.urwrist.recovered", "rec.urwrist.graded", "rec.urwrist.not_identified")),
              "nominal": Cell(("rec.urwrist.nominal",)), "fitted": Cell(("rec.urwrist.fitted",)), "floor": Cell(("rec.urwrist.floor",))},
             notes=("{rec.urwrist.not_identified} more values are carried, each saying why it is not identified.",)),
    Recovery("ur5e-oracle", "ur_arm", "UR5e", "python -m sysid run ur5e",
             "flange position, twin against a hidden tracker on held-out poses (the sysid oracle; not yet a RobotTwin)",
             "sysid-ur5e", None,
             {"recovered": Cell(("rec.ur5e.recovered", "rec.ur5e.graded")), "nominal": Cell(("rec.ur5e.nominal",)),
              "fitted": Cell(("rec.ur5e.fitted",)),
              "floor": Status("not_measured", "the sysid oracle records no floor for this measure.")}),
    # WHY four short reasons, not one sentence four times (review 2026-11-20 D9)
    Recovery("bamarm-oracle", "bam_arm", "BAM arm", None, "none yet", None, None,
             {"recovered": Status("not_built", "no hidden-truth world or RobotTwin for the BAM arm yet."),
              "nominal": Status("not_built", "needs that world."),
              "fitted": Status("not_built", "needs that world."),
              "floor": Status("not_built", "needs repeat runs on that world.")}),
)


# ---------------------------------------------------------------------------------------------------------------- the three modes

MODES = (
    Mode(1, "Start in sim at the right values and see the performance",
         "Not a sim2real call yet, on any robot. The Sim column above was played by each robot's own lab twin. The missing verb: play "
         "a target on the twin under the controller you ship, and score it with the robot's own ruler.",
         None,
         {"pendulum": Status("not_built", "`simulate()` plays a free release, not a target; the lab's scorer plays targets on its own "
                                          "twin."),
          "ur_arm": Status("not_built", "the wrist rig has no `simulate()` yet; the UR5e is played in arm_motion_bench, not as a sim2real "
                                        "twin."),
          "bam_arm": Status("not_built", "no RobotTwin for the BAM arm yet; its sims run in arm_motion_bench.")}),
    Mode(2, "Run every routine and check it recovers the true values",
         "The twin calibrates against a sealed world whose values differ from its description's, then each recovered value is checked "
         "against the hidden one.",
         'sim2real.examples.pendulum_can11().calibrate(on="sim")',
         {"pendulum": Status("runs", "every hidden value recovered (the table below)."),
          "ur_arm": Status("runs", "the wrist rig through `sim2real.examples.ur_wrist_test_rig()`; the UR5e only through the sysid oracle."),
          "bam_arm": Status("not_built", "no hidden-truth world for the BAM arm yet.")}),
    Mode(3, "Pseudo-real: another sim with slightly different values",
         # WHY "away from", not "further from": the ruler bans comparatives in prose (a comparison is only ever computed)
         "Move the hidden world away from the description with `move_truth=`: a fit that misses the moved values must turn red.",
         'sim2real.RobotTwin.from_robot_description(station_description(11), world="nominal").calibrate(on="sim", '
         'move_truth={"can11.gravity_nm": 5.2, "can11.damping_nm_s_rad": 0.25})',
         {"pendulum": Status("runs", "the sealed world, and the description's own world moved by `move_truth`."),
          "ur_arm": Status("runs", "the wrist rig's sealed world, and its CAD bundle moved through a test-only reader; the UR5e's sysid "
                                   "hidden world."),
          "bam_arm": Status("not_built", "only its homing plant hides values; no `calibrate()` world yet.")}),
)


# ---------------------------------------------------------------------------------------------------------------- hero

HERO = {
    "eyebrow": "sim2real · calibration for robot twins",
    "h1": "Describe your robot in CAD. The calibration comes with it.",
    "lead": "Every part in a robot description has a known type: a servo, a gearbox, a camera. Each type knows the models that describe it "
            "and the routines that measure them, so the description is enough: sim2real builds the twin, plans the routines your bench can "
            "run, fits them, and scores the twin on runs it never saw.",
    # WHY "not accepted", the plain reading of twin.py's refusal of component types sim2real does not know (review 2026-11-20 C11)
    "today": "Today that holds for the bench pendulum's description, and for the UR wrist rig's CAD bundle through a test-only reader. "
             "The BAM arm's description is not accepted yet: its servos are not typed parts.",
    # WHY each measure is named where it is quoted (review 2026-11-20 D3): "x floor" was first defined a section later
    "lines": (
        "{=1-DOF} pendulum: {rec.pendulum.recovered} of {rec.pendulum.graded} hidden values recovered. Held-out error in multiples "
        "of the run-to-run floor: {rec.pendulum.nominal} with the description's values, {rec.pendulum.fitted} after fitting.",
        "UR wrist rig: {rec.urwrist.recovered} of {rec.urwrist.graded} graded values recovered, {rec.urwrist.not_identified} more not "
        "identified. Tool error at stops on held-out runs (p95): {rec.urwrist.nominal} with the description's values, "
        "{rec.urwrist.fitted} after fitting.",
    ),
    "media": "pendulum-can11-loop",
}


# ---------------------------------------------------------------------------------------------------------------- deployed lifecycle

LIFECYCLE = {
    "lead": "Once a robot is at work, calibration is mostly watching the fit. Its own work, every pick, is data. The twin replays recent "
            "runs; when the fit drifts it refits a challenger on recent sessions, scores it against the twin in service on the same "
            "held-out runs, and keeps it only if it wins. Nothing is installed on its own.",
    "loop": ("monitor", "trigger", "refit a challenger", "shadow-compare", "keep if it wins", "new record"),
    "today": (
        ("/routines/servo.live_reid_t10/", "Live re-identification while the joint works; its page shows its grades, biased against a "
                                           "Stribeck truth."),
        ("/routines/servo.gap_check_forecast/", "A gap check every {life.wear.check_every_h} with a wear forecast. In a sim study on the "
                                                "pendulum's hidden world the fidelity ratio warned at {life.wear.ratio_alarm_h} and the "
                                                "gap check alone at {life.wear.gap_alarm_h}; the hidden wear crossed its allowance at "
                                                "{life.wear.crossing_h}. At {life.wear.predicted_at_h} the forecast named "
                                                "{life.wear.predicted_crossing_h}, with plan-by {life.wear.plan_by_h}."),
        ("/routines/camera.pose_recal_belt_tags/", "Camera pose refit from belt tags. In a sim study of a two-arm cell, a camera knocked at "
                                                   "{life.camera.knock_h} was flagged at {life.camera.alarm_h}."),
        ("/routines/cell.tags_bundle_adjustment/", "Cell tags bundle adjustment."),
        # WHY "plus those that run anywhere" (review 2026-11-20 C3): Budget.allows admits setting "both" whatever the settings say
        ("/api/#api-Budget", '`Budget(settings=("deployed",))` plans the routines that run on a robot at work plus those that run anywhere, '
                             "and `calibrate(data=…)` refits on runs the twin already holds."),
        ("/api/#api-Ledger", "Each calibration writes a ledger with a W&B copy, and `preflight()` checks a fit before it ships."),
        (None, "No robot has a real deployed record yet."),
    ),
    "not_built": (
        ("production", "`sim2real.calibration.production()`: pick sessions in, CalibrationData out, the newest sessions held out."),
        ("monitor", "`fitted.monitor()`: fidelity, parameter drift with its forecast, performance, coverage, and what is due."),
        ("recalibrate", "`fitted.recalibrate()`: a challenger refit on recent sessions, kept only if it wins on the same held-out runs."),
        ("valid_until", "a validity window on the record."),
        ("save_description", "`fitted.save_description()`: the description is written only when you say so."),
    ),
}


# ---------------------------------------------------------------------------------------------------------------- media

# WHY WebP and JPEG only: the cloud cut drops *.mp4, *.webm and *.gif (bam_ws tools/cloud/slim_repo.py), so a VM would build a page whose
# video is missing. WHY the crop: the onedof clip burns in text in its top band (rows 0-103: rung, speed, numbers) and a progress bar along
# its bottom edge (rows 350-359), so the crop keeps rows 104-343 only (seen on the contact sheets); and the camera sits the pendulum at the
# clip's right edge, so the crop keeps columns 280-639, where the link swings (review 2026-11-20 D2). WHY the whole clip (review C10): the
# caption says the speed rises rung by rung, and the first ten seconds showed only the slow rungs.
MEDIA = (
    Media("pendulum-can11-loop", "media/pendulum-can11.webp", "bamws:reports/media/onedof-pendulum-2026-11-15/rising-can11.mp4",
          "bamws:reports/onedof-pendulum-2026-11-15.html",
          "The {=1-DOF} pendulum on its tuned controller, speed rising rung by rung (real, one-to-one time). The numbers beside it are its "
          "twin's calibration against a hidden world.",
          "loop", "trim=0:25.8,crop=360:240:280:104,fps=10", quality=55),
    Media("pendulum-can11-still", "media/pendulum-can11.jpg", "bamws:reports/media/onedof-pendulum-2026-11-15/rising-can11.mp4",
          "bamws:reports/onedof-pendulum-2026-11-15.html", "The {=1-DOF} pendulum on the bench (real).",
          "frame", "crop=360:240:280:104", at_s=5.0, quality=4),
    Media("ur-wrist-rig", "media/ur-wrist-rig.jpg", "bamws:reports/media/ur-wrist-sim2real-2026-11-12/poster.jpg",
          "bamws:reports/ur-wrist-sim2real-2026-11-12.html", "The UR wrist test rig on the bench (real).", "copy"),
    Media("bam-arm-tuned", "media/bam-arm-tuned.jpg",
          "amb:reports/media/bam_fb_real/dev000_v2_rung_0.5_modelff_la_restload_kp2_1120-191453-1e54.mp4",
          "amb:outputs/bam_fb/real/climb.json", "The BAM arm during the tuned run in its row (real).",
          "frame", "scale=960:-2", at_s=None, quality=4),   # at_s None = half the tape
)
