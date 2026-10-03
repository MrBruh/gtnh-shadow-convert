from __future__ import annotations

from fractions import Fraction

import pytest

from gtnh_shadow_convert.databin import Recipe, Repository
from gtnh_shadow_convert.errors import UnsupportedMachineError
from gtnh_shadow_convert.machines import (
    MACHINES,
    NULL_OVERCLOCKER,
    SINGLE_BLOCK,
    UNSUPPORTED,
    Choice,
    Coefficient,
    Machine,
    RecipeContext,
    StandardOverclocker,
    evaluate,
    excluder_of,
    rule_for,
    single_block_rule,
)
from gtnh_shadow_convert.machines.singleblock import MASS_FABRICATOR
from gtnh_shadow_convert.testing import Gt, SyntheticData


@pytest.fixture
def repo() -> Repository:
    data = SyntheticData()
    data.recipe_type("Compressor")
    data.recipe_type("Mass Fabrication")
    data.recipe("r~plain", "Compressor", gt=Gt(2, 100))
    data.recipe("r~dense", "Compressor", gt=Gt(2, 100, metadata={"compression_tier": 1.0}))
    data.recipe("r~craft", "Compressor")
    data.recipe("r~uu", "Mass Fabrication", gt=Gt(256, 100))
    return Repository.from_bytes(data.to_bytes())


def _recipe(repo: Repository, recipe_id: str) -> Recipe:
    recipe = repo.recipe(recipe_id)
    assert recipe is not None
    return recipe


def _context(repo: Repository, tier: int = 0) -> RecipeContext:
    return RecipeContext(_recipe(repo, "r~plain"), tier, {})


@pytest.mark.parametrize(
    ("overclocker", "tiers", "speed", "power", "name"),
    [
        (StandardOverclocker.only_normal(), 0, 1, 1, ""),
        (StandardOverclocker.only_normal(), 2, 4, 4, "OC x2"),
        (StandardOverclocker.only_normal(1), 3, 2, 2, "OC x1 (capped)"),
        (StandardOverclocker.only_perfect(), 2, 16, 1, "Perfect OC x2"),
        (StandardOverclocker.only_perfect(1), 3, 4, 1, "Perfect OC x1 (capped)"),
        (StandardOverclocker.only_perfect(2, 2), 3, 4, 1, "2/2 OC x2 (capped)"),
        (StandardOverclocker.perfect_then_normal(1), 3, 16, 4, "Perfect OC x1, OC x2"),
        (StandardOverclocker.perfect_then_normal(), 2, 16, 1, "Perfect OC x2"),
        (StandardOverclocker.only_perfect(0), 3, 1, 1, "Can't overclock"),
        (StandardOverclocker.only_normal(), -2, 1, 1, ""),
        (NULL_OVERCLOCKER, 5, 1, 1, "Can't overclock"),
    ],
)
def test_overclockers(
    repo: Repository, overclocker: object, tiers: int, speed: int, power: int, name: str
) -> None:
    assert isinstance(overclocker, StandardOverclocker | type(NULL_OVERCLOCKER))
    result = overclocker.calculate(_context(repo), tiers)
    assert (result.speed, result.power, result.name) == (speed, power, name)


def test_a_negative_perfect_cap_spends_normal_tiers_as_the_app_does(repo: Repository) -> None:
    # An EBF whose coils are too cold for the recipe: floor(negative heat / 1800) perfect tiers.
    # The app's arithmetic then grants more normal tiers than the machine has; kept, as it is.
    result = StandardOverclocker.perfect_then_normal(-1).calculate(_context(repo), 2)
    assert (result.speed, result.perfect, result.name) == (8, -1, "OC x3")


def test_single_block_rule(repo: Repository) -> None:
    compressor = _recipe(repo, "r~plain").recipe_type
    assert single_block_rule(compressor) is SINGLE_BLOCK
    excludes = SINGLE_BLOCK.excludes_recipe
    assert excludes is not None
    assert not excludes(_recipe(repo, "r~plain"))
    assert excludes(_recipe(repo, "r~dense"))
    assert not excludes(_recipe(repo, "r~craft"))
    mass = _recipe(repo, "r~uu").recipe_type
    assert single_block_rule(mass) is MASS_FABRICATOR
    assert evaluate(MASS_FABRICATOR.power, _context(repo, 3)) == Fraction(1, 8)


def test_evaluate_constants_and_functions(repo: Repository) -> None:
    context = _context(repo, 2)
    assert RecipeContext(context.recipe, 2, {"coil": 3}).choice("coil") == 3
    assert evaluate(Fraction(3), context) == 3

    def twice_the_tier(c: RecipeContext) -> int:
        return c.voltage_tier * 2

    coefficient: Coefficient[int] = twice_the_tier
    assert evaluate(coefficient, context) == 4


def test_choice_bounds() -> None:
    assert Choice("Coil", ("a", "b", "c")).upper == 2
    assert Choice("Slices", minimum=1, maximum=999).upper == 999
    assert Choice("Amps", minimum=16).upper is None


def test_rule_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = Machine(StandardOverclocker.only_normal())
    monkeypatch.setitem(MACHINES, "Test Machine", rule)
    assert rule_for("Test Machine") is rule
    assert excluder_of("Test Machine") is rule
    assert excluder_of("Nothing") is None
    with pytest.raises(UnsupportedMachineError, match="'Nothing'") as caught:
        rule_for("Nothing")
    assert caught.value.machine == "Nothing"


def test_unsupported_machines_say_why(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(UNSUPPORTED, '<span class="fmt-d">Odd</span> Machine', "it is odd")
    with pytest.raises(UnsupportedMachineError, match=r"'Odd Machine'.*it is odd"):
        rule_for('<span class="fmt-d">Odd</span> Machine')
