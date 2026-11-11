"""The one-click tracer report (2026-11-11): the types on the home page, and Twin.load -> simulate -> calibrate -> eval_twin on the
one-DOF pendulum oracle, green on the hidden truth and red on a moved one.

    python3 /home/bam/sim2real/docs/build_report_one_click.py

Stdlib only. Reads, never computes: the captures in reports/media/one-click-tracer-2026-11-11/ (the home and type-page screenshots, the
slow acceptance runs' terminal logs green.log / red.log and their summaries green.json / red.json, written by tests/test_one_click.py
with SIM2REAL_CAPTURE, the red-first log, suites.txt: each suite's own last lines before and after) and the API's source,
src/sim2real/twin.py. Writes reports/one-click-tracer-2026-11-11.html, a text page whose pictures are files beside it in
reports/media/ (gitignored), linked relatively.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "reports" / "media" / "one-click-tracer-2026-11-11"
REL = "media/one-click-tracer-2026-11-11"
OUT = REPO / "reports" / "one-click-tracer-2026-11-11.html"
TWIN = REPO / "src" / "sim2real" / "twin.py"


def e(text) -> str:
    return html.escape(str(text), quote=True)


def g(x, digits: int = 4) -> str:
    return "—" if x is None else f"{x:.{digits}g}"


def read(name: str) -> str:
    path = MEDIA / name
    return path.read_text(encoding="utf-8") if path.is_file() else f"(not captured: {name})"


def doc(name: str) -> dict | None:
    path = MEDIA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def log_lines(name: str) -> str:
    """A slow run's terminal output, the pytest progress dots and warnings summary dropped."""
    keep = [line for line in read(name).splitlines() if line.strip() and not re.fullmatch(r"[.sF]+\s*(\[\s*\d+%\])?", line.strip())]
    return "\n".join(keep)


def rows_table(run: dict | None) -> str:
    if run is None:
        return "<p class='mut'>Not captured yet.</p>"
    out = []
    for r in run["calibration"]["rows"]:
        err = None if r["recovered"] is None or r["true"] is None else r["recovered"] - r["true"]
        tol = r["tolerance"]
        tol_text = "—" if tol is None else (f"±{tol['value'] * 100:g} %" if tol["kind"] == "rel" else f"±{tol['value']:g}")
        rel = "" if err is None or not r["true"] else f"{100 * err / abs(r['true']):+.2f} %"
        moved = r["key"] in run["calibration"]["truth_moved"]
        out.append(f"<tr class='{'' if r['pass'] else 'bad'}'><th scope='row'><code>{e(r['key'])}</code>{' <span class=chip>moved in the world</span>' if moved else ''}</th>"
                   f"<td>{e(r['unit'])}</td><td>{g(r['nominal'])}</td><td>{g(r['true'])}</td><td><b>{g(r['recovered'])}</b></td>"
                   f"<td>{e(rel)}</td><td>{e(tol_text)}</td><td>{'pass' if r['pass'] else '<b>FAIL</b>'}</td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>parameter</th><th>unit</th><th>nominal (description)</th><th>hidden truth (world.json)</th>"
            "<th>recovered</th><th>error</th><th>tolerance</th><th>verdict</th></tr></thead><tbody>" + "".join(out) + "</tbody></table></div>")


def gates_table(run: dict | None) -> str:
    if run is None:
        return ""
    rep = run["report"]
    rows = "".join(f"<tr class='{'' if gt['passed'] else 'bad'}'><th scope='row'><code>{e(gt['id'])}</code></th><td>{e(gt['title'])}</td><td>{e(gt['value'])}</td>"
                   f"<td>{e(gt['rule'])}</td><td>{'pass' if gt['passed'] else '<b>FAIL</b>'}</td><td class='mut'>{e(gt['source'])}</td></tr>" for gt in rep["gates"])
    ratios = " · ".join(f"{e(k)} {g(v, 3)}×" for k, v in rep["ratios"].items())
    return (f"<p>Held-out link error ÷ floor ({e(rep['runs'])} runs, floor {g(rep['floor_mrad'], 3)} mrad): {ratios}. The selection rule picks "
            f"<b>{e(rep['selected'])}</b>.</p><div class='scroll'><table><thead><tr><th>gate</th><th>what</th><th>value</th><th>rule</th><th>verdict</th>"
            f"<th>from</th></tr></thead><tbody>{rows}</tbody></table></div>")


def same_as_oracle(run: dict | None) -> str:
    """The green run's recovered values beside sysid's committed result for the same example (python -m sysid run, held to the code by
    sysid/tests/test_oracle.py): the API adds no fitting of its own."""
    path = REPO / "sysid" / "results" / "pendulum_can11.json"
    if run is None or not path.is_file():
        return ""
    committed = {p["key"]: p["recovered"] for p in json.loads(path.read_text(encoding="utf-8"))["parameters"]}
    same = [r["key"] for r in run["calibration"]["rows"] if committed.get(r["key"]) == r["recovered"]]
    return (f"<p>{len(same)} of {len(run['calibration']['rows'])} recovered values equal sysid's committed <code>results/pendulum_can11.json</code> "
            "bit for bit: the Twin calls the oracle's own pipeline and adds no fitting of its own.</p>")


def twin_source() -> str:
    text = TWIN.read_text(encoding="utf-8")
    start = text.index("class Twin:")
    return text[start:]


def figure(name: str, caption: str, width: str = "100%") -> str:
    return (f"<figure><a href='{REL}/{name}'><img src='{REL}/{name}' alt='{e(caption)}' style='max-width:{width}' loading='lazy'></a>"
            f"<figcaption>{e(caption)}</figcaption></figure>")


def main() -> None:
    green, red = doc("green.json"), doc("red.json")
    gv = "PASS" if green and green["report"]["passed"] and green["calibration"]["passed"] else ("FAIL" if green else "not run")
    rv = "RED as it must be" if red and not red["report"]["passed"] and not red["calibration"]["passed"] else ("did not go red" if red else "not run")
    usage = '''import sim2real

twin = sim2real.Twin.load("pendulum_can11")          # typed instances, parameters as robot_msgs Values
twin.simulate()                                      # MuJoCo, headless
fitted = twin.calibrate(on="sim", truth="sealed")    # a NEW twin: values_, intervals_, rungs_, calibration_
fitted.eval_twin().summary()                         # held-out runs only: error / floor and the gates

# the level below: fitted.runner (SimRunner: plan -> RealWorld.measure -> identify (sealed) -> score -> assemble)
# the mutation test of the ruler: twin.calibrate(on="sim", truth="sealed", move_truth={"can11.gravity_nm": 5.555})
# twin.calibrate(on="real") -> NotImplementedError naming the rack path'''
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>One-click tracer</title>
<style>
:root {{ --bg:#fff; --bg2:#f5f6f7; --ink:#16181b; --ink3:#6a7079; --rule:#dcdfe3; --good:#1f7a3d; --bad:#b42318; --accent:#1d5fbf; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141619; --bg2:#1d2024; --ink:#e7e9ec; --ink3:#9aa1ab; --rule:#30343a; --good:#5cc27e; --bad:#ff7b6e; --accent:#7fb0ff; }} }}
body {{ background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, sans-serif; margin:0; }}
main {{ max-width:1100px; margin:0 auto; padding:20px 16px 60px; }}
h1 {{ font-size:24px; margin:8px 0 4px; }} h2 {{ margin-top:36px; border-bottom:1px solid var(--rule); padding-bottom:4px; }}
.verdict {{ font-size:17px; padding:10px 14px; border-left:4px solid var(--good); background:var(--bg2); }}
.mut {{ color:var(--ink3); }} code, pre {{ font-family: ui-monospace, monospace; font-size:12.5px; }}
pre {{ background:var(--bg2); border:1px solid var(--rule); padding:10px 12px; overflow:auto; max-height:560px; white-space:pre; }}
table {{ border-collapse:collapse; width:100%; font-size:13.5px; }} th, td {{ text-align:left; padding:5px 8px; border-bottom:1px solid var(--rule); vertical-align:top; }}
td {{ font-variant-numeric: tabular-nums; }} tr.bad td, tr.bad th {{ color:var(--bad); }}
.scroll {{ overflow-x:auto; }} .chip {{ font-size:11px; border:1px solid var(--bad); color:var(--bad); border-radius:3px; padding:0 4px; }}
figure {{ margin:10px 0; }} figure img {{ border:1px solid var(--rule); display:block; width:100%; height:auto; }} figcaption {{ color:var(--ink3); font-size:13px; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }} @media (max-width:760px) {{ .two {{ grid-template-columns:1fr; }} }}
ul li {{ margin:3px 0; }}
</style></head><body><main>
<h1>One-click tracer: types first, then Twin.load → simulate → calibrate → eval_twin</h1>
<p class="verdict"><b>The home opens on the 11 types, and the pendulum oracle runs end to end through four calls.</b> Green run: <b>{e(gv)}</b> (every hidden
value within its tolerance; the twin passes its gates). Truth moved 10 % on gravity: <b>{e(rv)}</b>. <code>on="real"</code> raises, naming the rack path.</p>

<h2>Part 1 · The types are the front door</h2>
<p>Before, the home opened on Deployments, Stations and Oracle examples, and <code>/models/</code>, <code>/routines/</code> and <code>/parameters/</code> had no
link on it. Now a Types section comes first, one tile per type in <code>cards.domain.TYPE_ORDER</code> (read from the data, so a new type shows up by itself),
and Models · Routines · Parameters lead the Choose column and the header. Why it fails and Analysis left the bar: five links overlapped the search at every width
from 768 to 1440 px (measured). They're still in the Account menu and on the home.</p>
<div class="two">{figure("home-before-1280.jpg", "Before: the home at 1280 px")}{figure("home-after-1280.jpg", "After: Types first; Models · Routines · Parameters in Choose and the header")}</div>
<div class="two">{figure("home-after-390.jpg", "After, at 390 px: no sideways scroll", "390px")}{figure("type-integrated_servo.jpg", "A type tile opens its ladder: /models/integrated_servo/")}</div>

<h2>Part 2 · The API</h2>
<pre>{e(usage)}</pre>
<p>This follows the API prior-art note's verdict (vault: <i>Sim2Real API Prior Art (2026-11-11)</i>):</p>
<ul><li><b>The verbs are on a sim2real <code>Twin</code>, not on the description.</b> The description lives in robot_description, below sim2real, so verbs on it would bring back the cycle.</li>
<li><b><code>calibrate()</code> returns a new fitted twin</b> (scikit-learn style): learned values end in <code>_</code>, and nothing is written to robotparts.</li>
<li><b><code>eval_twin()</code> refuses a training run.</b> Identification runs sealed from the truth, and both guards live in the runner.</li>
<li><b>The fitting is sysid's existing oracle code, not <code>mujoco.sysid</code>.</b> The pendulum's twin is bam_rack_twin's 30 kHz moteus PID with a gear-gap hinge (its Replayer), not a plain MJCF rollout. <code>mujoco.sysid</code> is in the pinned 3.11.0, but its extra's packages (colorama…) aren't installed. It's <code>fit/</code>'s engine for a type whose twin is plain MJCF.</li></ul>

<h2>The four calls, end to end (green)</h2>
<p class="mut">The slow acceptance test's own terminal output: <code>SIM2REAL_SLOW=1 pytest -s tests/test_one_click.py -k recovers_the_hidden_truth</code></p>
<pre>{e(log_lines("green.log"))}</pre>
<h3>Recovered vs hidden</h3>{rows_table(green)}{same_as_oracle(green)}
<h3>eval_twin's gates</h3>{gates_table(green)}

<h2>The red run: truth moved past its tolerance</h2>
<p>The world plays gravity at 5.555 N·m, 10 % above the committed 5.05 and five times its 2 % tolerance. The ruler stays <code>world.json</code>'s.
The fit recovers what the world played (gravity about 5.57), so the recovery gate goes red and names the parameter.</p>
<p>The twinned gate also went red: the M4 twin fitted on the moved world reached 2.14× the floor on held-out runs, over the 1.5× limit.
The test's first form guessed that only recovery would fail, and the first run proved that wrong. Now it asserts that recovery is <i>among</i> the red gates.</p>
<pre>{e(log_lines("red.log"))}</pre>
{rows_table(red)}{gates_table(red)}

<h2>Red first</h2><p class="mut">The acceptance tests before <code>sim2real.load</code> existed (their first form, before the move onto <code>Twin</code>):</p>
<pre>{e(read("red-first.log"))}</pre>
<h2>Suites before → after</h2><pre>{e(read("suites.txt"))}</pre>

<h2>What robot_description would need (a proposal; its contract is untouched here)</h2>
<ul><li><b>A typed instance element.</b> Each component needs a name, its sim2real type id as a plain string, a parent, binds (joint, link) and
<code>parameters: Mapping[str, robot_msgs.space.Value]</code>. Today <code>Actuator</code> and <code>Sensor</code> carry <code>tags: tuple[tuple[str, str], ...]</code>,
which hold strings, not Values with a unit and source.</li>
<li><b>A description of the station itself.</b> The One Dof Test Rack's CAN 11 hinge and plate link aren't in it today (<code>build_payload</code> is the FB payload).
The tracer's model is bam_rack_twin's MJCF, named by sysid's manifest.</li>
<li><b>A lowering that applies typed values.</b> MJCF <code>armature</code>, <code>damping</code> and <code>frictionloss</code> should come from the instance's
parameter Values, so a calibrated parameter set produces the twin's model.</li>
<li><b>Until then</b>, <code>sim2real.describe()</code> is the thin adapter: it reads the sysid manifest and returns typed instances.</li>
<li><b>A contract gap, for the type card.</b> <code>integrated_servo</code> has no parameter named <code>gravity_bottom_rad</code> or <code>friction_stribeck_speed_rad_s</code>.
The oracle recovers both, and <code>Instance.on_type</code> carries and flags them.</li></ul>

<h2>Next for <code>on="real"</code></h2>
<ul><li>Play the same schedule on CAN 11 through bam_rack_twin.hardware. Its torque cap and stops are the runner's guards, never callbacks.</li>
<li>Read the runs back through <code>tools/run_files.py</code> as robot_msgs <code>JointTrajectory</code>, then fit with the same <code>identify</code>.</li>
<li>Score held-out runs against the rack's own run-to-run floor (gate T1), not two camera draws.</li>
<li>Bind with <code>binding=</code>: the description stays address-free, and CAN ids and bus serials come from the deployment record.</li></ul>

<h2>The Twin's code</h2><p class="mut"><code>src/sim2real/twin.py</code>, from <code>class Twin</code> on:</p><pre>{e(twin_source())}</pre>
</main></body></html>"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
