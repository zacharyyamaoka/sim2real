"""The rows data-ui's gate views read (CONTRACT §35, PEP 0010 P5), written beside the app's tables in the site's data folder.

data-ui computes no gate, metric or verdict: the producers write them as rows. These are the app's own rows reshaped for the
stock views, never a new number:

    gates.json          + gate_id (T1), rank (RobotDx's: pass 0, warn and partial 1, not run 2, fail 4; the roll-up's Max),
                          passes (1 when the cell passes, else 0; the roll-up's Sum and Count), why_url (the cell's why, or the
                          station's gates when it passes) for the matrix's peek
    run_gates.json      + started (the run's, from runs.json), titled by its record, for the run checks' peek
    components.json     the deployment's tree (site/deploy_tree.py's tree.json: the rack, its adapters, its stations) as the
                        roll-up's nodes; `worst`, `passing` and `cells` filled by data-ui
    gate_history.json   per bam_rack_twin acceptance file in the archive (all eight stations each): cells passing, rack and
                        per station, against every cell (the KPI cards' trend and target)
    coverage_cells.json the coverage paths on each station's own (q, qd) grid, 24 x 24 over the range it ran: one row per
                        run and cell, so voxels count runs per cell (value: runs); a whole rack past ~200 runs, where 1/n
                        opacity stops reading (CONTRACT §32)

WHY in the site build: the app's producer (tools/build_app.py) writes the tables both the app and the site read; these
columns serve only the site's views, and each is a lookup or a join of what the producer wrote (the history reads the same
acceptance files the producer picks the newest of).
"""

from __future__ import annotations

import json
import math
import os
import pathlib
from collections import defaultdict

ARCHIVE = pathlib.Path(os.environ.get("SIM2REAL_ARCHIVE") or "/archive/datasets/bam_rig")
# RobotDx's ranks (data-ui STATUS_ORDER, CONTRACT §35): ok 0 < warn 1 < unknown and not run 2 < stale 3 < error and fail 4
RANK = {"pass": 0, "ok": 0, "warn": 1, "warning": 1, "partial": 1, "unknown": 2, "not_run": 2, "not run": 2, "stale": 3, "error": 4, "fail": 4}
RANK_WORDS = {"0": "pass", "1": "warn", "2": "not run", "3": "stale", "4": "fail"}
GRID = 24  # cells per axis of a station's (q, qd) coverage grid


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def _dump(path: pathlib.Path, doc: dict) -> None:
    if path.is_symlink():
        path.unlink()
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


def gate_rows(folder: pathlib.Path, why_url) -> list[dict]:
    path = folder / "gates.json"
    doc = _load(path)
    for row in doc["rows"]:
        row["gate_id"] = row["gate"].split()[0]
        row["rank"] = RANK.get(row["verdict"], 0)
        row["passes"] = 1 if row["verdict"] == "pass" else 0
        row["why_url"] = why_url(row)
    props = doc.setdefault("properties", {})
    props["gate_id"] = {"label": "Gate", "type": "text"}
    props["rank"] = {"label": "Rank", "type": "number", "labels": RANK_WORDS}
    props["passes"] = {"label": "Passes", "type": "number"}
    props["why_url"] = {"label": "Why", "type": "text", "display": "link"}
    props["verdict"] = {**props.get("verdict", {}), "label": "Verdict", "labels": {"not_run": "not run"}}
    doc["titleProperty"] = "gate"  # the peek's heading: "T3 torque", not the first column
    _dump(path, doc)
    return doc["rows"]


def run_gate_rows(folder: pathlib.Path, runs: list[dict]) -> None:
    started = {r["run"]: r["started"] for r in runs}
    path = folder / "run_gates.json"
    doc = _load(path)
    for row in doc["rows"]:
        row["started"] = started.get(row.get("run_slug") or row.get("run"))
    doc.setdefault("properties", {})["started"] = {"label": "Started", "type": "date"}
    doc["titleProperty"] = "record"  # the peek's heading: the run and what was measured
    doc["properties"]["evidence"] = {**doc["properties"].get("evidence", {}), "label": "Evidence", "display": "link"}
    _dump(path, doc)


def components(folder: pathlib.Path, dep_row: dict, devices: list[dict]) -> int:
    """The roll-up's nodes: the deployment's tree (tree.json, site/deploy_tree.py), a station's id its device (the key gates.json
    links on), every other node its path id. WHY the tree and not the plates (Zach, PROJECT - Sim2Real, Nov 5 2026: each deployment's
    tree is like RobotDx's entity tree, host -> adapter -> board): one tree per deployment, the rail's and the roll-up's."""
    tree = _load(folder / "tree.json")["rows"]
    key = {n["id"]: (n["device"] or n["id"]) for n in tree}
    station = {d["device"]: (d.get("station") or "").split(",", 1)[-1].strip() for d in devices}
    rows = [{"id": key[n["id"]], "label": f'{n["label"]} · {station[n["device"]]}' if n.get("device") in station and station[n["device"]] else n["label"],
             "parent": key.get(n["parent"]) if n.get("parent") else None, "kind": n["kind"], "board": n.get("board"), "card": n.get("card"),
             "worst": None, "passing": None, "cells": None} for n in tree]
    _dump(folder / "components.json", {
        "title": f"The tree: the deployment, its adapters and its stations · {dep_row['title']}",
        "source": "tree.json (site/deploy_tree.py, from the bam_rack_twin record's adapter_serial per board); devices.json (station text)",
        "schema": {"fields": [{"name": "id", "type": "string"}, {"name": "label", "type": "string"}, {"name": "parent", "type": "string"},
                              {"name": "kind", "type": "string"}, {"name": "board", "type": "string"}, {"name": "card", "type": "string"},
                              {"name": "worst", "type": "integer", "display": "status", "labels": RANK_WORDS},
                              {"name": "passing", "type": "integer", "description": "gate cells passing under the node"},
                              {"name": "cells", "type": "integer", "description": "every gate cell under the node"}]},
        "rows": rows})
    return len(rows)


def acceptance_files(archive: pathlib.Path = ARCHIVE) -> list[tuple[pathlib.Path, dict]]:
    """Every bam_rack_twin acceptance file under the archive's rack days, oldest first by its own generated_at."""
    found = []
    for path in archive.glob("rack_2026-*/analysis/acceptance*.json"):
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and str(doc.get("schema", "")).startswith("bam_rack_twin.acceptance/") and doc.get("generated_at"):
            found.append((path, doc))
    return sorted(found, key=lambda pd: pd[1]["generated_at"])


def gate_history(folder: pathlib.Path, dep_row: dict, archive: pathlib.Path = ARCHIVE) -> int:
    rows = []
    for path, doc in acceptance_files(archive):
        stations = doc.get("stations") or {}
        if len(stations) < 8:
            continue  # the matrix is eight stations; a partial file is not a reading of it
        cells = [(f"CAN {can}", g["status"]) for can, st in stations.items() for g in st["gates"]]
        base = {"dated": doc["generated_at"], "file": path.name, "path": str(path)}
        rows.append({**base, "scope": "rack", "device": dep_row["title"], "passing": sum(s == "pass" for _d, s in cells), "cells": len(cells)})
        per = defaultdict(list)
        for device, status in cells:
            per[device].append(status)
        for device, statuses in per.items():
            rows.append({**base, "scope": "station", "device": device, "passing": sum(s == "pass" for s in statuses), "cells": len(statuses)})
    _dump(folder / "gate_history.json", {
        "title": f"Gate cells passing, per acceptance file · {dep_row['title']}",
        "source": f"bam_rack_twin acceptance files under {archive}/rack_*/analysis/ (schema bam_rack_twin.acceptance/1), oldest first",
        "schema": {"fields": [{"name": "dated", "type": "datetime"}, {"name": "file", "type": "string"}, {"name": "path", "type": "string"},
                              {"name": "scope", "type": "string"}, {"name": "device", "type": "string"},
                              {"name": "passing", "type": "integer", "description": "gate cells that pass"},
                              {"name": "cells", "type": "integer", "description": "every gate cell: the target"}]},
        "rows": rows})
    return len(rows)


def coverage_cells(folder: pathlib.Path) -> int:
    """Each station's coverage paths on its own GRID x GRID (q, qd) grid: cell = floor((v - min) / (max - min) * GRID)."""
    src = folder / "coverage.json"
    if not src.exists():
        return 0
    rows = [r for r in _load(src)["rows"] if r.get("layer") == "path" and r.get("q_deg") is not None and r.get("qd_deg_s") is not None]
    span = {}
    for r in rows:
        lo_q, hi_q, lo_v, hi_v = span.get(r["device"], (math.inf, -math.inf, math.inf, -math.inf))
        span[r["device"]] = (min(lo_q, r["q_deg"]), max(hi_q, r["q_deg"]), min(lo_v, r["qd_deg_s"]), max(hi_v, r["qd_deg_s"]))
    cell = lambda v, lo, hi: min(GRID - 1, int((v - lo) / (hi - lo) * GRID)) if hi > lo else 0  # noqa: E731
    out = {}
    for r in rows:
        lo_q, hi_q, lo_v, hi_v = span[r["device"]]
        key = (r["device"], r["run"], cell(r["q_deg"], lo_q, hi_q), cell(r["qd_deg_s"], lo_v, hi_v))
        out[key] = out.get(key, 0) + (r.get("w") or 1)
    cells = [{"device": d, "run": run, "q_cell": i + 0.5, "qd_cell": j + 0.5, "z": 0.5, "w": w,
              "q_lo": round(span[d][0], 3), "q_hi": round(span[d][1], 3), "qd_lo": round(span[d][2], 3), "qd_hi": round(span[d][3], 3)}
             for (d, run, i, j), w in sorted(out.items())]
    _dump(folder / "coverage_cells.json", {
        "title": "Coverage cells: each station's (q, qd) on its own 24 x 24 grid, one row per run and cell",
        "source": "coverage.json (tools/build_app.py), gridded by site/overlays.py: q_cell, qd_cell in cells of 1/24 of the range the station ran",
        "schema": {"fields": [{"name": "device", "type": "string"}, {"name": "run", "type": "string"},
                              {"name": "q_cell", "type": "number", "description": "q, in 24ths of the station's range (q_lo..q_hi)"},
                              {"name": "qd_cell", "type": "number", "description": "qd, in 24ths of the station's range (qd_lo..qd_hi)"},
                              {"name": "z", "type": "number"}, {"name": "w", "type": "integer", "description": "grid samples in the cell"},
                              {"name": "q_lo", "type": "number", "unit": "deg"}, {"name": "q_hi", "type": "number", "unit": "deg"},
                              {"name": "qd_lo", "type": "number", "unit": "deg/s"}, {"name": "qd_hi", "type": "number", "unit": "deg/s"}]},
        "rows": cells})
    return len(cells)


def write(data: pathlib.Path, why_url, archive: pathlib.Path = ARCHIVE) -> dict:
    """Every overlay table for every deployment folder under data (site/build.py's OUT/data). Returns counts."""
    counts = {}
    deployments = _load(data / "deployments.json")["rows"]
    for dep in deployments:
        folder = data / dep["id"]
        runs = _load(folder / "runs.json")["rows"]
        devices = _load(folder / "devices.json")["rows"]
        counts[dep["id"]] = {"gates": len(gate_rows(folder, lambda row, d=dep: why_url(d["id"], row))),
                             "components": components(folder, dep, devices), "history": gate_history(folder, dep, archive),
                             "coverage_cells": coverage_cells(folder)}
        run_gate_rows(folder, runs)
    return counts
