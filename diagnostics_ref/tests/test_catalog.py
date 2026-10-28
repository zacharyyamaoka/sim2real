"""The catalog checks itself, and every quote marked 'his' is found verbatim in the vault file it cites."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from robotdx.diagnostics import REGISTRY
from robotdx.diagnostics.catalog import ENTRIES, PARTS, PRIMITIVES, problems

VAULT = Path("/home/bam/zach_brain")
_WHERE = re.compile(r"^(?:f?\{?)?(.*?\.md)")


def test_the_catalog_is_well_formed():
    assert problems() == []
    assert set(PARTS) == {entry.part for entry in ENTRIES}  # every part type has entries


def test_implemented_primitives_are_exactly_the_registered_stock():
    implemented = {name for name, p in PRIMITIVES.items() if p.implemented}
    assert implemented == {name for name in REGISTRY if name.startswith("stock.")}
    for name in implemented:
        spec = REGISTRY[name]
        assert (spec.hint, spec.emits, spec.family) == (PRIMITIVES[name].hint, PRIMITIVES[name].emits, PRIMITIVES[name].family), name


@pytest.mark.skipif(not VAULT.is_dir(), reason="vault not on this machine")
def test_every_his_quote_is_verbatim_at_its_source():
    checked = 0
    for entry in ENTRIES:
        if entry.prov != "his":
            continue
        match = _WHERE.match(entry.where)
        assert match, entry.id
        text = (VAULT / match.group(1)).read_text()
        assert entry.quote.rstrip(".…") in text, (entry.id, entry.where)
        checked += 1
    assert checked == sum(entry.prov == "his" for entry in ENTRIES) >= 40
