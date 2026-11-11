"""A calibration's result as one page: CalibrationResult and .display() (Zach, 2026-11-11).

Zach: "I have the deployment, I have a robot description for it, I just click .calibrate() and what I get is a result. result.display()
brings up this page that lets me see everything. At a glance I need to see the state of affairs." / "At a glance I can look at any level,
and navigate that with the tree." / "System ID is just: data (check its distribution and coverage), models, then adjusting the parameters
of models to lower the error."

A result is the description's typed tree (deployment -> arm -> each joint -> tool), each node with four sections:

    coverage     where the runs went (position / speed / acceleration per joint; the workspace for an arm)
    error        held-out error before vs after calibration, its distribution, and the trend across twin iterations
    parameters   each parameter before vs after (what changed)
    models       the model ladder, each rung's held-out error

and a verdict on top, by Zach's ruler (vault "Reality as Oracle", 2026-10-02 / 10-27): sim->real on held-out runs divided by the real
device's own run-to-run floor; TWINNED at <= 1.5x. A parent's verdict is its worst child's, so the deployment's line is the answer.

display() writes one folder (index.html + views.base + the tables + the data-ui kit, vendored the house way from vendor/data-ui) and,
unless open=False, serves it on 127.0.0.1 from a daemon thread and opens the browser (data-ui is ES modules, which no browser loads from
file://). Every number is in degrees or mm; the stored values stay SI where they are SI.

Layer: like twin.py, this module sits right of every folder (tests/test_layers.py).
"""

from __future__ import annotations

import json
import math
import shutil
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "vendor" / "data-ui" / "dist"
RULER_TWINNED = 1.5          # sim->real / floor at most this: twinned (sim2real README, the ruler)
RULER_CLOSE = 3.0            # past twinned, up to this: close
# WHY 1 mm (Zach, 2026-11-11): "we certainly need final tool error sub 1mm final accuracy" - replaces the 5 mm of Oct 24.
TOOL_GATE_MM = 1.0           # the deployment's tool gate at a stop (Zach's standing metric)


VERDICT_RANK = {"twinned": 0, "gate pass": 0, "close": 1, "not twinned": 2, "gate fail": 2}


def verdict_of(ratio: float | None) -> str:
    if ratio is None or not math.isfinite(ratio):
        return "no data"
    return "twinned" if ratio <= RULER_TWINNED else ("close" if ratio <= RULER_CLOSE else "not twinned")


@dataclass
class Node:
    """One node of the description's typed tree and its four sections. Section rows carry no `node` column; the result adds it."""
    id: str                                   # a path id, "deployment/arm/can15"
    label: str
    kind: str                                 # deployment | arm | joint | tool
    type: str = ""                            # the sim2real type ("integrated_servo") or a structural word
    word: str = ""                            # the description's own word
    parent: str | None = None
    floor_deg: float | None = None            # the real device's own run-to-run floor (joints)
    note: str = ""
    coverage: list[dict] = field(default_factory=list)      # {channel, lo, hi, seconds} | {channel: workspace, x_lo, x_hi, y_lo, y_hi, seconds}
    coverage_summary: list[dict] = field(default_factory=list)   # {measure, value, unit, of}
    errors: list[dict] = field(default_factory=list)        # per run x stage: {run, stage, order, held_out, sim_real_deg, target_real_deg}
    parameters: list[dict] = field(default_factory=list)    # {parameter, unit, before, after, source}
    models: list[dict] = field(default_factory=list)        # {model, held_out_deg, picked, note}
    runs: list[dict] = field(default_factory=list)          # {run, label, held_out, gains, tape, target_real_deg, sim_real_deg, sim_real_before_deg, run_view}
    gate: dict | None = None                  # the tool gate's numbers, on the node that carries it
    result: Any = field(default=None, repr=False, compare=False)   # set by CalibrationResult: node.show() asks it

    def show(self, *, held_out_only: bool = True, limit: int = 12):
        """This node's runs in Rerun (robot_msgs.viz.rerun): result.show(node=self.id)."""
        return self.result.show(node=self.id, held_out_only=held_out_only, limit=limit)


@dataclass
class CalibrationResult:
    """What a calibration returns: the deployment's typed tree with its sections, its twin iterations (first = before, last = after)."""
    id: str
    title: str
    stages: list[str]                         # the twin iterations, oldest first: stages[0] is "before", stages[-1] "after"
    nodes: list[Node]
    source: str
    notes: list[str] = field(default_factory=list)
    # run id -> its robot_msgs trajectories {"target": JointTrajectory, "sim": ..., "real": ...} (the producer's files, read on demand)
    messages: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for n in self.nodes:
            n.result = self

    # ---------------------------------------------------------------------------------------------------------- Rerun

    def recording(self, runs: list[str], *, into: str | None = None):
        """One Rerun recording (robot_msgs.viz.rerun.compose) of these runs: each one's target / sim / real under those names and each
        series' Comparison against the target (its error on the error/ tab); with several runs a name is suffixed by the run."""
        from robot_msgs.compare import compare
        from robot_msgs.viz import rerun as viz

        if self.messages is None:
            raise RuntimeError(f"{self.id} has no run messages to show")
        entries = []
        for run in runs:
            series = self.messages(run)
            suffix = "" if len(runs) == 1 else f" · {run}"
            for name in ("target", "sim", "real"):
                if name in series:
                    entries.append((f"{name}{suffix}", series[name]))
            for name in ("sim", "real"):
                if name in series and "target" in series:
                    entries.append((f"{name}{suffix}", compare(series["target"], series[name])))
        return viz.compose(*entries, application_id=f"sim2real {self.id}", into=into)

    def show(self, run: str | None = None, *, node: str | None = None, held_out_only: bool = True, limit: int = 12):
        """Open Rerun: one run (`run=`), a node's runs (`node=`, its held-out ones by default, at most `limit`), or the worst held-out
        runs of the whole result. The same robot_msgs.viz.rerun path everywhere; no viewer of our own."""
        from robot_msgs.viz import rerun as viz

        if run is not None:
            runs = [run]
        else:
            rows = [r for m in self.subtree(node or self.nodes[0].id) for r in m.runs if r.get("held_out") or not held_out_only]
            rows.sort(key=lambda r: -(r.get("sim_real_deg") or 0))
            runs = list(dict.fromkeys(r["run"] for r in rows))[:limit]
        return viz.view(self.recording(runs))

    # ---------------------------------------------------------------------------------------------------------- the roll-up

    def children(self, node_id: str) -> list[Node]:
        return [n for n in self.nodes if n.parent == node_id]

    def subtree(self, node_id: str) -> list[Node]:
        out, frontier = [], [node_id]
        while frontier:
            current = frontier.pop()
            out += [n for n in self.nodes if n.id == current]
            frontier += [n.id for n in self.children(current)]
        return out

    def node(self, node_id: str) -> Node:
        return next(n for n in self.nodes if n.id == node_id)

    def verdicts(self) -> dict[str, dict]:
        """Per node: the held-out sim->real median after calibration, before, the floor and the ratio. A leaf with errors judges itself;
        a parent is its worst child (its ratio the children's max), so the root is the deployment's answer."""
        out: dict[str, dict] = {}

        def leaf(n: Node) -> dict:
            after = [e["sim_real_deg"] for e in n.errors if e["stage"] == self.stages[-1] and e["held_out"] and e["sim_real_deg"] is not None]
            before = [e["sim_real_deg"] for e in n.errors if e["stage"] == self.stages[0] and e["held_out"] and e["sim_real_deg"] is not None]
            target = [e["target_real_deg"] for e in n.errors if e["stage"] == self.stages[-1] and e["target_real_deg"] is not None]
            med = _median(after)
            ratio = med / n.floor_deg if med is not None and n.floor_deg else None
            return {"sim_real_deg": med, "sim_real_before_deg": _median(before), "target_real_deg": _median(target),
                    "floor_deg": n.floor_deg, "ratio": ratio, "verdict": verdict_of(ratio), "held_out_runs": len(after)}

        def visit(n: Node) -> dict:
            kids = [visit(c) for c in self.children(n.id)]
            if n.errors:
                v = leaf(n)
            elif kids:
                judged = [k for k in kids if k["ratio"] is not None]
                worst = max(judged, key=lambda k: k["ratio"]) if judged else None
                # WHY by rank, not by ratio alone (Zach: "everything rolls up to the tool gate"): a failed tool gate makes its parent fail
                # even when every joint is twinned
                ranked = [k["verdict"] for k in kids if k["verdict"] in VERDICT_RANK]
                v = {"sim_real_deg": _median([k["sim_real_deg"] for k in kids]), "sim_real_before_deg": _median([k["sim_real_before_deg"] for k in kids]),
                     "target_real_deg": _median([k["target_real_deg"] for k in kids]), "floor_deg": None,
                     "ratio": worst["ratio"] if worst else None,
                     "verdict": max(ranked, key=VERDICT_RANK.get) if ranked else "no data",
                     "held_out_runs": sum(k["held_out_runs"] for k in kids)}
            else:
                # a leaf without joint errors (the tool) is judged by its gate when it carries one
                gate_verdict = ("gate pass" if n.gate["verdict"].startswith("pass") else "gate fail") if n.gate else "no data"
                v = {"sim_real_deg": None, "sim_real_before_deg": None, "target_real_deg": None, "floor_deg": None, "ratio": None,
                     "verdict": gate_verdict, "held_out_runs": 0}
            if n.gate:
                v["gate"] = n.gate
            out[n.id] = v
            return v

        for root in [n for n in self.nodes if n.parent is None]:
            visit(root)
        return out

    def summary(self) -> str:
        verdicts = self.verdicts()
        lines = [f"{self.title}: before = {self.stages[0]}, after = {self.stages[-1]}"]
        for n in self.nodes:
            depth = len(n.id.split("/")) - 1
            v = verdicts[n.id]
            lines.append(f"  {'  ' * depth}{n.label:34s} {v['verdict']:12s} sim->real {_f(v['sim_real_deg'])} (before {_f(v['sim_real_before_deg'])})"
                         + (f", {v['ratio']:.2f}x floor" if v["ratio"] is not None else ""))
        return "\n".join(lines)

    # ---------------------------------------------------------------------------------------------------------- the tables

    def tables(self) -> dict[str, list[dict]]:
        """The page's tables, one row per node x item. A parent's error / run / coverage rows are its subtree's (pooled), so picking any
        level of the tree shows that level's runs; parameters and models stay on the node that owns them, plus the subtree's below."""
        verdicts = self.verdicts()
        nodes, coverage, workspace, cover_sum, errors, error_stats, params, models, runs = [], [], [], [], [], [], [], [], []
        for n in self.nodes:
            v = verdicts[n.id]
            gate = v.get("gate") or {}
            nodes.append({"node": n.id, "parent": n.parent, "label": n.label, "kind": n.kind, "type": n.type, "word": n.word,
                          "verdict": v["verdict"], "ratio": _r(v["ratio"], 2), "sim_real_deg": _r(v["sim_real_deg"], 3),
                          "sim_real_before_deg": _r(v["sim_real_before_deg"], 3), "target_real_deg": _r(v["target_real_deg"], 3),
                          "floor_deg": _r(v["floor_deg"], 3), "held_out_runs": v["held_out_runs"], "twinned_at": RULER_TWINNED,
                          "parameters": ", ".join(p["parameter"] for p in n.parameters), "note": n.note,
                          "tool_gate_mm": gate.get("gate_mm"), "tool_sim_real_mm": _r(gate.get("sim_real_mm"), 2),
                          "tool_target_real_mm": _r(gate.get("target_real_mm"), 2),
                          "tool_gate": gate.get("verdict", "")})
            subtree = self.subtree(n.id)
            for member in subtree:
                # WHY two tables (2026-11-11 render): one table mixing histogram rows (lo/hi) and workspace cells (x_lo/...) drew
                # nothing for the wrist, whose 1300 plane cells come first; each table now has one row shape
                for row in member.coverage:
                    (workspace if row["channel"] == "workspace" else coverage).append({"node": n.id, "joint": member.label, **row})
                for row in member.coverage_summary:
                    cover_sum.append({"node": n.id, "of": member.label, **row})
                for row in member.errors:
                    errors.append({"node": n.id, "joint": member.label, **row})
                for row in member.runs:
                    runs.append({"node": n.id, "joint": member.label, **{("run_name" if k == "label" else k): v for k, v in row.items()},
                                 "rerun": f"show/{row['run']}"})
                for row in member.parameters:
                    shown = {k: (_sig(v) if k in ("before", "after") else v) for k, v in row.items()}
                    params.append({"node": n.id, "of": member.label, **shown,
                                   "change_pct": _r(100 * (row["after"] - row["before"]) / abs(row["before"]), 1)
                                   if isinstance(row.get("before"), (int, float)) and isinstance(row.get("after"), (int, float)) and row["before"] else None})
                for row in member.models:
                    models.append({"node": n.id, "of": member.label, **row})
            # the trend: per stage, the median and p95 over the subtree's held-out runs and over all runs
            pool = [e for m in subtree for e in m.errors]
            for order, stage in enumerate(self.stages):
                for scope, keep in (("held out", True), ("all runs", None)):
                    values = [e["sim_real_deg"] for e in pool if e["stage"] == stage and e["sim_real_deg"] is not None and (keep is None or e["held_out"])]
                    if values:
                        error_stats.append({"node": n.id, "stage": stage, "order": order, "label": f"{order + 1} · {stage}", "scope": scope,
                                            "median_deg": _r(_median(values), 3), "p95_deg": _r(_pct(values, 95), 3),
                                            "mean_deg": _r(sum(values) / len(values), 3), "runs": len(values)})
        return {"nodes": nodes, "coverage": coverage, "workspace": workspace, "coverage_summary": cover_sum, "errors": errors, "error_stats": error_stats,
                "parameters": params, "models": models, "runs": runs}

    # ---------------------------------------------------------------------------------------------------------- the page

    def write(self, out: Path, *, runs_folder: Path | None = None) -> Path:
        """Write the page folder: index.html, views.base, data/*.json and the kit. `runs_folder` (traj_compare run views, one folder per
        run slug) is linked in as runs/ so each run row's run_view opens the classic drill-down."""
        out = Path(out)
        (out / "data").mkdir(parents=True, exist_ok=True)
        for name, rows in self.tables().items():
            (out / "data" / f"{name}.json").write_text(json.dumps({"name": name, "rows": rows}, default=_json))
        _copy_kit(out / "vendor" / "data-ui")
        if runs_folder is not None and Path(runs_folder).is_dir():
            link = out / "runs"
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(Path(runs_folder).resolve(), target_is_directory=True)
        (out / "views.base").write_text(_views_base(self))
        (out / "index.html").write_text(_page(self))
        return out / "index.html"

    def display(self, out: Path | str | None = None, *, open: bool = True, port: int = 0, runs_folder: Path | None = None) -> str:
        """Write the page and (open=True) serve it from a daemon thread on 127.0.0.1 and open the browser. Returns the URL (or the file
        path when open=False). WHY a server: data-ui is ES modules; a browser loads none from file://."""
        out = Path(out) if out else REPO / "reports" / f"calibration-{self.id}"
        index = self.write(out, runs_folder=runs_folder)
        if not open:
            return str(index)
        url = serve(out, port=port, on_show=lambda run: self.show(run)) + "index.html"
        webbrowser.open(url)
        return url


def serve(folder: Path, *, port: int = 0, on_show=None) -> str:
    """Serve `folder` on 127.0.0.1 from a daemon thread (it ends with this Python process). Returns the base URL. With `on_show`, a
    GET of show/<run> calls on_show(run) here (the page's "Open in Rerun": result.show(run), robot_msgs.viz.rerun) and says so."""
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server's name)
            if on_show is not None and self.path.startswith("/show/"):
                run = unquote(self.path[len("/show/"):].split("?")[0])
                try:
                    on_show(run)
                    body, status = f"Opened {run} in Rerun (robot_msgs.viz.rerun). You can close this tab.", 200
                except Exception as error:  # the page shows why; the server keeps serving
                    body, status = f"Could not show {run}: {error}", 500
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()

    handler = functools.partial(Handler, directory=str(folder))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/"


# --------------------------------------------------------------------------------------------------------------- helpers


def _median(values) -> float | None:
    kept = sorted(float(v) for v in values if v is not None and math.isfinite(v))
    if not kept:
        return None
    mid = len(kept) // 2
    return kept[mid] if len(kept) % 2 else (kept[mid - 1] + kept[mid]) / 2


def _pct(values, q: float) -> float | None:
    kept = sorted(float(v) for v in values if v is not None and math.isfinite(v))
    if not kept:
        return None
    k = (len(kept) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return kept[lo] + (kept[hi] - kept[lo]) * (k - lo)


def _r(value, digits: int):
    return None if value is None or not isinstance(value, (int, float)) or not math.isfinite(value) else round(float(value), digits)


def _sig(value, digits: int = 4):
    """Display rounding to significant figures (a parameter's before / after); None and text pass through."""
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value == 0:
        return value
    return float(f"{value:.{digits}g}")


def _f(value) -> str:
    return "—" if value is None else f"{value:.3f}°"


def _json(value):
    return None if isinstance(value, float) and not math.isfinite(value) else str(value)


def _copy_kit(dest: Path) -> None:
    """The kit as sim2real vendors it (vendor/data-ui/dist, pinned by VENDOR.json), copied whole beside the page; never edited."""
    if not (KIT / "data-ui.js").exists():
        raise FileNotFoundError(f"no data-ui kit at {KIT}: rebuild it from vendor/data-ui/VENDOR.json (docs/migrations/vendor-sim2real.md)")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(KIT, dest)
    pin = KIT.parent / "VENDOR.json"
    if pin.exists():
        shutil.copy2(pin, dest / "VENDOR.json")


def _views_base(result: CalibrationResult) -> str:
    before, after = result.stages[0], result.stages[-1]
    return f"""# {result.title}: the calibration's page (sim2real.result.CalibrationResult.display). Pick a level in the tree; every section follows it.
# Sources: {result.source}
style:
  chrome: minimal
  numbers: {{ digits: 3, compact: true }}
  palette: {{ before: "#9aa0a6", after: "#2f8a4f", "held out": "#2f8a4f", "all runs": "#9aa0a6", twin: "#e08a2b", real: "#2a78d6" }}
datasets:
  nodes:
    data: data/nodes.json
    label: Tree
  node: data/nodes.json
  coverage: data/coverage.json
  workspace: data/workspace.json
  coverage_summary: data/coverage_summary.json
  errors: data/errors.json
  error_stats: data/error_stats.json
  parameters: data/parameters.json
  models: data/models.json
  runs:
    data: data/runs.json
    label: Runs
    facets:
      - {{ property: held_out, label: Held out }}
      - {{ property: tape, label: Tape }}
links:
  - {{ from: nodes.node, to: node.node, direction: one-way }}
  - {{ from: nodes.node, to: coverage.node, direction: one-way }}
  - {{ from: nodes.node, to: workspace.node, direction: one-way }}
  - {{ from: nodes.node, to: coverage_summary.node, direction: one-way }}
  - {{ from: nodes.node, to: errors.node, direction: one-way }}
  - {{ from: nodes.node, to: error_stats.node, direction: one-way }}
  - {{ from: nodes.node, to: parameters.node, direction: one-way }}
  - {{ from: nodes.node, to: models.node, direction: one-way }}
  - {{ from: nodes.node, to: runs.node, direction: one-way }}
layout:
  panels:
    - text: |
        **The ruler.** A joint is **twinned** when its twin's held-out error (sim→real RMS, median over held-out runs) is at most
        **{RULER_TWINNED}×** the real joint's own run-to-run floor (repeats of one stimulus); close up to {RULER_CLOSE}×. A level's verdict is
        its worst child's. The deployment also answers the **tool gate**: {TOOL_GATE_MM:g} mm at a stop. **Before** = {before}, **after** = {after}.
        Pick any level in the tree; coverage, error, parameters, models and runs follow it.
      w: 12
    - {{ view: Tree, w: 12, h: 4 }}
    - {{ view: Verdict, w: 3, h: 2 }}
    - {{ view: Twin ÷ floor, w: 3, h: 2 }}
    - {{ view: sim→real before → after, w: 3, h: 2 }}
    - {{ view: target→real, w: 3, h: 2 }}
    - text: "**1 · Coverage** · where the runs went: time spent per position, speed and acceleration bin, and the workspace."
      w: 12
    - {{ view: Coverage summary, w: 4, h: 3 }}
    - {{ view: Position, w: 4, h: 3 }}
    - {{ view: Speed, w: 4, h: 3 }}
    - {{ view: Acceleration, w: 4, h: 3 }}
    - {{ view: Workspace, w: 8, h: 4 }}
    - text: "**2 · Error** · held-out sim→real, before vs after, and across the twin iterations."
      w: 12
    - {{ view: Error trend, w: 6, h: 3 }}
    - {{ view: Error before vs after, w: 6, h: 3 }}
    - text: "**3 · Parameters** · before vs after: what the calibration changed."
      w: 12
    - {{ view: Parameters, w: 12, h: 4 }}
    - text: "**4 · Models** · the model ladder: each rung's held-out sim→real; the picked one is the twin."
      w: 12
    - {{ view: Models, w: 12, h: 3 }}
    - text: "**Runs** · every run under this level; **Run view** opens the classic traj_compare page; **Open in Rerun** calls `result.show(run)` (robot_msgs.viz.rerun) in the Python that ran `display()`."
      w: 12
    - {{ view: Runs, w: 12, h: 4 }}
properties:
  label: {{ displayName: Level }}
  verdict: {{ displayName: Verdict }}
  ratio: {{ displayName: Twin ÷ floor }}
  sim_real_deg: {{ displayName: sim→real after }}
  sim_real_before_deg: {{ displayName: sim→real before }}
  target_real_deg: {{ displayName: target→real }}
  floor_deg: {{ displayName: Floor }}
  held_out_runs: {{ displayName: Held-out runs }}
  kind: {{ displayName: Kind }}
  type: {{ displayName: Type }}
  parameters: {{ displayName: Its parameters }}
  tool_gate: {{ displayName: Tool gate }}
  before: {{ displayName: Before }}
  after: {{ displayName: After }}
  change_pct: {{ displayName: Change }}
  run_name: {{ displayName: Run }}
  run_view: {{ displayName: Run view }}
  rerun: {{ displayName: Open in Rerun }}
views:
  - type: table
    name: Tree
    from: nodes
    select: node
    selected: first
    tree: {{ parent: parent }}
    fold: open
    order: [label, verdict, ratio, sim_real_deg, sim_real_before_deg, target_real_deg, floor_deg, held_out_runs, kind, type, tool_gate, parameters]
    display: {{ verdict: badge }}
  - type: kpi
    name: Verdict
    from: node
    kpi: {{ label: Verdict (worst level below), value: {{ property: verdict }} }}
  - type: gauge
    name: Twin ÷ floor
    from: node
    gauge:
      value: {{ property: ratio }}
      min: 0
      max: 6
      target: {RULER_TWINNED}
      shape: arc
      better: lower
      label: twin error ÷ real floor · twinned ≤ {RULER_TWINNED}×
      bands: [{{ to: {RULER_TWINNED}, tone: good }}, {{ to: {RULER_CLOSE}, tone: warn }}, {{ tone: bad }}]
  - type: kpi
    name: sim→real before → after
    from: node
    kpi: {{ label: held-out sim→real after (°), value: {{ property: sim_real_deg }}, compare: {{ against: sim_real_before_deg, better: lower }} }}
  - type: kpi
    name: target→real
    from: node
    kpi: {{ label: target→real (°), value: {{ property: target_real_deg }} }}
  - type: table
    name: Coverage summary
    from: coverage_summary
    order: [of, measure, value, unit]
  - type: chart
    name: Position
    from: coverage
    filters: 'channel == "position"'
    chart:
      mark: {{ type: area, interpolate: step-after, opacity: 0.45, line: true }}
      encoding:
        x: {{ field: lo, type: quantitative, title: 'angle (°)', scale: {{ type: linear }} }}
        'y': {{ field: seconds, type: quantitative, title: 'time (s)', scale: {{ type: linear }}, stack: null }}
        color: {{ field: joint, title: Joint }}
  - type: chart
    name: Speed
    from: coverage
    filters: 'channel == "speed"'
    chart:
      mark: {{ type: area, interpolate: step-after, opacity: 0.45, line: true }}
      encoding:
        x: {{ field: lo, type: quantitative, title: 'speed (°/s)', scale: {{ type: linear }} }}
        'y': {{ field: seconds, type: quantitative, title: 'time (s)', scale: {{ type: linear }}, stack: null }}
        color: {{ field: joint, title: Joint }}
  - type: chart
    name: Acceleration
    from: coverage
    filters: 'channel == "acceleration"'
    chart:
      mark: {{ type: area, interpolate: step-after, opacity: 0.45, line: true }}
      encoding:
        x: {{ field: lo, type: quantitative, title: 'acceleration (°/s²)', scale: {{ type: linear }} }}
        'y': {{ field: seconds, type: quantitative, title: 'time (s)', scale: {{ type: linear }}, stack: null }}
        color: {{ field: joint, title: Joint }}
  - type: chart
    name: Workspace
    from: workspace
    chart:
      mark: {{ type: rect }}
      encoding:
        x: {{ field: x_lo, type: quantitative, title: 'x (see the summary: mm or °)', scale: {{ type: linear }} }}
        x2: {{ field: x_hi, title: null }}
        'y': {{ field: y_lo, type: quantitative, title: 'y', scale: {{ type: linear }} }}
        y2: {{ field: y_hi, title: null }}
        color: {{ field: seconds, type: quantitative, title: 'time (s)', scale: {{ scheme: greens }} }}
  - type: chart
    name: Error trend
    from: error_stats
    chart:
      mark: {{ type: line, point: true }}
      encoding:
        x: {{ field: label, title: null, axis: {{ labelAngle: -15 }} }}
        'y': {{ field: median_deg, type: quantitative, title: 'sim→real median (°)', scale: {{ zero: true }} }}
        color: {{ field: scope, title: Runs }}
    hover: {{ title: stage, fields: [scope, median_deg, p95_deg, mean_deg, runs] }}
  - type: chart
    name: Error before vs after
    from: errors
    filters: 'phase != ""'
    chart:
      mark: {{ type: bar, opacity: 0.7 }}
      encoding:
        x: {{ field: sim_real_deg, type: quantitative, bin: {{ maxbins: 30 }}, title: 'held-out sim→real per run (°)' }}
        'y': {{ aggregate: count, title: runs }}
        color: {{ field: phase, title: null }}
        xOffset: {{ field: phase }}
  - type: table
    name: Parameters
    from: parameters
    groupBy: {{ property: of }}
    order: [parameter, before, after, change_pct, unit, source]
  - type: chart
    name: Models
    from: models
    chart:
      mark: {{ type: bar }}
      encoding:
        'y': {{ field: model, title: null, sort: {{ field: rung }} }}
        x: {{ field: held_out_deg, type: quantitative, title: 'held-out sim→real (°)' }}
        color: {{ field: picked, title: Picked }}
        yOffset: {{ field: of }}
    hover: {{ title: model, fields: [of, held_out_deg, picked, note] }}
  - type: table
    name: Runs
    from: runs
    order: [run_name, joint, held_out, tape, gains, target_real_deg, sim_real_before_deg, sim_real_deg, run_view, rerun]
    sort:
      - {{ property: sim_real_deg, direction: DESC }}
"""


def _page(result: CalibrationResult) -> str:
    import html

    notes = "".join(f"<li>{html.escape(n)}</li>" for n in result.notes)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(result.title)}</title>
<link rel="stylesheet" href="vendor/data-ui/data-ui.css">
<script type="module" src="vendor/data-ui/data-ui.js"></script>
<script type="module" src="vendor/data-ui/dashboard.js"></script>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ecebe6;--mut:#a3a29b}}}}
body{{margin:0;padding:12px 16px 32px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}}
h1{{font-size:19px;margin:0 0 2px}}.sub{{color:var(--mut);margin:0 0 8px;font-size:13px}}details{{color:var(--mut);font-size:12.5px;margin:4px 0 10px}}
.file{{display:none;border-left:3px solid #c98a12;padding:6px 10px;margin:6px 0;background:#fff8ec;color:#1d1d1b}}
</style></head><body>
<h1>{html.escape(result.title)}</h1>
<p class="sub">Calibration result · before = {html.escape(result.stages[0])} → after = {html.escape(result.stages[-1])} · <code>result.display()</code></p>
<p class="file" id="file">Opened from disk: data-ui is ES modules, which no browser loads from file://. <code>result.display()</code> serves it, or:
<code>python3 -m http.server 8791 --bind 127.0.0.1 --directory &lt;this folder&gt;</code></p>
<details><summary>Where the numbers come from</summary><ul>{notes}</ul><p>{html.escape(result.source)}</p></details>
<data-dashboard src="views.base"></data-dashboard>
<script>if(location.protocol==='file:')document.getElementById('file').style.display='block'</script>
</body></html>
"""
