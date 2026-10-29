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
  <dep>/runs/<slug>/samples.json         t x situation rows: real, target and every model, display units (PEP 0010 §4)
  <dep>/runs/<slug>/diff.json            difference(a, b) rows: each model against real, real against target
  <dep>/runs/<slug>/diagnostics.json     that run's diagnostic rows
  <dep>/runs/<slug>/run.json             that run's one runs.json row (the run page's header)
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
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
from robotdx.diagnostics.data import Trajectory, difference
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


def sample_rows(situations: list[dict], device: str) -> list[dict]:
    rows = []
    for s in situations:
        t = s["t"]
        qdd = accel(t, s["qd"]) if s.get("qd") is not None else None
        for i in picks(t):
            row = {"t": num(t[i], 6), "situation": s["situation"], "source": s["source"], "device": device, "q_deg": deg(s["q"], i),
                   "qd_deg_s": deg(s["qd"], i) if s.get("qd") is not None else None, "qdd_deg_s2": deg(qdd, i) if qdd is not None else None}
            for key, column in (("tau", "tau_nm"), ("i_q", "i_q_a"), ("temp", "temp_c"), ("v", "v_bus_v")):
                if s.get(key) is not None:
                    row[column] = num(s[key][i], 5)
            rows.append(row)
    return rows


def diff_rows(situations: list[dict], device: str) -> list[dict]:
    """difference(a, b) (PEP 0010 §4.4, robotdx.diagnostics.data.difference): b(t_i) - a(t_i) on a's own samples, never
    extrapolated. Pairs: each model against real (a = model, b = real), and real against the target (a = real, b = target)."""

    by = {s["situation"]: s for s in situations}
    pairs = [(name, REAL) for name, s in by.items() if s["source"] == "sim"]
    if TARGET in by:
        pairs.append((REAL, TARGET))
    rows = []
    for a_name, b_name in pairs:
        a, b = by[a_name], by[b_name]
        good_a, good_b = np.isfinite(a["q"]), np.isfinite(b["q"])
        if good_a.sum() < 2 or good_b.sum() < 2:
            continue
        t, e = difference((a["t"][good_a], a["q"][good_a]), (b["t"][good_b], b["q"][good_b]))
        index = picks(t) if t.size else []
        for i in index:
            rows.append({"t": num(t[i], 6), "situation": a_name, "reference": b_name, "pair": f"{a_name} vs {b_name}",
                         "source": a["source"], "device": device, "e_q_mrad": num(1e3 * e[i], 5)})
    return rows


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

    runs, coverage, run_gate_rows = [], [], []
    for path, loaded in found:
        meta, arrays = loaded["meta"], loaded["arrays"]
        device = f"CAN {meta['can_id']}"
        rel = path.relative_to(Path(entry["archive"][0]).parent).with_suffix("")
        slug = str(rel).removeprefix("rack_").replace("/", "~")
        day = rel.parts[0].removeprefix("rack_")
        session = "/".join(p for p in rel.parts[1:-1] if p != "runs")
        wall = arrays.get("wall")
        wall_s = float(wall[0]) if wall is not None and np.isfinite(wall[0]) else None
        started = dt.datetime.fromtimestamp(wall_s, tz=TZ) if wall_s else dt.datetime.fromtimestamp(path.stat().st_mtime, tz=TZ)
        kind = meta.get("kind") or (meta.get("args") or {}).get("kind") or "?"
        args = meta.get("args") or {}
        gains = gains_at(by_device.get(device, {}), started.astimezone(dt.timezone.utc) if wall_s else None)
        kp_scale = float(args.get("kp_scale_cmd", args.get("kp_scale", 1.0)) or 1.0)
        kd_scale = float(args.get("kd_scale_cmd", args.get("kd_scale", 1.0)) or 1.0)
        replay = replays.get(str(path))
        if replay is not None:
            situations = model_situations(replay)
            real_s = situations[0]
            if real_s.get("i_q") is None:  # twin_replays carries no current or temperature: take them from the npz, prelude dropped
                keep = (arrays["t"] - arrays["t"][0]) >= float(replay.get("prelude_s") or 0.0) - 1e-9
                for key, column in (("i_q", "i_q"), ("temp", "temp_c")):
                    if column in arrays and int(keep.sum()) == real_s["t"].size:
                        real_s[key] = arrays[column][keep]
            floor = replay.get("floor_mrad") or (floors.get(str(meta["can_id"]), {}) or {}).get("floor_mrad")
        else:
            situations = situations_for(loaded)
            floor = None
        names = [s["situation"] for s in situations]
        models = [s["situation"] for s in situations if s["source"] == "sim"]
        title = f"{session} · {path.stem}"
        url = f"{APP_URL}?d={dep_id}&run={slug}"
        t = arrays["t"]
        row = {
            "run": slug, "title": title, "started": started.isoformat(timespec="seconds"), "day": day, "session": session, "device": device,
            "kind": kind, "class": (replay or {}).get("class"), "duration_s": num(t[-1] - t[0], 4), "samples": int(t.size),
            "rate_hz": num(1.0 / float(np.median(np.diff(t))), 4) if t.size > 1 else None,
            "kp": num((gains["kp"] or 0) * kp_scale, 4) if gains["kp"] is not None else None, "ki": gains["ki"],
            "kd": num((gains["kd"] or 0) * kd_scale, 4) if gains["kd"] is not None else None, "ilimit": gains["ilimit"],
            "gains": (f"kp {num(gains['kp'], 4):g} · ki {num(gains['ki'], 4):g} · kd {num(gains['kd'], 4):g}" if None not in (gains["kp"], gains["ki"], gains["kd"]) else "unknown")
                     + (f" (×{kp_scale:g} / ×{kd_scale:g})" if (kp_scale, kd_scale) != (1.0, 1.0) else ""),
            "situations": names, "models": len(models),
            "compare": f"real + {len(models)} model{'s' if len(models) != 1 else ''}" if models else ("real vs target" if TARGET in names else "real only"),
            "page": url, "npz": str(path), "basis": "real",
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
        write(run_dir / "samples.json", f"Samples · {title}", src, SAMPLE_PROPS, sample_rows(situations, device))
        write(run_dir / "diff.json", f"Differences · {title}", src + "; difference(a, b), robotdx.diagnostics.data", DIFF_PROPS, diff_rows(situations, device))
        write(run_dir / "diagnostics.json", f"Diagnostics · {title}", "robotdx.diagnostics (io-diagnostics), computed from this run", DX_PROPS, diagnostics)
        write(run_dir / "run.json", f"Run · {title}", src, RUN_PROPS, [row])
        coverage += coverage_rows(loaded, slug, device, kind, day, hz)

    runs.sort(key=lambda r: r["started"], reverse=True)  # newest first, as written: the table's sort says it too
    counts = Counter(r["device"] for r in runs)
    devices = []
    for device, component in sorted(by_device.items(), key=lambda kv: int(kv[0].split()[1])):
        env = envelopes.get(device, {})
        devices.append({"device": device, "station": component.get("station"), "type": "servo", "runs": counts.get(device, 0),
                        "q_min_deg": num(math.degrees(env["q_min_rad"]), 4) if env.get("q_min_rad") is not None else None,
                        "q_max_deg": num(math.degrees(env["q_max_rad"]), 4) if env.get("q_max_rad") is not None else None,
                        "qd_max_deg_s": num(math.degrees(env["qd_max_rad_s"]), 4) if env.get("qd_max_rad_s") is not None else None,
                        "kp": component.get("moteus_config", {}).get("kp"), "ki": component.get("moteus_config", {}).get("ki"),
                        "kd": component.get("moteus_config", {}).get("kd")})
    # the workspace as a closed outline in the same (q, qd) columns: one path per station, drawn grey by the `layer` column
    # (w = 0, so histograms that sum w never count it; the box plots filter it out)
    for d in devices:
        if None in (d["q_min_deg"], d["q_max_deg"], d["qd_max_deg_s"]):
            continue
        corners = [(d["q_min_deg"], -d["qd_max_deg_s"]), (d["q_max_deg"], -d["qd_max_deg_s"]), (d["q_max_deg"], d["qd_max_deg_s"]),
                   (d["q_min_deg"], d["qd_max_deg_s"]), (d["q_min_deg"], -d["qd_max_deg_s"])]
        for i, (q, qd) in enumerate(corners):
            coverage.append({"run": f"workspace · {d['device']}", "device": d["device"], "kind": "workspace", "day": None, "t": float(i), "w": 0,
                             "q_deg": q, "qd_deg_s": qd, "qdd_deg_s2": None, "tau_nm": None, "layer": "workspace"})
    cells, diagnostics, matrix = deployment_gates(dep_dir)
    stamp = now()
    source = f"{', '.join(entry['archive'])} (real runs, bam_rack_twin.hardware); built {stamp} by tools/build_app.py"
    write(dep_dir / "runs.json", f"Runs · {entry['title']}", source, RUN_PROPS, runs)
    write(dep_dir / "coverage.json", f"Coverage · {entry['title']}", source + f"; every run at {hz:.3g} Hz (w = 1) plus each run's argmin/argmax rows (w = 0)",
          COVER_PROPS, coverage, display_hz=hz)
    write(dep_dir / "devices.json", f"Stations · {entry['title']}", f"{entry['record']}; windows from bam_rack_twin TAPE_STATIONS", DEVICE_PROPS, devices)
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
        "gate_summary": matrix.get("message"), "page": f"{APP_URL}?d={dep_id}", "basis": "real",
    }
    print(f"{dep_id}: {len(runs)} runs ({summary['runs_with_models']} with models), {len(coverage)} coverage rows at {hz:.3g} Hz, "
          f"{len(run_gate_rows)} run diagnostics, gates {passing}/{len(cells)}; {time.perf_counter() - started_at:.0f} s")
    return summary


# ---------------------------------------------------------------------------------------------------- column declarations

SOURCE_SLOT = {"real": 1, "sim": 2, "target": 0}  # data-ui badge slots: 1 blue = real, 2 orange = sim, 0 muted = target
VERDICT_SLOT = {"pass": 3, "warn": 4, "fail": 8, "not_run": 0}  # green and red mean pass/fail only
# WHY every kind muted: an unlisted badge value gets a hashed slot, and "waypoints" landed on green, which means pass here
KIND_SLOT = {kind: 0 for kind in ("waypoints", "sine", "tape", "gravity", "friction", "chirp", "hardstop", "thermal", "staircase", "impact", "?")}
SAMPLE_PROPS = {"t": {"unit": "s", "digits": 4}, "q_deg": {"unit": "°", "digits": 5}, "qd_deg_s": {"unit": "°/s", "digits": 4},
                "qdd_deg_s2": {"unit": "°/s²", "digits": 4, "note": "derived: a 5-sample moving mean of qd, then central differences (the board logs no qdd)"},
                "tau_nm": {"unit": "N·m", "digits": 4}, "i_q_a": {"unit": "A", "digits": 4}, "temp_c": {"unit": "°C", "digits": 3},
                "v_bus_v": {"unit": "V", "digits": 3}, "source": {"display": "badge", "colors": SOURCE_SLOT}}
DIFF_PROPS = {"t": {"unit": "s", "digits": 4}, "e_q_mrad": {"unit": "mrad", "digits": 4, "note": "reference − situation at the situation's own sample times"},
              "source": {"display": "badge", "colors": SOURCE_SLOT}}
RUN_PROPS = {"started": {"type": "datetime"}, "duration_s": {"unit": "s", "digits": 3}, "rate_hz": {"unit": "Hz", "digits": 3},
             "tracking_mrad": {"unit": "mrad", "digits": 3, "note": "RMS(real − target), robotdx stock.tracking_error"},
             "best_model_mrad": {"unit": "mrad", "digits": 3, "note": "the closest model's RMS(real − model)"},
             "verdict": {"display": "badge", "colors": VERDICT_SLOT, "note": "the closest model's whole-run RMS against 1.5x the station's floor (not the T2 moves/holds split); not_run = no model played this run"},
             "page": {"display": "link"}, "kind": {"display": "badge", "colors": KIND_SLOT}, "basis": {"display": "badge", "colors": {"real": 1}}}
COVER_PROPS = {"t": {"unit": "s"}, "q_deg": {"unit": "°"}, "qd_deg_s": {"unit": "°/s"}, "qdd_deg_s2": {"unit": "°/s²"}, "tau_nm": {"unit": "N·m"},
               "w": {"note": "1 = a grid row (counts are time spent); 0 = a run's argmin/argmax row (kept for exact min/max)"},
               "q_lo_deg": {"unit": "°"}, "q_hi_deg": {"unit": "°"}, "qd_hi_deg_s": {"unit": "°/s"}, "qd_lo_deg_s": {"unit": "°/s"}}
DEVICE_PROPS = {"q_min_deg": {"unit": "°"}, "q_max_deg": {"unit": "°"}, "qd_max_deg_s": {"unit": "°/s"}}
GATE_PROPS = {"verdict": {"display": "badge", "colors": VERDICT_SLOT}}
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
