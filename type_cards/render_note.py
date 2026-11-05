"""Render the type registry into its vault note (a generated note: edit the registry, then re-run this).

    python3 /home/bam/sim2real/type_cards/render_note.py [--out PATH]

Stdlib only. Writes the note to the vault directly when it does not exist yet; an existing note is Obsidian's, so it is
rewritten only through ~/zach_brain/Settings/Scripts/obsidian-edit.py (the script says so and prints the path to pass it).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from type_cards import coverage as cov  # noqa: E402
from type_cards import registry as reg  # noqa: E402

NOTE = Path("/home/bam/zach_brain/Projects/BAM Robotics/Notes/Sim2Real Type Cards — Metrics, Models, Coverage and Views per Part Type (2026-11-04).md")
SCHEDULE = Path("/archive/datasets/bam_rig/schedules/one-dof-test-rack/can11/schedule.json")
MODEL = "Claude Code · Opus 5.5 (`claude-opus-5-5`)"
CATALOG_NOTE = "Stock Diagnostics per Robot Part Type — Catalog and Library (2026-10-28)"
SCHEDULE_NOTE = "Servo Test Schedule — Prior Art and a Recommended v1 (2026-10-29)"
FLOOR_NOTE = "C - Repeatability Floor (A Sim Cannot Match Reality Better Than Reality Matches Itself)"
WORD = {"yes": "yes", "partial": "partly", "no": "no"}


def cell(text) -> str:
    return "—" if text in (None, "") else str(text).replace("|", "\\|").replace("\n", " ")


def table(head, rows) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def sha(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def card_section(card: reg.Card, can11) -> str:
    out = [f"## {card.title}", ""]
    out.append(f"*Zach's word:* {card.zach} · *black box:* **in** {card.inputs}; **out** {card.outputs}. "
               f"RobotDx part type: `{card.robotdx_part}`." if card.robotdx_part else
               f"*Zach's word:* {card.zach} · *black box:* **in** {card.inputs}; **out** {card.outputs}. RobotDx part type: none ({card.robotdx_gap}).")
    if card.members:
        out.append("")
        out.append("**Made of:** " + "; ".join(f"{m.count} × `{m.card}` ({m.role})" for m in card.members)
                   + (f". **Error budget:** {card.error_budget}." if card.error_budget else "."))
    out += ["", "### Metrics", "", table(["Metric", "Family", "Defined on (inputs → outputs)", "Unit", "RobotDx id", "÷ floor", "Gate", "Today"],
            [[m.title, m.family, m.defined_on, m.unit, f"`{m.robotdx}`" if m.robotdx else f"**proposed:** {m.proposed}", m.normalised, m.gate, "yes" if m.today else "no"]
             for m in card.metrics])]
    out += ["", f"**Floor:** {('`' + card.floor.robotdx + '`: ') if card.floor.robotdx else ''}{card.floor.rule}."]
    m = card.model
    out += ["", f"### Model — {m.name}", "",
            f"robotparts: {'`' + m.robotparts + '`' if m.robotparts else 'none'}{(' · ' + m.proposed) if m.proposed else ''}. Equation: `{m.equation}`.", "",
            table(["Parameter", "Unit", "Nominal", "Source", "Identified by", "Outputs see it?", "Note"],
                  [[f"`{p.name}`", p.unit, p.nominal, p.source, p.identified_by, WORD[p.observable], p.note] for p in m.parameters])]
    c = card.coverage
    out += ["", "### Coverage", "", f"{c.rule}." + (f" RobotDx: `{c.robotdx}`." if c.robotdx else "") + (f" Plan from: {c.plan_source}." if c.plan_source else ""), "",
            table(["Axis", "Unit", "Binning"], [[a.name, a.unit, a.binning] for a in c.axes])]
    if card.id == "servo" and can11:
        train, held = cov.servo_coverage(can11), cov.servo_coverage(can11, split="held_out")
        out += ["", f"**CAN 11's planned schedule** (`{can11['digest']}`, not run yet): train visits **{train.pct} %** of the {train.reachable} reachable "
                    f"(q, qd, qdd) cells ({train.visited}), held out {held.pct} %; load torque {train.axes['load torque']} % of its cells; temperature: not planned. "
                    f"`bam_rack_twin.schedule` computes the same {can11['coverage']['train']['pct_reachable']} % (the registry's test holds them equal)."]
    v = card.view
    out += ["", "### View", "", (f"data-ui `gallery/examples/{v.template}` @ `{reg.data_ui_commit()}`: " + ", ".join(v.panels) + "." + (f" In sim2real: {v.site}." if v.site else ""))
            if v.template else f"**proposed:** {v.proposed}."]
    o = card.observability
    out += ["", "### Measurable today?", "", f"**{WORD[o.today]}.** With: {'; '.join(o.instruments)}. Needs: {'; '.join(o.needs) or '—'}." + (f" {o.note}." if o.note else "")]
    missing = [f"metric *{x.title}*: {x.proposed}" for x in card.metrics if not x.robotdx] + ([f"model: {m.proposed}"] if not m.robotparts else []) \
        + ([f"view: {v.proposed}"] if not v.template else []) + [f"step *{s.title}*: {card.procedure[s.key].text}" for s in reg.STEPS if card.procedure[s.key].status == "proposed"]
    out += ["", "### What's missing", ""] + [f"- {x}" for x in missing]
    return "\n".join(out)


def render() -> str:
    can11 = json.loads(SCHEDULE.read_text()) if SCHEDULE.is_file() else None
    cards = list(reg.CARDS.values())
    n_metrics = sum(len(c.metrics) for c in cards)
    n_prop = sum(1 for c in cards for x in c.metrics if not x.robotdx)
    today = [c.title for c in cards if c.observability.today == "yes"]
    glance = table(["Type", "Metrics (proposed)", "Model params", "Coverage axes", "View (data-ui)", "Measurable today?"],
                   [[f"[[#{c.title}]]", f"{len(c.metrics)} ({sum(1 for x in c.metrics if not x.robotdx)})", len(c.model.parameters),
                     ", ".join(a.name for a in c.coverage.axes), f"`{c.view.template}`" if c.view.template else "proposed", WORD[c.observability.today]] for c in cards])
    steps = table(["#", "Step", "File", "What"], [[i + 1, s.title, f"`{s.artifact}`", s.does] for i, s in enumerate(reg.STEPS)])
    gaps = {}
    for repo, card, what in reg.gaps():
        gaps.setdefault(repo, []).append(f"- **{reg.CARDS[card].title}:** {what}")
    gap_text = "\n\n".join(f"**{repo}**\n" + "\n".join(lines) for repo, lines in gaps.items())
    servo_line = ""
    if can11:
        servo_line = f" The Servo card's coverage function gives CAN 11's planned schedule **{cov.servo_coverage(can11).pct} %**, the same number `bam_rack_twin.schedule` computes."
    head = f"""---
date created: 2026-11-04T21:00:00-07:00
familiarity: Created by AI
model: {MODEL}
tags:
  - bam
  - sim-to-real
  - system-identification
  - diagnostics
parent: "[[PROJECT - Sim2Real]]"
generated_by: "/home/bam/sim2real/type_cards/render_note.py (sim2real {sha(reg.REPO)})"
---

> [!ai]- AI handoff: {len(cards)} type cards in code, each with metrics, a model, coverage, a view and the shared procedure; servo is the only one fully measurable today
> **What this is:** your Nov 4 journal list ([[PROJECT - Sim2Real#Nov 4 2026]]) turned into one card per part type. The cards are code: `/home/bam/sim2real/type_cards/registry.py`. This note is rendered from it by `type_cards/render_note.py`, so change the registry and re-render; don't edit this note by hand.
> **Kept:** your 10 types, plus `encoder`, because the servo is made of a motor, a driver, a gearbox and an encoder. Metrics are black box only. Model parameters are levers, never metrics.
> **Verify:** whether the two metric families (performance and fidelity) are the right split, and whether the coverage bins are where you want them. The gate numbers marked "Zach to confirm" are still yours to decide.
> *{MODEL}*

# Sim2Real Type Cards — Metrics, Models, Coverage and Views per Part Type (2026-11-04)

## The answer

- **One card per type, {len(cards)} cards.** Each card has black-box metrics ({n_metrics} in all, {n_prop} of them proposed), a model with every parameter's unit, nominal value or source, the experiment that identifies it and whether the outputs can see it, coverage axes with a scoring function, a standard data-ui view, and the same seven-step procedure.{servo_line}
- **Two metric families per type, both measured on outputs only.** *Performance* is the device against its commanded target. *Fidelity* is the twin against the real device on the same input. Each is divided by the device's own repeatability floor where one can be measured ([[{FLOOR_NOTE}]]), so different types can be compared.
- **Measurable today on the rack:** {", ".join(today)}. The gearbox and the motor alone need a dyno ([[Dyno — Buy, Build or Skip (2026-10-03)]]). The arm cards are sim only.
- **Reused, not forked:** metrics cite [[{CATALOG_NOTE}|RobotDx's stock catalog]] by id (io-diagnostics `{reg.ROBOTDX_COMMIT}`). Parameters cite [[PROJECT - Robot Parts|robotparts]]' twin and actuator terms and `bam_rack_twin`'s TwinParameters. Views cite [[PROJECT - Data UI|data-ui]]'s robotics gallery templates at `{reg.data_ui_commit()}`. Coverage generalises `bam_rack_twin.schedule` ([[{SCHEDULE_NOTE}]]).
- **See it:** the **Types** area of the sim2real site (`/types/`). Every rack station links to its Servo card.

## At a glance

{glance}

## The procedure (the same for every type)

Every step writes a file, so a person or an agent can do any step, and the next step reads only that file. If you run the same schedule again with a new model, the comparison is fair ([[DP - Reality as Oracle]]).

{steps}

Gates come last, after the held-out score. A type is twinned when its fidelity gates pass at ≤ 1.5× the floor and its stop error fits its share of the 5 mm tool gate. Coverage is computed at the schedule step, before anything runs ([[C - Practical Identifiability (Only Model What Your Experiment Can Excite)]]).

"""
    body = "\n\n".join(card_section(c, can11) for c in cards)
    tail = f"""

## Gaps: what each other repo would need

Generated from the proposals in the registry. Nothing was changed in RobotDx, robotparts or data-ui.

{gap_text}

## Sources

- [[PROJECT - Sim2Real]] (the Nov 4 journal), [[MOC - Summary of Sim to Real Thinking To Date (Nov 4 2026)]]
- [[{CATALOG_NOTE}]]: the RobotDx metric ids
- [[{SCHEDULE_NOTE}]]: the servo's coverage and schedule
- [[{FLOOR_NOTE}]], [[DP - Reality as Oracle]]: the floor and the 1.5× ruler
- [[C - ISO 9283 (Robot Pose and Path Performance Criteria)]]: the arm's AP, RP and path metrics
- [[C - Backlash]], [[C - Kinematic Calibration]], [[Multi Arm Kinematic Calibration — Prior Art (2026-10-08)]], [[MOC - Hyperspectral]]
- [[C - Grey, White vs Black box Modeling, System Design]]: why the metrics are black box and the models grey box
"""
    return head + body + tail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=NOTE)
    args = parser.parse_args(argv)
    text = render()
    if args.out == NOTE and NOTE.exists():
        staged = Path.home() / ".cache" / "sim2real" / NOTE.name
        staged.write_text(text, encoding="utf-8")
        print(f"{NOTE} exists: Obsidian owns it. Rewrite it with ~/zach_brain/Settings/Scripts/obsidian-edit.py from {staged}")
        return
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text):,} chars)")


if __name__ == "__main__":
    main()
