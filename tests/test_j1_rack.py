"""The rack entry point for J1's home (sim2real.sim.homing.j1_rack): the zero rule, the loop on the stand-in J1 (nominal, a power-up's
whole turns, the low-cap seed, an obstacle), and - where the rack's deployment venv is present - the entry point end to end on the twin
(the zero written ONLY through zero_writer -> homed_history.write_latest, into a copy of homed/), the dry run on the real files (read-only),
and J1HomeBus's one override. No port is ever opened.

    cd ~/sim2real && env -u VIRTUAL_ENV .venv/bin/python -m pytest -q tests/test_j1_rack.py
    # the rack-side checks run in the deployment venv (bam_rack_twin, moteus):
    cd ~/bam_ws-armhold/src/dev/bam_rack_twin && env -u VIRTUAL_ENV PYTHONPATH=$HOME/sim2real/src .venv/bin/python -m pytest -q -p no:cacheprovider $HOME/sim2real/tests/test_j1_rack.py
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

from sim2real.sim.homing import j1_rack as jr
from sim2real.sim.homing.j1_home import J1, J1_READY_RAD, J1_STOP_DEG, j1_home_sequence

DEPLOYMENT = jr.DEPLOYMENT
GAINS_FILE = DEPLOYMENT / "bam_rack_twin" / "hardware" / "j1_gains.py"
needs_gains = pytest.mark.skipif(not GAINS_FILE.is_file(), reason="the rack's j1_gains.py (deployment tree) is not here")
try:  # the rack's own package: only in its deployment venv
    import bam_rack_twin.hardware.zero_writer  # noqa: F401

    HAVE_RACK = True
except Exception:  # noqa: BLE001
    HAVE_RACK = False
needs_rack = pytest.mark.skipif(not HAVE_RACK or not jr.HOMED_DIR.is_dir(), reason="bam_rack_twin (its deployment venv) and the rack's homed/ only")

MAP = jr.J1Map(sign=1.0, zero_board_rad=0.25439, joint_at_zero_rad=0.0, homed_s=1794635898.0, sign_status="confirmed (5 capture runs)")
STOP_BOARD = MAP.board(math.radians(J1_STOP_DEG))


def gains():
    spec = importlib.util.spec_from_file_location("j1_gains_test", GAINS_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------------------------------------------- the zero rule


def test_the_reference_is_the_real_stalls_and_the_map_puts_the_stop_on_it():
    """The witness's reference (the 05:41Z / 05:56Z stalls) and the map's stop agree: a stall where the map puts the stop confirms it."""
    assert abs(jr.witness_deg(STOP_BOARD)) < 0.01
    decision = jr.zero_decision(STOP_BOARD, MAP, powered_up_since_home=False)
    assert decision["verdict"] == "confirmed" and abs(decision["shift_deg"]) < 0.01


@pytest.mark.parametrize("deg, powered, verdict", [
    (0.08, False, "confirmed"),  # the stop's give at the 11 N.m cap (CONFIRM_DEG's WHY)
    (0.3, False, "shift"),  # a sub-turn correction in the same frame
    (-36.0 * 2 + 0.2, True, "shift"),  # a power-up re-latched two turns: the witness still on the phase
    (36.0 + 0.1, False, "refused"),  # whole turns without a power-up: never written
    (36.0 + 0.1, None, "refused"),  # ... nor when the power-up time is unknown
    (2.0, False, "refused"),  # off the stop's rotor phase: an obstacle or a short stall
    (-39.97 + 36.0, True, "refused"),  # an obstacle 40 deg short sits 4 deg off the phase even after a power-up
])
def test_the_zero_rule(deg, powered, verdict):
    """``zero_decision``: the witness first (phase within 0.5 deg mod 36), then confirmed under 0.1 deg, a sub-turn shift, or whole turns only
    after a power-up. The stall reads ``deg`` short of the map's stop (the shift J1's zero needs)."""
    stall = MAP.board(math.radians(J1_STOP_DEG - deg))
    decision = jr.zero_decision(stall, MAP, powered_up_since_home=powered)
    assert decision["verdict"] == verdict, decision["why"]
    if verdict == "shift":
        assert decision["shift_deg"] == pytest.approx(deg, abs=1e-9)
        assert decision["turns"] == round(deg / 36.0)


def test_the_rack_sequence_is_the_routines_two_j1_steps_on_j1_alone():
    sequence = j1_home_sequence()
    assert sequence.joint_names == (J1,)
    assert [s.name for s in sequence.steps] == ["J1 seeks its stop", "J1 back to READY's angle"]
    seek, back = sequence.steps
    assert type(seek.done_when[0]).__name__ == "EffortStall" and seek.done_when[0].effort == 9.0
    assert seek.commands[0].max_effort == 11.0 and seek.define_position == {J1: pytest.approx(math.radians(J1_STOP_DEG))}
    assert back.commands[0].max_effort == 17.98 and back.commands[0].position == pytest.approx(J1_READY_RAD)


# ---------------------------------------------------------------------------------------------------------------- the loop on the stand-in J1


def home(bus, *, frame_known=True, j1map=MAP):
    g = gains()
    return jr.home_j1(bus, j1map, make_command=jr.twin_command(g), gravity_nm=g.j1_gravity_nm, frame_known=frame_known, say=lambda text: None)


@needs_gains
def test_the_home_stalls_on_the_stop_defines_it_and_returns_to_ready():
    g = gains()
    bus = jr.TwinJ1Bus(gravity_nm=g.j1_gravity_nm)
    record = home(bus)
    run = record["home"]
    assert run["outcome"] == "done", run["outcome"]
    assert [e["step"] for e in run["events"]] == ["J1 seeks its stop", "J1 back to READY's angle"]
    assert run["events"][0]["outcome"].startswith("EffortStall")
    assert abs(math.degrees(MAP.joint(run["stall_board_rad"])) - J1_STOP_DEG) < 0.15  # on the stop, pressed into its give
    assert abs(math.degrees(bus.q - J1_READY_RAD)) < 0.5  # back at READY's J1, in the defined frame = the true one here
    assert run["peak_effort_nm"] <= 11.0 + 1e-9 and -run["stall_effort_nm"] > 9.0  # pushing the way it seeks (-) past the rule
    assert jr.zero_decision(run["stall_board_rad"], MAP, powered_up_since_home=False)["verdict"] == "confirmed"
    assert "recovery" not in record


@needs_gains
def test_after_a_power_up_the_home_runs_without_feed_forward_until_the_stall_and_finds_the_whole_turns():
    """J1's board two rotor turns off the map (a power-up re-latch): the seek runs PD-only (the curve's frame is unknown), the stall defines
    the frame, J1 returns to the true READY, and the zero moves by the two turns - written only because J1 powered up since its home."""
    g = gains()
    bus = jr.TwinJ1Bus(gravity_nm=g.j1_gravity_nm, board_offset_rad=math.radians(-72.0))
    record = home(bus, frame_known=False)
    run = record["home"]
    assert run["outcome"] == "done" and run["feedforward"].startswith("none")
    assert abs(math.degrees(bus.q - J1_READY_RAD)) < 0.5
    decision = jr.zero_decision(run["stall_board_rad"], MAP, powered_up_since_home=True)
    assert decision["verdict"] == "shift" and decision["turns"] == 2 and abs(decision["shift_deg"] - 72.0) < 0.15
    assert jr.zero_decision(run["stall_board_rad"], MAP, powered_up_since_home=False)["verdict"] == "refused"


@needs_gains
def test_a_cap_under_gravity_never_records_a_stop_and_walks_back():
    """The low-cap seed on the rack's loop: a 5.5 N.m board limit with the feed-forward off stalls J1 short on gravity, the effort never passes
    9 N.m, the seek times out, nothing is defined, and J1 walks back to where it started."""
    g = gains()
    bus = jr.TwinJ1Bus(gravity_nm=g.j1_gravity_nm, cap_ceiling_nm=5.5)
    record = home(bus, frame_known=False)
    run = record["home"]
    assert "was not done within" in run["outcome"] and run["stall_board_rad"] is None
    assert record["recovery"]["outcome"] == "done"
    assert abs(bus.q - J1_READY_RAD) < math.radians(0.5)


@needs_gains
def test_an_obstacle_on_the_sweep_stalls_the_seek_and_the_witness_refuses_it():
    """EffortStall cannot tell the stop from an obstacle (both push back); the stop's rotor phase can: 40 deg short is 4 deg off it."""
    g = gains()
    bus = jr.TwinJ1Bus(gravity_nm=g.j1_gravity_nm, obstacle_joint_rad=math.radians(-50.0))
    run = home(bus)["home"]
    assert run["outcome"] == "done" and run["stall_board_rad"] is not None
    decision = jr.zero_decision(run["stall_board_rad"], MAP, powered_up_since_home=False)
    assert decision["verdict"] == "refused" and "rotor phase" in decision["why"]


# ---------------------------------------------------------------------------------------------------------------- the rack side (deployment venv)


@needs_rack
def test_the_twin_entry_point_writes_the_zero_only_through_write_latest_into_a_copy(tmp_path, monkeypatch):
    """--twin with J1's board 0.3 deg off the map: the home shifts the zero 0.3 deg through zero_writer, whose commit is write_latest (called
    once, its dated homed_<stamp>.json beside the copy's latest.json); the rack's own homed/ is not touched."""
    from bam_rack_twin.hardware import homed_history

    real_latest = jr.HOMED_DIR / "latest.json"
    before = real_latest.stat().st_mtime_ns
    calls = []
    original = homed_history.write_latest

    def counted(document, why, **kwargs):
        written = original(document, why, **kwargs)  # counted once written (a same-second retry raises first)
        calls.append(kwargs.get("path"))
        return written

    monkeypatch.setattr(homed_history, "write_latest", counted)
    from bam_rack_twin.hardware import zero_writer

    monkeypatch.setattr(zero_writer, "write_latest", counted)
    out = tmp_path / "run"
    code = jr.main(["--twin", "--out", str(out), "--twin-offset-deg", "0.3"])
    report = json.loads((out / "report.json").read_text())
    assert code == 0 and report["home"]["outcome"] == "done" and report["zero"]["verdict"] == "shift", report["zero"]
    assert abs(report["zero"]["shift_deg"] + 0.3) < 0.15  # J1 read 0.3 deg high: its zero moves 0.3 down (the stop's give aside)
    # two writes, both write_latest's, both into the copy: zero_writer's shift, then J1's homed_utc stamp (stamp_j1_homed)
    assert len(calls) == 2 and all(Path(c).parent == out / "full_arm_copy" / "homed" for c in calls)
    copy = json.loads((out / "full_arm_copy" / "homed" / "latest.json").read_text())
    entry = copy["joints"][J1]
    assert "J1 ZERO SHIFT" in entry["source"] and "J1 HOMED" in entry["source"] and report["homed_stamp"]["written"]
    assert entry["homed_utc"] > "20261114T055818Z" and copy["stamp_utc"] == json.loads(real_latest.read_text())["stamp_utc"]
    assert len(list((out / "full_arm_copy" / "homed").glob("homed_*.json"))) >= 2
    assert real_latest.stat().st_mtime_ns == before  # the rack's map untouched


@needs_rack
def test_a_confirmed_home_writes_only_j1s_homed_stamp_and_a_refused_one_writes_nothing(tmp_path, monkeypatch):
    """--twin on the map's own frame: the stall confirms the zero (zero_writer is not called) and only J1's homed_utc is stamped; with an
    obstacle on the sweep the witness refuses and nothing at all is written."""
    from bam_rack_twin.hardware import homed_history, zero_writer

    calls = []
    original = homed_history.write_latest
    def counted(document, why, **kw):
        written = original(document, why, **kw)
        calls.append(why)
        return written

    monkeypatch.setattr(homed_history, "write_latest", counted)
    monkeypatch.setattr(zero_writer, "shift", lambda *a, **k: pytest.fail("a confirmed home must not shift the zero"))
    out = tmp_path / "confirmed"
    assert jr.main(["--twin", "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["zero"]["verdict"] == "confirmed" and len(calls) == 1 and calls[0].startswith("J1 HOMED")
    calls.clear()
    out = tmp_path / "obstacle"
    assert jr.main(["--twin", "--out", str(out), "--twin-obstacle-deg", "-50"]) == 1
    report = json.loads((out / "report.json").read_text())
    assert report["zero"]["verdict"] == "refused" and not report["homed_stamp"]["written"] and calls == []


@needs_rack
def test_the_dry_run_reads_the_real_files_and_opens_nothing(capsys):
    """Against the rack's live files: either every check passes and a stall where the map puts the stop confirms the zero, or a refusal says
    which check the rack's current state fails (a power-up nobody re-homed after) - and no bus is ever built."""
    code = jr.main(["--dry-run"])
    text = capsys.readouterr().out
    if code == 0:
        assert '"a_stall_where_the_map_puts_the_stop"' in text and '"verdict": "confirmed"' in text
    else:
        assert code == 2 and "REFUSED" in text


@needs_rack
def test_the_real_run_refuses_without_allow_motion_or_out(tmp_path, capsys):
    """Every refusal before the bus opens (no port is opened by these paths)."""
    assert jr.main(["--out", str(tmp_path / "x")]) == 2
    assert "needs --allow-motion" in capsys.readouterr().out
    assert jr.main(["--allow-motion"]) == 2
    assert "needs a new --out" in capsys.readouterr().out


@needs_rack
def test_j1_home_bus_lifts_j1s_ceiling_to_the_steps_cap_only_while_nothing_holds():
    """J1HomeBus's one change to fullarm_stops' StopsBus: J1's frame carries the step's cap (11 N.m seek, 17.98 return) instead of HeldBus's
    J1_HOLD_NM 7; a guard's hold keeps the bus's own 7."""
    from bam_rack_twin.hardware import fivebar_plant as plant
    from bam_rack_twin.hardware import fullarm_stops as fs
    from bam_rack_twin.hardware import fullarm_tview_home as home

    bus = jr.j1_home_bus(fs, home, plant)(object(), {}, object())
    bus.drives = [home._hold_command(0.0, 5.0), home._hold_command(0.0, 5.0)]
    rack = jr.Rack(jr.DEPLOYMENT)
    bus.j1 = jr.real_command(rack)(-1.0, 1.2, 11.0)
    bus.j1_cap_nm = 11.0
    assert bus._frames()[home.J1_ID][1]["maximum_torque"] == pytest.approx(11.0)
    bus.j1 = jr.real_command(rack)(-1.0, 1.2, 17.98)
    bus.j1_cap_nm = 17.98
    frame = bus._frames()[home.J1_ID][1]
    assert frame["maximum_torque"] == pytest.approx(17.98) and frame["kp_scale"] == 14.0 and frame["ilimit_scale"] == 0.0
    bus.held = {"reason": "test", "drives": bus.drives, "j1": home._hold_command(-1.0, home.J1_HOLD_NM)}
    assert bus._frames()[home.J1_ID][1]["maximum_torque"] == pytest.approx(home.J1_HOLD_NM)
