"""The conveyor: the description's MJCF in, the belt's effective roller radius, moving mass and drag out.

The "real" belt is conveyor.xml at world.json's truth (a worn, lagged roller: 49.6 mm, not 50; a heavier, draggier belt than drawn).
The VFD is set in belt speed through the NOMINAL radius (that is how a drive is commissioned), so a radius error is a speed error
the encoder alone cannot see: the belt tracker (a camera following a mark on the belt) is the second sensor that sees it.

Identification: (1) M1, the radius: least squares of the tracker's belt travel on the encoder's roller angle, one offset per profile;
(2) M2, the dynamics: least squares of the simulated roller angle on the measured one over the train profiles, the description's
own MJCF at the fitted radius with the moving mass, viscous and Coulomb drag free (scipy least_squares, intervals from its Jacobian).
Held-out: the belt travel the twin predicts from the command alone (forward simulation) against the tracker, in mm: what a pick on
a moving belt needs.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np

from sysid import cards, result
from sysid import world as hidden

EXAMPLE = "conveyor"
DT = 0.002
TRACKER_EVERY = 5  # 100 Hz
HARD_FRICTION_SOLREF = (0.0004, 1.0)
HARD_FRICTION_SOLIMP = (0.99, 0.99, 0.001, 0.5, 2.0)
SPEED_EDGES = (-0.25, -0.05, 0.05, 0.15, 0.25, 0.35, 0.5, 0.65)  # m/s: reverse, stopped, then the levels
ACCEL_EDGES = (-30.0, -2.0, -0.2, 0.2, 2.0, 30.0)  # m/s^2: braking hard / gently, steady, speeding up gently / hard


def rng_for(seed: int, *names) -> np.random.Generator:
    return np.random.default_rng([seed, *(zlib.crc32(str(n).encode()) for n in names)])


class Belt:
    """conveyor.xml compiled, with the four values a calibration touches written into it."""

    def __init__(self, description):
        import mujoco  # noqa: PLC0415

        self.model = description.spec().compile()
        m = self.model
        self.eq = m.equality("belt_drive").id
        self.body = m.body("belt").id
        self.belt_dof = m.jnt_dofadr[m.joint("belt").id]
        self.belt_qpos = m.jnt_qposadr[m.joint("belt").id]
        self.roller_qpos = m.jnt_qposadr[m.joint("drive_roller").id]
        self.vfd = m.actuator("vfd").id
        # WHY hard friction (as the arms, bam_rack_twin's HARD_FRICTION_SOLREF): the Coulomb drag should be a Coulomb level
        m.dof_solref[self.belt_dof] = HARD_FRICTION_SOLREF
        m.dof_solimp[self.belt_dof] = HARD_FRICTION_SOLIMP
        self.data = mujoco.MjData(m)

    def set(self, values: dict) -> None:
        import mujoco  # noqa: PLC0415

        m = self.model
        if "belt.roller_radius_m" in values:
            m.eq_data[self.eq, 1] = float(values["belt.roller_radius_m"])
        if "belt.moving_mass_kg" in values:
            m.body_mass[self.body] = max(0.1, float(values["belt.moving_mass_kg"]))
        if "belt.viscous_drag_n_s_m" in values:
            m.dof_damping[self.belt_dof] = max(0.0, float(values["belt.viscous_drag_n_s_m"]))
        if "belt.coulomb_drag_n" in values:
            m.dof_frictionloss[self.belt_dof] = max(0.0, float(values["belt.coulomb_drag_n"]))
        mujoco.mj_setConst(m, self.data)

    def run(self, speed_command: np.ndarray, nominal_radius: float) -> tuple[np.ndarray, np.ndarray]:
        """(roller angle, belt travel) at every step for a belt-speed command set through the nominal radius."""
        import mujoco  # noqa: PLC0415

        m, d = self.model, self.data
        mujoco.mj_resetData(m, d)
        theta, x = np.zeros(speed_command.size), np.zeros(speed_command.size)
        for k, v in enumerate(speed_command):
            d.ctrl[self.vfd] = v / nominal_radius
            mujoco.mj_step(m, d)
            theta[k], x[k] = d.qpos[self.roller_qpos], d.qpos[self.belt_qpos]
        return theta, x


# --- plan -----------------------------------------------------------------------------------------------------------------------

@dataclass
class Plan:
    train: list[np.ndarray]
    held_out: list[np.ndarray]
    coverage: dict


def profile(rng, seconds: float, levels) -> np.ndarray:
    """A speed command: dwells of 0.8-2.5 s at levels drawn from the description's (and stops, and a slow reverse jog)."""
    out, t = [], 0.0
    choices = [0.0, -0.1] + list(levels)
    while t < seconds:
        level = float(rng.choice(choices))
        dwell = float(rng.uniform(0.8, 2.5))
        out.append(np.full(int(round(dwell / DT)), level))
        t += dwell
    return np.concatenate(out)[: int(round(seconds / DT))]


def plan(description) -> Plan:
    s = description.schedule
    profiles = [profile(rng_for(s["seed"], "profile", k), s["profile_s"], s["levels_m_s"]) for k in range(s["profiles_train"] + s["profiles_held_out"])]
    p = Plan(profiles[: s["profiles_train"]], profiles[s["profiles_train"]:], {})
    p.coverage = coverage(description, p)
    return p


def coverage(description, p: Plan) -> dict:
    """(belt speed, belt acceleration) cells the planned commands visit, by the description's own model before anything runs (as
    bam_rack_twin.schedule plans with its twin): sysid's adapter rule, the conveyor having no type card yet."""
    belt = Belt(description)
    nominal = description.nominal["belt.roller_radius_m"].value
    out = {}
    for split, profiles in (("train", p.train), ("held_out", p.held_out)):
        counts = np.zeros((len(SPEED_EDGES) - 1, len(ACCEL_EDGES) - 1), int)
        for command in profiles:
            _, x = belt.run(command, nominal)
            v = np.gradient(x, DT)
            a = np.gradient(v, DT)
            h, _, _ = np.histogram2d(np.clip(v, SPEED_EDGES[0], SPEED_EDGES[-1] - 1e-9), np.clip(a, ACCEL_EDGES[0], ACCEL_EDGES[-1] - 1e-9),
                                     bins=(SPEED_EDGES, ACCEL_EDGES))
            counts += h.astype(int)
        visited = int((counts > 0).sum())
        out[split] = {"pct": round(100.0 * visited / counts.size, 2), "visited": visited, "reachable": int(counts.size),
                      "samples": int(counts.sum()), "axes": {"load": None}, "unplanned": ["load (no profile carries product)"]}
    out["function"] = "sysid adapter (no conveyor card yet): occupancy of the (belt speed, belt acceleration) grid by the nominal model's response"
    out["rule"] = "share of the 7 speed x 5 acceleration cells the planned profiles visit; every cell counted reachable; belt load named unplanned"
    out["edges"] = [list(SPEED_EDGES), list(ACCEL_EDGES)]
    out["axes"] = ["belt speed (m/s)", "belt acceleration (m/s^2)"]
    return out


# --- the real belt ----------------------------------------------------------------------------------------------------------------

@dataclass
class Run:
    command: np.ndarray
    theta: np.ndarray       # encoder, every step
    x_tracked: np.ndarray   # tracker, every TRACKER_EVERY steps
    theta_at_track: np.ndarray


@dataclass
class Measured:
    train: list[Run]
    held_out: list[Run]


class RealWorld:
    def __init__(self, description, *, workers: int = 6):
        self.description = description
        doc = hidden.load(EXAMPLE)
        self.truth, self.noise, self.seed = doc["truth"], doc["noise"], doc["seed"]

    def measure(self, p: Plan) -> Measured:
        belt = Belt(self.description)
        belt.set(self.truth)
        nominal = self.description.nominal["belt.roller_radius_m"].value
        runs = {"train": [], "held_out": []}
        for split, profiles in (("train", p.train), ("held_out", p.held_out)):
            for k, command in enumerate(profiles):
                rng = rng_for(self.seed, split, k)
                theta, x = belt.run(command, nominal)
                theta_meas = theta + rng.normal(0, self.noise["encoder_rad"], theta.size)
                track = np.arange(0, theta.size, TRACKER_EVERY)
                runs[split].append(Run(command, theta_meas, x[track] + rng.normal(0, self.noise["belt_tracker_m"], track.size), theta_meas[track]))
        return Measured(runs["train"], runs["held_out"])


# --- identification ------------------------------------------------------------------------------------------------------------

@dataclass
class Fit:
    values: dict
    ci95: dict
    methods: dict


def identify(description, runs: list[Run]) -> Fit:
    """M1 the radius from tracker travel on encoder angle; M2 the moving mass and drag by forward simulation of the description's
    MJCF at that radius, matched to the encoder."""
    from scipy.optimize import least_squares  # noqa: PLC0415

    # M1: x = r theta + c_k per profile (each profile's tracker has its own zero)
    cols = [np.concatenate([r.theta_at_track for r in runs])]
    for k, r in enumerate(runs):
        cols.append(np.concatenate([np.full(rr.theta_at_track.size, 1.0 if kk == k else 0.0) for kk, rr in enumerate(runs)]))
    A = np.column_stack(cols)
    y = np.concatenate([r.x_tracked for r in runs])
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ c
    cov = np.linalg.pinv(A.T @ A) * float(resid @ resid) / max(1, y.size - A.shape[1])
    radius, radius_half = float(c[0]), 1.96 * math.sqrt(cov[0, 0])

    nominal = {key: entry.value for key, entry in description.nominal.items()}
    belt = Belt(description)
    belt.set({"belt.roller_radius_m": radius})
    names = ("belt.moving_mass_kg", "belt.viscous_drag_n_s_m", "belt.coulomb_drag_n")
    commanded_radius = nominal["belt.roller_radius_m"]

    def residual(x):
        belt.set(dict(zip(names, x)))
        return np.concatenate([belt.run(r.command, commanded_radius)[0][::2] - r.theta[::2] for r in runs]) / 1e-3

    # WHY a physics start before the output-error fit (measured 2026-11-05: from the nominal start, least_squares stopped at a cost
    # 8000x the truth's, mass barely off nominal, because Coulomb drag makes the cost non-smooth for finite differences): the
    # steady-state droop at each commanded level is linear in the drag, kv (w_cmd - w) = r (b r w + F sgn w); then the mass by a 1-D
    # golden section on the transients; then all three polished together.
    kv = float(belt.model.actuator_gainprm[belt.vfd, 0])
    rows, rhs = [], []
    for r in runs:
        for level, start, stop in dwells(r.command):
            if level == 0.0 or stop - start < 400:
                continue
            w = float(np.mean(np.diff(r.theta[start + (stop - start) // 2: stop])) / DT)
            rows.append([radius * radius * w, radius * math.copysign(1.0, w)])
            rhs.append(kv * (level / commanded_radius - w))
    b0, f0 = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0]
    b0, f0 = max(0.0, float(b0)), max(0.0, float(f0))
    cost = lambda m: float(np.sum(residual(np.array([m, b0, f0])) ** 2))  # noqa: E731
    lo, hi = 0.25 * nominal["belt.moving_mass_kg"], 4.0 * nominal["belt.moving_mass_kg"]
    for _ in range(24):
        a, b_ = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
        if cost(a) < cost(b_):
            hi = b_
        else:
            lo = a
    x0 = np.array([0.5 * (lo + hi), b0, f0])
    fit = least_squares(residual, x0, x_scale=np.maximum(x0, 1e-3), diff_step=1e-4, bounds=([0.5, 0.0, 0.0], [200.0, 500.0, 200.0]))
    cov = np.linalg.pinv(fit.jac.T @ fit.jac) * float(fit.fun @ fit.fun) / max(1, fit.fun.size - x0.size)
    half = 1.96 * np.sqrt(np.diag(cov))
    values = {"belt.roller_radius_m": radius, **{n: float(v) for n, v in zip(names, fit.x)}}
    ci = {"belt.roller_radius_m": (radius - radius_half, radius + radius_half), **{n: (float(v - h), float(v + h)) for n, v, h in zip(names, fit.x, half)}}
    methods = {"M1": f"least squares of tracker travel on encoder angle, {len(runs)} train profiles, one zero each",
               "M2": f"drag from the steady-state droop of {len(rows)} dwells (linear), mass by golden section on the transients, then least squares of "
                     f"the simulated roller angle on the encoder's over the train profiles ({fit.nfev} simulations), radius fixed at M1's"}
    return Fit(values, ci, methods)


def dwells(command: np.ndarray):
    """(level, start, stop) of every constant stretch of a command."""
    edges = np.concatenate(([0], np.nonzero(np.diff(command))[0] + 1, [command.size]))
    return [(float(command[a]), int(a), int(b)) for a, b in zip(edges[:-1], edges[1:])]


# --- held-out score -----------------------------------------------------------------------------------------------------------

def score(description, p: Plan, fit: Fit, measured: Measured, *, workers: int = 6) -> dict:
    nominal = {key: entry.value for key, entry in description.nominal.items()}
    models = {"M0": nominal, "M1": {**nominal, "belt.roller_radius_m": fit.values["belt.roller_radius_m"]}, "M2": {**nominal, **fit.values}}
    out = {"models": {}}
    for label, values in models.items():
        belt = Belt(description)
        belt.set(values)
        err = []
        for run in measured.held_out:
            theta, x = belt.run(run.command, nominal["belt.roller_radius_m"])
            err.append(x[::TRACKER_EVERY] - run.x_tracked - (x[0] - run.x_tracked[0]))
        e = np.concatenate(err)
        out["models"][label] = {"belt_mm": 1e3 * float(np.sqrt(np.mean(e ** 2))), "belt_max_mm": 1e3 * float(np.abs(e).max())}
    return out


def assemble(description, p: Plan, fit: Fit, scores: dict, *, truth: dict) -> dict:
    recovered = {k: {"value": v, "ci95": fit.ci95[k], "rung": "M1" if k == "belt.roller_radius_m" else "M2",
                     "method": fit.methods["M1" if k == "belt.roller_radius_m" else "M2"]} for k, v in fit.values.items()}
    m = scores["models"]
    ladder, source = cards.ladder("conveyor")
    rungs = []
    for r in ladder:
        row = cards.rung_row(r)
        if r.key in m:
            row.update(m[r.key])
        rungs.append(row)
    md = description.manifest["model"]
    return {
        "title": description.manifest["title"], "subtitle": description.manifest.get("subtitle", ""), "summary": description.manifest.get("summary", ""),
        "description": {"manifest": f"sysid/examples/{EXAMPLE}/description.json", "model": {k: md.get(k) for k in ("format", "path", "source")},
                        "sensors": description.manifest.get("sensors", []), "known": description.known, "components": len(description.components)},
        "tree": description.tree(),
        "schedule": {"train": {"profiles": len(p.train), "seconds": round(sum(c.size for c in p.train) * DT, 1)},
                     "held_out": {"profiles": len(p.held_out), "seconds": round(sum(c.size for c in p.held_out) * DT, 1)},
                     "levels_m_s": description.schedule["levels_m_s"], "coverage": p.coverage},
        "parameters": result.parameter_rows(EXAMPLE, description, truth, recovered),
        "metrics": [result.metric(EXAMPLE, "held_out_belt_position_mm", "Belt travel, twin (from the command) vs tracker", "mm",
                                  m["M0"]["belt_mm"], m["M2"]["belt_mm"], after_model="M2",
                                  note=f"{len(p.held_out)} held-out profiles; max {m['M0']['belt_max_mm']:.1f} -> {m['M2']['belt_max_mm']:.2f} mm")],
        "rungs": rungs, "ladder_source": source, "selected_rung": None,
        "notes": ["The conveyor has no type card yet; its ladder and coverage rule are sysid's adapter (cards.py).",
                  "The VFD's speed loop and torque limit are the description's; the belt's elasticity (a two-mass belt) is not modelled."],
    }
