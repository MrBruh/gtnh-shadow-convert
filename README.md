# gtnh-shadow-convert

Turns a plan made in [ShadowTheAge's GT:NH calculator](https://shadowtheage.github.io/gtnh/) (a
`.gtnh` file) into the plan JSON that
[gtnh-factory-flow](https://github.com/MrBruh/gtnh-factory-flow) exports, so tools that read those
plans, such as [gtnh-process-line-solver](https://github.com/MrBruh/gtnh-process-line-solver), can
read the calculator's too.

A `.gtnh` file holds hashed recipe ids, a voltage tier and the machine options per recipe, and the
plan's targets. Recipe contents, rates and machine counts are not in it: the calculator works them
out in the browser from its recipe data (`data.bin`) with a linear program and about 1,900 lines of
per-machine rules. This package ports that reader, solver and rule set to Python.

**Status:** under construction. This release reads `data.bin` and `.gtnh` files and maps the
calculator's goods ids; the solver, the machine rules and the plan output follow.

## The recipe data

The converter needs the calculator's `data.bin`, and **never ships it**: the data repository it
comes from ([ShadowTheAge/gtnh-data](https://github.com/ShadowTheAge/gtnh-data)) is published
without a license, since it is derived from Minecraft and mod content. Fetch it once into your user
cache:

```python
from gtnh_shadow_convert.fetch import fetch_data

path = fetch_data()  # downloads gtnh-data@d200440 and checks its sha256
```

| `data.bin` sha256 | Source | Pack |
|---|---|---|
| `624c9a20...a2fe73` | gtnh-data `d200440` (branch `2.9.0-v7`, "Import for 2.9.0", 2026-07-19), the file the calculator serves | GTNH `2.9.0-beta-2` |

**Which pack a file is** cannot be read from it, so the converter keeps this table. The 2.9 import
is recorded as `2.9.0-beta-2` because its exporter
([ShadowTheAge/nesql-exporter @ b5b896e](https://github.com/ShadowTheAge/nesql-exporter)) was
built against GregTech 5.09.54.20, the GregTech of that pack. A file not in the table needs its
pack named by hand.

The format carries a version number (`DATA_VERSION`, 7 today), and the calculator bumps it with
some of its pack imports. The reader refuses any version but 7 rather than guess at a new layout.

## Development

Python 3.14, and only 3.14:

```sh
py -3.14 -m venv .venv            # or python3.14 -m venv .venv
.venv/Scripts/activate            # or . .venv/bin/activate
pip install -e ".[dev]" -c constraints-dev.txt
pre-commit install
pytest
```

The tests never need the real `data.bin`. They build tiny synthetic ones with
`gtnh_shadow_convert.testing.SyntheticData`, which ships in the package so that consumers can do
the same. Tests that read the real file run only when `GTNH_SHADOW_DATA` points at it.

## Credits and license

MIT. This is a port of parts of [ShadowTheAge/gtnh](https://github.com/ShadowTheAge/gtnh) (MIT,
Copyright (c) 2025 ShadowTheAge) at commit
[`af8c798`](https://github.com/ShadowTheAge/gtnh/tree/af8c79888ec859913b27543c1381c3c11c24658f),
and `LICENSE` carries both copyright lines. The ported files:

| Calculator | Here |
|---|---|
| `src/repository.ts` (and the writer, `export/MemoryMappedPackConverter.cs`) | `databin.py`, `testing.py` |
| `src/page.ts` (the plan model) | `page.py` |
