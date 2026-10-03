"""Shared fixtures. The real ``data.bin`` is never needed: tests that read it skip without it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

#: Set to a real data.bin to run the tests that read one (CI's conformance job does).
REAL_DATA_ENV = "GTNH_SHADOW_DATA"


@pytest.fixture
def real_data() -> Path:
    """The real data.bin, or a skip when ``GTNH_SHADOW_DATA`` does not name one."""
    value = os.environ.get(REAL_DATA_ENV)
    if not value or not Path(value).is_file():
        pytest.skip(f"set {REAL_DATA_ENV} to a data.bin to run this test")
    return Path(value)
