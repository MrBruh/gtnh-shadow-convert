"""The ExxonMobil Chemical Plant (``machines["ExxonMobil Chemical Plant"]`` in ``machines.ts``).

Its own module because three of its parts describe the build: the heating coil (speed), the fluid
pipe casing (parallels), and the solid casing, which the calculator does not model at all. GT runs a
recipe only on a solid casing of at least the recipe's special value (``MTEChemicalPlant``: refused
when ``mSpecialValue > mSolidCasingTier``), so the emitter records that minimum as the node's
``solidCasing`` (:func:`solid_casing_key`).

Speed: half the recipe's speed with Cupronickel coils, a half faster per coil tier. Parallels: 2 per
pipe casing tier. A catalyst in the inputs wears out at 1/50 of an item per run, a fifth less per
pipe casing tier, and not at all with Infinity coils (T12, index 10 and up) and Tungstensteel pipes.
"""

from __future__ import annotations

from fractions import Fraction

from ..databin import IoType, Item, RecipeIo
from .machine import Machine, RecipeContext
from .overclock import StandardOverclocker
from .rules import COIL_TIER, FLUID_PIPE_CASING

NAME = "ExxonMobil Chemical Plant"

#: The solid casings by tier, as GT++ registers them for the Chemical Plant
#: (``GregtechAlgaeContent.registerMachineCasingForTier``, tiers 0 to 7), keyed by material.
SOLID_CASINGS = (
    "bronze",
    "steel",
    "aluminium",
    "stainless_steel",
    "titanium",
    "tungstensteel",
    "laurenium",
    "botmium",
)


def solid_casing_key(special_value: int) -> str:
    """The cheapest solid casing that runs a recipe with this special value."""
    tier = min(max(special_value, 0), len(SOLID_CASINGS) - 1)
    return SOLID_CASINGS[tier]


def _catalyst_wear(c: RecipeContext, items: list[RecipeIo]) -> list[RecipeIo]:
    if c.choice("coilTier") >= 10 and c.choice("pipeFluidCasingTier") >= 3:
        return items
    for slot in items:
        if (
            slot.type is IoType.ITEM_INPUT
            and isinstance(slot.goods, Item)
            and slot.goods.name.endswith("Catalyst")
        ):
            slot.amount = (1 - Fraction(2, 10) * c.choice("pipeFluidCasingTier")) / 50
            break
    return items


RULE = Machine(
    StandardOverclocker.only_normal(),
    speed=lambda c: c.choice("coilTier") * Fraction(1, 2) + Fraction(1, 2),
    parallels=lambda c: (c.choice("pipeFluidCasingTier") + 1) * 2,
    choices={"coilTier": COIL_TIER, "pipeFluidCasingTier": FLUID_PIPE_CASING},
    recipe=_catalyst_wear,
)
