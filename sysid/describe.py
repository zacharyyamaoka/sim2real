"""Parse a robot description (a URDF/MJCF and a small manifest) into typed components, nominal values and a model.

A manifest (sysid/examples/<id>/description.json, schema sysid.description/1) names the model file (or how to compose one from
several: parts attached in frames, a body, cameras), the components with the description's word for their type, the sensors,
every nominal value and where it comes from, the configuration identification does not touch, and the schedule's knobs.

Nominal values are read from where the description states them, never copied: "mjcf:<kind>:<name>:<field>[:<index>]" reads the
compiled model (a joint's armature, a body's mass, an equality's data, an actuator's gain), "camera:<name>:fx|fy|cx|cy" the
pinhole a MuJoCo fovy camera is (bam_scan_tunnel PinholeCamera.from_mujoco's convention: square pixels, centre at W/2, H/2), and
"bam_rack_twin:describe_station:<field>" the joint description bam_rack_twin builds CAN 11's schedule from.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np

from . import EXAMPLES_DIR, REPO
from . import cards


@dataclass(frozen=True)
class Nominal:
    key: str
    value: float | None
    unit: str
    source: str
    note: str = ""


@dataclass(frozen=True)
class Component:
    id: str
    title: str
    word: str
    type: cards.TypeRef
    parent: str | None
    binds: dict


@dataclass(frozen=True)
class Camera:
    name: str
    pos: tuple
    xyaxes: tuple
    fovy_deg: float
    resolution: tuple
    source: str = ""

    @property
    def fy(self) -> float:
        return (self.resolution[1] / 2.0) / math.tan(math.radians(self.fovy_deg) / 2.0)

    @property
    def fx(self) -> float:
        return self.fy  # a MuJoCo fovy camera has square pixels

    @property
    def cx(self) -> float:
        return self.resolution[0] / 2.0

    @property
    def cy(self) -> float:
        return self.resolution[1] / 2.0


def resolve_path(text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else REPO / path


def quat_from_rpy(roll: float, pitch: float, yaw: float) -> list[float]:
    """MuJoCo (w, x, y, z) of R = Rz(yaw) Ry(pitch) Rx(roll)."""
    cr, sr, cp, sp, cy, sy = (math.cos(roll / 2), math.sin(roll / 2), math.cos(pitch / 2), math.sin(pitch / 2), math.cos(yaw / 2), math.sin(yaw / 2))
    return [cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy]


def look_xyaxes(pos, target, up_hint=(0.0, 0.0, 1.0)) -> tuple:
    """A MuJoCo camera's xyaxes looking from `pos` at `target`: the camera looks along -z, +y is image up."""
    forward = np.asarray(target, float) - np.asarray(pos, float)
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.asarray(up_hint, float))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return tuple(float(v) for v in (*right, *up))


@dataclass
class Description:
    id: str
    path: Path
    manifest: dict
    components: list[Component]
    cameras: dict[str, Camera] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.manifest["title"]

    @property
    def known(self) -> dict:
        return self.manifest.get("known", {})

    @property
    def schedule(self) -> dict:
        return self.manifest.get("schedule", {})

    @property
    def monitoring(self) -> dict:
        return self.manifest.get("monitoring", {})

    # -- the model -----------------------------------------------------------------------------------------------------------------

    def spec(self):
        """A fresh MjSpec of the description's model (composed when the manifest says so)."""
        import mujoco  # noqa: PLC0415

        model = self.manifest["model"]
        if model["format"] == "mjcf":
            spec = mujoco.MjSpec.from_file(str(resolve_path(model["path"])))
            for attach in model.get("attach", ()):
                child = mujoco.MjSpec.from_file(str(resolve_path(attach["path"])))
                _quiet_options(spec, child)
                spec.site(attach["site"]).attach_body(child.body(attach["body"]), attach["prefix"], "")
            return spec
        if model["format"] != "mjcf-composed":
            raise ValueError(f"{self.id}: model format {model['format']!r} is not mjcf or mjcf-composed")
        spec = mujoco.MjSpec()
        spec.modelname = self.id
        spec.option.timestep = 0.002
        spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
        spec.option.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_CONTACT)
        for part in model.get("parts", ()):
            child = mujoco.MjSpec.from_file(str(resolve_path(part["path"])))
            for attach in part.get("attach", ()):
                grandchild = mujoco.MjSpec.from_file(str(resolve_path(attach["path"])))
                _quiet_options(child, grandchild)
                child.site(attach["site"]).attach_body(grandchild.body(attach["body"]), attach["prefix"], "")
            _quiet_options(spec, child)
            frame = spec.worldbody.add_frame(pos=list(part["pos"]), quat=quat_from_rpy(*part["rpy"]))
            frame.attach_body(child.worldbody.first_body(), part["prefix"], "")
        for body in model.get("bodies", ()):
            added = spec.worldbody.add_body(name=body["name"], pos=list(body["pos"]))
            added.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=list(body["box"]), rgba=[0.55, 0.57, 0.6, 1.0], mass=20.0)
        for camera in self.cameras.values():
            spec.worldbody.add_camera(name=camera.name, pos=list(camera.pos), xyaxes=list(camera.xyaxes), fovy=camera.fovy_deg)
        return spec

    @cached_property
    def model(self):
        """The compiled nominal model (contacts off: no example calibrates contact)."""
        import mujoco  # noqa: PLC0415

        model = self.spec().compile()
        model.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_CONTACT)
        return model

    # -- nominal values ------------------------------------------------------------------------------------------------------------

    @cached_property
    def nominal(self) -> dict[str, Nominal]:
        out = {}
        for key, entry in self.manifest.get("parameters", {}).items():
            if "from" in entry:
                value, source = self._resolve(entry["from"])
                value = None if value is None else float(value) * float(entry.get("scale", 1.0))
            else:
                value, source = entry.get("value"), entry.get("source", "the manifest")
            out[key] = Nominal(key, value, entry.get("unit", ""), source, entry.get("note", ""))
        return out

    def _resolve(self, ref: str) -> tuple[float | None, str]:
        kind, *rest = ref.split(":")
        if kind == "mjcf":
            what, name, attribute, *index = rest
            view = {"joint": self.model.joint, "body": self.model.body, "site": self.model.site, "actuator": self.model.actuator,
                    "equality": self.model.equality}[what](name)
            value = np.atleast_1d(getattr(view, attribute))[int(index[0]) if index else 0]
            return float(value), f"{Path(self.manifest['model'].get('path', self.id)).name} {what} {name} {attribute}{'[' + index[0] + ']' if index else ''}"
        if kind == "camera":
            name, attribute = rest
            camera = self.cameras[name]
            return float(getattr(camera, attribute)), f"camera {name}: fovy {camera.fovy_deg:g} deg at {camera.resolution[0]} x {camera.resolution[1]} ({attribute})"
        if kind == "bam_rack_twin":
            what, attribute = rest
            if what != "describe_station":
                raise ValueError(ref)
            return float(getattr(self.station_description, attribute)), f"bam_rack_twin.schedule.describe_station({self.manifest['record']['station']}).{attribute}"
        raise ValueError(f"{self.id}: cannot resolve the nominal reference {ref!r}")

    @cached_property
    def station_description(self):
        """CAN 11's joint description as bam_rack_twin builds the station's schedule from it (its twin of record's gravity and
        inertia, the model card's Coulomb, the board's gains)."""
        from bam_rack_twin import schedule  # noqa: PLC0415

        station = self.manifest["record"]["station"]
        _, twin = schedule.record_twin(station)
        return schedule.describe_station(station, twin=twin)

    # -- the typed tree ------------------------------------------------------------------------------------------------------------

    def tree(self) -> list[dict]:
        """Components depth first, each with its type card (or adapter type) and the nominal parameters it owns."""
        children: dict[str | None, list[Component]] = {}
        for c in self.components:
            children.setdefault(c.parent, []).append(c)
        owned: dict[str, list[str]] = {}
        for key in self.nominal:
            owned.setdefault(key.split(".")[0], []).append(key)
        rows = []

        def walk(parent, depth):
            for c in children.get(parent, []):
                rows.append({"id": c.id, "title": c.title, "word": c.word, "type": c.type.id, "type_title": c.type.title, "group": c.type.group,
                             "type_source": c.type.source, "parent": c.parent, "depth": depth, "binds": c.binds,
                             "parameters": owned.get(c.id, []) + [k for p, ks in owned.items() if p != c.id and _owner(self, p) == c.id for k in ks]})
                walk(c.id, depth + 1)

        walk(None, 0)
        return rows

    def model_sha256(self) -> str | None:
        model = self.manifest["model"]
        if model["format"] != "mjcf":
            return None
        return hashlib.sha256(resolve_path(model["path"]).read_bytes()).hexdigest()


# Parameter prefixes that are not component ids name what owns them
OWNER = {"belt": "conveyor", "hsi": "hsi_line", "left_mount": "left_arm", "right_mount": "right_arm"}


def _owner(description: Description, prefix: str) -> str | None:
    ids = {c.id for c in description.components}
    if prefix in ids:
        return None
    if prefix in OWNER:
        return OWNER[prefix]
    joint_owner = {c.binds.get("joint", "").removesuffix("_joint"): c.id for c in description.components if c.binds.get("joint")}
    return joint_owner.get(prefix)


def _quiet_options(parent, child) -> None:
    """Copy the child's solver options onto the parent so MjSpec.attach has no conflict to warn about (bam_arm.cell sets them on both)."""
    parent.option.impratio = max(parent.option.impratio, child.option.impratio)
    child.option.impratio = parent.option.impratio
    child.option.cone = parent.option.cone = max(int(parent.option.cone), int(child.option.cone))


def load(example: str) -> Description:
    path = EXAMPLES_DIR / example / "description.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "sysid.description/1":
        raise ValueError(f"{path}: schema {manifest.get('schema')!r} is not sysid.description/1")
    components = [Component(c["id"], c["title"], c["type"], cards.card_for(c["type"]), c.get("parent"), dict(c.get("binds", {})))
                  for c in manifest["components"]]
    ids = [c.id for c in components]
    if len(set(ids)) != len(ids) or any(c.parent not in (None, *ids) for c in components):
        raise ValueError(f"{example}: component ids must be unique and every parent a component")
    cameras = {}
    for cam in manifest["model"].get("cameras", ()):
        cameras[cam["name"]] = Camera(cam["name"], tuple(cam["pos"]), look_xyaxes(cam["pos"], cam["look_at"], cam.get("up_hint", (0.0, 0.0, 1.0))),
                                      float(cam["fovy_deg"]), tuple(cam["resolution"]), cam.get("source", ""))
    description = Description(example, path, manifest, components, cameras)
    model_path = manifest["model"].get("path")
    if model_path and manifest["model"].get("sha256"):
        digest = hashlib.sha256(resolve_path(model_path).read_bytes()).hexdigest()
        if digest != manifest["model"]["sha256"]:
            raise ValueError(f"{example}: {model_path} is not the file the description names (sha256 {digest[:12]}, expected {manifest['model']['sha256'][:12]})")
    return description


def check_binds(description: Description) -> list[str]:
    """Every bind a component names exists in the compiled model (joints, bodies, sites, actuators, cameras, equalities)."""
    model = description.model
    problems = []
    finders = {"joint": model.joint, "actuator": model.actuator, "camera": model.camera, "equality": model.equality,
               "base_body": model.body, "marker_body": model.body, "body": model.body, "observes": model.body,
               "flange_site": model.site, "tcp_site": model.site, "site": model.site}
    for c in description.components:
        for kind, name in c.binds.items():
            finder = finders.get(kind)
            if finder is None or not isinstance(name, str):
                continue
            try:
                finder(name)
            except KeyError:
                problems.append(f"{c.id}: {kind} {name!r} is not in the model")
    return problems
