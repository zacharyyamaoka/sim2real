"""W&B's tag limit is 64 BYTES of UTF-8, not 64 characters: '·' takes two, and the 64-character tags _tag made were refused
("invalid tag ... must be between 1 and 64 characters", logging pass 7, 2026-11-13)."""

from __future__ import annotations


def test_a_shortened_tag_fits_64_utf8_bytes():
    from sim2real.tracking.homing import _tag

    name = "recover_first(fed)+single_touch_c1seek+gff · real form · end group +22 % · ff nominal"
    tag = _tag(name)
    assert len(tag.encode("utf-8")) <= 64
    assert _tag("short · name") == "short · name"
    assert _tag(name) != _tag(name.replace("nominal", "+25 %"))
