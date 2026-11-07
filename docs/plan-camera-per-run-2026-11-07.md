# Plan: a compressed camera video beside every rack run (bam_ws, written, not built)

- **Asked by:** Zach, 2026-11-07: "video data saved so I could quickly see it (for cameras you certainly do want to save it)".
- **Why a plan and not code:** the brief allowed a small, safe change in bam_ws only from the worktree
  `/home/bam/bam_ws/.claude/worktrees/sim-to-real-motor-models-f1ee43-v5` on its own branch. On 2026-11-07 that worktree was on
  `claude/otherday-heldout-1107` with a peer's uncommitted changes (`docs/gates_next_report.py`, `tests/test_otherday_heads.py`), not on
  `claude/sim-to-real-motor-models-f1ee43`, so it was not switched and nothing in bam_ws was written.
- **What sim2real does meanwhile:** `tools/build_media.py` cuts each run's clip out of its session's recording on the site's side (317 runs,
  every one whose session filmed its station). This plan moves that cut into the recorder's path, so a run carries its own clip.

## What the archive shows (read 2026-11-07)

| finding | evidence |
|---|---|
| A session films only when its plan names cameras; the recorder then writes `cameras/cam_<serial>.mp4` (H.264, colour, frame *i* is `wall[i]`) and `cam_<serial>.npz` (every frame as raw grey, ~1.2 GB per 100 s, plus the stamps and intrinsics). | `bam_rack_twin/hardware/record.py` docstring; `rack_2026-10-23/session_01a/cameras/` (26 MB mp4, 1.23 GB npz) |
| The recorder holds every grey frame in RAM until it stops: `MAXIMUM_SECONDS = 120.0`, and `session.run` refuses a plan that needs more. | `record.py` `MAXIMUM_SECONDS`; `session.py` "REFUSED: the plan needs about … s of recording" |
| Every schedule session since 10-28 ran with `cameras: []`: CAN 11, 12 and 21's sessions are minutes long. | every `schedules/one-dof-test-rack/*/runs/*/session.json`, `plan.cameras` |
| So of the site's 2,074 runs, 317 were filmed by their station's camera (10-23 to 10-25) and 314 of those have clips (two cameras kept too few pictures for a clip, one stamps file is truncated); the other 1,757 runs' sessions recorded no camera. | `tools/build_media.py`'s index, each run's `why_none` |

## The change (three small parts, each test-first)

1. **`record.py --mp4-only`.** Write the mp4 as frames arrive (it is already piped to ffmpeg) and the stamps (`wall`, `hw_ms`) and
   intrinsics to a small `cam_<serial>.stamps.npz` at the end; never hold the grey frames, so no 120 s ceiling. The default (both files)
   is unchanged. Test: a fake device (synthetic frames, stamps) through `--mp4-only`: frame count = stamp count, no frames array, a
   30-minute recording accepted.
2. **`session.py`: `"camera_mode": "mp4" | "full"`** in a plan (default `"full"`, today's behaviour); the RAM ceiling applies to `"full"`
   only. `bam_rack_twin.schedule`'s plan writer names both D405s with `"camera_mode": "mp4"`. Test: a 30-minute plan is refused in `full`
   and accepted in `mp4`.
3. **A per-run clip at the session's end**, beside the run's npz: `runs/<stem>.cam_<serial>.mp4` (640 × 360, CRF 30, ~15 kB/s) and
   `runs/<stem>.cam_<serial>.json` (`t0`, `fps`, `frames`, `first_frame`, `last_frame`, `repeats`, `max_stamp_gap_s`), cut by the rule
   `tools/build_media.py` uses today (`grid_of`: each frame the camera frame nearest a uniform 30 fps grid from the run's first sample
   − 0.3 s to its last + 0.3 s). The cut then lives in bam_rack_twin as the stock part; sim2real reads a run's own clip when there is one
   and cuts the session recording only for older runs. Test: the cut's frame indices against a nearest-stamp recomputation from the
   stamps (sim2real's site test already holds its own clips to that).

Size: a run's clip is ~15-40 kB/s at 640 × 360; the session mp4 ~0.25 MB/s per camera at 1280 × 720; `--mp4-only` saves the npz's
~12 MB/s per camera.

## Needs Zach

- Whether schedule sessions may drop the raw grey frames (`--mp4-only`): the as-built calibration (`bam_rack_twin.asbuilt`) and tag
  detection read lossless frames from the npz. Recommendation: `mp4` for schedule sessions, `full` for calibration sessions. Default if
  nothing is said: schedule sessions `mp4`, everything else unchanged.
- The rack's lights: the 10-23/24 recordings are dark (the clips are brightened with gamma 0.5 on their luma, as the tag detector sees
  them).
