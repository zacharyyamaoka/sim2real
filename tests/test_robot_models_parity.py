"""sim2real's cards against robot_models' type ladders: the parity rule of robot_models PEP 0004 §8.2.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_robot_models_parity.py

WHY this file and nothing else (PEP 0004 decision 6): sim2real stays as it is and gains one additive test. The mapping is
sim2real's own table, kept here; robot_models and robotparts never read sim2real. The ladders are read LIVE through
`robot_models.ladder.ladders()` (robot-models is an editable path source in pyproject.toml), never through robot_models'
tests, so this checks the ladders robot_models ships, not its ruler's spec.

For every card rung, mapped to a robot_models rung:
  1. the mapped rung exists, at the card rung's level;
  2. the card rung's base (the physics rung before it, or a residual's named base) maps into the mapped rung's fallback();
  3. every card parameter is held: `ladder.resolve(name)` (canonical, alias or packed) lies in the mapped rung's holds(),
     or the name resolves in a type the rung composes and is held at the composed rung, or it is one of the type's
     deployment-only names; MOVED lists the one stated exception;
  4. a card parameter whose name is canonical carries the canonical SI unit (SAME_UNIT lists spellings that differ only in
     how they are written), or sits in UNITS with its factor to SI.
Every failure names the card, its rung, the mapped rung and the parameter.
"""

from __future__ import annotations

import pytest

# WHY importorskip: robot_models before PEP 0004 (0.1.0, the homing core only) has no `ladder` module; where sim2real
# resolves such a build this file skips instead of failing. A robot_models WITH ladders that lacks a mapped type or
# rung fails below, by name: that is the drift this test exists to catch.
ladder_core = pytest.importorskip(
    "robot_models.ladder",
    reason="robot_models has no ladder module (PEP 0004): the parity rule has no ladders to read",
)

from sim2real.cards import registry as reg  # noqa: E402

# --- sim2real's map onto robot_models (PEP 0004 §8.2's table) --------------------------------------------------------

# card id -> robot_models type
CARD_TYPES = {
    # WHY: sim2real's servo is a joint in one housing (motor, drive, reducer, encoder): PEP 0004 §5.2.
    "servo": "integrated_servo",
    # WHY: the bare motor (PEP 0004 §5.3).
    "motor": "bldc_motor",
    "gearbox": "gearbox",
    # WHY: a driver's parameters belong to foc_controller (PEP 0004 decision 4, §5.5).
    "driver": "foc_controller",
    "encoder": "encoder",
    # WHY both arms on one type: Zach, Nov 6 ("the 6 DOF robot arm is not a type"), PEP 0004 §0 flag 2; sim2real's own v3
    # already maps both cards to rigid_body_chain.
    "arm_subassembly": "rigid_body_chain",
    "arm_6dof": "rigid_body_chain",
    "arm_6dof_gripper": "gripper",
    "conveyor": "conveyor",
    "camera_rgb": "camera",
    # WHY depth_camera: robot_models' type id; its folder is sensors/rgbd, robotparts' rgbd_camera (PEP 0004 §4, Found.folder).
    "camera_rgbd": "depth_camera",
    # WHY its v3 id: the RGB camera already holds the category name `camera` (PEP 0004 §11.5).
    "camera_hsi": "hyperspectral_camera",
    "aruco_marker": "aruco_marker",
}

# card id -> {card rung key: robot_models rung key}. A card rung "M<k>.wear" maps to the type's wear variant at layer k.
RUNG_MAP = {
    "servo": {
        "M0": "M0.ideal",
        "M2": "M2.coulomb_viscous",
        # WHY weakening_capture, not stribeck: the rack twin's friction is its own type rung with every term its equation
        # reads (weakening limit, capture speed and dwell), PEP 0004 §11.7.
        "M3": "M3.weakening_capture",
        "M4": "M4.drivetrain",
        # WHY envelope, not dcmotor: sim2real's servo M5 builds on its M4 (the rack twin), and M5.envelope stands on
        # M4.drivetrain; M5.dcmotor stands on M3.lugre, so its fallback misses M4 and it holds none of the twin's friction
        # or stiffness. The first draft's M5 -> M5.dcmotor found 10 problems (PEP 0004 §8.2 status, §11.3).
        "M5": "M5.envelope",
        "M5.wear": "M5.wear",
        "M6": "M6.residual",
        "M7": "M7.learned",
    },
    # WHY M4 -> ripple and M5 -> dcmotor: the motor numbers its rungs by the actuator layers; its cogging is layer 4's
    # torque ripple and its electrics are robotparts' dcmotor rung at layer 5 (PEP 0004 §11.6).
    "motor": {
        "M0": "M0.ideal",
        "M4": "M4.ripple",
        "M5": "M5.dcmotor",
        "M5.wear": "M5.wear",
        "M6": "M6.residual",
        "M7": "M7.learned",
    },
    # WHY M3 -> load: the gearbox's load-dependent loss is layer 3, as efficiency (PEP 0004 §11.9); M4 is the drivetrain.
    "gearbox": {
        "M0": "M0.ideal",
        "M3": "M3.load",
        "M4": "M4.drivetrain",
        "M4.wear": "M4.wear",
        "M6": "M6.residual",
        "M7": "M7.learned",
    },
    # WHY: foc_controller has one physics rung per card rung: the delay and loop at M1, the ceilings and heat at M2.
    "driver": {
        "M0": "M0.ideal",
        "M1": "M1.delay_loop",
        "M2": "M2.ceiling_heat",
        "M2.wear": "M2.wear",
        "M6": "M6.residual",
        "M7": "M7.learned",
    },
    # WHY: one rung per level, the encoder example of PEP 0004 §4.
    "encoder": {
        "M0": "M0.quantiser",
        "M1": "M1.noise_latency",
        "M2": "M2.eccentricity",
        "M2.wear": "M2.wear",
    },
    # WHY the inertial branch: rigid_body_chain branches off M1.zero_offsets; the subassembly's inertials and loop closure
    # are M2.inertial, then M2.wear and M6.inertial_residual (PEP 0004 §11.2).
    "arm_subassembly": {
        "M0": "M0.nominal",
        "M1": "M1.zero_offsets",
        "M2": "M2.inertial",
        "M2.wear": "M2.wear",
        "M6": "M6.inertial_residual",
        "M7": "M7.learned",
    },
    # WHY the geometric branch: the 6-DOF arm's DH errors are M2.geometric, then M3.compliance, M3.wear and M6.residual
    # (PEP 0004 §11.2).
    "arm_6dof": {
        "M0": "M0.nominal",
        "M1": "M1.zero_offsets",
        "M2": "M2.geometric",
        "M3": "M3.compliance",
        "M3.wear": "M3.wear",
        "M6": "M6.residual",
        "M7": "M7.learned",
    },
    # WHY: the gripper card's rungs are the gripper type's, one per level.
    "arm_6dof_gripper": {
        "M0": "M0.tcp",
        "M1": "M1.width_map",
        "M2": "M2.contact",
        "M2.wear": "M2.wear",
        "M6": "M6.residual",
        "M7": "M7.learned",
    },
    # WHY M3 -> stribeck: sim2real's conveyor M3 points at robotparts' stribeck rung, whose stribeck_velocity the type's
    # rung now needs (PEP 0004 §11.13); M4 is the belt's stretch.
    "conveyor": {
        "M0": "M0.ideal",
        "M2": "M2.coulomb_viscous",
        "M3": "M3.stribeck",
        "M4": "M4.stretch",
        "M4.wear": "M4.wear",
        "M6": "M6.residual",
        "M7": "M7.learned",
    },
    # WHY: the camera types have one physics rung per level and no learned rung (sim2real's cards have none either).
    "camera_rgb": {
        "M0": "M0.pinhole",
        "M1": "M1.distortion",
        "M2": "M2.exposure_latency",
        "M3": "M3.rolling_shutter",
        "M3.wear": "M3.wear",
        "M6": "M6.residual",
    },
    "camera_rgbd": {
        "M0": "M0.stereo",
        "M1": "M1.disparity_noise",
        "M2": "M2.depth_bias",
        "M2.wear": "M2.wear",
        "M6": "M6.residual",
    },
    "camera_hsi": {
        "M0": "M0.bands",
        "M1": "M1.band_widths",
        "M2": "M2.smile_keystone",
        "M3": "M3.pushbroom",
        "M3.wear": "M3.wear",
    },
    # WHY: the marker's four physics rungs, one per level (PEP 0004 §5.13).
    "aruco_marker": {
        "M0": "M0.nominal",
        "M1": "M1.as_built",
        "M2": "M2.print_scale",
        "M3": "M3.curl",
    },
}

# (card, card rung key, parameter) -> the robot_models rung that holds it instead. The card holds the name LOWER than
# robot_models does; every other card parameter must be held at its mapped rung.
MOVED = {
    # WHY: heat is robotparts' layer 5. The rack twin carries its two-node thermal pair at its M4; robot_models holds it
    # at M5.envelope (PEP 0004 §8.2 rule 3, §11.3).
    ("servo", "M4", "thermal_r_c"): "M5.envelope",
}

# (card, parameter) -> (sim2real's unit, factor to SI, the SI unit it lands in). A canonical name the card states in
# another unit; the factor multiplies sim2real's number into robot_models' unit. The SI unit is kept so that a change of
# the canonical unit in robot_models turns this test red instead of silently re-meaning the factor.
UNITS = {
    # WHY mrad: the encoder card writes its noise and eccentricity in mrad, the scale an encoder's error is read at.
    ("encoder", "noise_sigma"): ("mrad", 1e-3, "rad"),
    ("encoder", "eccentricity_harmonics"): ("mrad", 1e-3, "rad"),
    # WHY mm: the five-bar's loop-closure tolerance is a millimetre figure from its bench geometry.
    ("arm_subassembly", "closure_tolerance"): ("mm", 1e-3, "m"),
    # WHY mm: a depth camera's bias is stated in millimetres of depth.
    ("camera_rgbd", "depth_bias_coeffs"): ("mm", 1e-3, "m"),
    # WHY nm: a spectrometer's band centres and widths are wavelengths in nanometres.
    ("camera_hsi", "band_centres"): ("nm", 1e-9, "m"),
    ("camera_hsi", "band_fwhm"): ("nm", 1e-9, "m"),
    # WHY ×1000: sim2real's exposure is in lux·ms; per lux·s the response is 1000 times larger.
    ("camera_rgb", "exposure_response"): ("DN / (lux·ms)", 1e3, "DN/(lx·s)"),
}

# sim2real's spelling -> robot_models' spelling of the SAME unit (no factor): rule 4 compares after this.
SAME_UNIT = {
    # WHY: sim2real writes "1" for a dimensionless number (registry.Parameter), robot_models "" for a ratio or a count.
    "1": "",
    # WHY: a text value (the marker's dictionary) and an id list carry no unit; sim2real names what they are instead.
    "name": "",
    "id": "",
    # WHY: metres per raw depth count; the count is dimensionless, so the SI unit is m.
    "m/unit": "m",
    # WHY: the same unit, without the brackets around the product.
    "rad/N·m": "rad/(N·m)",
    # WHY: sim2real's link_inertials omits the centre of mass's m from its unit; the quantity is the same (PEP 0004 §8.2).
    "kg, kg·m²": "kg, m, kg·m²",
}

CARD_IDS = sorted(RUNG_MAP)


# --- reading both sides ----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def robot_ladders():
    """{type: Ladder}, found live by walking the robot_models package (PEP 0004 §4, discovery)."""
    return ladder_core.ladders()


def ladder_of(robot_ladders, card_id):
    type_name = CARD_TYPES[card_id]
    if type_name not in robot_ladders:
        pytest.fail(f"card {card_id}: robot_models has no ladder of type {type_name!r}; ladders found: "
                    f"{', '.join(sorted(robot_ladders))}")
    return robot_ladders[type_name]


def card_level(card_rung_key: str) -> int:
    # WHY parse here: a sim2real key is its own "M<k>[.wear]" with k the layer (type_cards/CONTRACT.md, "Rung keys"); a
    # robot_models key is composed and never parsed (PEP 0004 §4), so that side reads Rung.level.
    return int(card_rung_key.split(".")[0].removeprefix("M"))


def card_base(card, card_rung) -> str | None:
    """The card rung this one builds on: the physics rung before it (a card's ladder is lowest first and each physics
    rung holds the whole rung below it, schema.Rung), a residual's named base, nothing for a learned net."""
    if card_rung.kind == "residual":
        return card_rung.base or None
    if card_rung.kind != "physics":
        return None
    position = [rung.key for rung in card.rungs].index(card_rung.key)
    physics_below = [rung.key for rung in card.rungs[:position] if rung.kind == "physics"]
    return physics_below[-1] if physics_below else None


def mapped_rungs(robot_ladders, card_id):
    """(card rung, mapped key) for every card rung whose mapped rung exists; rule 1's test reports the others."""
    ladder = ladder_of(robot_ladders, card_id)
    for card_rung in reg.CARDS[card_id].rungs:
        mapped = RUNG_MAP[card_id].get(card_rung.key)
        if mapped in ladder.keys:
            yield card_rung, mapped


def where_held(robot_ladders, ladder, mapped, name):
    """Where a card parameter resolves: (the ladder that knows it, its rung to check, the canonical names, held there?).

    The card's own type first; a name the type does not know is looked up in the types the mapped rung composes, at the
    composed rung (a servo's driver delay sits in foc_controller, PEP 0004 §7). None: no ladder knows it.
    """
    try:
        names = ladder.resolve(name)
    except KeyError:
        for other_type, other_key in ladder.composed(mapped).items():
            other = robot_ladders[other_type]
            try:
                names = other.resolve(name)
            except KeyError:
                continue
            return other, other_key, names, set(names) <= set(other.holds(other_key))
        return None
    return ladder, mapped, names, set(names) <= set(ladder.holds(mapped))


# --- the map covers the cards ----------------------------------------------------------------------------------------


def test_every_card_and_card_rung_is_mapped():
    problems = []
    for card_id in sorted(set(reg.CARDS) - set(RUNG_MAP)):
        problems.append(f"card {card_id} is not in RUNG_MAP: map it onto a robot_models type and rungs")
    for card_id in sorted(set(RUNG_MAP) - set(reg.CARDS)):
        problems.append(f"RUNG_MAP maps card {card_id}, which sim2real no longer has")
    if set(CARD_TYPES) != set(RUNG_MAP):
        problems.append(f"CARD_TYPES and RUNG_MAP name different cards: {sorted(set(CARD_TYPES) ^ set(RUNG_MAP))}")
    for card_id in sorted(set(reg.CARDS) & set(RUNG_MAP)):
        card_keys = [rung.key for rung in reg.CARDS[card_id].rungs]
        for key in card_keys:
            if key not in RUNG_MAP[card_id]:
                problems.append(f"card {card_id} rung {key} is not in RUNG_MAP[{card_id!r}]")
        for key in RUNG_MAP[card_id]:
            if key not in card_keys:
                problems.append(f"RUNG_MAP[{card_id!r}] maps rung {key}, which card {card_id} no longer has")
    assert not problems, "\n".join(problems)


def test_every_mapped_type_has_a_ladder(robot_ladders):
    missing = sorted(set(CARD_TYPES.values()) - set(robot_ladders))
    assert not missing, (f"robot_models has no ladder for {missing} (cards "
                         f"{sorted(card for card, type_name in CARD_TYPES.items() if type_name in missing)}); "
                         f"ladders found: {sorted(robot_ladders)}")


# --- the four rules, per card ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_rule1_mapped_rung_exists_at_the_card_rungs_level(robot_ladders, card_id):
    ladder = ladder_of(robot_ladders, card_id)
    problems = []
    for card_rung in reg.CARDS[card_id].rungs:
        mapped = RUNG_MAP[card_id].get(card_rung.key)
        if mapped is None:
            continue  # test_every_card_and_card_rung_is_mapped reports it
        try:
            robot_rung = ladder.rung(mapped)
        except KeyError as error:
            problems.append(f"card {card_id} {card_rung.key} -> {ladder.type} {mapped}: no such rung ({error.args[0]})")
            continue
        if robot_rung.level != card_level(card_rung.key):
            problems.append(f"card {card_id} {card_rung.key} -> {ladder.type} {mapped}: level {robot_rung.level}, "
                            f"the card rung's is {card_level(card_rung.key)}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_rule2_card_base_is_in_the_mapped_fallback(robot_ladders, card_id):
    ladder = ladder_of(robot_ladders, card_id)
    card = reg.CARDS[card_id]
    problems = []
    for card_rung, mapped in mapped_rungs(robot_ladders, card_id):
        base = card_base(card, card_rung)
        if base is None:
            continue
        mapped_base = RUNG_MAP[card_id].get(base)
        fallback = ladder.fallback(mapped)
        if mapped_base not in fallback:
            problems.append(f"card {card_id} {card_rung.key} -> {ladder.type} {mapped}: the card rung builds on {base} "
                            f"-> {mapped_base}, which is not in {mapped}'s fallback {' <- '.join(fallback)}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_rule3_every_card_parameter_is_held(robot_ladders, card_id):
    ladder = ladder_of(robot_ladders, card_id)
    deployment = {item.name for item in ladder.deployment}
    problems = []
    for card_rung, mapped in mapped_rungs(robot_ladders, card_id):
        for parameter in card_rung.parameters:
            if parameter.name in deployment or (card_id, card_rung.key, parameter.name) in MOVED:
                continue
            found = where_held(robot_ladders, ladder, mapped, parameter.name)
            if found is None:
                composed = ", ".join(f"{other} {key}" for other, key in ladder.composed(mapped).items()) or "none"
                try:
                    ladder.resolve(parameter.name)
                    hint = ""
                except KeyError as error:
                    hint = error.args[0]  # the ladder's own message, with the nearest known name
                problems.append(f"card {card_id} {card_rung.key} -> {ladder.type} {mapped}: parameter "
                                f"{parameter.name!r} is no parameter, alias, packed or deployment-only name of "
                                f"{ladder.type} nor of a type the rung composes ({composed}): {hint}")
                continue
            owner, owner_key, names, held = found
            if not held:
                missing = [name for name in names if name not in owner.holds(owner_key)]
                problems.append(f"card {card_id} {card_rung.key} -> {ladder.type} {mapped}: parameter "
                                f"{parameter.name!r} resolves to {', '.join(names)} in {owner.type}, and "
                                f"{owner.type} {owner_key} does not hold {', '.join(missing)} (add it to that rung, "
                                f"map the card rung elsewhere, or list it in MOVED with a WHY)")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("card_id", CARD_IDS)
def test_rule4_canonical_names_carry_the_si_unit(robot_ladders, card_id):
    ladder = ladder_of(robot_ladders, card_id)
    problems = []
    checked = set()  # (name, unit): a name every rung restates is judged once per unit the card writes it in
    for card_rung, mapped in mapped_rungs(robot_ladders, card_id):
        for parameter in card_rung.parameters:
            found = where_held(robot_ladders, ladder, mapped, parameter.name)
            if found is None or (parameter.name, parameter.unit) in checked:
                continue
            owner = found[0]
            # WHY canonical names only (PEP 0004 §8.2 rule 4): an alias states its source's unit on the Alias itself, which
            # this rule does not judge. A name canonical in a composed type (the servo card's torque_scale, which is
            # foc_controller's) is held to that type's unit: it is canonical where it is held.
            if parameter.name not in owner.names:
                continue
            checked.add((parameter.name, parameter.unit))
            canonical_unit = owner.parameter(parameter.name).unit
            if SAME_UNIT.get(parameter.unit, parameter.unit) == canonical_unit:
                continue
            stated = UNITS.get((card_id, parameter.name))
            if stated is not None and stated[0] == parameter.unit and stated[2] == canonical_unit:
                continue
            problems.append(f"card {card_id} {card_rung.key} -> {owner.type}: canonical parameter {parameter.name!r} "
                            f"is in {parameter.unit!r}, robot_models' unit is {canonical_unit!r}, and UNITS has "
                            f"{stated!r} for it (state (sim2real unit, factor, SI unit) there, or fix the card's unit)")
    assert not problems, "\n".join(problems)


# --- the exception tables stay true ----------------------------------------------------------------------------------


def test_moved_entries_are_needed_and_held_where_they_say(robot_ladders):
    problems = []
    for (card_id, card_key, name), holder in MOVED.items():
        ladder = ladder_of(robot_ladders, card_id)
        card_rung = next((rung for rung in reg.CARDS[card_id].rungs if rung.key == card_key), None)
        if card_rung is None or name not in card_rung.parameter_names:
            problems.append(f"MOVED ({card_id}, {card_key}, {name}): card {card_id} {card_key} no longer states {name}")
            continue
        mapped = RUNG_MAP[card_id][card_key]
        found = where_held(robot_ladders, ladder, mapped, name)
        if found is None:
            problems.append(f"MOVED ({card_id}, {card_key}, {name}): {ladder.type} does not know {name!r} at all")
            continue
        owner, _, names, held_at_mapped = found
        if held_at_mapped:
            problems.append(f"MOVED ({card_id}, {card_key}, {name}): {ladder.type} {mapped} holds it now; drop the entry")
        if holder not in owner.keys or not set(names) <= set(owner.holds(holder)):
            problems.append(f"MOVED ({card_id}, {card_key}, {name}): {owner.type} {holder} does not hold "
                            f"{', '.join(names)}, though the entry says it does")
    assert not problems, "\n".join(problems)


def test_unit_entries_match_the_card_and_the_canonical_unit(robot_ladders):
    problems = []
    for (card_id, name), (card_unit, factor, si_unit) in UNITS.items():
        ladder = ladder_of(robot_ladders, card_id)
        stated = {parameter.unit for rung in reg.CARDS[card_id].rungs for parameter in rung.parameters
                  if parameter.name == name}
        if stated != {card_unit}:
            problems.append(f"UNITS ({card_id}, {name}): the card states it in {sorted(stated) or 'no rung'}, "
                            f"the entry says {card_unit!r}")
        if name not in ladder.names:
            problems.append(f"UNITS ({card_id}, {name}): {name!r} is not canonical in {ladder.type}; drop the entry")
            continue
        if ladder.parameter(name).unit != si_unit:
            problems.append(f"UNITS ({card_id}, {name}): {ladder.type}'s unit is {ladder.parameter(name).unit!r}, "
                            f"the entry's factor {factor:g} lands in {si_unit!r}")
    assert not problems, "\n".join(problems)
