from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from gtnh_shadow_convert.errors import MalformedPlanError
from gtnh_shadow_convert.page import (
    LinkAlgorithm,
    RecipeElement,
    RecipeGroup,
    load_page,
    parse_page,
)


def _plan() -> dict[str, Any]:
    return {
        "name": "NB",
        "products": [
            {"goodsId": "f:miscutils:nitrobenzene", "amount": 5000},
            {"goodsId": "f:minecraft:water", "amount": -0.1},
        ],
        "rootGroup": {
            "type": "recipe_group",
            "links": {"f:minecraft:water": 1, "f:gregtech:benzene": 0},
            "elements": [
                {
                    "type": "recipe",
                    "recipeId": "r~a",
                    "voltageTier": 2,
                    "choices": {"coilTier": 0, "pipeFluidCasingTier": 1},
                },
                {
                    "type": "recipe_group",
                    "name": "Inner",
                    "links": {},
                    "elements": [
                        {
                            "type": "recipe",
                            "recipeId": "r~b",
                            "voltageTier": 0,
                            "choices": {},
                            "crafter": "i:gregtech:gt.blockmachines:1169",
                            "fixedCrafterCount": 2.5,
                        }
                    ],
                },
                {"type": "recipe", "recipeId": "r~c", "voltageTier": 1, "choices": {}},
            ],
            "collapsed": False,
            "name": "Group",
        },
        "settings": {"minVoltage": 0, "timeUnit": "sec"},
    }


def test_parses_a_plan() -> None:
    page = parse_page(_plan())
    assert page.name == "NB"
    assert page.time_unit == "sec"
    assert [(p.goods_id, p.amount) for p in page.products] == [
        ("f:miscutils:nitrobenzene", 5000),
        ("f:minecraft:water", Fraction(-1, 10)),
    ]
    root = page.root
    assert root.path == ()
    assert root.links == {
        "f:minecraft:water": LinkAlgorithm.IGNORE,
        "f:gregtech:benzene": LinkAlgorithm.MATCH,
    }
    first, inner, last = root.elements
    assert isinstance(first, RecipeElement)
    assert first.path == (0,)
    assert first.voltage_tier == 2
    assert first.choices == {"coilTier": 0, "pipeFluidCasingTier": 1}
    assert first.crafter is None
    assert first.fixed_crafter_count is None
    assert isinstance(inner, RecipeGroup)
    assert inner.name == "Inner"
    assert inner.path == (1,)
    (nested,) = inner.elements
    assert isinstance(nested, RecipeElement)
    assert nested.path == (1, 0)
    assert nested.crafter == "i:gregtech:gt.blockmachines:1169"
    assert nested.fixed_crafter_count == Fraction(5, 2)
    assert isinstance(last, RecipeElement)
    assert [row.recipe_id for row in root.recipes()] == ["r~a", "r~b", "r~c"]


def test_defaults() -> None:
    page = parse_page({})
    assert page.name == "New Page"
    assert page.products == ()
    assert page.root.elements == ()
    assert page.time_unit == "min"
    row = parse_page({"rootGroup": {"elements": [{"type": "recipe"}]}}).root.elements[0]
    assert isinstance(row, RecipeElement)
    assert (row.recipe_id, row.voltage_tier, dict(row.choices)) == ("", 0, {})
    product = parse_page({"products": [{"goodsId": "i:a:b:0"}]}).products[0]
    assert product.amount == 1


def test_anything_not_a_recipe_is_a_group() -> None:
    page = parse_page({"rootGroup": {"elements": [{"type": "mystery", "elements": []}]}})
    assert isinstance(page.root.elements[0], RecipeGroup)


def test_load_reads_decimals_exactly(tmp_path: Path) -> None:
    path = tmp_path / "plan.gtnh"
    path.write_text(json.dumps(_plan()), encoding="utf-8")
    page = load_page(path)
    assert page.products[1].amount == Fraction(-1, 10)
    nested = page.root.recipes()[1]
    assert nested.fixed_crafter_count == Fraction(5, 2)


def test_load_refuses_non_json(tmp_path: Path) -> None:
    path = tmp_path / "plan.gtnh"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(MalformedPlanError, match="not JSON"):
        load_page(path)


def test_load_refuses_nan(tmp_path: Path) -> None:
    path = tmp_path / "plan.gtnh"
    path.write_text('{"products": [{"goodsId": "x", "amount": NaN}]}', encoding="utf-8")
    with pytest.raises(MalformedPlanError, match="NaN"):
        load_page(path)


def _with(path: list[str | int], value: object) -> dict[str, Any]:
    plan: Any = _plan()
    target = plan
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return dict(plan)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "the plan is not a JSON object"),
        (_with(["name"], 3), "name is not a string"),
        (_with(["products"], {}), "products is not a JSON array"),
        (_with(["products", 0, "amount"], "5"), r"products\[0\].amount is not a number"),
        (_with(["products", 0, "amount"], True), "not a number"),
        (_with(["products", 0, "amount"], float("inf")), "not a finite number"),
        (_with(["rootGroup", "links", "f:minecraft:water"], 2), "not 0 .Match. or 1"),
        (_with(["rootGroup", "elements"], {}), "elements is not a JSON array"),
        (_with(["rootGroup", "elements", 0, "voltageTier"], 1.5), "not a tier index"),
        (_with(["rootGroup", "elements", 0, "voltageTier"], -1), "not a tier index"),
        (_with(["rootGroup", "elements", 0, "crafter"], 5), "crafter is not a string"),
        (_with(["rootGroup", "elements", 0, "choices"], []), "choices is not a JSON object"),
        (_with(["rootGroup", "elements", 0, "choices", "coilTier"], None), "not a number"),
        (_with(["settings", "timeUnit"], "week"), "not one of"),
        (_with(["settings"], 1), "settings is not a JSON object"),
    ],
)
def test_refuses_malformed_plans(data: object, message: str) -> None:
    with pytest.raises(MalformedPlanError, match=message):
        parse_page(data)


def test_parse_accepts_floats_from_a_plain_json_load() -> None:
    page = parse_page(json.loads(json.dumps(_plan())))
    assert page.products[1].amount == Fraction(-1, 10)
