"""The converter's errors. Every one is a :class:`ValueError`, so a caller that only wants to know
"this plan did not convert" catches one type, and a caller that cares can tell them apart."""

from __future__ import annotations

from collections.abc import Sequence


class ConversionError(ValueError):
    """The base of every error the converter raises on purpose."""


class DataError(ConversionError):
    """``data.bin`` is unreadable: not gzip, truncated, or a pointer that leads outside it."""


class UnsupportedDataVersionError(DataError):
    """``data.bin`` is a format version this converter was not written against.

    The format changes with each pack import Shadow's app takes, and a reader that guessed at a
    newer layout would resolve recipes to plausible nonsense, so anything but the known version is
    refused outright.
    """

    def __init__(self, found: int, supported: int) -> None:
        super().__init__(
            f"data.bin is format version {found}, but this converter reads only version "
            f"{supported}; use the data.bin the converter's README names, or a converter release "
            f"that supports version {found}"
        )
        self.found = found
        self.supported = supported


class MalformedPlanError(ConversionError):
    """The ``.gtnh`` file is not a plan the calculator would have saved."""


class UnknownRecipeError(ConversionError):
    """A recipe id in the plan is not in ``data.bin``, even after the remap table."""

    def __init__(self, recipe_id: str) -> None:
        super().__init__(
            f"recipe {recipe_id!r} is not in this data.bin (nor in its table of renamed recipes); "
            f"the plan was probably saved against another pack version"
        )
        self.recipe_id = recipe_id


class UnsupportedMachineError(ConversionError):
    """A recipe runs in a machine whose rule has not been ported, so its rates are unknown.

    Raised instead of guessing: the calculator itself computes such a machine as a single block,
    which can be off by its whole parallel count.
    """

    def __init__(self, machine: str, reason: str = "") -> None:
        detail = f": {reason}" if reason else ""
        super().__init__(
            f"no rule for the machine {machine!r} has been ported from the calculator yet{detail}"
        )
        self.machine = machine


class UnsupportedRecipeError(ConversionError):
    """A recipe the converter cannot turn into a machine, such as a crafting-table recipe."""


class InfeasiblePlanError(ConversionError):
    """The plan's links cannot all be balanced at once, so no rate satisfies it."""

    def __init__(self, links: Sequence[str]) -> None:
        names = ", ".join(links) if links else "(none identified)"
        super().__init__(f"the plan cannot be balanced; these links have no solution: {names}")
        self.links = tuple(links)
