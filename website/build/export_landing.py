"""Export the landing page's numbers: website/build/landing_picks.py -> website/data/landing.json (every number read out of its file).

    env -u VIRTUAL_ENV nice -n 19 ionice -c3 taskset -c 2-5,16,17 /home/bam/sim2real/.venv/bin/python /home/bam/sim2real/website/build/export_landing.py --snapshot

- `--snapshot`  copy every source outside the repo byte for byte to /archive/datasets/sim2real_landing/<SNAPSHOT_DATE>/<sid>.<ext>;
                a snapshot is written once and never rewritten (a file whose bytes moved since is refused, not overwritten)
- (default)     write website/data/landing.json from PICKS: lab numbers from the snapshots, repo numbers from their committed files;
                print one line per number (id, as shown, source, key)
- `--media --sheets DIR`  cut the page's stills and loop from the real recordings with ffmpeg into website/site/media/ (one thread,
                under a 1 GB memory scope, on CPUs 2-5,16,17) and write one-frame-per-second contact sheets into DIR to look at
- `--frames-checked-by WHO`  after WHO looked at every contact sheet: record the frame check (no people, no serials, no burned-in text)
- `--check`     re-read landing.json with tests/test_landing_page.py's own recheck() (the exporter never grades its own numbers) and
                list the live files that moved since their snapshot (informational)

Standard library only; it never imports sim2real. It refuses: a missing, None, NaN or non-numeric number (a missing number is a Status in
PICKS), a display unit in rad or mrad, a digit in any template's prose, a serial-looking token, an absolute path in the output, and an
integral term on a real row.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import datetime as dt
import hashlib
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEBSITE = HERE.parent
REPO = WEBSITE.parent
sys.path.insert(0, str(HERE))

import landing_picks as P  # noqa: E402

OUT = WEBSITE / "data" / "landing.json"
SITE = WEBSITE / "site"
SNAPSHOTS = Path("/archive/datasets/sim2real_landing")
SCHEMA = "sim2real.landing/1"

CONVERSIONS = {("m", "mm"): 1e3, ("mrad", "°"): 180.0 / math.pi / 1e3, ("rad", "°"): 180.0 / math.pi, ("deg", "°"): 1.0,
               ("rad/s", "°/s"): 180.0 / math.pi, ("x floor", "× floor"): 1.0, ("fraction", "%"): 100.0, ("x", "×"): 1.0,
               ("N.m", "N·m"): 1.0}
KPI_DISPLAY = {"mm": "mm", "deg": "°"}
FORMATS = {"mm": "{n} mm", "°": "{n}°", "°/s": "{n}°/s", "× floor": "{n} × floor", "h": "{n} h", "": "{n}", "%": "{n}%",
           "×": "×{n}", "N·m": "{n} N·m"}
MEASURE_CLASS = {"stop_worst": "stop", "stop_median": "stop", "stop_task_worst_median": "stop", "gate_pass_rate": "rate",
                 "tcp_rms": "tracking", "joint_rms": "tracking", "stops": "count", "within_gate": "count", "tasks": "count",
                 "recovered": "count", "graded": "count", "not_identified": "count", "held_out_ratio": "fidelity",
                 "held_out_tool": "fidelity", "held_out_flange": "fidelity", "fidelity_joint": "fidelity", "floor": "fidelity",
                 "peak_speed": "target", "amplitude": "target", "speed_fraction": "target", "gain_scale": "setting",
                 "feedforward": "setting", "hours": "hours", "gate": "gate"}
PLACE = re.compile(r"\{(=[^{}]+|gate:[a-z0-9_.-]+|cmp:[a-z0-9_.-]+:[a-z0-9_.-]+|[a-z0-9][a-z0-9_.-]*)\}")
TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*")
NAME_SPAN = re.compile(r"CAN \d{1,2}|\d-DOF")
SERIAL = re.compile(r"\b(?=[0-9A-F]*[A-F])(?=[0-9A-F]*[0-9])[0-9A-F]{8}\b|(?<![\d.])\d{10,}(?![\d.])")
ABSOLUTE = re.compile(r'"(?:/home/|/archive/|/tmp/|/root/|~/)')
INTEGRATOR = re.compile(r"\bintegra(?:l|tor)s?\b", re.I)
LIMITS = ["nice", "-n", "19", "ionice", "-c3", "taskset", "-c", "2-5,16,17"]
SCOPE = ["systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=1G", "--"]


class Refused(Exception):
    pass


# ------------------------------------------------------------------------------------------------------------- reading files


def local(ref: str) -> Path:
    """A logical name on this workstation ('lab:x' -> its root / x); a bare path is sim2real-relative."""
    root, sep, rest = ref.partition(":")
    if sep and root in P.ROOTS:
        return Path(P.ROOTS[root]) / rest
    return REPO / ref


def in_repo(src: P.Source) -> bool:
    return ":" not in src.ref


def shown_name(ref: str) -> str:
    root, sep, rest = ref.partition(":")
    return f"{P.ROOT_WORDS[root]}: {rest}" if sep and root in P.ROOTS else f"sim2real: {ref}"


def snapshot_of(src: P.Source) -> Path:
    return SNAPSHOTS / P.SNAPSHOT_DATE / f"{src.sid}{Path(src.ref).suffix}"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def read_bytes(src: P.Source) -> bytes:
    if in_repo(src):
        if git("status", "--porcelain", "--", src.ref):
            raise Refused(f"{src.sid}: {src.ref} has uncommitted changes; commit it first (the page cites a commit)")
        return (REPO / src.ref).read_bytes()
    snap = snapshot_of(src)
    if not snap.is_file():
        raise Refused(f"{src.sid}: no snapshot at {snap}; run --snapshot first")
    return snap.read_bytes()


def parse(src: P.Source, data: bytes):
    return data.decode("utf-8") if src.ref.endswith(".py") else json.loads(data)


def resolve(doc, key):
    node = doc
    for step in key:
        if isinstance(step, dict) and "where" in step:
            hits = [i for i in node if isinstance(i, dict) and all(_same(i.get(k), v) for k, v in step["where"].items())]
            if len(hits) != 1:
                raise Refused(f"{step} matches {len(hits)} items, not one")
            node = hits[0]
        elif isinstance(step, dict) and "newest" in step:
            rule = step["newest"]
            hits = [i for i in node if isinstance(i, dict) and all(_same(i.get(k), v) for k, v in rule.get("where", {}).items())
                    and all(str(i.get(f, "")).startswith(p) for f, p in rule.get("startswith", {}).items())
                    and not any(w.lower() in str(i.get(f, "")).lower() for f, ws in rule.get("excludes", {}).items() for w in ws)]
            if not hits:
                raise Refused(f"{step} matches nothing")
            node = max(hits, key=lambda i: str(i[rule["by"]]))
        else:
            node = node[step]
    return node


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def read_key(src: P.Source, doc, key):
    if src.ref.endswith(".py"):  # a module-level literal, read without importing the module
        name, *rest = key
        for node in ast.parse(doc).body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return resolve(ast.literal_eval(node.value), rest)
        raise Refused(f"{src.sid}: no module-level {name}")
    return resolve(doc, key)


def apply(raw, rule):
    if rule is None:
        return raw
    if "size" in rule:
        return len(raw)
    if "count" in rule:
        spec = rule["count"]
        items = list(raw.values()) if isinstance(raw, dict) else list(raw)
        if "equals" in spec:
            return sum(1 for i in items if _same(i.get(spec["field"]), spec["equals"]))
        return sum(1 for i in items if (i.get(spec["field"]) is not None) == spec["present"])
    if "basename" in rule:
        return str(raw).rstrip("/").rsplit("/", 1)[-1]
    if "pluck" in rule:
        return ", ".join(str(i[rule["pluck"]]) for i in raw)
    raise Refused(f"unknown derive {rule}")


def kpi_of(text: str, name: str) -> tuple[str, str, float]:
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "K" and node.args and \
                isinstance(node.args[0], ast.Constant) and node.args[0].value == name:
            return tuple(ast.literal_eval(a) for a in node.args[2:5])
    raise Refused(f"kpi_names has no K({name!r}, ...)")


# ------------------------------------------------------------------------------------------------------------- prose rules


def prose_of(template: str) -> str:
    return " ".join(re.sub(r"`[^`]*`", " ", PLACE.sub(" ", template)).split())


def check_template(where: str, template: str, value_ids: set[str]) -> None:
    loose = [t for t in TOKEN.findall(prose_of(template)) if t[0].isdigit() or re.match(r"[xX]\d", t)]
    if loose:
        raise Refused(f"{where}: a typed number in prose {loose} (a number is a {{value-id}}): {template!r}")
    if SERIAL.search(template):
        raise Refused(f"{where}: a serial-looking token {SERIAL.search(template).group(0)!r}")
    for body in PLACE.findall(template):
        if body.startswith("="):
            if not (NAME_SPAN.fullmatch(body[1:]) or not re.search(r"\b\d", body[1:])):
                raise Refused(f"{where}: name {body!r} is neither CAN n nor n-DOF")
            continue
        ids = body.split(":")[1:] if body.startswith(("gate:", "cmp:")) else [body]
        for vid in ids:
            if vid not in value_ids:
                raise Refused(f"{where}: {{{body}}} names no value")
    if re.search(r"\b(m?rad(?:/s)?|degs?)\b", prose_of(template)):
        raise Refused(f"{where}: radians or 'deg' in prose: {template!r}")


def templates():
    h = P.HERO
    yield "hero", h["eyebrow"]
    yield "hero", h["h1"]
    yield "hero", h["lead"]
    yield "hero", h["today"]
    for line in h["lines"]:
        yield "hero", line
    for key, _title, definition in P.METRICS:
        yield f"metric {key}", definition
    for robot in P.ROBOTS:
        yield robot.id, robot.title
        for row in robot.rows:
            for t in (row.title, row.target, *row.notes):
                yield row.id, t
            for name, cell in row.cells.items():
                yield f"{row.id}.{name}", cell.words if isinstance(cell, P.Cell) else cell.why
    for row in P.RECOVERY:
        for t in (row.title, row.measure, *row.notes):
            yield row.id, t
        for name, cell in row.cells.items():
            if isinstance(cell, P.Status):
                yield f"{row.id}.{name}", cell.why
    for mode in P.MODES:
        yield f"mode {mode.n}", mode.title
        yield f"mode {mode.n}", mode.what
        for robot, st in mode.robots.items():
            yield f"mode {mode.n}.{robot}", st.why
    yield "lifecycle", P.LIFECYCLE["lead"]
    for _href, text in P.LIFECYCLE["today"]:
        yield "lifecycle", text
    for _name, text in P.LIFECYCLE["not_built"]:
        yield "lifecycle", text
    for m in P.MEDIA:
        yield f"media {m.mid}", m.what


# ------------------------------------------------------------------------------------------------------------- snapshot


def snapshot() -> None:
    for src in P.SOURCES:
        if in_repo(src):
            continue
        live, snap = local(src.ref), snapshot_of(src)
        data = live.read_bytes()
        if snap.is_file():
            if sha(snap.read_bytes()) == sha(data):
                print(f"kept   {snap}")
                continue
            print(f"MOVED  {src.sid}: {live} changed since its snapshot {snap}; the snapshot stays (the page cites it)")
            continue
        snap.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, snap)   # WHY copy2: the copy keeps the file's own mtime, its date when nothing inside dates it
        if sha(snap.read_bytes()) != sha(data):
            raise Refused(f"{src.sid}: the copy at {snap} is not byte for byte {live}")
        print(f"wrote  {snap}")


# ------------------------------------------------------------------------------------------------------------- media


def _ffmpeg(*args: str) -> None:
    cmd = [*SCOPE, *LIMITS, "ffmpeg", "-hide_banner", "-v", "error", "-threads", "1", "-filter_threads", "1", "-y", *args]
    subprocess.run(cmd, check=True)


def _duration(path: Path) -> float:
    out = subprocess.run([*LIMITS, "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def _frame_time(m: P.Media, source: Path) -> float:
    return m.at_s if m.at_s is not None else round(_duration(source) / 2.0, 3)


def cut_media(sheets: Path) -> None:
    """The page's media from the real recordings, plus one contact sheet per file to look at before anything is published."""
    sheets.mkdir(parents=True, exist_ok=True)
    (SITE / "media").mkdir(parents=True, exist_ok=True)
    for m in P.MEDIA:
        source, target = local(m.ref), SITE / m.file
        if m.how == "copy":
            shutil.copyfile(source, target)
            shutil.copyfile(source, sheets / f"{m.mid}.jpg")
        elif m.how == "frame":
            at = _frame_time(m, source)
            _ffmpeg("-ss", f"{at}", "-i", str(source), "-frames:v", "1", "-vf", m.filter, "-q:v", str(m.quality), str(target))
            _ffmpeg("-ss", f"{at}", "-i", str(source), "-frames:v", "1", "-vf", m.filter, str(sheets / f"{m.mid}.png"))
        elif m.how == "loop":
            _ffmpeg("-i", str(source), "-an", "-vf", m.filter, "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", str(m.quality),
                    "-compression_level", "6", "-loop", "0", str(target))
            # one frame per second of what the loop shows, tiled: every second of the clip is looked at
            _ffmpeg("-i", str(source), "-an", "-vf", f"{m.filter},fps=1,tile=2x5:padding=4", "-frames:v", "1",
                    str(sheets / f"{m.mid}.png"))
        print(f"media  {m.mid}: {target.relative_to(REPO)} {target.stat().st_size / 1024:.0f} KiB; sheet in {sheets}")


def frames_in(m: P.Media) -> int:
    if m.how != "loop":
        return 1
    start, end = re.search(r"trim=([\d.]+):([\d.]+)", m.filter).groups()
    return int(round(float(end) - float(start)))


# ------------------------------------------------------------------------------------------------------------- the export


def export(*, frames_checked_by: str | None) -> dict:
    sources, cache, problems = {}, {}, []
    by_sid = {s.sid: s for s in P.SOURCES}
    for src in P.SOURCES:
        data = read_bytes(src)
        doc = parse(src, data)
        cache[src.sid] = doc
        entry = {"in_repo": in_repo(src)}
        if in_repo(src):
            entry["path"] = src.ref
            entry["commit"] = git("log", "-1", "--format=%H", "--", src.ref)
        else:
            entry["from"] = src.ref
            entry["snapshot"] = f"snap:{P.SNAPSHOT_DATE}/{snapshot_of(src).name}"
        entry |= {"shown": shown_name(src.ref), "what": src.what, "kind": src.kind}
        if src.kind_by_key:
            entry["kind_by_key"] = dict(src.kind_by_key)
        if src.unit_convention:
            entry["unit_convention"] = src.unit_convention
        entry |= {"moving": src.moving, "sha256": sha(data), "bytes": len(data)}
        if src.dated_key:
            entry |= {"dated": str(resolve(doc, list(src.dated_key))), "dated_from": "key", "dated_key": list(src.dated_key)}
        elif in_repo(src):
            entry |= {"dated": git("log", "-1", "--format=%cI", "--", src.ref), "dated_from": "commit"}
        else:
            mtime = snapshot_of(src).stat().st_mtime
            # WHY local time with its offset: the date a reader sees is the workstation's day, like the commits' and the recorders' stamps
            entry |= {"dated": dt.datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds"), "dated_from": "mtime"}
        sources[src.sid] = entry

    kpi_text = cache["amb-kpi-names"]
    values = {}
    for v in P.VALUES:
        src = by_sid[v.source]
        raw = apply(read_key(src, cache[v.source], list(v.key)), v.derive)
        if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise Refused(f"{v.vid}: {raw!r} is not a number (a missing number is a Status in PICKS)")
        if v.display_unit in ("rad", "mrad", "rad/s") or v.display_unit not in FORMATS:
            raise Refused(f"{v.vid}: display unit {v.display_unit!r} (angles show in degrees)")
        if v.kpi:
            unit, display, kscale = kpi_of(kpi_text, v.kpi)
            want_unit = unit if src.unit_convention == "si" else display
            scale = kscale if src.unit_convention == "si" else CONVERSIONS.get((display, KPI_DISPLAY[display]), 1.0)
            if v.unit != want_unit or v.display_unit != KPI_DISPLAY[display]:
                raise Refused(f"{v.vid}: kpi_names says {want_unit} shown as {KPI_DISPLAY[display]}, PICKS {v.unit} as {v.display_unit}")
        elif v.unit == v.display_unit:
            scale = 1
        else:
            scale = CONVERSIONS[(v.unit, v.display_unit)]
        cls = MEASURE_CLASS[v.measure]
        if cls in ("target", "setting"):
            kind = cls
        elif src.kind == "mixed":
            steps = [s for s in v.key if isinstance(s, str) and s in src.kind_by_key]
            kind = src.kind_by_key[steps[0]] if steps else v.kind
            if kind is None:
                raise Refused(f"{v.vid}: a mixed source's value with no real/sim step must declare its kind")
        else:
            kind = src.kind
        entry = {"source": v.source, "key": list(v.key), "derive": v.derive, "value": raw, "unit": v.unit, "display_unit": v.display_unit,
                 "scale": scale, "digits": v.digits, "measure": v.measure, "kind": kind}
        if v.kpi:
            entry["kpi"] = {"source": "amb-kpi-names", "name": v.kpi}
        values[v.vid] = entry

    labels = {}
    for lab in P.LABELS:
        src = by_sid[lab.source]
        text = apply(read_key(src, cache[lab.source], list(lab.key)), lab.derive)
        labels[lab.lid] = {"source": lab.source, "key": list(lab.key), "derive": lab.derive, "text": str(text)}

    for where, template in templates():
        check_template(where, template, set(values))

    def cell(c):
        if isinstance(c, P.Status):
            return {"status": c.status, "why": c.why}
        out = {"values": list(c.values)}
        if c.gate:
            out["gate"] = c.gate
        if c.label:
            out["controller"] = {"words": c.words, "label": c.label}
            if c.evidence:
                out["controller"]["evidence"] = list(c.evidence)
        return out

    robots = []
    for robot in P.ROBOTS:
        rows = []
        for row in robot.rows:
            for name, c in row.cells.items():  # WHY: the real arms run PD + feed-forward only (Zach, 2026-11-13)
                if isinstance(c, P.Cell) and c.label:
                    texts = [labels[c.label]["text"], *(labels[e]["text"] for e in c.evidence)]
                    if any(INTEGRATOR.search(t) for t in texts) and (row.where == "real" or not INTEGRATOR.search(c.words)):
                        raise Refused(f"{row.id}.{name}: an integral term on a real row, or one its words do not name")
            entry = {"id": row.id, "where": row.where, "title": row.title, "link": row.link}
            if row.media:
                entry["media"] = row.media
            entry |= {"target": row.target, "cells": {k: cell(c) for k, c in row.cells.items()}, "same": [list(p) for p in row.same],
                      "notes": list(row.notes)}
            rows.append(entry)
        robots.append({"id": robot.id, "title": robot.title, "rows": rows})

    recovery = [{"id": r.id, "robot": r.robot, "title": r.title, "via": r.via, "measure": r.measure,
                 "recorded": None if r.recorded is None else ({"source": r.recorded} | ({"routines": r.routines} if r.routines else {})),
                 "cells": {k: cell(c) for k, c in r.cells.items()}, "notes": list(r.notes)} for r in P.RECOVERY]
    modes = [{"n": m.n, "title": m.title, "what": m.what, "call": m.call,
              "robots": {k: {"status": s.status, "why": s.why} for k, s in m.robots.items()}} for m in P.MODES]

    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    media = {}
    for m in P.MEDIA:
        path = SITE / m.file
        if not path.is_file():
            raise Refused(f"media {m.mid}: {path} is missing; run --media first")
        data = path.read_bytes()
        digest = sha(data)
        checked = (previous.get("media", {}).get(m.mid) or {})
        if checked.get("sha256") == digest and checked.get("frames_checked", {}).get("by"):
            frames = checked["frames_checked"]
        elif frames_checked_by:
            frames = {"frames": frames_in(m), "by": frames_checked_by, "utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "people": False, "serials": False, "burned_text": False}
        else:  # WHY: frames nobody looked at say so; the ruler fails them until someone does
            frames = {"frames": 0, "by": "", "utc": "", "people": None, "serials": None, "burned_text": None}
        media[m.mid] = {"file": m.file, "sha256": digest, "bytes": len(data), "kind": "real", "what": m.what, "from": m.ref,
                        "from_sha256": sha(local(m.ref).read_bytes()), "shown": shown_name(m.ref), "report": m.report,
                        "filter": m.filter or "none (copied)", "frames_checked": frames}

    lifecycle = {"lead": P.LIFECYCLE["lead"], "loop": list(P.LIFECYCLE["loop"]),
                 "today": [({"href": href} if href else {}) | {"text": text} for href, text in P.LIFECYCLE["today"]],
                 "not_built": [{"name": name, "text": text} for name, text in P.LIFECYCLE["not_built"]]}
    out = {
        "schema": SCHEMA,
        "exported_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exporter": "website/build/export_landing.py",
        "sim2real_commit": git("rev-parse", "HEAD"),
        "gate": P.GATE,
        "metrics": {k: {"title": t, "definition": d} for k, t, d in P.METRICS},
        "sources": sources, "values": values, "labels": labels, "media": media,
        "hero": {**P.HERO, "lines": list(P.HERO["lines"])},
        "robots": robots, "recovery": recovery, "modes": modes, "lifecycle": lifecycle,
    }
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if ABSOLUTE.search(text):
        raise Refused(f"an absolute path in the output near {text[ABSOLUTE.search(text).start():][:80]!r}")
    # WHY digests are blanked first: a sha256 or a commit is hex, and ten decimal digits in a row turn up in about one digest in five;
    # the guard is for a device's serial (8 upper-case hex, or a camera's long number), which only prose, labels or keys could carry
    bare = re.sub(r'"(sha256|from_sha256|commit|sim2real_commit)": "[0-9a-f]{40,64}"', r'"\1": ""', text)
    if SERIAL.search(bare):
        raise Refused(f"a serial-looking token in the output: {SERIAL.search(bare).group(0)!r}")
    if "NaN" in text or "Infinity" in text:
        raise Refused("NaN or Infinity in the output")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    for vid, v in values.items():
        shown = FORMATS[v["display_unit"]].format(n=f"{v['value'] * v['scale']:.{v['digits']}f}")
        key = "/".join(json.dumps(s, ensure_ascii=False) if isinstance(s, dict) else str(s) for s in v["key"])
        print(f"{vid:36s} {shown:>14s}  {v['source']:24s} {key}")
    print(f"wrote {OUT.relative_to(REPO)}: {len(values)} numbers, {len(labels)} labels, {len(sources)} sources, {len(media)} media")
    return out


def check() -> int:
    spec = importlib.util.spec_from_file_location("landing_ruler", REPO / "tests" / "test_landing_page.py")
    ruler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ruler)
    data = json.loads(OUT.read_text(encoding="utf-8"))
    problems, counts = ruler.recheck(data)
    for p in problems:
        print(f"PROBLEM {p}")
    for src in P.SOURCES:
        if not in_repo(src) and snapshot_of(src).is_file() and local(src.ref).is_file():
            if sha(local(src.ref).read_bytes()) != data["sources"][src.sid]["sha256"]:
                print(f"moved  {src.sid}: {shown_name(src.ref)} changed since its snapshot (the page cites the snapshot)")
    print(f"recheck: {counts['repo']} repo numbers, {counts['lab']} lab numbers re-read; {len(problems)} problems")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", action="store_true", help="copy lab files to their snapshot folder (once) before exporting")
    ap.add_argument("--media", action="store_true", help="cut the page's media from the real recordings (needs --sheets)")
    ap.add_argument("--sheets", type=Path, help="where --media writes the contact sheets to look at")
    ap.add_argument("--frames-checked-by", help="record that this person/agent looked at every contact sheet: no people, serials or text")
    ap.add_argument("--check", action="store_true", help="re-read landing.json with the ruler's recheck(), then stop")
    args = ap.parse_args(argv)
    try:
        if args.check:
            return check()
        if args.snapshot:
            snapshot()
        if args.media:
            if not args.sheets:
                ap.error("--media needs --sheets DIR")
            cut_media(args.sheets)
        export(frames_checked_by=args.frames_checked_by)
    except Refused as exc:
        print(f"REFUSED {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
