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
import sys
from pathlib import Path
from typing import Any

from . import PACKAGE, REPO, RESULTS_DIR, cards

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
        where = cards.place(example, key)
        rows.append({"key": key, "component": component, "name": name, "unit": nominal.unit,
                     "nominal": nominal.value, "nominal_source": nominal.source, "true": true,
                     "recovered": _num(fit["value"]), "ci95": [_num(v) for v in fit["ci95"]] if fit.get("ci95") else None,
                     "rung": where["rung"], "card": where["card"], "card_parameter": where["parameter"], "on_card": where["on_card"],
                     "fit_step": fit.get("rung"), "method": fit.get("method", ""),
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


# What computes a result: sysid's code, the examples' descriptions and worlds, and the type cards it reads. Not sysid/results.
# WHY: results/ is what a run writes, not what computes it; counting it stamped every example after the first in one
# `all --write` run "+dirty" (every result committed on 2026-11-05 read 782bd5e+dirty).
COMPUTES_RESULTS = ("sysid", "type_cards", ":(exclude)sysid/results")


def code_version(repo: Path = REPO) -> str:
    try:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", *COMPUTES_RESULTS],
                               capture_output=True, text=True, check=True).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def checkout_version(repo: Path, roots) -> dict:
    """A checkout imported in place, as the code under `roots` stands: the branch checked out, the last commit that touched any
    root (an unrelated commit elsewhere in the repo leaves it alone), and whether a root has uncommitted changes."""
    paths = [str(Path(r).resolve().relative_to(Path(repo).resolve())) for r in roots]
    git = lambda *args: subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()  # noqa: E731
    try:
        commit, date = (git("log", "-1", "--format=%h %cI", "--", *paths).split(" ", 1) + [""])[:2]
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        return {"branch": "detached" if branch == "HEAD" else branch, "commit": commit, "date": date,
                "dirty": bool(git("status", "--porcelain", "--", *paths))}
    except (OSError, subprocess.CalledProcessError):
        return {"branch": "unknown", "commit": "unknown", "date": "", "dirty": False}


def external_checkouts(paths, exclude: Path = REPO) -> list[dict]:
    """Every git checkout outside `exclude` that `paths` (import roots, model files) live in, each stamped by checkout_version over
    the paths inside it (a file counts with its folder: a model's meshes sit beside it). Paths in `exclude`, in a virtualenv, missing,
    or in no checkout at all are not imports to stamp."""
    by_repo: dict[Path, set[Path]] = {}
    toplevel: dict[Path, Path | None] = {}
    skip = Path(exclude).resolve()
    for raw in paths:
        path = Path(raw).resolve()
        if not path.exists() or path.is_relative_to(skip) or {".venv", "site-packages", "dist-packages"} & set(path.parts):
            continue
        folder = path if path.is_dir() else path.parent
        if folder not in toplevel:
            try:
                out = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
                toplevel[folder] = Path(out).resolve()
            except (OSError, subprocess.CalledProcessError):
                toplevel[folder] = None
        if toplevel[folder] is not None:
            by_repo.setdefault(toplevel[folder], set()).add(folder)
    return [{"repo": str(top), "name": top.name, **checkout_version(top, sorted(used)), "paths": len(used)} for top, used in sorted(by_repo.items())]


def description_paths(example: str) -> list[Path]:
    """Every file an example's description names under a "path" key (its model, its parts and their attachments, its records),
    resolved the way sysid.describe resolves them."""
    from .describe import resolve_path  # noqa: PLC0415

    found: list[Path] = []

    def walk(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif key == "path" and isinstance(node, str):
            found.append(resolve_path(node))

    walk(json.loads((PACKAGE / "examples" / example / "description.json").read_text()))
    return list(dict.fromkeys(found))


def loaded_files() -> list[Path]:
    """The source file of every module loaded in this process: what the run could have executed, never less (sys.path alone named
    checkouts nothing imported: the rack twin's venv puts io-diagnostics on every process's path)."""
    return [Path(f) for m in list(sys.modules.values()) if isinstance(f := getattr(m, "__file__", None), str)]


def provenance(example: str) -> dict:
    """What a result was computed from: this repo's code (code_version), and every checkout outside it that a module loaded in this
    process or a file the example's description names came from (external_checkouts). WHY: bam_ws, io-diagnostics, robot_msgs and
    Menagerie are used in place, never vendored (docs/decision-sysid-oracle-2026-11-05.md), so this stamp is the only record of
    which of their code made a number."""
    return {"code": code_version(), "imports": external_checkouts([*loaded_files(), *description_paths(example)])}


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
