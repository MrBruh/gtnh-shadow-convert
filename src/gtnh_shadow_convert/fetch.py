"""Download the calculator's ``data.bin`` into a user cache, and know which pack a file is.

The data has **no license** (``ShadowTheAge/gtnh-data``'s README says so, with a fair-use note on
the game content), so this package never ships or commits it. A user fetches it on purpose, with
``gtnh-shadow-convert fetch-data``, and the converter then reads it from wherever they keep it::

    fetch_data()
      | download KNOWN_DATA's URL (a gtnh-data commit, so the bytes cannot change under it)
      | check its sha256 against the table, and that it is a data.bin this reader understands
      v
    <cache>/<sha256>/data.bin      the file, as served (gzip)
    <cache>/<sha256>/source.json   {url, sha256, dataVersion, packVersion, fetchedAt}

**Which pack a data.bin is** cannot be read from the file: it records a format version and nothing
about the game it was exported from. :data:`KNOWN_DATA` therefore maps a file's sha256 to its pack,
and an unknown file needs the pack named by hand (``--pack-version``). An exact pack matters: the
solver keeps one structure dataset per pack (``data/2.9.0-beta-2/``), and a near miss would size
the layout against another game version.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .databin import Repository
from .errors import ConversionError


@dataclass(frozen=True)
class KnownData:
    """A ``data.bin`` this converter has been checked against."""

    pack_version: str
    data_version: int
    url: str
    #: Where the calculator's own site serves the same bytes, for the record.
    site_url: str
    note: str


#: sha256 -> what that file is. The 2.9 import (gtnh-data ``d200440``, branch ``2.9.0-v7``,
#: committed 2026-07-19 as "Import for 2.9.0") is the one the calculator serves today. Its
#: exporter, ShadowTheAge/nesql-exporter @ b5b896e, was built against GT 5.09.54.20, which is the
#: GregTech of the GTNH 2.9.0-beta-2 pack, so that is the pack it is recorded as.
KNOWN_DATA: dict[str, KnownData] = {
    "624c9a20c8476dc630c274145dc04c72d7c582e130a3599dc49ce9aee0a2fe73": KnownData(
        pack_version="2.9.0-beta-2",
        data_version=7,
        url=(
            "https://raw.githubusercontent.com/ShadowTheAge/gtnh-data/"
            "d200440ea31d0357068a294d7312acf1146de909/data.bin"
        ),
        site_url="https://shadowtheage.github.io/gtnh/data/data.bin",
        note="gtnh-data d200440 (2.9.0-v7), exported against GT 5.09.54.20",
    ),
}

#: The file :func:`fetch_data` downloads by default: the newest entry of :data:`KNOWN_DATA`.
DEFAULT_SHA256 = "624c9a20c8476dc630c274145dc04c72d7c582e130a3599dc49ce9aee0a2fe73"

_CHUNK = 1 << 20


def cache_dir() -> Path:
    """Where fetched data lives: ``$GTNH_SHADOW_CACHE`` if set, else the platform's user cache."""
    override = os.environ.get("GTNH_SHADOW_CACHE")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "gtnh-shadow-convert" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "gtnh-shadow-convert"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "gtnh-shadow-convert"


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def pack_version_of(path: str | Path) -> str | None:
    """The pack a ``data.bin`` was exported from, if :data:`KNOWN_DATA` knows the file."""
    known = KNOWN_DATA.get(file_sha256(path))
    return None if known is None else known.pack_version


def fetch_data(
    *,
    url: str | None = None,
    sha256: str | None = DEFAULT_SHA256,
    cache: str | Path | None = None,
) -> Path:
    """Download a ``data.bin`` into the cache and return its path.

    With no arguments this fetches the default file and checks it against its known sha256. A
    ``url`` of your own needs ``sha256=None`` (no check) or the hash you expect. The download is
    refused, and nothing is kept, when the hash differs or the file is not a ``data.bin`` this
    reader understands. An already-cached file with the expected hash is returned as is.
    """
    if url is None:
        known = KNOWN_DATA.get(sha256 or "")
        if known is None:
            raise ConversionError("fetch_data needs a url for a data.bin it does not know")
        url = known.url
    root = Path(cache) if cache is not None else cache_dir()
    if sha256 is not None:
        cached = root / sha256 / "data.bin"
        if cached.is_file() and file_sha256(cached) == sha256:
            return cached
    root.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=root, suffix=".download")
    temp = Path(temp_name)
    try:
        digest = hashlib.sha256()
        with os.fdopen(handle, "wb") as out, urllib.request.urlopen(url, timeout=60) as response:
            while chunk := response.read(_CHUNK):
                digest.update(chunk)
                out.write(chunk)
        found = digest.hexdigest()
        if sha256 is not None and found != sha256:
            raise ConversionError(f"{url} has sha256 {found}, not the expected {sha256}")
        data_version = Repository.load(temp).data_version
        target_dir = root / found
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "data.bin"
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    known = KNOWN_DATA.get(found)
    record = {
        "url": url,
        "sha256": found,
        "dataVersion": data_version,
        "packVersion": known.pack_version if known is not None else None,
        "fetchedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (target_dir / "source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return target
