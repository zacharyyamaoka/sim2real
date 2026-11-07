"""Deployments, their trees, and the parameters table: the v3 instance level (type_cards/CONTRACT.md, "Domain model v3").

Zach (PROJECT - Sim2Real, 2026-11-06): "I like organizing this around Deployments. The orcale examples are also deployments its just they
are 'Virtual' ... Each sub componet of the deployment could basically be its own deployment (in fact it almost is) ... the first level of
filtering ... deployments tagged with orcale example. Or perhaps only deployments that use a camera"; "On the left should be like an
entity tree ... the standard dashboard for that level"; the parameter view with its presets ("all of the paramteres ... the Winning
model(s) ... at least some model run and rpocuded datata") and "each model ... its own Recovered error toerlance colum".

Pure functions over what the producers wrote, never a new number:
- virtual_nodes(results): the six oracle examples, each tree exactly its sysid result's typed tree, every node typed in v3;
- physical_nodes(data): each registry deployment's tree in RobotDx's shape (deployment -> fdcanusb adapter -> station, as
  site/deploy_tree.py builds it), each station's parts (its type's members, labelled from the bam_rack_twin record; a gearbox the record
  calls "none" is absent) and the cameras its v3 record declares (type_cards/deployments/);
- parameter_table(nodes, results, routines): one row per parameter of every typed node, the oracle's values where it graded one (each
  value bound to the part it belongs to, owner(), never to its deployment's type), one column group per (routine, model) from
  sysid/results/calibration_routines.json at the oracle's own noise ("1x");
- label_model(deployment, label): the ladder model a producer's model label is (type_cards/deployments/<id>.py `models`), exact words;
- write(data): the site's projections under <data>/domain/ (site/build.py calls it after deploy_tree.write).
A node is a deployment of its own: its subtree (subtree) and its children (sub_deployments). Stdlib only.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from pathlib import Path

from . import domain as dm
from . import registry as reg

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "sysid" / "results"
REGISTRY = REPO / "app" / "registry.json"
SCHEDULES = Path(os.environ.get("SIM2REAL_SCHEDULES") or "/archive/datasets/bam_rig/schedules")
EXAMPLES = ("pendulum_can11", "ur5e", "ur5e_2f85", "conveyor", "dual_arm_cell", "linescan_cell")  # site/landing.py's
LEVEL = "1x"  # the oracle's own noise: the committed oracle results are the ladder's 1x rows
RESULT_PROPERTIES = ("recovered", "ci95_lo", "ci95_hi", "interval", "error", "tolerance", "error_over_tolerance", "within")
NODE_FIELDS = ("id", "root", "parent", "depth", "title", "kind", "tags", "structural", "entity_type", "entity_title", "card", "device",
               "sysid_id", "sees", "runs", "children", "page", "source", "machine", "where", "summary", "dashboard", "dashboard_panels",
               "components", "current_models", "limits")
STATION_PARTS = ("motor", "driver", "gearbox", "encoder")  # the integrated servo's members, in the record's words


def load_results(root: Path = RESULTS) -> dict[str, dict]:
    return {ex: json.loads((root / f"{ex}.json").read_text(encoding="utf-8")) for ex in EXAMPLES if (root / f"{ex}.json").is_file()}


def physical_records() -> dict:
    from . import deployments  # noqa: PLC0415

    return deployments.records()


def _rows(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8")).get("rows", []) if path.is_file() else []


def _node(**kw) -> dict:
    node = {f: None for f in NODE_FIELDS}
    node["limits"] = []
    node.update(kw)
    tid = node.get("entity_type")
    if tid:
        t = dm.TYPES[tid]
        node.update(entity_title=t.title, dashboard=t.dashboard.template, dashboard_panels=list(t.dashboard.panels),
                    components=list(t.dashboard.components), current_models=[m.id for m in t.models if m.current])
    else:
        d = dm.STRUCTURAL.get(node.get("structural") or "", None)
        node.update(dashboard=None, dashboard_panels=list(d.panels) if d else [], components=[], current_models=[])
    return node


def _finish(nodes: list[dict], declared: tuple[str, ...]) -> list[dict]:
    """Children counts, and each node's tags: its deployment's declared ones and those derived from the types in its own subtree."""
    kids = Counter(n["parent"] for n in nodes)
    order = list(dm.TAGS)
    for n in nodes:
        types = {x["entity_type"] for x in subtree(nodes, n["id"]) if x["entity_type"]}
        tags = set(declared) | {dm.TAG_OF_TYPE[t] for t in types if t in dm.TAG_OF_TYPE}
        n["tags"] = sorted(tags, key=lambda t: order.index(t) if t in order else len(order))
        n["children"] = kids.get(n["id"], 0)
    return nodes


def subtree(nodes: list[dict], node_id: str) -> list[dict]:
    """The node and everything under it, the node first (a sub-deployment's own tree)."""
    by_parent: dict = {}
    for n in nodes:
        by_parent.setdefault(n["parent"], []).append(n)
    start = next(n for n in nodes if n["id"] == node_id)
    out, stack = [], [start]
    while stack:
        n = stack.pop(0)
        out.append(n)
        stack[0:0] = by_parent.get(n["id"], [])
    return out


def sub_deployments(nodes: list[dict], node_id: str) -> list[dict]:
    return [n for n in nodes if n["parent"] == node_id]


# --- virtual: the oracle's examples ----------------------------------------------------------------------------------------------------

def _virtual_type(row: dict) -> tuple[str | None, str | None]:
    if row["parent"] is None:
        return None, "deployment"
    if row["type"] == "arm_6dof_gripper":
        return None, "assembly"  # an arm with its gripper: a composition of a chain and a gripper, not a type (Zach: types are generic)
    if row["type_source"] == "type_cards":
        return dm.CARD_TYPE[row["type"]], None
    if row["type"] in dm.TYPES:
        return row["type"], None  # sysid's adapter word that v3 now has a type for (the 2F-85: gripper)
    if row["type"] in dm.STRUCTURAL:
        return None, row["type"]
    raise ValueError(f"sysid tree node {row['id']!r} has a type v3 does not know: {row['type']!r}")


def virtual_nodes(results: dict[str, dict]) -> list[dict]:
    out = []
    for ex in EXAMPLES:
        doc = results.get(ex)
        if not doc:
            continue
        ids: dict[str, str] = {}
        mine = []
        for row in doc["tree"]:
            nid = ex if row["parent"] is None else f"{ids[row['parent']]}/{row['id']}"
            ids[row["id"]] = nid
            tid, structural = _virtual_type(row)
            mine.append(_node(id=nid, root=ex, parent=None if row["parent"] is None else ids[row["parent"]], depth=row["depth"],
                              title=doc["title"] if row["parent"] is None else row["title"], kind="virtual", structural=structural,
                              entity_type=tid, card=row["type"] if row["type_source"] == "type_cards" else None, sysid_id=row["id"], sees=[],
                              runs=0, page=f"/sysid/{ex}/", source=f"sysid/results/{ex}.json tree ({row['type_source']})",
                              machine=doc.get("subtitle") if row["parent"] is None else None,
                              where="simulation (sysid/examples/" + ex + ")" if row["parent"] is None else None,
                              summary=doc.get("summary") if row["parent"] is None else None))
        out += _finish(mine, ("oracle example",))
    return out


# --- physical: the registry's deployments ----------------------------------------------------------------------------------------------

def _components(entry: dict) -> dict[str, dict]:
    record = Path(entry.get("record") or "")
    if not record.is_file():
        return {}
    return {f"CAN {c['can_id']}": c for c in json.loads(record.read_text()).get("components", []) if c.get("can_id") is not None}


def physical_nodes(data: Path, registry: Path = REGISTRY) -> list[dict]:
    entries = json.loads(registry.read_text())["deployments"] if registry.is_file() else []
    app = {r["id"]: r for r in _rows(Path(data) / "deployments.json")}
    records = physical_records()
    out = []
    for entry in entries:
        dep = entry["id"]
        rec = records.get(dep) or dm.PhysicalDeployment(id=dep)
        folder = Path(data) / dep
        devices = sorted(_rows(folder / "devices.json"), key=lambda d: d.get("order", 0))
        runs = Counter(r["device"] for r in _rows(folder / "runs.json"))
        parts = _components(entry)
        row = app.get(dep, {})
        mine = [_node(id=dep, root=dep, parent=None, depth=0, title=entry["title"], kind="physical", structural="deployment", sees=[],
                      runs=sum(runs.values()), page=f"/{dep}/", machine=entry.get("kind"), where=entry.get("where"),
                      summary=entry.get("summary") or row.get("summary"),
                      source=f"app/registry.json; type_cards/deployments/{dep.replace('-', '_')}.py; {entry.get('record') or 'no record'}")]
        adapters: dict[str, dict] = {}
        stations: dict[int, str] = {}
        for d in devices:
            serial = (parts.get(d["device"]) or {}).get("adapter_serial")
            if serial and serial not in adapters:
                adapters[serial] = _node(id=f"{dep}/fdcanusb-{serial}", root=dep, parent=dep, depth=1, title=f"fdcanusb {serial}", kind="physical",
                                         structural="adapter", sees=[], page=f"/{dep}/", source=f"{entry.get('record')} (adapter_serial)")
                mine.append(adapters[serial])
        for d in devices:
            comp = parts.get(d["device"]) or {}
            up = adapters.get(comp.get("adapter_serial")) or mine[0]
            key = d["device"].lower().replace(" ", "")
            sid = f"{up['id']}/{key}"
            tid = dm.CARD_TYPE.get(d.get("type") or "")
            mine.append(_node(id=sid, root=dep, parent=up["id"], depth=up["depth"] + 1, title=f"{d['device']} · {d.get('station') or ''}".rstrip(" ·"),
                              kind="physical", structural="station", entity_type=tid, card=d.get("type"), device=d["device"], sees=[],
                              runs=runs.get(d["device"], 0), page=f"/{dep}/{key}/", source="devices.json (tools/build_app.py)"))
            if comp.get("can_id") is not None:
                stations[int(comp["can_id"])] = sid
            for part in STATION_PARTS if comp else ():
                label = comp.get(part) or ("the board's rotor encoder" if part == "encoder" else None)
                if not label or str(label).lower().startswith("none"):
                    continue
                member = next(p for p in dm.TYPES["integrated_servo"].members if p.role and _member_word(p) == part)
                mine.append(_node(id=f"{sid}/{part}", root=dep, parent=sid, depth=up["depth"] + 2, title=f"{part}: {label}", kind="physical",
                                  entity_type=member.type, device=d["device"], sees=[], runs=runs.get(d["device"], 0), page=f"/{dep}/{key}/",
                                  source=f"{entry.get('record')} ({part})" if comp.get(part) else "the integrated servo type's members (every moteus "
                                  "commutates from its own rotor encoder; the record names none)"))
            if tid is None:
                raise ValueError(f"{dep} {d['device']}: devices.json type {d.get('type')!r} has no v3 type")
        for cam in rec.cameras:
            mine.append(_node(id=f"{dep}/camera-{cam.serial}", root=dep, parent=dep, depth=1, title=f"{cam.model} · {cam.serial}", kind="physical",
                              entity_type=cam.type, sees=[stations[c] for c in cam.sees if c in stations], runs=None, page=f"/{dep}/",
                              source=cam.source))
        bound = unit_limits(rec, mine)
        for n in mine:
            n["limits"] = bound.get(n["id"], [])
        out += _finish(mine, rec.tags)
    return out


LIMIT_SIDES = ("warn", "error", "target")


def unit_limits(record: dm.PhysicalDeployment, nodes: list[dict]) -> dict[str, list[dict]]:
    """{node id: [{diagnostic, warn?, error?, target?, source, note?}]}: each of the record's per-unit limits on the typed node at its device
    whose type holds that diagnostic (a station's servo diagnostics, its driver's). A side the unit does not set is left out. A limit that
    binds no node (a diagnostic no type at that device holds, a device not in the tree) is refused: a typo must not read as unknown."""
    out: dict[str, list[dict]] = {}
    for u in record.limits:
        hosts = [n for n in nodes if n.get("device") == u.device and n.get("entity_type")
                 and any(d.id == u.diagnostic for d in dm.TYPES[n["entity_type"]].diagnostics)]
        if not hosts:
            raise ValueError(f"{record.id}: the limit on {u.diagnostic} at {u.device} binds no node (no node there has a type with that diagnostic)")
        entry = {"diagnostic": u.diagnostic, **{k: getattr(u, k) for k in LIMIT_SIDES if getattr(u, k) is not None}, "source": u.source,
                 **({"note": u.note} if u.note else {})}
        for n in hosts:
            if any(x["diagnostic"] == u.diagnostic for x in out.get(n["id"], [])):
                raise ValueError(f"{record.id}: two limits on {u.diagnostic} at {u.device}")
            out.setdefault(n["id"], []).append(dict(entry))
    return out


def label_model(deployment: str, label: str | None) -> dm.ModelLabel | None:
    """The ladder model a producer's label names on a physical deployment (type_cards/deployments/<id>.py `models`), looked up by the
    label's exact words (never a prefix, never parsed); None for a label nobody mapped (unknown stays unknown)."""
    record = physical_records().get(deployment)
    return next((m for m in record.models if m.label == label), None) if record and label else None


def model_labels_dataset() -> dict:
    """model_labels.json: every physical deployment's producer labels and the ladder model each is, in the house table shape."""
    rows = []
    for dep, record in physical_records().items():
        for m in record.models:
            spec = dm.model(m.type, m.model)
            rows.append({"deployment": dep, "label": m.label, "type": m.type, "model": m.model, "model_key": spec.key, "model_title": spec.title,
                         "family": spec.family, "k": spec.k, "fit": m.fit, "friction": m.friction, "differs": m.differs, "source": m.source})
    return {"name": "model_labels", "title": "The producers' model labels and the ladder model each one is", "contract": dm.SCHEMA,
            "source": "type_cards/deployments/<id>.py models (read off the producer's own twin builds)", "schema": {"fields": fields_of(rows)},
            "rows": rows}


def _member_word(part: dm.Part) -> str:
    return {"bldc_motor": "motor", "foc_controller": "driver", "gearbox": "gearbox", "encoder": "encoder"}.get(part.type, part.type)


def field_type(values) -> str:
    """The robotics contract's word for a column (string, number, integer, boolean, array) from the values it holds."""
    seen = {type(v) for v in values if v is not None}
    if seen <= {bool} and seen:
        return "boolean"
    if seen and seen <= {list, tuple}:
        return "array"
    if seen and seen <= {int}:
        return "integer"
    if seen and seen <= {int, float}:
        return "number"
    return "string"


def fields_of(rows: list[dict], order=()) -> list[dict]:
    names = list(dict.fromkeys(list(order) + [k for r in rows for k in r]))
    return [{"name": n, "type": field_type(r.get(n) for r in rows)} for n in names]


def deployments_dataset(nodes: list[dict]) -> dict:
    """deployments.json: every node of every deployment, in the house table shape (its tree is `parent`; the index is `parent == null`)."""
    fields = fields_of(nodes, NODE_FIELDS)
    for f in fields:
        if f["name"] in ("tags", "sees", "dashboard_panels", "components", "current_models"):
            f["type"] = "array"
        if f["name"] in ("depth", "runs", "children"):
            f["type"] = "integer"
    return {"name": "deployments", "title": "Deployments, and every part of each as a deployment of its own", "contract": dm.SCHEMA,
            "source": "type_cards/instances.py over sysid/results (virtual) and app/registry.json + type_cards/deployments/ + the app's data (physical)",
            "schema": {"fields": fields}, "tree": {"parent": "parent"},
            "index": "rows whose parent is null are the deployments; the rest are their parts, each a deployment of its own (its subtree)",
            "rows": nodes}


# --- the parameters table --------------------------------------------------------------------------------------------------------------

def _v2_name(card_parameter: str) -> str:
    """sysid writes the card's parameter as "<name>" or "<name> (<which part of it>)": the name is the first word."""
    return card_parameter.split(" (")[0].strip()


def _winning(nodes: list[dict], results: dict) -> dict[tuple[str, str], tuple[set, str]]:
    """{(deployment, type): (the winning models' parameters, basis)}: the selection rule's pick where the example ran one on that type
    (sysid's selected_rung, held out), else the type's current model."""
    out = {}
    for n in nodes:
        if not n["entity_type"] or (n["root"], n["entity_type"]) in out:
            continue
        tid, basis, ids = n["entity_type"], "current", [m.id for m in dm.current_models(n["entity_type"])]
        doc = results.get(n["root"]) if n["kind"] == "virtual" else None
        if doc and doc.get("selected_rung") and doc.get("card_ladders"):
            card = doc["card_ladders"][0]["card"]
            if dm.CARD_TYPE[card] == tid:
                ids, basis = list(dm.legacy_models(card, doc["selected_rung"])), "selected"
        out[(n["root"], tid)] = ({p for i in ids for p in dm.model(tid, i).parameters}, basis)
    return out


def owner(nodes: list[dict], start: dict, tid: str) -> str | None:
    """The typed node a value of type `tid` belongs to, from the node it sits on: that node when it is of the type, else the one node of
    the type in the smallest subtree around it that holds one (a joint's zero offset is its chain's; the 2F-85 tool's mass is its arm's,
    its TCP its gripper's); None when that subtree holds two or more (the value cannot say whose) or the tree holds none (a component that is
    not a node: an assembly's arm, a depth camera's colour stream). WHY per instance (the v3 audit, finding 4): keyed by the deployment and
    the type, one measured servo hid the rows of every unmeasured servo beside it."""
    by_id = {n["id"]: n for n in nodes if n["root"] == start["root"]}
    mine = list(by_id.values())
    at = start
    while at is not None:
        if at["entity_type"] == tid:
            return at["id"]
        typed = [x["id"] for x in subtree(mine, at["id"]) if x["entity_type"] == tid]
        if typed:
            return typed[0] if len(typed) == 1 else None
        at = by_id.get(at["parent"])
    return None


def parameter_table(nodes: list[dict], results: dict, routines: dict) -> dict:
    by_sysid = {(n["root"], n["sysid_id"]): n for n in nodes if n["sysid_id"]}
    key_node = {(ex, key): by_sysid[(ex, row["id"])] for ex, doc in results.items() for row in doc["tree"] for key in row["parameters"]}
    winning = _winning(nodes, results)
    rows, bound = [], set()  # bound: (owner node, type, parameter), per instance
    columns: dict[str, dict] = {}
    entries = {(p["example"], p["key"]): p for p in routines.get("parameters", []) if p["example"] in results}

    def base(node: dict, tid: str, name: str) -> dict:
        spec = dm.parameter(tid, name)
        params, basis = winning.get((node["root"], tid), (set(), "current"))
        return {"deployment": node["root"], "node": node["id"], "entity_type": tid, "parameter": name, "family": spec.family,
                "introduced_in": spec.introduced_in, "unit": spec.unit, "winning": name in params, "winning_basis": basis}

    def add_columns(row: dict, entry: dict, tid: str) -> None:
        """One column group per (routine, model) the ladder graded this value with, at the oracle's own noise."""
        for m in entry.get("models", []):
            lv = m["levels"].get(LEVEL)
            if lv is None:
                continue
            fam = row["family"]
            mid = (next(i for i in dm.legacy_models(entry["card"], m["rung"]) if dm.model(tid, i).family == fam) if m.get("rung")
                   else dm.fitted_model(m["routine"], tid, fam))
            cid = f"{m['routine']}:{mid}"
            col = columns.setdefault(cid, {"id": cid, "routine": m["routine"], "routine_title": reg.routine(m["routine"]).title, "model": mid,
                                           "entity_type": tid, "family": fam, "fit": m["fit"], "label": f"{m['routine']} · {mid}",
                                           "properties": [f"{x}@{cid}" for x in RESULT_PROPERTIES]})
            if col["entity_type"] != tid:
                raise ValueError(f"result column {cid} would hold two types' values ({col['entity_type']}, {tid})")
            rec = lv.get("recovered") or {}
            lo, hi = rec.get("ci95") or (None, None)
            row.update({f"recovered@{cid}": rec.get("mean"), f"ci95_lo@{cid}": lo, f"ci95_hi@{cid}": hi, f"interval@{cid}": rec.get("interval"),
                        f"error@{cid}": lv.get("error"), f"tolerance@{cid}": (entry.get("tolerance") or {}).get("value"),
                        f"error_over_tolerance@{cid}": lv.get("error_over_tolerance"), f"within@{cid}": lv.get("within_tolerance")})

    by_id = {n["id"]: n for n in nodes}
    for ex, doc in results.items():
        done = set()
        for p in doc["parameters"]:
            tid, name = dm.legacy_parameter(p["card"], _v2_name(p["card_parameter"]))
            node = key_node[(ex, p["key"])]
            mine = owner(nodes, node, tid)
            tol = p.get("tolerance") or {}
            ci = p.get("ci95") or (None, None)
            row = {"id": f"{ex}/{p['key']}", **base(node, tid, name), "owner": mine, "key": p["key"], "element": p.get("component"), "unit": p["unit"],
                   "true": p.get("true"), "nominal": p.get("nominal"), "nominal_source": p.get("nominal_source"), "tolerance_kind": tol.get("kind"),
                   "tolerance": tol.get("value"), "recovered": p.get("recovered"), "ci95_lo": ci[0], "ci95_hi": ci[1], "pass": p.get("pass"),
                   "method": p.get("method")}
            if (ex, p["key"]) in entries:
                add_columns(row, entries[(ex, p["key"])], tid)
            rows.append(row)
            if mine:
                bound.add((mine, tid, name))
            done.add(p["key"])
        # WHY rows the example does not have: the noise ladder grades a few values only it hides (CAN 11's sliding Coulomb level and the
        # wear rate, the cell's camera knock); each sits on the deployment's one node of its type, else on the deployment itself
        for (ex2, key), entry in entries.items():
            if ex2 != ex or key in done:
                continue
            tid, name = dm.legacy_parameter(entry["card"], _v2_name(entry["card_parameter"]))
            mine = owner(nodes, by_id[ex], tid)
            node = by_id[mine] if mine else by_id[ex]
            tol = entry.get("tolerance") or {}
            row = {"id": f"{ex}/{key}", **base(node, tid, name), "owner": mine, "key": key, "element": None, "unit": entry["unit"], "true": entry.get("true"),
                   "nominal": entry.get("nominal"), "nominal_source": "graded by the noise ladder only (sysid/results/noise_ladder.json)",
                   "tolerance_kind": tol.get("kind"), "tolerance": tol.get("value"), "recovered": None, "ci95_lo": None, "ci95_hi": None,
                   "pass": None, "method": None}
            add_columns(row, entry, tid)
            rows.append(row)
            if mine:
                bound.add((mine, tid, name))
    for n in nodes:
        if not n["entity_type"]:
            continue
        for spec in dm.TYPES[n["entity_type"]].parameters:
            if (n["id"], n["entity_type"], spec.name) in bound:
                continue
            # WHY nominal null and the card's value apart: a v2 card's nominal is the instance it was written around (the servo card's
            # are CAN 11's), so on any other part it would read as that part's own
            rows.append({"id": f"{n['id']}#{spec.name}", **base(n, n["entity_type"], spec.name), "owner": n["id"], "key": None, "element": None, "true": None,
                         "nominal": None, "type_nominal": spec.nominal if isinstance(spec.nominal, (int, float)) else None,
                         "nominal_source": f"not recorded for this part; type_nominal is the type card's ({spec.source})",
                         "tolerance_kind": None, "tolerance": None, "recovered": None, "ci95_lo": None, "ci95_hi": None, "pass": None, "method": None})
    order = list(columns)
    for r in rows:
        scored = [(c, r.get(f"error_over_tolerance@{c}")) for c in order if r.get(f"error_over_tolerance@{c}") is not None]
        r["best"] = min(scored, key=lambda cv: abs(cv[1]))[0] if scored else None
        r["has_results"] = r.get("recovered") is not None or any(r.get(f"recovered@{c}") is not None for c in order)
    return {"name": "parameters", "title": "Every parameter: true, nominal and recovered, one column group per routine and model",
            "contract": dm.SCHEMA, "level": LEVEL, "schema": {"fields": fields_of(rows)},
            "source": "type_cards/instances.py: sysid/results/<example>.json (the oracle's own values), sysid/results/calibration_routines.json "
                      f"(one column group per routine and model at {LEVEL}), every typed node's type parameters (type_cards/domain_v3.json)",
            "result_columns": list(columns.values()), "column_groups": {c["label"]: c["properties"] for c in columns.values()},
            "presets": {
                "all": {"filter": None, "columns": "every column group", "what": "every parameter of every typed part of every deployment, with or without a value"},
                "winning model": {"filter": "winning == true", "columns": "every column group",
                                  "what": "the parameters of the winning model (winning_basis: the selection rule's pick, else the type's current model)"},
                "with results": {"filter": "has_results == true", "columns": "every column group", "what": "only parameters some routine produced a value for"},
                "errors only": {"filter": "has_results == true", "columns": "error_over_tolerance@* (and error@*)", "color_by": "best",
                                "what": "the errors side by side, each row coloured by the column whose error over tolerance is least"},
            },
            "rows": rows}


# --- the site's projections ----------------------------------------------------------------------------------------------------------

def _dump(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


def write(data: Path, out: Path | None = None, schedules: Path | None = None) -> dict:
    """<data>/domain/: deployments.json, parameters.json, model_labels.json, selections/<deployment>.json (the presets, computed),
    coverage_cells/<deployment>.json (the browser's coverage table), metric_values/<deployment>.json (the browser's metrics table) and
    reports/<id>.json (the frozen reports, copied). Returns counts."""
    from . import report as rep  # noqa: PLC0415
    from . import selection as sel  # noqa: PLC0415

    data = Path(data)
    out = Path(out) if out else data / "domain"
    out.mkdir(parents=True, exist_ok=True)
    results = load_results()
    nodes = virtual_nodes(results) + physical_nodes(data)
    _dump(out / "deployments.json", deployments_dataset(nodes))
    routines = json.loads((RESULTS / "calibration_routines.json").read_text(encoding="utf-8"))
    table = parameter_table(nodes, results, routines)
    _dump(out / "parameters.json", table)
    _dump(out / "model_labels.json", model_labels_dataset())
    counts = {"nodes": len(nodes), "deployments": sum(1 for n in nodes if n["parent"] is None), "parameter_rows": len(table["rows"]),
              "result_columns": len(table["result_columns"]), "selections": {}}
    for dep in [n["id"] for n in nodes if n["parent"] is None and n["kind"] == "physical"]:
        tables = sel.load_tables(data, dep, schedules, nodes=[n for n in nodes if n["root"] == dep])
        if not tables.runs:
            continue
        computed = {}
        for name, ids in sel.presets(tables.runs).items():
            result = sel.compute(ids, tables, name=name)
            result.pop("run_ids")
            computed[name] = result
        _dump(out / "selections" / f"{dep}.json", {"schema": sel.SCHEMA, "deployment": dep, "rule": "selection.presets: every run, each split, "
                                                    "each station, each day; run_ids_sha256 names the ids", "presets": computed})
        _dump(out / "coverage_cells" / f"{dep}.json", sel.coverage_cells(tables))
        # WHY beside coverage_cells (2026-11-07): the browser's metrics rule reads one run x metric table, as its coverage rule reads cells
        values = sel.metric_values(tables)
        _dump(out / "metric_values" / f"{dep}.json", values)
        counts["selections"][dep] = len(computed)
        counts.setdefault("metric_values", {})[dep] = len(values["rows"])
    (out / "reports").mkdir(exist_ok=True)
    for path in sorted(rep.REPORTS_DIR.glob("*.json")):
        shutil.copyfile(path, out / "reports" / path.name)
    counts["reports"] = len(list((out / "reports").glob("*.json")))
    return counts
