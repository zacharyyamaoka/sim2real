#!/usr/bin/env python3
"""One-click calibration: where it stands (2026-11-15) — summary report + clickable mock.

Stdlib only. Reads, never computes:
- website/examples/ur_wrist_test_rig.out.json   the real sim2real.calibration/1 record of the UR wrist (sim, 2026-11-12)
- sysid/examples/ur_wrist_test_rig/description.json   the rig's components
The "seen" flags are a snapshot taken 2026-11-15 from local Chrome history (file:// visits under /home/bam only); the
Claude app's side panel is not counted. The hero video is recorded from this page's own mock by
docs/record_one_click_summary_hero.py into reports/media/one-click-calibration-2026-11-15/.

Writes reports/one-click-calibration-2026-11-15.html.

WHY a mock on real numbers (Zach, Daily Note 2026-11-15 "turn key sim to real"): he wants the one-click calibrate to feel like
PID tuna — describe, plug in, calibrate — and asked for "a mock of the summary to date". Every number the mock shows comes from
the record above unless its chip says otherwise, so the mock can't promise more than the code does.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "one-click-calibration-2026-11-15.html"
MEDIA = "media/one-click-calibration-2026-11-15"


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


# --------------------------------------------------------------------------- the real record the mock plays
def mock_data() -> dict:
    record = json.loads((ROOT / "website/examples/ur_wrist_test_rig.out.json").read_text())
    description = json.loads((ROOT / "sysid/examples/ur_wrist_test_rig/description.json").read_text())
    calibration = record["calibration"]
    evaluation = record["evaluation"]["to_dict"]
    return {
        "recorded": record["recorded"],
        "seconds": calibration["seconds"],
        "model": record["model"],
        "summary": description.get("summary", ""),
        "bundle": description["model"]["source"],
        "components": [{k: c.get(k) for k in ("id", "type", "title", "parent")} for c in description["components"]],
        "steps": [{"routine": s["routine"], "title": s["title"], "kind": s["kind"], "setting": s["setting"],
                   "wall": s["wall_time_s"], "op": s["operator_time_s"]} for s in calibration["plan"]["steps"]],
        "ran": [{"routine": r["routine"], "runs": r["runs"], "seconds": r["seconds"], "identifies": r["identifies"]}
                for r in calibration["routines"]],
        "totals": calibration["plan"]["totals"],
        "params": [{"key": p["key"], "unit": p["unit"], "nominal": p["nominal"], "value": p["value"], "true": p["true"],
                    "pass": p["pass"], "routine": p["routine"], "why_not": (p.get("why_not") or "")} for p in record["parameters"]],
        "gates": [{"id": g["id"], "title": g["title"], "value": g["value"], "rule": g["rule"], "passed": g["passed"]}
                  for g in evaluation["gates"]],
        "eval_runs": evaluation["runs"],
        "eval_seconds": evaluation["seconds"],
    }


# --------------------------------------------------------------------------- reports (seen = opened in Chrome, snapshot 2026-11-15)
# (date, repo-relative path under /home/bam, title, one line, seen-date or None, read-first rank or None)
REPORTS = [
    ("2026-11-12", "sim2real/reports/docs-site-and-calibrate-backend-2026-11-12.html", "calibrate() back end + docs site",
     "The heart of one-click, merged (PEP 0001): the planner orders routines by requires/uses/refines, CalibrationConfig steers "
     "it, every run returns a sim2real.calibration/1 record. Docs site: 12 types, 62 routines, 261 pages.", None, 1),
    ("2026-11-11", "sim2real/reports/sim2real-kpis-gates-curriculum-2026-11-11.html", "KPIs, gates and the curriculum",
     "Five questions every joint, arm and deployment answers in order — Floor → Data → Routines → Twin → Job — and where each "
     "rig stops. The ruler a real calibrate() will be graded by.", None, 2),
    ("2026-11-12", "bam_ws/reports/sim2real-morning-2026-11-12.html", "Sim2real morning: wrist + five-bar",
     "Both real rigs put the tool within 1 mm at their stops (wrist 98/98, worst 0.86 mm); neither twin is twinned yet "
     "(wrist CAN 15 at 2.98× its floor). It asked you two rulings — defaults taken, see Open questions.", None, 3),
    ("2026-11-12", "sim2real/reports/fivebar-one-click-2026-11-12.html", "Five-bar on the one-click seam",
     "calibrate(on=\"sim\") on the five-bar's sealed world, with a hero video of each routine. Values recovered, but the tool "
     "gate fails; the lane is still unmerged.", None, 4),
    ("2026-11-14", "bam_ws/reports/media/kinematic-calibration-benchmark-2026-11-14.html", "Kinematic calibration benchmark",
     "Every method, UR5e and bam_fb_v2, sim only: the ~$425 stack (stops + sockets + camera) reaches 0.353 mm with backlash "
     "fitted; a $100k laser tracker 0.254 mm. On branch claude/kincal-bench-1114.", None, 5),
    ("2026-11-13", "bam_ws/reports/pid-tuna-full-arm-2026-11-13.html", "PID tuna on the full arm",
     "All seven drives tuned in SIM; 6 of 7 stop tighter; pick cycle 3.68 mm worst TCP (today's gains 4.71 mm). The 'tune' "
     "step a one-click calibrate would call. Proposals only, nothing written to a board.", None, 6),
    ("2026-11-11", "sim2real/reports/sim2real-api-2026-11-11.html", "sim2real API",
     "The public API on the pendulum: examples → simulate → calibrate(on=\"sim\") → eval; to_robot_twin()/from_robot_twin() "
     "not built.", None, None),
    ("2026-11-15", "bam_ws/reports/media/hold-friction-2026-11-15.html", "Full-arm hold friction",
     "READY stops pass the 1 mm gate 14/14 (0.14–0.39 mm) on aims alone, PD + FF only; the 5 Hz C1 ring was our own host relay.",
     None, None),
    ("2026-11-14", "io-diagnostics/reports/media/device-reset-2026-11-14.html", "RobotDx device reset ladder",
     "Every device gets a reset ladder — own reset, USB rungs, then a page to you; a deployed robot runs it itself. The "
     "plug-and-play half of turnkey.", None, None),
    ("2026-11-13", "bam_ws/reports/media/rack-night-2026-11-13.html", "Rack night: full arm",
     "Homing, hand-eye and arm-hold on the real bam_fb_v2; homed, holds itself, first overhead camera pose.", None, None),
    ("2026-11-13", "bam_ws/reports/fullarm-homing-2026-11-13.html", "Full-arm homing (sim)",
     "The proper full-arm home in two phases (five-bar, then claw and wrist), PEP 0047; MuJoCo only.", None, None),
    ("2026-11-13", "bam_ws/reports/media/hand-eye-calibration-2026-11-13.html", "Hand-eye calibration study",
     "No new algorithm needed: fit every marker corner around the loop, one approach direction; 0.70 mm pixel fit (sim).",
     None, None),
    ("2026-11-13", "bam_ws/reports/cloud-twin-sweeps-2026-11-13.html", "Twin sweeps leave the workstation",
     "The rack twin's and sim2real's sweeps run on cloud VMs, bit-identical to local.", None, None),
    ("2026-11-12", "bam_ws/reports/ur-wrist-sim2real-2026-11-12.html", "UR wrist: target vs sim vs real",
     "Gate 3 passes on the real wrist (98/98 stops ≤ 1 mm); gate 2 (twin) fails on CAN 15.", None, None),
    ("2026-11-12", "bam_ws/reports/fivebar-sim2real-2026-11-12.html", "Five-bar sim2real morning",
     "Target vs sim passes at every end stop; target vs real hinges on the settled-stop ruling.", None, None),
    ("2026-11-11", "sim2real/reports/camera-types-2026-11-11.html", "Camera types",
     "RGB, RGBD and hyperspectral as types: name a camera's type and it gets its ladder, routines and metrics.", None, None),
    ("2026-11-11", "sim2real/reports/calibration-fivebar-2026-11-11/index.html", "Five-bar calibration result",
     "Before/after result page (needs result.display() or a local server — ES modules).", None, None),
    ("2026-11-11", "bam_ws/reports/conveyor-calibration-2026-11-11.html", "Conveyor belt calibration",
     "Nine belt routines recover a hidden truth on a MuJoCo twin; the arm probe finds the belt plane (sim, branch).", None, None),
    ("2026-11-11", "bam_ws/reports/fivebar-repeat-floor-2026-11-11.html", "Five-bar repeat floor",
     "Gates 1 and 3 pass 7/7; gate 2 (twin) 0/7 — cogging took the twin 37 % closer.", None, None),
    ("2026-11-11", "bam_ws/reports/fivebar-target-sim-real-2026-11-11.html", "Five-bar target vs sim vs real",
     "The three gates in order on 7 real rungs: 4 / 0 / 0 that night.", None, None),
    ("2026-11-11", "bam_ws/reports/fivebar-cad-twin-2026-11-11.html", "Five-bar CAD twin",
     "Dry runs default to your Fusion five-bar's MuJoCo twin.", None, None),
    ("2026-11-10", "sim2real/reports/calibration-ur-wrist-2026-11-10/index.html", "UR wrist calibration result",
     "Before/after result page for the wrist (needs result.display() or a local server).", None, None),
    ("2026-11-10", "bam_ws/reports/media/camera-calibration-2026-11-10.html", "Camera calibration",
     "Plug in, lights on, one command: the D435 exposure lock — a real one-command calibration.", None, None),
    ("2026-11-10", "bam_ws/reports/pid-tuna-fivebar-sim-2026-11-10.html", "PID tuna on the five-bar (sim)",
     "Accepted gains + Coulomb FF; 1.6–3.3× lower tool RMS than October.", None, None),
    ("2026-11-10", "io-diagnostics/reports/status-dots-2026-11-10.html", "RobotDx status dots",
     "Ring = stale, dot = connected, breathe = running: one mapping for every device row.", None, None),
    ("2026-11-07", "sim2real/reports/calibration-routines-2026-11-07.html", "Calibration routines, graded",
     "Every way to calibrate a parameter as a typed record, graded on one hidden truth at 0/1/3/10× noise.", None, None),
    ("2026-11-07", "sim2real/reports/media/sim2real-v3-2026-11-07/report.html", "Sim2Real v3 overnight",
     "Nine asks built overnight (129 commits).", None, None),
    ("2026-10-26", "bam_ws/reports/pid-tuner-design-rationale-2026-10-26.html", "PID tuner design rationale",
     "Why PID tuna is the way it is: one call turns a description into gates-passed gains — the UX to copy.", None, None),
    ("2026-10-18", "bam_ws/reports/media/rack-twin-2026-10-18/report.html", "Rack digital-twin scorecard",
     "Real rack vs CAD twin vs identified twin, per station.", None, None),
    # seen (opened in Chrome)
    ("2026-11-12", "bam_ws/reports/kinematic-calibration-2026-11-12.html", "Kinematic calibration (multi-arm)",
     "Robin-3 loops + 2 ball sockets per plate: 0.38 mm worst-arm TCP (sim); branch unmerged.", "11-15", None),
    ("2026-11-13", "bam_ws/reports/homing-routine-2026-11-13.html", "Homing routine", "The recommended home and J1 matched to the rack.",
     "11-14", None),
    ("2026-11-13", "bam_ws/reports/media/hand-eye-method-study-2026-11-13.html", "Hand-eye method study",
     "~3 mm worst-region pick p95 in sim; reproduces V1's real pose to 0.7 mm.", "11-14", None),
    ("2026-11-11", "sim2real/reports/one-click-tracer-2026-11-11.html", "One-click tracer",
     "The first end-to-end: pendulum_can11 → simulate → calibrate → eval; moved truth turns red.", "11-12", None),
    ("2026-11-11", "bam_ws/reports/homing-sim-2026-11-11.html", "Homing in sim", "Five-bar homing on the twin.", "11-12", None),
    ("2026-11-11", "bam_ws/reports/sim2real-presentation-proposals-2026-11-11/index.html", "Sim2real presentation proposals",
     "How to present sim2real (you opened it 17 times).", "11-11", None),
    ("2026-11-10", "bam_ws/reports/fivebar-real-vs-sim-2026-11-10.html", "Five-bar real vs sim", "First real-vs-sim five-bar.",
     "11-11", None),
    ("2026-11-05", "sim2real/reports/media/sysid-oracle-2026-11-05/report.html", "Sysid oracle",
     "Recover a sealed hidden truth in sim before touching hardware — your rule, as code.", "11-07", None),
    ("2026-11-05", "sim2real/reports/media/gates-next-2026-11-05/report.html", "Gates next", "Next gates for the servo twin.",
     "11-07", None),
    ("2026-11-04", "sim2real/reports/media/type-cards-2026-11-04/report.html", "Type cards", "Per-type model ladders and gates.",
     "11-05", None),
    ("2026-11-04", "robotparts/reports/goals-kpis-2026-11-04.html", "Robot Parts goals and KPIs",
     "Levels; level 5 = a sim twin checked against a rig.", "11-11", None),
    ("2026-10-29", "sim2real/reports/media/servo-can11-2026-10-29/report.html", "Servo CAN 11", "The first servo twin page.",
     "10-29", None),
    ("2026-10-28", "robotparts/reports/media/robotparts-rack-workflow-2026-10-28.html", "Robot Parts rack workflow",
     "Attach a part to the rack and characterise it.", "10-28", None),
    ("2026-10-25", "bam_ws/reports/media/pid-autotune-2026-10-25/traces.html", "PID autotune traces", "The first tuner traces.",
     "10-28", None),
    ("2026-10-23", "bam_ws/reports/media/rack-motor-models-2026-10-23/report.html", "Rack motor models",
     "Motor models and gates T1–T11 on the rack.", "10-28", None),
]

# --------------------------------------------------------------------------- his own words (verified against the source lines)
TIMELINE = [
    ("2025-12-29", "Apple Note · Robot description 1", "We will have the nominal values and the calibrated values",
     "The description carries both — the seed of calibrate-in-place."),
    ("2026-06-09", "SPRINT · Picking up object", "One click to run it in simulation / One click to run in reality",
     "The first one-click framing: Fusion assembly → RobotDescription → sim → real."),
    ("2026-10-02", "DP - Reality as Oracle", "I kinda just want to plug in the robot… start up sequence calibration sequence while it zeros, calibrates PIIDS",
     "The first 'it calibrates itself when I plug it in'."),
    ("2026-10-24", "Daily Note Oct 24", "Now AI can write the drivers, and Its just more blackbox plug in play",
     "Plug-and-play hardware."),
    ("2026-10-25", "Daily Note Oct 25 · How do I want robotics development to feel", "I don't even want to have to think about how to do the calibration",
     "No rack: download the best estimates. With a rack: servo + pendulum → full tests → done. Then plug it into RobotDx."),
    ("2026-11-04", "Daily Note Nov 4 · the PID-tuna analogy, first time", "I want this to feel very point and fire, similar to the PID auto tunner.",
     "“You kinda just like point this at a system and then it will basically like model it” — actuators, sensors, robots, systems."),
    ("2026-11-04", "Daily Note Nov 4", "The lowest rung for robot dx is I plug it in without any urdf",
     "…and later that day: “So this is really my goal. 1 click to just get this entire thing running.”"),
    ("2026-11-05", "PROJECT - Sim2Real · What does success look like", "Robot Description in. and then a better model out.",
     "Plus: “System ID adjusts the analytical models… PID tunner adjusts the PID weights” (Daily Note Nov 5)."),
    ("2026-11-10", "Daily Note Nov 10", "with Cad2Robot I should be able to do 1 click and update the entire pipeline",
     "CAD as the one source."),
    ("2026-11-11", "Voice note · Composable robotic systems", "one click to Mojo simulator, one click two calibrate",
     "“…all this information just carried around with the description… pass that now into robot DX.”"),
    ("2026-11-11", "Daily Note Nov 11", "It should basically be like I plug it in. It automatically generates the test schedule.",
     "“You run the tests and evaluate it on the metrics done.”"),
    ("2026-11-11", "Daily Note Nov 11", "we need to make sim2real completely turn key and standardized",
     "…and: “one function call and have the robot do all the automatic stuff it needs to do.”"),
    ("2026-11-12", "Chat · the sim2real lanes", "So when you do .calbriate() we already have all of the calibration routines we could possible need!",
     "Parts → models → routines, run in the right order automatically, with an injectable CalibrationConfig. Then the layering ruling: "
     "sim2real on top “makes it very easy to do the 1 click .calibrate()”."),
    ("2026-11-15", "Daily Note Nov 15 · turn key sim to real", "almost making it a bit like PID tuna",
     "Two halves: Robot Parts + RobotDx make hardware plug-and-play; sim2real makes calibrate one click."),
]

DECISIONS = [
    ("Oct 27", "Robot Parts stays a light catalog; the twin work lives in a separate sim2real studio."),
    ("Nov 5–6", "Every type gets a model ladder (M0, M1…) and a routine ↔ parameter table both ways."),
    ("Nov 11", "sim2real owns generic <b>types</b>, not manufacturers; a Robot Parts record names its type and lends datasheet priors."),
    ("Nov 11", "<b>calibrate()</b> stays one verb. Routines are atomic, in four kinds: configure → fit → tune → measure. PID tuna stays its own tool."),
    ("Nov 11", "The tool gate is <b>1 mm at a settled stop</b> (was 5 mm) — <code>sim2real.result.TOOL_GATE_MM</code>."),
    ("Nov 11 21:50", "Every gate reads the joint encoders through FK; ArUco is a flag, never a gate. Order: target vs sim → sim vs real → target vs real."),
    ("Nov 12", "Layering: robot_msgs ← robot_models ← robot_description ← robotparts, with <b>sim2real on top</b> as the outer API (may import pidtuna and the controllers). The move hasn't happened: robot_models holds only the homing core."),
    ("Nov 13", "The real arm runs PD + FF only, never an integrator. Arm time is earned: pass sim first."),
]

OPEN_QUESTIONS = [
    ("Is “twinned ≤ 1.5× the repeat floor” your bar?",
     "Never confirmed by you; the code and every gate use it.", "Keep 1.5×."),
    ("Where do calibrated values go?",
     "calibrate() returns a new twin and never writes back. Your voice note has them “carried around with the description”.",
     "Return the twin plus a sim2real.calibration/1 record saved beside the description; writing into the description is an explicit .save()."),
    ("How does RobotDx hand “what's plugged in” to calibrate?",
     "No note says. RobotDx needs no URDF (your Nov 4 rung); calibrate needs the description.",
     "RobotDx emits a device inventory; calibrate's first configure step checks it against the description and refuses on a mismatch."),
    ("Five-bar: do the 0.3 s approach holds count as stops?",
     "Asked in the 11-12 morning report you haven't opened: 7/7 at the 2 s end hold, 0/7 if approach holds count.",
     "No — only settled holds, as the gate's own wording says."),
    ("Passive joints: “N/A with a measured reason” instead of failing Floor forever?",
     "Proposed in the KPI curriculum (CAN 15/16 carry ≤ 0.012 N·m of gravity against ≥ 0.14 N·m breakaway).", "Yes."),
    ("Verbs on RobotTwin (built) or RobotDescription (your sketch)?",
     "Built on RobotTwin to keep the import order acyclic; your Nov 11 sketch had RobotDescription.load(…).calibrate().",
     "Keep RobotTwin; description.to_robot_twin().calibrate() reads the same."),
]

STACK = [
    ("Robot Parts", "priors", "none", "/home/bam/robotparts",
     "Catalog + datasheet values. The part → sim2real type mapping is still “pending” (docs/sim2real-types.md); real/twin drivers exist for the OBSBOT and belt only."),
    ("RobotDx", "plug in", "real", "/home/bam/io-diagnostics",
     "Device health, status dots and the reset ladder run on the real rack. It doesn't yet compare what's plugged in with a description."),
    ("Description", "describe", "sim", "Cad2Robot → MJCF",
     "sim2real loads Cad2Robot MJCF bundles today. robot_description (load, to_robot_twin, from_robot_twin) has no code."),
    ("calibrate()", "plan · collect · fit", "sim", "/home/bam/sim2real",
     "Planner, CalibrationConfig, the routine catalog, the collect/fit split and the record — all in sim. on=\"real\" raises NotImplementedError."),
    ("PID tuna", "tune", "real", "bam_pid_tunning · pidtuna",
     "Proposes gains on the real rack (CAN 12/13/21) and in tiers SIM → BENCH → DEPLOYED (PEP 0046). Not yet a routine inside calibrate()."),
    ("eval()", "measure", "sim", "sim2real.result",
     "Gates twinned / recovery / tool-at-stops on held-out runs. On the real rigs the same gates are scored by rack scripts, not by eval()."),
    ("Write back", "save", "none", "robot_description",
     "Fitted values into the description and Robot Parts' measurements/: not built."),
]

GAPS = [
    ("Wire <code>calibrate(on=\"real\")</code>", "the one missing seam",
     "The collect/fit split already exists, so this is a real backend that plays each planned routine's runs() through the rack "
     "runner (rackq submissions, bus lock, torque caps) and hands back robot_msgs trajectories for the same fit(). The error message "
     "in twin.py already names the path. First target: one pendulum station — today's critical path."),
    ("Make the pendulum example load anywhere", "found today",
     "<code>sim2real.examples.pendulum_can11()</code> needs bam_rack_twin's venv: in sim2real's own env it dies with "
     "<code>ModuleNotFoundError: bam_rack_twin</code> (I hit it running plan() this morning; the wrist loads fine), and its run "
     "still returns no sim2real.calibration/1 record. A one-click that needs the right venv isn't one yet."),
    ("PID tuna as a <i>tune</i> routine", "PEP 0001 already allows it",
     "pidtuna's <code>tune(servo, plant, goal)</code> has the right shape; registering it in the catalog lets the planner put it "
     "after the fits it needs (friction, inertia, delay)."),
    ("RobotDx as configure step 0", "inventory vs description",
     "Turn RobotDx's device tree into a check the planner runs first: every board the description names answers, nothing extra, "
     "no faults — or the reset ladder runs before calibration starts."),
    ("robot_description from CAD, and the write-back", "the two ends",
     "<code>to_robot_twin()</code> / <code>from_robot_twin()</code> and the Robot Parts type mapping, so the click starts at your "
     "CAD and ends back in it."),
    ("Real twins inside 1.5× their floor", "the hard part",
     "Real calibrate will expose what the rack scripts already show: wrist CAN 15 at 2.98×, five-bar 1.83–2.57×. The levers named "
     "so far are cogging, a rest-state stiction model and direction-dependent ripple."),
    ("Land the stragglers", "branches",
     "one-click-fivebar (tool gate 1.18 mm), kincal-bench-1114, hand-eye-method-1113, the motor-models branch and "
     "1dof-rack-sim-to-real all sit unmerged."),
]


# --------------------------------------------------------------------------- page
CSS = r"""
:root{--bg:#f7f6f2;--fg:#1c1b19;--muted:#67655e;--line:#e2dfd7;--card:#ffffff;--soft:#f0eee8;
--real:#1d7a4c;--real-bg:#e3f3ea;--sim:#2857b0;--sim-bg:#e6edfb;--none:#7d7a72;--none-bg:#efede7;
--warn:#9a5600;--warn-bg:#fdf0dc;--bad:#b0261e;--bad-bg:#fbe9e7;--ok:#1d7a4c;--accent:#14130f;--accent-fg:#fff;--shadow:0 1px 2px rgba(0,0,0,.05),0 6px 24px rgba(0,0,0,.05)}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#121211;--fg:#ebe9e3;--muted:#a19e95;--line:#2c2b28;--card:#1a1a18;--soft:#22221f;
--real:#5dcb92;--real-bg:#15301f;--sim:#8eaeff;--sim-bg:#18233d;--none:#97948b;--none-bg:#262622;--warn:#f1aa52;--warn-bg:#36280f;--bad:#ff8c82;--bad-bg:#3a1916;--ok:#5dcb92;--accent:#f4f2ec;--accent-fg:#121211;--shadow:none}}
:root[data-theme="dark"]{--bg:#121211;--fg:#ebe9e3;--muted:#a19e95;--line:#2c2b28;--card:#1a1a18;--soft:#22221f;
--real:#5dcb92;--real-bg:#15301f;--sim:#8eaeff;--sim-bg:#18233d;--none:#97948b;--none-bg:#262622;--warn:#f1aa52;--warn-bg:#36280f;--bad:#ff8c82;--bad-bg:#3a1916;--ok:#5dcb92;--accent:#f4f2ec;--accent-fg:#121211;--shadow:none}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 80px}
a{color:inherit;text-decoration-color:var(--line);text-underline-offset:3px}
a:hover{text-decoration-color:currentColor}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--soft);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
h1{font-size:30px;line-height:1.15;margin:6px 0 10px;letter-spacing:-.01em}
h2{font-size:21px;margin:56px 0 6px;letter-spacing:-.005em}
h2+p.lede{margin-top:0}
h3{font-size:15px;margin:0 0 4px}
.eyebrow{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.verdict{font-size:18px;line-height:1.45;margin:0 0 14px}
.lede{color:var(--muted);max-width:760px}
ul.hl{margin:0 0 16px;padding-left:20px}ul.hl li{margin:4px 0}
nav.toc{display:flex;flex-wrap:wrap;gap:6px;margin:18px 0 0}
nav.toc a{font-size:13px;padding:4px 10px;border:1px solid var(--line);border-radius:999px;text-decoration:none;background:var(--card)}
.chip{display:inline-flex;align-items:center;gap:5px;font:600 11px/1 ui-sans-serif,system-ui,sans-serif;padding:4px 7px;border-radius:999px;white-space:nowrap;vertical-align:middle;cursor:help}
.chip::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.chip.real{color:var(--real);background:var(--real-bg)}
.chip.sim{color:var(--sim);background:var(--sim-bg)}
.chip.none{color:var(--none);background:transparent;border:1px dashed var(--none)}
.chip.none::before{background:transparent;border:1px solid currentColor}
.legend{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:13px;color:var(--muted);margin:10px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}
.card .rank{font:700 12px/1 ui-monospace,monospace;color:var(--muted)}
.card h3 a{text-decoration:none}
.card p{margin:6px 0 8px;font-size:14px}
.card .path{font-size:11.5px;color:var(--muted);overflow-wrap:anywhere}
.caveat{font-size:12.5px;color:var(--muted);margin-top:10px}
figure{margin:16px 0}
figure video,figure img{width:100%;border-radius:12px;border:1px solid var(--line);display:block;background:#000}
figcaption{font-size:12.5px;color:var(--muted);margin-top:6px}
.timeline{list-style:none;padding:0;margin:14px 0 0;border-left:2px solid var(--line)}
.timeline li{position:relative;padding:0 0 14px 18px}
.timeline li::before{content:"";position:absolute;left:-6px;top:7px;width:10px;height:10px;border-radius:50%;background:var(--card);border:2px solid var(--muted)}
.timeline .d{font:600 12px/1.4 ui-monospace,monospace;color:var(--muted)}
.timeline q{font-size:16px;font-weight:600;quotes:"“" "”"}
.timeline .src{font-size:12px;color:var(--muted)}
.timeline .g{font-size:13.5px;color:var(--muted);display:block}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:12px}
.seen{font-size:11px;color:var(--muted);white-space:nowrap}
.unseen{font:700 11px/1 ui-sans-serif,system-ui;color:var(--warn);background:var(--warn-bg);padding:3px 6px;border-radius:5px;white-space:nowrap}
.dec{display:grid;grid-template-columns:110px 1fr;gap:4px 14px;margin-top:12px;font-size:14.5px}
.dec .w{color:var(--muted);font:600 12.5px/1.6 ui-monospace,monospace}
.q{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin-top:10px}
.q b{display:block}.q .ctx{font-size:13.5px;color:var(--muted);margin:2px 0 4px}.q .def{font-size:13.5px}
.stack{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-top:16px;align-items:stretch}
.stk{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;position:relative;font-size:12.5px}
.stk.real{border-color:var(--real)}.stk.sim{border-color:var(--sim)}.stk.none{border-style:dashed}
.stk h3{font-size:14px;margin:0}.stk .verb{font:600 11px/1.3 ui-monospace,monospace;color:var(--muted);margin:2px 0 6px}
.stk .where{font:11px/1.3 ui-monospace,monospace;color:var(--muted);margin-top:6px;overflow-wrap:anywhere}
.stk:not(:last-child)::after{content:"→";position:absolute;right:-9px;top:14px;color:var(--muted);font-size:13px}
@media (max-width:900px){.stack{grid-template-columns:1fr 1fr}.stk::after{display:none}}
@media (max-width:520px){.stack{grid-template-columns:1fr}}
ol.gaps{padding-left:0;list-style:none;counter-reset:g;margin-top:12px}
ol.gaps li{counter-increment:g;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px 12px 48px;margin-bottom:10px;position:relative}
ol.gaps li::before{content:counter(g);position:absolute;left:14px;top:12px;width:24px;height:24px;border-radius:50%;background:var(--accent);color:var(--accent-fg);font:700 12px/24px ui-sans-serif,system-ui;text-align:center}
ol.gaps .tag{font-size:12px;color:var(--muted)}
.why{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
@media (max-width:760px){.why{grid-template-columns:1fr}}
.filter{font-size:13px;color:var(--muted);display:flex;gap:8px;align-items:center;margin-top:10px}
footer{margin-top:60px;font-size:12.5px;color:var(--muted);border-top:1px solid var(--line);padding-top:14px}

/* ------------------------------------------------------------ the mock */
.mock{--m-bg:var(--card);background:var(--m-bg);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden;margin-top:16px}
.mock.hidebuilt .chip{display:none}
.mbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--soft)}
.mlogo{font:700 15px/1 ui-sans-serif,system-ui;letter-spacing:-.01em;margin-right:auto;display:flex;align-items:center;gap:8px}
.mlogo .dot{width:18px;height:18px;border-radius:5px;background:var(--accent);display:inline-block;position:relative}
.mlogo .dot::after{content:"";position:absolute;inset:5px;border-radius:50%;background:var(--bg)}
.mlogo span{font-weight:500;color:var(--muted)}
.mbar select{font:13px ui-sans-serif,system-ui;padding:5px 8px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);max-width:100%}
.mtoggle{font-size:12.5px;color:var(--muted);display:flex;gap:6px;align-items:center;cursor:pointer}
.msteps{display:flex;list-style:none;margin:0;padding:0 8px;border-bottom:1px solid var(--line);overflow-x:auto}
.msteps li{padding:11px 12px;font-size:13.5px;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;display:flex;gap:7px;align-items:center}
.msteps li .n{width:20px;height:20px;border-radius:50%;border:1px solid var(--line);display:inline-grid;place-items:center;font:600 11px/1 ui-sans-serif,system-ui}
.msteps li.on{color:var(--fg);border-bottom-color:var(--fg)}
.msteps li.on .n{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}
.msteps li.done .n{background:var(--real-bg);color:var(--real);border-color:var(--real)}
.mbody{padding:18px;min-height:470px}
.mpanel{display:none}.mpanel.on{display:block;animation:fade .25s ease}
@keyframes fade{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}
.mgrid{display:grid;grid-template-columns:1.1fr 1fr;gap:16px}
@media (max-width:820px){.mgrid{grid-template-columns:1fr}}
.mbox{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:var(--bg)}
.mbox h4{margin:0 0 8px;font-size:13px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.mrow{display:flex;gap:8px;align-items:center;justify-content:space-between;font-size:13px;padding:5px 0;border-bottom:1px dashed var(--line)}
.mrow:last-child{border-bottom:0}
.mtree{font:12.5px/1.65 ui-monospace,monospace}
.mtree .t{color:var(--muted)}
.mbtn{font:600 13.5px/1 ui-sans-serif,system-ui;padding:10px 16px;border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
.mbtn.primary{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}
.mbtn.big{font-size:16px;padding:14px 28px;border-radius:11px}
.mbtn:disabled{opacity:.45;cursor:default}
.mfoot{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-top:16px}
.mnote{font-size:12px;color:var(--muted)}
.dotl{width:9px;height:9px;border-radius:50%;background:var(--real);display:inline-block;margin-right:6px;box-shadow:0 0 0 3px var(--real-bg)}
.dotl.wait{background:transparent;border:1.5px solid var(--muted);box-shadow:none;animation:breathe 1s ease-in-out infinite}
@keyframes breathe{50%{opacity:.3}}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}
.seg button{font:600 12.5px/1 ui-sans-serif,system-ui;padding:8px 12px;border:0;background:var(--card);color:var(--muted);cursor:pointer}
.seg button.on{background:var(--accent);color:var(--accent-fg)}
.merr{display:none;margin-top:12px;border:1px solid var(--bad);background:var(--bad-bg);color:var(--bad);border-radius:10px;padding:10px 12px;font:12px/1.5 ui-monospace,monospace}
.merr.on{display:block}
.plan{margin-top:12px}
.prow{display:grid;grid-template-columns:22px 70px 1fr 70px;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line);font-size:13px}
.prow .k{font:600 10.5px/1 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.04em;padding:4px 6px;border-radius:5px;background:var(--soft);text-align:center}
.prow .t small{display:block;color:var(--muted);font-size:11.5px}
.prow .w{font:12px ui-monospace,monospace;color:var(--muted);text-align:right}
.prow .bar{grid-column:2/5;height:4px;border-radius:2px;background:var(--soft);overflow:hidden;display:none}
.prow .bar i{display:block;height:100%;width:0;background:var(--sim);transition:width .12s linear}
.prow.run .bar,.prow.ok .bar{display:block}
.prow.ok .bar i{background:var(--real)}
.prow .st{font-size:13px}
.prow.ghost{opacity:.75}
.prow.ghost .k{background:transparent;border:1px dashed var(--none)}
.clock{font:600 22px/1 ui-monospace,monospace;letter-spacing:-.02em}
.found{max-height:330px;overflow:auto;margin-top:8px}
.found table{font-size:12px}
.found td,.found th{padding:4px 6px}
.found tr.new{animation:flash 1s ease}
@keyframes flash{from{background:var(--real-bg)}to{background:transparent}}
.pass{color:var(--ok);font-weight:700}
.gates{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px}
@media (max-width:640px){.gates{grid-template-columns:1fr}}
.gate{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--bg)}
.gate .v{font:700 24px/1.1 ui-monospace,monospace;letter-spacing:-.02em}
.gate .r{font-size:12px;color:var(--muted)}
.gate.fail{border-color:var(--warn);background:var(--warn-bg)}
.gate.fail .v{color:var(--warn)}
.answer{font-size:22px;font-weight:700;letter-spacing:-.01em;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
details.params summary{cursor:pointer;font-size:13px;color:var(--muted);margin-top:14px}
"""

MOCK_HTML = r"""
<div class="mock" id="mock">
  <div class="mbar">
    <div class="mlogo"><i class="dot"></i>sim2real <span>Calibrate</span></div>
    <select id="m-robot" aria-label="Robot">
      <option>UR wrist test rig · CAN 14 / 15 / 16</option>
      <option disabled>1-DOF pendulum rack · no calibration record yet</option>
      <option disabled>bam_fb_v2 full arm · no calibrate() record yet</option>
    </select>
    <label class="mtoggle"><input type="checkbox" id="m-built" checked> show what's built</label>
  </div>
  <ol class="msteps" id="m-steps">
    <li data-step="0" class="on"><span class="n">1</span>Describe</li>
    <li data-step="1"><span class="n">2</span>Plug in</li>
    <li data-step="2"><span class="n">3</span>Calibrate</li>
    <li data-step="3"><span class="n">4</span>Twin</li>
  </ol>
  <div class="mbody">

    <section class="mpanel on" data-panel="0">
      <div class="mgrid">
        <div class="mbox">
          <h4>Robot description <span class="chip sim" title="sim2real loads the Cad2Robot MJCF bundle today (sysid/examples/ur_wrist_test_rig/description.json)">loads from CAD in sim2real</span>
            <span class="chip none" title="robot_description has no code: load(), to_robot_twin(), from_robot_twin() are not built">robot_description.load()</span></h4>
          <div class="mnote" id="m-bundle"></div>
          <div class="mtree" id="m-tree" style="margin-top:8px"></div>
        </div>
        <div class="mbox">
          <h4>Models and priors <span class="chip sim" title="one model rung per part; the record's model string">model rungs</span>
            <span class="chip none" title="robotparts docs/sim2real-types.md: the part → type mapping and datasheet priors are pending">Robot Parts datasheet priors</span></h4>
          <div id="m-models"></div>
          <div class="mnote" id="m-pcount" style="margin-top:10px"></div>
        </div>
      </div>
      <div class="mfoot"><span class="mnote">Every number in this mock is from the real UR-wrist sim record of 2026-11-12, unless a chip says otherwise.</span>
        <button class="mbtn primary" data-go="1">Next: plug it in →</button></div>
    </section>

    <section class="mpanel" data-panel="1">
      <div class="mgrid">
        <div class="mbox">
          <h4>RobotDx sees the hardware <span class="chip real" title="RobotDx (io-diagnostics) main: device tree, health, status dots — runs on the real rack">device health</span></h4>
          <div id="m-devices"></div>
        </div>
        <div class="mbox">
          <h4>Matches the description? <span class="chip none" title="nothing compares RobotDx's device tree with a robot description yet">not built</span></h4>
          <div id="m-match" class="mnote">Waiting for the scan…</div>
          <h4 style="margin-top:16px">If a board stops answering <span class="chip real" title="io-diagnostics docs/device-reset.md, RobotDx main; the power-cycle rung needs a PPPS hub">reset ladder</span></h4>
          <div class="mnote">reopen → the device's own reset → USB reset → deauthorize / reauthorize → port power cycle → page you</div>
        </div>
      </div>
      <div class="mfoot"><span class="mnote">Device rows here are illustrative; RobotDx's real tree shows firmware, voltage and faults per board.</span>
        <button class="mbtn primary" data-go="2" id="m-to-cal" disabled>Next: calibrate →</button></div>
    </section>

    <section class="mpanel" data-panel="2">
      <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between">
        <div class="seg" role="group" aria-label="Backend"><button class="on" data-on="sim">Sim · sealed truth</button><button data-on="real">Real rack</button></div>
        <div style="text-align:right"><div class="clock" id="m-clock">00:00</div><div class="mnote" id="m-clocknote"></div></div>
      </div>
      <div class="merr" id="m-err"></div>
      <div class="mgrid" style="margin-top:12px">
        <div>
          <div class="mnote" id="m-plansum"></div>
          <div class="plan" id="m-plan"></div>
        </div>
        <div class="mbox">
          <h4>Found so far <span class="chip sim" title="each routine's recovered values vs the sealed hidden truth, from the record">recovered vs sealed truth</span></h4>
          <div class="found"><table><thead><tr><th>parameter</th><th>truth</th><th>found</th><th>err</th><th></th></tr></thead><tbody id="m-found"></tbody></table></div>
          <div class="mnote" id="m-foundnote">Press Calibrate.</div>
        </div>
      </div>
      <div class="mfoot"><span class="mnote">Sped up — the real sim run took 28 min 42 s.</span>
        <button class="mbtn primary big" id="m-cal">Calibrate</button></div>
    </section>

    <section class="mpanel" data-panel="3">
      <div class="answer"><span id="m-answer">Twinned — in sim</span> <span class="chip sim" title="eval() on 16 held-out sim runs; gates from sim2real.cards.registry and Zach's 1 mm tool gate">eval()</span></div>
      <div class="gates" id="m-gates"></div>
      <h4 style="margin:22px 0 4px;font-size:14px">On the real rack today <span class="chip real" title="bam_ws reports/sim2real-morning-2026-11-12.html — scored by rack scripts, not by calibrate()">rack scripts, not calibrate()</span></h4>
      <div class="gates">
        <div class="gate"><div class="r">tool at settled stops · target vs real</div><div class="v">98/98</div><div class="r">≤ 1 mm, worst 0.86 mm · 6 wide tapes · 11-12</div></div>
        <div class="gate fail"><div class="r">twin · held-out sim vs real</div><div class="v">2.98×</div><div class="r">CAN 15 vs its repeat floor · gate ≤ 1.5× · not twinned</div></div>
        <div class="gate"><div class="r">what calibrate(on="real") would add</div><div class="v" style="font-size:16px">one record</div><div class="r">the same plan, fit and gates on rack runs instead of rack scripts</div></div>
      </div>
      <details class="params"><summary>All 42 parameters — 22 identified, 20 not identifiable with one joint moving at a time</summary>
        <div class="tablewrap"><table><thead><tr><th>parameter</th><th>prior</th><th>truth</th><th>found</th><th>routine / why not</th></tr></thead><tbody id="m-params"></tbody></table></div>
      </details>
      <div class="mfoot">
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          <button class="mbtn">Save record <span class="chip sim" title="fitted.record_ — sim2real.calibration/1">built</span></button>
          <button class="mbtn">Open W&amp;B · wrist rig <span class="chip real" title="W&B project 'Sim2Real · wrist rig' — one project per rig">built</span></button>
          <button class="mbtn">Write back to the description <span class="chip none" title="from_robot_twin() / Robot Parts measurements: not built">not built</span></button>
        </div>
        <button class="mbtn" data-go="0">Start over</button>
      </div>
    </section>
  </div>
</div>
"""

MOCK_JS = r"""
(function(){
const D = window.MOCK, $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const mock = $('#mock');
let step = 0, running = false, backend = 'sim';
const fmt = (v, unit) => {
  if (v === null || v === undefined) return '—';
  if (unit === 'rad') return (v*180/Math.PI).toFixed(3)+'°';
  const a = Math.abs(v); const s = a !== 0 && (a < 0.01 || a >= 1e4) ? v.toExponential(2) : (+v.toPrecision(4)).toString();
  return s + (unit ? ' '+unit.replace('kg·m²','kg·m²') : '');
};
const mmss = s => { s = Math.round(s); return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0'); };
function go(n){
  step = n;
  $$('#m-steps li').forEach((li,i)=>{li.classList.toggle('on', i===n); li.classList.toggle('done', i<n);});
  $$('.mpanel').forEach((p,i)=>p.classList.toggle('on', i===n));
  if (n === 1) scan();
}
$$('#m-steps li').forEach(li => li.addEventListener('click', () => { if (!running) go(+li.dataset.step); }));
$$('[data-go]').forEach(b => b.addEventListener('click', () => go(+b.dataset.go)));
$('#m-built').addEventListener('change', e => mock.classList.toggle('hidebuilt', !e.target.checked));

// 1 describe
$('#m-bundle').textContent = 'From CAD: ' + D.bundle;
const kids = id => D.components.filter(c => c.parent === id);
function tree(id, depth){
  const c = D.components.find(x => x.id === id); if (!c) return '';
  let s = '<div style="padding-left:'+(depth*14)+'px">'+(depth?'└ ':'')+'<b>'+c.id+'</b> <span class="t">'+c.type+' · '+c.title+'</span></div>';
  kids(id).forEach(k => s += tree(k.id, depth+1)); return s;
}
$('#m-tree').innerHTML = tree('rig', 0);
const per = {}; D.params.forEach(p => { const i = p.key.split('.')[0]; per[i] = per[i] || {n:0, id:0}; per[i].n++; if (p.pass !== null) per[i].id++; });
const rung = {can14:'servo M4.dynamics.twin', can15:'servo M4.dynamics.twin', can16:'servo M4.dynamics.twin', wrist:'chain M0.dynamics.rigid'};
$('#m-models').innerHTML = Object.keys(per).map(i => '<div class="mrow"><span><b>'+i+'</b> · '+(rung[i]||'')+'</span><span class="mnote">'+per[i].n+' parameters</span></div>').join('');
const nId = D.params.filter(p => p.pass !== null).length;
$('#m-pcount').textContent = D.params.length+' parameters · the plan can identify '+nId+' · '+(D.params.length-nId)+' stay at their prior, each with its reason. Model: '+D.model;

// 2 plug in (illustrative rows)
const devs = [['fdcanusb','rack bus adapter'],['CAN 14','moteus C1 · revolute_11'],['CAN 15','moteus C1 · revolute_14'],['CAN 16','moteus C1 · revolute_17']];
let scanned = false;
function scan(){
  if (scanned) return; scanned = true;
  const box = $('#m-devices'); box.innerHTML = devs.map((d,i)=>'<div class="mrow" id="dev'+i+'"><span><i class="dotl wait"></i><b>'+d[0]+'</b> <span class="mnote">'+d[1]+'</span></span><span class="mnote">looking…</span></div>').join('');
  devs.forEach((d,i)=> setTimeout(()=>{ const r = $('#dev'+i); r.querySelector('i').className='dotl'; r.lastChild.textContent = i ? 'answers · no faults' : 'connected'; if (i===devs.length-1){
    $('#m-match').innerHTML = '<div class="mrow"><span>servos named by the description</span><b class="pass">3 / 3</b></div><div class="mrow"><span>unexpected devices</span><b>0</b></div><div class="mrow"><span>ready to calibrate</span><b class="pass">yes</b></div>';
    $('#m-to-cal').disabled = false; } }, 350 + i*380));
}

// 3 calibrate
const T = D.totals;
$('#m-plansum').innerHTML = '<b>plan</b> (planner, recovery at 1×): '+D.steps.length+' routines · ≈'+Math.round(T.wall_time_s/60)+' min wall · '+Math.round(T.operator_time_s/60)+' min hands-on · $'+T.equipment_usd+' equipment <span class="chip sim" title="sim2real.calibration.plan(twin) — the planner\'s real output for this twin">planner</span>';
const ghost = [
  {kind:'tune', title:'PID gains with pidtuna (SIM → BENCH tiers)', note:'pidtuna runs on the real rack, but calibrate() doesn\'t call it yet', chip:'<span class="chip none" title="PEP 0001: the planner may call the PID tuner later; not registered as a routine">not in calibrate()</span>'},
  {kind:'measure', title:'eval() on '+D.eval_runs+' held-out runs', note:'gates: twinned, recovery, tool at stops', chip:'<span class="chip sim" title="fitted.eval()">sim</span>'}];
$('#m-plan').innerHTML = D.steps.map((s,i)=>'<div class="prow" id="pr'+i+'"><span class="st">'+(i+1)+'</span><span class="k">'+(s.kind==='identify'?'fit':s.kind)+'</span><span class="t">'+s.routine+'<small>'+s.title+' · '+s.setting+'</small></span><span class="w">'+mmss(s.wall)+'</span><span class="bar"><i></i></span></div>').join('')
 + ghost.map((g,i)=>'<div class="prow ghost" id="pg'+i+'"><span class="st">'+(D.steps.length+i+1)+'</span><span class="k">'+g.kind+'</span><span class="t">'+g.title+' '+g.chip+'<small>'+g.note+'</small></span><span class="w"></span><span class="bar"><i></i></span></div>').join('');
$('#m-clocknote').textContent = 'of ~'+mmss(D.seconds)+' (sim)';
$$('.seg button').forEach(b => b.addEventListener('click', () => {
  if (running) return; backend = b.dataset.on; $$('.seg button').forEach(x => x.classList.toggle('on', x===b));
  const e = $('#m-err');
  if (backend === 'real') { e.innerHTML = 'NotImplementedError: on=\'real\' is next: the rack path. CAN 11 plays the same schedule on the One Dof Test Rack (bam_rack_twin.schedule replay through bam_rack_twin.hardware, its torque cap and stops as the runner\'s guards) … Not wired in this lane.<br><span style="font-family:ui-sans-serif,system-ui">This is the real error <code>twin.calibrate(on="real")</code> raises today (src/sim2real/twin.py). <span class="chip none" title="the missing seam">not built</span></span>'; e.classList.add('on'); $('#m-cal').disabled = true; }
  else { e.classList.remove('on'); $('#m-cal').disabled = false; }
}));
const byRoutine = {}; D.ran.forEach(r => byRoutine[r.routine] = r);
const pByKey = {}; D.params.forEach(p => pByKey[p.key] = p);
$('#m-cal').addEventListener('click', () => {
  if (running) return; running = true; $('#m-cal').disabled = true; $('#m-found').innerHTML = ''; $('#m-foundnote').textContent = '';
  $$('.prow').forEach(r => { r.classList.remove('run','ok'); const i = r.querySelector('.bar i'); if (i) i.style.width = '0'; r.querySelector('.st').textContent = r.querySelector('.st').dataset.n || r.querySelector('.st').textContent; });
  const durs = D.steps.map(s => 600 + Math.sqrt(byRoutine[s.routine] ? byRoutine[s.routine].seconds : s.wall) * 55);
  const realTotal = D.steps.reduce((a,s)=>a+(byRoutine[s.routine]?byRoutine[s.routine].seconds:s.wall),0);
  let i = 0, simElapsed = 0;
  function runStep(){
    if (i >= D.steps.length) return finish();
    const s = D.steps[i], row = $('#pr'+i), bar = row.querySelector('.bar i'), st = row.querySelector('.st');
    st.dataset.n = st.dataset.n || st.textContent;
    row.classList.add('run'); const dur = durs[i], secs = byRoutine[s.routine] ? byRoutine[s.routine].seconds : s.wall, t0 = performance.now(), base = simElapsed;
    (function tick(now){
      const f = Math.min(1, (now - t0)/dur); bar.style.width = (f*100)+'%';
      $('#m-clock').textContent = mmss(base + f*secs);
      if (f < 1) return requestAnimationFrame(tick);
      simElapsed = base + secs; row.classList.remove('run'); row.classList.add('ok'); st.innerHTML = '<span class="pass">✓</span>';
      (byRoutine[s.routine] ? byRoutine[s.routine].identifies : []).forEach((k, j) => setTimeout(() => {
        const p = pByKey[k]; if (!p) return; const tr = document.createElement('tr'); tr.className = 'new';
        const err = (p.true && p.value !== null) ? ((p.value - p.true)/Math.abs(p.true)*100) : null;
        tr.innerHTML = '<td><code>'+k+'</code></td><td>'+fmt(p.true,p.unit)+'</td><td>'+fmt(p.value,p.unit)+'</td><td>'+(err===null?'—':(err>=0?'+':'')+err.toFixed(1)+'%')+'</td><td>'+(p.pass?'<span class="pass">✓</span>':'✗')+'</td>';
        $('#m-found').prepend(tr);
      }, j*70));
      i++; setTimeout(runStep, 160);
    })(t0);
  }
  function finish(){
    $('#pg1').classList.add('ok'); $('#pg1 .st').innerHTML = '<span class="pass">✓</span>'; $('#pg1 .bar i').style.width = '100%';
    $('#m-foundnote').textContent = nId+' / '+nId+' identified values inside their tolerance of the sealed truth.';
    setTimeout(() => { running = false; $('#m-cal').disabled = false; go(3); }, 1300);
  }
  runStep();
});

// 4 twin
$('#m-gates').innerHTML = D.gates.map(g => '<div class="gate'+(g.passed?'':' fail')+'"><div class="r">'+g.id+' · '+g.title+'</div><div class="v">'+(g.id==='twinned'?g.value+'×':g.value)+'</div><div class="r">gate '+g.rule+' · '+(g.passed?'<span class="pass">pass</span>':'fail')+'</div></div>').join('');
$('#m-params').innerHTML = D.params.map(p => '<tr><td><code>'+p.key+'</code></td><td>'+fmt(p.nominal,p.unit)+'</td><td>'+fmt(p.true,p.unit)+'</td><td>'+(p.value===null?'—':fmt(p.value,p.unit))+'</td><td class="mnote">'+(p.routine?p.routine+(p.pass?' <span class="pass">✓</span>':''):(p.why_not||'').slice(0,160))+'</td></tr>').join('');
window.mockGo = go;
})();
"""

PAGE_JS = r"""
(function(){
const cb = document.getElementById('only-unseen');
if (cb) cb.addEventListener('change', () => document.querySelectorAll('#all-reports tr[data-seen="1"]').forEach(r => r.style.display = cb.checked ? 'none' : ''));
})();
"""


def chip(status: str, label: str, title: str = "") -> str:
    return f'<span class="chip {status}" title="{esc(title)}">{esc(label)}</span>'


def build() -> str:
    data = mock_data()
    unseen = [r for r in REPORTS if r[4] is None]
    first = sorted([r for r in REPORTS if r[5]], key=lambda r: r[5])

    read_first = "".join(
        f'<div class="card"><div class="rank">#{r[5]} · {esc(r[0])} · {esc(r[1].split("/")[0])}</div>'
        f'<h3><a href="file:///home/bam/{esc(r[1])}">{esc(r[2])}</a></h3><p>{esc(r[3])}</p>'
        f'<div class="path">/home/bam/{esc(r[1])}</div></div>' for r in first)

    timeline = "".join(
        f'<li><span class="d">{esc(d)}</span> <span class="src">· {esc(src)}</span><br><q>{esc(quote)}</q>'
        f'<span class="g">{esc(gist)}</span></li>' for d, src, quote, gist in TIMELINE)

    decisions = "".join(f'<div class="w">{esc(w)}</div><div>{text}</div>' for w, text in DECISIONS)

    questions = "".join(
        f'<div class="q"><b>{esc(q)}</b><div class="ctx">{esc(ctx)}</div><div class="def">Taken: {esc(default)}</div></div>'
        for q, ctx, default in OPEN_QUESTIONS)

    status_label = {"real": "real rack", "sim": "sim only", "none": "not built"}
    stack = "".join(
        f'<div class="stk {s}"><h3>{esc(name)}</h3><div class="verb">{esc(verb)}</div>{chip(s, status_label[s])}'
        f'<div style="margin-top:6px">{esc(text)}</div><div class="where">{esc(where)}</div></div>'
        for name, verb, s, where, text in STACK)

    gaps = "".join(f'<li><b>{title}</b> <span class="tag">· {esc(tag)}</span><div>{text}</div></li>' for title, tag, text in GAPS)

    # unseen first (newest first), then seen (newest first)
    rows_sorted = sorted(REPORTS, key=lambda r: (r[4] is not None, [-int(x) for x in r[0].split("-")]))
    rows = "".join(
        f'<tr data-seen="{1 if r[4] else 0}"><td class="seen">{esc(r[0])}</td><td>{esc(r[1].split("/")[0])}</td>'
        f'<td><a href="file:///home/bam/{esc(r[1])}">{esc(r[2])}</a><div class="mnote">{esc(r[3])}</div></td>'
        f'<td>{"<span class=seen>opened " + esc(r[4]) + "</span>" if r[4] else "<span class=unseen>not opened</span>"}</td></tr>'
        for r in rows_sorted)

    n_all, n_unseen = len(REPORTS), len(unseen)
    mock_json = json.dumps(data).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>One-Click Calibration</title>
<meta name="description" content="Where Zach's one-click sim-to-real calibrate() stands on 2026-11-15: a clickable mock on real numbers, his thinking to date, decisions, the gap, and the reports he hasn't opened.">
<style>{CSS}</style></head>
<body><main>
<div class="eyebrow">sim2real · one-click calibration · 2026-11-15</div>
<h1>One-click calibration: where it stands</h1>
<p class="verdict"><b><code>.calibrate()</code> is already one call — in simulation. On real hardware it isn't wired:
<code>on="real"</code> still raises.</b> The pieces that would make it turnkey each run on their own, mostly not yet together.</p>
<ul class="hl">
<li><b>Sim:</b> <code>ur_wrist_test_rig().calibrate(on="sim")</code> plans 6 routines, recovers 22/22 hidden values and passes
3/3 gates (tool p95 0.046 mm) in 29 min, on sim2real main. The pendulum ran end to end on 11-11; the five-bar recovers 20–22 of its 22 values but fails the tool gate, on an unmerged lane.</li>
<li><b>Real:</b> PID tuna, homing, RobotDx's reset ladder and the rack's gate scoring all run on hardware — none is called by
<code>calibrate()</code>. The real tool already stops within 1 mm (wrist 98/98, READY 14/14); the real <i>twins</i> don't pass yet (wrist CAN 15 at 2.98× its floor).</li>
<li><b>You haven't opened {n_unseen} of the {n_all} reports on this</b> — the six that matter most are first below.</li>
</ul>
<nav class="toc"><a href="#first">Read first</a><a href="#mock-h">The mock</a><a href="#words">Your thinking</a><a href="#decided">Decided</a><a href="#open">Defaults taken</a><a href="#stack">The stack</a><a href="#gap">The gap</a><a href="#why">Why real is hard</a><a href="#all">All reports</a></nav>

<h2 id="first">Read these first — not opened yet</h2>
<p class="lede">Ranked by how much they change the picture of one-click calibration.</p>
<div class="cards">{read_first}</div>
<p class="caveat">“Opened” = visited in Chrome on this machine (local history, file:// pages under /home/bam only, checked 2026-11-15).
Reports you saw in the Claude app's side panel aren't counted, so “not opened” means “not opened in a browser”.</p>

<h2 id="mock-h">What one click should feel like</h2>
<p class="lede">A clickable mock of the PID-tuna-style flow: describe → plug in → calibrate → twin. It plays the real UR-wrist sim
record (sim2real <code>website/examples/ur_wrist_test_rig.out.json</code>, 2026-11-12) — the plan, the recovered values and the gates are
the code's own output. The chips say what exists today; untick “show what's built” to see the clean UI.</p>
<div class="legend">{chip("real", "runs on the real rack")} {chip("sim", "runs in sim only")} {chip("none", "not built")}</div>
<figure><video src="{MEDIA}/hero.mp4" autoplay muted loop playsinline controls poster="{MEDIA}/poster.jpg"></video>
<figcaption>The mock below, clicked through once (recorded from this page). No video? <a href="{MEDIA}/hero.gif">hero.gif</a></figcaption></figure>
{MOCK_HTML}

<h2 id="words">Your thinking, in your words</h2>
<p class="lede">The same idea, sharpening for a year: from “one click to sim” to “plug it in and it calibrates itself”. Quotes are verbatim from the notes named.
The fuller AI digest from Nov 4 is <a href="obsidian://open?vault=zach_brain&amp;file=Maps%20%26%20Views%2FMOC%2FMOC%20-%20Summary%20of%20Sim%20to%20Real%20Thinking%20To%20Date%20(Nov%204%202026)">MOC - Summary of Sim to Real Thinking To Date (Nov 4)</a>.</p>
<ol class="timeline">{timeline}</ol>

<h2 id="decided">What you've decided</h2>
<div class="dec">{decisions}</div>

<h2 id="open">Open questions — defaults taken</h2>
<p class="lede">You never ruled on these, so I took the default on each (Zach 2026-11-04: go with the default on easy-to-reverse things). Say the word and any one flips.</p>
{questions}

<h2 id="stack">The one-click chain today</h2>
<p class="lede">Left to right is what one click would run. Green runs on the real rack, blue in sim only, dashed isn't built.</p>
<div class="stack">{stack}</div>

<h2 id="gap">The gap to one real click</h2>
<p class="lede">In the order I'd close it. The first item is the only seam between “works in sim” and “works on the rack”; the rest make it turnkey.</p>
<ol class="gaps">{gaps}</ol>

<h2 id="why">Why the AI crushes digital and stalls on real</h2>
<div class="why">
<div class="card"><h3>It isn't intelligence — it's the loop</h3>
<p>In code the agent gets an exact, instant, free signal it can repeat a thousand times. On the rack every signal is slow (minutes),
costly (arm time is earned), noisy (the wrist's repeat floor is 0.09–0.24°), partly hidden and sometimes destructive (a trip, a
wedged fdcanusb that needs a 5 V cut).</p>
<p>This week's surprises were all hidden state: the C1 5 Hz ring was our own host relay (1.143° → 0.011° once off), the printed L2
was 1.5 % short with a 16 mm crank hub, and a 5.7 mm first-grasp offset is still unexplained. Each cost a night because nothing measured it first.</p></div>
<div class="card"><h3>So turnkey = make the real loop look digital</h3>
<p><b>Observable</b> — RobotDx says what's plugged in and healthy. <b>Recoverable without you</b> — the reset ladder and return-to-home.
<b>Predictable</b> — a twin inside 1.5× its floor, so most iterations run in sim or the cloud. <b>Graded by a ruler that can fail</b> —
sealed truths, held out from another day.</p>
<p>That is exactly the stack above. The button is about twenty lines once <code>on="real"</code> exists — don't build the GUI first.</p></div>
<div class="card"><h3>Wider view 1: zero clicks, not one</h3>
<p>A deployed robot shouldn't wait for a click. The same routines can re-run themselves when drift shows — PEP 0012's drift-only T10
routine and the lifelong-sysid branch are the start. One click is the commissioning case; zero clicks is the fleet case.</p></div>
<div class="card"><h3>Wider view 2: CAD isn't the truth, and “plug in” needs a kit</h3>
<p>Your CAD was off by a crank hub and 1.5 % on a link, so step one is “as-built” (the ArUco bundle-adjust routines already exist as a
type), not “load CAD”. And some routines need equipment — markers, a camera, a pendulum weight. The planner already prices operator
time and equipment $, so the click can say “attach the 10:1 pendulum” before it starts.</p></div>
</div>

<h2 id="all">All {n_all} reports on this</h2>
<label class="filter"><input type="checkbox" id="only-unseen"> show only the {n_unseen} not opened</label>
<div class="tablewrap"><table id="all-reports"><thead><tr><th>date</th><th>repo</th><th>report</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>

<footer>Built by <code>sim2real/docs/build_report_one_click_summary.py</code> (stdlib only) from the real UR-wrist record and the rig
description; hero video by <code>docs/record_one_click_summary_hero.py</code>. Sources: sim2real main @ e714741, bam_ws, io-diagnostics,
robotparts, the vault notes named above. Written by Claude Opus 5.5 (claude-opus-5-5) in Claude Code, 2026-11-15.</footer>
</main>
<script>window.MOCK = {mock_json};</script>
<script>{MOCK_JS}</script>
<script>{PAGE_JS}</script>
</body></html>
"""


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build())
    print(OUT, f"{OUT.stat().st_size / 1024:.0f} KB")
