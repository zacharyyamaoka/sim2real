"""sim2real.sim.homing: the homing bench's kinematic rung on the v11 five-bar (decision report 2026-11-12, steps 3-4).

``geometry`` (exact drive stops from robot_models' stop core, the exporter's loop map), ``plant`` (``KinematicStopPlant``, a robot_models
``HomingPlant``), ``procedures`` (the five leaderboard rows as ``HomingProcedure`` black boxes, each one robot_msgs
``JointCommandSequence``), ``bench`` (episodes, starts, the results JSON). Needs the ``homing`` extra (robot_models[contact], scipy).
Imports nothing from sim2real's other layers.
"""
