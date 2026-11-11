"""Coverage of recorded data over a declared envelope: rows per cell of two channels, and the share of cells with enough rows.

WHY robot_msgs.coverage (Zach, 2026-11-10, proposal 2 step 4: "coverage comes from robot_msgs.coverage"): which cell a value falls in is the
one binning rule (numpy.histogramdd's: [lo, hi) per bin, the last [lo, hi], outside dropped), and robot_msgs.coverage.occupancy is it. RobotDx's
stock coverage check called numpy.histogram2d for the same rule; it reads these now, so the rule is written once. What a device's envelope
is and how many rows make a cell covered are the caller's (a card's, a diagnostic's config).
"""

from __future__ import annotations

import numpy as np
from robot_msgs.coverage import occupancy

__all__ = ["cell_counts", "covered_share"]


def cell_counts(x: np.ndarray, y: np.ndarray, x_edges: np.ndarray, y_edges: np.ndarray) -> np.ndarray:
    """Rows per (x, y) cell as a dense int array (x cells by y cells); rows outside the edges are dropped. Finite rows only."""

    cells, _ = occupancy(list(zip(np.asarray(x, float).tolist(), np.asarray(y, float).tolist())),
                         [np.asarray(x_edges, float).tolist(), np.asarray(y_edges, float).tolist()])
    counts = np.zeros((len(x_edges) - 1, len(y_edges) - 1), np.int64)
    for cell, count in cells.items():
        counts[cell] = count
    return counts


def covered_share(counts: np.ndarray, min_samples: int) -> float:
    """The share of the cells holding at least ``min_samples`` rows."""

    return float(np.mean(counts >= min_samples))
