"""The site's shared UI pieces, used by more than one page: the entity tree (a deployment's tree on the left, as RobotDx draws its device
tree) and the left filter bar (data-ui's rail in the workbench's left column).

WHY one module (the coordinator, 2026-11-07: the deployments pages and the run page both put a tree on the left; Zach, 2026-11-06: "On
the left should be like an entity tree"; 2026-10-29: "The filter bar should always be on the left hand side"): one tree markup, one
stylesheet (static/ui-shared.css), one remembered width, so every page with a left column reads the same.

    entity_tree(nodes, current, href, ...)   a <nav> of one tree: every node a link, the current one marked (aria-current), the first
                                             levels and the path to the current node open (native <details>, no script needed); on a
                                             phone the whole tree is one closed disclosure, so the page's answer comes first
    filter_bar(views_id)                     data-ui's rail (<data-facets>) for a <data-views>, for the workbench's left column
    chip(text, tone, title)                  a small word: a kind, a tag (tone "real" is data-ui's series 1, blue; "sim" series 2, orange)
    head()                                   the stylesheet's <link>, for a page's extra_head
    status_tree(nodes, selected, ...)        a tree that picks a level in place (the run page): RobotDx's device tree with a status dot,
                                             a one-line summary and a muted end per node, search, collapse and expand all, ?entity= deep
                                             links (static/ui-shared.js); a closed disclosure on a phone too
    dot(level, why)                          a status dot: ok, warning, error filled, unknown a hollow ring, always with its word
    record_page(catalog, kind, ..., aside)   a record's page in the two panes below: the workbench's record on the right, `aside` left

Where they go: the workbench shell's two panes (catalog_workbench.shell.page(aside=...)). Its left column is resizable and its width
remembered (data-resizable: data-ui's resize, CONTRACT §11), each pane scrolls on its own, and below 768 px the column stacks above
the page. Stdlib only.
"""

from __future__ import annotations

from collections.abc import Callable

from catalog_workbench.html import e

STYLESHEET = "/static/ui-shared.css"

# 16 px line icons, one per level of a tree: a type (type_cards domain v3) or a structural word. Drawn in the text colour (stroke).
_ICON = {
    "deployment": '<rect x="2" y="3" width="12" height="10" rx="1.2"/><path d="M2 7h12M6 7v6"/>',
    "adapter": '<path d="M6 2.5v3M10 2.5v3M4.5 5.5h7v2.5a3.5 3.5 0 01-7 0zM8 11.5v2.5"/>',
    "station": '<circle cx="8" cy="8" r="5.5"/><circle cx="8" cy="8" r="1.8"/>',
    "integrated_servo": '<circle cx="8" cy="8" r="5.5"/><circle cx="8" cy="8" r="1.8"/>',
    "bldc_motor": '<rect x="2" y="4" width="9.5" height="8" rx="1.5"/><path d="M11.5 8h3M5 6.5v3M8 6.5v3"/>',
    "foc_controller": '<rect x="2.5" y="2.5" width="11" height="11" rx="1"/><rect x="6" y="6" width="4" height="4"/>',
    "gearbox": '<circle cx="8" cy="8" r="3"/><path d="M8 1.8v2.4M8 11.8v2.4M1.8 8h2.4M11.8 8h2.4M3.6 3.6l1.7 1.7M10.7 10.7l1.7 1.7M3.6 12.4l1.7-1.7M10.7 5.3l1.7-1.7"/>',
    "encoder": '<circle cx="8" cy="8" r="5.5"/><path d="M8 8l3.6-2.4M8 2.5v1.5"/>',
    "camera": '<rect x="1.5" y="4.5" width="13" height="8.5" rx="1.5"/><circle cx="8" cy="8.75" r="2.4"/><path d="M5.5 4.5l1-2h3l1 2"/>',
    "depth_camera": '<rect x="1.5" y="5" width="13" height="6.5" rx="1.5"/><circle cx="5" cy="8.25" r="1.6"/><circle cx="11" cy="8.25" r="1.6"/>',
    "hyperspectral_camera": '<rect x="1.5" y="4.5" width="13" height="7" rx="1.5"/><path d="M4 13.5h8M5 8h6"/>',
    "rigid_body_chain": '<path d="M2.5 14h6M5.5 14V9.5l4.5-5 3.5 2"/><circle cx="5.5" cy="9.5" r="1.3"/><circle cx="10" cy="4.5" r="1.3"/>',
    "gripper": '<path d="M8 1.5v5M4.5 6.5h7M4.5 6.5v4.5l1.5 2.5M11.5 6.5v4.5l-1.5 2.5"/>',
    "conveyor": '<rect x="1.5" y="6" width="13" height="4.5" rx="2.25"/><circle cx="4" cy="8.25" r="1"/><circle cx="12" cy="8.25" r="1"/>',
    "assembly": '<rect x="2" y="2" width="5.5" height="5.5" rx="1"/><rect x="8.5" y="8.5" width="5.5" height="5.5" rx="1"/><path d="M7.5 4.75h3.25V8.5"/>',
    "mount": '<path d="M2 13.5h12M4 13.5V8.5h8v5M6 8.5v-4h4v4"/>',
    "tool": '<path d="M3 13l6-6M8.5 7.5l2-4.5 2.5 2.5-4.5 2"/>',
    "part": '<circle cx="8" cy="8" r="2.5"/>',
}


def icon(word: str | None) -> str:
    """The line icon of a type or a structural word (a dot for any other)."""
    return f'<svg viewBox="0 0 16 16" aria-hidden="true">{_ICON.get(word or "", _ICON["part"])}</svg>'


def icon_word(node: dict) -> str:
    """A node's icon: its type when it has one (a station is an integrated servo), else its structural word."""
    return node.get("entity_type") or node.get("structural") or "part"


def head() -> str:
    return f'<link rel="stylesheet" href="{STYLESHEET}">\n'


def chip(text: str, tone: str = "", title: str = "") -> str:
    tip = f' title="{e(title)}"' if title else ""
    return f'<span class="s2r-chip{" s2r-chip-" + e(tone) if tone else ""}"{tip}>{e(text)}</span>'


def filter_bar(views_id: str, noscript: str = "The filters need JavaScript; everything is listed on the right.") -> str:
    """data-ui's rail for the <data-views> `views_id` (its .base's `facets:`), for the workbench's left column. WHY no width of its own:
    a rail inside a host panel that is itself [data-resizable] gets no handle (data-ui CONTRACT §11): the column is what resizes."""
    return f'<data-facets for="{e(views_id)}" class="rail"></data-facets>\n<noscript><p>{e(noscript)}</p></noscript>'


def entity_tree(nodes: list[dict], current: str, href: Callable[[dict], str], *, count: Callable[[dict], str] | None = None,
                label: Callable[[dict], str] | None = None, heading: str = "Deployment tree", open_levels: int = 2) -> str:
    """One tree's <nav>: `nodes` are its rows (id, parent, title; entity_type / structural pick the icon) in display order, a node's
    children in the order they appear. Every node is a link (`href(node)`); `current` is marked aria-current="page". Open: the first
    `open_levels` levels (counted from the tree's own top, so a subset tree starting deep opens the same way) and every node on the path
    to the current one. `count(node)` is the muted number at a row's end (its runs), `label(node)` its words (default its title; the
    full title stays one hover away when the column cuts it)."""
    ids = {n["id"] for n in nodes}
    kids: dict = {}
    for n in nodes:
        kids.setdefault(n["parent"] if n["parent"] in ids else None, []).append(n)
    by_id = {n["id"]: n for n in nodes}
    path, at = set(), by_id.get(current)
    while at is not None:
        path.add(at["id"])
        at = by_id.get(at["parent"])

    def item(n: dict, level: int) -> str:
        words = label(n) if label else n["title"]
        mark = ' aria-current="page"' if n["id"] == current else ""
        number = count(n) if count else ""
        row = (f'<a href="{e(href(n))}" data-node="{e(n["id"])}"{mark}><span class="s2r-ei">{icon(icon_word(n))}</span>'
               f'<span class="s2r-et" title="{e(n["title"])}">{e(words)}</span></a>' + (f'<span class="s2r-en">{e(number)}</span>' if number else ""))
        children = kids.get(n["id"], [])
        if not children:
            return f'<li data-level="{level}"><div class="s2r-erow">{row}</div></li>'
        opened = " open" if level < open_levels or n["id"] in path else ""
        return (f'<li data-level="{level}"><details{opened}><summary>{row}</summary>'
                f'<ul>{"".join(item(c, level + 1) for c in children)}</ul></details></li>')

    tree = "".join(item(n, 0) for n in kids.get(None, []))
    # WHY a disclosure closed on a phone (the workbench stacks the column above the page under 768 px, as data-ui's rail is a closed
    # disclosure under 700 px): the page's answer comes first, the tree one tap away
    return (f'<nav class="s2r-etree" aria-label="{e(heading)}"><details class="s2r-etree-box" open><summary class="s2r-etree-h">{e(heading)}</summary>'
            f'<ul class="s2r-etree-l">{tree}</ul></details>'
            "<script>(function(){var d=document.currentScript.previousElementSibling;try{if(d&&matchMedia('(max-width: 767px)').matches)d.open=false}"
            "catch(x){}})()</script></nav>")


# --- the status tree and a record in two panes (the run-page lane, 2026-11-07) --------------------------------------------------------
# WHY a second tree beside entity_tree's links: the run page shows every level of one run in place (the right pane switches to the picked
# node's dashboard, the URL names it), and the brief for it (Zach, 2026-11-06, his RobotDx device tree as the picture: "On the left should be
# like an entity tree ... and then on the page what shows is the standard dashboard for that level") asks for RobotDx's tree: icons, a status
# dot per node, search, collapse and expand, a one-line summary per node. Its root is .s2r-tree, so entity_tree's .s2r-etree rules never
# touch it; the icons are the same (icon()). Making the two one component is a follow-up. Its behaviour is static/ui-shared.js.

RUN_STYLESHEET = "/static/run-page.css"
LEVEL_WORDS = ("ok", "warning", "error", "unknown")  # type_cards domain v3's LEVELS
TWISTY = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 4l4 4-4 4"/></svg>'
COLLAPSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 13.5L8 10l3.5 3.5M4.5 2.5L8 6l3.5-3.5"/></svg>'
EXPAND = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 10L8 13.5 11.5 10M4.5 6L8 2.5 11.5 6"/></svg>'
FIND = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>'
TREE = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="2" width="4.5" height="3.5" rx=".8"/><rect x="9.5" y="7" width="4.5" height="3" rx=".8"/><rect x="9.5" y="11.5" width="4.5" height="3" rx=".8"/><path d="M4.25 5.5v7h5.25M4.25 8.5h5.25"/></svg>'


def dot(level: str | None, why: str = "") -> str:
    """A node's status dot: ok, warning, error filled in their tones; unknown a hollow ring (RobotDx's "not heard"), never a guess."""
    word = level if level in LEVEL_WORDS else "unknown"
    tip = f"{word} in this run" + (f": {why}" if why else "")
    return f'<span class="s2r-dot s2r-dot-{word}" role="img" aria-label="{e(word)}" title="{e(tip)}"></span>'


def status_tree(nodes: list[dict], *, selected: str, href: Callable[[dict], str], name: Callable[[dict], str], line: Callable[[dict], str],
                kind: Callable[[dict], str], level: Callable[[dict], str], why: Callable[[dict], str] | None = None,
                meta: Callable[[dict], str] | None = None, find: Callable[[dict], str] | None = None, key: str = "",
                heading: str = "Entities", section: str = "", summary: str = "", more: str = "") -> str:
    """A tree of `nodes` (rows with id, parent, title; entity_type / structural pick the icon), in display order (a node's children in
    the order they appear), as an ARIA tree: each node a row of its twisty, its dot (`level(node)`, `why(node)` its tooltip), its icon, its
    name (`name(node)`, the full title one hover away), its one-line summary (`line(node)`) and a muted end (`meta(node)`); `selected` is
    the node shown first, `href(node)` its deep link. The bar holds the tree's name, Collapse all and Expand all, then the search box (it
    matches `find(node)`, default the name, title, id and type) and the `section` line with its `summary` on the right; `more` closes it
    (what the tree leaves out). `key` names the tree's remembered open rows."""
    ids = {n["id"] for n in nodes}
    kids: dict = {}
    for n in nodes:
        kids.setdefault(n.get("parent") if n.get("parent") in ids else None, []).append(n)

    def item(n: dict, depth: int) -> str:
        children = kids.get(n["id"], [])
        title, words, text = n.get("title") or n["id"], name(n), line(n)
        haystack = find(n) if find else " ".join(str(x) for x in (words, title, n["id"], n.get("entity_title") or "", n.get("structural") or "") if x)
        end = meta(n) if meta else ""
        twisty = f'<span class="s2r-tree-tw" data-etree-toggle>{TWISTY}</span>' if children else '<span class="s2r-tree-tw"></span>'
        row = (f'<div class="s2r-etree-row">{twisty}{dot(level(n), why(n) if why else "")}<span class="s2r-tree-ic">{icon(icon_word(n))}</span>'
               f'<a class="s2r-tree-name" href="{e(href(n))}" title="{e(title)}">{e(words)}</a>'
               f'<span class="s2r-etree-line" title="{e(text)}">{e(text)}</span>' + (f'<span class="s2r-tree-meta">{e(end)}</span>' if end else "") + "</div>")
        expanded = ' aria-expanded="true"' if children else ""
        group = f'<ul role="group">{"".join(item(c, depth + 1) for c in children)}</ul>' if children else ""
        return (f'<li role="treeitem" data-entity="{e(n["id"])}" data-entity-kind="{e(kind(n))}" data-level="{e(level(n) if level(n) in LEVEL_WORDS else "unknown")}" '
                f'aria-level="{depth}" aria-selected="{"true" if n["id"] == selected else "false"}"{expanded} data-find="{e(haystack.lower())}">{row}{group}</li>')

    rows = "".join(item(n, 1) for n in kids.get(None, []))
    # WHY a disclosure closed on a phone, as entity_tree's (the workbench stacks the column above the page under 768 px): the level's
    # answer comes first, the tree one tap away; on a wider screen its summary is hidden and the tree always open
    return f"""<div class="s2r-tree" data-etree="{e(key)}" data-default="{e(selected)}">
<details class="s2r-tree-box" open><summary class="s2r-tree-phone">{TREE}{e(heading)} <small>{e(summary)}</small></summary>
<div class="s2r-tree-bar"><span class="s2r-tree-title">{TREE}{e(heading)}</span><span class="s2r-tree-tools"><button type="button" class="s2r-tree-btn" data-etree-collapse title="Collapse all" aria-label="Collapse all">{COLLAPSE}</button><button type="button" class="s2r-tree-btn" data-etree-expand title="Expand all" aria-label="Expand all">{EXPAND}</button></span></div>
<label class="s2r-tree-find">{FIND}<input type="search" data-etree-search placeholder="Search entities, ids, types…" aria-label="Search entities" autocomplete="off"></label>
<p class="s2r-tree-sec"><span>{e(section)}</span><span class="s2r-tree-sum">{e(summary)}</span></p>
<ul class="s2r-tree-list" role="tree" aria-label="{e(section or heading)}">{rows}</ul>
<p class="s2r-tree-none" data-etree-none hidden>No entity matches.</p>
{more}
</details><script>(function(){{var d=document.currentScript.previousElementSibling;try{{if(d&&matchMedia('(max-width: 767px)').matches)d.open=false}}catch(x){{}}}})()</script>
</div>"""


# The workbench's left column as its shell writes it (catalog_workbench.shell.page(aside=...)): named here so a record's tree gets its own
# name and its own remembered width (data-ui's resize keys the width by data-resizable-key, else the id), never the filter rail's.
WORKBENCH_ASIDE = '<aside class="fcol" id="filter" aria-label="Filters" data-resizable="right"'


def record_page(catalog, kind, site, record, aside: str, *, label: str = "Entities", aside_id: str = "entities", key: str = "s2r-entities",
                extra_head: str = "") -> str:
    """A record's page in the workbench's two panes: `aside` in the left column (resizable, its width remembered under `key`; on a phone
    stacked above), the record itself (the workbench's record_body: header, tabs, panels) on the right, each pane its own scroll. The same
    call the workbench's record_page makes, plus the column. WHY not the workbench's record writer: its record page has no left column, and
    a run's entity tree sits left of every level of the run (Zach, 2026-11-06)."""
    from catalog_workbench.html import breadcrumb  # noqa: PLC0415
    from catalog_workbench.record import record_body  # noqa: PLC0415
    from catalog_workbench.shell import page  # noqa: PLC0415

    back = kind.back(site, record) if kind.back else None
    html = page(catalog, site, f"{kind.title(record)}: {catalog.brand.name}", kind.url(record), record_body(kind, site, record), kind.key,
                description=kind.description(site, record) if kind.description else "", scripts=kind.scripts,
                trail=breadcrumb(kind.crumbs(site, record), back=back), aside=aside, data_ui=kind.data_ui, extra_head=head() + extra_head)
    if html.count(WORKBENCH_ASIDE) != 1:
        raise ValueError(f"the workbench's left column is no longer {WORKBENCH_ASIDE!r}: re-read catalog_workbench.shell.page")
    return html.replace(WORKBENCH_ASIDE, f'<aside class="fcol s2r-aside" id="{e(aside_id)}" aria-label="{e(label)}" data-resizable="right" '
                                         f'data-resizable-key="{e(key)}"', 1)
