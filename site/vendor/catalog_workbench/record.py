"""The record page: the catalog's header, then its tabs, one panel each (PEP 0003 §6, the shared record frame).

WHY tabs (Zach, 2026-10-25: "he will put a LOT on each part… tabs give separation of concerns, one concern at a
time"). Each tab is a panel; a tab's link is #<key>, and an older section anchor inside a panel still lands, because
the catalog's site script opens the panel that holds it. Without JavaScript every panel shows, stacked, so tests,
crawlers and llms readers see everything. An empty tab is either listed in "Nothing recorded yet" or, with
empty="hide", has no tab, no panel and no place in that line.
"""

from __future__ import annotations

from .contract import Catalog, Kind
from .html import breadcrumb, e
from .shell import page


def record_body(kind: Kind, site, record) -> str:
    """The page's content: the header block, the tab list with its "Nothing recorded yet" line, the panels."""
    tabs, empty, blocks = [], [], []
    for tab in kind.tabs:
        panel_id = tab.panel_id or f"tab-{tab.key}"
        if tab.has is None or tab.has(site, record):
            tabs.append(f'<a role="tab" id="t-{tab.key}" href="#{tab.key}" aria-controls="{panel_id}">{e(tab.label)}</a>')
        elif tab.empty == "hide":
            continue
        else:
            empty.append(f'<a href="{e("#" + tab.key)}">{e(tab.label)}</a>')
        blocks.append(f'<div class="panel" role="tabpanel" id="{panel_id}" data-tab="{tab.key}" aria-label="{e(tab.label)}">\n'
                      f'{tab.body(site, record)}\n</div>')
    nothing = f'<p class="nothing">Nothing recorded yet: {" · ".join(empty)}.</p>' if empty else ""
    sections = f"{kind.label} sections"
    return f"""<div class="phead">
{kind.header(site, record)}
</div>
<nav class="tabs" aria-label="{e(sections)}"><div role="tablist" aria-label="{e(sections)}">{"".join(tabs)}</div>{nothing}</nav>
<div class="panels">
{chr(10).join(blocks)}
</div>"""


def record_page(catalog: Catalog, kind: Kind, site, record) -> str:
    """One record's whole page in the catalog's shell."""
    back = kind.back(site, record) if kind.back else None
    return page(catalog, site, f"{kind.title(record)}: {catalog.brand.name}", kind.url(record), record_body(kind, site, record),
                kind.key, description=kind.description(site, record) if kind.description else "", scripts=kind.scripts,
                trail=breadcrumb(kind.crumbs(site, record), back=back), data_ui=kind.data_ui)
