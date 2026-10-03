"""Overclocking, as the calculator models it (the ``Overclocker`` classes of ``machines.ts``).

An overclock tier is one voltage tier of headroom the machine spends on speed::

    normal   x2 speed, x2 power per batch   (so x4 EU/t)
    perfect  xM speed, x1 power per batch   (M is 4 for every machine but fusion, which has 2)

:class:`StandardOverclocker` spends perfect tiers first, up to ``max_perfect``, then normal ones up
to ``max_normal`` (``None`` is unlimited). The result's ``name`` is the app's label for it ("OC x2",
"Perfect OC x1 (capped)"), kept verbatim because the conformance suite compares it.

A negative tier count (a row set below its recipe's tier) is passed through as the app passes it:
no tier is spent and the machine runs at base speed.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from .machine import RecipeContext


@dataclass(frozen=True)
class OverclockResult:
    speed: Fraction
    power: Fraction
    perfect: int
    name: str


class Overclocker(Protocol):
    def calculate(self, context: RecipeContext, tiers: int) -> OverclockResult: ...


_CANNOT = OverclockResult(Fraction(1), Fraction(1), 0, "Can't overclock")


def js_number(value: Fraction) -> str:
    """A number as JavaScript prints it in a label: ``2``, ``1.5``."""
    return str(value.numerator) if value.denominator == 1 else repr(float(value))


def _capped(limit: int | None, count: int) -> int:
    return count if limit is None else min(limit, count)


@dataclass(frozen=True)
class StandardOverclocker:
    """Perfect overclocks first, then normal ones (``StandardOverclocker``)."""

    max_perfect: int | None
    max_normal: int | None
    #: Speed per perfect tier. Not always whole: a Netherite arc-furnace electrode gives 1.5.
    multiplier: Fraction = Fraction(4)

    @classmethod
    def only_perfect(
        cls, max_perfect: int | None = None, multiplier: Fraction | int = 4
    ) -> StandardOverclocker:
        return cls(max_perfect, 0, Fraction(multiplier))

    @classmethod
    def only_normal(cls, max_normal: int | None = None) -> StandardOverclocker:
        return cls(0, max_normal)

    @classmethod
    def perfect_then_normal(cls, max_perfect: int | None = None) -> StandardOverclocker:
        return cls(max_perfect, None)

    def calculate(self, context: RecipeContext, tiers: int) -> OverclockResult:
        if self.max_perfect == 0 and self.max_normal == 0:
            return _CANNOT
        perfect = _capped(self.max_perfect, tiers)
        normal = _capped(self.max_normal, tiers - perfect)
        speed = Fraction(1)
        power = Fraction(1)
        parts: list[str] = []
        if perfect > 0:
            speed = Fraction(self.multiplier) ** perfect
            capped = " (capped)" if perfect == self.max_perfect and normal == 0 else ""
            if self.multiplier == 4:
                parts.append(f"Perfect OC x{perfect}{capped}")
            else:
                m = js_number(self.multiplier)
                parts.append(f"{m}/{m} OC x{perfect}{capped}")
        if normal > 0:
            capped = " (capped)" if normal == self.max_normal else ""
            factor = Fraction(2) ** normal
            speed *= factor
            power *= factor
            parts.append(f"OC x{normal}{capped}")
        return OverclockResult(speed, power, perfect, ", ".join(parts))


@dataclass(frozen=True)
class NullOverclocker:
    """A machine that cannot overclock (``NullOverclocker``)."""

    def calculate(self, context: RecipeContext, tiers: int) -> OverclockResult:
        return _CANNOT


NULL_OVERCLOCKER = NullOverclocker()
