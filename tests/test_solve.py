from __future__ import annotations

import warnings
from collections.abc import Iterator, Mapping
from fractions import Fraction
from typing import Any

import pytest

from gtnh_shadow_convert.databin import Fluid, Item, Repository
from gtnh_shadow_convert.errors import (
    ConversionError,
    ConversionWarning,
    InfeasiblePlanError,
    MalformedPlanError,
    UnknownRecipeError,
    UnsupportedMachineError,
)
from gtnh_shadow_convert.machines import (
    MACHINES,
    Choice,
    Machine,
    RecipeContext,
    StandardOverclocker,
)
from gtnh_shadow_convert.page import parse_page
from gtnh_shadow_convert.solve import (
    TIER_NAMES,
    VOLTAGES,
    SolvedPage,
    SolvedRecipe,
    flows,
    solve,
    validate_choices,
)
from gtnh_shadow_convert.testing import Gt, Stack, SyntheticData

F = Fraction

WATER = "f:minecraft:water"
HYDROGEN = "f:gregtech:hydrogen"
OXYGEN = "f:gregtech:oxygen"
STEAM = "f:IC2:ic2steam"
DUST = "i:gregtech:gt.metaitem.01:2022"
LOG0 = "i:minecraft:log:0"
LOG1 = "i:minecraft:log:1"
CELL = "i:IC2:itemCellEmpty:0"
WATER_CELL = "i:IC2:itemCellWater:0"
BIG = "i:gregtech:gt.blockmachines:1000"
HUGE = "i:gregtech:gt.blockmachines:1001"


@pytest.fixture
def repo() -> Repository:
    data = SyntheticData()
    for fluid, name in ((WATER, "Water"), (HYDROGEN, "Hydrogen"), (OXYGEN, "Oxygen")):
        mod, internal = fluid[2:].split(":")
        data.fluid(mod, internal, name)
    data.fluid("IC2", "ic2steam", "Steam", gas=True)
    data.item("gregtech", "gt.metaitem.01", 2022, "Sulfur Dust")
    data.item("minecraft", "log", 0, "Oak Wood")
    data.item("minecraft", "log", 1, "Spruce Wood")
    data.item("IC2", "itemCellEmpty", 0, "Empty Cell")
    data.item("IC2", "itemCellWater", 0, "Water Cell", container=(WATER, 1000, CELL))
    data.item("gregtech", "gt.integrated_circuit", 1, "Programmed Circuit")
    data.oredict("o:dustSulfur", [DUST])
    data.oredict("o:minecraft:log", [LOG0, LOG1])
    lv = data.item("gregtech", "gt.blockmachines", 401, "Basic Electrolyzer")
    mv = data.item("gregtech", "gt.blockmachines", 402, "Advanced Electrolyzer")
    data.item("gregtech", "gt.blockmachines", 1000, "Big Machine")
    data.item("gregtech", "gt.blockmachines", 1001, "Huge Machine")
    data.recipe_type("Electrolyzer", singleblocks=[lv, mv])
    data.recipe_type("Big", multiblocks=[BIG, HUGE])
    data.recipe_type("Mixed", singleblocks=[lv], multiblocks=[BIG])
    data.recipe_type("Bare")
    data.recipe(
        "r~split",
        "Electrolyzer",
        inputs=[(WATER, 3000)],
        outputs=[(HYDROGEN, 2000), (OXYGEN, 1000)],
        gt=Gt(voltage=30, duration_ticks=100, voltage_tier=0),
    )
    data.recipe(
        "r~boil",
        "Electrolyzer",
        inputs=[(HYDROGEN, 1000), ("i:gregtech:gt.integrated_circuit:1", 0)],
        outputs=[(STEAM, 500)],
        gt=Gt(voltage=30, duration_ticks=40, voltage_tier=0),
    )
    data.recipe(
        "r~logs",
        "Electrolyzer",
        inputs=[(WATER, 100)],
        outputs=[Stack(LOG1, 4, probability=50)],
        gt=Gt(voltage=8, duration_ticks=20),
    )
    data.recipe(
        "r~burn",
        "Electrolyzer",
        inputs=[("o:minecraft:log", 2)],
        outputs=[(STEAM, 100)],
        gt=Gt(voltage=8, duration_ticks=20),
    )
    data.recipe(
        "r~sulfur",
        "Electrolyzer",
        inputs=[("o:dustSulfur", 1)],
        outputs=[(OXYGEN, 10)],
        gt=Gt(voltage=8, duration_ticks=20),
    )
    data.recipe(
        "r~fill",
        "Electrolyzer",
        inputs=[(WATER_CELL, 2)],
        outputs=[(STEAM, 10)],
        gt=Gt(voltage=8, duration_ticks=20),
    )
    data.recipe(
        "r~pump",
        "Electrolyzer",
        inputs=[(CELL, 1)],
        outputs=[(WATER_CELL, 1)],
        gt=Gt(voltage=8, duration_ticks=20),
    )
    data.recipe(
        "r~big",
        "Big",
        inputs=[(WATER, 1000)],
        outputs=[(STEAM, 1000)],
        gt=Gt(voltage=30, duration_ticks=100, voltage_tier=0),
    )
    data.recipe(
        "r~mixed",
        "Mixed",
        inputs=[(WATER, 1000)],
        outputs=[(STEAM, 1000)],
        gt=Gt(voltage=30, duration_ticks=100, metadata={"compression_tier": 1.0}),
    )
    data.recipe("r~hand", "Electrolyzer", inputs=[(WATER, 1)], outputs=[(STEAM, 1)])
    data.recipe("r~bighand", "Big", inputs=[(WATER, 1), ("o:dustSulfur", 0)], outputs=[(STEAM, 1)])
    data.recipe("r~bare", "Bare", inputs=[(WATER, 1)], outputs=[(STEAM, 1)], gt=Gt(8, 20))
    data.remap("r~old-split", "r~split")
    return Repository.from_bytes(data.to_bytes())


def _row(recipe_id: str, tier: int = 0, **extra: Any) -> dict[str, Any]:
    return {"type": "recipe", "recipeId": recipe_id, "voltageTier": tier, "choices": {}, **extra}


def _page(
    elements: list[dict[str, Any]],
    products: Mapping[str, float] | None = None,
    links: Mapping[str, int] | None = None,
) -> Any:
    return parse_page(
        {
            "products": [{"goodsId": k, "amount": v} for k, v in (products or {}).items()],
            "rootGroup": {"type": "recipe_group", "links": dict(links or {}), "elements": elements},
        }
    )


def _solve(repo: Repository, *args: Any, **kwargs: Any) -> SolvedPage:
    return solve(_page(*args, **kwargs), repo)


def _by_id(solved: SolvedPage) -> dict[str, SolvedRecipe]:
    return {r.recipe.id: r for r in solved.recipes}


@pytest.fixture
def big_rule() -> Iterator[Machine]:
    rule = Machine(
        StandardOverclocker.only_normal(),
        speed=F(3, 2),
        parallels=4,
        choices={"coil": Choice("Coil", ("a", "b", "c"))},
    )
    MACHINES["Big Machine"] = rule
    yield rule
    del MACHINES["Big Machine"]


def test_a_single_block_chain(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~split", 1), _row("r~boil")], {STEAM: 1000})
    split, boil = solved.recipes
    # 1000 steam/min needs 2 boils/min, which need 2000 H2: one split.
    assert boil.runs_per_minute == 2
    assert split.runs_per_minute == 1
    # The split runs one tier up: OC x1 doubles its speed and power.
    assert (split.overclock_tiers, split.overclock.name) == (1, "OC x1")
    assert (split.overclock_factor, split.power_factor) == (2, 2)
    assert split.crafter_count == F(1) * F(100, 1200) / 2
    assert split.crafter is None
    assert split.single_block is not None
    assert split.single_block.name == "Advanced Electrolyzer"
    assert split.batch_ticks == 50
    assert split.eut_per_parallel == 120
    assert split.parallels == 1
    assert (boil.crafter_count, boil.overclock.name) == (F(2) * F(40, 1200), "")
    link_goods = {link.goods_id: link for link in solved.links}
    assert set(link_goods) == {HYDROGEN, STEAM}
    hydrogen = link_goods[HYDROGEN]
    assert [(r.recipe.id, key) for r, key in hydrogen.consumers] == [("r~boil", HYDROGEN)]
    assert [r.recipe.id for r in hydrogen.producers] == ["r~split"]
    assert link_goods[STEAM].demand == 1000
    assert "in group 'Group'" in hydrogen.description
    assert [(e.goods_id, [r.recipe.id for r in e.recipes]) for e in solved.inputs] == [
        (WATER, ["r~split"])
    ]
    assert [e.goods_id for e in solved.outputs] == [OXYGEN]


def test_remapped_ids_resolve(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~old-split")], {OXYGEN: 1000})
    assert solved.recipes[0].recipe.id == "r~split"


def test_an_ignored_good_crosses_the_group(repo: Repository) -> None:
    inner = {
        "type": "recipe_group",
        "links": {HYDROGEN: 1},
        "elements": [_row("r~split"), _row("r~boil")],
    }
    solved = _solve(repo, [inner], {STEAM: 1000})
    links = {(link.group.path, link.goods_id) for link in solved.links}
    # Ignored inside the group, hydrogen is linked one level up, in the root group.
    assert links == {((), HYDROGEN), ((), STEAM)}


def test_ignored_at_every_level_crosses_the_plan(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~split"), _row("r~boil")], {STEAM: 1000}, {HYDROGEN: 1})
    by_id = _by_id(solved)
    assert by_id["r~split"].runs_per_minute == 0  # nothing demands its hydrogen now
    assert {e.goods_id for e in solved.inputs} == {WATER, HYDROGEN}
    assert {e.goods_id for e in solved.outputs} == {HYDROGEN, OXYGEN}


def test_an_oredict_links_to_the_item_made(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~logs"), _row("r~burn")], {STEAM: 100})
    by_id = _by_id(solved)
    assert by_id["r~burn"].selected_oredicts["o:minecraft:log"].id == LOG1
    (log_link,) = [link for link in solved.links if link.goods_id == LOG1]
    assert [(r.recipe.id, key) for r, key in log_link.consumers] == [("r~burn", "o:minecraft:log")]
    # Two logs a run, from a 50% chance of four: one run of each.
    assert by_id["r~logs"].runs_per_minute == 1


def test_an_ignored_oredict_still_picks_the_item(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~logs"), _row("r~burn")], {STEAM: 100}, {LOG1: 1})
    burn = _by_id(solved)["r~burn"]
    assert burn.selected_oredicts["o:minecraft:log"].id == LOG1
    assert "o:minecraft:log" in {e.goods_id for e in solved.inputs}


def test_an_oredict_nobody_makes_is_an_input(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~sulfur")], {OXYGEN: 10})
    assert [(e.goods_id, len(e.recipes)) for e in solved.inputs] == [("o:dustSulfur", 1)]
    assert solved.recipes[0].selected_oredicts == {}


def test_a_filled_container_splits(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~fill"), _row("r~pump")], {STEAM: 10}, {CELL: 1})
    by_id = _by_id(solved)
    fill = by_id["r~fill"]
    assert [(f.output, f.goods.id, f.amount) for f in fill.flows()] == [
        (False, WATER, 2000),
        (False, CELL, 2),
        (True, STEAM, 10),
    ]
    assert isinstance(fill.flows()[0].goods, Fluid)
    # The pump's water-cell output is 1000 water plus an empty cell; the water links to the fill.
    (water,) = [link for link in solved.links if link.goods_id == WATER]
    assert [r.recipe.id for r in water.producers] == ["r~pump"]
    assert by_id["r~pump"].runs_per_minute == 2


def test_flows_of_a_chanced_output(repo: Repository) -> None:
    logs = repo.recipe("r~logs")
    assert logs is not None
    (_, out) = flows(logs.items)
    assert (out.amount, out.probability, out.expected) == (4, F(1, 2), 2)
    assert isinstance(out.goods, Item)


def test_a_given_product_supplies_its_users(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~boil")], {STEAM: 500, HYDROGEN: -1000})
    (hydrogen,) = [link for link in solved.links if link.goods_id == HYDROGEN]
    assert hydrogen.supply == 1000
    assert hydrogen.producers == []
    assert solved.recipes[0].runs_per_minute == 1


def test_fixed_machine_count(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~split", fixedCrafterCount=3)])
    assert solved.recipes[0].crafter_count == 3


def test_contradictory_counts_are_infeasible(repo: Repository) -> None:
    with pytest.raises(InfeasiblePlanError, match=r"hydrogen|fixed machine count") as caught:
        _solve(repo, [_row("r~split", fixedCrafterCount=1), _row("r~boil", fixedCrafterCount=1)])
    assert caught.value.links


def test_unknown_recipe(repo: Repository) -> None:
    with pytest.raises(UnknownRecipeError):
        _solve(repo, [_row("r~missing")])


def test_a_multiblock_without_a_rule(repo: Repository) -> None:
    with pytest.raises(UnsupportedMachineError, match="'Big Machine'"):
        _solve(repo, [_row("r~big")])


def test_multiblock_rate_math(repo: Repository, big_rule: Machine) -> None:
    # 30 EU/t at HV (512 V): floor(512 / 30) = 17 parallels fit, the rule offers 4. The spare
    # factor 17/4 >= 4 buys one overclock tier of the two the tier difference allows.
    solved = _solve(repo, [_row("r~big", 2, choices={"coil": 9, "junk": 1})])
    big = solved.recipes[0]
    assert big.crafter is not None
    assert big.crafter.name == "Big Machine"
    assert big.single_block is None
    assert big.choices == {"coil": 2}
    assert (big.parallels, big.overclock_tiers, big.overclock.name) == (4, 1, "OC x1")
    # 100 ticks / (2 x 1.5) = 33.3 ticks, rounded down to 33.
    assert big.speed_correction == F(100, 3) / 33
    assert big.overclock_factor == 2 * F(3, 2) * (F(100, 3) / 33) * 4
    assert big.batch_ticks == 33
    assert big.eut_per_parallel == 30 * 2 * 2  # normal OC: x2 power per batch, x2 speed


def test_a_saved_crafter_wins(repo: Repository, big_rule: Machine) -> None:
    solved = _solve(repo, [_row("r~mixed", crafter=BIG), _row("r~split", crafter=BIG)])
    mixed, split = solved.recipes
    assert mixed.crafter is not None
    assert mixed.crafter.id == BIG
    assert split.crafter is None  # BIG cannot run electrolyzer recipes; the save is ignored


def test_an_excluded_single_block_moves_to_a_multiblock(
    repo: Repository, big_rule: Machine
) -> None:
    solved = _solve(repo, [_row("r~mixed")])
    assert solved.recipes[0].crafter is not None


def test_excluded_multiblocks_fall_to_the_default_crafter(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuse = Machine(StandardOverclocker.only_normal(), excludes_recipe=lambda recipe: True)
    monkeypatch.setitem(MACHINES, "Big Machine", refuse)
    monkeypatch.setitem(MACHINES, "Huge Machine", refuse)
    solved = _solve(repo, [_row("r~big")])
    assert solved.recipes[0].crafter is not None
    assert solved.recipes[0].crafter.name == "Big Machine"  # the type's default crafter


def test_the_first_multiblock_that_accepts(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuse = Machine(StandardOverclocker.only_normal(), excludes_recipe=lambda recipe: True)
    monkeypatch.setitem(MACHINES, "Big Machine", refuse)
    monkeypatch.setitem(MACHINES, "Huge Machine", Machine(StandardOverclocker.only_normal()))
    solved = _solve(repo, [_row("r~big")])
    assert solved.recipes[0].crafter is not None
    assert solved.recipes[0].crafter.name == "Huge Machine"


def test_a_recipe_without_a_duration(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~hand")], {STEAM: 5})
    hand = solved.recipes[0]
    assert (hand.runs_per_minute, hand.crafter_count, hand.timed) == (5, 0, False)
    assert hand.batch_ticks == 0
    assert hand.eut_per_parallel == 0


def test_a_multiblock_recipe_without_a_duration_needs_no_rule(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~bighand")], {STEAM: 3})
    hand = solved.recipes[0]
    assert hand.crafter is not None
    assert hand.machine is None
    assert hand.runs_per_minute == 3
    # A zero-amount ore-dict input (a catalyst that is not used up) is never linked.
    assert solved.inputs == [solved.inputs[0]]
    assert solved.inputs[0].goods_id == WATER


def test_an_oredict_used_in_a_child_group(repo: Repository) -> None:
    inner = {"type": "recipe_group", "links": {}, "elements": [_row("r~burn")]}
    solved = _solve(repo, [_row("r~logs"), inner], {STEAM: 100})
    burn = _by_id(solved)["r~burn"]
    assert burn.selected_oredicts["o:minecraft:log"].id == LOG1
    assert [link.group.path for link in solved.links if link.goods_id == LOG1] == [()]


def test_a_type_with_no_machine(repo: Repository) -> None:
    solved = _solve(repo, [_row("r~bare")], {STEAM: 1})
    bare = solved.recipes[0]
    assert bare.crafter is None
    assert bare.single_block is None
    assert bare.crafter_count == F(20, 1200)


def test_running_below_the_recipe_tier_warns(repo: Repository) -> None:
    data = SyntheticData()
    data.recipe_type("T", singleblocks=[data.item("m", "lv", 0, "LV")])
    data.recipe("r~hv", "T", gt=Gt(voltage=480, duration_ticks=20, voltage_tier=2))
    low = Repository.from_bytes(data.to_bytes())
    with pytest.warns(ConversionWarning, match="runs a HV recipe at LV"):
        solved = solve(_page([_row("r~hv", 0)]), low)
    assert solved.recipes[0].overclock_factor == 1


def test_an_unmade_product_warns(repo: Repository) -> None:
    with pytest.warns(ConversionWarning, match="no recipe in it makes"):
        solved = _solve(repo, [_row("r~split")], {STEAM: 5})
    assert [e.product for e in solved.inputs if e.goods_id == STEAM] == [-5]


def test_no_warning_for_a_balanced_plan(repo: Repository) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _solve(repo, [_row("r~split")], {OXYGEN: 1000})


def test_tier_out_of_range(repo: Repository) -> None:
    with pytest.raises(MalformedPlanError, match="voltage tier 25"):
        _solve(repo, [_row("r~split", 25)])


def test_fixed_voltage_tier(repo: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        MACHINES, "Big Machine", Machine(StandardOverclocker.only_normal(), fixed_voltage_tier=5)
    )
    big = _solve(repo, [_row("r~big", 0)]).recipes[0]
    assert big.voltage_tier == 5


def test_unpowered_machine_has_no_parallel_limit(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    steam = Machine(StandardOverclocker.only_normal(), power=F(0), parallels=8)
    monkeypatch.setitem(MACHINES, "Big Machine", steam)
    big = _solve(repo, [_row("r~big", 0)]).recipes[0]
    assert (big.parallels, big.power_factor) == (8, 0)


def test_ignore_parallel_limit_and_round_after(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = Machine(
        StandardOverclocker.only_normal(),
        parallels=64,
        ignore_parallel_limit=True,
        round_after_parallels=True,
    )
    monkeypatch.setitem(MACHINES, "Big Machine", rule)
    big = _solve(repo, [_row("r~big", 0)]).recipes[0]
    assert big.parallels == 64
    # 100 / 64 = 1.5625 ticks per batch, rounded down to 1.
    assert big.speed_correction == F(100, 64)


def test_a_rule_rewrites_the_recipe(repo: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    def double(context: RecipeContext, items: list[Any]) -> list[Any]:
        for slot in items:
            slot.amount *= 2
        return items

    monkeypatch.setitem(
        MACHINES, "Big Machine", Machine(StandardOverclocker.only_normal(), recipe=double)
    )
    big = _solve(repo, [_row("r~big", 0)], {STEAM: 2000}).recipes[0]
    assert big.runs_per_minute == 1


def test_a_rule_with_no_speed(repo: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        MACHINES, "Big Machine", Machine(StandardOverclocker.only_normal(), speed=F(0))
    )
    with pytest.raises(ConversionError, match="no speed"):
        _solve(repo, [_row("r~big", 0)])


def test_validate_choices(repo: Repository) -> None:
    recipe = repo.recipe("r~big")
    assert recipe is not None

    def at_least_one(context: RecipeContext, choices: dict[str, int]) -> None:
        choices["slices"] = max(choices["slices"], context.voltage_tier)

    rule = Machine(
        StandardOverclocker.only_normal(),
        choices={
            "coil": Choice("Coil", ("a", "b")),
            "slices": Choice("Slices", minimum=1, maximum=10),
            "amps": Choice("Amps", minimum=16),
        },
        enforce_choice_constraints=at_least_one,
    )
    assert validate_choices(rule, recipe, 3, {"coil": F(5), "amps": F(100), "x": F(1)}) == {
        "coil": 1,
        "slices": 3,
        "amps": 100,
    }
    assert validate_choices(rule, recipe, 0, {"slices": F(-4)})["slices"] == 1
    assert (
        validate_choices(Machine(StandardOverclocker.only_normal()), recipe, 0, {"a": F(1)}) == {}
    )
    with pytest.raises(MalformedPlanError, match="not a whole number"):
        validate_choices(rule, recipe, 0, {"amps": F(33, 2)})


def test_tier_tables() -> None:
    assert len(VOLTAGES) == len(TIER_NAMES) == 25
    assert (TIER_NAMES[5], VOLTAGES[5]) == ("LuV", 32768)
    assert VOLTAGES[14] == 2147483640 * 4
