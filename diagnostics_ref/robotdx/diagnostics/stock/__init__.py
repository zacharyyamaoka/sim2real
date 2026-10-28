"""The stock diagnostics, registered on import. Each is one pure function and one frozen config; a part type gets its
diagnostics by picking these with its own config (``catalog.py``), not by writing code.

Implemented here (the reference): 11 functions. The rest of the catalog's primitives are specified in ``catalog.py``
(``implemented=False``) and land in this package the same way.
"""

from __future__ import annotations

from ..registry import Spec, register
from ..rollup import GateMatrixConfig, RollupConfig, gate_matrix, rollup
from .coverage import CoverageConfig, coverage
from .fidelity import FidelityRatioConfig, FloorConfig, ModelErrorConfig, fidelity_ratio, model_error, repeatability_floor
from .health import BoxConfig, FaultCodesConfig, RateConfig, box, fault_codes, sample_rate
from .tracking import StopErrorConfig, TrackingErrorConfig, stop_error, tracking_error
from .truthfulness import KnownLoadConfig, KtConsistencyConfig, known_load_gain, kt_consistency

STOCK = [
    Spec("stock.tracking_error", tracking_error, TrackingErrorConfig, "tracking error", "real_vs_target", "driver", "kpi_trend", "scalar", "mrad",
         summary="statistic(actual - target) per run, combined over runs"),
    Spec("stock.stop_error", stop_error, StopErrorConfig, "stop error", "real_vs_target", "driver", "distribution", "series", "mrad",
         summary="error left at every dwell; p90 vs the joint's share of the tool gate (T4)"),
    Spec("stock.repeatability_floor", repeatability_floor, FloorConfig, "repeatability floor", "repeatability", "driver", "evidence", "matrix", "mrad",
         summary="median pairwise RMS over identical repeats (T1); the pair matrix is the evidence"),
    Spec("stock.model_error", model_error, ModelErrorConfig, "model error", "sim_vs_real", "driver", "kpi_trend", "scalar", "mrad",
         summary="RMS(real - model) per run, any number of models"),
    Spec("stock.fidelity_ratio", fidelity_ratio, FidelityRatioConfig, "fidelity ratio", "sim_vs_real", "headline", "threshold_band", "series", "1",
         summary="model error / floor per model and tape class (T2 on q, T3 on tau)"),
    Spec("stock.known_load_gain", known_load_gain, KnownLoadConfig, "torque truthfulness (known load)", "truthfulness", "driver", "evidence", "series", "%",
         consumers=("sim2real",), view_extra="xy scatter, reference vs reported torque with the identity line: a slope is the finding",
         summary="drive gain from load-on minus load-off sweeps (T6)"),
    Spec("stock.kt_consistency", kt_consistency, KtConsistencyConfig, "torque truthfulness (Kt vs calibration)", "truthfulness", "health", "kpi_trend", "scalar", "1",
         summary="board Kv vs an independent calibration: reported / true torque"),
    Spec("stock.box", box, BoxConfig, "box check", "health", "health", "threshold_band", "series", "",
         summary="min/max/mean/std of a channel vs four Limits (Zach's BoxChartTask)"),
    Spec("stock.sample_rate", sample_rate, RateConfig, "sample rate", "health", "health", "threshold_band", "series", "Hz",
         summary="achieved rate vs expected +- tolerance, gaps (ROS FrequencyStatus; Zach's EventPeriodTask)"),
    Spec("stock.fault_codes", fault_codes, FaultCodesConfig, "fault and limiter codes", "health", "health", "level_history", "series", "1",
         summary="hard faults and watchdog fail; limiters engaged warn (moteus code table)"),
    Spec("stock.coverage", coverage, CoverageConfig, "coverage", "coverage", "driver", "distribution", "matrix", "1",
         view_extra="2-D occupancy heatmap of the envelope (Zach Oct 28: 'discretize the space'); slices look like image heatmaps",
         summary="share of the declared envelope's cells the runs visited"),
    Spec("stock.rollup", rollup, RollupConfig, "rollup", "rollup", "headline", "rollup_tree", "series", "1",
         summary="a composite's own verdict from its members; caused_by names them"),
    Spec("stock.gate_matrix", gate_matrix, GateMatrixConfig, "gate matrix", "rollup", "headline", "gate_matrix", "matrix", "1",
         summary="subjects x gates; headline = passing cells"),
]

for _spec in STOCK:
    register(_spec)
