"""Build the comparison gallery for the five deployment-page proposals (babble skill's deck shell).

Writes docs/proposals/2026-11-17-deployment-page/gallery-spec.json (the round: brief, frozen criteria from CRITERIA.md,
the five variants with their walkthroughs, media, scores and gate results) and builds
/home/bam/sim2real/reports/deployment-page-proposals-2026-11-17.html with the skill's gallery.py, then checks it strictly.
The stills and clips it points at are tools/capture.py's (reports/media/deployment-page-proposals-2026-11-17/, gitignored);
each variant's live prototype is embedded from this folder by a relative iframe (opens from file:// and over http).

    python3 -I /home/bam/sim2real/docs/proposals/2026-11-17-deployment-page/tools/build_gallery.py
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
OUT = REPO / "reports" / "deployment-page-proposals-2026-11-17.html"
MEDIA = "media/deployment-page-proposals-2026-11-17"
LIVE = "../docs/proposals/2026-11-17-deployment-page"
GALLERY = Path("/home/bam/zach_brain/Settings/Skills/babble/scripts/gallery.py")
STEPS = [("s1", "The rack: 3D + typed tree"), ("s2", "CAN 11: metrics and gates"), ("s3", "Nested table"), ("s4", "Before fit vs now"), ("s5", "Deployments")]
VERIFY = json.loads((HERE / "tools" / "verify.json").read_text())

REQUIREMENTS = [
    {"id": "fr1", "name": "One answer first on every node", "weight": 25,
     "why": "He asked for 'the current value of its metrics and gates' on each node, and calm UI is a standing rule: with 6 stations × 5 levels he must not read a table to learn that CAN 11's twin is the one red.",
     "passCondition": "On the deployment and on any node, the verdict, the first failing question and its metric against the gate read without a click or scroll.",
     "anchors": {"1": "The verdict needs reading a table or several clicks.", "3": "The verdict is up top, but its cause (which question, which metric) needs a click.", "5": "Verdict, first failing question and its metric vs gate in one line at the top of every node."}},
    {"id": "fr2", "name": "Typed tree you already know how to drive", "weight": 20,
     "why": "Reference apps: RobotDx's device tree and Table view, sim2real's Typed tree. Zero relearning; clicking any node shows that level.",
     "passCondition": "Tree on the left with click, keyboard and search; the picked level on the right; a nested table (tree + columns) of the same typed tree.",
     "anchors": {"1": "A new navigation model to learn; no nested table.", "3": "A tree and a table, but they drift from RobotDx / Typed tree conventions or lose the selection between them.", "5": "RobotDx's tree and Table conventions (dot, twisty, search, keyboard) with one selection shared by tree, table and 3D."}},
    {"id": "fr3", "name": "Before fit vs now, legible", "weight": 15,
     "why": "'Let me run the pendulum as it currently is' = round 0 (2026-11-15, as found) against round 8 (2026-11-17), without losing your place.",
     "passCondition": "The same metric's round-0 and round-8 values readable together at the node you are on, with the direction of change and the ladder caveat (CAN 11's top speed 2.5 → 5 rad/s).",
     "anchors": {"1": "One round at a time, no anchor between them.", "3": "A round switch that keeps your place; change seen by flipping.", "5": "Both rounds together at the node, direction marked, the ladder caveat stated where it matters."}},
    {"id": "fr4", "name": "Stacking and observability told truthfully", "weight": 15,
     "why": "Settled (MOC Nov 15): Floor → Data → Routines → Twin → Job at every node; a parent passes at its own output and with its children; on this rack motor and gearbox cannot be seen apart from the servo.",
     "passCondition": "Every node shows the five questions in order; 'not observable here' never reads as a fail; children shown as not gating where the contract says so.",
     "anchors": {"1": "One blended status; unobservable reads as failure.", "3": "Five questions shown, but the roll-up or the observability rule stays implicit.", "5": "Five questions in order at every level, the roll-up rule visible, 'not observable' and 'shown, not gating' distinct from fail."}},
    {"id": "fr5", "name": "Backend shape concrete and on the settled layering", "weight": 15,
     "why": "His follow-up: 'what is going on in the backend?' Fit lives on the Model, health on the unit, the verdict on a composition; robot_models knows ModelFamily → Model → Parameter; he leans to robot_models and 'a folder called metrics'. (Weight inferred.)",
     "passCondition": "A short code sketch names where definitions, gate numbers and values live, the API, and the page's read path; additive; breaks no ruling.",
     "anchors": {"1": "Hand-waved ('a metrics layer').", "3": "A location and an API, but it collides with a ruling or adds a package for little reason.", "5": "One concrete home per concern, additive, the read path named, pendulum_goal.py lifted not rewritten."}},
    {"id": "fr6", "name": "3D grounds the tree", "weight": 10,
     "why": "'Bring up the 3D viewer of that deployment.' House viewer taste: inline, no logo, a Fusion-style ViewCube. (Weight inferred.)",
     "passCondition": "A 3D view of the deployment on its page, selection synced both ways with the tree, honest about simulated geometry.",
     "anchors": {"1": "A static picture with no link to the tree.", "3": "A 3D view, but selection one-way or geometry unexplained.", "5": "Inline 3D, ViewCube, station ↔ tree selection both ways, status on the geometry, 'simulated' labelled."}},
]
GATES = [
    {"id": "g1", "name": "Real fixture only", "why": "Every number from round0.json / latest_real.json or sim2real's sysid index; anything simulated or assumed is labelled."},
    {"id": "g2", "name": "No dead controls", "why": "Every visible control does something; what is not wired is hidden."},
    {"id": "g3", "name": "Panels resize and remember", "why": "Every panel boundary drags and persists; an inspector folds (Zach's standing rule)."},
    {"id": "g4", "name": "Degrees and plain names", "why": "Angles in degrees, never rad or mrad; no bare code without its plain name beside it."},
    {"id": "g5", "name": "Read-only and isolated", "why": "No hardware, bus, camera or network access; writes only to the proposal folder and reports/."},
]


def preview(v: str) -> str:
    imgs = "".join(f'<img class="st-{sid}" src="{MEDIA}/{v}/{sid}.png" alt="{html.escape(label)}" loading="eager">' for sid, label in STEPS)
    show = "".join(f'.prototype[data-story-state="{sid}"] .dp .dp-shot img.st-{sid}{{display:block}}' for sid, _ in STEPS)
    chips = "".join(f'<button type="button" data-story-to="{sid}">{k} · {html.escape(label)}</button>' for k, (sid, label) in enumerate(STEPS, 1))
    on = "".join(f'.prototype[data-story-state="{sid}"] [data-story-to="{sid}"]{{background:#2a2a2f;color:#f7f8f8;border-color:#8a8d96}}' for sid, _ in STEPS)
    return (f"<style>.dp{{width:1440px;max-width:100%}}.dp .dp-shot img{{display:none;width:100%;height:auto;border-radius:6px;border:1px solid #26282d}}"
            f".prototype:not([data-story-state]) .dp .dp-shot img.st-s1{{display:block}}{show}"
            f".dp-steps{{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 0}}.dp-steps button{{font:600 13px system-ui,sans-serif;padding:5px 10px;border-radius:7px;border:1px solid #c4c4c4;background:transparent;color:inherit;cursor:pointer}}{on}</style>"
            f'<div class="dp"><div class="dp-shot">{imgs}</div><div class="dp-steps">{chips}</div></div>')


def story(captions: list[str]) -> dict:
    return {"title": "Walk the same five states", "steps": [{"label": label, "caption": cap, "state": sid, "target": f'[data-story-to="{sid}"]'} for (sid, label), cap in zip(STEPS, captions)]}


def media(v: str, extras: list[tuple[str, str, str]]) -> list[dict]:
    out = [{"label": "Click-through (real clicks, 16 s)", "caption": "Recorded from the running prototype with real clicks only: deployments → the rack → CAN 11 → this variant's own moves. Muted, loops.",
            "html": f'<video src="{MEDIA}/{v}/walk.mp4" poster="{MEDIA}/{v}/s2.png" muted loop autoplay playsinline controls width="1280" height="800"></video>'}]
    for name, label, cap in extras:
        out.append({"label": label, "caption": cap, "html": f'<img src="{MEDIA}/{v}/x_{name}.png" alt="{html.escape(label)}">'})
    sketch = (HERE / v / "BACKEND.md").read_text()
    code = sketch.split("```python", 1)[1].split("```", 1)[0].strip("\n")
    table = sketch.split("\n| concern", 1)[1].split("\n\n", 1)[0]
    import re
    md = lambda t: re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(t))
    rows = "".join("<tr>" + "".join(f'<td style="padding:3px 10px 3px 0;border-bottom:1px solid rgba(127,127,127,.25);vertical-align:top">{md(c.strip())}</td>' for c in line.strip("|").split("|")) + "</tr>" for line in table.splitlines()[2:])
    first = sketch.split("**Thesis:**", 1)[1].split("\n\n", 1)[0].strip()
    fits = "**Fits:**" + sketch.split("**Fits:**", 1)[1].strip()
    out.append({"label": "Backend: where the metrics live", "caption": f"This variant's backend ({v}/BACKEND.md): a sketch, not implemented in any library.",
                "html": (f'<div style="padding:16px;max-width:1100px;font:14px/1.5 system-ui,sans-serif"><p style="margin:0 0 10px"><b>Thesis.</b> {md(first)}</p>'
                         f'<table style="border-collapse:collapse;font-size:12.5px;margin:0 0 12px">{rows}</table>'
                         f'<pre style="font:12px/1.5 ui-monospace,monospace;background:rgba(127,127,127,.12);padding:12px;border-radius:8px;overflow:auto;white-space:pre">{html.escape(code)}</pre>'
                         f'<p style="margin:10px 0 0">{md(fits.replace("**", ""))}</p></div>')})
    out.append({"label": "Live prototype", "caption": "The real prototype, embedded (drag, click, fold, switch rounds). Open it full size with the serve command in the README.",
                "html": f'<iframe src="{LIVE}/{v}/index.html#/d/one-dof-test-rack?n=can11" width="1440" height="900" style="width:1440px;height:900px;border:1px solid #26282d;border-radius:8px" title="{v} live"></iframe>'})
    return out


def gates(v: str, extra: dict[str, str] | None = None) -> dict:
    r = VERIFY[v]
    sash = r["sash_px"]
    fold = r["inspector_folds"]
    ev = {
        "g1": "Every number reads the shared fixture (fixture/build_fixture.py recomputes the scorecards' 82 and 151 gates and holds them); the 3D wears a 'schematic geometry · simulated' chip.",
        "g2": "tools/verify.py clicked the tree/table row, a 3D station mesh, the ViewCube, the CAD-render toggle and the before/after control: all moved the page; 0 console errors.",
        "g3": f"Main boundary dragged +70 px ({sash[0]}→{sash[1]}), kept {sash[2]} px after a reload, double-click restored {sash[3]} px; inspector fold: {fold}.",
        "g4": "Angles print in degrees (0.045°, 2.14× floor); every T-code sits beside its name (T2 Twin ÷ floor at the output).",
        "g5": "Static pages over the fixture file; no network, bus or device access; nothing written outside the proposal folder and reports/.",
    }
    ev.update(extra or {})
    ok = all(x is True or (isinstance(x, str) and not x.endswith("False")) for k, x in r.items() if k not in ("sash_px", "console_errors")) and not r["console_errors"]
    return {g["id"]: {"pass": ok if g["id"] in ("g2", "g3") else True, "evidence": ev[g["id"]]} for g in GATES}


def sc(score: int, evidence: str, confidence: str) -> dict:
    return {"score": score, "evidence": evidence, "confidence": confidence}


VARIANTS = [
    {"id": "v1", "name": "Workbench", "accent": "#3987e5",
     "thesis": "RobotDx's own frame on the typed tree: icon rail, tree on the left, the picked level's entity page (answer, 3D strip, tabs) on the right, and RobotDx's Table view with a foldable inspector.",
     "bestWhen": "You want zero relearning: the same muscle memory as RobotDx, one page per level, depth on tabs (Gates · Metrics · Speed ladder · Definition).",
     "losesWhen": "You want to compare many nodes at once: a level at a time is slower than a matrix or a sheet for 'where is the red'.",
     "decisions": [{"label": "Mental model", "value": "tree + entity page, like RobotDx; the Table view is one rail click away"},
                   {"label": "Before vs now", "value": "one round switch in the bar; every value carries the other round beside it ('was 4.27× ▲')"},
                   {"label": "Backend", "value": "metrics nested on the ModelFamily: IntegratedServo.metrics beside IntegratedServo.m3"},
                   {"label": "3D", "value": "a resizable strip on every entity page; a click on a part selects that part"}],
     "keepParts": ["entity page header with the one-line answer", "Unit health box apart from the verdict", "Table view + foldable inspector", "Definition tab"],
     "proof": ["Walked by real clicks (clip); verify.py: row select, 3D mesh pick, ViewCube, CAD toggle, sash drag + persist + reset, inspector fold (Esc), round switch all pass.",
               "Prototype: front-end over the real fixture; the backend is a sketch (v1/BACKEND.md)."],
     "extras": [("ladder", "Speed ladder tab", "CAN 11 up the ladder: round 0 dashed under now, the gate as a band.")],
     "captions": ["Tree on the left, the deployment's entity page on the right: the answer names CAN 11's twin; the 3D strip wears each station's verdict.",
                  "CAN 11's page: 'Fails at Twin: twin ÷ floor 2.14×' on top, health apart, the ladder caveat, then the five questions with round 0 beside each value.",
                  "RobotDx's Table view: the same typed tree as nested rows, F D R T J dots, the message column, round 0 beside the key metric; the inspector folds.",
                  "The round switch on As found: CAN 11 fails first at Floor (1 of 6 rungs had a floor); 'now 0.045°' sits beside every value.",
                  "Deployments: physical and virtual in RobotDx's list style; only the rack has round data in this fixture."],
     "scores": {"fr1": sc(5, "Every entity page opens on the one-line answer (verdict, first failing question, metric vs gate); the deployment's names CAN 11 · twin 2.14×.", "high"),
                "fr2": sc(5, "RobotDx's frame cloned: dot per node, twisty, search, keyboard; Table view with inspector; tree, table and 3D share one selection (verify: row + mesh pick).", "high"),
                "fr3": sc(4, "Round switch keeps your place and every value shows the other round with ▲/▼; still a flip for the page's main colour, not side by side.", "high"),
                "fr4": sc(4, "Five questions in order on every node, children listed 'shown, not gating', not-observable hollow; the parent rule itself is not stated on the page.", "medium"),
                "fr5": sc(3, "Concrete and his lean (`.metrics` beside `.models`), but it adds a new kind of thing to robot_models against the 11-17 'ModelFamily → Model → Parameter only' ruling.", "medium"),
                "fr6": sc(4, "Inline 3D on every page, ViewCube, labels with verdict, both-way selection incl. part picks; a strip, so secondary to the tabs.", "high")}},
    {"id": "v2", "name": "Sheet", "accent": "#d95926",
     "thesis": "The nested typed table IS the deployment page: every node a row, the five questions as columns, round 0 and now as columns side by side; the 3D and the inspector dock on the right and fold away.",
     "bestWhen": "You scan for the odd one out across all 45 nodes and want both rounds visible at once without touching a control.",
     "losesWhen": "A single node's story matters more than the overview: the why lives in the dock, and 13 columns crowd a laptop width.",
     "decisions": [{"label": "Mental model", "value": "the table is the page (Typed tree + RobotDx Table merged)"},
                   {"label": "Before vs now", "value": "always both: Round 0 | Now | Δ columns, no switch"},
                   {"label": "Backend", "value": "a flat robot_models/metrics/ folder of records + a values ledger the table reads as is"},
                   {"label": "3D", "value": "docked above the inspector, folds with it (D / Esc)"}],
     "keepParts": ["round 0 | now | Δ columns", "five-question cells with their deciding number", "the ledger rows the page reads", "filter box"],
     "proof": ["Walked by real clicks (clip); verify.py: row select, mesh pick, ViewCube, CAD toggle, dock drag + persist + reset, dock fold all pass.", "Prototype: front-end over the real fixture; backend sketch in v2/BACKEND.md."],
     "extras": [("ledger", "The ledger rows", "The servo's inspector with the raw values.jsonl rows this backend would write: what the table reads.")],
     "captions": ["The deployment as one nested table: verdict round 0 and now, the five questions with their numbers, the dock with 3D and the rack's answer.",
                  "CAN 11's Twin cell picked: the dock's inspector lists every metric round 0 → now, the twin row highlighted.",
                  "Dock folded: the whole sheet, CAN 11's servo opened to its parts, key metric round 0 → now → Δ on every row.",
                  "Round 0 and now side by side in the inspector: floor 0.104° → 0.045°, repeats 3 → 5, twin 4.27× → 2.14×.",
                  "Deployments as rows, gates round 0 → now (82 → 151 of 180)."],
     "scores": {"fr1": sc(4, "Red cells pop and the dock opens on the answer, but the one-line why needs the dock open; the sheet itself is dense.", "medium"),
                "fr2": sc(4, "Exactly the nested table he pointed at (Typed tree columns + RobotDx Table) with twisties and a filter; no separate tree pane or keyboard row navigation.", "high"),
                "fr3": sc(5, "Both rounds always on screen as columns with Δ, per node and per metric; the ladder caveat in the inspector.", "high"),
                "fr4": sc(4, "The five questions are columns on every row, so stacking reads down the sheet; 'not seen' distinct; the parent rule not stated.", "medium"),
                "fr5": sc(4, "His 'folder called metrics' literally, cheap to move later, ledger shape like results.json/W&B; still non-models inside robot_models, loose records can drift.", "medium"),
                "fr6": sc(4, "Docked 3D synced both ways (row ↔ mesh), ViewCube; small beside the sheet, labels only on the picked station.", "medium")}},
    {"id": "v3", "name": "Scene", "accent": "#4cc06e",
     "thesis": "The deployment in 3D is the page: each station wears its verdict in space, a servo explodes into its parts tinted by their own status, the nested table pulls up from the bottom, and a time bar under the scene flips round 0 ↔ now.",
     "bestWhen": "You think spatially and want the physical rig to be the index: 'which arm, which part' before 'which row'.",
     "losesWhen": "You need to compare many numbers: the table is a pull-up, the overview is spatial, not tabular.",
     "decisions": [{"label": "Mental model", "value": "the scene is the page; the tree is a slim outline"},
                   {"label": "Before vs now", "value": "a time bar under the scene: drag it and labels, rings and the card change together"},
                   {"label": "Backend", "value": "the RobotPart type carries .models, .metrics and .dx (health = metric + threshold)"},
                   {"label": "3D", "value": "the stage; servo-level picks pull the station's parts apart, each tinted by its status"}],
     "keepParts": ["verdict labels in space", "exploded servo with part tints", "time bar", "bottom sheet table"],
     "proof": ["Walked by real clicks (clip); verify.py: outline row, mesh pick, ViewCube, CAD toggle, outline drag + persist + reset, card fold, time bar all pass.", "Prototype: front-end over the real fixture; backend sketch in v3/BACKEND.md."],
     "extras": [("exploded", "CAN 11's servo pulled apart", "The motor picked: motor, gearbox, encoder and driver separate behind the plate; the motor tints amber (envelope +71 %, not gating).")],
     "captions": ["The rack as the page: every station labelled with its verdict and deciding number; the card on the right answers for the whole rack.",
                  "CAN 11 picked in 3D: the camera flies to it, the card leads with 'Fails at Twin 2.14×' and the five questions.",
                  "The sheet pulled up: the same typed tree as a nested table under the scene, its height remembered.",
                  "The time bar at As found: rings and labels turn red, CAN 11 fails first at Floor; 82 of 180 gates.",
                  "Deployments as picture tiles: the rack's CAD render, the oracle examples dimmed."],
     "scores": {"fr1": sc(5, "Station labels carry verdict + number in space and the card opens on the one-line answer at every level.", "medium"),
                "fr2": sc(4, "Same tree component (keyboard, search) and a nested table, all sharing one selection with 3D; the table is a pull-up rather than RobotDx's Table view.", "medium"),
                "fr3": sc(4, "The time bar flips scene, labels and card together and the card shows 'was' values; a flip, not side by side.", "medium"),
                "fr4": sc(4, "Five questions in the card at every level, exploded parts tinted by their own status, not-observable hollow; parent rule implicit.", "medium"),
                "fr5": sc(2, "His literal words, but a pendulum arm or a cell is not a part, so composite metrics still need another home, and he said robot_parts should not be specific to each part.", "medium"),
                "fr6": sc(5, "The 3D is the navigation: verdict labels, ViewCube, part-level picks, exploded servo; 'schematic geometry · simulated' labelled.", "high")}},
    {"id": "v4", "name": "Questions", "accent": "#f0a548",
     "thesis": "The page is the question matrix: rows are the typed tree, columns the five questions in order, each cell the number that decides it; a banner names the one thing that stops the goal, and a click on any cell opens its evidence per speed rung.",
     "bestWhen": "You want the cause, not the data: 'what stops the goal, at which level, at which question' in one look, and what moved since round 0.",
     "losesWhen": "You want to browse a part like a catalog page, or you live in RobotDx's tree: there is no separate tree pane, and the 3D is a thumbnail.",
     "decisions": [{"label": "Mental model", "value": "a question matrix: rows = typed tree, columns = Floor → Data → Routines → Twin → Job"},
                   {"label": "Before vs now", "value": "Now · As found · What changed (every cell before → after, unchanged rows dimmed)"},
                   {"label": "Backend", "value": "sim2real owns the verdict: five questions once (verdicts.py), a card per type (cards/pendulum_arm.py lifts pendulum_goal.py)"},
                   {"label": "3D", "value": "a thumbnail beside the matrix, synced both ways"}],
     "keepParts": ["'one thing stops the goal' banner", "question columns", "What changed mode", "per-rung evidence table", "the first failing question marked as the cause"],
     "proof": ["Walked by real clicks (clip); verify.py: row select, mesh pick, ViewCube, CAD toggle, side drag + persist + reset, inspector fold, What changed all pass.", "Prototype: front-end over the real fixture; backend sketch in v4/BACKEND.md."],
     "extras": [("ladder", "CAN 11 as a ladder", "A row name opens the level as the five questions in order; Twin is marked as the cause.")],
     "captions": ["The matrix: one banner names the stop (CAN 11 · Twin 2.14×), every cell carries its deciding number, the inspector holds the rack's ladder.",
                  "CAN 11's Twin cell: the metrics behind it, round 0 beside, and the per-rung table where the 0.4 and 0.6 rungs miss 1.5×.",
                  "The matrix is the nested table: CAN 11's servo opened to its parts, motor amber (+71 % envelope), gearbox not observable.",
                  "What changed: every cell as round 0 → now; 6 of 6 floors and data now pass, twins 0 → 5 of 6.",
                  "Deployments × the five questions: virtual ones answer only Routines (their sysid oracle)."],
     "scores": {"fr1": sc(5, "The banner answers for the deployment ('One thing stops the goal: CAN 11 · Twin 2.14×, gate 1.5×'); every cell carries its deciding number.", "high"),
                "fr2": sc(3, "The matrix is a nested typed table with twisties, but no tree pane, no search, no keyboard; a new primary layout to learn.", "medium"),
                "fr3": sc(5, "What changed shows every cell before → after and dims unchanged rows; As found is one click; the ladder caveat sits under the rung table.", "high"),
                "fr4": sc(5, "The five questions in order are the page's columns; the parent rule is written beside it; the first failing question is marked 'the cause'; not observable and not gating distinct.", "high"),
                "fr5": sc(5, "One home per concern on the settled layering: verdict and gate numbers in sim2real (cards/servo_gates.py exists), pendulum_goal.py lifted as a card, robot_models stays models-only, metric_values/<dep>.json exists.", "medium"),
                "fr6": sc(3, "A synced 3D thumbnail with ViewCube; secondary to the matrix, labels only on the picked station.", "medium")}},
    {"id": "v5", "name": "Ladder", "accent": "#8e95ff",
     "thesis": "Measurement first: every level opens on its KPIs with round 0 beside them, then the evidence drawn: a ladder grid (stations × speed rungs, each cell the rung's five gates), speed-ladder plots with the gate as a band, bullet charts for the servo and parts.",
     "bestWhen": "You think in curves: 'how does it degrade with speed, and did round 8 move the curve under the gate'.",
     "losesWhen": "You want the five questions as the frame: here they are implicit in gates and plots, and the ladder grid needs its legend.",
     "decisions": [{"label": "Mental model", "value": "a measurement ladder: KPIs, then plots and grids of the evidence"},
                   {"label": "Before vs now", "value": "round 0 drawn underneath everything (dashed lines, a thin bar row, hollow marks); one toggle"},
                   {"label": "Backend", "value": "a small robot_metrics package of model-free functions; a type names what judges it"},
                   {"label": "3D", "value": "a hero beside the KPIs on every level"}],
     "keepParts": ["ladder grid (stations × rungs × 5 gates)", "speed-ladder plots with round 0 dashed", "bullet charts with a round-0 mark", "KPI cards with 'was'"],
     "proof": ["Walked by real clicks (clip); verify.py: tree row, mesh pick, ViewCube, CAD toggle, tree drag + persist + reset, overlay toggle all pass; no inspector beside a wide view.", "Prototype: front-end over the real fixture; backend sketch in v5/BACKEND.md."],
     "extras": [("servo", "Servo as bullet charts", "CAN 11's servo: T1 and T2 against their gates, round 0 as a hollow mark, T4 not run.")],
     "captions": ["The rack: KPIs with round 0 beside them, then the ladder grid: each station's six rungs, each cell its five gates, round 0's thin row under it.",
                  "CAN 11: the answer and KPIs on top (2.14× was 4.27×), then the plots up the speed ladder.",
                  "The ladder grid is the nested table: CAN 11 opened to its servo and parts, their gates spelled out across the row.",
                  "CAN 11's plots, the 0.4 rung highlighted (picked from the grid): round 0 dashed far above the gate, now under it except the twin.",
                  "Deployments with gates passed round 0 (82) under now (151 of 180)."],
     "scores": {"fr1": sc(4, "The one-line answer leads, but five KPI cards and a plot wall compete with it; calmer pages put one answer and fold the rest.", "medium"),
                "fr2": sc(4, "RobotDx tree on the left (keyboard, search); the nested table is a ladder grid with rung columns, an unfamiliar layout.", "medium"),
                "fr3": sc(5, "Round 0 drawn under every number and curve (dashed, thin row, hollow mark), toggle to clear it; the caveat over the plots.", "high"),
                "fr4": sc(3, "Gates per rung in Zach's order (sim stop → twin → predicts → tracking → stop) and hatched 'not observable' bullets, but the five questions are not the visible frame.", "medium"),
                "fr5": sc(3, "Shared model-free functions once, below robot_models; a new package to version and publish, and the five questions still need a home in sim2real.", "medium"),
                "fr6": sc(4, "A hero 3D on every level, synced both ways with ViewCube; beside, not part of, the evidence.", "medium")}},
]

AXES = [
    {"name": "Mental model", "values": ["tree + entity page, like RobotDx (V1)", "the nested table is the page (V2)", "the 3D scene is the page (V3)", "question matrix (V4)", "measurement ladder (V5)"]},
    {"name": "Before vs now", "values": ["round switch + 'was' beside every value (V1)", "Round 0 | Now | Δ columns (V2)", "time bar under the scene (V3)", "What changed: cells before → after (V4)", "round 0 drawn underneath (V5)"]},
    {"name": "Where metric definitions live", "values": ["nested on the ModelFamily: IntegratedServo.metrics (V1)", "robot_models/metrics/ folder + values ledger (V2)", "robotparts type: .models .metrics .dx (V3)", "sim2real: verdicts.py once + a card per type (V4)", "robot_metrics package of functions (V5)"]},
    {"name": "Role of the 3D", "values": ["strip on every entity page (V1)", "docked over the inspector (V2)", "the stage, parts pulled apart (V3)", "thumbnail beside the matrix (V4)", "hero beside the KPIs (V5)"]},
]


def build_spec() -> dict:
    variants = []
    for v in VARIANTS:
        vid = v["id"]
        variants.append({
            "id": vid, "name": v["name"], "thesis": v["thesis"], "accent": v["accent"], "bestWhen": v["bestWhen"], "losesWhen": v["losesWhen"],
            "decisions": v["decisions"], "keepParts": v["keepParts"], "proof": v["proof"], "scores": v["scores"], "gateResults": gates(vid),
            "previewLabel": "The same five states, captured from the running prototype", "preview": preview(vid), "story": story(v["captions"]),
            "media": media(vid, v["extras"]),
        })
    return {
        "schemaVersion": 3,
        "title": "Sim2Real deployment page · five proposals",
        "kicker": "Babble round · 2026-11-17 · /babble 5",
        "brief": ("Sim2Real opens on Deployments; a deployment shows its 3D and its typed component tree; any node shows the current value of its metrics and gates "
                  "(the five questions), a nested table like RobotDx's, and before any fit (round 0, 11-15) against now (round 8, 11-17). Each proposal also says where "
                  "the metric and gate definitions live in the backend."),
        "count": 5,
        "defaultId": "v4",
        "defaultWhy": ("Questions leads at 88/100 on the frozen criteria: it answers 'what stops the goal' in one banner, makes the five questions and the parent rule the page's "
                       "structure, shows every cell before → after, and its backend (sim2real owns the verdict, robot_models stays models-only) is the one that breaks no ruling. "
                       "Workbench is 2 points behind (86): a fragile lead."),
        "decisionHinge": ("Familiarity against cause-finding. Move 5 points from fr5 (backend fit) to fr2 (RobotDx conventions) and Workbench wins 88 to 86. The backend axis "
                          "is separable, so the stronger answer is a splice: Workbench's frame with Questions' banner, question columns and What-changed mode in its Table view, "
                          "on V4's backend with V2's metrics/ folder if he wants `.metrics` beside `.models`."),
        "invariants": ["The same fixture: round 0 (as found, 11-15) and round 8 (now, 11-17) scorecards of the pendulum campaign, read-only.",
                       "The same 45-node typed tree, the same five questions per node, the same status words and colours (sim2real's tokens).",
                       "1440 × 900, dark theme, every variant runnable from file:// and over http, no build step.",
                       "Schematic 3D from the station facts, labelled simulated; the CAD render one click away."],
        "boundary": "Front-end prototypes over the real fixture. The values a backend would compute are precomputed by fixture/build_fixture.py; each backend is a sketch (BACKEND.md), not implemented in any library.",
        "axes": AXES,
        "requirements": REQUIREMENTS,
        "hardGates": GATES,
        "variants": variants,
    }


def main() -> None:
    spec = build_spec()
    path = HERE / "gallery-spec.json"
    path.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if OUT.exists():
        OUT.unlink()
    subprocess.run([sys.executable, "-I", str(GALLERY), "build", "--spec", str(path), "--output", str(OUT), "--strict"], check=True)
    subprocess.run([sys.executable, "-I", str(GALLERY), "check", "--input", str(OUT), "--strict"], check=True)


if __name__ == "__main__":
    main()
