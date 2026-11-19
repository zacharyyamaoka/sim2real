# Decision: the twin holds its data, refits from it and grows it (2026-11-18)

**Decided:** every fitted `RobotTwin` holds the runs it was fitted on as `fitted.data_`, a `sim2real.calibration.CalibrationData`;
`calibrate(data=)` refits from them on the backend that recorded them, without measuring; datasets grow by session (`data + more`). Lane L7
(gap D) of the sim2real calibrate plan of 2026-11-18; ruler `tests/test_twin_holds_data.py`, plus the agreed ruler change R2 in
`tests/test_real_backend.py` (`on="real", data=` refits held rack runs).

Zach, in his own words:

> and I think its the RobotTwin that can kidna like hold all the dataset, etc. etc. (2026-11-17)

> What about if you are doing like incoeprating life time learning... Then you need to like consider offline datasets (2026-11-17)

> So on any dataset... now I should be able to just like better fit the models no? (2026-11-18)

> The run can come from a calibration routine or just normal operation / ITs all just runs at the end of the day though (2026-11-11)

## What was decided, each with its undo

| call | why | undo |
|---|---|---|
| `CalibrationData(runs, plan, noise=None, meta={}, held_out={}, serves={})`; no `parent`, no `digest` | the two new fields carry what a fit may read and what only judges it; a lineage digest had no consumer yet (gap E's ledger can add one) | drop the two fields; every caller passed keywords |
| `fitted.data_` on every fitted twin: all of `data` when given, else the very recordings the fit read, one key per run; `None` when a runner hands back no measurements | the twin is what holds the dataset; holding a recording never measures it again (the measure count and object identity are tested) | stop setting it |
| `serves` {key: run id it answers}; `answering(run_id)` | the same run recorded on two days is two recordings under one run id; a fit is handed every recording that answers a run it asks for, keyed by recording key | — |
| growth by session, never by key: a session already held is kept once; a re-recorded run is kept as `<key>@<session>` | dedup by key would drop Tuesday's recording of Monday's run id; by session, `(a + b) + b` is `a + b` and nothing is overwritten | — |
| the sim's session id is a hash of (twin, plan ids, noise with its seed, plus, when set, known values, a moved truth, the options `CalibrationConfig.routines` set on planned routines, the custom routines by type, and the values the world played); the rack's is the submission folder's absolute path | deterministic, so the same session collected twice is recognised; what changes the draws changes the id (an injected world through the values it plays; a rig swapped under one twin id is not hashed). Fix round 1 (review): options, custom routines and the world were left out, and the rack used the folder's basename, so two different sessions could share an id | — |
| two datasets that claim one session id with different runs (compared by run name, the session suffix stripped) are refused by name | a session already held is skipped when datasets grow, so a shared id must never drop a whole session silently; `(a + b) + b` and `a + (a + b)` still give `a + b` | drop the check in `CalibrationData.extend` |
| every refit starts from the description's priors: a fitted twin's runner keeps the loaded twin's description (and a rig's world, `RigRunner.with_state`) | the same runs then give the same values generation after generation; before, a rig's refit of a refit read the last fit as its priors, and a fitted tracer's refit was refused for edited priors | a warm start would be an explicit option |
| rack runs are never fitted on the sim, sim draws never refitted as rack runs, and one dataset never mixes the two | rack runs graded against a hidden truth that did not make them would pass or fail on nothing | — |
| a held-out run never becomes a training run, compared by run name with the session suffix stripped | sklearn's leakage rule, as eval() already refuses it | — |
| `calibrate(on="real", data=)` refits held rack runs with no transport, emit or play; `transport=` with `data=` is refused | a refit spends no rack time; a transport plays, so passing one with data would be half-used | — |
| `move_truth` with `data=` is refused | recorded runs were drawn at the truth they were drawn at | — |
| save/load points at the run files, never copies them; pooling across units is refused (another twin's runs) | decided now, built later: a dataset is the runs' references plus their provenance | — |

## Not built in this leg

- Saving and loading a dataset (`data.json` by reference: path, sha256, split, serves).
- Ingesting the 1-DOF campaign rounds as a dataset by query (blocked on the link-camera producer in bam_rack_twin).
- A keep-if-better rule on held-out runs for lifelong refits.

The record schema `sim2real.calibration/1` is unchanged: a record and its data are linked only in a later schema.
