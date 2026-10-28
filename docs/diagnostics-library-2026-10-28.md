# robotdx.diagnostics: the library that computes stock diagnostics (2026-10-28)

**One pure function per stock diagnostic, `diagnose(config, data) -> Result`, a registry of them, and a Result that
converts with no loss into RobotDx's record and into data-ui's diagnostic row.** The reference implementation is
`/home/bam/sim2real/diagnostics_ref/` (stdlib + numpy). On the real rack runs it reproduces bam_rack_twin's published
numbers: 96 of 105 comparisons agree exactly (to 1e-9), and the other 9 differ by at most 4e-4 only because
acceptance.json and kt_can14.json store 3-4 digits. 40 tests pass. It is a reference for RobotDx's owner to lift into the io-diagnostics distribution
as the top-level package `robotdx.diagnostics`. It is not a fork of RobotDx.

What to measure, per part type, is the companion: [diagnostics-catalog-2026-10-28.md](diagnostics-catalog-2026-10-28.md).

## The shape, and whose it is

| Piece | Zach's words | Here |
|---|---|---|
| A frozen config parametrises the check; data comes in at run time | "you essentially like pass in a dataclass config, that paramterizes the diaginstics, and then at run time you just like pass in the data" (Daily Note Oct 28) | every stock diagnostic: `(Config, data) -> Result`, no state, no I/O |
| Calculation apart from the threshold check | "My goal was to seperate the calculation of the metric, and the checking of thresholds." (bam_machine `docs/diagnostic-tracker.md`) | each function measures; `core.judge(value, Limits)` decides |
| Stock first, custom by registration | "for most diaginstics you don't really need to right any standard code beacuse they are so stock... if you do a custom one you can like provide a registery" (Oct 28) | `registry.REGISTRY`: stock on import; custom via `register`, a TOML `[[diagnostic]]` table or the `robotdx.diagnostics` entry point |
| Drill in and configure | "we can actually on the diaginstics kinda like drill in and you can see and even configure these values" (Oct 28) | `Result.config` carries the config as data; `config_from_dict` rebuilds it from a form or a file |
| Stock views | "Using the stock diaginstics we can also have stock visualiztion for them" (Oct 28) | every Spec carries `hint` (data-ui PEP 0010 §10) and `emits` |
| Black boxes self-report; a composite judges itself | the spider rule, 2026-10-22 | `stock.rollup(tolerate_fail=...)`, `caused_by` |
| Gates bound, KPIs optimise | "The gates set the bounds of the design space, and the KPI's are the things to optimize for" (Oct 14) | `Limits` on a gate; `role` = headline / driver / health on a KPI |

## Core types (`core.py`)

- **`Limits(warn_low, warn_high, error_low, error_high)`** in the value's own unit. A value on a limit is inside; strictly beyond trips. `Limits.at_most(error, warn)` / `at_least(...)`. Zero is a real limit (the old code read 0 as "skip").
- **Verdict** `pass | warn | fail | not_run`. No value is `not_run`, never `pass`. Rank is RobotDx's level rank: pass 0, warn 1, not_run 2, fail 4.
- **`Result`**: diagnostic, title, verdict, value, unit, metric, limits, code (PascalCase, required unless pass), message, subject, measurements, payload, family, role, hint, emits, view_extra, evidence, caused_by, config, stamp, target, better, run, t0, t1, why, basis.
- **`emits`** is the payload's shape: `scalar` (the value), `series` (`payload.x`, `payload.y`, optional `group`), `matrix` (`payload.rows`, `cols`, `cells`). `registry.evaluate` refuses a Result whose payload does not match.
- **`run`, `t0`, `t1`** point at the worst evidence: the run and window behind the number, which is where a click on a red cell lands.

## Data (`data.py`)

`Trajectory` follows data-ui PEP 0010 §4: `t` in s from the run's start, and columns that end in their unit (`q_rad`, `q_target_rad`, `qd_rad_s`, `qd_target_rad_s`, `tau_nm`, `i_q_a`, `v_bus_v`, `temp_c`, `mode`, `fault`). Each also carries `run`, `device`, `situation` (real, target, "twin v7") and `source` (real | sim | target), plus `frame`. The arrays stay SI; `rows.py` writes the display projection in degrees.

There are two comparison rulers, both shared by the floor and by fidelity:
- `difference(a, b)`: PEP 0010's rule. It uses a's own samples, b interpolated, and no extrapolation.
- `on_common_clock`: bam_rack_twin's T1 rule, one grid over the overlap. The floor's `clock` config picks between them, and the default reproduces T1.

## Registry (`registry.py`)

`Spec(name, function, config_type, title, family, role, hint, emits, unit, consumers, view_extra)`. It refuses an unknown hint, family or role, and a config that is not a frozen dataclass.

- `evaluate(name, config, data, subject=, stamp=)` runs the function and stamps on the registry's facts.
- `load_toml(path)` reads `[[diagnostic]] name, function = "pkg.mod:fn", config = "pkg.mod:Config", ...`, the same shape as io-diagnostics' `plugins.d`.
- `load_entry_points("robotdx.diagnostics")` loads Specs that packages ship.

## Result -> RobotDx record (`record.py`, stdlib only)

`to_record(result, hardware_id=, expected_period_s=)` writes a `diagnostics-record/0` status line, and `from_record` is its inverse.

| Result | DiagnosticStatus (record v0.2) |
|---|---|
| verdict | level: pass ok, warn warn, fail error, not_run unknown |
| title, message, subject, code, stamp, caused_by | name, message, path, code, stamp, caused_by |
| value, unit, limits, metric | `measurements[0]` (key = metric, limits in the value's unit) |
| measurements | `measurements[1:]` |
| diagnostic, family, role, hint, emits, view_extra, better, run, why, basis, target, t0, t1, config, payload, evidence | `values`, keys `dx.*` (JSON where structured) |

Proof: `tests/test_record.py` sends every stock result through io-diagnostics' own `contract/record.py` (`from_dict`, `validate() == []`, `to_dict`) and back, and gets an equal Result. The test loads the contract read-only, with no bytecode written into that repo. `expected_period_s` is set by a live consumer, so the host derives STALE; a dataset evaluation leaves it unset.

## Result -> data-ui row (`rows.py`)

`result_row(result, parent=, vocabulary="verdict" | "level")` returns exactly PEP 0010 §10's columns, plus `emits`:
`subject, diagnostic, title, verdict|level, rank, value, unit, warn_lo, warn_hi, error_lo, error_hi, target, better, t, t0, t1, run, message, why, evidence, basis, source, sourceUrl, record, parent, hint`.

- `evidence` is `<run>#t=t0&tr=t0,t1`.
- `sample_rows` and `diff_rows` write `samples.json` / `diff_samples.json` rows (`q_deg`, `e_q_mrad` = b - a on a's samples).

## Rollups (`rollup.py`)

- **`rollup`:** the composite's own verdict, with `tolerate_fail` as the spider rule and `not_run` never a pass. `caused_by` names every non-pass member, so RobotDx's `summarize` counts one cause, not two (Rollups note, 2026-10-23).
- **`gate_matrix`:** subjects x gates. A missing cell is `not_run`, and the headline is the count of passing cells (bam_rack_twin's `type_gate_cells`).

## One library, two consumers

- **RobotDx** (one robot, its whole history, a system monitor): `stream.windows(run, window_s, step_s)` slices the stream it already keeps; `stream.monitor` evaluates each window and emits `(Result, record)` with `expected_period_s = step_s`. Debounce, faults and staleness stay in the host (`FaultManager`, `effective_level`). The library never holds state. The old `queue_type = "count" | "timed"` windowing is now the caller's slice.
- **sim2real** (datasets of runs, model vs model vs real): call the functions over runs; any number of models are `situation`s of the same run (`Trajectory.as_situation`). Write `diagnostics.json` and `gates.json` per deployment (PEP 0010 §10). `tools/run_rack.py` does this for the rack.

## Module layout to lift into io-diagnostics

```
robotdx/                        new top-level package beside io_diagnostics/, contract/, io_facts/
  __init__.py
  diagnostics/
    __init__.py                 public API: evaluate, Limits, Result, Trajectory, register, load_toml, ...
    core.py                     Limits, judge, Result, Evidence, Measure, HINTS, EMITS, FAMILIES, ROLES   (stdlib)
    data.py                     Trajectory (PEP 0010 columns), difference, on_common_clock, pairwise_rms   (numpy)
    registry.py                 Spec, REGISTRY, evaluate, config_from_dict, load_toml, load_entry_points  (stdlib)
    record.py                   to_record / from_record: Result <-> diagnostics-record/0 status         (stdlib)
    rows.py                     result_row / sample_rows / diff_rows: data-ui PEP 0010 rows
    rollup.py                   rollup, gate_matrix
    stream.py                   windows, monitor: the RobotDx consumer
    catalog.py                  PARTS, PRIMITIVES, ENTRIES: what each part type gets (data)
    stock/
      __init__.py               registers the stock Specs
      tracking.py               tracking_error, stop_error
      fidelity.py               repeatability_floor, model_error, fidelity_ratio
      truthfulness.py           known_load_gain, kt_consistency
      health.py                 box, sample_rate, fault_codes (+ MOTEUS_CODES)
      coverage.py               coverage
    adapters/
      rack_npz.py               bam_rack_twin npz -> Trajectory (the only file reader)
```

To lift it:
1. Copy `robotdx/` into the io-diagnostics checkout.
2. Add `"robotdx"` to `[tool.hatch.build.targets.wheel] packages`.
3. Add numpy, either as a dependency or as an extra (`diagnostics = ["numpy>=1.26"]`). The record contract and `io_diagnostics` stay stdlib-only.
4. Copy `tests/`. `conftest.py` loads the contract from the checkout; inside io-diagnostics, import `contract.record` directly.

## The old code, mapped

| Old piece (like_keras archive `lk/archive/common/diagnostics/v2/`, bam_machine) | Verdict | Becomes |
|---|---|---|
| `DiagnosticValue(warn, error)` + `check_thresholds` (upper/lower) | keep | `Limits` + `judge`. A value on the limit is inside; 0 is a real limit (was "SKIPPING" = OK) |
| `BoxChartThresholds` / `BoxChartTask` (min, max, mean_min/max, std) | keep the stats | `stock.box`: four `Limits`, a pure function over the window. Thresholds stay numbers, not key strings like `"mean_max [50.0, 60.0]"` |
| `ValueTask` (one scalar, two bounds) | keep | `judge(value, limits)` |
| `EventPeriodTask` (period stats) | adapt | `stock.sample_rate`: Hz and seconds named once. The old `loop_duration` default put Hz-shaped numbers on a period in s, so a healthy loop read ERROR |
| `CounterTask` / `PercentTask` | adapt | `stock.share` (specified): an explicit `better`. Old `success_rate` only had an upper bound, so 100 % success read ERROR |
| `queue_val` / `queue_type` count or timed windows | adapt | the caller slices the window (`stream.windows`); the function takes the window |
| empty window = OK "waiting for values" | drop | `not_run` (record UNKNOWN), never green |
| STALE = 3 > ERROR = 2 numeric worst-of | drop | RobotDx's rank: STALE between UNKNOWN and ERROR; the host derives STALE |
| `DiagnosticTaskManager` (`__getattr__`, append-to-state) | adapt | `registry`: name -> (function, config type), no state |
| `DiagnosticsMixin`, dx tick, ports, heartbeat = `ValueTask(0)` | drop | ROS/component coupling; liveness is the host's `expected_period_s` |
| `DiagonisticClient` (worst level over a 10 s window) | adapt | the host's `summarize` over records; in tests, `assert all(r.verdict == "pass" ...)` |
| `DiagnosticStatus` msgs, `SystemDiagnostics` | adapt | `Result`, which converts to record v0.2 |
| moteus `ErrorDef` table (32-48 ERROR, 96-103 WARN, fix messages) | keep | `stock.fault_codes` + `MOTEUS_CODES` (32-50, 96-105, from moteus registers.md) |
| declared numbers: board_temp max 60/70 C, mean 55/65; fault_count 1/5; transport 3/10; loop period 0.020/0.100 s | keep | the catalog's driver defaults (`prov: his code`) |
| "1 diagnostic per interface", wrapper (bam_docs/diagnostics.md) | keep as a rule | a part type's catalog row set is its interface's contract test |

## Proof on the real rack (rack_2026-10-24/25; `tests/test_rack_oracle.py`, `tools/run_rack.py`)

| Check | Oracle (bam_rack_twin file) | Comparisons | Max \|diff\| |
|---|---|---|---|
| T1 floor, q and tau | floors.json | 16 | 0 |
| T4 stop p90, plain PD (n, median, mean signed too) | stop_accuracy.json | 8 | 0 |
| Tracking RMS and stop p90 per feed-forward fraction | ff_study.json | 64 | 0 |
| T2 twin / floor per class, value and verdict | acceptance.json | 8 (+ 31 class cells) | 4e-4 (rounding to 3 dp) |
| T3 twin torque / tau floor | acceptance.json | 8 | 0 |
| Real tracking RMS per dataset run | dataset_twin_can{1,4,14,15}.json | 48 | 0 |
| Limiter shares, row rate, temp max, voltage min, error RMS, speed peak | envelope_rungs.json | 75 runs | 0 |
| Kt artifact, board Kv / measured Kv | kt_can14.json | 1 | 4e-5 (rounding) |

- Gate verdicts agree with acceptance.json on 39 of 40 cells (8 stations x T1, T2, T3, T4, T6).
- **CAN 21's T4 differs.** acceptance.json scores T4 on the PID auto-tuner's proposal (6.32 mrad, never written to the board). The library scores the best controller the rack actually ran (plain PD, 36.9 mrad).
- **The rulers can fail.** A 10 ms floor clock moves CAN 14's floor off the oracle, and a test asserts it.

## Deliberately left out

- **A 0-1 health score.** His raw notes never ask for one (only AI synthesis did), and worst-of plus counts plus `caused_by` is honest.
- **Debounce, fault memory and staleness.** They are the host's: RobotDx `FaultManager`, `effective_level`.
- **The 17 specified primitives** (step response, ISO 9283 pose/path, hysteresis loop, Allan, reprojection, depth plane, spectral, share, agreement, stamp delay, sharpness, marker drift, event interval, staleness, feedback share). The catalog defines each; each lands like the 13 here.
- **Any write to io-diagnostics, data-ui, bam_ws or pidtuna.**
