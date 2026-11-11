"""Moved to src/sim2real/cards/check_references.py on 2026-11-10; this path still runs it (python3 type_cards/check_references.py ... as before)."""

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
runpy.run_module("sim2real.cards.check_references", run_name="__main__", alter_sys=True)
