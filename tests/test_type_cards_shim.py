"""type_cards is a shim over sim2real.cards (2026-11-10): every old spelling still works, and reaches the SAME module.

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs --with pytest pytest -q /home/bam/sim2real/tests/test_type_cards_shim.py

Written after the shim; the ruler that held the move itself is type_cards/tests, unchanged (docs/decision-package-layers-2026-11-10.md).
"""

from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import type_cards  # noqa: E402
from sim2real import cards  # noqa: E402

MODULES = sorted(m.name for m in pkgutil.walk_packages(cards.__path__, "sim2real.cards.") if ".tests" not in m.name)


def test_every_module_moved():
    assert {"sim2real.cards.registry", "sim2real.cards.coverage", "sim2real.cards.report", "sim2real.cards.deployments"} <= set(MODULES)


@pytest.mark.parametrize("real", MODULES)
def test_old_name_is_the_same_module(real):
    old = "type_cards" + real[len("sim2real.cards"):]
    assert importlib.import_module(old) is importlib.import_module(real)
    assert importlib.import_module(real).__spec__.name == real  # the alias never relabels the real module


def test_from_import_spelling():
    from type_cards import coverage as cov
    from type_cards import registry as reg

    from sim2real.cards import coverage, registry

    assert (cov, reg) == (coverage, registry)
    assert cov.CoverageResult.__module__ == "robot_msgs.coverage"


def test_old_data_paths_reach_the_moved_files():
    for name in ("arm_reachable", "frozen_reports", "references_checked.json", "CONTRACT.md"):
        assert (REPO / "type_cards" / name).resolve() == (REPO / "src" / "sim2real" / "cards" / name).resolve(), name


def test_python_dash_m_still_runs():
    out = subprocess.run([sys.executable, "-m", "type_cards.report", "list"], cwd=REPO, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    assert "verifies" in out.stdout
