"""Build the sim2real docs site (robotmsgs.com's shape) from sim2real's registries into a folder.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python /home/bam/sim2real/website/build/build.py

`--out <dir>` (default website/dist/, gitignored). It reads cards/domain.py, cards/calibration.py, sim2real.calibration.recovery, the
docstrings, docs/*.md and website/examples/*.out.json; it never runs a calibration and never writes a tracked file. Runs in seconds.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import model  # noqa: E402
import pages  # noqa: E402

SITE = ROOT / "site"
# WHY a placeholder origin: the domain is Zach's pick (PEP 0001 section 10); .example is reserved and resolves nowhere
ORIGIN = "https://sim2real.example"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "dist", help="output folder (default: website/dist/)")
    ap.add_argument("--origin", default=ORIGIN, help=f"the site's origin for sitemap.xml and robots.txt (default {ORIGIN})")
    args = ap.parse_args(argv)
    dist: Path = args.out.resolve()

    def write(path: str, content: str | bytes) -> None:
        target = dist / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    if dist.exists():
        for child in dist.iterdir():  # WHY not rmtree(dist): --out may be a folder the caller made (a test's tmp dir)
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    dist.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SITE, dist / "assets", ignore=shutil.ignore_patterns("PINNED.json"))
    digest = hashlib.sha256()
    for name in ("site.css", "site.js", "sim2real.css"):
        digest.update((SITE / name).read_bytes())
    ctx = {"asset_version": digest.hexdigest()[:8], "stamp": model.source_stamp()}

    types = model.types()
    routines = model.routines()
    routines_by_id = {r.id: r for r in routines}
    catalog = set(routines_by_id)
    examples = model.examples()
    docs = model.docs()
    doc_links = {"API.md": "/docs/guide/", "CALIBRATE.md": "/docs/calibrate/"}
    doc_links = {name: url for name, url in doc_links.items() if any(url == f"/docs/{s}/" for s, *_ in docs)}

    urls: list[str] = []

    def page(url: str, content: str) -> None:
        write(f"{url}index.html", content)
        urls.append(url)

    page("/", pages.home(types, routines, examples, docs, **ctx))
    page("/types/", pages.types_index(types, **ctx))
    for t in types:
        page(t.path, pages.type_page(t, types, routines_by_id, **ctx))
        for m in t.models:
            page(m.path, pages.model_page(t, m, types, routines_by_id, **ctx))
        for p in t.parameters:
            page(p.path, pages.parameter_page(t, p, types, routines_by_id, **ctx))
    page("/routines/", pages.routines_index(routines, types, **ctx))
    for r in routines:
        page(r.path, pages.routine_page(r, types, catalog, **ctx))
    page("/examples/", pages.examples_index(examples, types, **ctx))
    for ex in examples:
        page(ex.path, pages.example_page(ex, types, catalog, **ctx))
    page("/api/", pages.api_page(model.api(), types, **ctx))
    page("/docs/", pages.docs_index(docs, types, **ctx))
    for slug, title, label, markdown in docs:
        page(f"/docs/{slug}/", pages.doc_page(slug, title, label, markdown, types, doc_links, **ctx))
    write("404.html", pages.not_found(types, **ctx))

    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {args.origin}/sitemap.xml\n")
    entries = "".join(f"<url><loc>{args.origin}{u}</loc></url>" for u in urls)
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n')
    size = sum(f.stat().st_size for f in dist.rglob("*") if f.is_file())
    stale = [ex.name for ex in examples if ex.stale]
    print(f"built {len(urls) + 1} pages ({len(types)} types, {len(routines)} routines, {len(examples)} examples, {len(docs)} docs) "
          f"into {dist}, {size / 1024:.0f} KiB" + (f"; STALE example output: {', '.join(stale)}" if stale else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
