"""CAN 11, the rack's pendulum servo: its own test schedule played through its own twin at a hidden truth, fitted rung by rung.

Everything physical is bam_rack_twin's, imported from bam_ws main and never copied: the joint description and the test schedule
(bam_rack_twin.schedule: describe_station, build_schedule, the frozen 581ffd3e), the twin (TwinParameters on a bare hinge behind
bam_sim's 30 kHz moteus PID, gear_backlash's gap hinge), the replayer (budget.Replayer, worker processes), the synthetic command
tape of a planned run (schedule._synthetic_run), the smoother (identify.filtered: one Savitzky-Golay on every channel, torque read
at a shift) and the block bootstrap (identify.block_bootstrap). The "real" CAN 11 is that twin at world.json's truth: BAM's M3
friction (a Stribeck curve) and 2 mrad of gear backlash, under the board's own gains (kp 200, ki 16000, kd 4 N.m/rev), with the
encoder, the torque and the link camera on tags 8-12 each carrying noise.

WHY a regression and not bam_rack_twin.identify's three quasi-static fits (measured 2026-11-05, the stock fit is still run and
reported beside it): under CAN 11's ki 16000 the joint limit-cycles through its slow gravity sweeps (qd std 0.1-0.24 rad/s at a
0.08 rad/s command), so the sweep's tau = G sin(q - bottom) + Fc sgn(qd) reads inertia as load (G +9.5 % on an M2 truth, +16 % on
this one) and the plateau fit reads the Stribeck curve as a negative viscous term. One inverse-dynamics regression over every train
run, tau(t + shift) = J qdd + G sin(q - bottom) + friction(qd) on the stock smoother's grid, uses the oscillation as
excitation instead of fighting it.

Rungs (sysid.cards: robotparts' actuator layers): M2 Coulomb + viscous, M3 + Stribeck (vs profiled), M4 + the gear gap from the
motor encoder minus the link camera. The nominal model is M2's terms at the description's values (robotparts' "M1, the datasheet").
"""

from __future__ import annotations

import dataclasses
import functools
import json
import math
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from sysid import cards, result
from sysid import world as hidden

EXAMPLE = "pendulum_can11"
JOINT = "can11_hinge"
SCENES = Path.home() / ".cache" / "sim2real" / "sysid" / "scenes"
# WHY 0.03 rad/s: below it the joint can stick, and a sticking joint's friction is anywhere in [-Fs, Fs]: no regressor describes it
MOVING_RAD_S = 0.03
WINDOW = 21  # the stock smoother's window (identify.INERTIA_WINDOW_SAMPLES): 105 ms on its 5 ms grid
# WHY 0.97 of the current limit: a requested torque past the board's current ceiling is not the torque the joint got
CEILING_FRACTION = 0.97
BLOCK_ROWS = 100  # 0.5 s blocks on the 5 ms grid (identify.BOOTSTRAP_BLOCK_S)
RESAMPLES = 200
VS_GRID = np.geomspace(0.02, 0.8, 41)
RUNGS = ("M0", "M2", "M3", "M4")  # the servo card's physics rungs the hidden truth's terms reach (M5 electrics: the board's known knobs)
SERVO_KEYS = ("gravity_nm", "gravity_bottom_rad", "armature_kg_m2", "frictionloss_nm", "damping_nm_s_rad",
              "friction_stribeck_drop_nm", "friction_stribeck_speed_rad_s", "backlash_rad")


@functools.lru_cache(maxsize=1)
def _rack():
    """(label, twin of record, station), loaded once per process. WHY once (measured 2026-11-05): record_twin re-executes
    docs/gates_1029.py from disk on every call, so a peer's commit to bam_ws main landing mid-run mixed two versions of the rack twin
    in one process (an AttributeError on a field the in-memory Station did not have yet)."""
    from bam_rack_twin import schedule as rack_schedule  # noqa: PLC0415
    from bam_rack_twin.stations import DEFAULT_RECORD_PATH, load_stations  # noqa: PLC0415

    label, record = rack_schedule.record_twin(11)
    station = next(s for s in load_stations(DEFAULT_RECORD_PATH) if s.can_id == 11)
    return label, record, station


# --- plan ---------------------------------------------------------------------------------------------------------------------

@dataclass
class Plan:
    document: dict
    train: list[dict]
    held_out: list[dict]
    check: list[dict]
    coverage: dict
    digest: str
    frozen_digest: str


def plan(description) -> Plan:
    """CAN 11's own schedule, built from its joint description (bam_rack_twin.schedule.build_schedule, seed 0): every FB run of the
    train split identifies, every FB run of the held-out split scores; the H2 operate runs are the deployed check."""
    from bam_rack_twin import schedule as rack_schedule  # noqa: PLC0415
    from type_cards import coverage as cov  # noqa: PLC0415

    document = rack_schedule.build_schedule(description.station_description, seed=0)
    train = [r for r in document["runs"] if r["split"] == "train" and r["mode"] == "fb"]
    held_out = [r for r in document["runs"] if r["split"] == "held_out" and r["mode"] == "fb"]
    check = [r for r in held_out if r.get("held_out_set") == "H2"]
    used = dict(document, runs=train + held_out)
    by_id = {t["id"]: t for t in document["trajectories"]}
    cover = {}
    for split in ("train", "held_out"):
        c = cov.servo_coverage(used, split)
        cover[split] = {"pct": c.pct, "visited": c.visited, "reachable": c.reachable, "samples": c.samples, "axes": c.axes,
                        "unplanned": list(c.unplanned)}
    coverage = {**cover, "function": "type_cards.coverage.servo_coverage (bam_rack_twin.schedule's rule, byte for byte)",
                "rule": "share of the reachable (q, qd, qdd) cells any planned target visits; load torque a marginal, temperature unplanned",
                "edges": document["coverage"]["edges"], "axes": document["coverage"]["axes"],
                "plane": _plane(used, by_id, document["coverage"]["edges"])}
    frozen = json.loads(Path(description.schedule["frozen"]).read_text())
    return Plan(document, train, held_out, check, coverage, document["digest"], frozen["digest"])


def _plane(document, by_id, edges) -> dict:
    """The (q, qd) occupancy of the train split's targets: what the card's coverage map draws."""
    q_edges, qd_edges = np.asarray(edges[0]), np.asarray(edges[1])
    counts = np.zeros((q_edges.size - 1, qd_edges.size - 1), int)
    for run in document["runs"]:
        if run["split"] != "train":
            continue
        target = by_id[run["trajectory"]]["target"]
        h, _, _ = np.histogram2d(target["q"], target["qd"], bins=(q_edges, qd_edges))
        counts += h.astype(int)
    return {"q_edges": q_edges.tolist(), "qd_edges": qd_edges.tolist(), "counts": counts.tolist()}


# --- the real hardware (the hidden truth) ---------------------------------------------------------------------------------------

@dataclass
class RunData:
    name: str
    family: str
    kind: str
    output: object  # bam_rack_twin OutputRun with the measured channels
    q_link: np.ndarray


@dataclass
class Measured:
    train: dict[str, RunData]
    held_out: dict[str, RunData]
    repeat: dict[str, np.ndarray]  # a second camera draw of every held-out run: the floor


def synthetic_runs(description, plan: Plan, rows: list[dict]) -> dict:
    """The command tape each planned run sends, as bam_rack_twin.schedule.replay_schedule builds it (an OutputRun whose measured
    channels are placeholders until a twin answers it)."""
    from bam_rack_twin import schedule as rack_schedule  # noqa: PLC0415

    _, _, station = _rack()
    by_id = {t["id"]: t for t in plan.document["trajectories"]}
    out = {}
    for run in rows:
        out[run["run"]], _ = rack_schedule._synthetic_run(run["run"], station, description.station_description, by_id[run["trajectory"]],
                                                          plan.document["modes"][run["mode"]], run["kp_level"])
    return out


def replay(runs: dict, twins: dict, *, workers: int) -> dict:
    from bam_rack_twin.budget import Replayer  # noqa: PLC0415

    _, _, station = _rack()
    SCENES.mkdir(parents=True, exist_ok=True)
    return Replayer(runs, JOINT, station.output_pid(), SCENES, workers, 0.0).replays(twins, sorted(runs))


def twin(values: dict, version: str):
    """A bare-hinge TwinParameters from servo values (the SERVO_KEYS), on the twin of record's board knobs (current loop, command
    delay, current limit, the hard friction constraint): the description's known configuration, never fitted."""
    _, record, _ = _rack()
    drop = values.get("friction_stribeck_drop_nm") or None
    gap = values.get("backlash_rad") or None
    known = _known()
    return dataclasses.replace(
        record, version=version, armature_kg_m2=float(values["armature_kg_m2"]), frictionloss_nm=float(values["frictionloss_nm"]),
        damping_nm_s_rad=max(0.0, float(values["damping_nm_s_rad"])), gravity_nm=float(values["gravity_nm"]),
        gravity_bottom_rad=float(values["gravity_bottom_rad"]), friction_lugre=None,
        friction_stribeck_drop_nm=drop, friction_stribeck_speed_rad_s=float(values["friction_stribeck_speed_rad_s"]) if drop else None,
        backlash_rad=gap, rotor_inertia_fraction=known["rotor_inertia_fraction"] if gap else None,
        output_friction_fraction=known["output_friction_fraction"] if gap else None)


def _known() -> dict:
    from sysid import describe  # noqa: PLC0415

    return describe.load(EXAMPLE).known


def noise_rng(seed: int, *names) -> np.random.Generator:
    return np.random.default_rng([seed, *(zlib.crc32(str(n).encode()) for n in names)])


def measured_run(name: str, family: str, kind: str, synthetic, rp, noise: dict, rng) -> RunData:
    n = rp.t.size
    link = camera_view(rp.t, rp.q_link if rp.q_link is not None else rp.q)
    q = rp.q + rng.normal(0.0, noise["encoder_rad"], n)
    quantum = hidden.perturbation("encoder_quantised")  # the noise ladder's encoder variant (sysid/noise_ladder.json); None outside it
    if quantum is not None:
        q = np.round(q / quantum) * quantum
    output = dataclasses.replace(synthetic, t=rp.t, q=q, qd=rp.qd + rng.normal(0.0, noise["speed_rad_s"], n),
                                 tau=rp.tau + rng.normal(0.0, noise["torque_nm"], n), mode=rp.mode)
    return RunData(name, family, kind, output, link + rng.normal(0.0, noise["link_camera_rad"], n))


def camera_view(t: np.ndarray, link: np.ndarray) -> np.ndarray:
    """The link angle as the camera reports it: itself, or, while the noise ladder's camera_late variant runs, held a delay behind."""
    late = hidden.perturbation("camera_late")
    if late is None:
        return link
    lag = int(round(late / float(np.median(np.diff(t)))))
    return np.concatenate([np.repeat(link[:1], lag), link[:-lag]]) if lag else link


class RealWorld:
    """CAN 11 as the simulator plays it at the hidden truth."""

    def __init__(self, description, *, workers: int = 6):
        self.description = description
        self.workers = workers
        doc = hidden.load(EXAMPLE)
        self.truth = doc["truth"]
        self.noise = doc["noise"]
        self.seed = doc["seed"]
        self.drift = doc.get("drift", {})

    def twin(self, backlash_rad: float | None = None, version: str = "truth"):
        values = {key.split(".", 1)[1]: value for key, value in self.truth.items()}
        if backlash_rad is not None:
            values["backlash_rad"] = backlash_rad
        return twin(values, version)

    def measure(self, plan: Plan) -> Measured:
        rows = plan.train + plan.held_out
        runs = synthetic_runs(self.description, plan, rows)
        replays = replay(runs, {"truth": self.twin()}, workers=self.workers)
        by_id = {t["id"]: t for t in plan.document["trajectories"]}
        train, held, repeat = {}, {}, {}
        for run in rows:
            name = run["run"]
            rp = replays[("truth", name)]
            rng = noise_rng(self.seed, "commissioning", name)
            data = measured_run(name, run["family"], by_id[run["trajectory"]]["runner_kind"] or "", runs[name], rp, self.noise, rng)
            (train if run["split"] == "train" else held)[name] = data
            if run["split"] == "held_out":
                link = camera_view(rp.t, rp.q_link if rp.q_link is not None else rp.q)
                repeat[name] = link + noise_rng(self.seed, "repeat", name).normal(0.0, self.noise["link_camera_rad"], rp.t.size)
        return Measured(train, held, repeat)


# --- identification (measurements and the description only) ------------------------------------------------------------------

@dataclass
class Fit:
    values: dict[str, dict[str, float]]
    ci95: dict[str, dict[str, tuple[float, float]]]
    rows: int
    runs: int
    methods: dict[str, str]
    stock: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Gap:
    """The gear gap from load reversals seen by the link camera (the catalog's servo.backlash_reversals_camera): `rad` the distance
    between the two contact levels of (motor encoder - link camera), `levels` those two levels, `ci95` the bootstrap over runs."""
    rad: float
    levels: tuple[float, float]
    ci95: tuple[float, float]
    runs: int


GAP_METHOD = ("two-means of (motor encoder - link camera) over every train row: the two contact levels, each re-taken as the median within a "
              f"quarter gap of it; the gap is their distance; 95 % by a bootstrap over runs ({RESAMPLES} resamples)")


def gear_gap(measurements: dict[str, RunData]) -> Gap:
    """The gap between the motor encoder and the link camera over the train runs (backlash_from_gaps), with its bootstrap interval.
    identify() calls it when no earlier routine handed it the gap; the schedule's servo.backlash_reversals_camera step calls it first."""
    gaps = [run.output.q - run.q_link for run in measurements.values()]
    gap_hat, levels = backlash_from_gaps(gaps, levels=True)
    # WHY its own seeded generator (as identify() drew it before the split, 2026-11-17): the interval is the same numbers wherever it is drawn
    rng = np.random.default_rng(20261105)
    gap_boot = np.array([backlash_from_gaps([gaps[i] for i in rng.integers(0, len(gaps), len(gaps))]) for _ in range(RESAMPLES)])
    return Gap(float(gap_hat), (float(levels[0]), float(levels[1])), tuple(float(v) for v in np.percentile(gap_boot, (2.5, 97.5))), len(gaps))


def identify(description, measurements: dict[str, RunData], *, workers: int = 8, gap: float | None = None) -> Fit:
    """M2 and M3 by one inverse-dynamics regression over every train run on the stock smoother's grid, M4 by the gap between the
    motor encoder and the link camera; 95 % intervals by the stock moving-block bootstrap (0.5 s blocks, every run its own share).
    `workers`: the replay pool of the friction polish (refine_friction). WHY a keyword with the old 8 as its default (2026-11-15, the
    real backend): each replay is one deterministic (twin, run) job, so the pool's size moves no number; a lane beside the powered rack
    caps it at 2 (sim2real.real), and every existing caller keeps its 8.

    `gap` (rad): the gear gap a routine before this one found (the schedule's servo.backlash_reversals_camera, gear_gap()), or the prior
    that serves when that routine did not run. M4 regresses on the rows within 30 % of THIS gap of a contact level, carries it as its
    backlash, and leaves its interval to the routine that found it. None (every caller before 2026-11-17): the gap is found here."""
    from bam_rack_twin import identify as rack_identify  # noqa: PLC0415

    board = _rack()[1]  # the twin of record's board knobs: the description's known configuration (description.known)
    # the board's current loop (a first-order lag) stands between the requested torque the board reports and the joint
    shift = -1.0 / (2.0 * math.pi * board.current_loop_hz)
    ceiling = CEILING_FRACTION * board.current_limit[0] * board.current_limit[1]
    found = gear_gap(measurements) if gap is None else None
    if found is not None:
        gap_hat, levels = found.rad, found.levels
    else:
        # the contact levels are where the data sits (a data selection, never a parameter); the gap's width is the one handed in
        gap_hat, levels = float(gap), backlash_from_gaps([run.output.q - run.q_link for run in measurements.values()], levels=True)[1]
    q, qd, qdd, tau, sgn, contact, groups = [], [], [], [], [], [], []
    start = 0
    for run in measurements.values():
        f = rack_identify.filtered(run.output, WINDOW, (shift,))
        # WHY rows a half window from any stuck row are dropped (the arm's fix, swept here 2026-11-05): inside the smoother's window a
        # stuck joint's friction (anywhere in [-Fs, Fs]) leaks into the moving rows' smoothed torque, and under CAN 11's limit cycle
        # the joint sticks and slips all the time
        stuck = np.abs(f.qd) <= MOVING_RAD_S
        near_stuck = np.convolve(stuck.astype(float), np.ones(WINDOW), mode="same") > 0
        keep = ~near_stuck & (np.abs(f.tau) < ceiling)
        if keep.sum() < BLOCK_ROWS:
            continue
        # WHY every row when the gap handed in is none (a prior of 0 when the gap routine did not run): with no gap the gear is always in contact
        in_contact = gear_in_contact(run, f, shift, levels, gap_hat) if gap_hat > 0 else np.ones(f.q.size, bool)
        q.append(f.q[keep]); qd.append(f.qd[keep]); qdd.append(f.qdd[keep]); tau.append(f.tau[keep]); sgn.append(f.sign_qd[keep])
        contact.append(in_contact[keep])
        groups.append(np.arange(start, start + int(keep.sum())))
        start += int(keep.sum())
    q, qd, qdd, tau, sgn, contact = (np.concatenate(x) for x in (q, qd, qdd, tau, sgn, contact))
    # WHY no torque-offset column: over CAN 11's +-0.33 rad swing G sin(q - bottom) is nearly G (q - bottom), so a constant torque is
    # collinear with the bottom (measured 2026-11-05: with the column, bottom came out -0.539 for a true -0.350); the stock gravity
    # fit has none either. A real torque-estimate bias would land in the bottom: the oracle cannot tell them apart over this range.
    base = np.column_stack([qdd, np.sin(q), np.cos(q), sgn, qd])

    def m0(rows):
        # the servo card's M0: rigid inertia and gravity under the board's PD, no friction term
        c, *_ = np.linalg.lstsq(base[rows][:, :3], tau[rows], rcond=None)
        return np.array([c[0], math.hypot(c[1], c[2]), math.atan2(-c[2], c[1])])

    def m2(rows):
        c, *_ = np.linalg.lstsq(base[rows], tau[rows], rcond=None)
        return np.array([c[0], math.hypot(c[1], c[2]), math.atan2(-c[2], c[1]), c[3], c[4]])

    def m3_at(rows, vs):
        design = np.column_stack([base[rows], sgn[rows] * np.exp(-(qd[rows] / vs) ** 2)])
        c, residual, *_ = np.linalg.lstsq(design, tau[rows], rcond=None)
        sse = float(residual[0]) if residual.size else float(np.sum((design @ c - tau[rows]) ** 2))
        return c, sse

    def m3(rows, grid=VS_GRID):
        fits = [(m3_at(rows, vs), vs) for vs in grid]
        (c, _), vs = min(fits, key=lambda item: item[0][1])
        # WHY a golden-section refinement: the grid is 9 % apart; the profile is smooth near its minimum
        lo, hi = vs / 1.1, vs * 1.1
        for _ in range(30):
            a, b = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
            if m3_at(rows, a)[1] < m3_at(rows, b)[1]:
                hi = b
            else:
                lo = a
        vs = 0.5 * (lo + hi)
        c, _ = m3_at(rows, vs)
        # frictionloss in M3 is the static level Fs = Fc + drop (TwinParameters' Stribeck convention)
        return np.array([c[0], math.hypot(c[1], c[2]), math.atan2(-c[2], c[1]), c[3] + c[5], c[4], c[5], vs])

    rows = np.arange(q.size)
    blocks = [BLOCK_ROWS] * len(groups)
    est0 = m0(rows)
    boot0 = rack_identify.block_bootstrap(groups, m0, rows_per_block=blocks, resamples=RESAMPLES)
    est2 = m2(rows)
    boot2 = rack_identify.block_bootstrap(groups, m2, rows_per_block=blocks, resamples=RESAMPLES)
    est3 = m3(rows)
    local = np.geomspace(est3[6] / 1.6, est3[6] * 1.6, 15)
    boot3 = rack_identify.block_bootstrap(groups, lambda r: m3(r, local), rows_per_block=blocks, resamples=RESAMPLES // 2)
    # M4: the rigid terms again, on the rows where the gear is in contact. WHY (measured 2026-11-05, noise-free plants): on a rigid M3
    # plant the regression returns G to 0.14 %; with 2 mrad of gap the same regression reads G -6 %, Fs +16 %, the drop +39 %, because
    # while the motor crosses the gap it carries neither the link's weight nor its inertia. The lower rungs keep that bias (they have
    # no gap to explain it); M4, which knows the gap, regresses only where the motor drives the link.
    groups4 = [g[contact[g]] for g in groups]
    groups4 = [g for g in groups4 if g.size >= BLOCK_ROWS]
    rows4 = np.concatenate(groups4)
    est4 = m3(rows4)
    local4 = np.geomspace(est4[6] / 1.6, est4[6] * 1.6, 15)
    boot4 = rack_identify.block_bootstrap(groups4, lambda r: m3(r, local4), rows_per_block=[BLOCK_ROWS] * len(groups4), resamples=RESAMPLES // 2)

    names2 = ("armature_kg_m2", "gravity_nm", "gravity_bottom_rad", "frictionloss_nm", "damping_nm_s_rad")
    names3 = names2 + ("friction_stribeck_drop_nm", "friction_stribeck_speed_rad_s")
    ci = lambda boot, i: tuple(float(v) for v in np.percentile(boot[:, i], (2.5, 97.5)))  # noqa: E731
    names0 = names2[:3]
    values = {"M0": {**dict(zip(names0, map(float, est0))), "frictionloss_nm": 0.0, "damping_nm_s_rad": 0.0, "friction_stribeck_drop_nm": 0.0,
                     "friction_stribeck_speed_rad_s": None, "backlash_rad": 0.0},
              "M2": {**dict(zip(names2, map(float, est2))), "friction_stribeck_drop_nm": 0.0, "friction_stribeck_speed_rad_s": None, "backlash_rad": 0.0},
              "M3": {**dict(zip(names3, map(float, est3))), "backlash_rad": 0.0}}
    values["M4"] = {**dict(zip(names3, map(float, est4))), "backlash_rad": float(gap_hat)}
    refined, evaluations, cost = refine_friction(measurements, values["M4"], workers=workers)
    values["M4"].update(refined)
    intervals = {"M0": {n: ci(boot0, i) for i, n in enumerate(names0)},
                 "M2": {n: ci(boot2, i) for i, n in enumerate(names2)}, "M3": {n: ci(boot3, i) for i, n in enumerate(names3)},
                 "M4": {n: ci(boot4, i) for i, n in enumerate(names3)}}
    if found is not None:
        intervals["M4"]["backlash_rad"] = found.ci95
    methods = {
        "M0": "the same regression without friction terms: tau = J qdd + G sin(q - bottom) (the card's ideal rung, rigid under the board's PD)",
        "M2": f"tau(t {shift * 1e3:+.2f} ms) = J qdd + G sin(q - bottom) + Fc sgn(qd) + b qd over {q.size:,} moving rows of {len(groups)} train runs "
              "(identify.filtered's 5 ms grid, one Savitzky-Golay); block bootstrap",
        "M3": "the same regression + D sgn(qd) exp(-(qd/vs)^2), vs profiled (41-point grid, golden section); Fs = Fc + D",
        "M4": f"the gap: two clusters of (motor encoder - link camera) over every train row (bootstrap over runs); the M3 regression again on "
              f"the {rows4.size:,} rows where the gear is in contact (the smoothed gap at a contact level, a half window from any traversal); then the "
              f"static level and the drop polished by output error: Nelder-Mead on the motor encoder's RMS over the train operate runs replayed "
              f"through the twin ({evaluations} replays, {cost * 1e3:.3f} mrad)",
    }
    stock = stock_fit(measurements)
    return Fit(values, intervals, int(q.size), len(groups), methods, stock)


REFINE_FAMILIES = ("pickplace", "cycle", "jog", "sweep", "plateaus")


def refine_friction(measurements: dict[str, RunData], start: dict, *, workers: int = 8) -> tuple[dict, int, float]:
    """The friction constraint's static level and the Stribeck drop, polished by output error on the train operate runs.

    WHY (measured 2026-11-05, held-out sensitivity of the replay to each parameter at the truth): under CAN 11's ki 16000 a joint
    stops wherever its stiction band (Fs / kp ~ 30 mrad) lets the integrator break it free, so Fs off by 3 % moved the held-out link
    angle 4.6 mrad RMS and the drop off by 8 % moved it 3.1, while gravity, inertia, damping and the gap each moved it 0.3-0.5. A
    regression over moving rows can only extrapolate Fs to zero speed; the twin's own replay, matched to the motor encoder over the
    runs that stop and start, measures it. The intervals stay the regression's (the polish moves the point, not the spread).
    """
    from scipy.optimize import minimize  # noqa: PLC0415

    runs = {name: run.output for name, run in measurements.items() if run.family in REFINE_FAMILIES}
    names = sorted(runs)
    measured = {name: runs[name].q for name in names}
    count = [0]

    def cost(x):
        fs, drop = float(x[0]), float(x[1])
        if not (0.0 <= drop < fs):
            return 1.0
        count[0] += 1
        values = {**start, "frictionloss_nm": fs, "friction_stribeck_drop_nm": drop}
        replays = replay(runs, {"probe": twin(values, f"refine-{count[0]}")}, workers=workers)
        err = np.concatenate([replays[("probe", n)].q - measured[n] for n in names])
        return float(np.sqrt(np.mean(err ** 2)))

    x0 = np.array([start["frictionloss_nm"], start["friction_stribeck_drop_nm"]])
    fit = minimize(cost, x0, method="Nelder-Mead",
                   options={"initial_simplex": np.array([x0, x0 * [1.03, 1.0], x0 * [1.0, 1.08]]), "xatol": 1e-3, "fatol": 1e-6, "maxfev": 40})
    return {"frictionloss_nm": float(fit.x[0]), "friction_stribeck_drop_nm": float(fit.x[1])}, count[0], float(fit.fun)


def backlash_from_gaps(gaps, *, levels: bool = False):
    """The gear gap: the distance between the two contact levels of (motor encoder - link camera), by 1-D two-means; with
    `levels`, also the two levels."""
    g = np.concatenate([np.asarray(x, float) for x in gaps])
    lo, hi = np.percentile(g, (10, 90))
    for _ in range(50):
        split = 0.5 * (lo + hi)
        low, high = g[g <= split], g[g > split]
        if low.size == 0 or high.size == 0:
            return (0.0, (lo, hi)) if levels else 0.0
        new = (float(low.mean()), float(high.mean()))
        if abs(new[0] - lo) < 1e-12 and abs(new[1] - hi) < 1e-12:
            break
        lo, hi = new
    # WHY trimmed: the rows crossing the gap sit between the two levels and pull both means inward (read -5.7 % on a 2 mrad truth);
    # each level is re-taken as the median of the rows within a quarter gap of it
    width = hi - lo
    lo = float(np.median(g[np.abs(g - lo) < 0.25 * width]))
    hi = float(np.median(g[np.abs(g - hi) < 0.25 * width]))
    return (hi - lo, (lo, hi)) if levels else hi - lo


def gear_in_contact(run, f, shift: float, levels: tuple[float, float], gap: float) -> np.ndarray:
    """On identify.filtered's grid: True where the smoothed (motor - link) gap sits at a contact level (within 30 % of the gap of
    it) and no row within half the smoother's window is crossing the gap."""
    from bam_rack_twin import identify as rack_identify  # noqa: PLC0415
    from scipy.signal import savgol_filter  # noqa: PLC0415

    rows = np.nonzero(run.output.controlled)[0]
    t = run.output.t[rows]
    edge = int(round(rack_identify.INERTIA_EDGE_S / rack_identify.INERTIA_GRID_S))
    grid = np.arange(t[0] + abs(shift), t[-1] - abs(shift), rack_identify.INERTIA_GRID_S)
    g = savgol_filter(np.interp(grid, t, (run.output.q - run.q_link)[rows]), WINDOW, 3)[edge: grid.size - edge]
    at_level = (g >= levels[1] - 0.3 * gap) | (g <= levels[0] + 0.3 * gap)
    crossing = np.convolve((~at_level).astype(float), np.ones(WINDOW), mode="same") > 0
    out = at_level & ~crossing
    if out.size != f.q.size:  # the grid is identify.filtered's; refuse quietly mismatched rows rather than misalign them
        raise ValueError(f"{run.name}: contact grid has {out.size} rows, the smoother's {f.q.size}")
    return out


def stock_fit(measurements: dict[str, RunData]) -> dict:
    """bam_rack_twin.identify.identify_without_cad on the same train runs: the stock quasi-static fits, reported beside sysid's."""
    from bam_rack_twin import identify as rack_identify  # noqa: PLC0415

    _, _, station = _rack()
    runs = [run.output for run in measurements.values() if run.kind in ("gravity", "friction", "chirp")]
    try:
        ident = rack_identify.identify_without_cad(station, runs, held_out=set())
    except Exception as error:  # noqa: BLE001 - reported, never hidden
        return {"error": f"{type(error).__name__}: {error}"}
    out = {}
    for name, key in (("gravity_amplitude_nm", "gravity_nm"), ("gravity_bottom_rad", "gravity_bottom_rad"), ("axis_inertia_kg_m2", "armature_kg_m2"),
                      ("coulomb_nm", "frictionloss_nm"), ("viscous_nm_s_rad", "damping_nm_s_rad")):
        est = ident.estimates.get(name)
        if est is not None:
            out[key] = {"value": est.value, "ci95": list(est.ci95) if est.ci95 else None, "refused": est.reason or ""}
    return {"estimates": out, "runs": len(runs), "what": "bam_rack_twin.identify.identify_without_cad: gravity sweeps, plateaus, chirps"}


# --- held-out score -----------------------------------------------------------------------------------------------------------

def nominal_values(description) -> dict:
    return {key.split(".", 1)[1]: entry.value for key, entry in description.nominal.items()}


def link_of(rp) -> np.ndarray:
    return rp.q_link if rp.q_link is not None else rp.q


def score(description, plan: Plan, fit: Fit, measured: Measured, *, workers: int = 6) -> dict:
    """Every rung (and the nominal) replays the held-out FB runs; fidelity = link-camera RMS twin vs real ÷ the floor (two camera
    draws of one run), pooled over the runs; the motor encoder and the torque beside it."""
    runs = synthetic_runs(description, plan, plan.held_out)
    twins = {"nominal": twin(nominal_values(description), "nominal")}
    twins.update({key: twin(fit.values[key], f"sysid-{key}") for key in RUNGS})
    replays = replay(runs, twins, workers=workers)
    floor = np.concatenate([measured.repeat[n] - measured.held_out[n].q_link for n in sorted(runs)])
    floor_rms = float(np.sqrt(np.mean(floor ** 2)))
    out = {"floor_mrad": floor_rms * 1e3, "models": {}}
    for label in twins:
        link = np.concatenate([link_of(replays[(label, n)]) - measured.held_out[n].q_link for n in sorted(runs)])
        motor = np.concatenate([replays[(label, n)].q - measured.held_out[n].output.q for n in sorted(runs)])
        torque = np.concatenate([replays[(label, n)].tau - measured.held_out[n].output.tau for n in sorted(runs)])
        rms = lambda x: float(np.sqrt(np.mean(x ** 2)))  # noqa: E731
        # WHY None without noise (the noise ladder's 0x level): the floor is two camera draws of one run, zero when the camera is exact
        out["models"][label] = {"link_mrad": rms(link) * 1e3, "ratio": rms(link) / floor_rms if floor_rms > 0 else None, "motor_mrad": rms(motor) * 1e3,
                                "torque_nm": rms(torque)}
    out["runs"] = len(runs)
    out["seconds"] = round(sum(float(r.output.t[-1] - r.output.t[0]) for r in measured.held_out.values()), 1)
    return out


# --- the result document ------------------------------------------------------------------------------------------------------

def assemble(description, plan: Plan, fit: Fit, scores: dict, *, truth: dict) -> dict:
    from type_cards import registry as reg  # noqa: PLC0415

    ladder, ladder_source = cards.ladder("servo")
    scored = [r for r in ladder if r.key in RUNGS]
    held = {r.key: scores["models"][r.key]["ratio"] for r in scored}
    selected = reg.select_rung(tuple(scored), held)
    top = "M4"
    recovered = {f"can11.{name}": {"value": value, "ci95": fit.ci95[top].get(name), "rung": f"fitted with {top}", "method": fit.methods[top]}
                 for name, value in fit.values[top].items()}
    parameters = result.parameter_rows(EXAMPLE, description, truth, recovered)
    nominal = scores["models"]["nominal"]
    after = scores["models"][top]
    metrics = [
        result.metric(EXAMPLE, "held_out_link_fidelity", "Link angle, twin vs real (the camera on tags 8-12)", "x floor", nominal["ratio"], after["ratio"],
                      after_model=top, note=f"floor {scores['floor_mrad']:.3f} mrad (two camera draws of one run); {scores['runs']} held-out FB runs, {scores['seconds']} s"),
        result.metric(EXAMPLE, "held_out_motor_mrad", "Motor encoder, twin vs real", "mrad", nominal["motor_mrad"], after["motor_mrad"], after_model=top, gated=False),
        result.metric(EXAMPLE, "held_out_torque_rms_nm", "Reported torque, twin vs real", "N·m", nominal["torque_nm"], after["torque_nm"], after_model=top, gated=False),
    ]
    rung_rows = []
    for r in ladder:
        row = cards.rung_row(r, "servo")
        if r.key in RUNGS:
            row.update({"held_out_ratio": held[r.key], "limit": reg.TWINNED_LIMIT, "link_mrad": scores["models"][r.key]["link_mrad"],
                        "motor_mrad": scores["models"][r.key]["motor_mrad"], "values": fit.values[r.key],
                        "ci95": {k: list(v) for k, v in fit.ci95[r.key].items()}, "method": fit.methods[r.key]})
        rung_rows.append(row)
    stock = fit.stock
    for key, est in stock.get("estimates", {}).items():
        est["true"] = truth.get(f"can11.{key}")
        if est["true"] is not None and est.get("value") is not None and key not in ("frictionloss_nm", "damping_nm_s_rad"):
            est["error_pct"] = 100.0 * (est["value"] - est["true"]) / abs(est["true"])
    doc = {
        "title": description.manifest["title"], "subtitle": description.manifest.get("subtitle", ""), "summary": description.manifest.get("summary", ""),
        "description": _description_block(description),
        "tree": description.tree(),
        "schedule": {"source": description.schedule["source"], "digest": plan.digest, "frozen_digest": plan.frozen_digest,
                     "same_as_frozen": plan.digest == plan.frozen_digest,
                     "train": {"runs": len(plan.train), "seconds": round(sum(plan_seconds(plan, plan.train)), 1),
                               "families": sorted({r["family"] for r in plan.train})},
                     "held_out": {"runs": len(plan.held_out), "seconds": round(sum(plan_seconds(plan, plan.held_out)), 1),
                                  "families": sorted({r["family"] for r in plan.held_out})},
                     "coverage": plan.coverage},
        "parameters": parameters,
        "metrics": metrics,
        "rungs": rung_rows, "ladder_source": ladder_source, "card_ladders": cards.card_ladders(EXAMPLE, [r["key"] for r in parameters]),
        "selected_rung": selected.key if selected else None,
        "selection_rule": reg.SELECTION_RULE,
        "stock_fit": stock,
        "fit": {"rows": fit.rows, "runs": fit.runs},
        "provenance": {"twin_of_record": _rack()[0],
                       "twin_of_record_digest": _rack()[1].digest()},
        "notes": [
            "The real CAN 11 is bam_rack_twin's own twin at world.json's truth; the floor is the oracle's measurement noise alone (two camera draws of one deterministic run), so real floors are larger.",
            "The truth's friction is BAM's M3 Stribeck curve (static above sliding); the real CAN 11's twin of record has LuGre with its static level BELOW the sliding one, which a Stribeck drop cannot express.",
            "Torque ripple (robotparts' M4 layer holds ripple and backlash) is not in the truth and not fitted.",
        ],
    }
    return doc


def plan_seconds(plan: Plan, rows):
    by_id = {t["id"]: t for t in plan.document["trajectories"]}
    return [by_id[r["trajectory"]]["duration_s"] for r in rows]


def _description_block(description) -> dict:
    m = description.manifest["model"]
    return {"manifest": str(description.path.relative_to(description.path.parents[3])), "model": {k: m.get(k) for k in ("format", "path", "source", "sha256")},
            "record": description.manifest.get("record"), "sensors": description.manifest.get("sensors", []), "known": description.known,
            "components": len(description.components)}
