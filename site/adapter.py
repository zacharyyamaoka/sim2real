"""sim2real's adapter for catalog-workbench: reads the app's data (tools/build_app.py's tables, gitignored app/data/) into
one Site, names every record's URL, and pins the files sim2real takes from elsewhere (robotparts' shell scripts and
styles by commit, the vendored data-ui kit by its manifest).

Records (the three kinds of site/catalog.py):
- a **deployment**: one instantiated machine we do sim to real on (deployments.json; today the One Dof Test Rack);
- a **station**: one device of a deployment, a motor with its gates T1-T11 (devices.json, gates.json);
- a **run**: one real recording, played back against every model that replayed it (runs.json, runs/<run>/).

WHY an adapter and not a new data build: the producers (tools/build_app.py, bam_rack_twin) already write data-ui's
robotics tables; the migration changes the shell around them, never the numbers (Zach, 2026-10-29: "All we are going to
change is kinda the contents of the page but the layout of the site is the exact same").
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import tarfile
from collections import defaultdict
from dataclasses import dataclass, field

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
CACHE = pathlib.Path.home() / ".cache" / "sim2real"

# The app's data: env SIM2REAL_DATA, else this checkout's app/data (tools/build_app.py writes it)
DATA = pathlib.Path(os.environ.get("SIM2REAL_DATA") or REPO / "app" / "data")

# robotparts' static shell, byte for byte (the workbench ships the Python frame; the scripts and styles that run it are
# still robotparts', as for the object database). WHY main @ 115e020: it is the robotparts.dev that is live
# (release 2026.10.28.1), and its shell.js / site.js / site.css are the ones lane/catalog-workbench-stage3 serves.
ROBOTPARTS_REPO = pathlib.Path("/home/bam/robotparts")
SHELL_COMMIT = "115e020a22b449a7eff9b306f3a5541e8cbc6341"     # robotparts main, release 2026.10.28.1
ANALYSIS_COMMIT = "f51fc19159e8259856df476e6b6b2f6ea0cd635c"  # lane/analysis (PEP 0002): analysis.css, not on main yet
SHELL_STATIC = ("shell.js", "site.js", "site.css")

# The data-ui kit sim2real already vendors (vendor/data-ui/VENDOR.md); never re-vendored by the site build
KIT = REPO / "vendor" / "data-ui" / "dist"
KIT_PIN = HERE / "DATA_UI.json"
KIT_SKIP = ("site/", "python/")


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _materialise(commit: str, paths: tuple[str, ...]) -> pathlib.Path:
    """The pinned commit's files under CACHE/robotparts-<commit>-<what>/ (written once, from `git archive`)."""
    root = CACHE / f"robotparts-{commit[:12]}-{hashlib.sha256(' '.join(paths).encode()).hexdigest()[:8]}"
    if (root / ".complete").is_file():
        return root
    blob = subprocess.run(["git", "-C", str(ROBOTPARTS_REPO), "archive", commit, *paths], check=True, capture_output=True).stdout
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(root, filter="data")
    (root / ".complete").write_text(commit + "\n")
    return root


def shell_static() -> pathlib.Path:
    return _materialise(SHELL_COMMIT, tuple(f"site/static/{name}" for name in SHELL_STATIC)) / "site" / "static"


def analysis_css() -> pathlib.Path:
    return _materialise(ANALYSIS_COMMIT, ("site/static/analysis.css",)) / "site" / "static" / "analysis.css"


def kit_files() -> dict[str, str]:
    return {p.relative_to(KIT).as_posix(): sha256(p) for p in sorted(KIT.rglob("*"))
            if p.is_file() and not p.relative_to(KIT).as_posix().startswith(KIT_SKIP) and p.suffix != ".map"}


def check_kit() -> dict:
    """The vendored kit is the one site/DATA_UI.json pins (its manifest), so a re-vendor is a deliberate re-pin."""
    pin = json.loads(KIT_PIN.read_text())
    got = sha256(KIT / "manifest.json") if (KIT / "manifest.json").is_file() else None
    if got != pin["manifest_sha256"]:
        raise SystemExit(f"{KIT} is not the data-ui kit site/DATA_UI.json pins (manifest {got} != {pin['manifest_sha256']}); "
                         "re-pin on purpose with: python3 site/build.py --repin")
    return pin


def repin() -> dict:
    vendor_md = (REPO / "vendor" / "data-ui" / "VENDOR.md").read_text()
    source = re.search(r"\*\*Source:\*\* (.+?)\n", vendor_md)
    pin = {"what": "the data-ui kit sim2real already vendors (vendor/data-ui/dist, VENDOR.md), served at /static/data-ui/; never edited, never re-vendored by the site",
           "source": source.group(1).strip() if source else None, "manifest_sha256": sha256(KIT / "manifest.json"), "files": len(kit_files())}
    KIT_PIN.write_text(json.dumps(pin, indent=1, ensure_ascii=False) + "\n")
    return pin


# --- URLs -------------------------------------------------------------------------------------------------------------

def station_key(device: str) -> str:
    """"CAN 12" -> "can12" (the producers' own station id, why.json's `station`)."""
    return device.lower().replace(" ", "")


def deployment_url(dep_id: str) -> str:
    return f"/{dep_id}/"


def station_url(dep_id: str, device: str) -> str:
    return f"/{dep_id}/{station_key(device)}/"


def run_url(row: dict) -> str:
    return f"/{row['deployment']}/runs/{row['run']}/"


OLD_LINK = re.compile(r"/app/\?d=([\w.~-]+)((?:&[\w]+=[^&#\s\"]*)*)(#[^\s\"]*)?")


def new_link(match: re.Match) -> str:
    """The app's old query-string route (/app/?d=<d>&run=<r>&why=<s>&layer=gates#t=…) as the site's path. WHY the hash
    kept: `#t=…&tr=…` is data-ui's clock, and a run page's first tab is its Playback (site.js opens the first tab for
    a hash that names no tab), so an evidence link still lands on the playback at its window."""
    dep, query, frag = match.group(1), dict(re.findall(r"&(\w+)=([^&#]*)", match.group(2) or "")), match.group(3) or ""
    if query.get("run"):
        return f"/{dep}/runs/{query['run']}/{frag}"
    return f"/{dep}/{frag or ('#gates' if query.get('layer') == 'gates' else '')}"


def rewrite_links(text: str) -> str:
    return OLD_LINK.sub(new_link, text)


# --- the site ---------------------------------------------------------------------------------------------------------

def _rows(path: pathlib.Path) -> list[dict]:
    return json.loads(path.read_text())["rows"] if path.is_file() else []


@dataclass
class Deployment:
    row: dict
    folder: pathlib.Path
    runs: list[dict]
    devices: list[dict]
    gates: list[dict]
    why: list[dict]
    evidence: list[dict]
    caveats: list[dict]
    diagnostics: list[dict]
    run_gates: dict = field(default_factory=dict)   # run slug -> its rows of run_gates.json
    decompositions: set = field(default_factory=set)  # station keys with why/<station>.json

    @property
    def id(self) -> str:
        return self.row["id"]

    def gates_of(self, device: str) -> list[dict]:
        return sorted((g for g in self.gates if g["device"] == device), key=lambda g: g["order"])

    def why_of(self, device: str) -> list[dict]:
        return sorted((w for w in self.why if w["device"] == device), key=lambda w: (w.get("rank", 0), w.get("order", 0)))

    def runs_of(self, device: str) -> list[dict]:
        return [r for r in self.runs if r["device"] == device]

    def diagnostics_of(self, device: str) -> list[dict]:
        return [d for d in self.diagnostics if d.get("subject", "").endswith("/" + device)]

    def device(self, name: str) -> dict:
        return next(d for d in self.devices if d["device"] == name)

    def acceptance(self) -> dict | None:
        return next((e for e in self.evidence if e.get("kind") == "acceptance"), None)


@dataclass
class Station:
    """One device of a deployment, as a record of its own."""
    deployment: Deployment
    row: dict

    @property
    def device(self) -> str:
        return self.row["device"]

    @property
    def key(self) -> str:
        return station_key(self.device)

    @property
    def url(self) -> str:
        return station_url(self.deployment.id, self.device)


@dataclass
class Site:
    data: pathlib.Path
    deployments: list[Deployment]

    @property
    def runs(self) -> list[dict]:
        return [r for d in self.deployments for r in d.runs]

    @property
    def stations(self) -> list[Station]:
        return [Station(d, row) for d in self.deployments for row in sorted(d.devices, key=lambda r: r.get("order", 0))]

    def deployment(self, dep_id: str) -> Deployment:
        return next(d for d in self.deployments if d.id == dep_id)


def load(data: pathlib.Path = DATA) -> Site:
    """The app's tables, as the site serves them (site/build.py writes `data` with every old /app/ link rewritten)."""
    deployments = []
    for row in _rows(data / "deployments.json"):
        folder = data / row["id"]
        run_gates = defaultdict(list)
        for g in _rows(folder / "run_gates.json"):
            run_gates[g.get("run_slug") or g.get("run")].append(g)
        decompositions = {p.stem for p in (folder / "why").glob("*.json") if _rows(p)} if (folder / "why").is_dir() else set()  # an empty file draws empty axes
        deployments.append(Deployment(row=row, folder=folder, runs=_rows(folder / "runs.json"), devices=_rows(folder / "devices.json"),
                                      gates=_rows(folder / "gates.json"), why=_rows(folder / "why.json"), evidence=_rows(folder / "evidence.json"),
                                      caveats=_rows(folder / "caveats.json"), diagnostics=_rows(folder / "diagnostics.json"),
                                      run_gates=dict(run_gates), decompositions=decompositions))
    return Site(data=data, deployments=deployments)
