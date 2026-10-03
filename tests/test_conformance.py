"""The converter against the calculator itself: every one of the app's 29 test plans, solved here and
compared row by row with the app's Jest snapshot (``tests/conformance``, MIT, see its README).

Needs the real ``data.bin`` (``GTNH_SHADOW_DATA``); skipped without it. CI's conformance job
fetches it. A plan that uses a machine whose rule is not ported must fail with exactly that
machine named, so the list below only ever shrinks as rules are ported.
"""

from __future__ import annotations

import json
import re
import warnings
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from gtnh_shadow_convert.databin import Repository
from gtnh_shadow_convert.errors import UnsupportedMachineError
from gtnh_shadow_convert.machines import UNSUPPORTED
from gtnh_shadow_convert.page import load_page
from gtnh_shadow_convert.solve import solve

HERE = Path(__file__).parent / "conformance"
PLANS = sorted((HERE / "plans").glob("*.gtnh"))

#: Plans that use a machine whose rule is not ported, and that machine.
EXPECTED_UNSUPPORTED = {
    "AAL Test.gtnh": "Advanced Assembly Line",
    "DTPF Convergence Catalyst Test.gtnh": "Dimensionally Transcendent Plasma Forge",
    "DTPF Convergence Test.gtnh": "Dimensionally Transcendent Plasma Forge",
    "Nano Forge.gtnh": "Nano Forge",
    "PCB test.gtnh": "PCB Factory",
    "QFT.gtnh": "Quantum Force Transformer",
}

#: The app solves in floating point and its LP rounds to 1e-8; this compares at 1e-6 relative.
RELATIVE = 1e-6
ABSOLUTE = 1e-7

_EXPORT = re.compile(
    r"exports\[`Solver Processing (.+?) should process without errors 1`\] = `\n(.*?)\n`;", re.S
)


def snapshot() -> dict[str, list[dict[str, Any]]]:
    """The Jest snapshot, per plan file. Its pretty-format is JSON but for trailing commas and
    ``undefined``."""
    text = (HERE / "solver.test.ts.snap").read_text(encoding="utf-8")
    plans: dict[str, list[dict[str, Any]]] = {}
    for name, body in _EXPORT.findall(text):
        body = re.sub(r",(\s*[\]}])", r"\1", body).replace("undefined", "null")
        plans[name] = json.loads(body)
    return plans


@cache
def _repo(path: str) -> Repository:
    return Repository.load(path)


def test_the_fixtures_are_complete() -> None:
    expected = snapshot()
    assert len(PLANS) == 29
    assert sorted(expected) == sorted(plan.name for plan in PLANS)
    assert sum(len(rows) for rows in expected.values()) == 270
    assert set(EXPECTED_UNSUPPORTED.values()) <= set(UNSUPPORTED)


def _close(got: float, want: float) -> bool:
    return abs(got - want) <= RELATIVE * max(abs(got), abs(want)) + ABSOLUTE


@pytest.mark.parametrize("plan", PLANS, ids=[plan.stem for plan in PLANS])
def test_plan_matches_the_calculator(plan: Path, real_data: Path) -> None:
    repo = _repo(str(real_data))
    page = load_page(plan)
    unsupported = EXPECTED_UNSUPPORTED.get(plan.name)
    if unsupported is not None:
        with pytest.raises(UnsupportedMachineError) as caught:
            solve(page, repo)
        assert caught.value.machine == unsupported
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the app's own plans include rows set below their tier
        solved = solve(page, repo)
    expected = snapshot()[plan.name]
    assert len(solved.recipes) == len(expected)
    for row, want in zip(solved.recipes, expected, strict=True):
        assert row.element.recipe_id == want["id"]
        where = f"{plan.name} row {list(row.element.path)} ({want['id']})"
        for got, key in (
            (row.runs_per_minute, "recipesPerMinute"),
            (row.crafter_count, "crafterCount"),
            (row.power_factor, "powerFactor"),
            (row.overclock_factor, "overclockFactor"),
        ):
            assert _close(float(got), want[key]), f"{where}: {key} {float(got)} != {want[key]}"
        name = row.overclock.name if row.timed else None
        assert name == want["overclockName"], f"{where}: overclock label"
