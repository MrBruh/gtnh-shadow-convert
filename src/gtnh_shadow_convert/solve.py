"""Solve a plan for its rates: a port of the calculator's ``src/solver.ts``.

The calculator never saves its results, so they are recomputed here the way it computes them::

    page.products ------------------------------------> root collection (a demand is an input)
    every recipe row, depth first (_prepare)
      | resolve the recipe (remap table included)
      | pick its machine: the row's saved multiblock, else a single block, else the first
      |   multiblock that does not refuse the recipe, else the type's default crafter
      | rate math from the machine rule: parallels, overclocks, speed, rounding to whole ticks
      | the rule's rewrite of the recipe's slots; a filled container splits into fluid + empty
      v
    per group, innermost first (_link_group)
      | a good made AND used in a group is linked there (one equality: used - made = demand),
      |   unless the group says Ignore; an ore-dict input links to the first of its items made
      | a linked good stops there; anything else bubbles up to the parent group
      v
    exact LP (lp.minimise): one variable per row (runs per minute), minimise total runs
      v
    machines = runs x duration / (overclock factor)       [fractional; the emitter rounds up]

The app solves twice to dodge an ordering bug (``UpdateProject``: a rule reading the recipe's slot
count saw last solve's slots). The rules ported here never read it, so one solve suffices; the
heavy machines that do (the Advanced Assembly Line, the QFT) are not ported.

Where the app silently gives up (a recipe id it cannot find, an infeasible LP), this raises.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction

from . import lp
from .databin import Fluid, IoType, Item, OreDict, Recipe, RecipeIo, Repository
from .errors import (
    ConversionError,
    ConversionWarning,
    InfeasiblePlanError,
    MalformedPlanError,
    UnknownRecipeError,
)
from .machines import (
    Machine,
    OverclockResult,
    RecipeContext,
    evaluate,
    excluder_of,
    rule_for_crafter,
    single_block_rule,
)
from .page import LinkAlgorithm, Page, RecipeElement, RecipeGroup

#: Each tier's voltage, LV first (``voltageTier`` in ``utils.ts``), to MAX+11.
VOLTAGES: tuple[int, ...] = (
    32,
    128,
    512,
    2048,
    8192,
    32768,
    131072,
    524288,
    2097152,
    8388608,
    33554432,
    134217728,
    536870912,
    2147483640,
    *(2147483640 * 4**k for k in range(1, 12)),
)

#: Each tier's name, spelled as gtnh-factory-flow plans spell them (``LuV``, not ``LUV``).
TIER_NAMES: tuple[str, ...] = (
    "LV",
    "MV",
    "HV",
    "EV",
    "IV",
    "LuV",
    "ZPM",
    "UV",
    "UHV",
    "UEV",
    "UIV",
    "UMV",
    "UXV",
    "MAX",
    *(f"MAX+{k}" for k in range(1, 12)),
)

#: Ticks in a minute: rates are per minute, recipe durations in ticks.
TICKS_PER_MINUTE = 1200

_NO_OVERCLOCK = OverclockResult(Fraction(1), Fraction(1), 0, "")
#: The key the app's collections use for a product's amount, beside the recipe variables.
_PRODUCT = -1

_Entries = dict[int, Fraction]


@dataclass(frozen=True)
class Flow:
    """One good a recipe moves per run, after a filled container is split into its fluid and its
    empty form, the way the app links them. ``amount`` is before ``probability``."""

    output: bool
    goods: Item | Fluid | OreDict
    amount: Fraction
    probability: Fraction

    @property
    def expected(self) -> Fraction:
        return self.amount * self.probability


def flows(items: list[RecipeIo]) -> list[Flow]:
    """The goods ``items`` move, in slot order, a filled container split in two."""
    result: list[Flow] = []
    for slot in items:
        goods = slot.goods
        output = slot.type.is_output
        container = goods.container if isinstance(goods, Item) else None
        if container is not None and slot.type in (IoType.ITEM_INPUT, IoType.ITEM_OUTPUT):
            fluid_amount = slot.amount * container.amount
            result.append(Flow(output, container.fluid, fluid_amount, slot.probability))
            result.append(Flow(output, container.empty, slot.amount, slot.probability))
        else:
            result.append(Flow(output, goods, slot.amount, slot.probability))
    return result


@dataclass(eq=False)
class SolvedRecipe:
    """One recipe row, solved: which machine runs it, how fast, and how often."""

    element: RecipeElement
    recipe: Recipe
    #: The multiblock (or default crafter) that runs it; ``None`` when a single block does.
    crafter: Item | None
    #: The rule it ran by; ``None`` for a recipe that is not a timed GregTech one and whose
    #: machine has no rule (it has no rate math to apply).
    machine: Machine | None
    voltage_tier: int
    choices: dict[str, int]
    items: list[RecipeIo]
    parallels: int = 0
    overclock_tiers: int = 0
    overclock: OverclockResult = _NO_OVERCLOCK
    #: The rule's speed and power multipliers (``speedModifier``, ``energyModifier``).
    speed: Fraction = Fraction(1)
    power: Fraction = Fraction(1)
    #: The speed gained by rounding the batch down to whole ticks (``speedCorrectionFactor``).
    speed_correction: Fraction = Fraction(1)
    #: Runs one machine completes per base duration (``overclockFactor``).
    overclock_factor: Fraction = Fraction(1)
    #: Energy per run relative to the recipe's own (``powerFactor``).
    power_factor: Fraction = Fraction(1)
    runs_per_minute: Fraction = Fraction(0)
    #: Machines needed, fractional (``crafterCount``); 0 for a recipe with no duration.
    crafter_count: Fraction = Fraction(0)
    #: The item each ore-dict input was linked to, by ore-dict id (``selectedOreDicts``).
    selected_oredicts: dict[str, Item] = field(default_factory=dict)

    @property
    def timed(self) -> bool:
        """Whether this is a GregTech recipe with a duration, the only kind with rate math."""
        gt = self.recipe.gt
        return gt is not None and gt.duration_ticks > 0

    @property
    def single_block(self) -> Item | None:
        """The single block of the row's tier that runs it, if a single block does."""
        if self.crafter is not None:
            return None
        blocks = self.recipe.recipe_type.singleblocks
        tier = self.voltage_tier
        return blocks[tier] if 0 <= tier < len(blocks) else None

    @property
    def batch_ticks(self) -> Fraction:
        """One batch's duration after overclocks, the speed bonus and rounding, in ticks."""
        gt = self.recipe.gt
        if gt is None:
            return Fraction(0)
        return gt.duration_ticks * self.parallels / self.overclock_factor

    @property
    def eut_per_parallel(self) -> Fraction:
        """EU/t one machine draws for each parallel it runs."""
        gt = self.recipe.gt
        if gt is None or self.parallels == 0:
            return Fraction(0)
        return gt.voltage * self.power_factor * self.overclock_factor / self.parallels

    def flows(self) -> list[Flow]:
        return flows(self.items)


@dataclass(eq=False)
class Link:
    """One equality the plan balances: a good made and used inside one group.

    ``consumers`` pair each recipe with the id it asks for, which for an ore-dict input is the
    dict's id. ``demand`` is a plan product linked here (the plan must make it), ``supply`` one the
    plan is given.
    """

    group: RecipeGroup
    goods_id: str
    consumers: list[tuple[SolvedRecipe, str]] = field(default_factory=list)
    producers: list[SolvedRecipe] = field(default_factory=list)
    demand: Fraction | None = None
    supply: Fraction | None = None

    @property
    def description(self) -> str:
        return f"{self.goods_id} in group {self.group.name!r} at {list(self.group.path)}"


@dataclass(frozen=True)
class External:
    """A good that crosses the plan's boundary: used but not made (an input) or made but not used
    (an output). ``recipes`` use or make it; ``product`` is a plan product's amount on it."""

    goods_id: str
    recipes: tuple[SolvedRecipe, ...]
    product: Fraction | None = None


@dataclass
class SolvedPage:
    page: Page
    recipes: list[SolvedRecipe]
    links: list[Link]
    inputs: list[External]
    outputs: list[External]


class _Collection:
    """``LinkCollection``: per good, the recipes that use or make it, not yet linked."""

    def __init__(self) -> None:
        self.inputs: dict[str, _Entries] = {}
        self.outputs: dict[str, _Entries] = {}
        self.oredict_inputs: dict[str, _Entries] = {}
        self.oredict_recipes: dict[str, list[SolvedRecipe]] = {}

    def add_input(self, goods_id: str, amount: Fraction, var: int) -> None:
        if amount == 0:
            return
        entries = self.inputs.setdefault(goods_id, {})
        entries[var] = entries.get(var, Fraction(0)) + amount

    def add_output(self, goods_id: str, amount: Fraction, var: int) -> None:
        entries = self.outputs.setdefault(goods_id, {})
        entries[var] = entries.get(var, Fraction(0)) - amount

    def add_oredict_input(
        self, oredict_id: str, amount: Fraction, var: int, solved: SolvedRecipe
    ) -> None:
        if amount == 0:
            return
        entries = self.oredict_inputs.setdefault(oredict_id, {})
        entries[var] = entries.get(var, Fraction(0)) + amount
        self.oredict_recipes.setdefault(oredict_id, []).append(solved)

    def merge(self, other: _Collection) -> None:
        """``Merge``: a child group's leftovers join this one's, key by key."""
        for mine, theirs in (
            (self.outputs, other.outputs),
            (self.inputs, other.inputs),
            (self.oredict_inputs, other.oredict_inputs),
        ):
            for key, entries in theirs.items():
                mine[key] = {**mine.get(key, {}), **entries}
        for key, recipes in other.oredict_recipes.items():
            self.oredict_recipes[key] = [*self.oredict_recipes.get(key, []), *recipes]


@dataclass
class _Row:
    description: str
    coefficients: _Entries = field(default_factory=dict)
    rhs: Fraction = Fraction(0)


def validate_choices(
    machine: Machine, recipe: Recipe, voltage_tier: int, raw: Mapping[str, Fraction]
) -> dict[str, int]:
    """``ValidateChoices``: each of the machine's options clamped to its range (absent ones at the
    minimum), unknown keys dropped, then the rule's own constraints applied."""
    if not machine.choices:
        return {}
    validated: dict[str, int] = {}
    for key, choice in machine.choices.items():
        value = raw.get(key)
        clamped = Fraction(choice.minimum) if value is None else value
        if clamped < choice.minimum:
            clamped = Fraction(choice.minimum)
        upper = choice.upper
        if upper is not None and clamped > upper:
            clamped = Fraction(upper)
        if clamped.denominator != 1:
            raise MalformedPlanError(
                f"the {choice.description} option is {value}, not a whole number"
            )
        validated[key] = int(clamped)
    if machine.enforce_choice_constraints is not None:
        machine.enforce_choice_constraints(
            RecipeContext(recipe, voltage_tier, validated), validated
        )
    return validated


def _floor_log4(ratio: Fraction) -> int:
    """``floor(log2(ratio) / 2)`` exactly, for ``ratio >= 1``."""
    steps = 0
    while ratio >= 4:
        ratio /= 4
        steps += 1
    return steps


class _Solver:
    def __init__(self, page: Page, repo: Repository) -> None:
        self.page = page
        self.repo = repo
        self.recipes: list[SolvedRecipe] = []
        self.rows: dict[tuple[str, tuple[int, ...], str], _Row] = {}
        self.links: dict[tuple[tuple[int, ...], str], Link] = {}
        self.oredicts: dict[str, OreDict] = {}

    # -- recipe rows ------------------------------------------------------------------------------

    def _pick_crafter(self, element: RecipeElement, recipe: Recipe) -> Item | None:
        """The multiblock that runs the row, or ``None`` for a single block (``PreProcessRecipe``)."""
        recipe_type = recipe.recipe_type
        multiblocks = recipe_type.multiblocks
        crafter: Item | None = None
        if element.crafter:
            saved = self.repo.goods(element.crafter)
            if isinstance(saved, Item) and saved in multiblocks:
                crafter = saved
        if crafter is not None:
            return crafter
        if recipe_type.singleblocks:
            rule = single_block_rule(recipe_type)
            if rule.excludes_recipe is None or not rule.excludes_recipe(recipe):
                return None
        for item in multiblocks:
            rule_or_none = excluder_of(item.name)
            excludes = rule_or_none.excludes_recipe if rule_or_none is not None else None
            if excludes is None or not excludes(recipe):
                return item
        return recipe_type.default_crafter

    def _prepare(self, element: RecipeElement, collection: _Collection) -> None:
        recipe = self.repo.recipe(element.recipe_id)
        if recipe is None:
            raise UnknownRecipeError(element.recipe_id)
        var = len(self.recipes)
        crafter = self._pick_crafter(element, recipe)
        recipe_type = recipe.recipe_type
        gt = recipe.gt
        timed = gt is not None and gt.duration_ticks > 0
        machine: Machine | None
        if crafter is None:
            machine = single_block_rule(recipe_type)
        elif timed:
            machine = rule_for_crafter(crafter)
        else:
            machine = excluder_of(crafter.name)
        tier = element.voltage_tier
        if timed and machine is not None and machine.fixed_voltage_tier is not None:
            tier = machine.fixed_voltage_tier
        if tier >= len(VOLTAGES):
            raise MalformedPlanError(f"recipe row {list(element.path)} has voltage tier {tier}")
        choices = validate_choices(machine, recipe, tier, element.choices) if machine else {}
        solved = SolvedRecipe(element, recipe, crafter, machine, tier, choices, [])
        self.recipes.append(solved)
        context = RecipeContext(recipe, tier, choices)
        if timed and gt is not None and machine is not None:
            self._rate(solved, machine, context)
        items = recipe.items
        if machine is not None and machine.recipe is not None:
            items = machine.recipe(context, items)
        solved.items = items
        for flow in flows(items):
            expected = flow.expected
            if isinstance(flow.goods, OreDict):
                self.oredicts[flow.goods.id] = flow.goods
                collection.add_oredict_input(flow.goods.id, expected, var, solved)
            elif flow.output:
                collection.add_output(flow.goods.id, expected, var)
            else:
                collection.add_input(flow.goods.id, expected, var)

    def _rate(self, solved: SolvedRecipe, machine: Machine, context: RecipeContext) -> None:
        """The rate math of ``PreProcessRecipe``, exact."""
        gt = solved.recipe.gt
        assert gt is not None
        tier = context.voltage_tier
        if tier < gt.voltage_tier:
            warnings.warn(
                f"recipe row {list(solved.element.path)} runs a {TIER_NAMES[gt.voltage_tier]} recipe "
                f"at {TIER_NAMES[tier]}, which GT will not run; the calculator, and so this "
                f"converter, computes it at base speed",
                ConversionWarning,
                stacklevel=4,
            )
        machine_parallels = max(1, evaluate(machine.parallels, context))
        energy = Fraction(evaluate(machine.power, context))
        per_parallel = gt.voltage * energy * gt.amperage
        max_parallels: int | None
        if machine.ignore_parallel_limit:
            max_parallels = machine_parallels
        elif per_parallel == 0:
            max_parallels = None  # the app's floor(V / 0): unlimited
        else:
            max_parallels = max(1, math.floor(VOLTAGES[tier] / per_parallel))
        parallels = (
            machine_parallels if max_parallels is None else min(max_parallels, machine_parallels)
        )
        tier_difference = tier - gt.voltage_tier
        if solved.crafter is None or max_parallels is None:
            overclock_tiers = tier_difference
        else:
            overclock_tiers = min(tier_difference, _floor_log4(Fraction(max_parallels, parallels)))
        overclock = evaluate(machine.overclocker, context).calculate(context, overclock_tiers)
        speed = Fraction(evaluate(machine.speed, context))
        if speed <= 0:
            raise ConversionError(f"the machine rule gives recipe {solved.recipe.id!r} no speed")
        ticks = Fraction(gt.duration_ticks)
        if machine.round_after_parallels:
            ticks /= parallels
        # The game truncates a duration to whole ticks, in the player's favour. Below one tick
        # (subtick processing) the app assumes no rounding.
        estimated = ticks / (overclock.speed * speed)
        correction = estimated / math.floor(estimated) if estimated > 1 else Fraction(1)
        solved.parallels = parallels
        solved.overclock_tiers = overclock_tiers
        solved.overclock = overclock
        solved.speed = speed
        solved.power = energy
        solved.speed_correction = correction
        solved.overclock_factor = overclock.speed * speed * correction * parallels
        solved.power_factor = gt.amperage * overclock.power * energy / speed / correction
        fixed = solved.element.fixed_crafter_count
        if fixed:
            row = self._row(("fixed", solved.element.path, solved.recipe.id))
            row.description = f"the fixed machine count of recipe row {list(solved.element.path)}"
            row.coefficients[len(self.recipes) - 1] = Fraction(1)
            row.rhs = fixed * solved.overclock_factor * TICKS_PER_MINUTE / gt.duration_ticks

    # -- linking ----------------------------------------------------------------------------------

    def _row(self, key: tuple[str, tuple[int, ...], str]) -> _Row:
        row = self.rows.get(key)
        if row is None:
            row = self.rows[key] = _Row(description=" ".join(map(str, key)))
        return row

    def _link(self, group: RecipeGroup, goods_id: str) -> Link:
        key = (group.path, goods_id)
        link = self.links.get(key)
        if link is None:
            link = self.links[key] = Link(group, goods_id)
        return link

    def _add_terms(self, group: RecipeGroup, goods_id: str, entries: _Entries) -> None:
        """``MatchVariablesToConstraints``: add a collection entry's recipes to a link's row."""
        row = self._row(("link", group.path, goods_id))
        for var, amount in entries.items():
            if var != _PRODUCT:
                row.coefficients[var] = row.coefficients.get(var, Fraction(0)) + amount

    def _create_link(
        self,
        group: RecipeGroup,
        goods_id: str,
        key: str,
        table: dict[str, _Entries],
        matched: dict[str, None],
        outputs: _Entries,
    ) -> None:
        """``CreateLinkByAlgorithm``: link ``table[key]`` (the users) to ``goods_id``'s makers."""
        entries = table.pop(key)
        self._add_terms(group, goods_id, entries)
        # `input._amount || -output._amount || 0`: a demanded product, else a given one, else 0.
        demand = entries.get(_PRODUCT)
        supply = outputs.get(_PRODUCT)
        row = self._row(("link", group.path, goods_id))
        row.description = f"the link of {goods_id} in group {group.name!r} at {list(group.path)}"
        row.rhs = demand if demand else (-supply if supply else Fraction(0))
        matched[goods_id] = None
        link = self._link(group, goods_id)
        link.consumers.extend((self.recipes[var], key) for var in entries if var != _PRODUCT)
        if demand is not None:
            link.demand = -demand
        if supply is not None:
            link.supply = -supply

    def _link_group(self, group: RecipeGroup, collection: _Collection) -> None:
        """``CreateAndMatchLinks``: solve the group's children, then link what it makes and uses."""
        for child in group.elements:
            if isinstance(child, RecipeElement):
                self._prepare(child, collection)
            else:
                inner = _Collection()
                self._link_group(child, inner)
                collection.merge(inner)
        matched: dict[str, None] = {}
        for key in list(collection.oredict_inputs):
            for item in self.oredicts[key].items:
                if item.id not in collection.outputs:
                    continue
                # Even an ignored link picks the item, so making and using name the same one.
                for solved in collection.oredict_recipes[key]:
                    solved.selected_oredicts[key] = item
                if group.links.get(item.id, LinkAlgorithm.MATCH) is LinkAlgorithm.IGNORE:
                    continue
                self._create_link(
                    group,
                    item.id,
                    key,
                    collection.oredict_inputs,
                    matched,
                    collection.outputs[item.id],
                )
                break
        for key in list(collection.inputs):
            if group.links.get(key, LinkAlgorithm.MATCH) is LinkAlgorithm.IGNORE:
                continue
            if key not in collection.outputs:
                continue
            self._create_link(group, key, key, collection.inputs, matched, collection.outputs[key])
        for key in matched:
            entries = collection.outputs.pop(key)
            self._add_terms(group, key, entries)
            link = self._link(group, key)
            link.producers.extend(self.recipes[var] for var in entries if var != _PRODUCT)

    # -- the whole page ---------------------------------------------------------------------------

    def solve(self) -> SolvedPage:
        collection = _Collection()
        for product in self.page.products:
            if product.amount > 0:
                collection.inputs[product.goods_id] = {_PRODUCT: -product.amount}
            else:
                collection.outputs[product.goods_id] = {_PRODUCT: product.amount}
        self._link_group(self.page.root, collection)
        rows = list(self.rows.values())
        try:
            runs = lp.minimise(
                [Fraction(1)] * len(self.recipes),
                [row.coefficients for row in rows],
                [row.rhs for row in rows],
            )
        except lp.InfeasibleError as error:
            raise InfeasiblePlanError([rows[i].description for i in error.rows]) from error
        for solved, value in zip(self.recipes, runs, strict=True):
            solved.runs_per_minute = value
            gt = solved.recipe.gt
            if solved.timed and gt is not None:
                minutes = Fraction(gt.duration_ticks, TICKS_PER_MINUTE)
                solved.crafter_count = solved.runs_per_minute * minutes / solved.overclock_factor
        inputs = [
            External(goods_id, *self._boundary(entries))
            for table in (collection.inputs, collection.oredict_inputs)
            for goods_id, entries in table.items()
        ]
        outputs = [
            External(goods_id, *self._boundary(entries))
            for goods_id, entries in collection.outputs.items()
        ]
        for external in inputs:
            if external.product is not None:
                warnings.warn(
                    f"the plan asks for {-external.product} per minute of {external.goods_id}, but "
                    f"no recipe in it makes that where the plan can link it",
                    ConversionWarning,
                    stacklevel=3,
                )
        return SolvedPage(self.page, self.recipes, list(self.links.values()), inputs, outputs)

    def _boundary(self, entries: _Entries) -> tuple[tuple[SolvedRecipe, ...], Fraction | None]:
        recipes = tuple(self.recipes[var] for var in entries if var != _PRODUCT)
        return recipes, entries.get(_PRODUCT)


def solve(page: Page, repo: Repository) -> SolvedPage:
    """Solve ``page`` against ``repo``. See the module docstring."""
    return _Solver(page, repo).solve()


__all__ = [
    "TICKS_PER_MINUTE",
    "TIER_NAMES",
    "VOLTAGES",
    "External",
    "Flow",
    "Link",
    "SolvedPage",
    "SolvedRecipe",
    "flows",
    "solve",
    "validate_choices",
]
