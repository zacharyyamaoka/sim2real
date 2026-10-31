"""The contract between the workbench and a catalog (PEP 0003 §7, draft 0.x): what a catalog hands over, as frozen
dataclasses. Stdlib only. Stage 1 holds the fields the first catalog's pages need byte for byte; Stage 3 adds what the
object database proves it needs, and the contract freezes as 1.0 after that.

WHY dataclasses, not a config file (PEP 0003 §7): every tab, list and section names a function, and a typo then fails
at import, not late in a build.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

Site = Any    # whatever the catalog loads (a data loader, a note library)
Record = Any  # one record, as the catalog's adapters read it


@dataclass(frozen=True)
class Area:
    """One of the catalog's areas: the search menu's "Go to" rows and the Account menu's Site column."""
    key: str     # its icon in shell.ICON
    label: str
    href: str
    what: str    # one line under the label in the search menu


@dataclass(frozen=True)
class Words:
    """The nouns the shell shows, so no catalog's words are baked into the frame."""
    item: str = "record"         # "Opening a part from a list"
    an_item: str | None = None   # the item with its article when it is not "a <item>": "an object"
    items: str = "records"       # "Search 1,234 parts"
    groups: str = "Categories"   # the search menu's first chip row
    subgroups: str = "Brands"    # its second chip row


@dataclass(frozen=True)
class Menu:
    """What the search menu lists before anything is typed, computed from the catalog's data."""
    groups: list[tuple[str, str, int]]   # (label, href, count): the first chip row, in order
    top: list[tuple[str, str, int]]      # (name, href, count): the second chip row, most records first
    total: int                           # every record: the search box's placeholder


@dataclass(frozen=True)
class Account:
    """The Account menu's catalog-specific lines; the frame (recently viewed, saved, theme, logo, open mode, keys) is the
    workbench's."""
    lists: tuple[tuple[str, str], ...] = ()   # (href, title) of the example analyses under "Your lists & analyses"
    links: tuple[tuple[str, str], ...] = ()   # (href, text) of the line under that list
    data: str | None = None                   # the "Data files" link in the Site column
    pill: str = "example"                     # the pill beside each of `lists`
    create: str = "Create a list"             # the "coming soon" line after them
    signin: str | None = None                 # the line under "Sign in"
    logo: bool = False                        # Settings › Logo (only where the catalog has a second, solid logo)


@dataclass(frozen=True)
class Brand:
    name: str                 # page titles "<page>: <name>", the wordmark's screen-reader name, storage keys "<name>.*"
    origin: str               # rel=canonical; absolute links to it are written site-relative
    logo: str                 # the header's logo markup
    icons: str                # the <link rel="icon"> block
    head: str                 # the inline script that applies a reader's theme and logo before first paint
    root_crumb: tuple[str, str] = ("Home", "/")
    footer: Callable[[Site], str] | None = None
    styles: tuple[str, ...] = ()           # the catalog's stylesheets, after the shell's /static/site.css
    kit_preludes: tuple[str, ...] = ()     # module scripts a data-ui page loads before the kit (a catalog's stopgaps)


@dataclass(frozen=True)
class Tab:
    """One tab of a record page: its link is #<key>; its panel is the catalog's HTML."""
    key: str
    label: str
    body: Callable[[Site, Record], str]
    has: Callable[[Site, Record], bool] | None = None   # None: always shown
    empty: Literal["line", "hide"] = "line"   # listed in "Nothing recorded yet: …", or no tab and no panel at all
    panel_id: str | None = None   # an anchor kept from an older page; else tab-<key>


@dataclass(frozen=True)
class Kind:
    """One kind of record and its page."""
    key: str                                   # "part": the page's <body data-page>
    label: str                                 # "Part": the tab list's name, "Part sections"
    plural: str
    records: Callable[[Site], list]
    url: Callable[[Record], str]               # the canonical URL, in the catalog's own scheme
    title: Callable[[Record], str]             # the page's name (its <title> is "<title>: <brand>")
    tabs: tuple[Tab, ...]
    header: Callable[[Site, Record], str]      # inside <div class="phead">: logo plate, h1, subtitle, notices
    crumbs: Callable[[Site, Record], list[tuple[str, str]]]
    back: Callable[[Site, Record], list[str]] | None = None   # the list URLs a "Back to results" link accepts
    description: Callable[[Site, Record], str] | None = None
    scripts: tuple[str, ...] = ("site",)       # /static/<name>.js after shell.js
    data_ui: bool = False                      # the page holds a <data-views>: load the kit


@dataclass(frozen=True)
class Report:
    """One page of the Analysis area, drawn by the catalog."""
    slug: str                                  # its page is <area url><slug>/
    title: str
    body: str                                  # the page's HTML (analysis.report_layout gives the shared layout)
    description: str = ""
    files: tuple = ()                          # (relative path, text or bytes) written beside the pages (its .md, its views)


@dataclass(frozen=True)
class AnalysisArea:
    """The Analysis area: the list page, one page per report, and (optionally) the shell a folder's own report opens
    in (analysis.pages writes them in the catalog's shell)."""
    reports: Callable[[Site], list]                      # the Reports, in list order
    list_body: Callable[[Site, list], str]               # the list page's HTML (analysis.list_layout gives the shared layout)
    url: str = "/analysis/"
    label: str = "Analysis"                              # the crumb, and the list page's title
    list_description: str = ""
    list_kind: str = "analysis"                          # the pages' <body data-page>
    report_kind: str = "analysis"
    shell: Report | None = None                          # /analysis/_/: a folder's own report, read in the browser
    files: Callable[[Site], Any] = lambda site: ()       # (relative path, text or bytes): the list's .base and rows, the format
    data_ui: bool = False                                # the pages hold <data-views>: load the kit
    head: str = ""                                       # extra head tags on every Analysis page (its stylesheet)


@dataclass(frozen=True)
class Catalog:
    brand: Brand
    words: Words
    menu: Callable[[Site], Menu]
    kinds: tuple[Kind, ...] = ()
    areas: tuple[Area, ...] = ()
    quick: tuple[tuple[str, str], ...] = ()    # (label, href): the bar's links before Account
    account: Account = field(default_factory=Account)
    top_count: int = 12                        # chips in the search menu's second row
    scripts: tuple[str, ...] = ("site",)       # /static/<name>.js every page loads after shell.js, unless it names its own
    pages: Callable[[Site], Any] = lambda site: ()   # (relative path, text or bytes): every other file the catalog writes
    data_dirs: tuple[str, ...] = ()            # its data build's outputs: never written
    data_files: tuple[str, ...] = ()
    analysis: AnalysisArea | None = None       # the Analysis area, when the catalog has one
