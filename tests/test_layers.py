"""The sim2real package's folders, by stability: each may import only the folders to its left.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_layers.py

    metrics/ -> schedule/ -> fit/ -> sim/ -> models/ -> cards/
    most stable                                   churns most

Zach, 2026-11-10 ("Sim2Real as a Pure Library on robot_msgs", his picks): "nothing stable can import something that churns". A new
servo model lands in models/ without touching metrics/; a changed gate target is a cards/ data edit. Decision record:
docs/decision-package-layers-2026-11-10.md. Written before the package; the checker is held red on planted violations below, so a
rule that silently passes everything cannot pass here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "sim2real"
LAYERS = ("metrics", "schedule", "fit", "sim", "models", "cards")


def imported_layers(path: Path, root: Path) -> list[tuple[str, int]]:
    """The sim2real layers a file imports (absolute `sim2real.<layer>` or relative), each with its line."""
    rel = path.relative_to(root).with_suffix("").parts  # e.g. ("metrics", "coverage") or ("metrics", "__init__")
    package = list(rel[:-1])  # the file's own package, as relative imports resolve it
    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        targets: list[list[str]] = []
        if isinstance(node, ast.Import):
            targets = [alias.name.split(".") for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level - 1 > len(package):
                    continue  # above sim2real: not a layer
                base = package[: len(package) - (node.level - 1)]
                module = base + (node.module.split(".") if node.module else [])
                if node.module is None:  # `from . import x` / `from .. import fit`
                    targets = [module + [alias.name] for alias in node.names]
                else:
                    targets = [module]
                targets = [["sim2real", *t] for t in targets]
            elif node.module:
                parts = node.module.split(".")
                targets = [parts + [alias.name] for alias in node.names] if parts == ["sim2real"] else [parts]
        for parts in targets:
            if len(parts) >= 2 and parts[0] == "sim2real" and parts[1] in LAYERS:
                found.append((parts[1], node.lineno))
    return found


def violations(root: Path) -> list[str]:
    """Every import of a layer to the right of the importing file's own layer, as 'file:line imports layer'."""
    out = []
    for layer in LAYERS:
        for path in sorted((root / layer).rglob("*.py")):
            if "tests" in path.relative_to(root).parts:
                continue  # a layer's own tests may reach anything
            for target, line in imported_layers(path, root):
                if LAYERS.index(target) > LAYERS.index(layer):
                    out.append(f"{path.relative_to(root)}:{line} imports {target}")
    return out


def test_every_layer_is_a_package():
    assert (PACKAGE / "__init__.py").is_file()
    for layer in LAYERS:
        assert (PACKAGE / layer / "__init__.py").is_file(), layer


def test_no_layer_imports_one_to_its_right():
    assert violations(PACKAGE) == []


def test_the_package_root_imports_no_layer():
    # WHY: `import sim2real.metrics` runs sim2real/__init__.py first; if that imported cards, the stable end would load the churning one
    assert imported_layers(PACKAGE / "__init__.py", PACKAGE) == []


@pytest.mark.parametrize(
    ("layer", "source", "caught"),
    [
        ("metrics", "from sim2real.cards import registry\n", "cards"),
        ("metrics", "import sim2real.models.servo\n", "models"),
        ("schedule", "from sim2real import fit\n", "fit"),
        ("fit", "from ..sim import plant\n", "sim"),
        ("sim", "from sim2real.models import x as y\n", "models"),
        ("models", "def f():\n    from sim2real.cards.coverage import binned\n", "cards"),
        ("cards", "from sim2real.metrics import x\nfrom ..models import y\n", None),  # leftward: allowed
        ("fit", "from .least_squares import solve\nfrom ..metrics import z\n", None),  # own layer and leftward: allowed
    ],
)
def test_the_checker_catches_a_planted_violation(tmp_path, layer, source, caught):
    root = tmp_path / "sim2real"
    for name in LAYERS:
        (root / name).mkdir(parents=True)
        (root / name / "__init__.py").write_text("")
    (root / "__init__.py").write_text("")
    (root / layer / "planted.py").write_text(source)
    found = violations(root)
    if caught is None:
        assert found == []
    else:
        assert found and all(f.startswith(f"{layer}/planted.py:") and f.endswith(f"imports {caught}") for f in found), found
