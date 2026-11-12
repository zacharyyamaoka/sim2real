"""The ArUco Marker type as a kit (PEP 0001 section 8): name the type, get its model rungs, the code behind its three routines and its
black-box fidelity metric.

    from sim2real.models.aruco_marker import kit
    k = kit()
    k.rungs, k.identify, k.fidelity      # identify: {"aruco.id_confirm": confirm_ids, "aruco.caliper_size": ..., "aruco.bundle_adjustment": ...}

The instance is one printed sticker carrying one or more markers rigidly, its layout from CAD. The cards (sim2real.cards, the stdlib
contract) hold each routine's record (what it identifies, its time, equipment, status, requires / uses); this module is the code behind
those ids. WHY no import of cards and no routine planning here (PEP 0001 section 1, Zach 2026-11-12): models and parameters stay low and
routine-free so the RobotModels / RobotTwin extraction lifts them out unchanged; the camera's ArUco exposure tuning is the camera kit's
(models/camera.py, its `tune` mapping), since it writes the camera's settings.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from ..fit import aruco
from ..metrics import camera as metric
from .camera import FidelityMetric, Rung

__all__ = ["MarkerKit", "kit", "corner_reprojection_fidelity", "TYPE_ID"]

TYPE_ID = "aruco_marker"


@dataclass(frozen=True)
class MarkerKit:
    type_id: str
    title: str
    rungs: tuple[Rung, ...]
    identify: dict[str, Callable] = field(default_factory=dict)
    fidelity: tuple[FidelityMetric, ...] = ()

    def rung(self, key: str) -> Rung:
        for r in self.rungs:
            if r.key == key:
                return r
        raise KeyError(f"{self.type_id} has no rung {key!r}")


def corner_reprojection_fidelity(bundle: aruco.Bundle, held_out_views: Sequence[aruco.View], sheets: Sequence[aruco.MarkerSheet], *, K, dist,
                                 link_pose: Callable, repeat_views: np.ndarray) -> metric.Fidelity:
    """The fitted twin's corners on views the fit never saw vs the detected corners, over the corner jitter of the sticker held still
    (repeat_views: (frames, corners, 2)): <= 1.5 x is twinned (cards.schema.TWINNED_LIMIT)."""

    predicted, measured = aruco.reproject(bundle, held_out_views, sheets, K=K, dist=dist, link_pose=link_pose)
    return metric.fidelity("aruco.reprojection", metric.reprojection_rms(predicted, measured), metric.jitter_floor(repeat_views), "px",
                           len(measured))


NOMINAL = ("dictionary", "marker_ids", "marker_length_m", "layout_m", "pose_on_link")

MARKER_KIT = MarkerKit(
    TYPE_ID, "ArUco marker",
    rungs=(
        Rung("M0", "Nominal from CAD", NOMINAL, aruco.MarkerSheet, "the sheet as designed, where the CAD bundle put it"),
        Rung("M1", "+ as-built offset", NOMINAL + ("as_built_offset",), aruco.bundle_adjust, "6-DOF in the sticker frame"),
        Rung("M2", "+ print scale", NOMINAL + ("as_built_offset", "print_scale"), aruco.bundle_adjust,
             "today's model; the caliper's scale is its prior where it ran"),
        Rung("M3", "+ curl", NOMINAL + ("as_built_offset", "print_scale", "flatness_m"), "not implemented",
             "no routine fits flatness yet: listed uncovered"),
    ),
    identify={"aruco.id_confirm": aruco.confirm_ids, "aruco.caliper_size": aruco.caliper_scale, "aruco.bundle_adjustment": aruco.bundle_adjust},
    fidelity=(
        FidelityMetric("aruco.reprojection", "where the twin puts each sticker's corners on held-out views", "corner jitter on a still view",
                       "px", corner_reprojection_fidelity),
    ),
)


def kit(type_id: str = TYPE_ID) -> MarkerKit:
    if type_id != TYPE_ID:
        raise KeyError(f"no marker type {type_id!r} (types: {TYPE_ID})")
    return MARKER_KIT
