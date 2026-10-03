# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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
- `machines`: the machine-rule model, the calculator's overclockers and its single-block rule.
