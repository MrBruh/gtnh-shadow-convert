"""An exact linear-program solver: minimise ``c.x`` subject to ``A x = b`` and ``x >= 0``.

The calculator solves its plans with javascript-lp-solver in floating point. This is the same
problem solved in rationals (:class:`~fractions.Fraction`), so a machine count that is exactly 2
comes out exactly 2 and its ceiling is 2, not 3. Plans are small (one variable per recipe row, one
equality per link), so a textbook method is plenty::

    rows with b < 0 negated, so b >= 0
      |
      v
    phase 1: one artificial per row, minimise their sum     sum > 0 -> infeasible: the rows whose
      |                                                                artificial is still positive
      v                                                                cannot be met
    drive the remaining (zero) artificials out of the basis; a row that cannot be is redundant
      |
      v
    phase 2: minimise c.x from that basis                   a column with no positive entry ->
      |                                                     unbounded
      v
    x

Pivots follow **Bland's rule** (lowest entering index, lowest leaving index on a ratio tie), which
cannot cycle, so degenerate plans terminate. Rows are sparse ``{column: value}`` dicts, since each
link touches only the few recipes that make or use its good.

When the optimum is not unique (two recipes making the same good at the same cost), this returns
the vertex Bland's rule reaches, which need not be the one the calculator's solver reports. Both
are optimal for the same plan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

_ZERO = Fraction(0)


class InfeasibleError(ValueError):
    """No ``x >= 0`` satisfies every row. ``rows`` are the indexes that could not be met."""

    def __init__(self, rows: Sequence[int]) -> None:
        super().__init__(f"infeasible: rows {list(rows)} cannot be satisfied")
        self.rows = tuple(rows)


class UnboundedError(ValueError):
    """The objective decreases without limit."""


def minimise(
    costs: Sequence[Fraction],
    rows: Sequence[Mapping[int, Fraction]],
    rhs: Sequence[Fraction],
) -> list[Fraction]:
    """An optimal ``x`` for: minimise ``sum(costs[j] * x[j])``, ``rows[i] . x == rhs[i]``, ``x >= 0``.

    ``rows[i]`` maps a column index to its coefficient; absent columns are zero.
    """
    if len(rows) != len(rhs):
        raise ValueError("one right-hand side per row")
    columns = len(costs)
    tableau: list[dict[int, Fraction]] = []
    values: list[Fraction] = []
    for row, b in zip(rows, rhs, strict=True):
        sign = -1 if b < 0 else 1
        entries = {j: sign * Fraction(v) for j, v in row.items() if v != 0}
        if any(not 0 <= j < columns for j in entries):
            raise ValueError("a row names a column beyond the cost vector")
        tableau.append(entries)
        values.append(sign * Fraction(b))
    artificial = [columns + i for i in range(len(tableau))]
    for i, column in enumerate(artificial):
        tableau[i][column] = Fraction(1)
    basis = list(artificial)
    solver = _Simplex(tableau, values, basis)

    # Phase 1: minimise the artificials' sum. Its reduced costs are minus the column sums.
    phase1: dict[int, Fraction] = {}
    for entries in tableau:
        for j, value in entries.items():
            if j < columns:
                phase1[j] = phase1.get(j, _ZERO) - value
    solver.optimise(phase1, -sum(values, _ZERO), allowed=columns)
    if solver.objective_value < 0:
        stuck = [i for i, column in enumerate(solver.basis) if column >= columns and solver.rhs[i]]
        raise InfeasibleError(sorted(solver.origin[i] for i in stuck))
    solver.drop_artificials(columns)

    # Phase 2: the real costs, reduced against the basis phase 1 left.
    objective = {j: Fraction(c) for j, c in enumerate(costs) if c != 0}
    value = _ZERO
    for i, column in enumerate(solver.basis):
        cost = objective.get(column, _ZERO)
        if cost:
            for j, entry in solver.tableau[i].items():
                objective[j] = objective.get(j, _ZERO) - cost * entry
            value -= cost * solver.rhs[i]
    solver.optimise({j: v for j, v in objective.items() if v}, value, allowed=columns)

    x = [_ZERO] * columns
    for i, column in enumerate(solver.basis):
        x[column] = solver.rhs[i]
    return x


class _Simplex:
    """A sparse tableau in canonical form for ``basis``: each basic column is a unit column."""

    def __init__(
        self, tableau: list[dict[int, Fraction]], rhs: list[Fraction], basis: list[int]
    ) -> None:
        self.tableau = tableau
        self.rhs = rhs
        self.basis = basis
        #: The caller's index of each row, which survives redundant rows being dropped.
        self.origin = list(range(len(tableau)))
        self.reduced: dict[int, Fraction] = {}
        #: Minus the objective's current value (the tableau's top-right corner).
        self.objective_value = _ZERO

    def optimise(self, reduced: dict[int, Fraction], corner: Fraction, *, allowed: int) -> None:
        """Pivot until no column below ``allowed`` has a negative reduced cost."""
        self.reduced = reduced
        self.objective_value = corner
        while True:
            entering = min(
                (j for j, v in self.reduced.items() if v < 0 and j < allowed), default=None
            )
            if entering is None:
                return
            leaving: int | None = None
            best: Fraction | None = None
            for i, entries in enumerate(self.tableau):
                coefficient = entries.get(entering)
                if coefficient is None or coefficient <= 0:
                    continue
                ratio = self.rhs[i] / coefficient
                if (
                    best is None
                    or ratio < best
                    or (
                        ratio == best
                        and leaving is not None
                        and self.basis[i] < self.basis[leaving]
                    )
                ):
                    best, leaving = ratio, i
            if leaving is None:
                raise UnboundedError("the objective is unbounded below")
            self.pivot(leaving, entering)

    def pivot(self, row: int, column: int) -> None:
        pivot_row = self.tableau[row]
        scale = pivot_row[column]
        if scale != 1:
            for j in pivot_row:
                pivot_row[j] /= scale
            self.rhs[row] /= scale
        for i, entries in enumerate(self.tableau):
            if i != row:
                factor = entries.get(column)
                if factor:
                    _subtract(entries, pivot_row, factor)
                    self.rhs[i] -= factor * self.rhs[row]
        factor = self.reduced.get(column)
        if factor:
            _subtract(self.reduced, pivot_row, factor)
            self.objective_value -= factor * self.rhs[row]
        self.basis[row] = column

    def drop_artificials(self, columns: int) -> None:
        """Pivot each zero-level artificial out of the basis, or drop its row as redundant, then
        remove the artificial columns."""
        i = 0
        while i < len(self.tableau):
            if self.basis[i] < columns:
                i += 1
                continue
            replacement = min(
                (j for j, v in self.tableau[i].items() if j < columns and v), default=None
            )
            if replacement is None:
                del self.tableau[i], self.rhs[i], self.basis[i], self.origin[i]
                continue
            self.reduced = {}
            self.pivot(i, replacement)
            i += 1
        for entries in self.tableau:
            for j in [j for j in entries if j >= columns]:
                del entries[j]


def _subtract(
    target: dict[int, Fraction], source: Mapping[int, Fraction], factor: Fraction
) -> None:
    """``target -= factor * source``, dropping entries that reach zero."""
    for j, value in source.items():
        updated = target.get(j, _ZERO) - factor * value
        if updated:
            target[j] = updated
        else:
            target.pop(j, None)
