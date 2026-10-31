"""The Analysis area (PEP 0002 "analyses" and PEP 0003 §8 of the first catalog): reports that mix Markdown with live data-ui views, one file
each. Three parts, every catalog word an argument:

- **the reader and checker**: an analysis file's frontmatter and blocks (```base fences, ![[name.base]] embeds,
  > [!callout]s), and what is wrong with it (a view naming a property its data does not have, a missing file). Ported
  from the first catalog's lane/analysis build/site_analysis.py @ f51fc19 with its module constants made arguments (the folder,
  the URLs, the frontmatter key naming record ids) and its `Catalog` renamed `RecordIndex`; the .base reader is passed in
  (`reader`, a catalog's vendored data_ui_base) so this module imports nothing outside the stdlib.
- **the two layouts**: the list (`list_layout`: a heading block, one <data-views> over the rows, a fallback list) and a
  report (`report_layout`: the contents column, drag-resizable, beside the article).
- **the frame** (`pages`): /analysis/, one page per report, the shell a folder's own report opens in, each in the
  catalog's shell, titled "<title>: <brand>" under the crumbs root › Analysis › report. The catalog draws the bodies
  (contract.AnalysisArea's callbacks).

WHY the reader mirrors the browser's (lane/analysis static/analysis.js): the checker and the page must never disagree.
"""

from __future__ import annotations

import json
import pathlib
import re

from .contract import AnalysisArea, Catalog
from .data_ui import base_properties as _base_properties
from .html import breadcrumb
from .shell import page

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
STATUSES = ("draft", "open", "decided", "superseded")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- the format (the same rules and words as the browser's reader) ----------------------------------------------------

def _empty(value) -> bool:
    return value is None or value == "" or (isinstance(value, list) and not value)


def _list(value) -> list[str]:
    items = value if isinstance(value, list) else ([] if _empty(value) else [value])
    return [str(item).strip() for item in items if str(item).strip()]


def split_frontmatter(text: str):
    """(yaml or None, body, the body's first line)."""
    src = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    m = re.match(r"---[ \t]*\n((?:.*\n)*?)?---[ \t]*(?:\n|$)", src)
    if not m:
        return None, src, 1
    yaml = m.group(1) or ""
    lines = len(yaml.split("\n")) - 1 if yaml else 0
    return yaml, src[m.end():], lines + 3


def read_analysis(text: str, reader, ids: str = "parts"):
    """(front, body, body_line, problems): the file read with data-ui's own reader (`reader`), and what the format
    asks (PEP 0002 §4). `ids` is the frontmatter key that names record ids ("parts" in a parts catalog)."""
    yaml, body, body_line = split_frontmatter(text)
    if yaml is None:
        return {}, body, body_line, [{"line": 1, "message": "no frontmatter: the file must start with --- and a title:"}]
    try:
        front = reader.loads(yaml) if yaml.strip() else {}
        if not isinstance(front, dict):
            raise reader.BaseSyntaxError("it is not a list of key: value lines")
    except (reader.BaseSyntaxError, ValueError) as error:
        return {}, body, body_line, [{"line": 2, "message": f"frontmatter does not parse: {error}"}]
    lines = yaml.split("\n")

    def at(key):
        for n, line in enumerate(lines):
            if re.match(rf"{key}\s*:", line):
                return n + 2
        return 1

    problems = []
    for key in ("title", "question"):
        if not (isinstance(front.get(key), str) and front[key].strip()):
            problems.append({"line": at(key), "message": f"{key}: is required"})
    status = front.get("status")
    if not _empty(status) and status not in STATUSES:
        problems.append({"line": at("status"), "message": f"status: must be one of {', '.join(STATUSES)} (it is {status})"})
    if not _empty(front.get(ids)) and not isinstance(front.get(ids), list):
        problems.append({"line": at(ids), "message": f"{ids}: must be a list of ids"})
    decision = front.get("decision")
    if not _empty(decision) and str(decision) not in _list(front.get(ids)):
        problems.append({"line": at("decision"), "message": f"decision: {decision} is not one of {ids}:"})
    date = front.get("date")
    if not _empty(date) and not DATE_RE.match(str(date)):
        problems.append({"line": at("date"), "message": f"date: must be YYYY-MM-DD (it is {date})"})
    return front, body, body_line, problems


def blocks_of(body: str, start: int = 1) -> list[dict]:
    """The body's blocks: markdown, base (a ```base fence), embed (![[name.base#view]]) and callout."""
    lines = body.split("\n")
    out, prose, prose_line = [], [], 0

    def flush():
        nonlocal prose
        if any(line.strip() for line in prose):
            out.append({"kind": "markdown", "text": "\n".join(prose).strip("\n"), "line": prose_line})
        prose = []

    def add(line, n):
        nonlocal prose_line
        if not prose:
            prose_line = start + n
        prose.append(line)

    i = 0
    while i < len(lines):
        line = lines[i]
        fence = re.match(r"\s*(`{3,}|~{3,})\s*([\w-]*)\s*$", line)
        if fence:
            mark, lang = fence.groups()
            close = re.compile(rf"\s*{re.escape(mark[0])}{{{len(mark)},}}\s*$")
            j = i + 1
            while j < len(lines) and not close.match(lines[j]):
                j += 1
            if lang.lower() == "base":
                flush()
                out.append({"kind": "base", "text": "\n".join(lines[i + 1:j]), "line": start + i})
            else:
                for k in range(i, min(j, len(lines) - 1) + 1):
                    add(lines[k], k)
            i = j + 1
            continue
        embed = re.match(r"\s*!\[\[([^\]|#]+?\.base)(?:#([^\]|]+))?(?:\|[^\]]*)?\]\]\s*$", line)
        if embed:
            flush()
            out.append({"kind": "embed", "name": embed.group(1).strip(), "view": (embed.group(2) or "").strip() or None, "line": start + i})
            i += 1
            continue
        callout = re.match(r">\s*\[!([\w-]+)\]([+-]?)\s*(.*)$", line)
        if callout:
            flush()
            text, j = [], i + 1
            while j < len(lines) and lines[j].startswith(">"):
                text.append(re.sub(r"^>\s?", "", lines[j]))
                j += 1
            out.append({"kind": "callout", "type": callout.group(1).lower(), "fold": callout.group(2), "title": callout.group(3).strip(),
                        "text": "\n".join(text), "line": start + i})
            i = j
            continue
        add(line, i)
        i += 1
    flush()
    return out


def datasets_of(doc: dict) -> list[dict]:
    """A dashboard's datasets as data-ui names them."""
    out = [{"name": name, "data": entry if isinstance(entry, str) else (entry or {}).get("data")}
           for name, entry in (doc.get("datasets") or {}).items()]
    data = doc.get("data")
    if isinstance(data, str) and not any(d["data"] == data for d in out):
        out.append({"name": re.sub(r"\.[^.]+$", "", data.rsplit("/", 1)[-1]), "data": data})
    return out


# --- what an analysis may name and embed ----------------------------------------------------------------------------

class RecordIndex:
    """The built site's public records and data files: what an analysis may name (`records`: {id: {name, url,
    category, brand, photo}}) and embed (a public URL's file under `site`)."""

    def __init__(self, site: pathlib.Path, records: dict):
        self.site = pathlib.Path(site)
        self.records = records
        self._props: dict[str, set | None] = {}

    def file(self, url: str) -> pathlib.Path | None:
        """A public URL's file in the build, or None."""
        path = (self.site / url.lstrip("/")).resolve()
        return path if path.is_relative_to(self.site.resolve()) and path.is_file() else None

    def properties(self, path: pathlib.Path) -> set | None:
        key = str(path)
        if key not in self._props:
            self._props[key] = dataset_properties(path)
        return self._props[key]


def dataset_properties(path: pathlib.Path) -> set | None:
    """The properties a data file's rows have (its declared properties, every row's keys, and id)."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = doc if isinstance(doc, list) else doc.get("rows", [])
    names = set((doc.get("properties") or {}) if isinstance(doc, dict) else ())
    for row in rows:
        if isinstance(row, dict):
            names.update(row)
    return names | {"id"}


# --- the checker (PEP 0002 §6) ---------------------------------------------------------------------------------------

KEYWORDS = {"true", "false", "null", "this", "note", "file", "formula"}


def filter_properties(filters) -> set[str]:
    """The properties a filter (a string, or and/or/not of them) reads: identifiers outside quotes, not after a '.',
    not a keyword, and never this.<key> (the note's frontmatter)."""
    if isinstance(filters, dict):
        return set().union(*(filter_properties(v) for v in filters.values())) if filters else set()
    if isinstance(filters, list):
        return set().union(*(filter_properties(v) for v in filters)) if filters else set()
    if not isinstance(filters, str):
        return set()
    names = set()
    unquoted = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', '""', filters)
    for m in re.finditer(r"(?<![\w.])([A-Za-z_]\w*)", unquoted):
        if m.group(1) not in KEYWORDS:
            names.add(m.group(1))
    for m in re.finditer(r'note\[\s*"([^"]+)"\s*\]', filters):
        names.add(m.group(1))
    return names


def _properties_of_view(view: dict, base_properties) -> set[str]:
    names = set(base_properties({"views": [view]}))
    names |= filter_properties(view.get("filters"))
    if isinstance(view.get("select"), str):
        names.add(view["select"])
    kpi = view.get("kpi") or {}
    for part in kpi.values() if isinstance(kpi, dict) else ():
        if isinstance(part, dict) and isinstance(part.get("property"), str):
            names.add(part["property"])
    return {name for name in names if name}


def _line_of(text: str, start: int, name: str) -> int:
    for n, line in enumerate(text.split("\n")):
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", line):
            return start + 1 + n
    return start


class Problems(list):
    def add(self, line: int, message: str):
        self.append({"line": line, "message": message})


def check_base(text: str, here_dir: pathlib.Path | str, line: int, label: str, index: RecordIndex, problems: Problems,
               reader, view: str | None = None, base_properties=_base_properties):
    """One .base document (a fence, an embedded file): it parses, its data exists, its views name real properties."""
    try:
        doc = reader.loads(text)
    except reader.BaseSyntaxError as error:
        problems.add(line, f"{label}: the .base does not parse: {error}")
        return
    views = [v for v in doc.get("views") or [] if isinstance(v, dict)]
    if view:
        views = [v for v in views if v.get("name") == view]
        if not views:
            problems.add(line, f"{label}: no view named \"{view}\"")
            return

    def props_of(path: str | None):
        if not isinstance(path, str) or not path:
            problems.add(line, f"{label}: names no data: file")
            return None, None
        if path.startswith("/") or isinstance(here_dir, str):
            url = path if path.startswith("/") else f"{str(here_dir).rstrip('/')}/{path}"
            target = index.file(url)
        else:
            target = (here_dir / path).resolve()
            target = target if target.is_file() else None
        if target is None:
            problems.add(line, f"{label}: data {path}: no such file")
            return None, None
        return index.properties(target), target.name

    if doc.get("layout") or doc.get("datasets"):
        sets = {d["name"]: props_of(d["data"]) for d in datasets_of(doc)}
        default = next((d["name"] for d in datasets_of(doc) if d["data"] == doc.get("data")), None)
        for v in views:
            props, name = sets.get(v.get("from") or default, (None, None))
            if props is None:
                continue
            for prop in sorted(_properties_of_view(v, base_properties) - props):
                problems.add(_line_of(text, line, prop), f"'{prop}' is not a property of {name}")
        return
    props, name = props_of(doc.get("data"))
    if props is None:
        return
    wanted = set(filter_properties(doc.get("filters")))
    for facet in doc.get("facets") or []:
        if isinstance(facet, str):
            wanted.add(facet)
        elif isinstance(facet, dict) and facet.get("property"):
            wanted.add(facet["property"])
    for v in views:
        wanted |= _properties_of_view(v, base_properties)
    for prop in sorted(wanted - props):
        problems.add(_line_of(text, line, prop), f"'{prop}' is not a property of {name}")


def find_embed(name: str, here: pathlib.Path | str, index: RecordIndex, presets: str = "/search/views/"):
    """(text, folder) of the .base an embed names: beside the note, the folder's views/, the catalog's presets."""
    if isinstance(here, pathlib.Path):
        root = here.parent if here.name == "analyses" else here
        for candidate in ([here / name, root / name] if "/" in name else [here / name, root / "views" / name]):
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8"), candidate.parent
    else:
        path = index.file(f"{here.rstrip('/')}/{name}")
        if path:
            return path.read_text(encoding="utf-8"), here.rstrip("/")
    preset = index.file(f"{presets.rstrip('/')}/{name.rsplit('/', 1)[-1]}")
    if preset:
        return preset.read_text(encoding="utf-8"), presets.rstrip("/")
    return None


def check_text(text: str, index: RecordIndex, here: pathlib.Path | str, reader, ids: str = "parts",
               presets: str = "/search/views/", base_properties=_base_properties) -> list[dict]:
    """Every problem in one analysis file, each {line, message}. `here` is the file's folder (a path; or, for a
    published example, its public URL folder)."""
    front, body, body_line, problems = read_analysis(text, reader, ids)
    problems = Problems(problems)
    yaml = split_frontmatter(text)[0] or ""
    for record in _list(front.get(ids)):
        if record not in index.records:
            n = next((i + 2 for i, line in enumerate(yaml.split("\n")) if record in line), 1)
            problems.add(n, f"{ids}: {record} is not in this release")
    for block in blocks_of(body, body_line):
        if block["kind"] == "base":
            check_base(block["text"], here, block["line"], "```base", index, problems, reader, base_properties=base_properties)
        elif block["kind"] == "embed":
            found = find_embed(block["name"], here, index, presets)
            label = f"![[{block['name']}]]"
            if found is None:
                problems.add(block["line"], f"{label}: no such file (looked beside the note, in views/ and in the catalog's presets)")
                continue
            embed_text, embed_dir = found
            check_base(embed_text, embed_dir, block["line"], label, index, problems, reader, view=block["view"],
                       base_properties=base_properties)
    return sorted(problems, key=lambda p: p["line"])


def examples(folder: pathlib.Path, index: RecordIndex, reader, ids: str = "parts", warn=None) -> list[tuple[str, str, dict]]:
    """(slug, text, front) of every analysis in `folder` that checks clean, in name order. One with a problem is left
    out and named through `warn` (the build keeps going: a test site may lack the data a shipped example reads)."""
    warn = warn or (lambda message: None)
    out = []
    for path in sorted(pathlib.Path(folder).glob("*.md")):
        if path.name == "README.md":
            continue
        slug = path.stem
        if not SLUG_RE.match(slug):
            raise ValueError(f"{path}: the file name is not a slug ({SLUG_RE.pattern})")
        text = path.read_text(encoding="utf-8")
        problems = check_text(text, index, pathlib.Path(folder), reader, ids)
        if problems:
            warn(f"analysis: left out {path.name}: " + "; ".join(f"line {p['line']}: {p['message']}" for p in problems[:5]))
            continue
        out.append((slug, text, read_analysis(text, reader, ids)[0]))
    return out


def example_row(slug: str, front: dict, index: RecordIndex, url: str, files_url: str, ids: str = "parts",
                source: str = "Example") -> dict:
    """An analysis's row in the list (the keys the list's .base presets and the browser's reader use)."""
    named = _list(front.get(ids))
    decision = None if _empty(front.get("decision")) else str(front["decision"])
    chosen = index.records.get(decision) if decision else None
    known = [(i, index.records.get(i)) for i in named]
    text = lambda key: front[key] if isinstance(front.get(key), str) and front[key].strip() else None  # noqa: E731
    return {
        "id": f"example:{slug}", "title": text("title") or slug, "question": text("question"),
        "status": front.get("status") if front.get("status") in STATUSES else "draft", "source": source,
        "parts": [(p and p["name"]) or i for i, p in known], "part_ids": named, "parts_count": len(named),
        "decision": ((chosen and chosen["name"]) or decision) if decision else None, "decision_id": decision,
        "decision_brand": (chosen and chosen["brand"]) or None,
        "category": sorted({p["category"] for _i, p in known if p and p.get("category")}),
        "date": None if _empty(front.get("date")) else str(front["date"]), "author": text("author"), "tags": _list(front.get("tags")),
        "visibility": "public", "url": f"{url}{slug}/", "path": f"{files_url}{slug}.md", "host": None,
        "photos": [p["photo"] for _i, p in known if p and p.get("photo")][:4], "mosaic": None,
    }


LIST_PROPERTIES = {
    "title": {"type": "text", "label": "Analysis", "width": 260},
    "question": {"type": "text", "label": "Question", "width": 320},
    "status": {"type": "text", "label": "Status", "width": 100},
    "source": {"type": "text", "label": "Whose", "width": 90},
    "parts": {"type": "list", "label": "Parts considered", "width": 300},
    "part_ids": {"type": "list", "hidden": True},
    "parts_count": {"type": "number", "label": "Parts", "width": 70},
    "decision": {"type": "text", "label": "Decision", "width": 200},
    "decision_id": {"type": "text", "hidden": True},
    "decision_brand": {"type": "text", "label": "Decided brand", "width": 120},
    "category": {"type": "list", "label": "Part category", "width": 120},
    "date": {"type": "date", "label": "Date", "width": 110},
    "author": {"type": "text", "label": "Author", "width": 160},
    "tags": {"type": "list", "label": "Tags", "width": 160},
    "visibility": {"type": "text", "label": "Visibility", "width": 100},
    "url": {"type": "text", "hidden": True},
    "path": {"type": "text", "label": "File", "width": 300},
    "host": {"type": "text", "label": "Machine", "width": 120},
    "photos": {"type": "list", "hidden": True},
    "mosaic": {"type": "text", "hidden": True, "display": "image", "note": "the parts considered, up to four photos"},
}


def examples_dataset(rows: list[dict], dataset_id: str) -> dict:
    return {"id": dataset_id, "title": "Analyses", "titleProperty": "title", "linkProperty": "url", "imageProperty": "mosaic",
            "properties": LIST_PROPERTIES, "rows": rows}


# --- the layouts ------------------------------------------------------------------------------------------------------

def list_layout(url: str, lede: str, note: str, items: str, how: str, views_attrs: str = 'toolbar="bar" filters="pills"',
                noscript: str = "") -> str:
    """The /analysis/ list: a heading block (`lede`, `note`: HTML), ONE <data-views> over <url>examples.json with
    <url>analysis.base's presets (`items`, the <li>s, inside it as the reading without JavaScript), then `how` (HTML:
    how to write one) and an optional <noscript>."""
    return f"""<div class="an-listhead">
<h1>Analysis</h1>
<p class="an-lede">{lede}</p>
<p class="an-mut" id="analysis-note" aria-live="polite">{note}</p>
</div>
<data-views id="analysis-list" src="{url}analysis.base" data="{url}examples.json" aria-label="Analyses" {views_attrs} data-hearts="off">
<ul class="an-fallback">
{items}
</ul>
</data-views>
<details class="an-how">
{how}
</details>{noscript}"""


def report_layout(article: str, toc: str = "") -> str:
    """A report page: the contents column (`toc`, a <nav>'s inside), drag-resizable and remembered as
    "analysis-toc", beside the article (`article`, HTML)."""
    return f"""<div class="an-layout" id="analysis-report">
<aside class="an-toc" id="analysis-toc" aria-label="Contents" data-resizable="right" data-resizable-min="160" data-resizable-max="440" data-resizable-key="analysis-toc"><nav>{toc}</nav></aside>
<article class="an-main">
{article}
</article>
</div>"""


# --- the frame ----------------------------------------------------------------------------------------------------------

def pages(catalog: Catalog, site):
    """(relative path, text or bytes) of every /analysis/ file: the list, the area's files, each report's files and
    page, and the shell a folder's own report opens in; every page in the catalog's shell."""
    area: AnalysisArea = catalog.analysis
    url, label, brand = area.url, area.label, catalog.brand.name
    crumbs = [catalog.brand.root_crumb, (label, url)]
    reports = area.reports(site)
    yield (f"{url.strip('/')}/index.html",
           page(catalog, site, f"{label}: {brand}", url, area.list_body(site, reports), area.list_kind,
                description=area.list_description, trail=breadcrumb(crumbs), data_ui=area.data_ui, extra_head=area.head))
    yield from area.files(site)
    for report in reports:
        yield from report.files
        report_url = f"{url}{report.slug}/"
        yield (f"{report_url.strip('/')}/index.html",
               page(catalog, site, f"{report.title}: {brand}", report_url, report.body, area.report_kind,
                    description=report.description, trail=breadcrumb(crumbs + [(report.title, report_url)]),
                    data_ui=area.data_ui, extra_head=area.head))
    if area.shell is not None:
        yield (f"{url.strip('/')}/_/index.html",
               page(catalog, site, f"{label}: {brand}", f"{url}_/", area.shell.body, area.report_kind,
                    description=area.shell.description, trail=breadcrumb(crumbs), data_ui=area.data_ui, extra_head=area.head))
