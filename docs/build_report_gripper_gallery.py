"""Gallery: every MuJoCo Menagerie model with a gripper or hand - its visual vs collision geometry and contact settings.

Runs on the latest MuJoCo from PyPI (no sim2real import), against a Menagerie checkout:

    MUJOCO_GL=egl uv run --isolated --with mujoco --with pillow python docs/build_report_gripper_gallery.py <menagerie_dir>

Writes /home/bam/sim2real/reports/media/gripper-gallery-2026-11-11.html (self-contained) and, beside it,
gripper-gallery-2026-11-11.json (the extracted settings, one row per model file). Read by
docs/practice-gripper-contact-sim-2026-11-11.md.

What counts as a gripper: a body whose name reads as a finger part (FINGER_WORDS). The gallery frames the lowest
common ancestor of those bodies; the settings columns are read from the COMPILED model (defaults resolved), for the
collision geoms on finger bodies only, and the solver options from the scene file that includes the model when there
is one (Menagerie keeps impratio/cone there).
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image

OUT_DIR = Path("/home/bam/sim2real/reports/media")
STEM = "gripper-gallery-2026-11-11"
FINGER_WORDS = re.compile(
    r"finger|pad|jaw|claw|thumb|index|middle|ring(?!_?gear)|pinky|little|fingertip|knuckle|phalan|distal|proximal"
    r"|follower|digit|gripper_link|inner_knuckle|left_inner|right_inner|carriage"
    r"|gripper_left|gripper_right|gripper_finger|gripperMover|fngr|rubber_tip|^(if|mf|rf|th|lf|ff)_",
    re.IGNORECASE,
)
NOT_FINGER = re.compile(r"spring|bearing|string|wrist|forearm|elbow|shoulder|head|hip|knee|ankle|toe|foot|leg|camera",
                        re.IGNORECASE)
TYPE_COLOURS = {
    mujoco.mjtGeom.mjGEOM_BOX: (0.20, 0.45, 0.95),
    mujoco.mjtGeom.mjGEOM_CAPSULE: (0.98, 0.55, 0.10),
    mujoco.mjtGeom.mjGEOM_SPHERE: (0.15, 0.75, 0.35),
    mujoco.mjtGeom.mjGEOM_CYLINDER: (0.65, 0.35, 0.90),
    mujoco.mjtGeom.mjGEOM_ELLIPSOID: (0.95, 0.30, 0.60),
    mujoco.mjtGeom.mjGEOM_MESH: (0.62, 0.62, 0.66),
}
TYPE_NAMES = {value: name.removeprefix("mjGEOM_").lower() for name, value in mujoco.mjtGeom.__members__.items()}
WIDTH, HEIGHT = 480, 380
# Grippers whose finger bodies carry no finger-like name (read from each model's own kinematic tree).
NAMED_FINGERS = {"agilex_piper": ("link7", "link8"), "arx_l5": ("link7", "link8")}
# Matched by name but not grippers: a fruit fly's tarsal claws and a soft robotic foot.
NOT_GRIPPERS = {"flybody", "iit_softfoot", "anybotics_anymal_b", "anybotics_anymal_c", "ms_human_700"}  # legs named LF_/RF_; a musculoskeletal human


def geom_type_name(value: int) -> str:
    return TYPE_NAMES.get(mujoco.mjtGeom(value), str(value))


def is_collision(model, geom: int) -> bool:
    return bool(model.geom_contype[geom] or model.geom_conaffinity[geom])


def finger_bodies(model, folder: str = "") -> list[int]:
    if folder in NAMED_FINGERS:
        return [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name) for name in NAMED_FINGERS[folder]]
    found = []
    for body in range(1, model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body) or ""
        if FINGER_WORDS.search(name) and not NOT_FINGER.search(name):
            found.append(body)
    return found


def ancestors(model, body: int) -> list[int]:
    chain = [body]
    while body != 0:
        body = int(model.body_parentid[body])
        chain.append(body)
    return chain


def common_ancestor(model, bodies: list[int]) -> int:
    chains = [ancestors(model, body) for body in bodies]
    shared = set(chains[0]).intersection(*map(set, chains[1:]))
    return next(body for body in chains[0] if body in shared)


def gripper_root(model, bodies: list[int]) -> int:
    """The smallest body whose subtree holds finger bodies on >= 2 child branches (searched up from every finger
    body): a parallel gripper's base or a hand's palm, and only ONE gripper on a bimanual robot."""

    finger_set = set(bodies)
    best = None
    for start in bodies:
        for candidate in ancestors(model, start):
            children = [body for body in range(1, model.nbody) if int(model.body_parentid[body]) == candidate]
            branches = sum(1 for child in children if subtree(model, child) & finger_set)
            if branches >= 2:
                size = len(subtree(model, candidate))
                if best is None or size < best[0]:
                    best = (size, candidate)
                break
    return best[1] if best else int(model.body_parentid[bodies[0]])


def subtree(model, root: int) -> set[int]:
    return {body for body in range(model.nbody) if root in ancestors(model, body)}


def scene_options(path: Path):
    """Solver options from a scene file in the same folder that includes ``path`` (Menagerie's convention)."""

    for scene in sorted(path.parent.glob("*.xml")):
        if scene == path:
            continue
        text = scene.read_text(errors="ignore")
        if re.search(rf'<include\s+file="{re.escape(path.name)}"', text):
            try:
                return mujoco.MjModel.from_xml_path(str(scene)).opt, scene.name
            except Exception:  # noqa: BLE001 - a scene that does not compile leaves the model's own options
                continue
    return None, None


def options_row(opt) -> dict:
    flags = []
    for name in ("mjDSBL_MULTICCD", "mjDSBL_NATIVECCD"):
        bit = getattr(mujoco.mjtDisableBit, name, None)
        if bit is not None and opt.disableflags & int(bit):
            flags.append(name.removeprefix("mjDSBL_").lower() + " off")
    multiccd_enable = getattr(mujoco.mjtEnableBit, "mjENBL_MULTICCD", None)
    if multiccd_enable is not None and opt.enableflags & int(multiccd_enable):
        flags.append("multiccd on")
    return {
        "timestep_ms": round(1000 * float(opt.timestep), 3),
        "integrator": ["euler", "rk4", "implicit", "implicitfast"][int(opt.integrator)],
        "cone": "elliptic" if int(opt.cone) == int(mujoco.mjtCone.mjCONE_ELLIPTIC) else "pyramidal",
        "impratio": round(float(opt.impratio), 3),
        "noslip_iterations": int(opt.noslip_iterations),
        "iterations": int(opt.iterations),
        "flags": flags,
    }


def render(model, data, root_bodies: set[int], mode: str, camera) -> Image.Image:
    model = model  # rgba edits are restored by the caller (copy)
    rgba = model.geom_rgba.copy()
    matid = model.geom_matid.copy()
    for geom in range(model.ngeom):
        inside = int(model.geom_bodyid[geom]) in root_bodies
        collision = is_collision(model, geom)
        if not inside:
            model.geom_rgba[geom, 3] = 0.0
        elif mode == "visual":
            if collision and model.geom_group[geom] >= 3:
                model.geom_rgba[geom, 3] = 0.0
            elif collision:
                # A geom that is both drawn and collides (no separate visual layer): drawn as-is.
                pass
        else:
            if collision:
                model.geom_matid[geom] = -1
                model.geom_rgba[geom] = (*TYPE_COLOURS.get(mujoco.mjtGeom(model.geom_type[geom]), (0.5, 0.5, 0.5)), 1.0)
            else:
                model.geom_rgba[geom, 3] = 0.0
    option = mujoco.MjvOption()
    option.geomgroup[:] = 1
    option.sitegroup[:] = 0
    model.vis.headlight.ambient[:] = 0.42
    model.vis.headlight.diffuse[:] = 0.62
    model.vis.headlight.specular[:] = 0.08
    with mujoco.Renderer(model, height=HEIGHT, width=WIDTH) as renderer:
        renderer.update_scene(data, camera=camera, scene_option=option)
        pixels = renderer.render().copy()
        # WHY a depth pass: Menagerie robot files carry no skybox, so the background renders black; pixels at the far
        # plane are background and turn light without touching the robot's. (Segmentation rendering raises an
        # IndexError on some models in MuJoCo 4.0.1.)
        renderer.enable_depth_rendering()
        renderer.update_scene(data, camera=camera, scene_option=option)
        depth = renderer.render()
        renderer.disable_depth_rendering()
    pixels[depth >= 0.999 * float(depth.max())] = (236, 237, 240)
    image = Image.fromarray(pixels)
    model.geom_rgba[:] = rgba
    model.geom_matid[:] = matid
    return image


def jpeg_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def summarise_contacts(model, fingers: set[int]) -> dict:
    geoms = [geom for geom in range(model.ngeom) if int(model.geom_bodyid[geom]) in fingers and is_collision(model, geom)]
    if not geoms:
        return {"finger_collision_geoms": 0}

    def distinct(values, digits=4):
        return sorted({tuple(round(float(v), digits) for v in np.atleast_1d(value)) for value in values})

    return {
        "finger_collision_geoms": len(geoms),
        "types": dict(Counter(geom_type_name(model.geom_type[geom]) for geom in geoms)),
        "condim": sorted({int(model.geom_condim[geom]) for geom in geoms}),
        "friction": distinct(model.geom_friction[geom] for geom in geoms),
        "solref": distinct(model.geom_solref[geom] for geom in geoms),
        "solimp": distinct(model.geom_solimp[geom][:3] for geom in geoms),
        "priority": sorted({int(model.geom_priority[geom]) for geom in geoms}),
        "margin_mm": sorted({round(1000 * float(model.geom_margin[geom]), 3) for geom in geoms}),
    }


def camera_for(model, data, bodies: set[int]):
    points = []
    for geom in range(model.ngeom):
        if int(model.geom_bodyid[geom]) in bodies:
            centre, radius = data.geom_xpos[geom], float(model.geom_rbound[geom])
            if radius > 0.6:  # planes / huge meshes would blow the framing up
                continue
            points.append((centre, radius))
    centre = np.mean([point for point, _ in points], axis=0)
    extent = max(np.linalg.norm(point - centre) + radius for point, radius in points)
    camera = mujoco.MjvCamera()
    camera.lookat[:] = centre
    camera.distance = 0.95 * extent / np.tan(np.radians(model.vis.global_.fovy / 2.0))
    camera.azimuth, camera.elevation = 135.0, -20.0
    return camera


def entries(menagerie: Path):
    for path in sorted(menagerie.glob("*/*.xml")):
        if path.name.startswith("scene") or path.parent.name in {"assets", "test", "python", *NOT_GRIPPERS}:
            continue
        try:
            model = mujoco.MjModel.from_xml_path(str(path))
        except Exception as error:  # noqa: BLE001 - recorded, never silently dropped
            yield {"model": path.parent.name, "file": path.name, "error": str(error).splitlines()[0][:160]}
            continue
        bodies = finger_bodies(model, path.parent.name)
        if not bodies:
            continue
        data = mujoco.MjData(model)
        if model.nkey:
            mujoco.mj_resetDataKeyframe(model, data, 0)
        mujoco.mj_forward(model, data)
        root = gripper_root(model, bodies)
        framed = subtree(model, root)
        fingers = set()
        for body in bodies:
            fingers |= subtree(model, body)
        if not summarise_contacts(model, {b for body in bodies for b in subtree(model, body)}).get("finger_collision_geoms"):
            continue  # finger bodies with no collision geoms (e.g. MS-Human-700's locomotion variant): nothing to show
        opt, scene_name = scene_options(path)
        camera = camera_for(model, data, framed)
        row = {
            "model": path.parent.name,
            "file": path.name,
            "framed_body": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, root),
            "finger_bodies": len(bodies),
            "contacts": summarise_contacts(model, fingers),
            "options": options_row(opt if opt is not None else model.opt),
            "options_from": scene_name or path.name,
            "visual": jpeg_uri(render(model, data, framed, "visual", camera)),
            "collision": jpeg_uri(render(model, data, framed, "collision", camera)),
        }
        print(path.parent.name, path.name, row["contacts"].get("types"), flush=True)
        yield row


def fmt(values) -> str:
    if not values:
        return "—"
    return "<br>".join(" ".join(f"{v:g}" for v in value) if isinstance(value, (list, tuple)) else f"{value:g}"
                       for value in values)


def card(row: dict) -> str:
    contacts, options = row["contacts"], row["options"]
    types = ", ".join(f"{count} {name}" for name, count in sorted(contacts.get("types", {}).items())) or "none"
    flags = ", ".join(options["flags"]) or "defaults"
    return f"""<article class="card" data-types="{html.escape(' '.join(contacts.get('types', {})))}">
<h3>{html.escape(row['model'])} <small>{html.escape(row['file'])}{(' (+ ' + html.escape(', '.join(row['variants'])) + ', same settings)') if row.get('variants') else ''}</small></h3>
<div class="pair"><figure><img loading="lazy" src="{row['visual']}" alt="visual"><figcaption>visual</figcaption></figure>
<figure><img loading="lazy" src="{row['collision']}" alt="collision"><figcaption>collision</figcaption></figure></div>
<table>
<tr><th>finger collision geoms</th><td>{types}</td></tr>
<tr><th>condim</th><td>{fmt(contacts.get('condim'))}</td></tr>
<tr><th>friction</th><td>{fmt(contacts.get('friction'))}</td></tr>
<tr><th>solref</th><td>{fmt(contacts.get('solref'))}</td></tr>
<tr><th>solimp</th><td>{fmt(contacts.get('solimp'))}</td></tr>
<tr><th>priority · margin</th><td>{fmt(contacts.get('priority'))} · {fmt(contacts.get('margin_mm'))} mm</td></tr>
<tr><th>options <small>({html.escape(row['options_from'])})</small></th><td>{options['cone']}, impratio {options['impratio']:g},
noslip {options['noslip_iterations']}, dt {options['timestep_ms']:g} ms, {options['integrator']}, {flags}</td></tr>
</table></article>"""


def main() -> None:
    menagerie = Path(sys.argv[1])
    commit = subprocess.run(["git", "-C", str(menagerie), "log", "-1", "--format=%h %cs"], capture_output=True,
                            text=True).stdout.strip()
    rows = list(entries(menagerie))
    good, seen = [], {}
    for row in rows:
        if "error" in row:
            continue
        key = (row["model"], json.dumps(row["contacts"], sort_keys=True), json.dumps(row["options"], sort_keys=True))
        if key in seen:
            seen[key]["variants"].append(row["file"])
            continue
        row["variants"] = []
        seen[key] = row
        good.append(row)
    errors = [row for row in rows if "error" in row]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{STEM}.json").write_text(json.dumps(
        {"menagerie": commit, "mujoco": mujoco.__version__,
         "rows": [{k: v for k, v in row.items() if k not in ("visual", "collision")} for row in good],
         "not_compiled": [row for row in rows if "error" in row]}, indent=1))
    legend = "".join(
        f'<span><i style="background:rgb({",".join(str(int(255 * c)) for c in colour)})"></i>{geom_type_name(kind)}</span>'
        for kind, colour in TYPE_COLOURS.items()
    )
    page = TEMPLATE.format(
        count=len(good), commit=html.escape(commit), mujoco=mujoco.__version__, legend=legend,
        cards="".join(card(row) for row in good),
        errors="".join(f"<li>{html.escape(row['model'])}/{html.escape(row['file'])}: {html.escape(row['error'])}</li>"
                       for row in errors) or "<li>none</li>",
        summary=summary(good),
    )
    (OUT_DIR / f"{STEM}.html").write_text(page)
    print(OUT_DIR / f"{STEM}.html", f"{len(good)} grippers, {len(errors)} files did not compile")


def summary(rows: list[dict]) -> str:
    """Counts over the distinct set-ups, then the curved-finger prior art read off the same rows."""

    total = len(rows)
    types = [set(row["contacts"].get("types", {})) for row in rows]
    primitive = sum(1 for kinds in types if kinds - {"mesh"})
    mesh_only = sorted({row["model"] for row, kinds in zip(rows, types) if kinds == {"mesh"}})
    elliptic = sum(1 for row in rows if row["options"]["cone"] == "elliptic")
    impratio = sum(1 for row in rows if row["options"]["impratio"] >= 10)
    noslip = [f"{row['model']} ({row['options']['noslip_iterations']})" for row in rows if row["options"]["noslip_iterations"]]
    condim = sum(1 for row in rows if max(row["contacts"].get("condim", [3])) >= 4)
    priority = sum(1 for row in rows if max(row["contacts"].get("priority", [0])) >= 1)

    def kinds(model: str) -> str:
        row = next((row for row in rows if row["model"] == model), None)
        if row is None:
            return "absent"
        return ", ".join(f"{count} {name}" for name, count in row["contacts"]["types"].items())

    return (
        f"<b>{primitive} of {total} set-ups put primitives (box / capsule / sphere / cylinder) on the fingers; "
        f"{len(mesh_only)} models collide on meshes only</b> ({', '.join(mesh_only)}).<br>"
        "<b>Curved fingers are approximated with chains of small primitives, not one box:</b> "
        f"LEAP hand {kinds('leap_hand')}; Allegro {kinds('wonik_allegro')}; TetherIA Aero "
        f"{kinds('tetheria_aero_hand_open')}; Google robot {kinds('google_robot')}; Shadow hand {kinds('shadow_hand')}; "
        f"RB-Y1 {kinds('rainbow_robotics_rby1')}; ALOHA {kinds('aloha')} (small sphere pads on the mesh fingers).<br>"
        f"Options: elliptic cone in {elliptic}/{total}, impratio &ge; 10 in {impratio}/{total}; finger condim &ge; 4 in "
        f"{condim}/{total}; pad priority set in {priority}/{total}; noslip only in {', '.join(noslip) or 'none'}."
    )

TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Menagerie Gripper Gallery</title>
<style>
:root{{--bg:#fbfbfa;--fg:#1f2328;--muted:#656d76;--line:#e4e4e2;--card:#fff;--accent:#3b6fd8}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#16181b;--fg:#e6e6e3;--muted:#9aa0a6;--line:#2c3036;--card:#1d2024;--accent:#7aa2f7}}}}
:root[data-theme="dark"]{{--bg:#16181b;--fg:#e6e6e3;--muted:#9aa0a6;--line:#2c3036;--card:#1d2024;--accent:#7aa2f7}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14.5px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}}
main{{max-width:1240px;margin:0 auto;padding:26px 16px 70px}}h1{{font-size:25px;margin:0 0 6px}}.sub{{color:var(--muted);margin:0 0 16px}}
.lead{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:6px;padding:12px 16px}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0;color:var(--muted);font-size:13px}}.legend i{{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px;vertical-align:-1px}}
.filters{{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 16px}}.filters button{{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:14px;padding:3px 11px;cursor:pointer;font-size:13px}}
.filters button.on{{border-color:var(--accent);color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(370px,1fr));gap:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}}.card h3{{margin:0 0 6px;font-size:15px}}.card h3 small{{color:var(--muted);font-weight:400}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}figure{{margin:0}}img{{width:100%;border-radius:4px;display:block;cursor:zoom-in}}img.big{{position:fixed;inset:0;margin:auto;width:min(92vw,900px);height:auto;z-index:9;box-shadow:0 0 0 100vmax rgba(0,0,0,.6);cursor:zoom-out}}figcaption{{font-size:11.5px;color:var(--muted);text-align:center}}
.card table{{width:100%;border-collapse:collapse;margin-top:6px;font-size:12.5px}}.card th{{text-align:left;color:var(--muted);font-weight:500;padding:3px 6px 3px 0;vertical-align:top;width:34%}}.card td{{padding:3px 0;font-family:ui-monospace,Menlo,monospace;font-size:12px}}
.card th small{{display:block;font-size:10.5px}}
details{{margin-top:24px;color:var(--muted)}}
</style></head><body><main>
<h1>Menagerie gripper gallery: visual vs collision</h1>
<p class="sub">Every MuJoCo Menagerie model with a gripper or hand ({count} distinct set-ups; variants with identical settings merged) · Menagerie {commit} · MuJoCo {mujoco} · settings read from the compiled model, collision geoms on finger bodies only</p>
<div class="lead">{summary}</div>
<div class="legend">collision geoms coloured by type: {legend}<span>· one gripper framed per robot (bimanual robots: the first)</span></div>
<div class="filters" id="filters"><button class="on" data-f="">all</button><button data-f="box">has box</button><button data-f="capsule">has capsule</button><button data-f="sphere">has sphere</button><button data-f="mesh">has mesh</button><button data-f="cylinder">has cylinder</button></div>
<div class="grid" id="grid">{cards}</div>
<details><summary>Files that do not compile alone (include fragments: actuator / keyframe snippets)</summary><ul>{errors}</ul></details>
<script>
document.getElementById('grid').addEventListener('click',e=>{{if(e.target.tagName==='IMG')e.target.classList.toggle('big')}});
document.getElementById('filters').addEventListener('click',e=>{{const b=e.target.closest('button');if(!b)return;
document.querySelectorAll('#filters button').forEach(x=>x.classList.toggle('on',x===b));const f=b.dataset.f;
document.querySelectorAll('#grid .card').forEach(c=>{{c.style.display=!f||c.dataset.types.split(' ').includes(f)?'':'none'}});}});
</script>
</main></body></html>"""

if __name__ == "__main__":
    main()
