"""The sim2real docs site (PEP 0001, docs/peps/0001-sim2real-docs-site-and-calibrate-backend.md, the site lane): robotmsgs.com's shape over
sim2real's registries. Types -> model rungs -> parameters -> calibration routines -> examples -> API reference.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_docs_site.py

Written by the designer BEFORE the site exists (red). The builder may not edit this file. The site is built once into a temporary folder
by `website/build/build.py --out <dir>`, and every check reads the built HTML with the standard library's parser. Expected values come
from the registries themselves (cards/domain.py, cards/calibration.py, sim2real.calibration.recovery), never from the site's own code, so
a page that drifts from the catalog goes red. Zach asked to KEEP the two tables he likes (the per-type model-rung table with "today's
model", and the routines table with runs / time / equipment $ / recovery at 0x 1x 3x 10x); their columns are pinned here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

REPO = Path(__file__).resolve().parents[1]
WEBSITE = REPO / "website"
ROBOT_MSGS = Path("/home/bam/robot_msgs")
LEVELS = ("0x", "1x", "3x", "10x")

RUNG_HEADERS = ["Rung", "Model", "Parameters", "Adds", "Identified by"]
ROUTINE_HEADERS = ["Routine", "Kind", "Runs", "Status", "Time", "Operator time", "Equipment $", "Recovery 0x", "Recovery 1x",
                   "Recovery 3x", "Recovery 10x", "Needs first"]
ROUTINE_FIELDS = ["Identifies", "Kind", "Runs", "Status", "Time", "Operator time", "Equipment", "Equipment $", "Requires", "Uses",
                  "Refines"]
EXAMPLES = ("pendulum_can11", "ur_wrist_test_rig")


# --- a small DOM over html.parser ------------------------------------------------------------------------------------------------------

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag: str, attrs: dict, parent: Node | None):
        self.tag, self.attrs, self.parent, self.children, self.parts = tag, attrs, parent, [], []

    def text(self) -> str:
        out = []
        for part in self.parts:
            out.append(part if isinstance(part, str) else part.text())
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def raw_text(self) -> str:
        return "".join(part if isinstance(part, str) else part.raw_text() for part in self.parts)

    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()

    def find_all(self, tag: str | None = None, **attrs) -> list[Node]:
        out = []
        for node in self.iter():
            if tag and node.tag != tag:
                continue
            if all((node.attrs.get(k.replace("_", "-")) == v) if v is not True else (k.replace("_", "-") in node.attrs)
                   for k, v in attrs.items()):
                out.append(node)
        return out

    def find(self, tag: str | None = None, **attrs) -> Node | None:
        found = self.find_all(tag, **attrs)
        return found[0] if found else None


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        self.cur.parts.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        self.cur.parts.append(node)

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.parts.append(data)


def parse(path: Path) -> Node:
    tree = Tree()
    tree.feed(path.read_text())
    return tree.root


def table_headers(table: Node) -> list[str]:
    head = table.find("thead") or table
    row = head.find("tr")
    return [cell.text() for cell in row.children if cell.tag in ("th", "td")]


def body_rows(table: Node) -> list[Node]:
    body = table.find("tbody")
    return [r for r in (body or table).find_all("tr") if r.find("td")]


# --- the build -------------------------------------------------------------------------------------------------------------------------

TRACKED = ("src", "sysid", "type_cards", "docs", "tests")


def _status() -> str:
    return subprocess.run(["git", "status", "--porcelain", "--", *TRACKED], cwd=REPO, capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("docs_site")
    before = _status()
    env = {**os.environ, "PYTHONPATH": f"{REPO / 'src'}:{REPO}"}
    env.pop("VIRTUAL_ENV", None)
    run = subprocess.run([sys.executable, str(WEBSITE / "build" / "build.py"), "--out", str(out)], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=900)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    return {"out": out, "status_before": before, "status_after": _status()}


def page(site, url_path: str) -> Node:
    path = site["out"] / url_path.strip("/") / "index.html" if not url_path.endswith(".html") else site["out"] / url_path.lstrip("/")
    assert path.is_file(), f"no page at {url_path}"
    return parse(path)


def all_pages(site) -> list[Path]:
    return sorted(site["out"].rglob("*.html"))


def dm():
    from sim2real.cards import domain  # noqa: PLC0415

    return domain


def cat():
    from sim2real.cards import calibration  # noqa: PLC0415

    return calibration


def rec():
    from sim2real.calibration import recovery  # noqa: PLC0415

    recovery.ladders.cache_clear()
    return recovery


def schema():
    from sim2real.cards import schema as module  # noqa: PLC0415

    return module


def type_routines(tid: str) -> set[str]:
    """The routines a type's page lists: every routine that identifies one of its parameters, and every routine that configures one of
    the cards it was built from (its settings)."""
    t = dm().entity_type(tid)
    ids = {rid for rids in dm().parameter_routines().get(tid, {}).values() for rid in rids}
    ids |= {r.id for r in cat().ROUTINES for c in r.configures if c.card in t.legacy_cards}
    return ids


# --- the site's own promises -------------------------------------------------------------------------------------------------------------


def test_the_build_reads_the_registries_and_writes_none_of_them(site):
    assert site["status_after"] == site["status_before"], "the site build changed tracked files"
    assert (site["out"] / "index.html").is_file() and (site["out"] / "404.html").is_file()


def test_the_css_and_js_are_robot_msgs_own_pinned_by_commit():
    """Shared with robotmsgs.com, pinned byte for byte to a robot_msgs commit (the way site/ pins robotparts' assets)."""
    pins = json.loads((WEBSITE / "site" / "PINNED.json").read_text())
    assert {"site.css", "site.js"} <= set(pins["files"])
    for name, pin in pins["files"].items():
        local = (WEBSITE / "site" / name).read_bytes()
        assert hashlib.sha256(local).hexdigest() == pin["sha256"], name
        if (ROBOT_MSGS / ".git").exists():
            blob = subprocess.run(["git", "-C", str(ROBOT_MSGS), "show", f"{pins['commit']}:{pin['path']}"], capture_output=True, check=True).stdout
            assert hashlib.sha256(blob).hexdigest() == pin["sha256"], f"{name} is not robot_msgs {pins['commit']}:{pin['path']}"


def test_home_links_every_section_and_the_sidebar_lists_the_types_in_order(site):
    home = page(site, "/")
    hrefs = {a.attrs.get("href") for a in home.find_all("a")}
    for section in ("/types/", "/routines/", "/examples/", "/api/"):
        assert section in hrefs, section
    nav = home.find(None, data_group="types")
    assert nav is not None, "the sidebar's Types group (data-group=types)"
    listed = [a.attrs["href"] for a in nav.find_all("a")]
    assert listed == [f"/types/{tid}/" for tid in dm().TYPE_ORDER]


# --- types: the model-rung table and the routines table ------------------------------------------------------------------------------------


def test_every_type_page_has_its_model_rungs_with_todays_model(site):
    for tid in dm().TYPE_ORDER:
        t = dm().entity_type(tid)
        doc = page(site, f"/types/{tid}/")
        assert len(doc.find_all("h1")) == 1 and t.title in doc.find("h1").text(), tid
        tables = doc.find_all("table", data_table="rungs")
        assert tables, f"{tid}: no model-rung table"
        rows = {}
        for table in tables:
            assert table_headers(table) == RUNG_HEADERS, (tid, table_headers(table))
            for row in body_rows(table):
                rows[row.attrs["data-model"]] = row
        assert set(rows) == {m.id for m in t.models}, tid
        for m in t.models:
            row = rows[m.id]
            cells = [c for c in row.children if c.tag in ("td", "th")]
            assert (row.attrs.get("data-current") == "true") == bool(m.current), (tid, m.id)
            assert ("today's model" in row.text()) == bool(m.current), (tid, m.id)
            assert cells[2].text().split()[0] == str(len(m.parameters)), (tid, m.id, cells[2].text())
            adds = {a.attrs["href"] for a in cells[3].find_all("a")}
            assert adds == {f"/parameters/{tid}/{n}/" for n in m.adds}, (tid, m.id)
            want = {rid for n in m.adds for rid in dm().routines_identifying(tid, n)}
            assert {a.attrs["href"] for a in cells[4].find_all("a")} == {f"/routines/{rid}/" for rid in want}, (tid, m.id)
            assert {a.attrs["href"] for a in cells[1].find_all("a")} >= {f"/models/{tid}/{m.id}/"}, (tid, m.id)


def _check_routine_rows(table: Node, ids: set[str], where: str):
    assert table_headers(table) == ROUTINE_HEADERS, (where, table_headers(table))
    rows = {r.attrs["data-routine"]: r for r in body_rows(table)}
    assert set(rows) == ids, (where, sorted(set(rows) ^ ids))
    by_id = {r.id: r for r in cat().ROUTINES}
    words = schema().KIND_WORDS
    for rid, row in rows.items():
        r = by_id[rid]
        cells = [c for c in row.children if c.tag in ("td", "th")]
        assert cells[1].text() == words[r.kind], (where, rid)
        assert cells[2].text() == r.setting, (where, rid)
        assert cells[3].text() == r.status, (where, rid)
        for level in LEVELS:
            cell = row.find("td", data_level=level)
            assert cell is not None, (where, rid, level)
            entry = rec().recovery(rid, level)
            ratio = None if entry is None else entry.get("worst_error_over_tolerance")
            if ratio is None:
                assert cell.attrs.get("data-ratio", "") == "" and "not graded" in cell.text(), (where, rid, level)
            else:
                assert float(cell.attrs["data-ratio"]) == pytest.approx(ratio, rel=1e-3, abs=1e-6), (where, rid, level)
                assert cell.attrs.get("data-pass") == ("true" if entry.get("pass") else "false"), (where, rid, level)
        for name in r.requires:
            assert name in cells[-1].text(), (where, rid, name)
        if not r.requires:
            assert cells[-1].text() in ("", "-", "\u2014"), (where, rid, cells[-1].text())


def test_every_type_page_lists_its_routines_with_recovery_at_every_level(site):
    for tid in dm().TYPE_ORDER:
        doc = page(site, f"/types/{tid}/")
        table = doc.find("table", data_table="routines")
        ids = type_routines(tid)
        if not ids:
            assert table is None or not body_rows(table), tid
            assert "no calibration routine" in doc.text().lower(), tid
            continue
        assert table is not None, f"{tid}: no routines table"
        _check_routine_rows(table, ids, f"/types/{tid}/")


def test_the_routines_index_is_the_whole_catalog(site):
    table = page(site, "/routines/").find("table", data_table="routines")
    _check_routine_rows(table, {r.id for r in cat().ROUTINES}, "/routines/")


# --- models, parameters, routines: one page each -------------------------------------------------------------------------------------------


def test_every_model_has_a_page_with_its_equation_and_parameters(site):
    for tid in dm().TYPE_ORDER:
        for m in dm().models(tid):
            doc = page(site, f"/models/{tid}/{m.id}/")
            hrefs = {a.attrs.get("href") for a in doc.find_all("a")}
            assert {f"/parameters/{tid}/{n}/" for n in m.parameters} <= hrefs, (tid, m.id)
            if m.equation:
                assert re.sub(r"\s+", " ", m.equation) in re.sub(r"\s+", " ", doc.raw_text()), (tid, m.id)
            assert f"/types/{tid}/" in hrefs


def test_every_parameter_has_a_page_with_its_unit_and_the_routines_that_identify_it(site):
    for tid in dm().TYPE_ORDER:
        for p in dm().entity_type(tid).parameters:
            doc = page(site, f"/parameters/{tid}/{p.name}/")
            unit = doc.find(None, data_field="unit")
            assert unit is not None and unit.text() == (p.unit or "-"), (tid, p.name)
            want = set(dm().routines_identifying(tid, p.name))
            got = {a.attrs["href"] for a in doc.find_all("a") if a.attrs.get("href", "").startswith("/routines/") and a.attrs["href"] != "/routines/"}
            assert got == {f"/routines/{rid}/" for rid in want}, (tid, p.name)
            if not want:
                assert "no routine identifies it yet" in doc.text(), (tid, p.name)


def test_every_routine_has_a_page_with_its_facts_dependencies_and_recovery_ladder(site):
    words = schema().KIND_WORDS
    for r in cat().ROUTINES:
        doc = page(site, f"/routines/{r.id}/")
        kv = doc.find("table", data_table="routine")
        assert kv is not None, r.id
        fields = {row.find("th").text(): row.find("td") for row in kv.find_all("tr") if row.find("th") and row.find("td")}
        assert list(fields)[: len(ROUTINE_FIELDS)] == ROUTINE_FIELDS, (r.id, list(fields))
        assert fields["Kind"].text() == words[r.kind] and fields["Runs"].text() == r.setting, r.id
        for name in ("requires", "uses", "refines"):
            for value in getattr(r, name):
                assert value in fields[name.capitalize()].text(), (r.id, name, value)
        ladder = doc.find("table", data_table="recovery")
        assert ladder is not None and [row.attrs.get("data-level") for row in body_rows(ladder)] == list(LEVELS), r.id


# --- examples and the API reference ----------------------------------------------------------------------------------------------------------


def test_every_example_shows_its_code_and_the_real_output_it_recorded(site):
    index = page(site, "/examples/")
    assert {f"/examples/{name}/" for name in EXAMPLES} <= {a.attrs.get("href") for a in index.find_all("a")}
    for name in EXAMPLES:
        source = (WEBSITE / "examples" / f"{name}.py").read_text()
        recorded = json.loads((WEBSITE / "examples" / f"{name}.out.json").read_text())
        assert recorded["source_sha256"] == hashlib.sha256(source.encode()).hexdigest(), f"{name}: the output is stale; re-run the example"
        doc = page(site, f"/examples/{name}/")
        code = doc.find("pre", data_source=name) or doc.find("pre")
        assert code is not None and code.raw_text().strip() == source.strip(), name
        out = doc.find(None, data_output=name)
        assert out is not None, name
        shown = {row.attrs["data-key"] for row in out.find_all("tr") if "data-key" in row.attrs}
        assert shown and shown == {p["key"] for p in recorded["parameters"]}, name


def _first_sentence(obj) -> str:
    import inspect  # noqa: PLC0415

    doc = inspect.getdoc(obj) or ""
    return re.split(r"(?<=[.:])\s", doc.split("\n\n")[0].replace("\n", " "), maxsplit=1)[0].replace("`", "")


def test_the_api_reference_is_generated_from_the_docstrings(site):
    from sim2real.twin import RobotTwin  # noqa: PLC0415

    doc = page(site, "/api/")
    for anchor, obj in (("api-RobotTwin", RobotTwin), ("api-RobotTwin-calibrate", RobotTwin.calibrate), ("api-RobotTwin-eval", RobotTwin.eval)):
        section = doc.find(None, id=anchor)
        assert section is not None, anchor
        assert _first_sentence(obj)[:60] in section.text().replace("`", ""), (anchor, _first_sentence(obj)[:60])


def test_the_guide_page_is_docs_api_md(site):
    first = next(line for line in (REPO / "docs" / "API.md").read_text().splitlines() if line.startswith("# "))
    assert page(site, "/docs/guide/").find("h1").text() == first[2:].strip()


# --- generic: links, anchors, landmarks, sitemap (robotmsgs.com's own checks, website/tests/test_site.py) --------------------------------------


def test_every_internal_link_and_anchor_resolves_and_ids_are_unique(site):
    out = site["out"]
    broken = []
    for path in all_pages(site):
        doc = parse(path)
        ids = [n.attrs["id"] for n in doc.iter() if "id" in n.attrs]
        assert len(ids) == len(set(ids)), (path, sorted({i for i in ids if ids.count(i) > 1})[:5])
        for a in doc.find_all("a"):
            href = a.attrs.get("href", "")
            if not href or href == "#" or href.startswith("mailto:"):
                continue
            url = urlparse(href)
            if url.scheme in ("http", "https"):
                assert url.scheme == "https", (path, href)
                continue
            if url.scheme:
                continue
            target = (out / unquote(url.path).lstrip("/")) if url.path.startswith("/") else (path.parent / unquote(url.path))
            if url.path == "" and url.fragment:
                target = path
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                broken.append((str(path.relative_to(out)), href))
                continue
            if url.fragment and target.suffix == ".html":
                tdoc = doc if target == path else parse(target)
                if not any(n.attrs.get("id") == url.fragment for n in tdoc.iter()):
                    broken.append((str(path.relative_to(out)), href))
    assert not broken, broken[:20]


def test_every_page_has_one_h1_main_and_nav_and_the_sitemap_lists_it(site):
    out = site["out"]
    sitemap = (out / "sitemap.xml").read_text()
    for path in all_pages(site):
        if path.name == "404.html":
            continue
        doc = parse(path)
        assert len(doc.find_all("h1")) == 1, path
        assert doc.find("main") is not None and doc.find("nav") is not None, path
        parent = path.relative_to(out).parent
        rel = ("/" if str(parent) == "." else f"/{parent.as_posix()}/") if path.name == "index.html" else f"/{path.relative_to(out).as_posix()}"
        assert rel in sitemap, rel
        assert path.stat().st_size < 2_000_000, path
