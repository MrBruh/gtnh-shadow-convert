# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-02

The first release: converts a ShadowTheAge calculator plan into gtnh-factory-flow plan JSON for
gtnh-process-line-solver (MrBruh/gtnh-process-line-solver#293).

### Added

- `convert(plan, data)` and the `gtnh-shadow-convert` command (`PLAN.gtnh --data DATA.bin`, and
  `fetch-data`): a solved plan written as gtnh-factory-flow plan JSON with a `converter` block, one
  node per recipe row, whole machine counts, one runtime variant per recipe, the controller block,
  the build options (coil, pipe and coke-oven casings, slices, the Chemical Plant's solid casing),
  and feeds and drains for everything the plan takes in and puts out.

- `databin`: a reader for the calculator's `data.bin` (format version 7), ported from its
  `repository.ts`, including the table that carries older exports' recipe ids forward. Any other
  format version is refused.
- `page`: the `.gtnh` plan model, read with exact numbers.
- `goods`: the calculator's goods ids spelled as a gtnh-factory-flow plan spells them, with an
  ore-dict input resolved to one concrete item.
- `fetch`: `fetch_data()` downloads the 2.9 `data.bin` into a user cache, checks its sha256 and
  records where it came from; a table maps each known file to its GTNH pack.
- `testing.SyntheticData`: builds small synthetic `data.bin` files for tests.
- `lp`: an exact linear-program solver (two-phase simplex over `Fraction`s, Bland's rule).
- `solve`: the calculator's solver, ported: the machine pick, choice validation, the rate math
  (parallels, overclocks, whole-tick rounding), linking goods within groups, and the LP. A missing
  recipe, an unbalanceable plan or a machine with no ported rule raises instead of being skipped.
- `machines`: the machine-rule model, the calculator's overclockers and its single-block rule, and
  123 of its 133 machine rules, the Industrial Coke Oven and ExxonMobil Chemical Plant among them.
  The other 10 raise `UnsupportedMachineError` with the reason.
- A tiered single block that the data lists among a recipe type's multiblocks (all of them, in the
  2.9 data) is computed as the calculator computes it, and its tier is read off its tooltip.
- A conformance suite: the calculator's 29 test plans and Jest snapshot, compared row by row; CI
  runs it against the real `data.bin`, fetched by its sha256 and cached.

[Unreleased]: https://github.com/MrBruh/gtnh-shadow-convert/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MrBruh/gtnh-shadow-convert/releases/tag/v0.1.0
