"""Run each docs-site example for real and record what it printed and found: website/examples/<name>.out.json.

    systemd-run --user --scope -p MemoryMax=16G -p OOMPolicy=continue -- env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python /home/bam/sim2real/website/build/record_examples.py pendulum_can11

Heavy: calibrate(on="sim") replays the oracle's runs (the pendulum about 15-27 min, the wrist tens of minutes), so run it in the
background under the memory cap above. The site build (build.py) never runs this; it reads the .out.json files.

Each record is stamped with ``source_sha256``, the sha256 of the snippet's bytes, so an edited snippet with an old output is caught
(tests/test_docs_site.py). WHY the snippet runs in THIS process via runpy, with this file's own ``__main__`` guard: calibrate() replays
runs in a process pool whose workers re-import the main module; this file is that module, and its guard keeps a worker from recording
again. The snippet's globals come back from runpy, so the record reads the real ``fitted`` and ``report`` objects, never parsed stdout.

Schema: whatever the calibration's to_dict seam reports today. Once the backend lane lands (PEP 0001 section 7) a fitted twin carries
``record_`` and the record is ``sim2real.calibration/1``; this file prefers it with no edit.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import io
import json
import math
import runpy
import sys
import time
from pathlib import Path

WEBSITE = Path(__file__).resolve().parent.parent
EXAMPLES = WEBSITE / "examples"
NAMES = ("pendulum_can11", "ur_wrist_test_rig")


class _Tee(io.TextIOBase):
    """Keep what the snippet prints and still show it live (a long run should not look hung)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def _plain(value):
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return None if isinstance(value, float) and not math.isfinite(value) else value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _parameter(row: dict) -> dict:
    """One parameter row in the site's shape; every key the seam reported is kept beside the named ones."""
    value = row["value"] if "value" in row else row.get("recovered")
    named = {"key": row["key"], "value": value, "ci95": row.get("ci95"), "true": row.get("true"), "pass": row.get("pass"),
             "routine": row.get("routine"), "unit": row.get("unit"), "nominal": row.get("nominal"), "error": row.get("error"),
             "tolerance": row.get("tolerance")}
    if named["error"] is None and value is not None and row.get("true") is not None:
        named["error"] = value - row["true"]
    return _plain({**row, **named})


def record(name: str) -> dict:
    snippet = EXAMPLES / f"{name}.py"
    source = snippet.read_bytes()
    printed = io.StringIO()
    started = time.monotonic()
    with contextlib.redirect_stdout(_Tee(sys.stdout, printed)):
        env = runpy.run_path(str(snippet), run_name="__main__")
    seconds = round(time.monotonic() - started, 1)
    fitted, report = env.get("fitted"), env.get("report")
    if fitted is None:
        raise RuntimeError(f"{snippet} must leave its calibrated twin in a variable named `fitted`")
    record_ = getattr(fitted, "record_", None)
    if record_ is not None:  # PEP 0001 section 7: the stable record, once the backend lane has landed
        seam = record_.to_dict()
        schema = seam.get("schema")
        rows = seam.get("parameters", [])
    else:
        seam = fitted.calibration_.to_dict()
        schema = seam.get("schema") or seam.get("seam") or f"{type(fitted.calibration_).__module__}.{type(fitted.calibration_).__name__}.to_dict"
        rows = seam.get("rows", [])
    evaluation = None
    if report is not None:
        evaluation = {"passed": bool(report.passed), "summary": report.summary(), "to_dict": _plain(report.to_dict())}
    return {
        "example": name,
        "source": f"website/examples/{name}.py",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "schema": schema,
        "recorded": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "seconds": seconds,
        "model": getattr(fitted, "model", None),
        "passed": bool(fitted.calibration_.passed),
        "failing": list(fitted.calibration_.failing),
        "stdout": printed.getvalue(),
        "parameters": [_parameter(r) for r in rows],
        "evaluation": evaluation,
        "calibration": _plain({k: v for k, v in seam.items() if k not in ("rows", "parameters")}),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", default=list(NAMES), help=f"examples to run (default: all of {', '.join(NAMES)})")
    args = ap.parse_args(argv)
    for name in args.names:
        if name not in NAMES:
            raise SystemExit(f"unknown example {name!r}; known: {', '.join(NAMES)}")
        out = record(name)
        target = EXAMPLES / f"{name}.out.json"
        target.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"recorded {target} ({len(out['parameters'])} parameters, {out['seconds']:.0f} s, schema {out['schema']})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
