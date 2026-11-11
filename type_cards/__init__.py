"""Compat shim: the type cards are `sim2real.cards` since 2026-11-10 (src/sim2real/cards/).

`import type_cards.registry`, `from type_cards import coverage as cov`, `python -m type_cards.report freeze ...` and every other old
spelling keep working: each `type_cards.<name>` IS the module `sim2real.cards.<name>` (the same object, so module state, caches and
classes are shared, never a second copy). New code imports `sim2real.cards`. type_cards/tests stays here, unchanged, as the ruler that
held the move (decision: docs/decision-package-layers-2026-11-10.md).

WHY a shim and not a rename of every caller (Zach, 2026-11-10, proposal 2 step 3): the site, app, tools, sysid and 30-odd documented
commands import type_cards, and the cards' contract is additive-only; the move must change no caller.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path

_NEW = "sim2real.cards"
_SRC = Path(__file__).resolve().parents[1] / "src"

# WHY put this checkout's src/ first: a caller that has the repo on sys.path but not the package installed (the site build under
# `uv run --no-project`, sysid under bam_rack_twin's venv) must get this checkout's sim2real.cards, never another checkout's.
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

importlib.import_module(_NEW)


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """type_cards.<name> -> the already-imported sim2real.cards.<name> (type_cards.tests excepted: it lives here)."""

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(__name__ + ".") or fullname.startswith(__name__ + ".tests"):
            return None
        real = _NEW + fullname[len(__name__):]
        real_spec = importlib.util.find_spec(real)
        if real_spec is None:
            return None
        spec = importlib.util.spec_from_loader(fullname, self, origin=real_spec.origin,
                                               is_package=real_spec.submodule_search_locations is not None)
        spec.has_location = real_spec.has_location  # so `python -m type_cards.x` gets the real __file__
        if real_spec.submodule_search_locations is not None:
            spec.submodule_search_locations = list(real_spec.submodule_search_locations)
        return spec

    def create_module(self, spec):
        module = importlib.import_module(_NEW + spec.name[len(__name__):])
        self._specs = getattr(self, "_specs", {})
        self._specs[spec.name] = module.__spec__
        return module

    def exec_module(self, module):
        # the import system stamps the alias's spec on the module it was handed; give the real module its own back
        real_spec = self._specs.pop(module.__spec__.name, None)
        if real_spec is not None:
            module.__spec__ = real_spec

    def get_code(self, fullname):
        """`python -m type_cards.<name>`: run the real module's code as __main__."""
        real = _NEW + fullname[len(__name__):]
        real_spec = importlib.util.find_spec(real)
        return real_spec.loader.get_code(real)


if not any(isinstance(finder, _Alias) for finder in sys.meta_path):
    sys.meta_path.insert(0, _Alias())
