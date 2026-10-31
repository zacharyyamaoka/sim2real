"""The home page's frame: "Choose a …" on the left (a resizable column), every group on the right as tiles, each with a
small picture (McMaster-Carr's home, Zach 2026-10-25). The catalog draws the pictures and the sections below.

WHY no description above the tiles (Zach's pick of 2026-10-26, layout proposal 1): McMaster's home opens straight on
Choose a category; a catalog puts its description under the tiles.
"""

from __future__ import annotations

from dataclasses import dataclass

from .html import e


@dataclass(frozen=True)
class Group:
    """One group of tiles on the home page, and its line in the Choose column."""
    key: str           # its anchor, #c-<key>
    label: str
    href: str          # the group's own list page
    count: int
    tiles: tuple[str, ...]   # tile() and more_tile() items, in order


def tile(href: str, name: str, count: int, picture: str) -> str:
    """One tile: the catalog's picture markup, its name and its count."""
    return (f'<li><a class="tile" href="{e(href)}">{picture}'
            f'<span class="tn">{e(name)}</span> <span class="n">({count:,})</span></a></li>')


def more_tile(href: str, text: str, count: int) -> str:
    """The last tile of a group that shows only its first few: it opens the rest."""
    return (f'<li><a class="tile more" href="{e(href)}"><span class="tn">{e(text)}</span> '
            f'<span class="n">({count:,})</span></a></li>')


def tile_home(title: str, choose: str, groups, not_yet: str = "") -> str:
    """The top of the home page: a visually hidden title, the Choose column (drag to resize, remembered as "choose")
    and the groups of tiles. `not_yet` is the catalog's line under the column (its groups with nothing in them)."""
    items = "\n".join(f'<li><a href="#c-{e(group.key)}">{e(group.label)}</a> <span class="n">({group.count:,})</span></li>'
                      for group in groups)
    sections = "".join(f'<section class="group" id="c-{e(group.key)}"><h2 class="gh"><a href="{e(group.href)}">{e(group.label)}</a> '
                       f'<span class="n">({group.count:,})</span></h2><ul class="tiles">{"".join(group.tiles)}</ul></section>'
                       for group in groups)
    return f"""<h1 class="sr">{e(title)}</h1>
<div class="home">
<nav class="choose" aria-label="{e(choose)}" data-resizable="right" data-resizable-key="choose" data-resizable-min="160" data-resizable-max="420">
<h2>{e(choose)}</h2>
<ul>
{items}
</ul>
{not_yet}
</nav>
<div class="groups">
{sections}
</div>
</div>"""
