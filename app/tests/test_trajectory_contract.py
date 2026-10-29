"""sim2real's difference(a, b) against data-ui's fixture, and the app's run tables against the contract's 13 schemas.

    env -u VIRTUAL_ENV uv run --isolated --with numpy python /home/bam/sim2real/app/tests/test_trajectory_contract.py

The fixture (vendor/data-ui/gallery/robotics/fixtures/difference, numpy/scipy oracle, seed 20261029) is data-ui's ruler:
this test reads it through data-ui's own fixture.py and never edits it. It also proves the check can fail: a difference
that holds b's end values (np.interp, the bug the contract names) and one that writes a − b must each be rejected.
With --data it checks every table the app wrote under app/data/ (tools/build_app.py) against the contract's schemas.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "vendor" / "data-ui" / "gallery" / "robotics"))
import fixture  # noqa: E402  (data-ui's reader of its own fixture, stdlib only)
import numpy as np  # noqa: E402
import trajectory  # noqa: E402

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAILS.append(what)


def held_ends(a, b):
    """A wrong difference on purpose: np.interp holds b's end values, so a's samples outside b's span get rows."""
    out = []
    for row in a:
        bs = [r for r in b if r["run"] == row["run"] and r["device"] == row["device"]]
        if not bs:
            continue
        bt = np.array([r["t"] for r in bs])
        q = np.array([np.nan if r["q_deg"] is None else r["q_deg"] for r in bs])
        new = {"t": row["t"], "run": row["run"], "situation": row["situation"], "source": row["source"], "reference": bs[0]["situation"], "device": row["device"]}
        new["e_q_mrad"] = None if row["q_deg"] is None else float((np.interp(row["t"], bt, q) - row["q_deg"]) * trajectory.DEG_TO_MRAD)
        out.append(new)
    return out


def a_minus_b(a, b):
    rows = trajectory.difference_samples(a, b)
    return [{**r, **{k: (None if r[k] is None else -r[k]) for k in r if k.startswith("e_")}} for r in rows]


def robotdx_samples(a, b):
    """robotdx.diagnostics.data.difference (arrays in, (t, e) out) wrapped to rows: only e_q_mrad, the one channel it computes."""
    from robotdx.diagnostics.data import difference
    out = []
    groups = {}
    for row in b:
        groups.setdefault((row["run"], row["device"]), []).append(row)
    for key in dict.fromkeys((r["run"], r["device"]) for r in a):
        if key not in groups:
            continue
        a_rows = [r for r in a if (r["run"], r["device"]) == key and r["q_deg"] is not None]
        b_rows = groups[key]
        if not a_rows or all(r["q_deg"] is None for r in b_rows):
            continue
        ta = np.array([r["t"] for r in a_rows]); qa = np.radians([r["q_deg"] for r in a_rows])
        tb = np.array([r["t"] for r in b_rows if r["q_deg"] is not None]); qb = np.radians([r["q_deg"] for r in b_rows if r["q_deg"] is not None])
        t, e = difference((ta, qa), (tb, qb))
        out += [{"t": float(ti), "device": key[1], "e_q_mrad": float(1e3 * ei)} for ti, ei in zip(t, e)]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", action="store_true", help="also check every table under app/data against the contract's schemas")
    parser.add_argument("--robotdx", action="store_true", help="also report whether robotdx's difference passes the fixture (q only)")
    args = parser.parse_args()

    problems = fixture.check_difference(poses=trajectory.difference_poses, samples=trajectory.difference_samples)
    check(problems == [], f"difference(a, b) reproduces the fixture: {len(fixture.rows('diff_poses'))} pose rows, "
                          f"{len(fixture.rows('diff_samples'))} sample rows ({problems[:3]})")
    wrong = fixture.check_difference(samples=held_ends)
    check(bool(wrong), f"the check rejects np.interp's held ends ({wrong[0] if wrong else 'accepted!'})")
    wrong = fixture.check_difference(samples=a_minus_b)
    check(bool(wrong), f"the check rejects a − b ({wrong[0] if wrong else 'accepted!'})")

    if args.robotdx:
        a, b = fixture.trajectories("samples")
        expected = [r for r in fixture.rows("diff_samples") if r["e_q_mrad"] is not None]
        got = robotdx_samples(a, b)
        same_rows = len(got) == len(expected) and all(abs(g["t"] - e["t"]) < 1e-12 for g, e in zip(got, expected))
        worst = max((abs(g["e_q_mrad"] - e["e_q_mrad"]) for g, e in zip(got, expected)), default=math.inf) if same_rows else math.inf
        print(f"REPORT robotdx difference on the fixture's samples (e_q_mrad only): {len(got)} rows vs {len(expected)} expected; "
              f"same times: {same_rows}; worst |e_q_mrad - expected| {worst:.3g} -> {'passes' if same_rows and worst <= 1e-9 else 'FAILS'} the fixture")

    if args.data:
        data = REPO / "app" / "data"
        names = {"runs.json": "runs", "samples.json": "samples", "poses.json": "poses", "diff_samples.json": "diff_samples",
                 "diff_poses.json": "diff_poses", "devices.json": "devices", "coverage_samples.json": "coverage_samples"}
        checked, bad = 0, []
        for path in sorted(data.rglob("*.json")):
            name = names.get(path.name)
            if name is None or "source" in path.parts:
                continue
            document = json.loads(path.read_text())
            if "schema" not in document:
                continue  # an app table in data-ui's runtime shape (not a contract table)
            checked += 1
            found = trajectory.validate(name, document)
            if found:
                bad.append((str(path.relative_to(data)), found[:2]))
        check(checked > 0 and not bad, f"{checked} contract tables under app/data validate against the 13 schemas ({bad[:3]})")
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
