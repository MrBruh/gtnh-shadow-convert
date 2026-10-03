"""The calculator's saved plan, a ``.gtnh`` file: a port of the model in ``src/page.ts``.

A ``.gtnh`` file is JSON the app writes with ``DownloadCurrentPage``::

    {"name": "...",
     "products": [{"goodsId": "f:miscutils:nitrobenzene", "amount": 5000}],   # per MINUTE
     "rootGroup": {"type": "recipe_group", "name": "Group", "collapsed": false,
                   "links": {"f:minecraft:water": 1},                         # 0 Match, 1 Ignore
                   "elements": [{"type": "recipe", "recipeId": "r~...", "voltageTier": 2,
                                 "choices": {"coilTier": 0}, "crafter": "i:...",
                                 "fixedCrafterCount": 2},
                                {"type": "recipe_group", ...}]},
     "settings": {"minVoltage": 0, "timeUnit": "min"}}

It holds no recipe contents, rates or machine counts; those come from ``data.bin`` and the solver.

A product's ``amount`` is per minute whatever ``timeUnit`` says (the unit only scales what the app
displays), positive for something the plan must make and zero or negative for something it is
given. ``crafter`` and ``fixedCrafterCount`` are absent unless the player set them.

Numbers are read exactly: a whole number becomes an ``int`` and a decimal becomes the
:class:`~fractions.Fraction` of the digits written, so ``0.1`` is one tenth rather than the binary
float nearest it. The LP downstream is exact, and a rate that should be 3 must not come out
2.9999999999999996.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from fractions import Fraction
from pathlib import Path
from typing import Any

from .errors import MalformedPlanError

_TIME_UNITS = ("hour", "min", "sec", "tick")


class LinkAlgorithm(IntEnum):
    """How a group treats a good (``LinkAlgorithm``). Absent from ``links`` means MATCH."""

    MATCH = 0
    IGNORE = 1


@dataclass(frozen=True)
class RecipeElement:
    """One recipe row (``RecipeModel``): which recipe, at which tier, with which machine options.

    ``path`` is where the row sits in the tree (indexes from the root group down), which is unique
    and stable, so it names the row wherever a recipe id alone would not: one recipe can appear in
    a plan twice.
    """

    path: tuple[int, ...]
    recipe_id: str
    voltage_tier: int = 0
    choices: Mapping[str, Fraction] = field(default_factory=dict)
    crafter: str | None = None
    fixed_crafter_count: Fraction | None = None


@dataclass(frozen=True)
class RecipeGroup:
    """A group of rows (``RecipeGroupModel``), which links the goods made and used inside it."""

    path: tuple[int, ...]
    name: str = "Group"
    links: Mapping[str, LinkAlgorithm] = field(default_factory=dict)
    elements: tuple[RecipeElement | RecipeGroup, ...] = ()

    def recipes(self) -> list[RecipeElement]:
        """Every recipe row in this group and below, in the app's order (depth first)."""
        rows: list[RecipeElement] = []
        for element in self.elements:
            if isinstance(element, RecipeElement):
                rows.append(element)
            else:
                rows.extend(element.recipes())
        return rows


@dataclass(frozen=True)
class Product:
    """A target of the plan (``ProductModel``), per minute."""

    goods_id: str
    amount: Fraction


@dataclass(frozen=True)
class Page:
    """A whole plan (``PageModel``)."""

    name: str
    products: tuple[Product, ...]
    root: RecipeGroup
    time_unit: str = "min"


def load_page(path: str | Path) -> Page:
    """Read a ``.gtnh`` file."""
    try:
        data = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_float=Fraction,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise MalformedPlanError(f"{path} is not JSON: {error}") from error
    return parse_page(data)


def parse_page(data: object) -> Page:
    """Build a :class:`Page` from already-parsed JSON. Floats are accepted and read exactly."""
    obj = _object(data, "the plan")
    name = _string(obj.get("name", "New Page"), "name")
    products = tuple(
        _product(entry, f"products[{index}]")
        for index, entry in enumerate(_array(obj.get("products", []), "products"))
    )
    root = _group(obj.get("rootGroup", {}), (), "rootGroup")
    settings = _object(obj.get("settings", {}), "settings")
    time_unit = _string(settings.get("timeUnit", "min"), "settings.timeUnit")
    if time_unit not in _TIME_UNITS:
        raise MalformedPlanError(f"settings.timeUnit is {time_unit!r}, not one of {_TIME_UNITS}")
    return Page(name=name, products=products, root=root, time_unit=time_unit)


def _product(data: object, where: str) -> Product:
    obj = _object(data, where)
    return Product(
        goods_id=_string(obj.get("goodsId", ""), f"{where}.goodsId"),
        amount=_number(obj.get("amount", 1), f"{where}.amount"),
    )


def _group(data: object, path: tuple[int, ...], where: str) -> RecipeGroup:
    obj = _object(data, where)
    links: dict[str, LinkAlgorithm] = {}
    for goods_id, value in _object(obj.get("links", {}), f"{where}.links").items():
        number = _number(value, f"{where}.links[{goods_id!r}]")
        if number not in (0, 1):
            raise MalformedPlanError(
                f"{where}.links[{goods_id!r}] is {value}, not 0 (Match) or 1 (Ignore)"
            )
        links[goods_id] = LinkAlgorithm(int(number))
    elements: list[RecipeElement | RecipeGroup] = []
    for index, child in enumerate(_array(obj.get("elements", []), f"{where}.elements")):
        child_where = f"{where}.elements[{index}]"
        child_path = (*path, index)
        if _object(child, child_where).get("type") == "recipe":
            elements.append(_recipe(child, child_path, child_where))
        else:  # the app reads anything that is not a recipe as a group
            elements.append(_group(child, child_path, child_where))
    return RecipeGroup(
        path=path,
        name=_string(obj.get("name", "Group"), f"{where}.name"),
        links=links,
        elements=tuple(elements),
    )


def _recipe(data: object, path: tuple[int, ...], where: str) -> RecipeElement:
    obj = _object(data, where)
    tier = _number(obj.get("voltageTier", 0), f"{where}.voltageTier")
    if tier.denominator != 1 or tier < 0:
        raise MalformedPlanError(f"{where}.voltageTier is {tier}, not a tier index")
    crafter = obj.get("crafter")
    fixed = obj.get("fixedCrafterCount")
    choices = {
        key: _number(value, f"{where}.choices[{key!r}]")
        for key, value in _object(obj.get("choices", {}), f"{where}.choices").items()
    }
    return RecipeElement(
        path=path,
        recipe_id=_string(obj.get("recipeId", ""), f"{where}.recipeId"),
        voltage_tier=int(tier),
        choices=choices,
        crafter=None if crafter is None else _string(crafter, f"{where}.crafter"),
        fixed_crafter_count=None if fixed is None else _number(fixed, f"{where}.fixedCrafterCount"),
    )


def _object(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MalformedPlanError(f"{where} is not a JSON object")
    return value


def _array(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise MalformedPlanError(f"{where} is not a JSON array")
    return value


def _string(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise MalformedPlanError(f"{where} is not a string")
    return value


def _number(value: object, where: str) -> Fraction:
    """A JSON number, exactly. A float that reached here (from :func:`parse_page`'s caller) is read
    as the shortest decimal that round-trips to it, which is what the app wrote."""
    if isinstance(value, bool) or not isinstance(value, int | float | Fraction):
        raise MalformedPlanError(f"{where} is not a number")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise MalformedPlanError(f"{where} is not a finite number")
        return Fraction(repr(value))
    return Fraction(value)


def _reject_constant(name: str) -> object:
    raise MalformedPlanError(f"the plan contains {name}, which is not a finite number")
