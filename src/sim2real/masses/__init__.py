"""bam_fb_v2's MEASURED masses for sim2real's twin: a byte copy of the mass-overrides file its description names, and the one rule that
applies it. The twin loads these by default; ``masses="cad"`` is the explicit opt-out (bam_ws PEP 0060 addendum).

The description owns the pointer: bam_ws ``bam_cad_descriptions/descriptions/bam_fb_v2.py`` ``MEASURED_MASSES`` (``VersionedDescription.
measured_masses``) names ``bam_pid_tunning/data/bam_fb_v2_masses_2026-11-15c.json`` (schema ``bam-description/mass-overrides/1``: PID tuna's
fit, the shoulder confirmed by the 29 J1 rests of rackq 20ad + r1a). The bundle's inertials stay as exported; this file goes over them.

WHY a copy (PEP 0056's reason for the named-pose copy beside this one): sim2real imports nothing of bam_ws at runtime, and the bam_ws
checkout its paths default to is not kept at origin/main (on 2026-11-17 it predates the 15c file and PEP 0060). ``SOURCE`` says what was
copied; ``check`` compares the copy with the file the description names in a bam_ws checkout that has the pointer (tests/test_masses.py),
and ``python -m sim2real.masses --write --bam-ws <checkout>`` refreshes it after the description moves.

WHY sim2real's own ``apply`` and not an import of ``bam_pid_tunning.plants.mass_file.apply_mass_file`` (the rule's owner): the same reason;
tests/test_masses.py holds the two equal body by body on the bundle's MJCF whenever bam_ws' copy is importable.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
BAM_FB_V2 = HERE / "bam_fb_v2.json"
SCHEMA = "bam-description/mass-overrides/1"
# the twin's mass sources: "measured" (this file over the bundle's inertials, the default) or "cad" (the bundle's as exported: an opt-out)
MASSES = ("measured", "cad")
DEFAULT = "measured"
SOURCE = {"description": "bam_fb_v2", "pointer": "bam_cad_descriptions/descriptions/bam_fb_v2.py MEASURED_MASSES",
          "path": "src/core/mdp/setup/bam_pid_tunning/data/bam_fb_v2_masses_2026-11-15c.json", "bam_ws_sha": "a4a9ba3e4",
          "sha256": "54b01e8c512e56561dc29478d981a253f130ecf2aef425ac0192694b3c011e7d"}
RECORD = Path("src/dev/bam_cad_descriptions/bam_cad_descriptions/descriptions/bam_fb_v2.py")


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def apply(model, path: str | Path = BAM_FB_V2) -> dict:
    """Write the file's masses / COMs into a MuJoCo ``model`` in place (``apply_mass_file``'s rule: each subtree scale first - every body
    at and below that joint's body, mass and inertia, COMs kept - then each body's mass and COM, its inertia scaled with its mass).
    The caller runs ``mj_setConst`` after. Returns {body: {"mass_kg": (before, after), "com_m": (before, after)}}."""

    data = json.loads(Path(path).read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{path}: not a {SCHEMA} file")
    report: dict = {}
    for joint, spec in (data.get("subtree_mass_scale") or {}).items():
        root = int(model.jnt_bodyid[model.joint(joint).id])
        scale = float(spec["scale"])
        for body in range(model.nbody):
            parent = body
            while parent > 0 and parent != root:
                parent = int(model.body_parentid[parent])
            if parent == root:
                before = float(model.body_mass[body])
                model.body_mass[body] *= scale
                model.body_inertia[body] *= scale
                report[model.body(body).name] = {"mass_kg": (before, float(model.body_mass[body]))}
    for name, spec in (data.get("bodies") or {}).items():
        body = model.body(name).id
        before_mass, before_com = float(model.body_mass[body]), [float(v) for v in model.body_ipos[body]]
        mass = float(spec["mass_kg"])
        if before_mass > 0:
            model.body_inertia[body] *= mass / before_mass
        model.body_mass[body] = mass
        model.body_ipos[body] = [float(v) for v in spec["com_m"]]
        report[name] = {"mass_kg": (before_mass, mass), "com_m": (before_com, [float(v) for v in spec["com_m"]])}
    return report


def described_path(bam_ws: str | Path) -> str | None:
    """The mass file bam_fb_v2's description names in a bam_ws checkout (its record's ``MeasuredMasses(path=...)``, read with ``ast``,
    never imported); None when that checkout predates PEP 0060."""

    record = Path(bam_ws) / RECORD
    if not record.is_file():
        return None
    for node in ast.walk(ast.parse(record.read_text())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "MeasuredMasses":
            for keyword in node.keywords:
                if keyword.arg == "path" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
    return None


def check(bam_ws: str | Path) -> dict:
    """The copy against the description in ``bam_ws``: {"status": "same" | "differs" | "no pointer", ...}."""

    named = described_path(bam_ws)
    if named is None:
        return {"status": "no pointer", "bam_ws": str(bam_ws), "why": "this bam_ws checkout predates PEP 0060 (no MeasuredMasses in its record)"}
    source = Path(bam_ws) / named
    same = named == SOURCE["path"] and source.is_file() and sha256(source) == sha256(BAM_FB_V2) == SOURCE["sha256"]
    return {"status": "same" if same else "differs", "bam_ws": str(bam_ws), "named": named, "copied": SOURCE["path"],
            "named_sha256": sha256(source) if source.is_file() else None, "copy_sha256": sha256(BAM_FB_V2)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="sim2real's copy of bam_fb_v2's measured masses against its description")
    parser.add_argument("--bam-ws", type=Path, required=True, help="a bam_ws checkout at the commit to copy from (origin/main)")
    parser.add_argument("--write", action="store_true", help="copy the file the description names over sim2real's (then edit SOURCE)")
    args = parser.parse_args(argv)
    named = described_path(args.bam_ws)
    if args.write:
        if named is None:
            raise SystemExit(f"{args.bam_ws}: no MeasuredMasses pointer in {RECORD}")
        shutil.copyfile(args.bam_ws / named, BAM_FB_V2)
        print(f"copied {named} (sha256 {sha256(BAM_FB_V2)}): set SOURCE's path, bam_ws_sha and sha256 to match")
        return 0
    result = check(args.bam_ws)
    print(json.dumps(result, indent=1))
    return 0 if result["status"] == "same" else 1


if __name__ == "__main__":
    raise SystemExit(main())
