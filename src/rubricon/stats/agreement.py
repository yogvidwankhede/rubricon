"""Inter-annotator agreement.

Why several coefficients instead of one
---------------------------------------
Every agreement coefficient encodes an assumption about chance. Reporting a
single number invites the reader to trust that assumption silently.

* **Krippendorff's alpha** handles missing data and arbitrary numbers of
  annotators per unit, and respects the measurement scale. It is the default.
* **Fleiss' kappa** is reported because reviewers expect it, and because a large
  alpha/kappa gap is diagnostic (it usually means ordinal structure that kappa
  is discarding).
* **Gwet's AC1** exists to expose the *kappa paradox*: when one category
  dominates, kappa collapses toward zero even at 95%+ raw agreement. A track
  showing kappa 0.11 / AC1 0.79 / raw 0.94 does not have an annotator problem,
  it has a prevalence problem, and the fix is stratified sampling, not retraining.

Getting this distinction wrong is the most expensive mistake in an annotation
program: it triggers weeks of unnecessary annotator retraining for a design flaw.

References
----------
Krippendorff, K. (2011). Computing Krippendorff's Alpha-Reliability.
Gwet, K. L. (2008). Computing inter-rater reliability and its variance in the
    presence of high agreement. Br. J. Math. Stat. Psychol. 61(1), 29-48.
Feinstein & Cicchetti (1990). High agreement but low kappa.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Hashable, Mapping, Sequence

Value = Hashable
# unit_id -> {annotator_id: value}
Reliability = Mapping[str, Mapping[str, Value]]


# --------------------------------------------------------------------------
# distance metrics
# --------------------------------------------------------------------------


def _delta_nominal(c: Value, k: Value, _n: Mapping[Value, float], _order: Sequence[Value]) -> float:
    return 0.0 if c == k else 1.0


def _delta_interval(c: Value, k: Value, _n: Mapping[Value, float], _order: Sequence[Value]) -> float:
    return (float(c) - float(k)) ** 2


def _delta_ratio(c: Value, k: Value, _n: Mapping[Value, float], _order: Sequence[Value]) -> float:
    cf, kf = float(c), float(k)
    if cf + kf == 0:
        return 0.0
    return ((cf - kf) / (cf + kf)) ** 2


def _delta_ordinal(
    c: Value, k: Value, n: Mapping[Value, float], order: Sequence[Value]
) -> float:
    """Krippendorff's ordinal metric.

    Distance depends on how much probability mass sits *between* the two ranks,
    so a disagreement across a sparsely-populated region of the scale counts for
    more than one across a crowded region.
    """
    if c == k:
        return 0.0
    i, j = order.index(c), order.index(k)
    if i > j:
        i, j = j, i
    between = sum(n[order[g]] for g in range(i, j + 1))
    return (between - (n[order[i]] + n[order[j]]) / 2.0) ** 2


_METRICS = {
    "nominal": _delta_nominal,
    "binary": _delta_nominal,
    "ordinal": _delta_ordinal,
    "interval": _delta_interval,
    "ratio": _delta_ratio,
}


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


@dataclass
class AgreementResult:
    coefficient: str
    value: float
    n_units: int
    n_annotators: int
    n_pairable: int
    metric: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "coefficient": self.coefficient,
            "value": None if self.value is None or math.isnan(self.value) else round(self.value, 4),
            "n_units": self.n_units,
            "n_annotators": self.n_annotators,
            "n_pairable": self.n_pairable,
            "metric": self.metric,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------
# Krippendorff's alpha
# --------------------------------------------------------------------------


def krippendorff_alpha(data: Reliability, metric: str = "nominal") -> AgreementResult:
    """Krippendorff's alpha via the coincidence-matrix formulation.

    ``data`` maps unit -> {annotator: value}. Units with fewer than two values
    are excluded from the coincidence matrix (they carry no pairing information)
    but are still counted in ``n_units`` so coverage loss stays visible.
    """
    if metric not in _METRICS:
        raise ValueError(f"unknown metric {metric!r}; choose from {sorted(_METRICS)}")
    delta = _METRICS[metric]

    annotators = sorted({a for vals in data.values() for a in vals})
    pairable = {u: v for u, v in data.items() if len(v) >= 2}

    # Coincidence matrix: each unit contributes pairs weighted by 1/(m_u - 1).
    coincidence: dict[tuple[Value, Value], float] = defaultdict(float)
    for vals in pairable.values():
        observed = list(vals.values())
        m = len(observed)
        w = 1.0 / (m - 1)
        for a in range(m):
            for b in range(m):
                if a != b:
                    coincidence[(observed[a], observed[b])] += w

    if not coincidence:
        return AgreementResult("krippendorff_alpha", float("nan"), len(data), len(annotators), 0, metric)

    values = sorted({v for pair in coincidence for v in pair}, key=_sort_key)
    n_c: dict[Value, float] = {v: 0.0 for v in values}
    for (c, k), w in coincidence.items():
        n_c[c] += w
    n_total = sum(n_c.values())

    if n_total <= 1:
        return AgreementResult("krippendorff_alpha", float("nan"), len(data), len(annotators), len(pairable), metric)

    # Single observed category => no variance to explain; alpha is undefined.
    if len(values) == 1:
        return AgreementResult(
            "krippendorff_alpha",
            float("nan"),
            len(data),
            len(annotators),
            len(pairable),
            metric,
            detail={"note": "degenerate: all annotators used a single category"},
        )

    d_obs = sum(w * delta(c, k, n_c, values) for (c, k), w in coincidence.items()) / n_total
    d_exp = sum(
        n_c[c] * n_c[k] * delta(c, k, n_c, values)
        for c in values
        for k in values
        if c != k
    ) / (n_total * (n_total - 1))

    alpha = 1.0 if d_exp == 0 else 1.0 - (d_obs / d_exp)
    return AgreementResult(
        "krippendorff_alpha",
        alpha,
        len(data),
        len(annotators),
        len(pairable),
        metric,
        detail={"D_observed": round(d_obs, 6), "D_expected": round(d_exp, 6)},
    )


def _sort_key(v: Value):
    try:
        return (0, float(v))
    except (TypeError, ValueError):
        return (1, str(v))


# --------------------------------------------------------------------------
# percent agreement, Fleiss' kappa, Gwet's AC1
# --------------------------------------------------------------------------


def percent_agreement(data: Reliability) -> AgreementResult:
    """Mean pairwise exact agreement across units with >= 2 annotations."""
    pairable = {u: v for u, v in data.items() if len(v) >= 2}
    if not pairable:
        return AgreementResult("percent_agreement", float("nan"), len(data), 0, 0)
    per_unit = []
    for vals in pairable.values():
        obs = list(vals.values())
        m = len(obs)
        agree = sum(1 for a in range(m) for b in range(a + 1, m) if obs[a] == obs[b])
        per_unit.append(agree / (m * (m - 1) / 2))
    annotators = {a for v in data.values() for a in v}
    return AgreementResult(
        "percent_agreement",
        sum(per_unit) / len(per_unit),
        len(data),
        len(annotators),
        len(pairable),
    )


def _category_counts(pairable: Reliability) -> tuple[list[Value], dict[str, Counter]]:
    cats = sorted({v for vals in pairable.values() for v in vals.values()}, key=_sort_key)
    counts = {u: Counter(vals.values()) for u, vals in pairable.items()}
    return cats, counts


def fleiss_kappa(data: Reliability) -> AgreementResult:
    """Fleiss' kappa, generalised to unequal numbers of raters per unit."""
    pairable = {u: v for u, v in data.items() if len(v) >= 2}
    annotators = {a for v in data.values() for a in v}
    if not pairable:
        return AgreementResult("fleiss_kappa", float("nan"), len(data), len(annotators), 0)

    cats, counts = _category_counts(pairable)
    if len(cats) == 1:
        return AgreementResult(
            "fleiss_kappa", float("nan"), len(data), len(annotators), len(pairable),
            detail={"note": "degenerate: single category observed"},
        )

    p_i = []
    for u, cnt in counts.items():
        r = sum(cnt.values())
        p_i.append((sum(c * (c - 1) for c in cnt.values())) / (r * (r - 1)))
    p_bar = sum(p_i) / len(p_i)

    # Category prevalence is the UNIT-AVERAGED marginal, (1/n) * sum_i r_ik/r_i,
    # not the rating-weighted marginal sum_i r_ik / sum_i r_i.
    #
    # The two coincide exactly when every unit has the same number of raters, so
    # the equal-rater reference checks against statsmodels cannot tell them
    # apart. Under unequal raters they diverge, and the rating-weighted form
    # lets heavily-rated units dominate the chance model. It also silently
    # disagreed with ``gwet_ac1`` in this same module, which already uses the
    # unit-averaged marginal -- so kappa and AC1 were reported side by side
    # under two different definitions of chance, which is precisely the
    # comparison the module docstring says is diagnostic. Verified against
    # irrCAC on a 25-unit unequal-rater set: -0.01786 (unit-averaged) vs
    # -0.02218 (rating-weighted).
    n_units_pairable = len(counts)
    p_j = {
        k: sum(c[k] / sum(c.values()) for c in counts.values()) / n_units_pairable
        for k in cats
    }
    p_e = sum(v * v for v in p_j.values())

    kappa = float("nan") if p_e == 1 else (p_bar - p_e) / (1 - p_e)
    return AgreementResult(
        "fleiss_kappa", kappa, len(data), len(annotators), len(pairable),
        detail={"P_observed": round(p_bar, 4), "P_expected": round(p_e, 4),
                "category_prevalence": {str(k): round(v, 4) for k, v in p_j.items()}},
    )


def gwet_ac1(data: Reliability) -> AgreementResult:
    """Gwet's AC1: chance correction that does not collapse under skew.

    Where kappa assumes raters guess in proportion to observed prevalence, AC1
    assumes chance agreement is highest for categories near 50% prevalence.
    Under heavy skew the two diverge sharply, and the divergence is the signal.
    """
    pairable = {u: v for u, v in data.items() if len(v) >= 2}
    annotators = {a for v in data.values() for a in v}
    if not pairable:
        return AgreementResult("gwet_ac1", float("nan"), len(data), len(annotators), 0)

    cats, counts = _category_counts(pairable)
    q = len(cats)
    if q == 1:
        return AgreementResult(
            "gwet_ac1", float("nan"), len(data), len(annotators), len(pairable),
            detail={"note": "degenerate: single category observed"},
        )

    p_a_terms, pi_terms = [], defaultdict(list)
    for cnt in counts.values():
        r = sum(cnt.values())
        p_a_terms.append(sum(c * (c - 1) for c in cnt.values()) / (r * (r - 1)))
        for k in cats:
            pi_terms[k].append(cnt[k] / r)

    p_a = sum(p_a_terms) / len(p_a_terms)
    pi = {k: sum(v) / len(v) for k, v in pi_terms.items()}
    p_e = sum(pi[k] * (1 - pi[k]) for k in cats) / (q - 1)

    ac1 = float("nan") if p_e == 1 else (p_a - p_e) / (1 - p_e)
    return AgreementResult(
        "gwet_ac1", ac1, len(data), len(annotators), len(pairable),
        detail={"P_observed": round(p_a, 4), "P_expected": round(p_e, 4),
                "max_prevalence": round(max(pi.values()), 4)},
    )


# --------------------------------------------------------------------------
# combined report + interpretation
# --------------------------------------------------------------------------

# Landis & Koch bands, used with the caveat below.
_BANDS = [
    (0.80, "substantial-to-perfect"),
    (0.67, "tentative (Krippendorff's minimum for cautious conclusions)"),
    (0.60, "moderate"),
    (0.40, "fair"),
    (0.20, "slight"),
    (float("-inf"), "poor"),
]


def interpret(alpha: float) -> str:
    if alpha is None or math.isnan(alpha):
        return "undefined"
    for threshold, label in _BANDS:
        if alpha >= threshold:
            return label
    return "poor"


# --------------------------------------------------------------------------
# uncertainty around alpha
# --------------------------------------------------------------------------


def alpha_interval(
    data: Reliability, metric: str = "ordinal", n_boot: int = 600,
    level: float = 0.95, seed: int = 0,
) -> dict | None:
    """Cluster bootstrap interval for Krippendorff's alpha.

    The cluster is the *unit* (a response), not the individual annotation: an
    annotation is not an independent draw, and resampling annotations would
    produce an interval roughly sqrt(replication) too narrow.

    This exists because alpha is quoted against hard thresholds (0.50, 0.667) at
    n=36-48 units, where its own sampling interval is around +/-0.15. A point
    estimate of 0.52 and a point estimate of 0.62 are frequently the same
    measurement, and reporting only the point estimate hides that.
    """
    from .precision import bootstrap_statistic  # local: avoids an import cycle

    units = [dict(v) for v in data.values() if len(v) >= 2]
    if len(units) < 2:
        return None

    def stat(sample: Sequence[Mapping[str, Value]]) -> float:
        rebuilt = {f"u{i}": v for i, v in enumerate(sample)}
        return krippendorff_alpha(rebuilt, metric=metric).value

    iv = bootstrap_statistic(units, stat, n_boot=n_boot, level=level, seed=seed)
    if math.isnan(iv.lo) or math.isnan(iv.hi):
        return None
    return iv.to_dict()


def straddles(ci: Mapping | None, threshold: float) -> bool:
    """True when ``ci`` fails to exclude ``threshold`` (so the side is unproven)."""
    if not ci:
        return False
    lo, hi = ci.get("lo"), ci.get("hi")
    if lo is None or hi is None or math.isnan(lo) or math.isnan(hi):
        return False
    return lo <= threshold <= hi


# --------------------------------------------------------------------------
# reliability of the composite
# --------------------------------------------------------------------------


def spearman_brown(rho_1: float, k: int) -> float:
    """Reliability of a mean of ``k`` exchangeable replications.

    ``rho_k = k*rho_1 / (1 + (k-1)*rho_1)``. Averaging k independent raters
    cancels part of their independent error, so the mean of three raters is a
    more reliable measurement than any one of them. Quoting the single-rater
    coefficient for a quantity that is actually a 3-rater mean understates the
    reliability of what was measured.
    """
    if rho_1 is None or math.isnan(rho_1) or k < 1:
        return float("nan")
    denom = 1.0 + (k - 1) * rho_1
    if abs(denom) < 1e-12:
        return float("nan")
    return min(1.0, k * rho_1 / denom)


def composite_reliability(
    spec, annotations: Sequence[Mapping], k: int = 3,
    n_boot: int = 600, seed: int = 0,
) -> dict:
    """Reliability of the quantity the pipeline actually compares.

    Every downstream comparison is made on the per-item mean of the WEIGHTED
    COMPOSITE, averaged over ``k`` annotators. Neither the mean of the
    per-dimension single-rater alphas nor any individual dimension's alpha is
    the reliability of that quantity:

    * the composite is a weighted sum, and a weighted sum of noisy-but-
      correlated parts is more reliable than its parts (the errors partly
      cancel), so the mean of per-dimension alphas understates it;
    * the reported number is a mean over ``k`` raters, so the single-rater
      coefficient has to be stepped up by Spearman-Brown.

    ``rho_1`` is Krippendorff's alpha on the INTERVAL metric with unit =
    response and value = that annotator's composite for that response, which is
    the right scale because the composite is continuous in [0, 1]. ``rho_k`` is
    ``rho_1`` after Spearman-Brown for the k-rater mean. Both are returned;
    downstream power calculations use ``rho_k`` because the compared quantity is
    the k-rater mean.

    ``spec`` needs only ``spec.rubric.composite(scores) -> float``.
    """
    data: dict[str, dict[str, Value]] = defaultdict(dict)
    for a in annotations:
        scores = a["scores"] if isinstance(a, dict) else a.scores
        rid = a["response_id"] if isinstance(a, dict) else a.response_id
        aid = a["annotator_id"] if isinstance(a, dict) else a.annotator_id
        data[rid][aid] = round(float(spec.rubric.composite(scores)), 6)

    res = krippendorff_alpha(dict(data), metric="interval")
    rho_1 = res.value
    rho_k = spearman_brown(rho_1, k)
    ci_1 = alpha_interval(dict(data), metric="interval", n_boot=n_boot, seed=seed)
    ci_k = None
    if ci_1:
        ci_k = dict(ci_1)
        ci_k["point"] = round(spearman_brown(ci_1["point"], k), 4)
        ci_k["lo"] = round(spearman_brown(ci_1["lo"], k), 4)
        ci_k["hi"] = round(spearman_brown(ci_1["hi"], k), 4)
        ci_k["width"] = round(ci_k["hi"] - ci_k["lo"], 4)

    return {
        "unit": "response_id",
        "value": "weighted rubric composite in [0,1]",
        "metric": "interval",
        "k_raters": k,
        "rho_1": None if math.isnan(rho_1) else round(rho_1, 4),
        "rho_k": None if math.isnan(rho_k) else round(rho_k, 4),
        "ci_rho_1": ci_1,
        "ci_rho_k": ci_k,
        "n_units": res.n_units,
        "n_pairable": res.n_pairable,
        "n_annotators": res.n_annotators,
        "method": (
            "Krippendorff interval alpha of the per-annotator composite "
            "(unit=response), stepped up to the k-rater mean by Spearman-Brown."
        ),
        "note": (
            "This -- not the mean of the per-dimension single-rater alphas -- is "
            "the reliability of the quantity the system comparisons are computed "
            "on, and it is what the power calculation consumes."
        ),
    }


def agreement_report(data: Reliability, scale: str = "ordinal",
                     n_boot: int = 600, seed: int = 0) -> dict:
    """Run the full battery and flag the kappa paradox when it appears."""
    alpha = krippendorff_alpha(data, metric=scale)
    raw = percent_agreement(data)
    kappa = fleiss_kappa(data)
    ac1 = gwet_ac1(data)
    ci = alpha_interval(data, metric=scale, n_boot=n_boot, seed=seed)

    paradox = (
        not math.isnan(kappa.value)
        and not math.isnan(ac1.value)
        and raw.value >= 0.85
        and kappa.value < 0.40
        and (ac1.value - kappa.value) > 0.25
    )

    return {
        "scale": scale,
        "krippendorff_alpha": alpha.to_dict(),
        "ci": ci,
        "percent_agreement": raw.to_dict(),
        "fleiss_kappa": kappa.to_dict(),
        "gwet_ac1": ac1.to_dict(),
        "interpretation": interpret(alpha.value),
        "kappa_paradox_detected": paradox,
        "paradox_note": (
            "High raw agreement with low kappa and a much higher AC1 indicates "
            "category prevalence skew, not annotator unreliability. Remedy is "
            "stratified oversampling of the rare category, not retraining."
        )
        if paradox
        else "",
    }


def per_dimension_agreement(
    annotations: Sequence[Mapping], dimension_keys: Sequence[str], scales: Mapping[str, str],
    n_boot: int = 600,
) -> dict:
    """Agreement for every rubric dimension, keyed on (response_id) as the unit."""
    out = {}
    for idx, dim in enumerate(dimension_keys):
        data: dict[str, dict[str, Value]] = defaultdict(dict)
        for a in annotations:
            scores = a["scores"] if isinstance(a, dict) else a.scores
            rid = a["response_id"] if isinstance(a, dict) else a.response_id
            aid = a["annotator_id"] if isinstance(a, dict) else a.annotator_id
            if dim in scores:
                data[rid][aid] = scores[dim]
        out[dim] = agreement_report(
            dict(data), scale=scales.get(dim, "ordinal"), n_boot=n_boot, seed=idx
        )
    return out


__all__ = [
    "AgreementResult",
    "agreement_report",
    "alpha_interval",
    "composite_reliability",
    "fleiss_kappa",
    "gwet_ac1",
    "interpret",
    "krippendorff_alpha",
    "per_dimension_agreement",
    "percent_agreement",
    "spearman_brown",
    "straddles",
]
