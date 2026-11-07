"""The deployed life: model drift on the servo (wear) and on the head camera (a knock), each against the card's own drift check.

Zach, PROJECT - Sim2Real, Nov 5 2026: "you deploy the robot, and it lives checks with the diagonistics. If the model starts to drift
warning are sent ... (you can actually simulate backlash increasing, camera being vibrated out of position, etc. etc.. its like
predictive maintence right...)". And his addition the same day (via the coordinator): grow the hidden backlash with deployment hours,
b(h) = b0 + k h; fit k from the early-life checks (k recovered vs k true); predict the hour the fidelity crosses the drift threshold
and compare it with the hour it does; show the plain detector beside it (detection after the fact vs a forecast of hours left).

Backlash wear (CAN 11): commissioning is the oracle's own identification (M4, the gap included). Every 12 deployment hours the joint
runs its daily motions (the held-out H2 operate runs) on the real, wearing joint; each check measures the gap from the motor encoder
minus the link camera (the routine commissioning measured it with) and scores the commissioned twin on the link camera (live fidelity,
x floor). The plain detector is the servo's drift alarm, which warns on EITHER of two checks: the gap drift (type_cards servo.gap_drift,
dm.parameter_drift: the gap a check measures, less the commissioned gap, against the station's allowance; description.json
monitoring.gap_allowance; CAN 11's is T5's 2 arcmin) or the fidelity ratio (the servo card's servo.drift), whichever comes first. The
wear-aware forecast is the gap's history fitted on hours (the servo card's M5.wear backlash term, a linear law at a fixed duty), re-made
at every check and issued once, solved by type_cards' wear_usage_at for the hour the gap reaches the commissioned gap plus the allowance.
At the alarm the twin is recalibrated (the gap re-measured) and re-scored.

WHY the gap's own units beside the fidelity ratio (2026-11-07, docs/decision-calibration-routines-2026-11-07.md, its addendum; the domain-v3
decision's "The drift threshold"): the ratio is the twin's link error over the camera's floor, so as the camera's noise grows the same
wear moves it less; at 3x the noise CAN 11's ratio never warned inside the 480 h horizon. The gap estimate's error grows with the noise,
its mean does not. WHY either, not the gap alone (the addendum's last line, decided 2026-11-07): at 1x the gap check alone warns 96 h
after the ratio does, and the ratio is already computed on every check (ratio, ratio_status, ratio_alarm_h), so the servo warns on
whichever comes first (servo_verdict, first_alarm; each check's status, gap_status, warned_by; the doc's detector_alarm_h, gap_alarm_h,
alarm_by). The forecast stays the gap's: the gap -> drift-ratio curve the ratio's forecast needed (45 replays of the commissioned twin) is
gone. The gap check needs no twin: where commissioning has only the gap (the regression raised), the alarm is the gap check alone and
the fidelity view and the recalibration are skipped.

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

def gap_allowance(description) -> dict:
    """The station's allowance on its gap's growth (type_cards servo.gap_drift's warn limit, set per station) as its description declares
    it (monitoring.gap_allowance: value, unit, rule, source, why); refused unless it is a positive value in rad."""
    allowance = dict(description.monitoring.get("gap_allowance") or {})
    value = allowance.get("value")
    if allowance.get("unit") != "rad" or isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ValueError(f"{description.id}: monitoring.gap_allowance must be a positive value in rad, not {allowance!r}")
    return allowance


def t5_gap_allowance_rad(station) -> float | None:
    """The rule a station's gap allowance is set by (2026-11-07): T5's gap half-width at the output (bam_rack_twin acceptance
    GAP_CI_HALF_ARCMIN) on a geared station, None on a direct drive (no gear, no gap; its board's rotor turn is the output's).

    WHY T5: the commissioned twin carries the gap commissioning measured, and T5 accepts a geared unit when that gap is known to within
    +-2 arcmin (its 95 % interval's half-width); once wear has grown the gap further than that past the twin's, the twin's gap is off by
    more than the unit was accepted with. The same 2 arcmin grades every UR gap in the noise ladder (sysid/noise_ladder.json)."""
    from bam_rack_twin import acceptance  # noqa: PLC0415

    if float(station.board_rotor_to_output_ratio) == 1.0:
        return None
    return math.radians(acceptance.GAP_CI_HALF_ARCMIN / 60.0)


def gap_verdict(measured: float, *, commissioned: float, allowance: float) -> dict:
    """One deployed gap check: type_cards' servo.gap_drift (dm.parameter_drift), the gap measured less the commissioned gap against the
    allowance, with its growth and, past the allowance, the diagnostic's message."""
    from type_cards import domain as dm  # noqa: PLC0415

    spec = dm.diagnostic("integrated_servo", "servo.gap_drift")
    status = dm.parameter_drift(spec, commissioned=float(commissioned), measured=float(measured), allowance=float(allowance))
    return {"status": status, "growth_rad": float(measured) - float(commissioned), "message": spec.message if status == "warning" else ""}


def servo_verdict(gap_status: str, ratio_status: str | None = None) -> dict:
    """The servo's drift alarm on one check: it warns when EITHER check does, the gap check (gap_verdict) or the fidelity ratio (None: no
    twin, no ratio, the gap check alone); warned_by names which."""
    warned_by = [name for name, status in (("gap", gap_status), ("ratio", ratio_status)) if status == "warning"]
    return {"status": "warning" if warned_by else "ok", "warned_by": warned_by}


def first_alarm(checks) -> tuple[float | None, list]:
    """(hour, warned_by) of the first check whose status is a warning, (None, []) if none is."""
    return next(((float(c["h"]), list(c["warned_by"])) for c in checks if c["status"] == "warning"), (None, []))


def run_backlash(*, workers: int = 6, write: bool = False, commissioned_values: dict | None = None,
                 commissioned_gap: float | None = None) -> dict:
    """CAN 11's deployed life: the gap check and the fidelity ratio every 12 h (the alarm is either), the wear forecast, the recalibration at
    the alarm. `commissioned_values` (M4's) commission a twin, whose fidelity ratio is kept beside the gap check; `commissioned_gap` alone
    (the regression raised: the noise ladder's 10x) runs the gap check without a twin; neither, the oracle's own fit (re-made if absent)."""
    from type_cards import registry as reg  # noqa: PLC0415

    from sysid import describe, oracle  # noqa: PLC0415
    from sysid.examples.pendulum_can11 import pipeline as P  # noqa: PLC0415

    started = time.monotonic()
    description = describe.load(P.EXAMPLE)
    plan = P.plan(description)
    real = P.RealWorld(description, workers=workers)
    hidden_wear = real.drift["backlash_wear"]
    mon = description.monitoring
    allowance = gap_allowance(description)
    limit = float(allowance["value"])

    if commissioned_values is None and commissioned_gap is None:
        if P.EXAMPLE in oracle.LAST_FIT:
            commissioned_values = oracle.LAST_FIT[P.EXAMPLE].values["M4"]
        else:
            measured = real.measure(plan)
            with hidden.sealed():
                commissioned_values = P.identify(description, measured.train).values["M4"]
    commissioned = None if commissioned_values is None else P.twin(commissioned_values, "commissioned")
    gap0 = float(commissioned_values["backlash_rad"]) if commissioned_values is not None else float(commissioned_gap)
    runs = P.synthetic_runs(description, plan, plan.check)
    names = sorted(runs)
    check_seconds = sum(float(runs[n].t[-1] - runs[n].t[0]) for n in names)

    hours = np.arange(0.0, mon["horizon_h"] + 1e-9, mon["check_every_h"])
    rng = P.noise_rng(real.seed, "backlash wear")
    b_true = {float(h): hidden_wear["b0_rad"] + hidden_wear["rate_rad_per_h"] * h + rng.normal(0.0, hidden_wear["process_noise_rad"]) for h in hours}
    twins = {} if commissioned is None else {"commissioned": commissioned}
    twins.update({f"h{h:g}": real.twin(backlash_rad=b, version=f"wear-h{h:g}") for h, b in b_true.items()})
    replays = P.replay(runs, twins, workers=workers)
    twin_link = None if commissioned is None else {n: P.link_of(replays[("commissioned", n)]) for n in names}

    checks = []
    for h in hours:
        label = f"h{h:g}"
        err, floor, gaps = [], [], []
        for n in names:
            rp = replays[(label, n)]
            link = P.link_of(rp)
            # WHY these three draws in this order on every path: they are the check's own measurement (camera, its repeat, encoder); a
            # gap-only run draws the repeat too, so its gaps are the twin path's, number for number
            noise = P.noise_rng(real.seed, "check", label, n)
            meas_link = link + noise.normal(0.0, real.noise["link_camera_rad"], link.size)
            repeat = link + noise.normal(0.0, real.noise["link_camera_rad"], link.size)
            meas_q = rp.q + noise.normal(0.0, real.noise["encoder_rad"], rp.q.size)
            if twin_link is not None:
                err.append(twin_link[n] - meas_link)
            floor.append(repeat - meas_link)
            gaps.append(meas_q - meas_link)
        b_hat = float(P.backlash_from_gaps(gaps))
        verdict = gap_verdict(b_hat, commissioned=gap0, allowance=limit)
        check = {"h": float(h), "b_true_rad": b_true[float(h)], "b_hat_rad": b_hat, "gap_growth_rad": verdict["growth_rad"],
                 "gap_status": verdict["status"], "message": verdict["message"], "floor_mrad": 1e3 * rms(np.concatenate(floor))}
        if twin_link is not None:
            check.update(live_x_floor=float(rms(np.concatenate(err)) / rms(np.concatenate(floor))), link_mrad=1e3 * rms(np.concatenate(err)))
        checks.append(check)

    # the truth's crossing: the first hour the hidden gap has grown the allowance past the gap the twin carries
    actual = crossing_hour([(c["h"], c["b_true_rad"] - gap0) for c in checks], limit)

    # the fidelity view, the alarm's second check beside the gap check on the same checks: the servo card's drift diagnostic (reg.DRIFT_THRESHOLD)
    # WHY not TWINNED_LIMIT / calibrated as its threshold (the first rule tried, 2026-11-05): a twin commissioned near 1.45x floor puts that
    # ratio at ~1.03, inside the checks' own scatter
    ratio_threshold = float(cards.drift_diagnostic("servo").threshold.value)
    calibrated = None if twin_link is None else checks[0]["live_x_floor"]
    if calibrated is not None:
        for c in checks:
            v = cards.check_drift("servo", c["live_x_floor"], calibrated, ratio_threshold)
            c.update(ratio=float(v.ratio), ratio_status=v.status)
            c["message"] = c["message"] or (v.message if v.status == "warning" else "")
    # the servo's alarm: either check (servo_verdict); no twin, no ratio: the gap check alone
    for c in checks:
        c.update(servo_verdict(c["gap_status"], c.get("ratio_status")))
    alarm, alarm_by = first_alarm(checks)
    gap_alarm = next((c["h"] for c in checks if c["gap_status"] == "warning"), None)
    ratio_alarm = next((c["h"] for c in checks if c.get("ratio_status") == "warning"), None)
    ratio_crossing = None if calibrated is None else crossing_hour([(c["h"], c["ratio"]) for c in checks], ratio_threshold)

    # the wear-aware forecast: re-made at every check from the checks so far, issued at the first whose crossing is within the planning
    # horizon (the monitoring's early_life_h at the latest); each one reads only the checks at or before its hour
    level = gap0 + limit
    forecast = issue_forecast(checks, level=level, latest_h=float(mon["early_life_h"]))
    forecast_h = forecast["forecast_h"]
    early = [c for c in checks if c["h"] <= forecast_h + 1e-9]
    # the card's own trend forecast beside it, at the same hour: the drift ratio's history alone, fitted on hours (the servo card's Forecast)
    trend = None if calibrated is None else cards.check_drift("servo", early[-1]["live_x_floor"], calibrated, ratio_threshold,
                                                              history=[(c["h"], c["ratio"]) for c in early])

    recal = None
    if alarm is not None and commissioned is not None:
        # WHY fitted, not the re-measured gap plugged in (2026-11-05, twin C): a replay's error is a jagged function of the gap, and the
        # gap measured at the alarm (2.3625 mrad) landed on a spike: 1.169x against the 1.1 gate, while twins 0.025 mrad either side
        # scored 0.95-1.06. So the gap is searched near the measurement on the alarm check and scored on the NEXT check (held out).
        def measured(label):
            out = {}
            for n in names:
                noise = P.noise_rng(real.seed, "check", label, n)
                link = P.link_of(replays[(label, n)])
                out[n] = (link + noise.normal(0.0, real.noise["link_camera_rad"], link.size), link + noise.normal(0.0, real.noise["link_camera_rad"], link.size))
            return out

        at = next(c for c in checks if c["h"] == alarm)
        candidates = at["b_hat_rad"] + np.arange(-0.1e-3, 0.1e-3 + 1e-12, 0.025e-3)
        rp = P.replay(runs, {f"recal{i}": P.twin({**commissioned_values, "backlash_rad": float(b)}, f"recalibrated-{i}") for i, b in enumerate(candidates)}, workers=workers)
        fit_on = measured(f"h{alarm:g}")
        scores = [rms(np.concatenate([P.link_of(rp[(f"recal{i}", n)]) - fit_on[n][0] for n in names])) for i in range(len(candidates))]
        best = int(np.argmin(scores))
        score_h = alarm + mon["check_every_h"] if any(c["h"] == alarm + mon["check_every_h"] for c in checks) else alarm
        held = measured(f"h{score_h:g}")
        live = rms(np.concatenate([P.link_of(rp[(f"recal{best}", n)]) - held[n][0] for n in names])) / rms(np.concatenate([held[n][1] - held[n][0] for n in names]))
        ratio = cards.check_drift("servo", live, calibrated, ratio_threshold)
        # the gap check on the next check, against the recalibrated gap: the alarm cleared in its own units
        again = gap_verdict(next(c for c in checks if c["h"] == score_h)["b_hat_rad"], commissioned=float(candidates[best]), allowance=limit)
        recal = {"h": alarm, "backlash_rad": float(candidates[best]), "measured_gap_rad": at["b_hat_rad"], "scored_at_h": score_h,
                 "rule": "the gap searched over the measured gap +-0.1 mrad (0.025 mrad steps) on the alarm check's link error, scored on the next check",
                 "live_x_floor": live, "ratio": float(ratio.ratio), "ratio_status": ratio.status,
                 "gap_growth_rad": again["growth_rad"], "status": again["status"]}

    duty = torque_revolutions_per_hour(replays, names, "h0", check_seconds)
    wear_rung = next(r for r in reg.rungs("servo") if r.key == "M5.wear")
    wear = next(p.wear for p in wear_rung.parameters if p.name == "backlash_rad")
    k_hat = forecast["rate"]
    gap_spec = {"id": "servo.gap_drift", "units": "parameter", "parameter": "backlash_rad", "message": reg.DRIFT_MESSAGE,
                "forecast": "the gap's history on hours, solved for the commissioned gap plus the allowance (type_cards wear_usage_at)"}
    doc = {
        "schema": "sysid.drift/2", "name": "backlash_wear", "example": P.EXAMPLE,
        "title": "Backlash wear on CAN 11: detected after the fact vs forecast ahead",
        "check_every_h": mon["check_every_h"], "horizon_h": mon["horizon_h"], "early_life_h": mon["early_life_h"],
        "check": mon["check"], "check_runs": names, "check_seconds": round(check_seconds, 1),
        "station": description.manifest["record"]["station"], "allowance_rad": limit, "allowance": allowance, "commissioned_gap_rad": gap0,
        "commissioned_from": ("the commissioning fit's M4 gap: backlash_from_gaps over the train runs, the routine every check runs" if commissioned is not None
                              else "the reversals routine's gap over the train runs (backlash_from_gaps); no twin: the regression commissioned none"),
        "threshold_rule": (f"the servo's gap drift (type_cards servo.gap_drift, dm.parameter_drift): a check's gap less the commissioned gap "
                           f"({1e3 * gap0:.3f} mrad) <= {1e3 * limit:.3f} mrad, the station's allowance ({allowance['rule']}, "
                           f"{allowance.get('arcmin', 60 * math.degrees(limit)):g} arcmin); the camera's floor is not in it. The alarm warns on this "
                           f"or the fidelity ratio below, whichever comes first"),
        "diagnostic": gap_spec,
        "checks": checks,
        "detector_alarm_h": alarm, "gap_alarm_h": gap_alarm, "alarm_by": alarm_by, "actual_crossing_h": actual,
        "alarm_rule": "the servo's drift alarm warns on either check, the gap check or the fidelity ratio, whichever comes first (servo_verdict); "
                      "detector_alarm_h is that hour, gap_alarm_h and ratio_alarm_h each check's own, alarm_by who fired it",
        "actual_rule": "the first hour the hidden gap (world.json's wear line and its process noise) is the allowance past the commissioned gap, interpolated between checks",
        "rate_recovered": k_hat, "rate_ci95": list(forecast["rate_ci95"]), "b0_recovered_rad": forecast["b0_rad"],
        "rate_true": hidden_wear["rate_rad_per_h"], "b0_true_rad": hidden_wear["b0_rad"],
        "predicted_at_h": forecast_h, "predicted_crossing_h": forecast["predicted_crossing_h"], "remaining_h_at_prediction": forecast["remaining_h"],
        "plan_by_h": forecast["plan_by_h"],
        "plan_by_rule": "the hour the wear line's upper 95 % confidence band (slope and intercept, Student's t) reaches the commissioned gap plus the allowance: the early edge maintenance plans against",
        "forecast": {"checks_h": forecast["checks_h"], "horizon_h": FORECAST_HORIZON_H, "rolling": forecast["rolling"],
                     "issue_rule": f"re-made at every check from {MIN_CHECKS} on; issued at the first whose crossing is within {FORECAST_HORIZON_H:g} h, hour {mon['early_life_h']:g} at the latest",
                     "rule": "the gap's history up to the issue hour fitted on hours (the servo card's M5.wear backlash term, linear at the check's fixed duty), solved for the hour it reaches the commissioned gap plus the allowance"},
        "gap_at_threshold_rad": level,
        # the fidelity view (the alarm's second check), on the same checks. `threshold` is its ratio threshold: the site's wear chart draws the ratio against it
        "threshold": ratio_threshold, "calibrated_x_floor": calibrated, "ratio_alarm_h": ratio_alarm, "ratio_crossing_h": ratio_crossing,
        "ratio_rule": (f"the alarm's second check, beside the gap check (either warns): live fidelity (twin vs camera) / the camera's floor, / its hour-0 value, against the servo card's "
                       f"drift diagnostic (servo.drift, {ratio_threshold:g}); its sensitivity is the camera's"),
        "card_trend_remaining_h": None if trend is None else trend.remaining, "card_trend_unit": None if trend is None else trend.unit,
        "recalibrated": recal,
        "wear": {"card": "servo", "rung": "M5.wear", "parameter": "backlash_rad", "usage": wear.usage, "unit": wear.unit, "law": wear.law, "rate": wear.rate,
                 "duty_nm_rev_per_h": duty, "rate_recovered_per_nm_rev": k_hat / duty if duty else None, "rate_true_per_nm_rev": hidden_wear["rate_rad_per_h"] / duty if duty else None,
                 "note": "the card's law is Archard's (load x sliding distance); at the check's fixed duty it is linear in hours: rate per N.m.rev = rate per hour / duty"},
        "provenance": {**result.provenance(P.EXAMPLE), "seconds": round(time.monotonic() - started, 1),
                       "commissioned_twin": None if commissioned is None else commissioned.digest(),
                       "twin_of_record": P._rack()[0], "twin_of_record_digest": P._rack()[1].digest(), "identify_sealed": True},
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


# WHY 96 h (2026-11-05, twin C): twice the 48 h lead the maintenance gate asks for (acceptance.json drift.backlash_wear.lead_h_min),
# so a forecast issued when it says 96 h are left keeps the 48 h even if it is that late; a fixed hour (168) cannot lead a crossing
# that comes sooner (twin C crosses at 197 h: 29 h of lead).
FORECAST_HORIZON_H = 96.0
MIN_CHECKS = 5  # a wear line through fewer checks (48 h) is noise


def issue_forecast(checks, *, level: float, latest_h: float, horizon_h: float = FORECAST_HORIZON_H) -> dict:
    """The rolling forecast: wear_forecast at every check from the MIN_CHECKS-th on, each from the checks at or before it; issued at
    the first whose predicted crossing is within `horizon_h` of it, or at `latest_h` at the latest. Returns that forecast with
    forecast_h (the issue hour) and rolling ([hour, predicted] for every forecast made up to it)."""
    ordered = sorted(checks, key=lambda c: c["h"])
    rolling, made = [], None
    for c in ordered[MIN_CHECKS - 1:]:
        h = float(c["h"])
        made = wear_forecast(ordered, forecast_h=h, level=level)
        rolling.append([h, made["predicted_crossing_h"]])
        if (made["predicted_crossing_h"] is not None and made["predicted_crossing_h"] - h <= horizon_h) or h >= latest_h - 1e-9:
            break
    return {**made, "forecast_h": float(rolling[-1][0]), "rolling": rolling}


def wear_forecast(checks, *, forecast_h: float, level: float) -> dict:
    """The wear-aware forecast from the checks at or before `forecast_h` only (later ones are never read): the gap's history fitted on
    hours gives the wear line (the servo card's M5.wear term, linear at the check's fixed duty), solved for the hour it reaches `level`,
    the commissioned gap plus the allowance (type_cards wear_usage_at), and the hour its upper 95 % band does (the plan-by hour).

    WHY the line alone (2026-11-07): with the threshold in the gap's units, the hour the check will warn is the hour the gap reaches its
    level; the gap -> drift-ratio curve (the commissioned twin replayed at 45 gaps, a ratio^2 = 1 + d^2 + 2 rho d model fitted to it and to
    the checks, 2026-11-05) translated the ratio's threshold into a gap, and the camera's floor sat inside that translation."""
    from type_cards import registry as reg  # noqa: PLC0415

    gaps = [(float(c["h"]), float(c["b_hat_rad"])) for c in checks if c["h"] <= forecast_h + 1e-9]
    k, b0, k_ci = line_fit(gaps)
    return {"checks_h": [h for h, _ in gaps], "rate": k, "rate_ci95": list(k_ci), "b0_rad": b0, "gap_at_threshold_rad": float(level),
            "predicted_crossing_h": reg.wear_usage_at(b0, k, float(level), "linear"), "remaining_h": reg.usage_remaining(gaps, float(level), "linear"),
            "plan_by_h": band_hour(gaps, float(level), after=forecast_h)}


def band_hour(points, level: float, *, after: float, horizon: float = 1e4) -> float | None:
    """The first hour after `after` at which the upper 95 % confidence band of the least-squares line through `points` reaches `level`
    (bisection on the band, which rises monotonically past the data for a rising line); None when it never does within `horizon`."""
    from scipy import stats  # noqa: PLC0415

    x, y = (np.array([p[i] for p in points], float) for i in (0, 1))
    fit = stats.linregress(x, y)
    n, xm = x.size, float(x.mean())
    s = math.sqrt(float(np.sum((y - (fit.intercept + fit.slope * x)) ** 2)) / (n - 2))
    sxx, t = float(np.sum((x - xm) ** 2)), float(stats.t.ppf(0.975, n - 2))

    def upper(h: float) -> float:
        return fit.intercept + fit.slope * h + t * s * math.sqrt(1.0 / n + (h - xm) ** 2 / sxx)

    if upper(after) >= level:
        return float(after)
    if upper(horizon) < level:
        return None
    lo, hi = float(after), float(horizon)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lo, hi = (lo, mid) if upper(mid) >= level else (mid, hi)
    return float(hi)


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
