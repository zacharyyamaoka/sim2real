"""The v11 five-bar's stops for the kinematic homing rung: exact mesh first contact for the drives, the exporter's map for the loop.

Two sources, each used only where it is exact enough for what rides on it:

* the drive stops (J1 = revolute_3, J2 = revolute_6, C1 = revolute_7): robot_models' stop core, ``contact.first_contact`` on the
  visual meshes ``hardstops.json`` names (coal; the exporter's algorithm 2). The C1 stop is C1's crank against a spacer on L1, so in
  principle it moves with J2; measured on 8957130 it moves at most 0.004 deg over J2's whole range (the spacer sits about J2's axis).
  It is still computed at J2's angle: ``stop(joint, side, q6)`` interpolates a 0.5 deg table of exact first contacts, built lazily and
  cached on disk per hardstops.json sha256.
* the loop (the coupler and the elbow against the L1 tube, the weight on the shoulder, the loop that cannot close): the exporter's own
  flood-filled (J2, C1) map in ``loops.json`` - 2 deg cells on the export assembly (``grid``), 0.25 deg on the mirrored crank
  (``mirror_grids``). WHY a map here and not exact contact: nothing homes on these contacts; they only decide whether a start can
  reach its stops (reliability, any start). A loop contact found from the map is good to one cell, and the page says so.

Angles are radians in the URDF joint coordinate; the maps are read in degrees, as stored.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BUNDLE_SHA = "8957130"
DEFAULT_ROOT = Path(os.environ.get("SIM2REAL_HOMING_BUNDLE",
                                   f"~/.cache/cad2robot-build/bundles/{BUNDLE_SHA}/fixtures/cad2robot/bam_fb_test_rig")).expanduser()
CACHE_DIR = Path(os.environ.get("SIM2REAL_HOMING_CACHE", "~/.cache/sim2real-homing")).expanduser()
J1, J2, C1 = "revolute_3", "revolute_6", "revolute_7"
DRIVES = (J1, J2, C1)
ROLE = {J1: "J1", J2: "J2", C1: "C1"}
C1_TABLE_STEP_DEG = 0.5
EXPORT, MIRROR = "export", "mirror"


@dataclass(frozen=True)
class LoopMap:
    """One assembly's (J2, C1) status map: '.' free, '#' contact, 'x' the loop cannot close, ' ' not reached."""

    branch: str
    rows_deg: np.ndarray  # J2 (revolute_6)
    cols_deg: np.ndarray  # C1 (revolute_7)
    rows: tuple[str, ...]
    step_deg: float

    def node(self, q6_deg: float, q7_deg: float) -> tuple[int, int] | None:
        i = int(round((q6_deg - self.rows_deg[0]) / self.step_deg))
        k = int(round((q7_deg - self.cols_deg[0]) / self.step_deg))
        if not (0 <= i < len(self.rows_deg) and 0 <= k < len(self.cols_deg)):
            return None
        return i, k

    def status(self, q6_deg: float, q7_deg: float) -> str:
        node = self.node(q6_deg, q7_deg)
        return " " if node is None else self.rows[node[0]][node[1]]

    def node_deg(self, q6_deg: float, q7_deg: float) -> tuple[float, float] | None:
        node = self.node(q6_deg, q7_deg)
        return None if node is None else (float(self.rows_deg[node[0]]), float(self.cols_deg[node[1]]))


class FivebarGeometry:
    """The stops and the loop map of one cad2robot five-bar bundle."""

    def __init__(self, root: str | Path = DEFAULT_ROOT, *, cache_dir: Path | None = CACHE_DIR):
        from robot_models.homing.cad_bundle import CadBundle  # noqa: PLC0415 -- the contact extra (coal + trimesh)

        self.root = Path(root)
        self.bundle = CadBundle(self.root)
        self.hardstops_sha256 = self.bundle.hardstops_sha256
        self.cad = self.bundle.stop_map()
        self._cad_stops = {(s.stop.joint, s.stop.side): s for s in self.bundle.cad_stops()}
        self._meshes = {key: self.bundle.stop_meshes(stop) for key, stop in self._cad_stops.items()}
        self._j2_axis = self.bundle.joint_axis(J2)
        loops_raw = (self.root / "loops.json").read_bytes()
        self.loops_sha256 = hashlib.sha256(loops_raw).hexdigest()
        loops = json.loads(loops_raw)
        grid = loops["grid"]["status_rows"]
        values = np.array(grid["values_deg"], float)
        self.maps = {EXPORT: LoopMap(EXPORT, values, values, tuple(grid["rows"]), float(loops["grid"]["step_deg"]))}
        if loops.get("mirror_grids"):
            mirror = loops["mirror_grids"][0]
            rows = mirror["status_rows"]
            self.maps[MIRROR] = LoopMap(MIRROR, np.array(rows["row_values_deg"], float), np.array(rows["col_values_deg"], float),
                                        tuple(rows["rows"]), float(mirror["step_deg"]))
        self._cache_path = None if cache_dir is None else Path(cache_dir) / f"stops-{self.hardstops_sha256[:16]}.json"
        self._fixed: dict[str, float] = {}
        self._c1: dict[str, float] = {}
        self._dirty = False
        if self._cache_path is not None and self._cache_path.is_file():
            data = json.loads(self._cache_path.read_text())
            self._fixed, self._c1 = data.get("fixed", {}), data.get("c1", {})
        for joint in (J1, J2):
            for side in (-1, 1):
                self._fixed_stop(joint, side)
        self.save()

    # -- exact drive stops ----------------------------------------------------------------------------------------------

    def _first_contact(self, joint: str, side: int, q6_rad: float = 0.0) -> float | None:
        from robot_models.homing.contact import first_contact  # noqa: PLC0415

        stop = self._cad_stops.get((joint, side))
        if stop is None:
            return None
        moving, fixed = self._meshes[(joint, side)]
        if joint == C1 and q6_rad:
            point, axis = self._j2_axis
            fixed = [mesh.rotated(point, axis, q6_rad) for mesh in fixed]
        found = first_contact(moving, fixed, stop.axis_point, stop.axis, side, contact_m=stop.contact_m)
        return None if found is None else float(found.q_rad)

    def _fixed_stop(self, joint: str, side: int) -> float | None:
        key = f"{joint}:{side:+d}"
        if key not in self._fixed:
            self._fixed[key] = self._first_contact(joint, side)
            self._dirty = True
        return self._fixed[key]

    def _c1_at(self, side: int, index: int) -> float:
        key = f"{side:+d}:{index}"
        if key not in self._c1:
            self._c1[key] = self._first_contact(C1, side, math.radians(index * C1_TABLE_STEP_DEG))
            self._dirty = True
        return self._c1[key]

    def stop(self, joint: str, side: int, q6_rad: float = 0.0) -> float | None:
        """The exact first-contact angle of ``joint``'s ``side`` stop (C1's at J2 = ``q6_rad``); None: no stop that way."""
        if joint != C1:
            return self._fixed_stop(joint, side)
        if (C1, side) not in self._cad_stops:
            return None
        x = math.degrees(q6_rad) / C1_TABLE_STEP_DEG
        low = math.floor(x)
        a, b = self._c1_at(side, low), self._c1_at(side, low + 1)
        return a + (b - a) * (x - low)

    def save(self) -> None:
        if self._cache_path is None or not self._dirty:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"hardstops_sha256": self.hardstops_sha256, "fixed": self._fixed, "c1": self._c1}))
        os.replace(tmp, self._cache_path)
        self._dirty = False

    def found_stop_map(self):
        """The stops as the kinematic rung finds them (export pose; C1 at J2 = 0), basis 'measured'."""
        from robot_models.homing.types import StopMap, StopSide  # noqa: PLC0415

        sides = []
        for stop in self.cad.sides:
            q = None if stop.q_rad is None else self.stop(stop.joint, stop.side, 0.0)
            sides.append(StopSide(stop.joint, stop.side, q, basis="measured", source="kinematic rung, coal first contact",
                                  pair=stop.pair))
        return StopMap(tuple(sides), source=f"kinematic rung on {self.root.name}")

    # -- the loop -------------------------------------------------------------------------------------------------------

    def loop_blocked(self, q6_rad: float, q7_rad: float, branch: str = EXPORT) -> bool:
        """True when the exporter's map puts (J2, C1) in contact or unclosable on ``branch``.

        The map's nodes are read as 1 (contact, cannot close, not reached) or 0 (free) and interpolated bilinearly; blocked past
        0.5. WHY interpolated: a link pressed along the loop's boundary follows it, and a nearest-cell staircase would make it jump
        a whole cell (2 deg on the export map) the tick a cell frees - a 3.5 rad/s lunge on the speed guard that no contact makes.
        A node beyond a drive's exact stop counts as free (WHY: the cells straddle the stop faces; the exact contact owns them)."""
        q6, q7 = math.degrees(q6_rad), math.degrees(q7_rad)
        loop = self.maps[branch]
        x = (q6 - loop.rows_deg[0]) / loop.step_deg
        y = (q7 - loop.cols_deg[0]) / loop.step_deg
        i, k = math.floor(x), math.floor(y)
        if not (0 <= i < len(loop.rows_deg) - 1 and 0 <= k < len(loop.cols_deg) - 1):
            return True
        lo6, hi6 = self._fixed_stop(J2, -1), self._fixed_stop(J2, 1)
        lo7, hi7 = self.stop(C1, -1, q6_rad), self.stop(C1, 1, q6_rad)

        def value(a: int, b: int) -> float:
            n6, n7 = math.radians(float(loop.rows_deg[a])), math.radians(float(loop.cols_deg[b]))
            if not (lo6 <= n6 <= hi6 and lo7 <= n7 <= hi7):
                return 0.0
            return 0.0 if loop.rows[a][b] == "." else 1.0

        fx, fy = x - i, y - k
        level = ((1 - fx) * (1 - fy) * value(i, k) + fx * (1 - fy) * value(i + 1, k)
                 + (1 - fx) * fy * value(i, k + 1) + fx * fy * value(i + 1, k + 1))
        return level > 0.5


__all__ = ["BUNDLE_SHA", "C1", "DEFAULT_ROOT", "DRIVES", "EXPORT", "J1", "J2", "MIRROR", "ROLE", "FivebarGeometry", "LoopMap"]
