"""The ported machine rules on synthetic recipes. The conformance suite checks them against the app
on real plans; these check every rule evaluates, and pin the formulas that branch."""

from __future__ import annotations

from fractions import Fraction

import pytest

from gtnh_shadow_convert.databin import Item, OreDict, Recipe, RecipeIo, Repository
from gtnh_shadow_convert.errors import ConversionError, ConversionWarning
from gtnh_shadow_convert.machines import (
    LISTED_SINGLE_BLOCK,
    MACHINES,
    Machine,
    RecipeContext,
    chemical_plant,
    coke_oven,
    evaluate,
    rule_for_crafter,
    rules,
)
from gtnh_shadow_convert.solve import validate_choices
from gtnh_shadow_convert.testing import Gt, SyntheticData, voltage_tooltip

F = Fraction
METADATA = {
    "coal_casing_tier": 2.0,
    "nfr_coil_tier": 2.0,
    "defc_casing_tier": 2.0,
    "compression_tier": 1.0,
    "space_elevator_module_tier": 2.0,
    "fusion_threshold": 170_000_000.0,
    "fog_plasma_tier": 0.0,
}


@pytest.fixture(scope="module")
def repo() -> Repository:
    data = SyntheticData()
    water = data.fluid("minecraft", "water", "Water")
    co2 = data.fluid("gregtech", "carbondioxide", "CO2 Gas")
    so2 = data.fluid("gregtech", "sulfurdioxide", "Sulfur Dioxide")
    catalyst = data.item("miscutils", "item.catalyst", 0, "Green Metal Catalyst")
    dust = data.item("gregtech", "gt.metaitem.01", 2022, "Sulfur Dust")
    data.item(
        "gregtech",
        "gt.blockmachines",
        621,
        "Basic Fluid Heater",
        tooltip=[
            "Heating up your Fluids",
            voltage_tooltip("LV"),
        ],
    )
    data.item("gregtech", "gt.blockmachines", 1000, "Electric Blast Furnace", tooltip=["Smelts"])
    for name in ("Generic", "Distillation Tower", "Precise Assembler"):
        data.recipe_type(name)
        data.recipe(
            f"r~{name}",
            name,
            inputs=[(water, 1000), (catalyst, 1), (dust, 2)],
            outputs=[(co2, 1000), (so2, 1000), (water, 10)],
            gt=Gt(voltage=30, duration_ticks=100, special_value=1800, metadata=METADATA),
        )
    data.recipe("r~nogt", "Generic", inputs=[(water, 1)], outputs=[(co2, 1)])
    return Repository.from_bytes(data.to_bytes())


def _name(slot: RecipeIo) -> str:
    return "" if isinstance(slot.goods, OreDict) else slot.goods.name


def _recipe(repo: Repository, recipe_id: str) -> Recipe:
    recipe = repo.recipe(recipe_id)
    assert recipe is not None
    return recipe


def _context(repo: Repository, rule: Machine, tier: int, **choices: int) -> RecipeContext:
    recipe = _recipe(repo, "r~Generic")
    raw = {key: F(value) for key, value in choices.items()}
    return RecipeContext(recipe, tier, validate_choices(rule, recipe, tier, raw))


def _upper_choices(rule: Machine) -> dict[str, int]:
    return {
        key: choice.upper if choice.upper is not None else 64
        for key, choice in rule.choices.items()
    }


@pytest.mark.filterwarnings("ignore::gtnh_shadow_convert.errors.ConversionWarning")
@pytest.mark.parametrize("name", sorted(MACHINES))
@pytest.mark.parametrize("recipe_id", ["r~Generic", "r~Distillation Tower", "r~nogt"])
def test_every_rule_evaluates(repo: Repository, name: str, recipe_id: str) -> None:
    rule = MACHINES[name]
    recipe = _recipe(repo, recipe_id)
    for raw in ({}, _upper_choices(rule)):
        tier = rule.fixed_voltage_tier if rule.fixed_voltage_tier is not None else 3
        choices = validate_choices(rule, recipe, tier, {k: F(v) for k, v in raw.items()})
        context = RecipeContext(recipe, tier, choices)
        result = evaluate(rule.overclocker, context).calculate(context, 2)
        assert result.speed > 0
        assert evaluate(rule.speed, context) > 0
        assert evaluate(rule.power, context) >= 0
        assert evaluate(rule.parallels, context) >= 0
        if rule.recipe is not None:
            assert rule.recipe(context, recipe.items)
        if rule.excludes_recipe is not None:
            rule.excludes_recipe(recipe)


def test_listed_single_blocks(repo: Repository) -> None:
    heater = repo.goods("i:gregtech:gt.blockmachines:621")
    assert isinstance(heater, Item)
    assert heater.single_block_tier == 0
    assert rule_for_crafter(heater) is LISTED_SINGLE_BLOCK
    ebf = repo.goods("i:gregtech:gt.blockmachines:1000")
    assert isinstance(ebf, Item)
    assert ebf.single_block_tier is None
    assert rule_for_crafter(ebf) is MACHINES["Electric Blast Furnace"]


def test_ebf_heat(repo: Repository) -> None:
    rule = MACHINES["Electric Blast Furnace"]
    # Nichrome (3601 K) at HV (+100 K) for an 1800 K recipe: 1901 K spare.
    context = _context(repo, rule, 2, coilTier=2, muffler=4)
    overclock = evaluate(rule.overclocker, context).calculate(context, 2)
    assert overclock.name == "Perfect OC x1, OC x1"
    assert evaluate(rule.power, context) == F(95, 100) ** 2
    assert rule.recipe is not None
    co2, so2 = [
        s
        for s in rule.recipe(context, _recipe(repo, "r~Generic").items)
        if _name(s) in ("CO2 Gas", "Sulfur Dioxide")
    ]
    assert (co2.amount, so2.amount) == (500, 1000)  # only the first pollution gas scales


def test_cold_ebf_warns(repo: Repository) -> None:
    rule = MACHINES["Electric Blast Furnace"]
    data = SyntheticData()
    data.recipe_type("T")
    data.recipe("r~hot", "T", gt=Gt(voltage=30, duration_ticks=100, special_value=9000))
    hot = Repository.from_bytes(data.to_bytes()).recipe("r~hot")
    assert hot is not None
    context = RecipeContext(hot, 0, validate_choices(rule, hot, 0, {}))
    with pytest.warns(ConversionWarning, match="more heat"):
        evaluate(rule.overclocker, context)


def test_volcanus_and_hearth(repo: Repository) -> None:
    volcanus = MACHINES["Volcanus"]
    context = _context(repo, volcanus, 2, coilTier=2)
    assert evaluate(volcanus.power, context) == F(95, 100) ** 2 * F(9, 10)
    assert evaluate(MACHINES["Exothermic Hearth"].parallels, context) == 256


def test_fusion(repo: Repository) -> None:
    assert [rules.fusion_tier_by_startup_cost(c) for c in (1e8, 2e8, 4e8, 1e9, 1e10)] == [
        1,
        2,
        3,
        4,
        5,
    ]
    with pytest.raises(ConversionError, match="beyond every reactor"):
        rules.fusion_tier_by_startup_cost(1e12)
    recipe = _recipe(repo, "r~Generic")
    assert rules.fusion_tier(recipe) == 2
    mark1, mark2 = (
        MACHINES["Fusion Control Computer Mark I"],
        MACHINES["Fusion Control Computer Mark II"],
    )
    assert mark1.excludes_recipe is not None
    assert mark2.excludes_recipe is not None
    assert mark1.excludes_recipe(recipe)
    assert not mark2.excludes_recipe(recipe)
    mark3 = MACHINES["Fusion Control Computer Mark III"]
    context = _context(repo, mark3, rules.TIER_UV)
    assert evaluate(mark3.overclocker, context).calculate(context, 5).name == "2/2 OC x1 (capped)"
    compact = MACHINES["Compact Fusion Computer MK-III"]
    assert evaluate(compact.parallels, context) == 128


def test_arc_furnace_fractional_multiplier(repo: Repository) -> None:
    arc = MACHINES["Industrial Arc Furnace"]
    context = _context(repo, arc, 3, electrode=7)  # Netherite
    result = evaluate(arc.overclocker, context).calculate(context, 2)
    assert (result.name, result.speed) == ("1.5/1.5 OC x2", F(9, 4))


@pytest.mark.parametrize(
    ("amps", "parallels"), [(1, 1), (7, 1), (8, 2), (26, 2), (27, 3), (10**6, 100)]
)
def test_laser_engraver_cube_root(repo: Repository, amps: int, parallels: int) -> None:
    rule = MACHINES["Hyper-Intensity Laser Engraver"]
    assert evaluate(rule.parallels, _context(repo, rule, 3, laserAmperage=amps)) == parallels


def test_coke_oven(repo: Repository) -> None:
    rule = coke_oven.RULE
    assert MACHINES[coke_oven.NAME] is rule
    assert evaluate(rule.parallels, _context(repo, rule, 1, casingType=1, slices=3)) == 64
    assert evaluate(rule.parallels, _context(repo, rule, 1, slices=3)) == 32
    assert _context(repo, rule, 1, slices=40).choices["slices"] == 15
    assert _context(repo, rule, 1, slices=40, coilTier=13).choices["slices"] == 40
    assert evaluate(rule.power, _context(repo, rule, 1)) == F(50, 49)


def test_chemical_plant(repo: Repository) -> None:
    rule = chemical_plant.RULE
    assert MACHINES[chemical_plant.NAME] is rule
    assert rule.recipe is not None
    items = _recipe(repo, "r~Generic").items
    worn = rule.recipe(_context(repo, rule, 2, pipeFluidCasingTier=1), [s.copy() for s in items])
    assert [s.amount for s in worn if _name(s).endswith("Catalyst")] == [F(8, 10) / 50]
    kept = rule.recipe(
        _context(repo, rule, 2, coilTier=10, pipeFluidCasingTier=3), [s.copy() for s in items]
    )
    assert [s.amount for s in kept if _name(s).endswith("Catalyst")] == [1]
    assert evaluate(rule.speed, _context(repo, rule, 2, coilTier=3)) == 2
    assert evaluate(rule.parallels, _context(repo, rule, 2, pipeFluidCasingTier=3)) == 8
    assert chemical_plant.solid_casing_key(4) == "titanium"
    assert chemical_plant.solid_casing_key(0) == "bronze"
    assert chemical_plant.solid_casing_key(99) == "botmium"


def test_a_plant_recipe_without_a_catalyst(repo: Repository) -> None:
    rule = chemical_plant.RULE
    assert rule.recipe is not None
    items = [s for s in _recipe(repo, "r~Generic").items if not _name(s).endswith("Catalyst")]
    assert rule.recipe(_context(repo, rule, 2), items) == items


def test_recipe_type_switches(repo: Repository) -> None:
    dangote = MACHINES["Dangote Distillus"]
    tower = _recipe(repo, "r~Distillation Tower")
    in_tower = RecipeContext(tower, 3, {})
    assert (evaluate(dangote.speed, in_tower), evaluate(dangote.parallels, in_tower)) == (
        F(7, 2),
        12,
    )
    other = RecipeContext(_recipe(repo, "r~Generic"), 3, {})
    assert (evaluate(dangote.speed, other), evaluate(dangote.parallels, other)) == (2, 32)
    precise = MACHINES["Precise Auto-Assembler MT-3662"]
    assert (
        evaluate(
            precise.speed,
            RecipeContext(_recipe(repo, "r~Precise Assembler"), 3, {"precisionTier": 0}),
        )
        == 1
    )
    assert (
        evaluate(precise.speed, RecipeContext(_recipe(repo, "r~Generic"), 3, {"precisionTier": 0}))
        == 2
    )


def test_recipe_minimums(repo: Repository) -> None:
    assert _context(repo, MACHINES["Component Assembly Line"], 3).choices["componentTier"] == 1
    assert _context(repo, MACHINES["Naquadah Fuel Refinery"], 3).choices["coils"] == 1
    assert _context(repo, MACHINES["Draconic Evolution Fusion Crafter"], 3).choices["casings"] == 1


def test_whole_metadata_only() -> None:
    with pytest.raises(ConversionError, match="not a whole number"):
        rules._whole(1.5)


def test_compressor_and_space_excluders(repo: Repository) -> None:
    recipe = _recipe(repo, "r~Generic")
    nogt = _recipe(repo, "r~nogt")
    for name, refused in (
        ("Large Electric Compressor", True),
        ("Hot Isostatic Pressurization Unit", False),
        ("Space Assembler Module MK-I", True),
        ("Space Assembler Module MK-II", False),
    ):
        excludes = MACHINES[name].excludes_recipe
        assert excludes is not None
        assert excludes(recipe) is refused
        assert not excludes(nogt)
