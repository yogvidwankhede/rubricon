# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.5.1] - 2026-09-30
### Added
- Property-based tests (Hypothesis) for alpha invariances and the noise model.
- OpenSSF Scorecard workflow and badge; CI, release and licence badges; ORCID in CITATION.cff; `.zenodo.json` archive metadata.
### Changed
- Dependabot raises dependency ranges only when necessary.
- No change to any statistic or result.

## [0.5.0] - 2026-09-30
### Added
- `rubricon.gates.attenuation` (gate v2): claim checks that propagate gold-label noise
  into a paired comparison instead of blocking on a reliability floor.
  - `eta_from_disagreement`, `eta_majority`, `attenuation`: the binary noise model.
    Label noise leaves two systems' disagreement rate unchanged and shrinks the expected
    accuracy gap by `1 - 2 * eta_gold`.
  - `check_direction` (the only blocking check, a paired z-test at a pre-set `z*`),
    `attenuation_report` (true-scale gap and MDE, never blocks), and
    `check_contested_consistency` (the gap reverses between unanimous and split items).
- Tests validating the noise model against exact enumeration and simulation.
- CI workflow (tests on Python 3.12 and 3.14, plus a byte-for-byte reproduction job),
  Dependabot, issue/PR templates, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CITATION.cff,
  and a pinned `requirements-dev.lock`.

### Unchanged, on purpose
- `SignalGate` and its alpha floor keep their behaviour, so existing reports reproduce.
  A known-truth simulation in the companion audit repository found the floor costs power
  without reducing false claims at a matched false-claim rate; see that repository's paper.

## [0.4.0]
- State of the repository before this changelog was started (see git history).
