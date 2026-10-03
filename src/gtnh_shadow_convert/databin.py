"""Reader for the calculator's ``data.bin``, format version 7.

A port of ``src/repository.ts`` from ShadowTheAge/gtnh @ af8c798 (MIT); the writer it mirrors is
that repo's ``export/MemoryMappedPackConverter.cs``. The file is gzip over one flat array of
little-endian int32s, and everything in it is an index into that same array::

    [0] DATA_VERSION   [1] items   [2] fluids   [3] ore dicts   [4] recipe types
    [5] recipes        [6] service items         [7] recipe remaps        (each points to a slice)

    pointer  an int32 index into the array; -1 is null
    slice    [count, element, element, ...]          (an element is a pointer or a plain int)
    string   [byte length, utf-8 bytes packed four to an int]
    double   two ints, low word first

Objects are read lazily and cached by pointer, as the app does, so one pointer is always one Python
object and identity comparisons (is this crafter one of the type's multiblocks?) mean what they do
there. Only the fields the converter uses are exposed.

The remap table carries recipe ids from older exports: a plan saved against an earlier import still
names its recipes by their old ids, and :meth:`Repository.recipe` resolves those the way the app
does.
"""

from __future__ import annotations

import gzip
import html
import re
import struct
import sys
import zlib
from array import array
from collections import Counter
from enum import IntEnum
from fractions import Fraction
from pathlib import Path

from .errors import DataError, UnsupportedDataVersionError

#: The only ``data.bin`` format this reader understands (``repository.ts`` ``DATA_VERSION``).
DATA_VERSION = 7

_GZIP_MAGIC = b"\x1f\x8b"
_TAG = re.compile(r"<[^>]+>")


class IoType(IntEnum):
    """What a recipe slot is (``RecipeIoType``); the value is what the file stores."""

    ITEM_INPUT = 0
    OREDICT_INPUT = 1
    FLUID_INPUT = 2
    ITEM_OUTPUT = 3
    FLUID_OUTPUT = 4

    @property
    def is_output(self) -> bool:
        return self in (IoType.ITEM_OUTPUT, IoType.FLUID_OUTPUT)


def plain_text(name: str) -> str:
    """A name as text. The export stores names as HTML (Minecraft colour codes become spans, and
    ``&`` an entity), which is what the machine rules match on, so it is kept that way and only
    turned into text for display."""
    return html.unescape(_TAG.sub("", name.replace("<br>", " ")))


class _Object:
    """Something that lives at a pointer in the array (``MemMappedObject``)."""

    __slots__ = ("_repo", "pointer")

    def __init__(self, repo: Repository, pointer: int) -> None:
        self._repo = repo
        self.pointer = pointer

    def _int(self, offset: int) -> int:
        return self._repo.int_at(self.pointer + offset)

    def _string(self, offset: int) -> str | None:
        return self._repo.string(self._int(offset))

    def _slice(self, offset: int) -> list[int]:
        return self._repo.slice(self._int(offset))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} @{self.pointer}>"


class _Searchable(_Object):
    """An object with an id (``SearchableObject``): ints 0-3 are a search index, 4 is the id."""

    __slots__ = ()

    @property
    def id(self) -> str:
        return self._string(4) or ""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id}>"


class Goods(_Searchable):
    """An item or a fluid (``Goods``)."""

    __slots__ = ()

    @property
    def name(self) -> str:
        """The display name as the export stores it: HTML. Rules compare against this."""
        return self._string(5) or ""

    @property
    def display_name(self) -> str:
        return plain_text(self.name)

    @property
    def mod(self) -> str:
        return self._string(6) or ""

    @property
    def internal_name(self) -> str:
        return self._string(7) or ""

    @property
    def unlocalized_name(self) -> str:
        return self._string(11) or ""

    @property
    def nbt(self) -> str | None:
        return self._string(12)


#: Tier names as a single block's tooltip spells them, LV first (``export/VoltageTiers.cs``).
_TOOLTIP_TIERS = (
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
)


class Item(Goods):
    """An item (``Item``); a filled container also names its fluid and its empty form."""

    __slots__ = ()

    @property
    def tooltip(self) -> list[str]:
        """The tooltip's lines, as HTML."""
        return [self._repo.string(pointer) or "" for pointer in self._slice(10)]

    @property
    def single_block_tier(self) -> int | None:
        """The voltage tier of a GregTech single block (0 is LV), read off its tooltip's
        "Voltage IN: 32 (LV)" line as the export's ``GetSingleBlockVoltageTier`` does; ``None``
        for anything else, multiblock controllers included."""
        line = next((text for text in self.tooltip if "Voltage IN" in text), None)
        if line is None:
            return None
        text = plain_text(line)
        return next((tier for tier, name in enumerate(_TOOLTIP_TIERS) if f"({name})" in text), None)

    @property
    def damage(self) -> int:
        return self._int(16)

    @property
    def container(self) -> FluidContainer | None:
        pointer = self._int(17)
        return None if pointer == -1 else self._repo.container_at(pointer)


class Fluid(Goods):
    """A fluid (``Fluid``)."""

    __slots__ = ()

    @property
    def is_gas(self) -> bool:
        return self._int(15) == 1


class FluidContainer(_Object):
    """What a filled container holds, and what is left of it once emptied."""

    __slots__ = ()

    @property
    def fluid(self) -> Fluid:
        return self._repo.fluid_at(self._int(0))

    @property
    def amount(self) -> int:
        return self._int(1)

    @property
    def empty(self) -> Item:
        return self._repo.item_at(self._int(2))


class OreDict(_Searchable):
    """An ore-dictionary input (``OreDict``): any one of its items will do."""

    __slots__ = ()

    @property
    def items(self) -> list[Item]:
        return [self._repo.item_at(pointer) for pointer in self._slice(5)]


class RecipeType(_Object):
    """A recipe map and the machines that run it (``RecipeType``).

    ``singleblocks`` is indexed by voltage tier (0 is LV) and has ``None`` where no block of that
    tier exists; ``multiblocks`` are the controllers, in the export's order.
    """

    __slots__ = ()

    @property
    def name(self) -> str:
        return self._string(0) or ""

    @property
    def category(self) -> str:
        return self._string(1) or ""

    @property
    def multiblocks(self) -> list[Item]:
        return [self._repo.item_at(pointer) for pointer in self._slice(3)]

    @property
    def singleblocks(self) -> list[Item | None]:
        return [
            None if pointer == -1 else self._repo.item_at(pointer) for pointer in self._slice(5)
        ]

    @property
    def default_crafter(self) -> Item | None:
        pointer = self._int(6)
        return None if pointer == -1 else self._repo.item_at(pointer)


class GtRecipe(_Object):
    """A GregTech recipe's machine figures (``GtRecipe``)."""

    __slots__ = ()

    @property
    def voltage(self) -> int:
        """The recipe's EU/t (per amp), not a tier's voltage."""
        return self._int(0)

    @property
    def duration_ticks(self) -> int:
        return self._int(1)

    @property
    def amperage(self) -> int:
        return self._int(2)

    @property
    def voltage_tier(self) -> int:
        return self._int(3)

    @property
    def circuit_conflicts(self) -> int:
        return self._int(5)

    @property
    def special_value(self) -> int:
        return self._int(6)

    @property
    def metadata(self) -> list[tuple[str, float]]:
        return [
            (self._repo.string(self._repo.int_at(pointer)) or "", self._repo.double(pointer + 1))
            for pointer in self._slice(4)
        ]

    def metadata_value(self, key: str, default: float = 0.0) -> float:
        """The first metadata entry named ``key``, else ``default`` (``MetadataByKey``)."""
        for name, value in self.metadata:
            if name == key:
                return value
        return default


class RecipeIo:
    """One slot of a recipe (``RecipeInOut``). Amounts are exact, since rules rescale them."""

    __slots__ = ("amount", "goods", "probability", "slot", "type")

    def __init__(
        self,
        type: IoType,
        goods: Item | Fluid | OreDict,
        slot: int,
        amount: Fraction,
        probability: Fraction,
    ) -> None:
        self.type = type
        self.goods = goods
        self.slot = slot
        self.amount = amount
        self.probability = probability

    def copy(self) -> RecipeIo:
        """An independent copy (``createEditableCopy``), for a rule that edits the slot."""
        return RecipeIo(self.type, self.goods, self.slot, self.amount, self.probability)

    def __repr__(self) -> str:
        return f"<RecipeIo {self.type.name} {self.amount} x {self.goods!r} p={self.probability}>"


class Recipe(_Searchable):
    """A recipe (``Recipe``)."""

    __slots__ = ()

    @property
    def recipe_type(self) -> RecipeType:
        return self._repo.recipe_type_at(self._int(6))

    @property
    def gt(self) -> GtRecipe | None:
        pointer = self._int(7)
        return None if pointer == -1 else self._repo.gt_recipe_at(pointer)

    @property
    def items(self) -> list[RecipeIo]:
        """The slots, inputs before outputs, each as the file lists it.

        A slot is five ints: type, goods pointer, slot, amount, and probability in percent (inputs
        are always 100). Fresh objects each call, so a caller may edit them.
        """
        raw = self._slice(5)
        if len(raw) % 5:
            raise DataError(f"recipe {self.id!r} has a malformed slot list")
        slots: list[RecipeIo] = []
        for index in range(0, len(raw), 5):
            kind, goods_pointer, slot, amount, probability = raw[index : index + 5]
            try:
                io_type = IoType(kind)
            except ValueError as error:
                raise DataError(f"recipe {self.id!r} has a slot of unknown type {kind}") from error
            goods: Item | Fluid | OreDict
            if io_type is IoType.OREDICT_INPUT:
                goods = self._repo.oredict_at(goods_pointer)
            elif io_type in (IoType.FLUID_INPUT, IoType.FLUID_OUTPUT):
                goods = self._repo.fluid_at(goods_pointer)
            else:
                goods = self._repo.item_at(goods_pointer)
            slots.append(
                RecipeIo(io_type, goods, slot, Fraction(amount), Fraction(probability, 100))
            )
        return slots


class Repository:
    """A loaded ``data.bin`` (``Repository``). Build one with :meth:`load` or :meth:`from_bytes`."""

    def __init__(self, raw: bytes) -> None:
        if len(raw) < 32 or len(raw) % 4:
            raise DataError("data.bin is too short or not a whole number of int32s")
        elements = array("i")
        elements.frombytes(raw)
        if sys.byteorder != "little":  # pragma: no cover - no supported platform is big-endian
            elements.byteswap()
        self._raw = raw
        self._e = elements
        self.data_version = elements[0]
        if self.data_version != DATA_VERSION:
            raise UnsupportedDataVersionError(self.data_version, DATA_VERSION)
        self._strings: dict[int, str] = {}
        self._objects: dict[int, _Object] = {}
        self._positions: dict[str, dict[str, int]] = {}
        self._remapped: set[str] = set()
        self._item_names: Counter[tuple[str, str]] | None = None

    @classmethod
    def load(cls, path: str | Path) -> Repository:
        """Read a ``data.bin`` file, gzip-compressed as the app serves it or already unpacked."""
        return cls.from_bytes(Path(path).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> Repository:
        if data[:2] == _GZIP_MAGIC:
            try:
                data = gzip.decompress(data)
            except (OSError, EOFError, zlib.error) as error:
                raise DataError(f"data.bin is not readable gzip: {error}") from error
        return cls(data)

    # -- raw access -------------------------------------------------------------------------------

    def int_at(self, index: int) -> int:
        if not 0 <= index < len(self._e):
            raise DataError(f"data.bin points outside itself (index {index})")
        return self._e[index]

    def slice(self, pointer: int) -> list[int]:
        """The elements of the slice at ``pointer``; an empty list for a null pointer."""
        if pointer == -1:
            return []
        count = self.int_at(pointer)
        if count < 0 or pointer + count >= len(self._e):
            raise DataError(f"data.bin has a slice that overruns it (at {pointer})")
        return self._e[pointer + 1 : pointer + 1 + count].tolist()

    def string(self, pointer: int) -> str | None:
        if pointer == -1:
            return None
        cached = self._strings.get(pointer)
        if cached is not None:
            return cached
        length = self.int_at(pointer)
        begin = (pointer + 1) * 4
        if length < 0 or begin + length > len(self._raw):
            raise DataError(f"data.bin has a string that overruns it (at {pointer})")
        try:
            text = self._raw[begin : begin + length].decode("utf-8")
        except UnicodeDecodeError as error:
            raise DataError(f"data.bin has a string that is not UTF-8 (at {pointer})") from error
        self._strings[pointer] = text
        return text

    def double(self, index: int) -> float:
        self.int_at(index + 1)  # bounds
        value: float = struct.unpack_from("<d", self._raw, index * 4)[0]
        return value

    # -- objects ----------------------------------------------------------------------------------

    def _object[T: _Object](self, pointer: int, kind: type[T]) -> T:
        if pointer == -1:
            raise DataError(f"data.bin has a null where a {kind.__name__} belongs")
        cached = self._objects.get(pointer)
        if cached is None:
            self.int_at(pointer)  # bounds
            cached = self._objects[pointer] = kind(self, pointer)
        if not isinstance(cached, kind):
            raise DataError(f"data.bin uses one object as both {type(cached).__name__} and {kind}")
        return cached

    def item_at(self, pointer: int) -> Item:
        return self._object(pointer, Item)

    def fluid_at(self, pointer: int) -> Fluid:
        return self._object(pointer, Fluid)

    def oredict_at(self, pointer: int) -> OreDict:
        return self._object(pointer, OreDict)

    def container_at(self, pointer: int) -> FluidContainer:
        return self._object(pointer, FluidContainer)

    def recipe_type_at(self, pointer: int) -> RecipeType:
        return self._object(pointer, RecipeType)

    def gt_recipe_at(self, pointer: int) -> GtRecipe:
        return self._object(pointer, GtRecipe)

    def recipe_at(self, pointer: int) -> Recipe:
        return self._object(pointer, Recipe)

    # -- lookup by id -----------------------------------------------------------------------------

    def _table(self, header: int) -> dict[str, int]:
        """Id to pointer for one of the top-level lists, built on first use (it decodes every id
        in the list, which for recipes is most of the file)."""
        key = str(header)
        table = self._positions.get(key)
        if table is None:
            table = {}
            for pointer in self.slice(self.int_at(header)):
                table[self.string(self.int_at(pointer + 4)) or ""] = pointer
            if header == 5:
                # After the recipes, and overriding them, as FillRecipesRemap does.
                for remap in self.slice(self.int_at(7)):
                    old = self.string(self.int_at(remap)) or ""
                    table[old] = self.int_at(remap + 1)
                    self._remapped.add(old)
            self._positions[key] = table
        return table

    def recipe(self, recipe_id: str) -> Recipe | None:
        """The recipe with this id, following the remap table for an id from an older export."""
        pointer = self._table(5).get(recipe_id)
        return None if pointer is None else self.recipe_at(pointer)

    def is_remapped(self, recipe_id: str) -> bool:
        """Whether ``recipe_id`` is an older export's id that the remap table carries forward."""
        self._table(5)
        return recipe_id in self._remapped

    def goods(self, goods_id: str) -> Item | Fluid | OreDict | None:
        """The item (``i:``), fluid (``f:``) or ore dict (``o:``) with this id, or ``None``."""
        if goods_id.startswith("i:"):
            pointer = self._table(1).get(goods_id)
            return None if pointer is None else self.item_at(pointer)
        if goods_id.startswith("f:"):
            pointer = self._table(2).get(goods_id)
            return None if pointer is None else self.fluid_at(pointer)
        if goods_id.startswith("o:"):
            pointer = self._table(3).get(goods_id)
            return None if pointer is None else self.oredict_at(pointer)
        return None

    def items_named(self, mod: str, internal_name: str) -> int:
        """How many items share this registry name, across every damage value and NBT."""
        if self._item_names is None:
            self._item_names = Counter(
                (self.item_at(pointer).mod, self.item_at(pointer).internal_name)
                for pointer in self.slice(self.int_at(1))
            )
        return self._item_names[(mod, internal_name)]
