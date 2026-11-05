"""The deployed life: model drift on the servo (wear) and on the head camera (a knock), each against the card's own drift check.

Zach, PROJECT - Sim2Real, Nov 5 2026: "you deploy the robot, and it lives checks with the diagonistics. If the model starts to drift
warning are sent ... (you can actually simulate backlash increasing, camera being vibrated out of position, etc. etc.. its like
predictive maintence right...)". And his addition the same day (via the coordinator): grow the hidden backlash with deployment hours,
b(h) = b0 + k h; fit k from the early-life checks (k recovered vs k true); predict the hour the fidelity crosses the drift threshold
and compare it with the hour it does; show the plain detector beside it (detection after the fact vs a forecast of hours left).

Backlash wear (CAN 11): commissioning is the oracle's own identification (M4, the gap included). Every 12 deployment hours the joint
runs its daily motions (the held-out H2 operate runs) on the real, wearing joint; each check scores the commissioned twin on the
link camera (live fidelity, x floor) and measures the gap from the motor encoder minus the link camera. The plain detector is the
servo card's drift check (reg.check_drift: live / calibrated against the threshold, its message). The wear-aware forecast is made
once, at the end of early life: the gap's history fitted on hours gives k (the servo card's M5.wear backlash term, a linear law at a
fixed duty), the commissioned twin replayed with growing gaps gives the fidelity a gap will cost, and type_cards' wear_usage_at
solves for the hour the threshold is reached. At the detector's alarm the twin is recalibrated (the gap re-measured) and re-scored.

Camera knock (the dual-arm cell): every 12 h the belt carries its printed tags past the head camera; the live reprojection error with
the commissioned camera, divided by the commissioned one, is camera_rgb's drift check. At hour 300 the camera is knocked; at the
alarm a short recalibration (the belt tags, the camera's six pose numbers only) restores it, and the shift it finds is compared with
the hidden one.
"""

from __future__ import annotations

import math
import time

import numpy as np

from sysid import cards, result
from sysid import world as hidden


# --- backlash wear --------------------------------------------------------------------------------------------------------------

def run_backlash(*, workers: int = 6, write: bool = False, commissioned_values: dict | None = None) -> dict:
    from type_cards import registry as reg  # noqa: PLC0415

    from sysid import describe  # noqa: PLC0415
    from sysid.examples.pendulum_can11 import pipeline as P  # noqa: PLC0415

    started = time.monotonic()
    description = describe.load(P.EXAMPLE)
    plan = P.plan(description)
    real = P.RealWorld(description, workers=workers)
    hidden_wear = real.drift["backlash_wear"]
    mon = description.monitoring
    from sysid import oracle  # noqa: PLC0415

    if commissioned_values is None and P.EXAMPLE in oracle.LAST_FIT:
        commissioned_values = oracle.LAST_FIT[P.EXAMPLE].values["M4"]
    if commissioned_values is None:
        measured = real.measure(plan)
        with hidden.sealed():
            commissioned_values = P.identify(description, measured.train).values["M4"]
    commissioned = P.twin(commissioned_values, "commissioned")
    runs = P.synthetic_runs(description, plan, plan.check)
    names = sorted(runs)
    check_seconds = sum(float(runs[n].t[-1] - runs[n].t[0]) for n in names)

    hours = np.arange(0.0, mon["horizon_h"] + 1e-9, mon["check_every_h"])
    rng = P.noise_rng(real.seed, "backlash wear")
    b_true = {float(h): hidden_wear["b0_rad"] + hidden_wear["rate_rad_per_h"] * h + rng.normal(0.0, hidden_wear["process_noise_rad"]) for h in hours}
    twins = {"commissioned": commissioned}
    twins.update({f"h{h:g}": real.twin(backlash_rad=b, version=f"wear-h{h:g}") for h, b in b_true.items()})
    replays = P.replay(runs, twins, workers=workers)
    twin_link = {n: P.link_of(replays[("commissioned", n)]) for n in names}

    checks, gap_history = [], []
    for h in hours:
        label = f"h{h:g}"
        err, floor, gaps, links = [], [], [], {}
        for n in names:
            rp = replays[(label, n)]
            link = P.link_of(rp)
            noise = P.noise_rng(real.seed, "check", label, n)
            meas_link = link + noise.normal(0.0, real.noise["link_camera_rad"], link.size)
            repeat = link + noise.normal(0.0, real.noise["link_camera_rad"], link.size)
            meas_q = rp.q + noise.normal(0.0, real.noise["encoder_rad"], rp.q.size)
            err.append(twin_link[n] - meas_link)
            floor.append(repeat - meas_link)
            gaps.append(meas_q - meas_link)
            links[n] = meas_link
        live = rms(np.concatenate(err)) / rms(np.concatenate(floor))
        b_hat = P.backlash_from_gaps(gaps)
        checks.append({"h": float(h), "b_true_rad": b_true[float(h)], "b_hat_rad": float(b_hat), "live_x_floor": float(live),
                       "floor_mrad": 1e3 * rms(np.concatenate(floor)), "link_mrad": 1e3 * rms(np.concatenate(err)), "_links": links})
        gap_history.append((float(h), float(b_hat)))

    calibrated = checks[0]["live_x_floor"]
    # the threshold: the servo card's own drift diagnostic's (reg.DRIFT_THRESHOLD, settable). WHY not TWINNED_LIMIT / calibrated (the
    # first rule tried, 2026-11-05): a twin commissioned near 1.45x floor puts that ratio at ~1.03, inside the checks' own scatter
    threshold = float(cards.drift_diagnostic("servo").threshold.value)
    for c in checks:
        verdict = cards.check_drift("servo", c["live_x_floor"], calibrated, threshold)
        c.update({"ratio": float(verdict.ratio), "status": verdict.status, "message": verdict.message})
    alarm = next((c["h"] for c in checks if c["status"] == "warning"), None)
    actual = crossing_hour([(c["h"], c["ratio"]) for c in checks], threshold)

    # the wear-aware forecast, made once at the end of early life
    early = [(h, b) for h, b in gap_history if h <= mon["early_life_h"] + 1e-9]
    k_hat, b0_hat, k_ci = line_fit(early)
    grid = b0_hat + np.linspace(0.0, 2.0e-3, 11)
    curve_twins = {f"b{i}": P.twin({**commissioned_values, "backlash_rad": float(b)}, f"wear-curve-{i}") for i, b in enumerate(grid)}
    curve_replays = P.replay(runs, curve_twins, workers=workers)
    floor_mrad = checks[0]["floor_mrad"]
    curve = []
    for i, b in enumerate(grid):
        delta = rms(np.concatenate([P.link_of(curve_replays[(f"b{i}", n)]) - twin_link[n] for n in names]))
        # the commissioned error and the gap's own error add in quadrature: two independent sources
        ratio = math.sqrt(calibrated ** 2 + (1e3 * delta / floor_mrad) ** 2) / calibrated
        curve.append((float(b), float(ratio)))
    b_star = crossing_hour(curve, threshold)  # the same interpolation, on the gap axis
    predicted = reg.wear_usage_at(b0_hat, k_hat, b_star, "linear") if b_star is not None else None
    remaining = reg.usage_remaining(early, b_star, "linear") if b_star is not None else None
    # the card's own forecast beside it: the drift ratio's history alone, fitted on hours (the servo card's Forecast)
    trend = cards.check_drift("servo", checks[len(early) - 1]["live_x_floor"], calibrated, threshold,
                              history=[(c["h"], c["ratio"]) for c in checks if c["h"] <= mon["early_life_h"] + 1e-9])

    recal = None
    if alarm is not None:
        at = next(c for c in checks if c["h"] == alarm)
        b_recal = at["b_hat_rad"]
        recal_twin = P.twin({**commissioned_values, "backlash_rad": b_recal}, "recalibrated")
        rp = P.replay(runs, {"recalibrated": recal_twin}, workers=workers)
        label = f"h{alarm:g}"
        err, floor = [], []
        for n in names:
            noise = P.noise_rng(real.seed, "check", label, n)
            link = P.link_of(replays[(label, n)])
            meas_link = link + noise.normal(0.0, real.noise["link_camera_rad"], link.size)
            repeat = link + noise.normal(0.0, real.noise["link_camera_rad"], link.size)
            err.append(P.link_of(rp[("recalibrated", n)]) - meas_link)
            floor.append(repeat - meas_link)
        live = rms(np.concatenate(err)) / rms(np.concatenate(floor))
        verdict = cards.check_drift("servo", live, calibrated, threshold)
        recal = {"h": alarm, "backlash_rad": b_recal, "live_x_floor": live, "ratio": float(verdict.ratio), "status": verdict.status}

    duty = torque_revolutions_per_hour(replays, names, "h0", check_seconds)
    wear_rung = next(r for r in reg.rungs("servo") if r.key == "M5.wear")
    wear = next(p.wear for p in wear_rung.parameters if p.name == "backlash_rad")
    for c in checks:
        c.pop("_links")
    doc = {
        "schema": "sysid.drift/1", "name": "backlash_wear", "example": P.EXAMPLE,
        "title": "Backlash wear on CAN 11: detected after the fact vs forecast ahead",
        "check_every_h": mon["check_every_h"], "horizon_h": mon["horizon_h"], "early_life_h": mon["early_life_h"],
        "check": mon["check"], "check_runs": names, "check_seconds": round(check_seconds, 1),
        "calibrated_x_floor": calibrated, "threshold": threshold,
        "threshold_rule": f"the servo card's drift diagnostic: live fidelity / calibrated <= {threshold:g} (reg.DRIFT_THRESHOLD; settable); calibrated {calibrated:.3f} x floor at hour 0",
        "diagnostic": {"id": cards.drift_diagnostic("servo").id, "message": reg.DRIFT_MESSAGE, "forecast": cards.drift_diagnostic("servo").forecast.method},
        "checks": checks,
        "detector_alarm_h": alarm, "actual_crossing_h": actual,
        "rate_recovered": k_hat, "rate_ci95": list(k_ci), "b0_recovered_rad": b0_hat, "rate_true": hidden_wear["rate_rad_per_h"], "b0_true_rad": hidden_wear["b0_rad"],
        "predicted_at_h": float(mon["early_life_h"]), "predicted_crossing_h": predicted, "remaining_h_at_prediction": remaining,
        "gap_at_threshold_rad": b_star, "curve": [{"backlash_rad": b, "ratio": r} for b, r in curve],
        "card_trend_remaining_h": trend.remaining, "card_trend_unit": trend.unit,
        "recalibrated": recal,
        "wear": {"card": "servo", "rung": "M5.wear", "parameter": "backlash_rad", "usage": wear.usage, "unit": wear.unit, "law": wear.law, "rate": wear.rate,
                 "duty_nm_rev_per_h": duty, "rate_recovered_per_nm_rev": k_hat / duty if duty else None, "rate_true_per_nm_rev": hidden_wear["rate_rad_per_h"] / duty if duty else None,
                 "note": "the card's law is Archard's (load x sliding distance); at the check's fixed duty it is linear in hours: rate per N.m.rev = rate per hour / duty"},
        "provenance": {**result.provenance(P.EXAMPLE), "seconds": round(time.monotonic() - started, 1), "commissioned_twin": commissioned.digest(),
                       "identify_sealed": True},
    }
    if write:
        result.write(doc, "drift_backlash_wear")
    return doc


def crossing_hour(series, threshold: float) -> float | None:
    """The first x at which y reaches `threshold`, linearly interpolated between the samples either side; None when it never does."""
    for (x0, y0), (x1, y1) in zip(series, series[1:]):
        if y0 < threshold <= y1:
            return float(x0 + (threshold - y0) * (x1 - x0) / (y1 - y0))
    return None


def line_fit(points) -> tuple[float, float, tuple[float, float]]:
    """(slope, intercept, 95 % interval of the slope): ordinary least squares, the interval from Student's t."""
    from scipy import stats  # noqa: PLC0415

    x, y = (np.array([p[i] for p in points], float) for i in (0, 1))
    fit = stats.linregress(x, y)
    t = stats.t.ppf(0.975, len(x) - 2)
    return float(fit.slope), float(fit.intercept), (float(fit.slope - t * fit.stderr), float(fit.slope + t * fit.stderr))


def torque_revolutions_per_hour(replays, names, label: str, seconds: float) -> float:
    """The check motion's torque-weighted output revolutions per hour of running (sum |tau| |dq| / 2 pi): Archard's usage rate."""
    total = sum(float(np.sum(np.abs(replays[(label, n)].tau[1:]) * np.abs(np.diff(replays[(label, n)].q)))) for n in names) / (2 * math.pi)
    return total / (seconds / 3600.0)


def rms(x) -> float:
    x = np.asarray(x, float)
    return float(math.sqrt(np.mean(x ** 2)))


# --- camera knock ---------------------------------------------------------------------------------------------------------------

def run_camera(*, workers: int = 6, write: bool = False) -> dict:
    from sysid import camera as cam  # noqa: PLC0415
    from sysid import describe  # noqa: PLC0415
    from sysid.examples.dual_arm_cell import pipeline as P  # noqa: PLC0415

    started = time.monotonic()
    description = describe.load(P.EXAMPLE)
    plan = P.plan(description)
    real = P.RealWorld(description)
    knock = real.drift["camera_knock"]
    mon = description.monitoring
    measured = real.measure(plan)
    with hidden.sealed():
        fit = P.identify(description, measured.train)
    nominal = {k: v.value for k, v in description.nominal.items()}
    calibrated_values = {**nominal, **fit.values}
    cell = real.cell

    def observe_belt(h: float, count: int, tag: str) -> list:
        shift = knock["shift"] if h >= knock["hour"] else None
        pin = real.camera(shift)
        rng = P.rng_for(real.seed, "monitor", tag, h)
        out = []
        for k, travel in enumerate(rng.uniform(-0.45, 0.45, count)):
            for j, corners in enumerate(cell.belt_tag_world(float(travel))):
                px, ok = real.observe(pin, corners, P.rng_for(real.seed, "monitor", tag, h, k, j))
                if ok.all():
                    out.append(P.Observation("belt", None, corners, px, "monitor"))
        return out

    def observe_arms(h: float, tag: str) -> list:
        """The arms show their gripper tags at the plan's held-out poses (a short maintenance routine, both arms)."""
        shift = knock["shift"] if h >= knock["hour"] else None
        pin = real.camera(shift)
        out = []
        for arm in P.ARMS:
            for k, q in enumerate(plan.poses[(arm, "held_out")]):
                corners, _ = cell.gripper_tag_in_base(arm, q)
                px, ok = real.observe(pin, cell.to_world(real.truth, arm, corners), P.rng_for(real.seed, "monitor", tag, h, arm, k))
                if ok.all():
                    out.append(P.Observation("gripper", arm, corners, px, "monitor"))
        return out

    def reprojection(values, obs) -> float:
        return cam.rms(P.predict(cell, values, obs) - np.vstack([o.pixels for o in obs]))

    hours = np.arange(0.0, mon["horizon_h"] + 1e-9, mon["check_every_h"])
    checks, calibrated = [], None
    for h in hours:
        obs = observe_belt(float(h), 4, "check")
        live = reprojection(calibrated_values, obs)
        calibrated = live if calibrated is None else calibrated
        verdict = cards.check_drift("camera_rgb", live, calibrated)
        checks.append({"h": float(h), "reprojection_px": live, "ratio": float(verdict.ratio), "status": verdict.status, "message": verdict.message,
                       "knocked": bool(h >= knock["hour"])})
    alarm = next((c["h"] for c in checks if c["status"] == "warning"), None)
    recal = None
    shift_recovered = {}
    if alarm is not None:
        # WHY the arms' tags too (measured 2026-11-05): from the belt's coplanar tags alone a sideways shift and a tilt look alike at
        # ~0.9 m (the knock read dx 1.8 of 3.0 mm, ry 12.7 of 14.0 mrad, the image restored all the same); points at other depths split them
        obs = observe_belt(alarm, 10, "recalibration") + observe_arms(alarm, "recalibration")
        pose = tuple(f"{P.CAMERA}.{n}" for n in cam.POSE_NAMES)
        with hidden.sealed():
            again = P.identify(description, obs, only=pose, start=calibrated_values)
        recalibrated = {**calibrated_values, **again.values}
        after = observe_belt(alarm + mon["check_every_h"], 4, "check")
        live = reprojection(recalibrated, after)
        verdict = cards.check_drift("camera_rgb", live, calibrated)
        recal = {"h": alarm, "ratio": float(verdict.ratio), "reprojection_px": live, "status": verdict.status, "views": len(obs)}
        R_old, t_old = cell.frame(calibrated_values, P.CAMERA)
        R_new, t_new = cell.frame(recalibrated, P.CAMERA)
        shift_recovered = {**dict(zip(cam.POSE_NAMES[:3], map(float, t_new - t_old))), **dict(zip(cam.POSE_NAMES[3:], map(float, cam.rotvec_of(R_new @ R_old.T))))}
    doc = {
        "schema": "sysid.drift/1", "name": "camera_knock", "example": P.EXAMPLE, "title": "The head camera knocked out of pose",
        "check_every_h": mon["check_every_h"], "horizon_h": mon["horizon_h"], "check": mon["check"],
        "threshold": float(cards.drift_diagnostic("camera_rgb").threshold.value), "diagnostic": {"id": cards.drift_diagnostic("camera_rgb").id},
        "calibrated_reprojection_px": calibrated, "checks": checks, "alarm_h": alarm, "knock_h": knock["hour"],
        "recalibrated": recal, "shift_recovered": shift_recovered, "shift_true": knock["shift"],
        "provenance": {**result.provenance(P.EXAMPLE), "seconds": round(time.monotonic() - started, 1), "identify_sealed": True},
    }
    if write:
        result.write(doc, "drift_camera_knock")
    return doc
