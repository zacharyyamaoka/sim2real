"""Test-session settings for tests/.

WHY one BLAS thread (measured 2026-11-11 at load average ~57): the camera fits solve ~120 x 120 normal equations, microseconds of work,
and OpenBLAS's thread pool spent ~6 s per solve waiting on busy cores (an 18-view Zhang calibration: 63 s threaded, 0.74 s on one
thread). Set before numpy is imported anywhere in the session; a value already in the environment wins.
"""

import os

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

# WHY forced off (gap E, 2026-11-18): a developer shell or a cloud VM with SIM2REAL_TRACK=ledger|wandb must never make the suite write
# ledgers or push W&B runs; the tests that exercise tracking set it themselves (monkeypatch), and an explicit callbacks= always wins.
os.environ["SIM2REAL_TRACK"] = "off"
