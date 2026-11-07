"""The calibration procedure comparison table: type_cards' procedure records joined with the committed noise ladder.

One row per procedure (type_cards/calibration.py PROCEDURES, in that order): where it runs, its wall and operator time, its equipment and
their cost (every number with its source or "estimate"), the parameters it covers, its excitation, coverage and repeats, its code, and its
oracle verdict level by level from sysid/results/noise_ladder.json (or why it has none). A pure function of those two inputs, so
sysid/tests/test_noise_ladder.py recomputes it and holds the committed sysid/results/calibration_procedures.json to it. The shape is
documented in type_cards/CONTRACT.md ("Calibration procedures"); the site reads the JSON, never this module.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid procedures --write
"""

from __future__ import annotations

import dataclasses

SCHEMA = "sysid.calibration_procedures/1"
SUMMARY_LEVELS = ("1x", "3x")  # the table's headline columns (the coordinator, 2026-11-07: recovery accuracy at 1x and 3x noise)
COLUMNS = (
    ("procedure", "the type_cards procedure id"),
    ("setting", "bench | deployed | both"),
    ("wall_time", "s, the whole procedure (value, unit, source)"),
    ("operator_time", "s, a person's hands-on share (value, unit, source)"),
    ("equipment_cost", "USD, the sum of its equipment (value, unit, source)"),
    ("equipment", "what it needs beyond the robot's own sensors"),
    ("recovery", "per summary level: the worst |error| / tolerance over every check and parameter, and whether all pass"),
    ("parameters_covered", "card parameters it identifies (identifies[].parameters, counted)"),
)


def _plain(obj):
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj


def level_key(row: dict) -> str:
    return row["level"] if row["variant"] is None else f"{row['level']}+{row['variant']}"


def level_cell(row: dict) -> dict:
    params = row["parameters"]
    return {"pass": row["pass"], "usable": row["usable"], "worst_error_over_tolerance": row["worst_error_over_tolerance"],
            "within_tolerance": f"{sum(p['within_tolerance'] for p in params)}/{len(params)}", "parameters": len(params),
            "failing": [p["key"] for p in params if not p["pass"]], "held_out": row["held_out"]}


def verdict(levels: dict) -> str:
    """One line: the levels it passes, the first it fails and its worst error there in tolerances."""
    main = [k for k in levels if "+" not in k]
    passed = [k for k in main if levels[k]["pass"]]
    failed = [k for k in main if not levels[k]["pass"]]
    variants = [k for k in levels if "+" in k]
    parts = []
    if passed:
        parts.append("passes " + ", ".join(passed))
    if failed:
        worst = levels[failed[0]]["worst_error_over_tolerance"]
        parts.append(f"fails {', '.join(failed)}" + (f" (worst {worst:.3g}x its tolerance at {failed[0]})" if worst is not None else " (values missing)"))
    for k in variants:
        parts.append(f"{k.split('+', 1)[1]}: {'pass' if levels[k]['pass'] else 'FAIL'}")
    return "; ".join(parts) if parts else "not run"


def recovery(checks: list[dict]) -> dict:
    """The headline cells: per summary level, the worst |error| / tolerance over all the procedure's checks, and whether all pass."""
    out = {}
    for level in SUMMARY_LEVELS:
        cells = [c["levels"][level] for c in checks if level in c["levels"]]
        if not cells:
            continue
        worsts = [cell["worst_error_over_tolerance"] for cell in cells]
        out[level] = {"pass": all(cell["pass"] for cell in cells), "usable": all(cell["usable"] for cell in cells),
                      "worst_error_over_tolerance": None if any(w is None for w in worsts) else max(worsts),
                      "parameters": sum(cell["parameters"] for cell in cells)}
    return out


def table(ladder_doc: dict) -> dict:
    from type_cards import registry as reg  # noqa: PLC0415

    checks = {c["id"]: c for c in ladder_doc["checks"]}
    rows = []
    for p in reg.PROCEDURES:
        graded = []
        for cid in p.oracle:
            c = checks.get(cid)
            if c is None:
                graded.append({"id": cid, "levels": {}, "verdict": "not run"})
                continue
            levels = {level_key(r): level_cell(r) for r in c["rows"]}
            graded.append({"id": cid, "example": c["example"], "owner": c["owner"], "structure": c["structure"], "parameters": c["parameters"],
                           "unclaimed": c["unclaimed"], "not_at": c["not_at"], "realism": c["realism"], "levels": levels, "verdict": verdict(levels)})
        rows.append({
            "procedure": p.id, "title": p.title, "package": p.package, "kind": p.kind, "setting": p.setting, "status": p.status,
            "wall_time": _plain(p.wall_time), "operator_time": _plain(p.operator_time),
            "equipment": [{"id": e, "title": reg.EQUIPMENT[e].title, "cost": _plain(reg.EQUIPMENT[e].cost)} for e in p.equipment],
            "equipment_cost": _plain(reg.equipment_cost(p)),
            "identifies": [{"card": i.card, "rung": i.rung, "parameters": list(i.parameters)} for i in p.identifies],
            "parameters_covered": sum(len(i.parameters) for i in p.identifies),
            "excitation": p.excitation, "coverage": p.coverage, "repeats": p.repeats, "how": p.how, "tests": list(p.tests),
            "code": [_plain(h) for h in p.code],
            "oracle": {"status": "checked" if p.oracle else "not checked", "checks": graded, "note": p.oracle_note},
            "recovery": recovery([g for g in graded if g.get("levels")]),
            "alternatives": list(p.alternatives), "references": [r.title for r in p.references], "note": p.note})
    return {"schema": SCHEMA,
            "generated_from": {"records": "type_cards/calibration.py PROCEDURES and EQUIPMENT", "ladder": "sysid/results/noise_ladder.json",
                               "ruler": ladder_doc["ruler"]},
            "levels": [level["id"] for level in ladder_doc["levels"]], "variants": list(ladder_doc["variants"]),
            "summary_levels": list(SUMMARY_LEVELS), "columns": [{"key": k, "what": w} for k, w in COLUMNS], "rows": rows}
