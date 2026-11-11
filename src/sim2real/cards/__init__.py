"""Sim2Real type cards (type_cards.registry): metrics, model, coverage, view and procedure per part type.

Moved unchanged from type_cards/ on 2026-11-10 (schema sim2real.type_cards/2, CONTRACT.md's additive-only rule); `type_cards` stays
importable as a shim that IS this package. Data only in spirit: which metrics, gates and coverage each type uses, and the gate
targets. It defines no parameter or range type of its own: datasheet values are robot_msgs.space.Value, range checks
Space(msg).contains / .violations. The churning-most layer: may import every other sim2real layer, and none may import it.
"""
