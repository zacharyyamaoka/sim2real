"""sim2real as a catalog of catalog-workbench (robotparts PEP 0003): the one Catalog the vendored workbench draws
(site/vendor/catalog_workbench/), its three kinds (a deployment, a station, a run) with their tabs, the search menu's
lists, the suggest file the search reads, and the Analysis area.

WHY a catalog (Zach, Daily Note 2026-10-29): "Sim to real is basically a catalog of what? Its a catalog of robot Runs
compared to virtual runs ... we should be using the catalog workbench off the shelf. All we are going to change is
kinda the contents of the page but the layout of the site is the exact same." So the bar, the search, the Account menu,
the trail, the home's tiles and the record page with its tabs are the workbench's, unchanged; only what is in them is
sim2real's (site/pages.py).
"""

from __future__ import annotations

import json

from catalog_workbench import shell as _shell
from catalog_workbench.analysis import report_layout
from catalog_workbench.contract import Account, AnalysisArea, Area, Brand, Catalog, Kind, Menu, Report, Tab, Words
from catalog_workbench.html import e

import pages
import run_pages
import types_pages
from adapter import Station, deployment_url, run_url, station_url

ROOT_CRUMB = pages.ROOT_CRUMB
LOGO = ('<img class="lockup" src="/static/sim2real-logo-lockup.svg" alt="" width="126" height="40">'
        '<img class="lockup dark" src="/static/sim2real-logo-lockup-dark.svg" alt="" width="126" height="40">')
ICONS = '<link rel="icon" type="image/svg+xml" href="/static/sim2real-app.svg">\n'
# WHY the "robotparts" storage prefix: robotparts' shell.js, which sim2real serves unchanged (as the object database
# does), keeps Settings under robotparts.* keys; localStorage is per origin, so nothing is shared with robotparts.dev.
THEME_HEAD = _shell.theme_head("robotparts", {})
AREAS = (
    Area("analysis", "Analysis", "/analysis/", "Why it fails, and the gate standing: where every twin falls short"),
    Area("data", "Every run", "/runs/", "Every real run, newest first, with its station, kind and models"),
    Area("sources", "Stations", "/stations/", "Every station's gates T1-T11 in one matrix"),
    Area("guides", "Deployments", "/deployments/", "Every deployment, virtual and physical, and each of its parts"),
    Area("programs", "Types", "/types/", "One card per part type: metrics, model, coverage, view and procedure"),
    # the models by generic type, the calibration routines both ways, every parameter (site/models_pages.py, w2c 2026-11-07)
    Area("programs", "Models", "/models/", "Each generic type's model ladder, by family, and where each model is used"),
    Area("guides", "Routines", "/routines/", "Every calibration routine and what it identifies, and every parameter's routines"),
    Area("data", "Parameters", "/parameters/", "Every parameter: true, nominal and recovered per model, with presets"),
    # the metrics lane (2026-11-07): metrics, diagnostics and coverage over any selection of runs, and the frozen reports
    Area("analysis", "Metrics", "/metrics/", "Metrics, diagnostics and coverage over the runs you pick, live"),
    Area("guides", "Reports", "/reports/", "Named, frozen sets of runs with their results as they were"),
)
REPORTS = (("why-it-fails", "Why it fails", "Every gate cell that does not pass, in words: the number against its limit, why, and the next step."),
           ("gate-standing", "Gate standing", "The stations × gates matrix, passing per gate, and the caveats on the numbers."))


def footer(site) -> str:
    sources = "; ".join(f"{e(d.row['title'])}: {e(d.row.get('gates_source') or '—')}" for d in site.deployments)
    return (f"<p>sim2real · how close each digital twin is to its real hardware. Real runs from the rack's archive, models replayed by bam_rack_twin; "
            f"gates from {sources}. Blue is real, orange is a model; green and red mean pass and fail only.</p>")


def menu(site) -> Menu:
    """The search menu's idle lists: the deployments, and the stations with the most runs."""
    cached = getattr(site, "_menu", None)
    if cached:
        return cached
    stations = [(st.device, st.url, len(st.deployment.runs_of(st.device))) for st in site.stations]
    site._menu = Menu(groups=[(d.row["title"], deployment_url(d.id), len(d.runs)) for d in site.deployments],
                      top=sorted(stations, key=lambda s: (-s[2], s[0])), total=len(site.runs))
    return site._menu


def suggest_index(site) -> str:
    """/search/suggest.json in the shape robotparts' shell.js reads (categories, brands, parts as positional rows): the
    deployments, the stations, the runs. A run's level is 1 when a model replayed it and 0 when it is real only
    (static/sim2real.js says it in words). No thumbnails: the shell draws its line icon."""
    deps = site.deployments
    order = [d.id for d in deps]
    categories = [[d.row["title"], deployment_url(d.id), len(d.runs), ""] for d in deps]
    brands = [[f"{st.device} · {st.row.get('station') or ''}", st.url, len(st.deployment.runs_of(st.device)), order.index(st.deployment.id), ""]
              for st in site.stations]
    parts = [[f"{r['device']} · {r['title']}", f"{r.get('kind') or ''} · {(r.get('started') or '')[:10]} · {r.get('compare') or ''}", run_url(r),
              order.index(r["deployment"]), 1 if r.get("models") else 0, ""] for r in sorted(site.runs, key=lambda r: r["started"], reverse=True)]
    return json.dumps({"format": "sim2real-suggest/1", "files": "/static/",
                       "fields": {"categories": ["label", "url", "count", "thumb"], "brands": ["name", "url", "count", "category", "thumb"],
                                  "parts": ["name", "title", "url", "category", "level", "thumb"]},
                       "categories": categories, "brands": brands, "parts": parts},
                      ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def _dep(site, record):
    return record


DEPLOYMENT = Kind(
    key="deployment", label="Deployment", plural="Deployments",
    records=lambda site: site.deployments, url=lambda d: deployment_url(d.id), title=lambda d: d.row["title"],
    # WHY Runs first: an unnamed hash (#t=…, data-ui's own state) opens the first tab, and the runs dashboard owns the URL
    tabs=(Tab("runs", "Runs", body=pages.deployment_runs),
          Tab("gates", "Gates", body=pages.deployment_gates),
          Tab("why", "Why it fails", body=pages.deployment_why),
          Tab("coverage", "Coverage", body=pages.deployment_coverage),
          Tab("evidence", "Evidence", body=pages.deployment_evidence)),
    header=pages.deployment_header, crumbs=lambda site, d: [ROOT_CRUMB, (d.row["title"], deployment_url(d.id))],
    back=lambda site, d: ["/", "/deployments/"],
    description=lambda site, d: f"{d.row['title']}: {len(d.runs):,} real runs, {d.row.get('gate_summary')}; runs, gates, why it fails, coverage.",
    scripts=("site", "sim2real"), data_ui=True,
)

STATION = Kind(
    key="station", label="Station", plural="Stations",
    records=lambda site: site.stations, url=lambda st: st.url, title=lambda st: f"{st.device} · {st.deployment.row['title']}",
    tabs=(Tab("runs", "Runs", body=pages.station_runs),
          Tab("gates", "Gates", body=pages.station_gates),
          Tab("why", "Why it fails", body=pages.station_why),
          Tab("coverage", "Coverage", body=pages.station_coverage),
          # WHY a tab and not a run (2026-10-29, Zach: "I should be able to generate it and view it within sim2real, its just that we will
          # not have run it yet"): a schedule is the plan for the station's next runs, so it sits beside its real runs, only where one exists
          Tab("schedule", "Schedule", body=pages.station_schedule, has=lambda site, st: st.key in st.deployment.schedules, empty="hide"),
          Tab("evidence", "Evidence", body=pages.station_evidence)),
    header=pages.station_header,
    crumbs=lambda site, st: [ROOT_CRUMB, (st.deployment.row["title"], deployment_url(st.deployment.id)), (st.device, st.url)],
    back=lambda site, st: ["/", "/stations/", deployment_url(st.deployment.id)],
    description=lambda site, st: f"{st.device} on {st.deployment.row['title']}: its gates T1-T11, why it fails, its runs and coverage.",
    scripts=("site", "sim2real"), data_ui=True,
)


def _run_crumbs(site, row):
    dep = site.deployment(row["deployment"])
    return [ROOT_CRUMB, (dep.row["title"], deployment_url(dep.id)), (row["device"], station_url(dep.id, row["device"])), (row["title"], run_url(row))]


RUN = Kind(
    # WHY key "part": robotparts' shell.js keeps Account › Recently viewed from pages whose <body data-page> is "part"
    # (the object database does the same); a run is the record people come back to
    key="part", label="Run", plural="Runs",
    records=lambda site: site.runs, url=run_url, title=pages.run_title,
    # WHY Playback first: data-ui's clock lives in the hash (#t=…&tr=…), which names no tab, so it opens the first one
    tabs=(Tab("playback", "Playback", body=pages.run_playback),
          Tab("gates", "Gates", body=pages.run_gates),
          Tab("why", "Why it fails", body=pages.run_why),
          Tab("diagnostics", "Diagnostics", body=pages.run_diagnostics, has=lambda site, r: bool(pages.run_diagnostics_rows(site, r))),
          Tab("evidence", "Evidence", body=pages.run_evidence)),
    # WHY its own header (site/run_pages.py): the run's tags, then one section per level of its entity tree, the station's first
    header=run_pages.run_header, crumbs=_run_crumbs,
    back=lambda site, r: ["/", "/runs/", "/search/", deployment_url(r["deployment"]), station_url(r["deployment"], r["device"])],
    description=lambda site, r: f"{pages.run_title(r)}: real vs every model, played back on one clock, with its gates and diagnostics.",
    scripts=run_pages.SCRIPTS, data_ui=True,
)


TYPE = Kind(
    # WHY a kind and not a page per card (Zach, PROJECT - Sim2Real, Nov 4 2026): "for each 'type' ... the models, and then the dashboards
    # to view the results": a type is what a station is; its card is a record with the same tabs every card has
    key="type", label="Type", plural="Types",
    records=types_pages.records, url=lambda t: types_pages.type_url(t.id), title=lambda t: t.card.title,
    # WHY Models and Tests (Zach, PROJECT - Sim2Real, Nov 5 2026: "2. Models ... Multiple rungs of models", "3. Test Type"): the tab keeps its
    # #model anchor, so old links still open it
    tabs=(Tab("metrics", "Metrics", body=types_pages.metrics_tab),
          Tab("model", "Models", body=types_pages.model_tab),
          Tab("tests", "Tests", body=types_pages.tests_tab),
          Tab("coverage", "Coverage", body=types_pages.coverage_tab),
          Tab("view", "View", body=types_pages.view_tab),
          Tab("procedure", "Procedure", body=types_pages.procedure_tab)),
    header=types_pages.header, crumbs=lambda site, t: [ROOT_CRUMB, ("Types", "/types/"), (t.card.title, types_pages.type_url(t.id))],
    back=lambda site, t: ["/", "/types/"],
    description=lambda site, t: f"{t.card.title}: its black-box metrics, diagnostics and gates, model rungs, test types, coverage, view and the shared procedure.",
    scripts=("site", "sim2real"),
)


def reports(site) -> list[Report]:
    out = []
    for slug, title, what in REPORTS:
        article, toc = (pages.why_report if slug == "why-it-fails" else pages.standing_report)(site)
        out.append(Report(slug=slug, title=title, body=report_layout(article, toc), description=what))
    return out


ANALYSIS = AnalysisArea(
    reports=reports, list_body=pages.analysis_list,
    list_description="Standard analyses over sim2real's gates and runs: why it fails, and the gate standing.",
    head='<link rel="stylesheet" href="/static/analysis.css">\n',
)


def site_pages(site):
    from build import site_files  # noqa: PLC0415  (the build writes the home, the lists, the views, the static files and the kit)
    yield from site_files(site)
    # WHY the run pages here and not the workbench's record writer (RUN is not in CATALOG.kinds): a run's page is the workbench's record in
    # its two panes, the run's entity tree in the left column (Zach, 2026-11-06: "On the left should be like an entity tree"), and the
    # workbench's record page has no left column (site/ui_shared.py record_page)
    yield from run_pages.pages_of(site)


CATALOG = Catalog(
    brand=Brand(name="sim2real", origin="", logo=LOGO, icons=ICONS, head=THEME_HEAD, root_crumb=ROOT_CRUMB, footer=footer,
                styles=("/static/sim2real.css",)),
    words=Words(item="run", items="runs", an_item="a run", groups="Deployments", subgroups="Stations"),
    menu=menu,
    kinds=(DEPLOYMENT, STATION, TYPE),  # RUN's pages: site_pages (run_pages.pages_of), in two panes
    areas=AREAS,
    quick=(("Why it fails", "/analysis/why-it-fails/"), ("Analysis", "/analysis/")),
    account=Account(lists=tuple((f"/analysis/{slug}/", title) for slug, title, _w in REPORTS), pill="standard",
                    create="Your own analyses", links=(("/analysis/", "Analysis"), ("/runs/", "Every run")),
                    data="/data/deployments.json"),
    scripts=("site", "sim2real"),
    pages=site_pages,
    data_dirs=("data",),
    analysis=ANALYSIS,
)


def page(site, title: str, url: str, body: str, kind: str, **options) -> str:
    """A sim2real page in the workbench's shell."""
    return _shell.page(CATALOG, site, title, url, body, kind, **options)
