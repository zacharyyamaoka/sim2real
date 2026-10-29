"""data-ui wiring every catalog shares: the kit's module tag, the .base property check, a view's old links, the rows'
JSON. The kit itself is vendored by each host (its tools/vendor_data_ui.py) and published at DATA_UI."""

from __future__ import annotations

import json
import pathlib

from .html import e
from .writer import PagesError

DATA_UI = "/static/data-ui/"  # the vendored kit, as each host publishes it


def data_ui_head(preludes=()) -> str:
    """The kit's module, for a page that has a <data-views> (its stylesheet is in the head, before site.css, so the
    site's rules win). WHY after site.js: site.js sets the start view from an old ?view= link before the element
    upgrades (deferred and module scripts run in document order). A reader's frame is the kit's own pick (View
    settings › Frame, data-ui CONTRACT §13)."""
    before = "".join(f'<script type="module" src="{src}"></script>\n' for src in preludes)  # a catalog's own, before the kit
    return before + f'<script type="module" src="{DATA_UI}data-ui.js"></script>\n'


def base_properties(doc) -> set[str]:
    """Every property a .base file names (facets, order, sort, groups, images, captions, hover, chart fields, guides,
    compare directions, display and summaries); filter expressions are data-ui's to check."""
    names = set()

    def field_of(value):
        if isinstance(value, dict):
            if isinstance(value.get("field"), str):
                names.add(value["field"])
            for item in value.values():
                field_of(item)
        elif isinstance(value, list):
            for item in value:
                field_of(item)

    for facet in doc.get("facets") or []:
        names.add(facet if isinstance(facet, str) else facet.get("property"))
    for view in doc.get("views") or []:
        names.update(view.get("order") or [])
        names.update(rule.get("property") for rule in view.get("sort") or [])
        for grouping in ("groupBy", "subGroupBy"):
            if view.get(grouping):
                names.add(view[grouping].get("property"))
        names.update(view.get(key) for key in ("image", "media") if view.get(key))
        names.update(view.get("caption") or [])
        hover = view.get("hover") or {}
        names.update(hover.get(key) for key in ("image", "title") if hover.get(key))
        names.update(hover.get("fields") or [])
        field_of((view.get("chart") or {}).get("encoding"))
        for guide in view.get("guides") or []:
            if isinstance(guide.get("envelope"), str):
                names.add(guide["envelope"])
        names.update(((view.get("compare") or {}).get("better") or {}).keys())
        for key in ("display", "summaries"):
            names.update((view.get(key) or {}).keys())
    # how a record opens (data-ui CONTRACT §13): `open: {url: <property>}` names the property holding its page's URL
    for opener in [doc.get("open")] + [view.get("open") for view in doc.get("views") or []]:
        if isinstance(opener, dict) and isinstance(opener.get("url"), str):
            names.add(opener["url"])
    return {name for name in names if name}


def read_base(reader, path: pathlib.Path, root: pathlib.Path, properties: dict) -> tuple[str, dict]:
    """(text, document) of a committed .base file, read with data-ui's own reader (`reader`, the kit's data_ui_base);
    a property the rows lack stops the build, so a preset can never name a column that is not there. Errors name the
    file relative to `root`, the catalog's repository."""
    text = path.read_text(encoding="utf-8")
    try:
        doc = reader.loads(text)
    except reader.BaseSyntaxError as error:
        raise PagesError(f"{path.relative_to(root)}: {error}") from error
    if not doc.get("views"):
        raise PagesError(f"{path.relative_to(root)} has no views")
    unknown = sorted(base_properties(doc) - set(properties) - {"id"})
    if unknown:
        raise PagesError(f"{path.relative_to(root)} names properties its rows do not have: {', '.join(unknown)}")
    return text, doc


def old_views(doc) -> dict:
    """{old ?view= value or 'cmp': the preset it now means}: rows, gallery and chart (round 3's three views) and a part
    page's 'Compare with other …' link (?cmp=<id>) open the first preset of the matching type (static/site.js)."""
    first = {}
    for view in doc["views"]:
        first.setdefault(view.get("type", "table"), view["name"])
    return {old: first[kind] for old, kind in (("rows", "table"), ("gallery", "cards"), ("chart", "chart"), ("cmp", "compare"))
            if kind in first}


def data_ui_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def views_element(element_id: str, src: str, label: str, inner: str, frame: str | None = None, attrs: str = "",
                  old: dict | None = None) -> str:
    """A list's <data-views>: its .base (`src`), the frame a first visit gets (data-ui CONTRACT §12), the catalog's
    toolbar attributes, the old ?view= values it still answers (data-old-views) and `inner`, the reading without
    JavaScript (a server-drawn table) that the kit replaces when it upgrades."""
    frame_attr = f' frame="{frame}"' if frame else ""
    attrs_text = f" {attrs}" if attrs else ""
    old_attr = (f' data-old-views="{e(json.dumps(old, ensure_ascii=False, separators=(",", ":"), allow_nan=False))}"'
                if old is not None else "")
    return (f'<data-views id="{e(element_id)}" src="{e(src)}"{frame_attr} aria-label="{e(label)}"{attrs_text}{old_attr}>\n'
            f"{inner}\n</data-views>")
