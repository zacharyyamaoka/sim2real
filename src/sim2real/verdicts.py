"""The five questions, written once: Floor -> Data -> Routines -> Twin -> Job, answered at a node's own output and rolled up its typed tree.

The rule (MOC - Sim2Real Success Criteria and Metrics, proposal C, the same one CalibrationResult.verdicts() in result.py applies): every
node of a deployment answers the same five questions in order; a parent passes a question only when it passes AT ITS OWN OUTPUT and every
child that gates it passes too; the node's verdict is the first question it does not pass. Two refinements the pendulum campaign settled:

- MOC decision 1's default ("show them, don't gate on them"): a child can be shown under its parent without gating it. The station's
  integrated servo is: its gates T1-T8 are on the page, the campaign goal stays the five pendulum gates. A node says so with
  `gating: False` (it is about the edge to its parent).
- RobotDx's "not run = a warning, never a block": a metric this rig cannot observe, or one not run this round, never fails a question.

A metric's `kind` says how it counts: gated (a goal gate: a miss fails the question) · shown (a gate shown, not gating: a miss is
"watch", amber) · counted (a gate in the scorecard's 180, not in the goal: counted as a miss beside the question, never its status) ·
observed (no gate) · not_observable (this rig cannot see it). A metric's value per round is {"value", "status": pass | fail |
not_observable | not_run | observed, ...}.

Pure and stdlib-only: the page's data builder (sim2real.deployments_page) and the site build call it; nothing here reads a file.
Layer: like result.py, this module sits right of every folder (tests/test_layers.py) and imports none of them.
"""

from __future__ import annotations

# the five, in order; the names are result.QUESTIONS (tests/test_deployments_page.py holds them equal)
QUESTIONS = (
    {"id": "floor", "n": 1, "name": "Floor", "ask": "How much does the real thing disagree with itself?"},
    {"id": "data", "n": 2, "name": "Data", "ask": "Is there enough data, in the right places?"},
    {"id": "routines", "n": 3, "name": "Routines", "ask": "Does each calibration recover a hidden truth, in sim?"},
    {"id": "twin", "n": 4, "name": "Twin", "ask": "Is held-out sim vs real within 1.5× the floor?"},
    {"id": "job", "n": 5, "name": "Job", "ask": "Does the real thing do its job (1 mm at the tip)?"},
)
QUESTION_IDS = tuple(q["id"] for q in QUESTIONS)
KINDS = ("gated", "shown", "counted", "observed", "not_observable")
# how bad a status is when rolling up: a failing goal gate, then a shown gate's miss; everything else is never worse than a pass
SEVERITY = {"fail": 3, "watch": 2, "pass": 1}


def own_answer(metrics: list[dict], question: str, rid: str) -> dict:
    """One question at one node in one round, from the node's own metrics only: {"status", "metric" (the one that decides it), "misses",
    "missed"}. status: fail (a goal gate fails) · watch (a shown gate misses) · pass · not_observable · observed · not_run · none (no metric
    at this level asks it)."""
    rows = [(m, m["values"][rid]) for m in metrics if m["question"] == question and rid in m["values"]]
    if not rows:
        return {"status": "none", "metric": None, "misses": 0, "missed": []}
    gated = [(m, v) for m, v in rows if m["kind"] == "gated" and v["status"] in ("pass", "fail")]
    shown = [(m, v) for m, v in rows if m["kind"] == "shown" and v["status"] in ("pass", "fail")]
    missed = [m["id"] for m, v in rows if m["kind"] == "counted" and v["status"] == "fail"]
    if any(v["status"] == "fail" for _m, v in gated):
        status = "fail"
    elif any(v["status"] == "fail" for _m, v in shown):
        status = "watch"
    elif gated or shown or any(m["kind"] == "counted" and v["status"] == "pass" for m, v in rows):
        status = "pass"
    elif any(v["status"] == "not_observable" for _m, v in rows):
        status = "not_observable"
    elif any(v["status"] == "observed" for _m, v in rows):
        status = "observed"
    else:
        status = "not_run"
    lead = next((x for x in gated + shown if x[1]["status"] == "fail"), None) or next(iter(gated + shown), None) or rows[0]
    return {"status": status, "metric": lead[0]["id"], "misses": len(missed), "missed": missed}


def verdict_of(answers: dict) -> dict:
    """The first question in order that fails, else the first that is outside a shown target, else pass when any question was judged."""
    first = next((q for q in QUESTION_IDS if answers[q]["status"] == "fail"), None)
    watch = next((q for q in QUESTION_IDS if answers[q]["status"] == "watch"), None)
    judged = [answers[q]["status"] for q in QUESTION_IDS if answers[q]["status"] in SEVERITY]
    if first or watch:
        return {"status": "fail" if first else "watch", "first": first or watch}
    if judged:
        return {"status": "pass", "first": None}
    unseen = any(answers[q]["status"] == "not_observable" for q in QUESTION_IDS)
    return {"status": "not_observable" if unseen else "none", "first": None}


def roll_up(nodes: list[dict], rounds) -> list[dict]:
    """Answer the five questions on every node of a tree, bottom up, in each round. Each node needs `id`, `parent`, `children` (ids),
    `metrics` and `gating` (does it gate its parent; default True). Adds, per round:

        questions[rid][q] = {"status", "own", "metric", "via" (the gating children that made it worse), "misses", "missed"}
        verdict[rid]      = {"status", "first"}            the five in order (verdict_of)
        rollup[rid]       = the worst status at or below the node, gating or not (a folded tree row shows it)

    A parent's question is its own answer, made worse by any gating child's fail or watch: it passes only at its own output and with every
    child. Returns the nodes."""
    by_id = {n["id"]: n for n in nodes}

    def visit(n: dict, rid: str) -> None:
        kids = [by_id[c] for c in n["children"]]
        for k in kids:
            visit(k, rid)
        answers = {}
        for q in QUESTION_IDS:
            own = own_answer(n["metrics"], q, rid)
            status, via = own["status"], []
            for k in kids:
                if not k.get("gating", True):
                    continue
                ks = k["questions"][rid][q]["status"]
                if SEVERITY.get(ks, 0) >= 2 and SEVERITY.get(ks, 0) >= SEVERITY.get(status, 0):
                    if SEVERITY.get(ks, 0) > SEVERITY.get(status, 0):
                        via = []
                    status = ks
                    via.append(k["id"])
            answers[q] = {**own, "own": own["status"], "status": status, "via": via}
        n.setdefault("questions", {})[rid] = answers
        n.setdefault("verdict", {})[rid] = verdict_of(answers)
        worst = n["verdict"][rid]["status"]
        for k in kids:
            if SEVERITY.get(k["rollup"][rid], 0) > SEVERITY.get(worst, 0):
                worst = k["rollup"][rid]
        n.setdefault("rollup", {})[rid] = worst

    for rid in rounds:
        for root in (n for n in nodes if n["parent"] is None):
            visit(root, rid)
    return nodes
