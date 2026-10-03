"""The calculator's machine rules (``src/machines.ts``), by the name of the machine that runs them.

A single block runs by one generic rule (:mod:`.singleblock`); a multiblock controller looks its
rule up here by its display name, exactly as the export stores it, which is how the app keys its
table. A controller with no ported rule is an :class:`~..errors.UnsupportedMachineError`, never a
guess: the app falls back to computing it as a single block, which can be off by its whole parallel
count.
"""

from __future__ import annotations

from ..databin import Item, plain_text
from ..errors import UnsupportedMachineError
from . import chemical_plant, coke_oven, rules
from .machine import Choice, ChoiceKind, Coefficient, Machine, RecipeContext, evaluate
from .overclock import NULL_OVERCLOCKER, NullOverclocker, OverclockResult, StandardOverclocker
from .singleblock import SINGLE_BLOCK, single_block_rule

#: Rules by controller name (the export's HTML name), as the app's ``machines`` table.
MACHINES: dict[str, Machine] = {
    **rules.MACHINES,
    coke_oven.NAME: coke_oven.RULE,
    chemical_plant.NAME: chemical_plant.RULE,
}

#: Controllers the calculator knows whose rules are not ported, with the reason.
UNSUPPORTED: dict[str, str] = dict(rules.NOT_PORTED)


#: How the app computes a tiered single block that its data lists among a recipe type's
#: multiblocks: as ``notImplementedMachine``, normal overclocks and one parallel, on the multiblock
#: path (its overclocks capped by the voltage's spare parallels). The 2.9 data lists every single
#: block that way, because its export found no "Voltage IN (LV)" tooltip to sort them by, so this
#: is what the app computes for every single block today. The figures are the single-block rule's;
#: only a recipe drawing more than one amp can come out an overclock lower than on that path.
LISTED_SINGLE_BLOCK = Machine(
    StandardOverclocker.only_normal(), info="Machine not implemented (Calculated as a singleblock)"
)


def rule_for(name: str) -> Machine:
    """The rule for the controller named ``name``, or :class:`UnsupportedMachineError`."""
    rule = MACHINES.get(name)
    if rule is None:
        raise UnsupportedMachineError(plain_text(name), UNSUPPORTED.get(name, ""))
    return rule


def rule_for_crafter(crafter: Item) -> Machine:
    """The rule a recipe's machine runs by: its own, else :data:`LISTED_SINGLE_BLOCK` for a tiered
    single block, else :class:`UnsupportedMachineError`."""
    rule = MACHINES.get(crafter.name)
    if rule is not None:
        return rule
    if crafter.single_block_tier is not None:
        return LISTED_SINGLE_BLOCK
    return rule_for(crafter.name)


def excluder_of(name: str) -> Machine | None:
    """The rule for ``name`` if there is one, for the crafter pick, which only asks whether a
    machine refuses a recipe and must not fail on a machine it then passes over."""
    return MACHINES.get(name)


__all__ = [
    "LISTED_SINGLE_BLOCK",
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
    "rule_for_crafter",
    "single_block_rule",
]
