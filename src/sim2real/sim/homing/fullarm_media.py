"""Videos of full-arm homing episodes: the bam_fb_v2 twin WITH its visual meshes, posed at each traced tick, rendered offscreen (MuJoCo's
Renderer, EGL) and encoded with ffmpeg (H.264 mp4 + a GIF fallback). Stock parts: mujoco.Renderer, ffmpeg. Ours: the framing and the caption.

    env -u VIRTUAL_ENV MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m sim2real.sim.homing.fullarm_media --help

The episode is re-run here (deterministic: same plant, start, prior and procedure) with ``trace_every`` set, then each traced pose is copied
joint by joint (by name) from the plant's model into the visual model, so a backlash twin's extra gear joints never shift the pose.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import fullarm_home as fh

PANEL = 480
WIDTH, HEIGHT = 2 * PANEL, PANEL  # the whole arm | a close-up that follows the wrist
FPS = 30


_VISUAL: dict = {}


def visual_model(belt: bool = False):
    """The bam_fb_v2 twin with every visual mesh (the bundle's full scene), on the rack mount, no backlash, plus a floor and light; with
    ``belt`` the rack's belt drawn under it (bam_fb_test_rig CONVEYOR - the homing routine's videos, where the arm starts on it)."""
    import mujoco  # noqa: PLC0415

    from .mujoco_plant import bam_ws_path  # noqa: PLC0415

    bam_ws_path()
    from bam_fb_test_rig.model import CONVEYOR, STIFF, build_model  # noqa: PLC0415

    if belt in _VISUAL:
        rig = _VISUAL[belt]
        return rig, mujoco.MjData(rig.model)
    rig = build_model(fh.load_v2_bundle(strip=False), STIFF, mount=fh.v2_mount(), conveyor=CONVEYOR if belt else None, backlash=None)
    _VISUAL[belt] = rig
    model = rig.model
    model.vis.global_.offwidth = max(model.vis.global_.offwidth, PANEL)
    model.vis.global_.offheight = max(model.vis.global_.offheight, PANEL)
    return rig, mujoco.MjData(model)


def pose_mapper(plant_model, view_model):
    """(plant qpos index, view qpos index) for every 1-dof joint both models share by name."""
    pairs = []
    for j in range(view_model.njnt):
        name = view_model.joint(j).name
        try:
            k = plant_model.joint(name).id
        except KeyError:
            continue
        pairs.append((int(plant_model.jnt_qposadr[k]), int(view_model.jnt_qposadr[j])))
    return pairs


def render_frames(plant_model, trace: dict, *, every: int = 1, azimuth: float = 110.0, elevation: float = -12.0, distance: float = 1.7,
                  lookat=(0.08, 0.0, 0.42), captions: bool = True, belt: bool = False) -> list[np.ndarray]:
    import mujoco  # noqa: PLC0415

    rig, data = visual_model(belt)
    model = rig.model
    pairs = pose_mapper(plant_model, model)
    wide = mujoco.MjvCamera()
    wide.azimuth, wide.elevation, wide.distance = azimuth, elevation, distance
    wide.lookat[:] = lookat
    close = mujoco.MjvCamera()  # follows wrist 1's body (hard_stop), looking along the five-bar's plane normal a little from above
    close.azimuth, close.elevation, close.distance = azimuth, -20.0, 0.55
    wrist = model.body("hard_stop").id
    option = mujoco.MjvOption()
    for group in range(6):
        # group 2 is bam_fb_test_rig's belt, rails and floor (drawn only when the model was built with them)
        option.geomgroup[group] = 1 if group in (0, 1) or (belt and group == 2) else 0
    frames = []
    with mujoco.Renderer(model, PANEL, PANEL) as renderer:
        for k in range(0, len(trace["t"]), every):
            q = trace["qpos"][k]
            data.qpos[:] = model.qpos0
            for a, b in pairs:
                data.qpos[b] = q[a]
            mujoco.mj_kinematics(model, data)
            renderer.update_scene(data, wide, option)
            left = renderer.render().copy()
            close.lookat[:] = data.xpos[wrist]
            renderer.update_scene(data, close, option)
            right = renderer.render().copy()
            image = np.hstack([left, right])
            if captions:
                touching = list(trace["self_contact"][k]) + list((trace.get("belt") or [[]] * len(trace["t"]))[k])
                image = caption(image, f"t {trace['t'][k]:5.1f} s   {trace['step'][k][:70]}",
                                "CONTACT " + ", ".join(touching) if touching else "")
            frames.append(image)
    return frames


def caption(image: np.ndarray, text: str, alert: str = "") -> np.ndarray:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    picture = Image.fromarray(image)
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 0, WIDTH, 22), fill=(20, 20, 20))
    draw.text((8, 5), text, fill=(235, 235, 235))
    if alert:
        draw.rectangle((0, HEIGHT - 22, WIDTH, HEIGHT), fill=(150, 30, 30))
        draw.text((8, HEIGHT - 17), alert, fill=(255, 255, 255))
    return np.asarray(picture)


def encode(frames: list[np.ndarray], out_mp4: Path, *, fps: int = FPS, gif: bool = True) -> dict:
    """H.264 mp4 (yuv420p, faststart) and a half-size GIF beside it."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "frames.rgb"
        raw.write_bytes(b"".join(f.astype(np.uint8).tobytes() for f in frames))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(fps),
                        "-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", "-movflags", "+faststart", str(out_mp4)], check=True)
    out = {"mp4": str(out_mp4), "mp4_bytes": out_mp4.stat().st_size}
    if gif:  # half size
        out_gif = out_mp4.with_suffix(".gif")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_mp4), "-vf", "fps=10,scale=480:-1:flags=lanczos", str(out_gif)],
                       check=True)
        out.update({"gif": str(out_gif), "gif_bytes": out_gif.stat().st_size})
    return out


def episode_video(spec: dict, start, out_mp4: Path, *, kind: str = "B0", speedup: float = 4.0, table=None) -> dict:
    """Run ``FullArmHome(**spec)`` from ``start`` on ``kind`` and render it at ``speedup`` x real time. Returns the files and the report."""
    from .fullarm_check import run_episode  # noqa: PLC0415
    from .fullarm_plant import FullArmHomingPlant, arm_prior  # noqa: PLC0415
    from .fullarm_procedures import FullArmHome  # noqa: PLC0415

    plant = FullArmHomingPlant(kind)
    every_tick = max(1, round(speedup / (FPS * 0.01)))  # ticks are 10 ms; one frame per (speedup / FPS) s of sim
    report = run_episode(FullArmHome(**spec), plant, start, arm_prior(table), trace_every=every_tick)
    frames = render_frames(plant.rig.model, report.trace)
    files = encode(frames, out_mp4)
    summary = asdict(report)
    summary.pop("trace", None)
    still = out_mp4.with_suffix(".jpg")
    from PIL import Image  # noqa: PLC0415

    Image.fromarray(frames[len(frames) // 2]).save(still, quality=85)
    return {**files, "still": str(still), "report": summary, "speedup": speedup, "frames": len(frames)}


def main(argv=None) -> int:
    from .fullarm_check import starts  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    adversarial = {s.name: s for s in starts("adversarial")}
    real = starts("real")[0]
    from .fullarm_plant import ArmStart  # noqa: PLC0415
    from .fullarm_check import HOME_CRAIG_DEG  # noqa: PLC0415

    trap = ArmStart("W1 -100 / W2 -150 (settles W1 -42 / W2 -140)", *HOME_CRAIG_DEG, (-100.0, -150.0, 0.0), 15.0, family="adversarial")
    jobs = [("park_first_real", {"order": "park_first"}, real),
            ("zach_v1_trap", {"order": "zach_v1", "wrist_only": True}, trap),
            ("park_first_trap", {"order": "park_first", "wrist_only": True}, trap),
            ("park_first_corner", {"order": "park_first", "wrist_only": True}, adversarial["W1 past 105, W2 past 105 (corner)"])]
    index = {}
    for name, spec, start in jobs:
        index[name] = episode_video(spec, start, args.out_dir / f"{name}.mp4")
        print(name, index[name]["mp4_bytes"], index[name]["report"]["outcome"][:100])
    (args.out_dir / "videos.json").write_text(json.dumps(index, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
