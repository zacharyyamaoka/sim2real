"""The sim2real landing page (Zach, Daily Note 2026-11-20, "# Sim2Real routines", line 221): pidtuna.com's section grammar on sim2real's
own site builder, in eight sections - hero, proof, modes, how, api, lifecycle, promises, sources. His three metrics (Sim / Sim on Real /
Sim on Real (tuned)) for his three robots (the 1-DOF pendulum, the UR arm, the BAM arm); his three modes (sim at the right values,
recover a hidden truth, pseudo-real); the API on one screen; bench vs deployed; deployed lifetime calibration and monitoring, marked
designed, not built.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_landing_page.py

Never on the workstation while the arm is powered: on a cloud VM (bam_ws tools/cloud recipe 2 with
--with-list tools/cloud/data/sim2real_landing.list; the calls test with recipe 1 and SIM2REAL_LANDING_CALLS=1).

Written by the designer BEFORE the page exists (red). The builder may not edit this file. Light: it runs website/build/build.py into a
temporary folder and reads the HTML with the standard library's parser; nothing calibrates and nothing imports MuJoCo (the calls test
excepted, which builds twins and plans, never calibrates). Every number on the page comes from website/data/landing.json and carries a
link to its source. Every source is re-read here through this file's own resolve/derive: in-repo files from the checkout, lab files
from byte-for-byte snapshots under /archive/datasets/sim2real_landing/<date>/ that the exporter writes once and nothing rewrites. A
missing snapshot fails unless SIM2REAL_LANDING_LAB=optional; a changed one always fails. website/build/export_landing.py --check
imports recheck() from this file, so the exporter never grades its own numbers. Prose that makes a claim (definitions, targets,
controller words, notes, whys, the hero, the lifecycle lists, media captions) lives in landing.json and is compared verbatim; prose in
pages.py may carry no digit, no comparative, no placeholder and no radian.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import math
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEBSITE = REPO / "website"
LANDING_JSON = WEBSITE / "data" / "landing.json"
SNAPSHOT_ROOT = Path(os.environ.get("SIM2REAL_LANDING_SNAPSHOTS", "/archive/datasets/sim2real_landing"))
LAB_OPTIONAL = os.environ.get("SIM2REAL_LANDING_LAB") == "optional"
GITHUB = "https://github.com/zacharyyamaoka/sim2real"

# WHY pinned by hash: the landing must not buy its green by loosening the docs site's own ruler (Zach, 2026-11-11: "I really like these
# tables"). A deliberate change to either file re-pins here in the same commit, with the reason in the commit message.
PINNED_TESTS = {
    "tests/test_docs_site.py": "fd3e107be5c942c40c8d9610dd42bf5897bfc5c05d1fbaa39a378f34f923bada",
    "tests/test_docs_site_merged.py": "4379909577bdd68f9948e8e90f3bba7b9a4ed20db67221b8a9752f18f6e0b05e",
}
# WHY eight, in this order (review 2026-11-20): pidtuna's hero -> proof -> how -> quickstart -> promises -> CTA, plus Zach's modes and
# bench/deployed, with no section saying twice what another says (the gallery is the proof table; the step strip is the seam diagram).
SECTIONS = ("hero", "proof", "modes", "how", "api", "lifecycle", "promises", "sources")
# WHY these titles: Zach's own words (Daily Note 2026-11-20 L227-229); "as found" belongs in the definition, not the title
METRICS = (("sim", "Sim"), ("on_real", "Sim on Real"), ("tuned", "Sim on Real (tuned)"))
RECOVERY_CELLS = ("recovered", "nominal", "fitted", "floor")
ROBOTS = ("pendulum", "ur_arm", "bam_arm")
ROWS = {"pendulum-real": ("pendulum", "real"), "ur5e-pseudo": ("ur_arm", "pseudo-real"), "urwrist-real": ("ur_arm", "real"),
        "bamarm-track": ("bam_arm", "real")}
RECOVERY_ROWS = {"pendulum-oracle": "pendulum", "urwrist-oracle": "ur_arm", "ur5e-oracle": "ur_arm", "bamarm-oracle": "bam_arm"}
# WHY pinned: a status cell is the honest answer only where nothing was measured; pinning them stops an inconvenient number from
# quietly becoming "not measured yet". A cell that gains a real number re-pins here, deliberately.
STATUS_CELLS = {("ur5e-pseudo", "sim"): "not_measured", ("urwrist-real", "sim"): "not_measured",
                ("bamarm-track", "sim"): "not_measured", ("ur5e-oracle", "floor"): "not_measured",
                **{("bamarm-oracle", cell): "not_built" for cell in RECOVERY_CELLS}}
MODE_STATUS = {1: {"pendulum": "not_built", "ur_arm": "not_built", "bam_arm": "not_built"},
               2: {"pendulum": "runs", "ur_arm": "runs", "bam_arm": "not_built"},
               3: {"pendulum": "runs", "ur_arm": "runs", "bam_arm": "not_built"}}
STATUS_WORDS = {"not_measured": "not measured yet", "not_built": "not built yet", "runs": "runs today"}
# WHY a like-for-like check per row (review A1: the as-found pendulum ran at half the tuned one's speed): each real row names the value
# pair that proves its cells played the same target, and the pair must agree within one percent
SAME_TARGET = {"pendulum-real": "peak_speed", "urwrist-real": "stops", "bamarm-track": "speed_fraction"}
SEAM_STEPS = ("describe", "twin", "schedule", "calibrate", "tune", "callbacks", "fitted", "evaluate", "preflight", "deployed")
LIFETIME_NAMES = ("production", "monitor", "recalibrate", "save_description")
TWIN_METHODS = ("from_robot_description", "generate_schedule", "calibrate", "evaluate")
TRACKED = ("src", "sysid", "type_cards", "docs", "tests", "website/data", "website/examples", "website/site", "website/build")

FORMATS = {"mm": "{n} mm", "°": "{n}°", "°/s": "{n}°/s", "× floor": "{n} × floor", "h": "{n} h", "": "{n}", "%": "{n}%",
           "×": "×{n}", "N·m": "{n} N·m"}
CONVERSIONS = {("m", "mm"): 1e3, ("mrad", "°"): 180.0 / math.pi / 1e3, ("rad", "°"): 180.0 / math.pi, ("deg", "°"): 1.0,
               ("rad/s", "°/s"): 180.0 / math.pi, ("x floor", "× floor"): 1.0, ("fraction", "%"): 100.0, ("x", "×"): 1.0,
               ("N.m", "N·m"): 1.0}
KPI_DISPLAY = {"mm": "mm", "deg": "°"}  # arm_motion_bench kpi_names display units -> this page's
# measure -> class. "stop" numbers carry a gate verdict; cells hold measured classes plus targets and settings.
MEASURES = {"stop_worst": "stop", "stop_median": "stop", "stop_task_worst_median": "stop", "gate_pass_rate": "rate",
            "tcp_rms": "tracking", "joint_rms": "tracking",
            "stops": "count", "within_gate": "count", "tasks": "count", "recovered": "count", "graded": "count",
            "not_identified": "count",
            "held_out_ratio": "fidelity", "held_out_tool": "fidelity", "held_out_flange": "fidelity", "fidelity_joint": "fidelity",
            "floor": "fidelity",
            "peak_speed": "target", "amplitude": "target", "speed_fraction": "target",
            "gain_scale": "setting", "feedforward": "setting", "hours": "hours", "gate": "gate"}
MEASURED = ("stop", "rate", "tracking", "count")
SOURCE_KINDS = ("real", "sim", "pseudo-real", "code", "setting", "mixed")
DECLARABLE = {"fidelity": ("real", "pseudo-real", "sim")}  # a mixed source's value with no real/sim step in its key declares its kind
GATE_WORDS = {"pass": "pass", "fail": "fail", "unjudged": "not judged"}
COMPARE_WORDS = {-1: "smaller than", 0: "the same as", 1: "larger than"}
MEDIA_EXT = (".webp", ".jpg", ".png")  # WHY no .mp4/.webm/.gif: the cloud cut drops them (bam_ws tools/cloud/slim_repo.py), so a VM
#                                        would build a page whose video is missing and this ruler would be red for the wrong reason

COMPARATIVE = re.compile(r"\b(better|worse|closer|further|farther|beats?|improve[sd]?|improvements?|worsen(?:s|ed)?|outperforms?|"
                         r"regress(?:es|ed)?|smaller|larger)\b", re.I)
RADIANS = re.compile(r"\b(m?rad(?:/s)?|degs?)\b")
PLACEHOLDER = re.compile(r"\b(nan|NaN|null|undefined|TODO|TBD|FIXME|XXX|lorem)\b|\bNone\b(?!\s+of\b)|\?\?\?|[{}]")
# WHY: a CAN adapter's serial (8 upper-case hex) or a camera's (a D405's is twelve digits) is lab data, not page data. pidtuna's public
# guard also bans CAN ids and the words rack, serial and twin; those are this page's subject, so only the serial patterns stay.
SERIAL = re.compile(r"\b(?=[0-9A-F]*[A-F])(?=[0-9A-F]*[0-9])[0-9A-F]{8}\b|(?<![\d.])\d{10,}(?![\d.])")
NAME_SPAN = re.compile(r"CAN \d{1,2}|\d-DOF")  # the only digit-led names prose may show, inside <span class="name">
TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*")
PLACE = re.compile(r"\{(=[^{}]+|gate:[a-z0-9_.-]+|cmp:[a-z0-9_.-]+:[a-z0-9_.-]+|[a-z0-9][a-z0-9_.-]*)\}")
ABSOLUTE = re.compile(r'"(?:/home/|/archive/|/tmp/|/root/|~/)')
INTEGRATOR = re.compile(r"\bintegra(?:l|tor)s?\b", re.I)


# --- a small DOM over html.parser (tests/test_docs_site.py's; copied, since that file is pinned) ------------------------------------------

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

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def inside(self, tag: str) -> bool:
        node = self.parent
        while node is not None:
            if node.tag == tag:
                return True
            node = node.parent
        return False


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
    tree.feed(path.read_text(encoding="utf-8"))
    return tree.root


def norm(text: str) -> str:
    return " ".join(text.split())


def text_skipping(node: Node, skip, gap: str) -> str:
    out = []
    for part in node.parts:
        if isinstance(part, str):
            out.append(part)
        elif skip(part):
            out.append(gap)
        else:
            out.append(text_skipping(part, skip, gap))
    return "".join(out)


def shown(node: Node) -> str:
    """What a reader reads in a node, minus the [n] links to the sources list."""
    return norm(text_skipping(node, lambda n: n.tag == "a" and "src" in n.classes(), ""))


def exempt(node: Node) -> bool:
    """Elements whose digits are checked elsewhere (or are code): everything else a reader sees is prose and may carry none."""
    a = node.attrs
    if node.tag in ("pre", "code", "script", "style", "svg", "footer"):
        return True
    if "data-value" in a or "data-count" in a or "data-setting-count" in a or "data-mode-n" in a:
        return True
    if node.tag == "time" and "data-source-date" in a:
        return True
    if node.tag == "li" and ("data-source-id" in a or "data-media-id" in a):
        return True
    return node.tag == "span" and "name" in node.classes() and bool(NAME_SPAN.fullmatch(node.text()))


def under(node: Node, attr: str, stop: Node) -> bool:
    cur = node.parent
    while cur is not None and cur is not stop:
        if attr in cur.attrs:
            return True
        cur = cur.parent
    return False


def prose(node: Node) -> str:
    return norm(text_skipping(node, exempt, " "))


def loose_numbers(text: str) -> list[str]:
    """Digit-led tokens (a number typed into prose), and x2-style factors; letter-led names (sim2real, can11-r18a, it5, p95) pass."""
    return [t for t in TOKEN.findall(text) if t[0].isdigit() or re.match(r"[xX]\d", t)]


# --- the export, read with this file's own code ---------------------------------------------------------------------------------------------

_JSON: dict[str, object] = {}


def load_json(path: Path):
    key = str(path)
    if key not in _JSON:
        _JSON[key] = json.loads(path.read_text(encoding="utf-8"))
    return _JSON[key]


def same(a, b) -> bool:
    if isinstance(b, bool) or isinstance(a, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def _matches(item, want: dict) -> bool:
    return isinstance(item, dict) and all(same(item.get(k), v) for k, v in want.items())


def resolve(doc, key: list):
    """A key is a list of steps: a dict key, a list index, {"where": {field: value}} (the one list item whose fields match), or
    {"newest": {"where", "startswith", "excludes", "by"}} (of the items that match, the one with the largest `by`)."""
    node = doc
    for step in key:
        if isinstance(step, dict) and "where" in step:
            matches = [item for item in node if _matches(item, step["where"])]
            assert len(matches) == 1, f"{step} matches {len(matches)} items, not one"
            node = matches[0]
        elif isinstance(step, dict) and "newest" in step:
            rule = step["newest"]
            matches = [item for item in node if _matches(item, rule.get("where", {}))
                       and all(str(item.get(f, "")).startswith(p) for f, p in rule.get("startswith", {}).items())
                       and not any(w.lower() in str(item.get(f, "")).lower() for f, words in rule.get("excludes", {}).items()
                                   for w in words)]
            assert matches, f"{step} matches nothing"
            node = max(matches, key=lambda item: str(item[rule["by"]]))
        else:
            node = node[step]
    return node


def derive(raw, rule):
    """export_landing.py's derive vocabulary, re-implemented here so the ruler never trusts the exporter's own code."""
    if rule is None:
        return raw
    if "size" in rule:
        return len(raw)
    if "count" in rule:
        spec = rule["count"]
        items = list(raw.values()) if isinstance(raw, dict) else list(raw)
        if "equals" in spec:
            return sum(1 for item in items if same(item.get(spec["field"]), spec["equals"]))
        return sum(1 for item in items if (item.get(spec["field"]) is not None) == spec["present"])
    if "basename" in rule:
        return str(raw).rstrip("/").rsplit("/", 1)[-1]
    if "pluck" in rule:
        return ", ".join(str(item[rule["pluck"]]) for item in raw)
    raise AssertionError(f"unknown derive rule {rule}")


def read_source(path: Path, key: list):
    if path.suffix == ".py":  # a module-level literal, read without importing the module
        name, *rest = key
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return resolve(ast.literal_eval(node.value), rest)
        raise AssertionError(f"{path}: no module-level {name}")
    return resolve(load_json(path), key)


def kpi(path: Path, name: str) -> tuple[str, str, float]:
    """arm_motion_bench's kpi_names.py: K("<name>", category, unit, display_unit, scale, ...) -> (unit, display_unit, scale)."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "K" and node.args and \
                isinstance(node.args[0], ast.Constant) and node.args[0].value == name:
            return tuple(ast.literal_eval(arg) for arg in node.args[2:5])
    raise AssertionError(f"{path}: no K({name!r}, ...)")


def source_path(src: dict) -> Path:
    if src["in_repo"]:
        return REPO / src["path"]
    assert src["snapshot"].startswith("snap:"), src["snapshot"]
    return SNAPSHOT_ROOT / src["snapshot"][len("snap:"):]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def own_git() -> bool:
    """True in sim2real's own checkout; False in a cloud cut, where the vendored tree is not its own repo."""
    run = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=REPO, capture_output=True, text=True)
    return run.returncode == 0 and Path(run.stdout.strip()).resolve() == REPO.resolve()


def value_kind(v: dict, src: dict) -> str:
    cls = MEASURES[v["measure"]]
    if cls in ("target", "setting"):
        return cls
    if src["kind"] == "mixed":
        for step in v["key"]:
            if isinstance(step, str) and step in src["kind_by_key"]:
                return src["kind_by_key"][step]
        assert v.get("kind") in DECLARABLE.get(cls, ()), f"{v}: a mixed source's value with no real/sim step must declare its kind"
        return v["kind"]
    return src["kind"]


def recheck(data: dict, *, require_lab: bool = True) -> tuple[list[str], dict]:
    """Re-read every number and label from its file. Returns (problems, counts); the export is good when problems is empty."""
    problems: list[str] = []
    counts = {"repo": 0, "lab": 0, "skipped": set()}
    ok: dict[str, Path | None] = {}

    def load(sid: str) -> Path | None:
        if sid in ok:
            return ok[sid]
        src = data["sources"][sid]
        path = source_path(src)
        if not path.is_file():
            if src["in_repo"] or require_lab:
                problems.append(f"{sid}: {src['shown']} is missing ({path})")
            else:
                counts["skipped"].add(sid)
            ok[sid] = None
        elif sha(path.read_bytes()) != src["sha256"]:
            problems.append(f"{sid}: {path} changed since the export (a snapshot is never rewritten; an in-repo file means re-export)")
            ok[sid] = None
        else:
            ok[sid] = path
        return ok[sid]

    for vid, v in data["values"].items():
        src = data["sources"][v["source"]]
        path = load(v["source"])
        if path is None:
            continue
        try:
            got = derive(read_source(path, v["key"]), v.get("derive"))
        except Exception as exc:  # noqa: BLE001 - named in the problem list
            problems.append(f"{vid}: {exc!r}")
            continue
        if not (isinstance(got, (int, float)) and not isinstance(got, bool) and math.isfinite(got) and same(got, v["value"])):
            problems.append(f"{vid}: the file says {got!r}, the export {v['value']!r}")
            continue
        if value_kind(v, src) != v["kind"]:
            problems.append(f"{vid}: kind {v['kind']!r}, its key path says {value_kind(v, src)!r}")
        if v.get("kpi"):
            kpath = load(v["kpi"]["source"])
            if kpath is not None:
                unit, display, scale = kpi(kpath, v["kpi"]["name"])
                want_unit = unit if src["unit_convention"] == "si" else display
                want_scale = scale if src["unit_convention"] == "si" else CONVERSIONS.get((display, KPI_DISPLAY[display]), 1.0)
                if v["unit"] != want_unit or v["display_unit"] != KPI_DISPLAY[display] or not same(v["scale"], want_scale):
                    problems.append(f"{vid}: kpi_names says {unit}/{display}x{scale}; the export {v['unit']}/{v['display_unit']}x{v['scale']}")
        counts["repo" if src["in_repo"] else "lab"] += 1
    for lid, label in data["labels"].items():
        path = load(label["source"])
        if path is None:
            continue
        try:
            got = derive(read_source(path, label["key"]), label.get("derive"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"label {lid}: {exc!r}")
            continue
        if got != label["text"]:
            problems.append(f"label {lid}: the file says {got!r}, the export {label['text']!r}")
    git = own_git()
    for sid, src in data["sources"].items():
        path = load(sid)
        if path is None:
            continue
        if src.get("dated_from") == "key":
            got = read_source(path, src["dated_key"])
            if str(got) != src["dated"]:
                problems.append(f"{sid}: dated {src['dated']!r}, its {src['dated_key']} says {got!r}")
        if src["in_repo"] and git:
            blob = subprocess.run(["git", "show", f"{src['commit']}:{src['path']}"], cwd=REPO, capture_output=True)
            if blob.returncode != 0 or sha(blob.stdout) != src["sha256"]:
                problems.append(f"{sid}: {src['path']} at {src['commit']} is not the exported file")
    for mid, media in data["media"].items():
        path = WEBSITE / "site" / media["file"]
        if not path.is_file() or sha(path.read_bytes()) != media["sha256"]:
            problems.append(f"media {mid}: website/site/{media['file']} is missing or not the exported file")
    return problems, counts


def fmt(v: dict) -> str:
    return FORMATS[v["display_unit"]].format(n=f"{v['value'] * v['scale']:.{v['digits']}f}")


def gate_verdict(data: dict, vid: str) -> str:
    """The 1 mm tool gate at every stop (sim2real.result.TOOL_GATE_MM). A worst stop passes or fails; a median above the gate proves a
    fail (at least one stop is above it), a median at or under it proves nothing; a pass rate of one is a pass."""
    v, g = data["values"][vid], data["values"][data["gate"]]
    if v["measure"] == "gate_pass_rate":
        return "pass" if v["value"] >= 1.0 - 1e-12 else "fail"
    assert v["display_unit"] == g["display_unit"] == "mm", vid
    value, limit = v["value"] * v["scale"], g["value"] * g["scale"]
    if v["measure"] == "stop_worst":
        return "pass" if value <= limit else "fail"
    if v["measure"] in ("stop_median", "stop_task_worst_median"):
        return "fail" if value > limit else "unjudged"
    raise AssertionError(f"{vid}: {v['measure']} is no stop measure the gate can judge")


def compare(data: dict, a: str, b: str) -> str:
    va, vb = data["values"][a], data["values"][b]
    assert va["display_unit"] == vb["display_unit"], (a, b)
    x, y = va["value"] * va["scale"], vb["value"] * vb["scale"]
    return COMPARE_WORDS[0 if math.isclose(x, y, rel_tol=1e-9) else (1 if x > y else -1)]


def render(template: str, data: dict) -> str:
    """A landing.json template as a reader sees it: {value-id} -> its formatted number, {=name} -> name, {gate:value-id} -> the verdict,
    {cmp:a:b} -> the computed comparison, `code` -> code."""
    def one(match):
        body = match.group(1)
        if body.startswith("="):
            return body[1:]
        if body.startswith("gate:"):
            return GATE_WORDS[gate_verdict(data, body[5:])]
        if body.startswith("cmp:"):
            _, a, b = body.split(":")
            return compare(data, a, b)
        return fmt(data["values"][body])
    return norm(PLACE.sub(one, template).replace("`", ""))


def template_ids(template: str) -> set[str]:
    out = set()
    for body in PLACE.findall(template):
        if body.startswith("="):
            continue
        out |= set(body.split(":")[1:]) if body.startswith(("gate:", "cmp:")) else {body}
    return out


def proof_rows(data: dict) -> list[dict]:
    return [row for robot in data["robots"] for row in robot["rows"]]


def templates(data: dict):
    """Every prose template the page shows."""
    hero = data["hero"]
    yield from (hero["eyebrow"], hero["h1"], hero["lead"], hero["today"], *hero["lines"])
    yield from (m["definition"] for m in data["metrics"].values())
    for row in proof_rows(data):
        yield from (row["title"], row["target"], *row.get("notes", ()))
        for cell in row["cells"].values():
            if "controller" in cell:
                yield cell["controller"]["words"]
            if "why" in cell:
                yield cell["why"]
    for row in data["recovery"]:
        yield from (row["title"], row["measure"], *row.get("notes", ()))
        yield from (cell["why"] for cell in row["cells"].values() if "why" in cell)
    for mode in data["modes"]:
        yield from (mode["title"], mode["what"], *(r["why"] for r in mode["robots"].values()))
    for item in data["lifecycle"]["today"]:
        yield item["text"]
    yield from (item["text"] for item in data["lifecycle"]["not_built"])
    yield from (m["what"] for m in data["media"].values())


def used_value_ids(data: dict) -> set[str]:
    used = {data["gate"]}
    for template in templates(data):
        used |= template_ids(template)
    for row in [*proof_rows(data), *data["recovery"]]:
        for cell in row["cells"].values():
            used |= set(cell.get("values", ()))
            if "gate" in cell:
                used.add(cell["gate"])
    return used


# --- the build ---------------------------------------------------------------------------------------------------------------------------


def _status() -> str:
    return subprocess.run(["git", "status", "--porcelain", "--", *TRACKED], cwd=REPO, capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def data() -> dict:
    assert LANDING_JSON.is_file(), "no website/data/landing.json: run website/build/export_landing.py on the workstation and commit it"
    return json.loads(LANDING_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("landing_site")
    before = _status()
    env = {**os.environ, "PYTHONPATH": f"{REPO / 'src'}:{REPO}"}
    env.pop("VIRTUAL_ENV", None)
    run = subprocess.run([sys.executable, str(WEBSITE / "build" / "build.py"), "--out", str(out)], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=900)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    return {"out": out, "before": before, "after": _status(), "stdout": run.stdout}


@pytest.fixture(scope="module")
def home(site) -> Node:
    return parse(site["out"] / "index.html")


def section(home: Node, name: str) -> Node:
    node = home.find("main").find(None, data_section=name)
    assert node is not None, f"the landing has no data-section={name!r}"
    return node


def cat():
    from sim2real.cards import calibration  # noqa: PLC0415

    return calibration


def dm():
    from sim2real.cards import domain  # noqa: PLC0415

    return domain


# --- what the landing may not change -------------------------------------------------------------------------------------------------------


def test_the_docs_site_rulers_are_untouched():
    for rel, digest in PINNED_TESTS.items():
        assert sha((REPO / rel).read_bytes()) == digest, f"{rel} changed: the landing may not edit the docs site's ruler"


def test_the_build_writes_no_tracked_file_and_reports_no_stale_source(site):
    assert site["after"] == site["before"], "the site build changed tracked files"
    assert "STALE landing" not in site["stdout"], site["stdout"][-2000:]


def test_the_landing_keeps_the_docs_site_contract(site, home):
    """The promises tests/test_docs_site.py makes of the home page, re-read on the new one, plus every anchor and every file it loads."""
    assert len(home.find_all("h1")) == 1
    main = home.find("main")
    assert main is not None and home.find("nav") is not None
    hrefs = {a.attrs.get("href") for a in home.find_all("a")}
    assert {"/types/", "/routines/", "/examples/", "/api/", "/docs/deployed/"} <= hrefs
    group = home.find(None, data_group="types")
    assert group is not None and [a.attrs["href"] for a in group.find_all("a")] == [f"/types/{t}/" for t in dm().TYPE_ORDER]
    raw = (site["out"] / "index.html").read_bytes()
    assert len(raw) < 2_000_000 and not re.search(rb'(?:src|href|poster)="data:|url\(["\']?data:', raw), "media ship as files"
    ids = [n.attrs["id"] for n in home.iter() if "id" in n.attrs]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})
    pages: dict[str, set[str]] = {}
    for href in sorted(h for h in hrefs if h and "#" in h):
        path, frag = href.split("#", 1)
        if not frag or path.startswith(("http:", "https:")):
            continue
        if path == "":
            assert frag in ids, href
            continue
        if path not in pages:
            target = site["out"] / path.strip("/") / "index.html"
            assert target.is_file(), href
            pages[path] = {n.attrs["id"] for n in parse(target).iter() if "id" in n.attrs}
        assert frag in pages[path], href
    for href in hrefs:
        if href and href.startswith("/") and "#" not in href:
            assert (site["out"] / href.strip("/") / "index.html").is_file() or (site["out"] / href.lstrip("/")).is_file(), href
        if href and href.startswith("http"):
            assert href.startswith("https://"), href
    for node in main.iter():
        if "src" in node.attrs:
            src = node.attrs["src"]
            assert src.startswith("/assets/") and (site["out"] / src.lstrip("/")).is_file(), src
    assert not main.find_all("video") and not main.find_all("source"), "a video file would be missing on the cloud cut (MEDIA_EXT)"


def test_the_page_has_pidtunas_sections_in_order(home):
    order = [n.attrs["data-section"] for n in home.find("main").find_all(None, data_section=True)]
    assert order == list(SECTIONS), order


# --- the export ------------------------------------------------------------------------------------------------------------------------------


def test_the_export_is_well_formed_and_public_safe(data):
    assert data["schema"] == "sim2real.landing/1"
    for key in ("exported_utc", "exporter", "sim2real_commit", "gate", "metrics", "sources", "values", "labels", "media", "hero",
                "robots", "recovery", "modes", "lifecycle"):
        assert key in data, key
    assert set(data["metrics"]) == {k for k, _ in METRICS}
    for key, title in METRICS:
        assert data["metrics"][key]["title"] == title, key
    for sid, src in data["sources"].items():
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", sid), sid
        assert re.fullmatch(r"[0-9a-f]{64}", src["sha256"]) and src["kind"] in SOURCE_KINDS, sid
        assert src["shown"].strip() and src["what"].strip() and isinstance(src["in_repo"], bool) and isinstance(src["moving"], bool), sid
        assert src["dated"] and src["dated_from"] in ("key", "commit", "mtime"), sid
        if src["in_repo"]:
            assert not Path(src["path"]).is_absolute() and re.fullmatch(r"[0-9a-f]{40}", src["commit"]), sid
        else:
            assert re.fullmatch(r"snap:\d{4}-\d{2}-\d{2}/[a-z0-9-]+\.[a-z]+", src["snapshot"]) and ":" in src["from"], sid
        if src["kind"] == "mixed":
            assert set(src["kind_by_key"].values()) <= {"real", "sim", "pseudo-real"}, sid
        if src.get("from", "").startswith("amb:") and src["kind"] != "code":
            assert src.get("unit_convention") in ("si", "display"), f"{sid}: an arm_motion_bench file must say how it stores units"
    for vid, v in data["values"].items():
        src = data["sources"].get(v["source"])
        assert src is not None and isinstance(v["key"], list) and v["key"], vid
        assert v["measure"] in MEASURES and v["kind"] in ("real", "sim", "pseudo-real", "code", "setting", "target"), vid
        assert isinstance(v["value"], (int, float)) and not isinstance(v["value"], bool) and math.isfinite(v["value"]), vid
        assert v["display_unit"] in FORMATS and isinstance(v["digits"], int) and 0 <= v["digits"] <= 6, vid
        if src.get("unit_convention") and v["unit"] not in ("", "fraction"):
            assert v.get("kpi") and v["kpi"]["source"] in data["sources"], f"{vid}: an arm_motion_bench number names its kpi"
        elif v["unit"] == v["display_unit"]:
            assert v["scale"] == 1, vid
        else:
            assert v["scale"] == pytest.approx(CONVERSIONS[(v["unit"], v["display_unit"])]), vid
    for lid, label in data["labels"].items():
        assert label["source"] in data["sources"] and isinstance(label["text"], str) and label["text"].strip(), lid
    assert used_value_ids(data) <= set(data["values"]), sorted(used_value_ids(data) - set(data["values"]))
    gate = data["values"][data["gate"]]
    assert gate["measure"] == "gate" and gate["display_unit"] == "mm" and data["sources"][gate["source"]]["kind"] == "code"
    assert gate["key"] == ["TOOL_GATE_MM"] and data["sources"][gate["source"]]["path"] == "src/sim2real/result.py"
    text = LANDING_JSON.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    assert not SERIAL.search(text), SERIAL.search(text).group(0)
    assert not ABSOLUTE.search(text), "landing.json is public: logical names only (lab:, amb:, snap:), never an absolute path"
    for template in templates(data):  # WHY (review C R1, R2): a template's prose carries no number; numbers are {value-id}s
        assert not loose_numbers(prose_of_template(template)), template
        for body in PLACE.findall(template):
            if body.startswith("="):
                assert NAME_SPAN.fullmatch(body[1:]) or not loose_numbers(body[1:]), (template, body)


def prose_of_template(template: str) -> str:
    """A template's prose: placeholders and `code` removed."""
    return norm(re.sub(r"`[^`]*`", " ", PLACE.sub(" ", template)))


def test_every_number_and_label_still_says_what_its_file_says(data):
    """Every value and label re-read from its file through this file's own resolve/derive (G9 of the 2026-11-20 review)."""
    problems, counts = recheck(data, require_lab=not LAB_OPTIONAL)
    assert not problems, "\n".join(problems)
    in_repo = sum(1 for v in data["values"].values() if data["sources"][v["source"]]["in_repo"])
    assert counts["repo"] == in_repo and in_repo, (counts, in_repo)
    if not LAB_OPTIONAL:
        lab = sum(1 for v in data["values"].values() if not data["sources"][v["source"]]["in_repo"])
        assert counts["lab"] == lab, (counts, lab)


# --- hero ----------------------------------------------------------------------------------------------------------------------------------


def test_the_hero_states_the_aim_today_and_sim2reals_own_numbers(home, data):
    hero, want = section(home, "hero"), data["hero"]
    assert shown(hero.find("h1")) == render(want["h1"], data)
    assert shown(hero.find(None, data_today=True)) == render(want["today"], data)
    readout = hero.find(None, data_readout=True)
    assert readout is not None and readout.find(None, data_chip="pseudo-real") is not None
    lines = [shown(n) for n in readout.find_all(None, data_line=True)]
    assert lines == [render(line, data) for line in want["lines"]]
    recovery_ids = {vid for row in data["recovery"] for cell in row["cells"].values() for vid in cell.get("values", ())}
    for line in want["lines"]:  # WHY (review A3): the hero shows only sim2real's own output, never a campaign's
        for vid in template_ids(line):
            assert vid in recovery_ids and data["values"][vid]["kind"] == "pseudo-real", vid
    assert hero.find(None, data_count="types").text() == str(len(dm().TYPE_ORDER))
    assert hero.find(None, data_count="routines").text() == str(len(cat().ROUTINES))
    figure = hero.find("figure", data_media=want["media"])
    assert figure is not None and data["media"][want["media"]]["file"].endswith(".webp")


# --- proof: the three metrics, the three robots ---------------------------------------------------------------------------------------------


def test_the_three_metrics_head_the_proof_table_and_are_defined(home, data):
    proof = section(home, "proof")
    table = proof.find("table", data_table="metrics")
    assert table is not None
    heads = [(th.attrs["data-metric"], th.text()) for th in table.find("thead").find_all("th", data_metric=True)]
    assert heads == list(METRICS)
    for key, _ in METRICS:
        definition = proof.find("dd", data_metric_def=key)
        assert definition is not None and shown(definition) == render(data["metrics"][key]["definition"], data), key
    caveat = table.find("caption")
    caveat = caveat.find(None, data_caveat=True) if caveat else None
    assert caveat is not None and "calibrate(" in caveat.text() and "hardware" in caveat.text(), \
        "the table must say, next to its numbers, that campaign tooling measured them, not calibrate(on='real')"


def test_every_robot_has_its_rows_each_with_its_three_cells(home, data):
    assert [r["id"] for r in data["robots"]] == list(ROBOTS)
    assert {row["id"]: (robot["id"], row["where"]) for robot in data["robots"] for row in robot["rows"]} == ROWS
    table = section(home, "proof").find("table", data_table="metrics")
    trs = {tr.attrs["data-row"]: tr for tr in table.find("tbody").find_all("tr") if "data-row" in tr.attrs}
    assert set(trs) == set(ROWS)
    for row in proof_rows(data):
        tr, (robot, where) = trs[row["id"]], ROWS[row["id"]]
        assert tr.attrs.get("data-robot") == robot and tr.attrs.get("data-where") == where, row["id"]
        assert [td.attrs["data-cell"] for td in tr.find_all("td", data_cell=True)] == [k for k, _ in METRICS], row["id"]
        th = tr.find("th", data_cell="robot")
        assert th is not None and shown(th.find(None, data_title=True)) == render(row["title"], data), row["id"]
        assert any(a.attrs.get("href") == row["link"] for a in th.find_all("a")), row["id"]
        assert shown(th.find(None, data_where_chip=True)) == where, row["id"]
        assert shown(th.find(None, data_target=True)) == render(row["target"], data), row["id"]
        figures = th.find_all("figure", data_media=True)
        if where == "real":  # WHY (review B8): Zach asked to see the real robots; each real row shows its own, a pseudo-real one none
            assert [f.attrs["data-media"] for f in figures] == [row["media"]], row["id"]
        else:
            assert not figures, row["id"]
    links = {row["id"]: row["link"] for row in proof_rows(data)}
    assert links["pendulum-real"] == "/examples/pendulum_can11/" and links["urwrist-real"] == "/examples/ur_wrist_test_rig/"


def test_each_real_row_plays_the_same_target_in_every_cell(data):
    for row in proof_rows(data):
        pairs = row.get("same", [])
        if row["id"] in SAME_TARGET:
            assert any(data["values"][a]["measure"] == SAME_TARGET[row["id"]] for a, _ in pairs), row["id"]
        for a, b in pairs:
            va, vb = data["values"][a], data["values"][b]
            assert va["measure"] == vb["measure"] and va["display_unit"] == vb["display_unit"], (row["id"], a, b)
            assert va["value"] * va["scale"] == pytest.approx(vb["value"] * vb["scale"], rel=0.01), (row["id"], a, b)


def _cells(home, data):
    proof = section(home, "proof").find("table", data_table="metrics")
    recovery = section(home, "modes").find("table", data_table="recovery-proof")
    for table, rows, where_of in ((proof, proof_rows(data), lambda r: r["where"]), (recovery, data["recovery"], lambda r: "pseudo-real")):
        for row in rows:
            tr = table.find("tr", data_row=row["id"])
            for key, spec in row["cells"].items():
                yield row["id"], where_of(row), key, spec, (tr.find("td", data_cell=key) if tr else None)


def test_every_cell_is_sourced_numbers_or_says_why_not(home, data):
    values, labels = data["values"], data["labels"]
    status_seen = {}
    for rid, where, key, spec, td in _cells(home, data):
        at = (rid, key)
        assert td is not None, at
        if "status" in spec:
            status_seen[at] = spec["status"]
            status = td.find(None, data_status=spec["status"])
            assert status is not None and STATUS_WORDS[spec["status"]] in status.text(), at
            why = td.find(None, data_why=True)
            assert why is not None and shown(why) == render(spec["why"], data) and spec["why"].strip(), at
            assert not td.find_all(None, data_value=True), at
            continue
        ids = [n.attrs.get("data-value-id") for n in td.find_all(None, data_value=True) if not under(n, "data-ctl-words", td)]
        assert ids and ids == list(spec["values"]), at
        for vid in spec["values"]:  # WHY (review G5): a real row's robot cells hold real numbers, its Sim cell sim ones
            v, cls = values[vid], MEASURES[values[vid]["measure"]]
            if cls not in MEASURED:
                assert cls in (("target", "setting") if rid in ROWS else ("fidelity",)), (at, vid, cls)
                if cls == "fidelity":
                    assert v["kind"] == "pseudo-real", (at, vid, v["kind"])
                continue
            want = "pseudo-real" if where == "pseudo-real" and key != "sim" else ("sim" if key == "sim" else "real")
            assert v["kind"] == want, (at, vid, v["kind"], want)
        stops = [vid for vid in spec["values"] if MEASURES[values[vid]["measure"]] == "stop"]
        if stops:  # WHY (review A6, G8): every stop number shown carries its verdict against the gate
            assert spec.get("gate") in spec["values"], at
            chip = td.find(None, data_gate_value=spec["gate"])
            assert chip is not None, at
        if "controller" in spec:  # WHY (review G2, G6): words are prose; the code beside them is the source's own controller field
            ctl = spec["controller"]
            words = td.find(None, data_ctl_words=True)
            assert words is not None and shown(words) == render(ctl["words"], data), at
            code = td.find("code", data_label_id=ctl["label"])
            assert code is not None and code.text() == labels[ctl["label"]]["text"], at
            evidence = [labels[ctl["label"]]["text"], *(labels[e]["text"] for e in ctl.get("evidence", ()))]
            if any(INTEGRATOR.search(text) for text in evidence):  # WHY: the real arms run PD + feed-forward only (Zach, 2026-11-13)
                assert where == "pseudo-real" and INTEGRATOR.search(ctl["words"]), (at, "an integral term on a real row, or unnamed")
        elif rid in ROWS:
            raise AssertionError(f"{at}: a measured cell names the controller it ran")
    assert status_seen == STATUS_CELLS, (status_seen, STATUS_CELLS)


def test_every_stop_number_carries_its_gate_verdict(home, data):
    main = home.find("main")
    for chip in main.find_all(None, data_gate=True):
        vid = chip.attrs.get("data-gate-value")
        assert vid in data["values"], vid
        verdict = gate_verdict(data, vid)
        assert chip.attrs["data-gate"] == verdict and chip.text() == GATE_WORDS[verdict], (vid, verdict, chip.text())
    for span in main.find_all(None, data_value=True):
        vid = span.attrs["data-value-id"]
        if MEASURES[data["values"][vid]["measure"]] != "stop":
            continue
        box = span.parent
        while box is not None and box.tag not in ("td", "th", "li", "p", "dd", "figcaption"):
            box = box.parent
        assert box is not None, f"{vid}: a stop number outside any cell, note or line"
        here = {s.attrs["data-value-id"] for s in box.find_all(None, data_value=True)}
        judged = {c.attrs.get("data-gate-value") for c in box.find_all(None, data_gate=True)}
        assert here & judged, f"{vid}: a stop number with no gate verdict beside it"


def test_the_row_notes_are_the_exported_notes(home, data):
    for kind, rows in (("proof", proof_rows(data)), ("recovery", data["recovery"])):
        notes = home.find("main").find("ul", data_notes=kind)
        assert notes is not None, kind
        for row in rows:
            got = [shown(li) for li in notes.find_all("li", data_note_for=row["id"])]
            assert got == [render(note, data) for note in row.get("notes", [])], row["id"]


def test_every_number_on_the_page_is_formatted_from_its_value_and_names_its_file(home, data):
    values, sources = data["values"], data["sources"]
    main = home.find("main")
    on_page = set()
    for span in main.find_all(None, data_value=True):
        vid = span.attrs.get("data-value-id")
        assert vid in values, vid
        on_page.add(vid)
        v = values[vid]
        assert re.fullmatch(r"-?\d+(\.\d+)?(e[+-]?\d+)?", span.attrs["data-value"]), span.attrs["data-value"]
        assert float(span.attrs["data-value"]) == pytest.approx(v["value"] * v["scale"], rel=1e-9, abs=1e-12), vid
        assert span.attrs.get("data-unit") == v["display_unit"] and span.attrs.get("data-source") == v["source"], vid
        assert shown(span) == fmt(v), (vid, shown(span), fmt(v))  # WHY (review G3): the digits read are the digits exported
        link = span.find("a")
        assert link is not None and "src" in link.classes() and link.attrs.get("href") == f"#src-{v['source']}", vid
    assert used_value_ids(data) <= on_page, sorted(used_value_ids(data) - on_page)
    listed = section(home, "sources")
    for sid in {values[vid]["source"] for vid in on_page} | {label["source"] for label in data["labels"].values()}:
        item = listed.find("li", id=f"src-{sid}")
        assert item is not None and item.attrs.get("data-source-id") == sid and item.attrs.get("data-sha256") == sources[sid]["sha256"], sid
        text = item.text()
        assert sources[sid]["shown"] in text and sources[sid]["sha256"][:12] in text and sources[sid]["dated"][:10] in text, sid
        if sources[sid]["in_repo"]:
            want = f"{GITHUB}/blob/{sources[sid]['commit']}/{sources[sid]['path']}"
            assert want in {a.attrs.get("href") for a in item.find_all("a")}, sid
    for item in listed.find_all("li", data_source_id=True):
        assert item.attrs["data-source-id"] in sources or item.attrs["data-source-id"] == "registry", item.attrs["data-source-id"]


def test_prose_carries_no_typed_number_no_comparative_no_radian_no_placeholder(home, data):
    """WHY (review G1, U1): a digit a reader sees is a sourced value, a registry count, a date stamped from its source, or a name; the
    comparatives that once contradicted the data (review A7) are only ever computed ({cmp:a:b}, data-compare)."""
    main = home.find("main")
    text = prose(main)
    assert not loose_numbers(text), loose_numbers(text)[:10]
    for bad, pattern in (("comparative", COMPARATIVE), ("radian", RADIANS), ("placeholder", PLACEHOLDER), ("serial", SERIAL)):
        hit = pattern.search(norm(text_skipping(main, lambda n: exempt(n) or "data-compare" in n.attrs, " ")))
        assert hit is None, (bad, hit.group(0) if hit else "")
    for span in main.find_all(None, data_compare=True):
        assert span.text() == compare(data, span.attrs["data-a"], span.attrs["data-b"]), span.attrs
    for code in main.find_all("code"):
        if code.inside("pre") or "data-label-id" in code.attrs or "data-commit" in code.attrs or "data-call" in code.attrs:
            continue
        assert not loose_numbers(code.text()), code.text()
    for code in main.find_all("code", data_label_id=True):
        assert code.text() == data["labels"][code.attrs["data-label-id"]]["text"], code.attrs["data-label-id"]
    for node in main.find_all("time", data_source_date=True):
        src = data["sources"][node.attrs["data-source-date"]]
        assert node.text() == src["dated"][:10] and node.attrs.get("datetime") == src["dated"], node.attrs
    for node in main.find_all(None, data_mode_n=True):
        assert node.text() == node.attrs["data-mode-n"], node.attrs
    for svg in main.find_all("svg"):
        assert not loose_numbers(svg.text()), svg.text()


# --- modes, with the hidden-truth table ------------------------------------------------------------------------------------------------------


def _called(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _name(call: ast.Call) -> str | None:
    return getattr(call.func, "attr", None) or getattr(call.func, "id", None)


def check_calls(source: str, where: str) -> None:
    """Every RobotTwin method a shown block calls takes the keywords it is given, with values the API accepts (review G10)."""
    from sim2real.twin import RobotTwin  # noqa: PLC0415

    for call in _called(ast.parse(source)):
        name = _name(call)
        if name not in TWIN_METHODS:
            continue
        params = inspect.signature(getattr(RobotTwin, name)).parameters
        for kw in call.keywords:
            assert kw.arg in params, (where, name, kw.arg)
            if (name, kw.arg) == ("from_robot_description", "world"):
                assert ast.literal_eval(kw.value) in (None, "nominal"), where
            if (name, kw.arg) == ("calibrate", "on"):
                assert ast.literal_eval(kw.value) in ("sim", "real"), where


def test_the_three_modes_show_a_one_line_call_or_say_none_exists(home, data):
    modes = section(home, "modes")
    assert [n.attrs["data-mode"] for n in modes.find_all(None, data_mode=True)] == ["1", "2", "3"]
    assert [m["n"] for m in data["modes"]] == [1, 2, 3]
    factories = {n.name for n in ast.parse((REPO / "src" / "sim2real" / "examples.py").read_text(encoding="utf-8")).body
                 if isinstance(n, ast.FunctionDef)}
    move = read_source(REPO / "tests" / "test_from_robot_description_nominal.py", ["PENDULUM_MOVE"])
    for mode in data["modes"]:
        block = modes.find(None, data_mode=str(mode["n"]))
        assert shown(block.find(None, data_mode_title=True)) == render(mode["title"], data), mode["n"]
        assert shown(block.find(None, data_mode_what=True)) == render(mode["what"], data), mode["n"]
        statuses = {robot: spec["status"] for robot, spec in mode["robots"].items()}
        assert statuses == MODE_STATUS[mode["n"]], (mode["n"], statuses)
        code = block.find("pre", data_code=f"mode-{mode['n']}")
        if mode["call"] is None:  # WHY (review B7): no snippet that quietly runs a half-hour calibration in place of the missing verb
            assert code is None and set(statuses.values()) == {"not_built"}, mode["n"]
        else:
            source = code.raw_text().strip()
            assert source == mode["call"].strip() and "\n" not in source, mode["n"]
            compile(source, f"mode-{mode['n']}", "exec")
            check_calls(source, f"mode-{mode['n']}")
            for call in _called(ast.parse(source)):
                if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Attribute) and \
                        call.func.value.attr == "examples":
                    assert call.func.attr in factories, call.func.attr
        shown_robots = {li.attrs["data-robot"]: li for li in block.find_all("li", data_robot=True)}
        assert set(shown_robots) == set(ROBOTS), mode["n"]
        for robot, li in shown_robots.items():
            spec = mode["robots"][robot]
            assert li.attrs.get("data-status") == spec["status"] and STATUS_WORDS[spec["status"]] in li.text(), (mode["n"], robot)
            assert shown(li.find(None, data_why=True)) == render(spec["why"], data), (mode["n"], robot)
    calls = {m["n"]: m["call"] for m in data["modes"]}
    assert 'calibrate(on="sim")' in calls[2]
    moves = [kw.value for call in _called(ast.parse(calls[3])) if _name(call) == "calibrate" for kw in call.keywords
             if kw.arg == "move_truth"]
    assert len(moves) == 1 and ast.literal_eval(moves[0]) == move, "mode 3 moves the truth the nominal-world test moves"


def test_the_hidden_truth_table_covers_the_three_robots_and_says_when_it_was_recorded(home, data):
    table = section(home, "modes").find("table", data_table="recovery-proof")
    assert table is not None
    assert {r["id"]: r["robot"] for r in data["recovery"]} == RECOVERY_ROWS
    trs = {tr.attrs["data-row"]: tr for tr in table.find("tbody").find_all("tr") if "data-row" in tr.attrs}
    assert set(trs) == set(RECOVERY_ROWS)
    for row in data["recovery"]:
        tr = trs[row["id"]]
        assert tr.attrs.get("data-robot") == row["robot"], row["id"]
        assert [td.attrs["data-cell"] for td in tr.find_all("td", data_cell=True)] == list(RECOVERY_CELLS), row["id"]
        th = tr.find("th", data_cell="robot")
        assert shown(th.find(None, data_title=True)) == render(row["title"], data), row["id"]
        assert shown(th.find(None, data_measure=True)) == render(row["measure"], data), row["id"]  # WHY (review C14)
        call = th.find("code", data_call=True)
        assert (call is None) == (row["via"] is None) and (call is None or call.text() == row["via"]), row["id"]
        rec = row["recorded"]
        if rec is None:
            continue
        src = data["sources"][rec["source"]]
        stamp = th.find("time", data_source_date=rec["source"])
        assert stamp is not None and stamp.text() == src["dated"][:10], row["id"]  # WHY (review A12): the record's own date
        if src["in_repo"]:
            commit = th.find("code", data_commit=rec["source"])
            assert commit is not None and commit.text() == src["commit"][:7], row["id"]
        if rec.get("routines"):
            routines = th.find("code", data_label_id=rec["routines"])
            assert routines is not None and routines.text() == data["labels"][rec["routines"]]["text"], row["id"]


# --- how it works, the API --------------------------------------------------------------------------------------------------------------------


def test_how_it_works_is_the_seam_with_the_tune_step_switched_from_the_registry(home):
    how = section(home, "how")
    svg = how.find("svg")
    assert svg is not None
    steps = {n.attrs["data-step"]: n for n in svg.find_all(None, data_step=True)}
    assert set(steps) == set(SEAM_STEPS), sorted(steps)
    for name, node in steps.items():
        assert node.find("a") is not None and node.find("a").attrs.get("href"), name
    # WHY (review B9): the tune step Zach approved (dashed amber, "on claude/l10-c") is solid once pid.pidtuna is a tune routine on main
    tune = {r.id: r for r in cat().ROUTINES}["pid.pidtuna"]
    want = "main" if tune.kind == "tune" else "branch"
    assert steps["tune"].attrs.get("data-status") == want and (want == "main" or "on a branch" in steps["tune"].text())
    assert steps["deployed"].attrs.get("data-status") == "designed"


def test_the_api_block_is_real_calls_with_real_arguments(home):
    import sim2real.calibration as cal  # noqa: PLC0415
    from sim2real.calibration.config import SETTINGS  # noqa: PLC0415

    api = section(home, "api")
    block = api.find("pre", data_code="api")
    assert block is not None
    source = block.raw_text()
    for needle in ("RobotTwin.from_robot_description(", ".generate_schedule(", ".calibrate(", ".evaluate()", "CalibrationConfig(",
                   "Budget(", "equipment=", "settings=", "callbacks=", ".data_", 'if __name__ == "__main__":'):
        assert needle in source, needle
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "sim2real.calibration":
            assert all(alias.name in cal.__all__ for alias in node.names), [a.name for a in node.names]
    check_calls(source, "api")
    budget_fields = {f.name for f in dataclasses.fields(cal.Budget)}
    config_fields = {f.name for f in dataclasses.fields(cal.CalibrationConfig)}
    for call in _called(tree):
        name = _name(call)
        if name == "Budget":
            for kw in call.keywords:
                assert kw.arg in budget_fields, kw.arg
                if kw.arg == "equipment":
                    assert set(ast.literal_eval(kw.value)) <= set(cat().EQUIPMENT), ast.literal_eval(kw.value)
                if kw.arg == "settings":
                    assert set(ast.literal_eval(kw.value)) <= set(SETTINGS), ast.literal_eval(kw.value)
        if name == "CalibrationConfig":
            assert all(kw.arg in config_fields for kw in call.keywords), [kw.arg for kw in call.keywords]
    for pre in home.find("main").find_all("pre", data_code=True):
        compile(pre.raw_text(), pre.attrs["data-code"], "exec")
    assert "/examples/pendulum_can11/" in {a.attrs.get("href") for a in api.find_all("a")}


@pytest.mark.skipif(os.environ.get("SIM2REAL_LANDING_CALLS") != "1",
                    reason="builds twins from bam_rack_twin's description: run on a cloud VM in bam_rack_twin's venv (recipe 1)")
def test_the_shown_calls_build_their_twins_and_plan_without_dropping_a_step(home):
    from bam_rack_twin.description import station_description  # noqa: PLC0415

    import sim2real.examples  # noqa: PLC0415
    from sim2real.calibration import Budget, CalibrationConfig  # noqa: PLC0415
    from sim2real.twin import RobotTwin  # noqa: PLC0415

    source = section(home, "api").find("pre", data_code="api").raw_text()
    config_call = next(c for c in _called(ast.parse(source)) if _name(c) == "CalibrationConfig")
    config = eval(ast.unparse(config_call), {"CalibrationConfig": CalibrationConfig, "Budget": Budget})  # noqa: S307 - the page's own literal
    schedule = RobotTwin.from_robot_description(station_description(11), workers=1).generate_schedule(config)
    assert not schedule.dropped, schedule.dropped  # WHY (review E): the page says this budget keeps the whole pendulum schedule
    RobotTwin.from_robot_description(station_description(11), world="nominal", workers=1).generate_schedule()
    sim2real.examples.pendulum_can11(workers=1)


# --- bench and deployed ----------------------------------------------------------------------------------------------------------------------


def test_bench_and_deployed_counts_come_from_the_registry(home):
    life = section(home, "lifecycle")
    for setting in ("bench", "deployed", "both"):
        node = life.find(None, data_setting_count=setting)
        assert node is not None and node.text() == str(sum(r.setting == setting for r in cat().ROUTINES)), setting


def test_the_lifecycle_is_marked_designed_and_its_lists_are_the_exported_ones(site, home, data):
    import sim2real.calibration as cal  # noqa: PLC0415
    from sim2real.twin import RobotTwin  # noqa: PLC0415

    life = section(home, "lifecycle")
    assert life.find(None, id="deployed") is not None
    assert life.find(None, data_status="designed") is not None and "designed, not built" in life.text()
    loop = life.find(None, data_loop=True)
    assert loop is not None and all(word in loop.text().lower() for word in ("monitor", "trigger", "challenger", "keep"))
    today = life.find_all("li", data_today_item=True)
    assert [shown(li) for li in today] == [render(item["text"], data) for item in data["lifecycle"]["today"]]
    by_id = {r.id: r for r in cat().ROUTINES}
    linked = set()
    for li, item in zip(today, data["lifecycle"]["today"]):
        if item.get("href"):
            assert item["href"] in {a.attrs.get("href") for a in li.find_all("a")}, item["href"]
            match = re.fullmatch(r"/routines/([^/]+)/", item["href"])
            if match:
                linked.add(match.group(1))
    assert len(linked) >= 2 and all(by_id[rid].setting in ("deployed", "both") for rid in linked), linked
    missing = {item["name"]: item for item in data["lifecycle"]["not_built"]}
    for name in LIFETIME_NAMES:
        if not (hasattr(RobotTwin, name) or hasattr(cal, name)):
            li = life.find("li", data_not_built=name)
            assert name in missing and li is not None and shown(li) == render(missing[name]["text"], data), name
    assert "/docs/deployed/" in {a.attrs.get("href") for a in life.find_all("a")}
    doc = parse(site["out"] / "docs" / "deployed" / "index.html")
    sketch = "".join(pre.raw_text() for pre in doc.find_all("pre"))
    for name in LIFETIME_NAMES:  # WHY (review C12): the sketch of calls that do not exist lives on the design page, not the landing
        assert re.search(rf"\b{name}\(", sketch), name
    assert "designed, not built" in doc.find("main").text() and len(doc.find_all("h1")) == 1
    assert not life.find_all("pre"), "the landing keeps the loop and the two lists; the code sketch is /docs/deployed/'s"


# --- media, promises, sources ----------------------------------------------------------------------------------------------------------------


def test_the_media_are_real_frame_checked_files_beside_the_page(site, home, data):
    main = home.find("main")
    figures = main.find_all("figure", data_media=True)
    assert figures
    used = {f.attrs["data-media"] for f in figures}
    assert used == set(data["media"]), (used, set(data["media"]))
    for figure in figures:
        mid = figure.attrs["data-media"]
        media = data["media"][mid]
        assert media["kind"] == "real" and media["file"].startswith("media/") and media["file"].endswith(MEDIA_EXT), mid
        img = figure.find("img")
        assert img is not None and img.attrs.get("src") == f"/assets/{media['file']}" and img.attrs.get("alt", "").strip(), mid
        built = site["out"] / "assets" / media["file"]
        assert built.is_file() and sha(built.read_bytes()) == media["sha256"], mid
        assert built.stat().st_size <= 1_000_000, mid
        caption = figure.find("figcaption")
        assert caption is not None and render(media["what"], data) in shown(caption), mid
        assert f"#media-{mid}" in {a.attrs.get("href") for a in caption.find_all("a")}, mid
        # WHY (review B8): frames are looked at before anything goes public; the ruler cannot see pixels, so it pins the record
        check = media["frames_checked"]
        assert check["frames"] >= 1 and check["by"].strip() and check["utc"], mid
        assert check["people"] is False and check["serials"] is False and check["burned_text"] is False, mid
        item = section(home, "sources").find("li", id=f"media-{mid}")
        assert item is not None and item.attrs.get("data-media-id") == mid and media["sha256"][:12] in item.text(), mid
        assert media["shown"] in item.text(), mid
    assert sum((site["out"] / "assets" / m["file"]).stat().st_size for m in data["media"].values()) <= 2_000_000


def test_the_promises_are_three_and_say_no_number(home):
    promises = section(home, "promises")
    assert len(promises.find_all(None, data_promise=True)) == 3
    assert {"/routines/", "/api/", "/docs/deployed/"} <= {a.attrs.get("href") for a in promises.find_all("a")}
    assert not loose_numbers(prose(promises))
