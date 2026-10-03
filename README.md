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

## Usage

```sh
pip install "gtnh-shadow-convert @ git+https://github.com/MrBruh/gtnh-shadow-convert@v0.1.1"
gtnh-shadow-convert fetch-data                         # once: prints where data.bin went
gtnh-shadow-convert MyPlan.gtnh --data <that path> -o MyPlan.json
```

or from Python:

```python
from gtnh_shadow_convert import convert

plan = convert("MyPlan.gtnh", "data.bin")  # a dict, ready for json.dump
```

A plan that does not convert raises a `ConversionError` (the command exits 2 with the reason):
an unknown recipe id, a plan that cannot be balanced, a machine whose rule is not ported, or a
recipe with no machine time. Things the calculator computes but the game would not run are kept and
reported as a `ConversionWarning`. The library never prints.

[gtnh-process-line-solver](https://github.com/MrBruh/gtnh-process-line-solver) calls this
in-process: `gtnh-solve MyPlan.gtnh --shadow-data data.bin`.

## How a plan is solved

The calculator's solver (`src/solver.ts`) is ported line for line, with two differences:

- **Exact arithmetic.** The calculator solves its linear program in floating point
  (javascript-lp-solver). Here every rate is a `Fraction` and the LP is an exact simplex
  (`lp.py`), so a machine count that is exactly 2 stays 2 when it is rounded up.
- **Failures are errors.** Where the calculator silently skips (a recipe id it cannot find, a plan
  that cannot be balanced, a machine it has no rule for), this raises a `ConversionError` naming
  the problem. Things the calculator computes but the game would not run (a recipe set below its
  own tier) are kept, with a `ConversionWarning`.

When a plan's optimum is not unique (two recipes making one good at the same cost), the exact
solver may return a different, equally optimal split than the calculator does.

## Machines

123 of the calculator's 133 machine rules are ported (`machines/`). These 10 are not yet, and a plan
that uses one raises `UnsupportedMachineError` naming it:

| Machine | Why not yet |
|---|---|
| Advanced Assembly Line | laser overclocking and per-input parallels |
| Nano Forge | nanite parallels and magmatter cost |
| PCB Factory | trace size, nanites and cooling |
| Dimensionally Transcendent Plasma Forge | catalysts and convergence |
| Quantum Force Transformer | focused output chances |
| Tree Growth Simulator | per-tool outputs |
| Eye of Harmony | success chance, dilation and astral arrays |
| Forge of the Gods, Absolute Baryonic Perfection and High Energy Laser Purification Units | the calculator has no rule for them either |

**Single blocks in the 2.9 data.** The export that built the 2.9 `data.bin` did not recognise any
single block (it sorts them by a "Voltage IN (LV)" tooltip line it no longer matched), so every
recipe type lists its tiered single blocks among its multiblocks, and the calculator computes them
with its fallback rule: normal overclocks, one parallel, on the multiblock path. The converter does
the same, so its numbers are the ones a player sees, and reads each block's tier off that tooltip
line itself to name the right tiered machine. The only difference from the single-block path is for
a recipe drawing more than one amp, which can come out one overclock lower.

## Conformance

`tests/test_conformance.py` solves the calculator's own 29 test plans and compares every recipe
row with the calculator's Jest snapshot (runs per minute, machine count, power and overclock
factors, overclock label). All 244 rows of the 23 plans whose machines are ported match; the other
6 plans fail with the unported machine named. CI runs it against the real `data.bin`.

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

## The plan it writes

The output is gtnh-factory-flow plan JSON, in the shape gtnh-process-line-solver's adapter reads
(`adapter/plan.py` there), with a `converter` block naming this package, the calculator commit, and
the `data.bin` (format version, sha256, pack) it was solved against.

- **One node per recipe row**, with its own recipe, since one recipe can sit in a plan twice at
  different tiers. A row the solved plan never runs is left out, with a warning.
- **Machine count** is the calculator's fractional count rounded up, exactly (`max(1, ceil)`).
- **Figures:** the recipe keeps its base EU/t and duration, and carries one runtime variant with
  the figures the row runs at: EU/t per parallel and the batch duration after overclocks, the speed
  bonus and rounding to whole ticks, with `parallel: 1`. The node carries the parallels. The adapter
  multiplies `variant.eut x node.parallel` for power and `amount x node.parallel / duration` for
  rates, so each figure is counted once.
- **The machine:** `source.machineBlock` is the controller block (`gregtech:gt.blockmachines@998`),
  `machineType` its name, and one machine handler says whether it is a `single` block or a
  `multiblock`. A single block is the tiered block of the row's tier ("Advanced Fluid Heater" at
  MV), read off the listed blocks' tooltips.
- **Options** that shape the build, in the arodoid fork's keys: `coilTier` (`hss_g`), and
  `machineConfigTiers` `pipeCasing` (`titanium`), `itemPipeCasing`, `cokeOvenCasing`
  (`heat_proof`), `cokeOvenSlices` (`slice-3`), and for the Chemical Plant `solidCasing`: the
  cheapest solid casing GT runs the recipe on, from its special value (`titanium` for 4), which the
  calculator itself does not model.
- **Goods:** items as `mod:name@damage` in lower case (damage 0 left off), fluids by their bare name,
  an ore-dict input as one concrete item. A non-consumed input (a programmed circuit) is
  `amount: 1, consumed: false`; a chanced output keeps its amount and adds `chance` (0 to 1).
- **Edges:** every good linked inside a group gets an edge from each row that makes it to each row
  that uses it. Every good the plan takes in gets a feed storage piped to its users, and every good
  it puts out (products and by-products) a drain.

A filled container in a recipe (a water cell) is split into its fluid and its empty container, as
the calculator links it.

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
| `src/page.ts` (the plan model, `ValidateChoices`) | `page.py`, `solve.py` |
| `src/solver.ts` | `solve.py`, `lp.py` (replacing javascript-lp-solver) |
| (new: the calculator has no export of its results) | `emit.py`, `cli.py` |
| `src/machines.ts` | `machines/` |
| `tests/*.gtnh`, `src/tests/__snapshots__/solver.test.ts.snap` (copied) | `tests/conformance/` |
