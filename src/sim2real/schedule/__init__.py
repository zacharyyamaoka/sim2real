"""sim2real.schedule: a robot description -> its test schedule, with the coverage known before anything runs (the train / held-out split).
May import metrics.

- joint.py: a 1-DOF joint's schedule (description, build loop and split rule, sampling and limits, coverage before running), played
  through a Player (the rack's runner, a simulator); moved from bam_rack_twin/schedule.py by proposal 2 step 4 (2026-11-10)
"""
