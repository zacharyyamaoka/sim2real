"""Log a CalibrationResult to Weights & Biases: ONE project, one run per node of the tree per twin iteration (2026-11-11).

    env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra tracking python -m sim2real.tracking.wandb_log --backfill --views --verify

Zach (2026-11-11): "Should we have one weights and biases project per generic type? This could be a lot of projects ... having it in one
location could work, if we can filter that data to show it for particular types of models". Decision (proposal B, scored in
docs/KPIS_GATES_CURRICULUM.md section 3; decision record docs/decision-wandb-one-project-2026-11-11.md): one project, "Sim2Real"; every
run carries its node's type, level, deployment and twin iteration as config, and one saved view plus one report per type and per
deployment filter on them. Do not re-split by type: the per-type views already show one type alone, and a split scatters each rig's tree.

What a run is: one node of the result's typed tree (deployment -> arm -> joint -> tool) at one twin iteration (result.stages) of one
evaluation. The last iteration's run carries the five answers (proposal C: Floor -> Data -> Routines -> Twin -> Job, the verdict is the
first "no"), their soft numbers and the node's curriculum rungs, and logs the held-out sim->real of every iteration as its history (so
a line chart shows the trend); each earlier iteration is a run of its own carrying its twin's held-out sim->real. The deployment's last
run also carries the whole tree, every node's five questions and the curriculum as W&B Tables.

Nothing is recomputed: every number is the result tree's own (verdicts(), tables(), Node fields). wandb and wandb-workspaces are imported
only inside the functions that talk to W&B (the `tracking` extra), so sim2real never depends on them.

Layer: like result.py, right of every folder (tests/test_layers.py); nothing in sim2real imports this module.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import curriculum

ENTITY = "zach-yamaoka-independent"   # the entity every BAM project logs to (bam_ws bam_trackio.wandb_view.ENTITY)
# WHY "Sim2Real": the house's curriculum projects are named in Title Case words ("Traj Gen", which Zach made himself, and "Grasp
# Detection"); one word, so the URL needs no quoting
PROJECT = "Sim2Real"
REPO = Path(__file__).resolve().parents[3]
WANDB_DIR = Path.home() / ".cache" / "sim2real" / "wandb"      # W&B's local run files: a cache, never the repo
REGISTRY = Path(__file__).resolve().parent / "wandb_views.json"  # report and view URLs, so a rebuild updates them in place
DOMAIN = Path(__file__).resolve().parents[1] / "cards" / "domain_v3.json"
# WHY a kind fallback: the result tree's Node.type is sometimes the description's own words ("robot arm", "Tool (payload + TCP)");
# the filterable `type` must be a sim2real type id (domain_v3.json's entity_types and structural nodes)
KIND_TYPE = {"deployment": "deployment", "arm": "rigid_body_chain", "tool": "tool"}
STAGE_ROLES = ("before", "between", "after")


# ---------------------------------------------------------------------------------------------------------------- pure: records


def type_ids() -> dict[str, str]:
    """sim2real type id -> its group (actuator | sensor | structural), from domain_v3.json."""
    domain = json.loads(DOMAIN.read_text())
    out = {t["id"]: t.get("group", "") for t in domain["entity_types"]}
    out.update({name: "structural" for name in domain.get("structural", {})})
    return out


def type_of(node, known: dict[str, str]) -> str:
    return node.type if node.type in known else KIND_TYPE.get(node.kind, node.type or node.kind)


_LEADING_PCT = re.compile(r"^\s*(\d+(?:\.\d+)?) % of (\d+) reachable")
_NAMED_PCT = re.compile(r"(joint cube|workspace|facing|heading)\b[^;%]*?(\d+(?:\.\d+)?) % of allowed")
_RATIO = re.compile(r"= (\d+(?:\.\d+)?)×")
_SETTLED = re.compile(r"settled (\d+(?:\.\d+)?)° median, (\d+(?:\.\d+)?)° p95 over (\d+) .*? vs its share (\d+(?:\.\d+)?)°"
                      r"(?: \((\d+(?:\.\d+)?)×\))?")


def percentages(text: str) -> dict[str, float]:
    """The Data answer's coverage numbers, read from its own text ("45.7 % of 1716 reachable ...", "joint cube 100.0 % of allowed ...").
    WHY parsed (2026-11-11): the Data answer carries its number only in its text today, and rack_results.py was a peer's in-flight file;
    an answer that carries a `metrics` dict wins over this (summary_numbers), so parsing retires itself once the tree is structured."""
    out: dict[str, float] = {}
    lead = _LEADING_PCT.match(text or "")
    if lead:
        out["coverage_pct"], out["reachable_cells"] = float(lead.group(1)), int(lead.group(2))
    for name, value in _NAMED_PCT.findall(text or ""):
        out[name.replace("joint ", "").replace(" ", "_") + "_pct"] = float(value)
    return out


def worst_ratio(text: str) -> float | None:
    """The largest "= N×" in an answer's text (the tool's Twin lists one ratio per run kind); None when it has none."""
    found = [float(v) for v in _RATIO.findall(text or "")]
    return max(found) if found else None


def settled(text: str) -> dict[str, float]:
    """A joint's Job numbers from its own text ("settled 0.339° median, 0.551° p95 over 9812 settled rows ... vs its share 0.329°"):
    the settled stop error against its share of the tool gate. Empty when the answer has none (same WHY as percentages)."""
    found = _SETTLED.search(text or "")
    if not found:
        return {}
    median, p95, n, share = float(found.group(1)), float(found.group(2)), int(found.group(3)), float(found.group(4))
    # WHY the text's own ratio: it divides the unrounded numbers; dividing the printed ones gave 18.7× for the tree's 18.6×
    return {"settled_median_deg": median, "settled_p95_deg": p95, "settled_n": n, "share_deg": share,
            "settled_over_share": float(found.group(5)) if found.group(5) else None}


def digest(result, tables: dict) -> str:
    """A content id for one evaluation: the same numbers give the same id (a re-run updates the same runs), new numbers a new evaluation."""
    payload = {"id": result.id, "stages": result.stages,
               **{name: tables[name] for name in ("nodes", "questions", "floors", "error_stats") if name in tables}}
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:10]


def run_id(*parts: str) -> str:
    """A stable W&B run id (the house's rule, bam_trackio.wandb_view.wandb_id_text): 16 hex characters of a sha1."""
    return hashlib.sha1("|".join(("sim2real", *parts)).encode()).hexdigest()[:16]


def _floor_rows(node) -> tuple[dict | None, dict | None]:
    """The node's driven floor row (the one result.verdicts divides by) and its passive one, from Node.floors."""
    driven = [r for r in node.floors if r.get("mode") == "driven"]
    chosen = None
    if node.floor_deg is not None:
        chosen = next((r for r in driven if r.get("known") and r.get("floor_deg") is not None
                       and abs(r["floor_deg"] - node.floor_deg) < 5e-4), None)
    if chosen is None and driven:
        chosen = max(driven, key=lambda r: (bool(r.get("known")), r.get("pairs") or 0))
    passive = next((r for r in node.floors if r.get("mode") == "passive" and r.get("known")), None)
    return chosen, passive


def summary_numbers(node, verdict: dict, questions: tuple[str, ...]) -> tuple[dict[str, float], dict[str, str]]:
    """A node's five answers and its soft numbers: (numbers for charts, text for the runs table). All read off the tree."""
    from ..result import verdict_of

    answers = verdict["answers"]
    passed = next((index for index, q in enumerate(questions) if not answers[q]["passes"]), len(questions))
    numbers: dict[str, Any] = {"questions_passed": passed, "passes_all": int(verdict["stops_at"] is None)}
    text: dict[str, str] = {"verdict": verdict["verdict"], "stops_at": verdict["stops_at"] or "", "why": verdict["why"]}
    for q in questions:
        answer = answers[q]
        numbers[f"{q}/pass"] = int(bool(answer["passes"]))
        text[f"{q}/own"] = answer["own"]
        text[f"{q}/numbers"] = answer.get("numbers", "")
        text[f"{q}/gate"] = answer.get("gate", "")
        text[f"{q}/children_not_passing"] = ", ".join(answer.get("failing_children", []))
        for key, value in (answer.get("metrics") or {}).items():   # a structured answer, when the tree carries one
            numbers[f"{q}/{key}"] = value
    driven, passive = _floor_rows(node)
    numbers["Floor/floor_deg"] = node.floor_deg
    if driven:
        numbers["Floor/pairs"], numbers["Floor/runs"] = driven.get("pairs"), driven.get("runs")
        text["Floor/kind"] = driven.get("kind", "")
    if passive:
        numbers["Floor/passive_floor_deg"] = passive.get("floor_deg")
        numbers["Twin/passive_ratio"] = passive.get("twin_over_floor")
    if not (answers["Data"].get("metrics")):
        numbers.update({f"Data/{key}": value for key, value in percentages(answers["Data"].get("numbers", "")).items()})
    ratio = node.twin_ratio if node.twin_ratio is not None else (worst_ratio(answers["Twin"].get("numbers", "")) if node.kind == "tool" else None)
    numbers["Twin/ratio"] = ratio
    text["Twin/band"] = verdict_of(ratio) if ratio is not None else "no ratio"
    numbers["Twin/twin_deg"] = driven.get("twin_deg") if driven else None
    numbers["Twin/sim_real_after_deg"] = verdict.get("sim_real_deg")
    numbers["Twin/sim_real_before_deg"] = verdict.get("sim_real_before_deg")
    numbers["Twin/held_out_runs"] = verdict.get("held_out_runs")
    numbers["Job/target_real_deg"] = verdict.get("target_real_deg")
    if not answers["Job"].get("metrics"):
        numbers.update({f"Job/{key}": value for key, value in settled(answers["Job"].get("numbers", "")).items()})
    gate = node.gate or {}
    if gate:
        numbers["Job/tool_settled_mm"] = gate.get("target_real_mm")
        numbers["Job/tool_gate_mm"] = gate.get("gate_mm")
        numbers["Job/tool_twin_at_stops_mm"] = gate.get("sim_real_mm")
    return numbers, text


def records(result, *, sha: str = "unknown", dirty: bool = False, extra_config: dict | None = None, now: str | None = None,
            add=None) -> list[dict]:
    """The W&B runs one CalibrationResult makes, as plain dicts (no wandb needed): one per node x twin iteration.

    Each: {id, name, group, job_type, tags, notes, config, history: [step dicts], summary: {text}, tables: {name: rows}}.
    `add(node, k, role)` may return (numbers, text, tables) to add to that run (the per-rig projects' gates, tracking/rigs.py)."""
    from ..result import QUESTIONS, RULER_TWINNED, TOOL_GATE_MM

    verdicts = result.verdicts()
    tables = result.tables()
    evaluation = digest(result, tables)
    rungs = curriculum.status(result, verdicts)
    stats = {(row["node"], row["stage"], row["scope"]): row for row in tables["error_stats"]}
    known = type_ids()
    root = next(n for n in result.nodes if n.parent is None)
    stages = list(result.stages)
    last = len(stages) - 1
    now = now or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    extra = dict(extra_config or {})
    out = []
    for node in result.nodes:
        verdict = verdicts[node.id]
        type_id = type_of(node, known)
        can = re.search(r"CAN (\d+)", node.label)
        picked = next((m["model"] for m in node.models if m.get("picked")), "")
        driven, _passive = _floor_rows(node)
        base = {
            "result_id": result.id, "result_title": result.title, "evaluation": evaluation, "evaluation_state": "latest",
            "sim2real_sha": sha, "sim2real_dirty": bool(dirty), "evaluated_at": now, "source": result.source,
            "deployment": root.id, "deployment_label": root.label,
            "node": node.id, "node_label": node.label, "parent": node.parent or "", "depth": node.id.count("/"),
            "level": node.kind, "type": type_id, "type_group": known.get(type_id, ""), "type_word": node.type, "word": node.word,
            "instance": node.id.rsplit("/", 1)[-1], "can_id": int(can.group(1)) if can else None,
            "twin_before": stages[0], "twin_after": stages[-1], "iterations": len(stages),
            "floor_kind": (driven or {}).get("kind", ""), "split": "held out", "compares": "sim vs real on held-out runs",
            "gains": ", ".join(sorted({str(r.get("gains")) for r in node.runs if r.get("gains")})),
            "questions_order": " > ".join(QUESTIONS), "twinned_at_x_floor": RULER_TWINNED, "tool_gate_mm": TOOL_GATE_MM,
            "curriculum_ladder": curriculum.ladder_of(node.kind)[0].id[0],
            **extra,
        }
        trend = []
        for k, stage in enumerate(stages):
            held = stats.get((node.id, stage, "held out")) or {}
            pooled = stats.get((node.id, stage, "all runs")) or {}
            trend.append({"iteration": k, "trend/heldout_median_deg": held.get("median_deg"), "trend/heldout_p95_deg": held.get("p95_deg"),
                          "trend/heldout_runs": held.get("runs"), "trend/all_median_deg": pooled.get("median_deg"),
                          "trend/floor_deg": node.floor_deg})
        for k, stage in enumerate(stages):
            role = "after" if k == last else ("before" if k == 0 else "between")
            config = {**base, "twin_iteration": stage, "iteration": k, "stage_role": role,
                      "model_rung": picked if k == last else stage}
            tags = sorted({type_id, root.id, node.kind, role, "latest"})
            record = {"id": run_id(result.id, evaluation, node.id, str(k)),
                      "name": node.label if k == last else f"{node.label} · {k + 1}/{len(stages)} {stage}",
                      "group": f"{result.id} · {evaluation}", "job_type": node.kind, "tags": tags,
                      "notes": f"{verdict['verdict']}: {verdict['why']}" if k == last else f"twin iteration {k + 1} of {len(stages)}: {stage}",
                      "config": config, "summary": {"twin_iteration": stage}, "tables": {}}
            if k != last:
                record["history"] = [trend[k]]
            else:
                numbers, text = summary_numbers(node, verdict, QUESTIONS)
                text["next_rung"] = curriculum.next_rung(rungs, node.id) or "climbed"
                text["rungs"] = curriculum.compact(rungs, node.id)
                record["summary"].update(text)
                record["history"] = trend[:-1] + [{**trend[-1], **numbers}]
                record["tables"] = {
                    "questions": [r for r in tables["questions"] if r["node"] == node.id],
                    "curriculum": [r for r in rungs if r["node"] == node.id],
                    "floors": [dict(r) for r in node.floors],
                    "models": [dict(r) for r in node.models],
                    "parameters": [dict(r) for r in node.parameters],
                }
                if node.parent is None:
                    record["tables"].update({"tree": tables["nodes"], "questions_all": tables["questions"], "curriculum_all": rungs,
                                             "trend_all": tables["error_stats"]})
            if add is not None:
                more_numbers, more_text, more_tables = add(node, k, role)
                record["history"] = record["history"][:-1] + [{**record["history"][-1], **more_numbers}]
                record["summary"].update(more_text)
                record["tables"].update(more_tables)
            out.append(record)
    return out


def code_version(repo: Path = REPO) -> tuple[str, bool]:
    """(HEAD sha, whether src/ has uncommitted changes) of the sim2real checkout this module runs from; ("unknown", False) outside git."""
    try:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", "src"], capture_output=True, text=True,
                                    check=True).stdout.strip())
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return os.environ.get("SIM2REAL_SHA", "unknown"), os.environ.get("SIM2REAL_DIRTY", "") == "1"


def _differs(stored, value) -> bool:
    """Whether a run's stored summary value is not `value` (numbers compared to 1e-9; W&B hands back ints and floats alike)."""
    if isinstance(value, (int, float)) and isinstance(stored, (int, float)) and not isinstance(value, bool):
        return abs(float(stored) - float(value)) > 1e-9
    return stored != value


def _clean(values: dict) -> dict:
    """Drop None and non-finite numbers (W&B charts skip them anyway; a NaN in history breaks the run's summary sort)."""
    return {k: v for k, v in values.items() if v is not None and not (isinstance(v, float) and not math.isfinite(v))}


def _table_rows(rows: list[dict]) -> tuple[list[str], list[list]]:
    """Rows -> (columns, data) with one type per column: a column mixing numbers and text becomes text (a W&B Table checks types)."""
    columns: list[str] = []
    for row in rows:
        columns += [key for key in row if key not in columns]
    data = [[row.get(c) for c in columns] for row in rows]
    for index, _column in enumerate(columns):
        kinds = {type(r[index]) for r in data if r[index] is not None}
        numeric = kinds <= {int, float, bool}
        if not numeric or (bool in kinds and kinds != {bool}):
            for r in data:
                if r[index] is not None:
                    r[index] = str(r[index])
        elif float in kinds:
            for r in data:
                if r[index] is not None and not (isinstance(r[index], float) and not math.isfinite(r[index])):
                    r[index] = float(r[index])
                elif isinstance(r[index], float):
                    r[index] = None
    return columns, data


# ---------------------------------------------------------------------------------------------------------------- W&B: writes


def log(result, *, entity: str = ENTITY, project: str = PROJECT, extra_config: dict | None = None, sha: str | None = None,
        dirty: bool | None = None, retire_older: bool = True, add=None) -> list[dict]:
    """Log one CalibrationResult (one evaluation) as W&B runs. Idempotent: the same numbers resume the same runs and add only the keys
    a run lacks (a logger that learned a new number patches it in; a second rebuild adds nothing); new numbers make a new evaluation
    and mark the result's older runs `evaluation_state: superseded` (never deleted)."""
    if sha is None:
        sha, dirty = code_version()
    batch = records(result, sha=sha, dirty=bool(dirty), extra_config=extra_config, add=add)
    logged = push(batch, entity=entity, project=project)
    if retire_older:
        retire(result.id, batch[0]["config"]["evaluation"], entity=entity, project=project)
    return logged


def push(batch: list[dict], *, entity: str = ENTITY, project: str = PROJECT) -> list[dict]:
    """Write records (records()'s shape) as W&B runs: a new id makes a run; an existing one gets only what it lacks or holds
    differently, as one more step (see log)."""
    import wandb

    WANDB_DIR.mkdir(parents=True, exist_ok=True)
    api = wandb.Api(timeout=60)
    logged = []
    for record in batch:
        try:
            have = dict(api.run(f"{entity}/{project}/{record['id']}").summary)
        except Exception:   # wandb raises CommError / ValueError for a run that does not exist yet
            have = None
        run = wandb.init(entity=entity, project=project, id=record["id"], name=record["name"], group=record["group"],
                         job_type=record["job_type"], tags=record["tags"], notes=record["notes"], config=record["config"],
                         resume="allow", reinit="create_new", allow_val_change=True, dir=str(WANDB_DIR),
                         settings=wandb.Settings(silent=True, console="off"))
        steps = [_clean(step) for step in record["history"]]
        tables = {name: rows for name, rows in record["tables"].items() if rows}
        if have is not None:
            # WHY only what is missing or changed: the run id is the evaluation's content id, so the run already holds this
            # evaluation; re-logging its trend would add steps W&B drops (a step must increase) and duplicate points. A logger that
            # learned a number (or fixed how it reads one) patches just that key in, as one more step
            last = {k: v for k, v in steps[-1].items()
                    if k != "iteration" and not k.startswith("trend/") and (k not in have or _differs(have[k], v))}
            tables = {name: rows for name, rows in tables.items() if name not in have}
            steps = [last] if (last or tables) else []
        for index, values in enumerate(steps):
            if index == len(steps) - 1:
                for name, rows in tables.items():
                    columns, data = _table_rows(rows)
                    values[name] = wandb.Table(columns=columns, data=data, allow_mixed_types=True)
            if values:
                run.log(values)
        run.summary.update(record["summary"])
        logged.append({"id": run.id, "url": run.url, "name": record["name"], "resumed": have is not None, "group": record["group"],
                       "patched": sorted(steps[-1]) if (have is not None and steps) else []})
        run.finish()
    return logged


def retire(result_id: str, evaluation: str, *, entity: str = ENTITY, project: str = PROJECT) -> int:
    """Mark every run of `result_id` from another evaluation as superseded (config + tag); returns how many changed. Never deletes."""
    import wandb

    changed = 0
    for run in wandb.Api(timeout=60).runs(f"{entity}/{project}", filters={"config.result_id": result_id}):
        if run.config.get("evaluation") != evaluation and run.config.get("evaluation_state") != "superseded":
            run.config["evaluation_state"] = "superseded"
            run.tags = sorted({*run.tags, "superseded"} - {"latest"})
            run.update()
            changed += 1
    return changed


# ---------------------------------------------------------------------------------------------------------------- W&B: views


def browser_url(url: str) -> str:
    """W&B's app moved under forge.coreweave.com/wandb/ (wandb.ai/... redirects there, checked 2026-11-11); wandb-workspaces 0.4.13 still
    returns forge.coreweave.com/<entity>/..., which 404s (bam_trackio.wandb_reports.browser_url), so hand out the wandb.ai form."""
    return re.sub(r"^https://forge\.coreweave\.com/(?:wandb/)?", "https://wandb.ai/", url)


def slices(results: list) -> list[dict]:
    """The views to build: one per sim2real type present and one per deployment, each with its runset filter (latest, last iteration)."""
    known = type_ids()
    found_types: dict[str, set] = {}
    deployments = []
    for result in results:
        root = next(n for n in result.nodes if n.parent is None)
        deployments.append((root.id, root.label))
        for node in result.nodes:
            found_types.setdefault(type_of(node, known), set()).add(node.kind)
    out = [{"key": f"type-{t}", "by": "type", "value": t, "title": f"Type · {t}", "levels": sorted(kinds)}
           for t, kinds in sorted(found_types.items())]
    out += [{"key": f"deployment-{d}", "by": "deployment", "value": d, "title": f"Deployment · {label}", "levels": []}
            for d, label in deployments]
    return out


def _status_markdown(results: list, keep) -> str:
    """The curriculum as a markdown table: one row per node the slice keeps, one column per rung (the six questions' rungs)."""
    marks = {"passed": "✓", "partial": "~ partial", "no": "✗ no", "unknown": "? unknown", "child": "↓ child"}
    lines = ["| Node | Verdict | 0 · Described | 1 · Routines | 2 · Floor | 3 · Data | 4 · Twin | 5 · Job | Next rung |",
             "|---|---|---|---|---|---|---|---|---|"]
    for result in results:
        verdicts = result.verdicts()
        rows = curriculum.status(result, verdicts)
        for node in result.nodes:
            if not keep(result, node):
                continue
            mine = [r for r in rows if r["node"] == node.id]
            cells = [f"{r['rung']} {marks.get(r['status'], r['status'])}" for r in mine]
            lines.append(f"| {node.label} | {verdicts[node.id]['verdict']} | " + " | ".join(cells)
                         + f" | {curriculum.next_rung(rows, node.id) or 'climbed'} |")
    return "\n".join(lines)


def _ladders_markdown(levels: list[str]) -> str:
    parts = []
    for level in levels:
        rungs = curriculum.ladder_of(level)
        parts.append(f"**{level} ladder ({rungs[0].id[0]})**\n\n| Rung | What | Reads | Gate |\n|---|---|---|---|\n"
                     + "\n".join(f"| {r.id} | {r.title} | {r.question or '—'} | {r.gate} |" for r in rungs))
    return "\n\n".join(parts)


INTRO = ("Every node of a deployment's tree (deployment → arm → joint → tool) answers five questions in order: **Floor** (do we know how "
         "much the real thing disagrees with itself: ≥ 5 same-input repeats per run kind) → **Data** (is the data enough: coverage) → "
         "**Routines** (does each calibration routine get a hidden truth back, in sim, at 1× noise) → **Twin** (held-out sim vs real ≤ "
         "1.5× the floor, passive and driven) → **Job** (real vs target; the tool ≤ 1 mm at a stop). The verdict is the first \"no\"; a "
         "parent passes a question only if it does at its own output and every child does. Source: sim2real `result.py` / "
         "`rack_results.py`; the curriculum and the three tracker proposals: sim2real `docs/KPIS_GATES_CURRICULUM.md`.")


def _panels(wr, slice_: dict) -> list:
    """The KPI panels every view and report shows over its runset (the slice's latest runs at their last twin iteration)."""
    L = wr.Layout
    panels = [
        # WHY plain metric names, not wr.SummaryMetric: W&B's bar panel looked up "summary_metrics.<key>" and found no runs
        # (bam_trackio, 2026-11-11); every KPI is logged in history once, so the plain name is the same value
        wr.BarPlot(title="Questions passed in order (5 = passes all five)", metrics=["questions_passed"], orientation="h",
                   layout=L(x=0, y=0, w=12, h=8)),
        wr.BarPlot(title="Twin ÷ floor, driven, on the floor's run kind (twinned ≤ 1.5×)", metrics=["Twin/ratio"], orientation="h",
                   layout=L(x=12, y=0, w=12, h=8)),
        wr.BarPlot(title="Floor (°): same-input repeats, driven", metrics=["Floor/floor_deg"], orientation="h", layout=L(x=0, y=8, w=8, h=8)),
        wr.BarPlot(title="Held-out sim→real after vs before (°)", metrics=["Twin/sim_real_before_deg", "Twin/sim_real_after_deg"],
                   orientation="h", layout=L(x=8, y=8, w=8, h=8)),
        wr.LinePlot(title="Held-out sim→real across twin iterations (°)", x="iteration", y=["trend/heldout_median_deg"],
                    layout=L(x=16, y=8, w=8, h=8)),
    ]
    if slice_["by"] == "deployment" or "joint" in slice_["levels"]:
        panels.append(wr.BarPlot(title="Data: reachable (angle, speed, acceleration) cells visited (%, gate ≥ 40 % proposed)",
                                 metrics=["Data/coverage_pct"], orientation="h", layout=L(x=0, y=16, w=12, h=8)))
        panels.append(wr.BarPlot(title="Job: settled stop error vs its share of the 1 mm tool gate (°)",
                                 metrics=["Job/settled_median_deg", "Job/share_deg"], orientation="h", layout=L(x=12, y=24, w=12, h=8)))
    if slice_["by"] == "deployment" or "arm" in slice_["levels"]:
        panels.append(wr.BarPlot(title="Data at the arm: cube / workspace / facing or heading (% of the allowed mask)",
                                 metrics=["Data/cube_pct", "Data/workspace_pct", "Data/facing_pct", "Data/heading_pct"], orientation="h",
                                 layout=L(x=12, y=16, w=12, h=8)))
    if slice_["by"] == "deployment" or "tool" in slice_["levels"]:
        panels.append(wr.BarPlot(title="Tool at settled holds (mm, gate 1 mm)", metrics=["Job/tool_settled_mm", "Job/tool_gate_mm"],
                                 orientation="h", layout=L(x=0, y=24, w=12, h=8)))
    panels += [wr.WeavePanelSummaryTable(table_name="questions", layout=L(x=0, y=32, w=24, h=12)),
               wr.WeavePanelSummaryTable(table_name="curriculum", layout=L(x=0, y=44, w=24, h=12))]
    return panels


def _filters(expr, slice_: dict, *, last_only: bool = True) -> list:
    keep = [expr.Config(slice_["by"]) == slice_["value"], expr.Config("evaluation_state") == "latest"]
    if last_only:
        keep.append(expr.Config("stage_role") == "after")
    return keep


def build_views(results: list, *, entity: str = ENTITY, project: str = PROJECT, registry: Path = REGISTRY) -> dict[str, dict[str, str]]:
    """One saved workspace view and one report per slice (type, deployment), plus an overview report; updated in place on a rebuild
    (their URLs live in `registry`), never duplicated. Returns {"views": {key: url}, "reports": {key: url}}."""
    import wandb_workspaces.reports.v2 as wr
    import wandb_workspaces.workspaces as ws
    from wandb_workspaces import expr

    known = json.loads(registry.read_text()) if registry.exists() else {}
    urls: dict[str, dict[str, str]] = {"views": dict(known.get("views", {})), "reports": dict(known.get("reports", {}))}
    pinned = ["summary:verdict", "summary:next_rung", "summary:questions_passed", "summary:Floor/floor_deg", "summary:Twin/ratio",
              "summary:Data/coverage_pct", "config:type", "config:deployment", "config:level"]
    every = slices(results)
    for slice_ in every:
        # the saved view (the workspace's view menu: "filter that data to show it for particular types")
        sections = [ws.Section(name="Five questions (latest evaluation, last twin iteration)", panels=_panels(wr, slice_), is_open=True)]
        settings = ws.RunsetSettings(filters=_filters(expr, slice_), pinned_columns=pinned)
        view = None
        if slice_["key"] in urls["views"]:
            try:
                view = ws.Workspace.from_url(urls["views"][slice_["key"]])
                view.name, view.sections, view.runset_settings = slice_["title"], sections, settings
            except Exception:   # a view deleted in the app: make it again
                view = None
        if view is None:
            view = ws.Workspace(entity=entity, project=project, name=slice_["title"], sections=sections, runset_settings=settings)
        view.save()
        urls["views"][slice_["key"]] = browser_url(view.url)

        # the report: the same panels, plus the curriculum rungs and today's status as tables
        if slice_["by"] == "type":
            keep = lambda result, node, t=slice_["value"]: type_of(node, type_ids()) == t  # noqa: E731
            levels = slice_["levels"]
        else:
            keep = lambda result, node, d=slice_["value"]: next(n for n in result.nodes if n.parent is None).id == d  # noqa: E731
            levels = ["deployment", "arm", "joint", "tool"]
        blocks = [
            wr.MarkdownBlock(text=INTRO),
            wr.H2(text="Today's status: every node's rungs"),
            wr.MarkdownBlock(text=_status_markdown(results, keep)
                             + "\n\n✓ passed · ~ partial · ✗ no · ? unknown · ↓ its own answer is yes, a child holds it back. "
                               "Rungs are climbed in work order (Routines first: sim before rig time); the verdict reads the same "
                               "answers in check order (Floor → Data → Routines → Twin → Job)."),
            wr.H2(text="The KPI panels"),
            wr.PanelGrid(runsets=[wr.Runset(entity=entity, project=project, name=slice_["title"], filters=_filters(expr, slice_),
                                            pinned_columns=pinned)],
                         panels=_panels(wr, slice_)),
        ]
        if slice_["by"] == "deployment":
            blocks += [wr.H2(text="The tree"),
                       wr.PanelGrid(hide_run_sets=True,
                                    runsets=[wr.Runset(entity=entity, project=project, name="the deployment",
                                                       filters=[*_filters(expr, slice_), expr.Config("level") == "deployment"])],
                                    panels=[wr.WeavePanelSummaryTable(table_name="tree", layout=wr.Layout(x=0, y=0, w=24, h=14))])]
        blocks += [wr.H2(text="Every twin iteration"),
                   wr.MarkdownBlock(text="One run per node per twin iteration (oldest = before, last = after): held-out sim→real median "
                                         "of each iteration's twin, from the result's own error table."),
                   wr.PanelGrid(runsets=[wr.Runset(entity=entity, project=project, name="every iteration",
                                                   filters=_filters(expr, slice_, last_only=False))],
                                panels=[wr.ScatterPlot(title="Held-out sim→real (°) per twin iteration", x=wr.Config("iteration"),
                                                       y=wr.SummaryMetric("trend/heldout_median_deg"), layout=wr.Layout(x=0, y=0, w=24, h=10))]),
                   wr.H2(text="The ladders"),
                   wr.MarkdownBlock(text=_ladders_markdown(levels))]
        title = f"Sim2Real · {slice_['title']}"
        description = "Five questions per node, the curriculum rungs and the KPI panels, filtered to " + slice_["title"].lower()
        urls["reports"][slice_["key"]] = _save_report(wr, entity, project, urls["reports"].get(slice_["key"]), title, description, blocks)

    links = "\n".join(f"- **{s['title']}**: [report]({urls['reports'][s['key']]}) · [saved view]({urls['views'][s['key']]})" for s in every)
    overview = [wr.MarkdownBlock(text=INTRO), wr.H2(text="Views and reports"), wr.MarkdownBlock(text=links),
                wr.H2(text="Every node, latest evaluation"),
                wr.MarkdownBlock(text=_status_markdown(results, lambda result, node: True)),
                wr.PanelGrid(runsets=[wr.Runset(entity=entity, project=project, name="every node",
                                                filters=[expr.Config("evaluation_state") == "latest", expr.Config("stage_role") == "after"],
                                                pinned_columns=pinned)],
                             panels=_panels(wr, {"by": "deployment", "levels": []})[:5])]
    urls["reports"]["overview"] = _save_report(wr, entity, project, urls["reports"].get("overview"), "Sim2Real · Overview",
                                               "Every type and deployment in one project: the five questions, the curriculum, the views",
                                               overview)
    registry.write_text(json.dumps(urls, indent=1, sort_keys=True) + "\n")
    return urls


def _save_report(wr, entity: str, project: str, url: str | None, title: str, description: str, blocks: list) -> str:
    """Save a report, in place when `url` names one (rebuilt from its id: a title's slug can hold characters from_url misreads)."""
    report = None
    if url:
        try:
            report = wr.Report.from_url(f"https://wandb.ai/{entity}/{project}/reports/report--{url.rsplit('--', 1)[-1]}")
            report.title, report.description, report.blocks = title, description, blocks
        except Exception:   # deleted in the app: make it again
            report = None
    if report is None:
        report = wr.Report(entity=entity, project=project, title=title, description=description, blocks=blocks)
    report.width = "fluid"
    report.save()
    return browser_url(report.url)


# ---------------------------------------------------------------------------------------------------------------- W&B: checks


def verify(results: list, *, entity: str = ENTITY, project: str = PROJECT, registry: Path = REGISTRY) -> list[str]:
    """Read the project back through W&B's API: every node of every result has a latest last-iteration run, a type filter returns
    exactly that type's nodes, a deployment filter that deployment's, every iteration has its run, and the reports exist. Returns
    the failures (empty = all good) and prints what it checked."""
    import wandb

    api = wandb.Api(timeout=60)
    path = f"{entity}/{project}"
    failures: list[str] = []
    known = type_ids()
    latest = {"config.evaluation_state": "latest"}
    for result in results:
        root = next(n for n in result.nodes if n.parent is None)
        runs = list(api.runs(path, filters={**latest, "config.result_id": result.id}))
        want = len(result.nodes) * len(result.stages)
        print(f"{result.id}: {len(runs)} latest runs (want {want} = {len(result.nodes)} nodes x {len(result.stages)} twin iterations)")
        if len(runs) != want:
            failures.append(f"{result.id}: {len(runs)} latest runs, want {want}")
        after = {r.config.get("node"): r for r in runs if r.config.get("stage_role") == "after"}
        verdicts = result.verdicts()
        for node in result.nodes:
            run = after.get(node.id)
            if run is None:
                failures.append(f"{node.id}: no after run")
                continue
            if run.summary.get("verdict") != verdicts[node.id]["verdict"]:
                failures.append(f"{node.id}: W&B says {run.summary.get('verdict')!r}, the tree {verdicts[node.id]['verdict']!r}")
        by_deployment = list(api.runs(path, filters={**latest, "config.stage_role": "after", "config.deployment": root.id}))
        print(f"  filter deployment={root.id}: {len(by_deployment)} runs -> {sorted(r.name for r in by_deployment)}")
        if len(by_deployment) != len(result.nodes):
            failures.append(f"deployment={root.id}: {len(by_deployment)} runs, want {len(result.nodes)}")
    for type_id in sorted({type_of(n, known) for result in results for n in result.nodes}):
        want = sorted(n.label for result in results for n in result.nodes if type_of(n, known) == type_id)
        got = list(api.runs(path, filters={**latest, "config.stage_role": "after", "config.type": type_id}))
        print(f"  filter type={type_id}: {len(got)} runs -> {sorted(r.name for r in got)}")
        if sorted(r.name for r in got) != want:
            failures.append(f"type={type_id}: got {sorted(r.name for r in got)}, want {want}")
    urls = json.loads(registry.read_text()) if registry.exists() else {}
    in_project = {str(report.id): report.display_name for report in api.reports(path)}
    print(f"  reports in the project: {sorted(in_project.values())}")
    for key, url in sorted(urls.get("reports", {}).items()):
        if url.rsplit("--", 1)[-1] not in in_project:
            failures.append(f"report {key}: {url} is not in {path}")
    print(f"  registry: {len(urls.get('reports', {}))} reports, {len(urls.get('views', {}))} saved views")
    return failures


# ---------------------------------------------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--backfill", action="store_true", help="log the rack's two calibrations (rack_results ur_wrist, fivebar)")
    parser.add_argument("--views", action="store_true", help="build or update the saved views and reports")
    parser.add_argument("--verify", action="store_true", help="read the project back through the W&B API and check it")
    parser.add_argument("--registry", type=Path, default=REGISTRY, help="where the view / report URLs are kept (default: beside this file)")
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--allow-dirty", action="store_true", help="log even when src/ has uncommitted changes")
    args = parser.parse_args(argv)

    # WHY refuse a dirty tree (2026-11-11): every evaluation in W&B should be reproducible from a commit; that night a peer's
    # in-flight edit to rack_results.py would otherwise have been logged as an evaluation of its own
    sha, dirty = code_version()
    if args.backfill and dirty and not args.allow_dirty:
        parser.error(f"src/ has uncommitted changes (HEAD {sha[:9]}): commit them, or pass --allow-dirty")

    from ..rack_results import load

    results = [load("ur_wrist"), load("fivebar")]
    rig = {"deployment_kind": "physical", "rig": "One Dof Test Rack"}
    if args.backfill:
        for result in results:
            logged = log(result, project=args.project, extra_config=rig)
            fresh = sum(1 for item in logged if not item["resumed"])
            patched = sorted({key for item in logged for key in item["patched"]})
            print(f"{result.id}: {len(logged)} runs ({fresh} new, {len(logged) - fresh} already there"
                  + (f"; patched in {', '.join(patched)}" if patched else "") + f"), group {logged[0]['group']}")
    if args.views:
        urls = build_views(results, project=args.project, registry=args.registry)
        for kind, items in urls.items():
            for key, url in sorted(items.items()):
                print(f"{kind[:-1]:6s} {key:32s} {url}")
    if args.verify:
        failures = verify(results, project=args.project, registry=args.registry)
        print("VERIFY: " + ("PASS" if not failures else "FAIL\n  " + "\n  ".join(failures)))
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
