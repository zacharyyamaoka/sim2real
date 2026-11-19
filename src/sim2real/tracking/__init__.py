"""Where a calibration's result goes after result.display(): the curriculum it climbs (curriculum.py) and the trackers it is logged to
(wandb_log.py: Weights & Biases, an optional extra), and the W&B copy of a calibration's ledger as it runs (calibrate_wandb.py, gap E).
Nothing in sim2real imports this package at load: only sim2real.calibration.callbacks reaches in, lazily (wandb_log.code_version for a
ledger's provenance, calibrate_wandb for SIM2REAL_TRACK=wandb), and nothing here imports wandb until it talks to W&B.

Layer: like result.py and twin.py, right of every folder (tests/test_layers.py).
"""
