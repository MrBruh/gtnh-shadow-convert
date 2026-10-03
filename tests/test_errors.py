from __future__ import annotations

import pytest

from gtnh_shadow_convert import (
    ConversionError,
    DataError,
    InfeasiblePlanError,
    MalformedPlanError,
    UnknownRecipeError,
    UnsupportedDataVersionError,
    UnsupportedMachineError,
    UnsupportedRecipeError,
)


@pytest.mark.parametrize(
    "error",
    [
        DataError("x"),
        UnsupportedDataVersionError(8, 7),
        MalformedPlanError("x"),
        UnknownRecipeError("r~x"),
        UnsupportedMachineError("QFT"),
        UnsupportedRecipeError("x"),
        InfeasiblePlanError(["link"]),
    ],
)
def test_every_error_is_a_value_error(error: ConversionError) -> None:
    assert isinstance(error, ValueError)
    assert isinstance(error, ConversionError)


def test_messages_name_what_failed() -> None:
    assert UnknownRecipeError("r~x").recipe_id == "r~x"
    assert "'r~x'" in str(UnknownRecipeError("r~x"))
    machine = UnsupportedMachineError("Quantum Force Transformer", "its outputs depend on focusing")
    assert machine.machine == "Quantum Force Transformer"
    assert str(machine).endswith(": its outputs depend on focusing")
    assert not str(UnsupportedMachineError("X")).endswith(":")
    infeasible = InfeasiblePlanError(["water in Group", "steam in Group"])
    assert infeasible.links == ("water in Group", "steam in Group")
    assert "water in Group, steam in Group" in str(infeasible)
    assert "(none identified)" in str(InfeasiblePlanError([]))
