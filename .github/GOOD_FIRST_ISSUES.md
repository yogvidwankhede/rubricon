# Draft "good first issue" tickets (not yet filed; the maintainer files them)

## 1. Helper: pairwise disagreement from a reliability matrix
`rubricon.gates.attenuation.eta_from_disagreement` takes a pairwise disagreement rate, but
callers compute it themselves. Add `pairwise_disagreement(matrix)` to
`rubricon/stats/agreement.py` (mean over items with >= 2 ratings of the share of disagreeing
rater pairs), with a test that it equals `1 - percent_agreement(matrix).value`.
*Skills:* Python, a small test. *Files:* `stats/agreement.py`, `tests/test_agreement.py`.

## 2. Doctest examples for the attenuation module
Add a short runnable example to each public function docstring in
`gates/attenuation.py` and run them in CI with `pytest --doctest-modules src/rubricon/gates/attenuation.py`.
*Acceptance:* examples pass; values match `tests/test_attenuation.py`.

## 3. Add Python 3.13 to the CI matrix
`.github/workflows/ci.yml` tests 3.12 and 3.14. Add 3.13, confirm `requirements-dev.lock`
installs, and update the README sentence about tested versions.

## 4. `rubricon validate --json`
`cmd_validate` in `cli.py` prints a human-readable table. Add a `--json` flag that prints the
same comparisons as JSON (coefficient, published value, computed value, absolute error), with a CLI test.

## 5. Guard against non-binary input in gate v2
`PairedGap.from_correctness` accepts any numbers. Raise `ValueError` if an element is not 0/1
(or bool), with a test. This prevents silently wrong z statistics from scores passed by mistake.
