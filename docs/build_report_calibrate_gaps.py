"""Builds reports/calibrate-gaps-2026-11-19.html: the calibrate-gaps run of 2026-11-18/19 (lanes L1-L10), as handed over to Zach.

    python3 /home/bam/sim2real/docs/build_report_calibrate_gaps.py

Stdlib only. Every number on the page comes from a capture in reports/media/calibrate-gaps-2026-11-19/ (gitignored):
- cloud_cited.json      the summary.json of each cited cloud dispatch (bam_ws reports/media/cloud/s2r-*/<run>/out/summary.json),
                        trimmed to sim2real sha, exit, venv, slow flag and per-file pass/fail/skip/error counts
- git_log.txt           `git log --oneline --reverse 7526705..origin/main` (the pushed head is 713da7a)
- l10_log.txt           `git log --oneline --reverse origin/main..claude/l10-c` (not landed)
- ff_ladder.json        sysid/results/routine_ladders/arm.feedforward_bench.json as committed (817ff5b)
- ff_perf.txt           the PERF lines of the FF-2 probe d07280523 (feedback share, tracking RMS in rad)
- pid_probe_ladder.json the L10 grade probe's VM-written ladder (d14162546, throwaway branch, never lands)
- d19420510_ledger.json the dispatch ledger row of the L10 grade that never started a worker
- plan_s5_s6.md         sections 5 and 6 of the integrated plan (the defaults taken, feedforward status)
- journal_wf*.txt       the workflow journals, one block per agent result (the prose below is written from these)
A commit or dispatch the captures don't hold renders as "not captured"; nothing is typed in by hand.
"""

from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "reports" / "media" / "calibrate-gaps-2026-11-19"
OUT = REPO / "reports" / "calibrate-gaps-2026-11-19.html"
DEG = 180.0 / math.pi


def _load(name: str):
    return json.loads((MEDIA / name).read_text(encoding="utf-8"))


CLOUD = _load("cloud_cited.json")
LADDER = _load("ff_ladder.json")
PID_PROBE = _load("pid_probe_ladder.json")


def _subjects() -> dict[str, str]:
    out = {}
    for name in ("git_log.txt", "l10_log.txt"):
        for line in (MEDIA / name).read_text(encoding="utf-8").splitlines():
            sha, _, subject = line.partition(" ")
            out[sha] = subject
    return out


SUBJECTS = _subjects()
e = html.escape


# --------------------------------------------------------------------------------------------------------------------------- helpers

def commit(sha: str) -> str:
    """One commit: its short sha and the first clause of its subject (full subject on hover); 'not captured' if git didn't list it."""
    subject = SUBJECTS.get(sha)
    if subject is None:
        return f"<li><code>{e(sha)}</code> <span class='bad'>not captured</span></li>"
    short = subject if len(subject) <= 96 else subject[:95].rstrip() + "…"
    return f"<li><code>{e(sha)}</code> <span class='muted' title='{e(subject)}'>{e(short)}</span></li>"


def _counts(f: dict, slow: bool) -> str:
    bits = [f"{f['passed']} passed"]
    if f["failed"]:
        bits.append(f"<span class='bad'>{f['failed']} failed</span>")
    if f["skipped"]:
        bits.append(f"{f['skipped']} skipped")
    if f["errors"]:
        bits.append(f"<span class='bad'>{f['errors']} errors</span>")
    text = " · ".join(bits)
    if slow and f.get("seconds"):
        s = float(f["seconds"])
        text += f" <span class='muted'>({s / 60:.0f} min)</span>" if s >= 120 else f" <span class='muted'>({s:.0f} s)</span>"
    return text


def run(dispatch: str, tier: str, note: str = "", rulers: tuple[str, ...] = ()) -> str:
    """A cloud dispatch as the summary.json files say it ran: venv, sim2real sha, VMs, exit, and each file's counts."""
    entries = CLOUD.get(dispatch)
    if not entries:
        return f"<div class='run'><div class='runhead'><code>{e(dispatch)}</code> · {e(tier)} · <span class='bad'>not captured</span></div></div>"
    venv = "rack venv" if entries[0].get("require_rack") == "1" else "sim2real's own venv"
    shas = sorted({x.get("sim2real") or "?" for x in entries})
    slow = any(x.get("slow") == "1" for x in entries)
    exits = [x.get("exit") for x in entries]
    green = all(x == 0 for x in exits)
    missing = sum(int(x.get("archive_missing") or 0) for x in entries)
    files = [f for x in entries for f in x["files"]]
    files.sort(key=lambda f: f["file"])
    items = []
    for f in files:
        name = f["file"].removeprefix("tests/").removesuffix(".py").replace(".py::", "::")
        cls = " class='badrow'" if (f["failed"] or f["errors"]) else ""
        items.append(f"<li{cls}><code>{e(name)}</code> {_counts(f, slow)}</li>")
    verdict = "<span class='good'>exit 0</span>" if green else f"<span class='bad'>exit {e(', '.join(str(x) for x in exits))}</span>"
    vms = f"{len(entries)} VM" + ("s" if len(entries) > 1 else "")
    head = (f"<code>{e(dispatch)}</code> · {e(tier)} · {venv} · sim2real <code>{e(', '.join(shas))}</code> · {vms} · {verdict}"
            + (f" · <span class='bad'>{missing} /archive files missing</span>" if missing else ""))
    total = {k: sum(int(f[k]) for f in files) for k in ("passed", "failed", "skipped", "errors")}
    tally = f"{len(files)} file" + ("s" if len(files) != 1 else "") + ": " + _counts(total, False)
    if len(files) == 1 and slow:
        tally = _counts(files[0], True)
    elif not slow:  # WHY: lead with the gap's own ruler, so a VM-environment red elsewhere in the run never hides the verdict that matters
        lead = [f"ruler <code>{e(f['file'].removeprefix('tests/').removesuffix('.py'))}</code> {_counts(f, slow)}" for f in files
                if f["file"].split("::")[0].removeprefix("tests/").removesuffix(".py") in rulers]
        if lead:
            tally = " · ".join(lead) + f" <span class='muted'>· all {tally}</span>"
    note_html = f"<p class='note'>{note}</p>" if note else ""
    return (f"<div class='run'><div class='runhead'>{head}</div><details><summary class='tally'>{tally}</summary>"
            f"<ul class='files'>{''.join(items)}</ul></details>{note_html}</div>")


def none_run(tier: str, why: str) -> str:
    return f"<div class='run'><div class='runhead'>{e(tier)} · <span class='muted'>{why}</span></div></div>"


# --------------------------------------------------------------------------------------------------------------------------- the gaps
# Prose is written from the workflow journals (builder, reviewer and lander results); counts come from cloud_cited.json.

GAPS = [
    dict(key="A1", lane="L1", title="CalibrationSchedule: a static view with typed commands", landed=True,
         changed=[
             "<code>CalibrationSchedule</code> is the class (<code>CalibrationPlan</code> stays as an alias). <code>twin.generate_schedule(config)</code> "
             "is <code>plan(twin, config)</code>, and the tracer's <code>calibrate()</code> plays it.",
             "<code>Run(id, split, spec, seconds, command)</code>: a run carries its robot_msgs <code>JointTrajectory</code> or "
             "<code>JointCommandSequence</code> and its length; anything else is refused by name. The pendulum's train run carries its real 771.8 s.",
             "Each step says whether its commands are <b>known now</b> or <b>made after</b> an earlier step, from what it declares it reads, never "
             "by probing. A known-now step whose runs changed by play time is refused before anything plays."],
         ruler="tests/test_calibration_schedule.py", commits=["3d1818a", "c42bb22", "6b0a2b9"],
         runs=[("d02243729", "fast", "The reds are the VM, not the lane: 4 wrist tests need a scene.xml no VM had, and the docs-site tests need "
                "<code>website/site</code>, which the cut left out. Main 24d4d3b fails the same way (d02291563). The harness fix "
                "<code>be55ede05</code> made both green from then on (d04021010)."),
               ("d02394624", "slow", "The whole CAN 11 calibration plays the bound schedule end to end."),
               ("d04021010", "fast", "Harness proof after <code>be55ede05</code>: the wrist and docs-site files that were red only on the VM.")],
         note="<code>6b0a2b9</code> changes one line of the decision record after the cloud run at <code>c42bb22</code>."),
    dict(key="F-real", lane="L2", title="on=\"real\" plays the schedule's routines", landed=True,
         changed=[
             "<code>calibrate(on=\"real\")</code> plays <code>plan(twin)</code>'s routines through the same loop the sim uses "
             "(<code>twin._play_routines</code>), over the train runs the rack sent back.",
             "Its record names the planner's schedule (source <code>\"planner\"</code>), not sysid's M0–M4 list. <code>from_sysid</code> is gone; "
             "old records still load.",
             "Pre-flight: a known-now run the submission can't fill is refused before anything is emitted.",
             "Honest limit: what the rack <i>plays</i> is still the sysid pipeline's schedule. Typed collection on the rack is a later leg."],
         ruler="tests/test_real_plays_schedule.py, plus R1 in tests/test_real_backend.py", commits=["72f2f48", "dc3aae7", "aad097f"],
         runs=[("d03203316", "fast", "On the landed head. The 4 wrist failures and the docs-site error are the VM environment, the same on "
                "main 24d4d3b (d02291563)."),
               ("d02280344", "slow", "At <code>fb4a175</code>, before the rebase onto L1. That rebase's only conflict was one docs row.")]),
    dict(key="T", lane="L3", title="totals count a shared run once", landed=True,
         changed=[
             "<code>totals[\"wall_time_s\"]</code> counts a run two steps share once, using <code>Run.robot_seconds()</code>. New: "
             "<code>totals[\"run_time_s\"]</code>.",
             "CAN 11's two steps now total 1972 s (the 771.8 s train run once, plus 600 s per step). The old plan said 2744 s.",
             "Two lengths for one run id are refused by name. A step whose runs need an earlier fit keeps its whole time and says \"counted whole\".",
             "Review fix: a run id shared by a known-now and a made-after step stays refused unless the run has neither a command nor a spec."],
         ruler="tests/test_plan_totals_shared_runs.py", commits=["3a08f49", "7e462f3", "f6af98a"],
         runs=[("d04490454", "fast", ""), ("d04501288", "slow", "")]),
    dict(key="FF-1", lane="L4", title="the bench feedforward routine arm.feedforward_bench", landed=True,
         changed=[
             "New routine <code>FeedforwardBench</code> (<code>arm.feedforward_bench</code>): one robot_trajectories "
             "<code>trapezoidal_velocity(..., back_to_start=True)</code> out-and-back move per cell, with the current feedforward in its command.",
             "New fit <code>sim2real.fit.feedforward</code>: gravity from the twin's regressor plus Coulomb and net viscous friction per drive, "
             "on moving rows only. The way back cancels friction. A run without both directions over the same poses is refused by name. The "
             "residual is held out one cell at a time.",
             "Catalog row (identifies link inertials, refines drive friction), <code>metrics.actuator.feedback_share</code>, a decision record, "
             "<code>docs/feedforward-flow.svg</code>, and a <code>trajectories</code> extra in pyproject.",
             "Review fix: it declares <code>commands_read</code>. After a step that finds friction it now shows \"made after\" instead of being "
             "refused at play."],
         ruler="tests/test_feedforward_bench.py and tests/feedforward_toy.py", commits=["084ca89", "3cecf0b", "3a8b678", "3369c0c", "ee7c4cd"],
         runs=[("d04412493", "ruler alone, red first", "Every failure is a missing name; no fixture error."),
               ("d05312231", "fast", "On the landed head. The 10 <code>type_cards/tests</code> failures are the set main aad097f fails "
                "(d04304159). The one <code>test_plan_totals_shared_runs</code> failure is no MuJoCo in this venv; it passes in the rack venv."),
               ("d05301716", "fast", "On the landed head."),
               ("d04564072", "probe", "The review fix, on a throwaway commit that never lands: a two-step rig shows the routine \"made after\" and "
                "plays; a negative control without the declaration is refused.")],
         slow="none: FF-1 has no slow tier"),
    dict(key="A2", lane="L5", title="rounds: collect, fit, come back for more", landed=True,
         changed=[
             "A routine can iterate: <code>max_rounds</code>, <code>next_runs(values, history)</code>, <code>converged(history, values)</code>. "
             "Each round's new runs are measured once, and the fit sees every run so far.",
             "Stop order: the routine's own rule, else every 95 % interval inside its tolerance (never the hidden truth), else <code>max_rounds</code>, "
             "else nothing left to collect. Step rows record <code>rounds</code>, <code>converged</code> and <code>stopped</code>; the schedule "
             "says \"up to N rounds\".",
             "Refused at plan time: an iterating routine with no cap, and a tune with no stop rule of its own. The tracer and the rack path "
             "refuse iterating routines by name for now.",
             "Review fix: <code>collect()</code> fits an iterating step's inputs as it goes, so a replay rebuilds each round with the command it "
             "recorded."],
         ruler="tests/test_calibration_rounds.py", commits=["908ec84", "65c3419", "723824f"],
         runs=[("d06122565", "fast", "On the landed head."),
               ("d06134462", "probe, old head", "Throwaway probe of the review finding: collect recorded <code>trim/r1</code> at −0.196 where "
                "calibrate builds −0.393."),
               ("d06132788", "probe, fixed head", "The same probe green on the fix, with the ruler and its sim2real-venv neighbours. Never committed.")],
         slow="none required. The one informational wrist run (d05540530) failed in 2 s on a harness gap, bam_ur_wrist_coverage missing "
              "from the rack cut, before any routine ran"),
    dict(key="B", lane="L6", title="equipment you have, and the gates before ranking", landed=True,
         changed=[
             "<code>Budget(equipment=(...))</code>: the equipment you have or can borrow. An id the catalog doesn't know is refused.",
             "Gates before ranking, in order: exclude → not implemented → setting → equipment → recovery at your noise level → known. Each "
             "drop is named, e.g. \"needs output_clamp ($150), which Budget.equipment does not list\". The recovery gate applies to catalog "
             "fits only, never to a rig's own routines.",
             "<code>include</code> naming a routine a gate drops is refused. New <code>totals[\"equipment_to_buy_usd\"]</code>, which the money "
             "cap and strict mode now limit.",
             "The why text says \"ranked ahead of\" only about routines that really rank worse. Catalog plans change on purpose: fits that fail "
             "recovery now read \"recovery at 1x fails\"."],
         ruler="tests/test_calibration_gates.py", commits=["d0b8483", "68a75dd"],
         runs=[("d06383237", "fast", "Two of three VMs. The third had no libEGL and ran nothing, so its files ran again in d07084066."),
               ("d07084066", "fast", "The pendulum gate test ran (13 passed, 0 skipped)."),
               ("d06392962", "fast", "The one skip is the pendulum test, which needs the rack venv.")],
         slow="none: the gates ruler has no slow test"),
    dict(key="D", lane="L7", title="the twin holds its data", landed=True,
         changed=[
             "Every fitted twin carries <code>fitted.data_</code>: the very runs its fit read, as <code>CalibrationData</code> with held-out "
             "runs and sessions.",
             "<code>calibrate(data=...)</code> refits without measuring, on sim and on the rack (<code>on=\"real\", data=</code> uses no rack time). "
             "Data from the other backend or another twin is refused, and so is <code>move_truth</code> with data.",
             "Data grows by session (<code>a + b</code>). A run recorded again is kept as <code>key@session</code> and answers the same run id.",
             "Review fix: a session id now hashes routine options and the world that played. A different dataset claiming an existing "
             "session is refused instead of silently dropped. The rack session is the submission folder's full path."],
         ruler="tests/test_twin_holds_data.py, plus R2 in tests/test_real_backend.py", commits=["f7328db", "e79c4a2", "d61542d", "f3f6f22"],
         runs=[("d10202764", "fast", "On the landed head, after the rebase onto L6: all 17 files pass."),
               ("d10212869", "fast", "On the landed head. The 5 skips are 3 pendulum tests that need the rack venv and 2 slow ones."),
               ("d09074898", "slow", "At <code>b257f32</code>, before the conflict-free rebase onto L6. Not re-run after it.")]),
    dict(key="FF-2", lane="L8", title="feedforward rounds and the committed ladder", landed=True,
         changed=[
             "<code>FeedforwardBench</code> iterates on A2's rounds. Round 1 is the slow band. Each later round collects the empty cells, then "
             "the cells whose held-out residual is over tolerance, worst first, as fresh runs carrying the last fit's feedforward.",
             "It converges when gravity moves less than <code>delta_nm</code> between rounds, the worst held-out cell is within tolerance and no "
             "cell is empty. It stops \"no improvement\" only when it is over tolerance with every cell collected. When every cell fits but ΔG "
             "hasn't been read yet, it re-collects the worst cells instead of stopping unconverged.",
             "Bench row rules for a board's PD: a moving row is |qd| ≥ 0.1 rad/s (5.7°/s), and the two legs pair within 0.05 rad (2.9°).",
             "Review fix: on a dataset grown by session, <code>X</code> and <code>X@session</code> are one run in one cell, so a refit finds its "
             "round fits and holds out both recordings together.",
             "The committed hidden-truth ladder: see the feedforward section."],
         ruler="tests/test_feedforward_rounds.py, plus the toy fix cda06cd",
         commits=["7a75162", "52a1eb3", "8af4b3d", "8b1d8bc", "fb2b298", "cda06cd", "fa45563", "72e200f", "b1ed2d7", "817ff5b"],
         runs=[("d13321145", "fast", "On the landed head. The committed-ladder check passes."),
               ("d13323990", "fast", "On the landed head."),
               ("d13124016", "slow, writes the ladder", "At <code>ced28f3</code> (now <code>b1ed2d7</code>). The ladder it wrote is "
                "<code>817ff5b</code>."),
               ("d13175137", "slow, checks the ladder", "At <code>ac9e3b4</code>, without WRITE: the run matched the committed ladder level "
                "by level. <code>ac9e3b4</code> → <code>817ff5b</code> is the rebase onto L9. Outside the docs it differs by exactly L9's diff, "
                "and the ladder hashes only the two feedforward modules.")]),
    dict(key="E", lane="L9", title="watching a calibration live", landed=True,
         changed=[
             "<code>calibrate(callbacks=...)</code> reports the schedule, each step as it finishes (round, found values, timings), done, "
             "error or pending, and evaluate. A hook that raises is detached with one warning.",
             "<code>Ledger</code> writes <code>events.jsonl</code>, <code>schedule.json</code>, <code>calibration.json</code> and "
             "<code>eval.json</code> locally. Defaults: sim writes nothing; a rack calibration keeps a ledger in its submission folder; a refit "
             "writes nothing. <code>SIM2REAL_TRACK=off|ledger|wandb</code> overrides.",
             "<code>sim2real.tracking.calibrate_wandb</code>: W&amp;B as a copy of the ledger (angles in degrees; before/after in the trend "
             "names), a <code>--follow</code> live copy and a <code>--sync</code> replay. The copy never gets ahead of its ledger, even when the "
             "ledger dies mid-run.",
             "bam_ws: the three sim2real W&amp;B tracker records name their ledger (<code>ff21b7032</code>, on bam_ws origin/main)."],
         ruler="tests/test_calibrate_tracking.py, plus R3 in tests/conftest.py",
         commits=["008caa9", "80813cf", "a72bf75", "d607380", "9b38cc2", "5d7ec2a"],
         runs=[("d12525720", "fast", "On the landed head. The one non-slow skip checks the bam_ws tracker registry, which the cut doesn't carry."),
               ("d12535254", "fast", "On the landed head."),
               ("d12541672", "slow", "W&amp;B offline: the live-copy test wrote a real wandb run."),
               ("d11484463", "slow", "At <code>d607380</code>. After it, <code>9b38cc2</code> is whitespace only and <code>5d7ec2a</code> touches "
                "only callbacks.py, calibrate_wandb.py and the docs.")]),
    dict(key="C", lane="L10", title="PID tuna as a tune routine", landed=True,
         changed=[
             "<code>pid.pidtuna</code> becomes a <b>tune</b> step. It configures the servo's kp/kd, needs the fitted inertia and friction, and "
             "uses no robot time. Its outputs are settings (<code>fitted.settings_</code>, <code>proposals_</code>), never fitted values.",
             "<code>PidTune</code> wraps pidtuna v2 with the integrator off (PD + FF), its pool capped at the twin's workers. The CAN 11 pendulum "
             "runs it as the third step.",
             "Review fixes on the branch: the proposal is written against the board as it runs, so applying it sets <code>ilimit: 0</code> (PD, not "
             "PID). A rig twin's <code>values_</code> now shows a known key at its known number.",
             "<b>Landed Nov 21</b> at sim2real <code>02d1034</code>, pushed. <code>on=\"real\"</code> takes "
             "<code>CalibrationConfig(exclude=(\"pid.pidtuna\",))</code> and refuses any other config; a tune that fails after the rack played "
             "is a stopped step and the paid-for fits are kept (<code>5355ff6</code>, pinned by <code>tests/test_pid_tune_real_path.py</code>).",
             "<b>The grade, after pidtuna's damping-band rule</b> (pidtuna <code>85495d4</code>, never deliver outside the caller's band): PID "
             "Tuna's owner ruled the band stays, so the ruler's owner graded against pidtuna's own pool, inside the 0.25–2× gain guard and the "
             "band (<code>8f9fad2</code>). On CAN 11 no gains in the guard reach ζ 0.65 (best 0.58; 0.65 needs kd ×4.27 as found, and no measured "
             "run went past ×2), so pidtuna keeps the as-found kp/kd and the gain is the feed-forward's: 0x regret 0.000, gain 4.19×; 1x regret "
             "0.039, 4.03×; 3x regret 0.33, recorded, not gated (<code>c9deaf0</code>, from d06353334)."],
         ruler="tests/test_pid_tune_routine.py, with the owner's fixes 274d0cf (pidtuna v2) and 8f9fad2 (pidtuna's band and guard)",
         commits=["e605418", "6da4969", "367af92", "f879b7d", "8538233", "a012452", "a83f1ad", "6d41810", "4cebd28", "5355ff6", "d909124",
                  "c7e912e", "8f9fad2", "c9deaf0", "df14143", "08077b0", "02d1034"],
         runs=[("d06502487", "fast", "At the landed head <code>02d1034</code>, rack venv, 4 VMs. Every red is identical to main <code>090c638</code> "
                "run the same way (d06505253): <code>test_preflight</code> 5 and <code>test_preflight_nominal</code> 5 (the cut lacks robotparts' "
                "datasheets and robot_trajectories), <code>type_cards/tests</code> 13. L10's files: <code>test_pid_tune_routine</code> 13 · 0 · 3, "
                "<code>test_pid_tune_real_path</code> 8 · 0 · 0, <code>test_real_backend</code> 18 · 0 · 2."),
               ("d06515241", "fast", "At <code>02d1034</code>, sim2real's own venv. Reds identical to main's (d06521840)."),
               ("d07255742", "fast", "<code>sysid/tests/test_noise_ladder.py</code> at <code>02d1034</code> in both venvs (with d07262288): 19 · 5 · 3 "
                "and 17 · 7 · 3, the same five and seven failures as main."),
               ("d06501647", "slow", "At <code>02d1034</code>: the three-lines end-to-end and the pendulum schedule's calibrate pass; "
                "<code>test_pid_tune_routine</code> 16 · 0 · 0, reproducing the committed ladder; the real-fit preflight fails as it does on main "
                "(torque_margin: the cut has no robotparts datasheet)."),
               ("d14061318", "fast", "At <code>fd7f849</code>, before the review fixes. The 2 ruler failures are the missing ladder and the plan "
                "recovery that reads it. <code>test_calibration_backend</code> (4) and <code>test_plan_totals_shared_runs</code> (1) need MuJoCo, "
                "which this venv lacks; both pass in the rack venv below. <code>type_cards/tests</code>: 10 of the 11 fail on the base too (files "
                "the cut doesn't carry). The extra one was the 0 s wall time against \"every routine's wall time &gt; 0\", which "
                "<code>274d0cf</code> and <code>e33ce71</code> settle."),
               ("d14065833", "fast", "At <code>fd7f849</code>, the rack venv. Same two ruler failures. <code>type_cards/tests</code>: 13 of the 14 "
                "fail on the base too; the extra one is the same wall-time conflict."),
               ("d14145289", "slow", "At <code>6411acd</code>. The grade failed on pidtuna v2's API, which the ruler fix <code>274d0cf</code> "
                "respells. The ladder test and the plan's recovery fail with it. The pendulum, from_robot_description and real_backend slow "
                "files pass with the tune step in."),
               ("d14162546", "slow, grade probe", "Throwaway branch <code>d2daa45</code>: the ruler's two pidtuna-v1 lines respelled for v2. "
                "Never lands. Its ladder is in the table below.")],
         slow_note="Before the band ruling, the grade failed on pidtuna main 6882390 (d04582098: regret 0.94 at 0x) while it passed on "
                   "33bfce3. The 2026-11-19 stall (no account could start a worker) ended when bam's quota reset."),
]


def gap_section(g: dict) -> str:
    chip = "<span class='chip ok'>landed</span>" if g["landed"] else "<span class='chip warn'>blocked · on claude/l10-c</span>"
    changed = "".join(f"<li>{c}</li>" for c in g["changed"])
    commits = "".join(commit(s) for s in g["commits"])
    rulers = tuple(re.findall(r"tests/(test_[a-z0-9_]+)\.py", g["ruler"]))
    runs = "".join(run(d, t, n, rulers) for d, t, n in g["runs"])
    if g.get("slow"):
        runs += none_run("slow", e(g["slow"]))
    if g.get("slow_note"):
        runs += f"<div class='run'><div class='runhead'><span class='bad'>head</span> · {g['slow_note']}</div></div>"
    note = f"<p class='note'>{g['note']}</p>" if g.get("note") else ""
    where = "sim2real origin/main" if g["landed"] else "branch <code>claude/l10-c</code>, not landed"
    shas = " ".join(f"<code>{e(sha)}</code>" for sha in g["commits"])
    return f"""
<section class="gap" id="gap-{e(g['key'])}">
<h3><span class="tag">{e(g['key'])}</span> {e(g['title'])} {chip}</h3>
<p class="muted small">lane {e(g['lane'])} · ruler <code>{e(g['ruler'])}</code></p>
<ul>{changed}</ul>
<details><summary>Commits on {where}: {shas}</summary><ul class="commits">{commits}</ul></details>{note}
<p class="label">Cloud evidence <span class="muted small">(open a line for its per-file counts)</span></p>{runs}
</section>"""


# --------------------------------------------------------------------------------------------------------------------------- diagram

SEAM_WIDE = """
<svg class="seam wide" viewBox="0 0 980 412" role="img" aria-label="The one-click seam: rd, RobotTwin, generate_schedule, CalibrationSchedule, calibrate through a backend, callbacks, fitted twin holding its data, evaluate">
<defs><marker id="aw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="head"/></marker></defs>
<rect class="box" x="8" y="30" width="134" height="64" rx="8"/><text x="75" y="57" text-anchor="middle" class="b">rd</text><text x="75" y="76" text-anchor="middle">a robot description</text>
<rect class="box" x="162" y="30" width="196" height="64" rx="8"/><text x="260" y="57" text-anchor="middle" class="b">RobotTwin</text><text x="260" y="76" text-anchor="middle">.from_robot_description(rd)</text>
<rect class="box new" x="378" y="30" width="226" height="64" rx="8"/><text x="491" y="57" text-anchor="middle" class="b">twin.generate_schedule(config)</text><text x="491" y="76" text-anchor="middle">= plan(twin, config) · A1</text>
<rect class="box new" x="624" y="8" width="348" height="174" rx="8"/>
<text x="640" y="32" class="b">CalibrationSchedule (static)</text>
<text x="640" y="56">• steps in order, each with its why · A1</text>
<text x="640" y="78">• each step: known now, or made after step k · A1</text>
<text x="640" y="100">• time: wall_time_s, run_time_s, shared runs once · T</text>
<text x="640" y="122">• $: equipment_usd, equipment_to_buy_usd; gates · B</text>
<text x="640" y="144">• "up to N rounds" for a routine that iterates · A2</text>
<text x="640" y="166" class="pend">• pid.pidtuna tune step · C (on branch)</text>
<path class="arrow" d="M142 62 H160"/><path class="arrow" d="M358 62 H376"/><path class="arrow" d="M604 62 H622"/>
<path class="arrow" d="M798 182 V198 H103 V212"/>
<rect class="box new" x="8" y="214" width="190" height="64" rx="8"/><text x="103" y="241" text-anchor="middle" class="b">twin.calibrate(config)</text><text x="103" y="260" text-anchor="middle">plays that schedule</text>
<path class="arrow" d="M198 246 H220"/>
<rect class="box new" x="222" y="214" width="352" height="188" rx="8"/>
<text x="238" y="238" class="b">through a backend, step by step</text>
<rect class="box inner" x="238" y="250" width="156" height="48" rx="6"/><text x="316" y="270" text-anchor="middle" class="b">sim</text><text x="316" y="288" text-anchor="middle">SimRunner, RigRunner</text>
<rect class="box inner" x="404" y="250" width="156" height="48" rx="6"/><text x="482" y="270" text-anchor="middle" class="b">rack</text><text x="482" y="288" text-anchor="middle">on="real" · F-real</text>
<text x="238" y="322">rounds: collect → fit → come back · A2</text>
<text x="238" y="344">e.g. arm.feedforward_bench · FF-1, FF-2</text>
<rect class="box pendbox" x="238" y="358" width="322" height="30" rx="6"/><text x="399" y="378" text-anchor="middle" class="pend">PidTune tune step · C · on claude/l10-c</text>
<rect class="box new" x="598" y="214" width="180" height="74" rx="8"/><text x="688" y="238" text-anchor="middle" class="b">callbacks · E</text><text x="688" y="258" text-anchor="middle">Ledger, then W&amp;B copy</text><text x="688" y="276" text-anchor="middle" class="small">each step as it lands</text>
<path class="arrow dash" d="M574 250 H596"/>
<rect class="box new" x="598" y="306" width="180" height="74" rx="8"/><text x="688" y="330" text-anchor="middle" class="b">fitted twin · D</text><text x="688" y="350" text-anchor="middle">data_ · plan_ · record_</text><text x="688" y="368" text-anchor="middle" class="small">calibrate(data=) refits it</text>
<path class="arrow" d="M574 343 H596"/>
<rect class="box" x="800" y="306" width="172" height="74" rx="8"/><text x="886" y="336" text-anchor="middle" class="b">fitted.evaluate()</text><text x="886" y="356" text-anchor="middle">gates on held-out runs</text>
<path class="arrow" d="M778 343 H798"/>
</svg>
"""

SEAM_NARROW = """
<svg class="seam narrow" viewBox="0 0 360 780" role="img" aria-label="The one-click seam, top to bottom">
<defs><marker id="an" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="head"/></marker></defs>
<rect class="box" x="20" y="6" width="320" height="50" rx="8"/><text x="180" y="28" text-anchor="middle" class="b">rd</text><text x="180" y="46" text-anchor="middle">a robot description</text>
<path class="arrow n" d="M180 56 V76"/>
<rect class="box" x="20" y="78" width="320" height="50" rx="8"/><text x="180" y="100" text-anchor="middle" class="b">RobotTwin.from_robot_description(rd)</text><text x="180" y="118" text-anchor="middle">the twin</text>
<path class="arrow n" d="M180 128 V148"/>
<rect class="box new" x="20" y="150" width="320" height="50" rx="8"/><text x="180" y="172" text-anchor="middle" class="b">twin.generate_schedule(config)</text><text x="180" y="190" text-anchor="middle">= plan(twin, config) · A1</text>
<path class="arrow n" d="M180 200 V220"/>
<rect class="box new" x="20" y="222" width="320" height="168" rx="8"/>
<text x="34" y="244" class="b">CalibrationSchedule (static)</text>
<text x="34" y="266">• steps in order, each with its why · A1</text>
<text x="34" y="288">• known now / made after step k · A1</text>
<text x="34" y="310">• wall_time_s, run_time_s · T</text>
<text x="34" y="332">• equipment $ and gates · B</text>
<text x="34" y="354">• "up to N rounds" · A2</text>
<text x="34" y="376" class="pend">• pid.pidtuna tune step · C (branch)</text>
<path class="arrow n" d="M180 390 V410"/>
<rect class="box new" x="20" y="412" width="320" height="50" rx="8"/><text x="180" y="434" text-anchor="middle" class="b">twin.calibrate(config)</text><text x="180" y="452" text-anchor="middle">plays that schedule</text>
<path class="arrow n" d="M180 462 V482"/>
<rect class="box new" x="20" y="484" width="320" height="118" rx="8"/>
<text x="34" y="506" class="b">through a backend: sim or rack · F-real</text>
<text x="34" y="528">rounds: collect → fit → come back · A2</text>
<text x="34" y="550">e.g. arm.feedforward_bench · FF-1, FF-2</text>
<text x="34" y="572">callbacks: Ledger, then W&amp;B copy · E</text>
<text x="34" y="594" class="pend">PidTune tune step · C (on claude/l10-c)</text>
<path class="arrow n" d="M180 602 V622"/>
<rect class="box new" x="20" y="624" width="320" height="58" rx="8"/><text x="180" y="646" text-anchor="middle" class="b">fitted twin · D</text><text x="180" y="666" text-anchor="middle">data_ · plan_ · record_; calibrate(data=)</text>
<path class="arrow n" d="M180 682 V702"/>
<rect class="box" x="20" y="704" width="320" height="50" rx="8"/><text x="180" y="726" text-anchor="middle" class="b">fitted.evaluate()</text><text x="180" y="744" text-anchor="middle">gates on held-out runs</text>
</svg>
"""


# --------------------------------------------------------------------------------------------------------------------------- feedforward

LEVELS = ("0x", "1x", "3x", "10x")


def ladder_chart() -> str:
    """Horizontal grouped bars: gravity and friction error per noise level, on an axis that ends at the 0.10 N·m tolerance."""
    tol_g, tol_f = LADDER["tolerance"]["gravity_nm"], LADDER["tolerance"]["friction_nm"]
    tol = max(tol_g, tol_f)
    left, right, top, row, bar = 40, 420, 38, 50, 16
    width = right - left
    out = [f'<svg class="chart" viewBox="0 0 480 {top + row * 4 + 46}" role="img" aria-label="Feedforward ladder: gravity and friction error per noise level against the {tol:g} N·m tolerance">']
    for k in range(6):
        x = left + width * k / 5
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{top + row * 4 - 6}"/>')
        out.append(f'<text class="axis" x="{x:.1f}" y="{top + row * 4 + 14}" text-anchor="middle">{tol * k / 5:.2f}</text>')
    out.append(f'<line class="tol" x1="{right}" y1="{top - 14}" x2="{right}" y2="{top + row * 4 - 6}"/>')
    out.append(f'<text class="axis" x="{right}" y="{top - 18}" text-anchor="end">tolerance {tol:.2f} N·m</text>')
    for i, level in enumerate(LEVELS):
        lv = LADDER["levels"][level]
        y0 = top + i * row
        out.append(f'<text class="lab" x="{left - 10}" y="{y0 + bar + 4}" text-anchor="end">{level}</text>')
        for j, (key, cls, name) in enumerate((("gravity_error_nm", "s1", "gravity"), ("friction_error_nm", "s2", "friction"))):
            v = lv[key]
            w = max(2.0, width * v / tol)
            y = y0 + j * (bar + 2)
            out.append(f'<rect class="{cls}" x="{left}" y="{y}" width="{w:.1f}" height="{bar}" rx="3"><title>{level} {name} error {v:.4f} N·m '
                       f'({lv["rounds"]} rounds, {"converged" if lv["converged"] else "stopped: no improvement"})</title></rect>')
            out.append(f'<text class="val" x="{left + w + 6:.1f}" y="{y + bar - 4}">{v:.4f}</text>')
    out.append(f'<text class="axis" x="{(left + right) / 2}" y="{top + row * 4 + 32}" text-anchor="middle">error against the hidden truth, N·m</text>')
    out.append("</svg>")
    legend = ("<div class='legend'><span><i class='sw s1'></i>gravity error</span><span><i class='sw s2'></i>friction error</span>"
              f"<span class='muted'>both gated at {tol_g:.2f} N·m</span></div>")
    return legend + "".join(out)


def ladder_table() -> str:
    rows = []
    for level in LEVELS:
        lv = LADDER["levels"][level]
        stop = "converged" if lv["converged"] else "no improvement"
        ok = "<span class='good'>pass</span>" if lv["pass"] else "<span class='bad'>fail</span>"
        rows.append(f"<tr><td>{level}</td><td>{lv['gravity_error_nm']:.4f}</td><td>{lv['friction_error_nm']:.4f}</td><td>{lv['rounds']}</td>"
                    f"<td>{stop}</td><td>{ok}</td></tr>")
    return ("<div class='tablewrap'><table><tr><th>noise</th><th>gravity error</th><th>friction error</th><th>rounds</th><th>stop</th>"
            f"<th>grade</th></tr>{''.join(rows)}</table></div><p class='note'>Errors in N·m against the hidden truth.</p>")


def perf_rows() -> str:
    """The FF-2 probe's PERF line at the landed bench row rules (pair 0.05 rad, moving 0.1 rad/s)."""
    line = next(x for x in (MEDIA / "ff_perf.txt").read_text(encoding="utf-8").splitlines() if "moving0.1" in x)
    data = json.loads(line.split(" ", 2)[2])
    shown = (("fb only", "PD alone"), ("cad ff + fb", "CAD feedforward + PD"), ("fitted ff + fb", "fitted feedforward + PD"))
    rows = []
    for key, label in shown:
        share, track = data[key]
        shown_share = "1.00" if share == 1.0 else f"{share:.3g}"
        rows.append(f"<tr><td>{label}</td><td>{shown_share}</td><td>{track * DEG:.3g}°</td></tr>")
    cad, fit = data["cad ff + fb"], data["fitted ff + fb"]
    table = ("<div class='tablewrap'><table><tr><th>controller</th><th>feedback share</th><th>tracking RMS</th></tr>"
             f"{''.join(rows)}</table></div>")
    gain = (f"<p>Fitted against CAD feedforward: feedback share <b>{cad[0] / fit[0]:.1f}× lower</b>, tracking error <b>{cad[1] / fit[1]:.1f}× "
            "lower</b>. The ruler asks for at least 2× on both, and for never tracking worse than PD alone. Feedforward alone, with no PD, "
            "runs away (not shown).</p>")
    return table + gain


def pid_probe_table() -> str:
    rows = []
    for level in ("0x", "1x", "3x"):
        lv = PID_PROBE["levels"].get(level)
        if lv is None:
            rows.append(f"<tr><td>{level}</td><td colspan='4'>not captured</td></tr>")
            continue
        ok = "<span class='good'>pass</span>" if lv["pass"] else "<span class='bad'>fail (recorded, not gated)</span>"
        rows.append(f"<tr><td>{level}</td><td>{lv['regret']:.3f}</td><td>{lv['gain']:.2f}×</td><td>{lv['stop_p90_mrad'] * 0.001 * DEG:.3f}°</td>"
                    f"<td>{ok}</td></tr>")
    return ("<div class='tablewrap'><table><tr><th>level</th><th>regret vs oracle</th><th>gain vs as-found PID</th><th>stop p90</th>"
            f"<th>grade</th></tr>{''.join(rows)}</table></div>"
            "<p class='note'>Cost is the stop p90 plus the tracking RMS, each relative to the board's as-found PID, on held-out tapes. "
            "Gain is the as-found cost over the tuned cost. Pass means regret ≤ 0.15 against the best PD + feedforward controller on the "
            "hidden truth. The level scales how far the fitted values handed to the tune sit from the truth, in units of the dynamics fit's "
            "acceptance tolerance. Throwaway probe "
            "d14162546 on branch d2daa45; its provenance hashes are stale, so this ladder can never be committed. The real one is written by "
            "the grade at <code>8a97966</code> or later.</p>")


# --------------------------------------------------------------------------------------------------------------------------- page

CSS = """
:root { color-scheme: light dark; --bg:#fbfbf9; --ink:#141414; --muted:#6b6a66; --line:#e2e1da; --code:#f2f1ec; --good:#0a7d0a; --bad:#b42f2f;
  --warn:#8a5a00; --accent:#2a6fd6; --s1:#2a78d6; --s2:#eb6834; }
@media (prefers-color-scheme: dark) { :root { --bg:#141413; --ink:#ecebe6; --muted:#a19f98; --line:#33322e; --code:#1d1d1b; --good:#4cc04c;
  --bad:#ec6b6b; --warn:#e0a83a; --accent:#6ea6ff; --s1:#3987e5; --s2:#d95926; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1000px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 1.6rem; margin: 0 0 6px; line-height: 1.25; }
h2 { font-size: 1.2rem; margin: 38px 0 10px; border-top: 1px solid var(--line); padding-top: 22px; }
h3 { font-size: 1.05rem; margin: 0 0 4px; }
.lede, .muted { color: var(--muted); } .small { font-size: .88rem; } .lede { margin: 0 0 18px; }
.verdict { border-left: 4px solid var(--good); padding: 12px 16px; background: var(--code); border-radius: 6px; }
.needs { border-left: 4px solid var(--warn); padding: 12px 16px; background: var(--code); border-radius: 6px; margin-top: 14px; }
pre { background: var(--code); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; overflow-x: auto;
  font: 13px/1.45 ui-monospace, "SF Mono", Menlo, monospace; }
code { font-family: ui-monospace, Menlo, monospace; font-size: .9em; overflow-wrap: anywhere; }
table { border-collapse: collapse; width: 100%; font-size: .93rem; } th, td { text-align: left; padding: 6px 9px; border-bottom: 1px solid var(--line);
  vertical-align: top; } th { color: var(--muted); font-weight: 600; }
.tablewrap { max-width: 100%; overflow-x: auto; }
.good { color: var(--good); font-weight: 600; } .bad { color: var(--bad); font-weight: 600; }
.chip { display: inline-block; font-size: .75rem; font-weight: 600; padding: 1px 8px; border-radius: 99px; vertical-align: 2px; margin-left: 6px; }
.chip.ok { color: var(--good); border: 1px solid var(--good); } .chip.warn { color: var(--warn); border: 1px solid var(--warn); }
.tag { display: inline-block; margin-right: 6px; font: 600 .85rem ui-monospace, Menlo, monospace; color: var(--accent); }
.board { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 8px; margin: 10px 0; }
.board a { display: block; text-decoration: none; color: inherit; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: var(--code); }
.board a:hover { border-color: var(--accent); } .board .t { display: block; font-size: .9rem; }
section.gap { border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin: 14px 0; }
section.gap ul { margin: 6px 0 8px; padding-left: 20px; } section.gap li { margin: 3px 0; }
details { margin: 6px 0; } summary { cursor: pointer; color: var(--muted); font-weight: 600; font-size: .9rem; }
summary.tally { font-weight: 400; color: var(--ink); } .label { font-weight: 600; font-size: .9rem; margin: 10px 0 2px; color: var(--muted); }
ul.commits { list-style: none; padding-left: 4px; font-size: .88rem; } ul.commits li { margin: 1px 0; }
.run { border-left: 3px solid var(--line); padding: 4px 0 4px 10px; margin: 8px 0; font-size: .88rem; }
.runhead { overflow-wrap: anywhere; } ul.files { list-style: none; padding-left: 4px; margin: 4px 0; columns: 2 330px; column-gap: 24px; } ul.files li { break-inside: avoid; } ul.files li { margin: 0; }
ul.files li.badrow code { color: var(--bad); } .note { color: var(--muted); font-size: .86rem; margin: 4px 0; }
.seam { width: 100%; height: auto; } .seam.narrow { display: none; max-width: 420px; margin: 0 auto; }
@media (max-width: 640px) { .seam.wide { display: none; } .seam.narrow { display: block; } main { padding: 20px 12px 48px; } h1 { font-size: 1.35rem; }\n  table { font-size: .84rem; } th, td { padding: 5px 5px; } }
svg text { fill: var(--ink); font: 13px system-ui, sans-serif; } svg text.b { font-weight: 600; } svg text.small { font-size: 11px; fill: var(--muted); }
svg text.pend { fill: var(--warn); font-style: italic; }
svg .box { fill: var(--code); stroke: var(--line); stroke-width: 1.2; } svg .box.new { stroke: var(--accent); stroke-width: 1.8; }
svg .box.inner { fill: var(--bg); } svg .box.pendbox { fill: none; stroke: var(--warn); stroke-dasharray: 5 4; }
svg .arrow { stroke: var(--muted); stroke-width: 1.5; fill: none; marker-end: url(#aw); } svg .arrow.n { marker-end: url(#an); }
svg .arrow.dash { stroke-dasharray: 4 3; } svg .head { fill: var(--muted); }
.chart { width: 100%; max-width: 640px; height: auto; display: block; } .chart .grid { stroke: var(--line); stroke-width: 1; }
.chart .tol { stroke: var(--bad); stroke-width: 1.5; stroke-dasharray: 4 3; } .chart .axis { font-size: 12px; fill: var(--muted); }
.chart .lab { font-size: 14px; font-weight: 600; } .chart .val { font-size: 12px; fill: var(--muted); }\npre.cmd { white-space: pre-wrap; overflow-wrap: anywhere; }
.chart .s1 { fill: var(--s1); } .chart .s2 { fill: var(--s2); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: .88rem; margin: 6px 0; } .legend .sw { display: inline-block; width: 12px; height: 12px;
  border-radius: 3px; margin-right: 6px; vertical-align: -1px; } .legend .sw.s1 { background: var(--s1); } .legend .sw.s2 { background: var(--s2); }
.cols2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 18px; }
ol.decided > li, ul.left > li { margin: 8px 0; } .undo { color: var(--muted); font-size: .88rem; }
"""


def board() -> str:
    cards = []
    for g in GAPS:
        chip = "<span class='chip ok'>landed</span>" if g["landed"] else "<span class='chip warn'>blocked</span>"
        cards.append(f"<a href='#gap-{e(g['key'])}'><span class='tag'>{e(g['key'])}</span>{chip}<span class='t'>{e(g['title'])}</span></a>")
    return f"<div class='board'>{''.join(cards)}</div>"


def main() -> None:
    named = [sha for g in GAPS for sha in g["commits"]]
    found = sum(sha in SUBJECTS for sha in named)  # commit() renders any sha git didn't list as "not captured"
    ledger_row = json.loads((MEDIA / "d19420510_ledger.json").read_text(encoding="utf-8"))
    stalled = f"{e(ledger_row['dispatch'])} at {e(ledger_row['at'])}, session {e(str(ledger_row['session'] or 'none: no worker started'))}"
    gaps_html = "".join(gap_section(g) for g in GAPS)
    lv = LADDER["levels"]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calibrate gaps: all 10 landed</title><style>{CSS}</style></head><body><main>
<h1>Calibrate gaps: all ten landed</h1>
<p class="lede">sim2real · lanes L1–L10 · 2026-11-18 → 19 · every test ran on Claude Code cloud VMs, none on the workstation (the arm is powered)</p>

<div class="verdict"><b>Update, Nov 21: all 10 lanes are landed and pushed.</b> L10 (PID tuna as the tune step) landed at sim2real
<code>02d1034</code>, after pidtuna's damping-band rule was settled with PID Tuna's owner: on CAN 11 the tune keeps the board's kp/kd and its
gain is the feed-forward's (4.19× at 0x). Every cloud red at that head is identical to main's. The first 9 landed Nov 19 at
<code>713da7a</code>.
The cloud harness the lanes ran on is on bam_ws <code>origin/main</code> (<code>0bea21956</code>, <code>be55ede05</code>, plus the tracker
records <code>ff21b7032</code>).</div>

<p class="small muted">Nov 19 stall, for the record: the grade's first dispatch never started a worker ({stalled}). It ran on bam
after its reset; jidoka was never needed.</p>

<h2>The ten gaps</h2>
{board()}

<h2>The one-click seam, as it is now</h2>
{SEAM_WIDE}{SEAM_NARROW}
<p class="small muted">Blue outline: changed by this run and on <code>origin/main</code>. Dashed amber: the tune step, drawn as it stood Nov 19
(on <code>claude/l10-c</code>); since Nov 21 it is on main, and the CAN 11 schedule runs PID tuna as its third step.</p>

<h2>Each gap: what changed, its ruler, its commits, its cloud runs</h2>
<p class="small muted">Every lane worked the same way. Its ruler was committed alone and red first. A builder in its own worktree never
touched <code>tests/</code>. Tests ran on cloud VMs only. Two reviewers checked it, and it landed by fast-forward. Counts are passed ·
failed · skipped, per file, read from each run's <code>summary.json</code>. "Rack venv" is bam_rack_twin's environment, with the CAN 11
pendulum.</p>
{gaps_html}

<h2>Ruler changes, and why</h2>
<p class="small muted">A ruler is the frozen test file a lane must pass. None of these were made by the implementer whose work they grade.</p>
<ul class="left">
<li><b>R1, <code>tests/test_real_backend.py</code></b> (<code>72f2f48</code>, agreed with the One-click session, which owns that file).
The real record's plan source is <code>"planner"</code>, not <code>"sysid"</code>, and its step ids equal <code>plan(twin)</code>'s.
<span class="undo">Why: with F-real, <code>on="real"</code> plays the planner's schedule, so the old line asserted the very behaviour the gap
removes.</span></li>
<li><b>R2, <code>tests/test_real_backend.py</code></b> (<code>f7328db</code>, agreed with the One-click session). <code>data=</code> leaves
the list of keywords <code>on="real"</code> refuses. <code>data=object()</code> must now raise a <code>TypeError</code> naming
<code>CalibrationData</code>, and the folder must stay empty. <span class="undo">Why: with D, <code>on="real", data=</code> means "refit the
rack runs this twin holds", with no rack time.</span></li>
<li><b>R3, <code>tests/conftest.py</code></b> (<code>008caa9</code>, orchestrator-owned). The suite forces <code>SIM2REAL_TRACK=off</code>.
<span class="undo">Why: a shell or VM with tracking on must never make the suite write ledgers or W&amp;B runs.</span></li>
<li><b>The rounds fixture, <code>tests/test_calibration_rounds.py</code></b> (in the ruler before its first commit, <code>908ec84</code>). The
ruler dry run (d01311712) hit <code>KeyError: "pid.pidtuna adjusts ['toy.trim'], which toy does not carry"</code> before any round ran.
<code>TrimRig.parameters()</code> now declares <code>toy.offset</code> and <code>toy.trim</code> as parameters nothing identifies, and both
tune tests start from priors of 0. <span class="undo">Why: a fixture error, not A2's gap. It would have stayed red after A2 landed.</span></li>
<li><b>The feedforward toy, <code>tests/feedforward_toy.py</code></b> (<code>cda06cd</code>, the routines session as ruler owner).
(1) <code>ToyArm.parameters()</code> names the routine only for the keys it identifies, so the blind-model test is no longer refused before it
plays. (2) The closed loop logs the board's torque <b>averaged over each 10 ms host period</b>, not its first 1 kHz tick.
<span class="undo">Why: the first tick sits kp · v · 4.5 ms above what the plant feels, which reads as +0.135 / +0.090 N·m·s/rad of viscous
friction that isn't there. Friction then missed at every level, 0.112 / 0.112 / 0.110 / 0.100 against 0.10 N·m (d08272271). With the mean
it's {lv['0x']['friction_error_nm']:.4f} / {lv['1x']['friction_error_nm']:.4f} / {lv['3x']['friction_error_nm']:.4f} /
{lv['10x']['friction_error_nm']:.4f}. <b>Hardware caveat kept for FF-3:</b> a real bench that logs a first-tick sample under held host targets
has the same bias. The real log must carry the host-period mean.</span></li>
<li><b>FF-2's committed-ladder compare, <code>tests/test_feedforward_rounds.py</code></b> (in the ruler before its first commit,
<code>7a75162</code>). A slow run without WRITE compares its own pass and worst error per level against the committed ladder.
<span class="undo">Why: the dry-run review found that any hand-written JSON with the right hashes passed the fast check.</span></li>
<li><b>The PID ruler, <code>tests/test_pid_tune_routine.py</code></b> (<code>274d0cf</code>, on <code>claude/l10-c</code> only).
(1) pidtuna v2: it imports the <code>pidtuna.tune</code> module by name, because the package now exports a function of the same name, and
it grades the controller rebuilt from what the call delivered (<code>Tuning.gains</code> plus the feedforward the tune held fixed), never the
wrapper's own proposal. (2) Wall time: the tune's wall time is positive compute on the fitted twin, not 0. "No robot time" is pinned by
<code>runs()</code> being empty. <span class="undo">Why: (1) the v1 spelling failed before any tune ran (d14145289). (2) 0 s contradicted
<code>type_cards/tests/test_routines.py</code>, which requires every routine's wall time &gt; 0, so no catalog value could pass both.</span></li>
</ul>

<h2 id="ff">Feedforward calibration: where it stands</h2>
<div class="cols2"><div>
<p><b>What the arm runs today.</b> A lot of feedforward, but none of it came from a routine:</p>
<ul>
<li>gravity from measured masses on J2/C1 and the wrist (PID tuna's 15c file);</li>
<li>J1's sine gravity law (two laws are live; they agree within 0.19 N·m);</li>
<li>Coulomb friction while moving: the J2/C1 0.70 / 0.78 N·m is a bench constant, never refit on bam_fb_v2;</li>
<li>an inertial term from the trajectory, using the CAD masses;</li>
<li>the gated hold pushes on J2/C1;</li>
<li>two five-bar compensations; the lumped one is about 0.65 N·m off on C1 at a family −1 wrist.</li>
</ul>
<p class="small muted">Each came from one-off PID tuna scripts over runs harvested from picks, checked on held-out runs and installed by a
pin move. The fits are good, but the process doesn't repeat and has no stop rule.</p>
</div><div>
<p><b>What sim2real now has: <code>arm.feedforward_bench</code>, your collect → fit → iterate.</b></p>
<ol>
<li><b>Collect:</b> paired out-and-back moves from the trajectory library, at two speeds, over a workspace pose graph. Each command already
carries the current feedforward.</li>
<li><b>Fit:</b> gravity, plus Coulomb and viscous friction per drive. The way back cancels the friction, and holds never count.</li>
<li><b>Check:</b> each fit is tested on held-out cells.</li>
<li><b>Iterate:</b> each new round collects only what is missing or still off, with the last fit's feedforward. It stops when the fit stops
changing, stops improving, or hits its cap.</li>
</ol>
<p class="small muted">Bench is this routine, submitted through rackq once the twin passes. Deployed is the same fit over the production
runs the twin now holds (gap D), with PID tuna's learned feedforward as a drift canary.</p>
</div></div>

<h3>The ladder: hidden-truth recovery on the toy arm, closed loop</h3>
<p class="small muted"><code>sysid/results/routine_ladders/arm.feedforward_bench.json</code> as committed in <code>817ff5b</code>, written
on a cloud VM (d13124016) and re-checked without WRITE (d13175137). Two drives, 12 cells. The noise level scales the bench's sensor noise.</p>
{ladder_chart()}
{ladder_table()}
<p>All four levels pass. 0x and 1x converge at round 2. At 3x and 10x the fit is still right (gravity within
{lv['3x']['gravity_error_nm']:.3f} / {lv['10x']['gravity_error_nm']:.3f} N·m of the truth), but the held-out residual sits at its noise floor,
above the 0.10 N·m tolerance, so the routine stops "no improvement" and never claims convergence. That's honest. A noise-aware residual
tolerance would let 3x converge.</p>

<h3>Performance gained, closed loop, held-out transfers</h3>
{perf_rows()}
<p class="note">Feedback share is RMS(feedback torque) / RMS(total torque) on moving rows. Tracking is the RMS position error to the board's
target. These numbers come from probe d07280523 at <code>34b0570</code>, at the landed row rules (0.05 rad, 0.1 rad/s), before the toy's
torque-averaging fix and the later code fixes. On the final head the halving test passes (d13175137, 6 of 6), but pytest didn't print its
numbers, so the landed numbers are not captured.</p>

<h3>What blocks a real-arm run</h3>
<ul>
<li><b>FF-3, the hookup:</b> CAN 11 first (the seam and the real path exist), then the bam_fb_v2 rig on the one-click seam, twin first.
After that, a bench run at about 20–30 arm-minutes per round (an estimate, not measured), installed by pin move with its undo.</li>
<li><b>Torque logging:</b> the bench log must carry the board's torque averaged over each host period. A first-tick sample adds
kp · qd · (about half a host period) to the viscous term, which no fit can tell from friction.</li>
<li><b>Kt is not separated:</b> nothing measures it, and a Kt error looks exactly like a mass error. Default taken: no known-mass rung, and
the result says "Kt not measured".</li>
<li><b>The friction twin's 20ad gate</b> fails today.</li>
</ul>

<h2>L10, PID tuna: what its probe already shows</h2>
{pid_probe_table()}

<h2>Decided for you</h2>
<ol class="decided">
<li><b>The ruler fixes the routines session made as owner:</b> the rounds fixture, the feedforward toy (<code>cda06cd</code>) and FF-2's
committed-ladder compare. <span class="undo">Undo: <code>git revert cda06cd</code>. FF-2's slow ladder test goes red again, and the ladder
would need rewriting.</span></li>
<li><b>PID tuna's wall time is about 3 s of compute, not 0 s</b> (<code>274d0cf</code> in the ruler, <code>e33ce71</code> / <code>8a97966</code>
in the catalog, on the branch). The 3 s is a probe session's time (d15425264), and the source string says so. The grade's own call time
divided by 3 replaces it on the next run. <span class="undo">Undo: change <code>Q(3, ...)</code> in <code>cards/calibration.py</code>; nothing
is landed.</span></li>
<li><b>Pushed sim2real:</b> 50 commits, <code>24d4d3b..713da7a</code>. That's 39 lane commits plus 11 peer commits (preflight and the
nominal-world twin, <code>f8e408e..713da7a</code>). The repo was already public. <span class="undo">Undo: <code>git revert</code> a lane's
commits, listed above. The push itself can't be taken back.</span></li>
<li><b>Landed the cloud harness on bam_ws <code>origin/main</code></b> (<code>0bea21956</code>). It fails a run that reads a missing /archive
file and an empty shard, prints FAILED lines, and brings home ladders a VM writes. Then <code>be55ede05</code>: the cut keeps sim2real's
<code>website/site</code> and the UR wrist scene + meshes. <span class="undo">Undo: <code>git revert be55ede05 0bea21956</code> in bam_ws.
L9's tracker records are <code>ff21b7032</code>.</span></li>
<li><b>The defaults for plan §5's questions</b>, each one config value away:
<ul>
<li>B: a routine graded in sim is not preferred when it costs an extra routine of robot time. The cover stays minimal. <span class="undo">Change: a
planner rank rule.</span></li>
<li>B: nothing is hard-coded about what the 1-DOF bench has. Docs use <code>("camera_tags",)</code>. <span class="undo">Change:
<code>Budget(equipment=(...))</code>. Tell me if it also has a ChArUco board, a weighed mass or a thermocouple.</span></li>
<li>FF success: gravity within 0.10 N·m on held-out poses for J2/C1 (0.02 on the wrist), friction within 0.05 N·m per parameter (the
ladder gates 2 × 0.05 = 0.10), and stop when ΔFF &lt; 0.05 / 0.01 N·m. <span class="undo">Change: <code>FeedforwardBench(tolerance_nm=,
delta_nm=)</code>.</span></li>
<li>FF arm time: at most 4 rounds of about 25 arm-minutes, only after the twin passes, in rackq slots that never pre-empt picks.
<span class="undo">Change: <code>max_rounds=</code>.</span></li>
<li>FF first hardware: the CAN 11 pendulum, then bam_fb_v2.</li>
<li>FF Kt: no known-mass rung, so the result says "Kt not measured".</li>
<li>E, W&amp;B default: sim off, rack ledger on, W&amp;B only with <code>SIM2REAL_TRACK=wandb</code> or the follower.
<span class="undo">Recommendation: turn W&amp;B on for rack runs once the follower is proven beside the powered arm.</span></li>
<li>E, project: the deployment's own, so CAN 11 goes to "Sim2Real · 1-DOF rack" as job_type calibrate.</li>
<li>C: "before" for performance gained is what the board runs today (its PID with integrator). "After" is PD + FF.</li>
</ul></li>
</ol>
<details><summary>Smaller calls the lanes made, each undone by reverting its commit</summary><ul class="left small">
<li>T: the known-now/made-after shared-id refusal exempts only runs with neither command nor spec (<code>f6af98a</code>).</li>
<li>FF-1: the catalog wall time is an estimate, Q(6600 s). <code>commands_read</code> covers every key the feedforward is made from
(<code>ee7c4cd</code>).</li>
<li>A2: <code>sim2real.rig.Stop(why, converged=False)</code>, so a routine can stop without claiming convergence, plus one guard line in
<code>real.py</code> (<code>65c3419</code>).</li>
<li>B: "known" counts as a gate for the include refusal (<code>68a75dd</code>).</li>
<li>D: <code>transport=</code> with <code>data=</code> is refused; a rack refit is ungraded; the rack session is the absolute submission path
(<code>d61542d</code>, <code>f3f6f22</code>).</li>
<li>E: two extra real-path hooks, on_submission and on_collect, so the default rack ledger opens in the folder emit names
(<code>a72bf75</code>).</li>
<li>FF-2: the bench row rules 0.05 rad / 0.1 rad/s; re-collect the worst cells while ΔG is unread (<code>8af4b3d</code>,
<code>fa45563</code>).</li>
<li>L10 (branch): known values in <code>values_</code> use basis CHOSEN; the routines projection was regenerated locally, a ~2 s pure catalog
projection on one pinned core (<code>8a97966</code>).</li>
</ul></details>

<h2>Left</h2>
<ul class="left">
<li><b>L10, landed; what's left around it:</b> a citable kd cap on CAN 11 (PID Tuna's ask: a twin sweep at kd ×2–6 and a prepared,
unrun bench step at ×4.5, in progress), without which the band stays out of reach there. The catalog's 3 s wall time is still a probe
session's. The real-fit preflight test can't pass on a VM until bam_ws's rack cut carries robotparts' datasheets and robot_trajectories.</li>
<li><b>FF-3:</b> hook <code>arm.feedforward_bench</code> to CAN 11, then build the bam_fb_v2 rig on the seam, twin first (see above).</li>
<li><b>Routine grades from the Nov 17 proposal, not built:</b> model mismatch, honest error bars, identifiability, repeatability, completion,
safety margin, validity window, and performance gain as a ranked grade. Today a routine is graded on hidden-truth recovery, and FF and PID tuna
also on performance in their own rulers.</li>
<li><b>Smaller:</b> E's W&amp;B saved view and the first real <code>--sync</code> into "Sim2Real · 1-DOF rack"; measuring wandb-core beside the
powered arm before the live copy becomes the rack default. The harness's rack cut still lacks <code>bam_ur_wrist_coverage</code>, so the slow
wrist tests can't run on a VM.</li>
</ul>

<h2>Needs you</h2>
<p>Nothing. (The Nov 19 onboarding ask is moot: L10 ran on bam after its reset.)</p>

<h2>Deliberately not done</h2>
<ul class="left">
<li>No pytest, sim or build ran on the workstation: the arm is powered. Every count above is from a cloud VM.</li>
<li>pidtuna and robot_trajectories were not pushed. Their first push would make each one public. The cloud carries both inside the cut.</li>
<li>The preflight fixture fix in <code>tests/test_preflight.py</code> (<code>df14143</code>) was made by the routines dispatcher for its
owner, the One-click session, which was not running. No assertion changed. <span class="undo">Undo: <code>git revert df14143</code>.</span></li>
</ul>

<h2>Sources</h2>
<p class="small muted">Workflow journals (one JSON line per agent result): wf_352f7b7d-d5e (L1–L9 builds, reviews, landers), wf_acbbe589-275
(L8/L9 finish, L10 build), wf_4752f827-d19 (L10 finish, blocked), wf_d8fe7072-e34 (cloud harness L0 and the ruler dry run). Cloud results:
<code>/home/bam/bam_ws/reports/media/cloud/s2r-*/</code>. Git: sim2real <code>origin/main</code> and <code>claude/l10-c</code>. Builder:
<code>docs/build_report_calibrate_gaps.py</code>, captures in <code>reports/media/calibrate-gaps-2026-11-19/</code>. {found} of {len(named)} named
commits found in git's own log.</p>
</main></body></html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
