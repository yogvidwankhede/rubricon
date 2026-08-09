"""Guards the agreement mathematics.

Class of regression protected here: silently wrong reliability coefficients.
Every downstream gate, MDE and portfolio decision is a function of alpha, so an
off-by-a-term coincidence matrix or a mis-specified distance metric would move
every published number in the repository without failing anything else. The
anchor is Krippendorff's published 2011 worked example, checked for all four
distance metrics, plus the degenerate and boundary behaviours (perfect
agreement, independence, single-category data) and the kappa-vs-AC1 prevalence
paradox that the report layer must flag rather than blame on annotators.
"""

from __future__ import annotations

import math
import random

from rubricon.stats.agreement import (
    agreement_report,
    alpha_interval,
    composite_reliability,
    fleiss_kappa,
    gwet_ac1,
    krippendorff_alpha,
    percent_agreement,
    spearman_brown,
)

from .conftest import KRIPPENDORFF_2011_EXPECTED

TOL = 0.002


# --------------------------------------------------------------------------
# Krippendorff's alpha against the published reference dataset
# --------------------------------------------------------------------------


def test_krippendorff_reference_all_four_metrics(krippendorff_reference):
    for metric, expected in KRIPPENDORFF_2011_EXPECTED.items():
        result = krippendorff_alpha(krippendorff_reference, metric=metric)
        assert abs(result.value - expected) < TOL, (
            f"{metric} alpha {result.value:.6f} != published {expected} "
            f"(tolerance {TOL})"
        )
        assert result.coefficient == "krippendorff_alpha"
        assert result.metric == metric


def test_krippendorff_reference_shape(krippendorff_reference):
    result = krippendorff_alpha(krippendorff_reference, metric="nominal")
    assert result.n_units == 12
    assert result.n_annotators == 4
    # Unit 11 carries a single observation (only observer D) and therefore
    # contributes no pairs.
    assert result.n_pairable == 11


def test_unknown_metric_raises(krippendorff_reference):
    try:
        krippendorff_alpha(krippendorff_reference, metric="euclidean")
    except ValueError as exc:
        assert "unknown metric" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown distance metric")


# --------------------------------------------------------------------------
# boundary behaviour
# --------------------------------------------------------------------------


def test_alpha_is_one_for_perfect_agreement_with_multiple_categories():
    data = {f"u{i}": {"a": i % 4, "b": i % 4, "c": i % 4} for i in range(40)}
    for metric in ("nominal", "ordinal", "interval", "ratio"):
        result = krippendorff_alpha(data, metric=metric)
        assert result.value == 1.0, f"{metric} alpha should be exactly 1.0"


def test_alpha_near_zero_for_independent_labels():
    rng = random.Random(20240817)
    data = {
        f"u{i}": {f"ann{j}": rng.randrange(4) for j in range(4)} for i in range(500)
    }
    for metric in ("nominal", "ordinal", "interval"):
        value = krippendorff_alpha(data, metric=metric).value
        assert abs(value) < 0.15, f"{metric} alpha {value:.4f} is not near zero"


def test_alpha_is_nan_when_only_one_category_is_used():
    data = {f"u{i}": {"a": 2, "b": 2, "c": 2} for i in range(25)}
    result = krippendorff_alpha(data, metric="nominal")
    assert math.isnan(result.value)
    assert "degenerate" in result.detail["note"]


def test_ordinal_alpha_uses_ordering_information(krippendorff_reference):
    """Ordinal >= nominal on ordered data: near-miss disagreements cost less."""
    nominal = krippendorff_alpha(krippendorff_reference, metric="nominal").value
    ordinal = krippendorff_alpha(krippendorff_reference, metric="ordinal").value
    assert ordinal >= nominal

    # A second, purpose-built case: annotators are never more than one level
    # apart, which a nominal metric scores as total disagreement.
    near_miss = {f"u{i}": {"a": i % 5, "b": (i % 5) + 1} for i in range(40)}
    assert (
        krippendorff_alpha(near_miss, metric="ordinal").value
        > krippendorff_alpha(near_miss, metric="nominal").value
    )


# --------------------------------------------------------------------------
# percent agreement
# --------------------------------------------------------------------------


def test_percent_agreement_basic():
    data = {
        "u0": {"a": 1, "b": 1},          # 1/1 pairs agree
        "u1": {"a": 1, "b": 2},          # 0/1
        "u2": {"a": 3, "b": 3, "c": 1},  # 1/3 pairs agree
    }
    result = percent_agreement(data)
    expected = (1.0 + 0.0 + 1.0 / 3.0) / 3.0
    assert abs(result.value - expected) < 1e-12
    assert result.n_units == 3
    assert result.n_pairable == 3
    assert result.n_annotators == 3


def test_single_annotation_units_excluded_from_pairable_but_counted():
    data = {
        "u0": {"a": 1, "b": 1},
        "u1": {"a": 2},          # single annotation: no pairing information
        "u2": {"b": 3, "c": 3},
        "u3": {"c": 0},          # single annotation
    }
    raw = percent_agreement(data)
    assert raw.n_units == 4
    assert raw.n_pairable == 2
    assert raw.value == 1.0  # only the pairable units contribute, both agree

    alpha = krippendorff_alpha(data, metric="nominal")
    assert alpha.n_units == 4
    assert alpha.n_pairable == 2

    kappa = fleiss_kappa(data)
    assert kappa.n_units == 4 and kappa.n_pairable == 2

    ac1 = gwet_ac1(data)
    assert ac1.n_units == 4 and ac1.n_pairable == 2


# --------------------------------------------------------------------------
# Fleiss' kappa against arithmetic worked out here
# --------------------------------------------------------------------------


def test_fleiss_kappa_hand_computed_case():
    # 4 units, 2 raters each, 2 categories (A=0, B=1):
    #   u0: 0,0   u1: 0,0   u2: 0,1   u3: 1,1
    #
    # P_i = sum_k c_k(c_k - 1) / (r(r-1)) with r = 2:
    #   u0 = (2*1)/2 = 1 ; u1 = 1 ; u2 = 0 ; u3 = 1
    #   P_bar = (1 + 1 + 0 + 1) / 4 = 0.75
    #
    # Marginals over 8 ratings: category 0 appears 5 times, category 1 appears 3.
    #   p_0 = 5/8 = 0.625 , p_1 = 3/8 = 0.375
    #   P_e = 0.625^2 + 0.375^2 = 0.390625 + 0.140625 = 0.53125
    #
    # kappa = (0.75 - 0.53125) / (1 - 0.53125) = 0.21875 / 0.46875 = 7/15
    data = {
        "u0": {"r1": 0, "r2": 0},
        "u1": {"r1": 0, "r2": 0},
        "u2": {"r1": 0, "r2": 1},
        "u3": {"r1": 1, "r2": 1},
    }
    result = fleiss_kappa(data)
    assert abs(result.value - 7.0 / 15.0) < 1e-12
    # detail values are rounded to 4 decimal places by the implementation
    assert abs(result.detail["P_observed"] - 0.75) < 1e-4
    assert abs(result.detail["P_expected"] - 0.53125) < 1e-4


def test_fleiss_kappa_is_nan_on_a_single_category():
    data = {f"u{i}": {"a": 1, "b": 1} for i in range(6)}
    assert math.isnan(fleiss_kappa(data).value)
    assert math.isnan(gwet_ac1(data).value)


# --------------------------------------------------------------------------
# the kappa paradox
# --------------------------------------------------------------------------


def _skewed_pool(n_unanimous_zero=89, n_split=6):
    """Heavy prevalence skew: almost every annotator says category 0."""
    data = {}
    i = 0
    for _ in range(n_unanimous_zero):
        data[f"u{i:03d}"] = {"a": 0, "b": 0, "c": 0}
        i += 1
    for _ in range(n_split):
        data[f"u{i:03d}"] = {"a": 0, "b": 0, "c": 1}
        i += 1
    return data


def test_gwet_ac1_versus_kappa_paradox():
    data = _skewed_pool()
    assert len(data) == 95

    raw = percent_agreement(data).value
    kappa = fleiss_kappa(data).value
    ac1 = gwet_ac1(data).value

    assert raw >= 0.90, f"raw agreement should be high, got {raw:.4f}"
    assert kappa < 0.40, f"kappa should collapse under skew, got {kappa:.4f}"
    assert ac1 > kappa + 0.25, (
        f"AC1 ({ac1:.4f}) should be far above kappa ({kappa:.4f}) under skew"
    )
    assert ac1 >= 0.85

    report = agreement_report(data, scale="nominal")
    assert report["kappa_paradox_detected"] is True
    assert "prevalence skew" in report["paradox_note"]
    assert "retraining" in report["paradox_note"]


def test_no_paradox_flag_on_a_balanced_healthy_pool():
    # Balanced categories with genuine, high agreement: kappa and AC1 agree, so
    # the paradox flag must stay down.
    data = {}
    for i in range(60):
        v = i % 3
        data[f"u{i:03d}"] = {"a": v, "b": v, "c": v if i % 7 else (v + 1) % 3}
    report = agreement_report(data, scale="nominal")
    assert report["kappa_paradox_detected"] is False
    assert report["paradox_note"] == ""


def test_agreement_report_carries_every_coefficient(krippendorff_reference):
    report = agreement_report(krippendorff_reference, scale="ordinal")
    for key in ("krippendorff_alpha", "percent_agreement", "fleiss_kappa", "gwet_ac1"):
        assert key in report
        assert "value" in report[key]
    assert report["scale"] == "ordinal"
    assert abs(report["krippendorff_alpha"]["value"] - 0.8154) < 0.001
    assert report["interpretation"] == "substantial-to-perfect"


# --------------------------------------------------------------------------
# Fleiss' kappa: the marginal estimator under unequal raters
# --------------------------------------------------------------------------


# 5 units, 2 categories, between 2 and 4 raters per unit. Deliberately unequal:
# with equal raters the two candidate marginal estimators coincide exactly, so
# an equal-rater fixture cannot detect the defect this guards.
_UNEQUAL = {
    "u0": {"r1": 0, "r2": 0, "r3": 0},
    "u1": {"r1": 0, "r2": 1},
    "u2": {"r1": 1, "r2": 1, "r3": 0, "r4": 1},
    "u3": {"r1": 1, "r2": 0},
    "u4": {"r1": 0, "r2": 0},
}


def test_fleiss_kappa_uses_the_unit_averaged_marginal_under_unequal_raters():
    """The standard generalisation averages per-unit proportions, not ratings.

    P_i (unchanged by the marginal choice):
        u0 = 1, u1 = 0, u2 = 6/12 = 0.5, u3 = 0, u4 = 1  ->  P_bar = 0.5

    UNIT-AVERAGED marginal, (1/n) * sum_i r_ik / r_i:
        p_0 = (1 + 0.5 + 0.25 + 0.5 + 1) / 5 = 0.65 ; p_1 = 0.35
        P_e = 0.65^2 + 0.35^2 = 0.545
        kappa = (0.5 - 0.545) / (1 - 0.545) = -0.045 / 0.455

    RATING-WEIGHTED marginal, sum_i r_ik / sum_i r_i (the defect):
        p_0 = 8/13, p_1 = 5/13, P_e = 0.526627, kappa = -0.056249

    The two differ by a factor of 1.8 here. On a 25-unit missing-data set the
    same defect produced -0.02218 where irrCAC gives -0.01786.
    """
    result = fleiss_kappa(_UNEQUAL)

    expected = (0.5 - 0.545) / (1 - 0.545)
    assert abs(result.value - expected) < 1e-12

    rating_weighted_p_e = (8 / 13) ** 2 + (5 / 13) ** 2
    rating_weighted = (0.5 - rating_weighted_p_e) / (1 - rating_weighted_p_e)
    assert abs(result.value - rating_weighted) > 0.04, (
        "kappa collapsed back onto the rating-weighted marginal"
    )

    assert abs(result.detail["P_observed"] - 0.5) < 1e-4
    assert abs(result.detail["P_expected"] - 0.545) < 1e-4
    assert abs(result.detail["category_prevalence"]["0"] - 0.65) < 1e-4


def test_fleiss_and_gwet_share_one_marginal_estimator():
    """The two coefficients are reported side by side and must agree on chance.

    The module docstring makes the kappa/AC1 gap diagnostic of prevalence skew.
    That reading only holds if the two differ in their chance MODEL and not in
    how they estimate prevalence, so both must use the unit-averaged marginal.
    """
    kappa = fleiss_kappa(_UNEQUAL)
    ac1 = gwet_ac1(_UNEQUAL)
    prevalence = kappa.detail["category_prevalence"]
    assert abs(max(prevalence.values()) - ac1.detail["max_prevalence"]) < 1e-4


def test_fleiss_kappa_matches_statsmodels_on_equal_raters():
    """Equal raters: the reference implementation only supports this case."""
    from statsmodels.stats.inter_rater import fleiss_kappa as sm_fleiss

    rng = random.Random(20)
    n_units, n_raters, n_cats = 30, 4, 3
    data = {
        f"u{i}": {f"r{j}": rng.randrange(n_cats) for j in range(n_raters)}
        for i in range(n_units)
    }
    table = [
        [sum(1 for v in data[f"u{i}"].values() if v == c) for c in range(n_cats)]
        for i in range(n_units)
    ]
    assert abs(fleiss_kappa(data).value - float(sm_fleiss(table))) < 1e-10


# --------------------------------------------------------------------------
# uncertainty around alpha
# --------------------------------------------------------------------------


def test_alpha_interval_brackets_the_point_estimate(krippendorff_reference):
    ci = alpha_interval(krippendorff_reference, metric="interval", n_boot=400, seed=0)
    point = krippendorff_alpha(krippendorff_reference, metric="interval").value
    assert ci is not None
    assert abs(ci["point"] - round(point, 4)) < 1e-4
    assert ci["lo"] <= ci["point"] <= ci["hi"]
    assert ci["width"] > 0


def test_alpha_interval_is_deterministic_and_narrows_with_more_units():
    def build(n_units, seed):
        rng = random.Random(seed)
        out = {}
        for i in range(n_units):
            base = rng.randrange(4)
            out[f"u{i}"] = {
                f"r{j}": max(0, min(3, base + rng.choice((-1, 0, 0, 1))))
                for j in range(3)
            }
        return out

    small, large = build(20, 3), build(300, 3)
    a = alpha_interval(small, metric="ordinal", n_boot=400, seed=1)
    b = alpha_interval(small, metric="ordinal", n_boot=400, seed=1)
    assert a == b, "bootstrap interval must be reproducible under a fixed seed"

    wide = alpha_interval(small, metric="ordinal", n_boot=600, seed=1)
    tight = alpha_interval(large, metric="ordinal", n_boot=600, seed=1)
    assert tight["width"] < wide["width"]


def test_agreement_report_carries_an_interval(krippendorff_reference):
    rep = agreement_report(krippendorff_reference, scale="ordinal", n_boot=300)
    assert rep["ci"] is not None
    assert rep["ci"]["lo"] <= rep["krippendorff_alpha"]["value"] <= rep["ci"]["hi"]


# --------------------------------------------------------------------------
# composite reliability and Spearman-Brown
# --------------------------------------------------------------------------


def test_spearman_brown_matches_the_closed_form():
    for rho, k in [(0.75, 3), (0.369, 3), (0.5, 2), (0.2, 10)]:
        assert abs(spearman_brown(rho, k) - k * rho / (1 + (k - 1) * rho)) < 1e-12
    # k = 1 is the identity, and a perfect single rater cannot be improved.
    assert abs(spearman_brown(0.42, 1) - 0.42) < 1e-12
    assert abs(spearman_brown(1.0, 5) - 1.0) < 1e-12
    # Averaging raters always helps when the single-rater coefficient is positive.
    assert spearman_brown(0.4, 3) > 0.4


def test_composite_reliability_is_the_interval_alpha_of_the_composite():
    """The reported rho_1 must be the composite's OWN alpha, not a dimension mean."""
    from .conftest import annotation_row, make_dimension, make_rubric, make_spec

    rubric = make_rubric(
        dimensions=(
            make_dimension(key="d1", levels=(0, 1, 2, 3), weight=2.0),
            make_dimension(key="d2", levels=(0, 1, 2, 3), weight=1.0),
        ),
        key="mini",
    )
    spec = make_spec(rubric=rubric, key="mini-rel")

    rng = random.Random(11)
    rows = []
    for i in range(40):
        base1, base2 = rng.randrange(4), rng.randrange(4)
        for j, aid in enumerate(("A1", "A2", "A3")):
            rows.append(annotation_row(
                f"r{i}", aid,
                {"d1": max(0, min(3, base1 + rng.choice((-1, 0, 0, 1)))),
                 "d2": max(0, min(3, base2 + rng.choice((-1, 0, 0, 1))))},
                item_id=f"i{i}",
            ))

    rel = composite_reliability(spec, rows, k=3, n_boot=300)

    # Reconstruct the same quantity independently.
    data = {}
    for r in rows:
        data.setdefault(r["response_id"], {})[r["annotator_id"]] = round(
            float(rubric.composite(r["scores"])), 6
        )
    direct = krippendorff_alpha(data, metric="interval").value

    assert abs(rel["rho_1"] - round(direct, 4)) < 1e-4
    assert rel["k_raters"] == 3
    assert abs(rel["rho_k"] - round(spearman_brown(direct, 3), 4)) < 1e-3
    assert rel["rho_k"] > rel["rho_1"], "Spearman-Brown must step the coefficient up"
    assert rel["ci_rho_1"]["lo"] <= rel["rho_1"] <= rel["ci_rho_1"]["hi"]
    assert rel["ci_rho_k"]["lo"] <= rel["rho_k"] <= rel["ci_rho_k"]["hi"]
    assert rel["metric"] == "interval"
    assert rel["unit"] == "response_id"
