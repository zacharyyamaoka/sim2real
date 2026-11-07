"""The Calibration Routines table: type_cards' routine records joined with the committed noise ladder, both ways round.

Routine -> parameters: one row per routine (type_cards/calibration.py ROUTINES, in that order): where it runs, its wall and operator time,
its equipment and their cost (every number with its source or "estimate"), the card parameters it identifies, its excitation, coverage and
repeats, its code, and its oracle verdict level by level from sysid/results/noise_ladder.json (or why it has none).

Parameter -> routines: one entry per hidden parameter the ladder grades (per example and key), placed on its type card (card, rung, card
parameter), with every routine the type cards say can identify that card parameter, and one group per model that recovered it (a routine's
fit, or each rung of CAN 11's regression): per level its recovered value (the mean) and 95 % interval, its error and error in tolerances,
beside the parameter's true and nominal values and its tolerance. A site can draw a recovered / error column group per model from it.

A pure function of those two inputs, so sysid/tests/test_noise_ladder.py recomputes it and holds the committed
sysid/results/calibration_routines.json to it. The shape is documented in type_cards/CONTRACT.md ("Calibration routines"); the site reads
the JSON, never this module.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid routines --write
"""

from __future__ import annotations

import dataclasses

SCHEMA = "sysid.calibration_routines/1"
SUMMARY_LEVELS = ("1x", "3x")  # the table's headline columns (the coordinator, 2026-11-07: recovery accuracy at 1x and 3x noise)
# WHY recovery holds every level and not the headline two (the v3 audit, 2026-11-07, finding 5): 0x is the bias a routine keeps
# with no noise, 10x where it breaks; a routines page that showed 1x and 3x only hid both, and a level a check skips
COLUMNS = (
    ("routine", "the type_cards routine id"),
    ("setting", "bench | deployed | both"),
    ("wall_time", "s, the whole routine (value, unit, source)"),
    ("operator_time", "s, a person's hands-on share (value, unit, source)"),
    ("equipment_cost", "USD, the sum of its equipment (value, unit, source)"),
    ("equipment", "what it needs beyond the robot's own sensors"),
    ("recovery", "per level the ladder runs (0x 1x 3x 10x): over the checks that ran there, the worst |error| / tolerance over the recovered "
                 "parameters, all pass, the missing and failing ones; the checks not run there and why"),
    ("parameters_covered", "card parameters it identifies (identifies[].parameters, counted)"),
)


def _plain(obj):
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj


def level_key(row: dict) -> str:
    return row["level"] if row["variant"] is None else f"{row['level']}+{row['variant']}"


def level_cell(row: dict) -> dict:
    """A level's cell. WHY the worst over the recovered parameters and `missing` apart (the ladder row's own worst is None when any
    claimed value is missing): a routine that recovers two of four joints still says how close the two came."""
    params = row["parameters"]
    recovered = [p["error_over_tolerance"] for p in params if p["error_over_tolerance"] is not None]
    return {"pass": row["pass"], "usable": row["usable"], "worst_error_over_tolerance": max(recovered) if recovered else None,
            "missing": [p["key"] for p in params if p["recovered"] is None],
            "within_tolerance": f"{sum(p['within_tolerance'] for p in params)}/{len(params)}", "parameters": len(params),
            "failing": [p["key"] for p in params if not p["pass"]], "held_out": row["held_out"], "notes": row.get("notes", [])}


def verdict(levels: dict) -> str:
    """One line: the levels it passes, the first it fails and its worst error there in tolerances."""
    main = [k for k in levels if "+" not in k]
    passed = [k for k in main if levels[k]["pass"]]
    failed = [k for k in main if not levels[k]["pass"]]
    parts = []
    if passed:
        parts.append("passes " + ", ".join(passed))
    if failed:
        cell = levels[failed[0]]
        worst, missing = cell["worst_error_over_tolerance"], len(cell["missing"])
        detail = [f"worst {worst:.3g}x its tolerance" if worst is not None else "", f"{missing} of {cell['parameters']} not recovered" if missing else ""]
        parts.append(f"fails {', '.join(failed)}" + (f" ({'; '.join(d for d in detail if d)} at {failed[0]})" if any(detail) else ""))
    for k in levels:
        if "+" in k:
            parts.append(f"{k.split('+', 1)[1]}: {'pass' if levels[k]['pass'] else 'FAIL'}")
    return "; ".join(parts) if parts else "not run"


def recovery(checks: list[dict], levels) -> dict:
    """Per level the ladder runs, over the routine's checks that ran there: the worst |error| / tolerance, whether all pass (and are
    usable), the parameters missing and failing; with the checks that did not run there and the ruler's reason (not_at). A level no check
    ran is kept, pass null, so a reader sees the gap; a routine with no check has none ({}: not checked)."""
    out = {}
    if not checks:
        return out
    for level in levels:
        ran = [c for c in checks if level in c["levels"]]
        cells = [c["levels"][level] for c in ran]
        worsts = [cell["worst_error_over_tolerance"] for cell in cells if cell["worst_error_over_tolerance"] is not None]
        out[level] = {"pass": all(cell["pass"] for cell in cells) if cells else None, "usable": all(cell["usable"] for cell in cells) if cells else None,
                      "worst_error_over_tolerance": max(worsts) if worsts else None,
                      "missing": sum(len(cell["missing"]) for cell in cells), "failing": sum(len(cell["failing"]) for cell in cells),
                      "parameters": sum(cell["parameters"] for cell in cells), "checks": len(cells),
                      "not_run": {c["id"]: (c.get("not_at") or {}).get(level, "not run at this level") for c in checks if level not in c["levels"]}}
    return out


def parameters(ladder_doc: dict, reg) -> list[dict]:
    """Parameter -> routines and models: one entry per (example, key) the ladder grades, in ruler order."""
    entries: dict[tuple[str, str], dict] = {}
    for check in ladder_doc["checks"]:
        for row in check["rows"]:
            level = level_key(row)
            for p in row["parameters"]:
                entry = entries.setdefault((check["example"], p["key"]), {
                    "example": check["example"], "key": p["key"], "card": p["card"], "rung": p["rung"], "card_parameter": p["card_parameter"],
                    "unit": p["unit"], "true": p["true"], "nominal": p["nominal"], "tolerance": p["tolerance"],
                    "routines": _routines_identifying(reg, p["card"], p["card_parameter"]), "checks": [], "models": {}})
                if check["id"] not in entry["checks"]:
                    entry["checks"].append(check["id"])
                for m in p["models"]:
                    label = f"{check['routine']} · {m['model']}"
                    group = entry["models"].setdefault(label, {"model": label, "routine": check["routine"], "check": check["id"], "fit": m["model"],
                                                               "rung": m["rung"], "graded": m["graded"], "levels": {}})
                    group["levels"][level] = {"recovered": m["recovered"], "error": m["error"], "error_over_tolerance": m["error_over_tolerance"],
                                              "within_tolerance": m["within_tolerance"], "pass": m["pass"], "bound": p["bound"]}
    out = []
    for entry in entries.values():
        entry["models"] = list(entry["models"].values())
        out.append(entry)
    return out


def _routines_identifying(reg, card: str | None, parameter: str | None) -> list[str]:
    if not card or not parameter or card not in reg.CARDS:
        return []
    try:
        return [r.id for r in reg.routines_identifying(card, parameter)]
    except KeyError:
        return []


def table(ladder_doc: dict) -> dict:
    from type_cards import registry as reg  # noqa: PLC0415

    checks = {c["id"]: c for c in ladder_doc["checks"]}
    rows = []
    for r in reg.ROUTINES:
        graded = []
        for cid in r.oracle:
            c = checks.get(cid)
            if c is None:
                graded.append({"id": cid, "levels": {}, "verdict": "not run"})
                continue
            levels = {level_key(row): level_cell(row) for row in c["rows"]}
            graded.append({"id": cid, "example": c["example"], "owner": c["owner"], "structure": c["structure"], "parameters": c["parameters"],
                           "unclaimed": c["unclaimed"], "not_at": c["not_at"], "realism": c["realism"], "levels": levels, "verdict": verdict(levels)})
        rows.append({
            "routine": r.id, "title": r.title, "package": r.package, "kind": r.kind, "setting": r.setting, "status": r.status,
            "wall_time": _plain(r.wall_time), "operator_time": _plain(r.operator_time),
            "equipment": [{"id": e, "title": reg.EQUIPMENT[e].title, "cost": _plain(reg.EQUIPMENT[e].cost)} for e in r.equipment],
            "equipment_cost": _plain(reg.equipment_cost(r)),
            "identifies": [{"card": i.card, "rung": i.rung, "parameters": list(i.parameters)} for i in r.identifies],
            "parameters_covered": sum(len(i.parameters) for i in r.identifies),
            "excitation": r.excitation, "coverage": r.coverage, "repeats": r.repeats, "how": r.how, "tests": list(r.tests),
            "code": [_plain(h) for h in r.code],
            "oracle": {"status": "checked" if r.oracle else "not checked", "checks": graded, "note": r.oracle_note},
            "recovery": recovery([g for g in graded if g.get("levels")], [level["id"] for level in ladder_doc["levels"]]),
            "alternatives": list(r.alternatives), "references": [ref.title for ref in r.references], "note": r.note})
    return {"schema": SCHEMA,
            "generated_from": {"records": "type_cards/calibration.py ROUTINES and EQUIPMENT", "ladder": "sysid/results/noise_ladder.json",
                               "ruler": ladder_doc["ruler"]},
            "levels": [level["id"] for level in ladder_doc["levels"]], "variants": list(ladder_doc["variants"]),
            "summary_levels": list(SUMMARY_LEVELS), "columns": [{"key": k, "what": w} for k, w in COLUMNS], "rows": rows,
            "parameters": parameters(ladder_doc, reg), "parameter_routines": reg.parameter_routines()}
