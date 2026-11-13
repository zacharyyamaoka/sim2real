"""One homing episode's trace (sim2real.sim.homing.routine_media's JSON) as a Rerun recording: the seven joints in degrees and their
efforts (robot_msgs' JointTrajectory layout), the step and every contact as text, and the arm as a 3D stick figure over the belt.

    env -u VIRTUAL_ENV /home/bam/data_recorder/.venv/bin/python -I /home/bam/sim2real/tools/homing_routine_rrd.py trace.json out.rrd

Runs in data_recorder's venv: robot-msgs[rerun] there pins rerun-sdk 0.40.0, the house's one Rerun (robot_msgs.viz.rerun). sim2real's own
venv carries no Rerun, so the episode is written as JSON there and converted here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rerun as rr
from robot_msgs.trajectory import JointTrajectory
from robot_msgs.viz import rerun as rmr

ROLES = ("J1", "J2", "C1", "W1", "W2", "W3", "CLAW")


def main(argv: list[str]) -> int:
    trace = json.loads(Path(argv[0]).read_text())
    out = Path(argv[1])
    t = np.asarray(trace["t"], dtype=float)
    stream = rr.RecordingStream(rmr.APPLICATION_ID, recording_id=trace.get("recording_id"))
    stream.save(str(out))
    link = np.radians(np.asarray(trace["link_deg"], dtype=float))
    effort = np.asarray(trace["effort_nm"], dtype=float)
    traj = JointTrajectory(t=t, joint_names=ROLES, positions=link, effort=effort)
    rmr.log(traj, "twin", recording=stream, degrees=True)
    # the belt (top face at world z 0, bam_fb_test_rig CONVEYOR) and the stick figure, on the same clock
    belt = trace.get("belt_box")
    if belt:
        stream.log("world/belt", rr.Boxes3D(centers=[belt["centre"]], half_sizes=[belt["half"]], colors=[[60, 62, 66]]), static=True)
    previous = ""
    for k, seconds in enumerate(t):
        stream.set_time(rmr.TIMELINE, duration=float(seconds - t[0]))
        points = trace["stick_m"][k] if trace.get("stick_m") else None
        if points:
            stream.log("world/arm", rr.LineStrips3D([points], radii=0.006, colors=[[220, 120, 40]]))
            stream.log("world/claw", rr.Points3D([points[-1]], radii=0.012, colors=[[12, 163, 12]]))
        step = trace["step"][k]
        if step != previous:
            stream.log("notes/step", rr.TextLog(step))
            previous = step
        contacts = (trace.get("belt") or [[]] * len(t))[k] + (trace.get("self_contact") or [[]] * len(t))[k]
        if contacts:
            stream.log("notes/contact", rr.TextLog(", ".join(contacts), level=rr.TextLogLevel.WARN))
    stream.flush()
    stream.disconnect()
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
