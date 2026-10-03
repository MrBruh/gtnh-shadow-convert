from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gtnh_shadow_convert.lp import InfeasibleError, UnboundedError, minimise

F = Fraction


def _check(costs: list[Fraction], rows: list[dict[int, Fraction]], rhs: list[Fraction]) -> list[F]:
    x = minimise(costs, rows, rhs)
    assert all(v >= 0 for v in x)
    for row, b in zip(rows, rhs, strict=True):
        assert sum((c * x[j] for j, c in row.items()), F(0)) == b
    return x


def test_a_chain_balances_exactly() -> None:
    # x0 makes 3 of A per run; x1 uses 2 A and makes 1 B; the plan wants 7 B.
    x = _check([F(1), F(1)], [{0: F(-3), 1: F(2)}, {1: F(-1)}], [F(0), F(-7)])
    assert x == [F(14, 3), F(7)]


def test_picks_the_cheaper_of_two_makers() -> None:
    # Two recipes make A: x0 makes 1, x1 makes 2 per run. Demand 4 A. Cheapest: two runs of x1.
    x = _check([F(1), F(1)], [{0: F(-1), 1: F(-2)}], [F(-4)])
    assert x == [F(0), F(2)]


def test_no_rows_runs_nothing() -> None:
    assert minimise([F(1), F(1)], [], []) == [F(0), F(0)]


def test_redundant_rows_are_dropped() -> None:
    x = _check([F(1)], [{0: F(2)}, {0: F(4)}], [F(6), F(12)])
    assert x == [F(3)]


def test_degenerate_zero_rows() -> None:
    x = _check([F(1), F(1), F(1)], [{0: F(1), 1: F(-1)}, {1: F(1), 2: F(-1)}], [F(0), F(0)])
    assert x == [F(0), F(0), F(0)]


def test_infeasible_names_the_rows() -> None:
    with pytest.raises(InfeasibleError) as caught:
        minimise([F(1)], [{0: F(1)}, {0: F(1)}], [F(1), F(2)])
    assert caught.value.rows
    assert set(caught.value.rows) <= {0, 1}


def test_infeasible_when_a_row_cannot_be_met() -> None:
    with pytest.raises(InfeasibleError) as caught:
        minimise([F(1)], [{0: F(-1)}], [F(5)])
    assert caught.value.rows == (0,)


def test_unbounded() -> None:
    with pytest.raises(UnboundedError):
        minimise([F(-1), F(0)], [{0: F(1), 1: F(-1)}], [F(0)])


def test_shape_errors() -> None:
    with pytest.raises(ValueError, match="one right-hand side"):
        minimise([F(1)], [{0: F(1)}], [])
    with pytest.raises(ValueError, match="beyond"):
        minimise([F(1)], [{3: F(1)}], [F(1)])


def test_zero_coefficients_are_ignored() -> None:
    assert minimise([F(1)], [{0: F(0)}], [F(0)]) == [F(0)]


@st.composite
def feasible_problems(draw: st.DrawFn) -> tuple[list[F], list[dict[int, F]], list[F], list[F]]:
    columns = draw(st.integers(min_value=1, max_value=6))
    count = draw(st.integers(min_value=0, max_value=5))
    witness = [F(draw(st.integers(min_value=0, max_value=6))) for _ in range(columns)]
    rows: list[dict[int, F]] = []
    for _ in range(count):
        row = {
            j: F(draw(st.integers(min_value=-4, max_value=4)))
            for j in range(columns)
            if draw(st.booleans())
        }
        rows.append(row)
    rhs = [sum((c * witness[j] for j, c in row.items()), F(0)) for row in rows]
    costs = [F(draw(st.integers(min_value=0, max_value=3))) for _ in range(columns)]
    return costs, rows, rhs, witness


@settings(max_examples=300)
@given(feasible_problems())
def test_any_feasible_problem_is_solved_optimally(
    problem: tuple[list[F], list[dict[int, F]], list[F], list[F]],
) -> None:
    costs, rows, rhs, witness = problem
    x = _check(costs, rows, rhs)
    cost = sum((c * v for c, v in zip(costs, x, strict=True)), F(0))
    assert cost <= sum((c * v for c, v in zip(costs, witness, strict=True)), F(0))
