"""calibrate()'s back end (PEP 0001, docs/peps/0001-sim2real-docs-site-and-calibrate-backend.md): pick models per part, derive the
parameters, select the catalog routines that identify them by metric, order them from their declared dependencies, steer the whole run
with a CalibrationConfig, and return one stable record.

The designer's base commit holds only ``recovery`` (the one reader of the routines' recovery ladders, shared by the planner and the docs
site). The backend lane adds plan.py, config.py and record.py here and exports their names from this file.

Layer: like twin.py and rig.py, right of every folder (tests/test_layers.py names the folders); no layer folder imports this package.
"""
