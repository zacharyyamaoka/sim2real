"""The media as components scoped to an entity: the link in 3D (a joint), the camera's clip (a camera), MuJoCo's render of the link (a
joint), and the words that say what you are looking at (any entity). A page drops them in per entity level.

The coordinator, 2026-11-07, for the run page's next redesign ("an entity tree on the left (deployment -> sub-parts, like RobotDx's device
tree); the standard dashboard for the selected level on the right"): "build your 3D view, the video and the 'what you're looking at' text as
components scoped to an entity (a joint, a camera, an arm). A page should be able to drop them in per entity level. Don't hard-wire them
into one flat page."

A component is a data-ui `.base` fragment (its datasets, views, panels and dataset links) whose every dataset is a run's
(`{deployment}`, `{run}`) and filtered to its entity (`{station}` / `{device}` for a joint, `{camera}` for a camera). Its entity comes from
the page's record or, when it is mounted alone, from its `.base` URL's query (static/sim2real.js fills both):

    compose(page_doc, joint_3d(models))                        the run page's Playback (site/views.py)
    standalone(camera_clip())  -> views/components/camera-clip.base
    <div class="s2r-dash" data-src="/views/components/joint-3d.base?deployment=…&run=…&station=can12&device=CAN%2012&glb=…">

An arm is a joint chain: its 3D component is joint_3d with its links (the GLB's nodes, the links table's <link>_ columns) once a producer
writes them; today every deployment's entities are single joints and cameras. Stdlib only; the media themselves are tools/build_media.py's.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from urllib.parse import urlencode

from catalog_workbench.html import e

# WHY relative: the run page's own datasets are written so (tools/build_pages.py), and site/views.py roots every data/ path at /data/
SAMPLES = "data/{deployment}/runs/{run}/samples.json"
POSES = "data/{deployment}/runs/{run}/poses.json"
LINKS = "/media/{deployment}/runs/{run}/links.json"
CLIPS = "/media/{deployment}/runs/{run}/media.json"
THREE_D = "Output link · 3D in its joint frame"
CAMERA = "Camera · real"
RENDER = "Twin render · MuJoCo"


@dataclass(frozen=True)
class Entity:
    """What a component is scoped to: a joint (its device and station key), a camera (its serial), or a deployment."""

    kind: str  # "joint" | "camera" | "deployment"
    id: str  # the joint's device ("CAN 12"), the camera's serial, the deployment's id
    deployment: str
    station: str = ""  # a joint's station key ("can12"): its frame ({station}_joint) and its link model

    def fill(self, run: str = "", glb: str = "", device: str = "") -> dict:
        """The values a component's .base reads for this entity on one run (the query of a component mounted alone)."""
        values = {"deployment": self.deployment, "run": run}
        if self.kind == "joint":
            values.update(device=self.id, station=self.station, glb=glb)
        elif self.kind == "camera":
            values.update(camera=self.id, device=device)  # WHY device: a camera's clip plays on the run's clock, the joint it filmed
        return {k: v for k, v in values.items() if v}


@dataclass
class Fragment:
    """A component as `.base` parts. `replaces` names the page views it stands in for when composed (the page's own older card)."""

    name: str
    datasets: dict
    views: list
    panels: list
    links: list = field(default_factory=list)
    replaces: tuple = ()
    what: str = ""  # one line: what the component shows


def _and(a: str | None, b: str | None) -> str | None:
    """Both filters (one that already holds the other is kept alone)."""
    if not a or a == b or a in (b or ""):
        return b or a
    if not b or b in a:
        return a
    return f"({a}) && ({b})"


def compose(doc: dict, fragment: Fragment, before: str | None = None, after: str | None = None) -> dict:
    """The page's doc with the component in it: its datasets (a dataset the page already has must read the same file; the two filters
    are both kept), its views (in place of any it replaces), its panels (where a replaced view's panel was, else right after the panel
    of view `after` or before the panel of view `before`, else at the end) and its dataset links."""
    doc = copy.deepcopy(doc)
    for name, ds in fragment.datasets.items():
        mine = doc.setdefault("datasets", {}).get(name)
        if mine is None:
            doc["datasets"][name] = copy.deepcopy(ds)
            continue
        if mine.get("data") != ds.get("data"):
            raise ValueError(f"{fragment.name}: dataset {name!r} reads {ds.get('data')}, the page's reads {mine.get('data')}")
        mine["filters"] = _and(mine.get("filters"), ds.get("filters"))
    gone = set(fragment.replaces) | {v["name"] for v in fragment.views}
    doc["views"] = [v for v in doc.get("views", []) if v["name"] not in gone] + copy.deepcopy(fragment.views)
    panels = doc["layout"]["panels"]
    at = next((i for i, p in enumerate(panels) if p.get("view") in gone), None)
    kept = [p for p in panels if p.get("view") not in gone]
    if at is None and after:
        at = next((i + 1 for i, p in enumerate(kept) if p.get("view") == after), len(kept))
    elif at is None:
        at = next((i for i, p in enumerate(kept) if before and p.get("view") == before), len(kept))
    else:
        at = sum(1 for p in panels[:at] if p.get("view") not in gone)
    doc["layout"]["panels"] = kept[:at] + copy.deepcopy(fragment.panels) + kept[at:]
    have = {(l["from"], l["to"]) for l in doc.get("links", [])}
    for link in fragment.links:
        if (link["from"], link["to"]) not in have and link["from"].split(".")[0] in doc["datasets"] and link["to"].split(".")[0] in doc["datasets"]:
            doc.setdefault("links", []).append(dict(link))
    return doc


def standalone(fragment: Fragment, style: dict | None = None) -> dict:
    """The component as a dashboard of its own: its entity's samples as the clock (the run's t), a playback bar, then the component.
    WHY its own clock: mounted alone at an entity level, it plays without the run page around it."""
    doc = {"data": SAMPLES, "properties": {"situation": {"displayName": "Situation"}, "source": {"displayName": "Family"}},
           "style": copy.deepcopy(style or {"chrome": "minimal"}), "clock": {"data": "samples", "time": "t"},
           "datasets": {"samples": {"data": SAMPLES, "label": "Samples", "filters": 'device == "{device}"'}},
           "layout": {"panels": [{"view": "Playback", "w": 12}]},
           "views": [{"type": "playback", "name": "Playback", "playback": {"speeds": [0.25, 0.5, 1, 2, 4], "readout": True}}]}
    return compose(doc, fragment)


# --- the components ---------------------------------------------------------------------------------------------------------------

def joint_3d(models: list[str] | None = None) -> Fragment:
    """A joint's output link in 3D (data-ui trajectory3d): the 100 mm marker's paths over the whole run and the station's link model ({glb})
    posed per series at the clock's t, real solid, every model translucent, the command a ghost; the joint frame's y up (the twins' gravity
    is their -y). WHY (Zach, 2026-11-07: "we can basically always have a 3D view ... remember in traj compare we had ... the 3D models")."""
    models = models or []
    view = {"type": "trajectory3d", "name": THREE_D, "from": "poses",
            "trajectory3d": {"series": "situation", "family": "source", "unit": "mm", "show": "all", "projection": "perspective", "axes": "auto",
                             "density": 20, "up": "y",
                             "robots": {"data": "links", "model": "{glb}", "links": ["link"],
                                        "series": {"target": {"color": "muted", "opacity": 0.25}, **{m: {"opacity": 0.3} for m in models}}}}}
    text = ("### The link in 3D\nThe station's output link posed at each series' angle at the clock's t: **real** solid blue in front, each **model** "
            "translucent orange 2 mm behind the one before, the **command** a grey ghost last (stacked along the axis so equal angles never hide each "
            "other); the paths are the 100 mm marker's over the whole run, the command's dashed. Drag to orbit, scrub the playback to move them. The "
            "link is drawn from its twin's numbers (the disc, the marker, the twin's gravity load), not CAD.")
    return Fragment(
        name="joint-3d",
        datasets={"poses": {"data": POSES, "label": "Poses", "filters": 'body == "marker_100mm" && frame == "{station}_joint"'},
                  "links": {"data": LINKS, "label": "Link poses", "filters": 'device == "{device}"'}},
        views=[view], panels=[{"text": text, "w": 12}, {"view": THREE_D, "w": 7, "h": 5}],
        links=[{"from": "poses.situation", "to": "samples.situation"}, {"from": "links.situation", "to": "samples.situation"}],
        replaces=(THREE_D,),
        what="the joint's output link in 3D, real, the command and every model posed at the clock's t")


def camera_clip() -> Fragment:
    """A camera's clip of one run (data-ui video on the clock): the D405 that watched it, cut from its session's recording onto the run's
    clock, the station's tag boxed. Real footage."""
    return Fragment(
        name="camera-clip",
        datasets={"media": {"data": CLIPS, "label": "Clips", "filters": 'camera == "{camera}"'}},
        views=[{"type": "video", "name": CAMERA, "from": "media", "filters": 'basis == "real-camera"', "empty": "No camera clip for this run.",
                "video": {"src": "src", "label": "label"}}],
        panels=[{"view": CAMERA, "w": 6, "h": 4}],
        what="the camera's clip of the run, on the run's clock")


def joint_render() -> Fragment:
    """MuJoCo's render of a joint's link on the same frames as the camera's clip: real at its encoder angle, every model at its replayed
    angle, the command a ghost. WHY beside the clip and never over it: the render is the joint's own frame, not the camera's pinhole."""
    return Fragment(
        name="joint-render",
        datasets={"renders": {"data": CLIPS, "label": "Renders", "filters": 'device == "{device}"'}},
        views=[{"type": "video", "name": RENDER, "from": "renders", "filters": 'basis == "sim-render"', "empty": "No render for this run.",
                "video": {"src": "src", "label": "label"}}],
        panels=[{"view": RENDER, "w": 6, "h": 4}],
        what="MuJoCo's render of the joint's link on the clip's frames")


CLIPS_TEXT = {"text": "### Camera and twin, one clock\nLeft: the D405 that watches this station, cut from its session's recording onto this run's "
                      "clock (the whole view, brightened, the station's tag boxed in blue). Right: MuJoCo's render of the station's link on the same "
                      "frames, real at its encoder angle (blue), every model at its replayed angle (orange), the command a grey ghost. Both follow "
                      "the playback and every plot below.", "w": 12}


def clips_pair() -> Fragment:
    """The camera's clip and the joint's render side by side, with their line: the run page's pair (two components, one panel row)."""
    cam, ren = camera_clip(), joint_render()
    return Fragment(name="clips-pair", datasets={**cam.datasets, **ren.datasets}, views=cam.views + ren.views,
                    panels=[CLIPS_TEXT] + cam.panels + ren.panels, what="the camera's clip beside the twin's render")


COMPONENTS = {"joint-3d": joint_3d, "camera-clip": camera_clip, "joint-render": joint_render}


# --- what you are looking at, per entity ------------------------------------------------------------------------------------------

def what_joint(row: dict, media) -> str:
    """A joint's run in words: its motion, every series by name and colour, what its 3D card shows (plain text)."""
    models = [s for s in row.get("situations", []) if s not in ("real", "target")]
    against = []
    if "target" in row.get("situations", []):
        against.append("its command (grey, dashed)")
    if models:
        against.append(f"{len(models)} model{'s' if len(models) != 1 else ''} replaying the same command (orange): " + ", ".join(models))
    versus = (" against " + " and ".join(against)) if against else ", with no command or model to compare"
    return (f"{row['device']} ran {row.get('kind') or 'a run'} for {row.get('duration_s') or 0:.3g} s on the rack: the real joint (blue){versus}.")


def what_camera(row: dict, media) -> str:
    """A run's camera in words: what it filmed and the render beside it, or why there is no video (plain text)."""
    models = [s for s in row.get("situations", []) if s not in ("real", "target")]
    if media and media.clips(row["run"]):
        return ("Below the playback, the camera clip of this run (the D405 that watches the station, its tag boxed in blue where the camera found it) "
                "beside MuJoCo's render of the station's link at the same instants (real at its encoder angle"
                + (", each model at its replayed angle" if models else "") + "), both on the plots' clock; then the link in 3D, posed at each one's angle.")
    entry = (media.runs.get(row["run"]) if media else None) or {}
    if media:
        return "The 3D card poses the station's link at each one's angle on the plots' clock. No video: " + (entry.get("why_none") or "this run has none") + "."
    return "The 3D card draws the 100 mm marker's path at each one's angle on the plots' clock."


def what_html(*texts: str) -> str:
    """One "what you're looking at" paragraph from the entities' lines (a page with a joint and its camera says both, in that order)."""
    return f'<p class="s2r-what"><b>What you\'re looking at:</b> {e(" ".join(t for t in texts if t))}</p>'


def entities_of(row: dict, media) -> list[Entity]:
    """A run's entities: its joint, and the camera that filmed it when it has a clip (the levels a page can drop components in at)."""
    from adapter import station_key  # noqa: PLC0415

    out = [Entity("joint", row["device"], row["deployment"], station_key(row["device"]))]
    entry = (media.runs.get(row["run"]) if media else None) or {}
    if entry.get("media") and entry.get("camera"):
        out.append(Entity("camera", entry["camera"], row["deployment"]))
    return out


def mount_url(name: str, entity: Entity, run: str, glb: str = "", device: str = "") -> str:
    """The component's .base for one entity on one run: its entity in the URL's query (static/sim2real.js fills the .base from it)."""
    return f"/views/components/{name}.base?{urlencode(entity.fill(run=run, glb=glb, device=device))}"


def mount(name: str, entity: Entity, run: str, glb: str = "", device: str = "", label: str = "") -> str:
    """A component mounted alone for one entity on one run: a placeholder static/sim2real.js turns into a dashboard."""
    return (f'<div class="s2r-dash s2r-component" data-component="{e(name)}" data-src="{e(mount_url(name, entity, run, glb, device))}" '
            f'aria-label="{e(label or name)}"><noscript><p>This component is a data-ui dashboard; it needs JavaScript.</p></noscript></div>')
