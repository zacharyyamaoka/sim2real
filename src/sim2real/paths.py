"""Where sim2real looks outside its own repo, each place behind one environment variable whose default is the rack workstation's path.

WHY one module (2026-11-13, bam_ws tools/cloud): the twin sweeps move off the workstation that drives the powered arm (a host-load spike
there stalled its control loop for 23 s). A cloud VM or a rented box has none of these paths, so it sets the variables to where its own
copy is (bam_ws ``tools/cloud/run_job.py`` per job) - the workstation sets nothing and every default below is what the code read before.
Plain constants: nothing is read, created or checked at import.

| variable | default | what it is |
|---|---|---|
| ``SIM2REAL_BAM_WS`` | /home/bam/bam_ws | the bam_ws checkout (its packages, docs and reports) |
| ``SIM2REAL_BAM_WS_SRC`` | $SIM2REAL_BAM_WS/src | the bam_ws ``src`` the twins load by path (mujoco_plant's WHY) |
| ``SIM2REAL_RIG_DATA`` | /archive/datasets/bam_rig | the rig's recorded runs (39 GB; never leaves the workstation) |
| ``SIM2REAL_RACK_DIR`` | $SIM2REAL_RIG_DATA/rack_2026-11-10 | the One Dof Test Rack's session folder |
| ``SIM2REAL_SCHEDULES`` | $SIM2REAL_RIG_DATA/schedules | the frozen schedules |
| ``CAD2ROBOT_BUNDLE_CACHE`` | ~/.cache/cad2robot-build/bundles | git-archived cad2robot/1 bundles, ``<ref>/<subdir>`` (shared with bam_ws) |
| ``SIM2REAL_CAD_EXPORTER`` | /home/bam/cad-exporter | the clone the bundles are archived from when the cache lacks one |
| ``SIM2REAL_ROBOT_MODELS`` / ``_IO_DIAGNOSTICS`` / ``_ROBOTPARTS`` / ``_PIDTUNA`` / ``_DATA_UI`` / ``_DATA_RECORDER`` | /home/bam/<repo> | sibling repos |
"""

from __future__ import annotations

import os
from pathlib import Path


def env_path(name: str, default) -> Path:
    """``$name`` when it is set and not empty, else ``default``."""

    return Path(os.environ.get(name) or default)


BAM_WS = env_path("SIM2REAL_BAM_WS", "/home/bam/bam_ws")
BAM_WS_SRC = env_path("SIM2REAL_BAM_WS_SRC", BAM_WS / "src")
RIG_DATA = env_path("SIM2REAL_RIG_DATA", "/archive/datasets/bam_rig")
RACK_DIR = env_path("SIM2REAL_RACK_DIR", RIG_DATA / "rack_2026-11-10")
SCHEDULES = env_path("SIM2REAL_SCHEDULES", RIG_DATA / "schedules")
BUNDLE_CACHE = env_path("CAD2ROBOT_BUNDLE_CACHE", Path.home() / ".cache" / "cad2robot-build" / "bundles")
CAD_EXPORTER = env_path("SIM2REAL_CAD_EXPORTER", "/home/bam/cad-exporter")
ROBOT_MODELS = env_path("SIM2REAL_ROBOT_MODELS", "/home/bam/robot_models")
IO_DIAGNOSTICS = env_path("SIM2REAL_IO_DIAGNOSTICS", "/home/bam/io-diagnostics")
ROBOTPARTS = env_path("SIM2REAL_ROBOTPARTS", "/home/bam/robotparts")
PIDTUNA = env_path("SIM2REAL_PIDTUNA", "/home/bam/pidtuna")
DATA_UI = env_path("SIM2REAL_DATA_UI", "/home/bam/data-ui")
DATA_RECORDER = env_path("SIM2REAL_DATA_RECORDER", "/home/bam/data_recorder")
