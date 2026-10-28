"""Roll results up to a component and a composite, by the rules RobotDx already settled.

- A composite is a black box with its own verdict (Zach, 2026-10-22: "say a robot with 8 legs, 1 leg says failure, the
  spider can still report warning"): ``tolerate`` failing members before it fails.
- Explanation runs UP from members to a composite: its record names the members that caused it in ``caused_by``, so
  RobotDx's ``summarize`` counts one cause, not two (Diagnostics Rollups note, 2026-10-23, record v0.1 addendum).
- ``not_run`` is never a pass (record v0 lessons 3 and 5): a cell that never ran stays a gap in the matrix.
- ``gate_matrix`` is Zach's Oct 25 "roll up ... see all of the hard gates passing": subjects x gates, the headline is the
  count of passing cells (bam_rack_twin ``type_gate_cells``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .core import FAIL, NOT_RUN, PASS, RANK, WARN, Limits, Measure, Result, result, worst


@dataclass(frozen=True)
class RollupConfig:
    title: str = "rollup"
    tolerate_fail: int = 0  # failing members before the composite itself fails (the spider rule); 0 = any fail fails
    not_run_is: str = WARN  # what an unrun member does to the composite: warn (default) or fail; never pass


def rollup(config: RollupConfig, members: Sequence[Result]) -> Result:
    """The composite's own verdict from its members' verdicts; ``caused_by`` names every non-pass member."""

    if not members:
        return result(config, value=None, unit="1", metric="passing", limits=Limits(), title=config.title,
                      message="no members", code="NoMembers")
    failing = [m for m in members if m.verdict == FAIL]
    unrun = [m for m in members if m.verdict == NOT_RUN]
    warned = [m for m in members if m.verdict == WARN]
    if len(failing) > config.tolerate_fail:
        verdict, code = FAIL, "MembersFailing"
    elif failing or warned or (unrun and config.not_run_is == WARN):
        verdict, code = WARN, "MembersDegraded" if (failing or warned) else "MembersNotRun"
    elif unrun:
        verdict, code = FAIL, "MembersNotRun"
    else:
        verdict, code = PASS, ""
    passing = sum(m.verdict == PASS for m in members)
    culprits = tuple(dict.fromkeys(m.subject for m in sorted(members, key=lambda m: -RANK[m.verdict]) if m.verdict != PASS and m.subject))
    return result(config, value=passing, unit="1", metric="passing", limits=Limits(), title=config.title, verdict=verdict, code=code,
                  message=f"{passing}/{len(members)} pass; {len(failing)} fail, {len(warned)} warn, {len(unrun)} not run",
                  measurements=(Measure("members", len(members)), Measure("failing", len(failing)), Measure("not_run", len(unrun))),
                  payload={"x": [f"{m.subject} · {m.title}" for m in members], "y": [RANK[m.verdict] for m in members],
                           "group": [m.verdict for m in members], "x_label": "member", "y_label": "verdict rank"},
                  caused_by=culprits)


@dataclass(frozen=True)
class GateMatrixConfig:
    title: str = "gate matrix"
    gates: tuple[str, ...] = ()  # column order (gate names); empty = order of first appearance
    subjects: tuple[str, ...] = ()  # row order; empty = order of first appearance


def gate_matrix(config: GateMatrixConfig, cells: Sequence[tuple[str, str, Result]]) -> Result:
    """``cells`` = (subject label, gate label, result). Headline: passing cells out of rows x gates (a missing cell is
    not_run). Verdict: pass only when every cell passes."""

    rows = list(config.subjects) or list(dict.fromkeys(s for s, _, _ in cells))
    cols = list(config.gates) or list(dict.fromkeys(g for _, g, _ in cells))
    table = {(s, g): r for s, g, r in cells}
    grid = [[table[(s, g)].verdict if (s, g) in table else NOT_RUN for g in cols] for s in rows]
    passing = sum(v == PASS for row in grid for v in row)
    total = len(rows) * len(cols)
    verdict = worst(v for row in grid for v in row) if total else NOT_RUN
    culprits = tuple(dict.fromkeys(table[(s, g)].subject for s in rows for g in cols
                                   if (s, g) in table and table[(s, g)].verdict != PASS and table[(s, g)].subject))
    code = {PASS: "", WARN: "CellsDegraded", FAIL: "CellsFailing", NOT_RUN: "CellsNotRun"}[verdict]
    return result(config, value=passing, unit="1", metric="cells_passing", limits=Limits(), title=config.title, verdict=verdict, code=code,
                  message=f"{passing} of {total} cells pass",
                  measurements=(Measure("cells", total),
                                Measure("not_run", sum(v == NOT_RUN for row in grid for v in row))),
                  payload={"rows": rows, "cols": cols, "cells": grid,
                           "values": [[table[(s, g)].value if (s, g) in table else None for g in cols] for s in rows]},
                  caused_by=culprits)
