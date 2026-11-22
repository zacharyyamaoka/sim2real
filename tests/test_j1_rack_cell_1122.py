"""j1_rack judges the MEASURED cell before any motion, fail closed (sim2real.sim.homing.j1_rack: ``cell_judge_for``, ``judge_seek``,
``route_and_judge``).

WHY (2026-11-22): the 17:57Z step-8 J1 top-stop seek (j1_home_175659) drove the wrist into the right flood lamp; j1_rack's route judged the belt
only and its seek nothing at all. bam_ws 265d451ce adds ``fullarm_stops.cell_judge(geometry)`` (cell_frame.FULL_CELL_POSTS at plan margins) and
an opt-in ``cell=`` on ``plan_route`` / ``route_to_start``; j1_rack now passes it to the route, and judges the seek (J1 to -89.972 deg, every
other joint held, as a ``plan_route`` J1 step) and its return leg BEFORE home_j1. Any breach - or a deployment without the judge - is Refused
before motion, naming the member and the gap (CONTRACT v3.11: fail closed).

Two halves:
- the wiring, on a stand-in fullarm_stops (runs anywhere): what is judged, in which order, and that nothing moves on a breach;
- the real judge on today's seek (needs a bam_rack_twin with ``cell_judge``: bam_ws >= 265d451ce). The pose is lane F's: the seek's routed
  start read off j1_home_175659's bus trace through today's map (bam_ws tests/test_homing_cell_route_1122.py, HOMING_CELL_CHECK.md).

    cd ~/sim2real && env -u VIRTUAL_ENV .venv/bin/python -m pytest -q tests/test_j1_rack_cell_1122.py
    # the real-judge half, in a bam_rack_twin venv with a tree that has cell_judge on the path, e.g. lane F's:
    # (run from ~/sim2real: the rack tree's own cwd would shadow the PYTHONPATH tree)
    W=~/bam_ws-worktrees/rtp-cellcheck-1121; cd ~/sim2real && env -u VIRTUAL_ENV PYTHONPATH=$W/src/dev/bam_rack_twin:$W/src/core/mdp/agent/actuators/moteus_servo/src:$W/src/dev/bam_cad_descriptions:$HOME/sim2real/src ~/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_j1_rack_cell_1122.py
"""

from __future__ import annotations

import inspect
import math
import types

import pytest

from sim2real.sim.homing import j1_rack as jr
from sim2real.sim.homing.j1_home import J1, J1_READY_RAD, J1_STOP_DEG

# lane F's pose (URDF deg): the 17:57Z seek's routed start, the seek walks J1 from here to the stop with everything else held
SEEK_START_DEG = {"revolute_3": -2.23, "revolute_6": -25.01, "revolute_7": -13.04, "revolute_11": -5.68, "revolute_14": 89.23,
                  "revolute_17": -0.43, "revolute_5": 5.23}

try:  # the real judge: only where bam_rack_twin has it
    from bam_rack_twin.hardware import cell_frame as _cell_frame
    from bam_rack_twin.hardware import fullarm_stops as _real_fs
    from bam_rack_twin.hardware.board import Refused as _RealRefused

    HAVE_CELL = hasattr(_real_fs, "cell_judge")
except Exception:  # noqa: BLE001
    HAVE_CELL = False
needs_cell = pytest.mark.skipif(not HAVE_CELL, reason="bam_rack_twin with fullarm_stops.cell_judge (bam_ws >= 265d451ce) only")


# ---------------------------------------------------------------------------------------------------------------- a stand-in fullarm_stops


class Refused(Exception):
    pass


class FakeGeometry:
    def craig_of(self, q):
        return (q.get("revolute_6", 0.0), q.get("revolute_7", 0.0))

    def q_from(self, craig, *, j1, wrist, claw):
        return {"revolute_6": craig[0], "revolute_7": craig[1], J1: j1, "revolute_11": wrist[0], "revolute_14": wrist[1],
                "revolute_17": wrist[2], "revolute_5": claw}


def fake_fs(*, breach_below_deg=None, has_judge=True, calls=None):
    """plan_route / route_to_start that judge J1's straight line with ``cell``; the judge breaches below ``breach_below_deg`` (J1, deg)."""

    calls = [] if calls is None else calls

    def cell_judge(geometry):
        def judge(q):
            if breach_below_deg is not None and math.degrees(q[J1]) < breach_below_deg:
                return f"the frame: moving_finger -91.6 mm from the work lights's face (margin 33.2 mm; cell_frame's WHY) at J1 {math.degrees(q[J1]):+.1f}"
            return ""
        return judge

    def plan_route(q_here, craig_here, q_start, geometry, keep_out, *, cell=None, **_):
        calls.append(("plan_route", math.degrees(q_here[J1]), math.degrees(q_start[J1]), cell is not None))
        for i in range(41):
            q = {**q_here, J1: q_here[J1] + (q_start[J1] - q_here[J1]) * i / 40}
            problem = cell(q) if cell is not None else ""
            if problem:
                raise Refused(f"REFUSED: no safe route to the stops file's start (revolute_3 ...): j1: J1: {problem} ({i / 40:.0%} of the move)")
        return {"order": "j1", "steps": ["j1"], "tried": [{"order": "j1", "problem": ""}]}

    def route_to_start(bus, frames, geometry, start_q, *, cell=None, **_):
        calls.append(("route_to_start", cell is not None))
        bus.moved = True
        return {"routed": True}

    module = types.SimpleNamespace(plan_route=plan_route, route_to_start=route_to_start, board_angles=lambda last: last, calls=calls)
    if has_judge:
        module.cell_judge = cell_judge
    return module


class FakeBus:
    moved = False
    last = None


class FakeFrames:
    def __init__(self, q):
        self._q = q

    def q(self, boards, geometry):
        return dict(self._q)


def start(degrees=SEEK_START_DEG):
    return {k: math.radians(v) for k, v in degrees.items()}


# ---------------------------------------------------------------------------------------------------------------- the wiring


def test_a_deployment_without_the_judge_is_refused():
    """The arm pin (41a2676dc) has no cell_judge: refuse, never run unjudged."""
    with pytest.raises(Refused, match="cell_judge"):
        jr.cell_judge_for(fake_fs(has_judge=False), FakeGeometry(), refused=Refused)


def test_a_breaching_seek_is_refused_before_the_route_moves_anything():
    fs = fake_fs(breach_below_deg=-43.6)
    bus = FakeBus()
    judge = jr.cell_judge_for(fs, FakeGeometry(), refused=Refused)
    with pytest.raises(Refused) as refusal:
        jr.route_and_judge(bus, FakeFrames(start()), FakeGeometry(), start(), fs=fs, judge=judge, refused=Refused, tolerance_deg=8.0,
                           say=lambda text: None)
    assert not bus.moved and not any(call[0] == "route_to_start" for call in fs.calls)
    message = str(refusal.value)
    assert message.startswith("REFUSED before motion") and "work lights" in message and "-91.6 mm" in message  # the member and the gap
    assert f"{J1_STOP_DEG:+.1f}" in message  # which leg


def test_a_clear_seek_routes_with_the_cell_and_is_judged_again_from_the_measured_pose():
    fs = fake_fs(breach_below_deg=None)
    bus = FakeBus()
    judge = jr.cell_judge_for(fs, FakeGeometry(), refused=Refused)
    record = jr.route_and_judge(bus, FakeFrames(start()), FakeGeometry(), start(), fs=fs, judge=judge, refused=Refused, tolerance_deg=8.0,
                                say=lambda text: None)
    assert bus.moved and ("route_to_start", True) in fs.calls  # route_to_start got cell=
    plans = [call for call in fs.calls if call[0] == "plan_route"]
    # the seek and its return, from the planned start, then again from the measured pose after the route: all with the cell
    assert [(round(a, 2), round(b, 2), c) for _, a, b, c in plans] == [
        (-2.23, J1_STOP_DEG, True), (J1_STOP_DEG, round(math.degrees(J1_READY_RAD), 2), True)] * 2
    assert fs.calls.index(("route_to_start", True)) == 2  # between the planned and the measured judgements
    assert set(record) >= {"planned", "route", "measured"}


def test_real_run_judges_before_home_j1():
    """real_run builds the judge before the bus opens and calls route_and_judge (never fs.route_to_start bare) before home_j1."""
    source = inspect.getsource(jr.real_run)
    assert source.index("cell_judge_for(") < source.index("_open_real(")
    assert "fs.route_to_start(" not in source
    assert source.index("route_and_judge(") < source.index("home_j1(")


# ---------------------------------------------------------------------------------------------------------------- the real judge


@pytest.fixture(scope="module")
def geometry():
    return _real_fs.ClawGeometry()


@needs_cell
def test_todays_1757z_seek_is_refused_before_motion(geometry):
    """j1_home_175659's seek, as lane F replayed it, against today's measured cell: refused, naming the member and the gap."""
    judge = jr.cell_judge_for(_real_fs, geometry, refused=_RealRefused)
    here = jr.full_q(geometry, start(), refused=_RealRefused)
    with pytest.raises(_RealRefused) as refusal:
        jr.judge_seek(_real_fs, geometry, here, judge, refused=_RealRefused)
    message = str(refusal.value)
    print(message)
    assert message.startswith("REFUSED before motion") and "seek" in message
    assert " mm from the " in message and "face" in message  # cell_frame.frame_problem's member and gap


@needs_cell
def test_a_breach_free_seek_is_allowed(geometry):
    """The same seek against the members it clears (the left upright and its bracket: +110 / +126 mm in lane F's replay) plans: the check
    refuses breaches, not seeks."""
    clear = [post for post in _cell_frame.FULL_CELL_POSTS if post.name.startswith("left upright")]
    assert clear
    judge = _real_fs.cell_judge(geometry, posts=clear)
    here = jr.full_q(geometry, start(), refused=_RealRefused)
    record = jr.judge_seek(_real_fs, geometry, here, judge, refused=_RealRefused)
    assert [leg["to_deg"] for leg in record["legs"]] == [pytest.approx(J1_STOP_DEG), pytest.approx(math.degrees(J1_READY_RAD))]
