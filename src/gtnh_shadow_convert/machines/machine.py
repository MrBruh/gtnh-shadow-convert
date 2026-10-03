"""What a machine rule is (the ``Machine`` type of the calculator's ``src/machines.ts``).

A rule says how one machine runs a recipe: its speed and power multipliers, its parallels, how it
overclocks, which options (``choices``) the player sets on it, and, for a few machines, how it
rewrites the recipe's inputs and outputs. Every one of those may be a constant or a function of the
recipe row being solved (:class:`RecipeContext`), which is ``MachineCoefficient`` in the app.

All arithmetic is exact: a speed of 2.2 is ``Fraction(11, 5)``. The app works in floating point, so
the two agree to rounding error, except that a whole machine count here is exactly whole.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import TYPE_CHECKING

from ..databin import Recipe, RecipeIo

if TYPE_CHECKING:
    from .overclock import Overclocker


@dataclass(frozen=True)
class RecipeContext:
    """The recipe row a rule is evaluated for: which recipe, at which tier, with which options.

    ``voltage_tier`` is the row's tier after a machine that fixes its own tier has overridden it,
    and ``choices`` are the row's options after :func:`~.validate_choices`.
    """

    recipe: Recipe
    voltage_tier: int
    choices: Mapping[str, int]

    def choice(self, key: str) -> int:
        return self.choices[key]


type Coefficient[T] = T | Callable[[RecipeContext], T]


def evaluate[T](coefficient: Coefficient[T], context: RecipeContext) -> T:
    """``GetParameter``: a constant as is, a function applied to the row."""
    if callable(coefficient):
        result: T = coefficient(context)
        return result
    return coefficient


class ChoiceKind(Enum):
    """What a choice stands for in the built machine, for the options a plan carries over."""

    HEATING_COIL = "heatingCoil"
    FLUID_PIPE_CASING = "pipeCasing"
    ITEM_PIPE_CASING = "itemPipeCasing"
    COKE_OVEN_CASING = "cokeOvenCasing"
    COKE_OVEN_SLICES = "cokeOvenSlices"


@dataclass(frozen=True)
class Choice:
    """One option a player sets on a machine (``Choice``).

    A list of ``options`` bounds it to their indexes; otherwise ``minimum`` and ``maximum`` do,
    with no maximum when ``maximum`` is ``None``.
    """

    description: str
    options: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int | None = None
    kind: ChoiceKind | None = None

    @property
    def upper(self) -> int | None:
        return len(self.options) - 1 if self.options else self.maximum


#: A rule's rewrite of a recipe's slots (``Machine.recipe``). It receives copies it may edit.
RecipeRewrite = Callable[[RecipeContext, list[RecipeIo]], list[RecipeIo]]


@dataclass(frozen=True)
class Machine:
    """A machine rule (``Machine``). See the module docstring."""

    overclocker: Coefficient[Overclocker]
    speed: Coefficient[Fraction] = Fraction(1)
    power: Coefficient[Fraction] = Fraction(1)
    parallels: Coefficient[int] = 1
    choices: Mapping[str, Choice] = field(default_factory=dict)
    #: Adjusts the validated choices for the recipe (a minimum tier the recipe needs, say).
    enforce_choice_constraints: Callable[[RecipeContext, dict[str, int]], None] | None = None
    recipe: RecipeRewrite | None = None
    #: The app's machines that ignore the voltage limit on parallels (only the Advanced Assembly
    #: Line, which this package does not port).
    ignore_parallel_limit: bool = False
    #: A machine that always runs at one tier, whatever the row says (fusion reactors). A constant
    #: in every rule the app has, so not a coefficient here.
    fixed_voltage_tier: int | None = None
    #: Recipes this machine cannot run; the solver then picks another machine for them.
    excludes_recipe: Callable[[Recipe], bool] | None = None
    #: Round the duration after dividing by parallels (only the Advanced Assembly Line).
    round_after_parallels: bool = False
    #: The machine is a single block although the app keys it among the multiblocks (the bronze
    #: and steel steam machines). Only the emitter reads it, to say what kind of block it is.
    single_block: bool = False
    info: str = ""
