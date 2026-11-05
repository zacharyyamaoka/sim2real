"""sysid's adapter over the type cards (type_cards, contract sim2real.type_cards/2): typing, ladders, placement and drift.

`from type_cards import registry as reg` is the one import (type_cards/CONTRACT.md). Since main 4a8de23 every card sysid uses has
its own ladder and drift diagnostic, so `ladder(card)` and `check_drift(card, ...)` are the cards' own; this module adds only what
the cards do not carry, listed in the report and never written into type_cards/ (lane A's write set):

- **words** a description uses that `reg.card_for` does not resolve (bam_rack_twin's `moteus_servo`, UR's `ur5e`, a D405);
- **two component types with no card**, the gripper and the tool an arm carries (their parameters live on arm_6dof_gripper and
  arm_6dof: `place` says where), and two structural nodes (a deployment, a mount);
- **placement**: which card, rung and card parameter each identified value is (`place`). Rung keys are never parsed (CONTRACT.md):
  the table names them, and `rungs_in_order` orders by the card's own ladder.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from type_cards import registry as reg

STRUCTURAL = {"deployment": "Deployment", "mount": "Mount"}
# WHY words here and not reg.ALIASES: ALIASES is lane A's; these are the description words the examples use that it does not hold
WORDS = {"moteus_servo": "servo", "ur5e": "arm_6dof", "d405": "camera_rgbd"}


@dataclass(frozen=True)
class AdapterCard:
    """A component type with no type card yet: enough to type a component (proposed for lane A)."""
    id: str
    title: str
    group: str
    note: str
    words: tuple[str, ...] = ()


ADAPTER_CARDS = {
    "gripper": AdapterCard("gripper", "Gripper", "actuator",
                           "no card yet (arm_6dof_gripper names 'RobotDx part type gripper (no card yet)' as its member); its drive sits on "
                           "arm_6dof_gripper's M1 finger_width_map", ("gripper", "parallel gripper", "2f-85")),
    "tool": AdapterCard("tool", "Tool (payload + TCP)", "actuator",
                        "no card: the tool an arm carries is arm_6dof's M3 link_inertials and arm_6dof_gripper's M0 tcp_offset",
                        ("tool", "payload", "end effector")),
}


@dataclass(frozen=True)
class TypeRef:
    id: str
    title: str
    group: str
    source: str  # "type_cards" | "sysid adapter (no card yet)" | "structural"
    word: str


def card_for(word: str) -> TypeRef:
    """The type a description's word names: a type card first (reg.card_for), then this adapter's words, types and structure."""
    w = word.strip().lower()
    hit = reg.card_for(word) or (reg.CARDS.get(WORDS[w]) if w in WORDS else None)
    if hit is not None:
        return TypeRef(hit.id, hit.title, hit.group, "type_cards", word)
    for card in ADAPTER_CARDS.values():
        if w == card.id or w in card.words:
            return TypeRef(card.id, card.title, card.group, "sysid adapter (no card yet)", word)
    if w in STRUCTURAL:
        return TypeRef(w, STRUCTURAL[w], "structure", "structural", word)
    raise KeyError(f"no type card or adapter type for the description word {word!r}")


# --- placement: which card, rung and card parameter each identified value is -------------------------------------------------

# (example pattern, parameter-key pattern) -> (card, rung key, the card's parameter). First match wins.
PLACE = (
    ("pendulum_can11", "can11.gravity_nm", ("servo", "M0", "gravity_nm")),
    ("pendulum_can11", "can11.gravity_bottom_rad", ("servo", "M0", "gravity_nm (its bottom)")),
    ("pendulum_can11", "can11.armature_kg_m2", ("servo", "M0", "armature_kg_m2")),
    ("pendulum_can11", "can11.frictionloss_nm", ("servo", "M2", "frictionloss_nm")),
    ("pendulum_can11", "can11.damping_nm_s_rad", ("servo", "M2", "damping_nm_s_rad")),
    ("pendulum_can11", "can11.friction_stribeck_drop_nm", ("servo", "M3", "friction_stribeck_drop_nm")),
    ("pendulum_can11", "can11.friction_stribeck_speed_rad_s", ("servo", "M3", "friction_stribeck_drop_nm (its speed)")),
    ("pendulum_can11", "can11.backlash_rad", ("servo", "M4", "backlash_rad")),
    ("pendulum_can11", "can11.backlash_wear_rad_per_h", ("servo", "M5.wear", "backlash_wear_rad_per_nm_rev (per hour at the check's duty)")),
    ("ur5e*", "*.zero_offset_rad", ("arm_6dof", "M1", "joint_zero_offsets")),
    ("ur5e*", "*.armature_kg_m2", ("servo", "M0", "armature_kg_m2 (each joint is a servo)")),
    ("ur5e*", "*.damping_nm_s_rad", ("servo", "M2", "damping_nm_s_rad (each joint is a servo)")),
    ("ur5e*", "*.frictionloss_nm", ("servo", "M2", "frictionloss_nm (each joint is a servo)")),
    ("ur5e_2f85", "tool.mass_kg", ("arm_6dof", "M3", "link_inertials (the tool)")),
    ("ur5e_2f85", "tool.com_z_m", ("arm_6dof", "M3", "link_inertials (the tool)")),
    ("ur5e_2f85", "tool.tcp_*", ("arm_6dof_gripper", "M0", "tcp_offset")),
    ("ur5e_2f85", "gripper.*", ("arm_6dof_gripper", "M1", "finger_width_map (the drive that sets it)")),
    ("conveyor", "belt.roller_radius_m", ("conveyor", "M0", "drum_radius_m")),
    ("conveyor", "belt.moving_mass_kg", ("conveyor", "M0", "moving_mass_kg")),
    ("conveyor", "belt.viscous_drag_n_s_m", ("conveyor", "M2", "viscous_n_s_m")),
    ("conveyor", "belt.coulomb_drag_n", ("conveyor", "M2", "coulomb_n")),
    ("dual_arm_cell", "*_mount.*", ("arm_6dof", "M0", "base_frame")),
    ("dual_arm_cell", "head_camera.f?_px", ("camera_rgb", "M0", "fx_fy")),
    ("dual_arm_cell", "head_camera.c?_px", ("camera_rgb", "M0", "cx_cy")),
    ("dual_arm_cell", "head_camera.*", ("camera_rgb", "M0", "extrinsics")),
    ("linescan_cell", "hsi.gain_b*", ("camera_hsi", "M0", "dark_white_refs (white)")),
    ("linescan_cell", "hsi.dark_b*", ("camera_hsi", "M0", "dark_white_refs (dark)")),
    ("linescan_cell", "hsi.*", ("camera_hsi", "M3", "line_geometry")),
    ("linescan_cell", "rgbd.f?_px", ("camera_rgb", "M0", "fx_fy (the D435's colour stream)")),
    ("linescan_cell", "rgbd.c?_px", ("camera_rgb", "M0", "cx_cy (the D435's colour stream)")),
    ("linescan_cell", "rgbd.depth_scale", ("camera_rgbd", "M0", "depth_scale")),
    ("linescan_cell", "rgbd.depth_offset_m", ("camera_rgbd", "M2", "depth_bias_coeffs (its constant term)")),
    ("linescan_cell", "rgbd.*", ("camera_rgb", "M0", "extrinsics (the D435's colour stream)")),
)


def place(example: str, key: str) -> dict:
    for ex, pattern, (card, rung, parameter) in PLACE:
        if fnmatch.fnmatchcase(example, ex) and fnmatch.fnmatchcase(key, pattern):
            known = card in reg.CARDS and any(r.key == rung for r in reg.rungs(card))
            return {"card": card, "rung": rung, "parameter": parameter, "on_card": known}
    return {"card": None, "rung": None, "parameter": None, "on_card": False}


# --- ladders ---------------------------------------------------------------------------------------------------------------------

def ladder(card_id: str) -> tuple[tuple, str]:
    """(rungs lowest first, source): the card's own ladder."""
    if card_id in reg.CARDS and reg.rungs(card_id):
        return reg.rungs(card_id), "type_cards"
    return (), "no ladder (no type card)"


def rung_row(rung, card_id: str | None = None) -> dict:
    row = {"key": rung.key, "name": rung.name, "kind": rung.kind, "n_parameters": rung.n_parameters, "parameters": list(rung.parameter_names),
           "equation": rung.equation, "current": rung.current,
           "references": [{"title": r.title, "doi": r.doi, "url": r.url} for r in rung.references],
           "wear": [{"parameter": p.name, "usage": p.wear.usage, "unit": p.wear.unit, "law": p.wear.law, "rate": p.wear.rate} for p in rung.wear_parameters]}
    if card_id:
        row["card"] = card_id
        row["added"] = [p.name for p in reg.added(card_id, rung.key)]
    return row


def card_ladders(example: str, keys) -> list[dict]:
    """The ladder of every card the example's identified values sit on, each rung marked with the values placed on it."""
    by_card: dict[str, dict[str, list[str]]] = {}
    for key in keys:
        p = place(example, key)
        if p["card"]:
            by_card.setdefault(p["card"], {}).setdefault(p["rung"], []).append(key)
    out = []
    for card_id, rungs in by_card.items():
        lad, source = ladder(card_id)
        out.append({"card": card_id, "title": reg.CARDS[card_id].title if card_id in reg.CARDS else card_id, "source": source,
                    "rungs": [{**rung_row(r, card_id), "identified": rungs.get(r.key, [])} for r in lad]})
    return out


# --- drift --------------------------------------------------------------------------------------------------------------------------

def drift_diagnostic(card_id: str):
    return reg.drift_diagnostic(card_id)


def check_drift(card_id: str, live: float, calibrated: float, threshold: float | None = None, history=None):
    """The card's own drift check: DriftResult(status, ratio, threshold, message, remaining, unit)."""
    return reg.check_drift(card_id, live, calibrated, threshold, history)
