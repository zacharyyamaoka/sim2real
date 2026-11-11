"""Build the conveyor belt calibration report: run every Step on the hidden-truth twin with the recorder on, write one video per routine
plus a hero, the plots, and the HTML.

    env -u VIRTUAL_ENV MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra sim --extra vision python /home/bam/sim2real/docs/build_report_conveyor_belt.py

Writes /home/bam/bam_ws/reports/conveyor-calibration-2026-11-11.html and its media under reports/media/conveyor-calibration-2026-11-11/
(videos are separate files, so the page stays a small text page). Reads seeds.json there if tools/conveyor_belt.py seeds wrote it.
"""

from __future__ import annotations

import html
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

import cv2  # noqa: E402

from sim2real.cards import conveyor_belt as card  # noqa: E402
from sim2real.models.conveyor_belt import NOMINAL, STEPS, contact_height  # noqa: E402

OUT = Path("/home/bam/bam_ws/reports/conveyor-calibration-2026-11-11.html")
MEDIA = OUT.parent / "media" / "conveyor-calibration-2026-11-11"
REL = "media/conveyor-calibration-2026-11-11"
W, H = 640, 360
FPS = 15


class Recorder:
    """Streams twin frames into one MP4 per routine and a hero MP4 of the whole run (every 5th frame)."""

    def __init__(self):
        self.pipes: dict[str, subprocess.Popen] = {}
        self.counts: dict[str, int] = {}
        self.last_sensor = np.zeros((H, W, 3), np.uint8)
        self.posters: dict[str, np.ndarray] = {}
        self.n = 0

    def _pipe(self, name):
        if name not in self.pipes:
            path = MEDIA / f"{name}.mp4"
            self.pipes[name] = subprocess.Popen(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{2 * W}x{H}", "-r", str(FPS), "-i", "-",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "30", "-preset", "veryfast", "-movflags", "+faststart", str(path)],
                stdin=subprocess.PIPE)
            self.counts[name] = 0
        return self.pipes[name]

    def __call__(self, frame: dict) -> None:
        label = frame["label"] or "setup"
        left = cv2.resize(frame["overview"], (W, H), interpolation=cv2.INTER_AREA)
        if "sensor" in frame:
            sensor = frame["sensor"]
            if sensor.ndim == 2:
                sensor = np.repeat(sensor[:, :, None], 3, axis=2)
            self.last_sensor = cv2.resize(sensor, (W, H), interpolation=cv2.INTER_AREA)
            self.sensor_name = frame.get("sensor_name", "")
        right = self.last_sensor.copy()
        img = np.ascontiguousarray(np.hstack([left, right]))
        cv2.rectangle(img, (0, 0), (2 * W, 26), (20, 20, 20), -1)
        cv2.putText(img, f"{label}", (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (120, 230, 140), 1, cv2.LINE_AA)
        cv2.putText(img, getattr(self, "sensor_name", ""), (W + 10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)
        self._pipe(label).stdin.write(img.tobytes())
        self.counts[label] += 1
        if self.counts[label] == max(3, self.counts[label] // 2) or label not in self.posters:
            self.posters[label] = img
        if self.n % 5 == 0:
            self._pipe("hero").stdin.write(img.tobytes())
        self.n += 1

    def close(self):
        for p in self.pipes.values():
            p.stdin.close()
            p.wait()
        self.posters.setdefault("hero", self.posters.get("robot_to_robot", next(iter(self.posters.values()))))
        for label, img in self.posters.items():
            cv2.imwrite(str(MEDIA / f"{label}.jpg"), img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 82])


# ------------------------------------------------------------------------------------------------------------------------------------
# small inline SVG plots (no plotting library)


def svg_plot(series, xlabel, ylabel, width=620, height=240, points=None):
    """series: [(xs, ys, css colour var, label, 'line'|'dots')]."""

    xs_all = np.concatenate([np.asarray(s[0], float) for s in series])
    ys_all = np.concatenate([np.asarray(s[1], float) for s in series])
    x0, x1 = float(xs_all.min()), float(xs_all.max())
    y0, y1 = float(ys_all.min()), float(ys_all.max())
    pad = 0.08 * (y1 - y0 or 1)
    y0, y1 = y0 - pad, y1 + pad
    L, R, T, B = 56, 12, 10, 36

    def X(x):
        return L + (x - x0) / ((x1 - x0) or 1) * (width - L - R)

    def Y(y):
        return T + (1 - (y - y0) / ((y1 - y0) or 1)) * (height - T - B)

    out = [f'<svg viewBox="0 0 {width} {height}" class="plot" role="img">']
    for frac in (0, 0.5, 1):
        yv = y0 + frac * (y1 - y0)
        out.append(f'<line x1="{L}" x2="{width - R}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{Y(yv) + 4:.1f}" class="tick" text-anchor="end">{yv:.3g}</text>')
    for frac in (0, 0.5, 1):
        xv = x0 + frac * (x1 - x0)
        out.append(f'<text x="{X(xv):.1f}" y="{height - 18}" class="tick" text-anchor="middle">{xv:.3g}</text>')
    out.append(f'<text x="{(L + width - R) / 2}" y="{height - 3}" class="axis" text-anchor="middle">{html.escape(xlabel)}</text>')
    out.append(f'<text x="12" y="{(T + height - B) / 2}" class="axis" transform="rotate(-90 12 {(T + height - B) / 2})" text-anchor="middle">{html.escape(ylabel)}</text>')
    lx = L + 8
    for xs, ys, colour, label, kind in series:
        if kind == "line":
            pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
            out.append(f'<polyline points="{pts}" fill="none" stroke="var({colour})" stroke-width="2"/>')
        else:
            out.extend(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.2" fill="var({colour})"/>' for x, y in zip(xs, ys))
        out.append(f'<rect x="{lx}" y="{T + 4}" width="10" height="10" fill="var({colour})"/><text x="{lx + 14}" y="{T + 13}" class="tick">{html.escape(label)}</text>')
        lx += 18 + 7 * len(label)
    out.append("</svg>")
    return "".join(out)


def colour_png(array, name, lo=None, hi=None):
    a = np.asarray(array, float)
    lo = np.nanpercentile(a, 2) if lo is None else lo
    hi = np.nanpercentile(a, 98) if hi is None else hi
    norm = np.clip((a - lo) / ((hi - lo) or 1), 0, 1)
    img = cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_VIRIDIS)
    cv2.imwrite(str(MEDIA / name), cv2.resize(img, (640, int(640 * a.shape[0] / a.shape[1]))))
    return lo, hi


# ------------------------------------------------------------------------------------------------------------------------------------


def main() -> int:
    MEDIA.mkdir(parents=True, exist_ok=True)
    from sim2real.metrics.gate import gate
    from sim2real.models.conveyor_belt import ConveyorBelt
    from sim2real.sim.conveyor_belt import BeltTruth, BeltTwin

    rec = Recorder()
    twin = BeltTwin(NOMINAL, BeltTruth.default(), seed=0, record=rec)
    belt = ConveyorBelt(NOMINAL, twin)
    try:
        cal = belt.calibrate()
        held = belt.eval_twin(cal)
        truths = twin.truths()
        scores = twin.score(cal)
        nominal = twin.score(belt.nominal_calibration())
    finally:
        rec.close()
        twin.close()

    # --- plots and stills from the run's own data -------------------------------------------------------------------------------
    s = cal["scale"]
    line = s["line"]
    along = (s["centres_c1"] - line.origin) @ line.direction
    linear = along - line.m_per_rev * s["revs"]
    linear -= linear.mean()
    order = np.argsort(s["revs"])
    phase = 2 * np.pi * s["revs"][order] / float(NOMINAL.gear_ratio)
    sine = line.runout_m * (np.sin(phase + line.runout_phase_rad))
    sine -= sine.mean() - linear[order].mean()
    scale_svg = svg_plot([(s["revs"], linear * 1e3, "--c2", "camera minus linear fit, mm", "dots"),
                          (s["revs"][order], sine * 1e3, "--c1", f"fitted runout {line.runout_m * 1e3:.3f} mm", "line")],
                         "motor encoder revs", "along-belt, mm")
    # WHY the range from the belt's central band: the side rails are 40 mm nearer and would flatten the belt's own millimetres
    mean_mm, std_mm = cal["plane_depth"]["background"]["mean_m"] * 1e3, cal["plane_depth"]["background"]["std_m"] * 1e3
    band = slice(int(mean_mm.shape[0] * 0.2), int(mean_mm.shape[0] * 0.8))
    lo, hi = colour_png(mean_mm, "background_mean.png", *np.nanpercentile(mean_mm[band], [1, 99]))
    slo, shi = colour_png(std_mm, "background_std.png", *np.nanpercentile(std_mm[band], [1, 99]))
    trace = cal["plane_probe"]["traces"][5]
    z0 = contact_height(trace)
    sel = trace["force_n"] > -1
    zz = (trace["z_m"][sel] - z0) * 1e3
    probe_svg = svg_plot([(zz, trace["force_n"][sel], "--c2", "joint-current force, N", "dots"),
                          (np.array([0.0, zz.min()]), np.array([0.0, (zz.min() / 1e3) / np.polyfit(trace['force_n'][(trace['force_n'] >= 1) & (trace['force_n'] <= 5.5)], trace['z_m'][(trace['force_n'] >= 1) & (trace['force_n'] <= 5.5)], 1)[0]]), "--c1", "fit, intercept = contact", "line")],
                         "tip height above the fitted contact, mm", "press force, N")
    tp = truths["plane_world"]
    pts = cal["plane_probe"]["points_m"]
    probe_rows = "".join(f"<tr><td>{x * 1e3:.0f}</td><td>{y * 1e3:.0f}</td><td>{z * 1e3:.3f}</td><td>{tp.height_at(x, y) * 1e3:.3f}</td>"
                         f"<td>{(z - tp.height_at(x, y)) * 1e3:+.3f}</td></tr>" for x, y, z in pts)
    to = cal["time_offset"]
    pos_raw = np.interp(to["stamps_s"], to["t_log_s"], to["travel_log_m"])
    pos_fix = np.interp(to["stamps_s"] - to["latency_s"], to["t_log_s"], to["travel_log_m"])

    def resid(x):
        a = np.column_stack([np.ones_like(x), x])
        c, *_ = np.linalg.lstsq(a, to["along_m"], rcond=None)
        return (to["along_m"] - a @ c) * 1e3

    t_rel = to["stamps_s"] - to["stamps_s"][0]
    time_svg = svg_plot([(t_rel, resid(pos_raw), "--c3", "stamps as given", "dots"), (t_rel, resid(pos_fix), "--c1", f"shifted {to['latency_s'] * 1e3:.1f} ms", "dots")],
                        "time, s", "camera minus encoder, mm")
    for i, scan in enumerate(cal["line_scan"]["scans"]):
        img = cv2.cvtColor(scan["image"], cv2.COLOR_GRAY2BGR)
        for u, k in scan["corners_px"]:
            cv2.circle(img, (int(round(u)), int(round(k))), 5, (60, 220, 90), 2)
        cv2.imwrite(str(MEDIA / f"line_scan_{i}.png"), cv2.resize(img, (512, int(512 * img.shape[0] / img.shape[1]))))

    seeds = None
    seeds_path = MEDIA / "seeds.json"
    if seeds_path.exists():
        seeds = json.loads(seeds_path.read_text())

    # --- the recovery table ------------------------------------------------------------------------------------------------------
    by_routine = {r.id: r for r in card.ROUTINES}
    rows = []
    for r in card.ROUTINES:
        for q in r.quantities:
            sc, nm, tol = scores[q], nominal[q], float(card.TOLERANCES[q].high)
            ok = gate(abs(sc.error), card.TOLERANCES[q]).passes
            worst = ""
            if seeds:
                errs = [abs(row["error"]) for run in seeds for row in run["rows"] if row["quantity"] == q]
                passes = sum(row["pass"] for run in seeds for row in run["rows"] if row["quantity"] == q)
                worst = f"{max(errs):.3g} ({passes}/{len(errs)})"
            est = f"{sc.estimate:.4g}" if sc.estimate or sc.truth else "&mdash;"
            tru = f"{sc.truth:.4g}" if sc.estimate or sc.truth else "&mdash;"
            rows.append(f'<tr><td>{r.id.split(".")[1]}</td><td><code>{q.split(".", 1)[1]}</code></td><td>{est}</td><td>{tru}</td>'
                        f'<td class="num"><b>{sc.error:+.3g}</b></td><td class="num">{tol:g}</td><td class="num">{worst}</td>'
                        f'<td class="num muted">{nm.error:+.3g}</td><td>{sc.unit}</td><td class="{"ok" if ok else "bad"}">{"pass" if ok else "FAIL"}</td>'
                        f'<td><span class="tag {r.limited_by}">{r.limited_by}</span></td></tr>')
    eval_rows = "".join(f"<tr><td>{k.replace('_', ' ')}</td><td class='num'><b>{v:.3f}</b></td><td class='num'>{float(card.EVAL_TOLERANCES[k].high):g}</td>"
                        f"<td>mm</td><td class='{'ok' if gate(v, card.EVAL_TOLERANCES[k]).passes else 'bad'}'>"
                        f"{'pass' if gate(v, card.EVAL_TOLERANCES[k]).passes else 'FAIL'}</td></tr>" for k, v in held.items())

    def vid(name, caption):
        return (f'<figure><video controls muted loop playsinline preload="metadata" poster="{REL}/{name}.jpg" src="{REL}/{name}.mp4"></video>'
                f'<figcaption>{caption}</figcaption></figure>')

    sections = []
    blurbs = {
        "scale": ("The board steps 0.56 m back and forth three times under camera 1. Each stop gives a ChArUco pose, and travel is regressed on motor revs "
                  "with a once-per-drum-turn sine. The camera sees the belt surface, so belt thickness, wear and runout are all included.", scale_svg),
        "slip": ("The same sweep with 15 kg on the belt. Slip is one minus the ratio of the loaded scale to the unloaded one.", ""),
        "direction": ("No new motion: the direction is the scale data's fitted line. The perpendicular scatter is the sideways tracking wander "
                      f"({cal['direction']['wander_mm']:.3f} mm RMS, including pose noise).", ""),
        "plane_depth": ("Thirty depth frames of the empty belt, averaged per pixel. The mean and std are kept as the background model; the plane is "
                        "fitted through the hand-eye. Range bias (0.4 % at 0.65 m) does not average out, so this routine is camera-limited.",
                        f'<div class="pair"><figure><img src="{REL}/background_mean.png" alt="mean depth"><figcaption>background mean, {lo:.0f}-{hi:.0f} mm</figcaption></figure>'
                        f'<figure><img src="{REL}/background_std.png" alt="depth std"><figcaption>per-pixel std, {slo:.2f}-{shi:.2f} mm</figcaption></figure></div>'),
        "plane_probe": ("A 4 x 4 grid, 0.3 x 0.3 m. Each point descends at 5 mm/s, tares the joint-current force, and stops at 6 N or a 30 mm travel guard. "
                        "The contact height is the zero-force intercept of z on force, which is independent of the threshold and of belt stiffness.",
                        probe_svg + f'<details><summary>all 16 probe points vs the hidden plane</summary><table class="small"><tr><th>x mm</th><th>y mm</th><th>probed z mm</th><th>true z mm</th><th>error mm</th></tr>{probe_rows}</table></details>'),
        "camera_to_camera": ("Three placements. Camera 1's pose of the board is carried by the calibrated belt 4 whole drum turns (1.28 m) and composed with camera 2's pose; "
                             "the rotation is the chordal mean.", ""),
        "robot_to_robot": ("Arm 1 touches the four divots, the belt moves 2 drum turns and arm 1 touches again (the belt's vector in arm 1's own frame). The belt then "
                           f"carries the board 3 more turns to arm 2, which touches. Kabsch fits all 12 pairs; the residual is {cal['robot_to_robot']['residual_mm']:.2f} mm RMS.", ""),
        "time_offset": ("The belt runs at +0.1, -0.1, +0.2 and -0.2 m/s while camera 1 streams at 30 fps. Shifting the encoder log by the latency collapses the "
                        "direction-dependent offset. Motion blur is not modelled, so expect more scatter on the real camera.", time_svg),
        "line_scan": ("The board is measured by camera 1, then carried under the line scanner at 0.1 and 0.4 m/s with one line every 0.5 mm (encoder-triggered). "
                      "ChArUco is detected in the stitched image (green circles). Each corner's belt position places the scan line in camera 1's frame. "
                      "The along-belt shift between the two speeds is the trigger delay.",
                      f'<div class="pair"><figure><img src="{REL}/line_scan_0.png" alt="stitched scan 0.1 m/s"><figcaption>stitched, 0.1 m/s ({cal["line_scan"]["corners"][0]} corners)</figcaption></figure>'
                      f'<figure><img src="{REL}/line_scan_1.png" alt="stitched scan 0.4 m/s"><figcaption>stitched, 0.4 m/s ({cal["line_scan"]["corners"][1]} corners)</figcaption></figure></div>'),
    }
    for step in STEPS:
        r = by_routine[step.routine]
        text, extra = blurbs[step.name]
        video = vid(step.name, f"{r.title}. Left: the cell. Right: the sensor the routine reads.") if (MEDIA / f"{step.name}.mp4").exists() else ""
        qs = ", ".join(f"<code>{q.split('.', 1)[1]}</code> {scores[q].error:+.3g} {scores[q].unit}" for q in r.quantities)
        sections.append(f'<section id="{step.name}"><h3>{html.escape(r.title)} <span class="tag {r.limited_by}">{r.limited_by}-limited</span>'
                        f'{" <span class=\"tag sub\">&lt; 1 mm</span>" if r.sub_mm else ""}</h3><p>{text}</p><p class="muted">Recovered: {qs}. '
                        f'Zach\'s point {r.zach}. Equipment: {html.escape("; ".join(r.equipment))}.</p>{video}{extra}</section>')

    page = TEMPLATE.format(
        hero=vid("hero", "The whole calibration on the twin, every 5th frame. Left: the cell (camera 2 at 1.2 m, line scanner at 0.75 m, arm 2 at 1.5 m). Right: the latest sensor frame."),
        rows="".join(rows), eval_rows=eval_rows, sections="".join(sections),
        seeds_note=(f"Worst |error| over {len(seeds)} seeds (passes/runs)" if seeds else "seed sweep not run"),
        probe=f"{scores['plane_probe.height_mm'].error:+.3f}", depth=f"{scores['plane_depth.height_mm'].error:+.2f}",
        r2r=f"{scores['robot_to_robot.translation_mm'].error:.2f}", c2c=f"{scores['camera_to_camera.translation_mm'].error:.2f}",
        c2h=f"{held['camera_2_handoff_mm']:.2f}",
    )
    OUT.write_text(page)
    print(OUT, f"{OUT.stat().st_size / 1e3:.0f} kB")
    return 0


TEMPLATE = (Path(__file__).with_name("report_conveyor_belt_template.html")).read_text()

if __name__ == "__main__":
    raise SystemExit(main())
