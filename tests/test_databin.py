from __future__ import annotations

import gzip
import struct
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gtnh_shadow_convert.databin import (
    DATA_VERSION,
    Fluid,
    IoType,
    Item,
    OreDict,
    Repository,
    plain_text,
)
from gtnh_shadow_convert.errors import DataError, UnsupportedDataVersionError
from gtnh_shadow_convert.testing import Gt, Stack, SyntheticData


def _sample() -> SyntheticData:
    data = SyntheticData()
    water = data.fluid("minecraft", "water", "Water")
    data.fluid("IC2", "ic2steam", "Steam", gas=True)
    cell = data.item("IC2", "itemCellEmpty", 0, "Empty Cell")
    data.item("IC2", "itemCellWater", 0, "Water Cell", container=(water, 1000, cell))
    data.item("gregtech", "gt.metaitem.01", 2022, '<span class="fmt-e">Sulfur</span> Dust')
    data.item("minecraft", "log", 0, "Oak Wood")
    data.item("minecraft", "log", 1, "Spruce Wood")
    data.item("bees", "drone", 0, "Drone", nbt='{species:"forestry.speciesCommon"}')
    data.oredict("o:dustSulfur", ["i:gregtech:gt.metaitem.01:2022"])
    lv = data.item("gregtech", "gt.blockmachines", 201, "Basic Chemical Reactor")
    hv = data.item("gregtech", "gt.blockmachines", 203, "Advanced Chemical Reactor II")
    lcr = data.item("gregtech", "gt.blockmachines", 1169, "Large Chemical Reactor")
    data.recipe_type("Chemical Reactor", singleblocks=[lv, None, hv], multiblocks=[lcr])
    data.recipe(
        "r~acid",
        "Chemical Reactor",
        inputs=[("o:dustSulfur", 1), (water, 1000), ("i:IC2:itemCellWater:0", 2)],
        outputs=[Stack("i:minecraft:log:1", 3, probability=25, slot=1), ("f:IC2:ic2steam", 160)],
        gt=Gt(
            voltage=30,
            duration_ticks=100,
            voltage_tier=0,
            amperage=2,
            special_value=4,
            circuit_conflicts=1,
            metadata={"coil_heat": 1800.5, "tier": 2.0},
        ),
    )
    data.recipe("r~nogt", "Chemical Reactor", inputs=[(water, 1)])
    data.remap("r~old", "r~acid")
    return data


@pytest.fixture
def repo() -> Repository:
    return Repository.from_bytes(_sample().to_bytes())


def test_reads_back_what_was_written(repo: Repository) -> None:
    assert repo.data_version == DATA_VERSION
    recipe = repo.recipe("r~acid")
    assert recipe is not None
    assert recipe.id == "r~acid"
    kinds = [(io.type, io.goods.id, io.amount, io.probability, io.slot) for io in recipe.items]
    one = Fraction(1)
    assert kinds == [
        (IoType.ITEM_INPUT, "i:IC2:itemCellWater:0", Fraction(2), one, 0),
        (IoType.OREDICT_INPUT, "o:dustSulfur", one, one, 0),
        (IoType.FLUID_INPUT, "f:minecraft:water", Fraction(1000), one, 0),
        (IoType.ITEM_OUTPUT, "i:minecraft:log:1", Fraction(3), Fraction(1, 4), 1),
        (IoType.FLUID_OUTPUT, "f:IC2:ic2steam", Fraction(160), one, 0),
    ]
    assert [io.type.is_output for io in recipe.items] == [False, False, False, True, True]


def test_gt_figures_and_metadata(repo: Repository) -> None:
    recipe = repo.recipe("r~acid")
    assert recipe is not None
    gt = recipe.gt
    assert gt is not None
    assert (gt.voltage, gt.duration_ticks, gt.amperage, gt.voltage_tier) == (30, 100, 2, 0)
    assert (gt.special_value, gt.circuit_conflicts) == (4, 1)
    assert gt.metadata == [("coil_heat", 1800.5), ("tier", 2.0)]
    assert gt.metadata_value("tier") == 2.0
    assert gt.metadata_value("missing") == 0.0
    assert gt.metadata_value("missing", 7.0) == 7.0
    nogt = repo.recipe("r~nogt")
    assert nogt is not None
    assert nogt.gt is None


def test_recipe_type_blocks(repo: Repository) -> None:
    recipe = repo.recipe("r~acid")
    assert recipe is not None
    recipe_type = recipe.recipe_type
    assert recipe_type.name == "Chemical Reactor"
    assert recipe_type.category == "gregtech"
    single = recipe_type.singleblocks
    assert [None if s is None else s.name for s in single] == [
        "Basic Chemical Reactor",
        None,
        "Advanced Chemical Reactor II",
    ]
    assert [m.name for m in recipe_type.multiblocks] == ["Large Chemical Reactor"]
    assert recipe_type.default_crafter is single[0]
    # One pointer is one object, so membership tests are identity tests, as in the app.
    assert recipe_type.multiblocks[0] is repo.goods("i:gregtech:gt.blockmachines:1169")


def test_undeclared_goods_are_refused() -> None:
    data = SyntheticData()
    data.recipe_type("T")
    data.recipe("r~x", "T", inputs=[("i:nope:nope:0", 1)])
    with pytest.raises(ValueError, match="never declared"):
        data.to_bytes()


def test_explicit_default_crafter_and_a_type_with_no_blocks() -> None:
    data = SyntheticData()
    a = data.item("m", "a", 0, "A")
    b = data.item("m", "b", 0, "B")
    data.recipe_type("Picked", multiblocks=[a, b], default_crafter=b)
    data.recipe_type("Bare")
    data.recipe("r~p", "Picked")
    data.recipe("r~b", "Bare")
    repo = Repository.from_bytes(data.to_bytes())
    picked, bare = repo.recipe("r~p"), repo.recipe("r~b")
    assert picked is not None
    assert bare is not None
    assert picked.recipe_type.default_crafter is repo.goods(b)
    assert bare.recipe_type.default_crafter is None
    assert bare.recipe_type.singleblocks == []


def test_goods_fields(repo: Repository) -> None:
    sulfur = repo.goods("i:gregtech:gt.metaitem.01:2022")
    assert isinstance(sulfur, Item)
    assert sulfur.name == '<span class="fmt-e">Sulfur</span> Dust'
    assert sulfur.display_name == "Sulfur Dust"
    assert (sulfur.mod, sulfur.internal_name, sulfur.damage) == ("gregtech", "gt.metaitem.01", 2022)
    assert sulfur.nbt is None
    assert sulfur.container is None
    assert sulfur.unlocalized_name == "gt.metaitem.01"
    steam = repo.goods("f:IC2:ic2steam")
    assert isinstance(steam, Fluid)
    assert steam.is_gas
    water = repo.goods("f:minecraft:water")
    assert isinstance(water, Fluid)
    assert not water.is_gas
    drone = repo.goods(next(i for i in _sample()._items if "drone" in i))
    assert isinstance(drone, Item)
    assert drone.nbt == '{species:"forestry.speciesCommon"}'


def test_container(repo: Repository) -> None:
    cell = repo.goods("i:IC2:itemCellWater:0")
    assert isinstance(cell, Item)
    container = cell.container
    assert container is not None
    assert container.fluid is repo.goods("f:minecraft:water")
    assert container.amount == 1000
    assert container.empty is repo.goods("i:IC2:itemCellEmpty:0")


def test_oredict(repo: Repository) -> None:
    sulfur = repo.goods("o:dustSulfur")
    assert isinstance(sulfur, OreDict)
    assert [item.id for item in sulfur.items] == ["i:gregtech:gt.metaitem.01:2022"]
    assert repr(sulfur) == "<OreDict o:dustSulfur>"


def test_lookup_misses(repo: Repository) -> None:
    assert repo.recipe("r~nope") is None
    assert repo.goods("i:nope:nope:0") is None
    assert repo.goods("f:nope:nope") is None
    assert repo.goods("o:nope") is None
    assert repo.goods("x:nope") is None


def test_remap(repo: Repository) -> None:
    assert repo.recipe("r~old") is repo.recipe("r~acid")
    assert repo.is_remapped("r~old")
    assert not repo.is_remapped("r~acid")


def test_items_named(repo: Repository) -> None:
    assert repo.items_named("minecraft", "log") == 2
    assert repo.items_named("IC2", "itemCellEmpty") == 1
    assert repo.items_named("nope", "nope") == 0


def test_slots_are_fresh_copies(repo: Repository) -> None:
    recipe = repo.recipe("r~acid")
    assert recipe is not None
    first = recipe.items[0]
    first.amount = Fraction(99)
    assert recipe.items[0].amount == 2
    copy = recipe.items[0].copy()
    assert (copy.type, copy.goods, copy.amount) == (
        IoType.ITEM_INPUT,
        recipe.items[0].goods,
        Fraction(2),
    )
    assert "ITEM_INPUT" in repr(copy)


def test_load_from_file_and_uncompressed(tmp_path: Path) -> None:
    path = _sample().write(tmp_path / "data.bin")
    assert Repository.load(path).recipe("r~acid") is not None
    raw = _sample().to_bytes(compress=False)
    assert raw[:2] != b"\x1f\x8b"
    assert Repository.from_bytes(raw).recipe("r~acid") is not None


def test_refuses_other_versions() -> None:
    with pytest.raises(UnsupportedDataVersionError, match="version 8") as caught:
        Repository.from_bytes(_sample().to_bytes(data_version=8))
    assert (caught.value.found, caught.value.supported) == (8, DATA_VERSION)


@pytest.mark.parametrize(
    "blob",
    [
        b"\x1f\x8bnot really gzip",
        b"short",
        b"\x07\x00\x00\x00" * 8 + b"\x01",  # not a whole number of ints
    ],
)
def test_refuses_unreadable_bytes(blob: bytes) -> None:
    with pytest.raises(DataError):
        Repository.from_bytes(blob)


def _header_only(*ints: int) -> Repository:
    return Repository(struct.pack(f"<{len(ints)}i", *ints))


def test_pointer_outside_the_file() -> None:
    repo = _header_only(7, 1000, -1, -1, -1, -1, -1, -1)
    with pytest.raises(DataError, match="outside"):
        repo.goods("i:a:b:0")


def test_slice_overrunning_the_file() -> None:
    repo = _header_only(7, 8, -1, -1, -1, -1, -1, -1, 50)
    with pytest.raises(DataError, match="overruns"):
        repo.goods("i:a:b:0")


def test_string_overrunning_the_file() -> None:
    repo = _header_only(7, -1, -1, -1, -1, -1, -1, -1, 4000)
    with pytest.raises(DataError, match="string"):
        repo.string(8)


def test_string_that_is_not_utf8() -> None:
    raw = struct.pack("<9i", 7, -1, -1, -1, -1, -1, -1, -1, 2) + b"\xff\xfe\x00\x00"
    with pytest.raises(DataError, match="UTF-8"):
        Repository(raw).string(8)


def test_null_string_and_null_object() -> None:
    repo = _header_only(7, -1, -1, -1, -1, -1, -1, -1)
    assert repo.string(-1) is None
    assert repo.slice(-1) == []
    with pytest.raises(DataError, match="null"):
        repo.item_at(-1)


def test_one_pointer_read_as_two_kinds(repo: Repository) -> None:
    item = repo.goods("i:minecraft:log:0")
    assert item is not None
    with pytest.raises(DataError, match="both"):
        repo.fluid_at(item.pointer)


def test_malformed_slot_list() -> None:
    data = SyntheticData()
    data.recipe_type("T")
    data.recipe("r~x", "T")
    repo = Repository.from_bytes(data.to_bytes())
    recipe = repo.recipe("r~x")
    assert recipe is not None
    # Point the slot list at a three-int slice: a slot is five ints.
    repo._e[repo._e[recipe.pointer + 5]] = 3
    with pytest.raises(DataError, match="malformed"):
        _ = recipe.items


def test_unknown_slot_type() -> None:
    data = SyntheticData()
    water = data.fluid("minecraft", "water")
    data.recipe_type("T")
    data.recipe("r~x", "T", inputs=[(water, 1)])
    repo = Repository.from_bytes(data.to_bytes())
    recipe = repo.recipe("r~x")
    assert recipe is not None
    repo._e[repo._e[recipe.pointer + 5] + 1] = 9
    with pytest.raises(DataError, match="unknown type 9"):
        _ = recipe.items


def test_plain_text() -> None:
    assert plain_text('<span class="fmt-c">Hot</span> &amp; Cold') == "Hot & Cold"
    assert plain_text("Line<br>two") == "Line two"


def test_repr_of_unnamed_object(repo: Repository) -> None:
    recipe = repo.recipe("r~acid")
    assert recipe is not None
    assert repr(recipe.recipe_type).startswith("<RecipeType @")


_names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz._0123456789", min_size=1, max_size=12)


@given(
    mod=_names,
    internal=_names,
    damage=st.integers(min_value=0, max_value=32767),
    name=st.text(min_size=1, max_size=20).filter(lambda s: "<" not in s and "&" not in s),
)
def test_any_item_round_trips(mod: str, internal: str, damage: int, name: str) -> None:
    data = SyntheticData()
    goods_id = data.item(mod, internal, damage, name)
    item = Repository.from_bytes(data.to_bytes()).goods(goods_id)
    assert isinstance(item, Item)
    assert (item.mod, item.internal_name, item.damage, item.name) == (mod, internal, damage, name)


def test_real_data_resolves_a_known_recipe(real_data: Path) -> None:
    repo = Repository.load(real_data)
    recipe = repo.recipe("r~lbiMPNCCNS6AdBtSLQ3-gw==")
    assert recipe is not None
    assert recipe.recipe_type.name == "Chemical Plant"
    assert [m.name for m in recipe.recipe_type.multiblocks] == ["ExxonMobil Chemical Plant"]
    gt = recipe.gt
    assert gt is not None
    assert (gt.voltage, gt.duration_ticks, gt.special_value) == (480, 600, 4)
    assert gzip.decompress(real_data.read_bytes())[:4] == struct.pack("<i", DATA_VERSION)
