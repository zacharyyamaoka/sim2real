"""The physical deployments' v3 records, one per file (Zach's Python ground truth: `record = PhysicalDeployment(...)`, one keyword per
line). Each names its id in app/registry.json, where its producer fields stay (archive days, the bam_rack_twin record, the schedule
index); type_cards/tests/test_instances.py holds the two to one set of ids. A virtual deployment has no file here: it is a system-ID
oracle example (sysid/results), typed by type_cards/instances.py."""

from __future__ import annotations

import importlib
from pathlib import Path


def records() -> dict:
    """{deployment id: PhysicalDeployment} from every module of this package."""
    out = {}
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        record = importlib.import_module(f"{__name__}.{path.stem}").record
        if record.id in out:
            raise ValueError(f"two records for deployment {record.id!r}")
        out[record.id] = record
    return out
