"""sim2real: how close each digital twin is to its real hardware, as a library on robot_msgs.

Folders by stability; each imports only the folders to its left (tests/test_layers.py enforces it):

    metrics/ -> schedule/ -> fit/ -> sim/ -> models/ -> cards/
    most stable                                   churns most

WHY this order (Zach, 2026-11-10, proposal 2's picks): nothing stable can import something that churns. A new servo model lands in
models/ without touching metrics/; a changed gate target is a cards/ data edit. Decision: docs/decision-package-layers-2026-11-10.md.
The site, dashboards and catalog are app folders beside this package, not in it. This file imports no layer, so importing
sim2real.metrics never loads cards.
"""

FRONT_DOOR = ("Twin", "load", "describe")


def __getattr__(name: str):
    """The front door, loaded on first use (sim2real.Twin.load(...), sim2real.load(...), sim2real.describe(...); src/sim2real/twin.py).
    WHY lazy: `import sim2real` must load no layer; twin.py imports cards and metrics."""
    if name in FRONT_DOOR:
        from . import twin  # noqa: PLC0415

        return getattr(twin, name)
    raise AttributeError(f"module 'sim2real' has no attribute {name!r}")
