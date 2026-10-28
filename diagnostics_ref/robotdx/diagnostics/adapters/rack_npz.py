"""Load a ``bam_rack_twin.hardware`` run (``<name>.npz`` + its ``<name>.json`` sidecar) into a ``Trajectory``.

The only module here that touches files. The stock diagnostics never import it: a consumer loads, then passes arrays.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ..data import Trajectory
from ..stock.health import Stamps

# the recorder's npz names -> the unit-suffixed columns (data-ui PEP 0010 §4: every column name ends in its unit)
COLUMN_OF = {"q": "q_rad", "q_target": "q_target_rad", "qd": "qd_rad_s", "qd_target": "qd_target_rad_s", "tau": "tau_nm",
             "i_q": "i_q_a", "mode": "mode", "fault": "fault", "temp_c": "temp_c", "voltage": "v_bus_v"}


def load(path: Path | str, *, labels: Mapping[str, Any] | None = None) -> Trajectory:
    path = Path(path)
    meta_path = path.with_suffix(".json")
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    with np.load(path) as archive:
        arrays = {COLUMN_OF.get(name, name): np.asarray(archive[name], float) for name in ("t", *COLUMN_OF) if name in archive.files}
        wall = float(archive["wall"][0]) if "wall" in archive.files and archive["wall"].size else None
    args = meta.get("args") or {}
    merged = {"can_id": meta.get("can_id"), "kind": meta.get("kind"), "ff_coulomb_nm": float(args.get("ff_coulomb_nm") or 0.0),
              "wall_start": wall, **(labels or {})}
    device = f"CAN {meta['can_id']}" if meta.get("can_id") is not None else ""
    return Trajectory(run=str(path), device=device, prelude_s=float(meta.get("prelude_s") or 0.0), labels=merged, **arrays)


def camera_stamps(path: Path | str) -> Stamps:
    """A RealSense recording's hardware clock (ms), read without loading its frames."""

    with np.load(path) as archive:
        return Stamps(np.asarray(archive["hw_ms"], float), source_id=str(path))
