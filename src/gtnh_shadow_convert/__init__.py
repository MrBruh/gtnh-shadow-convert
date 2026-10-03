"""Convert ShadowTheAge's GT:NH calculator plans (``.gtnh``) into gtnh-factory-flow plan JSON.

A ``.gtnh`` file holds hashed recipe ids, tiers and machine options, and nothing else: the recipes
themselves come from the calculator's ``data.bin``, and the rates from its solver. This package
ports both from ShadowTheAge/gtnh (MIT), pinned in ``SHADOW_COMMIT``.
"""

from .errors import (
    ConversionError,
    ConversionWarning,
    DataError,
    InfeasiblePlanError,
    MalformedPlanError,
    UnknownRecipeError,
    UnsupportedDataVersionError,
    UnsupportedMachineError,
    UnsupportedRecipeError,
)

#: The ShadowTheAge/gtnh commit this package's port follows.
SHADOW_COMMIT = "af8c79888ec859913b27543c1381c3c11c24658f"

__all__ = [
    "SHADOW_COMMIT",
    "ConversionError",
    "ConversionWarning",
    "DataError",
    "InfeasiblePlanError",
    "MalformedPlanError",
    "UnknownRecipeError",
    "UnsupportedDataVersionError",
    "UnsupportedMachineError",
    "UnsupportedRecipeError",
]
