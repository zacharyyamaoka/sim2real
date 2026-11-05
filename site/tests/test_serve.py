"""serve.py serves the catalog-workbench site at / and keeps the old app and the proposals beside it.

    python3 /home/bam/sim2real/site/tests/test_serve.py

Starts serve.py on a free port in 4711-4799 (never 4700, Zach's), reads each route, stops it by the pid it started.
"""

from __future__ import annotations

import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
SITE = pathlib.Path.home() / ".cache" / "sim2real" / "site"


def free_port() -> int:
    taken = {int(m) for m in re.findall(r":(\d+)\s", subprocess.run(["ss", "-ltnH"], capture_output=True, text=True).stdout)}
    return next(port for port in range(4711, 4800) if port not in taken)


def fetch(base: str, route: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(base + route) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


def main() -> int:
    port = free_port()
    server = subprocess.Popen([sys.executable, str(REPO / "serve.py"), "--port", str(port)], stdout=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    fails = 0
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        want_home = (SITE / "index.html").read_bytes()
        want_app = (REPO / "app" / "index.html").read_bytes()
        checks = [("/ is the site's home", "/", 200, want_home),
                  ("a site page", "/one-dof-test-rack/", 200, (SITE / "one-dof-test-rack" / "index.html").read_bytes()),
                  ("the site's data", "/data/one-dof-test-rack/why.json", 200, (SITE / "data" / "one-dof-test-rack" / "why.json").read_bytes()),
                  ("/app/ is still the old app", "/app/", 200, want_app),
                  ("the app's kit", "/vendor/data-ui/dist/data-ui.css", 200, (REPO / "vendor" / "data-ui" / "dist" / "data-ui.css").read_bytes()),
                  ("the app's logo", "/brand/icons/sim2real-app.svg", 200, (REPO / "brand" / "icons" / "sim2real-app.svg").read_bytes()),
                  ("the proposals", "/dashboards/", 200, None),
                  ("nothing outside the two roots", "/../../.bashrc", 404, None)]
        for what, route, status, body in checks:
            got, data = fetch(base, route)
            ok = got == status and (body is None or data == body)
            fails += not ok
            print(("PASS " if ok else "FAIL ") + f"{what} ({route}: {got})", flush=True)
    finally:
        server.terminate()
        server.wait(timeout=10)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
