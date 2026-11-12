"""The sim2real curriculum: the rungs each level of the tree climbs, read off the result's five answers (docs/KPIS_GATES_CURRICULUM.md).

    from sim2real.rack_results import load
    from sim2real.tracking.curriculum import status, next_rung
    rows = status(load("fivebar"))          # one row per node x rung: passed / partial / no / unknown / child
    next_rung(rows, "fivebar/arm/j2")       # "S1"

A rung is passed exactly when its question passes in result.verdicts() (its own answer is "yes" AND every child passes it), so the
curriculum never disagrees with the page; it adds no number of its own.

WHY two orders over the same answers (2026-11-11): the verdict reads the five questions in CHECK order (Floor -> Data -> Routines ->
Twin -> Job, proposal C: a wrong floor makes every later number meaningless, so it is asked first). The ladder is climbed in WORK order:
Routines first, because it needs no rig time (Zach's sim-ground-truth-first rule: a routine proves it recovers a hidden truth in sim
before it is trusted on hardware), then the rig rungs from cheapest to dearest. "next rung" and "stops at" can therefore name different
questions only when more than one question is open; today (2026-11-11) they agree on every node.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rung:
    id: str
    title: str
    question: str | None   # the five-question it reads (result.QUESTIONS); None = S0 "described": true of every node in the tree
    gate: str               # the rule in plain words (degrees, mm); "(proposed)" marks a number Zach has not confirmed


TOOL_GATE = "1 mm at a stop"   # result.TOOL_GATE_MM (Zach, 2026-11-11: "final tool error sub 1mm")

LADDERS: dict[str, tuple[Rung, ...]] = {
    # every actuator or sensor type (the joint is the integrated servo; a camera, conveyor or gearbox climbs the same rungs, its own
    # numbers in each gate: docs/KPIS_GATES_CURRICULUM.md, "per type")
    "joint": (
        Rung("S0", "Described", None, "a sim2real type with a nominal model, its parameters and their tolerances"),
        Rung("S1", "Routines recover the hidden truth in sim", "Routines",
             "noise-free, then 1× the real noise with the truth off the search grid, then the stress ladder (3×, 10×, delay and "
             "quantisation variants): every identifiable value within its tolerance, and the nominal value fails its own"),
        Rung("S2", "Real floor known", "Floor",
             "≥ 5 repeats of one input per run kind (commands within 0.01°, compared tick for tick); driven, and passive or "
             "N/A with a measured reason (proposed); twin ÷ floor never below 0.71"),
        Rung("S3", "Coverage", "Data", "≥ 40 % of the reachable (angle, speed, acceleration) cells visited by real runs (proposed); "
             "the held-out split sealed before fitting"),
        Rung("S4", "Twin within 1.5× the floor", "Twin",
             "held-out sim vs real on the floor's own run kind ≤ 1.5× the floor, passive and driven"),
        Rung("S5", "Does its job", "Job",
             f"settled stop error within the joint's share of the tool gate ({TOOL_GATE}); feedback-torque share falling"),
    ),
    "arm": (
        Rung("A0", "Described", None, "the chain, its mounts and a committed reachable mask"),
        Rung("A1", "Arm routines recover the truth in sim", "Routines",
             "kinematics, mounts, joint zeros, delay and the gravity direction at 1× noise, truth sealed"),
        Rung("A2", "Tool repeats", "Floor", "the same commanded tool pose revisited (ISO 9283 RP: 5 poses × 30 cycles), seen by camera"),
        Rung("A3", "Arm coverage", "Data", "joint cube ≥ 90 %, workspace ≥ 50 %, facing or heading ≥ 90 % of the allowed mask (proposed)"),
        Rung("A4", "Coupled twin", "Twin", "twin vs real tool pose ≤ 1.5× the tool floor on coupled multi-joint moves"),
        Rung("A5", "Tool gate", "Job", f"tool ≤ {TOOL_GATE}, on settled holds (not raster turnarounds), measured at the tool"),
    ),
    "tool": (
        Rung("T0", "Described", None, "the TCP and payload, with their tolerances"),
        Rung("T1", "Tool routines recover the truth in sim", "Routines", "payload mass 5 %, centre of mass 3 mm, TCP 0.5 mm across and 1 mm along"),
        Rung("T2", "Tool repeats", "Floor", "the tool at the same commanded stop, revisited, seen by camera"),
        Rung("T3", "Tool seen widely", "Data", "the TCP seen from spread poses; payload classes"),
        Rung("T4", "Tool twin", "Twin", "the after twin's tool vs the real tool at stops ≤ 1.5× the tool floor"),
        Rung("T5", "Tool gate", "Job", f"real tool vs commanded ≤ {TOOL_GATE}, settled, measured at the tool"),
    ),
    "deployment": (
        Rung("D0", "Described", None, "physical or virtual, with its schedule of routines"),
        Rung("D1", "Every child's routines pass", "Routines", "the roll-up of its children's Routines"),
        Rung("D2", "Its output repeats", "Floor", "the deployment's own output repeated: the same scene run twice"),
        Rung("D3", "Physical runs, split sealed", "Data", "runs from every routine in its schedule; for a physical deployment, physical runs"),
        Rung("D4", "The sim ranks like reality", "Twin", "sim ranks policies in the order reality does (rank correlation > 0.9, proposed)"),
        Rung("D5", "Picks", "Job", f"real picks, then successful picks per minute; tool ≤ {TOOL_GATE}"),
    ),
}


def ladder_of(kind: str) -> tuple[Rung, ...]:
    """The ladder a node of this kind climbs (deployment | arm | joint | tool); an unknown kind climbs the joint's generic one."""
    return LADDERS.get(kind, LADDERS["joint"])


def _state(answer: dict) -> str:
    """A question's state at a node, as result._chip has it: passed, or its own answer, or "child" when only a child holds it back."""
    if answer["passes"]:
        return "passed"
    return answer["own"] if answer["own"] != "yes" else "child"


def status(result, verdicts: dict | None = None) -> list[dict]:
    """One row per node x rung of `result` (a sim2real.result.CalibrationResult), in tree order then ladder order."""
    verdicts = verdicts if verdicts is not None else result.verdicts()
    rows = []
    for node in result.nodes:
        answers = verdicts[node.id]["answers"]
        for order, rung in enumerate(ladder_of(node.kind)):
            if rung.question is None:
                state, numbers = "passed", f"{node.type or node.kind}: in the description"
            else:
                answer = answers[rung.question]
                state, numbers = _state(answer), answer.get("numbers", "")
                if state == "child":
                    numbers = "its own answer is yes; not passing below it: " + ", ".join(answer.get("failing_children", []))
            rows.append({"node": node.id, "label": node.label, "level": node.kind, "order": order, "rung": rung.id, "title": rung.title,
                         "question": rung.question or "", "gate": rung.gate, "status": state, "numbers": numbers})
    return rows


def next_rung(rows: list[dict], node_id: str) -> str | None:
    """The lowest rung of this node not passed, in work order; None when it has climbed them all."""
    for row in rows:
        if row["node"] == node_id and row["status"] != "passed":
            return row["rung"]
    return None


def compact(rows: list[dict], node_id: str) -> str:
    """One node's ladder in one line, "S0 ✓ · S1 ~ · S2 ✓ …" (✓ passed, ~ partial, ✗ no, ? unknown, ↓ a child holds it back)."""
    marks = {"passed": "✓", "partial": "~", "no": "✗", "unknown": "?", "child": "↓"}
    return " · ".join(f"{row['rung']} {marks.get(row['status'], '?')}" for row in rows if row["node"] == node_id)
