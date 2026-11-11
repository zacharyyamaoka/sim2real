"""sim2real.metrics: data in, numbers out, per modality: performance (real vs target) and fidelity (twin vs real), coverage, the floor ratio,
gate(value, target). The most stable layer: imports robot_msgs and numpy, and no other sim2real layer.
Textbook math with one definition goes to robot_msgs instead (robot_msgs.compare, robot_msgs.coverage).

- gate.py: gate(value, target), a robot_msgs Value's range checked through robot_msgs.space.Space (no range type of its own)
- series.py: the shared rulers (RMS from robot_msgs.compare, the median, the common clock, pairwise RMS)
- actuator.py: the actuator's verbs: tracking, stops (T4), the floor (T1), fidelity ratios (T2, T3), T2's move / hold split
- coverage.py: rows per cell over a declared envelope, robot_msgs.coverage's binning
- servo_gates.py: the servo acceptance gates T1-T11, facts in, verdicts out, targets passed in (cards/ data)

Proposal 2 step 4 (2026-11-10) moved these from bam_rack_twin (acceptance.py) and RobotDx (its stock checks), which now call them
(docs/decision-actuator-verbs-2026-11-10.md).
"""
