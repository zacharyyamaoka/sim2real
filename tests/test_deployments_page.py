"""The Deployments page's data, written before the code (2026-11-17): the pendulum campaign's two scorecards in, the One Dof Test Rack's
typed tree out, every node with its metrics per round (round 0 as found, round 8 now) and the five-question verdicts.

    env -u VIRTUAL_ENV taskset -c 2-5,16,17 /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_deployments_page.py

What it holds (Zach, Daily Note 2026-11-17, "# What is required for me to actually get this working?": "on the part page I want to see
basically the current value of its metrics and gates"; "Performance is real/sim vs target. Fidelity is real vs sim"):
- the numbers are the scorecards' own: the five cell gates re-scored here pass 82 (round 0) and 151 (round 8) of 180, each station's
  highest tracked rung and twin verdict equal the scorecard's goal block, and CAN 11's twin is 2.14x its floor now (4.27x as found);
- the tree is typed: the rack, six stations (CAN 1, 11-15), each with an integrated servo pulled apart into driver, motor, gearbox and
  encoder, and its link; the motor's Kt and winding temperature and the gearbox's lost motion read "not observable on this rack";
- every metric says whether it is performance (real or sim vs the target), fidelity (real vs sim) or evidence (the ruler and the data);
- the five questions live once, in sim2real.verdicts: a parent passes a question only at its own output and with every child that gates
  it (MOC - Sim2Real Success Criteria and Metrics: proposal C, with decision 1's default: the servo's gates are shown under a station,
  never gating it). Held on a synthetic tree, so the rule is tested apart from the data.
The scorecards live on the workstation's archive; a machine without them skips the data tests (the rule's tests still run).

"Now" is whatever round the campaign's latest_real.json holds, so the numbers above are pinned to the round they were written against:
the data tests build with round8.json as "now" (NOW below). The campaign moved on (round 9 on 2026-11-18), and the page must follow
without a code change (Zach: "open up that deployment and at a glance see exactly the current state"): "Now" is labelled from its file's
own round and scored_utc, the history is every round{n}.json below it then it, none after, and a missing round is skipped and reported.
"""

from __future__ import annotations

import json

import pytest

from sim2real import deployments_page as dp
from sim2real import result, verdicts

# the round the numbers in these tests were written against (2026-11-17): built as "now", whatever latest_real.json holds today
NOW = "round8.json"
FILES = {"r0": "round0.json", "r8": NOW}  # each column's file, for reading the scorecard back
HAVE = dp.SCORECARDS.is_dir() and all((dp.SCORECARDS / name).is_file() for name in FILES.values())
needs_data = pytest.mark.skipif(not HAVE, reason=f"no pendulum scorecards at {dp.SCORECARDS}")
HAVE_ROUND9 = HAVE and all((dp.SCORECARDS / name).is_file() for name in ("round9.json", "latest_real.json"))
needs_round9 = pytest.mark.skipif(not HAVE_ROUND9, reason=f"no round9.json or latest_real.json at {dp.SCORECARDS}")


@pytest.fixture(scope="module")
def doc():
    return dp.build(now=NOW)


def node(doc, node_id):
    return next(n for n in doc["nodes"] if n["id"] == node_id)


def metric(n, metric_id):
    return next(m for m in n["metrics"] if m["id"] == metric_id)


# ---- the rule, on a synthetic tree ------------------------------------------------------------------------------------------------------

def leaf(node_id, parent, status, question="twin", kind="gated", gating=True):
    return {"id": node_id, "parent": parent, "gating": gating, "children": [],
            "metrics": [{"id": f"{node_id}.m", "question": question, "kind": kind, "values": {"r": {"value": 1.0, "status": status}}}]}


def tree(*nodes):
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        n["children"] = [c["id"] for c in nodes if c["parent"] == n["id"]]
    verdicts.roll_up(list(by_id.values()), ("r",))
    return by_id


def test_question_names_are_sim2reals_own():
    assert tuple(q["name"] for q in verdicts.QUESTIONS) == result.QUESTIONS


def test_a_parent_fails_with_a_gating_child_even_when_its_own_output_passes():
    t = tree(leaf("p", None, "pass"), leaf("a", "p", "pass"), leaf("b", "p", "fail"))
    q = t["p"]["questions"]["r"]["twin"]
    assert q["own"] == "pass" and q["status"] == "fail" and q["via"] == ["b"]
    assert t["p"]["verdict"]["r"] == {"status": "fail", "first": "twin"}


def test_a_child_that_does_not_gate_is_shown_never_rolled_up():
    t = tree(leaf("p", None, "pass"), leaf("servo", "p", "fail", gating=False))
    assert t["p"]["questions"]["r"]["twin"]["status"] == "pass" and t["p"]["verdict"]["r"]["status"] == "pass"
    # its trouble is still visible as what lies below
    assert t["p"]["rollup"]["r"] == "fail"


def test_not_observable_and_not_run_never_fail_a_parent():
    t = tree(leaf("p", None, "pass"), leaf("gearbox", "p", "not_observable", kind="not_observable"), leaf("enc", "p", "not_run"))
    assert t["p"]["questions"]["r"]["twin"]["status"] == "pass"
    assert t["gearbox"]["verdict"]["r"]["status"] == "not_observable"


def test_a_shown_gate_that_misses_reads_watch_not_fail():
    t = tree(leaf("p", None, "fail", kind="shown"))
    assert t["p"]["questions"]["r"]["twin"]["status"] == "watch" and t["p"]["verdict"]["r"]["status"] == "watch"


def test_the_first_failing_question_in_order_names_the_cause():
    p = leaf("p", None, "fail", question="job")
    p["metrics"].append({"id": "p.floor", "question": "floor", "kind": "gated", "values": {"r": {"value": 3.0, "status": "fail"}}})
    t = tree(p)
    assert t["p"]["verdict"]["r"] == {"status": "fail", "first": "floor"}


# ---- the data ---------------------------------------------------------------------------------------------------------------------

@needs_data
def test_totals_are_the_scorecards_own(doc):
    rack = node(doc, doc["root"])
    gates = metric(rack, "gates_passed")["values"]
    assert (gates["r0"]["value"], gates["r8"]["value"]) == (82, 151)
    assert (gates["r0"]["of"], gates["r8"]["of"]) == (180, 180)
    for rd in doc["rounds"]:
        card = json.loads((dp.SCORECARDS / FILES[rd["id"]]).read_text())
        assert rd["gates_passed"] == card["goal"]["gates_passed"]
        assert rd["sha256"] and rd["source"].endswith(".json")


@needs_data
def test_can11_twin_is_2_14x_now_and_4_27x_as_found(doc):
    can11 = node(doc, "can11")
    twin = metric(can11, "twin_over_floor")
    assert round(twin["values"]["r8"]["value"], 2) == 2.14 and twin["values"]["r8"]["status"] == "fail"
    assert round(twin["values"]["r0"]["value"], 2) == 4.27
    assert twin["family"] == "fidelity"
    assert can11["verdict"]["r8"] == {"status": "fail", "first": "twin"}


@needs_data
def test_one_thing_stops_the_goal_now(doc):
    rack = node(doc, doc["root"])
    assert rack["verdict"]["r8"]["status"] == "fail"
    assert rack["stops"]["r8"] == {"question": "twin", "stations": ["can11"]}
    failing = [n["id"] for n in doc["nodes"] if n["level"] == "station" and n["verdict"]["r8"]["status"] == "fail"]
    assert failing == ["can11"]


@needs_data
def test_the_typed_tree(doc):
    rack = node(doc, doc["root"])
    stations = [c for c in rack["children"] if node(doc, c)["level"] == "station"]
    assert stations == ["can1", "can11", "can12", "can13", "can14", "can15"]
    for sid in stations:
        st = node(doc, sid)
        assert st["children"] == [f"{sid}/servo", f"{sid}/link"] and st["gating"] is True
        servo = node(doc, f"{sid}/servo")
        assert servo["gating"] is False  # MOC decision 1's default: shown under the station, never gating it
        assert servo["children"] == [f"{sid}/servo/{p}" for p in ("driver", "motor", "gearbox", "encoder")]
        motor, gearbox = node(doc, f"{sid}/servo/motor"), node(doc, f"{sid}/servo/gearbox")
        for m in (metric(motor, "T6"), metric(motor, "T8"), metric(gearbox, "T5")):
            assert m["kind"] == "not_observable" and all(v["status"] == "not_observable" for v in m["values"].values()), m["id"]
        assert gearbox["verdict"]["r8"]["status"] == "not_observable"


@needs_data
def test_every_metric_is_performance_fidelity_or_evidence(doc):
    families = {m["family"] for n in doc["nodes"] for m in n["metrics"]}
    assert families <= {"performance", "fidelity", "evidence"} and {"performance", "fidelity"} <= families
    can11 = node(doc, "can11")
    assert metric(can11, "tip_stop_09")["family"] == "performance"
    assert metric(can11, "tracking_rms_09")["family"] == "performance"
    assert metric(can11, "sim_predicts")["family"] == "fidelity"
    assert metric(node(doc, "can11/servo"), "T2")["family"] == "fidelity"


@needs_data
def test_station_numbers_match_each_scorecards_goal(doc):
    for rd in doc["rounds"]:
        card = json.loads((dp.SCORECARDS / FILES[rd["id"]]).read_text())
        for sid in dp.STATIONS:
            st = node(doc, sid)
            assert metric(st, "passes_up_to")["values"][rd["id"]]["value"] == card["goal"][f"max_trackable_fraction_{sid}"], (rd["id"], sid)
            twin_ok = metric(st, "twin_over_floor")["values"][rd["id"]]["status"] == "pass"
            assert twin_ok == card["goal"][f"twin_ok_{sid}"], (rd["id"], sid)


# ---- performance first, runs as the atomic unit (Zach, Daily Note 2026-11-17 "# Ok": "Performance is what matters at the end of the
# day ... So performance is first and up center"; "Runs are the atomic unit ... drill into a particular run (rerun)") ---------------

@needs_data
def test_real_performance_gates_28_then_67_of_72(doc):
    rack = node(doc, doc["root"])
    perf = metric(rack, "perf_gates")
    assert (perf["values"]["r0"]["value"], perf["values"]["r8"]["value"]) == (28, 67) and perf["values"]["r8"]["of"] == 72
    assert perf["family"] == "performance"


@needs_data
def test_the_top_performance_gap_now_is_full_speed_tracking(doc):
    gap = node(doc, doc["root"])["performance"]["r8"]
    assert gap["passed"] == 67 and gap["of"] == 72
    top = gap["gaps"][0]
    assert top["gate"] == "tracking" and top["fraction"] == 1.0 and top["stations"] == ["can1", "can12", "can13", "can14", "can15"]
    # the median passes every rung, the worst stop does not: CAN 11 over 1 mm on 3 of 6 rungs (0.4, 0.9, 1.0)
    worst = gap["worst_stops_over"]
    assert worst == [{"station": "can11", "rungs": [0.4, 0.9, 1.0]}]


@needs_data
def test_round_by_round_history_is_every_scorecard(doc):
    hist = doc["history"]
    assert [h["round"] for h in hist] == list(range(9))
    assert [h["gates_passed"] for h in hist] == [82, 106, 114, 132, 137, 145, 148, 149, 151]
    assert hist[0]["perf_gates"] == 28 and hist[-1]["perf_gates"] == 67
    assert round(hist[-1]["stations"]["can12"]["tracking_rms_09"], 2) == 0.25 and round(hist[0]["stations"]["can12"]["tracking_rms_09"], 2) == 8.08


@needs_data
def test_runs_are_every_play_of_every_round():
    rows = dp.runs(now=NOW)
    by_round = {}
    for r in rows:
        by_round.setdefault(r["round"], []).append(r)
    assert sorted(by_round) == list(range(9)) and len(by_round[8]) == 252 and len(by_round[0]) == 196
    one = next(r for r in by_round[8] if r["run"].endswith("round8/real/can11/runs/s57_can11_waypoints.npz") and r["station"] == "can11")
    assert one["kind"] == "repeat" and one["fraction"] == 0.9 and round(one["tracking_rms_deg"], 3) == 0.113
    assert one["rrd"].endswith("rrd/round8/real/can11/runs/s57_can11_waypoints.rrd")
    for r in rows:
        assert r["kind"] in ("repeat", "held_out") and r["station"] in dp.STATIONS
        if r["rrd"] is not None:
            # a link is only ever to the recording of THIS run: the rerun index names it, or its npz is a byte-identical copy
            assert r["rrd"].endswith(".rrd") and dp.Path(r["rrd"]).is_file() and r["rrd_via"] in ("rerun index", "identical copy")
    with_rrd = [r for r in by_round[8] if r["rrd"]]
    assert len(with_rrd) == 252  # 168 by the index, the 84 can12+can14 plays by their identical copy's recording


@needs_data
def test_write_round_trips(tmp_path, doc):
    out = dp.write(tmp_path / "page.json", now=NOW)
    back = json.loads(out.read_text())
    assert back["schema"] == dp.SCHEMA and back == json.loads(json.dumps(doc))


# ---- "Now" is always the latest round, and says which (Zach, 2026-11-17: "open up that deployment and at a glance see exactly the current
# state"; the campaign resumed and wrote round 9 to latest_real.json on 2026-11-18): written before the code -----------------------------

def now_column(d):
    return next(r for r in d["rounds"] if r["label"] == "Now")


@needs_round9
@pytest.mark.parametrize("name, n, day", [("round8.json", 8, "2026-11-17"), ("round9.json", 9, "2026-11-18")])
def test_now_is_labelled_from_its_files_own_round(name, n, day):
    d = dp.build(now=name)
    now = now_column(d)
    assert (now["round"], now["long"]) == (n, f"round {n} · {day}") and now["source"].endswith(name)
    assert d["rounds"][0]["long"] == "round 0 · before any fit"
    # the station whose ladder moved names the round it moved to, never a round written into the code
    caveat = node(d, "can11")["caveat"]
    assert f"round {n}'s is" in caveat and not any(f"round {k}'s is" in caveat for k in range(1, 20) if k != n)


@needs_round9
def test_the_default_now_is_whatever_round_latest_real_holds():
    card = json.loads((dp.SCORECARDS / dp.NOW_FILE).read_text())
    now = now_column(dp.build())
    assert now["round"] == card["round"] and now["long"] == f"round {card['round']} · {card['scored_utc'][:10]}"


@needs_round9
def test_history_is_every_round_up_to_now_and_none_after():
    assert (dp.SCORECARDS / "round9.json").is_file()  # a later round exists beside it, and must stay out
    at8 = dp.build(now="round8.json")
    assert [h["round"] for h in at8["history"]] == list(range(9)) and at8["history"][-1]["source"].endswith("round8.json")
    assert at8["history_missing"] == []
    at9 = dp.build(now="round9.json")
    assert [h["round"] for h in at9["history"]] == list(range(10)) and at9["history"][-1]["gates_passed"] == 153
    latest = json.loads((dp.SCORECARDS / dp.NOW_FILE).read_text())["round"]
    default = dp.build()
    assert [h["round"] for h in default["history"]] == list(range(latest + 1)) and default["history"][-1]["source"].endswith(dp.NOW_FILE)


@needs_data
def test_a_missing_middle_round_is_skipped_and_reported(tmp_path):
    for n in (0, 1, 2, 4, 5, 6, 7, 8):  # no round3.json
        (tmp_path / f"round{n}.json").symlink_to(dp.SCORECARDS / f"round{n}.json")
    d = dp.build(scorecards=tmp_path, now="round8.json")
    assert [h["round"] for h in d["history"]] == [0, 1, 2, 4, 5, 6, 7, 8]
    assert d["history_missing"] == [3]
    assert sorted({r["round"] for r in dp.runs(scorecards=tmp_path, now="round8.json")}) == [0, 1, 2, 4, 5, 6, 7, 8]
