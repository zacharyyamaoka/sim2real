"""Builds reports/pendulum-schedule-2026-11-17.html: gap F, the CAN 11 pendulum's calibrate() plays the schedule plan() shows.

    python3 /home/bam/sim2real/docs/build_report_pendulum_schedule.py

Reads the captures in reports/media/pendulum-schedule-2026-11-17/ (plan-before.txt, plan-after.txt, fast.txt, slow.txt), all real
terminal output from 2026-11-17, and writes one self-contained page. Stdlib only.
"""

from __future__ import annotations

import html
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "reports" / "media" / "pendulum-schedule-2026-11-17"
OUT = REPO / "reports" / "pendulum-schedule-2026-11-17.html"


def capture(name: str) -> str:
    path = MEDIA / name
    return html.escape(path.read_text(encoding="utf-8").rstrip()) if path.exists() else f"(missing capture: {html.escape(name)})"


CSS = """
:root { color-scheme: light dark; --bg:#fbfbf9; --ink:#141414; --muted:#6b6a66; --line:#e2e1da; --code:#f2f1ec; --good:#0a7d0a; --bad:#b42f2f; --accent:#2a6fd6; }
@media (prefers-color-scheme: dark) { :root { --bg:#141413; --ink:#ecebe6; --muted:#a19f98; --line:#33322e; --code:#1d1d1b; --good:#4cc04c; --bad:#ec6b6b; --accent:#6ea6ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 1.6rem; margin: 0 0 6px; } h2 { font-size: 1.15rem; margin: 34px 0 10px; border-top: 1px solid var(--line); padding-top: 20px; }
.lede { color: var(--muted); margin: 0 0 18px; }
.verdict { border-left: 4px solid var(--good); padding: 10px 14px; background: var(--code); border-radius: 6px; }
pre { background: var(--code); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; overflow-x: auto; font: 13px/1.45 ui-monospace, "SF Mono", Menlo, monospace; }
table { border-collapse: collapse; width: 100%; font-size: .95rem; } th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; } .good { color: var(--good); font-weight: 600; } .bad { color: var(--bad); font-weight: 600; }
.cols { display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; }
code { font-family: ui-monospace, Menlo, monospace; font-size: .92em; }
svg text { fill: var(--ink); font: 13px system-ui, sans-serif; } svg .box { fill: var(--code); stroke: var(--line); } svg .new { stroke: var(--accent); stroke-width: 2; }
svg .arrow { stroke: var(--muted); stroke-width: 1.5; fill: none; marker-end: url(#a); }
"""

SEAM = """
<svg viewBox="0 0 940 150" width="100%" role="img" aria-label="rd to RobotTwin to plan to calibrate to evaluate">
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>
<rect class="box" x="4" y="40" width="150" height="56" rx="8"/><text x="79" y="64" text-anchor="middle">rd</text><text x="79" y="82" text-anchor="middle">station_description(11)</text>
<rect class="box" x="190" y="40" width="160" height="56" rx="8"/><text x="270" y="64" text-anchor="middle">RobotTwin</text><text x="270" y="82" text-anchor="middle">.from_robot_description</text>
<rect class="box new" x="386" y="40" width="170" height="56" rx="8"/><text x="471" y="64" text-anchor="middle">plan(twin)</text><text x="471" y="82" text-anchor="middle">2 runnable routines</text>
<rect class="box new" x="592" y="40" width="160" height="56" rx="8"/><text x="672" y="64" text-anchor="middle">twin.calibrate()</text><text x="672" y="82" text-anchor="middle">plays exactly plan</text>
<rect class="box" x="788" y="40" width="148" height="56" rx="8"/><text x="862" y="64" text-anchor="middle">fitted.evaluate()</text><text x="862" y="82" text-anchor="middle">gates</text>
<path class="arrow" d="M154 68 H188"/><path class="arrow" d="M350 68 H384"/><path class="arrow" d="M556 68 H590"/><path class="arrow" d="M752 68 H786"/>
<text x="471" y="122" text-anchor="middle" fill="var(--accent)">new: sysid/examples/pendulum_can11/routines.py</text>
<text x="672" y="140" text-anchor="middle" fill="var(--accent)">fitted.plan_ is that CalibrationPlan</text>
</svg>
"""


def main() -> None:
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pendulum calibration schedule</title><style>{CSS}</style></head><body><main>
<h1>The pendulum's calibrate() plays the schedule it shows</h1>
<p class="lede">Gap F · sim2real main <code>23a176f</code> (ruler <code>f24952a</code> + <code>b481a90</code>) · 2026-11-17 · CAN 11 pendulum, in sim</p>
<div class="verdict"><b>Done and verified.</b> <code>plan(twin)</code> on the CAN 11 pendulum now lists only the two routines that can run
there, and <code>twin.calibrate()</code> plays exactly those, in that order. Recovery is unchanged: 8 of 8 hidden values, 3 of 3 gates, twin at
1.34× its floor.</div>

<h2>The seam you sketched, as it runs now</h2>
{SEAM}
<p>Your words: "robottwin.calibrate() internall mabye that does .generate_schedule() -&gt; CalibrationSchedule … a static description of the
routines that will be run". On the pendulum that static object is now real, and it is what runs.</p>

<h2>Before and after: <code>plan(pendulum_can11()).summary()</code></h2>
<div class="cols"><div><b class="bad">Before</b>: five catalog stand-ins, three needing a jig the rack doesn't have, and calibrate() ignored the list
<pre>{capture("plan-before.txt")}</pre></div>
<div><b class="good">After</b>: the two routines that recover CAN 11 in sim, each a step of the existing pipeline
<pre>{capture("plan-after.txt")}</pre></div></div>

<h2>End to end, in sim (description twin, 2 workers)</h2>
<table><tr><th></th><th>Before</th><th>After</th></tr>
<tr><td>Hidden values recovered</td><td>8 / 8</td><td class="good">8 / 8, same to 4 significant figures</td></tr>
<tr><td>Gates</td><td>3 / 3</td><td class="good">3 / 3</td></tr>
<tr><td>Twin ÷ floor (M4)</td><td>1.338×</td><td class="good">1.34×</td></tr>
<tr><td><code>calibrate()</code> time</td><td>1112 s</td><td>1073 s</td></tr>
<tr><td><code>fitted.plan_</code></td><td>a sysid list of model levels</td><td class="good">the <code>CalibrationPlan</code> plan() showed</td></tr>
<tr><td>Replay pools</td><td>capped in SimRunner only</td><td class="good">every pool checked at ≤ 2 workers by the ruler</td></tr>
</table>
<p>Before and after numbers are the builder's runs. The slow ruler test below is my own re-run on the landed commit.</p>

<h2>The ruler: <code>tests/test_pendulum_schedule.py</code></h2>
<p>Committed red before any code (2 of 4 fast checks failed, on exactly this gap). The builder never edited it.</p>
<pre>{capture("fast.txt")}</pre>
<pre>{capture("slow.txt")}</pre>

<h2>What changed</h2>
<pre>{capture("diffstat.txt")}</pre>
<ul>
<li><b>New</b> <code>sysid/examples/pendulum_can11/routines.py</code>: <code>servo.backlash_reversals_camera</code> (the gap from the train runs'
load reversals) then <code>servo.dynamics_regression</code> (the regression at that gap). Both are steps of the existing <code>pipeline.py</code>, not
re-derived.</li>
<li><b>Kept</b> the pendulum on <code>SimRunner</code>, not a <code>rig.py</code>. A rig would have refused <code>on="real"</code> and <code>models=</code>
and broken the one-click session's tests (its four points).</li>
<li><b>Refused by name</b> on the pendulum: <code>known</code>, <code>models</code>, <code>noise</code> and <code>seed</code> in a config. Exclude,
include and order work.</li>
</ul>

<h2>Left</h2>
<ul>
<li><b>The real path:</b> <code>on="real"</code> still runs the pipeline in one call and records a sysid plan. Moving it onto the same routines
changes the one-click session's <code>test_real_backend</code>, so that change is its call. (Closed 2026-11-18 by gap F-real: <code>on="real"</code>
plays the same routines through the same loop; docs/decision-real-backend-2026-11-15.md, amendment.)</li>
<li><b>Double-counted time:</b> the plan's 2744 s counts the shared train runs twice; the real wall time is about 1372 s.</li>
<li><b>The clamp-over-camera pick:</b> the planner's minimal cover still prefers an ungraded routine that covers more over a graded one that
covers less, for catalog-only planning.</li>
</ul>
</main></body></html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
