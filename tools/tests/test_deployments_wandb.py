"""tools/deployments_wandb.py's tables, on a two-round synthetic pendulum campaign whose roll-ups are worked by hand below (no W&B, no network).

    env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --with pytest pytest -q /home/bam/sim2real/tools/tests/test_deployments_wandb.py

The campaign: round 0 (round0.json) and round 1 (latest_real.json, the "now" file); only CAN 11 has plays.
- round 0, CAN 11: rung 0.2 plays RMS 0.1 / 0.3 (peaks 0.2 / 0.6), rung 0.9 plays 0.4 / 0.6 (peaks 1.0 / 1.2), rung 1.0 one play 0.8 (peak 2.0).
  The tracking gate (RMS <= 0.5, peak <= 1.5, no fault): pass, pass, pass, fail, fail. So median 0.4; p95 = 0.6 + 0.8 x (0.8 - 0.6) = 0.76;
  meeting the goal (rungs up to 0.9): 3 of 4; at every rung 3 of 5; worst stop = rung 1.0's max 2.5 mm; stop at the goal's rung 0.9 mm.
- round 1, CAN 11: one play at 0.9 (0.2, peak 0.5), recorded: its row's rerun cell is the launcher link, every other row's says why not.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import deployments_wandb as dw  # noqa: E402
from sim2real import deployments_page as dp  # noqa: E402

T = {"tracking_rms_deg": 0.5, "tracking_peak_deg": 1.5, "stop_tool_mm": 1.0, "settle_s": 0.3, "sim_vs_real_floor_ratio": 1.5,
     "sim_predicts_rel": 0.2, "sim_predicts_abs_deg": 0.05, "limiter_share_max": 0.02}


def rung(fraction, plays, rms, stop, stop_max):
    return {"fraction": fraction, "peak_speed_rad_s": 10.0 * fraction, "plays": plays,
            "real": {"tracking_rms_deg": rms, "tracking_peak_deg": 0.5, "stop_tool_mm": stop, "stop_tool_max_mm": stop_max, "settle_s": 0.1,
                     "limiter_share": 0.0, "faults": 0},
            "sim": {"tracking_rms_deg": rms, "stop_tool_mm": 0.1}}


def play(root: Path, rnd: int, name: str, rms: float, peak: float) -> dict:
    return {"run": str(root / f"round{rnd}" / "real" / "can11" / "runs" / f"{name}.npz"), "kind": "repeat", "seed": None, "status": "complete",
            "tracking_rms_deg": rms, "tracking_peak_deg": peak, "tape_rms_deg": rms / 2, "stops": 2, "sim_tracking_rms_deg": rms, "fault": False}


def card(rnd: int, can11_rungs: list[dict]) -> dict:
    stations = {sid: {"omega_max_rad_s": 10.0, "tip_length_m": 0.1, "rungs": []} for sid in dp.STATIONS}
    stations["can11"]["rungs"] = can11_rungs
    return {"round": rnd, "scored_utc": f"2026-11-1{5 + rnd}T00:00:00Z", "controller": f"c{rnd}", "twin": "latest", "thresholds": T,
            "goal": {"goal_met": rnd == 1, "gates_passed": 10 + rnd, "gates_total": 180}, "round_dir": "", "stations": stations}


@pytest.fixture()
def campaign(tmp_path):
    root = tmp_path / "onedof"
    cards = root / "scorecards"
    cards.mkdir(parents=True)
    r0 = [rung(0.2, [play(root, 0, "s01", 0.1, 0.2), play(root, 0, "s02", 0.3, 0.6)], 0.2, 0.2, 0.5),
          rung(0.9, [play(root, 0, "s03", 0.4, 1.0), play(root, 0, "s04", 0.6, 1.2)], 0.45, 0.9, 1.3),
          rung(1.0, [play(root, 0, "s05", 0.8, 2.0)], 0.8, 1.4, 2.5)]
    r1 = [rung(0.9, [play(root, 1, "s01", 0.2, 0.5)], 0.2, 0.3, 0.4)]
    (cards / "round0.json").write_text(json.dumps(card(0, r0)))
    (cards / "latest_real.json").write_text(json.dumps(card(1, r1)))
    rrd = root / "rrd" / "round1" / "real" / "can11" / "runs" / "s01.rrd"
    rrd.parent.mkdir(parents=True)
    rrd.write_bytes(b"rrd")
    (root / "rrd" / "round1" / "real" / "index.json").write_text(json.dumps(
        {"schema": "bam_rack_twin.pendulum_rerun-index/1", "runs": [{"run": r1[0]["plays"][0]["run"], "rrd": str(rrd)}]}))
    return cards, rrd


class FakeRunlink:
    """data_recorder.runlink's four calls; counts the index writes."""

    def __init__(self):
        self.index, self.writes = {}, 0

    def replay_id(self, path):
        return "id" + str(abs(hash(str(path))) % 10**6)

    def register(self, path):
        self.index[self.replay_id(path)] = str(path)
        self.writes += 1
        return self.replay_id(path)

    def resolve(self, key):
        return Path(self.index[key]) if key in self.index else None

    def links(self, path):
        return {"replay_url": f"http://127.0.0.1:8771/f/tok/{self.register(path)}"}


def built(cards):
    runs = dp.runs(scorecards=cards)
    rl = FakeRunlink()
    urls = dw.replay_urls(runs + runs, rl)  # every row twice: each recording is still registered once
    return dw.payload(runs, dw.read_rounds(cards), dp.history(cards), urls), rl


def test_runs_table_rows(campaign):
    cards, rrd = campaign
    data, rl = built(cards)
    rows = data["rows"]
    assert len(rows) == 6 and rl.writes == 1
    assert all(tuple(r) == dw.RUN_COLUMNS for r in rows)
    linked = [r for r in rows if r["rerun"].startswith("http")]
    assert [(r["round"], r["name"]) for r in linked] == [(1, "s01")] and linked[0]["rrd"] == str(rrd)
    assert linked[0]["rerun"] == f"http://127.0.0.1:8771/f/tok/{rl.replay_id(rrd)}"
    assert {r["rerun"] for r in rows if r["round"] == 0} == {dw.NO_RECORDING}
    s03 = next(r for r in rows if r["round"] == 0 and r["name"] == "s03")
    assert (s03["rung"], s03["tracks"], s03["rung_stop_mm"], s03["rung_stop_worst_mm"], s03["rung_stop"]) == (0.9, "pass", 0.9, 1.3, "pass")
    assert s03["speed_deg_s"] == round(math.degrees(9.0), 1) and s03["controller"] == "c0" and s03["motor"] == "JMC 60ASM200"
    assert next(r for r in rows if r["name"] == "s05")["rung_stop"] == "fail"  # 1.4 mm > 1 mm


def test_recorded_without_launcher_says_so(campaign):
    cards, _ = campaign
    runs = dp.runs(scorecards=cards)
    rows = dw.run_rows(runs, dw.read_rounds(cards), {r["rrd"]: None for r in runs if r["rrd"]})
    assert {r["rerun"] for r in rows if r["rrd"]} == {dw.NO_LAUNCHER}


def test_station_and_round_summaries(campaign):
    cards, _ = campaign
    data, _ = built(cards)
    can11 = next(r for r in data["by_station"] if (r["round"], r["station"]) == (0, "can11"))
    assert (can11["runs"], can11["recordings"], can11["tracking_rms_median_deg"], can11["tracking_rms_p95_deg"]) == (5, 0, 0.4, 0.76)
    assert (can11["tracking_peak_worst_deg"], can11["worst_stop_mm"], can11["stop_at_goal_mm"]) == (2.0, 2.5, 0.9)
    assert (can11["share_meeting_goal"], can11["share_tracking_ok"]) == (0.75, 0.6)
    empty = next(r for r in data["by_station"] if (r["round"], r["station"]) == (0, "can1"))
    assert (empty["runs"], empty["tracking_rms_median_deg"], empty["share_meeting_goal"]) == (0, None, None)
    r0, r1 = data["by_round"]
    assert (r0["round"], r0["runs"], r0["tracking_rms_median_deg"], r0["worst_stop_mm"], r0["goal_met"], r0["gates_passed"]) == (0, 5, 0.4, 2.5, False, 10)
    assert (r1["round"], r1["runs"], r1["recordings"], r1["share_meeting_goal"], r1["goal_met"]) == (1, 1, 1, 1.0, True)
    assert data["now"] is r1 and data["links"] == {"rows": 6, "with_link": 1, "no_recording": 5, "no_recording_by_round": {"0": 5, "1": 0}}
    assert "Round 1" in dw.headline(r1) and "goal met" in dw.headline(r1)


def test_goal_lines_leave_unmeasured_out(campaign):
    cards, _ = campaign
    data, _ = built(cards)
    track = data["charts"]["chart/tracking_rms_at_goal"]["rows"]
    assert track == [[0, "CAN 11", 0.45], [0, "goal ≤ 0.5°", 0.5], [1, "CAN 11", 0.2], [1, "goal ≤ 0.5°", 0.5]]
    assert data["charts"]["chart/stop_at_goal"]["rows"] == [[0, "CAN 11", 0.9], [0, "goal ≤ 1 mm", 1.0], [1, "CAN 11", 0.3], [1, "goal ≤ 1 mm", 1.0]]
    per = data["charts"]["station/can11/tracking_rms"]["rows"]
    assert [0, "median run", 0.4] in per and [0, "p95 run", 0.76] in per and [1, "goal ≤ 0.5°", 0.5] in per
    assert set(data["charts"]) == {"chart/tracking_rms_at_goal", "chart/stop_at_goal", "chart/share_meeting_goal",
                                   *(f"station/{sid}/tracking_rms" for sid in dp.STATIONS)}


def test_a_second_build_has_the_same_digest(campaign):
    cards, _ = campaign
    first, _ = built(cards)
    second, _ = built(cards)
    assert dw.digest(first) == dw.digest(second)


def test_the_goal_lines_are_one_scalar_step_per_round(campaign):
    cards, _ = campaign
    data, _ = built(cards)
    r0, r1 = data["steps"]
    assert (r0["round"], r0["chart/tracking_rms_at_goal/can11"], r0["chart/tracking_rms_at_goal/goal"]) == (0, 0.45, 0.5)
    assert (r1["chart/stop_at_goal/can11"], r1["chart/stop_at_goal/goal"]) == (0.3, 1.0)
    assert (r0["station/can11/tracking_rms/median"], r0["station/can11/tracking_rms/p95"]) == (0.4, 0.76)
    assert (r0["chart/share_meeting_goal/all"], r0["chart/share_meeting_goal/can11"]) == (0.75, 0.75)
    assert "chart/tracking_rms_at_goal/can1" not in r0, "a value not measured is left out, never 0"


def test_a_sync_sends_w_and_b_scalars_and_keeps_every_run_local(campaign, tmp_path, monkeypatch):
    """Zach, 2026-11-21: "to help limit W and B storage I think we need to just be using it for summary statistics; for the media-rich
    things we should be using rerun!". Against a stand-in wandb whose Table / plot_table / Artifact raise and whose runs refuse a
    non-scalar: the runs table and the roll-ups are jsonl on this computer, W&B gets the headline, the goal lines as steps, the counts."""
    sys.path.insert(0, str(REPO / "tests"))
    from strict_wandb import StrictWandb  # noqa: PLC0415

    cards, rrd = campaign
    data, rl = built(cards)
    monkeypatch.setattr(dw, "WANDB_DIR", tmp_path / "wandb")
    fake = StrictWandb()
    monkeypatch.setitem(sys.modules, "wandb", fake)
    local = tmp_path / "local"
    out = dw.sync(data, scorecards=cards, local=local)
    assert [o["id"] for o in out] == [dw.SUMMARY_ID, f"{dw.SUMMARY_ID}-r0", f"{dw.SUMMARY_ID}-r1"] and all(o["written"] for o in out)

    def rows(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    runs = rows(local / "runs.jsonl")
    assert runs == json.loads(json.dumps(data["rows"])) and len(runs) == 6
    linked = [r for r in runs if r["rerun"].startswith("http")]
    assert [r["name"] for r in linked] == ["s01"] and linked[0]["rerun"] == f"http://127.0.0.1:8771/f/tok/{rl.replay_id(rrd)}"
    assert len(rows(local / "r0" / "runs.jsonl")) == 5 and len(rows(local / "r1" / "runs.jsonl")) == 1
    assert rows(local / "by_round.jsonl")[1]["round"] == 1 and len(rows(local / "by_round_station.jsonl")) == 2 * len(dp.STATIONS)
    summary, round0, round1 = fake.runs
    assert summary.config["local_tables"] == str(local) and round1.config["local_tables"] == str(local / "r1")
    assert summary.logged == data["steps"], "the goal lines: one step per round, x = round"
    assert (summary.summary["rows/runs"], summary.summary["links/with_link"], summary.summary["now/round"]) == (6, 1, 1)
    assert summary.summary["sync/last_round"] == 1
    assert round0.logged == [] and (round0.summary["rows/runs"], round0.summary["share_meeting_goal"]) == (5, 0.75)
    assert round0.summary["chart/tracking_rms_at_goal/can11"] == 0.45 and round0.summary["can11/runs"] == 5

    # an unchanged campaign writes nothing; a changed one logs only the rounds the summary run lacks
    held = {run.id: dict(run.summary) for run in fake.runs}
    again = StrictWandb(held=held)
    monkeypatch.setitem(sys.modules, "wandb", again)
    assert not any(o["written"] for o in dw.sync(data, scorecards=cards, local=local)) and again.runs == []
    held[dw.SUMMARY_ID]["sync/digest"] = "older"
    moved = StrictWandb(held=held)
    monkeypatch.setitem(sys.modules, "wandb", moved)
    dw.sync(data, scorecards=cards, local=local)
    assert [run.logged for run in moved.runs] == [[]], "both rounds are already lines: no point drawn twice"


def test_the_report_is_charts_over_scalars_and_pointers_to_the_local_files(campaign, tmp_path):
    wr = pytest.importorskip("wandb_workspaces.reports.v2", reason="sim2real's tracking extra")
    cards, _ = campaign
    data, _ = built(cards)
    blocks = dw.report_blocks(data, local=tmp_path / "local")
    panels = [p for b in blocks for p in (getattr(b, "panels", None) or [])]
    kinds = {type(p).__name__ for p in panels}
    assert kinds <= {"ScalarChart", "LinePlot", "BarPlot", "MarkdownPanel"}, kinds
    logged = {key for step in data["steps"] for key in step}
    for plot in (p for p in panels if isinstance(p, wr.LinePlot)):
        assert plot.x == "round" and set(plot.y) <= logged, plot.y   # every line is a key the summary run logs
        goal = [key for key in plot.y if key.endswith("/goal")]
        assert goal in ([], plot.y[-1:]), "the goal line is drawn last"
    text = "\n".join(getattr(b, "text", "") or "" for b in blocks) + "\n".join(p.markdown for p in panels if hasattr(p, "markdown"))
    assert str(tmp_path / "local" / "runs.jsonl") in text and dw.RUNS_VIEW in text and "by_round_station.jsonl" in text
    assert "| 0 | 2026-11-15 | c0 | not met |" in text, "the round-by-round numbers, written into the report"
