"""Disagreement triage and adjudication.

Adjudication is where an annotation program either learns or calcifies. The
default practice -- send disagreements to a senior annotator, take their answer,
move on -- produces clean labels and no institutional knowledge.

The addition here is the ``rubric_gap`` attribution. Every adjudication asks a
second question after "what is the right label?": *could a competent annotator
have reached the wrong label by correctly following the written rubric?* If yes,
the disagreement is evidence about the instrument, not the annotator, and it
routes to a rubric revision instead of to a retraining queue.

Tracking that ratio is what lets the pipeline tell "our annotators need help"
apart from "our rubric is ambiguous" -- two diagnoses with opposite remedies
that look identical in an agreement coefficient.

Honest accounting
-----------------
Adjudicating only the high-disagreement tail and then reporting agreement over
the whole pool inflates the number. This module therefore records which
responses were adjudicated, and the reporting layer presents pre-adjudication
agreement as the headline reliability figure, with post-adjudication agreement
shown separately and labelled as a label-quality figure, not a reliability one.
"""

from __future__ import annotations

import hashlib
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..core.schema import Adjudication, Annotation, TrackSpec
from .effects import properties_for


@dataclass
class TriageItem:
    response_id: str
    item_id: str
    max_spread: float
    spread_by_dimension: dict[str, int]
    reason: str
    priority: float

    def to_dict(self) -> dict:
        return {
            "response_id": self.response_id,
            "item_id": self.item_id,
            "max_spread": self.max_spread,
            "spread_by_dimension": self.spread_by_dimension,
            "reason": self.reason,
            "priority": round(self.priority, 3),
        }


def triage(
    annotations: Sequence[Annotation | Mapping],
    spec: TrackSpec,
    spread_threshold: int = 2,
    critical_any_disagreement: bool = True,
) -> list[TriageItem]:
    """Select responses that need a human decision.

    Two entry routes:

    * **spread** -- any dimension where max(score) - min(score) meets the
      threshold. Straightforward magnitude-of-disagreement rule.
    * **critical dimension** -- *any* disagreement on a critical dimension,
      regardless of magnitude. A 1-vs-0 split on ``argument_fidelity`` decides
      whether the whole item scores zero, so a one-point gap there matters more
      than a three-point gap on ``efficiency``.
    """
    rows = [a if isinstance(a, dict) else a.to_dict() for a in annotations]
    by_resp: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_resp[r["response_id"]].append(r)

    critical_keys = {d.key for d in spec.rubric.dimensions if d.critical}
    weights = {d.key: d.weight for d in spec.rubric.dimensions}

    out: list[TriageItem] = []
    for rid, group in sorted(by_resp.items()):
        if len(group) < 2:
            continue
        spread: dict[str, int] = {}
        for dim in spec.rubric.dimensions:
            vals = [g["scores"][dim.key] for g in group if dim.key in g["scores"]]
            if len(vals) >= 2:
                spread[dim.key] = max(vals) - min(vals)
        if not spread:
            continue

        reasons = []
        hit_dims = [k for k, v in spread.items() if v >= spread_threshold]
        if hit_dims:
            reasons.append(f"spread>={spread_threshold} on {','.join(sorted(hit_dims))}")
        crit_hits = [k for k in critical_keys if spread.get(k, 0) >= 1]
        if critical_any_disagreement and crit_hits:
            reasons.append(f"any-disagreement on critical dimension {','.join(sorted(crit_hits))}")

        if not reasons:
            continue

        priority = sum(spread[k] * weights.get(k, 1.0) for k in spread)
        priority += 4.0 * len(crit_hits)  # critical disagreements jump the queue
        out.append(
            TriageItem(rid, group[0]["item_id"], max(spread.values()), spread,
                       "; ".join(reasons), priority)
        )

    out.sort(key=lambda t: (-t.priority, t.response_id))
    return out


def adjudicate(
    queue: Sequence[TriageItem],
    annotations: Sequence[Annotation | Mapping],
    spec: TrackSpec,
    adjudicator_id: str = "L1-adjudicator",
    capacity: int | None = None,
) -> list[Adjudication]:
    """Resolve the queue, attributing each case to rubric gap or annotator error.

    ``capacity`` models a real constraint: adjudication is expensive and the
    queue is usually longer than the budget. Cases are resolved in priority
    order and the unresolved remainder is visible to the reporting layer, so
    "we adjudicated the top 60%" is stated rather than implied.

    The rubric-gap attribution is driven by whether the disagreement fell on a
    dimension flagged ``contested``: those are exactly the cases where following
    the written rubric correctly can still produce different answers.
    """
    rows = [a if isinstance(a, dict) else a.to_dict() for a in annotations]
    by_resp: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_resp[r["response_id"]].append(r)

    props = properties_for(spec.key)
    contested = {k for k, v in props.items() if v.get("contested")}
    weights = {d.key: d.weight for d in spec.rubric.dimensions}
    work = list(queue)[: capacity] if capacity else list(queue)

    out: list[Adjudication] = []
    for t in work:
        group = by_resp.get(t.response_id, [])
        if not group:
            continue
        rng = random.Random(
            int(hashlib.sha256(t.response_id.encode()).hexdigest()[:8], 16)
        )
        final: dict[str, int] = {}
        for dim in spec.rubric.dimensions:
            vals = [g["scores"][dim.key] for g in group if dim.key in g["scores"]]
            if not vals:
                continue
            # The adjudicator is a strong annotator: median, breaking toward the
            # more conservative (lower) score on critical dimensions.
            med = statistics.median(vals)
            final[dim.key] = int(math_floor_half(med) if dim.critical else round(med))

        # A rubric gap requires that the contested dimension be the PRIMARY
        # driver of the disagreement, not merely present among the disputed
        # dimensions. The looser rule -- flag whenever any contested dimension
        # disagrees at all -- attributed 60%+ of adjudications to rubric
        # ambiguity on tracks with a single contested dimension, because triage
        # selects high-disagreement items and those almost always include the
        # contested dimension somewhere. That inflated rate then blocked claims
        # for the wrong reason.
        weighted = {
            k: v * weights.get(k, 1.0) for k, v in t.spread_by_dimension.items() if v >= 1
        }
        total_w = sum(weighted.values())
        contested_w = sum(v for k, v in weighted.items() if k in contested)
        gap_dims = sorted(k for k in weighted if k in contested)
        dominant = bool(total_w) and (contested_w / total_w) >= 0.50
        is_gap = dominant and rng.random() < 0.72

        out.append(
            Adjudication(
                response_id=t.response_id,
                item_id=t.item_id,
                final_scores=final,
                adjudicator_id=adjudicator_id,
                triage_reason=t.reason,
                original_annotations=tuple(sorted(g["annotation_id"] for g in group)),
                notes=(
                    f"Disagreement is driven by contested dimension(s) "
                    f"{','.join(gap_dims)} ({contested_w / total_w:.0%} of weighted spread); "
                    "a competent annotator could reach either label from the written rubric."
                    if is_gap
                    else "Resolved as annotator error; the rubric determines the answer."
                ),
                rubric_gap_flagged=is_gap,
            )
        )
    return out


def math_floor_half(x: float) -> int:
    """Floor to an integer. Used on critical dimensions so ties resolve strictly.

    Named for the case it exists to handle: a median of x.5 on a critical
    dimension resolves DOWN, to the more conservative score, rather than to the
    nearest even integer as ``round`` would. It is a plain floor, not a
    round-half-down -- the two differ nowhere on the medians this is applied to
    (which are always integers or half-integers) but the docstring previously
    described the narrower behaviour, which is not what the code does.
    """
    import math

    return int(math.floor(x + 1e-9))


def post_adjudication_agreement(
    adjudications: Sequence[Adjudication],
    annotations: Sequence[Annotation | Mapping],
    spec: TrackSpec,
) -> dict:
    """Label quality after adjudication. NOT a reliability figure.

    Every reported per-dimension alpha in this pipeline is computed
    PRE-adjudication over all replicated responses, and that is the reliability
    number. This function measures something different: how far the original
    annotations sat from the label that was finally adopted, on the adjudicated
    subset only.

    It cannot be compared to a reliability coefficient and it must never be
    quoted as one. Adjudication is applied to the disagreement tail by
    construction, so this subset is the worst-behaved part of the corpus; and the
    adjudicated label is derived from those same annotations, so agreement with
    it is not independent evidence. What it is good for is the label-quality
    question -- after adjudication, how much of the disagreement in the tail has
    been resolved into a single defensible label, and on which dimensions did the
    adjudicator have to overrule the most annotators.
    """
    if not adjudications:
        return {
            "n_adjudicated_responses": 0,
            "is_reliability_figure": False,
            "note": "No adjudications; nothing to measure.",
        }

    rows = [a if isinstance(a, dict) else a.to_dict() for a in annotations]
    by_resp: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_resp[r["response_id"]].append(r)

    per_dim_exact: dict[str, list[int]] = defaultdict(list)
    per_dim_within1: dict[str, list[int]] = defaultdict(list)
    overruled = 0
    total = 0
    composite_shift: list[float] = []

    for adj in adjudications:
        group = by_resp.get(adj.response_id, [])
        if not group:
            continue
        final = dict(adj.final_scores)
        for g in group:
            for dim, value in final.items():
                if dim not in g["scores"]:
                    continue
                diff = int(g["scores"][dim]) - int(value)
                per_dim_exact[dim].append(int(diff == 0))
                per_dim_within1[dim].append(int(abs(diff) <= 1))
                total += 1
                overruled += int(diff != 0)
        pre = statistics.fmean(spec.rubric.composite(g["scores"]) for g in group)
        composite_shift.append(spec.rubric.composite(final) - pre)

    def rate(d: Mapping[str, Sequence[int]]) -> dict:
        return {k: round(sum(v) / len(v), 4) for k, v in sorted(d.items()) if v}

    exact_all = [x for v in per_dim_exact.values() for x in v]
    within_all = [x for v in per_dim_within1.values() for x in v]
    return {
        "n_adjudicated_responses": len(composite_shift),
        "n_annotation_dimension_pairs": total,
        "exact_match_with_final_label": round(sum(exact_all) / len(exact_all), 4)
        if exact_all else None,
        "within_one_of_final_label": round(sum(within_all) / len(within_all), 4)
        if within_all else None,
        "overrule_rate": round(overruled / total, 4) if total else None,
        "exact_match_by_dimension": rate(per_dim_exact),
        "mean_composite_shift": round(statistics.fmean(composite_shift), 4)
        if composite_shift else None,
        "is_reliability_figure": False,
        "label": "label quality on the adjudicated subset",
        "note": (
            "LABEL QUALITY, NOT RELIABILITY. Computed only on the adjudicated "
            "disagreement tail, against a final label derived from the same "
            "annotations. Not comparable to the pre-adjudication alpha reported as "
            "this track's reliability, and not to be quoted in its place."
        ),
    }


def adjudication_summary(
    queue: Sequence[TriageItem], adjudications: Sequence[Adjudication], n_responses: int
) -> dict:
    resolved = len(adjudications)
    gaps = sum(1 for a in adjudications if a.rubric_gap_flagged)
    return {
        "n_responses": n_responses,
        "n_queued": len(queue),
        "queue_rate": round(len(queue) / n_responses, 4) if n_responses else 0.0,
        "n_resolved": resolved,
        "n_unresolved": max(0, len(queue) - resolved),
        "resolution_rate": round(resolved / len(queue), 4) if queue else 1.0,
        "n_rubric_gaps": gaps,
        "rubric_gap_rate": round(gaps / resolved, 4) if resolved else 0.0,
        "accounting_note": (
            "Headline reliability is computed PRE-adjudication over all replicated "
            "responses. Post-adjudication agreement is a label-quality figure and is "
            "not comparable to a reliability coefficient, because adjudication "
            "selectively targets the disagreement tail."
        ),
    }


__all__ = ["TriageItem", "adjudicate", "adjudication_summary",
           "post_adjudication_agreement", "triage"]
