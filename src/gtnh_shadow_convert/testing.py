"""Build small synthetic ``data.bin`` files, for tests that must not depend on the real one.

The real file has no license, so neither this package's tests nor a consumer's may commit it. This
writes the same format (``databin``'s layout, as ``MemoryMappedPackConverter.cs`` writes it) from a
handful of declared goods and recipes::

    data = SyntheticData()
    water = data.fluid("minecraft", "water", "Water")
    steam = data.fluid("IC2", "ic2steam", "Steam")
    boiler = data.item("gregtech", "gt.blockmachines", 1000, "Large Boiler")
    boil = data.recipe_type("Boiling", multiblocks=[boiler])
    data.recipe(
        "r~boil",
        boil,
        inputs=[(water, 10)],
        outputs=[(steam, 1600)],
        gt=Gt(voltage=30, duration_ticks=20),
    )
    data.write(tmp_path / "data.bin")

Every method returns the calculator id of what it declared, so the next call can name it. A goods
reference in a recipe is a calculator id: ``i:`` item, ``f:`` fluid, ``o:`` ore dict.
"""

from __future__ import annotations

import gzip
import hashlib
import struct
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .databin import DATA_VERSION, IoType

_Key = tuple[str, str]


@dataclass(frozen=True)
class Gt:
    """A GregTech recipe's figures. ``voltage`` is the recipe's EU/t, ``voltage_tier`` its tier
    (0 is LV)."""

    voltage: int
    duration_ticks: int
    voltage_tier: int = 0
    amperage: int = 1
    special_value: int = 0
    circuit_conflicts: int = 0
    metadata: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Stack:
    """One recipe slot. ``probability`` is in percent, as the file stores it (inputs are 100)."""

    goods: str
    amount: int
    probability: int = 100
    slot: int = 0


StackLike = Stack | tuple[str, int]


@dataclass
class _Item:
    mod: str
    internal_name: str
    damage: int
    name: str
    nbt: str | None
    container: tuple[str, int, str] | None


@dataclass
class _Fluid:
    mod: str
    internal_name: str
    name: str
    gas: bool


@dataclass
class _RecipeType:
    name: str
    category: str
    singleblocks: list[str | None]
    multiblocks: list[str]
    default_crafter: str | None


@dataclass
class _Recipe:
    recipe_type: str
    inputs: list[Stack]
    outputs: list[Stack]
    gt: Gt | None


class SyntheticData:
    """A ``data.bin`` under construction. See the module docstring."""

    def __init__(self) -> None:
        self._items: dict[str, _Item] = {}
        self._fluids: dict[str, _Fluid] = {}
        self._oredicts: dict[str, list[str]] = {}
        self._types: dict[str, _RecipeType] = {}
        self._recipes: dict[str, _Recipe] = {}
        self._remaps: dict[str, str] = {}

    def item(
        self,
        mod: str,
        internal_name: str,
        damage: int = 0,
        name: str | None = None,
        *,
        nbt: str | None = None,
        container: tuple[str, int, str] | None = None,
    ) -> str:
        """An item. ``container`` makes it a filled container: (fluid id, mB held, empty item id).
        An item with ``nbt`` gets the export's id for it: the SHA-1 of the NBT appended."""
        goods_id = f"i:{mod}:{internal_name}:{damage}"
        if nbt:
            goods_id += ":" + hashlib.sha1(nbt.encode("utf-8")).hexdigest()
        self._items[goods_id] = _Item(
            mod, internal_name, damage, name or internal_name, nbt, container
        )
        return goods_id

    def fluid(
        self, mod: str, internal_name: str, name: str | None = None, *, gas: bool = False
    ) -> str:
        goods_id = f"f:{mod}:{internal_name}"
        self._fluids[goods_id] = _Fluid(mod, internal_name, name or internal_name, gas)
        return goods_id

    def oredict(self, oredict_id: str, items: Sequence[str]) -> str:
        """An ore dict. ``oredict_id`` is its full id (``o:dustSulfur``); ``items`` are item ids."""
        self._oredicts[oredict_id] = list(items)
        return oredict_id

    def recipe_type(
        self,
        name: str,
        *,
        singleblocks: Sequence[str | None] = (),
        multiblocks: Sequence[str] = (),
        default_crafter: str | None = None,
        category: str = "gregtech",
    ) -> str:
        """A recipe map. ``singleblocks`` is indexed by tier (0 is LV), ``None`` where none exists.
        The default crafter defaults as the export picks it: the first single block, else the first
        multiblock."""
        if default_crafter is None:
            default_crafter = next(
                (block for block in singleblocks if block is not None),
                multiblocks[0] if multiblocks else None,
            )
        self._types[name] = _RecipeType(
            name, category, list(singleblocks), list(multiblocks), default_crafter
        )
        return name

    def recipe(
        self,
        recipe_id: str,
        recipe_type: str,
        *,
        inputs: Iterable[StackLike] = (),
        outputs: Iterable[StackLike] = (),
        gt: Gt | None = None,
    ) -> str:
        self._recipes[recipe_id] = _Recipe(
            recipe_type, [_stack(s) for s in inputs], [_stack(s) for s in outputs], gt
        )
        return recipe_id

    def remap(self, old_id: str, new_id: str) -> None:
        """Make ``old_id`` (an older export's recipe id) resolve to ``new_id``."""
        self._remaps[old_id] = new_id

    def to_bytes(self, *, compress: bool = True, data_version: int = DATA_VERSION) -> bytes:
        raw = _Writer(self, data_version).build()
        return gzip.compress(raw, mtime=0) if compress else raw

    def write(self, path: str | Path, *, compress: bool = True) -> Path:
        target = Path(path)
        target.write_bytes(self.to_bytes(compress=compress))
        return target


def _stack(value: StackLike) -> Stack:
    return value if isinstance(value, Stack) else Stack(value[0], value[1])


class _Writer:
    """Lays the declared objects out the way the export does: records, then the slices and strings
    they point to, every reference patched once everything has a position."""

    def __init__(self, data: SyntheticData, data_version: int) -> None:
        self.data = data
        self.ints: list[int] = [data_version]
        self.fixups: list[tuple[int, _Key]] = []
        self.positions: dict[_Key, int] = {}
        self.queue: list[tuple[_Key, Callable[[], None]]] = []
        self.strings: dict[str, int] = {}
        self.blobs = 0

    # -- primitives -------------------------------------------------------------------------------

    def ref(self, key: _Key | None) -> None:
        if key is not None:
            self.fixups.append((len(self.ints), key))
        self.ints.append(-1)

    def string(self, text: str | None) -> None:
        self.ref(("str", text) if text else None)

    def slice_of(self, values: Sequence[int | _Key | None]) -> _Key:
        """Queue a slice; elements are plain ints, references, or ``None`` for a null."""
        self.blobs += 1
        key = ("blob", str(self.blobs))

        def write() -> None:
            self.ints.append(len(values))
            for value in values:
                if isinstance(value, int):
                    self.ints.append(value)
                else:
                    self.ref(value)

        self.queue.append((key, write))
        return key

    def record(self, key: _Key, write: Callable[[], None]) -> _Key:
        if key not in self.positions and all(queued != key for queued, _ in self.queue):
            self.queue.append((key, write))
        return key

    # -- records ----------------------------------------------------------------------------------

    def searchable(self, goods_id: str) -> None:
        self.ints.extend((0, 0, 0, 0))  # the search index, which nothing here reads
        self.string(goods_id)

    def goods(
        self, goods_id: str, name: str, mod: str, internal_name: str, nbt: str | None
    ) -> None:
        self.searchable(goods_id)
        self.string(name)
        self.string(mod)
        self.string(internal_name)
        self.ints.extend((0, 0))  # numeric id, icon id
        self.ref(self.slice_of([]))  # tooltip
        self.string(internal_name)  # unlocalized name
        self.string(nbt)
        self.ref(self.slice_of([]))  # production
        self.ref(self.slice_of([]))  # consumption

    def item_key(self, goods_id: str) -> _Key:
        item = self.data._items[goods_id]

        def write() -> None:
            self.goods(goods_id, item.name, item.mod, item.internal_name, item.nbt)
            self.ints.extend((64, item.damage))
            self.ref(
                None if item.container is None else self.container_key(goods_id, item.container)
            )

        return self.record(("item", goods_id), write)

    def container_key(self, goods_id: str, container: tuple[str, int, str]) -> _Key:
        fluid, amount, empty = container

        def write() -> None:
            self.ref(self.fluid_key(fluid))
            self.ints.append(amount)
            self.ref(self.item_key(empty))

        return self.record(("container", goods_id), write)

    def fluid_key(self, goods_id: str) -> _Key:
        fluid = self.data._fluids[goods_id]

        def write() -> None:
            self.goods(goods_id, fluid.name, fluid.mod, fluid.internal_name, None)
            self.ints.append(1 if fluid.gas else 0)
            self.ref(self.slice_of([]))  # containers

        return self.record(("fluid", goods_id), write)

    def oredict_key(self, oredict_id: str) -> _Key:
        def write() -> None:
            self.searchable(oredict_id)
            self.ref(self.slice_of([self.item_key(i) for i in self.data._oredicts[oredict_id]]))

        return self.record(("oredict", oredict_id), write)

    def goods_key(self, goods_id: str) -> _Key:
        data = self.data
        if goods_id not in (*data._items, *data._fluids, *data._oredicts):
            raise ValueError(f"{goods_id!r} is used in a recipe but was never declared")
        if goods_id.startswith("f:"):
            return self.fluid_key(goods_id)
        if goods_id.startswith("o:"):
            return self.oredict_key(goods_id)
        return self.item_key(goods_id)

    def type_key(self, name: str) -> _Key:
        recipe_type = self.data._types[name]

        def write() -> None:
            self.string(recipe_type.name)
            self.string(recipe_type.category)
            self.ref(self.slice_of([0] * 8))  # slot grid dimensions, display only
            self.ref(self.slice_of([self.item_key(i) for i in recipe_type.multiblocks]))
            self.ints.append(0)  # shapeless
            self.ref(
                self.slice_of(
                    [None if i is None else self.item_key(i) for i in recipe_type.singleblocks]
                )
            )
            crafter = recipe_type.default_crafter
            self.ref(None if crafter is None else self.item_key(crafter))

        return self.record(("type", name), write)

    def gt_key(self, recipe_id: str, gt: Gt) -> _Key:
        def write() -> None:
            self.ints.extend((gt.voltage, gt.duration_ticks, gt.amperage, gt.voltage_tier))
            self.ref(
                self.slice_of(
                    [self.metadata_key(recipe_id, key, value) for key, value in gt.metadata.items()]
                )
            )
            self.ints.extend((gt.circuit_conflicts, gt.special_value))

        return self.record(("gt", recipe_id), write)

    def metadata_key(self, recipe_id: str, key: str, value: float) -> _Key:
        def write() -> None:
            self.string(key)
            low, high = struct.unpack("<ii", struct.pack("<d", value))
            self.ints.extend((low, high))

        return self.record(("meta", f"{recipe_id}/{key}"), write)

    def recipe_key(self, recipe_id: str) -> _Key:
        recipe = self.data._recipes[recipe_id]

        def write() -> None:
            self.searchable(recipe_id)
            slots: list[int | _Key | None] = []
            ordered = sorted(
                [(_input_type(s.goods), s) for s in recipe.inputs]
                + [(_output_type(s.goods), s) for s in recipe.outputs],
                key=lambda pair: pair[0],
            )
            for io_type, stack in ordered:
                probability = 100 if io_type < IoType.ITEM_OUTPUT else stack.probability
                slots.extend(
                    (
                        int(io_type),
                        self.goods_key(stack.goods),
                        stack.slot,
                        stack.amount,
                        probability,
                    )
                )
            self.ref(self.slice_of(slots))
            self.ref(self.type_key(recipe.recipe_type))
            self.ref(None if recipe.gt is None else self.gt_key(recipe_id, recipe.gt))

        return self.record(("recipe", recipe_id), write)

    def remap_key(self, old_id: str) -> _Key:
        def write() -> None:
            self.string(old_id)
            self.ref(self.recipe_key(self.data._remaps[old_id]))

        return self.record(("remap", old_id), write)

    # -- assembly ---------------------------------------------------------------------------------

    def build(self) -> bytes:
        data = self.data
        self.ref(self.slice_of([self.item_key(i) for i in data._items]))
        self.ref(self.slice_of([self.fluid_key(f) for f in data._fluids]))
        self.ref(self.slice_of([self.oredict_key(o) for o in data._oredicts]))
        self.ref(self.slice_of([self.type_key(t) for t in data._types]))
        self.ref(self.slice_of([self.recipe_key(r) for r in data._recipes]))
        self.ref(self.slice_of([]))  # service items
        self.ref(self.slice_of([self.remap_key(r) for r in data._remaps]))
        while self.queue:  # record() never queues a key twice
            key, write = self.queue.pop(0)
            self.positions[key] = len(self.ints)
            write()
        for index, key in self.fixups:
            if key[0] == "str":
                self.ints[index] = self._string_at(key[1])
            else:
                self.ints[index] = self.positions[key]
        return struct.pack(f"<{len(self.ints)}i", *self.ints)

    def _string_at(self, text: str) -> int:
        position = self.strings.get(text)
        if position is None:
            encoded = text.encode("utf-8")
            position = self.strings[text] = len(self.ints)
            self.ints.append(len(encoded))
            padded = encoded + b"\0" * (-len(encoded) % 4)
            self.ints.extend(struct.unpack(f"<{len(padded) // 4}i", padded))
        return position


def _input_type(goods_id: str) -> IoType:
    if goods_id.startswith("f:"):
        return IoType.FLUID_INPUT
    if goods_id.startswith("o:"):
        return IoType.OREDICT_INPUT
    return IoType.ITEM_INPUT


def _output_type(goods_id: str) -> IoType:
    return IoType.FLUID_OUTPUT if goods_id.startswith("f:") else IoType.ITEM_OUTPUT
