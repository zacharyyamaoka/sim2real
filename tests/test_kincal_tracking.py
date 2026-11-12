"""The Kinematic Calibration W&B tracker (sim2real.tracking.kincal): pure selection, statistics and record shapes; no network.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra tracking pytest -q /home/bam/sim2real/tests/test_kincal_tracking.py

The numbers are Zach's existing bam_calibration ledgers; what is held red here is the reading of them: the newest row per
(cell, seed) wins, a per-seed paired ratio is not a ratio of medians, and one changed number is a new evaluation.
"""

from __future__ import annotations

import copy
import json
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sim2real.tracking import kincal, rigs
from sim2real.tracking.wandb_log import run_id

DATA = Path(kincal.__file__).resolve().parents[1] / "data" / "kincal_ledger_2026-11-12.json"


def v2_row(cell="R1.horse.ur5e.Nur", seed=0, started="2026-11-07T04:00:00-07:00", a0=10.0, a1=5.0, *, status="ok", sha="aaa",
           before=20.0, floor=1.0, converged=True):
    def algorithm(mean, form):
        return {"form": form, "status": "ok", "converged": converged, "iterations": 3, "runtime_s": 0.5, "parameters": 47,
                "ur": {"accept": True},
                "kpi": {"leader": {"K4d": {"pos_mm": {"mean": mean / 2, "p95": mean, "max": mean}}},
                        "follower": {"K4d": {"pos_mm": {"mean": mean, "p95": mean * 2, "max": mean * 3}}},
                        "worst_arm": {"arm": "follower", "K4d_pos_mean_mm": mean}}}
    return {"schema": "kincal-run/2", "run_id": f"{cell}.s{seed}.{started}", "batch_id": f"b-{started}", "cell_id": cell, "rung": "R1",
            "seed_index": seed, "status": status, "started_at": started, "git_sha": sha, "code_hash": "hash",
            "label": "a label", "setup": {"kind": "horse", "arm": "ur5e"},
            "headline": {"metric": "K4d.pos_mean_mm", "before": before, "floor": floor},
            "algorithms": {"A0": algorithm(a0, "patent"), "A1": algorithm(a1, "map")}}


def v1_row(cell="Q1.pair.N1", seed=0, started="2026-10-08T12:59:37-07:00", rms=2.0, status="ok"):
    return {"schema": "kincal-run/1", "run_id": f"{cell}.s{seed}.{started}", "cell_id": cell, "question": "Q1", "seed_index": seed,
            "status": status, "started_at": started, "duration_s": 12.0, "git_sha": "g1", "code_hash": "c1",
            "config": {"topology": "pair", "arms": ["a", "b"], "sessions": [["a", "b"]], "coupling": {"kind": "pinned"},
                       "datum": {"site_count": 2}, "noise": {"level": "N1"}, "poses_per_session": 100, "fit": "full_chain",
                       "tilt_rad": []},
            "headline": {"worst_arm": "a", "pos_rms_mm": rms, "pos_p95_mm": rms * 2, "pos_max_mm": rms * 3, "rot_rms_mrad": 1.0,
                         "before_pos_rms_mm": 9.0, "internal_pos_rms_mm": 0.5},
            "prediction": {"floor_worst_arm_pos_rms_mm": 0.25}}


def compact(v2_rows=None, v1_rows=None):
    v2_rows = [v2_row(seed=s) for s in range(3)] if v2_rows is None else v2_rows
    v1_rows = [v1_row(seed=s) for s in range(3)] if v1_rows is None else v1_rows
    return kincal.compact_ledgers(v1_rows, v2_rows, v1_source="/v1.jsonl", v2_sources=["/v2.jsonl"])


# ---------------------------------------------------------------------------------------------------------------- selection


def test_latest_row_per_cell_and_seed_wins_in_either_order():
    old, new = v2_row(started="2026-11-07T04:00:00-07:00", a0=99.0), v2_row(started="2026-11-07T05:00:00-07:00", a0=1.0)
    for rows in ([old, new], [new, old]):
        kept = kincal.latest_rows(rows)
        assert len(kept) == 1
        assert kept[0]["algorithms"]["A0"]["kpi"]["worst_arm"]["K4d_pos_mean_mm"] == 1.0


def test_latest_compares_instants_not_strings():
    # 05:00 at -08:00 is 13:00Z, later than 05:30 at -05:00 (10:30Z), though the string sorts lower
    earlier = v2_row(started="2026-11-07T05:30:00-05:00", a0=99.0)
    later = v2_row(started="2026-11-07T05:00:00-08:00", a0=1.0)
    assert kincal.latest_rows([later, earlier])[0]["algorithms"]["A0"]["kpi"]["worst_arm"]["K4d_pos_mean_mm"] == 1.0


def test_a_failed_newer_row_does_not_replace_an_ok_one():
    ok, failed = v2_row(started="2026-11-07T04:00:00-07:00"), v2_row(started="2026-11-07T06:00:00-07:00", status="error")
    kept = kincal.latest_rows([ok, failed])
    assert [r["started_at"] for r in kept] == [ok["started_at"]]


def test_cells_and_seeds_are_distinct_keys():
    rows = [v2_row(cell="X", seed=1), v2_row(cell="X", seed=0), v2_row(cell="Y", seed=0)]
    assert [(r["cell_id"], r["seed_index"]) for r in kincal.latest_rows(rows)] == [("X", 0), ("X", 1), ("Y", 0)]


# ---------------------------------------------------------------------------------------------------------------- statistics


def test_median_min_max_over_seeds():
    assert kincal.spread([3.0, 1.0, 2.0]) == {"median": 2.0, "min": 1.0, "max": 3.0}
    assert kincal.spread([4.0, 1.0, 2.0, 3.0])["median"] == 2.5


def test_paired_ratio_is_the_median_of_per_seed_ratios_not_the_ratio_of_medians():
    a0, alg = [1.0, 1.0, 100.0], [0.5, 3.0, 100.0]
    rows = [v2_row(seed=s, a0=a0[s], a1=alg[s]) for s in range(3)]
    cell = compact(rows)["v2"]["R1.horse.ur5e.Nur"]
    ratios = kincal.paired_ratios(cell, "A1")
    assert [r for _, r in ratios] == [0.5, 3.0, 1.0]
    summary = kincal.records(compact(rows))
    a1 = next(r for r in summary if r["name"] == "A1 · R1.horse.ur5e.Nur")["summary"]
    assert a1["ratio_vs_A0"] == 1.0                                # median of [0.5, 3, 1]
    assert a1["ratio_vs_A0"] != pytest.approx(3.0 / 1.0)           # the ratio of medians, which is wrong here
    assert a1["wins_vs_A0"] == 1


def test_ratio_skips_seeds_with_a_zero_baseline():
    rows = [v2_row(seed=0, a0=0.0, a1=1.0), v2_row(seed=1, a0=2.0, a1=1.0)]
    assert kincal.paired_ratios(compact(rows)["v2"]["R1.horse.ur5e.Nur"], "A1") == [(1, 0.5)]


# ---------------------------------------------------------------------------------------------------------------- extract


def test_compact_counts_sources_and_provenance():
    older = v2_row(seed=0, started="2026-11-07T03:00:00-07:00", a0=99.0)
    data = compact([older, v2_row(seed=0, sha="bbb"), v2_row(seed=1)], [v1_row(seed=0), v1_row(seed=1)])
    assert data["sources"]["v2"] == {"paths": ["/v2.jsonl"], "schema": "kincal-run/2", "rows": 3, "kept": 2, "git_shas": ["aaa", "bbb"]}
    assert data["sources"]["v1"]["rows"] == 2 and data["sources"]["v1"]["git_shas"] == ["g1"]
    seed0 = data["v2"]["R1.horse.ur5e.Nur"]["seeds"][0]
    assert seed0["algorithms"]["A0"]["k4d_pos_mean_mm"] == 10.0     # the newest row, not the 99.0 one
    assert seed0["algorithms"]["A0"]["k4d_pos_p95_mm"] == 20.0      # the worst arm's p95 (follower), not leader's
    assert seed0["algorithms"]["A0"]["worst_arm"] == "follower"
    assert seed0["before_mm"] == 20.0 and seed0["floor_mm"] == 1.0
    assert data["v1"]["Q1.pair.N1"]["config"]["noise_level"] == "N1"
    assert data["v1"]["Q1.pair.N1"]["config"]["coupling_kind"] == "pinned"


def test_compact_is_json_round_trippable():
    data = compact()
    assert json.loads(json.dumps(data)) == data


def test_the_committed_ledger_holds_what_the_source_had():
    data = json.loads(DATA.read_text())
    assert DATA.stat().st_size < 1_000_000
    assert (data["sources"]["v1"]["rows"], len(data["v1"])) == (348, 52)
    assert data["sources"]["v2"]["rows"] == 116 and data["sources"]["v2"]["kept"] == 54
    assert sum(len(c["seeds"]) for c in data["v1"].values()) == 348
    assert len(data["v2"]) == 8
    assert sum(len(s["algorithms"]) for c in data["v2"].values() for s in c["seeds"]) == 42 * 11 + 12 * 2


# ---------------------------------------------------------------------------------------------------------------- records


def test_v2_records_shape_and_stable_ids():
    data = compact()
    batch = kincal.records(data)
    v2 = [r for r in batch if r["config"]["version"] == "v2"]
    assert sorted(r["name"] for r in v2) == ["A0 · R1.horse.ur5e.Nur", "A1 · R1.horse.ur5e.Nur"]
    a1 = next(r for r in v2 if r["name"].startswith("A1"))
    config = a1["config"]
    assert a1["group"] == "R1.horse.ur5e.Nur" and a1["job_type"] == "kincal"
    assert a1["tags"] == ["v2", "R1", "A1", "ur5e", "latest"]
    assert config["algorithm_desc"] == kincal.ALGORITHM_DESC["A1"] and config["seeds"] == [0, 1, 2]
    assert config["evaluation_state"] == "latest" and config["result_id"] == "kincal-v2-R1.horse.ur5e.Nur-A1"
    assert a1["id"] == run_id("kincal", "v2", "R1.horse.ur5e.Nur", "A1", config["evaluation"])
    s = a1["summary"]
    assert (s["k4d_pos_mean_mm_worst_arm_median"], s["k4d_pos_mean_mm_worst_arm_min"], s["k4d_pos_mean_mm_worst_arm_max"]) == (5.0, 5.0, 5.0)
    assert (s["k4d_pos_p95_mm_worst_arm_median"], s["before_mm_median"], s["floor_mm_median"]) == (10.0, 20.0, 1.0)
    assert s["ratio_vs_A0"] == 0.5 and s["wins_vs_A0"] == 3 and s["converged_rate"] == 1.0 and s["ur_accept_rate"] == 1.0
    assert s["n_seeds"] == 3 and "seeds" not in s            # "seeds" is the table's name in the run summary
    assert len(a1["tables"]["seeds"]) == 3 and a1["history"][0]["k4d_pos_mean_mm_worst_arm_median"] == 5.0
    assert [r["id"] for r in kincal.records(data)] == [r["id"] for r in batch]            # a re-run maps to the same ids
    assert len({r["id"] for r in batch}) == len(batch)


def test_v1_records_shape():
    batch = kincal.records(compact())
    v1 = next(r for r in batch if r["config"]["version"] == "v1")
    assert v1["name"] == "Q1.pair.N1" and v1["group"] == "Q1"
    assert v1["tags"] == ["v1", "Q1", "pair", "full_chain", "N1", "latest"]
    assert v1["config"]["seeds"] == [0, 1, 2] and v1["config"]["poses_per_session"] == 100
    assert v1["config"]["result_id"] == "kincal-v1-Q1.pair.N1"
    assert v1["summary"]["pos_rms_mm_median"] == 2.0 and v1["summary"]["pos_p95_mm_median"] == 4.0
    assert v1["summary"]["pos_max_mm_median"] == 6.0 and v1["summary"]["floor_worst_arm_pos_rms_mm_median"] == 0.25
    assert len(v1["tables"]["seeds"]) == 3 and v1["summary"]["n_seeds"] == 3 and "seeds" not in v1["summary"]


def test_one_changed_number_is_a_new_evaluation_and_a_timestamp_is_not():
    base = compact()
    changed = copy.deepcopy(base)
    changed["v2"]["R1.horse.ur5e.Nur"]["seeds"][1]["algorithms"]["A1"]["k4d_pos_mean_mm"] += 0.001
    retimed = copy.deepcopy(base)
    retimed["v2"]["R1.horse.ur5e.Nur"]["seeds"][1]["started_at"] = "2030-01-01T00:00:00+00:00"
    retimed["v2"]["R1.horse.ur5e.Nur"]["seeds"][1]["algorithms"]["A1"]["runtime_s"] = 99.0

    def evaluation(data, alg):
        return kincal.evaluation_digest_v2(data["v2"]["R1.horse.ur5e.Nur"], "R1.horse.ur5e.Nur", alg)

    assert evaluation(changed, "A1") != evaluation(base, "A1")
    assert evaluation(retimed, "A1") == evaluation(base, "A1")
    assert evaluation(changed, "A0") == evaluation(base, "A0")        # A0's own numbers did not change
    # but the paired ratio of every other algorithm reads A0, so a changed A0 number moves A1 too
    moved = copy.deepcopy(base)
    moved["v2"]["R1.horse.ur5e.Nur"]["seeds"][0]["algorithms"]["A0"]["k4d_pos_mean_mm"] += 1.0
    assert evaluation(moved, "A1") != evaluation(base, "A1")


# ---------------------------------------------------------------------------------------------------------------- Weave


@dataclass(frozen=True)
class FakeEpisode:
    inputs: dict
    output: dict
    scores: dict


@dataclass(frozen=True)
class FakeScoredRun:
    black_box: str
    version: dict
    environment: str
    episodes: list
    summary: dict
    attributes: dict = field(default_factory=dict)


def fake_bbo():
    calls = {}
    bbo = types.SimpleNamespace(Episode=FakeEpisode, ScoredRun=FakeScoredRun, calls=calls,
                                Metric=lambda title, path, minimize=False: (title, path, minimize))
    bbo.delete_unended = lambda client: pytest.fail("delete_unended must be switched off")
    bbo.prune_superseded = lambda client, runs, columns=None: pytest.fail("prune_superseded must be switched off")

    def log_evaluations(entity_project, runs, scorers):
        # what bbo does internally with them: neither may delete
        assert bbo.delete_unended(None) == 0 and bbo.prune_superseded(None, [], None) == 0
        calls["scorers"] = scorers
        calls["runs"] = list(runs)
        return {r.environment: f"ref-{r.environment}" for r in runs}

    def publish_leaderboard(entity_project, name, description, refs, metrics, environments):
        calls["board"] = (entity_project, name, refs, metrics, environments)
        return "weave:///ref"

    bbo.log_evaluations, bbo.publish_leaderboard = log_evaluations, publish_leaderboard
    return bbo


def test_scored_runs_are_algorithms_in_environments_with_seeds_as_episodes():
    runs = kincal.scored_runs(fake_bbo(), compact())
    a1 = next(r for r in runs if r.black_box == "A1")
    assert a1.environment == "R1.horse.ur5e.Nur" and len(a1.episodes) == 3
    assert a1.episodes[0].inputs == {"seed_index": 0}
    assert a1.episodes[0].scores == {"k4d_pos_mean_mm": 5.0, "ratio_vs_A0": 0.5}
    assert a1.summary == {"k4d_pos_mean_mm": 5.0, "k4d_pos_p95_mm": 10.0, "ratio_vs_A0": 0.5}


def test_log_pushes_runs_publishes_one_v2_board_and_deletes_nothing(monkeypatch):
    bbo, pushed = fake_bbo(), {}

    def fake_push(batch, project):
        pushed["batch"], pushed["project"] = batch, project
        return [{"id": r["id"], "url": f"https://forge.coreweave.com/wandb/x/{r['id']}", "name": r["name"], "resumed": False}
                for r in batch]

    monkeypatch.setattr(kincal, "push", fake_push)
    monkeypatch.setattr(kincal, "retire", lambda result_id, evaluation, project: 0)
    monkeypatch.setattr(rigs, "load_bbo", lambda: bbo)
    out = kincal.log(compact())
    assert pushed["project"] == "Kinematic Calibration" and out["runs"] == 2 + 1 and out["leaderboard"] == "weave:///ref"
    entity_project, name, refs, metrics, environments = bbo.calls["board"]
    assert entity_project == "zach-yamaoka-independent/Kinematic Calibration"
    assert name == "Kinematic Calibration · UR horse (v2)"
    assert [m[0] for m in metrics] == ["K4d mean, worst arm (mm)", "K4d p95, worst arm (mm)", "Ratio vs A0 (paired median)"]
    assert all(m[2] for m in metrics) and environments == ["R1.horse.ur5e.Nur"]
    assert "k4d_pos_mean_mm" in bbo.calls["scorers"] and "ratio_vs_A0" in bbo.calls["scorers"]
    assert all(url.startswith("https://wandb.ai/") for url in out["urls"].values())
    assert kincal.log(compact(), weave=False)["leaderboard"] is None


# ---------------------------------------------------------------------------------------------------------------- a later BAM ledger


def bam_row(seed=0, started="2026-11-13T10:00:00-07:00", recovery=None):
    """A BAM cell's row: no UR-only algorithms (just A0 and A0fb), no A1, an arm that is not a UR5e, an optional recovery block."""
    row = v2_row(cell="R1.bam.pair.rigid_wrist", seed=seed, started=started)
    row["setup"] = {"kind": "bam_pair", "arm": "five_bar"}
    row["algorithms"] = {"A0": row["algorithms"]["A0"], "A0fb": row["algorithms"]["A1"]}
    if recovery is not None:
        row["algorithms"]["A0fb"]["parameter_recovery"] = recovery
    return row


def test_a_second_v2_ledger_is_unioned_and_bam_cells_may_lack_algorithms(tmp_path):
    first, second = tmp_path / "v2a.jsonl", tmp_path / "v2b.jsonl"
    v1 = tmp_path / "v1.jsonl"
    first.write_text("\n".join(json.dumps(v2_row(seed=s)) for s in range(2)) + "\n")
    second.write_text("\n".join(json.dumps(bam_row(seed=s)) for s in range(2)) + "\n")
    v1.write_text(json.dumps(v1_row()) + "\n")
    data = kincal.extract(v1, [first, second])
    assert data["sources"]["v2"]["paths"] == [str(first), str(second)] and data["sources"]["v2"]["kept"] == 4
    names = [r["name"] for r in kincal.records(data)]
    assert "A0fb · R1.bam.pair.rigid_wrist" in names and "A1 · R1.bam.pair.rigid_wrist" not in names
    bam = next(r for r in kincal.records(data) if r["name"] == "A0fb · R1.bam.pair.rigid_wrist")
    assert bam["tags"][3] == "five_bar" and bam["config"]["algorithm_desc"] == kincal.ALGORITHM_DESC["A0fb"]
    assert kincal.main(["extract", "--v1", str(v1), "--v2", str(first), "--v2", str(second), "--out", str(tmp_path / "o.json")]) == 0
    assert json.loads((tmp_path / "o.json").read_text())["sources"]["v2"]["kept"] == 4


def test_a_newer_row_in_the_second_ledger_replaces_the_first():
    old, new = v2_row(started="2026-11-07T04:00:00-07:00", a0=99.0), v2_row(started="2026-11-13T04:00:00-07:00", a0=1.0)
    data = compact([old, new])
    assert data["v2"]["R1.horse.ur5e.Nur"]["seeds"][0]["algorithms"]["A0"]["k4d_pos_mean_mm"] == 1.0


def test_a_parameter_recovery_block_becomes_a_parameters_table():
    block = {"q1": {"truth": 1.0, "estimate": 1.1, "error": 0.1}, "q2": 0.5}
    data = compact([bam_row(seed=0, recovery=block), bam_row(seed=1, recovery=[{"parameter": "q1", "error": 0.2}])])
    runs = {r["name"]: r for r in kincal.records(data)}
    table = runs["A0fb · R1.bam.pair.rigid_wrist"]["tables"]["parameters"]
    assert table[0] == {"seed_index": 0, "parameter": "q1", "truth": 1.0, "estimate": 1.1, "error": 0.1}
    assert table[1] == {"seed_index": 0, "parameter": "q2", "value": 0.5}
    assert table[2] == {"seed_index": 1, "parameter": "q1", "error": 0.2}
    assert "parameters" not in runs["A0 · R1.bam.pair.rigid_wrist"]["tables"]
