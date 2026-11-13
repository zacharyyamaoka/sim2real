"""Export bam_fivebar_recovery's ``blind_recovery`` as a robot_msgs ``JointCommandSequence`` JSON for the homing bench's recover_first.

Runs under bam_fivebar_recovery's own environment (it imports that package and robot_msgs only, never sim2real), so the sequence bytes
are the routine's own, through its own ``commands.to_robot_msgs`` (the README's swap):

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 /home/bam/bam_ws/src/dev/bam_fivebar_recovery/.venv/bin/python /home/bam/sim2real/src/sim2real/sim/homing/recovery_export.py --out /home/bam/sim2real/src/sim2real/data/fivebar_blind_recovery_v11.json

What is exported, and why (the reuse is the routine with its two references passed in, ``blind_recovery(references=...)``):

* the references are the v11 CAD's (``--j2-stop-deg`` J2's upper stop, ``--c1-contact-deg`` C1's upper stop with L1 on that stop; the
  homing bench's exact first contacts, URDF joint frame), not the July bench's (114.4 / -38.61 deg Craig). WHY the URDF frame works:
  bam_fb_test_rig's ``CraigMap`` on bundle 8957130 gives Craig = URDF + offset with sign +1 for both drives (J2 +90.00, C1 +137.46 deg),
  and the routine defines its own frame at its references, so its positions are then URDF angles.
* only steps 1-7 (``--keep``, default 7): limp, J2 +, lift, C1 +, J2 + onto the stop, C1 + with J2 pressed (define both), J2 5 deg off.
  WHY not 8-: those waypoints are planned on the July bench's reachable map (bam_fivebar BENCH, J2 stop 114.4 deg Craig), which is not
  the v11 arm; every homing procedure seeks from wherever it is, so nothing after the references is needed in front of one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np


def git_sha(path: Path) -> str:
    """sim2real.provenance.code_sha (WHY: this read HEAD with no dirty check, so an uncommitted tree was stamped as a clean commit)."""

    from sim2real.provenance import code_sha  # noqa: PLC0415

    return code_sha(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--j2-stop-deg", type=float, required=True, help="v11 J2 upper stop, URDF deg (homing bench geometry)")
    parser.add_argument("--c1-contact-deg", type=float, required=True, help="v11 C1 upper stop at J2's upper stop, URDF deg")
    parser.add_argument("--keep", type=int, default=7, help="steps kept from the front of the routine")
    args = parser.parse_args(argv)

    import bam_fivebar_recovery
    from bam_fivebar_recovery.commands import to_robot_msgs
    from bam_fivebar_recovery.routine import BLIND_TUNING, BlindReferences, blind_recovery
    from bam_fivebar_recovery.steps import StepSequence

    references = BlindReferences(j2_stop_rad=math.radians(args.j2_stop_deg), c1_contact_rad=math.radians(args.c1_contact_deg))
    # WHY the walk home is not planned: blind_recovery plans steps 8- on the July bench's reachable map from the backoff pose, and with
    # the v11 references that pose (J2 120 deg, C1 197.8 deg) is off that map (bam_fivebar HomingError: no passable pose within 6 deg).
    # Steps 1-7 never read the plan, so the planner is given the backoff pose as the whole path; the one no-op step it adds is dropped.
    from bam_fivebar_recovery import routine

    routine.home_waypoints = lambda bench, start, *, waypoint_deg: np.asarray([start], dtype=float)
    full = blind_recovery(references=references)
    planned = len(full.steps)
    kept = StepSequence(joint_names=full.joint_names, steps=full.steps[: args.keep], name=f"{full.name} (steps 1-{args.keep})",
                        max_speed_rad_s=full.max_speed_rad_s)
    sequence = to_robot_msgs(kept)
    package = Path(bam_fivebar_recovery.__file__).resolve().parent
    payload = {
        "schema": "sim2real_homing_recovery/1",
        "source": f"bam_fivebar_recovery.routine.blind_recovery(references=...) -> commands.to_robot_msgs, steps 1-{args.keep}",
        "bam_ws_sha": git_sha(package),
        "references_deg": {"j2_stop": args.j2_stop_deg, "c1_contact": args.c1_contact_deg},
        "frame": "URDF joint frame of the v11 CAD (Craig = URDF + offset, sign +1 for J2 and C1, bam_fb_test_rig.gravity.CraigMap)",
        "steps_planned": planned,
        "steps_kept": args.keep,
        "tuning": {k: getattr(BLIND_TUNING, k) for k in BLIND_TUNING.__dataclass_fields__},
        "sequence": sequence.to_dict(),
    }
    payload["sequence_sha1"] = hashlib.sha1(json.dumps(payload["sequence"], sort_keys=True).encode()).hexdigest()[:12]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"{args.out}: {args.keep} of {planned} steps, sequence {payload['sequence_sha1']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
