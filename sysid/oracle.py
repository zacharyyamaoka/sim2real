"""The oracle runner: one entry per example, each the same seven steps (type_cards STEPS: describe, nominal, schedule, capture,
identify, held-out score, gates), with the hidden world sealed while identification runs.

Every example's pipeline module (sysid/examples/<id>/pipeline.py) provides

    plan(description)                         the schedule (train / held-out, coverage) before anything runs
    RealWorld(description)                    the simulator at the hidden truth: .measure(plan) -> measurements, .truth
    identify(description, measurements)       the fit, from the description's nominal values and the train split only
    score(description, plan, fit, measured)   held-out fidelity before (nominal) and after (fitted), per rung
    assemble(...)                             the result document (sysid.result/1)
"""

from __future__ import annotations

import importlib
import inspect
import time

from . import describe, result, world

EXAMPLES = ("pendulum_can11", "ur5e", "ur5e_2f85", "conveyor", "dual_arm_cell", "linescan_cell")
# Noise-ladder scenarios (sysid/noise_ladder.json): the same five-function pipelines and sealed worlds, graded only by the ladder, never
# on the landing page. ur5e_backlash hides a gear gap on the UR's joints (gear_backlash's plant and sweep).
SCENARIOS = ("ur5e_backlash",)
# the last fit per example in this process: drift.run_backlash reuses CAN 11's commissioning instead of re-fitting it (the same
# deterministic inputs give the same fit; this only saves the minutes)
LAST_FIT: dict = {}


def example_module(example: str):
    if example not in EXAMPLES + SCENARIOS:
        raise KeyError(f"no sysid example {example!r} (examples: {', '.join(EXAMPLES + SCENARIOS)})")
    return importlib.import_module(f"sysid.examples.{example}.pipeline")


def run(example: str, *, workers: int = 6, write: bool = False) -> dict:
    started = time.monotonic()
    module = example_module(example)
    description = describe.load(example)
    plan = module.plan(description)
    real = module.RealWorld(description, workers=workers)
    measured = real.measure(plan)
    with world.sealed():
        # WHY by signature (2026-11-17): only the pendulum's identify() opens a pool (its friction polish, default 8); hand it the caller's cap
        options = {"workers": workers} if "workers" in inspect.signature(module.identify).parameters else {}
        fit = module.identify(description, measured.train, **options)
    LAST_FIT[example] = fit
    scores = module.score(description, plan, fit, measured, workers=workers)
    doc = module.assemble(description, plan, fit, scores, truth=real.truth)
    doc["schema"] = result.SCHEMA
    doc["example"] = example
    doc["verdict"] = result.verdict(doc)
    doc.setdefault("provenance", {}).update({"identify_sealed": True, **result.provenance(example),
                                             "seconds": round(time.monotonic() - started, 1)})
    if write:
        result.write(doc)
    return doc
