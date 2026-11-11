"""Run the conveyor belt's calibration Steps on the MuJoCo twin and print the recovery table (and, later, on the real belt).

    env -u VIRTUAL_ENV MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra sim --extra vision python /home/bam/sim2real/tools/conveyor_belt.py calibrate --rig sim
    env -u VIRTUAL_ENV MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra sim --extra vision python /home/bam/sim2real/tools/conveyor_belt.py seeds --n 5

WHY a tool and not a __main__ in models/ (tests/test_layers.py): the table grades against cards/, and models/ may not import cards/.
"""

from __future__ import annotations

import argparse
import json
import sys

REAL_NEEDS = """the real belt rig adapter (a BeltRig) is not written yet. It needs, from Zach:
  - the belt drive: motor + driver type, its adapter serial (/dev/serial/by-id/...), counts per rev, gear ratio, drum diameter
  - camera 1 and camera 2 serials (RealSense) and camera 1's hand-eye file (bam_calibration)
  - arm 1's probe: which joint currents to read as the load cell, and the tool's ball-tip radius
  - arm 2's touch: a pointed tool and its TCP
  - the line scanner's SDK and its encoder-trigger input
  - belt geometry: width, length, height under arm 1, and where each sensor and arm sits (the description's nominals)
See /home/bam/bam_ws/reports/conveyor-calibration-2026-11-11.html, runbook."""


def _run(seed: int, only, record=None):
    from sim2real.cards import conveyor_belt as card
    from sim2real.metrics.gate import gate
    from sim2real.models.conveyor_belt import NOMINAL, ConveyorBelt
    from sim2real.sim.conveyor_belt import BeltTruth, BeltTwin

    twin = BeltTwin(NOMINAL, BeltTruth.default(), seed=seed, record=record)
    belt = ConveyorBelt(NOMINAL, twin)
    result = belt.calibrate(only=tuple(only) if only else None)
    rows, held_out = [], {}
    if not only:
        nominal = twin.score(belt.nominal_calibration())
        for q, s in twin.score(result).items():
            rows.append({"quantity": q, "estimate": s.estimate, "truth": s.truth, "error": s.error, "unit": s.unit,
                         "nominal_error": nominal[q].error, "tolerance": float(card.TOLERANCES[q].high),
                         "pass": gate(abs(s.error), card.TOLERANCES[q]).passes,
                         "nominal_pass": gate(abs(nominal[q].error), card.TOLERANCES[q]).passes})
        held_out = belt.eval_twin(result)
        fid = held_out.pop("camera_2_handoff_fidelity", None)
        if fid is not None:
            held_out["camera_2_handoff_x_floor"] = fid.ratio
    return twin, result, rows, held_out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="conveyor_belt.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cal = sub.add_parser("calibrate")
    cal.add_argument("--rig", choices=("sim", "real"), default="sim")
    cal.add_argument("--only", nargs="*", default=None, help="step names: scale direction slip plane_depth plane_probe camera_to_camera "
                                                             "robot_to_robot time_offset line_scan")
    cal.add_argument("--seed", type=int, default=0)
    cal.add_argument("--json", default=None)
    # the real rig's wiring (accepted now so the runbook's commands are final; refused until the BeltRig adapter exists)
    cal.add_argument("--drive", default=None, help="belt drive adapter, /dev/serial/by-id/... (never autodetected)")
    cal.add_argument("--camera-1", default=None, help="camera 1 RealSense serial")
    cal.add_argument("--camera-2", default=None, help="camera 2 RealSense serial")
    cal.add_argument("--hand-eye", default=None, help="camera 1's hand-eye file (bam_calibration)")
    cal.add_argument("--max-speed", type=float, default=0.2, help="belt speed guard, m/s")
    cal.add_argument("--dry-run", action="store_true", help="print the plan (moves, speeds, guards) and touch no hardware")
    seeds = sub.add_parser("seeds")
    seeds.add_argument("--n", type=int, default=5)
    seeds.add_argument("--json", default=None)
    args = parser.parse_args(argv)
    if args.cmd == "calibrate" and args.rig == "real":
        print(REAL_NEEDS, file=sys.stderr)
        return 2
    runs = range(args.n) if args.cmd == "seeds" else [args.seed]
    every = []
    ok = True
    for seed in runs:
        twin, _, rows, held_out = _run(seed, getattr(args, "only", None))
        twin.close()
        every.append({"seed": seed, "rows": rows, "eval": held_out})
        for r in rows:
            ok &= r["pass"]
            print(f"seed {seed} {'PASS' if r['pass'] else 'FAIL'}  {r['quantity']:34s} error {r['error']:+9.4f} {r['unit']:4s} "
                  f"(tolerance {r['tolerance']:g}; nominal {r['nominal_error']:+.3f})")
        for k, v in held_out.items():
            print(f"seed {seed} eval  {k:34s} {v:9.4f} {'x floor' if k.endswith('x_floor') else 'mm'}")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(every, fh, indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
