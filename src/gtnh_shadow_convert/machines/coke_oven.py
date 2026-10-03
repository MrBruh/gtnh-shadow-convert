"""The Industrial Coke Oven (``machines["Industrial Coke Oven"]`` in ``machines.ts``).

Its own module because its options are also the shape of the build: the slice count is how long the
oven is and the casing which blocks it is made of, and the emitter carries both into the plan, where
the solver reserves the form with that many slices (``cokeOvenSlices``).

Parallels: 16 plus 8 per slice past the first with Heat Resistant casings, 32 plus 16 with Heat
Proof ones. Power: 2% less per coil tier, multiplicatively, from the second tier (so Cupronickel
costs 2% more). More than 15 slices needs Eternal coils, the fourteenth tier.
"""

from __future__ import annotations

from fractions import Fraction

from .machine import Choice, ChoiceKind, Machine, RecipeContext
from .overclock import StandardOverclocker
from .rules import COIL_TIER

NAME = "Industrial Coke Oven"
#: The coil index (Eternal) that allows more than :data:`MAX_SLICES` slices.
ETERNAL = 13
MAX_SLICES = 15


def _parallels(c: RecipeContext) -> int:
    heat_proof = c.choice("casingType") == 1
    base, per_slice = (32, 16) if heat_proof else (16, 8)
    return base + (c.choice("slices") - 1) * per_slice


def _slice_limit(c: RecipeContext, choices: dict[str, int]) -> None:
    if choices["coilTier"] != ETERNAL and choices["slices"] > MAX_SLICES:
        choices["slices"] = MAX_SLICES


RULE = Machine(
    StandardOverclocker.only_normal(),
    power=lambda c: Fraction(98, 100) ** (c.choice("coilTier") - 1),
    parallels=_parallels,
    choices={
        "casingType": Choice(
            "Casing Type",
            ("Heat Resistant Casings", "Heat Proof Casings"),
            kind=ChoiceKind.COKE_OVEN_CASING,
        ),
        "slices": Choice(
            "Number of slices", minimum=1, maximum=999, kind=ChoiceKind.COKE_OVEN_SLICES
        ),
        "coilTier": COIL_TIER,
    },
    enforce_choice_constraints=_slice_limit,
    info="Eternal coils needed for more than 15 slices",
)
