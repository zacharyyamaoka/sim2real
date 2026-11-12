"""Write docs/KPIS_GATES_CURRICULUM.md (+ a copy and an HTML render under reports/): sim2real's KPIs and gates, the curriculum, today's
status per rig and the three W&B tracker proposals (Zach, 2026-11-11).

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real python /home/bam/sim2real/docs/build_kpis_gates_curriculum.py

WHY generated: every status number on the page comes from sim2real.tracking.wandb_log.records(), the same records the W&B runs are
made from, so the page and the tracker cannot disagree; the prose around them is written here. --verify-log embeds the output of
`python -m sim2real.tracking.wandb_log --verify` (the W&B read-back), when given; --rig-verify-log the per-rig projects' read-back
(`python -m sim2real.tracking.rigs --verify`).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

from sim2real.rack_results import load
from sim2real.result import QUESTIONS
from sim2real.tracking import curriculum, rigs
from sim2real.tracking.wandb_log import ENTITY, PROJECT, REGISTRY, code_version, records

REPO = Path(__file__).resolve().parents[1]
DATE = "2026-11-11"
OUT = REPO / "docs" / "KPIS_GATES_CURRICULUM.md"
COPY = REPO / "reports" / f"sim2real-kpis-gates-curriculum-{DATE}.md"
HTML = REPO / "reports" / f"sim2real-kpis-gates-curriculum-{DATE}.html"
RIG = {"deployment_kind": "physical", "rig": "One Dof Test Rack"}
MARK = {"no": "✗", "partial": "~", "unknown": "?"}


def chip(record: dict, q: str) -> str:
    """✓ passes · ✗ no · ~ partial · ? unknown · ↓ its own answer is yes, a child holds it back."""
    if record["history"][-1].get(f"{q}/pass"):
        return "✓"
    own = record["summary"][f"{q}/own"]
    return "↓" if own == "yes" else MARK.get(own, "?")


def cell(record: dict, q: str) -> str:
    """The question's mark and its headline number, read off the record (never recomputed here)."""
    n, s = record["history"][-1], record["summary"]
    text = s.get(f"{q}/numbers", "")
    mark = chip(record, q)
    if q == "Floor":
        if n.get("Floor/floor_deg") is not None:
            out = f"{n['Floor/floor_deg']:.3f}° ({n.get('Floor/pairs')} pairs)"
            if n.get("Floor/passive_floor_deg") is not None:
                out += f"; passive {n['Floor/passive_floor_deg']:.3f}°"
            elif "passive N/A" in text:
                out += "; passive N/A"
            return f"{mark} {out}"
        if "driven floor is known" in text:
            return f"{mark} driven {' / '.join(re.findall(r'(\d+(?:\.\d+)?) mm', text))} mm; no settled tool revisit"
        return f"{mark} " + ("no tool runs" if "no tool runs" in text else "no tool-pose repeats" if "ISO" in text
                             else "no output repeat" if "deployment" in text else text[:40])
    if q == "Data":
        if n.get("Data/coverage_pct") is not None:
            return f"{mark} {n['Data/coverage_pct']:.1f} % of {n.get('Data/reachable_cells')} cells"
        parts = [f"{label} {n[key]:.1f} %" for key, label in (("Data/cube_pct", "cube"), ("Data/workspace_pct", "workspace"),
                                                              ("Data/facing_pct", "facing"), ("Data/heading_pct", "heading")) if key in n]
        return f"{mark} " + (", ".join(parts) if parts else ("physical runs, split sealed" if "physical" in text else "not measured"))
    if q == "Routines":
        found = re.search(r"(\d+)/(\d+) identifiable", text)
        if found:
            return f"{mark} {found.group(1)}/{found.group(2)} at 1× noise"
        return f"{mark} " + ("gravity only" if "gravity only" in text else "roll-up" if "rolls up" in text else "not graded")
    if q == "Twin":
        if n.get("Twin/ratio") is not None:
            out = f"{n['Twin/ratio']:.2f}×"
            if n.get("Twin/passive_ratio") is not None:
                out += f"; passive {n['Twin/passive_ratio']:.1f}×"
            return f"{mark} {out}"
        coupled = re.search(r"twin vs real ([\d.]+–[\d.]+)°, real vs target ([\d.]+–[\d.]+)°", text)
        if coupled:
            return f"{mark} coupled moves: twin {coupled.group(1)}° vs target {coupled.group(2)}°, no tool floor"
        return f"{mark} " + ("roll-up" if "rolls up" in text else "per joint only" if "per joint only" in text
                             else "no tool runs" if "no tool runs" in text else "no ratio")
    if q == "Job":
        if n.get("Job/settled_median_deg") is not None:
            return f"{mark} {n['Job/settled_median_deg']:.3f}° vs {n['Job/share_deg']:.3f}° share"
        held = re.search(r"(\d+(?:\.\d+)?) mm median", text)
        if held and record["config"]["level"] != "deployment":
            return f"{mark} {held.group(1)} mm vs 1 mm (settled holds)"
        return f"{mark} " + ("no picks" if "picks" in text else "not measured")
    return mark


# ---------------------------------------------------------------------------------------------------------------- the per-rig gates

STAGE_TITLE = {"target_vs_sim": "1 · target vs sim (controller)", "sim_vs_real": "2 · sim vs real (twin)",
               "target_vs_real": "3 · target vs real", None: "flag"}


def href(url: str) -> str:
    """A URL safe inside a markdown link: the rig projects' names carry spaces and '·', and a bare space ends a GFM link target."""
    return quote(url, safe=":/?=&%#")


def joint_label(joint: str) -> str:
    """'can14' -> 'CAN 14', 'j2' -> 'J2'."""
    return f"CAN {joint[3:]}" if joint.startswith("can") else joint.upper()


def unit(name: str, value: float) -> str:
    return f"{value:.3f}°" if name.endswith("_deg") else f"{value:.2f} mm" if name.endswith("_mm") else f"{value:.3g}"


def rig_data(results: dict, sha: str, dirty: bool) -> dict:
    """Per rig: its twin versions (the records the per-rig project gets) and its controller versions, as rigs.py builds them."""
    out = {}
    for name, rig in rigs.RIGS.items():
        result = results[name]
        twin = rigs.twin_records(result, rig, sha=sha, dirty=dirty)
        versions = sorted(rigs.controller_versions(result, rig), key=lambda v: v["order"])
        root = [r for r in twin if r["config"]["level"] == "deployment"]
        out[name] = {"rig": rig, "twin": twin, "versions": versions, "twin_after": next(r for r in root if r["config"]["stage_role"] == "after"),
                     "controller": rigs.controller_records(result, rig, versions, sha=sha, dirty=dirty)}
    return out


def latest(data: dict, key: str):
    """The latest controller version (by the order it ran) that measures `key`: (value, its title) or (None, None)."""
    for version in reversed(data["versions"]):
        if version["numbers"].get(key) is not None:
            return version["numbers"][key], version["title"]
    return None, None


def gate_cell(data: dict, name: str) -> str:
    if name == rigs.OBJECTIVE:
        numbers = data["twin_after"]["history"][-1]
        value = numbers.get(name)
        if value is None:
            return "not measured"
        verdict = "passes" if numbers.get("heldout_sim_vs_real_pass") else "fails"
        failing = [j for j in data["rig"].joints if numbers.get(f"heldout_sim_vs_real_pass_{j}") == 0]
        return f"{unit(name, value)} · **{verdict}**" + (f" ({', '.join(joint_label(j) for j in failing)} over 1.5× floor)" if failing else "") \
            + f" · latest twin ({data['twin_after']['config']['twin_iteration']})"
    value, title = latest(data, name)
    if value is None:
        return "not measured"
    limit = rigs.GATES[name]["limit"]
    verdict = "" if limit is None else (" · **passes**" if value <= limit else f" · **fails** ({value / limit:.{2 if value / limit < 1.5 else 1}f}× the gate)")
    return f"{unit(name, value)}{verdict} · {title}"


def gates_table(rd: dict) -> str:
    lines = ["| Order | Metric (same name on both rigs) | Role | Limit | UR wrist today | Five-bar today |", "|---|---|---|---|---|---|"]
    order = {stage: k for k, stage in enumerate(rigs.GATE_ORDER)}
    for name, gate in sorted(rigs.GATES.items(), key=lambda item: order.get(item[1]["stage"], 9)):
        limit = (f"≤ {gate['limit']:g} mm" + (" (proposed)" if "proposed" in gate["rule"] else "")) if gate["limit"] is not None \
            else ("≤ 1.5× floor, per joint" if name == rigs.OBJECTIVE else "—")
        lines.append(f"| {STAGE_TITLE[gate['stage']]} | `{name}` | {gate['role']} | {limit} | {gate_cell(rd['ur_wrist'], name)} | "
                     f"{gate_cell(rd['fivebar'], name)} |")
    return "\n".join(lines)


def controller_table(data: dict) -> str:
    joints = data["rig"].joints
    head = ("| # | Controller version | target vs sim, worst joint | target vs real, worst joint | per joint, sim / real | tool tracking, sim / "
            "real | tool at a settled stop (encoders + FK) | camera vs commanded (flag) |")
    lines = [head, "|---|---|---|---|---|---|---|---|"]
    for version in data["versions"]:
        n = version["numbers"]
        fmt = lambda key, u="°": "—" if n.get(key) is None else (f"{n[key]:.3f}°" if u == "°" else f"{n[key]:.2f} mm")
        per = ", ".join(f"{joint_label(j)} {fmt('target_vs_sim_tracking_deg_' + j)} / {fmt('tracking_rms_deg_' + j)}" for j in joints
                        if n.get(f"tracking_rms_deg_{j}") is not None or n.get(f"target_vs_sim_tracking_deg_{j}") is not None) or "—"
        tool = (f"{fmt('target_vs_sim_tracking_tool_mm', 'mm')} / {fmt('tracking_rms_tool_mm', 'mm')}"
                if n.get("tracking_rms_tool_mm") is not None else "—")
        stop = "—" if n.get("tool_error_at_stop_mm") is None else \
            f"{n['tool_error_at_stop_mm']:.2f} mm ({'passes' if n['tool_error_at_stop_mm'] <= 1.0 else 'fails'} 1 mm; p95 {n['tool_error_at_stop_p95_mm']:.1f})"
        if n.get("target_vs_sim_at_stop_mm") is not None:
            stop += (f"; sim {n['target_vs_sim_at_stop_mm']:.2f} mm ({'passes' if n['target_vs_sim_at_stop_mm'] <= 1.0 else 'fails'}), "
                     f"sim vs real {n['sim_vs_real_at_stop_mm']:.2f} mm")
        lines.append(f"| {version['order']} | {version['title']} | {fmt('target_vs_sim_tracking_deg')} | {fmt('tracking_rms_deg')} | {per} | "
                     f"{tool} | {stop} | {fmt('flag_camera_vs_commanded_mm', 'mm')} |")
    return "\n".join(lines)


def first_open(data: dict) -> str:
    """Zach's order, read for one rig: the first stage whose gate fails or is not yet measured."""
    after = data["twin_after"]["history"][-1]
    stop_sim, sim_title = latest(data, "target_vs_sim_at_stop_mm")
    stop_real, title = latest(data, "tool_error_at_stop_mm")
    if stop_sim is None:
        one = "gate 1 (target vs sim at a stop) is **not measured**: no sim replay of settled holds"
    else:
        one = (f"gate 1 (target vs sim at a stop) **{'passes' if stop_sim <= 1 else 'fails'}**: the twin's tool settles {stop_sim:.2f} mm "
               f"from its target on {sim_title}")
    two = f"gate 2 (twin) **{'passes' if after.get('heldout_sim_vs_real_pass') else 'fails'}**"
    three = ("gate 3 (tool at a stop) is **not measured** (the tool is not tracked)" if stop_real is None
             else f"gate 3 (tool at a stop) **{'passes' if stop_real <= 1 else 'fails'}**: {stop_real:.2f} mm on {title}")
    return f"{one}; {two}; {three}"


def rig_wandb_section(rd: dict, verify_log: str | None) -> str:
    urls = json.loads(rigs.REGISTRY.read_text()) if rigs.REGISTRY.exists() else {"reports": {}, "views": {}}
    lines = ["| Project | Runs (latest evaluation) | Saved view | Report |", "|---|---|---|---|"]
    for name, data in rd.items():
        rig = data["rig"]
        link = href(f"https://wandb.ai/{ENTITY}/{rig.project}")
        lines.append(f"| [{rig.project}]({link}) | {len(data['twin'])} twin ({len({r['config']['node'] for r in data['twin']})} nodes × "
                     f"{data['twin'][0]['config']['iterations']} twin iterations) + {len(data['controller'])} controller versions | "
                     + (f"[view]({href(urls['views'][name])})" if name in urls.get("views", {}) else "—") + " | "
                     + (f"[report]({href(urls['reports'][name])})" if name in urls.get("reports", {}) else "—") + " |")
    if "servo-across-rigs" in urls.get("reports", {}):
        lines.append(f"| [{rigs.HUB}](https://wandb.ai/{ENTITY}/{rigs.HUB}) (cross-rig) | the one-project runs below | — | "
                     f"[servo joints and the same-named gates across rigs]({href(urls['reports']['servo-across-rigs'])}) |")
    boards = [(data["rig"], f"https://wandb.ai/{ENTITY}/{data['rig'].project}/weave/leaderboards") for data in rd.values()]
    lines += ["", "Each project also holds the rig's Weave evaluations and leaderboards (bam_ws `bam_trackio.bbo`: a version is a Weave "
              "model version scored on a fixed environment; one leaderboard per environment: twin versions on the held-out runs, "
              "controller versions on the coverage set, and on the five-bar the tool at the 16 settled holds): " + ", ".join(
                  f"[{rig.label} leaderboards]({href(board)})" for rig, board in boards) + ".", "",
              "Log both rigs (idempotent; new numbers supersede, nothing is deleted), rebuild the reports and views, read it all back:", "",
              "```bash",
              "env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra tracking python -m sim2real.tracking.rigs --log --views --verify",
              "```"]
    if verify_log:
        kept = [line for line in verify_log.splitlines() if line.startswith(("Sim2Real", "  ", "VERIFY"))]
        lines += ["", "The read-back through W&B's API (`rigs --verify`), as run for this page:", "", "```text", *kept, "```"]
    return "\n".join(lines)


def status_table(after: list[dict], rungs: list[dict]) -> str:
    lines = ["| Node | Verdict | Floor | Data | Routines | Twin | Job | Next rung |", "|---|---|---|---|---|---|---|---|"]
    for record in after:
        node = record["config"]["node"]
        indent = "&nbsp;&nbsp;" * record["config"]["depth"]
        nxt = curriculum.next_rung(rungs, node)
        title = next((r["title"] for r in rungs if r["node"] == node and r["rung"] == nxt), "")
        lines.append(f"| {indent}{record['config']['node_label']} | **{record['summary']['verdict']}** | "
                     + " | ".join(cell(record, q) for q in QUESTIONS) + f" | {nxt or 'climbed'}{(' · ' + title) if title else ''} |")
    return "\n".join(lines)


def trend_table(result) -> str:
    stats = [r for r in result.tables()["error_stats"] if r["scope"] == "held out"]
    head = "| Node | " + " | ".join(f"{k + 1} · {stage}" for k, stage in enumerate(result.stages)) + " |"
    lines = [head, "|---|" + "---|" * len(result.stages)]
    for node in result.nodes:
        mine = {r["stage"]: r for r in stats if r["node"] == node.id}
        if not mine or node.kind in ("arm",):
            continue
        cells = [f"{mine[s]['median_deg']:.3f}° ({mine[s]['runs']})" if s in mine else "—" for s in result.stages]
        lines.append(f"| {node.label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def ladder_tables() -> str:
    out = []
    names = {"joint": "Joint (every actuator or sensor type; the integrated servo here)", "arm": "Arm (rigid body chain)",
             "tool": "Tool (payload + TCP)", "deployment": "Deployment"}
    for level, rungs in curriculum.LADDERS.items():
        out.append(f"**{names[level]}**\n\n| Rung | What | Reads | Gate |\n|---|---|---|---|\n"
                   + "\n".join(f"| **{r.id}** | {r.title} | {r.question or '—'} | {r.gate} |" for r in rungs))
    return "\n\n".join(out)


def wandb_section(batches: dict, verify_log: str | None) -> str:
    urls = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"reports": {}, "views": {}}
    project = f"https://wandb.ai/{ENTITY}/{PROJECT}"
    n_runs = sum(len(b) for b in batches.values())
    groups = ", ".join(f"`{b[0]['group']}`" for b in batches.values())
    lines = [f"- **Project:** [{ENTITY}/{PROJECT}]({project}) (wandb.ai redirects to forge.coreweave.com/wandb/).",
             f"- **Runs:** {n_runs} = " + " + ".join(f"{len(b)} ({rid}: {len({r['config']['node'] for r in b})} nodes × "
                                                     f"{b[0]['config']['iterations']} twin iterations)" for rid, b in batches.items())
             + f"; one group per evaluation: {groups}. Runs of earlier evaluations stay in the project as `superseded` (never "
             "deleted) and every view filters them out; logging refuses a src/ with uncommitted changes, so each evaluation is a commit.",
             "- **Config on every run** (filter and group on any): `type`, `type_group`, `level`, `deployment`, `deployment_kind`, `rig`, "
             "`node`, `instance`, `can_id`, `twin_iteration`, `iteration`, `stage_role` (before / between / after), `model_rung`, "
             "`floor_kind`, `gains`, `split`, `evaluation`, `evaluation_state` (latest / superseded), `sim2real_sha`, `result_id`.",
             "- **Summary on each node's last iteration:** `verdict`, `stops_at`, `questions_passed` (0–5), `next_rung`, `rungs`; per "
             "question `<Q>/own`, `<Q>/pass`, `<Q>/numbers`, `<Q>/gate`; the numbers `Floor/floor_deg`, `Floor/pairs`, "
             "`Data/coverage_pct` (or `Data/cube_pct`, `Data/workspace_pct`, `Data/facing_pct`), `Twin/ratio`, `Twin/sim_real_after_deg`, "
             "`Twin/sim_real_before_deg`, `Job/settled_median_deg`, `Job/share_deg`, `Job/tool_settled_mm`; the held-out trend as history "
             "(`trend/heldout_median_deg` per `iteration`); W&B Tables `questions`, `curriculum`, `floors`, `models`, `parameters`, and on "
             "the deployment's run `tree`, `questions_all`, `curriculum_all`, `trend_all`.",
             "- **Saved views** (the workspace's view menu) and **reports**, one per type and per deployment, plus an overview:",
             ""]
    lines += ["| Slice | Saved view | Report |", "|---|---|---|"]
    for key in sorted(urls.get("views", {})):
        label = key.replace("type-", "type = ").replace("deployment-", "deployment = ")
        lines.append(f"| {label} | [view]({urls['views'][key]}) | [report]({urls['reports'].get(key, '')}) |")
    if "overview" in urls.get("reports", {}):
        lines.append(f"| everything | [project workspace]({project}) | [overview]({urls['reports']['overview']}) |")
    lines += ["", "Log a new evaluation (idempotent: the same numbers update the same runs; new numbers supersede them, nothing is "
              "deleted), rebuild the views and read it all back:", "",
              "```bash",
              "env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra tracking python -m sim2real.tracking.wandb_log --backfill --views --verify",
              "```"]
    if verify_log:
        kept = [line for line in verify_log.splitlines() if line.startswith(("  filter", "ur-", "five", "VERIFY", "  reports", "  registry"))]
        lines += ["", "The read-back through W&B's API (`--verify`), as run for this page:", "", "```text", *kept, "```"]
    return "\n".join(lines)


def build(verify_log: str | None, rig_verify_log: str | None = None) -> str:
    sha, dirty = code_version(REPO)
    results = {name: load(name) for name in ("ur_wrist", "fivebar")}
    rd = rig_data(results, sha, dirty)
    rig_urls = json.loads(rigs.REGISTRY.read_text()) if rigs.REGISTRY.exists() else {"reports": {}, "views": {}}
    rig_links = ", ".join(f"[{rig.project}]({href(f'https://wandb.ai/{ENTITY}/{rig.project}')})" for rig in rigs.RIGS.values())
    batches, afters, rungs = {}, {}, {}
    for name, result in results.items():
        batch = records(result, sha=sha, dirty=dirty, extra_config=RIG)
        batches[result.id] = batch
        afters[name] = [r for r in batch if r["config"]["stage_role"] == "after"]
        rungs[name] = curriculum.status(result)
    w = {r["config"]["instance"]: r for r in afters["ur_wrist"]}
    f = {r["config"]["instance"]: r for r in afters["fivebar"]}

    def num(record, key, fmt="{:.3f}"):
        value = record["history"][-1].get(key)
        return "—" if value is None else fmt.format(value)

    servo = sorted(r["config"]["node_label"].split(" (")[0] for b in afters.values() for r in b if r["config"]["type"] == "integrated_servo")
    stamp = f"sim2real `main` @ `{sha[:9]}`" + (" (with uncommitted changes in src/)" if dirty else "")
    fivebar_tool = f["tool"]["history"][-1]
    # the brief's tool number (sim2real 662e64d): 9.6 mm at the 16 settled holds on the nominal gravity compensation
    tool_now = fivebar_tool.get("Job/tool_settled_mm", float("nan"))
    tool_moved = abs(tool_now - 9.5588) > 0.05
    tool_bullet = (f"> - **Five-bar tool:** 9.6 mm at the 16 settled holds on the nominal gravity compensation → {tool_now:.1f} mm on the "
                   "identified one (`data/fivebar_dwell_identified_2026-11-11.json`); the tool's Job now reads the operating config, the "
                   "nominal run stays beside it.\n" if tool_moved else "")
    tool_unchanged = "" if tool_moved else f", the tool's {tool_now:.1f} mm"
    ratios = {joint: f[joint]["history"][-1].get("Job/settled_over_share") for joint in ("j2", "c1")}
    if all(ratios.values()):
        big, small = sorted(ratios, key=lambda joint: -ratios[joint])
        name = {"j2": "J2", "c1": "C1"}
        big_term = (f"{name[big]} is the bigger term: it settles {num(f[big], 'Job/settled_median_deg')}° from its target, "
                    f"{ratios[big]:.1f}× its {num(f[big], 'Job/share_deg')}° share ({name[small]}: {ratios[small]:.1f}×).")
    else:
        big_term = ""
    d435 = re.search(r"(\d+(?:\.\d+)?) mm median by the D435", f["arm"]["summary"].get("Job/numbers", ""))
    campaign = re.search(r"repeat campaign: (\d+(?:\.\d+)?)° median", w["can15"]["summary"].get("Job/numbers", ""))
    d435_text = f" ({d435.group(1)} mm by the D435)" if d435 else ""
    campaign_text = (f"; on the repeat campaign's gains it settles at {campaign.group(1)}°, "
                     + ("inside it" if float(campaign.group(1)) <= w["can15"]["history"][-1]["Job/share_deg"] else "also outside it")
                     if campaign and w["can15"]["history"][-1].get("Job/share_deg") else "")
    return f"""# Sim2Real: KPIs, gates and the curriculum

*{DATE} · status as of {stamp} · written by `docs/build_kpis_gates_curriculum.py` from `sim2real.rack_results.load(...)` through
`sim2real.tracking.wandb_log.records()`, the same records the W&B runs are made from · angles in degrees, lengths in mm*

## The answer

- **The KPIs are five questions every node of the tree answers in order: Floor → Data → Routines → Twin → Job.** A node's verdict is
  its first "no"; a parent passes a question only if it does at its own output and every child does. Each question has one hard gate;
  the numbers beside it are soft KPIs you push inside the gate.
- **UR wrist today:** CAN 16 *{w['can16']['summary']['verdict']}*. CAN 15 *{w['can15']['summary']['verdict']}*: it settles
  {num(w['can15'], 'Job/settled_median_deg')}° from its target against its {num(w['can15'], 'Job/share_deg')}° share of the 1 mm tool gate.
  CAN 14 *{w['can14']['summary']['verdict']}*: driven it is {num(w['can14'], 'Twin/ratio', '{:.2f}')}× its floor, but its passive
  release is {num(w['can14'], 'Twin/passive_ratio', '{:.1f}')}×. The arm, the holder board and the deployment read
  *{w['wrist']['summary']['verdict']}*: nothing revisits a tool stop yet.
- **Five-bar today:** J2 and C1 both read *{f['j2']['summary']['verdict']}* (only their gravity is graded on a hidden truth). Behind
  that, their twins are {num(f['j2'], 'Twin/ratio', '{:.2f}')}× and {num(f['c1'], 'Twin/ratio', '{:.2f}')}× their floors, and the tool
  settles {fivebar_tool.get('Job/tool_settled_mm', float('nan')):.1f} mm from its target against the 1 mm gate.
- **The curriculum is the same five answers climbed in work order:** S0 described → S1 routines recover a hidden truth in sim → S2 real
  floor → S3 coverage → S4 twin ≤ 1.5× floor → S5 job, at every joint; A0–A5 for an arm (tool repeats, the 1 mm tool gate), T0–T5 for
  a tool, D0–D5 for a deployment. A rung passes exactly when its question does.
- **Next rungs:** the wrist's holder board (T1: its TCP and payload graded in sim; T2: one stop revisited, the tool by encoders + FK), then CAN 14's
  passive twin (S4) and CAN 15's settled stop (S5). The five-bar's S1: grade friction, armature and delay in sim at 1× noise (the
  one-click seam the wrist got today), then its twin (S4) and the tool gate.
- **The gates, in Zach's order (2026-11-11 21:50), all from the joint encoders through FK:** target vs sim (the controller) →
  sim vs real (the twin, ≤ 1.5× the same-input floor on the tick clock) → target vs real (the tool ≤ 1 mm at a settled stop). ArUco is a
  flag, never a gate. UR wrist: {first_open(rd['ur_wrist'])}. Five-bar: {first_open(rd['fivebar'])}.
- **W&B, live: one project per rig**, {rig_links}, on bam_ws's `bam_trackio.bbo` template (Zach's direction, relayed by the W1 sprint),
  with the same gate names on both and `type`, `joint` and `deployment` config on every run; one W&B run per version of what is fitted
  (each twin iteration, each controller configuration). The one-project layout I first recommended (proposal B) stays in `{PROJECT}`
  ({sum(len(b) for b in batches.values())} runs; the filter `type = integrated_servo` returns the {len(servo)} servo joints of both rigs),
  and its filter-by-type view now lives on as the cross-rig report there.

> [!note] What moved since the brief (its numbers were sim2real `662e64d`)
> - **Wrist Routines:** the one-click seam (sim2real `82f14db`, wired in `7f8d13b`) recovers CAN 14 8/8, CAN 15 6/6, CAN 16 6/6 and the
>   arm's 2/2 identifiable parameters at 1× noise on a sealed truth, so no wrist joint stops at Routines any more.
> - **Joint Job** (`d626be9`): each joint's settled error is now held against its share of the 1 mm tool gate, 1 mm ÷ (lever × √joints)
>   (an RSS split, proposed): CAN 15 {num(w['can15'], 'Job/share_deg')}°, CAN 16 {num(w['can16'], 'Job/share_deg')}°, CAN 14
>   {num(w['can14'], 'Job/share_deg')}°; J2 {num(f['j2'], 'Job/share_deg')}°, C1 {num(f['c1'], 'Job/share_deg')}°.
> - **C1 coverage:** 34.1 % → {num(f['c1'], 'Data/coverage_pct', '{:.1f}')} % after seven C1 swings (`coverage_real_031652`, `7f8d13b`), so
>   C1 now stops at Routines like J2.
> - **Wrist workspace:** the source says 60.55 % (`multi3/multi_scores.json` real_all); the page prints it to one place as 60.5 %.
{tool_bullet}> - **Unchanged:** the floors ({num(w['can14'], 'Floor/floor_deg')} / {num(w['can15'], 'Floor/floor_deg')} /
>   {num(w['can16'], 'Floor/floor_deg')}° wrist, {num(f['j2'], 'Floor/floor_deg')} / {num(f['c1'], 'Floor/floor_deg')}° five-bar), the twin
>   ratios ({num(w['can14'], 'Twin/ratio', '{:.2f}')}× / {num(w['can15'], 'Twin/ratio', '{:.2f}')}× / {num(w['can16'], 'Twin/ratio', '{:.2f}')}×;
>   {num(f['j2'], 'Twin/ratio', '{:.2f}')}× / {num(f['c1'], 'Twin/ratio', '{:.2f}')}×){tool_unchanged}.

## 1 · The KPIs and gates (as decided 2026-11-11)

Proposal C of the vault note *Sim2Real KPIs and Gates — 3 Proposals and What Good Looks Like per Type (2026-11-11)*, as `result.py`
and `rack_results.py` implement it tonight.

| # | Question | It asks | Hard gate | Soft numbers beside it | Rule |
|---|---|---|---|---|---|
| 1 | **Floor** | How much does the real thing disagree with itself? | ≥ 5 repeats of one input per run kind; a pair counts only if its commands agree within 0.01° RMS, compared tick for tick when the run carries its plan tick; driven, and passive or N/A with a measured reason; twin ÷ floor never below 0.71 | floor (°), same-input pairs, runs, per run kind | decided; passive N/A proposed |
| 2 | **Data** | Is the data enough? | joint: ≥ 40 % of its reachable (angle, speed, acceleration) cells visited by real runs; arm: joint cube ≥ 90 %, workspace ≥ 50 %, facing or heading ≥ 90 % of the allowed mask; held-out split sealed before fitting; physical runs for a physical deployment | coverage %, samples, minutes logged | thresholds proposed |
| 3 | **Routines** | Does each calibration routine get a hidden truth back, in sim? | every identifiable value within its tolerance of a sealed truth at 1× the real sensor noise, the truth off the search grid; the nominal value fails its own tolerance; then the stress ladder (3×, 10×, delay and quantisation variants) | k of n identifiable recovered; error ÷ tolerance; wall and operator time | decided |
| 4 | **Twin** | Is the twin as good as reality allows? | held-out sim vs real ≤ 1.5× the floor **of the same run kind**, passive and driven (≤ 3× reads "close") | the ratio per run kind; before → after; how many times better than "it follows its target" | decided |
| 5 | **Job** | Does the real thing do its job? | joint: settled stop error within its share of the tool gate; tool: **≤ 1 mm at a stop**, on settled holds, at the tool by the joint encoders through FK (Zach, 21:50) | real vs target; feedback-torque share, RMS(τ − τ_ff) ÷ RMS(τ), falling (≤ 0.3 proposed); the sim predicting its own tracking | 1 mm decided (Zach); joint share proposed |

**How it rolls up**

- **The verdict is the first "no":** "stops at Data" means Floor passed and Data did not; the later answers are still computed and
  shown beside it.
- **A parent passes a question only if it answers yes at its own output (an arm at its tool pose, a deployment at its picks) and every
  child passes it** (`CalibrationResult.verdicts()`). So the deployment's line is the answer for the whole rig, and a joint that is
  twinned on its own cannot make an arm twinned whose coupled moves are not.
- **The numbers roll up softly:** medians of the children, the worst child's twin ratio, the tool in mm.

**The rules behind each gate**

- **Floor, from same-input repeats only** (`metrics.series.repeat_floor`). Repeats are grouped per run kind and controller gains (T1:
  like for like) and compared tick for tick when the run carries its plan tick: on the host's wall clock, ~1 ms of jitter put identical
  five-bar tapes 1.6–3.1° apart. **The floor check:** with each real run = truth + independent noise, floor² = 2σ² and gap² = bias² + σ²,
  so a twin cannot sit below 1/√2 ≈ 0.71× its floor; one that does fails *Floor* (its "repeats" were not repeats), it does not pass Twin.
- **Twin on the floor's own run kind:** the wrist's twin is judged on its repeat campaign's tape (`cycle-s4`, `cycle14-a`), the
  five-bar's on the five repeats of the 0.05 m/s gravity-feed-forward rung, replayed on the after twin.
- **Passive "N/A with a measured reason" (proposed, Zach to confirm):** a joint that cannot move unpowered answers N/A instead of
  failing Floor forever. CAN 15 and 16 carry at most 0.012 N·m of gravity against 0.140 and 0.186 N·m of breakaway; the five-bar's J2
  and C1 rest at the closure fold, where gravity cannot move them, and larger releases fall 40–80° at up to 1,300°/s.
- **Data thresholds (proposed, coordinator 2026-11-11, Zach to confirm):** per joint ≥ 40 % of reachable (angle, speed, acceleration)
  cells; arm: cube ≥ 90 %, workspace ≥ 50 %, facing (wrist) or heading (five-bar) ≥ 90 %. The joint's reachable cells come from its
  committed description; for these joints every cell of the box counts as reachable, so it is the visited share of the full box.
- **Routines means recovering the hidden truth, in sim, within tolerance, under noise:** the oracle's rule (`sysid/acceptance.json`):
  every hidden value within its tolerance at 1× sensor noise, and the nominal fails its own tolerance so "return the description
  unchanged" fails; the noise ladder (`sysid/noise_ladder.json`): 0×, 1×, 3×, 10×, bound min(k × tol, max(tol, |nominal − true|)).
- **Job: the tool gate is 1 mm at a stop** (Zach, 2026-11-11: "we certainly need final tool error sub 1mm", was 5 mm), **measured on
  settled holds**: the five-bar's 16 three-second mass-ID holds, not the raster's turnarounds (median 0.06 s: tracking, not settled). A
  joint's share of it is 1 mm ÷ (lever × √joints), an RSS split (proposed); `tools/tool_levers.py` measures each rig's lever.

**Still sized for 5 mm in code** (to re-derive at 1 mm; not changed here):

- `cards/domain_v3.json`: `arm.tool_error_at_stop.gate`, `pick.grasp_pose_error.gate` and `conveyor.object_position.gate` are ≤ 5 mm.
- `cards/servo_gates.py`: `STOP_ALLOCATION_MRAD` and T4's rule text allocate "the 5 mm tool gate" (about 3 mm RSS inside 5 mm).
- `sysid/acceptance.json`: tolerances are set for "a 5 mm tool budget"; the ur5e examples' held-out tool is 5 mm.

### 1.1 Zach's gate rulings (2026-11-11 21:50) and the same-named gates

- **Every gate and tracking error comes from the joint encoders through FK, never the camera.** The five-bar's tool at a stop is the
  16 settled holds through the encoders and the CAD lever (`encoders_fk_mm`); the D435's number (camera vs the commanded target) is kept
  beside it as a flag only, under a name no gate reads.
- **ArUco is a 6-DOF tracked point logged as a flag, never a gate** (`aruco_vs_fk_mm`: the tag vs the encoders' FK at the same instant;
  a large value says look at the stickers or the as-built geometry, it passes or fails nothing). Not measured yet on either rig.
- **The gate order: target vs sim first, then sim vs real, then target vs real.** Target vs sim is the controller alone (does the
  controller do the job in a sim that is right by construction?); sim vs real is the twin (held-out, ≤ 1.5× the same-input repeat floor
  on the tick clock, the tree's Twin answer); target vs real is the job. A later gate is read only after the earlier ones: a real tool
  error cannot be blamed on the twin until the controller passes in sim.
- **Tool gate 1 mm at a settled stop.** `target_vs_real_at_stop_mm` is the same number as `tool_error_at_stop_mm` under its gate-order
  name; `target_vs_sim_at_stop_mm` holds the controller to the same 1 mm in sim (proposed: the sim must pass before the real rig can).

**The gates, one metric name each on both rig projects** (`sim2real.tracking.rigs.GATES`; "today" is the latest version that measures
it: the latest twin for the twin gate, the last controller configuration that ran for the rest):

{gates_table(rd)}

**Read in that order, today:**

- **UR wrist:** {first_open(rd['ur_wrist'])}. The controller in sim on the operating gains (pick_sliding) tracks to
  {latest(rd['ur_wrist'], 'target_vs_sim_tracking_deg')[0]:.3f}° (worst joint, held-out runs on the twin of
  record), the real joints to {latest(rd['ur_wrist'], 'tracking_rms_deg')[0]:.3f}°. At a stop the twin's holder passes 1 mm and the real one
  just misses it ({latest(rd['ur_wrist'], 'tool_error_at_stop_mm')[0]:.2f} mm; twin vs real {latest(rd['ur_wrist'], 'sim_vs_real_at_stop_mm')[0]:.2f} mm at the same stops), so the first fix is the twin (CAN 14's passive
  release) and a tool floor, not the controller.
- **Five-bar:** {first_open(rd['fivebar'])}. Gate 1 fails first: the controller misses the tool gate in a sim that is right by
  construction ({latest(rd['fivebar'], 'target_vs_sim_at_stop_mm')[0]:.2f} mm vs the real arm's {latest(rd['fivebar'], 'tool_error_at_stop_mm')[0]:.2f} mm), so
  the tool gap is the controller's (gains, compensation, hold logic) before it is the twin's; the twin's tool is
  {latest(rd['fivebar'], 'sim_vs_real_at_stop_mm')[0]:.2f} mm from the real one at the same holds. Coulomb feed-forward is a controller change, and it shows first in gate 1: target vs sim
  went {rd['fivebar']['versions'][1]['numbers']['target_vs_sim_tracking_deg']:.2f}° → {rd['fivebar']['versions'][2]['numbers']['target_vs_sim_tracking_deg']:.2f}°
  (worst joint) and the sim's tool {rd['fivebar']['versions'][1]['numbers']['target_vs_sim_tracking_tool_mm']:.1f} → {rd['fivebar']['versions'][2]['numbers']['target_vs_sim_tracking_tool_mm']:.1f} mm,
  before the real tool's {rd['fivebar']['versions'][1]['numbers']['tracking_rms_tool_mm']:.1f} → {rd['fivebar']['versions'][2]['numbers']['tracking_rms_tool_mm']:.1f} mm.

**Controller versions, UR wrist** (target vs sim: bam_ur_wrist_coverage's own score on the twin of record, held-out runs, CAN 15 and 16
only; target vs real: each coverage run's RMS per joint, averaged):

{controller_table(rd['ur_wrist'])}

**Controller versions, five-bar** (tracking: each coverage rung's own metrics, the real run and the sim the ladder ran beside it on the
same plan, averaged over the rungs; the tool at a stop: the 16 three-second holds, last second scored):

{controller_table(rd['fivebar'])}

## 2 · The curriculum

**How to read it.** The verdict reads the five questions in *check* order (Floor first: a wrong floor makes every later number
meaningless). The ladder is climbed in *work* order: Routines first, because it needs no rig time (prove a routine on a hidden truth in
sim before trusting it on hardware), then the rig rungs from cheapest to dearest. A rung passes exactly when its question passes, so the
two orders read the same answers; "next rung" and "stops at" can name different questions only when more than one is open. Today they
agree on every node. `sim2real.tracking.curriculum` holds the ladders; each W&B run carries its node's rungs.

### 2.1 The ladders

{ladder_tables()}

### 2.2 What each rung means, per generic type

The rungs are the same for every type; what changes is each gate's number. Tolerances are the oracle's (`sysid/acceptance.json`), hard
gates are `cards/domain_v3.json`'s; *proposed* marks a number no code holds yet.

| Type | S1 · Routines (tolerance at 1× noise) | S2 · Floor (what repeats) | S3 · Data (cells, ≥ 40 %) | S4 · Twin (≤ 1.5× floor) | S5 · Job (hard gate) |
|---|---|---|---|---|---|
| **integrated_servo** | gravity 2 %, gravity zero 0.29°, armature 5 %, Coulomb 10 %, Stribeck drop 25 % and speed 30 %, viscous 20 %, backlash 10 % (pendulum_can11) | one tape ×5, per run kind and gains | (angle, speed, acceleration) at the output | held-out angle, passive and driven; current ≤ 2× its scatter in closed loop (T3) | settled stop within its share of the 1 mm tool gate (T4); feedback share |
| **bldc_motor** | torque per amp, phase resistance (Kt ≤ 2 %, proposed) | dyno shaft torque, or current scatter | (angle, speed, acceleration) at the shaft | shaft torque; winding ≤ 5 °C | Kt within 5 % (T6); share of the datasheet speed-torque curve |
| **gearbox** | backlash 0.033° (2 arcmin) or 10 % | the hysteresis loop's 95 % half-width (T5) | (angle, speed, acceleration) at the output | output angle for the same input (needs an output encoder; a camera tag only as a flag) | lost motion ≤ 0.033° (2 arcmin) |
| **foc_controller** | command delay (≤ 1 ms, proposed); current-loop bandwidth | q-current scatter on one command | (q-current, speed) map | q-current ≤ 2× scatter; board temperature ≤ 5 °C | torque-cap share (≤ 1 %, proposed); loop rate ±10 % |
| **encoder** | quantisation known; eccentricity 10 % (proposed) | standstill spread; homing repeats | (angle, speed) | noise and quantisation spectrum | homing repeatability |
| **rigid_body_chain** | joint zeros 0.029°, armature 10 %, damping 20 %, friction 10 %, mounts 1 mm / 0.057° | the same tool pose revisited (ISO 9283 RP) | joint cube ≥ 90 %, workspace ≥ 50 %, facing ≥ 90 % (proposed) | tool pose ≤ 1.5× the tool floor | tool ≤ 1 mm at a stop, settled, at the tool |
| **gripper** | actuator gain 5 %, finger damping 15 % | the same grasp revisited | the arm's coverage at grasp poses | grasp pose ≤ 1.5× | grasp pose ≤ 5 mm in the card (to re-derive at 1 mm); picks per minute |
| **conveyor** | drum radius 0.1 %, moving mass 10 %, viscous 15 %, Coulomb 10 % | belt position run to run on one profile | (belt speed, load mass) | belt position ≤ 1.5× | object position ≤ 5 mm in the card |
| **camera** | pose 2 mm / 0.11°, focal 0.5 %, principal point 2 px | a static scene frame to frame; corner jitter | distance × incidence × light × material × exposure | sim overlay ≤ 1.5× | reprojection ≤ 0.5 px |
| **depth_camera** | depth scale 0.2 %, depth offset 1 mm, plus the camera's | temporal noise on a flat target | as the camera | cloud vs sim ≤ 1.5× | Z within 1 % of Z, plane RMS ≤ 0.4 % of Z, fill ≥ 99 % |
| **hyperspectral_camera** | focal 1 %, principal point 1 px, height 3 mm, across 1 mm, scan line 1 mm, scan yaw 0.11°, gain 2 %, dark 2 counts | the spectral angle between repeat cubes | × wavelength band × material class | rendered cube ≤ 1.5× | smile and keystone ≤ 1 px |
| **tool** (structural) | mass 5 %, centre of mass 3 mm, TCP 0.5 mm across, 1 mm along | the same stop revisited, encoders + FK | the TCP seen from spread poses | the after twin's tool ≤ 1.5× the tool floor | ≤ 1 mm at a stop, settled |
| **deployment** (structural) | every child's routines | its output repeated: the same scene twice | physical runs from every routine in its schedule | sim ranks policies like reality (r > 0.9, proposed) | picks per minute; tool ≤ 1 mm |

### 2.3 Today, per rig

✓ passes · ✗ no · ~ partial · ? unknown · ↓ its own answer is yes, a child holds it back. Each cell is the question's mark and its
headline number; the full text of every answer is on the result page (`load(...).display()`) and in each W&B run's `<Q>/numbers`.

**UR wrist on the One Dof Test Rack** (twins: {' → '.join(results['ur_wrist'].stages)})

{status_table(afters['ur_wrist'], rungs['ur_wrist'])}

Held-out sim → real median per twin iteration (held-out runs in brackets): the it3 refit got *worse* on held-out tapes while its all-run
median improved (an overfit), before it5 + gravity brought it to about 0.12°.

{trend_table(results['ur_wrist'])}

**Five-bar on the One Dof Test Rack** (twins: {' → '.join(results['fivebar'].stages)})

{status_table(afters['fivebar'], rungs['fivebar'])}

Held-out sim → real median per twin iteration (the study twin scored every rung; the refits scored their own held-out rungs, so the
counts differ):

{trend_table(results['fivebar'])}

### 2.4 The next rung per rig

**UR wrist**

1. **The holder board, T1 and T2.** It is the one node with no evidence at all ("no tool runs: the holder board is not tracked"), and
   it holds back the arm (A1, A2) and the deployment (D1, D2). T1: grade its TCP and payload on a sealed truth in sim, the way the
   one-click seam already grades the joints. T2: revisit one commanded stop ≥ 5 times, the holder's point by the joint encoders through FK (ISO 9283 RP); a tag on it is
   logged beside it as a flag.
2. **CAN 14, S4 (passive twin).** Driven it is {num(w['can14'], 'Twin/ratio', '{:.2f}')}× its floor. On its passive release
   (`release60`: let go near 142°, the real joint swings and rests near 80°) the twin rests 34.5° away from the real joint, which is
   {num(w['can14'], 'Twin/passive_ratio', '{:.1f}')}× its {num(w['can14'], 'Floor/passive_floor_deg')}° passive floor: the released
   joint's gravity or breakaway model is wrong.
3. **CAN 15, S5 (settled stop).** {num(w['can15'], 'Job/settled_median_deg')}° median on its operating gains (pick_sliding) against its
   {num(w['can15'], 'Job/share_deg')}° share{campaign_text}.

**Five-bar**

1. **J2 and C1, S1.** Only the gravity is graded on a hidden truth (`bam_fivebar tests/test_massid.py`). Port the wrist's one-click seam
   (`Twin.load(...).calibrate(on='sim', truth='sealed')` at 1× noise) so friction, armature and delay are graded too; the arm's A1 and
   the tool's T1 come with it.
2. **Then S4.** The after twin is {num(f['j2'], 'Twin/ratio', '{:.2f}')}× (J2) and {num(f['c1'], 'Twin/ratio', '{:.2f}')}× (C1) its floor
   on the floor's own tape; the gate is 1.5×.
3. **Then the tool gate (A5, T5).** The tool settles {fivebar_tool.get('Job/tool_settled_mm', float('nan')):.1f} mm from its target by
   encoders + FK{d435_text} against 1 mm. {big_term}

## 3 · Tracking it in W&B: three proposals

**Your question:** "Should we have one weights and biases project per generic type? This could be a lot of projects. But I guess for
each one it's a bit unique, no? OK, having it in one location could work, if we can filter that data to show it for particular types
of models or something…"

**What the question assumes:**

- **"A lot of projects" is the cheap part of the cost.** The dear part is that per-type projects split one rig's tree: the wrist's
  deployment, arm, three joints and holder would land in four projects. "A parent passes only if every child does" would then be
  visible nowhere, and a W&B workspace cannot hold runs from two projects (only a report can).
- **"Each one is a bit unique": less than it looks.** Every node answers the same five questions with the same words; that is the
  point of proposal C. What is unique per type is its Job metric and unit (px, mm, °, %) and its coverage axes: config and summary
  keys, data rather than structure.
- **What a W&B run is.** Not a rig run (the wrist calibration has 400+); those stay in the archive, on the result page and in Rerun
  (the house rule: "we own our data … W&B only ever gets a copy"). A W&B run is one node's evaluation at one twin iteration, so W&B
  tracks the verdicts and their numbers over time.

**Criteria, weighted for now:**

| # | Criterion | Weight | Why it matters now |
|---|---|---:|---|
| 1 | **One place, filterable at a glance** | 25 | your worry, and "at a glance I can look at any level, and navigate that with the tree" |
| 2 | **Like with like, across rigs and within one** | 20 | a servo type is judged across its units (`TYPE_GATES` T1–T8 vs `UNIT_GATES`); a rig across its types (the roll-up) |
| 3 | **Keeps the tree and its roll-up together** | 15 | the verdict rolls up deployment → arm → joint → tool |
| 4 | **Cost of growth** | 15 | 11 generic and 6 structural types today; deployments multiply fastest (every rig, every customer cell) |
| 5 | **Type-specific numbers stay honest** | 10 | px, mm, ° and % must never share an axis |
| 6 | **House conventions** | 10 | entity `{ENTITY}`; Title Case project names ("Traj Gen", "Grasp Detection"); views and reports built from code |
| 7 | **Sharing one deployment outside** | 5 | W&B permissions are per project; a customer's cell may be shared one day |

**A · One project per generic type** ("Integrated Servo", "Gearbox", "Camera", "Conveyor", "Rigid Body Chain", … up to 17)

- *For:* one schema per project and a clean auto-made workspace; one type compares across rigs natively. It mirrors today's split of
  the pick-place ladder into "Grasp Detection" and "Traj Gen".
- *Against:* a rig's tree is spread over 4–6 projects and its roll-up is visible nowhere; a deployment view needs a cross-project
  report; every new type is a new project with its own views.
- *Scores:* one place 1 · like with like 3 (across rigs 5, within a rig 1) · tree 1 · growth 2 · honest numbers 5 · house 4 · sharing 2.

**B · One project, `{PROJECT}`, every run configured and filtered** (recommended on these criteria and built first; superseded as the home by C per rig, below)

- *For:* filter `type = integrated_servo` and get every servo on every rig; `deployment = fivebar` and get its whole tree; group by
  either; one overview over everything. A new type or deployment is a new config value; its view and report are generated from the runs
  present (`build_views`).
- *Against:* one key namespace, so type-specific keys sit sparse beside each other. Kept honest by units in every key name (`_deg`,
  `_mm`, `_pct`) and by per-type views that chart only that type's keys.
- *Scores:* one place 5 · like with like 5 · tree 5 · growth 4 · honest numbers 3 · house 4 · sharing 3.

**C · One project per deployment** ("UR Wrist Test Rig", "Five-bar Test Rig", "Conveyor", …), types as config

- *For:* it mirrors `result.display()`: one tree per project; sharing one customer's cell is clean.
- *Against:* a type across rigs needs a cross-project report; deployments are the fastest-growing count; the house's own deployment
  mirror (bam_ws `bam_deployments`, project `bam-deployments`) is one project grouped by deployment, not one per deployment.
- *Scores:* one place 3 · like with like 2 · tree 5 · growth 2 · honest numbers 3 · house 3 · sharing 5.

| Criterion (weight) | A · per type | B · one project | C · per deployment |
|---|---:|---:|---:|
| One place, filterable (25) | 1 | **5** | 3 |
| Like with like (20) | 3 | **5** | 2 |
| Tree and roll-up together (15) | 1 | **5** | **5** |
| Cost of growth (15) | 2 | **4** | 2 |
| Type numbers honest (10) | **5** | 3 | 3 |
| House conventions (10) | **4** | **4** | 3 |
| Sharing outside (5) | 2 | 3 | **5** |
| **Total (of 100)** | **46** | **89** | **61** |

**My recommendation on these criteria was B** (89), and it was built first. **What is live is C, per rig, with B's config on every
run**, because you set the direction tonight (relayed by the W1 sprint): bottom-up per sub-assembly, each rig introspected through W&B
and Rerun, in projects named "Sim2Real · five-bar rig" and "Sim2Real · wrist rig" on the house black-box template (bam_ws
`bam_trackio.bbo`: one W&B project per black-box family, its versions on leaderboards). Your call outranks my scoring, and the
criteria above did not weigh what it adds:

- **One leaderboard per sub-assembly.** A rig is the black box being optimised; its twin iterations and controller configurations are
  its versions, ranked on the same environment. In one shared project those leaderboards would sit side by side with no owner.
- **What C costs against B, and how it is paid:** a workspace cannot filter across rigs, so "every servo on every rig" is a report, not
  a filter: the cross-rig report in `{PROJECT}` takes one runset per rig, each filtered `type = integrated_servo`, and charts the
  same-named gates side by side. Every run carries `type`, `level`, `deployment` and `joint`, so any new cross-rig report is one filter.
- **Decision record:** `docs/decision-wandb-one-project-2026-11-11.md`, amended: B is superseded as the home by C per rig; B's runs stay
  in `{PROJECT}` (nothing is deleted) and `wandb_log` still logs that layout.

- **Reversible either way:** the per-rig projects are `rigs.RIGS[...].project`, the one-project layout is `wandb_log.PROJECT`; both are
  written from the same records, so going back to B is one command and no data moves.
- **Steelman for A:** you split the pick-place ladder into two projects today because "we are optimizing them separately". That split
  is between two products with a contract between them and two scoreboards; sim2real has one scoreboard at every level, and splitting it
  by type would break the roll-up the scoreboard is made of.
- **What would change my mind:** a customer who may see only their own cell (C for customer cells); one type's media (camera frames,
  hyperspectral cubes) swamping the shared workspace even with views (that type's media in its own project, its verdict still here);
  W&B filters slowing down at scale (untested past a few hundred runs).

### What is in W&B now

**The per-rig projects (live, proposal C):**

{rig_wandb_section(rd, rig_verify_log)}

**The one-project layout (proposal B), kept in `{PROJECT}`:**

{wandb_section(batches, verify_log)}

Not done: the reports and views were read back through the API (blocks, panels, filters), not looked at in a signed-in browser; no
run was deleted.

## Sources

- **Decision:** vault `Projects/robot_msgs/Sim2Real KPIs and Gates — 3 Proposals and What Good Looks Like per Type (2026-11-11).md`
  (proposal C, the per-type tables).
- **Code (sim2real):** `src/sim2real/result.py` (`QUESTIONS`, `FLOOR_CHECK`, `RULER_TWINNED` 1.5, `RULER_CLOSE` 3.0, `TOOL_GATE_MM` 1.0,
  `verdicts()`), `src/sim2real/rack_results.py` (both rigs' trees, the passive N/A reasons, the joint shares), `src/sim2real/metrics/series.py`
  (`repeat_floor`, `SAME_INPUT_TOLERANCE_RAD` 0.01°, `FLOOR_MIN_REPEATS` 5), `src/sim2real/cards/servo_gates.py` (T1–T11,
  `MINIMUM_COVERAGE_PCT` 40, `TYPE_GATES`, `UNIT_GATES`), `src/sim2real/cards/schema.py` (`TWINNED_LIMIT`, `DRIFT_THRESHOLD` 1.25),
  `src/sim2real/cards/ladders.py` (`LEARNED_PCT` 95, `LEARNED_SAMPLES` 200, `DEPLOYED_PCT` 99), `src/sim2real/cards/domain_v3.json` (11
  types, their gates and coverage), `src/sim2real/cards/calibration.py` (the routines), `sysid/acceptance.json`, `sysid/noise_ladder.json`.
- **Data (read-only):** `/archive/datasets/bam_rig/rack_2026-11-10/ur_wrist/` (`repeat_floor/floor_scores.json`, `twin_scores.json`,
  `coverage/summary_real.json`, `coverage/multi3/multi_scores.json`, `coverage/refit_rig/it5/refit.json`),
  `/archive/datasets/bam_rig/rack_2026-11-10/fivebar_real/` (the ladders, the refits, `refit_repeats_025953/after_twin.json`),
  `src/sim2real/data/fivebar_dwell_2026-11-11.json`, `ur_wrist_one_click_2026-11-11.json`, `tool_levers_2026-11-11.json`.
- **This page's code:** `src/sim2real/tracking/curriculum.py`, `src/sim2real/tracking/wandb_log.py`, `docs/build_kpis_gates_curriculum.py`,
  `tests/test_tracking.py`.
"""


CSS = """
:root{--bg:#fbfbf9;--fg:#1d1d1b;--mut:#6b6b66;--line:#e2e1dc;--card:#ffffff;--accent:#2f8a4f;--code:#f2f1ec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--fg:#ecebe6;--mut:#a3a29b;--line:#34332f;--card:#1e1e1c;--accent:#5cc27e;--code:#262623}}
:root[data-theme="dark"]{--bg:#161615;--fg:#ecebe6;--mut:#a3a29b;--line:#34332f;--card:#1e1e1c;--accent:#5cc27e;--code:#262623}
html{background:var(--bg)}body{margin:0 auto;max-width:1180px;padding:20px 16px 48px;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
h1{font-size:26px;margin:4px 0 6px}h2{font-size:20px;margin:30px 0 8px;padding-top:10px;border-top:1px solid var(--line)}
h3{font-size:16.5px;margin:22px 0 6px}a{color:var(--accent)}p,li{max-width:96ch}
table{border-collapse:collapse;margin:10px 0 16px;font-size:13px;display:block;overflow-x:auto;max-width:100%}
th,td{border:1px solid var(--line);padding:5px 8px;vertical-align:top;text-align:left}th{background:var(--code)}
tbody tr:nth-child(even){background:color-mix(in srgb,var(--code) 45%,transparent)}
code{background:var(--code);padding:1px 4px;border-radius:4px;font-size:12.5px}pre{background:var(--code);padding:10px 12px;border-radius:6px;overflow-x:auto}
pre code{padding:0}blockquote{margin:12px 0;padding:8px 14px;border-left:3px solid var(--accent);background:var(--card)}
blockquote p{margin:4px 0}em{color:var(--mut)}
"""


def render_html(markdown: str) -> None:
    """Pandoc (GFM in, one standalone HTML file out, the stylesheet inline): opens from disk, no server, works offline."""
    import tempfile

    # WHY the callout rewritten: pandoc has no "[!note]" admonitions; a plain blockquote with a bold first line reads the same
    body = re.sub(r"^> \[!note\] (.*)$", r"> **\1**", markdown, flags=re.M)
    with tempfile.TemporaryDirectory() as folder:
        # WHY a .css name: --embed-resources types the inlined file by its extension; a ".tmp" sheet went in as octet-stream and
        # the browser ignored it (2026-11-11 render)
        style = Path(folder) / "page.css"
        style.write_text(CSS)
        subprocess.run(["pandoc", "-f", "gfm", "-t", "html5", "--standalone", "--embed-resources", f"--css={style}",
                        "--metadata", "pagetitle=Sim2Real KPIs and curriculum", "-o", str(HTML)], input=body, text=True, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verify-log", type=Path, help="the output of `python -m sim2real.tracking.wandb_log --verify`, embedded on the page")
    parser.add_argument("--rig-verify-log", type=Path, help="the output of `python -m sim2real.tracking.rigs --verify`, embedded on the page")
    args = parser.parse_args()
    verify_log = args.verify_log.read_text() if args.verify_log and args.verify_log.exists() else None
    rig_verify_log = args.rig_verify_log.read_text() if args.rig_verify_log and args.rig_verify_log.exists() else None
    text = build(verify_log, rig_verify_log)
    OUT.write_text(text)
    COPY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT, COPY)
    render_html(text)
    print(OUT, COPY, HTML, sep="\n")


if __name__ == "__main__":
    main()
