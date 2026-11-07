"""The site's media (tools/build_media.py's cache folder, served at /media/): what each card and run page shows of it, and the words that
say what you are looking at.

Zach, 2026-11-07: "I would like the runs to be a bit more media rich ... I think we can basically always have a 3D view ... in these cards
I was hoping to see an image of the actual deployment ... more explanatory". Stdlib only. Everything here is read from the media index
(index.json, schema sim2real.media/1); a site built without it shows every page as before, with no picture and no clip.

WHY a cache folder and never git (the brief's size budget): renders, GLBs and clips are build outputs of committed code; the builder is
committed (tools/build_media.py), the media are rebuilt from it.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from dataclasses import dataclass, field

from catalog_workbench.html import e

SCHEMA = "sim2real.media/1"
DEFAULT = pathlib.Path(os.environ.get("SIM2REAL_MEDIA") or pathlib.Path.home() / ".cache" / "sim2real" / "media")
URL = "/media/"


@dataclass
class Media:
    root: pathlib.Path
    scenes: dict = field(default_factory=dict)
    stations: dict = field(default_factory=dict)  # (deployment, station key) -> entry
    runs: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)
    renderer: dict = field(default_factory=dict)

    def scene_url(self, sid: str) -> str | None:
        s = self.scenes.get(sid)
        return URL + s["src"] if s else None

    def glb_url(self, dep_id: str, station: str) -> str | None:
        s = self.stations.get((dep_id, station))
        return URL + s["glb"] if s else None

    def clips(self, run: str) -> bool:
        return bool((self.runs.get(run) or {}).get("media"))

    def models_of(self, run: str) -> list[dict]:
        return [self.models[k] for k in (self.runs.get(run) or {}).get("models", []) if k in self.models]


def load(root: pathlib.Path) -> Media | None:
    path = root / "index.json"
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise SystemExit(f"{path} is {doc.get('schema')!r}, not {SCHEMA}: rebuild it with tools/build_media.py")
    return Media(root=root, scenes={s["id"]: s for s in doc.get("scenes", [])},
                 stations={(s["deployment"], s["station"]): s for s in doc.get("stations", [])},
                 runs=doc.get("runs", {}), models=doc.get("models", {}), renderer=doc.get("renderer", {}))


# --- pictures ---------------------------------------------------------------------------------------------------------------------

def figure(media: Media | None, sid: str, cls: str = "s2r-shot", caption: bool = True, eager: bool = False) -> str:
    """The card's render as a figure (its MuJoCo caption under it), or nothing when the media were not built."""
    s = (media.scenes.get(sid) if media else None)
    if not s:
        return ""
    cap = f'<figcaption>{e(s.get("caption") or "")}</figcaption>' if caption else ""
    return (f'<figure class="{cls}"><img src="{e(URL + s["src"])}" width="{s["width"]}" height="{s["height"]}" alt="{e(s.get("what") or s.get("title") or sid)}" '
            f'loading="{"eager" if eager else "lazy"}" decoding="async">{cap}</figure>')


def thumb(media: Media | None, sid: str) -> str | None:
    """A tile's picture: the render, cropped to the tile (object-fit), or None to keep the tile's own."""
    url = media.scene_url(sid) if media else None
    return f'<span class="pic s2r-tile-shot" data-thumb><img src="{e(url)}" class="s2r-thumb" alt="" loading="lazy" decoding="async"></span>' if url else None


# --- the words --------------------------------------------------------------------------------------------------------------------

def what_deployment(dep_row: dict, media: Media | None) -> str:
    s = media.scenes.get(dep_row["id"]) if media else None
    picture = f"The picture: {s['what']} " if s else ""
    return (f'<p class="s2r-what"><b>What you\'re looking at:</b> {e(picture)}Below, every real run of its {dep_row.get("stations")} stations, newest '
            f"first; open one to play it back, real (blue) against the command (grey, dashed) and every model that replayed it (orange), in 3D and, "
            f"where the session filmed it, beside the camera.</p>")


MODEL_WHAT = (
    # (name prefix, what the model is): the producers' own model names (tools/build_app.py's situations), in words
    ("twin of record", "The station's twin of record: the MuJoCo hinge bam_rack_twin grades the gates with, replaying this run's own command"),
    ("twin A", "The twin deployed before the 10-29 calibration round, replaying this run's command"),
    ("twin C1", "A follow-up of C (the 10-29 round's fit) with a faster inertia fit, replaying this run's command"),
    ("twin C", "The 10-29 calibration round's fit of this station, replaying this run's command"),
    ("twin D", "LuGre friction (bristle stiffness and damping, Coulomb and static friction, a Stribeck speed, viscous) as round 1 of the 10-28 "
               "pre-sliding study identified it"),
    ("twin G", "The same LuGre model with its stiffness, Coulomb and viscous re-identified on the study's train runs"),
    ("twin H", "LuGre plus dwell-time static friction: static friction that grows while the joint rests and resets when it slips"),
    ("twin R", "LuGre with its sliding law swapped for rate-and-state friction (a direct and an evolution term over a slip distance)"),
    ("refit R1", "A friction refit on the train runs only (R1), kept for comparison: not picked under the safer rule"),
    ("twin · full", "The 10-24 dataset study's \"full\" twin: every term that study identified, replaying this run's command"),
)


def model_what(name: str) -> str:
    return next((text for prefix, text in MODEL_WHAT if name.startswith(prefix)), "A model of this station replaying this run's command")


def num(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return e(str(value))
    if value == 0:
        return "0"
    mag = abs(value)
    if mag >= 1e4:
        return f"{value:,.0f}"
    if mag < 1e-3:
        return f"{value:.4g}"
    return f"{value:,.6g}" if mag >= 1 else f"{value:.4g}"


def models_section(row: dict, media: Media | None) -> str:
    """Each model the run plays: what it is, its replay's own label, and its parameters as its source declares them (the twin's own MJCF,
    or the identification file's points, with the fit's start where it kept one); no truth exists for real hardware, so no true column."""
    names = [s for s in row.get("situations", []) if s not in ("real", "target")]
    if not names:
        return ""
    entries = {m["name"]: m for m in (media.models_of(row["run"]) if media else [])}
    arts = []
    for name in names:
        m = entries.get(name) or {}
        params = m.get("parameters") or []
        nominal = any(p.get("nominal") is not None for p in params)
        source = m.get("source")
        where = (" from its own MJCF" if m.get("columns") == "mjcf" else " as the identification file wrote them" if m.get("columns") else "")
        rows = "".join(f'<tr data-key="{e(p["key"])}"><th scope="row">{e(p["key"])}<br><small>{e(p.get("what") or "")}</small></th>'
                       + (f'<td>{num(p.get("nominal"))}</td>' if nominal else "") + f'<td>{num(p.get("value"))}</td><td>{e(p.get("unit") or "")}</td></tr>'
                       for p in params)
        table = (f'<div class="s2r-scroll"><table class="s2r-table s2r-model-params"><thead><tr><th scope="col">parameter</th>'
                 + ('<th scope="col">nominal (the fit\'s start)</th>' if nominal else "")
                 + f'<th scope="col">{"identified" if m.get("columns") == "identified" else "value"}</th><th scope="col">unit</th></tr></thead><tbody>{rows}</tbody></table></div>'
                 if params else "<p class=\"mut\">Its parameters are not exported where this site can read them yet"
                                + (f" (its replay names {e(m.get('label'))})" if m.get("label") and m.get("label") != name else "") + ".</p>")
        src = f'<p class="s2r-model-src"><small>Parameters{e(where)}: <code>{e(source)}</code></small></p>' if source and params else ""
        label = f' <small class="mut">({e(m["label"])})</small>' if m.get("label") and m.get("label") != name else ""
        arts.append(f'<article class="s2r-model" data-model="{e(name)}"><h3><span class="s2r-sim-dot"></span>{e(name)}{label}</h3>'
                    f'<p class="s2r-model-what">{e(model_what(name))}.</p>{table}{src}</article>')
    return (f'<section class="s2r-models" id="models" aria-labelledby="models-h"><h2 id="models-h">Models in this run</h2>'
            f'<p class="lede">Each model plays the real run\'s own command in simulation; its error against real is the Playback\'s "Model error" card '
            f'and the Gates tab\'s T2 row. Real hardware has no hidden truth, so a model\'s parameters are its values, not a recovery.</p>'
            f'<div class="s2r-model-grid">{"".join(arts)}</div></section>')


def example_model_what(doc: dict) -> str:
    """An oracle example's model in a sentence: the MJCF it simulates and the type cards' rungs sysid fits on it (by card, the rung keys)."""
    model = doc["description"]["model"]
    files = [pathlib.Path(model["path"]).name] if model.get("path") else [pathlib.Path(p["path"]).name for p in model.get("parts", [])]
    files += [pathlib.Path(a["path"]).name for a in model.get("attach", []) or []]
    cards = []
    for lad in doc.get("card_ladders", []):
        keys = [r["key"] for r in lad.get("rungs", []) if r.get("identified")]
        if keys:
            cards.append(f"{lad.get('title') or lad['card']} {', '.join(keys)}")
    n = doc["verdict"]["parameters"]
    return (f"The model is {' + '.join(dict.fromkeys(files))} in MuJoCo. sysid fits its {n} parameters on the type cards' rungs "
            + ("; ".join(cards) if cards else "of its typed components") + ", each from the description's nominal value.")


def example_what(doc: dict, media: Media | None) -> str:
    s = media.scenes.get(doc["example"]) if media else None
    picture = (s["what"] + " ") if s else ""
    return (f"{picture}Below: the description sysid reads, the schedule it plans and how much of the joint space it covers, each hidden value "
            f"against the nominal it starts from and the value it recovers, and the held-out error before and after.")


# What each identified parameter is, in plain words (Zach's 11-06 note showed the card's table: "can11.gravity_bott…", no meaning). Keyed by
# the parameter's own name (sysid's results), the band index for a camera's 16 bands.
PARAM_WHAT = {
    "zero_offset_rad": "the joint's zero: where its encoder reads 0 against the true angle",
    "armature_kg_m2": "the inertia about the joint axis (the motor and gearbox, reflected)",
    "damping_nm_s_rad": "viscous friction: torque per unit of speed",
    "frictionloss_nm": "Coulomb friction: the torque that keeps it sliding",
    "friction_stribeck_drop_nm": "Stribeck drop: how far friction falls from sticking to sliding",
    "friction_stribeck_speed_rad_s": "Stribeck speed: how fast that fall happens",
    "gravity_nm": "the gravity torque's amplitude: mass x g x the centre of mass's distance from the axis",
    "gravity_bottom_rad": "the angle where the link hangs (gravity's torque is zero there)",
    "backlash_rad": "the gear's backlash: what the output turns before the teeth meet",
    "mass_kg": "the tool's mass",
    "com_z_m": "the tool's centre of mass along the flange axis",
    "tcp_x_m": "the tool point's offset from the flange, sideways",
    "tcp_z_m": "the tool point's offset from the flange, along its axis",
    "actuator_gain": "the gripper drive: finger force per command count",
    "damping": "the finger drive's viscous damping",
    "roller_radius_m": "the drive roller's radius (belt travel per turn)",
    "moving_mass_kg": "the mass the belt moves",
    "viscous_drag_n_s_m": "drag per unit of belt speed",
    "coulomb_drag_n": "the belt's constant drag",
    "dx_m": "the mount's position offset in x", "dy_m": "the mount's position offset in y", "dz_m": "the mount's position offset in z",
    "rx_rad": "the mount's turn about x", "ry_rad": "the mount's turn about y", "rz_rad": "the mount's turn about z",
    "fx_px": "the focal length in pixels, across", "fy_px": "the focal length in pixels, down",
    "cx_px": "the optical centre on the image, across", "cy_px": "the optical centre on the image, down",
    "focal_px": "the line camera's focal length in pixels", "principal_px": "its optical centre along the line",
    "height_m": "its height above the belt", "across_offset_m": "its offset across the belt",
    "scan_line_x_m": "where along the belt its line falls", "scan_yaw_rad": "its line's turn on the belt",
    "depth_scale": "the depth camera's scale (1 is right)", "depth_offset_m": "its depth offset",
}
_BAND = re.compile(r"^(gain|dark)_b(\d+)$")


def param_what(name: str) -> str:
    band = _BAND.match(name)
    if band:
        return (f"band {int(band.group(2))}'s gain: counts per unit of reflectance" if band.group(1) == "gain"
                else f"band {int(band.group(2))}'s dark level: counts with no light")
    return PARAM_WHAT.get(name, "")
