"""PidTune hands PID tuna the board's stated loop (pidtuna Servo.loop), so pidtuna's analytic ceiling holds the sim tune's climb.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src taskset -c 2-5,16,17 nice -n 19 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_pid_tune_stated_loop.py

WHY (pidtuna CONTRACT amendment 3, v2.3; pidtuna 6c6c4a9): with no relative gain range a tune's climb is held by the analytic bounds on
the identified model and the STATED loop, and pidtuna's tune holds the climb at that ceiling only where the loop is stated; PidTune
stated none, so the CAN 11 sim tune climbed to its first ringing rung with no cited ceiling at all. Written red first (on 2d228a4). The
ruler:

1. The pendulum's PidTune states CAN 11's loop: the driver's datasheet control rate (robotparts mjbots-moteus-r4-11, its low end), the
   board's recorded current loop, velocity filter and one encoder count (sim2real/data/board_configs.json, a copy of its moteus dump),
   and the twin of record's command delay; this file reads each from those files itself. The loop is built with no pipeline in hand
   (a handle with workers only, as the slow grade and a VM without bam_rack_twin hold it).
2. On CAN 11's sim (the committed fit's values), PID tuna gets that loop, its climb has a finite analytic ceiling, and every rung the
   climb plays is at or under it.
3. The control: with no stated loop the climb has no analytic ceiling (the loop is what holds it).
"""

from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("bam_rack_twin", reason="CAN 11's description and twin of record live in bam_rack_twin (the rack venv)")

import sim2real  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TAU = 2.0 * math.pi
ROBOTPARTS = Path("/home/bam/robotparts")


def _copy():
    return json.loads((REPO / "src" / "sim2real" / "data" / "board_configs.json").read_text())["deployments"]["one-dof-test-rack"]["11"]


def _expected_loop() -> dict[str, float]:
    """CAN 11's stated loop, read here from the files it is stated in (never from the code under test)."""
    board = _copy()
    lines = board["lines"]
    rate = json.loads((ROBOTPARTS / "dist" / "site" / "v2" / "parts" / f"{board['driver_part']}.json").read_text())["specs"]["control_rate"]
    assert rate["unit"] == "kHz", rate
    return {"loop_hz": 1000.0 * min(rate["value"]), "torque_bandwidth_hz": float(lines["servo.pid_dq_hz"]),
            "velocity_filter_hz": float(lines["motor_position.sources.0.pll_filter_hz"]),
            "position_quantum_rad": TAU * float(lines["motor_position.rotor_to_output_ratio"]) / float(lines["motor_position.sources.0.cpr"])}


@pytest.fixture(scope="module")
def pendulum():
    from bam_rack_twin.description import station_description  # noqa: PLC0415

    return sim2real.RobotTwin.from_robot_description(station_description(11), workers=1)


@pytest.fixture(scope="module")
def tune_step(pendulum):
    return next(r for r in pendulum.runner.schedule().routines() if r.id == "pid.pidtuna")


@pytest.fixture(scope="module")
def values(pendulum):
    """The values the tune sees: the description's priors, then the committed fit's dynamics (sysid/results/pendulum_can11.json)."""
    out = {k: float(v) for k, v in pendulum.description.values().items() if v is not None}
    out.update({r["key"]: float(r["recovered"]) for r in json.loads((REPO / "sysid" / "results" / "pendulum_can11.json").read_text())["parameters"]})
    return out


def _tune(pendulum, step, values, monkeypatch):
    """PidTune.fit on CAN 11's sim, PID tuna's tune() watched: (the servo it was handed, the Tuning it returned)."""
    seen = {}
    from sim2real.calibration.pid_tune import _pidtuna_module  # noqa: PLC0415

    _pidtuna_module("pidtuna.types")   # puts pidtuna on the path
    module = importlib.import_module("pidtuna.tune")
    real = module.tune

    def watched(servo, plant, *args, **kwargs):
        seen["servo"] = servo
        seen["tuning"] = real(servo, plant, *args, **kwargs)
        return seen["tuning"]

    monkeypatch.setattr(module, "tune", watched)
    handle = SimpleNamespace(workers=1, module=pendulum.runner.pipeline())
    step.fit({}, values, handle)
    return seen["servo"], seen["tuning"]


def test_the_pendulums_tune_states_can11s_loop(tune_step, values, pendulum):
    from sim2real.calibration.pid_tune import _pidtuna_module  # noqa: PLC0415

    analytic = _pidtuna_module("pidtuna.analytic")
    assert tune_step.loop is not None, "the pendulum's PidTune states no loop"
    loop = tune_step.loop(values, SimpleNamespace(workers=1)) if callable(tune_step.loop) else tune_step.loop
    assert isinstance(loop, analytic.LoopModel), loop
    for name, expected in _expected_loop().items():
        assert getattr(loop, name) == pytest.approx(expected, rel=1e-12), (name, getattr(loop, name), expected)
    record = pendulum.runner.pipeline().twin({k.split(".", 1)[1]: v for k, v in values.items() if k.startswith("can11.")}, "ruler")
    assert loop.delay_s == pytest.approx(float(record.command_delay_s)), (loop.delay_s, record.command_delay_s)


def test_the_climb_stops_at_or_under_the_analytic_ceiling(pendulum, tune_step, values, monkeypatch):
    servo, tuning = _tune(pendulum, tune_step, values, monkeypatch)
    assert servo.loop is not None, "PID tuna was handed no stated loop"
    limit = tuning.log.find(stage="sweep", kind="limit")
    assert limit, "the tune recorded no sweep limit"
    cap = limit[-1].data.get("wn_climb_cap")
    assert cap is not None and math.isfinite(cap), limit[-1].data
    rungs = [e.data["wn"] for e in tuning.log.find(stage="sweep", kind="rung")]
    print(f"\nclimb ceiling wn {cap:.4g} rad/s; rungs played {[round(w, 3) for w in rungs]}; tuned {tuning.gains[servo.name]}")
    assert rungs and max(rungs) <= cap * (1.0 + 1e-9), (rungs, cap)


def test_without_a_stated_loop_the_climb_has_no_analytic_ceiling(pendulum, tune_step, values, monkeypatch):
    import dataclasses  # noqa: PLC0415

    bare = dataclasses.replace(tune_step, loop=None)
    servo, tuning = _tune(pendulum, bare, values, monkeypatch)
    assert servo.loop is None
    assert tuning.log.find(stage="sweep", kind="limit")[-1].data.get("wn_climb_cap") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-s"]))
