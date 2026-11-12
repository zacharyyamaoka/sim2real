"""Runs docs/api_example.py verbatim (the compact example docs/API.md opens with) and keeps what docs/build_report_api.py shows.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python /home/bam/sim2real/docs/run_api_example.py

The example's own stdout goes to the terminal untouched (tee it into reports/media/sim2real-api-2026-11-11/example.log). After it ends,
this writes example.json beside the log: the fitted twin's parameters with their provenance, the calibration and the eval report, all
read from the example's own variables (runpy's globals), so nothing is run twice. About 15-27 min: the CAN 11 oracle replays at 30 kHz.
"""

from __future__ import annotations

import json
import runpy
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "media" / "sim2real-api-2026-11-11"


def value(v) -> dict | None:
    if v is None:
        return None
    meta = {k: (m.value if hasattr(m, "value") and not isinstance(m, (int, float, str)) else m) for k, m in v.meta().items()}
    return {"value": float(v), **{k: m for k, m in meta.items() if m not in (None, "", ())}}


def main() -> None:
    from sim2real import twin as front  # noqa: PLC0415

    reports = []
    scored = front.RobotTwin.eval

    def eval_kept(self):
        # WHY kept, not called again: the tracer's eval replays every held-out run (minutes); the report the example printed is the one shown
        reports.append(scored(self))
        return reports[-1]

    front.RobotTwin.eval = eval_kept
    started = time.monotonic()
    # WHY not run_name="__main__": the oracle's replays run in a process pool (bam_rack_twin's Replayer; forkserver on Python 3.14), whose
    # workers re-import the main module; run as __main__, the example would run again inside every worker and the pool refuses that
    # (multiprocessing's "not importing main" RuntimeError: the first try, 2026-11-11). This file stays __main__, behind its guard.
    names = runpy.run_path(str(REPO / "docs" / "api_example.py"), run_name="api_example")
    seconds = round(time.monotonic() - started, 1)
    twin, fitted = names["twin"], names["fitted"]
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"seconds": seconds, "priors": {i: {n: value(v) for n, v in named.items()} for i, named in twin.parameters.items()},
           "parameters": {i: {n: value(v) for n, v in named.items()} for i, named in names["parameters"].items()},
           "calibration": fitted.calibration_.to_dict(), "report": reports[-1].to_dict()}
    (OUT / "example.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
