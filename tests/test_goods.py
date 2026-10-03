from __future__ import annotations

import pytest

from gtnh_shadow_convert.databin import Fluid, Item, OreDict, Repository
from gtnh_shadow_convert.errors import ConversionError
from gtnh_shadow_convert.goods import (
    Resource,
    check_unique,
    fluid_resource,
    goods_resource,
    item_id,
    item_resource,
    oredict_pick,
)
from gtnh_shadow_convert.testing import SyntheticData


@pytest.fixture
def repo() -> Repository:
    data = SyntheticData()
    data.fluid("IC2", "ic2distilledwater", "Distilled Water")
    data.item("IC2", "itemCellEmpty", 0, "Empty Cell")
    data.item("gregtech", "gt.blockmachines", 998, "ExxonMobil Chemical Plant")
    for damage, name in enumerate(["Oak Wood", "Spruce Wood", "Birch Wood", "Jungle Wood"]):
        data.item("minecraft", "log", damage, name)
    data.item("minecraft", "log2", 0, "Acacia Wood")
    data.item("gregtech", "gt.metaitem.01", 2022, "Sulfur Dust")
    data.item("miscutils", "itemDustSulfur", 0, "Sulfur Dust")
    logs = [f"i:minecraft:log:{d}" for d in range(4)]
    data.oredict("o:minecraft:log", logs)
    data.oredict("o:twoLogs", logs[:2])
    data.oredict("o:logWood", [*logs, "i:minecraft:log2:0"])
    data.oredict("o:dustSulfur", ["i:gregtech:gt.metaitem.01:2022", "i:miscutils:itemDustSulfur:0"])
    data.oredict("o:empty", [])
    return Repository.from_bytes(data.to_bytes())


def _get[T](repo: Repository, goods_id: str, kind: type[T]) -> T:
    goods = repo.goods(goods_id)
    assert isinstance(goods, kind)
    return goods


def test_item_id() -> None:
    assert item_id("gregtech", "gt.blockmachines", 998) == "gregtech:gt.blockmachines@998"
    assert item_id("IC2", "itemCellEmpty", 0) == "ic2:itemcellempty"


def test_item_and_fluid_resources(repo: Repository) -> None:
    plant = _get(repo, "i:gregtech:gt.blockmachines:998", Item)
    assert item_resource(plant) == Resource(
        "item", "gregtech:gt.blockmachines@998", "ExxonMobil Chemical Plant"
    )
    water = _get(repo, "f:IC2:ic2distilledwater", Fluid)
    assert fluid_resource(water) == Resource("fluid", "ic2distilledwater", "Distilled Water")
    assert goods_resource(repo, water) == fluid_resource(water)
    assert goods_resource(repo, plant) == item_resource(plant)


def test_oredict_prefers_what_the_plan_makes(repo: Repository) -> None:
    sulfur = _get(repo, "o:dustSulfur", OreDict)
    made = oredict_pick(repo, sulfur, {"i:miscutils:itemDustSulfur:0"})
    assert made.id == "miscutils:itemdustsulfur"
    assert goods_resource(repo, sulfur, {"i:miscutils:itemDustSulfur:0"}) == made


def test_oredict_of_every_damage_is_a_wildcard(repo: Repository) -> None:
    logs = _get(repo, "o:minecraft:log", OreDict)
    assert oredict_pick(repo, logs) == Resource("item", "minecraft:log@32767", "Oak Wood")


def test_oredict_of_some_damages_is_its_first_item(repo: Repository) -> None:
    two = _get(repo, "o:twoLogs", OreDict)
    assert oredict_pick(repo, two).id == "minecraft:log"
    mixed = _get(repo, "o:logWood", OreDict)
    assert oredict_pick(repo, mixed).id == "minecraft:log"
    sulfur = _get(repo, "o:dustSulfur", OreDict)
    assert oredict_pick(repo, sulfur).id == "gregtech:gt.metaitem.01@2022"


def test_empty_oredict(repo: Repository) -> None:
    with pytest.raises(ConversionError, match="lists no items"):
        oredict_pick(repo, _get(repo, "o:empty", OreDict))


def test_check_unique() -> None:
    dust = Resource("item", "gregtech:gt.metaitem.01@2022", "Sulfur Dust")
    check_unique(
        [
            ("i:gregtech:gt.metaitem.01:2022", dust),
            ("o:dustSulfur", dust),
            ("i:gregtech:gt.metaitem.01:2022", dust),
        ]
    )
    with pytest.raises(ConversionError, match="different goods"):
        check_unique([("i:bees:drone:0:aa", dust), ("i:bees:drone:0:bb", dust)])
