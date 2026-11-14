"""sim2real.paths: every place outside the repo behind one environment variable, its default the rack workstation's path.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_paths.py

WHY (2026-11-13, bam_ws tools/cloud): the twin sweeps run in cloud VMs, where /home/bam and /archive do not exist; a job sets these variables
to its own copy. Pinned: the defaults are the workstation's (so nothing there moves), each variable moves what reads it, and no module grows a
new absolute workstation path outside sim2real/paths.py (the scan fails on one; the allowlist names why each remaining literal stays).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "sim2real"
# file -> literals allowed to stay, each with its reason
ALLOWED = {
    "paths.py": "the defaults themselves",
    "cards/calibration.py": "CodeHome pointers (this repo's canonical path, aruco-studio): where code lives, shown on the cards, never opened",
    "cards/render_note.py": "the vault note the workstation-only renderer writes",
    "cards/report.py": "the app's data folder, a workstation CLI default",
    "rack_results.py": "a lane's worktree, the fallback after $SIM2REAL_BAM_WS's copy",
}
PROBE = ("import json; from sim2real import paths, rack_results; from sim2real.cards import instances; "
         "print(json.dumps({k: str(getattr(paths, k)) for k in dir(paths) if k.isupper()} | "
         "{'rack_results.RACK': str(rack_results.RACK), 'instances.SCHEDULES': str(instances.SCHEDULES)}))")


def probe(**env) -> dict:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("SIM2REAL_", "CAD2ROBOT_"))}
    run = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, check=True,
                         env={**clean, **env, "PYTHONPATH": str(PACKAGE.parent)})
    return json.loads(run.stdout)


def absolute_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    docs = {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body
            and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return [f"{path.relative_to(PACKAGE)}:{node.lineno}: {node.value[:60]}" for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
            and node.value.startswith(("/home/bam", "/archive"))]


def test_the_defaults_are_the_workstations_paths():
    got = probe()
    assert got["BAM_WS"] == "/home/bam/bam_ws" and got["BAM_WS_SRC"] == "/home/bam/bam_ws/src"
    assert got["RACK_DIR"] == got["rack_results.RACK"] == "/archive/datasets/bam_rig/rack_2026-11-10"
    assert got["SCHEDULES"] == got["instances.SCHEDULES"] == "/archive/datasets/bam_rig/schedules"
    assert got["BUNDLE_CACHE"] == str(Path.home() / ".cache" / "cad2robot-build" / "bundles")
    assert got["ROBOT_MODELS"] == "/home/bam/robot_models" and got["CAD_EXPORTER"] == "/home/bam/cad-exporter"


def test_each_variable_moves_what_reads_it():
    got = probe(SIM2REAL_BAM_WS="/vm/bam_ws", SIM2REAL_RIG_DATA="/vm/rig", CAD2ROBOT_BUNDLE_CACHE="/vm/bundles")
    assert got["BAM_WS_SRC"] == "/vm/bam_ws/src"  # follows SIM2REAL_BAM_WS unless set itself
    assert got["rack_results.RACK"] == "/vm/rig/rack_2026-11-10" and got["instances.SCHEDULES"] == "/vm/rig/schedules"
    assert got["BUNDLE_CACHE"] == "/vm/bundles"
    assert probe(SIM2REAL_BAM_WS_SRC="/elsewhere/src")["BAM_WS_SRC"] == "/elsewhere/src"
    assert probe(SIM2REAL_SCHEDULES="")["SCHEDULES"] == "/archive/datasets/bam_rig/schedules"  # empty = unset, as before


def test_no_module_names_a_workstation_path_outside_paths_py():
    found = [line for path in sorted(PACKAGE.rglob("*.py")) if "tests" not in path.relative_to(PACKAGE).parts
             for line in absolute_literals(path) if line.split(":")[0] not in ALLOWED]
    assert found == [], "route these through sim2real.paths:\n" + "\n".join(found)


def test_the_scan_catches_a_planted_path(tmp_path):
    planted = PACKAGE / "sim" / "_planted_path_probe.py"
    planted.write_text('"""Docstrings may say /home/bam/x."""\nWHERE = "/archive/datasets/bam_rig/x"\n')
    try:
        assert absolute_literals(planted) == ["sim/_planted_path_probe.py:2: /archive/datasets/bam_rig/x"]
    finally:
        planted.unlink()
