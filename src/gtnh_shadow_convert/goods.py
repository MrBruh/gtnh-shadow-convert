"""The calculator's goods ids, spelled the way a gtnh-factory-flow plan spells them.

===========================================  ===============================================
calculator                                   plan
===========================================  ===============================================
``i:gregtech:gt.blockmachines:998``          ``gregtech:gt.blockmachines@998``
``i:minecraft:log:0``                        ``minecraft:log`` (damage 0 is left off)
``i:IC2:itemCellEmpty:0``                    ``ic2:itemcellempty`` (lower case, as both forks)
``f:IC2:ic2distilledwater``                  ``ic2distilledwater`` (a fluid is its bare name)
``o:dustSulfur``, ``o:minecraft:log``        one concrete item, see :func:`oredict_pick`
===========================================  ===============================================

An item is built from its fields rather than by parsing its id, because a registry name may hold a
colon and an item with NBT carries a hash on its id that a plan has no place for. Two items that
differ only in NBT therefore spell the same; :func:`check_unique` refuses a plan where that happens
rather than letting one machine port stand for both.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Literal

from .databin import Fluid, Item, OreDict, Repository
from .errors import ConversionError

#: Forge's ``OreDictionary.WILDCARD_VALUE``: an item id with this damage accepts any damage.
WILDCARD_DAMAGE = 32767


@dataclass(frozen=True)
class Resource:
    """A good as a plan names it."""

    kind: Literal["item", "fluid"]
    id: str
    display_name: str


def item_id(mod: str, internal_name: str, damage: int) -> str:
    """``mod:internal_name@damage``, lower case, with ``@0`` left off."""
    key = f"{mod}:{internal_name}".lower()
    return key if damage == 0 else f"{key}@{damage}"


def item_resource(item: Item) -> Resource:
    return Resource("item", item_id(item.mod, item.internal_name, item.damage), item.display_name)


def fluid_resource(fluid: Fluid) -> Resource:
    return Resource("fluid", fluid.internal_name.lower(), fluid.display_name)


def oredict_pick(repo: Repository, oredict: OreDict, produced: Collection[str] = ()) -> Resource:
    """The one item a plan names for an ore-dict input.

    1. The first of its items that ``produced`` lists (calculator ids): the one the plan makes, which
       is also the one the calculator links the input to.
    2. Else, when its items are every damage value of one registry name and nothing else (the
       export's own test for an unnamed dict, ``OreDict.GenerateId``), that name at the wildcard
       damage: ``minecraft:log@32767``, "any log".
    3. Else its first item.
    """
    items = oredict.items
    if not items:
        raise ConversionError(f"ore dict {oredict.id!r} lists no items")
    for item in items:
        if item.id in produced:
            return item_resource(item)
    first = items[0]
    every_damage = (
        len(items) > 1
        and all(
            (item.mod, item.internal_name) == (first.mod, first.internal_name) for item in items
        )
        and repo.items_named(first.mod, first.internal_name) == len(items)
    )
    if every_damage:
        wildcard = item_id(first.mod, first.internal_name, WILDCARD_DAMAGE)
        return Resource("item", wildcard, first.display_name)
    return item_resource(first)


def goods_resource(
    repo: Repository, goods: Item | Fluid | OreDict, produced: Collection[str] = ()
) -> Resource:
    """Any good as a plan names it; ``produced`` only matters for an ore dict."""
    if isinstance(goods, Fluid):
        return fluid_resource(goods)
    if isinstance(goods, OreDict):
        return oredict_pick(repo, goods, produced)
    return item_resource(goods)


def check_unique(pairs: Iterable[tuple[str, Resource]]) -> None:
    """Refuse two different calculator goods that a plan would spell the same.

    ``pairs`` is (calculator id, resource). An ore dict and the item it resolves to are the same
    good and pass; two items differing only in NBT are not, and fail.
    """
    seen: dict[tuple[str, str], str] = {}
    for source, resource in pairs:
        key = (resource.kind, resource.id)
        other = seen.setdefault(key, source)
        if other != source and not (source.startswith("o:") or other.startswith("o:")):
            raise ConversionError(
                f"{other!r} and {source!r} are different goods, but a plan can only name both "
                f"{resource.id!r}; the converter cannot tell their pipes apart"
            )
