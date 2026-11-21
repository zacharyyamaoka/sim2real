"""A stand-in `wandb` module that holds a writer to summary statistics: every media / table / artifact call raises, every value logged
to a run's history or summary must be a scalar. No network, no wandb-core.

    fake = StrictWandb(); monkeypatch.setitem(sys.modules, "wandb", fake); ...writer...; fake.runs[0].logged / .summary / .config

WHY (Zach, 2026-11-21: "to help limit W and B storage I think we need to just be using it for summary statistics; for the media-rich
things we should be using rerun!"): W&B was at 17 GB against a 5 GB cap, mostly tables and images; a writer that reaches for one again
fails its test here, whatever it logs it through.
"""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

# what W&B may hold: a number, a word, a flag (a None is dropped by the writers, but harmless)
SCALARS = (int, float, str, bool, type(None))
FORBIDDEN = ("Table", "Image", "Video", "Html", "Object3D", "Plotly", "Audio", "Histogram", "Artifact", "Molecule", "Graph", "plot_table",
             "log_artifact", "save", "use_artifact")


def _forbidden(name: str):
    def call(*args, **kwargs):
        raise AssertionError(f"wandb.{name} called: W&B is for summary statistics only (Zach, 2026-11-21); keep it local / in Rerun")

    return call


def assert_scalars(values: dict, where: str) -> None:
    bad = {key: type(value).__name__ for key, value in values.items() if not isinstance(value, SCALARS)}
    assert not bad, f"{where}: not scalars {bad}"


class _Summary(dict):
    def __setitem__(self, key, value):
        assert_scalars({key: value}, "run.summary")
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        values = dict(*args, **kwargs)
        assert_scalars(values, "run.summary.update")
        super().update(values)


class _Config(dict):
    def update(self, *args, allow_val_change: bool = False, **kwargs):
        super().update(dict(*args, **kwargs))


class StrictRun:
    def __init__(self, module: StrictWandb, init: dict):
        self.module, self.init = module, init
        self.id = init.get("id")
        self.url = f"https://wandb.ai/e/p/runs/{self.id}"
        self.config = _Config(init.get("config") or {})
        size = len(json.dumps(dict(self.config), default=str))
        assert size < 64_000, f"wandb.init config is {size} bytes: W&B's config is small (paths, ids, settings), never the data"
        self.summary = _Summary()
        self.logged: list[dict] = []
        self.finished = False
        for name in ("log_artifact", "save", "use_artifact"):
            setattr(self, name, _forbidden(f"Run.{name}"))

    def log(self, values: dict, *args, **kwargs) -> None:
        assert_scalars(values, "run.log")
        self.logged.append(dict(values))

    def define_metric(self, *args, **kwargs) -> None:
        pass

    def finish(self, *args, **kwargs) -> None:
        self.finished = True


class _Forbidden(types.SimpleNamespace):
    def __getattr__(self, name):
        return _forbidden(f"plot.{name}")


class _Api:
    def __init__(self, module: StrictWandb):
        self.module = module

    def run(self, path: str):
        held = self.module.held.get(path.rsplit("/", 1)[-1])
        if held is None:
            raise ValueError(f"no run {path}")   # as wandb's CommError for a run that does not exist yet
        return SimpleNamespace(summary=dict(held), config={}, tags=[])

    def runs(self, *args, **kwargs):
        return []


class StrictWandb(types.ModuleType):
    """`held`: run id -> the summary W&B already holds for it (a resumed run); empty = every run is new."""

    def __init__(self, held: dict[str, dict] | None = None):
        super().__init__("wandb")
        self.held = dict(held or {})
        self.runs: list[StrictRun] = []
        for name in FORBIDDEN:
            setattr(self, name, _forbidden(name))
        self.plot = _Forbidden()
        self.Settings = lambda **kwargs: SimpleNamespace(**kwargs)
        self.Api = lambda **kwargs: _Api(self)

    def init(self, **kwargs) -> StrictRun:
        run = StrictRun(self, kwargs)
        self.runs.append(run)
        return run

    def log(self, values: dict, *args, **kwargs) -> None:
        raise AssertionError("module-level wandb.log: log through the run")

    def logged_values(self) -> list[dict]:
        return [row for run in self.runs for row in run.logged]
