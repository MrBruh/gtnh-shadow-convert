"""Convert ShadowTheAge's GT:NH calculator plans (``.gtnh``) into gtnh-factory-flow plan JSON.

A ``.gtnh`` file holds hashed recipe ids, tiers and machine options, and nothing else: the recipes
themselves come from the calculator's ``data.bin``, and the rates from its solver. This package
ports both from ShadowTheAge/gtnh (MIT), pinned in ``SHADOW_COMMIT``::

    from gtnh_shadow_convert import convert

    plan = convert("Shadow-NB.gtnh", "data.bin")  # a dict, ready for json.dump
"""

from ._pins import SHADOW_COMMIT
from .emit import convert, emit
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
    "convert",
    "emit",
]
