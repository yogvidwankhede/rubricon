"""Annotator quality: bias, drift, and gold-item calibration.

An annotation pool is a measuring instrument that changes while you use it.
Three failure modes matter and each needs a different response:

* **Bias** - an annotator's scores are systematically offset from the pool mean.
  Correctable post-hoc, or by re-anchoring that annotator. Not fatal.
* **Drift** - the pool's mean moves across batches while the item distribution
  holds constant. Fatal for longitudinal claims, because it manufactures
  "improvement" out of nothing. Detected by comparing batch means with the
  item mix held fixed.
* **Gold failure** - measured accuracy against seeded items with known answers.
  The only one of the three that is an absolute rather than relative signal,
  and therefore the only one that can catch the whole pool drifting together.

The third is why gold items exist. Bias and drift are both computed relative to
the pool, so a uniformly miscalibrated pool looks perfectly healthy on both.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass
class AnnotatorProfile:
    annotator_id: str
    n_annotations: int
    mean_score: float
    sd_score: float
    bias_vs_pool: float
    # Same offset recomputed over the NON-contested dimensions only. This is the
    # leniency figure; ``bias_vs_pool`` mixes leniency with value position.
    bias_vs_pool_uncontested: float = float("nan")
    # Offset over the contested dimensions only, net of the uncontested offset.
    # A position, not a defect. See ``profile_annotators``.
    contested_position: float = float("nan")
    gold_n: int = 0
    gold_exact: float = float("nan")
    gold_within_one: float = float("nan")
    gold_signed_error: float = float("nan")
    mean_duration_s: float = 0.0
    flags: list[str] = field(default_factory=list)
    # Deliberately NOT ``flags``. Entries here describe where an annotator sits
    # on the contested dimensions. That is a position, not a quality defect, and
    # it must not count toward the flagged fraction or trigger remediation.
    positions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def r(x):
            return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 4)

        return {
            "annotator_id": self.annotator_id,
            "n_annotations": self.n_annotations,
            "mean_score": r(self.mean_score),
            "sd_score": r(self.sd_score),
            "bias_vs_pool": r(self.bias_vs_pool),
            "bias_vs_pool_uncontested": r(self.bias_vs_pool_uncontested),
            "contested_position": r(self.contested_position),
            "gold_n": self.gold_n,
            "gold_exact": r(self.gold_exact),
            "gold_within_one": r(self.gold_within_one),
            "gold_signed_error": r(self.gold_signed_error),
            "mean_duration_s": r(self.mean_duration_s),
            "flags": self.flags,
            "positions": self.positions,
        }


def _composite(scores: Mapping[str, int], dims: Sequence[str]) -> float:
    vals = [float(scores[d]) for d in dims if d in scores]
    return sum(vals) / len(vals) if vals else float("nan")


def profile_annotators(
    annotations: Sequence[Mapping],
    dimension_keys: Sequence[str],
    gold_scores: Mapping[str, Mapping[str, int]] | None = None,
    bias_threshold: float = 0.35,
    gold_floor: float = 0.70,
    speed_floor_s: float = 45.0,
    contested_dimensions: Sequence[str] | None = None,
) -> dict:
    """Per-annotator bias, gold accuracy, and speed flags.

    ``gold_scores`` maps item_id -> {dimension: true_score} for seeded items.

    Leniency bias vs. value position
    --------------------------------
    An annotator's offset from the pool mean, computed over ALL dimensions,
    conflates two things this project exists to keep apart:

    * **leniency/harshness** -- a scoring calibration defect, correctable by
      re-anchoring that annotator, and a real quality problem;
    * **value position** -- a consistent stance on the dimensions where the
      rubric does not determine the answer. Two annotators at opposite ends of a
      contested dimension will sit far apart from the pool mean forever while
      both applying the rubric correctly. That is the disagreement the whole
      framework is built to surface. Reporting it as ``systematic_bias`` is a
      category error, and it produces exactly the wrong remedy: retraining
      someone for holding a defensible position.

    So when ``contested_dimensions`` is supplied, the offset is computed twice:
    ``bias_vs_pool_uncontested`` over the non-contested dimensions only, and
    ``contested_position`` over the contested ones (net of the uncontested
    offset, so it measures stance rather than stance-plus-leniency). Only the
    former can raise ``systematic_bias``. The latter is reported under
    ``contested_position:<value>``, which is explicitly NOT a quality flag and
    does not count toward the flagged fraction.

    ``speed_floor_s`` defaults to 45 seconds: the floor below which a
    multi-dimension rubric judgement on a full model response cannot plausibly
    have been made. It is a per-programme number and should be re-derived from
    the observed distribution rather than inherited -- an 8-second default,
    carried over from a single-dimension task, is unreachable here and silently
    disables the check.
    """
    gold_scores = gold_scores or {}
    contested = [d for d in (contested_dimensions or []) if d in set(dimension_keys)]
    uncontested = [d for d in dimension_keys if d not in set(contested)]

    by_ann: dict[str, list[Mapping]] = defaultdict(list)
    for a in annotations:
        by_ann[a["annotator_id"]].append(a)

    def pool_mean_over(dims: Sequence[str]) -> float:
        vals = [_composite(a["scores"], dims) for a in annotations]
        vals = [c for c in vals if not math.isnan(c)]
        return statistics.fmean(vals) if vals else float("nan")

    pool_mean = pool_mean_over(dimension_keys)
    pool_mean_unc = pool_mean_over(uncontested) if uncontested else float("nan")
    pool_mean_con = pool_mean_over(contested) if contested else float("nan")

    profiles = []
    for aid, rows in sorted(by_ann.items()):
        comps = [_composite(r["scores"], dimension_keys) for r in rows]
        comps = [c for c in comps if not math.isnan(c)]
        mean = statistics.fmean(comps) if comps else float("nan")
        sd = statistics.stdev(comps) if len(comps) > 1 else 0.0
        durations = [float(r.get("duration_s", 0) or 0) for r in rows]

        def offset(dims: Sequence[str], reference: float) -> float:
            if not dims or math.isnan(reference):
                return float("nan")
            vals = [_composite(r["scores"], dims) for r in rows]
            vals = [c for c in vals if not math.isnan(c)]
            return statistics.fmean(vals) - reference if vals else float("nan")

        bias_unc = offset(uncontested, pool_mean_unc)
        bias_con = offset(contested, pool_mean_con)
        # Net of the leniency offset: what is left is stance on the contested
        # dimensions, not a scoring level that applies everywhere.
        contested_pos = (
            bias_con - bias_unc
            if not (math.isnan(bias_con) or math.isnan(bias_unc))
            else bias_con
        )

        exact = within1 = gold_n = 0
        signed_sum = 0.0
        for r in rows:
            truth = gold_scores.get(r["item_id"])
            if not truth:
                continue
            for d in dimension_keys:
                if d in truth and d in r["scores"]:
                    gold_n += 1
                    diff = int(r["scores"][d]) - int(truth[d])
                    signed_sum += diff
                    if diff == 0:
                        exact += 1
                    if abs(diff) <= 1:
                        within1 += 1

        prof = AnnotatorProfile(
            annotator_id=aid,
            n_annotations=len(rows),
            mean_score=mean,
            sd_score=sd,
            bias_vs_pool=(mean - pool_mean) if not math.isnan(mean) else float("nan"),
            bias_vs_pool_uncontested=bias_unc,
            contested_position=contested_pos,
            gold_n=gold_n,
            gold_exact=(exact / gold_n) if gold_n else float("nan"),
            gold_within_one=(within1 / gold_n) if gold_n else float("nan"),
            gold_signed_error=(signed_sum / gold_n) if gold_n else float("nan"),
            mean_duration_s=statistics.fmean(durations) if durations else 0.0,
        )

        # ``systematic_bias`` fires on the UNCONTESTED offset when there are
        # contested dimensions to exclude, and on the overall offset otherwise.
        # Firing it on the overall offset in a track with contested dimensions
        # is what mislabelled two accurate senior annotators as harsh/lenient at
        # -0.49/+0.43 when their actual leniency was +0.03/-0.06.
        leniency = prof.bias_vs_pool_uncontested if uncontested else prof.bias_vs_pool
        if not math.isnan(leniency) and abs(leniency) > bias_threshold:
            direction = "lenient" if leniency > 0 else "harsh"
            prof.flags.append(f"systematic_bias:{direction}:{leniency:+.2f}")
        if gold_n and prof.gold_exact < gold_floor:
            prof.flags.append(f"gold_accuracy_below_floor:{prof.gold_exact:.2f}<{gold_floor}")
        if prof.mean_duration_s and prof.mean_duration_s < speed_floor_s:
            prof.flags.append(f"suspiciously_fast:{prof.mean_duration_s:.1f}s")
        if prof.sd_score < 0.15 and prof.n_annotations >= 10:
            prof.flags.append("low_variance:possible_straightlining")
        if not math.isnan(prof.contested_position) and abs(prof.contested_position) > bias_threshold:
            prof.positions.append(f"contested_position:{prof.contested_position:+.2f}")
        profiles.append(prof)

    flagged = [p.annotator_id for p in profiles if p.flags]
    positioned = [p.annotator_id for p in profiles if p.positions]
    return {
        "pool_mean": None if math.isnan(pool_mean) else round(pool_mean, 4),
        "n_annotators": len(profiles),
        "annotators": [p.to_dict() for p in profiles],
        "flagged_annotators": flagged,
        "flagged_fraction": round(len(flagged) / len(profiles), 3) if profiles else 0.0,
        "contested_dimensions": list(contested),
        "divergent_on_contested": positioned,
        "divergent_on_contested_fraction": (
            round(len(positioned) / len(profiles), 3) if profiles else 0.0
        ),
        "position_note": (
            "``contested_position`` is an annotator's offset on the contested dimensions "
            "net of their leniency offset. It is a value position, not a quality defect: "
            "it does not count toward the flagged fraction and it is not remediable by "
            "retraining. ``systematic_bias`` is computed over the NON-contested dimensions "
            "only, so it measures leniency and nothing else."
            if contested
            else "No contested dimensions declared for this track; bias is computed over "
                 "all dimensions and there is no value-position term to separate out."
        ),
    }


def detect_drift(
    annotations: Sequence[Mapping],
    dimension_keys: Sequence[str],
    min_effect: float = 0.20,
    alpha_level: float = 0.05,
    n_perm: int = 2000,
    seed: int = 0,
) -> dict:
    """Batch-over-batch movement in pool mean, tested against a null model.

    Why a permutation test rather than a threshold
    ----------------------------------------------
    The obvious implementation -- flag drift when the range of batch means
    exceeds some constant -- has no null model, and that makes it useless at
    exactly the sample sizes annotation programs run at. With 24 observations
    per batch and a within-batch SD near 0.75, the standard error of a batch
    mean is about 0.15, so the expected range of five such means under *no
    drift whatsoever* is roughly 0.35. A fixed 0.25 threshold therefore fires
    on almost every healthy track, and the resulting stream of false drift
    alarms is worse than no detector: people learn to dismiss it.

    This version shuffles batch labels across annotations, rebuilds the batch
    means, and asks how often pure chance produces a range at least as large as
    the observed one. Drift is reported only when the observed spread is both
    statistically distinguishable from that null AND large enough to matter --
    a significance-only rule would flag trivial-but-real movement at large n.

    Assumption
    ----------
    This isolates annotator drift only if item difficulty mix is stable across
    batches. The pipeline enforces that with serpentine difficulty-stratified
    assignment; on convenience-ordered batches the statistic confounds drift
    with mix, and the permutation null does not save you from that.
    """
    by_batch: dict[int, list[float]] = defaultdict(list)
    flat: list[tuple[int, float]] = []
    for a in annotations:
        c = _composite(a["scores"], dimension_keys)
        if not math.isnan(c):
            b = int(a.get("batch", 0))
            by_batch[b].append(c)
            flat.append((b, c))

    batches = sorted(by_batch)
    series = [
        {
            "batch": b,
            "n": len(by_batch[b]),
            "mean": round(statistics.fmean(by_batch[b]), 4),
            "sd": round(statistics.stdev(by_batch[b]), 4) if len(by_batch[b]) > 1 else 0.0,
        }
        for b in batches
    ]

    if len(series) < 2:
        return {"batches": series, "drift_detected": False, "span": 0.0,
                "slope_per_batch": 0.0, "p_value": None,
                "note": "fewer than two batches; drift undefined"}

    means = [s["mean"] for s in series]
    span = max(means) - min(means)
    first_last = means[-1] - means[0]

    n = len(means)
    xbar = (n - 1) / 2
    ybar = statistics.fmean(means)
    num = sum((i - xbar) * (m - ybar) for i, m in enumerate(means))
    den = sum((i - xbar) ** 2 for i in range(n))
    slope = num / den if den else 0.0

    # Permutation null: batch labels are exchangeable if there is no drift.
    rng = random.Random(seed)
    labels = [b for b, _ in flat]
    values = [v for _, v in flat]
    at_least = 0
    for _ in range(n_perm):
        rng.shuffle(labels)
        agg: dict[int, list[float]] = defaultdict(list)
        for b, v in zip(labels, values):
            agg[b].append(v)
        ms = [statistics.fmean(v) for v in agg.values() if v]
        if ms and (max(ms) - min(ms)) >= span - 1e-12:
            at_least += 1
    p_value = (at_least + 1) / (n_perm + 1)

    significant = p_value < alpha_level
    material = span >= min_effect
    detected = significant and material

    if detected:
        verdict = (
            f"Drift detected: batch-mean range {span:.3f} exceeds both the permutation "
            f"null (p={p_value:.4f}) and the materiality floor ({min_effect})."
        )
    elif significant and not material:
        verdict = (
            f"Statistically detectable but immaterial: range {span:.3f} is unlikely under "
            f"the null (p={p_value:.4f}) but below the {min_effect} floor that would change "
            "any decision. Monitor; do not act."
        )
    elif material and not significant:
        verdict = (
            f"Range {span:.3f} exceeds the materiality floor but is well within sampling "
            f"noise at this batch size (p={p_value:.4f}). Not evidence of drift -- this is "
            "the case a fixed-threshold detector gets wrong."
        )
    else:
        verdict = f"No drift: range {span:.3f}, p={p_value:.4f}."

    return {
        "batches": series,
        "span": round(span, 4),
        "first_to_last_delta": round(first_last, 4),
        "slope_per_batch": round(slope, 4),
        "p_value": round(p_value, 4),
        "n_permutations": n_perm,
        "min_effect": min_effect,
        "alpha_level": alpha_level,
        "statistically_significant": significant,
        "materially_large": material,
        "drift_detected": detected,
        "verdict": verdict,
        "assumption": (
            "Valid only if item difficulty mix is constant across batches. Rubricon "
            "assigns responses to batches by serpentine difficulty-stratified dealing "
            "within each system; do not reuse this statistic on convenience-ordered batches."
        ),
        "implication": (
            "Longitudinal comparisons across these batches are not defensible without "
            "re-anchoring the pool and re-annotating a bridge sample."
        )
        if detected
        else "",
    }


def rubric_gap_signals(adjudications: Sequence[Mapping], min_rate: float = 0.15) -> dict:
    """Adjudications flagged as rubric gaps rather than annotator error.

    High rates here mean the instrument is underspecified. This is the feedback
    loop that turns disagreement into rubric revisions instead of into blame.
    """
    total = len(adjudications)
    gaps = [a for a in adjudications if a.get("rubric_gap_flagged")]
    rate = len(gaps) / total if total else 0.0
    return {
        "n_adjudicated": total,
        "n_rubric_gaps": len(gaps),
        "rubric_gap_rate": round(rate, 4),
        "threshold": min_rate,
        "instrument_underspecified": rate > min_rate,
        "action": (
            "Rubric revision required before further collection: a majority of "
            "disagreements trace to definition ambiguity, not annotator error. "
            "Retraining annotators against an ambiguous rubric will not converge."
        )
        if rate > min_rate
        else "",
    }


__all__ = ["AnnotatorProfile", "detect_drift", "profile_annotators", "rubric_gap_signals"]
