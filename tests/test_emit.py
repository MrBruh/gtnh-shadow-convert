from __future__ import annotations

import json
import math
import warnings
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from gtnh_shadow_convert import SHADOW_COMMIT, convert
from gtnh_shadow_convert.databin import Repository
from gtnh_shadow_convert.emit import DataInfo, _Emitter, emit
from gtnh_shadow_convert.errors import (
    ConversionError,
    ConversionWarning,
    UnsupportedRecipeError,
)
from gtnh_shadow_convert.fetch import KNOWN_DATA, KnownData, file_sha256
from gtnh_shadow_convert.machines import MACHINES, Machine, StandardOverclocker
from gtnh_shadow_convert.page import load_page, parse_page
from gtnh_shadow_convert.solve import solve
from gtnh_shadow_convert.testing import Gt, Stack, SyntheticData, voltage_tooltip

F = Fraction
INFO = DataInfo("ab" * 32, 7, "2.9.0-beta-2")

WATER = "f:minecraft:water"
STEAM = "f:IC2:ic2steam"
ACID = "f:gregtech:sulfuricacid"
CIRCUIT = "i:gregtech:gt.integrated_circuit:1"
LOG0 = "i:minecraft:log:0"
LOG1 = "i:minecraft:log:1"
DUST = "i:gregtech:gt.metaitem.01:2022"
ASH = "i:gregtech:gt.metaitem.01:1815"
PLANT = "i:gregtech:gt.blockmachines:998"
EBF = "i:gregtech:gt.blockmachines:1000"
OVEN = "i:gregtech:gt.blockmachines:15543"
BOILER = "i:gregtech:gt.blockmachines:101"


def _tiered(data: SyntheticData, meta: int, name: str, tier: str) -> str:
    return data.item("gregtech", "gt.blockmachines", meta, name, tooltip=[voltage_tooltip(tier)])


@pytest.fixture(scope="module")
def data() -> SyntheticData:
    data = SyntheticData()
    data.fluid("minecraft", "water", "Water")
    data.fluid("IC2", "ic2steam", "Steam")
    data.fluid("gregtech", "sulfuricacid", "Sulfuric Acid")
    data.item("gregtech", "gt.integrated_circuit", 1, "Programmed Circuit")
    data.item("minecraft", "log", 0, "Oak Wood")
    data.item("minecraft", "log", 1, "Spruce Wood")
    data.item("gregtech", "gt.metaitem.01", 2022, "Sulfur Dust")
    data.item("gregtech", "gt.metaitem.01", 1815, "Ash")
    data.oredict("o:minecraft:log", [LOG0, LOG1])
    data.item("gregtech", "gt.blockmachines", 998, "ExxonMobil Chemical Plant")
    data.item("gregtech", "gt.blockmachines", 15543, "Industrial Coke Oven")
    data.item("gregtech", "gt.blockmachines", 101, "Steam Furnace")
    data.item("gregtech", "gt.blockmachines", 1000, "Electric Blast Furnace")
    heaters = [
        _tiered(data, 621, "Basic Fluid Heater", "LV"),
        _tiered(data, 622, "Advanced Fluid Heater", "MV"),
        _tiered(data, 624, "Advanced Fluid Heater III", "EV"),
    ]
    data.recipe_type("Fluid Heater", multiblocks=heaters)
    single = [data.item("gregtech", "gt.blockmachines", 401, "Basic Boiler"), None]
    data.recipe_type("Boiling", singleblocks=single)
    data.recipe_type("Chemical Plant", multiblocks=[PLANT])
    data.recipe_type("Coke Oven", multiblocks=[OVEN])
    data.recipe_type("Furnace", multiblocks=[BOILER])
    data.recipe_type("Blast Furnace", multiblocks=[EBF])
    data.recipe(
        "r~heat",
        "Fluid Heater",
        inputs=[(WATER, 100), (CIRCUIT, 0)],
        outputs=[(STEAM, 100)],
        gt=Gt(voltage=30, duration_ticks=20),
    )
    data.recipe(
        "r~boil",
        "Boiling",
        inputs=[(WATER, 100)],
        outputs=[(STEAM, 100), Stack(ASH, 1, probability=25)],
        gt=Gt(voltage=8, duration_ticks=20),
    )
    data.recipe(
        "r~acid",
        "Chemical Plant",
        inputs=[(STEAM, 1000), ("o:minecraft:log", 2)],
        outputs=[(ACID, 1000)],
        gt=Gt(voltage=480, duration_ticks=600, voltage_tier=2, special_value=4),
    )
    data.recipe(
        "r~coke",
        "Coke Oven",
        inputs=[(WATER, 10)],
        outputs=[(LOG1, 2)],
        gt=Gt(voltage=96, duration_ticks=256, voltage_tier=1),
    )
    data.recipe(
        "r~steam",
        "Furnace",
        inputs=[(WATER, 10)],
        outputs=[(STEAM, 10)],
        gt=Gt(voltage=4, duration_ticks=100),
    )
    data.recipe("r~craft", "Fluid Heater", inputs=[(WATER, 1)], outputs=[(STEAM, 1)])
    data.recipe(
        "r~blast",
        "Blast Furnace",
        inputs=[(WATER, 1)],
        outputs=[(STEAM, 1)],
        gt=Gt(voltage=120, duration_ticks=400, voltage_tier=1, special_value=1800),
    )
    return data


@pytest.fixture(scope="module")
def repo(data: SyntheticData) -> Repository:
    return Repository.from_bytes(data.to_bytes())


def _row(recipe_id: str, tier: int = 0, **extra: Any) -> dict[str, Any]:
    return {"type": "recipe", "recipeId": recipe_id, "voltageTier": tier, "choices": {}, **extra}


def _plan(
    repo: Repository,
    elements: list[dict[str, Any]],
    products: Mapping[str, float],
    links: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    page = parse_page(
        {
            "name": "Test",
            "products": [{"goodsId": k, "amount": v} for k, v in products.items()],
            "rootGroup": {"type": "recipe_group", "links": dict(links or {}), "elements": elements},
        }
    )
    return emit(solve(page, repo), repo, INFO)


def _by(items: list[dict[str, Any]], key: str = "id") -> dict[str, dict[str, Any]]:
    return {item[key]: item for item in items}


@pytest.fixture
def full(repo: Repository) -> dict[str, Any]:
    elements = [
        _row("r~heat", 1),
        _row("r~acid", 2, choices={"coilTier": 3, "pipeFluidCasingTier": 2}),
        _row("r~coke", 1, choices={"casingType": 1, "slices": 3, "coilTier": 4}),
    ]
    return _plan(repo, elements, {ACID: 1000})


def test_the_plan_shape(full: dict[str, Any]) -> None:
    assert full["schemaVersion"] == 1
    assert full["name"] == "Test"
    assert full["converter"] == {
        "name": "gtnh-shadow-convert",
        "version": full["converter"]["version"],
        "shadowCommit": SHADOW_COMMIT,
        "dataVersion": 7,
        "dataSha256": INFO.sha256,
        "packVersion": "2.9.0-beta-2",
    }
    assert "app" not in full
    assert "resolved" not in full
    ids = [n["id"] for n in full["nodes"]] + [s["id"] for s in full["storages"]]
    assert len(ids) == len(set(ids))
    assert not any("+" in i or "#" in i for i in ids + [e["id"] for e in full["edges"]])
    json.dumps(full)  # plain JSON all the way down


def test_recipe_and_node(full: dict[str, Any]) -> None:
    recipes, nodes = _by(full["recipes"]), _by(full["nodes"])
    plant = nodes["node-1"]
    recipe = recipes[plant["recipeId"]]
    assert recipe["machineType"] == "ExxonMobil Chemical Plant"
    assert recipe["source"]["machineBlock"] == {
        "id": "gregtech:gt.blockmachines@998",
        "displayName": "ExxonMobil Chemical Plant",
    }
    assert recipe["source"]["datasetVersionId"] == "shadow-2.9.0-beta-2"
    assert recipe["source"]["rawRecipeId"] == ""
    assert recipe["machineHandlers"] == [
        {"id": "shadow", "kind": "multiblock", "label": "ExxonMobil Chemical Plant"}
    ]
    (variant,) = recipe["runtimeCalculation"]["variants"]
    assert variant["overclockTier"] == "HV"
    assert variant["coilTier"] == "tpv"
    assert variant["parallel"] == 1
    assert plant["coilTier"] == "tpv"
    assert plant["overclockTier"] == "HV"
    assert plant["machineConfigTiers"] == {"pipeCasing": "titanium", "solidCasing": "titanium"}
    assert (recipe["eut"], recipe["durationTicks"]) == (480, 600)
    coke = nodes["node-2"]
    assert coke["machineConfigTiers"] == {
        "cokeOvenCasing": "heat_proof",
        "cokeOvenSlices": "slice-3",
    }
    assert coke["coilTier"] == "hss_g"
    heater = nodes["node-0"]
    assert "coilTier" not in heater
    assert "machineConfigTiers" not in heater


def test_an_option_that_is_not_part_of_the_build(repo: Repository) -> None:
    plan = _plan(repo, [_row("r~blast", 1, choices={"coilTier": 2, "muffler": 3})], {STEAM: 1})
    node = plan["nodes"][0]
    assert node["coilTier"] == "nichrome"
    assert "machineConfigTiers" not in node  # the muffler hatch is not a build option here


def test_emitter_guards(repo: Repository) -> None:
    page = parse_page(
        {
            "products": [{"goodsId": STEAM, "amount": 1}],
            "rootGroup": {"elements": [_row("r~heat", 0)]},
        }
    )
    emitter = _Emitter(solve(page, repo), repo, INFO)
    with pytest.raises(ConversionError, match="not an item or fluid"):
        emitter.resource("o:minecraft:log")
    with pytest.raises(ConversionError, match="not an item or fluid"):
        emitter.resource("i:nope:nope:0")
    with pytest.raises(ConversionError, match="does not have"):
        emitter.input_resource(emitter.solved.recipes[0], None)
    water = emitter.resource(WATER)
    emitter.edge("node-0", "node-0", water)
    emitter.edge("feed-1", "node-0", water)
    emitter.edge("feed-1", "node-0", water)
    assert len(emitter.edges) == 1


def test_listed_single_block_is_the_one_of_the_row_tier(full: dict[str, Any]) -> None:
    recipes = _by(full["recipes"])
    heater = recipes[_by(full["nodes"])["node-0"]["recipeId"]]
    # The calculator names "Basic Fluid Heater", the first listed, whatever the tier.
    assert heater["machineType"] == "Advanced Fluid Heater"
    assert heater["machineHandlers"][0]["kind"] == "single"
    assert heater["source"]["machineBlock"]["id"] == "gregtech:gt.blockmachines@622"


@pytest.mark.parametrize(
    ("tier", "name"), [(0, "Basic Fluid Heater"), (3, "Advanced Fluid Heater III")]
)
def test_tiered_block_exact(repo: Repository, tier: int, name: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        plan = _plan(repo, [_row("r~heat", tier)], {STEAM: 100})
    assert plan["recipes"][0]["machineType"] == name


def test_tiered_block_missing_warns(repo: Repository) -> None:
    with pytest.warns(
        ConversionWarning,
        match="runs at HV, but no 'Fluid Heater' single block exists at that tier",
    ):
        _plan(repo, [_row("r~heat", 2)], {STEAM: 100})


def test_tiered_block_above(repo: Repository) -> None:
    data = SyntheticData()
    data.fluid("minecraft", "water")
    heater = _tiered(data, 624, "Advanced Fluid Heater III", "EV")
    data.recipe_type("Fluid Heater", multiblocks=[data.item("m", "lv", 0, "Unlisted"), heater])
    data.recipe("r~h", "Fluid Heater", outputs=[(WATER, 1)], gt=Gt(voltage=8, duration_ticks=20))
    local = Repository.from_bytes(data.to_bytes())
    with pytest.warns(ConversionWarning, match="using 'Advanced Fluid Heater III'"):
        plan = _plan(local, [_row("r~h", 0, crafter=heater)], {WATER: 1})
    assert plan["recipes"][0]["machineType"] == "Advanced Fluid Heater III"


def test_a_true_single_block(repo: Repository) -> None:
    plan = _plan(repo, [_row("r~boil", 0)], {STEAM: 100})
    recipe = plan["recipes"][0]
    assert recipe["machineType"] == "Basic Boiler"
    assert recipe["machineHandlers"][0]["kind"] == "single"
    with pytest.raises(UnsupportedRecipeError, match="no machine for that type at MV"):
        _plan(repo, [_row("r~boil", 1)], {STEAM: 100})


def test_a_steam_machine_is_a_single_block(repo: Repository) -> None:
    plan = _plan(repo, [_row("r~steam", 0)], {STEAM: 10})
    recipe = plan["recipes"][0]
    assert recipe["machineHandlers"][0] == {
        "id": "shadow",
        "kind": "single",
        "label": "Steam Furnace",
    }
    assert recipe["runtimeCalculation"]["variants"][0]["eut"] == 0  # steam is not EU


def test_slots(repo: Repository) -> None:
    # A quarter of an ash per boil: asking for a quarter pins the boil at one run a minute.
    plan = _plan(repo, [_row("r~heat", 0), _row("r~boil", 0)], {STEAM: 200, ASH: 0.25})
    heat, boil = plan["recipes"]
    circuit = next(i for i in heat["inputs"] if i["id"] == "gregtech:gt.integrated_circuit@1")
    assert circuit == {
        "kind": "item",
        "id": "gregtech:gt.integrated_circuit@1",
        "amount": 1,
        "displayName": "Programmed Circuit",
        "consumed": False,
    }
    ash = next(o for o in boil["outputs"] if o["kind"] == "item")
    assert (ash["amount"], ash["chance"]) == (1, 0.25)
    assert all("chance" not in o for o in boil["outputs"] if o["kind"] == "fluid")
    # No feed for the circuit: it is not used up.
    assert all(s["resourceId"] != circuit["id"] for s in plan["storages"])


def test_edges_and_storages(full: dict[str, Any]) -> None:
    storages = _by(full["storages"])
    edges = {(e["source"], e["target"], e["resourceId"]) for e in full["edges"]}
    feeds = {s["resourceId"]: i for i, s in storages.items() if i.startswith("feed")}
    drains = {s["resourceId"]: i for i, s in storages.items() if i.startswith("drain")}
    assert ("node-0", "node-1", "ic2steam") in edges
    assert ("node-2", "node-1", "minecraft:log@1") in edges  # the ore dict, linked to what is made
    assert ("node-1", drains["sulfuricacid"], "sulfuricacid") in edges  # the product
    assert (feeds["water"], "node-0", "water") in edges
    assert (feeds["water"], "node-2", "water") in edges
    # Every consumed input of every node is fed by an edge.
    recipes, nodes = _by(full["recipes"]), full["nodes"]
    for node in nodes:
        for slot in recipes[node["recipeId"]]["inputs"]:
            if slot.get("consumed", True):
                assert any(t == node["id"] and r == slot["id"] for _, t, r in edges), slot


def test_the_adapter_arithmetic_covers_the_calculator(repo: Repository) -> None:
    """Per machine, the adapter draws variant.eut x variant.parallel x node.parallel and moves
    amount x node.parallel / duration. Times the machine count, both must cover the solved plan,
    which catches a parallel counted twice or a duration taken before the speed bonus."""
    page = parse_page(
        {
            "products": [{"goodsId": ACID, "amount": 1000}],
            "rootGroup": {
                "elements": [
                    _row("r~heat", 3),
                    _row("r~acid", 3, choices={"coilTier": 6, "pipeFluidCasingTier": 3}),
                    _row("r~coke", 2, choices={"casingType": 1, "slices": 4, "coilTier": 2}),
                ]
            },
        }
    )
    solved = solve(page, repo)
    plan = emit(solved, repo, INFO)
    recipes = _by(plan["recipes"])
    for row, node in zip(solved.recipes, plan["nodes"], strict=True):
        recipe = recipes[node["recipeId"]]
        (variant,) = recipe["runtimeCalculation"]["variants"]
        per_machine_eut = variant["eut"] * variant["parallel"] * node["parallel"]
        gt = row.recipe.gt
        assert gt is not None
        energy = gt.duration_ticks / 1200 * gt.voltage * row.runs_per_minute * row.power_factor
        assert per_machine_eut * node["machineCount"] >= float(energy) * (1 - 1e-9)
        assert node["machineCount"] == max(1, math.ceil(row.crafter_count))
        for slot in recipe["outputs"]:
            per_machine = slot["amount"] * node["parallel"] / variant["durationTicks"] * 1200
            wanted = slot["amount"] * row.runs_per_minute
            assert per_machine * node["machineCount"] >= float(wanted) * (1 - 1e-9)
    assert any(n["parallel"] > 1 for n in plan["nodes"])  # the check exercised parallels


def test_an_ignored_oredict_feeds_the_picked_item(repo: Repository) -> None:
    with pytest.warns(ConversionWarning, match="left out"):  # the coke oven's logs go unused
        plan = _plan(
            repo,
            [_row("r~heat", 0), _row("r~acid", 2), _row("r~coke", 1)],
            {ACID: 1000},
            {LOG1: 1},
        )
    acid = next(r for r in plan["recipes"] if r["machineType"] == "ExxonMobil Chemical Plant")
    assert "minecraft:log@1" in [i["id"] for i in acid["inputs"]]
    feeds = {s["resourceId"] for s in plan["storages"] if s["id"].startswith("feed")}
    assert "minecraft:log@1" in feeds


def test_an_unmade_oredict_is_fed_its_wildcard(repo: Repository) -> None:
    plan = _plan(repo, [_row("r~heat", 0), _row("r~acid", 2)], {ACID: 1000})
    feeds = {s["resourceId"] for s in plan["storages"] if s["id"].startswith("feed")}
    assert "minecraft:log@32767" in feeds


def test_a_given_product_is_a_feed(repo: Repository) -> None:
    plan = _plan(repo, [_row("r~acid", 2)], {ACID: 1000, STEAM: -1000, LOG1: -2})
    feeds = {s["resourceId"]: s["id"] for s in plan["storages"] if s["id"].startswith("feed")}
    edges = {(e["source"], e["target"]) for e in plan["edges"]}
    assert (feeds["ic2steam"], "node-0") in edges


def test_rows_that_never_run_are_left_out(repo: Repository) -> None:
    with pytest.warns(ConversionWarning, match="left out"):
        plan = _plan(repo, [_row("r~heat", 0), _row("r~coke", 1)], {STEAM: 100})
    assert [n["id"] for n in plan["nodes"]] == ["node-0"]
    assert all("node-1" not in (e["source"], e["target"]) for e in plan["edges"])
    assert {s["resourceId"] for s in plan["storages"]} == {"water", "ic2steam"}


def test_a_row_with_no_machine_time(repo: Repository) -> None:
    with pytest.raises(UnsupportedRecipeError, match="no machine time"):
        _plan(repo, [_row("r~craft")], {STEAM: 1})


def test_too_many_machines(repo: Repository) -> None:
    with pytest.raises(ConversionError, match="more than the 1000"):
        _plan(repo, [_row("r~heat", 0)], {STEAM: 10**7})


def test_two_goods_one_name() -> None:
    data = SyntheticData()
    a = data.item("bees", "drone", 0, "Drone A", nbt="{a}")
    b = data.item("bees", "drone", 0, "Drone B", nbt="{b}")
    breeder = _tiered(data, 1, "Breeder", "LV")
    data.recipe_type("Breeding", multiblocks=[breeder])
    data.recipe(
        "r~b", "Breeding", inputs=[(a, 1)], outputs=[(b, 1)], gt=Gt(voltage=8, duration_ticks=20)
    )
    repo = Repository.from_bytes(data.to_bytes())
    with pytest.raises(ConversionError, match="different goods"):
        _plan(repo, [_row("r~b", 0)], {b: 1})


@pytest.fixture
def files(tmp_path: Path, data: SyntheticData) -> tuple[Path, Path]:
    plan = tmp_path / "plan.gtnh"
    plan.write_text(
        json.dumps(
            {
                "name": "P",
                "products": [{"goodsId": STEAM, "amount": 100}],
                "rootGroup": {"elements": [_row("r~heat", 0)]},
            }
        ),
        encoding="utf-8",
    )
    return plan, data.write(tmp_path / "data.bin")


def test_convert_needs_a_pack_for_an_unknown_file(files: tuple[Path, Path]) -> None:
    plan, data_bin = files
    with pytest.raises(ConversionError, match="--pack-version"):
        convert(plan, data_bin)
    converted = convert(plan, data_bin, pack_version="2.9.0-beta-3")
    assert converted["converter"]["packVersion"] == "2.9.0-beta-3"
    assert converted["converter"]["dataSha256"] == file_sha256(data_bin)
    assert converted["recipes"][0]["source"]["datasetVersionId"] == "shadow-2.9.0-beta-3"


def test_convert_knows_a_listed_file(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, data_bin = files
    monkeypatch.setitem(KNOWN_DATA, file_sha256(data_bin), KnownData("9.9.9", 7, "", "", ""))
    assert convert(plan, data_bin)["converter"]["packVersion"] == "9.9.9"


def test_real_nitrobenzene_converts(real_data: Path) -> None:
    plan_path = Path(__file__).parent / "conformance" / "plans" / "Nitrobenzene.gtnh"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plan = convert(plan_path, real_data)
    assert plan["converter"]["packVersion"] == "2.9.0-beta-2"
    assert len(plan["nodes"]) == 7
    kinds = {r["machineHandlers"][0]["kind"] for r in plan["recipes"]}
    assert kinds == {"single", "multiblock"}
    page = load_page(plan_path)
    assert {n["id"] for n in plan["nodes"]} == {
        "node-" + "-".join(map(str, row.path)) for row in page.root.recipes()
    }


def test_unused_machine_rules_are_untouched() -> None:
    # A rule registered by a test elsewhere never leaks into this module's plans.
    assert all(isinstance(rule, Machine) for rule in MACHINES.values())
    assert StandardOverclocker.only_normal().max_normal is None
