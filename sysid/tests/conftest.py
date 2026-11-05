"""sysid's tests run from any cwd: the repo root goes on sys.path (sysid, type_cards), bam_ws's packages the examples import too."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
