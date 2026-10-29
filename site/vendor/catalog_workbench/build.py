"""Write a catalog's site: every record of every kind through the record frame, every other file the catalog yields,
and its Analysis area when it has one."""

from __future__ import annotations

from .analysis import pages as analysis_pages
from .contract import Catalog
from .record import record_page
from .writer import Writer


def build(catalog: Catalog, site, writer: Writer) -> Writer:
    """Write into `writer` (the catalog clears its own outputs first: only it knows which names at the top of the folder it owns).
    Output never depends on the order files are written: a page is a function of the data alone."""
    for kind in catalog.kinds:
        for record in kind.records(site):
            writer.write(writer.page_path(kind.url(record)), record_page(catalog, kind, site, record))
    for relative, data in catalog.pages(site):
        writer.write(relative, data)
    if catalog.analysis is not None:
        for relative, data in analysis_pages(catalog, site):
            writer.write(relative, data)
    return writer
