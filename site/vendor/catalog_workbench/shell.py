"""The shell every page shares: the bar (wordmark, one centred search with its menu, the catalog's quick links,
Account ▾), the trail and the one or two panes (PEP 0003 §8). Everything a catalog says is a setting on its Catalog
(contract.py), so one frame serves every catalog.
"""

from __future__ import annotations

import json

from .contract import Catalog
from .data_ui import DATA_UI, data_ui_head
from .html import e

ICON = {
    "search": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10.4 10.4l3.6 3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    "user": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="5.6" r="2.8" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M2.8 14c.6-2.8 2.7-4.3 5.2-4.3s4.6 1.5 5.2 4.3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    "caret": '<svg class="car" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "analysis": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 13.5h11M4.5 11V7.5M8 11V4M11.5 11V6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "guides": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 2.5h7.5L13 5v8.5H3zM5.5 7h5M5.5 9.5h5M5.5 12h3" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    "sources": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.5 9.5l3-3M7 4.5l1.2-1.2a2.8 2.8 0 014 4L11 8.5M9 11.5l-1.2 1.2a2.8 2.8 0 01-4-4L5 7.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    "submit": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 11V3M4.8 6.2L8 3l3.2 3.2M3 13.5h10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "data": '<svg viewBox="0 0 16 16" aria-hidden="true"><ellipse cx="8" cy="4" rx="5" ry="2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-.9 5-2" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
    "programs": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
}
SHORTCUTS = (("/", "from anywhere but a text box"), ("Ctrl K", ""), ("Ctrl S", "replaces the browser's Save on this site"),
             ("Ctrl O", "replaces the browser's Open on this site"))


def theme_head(name: str, solid_icons: dict) -> str:
    """Settings › Theme before first paint: an inline script (no request) puts a reader's pick on <html>; with none the
    system decides (the catalog's CSS). WHY inline and tiny: a remembered dark page must never flash light first.
    The same script applies Settings › Logo: html[data-logo] and the icon links, so a reader who picked Solid never
    sees a frame of the line logo or tab icon. Keys are "<name>.theme" and "<name>.logo" in localStorage."""
    return ("<script>try{var d=document.documentElement,t=localStorage.getItem('" + name + ".theme');"
            "if(t==='light'||t==='dark')d.dataset.theme=t;"
            f"var m={json.dumps(solid_icons, separators=(',', ':'), allow_nan=False)};window.rpIcons=m;"
            "if(localStorage.getItem('" + name + ".logo')==='solid'){d.dataset.logo='solid';"
            "document.querySelectorAll('link[rel=icon],link[rel=apple-touch-icon]').forEach(function(l){"
            "var h=l.getAttribute('href');if(m[h])l.setAttribute('href',m[h])})}}catch(e){}</script>\n")


def search_menu(catalog: Catalog, site) -> str:
    """The search's menu, idle: the catalog's groups, its top subgroups, every area and the keys. Typed, static/shell.js
    fills .sm-typed from the catalog's suggest file (fetched on first use) and hides the idle part."""
    menu = catalog.menu(site)
    chips = "".join(f'<a class="chip" href="{e(href)}">{e(label)} <span class="n">{n:,}</span></a>'
                    for label, href, n in menu.groups)
    brands = "".join(f'<a class="chip" href="{e(url)}">{e(name)} <span class="n">{n:,}</span></a>'
                     for name, url, n in menu.top[:catalog.top_count])
    go = "".join(f'<a class="go" href="{a.href}"><span class="ic">{ICON[a.key]}</span><span><span class="t">{e(a.label)}</span>'
                 f'<small>{e(a.what)}</small></span></a>' for a in catalog.areas)
    keys = " ".join(f"<kbd>{k}</kbd>" for k, _w in SHORTCUTS)
    return f"""<div class="sm" id="sm" role="dialog" aria-label="Search suggestions" hidden>
<div class="sm-typed" hidden></div>
<div class="sm-idle">
<p class="sm-h">{e(catalog.words.groups)}</p><div class="chips">{chips}</div>
<p class="sm-h">{e(catalog.words.subgroups)}</p><div class="chips">{brands}</div>
<p class="sm-h">Go to</p>{go}
</div>
<p class="sm-foot">{keys} open this · <kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Enter</kbd> open · <kbd>Esc</kbd> close</p>
</div><!-- /sm -->"""


def account_menu(catalog: Catalog) -> str:
    """Account ▾: Amazon's "Account & Lists" in the catalog's own areas. Recently viewed is this browser's
    (static/shell.js, localStorage); Saved and Your lists wait for accounts and say so; nothing pretends to work.
    The Site column lists every area but the first (it has its own column)."""
    items, account = catalog.words.items, catalog.account
    an_item = catalog.words.an_item or f"a {catalog.words.item}"
    site_links = "".join(f'<li><a href="{a.href}"><span class="ic">{ICON[a.key]}</span>{e(a.label)}</a></li>'
                         for a in catalog.areas[1:])
    keys = "".join(f"<li><kbd>{k}</kbd> open the search{f' <small>({e(w)})</small>' if w else ''}</li>" for k, w in SHORTCUTS)
    radios = lambda name, options: "".join(  # noqa: E731
        f'<label><input type="radio" name="{name}" value="{value}"> {e(text)}</label>' for value, text in options)
    examples = "".join(f'<li><a href="{e(href)}">{e(title)}</a> <span class="pill">{e(account.pill)}</span></li>' for href, title in account.lists)
    links = " · ".join(f'<a href="{e(href)}">{e(text)}</a>' for href, text in account.links)
    data = (f'<li><a href="{e(account.data)}"><span class="ic">{ICON["data"]}</span>Data files</a></li>\n'
            if account.data else "")
    signin = f'<br><small class="mut">{e(account.signin)}</small>' if account.signin else ""
    # WHY optional: Settings › Logo only does something where the catalog has a second logo (the shell never shows a
    # control that does nothing)
    logo = (f'<fieldset><legend>Logo</legend>{radios("logo", (("line", "Line"), ("solid", "Solid")))}</fieldset>\n'
            if account.logo else "")
    return f"""<div class="am" id="am" popover role="menu" aria-label="Account">
<div class="am-col">
<h3 class="am-h">Recently viewed</h3>
<ul class="am-recent"></ul>
<p class="am-empty mut">The {e(items)} you open show here (kept in this browser only).</p>
<h3 class="am-h">Saved</h3>
<p class="mut">Saving and liking {e(items)} comes with accounts. <span class="pill">coming soon</span></p>
</div>
<div class="am-col">
<h3 class="am-h">Your lists &amp; analyses</h3>
<ul class="am-list">
{examples}
<li><span class="mut">{e(account.create)}</span> <span class="pill">coming soon</span></li>
<li><span class="mut">Shared with your org</span> <span class="pill">coming soon</span></li>
</ul>
<p>{links}</p>
</div>
<div class="am-col">
<h3 class="am-h">Site</h3>
<ul class="am-links">{site_links}
{data}</ul>
</div>
<div class="am-col">
<h3 class="am-h">Account</h3>
<p class="am-signin"><span>Sign in</span> <span class="pill">coming soon</span>{signin}</p>
<fieldset><legend>Theme</legend>{radios("theme", (("system", "System"), ("light", "Light"), ("dark", "Dark")))}</fieldset>
{logo}<fieldset><legend>Opening {e(an_item)} from a list</legend>{radios("open", (("side", "Side peek"), ("expand", "Expand in place"), ("link", "Go to its page")))}</fieldset>
<details><summary>Keyboard shortcuts</summary><ul class="am-keys">{keys}<li><kbd>↑</kbd><kbd>↓</kbd> move in a menu · <kbd>Esc</kbd> close it</li></ul></details>
</div>
</div><!-- /am -->"""


def site_header(catalog: Catalog, site, url: str) -> str:
    total = catalog.menu(site).total
    items = catalog.words.items
    current = lambda href: ' aria-current="page"' if url.startswith(href) else ""  # noqa: E731
    quick = "".join(f'<a href="{e(href)}"{current(href)}>{e(label)}</a>' for label, href in catalog.quick)
    return f"""<header class="top">
<div class="bar">
<a class="wordmark" href="/">{catalog.brand.logo}<span class="sr">{e(catalog.brand.name)}</span></a>
<form role="search" class="find" action="/search/" method="get"><label class="sr" for="site-q">Search {e(items)}</label><input type="search" id="site-q" name="q" placeholder="Search {total:,} {e(items)}" autocomplete="off" aria-controls="sm" aria-expanded="false"><span class="si">{ICON["search"]}</span><kbd class="fk" title="Open the search: / · Ctrl K · Ctrl S · Ctrl O">Ctrl K</kbd><button type="submit" class="sr">Search</button>
{search_menu(catalog, site)}
</form>
<nav class="quick" aria-label="Site">{quick}<button type="button" class="acct" popovertarget="am" aria-haspopup="menu" aria-expanded="false">{ICON["user"]}<span class="lbl">Account</span>{ICON["caret"]}</button></nav>
</div>
{account_menu(catalog)}
</header>"""


def page(catalog: Catalog, site, title: str, url: str, body: str, kind: str, description: str = "", scripts=None,
         trail: str = "", aside: str | None = None, data_ui: bool = False, extra_head: str = "") -> str:
    """The shell every page shares. WHY this shape (Zach, 2026-10-25, design/BRIEF-2026-10-25.md: "muscle memory,
    don't reinvent the wheel"): McMaster-Carr's catalog shell. The wordmark on the left, ONE search box dead centre (the
    header's middle grid column, so it has the same width and place on every page), the catalog's quick links and
    Account on the right (site_header); then the trail (the results line on a list page and the drill-down breadcrumb on every page). With `aside` the page is
    McMaster's two panes: the filter column and the results, each its own scroll container (static/site.css).
    Accounts come later: the account menu says so, and the site never shows a control that does nothing."""
    # WHY shell.js first (deferred scripts and the kit's module run in document order): it puts a reader's Settings ›
    # "Opening a <item>" on each <data-views> before the kit upgrades it
    scripts = catalog.scripts if scripts is None else scripts
    script_tags = "".join(f'<script src="/static/{name}.js" defer></script>\n' for name in ("shell",) + tuple(scripts))
    if "data-toolbar-presets" in body:  # the temporary toolbar preset switcher (static/toolbar-presets.js says why)
        script_tags += '<script src="/static/toolbar-presets.js" defer></script>\n'
    if data_ui:  # a page with a <data-views>: the vendored kit, after site.js (data_ui_head says why)
        script_tags += data_ui_head(catalog.brand.kit_preludes)
    elif aside is not None or 'data-resizable="' in body:  # a side panel and no kit: the kit's resize module alone (5 KB)
        script_tags += f'<script type="module" src="{DATA_UI}resize.js"></script>\n'
    meta = f'<meta name="description" content="{e(description)}">\n' if description else ""
    styles = "".join(f'<link rel="stylesheet" href="{e(href)}">\n' for href in catalog.brand.styles)
    footer = f"""<footer>
{catalog.brand.footer(site) if catalog.brand.footer else ""}
</footer>"""
    if aside is None:
        main = f"<main>\n{body}\n</main>\n{footer}"
        layout = "flow"
    else:
        # WHY data-resizable (Zach, 2026-10-26, .claude/feedback.md): every side panel drags to resize, remembered;
        # data-ui's resize primitive gives it the handle (its CONTRACT.md §11), static/site.css reads the width
        main = (f'<main class="panes">\n<aside class="fcol" id="filter" aria-label="Filters" data-resizable="right" data-resizable-min="200" data-resizable-max="560">\n{aside}\n</aside>\n'
                f'<div class="mpane" id="pane">\n{body}\n{footer}\n</div>\n</main>')
        layout = "panes"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{e(title)}</title>
{meta}<link rel="canonical" href="{e(catalog.brand.origin + url)}">
{f'<link rel="stylesheet" href="{DATA_UI}data-ui.css">{chr(10)}' if data_ui else ""}<link rel="stylesheet" href="/static/site.css">
{styles}{extra_head}{catalog.brand.icons}{catalog.brand.head}</head>
<body data-page="{e(kind)}" class="{layout}">
{site_header(catalog, site, url)}
<div class="trail">
{trail}
</div>
{main}
{script_tags}</body>
</html>
"""
