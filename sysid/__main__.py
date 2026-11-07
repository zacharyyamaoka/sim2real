"""python -m sysid: run the oracle and write the results the site shows.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid run --all --write
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid run ur5e conveyor
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid drift all --write
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid list
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid all --write
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid ladder conveyor --write
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sysid routines --write
"""

from __future__ import annotations

import argparse
import json
import sys

from . import RESULTS_DIR, oracle, result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sysid", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run examples")
    run.add_argument("examples", nargs="*")
    run.add_argument("--all", action="store_true")
    run.add_argument("--workers", type=int, default=6)
    run.add_argument("--write", action="store_true", help=f"write {RESULTS_DIR}/<id>.json")
    drift = sub.add_parser("drift", help="run the drift demos")
    drift.add_argument("which", choices=("backlash_wear", "camera_knock", "all"))
    drift.add_argument("--workers", type=int, default=6)
    drift.add_argument("--write", action="store_true")
    every = sub.add_parser("all", help="every example, then both drift demos, in one process (the wear demo reuses CAN 11's commissioning fit)")
    every.add_argument("--workers", type=int, default=6)
    every.add_argument("--write", action="store_true")
    sub.add_parser("list", help="the examples and their committed verdicts")
    ladder = sub.add_parser("ladder", help="the noise ladder (sysid/noise_ladder.json) for examples (default: every one it has checks for)")
    ladder.add_argument("examples", nargs="*")
    ladder.add_argument("--levels", nargs="+", help="only these main levels (0x 1x 3x 10x)")
    ladder.add_argument("--variants", nargs="+", help="only these variants (sysid/noise_ladder.json variants)")
    ladder.add_argument("--workers", type=int, default=6)
    ladder.add_argument("--write", action="store_true", help=f"merge the rows into {RESULTS_DIR}/noise_ladder.json")
    routines = sub.add_parser("routines", help="the Calibration Routines table: type_cards' records joined with the committed ladder")
    routines.add_argument("--write", action="store_true", help=f"write {RESULTS_DIR}/calibration_routines.json")
    args = parser.parse_args(argv)

    if args.command == "ladder":
        from . import ladder as ladder_module  # noqa: PLC0415

        for example in tuple(args.examples) or tuple(ladder_module.examples()):
            checks = ladder_module.run_example(example, levels=args.levels, variants=args.variants, workers=args.workers)
            for check in checks:
                for row in check["rows"]:
                    worst = row["worst_error_over_tolerance"]
                    failing = [p["key"] for p in row["parameters"] if not p["pass"]]
                    print(f"{check['id']} {row['level']}{'+' + row['variant'] if row['variant'] else ''}: {'pass' if row['pass'] else 'FAIL'} "
                          f"(worst {'—' if worst is None else f'{worst:.3g}'}x tolerance, {row['provenance']['seconds']} s)"
                          f"{' failing ' + ', '.join(failing[:6]) if failing else ''}", flush=True)
            if args.write and checks:
                ladder_module.merge(checks)
        return 0
    if args.command == "routines":
        from . import ladder as ladder_module  # noqa: PLC0415
        from . import routines as routines_module  # noqa: PLC0415

        doc = routines_module.table(json.loads(ladder_module.RESULT_PATH.read_text(encoding="utf-8")))
        for row in doc["rows"]:
            cells = ", ".join(f"{k} {'pass' if v['pass'] else 'FAIL'} {v['worst_error_over_tolerance'] if v['worst_error_over_tolerance'] is None else round(v['worst_error_over_tolerance'], 3)}"
                              for k, v in row["recovery"].items())
            print(f"{row['routine']:38s} {row['setting']:8s} {row['status']:16s} {cells or row['oracle']['status']}")
        if args.write:
            result.write(doc, "calibration_routines")
        return 0

    if args.command == "list":
        for example in oracle.EXAMPLES:
            path = RESULTS_DIR / f"{example}.json"
            doc = json.loads(path.read_text()) if path.is_file() else None
            print(f"{example:16s} {doc['verdict']['status'] if doc else 'not run':8s} {doc['title'] if doc else ''}")
        return 0
    if args.command == "all":
        status = main(["run", "--all", "--workers", str(args.workers)] + (["--write"] if args.write else []))
        return main(["drift", "all", "--workers", str(args.workers)] + (["--write"] if args.write else [])) or status
    if args.command == "run":
        examples = oracle.EXAMPLES if args.all else tuple(args.examples)
        failing = 0
        for example in examples:
            doc = oracle.run(example, workers=args.workers, write=args.write)
            v = doc["verdict"]
            failing += v["status"] != "pass"
            print(f"{example}: {v['status']} ({v['parameters_pass']}/{v['parameters']} parameters, {v['metrics_pass']}/{v['metrics']} metrics, "
                  f"{doc['provenance']['seconds']} s){' failing: ' + ', '.join(v['failing']) if v['failing'] else ''}", flush=True)
        if args.write:
            write_index()
        return 1 if failing else 0
    from . import drift as drift_module  # noqa: PLC0415

    names = ("backlash_wear", "camera_knock") if args.which == "all" else (args.which,)
    for name in names:
        doc = {"backlash_wear": drift_module.run_backlash, "camera_knock": drift_module.run_camera}[name](workers=args.workers, write=args.write)
        if name == "backlash_wear":
            print(f"backlash_wear: rate {doc['rate_recovered']:.4g} rad/h (true {doc['rate_true']:.4g}); predicted crossing {doc['predicted_crossing_h']} h (plan by {doc['plan_by_h']} h) at "
                  f"{doc['predicted_at_h']:g} h, actual {doc['actual_crossing_h']} h, detector {doc['detector_alarm_h']} h; recalibrated ratio "
                  f"{(doc['recalibrated'] or {}).get('ratio')}", flush=True)
        else:
            print(f"camera_knock: knock {doc['knock_h']} h, alarm {doc['alarm_h']} h, recalibrated ratio {(doc['recalibrated'] or {}).get('ratio')}", flush=True)
    if args.write:
        write_index()
    return 0


def write_index() -> None:
    rows = []
    for example in oracle.EXAMPLES:
        path = RESULTS_DIR / f"{example}.json"
        if path.is_file():
            doc = json.loads(path.read_text())
            rows.append({"example": example, "title": doc["title"], "subtitle": doc.get("subtitle", ""), "verdict": doc["verdict"],
                         "code": doc["provenance"].get("code")})
    drifts = [name for name in ("drift_backlash_wear", "drift_camera_knock") if (RESULTS_DIR / f"{name}.json").is_file()]
    result.write({"schema": "sysid.index/1", "example": "index", "examples": rows, "drift": drifts}, "index")


if __name__ == "__main__":
    sys.exit(main())
