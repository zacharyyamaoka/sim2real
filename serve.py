"""Serve the sim2real app (and the dashboard proposals) on 127.0.0.1 and print the URL. Never opens a browser.

    python3 /home/bam/sim2real/serve.py            (a free port in 4700-4799)
    python3 /home/bam/sim2real/serve.py --port 4712

Stdlib only. Serves the catalog-workbench site at / (site/build.py's output, ~/.cache/sim2real/site); the old app stays at /app/
(deployments -> runs -> run, built by tools/build_app.py), the five proposals at /dashboards/, and those pages reach vendor/data-ui
and brand/ in this repo. With no site built yet, / falls back to this repo's root (a redirect to /app/).
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import pathlib
import re
import socket
import subprocess
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent
SITE = pathlib.Path.home() / ".cache" / "sim2real" / "site"
# WHY two roots (Zach's landing brief, 2026-10-30): the site's URLs are absolute at /, and the old app's are absolute at /app/, /vendor/ and /brand/
REPO_ROUTES = {"app", "vendor", "brand", "dashboards", "reports"}
PORTS = range(4700, 4800)
TYPES = {".svg": "image/svg+xml", ".base": "text/plain; charset=utf-8", ".mjs": "text/javascript", ".js": "text/javascript", ".glb": "model/gltf-binary",
         ".mp4": "video/mp4", ".json": "application/json", ".css": "text/css", ".md": "text/plain; charset=utf-8"}


def listening_ports() -> set[int]:
    """Ports something already listens on (ss -ltn): a port Zach or a peer owns is never taken over."""

    try:
        out = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {int(m.group(1)) for m in re.finditer(r":(\d+)\s", out)}


def free_port() -> int:
    busy = listening_ports()
    for port in PORTS:
        if port in busy:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise SystemExit("no free port in 4700-4799")


class Handler(http.server.SimpleHTTPRequestHandler):
    """Static files with byte ranges (a <video> seeks with Range requests) and no caching (the build rewrites the data)."""

    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **TYPES}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def translate_path(self, path):
        local = pathlib.Path(super().translate_path(path))  # the stock handler has already stripped any .. and the query
        top = urllib.parse.urlsplit(path).path.lstrip("/").split("/")[0]
        if top in REPO_ROUTES or not (SITE / "index.html").is_file():
            return str(local)
        return str(SITE / local.relative_to(ROOT))

    def send_head(self):
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        path = pathlib.Path(self.translate_path(self.path))
        if not match or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        start = int(match.group(1)) if match.group(1) else max(size - int(match.group(2) or 0), 0)
        end = min(int(match.group(2)), size - 1) if match.group(1) and match.group(2) else size - 1
        if start >= size:
            self.send_error(416)
            return None
        handle = path.open("rb")
        handle.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._remaining = end - start + 1
        return handle

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)
        self._remaining = None

    def log_message(self, format, *args):  # quiet: one line per error only
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, help="a port in 4700-4799 (default: the first free one)")
    args = parser.parse_args()
    port = args.port or free_port()
    if port in listening_ports():
        raise SystemExit(f"port {port} is already in use (someone else owns it); omit --port to take a free one")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(ROOT)))
    print(f"sim2real: http://127.0.0.1:{port}/  (old app: /app/, proposals: /dashboards/; pid {os.getpid()}, Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
