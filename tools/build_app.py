"""The sim2real app's data: deployments -> runs -> one run, every file the pages in app/ read.

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/build_app.py

Zach (2026-10-28): "At the top level we have deployments ... On any given deployment you will have a number of runs ... a
table organized from recent to oldest ... statistics over the coverage of the runs ... make a really great robotic data
visualizer first and THEN afterwards ... the diagnostics layer". So the playback files and the diagnostics files are
separate: the pages draw the first, and the gates layer adds the second on top, computed FROM the same runs by
robotdx.diagnostics (io-diagnostics), never by the pages.

Reads (never writes): app/registry.json, each deployment's record (bam_rack_twin deployment.json), every real run under its
archive days (<name>.npz + <name>.json, recorder bam_rack_twin.hardware), app/data/source/twin_replays.json (the 10-28 CAN
12/13 held-out runs played by four friction models, tools/twin_replays.py) and dashboards/source/rack_replays.json (one
held-out run per station played by its "full" twin, dashboards/source/rack_replays.py). Writes app/data/ (gitignored):

  deployments.json                       one row per deployment, with roll-up KPIs
  <dep>/runs.json                        one row per run, newest first: time, station, kind, duration, gains, situations
  <dep>/coverage.json                    every run on a uniform time grid (w = 1) plus each run's argmin/argmax rows (w = 0)
  <dep>/devices.json                     stations with their proven window (the 1-DOF workspace) and run counts
  <dep>/gates.json, diagnostics.json     the gates layer: the rack's gate matrix and every diagnostic row (PEP 0010 §10)
  <dep>/run_gates.json                   per-run diagnostic rows for every run (the gates layer's run verdicts)
  <dep>/runs/<slug>/samples.json         t x situation rows: real, target and every model, display units
  <dep>/runs/<slug>/poses.json           the output link's orientation in the joint's own frame (explicit frame id)
  <dep>/runs/<slug>/diff_samples.json    difference(a, b): each situation against the target, each model against real
  <dep>/runs/<slug>/diff_poses.json      the same pairs on the output link's pose
  (runs.json, devices.json and every per-run table above are data-ui robotics CONTRACT.md v1 tables, checked against its
  schemas before they are written; tools/trajectory.py computes difference(a, b), pinned to data-ui's fixture)
  <dep>/runs/<slug>/diagnostics.json     that run's diagnostic rows
  <dep>/runs/<slug>/run.json             that run's one runs.json row (the run page's header)
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import math
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from robotdx.diagnostics import Limits, evaluate
from robotdx.diagnostics.data import Trajectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trajectory as traj  # noqa: E402  (sim2real's difference(a, b) and the robotics contract tables; pinned to data-ui's fixture)
from robotdx.diagnostics.rows import result_row
from robotdx.diagnostics.stock import BoxConfig, FaultCodesConfig, ModelErrorConfig, RateConfig, TrackingErrorConfig
from robotdx.diagnostics.stock.health import Stamps

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
DATA = APP / "data"
REGISTRY = APP / "registry.json"
TWIN_REPLAYS = DATA / "source" / "twin_replays.json"
RACK_REPLAYS = REPO / "dashboards" / "source" / "rack_replays.json"
FLOORS_1024 = Path("/archive/datasets/bam_rig/rack_2026-10-24/analysis/floors.json")
TZ = ZoneInfo("America/Vancouver")  # the rack's wall clock; every `started` carries its offset
MAX_DISPLAY_HZ = 100.0  # rack_replays.py's rule: display rows are picked, never averaged
COVER_HZ = 10.0  # the coverage grid; a count is time spent (count / COVER_HZ s)
COVER_BUDGET = 150_000  # PEP 0010 §4.4: a coverage file stays <= 150k rows (Vega-Lite binning measured at ~85 ms there)
FIDELITY_GATE = 1.5  # the ruler: sim-vs-real error <= 1.5x the device's own floor is twinned
# WHY a fixed app path in every link: the data files sit at different depths, and a link relative to each would differ;
# serve.py serves this repo's root, so /app/ is the same everywhere
APP_URL = "/app/"
TARGET = "target"
REAL = "real"
BOARD_TEMP = BoxConfig(channel="temp_c", unit="Cel", max=Limits.at_most(70.0, warn=60.0),
                       mean=Limits(error_low=5.0, warn_low=10.0, warn_high=55.0, error_high=65.0))  # as tools/diagnostics_run_rack.py


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def num(value, digits: int = 5):
    """A finite float rounded to `digits` significant figures, else None (missing is null, never 0)."""

    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    if value == 0:
        return 0.0
    return round(value, max(0, digits - 1 - int(math.floor(math.log10(abs(value))))))


def write(path: Path, title: str, source: str, properties: dict, rows: list[dict], **extra) -> int:
    """A data-ui data file: id, title, source, every column declared (the checker and the menus read `properties`)."""

    columns: dict[str, dict] = {}
    for row in rows:
        for key, value in row.items():
            if key not in columns:
                columns[key] = dict(properties.get(key, {}))
            if "type" not in columns[key] and value is not None:
                columns[key]["type"] = ("checkbox" if isinstance(value, bool) else "number" if isinstance(value, (int, float))
                                        else "list" if isinstance(value, list) else "text")
    for spec in columns.values():
        spec.setdefault("type", "text")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"id": f"sim2real-{path.parent.name}-{path.stem}", "title": title, "source": source, "properties": columns, **extra, "rows": rows}
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return len(rows)


# ---------------------------------------------------------------------------------------------------- the registry


def gains_at(component: dict, wall_utc: dt.datetime | None) -> dict:
    """The board's gains in force when the run started: the newest config_history entry at or before it, else the record's current."""

    history = sorted(component.get("config_history", []), key=lambda h: h.get("since_utc") or "")
    chosen = component.get("moteus_config", {})
    if wall_utc is not None and history:
        stamp = wall_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        earlier = [h for h in history if (h.get("since_utc") or "") <= stamp]
        chosen = earlier[-1]["moteus_config"] if earlier else history[0]["moteus_config"]
    return {key: chosen.get(key) for key in ("kp", "ki", "kd", "ilimit")}


def stations(record: dict) -> dict[str, dict]:
    out = {}
    for component in record.get("components", []):
        if component.get("can_id") is None:
            continue
        out[f"CAN {component['can_id']}"] = component
    return out


# ---------------------------------------------------------------------------------------------------- one real run


def smooth(values: np.ndarray, width: int = 5) -> np.ndarray:
    if values.size < width:
        return values
    kernel = np.ones(width) / width
    padded = np.pad(values, width // 2, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def accel(t: np.ndarray, qd: np.ndarray) -> np.ndarray:
    """qdd from the logged qd: a 5-sample moving mean, then central differences. basis: derived (the board logs no qdd)."""

    if t.size < 3:
        return np.full(t.shape, np.nan)
    good = np.isfinite(qd)
    if good.sum() < 3:
        return np.full(t.shape, np.nan)
    filled = np.interp(t, t[good], qd[good])
    return np.gradient(smooth(filled), t)


def load_run(path: Path) -> dict | None:
    meta_path = path.with_suffix(".json")
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get("can_id") is None:
        return None
    try:
        with np.load(path) as archive:
            files = set(archive.files)
            if not {"t", "q"} <= files:
                return None
            arrays = {name: np.asarray(archive[name], float) for name in files if archive[name].ndim == 1 and archive[name].size == archive["t"].size}
    except Exception:  # a truncated npz: not a run (one camera file on 10-23 is not a zip)
        return None
    if arrays["t"].size < 2:
        return None
    return {"meta": meta, "arrays": arrays}


def trajectory(arrays: dict, *, run: str, device: str, situation: str, source: str, t: np.ndarray | None = None, q=None, qd=None, tau=None) -> Trajectory:
    t = arrays["t"] - arrays["t"][0] if t is None else t
    return Trajectory(t=t, q_rad=arrays["q"] if q is None else q, q_target_rad=arrays.get("q_target"), qd_rad_s=arrays.get("qd") if qd is None else qd,
                      qd_target_rad_s=arrays.get("qd_target"), tau_nm=arrays.get("tau") if tau is None else tau, i_q_a=arrays.get("i_q"),
                      mode=arrays.get("mode"), fault=arrays.get("fault"), temp_c=arrays.get("temp_c"), v_bus_v=arrays.get("voltage"),
                      run=run, device=device, situation=situation, source=source)


# ---------------------------------------------------------------------------------------------------- situations


def situations_for(record: dict) -> list[dict]:
    """Every series a run plays: real, the target (when the run commanded positions) and each model, on one clock."""

    a = record["arrays"]
    t = a["t"] - a["t"][0]
    out = [{"situation": REAL, "source": "real", "t": t, "q": a["q"], "qd": a.get("qd"), "tau": a.get("tau"), "i_q": a.get("i_q"),
            "temp": a.get("temp_c"), "v": a.get("voltage")}]
    if "q_target" in a and np.isfinite(a["q_target"]).any():
        out.append({"situation": TARGET, "source": "target", "t": t, "q": a["q_target"], "qd": a.get("qd_target")})
    return out


def model_situations(replay: dict) -> list[dict]:
    """A replayed run (twin_replays or rack_replays) as situations on the replay's own clock (the tape, prelude dropped)."""

    t = np.asarray(replay["t"], float)
    arr = lambda values: None if values is None else np.asarray([np.nan if v is None else v for v in values], float)  # noqa: E731
    out = [{"situation": REAL, "source": "real", "t": t, "q": arr(replay["q_rad"]), "qd": arr(replay.get("qd_rad_s")), "tau": arr(replay.get("tau_nm")),
            "i_q": arr(replay.get("i_q_a")), "temp": arr(replay.get("temp_c")), "v": arr(replay.get("v_bus_v")), "mode": arr(replay.get("mode"))},
           {"situation": TARGET, "source": "target", "t": t, "q": arr(replay["q_target_rad"]), "qd": arr(replay.get("qd_target_rad_s"))}]
    for name, model in replay["models"].items():
        out.append({"situation": name, "source": "sim", "t": t, "q": arr(model["q_rad"]), "qd": arr(model.get("qd_rad_s")), "tau": arr(model.get("tau_nm")),
                    "model": model})
    return out


def replays_by_path() -> dict[str, dict]:
    """npz path -> the replay record (twin_replays' four models win over rack_replays' one twin for the same run)."""

    out: dict[str, dict] = {}
    if RACK_REPLAYS.is_file():
        for run in json.loads(RACK_REPLAYS.read_text())["runs"]:
            s = run["samples"]
            out[run["run_path"]] = {"origin": "rack_replays", "t": s["t"], "q_rad": s["q_real"], "q_target_rad": s["q_target"], "tau_nm": s["tau_real"],
                                    "i_q_a": s.get("i_q_real"), "temp_c": s.get("temp_c_real"), "class": run.get("class"),
                                    "models": {"twin · full": {"label": f"{run['twin_name']} ({run['twin_version']})", "q_rad": s["q_twin"], "tau_nm": s["tau_twin"],
                                                               "q_rms_mrad": run["rms_q_mrad"], "expected_q_rms_mrad": run["rms_q_mrad_expected"], "oracle": run["oracle"]}},
                                    "floor_mrad": None, "source_file": str(RACK_REPLAYS)}
    if TWIN_REPLAYS.is_file():
        document = json.loads(TWIN_REPLAYS.read_text())
        for run in document["runs"]:
            out[run["run_path"]] = {"origin": "twin_replays", **run, "source_file": str(TWIN_REPLAYS)}
        out["__envelopes__"] = document.get("envelopes", {})
    # WHY a session's own replays (2026-11-05, CAN 11's frozen schedule): a schedule session's producer (bam_rack_twin
    # docs/can11_frozen_1105.py) writes the twin of record's replay of every run beside the runs, <session>/analysis/twin_replays.json,
    # in this file's twin_replays shape; found under the registry's archive folders, never copied into this repo
    for entry in json.loads(REGISTRY.read_text())["deployments"]:
        for root in entry["archive"]:
            for path in sorted(Path(root).glob("*/analysis/twin_replays.json")):
                document = json.loads(path.read_text())
                if document.get("schema") != "sim2real.twin_replays/1":
                    continue
                for run in document["runs"]:
                    out.setdefault(run["run_path"], {"origin": "session_replays", **run, "source_file": str(path)})
    return out


# ---------------------------------------------------------------------------------------------------- rows


def picks(t: np.ndarray) -> np.ndarray:
    """Display rows: every k-th row so the rate is <= MAX_DISPLAY_HZ (picked, never averaged), plus the last row."""

    period = float(np.median(np.diff(t))) if t.size > 1 else 1.0
    stride = max(1, math.ceil((1.0 / period) / MAX_DISPLAY_HZ - 1e-9)) if period > 0 else 1
    index = np.arange(0, t.size, stride)
    return index if index[-1] == t.size - 1 else np.append(index, t.size - 1)


def deg(values, i):
    return None if values is None else num(math.degrees(values[i]) if math.isfinite(values[i]) else math.nan, 6)


def sample_rows(situations: list[dict], device: str, run_id: str) -> list[dict]:
    """samples.json rows (contract §2/§3): t × situation for one device, display units, at most 100 Hz by picking rows."""
    rows = []
    for s in situations:
        t = s["t"]
        qdd = accel(t, s["qd"]) if s.get("qd") is not None else None
        for i in picks(t):
            row = {"t": num(t[i], 6), "run": run_id, "situation": s["situation"], "source": s["source"], "device": device, "q_deg": deg(s["q"], i),
                   "qd_deg_s": deg(s["qd"], i) if s.get("qd") is not None else None, "qdd_deg_s2": deg(qdd, i) if qdd is not None else None}
            for key, column in (("tau", "tau_nm"), ("i_q", "i_q_a"), ("temp", "temp_c"), ("v", "v_bus_v")):
                if s.get(key) is not None:
                    row[column] = num(s[key][i], 5)
            rows.append(row)
    return rows


def pairs_of(names_sources: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The pairs a producer writes (contract §5): each situation against the target, and each sim situation against real."""
    names = [n for n, _ in names_sources]
    out = [(n, TARGET) for n, _ in names_sources if n != TARGET and TARGET in names]
    out += [(n, REAL) for n, src in names_sources if src == "sim" and REAL in names]
    return out


def diff_tables(samples: list[dict], poses: list[dict]) -> tuple[list[dict], list[dict]]:
    """diff_samples and diff_poses rows: trajectory.difference_*(a, b) for every pair, on the samples as written (the display
    rows: the rack logs at ~94 Hz, under the 100 Hz cap, so they are its own samples)."""
    by = defaultdict(list)
    for row in samples:
        by[row["situation"]].append(row)
    pose_by = defaultdict(list)
    for row in poses:
        pose_by[row["situation"]].append(row)
    situations = [(name, rows[0]["source"]) for name, rows in by.items()]
    d_samples, d_poses = [], []
    for a, b in pairs_of(situations):
        d_samples += traj.difference_samples(by[a], by[b])
        d_poses += traj.difference_poses(pose_by[a], pose_by[b])
    return d_samples, d_poses


# WHY a marker at a nominal 100 mm (2026-10-29, the trajectory3d panel): the output link's own origin sits on the axis, so its
# path is a point; a marker 100 mm out along the link's x axis draws the arc the joint swept. It is a display marker, named
# for its radius, never a measured lever (the rack's lever lengths are unmeasured): its err_mm is 100 mm × the angle error.
MARKER_BODY = "marker_100mm"
MARKER_MM = 100.0


def pose_rows(samples: list[dict], device: str) -> list[dict]:
    """poses.json rows for the joint's output link: frame = the joint's own (origin on the axis, z along it, angle 0 at the
    board's zero), so the position stays at the origin and the orientation is the angle about z. WHY no lever tip: the
    rack's lever lengths are not measured (acceptance.py's class levers are agent defaults), and a pose is never guessed.
    Plus MARKER_BODY: the same link, a marker MARKER_MM along its x axis (see MARKER_BODY)."""
    frame = f"{device.replace(' ', '').lower()}_joint"
    out = []
    for body, radius in (("output_link", 0.0), (MARKER_BODY, MARKER_MM)):
        for row in samples:
            q = row.get("q_deg")
            if q is None:
                continue  # no angle, no pose (positions are required; a pose row is never made from 0)
            angle = math.radians(q)
            out.append({"t": row["t"], "run": row["run"], "situation": row["situation"], "source": row["source"], "body": body, "frame": frame,
                        "x_mm": radius * math.cos(angle), "y_mm": radius * math.sin(angle), "z_mm": 0.0,
                        "quat_w": math.cos(angle / 2), "quat_x": 0.0, "quat_y": 0.0, "quat_z": math.sin(angle / 2)})
    return out


# WHY err_mm on the pose rows (data-ui CONTRACT §35, path_overlay: "the producer writes the number (an error column is the
# difference rows' err_mm, written onto the pose rows): the view never computes an error"): the run page colours each path by
# its distance from the target at that instant, the diff_poses row of (situation, body, t) against the target; 0 on the target.
POSE_HINTS = {"err_mm": {"type": "number", "unit": "mm", "description": "distance from the target at t (diff_poses err_mm against target); 0 on the target"}}


def pose_errors(poses: list[dict], d_poses: list[dict]) -> None:
    err = {(r["situation"], r["body"], r["t"]): r["err_mm"] for r in d_poses if r.get("reference") == TARGET}
    has_target = any(r["situation"] == TARGET for r in poses)
    for row in poses:
        row["err_mm"] = (0.0 if row["situation"] == TARGET else err.get((row["situation"], row["body"], row["t"]))) if has_target else None


def write_contract(path: Path, name: str, rows: list[dict], title: str, source: str, hints: dict | None = None, **top) -> int:
    """A contract table ({schema: {fields}, rows}) checked against data-ui's schema before it is written; a breach stops the build.
    `hints` adds data-ui's display keys (display, colors, digits, note) to a field, and declares the app's own columns."""
    hints = hints or {}
    extra = [{"name": k, "type": v.get("type", "string"), **{kk: vv for kk, vv in v.items() if kk != "type"}} for k, v in hints.items()]
    document = traj.contract_table(name, rows, title=title, source=source, extra_fields=extra, **top)
    for field in document["schema"]["fields"]:
        for k, v in hints.get(field["name"], {}).items():
            if k not in ("type", "unit"):
                field.setdefault(k, v)
    problems = traj.validate(name, document)
    if problems:
        raise SystemExit(f"{path}: breaks the robotics contract: {problems[:5]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return len(rows)


def coverage_rows(record: dict, run_id: str, device: str, kind: str, day: str, hz: float) -> list[dict]:
    """The run on a uniform time grid (w = 1, so a count is time spent), plus its argmin/argmax rows of every channel (w = 0:
    histograms that sum w stay unbiased, while min/max over rows stays exact; PEP 0010 §4.4, M4 weighted)."""

    a = record["arrays"]
    t = a["t"] - a["t"][0]
    qd = a.get("qd")
    qdd = accel(t, qd) if qd is not None else None
    grid = np.arange(0.0, t[-1] + 1e-9, 1.0 / hz)
    on_grid = np.unique(np.clip(np.searchsorted(t, grid), 0, t.size - 1))
    extremes = set()
    for values in (a["q"], qd, qdd, a.get("tau")):
        if values is not None and np.isfinite(values).any():
            extremes.update((int(np.nanargmin(values)), int(np.nanargmax(values))))
    rows = []
    for i, w in [(int(i), 1) for i in on_grid] + [(i, 0) for i in sorted(extremes - set(on_grid.tolist()))]:
        rows.append({"run": run_id, "device": device, "kind": kind, "day": day, "t": num(t[i], 5), "w": w, "q_deg": deg(a["q"], i),
                     "qd_deg_s": deg(qd, i) if qd is not None else None, "qdd_deg_s2": deg(qdd, i) if qdd is not None else None,
                     "tau_nm": num(a["tau"][i], 4) if "tau" in a else None, "layer": "path"})
    return rows


# ---------------------------------------------------------------------------------------------------- diagnostics


def run_link(dep_id: str, slug: str):
    def link(run: str, t0, t1) -> str:
        base = f"{APP_URL}?d={dep_id}&run={slug}"
        return base if t0 is None else f"{base}#t={t0:.3f}&tr={t0:.3f},{(t1 if t1 is not None else t0):.3f}"
    return link


def run_diagnostics(dep_id: str, slug: str, title: str, device: str, situations: list[dict], arrays: dict, floor_mrad: float | None) -> list[dict]:
    """The gates layer of one run, computed FROM its data by robotdx.diagnostics: tracking (real vs target), each model's
    error against real over the station's floor, board temperature, faults and the sample rate."""

    by = {s["situation"]: s for s in situations}
    real_s = by[REAL]
    mode = real_s.get("mode") if real_s.get("mode") is not None else (arrays.get("mode") if real_s["t"].size == arrays["t"].size else None)
    real = Trajectory(t=real_s["t"], q_rad=real_s["q"], q_target_rad=by[TARGET]["q"] if TARGET in by else None, qd_rad_s=real_s.get("qd"),
                      tau_nm=real_s.get("tau"), mode=mode, run=slug, device=device)
    link = run_link(dep_id, slug)
    subject = f"{dep_id}/{device}"
    rows, results = [], []
    if TARGET in by:
        results.append(evaluate("stock.tracking_error", TrackingErrorConfig(controlled_only=mode is not None), [real], subject=subject))
    for name, s in by.items():
        if s["source"] != "sim":
            continue
        model = real.as_situation(s["q"], name, "sim")
        limits = Limits.at_most(FIDELITY_GATE * floor_mrad) if floor_mrad else Limits()
        result = evaluate("stock.model_error", ModelErrorConfig(controlled_only=mode is not None, limits=limits), [(real, model)], subject=subject)
        note = f" (gate {FIDELITY_GATE:g} x floor {floor_mrad:.2f} mrad)" if floor_mrad else " (no floor recorded: not judged)"
        results.append(replace(result, title=f"{name} vs real", message=result.message + note))
    full = trajectory(arrays, run=slug, device=device, situation=REAL, source="real")
    if full.temp_c is not None:
        results.append(evaluate("stock.box", BOARD_TEMP, [full], subject=subject))
    if full.fault is not None:
        results.append(evaluate("stock.fault_codes", FaultCodesConfig(), [full], subject=subject))
    results.append(evaluate("stock.sample_rate", RateConfig(expected_hz=100.0), [Stamps(full.t, slug)], subject=subject))
    for result in results:
        row = result_row(result, parent=title, link=link)
        row.update({"device": device, "run_slug": slug})
        rows.append(row)
    return rows


def deployment_gates(dep_dir: Path) -> tuple[list[dict], list[dict], dict]:
    """The rack's gate matrix and diagnostic rows: tools/diagnostics_run_rack.py run as is (its OUT pointed into the app),
    so the app's gates layer is byte-for-byte the producer's."""

    spec = importlib.util.spec_from_file_location("diagnostics_run_rack", REPO / "tools" / "diagnostics_run_rack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = dep_dir / "dx"
    module.main()
    gates = json.loads((module.OUT / "gates.json").read_text())
    diagnostics = json.loads((module.OUT / "diagnostics.json").read_text())
    order = {gate: i for i, gate in enumerate(gates["payload"].get("gates", []) if isinstance(gates.get("payload"), dict) else [])}
    cells = [{"device": cell["subject"], "gate": cell["gate"], "verdict": cell["verdict"], "value": num(cell["value"], 4), "unit": cell["unit"],
              "message": cell["message"], "acceptance": cell.get("acceptance"), "order": order.get(cell["gate"], i),
              "passed": 1 if cell["verdict"] == "pass" else 0, "cell": 1}
             for i, cell in enumerate(gates["cells"])]
    return cells, diagnostics, gates["matrix"]


# ---------------------------------------------------------------------------------------------------- why it fails (calibration round)

GATE_ORDER = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11"]


def acceptance_cells(path: Path) -> list[dict]:
    """The station gate matrix from bam_rack_twin's acceptance file (every gate T1-T11 as that pipeline judged it from the runs)."""

    stations = json.loads(path.read_text())["stations"]
    cells = []
    for can, station in stations.items():
        for gate in station["gates"]:
            verdict = gate.get("status") or gate.get("verdict")
            value = gate.get("value")
            cells.append({"device": f"CAN {can}", "gate": f"{gate['id']} {gate.get('name', '')}".strip(), "verdict": verdict,
                          "value": num(value, 4) if isinstance(value, (int, float)) else None, "value_text": None if isinstance(value, (int, float)) else value,
                          "target": gate.get("target"), "message": gate.get("detail") or None, "order": GATE_ORDER.index(gate["id"]) if gate["id"] in GATE_ORDER else 99,
                          "passed": 1 if verdict == "pass" else 0, "cell": 1, "source": str(path)})
    return cells


def slug_of(path: str) -> str:
    rel = Path(path).relative_to("/archive/datasets/bam_rig").with_suffix("")
    return str(rel).removeprefix("rack_").replace("/", "~")


def rules_in_force(acceptance_path: Path | None) -> tuple[str, str]:
    """(floor rule, pick rule) the acceptance file was judged under. WHY (bam_rack_twin, 2026-11-04): the gates default to the pooled
    floor and the held-out-safer pick (Zach: go with the default on easy-to-reverse calls); a file written before then names neither
    and was judged on the session floor with the declared pick."""

    doc = json.loads(Path(acceptance_path).read_text()) if acceptance_path else {}
    return doc.get("floor_rule", "session"), doc.get("pick_rule", "declared")


def why(entry: dict, dep_id: str, runs: list[dict], pick_rule: str = "declared") -> tuple[list[dict], list[dict]]:
    """One row per station: T2 moves/hold against the 1.5 gate (before -> after), the limiting term in the study's words, the share of
    the held-out torque gap its term family explains on its own, and a link to the worst held-out window in playback. Plus the two
    caveats, derived (the why file does not state them): the floors grew on the new day, and three picks were overfit."""

    doc = json.loads(Path(entry["why"]).read_text())
    scored = json.loads(Path(entry["scored"]).read_text())["stations"]
    earlier = json.loads(Path(entry["earlier_floors"]).read_text())
    by_slug = {r["run"]: r for r in runs}
    v1 = json.loads(Path(entry["why_calibration"]).read_text())["stations"] if entry.get("why_calibration") else {}
    rows, grew, overfit, rules = [], [], [], []
    for sid, station in doc["stations"].items():
        can = int(sid.removeprefix("can"))
        t2 = station["t2"]
        after, before = t2.get("after") or {}, t2.get("before") or {}
        lt = station.get("limiting_term") or {}
        ev = lt.get("evidence") or {}
        dec = ev.get("residual_decomposition_after") or ev.get("residual_decomposition_before") or {}
        family = lt.get("remaining_largest_family")
        name = lt.get("name") or ""
        summary = station.get("summary") or ""
        chosen = (t2.get("safer_pick") if pick_rule == "safer" else None) or t2.get("declared_pick")
        if "variants" in t2:  # v2 (follow-up) rows: the pick under the rule in force against the twin today (C), the decomposition keyed by variant
            after, before = t2["variants"][chosen], t2["variants"].get("C", {})
            per_variant = ev.get("residual_decomposition") or {}
            dec = per_variant.get(chosen) or {}
            m = re.search(r"follows (.+?) most \((\d+)% on its own", summary)
            family = m.group(1) if m else family
            if not name:
                sentences = [x for x in summary.split(". ") if x and not x.startswith(("passes", "fails", "The held-out torque gap"))]
                name = (f"{family} (the held-out gap's largest term); " if family else "") + (sentences[0] if sentences else "")
        shares = dec.get("unique_r2") or {}
        term_family = next((f for f in shares if f.split(" ")[0] in name.lower()), None) or ("inertia" if "inertia" in name else None)
        shown = term_family or family
        share = shares.get(shown) if shown else None
        # the floor on the new day against the 10-24 floor (the same T1 ruler), and the pick against the deployed twin
        new_floor = (t2.get("floor") or {}).get("floor_mrad") or (scored.get(sid, {}).get("floor") or {}).get("floor_mrad")
        pick_rule_row = None
        if "declared_pick" in t2 and t2["declared_pick"] != t2.get("safer_pick"):
            declared, safer = t2["variants"][t2["declared_pick"]], t2["variants"][t2["safer_pick"]]
            pick_rule_row = (can, t2["declared_pick"], declared["moves_over_floor"], t2["safer_pick"], safer["moves_over_floor"])
        old_floor = (earlier.get(str(can)) or {}).get("floor_mrad")
        floor_growth = new_floor / old_floor if new_floor and old_floor and sid in scored else None  # CAN 11: its final-controller floor
        if floor_growth and floor_growth > 1:
            grew.append(f"CAN {can} {old_floor:.2f} → {new_floor:.2f} mrad")
        is_overfit = None
        if sid in scored:
            variants = scored[sid]["variants"]
            pick = scored[sid]["pick"]
            # the calibration round's identification objectives (v1 why file): v2 re-scored CAN 1 and 11 but the round's picks stand as they were
            ident = ((((v1.get(sid) or {}).get("limiting_term") or {}).get("evidence") or {}).get("identification_objective_mrad")
                     or ev.get("identification_objective_mrad") or {})
            if pick in variants and "A" in variants and pick in ident and "A" in ident:
                better_ident = ident[pick] < ident["A"]
                worse_held = variants[pick]["split"]["moves_over_floor"] > variants["A"]["split"]["moves_over_floor"]
                is_overfit = bool(better_ident and worse_held)
                if is_overfit:
                    overfit.append(f"CAN {can} (identification {ident['A']:.2f} → {ident[pick]:.2f} mrad, held-out moves "
                                   f"{variants['A']['split']['moves_over_floor']:.2f}× → {variants[pick]['split']['moves_over_floor']:.2f}×)")
        worst = (station.get("worst") or [{}])[0]
        window = (worst.get("windows") or [{}])[0]
        slug = slug_of(worst["run"]) if worst.get("run") else None
        run_row = by_slug.get(slug)
        link = None
        if run_row and window:
            offset = run_row.get("clock_offset_s") or 0.0
            t0, t1 = window["t0_s"] + offset, window["t1_s"] + offset
            link = f"{APP_URL}?d={dep_id}&run={slug}&why={sid}#t={t0:.3f}&tr={t0:.3f},{t1:.3f}"
        reason = summary.split(". ", 1)[1] if ". " in summary else summary
        rows.append({
            "device": f"CAN {can}", "station": sid, "status": "pass" if station["status"].startswith("pass") or "passes" in summary[:40] else "fail",
            "round": "carried (10-28 tapes)" if "carried" in station["status"] else "calibration 10-29",
            "moves_x": num(after.get("moves_over_floor"), 3), "hold_x": num(after.get("hold_offset_over_floor"), 3), "gate_x": 1.5,
            "moves_before_x": num(before.get("moves_over_floor"), 3), "hold_before_x": num(before.get("hold_offset_over_floor"), 3),
            "limiting_term": name, "why": reason, "evidence_family": shown, "evidence_share": num(share, 3),
            "unexplained": num(dec.get("unexplained"), 3),
            "evidence": (f"{shown}: {100 * share:.0f} % of the held-out torque gap on its own; {100 * dec['unexplained']:.0f} % unexplained"
                         if share is not None and dec.get("unexplained") is not None else "no residual decomposition in the why file"),
            "floor_mrad": num(new_floor, 4), "floor_before_mrad": num(old_floor, 4) if sid in scored else None,
            "floor_growth_x": num(floor_growth, 3), "overfit_pick": is_overfit,
            "worst_run": slug, "worst_window": f"{window['t0_s']:.2f}-{window['t1_s']:.2f} s (tape clock), {window['rms_mrad']:.2f} mrad RMS" if window else None,
            "page": link, "order": can,
            "pick": chosen or t2.get("pick"), "safer_pick": t2.get("safer_pick"),
            "cis": "; ".join(f"{p['name']} {p['value']:.3g} [{p['ci95'][0]:.3g}, {p['ci95'][1]:.3g}]" for p in
                             (((station.get("identified") or {}).get("parameters") if isinstance(station.get("identified"), dict) else station.get("identified")) or [])
                             if isinstance(p, dict) and p.get("ci95") and isinstance(p.get("value"), (int, float)))[:400] or None,
            "pick_rule": (f"declared {pick_rule_row[1]} {pick_rule_row[2]:.2f}× vs held-out-safer {pick_rule_row[3]} {pick_rule_row[4]:.2f}× "
                          f"(the gates use the {pick_rule} pick)" if pick_rule_row else None)})
        if pick_rule_row:
            rules.append(pick_rule_row)
    rows.sort(key=lambda r: (r["status"] == "pass", -(r["moves_x"] or 0)))
    caveats = [
        {"caveat": "Floors grew on the new day", "detail": f"{len(grew)} of {len(scored)} refit stations have a larger T1 floor than on 10-24 ("
                   + "; ".join(grew) + "), so every × floor ratio looks better than it would against the old floor.", "stations": len(grew)},
        {"caveat": f"{len(overfit)} picks were overfit (calibration round)", "detail": "The calibrated twin beat the deployed twin on identification but did worse on the "
                   "held-out tapes: " + "; ".join(overfit) + ". The pick rule chooses on identification only, so these passes or fails lean on a twin "
                   "the held-out data did not prefer.", "stations": len(overfit)},
    ]
    for can, declared, d_moves, safer, s_moves in rules:
        shown, shown_moves = (safer, s_moves) if pick_rule == "safer" else (declared, d_moves)
        caveats.append({"caveat": f"The two pick rules disagree on CAN {can}",
                        "detail": f"The held-out-safer twin ({safer}) scores {s_moves:.2f}× moves; the declared pick ({declared}) scores {d_moves:.2f}×. "
                                  f"The gates use the {pick_rule} pick (declared: the lower identification mean; safer: the same among the candidates "
                                  f"with no identification family worse by > 5 %), so this panel shows {shown}'s {shown_moves:.2f}×. "
                                  + ("The safer rule is the default since 2026-11-04 (Zach: go with the default on easy-to-reverse calls); "
                                     "--pick-rule declared in bam_rack_twin.acceptance switches back." if pick_rule == "safer" else
                                     "The safer rule would show the other number."), "stations": 1})
    return rows, caveats


def write_decompositions(dep_dir: Path, entry: dict) -> None:
    """Per station: each term family's unique share of the held-out torque gap (before and after this round) and where the move error lives."""

    doc = json.loads(Path(entry["why"]).read_text())
    for sid, station in doc["stations"].items():
        ev = (station.get("limiting_term") or {}).get("evidence") or {}
        rows = []
        t2 = station.get("t2") or {}
        if "residual_decomposition" in ev:  # v2: one decomposition per variant; the twin today (C) and the declared pick
            pairs = [(f"before (twin today, C)", ev["residual_decomposition"].get("C") or {}),
                     (f"after (declared pick, {t2.get('declared_pick')})", ev["residual_decomposition"].get(t2.get("declared_pick")) or {})]
        else:
            pairs = [("before (deployed twin)", ev.get("residual_decomposition_before") or {}), ("after (calibrated twin)", ev.get("residual_decomposition_after") or {})]
        for when, dec in pairs:
            for family, share in (dec.get("unique_r2") or {}).items():
                rows.append({"chart": "torque gap", "what": family, "share": num(share, 4), "when": when})
            if dec.get("unexplained") is not None:
                rows.append({"chart": "torque gap", "what": "unexplained", "share": num(dec["unexplained"], 4), "when": when})
            for phase, share in (dec.get("moving_q_error_share") or {}).items():
                rows.append({"chart": "move error", "what": phase, "share": num(share, 4), "when": when})
        write(dep_dir / "why" / f"{sid}.json", f"Residual decomposition · CAN {sid[3:]}", f"{entry['why']} limiting_term.evidence",
              {"share": {"digits": 3}}, rows)


# ---------------------------------------------------------------------------------------------------- the newest evidence, found, never pinned


def newest(entry: dict, pattern: str, stamp_key: str, schema_prefix: str | None = None) -> tuple[Path, str] | tuple[None, None]:
    """The newest file matching `pattern` in any archive day's analysis/ folder, by its own `stamp_key` (an ISO time inside the
    file). WHY by the file's stamp and never a pinned path (Codex audit 2026-10-29): the registry pinned acceptance_followup.json
    while acceptance_warm4.json had landed, so the app showed 22/88 cells passing instead of 28/88 and CAN 12 T3 as a pass."""

    best = (None, None)
    for day in entry["archive"]:
        for path in sorted((Path(day) / "analysis").glob(pattern)):
            try:
                doc = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            stamp = doc.get(stamp_key) if isinstance(doc, dict) else None
            if not stamp or (schema_prefix and not str(doc.get("schema", "")).startswith(schema_prefix)):
                continue
            if best[1] is None or stamp > best[1]:
                best = (path, stamp)
    return best


def evidence_sources(entry: dict) -> dict:
    """Every evidence file the gates layer and Why it fails read: the newest of each kind, with its own date."""

    found = {"acceptance": newest(entry, "acceptance*.json", "generated_at", "bam_rack_twin.acceptance/"),
             "why": newest(entry, "calibration_why*.json", "written_at"),
             "triage": newest(entry, "gates_triage*.json", "written_at"),
             "floors_pooled": newest(entry, "floors_pooled*.json", "written_at")}
    warm = {}
    for day in entry["archive"]:
        for path in sorted((Path(day) / "analysis").glob("warm*_scored.json")):
            doc = json.loads(path.read_text())
            for sid, station in doc.get("stations", {}).items():
                if sid not in warm or doc["scored_at"] > warm[sid][1]:
                    warm[sid] = (path, doc["scored_at"], station)
    found["warm"] = warm
    return found


GATE_NAMES = {"T1": "floor", "T2": "fidelity", "T3": "torque", "T4": "static accuracy", "T5": "encoder-blind terms", "T6": "drive gain",
              "T7": "envelope", "T8": "thermal", "T9": "warm and cold", "T10": "live re-identification", "T11": "provenance"}


def _fmt(value) -> str:
    if value is None:
        return "no number"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:.3g}"
    return str(value)


# WHY every number on a row is the displayed result's (Codex audit round 2, 2026-10-29: CAN 21 T9's headline read 4.08x while its
# explanation said 3.93x from an older warm file; T2 showed 1.747 beside a split limit it is not judged by). The headline is built
# only from the acceptance cell (its judged statistics and limits); prose from any other file is wrapped in a
# "[from <file>, <date>, model <id>, ...]" block, and when that file's own number differs from the one shown, the block says both.
RATIO_GATES = {"T2", "T3", "T9", "T10"}
RULE_WORD = {"<=": "≤", ">=": "≥", "==": "needs"}
LIMIT_UNIT = {"T1": " repeats", "T4": " mrad", "T5": " arcmin", "T6": " %", "T7": " %", "T8": " degC"}
# the facts line each gate's result was read from (the study that wrote it names its file and model there)
SOURCE_KEYS = {"T2": ("dataset_source", "t2_split_source"), "T3": ("torque_ratio_source",), "T9": ("warm_cold_source",), "T10": ("live_reid_source",)}


def _same(a, b, tol: float = 0.006) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= tol * max(1.0, abs(b))


def _stamp(stamp) -> str:
    return f"{str(stamp)[:10]} {str(stamp)[11:16]}Z" if stamp else "undated"


def labelled(path, stamp, model, text: str, note: str = "") -> str:
    """Prose from a file other than the displayed acceptance, with its provenance; `note` says whether it is the same result."""
    return (f"[from {Path(str(path)).name}, {_stamp(stamp)}, model {model or 'not named in that file'}"
            f"{', ' + note if note else ''}: {text.strip().rstrip('.;')}]")


def cited_result(facts: dict, gid: str) -> tuple[Path | None, str | None]:
    """(result file, model) the acceptance's facts cite for this gate: '<path> (<model>; ...)'."""
    for key in SOURCE_KEYS.get(gid, ()):
        line = facts.get(key)
        m = re.match(r"(\S+\.json)\s*(?:\((.*)\))?", str(line or ""))
        if m:
            model = (m.group(2) or "").split(";")[0].strip()
            if gid == "T10":  # WHY: T10's line opens with the routine, not the twin; T9's line names the twin the routine started from
                warm = re.match(r"\S+\.json\s*\((.*)\)", str(facts.get("warm_cold_source") or ""))
                model = warm.group(1).split(";")[0].strip() if warm else model
            return Path(m.group(1)), model.split(", floor /")[0] or None
    return None, None


def model_of(gid: str, facts: dict, cited_model: str | None) -> str:
    if cited_model:
        return cited_model
    if gid == "T1":
        return "none: the rack against itself"
    if gid == "T4" and (facts.get("stop") or {}).get("variant"):
        return f"controller: {facts['stop']['variant']}"
    return "not model-scored (a measurement of the rack or its record)"


def headline(gid: str, gate: dict) -> str:
    """The judged statistics beside their own limits, from the acceptance cell only."""
    unit = "×" if gid in RATIO_GATES else ""
    judged = gate.get("judged") or []
    if judged:
        parts = []
        for j in judged:
            if j["rule"] == "==":
                parts.append(f"{j['name']}: {_fmt(j['value'])} ({'ok' if j['passes'] else 'needs ' + _fmt(j['limit'])})")
            else:
                parts.append(f"{j['name']} {_fmt(j['value'])}{unit} {RULE_WORD[j['rule']]} {_fmt(j['limit'])}{unit} {'✓' if j['passes'] else '✗'}")
        text = " · ".join(parts)
        value = gate.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not any(_same(value, j["value"], 0.0005) for j in judged if isinstance(j["value"], (int, float))):
            text += f" (overall {_fmt(value)}{unit}, shown, not judged)"
        return text
    limit = gate.get("limit")
    unit = LIMIT_UNIT.get(gid, unit)
    return "no judged number" + (f" · limit {_fmt(limit)}{unit}" if limit is not None else "")


WORST_WINDOW_S = 1.0  # the playback window a session-scored T2 row opens: the 1 s of the judged tape where the twin is furthest from real


def worst_window(replay: dict, prelude_s: float) -> tuple[float, float, float] | None:
    """(t0, t1, RMS mrad) of the WORST_WINDOW_S window with the largest RMS(real - twin) after the prelude, rows both in position mode, on the
    run's own clock (the page clock: the replay's t starts at the run's first row)."""

    t = np.asarray(replay["t"], float)
    model = next(iter(replay["models"].values()))
    real = np.asarray([np.nan if v is None else v for v in replay["q_rad"]], float)
    twin = np.asarray([np.nan if v is None else v for v in model["q_rad"]], float)
    error = np.where((t >= prelude_s) & np.isfinite(real) & np.isfinite(twin), real - twin, np.nan)
    best = None
    for start in np.arange(prelude_s, max(prelude_s, t[-1] - WORST_WINDOW_S) + 1e-9, 0.1):
        rows = error[(t >= start) & (t < start + WORST_WINDOW_S)]
        rows = rows[np.isfinite(rows)]
        if rows.size and (best is None or np.sqrt(np.mean(rows**2)) > best[2]):
            best = (float(start), float(start + WORST_WINDOW_S), float(np.sqrt(np.mean(rows**2))))
    return None if best is None else (best[0], best[1], 1e3 * best[2])


def session_t2(res: dict, cited_path: Path, by_slug: dict, dep_id: str, sid: str) -> tuple[str, bool, bool, str, str | None]:
    """A schedule session's T2 (its scored file's fidelity.t2): both floor rules, the reason in numbers, and the worst window of the judged tape."""

    t2, the_floors = res["fidelity"]["t2"], res["floors"]
    a, b = t2["session"], t2["pooled"]
    floors = (f"session floor ({the_floors['session']['all']:.2f} mrad): moves {a['moves_over_floor']:.2f}×, hold {a['hold_offset_over_floor']:.2f}× "
              f"({'pass' if a['passes'] else 'fail'}) · pooled floor ({the_floors['pooled']['all']:.2f} mrad, {the_floors['pooled']['pairs']} pairs): "
              f"moves {b['moves_over_floor']:.2f}×, hold {b['hold_offset_over_floor']:.2f}× ({'pass' if b['passes'] else 'fail'})")
    run = Path(a["t2_run"])
    body = (f"on the frozen schedule {str(res.get('schedule_digest', ''))[:8]}'s held-out operate runs ({t2['runs']}, H2), the twin's moving error on the worst "
            f"{t2['floor_class']} tape ({run.stem}) is {a['moves_mrad']:.2f} mrad against the floor's moving part; its rest offset {abs(a['rest_offset_mrad']):.2f} mrad "
            f"passes. This session's floor is {the_floors['session']['all'] / the_floors['il0.5']['all']:.2f}× the 10-29 floor, so the verdict depends on which "
            f"floor divides it")
    link = None
    slug = slug_of(str(run))
    replays = cited_path.parent / "twin_replays.json"
    if slug in by_slug and replays.is_file():
        replay = next((r for r in json.loads(replays.read_text())["runs"] if r["run_path"] == str(run)), None)
        window = worst_window(replay, float(replay.get("prelude_s") or 0.0)) if replay else None
        if window:
            t0, t1, rms_mrad = window
            link = f"{APP_URL}?d={dep_id}&run={slug}&why={sid}#t={t0:.3f}&tr={t0:.3f},{t1:.3f}"
            body += f"; its worst {WORST_WINDOW_S:g} s is {t0:.2f}-{t1:.2f} s, {rms_mrad:.2f} mrad RMS (twin vs real)"
    return floors, bool(a["passes"]), bool(b["passes"]), body, link


def failed_cells(entry: dict, dep_id: str, runs: list[dict], sources: dict, t2_rows: list[dict]) -> list[dict]:
    """One row per (station, gate) the newest acceptance does not pass, plus each pass that flips under the pooled floor: the judged
    statistics against their limits (headline), why (from the result file the acceptance cites, else the acceptance's own words),
    the evidence, both floor rules where they differ (the acceptance file names the one in force), the next step, and any earlier result from an older
    file, labelled with its file, date and model. Each field says something the others do not."""

    acc_path, acc_stamp = sources["acceptance"]
    acceptance = json.loads(acc_path.read_text())["stations"]
    floor_rule, _ = rules_in_force(acc_path)
    other_rule = "session" if floor_rule == "pooled" else "pooled"
    triage_path, triage_stamp = sources["triage"]
    triage_doc = json.loads(triage_path.read_text()) if triage_path else {}
    triage = {(c["station"], c["gate"]): c for c in triage_doc.get("cells", [])}
    zach = {}
    for action, cells in triage_doc.get("zach_actions", {}).items():
        for cell in cells:
            zach.setdefault(tuple(cell.split()), action)
    pooled_path, pooled_stamp = sources["floors_pooled"]
    pooled = json.loads(pooled_path.read_text())["stations"] if pooled_path else {}
    why_path, why_stamp = sources["why"]
    t2_by = {r["station"]: r for r in t2_rows}
    by_slug = {r["run"]: r for r in runs}
    loaded: dict[Path, dict] = {}

    def result_doc(path: Path | None) -> dict:
        if path is None or not path.is_file():
            return {}
        if path not in loaded:
            loaded[path] = json.loads(path.read_text())
        return loaded[path]

    rows = []
    for can, station in acceptance.items():
        sid = f"can{can}"
        facts = station.get("facts") or {}
        for gate in station["gates"]:
            status = gate.get("status")
            gid = gate["id"]
            if status == "pass" and gid not in ("T2", "T9"):
                continue
            tri = triage.get((sid, gid), {})
            value = gate.get("value")
            cited_path, cited_model = cited_result(facts, gid)
            model = model_of(gid, facts, cited_model)
            res = result_doc(cited_path)
            if str(res.get("schema", "")).startswith("bam_rack_twin.can11_frozen") and (res.get("twin") or {}).get("version"):
                # a schedule session's scored file names its twin itself; the acceptance's source line opens with the schedule instead
                cited_model = model = f"twin of record: followup {res['twin']['label']} ({res['twin']['version']})" if gid in RATIO_GATES else model
            res_station = (res.get("stations") or {}).get(sid) or {}
            res_stamp = res.get("scored_at") or res.get("written_at")
            limiting = res_station.get("labels", {}).get("pick")  # a modelling round's pick: t2/t9/t10 keyed by its label
            why_parts, evidence, earlier = [], [], []
            floors, session_pass, pooled_pass, link = None, None, None, None
            judged = {j["name"]: j["value"] for j in gate.get("judged") or []}
            if cited_path:
                evidence.append(f"result: {cited_path.name} ({_stamp(res_stamp)}), as {acc_path.name} cites it")

            if gid == "T2":
                if limiting is not None:
                    t2 = res_station["t2"][limiting]
                    a, b = t2["session"]["split"], t2["pooled"]["split"]
                    session_pass, pooled_pass = a["passes"], b["passes"]
                    floors = (f"session floor: moves {a['moves_over_floor']:.2f}×, hold {a['hold_offset_over_floor']:.2f}× ({'pass' if a['passes'] else 'fail'}) · "
                              f"pooled floor: moves {b['moves_over_floor']:.2f}×, hold {b['hold_offset_over_floor']:.2f}× ({'pass' if b['passes'] else 'fail'})")
                elif ((res.get("fidelity") or {}).get("t2") or {}).get("pooled"):
                    # a schedule session's scored file (bam_rack_twin docs/can11_frozen_1105.py): its own T2 on the session's held-out set
                    floors, session_pass, pooled_pass, body, link = session_t2(res, cited_path, by_slug, dep_id, sid)
                    floors = labelled(cited_path, res_stamp, cited_model, floors, "the same result")
                    why_parts.append(labelled(cited_path, res_stamp, cited_model, body, "the same result"))
                else:
                    p2 = (pooled.get(sid) or {}).get("t2") or {}
                    if p2.get("session") and p2.get("pooled"):
                        a, b = p2["session"], p2["pooled"]
                        used = b if floor_rule == "pooled" else a  # the side the gate was judged on
                        same = _same(used["moves_over_floor"], judged.get("moves")) and _same(used["hold_offset_over_floor"], judged.get("hold offset"))
                        text = (f"session floor: moves {a['moves_over_floor']:.2f}×, hold {a['hold_offset_over_floor']:.2f}× ({'pass' if a['passes'] else 'fail'}) · "
                                f"pooled floor: moves {b['moves_over_floor']:.2f}×, hold {b['hold_offset_over_floor']:.2f}× ({'pass' if b['passes'] else 'fail'})")
                        if same:
                            floors, session_pass, pooled_pass = labelled(pooled_path, pooled_stamp, None, text, "the same result"), a["passes"], b["passes"]
                        else:
                            earlier.append(labelled(pooled_path, pooled_stamp, None, text, "an earlier result"))
                if sid in t2_by:
                    t2 = t2_by[sid]
                    term, story = t2.get("limiting_term") or "", t2.get("why") or ""
                    reason = story if term and term.split(";")[-1].strip()[:40] in story else (f"limiting term: {term}. " if term else "") + story
                    extra = [t2.get("evidence") or ""]
                    if t2.get("cis"):
                        extra.append("identified, 95 % CI: " + t2["cis"])
                    if t2.get("unexplained") is not None and t2["unexplained"] >= 0.5:
                        extra.append(f"{100 * t2['unexplained']:.0f} % of the held-out torque gap follows no term the decomposition tests: unexplained, not attributed")
                    body = reason.strip().rstrip(".") + ". Evidence there: " + "; ".join(x for x in extra if x)
                    same = _same(t2.get("moves_x"), judged.get("moves")) and _same(t2.get("hold_x"), judged.get("hold offset"))
                    if same:
                        why_parts.append(labelled(why_path, why_stamp, t2.get("pick"), body, "the same result"))
                        link = t2.get("page")
                    else:
                        earlier.append(labelled(why_path, why_stamp, t2.get("pick"), body,
                                                f"an earlier result: moves {_fmt(t2.get('moves_x'))}×, hold {_fmt(t2.get('hold_x'))}× there"))

            if gid in ("T9", "T10"):
                if limiting is not None:
                    cell = res_station[gid.lower()][limiting]
                    if gid == "T9":
                        worst = max(cell["sessions"].values(), key=lambda w: w["session_ratio"])
                        session_pass, pooled_pass = cell["session"] <= 1.5, cell["pooled"] <= 1.5
                        why_parts.append(f"warm, the twin misses by {worst['twin_mrad']:.2f} mrad against that session's own floor of {worst['session_floor_mrad']:.2f} mrad "
                                         f"(= {_fmt(cell['session'])}×); over the pooled floor it is {_fmt(cell['pooled'])}×, which "
                                         + ("passes, so the verdict depends on the floor rule" if pooled_pass else "still fails, so the floor rule does not rescue it"))
                        floors = (f"session floor: {_fmt(cell['session'])}× ({'pass' if session_pass else 'fail'}) · "
                                  f"pooled floor: {_fmt(cell['pooled'])}× ({'pass' if pooled_pass else 'fail'})")
                        evidence.append(f"{len(cell['sessions'])} warm session(s): " + ", ".join(Path(k).name for k in cell["sessions"]))
                    else:
                        v2 = cell.get("v2") or {}
                        why_parts.append(f"the 60 s live routine (v2) changes nothing: {v2.get('why', 'no reason written')} (applied scale {_fmt(v2.get('applied_scale'))}), "
                                         f"so after the warm drift the twin stays at {cell['restored_mrad']:.2f} mrad = {_fmt(cell['session_ratio'])}× the session floor "
                                         f"({_fmt(cell['pooled_ratio'])}× the pooled floor)")
                        evidence.append(f"warm session {Path(cell.get('session', '')).name}")
                elif res_station.get(gid.lower()):
                    warm = res_station
                    if gid == "T9":
                        t9 = warm["t9"]
                        body = (f"warm, the twin misses by {t9['warm_twin_median_mrad']:.2f} mrad against the warm floor's {t9['warm_floor_mrad']:.2f} mrad = "
                                f"{t9['warm_over_floor']:.2f}×; cold it is {t9['cold_over_floor']:.2f}×. The twin moved {t9['twin_warm_over_cold']:.2f}× warm vs cold, "
                                f"the floor {t9['floor_warm_over_cold']:.2f}×; {len(t9.get('warm_runs_mrad', {}))} warm runs, worst session: {t9.get('worst_session')}")
                        mine = t9["warm_over_floor"]
                    else:
                        t10 = warm["t10"]
                        mine = t10.get("restored_over_floor", (t10.get("v2") or {}).get("restored_over_floor"))
                        note = (t10.get("v2") or {}).get("why") or ""
                        body = (f"after the heating drift, the live re-identification left the twin at {_fmt(mine)}× the warm floor (stale twin "
                                f"{_fmt(t10.get('stale_over_floor'))}×){': ' + note if note else ''}")
                    if _same(mine, value):
                        why_parts.append(labelled(cited_path, res_stamp, warm.get("twin") or cited_model, body, "the same result"))
                        runs_mrad = (warm.get("t9") or {}).get("warm_runs_mrad") or {}
                        if gid == "T9" and runs_mrad:
                            try:
                                slug = slug_of(max(runs_mrad, key=runs_mrad.get))
                                link = f"{APP_URL}?d={dep_id}&run={slug}&why={sid}" if slug in by_slug else None
                            except ValueError:
                                pass
                    else:
                        earlier.append(labelled(cited_path, res_stamp, warm.get("twin"), body, f"an earlier result: {_fmt(mine)}× there"))
                # the newest warm file by date, when it is not the one the acceptance cites, is an earlier (or other) result: labelled
                if sid in sources["warm"] and sources["warm"][sid][0] != cited_path:
                    wpath, wstamp, warm = sources["warm"][sid]
                    w = warm.get(gid.lower()) or {}
                    mine = w.get("warm_over_floor") if gid == "T9" else w.get("restored_over_floor", (w.get("v2") or {}).get("restored_over_floor"))
                    if mine is not None and not _same(mine, value):
                        earlier.append(labelled(wpath, wstamp, warm.get("twin"), f"{gid} {_fmt(mine)}× (shown: {_fmt(value)}×)", "an earlier result"))
                if gid == "T9" and floors is None:
                    p9 = (pooled.get(sid) or {}).get("t9") or {}
                    sess = p9.get("sessions") or []
                    sess = [w for w in sess if w.get("session_floor_mrad") and w.get("pooled_floor_mrad")]
                    if sess:
                        # the worst session under the rule in force is the one the gate counted
                        floor_key = "pooled_floor_mrad" if floor_rule == "pooled" else "session_floor_mrad"
                        w = max(sess, key=lambda row: row["twin_mrad"] / row[floor_key])
                        a, b = w["twin_mrad"] / w["session_floor_mrad"], w["twin_mrad"] / w["pooled_floor_mrad"]
                        text = (f"worst warm session {Path(w.get('session', '')).name}: session floor {w['session_floor_mrad']:.2f} mrad: {a:.2f}× "
                                f"({'pass' if a <= 1.5 else 'fail'}) · pooled floor {w['pooled_floor_mrad']:.2f} mrad: {b:.2f}× ({'pass' if b <= 1.5 else 'fail'})")
                        if _same(b if floor_rule == "pooled" else a, value):
                            floors, session_pass, pooled_pass = labelled(pooled_path, pooled_stamp, None, text, "the same result"), a <= 1.5, b <= 1.5
                        else:
                            earlier.append(labelled(pooled_path, pooled_stamp, None, text, "an earlier result"))

            # the acceptance's own words when no result file explains the cell (T2's detail restates the headline: skipped)
            if not why_parts and gate.get("detail") and gid != "T2" and not str(gate["detail"]).startswith("/"):
                why_parts.append(gate["detail"])
            # the triage: older than the result for most cells, so its words carry their file, date and whether it saw this number
            if tri:
                same_tri = _same(tri.get("value"), value) or tri.get("value") == value
                tri_note = "the same result" if same_tri else f"written for an earlier result ({_fmt(tri.get('value'))} there, {_fmt(value)} shown)"
                if tri.get("status") != status:
                    evidence.append(f"the triage ({_stamp(triage_stamp)}) saw this cell as {tri.get('status')}; {acc_path.name} says {status}")
            else:
                evidence.append(f"not in the triage ({_stamp(triage_stamp)}): it predates this result")
            action = zach.get((sid, gid)) or tri.get("zach_action")
            closes = labelled(triage_path, triage_stamp, None, tri["what_closes_it"], tri_note) if tri.get("what_closes_it") else ""
            if tri.get("category") == "Zach" and action:
                nxt = f"blocked on Zach: {action}"
            elif tri.get("category") == "impossible as defined":
                nxt = f"impossible as defined: the gate needs redefining for this station (Zach's call). {closes}"
            elif tri.get("plan") and tri.get("status") == status:
                nxt = f"{tri.get('category')}: run {', '.join(Path(p).name for p in str(tri['plan']).split(' + '))}"
            elif tri.get("plan"):
                nxt = f"the planned run ({', '.join(Path(p).name for p in str(tri['plan']).split(' + '))}) has been run and the cell is now {status}: needs re-triage"
            elif closes:
                nxt = f"{tri.get('category')}{' (no rack time)' if tri.get('category') == 'modelling' else ''}: {closes}"
            else:
                nxt = "not triaged yet"
            flips = floors is not None and session_pass is not None and session_pass != pooled_pass
            if flips:
                # WHY name the rule in force (2026-11-04): the gates use bam_rack_twin's FLOOR_RULE, pooled by default since Zach's go-with-
                # the-default call; the other rule's verdict stays visible beside it
                floors += (f" — the verdict depends on the floor rule; the gates use the {floor_rule} floor"
                           + (" (the default since 2026-11-04; --floor-rule session switches back)" if floor_rule == "pooled" else ""))
            if status == "pass":
                if not flips:
                    continue  # a pass under both floor rules is not a failure to explain
                nxt = f"none needed under the {floor_rule} floor the gates use; it would fail under the {other_rule} floor"
                why_parts.insert(0, f"passes on the {floor_rule} floor the gates use; fails on the {other_rule} floor")
            measured = headline(gid, gate)
            # WHY the triage's words land in Why only when Next does not already carry them: each field says something different
            if not why_parts and closes and closes not in nxt:
                why_parts.append(closes)
            if not why_parts:
                why_parts.append(f"no evidence yet; the gate asks: {gate.get('target')}" if status == "not_run" else "the acceptance file gives no reason for this cell")
            why_text = "; ".join(x.strip().rstrip(".") for x in why_parts if x)
            ev_text = "; ".join(e for e in evidence if e) or None
            title = f"{gid} {GATE_NAMES[gid]}" if gid in GATE_NAMES else gid
            explain = (f"{title} — {status}: {measured}. Why: {why_text}. Model: {model}." + (f" Evidence: {ev_text}." if ev_text else "") + (f" Floor rules: {floors}." if floors else "")
                       + f" Next: {nxt}." + (f" Earlier: {' '.join(earlier)}." if earlier else ""))
            rows.append({"explain": explain, "rank": {"fail": 0, "partial": 1, "pass": 1, "not_run": 2}.get(status, 3), "station": sid, "device": f"CAN {can}", "gate_id": gid, "gate": f"{gid} {GATE_NAMES.get(gid, gate.get('name', ''))}",
                         "status": status, "measured": measured, "value": value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                         "statistic": [dict(j) for j in gate.get("judged") or []], "limit": gate.get("limit"), "rule": gate.get("target"),
                         "model": model, "result_file": str(cited_path) if cited_path else None,
                         "why": why_text, "evidence": ev_text, "floor_rules": floors, "next": nxt, "earlier": " ".join(earlier) or None,
                         "category": tri.get("category"), "blocked_on_zach": nxt.startswith("blocked on Zach"),
                         "page": link, "order": int(can) * 100 + int(gid[1:]), "source": f"{acc_path.name} ({acc_stamp})"})
    rows.sort(key=lambda r: ({"fail": 0, "partial": 1, "pass": 2, "not_run": 3}.get(r["status"], 4), int(r["device"].split()[1]), int(r["gate_id"][1:])))
    return rows


# ---------------------------------------------------------------------------------------------------- one deployment


def build_deployment(entry: dict, replays: dict) -> dict:
    started_at = time.perf_counter()
    dep_id = entry["id"]
    dep_dir = DATA / dep_id
    if dep_dir.exists():
        shutil.rmtree(dep_dir)
    (dep_dir / "runs").mkdir(parents=True)
    record = json.loads(Path(entry["record"]).read_text())
    by_device = stations(record)
    envelopes = replays.get("__envelopes__", {})
    floors = json.loads(FLOORS_1024.read_text()) if FLOORS_1024.is_file() else {}

    # every real run, oldest first while we read
    found = []
    for day in entry["archive"]:
        day = Path(day)
        for path in sorted(day.rglob("*.npz")):
            loaded = load_run(path)
            if loaded is not None:
                found.append((path, loaded))
    total_seconds = sum(float(l["arrays"]["t"][-1] - l["arrays"]["t"][0]) for _, l in found)
    hz = COVER_HZ
    while total_seconds * hz > COVER_BUDGET * 0.93 and hz > 1:  # leave room for the w = 0 extremes
        hz /= 1.25

    runs, coverage, run_gate_rows, run_rows = [], [], [], []
    for path, loaded in found:
        meta, arrays = loaded["meta"], loaded["arrays"]
        device = f"CAN {meta['can_id']}"
        rel = path.relative_to(Path(entry["archive"][0]).parent).with_suffix("")
        slug = str(rel).removeprefix("rack_").replace("/", "~")
        session = "/".join(p for p in rel.parts[1:-1] if p != "runs")
        wall = arrays.get("wall")
        wall_s = float(wall[0]) if wall is not None and np.isfinite(wall[0]) else None
        started = dt.datetime.fromtimestamp(wall_s, tz=TZ) if wall_s else dt.datetime.fromtimestamp(path.stat().st_mtime, tz=TZ)
        day = started.date().isoformat()  # WHY the wall clock: the 10-29 calibration sessions sit in the rack_2026-10-28 folder
        kind = meta.get("kind") or (meta.get("args") or {}).get("kind") or "?"
        args = meta.get("args") or {}
        gains = gains_at(by_device.get(device, {}), started.astimezone(dt.timezone.utc) if wall_s else None)
        kp_scale = float(args.get("kp_scale_cmd", args.get("kp_scale", 1.0)) or 1.0)
        kd_scale = float(args.get("kd_scale_cmd", args.get("kd_scale", 1.0)) or 1.0)
        # WHY ilimit x the command's scale (bam_rack_twin followup_1029.py): CAN 11's il0.25 / il0.5 sessions ran on board ilimit 0.8
        # with ilimit_scale 0.3125 / 0.625; the integral saw 0.25 / 0.5 N.m. A run with no scale argument used the board's limit.
        il_scale = args.get("ilimit_scale_cmd", args.get("ilimit_scale"))
        il_eff = None if gains["ilimit"] is None else gains["ilimit"] * (1.0 if il_scale is None else float(il_scale))
        replay = replays.get(str(path))
        if replay is not None:
            situations = model_situations(replay)
            real_s = situations[0]
            # WHY the page clock's offset: the 10-28 T2 replays start at the tape (prelude dropped); the calibration round's replays and
            # every unreplayed run start at the npz's first row, so a window on the tape clock is t + prelude there
            whole = replay.get("round") is not None or replay.get("origin") == "rack_replays"
            clock_offset = float(replay.get("prelude_s") or meta.get("prelude_s") or 0.0) if whole and replay.get("origin") != "rack_replays" else 0.0
            if real_s.get("i_q") is None:  # twin_replays carries no current or temperature: take them from the npz (prelude dropped if the replay did)
                keep = np.ones(arrays["t"].size, bool) if whole else (arrays["t"] - arrays["t"][0]) >= float(replay.get("prelude_s") or 0.0) - 1e-9
                for key, column in (("i_q", "i_q"), ("temp", "temp_c")):
                    if column in arrays and int(keep.sum()) == real_s["t"].size:
                        real_s[key] = arrays[column][keep]
            floor = replay.get("floor_mrad") or (floors.get(str(meta["can_id"]), {}) or {}).get("floor_mrad")
        else:
            situations = situations_for(loaded)
            floor = None
            clock_offset = float(meta.get("prelude_s") or 0.0)
        names = [s["situation"] for s in situations]
        models = [s["situation"] for s in situations if s["source"] == "sim"]
        title = f"{session} · {path.stem}"
        # WHY a run set (2026-11-05): a schedule session's runs carry their schedule stamp (bam_rack_twin.hardware.session); they are one
        # set to read together (one frozen schedule, one mode, one sitting), so the runs table groups and filters by it
        stamp = meta.get("schedule") or {}
        run_set = (f"{device} · schedule {str(stamp['digest'])[:8]} · {stamp.get('mode')} · {Path(session).name}" if stamp.get("digest")
                   else session)
        if stamp.get("run"):
            title += f" · {stamp['run']}"
        url = f"{APP_URL}?d={dep_id}&run={slug}"
        t = arrays["t"]
        row = {
            "run": slug, "title": title, "started": started.isoformat(timespec="seconds"), "day": day, "session": session, "device": device,
            "kind": kind, "class": (replay or {}).get("class"), "duration_s": num(t[-1] - t[0], 4), "samples": int(t.size),
            "rate_hz": num(1.0 / float(np.median(np.diff(t))), 4) if t.size > 1 else None,
            "display_hz": num(min(1.0 / float(np.median(np.diff(t))), MAX_DISPLAY_HZ) / max(1, math.ceil((1.0 / float(np.median(np.diff(t)))) / MAX_DISPLAY_HZ - 1e-9)), 4) if t.size > 1 else None,
            "kp": num((gains["kp"] or 0) * kp_scale, 4) if gains["kp"] is not None else None, "ki": gains["ki"],
            "kd": num((gains["kd"] or 0) * kd_scale, 4) if gains["kd"] is not None else None, "ilimit": num(il_eff, 4),
            "gains": (f"kp {num(gains['kp'], 4):g} · ki {num(gains['ki'], 4):g} · kd {num(gains['kd'], 4):g}" if None not in (gains["kp"], gains["ki"], gains["kd"]) else "unknown")
                     + (f" · il {num(il_eff, 3):g}" if il_eff is not None and gains["ki"] else "")
                     + (f" (×{kp_scale:g} / ×{kd_scale:g})" if (kp_scale, kd_scale) != (1.0, 1.0) else ""),
            "situations": names, "models": len(models),
            "compare": f"real + {len(models)} model{'s' if len(models) != 1 else ''}" if models else ("real vs target" if TARGET in names else "real only"),
            "page": url, "url": url, "npz": str(path), "basis": "real", "round": (replay or {}).get("round"),
            "deployment": dep_id, "devices": [device], "label": title,
            "clock_offset_s": num(clock_offset, 6),
            "run_set": run_set, "split": stamp.get("split"), "schedule_run": stamp.get("run"),
        }
        diagnostics = run_diagnostics(dep_id, slug, title, device, situations, arrays, floor)
        tracking = next((d for d in diagnostics if d["diagnostic"] == "stock.tracking_error"), None)
        row["tracking_mrad"] = num(tracking["value"], 4) if tracking and tracking["value"] is not None else None
        best = min((d for d in diagnostics if d["diagnostic"] == "stock.model_error" and d["value"] is not None), key=lambda d: d["value"], default=None)
        row["best_model"] = best["title"].removesuffix(" vs real") if best else None
        row["best_model_mrad"] = num(best["value"], 4) if best else None
        # WHY the best model's verdict: the question a run answers is "does any model twin it?"; each model's own verdict is in run_gates
        row["verdict"] = best["verdict"] if best else "not_run"
        runs.append(row)
        run_gate_rows += diagnostics

        run_dir = dep_dir / "runs" / slug
        src = f"{path} (bam_rack_twin.hardware)" + (f"; models: {replay['source_file']}" if replay else "")
        samples = sample_rows(situations, device, slug)
        poses = pose_rows(samples, device)
        d_samples, d_poses = diff_tables(samples, poses)
        pose_errors(poses, d_poses)
        write_contract(run_dir / "samples.json", "samples", samples, f"Samples · {title}", src, SAMPLE_HINTS)
        write_contract(run_dir / "poses.json", "poses", poses, f"Output link · {title}", src + "; the joint's own frame, orientation about z", POSE_HINTS)
        write_contract(run_dir / "diff_samples.json", "diff_samples", d_samples, f"Differences · {title}", src + "; difference(a, b), tools/trajectory.py (data-ui fixture)", SAMPLE_HINTS)
        write_contract(run_dir / "diff_poses.json", "diff_poses", d_poses, f"Output link differences · {title}", src + "; difference(a, b), tools/trajectory.py")
        write(run_dir / "diagnostics.json", f"Diagnostics · {title}", "robotdx.diagnostics (io-diagnostics), computed from this run", DX_PROPS, diagnostics)
        run_rows.append((run_dir / "run.json", title, src, row))
        coverage += coverage_rows(loaded, slug, device, kind, day, hz)

    runs.sort(key=lambda r: r["started"], reverse=True)  # newest first, as written: the table's sort says it too
    for run_path, title, src, row in run_rows:  # after every row is complete (verdicts), one runs.json row per run page
        write_contract(run_path, "runs", [row], f"Run · {title}", src, RUN_HINTS)
    counts = Counter(r["device"] for r in runs)
    devices = []
    for device, component in sorted(by_device.items(), key=lambda kv: int(kv[0].split()[1])):
        env = envelopes.get(device, {})
        devices.append({"device": device, "station": component.get("station"), "type": "servo", "runs": counts.get(device, 0),
                        "label": f"{device} · {component.get('station')}", "parent": dep_id, "order": int(device.split()[1]),
                        "q_min_deg": num(math.degrees(env["q_min_rad"]), 4) if env.get("q_min_rad") is not None else None,
                        "q_max_deg": num(math.degrees(env["q_max_rad"]), 4) if env.get("q_max_rad") is not None else None,
                        "qd_max_deg_s": num(math.degrees(env["qd_max_rad_s"]), 4) if env.get("qd_max_rad_s") is not None else None,
                        "kp": component.get("moteus_config", {}).get("kp"), "ki": component.get("moteus_config", {}).get("ki"),
                        "kd": component.get("moteus_config", {}).get("kd")})
    # WHY a per-row opacity (Codex audit 2026-10-29, "draw all of the runs with 1/n opacity"): data-ui's chart draws a row's opacity
    # column but runs no Vega-Lite transform on its large-data path, so n cannot be counted in the page; the producer writes it. n is
    # the station's runs (the joint panels show one station) or every run (Angle over time), exactly 1/n with no floor (Codex audit
    # round 2: the 0.04 floor contradicted the page's "1/n"; data-ui 006e9d5's opacity: auto is exact 1/n too). Past ~200 runs an
    # 8-bit canvas draws a lone path as nothing (data-ui's README; CAN 13 at 1/337: 0 blue pixels), so only overlaps show: the Runs
    # per cell voxels are the readable count there, and the page says so. A rail filter does not recount n: a listed data-ui gap.
    per_station = Counter(r["device"] for r in runs)
    for row in coverage:
        row["path_opacity"] = num(1.0 / max(per_station.get(row["device"], 1), 1), 4)
        row["path_opacity_all"] = num(1.0 / max(len(runs), 1), 4)
    # the workspace as a closed outline in the same (q, qd) columns: one path per station, drawn grey by the `layer` column
    # (w = 0, so histograms that sum w never count it; the box plots filter it out)
    for d in devices:
        if None in (d["q_min_deg"], d["q_max_deg"], d["qd_max_deg_s"]):
            continue
        corners = [(d["q_min_deg"], -d["qd_max_deg_s"]), (d["q_max_deg"], -d["qd_max_deg_s"]), (d["q_max_deg"], d["qd_max_deg_s"]),
                   (d["q_min_deg"], d["qd_max_deg_s"]), (d["q_min_deg"], -d["qd_max_deg_s"])]
        for i, (q, qd) in enumerate(corners):
            coverage.append({"run": f"workspace · {d['device']}", "device": d["device"], "kind": "workspace", "day": None, "t": float(i), "w": 0,
                             "q_deg": q, "qd_deg_s": qd, "qdd_deg_s2": None, "tau_nm": None, "layer": "workspace", "path_opacity": 1.0, "path_opacity_all": 1.0})
    _, diagnostics, matrix = deployment_gates(dep_dir)
    sources = evidence_sources(entry)
    entry = {**entry, "why": str(sources["why"][0] or entry.get("why"))}
    cells = acceptance_cells(sources["acceptance"][0])
    t2_rows, caveats = why(entry, dep_id, runs, rules_in_force(sources["acceptance"][0])[1])
    why_rows = failed_cells(entry, dep_id, runs, sources, t2_rows)
    write(dep_dir / "why.json", f"Why it fails · {entry['title']}", f"one row per failed, partial or unrun gate cell of {sources['acceptance'][0]}; "
          f"reasons from {sources['why'][0]}, {sources['triage'][0]}, warm*_scored.json, {sources['floors_pooled'][0]}", WHY_PROPS, why_rows)
    write(dep_dir / "why_t2.json", f"T2 by station · {entry['title']}", f"{entry['why']}", WHY_PROPS, t2_rows)
    passing_now = sum(1 for c in cells if c["verdict"] == "pass")
    write(dep_dir / "evidence.json", f"Evidence files · {entry['title']}", "the newest of each kind, found by its own date (tools/build_app.py newest())", {},
          [{"kind": kind, "file": str(path), "dated": stamp, "note": (f"{passing_now} of {len(cells)} gate cells pass" if kind == "acceptance" else None)}
           for kind, (path, stamp) in ((k, sources[k]) for k in ("acceptance", "why", "triage", "floors_pooled")) if path]
          + [{"kind": f"warm T9 · {sid}", "file": str(p), "dated": st, "note": None} for sid, (p, st, _) in sorted(sources["warm"].items())])
    write(dep_dir / "caveats.json", f"Caveats · {entry['title']}", f"derived from {entry['scored']} and {entry['earlier_floors']}", {}, caveats)
    write_decompositions(dep_dir, entry)
    stamp = now()
    source = f"{', '.join(entry['archive'])} (real runs, bam_rack_twin.hardware); built {stamp} by tools/build_app.py"
    write_contract(dep_dir / "runs.json", "runs", runs, f"Runs · {entry['title']}", source, RUN_HINTS)
    write(dep_dir / "coverage.json", f"Coverage · {entry['title']}", source + f"; every run at {hz:.3g} Hz (w = 1) plus each run's argmin/argmax rows (w = 0)",
          COVER_PROPS, coverage, display_hz=hz)
    write_contract(dep_dir / "devices.json", "devices", devices, f"Stations · {entry['title']}", f"{entry['record']}; windows from bam_rack_twin TAPE_STATIONS",
                   {"station": {}, "runs": {"type": "integer"}, "kp": {"type": "number", "unit": "board"}, "ki": {"type": "number", "unit": "board"},
                    "kd": {"type": "number", "unit": "board"}})
    write(dep_dir / "gates.json", f"Gate matrix · {entry['title']}", "robotdx.diagnostics via tools/diagnostics_run_rack.py", GATE_PROPS, cells)
    write(dep_dir / "diagnostics.json", f"Diagnostics · {entry['title']}", "robotdx.diagnostics via tools/diagnostics_run_rack.py (PEP 0010 §10 rows)", DX_PROPS, diagnostics)
    write(dep_dir / "run_gates.json", f"Run diagnostics · {entry['title']}", "robotdx.diagnostics, computed per run by tools/build_app.py", DX_PROPS, run_gate_rows)
    passing = sum(1 for c in cells if c["verdict"] == "pass")
    days = sorted({r["day"] for r in runs})
    summary = {
        "id": dep_id, "title": entry["title"], "kind": entry["kind"], "family": entry.get("family"), "where": entry.get("where"), "summary": entry.get("summary"),
        "stations": len(devices), "runs": len(runs), "runs_with_models": sum(1 for r in runs if r["models"]),
        "hours": num(sum(r["duration_s"] or 0 for r in runs) / 3600.0, 3), "samples": sum(r["samples"] for r in runs),
        "days": len(days), "first_run": runs[-1]["started"] if runs else None, "last_run": runs[0]["started"] if runs else None,
        "gate_cells": len(cells), "gate_cells_passing": passing, "gates_passing": num(passing / len(cells), 3) if cells else None,
        "gate_summary": f"{passing} of {len(cells)} cells pass", "gates_source": f"{sources['acceptance'][0].name} ({sources['acceptance'][1]})", "page": f"{APP_URL}?d={dep_id}", "basis": "real",
    }
    print(f"{dep_id}: {len(runs)} runs ({summary['runs_with_models']} with models), {len(coverage)} coverage rows at {hz:.3g} Hz, "
          f"{len(run_gate_rows)} run diagnostics, gates {passing}/{len(cells)}; {time.perf_counter() - started_at:.0f} s")
    return summary


# ---------------------------------------------------------------------------------------------------- column declarations

SOURCE_SLOT = {"real": 1, "sim": 2, "target": 0}  # data-ui badge slots: 1 blue = real, 2 orange = sim, 0 muted = target
VERDICT_SLOT = {"pass": 3, "warn": 4, "partial": 4, "fail": 8, "not_run": 0}  # green and red mean pass/fail only
# WHY every kind muted: an unlisted badge value gets a hashed slot, and "waypoints" landed on green, which means pass here
KIND_SLOT = {kind: 0 for kind in ("waypoints", "sine", "tape", "gravity", "friction", "chirp", "hardstop", "thermal", "staircase", "impact", "samples", "?")}
SAMPLE_PROPS = {"t": {"unit": "s", "digits": 4}, "q_deg": {"unit": "°", "digits": 5}, "qd_deg_s": {"unit": "°/s", "digits": 4},
                "qdd_deg_s2": {"unit": "°/s²", "digits": 4, "note": "derived: a 5-sample moving mean of qd, then central differences (the board logs no qdd)"},
                "tau_nm": {"unit": "N·m", "digits": 4}, "i_q_a": {"unit": "A", "digits": 4}, "temp_c": {"unit": "°C", "digits": 3},
                "v_bus_v": {"unit": "V", "digits": 3}, "source": {"display": "badge", "colors": SOURCE_SLOT}}
DIFF_PROPS = {"t": {"unit": "s", "digits": 4}, "e_q_mrad": {"unit": "mrad", "digits": 4, "note": "reference − situation at the situation's own sample times"},
              "source": {"display": "badge", "colors": SOURCE_SLOT}}
SAMPLE_HINTS = {"source": {"display": "badge", "colors": {"real": 1, "sim": 2, "target": 0}}}
RUN_PROPS = {"started": {"type": "datetime"}, "duration_s": {"unit": "s", "digits": 3}, "rate_hz": {"unit": "Hz", "digits": 3},
             "tracking_mrad": {"unit": "mrad", "digits": 3, "note": "RMS(real − target), robotdx stock.tracking_error"},
             "best_model_mrad": {"unit": "mrad", "digits": 3, "note": "the closest model's RMS(real − model)"},
             "verdict": {"display": "badge", "colors": VERDICT_SLOT, "note": "the closest model's whole-run RMS against 1.5x the station's floor (not the T2 moves/holds split); not_run = no model played this run"},
             "page": {"display": "link"}, "kind": {"display": "badge", "colors": KIND_SLOT}, "basis": {"display": "badge", "colors": {"real": 1}}}
COVER_PROPS = {"t": {"unit": "s"}, "q_deg": {"unit": "°"}, "qd_deg_s": {"unit": "°/s"}, "qdd_deg_s2": {"unit": "°/s²"}, "tau_nm": {"unit": "N·m"},
               "w": {"note": "1 = a grid row (counts are time spent); 0 = a run's argmin/argmax row (kept for exact min/max)"},
               "q_lo_deg": {"unit": "°"}, "q_hi_deg": {"unit": "°"}, "qd_hi_deg_s": {"unit": "°/s"}, "qd_lo_deg_s": {"unit": "°/s"}}
# runs.json: the contract's columns plus the app's own (title, gains, verdicts, the page link), each declared with its unit
RUN_HINTS = {"title": {}, "day": {}, "session": {}, "device": {}, "class": {}, "samples": {"type": "integer"}, "kp": {"type": "number", "unit": "board"},
             "ki": {"type": "number", "unit": "board"}, "kd": {"type": "number", "unit": "board"}, "ilimit": {"type": "number", "unit": "N·m"},
             "gains": {}, "models": {"type": "integer"}, "compare": {}, "page": {"display": "link"}, "npz": {}, "round": {},
             "clock_offset_s": {"type": "number", "unit": "s"},
             "run_set": {"note": "a schedule session's runs (station, schedule digest, mode, session); else the session folder"},
             "split": {"note": "the run's schedule split: floor, train or held_out (blank for a run recorded before schedule stamps)"},
             "schedule_run": {},
             "tracking_mrad": {"type": "number", "unit": "mrad", "digits": 3, "note": "RMS(real − target), robotdx stock.tracking_error"},
             "best_model": {}, "best_model_mrad": {"type": "number", "unit": "mrad", "digits": 3, "note": "the closest model's RMS(real − model)"},
             "verdict": {"display": "badge", "colors": {"pass": 3, "warn": 4, "partial": 4, "fail": 8, "not_run": 0},
                         "note": "the closest model's whole-run RMS against 1.5x the station's floor (not the T2 moves/holds split); not_run = no model played this run"},
             "kind": {"display": "badge", "colors": {k: 0 for k in ("waypoints", "sine", "tape", "gravity", "friction", "chirp", "hardstop", "thermal", "staircase", "impact", "samples", "?")}},
             "basis": {"display": "badge", "colors": {"real": 1}}, "duration_s": {"digits": 3}, "rate_hz": {"digits": 3}}
DEVICE_PROPS = {"q_min_deg": {"unit": "°"}, "q_max_deg": {"unit": "°"}, "qd_max_deg_s": {"unit": "°/s"}}
GATE_PROPS = {"verdict": {"display": "badge", "colors": VERDICT_SLOT}}
WHY_PROPS = {"status": {"display": "badge", "colors": VERDICT_SLOT}, "blocked_on_zach": {"type": "checkbox"}, "moves_x": {"unit": "×", "digits": 3}, "hold_x": {"unit": "×", "digits": 3},
             "gate_x": {"unit": "×"}, "moves_before_x": {"unit": "×", "digits": 3}, "hold_before_x": {"unit": "×", "digits": 3},
             "evidence_share": {"digits": 3, "note": "unique R²: the share of the held-out torque gap (rack − twin) this term family explains on its own"},
             "floor_growth_x": {"unit": "×", "digits": 3, "note": "the new day's T1 floor ÷ the 10-24 floor: above 1 makes every × floor ratio look better"},
             "overfit_pick": {"note": "the calibrated twin won identification but lost on the held-out tapes"}, "page": {"display": "link"}}
DX_PROPS = {"verdict": {"display": "badge", "colors": VERDICT_SLOT}, "evidence": {"display": "link"}, "value": {"digits": 4}, "warn_hi": {"digits": 4}, "error_hi": {"digits": 4}}
DEP_PROPS = {"first_run": {"type": "datetime"}, "last_run": {"type": "datetime"}, "hours": {"unit": "h", "digits": 3}, "page": {"display": "link"},
             "gates_passing": {"digits": 3}, "basis": {"display": "badge", "colors": {"real": 1}}}


def main() -> int:
    registry = json.loads(REGISTRY.read_text())
    replays = replays_by_path()
    summaries = [build_deployment(entry, replays) for entry in registry["deployments"]]
    write(DATA / "deployments.json", "Deployments", f"app/registry.json; built {now()}", DEP_PROPS, summaries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
