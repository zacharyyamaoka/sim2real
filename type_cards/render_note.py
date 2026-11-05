"""Render the type registry into its vault note (a generated note: edit the registry, then re-run this).

    python3 /home/bam/sim2real/type_cards/render_note.py [--out PATH]

Stdlib only. Writes the note to the vault directly when it does not exist yet; an existing note is Obsidian's, so it is
rewritten only through ~/zach_brain/Settings/Scripts/obsidian-edit.py (the script says so and prints the path to pass it).

Since 2026-11-05 it renders v2 (Zach's Nov 5 workflow: model rungs, diagnostics and gates, test types, coverage bins, calibration
packages) into a NEW note, NOTE_V2; the Nov 4 note (NOTE) is never rewritten by this script (WHY: the dispatcher's brief, "Don't
overwrite the Nov 4 note": it is the record of what v1 said).
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
NOTE_V2 = NOTE.with_name("Sim2Real Type Cards v2 — Model Rungs, Diagnostics, Test Types and Calibration Packages (2026-11-05).md")
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
    out += rungs_section(card) + checks_section(card) + tests_section(card)
    c = card.coverage
    out += ["", "### Coverage", "", f"{c.rule}." + (f" RobotDx: `{c.robotdx}`." if c.robotdx else "") + (f" Plan from: {c.plan_source}." if c.plan_source else "")
            + (f" **Coverage gate:** a plan passes when it visits ≥ {c.gate_pct:g} % of the reachable headline cells." if c.gate_pct is not None else ""), "",
            table(["Axis", "Unit", "Bin size", "Binning", "Marginal"], [[a.name, a.unit, "—" if a.bin_size is None else f"{a.bin_size:g} {a.unit}", a.binning,
                                                                         "yes" if a.marginal else "headline"] for a in c.axes])]
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


def short(ref) -> str:
    """'Hwangbo et al. 2019' from 'Hwangbo, Lee, ... (2019). Title. Venue.' (the site's types_pages.ref_short, the same rule)."""
    head, _, rest = ref.title.partition(" (")
    year, _, after = rest.partition(").")
    authors = [a for a in head.split(", ") if a]
    who = authors[0] + (" et al." if len(authors) > 2 else f" & {authors[1]}" if len(authors) == 2 else "")
    return (f"{who} {year}".strip() + (": " + after.strip().rstrip(".") if ref.kind in ("doc", "standard", "code") else "")
            + (" (arXiv)" if ref.kind == "preprint" and "arXiv" in ref.title else ""))


def cite(ref) -> str:
    """A reference as a short markdown link; the full citation is in the note's References."""
    return f"[{short(ref)}]({ref.url})" if ref.url else short(ref)


def references_section() -> str:
    seen = {}
    for card in reg.CARDS.values():
        for r in card.rungs:
            for ref in r.references:
                seen.setdefault(ref.title, ref)
    for pkg in reg.CALIBRATION_PACKAGES:
        for ref in pkg.references:
            seen.setdefault(ref.title, ref)
    for refs in reg.WEAR_LAW_REFERENCES.values():
        for ref in refs:
            seen.setdefault(ref.title, ref)
    lines = [f"- {ref.title}" + (f" [{('doi:' + ref.doi) if ref.doi else 'link'}]({ref.url})" if ref.url else "") + (f" — {ref.note}" if ref.note else "")
             for _t, ref in sorted(seen.items())]
    return (f"## References\n\nEvery work the rungs, packages and wear laws cite ({len(lines)}), each DOI resolved at Crossref with its title matched and "
            "every URL fetched (`type_cards/check_references.py`, results in `type_cards/references_checked.json`).\n\n" + "\n".join(lines))


def rungs_section(card) -> list[str]:
    rows, below = [], set()
    for r in card.rungs:
        names = ", ".join(f"**{n}**" if n not in below else n for n in r.parameter_names) or "—"
        size = f"{r.n_parameters:,}" + (f" ({r.n_named} named + {r.architecture.weights:,} weights)" if r.architecture and r.n_named
                                        else " weights" if r.architecture else "")
        need = r.needs
        needs = (f"{need.min_pct:g} % × ≥ {need.min_samples}" + ("" if need.extrapolates else ", no extrapolation")) if need else "—"
        rows.append([f"{r.key}{' (today)' if r.current else ''}", r.name, r.kind, size, names, needs,
                     "<br>".join(cite(x) for x in r.references)])
        below = set(r.parameter_names)
    out = ["", "### Model rungs", "", table(["Rung", "Model", "Kind", "Parameters", "Names (new in bold)", "Coverage it needs", "Learn it"], rows)]
    arch = [[r.key, r.architecture.family, f"{', '.join(r.architecture.inputs)} × {r.architecture.history}", " × ".join(map(str, r.architecture.hidden)) or "—",
             r.architecture.activation or "—", r.architecture.output, f"{r.architecture.weights:,}"] for r in card.rungs if r.architecture]
    if arch:
        out += ["", table(["Learned rung", "Family", "Inputs × history", "Hidden", "Activation", "Predicts", "Weights"], arch)]
    worn = [[r.key, f"`{p.name}`", f"{p.wear.usage} ({p.wear.unit})", p.wear.law, f"`{p.wear.rate}`"] for r in card.rungs if r.kind == "physics"
            for p in r.wear_parameters]
    if worn:
        out += ["", table(["Wear rung", "Parameter", "Usage", "Law", "Rate"], worn)]
    return out


def checks_section(card) -> list[str]:
    gate_of = {g.diagnostic: g for g in card.gates}
    rows = []
    for d in card.diagnostics:
        g = gate_of.get(d.id)
        rows.append([d.metric, d.kind, d.threshold.text() + (f" — *{d.message}*" if d.kind == "drift" else ""),
                     (g.target.text() + (f" ({g.acceptance})" if g.acceptance else "")) if g else "observed",
                     (f"{d.forecast.usage} left, {d.forecast.law} law of {', '.join(d.forecast.parameters)}" if d.forecast else "")])
    observed = [m.title for m in card.metrics if reg.metric_status(card, m.id) == "observed"]
    return ["", "### Diagnostics and gates", "", "A diagnostic is a metric + a threshold; a gate is a diagnostic + a target." +
            (f" Observed, not gated: {', '.join(observed)}." if observed else ""), "",
            table(["Reads metric", "Kind", "Threshold (fine side)", "Gate target", "Forecast"], rows)]


def tests_section(card) -> list[str]:
    rows = [[t.title, t.setting, ", ".join(f"`{n}`" for n in t.identifies), t.how, "yes" if t.recalibration else "—", t.exists or "—"] for t in card.tests]
    return ["", "### Test types", "", table(["Test", "Setting", "Identifies", "How", "Recalibrates", "Today"], rows)]


def render() -> str:
    can11 = json.loads(SCHEDULE.read_text()) if SCHEDULE.is_file() else None
    cards = list(reg.CARDS.values())
    n_metrics = sum(len(c.metrics) for c in cards)
    n_prop = sum(1 for c in cards for x in c.metrics if not x.robotdx)
    today = [c.title for c in cards if c.observability.today == "yes"]
    glance = table(["Type", "Model rungs (parameters)", "Metrics (proposed)", "Gates", "Test types", "Coverage axes", "Measurable today?"],
                   [[f"[[#{c.title}]]", " · ".join(f"{r.key} {r.n_parameters:,}" for r in c.rungs), f"{len(c.metrics)} ({sum(1 for x in c.metrics if not x.robotdx)})",
                     len(c.gates), len(c.tests), ", ".join(a.name for a in c.coverage.axes), WORD[c.observability.today]] for c in cards])
    packages = table(["Package", "Serves", "Code today", "Status"],
                     [[f"**{p.group}**: {p.title}", ", ".join(f"[[#{reg.CARDS[s].title}]]" for s in p.serves),
                       "<br>".join(f"`{h.repo.replace('/home/bam/', '')}:{h.path}`" + (f" @ `{h.ref}`" if h.ref else "") for h in p.code) or "unknown",
                       p.status + (f": {p.note}" if p.note else "")] for p in reg.CALIBRATION_PACKAGES])
    servo = reg.CARDS["servo"]
    steps = table(["#", "Step", "File", "What"], [[i + 1, s.title, f"`{s.artifact}`", s.does] for i, s in enumerate(reg.STEPS)])
    gaps = {}
    for repo, card, what in reg.gaps():
        gaps.setdefault(repo, []).append(f"- **{reg.CARDS[card].title}:** {what}")
    gap_text = "\n\n".join(f"**{repo}**\n" + "\n".join(lines) for repo, lines in gaps.items())
    servo_line = ""
    if can11:
        servo_line = f" The Servo card's coverage function gives CAN 11's planned schedule **{cov.servo_coverage(can11).pct} %**, the same number `bam_rack_twin.schedule` computes."
    head = f"""---
date created: 2026-11-05T12:00:00-07:00
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

> [!ai]- AI handoff: your Nov 5 workflow per type card: {sum(len(c.rungs) for c in cards)} model rungs on {len(cards)} cards, diagnostics and gates, test types, coverage bins and the calibration packages
> **What this is:** [[PROJECT - Sim2Real#Proposed Work Flow Nov 5 2026]] applied to every type card, plus your two additions of the same day (wear; learned rungs at the top). It supersedes, and leaves untouched, the v1 note [[Sim2Real Type Cards — Metrics, Models, Coverage and Views per Part Type (2026-11-04)]]. Rendered from `/home/bam/sim2real/type_cards/registry.py` by `type_cards/render_note.py`; the API other lanes code against is `type_cards/CONTRACT.md`.
> **Kept:** every v1 metric, parameter and axis; today's single model is now the rung it equals (the servo's is M4, its 16 parameters unchanged).
> **Decided for you:** the rung numbers follow robotparts' published actuator ladder (so "M3" means the same model there), M6 is always the grey-box residual and M7 the black-box net; learned rungs need 95 % of cells with ≥ 200 samples (your schedule note's stricter target) and never extrapolate.
> **Verify:** the rung choices per type, the 1.25× drift threshold, and the gate numbers marked "Zach to confirm".
> *{MODEL}*

# Sim2Real Type Cards v2 — Model Rungs, Diagnostics, Test Types and Calibration Packages (2026-11-05)

## The answer

- **Every type has a ladder of models, {sum(len(c.rungs) for c in cards)} rungs on {len(cards)} cards**, each with its parameter count, the names, the coverage it needs and where to learn it. The servo climbs {" → ".join(f"{r.key} ({r.n_parameters:,})" for r in servo.rungs)}; M4 is today's twin.
- **The rule that picks one:** {reg.SELECTION_RULE}.
- **Metrics → diagnostics → gates.** Metrics are black box (performance: real vs target; fidelity: twin vs real). A diagnostic adds a threshold, a gate adds a target; a metric no gate reads is observed. Every type has a drift diagnostic, "{reg.DRIFT_MESSAGE}", at {reg.DRIFT_THRESHOLD:g}× its calibrated fidelity (settable), with a forecast of the usage left where the type wears ([[C - Model Drift]], [[C - Predictive Maintenance]]).
- **Test types per setting** (bench in the office, deployed in the facility), each with what it identifies; every type has a recalibration method in both. The servo's deployed one is `bam_rack_twin` `live_reid` (T10).
- **Coverage** axes carry bin sizes; every type has a coverage gate ({reg.CARDS["servo"].coverage.gate_pct:g} %, `bam_rack_twin.schedule`'s); CAN 11's plan passes it.{servo_line}
- **Calibration packages:** your six groups, ten packages, with the code each has today (one unknown: hyperspectral).
- **Measurable today on the rack:** {", ".join(today)}. The gearbox and the motor alone need a dyno ([[Dyno — Buy, Build or Skip (2026-10-03)]]). The arm cards and the conveyor are sim only. Fidelity is divided by the device's own floor ([[{FLOOR_NOTE}]]).
- **Reused, not forked:** metrics cite [[{CATALOG_NOTE}|RobotDx's stock catalog]] by id (io-diagnostics `{reg.ROBOTDX_COMMIT}`). Parameters cite [[PROJECT - Robot Parts|robotparts]]' twin and actuator terms and `bam_rack_twin`'s TwinParameters. Views cite [[PROJECT - Data UI|data-ui]]'s robotics gallery templates at `{reg.data_ui_commit()}`. Coverage generalises `bam_rack_twin.schedule` ([[{SCHEDULE_NOTE}]]).
- **See it:** the **Types** area of the sim2real site (`/types/`). Every rack station links to its Servo card.

## At a glance

{glance}

## Calibration packages

{packages}

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

- [[PROJECT - Sim2Real]] (the Nov 5 workflow and the Nov 4 journal), [[MOC - Summary of Sim to Real Thinking To Date (Nov 4 2026)]], [[MOC - System Identification]]
- [[Sim2Real Type Cards — Metrics, Models, Coverage and Views per Part Type (2026-11-04)]]: v1, unchanged
- [[C - Actuator Network (Learned Actuator Model)]], [[Servo System Identification — State of the Art and Our Plan (2026-10-25)]]: the learned rungs
- [[C - Coulomb and Viscous Friction]], [[C - Dynamic Friction Models (LuGre, GMS)]], [[C - Galling (Adhesive Wear)]]: the friction and wear rungs
- [[C - Covariate Shift (Fit Where You Excite, Weight Where You Operate)]]: why learned rungs are judged only inside their covered cells
- [[C - Hand-Eye Calibration]]: the hand-eye package
- [[{CATALOG_NOTE}]]: the RobotDx metric ids
- [[{SCHEDULE_NOTE}]]: the servo's coverage and schedule
- [[{FLOOR_NOTE}]], [[DP - Reality as Oracle]]: the floor and the 1.5× ruler
- [[C - ISO 9283 (Robot Pose and Path Performance Criteria)]]: the arm's AP, RP and path metrics
- [[C - Backlash]], [[C - Kinematic Calibration]], [[Multi Arm Kinematic Calibration — Prior Art (2026-10-08)]], [[MOC - Hyperspectral]]
- [[C - Grey, White vs Black box Modeling, System Design]]: why the metrics are black box and the models grey box
"""
    return head + body + tail + "\n" + references_section() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=NOTE_V2)
    args = parser.parse_args(argv)
    if args.out.resolve() == NOTE.resolve():
        raise SystemExit(f"{NOTE.name} is the Nov 4 (v1) note: this script no longer writes it (pass --out elsewhere)")
    text = render()
    if args.out == NOTE_V2 and NOTE_V2.exists():
        staged = Path.home() / ".cache" / "sim2real" / NOTE_V2.name
        staged.write_text(text, encoding="utf-8")
        print(f"{NOTE_V2} exists: Obsidian owns it. Rewrite it with ~/zach_brain/Settings/Scripts/obsidian-edit.py from {staged}")
        return
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text):,} chars)")


if __name__ == "__main__":
    main()
