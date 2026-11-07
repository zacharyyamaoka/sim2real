"""The model-independent metrics of every run, per run: RobotDx's own catalog entries on each run's npz (type_cards, Domain model v3).

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/run_metrics.py

Zach (PROJECT - Sim2Real, 2026-11-06): diagnostics "are basically like metrics + gate that reports warning or error ... Generally I think we
can calculate these metrics on a per run basis ... but also accross all the runs". Until 2026-11-07 no producer wrote a model-independent
metric per run that a diagnostic reads, so a run page's dots read unknown. This writes, for every deployment folder of the app's data
(tools/build_app.py's), <dep>/run_metrics.json: one row per (run, entry) below, its value or why it has none.

| type_cards metric | RobotDx entry (io-diagnostics robotdx/diagnostics/defaults.py) | the value |
|---|---|---|
| servo.stop_error (integrated servo) | servo.stop_error: stock.stop_error, p90 | the p90 of |q - q_target| (mrad) at the end (the last 50 ms) of every dwell of 0.25 s or more followed by motion, the prelude dropped; encoder side |
| driver.saturation (FOC controller) | driver.saturation: stock.fault_codes, limiter 102 | the share of rows (%) the board reports on its torque cap (moteus limiter code 102) |

WHY RobotDx's entries and its rack loader (robotdx.diagnostics.adapters.rack_npz.load), never a second implementation: they are the
definitions type_cards' metrics name (`MetricSpec.robotdx`), and the loader and dwell scan are the ones bam_rack_twin's T4 uses
(stop_accuracy.py: "so T4 and RobotDx can never disagree on what a stop is"). The value only is written: a level is type_cards' (each
diagnostic's limits, with the unit's own from the deployment's record), never this file's. tools/build_app.py calls write_all() last, so a
rebuild of the app's data writes this table again (it clears each deployment's folder first).

Held by tools/tests/test_run_metrics.py (synthetic runs worked by hand, the rack's runs against T4's definition written there).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from robotdx.diagnostics import defaults as dx_defaults
from robotdx.diagnostics.adapters.rack_npz import load
from robotdx.diagnostics.stock import fault_codes, stop_error

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "app" / "data"
NO_STOP = "no dwell of 0.25 s or more followed by motion (a stop is one constant target held at zero commanded speed)"


@dataclass(frozen=True)
class Entry:
    type: str      # the type_cards (domain v3) entity type
    metric: str    # its metric id (MetricSpec.id): the row's key
    robotdx: str   # the RobotDx catalog entry (MetricSpec.robotdx)
    unit: str


ENTRIES = (
    Entry(type="integrated_servo", metric="servo.stop_error", robotdx="servo.stop_error", unit="mrad"),
    Entry(type="foc_controller", metric="driver.saturation", robotdx="driver.saturation", unit="%"),
)
FIELDS = (("run", "string"), ("device", "string"), ("metric", "string"), ("robotdx", "string"), ("value", "number"), ("unit", "string"),
          ("n", "integer"), ("side", "string"), ("why", "string"))


def _finite(value) -> float | None:
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _measure(result, name: str):
    return next((m.value for m in result.measurements if m.key == name), None)


def stop_error_row(trajectory) -> dict:
    config = dx_defaults.DEFAULTS["servo.stop_error"].config
    if not (trajectory.has("q_target_rad") and trajectory.has("qd_target_rad_s")):
        return {"value": None, "n": 0, "side": config.side, "why": "the run commanded no position target (no q_target, qd_target)"}
    result = stop_error(config, [trajectory])
    value = _finite(result.value)
    n = int(_measure(result, "n") or 0) if value is not None else 0
    return {"value": value, "n": n, "side": config.side, "why": "" if value is not None else NO_STOP}


def saturation_row(trajectory) -> dict:
    config = dx_defaults.DEFAULTS["driver.saturation"].config
    code = config.limiter_codes[0]
    if trajectory.fault is None:
        return {"value": None, "n": 0, "why": "the run logged no fault channel (the board's limiter codes)"}
    result = fault_codes(config, [trajectory])
    rows = int(_measure(result, "rows") or 0)
    if not rows:
        return {"value": None, "n": 0, "why": "the run's fault channel is empty"}
    share = _measure(result, f"limiter_{code}_share") or 0.0  # WHY 0: fault_codes lists a limiter only once a row holds its code
    return {"value": 100.0 * float(share), "n": rows, "why": ""}


ROWS = {"servo.stop_error": stop_error_row, "driver.saturation": saturation_row}


def run_rows(npz: Path, *, run: str = "", device: str = "") -> list[dict]:
    """Every entry's row for one run (its npz and the <name>.json beside it)."""
    base = lambda e: {"run": run or Path(npz).stem, "device": device, "metric": e.metric, "robotdx": e.robotdx, "unit": e.unit}  # noqa: E731
    npz = Path(npz)
    if not npz.is_file():
        return [{**base(e), "value": None, "n": 0, "why": f"its npz is not on this machine ({npz})"} for e in ENTRIES]
    try:
        trajectory = load(npz)
    except Exception as err:  # noqa: BLE001  (a truncated npz: build_app skips those too)
        return [{**base(e), "value": None, "n": 0, "why": f"its npz does not load ({type(err).__name__})"} for e in ENTRIES]
    if not device and trajectory.device:
        device = trajectory.device
    return [{**base(e), "device": device or "", **ROWS[e.metric](trajectory)} for e in ENTRIES]


def table(rows: list[dict], source: str) -> dict:
    return {"name": "run_metrics", "title": "Model-independent metrics per run (RobotDx's catalog entries on each run's npz)",
            "contract": "sim2real.domain/3", "source": source, "entries": [e.__dict__ for e in ENTRIES],
            "schema": {"fields": [{"name": f, "type": t} for f, t in FIELDS]}, "rows": rows}


def write_deployment(folder: Path) -> int:
    runs = json.loads((folder / "runs.json").read_text(encoding="utf-8")).get("rows", [])
    rows = []
    for r in runs:
        rows += run_rows(Path(r.get("npz") or ""), run=r["run"], device=r.get("device") or "")
    import robotdx  # noqa: PLC0415

    source = f"tools/run_metrics.py over {folder.name}/runs.json's npz files (robotdx {getattr(robotdx, '__version__', '?')}, io-diagnostics)"
    (folder / "run_metrics.json").write_text(json.dumps(table(rows, source), ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
                                             encoding="utf-8")
    return len(rows)


def write_all(data: Path = DATA) -> dict[str, int]:
    """<dep>/run_metrics.json for every deployment folder (one holding runs.json). Returns rows written per deployment."""
    return {d.name: write_deployment(d) for d in sorted(Path(data).iterdir()) if d.is_dir() and (d / "runs.json").is_file()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=DATA, help=f"the app's data (default {DATA})")
    args = parser.parse_args(argv)
    started = time.monotonic()
    counts = write_all(args.data)
    for dep, n in counts.items():
        doc = json.loads((args.data / dep / "run_metrics.json").read_text())
        valued = {e.metric: sum(1 for r in doc["rows"] if r["metric"] == e.metric and r["value"] is not None) for e in ENTRIES}
        print(f"{dep}: {n:,} rows -> {args.data / dep / 'run_metrics.json'}; with a value: {valued}")
    print(f"in {time.monotonic() - started:.1f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
