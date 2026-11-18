"""Build sim2real's site: catalog-workbench (vendored, site/vendor/) over the app's data (tools/build_app.py).

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs python /home/bam/sim2real/site/build.py [--data PATH] [--out PATH]
    python3 -m http.server 4710 --bind 127.0.0.1 --directory /home/bam/.cache/sim2real/site

Stdlib only. Writes OUT (default ~/.cache/sim2real/site, disposable; nothing here is in git):

    OUT/data/<dep>/schedule/<station>/   a station's test schedule (bam_rack_twin.schedule), copied from SIM2REAL_SCHEDULES
    OUT/data/<dep>/  + the deployment's tree and every run's place in it, its tags and its configuration snapshot (site/deploy_tree.py)
    OUT/data/domain/ the domain model v3 (type_cards/instances.py): deployments.json, parameters.json, selections/<dep>.json,
                     coverage_cells/<dep>.json, reports/<id>.json (type_cards/CONTRACT.md, "Domain model v3")
                     + the rows data-ui's gate views read (site/overlays.py): gate ranks and links, the tree's roll-up rows, the gate
                     history from the archive's acceptance files, each station's coverage cells
    OUT/data/        the app's tables: the ones holding links copied with every old /app/?d=… link rewritten to the
                     site's path, everything else (each run's folder, coverage, dx) linked, never copied (3.8 GB)
    OUT/static/      robotparts' shell.js, site.js and site.css (pinned, byte for byte), analysis.css, the vendored
                     data-ui kit, sim2real's own sim2real.css / sim2real.js and its logo
    OUT/views/       the .base files each tab's dashboard reads (site/views.py), and /views/runs.base
    OUT/media        a link to the media folder (tools/build_media.py: the cards' renders, each station's link model, every run's link
                     poses and the camera runs' clips; --media, else $SIM2REAL_MEDIA, else ~/.cache/sim2real/media), when it is built
    OUT/<pages>      /, /<deployment>/, /<deployment>/<station>/, /<deployment>/runs/<run>/, /runs/, /search/,
                     /stations/, /deployments/, /analysis/…
    OUT/deployments/ /deployments/: the Deployments workbench (site/deployments_workbench.py; its data in OUT/data/deployments-workbench.json
                     and every run in deployments-workbench-runs.json); /deployments/all/, the filter-bar index of every deployment's card,
                     and /deployments/<node id>/ for every node of every deployment's tree (site/deployments_pages.py; rows in
                     OUT/data/deployment-cards.json)
    OUT/models/      a page per generic type, its model ladder by family; OUT/routines/, the calibration routines both ways; OUT/parameters/,
                     every parameter in data-ui (site/models_pages.py; rows in OUT/data/routines.json, parameter-routines.json, parameters-view.json)
    OUT/metrics/     /metrics/<dep>/: metrics, diagnostics and coverage over any selection of a deployment's runs, live (site/metrics_pages.py,
                     static/metrics.js; the runs table's rows in OUT/data/domain/metric_runs/<dep>.json)
    OUT/reports/     /reports/ and /reports/<id>/: every frozen report, read from its snapshot (site/reports_pages.py)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE / "vendor"))
sys.dont_write_bytecode = True

import adapter  # noqa: E402
import media as site_media  # noqa: E402

DEFAULT_OUT = pathlib.Path.home() / ".cache" / "sim2real" / "site"
MARKER = ".sim2real-site"
# the tables whose rows carry the app's old routes (a `page`, `url` or `evidence` link); copied with them rewritten
REWRITE = {"deployments.json", "runs.json", "why.json", "why_t2.json", "run_gates.json", "evidence.json", "diagnostics.json", "gates.json", "caveats.json", "devices.json"}


def clear(out: pathlib.Path):
    """Remove a previous build: only in a folder this build made (its marker), or an empty one."""
    entries = list(out.iterdir()) if out.is_dir() else []
    if entries and not (out / MARKER).is_file():
        raise SystemExit(f"refusing to write into {out}: it holds {entries[0].name} and is not a sim2real site folder")
    for path in entries:
        shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()


def write_data(source: pathlib.Path, out: pathlib.Path) -> int:
    """OUT/data from the app's data: the link-holding tables rewritten, the rest linked. Returns files rewritten."""
    rewritten = 0

    def place(src: pathlib.Path, dst: pathlib.Path):
        nonlocal rewritten
        if src.is_file() and src.name in REWRITE:
            dst.write_text(adapter.rewrite_links(src.read_text(encoding="utf-8")), encoding="utf-8")
            rewritten += 1
        else:
            os.symlink(src.resolve(), dst)

    out.mkdir(parents=True)
    for entry in sorted(source.iterdir()):
        if entry.is_dir() and (entry / "runs.json").is_file():  # a deployment's folder: its tables one by one
            (out / entry.name).mkdir()
            for child in sorted(entry.iterdir()):
                place(child, out / entry.name / child.name)
        else:
            place(entry, out / entry.name)
    return rewritten


def site_files(site):
    """(path, text or bytes) of every file but the record pages and the Analysis area (the workbench writes those)."""
    import catalog as s2r  # noqa: PLC0415
    import pages  # noqa: PLC0415
    import views  # noqa: PLC0415
    from catalog_workbench.html import breadcrumb, plural, results_line  # noqa: PLC0415

    n_runs = len(site.runs)
    yield "index.html", s2r.page(site, "sim2real: how close each twin is to its real hardware", "/", pages.home_body(site), "home",
                                 description="sim2real: every robot run against its virtual runs, the gates per station, and why each one fails.",
                                 trail=results_line(plural(n_runs, "run"), breadcrumb([s2r.ROOT_CRUMB])), data_ui=True)
    # the deployments index and one page per node of every deployment's tree (Domain model v3: site/deployments_pages.py)
    import deployments_pages  # noqa: PLC0415
    yield from deployments_pages.files(site)
    # the Deployments workbench at /deployments/ (2026-11-17): 3D, typed tree, every node's performance first (site/deployments_workbench.py)
    import deployments_workbench  # noqa: PLC0415
    yield from deployments_workbench.files(site)
    # the models by entity type, the calibration routines both ways, the parameters view (site/models_pages.py)
    import models_pages  # noqa: PLC0415
    yield from models_pages.files(site)
    # metrics over any selection of runs, and the frozen reports (the metrics lane, 2026-11-07: site/metrics_pages.py, site/reports_pages.py)
    import metrics_pages  # noqa: PLC0415
    import reports_pages  # noqa: PLC0415
    yield from metrics_pages.files(site)
    yield from reports_pages.files(site)
    yield "stations/index.html", s2r.page(site, "Stations: sim2real", "/stations/", pages.stations_body(site), "stations",
                                          trail=breadcrumb([s2r.ROOT_CRUMB, ("Stations", "/stations/")]))
    for url, title, kind, intro in (("/runs/", "Every run", "runs", "Every real run, newest first."),
                                    ("/search/", "Search", "search", "Search every run: the words in the box at the top filter the list below.")):
        aside, results = pages.runs_list(site, title)
        body = f"<h1>{title} ({n_runs:,})</h1>\n<p class=\"lede\">{intro} Open one to play it back against its models.</p>\n{results}"
        yield url.strip("/") + "/index.html", s2r.page(site, f"{title}: sim2real", url, body, kind, aside=aside, data_ui=True,
                                                       trail=results_line(plural(n_runs, "run"), breadcrumb([s2r.ROOT_CRUMB, (title, url)])))
    import types_pages  # noqa: PLC0415
    yield "types/index.html", s2r.page(site, "Types: sim2real", "/types/", types_pages.list_body(site), "types",
                                       description="One card per part type: metrics, model, coverage, view and the shared procedure.",
                                       trail=breadcrumb([s2r.ROOT_CRUMB, ("Types", "/types/")]))
    import landing  # noqa: PLC0415
    oracle = landing.load()
    if oracle:
        yield "sysid/index.html", s2r.page(site, "System-ID oracle: sim2real", "/sysid/", landing.index_body(oracle), "sysid",
                                           description="Six robot descriptions in, a better model out, each against a hidden truth.",
                                           trail=breadcrumb([s2r.ROOT_CRUMB, ("System-ID oracle", "/sysid/")]))
        for example in landing.EXAMPLES:
            if example in oracle:
                doc = oracle[example]
                yield f"sysid/{example}/index.html", s2r.page(site, f"{doc['title']}: system-ID oracle", landing.url(example), landing.page_body(doc, oracle, getattr(site, "media", None)), "sysid",
                                                              description=doc.get("summary", "")[:240],
                                                              trail=breadcrumb([s2r.ROOT_CRUMB, ("System-ID oracle", "/sysid/"), (doc["title"], landing.url(example))]))
    if getattr(site, "media", None):
        # the media components, each mounted alone for a real entity (site/components.py): the shelf a page per entity level takes them from
        yield "components/index.html", s2r.page(site, "Components: sim2real", "/components/", pages.components_body(site), "components",
                                                description="The media as entity-scoped components: a joint's link in 3D, a camera's clip, a joint's render.",
                                                trail=breadcrumb([s2r.ROOT_CRUMB, ("Components", "/components/")]), data_ui=True)
    yield "search/suggest.json", s2r.suggest_index(site)
    yield from views.files(site)
    yield "views/runs.base", pages.runs_base(site)

    shell = adapter.shell_static()
    for name in adapter.SHELL_STATIC:
        yield f"static/{name}", (shell / name).read_bytes()
    yield "static/analysis.css", adapter.analysis_css().read_bytes()
    for path in sorted((HERE / "static").iterdir()):
        yield f"static/{path.name}", path.read_bytes()
    brand = adapter.REPO / "brand"
    for rel in ("logos/sim2real-logo-lockup.svg", "logos/sim2real-logo-lockup-dark.svg", "icons/sim2real-app.svg"):
        yield f"static/{pathlib.Path(rel).name}", (brand / rel).read_bytes()
    for rel in adapter.kit_files():
        yield f"static/data-ui/{rel}", (adapter.KIT / rel).read_bytes()


def link_media(root: pathlib.Path, out: pathlib.Path) -> site_media.Media | None:
    """OUT/media -> the media folder, when tools/build_media.py has written one. WHY linked, never copied: its clips and link poses are
    ~0.5 GB of build outputs, rebuilt by their own tool; WHY never from a worktree or this repo: a worktree's folder goes when it does,
    and media are never committed."""
    if not (root / "index.json").is_file():
        print(f"site: no media at {root} (tools/build_media.py writes them): the pages show no render, link model or clip", file=sys.stderr)
        return None
    if adapter.in_worktree(root) or str(root.resolve()).startswith(str(adapter.REPO.resolve()) + "/"):
        raise SystemExit(f"refusing to serve media from {root}: build them outside the repo and its worktrees (tools/build_media.py --out)")
    os.symlink(root.resolve(), out / "media")
    return site_media.load(out / "media")


def build(data: pathlib.Path, out: pathlib.Path, media_root: pathlib.Path = site_media.DEFAULT) -> dict:
    started = time.monotonic()
    adapter.check_kit()
    from catalog_workbench.build import build as workbench_build  # noqa: PLC0415
    from catalog_workbench.writer import Writer  # noqa: PLC0415
    import catalog as s2r  # noqa: PLC0415
    import pages  # noqa: PLC0415

    if adapter.in_worktree(data):
        raise SystemExit(f"refusing to build from {data}: it is inside a worktree, and the site links its run folders to the data "
                         f"(a worktree's go when it does); build the data in the main checkout ({adapter.DATA}) or pass --data there")
    if not (data / "deployments.json").is_file():
        raise SystemExit(f"no app data at {data}: build it with tools/build_app.py (README), or pass --data")
    clear(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("sim2real site build folder: site/build.py clears everything here\n")
    rewritten = write_data(data, out / "data")
    schedules = adapter.link_schedules(adapter.SCHEDULES, out / "data")
    # the system-ID oracle's results (sysid/results, committed; site/landing.py renders them), served beside the app's tables
    oracle_dir = out / "data" / "sysid"
    oracle_dir.mkdir()
    for path in sorted((adapter.REPO / "sysid" / "results").glob("*.json")):
        shutil.copyfile(path, oracle_dir / path.name)
    import deploy_tree  # noqa: PLC0415
    import overlays  # noqa: PLC0415
    # WHY before the overlays: the roll-up rows (components.json) are the tree's nodes, and runs.json gains each run's place in it
    tree_counts = deploy_tree.write(out / "data")
    # the domain model v3's projections, after the tree overlay (runs.json carries the run tags by then): deployments and their trees,
    # the parameters table, the preset selections, the coverage cells the browser counts, the frozen reports (type_cards/CONTRACT.md,
    # "Domain model v3"; data only, no page reads them yet)
    from type_cards import instances as domain_v3  # noqa: PLC0415  (deploy_tree put the repo on sys.path)
    domain_counts = domain_v3.write(out / "data")
    before = adapter.load(out / "data")
    overlay_counts = overlays.write(out / "data", lambda dep_id, row: pages.cell_href(before.deployment(dep_id), row))
    site = adapter.load(out / "data")
    site.media = link_media(media_root, out)
    (out / "data" / "search.json").write_text(pages.search_rows(site), encoding="utf-8")
    import deployments_pages  # noqa: PLC0415  (the deployments index's rows, beside search.json: the workbench's writer keeps out of data/)
    deployments_pages.write_data(out / "data", site)
    import deployments_workbench  # noqa: PLC0415  (the workbench's tree, values and runs: sim2real.deployments_page over the scorecards)
    workbench = deployments_workbench.write_data(out / "data", site)
    import models_pages  # noqa: PLC0415  (the routines' and the parameters view's rows, beside the deployments' cards)
    models_pages.write_data(out / "data", site)
    import metrics_pages  # noqa: PLC0415  (the metrics page's runs table: each run's per-run values and levels)
    metric_runs = metrics_pages.write_data(out / "data", site)
    writer = workbench_build(s2r.CATALOG, site, Writer(out, s2r.CATALOG.data_dirs, s2r.CATALOG.data_files))
    result = {"files": len(writer.written), "bytes": sum(writer.written.values()), "rewritten_tables": rewritten, "data": str(data),
              "schedules": schedules, "schedules_root": str(adapter.SCHEDULES), "overlays": overlay_counts, "tree": tree_counts, "domain": domain_counts,
              "runs": len(site.runs), "stations": len(site.stations), "deployments": len(site.deployments), "metric_runs": metric_runs,
              "workbench": workbench,
              "media": ({"root": str(media_root.resolve()), "scenes": len(site.media.scenes), "stations": len(site.media.stations),
                         "links": sum(1 for r in site.runs if (site.media.runs.get(r["run"]) or {}).get("links")),
                         "clips": sum(1 for r in site.runs if site.media.clips(r["run"]))} if site.media else None),
              "seconds": round(time.monotonic() - started, 1)}
    (out / ".sim2real-build.json").write_text(json.dumps(result, indent=1) + "\n")
    print(f"site: {result['files']:,} files, {result['bytes'] / 1e6:.1f} MB -> {out} in {result['seconds']} s "
          f"({result['runs']:,} runs, {result['stations']} stations; {rewritten} tables rewritten)", file=sys.stderr)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=pathlib.Path, default=adapter.DATA, help=f"the app's data (default {adapter.DATA})")
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help=f"the site folder (default {DEFAULT_OUT})")
    parser.add_argument("--media", type=pathlib.Path, default=site_media.DEFAULT, help=f"the media folder tools/build_media.py wrote (default {site_media.DEFAULT})")
    parser.add_argument("--repin", action="store_true", help="pin the data-ui kit vendor/data-ui/dist holds now (site/DATA_UI.json)")
    args = parser.parse_args(argv)
    if args.repin:
        pin = adapter.repin()
        print(f"pinned the vendored data-ui kit: manifest {pin['manifest_sha256'][:12]}, {pin['files']} files")
        return
    build(args.data.resolve(), args.out.resolve(), args.media)


if __name__ == "__main__":
    main()
