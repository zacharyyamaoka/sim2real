"""The folders a deployment's real runs lie under: its archive days plus every LIVE station's schedule runs/, from the schedule index the
registry names. One rule, read by tools/build_app.py (runs, replays, the newest evidence) and site/deploy_tree.py (a run's tags).

WHY the schedule index and not a listed folder (2026-11-05, rack leftovers): the registry listed schedules/one-dof-test-rack/can11/runs by
hand, so CAN 21's sessions C and D, CAN 12's and CAN 4's schedule sessions never reached the Runs tab. bam_rack_twin.schedule's index.json
names each station's live build (stations[].out); its kept builds (kept[]) hold copies of runs their live folder keeps (checked on
2026-11-05: every run of CAN 12's and CAN 4's kept builds is in the live folder, byte-size equal), so a kept build is never a root.
"""

from __future__ import annotations

import json
from pathlib import Path


def roots(entry: dict) -> list[str]:
    """entry["archive"] (the archive days, in order) then each live station's runs/ by CAN id, where the station has one."""

    days = list(entry.get("archive") or [])
    index = Path(entry.get("schedule_index") or "")
    if not index.is_file():
        return days
    stations = sorted(json.loads(index.read_text())["stations"], key=lambda row: row["can_id"])
    return days + [str(Path(row["out"]) / "runs") for row in stations if (Path(row["out"]) / "runs").is_dir()]


def expanded(entry: dict) -> dict:
    """The registry entry with "archive" replaced by every root (the registry's own days stay under "archive_days")."""

    return {**entry, "archive_days": list(entry.get("archive") or []), "archive": roots(entry)}
