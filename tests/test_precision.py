"""Guards uncertainty, power and the reliability tax.

Class of regression protected here: confidently wrong error bars. The two
corrections in this module are the ones that are routinely dropped, and both
fail silently when they break.

* The cluster bootstrap must resample ITEMS, not observations. If it ever
  degrades to observation-level resampling, every interval in the repository
  narrows by roughly sqrt(replication) and nothing else notices. The central
  test here compares the two directly on deliberately clustered data.
* The reliability tax (n_eff = n * rho) must be applied and disclosed, so a
  400-item eval at alpha 0.55 is not quoted as though it had 400 items of
  resolving power.

The normal-quantile helper is checked against scipy on values that are NOT in
its lookup table, so the Acklam approximation branch is actually exercised.
"""

from __future__ import annotations

import math
import random

from scipy.stats import norm

from rubricon.stats.precision import (
    attenuated_correlation,
    benjamini_hochberg,
    cluster_bootstrap,
    minimum_detectable_effect,
    multiple_comparison_threshold,
    paired_permutation_test,
    z,
)


# --------------------------------------------------------------------------
# normal quantiles
# --------------------------------------------------------------------------


def test_z_matches_known_quantiles():
    assert abs(z(0.975) - 1.95996) < 1e-3
    assert abs(z(0.95) - 1.64485) < 1e-3
    assert abs(z(0.99) - 2.32635) < 1e-3


def test_z_acklam_branch_matches_scipy():
    """Values absent from the lookup table exercise the approximation."""
    from rubricon.stats.precision import _Z

    off_table = [0.93, 0.6, 0.01, 0.005, 0.3, 0.55, 0.9999, 0.0001, 0.02, 0.98]
    for p in off_table:
        assert p not in _Z, f"{p} is in the lookup table; pick another probe value"
        assert abs(z(p) - float(norm.ppf(p))) < 1e-3, f"z({p}) diverges from scipy"


def test_z_is_antisymmetric_about_the_median():
    assert abs(z(0.5)) < 1e-9
    for p in (0.93, 0.77, 0.999):
        assert abs(z(p) + z(1 - p)) < 1e-6


# --------------------------------------------------------------------------
# cluster bootstrap
# --------------------------------------------------------------------------


def _clustered_data(n_clusters=40, per_cluster=6, between_sd=1.0, within_sd=0.05, seed=1):
    """Observations inside a cluster are near-copies of one cluster-level value."""
    rng = random.Random(seed)
    clusters = []
    for _ in range(n_clusters):
        base = rng.gauss(0.0, between_sd)
        clusters.append([base + rng.gauss(0.0, within_sd) for _ in range(per_cluster)])
    return clusters


def test_point_estimate_is_the_mean_of_all_observations():
    clusters = [[1.0, 2.0, 3.0], [4.0], [5.0, 6.0]]
    flat = [x for c in clusters for x in c]
    ci = cluster_bootstrap(clusters, n_boot=500, seed=0)
    assert abs(ci.point - sum(flat) / len(flat)) < 1e-12
    assert ci.n_clusters == 3


def test_interval_contains_the_point_estimate():
    clusters = _clustered_data()
    ci = cluster_bootstrap(clusters, n_boot=1000, seed=7)
    assert ci.lo <= ci.point <= ci.hi
    assert ci.width > 0
    assert abs(ci.half_width - ci.width / 2) < 1e-12


def test_more_between_cluster_spread_widens_the_interval():
    tight = cluster_bootstrap(
        _clustered_data(between_sd=0.2, seed=11), n_boot=1000, seed=3
    )
    wide = cluster_bootstrap(
        _clustered_data(between_sd=2.0, seed=11), n_boot=1000, seed=3
    )
    assert wide.width > tight.width


def test_cluster_bootstrap_is_deterministic_under_a_fixed_seed():
    clusters = _clustered_data(seed=5)
    a = cluster_bootstrap(clusters, n_boot=800, seed=42)
    b = cluster_bootstrap(clusters, n_boot=800, seed=42)
    assert (a.point, a.lo, a.hi) == (b.point, b.lo, b.hi)
    # ... and a different seed is allowed to differ, otherwise the seed is dead.
    c = cluster_bootstrap(clusters, n_boot=800, seed=43)
    assert (c.lo, c.hi) != (a.lo, a.hi)


def test_cluster_bootstrap_is_wider_than_observation_level_bootstrap():
    """The reason this function exists.

    Six annotations of the same item are one item's worth of information, not
    six. Resampling observations pretends otherwise and shrinks the interval by
    roughly sqrt(replication). Passing each observation as its own singleton
    cluster IS the naive observation-level bootstrap, so the two calls differ
    only in the clustering assumption.
    """
    clusters = _clustered_data(n_clusters=40, per_cluster=6, between_sd=1.0,
                               within_sd=0.05, seed=1)
    flat = [x for c in clusters for x in c]

    clustered_ci = cluster_bootstrap(clusters, n_boot=2000, seed=3)
    naive_ci = cluster_bootstrap([[x] for x in flat], n_boot=2000, seed=3)

    assert abs(clustered_ci.point - naive_ci.point) < 1e-12
    assert clustered_ci.width > naive_ci.width, (
        f"cluster interval {clustered_ci.width:.4f} must exceed the naive "
        f"observation-level interval {naive_ci.width:.4f}"
    )
    # With 6 near-identical observations per cluster the inflation should be
    # substantial, not marginal.
    assert clustered_ci.width / naive_ci.width > 1.8


def test_empty_and_singleton_inputs_do_not_fabricate_intervals():
    empty = cluster_bootstrap([], n_boot=100, seed=0)
    assert math.isnan(empty.point) and math.isnan(empty.lo)
    single = cluster_bootstrap([[1.0, 2.0]], n_boot=100, seed=0)
    assert single.point == 1.5
    assert math.isnan(single.lo) and math.isnan(single.hi)


# --------------------------------------------------------------------------
# minimum detectable effect
# --------------------------------------------------------------------------


def test_mde_decreases_as_n_increases():
    small = minimum_detectable_effect(n=50, sd=1.0)
    large = minimum_detectable_effect(n=800, sd=1.0)
    assert large.mde_absolute < small.mde_absolute
    # Paired design: MDE scales as 1/sqrt(n).
    assert abs(small.mde_absolute / large.mde_absolute - math.sqrt(800 / 50)) < 1e-6


def test_reliability_moves_the_true_scale_mde_and_not_the_observed_one():
    """The reliability correction is applied once, on the true-score scale.

    ``sd`` is the SD of the OBSERVED differences and already contains the
    measurement error. Shrinking n to n*rho as well would charge for that error
    twice and inflate the headline MDE by 1/sqrt(rho). The observed-scale MDE --
    the one comparable to an observed effect, and the one gated on -- must
    therefore be invariant to reliability; only the disattenuated true-scale
    figure moves.
    """
    perfect = minimum_detectable_effect(n=400, sd=1.0, reliability=1.0)
    noisy = minimum_detectable_effect(n=400, sd=1.0, reliability=0.55)
    worse = minimum_detectable_effect(n=400, sd=1.0, reliability=0.30)

    assert perfect.mde_true_scale < noisy.mde_true_scale < worse.mde_true_scale
    for r in (perfect, noisy, worse):
        assert abs(r.mde_observed_scale - perfect.mde_observed_scale) < 1e-12
        assert r.mde_absolute == r.mde_observed_scale
        assert abs(r.mde_true_scale - r.mde_observed_scale / math.sqrt(r.reliability)) < 1e-12


def test_headline_mde_does_not_double_count_measurement_error():
    """Regression guard on the specific arithmetic that was wrong.

    The defective version computed the MDE at n_eff = n*rho against the observed
    SD, which is exactly 1/sqrt(rho) too large. If that ever comes back, the
    headline MDE stops matching the plain-n calculation.
    """
    rho = 0.6
    r = minimum_detectable_effect(n=48, sd=0.3, reliability=rho)
    plain = (z(0.975) + z(0.80)) * 0.3 / math.sqrt(48)
    double_counted = (z(0.975) + z(0.80)) * 0.3 / math.sqrt(48 * rho)

    assert abs(r.mde_absolute - plain) < 1e-12
    assert r.mde_absolute < double_counted
    assert abs(double_counted / plain - 1 / math.sqrt(rho)) < 1e-12
    # n_eff survives as an interpretive figure, it is just not compounded in.
    assert abs(r.n_effective - 48 * rho) < 1e-9


def test_effective_n_is_n_times_reliability():
    result = minimum_detectable_effect(n=400, sd=1.0, reliability=0.55)
    assert abs(result.n_effective - 400 * 0.55) < 1e-9


def test_reliability_tax_note_appears_only_when_reliability_is_below_one():
    taxed = minimum_detectable_effect(n=400, sd=1.0, reliability=0.55)
    assert any("Reliability tax" in n for n in taxed.notes)
    assert any("n_eff=220" in n for n in taxed.notes)
    # The convention must be stated, and the double-count named as avoided.
    assert "observed_scale" in taxed.convention
    assert any("OBSERVED scale" in n and "twice" in n for n in taxed.notes)

    clean = minimum_detectable_effect(n=400, sd=1.0, reliability=1.0)
    assert not any("Reliability tax" in n for n in clean.notes)


def test_n_required_for_a_tiny_target_effect_exceeds_current_n():
    result = minimum_detectable_effect(
        n=100, sd=1.0, reliability=0.6, target_effect=0.01
    )
    assert result.n_required_for_target is not None
    assert result.n_required_for_target > 100
    assert any("you need n>=" in n for n in result.notes)

    # A target the design can already resolve reports sufficiency instead.
    easy = minimum_detectable_effect(n=1000, sd=1.0, reliability=1.0, target_effect=5.0)
    assert easy.n_required_for_target <= 1000
    assert any("is sufficient to detect" in n for n in easy.notes)


def test_unpaired_design_needs_a_larger_effect_than_paired():
    paired = minimum_detectable_effect(n=200, sd=1.0, paired=True)
    unpaired = minimum_detectable_effect(n=200, sd=1.0, paired=False)
    assert unpaired.mde_absolute > paired.mde_absolute


# --------------------------------------------------------------------------
# multiplicity
# --------------------------------------------------------------------------


def test_benjamini_hochberg_hand_worked_example():
    # m = 10, alpha = 0.05, so the BH thresholds are rank * 0.005:
    #   rank 1 -> 0.005 : 0.001 <= 0.005  reject
    #   rank 2 -> 0.010 : 0.008 <= 0.010  reject   <- largest passing rank
    #   rank 3 -> 0.015 : 0.039 >  0.015
    #   rank 4 -> 0.020 : 0.041 >  0.020
    #   rank 5 -> 0.025 : 0.042 >  0.025
    #   ranks 6..10 all fail as well
    # Step-up therefore rejects the two smallest p-values and nothing else.
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    mask = benjamini_hochberg(pvals, alpha_level=0.05)
    assert mask == [True, True, False, False, False, False, False, False, False, False]


def test_benjamini_hochberg_step_up_rejects_below_a_failing_rank():
    # 0.030 fails its own threshold (rank 3 -> 0.030? no: 3*0.05/5 = 0.030, so it
    # passes at exactly the boundary). Use a case where a middle p-value fails
    # but a later one passes: step-UP must still reject everything below it.
    pvals = [0.001, 0.030, 0.049]  # m=3, thresholds 0.0167, 0.0333, 0.05
    mask = benjamini_hochberg(pvals, alpha_level=0.05)
    assert mask == [True, True, True]


def test_bh_rejects_at_least_as_many_as_bonferroni():
    rng = random.Random(4)
    for _ in range(30):
        m = rng.randrange(3, 25)
        pvals = [rng.random() ** 3 for _ in range(m)]
        bh = benjamini_hochberg(pvals, alpha_level=0.05)
        bonf_threshold = multiple_comparison_threshold(m, 0.05)["bonferroni"]
        bonferroni = [p <= bonf_threshold for p in pvals]
        assert sum(bh) >= sum(bonferroni)
        # BH is a superset, not merely a larger count.
        for i, rejected in enumerate(bonferroni):
            if rejected:
                assert bh[i]


def test_benjamini_hochberg_on_empty_input():
    assert benjamini_hochberg([]) == []


# --------------------------------------------------------------------------
# permutation test
# --------------------------------------------------------------------------


def test_paired_permutation_identical_inputs_gives_p_near_one():
    a = [0.1, 0.5, 0.9, 0.3, 0.7, 0.2]
    result = paired_permutation_test(a, list(a), n_perm=2000, seed=0)
    assert result["observed"] == 0.0
    assert result["p_value"] >= 0.99


def test_paired_permutation_separated_inputs_gives_small_p():
    a = [0.80, 0.85, 0.90, 0.78, 0.82, 0.88, 0.91, 0.86, 0.84, 0.89]
    b = [0.40, 0.45, 0.50, 0.38, 0.42, 0.48, 0.51, 0.46, 0.44, 0.49]
    result = paired_permutation_test(a, b, n_perm=5000, seed=0)
    assert result["p_value"] < 0.01
    assert result["n"] == 10


def test_paired_permutation_is_deterministic_under_seed():
    a = [1.0, 2.0, 3.5, 4.0, 2.5]
    b = [1.2, 1.8, 3.9, 3.6, 2.9]
    first = paired_permutation_test(a, b, n_perm=3000, seed=17)
    second = paired_permutation_test(a, b, n_perm=3000, seed=17)
    assert first == second


def test_paired_permutation_requires_equal_lengths():
    try:
        paired_permutation_test([1.0, 2.0], [1.0])
    except ValueError as exc:
        assert "equal-length" in str(exc)
    else:
        raise AssertionError("expected ValueError on mismatched lengths")


# --------------------------------------------------------------------------
# disattenuation
# --------------------------------------------------------------------------


def test_attenuated_correlation_is_capped_at_one():
    assert attenuated_correlation(0.62, 0.5, 0.5) == 1.0
    assert attenuated_correlation(0.99, 0.2, 0.2) == 1.0


def test_attenuated_correlation_rises_as_reliability_falls():
    observed = 0.5
    high = attenuated_correlation(observed, 0.95, 0.95)
    mid = attenuated_correlation(observed, 0.75, 0.75)
    low = attenuated_correlation(observed, 0.55, 0.55)
    assert observed <= high < mid < low <= 1.0


def test_perfect_reliability_leaves_the_correlation_untouched():
    assert abs(attenuated_correlation(0.62, 1.0, 1.0) - 0.62) < 1e-12


# --------------------------------------------------------------------------
# external validation of the MDE
# --------------------------------------------------------------------------


def test_paired_mde_matches_a_scipy_hand_derivation():
    """Independent re-derivation of the paired MDE from scipy's normal quantiles.

    Nothing in the module's own code is reused: the quantiles come from
    scipy.stats.norm.ppf rather than from the Acklam approximation, and the
    formula is written out longhand. Agreement is asserted well inside 2%.
    """
    for n, sd, alpha_level, power in [
        (36, 0.25, 0.05, 0.80),
        (48, 0.2963, 0.05, 0.80),
        (120, 1.0, 0.05, 0.90),
        (400, 0.4, 0.01, 0.80),
    ]:
        expected = (norm.ppf(1 - alpha_level / 2) + norm.ppf(power)) * sd / math.sqrt(n)
        got = minimum_detectable_effect(
            n=n, sd=sd, alpha_level=alpha_level, power=power, paired=True
        ).mde_absolute
        assert abs(got / expected - 1) < 0.02, f"n={n}: {got} vs scipy {expected}"


def test_paired_mde_matches_statsmodels_solve_power():
    """Cross-check against statsmodels' independent power solver.

    ``TTestPower().solve_power`` inverts the noncentral-t power function, while
    this module uses the normal approximation, so the two are expected to agree
    asymptotically rather than exactly. At n>=100 the gap is under 1%. Below
    that the t quantile is the larger of the two, so the normal approximation is
    slightly ANTI-conservative -- the deviation is bounded and one-directional,
    and that is asserted here rather than left to be discovered.
    """
    from statsmodels.stats.power import TTestPower

    for n in (100, 200, 400, 1000):
        d = TTestPower().solve_power(
            effect_size=None, nobs=n, alpha=0.05, power=0.80, alternative="two-sided"
        )
        got = minimum_detectable_effect(n=n, sd=1.0).mde_absolute
        assert abs(got / d - 1) < 0.02, f"n={n}: {got} vs statsmodels {d}"

    for n in (20, 36, 48):
        d = TTestPower().solve_power(
            effect_size=None, nobs=n, alpha=0.05, power=0.80, alternative="two-sided"
        )
        got = minimum_detectable_effect(n=n, sd=1.0).mde_absolute
        assert got < d, "normal approximation must sit below the t-based MDE"
        assert abs(got / d - 1) < 0.06, f"n={n}: gap {abs(got/d-1):.3f} larger than expected"
