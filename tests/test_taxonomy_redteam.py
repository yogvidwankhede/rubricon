"""Guards failure-taxonomy coverage, detection sensitivity, and the red-team probes.

Class of regression protected here: confident false assurance.

* ``coverage`` must be computed against the DECLARED design, so a stratum level
  that the design claims and the corpus never sampled is named rather than
  silently dropped out of every aggregate.
* ``detection_sensitivity`` must distinguish "the rubric cannot see this
  failure" (a blind spot, and the worst possible outcome) from "we planted too
  few instances to tell" (a sampling gap). Conflating the two blames the
  instrument for a collection problem.
* ``rubric_shortcut`` must notice when the composite is a relabelling of one
  dimension, and ``lazy_baseline`` must notice a dimension that a constant can
  reproduce. Both are the cheap checks that stop a rubric from being paid for
  six times and used once.
"""

from __future__ import annotations

import math

from rubricon.redteam.probes import lazy_baseline, length_bias, rubric_shortcut
from rubricon.taxonomy.induce import (
    cliffs_delta,
    coverage,
    delta_magnitude,
    detection_sensitivity,
    investment_recommendations,
)

from .conftest import (
    annotation_row,
    make_dimension,
    make_item,
    make_response,
    make_rubric,
    make_spec,
)


# --------------------------------------------------------------------------
# Cliff's delta
# --------------------------------------------------------------------------


def test_cliffs_delta_is_plus_one_when_a_dominates_b():
    assert cliffs_delta([5, 6, 7], [1, 2, 3]) == 1.0


def test_cliffs_delta_is_minus_one_when_b_dominates_a():
    assert cliffs_delta([1, 2, 3], [5, 6, 7]) == -1.0


def test_cliffs_delta_is_zero_for_identical_distributions():
    sample = [1, 2, 3, 4, 5]
    assert cliffs_delta(sample, list(sample)) == 0.0
    assert cliffs_delta([1, 1, 1], [1, 1, 1]) == 0.0


def test_cliffs_delta_is_nan_on_empty_input():
    assert math.isnan(cliffs_delta([], [1, 2]))
    assert math.isnan(cliffs_delta([1, 2], []))


def test_delta_magnitude_bands():
    assert delta_magnitude(0.10) == "negligible"
    assert delta_magnitude(0.20) == "small"
    assert delta_magnitude(0.40) == "medium"
    assert delta_magnitude(0.80) == "large"
    assert delta_magnitude(-0.80) == "large"
    assert delta_magnitude(float("nan")) == "undefined"


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------


def _well_covered_items():
    """Two factors, two levels each, every level at n >= 4."""
    items = []
    n = 0
    for difficulty in ("easy", "hard"):
        for domain in ("legal", "medical"):
            for _ in range(5):
                items.append(
                    make_item(f"i{n:03d}", strata={"difficulty": difficulty, "domain": domain})
                )
                n += 1
    return items


def test_coverage_reports_no_marginal_gap_when_every_level_is_populated():
    spec = make_spec(
        strata_design={"difficulty": ["easy", "hard"], "domain": ["legal", "medical"]}
    )
    cov = coverage(spec, _well_covered_items())
    assert cov["marginal_gap_fraction"] == 0.0
    assert cov["absent_levels"] == []
    assert cov["thin_levels"] == []
    assert cov["total_declared_levels"] == 4
    assert cov["adequate_levels"] == 4
    assert cov["worst_balance_ratio"] == 1.0


def test_coverage_names_a_declared_level_with_no_items():
    spec = make_spec(
        strata_design={
            "difficulty": ["easy", "hard"],
            "domain": ["legal", "medical", "financial"],  # never sampled
        }
    )
    cov = coverage(spec, _well_covered_items())
    assert "domain=financial" in cov["absent_levels"]
    assert cov["marginal_gap_fraction"] > 0.0
    assert cov["populated_levels"] == 4
    assert cov["total_declared_levels"] == 5


def test_coverage_flags_thin_levels_separately_from_absent_ones():
    items = _well_covered_items()
    items.append(make_item("thin-0", strata={"difficulty": "brutal", "domain": "legal"}))
    spec = make_spec(
        strata_design={
            "difficulty": ["easy", "hard", "brutal"],
            "domain": ["legal", "medical"],
        }
    )
    cov = coverage(spec, items)
    assert cov["absent_levels"] == []
    assert any(t.startswith("difficulty=brutal") for t in cov["thin_levels"])
    assert cov["worst_balance_ratio"] < 0.25


def test_coverage_counts_undeclared_levels_without_crediting_them():
    items = _well_covered_items()
    items.append(make_item("rogue", strata={"difficulty": "impossible", "domain": "legal"}))
    spec = make_spec(
        strata_design={"difficulty": ["easy", "hard"], "domain": ["legal", "medical"]}
    )
    cov = coverage(spec, items)
    assert cov["marginals"]["difficulty"]["<undeclared>"] == 1
    assert cov["total_declared_levels"] == 4


def test_investment_recommendations_name_absent_levels_and_blind_spots():
    spec = make_spec(
        strata_design={"difficulty": ["easy", "hard"], "domain": ["legal", "ghost"]}
    )
    cov = coverage(spec, _well_covered_items())
    recs = investment_recommendations(cov, {"blind_spot_codes": ["F9"], "codes": []})
    assert any("domain=ghost" in r and r.startswith("COLLECT") for r in recs)
    assert any("F9" in r and r.startswith("INSTRUMENT") for r in recs)


# --------------------------------------------------------------------------
# detection sensitivity
# --------------------------------------------------------------------------


def _sensitivity_corpus(n_planted_detectable=8, n_planted_rare=2, n_clean=10):
    """A code the rubric registers, a code with too few instances, and clean data."""
    rubric = make_rubric(
        dimensions=(make_dimension(key="quality", levels=(0, 1, 2, 3)),),
        key="mini",
    )
    spec = make_spec(
        rubric=rubric,
        key="mini-sensitivity",
        failure_codes={
            "F-DETECT": "a failure the rubric registers",
            "F-RARE": "a failure with too few planted instances",
        },
    )

    responses, rows = [], []

    def add(rid, planted, score, tag=None):
        responses.append(make_response(rid, rid.replace("r", "i"), planted=planted))
        for ann in ("A1", "A2"):
            rows.append(
                annotation_row(rid, ann, {"quality": score},
                               item_id=rid.replace("r", "i"),
                               codes=(tag,) if tag else ())
            )

    for i in range(n_clean):
        add(f"rclean{i}", None, 3)
    for i in range(n_planted_detectable):
        add(f"rdet{i}", "F-DETECT", 0, tag="F-DETECT")
    for i in range(n_planted_rare):
        # Also genuinely depressed, so "not detected" can only come from the
        # underpowered rule and not from a weak effect.
        add(f"rrare{i}", "F-RARE", 0, tag="F-RARE")

    return spec, responses, rows


def test_detection_sensitivity_reports_a_registered_code_as_detected():
    spec, responses, rows = _sensitivity_corpus()
    report = detection_sensitivity(spec, responses, rows, min_planted=4)
    by_code = {c["code"]: c for c in report["codes"]}

    detected = by_code["F-DETECT"]
    assert detected["detected"] is True
    assert detected["n_planted"] == 8
    assert detected["best_delta"] == 1.0
    assert detected["magnitude"] == "large"
    assert detected["diagnosis"].startswith("Detected:")
    assert detected["coder_recall"] == 1.0


def test_underpowered_code_is_not_reported_as_a_blind_spot():
    spec, responses, rows = _sensitivity_corpus()
    report = detection_sensitivity(spec, responses, rows, min_planted=4)
    by_code = {c["code"]: c for c in report["codes"]}

    rare = by_code["F-RARE"]
    assert rare["n_planted"] == 2
    assert rare["detected"] is False
    assert "Underpowered" in rare["diagnosis"]
    assert "sampling gap" in rare["diagnosis"]

    assert "F-RARE" not in report["blind_spot_codes"]
    assert report["n_blind_spots"] == 0
    assert report["n_estimable"] == 1
    assert report["sensitivity_rate"] == 1.0


def test_a_code_the_rubric_cannot_see_is_a_blind_spot():
    """Planted often enough to be estimable, but the scores do not move."""
    rubric = make_rubric(
        dimensions=(make_dimension(key="quality", levels=(0, 1, 2, 3)),), key="mini"
    )
    spec = make_spec(rubric=rubric, key="mini-blind",
                     failure_codes={"F-INVISIBLE": "never registered"})
    responses, rows = [], []
    for i in range(10):
        rid = f"rclean{i}"
        responses.append(make_response(rid, f"i{rid}", planted=None))
        rows.append(annotation_row(rid, "A1", {"quality": 3}, item_id=f"i{rid}"))
        rows.append(annotation_row(rid, "A2", {"quality": 3}, item_id=f"i{rid}"))
    for i in range(8):
        rid = f"rbad{i}"
        responses.append(make_response(rid, f"i{rid}", planted="F-INVISIBLE"))
        rows.append(annotation_row(rid, "A1", {"quality": 3}, item_id=f"i{rid}"))
        rows.append(annotation_row(rid, "A2", {"quality": 3}, item_id=f"i{rid}"))

    report = detection_sensitivity(spec, responses, rows, min_planted=4)
    assert report["blind_spot_codes"] == ["F-INVISIBLE"]
    assert report["n_blind_spots"] == 1
    assert report["sensitivity_rate"] == 0.0
    assert "BLIND SPOT" in report["codes"][0]["diagnosis"]


def test_sensitivity_method_note_explains_the_underpowered_rule():
    spec, responses, rows = _sensitivity_corpus()
    report = detection_sensitivity(spec, responses, rows, min_planted=4)
    assert "underpowered rather than" in report["method_note"]


# --------------------------------------------------------------------------
# rubric shortcut
# --------------------------------------------------------------------------


def test_single_dimension_rubric_is_flagged_as_a_shortcut():
    """A rubric with nothing left after leave-one-out is a total shortcut.

    The leave-one-out composite has no variance here because there is no other
    dimension to carry any, so Pearson is undefined. That is the most extreme
    shortcut there is, not the absence of one, and the probe must report it as
    such rather than returning NaN and passing by default.
    """
    rubric = make_rubric(
        dimensions=(make_dimension(key="only", levels=(0, 1, 2, 3)),), key="mini"
    )
    spec = make_spec(rubric=rubric, key="mini-shortcut")
    rows = []
    for i in range(12):
        rid = f"r{i}"
        rows.append(annotation_row(rid, "A1", {"only": i % 4}, item_id=f"i{i}"))
        rows.append(annotation_row(rid, "A2", {"only": i % 4}, item_id=f"i{i}"))
    result = rubric_shortcut(spec, rows)
    assert result.failed is True
    assert abs(result.statistic - 1.0) < 1e-9
    assert result.detail["degenerate_remainder_dimensions"] == ["only"]
    assert "relabelling of one dimension" in result.interpretation


def test_shortcut_fires_when_every_other_dimension_is_constant():
    rubric = make_rubric(
        dimensions=(
            make_dimension(key="driver", levels=(0, 1, 2, 3)),
            make_dimension(key="constant_a", levels=(0, 1, 2, 3)),
            make_dimension(key="constant_b", levels=(0, 1, 2, 3)),
        ),
        key="mini",
    )
    spec = make_spec(rubric=rubric, key="mini-shortcut2")
    rows = []
    for i in range(12):
        rid = f"r{i}"
        scores = {"driver": i % 4, "constant_a": 2, "constant_b": 2}
        rows.append(annotation_row(rid, "A1", scores, item_id=f"i{i}"))
        rows.append(annotation_row(rid, "A2", scores, item_id=f"i{i}"))
    result = rubric_shortcut(spec, rows)
    assert result.failed is True
    # Part-whole: driver against a composite that still contains driver.
    assert result.detail["correlation_to_composite_part_whole"]["driver"] >= 0.99
    # Leave-one-out: the remainder is constant, so driver explains all of it.
    assert result.detail["correlation_to_loo_composite"]["driver"] == 1.0
    assert "driver" in result.detail["degenerate_remainder_dimensions"]


def test_independent_dimensions_do_not_trip_the_shortcut_probe():
    rubric = make_rubric(
        dimensions=(
            make_dimension(key="d1", levels=(0, 1, 2, 3)),
            make_dimension(key="d2", levels=(0, 1, 2, 3)),
            make_dimension(key="d3", levels=(0, 1, 2, 3)),
        ),
        key="mini",
    )
    spec = make_spec(rubric=rubric, key="mini-independent")
    import random

    rng = random.Random(3)
    rows = []
    for i in range(60):
        rid = f"r{i}"
        scores = {d: rng.randrange(4) for d in ("d1", "d2", "d3")}
        rows.append(annotation_row(rid, "A1", scores, item_id=f"i{i}"))
    result = rubric_shortcut(spec, rows)
    assert result.failed is False
    assert result.statistic < 0.93


# --------------------------------------------------------------------------
# lazy baseline
# --------------------------------------------------------------------------


def test_constant_dimension_is_caught_by_the_lazy_baseline():
    rubric = make_rubric(
        dimensions=(
            make_dimension(key="informative", levels=(0, 1, 2, 3)),
            make_dimension(key="always_two", levels=(0, 1, 2, 3)),
        ),
        key="mini",
    )
    spec = make_spec(rubric=rubric, key="mini-lazy")
    rows, responses = [], []
    for i in range(20):
        rid = f"r{i}"
        responses.append(make_response(rid, f"i{i}"))
        rows.append(
            annotation_row(rid, "A1", {"informative": i % 4, "always_two": 2},
                           item_id=f"i{i}")
        )
    result = lazy_baseline(spec, responses, rows)
    assert result.failed is True
    assert result.statistic == 1.0
    per_dim = result.detail["per_dimension"]
    assert per_dim["always_two"]["modal_match_rate"] == 1.0
    assert per_dim["always_two"]["entropy_bits"] == 0.0
    assert per_dim["informative"]["modal_match_rate"] < 0.75
    assert "always_two" in result.interpretation


def test_informative_dimensions_pass_the_lazy_baseline():
    rubric = make_rubric(
        dimensions=(make_dimension(key="informative", levels=(0, 1, 2, 3)),), key="mini"
    )
    spec = make_spec(rubric=rubric, key="mini-lazy2")
    rows, responses = [], []
    for i in range(40):
        rid = f"r{i}"
        responses.append(make_response(rid, f"i{i}"))
        rows.append(annotation_row(rid, "A1", {"informative": i % 4}, item_id=f"i{i}"))
    result = lazy_baseline(spec, responses, rows)
    assert result.failed is False
    assert abs(result.statistic - 0.25) < 1e-9


# --------------------------------------------------------------------------
# length bias
# --------------------------------------------------------------------------


def test_length_bias_detects_a_pure_length_preference():
    rubric = make_rubric(
        dimensions=(make_dimension(key="quality", levels=(0, 1, 2, 3)),), key="mini"
    )
    spec = make_spec(rubric=rubric, key="mini-length")
    responses, rows = [], []
    for i in range(20):
        rid = f"r{i}"
        responses.append(make_response(rid, f"i{i}", text="x" * (10 + 40 * i)))
        rows.append(annotation_row(rid, "A1", {"quality": min(3, i // 5)}, item_id=f"i{i}"))
    result = length_bias(spec, responses, rows)
    assert result.failed is True
    assert result.statistic > 0.30
    assert "measuring verbosity" in result.interpretation


def test_length_bias_is_quiet_when_length_carries_no_signal():
    rubric = make_rubric(
        dimensions=(make_dimension(key="quality", levels=(0, 1, 2, 3)),), key="mini"
    )
    spec = make_spec(rubric=rubric, key="mini-length2")
    # Every score level spans the full length range, so rank correlation is ~0.
    pairs = [(50, 3), (100, 0), (150, 2), (200, 1),
             (500, 3), (550, 0), (600, 2), (650, 1),
             (950, 3), (1000, 0), (900, 2), (850, 1)]
    responses, rows = [], []
    for i, (n, s) in enumerate(pairs):
        rid = f"r{i}"
        responses.append(make_response(rid, f"i{i}", text="x" * n))
        rows.append(annotation_row(rid, "A1", {"quality": s}, item_id=f"i{i}"))
    result = length_bias(spec, responses, rows)
    assert result.failed is False
    assert abs(result.statistic) <= 0.30
    assert result.detail["n_all"] == 12
    assert "does not appear to be driving" in result.interpretation
