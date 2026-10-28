from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from robotdx.diagnostics.data import Trajectory

RACK = Path("/archive/datasets/bam_rig")
CONTRACT = Path("/home/bam/io-diagnostics/contract/record.py")


def tape(n: int = 600, dt: float = 0.01, *, offset: float = 0.0, run: str = "synthetic", **labels) -> Trajectory:
    """A 1-DOF waypoint tape: move, dwell 0.5 s, move, dwell, ... with q = q_target + offset."""

    t = np.arange(n) * dt
    q_target = np.zeros(n)
    qd_target = np.zeros(n)
    for start in range(0, n, 150):
        move = slice(start, min(start + 100, n))
        q_target[move] = np.linspace(0, 0.5, move.stop - move.start) + (start // 150) * 0.5
        qd_target[move] = 0.5 / (100 * dt)
        q_target[min(start + 100, n):min(start + 150, n)] = 0.5 + (start // 150) * 0.5
    return Trajectory(t=t, q_rad=q_target + offset, q_target_rad=q_target, qd_rad_s=qd_target.copy(), qd_target_rad_s=qd_target,
                      mode=np.full(n, 10.0), fault=np.zeros(n), temp_c=np.full(n, 25.0), v_bus_v=np.full(n, 24.0),
                      tau_nm=np.zeros(n), run=run, device="CAN 99", labels=labels)


@pytest.fixture(scope="session")
def contract():
    """io-diagnostics' record contract, loaded read-only from its checkout (no bytecode written into that repo)."""

    if not CONTRACT.is_file():
        pytest.skip("io-diagnostics contract not on this machine")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("io_diagnostics_contract_record", CONTRACT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


needs_rack = pytest.mark.skipif(not (RACK / "rack_2026-10-24" / "analysis" / "floors.json").is_file(), reason="rack archive not mounted")
