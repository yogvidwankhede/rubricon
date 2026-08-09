"""Guards the invest / iterate / hold / stop engine.

Class of regression protected here: an expensive wrong call at the portfolio
level, in either direction.

The two failure modes are symmetric and both are covered:

* Failing to recommend STOP when a construct is genuinely contested - the pool
  is demonstrably competent on gold, no dimension is usable, and adjudicators
  keep attributing disagreement to the definition. More labels buy precision
  around a quantity with no agreed referent.
* Recommending STOP when only ONE dimension of an otherwise sound rubric is
  broken. Mean alpha cannot tell those two situations apart, which is why the
  engine also consults ``alpha_max``. The regression test for that is
  ``test_strong_dimension_prevents_stop_and_names_the_broken_one``: an earlier
  engine, keyed on the mean alone, would have abandoned a track whose best
  dimension sat at 0.73.
"""

from __future__ import annotations

import math

from rubricon.core.schema import Recommendation
from rubricon.gates.decision import (
    DecisionInput,
    estimate_irreducible_share,
    recommend,
)


def _inp(**over):
    base = dict(
        track="t",
        depth="pilot",
        alpha_mean=0.80,
        alpha_min=0.75,
        alpha_by_dimension={"d1": 0.85, "d2": 0.80, "d3": 0.75},
        gold_accuracy=0.90,
        ci_half_width=0.03,
        mde=0.04,
        largest_effect=0.12,
        rubric_gap_rate=0.05,
        coverage_marginal_gap=0.05,
        n_items=100,
        n_annotations=300,
        detection_sensitivity=0.8,
    )
    base.update(over)
    return DecisionInput(**base)


# --------------------------------------------------------------------------
# irreducible share
# --------------------------------------------------------------------------


def test_irreducible_share_is_zero_at_perfect_agreement():
    assert estimate_irreducible_share(1.0, 0.9) == 0.0
    assert estimate_irreducible_share(1.0, 0.5) == 0.0


def test_irreducible_share_is_high_when_alpha_is_low_and_gold_is_high():
    # alpha 0.40 -> total disagreement 0.60 ; gold 0.95 -> execution error 0.05
    # reducible = 0.05, so (0.60 - 0.05) / 0.60 = 0.9167
    share = estimate_irreducible_share(0.40, 0.95)
    assert abs(share - (0.60 - 0.05) / 0.60) < 1e-9
    assert share > 0.85


def test_irreducible_share_is_low_when_the_pool_executes_badly():
    # A pool that cannot even hit gold explains its own disagreement.
    assert estimate_irreducible_share(0.40, 0.30) == 0.0
    assert estimate_irreducible_share(0.40, 0.45) < 0.10


def test_irreducible_share_propagates_nan():
    assert math.isnan(estimate_irreducible_share(float("nan"), 0.9))
    assert math.isnan(estimate_irreducible_share(0.5, float("nan")))


def test_irreducible_share_stays_in_the_unit_interval():
    for alpha in (-0.3, 0.0, 0.25, 0.5, 0.75, 1.0):
        for gold in (0.0, 0.3, 0.7, 1.0):
            share = estimate_irreducible_share(alpha, gold)
            assert 0.0 <= share <= 1.0


# --------------------------------------------------------------------------
# STOP
# --------------------------------------------------------------------------


def _contested_construct():
    """Low mean alpha, no usable dimension, high rubric-gap rate, competent pool."""
    return _inp(
        alpha_mean=0.42,
        alpha_min=0.28,
        alpha_by_dimension={"calibration": 0.38, "tone_respect": 0.44,
                            "over_refusal_cost": 0.28, "explanation_quality": 0.52},
        gold_accuracy=0.86,
        rubric_gap_rate=0.46,
        ci_half_width=0.05,
        mde=0.05,
        largest_effect=0.03,
    )


def test_contested_construct_profile_returns_stop():
    decision = recommend(_contested_construct())
    assert decision.recommendation is Recommendation.STOP
    assert "Stop investment" in decision.headline
    assert decision.irreducible_share >= 0.55
    assert decision.stop_criteria
    assert any("failure-mode catalogue" in a for a in decision.next_actions)
    assert any("structural indicators fired" in r for r in decision.rationale)


def test_stop_requires_a_competent_pool():
    """A pool that fails gold is a retraining problem, not a contested one."""
    incompetent = _contested_construct()
    incompetent.gold_accuracy = 0.55
    decision = recommend(incompetent)
    assert decision.recommendation is not Recommendation.STOP


def test_stop_survives_one_borderline_indicator():
    """Two of three indicators is enough; a brittle conjunction is not used."""
    inp = _contested_construct()
    inp.rubric_gap_rate = 0.10  # this indicator no longer fires
    decision = recommend(inp)
    assert decision.recommendation is Recommendation.STOP


# --------------------------------------------------------------------------
# the brittle-conjunction regression
# --------------------------------------------------------------------------


def test_strong_dimension_prevents_stop_and_names_the_broken_one():
    """One broken dimension in a sound rubric must not abandon the track.

    Mean alpha here (0.527) is below the STOP band, but the best dimension is
    at 0.73, so the correct action is to drop that dimension, not the track.
    """
    inp = _inp(
        alpha_mean=(0.73 + 0.66 + 0.19) / 3,
        alpha_min=0.19,
        alpha_by_dimension={"answer_correctness": 0.73,
                            "step_validity": 0.66,
                            "explanation_faithfulness": 0.19},
        gold_accuracy=0.88,
        rubric_gap_rate=0.05,
        coverage_marginal_gap=0.05,
        mde=0.05,
        largest_effect=0.12,
    )
    assert inp.alpha_mean < 0.55           # the mean alone would have said STOP
    assert max(inp.alpha_by_dimension.values()) >= 0.60

    decision = recommend(inp)
    assert decision.recommendation is Recommendation.ITERATE, (
        "a track with one strong dimension must be iterated, not stopped"
    )
    assert "explanation_faithfulness" in decision.headline or any(
        "explanation_faithfulness" in a for a in decision.next_actions
    )
    # The failing dimension is named explicitly in the actions.
    assert any("explanation_faithfulness" in a for a in decision.next_actions)
    # ... and the sound dimensions are named as the surviving composite.
    assert any(
        "answer_correctness" in a and "step_validity" in a
        for a in decision.next_actions
    )
    assert decision.stop_criteria


def test_broken_dimension_branch_reports_it_as_a_dimension_level_defect():
    inp = _inp(
        alpha_mean=0.60,
        alpha_min=0.22,
        alpha_by_dimension={"a": 0.82, "b": 0.76, "c": 0.22},
        rubric_gap_rate=0.02,
    )
    decision = recommend(inp)
    assert decision.recommendation is Recommendation.ITERATE
    assert any("dimension-level defect" in r for r in decision.rationale)
    assert decision.projected_cost_to_fix_usd is not None


# --------------------------------------------------------------------------
# ITERATE branches
# --------------------------------------------------------------------------


def test_high_rubric_gap_rate_iterates_on_the_instrument():
    inp = _inp(rubric_gap_rate=0.28, alpha_mean=0.72, alpha_min=0.65,
               alpha_by_dimension={"a": 0.72, "b": 0.65})
    decision = recommend(inp)
    assert decision.recommendation is Recommendation.ITERATE
    assert "rubric" in decision.headline
    assert any("bridge sample" in a for a in decision.next_actions)


def test_uniformly_low_alpha_without_contested_signals_is_a_calibration_problem():
    inp = _inp(
        alpha_mean=0.45,
        alpha_min=0.42,
        alpha_by_dimension={"a": 0.48, "b": 0.45, "c": 0.42},
        gold_accuracy=0.55,     # pool is NOT competent -> not a STOP
        rubric_gap_rate=0.04,
    )
    decision = recommend(inp)
    assert decision.recommendation is Recommendation.ITERATE
    assert "Recalibrate" in decision.headline


def test_coverage_gap_iterates_on_collection():
    inp = _inp(coverage_marginal_gap=0.45)
    decision = recommend(inp)
    assert decision.recommendation is Recommendation.ITERATE
    assert "coverage" in decision.headline
    assert any("thin and absent LEVELS" in a for a in decision.next_actions)


# --------------------------------------------------------------------------
# INVEST / HOLD
# --------------------------------------------------------------------------


def test_healthy_profile_returns_invest():
    decision = recommend(_inp())
    assert decision.recommendation is Recommendation.INVEST
    assert "Continue investing" in decision.headline
    assert any("clear their thresholds" in r for r in decision.rationale)
    assert any("Detection sensitivity" in r for r in decision.rationale)


def test_healthy_but_underpowered_track_is_not_stopped():
    inp = _inp(largest_effect=0.02, mde=0.06)
    decision = recommend(inp)
    assert decision.recommendation in (Recommendation.INVEST, Recommendation.HOLD)
    assert "cannot currently separate" in decision.headline
    assert any("no detectable difference" in a for a in decision.next_actions)


def test_hopelessly_underpowered_track_is_held():
    inp = _inp(largest_effect=0.002, mde=0.20, n_items=100)
    decision = recommend(inp)
    assert decision.recommendation is Recommendation.HOLD


def test_decision_to_dict_is_json_shaped():
    d = recommend(_inp()).to_dict()
    assert d["recommendation"] == "invest"
    assert isinstance(d["rationale"], list)
    assert isinstance(d["next_actions"], list)
    assert d["irreducible_share"] is None or isinstance(d["irreducible_share"], float)

    nan_share = recommend(_inp(gold_accuracy=float("nan"))).to_dict()
    assert nan_share["irreducible_share"] is None


# --------------------------------------------------------------------------
# pool competence as a STOP precondition
# --------------------------------------------------------------------------


def test_a_mostly_flagged_pool_blocks_the_stop_branch():
    """STOP asserts in writing that the pool is competent. It has to be.

    Gold accuracy alone does not establish competence: a pool can hit gold and
    still have most of its annotators flagged for bias, speed, or
    straightlining. In that state the contested-construct reading and the
    bad-pool reading are not separable, and the engine must not pick the
    irreversible one.
    """
    inp = _contested_construct()
    inp.flagged_annotator_fraction = 0.667
    decision = recommend(inp)

    assert decision.recommendation is Recommendation.ITERATE
    assert "Remediate" in decision.headline
    assert any("67%" in r for r in decision.rationale)
    assert any("precondition fails" in r for r in decision.rationale)
    assert any("Replace or re-anchor" in a for a in decision.next_actions)


def test_stop_is_reachable_when_the_pool_is_mostly_unflagged():
    inp = _contested_construct()
    inp.flagged_annotator_fraction = 0.333
    decision = recommend(inp)
    assert decision.recommendation is Recommendation.STOP
    assert any("of annotators flagged" in r for r in decision.rationale)


def test_flagged_fraction_defaults_to_zero_and_preserves_prior_behaviour():
    assert _inp().flagged_annotator_fraction == 0.0
    assert recommend(_contested_construct()).recommendation is Recommendation.STOP


def test_pool_remediation_only_preempts_the_structural_branch():
    """A healthy track with a flagged pool is not routed to remediation here.

    The pool-health BLOCK in the signal gate is what handles that case; this
    branch exists solely to stop STOP being asserted on an unestablished
    premise.
    """
    healthy = _inp(flagged_annotator_fraction=0.9)
    assert recommend(healthy).recommendation is Recommendation.INVEST
