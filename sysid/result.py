"""The result document an example writes (schema sysid.result/1): what the site's cards and the report read, and the test checks.

    parameters  one row per identified value: key, component, name, unit, nominal (+ source), true (world.json), recovered, ci95,
                rung, the tolerance it is held to and whether it passes it
    metrics     held-out fidelity before (the description's nominal model) and after (the fitted one), with the factor the ruler
                asks for and whether it is met
    rungs       the type's ladder as scored: each rung's parameters and its held-out ratio to the floor (the selection rule's input)
    schedule    the train and held-out plan and its coverage (the type card's function where one applies)
    tree        the typed components (type card or adapter type, its source)
"""

from __future__ import annotations

import fnmatch
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from . import PACKAGE, REPO, RESULTS_DIR

SCHEMA = "sysid.result/1"
ACCEPTANCE = json.loads((PACKAGE / "acceptance.json").read_text(encoding="utf-8"))


def tolerance(example: str, key: str) -> tuple[str, float] | None:
    for pattern, rule in ACCEPTANCE["examples"].get(example, {}).get("parameters", {}).items():
        if fnmatch.fnmatchcase(key, pattern):
            return rule[0], float(rule[1])
    return None


def passes(value, truth, rule) -> bool | None:
    if rule is None or truth is None:
        return None
    if value is None or not math.isfinite(float(value)):
        return False
    kind, tol = rule
    return abs(float(value) - float(truth)) <= (tol if kind == "abs" else tol * abs(float(truth)))


def parameter_rows(example: str, description, truth: dict, recovered: dict[str, dict]) -> list[dict]:
    """`recovered`: {key: {"value", "ci95", "rung", "method"}} for every key the fit identifies."""
    rows = []
    for key, nominal in description.nominal.items():
        fit = recovered.get(key)
        if fit is None:
            continue
        rule = tolerance(example, key)
        true = truth.get(key)
        component, _, name = key.partition(".")
        rows.append({"key": key, "component": component, "name": name, "unit": nominal.unit,
                     "nominal": nominal.value, "nominal_source": nominal.source, "true": true,
                     "recovered": _num(fit["value"]), "ci95": [_num(v) for v in fit["ci95"]] if fit.get("ci95") else None,
                     "rung": fit.get("rung"), "method": fit.get("method", ""),
                     "tolerance": None if rule is None else {"kind": rule[0], "value": rule[1]},
                     "pass": passes(fit["value"], true, rule), "nominal_pass": passes(nominal.value, true, rule)})
    return rows


def metric(example: str, metric_id: str, title: str, unit: str, before: float, after: float, *, split: str = "held_out",
           before_model: str = "nominal", after_model: str = "", note: str = "", gated: bool | None = None) -> dict:
    need = ACCEPTANCE["examples"].get(example, {}).get("metrics", {}).get(metric_id)
    factor = before / after if after else math.inf
    return {"id": metric_id, "title": title, "unit": unit, "split": split, "before": _num(before), "after": _num(after),
            "factor": _num(factor), "factor_needed": need, "gated": need is not None if gated is None else gated,
            "pass": None if need is None else factor >= need, "before_model": before_model, "after_model": after_model, "note": note}


def verdict(doc: dict) -> dict:
    params = [r for r in doc["parameters"] if r["pass"] is not None]
    metrics = [m for m in doc["metrics"] if m["pass"] is not None]
    failing = [r["key"] for r in params if not r["pass"]] + [m["id"] for m in metrics if not m["pass"]]
    return {"parameters_pass": sum(r["pass"] for r in params), "parameters": len(params),
            "metrics_pass": sum(m["pass"] for m in metrics), "metrics": len(metrics), "failing": failing,
            "status": "pass" if not failing else "fail"}


def code_version() -> str:
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "sysid"], capture_output=True, text=True, check=True).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _num(value):
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def plain(value: Any):
    """JSON-able: numpy scalars and arrays, tuples, Paths."""
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        np = None
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if np is not None and isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"not JSON-able: {type(value).__name__}")


def write(doc: dict, name: str | None = None) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name or doc['example']}.json"
    path.write_text(json.dumps(doc, indent=1, default=plain, allow_nan=False) + "\n", encoding="utf-8")
    return path
