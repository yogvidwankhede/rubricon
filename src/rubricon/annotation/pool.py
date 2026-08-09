"""Annotation pool simulation.

=========================== READ THIS FIRST ===========================
The annotators in this module are SIMULATED. No human labelled anything in
this repository. Every agreement coefficient downstream is a property of this
generative model, not evidence about real annotators.

What that means for how the results should be read:

* The *machinery* is real and reusable: the agreement math is validated against
  Krippendorff's published values, the gate logic is real, the decision rules
  are real. Point them at real labels and they work unchanged.
* The *findings* are not empirical claims about language models. They are
  demonstrations that the pipeline detects the conditions it was built to
  detect, on data where the ground truth is known by construction.
* Every generated report carries this caveat in its header. It is not buried in
  an appendix, because a reader who misses it draws exactly the wrong conclusion.

The one thing the simulation must NOT do is beg the question. If the annotator
model simply drew scores from the gate's pass region, the whole exercise would
be circular. Instead the model is specified in terms of *annotator psychology*
(competence, bias, fatigue, value positions) and the reliability statistics fall
out of it. Whether a track passes its gate is not set anywhere in this file.
=======================================================================

Annotator model
---------------
Each annotator has four stable traits:

* ``competence`` in [0,1] - scales down judgement noise. High-competence
  annotators sit closer to the latent value.
* ``bias`` in rubric points - a persistent leniency or harshness offset.
* ``value_position`` in [-1,1] - only active on dimensions flagged ``contested``.
  This is the term that does not average out: two annotators with opposite
  value positions will disagree consistently, forever, on the same items, while
  both remaining accurate on items with a defensible answer.
* ``fatigue`` - noise inflation that accumulates within a batch, modelling the
  well-documented decline in label quality over long sessions.

Gold items are, by construction, cases the rubric authors agreed on. Value
positions therefore do not apply to them. This is realistic and it is also a
real limitation of gold-item calibration in contested domains: gold can verify
that a pool executes the rubric, but it cannot verify agreement on precisely the
items where agreement is hardest. The pipeline surfaces that gap rather than
hiding it, and the decision engine uses it as the STOP discriminator.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Sequence

from ..core.schema import (
    Annotation,
    AnnotationSource,
    ModelResponse,
    Rubric,
    TaskItem,
    TrackSpec,
)
from .effects import effects_for, properties_for

SIMULATION_NOTICE = (
    "SIMULATED ANNOTATORS. No human labels were collected. Agreement statistics "
    "characterise the generative annotator model in rubricon.annotation.pool, "
    "not real annotator behaviour. The measurement machinery is real; the "
    "findings are demonstrations, not empirical claims about language models."
)


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("::".join(parts).encode()).hexdigest()[:12], 16)


@dataclass(frozen=True)
class Annotator:
    annotator_id: str
    competence: float
    bias: float
    value_position: float
    speed_factor: float = 1.0
    fatigue_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "annotator_id": self.annotator_id,
            "competence": round(self.competence, 3),
            "bias": round(self.bias, 3),
            "value_position": round(self.value_position, 3),
            "speed_factor": round(self.speed_factor, 3),
            "fatigue_rate": round(self.fatigue_rate, 4),
        }


# A fixed roster, so every run of the pipeline uses the same "people".
# Deliberately heterogeneous: one clearly weak annotator (A6) and one fast/lenient
# annotator (A5) exist so the quality-flagging machinery has something to catch.
# If every simulated annotator were good, the pool-health checks would be
# untested decoration.
#
# NOTE on speed_factor: values ABOVE 1.0 are faster than the reference pace.
# A5 was originally given 0.35, which made the annotator named "A5-fast" the
# slowest in the pool and meant the suspiciously-fast check never fired on
# anyone. Caught by reading the generated calibration doc against the roster.
ROSTER: tuple[Annotator, ...] = (
    Annotator("A1-senior",    competence=0.93, bias=+0.03, value_position=-0.75, speed_factor=1.30, fatigue_rate=0.004),
    Annotator("A2-senior",    competence=0.90, bias=-0.06, value_position=+0.80, speed_factor=1.20, fatigue_rate=0.005),
    Annotator("A3-core",      competence=0.84, bias=+0.11, value_position=-0.35, speed_factor=1.00, fatigue_rate=0.007),
    Annotator("A4-core",      competence=0.81, bias=-0.14, value_position=+0.45, speed_factor=1.00, fatigue_rate=0.008),
    Annotator("A5-fast",      competence=0.72, bias=+0.42, value_position=+0.15, speed_factor=4.00, fatigue_rate=0.011),
    Annotator("A6-untrained", competence=0.58, bias=-0.31, value_position=-0.20, speed_factor=0.75, fatigue_rate=0.016),
)


def roster() -> tuple[Annotator, ...]:
    return ROSTER


# --------------------------------------------------------------------------
# latent quality
# --------------------------------------------------------------------------


# Strata levels that make an item genuinely harder, and by how much (in rubric
# points of expected quality loss). Named explicitly rather than inferred, so a
# reader can disagree with any single entry.
_DIFFICULTY_PENALTY: dict[str, float] = {
    # agentic
    "tool_error_injected": 0.85, "ambiguous_request": 0.70, "missing_precondition": 0.95,
    "long_7_plus": 0.75, "medium_4_6_steps": 0.35, "irreversible_write": 0.30,
    # grounding
    "insufficient": 0.90, "conflicting": 1.00, "distractor_heavy": 0.65,
    "partially_relevant": 0.55, "aggregation": 0.45, "causal": 0.50, "temporal": 0.45,
    # reasoning
    "hard": 0.95, "medium": 0.45, "plausible_wrong_path": 0.80,
    "requires_case_split": 0.75, "extraneous_information": 0.55, "ambiguous_wording": 0.60,
    "combinatorics": 0.35, "probability": 0.40, "logic_puzzle": 0.30,
    # refusal
    "dual_use_ambiguous": 0.85, "harm_avoidance_intent": 0.55, "security_education": 0.50,
    "creative_fiction": 0.40, "alarming_keywords": 0.60, "clinical_terms": 0.35,
}

# Per-system baseline competence offset. Real systems differ in overall quality,
# not only in how often they trip a planted failure.
_SYSTEM_OFFSET: dict[str, float] = {
    "sut-baseline-v1": -0.42,
    "sut-candidate-v2": -0.05,
    "sut-candidate-v3": 0.00,
}


def item_difficulty(item: TaskItem) -> float:
    """Expected quality loss attributable to how hard this item is."""
    return sum(_DIFFICULTY_PENALTY.get(str(v), 0.0) for v in item.strata.values())


def latent_scores(spec: TrackSpec, item: TaskItem, response: ModelResponse) -> dict[str, float]:
    """True quality of a response on each dimension, before annotator noise.

    Three variance components, in decreasing size:

    1. **Shared response quality.** A single latent "how well did this system do
       on this item" term that moves all dimensions together. This is the
       dominant source of real between-item variance and the reason a corpus of
       real responses is not a wall of ceiling scores. Omitting it was the
       original modelling error here: without it, every dimension is
       near-degenerate and agreement coefficients collapse from range
       restriction rather than from annotator disagreement -- the exact
       confound the kappa-paradox check exists to catch.
    2. **Planted failure penalties** from the effect table.
    3. **Dimension-specific idiosyncrasy**, small.
    """
    rubric: Rubric = spec.rubric
    eff = effects_for(spec.key).get(response.planted_failure or "", {})
    rng = random.Random(_seed(response.response_id, "latent"))

    # (1) shared quality: item difficulty + system strength + response-level luck
    shared = (
        item_difficulty(item) * rng.uniform(0.55, 1.10)
        - _SYSTEM_OFFSET.get(response.system_id, 0.0)
        + rng.gauss(0.0, 0.62)
    )
    shared = max(-0.6, shared)  # a response can be slightly better than typical

    out: dict[str, float] = {}
    for dim in rubric.dimensions:
        levels = [float(x) for x in dim.levels]
        lo, hi = min(levels), max(levels)
        span = hi - lo

        if dim.key == "response_stance":
            # Descriptive classification, not a quality judgement: no shared term.
            base = float(
                response.metadata.get("stance_code", rng.randrange(int(lo), int(hi) + 1))
            )
            out[dim.key] = max(lo, min(hi, base))
            continue

        # How strongly this dimension loads on the shared quality factor.
        loading = 0.55 + 0.30 * rng.random()
        # Idiosyncrasy scales with the dimension's span. Without this, a 0-1
        # binary dimension inherits the same absolute jitter as a 0-4 scale,
        # which parks half its items on the rounding boundary and manufactures
        # coin-flip disagreement on a near-objective judgement.
        idio = rng.gauss(0.0, 0.22 * span / 3.0)

        if dim.key == "over_refusal_cost":
            # Inverted polarity: 0 is good, so shared deficit pushes the score UP.
            penalty = eff.get(dim.key, 0)
            base = lo + shared * loading * (span / 3.0) + idio
            base += abs(penalty) if penalty < 0 else 0.0
        else:
            base = hi - 0.20 - shared * loading * (span / 3.0) + idio
            base -= float(eff.get(dim.key, 0))

        out[dim.key] = max(lo, min(hi, base))
    return out


# --------------------------------------------------------------------------
# annotation
# --------------------------------------------------------------------------


def _observe(
    latent: float,
    dim_lo: float,
    dim_hi: float,
    noise: float,
    contested: bool,
    ann: Annotator,
    rng: random.Random,
    position_in_batch: int,
    is_gold: bool,
) -> int:
    # Leniency is a property of the annotator expressed on the scale in front of
    # them: "half a point soft" means something different on 0-4 than on 0-1.
    # Traits are calibrated against a reference 0-3 scale and rescaled here.
    span_factor = (dim_hi - dim_lo) / 3.0

    # 0.70 reflects an anchored pool: annotators have completed calibration and
    # read the anchors, so residual reading-variance is below the raw dimension
    # difficulty. An unanchored pool would use 1.0 or worse.
    sigma = 0.70 * noise * (1.6 - ann.competence) + ann.fatigue_rate * position_in_batch
    draw = (
        latent
        + rng.gauss(0.0, max(0.03, sigma * span_factor))
        + ann.bias * span_factor
    )
    if contested and not is_gold:
        # The term that does not average out. Two annotators with opposite value
        # positions disagree on the SAME items every time, so replication buys
        # precision around a split rather than convergence toward a truth.
        draw += ann.value_position * noise * 2.60 * span_factor
    return int(max(dim_lo, min(dim_hi, round(draw))))


def annotate(
    spec: TrackSpec,
    items: Sequence[TaskItem],
    responses: Sequence[ModelResponse],
    annotators: Sequence[Annotator] | None = None,
    replication: int | None = None,
    n_batches: int = 5,
) -> list[Annotation]:
    """Produce replicated annotations for every response.

    Assignment is deterministic and rotates annotators across responses so no
    pair of annotators co-occurs disproportionately (which would make agreement
    an artifact of who happened to overlap).

    Batches are assigned by stratified round-robin over the response list so
    that item difficulty mix is held approximately constant across batches --
    the precondition that makes the drift statistic interpretable.
    """
    annotators = list(annotators or ROSTER)
    k = replication or spec.replication
    if k > len(annotators):
        raise ValueError(f"replication {k} exceeds roster size {len(annotators)}")

    # n_batches must be coprime with the roster size. Both batch assignment and
    # annotator-window rotation are functions of the response index, so a shared
    # factor makes pool composition a periodic function of batch -- batches 0
    # and 2 draw from one half of the roster and batches 1 and 3 from the other.
    # The drift detector then correctly reports a batch-mean difference that is
    # entirely an artifact of assignment. Four batches with six annotators
    # (gcd 2) produced exactly this, and it took a spurious drift BLOCK on the
    # flagship track to notice.
    if math.gcd(n_batches, len(annotators)) != 1:
        raise ValueError(
            f"n_batches={n_batches} shares a factor with roster size "
            f"{len(annotators)}; pool composition would correlate with batch and "
            "invalidate the drift statistic. Choose a coprime batch count."
        )

    by_item = {i.item_id: i for i in items}
    rubric = spec.rubric
    props = properties_for(spec.key)
    bounds = {
        d.key: (min(float(x) for x in d.levels), max(float(x) for x in d.levels))
        for d in rubric.dimensions
    }

    out: list[Annotation] = []
    per_annotator_position: dict[str, int] = {a.annotator_id: 0 for a in annotators}

    # Batch assignment by DIFFICULTY-STRATIFIED round-robin.
    #
    # The naive version -- batch = index % n_batches over the corpus in id order
    # -- looks like it balances the mix and does not. Item generators lay strata
    # out in periodic blocks (five domains cycling across forty items, say), and
    # if that period shares a factor with the batch count, item difficulty
    # becomes a deterministic function of batch. The drift detector then reports
    # a real batch-mean difference that has nothing to do with annotators. Two
    # tracks failed this way before the ordering was made explicit.
    #
    # Dealing responses out in difficulty-rank order guarantees each batch draws
    # an almost identical difficulty distribution, which is precisely the
    # precondition the drift statistic documents.
    # Stratification is joint over (system, difficulty). Difficulty alone is not
    # enough: systems differ in baseline quality, and with three responses per
    # item sitting adjacent in id order, dealing on difficulty rank alone lets
    # system composition drift across batches whenever the corpus size is not a
    # clean multiple of (n_batches x n_systems). Dealing each system's responses
    # separately, each in its own difficulty order, fixes both margins at once.
    by_system: dict[str, list[ModelResponse]] = {}
    for r in responses:
        if r.item_id in by_item:
            by_system.setdefault(r.system_id, []).append(r)

    # Dealing is SERPENTINE (0,1,2,3,4,4,3,2,1,0,0,1,...), not plain round-robin.
    #
    # Plain round-robin over a difficulty-sorted list does not equalise the
    # batches -- it guarantees a gradient. Batch j receives ranks j, j+B, j+2B,
    # every one of them exactly j positions harder than batch 0's counterpart,
    # so batch mean declines monotonically with j. That is a textbook systematic
    # -sampling artifact. Serpentine dealing pairs each ascending sweep with a
    # descending one and cancels the gradient to first order.
    rank_of: dict[str, int] = {}
    for offset, (sysid, group) in enumerate(sorted(by_system.items())):
        ranked = sorted(group, key=lambda r: (item_difficulty(by_item[r.item_id]), r.response_id))
        for i, r in enumerate(ranked):
            block, pos = divmod(i, n_batches)
            slot = pos if block % 2 == 0 else (n_batches - 1 - pos)
            rank_of[r.response_id] = (slot + offset) % n_batches

    ordered = sorted(responses, key=lambda r: r.response_id)
    for idx, resp in enumerate(ordered):
        item = by_item.get(resp.item_id)
        if item is None:
            continue
        latent = latent_scores(spec, item, resp)
        base_batch = rank_of[resp.response_id]

        # Rotate the annotator window by a stride of 1, NOT by k.
        #
        # Striding by k is the obvious choice and it is wrong: with 6 annotators
        # and k=3 it yields only two distinct triples, {A1,A2,A3} and {A4,A5,A6},
        # alternating with index parity. Because batch is also a function of the
        # index, pool composition then correlates with batch, and the drift
        # detector faithfully reports "drift" that is really an artifact of the
        # assignment scheme. A stride of 1 produces all len(annotators) windows,
        # so no batch has a distinct pool.
        #
        # A stride of 1 alone is still not enough for pairwise coverage. A
        # CONTIGUOUS window of size k over a cyclic roster only ever pairs
        # annotators that sit within k-1 positions of each other: at n=6, k=3 the
        # three antipodal pairs (A1,A4), (A2,A5), (A3,A6) never co-occur on any
        # response, so their relative bias is never observed and every agreement
        # coefficient is computed over a proper subgraph of the pool rather than
        # the pool. Widening the leading gap by one position on each full
        # rotation walks the window through every gap pattern, so after
        # n*(n-k+1) responses every pair has co-occurred, while each rotation
        # still hands every annotator exactly k assignments (load stays flat).
        n_ann = len(annotators)
        start = idx % n_ann
        lead = (idx // n_ann) % max(1, n_ann - k + 1)
        offsets = [0] + [lead + j for j in range(1, k)]
        assigned = [annotators[(start + o) % n_ann] for o in offsets]

        for slot_j, ann in enumerate(assigned):
            # A response's k annotations are SPLIT ACROSS BATCHES rather than
            # all landing in one. This is the design decision that makes drift
            # identifiable at all.
            #
            # If each response sits entirely in one batch, batch means differ
            # for two reasons that cannot be separated: the annotators changed,
            # or the responses were harder. Stratifying on item features gets
            # the second under partial control, but response *quality* is not
            # knowable in advance -- you cannot stratify on how well the model
            # happened to do -- so a residual confound always survives. Two
            # tracks reported "drift" from exactly that residual before this
            # was fixed, and no amount of better item stratification removes it.
            #
            # Spreading the replicates across batches gives every batch an
            # overlapping view of the same responses, which is the same logic a
            # real programme implements with a re-annotated bridge sample. Batch
            # differences are then attributable to the pool, which is the thing
            # the statistic claims to measure.
            batch = (base_batch + slot_j) % n_batches
            rng = random.Random(_seed(resp.response_id, ann.annotator_id, spec.key))
            pos = per_annotator_position[ann.annotator_id]
            per_annotator_position[ann.annotator_id] = pos + 1

            scores: dict[str, int] = {}
            for dim in rubric.dimensions:
                lo, hi = bounds[dim.key]
                p = props.get(dim.key, {"noise": 0.5, "contested": False})
                truth = latent[dim.key]
                if item.is_gold and item.gold_scores and dim.key in item.gold_scores:
                    truth = float(item.gold_scores[dim.key])
                scores[dim.key] = _observe(
                    truth, lo, hi, float(p["noise"]), bool(p["contested"]),
                    ann, rng, pos, item.is_gold,
                )

            # Failure-code assignment: annotators tag codes they believe apply.
            codes = _infer_codes(spec, resp, scores, ann, rng)

            base_seconds = 55.0 + 14.0 * len(rubric.dimensions)
            duration = base_seconds / max(0.2, ann.speed_factor) * rng.uniform(0.75, 1.3)

            out.append(
                Annotation(
                    annotation_id=f"{resp.response_id}::{ann.annotator_id}",
                    response_id=resp.response_id,
                    item_id=resp.item_id,
                    annotator_id=ann.annotator_id,
                    rubric_version=rubric.version,
                    scores=scores,
                    source=AnnotationSource.SYNTHETIC,
                    failure_codes=tuple(codes),
                    rationale="",
                    confidence=round(min(1.0, 0.55 + 0.45 * ann.competence), 3),
                    duration_s=round(duration, 1),
                    batch=batch,
                    metadata={"simulated": True},
                )
            )
    return out


def _infer_codes(
    spec: TrackSpec, resp: ModelResponse, scores: dict[str, int],
    ann: Annotator, rng: random.Random,
) -> list[str]:
    """Which failure codes this annotator tags.

    Detection probability scales with competence, so code-level recall is a
    measured property rather than a stipulated one. Annotators also occasionally
    tag a code that was not planted (false positive), because real coders do.
    """
    codes: list[str] = []
    truth = resp.planted_failure
    if truth and truth in spec.failure_codes:
        if rng.random() < (0.42 + 0.55 * ann.competence):
            codes.append(truth)
    # False positives, more likely from weaker annotators.
    if rng.random() < (0.10 * (1.4 - ann.competence)):
        pool = [c for c in spec.failure_codes if c != truth]
        if pool:
            codes.append(pool[rng.randrange(len(pool))])
    return sorted(set(codes))


def pool_description(annotators: Sequence[Annotator] | None = None) -> dict:
    annotators = list(annotators or ROSTER)
    return {
        "notice": SIMULATION_NOTICE,
        "n_annotators": len(annotators),
        "annotators": [a.to_dict() for a in annotators],
        "trait_definitions": {
            "competence": "Scales down judgement noise; 1.0 would be a perfect reader of the rubric.",
            "bias": "Persistent leniency (+) or harshness (-) offset in rubric points.",
            "value_position": "Stable stance applied ONLY to dimensions marked contested. "
                              "This is the variance component that replication cannot reduce.",
            "speed_factor": "Relative annotation speed; <1 is slower than the reference pace.",
            "fatigue_rate": "Noise inflation per item completed within a session.",
        },
    }


__all__ = [
    "Annotator",
    "ROSTER",
    "SIMULATION_NOTICE",
    "annotate",
    "latent_scores",
    "pool_description",
    "roster",
]
