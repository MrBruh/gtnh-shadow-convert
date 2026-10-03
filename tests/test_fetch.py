from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gtnh_shadow_convert import fetch
from gtnh_shadow_convert.errors import ConversionError, DataError
from gtnh_shadow_convert.fetch import (
    KNOWN_DATA,
    KnownData,
    cache_dir,
    fetch_data,
    file_sha256,
    pack_version_of,
)
from gtnh_shadow_convert.testing import SyntheticData


@pytest.fixture
def served(tmp_path: Path) -> tuple[str, str]:
    """A synthetic data.bin behind a file:// URL, and its sha256."""
    data = SyntheticData()
    data.fluid("minecraft", "water")
    path = data.write(tmp_path / "served.bin")
    return path.as_uri(), file_sha256(path)


def test_cache_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GTNH_SHADOW_CACHE", str(tmp_path))
    assert cache_dir() == tmp_path


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("win32", {"LOCALAPPDATA": "/local"}, Path("/local/gtnh-shadow-convert/Cache")),
        ("darwin", {}, Path("/home/u/Library/Caches/gtnh-shadow-convert")),
        ("linux", {"XDG_CACHE_HOME": "/xdg"}, Path("/xdg/gtnh-shadow-convert")),
        ("linux", {}, Path("/home/u/.cache/gtnh-shadow-convert")),
    ],
)
def test_cache_dir_per_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str, env: dict[str, str], expected: Path
) -> None:
    for name in ("GTNH_SHADOW_CACHE", "LOCALAPPDATA", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/home/u")))
    assert cache_dir() == expected


def test_fetch_records_its_source(tmp_path: Path, served: tuple[str, str]) -> None:
    url, sha = served
    path = fetch_data(url=url, sha256=sha, cache=tmp_path / "cache")
    assert path == tmp_path / "cache" / sha / "data.bin"
    assert file_sha256(path) == sha
    record = json.loads((path.parent / "source.json").read_text(encoding="utf-8"))
    assert record["url"] == url
    assert record["sha256"] == sha
    assert record["dataVersion"] == 7
    assert record["packVersion"] is None
    assert record["fetchedAt"]
    assert [p.name for p in (tmp_path / "cache").iterdir()] == [sha]  # no temp file left


def test_fetch_reuses_a_cached_file(
    tmp_path: Path, served: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, sha = served
    first = fetch_data(url=url, sha256=sha, cache=tmp_path)

    def fail(*_: object, **__: object) -> None:
        raise AssertionError("downloaded again")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    assert fetch_data(url=url, sha256=sha, cache=tmp_path) == first


def test_fetch_without_a_hash_check(tmp_path: Path, served: tuple[str, str]) -> None:
    url, sha = served
    assert fetch_data(url=url, sha256=None, cache=tmp_path).parent.name == sha


def test_fetch_refuses_the_wrong_hash(tmp_path: Path, served: tuple[str, str]) -> None:
    url, _ = served
    with pytest.raises(ConversionError, match="not the expected"):
        fetch_data(url=url, sha256="0" * 64, cache=tmp_path / "cache")
    assert list((tmp_path / "cache").iterdir()) == []


def test_fetch_refuses_a_file_that_is_not_data(tmp_path: Path) -> None:
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"\x1f\x8bnope")
    with pytest.raises(DataError):
        fetch_data(url=junk.as_uri(), sha256=None, cache=tmp_path / "cache")
    assert list((tmp_path / "cache").iterdir()) == []


def test_fetch_needs_a_url_for_an_unknown_file(tmp_path: Path) -> None:
    with pytest.raises(ConversionError, match="needs a url"):
        fetch_data(sha256="f" * 64, cache=tmp_path)


def test_fetch_defaults_to_the_known_file(
    tmp_path: Path, served: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, sha = served
    monkeypatch.setitem(KNOWN_DATA, sha, KnownData("9.9.9", 7, url, "", "test"))
    path = fetch_data(sha256=sha, cache=tmp_path)
    record = json.loads((path.parent / "source.json").read_text(encoding="utf-8"))
    assert record["packVersion"] == "9.9.9"
    assert pack_version_of(path) == "9.9.9"


def test_pack_version_of_an_unknown_file(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"x")
    assert pack_version_of(path) is None


def test_known_table_is_consistent() -> None:
    for sha, known in KNOWN_DATA.items():
        assert len(sha) == 64
        assert known.data_version == 7
        assert sha in known.url or "d200440" in known.url
    assert fetch.DEFAULT_SHA256 in KNOWN_DATA


def test_real_data_is_the_known_file(real_data: Path) -> None:
    assert pack_version_of(real_data) == "2.9.0-beta-2"
    assert hashlib.sha256(real_data.read_bytes()).hexdigest() == fetch.DEFAULT_SHA256
