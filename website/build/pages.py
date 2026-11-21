"""HTML for every page of the sim2real docs site. Pure functions from model data to strings.

The page shell, sidebar, code block, heading and inline helpers are robotmsgs.com's (robot_msgs website/build/pages.py @ b4c8d36), given
brand, nav and footer parameters; the pages themselves are sim2real's: types -> model rungs -> parameters -> calibration routines ->
examples -> API reference.

WHY the two tables keep their columns (Zach, 2026-11-11: "I really like these tables you have here"): the per-type model-rung table
(Rung, Model, Parameters, Adds, Identified by, with "today's model") and the routines table (Kind, Runs, Status, Time, Operator time,
Equipment $, Recovery at 0x / 1x / 3x / 10x, Needs first) are the old catalog's, pinned by tests/test_docs_site.py.
"""

from __future__ import annotations

import html
import math
import re

from highlight import highlight
from model import LEVEL_WORDS, ApiEntry, ExampleInfo, ModelInfo, ParameterInfo, RoutineInfo, TypeInfo, seconds_text, usd_text

BRAND = "sim2real"
ROBOTMSGS = "https://robotmsgs.com"
NAV = (("Home", "/", "home"), ("Types", "/types/", "types"), ("Routines", "/routines/", "routines"), ("Examples", "/examples/", "examples"),
       ("API", "/api/", "api"), ("Docs", "/docs/", "docs"))
FOOTER = (f'generated from sim2real\'s registries (cards/domain.py, cards/calibration.py, calibration/recovery.py), not written per page'
          f' · styles shared with <a href="{ROBOTMSGS}" rel="noopener">robotmsgs.com</a>')
BRAND_SVG = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
             'stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="5" width="9" height="14" rx="1.5"/>'
             '<path d="M14.5 5h1.5M19 5h1a1.5 1.5 0 0 1 1.5 1.5v1M21.5 10.5v3M21.5 16.5v1A1.5 1.5 0 0 1 20 19h-1M16 19h-1.5" '
             'stroke="var(--accent)"/><path d="M7 11h.01M17 12h.01" stroke-width="3"/></svg>')


def esc(text: object) -> str:
    return html.escape(str(text))


def inline(text: str) -> str:
    """Escape text and turn its ``code`` / `code` spans (reST or Markdown) into <code>."""
    escaped = esc(text)
    escaped = re.sub(r"``([^`]+)``", r"<code>\1</code>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


# --------------------------------------------------------------------------------- components


def wrap_points(markup: str) -> str:
    """Markup with a <wbr> after each dot, bracket and comma of its text (never inside a tag or an entity), so a long call wraps where a
    reader would split it, not mid-identifier (WHY, review 2026-11-20 D6). A <wbr> carries no text: copy and the ruler read the same."""
    return "".join(part if part.startswith("<") else re.sub(r"(?<=[.(,\[])(?!$)", "<wbr>", part)
                   for part in re.split(r"(<[^>]*>)", markup))


def code_block(code: str, language: str = "python", *, wrap: bool = False, label: str = "", pre_attrs: str = "") -> str:
    cls = "code wrap" if wrap else "code"
    # WHY plain text is only escaped: robotmsgs' highlighter knows Python and JSON; a shell line or printed table is not Python
    body = highlight(code, language) if language in ("python", "json") else esc(code)
    if wrap:
        body = wrap_points(body)
    return (
        f'<div class="{cls}">'
        f'<button class="copy" type="button" aria-label="Copy {esc(label or "code")}">Copy</button>'
        f'<pre{pre_attrs}><code>{body}</code></pre></div>'
    )


def heading(level: int, text: str, anchor: str) -> str:
    return (
        f'<h{level} id="{anchor}"><a class="anchor" href="#{anchor}" '
        f'aria-label="Link to {esc(text)}">{esc(text)}</a></h{level}>'
    )


def chip(href: str, text: str, *, title: str = "") -> str:
    tip = f' title="{esc(title)}"' if title else ""
    return f'<a class="chip" href="{href}"{tip}>{esc(text)}</a>'


def ext_link(url: str, text: str) -> str:
    """An external link, https only; anything else is shown as text (a page never links out over plain http)."""
    if url.startswith("https://"):
        return f'<a href="{esc(url)}" rel="noopener">{esc(text)}</a>'
    return esc(text) + (f' <span class="faint small">({esc(url)})</span>' if url else "")


def table(headers: list[str], rows: list[str], *, attrs: str = "", cls: str = "") -> str:
    head = "".join(f"<th scope=\"col\">{esc(h)}</th>" for h in headers)
    klass = f' class="{cls}"' if cls else ""
    return f'<div class="table-wrap"><table{klass}{attrs}><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def shell(
    *,
    title: str,
    description: str,
    path: str,
    body: str,
    asset_version: str,
    types: list[TypeInfo],
    section: str = "",
    current: str = "",
    sidebar: bool = True,
    toc: list[tuple[str, str, int]] | None = None,
    stamp: str = "",
    robots: str = "",
    brand: str = BRAND,
    nav: tuple[tuple[str, str, str], ...] = NAV,
    footer: str = FOOTER,
    wide: bool = False,
    page_class: str = "",
) -> str:
    nav_links = "".join(
        f'<a href="{href}"{" aria-current=\"page\"" if section == key else ""}>{label}</a>'
        for label, href, key in nav
    )
    side = sidebar_html(types, current, section, full=sidebar, nav_links=nav_links)
    toc_html = ""
    if toc:
        items = "".join(
            f'<li class="l{level}"><a href="#{anchor}">{esc(label)}</a></li>'
            for anchor, label, level in toc
        )
        toc_html = (
            f'<aside class="toc" aria-label="On this page"><div class="toc-in">'
            f'<h2 class="toc-h">On this page</h2><ul>{items}</ul></div></aside>'
        )
    layout = ("docs" + (" wide-page" if wide else "")) if sidebar else "wide"
    if wide:  # WHY no on-this-page column: the two tables Zach keeps need the width more than a three-entry outline does
        toc_html = ""
    return f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="color-scheme" content="dark light">{f'<meta name="robots" content="{robots}">' if robots else ""}
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap">
<script>try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<link rel="stylesheet" href="/assets/site.css?v={asset_version}">
<link rel="stylesheet" href="/assets/sim2real.css?v={asset_version}">
</head>
<body class="{layout}{" " + page_class if page_class else ""}">
<a class="skip" href="#main">Skip to content</a>
<header class="topbar">
  <div class="topbar-in">
    <button class="icon-btn menu-btn" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="sidebar">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
    </button>
    <a class="brand" href="/">{BRAND_SVG}<span>{esc(brand)}</span></a>
    <nav class="topnav" aria-label="Main">{nav_links}</nav>
    <div class="spacer"></div>
    <button class="icon-btn theme-btn" type="button" aria-label="Toggle light and dark theme">
      <svg class="i-sun" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
      <svg class="i-moon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>
    </button>
  </div>
</header>
<div class="shell">
{side}
<main id="main" class="main" tabindex="-1">
{body}
<footer class="foot"><span>{esc(stamp)}</span><span>{footer}</span></footer>
</main>
{toc_html}
</div>
<div class="scrim" hidden></div>
<script src="/assets/site.js?v={asset_version}" defer></script>
</body>
</html>
"""


def sidebar_html(types: list[TypeInfo], current: str, section: str, *, full: bool, nav_links: str) -> str:
    drawer = f'<nav class="drawer-nav" aria-label="Site">{nav_links}</nav>'
    if not full:
        return f'<aside id="sidebar" class="sidebar lite">{drawer}</aside>'
    overview = [("All types", "/types/", "types-index"), ("Calibration routines", "/routines/", "routines-index"),
                ("Examples", "/examples/", "examples-index"), ("API reference", "/api/", "api"), ("Guide", "/docs/", "docs-index")]
    groups = [
        '<div class="sb-group"><h2 class="sb-h">Overview</h2><ul>'
        + "".join(
            f'<li><a href="{href}"{" aria-current=\"page\"" if current == key else ""}>{label}</a></li>'
            for label, href, key in overview
        )
        + "</ul></div>"
    ]
    # WHY one group in TYPE_ORDER (data-group="types"): the sidebar reads the types as cards/domain.py orders them, and site.js filters it
    items = "".join(
        f'<li data-name="{esc((t.title + " " + t.id).lower())}"><a href="{t.path}"'
        f'{" aria-current=\"page\"" if current == t.id else ""}>{esc(t.title)}</a></li>'
        for t in types
    )
    groups.append(f'<div class="sb-group" data-group="types"><h2 class="sb-h">Types</h2><ul>{items}</ul></div>')
    return (
        f'<aside id="sidebar" class="sidebar">{drawer}'
        '<div class="search"><input id="search" type="search" placeholder="Filter types…" '
        'aria-label="Filter types" autocomplete="off" spellcheck="false"><kbd>/</kbd></div>'
        '<nav class="sb-nav" aria-label="Types">'
        + "".join(groups)
        + '<p class="sb-empty" hidden>No type matches.</p></nav></aside>'
    )


def crumbs(*parts: tuple[str, str | None]) -> str:
    out = []
    for i, (text, href) in enumerate(parts):
        last = i == len(parts) - 1
        if last:
            out.append(f'<span aria-current="page">{esc(text)}</span>')
        else:
            out.append(f'<a href="{href}">{esc(text)}</a>' if href else esc(text))
    return '<nav class="crumbs" aria-label="Breadcrumb">' + ' <span aria-hidden="true">/</span> '.join(out) + "</nav>"


# ------------------------------------------------------------------------------- the two tables Zach keeps


ROUTINE_HEADERS = ["Routine", "Kind", "Runs", "Status", "Time", "Operator time", "Equipment $", "Recovery 0x", "Recovery 1x",
                   "Recovery 3x", "Recovery 10x", "Needs first"]


def recovery_cell(level) -> str:
    where = LEVEL_WORDS.get(level.level, level.level)
    if level.ratio is None:
        why = f"nobody graded it {where}" if level.entry is None else f"graded {where}, but no error ÷ tolerance was recorded"
        return f'<td data-level="{level.level}" data-ratio="" class="rec none" title="{esc(why)}">not graded</td>'
    ok = bool(level.passed)
    tip = f"worst |recovered − true| ÷ tolerance {where}: {level.ratio:.4g}"
    return (f'<td data-level="{level.level}" data-ratio="{level.ratio!r}" data-pass="{"true" if ok else "false"}" '
            f'class="rec {"pass" if ok else "fail"}" title="{esc(tip)}"><span class="num">{level.ratio:.2g}×</span> '
            f'<span class="verdict">{"pass" if ok else "fail"}</span></td>')


def cost_cell(r: RoutineInfo) -> str:
    est = ' <span class="faint" title="an estimate">est.</span>' if r.cost_estimated else ""
    return f'<td class="num" title="{esc(r.cost_source)}">{usd_text(r.cost_usd)}{est}</td>'


def routine_row(r: RoutineInfo) -> str:
    needs = ", ".join(r.requires) if r.requires else "—"
    return (
        f'<tr data-routine="{esc(r.id)}">'
        f'<th scope="row"><a href="{r.path}">{esc(r.title)}</a><div class="rid"><code>{esc(r.id)}</code></div></th>'
        f'<td><span class="kind kind-{esc(r.kind_word)}">{esc(r.kind_word)}</span></td>'
        f'<td>{esc(r.setting)}</td>'
        f'<td><span class="status status-{slug(r.status)}">{esc(r.status)}</span></td>'
        f'<td class="num" title="{esc(r.wall_time_source)}">{seconds_text(r.wall_time_s)}</td>'
        f'<td class="num" title="{esc(r.operator_time_source)}">{seconds_text(r.operator_time_s)}</td>'
        f'{cost_cell(r)}'
        + "".join(recovery_cell(level) for level in r.levels)
        + f'<td class="needs">{esc(needs)}</td></tr>'
    )


def routines_table(rows: list[RoutineInfo], *, table_id: str = "") -> str:
    attrs = ' data-table="routines"' + (f' id="{table_id}"' if table_id else "")
    return table(ROUTINE_HEADERS, [routine_row(r) for r in rows], attrs=attrs, cls="routines")


def rung_table(t: TypeInfo, family: str, routines_by_id: dict[str, RoutineInfo]) -> str:
    rows = []
    for m in (m for m in t.models if m.family == family):
        current = ' data-current="true"' if m.current else ""
        badge = ' <span class="badge current">★ today\'s model</span>' if m.current else ""
        wear = ' <span class="badge">wear</span>' if m.wear else ""
        adds = " ".join(chip(f"/parameters/{t.id}/{n}/", n) for n in m.adds) or '<span class="faint">—</span>'
        ident = " ".join(chip(f"/routines/{rid}/", rid, title=routines_by_id[rid].title if rid in routines_by_id else "")
                         for rid in m.identified_by)
        if not ident:
            ident = '<span class="faint">nothing yet</span>' if m.adds else '<span class="faint">—</span>'
        n = len(m.parameters)
        rows.append(
            f'<tr data-model="{esc(m.id)}"{current}>'
            f'<td><span class="rung">{esc(m.rung)}</span> <span class="faint small">{esc(m.kind)}</span></td>'
            f'<td><a href="{m.path}">{esc(m.title)}</a>{badge}{wear}<div class="rid"><code>{esc(m.id)}</code></div></td>'
            f'<td class="num">{n} <span class="faint small">{"parameter" if n == 1 else "parameters"}</span></td>'
            f'<td>{adds}</td><td>{ident}</td></tr>'
        )
    return table(["Rung", "Model", "Parameters", "Adds", "Identified by"], rows, attrs=f' data-table="rungs" data-family="{esc(family)}"',
                 cls="rungs")


# ------------------------------------------------------------------------------------------------------- pages


# ------------------------------------------------------------------------------------------------------- the landing page
#
# WHY this shape (Zach, Daily Note 2026-11-20, "# Sim2Real routines"): pidtuna.com's section grammar - hero, proof, how, quickstart,
# promises, CTA - plus his three modes and bench vs deployed, in eight sections. Every number comes from website/data/landing.json
# (export_landing.py reads it out of a named file) and links to its source; a missing number says "not measured yet" and why. Prose that
# makes a claim lives in landing.json and is rendered by render_template; the words written here carry no number and no comparison.

GITHUB = "https://github.com/zacharyyamaoka/sim2real"
LANDING_PLACE = re.compile(r"\{(=[^{}]+|gate:[a-z0-9_.-]+|cmp:[a-z0-9_.-]+:[a-z0-9_.-]+|[a-z0-9][a-z0-9_.-]*)\}")
FORMATS = {"mm": "{n} mm", "°": "{n}°", "°/s": "{n}°/s", "× floor": "{n} × floor", "h": "{n} h", "": "{n}", "%": "{n}%",
           "×": "×{n}", "N·m": "{n} N·m"}
GATE_WORDS = {"pass": "pass", "fail": "fail", "unjudged": "not judged"}
COMPARE_WORDS = {-1: "smaller than", 0: "the same as", 1: "larger than"}
STATUS_WORDS = {"not_measured": "not measured yet", "not_built": "not built yet", "runs": "runs today"}
# the small label after each number in a cell (what the number is); a count that follows a stop number reads "worst of N stops"
# WHY "of runs" (review 2026-11-20 C5): arm_motion_bench's gate_pass_rate is the share of runs, every repeat counted, not of tasks
MEASURE_WORDS = {"stop_worst": "worst stop", "stop_median": "median stop", "stop_task_worst_median": "median task's worst stop",
                 "gate_pass_rate": "of runs within the gate", "tcp_rms": "TCP RMS", "joint_rms": "joint RMS", "stops": "stops",
                 "not_identified": "more carried, not identified",
                 "held_out_ratio": "", "held_out_tool": "", "held_out_flange": "", "floor": ""}
GATE_TITLES = {"stop_worst": "the worst stop against the tool gate", "gate_pass_rate": "every stop of every run against the tool gate",
               "stop_median": "a median above the tool gate proves a fail; at or under it proves nothing",
               "stop_task_worst_median": "a median above the tool gate proves a fail; at or under it proves nothing"}
ROBOT_WORDS = {"pendulum": "Pendulum", "ur_arm": "UR arm", "bam_arm": "BAM arm"}
RECOVERY_HEADS = {"recovered": "Recovered", "nominal": "Description's values", "fitted": "Fitted", "floor": "Floor"}
# WHY short comments on their own lines (review 2026-11-20 D4): the old trailing comments made the block scroll sideways at 1280 px
API_EXAMPLE = '''import sim2real
from bam_rack_twin.description import station_description
from sim2real.calibration import Budget, CalibrationConfig, Ledger

# calibrate() replays runs in a process pool that re-imports this file
if __name__ == "__main__":
    # the bench pendulum's description (it sits on CAN id 11):
    # typed parts with their priors, an MJCF, its unit
    rd = station_description(11)
    twin = sim2real.RobotTwin.from_robot_description(rd)
    config = CalibrationConfig(
        budget=Budget(settings=("bench",), equipment=("camera_tags",)))
    # what will run, in order, with its time and equipment; nothing moves
    schedule = twin.generate_schedule(config)
    print(schedule.summary())
    fitted = twin.calibrate(on="sim", config=config, callbacks=[Ledger()])
    report = fitted.evaluate()  # held-out error and the gates
    print(report.summary())
    print(fitted.data_)  # the runs it was fitted on
'''


class Landing:
    """landing.json plus what rendering it needs: the [n] of each source in the sources list."""

    def __init__(self, data: dict):
        self.data = data
        self.cite = {sid: i for i, sid in enumerate(data["sources"], 1)}

    def value(self, vid: str) -> dict:
        return self.data["values"][vid]

    def shown(self, vid: str) -> str:
        v = self.value(vid)
        return FORMATS[v["display_unit"]].format(n=f"{v['value'] * v['scale']:.{v['digits']}f}")

    def span(self, vid: str) -> str:
        v = self.value(vid)
        sid = v["source"]
        src = self.data["sources"][sid]
        before, _, after = FORMATS[v["display_unit"]].partition("{n}")
        number = f"{v['value'] * v['scale']:.{v['digits']}f}"
        text = (f'<span class="u">{esc(before)}</span>' if before else "") + f'<span class="n">{esc(number)}</span>' + \
            (f'<span class="u">{esc(after)}</span>' if after else "")
        return (f'<span class="v" data-value-id="{esc(vid)}" data-value="{v["value"] * v["scale"]!r}" data-unit="{esc(v["display_unit"])}" '
                f'data-source="{esc(sid)}">{text}<a class="src" href="#src-{esc(sid)}" title="{esc(src["shown"])}">'
                f'[{self.cite[sid]}]</a></span>')

    def verdict(self, vid: str) -> str:
        """The 1 mm tool gate at a stop: a worst stop passes or fails; a median above it proves a fail, at or under it proves nothing."""
        v, g = self.value(vid), self.value(self.data["gate"])
        if v["measure"] == "gate_pass_rate":
            return "pass" if v["value"] >= 1.0 - 1e-12 else "fail"
        value, limit = v["value"] * v["scale"], g["value"] * g["scale"]
        if v["measure"] == "stop_worst":
            return "pass" if value <= limit else "fail"
        return "fail" if value > limit else "unjudged"

    def gate(self, vid: str) -> str:
        verdict = self.verdict(vid)
        title = GATE_TITLES.get(self.value(vid)["measure"], "against the tool gate at a stop")
        return (f'<span class="gate gate-{verdict}" data-gate="{verdict}" data-gate-value="{esc(vid)}" '
                f'title="{esc(title)}">{GATE_WORDS[verdict]}</span>')

    def compare(self, a: str, b: str) -> str:
        va, vb = self.value(a), self.value(b)
        x, y = va["value"] * va["scale"], vb["value"] * vb["scale"]
        word = COMPARE_WORDS[0 if math.isclose(x, y, rel_tol=1e-9) else (1 if x > y else -1)]
        return f'<span data-compare data-a="{esc(a)}" data-b="{esc(b)}">{word}</span>'

    def render(self, template: str) -> str:
        """A landing.json template as HTML: {value-id}, {=name}, {gate:value-id}, {cmp:a:b}, `code` (the ruler's render, as markup)."""
        out = []
        for i, part in enumerate(template.split("`")):
            if i % 2:
                out.append(f"<code>{esc(part)}</code>")
                continue
            pos = 0
            for m in LANDING_PLACE.finditer(part):
                out.append(esc(part[pos:m.start()]))
                body = m.group(1)
                if body.startswith("="):
                    out.append(f'<span class="name">{esc(body[1:])}</span>')
                elif body.startswith("gate:"):
                    out.append(self.gate(body[5:]))
                elif body.startswith("cmp:"):
                    _, a, b = body.split(":")
                    out.append(self.compare(a, b))
                else:
                    out.append(self.span(body))
                pos = m.end()
            out.append(esc(part[pos:]))
        return "".join(out)

    def plain(self, template: str) -> str:
        """The same template as plain text (an alt text)."""
        def one(m):
            body = m.group(1)
            if body.startswith("="):
                return body[1:]
            if body.startswith("gate:"):
                return GATE_WORDS[self.verdict(body[5:])]
            return self.shown(body) if not body.startswith("cmp:") else ""
        return " ".join(LANDING_PLACE.sub(one, template).replace("`", "").split())

    def img(self, mid: str, *, alt: str | None = None) -> str:
        """A picture with its own pixel size (WHY, review 2026-11-20: without width/height the page shifts as each one loads)."""
        m = self.data["media"][mid]
        size = f' width="{m["width"]}" height="{m["height"]}"' if m.get("width") else ""
        return f'<img src="/assets/{esc(m["file"])}" alt="{esc(alt if alt is not None else self.plain(m["what"]))}"{size}>'

    def figure(self, mid: str, cls: str = "") -> str:
        return (f'<figure class="shot {cls}" data-media="{esc(mid)}">{self.img(mid)}<figcaption>{self.render(self.data["media"][mid]["what"])} '
                f'<a class="media-src" href="#media-{esc(mid)}">where it is from</a></figcaption></figure>')

    def numbers(self, ids: list[str]) -> list[str]:
        """A cell's numbers, one line each, with what each one is; a stop count reads with the number before it."""
        lines, i = [], 0
        while i < len(ids):
            vid = ids[i]
            measure = self.value(vid)["measure"]
            nxt = ids[i + 1] if i + 1 < len(ids) else None
            nmeasure = self.value(nxt)["measure"] if nxt else None
            if measure == "stop_worst" and nmeasure == "stops":
                lines.append(f'{self.span(vid)} <span class="mw">worst of</span> {self.span(nxt)} <span class="mw">stops</span>')
                i += 2
                continue
            if measure == "within_gate" and nmeasure == "stops":
                lines.append(f'{self.span(vid)} <span class="mw">of</span> {self.span(nxt)} <span class="mw">stops within the gate</span>')
                i += 2
                continue
            if measure == "recovered" and nmeasure == "graded":
                lines.append(f'{self.span(vid)} <span class="mw">of</span> {self.span(nxt)}')
                i += 2
                continue
            word = MEASURE_WORDS.get(measure, "")
            lines.append(self.span(vid) + (f' <span class="mw">{esc(word)}</span>' if word else ""))
            i += 1
        return lines

    def cell(self, key: str, spec: dict, *, head: str = "") -> str:
        # WHY data-head: on a phone the table stacks into cards and each cell shows its column's title (CSS), so nobody scrolls sideways
        h = f' data-head="{esc(head)}"' if head else ""
        if "status" in spec:
            return (f'<td data-cell="{key}"{h} class="cell status-cell"><span class="st st-{esc(spec["status"])}" '
                    f'data-status="{esc(spec["status"])}">{STATUS_WORDS[spec["status"]]}</span>'
                    f'<span class="why" data-why>{self.render(spec["why"])}</span></td>')
        # WHY a headline (review 2026-11-20 D1): the first number (the one the gate judges, by the picks' order) reads large with its
        # verdict beside it, the rest small under it, so each cell says one thing at a glance
        first, *rest = self.numbers(spec["values"])
        chip = f" {self.gate(spec['gate'])}" if spec.get("gate") else ""
        body = f'<div class="num-line num-head">{first}{chip}</div>'
        if rest:
            body += '<div class="num-rest">' + "".join(f'<div class="num-line">{line}</div>' for line in rest) + "</div>"
        ctl = spec.get("controller")
        if ctl:
            text = self.data["labels"][ctl["label"]]["text"]
            body += (f'<div class="ctl"><span data-ctl-words>{self.render(ctl["words"])}</span> '
                     f'<code class="ctl-code" data-label-id="{esc(ctl["label"])}" title="the controller as its file names it">{esc(text)}'
                     '</code></div>')
        return f'<td data-cell="{key}"{h} class="cell">{body}</td>'


def _seam_steps(tune_on_main: bool) -> tuple:
    return (
        ("describe", "Describe", ("rd: typed parts,", "priors and an MJCF"), ""),
        ("twin", "Twin", ("RobotTwin.", "from_robot_description(rd)"), ""),
        ("schedule", "Plan", ("generate_schedule(config)", "→ CalibrationSchedule"), ""),
        ("calibrate", "Calibrate", ("calibrate(config)", "sim | rack"), ""),
        ("tune", "Tune", ("PID tuna tune step", "main" if tune_on_main else "on a branch"), "main" if tune_on_main else "branch"),
        ("callbacks", "Record", ("Ledger, then", "a W&B copy"), ""),
        ("fitted", "Fitted twin", ("data_ · plan_ · record_", ""), ""),
        ("evaluate", "Evaluate", ("evaluate(): gates", "on held-out runs"), ""),
        ("preflight", "Preflight", ("preflight(fitted)", "before it ships"), ""),
        ("deployed", "Deployed", ("monitor → refit →", "keep if it wins"), "designed"),
    )


def _seam_list(tune_on_main: bool, links: dict[str, str]) -> str:
    """The same ten steps as a list a phone stacks (WHY, review 2026-11-20 D7: the diagram's text is unreadable at phone width)."""
    items = []
    for key, title, (l1, l2), status in _seam_steps(tune_on_main):
        badge = {"branch": "on a branch", "designed": "designed"}.get(status, "")
        tag = f' <span class="badge designed">{badge}</span>' if badge else ""
        second = "" if status == "branch" else l2
        detail = l1 + ("" if l1.endswith(".") or not second else " ") + second
        items.append(f'<li class="seam-li{" seam-li-amber" if badge else ""}"><a href="{esc(links[key])}"><strong>{esc(title)}</strong>{tag}'
                     f'<span class="seam-li-code">{esc(detail)}</span></a></li>')
    return f'<ol class="seam-list">{"".join(items)}</ol>'


def _seam_svg(tune_on_main: bool, links: dict[str, str]) -> str:
    """How it works: the seam from a description to a deployed twin, ten steps in two rows. No numbers; every step links to its page."""
    w, h, gap, top, row2 = 204, 84, 36, 18, 164
    steps = _seam_steps(tune_on_main)
    parts = []
    for i, (key, title, (l1, l2), status) in enumerate(steps):
        col, y = i % 5, (top if i < 5 else row2)
        x = col * (w + gap) + 2
        cls = "seam-box" + (" seam-branch" if status == "branch" else "") + (" seam-designed" if status == "designed" else "")
        st = f' data-status="{status}"' if status else ""
        badge = ""
        if status in ("branch", "designed"):
            word = "on a branch" if status == "branch" else "designed"
            badge = (f'<rect class="seam-badge-bg" x="{x + w - 92}" y="{y - 10}" width="86" height="20" rx="10"/>'
                     f'<text class="seam-badge" x="{x + w - 49}" y="{y + 4}" text-anchor="middle">{word}</text>')
            if status == "branch":
                l2 = ""
        parts.append(
            f'<g data-step="{key}"{st}><a href="{esc(links[key])}"><rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="10"/>'
            f'<text class="seam-title" x="{x + 14}" y="{y + 28}">{esc(title)}</text>'
            f'<text class="seam-code" x="{x + 14}" y="{y + 50}">{esc(l1)}</text>'
            f'<text class="seam-code" x="{x + 14}" y="{y + 68}">{esc(l2)}</text>{badge}</a></g>'
        )
    arrows = []
    for i in range(4):  # row arrows
        for y in (top + h / 2, row2 + h / 2):
            x1 = (i + 1) * (w + gap) - gap + 6
            arrows.append(f'<path class="seam-arrow" d="M{x1} {y} h{gap - 14}" marker-end="url(#seam-head)"/>')
    # the wrap from the end of row one to the start of row two
    ex = 4 * (w + gap) + 2 + w / 2
    sx = 2 + w / 2
    mid = top + h + (row2 - top - h) / 2
    arrows.append(f'<path class="seam-arrow" d="M{ex} {top + h + 4} V{mid} H{sx} V{row2 - 8}" marker-end="url(#seam-head)"/>')
    width = 5 * w + 4 * gap + 4
    return (f'<svg class="seam" viewBox="0 0 {width} {row2 + h + 8}" role="img" aria-labelledby="seam-t">'
            f'<title id="seam-t">How sim2real works: describe, twin, plan, calibrate, tune, record, fitted twin, evaluate, preflight, deployed'
            f'</title><defs><marker id="seam-head" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="seam-head"/></marker></defs>'
            + "".join(arrows) + "".join(parts) + "</svg>")


def home(types: list[TypeInfo], routines: list[RoutineInfo], examples: list[ExampleInfo], docs: list[tuple[str, str, str, str]],
         landing: dict | None = None, **ctx) -> str:
    if landing is None:  # WHY a notice, never a page of made-up numbers: the ruler fails it until landing.json exists
        body = ('<div class="lp"><section class="lp-sec" data-section="hero"><h1>sim2real</h1><p class="warn">The landing page has no data: '
                'website/data/landing.json is missing. Run website/build/export_landing.py.</p></section></div>')
        return shell(title="sim2real", description="sim2real: calibration for robot twins.", path="/", body=body, section="home",
                     current="home", types=types, wide=True, **ctx)
    L = Landing(landing)
    data = landing
    by_id = {r.id: r for r in routines}
    settings = {s: sum(r.setting == s for r in routines) for s in ("bench", "deployed", "both")}
    tune_on_main = by_id.get("pid.pidtuna") is not None and by_id["pid.pidtuna"].kind == "tune"

    # 1 hero ------------------------------------------------------------------------------------------------------------------
    hero = data["hero"]
    lines = "".join(f'<p class="readout-line" data-line>{L.render(line)}</p>' for line in hero["lines"])
    # WHY a strip of the three robots (review 2026-11-20 D2): the hero loop shows one robot; Zach asked to see all three, so each real
    # robot's own picture (the same files its row shows) sits in the first screen and opens its row
    rows_by_id = {row["id"]: row for robot in data["robots"] for row in robot["rows"]}
    strip = "".join(
        f'<a class="robot-pick" href="#row-{esc(rid)}">{L.img(rows_by_id[rid]["media"], alt=L.plain(rows_by_id[rid]["title"]))}'
        f'<span class="robot-pick-name">{L.render(name)}</span></a>'
        for rid, name in (("pendulum-real", "The {=1-DOF} pendulum"), ("urwrist-real", "The UR arm's wrist rig"), ("bamarm-track", "The BAM arm"))
        if rows_by_id.get(rid, {}).get("media"))
    hero_html = f"""<section class="lp-hero" data-section="hero" id="hero" aria-labelledby="hero-h">
  <div class="hero-copy">
    <p class="eyebrow">{L.render(hero["eyebrow"])}</p>
    <h1 id="hero-h">{L.render(hero["h1"])}</h1>
    <div class="robot-strip" aria-label="The three robots on this page">{strip}</div>
    <p class="lead">{L.render(hero["lead"])}</p>
    <p class="today" data-today>{L.render(hero["today"])}</p>
    <div class="cta">
      <a class="btn primary" href="#api">Quickstart</a>
      <a class="btn" href="#how">How it works</a>
      <a class="btn" href="#proof">See the numbers</a>
      <a class="btn" href="/routines/">All routines</a>
      <a class="btn ghost" href="{GITHUB}" rel="noopener">Source on GitHub</a>
    </div>
  </div>
  <div class="hero-stage">{L.figure(hero["media"], "hero-shot")}
    <div class="readout" data-readout>
      <p class="readout-head"><span class="where where-pseudo" data-chip="pseudo-real">pseudo-real</span> sim2real's own <code>calibrate()</code>, against a hidden world whose values differ from the description's on purpose</p>
      {lines}
    </div>
    <p class="counts"><span data-count="types">{len(types)}</span> part types · <span data-count="routines">{len(routines)}</span> calibration routines, read from the registries</p>
  </div>
</section>"""

    # 2 proof -----------------------------------------------------------------------------------------------------------------
    metrics = data["metrics"]
    defs = "".join(f'<div class="mdef"><dt>{esc(metrics[k]["title"])}</dt><dd data-metric-def="{k}">{L.render(metrics[k]["definition"])}</dd></div>'
                   for k in ("sim", "on_real", "tuned"))
    heads = "".join(f'<th scope="col" data-metric="{k}">{esc(metrics[k]["title"])}</th>' for k in ("sim", "on_real", "tuned"))
    body_rows, note_groups = [], []
    for robot in data["robots"]:
        body_rows.append(f'<tr class="robot-group"><th scope="rowgroup" colspan="4">{L.render(robot["title"])}</th></tr>')
        notes = []
        for row in robot["rows"]:
            fig = L.figure(row["media"], "row-shot") if row.get("media") else ""
            where = row["where"]
            th = (f'<th scope="row" data-cell="robot" class="robot-cell"><div class="row-title" data-title><a href="{esc(row["link"])}">'
                  f'{L.render(row["title"])}</a></div><span class="where where-{"real" if where == "real" else "pseudo"}" data-where-chip>{where}</span>'
                  f'<p class="target" data-target>{L.render(row["target"])}</p>{fig}</th>')
            cells = "".join(L.cell(k, row["cells"][k], head=metrics[k]["title"]) for k in ("sim", "on_real", "tuned"))
            body_rows.append(f'<tr data-row="{esc(row["id"])}" data-robot="{esc(robot["id"])}" data-where="{esc(where)}" '
                             f'id="row-{esc(row["id"])}">{th}{cells}</tr>')
            notes += [f'<li data-note-for="{esc(row["id"])}">{L.render(n)}</li>' for n in row.get("notes", [])]
        if notes:
            note_groups.append(f'<li class="note-group"><span class="note-head">{esc(ROBOT_WORDS[robot["id"]])}</span><ul>{"".join(notes)}</ul></li>')
    caveat = ('Measured by each robot\'s own lab tooling (bam_rack_twin\'s pendulum scorer, the UR wrist rig\'s scripts, arm_motion_bench), '
              'not by sim2real. sim2real\'s <code>calibrate(on="real")</code> is built and tested on the rack twin; no hardware run of it is '
              'recorded yet. sim2real\'s own numbers are in <a href="#recovery">Does calibration find the truth?</a>')
    # WHY these words (review 2026-11-20 C4, D1): the rows do not share one set of measures or one matched target, so the intro says
    # what every cell leads with and how a median is judged, and each row says how its cells were matched
    proof_html = f"""<section class="lp-sec" data-section="proof" id="proof" aria-labelledby="proof-h">
  <div class="sec-head"><p class="kicker">Measured on the robots</p><h2 id="proof-h">Sim, Sim on Real, Sim on Real (tuned)</h2>
  <p>Fitting a model only pays if the robot then hits its target. Each row plays one target three ways: on the twin, on the robot as found, and on the robot after tuning. Each cell leads with the tool error at a stop and its verdict against the gate of {L.span(data["gate"])}: a worst stop passes or fails, a median above the gate fails, and a median at or under it is not judged. The rest is what that run's own file records; the notes under the table say what differs between a row's cells.</p></div>
  <dl class="metric-defs">{defs}</dl>
  <div class="table-wrap proof-wrap"><table class="proof" data-table="metrics">
    <caption><span data-caveat>{caveat}</span></caption>
    <thead><tr><th scope="col">Robot and target</th>{heads}</tr></thead>
    <tbody>{"".join(body_rows)}</tbody>
  </table></div>
  <ul class="notes" data-notes="proof">{"".join(note_groups)}</ul>
</section>"""

    # 3 modes, with the hidden-truth table -------------------------------------------------------------------------------------
    cards = []
    for mode in data["modes"]:
        code = (code_block(mode["call"], wrap=True, label=f"mode {mode['n']} call", pre_attrs=f' data-code="mode-{mode["n"]}"')
                if mode["call"] else '<p class="no-call">No call to show: this verb does not exist yet.</p>')
        robots_li = "".join(
            f'<li data-robot="{r}" data-status="{esc(spec["status"])}"><span class="st st-{esc(spec["status"])}">{STATUS_WORDS[spec["status"]]}</span> '
            f'<span class="who">{ROBOT_WORDS[r]}</span> <span class="why" data-why>{L.render(spec["why"])}</span></li>'
            for r, spec in mode["robots"].items())
        cards.append(f'<article class="mode" data-mode="{mode["n"]}"><div class="mode-top"><span class="mode-n" data-mode-n="{mode["n"]}">{mode["n"]}</span>'
                     f'<h3 data-mode-title>{L.render(mode["title"])}</h3></div><p class="mode-what" data-mode-what>{L.render(mode["what"])}</p>'
                     f'{code}<ul class="mode-robots">{robots_li}</ul></article>')
    rec_rows, rec_notes = [], []
    for row in data["recovery"]:
        meta = []
        rec = row["recorded"]
        if rec:
            src = data["sources"][rec["source"]]
            meta.append(f'recorded <time data-source-date="{esc(rec["source"])}" datetime="{esc(src["dated"])}">{esc(src["dated"][:10])}</time>')
            if src["in_repo"]:
                meta.append(f'commit <code data-commit="{esc(rec["source"])}">{esc(src["commit"][:7])}</code>')
            if rec.get("routines"):
                meta.append(f'routines <code data-label-id="{esc(rec["routines"])}">{esc(data["labels"][rec["routines"]]["text"])}</code>')
        call = f'<code class="call" data-call>{wrap_points(esc(row["via"]))}</code>' if row["via"] else ""
        th = (f'<th scope="row" data-cell="robot" class="robot-cell"><div class="row-title" data-title>{L.render(row["title"])}</div>{call}'
              f'<p class="measure" data-measure>{L.render(row["measure"])}</p>'
              + (f'<p class="rec-meta">{" · ".join(meta)}</p>' if meta else "") + "</th>")
        cells = "".join(L.cell(k, row["cells"][k], head=RECOVERY_HEADS[k]) for k in ("recovered", "nominal", "fitted", "floor"))
        rec_rows.append(f'<tr data-row="{esc(row["id"])}" data-robot="{esc(row["robot"])}" id="recovery-{esc(row["id"])}">{th}{cells}</tr>')
        rec_notes += [f'<li data-note-for="{esc(row["id"])}">{L.render(n)}</li>' for n in row.get("notes", [])]
    modes_html = f"""<section class="lp-sec" data-section="modes" id="modes" aria-labelledby="modes-h">
  <div class="sec-head"><p class="kicker">Today</p><h2 id="modes-h">What you can do today</h2>
  <p>Three ways to use a twin, and where each one stands for each robot.</p></div>
  <div class="modes">{"".join(cards)}</div>
  <p class="muted small">In sim2real the second and third are one call: the world it calibrates against is already pseudo-real. Run either inside <code>if __name__ == "__main__":</code> (the API section shows the whole script).</p>
  <h3 class="sub-h" id="recovery">Does calibration find the truth?</h3>
  <p class="muted">In sim the answer is known. These are sim2real's own numbers: modelling error, twin against a hidden world, on runs it never trained on.</p>
  <div class="table-wrap"><table class="recovery-proof" data-table="recovery-proof">
    <thead><tr><th scope="col">Robot, call and measure</th>{"".join(f'<th scope="col">{esc(RECOVERY_HEADS[k])}</th>' for k in ("recovered", "nominal", "fitted", "floor"))}</tr></thead>
    <tbody>{"".join(rec_rows)}</tbody>
  </table></div>
  <ul class="notes" data-notes="recovery">{"".join(rec_notes)}</ul>
</section>"""

    # 4 how it works ------------------------------------------------------------------------------------------------------------
    links = {
        "describe": "/types/", "twin": "/api/#api-RobotTwin-from_robot_description", "schedule": "/api/#api-RobotTwin-generate_schedule",
        "calibrate": "/api/#api-RobotTwin-calibrate", "tune": "/routines/pid.pidtuna/", "callbacks": "/api/#api-Ledger",
        "fitted": doc_anchor(docs, "calibrate", "The twin holds its data"), "evaluate": "/api/#api-RobotTwin-evaluate",
        "preflight": doc_anchor(docs, "guide", "`sim2real.preflight("), "deployed": "#deployed",
    }
    kinds = doc_anchor(docs, "calibrate", "The routine kinds")
    how_html = f"""<section class="lp-sec" data-section="how" id="how" aria-labelledby="how-h">
  <div class="sec-head"><p class="kicker">How it works</p><h2 id="how-h">From a description to a fitted twin</h2>
  <p>From the robot description to a twin that is fitted, checked and ready to ship. Each step opens its page.</p></div>
  <div class="seam-wrap">{_seam_svg(tune_on_main, links)}</div>
  {_seam_list(tune_on_main, links)}
  <p class="muted small">Routines come in four kinds, <a href="{esc(kinds)}">configure → fit → tune → measure</a>, and that is their order when nothing else orders them.</p>
</section>"""

    # 5 the API on one screen ------------------------------------------------------------------------------------------------
    wandb = doc_anchor(docs, "guide", "`sim2real.tracking.calibrate_wandb.WandbLogger(")
    api_html = f"""<section class="lp-sec" data-section="api" id="api" aria-labelledby="api-h">
  <div class="sec-head"><p class="kicker">Quickstart</p><h2 id="api-h">The API on one screen</h2>
  <p>There is no install command yet: sim2real is not on PyPI, its dependencies install from local checkouts, and this example reads the pendulum's description from bam_rack_twin, a workstation package. It runs there today.</p></div>
  <div class="api-code">{code_block(API_EXAMPLE, label="quickstart", pre_attrs=' data-code="api"')}</div>
  <ul class="api-notes">
      <li><a href="/api/#api-CalibrationConfig"><code>CalibrationConfig</code></a>: which models to fit, what is already known, what to include or leave out, the noise and the budget.</li>
      <li><a href="/api/#api-Budget"><code>Budget</code></a>: <code>settings=</code> says where it runs (bench, deployed), <code>equipment=</code> what you have. A routine needing anything else is dropped, and the schedule names the item and its price.</li>
      <li><code>callbacks=</code>: <a href="/api/#api-Ledger"><code>Ledger()</code></a> writes every event and the record; <a href="{esc(wandb)}">WandbLogger</a> keeps a W&amp;B copy of it.</li>
      <li><code>fitted.data_</code>: the runs it was fitted on. <code>fitted.calibrate(data=fitted.data_ + more)</code> refits with new runs.</li>
      <li><code>on="real", transport=</code>: the same call on hardware, through a transport you pass. Built and tested on the rack twin; no robot run of it is recorded yet.</li>
  </ul>
  <p class="api-more"><a href="/examples/pendulum_can11/">The pendulum example: <code>calibrate()</code> on a hidden world, with its recorded output</a> · <a href="/api/">the whole API</a> · <a href="/docs/guide/">the guide</a></p>
</section>"""

    # 6 bench today, deployed next ----------------------------------------------------------------------------------------------
    life = data["lifecycle"]
    today = []
    for item in life["today"]:
        go = ""
        if item.get("href"):
            go = (f'<a class="go" href="{esc(item["href"])}" title="{esc(item["href"])}" aria-label="Open {esc(item["href"])}">'
                  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                  'stroke-linejoin="round" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8"/></svg></a>')
        today.append(f'<li data-today-item>{go}{L.render(item["text"])}</li>')
    not_built = "".join(f'<li data-not-built="{esc(item["name"])}">{L.render(item["text"])}</li>' for item in life["not_built"])
    # WHY each arrow travels with the step after it (review 2026-11-20 D9): a wrapped line never ends on a dangling arrow
    loop = " ".join((f'<span class="loop-item">{"" if i == 0 else "<span class=\"loop-arrow\" aria-hidden=\"true\">→</span> "}'
                     f'<span class="loop-step">{esc(step)}</span></span>') for i, step in enumerate(life["loop"]))
    life_html = f"""<section class="lp-sec" data-section="lifecycle" id="bench-or-deployed" aria-labelledby="life-h">
  <div class="sec-head"><p class="kicker">Bench and deployed</p><h2 id="life-h">Bench today, deployed next</h2>
  <p>Every routine says where it runs. <code>Budget(settings=("bench",))</code> keeps the <span data-setting-count="bench">{settings["bench"]}</span> bench routines and the <span data-setting-count="both">{settings["both"]}</span> that run anywhere; <code>("deployed",)</code> keeps the <span data-setting-count="deployed">{settings["deployed"]}</span> that run on a robot at work and the same <span data-setting-count="both">{settings["both"]}</span> that run anywhere.</p>
  <p><code>Budget(equipment=(...))</code> says what you have: a routine needing anything else is dropped, and the schedule names the item and its price.</p></div>
  <div class="deployed">
    <h3 id="deployed">Deployed: lifetime calibration and monitoring <span class="badge designed" data-status="designed">designed, not built</span></h3>
    <p class="lead-sm">{L.render(life["lead"])}</p>
    <p class="loop" data-loop>{loop}</p>
    <div class="life-grid">
      <div><h4>There today</h4><ul class="life-list">{"".join(today)}</ul></div>
      <div><h4>Not built yet</h4><ul class="life-list not-built">{not_built}</ul></div>
    </div>
    <p><a href="/docs/deployed/">The whole design, with its code sketch</a></p>
  </div>
</section>"""

    # 7 promises ------------------------------------------------------------------------------------------------------------------
    promises_html = f"""<section class="lp-sec" data-section="promises" aria-labelledby="promises-h">
  <h2 class="visually-hidden" id="promises-h">What sim2real promises</h2>
  <div class="promises">
    <div class="promise" data-promise><strong>The fit never sees the answer.</strong><p>A hidden world stays sealed while the twin fits; the grade opens it only afterwards, and the score comes from runs the fit never used.</p></div>
    <div class="promise" data-promise><strong>It never moves a motor by itself.</strong><p>A calibration plans its runs and asks for them; on hardware a transport you pass moves the robot, and nothing is written to a board or a description unless you say so.</p></div>
    <div class="promise" data-promise><strong>It ships PD and feed-forward.</strong><p>The controller sim2real hands over is PD with feed-forward from the fitted values, and <code>preflight()</code> refuses one that integrates before it ships.</p></div>
  </div>
  <div class="cta lp-cta">
    <a class="btn primary" href="/routines/">Browse the routines</a>
    <a class="btn" href="/api/">API reference</a>
    <a class="btn" href="/docs/guide/">The guide</a>
    <a class="btn" href="/docs/deployed/">The deployed design</a>
    <a class="btn ghost" href="{GITHUB}" rel="noopener">GitHub</a>
  </div>
</section>"""

    # 8 sources --------------------------------------------------------------------------------------------------------------------
    stale = set(data.get("stale_sources", ()))
    # WHY span.mono, not <code>, in the two lists: a sha, a dated snapshot or an ffmpeg filter is a record, not code to run (the ruler
    # reads every <code> for typed numbers; these items are exempt as records, their code would not be)
    src_items = []
    for sid, src in data["sources"].items():
        flags = []
        if src["moving"]:
            flags.append('<span class="flag">still being written; the page cites the frozen copy</span>')
        if sid in stale:
            flags.append('<span class="flag bad">stale: re-export</span>')
        link = ""
        if src["in_repo"]:
            url = f'{GITHUB}/blob/{src["commit"]}/{src["path"]}'
            link = f' · <a href="{esc(url)}" rel="noopener">on GitHub at {esc(src["commit"][:7])}</a>'
        else:
            link = f' · snapshot <span class="mono">{esc(src["snapshot"])}</span>'
        src_items.append(
            f'<li id="src-{esc(sid)}" data-source-id="{esc(sid)}" data-sha256="{esc(src["sha256"])}"><span class="src-what">{esc(src["what"])}</span>'
            f'<span class="src-meta"><span class="mono">{esc(src["shown"])}</span> · sha256 <span class="mono">{esc(src["sha256"][:12])}</span> · dated '
            f'{esc(src["dated"][:10])} · <span class="kind-chip">{esc(src["kind"])}</span>{link} {" ".join(flags)}</span></li>')
    media_items = []
    for mid, m in data["media"].items():
        fc = m["frames_checked"]
        # WHY the time and "UTC" (review 2026-11-20): a bare UTC date read as tomorrow on the workstation's clock
        check = (f'frames checked by {esc(fc["by"])} at {esc(fc["utc"][:10])} {esc(fc["utc"][11:16])} UTC ({esc(plural(fc["frames"], "frame"))}: '
                 'no people, no serials, no burned-in text)' if fc.get("by") else "frames not checked yet")
        media_items.append(
            f'<li id="media-{esc(mid)}" data-media-id="{esc(mid)}"><span class="src-what">{esc(L.plain(m["what"]))}</span>'
            f'<span class="src-meta"><span class="mono">{esc(m["file"])}</span> · sha256 <span class="mono">{esc(m["sha256"][:12])}</span> · cut from '
            f'<span class="mono">{esc(m["shown"])}</span> (report <span class="mono">{esc(m["report"])}</span>) · filter '
            f'<span class="mono">{esc(m["filter"])}</span> · {check}</span></li>')
    stamp = ctx.get("stamp", "sim2real")
    # WHY folded (review 2026-11-20 D9): the list is a reference, about two screens on a phone; every [n] still opens its entry (the
    # script below opens the fold when a link lands inside it)
    sources_html = f"""<section class="lp-sec sources" data-section="sources" id="sources" aria-labelledby="sources-h">
  <h2 id="sources-h">Where every number comes from</h2>
  <p class="muted">Every number on this page names its file: its sha256, its date and whether it is real, sim or pseudo-real. A missing number says not measured yet, and why.</p>
  <details class="src-fold" id="sources-list"><summary>The files, with their hashes and dates</summary>
  <ol class="src-list">{"".join(src_items)}<li id="src-registry" data-source-id="registry"><span class="src-what">The part-type and routine counts, the bench and deployed counts, and the tune step's state</span><span class="src-meta">sim2real's registries (<code>cards/domain.py</code>, <code>cards/calibration.py</code>), read at build time from {esc(stamp)}</span></li></ol>
  <h3 class="sub-h">Pictures</h3>
  <ul class="src-list media-list">{"".join(media_items)}</ul>
  </details>
  <script>(function(){{var fold=document.getElementById("sources-list");function open(){{var id=location.hash.slice(1);var el=id&&document.getElementById(id);if(el&&fold&&fold.contains(el)){{fold.open=true;el.scrollIntoView();}}}}window.addEventListener("hashchange",open);open();}})();</script>
</section>"""

    body = f'<div class="lp">\n{hero_html}\n{proof_html}\n{modes_html}\n{how_html}\n{api_html}\n{life_html}\n{promises_html}\n{sources_html}\n</div>'
    return shell(
        title="sim2real · calibration for robot twins",
        description="Describe your robot in CAD and sim2real builds its twin, plans the calibration routines your bench can run, fits them "
                    "and scores the twin on runs it never saw.",
        path="/", body=body, section="home", current="home", types=types, wide=True, page_class="landing", **ctx,
    )  # fmt: skip


def types_index(types: list[TypeInfo], **ctx) -> str:
    cards = "".join(
        f'<a class="card" href="{t.path}"><span class="card-name">{esc(t.title)}</span>'
        f'<span class="card-sum">{esc(t.covers)}. {plural(len(t.models), "model")}, {plural(len(t.parameters), "parameter")}, '
        f'{plural(len(t.routines), "routine")}.</span></a>'
        for t in types
    )
    body = f"""<article class="prose">
{crumbs(("Types", None))}
<h1 id="all-types">All types</h1>
<p class="lead">{len(types)} generic types, never an instance: a type is "an integrated servo", not CAN 11. Each lists its model rungs, their parameters and the routines that calibrate them. A part's designer declares which models and routines apply.</p>
<div class="grid">{cards}</div>
</article>"""
    return shell(title="All types · sim2real", description=f"All {len(types)} sim2real generic types.", path="/types/", body=body,
                 section="types", current="types-index", types=types, **ctx)


def type_page(t: TypeInfo, types: list[TypeInfo], routines_by_id: dict[str, RoutineInfo], **ctx) -> str:
    toc: list[tuple[str, str, int]] = [("models", "Model rungs", 2)]
    by_type = {x.id: x for x in types}
    families = []
    for family in t.families:
        if not any(m.family == family for m in t.models):
            continue
        anchor = f"family-{slug(family)}"
        toc.append((anchor, f"{family} family", 3))
        families.append(f'{heading(3, f"{family} family", anchor)}{rung_table(t, family, routines_by_id)}')
    toc.append(("routines", "Calibration routines", 2))
    rows = [routines_by_id[rid] for rid in t.routines]
    if rows:
        routine_html = (f'<p class="muted">Every catalog routine that identifies one of its parameters or configures its settings. Recovery is '
                        f'the worst |recovered − true| ÷ tolerance against a hidden truth at each noise level (≤ 1 passes).</p>'
                        f'{routines_table(rows)}')
    else:
        routine_html = '<p class="muted">There is no calibration routine for this type yet: nothing in the catalog identifies its parameters.</p>'
    toc.append(("parameters", "Parameters", 2))
    prow = []
    for p in t.parameters:
        prow.append(f'<tr><th scope="row"><a href="{p.path}"><code>{esc(p.name)}</code></a></th><td>{esc(p.unit or "-")}</td>'
                    f'<td>{esc(p.family)}</td><td><a href="/models/{t.id}/{p.introduced_in}/"><code>{esc(p.introduced_in)}</code></a></td>'
                    f'<td class="num">{len(p.routines) or "<span class=faint>none</span>"}</td></tr>')
    members = ""
    if t.members:
        chips = " ".join(chip(by_type[ty].path, f"{count} × {by_type[ty].title}" + (f" ({role})" if role else "")) if ty in by_type
                         else esc(f"{count} × {ty}") for ty, count, role in t.members)
        members = f'<div class="meta-row"><span class="meta-k">Made of</span><span class="meta-v">{chips}</span></div>'
    current = [m for m in t.models if m.current]
    today = " + ".join(f'<a href="{m.path}"><code>{esc(m.id)}</code></a>' for m in current) or '<span class="faint">none marked</span>'
    body = f"""<article class="prose wide-table">
{crumbs(("Types", "/types/"), (t.title, None))}
<h1 id="top">{esc(t.title)}</h1>
<p class="lead">{esc(t.covers[:1].upper() + t.covers[1:])}.</p>
<div class="meta">
  <div class="meta-row"><span class="meta-k">Type id</span><code>{esc(t.id)}</code></div>
  <div class="meta-row"><span class="meta-k">Today's model</span><span class="meta-v">{today}</span></div>
  <div class="meta-row"><span class="meta-k">Families</span><span class="meta-v">{esc(", ".join(t.families))}</span></div>
  {members}
</div>
{f'<p class="muted">{inline(t.note)}</p>' if t.note else ""}
<section aria-labelledby="models">{heading(2, "Model rungs", "models")}
<p class="muted">Each rung holds the parameters of the rungs below it in its family, plus what it adds. ★ marks today's model; the routines in the last column identify what that rung adds.</p>
{"".join(families)}</section>
<section aria-labelledby="routines">{heading(2, "Calibration routines", "routines")}{routine_html}</section>
<section aria-labelledby="parameters">{heading(2, "Parameters", "parameters")}
{table(["Parameter", "Unit", "Family", "Introduced in", "Routines"], prow, cls="kv")}</section>
</article>"""
    return shell(title=f"{t.title} · sim2real", description=f"{t.title}: {t.covers}. Model rungs, parameters and calibration routines.",
                 path=t.path, body=body, section="types", current=t.id, toc=toc, types=types, wide=True, **ctx)


def model_page(t: TypeInfo, m: ModelInfo, types: list[TypeInfo], routines_by_id: dict[str, RoutineInfo], **ctx) -> str:
    params = {p.name: p for p in t.parameters}
    rows = []
    for n in m.parameters:
        p = params.get(n)
        ids = p.routines if p else ()
        ident = " ".join(chip(f"/routines/{rid}/", rid) for rid in ids) or '<span class="faint">no routine yet</span>'
        added = '<span class="badge current">added here</span>' if n in m.adds else ""
        rows.append(f'<tr><th scope="row"><a href="/parameters/{t.id}/{n}/"><code>{esc(n)}</code></a> {added}</th>'
                    f'<td>{esc((p.unit if p else "") or "-")}</td><td>{ident}</td></tr>')
    siblings = [x for x in t.models if x.family == m.family]
    ladder = " ".join(
        (f'<span class="chip on" aria-current="page">{esc(x.rung)} {esc(x.name)}</span>' if x.id == m.id else chip(x.path, f"{x.rung} {x.name}"))
        for x in siblings
    )
    refs = "".join(f"<li>{ext_link(url, title)}</li>" for title, url in m.references)
    equation = (f'<pre class="plain eq">{esc(m.equation)}</pre>' if m.equation else '<p class="faint">No equation written for it yet.</p>')
    body = f"""<article class="prose">
{crumbs(("Types", "/types/"), (t.title, t.path), (m.id, None))}
<h1 id="top">{esc(m.title)}</h1>
<p class="lead"><code>{esc(m.id)}</code> on the <a href="{t.path}">{esc(t.title)}</a> ladder: rung {esc(m.rung)} of the {esc(m.family)} family, a {esc(m.kind)} model.{" Today's model." if m.current else ""}</p>
<div class="meta">
  <div class="meta-row"><span class="meta-k">Ladder</span><span class="meta-v">{ladder}</span></div>
  {f'<div class="meta-row"><span class="meta-k">Built on</span><code>{esc(m.base)}</code></div>' if m.base else ""}
  {f'<div class="meta-row"><span class="meta-k">Implemented</span><span class="meta-v">{inline(m.implemented)}</span></div>' if m.implemented else ""}
</div>
<section aria-labelledby="equation">{heading(2, "Equation", "equation")}{equation}</section>
<section aria-labelledby="parameters">{heading(2, "Parameters", "parameters")}
<p class="muted">{plural(len(m.parameters), "parameter")}, cumulative within the family; {plural(len(m.adds), "parameter")} added at this rung.</p>
{table(["Parameter", "Unit", "Identified by"], rows, cls="kv")}</section>
{f'<p class="muted">{inline(m.note)}</p>' if m.note else ""}
{f'<section aria-labelledby="references">{heading(2, "References", "references")}<ul>{refs}</ul></section>' if refs else ""}
<p><a href="{t.path}">← Back to {esc(t.title)}</a></p>
</article>"""
    return shell(title=f"{m.id} · {t.title} · sim2real", description=f"{t.title} model {m.id}: {m.title}.", path=m.path, body=body,
                 section="types", current=t.id, types=types, **ctx)


def parameter_page(t: TypeInfo, p: ParameterInfo, types: list[TypeInfo], routines_by_id: dict[str, RoutineInfo], **ctx) -> str:
    if p.routines:
        items = "".join(
            f'<li><a href="/routines/{rid}/">{esc(routines_by_id[rid].title if rid in routines_by_id else rid)}</a> '
            f'<code>{esc(rid)}</code></li>' for rid in p.routines
        )
        who = f'<ul class="plain-list">{items}</ul>'
    else:
        who = '<p class="muted">There is no routine for it in the catalog: no routine identifies it yet.</p>'
    models = " ".join(chip(f"/models/{t.id}/{mid}/", mid) for mid in p.models)
    nominal = "-" if p.nominal is None else (f"{p.nominal:.6g}" if isinstance(p.nominal, float) else str(p.nominal))
    body = f"""<article class="prose">
{crumbs(("Types", "/types/"), (t.title, t.path), (p.name, None))}
<h1 id="top"><code>{esc(p.name)}</code></h1>
<p class="lead">A parameter of the <a href="{t.path}">{esc(t.title)}</a>, in its {esc(p.family)} family.</p>
<div class="table-wrap"><table class="kv" data-table="parameter"><tbody>
<tr><th scope="row">Unit</th><td data-field="unit">{esc(p.unit or "-")}</td></tr>
<tr><th scope="row">Introduced in</th><td><a href="/models/{t.id}/{p.introduced_in}/"><code>{esc(p.introduced_in)}</code></a></td></tr>
<tr><th scope="row">Held by</th><td>{models}</td></tr>
<tr><th scope="row">Nominal</th><td>{esc(nominal)} <span class="faint small">{esc(p.source)}</span></td></tr>
<tr><th scope="row">Observable</th><td>{esc(p.observable)}</td></tr>
<tr><th scope="row">How it is measured</th><td>{inline(p.identified_by_words)}</td></tr>
</tbody></table></div>
<section aria-labelledby="identified-by">{heading(2, "Routines that identify it", "identified-by")}{who}</section>
{f'<p class="muted">{inline(p.note)}</p>' if p.note else ""}
</article>"""
    return shell(title=f"{p.name} · {t.title} · sim2real", description=f"{t.title} parameter {p.name} ({p.unit or 'no unit'}).", path=p.path,
                 body=body, section="types", current=t.id, types=types, **ctx)


def routines_index(routines: list[RoutineInfo], types: list[TypeInfo], **ctx) -> str:
    counts = {}
    for r in routines:
        counts[r.kind_word] = counts.get(r.kind_word, 0) + 1
    kinds = ", ".join(f"{n} {w}" for w, n in counts.items())
    body = f"""<article class="prose wide-table">
{crumbs(("Routines", None))}
<h1 id="routines">Calibration routines</h1>
<p class="lead">{len(routines)} routines ({esc(kinds)}). Each is one way to calibrate parameters: where it runs (bench, deployed or both), what it costs in time and equipment, what it needs first, and how well it recovers a hidden truth at 0x, 1x, 3x and 10x sensor noise.</p>
<p class="muted">Recovery is the worst |recovered − true| ÷ tolerance over the parameters the routine identifies (≤ 1 passes); "not graded" means nobody has run it against a hidden truth at that level yet. Needs first lists what must be identified or configured before it runs.</p>
{routines_table(routines)}
</article>"""
    return shell(title="Calibration routines · sim2real", description=f"All {len(routines)} sim2real calibration routines with time, cost and recovery.",
                 path="/routines/", body=body, section="routines", current="routines-index", types=types, wide=True, **ctx)


def routine_page(r: RoutineInfo, types: list[TypeInfo], catalog: set[str], **ctx) -> str:
    by_type = {t.id: t for t in types}

    def names(values: tuple[str, ...]) -> str:
        return ", ".join(f"<code>{esc(v)}</code>" for v in values) if values else '<span class="faint">—</span>'

    ident = " ".join(chip(f"/parameters/{t}/{n}/", f"{by_type[t].title if t in by_type else t} · {n}") for t, _m, n in r.identifies)
    if not ident:
        ident = '<span class="faint">nothing (it identifies no parameter)</span>'
    equipment = ", ".join(f"{esc(title)} ({usd_text(cost)})" for _id, title, cost, _src in r.equipment) or '<span class="faint">nothing beyond the robot\'s own sensors</span>'
    configures = ", ".join(f"<code>{esc(card)}.{esc(s)}</code>" for card, s in r.configures)
    est = ' <span class="faint">est.</span>' if r.cost_estimated else ""
    fields = [
        ("Identifies", ident),
        ("Kind", esc(r.kind_word)),
        ("Runs", esc(r.setting)),
        ("Status", esc(r.status)),
        ("Time", f'{seconds_text(r.wall_time_s)} <span class="faint small">{esc(r.wall_time_source)}</span>'),
        ("Operator time", f'{seconds_text(r.operator_time_s)} <span class="faint small">{esc(r.operator_time_source)}</span>'),
        ("Equipment", equipment),
        ("Equipment $", f'{usd_text(r.cost_usd)}{est} <span class="faint small">{esc(r.cost_source)}</span>'),
        ("Requires", names(r.requires)),
        ("Uses", names(r.uses)),
        ("Refines", names(r.refines)),
    ]
    if configures:
        fields.append(("Configures", configures))
    fields += [("Package", f"<code>{esc(r.package)}</code>"), ("Repeats", esc(r.repeats))]
    if r.code:
        fields.append(("Code", "<br>".join(f"<code>{esc(c)}</code>" for c in r.code)))
    kv = "".join(f'<tr><th scope="row">{esc(k)}</th><td>{v}</td></tr>' for k, v in fields)

    ladder_rows = []
    for level in r.levels:
        e = level.entry or {}
        if level.ratio is None:
            ratio, verdict = '<span class="faint">not graded</span>', '<span class="faint">—</span>'
        else:
            ratio = f"{level.ratio:.3g}×"
            verdict = f'<span class="rec-word {"pass" if level.passed else "fail"}">{"pass" if level.passed else "fail"}</span>'
        n = e.get("parameters")
        missing = e.get("missing")
        recovered = "" if n is None else (f"{n - (missing or 0)} of {n}")
        ladder_rows.append(f'<tr data-level="{level.level}"><th scope="row">{level.level}</th><td>{esc(LEVEL_WORDS.get(level.level, ""))}</td>'
                           f'<td class="num">{ratio}</td><td>{verdict}</td><td class="num">{esc(recovered)}</td></tr>')
    source = f'<p class="muted small">Graded by <code>{esc(r.recovery_source)}</code>, read through <code>sim2real.calibration.recovery</code>.</p>' if r.recovery_source else \
        '<p class="muted small">Nobody has graded this routine against a hidden truth yet: unknown stays unknown.</p>'
    alts = " ".join(chip(f"/routines/{a}/", a) if a in catalog else f"<code>{esc(a)}</code>" for a in r.alternatives)
    refs = "".join(f"<li>{ext_link(url, title)}</li>" for title, url in r.references)
    oracle = ", ".join(f"<code>{esc(o)}</code>" for o in r.oracle)
    details = [
        ("How", inline(r.how)),
        ("Excitation", inline(r.excitation)),
        ("Coverage", inline(r.coverage)),
    ]
    if oracle or r.oracle_note:
        details.append(("Oracle", (oracle + (" · " if oracle and r.oracle_note else "") + inline(r.oracle_note))))
    if alts:
        details.append(("Alternatives", alts))
    details_html = "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in details if v)
    toc = [("facts", "Facts", 2), ("recovery", "Recovery ladder", 2), ("how", "How it works", 2)]
    if refs:
        toc.append(("references", "References", 2))
    body = f"""<article class="prose">
{crumbs(("Routines", "/routines/"), (r.id, None))}
<h1 id="top">{esc(r.title)}</h1>
<p class="lead"><code>{esc(r.id)}</code>: a <span class="kind kind-{esc(r.kind_word)}">{esc(r.kind_word)}</span> routine that runs {esc(r.setting)}.</p>
<section aria-labelledby="facts">{heading(2, "Facts", "facts")}
<div class="table-wrap"><table class="kv" data-table="routine"><tbody>{kv}</tbody></table></div></section>
<section aria-labelledby="recovery">{heading(2, "Recovery ladder", "recovery")}
<p class="muted">The worst |recovered − true| ÷ tolerance against a hidden truth at each sensor-noise level; ≤ 1 passes.</p>
{table(["Level", "Noise", "Worst error ÷ tolerance", "Verdict", "Recovered"], ladder_rows, attrs=' data-table="recovery"', cls="kv")}
{source}</section>
<section aria-labelledby="how">{heading(2, "How it works", "how")}<dl class="facts">{details_html}</dl>
{f'<p class="muted">{inline(r.note)}</p>' if r.note else ""}</section>
{f'<section aria-labelledby="references">{heading(2, "References", "references")}<ul>{refs}</ul></section>' if refs else ""}
</article>"""
    return shell(title=f"{r.id} · sim2real routines", description=f"{r.title}: {r.kind_word}, runs {r.setting}, {r.status}.", path=r.path,
                 body=body, section="routines", toc=toc, types=types, **ctx)


def examples_index(examples: list[ExampleInfo], types: list[TypeInfo], **ctx) -> str:
    cards = "".join(
        f'<a class="card" href="{ex.path}"><span class="card-name">{esc(ex.title)}</span><span class="card-sum">{esc(ex.summary)}</span></a>'
        for ex in examples
    )
    body = f"""<article class="prose">
{crumbs(("Examples", None))}
<h1 id="examples">Examples</h1>
<p class="lead">The oracle examples: a twin built from a simulated world with a sealed hidden truth, calibrated by <code>calibrate(on="sim")</code>, so every recovered value can be graded against the truth it never saw. Each page shows the code and the real output it recorded.</p>
<div class="grid">{cards}</div>
</article>"""
    return shell(title="Examples · sim2real", description="sim2real's oracle examples: code and the real output it recorded.",
                 path="/examples/", body=body, section="examples", current="examples-index", types=types, **ctx)


def _num(value, unit: str = "") -> str:
    if value is None:
        return '<span class="faint">—</span>'
    if isinstance(value, bool):
        return esc(value)
    if isinstance(value, (int, float)):
        return esc(f"{value:.4g}")
    return esc(value)


_HUMAN_UNITS = {"rad": (180.0 / 3.141592653589793, "deg"), "rad/s": (180.0 / 3.141592653589793, "deg/s"), "m": (1000.0, "mm")}


def example_page(ex: ExampleInfo, types: list[TypeInfo], catalog: set[str], **ctx) -> str:
    rec = ex.recorded or {}
    rows = []
    for p in rec.get("parameters", []):
        # WHY degrees and mm here only (Zach: angles in degrees, lengths in mm for humans): the record stays SI; convert at the display edge.
        scale, unit = _HUMAN_UNITS.get(p.get("unit") or "", (1.0, p.get("unit") or ""))
        p = {**p, "unit": unit, **{k: (p[k] * scale if isinstance(p.get(k), (int, float)) else p.get(k)) for k in ("true", "value")}}
        ci = p.get("ci95")
        if isinstance(ci, (list, tuple)) and len(ci) == 2 and None not in ci:
            ci = [ci[0] * scale, ci[1] * scale]
        ci_text = f"[{ci[0]:.4g}, {ci[1]:.4g}]" if isinstance(ci, (list, tuple)) and len(ci) == 2 and None not in ci else "—"
        verdict = p.get("pass")
        word = '<span class="rec-word pass">pass</span>' if verdict is True else ('<span class="rec-word fail">fail</span>' if verdict is False
                                                                                 else '<span class="faint">not graded</span>')
        routine = p.get("routine")
        routine_html = f'<a href="/routines/{esc(routine)}/"><code>{esc(routine)}</code></a>' if routine and routine in catalog \
            else (f"<code>{esc(routine)}</code>" if routine else '<span class="faint">—</span>')
        rows.append(f'<tr data-key="{esc(p["key"])}"><th scope="row"><code>{esc(p["key"])}</code></th><td class="num">{_num(p.get("true"))}</td>'
                    f'<td class="num">{_num(p.get("value"))}</td><td class="num">{esc(ci_text)}</td><td>{esc(p.get("unit") or "")}</td>'
                    f'<td>{word}</td><td>{routine_html}</td></tr>')
    stale = '<p class="warn">This output is stale: the snippet changed after it was recorded. Re-run the recorder.</p>' if ex.stale else ""
    printed = rec.get("stdout", "").strip()
    evaluation = (rec.get("evaluation") or {}).get("summary", "")
    # WHY count graded and ungraded apart: the wrist reports 20 of its 42 keys as not identified (pass=None); "42, all within tolerance"
    # claimed a verdict nobody gave them. Unknown stays unknown.
    params = rec.get("parameters", [])
    graded = [p for p in params if p.get("pass") is not None]
    ungraded = len(params) - len(graded)
    verdict_text = (f'{len(graded)} graded, {"all within tolerance" if rec.get("passed") else "failing: " + esc(", ".join(rec.get("failing", [])))}'
                    + (f', {ungraded} not identified' if ungraded else ""))
    meta = (f'Recorded {esc(rec.get("recorded", "?"))} in {esc(round(rec.get("seconds", 0) / 60, 1))} min; schema <code>{esc(rec.get("schema"))}</code>; '
            f'{plural(len(params), "parameter")}: {verdict_text}.'
            if rec else "Not recorded yet.")
    run_cmd = (f"systemd-run --user --scope -p MemoryMax=16G -p OOMPolicy=continue -- env -u VIRTUAL_ENV "
               f"PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src:/home/bam/sim2real "
               f"/home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python /home/bam/sim2real/website/build/record_examples.py {ex.name}")
    toc = [("code", "Code", 2), ("output", "What calibrate() found", 2), ("printed", "What it printed", 2), ("rerun", "Record it again", 2)]
    body = f"""<article class="prose wide-table">
{crumbs(("Examples", "/examples/"), (ex.title, None))}
<h1 id="top">{esc(ex.title)}</h1>
<p class="lead">{esc(ex.summary)}</p>
{stale}
<section aria-labelledby="code">{heading(2, "Code", "code")}
<p class="muted"><code>website/examples/{esc(ex.name)}.py</code>, verbatim.</p>
{code_block(ex.source, label=f"{ex.name} example", pre_attrs=f' data-source="{esc(ex.name)}"')}</section>
<section aria-labelledby="output">{heading(2, "What calibrate() found", "output")}
<p class="muted">{meta}</p>
<div data-output="{esc(ex.name)}">{table(["Parameter", "Hidden truth", "Recovered", "95 % interval", "Unit", "Verdict", "Routine"], rows, cls="kv example-out")}</div></section>
<section aria-labelledby="printed">{heading(2, "What it printed", "printed")}
{code_block(printed, "text", wrap=True, label="printed output") if printed else '<p class="faint">Nothing recorded.</p>'}
{code_block(evaluation, "text", wrap=True, label="evaluation") if evaluation and evaluation not in printed else ""}</section>
<section aria-labelledby="rerun">{heading(2, "Record it again", "rerun")}
<p class="muted">Heavy (the pendulum about 15–27 min, the wrist tens of minutes); the site build never runs it, it reads the recorded <code>{esc(ex.name)}.out.json</code>.</p>
{code_block(run_cmd, "shell", wrap=True, label="record command")}</section>
</article>"""
    return shell(title=f"{ex.title} · sim2real examples", description=ex.summary or ex.title, path=ex.path, body=body, section="examples",
                 toc=toc, types=types, wide=True, **ctx)


def api_page(entries: list[ApiEntry], types: list[TypeInfo], **ctx) -> str:
    toc: list[tuple[str, str, int]] = []
    sections = []
    for e in entries:
        toc.append((e.anchor, e.name, 2))
        rest = (f'<details class="doc-rest"><summary>Full docstring</summary><pre class="plain">{esc(e.rest)}</pre></details>' if e.rest else "")
        fields = ""
        if e.fields:
            rows = "".join(f'<tr><th scope="row"><code>{esc(n)}</code></th><td><code>{esc(a)}</code></td><td><code>{esc(d)}</code></td></tr>'
                           for n, a, d in e.fields)
            fields = (f'<div class="table-wrap"><table class="fields"><thead><tr><th>Field</th><th>Type</th><th>Default</th></tr></thead>'
                      f'<tbody>{rows}</tbody></table></div>')
        members = []
        for anchor, m in e.members:
            mrest = (f'<details class="doc-rest"><summary>More</summary><pre class="plain">{esc(m.rest)}</pre></details>' if m.rest else "")
            summary = inline(m.summary) if m.summary else '<span class="faint">No docstring.</span>'
            members.append(
                f'<div class="fn" id="{anchor}"><div class="fn-head"><h3><a class="anchor" href="#{anchor}"><code>{esc(e.name)}.{esc(m.name)}</code></a></h3>'
                f'<span class="badge">{esc(m.group)}</span></div>'
                f'<pre class="sig"><code>{highlight(m.signature)}</code></pre><p class="fn-doc">{summary}</p>{mrest}</div>'
            )
        summary = inline(e.summary) if e.summary else '<span class="faint">No docstring.</span>'
        sections.append(
            f'<section class="api" id="{e.anchor}"><h2><a class="anchor" href="#{e.anchor}"><code>{esc(e.name)}</code></a> '
            f'<span class="badge">{esc(e.kind)}</span></h2><p class="muted small"><code>{esc(e.qualname)}</code></p>'
            f'<pre class="sig"><code>{highlight(e.signature)}</code></pre><p class="fn-doc">{summary}</p>{rest}{fields}{"".join(members)}</section>'
        )
    body = f"""<article class="prose">
{crumbs(("API", None))}
<h1 id="top">API reference</h1>
<p class="lead">Generated from the docstrings: <code>sim2real.RobotTwin</code> and every public name of <code>sim2real.calibration</code>.</p>
{"".join(sections)}
</article>"""
    return shell(title="API reference · sim2real", description="sim2real API reference: RobotTwin, calibrate, eval and the calibration back end.",
                 path="/api/", body=body, section="api", current="api", toc=toc, types=types, **ctx)


def docs_index(docs: list[tuple[str, str, str, str]], types: list[TypeInfo], **ctx) -> str:
    cards = "".join(f'<a class="card" href="/docs/{s}/"><span class="card-name">{esc(label)}</span><span class="card-sum">{esc(title)}</span></a>'
                    for s, title, label, _md in docs)
    body = f"""<article class="prose">
{crumbs(("Docs", None))}
<h1 id="docs">Docs</h1>
<p class="lead">The guides, rendered from <code>docs/</code> in the repo.</p>
<div class="grid">{cards}</div>
</article>"""
    return shell(title="Docs · sim2real", description="sim2real guides.", path="/docs/", body=body, section="docs", current="docs-index",
                 types=types, **ctx)


def doc_page(slug_: str, title: str, label: str, markdown: str, types: list[TypeInfo], doc_links: dict[str, str], **ctx) -> str:
    content, toc = render_markdown(markdown, doc_links)
    body = f"""<article class="prose md">
{crumbs(("Docs", "/docs/"), (label, None))}
{content}
</article>"""
    return shell(title=f"{title} · sim2real", description=f"{title}: sim2real docs.", path=f"/docs/{slug_}/", body=body, section="docs",
                 current="docs-index", toc=toc, types=types, **ctx)


def not_found(types: list[TypeInfo], **ctx) -> str:
    body = """<div class="home">
<section class="hero">
  <p class="eyebrow">404</p>
  <h1>Nothing is calibrated at this address</h1>
  <p class="lead">Try the list of types or the routine catalog, or go back to the start.</p>
  <div class="cta"><a class="btn primary" href="/types/">Browse types</a><a class="btn" href="/routines/">Routines</a><a class="btn" href="/">Home</a></div>
</section></div>"""
    ctx.pop("robots", None)  # WHY: the 404 is always noindex, preview build or not
    return shell(title="Not found · sim2real", description="Page not found.", path="/404.html", body=body, sidebar=False, types=types,
                 robots="noindex", **ctx)


# ---------------------------------------------------------------------------------------------- markdown


def _md_inline(text: str, resolve) -> str:
    """Markdown inline: `code`, [text](url), **bold**, *em*. An https link stays a link; a link into the repo that the site has a page for
    becomes that page; any other relative link is shown as its text (a static page cannot follow it)."""
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{esc(m.group(1))}</code>"), text)

    def link(m: re.Match) -> str:
        label, url = _md_inline(m.group(1), resolve), m.group(2)
        target = resolve(url)
        return keep(f'<a href="{esc(target)}"{" rel=\"noopener\"" if target.startswith("https://") else ""}>{label}</a>' if target
                    else f'<span class="xref" title="{esc(url)}">{label}</span>')

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def _plain(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("`", "").strip()


def markdown_anchors(lines: list[str]) -> tuple[dict[str, str], set[str]]:
    """Each heading line's anchor, as the rendered page spells it (render_markdown's pass 1; the landing links into it)."""
    anchors: dict[str, str] = {}
    used: set[str] = set()
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        m = None if in_fence else re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            base = slug(_plain(m.group(2))) or "section"
            anchor, n = base, 2
            while anchor in used or anchor in ("main", "sidebar", "search", "top"):
                anchor, n = f"{base}-{n}", n + 1
            used.add(anchor)
            anchors[line] = anchors.get(line, anchor)
    return anchors, used


def doc_anchor(docs: list[tuple[str, str, str, str]], slug_: str, starts: str) -> str:
    """The URL of the first heading in docs/<slug_> whose text starts with `starts` (computed from the file, never typed); the page itself
    when no heading matches."""
    for s_, _title, _label, markdown in docs:
        if s_ != slug_:
            continue
        anchors, _ = markdown_anchors(markdown.splitlines())
        for line, anchor in anchors.items():
            if re.sub(r"^#{1,6}\s+", "", line).startswith(starts):
                return f"/docs/{slug_}/#{anchor}"
    return f"/docs/{slug_}/"


def render_markdown(text: str, doc_links: dict[str, str]) -> tuple[str, list[tuple[str, str, int]]]:
    """A small Markdown renderer for docs/*.md: headings, paragraphs, nested lists, fenced code, pipe tables, block quotes. One h1 per
    page: the file's first '# ' heading; any later one is shown as an h2."""
    lines = text.splitlines()
    # pass 1: heading anchors, so a #fragment link resolves only when its heading exists
    anchors, used = markdown_anchors(lines)

    def resolve(url: str) -> str | None:
        if url.startswith("https://"):
            return url
        if url.startswith("#"):
            return url if url[1:] in used else None
        path = url.split("#", 1)[0]
        name = path.rsplit("/", 1)[-1]
        return doc_links.get(name)

    out: list[str] = []
    toc: list[tuple[str, str, int]] = []
    seen_h1 = False
    i = 0
    para: list[str] = []

    def flush_para():
        if para:
            out.append(f"<p>{_md_inline(' '.join(s.strip() for s in para), resolve)}</p>")
            para.clear()

    list_re = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            lang = stripped[3:].strip().lower()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(code_block("\n".join(code), "python" if lang in ("python", "py") else ("json" if lang == "json" else "text"),
                                  label=f"{lang or 'text'} snippet"))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_para()
            level = len(m.group(1))
            if level == 1:
                level = 2 if seen_h1 else 1
                seen_h1 = True
            anchor = anchors[line]
            inner = _md_inline(m.group(2), resolve)
            out.append(f'<h{level} id="{anchor}"><a class="anchor" href="#{anchor}">{inner}</a></h{level}>' if level > 1
                       else f'<h1 id="{anchor}">{inner}</h1>')
            if level in (2, 3):
                label = _plain(m.group(2))
                if level == 3 and "(" in label:  # WHY: a signature heading reads as its name in the outline, the full call is on the page
                    label = label.split("(", 1)[0] + "()"
                toc.append((anchor, label, level))
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush_para()

            def cells(row: str) -> list[str]:
                row = row.strip()
                row = row[1:] if row.startswith("|") else row
                row = row[:-1] if row.endswith("|") else row
                return [c.strip() for c in re.split(r"(?<!\\)\|", row)]

            head = cells(line)
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(cells(lines[i]))
                i += 1
            ths = "".join(f"<th>{_md_inline(c, resolve)}</th>" for c in head)
            trs = "".join("<tr>" + "".join(f"<td>{_md_inline(c, resolve)}</td>" for c in row) + "</tr>" for row in body)
            out.append(f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>')
            continue
        if stripped.startswith(">"):
            flush_para()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote><p>{_md_inline(' '.join(quote), resolve)}</p></blockquote>")
            continue
        if list_re.match(line):
            flush_para()
            items: list[tuple[int, str, str]] = []   # (indent, tag, text)
            while i < len(lines):
                lm = list_re.match(lines[i])
                if lm:
                    items.append((len(lm.group(1)), "ol" if lm.group(2)[0].isdigit() else "ul", lm.group(3)))
                    i += 1
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                    indent, tag, txt = items[-1]
                    items[-1] = (indent, tag, txt + " " + lines[i].strip())
                    i += 1
                else:
                    break
            out.append(_md_list(items, resolve))
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        para.append(line)
        i += 1
    flush_para()
    return "\n".join(out), toc


def _md_list(items: list[tuple[int, str, str]], resolve) -> str:
    html_out: list[str] = []
    stack: list[tuple[int, str]] = []
    for indent, tag, text in items:
        while stack and indent < stack[-1][0]:
            html_out.append(f"</li></{stack.pop()[1]}>")
        if not stack or indent > stack[-1][0]:
            html_out.append(f"<{tag}>")
            stack.append((indent, tag))
        else:
            html_out.append("</li>")
        html_out.append(f"<li>{_md_inline(text, resolve)}")
    while stack:
        html_out.append(f"</li></{stack.pop()[1]}>")
    return "".join(html_out)
