"""Sim2Real's per-rig W&B projects: "Sim2Real · wrist rig" and "Sim2Real · five-bar rig" (proposal C, the default since 2026-11-11).

    env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra tracking python -m sim2real.tracking.rigs --log --views --verify

WHY per rig (the coordinator, 2026-11-11, relaying the W1 sprint: Zach's direction tonight is bottom-up per sub-assembly, introspected
through W&B + Rerun, and it names these two projects): one project per rig, one W&B run per version of what is being fitted, and the
gates as metrics with the SAME names on both rigs, so a cross-project report compares them. Every run still carries proposal B's
slice config (type, level, deployment, joint), so a report over both projects filters by type (decision record:
docs/decision-wandb-one-project-2026-11-11.md, as amended).

A version is a refit of either black box on the rig:
- the twin: one run per twin iteration (result.stages), from wandb_log.records(), each node of the tree beside it; the deployment's
  run is the version's row: held-out sim vs real for the rig and per joint, the objective, its held-out runs as episodes;
- the controller: one run per configuration that changed what the real rig does (the five-bar's Coulomb feed-forward, its gravity
  compensation; the wrist's gain sets), carrying tracking on the coverage set and the tool at a stop, its runs or holds as episodes.
WHY both: the five-bar's tool tracking went 9.4 -> 6.1 mm when Coulomb feed-forward was added (ladders 101015 -> 104843, both on the
mass-ID gravity), within one twin iteration: no twin version can carry it.

Built on bam_ws bam_trackio.bbo (the house black-box template): every version is also a Weave evaluation (bbo.ScoredRun ->
bbo.log_evaluations) and each rig gets its leaderboards (bbo.publish_leaderboard). Nothing is recomputed that the result tree has:
the twin numbers are its error table and verdicts; the controller numbers are the producers' own per-run metrics (ladder summaries,
dwell holds), averaged here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from . import curriculum
from .wandb_log import ENTITY, REPO, browser_url, code_version, push, records, retire, run_id

# WHY loaded by file, not imported or copied: bbo.py is the house template (bam_ws main) and imports only the standard library at
# module level (weave lazily); importing the bam_trackio package would pull trackio, the pick ladder and the trajgen bench, and a
# copy would be the parallel template the coordinator ruled out. BAM_TRACKIO_BBO points elsewhere (a worktree, a test).
BBO = Path(os.environ.get("BAM_TRACKIO_BBO", "/home/bam/bam_ws/src/dev/bam_trackio/bam_trackio/bbo.py"))
HUB = "Sim2Real"   # the one-project layout (proposal B, built first): it now holds the reports that span both rigs
REGISTRY = Path(__file__).resolve().parent / "wandb_rig_views.json"


@dataclass(frozen=True)
class Rig:
    name: str                    # rack_results.load(name)
    project: str                 # its W&B project
    label: str                   # in titles and environments
    joints: tuple[str, ...]      # the joint instances (node id tails) its gates are kept per


RIGS = {
    "ur_wrist": Rig("ur_wrist", "Sim2Real · wrist rig", "UR wrist", ("can14", "can15", "can16")),
    "fivebar": Rig("fivebar", "Sim2Real · five-bar rig", "five-bar", ("j2", "c1")),
}
RIG_CONFIG = {"deployment_kind": "physical", "rig": "One Dof Test Rack"}

# Zach's gate rulings (2026-11-11 21:50): every gate and tracking error comes from the JOINT ENCODERS through FK, never the camera;
# ArUco is a 6-DOF tracked point logged as a flag, never a gate; the gates are read in this order: target vs sim (the controller, in
# sim) first, then sim vs real (the twin, <= 1.5x the same-input repeat floor on the tick clock), then target vs real; the tool gate
# is 1 mm at a settled stop.
GATE_ORDER = ("target_vs_sim", "sim_vs_real", "target_vs_real")

# The gates, one name each on every rig (the coordinator's list, 2026-11-11), so a cross-project report compares them. role: "gate"
# has a pass/fail limit (None = a ratio rule, below), "kpi" is pushed inside a gate with no threshold decided, "flag" is shown and
# never decides anything. Every deployment-level run carries `gate/<name>` for EVERY gate, saying measured or why not, so both
# projects hold the same names even where one rig cannot measure a gate yet.
GATES = {
    "target_vs_sim_tracking_deg": {
        "stage": "target_vs_sim", "role": "kpi", "limit": None,
        "rule": "the controller in sim: RMS of sim vs target per coverage run, per joint (target_vs_sim_tracking_deg_<joint>), the worst "
                "joint as the headline; no threshold decided",
        "missing": "no sim run of this version's coverage set"},
    "target_vs_sim_at_stop_mm": {
        "stage": "target_vs_sim", "role": "gate", "limit": 1.0,
        "rule": "the sim's tool at a settled stop vs its target, by FK, <= 1 mm (proposed: the controller must pass the tool gate in sim "
                "before the real rig can)",
        "missing": "not measured on either rig yet: the five-bar's settled holds have no twin replay, the wrist's tool is not tracked"},
    "heldout_sim_vs_real_deg": {
        "stage": "sim_vs_real", "role": "gate", "limit": None,
        "rule": "held-out sim vs real median, joint encoders; passes when every joint's twin is <= 1.5x the same-input repeat floor of "
                "the same run kind on the tick clock (the tree's Twin answer, judged on the latest twin)",
        "missing": "no held-out runs scored on this version"},
    "tracking_rms_deg": {
        "stage": "target_vs_real", "role": "kpi", "limit": None,
        "rule": "real vs target RMS per coverage run from the joint encoders, per joint (tracking_rms_deg_<joint>), the worst joint as "
                "the headline; no threshold decided",
        "missing": "no real coverage runs on this version"},
    "tracking_rms_tool_mm": {
        "stage": "target_vs_real", "role": "kpi", "limit": None,
        "rule": "the same at the tool, encoders through FK, mean over the coverage set's runs; no threshold decided",
        "missing": "the tool is not tracked on this rig (no FK tool on the wrist's coverage runs)"},
    "target_vs_real_at_stop_mm": {
        "stage": "target_vs_real", "role": "gate", "limit": 1.0,
        "rule": "the real tool at a settled stop vs its target, encoders through FK, <= 1 mm: the same number as tool_error_at_stop_mm "
                "under its gate-order name",
        "missing": "no settled holds on this version (the wrist's tool is not tracked)"},
    "tool_error_at_stop_mm": {
        "stage": "target_vs_real", "role": "gate", "limit": 1.0,
        "rule": "<= 1 mm at a stop, on settled holds, at the tool, encoders through FK (Zach, 2026-11-11)",
        "missing": "no settled holds on this version (the wrist's tool is not tracked)"},
    "home_repeatability_deg": {
        "stage": "target_vs_real", "role": "kpi", "limit": None,
        "rule": "the spread of the homed angle over >= 5 homings from the joint encoders (proposed)",
        "missing": "not measured on either rig yet: needs >= 5 homings from one rest"},
    "aruco_vs_fk_mm": {
        "stage": None, "role": "flag", "limit": None,
        "rule": "a FLAG, never a gate: the ArUco 6-DOF tracked point vs the encoders' FK at the same instant; a large value says look at "
                "the stickers or the as-built geometry, it passes or fails nothing",
        "missing": "not measured: the five-bar's dwell json holds the D435 vs the commanded target (logged as flag_camera_vs_commanded_mm), "
                   "not vs encoder FK; the wrist's holder board carries no tag"},
}


def gate_lines(numbers: dict) -> dict[str, str]:
    """`gate/<name>` for every gate: its stage, rule and either the value here or why it is not measured."""
    out = {}
    for name, gate in GATES.items():
        value = numbers.get(name)
        stage = gate["stage"].replace("_", " ") if gate["stage"] else "flag"
        here = f"measured here: {value:.4g}" if isinstance(value, (int, float)) else f"not measured: {gate['missing']}"
        out[f"gate/{name}"] = f"[{stage} · {gate['role']}] {gate['rule']}. {here}"
    out["gate_order"] = " -> ".join(stage.replace("_", " ") for stage in GATE_ORDER) + " (Zach, 2026-11-11 21:50)"
    return out


# WHY this objective: it is what a refit minimises, and every twin version of every rig has it (the tool gate is the end goal, but
# the wrist's tool is not tracked and the five-bar's was measured on two controller configurations only)
OBJECTIVE = "heldout_sim_vs_real_deg"


def load_bbo():
    """bam_trackio.bbo as a private module object (see BBO)."""
    spec = importlib.util.spec_from_file_location("sim2real_tracking_bbo", BBO)
    module = importlib.util.module_from_spec(spec)
    # WHY registered before exec: bbo's frozen dataclasses (with `from __future__ import annotations`) look their module up in
    # sys.modules to resolve string annotations; an unregistered module object fails at class creation
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------------------------------------------- the twin versions


def _held_out(result) -> dict[tuple[str, str], dict]:
    return {(row["node"], row["stage"]): row for row in result.tables()["error_stats"] if row["scope"] == "held out"}


def twin_episodes(result, stage: str) -> list[dict]:
    """The held-out runs scored on one twin iteration, one row per run x joint, each with its Rerun replay command."""
    rows = []
    for node in result.nodes:
        if node.kind != "joint":
            continue
        slugs = {row["label"]: row["run"] for row in node.runs}
        for error in node.errors:
            if error["stage"] != stage or not error["held_out"] or error.get("sim_real_deg") is None:
                continue
            run = slugs.get(error["run"])
            rows.append({"run": error["run"], "joint": node.id.rsplit("/", 1)[-1], "sim_vs_real_deg": round(error["sim_real_deg"], 4),
                         "real_vs_target_deg": None if error.get("target_real_deg") is None else round(error["target_real_deg"], 4),
                         "rerun": replay(result, run) if run else ""})
    return rows


def replay(result, run_slug: str) -> str:
    """The one command that opens this run in Rerun (CalibrationResult.show, robot_msgs.viz.rerun): target, sim and real.
    WHY a command, not a link: W&B renders only http(s) links, and bam_trackio's 127.0.0.1 launcher accepts the pick ladder's run
    shapes only; this pastes into a terminal as it is."""
    name = {"ur-wrist": "ur_wrist", "fivebar": "fivebar"}.get(result.id.split("-2026")[0], result.id)
    return (f"env -u VIRTUAL_ENV uv run --project {REPO} python -c \"from sim2real.rack_results import load; "
            f"load('{name}').show('{run_slug}')\"")


def twin_extra(result, rig: Rig):
    """The hook wandb_log.records() calls per node x twin iteration: the rig's gates on the deployment's run, the joint's own on
    each joint's, the pass flags on the last iteration only (the tree judges the twin it ends with)."""
    held = _held_out(result)
    verdicts = result.verdicts()
    root = next(n for n in result.nodes if n.parent is None)
    joints = {n.id.rsplit("/", 1)[-1]: n for n in result.nodes if n.kind == "joint"}

    def extra(node, k, role):
        stage = result.stages[k]
        numbers: dict = {}
        text: dict = {}
        tables: dict = {}
        if node.kind == "joint":
            value = (held.get((node.id, stage)) or {}).get("median_deg")
            numbers[OBJECTIVE] = value
            if role == "after":
                numbers["heldout_sim_vs_real_pass"] = int(bool(verdicts[node.id]["answers"]["Twin"]["passes"]))
        elif node.id == root.id:
            numbers[OBJECTIVE] = (held.get((root.id, stage)) or {}).get("median_deg")
            numbers["objective"] = numbers[OBJECTIVE]
            for joint, joint_node in joints.items():
                numbers[f"{OBJECTIVE}_{joint}"] = (held.get((joint_node.id, stage)) or {}).get("median_deg")
            if role == "after":
                passes = [bool(verdicts[n.id]["answers"]["Twin"]["passes"]) for n in joints.values()]
                numbers["heldout_sim_vs_real_pass"] = int(all(passes))
                for joint, joint_node in joints.items():
                    numbers[f"heldout_sim_vs_real_pass_{joint}"] = int(bool(verdicts[joint_node.id]["answers"]["Twin"]["passes"]))
            text.update(gate_lines(numbers))
            text["objective_is"] = f"{OBJECTIVE} (minimise)"
            tables["episodes"] = twin_episodes(result, stage)
        return numbers, text, tables

    return extra


# ---------------------------------------------------------------------------------------------------------------- the controller versions


def _mean(values) -> float | None:
    kept = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.fmean(kept) if kept else None


def _fivebar_ladder(result, folder: str, key: str, title: str, what: str, order: int) -> dict:
    """A five-bar controller version from its coverage raster: each rung's own metrics (the ladder's summary.json), averaged."""
    from ..rack_results import FIVEBAR, slug

    summary = json.loads((FIVEBAR / folder / "ladder" / "summary.json").read_text())
    rungs = [s for s in summary["steps"] if s.get("kind") == "rung" and s.get("result") == "ran" and s.get("metrics")]
    known = {row["run"] for node in result.nodes for row in node.runs}
    episodes = []
    for step in rungs:
        metrics, stats = step["metrics"], step["metrics"].get("stats", {})
        run = slug(f"fivebar-{folder[-6:]} {step['speed_m_s']:.2f} m/s {step['ff_mode']}")
        # WHY the rung's own sim_metrics: the ladder ran the same plan in the sim beside every real rung (bam_fivebar), so target vs
        # sim is the controller alone on the identical input, the first gate in Zach's order; nothing is re-simulated here
        sim, sim_stats = step.get("sim_metrics") or {}, (step.get("sim_metrics") or {}).get("stats", {})
        episodes.append({"rung": step["name"], "speed_m_s": step.get("speed_m_s"), "feed_forward": step.get("ff_mode"),
                         "tool_rms_mm": round(metrics["tool_rms_m"] * 1e3, 3),
                         **{f"{j}_rms_deg": round(math.degrees(stats[f"joints/positions/{j}"]["rms"]), 4)
                            for j in ("j2", "c1") if f"joints/positions/{j}" in stats},
                         **({"sim_tool_rms_mm": round(sim["tool_rms_m"] * 1e3, 3)} if sim.get("tool_rms_m") is not None else {}),
                         **{f"sim_{j}_rms_deg": round(math.degrees(sim_stats[f"joints/positions/{j}"]["rms"]), 4)
                            for j in ("j2", "c1") if f"joints/positions/{j}" in sim_stats},
                         "rerun": replay(result, run) if run in known else ""})
    joint_means = {j: _mean(e.get(f"{j}_rms_deg") for e in episodes) for j in ("j2", "c1")}
    sim_means = {j: _mean(e.get(f"sim_{j}_rms_deg") for e in episodes) for j in ("j2", "c1")}
    numbers = {"tracking_rms_tool_mm": _mean(e["tool_rms_mm"] for e in episodes),
               **{f"tracking_rms_deg_{j}": v for j, v in joint_means.items()},
               "tracking_rms_deg": max(v for v in joint_means.values() if v is not None), "coverage_runs": len(episodes),
               "target_vs_sim_tracking_tool_mm": _mean(e.get("sim_tool_rms_mm") for e in episodes),
               **{f"target_vs_sim_tracking_deg_{j}": v for j, v in sim_means.items()},
               "target_vs_sim_tracking_deg": max((v for v in sim_means.values() if v is not None), default=None)}
    return {"key": key, "title": title, "order": order, "what": what, "environment": "five-bar · coverage raster",
            "source": str(FIVEBAR / folder), "numbers": numbers, "episodes": episodes,
            "feed_forward": {"coulomb_ff_nm": summary.get("coulomb_ff_nm"), "gravity": summary.get("identified"),
                             "lumped": summary.get("lumped")}}


def _fivebar_dwell(path: Path, key: str, title: str, what: str, order: int) -> dict:
    """A five-bar controller version from its 16 three-second holds (the lane's dwell json): the tool at a stop."""
    data = json.loads(path.read_text())
    summary = data["summary"]
    value = summary["encoders_fk_mm"]["median"]
    episodes = [{"hold": row["pose"], "tool_error_mm": round(row["joint_fk_cad_lever_mm"], 3),
                 "j2_error_deg": round(row["motor_error_deg"][0], 4), "c1_error_deg": round(row["motor_error_deg"][1], 4),
                 "camera_frames": row.get("camera_frames"), "rerun": ""} for row in data["rows"] if row.get("motor_error_deg")]
    # WHY encoders_fk_mm and never the camera (Zach, 2026-11-11 21:50): every gate reads the joint encoders through FK; the D435's
    # number is kept as a flag under a name no gate reads (it is the camera vs the COMMANDED target, not vs FK, so not aruco_vs_fk_mm)
    numbers = {"tool_error_at_stop_mm": value, "tool_error_at_stop_pass": int(value <= GATES["tool_error_at_stop_mm"]["limit"]),
               "target_vs_real_at_stop_mm": value, "target_vs_real_at_stop_pass": int(value <= GATES["target_vs_real_at_stop_mm"]["limit"]),
               "tool_error_at_stop_p95_mm": summary["encoders_fk_mm"]["p95"], "holds": len(episodes)}
    if summary.get("camera_vs_commanded_mm", {}).get("median") is not None:
        numbers["flag_camera_vs_commanded_mm"] = summary["camera_vs_commanded_mm"]["median"]
    return {"key": key, "title": title, "order": order, "what": what, "environment": "five-bar · dwell holds",
            "source": data.get("source", str(path)), "numbers": numbers, "episodes": episodes}


def wrist_target_vs_sim(gains: str, twin: str = "record", split: str = "held_out") -> dict[str, float]:
    """The wrist's controller in sim, per joint: the coverage campaign's own target-vs-sim score (bam_ur_wrist_coverage summary.json
    `target_vs_sim`: the median over the split's runs of each run's position RMS) on the twin of record ('record' = refit_rig it5 since
    2026-11-11), in degrees. WHY the held-out split: it is the split the twin is judged on; the campaign scored CAN 15 and 16 only."""
    from ..rack_results import WRIST

    path = WRIST / "summary.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text()).get("target_vs_sim", [])
    return {f"can{row['can_id']}": math.degrees(row["pos_rms_mrad_median"] * 1e-3) for row in rows
            if row["twin"] == twin and row["gains"] == gains and row["split"] == split and row.get("pos_rms_mrad_median") is not None}


def _wrist_gains(result, gains: str, order: int) -> dict:
    """A wrist controller version: one gain set's coverage runs, each run's real-vs-target RMS per joint (the lane's own scores)."""
    episodes = []
    for node in result.nodes:
        if node.kind != "joint":
            continue
        for row in node.runs:
            if row.get("gains") == gains and row.get("target_real_deg") is not None:
                episodes.append({"run": row["label"], "joint": node.id.rsplit("/", 1)[-1], "tape": row.get("tape"),
                                 "held_out": row.get("held_out"), "real_vs_target_deg": row["target_real_deg"],
                                 "rerun": replay(result, row["run"])})
    joint_means = {j: _mean(e["real_vs_target_deg"] for e in episodes if e["joint"] == j) for j in RIGS["ur_wrist"].joints}
    joint_means = {j: v for j, v in joint_means.items() if v is not None}
    sim = wrist_target_vs_sim(gains)
    numbers = {**{f"tracking_rms_deg_{j}": v for j, v in joint_means.items()},
               "tracking_rms_deg": max(joint_means.values()) if joint_means else None, "coverage_runs": len(episodes),
               **{f"target_vs_sim_tracking_deg_{j}": v for j, v in sim.items()},
               "target_vs_sim_tracking_deg": max(sim.values()) if sim else None}
    return {"key": f"gains-{gains}", "title": f"gains: {gains}", "order": order, "what": f"the {gains} gain set's coverage runs",
            "environment": "UR wrist · coverage runs", "source": "ur_wrist/coverage (summary_real.json, it5 player)",
            "numbers": numbers, "episodes": episodes}


def controller_versions(result, rig: Rig) -> list[dict]:
    """The controller configurations that changed what the real rig does, in the order they ran."""
    if rig.name == "fivebar":
        from ..rack_results import DWELL, DWELL_IDENTIFIED

        return [
            _fivebar_dwell(DWELL, "comp-nominal", "gravity comp: nominal", "the 16 holds of the mass-ID run, on the nominal gravity", 1),
            _fivebar_ladder(result, "ladder_real_101015", "ff-stock", "Coulomb feed-forward: none (stock)",
                            "the coverage raster on the mass-ID gravity, no Coulomb feed-forward", 2),
            _fivebar_ladder(result, "ladder_real_104843", "ff-winners", "Coulomb feed-forward: 0.70 / 0.78 N·m (winners)",
                            "the coverage raster on the mass-ID gravity with Coulomb feed-forward", 3),
            _fivebar_ladder(result, "ladder_real_124755", "ff-winners-lumped", "winners + lumped comp",
                            "the coverage raster with the lumped compensation (5 rungs: no 0.05 m/s)", 4),
            _fivebar_dwell(DWELL_IDENTIFIED, "comp-identified", "gravity comp: identified",
                           "the same 16 holds on the identified gravity (the operating config)", 5),
        ]
    return [_wrist_gains(result, gains, order) for order, gains in enumerate(("stock", "ram", "pick_sliding"), 1)]


def controller_records(result, rig: Rig, versions: list[dict], *, sha: str, dirty: bool) -> list[dict]:
    """The controller versions in wandb_log.records()'s shape (for push): one rig-level run each."""
    root = next(n for n in result.nodes if n.parent is None)
    content = json.dumps([{k: v["numbers"] for k, v in ((x["key"], x) for x in versions)}], sort_keys=True, default=str)
    evaluation = hashlib.sha1(content.encode()).hexdigest()[:10]
    out = []
    for version in versions:
        config = {"result_id": f"{result.id}-controller", "evaluation": evaluation, "evaluation_state": "latest", "sim2real_sha": sha,
                  "sim2real_dirty": bool(dirty), "deployment": root.id, "deployment_label": root.label, "node": root.id,
                  "node_label": root.label, "level": "deployment", "type": "deployment", "joint": "", "instance": "rig",
                  "version_kind": "controller", "version": version["key"], "version_title": version["title"],
                  "order": version["order"], "environment": version["environment"], "what": version["what"],
                  "source": version["source"], "stage_role": "controller", **RIG_CONFIG,
                  **({"feed_forward": json.dumps(version["feed_forward"])} if version.get("feed_forward") else {})}
        text = gate_lines(version["numbers"])
        out.append({"id": run_id(result.id, "controller", evaluation, version["key"]), "name": f"{version['order']} · {version['title']}",
                    "group": f"{result.id} · controller · {evaluation}", "job_type": "controller",
                    "tags": sorted({"controller", root.id, "latest"}), "notes": version["what"], "config": config,
                    "history": [{k: v for k, v in version["numbers"].items() if v is not None}], "summary": text,
                    "tables": {"episodes": version["episodes"]}})
    return out


# ---------------------------------------------------------------------------------------------------------------- Weave (bbo)


def scored_runs(bbo, result, rig: Rig, versions: list[dict], twin_batch: list[dict]) -> dict[str, tuple[list, list[str]]]:
    """Every version as a bbo.ScoredRun, grouped by environment with its declared scorers: {environment: (runs, scorers)}."""
    root = next(n for n in result.nodes if n.parent is None)
    groups: dict[str, tuple[list, list[str]]] = {}
    twin_env = f"{rig.label} · held-out runs"
    for record in twin_batch:
        if record["config"]["node"] != root.id:
            continue
        k, stage = record["config"]["iteration"], record["config"]["twin_iteration"]
        last = record["history"][-1]
        episodes = [bbo.Episode(inputs={"run": e["run"], "joint": e["joint"]}, output={"rerun": e["rerun"]},
                                scores={"sim_vs_real_deg": e["sim_vs_real_deg"], "real_vs_target_deg": e["real_vs_target_deg"]})
                    for e in record["tables"].get("episodes", []) if e.get("real_vs_target_deg") is not None]
        summary = {key: value for key, value in last.items()
                   if key == "objective" or key.startswith(OBJECTIVE) or key.startswith("heldout_sim_vs_real_pass")}
        groups.setdefault(twin_env, ([], ["real_vs_target_deg", "sim_vs_real_deg"]))[0].append(bbo.ScoredRun(
            black_box=f"{rig.label} twin", version={"twin": stage, "iteration": k, "result": result.id}, environment=twin_env,
            episodes=episodes, summary=summary,
            attributes={"run_id": record["id"], "sim2real_sha": record["config"]["sim2real_sha"], "evaluation": record["config"]["evaluation"]}))
    for version in versions:
        score_keys = sorted({k for e in version["episodes"] for k, v in e.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
                             and k not in ("hold", "speed_m_s", "camera_frames")})
        episodes = [bbo.Episode(inputs={k: e[k] for k in ("run", "rung", "hold", "joint", "tape") if k in e},
                                output={"rerun": e.get("rerun", "")},
                                scores={k: float(e[k]) for k in score_keys if e.get(k) is not None})
                    for e in version["episodes"]]
        groups.setdefault(version["environment"], ([], score_keys))[0].append(bbo.ScoredRun(
            black_box=f"{rig.label} controller", version={"config": version["key"], "title": version["title"]},
            environment=version["environment"], episodes=episodes,
            summary={k: v for k, v in version["numbers"].items() if v is not None},
            attributes={"run_id": run_id(result.id, "controller-weave", version["key"],
                                         hashlib.sha1(json.dumps(version["numbers"], sort_keys=True).encode()).hexdigest()[:10])}))
    return groups


def log_weave(bbo, rig: Rig, groups: dict[str, tuple[list, list[str]]]) -> dict[str, str]:
    """The evaluations (bbo.log_evaluations) and one leaderboard per environment (bbo.publish_leaderboard); returns name -> ref."""
    # WHY no deletion: bbo deletes evaluation calls whose end was dropped before it retries; this brief forbids deleting anything in
    # Zach's W&B, so an unended call is left in place (it holds no summary, so no leaderboard reads it) and the run is logged again
    bbo.delete_unended = lambda client: 0
    entity_project = f"{ENTITY}/{rig.project}"
    boards = {}
    for environment, (runs, scorers) in groups.items():
        refs = bbo.log_evaluations(entity_project, runs, scorers=scorers)
        keys = sorted({k for run in runs for k in run.summary})
        if environment.endswith("held-out runs"):
            metrics = [bbo.Metric("Held-out sim vs real, all joints (°)", OBJECTIVE, minimize=True)]
            metrics += [bbo.Metric(f"{joint} held-out (°)", f"{OBJECTIVE}_{joint}", minimize=True) for joint in rig.joints
                        if f"{OBJECTIVE}_{joint}" in keys]
            name, what = f"{rig.label} · twin versions", "each twin version on the rig's held-out runs: the objective, held-out sim vs real"
        elif "dwell" in environment:
            metrics = [bbo.Metric("Tool error at a stop (mm, gate 1 mm)", "tool_error_at_stop_mm", minimize=True),
                       bbo.Metric("Passes the 1 mm gate", "tool_error_at_stop_pass")]
            name, what = f"{rig.label} · tool at a stop", "each controller version on the 16 settled holds"
        else:
            metrics = ([bbo.Metric("Tool tracking RMS (mm)", "tracking_rms_tool_mm", minimize=True)] if "tracking_rms_tool_mm" in keys else [])
            metrics += [bbo.Metric("Target vs sim, worst joint (°): the controller in sim", "target_vs_sim_tracking_deg", minimize=True)
                        ] if "target_vs_sim_tracking_deg" in keys else []
            metrics += [bbo.Metric("Joint tracking RMS, worst joint (°)", "tracking_rms_deg", minimize=True)]
            metrics += [bbo.Metric(f"{joint} tracking RMS (°)", f"tracking_rms_deg_{joint}", minimize=True) for joint in rig.joints
                        if f"tracking_rms_deg_{joint}" in keys]
            name, what = f"{rig.label} · tracking on the coverage set", "each controller version on its coverage runs"
        boards[name] = bbo.publish_leaderboard(entity_project, name, f"Sim2Real, {what}. Gates with the same names on every rig.",
                                               refs, metrics, [environment])
    return boards


# ---------------------------------------------------------------------------------------------------------------- the whole rig


def twin_records(result, rig: Rig, *, sha: str, dirty: bool) -> list[dict]:
    """The twin versions in wandb_log.records()'s shape, each run also keyed by `joint` (its instance on a joint node, "" above), so a
    report over both rig projects filters by type, joint and deployment alike."""
    batch = records(result, sha=sha, dirty=dirty, extra_config={**RIG_CONFIG, "version_kind": "twin"}, add=twin_extra(result, rig))
    for record in batch:
        config = record["config"]
        config["joint"] = config["instance"] if config["level"] == "joint" else ""
    return batch


def log_rig(name: str, *, sha: str, dirty: bool, weave: bool = True) -> dict:
    from ..rack_results import load

    rig = RIGS[name]
    result = load(name)
    twin_batch = twin_records(result, rig, sha=sha, dirty=dirty)
    twin = push(twin_batch, project=rig.project)
    retire(result.id, twin_batch[0]["config"]["evaluation"], project=rig.project)
    versions = controller_versions(result, rig)
    control_batch = controller_records(result, rig, versions, sha=sha, dirty=dirty)
    control = push(control_batch, project=rig.project)
    retire(f"{result.id}-controller", control_batch[0]["config"]["evaluation"], project=rig.project)
    if weave:
        bbo = load_bbo()
        boards = log_weave(bbo, rig, scored_runs(bbo, result, rig, versions, twin_batch))
    else:
        boards = {}
    return {"rig": name, "project": rig.project, "twin_runs": len(twin), "twin_new": sum(1 for x in twin if not x["resumed"]),
            "controller_runs": len(control), "controller_new": sum(1 for x in control if not x["resumed"]), "leaderboards": boards}


def build_views(*, registry: Path = REGISTRY) -> dict:
    """Per rig: one report and one saved view; in the hub project: one report over both rigs, filtered by type (proposal B's
    view, kept across projects by the config on every run). Updated in place on a rebuild."""
    import wandb_workspaces.reports.v2 as wr
    import wandb_workspaces.workspaces as ws
    from wandb_workspaces import expr

    from ..rack_results import load
    from .wandb_log import _ladders_markdown, _save_report, _status_markdown

    known = json.loads(registry.read_text()) if registry.exists() else {}
    urls = {"views": dict(known.get("views", {})), "reports": dict(known.get("reports", {}))}
    L = wr.Layout
    latest = expr.Config("evaluation_state") == "latest"
    gates_md = "\n".join(f"- `{name}` ({(gate['stage'] or 'flag').replace('_', ' ')} · {gate['role']}): {gate['rule']}" for name, gate in GATES.items())
    results = {name: load(name) for name in RIGS}
    for name, rig in RIGS.items():
        result = results[name]
        twin_rows = [latest, expr.Config("version_kind") == "twin", expr.Config("level") == "deployment"]
        controller_rows = [latest, expr.Config("version_kind") == "controller"]
        twin_panels = [wr.BarPlot(title="Held-out sim vs real per twin version (°): the objective", metrics=[OBJECTIVE], orientation="h",
                                  layout=L(x=0, y=0, w=12, h=8)),
                       wr.LinePlot(title="Held-out sim vs real across twin iterations (°)", x="iteration", y=["trend/heldout_median_deg"],
                                   layout=L(x=12, y=0, w=12, h=8)),
                       wr.BarPlot(title="Per joint, per twin version (°)", metrics=[f"{OBJECTIVE}_{j}" for j in rig.joints], orientation="h",
                                  layout=L(x=0, y=8, w=24, h=8)),
                       wr.WeavePanelSummaryTable(table_name="episodes", layout=L(x=0, y=16, w=24, h=10))]
        controller_panels = [wr.BarPlot(title="Gate 1 · target vs sim, worst joint (°): the controller in sim",
                                        metrics=["target_vs_sim_tracking_deg"], orientation="h", layout=L(x=0, y=24, w=12, h=8)),
                             wr.BarPlot(title="Gate 3 · target vs real on the coverage set, worst joint (°)", metrics=["tracking_rms_deg"],
                                        orientation="h", layout=L(x=0, y=0, w=12, h=8)),
                             wr.BarPlot(title="Target vs sim per joint (°)", metrics=[f"target_vs_sim_tracking_deg_{j}" for j in rig.joints],
                                        orientation="h", layout=L(x=12, y=24, w=12, h=8)),
                             wr.BarPlot(title="Target vs real per joint (°)", metrics=[f"tracking_rms_deg_{j}" for j in rig.joints],
                                        orientation="h", layout=L(x=12, y=0, w=12, h=8))]
        if name == "fivebar":
            controller_panels += [wr.BarPlot(title="Tool tracking on the coverage set (mm)", metrics=["tracking_rms_tool_mm"], orientation="h",
                                             layout=L(x=0, y=8, w=12, h=8)),
                                  wr.BarPlot(title="Tool at a stop, settled holds (mm, gate 1 mm)", metrics=["tool_error_at_stop_mm"],
                                             orientation="h", layout=L(x=12, y=8, w=12, h=8))]
        controller_panels.append(wr.WeavePanelSummaryTable(table_name="episodes", layout=L(x=0, y=16, w=24, h=10)))
        tree_rows = [latest, expr.Config("version_kind") == "twin", expr.Config("level") == "deployment", expr.Config("stage_role") == "after"]
        root = next(n for n in result.nodes if n.parent is None)
        blocks = [
            wr.MarkdownBlock(text=(f"**{root.label}**: one run per version of what is fitted on this rig (each twin iteration; each "
                                   "controller configuration that changed what the real rig does), the gates as metrics with the same "
                                   f"names on every rig, the objective `{OBJECTIVE}` (minimise). Every run also carries `type`, `level`, "
                                   "`deployment` and `joint`, so a report over both rigs filters by type.\n\n" + gates_md)),
            wr.H2(text="Today's status: every node's rungs"),
            wr.MarkdownBlock(text=_status_markdown([result], lambda r, n: True)
                             + "\n\n✓ passed · ~ partial · ✗ no · ? unknown · ↓ its own answer is yes, a child holds it back."),
            wr.H2(text="Twin versions"),
            wr.PanelGrid(runsets=[wr.Runset(entity=ENTITY, project=rig.project, name="twin versions", filters=twin_rows)],
                         panels=twin_panels),
            wr.H2(text="Controller versions"),
            wr.PanelGrid(runsets=[wr.Runset(entity=ENTITY, project=rig.project, name="controller versions", filters=controller_rows)],
                         panels=controller_panels),
            wr.H2(text="The tree (latest twin)"),
            wr.PanelGrid(hide_run_sets=True, runsets=[wr.Runset(entity=ENTITY, project=rig.project, name="latest", filters=tree_rows)],
                         panels=[wr.WeavePanelSummaryTable(table_name="tree", layout=L(x=0, y=0, w=24, h=12)),
                                 wr.WeavePanelSummaryTable(table_name="questions_all", layout=L(x=0, y=12, w=24, h=12))]),
            wr.H2(text="The ladders"),
            wr.MarkdownBlock(text=_ladders_markdown(["deployment", "arm", "joint", "tool"])),
        ]
        urls["reports"][name] = _save_report(wr, ENTITY, rig.project, urls["reports"].get(name), f"{rig.project} · versions and gates",
                                             f"Twin and controller versions of the {rig.label}, the same-named gates, the curriculum", blocks)
        sections = [ws.Section(name="Twin versions", panels=twin_panels[:3], is_open=True),
                    ws.Section(name="Controller versions", panels=controller_panels[:-1], is_open=True)]
        settings = ws.RunsetSettings(filters=[latest, expr.Config("level") == "deployment"],
                                     pinned_columns=["config:version_kind", "config:twin_iteration", "config:version_title", f"summary:{OBJECTIVE}",
                                                     "summary:target_vs_sim_tracking_deg", "summary:tool_error_at_stop_mm",
                                                     "summary:tracking_rms_deg"])
        view = None
        if name in urls["views"]:
            try:
                view = ws.Workspace.from_url(urls["views"][name])
                view.name, view.sections, view.runset_settings = f"{rig.label} · versions", sections, settings
            except Exception:   # deleted in the app, or a URL from_url cannot parse: make it again
                view = None
        if view is None:
            view = ws.Workspace(entity=ENTITY, project=rig.project, name=f"{rig.label} · versions", sections=sections, runset_settings=settings)
        view.save()
        urls["views"][name] = browser_url(view.url)
    # proposal B's benefit across projects: one report, a runset per rig, filtered by type
    servo = [latest, expr.Config("type") == "integrated_servo", expr.Config("stage_role") == "after"]
    runsets = [wr.Runset(entity=ENTITY, project=rig.project, name=rig.label, filters=servo) for rig in RIGS.values()]
    panels = [wr.BarPlot(title="Twin ÷ floor, same run kind (twinned ≤ 1.5×)", metrics=["Twin/ratio"], orientation="h", layout=L(x=0, y=0, w=12, h=8)),
              wr.BarPlot(title="Floor (°)", metrics=["Floor/floor_deg"], orientation="h", layout=L(x=12, y=0, w=12, h=8)),
              wr.BarPlot(title="Held-out sim vs real (°)", metrics=[OBJECTIVE], orientation="h", layout=L(x=0, y=8, w=12, h=8)),
              wr.BarPlot(title="Settled stop ÷ its share of the 1 mm gate", metrics=["Job/settled_over_share"], orientation="h",
                         layout=L(x=12, y=8, w=12, h=8)),
              wr.BarPlot(title="Questions passed in order (5 = all)", metrics=["questions_passed"], orientation="h", layout=L(x=0, y=16, w=24, h=8)),
              wr.WeavePanelSummaryTable(table_name="questions", layout=L(x=0, y=24, w=24, h=12))]
    gate_runsets = [wr.Runset(entity=ENTITY, project=rig.project, name=f"{rig.label} versions",
                              filters=[latest, expr.Config("level") == "deployment"]) for rig in RIGS.values()]
    gate_panels = [wr.BarPlot(title="1 · target vs sim, worst joint (°)", metrics=["target_vs_sim_tracking_deg"], orientation="h",
                              layout=L(x=0, y=0, w=12, h=8)),
                   wr.BarPlot(title="2 · held-out sim vs real (°)", metrics=[OBJECTIVE], orientation="h", layout=L(x=12, y=0, w=12, h=8)),
                   wr.BarPlot(title="3 · target vs real on the coverage set, worst joint (°)", metrics=["tracking_rms_deg"],
                              orientation="h", layout=L(x=0, y=8, w=12, h=8)),
                   wr.BarPlot(title="3 · tool at a settled stop, encoders + FK (mm, gate 1 mm)", metrics=["tool_error_at_stop_mm"],
                              orientation="h", layout=L(x=12, y=8, w=12, h=8))]
    blocks = [wr.MarkdownBlock(text=("Every servo joint on every rig, from the per-rig projects: one runset per rig, each filtered "
                                     "`type = integrated_servo`, latest evaluation, last twin iteration. The per-rig projects are the "
                                     "default home (proposal C); this report is how proposal B's one-place, filter-by-type view survives "
                                     "across them.")),
              wr.PanelGrid(runsets=runsets, panels=panels),
              wr.H2(text="The same-named gates on both rigs, in Zach's order"),
              wr.MarkdownBlock(text=("Target vs sim (the controller) first, then sim vs real (the twin), then target vs real; every number "
                                     "from the joint encoders through FK, ArUco a flag only (Zach, 2026-11-11 21:50). Every twin and "
                                     "controller version of each rig, latest evaluation.\n\n" + gates_md)),
              wr.PanelGrid(runsets=gate_runsets, panels=gate_panels)]
    urls["reports"]["servo-across-rigs"] = _save_report(wr, ENTITY, HUB, urls["reports"].get("servo-across-rigs"),
                                                        "Sim2Real · servo joints across rigs", "type = integrated_servo over both rig projects",
                                                        blocks)
    registry.write_text(json.dumps(urls, indent=1, sort_keys=True) + "\n")
    return urls


def verify(*, registry: Path = REGISTRY) -> list[str]:
    """Read both rig projects back: one twin-version run per twin iteration, the controller versions, the same gate names on both
    rigs, a type filter in each project returning that rig's joints, the reports; returns the failures."""
    import wandb

    from ..rack_results import load

    api = wandb.Api(timeout=60)
    failures: list[str] = []
    names_per_rig = {}
    for name, rig in RIGS.items():
        result = load(name)
        path = f"{ENTITY}/{rig.project}"
        versions = list(api.runs(path, filters={"config.evaluation_state": "latest", "config.version_kind": "twin",
                                                "config.level": "deployment"}))
        print(f"{rig.project}: {len(versions)} twin-version runs -> "
              + "; ".join(f"{r.config.get('iteration')} {r.config.get('twin_iteration')}: {OBJECTIVE} {r.summary.get(OBJECTIVE)}"
                          for r in sorted(versions, key=lambda r: r.config.get("iteration", 0))))
        if len(versions) != len(result.stages):
            failures.append(f"{rig.project}: {len(versions)} twin versions, want {len(result.stages)}")
        control = list(api.runs(path, filters={"config.evaluation_state": "latest", "config.version_kind": "controller"}))
        print(f"  {len(control)} controller-version runs -> "
              + "; ".join(f"{r.name}: " + ", ".join(f"{k} {r.summary.get(k):.3f}" for k in ("tracking_rms_tool_mm", "tracking_rms_deg",
                                                                                        "tool_error_at_stop_mm") if isinstance(r.summary.get(k), (int, float)))
                          for r in sorted(control, key=lambda r: r.config.get("order", 0))))
        servo = list(api.runs(path, filters={"config.evaluation_state": "latest", "config.stage_role": "after", "config.type": "integrated_servo"}))
        want = sorted(n.label for n in result.nodes if n.kind == "joint")
        print(f"  filter type=integrated_servo: {sorted(r.name for r in servo)}")
        if sorted(r.name for r in servo) != want:
            failures.append(f"{rig.project}: type filter gave {sorted(r.name for r in servo)}, want {want}")
        names_per_rig[name] = {k for r in versions + control for k in r.summary.keys() if k.split("_")[0] in
                               ("tool", "heldout", "tracking", "home", "objective", "target", "aruco")}
        lines = {frozenset(k for k in r.summary.keys() if k.startswith("gate/")) for r in versions + control}
        print(f"  gate lines on every deployment run: {sorted(len(x) for x in lines)} of {len(GATES)}")
        if lines != {frozenset(f"gate/{g}" for g in GATES)}:
            failures.append(f"{rig.project}: a deployment run lacks a gate line")
    shared = set.intersection(*names_per_rig.values())
    print(f"  gate keys on both rigs: {sorted(k for k in shared if not any(k.endswith('_' + j) for rig in RIGS.values() for j in rig.joints))}")
    for gate in ("heldout_sim_vs_real_deg", "tracking_rms_deg", "target_vs_sim_tracking_deg"):
        if gate not in shared:
            failures.append(f"{gate} is not on both rigs")
    urls = json.loads(registry.read_text()) if registry.exists() else {}
    for key, url in sorted(urls.get("reports", {}).items()):
        project = HUB if key == "servo-across-rigs" else RIGS[key].project
        ids = {str(report.id) for report in api.reports(f"{ENTITY}/{project}")}
        if url.rsplit("--", 1)[-1] not in ids:
            failures.append(f"report {key} not in {project}")
    print(f"  reports: {sorted(urls.get('reports', {}))}; saved views: {sorted(urls.get('views', {}))}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--log", action="store_true", help="log both rigs: twin and controller versions, Weave evaluations, leaderboards")
    parser.add_argument("--no-weave", action="store_true", help="W&B runs only")
    parser.add_argument("--views", action="store_true", help="build or update each rig's report and saved view, and the cross-rig report")
    parser.add_argument("--verify", action="store_true", help="read both projects back through the W&B API")
    parser.add_argument("--allow-dirty", action="store_true", help="log even when src/ has uncommitted changes")
    args = parser.parse_args(argv)
    sha, dirty = code_version()
    if args.log and dirty and not args.allow_dirty:
        parser.error(f"src/ has uncommitted changes (HEAD {sha[:9]}): commit them, or pass --allow-dirty")
    if args.log:
        for name in RIGS:
            print(json.dumps(log_rig(name, sha=sha, dirty=dirty, weave=not args.no_weave), indent=1))
    if args.views:
        for kind, items in build_views().items():
            for key, url in sorted(items.items()):
                print(f"{kind[:-1]:6s} {key:22s} {url}")
    if args.verify:
        failures = verify()
        print("VERIFY: " + ("PASS" if not failures else "FAIL\n  " + "\n  ".join(failures)))
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
