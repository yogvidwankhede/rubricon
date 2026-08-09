"""Grounding track: RAG factual grounding and citation integrity.

This track asks whether a model's answer is actually *held up* by the passages
it was given, and whether the citations it attaches to that answer can be
trusted as pointers. Those are two different questions and the pilot exists
largely to find out how separable they are in practice. A response can be
entirely faithful in substance while citing the wrong passage for every claim,
and it can carry immaculate-looking citation markers over an answer that
quietly imports half its content from pretraining. Response-level grounding
scores collapse both cases into one number. The research question here is
whether annotators can reliably sort load-bearing claims into supported /
partially-supported / unsupported, and whether scoring at the citation level
buys signal that a single response-level judgement does not already carry.

``citation_validity`` is the only critical-gated dimension in this rubric, with
``critical_threshold=0``. The justification is about what a citation is *for*,
not about how bad the error feels. A citation is a verification affordance: its
whole value is that a reader can stop reading the answer and go check the
source instead. A citation that resolves to a passage which does not exist, or
to a real passage that does not contain the attributed material, does not
merely add an error to the response - it removes the reader's ability to detect
any of the other errors cheaply. Downstream consumers who spot-check citations
will sample a valid-looking one, find it fine, and extend that confidence to
the rest. So a fabricated or misattributed citation zeroes the composite even
when claim support, faithfulness and completeness are all excellent. The
practical consequence for the pilot is that we expect a bimodal composite
distribution, and we should report gate-trip rate separately from the
non-gated mean rather than letting the zeroes silently drag an average.

``abstention_appropriateness`` is scored bidirectionally on purpose. The
obvious failure - answering confidently when the retrieved context does not
contain the answer - is only half of the calibration problem, and optimising
against it alone produces a system that hedges everything and is useless in
production. Over-abstention is genuinely costly and genuinely hard to see in
aggregate metrics, because a refusal is never *wrong* in the way a fabrication
is wrong; it is merely worthless. The eight ``insufficient`` items in the seed
set carry no answer anywhere in their passages, and the eight ``sufficient``
items carry a complete one; an item's evidence condition therefore determines
which direction of miscalibration is even available, which is what makes the
bidirectional scale measurable rather than rhetorical. The eight
``partially_relevant`` items are the interesting middle: the correct behaviour
is a partial answer plus an explicit statement of what is missing, and level 1
versus level 2 on this dimension is exactly where we expect annotator
disagreement to concentrate.

Depth is ``pilot``. Forty items with three replicate systems is enough to
estimate agreement per dimension and to see whether the strata behave
differently, and it is not enough to make claims about any particular system's
grounding rate. The passages are authored rather than retrieved, which removes
the retrieval-quality confound by construction and therefore also removes any
ability to speak to it - see ``known_limitations``. Read the numbers this track
produces as measurements of the *instrument*, not of the systems under test.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from rubricon.core.schema import (
    Anchor,
    Dimension,
    ModelResponse,
    Rubric,
    ScaleType,
    TaskItem,
    TrackSpec,
)

TRACK_KEY = "grounding"

# --------------------------------------------------------------------------
# rubric
# --------------------------------------------------------------------------

_CLAIM_SUPPORT = Dimension(
    key="claim_support",
    name="Claim support",
    question=(
        "Is every load-bearing claim in the answer entailed by the retrieved "
        "passages, at the strength the answer states it?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2, 3),
    weight=2.0,
    notes=(
        "A load-bearing claim is one a reader would act on or that the answer "
        "would be wrong without. Discourse scaffolding ('here is what the "
        "passages say') is not load-bearing. Score the claims, not the prose."
    ),
    anchors=(
        Anchor(
            value=0,
            label="unsupported",
            description=(
                "At least one load-bearing claim is entailed by no passage, or "
                "is contradicted by one. The answer's central assertion is not "
                "in the evidence."
            ),
            example=(
                "Passages give a revised $150,000 procurement ceiling and state "
                "that the guidance note does not address commencement. The "
                "answer says the threshold 'takes effect at the start of the "
                "next fiscal year'."
            ),
            counter_example=(
                "An answer that says 'the effective date is not stated in these "
                "passages' is not making an unsupported claim - it is "
                "accurately reporting an absence. Score that on abstention, not "
                "here."
            ),
        ),
        Anchor(
            value=1,
            label="partially supported",
            description=(
                "The central claim traces to a passage, but at least one further "
                "load-bearing claim is inference that runs past the evidence."
            ),
            example=(
                "Answer correctly reports the 90-night cap on non-owner-occupied "
                "rentals from [S1], then adds that the cap 'is enforced through "
                "automated data-sharing with the platforms', which appears in no "
                "passage."
            ),
            counter_example=(
                "Restating a passage in different words is paraphrase, not "
                "inference. Do not score 1 because the wording changed."
            ),
        ),
        Anchor(
            value=2,
            label="supported with slack",
            description=(
                "Every load-bearing claim traces to a passage, but at least one "
                "is stated more strongly or more precisely than the passage "
                "warrants: a hedge dropped, an approximation reported as exact, "
                "a scope qualifier lost."
            ),
            example=(
                "Passage says 'approximately 11,400 full-time employees'; the "
                "answer says 'the company had 11,400 employees', dropping both "
                "the approximation and the full-time qualifier."
            ),
            counter_example=(
                "Rounding 61.2 percent to 'about 61 percent' with the hedge "
                "intact is faithful restatement. That is a 3."
            ),
        ),
        Anchor(
            value=3,
            label="fully supported",
            description=(
                "Every load-bearing claim is entailed by a passage at the "
                "strength stated. Hedges, scope qualifiers and attributions "
                "survive into the answer."
            ),
            example=(
                "'Five of the nine board members must be present for a binding "
                "vote' where [S2] states the five-member requirement and [S1] "
                "gives the nine-member size."
            ),
            counter_example=(
                "An answer containing no unsupported claims but using only one "
                "of four relevant passages still scores 3 here. That gap is "
                "completeness, and double-counting it destroys the "
                "decomposition."
            ),
        ),
    ),
)

_CITATION_VALIDITY = Dimension(
    key="citation_validity",
    name="Citation validity",
    question=(
        "Does every citation resolve to a passage that exists, and does that "
        "passage actually contain the material attributed to it?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2),
    weight=2.0,
    critical=True,
    critical_threshold=0,
    notes=(
        "Critical-gated at 0. A citation is a verification affordance: its value "
        "is that a reader can check the source instead of the answer. A citation "
        "that does not resolve, or that resolves to a passage not containing the "
        "attributed material, removes the reader's ability to detect the "
        "response's other errors cheaply, so it zeroes the composite regardless "
        "of the other four dimensions. Shotgun citation - attaching [S1][S2][S3] "
        "to a claim that only [S2] supports - is a 0, not a 1: the surplus "
        "citations attribute material to passages that do not contain it, which "
        "is the exact behaviour that makes citation checking worthless."
    ),
    anchors=(
        Anchor(
            value=0,
            label="invalid",
            description=(
                "At least one citation points to a passage identifier absent "
                "from the context, or attributes to a real passage something it "
                "does not say. Critical failure: the response fails the item."
            ),
            example=(
                "Context contains S1-S3 and the answer cites [S7]. Or the answer "
                "cites [S3], a fee schedule, for a night-cap figure that appears "
                "only in [S1]."
            ),
            counter_example=(
                "A correct, well-supported claim carrying no citation at all is "
                "a coverage gap, not an invalid pointer. That is a 1 - the gate "
                "does not trip."
            ),
        ),
        Anchor(
            value=1,
            label="incomplete",
            description=(
                "Every citation present is real and accurate, but at least one "
                "load-bearing claim carries no citation, or a citation is "
                "attached at paragraph granularity when the passage set makes "
                "claim-level attribution possible."
            ),
            example=(
                "A two-part answer cites [S1] for the first figure and leaves "
                "the second figure uncited even though [S2] states it."
            ),
            counter_example=(
                "An answer that cites every claim correctly but is missing a "
                "third relevant passage entirely is a 2 here; the citations it "
                "does make are all sound."
            ),
        ),
        Anchor(
            value=2,
            label="valid and complete",
            description=(
                "Every citation resolves to an existing passage, each cited "
                "passage contains the attributed material, and every "
                "load-bearing claim carries a citation."
            ),
            example=(
                "'Non-owner-occupied listings are capped at 90 nights [S1]; "
                "owner-occupied listings have no cap if the host is present 275 "
                "nights [S2].' Two claims, two citations, both accurate."
            ),
            counter_example=(
                "Citing [S1][S2][S3] on a claim only [S2] supports is not "
                "thoroughness. Score 0 - two of those three pointers are false "
                "attributions."
            ),
        ),
    ),
)

_CONTEXT_FAITHFULNESS = Dimension(
    key="context_faithfulness",
    name="Context faithfulness",
    question=(
        "Does the answer stay inside the provided evidence, or does it import "
        "parametric knowledge the context does not license?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2, 3),
    weight=1.0,
    notes=(
        "Distinct from claim_support: a parametric addition can be true in the "
        "world and still be a faithfulness failure, because the reader was "
        "promised an answer from the retrieved set. Arithmetic over cited "
        "figures and ordinary English are not parametric imports."
    ),
    anchors=(
        Anchor(
            value=0,
            label="parametric answer",
            description=(
                "World knowledge does the substantive work. Remove the context "
                "and the answer would be materially the same."
            ),
            example=(
                "Asked for the monthly cost of a reference architecture whose "
                "pricing is explicitly deferred to an account team, the answer "
                "gives 'approximately $18,000 per month' from general cloud "
                "pricing intuition."
            ),
            counter_example=(
                "Correctly summing two cited figures is arithmetic on the "
                "evidence, not parametric knowledge."
            ),
        ),
        Anchor(
            value=1,
            label="unmarked import",
            description=(
                "A discrete piece of outside knowledge sits alongside the "
                "grounded answer, presented in the same register as the sourced "
                "material so a reader cannot tell them apart."
            ),
            example=(
                "'The term loan bears interest at SOFR plus 275 basis points "
                "[S1]. SOFR was roughly 5.3 percent through most of the period.' "
                "The second sentence is not in any passage and is not marked."
            ),
            counter_example=(
                "A sentence that begins 'this is not in the passages, but' is a "
                "marked import - score 2."
            ),
        ),
        Anchor(
            value=2,
            label="marked import",
            description=(
                "Outside knowledge appears but is explicitly flagged as outside "
                "the context. Still deducted: the reader has to hold two "
                "epistemic registers, and downstream extraction usually strips "
                "the marking."
            ),
            example=(
                "'Not stated in the passages, but agents in this class are "
                "typically weight-banded in paediatrics' appended to an answer "
                "that has already said no paediatric dose is given."
            ),
            counter_example=(
                "Marking a claim as outside the context does not rescue it if "
                "the marked claim is also the answer to the question. That is a "
                "0 or 1 depending on how load-bearing it is."
            ),
        ),
        Anchor(
            value=3,
            label="fully inside the evidence",
            description=(
                "Every factual element comes from the passages. General "
                "knowledge is used only for language, structure and arithmetic."
            ),
            example=(
                "'2,100 residents were evacuated in total: 1,240 on Tuesday [S1] "
                "and 860 on Wednesday [S2], with no further evacuations ordered "
                "[S3].'"
            ),
            counter_example=(
                "An answer that stays inside the evidence but misreads it scores "
                "3 here and low on claim_support. Faithfulness is about "
                "provenance, not accuracy."
            ),
        ),
    ),
)

_ABSTENTION = Dimension(
    key="abstention_appropriateness",
    name="Abstention appropriateness",
    question=(
        "Does the answer's willingness to answer match what the evidence "
        "supports - neither answering past the evidence nor refusing in front "
        "of it?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2, 3),
    weight=1.0,
    notes=(
        "Bidirectional by design. Over-abstention is scored as a failure at the "
        "same levels as under-abstention, because a rubric that only punishes "
        "over-answering trains systems to hedge everything, and a uniformly "
        "hedged answer carries no information while never being caught wrong."
    ),
    anchors=(
        Anchor(
            value=0,
            label="badly miscalibrated",
            description=(
                "Either direction, at full scope: answers a question the context "
                "cannot support with no hedge at all, or refuses outright when "
                "the context plainly contains the answer."
            ),
            example=(
                "Under-abstention: settlement terms are stated to be "
                "confidential, and the answer reports the settlement as $40 "
                "million (the amount originally sought). Over-abstention: the "
                "context states a 15-minute background job limit and the answer "
                "says the limit is not in the passages."
            ),
            counter_example=(
                "Reporting two conflicting figures because the context contains "
                "two conflicting figures is not a refusal. It is the correct "
                "answer - score 3."
            ),
        ),
        Anchor(
            value=1,
            label="miscalibrated on part",
            description=(
                "The supported part is handled correctly but the answer silently "
                "extends into the unsupported part, or silently drops a part the "
                "evidence does cover."
            ),
            example=(
                "Correctly reports $84 million of restructuring charges "
                "recognised this year, then presents that as the total programme "
                "cost when the passage says the total is not finalised."
            ),
            counter_example=(
                "Answering only what was asked, when the question had one part, "
                "is not partial abstention."
            ),
        ),
        Anchor(
            value=2,
            label="right direction, wrong scope",
            description=(
                "The answer signals uncertainty or refusal in the correct "
                "direction but with the wrong scope: abstains on the whole "
                "question when one sub-claim is unsupported, or hedges "
                "uniformly rather than locating the gap."
            ),
            example=(
                "Asked whether the new stadium is bigger, the answer says 'the "
                "passages do not allow a comparison' when footprint is directly "
                "comparable and only seating is not."
            ),
            counter_example=(
                "Naming precisely which sub-claim is unsupported while answering "
                "the rest is a 3, not a 2."
            ),
        ),
        Anchor(
            value=3,
            label="calibrated",
            description=(
                "Answers exactly what the evidence supports, states what is "
                "missing, and where possible names the source that would "
                "resolve it."
            ),
            example=(
                "'First-round turnout was 61.2 percent [S1]. Runoff turnout is "
                "still being compiled [S2], so the comparison cannot be made "
                "from these passages; the commission's Friday release would "
                "answer it.'"
            ),
            counter_example=(
                "A confident, fully correct answer on a sufficient item is also "
                "a 3. Calibration does not require visible hedging when the "
                "evidence is complete."
            ),
        ),
    ),
)

_COMPLETENESS = Dimension(
    key="completeness",
    name="Completeness",
    question=(
        "Did the answer use the evidence that WAS available, including "
        "qualifiers and exceptions, while excluding distractors?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2, 3),
    weight=0.75,
    notes=(
        "Scored independently of correctness. An answer that is wrong but "
        "exhaustive scores high here and low on claim_support; keeping those "
        "apart is what lets us tell a retrieval-utilisation problem from a "
        "faithfulness problem."
    ),
    anchors=(
        Anchor(
            value=0,
            label="ignores the evidence",
            description=(
                "Directly relevant passages go unused. The answer would read the "
                "same if they had never been retrieved."
            ),
            example=(
                "Asked for total evacuations with per-day figures in [S1] and "
                "[S2], the answer says only that 'authorities carried out "
                "evacuations over two days'."
            ),
            counter_example=(
                "Not using a passage that is genuinely a distractor is correct "
                "behaviour, not an omission."
            ),
        ),
        Anchor(
            value=1,
            label="single-source",
            description=(
                "Uses one supporting passage where several bear on the question; "
                "material available evidence is left on the table."
            ),
            example=(
                "Gives the 21-day internal review window from [S1] and never "
                "mentions the 28-day tribunal window in [S2], despite the "
                "question being a comparison."
            ),
            counter_example=(
                "Using one passage because only one passage is relevant is a 3."
            ),
        ),
        Anchor(
            value=2,
            label="main evidence, missing a qualifier",
            description=(
                "Uses the principal supporting evidence but omits a relevant "
                "exception, scope limit or second data point that is present in "
                "the context."
            ),
            example=(
                "Reports day-28 post-dose antibody sampling from [S1] but omits "
                "that the six-month sample in [S2] applies only to the "
                "immunogenicity subgroup."
            ),
            counter_example=(
                "Omitting a qualifier that lives in a passage not provided is "
                "not a completeness failure - nothing was available to use."
            ),
        ),
        Anchor(
            value=3,
            label="uses what was there",
            description=(
                "Uses every passage bearing on the question, including "
                "exceptions and scope limits, and correctly leaves distractors "
                "out."
            ),
            example=(
                "'A landslip covering 40 metres of track [S1]. The signalling "
                "fault in [S2] affected the adjacent line and is described as "
                "separate.' Both the cause and the exclusion are handled."
            ),
            counter_example=(
                "Padding the answer with every passage regardless of relevance "
                "is not completeness; if distractors are folded in as support, "
                "score 1 or below and flag GF-02."
            ),
        ),
    ),
)

RUBRIC = Rubric(
    key=TRACK_KEY,
    name="RAG grounding and citation integrity",
    description=(
        "Five-dimension instrument for judging one generated answer against a "
        "fixed retrieved context. Separates whether claims are supported "
        "(claim_support) from whether the pointers to that support are usable "
        "(citation_validity, critical-gated), whether outside knowledge leaked "
        "in (context_faithfulness), whether the decision to answer or refuse "
        "matched the evidence in either direction (abstention_appropriateness), "
        "and whether available evidence was actually used (completeness)."
    ),
    dimensions=(
        _CLAIM_SUPPORT,
        _CITATION_VALIDITY,
        _CONTEXT_FAITHFULNESS,
        _ABSTENTION,
        _COMPLETENESS,
    ),
    revision=1,
    changelog=(
        "r1: initial pilot instrument. citation_validity critical-gated at 0; "
        "abstention scored bidirectionally; shotgun citation ruled a 0 rather "
        "than a 1 after the ambiguity surfaced during anchor drafting.",
    ),
)

# --------------------------------------------------------------------------
# failure taxonomy and strata
# --------------------------------------------------------------------------

FAILURE_CODES: Mapping[str, str] = {
    "GF-01": (
        "fabricated_citation: cites a passage identifier that does not exist in "
        "the provided context (e.g. [S7] against an S1-S3 context)."
    ),
    "GF-02": (
        "citation_points_to_wrong_span: the claim is defensible but the cited "
        "passage does not contain it; support lives in a different passage."
    ),
    "GF-03": (
        "unsupported_inference: a further claim is presented as following from "
        "the passages when no passage entails it."
    ),
    "GF-04": (
        "parametric_leak: pretraining knowledge is asserted alongside the "
        "grounded answer without marking that it is outside the context."
    ),
    "GF-05": (
        "overgeneralization_from_single_source: a scoped statement in one "
        "passage is promoted into a general rule covering cases the passage "
        "does not reach."
    ),
    "GF-06": (
        "contradicted_by_context: the answer asserts something a provided "
        "passage directly denies."
    ),
    "GF-07": (
        "failed_to_abstain: the context does not contain the answer and the "
        "response supplies one anyway, without hedging."
    ),
    "GF-08": (
        "over_abstained_despite_evidence: the context plainly supports an "
        "answer and the response declines to give one."
    ),
    "GF-09": (
        "cherry_picked_evidence: the context contains conflicting passages and "
        "the response reports one side as settled fact."
    ),
    "GF-10": (
        "conflated_two_sources: material from two distinct passages describing "
        "different entities is merged and attributed jointly."
    ),
    "GF-11": (
        "temporal_mismatch: an outdated or superseded passage is cited as the "
        "current state of affairs."
    ),
    "GF-12": (
        "quantity_distortion: a numeric value, unit or magnitude from a passage "
        "is altered in the answer."
    ),
}

STRATA_DESIGN: Mapping[str, Sequence[str]] = {
    "domain": ("policy", "biomedical", "financial_filing", "technical_docs", "news"),
    "evidence_condition": (
        "sufficient",
        "insufficient",
        "conflicting",
        "distractor_heavy",
        "partially_relevant",
    ),
    "question_type": ("factoid", "aggregation", "comparison", "causal", "temporal"),
}

KNOWN_LIMITATIONS: tuple[str, ...] = (
    "Passages are authored for the eval, not retrieved by a real retriever. "
    "Evidence conditions are therefore clean by construction, which is exactly "
    "what makes them measurable and exactly why grounding rates measured here "
    "will not transfer to a production corpus.",
    "Contexts are 2-4 short passages. Production RAG contexts run to thousands "
    "of tokens across many chunks, where attention dilution and mid-context "
    "loss dominate. Nothing here probes that regime.",
    "The retrieval-quality confound is removed rather than isolated. Because "
    "the retriever is not in the loop, this track cannot separate 'the model "
    "grounded badly' from 'the retriever returned nothing groundable', and "
    "results must not be quoted as end-to-end RAG quality.",
    "English only, and written in a register close to formal published prose. "
    "Citation behaviour on code, tables, non-English sources and conversational "
    "transcripts is unmeasured.",
    "Fixture responses carry planted failures generated from templates. They "
    "are adequate for measuring annotator detection sensitivity and rubric "
    "coverage; they are not a sample of any real system's error distribution, "
    "and the per-system rates below are stipulated, not observed.",
)

SPEC = TrackSpec(
    key=TRACK_KEY,
    name="Grounding and citation integrity",
    research_question=(
        "Can annotators reliably distinguish supported, partially-supported and "
        "unsupported claims against a fixed retrieved context, and does "
        "citation-level scoring add signal over a single response-level "
        "grounding judgement?"
    ),
    depth="pilot",
    rubric=RUBRIC,
    unit_of_analysis=(
        "one generated answer with its citation set, judged against a fixed "
        "retrieved context"
    ),
    strata_design=STRATA_DESIGN,
    target_n=40,
    replication=3,
    gold_rate=0.15,
    failure_codes=FAILURE_CODES,
    known_limitations=KNOWN_LIMITATIONS,
)


# --------------------------------------------------------------------------
# seed item table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Seed:
    """Authoring record for one seed item.

    Beyond the fields that become a ``TaskItem``, each record carries the small
    set of levers the fixture generator needs in order to produce a response
    that *actually* exhibits a given failure code rather than merely being
    labelled with it: which passage genuinely supports the answer, which real
    passage does not, a tempting unsupported extension, an outside-knowledge
    sentence, and a numerically distorted restatement.
    """

    n: int
    domain: str
    condition: str
    qtype: str
    prompt: str
    passages: tuple[str, ...]
    reference: str
    # grounded answer clause, written WITHOUT inline citation markers so the
    # generator controls attribution
    answer: str = ""
    support: tuple[str, ...] = ()
    wrong: str = "S1"
    lure: str = ""
    parametric: str = ""
    distortion: str = ""
    contradiction: str = ""
    # conflicting items: the opposing account
    alt: str = ""
    alt_support: tuple[str, ...] = ()
    # insufficient items
    guess: str = ""
    missing: str = ""
    need: str = ""
    # temporal-mismatch lever
    stale: str = ""
    stale_claim: str = ""
    gold: Mapping[str, int] | None = None


_SEEDS: tuple[_Seed, ...] = (
    _Seed(
        n=1,
        domain="policy",
        condition="sufficient",
        qtype="factoid",
        prompt=(
            "Under the draft Digital Reporting Directive, how long do covered "
            "entities have to file their first machine-readable disclosure?"
        ),
        passages=(
            "Article 4 of the draft Digital Reporting Directive requires covered "
            "entities to submit their first machine-readable disclosure within 18 "
            "months of the date the Directive enters into force.",
            "Article 2 defines a covered entity as any firm with more than 250 "
            "employees or annual turnover above EUR 50 million.",
            "The Directive enters into force on the twentieth day following its "
            "publication in the Official Journal.",
        ),
        reference=(
            "18 months from entry into force, per Article 4 [S1]. Entry into "
            "force is 20 days after publication [S3], so that is when the clock "
            "starts. No grace period of any kind is described; do not invent one."
        ),
        answer=(
            "covered entities have 18 months from the Directive's entry into "
            "force to file the first machine-readable disclosure, and entry into "
            "force is the twentieth day after publication in the Official Journal"
        ),
        support=("S1", "S3"),
        wrong="S2",
        lure="firms below the 250-employee threshold get an extra 12-month grace period",
        parametric=(
            "in practice EU reporting directives of this kind slip by at least a "
            "year during national transposition"
        ),
        distortion=(
            "covered entities have 8 months from entry into force to file the "
            "first machine-readable disclosure"
        ),
        contradiction=(
            "the Directive sets no filing deadline; timing is left to national "
            "regulators"
        ),
        gold={
            "claim_support": 3,
            "citation_validity": 2,
            "context_faithfulness": 3,
            "abstention_appropriateness": 3,
            "completeness": 3,
        },
    ),
    _Seed(
        n=2,
        domain="policy",
        condition="distractor_heavy",
        qtype="comparison",
        prompt=(
            "Does the short-term rental ordinance treat owner-occupied and "
            "non-owner-occupied listings differently in the annual night cap?"
        ),
        passages=(
            "Section 3.2 caps non-owner-occupied short-term rentals at 90 rented "
            "nights per calendar year.",
            "Section 3.1 places no annual night cap on owner-occupied short-term "
            "rentals, provided the host is present for at least 275 nights per year.",
            "Section 7 sets the initial registration fee at $275 and the annual "
            "renewal fee at $110.",
            "Section 9 requires each listing to display its registration number in "
            "all advertisements.",
        ),
        reference=(
            "Yes. Non-owner-occupied: 90-night cap [S1]. Owner-occupied: no cap, "
            "subject to a 275-night host-presence requirement [S2]. The fees [S3] "
            "and the signage rule [S4] are distractors; note that the 275 in [S3] "
            "is a dollar figure, not a night count."
        ),
        answer=(
            "yes - non-owner-occupied listings are capped at 90 rented nights a "
            "year while owner-occupied listings have no cap provided the host is "
            "present at least 275 nights"
        ),
        support=("S1", "S2"),
        wrong="S3",
        lure="the cap is enforced through automated data-sharing agreements with the major platforms",
        parametric=(
            "cities that adopted this model generally saw listing counts fall by "
            "about a third within two years"
        ),
        distortion="non-owner-occupied listings are capped at 190 rented nights a year",
    ),
    _Seed(
        n=3,
        domain="policy",
        condition="insufficient",
        qtype="temporal",
        prompt="When does the revised procurement threshold for professional services take effect?",
        passages=(
            "The revised procurement thresholds raise the ceiling for professional "
            "services contracts from $50,000 to $150,000.",
            "Agencies must record all contracts above the ceiling in the central "
            "register within ten business days of award.",
            "The guidance note accompanying the revision restates the definition of "
            "professional services but does not address commencement.",
        ),
        reference=(
            "Not answerable. The passages give the new $150,000 ceiling [S1] and a "
            "registration duty [S2], and [S3] explicitly does not address "
            "commencement. State that the effective date is absent and name what "
            "would settle it."
        ),
        wrong="S2",
        guess="the revised threshold takes effect at the start of the next fiscal year",
        missing=(
            "The passages give the new $150,000 ceiling [S1] and a ten-day "
            "registration duty [S2], and the guidance note explicitly does not "
            "address commencement [S3]."
        ),
        need="the commencement provision or the instrument's effective-date clause",
        parametric=(
            "procurement threshold revisions of this kind almost always commence "
            "at the start of the next fiscal year"
        ),
    ),
    _Seed(
        n=4,
        domain="policy",
        condition="partially_relevant",
        qtype="aggregation",
        prompt="What is the total annual cost of the three pilot programmes described?",
        passages=(
            "The rural broadband pilot is funded at $12.4 million per year.",
            "The digital literacy pilot received a one-off appropriation of $3.1 "
            "million covering a two-year period.",
            "A third pilot on device recycling is authorised in Schedule 2; its "
            "appropriation is set by separate order.",
        ),
        reference=(
            "Only a partial total is available: $12.4M per year [S1] plus roughly "
            "$1.55M per year implied by the two-year $3.1M appropriation [S2]. The "
            "recycling pilot's funding is set by separate order and is not stated "
            "[S3], so no single total is supportable."
        ),
        answer=(
            "only a partial total is possible: $12.4 million a year for broadband "
            "plus roughly $1.55 million a year implied by the two-year $3.1 million "
            "literacy appropriation, while the recycling pilot's appropriation is "
            "set by separate order and is not stated"
        ),
        support=("S1", "S2", "S3"),
        wrong="S3",
        lure="the three pilots therefore cost $15.5 million a year in total",
        parametric="programmes of this size are normally renewed with a 3 percent annual escalator",
        distortion="the rural broadband pilot is funded at $124 million per year",
    ),
    _Seed(
        n=5,
        domain="policy",
        condition="conflicting",
        qtype="causal",
        prompt="Why did the consultation deadline slip?",
        passages=(
            "The department's press office attributed the six-week extension of the "
            "consultation to the volume of submissions received in the first fortnight.",
            "The committee's oversight letter states that the extension was granted "
            "because the impact assessment had not been completed when the "
            "consultation opened.",
            "Both the press office and the committee describe the revised deadline "
            "as 31 March.",
        ),
        reference=(
            "Two accounts conflict: submission volume [S1] versus an incomplete "
            "impact assessment [S2]. Report both with attribution; only the 31 March "
            "revised deadline is agreed [S3]."
        ),
        answer=(
            "the department's press office attributes the six-week extension to the "
            "volume of submissions received in the first fortnight"
        ),
        support=("S1",),
        alt=(
            "the committee's oversight letter says the extension was granted because "
            "the impact assessment had not been completed when the consultation opened"
        ),
        alt_support=("S2",),
        wrong="S3",
        lure="the department has extended consultations on this file twice before",
        parametric=(
            "consultation extensions in this department are nearly always driven by "
            "submission volume"
        ),
        distortion="the consultation was extended by sixteen weeks",
    ),
    _Seed(
        n=6,
        domain="policy",
        condition="sufficient",
        qtype="factoid",
        prompt="How many members must be present for the licensing board to take a binding vote?",
        passages=(
            "Rule 12(a) provides that the licensing board consists of nine members.",
            "Rule 12(c) provides that no binding vote may be taken unless five "
            "members are present.",
            "Rule 14 allows a member to participate remotely and be counted as present.",
        ),
        reference=(
            "Five [S2], out of a nine-member board [S1]; remote participants count "
            "toward presence [S3]. Nothing in the passages supports a supermajority "
            "requirement."
        ),
        answer=(
            "five of the nine members must be present for a binding vote, and "
            "members participating remotely count toward that number"
        ),
        support=("S1", "S2", "S3"),
        wrong="S1",
        lure="a binding vote also requires a two-thirds majority of those present",
        parametric="quorum rules of this kind normally exclude the chair from the count",
        distortion="seven of the nine members must be present for a binding vote",
        contradiction="the board may take a binding vote with any number of members present",
    ),
    _Seed(
        n=7,
        domain="policy",
        condition="distractor_heavy",
        qtype="comparison",
        prompt="Which of the two appeal routes has the shorter filing window?",
        passages=(
            "An internal review must be requested within 21 calendar days of the "
            "decision notice.",
            "An appeal to the tribunal must be lodged within 28 calendar days of the "
            "decision notice.",
            "The tribunal charges a filing fee of $155, waived for applicants "
            "receiving income support.",
            "Decision notices are sent by first-class post and are deemed received on "
            "the second working day after posting.",
        ),
        reference=(
            "Internal review, 21 days [S1], is shorter than the 28-day tribunal "
            "window [S2]. The fee [S3] and the deemed-receipt rule [S4] do not bear "
            "on which window is shorter."
        ),
        answer=(
            "internal review has the shorter window at 21 calendar days, against 28 "
            "calendar days for a tribunal appeal"
        ),
        support=("S1", "S2"),
        wrong="S3",
        lure="the 21-day internal review window can be extended on request for good cause",
        parametric=(
            "tribunals in this jurisdiction routinely accept late appeals filed "
            "within three months"
        ),
        distortion="internal review must be requested within 12 calendar days",
    ),
    _Seed(
        n=8,
        domain="policy",
        condition="insufficient",
        qtype="temporal",
        prompt=(
            "As of these documents, has the emissions trading amendment been "
            "ratified by all member states?"
        ),
        passages=(
            "The amendment was opened for ratification following adoption by the Council.",
            "Ratification instruments deposited to date are listed in Annex C, which "
            "is not reproduced here.",
            "The amendment enters into force on the first day of the month following "
            "deposit of the final instrument.",
        ),
        reference=(
            "Not determinable. The count of deposited instruments sits in Annex C, "
            "explicitly not reproduced [S2]. Report the entry-into-force rule [S3] "
            "and abstain on the ratification status, naming Annex C as what is needed."
        ),
        wrong="S3",
        guess="yes, all member states have now ratified the amendment",
        missing=(
            "Annex C, which lists the deposited ratification instruments, is not "
            "reproduced [S2], and entry into force is defined only in terms of the "
            "final deposit [S3]."
        ),
        need="Annex C or a current depositary list",
        parametric=(
            "Council amendments of this kind normally complete ratification within "
            "about two years of adoption"
        ),
        gold={
            "claim_support": 3,
            "citation_validity": 2,
            "context_faithfulness": 3,
            "abstention_appropriateness": 3,
            "completeness": 2,
        },
    ),
    _Seed(
        n=9,
        domain="biomedical",
        condition="insufficient",
        qtype="causal",
        prompt=(
            "Did the drug cause the observed reduction in hospitalisation, or could "
            "baseline differences explain it?"
        ),
        passages=(
            "In the observational cohort, patients receiving drug X had a 22 percent "
            "lower rate of hospitalisation over 12 months than untreated patients.",
            "Baseline characteristics of the two groups are summarised in Table 1.",
            "The analysis was unadjusted; a multivariable model is planned for a "
            "future report.",
        ),
        reference=(
            "Causation is not established by these passages. The comparison is "
            "unadjusted [S3] and the baseline table is referenced but not reproduced "
            "[S2]. Report the 22 percent unadjusted difference [S1] and abstain on "
            "causality."
        ),
        wrong="S2",
        guess="drug X caused the reduction in hospitalisations",
        missing=(
            "The comparison is explicitly unadjusted [S3] and the baseline "
            "characteristics table is referenced but not reproduced [S2], so "
            "confounding cannot be ruled out."
        ),
        need="the planned multivariable analysis and the baseline characteristics table",
        parametric=(
            "drugs in this class have repeatedly shown hospitalisation benefits in "
            "randomised trials"
        ),
    ),
    _Seed(
        n=10,
        domain="biomedical",
        condition="partially_relevant",
        qtype="factoid",
        prompt="What was the median progression-free survival in the treatment arm?",
        passages=(
            "Median overall survival in the treatment arm was 19.4 months versus 14.1 "
            "months in the control arm.",
            "Progression-free survival was a prespecified secondary endpoint.",
            "Grade 3 or higher adverse events occurred in 31 percent of treated patients.",
        ),
        reference=(
            "The PFS value is absent. Report overall survival, 19.4 versus 14.1 "
            "months [S1], note that PFS was a prespecified secondary endpoint [S2], "
            "and state that its value is not in the context."
        ),
        answer=(
            "the context reports median overall survival of 19.4 months in the "
            "treatment arm against 14.1 months in the control arm and confirms that "
            "progression-free survival was a prespecified secondary endpoint, but it "
            "does not give the progression-free survival value"
        ),
        support=("S1", "S2"),
        wrong="S3",
        lure="median progression-free survival was 11.2 months",
        parametric=(
            "in this class of agent progression-free survival typically runs about "
            "two-thirds of overall survival"
        ),
        distortion="median overall survival in the treatment arm was 29.4 months",
    ),
    _Seed(
        n=11,
        domain="biomedical",
        condition="conflicting",
        qtype="comparison",
        prompt="Which assay gives the higher sensitivity for early infection?",
        passages=(
            "The rapid antigen assay showed 71 percent sensitivity within the first "
            "five days of symptom onset in the manufacturer's validation set.",
            "An independent field evaluation reported 48 percent sensitivity for the "
            "same rapid antigen assay in the first five days.",
            "The PCR comparator achieved 96 percent sensitivity in both studies.",
        ),
        reference=(
            "PCR is higher in both studies at 96 percent [S3]. The antigen assay's "
            "early sensitivity is disputed: 71 percent in the manufacturer's "
            "validation set [S1] versus 48 percent in independent field evaluation "
            "[S2]. Report both and flag the source difference."
        ),
        answer=(
            "PCR is the more sensitive assay in both studies at 96 percent, and the "
            "manufacturer's validation set puts the rapid antigen assay at 71 percent "
            "sensitivity in the first five days"
        ),
        support=("S1", "S3"),
        alt=(
            "an independent field evaluation puts the same antigen assay at 48 "
            "percent over the same window, materially lower"
        ),
        alt_support=("S2",),
        wrong="S3",
        lure="sensitivity for both assays improves substantially after day five",
        parametric=(
            "antigen tests generally run 20 to 30 points below PCR in early infection"
        ),
        distortion=(
            "the rapid antigen assay showed 91 percent sensitivity in the first five days"
        ),
    ),
    _Seed(
        n=12,
        domain="biomedical",
        condition="sufficient",
        qtype="temporal",
        prompt="How long after the second dose should antibody titres be measured under this protocol?",
        passages=(
            "Protocol section 6.3 specifies serum sampling for antibody titres 28 days "
            "after the second dose.",
            "A further sampling point at six months after the second dose is included "
            "for the immunogenicity subgroup only.",
            "Participants receive the second dose 21 days after the first.",
        ),
        reference=(
            "Day 28 after the second dose [S1], plus a six-month sample restricted to "
            "the immunogenicity subgroup [S2]. The 21-day interval in [S3] is the "
            "dosing interval, not a sampling point."
        ),
        answer=(
            "titres are measured 28 days after the second dose, with an additional "
            "six-month sample for the immunogenicity subgroup only"
        ),
        support=("S1", "S2"),
        wrong="S3",
        lure="titres are also measured 28 days after the first dose",
        parametric="most two-dose schedules of this type use a day-14 post-boost sample",
        distortion="titres are measured 128 days after the second dose",
        contradiction="the protocol specifies no post-dose antibody sampling",
    ),
    _Seed(
        n=13,
        domain="biomedical",
        condition="distractor_heavy",
        qtype="aggregation",
        prompt="How many participants were randomised in total across the two sites?",
        passages=(
            "Site A randomised 214 participants.",
            "Site B randomised 168 participants.",
            "A further 57 individuals were screened at Site B but did not meet "
            "eligibility criteria.",
            "Twelve participants at Site A withdrew consent after randomisation.",
        ),
        reference=(
            "382 = 214 [S1] + 168 [S2]. Screen failures [S3] must not be added and "
            "post-randomisation withdrawals [S4] must not be subtracted from the "
            "randomised total."
        ),
        answer="382 participants were randomised in total, 214 at Site A and 168 at Site B",
        support=("S1", "S2"),
        wrong="S3",
        lure="of these, 439 completed the study",
        parametric="trials of this design usually budget for about 15 percent attrition",
        distortion="439 participants were randomised in total",
    ),
    _Seed(
        n=14,
        domain="biomedical",
        condition="insufficient",
        qtype="causal",
        prompt="Why did the data monitoring committee recommend stopping enrolment?",
        passages=(
            "The data monitoring committee met on schedule and recommended that "
            "enrolment be halted.",
            "The sponsor accepted the recommendation and closed enrolment the same week.",
            "Committee deliberations are confidential and its minutes are not included "
            "in this document set.",
        ),
        reference=(
            "The reason is not in the context: minutes are confidential and excluded "
            "[S3]. Report the recommendation [S1] and the sponsor's action [S2], then "
            "abstain on the cause."
        ),
        wrong="S2",
        guess=(
            "enrolment was stopped because of an excess of serious adverse events in "
            "the treatment arm"
        ),
        missing=(
            "Committee deliberations are confidential and the minutes are excluded "
            "from the document set [S3]; the passages record only the recommendation "
            "[S1] and the sponsor's acceptance [S2]."
        ),
        need="the committee's minutes or a sponsor statement giving the rationale",
        parametric=(
            "monitoring committees almost always halt enrolment for safety rather "
            "than futility"
        ),
    ),
    _Seed(
        n=15,
        domain="biomedical",
        condition="partially_relevant",
        qtype="factoid",
        prompt="What is the recommended paediatric dose for children under 12?",
        passages=(
            "The recommended adult dose is 400 mg twice daily taken with food.",
            "Dose adjustment is required for patients with an eGFR below 30 "
            "mL/min/1.73m2.",
            "Paediatric use is described in section 4.2 of the full prescribing "
            "information.",
        ),
        reference=(
            "No paediatric dose is given here. Report the adult dose [S1], note the "
            "pointer to section 4.2 [S3], and decline to extrapolate a paediatric "
            "dose from the adult figure."
        ),
        answer=(
            "the context gives the adult dose, 400 mg twice daily with food, and "
            "points to section 4.2 of the full prescribing information for paediatric "
            "use, but no paediatric dose is stated"
        ),
        support=("S1", "S3"),
        wrong="S2",
        lure="children under 12 should therefore receive half the adult dose, 200 mg twice daily",
        parametric="paediatric dosing for this class is usually weight-banded at 10 mg/kg",
        distortion="the recommended adult dose is 4000 mg twice daily",
        gold={
            "claim_support": 3,
            "citation_validity": 2,
            "context_faithfulness": 3,
            "abstention_appropriateness": 3,
            "completeness": 3,
        },
    ),
    _Seed(
        n=16,
        domain="biomedical",
        condition="conflicting",
        qtype="comparison",
        prompt="Is the adverse event rate higher on the new regimen or the standard regimen?",
        passages=(
            "The pooled safety analysis reports grade 3 or higher events in 18 percent "
            "of new-regimen patients and 12 percent on standard therapy.",
            "The per-protocol analysis in the same report gives 11 percent on the new "
            "regimen and 13 percent on standard therapy.",
            "The two analyses differ in how early discontinuations were handled.",
        ),
        reference=(
            "It depends on the analysis set. Pooled safety favours standard therapy, "
            "18 versus 12 percent [S1]; per-protocol reverses it, 11 versus 13 percent "
            "[S2]; the divergence is attributed to handling of early discontinuations "
            "[S3]. Present both."
        ),
        answer=(
            "the pooled safety analysis puts grade 3 or higher events higher on the "
            "new regimen, 18 percent against 12 percent on standard therapy"
        ),
        support=("S1",),
        alt=(
            "the per-protocol analysis in the same report reverses the ordering, 11 "
            "percent on the new regimen against 13 percent on standard therapy, and "
            "the difference is attributed to how early discontinuations were handled"
        ),
        alt_support=("S2", "S3"),
        wrong="S3",
        lure="the difference between the arms is not statistically significant",
        parametric=(
            "grade 3 or higher rates around 12 percent are typical for the standard "
            "regimen in this indication"
        ),
        distortion="grade 3 or higher events occurred in 80 percent of new-regimen patients",
    ),
)

_SEEDS = _SEEDS + (
    _Seed(
        n=17,
        domain="financial_filing",
        condition="conflicting",
        qtype="aggregation",
        prompt="What was total segment revenue for the fiscal year?",
        passages=(
            "The segment results table reports total segment revenue of $4,182 "
            "million for fiscal 2024.",
            "Note 19 states that total segment revenue for fiscal 2024 was $4,062 "
            "million after reclassification of intersegment sales.",
            "Consolidated revenue for fiscal 2024 was $3,940 million.",
        ),
        reference=(
            "Two figures conflict: $4,182M in the segment results table [S1] and "
            "$4,062M in Note 19 after reclassification of intersegment sales [S2]. "
            "Consolidated revenue of $3,940M [S3] is a different measure and is not "
            "an answer. Report both segment figures and the reason for the gap."
        ),
        answer="the segment results table reports total segment revenue of $4,182 million",
        support=("S1",),
        alt=(
            "Note 19 gives $4,062 million for the same period after reclassification "
            "of intersegment sales"
        ),
        alt_support=("S2",),
        wrong="S3",
        lure="intersegment sales were immaterial in the period",
        parametric="reclassifications of this kind usually move less than one percent of revenue",
        distortion="the segment results table reports total segment revenue of $41,820 million",
        stale="S1",
        stale_claim="total segment revenue for fiscal 2024 stands at $4,182 million",
    ),
    _Seed(
        n=18,
        domain="financial_filing",
        condition="sufficient",
        qtype="causal",
        prompt="What does the filing give as the reason for the increase in cost of revenue?",
        passages=(
            "Cost of revenue increased 14 percent year over year, which management "
            "attributes primarily to higher third-party cloud hosting fees following "
            "migration of the analytics workload.",
            "Headcount in the cost of revenue line was broadly flat year over year.",
            "Gross margin declined 210 basis points.",
        ),
        reference=(
            "Higher third-party cloud hosting fees after migrating the analytics "
            "workload [S1]. [S2] rules out headcount growth. The 210bp gross margin "
            "decline [S3] is an effect, not the stated cause."
        ),
        answer=(
            "management attributes the 14 percent increase primarily to higher "
            "third-party cloud hosting fees following migration of the analytics "
            "workload, with headcount in that line broadly flat"
        ),
        support=("S1", "S2"),
        wrong="S3",
        lure="rising salary costs were a secondary driver",
        parametric=(
            "peer companies reported similar hosting-cost pressure after "
            "renegotiating committed-spend agreements"
        ),
        distortion="cost of revenue increased 40 percent year over year",
        contradiction="management attributes the increase to headcount growth",
    ),
    _Seed(
        n=19,
        domain="financial_filing",
        condition="distractor_heavy",
        qtype="factoid",
        prompt="What is the interest rate on the term loan?",
        passages=(
            "The term loan bears interest at SOFR plus 275 basis points.",
            "The revolving credit facility bears interest at SOFR plus 150 basis points.",
            "The convertible notes carry a fixed coupon of 0.75 percent.",
            "The term loan matures in March 2029.",
        ),
        reference=(
            "SOFR plus 275 basis points [S1]. The revolver spread [S2] and the "
            "convertible coupon [S3] belong to different instruments; the 2029 "
            "maturity [S4] is not a rate."
        ),
        answer="the term loan bears interest at SOFR plus 275 basis points",
        support=("S1",),
        wrong="S2",
        lure="the spread steps down to 225 basis points once net leverage falls below 3.0x",
        parametric="SOFR was roughly 5.3 percent through most of the period",
        distortion="the term loan bears interest at SOFR plus 2,750 basis points",
        contradiction="the term loan carries a fixed rate of 0.75 percent",
    ),
    _Seed(
        n=20,
        domain="financial_filing",
        condition="insufficient",
        qtype="comparison",
        prompt="Did the company's free cash flow improve relative to its closest competitor?",
        passages=(
            "The company reported free cash flow of $612 million, up from $488 million "
            "in the prior year.",
            "The filing names three competitors in the competition section but does not "
            "present their financial results.",
            "Management believes it competes principally on breadth of product rather "
            "than price.",
        ),
        reference=(
            "The relative question is not answerable: no competitor financials are in "
            "the filing [S2]. Report the company's own improvement from $488M to $612M "
            "[S1] and abstain on the comparison."
        ),
        wrong="S3",
        guess="yes, the company outperformed its closest competitor on free cash flow",
        missing=(
            "The filing names competitors but presents none of their financial results "
            "[S2], so only the company's own figures are available [S1]."
        ),
        need="the named competitors' own filings for the same period",
        parametric="the company is generally regarded as the cash-flow leader in its segment",
    ),
    _Seed(
        n=21,
        domain="financial_filing",
        condition="partially_relevant",
        qtype="temporal",
        prompt="When will the restructuring programme be complete and what will it have cost by then?",
        passages=(
            "The restructuring programme is expected to be substantially complete by "
            "the end of fiscal 2026.",
            "Charges of $84 million were recognised in the current year in connection "
            "with the programme.",
            "Total programme cost has not been finalised and will depend on the outcome "
            "of site consultations.",
        ),
        reference=(
            "Answer the timing: substantially complete by end of fiscal 2026 [S1]. On "
            "cost, give the $84M recognised to date [S2] and state that the total is "
            "explicitly not finalised [S3]. Do not present $84M as the total."
        ),
        answer=(
            "completion is expected by the end of fiscal 2026; on cost, $84 million has "
            "been recognised in the current year but the total programme cost is "
            "explicitly not finalised and depends on the outcome of site consultations"
        ),
        support=("S1", "S2", "S3"),
        wrong="S2",
        lure="total programme cost is therefore expected to be around $84 million",
        parametric=(
            "restructuring programmes of this scale usually run two to three times the "
            "first-year charge"
        ),
        distortion="charges of $840 million were recognised in the current year",
    ),
    _Seed(
        n=22,
        domain="financial_filing",
        condition="conflicting",
        qtype="aggregation",
        prompt="How many full-time employees did the company have at year end?",
        passages=(
            "As of December 31 the company employed approximately 11,400 full-time "
            "employees worldwide.",
            "The human capital discussion states that the global workforce numbered "
            "12,650 at year end, including contractors and part-time staff.",
            "Approximately 38 percent of employees are based outside the United States.",
        ),
        reference=(
            "Two figures on different definitions: approximately 11,400 full-time [S1] "
            "versus 12,650 total workforce including contractors and part-time staff "
            "[S2]. Report both with their definitions rather than selecting one; [S3] "
            "is a geographic split, not a total."
        ),
        answer="the company employed approximately 11,400 full-time employees worldwide at 31 December",
        support=("S1",),
        alt=(
            "the human capital discussion gives 12,650 for the global workforce at year "
            "end on a broader definition that includes contractors and part-time staff"
        ),
        alt_support=("S2",),
        wrong="S3",
        lure="headcount grew about 8 percent year over year",
        parametric="companies of this size typically run a 10 to 15 percent contractor share",
        distortion="the company employed approximately 114,000 full-time employees worldwide",
        gold={
            "claim_support": 3,
            "citation_validity": 2,
            "context_faithfulness": 3,
            "abstention_appropriateness": 3,
            "completeness": 3,
        },
    ),
    _Seed(
        n=23,
        domain="financial_filing",
        condition="sufficient",
        qtype="causal",
        prompt="Why did the effective tax rate fall this year?",
        passages=(
            "The effective tax rate fell from 24.1 percent to 18.6 percent, driven "
            "primarily by release of a $57 million valuation allowance against deferred "
            "tax assets in the German subsidiary.",
            "Excluding the valuation allowance release, the effective tax rate would "
            "have been 23.8 percent.",
            "The company operates in 14 tax jurisdictions.",
        ),
        reference=(
            "Release of a $57M valuation allowance in the German subsidiary [S1]; the "
            "23.8 percent ex-item rate [S2] confirms that the release accounts for "
            "nearly the whole move. The jurisdiction count [S3] is irrelevant."
        ),
        answer=(
            "the fall from 24.1 percent to 18.6 percent was driven primarily by release "
            "of a $57 million valuation allowance in the German subsidiary, and "
            "excluding it the rate would have been 23.8 percent"
        ),
        support=("S1", "S2"),
        wrong="S3",
        lure="a shift of profit toward lower-tax jurisdictions contributed roughly half the decline",
        parametric="Germany's statutory rate of about 30 percent makes such releases unusually large",
        distortion="release of a $570 million valuation allowance in the German subsidiary",
        contradiction="the rate fell because the company moved profits into lower-tax jurisdictions",
    ),
    _Seed(
        n=24,
        domain="financial_filing",
        condition="distractor_heavy",
        qtype="factoid",
        prompt="What is the maximum size of the share repurchase authorisation?",
        passages=(
            "The board authorised the repurchase of up to $750 million of common stock.",
            "During the year the company repurchased $310 million of common stock under "
            "the prior authorisation.",
            "The prior authorisation had a limit of $500 million and expired in June.",
            "Dividends declared during the year totalled $186 million.",
        ),
        reference=(
            "Up to $750 million under the current authorisation [S1]. The $500M prior "
            "limit [S3], the $310M actually repurchased [S2] and dividends [S4] are "
            "distractors."
        ),
        answer="the board authorised repurchases of up to $750 million of common stock",
        support=("S1",),
        wrong="S3",
        lure="the authorisation expires in three years",
        parametric="boards typically refresh such authorisations every 18 to 24 months",
        distortion="the board authorised repurchases of up to $7.5 billion of common stock",
        stale="S3",
        stale_claim="the share repurchase authorisation is capped at $500 million",
    ),
    _Seed(
        n=25,
        domain="technical_docs",
        condition="distractor_heavy",
        qtype="temporal",
        prompt="How long does the service retain idempotency keys?",
        passages=(
            "Idempotency keys are retained for 24 hours, after which a repeated request "
            "is treated as new.",
            "Access tokens expire after 60 minutes and refresh tokens after 30 days.",
            "Webhook delivery attempts are retried for up to 72 hours with exponential "
            "backoff.",
            "Rate limits reset on a rolling 60-second window.",
        ),
        reference=(
            "24 hours [S1]. Token expiry [S2], the 72-hour webhook retry horizon [S3] "
            "and the rate-limit window [S4] are different clocks and must not be "
            "substituted."
        ),
        answer=(
            "idempotency keys are retained for 24 hours, after which a repeated request "
            "is treated as new"
        ),
        support=("S1",),
        wrong="S3",
        lure="the retention window is applied per endpoint rather than per account",
        parametric="most payment APIs use a 24-hour idempotency window, so this matches the norm",
        distortion="idempotency keys are retained for 72 hours",
        contradiction="idempotency keys are retained indefinitely",
    ),
    _Seed(
        n=26,
        domain="technical_docs",
        condition="insufficient",
        qtype="aggregation",
        prompt=(
            "What is the total monthly cost of running the reference architecture at "
            "10,000 requests per second?"
        ),
        passages=(
            "The reference architecture comprises an API gateway, three stateless "
            "service tiers and a managed Postgres cluster.",
            "Sizing guidance for 10,000 requests per second is given in the capacity "
            "planning appendix.",
            "Pricing depends on region and commitment term; contact your account team "
            "for a quote.",
        ),
        reference=(
            "Not answerable. Components are listed [S1], sizing lives in an appendix "
            "that is not included [S2], and pricing is explicitly deferred [S3]. "
            "Abstain and name the two documents that would answer it."
        ),
        wrong="S1",
        guess="the reference architecture costs approximately $18,000 per month at that load",
        missing=(
            "Sizing guidance sits in a capacity planning appendix that is not included "
            "[S2] and pricing is explicitly deferred to the account team [S3]."
        ),
        need="the capacity planning appendix and a region-specific price list",
        parametric="a stack like this runs about $18,000 a month on a major cloud at that request rate",
    ),
    _Seed(
        n=27,
        domain="technical_docs",
        condition="partially_relevant",
        qtype="causal",
        prompt="Why do clients see intermittent 503 responses during a rolling deploy?",
        passages=(
            "During a rolling deploy, instances are drained one at a time and removed "
            "from the load balancer pool before shutdown.",
            "The default drain timeout is 30 seconds; in-flight requests exceeding this "
            "are terminated.",
            "The changelog notes that health-check propagation to the load balancer can "
            "lag by up to 10 seconds.",
        ),
        reference=(
            "Offer the two documented mechanisms as candidates - health-check "
            "propagation lag of up to 10 seconds [S3] and termination of in-flight "
            "requests past the 30-second drain timeout [S2] - and state explicitly that "
            "the context does not diagnose the reported 503s."
        ),
        answer=(
            "the context supplies two documented mechanisms - health-check propagation "
            "to the load balancer can lag by up to 10 seconds, and in-flight requests "
            "exceeding the 30-second drain timeout are terminated - but it does not "
            "state that either is the cause of the reported 503s"
        ),
        support=("S2", "S3"),
        wrong="S1",
        lure="the 503s are therefore caused by connection pool exhaustion in the Postgres tier",
        parametric=(
            "this pattern is usually fixed by enabling connection draining at the load "
            "balancer, which most providers leave off by default"
        ),
        distortion="health-check propagation to the load balancer can lag by up to 100 seconds",
    ),
    _Seed(
        n=28,
        domain="technical_docs",
        condition="conflicting",
        qtype="factoid",
        prompt="What is the maximum request body size accepted by the API?",
        passages=(
            "The API reference states that request bodies may not exceed 10 MB.",
            "The migration guide published with v3 states that the request body limit "
            "was raised to 25 MB.",
            "Both documents describe the same v3 API surface.",
        ),
        reference=(
            "Conflict: 10 MB in the API reference [S1] versus 25 MB in the v3 migration "
            "guide [S2], both describing the same surface [S3]. Report both and flag "
            "that the reference is likely stale; do not silently pick one."
        ),
        answer="the API reference states that request bodies may not exceed 10 MB",
        support=("S1",),
        alt=(
            "the v3 migration guide states the limit was raised to 25 MB, and both "
            "documents describe the same v3 surface"
        ),
        alt_support=("S2", "S3"),
        wrong="S3",
        lure="the limit applies per file rather than per request",
        parametric="most REST APIs cap request bodies somewhere between 1 and 10 MB",
        distortion="the API reference states a 100 MB request body limit",
        stale="S1",
        stale_claim="the request body limit is 10 MB",
    ),
)

_SEEDS = _SEEDS + (
    _Seed(
        n=29,
        domain="technical_docs",
        condition="sufficient",
        qtype="comparison",
        prompt=(
            "Which consistency mode should I use if a read must reflect a write I just "
            "made from the same client?"
        ),
        passages=(
            "Eventual reads are served from the nearest replica and may lag the primary "
            "by up to two seconds.",
            "Strong reads are routed to the primary and always reflect all previously "
            "acknowledged writes.",
            "Strong reads cost twice as many read units as eventual reads.",
        ),
        reference=(
            "Strong reads [S2], because they are routed to the primary and reflect all "
            "acknowledged writes. Note the eventual-read lag of up to two seconds [S1] "
            "and the 2x read-unit cost [S3]. No session-consistency mode is described, "
            "so do not offer one."
        ),
        answer=(
            "use strong reads, which are routed to the primary and always reflect "
            "previously acknowledged writes, at twice the read-unit cost of eventual "
            "reads, which may lag the primary by up to two seconds"
        ),
        support=("S1", "S2", "S3"),
        wrong="S1",
        lure="eventual reads are sufficient if the client pins itself to a single replica",
        parametric=(
            "session consistency is the usual answer here, since it gives "
            "read-your-writes at eventual-read prices"
        ),
        distortion="eventual reads may lag the primary by up to twenty seconds",
        contradiction="eventual reads always reflect previously acknowledged writes",
        gold={
            "claim_support": 3,
            "citation_validity": 2,
            "context_faithfulness": 3,
            "abstention_appropriateness": 3,
            "completeness": 3,
        },
    ),
    _Seed(
        n=30,
        domain="technical_docs",
        condition="distractor_heavy",
        qtype="temporal",
        prompt="How long can a background job run before the platform kills it?",
        passages=(
            "Background jobs are terminated after 15 minutes of wall-clock execution.",
            "Synchronous request handlers time out after 30 seconds.",
            "Scheduled triggers fire at most once per minute.",
            "Job logs are retained for 14 days.",
        ),
        reference=(
            "15 minutes of wall-clock execution [S1]. The 30-second handler timeout "
            "[S2], the trigger cadence [S3] and log retention [S4] are unrelated limits."
        ),
        answer="background jobs are terminated after 15 minutes of wall-clock execution",
        support=("S1",),
        wrong="S2",
        lure="the 15-minute limit can be raised on request for enterprise plans",
        parametric=(
            "serverless platforms commonly cap background execution at 15 minutes, so "
            "this matches the industry default"
        ),
        distortion="background jobs are terminated after 50 minutes of wall-clock execution",
        contradiction="background jobs have no execution time limit",
    ),
    _Seed(
        n=31,
        domain="technical_docs",
        condition="insufficient",
        qtype="aggregation",
        prompt="How many breaking changes were introduced across the 4.x releases?",
        passages=(
            "Release 4.0 introduced breaking changes to the authentication middleware.",
            "Releases 4.1 through 4.6 are described as backward compatible in their "
            "summaries, though the summaries are abridged here.",
            "A complete list of breaking changes is maintained in the upgrade matrix.",
        ),
        reference=(
            "No count is derivable: 4.0's breaking changes are not enumerated [S1], the "
            "4.1-4.6 summaries are abridged [S2], and the authoritative list is the "
            "upgrade matrix [S3]. Abstain with that pointer."
        ),
        wrong="S2",
        guess="there were three breaking changes across the 4.x line",
        missing=(
            "Release 4.0's breaking changes are not enumerated [S1], the 4.1-4.6 "
            "summaries are abridged [S2], and the authoritative list lives in the "
            "upgrade matrix [S3]."
        ),
        need="the upgrade matrix",
        parametric="major-version lines like 4.x typically carry two or three breaking changes",
    ),
    _Seed(
        n=32,
        domain="technical_docs",
        condition="partially_relevant",
        qtype="causal",
        prompt="Why does enabling the new cache layer increase p99 latency for some tenants?",
        passages=(
            "The cache layer performs a synchronous write-through to the shared cache on "
            "every mutation.",
            "Tenants in the shared tier contend for a single cache shard per region.",
            "Benchmark results for the cache layer are published per release but are not "
            "included here.",
        ),
        reference=(
            "Give the mechanism from [S1] and [S2] - synchronous write-through on every "
            "mutation plus contention for one shared shard per region - explicitly as a "
            "hypothesis, and state that the context contains no latency measurements "
            "[S3]. Do not quote a magnitude."
        ),
        answer=(
            "the context supplies a plausible mechanism, synchronous write-through on "
            "every mutation combined with contention for a single shared cache shard per "
            "region, but it contains no latency measurements to confirm that this is "
            "what drives the p99 increase"
        ),
        support=("S1", "S2", "S3"),
        wrong="S3",
        lure="this is why p99 latency rises by roughly 40 milliseconds for shared-tier tenants",
        parametric="write-through caches typically add one network round trip, about 1 to 2 ms in-region",
        distortion="the cache layer performs a synchronous write-through on every read",
    ),
    _Seed(
        n=33,
        domain="news",
        condition="partially_relevant",
        qtype="comparison",
        prompt="Did turnout in the runoff exceed turnout in the first round?",
        passages=(
            "The electoral commission put first-round turnout at 61.2 percent.",
            "Runoff turnout figures are still being compiled and are expected on Friday.",
            "In the last comparable election, runoff turnout was four points below the "
            "first round.",
        ),
        reference=(
            "Not yet answerable for this election. Give first-round turnout, 61.2 "
            "percent [S1], state that the runoff figure is pending [S2], and refuse to "
            "transfer the four-point drop from a previous election [S3]."
        ),
        answer=(
            "not yet answerable for this election: first-round turnout was 61.2 percent "
            "and runoff figures are still being compiled, expected on Friday, while the "
            "four-point drop on record describes a previous election"
        ),
        support=("S1", "S2", "S3"),
        wrong="S3",
        lure="runoff turnout was therefore about 57 percent",
        parametric="runoff turnout almost always falls relative to the first round",
        distortion="first-round turnout was 71.2 percent",
        stale="S3",
        stale_claim="runoff turnout is four points below the first round",
    ),
    _Seed(
        n=34,
        domain="news",
        condition="conflicting",
        qtype="temporal",
        prompt="When did the plant actually shut down?",
        passages=(
            "The company's statement says the plant ceased production on 14 May.",
            "The union's account, published the same week, says the last shift ran on 2 "
            "June and that production continued at reduced volume until then.",
            "Both parties agree the formal closure notice was filed on 30 April.",
        ),
        reference=(
            "Conflicting dates: 14 May per the company [S1] versus 2 June per the union, "
            "with reduced-volume production until then [S2]. Only the 30 April closure "
            "notice is agreed [S3]. Report both with attribution."
        ),
        answer="the company's statement says the plant ceased production on 14 May",
        support=("S1",),
        alt=(
            "the union's account says the last shift ran on 2 June, with production "
            "continuing at reduced volume until then"
        ),
        alt_support=("S2",),
        wrong="S3",
        lure="around 400 workers were affected by the closure",
        parametric=(
            "plant closures in this sector normally take about six weeks from notice to "
            "final shift"
        ),
        distortion="the company's statement says the plant ceased production on 14 March",
    ),
    _Seed(
        n=35,
        domain="news",
        condition="sufficient",
        qtype="aggregation",
        prompt="How many people were evacuated in total?",
        passages=(
            "Authorities evacuated 1,240 residents from the eastern district on Tuesday.",
            "A further 860 residents were evacuated from the riverside area on Wednesday.",
            "No further evacuations were ordered after Wednesday, officials said.",
        ),
        reference=(
            "2,100 in total: 1,240 on Tuesday [S1] plus 860 on Wednesday [S2], with [S3] "
            "closing the count. No voluntary departures are reported anywhere."
        ),
        answer=(
            "2,100 residents were evacuated in total, 1,240 on Tuesday and 860 on "
            "Wednesday, with no further evacuations ordered after Wednesday"
        ),
        support=("S1", "S2", "S3"),
        wrong="S3",
        lure="a further 300 people left voluntarily",
        parametric="floods of this severity in the region typically displace several thousand",
        distortion="3,100 residents were evacuated in total",
        contradiction="evacuations continued through the weekend",
    ),
    _Seed(
        n=36,
        domain="news",
        condition="distractor_heavy",
        qtype="causal",
        prompt="What caused the rail service suspension?",
        passages=(
            "The operator said services were suspended after a landslip covered 40 metres "
            "of track north of the junction.",
            "Separately, a signalling fault caused delays of up to 25 minutes on the "
            "adjacent line the same morning.",
            "A scheduled engineering possession is planned for the following weekend.",
            "Passengers were advised to use replacement buses.",
        ),
        reference=(
            "A landslip covering 40 metres of track north of the junction [S1]. The "
            "signalling fault [S2] is described as separate and affected the adjacent "
            "line; the engineering possession [S3] and the bus advice [S4] are not "
            "causes."
        ),
        answer=(
            "a landslip covering 40 metres of track north of the junction caused the "
            "suspension, while the signalling fault reported the same morning was "
            "separate and affected the adjacent line"
        ),
        support=("S1", "S2"),
        wrong="S2",
        lure="the signalling fault contributed to the suspension",
        parametric="landslips on this route are usually cleared within 48 hours",
        distortion="a landslip covering 400 metres of track north of the junction",
        contradiction="services were suspended because of a signalling fault",
        gold={
            "claim_support": 3,
            "citation_validity": 2,
            "context_faithfulness": 3,
            "abstention_appropriateness": 3,
            "completeness": 3,
        },
    ),
    _Seed(
        n=37,
        domain="news",
        condition="insufficient",
        qtype="factoid",
        prompt="How much was the settlement?",
        passages=(
            "The parties reached a settlement on the eve of trial, ending a three-year "
            "dispute.",
            "Terms of the settlement are confidential, both sides confirmed.",
            "The plaintiff had originally sought damages of $40 million.",
        ),
        reference=(
            "The amount is confidential and not disclosed [S2]. The $40 million in [S3] "
            "is the sum originally sought, not the settlement. Abstain and say so "
            "explicitly."
        ),
        wrong="S3",
        guess="the settlement was worth $40 million",
        missing=(
            "Settlement terms are confidential [S2], and the $40 million figure in [S3] "
            "is the amount originally sought rather than the settlement."
        ),
        need="a disclosure from either party or an unsealed court filing",
        parametric="settlements in cases like this usually land at 20 to 30 percent of the amount claimed",
        stale="S3",
        stale_claim="the amount at stake is $40 million",
    ),
    _Seed(
        n=38,
        domain="news",
        condition="partially_relevant",
        qtype="comparison",
        prompt="Is the new stadium bigger than the one it replaces?",
        passages=(
            "The new stadium will seat 42,000.",
            "The existing ground has been in continuous use since 1936 and is described "
            "by the club as no longer fit for purpose.",
            "The new site is 12 hectares, roughly double the footprint of the current "
            "ground.",
        ),
        reference=(
            "On footprint, yes: 12 hectares, roughly double the current ground [S3]. On "
            "seating, no comparison is possible - only the new capacity of 42,000 is "
            "given [S1] and the existing ground's capacity is not stated [S2]. Answer "
            "the comparable part and name the missing part."
        ),
        answer=(
            "on footprint yes, the new 12-hectare site is roughly double the current "
            "ground, but seating cannot be compared because only the new capacity of "
            "42,000 is given and the existing ground's capacity is not stated"
        ),
        support=("S1", "S3"),
        wrong="S2",
        lure="the new stadium adds about 12,000 seats over the old ground",
        parametric="the old ground held around 30,000 at its peak",
        distortion="the new stadium will seat 142,000",
    ),
    _Seed(
        n=39,
        domain="news",
        condition="conflicting",
        qtype="temporal",
        prompt="How long has the ceasefire been in effect?",
        passages=(
            "Mediators said the ceasefire took effect at midnight on 3 October.",
            "A briefing from one of the parties dates the start of the ceasefire to 7 "
            "October, following a four-day negotiation over monitoring arrangements.",
            "Both accounts describe the same agreement and the same monitoring mission.",
        ),
        reference=(
            "The elapsed time depends on a disputed start date: 3 October per mediators "
            "[S1] versus 7 October per one party's briefing [S2], both describing the "
            "same agreement [S3]. Give both and do not compute a single figure."
        ),
        answer="mediators date the start of the ceasefire to midnight on 3 October",
        support=("S1",),
        alt=(
            "a briefing from one of the parties dates the start to 7 October, after a "
            "four-day negotiation over monitoring arrangements"
        ),
        alt_support=("S2",),
        wrong="S3",
        lure="monitors have reported no violations since the ceasefire began",
        parametric="ceasefires brokered by this group have historically held for about three weeks",
        distortion="mediators date the start of the ceasefire to midnight on 3 December",
    ),
    _Seed(
        n=40,
        domain="news",
        condition="sufficient",
        qtype="aggregation",
        prompt="What was the total value of the three contracts awarded?",
        passages=(
            "The first contract, for rolling stock maintenance, is worth 118 million.",
            "The second, covering depot works, is worth 46 million.",
            "The third, for signalling upgrades, is worth 91 million.",
        ),
        reference=(
            "255 million: 118 [S1] plus 46 [S2] plus 91 [S3]. Nothing in the passages "
            "states contract durations, so do not add any."
        ),
        answer=(
            "255 million in total, made up of 118 million for rolling stock maintenance, "
            "46 million for depot works and 91 million for signalling upgrades"
        ),
        support=("S1", "S2", "S3"),
        wrong="S2",
        lure="all three contracts run for five years",
        parametric="signalling upgrades of this size normally take about four years to deliver",
        distortion="355 million in total across the three contracts",
    ),
)


# --------------------------------------------------------------------------
# item construction
# --------------------------------------------------------------------------


def _item_id(n: int) -> str:
    return f"{TRACK_KEY}-{n:04d}"


def _passage_ids(seed: _Seed) -> tuple[str, ...]:
    return tuple(f"S{i}" for i in range(1, len(seed.passages) + 1))


def _render_context(seed: _Seed) -> str:
    return "\n".join(
        f"[{pid}] {text}" for pid, text in zip(_passage_ids(seed), seed.passages)
    )


def seed_items() -> list[TaskItem]:
    """Build the 40 pilot items.

    The strata grid is fully crossed by construction: eight items per
    ``evidence_condition``, eight per ``question_type`` and eight per ``domain``,
    with no (domain, condition) cell left empty. Each item's passages were
    written so that its declared ``evidence_condition`` is literally true of
    them - a ``conflicting`` item contains two passages that cannot both be
    right, and an ``insufficient`` item contains no passage from which the
    answer can be derived. That is the property the whole track rests on; if it
    were only approximately true, ``abstention_appropriateness`` would be
    unscoreable.
    """
    items: list[TaskItem] = []
    for seed in _SEEDS:
        strata = {
            "domain": seed.domain,
            "evidence_condition": seed.condition,
            "question_type": seed.qtype,
        }
        metadata = {
            "n_passages": len(seed.passages),
            "passage_ids": list(_passage_ids(seed)),
            "supporting_passages": list(seed.support),
            "answerable": seed.condition != "insufficient",
            "gold_target": "reference answer sketch" if seed.gold else None,
        }
        items.append(
            TaskItem(
                item_id=_item_id(seed.n),
                track=TRACK_KEY,
                prompt=seed.prompt,
                context=_render_context(seed),
                reference=seed.reference,
                strata=strata,
                metadata=metadata,
                gold_scores=dict(seed.gold) if seed.gold else None,
                is_gold=seed.gold is not None,
            )
        )
    return items


# --------------------------------------------------------------------------
# fixture responses
# --------------------------------------------------------------------------

# Stipulated planted-failure rates. These are properties of the fixture, not
# measurements of any system: the point is to give the annotation pipeline a
# known signal to recover, so detection sensitivity can be estimated.
_SYSTEM_FAILURE_RATES: Mapping[str, float] = {
    "sut-baseline-v1": 0.50,
    "sut-candidate-v2": 0.32,
    "sut-candidate-v3": 0.30,
}

_SYSTEM_LATENCY_MS: Mapping[str, tuple[float, float]] = {
    "sut-baseline-v1": (620.0, 2100.0),
    "sut-candidate-v2": (900.0, 3400.0),
    "sut-candidate-v3": (1100.0, 4200.0),
}

_CONFLATE_NOUN: Mapping[str, str] = {
    "policy": "provision",
    "biomedical": "study population",
    "financial_filing": "instrument",
    "technical_docs": "component",
    "news": "event",
}

_CITE_RE = re.compile(r"\[(S\d+)\]")


def _cap(text: str) -> str:
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1 :]
    return text


def _sent(text: str) -> str:
    text = _cap(text.strip())
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _cite(ids: Sequence[str]) -> str:
    return "".join(f"[{i}]" for i in ids)


def _fabricated_id(seed: _Seed) -> str:
    """An identifier that is plausibly shaped but absent from the context."""
    return f"S{len(seed.passages) + 4}"


def _clean_text(seed: _Seed, system_id: str) -> str:
    if seed.condition == "insufficient":
        body = (
            f"The provided context does not answer this. {seed.missing} "
            f"To answer it I would need {seed.need}."
        )
    elif seed.condition == "conflicting":
        body = (
            "The passages disagree, so I am reporting both accounts rather than "
            f"choosing between them. {_sent(seed.answer)} {_cite(seed.support)} "
            f"{_sent(seed.alt)} {_cite(seed.alt_support)}"
        )
    else:
        body = f"{_sent(seed.answer)} {_cite(seed.support)}"

    if system_id == "sut-candidate-v2":
        return f"Working only from the retrieved passages: {body[0].lower()}{body[1:]}"
    if system_id == "sut-candidate-v3":
        if seed.condition == "insufficient":
            return f"{body} I have not filled the gap from background knowledge."
        return f"{body} No other passage in the retrieved set bears on this question."
    return body


def _failure_text(seed: _Seed, code: str) -> str:
    insufficient = seed.condition == "insufficient"
    support = seed.support or (seed.wrong,)
    fake = _fabricated_id(seed)

    if code == "GF-01":
        if insufficient:
            return (
                f"{_sent(seed.guess)} [{fake}] states this directly, so the "
                f"context does settle the question [{fake}]."
            )
        return (
            f"{_sent(seed.answer)} {_cite(support)} This is confirmed by "
            f"[{fake}], which repeats the same detail."
        )

    if code == "GF-02":
        if insufficient:
            return f"{_cap(seed.guess)}, as set out in [{seed.wrong}]."
        return f"{_cap(seed.answer)}, as set out in [{seed.wrong}]."

    if code == "GF-03":
        if insufficient:
            return (
                f"The passages do not say so directly, but it follows from "
                f"[{seed.wrong}] that {seed.guess}."
            )
        return (
            f"{_sent(seed.answer)} {_cite(support)} It follows from the same "
            f"passages that {seed.lure} {_cite(support)}"
        )

    if code == "GF-04":
        if insufficient:
            return f"{_sent(seed.guess)} {_sent(seed.parametric)}"
        return f"{_sent(seed.answer)} {_cite(support)} {_sent(seed.parametric)}"

    if code == "GF-05":
        anchor_id = support[0]
        return (
            f"{_sent(seed.answer)} [{anchor_id}] Since [{anchor_id}] is the "
            "governing source here, the same holds for every comparable case in "
            "this document set, not only the one asked about."
        )

    if code == "GF-06":
        return f"{_sent(seed.contradiction)} {_cite(support)}"

    if code == "GF-07":
        return (
            f"{_sent(seed.guess)} [{seed.wrong}] The passages are clear on "
            "this point."
        )

    if code == "GF-08":
        return (
            "I cannot answer this from the provided context. The passages cover "
            "related material, but none of them states the fact the question "
            "asks for, so any answer would be speculation."
        )

    if code == "GF-09":
        return (
            f"{_sent(seed.answer)} {_cite(seed.support)} The passages are "
            "consistent on this point."
        )

    if code == "GF-10":
        a = support[0]
        b = seed.wrong if seed.wrong != a else support[-1]
        noun = _CONFLATE_NOUN[seed.domain]
        return (
            f"{_sent(seed.answer)} [{a}][{b}] Passages [{a}] and [{b}] describe "
            f"the same {noun}, so their figures can be read together: "
            f"{seed.lure}."
        )

    if code == "GF-11":
        return (
            f"As things currently stand, {seed.stale_claim} [{seed.stale}]. "
            "That is the position that applies now."
        )

    if code == "GF-12":
        return f"{_sent(seed.distortion)} {_cite(support)}"

    raise ValueError(f"no generator for failure code {code!r}")


def _failure_pool(seed: _Seed) -> tuple[tuple[str, int], ...]:
    """Failure codes this item can genuinely exhibit, with sampling weights.

    A code is only offered when the seed carries the material needed to make
    the generated text actually display it. Labelling a response GF-11 when no
    passage in its context is superseded would make the planted-failure column
    a fiction, and the whole point of that column is to measure detection.
    """
    pool: list[tuple[str, int]] = []

    if seed.condition == "insufficient":
        pool.append(("GF-07", 6))
        pool.append(("GF-01", 2))
        pool.append(("GF-04", 3))
        pool.append(("GF-03", 2))
        pool.append(("GF-02", 2))
        if seed.stale and seed.stale_claim:
            pool.append(("GF-11", 5))
        return tuple(pool)

    pool.append(("GF-01", 2))
    pool.append(("GF-02", 4 if seed.condition == "distractor_heavy" else 2))
    if seed.lure:
        pool.append(("GF-03", 4 if seed.condition == "partially_relevant" else 2))
    if seed.parametric:
        pool.append(("GF-04", 2))
    if seed.support:
        pool.append(("GF-05", 2))
    if seed.contradiction:
        pool.append(("GF-06", 2))
    if seed.condition in ("sufficient", "distractor_heavy", "partially_relevant"):
        pool.append(("GF-08", 2))
    if seed.alt:
        pool.append(("GF-09", 6))
    if seed.lure and len(seed.passages) >= 3 and seed.support:
        pool.append(("GF-10", 2))
    if seed.stale and seed.stale_claim:
        pool.append(("GF-11", 6))
    if seed.distortion:
        pool.append(("GF-12", 2))
    return tuple(pool)


def _pick_failure(pool: Sequence[tuple[str, int]], rng: random.Random) -> str:
    total = sum(w for _, w in pool)
    draw = rng.randrange(total)
    upto = 0
    for code, weight in pool:
        upto += weight
        if draw < upto:
            return code
    return pool[-1][0]


def fixture_responses(items: list[TaskItem]) -> list[ModelResponse]:
    """Three synthetic responses per item, one per system under test.

    Failure assignment is deterministic in two layers. Which items a system
    fails on is drawn from a shuffle seeded on the system id alone, so each
    system's planted-failure rate is exact rather than binomially noisy:
    20/40 for the baseline, 13/40 for v2, 12/40 for v3. Which failure it
    exhibits, and the surface form of the text, are drawn from a generator
    seeded on ``item_id + system_id``, so the same item can fail differently
    across systems. Nothing here reads the clock or the global random state.
    """
    by_id = {_item_id(seed.n): seed for seed in _SEEDS}
    missing = [item.item_id for item in items if item.item_id not in by_id]
    if missing:
        raise KeyError(
            f"{TRACK_KEY}.fixture_responses: no seed record for {missing[:3]}; "
            "pass the list returned by seed_items()"
        )

    failing_by_system: dict[str, set[int]] = {}
    for system_id, rate in _SYSTEM_FAILURE_RATES.items():
        order = list(range(len(items)))
        random.Random(f"{TRACK_KEY}::select::{system_id}").shuffle(order)
        n_fail = int(round(rate * len(items)))
        failing_by_system[system_id] = set(order[:n_fail])

    responses: list[ModelResponse] = []
    for index, item in enumerate(items):
        seed = by_id[item.item_id]
        for system_id in _SYSTEM_FAILURE_RATES:
            rng = random.Random(f"{item.item_id}::{system_id}")
            planted: str | None = None
            if index in failing_by_system[system_id]:
                pool = _failure_pool(seed)
                planted = _pick_failure(pool, rng)
                text = _failure_text(seed, planted)
            else:
                text = _clean_text(seed, system_id)

            cited = sorted(set(_CITE_RE.findall(text)), key=lambda s: int(s[1:]))
            available = list(_passage_ids(seed))
            lo, hi = _SYSTEM_LATENCY_MS[system_id]
            responses.append(
                ModelResponse(
                    response_id=f"{item.item_id}::{system_id}",
                    item_id=item.item_id,
                    system_id=system_id,
                    text=text,
                    trace=(
                        {
                            "step": "generate",
                            "available_passages": available,
                            "cited_passages": cited,
                            "dangling_citations": [
                                c for c in cited if c not in available
                            ],
                        },
                    ),
                    latency_ms=round(rng.uniform(lo, hi), 1),
                    tokens_out=len(text.split()) * 4 // 3 + rng.randrange(6),
                    planted_failure=planted,
                    metadata={
                        "domain": seed.domain,
                        "evidence_condition": seed.condition,
                        "question_type": seed.qtype,
                        "is_clean_fixture": planted is None,
                    },
                )
            )
    return responses


__all__ = ["SPEC", "fixture_responses", "seed_items"]
