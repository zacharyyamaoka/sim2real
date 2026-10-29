"""sim2real's trajectory tables (data-ui robotics CONTRACT.md v1, §32): rows with unit-suffixed columns, difference(a, b),
and the check of a table against the contract's schemas.

    from trajectory import difference_samples, difference_poses, contract_table, validate

numpy only (no scipy, no data-ui import at runtime besides reading the vendored schema JSON). Pinned by
app/tests/test_trajectory_contract.py against data-ui's fixture (gallery/robotics/fixtures/difference, seed 20261029).

WHY sim2real computes difference itself: the contract's rule (CONTRACT.md §5) is one row per sample of a inside b's span
[first t, last t], both ends included; outside it no row. np.interp would hold b's end values and add rows (traj_compare
as landed wrote 18 such rows). b at one of its own samples is b's values exactly; between samples linear for every
numeric channel and slerp the short way for orientations; a null on either side is null.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[1]
ROBOTICS = REPO / "vendor" / "data-ui" / "gallery" / "robotics"
SCHEMAS = ROBOTICS / "schemas"
SOURCES = ("real", "sim", "target")
DEG_TO_MRAD = math.pi / 180.0 * 1000.0
# sample channels difference() writes as e_<name> (b − a in the column's unit), and how
SAMPLE_ERRORS = (("e_q_mrad", "q_deg", DEG_TO_MRAD), ("e_q_mm", "q_mm", 1.0), ("e_qd_deg_s", "qd_deg_s", 1.0),
                 ("e_qd_mm_s", "qd_mm_s", 1.0), ("e_tau_nm", "tau_nm", 1.0))
POSE_POSITION = ("x_mm", "y_mm", "z_mm")
QUAT = ("quat_w", "quat_x", "quat_y", "quat_z")


# ---------------------------------------------------------------------------------------------------- helpers


def _value(x) -> float:
    """A row's cell as a float, null (None) as NaN; never 0."""
    return math.nan if x is None else float(x)


def _out(x: float):
    return None if not math.isfinite(x) else float(x)


def _groups(rows: Sequence[Mapping[str, Any]], key: tuple[str, ...]) -> dict[tuple, list[int]]:
    out: dict[tuple, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        out[tuple(row.get(k) for k in key)].append(i)
    return out


def _locate(bt: np.ndarray, t: float) -> tuple[int, float, bool] | None:
    """(i, f, exact) for b at t: exact at one of b's samples (i), else between i and i+1 at fraction f; None outside b's span."""
    if not (bt[0] <= t <= bt[-1]):
        return None
    j = int(np.searchsorted(bt, t, side="left"))
    if j < bt.size and bt[j] == t:
        return j, 0.0, True
    i = j - 1
    return i, (t - bt[i]) / (bt[i + 1] - bt[i]), False


def _lerp(v: np.ndarray, i: int, f: float, exact: bool) -> float:
    if exact:
        return v[i]
    lo, hi = v[i], v[i + 1]
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return math.nan
    return lo + f * (hi - lo)


# ---------------------------------------------------------------------------------------------------- quaternions (w, x, y, z)


def _normalized(q: np.ndarray) -> np.ndarray:
    return q / np.linalg.norm(q)


def _slerp(q0: np.ndarray, q1: np.ndarray, f: float) -> np.ndarray:
    """Slerp of normalized quaternions the short way (q1 negated first when <q0, q1> < 0)."""
    q0, q1 = _normalized(q0), _normalized(q1)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1, dot = -q1, -dot
    dot = min(dot, 1.0)
    theta = math.acos(dot)
    if theta < 1e-12:
        return q0
    s = math.sin(theta)
    return (math.sin((1.0 - f) * theta) / s) * q0 + (math.sin(f * theta) / s) * q1


def _canonical(q: np.ndarray) -> np.ndarray:
    """w >= 0; when w == 0, the first non-zero of x, y, z positive (scipy's as_quat(canonical=True))."""
    if q[0] < 0 or (q[0] == 0 and next((c for c in q[1:] if c != 0), 0) < 0):
        return -q
    return q


def _multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw])


def _angle_mrad(a: np.ndarray, b: np.ndarray) -> float:
    """1000 · 2 · atan2(|v|, |w|) of (w, v) = conj(â) ⊗ b̂: the rotation from a to b (CONTRACT.md §5)."""
    a, b = _normalized(a), _normalized(b)
    r = _multiply(np.array([a[0], -a[1], -a[2], -a[3]]), b)
    return 1000.0 * 2.0 * math.atan2(float(np.linalg.norm(r[1:])), abs(float(r[0])))


# ---------------------------------------------------------------------------------------------------- difference(a, b)


def difference_samples(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]) -> list[dict]:
    """diff_samples rows: for each a row whose (run, device) b has and whose t is in b's span, b − a at t; in a's order."""
    b_groups = _groups(b, ("run", "device"))
    cache: dict[tuple, tuple[np.ndarray, dict[str, np.ndarray]]] = {}
    out = []
    for row in a:
        key = (row.get("run"), row.get("device"))
        if key not in b_groups:
            continue
        if key not in cache:
            idx = b_groups[key]
            bt = np.array([_value(b[i]["t"]) for i in idx])
            channels = {src: np.array([_value(b[i].get(src)) for i in idx]) for _, src, _ in SAMPLE_ERRORS}
            cache[key] = (bt, channels)
        bt, channels = cache[key]
        t = _value(row["t"])
        where = _locate(bt, t)
        if where is None:
            continue
        i, f, exact = where
        reference = b[b_groups[key][0]].get("situation")
        new = {"t": row["t"], "run": row["run"], "situation": row["situation"], "source": row.get("source"), "reference": reference,
               "device": row["device"]}
        for name, src, scale in SAMPLE_ERRORS:
            new[name] = _out((_lerp(channels[src], i, f, exact) - _value(row.get(src))) * scale)
        out.append(new)
    return out


def difference_poses(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]) -> list[dict]:
    """diff_poses rows: for each a row whose (run, body, frame) b has (a body in another frame gives none) and whose t is
    in b's span: a's columns, ref_<column> = b at t (positions linear, orientation slerp the short way, canonical sign),
    err_mm, err_rot_mrad (null when a or b has no quaternion); in a's order."""
    b_groups = _groups(b, ("run", "body", "frame"))
    cache: dict[tuple, tuple] = {}
    out = []
    for row in a:
        key = (row.get("run"), row.get("body"), row.get("frame"))
        if key not in b_groups:
            continue
        if key not in cache:
            idx = b_groups[key]
            bt = np.array([_value(b[i]["t"]) for i in idx])
            pos = {c: np.array([_value(b[i].get(c)) for i in idx]) for c in POSE_POSITION}
            quats = np.array([[_value(b[i].get(c)) for c in QUAT] for i in idx])
            cache[key] = (bt, pos, quats)
        bt, pos, quats = cache[key]
        t = _value(row["t"])
        where = _locate(bt, t)
        if where is None:
            continue
        i, f, exact = where
        reference = b[b_groups[key][0]].get("situation")
        new = {k: row.get(k) for k in ("t", "run", "situation", "source")}
        new["reference"] = reference
        new.update({k: row.get(k) for k in ("body", "frame", *POSE_POSITION)})
        ref = {c: _lerp(pos[c], i, f, exact) for c in POSE_POSITION}
        for c in POSE_POSITION:
            new[f"ref_{c}"] = _out(ref[c])
        delta = [ref[c] - _value(row.get(c)) for c in POSE_POSITION]
        new["err_mm"] = _out(math.sqrt(sum(d * d for d in delta)))
        for c in QUAT:
            new[c] = row.get(c)
        if exact:
            qb = quats[i]
            qb = _normalized(qb) if np.all(np.isfinite(qb)) else qb
        else:
            q0, q1 = quats[i], quats[i + 1]
            qb = _slerp(q0, q1, f) if np.all(np.isfinite(q0)) and np.all(np.isfinite(q1)) else np.full(4, np.nan)
        qb = _canonical(qb) if np.all(np.isfinite(qb)) else qb
        for c, v in zip(QUAT, qb):
            new[f"ref_{c}"] = _out(v)
        qa = np.array([_value(row.get(c)) for c in QUAT])
        new["err_rot_mrad"] = _angle_mrad(qa, qb) if np.all(np.isfinite(qa)) and np.all(np.isfinite(qb)) else None
        out.append(new)
    return out


# ---------------------------------------------------------------------------------------------------- tables and their check


def schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _suffix_units() -> dict[str, str]:
    channels = json.loads((SCHEMAS / "channels.json").read_text(encoding="utf-8"))
    return channels.get("suffixes") or channels.get("units") or {}


def contract_table(name: str, rows: list[dict], *, title: str, source: str, extra_fields: Iterable[dict] = (), **top) -> dict:
    """A table as the contract writes it ({schema: {fields}, rows}, the schema inline): the contract's own fields for the
    columns these rows use (units kept), plus `extra_fields` for a column the contract does not list."""
    base = schema(name)
    used = {k for row in rows for k in row}
    fields = [dict(f) for f in base["schema"]["fields"] if f["name"] in used]
    known = {f["name"] for f in fields}
    fields += [dict(f) for f in extra_fields if f["name"] in used and f["name"] not in known]
    return {"name": name, "title": title, "source": source, "contract": "data-ui gallery/robotics/CONTRACT.md v1", **top,
            "schema": {"fields": fields}, "rows": rows}


def validate(name: str, document: Mapping[str, Any]) -> list[str]:
    """What breaks the contract in a table: a required column missing or null, a value of the wrong type, a source outside
    real/sim/target, a column's unit other than the contract's, an undeclared column, or an extra numeric column with no
    unit. [] when it conforms."""
    base = schema(name)
    contract_fields = {f["name"]: f for f in base["schema"]["fields"]}
    fields = {f["name"]: f for f in document["schema"]["fields"]}
    problems = []
    for column, field in fields.items():
        want = contract_fields.get(column)
        if want is not None and want.get("unit") != field.get("unit"):
            problems.append(f"{name}.{column}: unit {field.get('unit')!r}, the contract says {want.get('unit')!r}")
        # an extra numeric column must declare its unit (§3: any extra channel with a unit suffix); text, lists and counts need none
        if want is None and field.get("type") == "number" and not field.get("unit"):
            problems.append(f"{name}.{column}: a number the contract does not list, with no unit")
    kinds = {"number": (int, float), "integer": (int,), "string": (str,), "array": (list,), "boolean": (bool,), "datetime": (str,), "date": (str,)}
    for i, row in enumerate(document["rows"]):
        for column in base.get("required", []):
            if row.get(column) is None:
                problems.append(f"{name} row {i}: required {column} is missing or null")
        for column, value in row.items():
            if value is None:
                continue
            field = fields.get(column)
            if field is None:
                problems.append(f"{name} row {i}: column {column} is not declared")
                continue
            kind = kinds.get(field.get("type"), (object,))
            if isinstance(value, bool) and field.get("type") != "boolean" or not isinstance(value, kind):
                problems.append(f"{name} row {i}: {column} = {value!r} is not a {field.get('type')}")
        if "source" in row and row["source"] is not None and row["source"] not in SOURCES:
            problems.append(f"{name} row {i}: source {row['source']!r} is not real/sim/target")
        if len(problems) > 20:
            return problems + ["…"]
    return problems
