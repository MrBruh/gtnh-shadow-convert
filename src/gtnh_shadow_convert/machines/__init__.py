"""The calculator's machine rules (``src/machines.ts``), by the name of the machine that runs them.

A single block runs by one generic rule (:mod:`.singleblock`); a multiblock controller looks its
rule up here by its display name, exactly as the export stores it, which is how the app keys its
table. A controller with no ported rule is an :class:`~..errors.UnsupportedMachineError`, never a
guess: the app falls back to computing it as a single block, which can be off by its whole parallel
count.
"""

from __future__ import annotations

from ..databin import plain_text
from ..errors import UnsupportedMachineError
from .machine import Choice, ChoiceKind, Coefficient, Machine, RecipeContext, evaluate
from .overclock import NULL_OVERCLOCKER, NullOverclocker, OverclockResult, StandardOverclocker
from .singleblock import SINGLE_BLOCK, single_block_rule

#: Rules by controller name (the export's HTML name). Filled by the rule modules.
MACHINES: dict[str, Machine] = {}

#: Controllers the calculator knows whose rules are not ported, with the reason.
UNSUPPORTED: dict[str, str] = {}


def rule_for(name: str) -> Machine:
    """The rule for the controller named ``name``, or :class:`UnsupportedMachineError`."""
    rule = MACHINES.get(name)
    if rule is None:
        raise UnsupportedMachineError(plain_text(name), UNSUPPORTED.get(name, ""))
    return rule


def excluder_of(name: str) -> Machine | None:
    """The rule for ``name`` if there is one, for the crafter pick, which only asks whether a
    machine refuses a recipe and must not fail on a machine it then passes over."""
    return MACHINES.get(name)


__all__ = [
    "MACHINES",
    "NULL_OVERCLOCKER",
    "SINGLE_BLOCK",
    "UNSUPPORTED",
    "Choice",
    "ChoiceKind",
    "Coefficient",
    "Machine",
    "NullOverclocker",
    "OverclockResult",
    "RecipeContext",
    "StandardOverclocker",
    "evaluate",
    "excluder_of",
    "rule_for",
    "single_block_rule",
]
