"""Invest / iterate / hold / stop.

The hardest recommendation an evaluation lead makes is "stop". It is easy to
justify more data forever: agreement can always be nudged, coverage can always
be widened, and no one is ever fired for collecting more labels.

This module forces the question by separating two things that get conflated:

* **Fixable-with-effort** - low agreement caused by an underspecified rubric,
  thin coverage, or an uncalibrated pool. Iterating pays off.
* **Structurally limited** - low agreement caused by genuine disagreement about
  what the right answer *is*. No amount of rubric refinement converges an
  annotator pool that disagrees about values rather than about facts. More data
  buys precision around an uninterpretable number.

The discriminator is the ratio of *irreducible* to *reducible* disagreement,
estimated by comparing agreement on items with objective ground truth (gold) to
agreement on judgement items. If a pool is accurate on gold but disagrees on
judgement items, the pool is fine and the construct is contested. That is a
STOP, and it is the recommendation this framework was built to be able to make.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.schema import Recommendation


@dataclass
class DecisionInput:
    track: str
    depth: str
    alpha_mean: float
    alpha_min: float
    alpha_by_dimension: dict[str, float]
    gold_accuracy: float
    ci_half_width: float
    mde: float
    largest_effect: float
    rubric_gap_rate: float
    coverage_marginal_gap: float
    n_items: int
    n_annotations: int
    detection_sensitivity: float | None = None  # recall on planted failures
    cost_per_1k_labels_usd: float = 0.0
    # Fraction of the annotator pool carrying quality flags. Part of the
    # pool-competence precondition: gold accuracy alone can be high while a
    # majority of the pool is flagged for bias, speed, or straightlining, and
    # the engine must not assert "the pool is competent" in that state.
    flagged_annotator_fraction: float = 0.0


@dataclass
class Decision:
    track: str
    recommendation: Recommendation
    headline: str
    rationale: list[str] = field(default_factory=list)
    irreducible_share: float = float("nan")
    next_actions: list[str] = field(default_factory=list)
    stop_criteria: list[str] = field(default_factory=list)
    projected_cost_to_fix_usd: float | None = None

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "recommendation": self.recommendation.value,
            "headline": self.headline,
            "rationale": self.rationale,
            "irreducible_share": None
            if math.isnan(self.irreducible_share)
            else round(self.irreducible_share, 3),
            "next_actions": self.next_actions,
            "stop_criteria": self.stop_criteria,
            "projected_cost_to_fix_usd": self.projected_cost_to_fix_usd,
        }


def estimate_irreducible_share(alpha: float, gold_accuracy: float) -> float:
    """Fraction of observed disagreement attributable to a contested construct.

    Intuition: gold items have a defensible right answer, so accuracy on gold
    upper-bounds how well this pool *can* execute the rubric. If the pool
    executes well (high gold accuracy) but still disagrees on judgement items
    (low alpha), the residual disagreement is about the construct, not the
    execution.

    Returns a value in [0, 1]. This is a heuristic decomposition, not an
    identified causal estimate; it is a decision aid, and it is labelled as one
    everywhere it is reported.
    """
    if math.isnan(alpha) or math.isnan(gold_accuracy):
        return float("nan")
    execution_ceiling = max(0.0, min(1.0, gold_accuracy))
    total_disagreement = max(0.0, 1.0 - max(0.0, alpha))
    if total_disagreement <= 1e-9:
        return 0.0
    # Disagreement the pool's demonstrated execution error can account for.
    reducible = min(total_disagreement, 1.0 - execution_ceiling)
    return max(0.0, min(1.0, (total_disagreement - reducible) / total_disagreement))


def recommend(inp: DecisionInput, unit_label_cost_usd: float = 0.85) -> Decision:
    irreducible = estimate_irreducible_share(inp.alpha_mean, inp.gold_accuracy)
    rationale: list[str] = []
    actions: list[str] = []

    rationale.append(
        f"Mean alpha across dimensions {inp.alpha_mean:.3f} "
        f"(worst dimension {inp.alpha_min:.3f}); gold accuracy {inp.gold_accuracy:.0%}."
    )
    rationale.append(
        f"95% CI half-width {inp.ci_half_width:.3f}; MDE {inp.mde:.3f}; "
        f"largest observed between-system effect {inp.largest_effect:.3f}."
    )

    # ---- STOP: construct is contested, not the instrument -----------------
    #
    # The ``alpha_max`` condition is what separates "this whole construct is
    # contested" from "one dimension of an otherwise sound rubric is broken".
    # Mean alpha cannot tell those apart: a track with five good dimensions and
    # one catastrophic one has the same mean as a track that is uniformly
    # mediocre, and the correct action differs completely -- drop a dimension
    # versus abandon the measurement. An early version of this engine used the
    # mean alone and recommended STOP for a track whose best dimension was at
    # 0.73, which would have been a bad and expensive call.
    alpha_max = max(inp.alpha_by_dimension.values()) if inp.alpha_by_dimension else 0.0

    # Three INDEPENDENT indicators that disagreement is definitional rather than
    # executional. The rule requires two of three rather than all of them.
    #
    # A conjunction of every condition is brittle in exactly the wrong
    # direction: one borderline value vetoes the recommendation regardless of
    # how strongly the other evidence points. An earlier version required all
    # four conditions and declined to recommend STOP for a track whose gold
    # accuracy came in at 0.725 against a 0.75 cut -- while its best dimension
    # sat at 0.59, its irreducible share at 0.57, and its adjudicators
    # attributed 58% of disagreements to definitional ambiguity. Every substantive
    # signal said stop; a single threshold two points low said continue.
    #
    # Gold accuracy is kept as a PRECONDITION rather than an indicator, because
    # it answers a different question: it establishes that the pool is competent
    # at all. Without that, low agreement is just a bad pool and the correct
    # action is retraining, not abandonment. The floor reuses the pre-registered
    # annotator-quality floor rather than introducing a new number.
    indicators = {
        "no_dimension_usable": alpha_max < 0.60,
        "disagreement_irreducible": (not math.isnan(irreducible)) and irreducible >= 0.55,
        "adjudicators_cite_definition": inp.rubric_gap_rate >= 0.30,
    }
    n_indicators = sum(indicators.values())

    # Pool competence has TWO requirements, not one. Gold accuracy shows the
    # pool can hit a defensible answer when one exists; the flagged fraction
    # shows how much of the pool the quality machinery has rejected on other
    # grounds (bias, speed, straightlining). A pool where most annotators are
    # flagged is not competent no matter how it scores on gold, and STOP -- which
    # asserts in writing that the disagreement cannot be an execution problem --
    # must not be reachable from that state. The correct action there is pool
    # remediation, which is cheap and testable; abandoning the construct is
    # neither, and it is irreversible in practice.
    POOL_FLAG_CEILING = 0.50
    pool_mostly_flagged = inp.flagged_annotator_fraction > POOL_FLAG_CEILING
    pool_is_competent = (
        (not math.isnan(inp.gold_accuracy))
        and inp.gold_accuracy >= 0.70
        and not pool_mostly_flagged
    )

    structural_case = inp.alpha_mean < 0.55 and n_indicators >= 2

    # ---- pool remediation preempts the structural verdict -----------------
    if structural_case and pool_mostly_flagged:
        rationale.append(
            f"{inp.flagged_annotator_fraction:.0%} of the annotator pool carries quality flags "
            f"(ceiling {POOL_FLAG_CEILING:.0%}). The structural indicators for a contested "
            f"construct did fire ({n_indicators} of 3), but they cannot be read as such while "
            "the majority of the instrument is flagged: the two explanations are not "
            "separable on this evidence."
        )
        rationale.append(
            "Declaring the construct contested requires first establishing that the pool is "
            "competent. That precondition fails here, so the recommendation is pool "
            "remediation, not abandonment."
        )
        return Decision(
            inp.track, Recommendation.ITERATE,
            f"Remediate the '{inp.track}' annotator pool before judging the construct.",
            rationale, irreducible,
            ["Replace or re-anchor the flagged annotators; a pool this heavily flagged cannot "
             "support any conclusion about whether the construct is measurable.",
             "Re-annotate a bridge sample with the remediated pool and recompute agreement.",
             "Only if agreement stays low with an unflagged pool is the contested-construct "
             "reading available; until then it is unfalsifiable.",
             "Check whether the flags are themselves an artifact -- a leniency detector that "
             "is really picking up value positions will flag the pool for disagreeing, which "
             "is the thing being measured."],
            [f"Revisit the STOP question only once the flagged fraction is below "
             f"{POOL_FLAG_CEILING:.0%} and agreement has been recomputed."],
            projected_cost_to_fix_usd=round(40 * 3 * unit_label_cost_usd, 2),
        )

    if structural_case and pool_is_competent:
        rationale.append(
            f"{n_indicators} of 3 structural indicators fired: "
            + "; ".join(f"{k}={v}" for k, v in indicators.items())
            + f". Best dimension {alpha_max:.3f}, irreducible share {irreducible:.0%}, "
            f"adjudicator-attributed rubric-gap rate {inp.rubric_gap_rate:.0%}."
        )
        rationale.append(
            f"The pool is competent ({inp.gold_accuracy:.0%} exact accuracy on items with "
            f"defensible answers; {inp.flagged_annotator_fraction:.0%} of annotators flagged, "
            f"under the {POOL_FLAG_CEILING:.0%} ceiling), so this is not an execution problem. "
            "Annotators can apply the rubric; they do not agree on what the rubric should say."
        )
        rationale.append(
            "Rubric refinement does not converge value disagreement. Additional labels would "
            "buy precision around a quantity that has no agreed referent."
        )
        return Decision(
            track=inp.track,
            recommendation=Recommendation.STOP,
            headline=(
                f"Stop investment in '{inp.track}' as a scalar measurement. "
                "Reframe as descriptive failure discovery."
            ),
            rationale=rationale,
            irreducible_share=irreducible,
            next_actions=[
                "Retire the composite score for this track; it is not a defensible measurement.",
                "Preserve the corpus and failure codes: the qualitative discovery value is real "
                "even though the scalar is not.",
                "Reframe the deliverable as a curated failure-mode catalogue with examples, "
                "reported as descriptive, not as a benchmark number.",
                "If a scalar is required by a stakeholder, first fund an upstream policy "
                "decision that fixes the contested definition. Measurement cannot precede it.",
            ],
            stop_criteria=[
                "Revisit only if a written adjudication policy resolves the contested cases, "
                "or if a demographically stratified pool shows the disagreement is pool-specific "
                "rather than construct-inherent.",
            ],
        )

    # ---- BLOCK-LEVEL: rubric underspecified -------------------------------
    if inp.rubric_gap_rate > 0.15:
        rationale.append(
            f"{inp.rubric_gap_rate:.0%} of adjudications were attributed to rubric ambiguity. "
            "The instrument, not the pool, is the bottleneck."
        )
        actions = [
            "Revise the ambiguous dimensions; add anchors for the specific cases that drove "
            "adjudication.",
            "Bump the rubric revision (this invalidates pooling with prior labels).",
            "Re-annotate a 40-item bridge sample under the new revision before scaling.",
        ]
        return Decision(
            inp.track, Recommendation.ITERATE,
            f"Revise the '{inp.track}' rubric before collecting more labels.",
            rationale, irreducible, actions,
            ["Proceed to scale only when rubric-gap rate falls below 15% on the bridge sample."],
            projected_cost_to_fix_usd=round(40 * 3 * unit_label_cost_usd, 2),
        )

    # ---- isolated broken dimension(s) in an otherwise sound rubric --------
    broken = sorted(
        (k for k, v in inp.alpha_by_dimension.items() if v < 0.40),
        key=lambda k: inp.alpha_by_dimension[k],
    )
    sound = [k for k, v in inp.alpha_by_dimension.items() if v >= 0.55]
    if broken and sound and len(sound) >= len(broken):
        rationale.append(
            f"Reliability is not uniform: {len(sound)} dimension(s) reach usable agreement "
            f"while {len(broken)} sit below 0.40 ("
            + ", ".join(f"{k}={inp.alpha_by_dimension[k]:.2f}" for k in broken)
            + "). This is a dimension-level defect, not a failure of the construct."
        )
        return Decision(
            inp.track, Recommendation.ITERATE,
            f"Drop or rebuild the failing dimension(s) of '{inp.track}'; keep the rest.",
            rationale, irreducible,
            [f"Remove {', '.join(broken)} from the reported composite immediately -- including "
             "them imports their noise into every downstream number.",
             f"Report the composite over {', '.join(sound)} only, and say so explicitly.",
             f"Decide separately whether {broken[0]} is worth rebuilding: if the judgement it "
             "encodes is genuinely contested, no anchor set will converge it.",
             "Re-run agreement on the reduced composite before quoting any system delta."],
            [f"Retire {broken[0]} permanently if a rebuilt version does not clear 0.50 "
             "on a 40-item bridge sample."],
            projected_cost_to_fix_usd=round(40 * 3 * unit_label_cost_usd, 2),
        )

    # ---- reliability too low but plausibly fixable ------------------------
    if inp.alpha_mean < 0.50:
        weakest = sorted(inp.alpha_by_dimension.items(), key=lambda kv: kv[1])[:2]
        rationale.append(
            "Reliability is below the blocking floor, but gold accuracy and rubric-gap rate do "
            "not indicate a contested construct. Treat as an execution problem."
        )
        actions = [
            "Rework the weakest dimensions first: "
            + ", ".join(f"{k} (alpha={v:.2f})" for k, v in weakest),
            "Run a calibration round on 25 anchored items with live disagreement review.",
            "Consider splitting any dimension that is bundling two distinct judgements.",
        ]
        return Decision(
            inp.track, Recommendation.ITERATE,
            f"Recalibrate the '{inp.track}' annotation pool; do not report scores yet.",
            rationale, irreducible, actions,
            ["Re-evaluate after the calibration round; stop if alpha does not clear 0.50."],
            projected_cost_to_fix_usd=round(25 * 3 * unit_label_cost_usd, 2),
        )

    # ---- coverage gap -----------------------------------------------------
    if inp.coverage_marginal_gap > 0.20:
        rationale.append(
            f"{inp.coverage_marginal_gap:.0%} of declared strata levels are absent or below the "
            "minimum count; aggregates silently exclude them."
        )
        return Decision(
            inp.track, Recommendation.ITERATE,
            f"Fill marginal coverage gaps in '{inp.track}' before reporting aggregates.",
            rationale, irreducible,
            ["Target collection at the thin and absent LEVELS, not uniformly across the design.",
             "Report per-level results only for levels meeting the minimum count."],
            ["Report aggregates once every declared level reaches n>=5."],
        )

    # ---- underpowered but healthy ----------------------------------------
    if inp.largest_effect < inp.mde:
        needed = (
            int(math.ceil(inp.n_items * (inp.mde / max(inp.largest_effect, 1e-6)) ** 2))
            if inp.largest_effect > 0
            else None
        )
        rationale.append(
            f"The instrument is healthy but underpowered: the largest between-system difference "
            f"({inp.largest_effect:.3f}) sits below the noise floor ({inp.mde:.3f})."
        )
        actions = [
            f"Scale n to approximately {needed} items to resolve the current effect size."
            if needed else "Effect is indistinguishable from zero at any feasible n.",
            "Alternatively reduce measurement variance: more replication per item raises "
            "effective n faster than more items when reliability is the binding constraint.",
            "Until then, report 'no detectable difference' rather than a ranking.",
        ]
        cost = round((needed - inp.n_items) * 3 * unit_label_cost_usd, 2) if needed and needed > inp.n_items else None
        return Decision(
            inp.track,
            Recommendation.HOLD if (needed and needed > 8 * inp.n_items) else Recommendation.INVEST,
            f"'{inp.track}' measures cleanly but cannot currently separate the candidate systems.",
            rationale, irreducible, actions,
            [f"Abandon the system-ranking use case if the required n exceeds "
             f"{8 * inp.n_items} items; at that point the eval costs more than the decision is worth."],
            projected_cost_to_fix_usd=cost,
        )

    # ---- healthy ----------------------------------------------------------
    rationale.append(
        "Reliability, coverage, and power all clear their thresholds; the measurement supports "
        "the claims being made on it."
    )
    if inp.detection_sensitivity is not None and not math.isnan(inp.detection_sensitivity):
        rationale.append(
            f"Detection sensitivity on planted failures is {inp.detection_sensitivity:.0%}: "
            "the eval finds the failures it was designed to find."
        )
    return Decision(
        inp.track, Recommendation.INVEST,
        f"Continue investing in '{inp.track}'; it is the portfolio's load-bearing measurement.",
        rationale, irreducible,
        ["Extend coverage into the strata with the highest observed failure rates.",
         "Add a held-out slice to guard against overfitting the rubric to known failures.",
         "Automate the highest-agreement dimensions with an LLM judge validated against "
         "the human labels, reserving human effort for the contested ones."],
        ["Re-audit reliability every 500 labels; drift invalidates longitudinal claims."],
    )


__all__ = ["Decision", "DecisionInput", "estimate_irreducible_share", "recommend"]
