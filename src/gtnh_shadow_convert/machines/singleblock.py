"""The rule every single-block machine runs by (``singleBlockMachine`` in ``machines.ts``).

One parallel, normal overclocks only. A recipe that needs a compressor tier above the basic
machine's (``compression_tier`` metadata, the black hole and neutronium compressors' recipes) is
excluded, so the solver moves it to a multiblock. The Mass Fabricator alone is cheaper: its power
halves per tier (the app's ``singleBlockMachineWith22Overclock``).
"""

from __future__ import annotations

from fractions import Fraction

from ..databin import Recipe, RecipeType
from .machine import Machine, RecipeContext
from .overclock import StandardOverclocker


def _excludes_compression(recipe: Recipe) -> bool:
    gt = recipe.gt
    return (gt.metadata_value("compression_tier") if gt is not None else 0) > 0


SINGLE_BLOCK = Machine(
    overclocker=StandardOverclocker.only_normal(),
    excludes_recipe=_excludes_compression,
)


def _mass_fabricator_power(context: RecipeContext) -> Fraction:
    return Fraction(1, 2) ** context.voltage_tier


MASS_FABRICATOR = Machine(
    overclocker=StandardOverclocker.only_normal(),
    power=_mass_fabricator_power,
)


def single_block_rule(recipe_type: RecipeType) -> Machine:
    """``GetSingleBlockMachine``: the rule for a recipe type's single blocks."""
    if recipe_type.name == "Mass Fabrication":
        return MASS_FABRICATOR
    return SINGLE_BLOCK
