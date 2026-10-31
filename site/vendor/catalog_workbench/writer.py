"""The writer: pages under one folder, never into the data build's outputs, never one file twice."""

from __future__ import annotations

import pathlib


def page_path(url: str) -> str:
    """The file a page's URL is served from: <url>/index.html, and index.html for /."""
    return url.strip("/") + "/index.html" if url != "/" else "index.html"


class PagesError(Exception):
    """The inputs cannot be rendered (missing /v2/ files, a page written twice, a write into the data)."""


class Writer:
    """Writes pages under `out`, refuses to touch the data build's outputs, and never writes one file twice."""

    def __init__(self, out: pathlib.Path, data_dirs=(), data_files=()):
        self.out = out
        self.data_dirs = tuple(data_dirs)
        self.data_files = tuple(data_files)
        self.written: dict[str, int] = {}

    def page_path(self, url: str) -> str:
        return page_path(url)

    def write(self, relative: str, text: str | bytes):
        top = relative.split("/", 1)[0]
        if top in self.data_dirs or relative in self.data_files:
            raise PagesError(f"refusing to write {relative}: it belongs to the data build")
        if relative in self.written:
            raise PagesError(f"{relative} would be written twice")
        data = text.encode("utf-8") if isinstance(text, str) else text
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.written[relative] = len(data)
