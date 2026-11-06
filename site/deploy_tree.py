"""The deployment tree and the run tags: where each run sits in its deployment, what kind of data it is, and whether the
configuration it ran under was recorded.

Zach, PROJECT - Sim2Real, Nov 5 2026: "each deployment, should have a tree, I guess simlar to the RobotDx Entity tree that allows
you to kinda look at the level you want to look at... And we can see like how the matching is at that level"; "The runs of course
though can also just be flat"; "I think we can tag a run as bench vs real, etc. A real run is just like a segment of real data";
"its super important ... as we do the runs that we record the current configuration values... so ideally we can reproduce!"

Written beside the app's tables in the site's data folder (site/build.py's OUT/data/<dep>/), as site/overlays.py writes its rows:
never a new number, each a lookup or a join of what the producers wrote.

    tree.json   the deployment's tree in RobotDx's shape (io-diagnostics' tree: path ids, a parent, a kind in its icon words): the
                deployment, each fdcanusb adapter its bam_rack_twin record wires its boards to (component.adapter_serial, the field
                bam_rack_twin.hardware.rackmap routes every command by), each station. Every node carries the gate cells under it
                (passing of cells and the worst, by RobotDx's rank, from gates.json), its runs and its type card (type_cards
                registry's card_for, CONTRACT sim2real.type_cards/2).
    runs.json   + node_0 … node_k: the run's station and its ancestors as path ids, each level's values labelled with the node's
                  match (data-ui's `tree` facet draws them in the rail; CONTRACT §7);
                + environment (sim | bench | real), setting (type_cards SETTINGS: bench | deployed) and test_type (a type_cards
                  TestType id the run recorded; none today), each `unknown` / empty unless the run's own files establish it;
                + config: `full` when the run's session recorded its board's whole config (bam_rack_twin.hardware.session's
                  board_configs, its key lines hashing to the sha256 written beside them), else `not recorded`, with what IS
                  recorded (the code, the plan, the run's own commands, the record's gains) in config_detail.

WHY a site overlay and not tools/build_app.py: the tags and the tree are lookups over the registry, the record and each run's
session.json, which the producer's 3.8 GB rebuild does not need to repeat; the same layer already writes the rack's roll-up rows.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from collections import Counter

import adapter
from overlays import RANK, RANK_WORDS, _dump, _load

if str(adapter.REPO) not in sys.path:
    sys.path.append(str(adapter.REPO))  # appended, so the repo's own site/ folder never shadows the stdlib's `site`

from type_cards import registry as reg  # noqa: E402  (CONTRACT.md: one import)

if str(adapter.REPO / "tools") not in sys.path:
    sys.path.append(str(adapter.REPO / "tools"))
import archive_roots  # noqa: E402  (tools/archive_roots.py: the folders a deployment's runs lie under)

REGISTRY = adapter.REPO / "app" / "registry.json"
UNKNOWN = "unknown"
FULL = "full"
NOT_RECORDED = "not recorded"
# WHY these three words (the Nov 5 brief): what made the data. A run's setting (where) is type_cards' SETTINGS; the two vocabularies
# share the word "bench" on purpose: a run on the test rack is a bench run in the bench setting.
ENVIRONMENTS = {
    "sim": "simulated: no hardware moved",
    "bench": "a test run on real hardware (a schedule, a sweep, a tape), not the robot doing its job",
    "real": "a segment of live deployed data: the robot doing its job",
}
# which run basis each environment needs (runs.json's `basis`, data-ui's robotics contract)
BASIS = {"sim": "sim", "bench": "real", "real": "real"}
SNAPSHOT_FROM = "bam_rack_twin.hardware session.json board_configs (conf enumerate at the session's start, read-only)"


# --- the registry and the record --------------------------------------------------------------------------------------

def registry_entries(path: pathlib.Path = REGISTRY) -> dict[str, dict]:
    # WHY expanded: a run's own archive is its days and every live station's schedule runs/ (tools/archive_roots.py, the build's rule)
    return {d["id"]: archive_roots.expanded(d) for d in json.loads(path.read_text())["deployments"]} if path.is_file() else {}


def components(entry: dict) -> dict[str, dict]:
    """{"CAN 11": component} from the deployment's bam_rack_twin record (bam-deployment/1), or {} without one."""
    record = pathlib.Path(entry.get("record") or "")
    if not record.is_file():
        return {}
    return {f"CAN {c['can_id']}": c for c in json.loads(record.read_text()).get("components", []) if c.get("can_id") is not None}


def card_of(word: str | None) -> str | None:
    card = reg.card_for(word) if word else None
    return card.id if card is not None else None


# --- the tree ---------------------------------------------------------------------------------------------------------

def tree_nodes(entry: dict, devices: list[dict]) -> list[dict]:
    """The deployment -> each adapter -> each station, RobotDx's physical composition (host -> bus -> device; io-diagnostics tree.py).
    WHY no host level: the record names each board's adapter, but no run or session records the computer it ran on, and a level
    that is guessed is not one (unknown stays unknown). A station the record wires to no adapter hangs from the deployment."""
    dep_id = entry["id"]
    parts = components(entry)
    nodes = [{"id": dep_id, "parent": None, "kind": "deployment", "label": entry["title"], "depth": 0, "device": None,
              "board": None, "card": card_of(entry.get("kind"))}]
    adapters = {}
    for d in sorted(devices, key=lambda d: d.get("order", 0)):
        serial = (parts.get(d["device"]) or {}).get("adapter_serial")
        if serial and serial not in adapters:
            adapters[serial] = {"id": f"{dep_id}/fdcanusb-{serial}", "parent": dep_id, "kind": "adapter", "label": f"fdcanusb {serial}",
                                "depth": 1, "device": None, "board": None, "card": card_of("adapter")}
            nodes.append(adapters[serial])
    for d in sorted(devices, key=lambda d: d.get("order", 0)):
        part = parts.get(d["device"]) or {}
        up = adapters.get(part.get("adapter_serial")) or nodes[0]
        nodes.append({"id": f"{up['id']}/{adapter.station_key(d['device'])}", "parent": up["id"], "kind": d.get("type") or "device",
                      "label": d["device"], "depth": up["depth"] + 1, "device": d["device"], "board": part.get("driver"),
                      "card": card_of(d.get("type"))})
    return nodes


def under(nodes: list[dict], node: dict) -> list[str]:
    """The devices of the stations at or below a node."""
    children: dict[str | None, list[dict]] = {}
    for n in nodes:
        children.setdefault(n["parent"], []).append(n)
    out, stack = [], [node]
    while stack:
        n = stack.pop()
        if n.get("device"):
            out.append(n["device"])
        stack += children.get(n["id"], [])
    return out


def match(nodes: list[dict], gates: list[dict], runs: list[dict]) -> None:
    """Each node's gate cells (every cell of every station under it, gates.json), passing of them, the worst by RobotDx's rank,
    and its runs. WHY the cells and not a new score: "how the matching is at that level" is the gate cells there, the same cells the
    matrix and the roll-up tree draw."""
    per_device = Counter(r["device"] for r in runs)
    for n in nodes:
        devices = set(under(nodes, n))
        cells = [g for g in gates if g["device"] in devices]
        n["cells"] = len(cells)
        n["passing"] = sum(1 for g in cells if g["verdict"] == "pass")
        n["worst_rank"] = max((RANK.get(g["verdict"], 2) for g in cells), default=None)
        n["worst"] = RANK_WORDS[str(n["worst_rank"])] if n["worst_rank"] is not None else None
        n["runs"] = sum(per_device.get(d, 0) for d in devices)
        n["match"] = f"{n['passing']} of {n['cells']} gate cells pass" if n["cells"] else "no gate cells"
        n["card_url"] = f"/types/{n['card']}/" if n.get("card") else None


def node_label(node: dict) -> str:
    """The rail's words for a node: its name and its gate cells passing, of all of them (a node without cells reads its name only).
    WHY no word after the numbers: the rail's label box is 173 px at 1280 (data-ui clips it with an ellipsis and no title), and
    "fdcanusb 0607623A · 19/55 pass" measured 188 px; the facet's info says what n/m is, and every other place spells it out."""
    return f"{node['label']} · {node['passing']}/{node['cells']}" if node.get("cells") else node["label"]


def path_of(nodes: list[dict], device: str) -> list[dict]:
    """The station node of a device and its ancestors, root first."""
    by_id = {n["id"]: n for n in nodes}
    node = next((n for n in nodes if n.get("device") == device), None)
    chain = []
    while node is not None:
        chain.append(node)
        node = by_id.get(node["parent"])
    return chain[::-1]


# --- the tags ---------------------------------------------------------------------------------------------------------

def tags_of(entry: dict, row: dict) -> dict:
    """environment, setting and test_type for one run: the deployment's declared tags when the run's own files establish them (its
    basis is the one that environment needs and its recording lies in the deployment's own archive), else unknown. WHY never a
    guess (the brief: "Unknown stays unknown"): a run outside the archive days the registry lists is not known to be the rack's."""
    npz = pathlib.Path(row["npz"]) if row.get("npz") else None
    roots = [pathlib.Path(a) for a in entry.get("archive") or []]
    declared = entry.get("environment")
    own = npz is not None and any(npz.is_relative_to(root) for root in roots) and row.get("basis") == BASIS.get(declared)
    environment = declared if declared in ENVIRONMENTS and own else UNKNOWN
    setting = entry.get("setting") if entry.get("setting") in reg.SETTINGS and own else UNKNOWN
    # WHY only a recorded id (type_cards CONTRACT: "a run is tagged with ... when it ran one, its test type's id"): no run records
    # which test type it ran today, and a run's kind does not name one
    # WHY "not recorded" and not an empty cell: the rail lists a value with its count, so /runs/ says that none of its runs records one
    recorded = row.get("test_type")
    ids = {t.id for card in reg.CARDS.values() for t in card.tests}
    return {"environment": environment, "setting": setting, "test_type": recorded if recorded in ids else NOT_RECORDED}


# --- the configuration snapshot ---------------------------------------------------------------------------------------

def session_of(npz: pathlib.Path) -> pathlib.Path | None:
    """bam_rack_twin.hardware.session writes <session>/runs/<run>.npz beside <session>/session.json."""
    folder = npz.parent.parent if npz.parent.name == "runs" else npz.parent
    path = folder / "session.json"
    return path if path.is_file() else None


def key_lines(text: str) -> str:
    """A snapshot file's key lines (moteus_tool --restore-config drops the # header), as their sha256 was taken."""
    return "".join(line + "\n" for line in text.splitlines() if line and not line.startswith("#"))


def config_of(npz: pathlib.Path, can_id: int, cache: dict) -> dict:
    """The run's configuration snapshot: `full` when its session recorded its board's whole config and the file's key lines hash to
    the sha256 written beside them; else `not recorded` and why. Either way, what IS recorded (the code, the plan, the run's own
    commands) in config_detail."""
    session = session_of(npz)
    doc = None
    if session is not None:
        if session not in cache:
            try:
                cache[session] = json.loads(session.read_text())
            except (OSError, ValueError):
                cache[session] = None
        doc = cache[session]
    recorded = ["this run's commands (its args)"]
    code = plan = None
    if doc:
        if doc.get("git_head"):
            code = f"bam_rack_twin {doc.get('package_version') or '?'} @ {str(doc['git_head'])[:7]}"
            recorded.insert(0, f"the code ({code})")
        if doc.get("plan_sha256"):
            plan = str(doc["plan_sha256"])[:12]
            recorded.insert(1, f"the session's plan (sha256 {plan})")
    out = {"config": NOT_RECORDED, "full_config_pct": 0, "config_file": None, "config_sha256": None, "config_keys": None,
           "config_firmware": None, "config_code": code, "config_plan": plan}
    if doc is None:
        out["config_detail"] = (f"Board config not recorded: no session (a single-kind run of bam_rack_twin.hardware, which keeps no session.json). "
                                f"Recorded: {', '.join(recorded)}; the gains come from the record's config_history.")
        return out
    snap = (doc.get("board_configs") or {}).get(str(can_id)) or {}
    why = None
    if not snap:
        why = "its session predates the snapshot (bam_rack_twin.hardware sessions keep each board's whole config since 2026-11-05)"
    elif snap.get("error") or not snap.get("file"):
        why = f"the session's read failed: {snap.get('error') or 'no file'}"
    else:
        path = session.parent / snap["file"]
        if not path.is_file():
            why = f"{snap['file']} is missing from the session"
        elif hashlib.sha256(key_lines(path.read_text(encoding="latin1")).encode("latin1")).hexdigest() != snap.get("sha256"):
            why = f"{snap['file']}'s key lines do not hash to the sha256 session.json records"
        else:
            out.update({"config": FULL, "full_config_pct": 100, "config_file": str(path), "config_sha256": snap["sha256"],
                        "config_keys": snap.get("keys"), "config_firmware": (str(snap.get("firmware") or "")[:7] or None)})
            out["config_detail"] = (f"Full snapshot: the board's whole config at the session's start ({snap.get('keys')} keys, sha256 "
                                    f"{str(snap['sha256'])[:12]}, firmware {out['config_firmware'] or 'unread'}), plus {', '.join(recorded)}.")
            return out
    out["config_detail"] = f"Board config not recorded: {why}. Recorded: {', '.join(recorded)}; the gains come from the record's config_history."
    return out


# --- writing ------------------------------------------------------------------------------------------------------------

LEVEL_TITLE = "Deployment"
FIELDS = {  # the run columns this overlay adds, as robotics-contract schema fields (data-ui fieldToProperty reads title / labels)
    "environment": {"type": "string", "title": "Environment", "description": "What made the data: " + "; ".join(f"{k}: {v}" for k, v in ENVIRONMENTS.items())
                    + "; unknown where the run's own files do not establish it"},
    "setting": {"type": "string", "title": "Setting", "description": "Where it ran (type_cards SETTINGS): " + "; ".join(f"{k}: {v}" for k, v in reg.SETTINGS.items())},
    "test_type": {"type": "string", "title": "Test type", "description": "The type_cards TestType id the run recorded, else not recorded"},
    "config": {"type": "string", "title": "Config snapshot", "description": "full: the board's whole config was read at the session's start and is "
               "kept beside the run; not recorded: it was not (config_detail says what is)"},
    "full_config_pct": {"type": "number", "title": "Full config snapshot", "unit": "%", "description": "100 when the run has a full config snapshot, else 0 "
                        "(their mean over runs is the share of runs with one)"},
    "config_detail": {"type": "string", "title": "Configuration recorded"},
    "config_file": {"type": "string", "title": "Config file"},
    "config_sha256": {"type": "string", "title": "Config sha256"},
    "config_keys": {"type": "integer", "title": "Config keys"},
    "config_firmware": {"type": "string", "title": "Firmware (snapshot)"},
    "config_code": {"type": "string", "title": "Code"},
    "config_plan": {"type": "string", "title": "Plan sha256"},
    "type": {"type": "string", "title": "Type", "description": "the station's type (devices.json), whose card is under Types"},
    "card": {"type": "string", "title": "Type card"},
    "deployment_kind": {"type": "string", "title": "Deployment kind"},
    "deployment_title": {"type": "string", "title": "Deployment"},
}


def level_field(depth: int, labels: dict) -> dict:
    title = LEVEL_TITLE if depth == 0 else f"Tree level {depth}"
    return {"name": f"node_{depth}", "type": "string", "title": title, "labels": labels,
            "description": "the run's place in its deployment's tree (tree.json), as path ids; each labelled with that node's gate cells passing"}


def write_tree(folder: pathlib.Path, entry: dict, nodes: list[dict]) -> None:
    _dump(folder / "tree.json", {
        "name": "tree", "title": f"The tree · {entry['title']}",
        "source": f"{entry.get('record')} (each board's adapter_serial); devices.json; gates.json (the newest acceptance); runs.json; site/deploy_tree.py",
        "schema": {"fields": [{"name": "id", "type": "string"}, {"name": "parent", "type": "string"}, {"name": "label", "type": "string"},
                              {"name": "kind", "type": "string", "description": "RobotDx's icon words: deployment, adapter, servo"},
                              {"name": "depth", "type": "integer"}, {"name": "device", "type": "string"}, {"name": "board", "type": "string"},
                              {"name": "card", "type": "string"}, {"name": "card_url", "type": "string", "display": "link"},
                              {"name": "cells", "type": "integer", "description": "gate cells under the node"},
                              {"name": "passing", "type": "integer", "description": "of them, passing"},
                              {"name": "worst_rank", "type": "integer", "display": "status", "labels": RANK_WORDS},
                              {"name": "worst", "type": "string"}, {"name": "runs", "type": "integer"}, {"name": "match", "type": "string"}]},
        "rows": nodes})


def enrich_runs(folder: pathlib.Path, entry: dict, nodes: list[dict], devices: list[dict]) -> dict:
    """runs.json's rows gain their tree path, tags and configuration snapshot; its schema the matching fields. Returns counts."""
    doc = _load(folder / "runs.json")
    type_of = {d["device"]: d.get("type") for d in devices}
    cache: dict = {}
    depth = 0
    counts = {"environment": Counter(), "setting": Counter(), "config": Counter()}
    for row in doc["rows"]:
        for node in path_of(nodes, row["device"]):
            row[f"node_{node['depth']}"] = node["id"]
            depth = max(depth, node["depth"])
        row.update(tags_of(entry, row))
        can_id = int(row["device"].split()[-1]) if row["device"].split()[-1].isdigit() else None
        row.update(config_of(pathlib.Path(row["npz"]), can_id, cache) if row.get("npz") and can_id is not None
                   else {"config": NOT_RECORDED, "full_config_pct": 0, "config_detail": "Board config not recorded: the run names no recording."})
        row["type"] = type_of.get(row["device"])
        row["card"] = card_of(row["type"])
        row["deployment_kind"] = entry.get("kind")
        row["deployment_title"] = entry.get("title")
        for key in counts:
            counts[key][row[key]] += 1
    labels = {k: {n["id"]: node_label(n) for n in nodes if n["depth"] == k} for k in range(depth + 1)}
    fields = [f for f in doc["schema"]["fields"] if not (f["name"].startswith("node_") or f["name"] in FIELDS)]
    fields += [level_field(k, labels[k]) for k in range(depth + 1)]
    fields += [{"name": name, **spec} for name, spec in FIELDS.items()]
    doc["schema"]["fields"] = fields
    _dump(folder / "runs.json", doc)
    return {"depth": depth, **{k: dict(v) for k, v in counts.items()}}


def write(data: pathlib.Path, registry: pathlib.Path = REGISTRY) -> dict:
    """tree.json and the enriched runs.json for every deployment under data (site/build.py's OUT/data). Returns counts per deployment."""
    entries = registry_entries(registry)
    out = {}
    for dep in _load(data / "deployments.json")["rows"]:
        folder = data / dep["id"]
        entry = {**dep, **entries.get(dep["id"], {})}
        devices = _load(folder / "devices.json")["rows"]
        runs = _load(folder / "runs.json")["rows"]
        gates = _load(folder / "gates.json")["rows"] if (folder / "gates.json").exists() else []
        nodes = tree_nodes(entry, devices)
        match(nodes, gates, runs)
        write_tree(folder, entry, nodes)
        out[dep["id"]] = {"nodes": len(nodes), **enrich_runs(folder, entry, nodes, devices)}
    return out


def depth(site) -> int:
    """The deepest tree level any run of the site sits at (node_<depth>)."""
    return max((int(k.split("_")[1]) for r in site.runs for k in r if k.startswith("node_")), default=0)


def labels(site) -> dict[str, dict[str, str]]:
    """{node_k: {node id: rail words}} over every deployment's tree.json (the flat /runs/ list's tree facet reads them)."""
    out: dict[str, dict[str, str]] = {}
    for dep in site.deployments:
        path = dep.folder / "tree.json"
        for n in (_load(path)["rows"] if path.is_file() else []):
            out.setdefault(f"node_{n['depth']}", {})[n["id"]] = node_label(n)
    return out


def tree(dep) -> list[dict]:
    path = dep.folder / "tree.json"
    return _load(path)["rows"] if path.is_file() else []
