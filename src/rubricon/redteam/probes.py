"""Red-teaming the evaluation itself.

An evaluation is a system under test. It has failure modes, it can be gamed, and
the people who will game it are not adversaries -- they are your own optimisation
process, doing exactly what you told it to.

Every probe here answers the same question in a different way: *how much of the
score is measuring the thing, and how much is measuring an artifact?*

Probes
------
``length_bias``       Does verbosity predict score independent of quality?
``lazy_baseline``     What does a strategy that ignores the content score?
``majority_baseline`` What does always predicting the modal label score?
``position_bias``     For pairwise judging, does presentation order move the winner?
``self_preference``   Does an LLM judge favour outputs from its own family?
``rubric_shortcut``   Can a single dimension reconstruct the composite? If so the
                      other five are decoration and the rubric is overclaiming.

The last one is the one people skip and it is the most damaging. A six-dimension
rubric whose composite is 0.96-correlated with one dimension costs six times the
annotation budget of a one-dimension rubric and delivers the same ranking. That
is not a measurement problem, it is a money problem, and it stays invisible
unless someone checks.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..core.schema import ModelResponse, TrackSpec


@dataclass
class ProbeResult:
    probe: str
    statistic: float
    threshold: float
    failed: bool
    interpretation: str
    detail: dict

    def to_dict(self) -> dict:
        return {
            "probe": self.probe,
            "statistic": None if math.isnan(self.statistic) else round(self.statistic, 4),
            "threshold": self.threshold,
            "failed": self.failed,
            "interpretation": self.interpretation,
            "detail": self.detail,
        }


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = statistics.fmean(x), statistics.fmean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    return num / (dx * dy) if dx and dy else float("nan")


def _spearman(x: Sequence[float], y: Sequence[float]) -> float:
    def rank(v: Sequence[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    return _pearson(rank(x), rank(y))


def _composites(spec: TrackSpec, annotations: Sequence[Mapping]) -> dict[str, float]:
    by_resp: dict[str, list[Mapping]] = defaultdict(list)
    for a in annotations:
        by_resp[a["response_id"]].append(a)
    out = {}
    for rid, group in by_resp.items():
        vals = [spec.rubric.composite(g["scores"]) for g in group]
        out[rid] = statistics.fmean(vals)
    return out


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------


def length_bias(
    spec: TrackSpec, responses: Sequence[ModelResponse], annotations: Sequence[Mapping],
    threshold: float = 0.30,
) -> ProbeResult:
    """Correlation between response length and composite score.

    A raw correlation is not damning on its own -- better answers are often
    longer. The probe therefore also reports the correlation *within* the clean
    subset, where quality is roughly held constant. Residual correlation there
    is much harder to explain as anything but a length preference.
    """
    comps = _composites(spec, annotations)
    pairs = [(len(r.text), comps[r.response_id]) for r in responses if r.response_id in comps]
    if len(pairs) < 5:
        return ProbeResult("length_bias", float("nan"), threshold, False,
                           "Insufficient data.", {})
    r_all = _spearman([p[0] for p in pairs], [p[1] for p in pairs])

    clean = [(len(r.text), comps[r.response_id]) for r in responses
             if not r.planted_failure and r.response_id in comps]
    r_clean = (
        _spearman([p[0] for p in clean], [p[1] for p in clean]) if len(clean) >= 5 else float("nan")
    )

    effective = r_clean if not math.isnan(r_clean) else r_all
    failed = abs(effective) > threshold
    return ProbeResult(
        "length_bias", effective, threshold, failed,
        (
            f"Within clean responses (quality approximately held constant), Spearman "
            f"rho between length and composite is {effective:.3f}. "
            + ("This exceeds the tolerance: part of the score is measuring verbosity, "
               "and any optimiser pointed at this rubric will learn to pad."
               if failed else
               "Below tolerance; length does not appear to be driving the score.")
        ),
        {"rho_all": round(r_all, 4), "rho_clean_only": None if math.isnan(r_clean) else round(r_clean, 4),
         "n_all": len(pairs), "n_clean": len(clean)},
    )


def lazy_baseline(
    spec: TrackSpec, responses: Sequence[ModelResponse], annotations: Sequence[Mapping],
    seed: int = 7,
) -> ProbeResult:
    """How well does a strategy that never reads the response do?

    Two lazy strategies are scored against the pool's own labels:
    always-modal-label, and label-drawn-from-the-marginal-distribution. The
    statistic is the exact-match rate of the best lazy strategy. If a machine
    that ignores the content matches human labels most of the time, the
    dimension carries little information and its cost is not justified.
    """
    dims = list(spec.rubric.dimension_keys)
    rng = random.Random(seed)
    per_dim: dict[str, dict] = {}
    for d in dims:
        vals = [int(a["scores"][d]) for a in annotations if d in a["scores"]]
        if not vals:
            continue
        counts = Counter(vals)
        modal, modal_n = counts.most_common(1)[0]
        modal_rate = modal_n / len(vals)
        levels, weights = zip(*sorted(counts.items()))
        marg = sum(
            1 for v in vals if v == rng.choices(levels, weights=weights, k=1)[0]
        ) / len(vals)
        per_dim[d] = {
            "modal_label": modal,
            "modal_match_rate": round(modal_rate, 4),
            "marginal_draw_match_rate": round(marg, 4),
            "n": len(vals),
            "entropy_bits": round(
                -sum((c / len(vals)) * math.log2(c / len(vals)) for c in counts.values()), 3
            ),
        }
    worst = max(per_dim, key=lambda k: per_dim[k]["modal_match_rate"]) if per_dim else ""
    stat = per_dim[worst]["modal_match_rate"] if worst else float("nan")
    failed = stat > 0.75
    return ProbeResult(
        "lazy_baseline", stat, 0.75, failed,
        (
            f"Dimension '{worst}' is matched {stat:.0%} of the time by always answering "
            f"{per_dim[worst]['modal_label']} without reading the response."
            + (" At that rate the dimension is close to constant and is not paying for "
               "its annotation cost; either oversample the rare levels or drop it."
               if failed else
               " Below the 75% tolerance, so annotators are doing work a constant cannot do.")
        ),
        {"per_dimension": per_dim},
    )


def _composite_excluding(spec: TrackSpec, scores: Mapping, drop: str) -> float:
    """Composite recomputed with ``drop``'s weight zeroed.

    Rebuilt from the same normalise-and-weight rule the rubric uses, including
    the critical-dimension gate, so the only difference from
    ``spec.rubric.composite`` is the excluded dimension.
    """
    acc = 0.0
    total_w = 0.0
    for dim in spec.rubric.dimensions:
        if dim.key not in scores:
            continue
        raw = scores[dim.key]
        if dim.is_failing(raw):
            return 0.0
        if dim.key == drop:
            continue
        numeric_levels = [float(x) for x in dim.levels]
        lo, hi = min(numeric_levels), max(numeric_levels)
        norm = 0.0 if hi == lo else (float(raw) - lo) / (hi - lo)
        acc += norm * dim.weight
        total_w += dim.weight
    return acc / total_w if total_w else 0.0


def rubric_shortcut(spec: TrackSpec, annotations: Sequence[Mapping],
                    threshold: float = 0.93) -> ProbeResult:
    """Can one dimension reconstruct the REST of the composite?

    The primary statistic is each dimension's correlation with the
    **leave-one-out composite** -- the composite recomputed with that dimension's
    own weight zeroed. Correlating a dimension against a composite that contains
    it is a part-whole correlation, and part of the resulting r is arithmetic
    rather than evidence: ``goal_completion`` carries weight 3.0 of the agentic
    rubric's 9.5, so it would correlate substantially with the composite even if
    it were statistically independent of every other dimension. Only the
    leave-one-out figure answers the question the probe is asking, which is
    whether the other dimensions are adding anything this one does not already
    say.

    The part-whole value is retained as ``correlation_to_composite_part_whole``
    so the inflation is visible rather than merely removed.

    Also reports the full inter-dimension correlation matrix, because a rubric
    whose dimensions are all mutually 0.8-correlated is measuring one construct
    under six names, and its "multi-dimensional" framing is misleading.
    """
    dims = list(spec.rubric.dimension_keys)
    by_resp: dict[str, list[Mapping]] = defaultdict(list)
    for a in annotations:
        by_resp[a["response_id"]].append(a)

    resp_ids = sorted(by_resp)
    dim_means: dict[str, list[float]] = {d: [] for d in dims}
    loo_means: dict[str, list[float]] = {d: [] for d in dims}
    comps: list[float] = []
    for rid in resp_ids:
        group = by_resp[rid]
        comps.append(statistics.fmean(spec.rubric.composite(g["scores"]) for g in group))
        for d in dims:
            vals = [g["scores"][d] for g in group if d in g["scores"]]
            dim_means[d].append(statistics.fmean(vals) if vals else float("nan"))
            loo_means[d].append(
                statistics.fmean(_composite_excluding(spec, g["scores"], d) for g in group)
            )

    usable = [d for d in dims if not any(math.isnan(v) for v in dim_means[d])]
    corr_part_whole = {d: _pearson(dim_means[d], comps) for d in usable}

    def _var(xs: Sequence[float]) -> float:
        return statistics.pvariance(xs) if len(xs) > 1 else 0.0

    corr_loo: dict[str, float] = {}
    degenerate: list[str] = []
    for d in usable:
        if _var(dim_means[d]) <= 1e-12:
            # The dimension itself is constant: it explains nothing, shortcut or
            # otherwise.
            corr_loo[d] = float("nan")
        elif _var(loo_means[d]) <= 1e-12:
            # The remainder of the rubric is constant across responses, so every
            # bit of variation in the composite comes from this one dimension.
            # Pearson is undefined here only because the remainder has no
            # variance to correlate with -- which is the most extreme possible
            # shortcut, not an absence of one. A one-dimension rubric lands here
            # too, correctly.
            corr_loo[d] = 1.0
            degenerate.append(d)
        else:
            corr_loo[d] = _pearson(dim_means[d], loo_means[d])
    corr_loo = {d: v for d, v in corr_loo.items() if not math.isnan(v)}
    matrix = {
        d1: {d2: round(_pearson(dim_means[d1], dim_means[d2]), 3) for d2 in dims if d2 != d1}
        for d1 in usable
    }

    best = max(corr_loo, key=lambda k: abs(corr_loo[k])) if corr_loo else ""
    stat = abs(corr_loo[best]) if best else float("nan")
    pw = abs(corr_part_whole[best]) if best else float("nan")
    redundant = [
        f"{d1}~{d2} r={v}"
        for d1, row in matrix.items() for d2, v in row.items()
        if v >= 0.85 and d1 < d2
    ]
    failed = stat >= threshold
    return ProbeResult(
        "rubric_shortcut", stat, threshold, failed,
        (
            f"'{best}' alone correlates r={stat:.3f} with the LEAVE-ONE-OUT composite "
            f"(the composite recomputed with '{best}' removed). The part-whole figure, "
            f"against a composite that includes '{best}' itself, is r={pw:.3f}; the gap "
            "between the two is arithmetic, not evidence, which is why the leave-one-out "
            "value is the one gated on."
            + (f" The remainder of the rubric is constant across responses, so all composite "
               f"variation comes from '{best}' by construction." if best in degenerate else "")
            + (" The composite is effectively a relabelling of one dimension; the other "
               "dimensions are being paid for and not used. Either drop them or reweight."
               if failed else
               " No single dimension reconstructs the rest of the composite, so the "
               "multi-dimensional structure is carrying real information.")
            + (f" Highly redundant pairs: {'; '.join(redundant)}." if redundant else "")
            + " CORPUS CAVEAT: the responses in this repository are generated from a single "
              "latent quality factor per response, so the dimensions are correlated by "
              "construction. The inter-dimension correlations below therefore partly measure "
              "the generative fixture model, not the rubric. On real data this probe is "
              "diagnostic of rubric redundancy; here it is a demonstration that the probe "
              "runs and reports, and its magnitudes should not be read as a finding about "
              "rubric design."
        ),
        {"primary_statistic": "leave_one_out",
         "correlation_to_loo_composite": {k: round(v, 4) for k, v in corr_loo.items()},
         "correlation_to_composite_part_whole": {
             k: round(v, 4) for k, v in corr_part_whole.items()},
         "part_whole_inflation": {
             k: round(abs(corr_part_whole[k]) - abs(corr_loo[k]), 4) for k in corr_loo},
         "degenerate_remainder_dimensions": degenerate,
         "inter_dimension_matrix": matrix,
         "redundant_pairs": redundant,
         "corpus_caveat": (
             "Fixture responses are generated from a single latent quality factor, so "
             "inter-dimension correlation on this corpus partly reflects the generative "
             "model rather than the rubric."
         )},
    )


def position_bias(spec: TrackSpec, responses: Sequence[ModelResponse],
                  annotations: Sequence[Mapping], seed: int = 11,
                  reference_effect: float | None = None) -> ProbeResult:
    """Order-effect fragility for pairwise comparison.

    No pairwise judging was actually run here, so this cannot *measure* a
    position bias. Asserting a flip rate under a stipulated order effect and
    then reporting pass/fail against it would be exactly the kind of laundered
    assumption this repository exists to catch -- an earlier version of this
    probe did precisely that and "failed" on every track, because the answer was
    baked into the input.

    What it does instead is a **sensitivity analysis**: it solves for the
    smallest order advantage that would flip 10% of pairwise comparisons. That
    number is a property of the observed score distribution and the pool's
    measured noise, both of which are real. It is then compared against the
    largest genuine between-system difference. If a pairwise artifact smaller
    than the real effect could reorder the results, pairwise reporting is
    fragile here regardless of any particular judge.
    """
    comps = _composites(spec, annotations)
    by_item: dict[str, list[str]] = defaultdict(list)
    for r in responses:
        if r.response_id in comps:
            by_item[r.item_id].append(r.response_id)

    by_resp: dict[str, list[float]] = defaultdict(list)
    for a in annotations:
        by_resp[a["response_id"]].append(spec.rubric.composite(a["scores"]))
    spreads = [statistics.stdev(v) for v in by_resp.values() if len(v) > 1]
    sigma = statistics.fmean(spreads) if spreads else 0.1

    pairs = [
        (comps[rids[i]], comps[rids[j]])
        for rids in by_item.values()
        for i in range(len(rids))
        for j in range(i + 1, len(rids))
    ]
    if not pairs:
        return ProbeResult("position_bias_fragility", float("nan"), 0.0, False,
                           "No pairs available.", {})

    def flip_rate(order_effect: float) -> float:
        rng = random.Random(seed)
        flips = 0
        for a, b in pairs:
            fwd = (a + order_effect + rng.gauss(0, sigma)) > (b + rng.gauss(0, sigma))
            rev = (a + rng.gauss(0, sigma)) > (b + order_effect + rng.gauss(0, sigma))
            flips += int(fwd != rev)
        return flips / len(pairs)

    # The flip rate at zero order effect is NOT zero: judgement noise alone
    # reverses near-tied pairs. Solving for "the effect that produces a 10% flip
    # rate" therefore returns 0.000 whenever baseline noise already exceeds 10%,
    # which on close systems is always -- an earlier version did exactly this and
    # reported a critical effect of exactly zero on all four tracks, i.e. it had
    # stopped measuring anything. The quantity of interest is the EXCESS flip
    # rate an order effect adds on top of the noise floor.
    baseline = flip_rate(0.0)
    target = baseline + 0.10

    lo, hi = 0.0, max(1.0, 6 * sigma)
    if flip_rate(hi) < target:
        critical = float("inf")
    else:
        for _ in range(30):
            mid = (lo + hi) / 2
            if flip_rate(mid) < target:
                lo = mid
            else:
                hi = mid
        critical = (lo + hi) / 2

    ref = reference_effect if reference_effect is not None else 0.0
    failed = bool(ref) and critical < ref
    return ProbeResult(
        "position_bias_fragility", critical if critical != float("inf") else 999.0,
        ref, failed,
        (
            f"Judgement noise alone (sigma={sigma:.3f}) already reverses {baseline:.0%} of "
            f"{len(pairs)} pairwise comparisons. An order advantage of "
            + (f"{critical:.3f} composite points" if critical != float("inf")
               else "more than the scale permits")
            + " would add a further 10 percentage points of flips on top of that floor."
            + (f" The largest real between-system difference on this track is {ref:.3f}, "
               "which is LARGER than the artifact needed to reorder results, so pairwise "
               "reporting here requires full order counterbalancing."
               if failed else
               (f" The largest real between-system difference is {ref:.3f}, so an order "
                "artifact would have to exceed the real effect before it mattered. "
                "Counterbalancing is still cheap insurance." if ref else
                " No between-system reference effect supplied; reported as context only."))
        ),
        {"n_pairs": len(pairs), "judge_sigma": round(sigma, 4),
         "baseline_noise_flip_rate": round(baseline, 4),
         "critical_excess_order_effect": None if critical == float("inf") else round(critical, 4),
         "reference_real_effect": round(ref, 4),
         "method": "Sensitivity analysis, not a measurement. No pairwise judging was run; "
                   "this solves for the artifact magnitude that would matter, measured as "
                   "EXCESS flips above the noise floor rather than absolute flips."},
    )


def annotator_leave_one_out(spec: TrackSpec, annotations: Sequence[Mapping],
                            ci_half_width: float | None = None) -> ProbeResult:
    """How much does the headline number depend on any single annotator?

    The tolerance is the reported CI half-width, not a fixed constant. That is
    the right comparison: if removing one annotator moves the mean further than
    the uncertainty you published, then your published uncertainty does not
    cover a source of variation you already know about.

    A fixed absolute threshold was the first implementation and it was wrong --
    it fired on every track regardless of how wide or narrow the intervals were,
    which made it uninformative.
    """
    comps_all = _composites(spec, annotations)
    base = statistics.fmean(comps_all.values()) if comps_all else float("nan")
    annotators = sorted({a["annotator_id"] for a in annotations})
    deltas = {}
    for aid in annotators:
        subset = [a for a in annotations if a["annotator_id"] != aid]
        if not subset:
            continue
        c = _composites(spec, subset)
        deltas[aid] = statistics.fmean(c.values()) - base
    worst = max(deltas, key=lambda k: abs(deltas[k])) if deltas else ""
    stat = abs(deltas[worst]) if worst else float("nan")
    tol = ci_half_width if ci_half_width and not math.isnan(ci_half_width) else 0.03
    failed = stat > tol
    return ProbeResult(
        "annotator_leave_one_out", stat, round(tol, 4), failed,
        (
            f"Removing '{worst}' moves the track mean by {deltas.get(worst, 0):+.4f}, against a "
            f"reported CI half-width of {tol:.4f}. "
            + ("The single-annotator sensitivity exceeds the published uncertainty, so the "
               "interval understates what is actually uncertain. Widen the interval to include "
               "annotator sampling, enlarge the pool, or reweight for measured bias."
               if failed else
               "Single-annotator sensitivity sits inside the published interval.")
        ),
        {"delta_by_annotator": {k: round(v, 4) for k, v in deltas.items()},
         "baseline_mean": round(base, 4),
         "tolerance_source": "reported CI half-width" if ci_half_width else "fallback constant"},
    )


def run_all(spec: TrackSpec, responses: Sequence[ModelResponse],
            annotations: Sequence[Mapping], ci_half_width: float | None = None,
            reference_effect: float | None = None) -> dict:
    probes = [
        length_bias(spec, responses, annotations),
        lazy_baseline(spec, responses, annotations),
        rubric_shortcut(spec, annotations),
        position_bias(spec, responses, annotations, reference_effect=reference_effect),
        annotator_leave_one_out(spec, annotations, ci_half_width=ci_half_width),
    ]
    failed = [p.probe for p in probes if p.failed]
    return {
        "n_probes": len(probes),
        "n_failed": len(failed),
        "failed_probes": failed,
        "probes": [p.to_dict() for p in probes],
        "verdict": (
            "Rubric shows no measured gameability on these probes."
            if not failed
            else f"Rubric is vulnerable on: {', '.join(failed)}. Findings that depend on the "
                 "affected mechanism must be caveated or withheld."
        ),
    }


__all__ = [
    "ProbeResult",
    "annotator_leave_one_out",
    "lazy_baseline",
    "length_bias",
    "position_bias",
    "rubric_shortcut",
    "run_all",
]
