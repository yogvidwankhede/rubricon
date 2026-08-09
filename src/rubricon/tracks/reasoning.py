"""Reasoning track: scoring the process, not just the outcome.

Answer-only accuracy is the default measurement for reasoning tasks because it is
cheap and unambiguous: the model either produced the reference answer or it did
not. The cost of that convenience is that accuracy is blind to *how* the answer
was produced. A model that reaches the right result through an invalid
derivation is scored identically to one that reasoned correctly, even though the
two have very different failure profiles under distribution shift. We call this
the "right answer, wrong reasoning" case, and it is the reason this track
exists. It is a latent failure: the outcome metric records a success while the
underlying capability is absent, so the failure surfaces only later, on a
neighbouring problem where the invalid shortcut no longer happens to land on the
correct number.

The research question is therefore two-part. First, **does process scoring add
signal beyond outcome scoring** - concretely, do ``answer_correctness`` and
``step_validity`` dissociate often enough, and in a systematic enough way, to be
worth the annotation cost? If the two dimensions are near-perfectly correlated
in practice, this track is an expensive re-derivation of accuracy and should be
retired. Second, **can annotators do process scoring reliably**? Judging whether
each step follows from the prior state is a harder discrimination than judging a
final answer, and reliability is not something we are willing to assume. The
fixture population in this module is deliberately loaded with right-answer /
invalid-path responses (thirteen of one hundred and thirty-two) precisely so
that the dissociation is measurable rather than hypothetical: an annotation
protocol that cannot separate those cases from clean solutions has failed its
first test.

The rubric has five dimensions. ``answer_correctness`` is binary and is the
outcome baseline we are trying to beat. ``step_validity``, ``premise_fidelity``
and ``verification_behavior`` are ordinal process dimensions that are, in
principle, checkable against the text: a reader can point at the step that does
not follow, at the constraint that was dropped or invented, at the absent or
fabricated check. ``premise_fidelity`` is marked critical with a threshold of
zero because a solution built on an invented or discarded given is not a partly
correct solution to the stated problem - it is a correct solution to a different
problem, and averaging it into a composite score would launder that.

One dimension deserves an explicit caveat rather than a footnote.
``explanation_faithfulness`` asks whether the stated reasoning is the reasoning
that actually determined the answer, and that is not directly observable from an
output transcript. We can see textual *symptoms* of post-hoc rationalisation -
the answer asserted before any derivation, a stated rule that does not in fact
yield the stated number, a derivation whose decisive step is a re-assertion of
the conclusion - but symptoms are a proxy, not the construct. Without
chain-of-thought instrumentation we cannot observe the computation that produced
the answer, only the story told about it. We therefore expect
``explanation_faithfulness`` to show the lowest inter-annotator agreement of the
five dimensions, and we would rather report that up front than discover it in an
alpha table and rationalise it afterwards. This track is depth ``pilot``: its
numbers are for deciding whether to build the production version, not for
quoting as measurements of a system.
"""

from __future__ import annotations

import random
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

TRACK_KEY = "reasoning"

SYSTEM_IDS: tuple[str, ...] = (
    "sut-baseline-v1",
    "sut-candidate-v2",
    "sut-candidate-v3",
)

# --------------------------------------------------------------------------
# failure taxonomy
# --------------------------------------------------------------------------

FAILURE_CODES: Mapping[str, str] = {
    "RF-01": (
        "right_answer_invalid_path - the final answer matches the reference but "
        "the derivation that reaches it is not valid: an invented rule, a "
        "coincidence, or two errors that cancel."
    ),
    "RF-02": (
        "arithmetic_slip - a local computation is wrong (a product, sum or "
        "simplification) while the surrounding method is sound."
    ),
    "RF-03": (
        "dropped_constraint - a given stated in the problem is silently ignored "
        "(a domain exclusion, a parity requirement, a second revenue stream)."
    ),
    "RF-04": (
        "invented_premise - the solution asserts a fact the problem never gave "
        "(replacement between draws, a midpoint meeting, a copied list)."
    ),
    "RF-05": (
        "unit_error - the numbers are handled correctly but the units are not: "
        "a missing conversion factor, a squared factor applied once, a rate "
        "treated as a total."
    ),
    "RF-06": (
        "sign_error - a sign is lost or flipped during distribution or "
        "transposition across the equals sign."
    ),
    "RF-07": (
        "circular_justification - the decisive step assumes the conclusion and "
        "then offers the conclusion's own consistency as evidence for it."
    ),
    "RF-08": (
        "post_hoc_rationalization - the answer is produced first by recognition "
        "or recall, and the presented derivation is a narrative assembled "
        "around it rather than the reasoning that produced it."
    ),
    "RF-09": (
        "unjustified_leap - the decisive inference is skipped: the text moves "
        "from setup to result with 'clearly' or 'it follows that' and no "
        "intervening argument."
    ),
    "RF-10": (
        "no_verification - the solution ends at the first candidate answer with "
        "no substitution back, no magnitude check and no edge-case test."
    ),
    "RF-11": (
        "verification_theater - the solution claims to have checked its work "
        "but the claimed check contains no numbers, no substitution and no "
        "quantity that could have failed."
    ),
    "RF-12": (
        "off_by_one - an index, bound or count is out by one: an inclusive "
        "range read as exclusive, a term index shifted, a loop run once too "
        "often."
    ),
    "RF-13": (
        "case_analysis_incomplete - the problem requires a split into cases and "
        "at least one required case is never examined."
    ),
}

# --------------------------------------------------------------------------
# strata design
# --------------------------------------------------------------------------

STRATA_DESIGN: Mapping[str, Sequence[str]] = {
    "problem_domain": (
        "arithmetic_word",
        "algebra",
        "combinatorics",
        "logic_puzzle",
        "code_trace",
        "unit_conversion",
        "probability",
    ),
    "difficulty": ("easy", "medium", "hard"),
    "trap_type": (
        "none",
        "plausible_wrong_path",
        "ambiguous_wording",
        "extraneous_information",
        "requires_case_split",
    ),
    "answer_type": ("numeric", "symbolic", "categorical"),
}

# --------------------------------------------------------------------------
# rubric
# --------------------------------------------------------------------------

_ANSWER_CORRECTNESS = Dimension(
    key="answer_correctness",
    name="Answer correctness",
    question=(
        "Does the final stated answer match the reference answer, allowing for "
        "equivalent forms (2/15 and 0.133, '48' and 'forty-eight')?"
    ),
    scale=ScaleType.BINARY,
    levels=(0, 1),
    weight=1.0,
    notes=(
        "Score the final stated answer only. Do not let a broken derivation "
        "pull this score down; that is what step_validity is for. The whole "
        "design depends on these two dimensions being scored independently."
    ),
    anchors=(
        Anchor(
            value=0,
            label="Incorrect or absent",
            description=(
                "The final answer differs from the reference, is missing, or is "
                "hedged to the point that no single answer is stated."
            ),
            example=(
                "Reference is 25 minutes. Response ends 'the tank fills in 40 "
                "minutes'. Score 0 even though every step before the dropped "
                "'3/8 full' constraint was clean."
            ),
            counter_example=(
                "Reference is 2/15; response says 0.1333. That is the same "
                "number in a different form - score 1, not 0."
            ),
        ),
        Anchor(
            value=1,
            label="Correct",
            description=(
                "The final answer matches the reference, in any equivalent "
                "notation, rounding convention or unit stated in the problem."
            ),
            example=(
                "Reference is 'No solution (x = 2 is excluded)'. Response ends "
                "'the solution set is empty'. Score 1."
            ),
            counter_example=(
                "Response derives x = 7 and x = -2 correctly in the body but "
                "the final line states only 'x = 7'. The stated answer is "
                "incomplete, so score 0."
            ),
        ),
    ),
)

_STEP_VALIDITY = Dimension(
    key="step_validity",
    name="Step validity",
    question=(
        "Is every step a valid inference from the state established by the "
        "steps before it?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2, 3),
    weight=1.5,
    notes=(
        "Judge each transition locally: given what the response has established "
        "so far, does this line follow? A step can be locally valid inside a "
        "solution that is globally wrong, and a step can be invalid inside a "
        "solution that reaches the right answer."
    ),
    anchors=(
        Anchor(
            value=0,
            label="Decisive step is invalid",
            description=(
                "The step that determines the answer does not follow: it "
                "applies a rule that does not exist, asserts a numeric result "
                "with no derivation, or contradicts an earlier line."
            ),
            example=(
                "'Both sides balance when their coefficients balance: -2 and 3 "
                "sum to 1, the constants differ by 10, and the root is the "
                "constant gap over the coefficient gap, 10/5 = 2.' The rule is "
                "invented; it produces x = 2 by coincidence."
            ),
            counter_example=(
                "'1/12 + 1/18 = 2/30' is a wrong computation, not an invalid "
                "inference pattern - the response is combining rates correctly "
                "and slipping on the addition. Score 1, not 0."
            ),
        ),
        Anchor(
            value=1,
            label="Substantive invalid step",
            description=(
                "One or more steps do not follow, or a computation error breaks "
                "the chain, but the overall method is a recognisable and "
                "appropriate method for the problem."
            ),
            example=(
                "'2(y + 3) + 3y = 31, so 5y = 31 + 6 = 37.' Substitution and "
                "collection are the right method; the transposition sign is "
                "wrong, so everything downstream is unsupported."
            ),
            counter_example=(
                "A solution that is entirely valid but stops one case short of "
                "a complete answer is a premise/coverage problem, not a step "
                "problem, if every step it did take was sound."
            ),
        ),
        Anchor(
            value=2,
            label="Valid but with a gap",
            description=(
                "Every stated step is defensible, but at least one transition "
                "is compressed enough that the reader must supply the "
                "justification (a formula used without naming it, a case "
                "collapsed into 'similarly')."
            ),
            example=(
                "'C(9,3) = 84, all-male committees C(5,3) = 10, so 74.' The "
                "complement argument is never stated, but each line is correct "
                "and the missing link is one short sentence."
            ),
            counter_example=(
                "'From here the answer is immediate: 22.2 degrees C', with no "
                "conversion shown at all, is not a gap - it is the decisive "
                "step missing. Score 1."
            ),
        ),
        Anchor(
            value=3,
            label="Every step follows",
            description=(
                "Each line is a valid inference from the previous state, and "
                "the justification for each transition is present in the text."
            ),
            example=(
                "'range(1, 6) yields 1..5 because the upper bound is exclusive; "
                "the loop accumulates 1+2+3+4+5; s = 15.' Each claim is stated "
                "and each follows."
            ),
            counter_example=(
                "A flawless derivation of the wrong quantity - correct algebra "
                "answering a question the problem did not ask - still scores 3 "
                "here. The mismatch is a premise_fidelity failure."
            ),
        ),
    ),
)

_PREMISE_FIDELITY = Dimension(
    key="premise_fidelity",
    name="Premise fidelity",
    question=(
        "Does the solution use the problem's actual givens - all of them, and "
        "only them - without inventing constraints or discarding stated ones?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2, 3),
    weight=1.5,
    critical=True,
    critical_threshold=0,
    notes=(
        "Critical dimension. A score of 0 zeroes the item: a solution resting "
        "on an invented or discarded given is a correct answer to a different "
        "problem. Deliberately unused extraneous information is not a fidelity "
        "failure - ignoring the party's duration in a handshake count is right."
    ),
    anchors=(
        Anchor(
            value=0,
            label="Invented or discarded given",
            description=(
                "The solution asserts a constraint the problem never stated, or "
                "silently drops one it did state, and the answer depends on it."
            ),
            example=(
                "'Assume the two trains meet at the midpoint of the 300 km "
                "gap.' The problem gives unequal speeds; the midpoint is "
                "invented and drives the wrong answer of 150 km."
            ),
            counter_example=(
                "Naming the rounding convention the problem did not specify "
                "('to two decimal places') is a presentation choice, not an "
                "invented premise, when the problem's answer is insensitive to "
                "it."
            ),
        ),
        Anchor(
            value=1,
            label="Given misread or partially used",
            description=(
                "A stated given is misread or applied to only part of its "
                "scope: the constraint is present in the text but the solution "
                "honours a weaker version of it."
            ),
            example=(
                "'Three consecutive integers summing to 138' when the problem "
                "said three consecutive *even* integers. The parity given is "
                "acknowledged in the restatement and then not used."
            ),
            counter_example=(
                "Never mentioning parity at all, and solving a problem that "
                "cannot produce the stated sum, is a full drop - score 0."
            ),
        ),
        Anchor(
            value=2,
            label="All givens used, one handled loosely",
            description=(
                "Every stated given appears and none is invented, but one is "
                "handled imprecisely - an exclusion noted then not enforced "
                "until the end, or a unit carried informally."
            ),
            example=(
                "The domain exclusions x != +/-2 are stated up front, then not "
                "referenced again until the final line rejects x = 2. Correct "
                "outcome, loose bookkeeping."
            ),
            counter_example=(
                "Stating the exclusion and then reporting x = 2 as the solution "
                "is not looseness - the given was discarded. Score 0."
            ),
        ),
        Anchor(
            value=3,
            label="Faithful to the problem as stated",
            description=(
                "Every stated given is used where it belongs, nothing is "
                "invented, and any extraneous information is correctly "
                "identified as irrelevant rather than silently dropped."
            ),
            example=(
                "'The tank's height and diameter are not needed' - the solution "
                "names the extraneous givens and explains why they do not "
                "enter."
            ),
            counter_example=(
                "Using the extraneous height to build a spurious "
                "height-per-minute rate, even if it lands on the right number, "
                "is not fidelity to the problem's structure. Score 2 at best."
            ),
        ),
    ),
)

_VERIFICATION_BEHAVIOR = Dimension(
    key="verification_behavior",
    name="Verification behaviour",
    question=(
        "Does the solution check its own work - substitute back, sanity-check "
        "the magnitude, or test the edge and boundary cases?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2, 3),
    weight=1.0,
    notes=(
        "Score the check that is present, not the check you would have done. A "
        "claimed check with no quantity in it scores 1, not 2: it is weaker "
        "than no claim at all because it manufactures unearned confidence."
    ),
    anchors=(
        Anchor(
            value=0,
            label="No checking",
            description=(
                "The solution stops at the first candidate answer. No "
                "substitution, no magnitude comment, no alternative route, no "
                "acknowledgement that the result could be wrong."
            ),
            example=(
                "'7.5 x 240 = 1800 L. Final answer: 1800 litres.' Eighteen "
                "hundred litres of fuel for a 240 km trip is absurd and nothing "
                "in the response notices."
            ),
            counter_example=(
                "A single line - 'that is about a tank and a half, which is "
                "plausible' - is a magnitude check and lifts the score to 2."
            ),
        ),
        Anchor(
            value=1,
            label="Verification claimed but empty",
            description=(
                "The solution says it verified the result, but the stated check "
                "contains no numbers, no substitution and nothing that could "
                "have come out wrong."
            ),
            example=(
                "'I substituted the result back into the original statement and "
                "everything is consistent.' Nothing is substituted; no value "
                "appears."
            ),
            counter_example=(
                "'Check: 3(19 - 4) = 45 and 2(19) + 7 = 45' is a real "
                "substitution with a quantity that could have disagreed. Score "
                "2 or 3."
            ),
        ),
        Anchor(
            value=2,
            label="One real check",
            description=(
                "Exactly one genuine check is performed: the answer is "
                "substituted back, or recomputed by a second route, or its "
                "magnitude is compared against a stated reference point."
            ),
            example=(
                "'Check: 25 min x 12 L/min = 300 L added, and 180 + 300 = 480 "
                "L, the full capacity.' One substitution, real numbers."
            ),
            counter_example=(
                "Two independent routes plus a boundary case - 'and if the "
                "drawn fruit had been an orange, the same argument gives the "
                "mirrored labelling' - is broader. Score 3."
            ),
        ),
        Anchor(
            value=3,
            label="Checked from more than one angle",
            description=(
                "The solution verifies by an independent route or covers the "
                "boundary and symmetric cases, and states what the check would "
                "have shown if the answer were wrong."
            ),
            example=(
                "'Check by counting subsets: C(4,2)/C(10,2) = 6/45 = 2/15. The "
                "sequential and combinatorial routes agree.' A second, "
                "structurally different derivation."
            ),
            counter_example=(
                "Restating the same computation in the same order with the same "
                "numbers is not an independent route. Score 2."
            ),
        ),
    ),
)

_EXPLANATION_FAITHFULNESS = Dimension(
    key="explanation_faithfulness",
    name="Explanation faithfulness",
    question=(
        "Does the stated reasoning look like the reasoning that actually "
        "determined the answer, or like a narrative assembled around a "
        "conclusion that arrived some other way?"
    ),
    scale=ScaleType.ORDINAL,
    levels=(0, 1, 2, 3),
    weight=1.0,
    notes=(
        "This is the weakest-defined dimension in the rubric and we expect the "
        "lowest agreement on it. Faithfulness is not directly observable from "
        "an output transcript; score the textual symptoms listed in the "
        "anchors, and do not infer unfaithfulness merely because a derivation "
        "is terse or a model is fast."
    ),
    anchors=(
        Anchor(
            value=0,
            label="Clearly post-hoc",
            description=(
                "The answer is asserted before any derivation, or the response "
                "says outright that it recognised the answer and then wrote up "
                "a justification; the presented steps do not determine the "
                "stated number."
            ),
            example=(
                "'Final answer: 48. (I recognised the type immediately; the "
                "write-up below is a tidy-up of that recognition.)' followed by "
                "steps ending 'which is the kind of setup that yields 48'."
            ),
            counter_example=(
                "Stating the answer first and then giving a derivation that "
                "genuinely produces it is a presentation order, not a "
                "faithfulness failure. Score 2 or 3."
            ),
        ),
        Anchor(
            value=1,
            label="Stated route cannot have produced the answer",
            description=(
                "The narrative and the number are inconsistent: the rule quoted "
                "does not yield the stated value, or the decisive line "
                "re-asserts the conclusion instead of deriving it, so the real "
                "route is hidden."
            ),
            example=(
                "'Collatz stopping times grow like 6.95 x ln(n), so 22.9 steps; "
                "27 is an outlier by a factor of 4.85, and 22.9 x 4.85 = 111.' "
                "The constants exist only to reach 111."
            ),
            counter_example=(
                "An honest wrong rule that genuinely produces the stated wrong "
                "answer is faithful - the model reported what it did. Score 2."
            ),
        ),
        Anchor(
            value=2,
            label="Mostly faithful, one unexplained move",
            description=(
                "The derivation plausibly produced the answer, but one step is "
                "presented with more confidence than its content supports, or a "
                "discarded attempt is dropped without saying why."
            ),
            example=(
                "'That is 0.643, slightly above the initial fraction; the "
                "dependence should not raise the probability, so take 5/8.' The "
                "abandonment is real but the reason given is thin."
            ),
            counter_example=(
                "Explicitly narrating the abandoned route and why it was wrong "
                "('averaging conditionals ignores their unequal weights') makes "
                "it fully faithful. Score 3."
            ),
        ),
        Anchor(
            value=3,
            label="Transcript matches the work",
            description=(
                "The steps read as the actual working: intermediate values are "
                "carried forward and used, dead ends are named as dead ends, "
                "and the final number falls out of the last step rather than "
                "being restated into it."
            ),
            example=(
                "'Suppose A is a knight. Then A's statement is true, so A is a "
                "knave - a contradiction. So A is a knave.' The refuted branch "
                "is shown doing work."
            ),
            counter_example=(
                "A polished write-up that never shows a considered alternative "
                "is not automatically unfaithful - most correct short-form "
                "solutions have no dead ends. Do not score below 3 for "
                "tidiness alone."
            ),
        ),
    ),
)

RUBRIC = Rubric(
    key="reasoning",
    name="Process-level reasoning quality",
    description=(
        "Scores one worked solution on both outcome and process. The binary "
        "answer_correctness dimension reproduces the conventional accuracy "
        "metric; the four ordinal process dimensions are the hypothesis under "
        "test. The design question is whether answer_correctness and "
        "step_validity dissociate enough to justify the added annotation cost, "
        "and whether annotators can apply the process dimensions reliably."
    ),
    dimensions=(
        _ANSWER_CORRECTNESS,
        _STEP_VALIDITY,
        _PREMISE_FIDELITY,
        _VERIFICATION_BEHAVIOR,
        _EXPLANATION_FAITHFULNESS,
    ),
    revision=1,
    changelog=(
        "r1: initial pilot rubric. answer_correctness kept binary and scored "
        "first so that annotators commit to the outcome judgement before "
        "reading the derivation critically.",
    ),
)

SPEC = TrackSpec(
    key=TRACK_KEY,
    name="Reasoning process quality",
    research_question=(
        "Does scoring the reasoning process add signal beyond final-answer "
        "correctness, and can annotators apply process dimensions reliably? "
        "The headline case is 'right answer, wrong reasoning': a model that "
        "reaches the correct result through an invalid derivation is a latent "
        "failure that answer-only accuracy records as a success."
    ),
    depth="pilot",
    rubric=RUBRIC,
    unit_of_analysis="one worked solution, scored on both outcome and process",
    strata_design=STRATA_DESIGN,
    target_n=44,
    replication=3,
    gold_rate=0.15,
    failure_codes=FAILURE_CODES,
    known_limitations=(
        "explanation_faithfulness is not directly observable from output text. "
        "Annotators score textual symptoms of post-hoc rationalisation, which "
        "is a proxy for the construct, not the construct. We expect this "
        "dimension to show the lowest agreement and we will report it "
        "separately rather than pooling it into a headline alpha.",
        "There is no chain-of-thought interpretability instrumentation behind "
        "this track. We observe only the emitted transcript, so we cannot "
        "distinguish a model that reasoned as described from one that reasoned "
        "otherwise and produced a plausible transcript.",
        "Problems are short-form: three to six steps, single correct answer, "
        "solvable in under two minutes by a competent human. Findings do not "
        "transfer without re-piloting to long-horizon reasoning, multi-tool "
        "workflows, or open-ended proof.",
        "English only, and the problem set draws on conventions of "
        "English-language school mathematics (notation, phrasing of word "
        "problems, decimal comma versus point). Trap types such as "
        "ambiguous_wording are language-specific by construction.",
        "The reference answers are single canonical strings. Equivalent-form "
        "matching is left to annotator judgement rather than a normaliser, so "
        "answer_correctness carries a small amount of the very subjectivity it "
        "is supposed to be free of.",
        "n = 44 items at replication 3 is a pilot-scale sample. Per-cell counts "
        "in the four-way stratification are one to three items, which supports "
        "reliability estimation and nothing more; no per-stratum system "
        "comparison from this track should be treated as powered.",
    ),
)

# --------------------------------------------------------------------------
# problem bank
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Problem:
    """One seed problem plus the authored material needed to render fixtures.

    ``steps`` is a valid derivation whose *last* element is the decisive one -
    the generic failure renderers rely on that, dropping the final step to
    manufacture unjustified leaps and circular justifications.

    ``invalid_path`` is an authored derivation that arrives at the *correct*
    reference answer through reasoning that does not support it. This is the
    RF-01 material and the reason the track exists.

    ``wrong_steps`` is an authored derivation that arrives at ``wrong_answer``
    by way of the specific failure named in ``wrong_code``.
    """

    domain: str
    difficulty: str
    trap: str
    answer_type: str
    prompt: str
    answer: str
    steps: tuple[str, ...]
    check: str
    invalid_path: tuple[str, ...]
    wrong_answer: str
    wrong_steps: tuple[str, ...]
    wrong_code: str
    context: str = ""
    verified_by: str = "hand"


_PROBLEMS: tuple[_Problem, ...] = (
    # ---- arithmetic word problems (7) -----------------------------------
    _Problem(
        domain="arithmetic_word",
        difficulty="easy",
        trap="none",
        answer_type="numeric",
        prompt=(
            "A bakery sells croissants for $3.25 each. On Tuesday it sold 148 "
            "croissants. Of those, 26 were bought by loyalty members, who get "
            "$0.50 off each croissant. What was Tuesday's croissant revenue?"
        ),
        answer="$468.00",
        steps=(
            "Revenue if nobody had a discount: 148 x $3.25 = $481.00.",
            "Total discount given: 26 discounted croissants x $0.50 = $13.00.",
            "Revenue = $481.00 - $13.00 = $468.00.",
        ),
        check=(
            "Cross-check by splitting the sale: 122 x $3.25 = $396.50 and 26 x "
            "$2.75 = $71.50; $396.50 + $71.50 = $468.00."
        ),
        invalid_path=(
            "Treat the member sales as a markdown block: 26 x $3.25 = $84.50 "
            "comes out of the $481.00 gross.",
            "Only part of that block is actually discounted, so most of it has "
            "to come back in; the returning amount is $71.50.",
            "$481.00 - $84.50 + $71.50 = $468.00.",
        ),
        wrong_answer="$405.00",
        wrong_steps=(
            "Full-price revenue: 148 x $3.25 = $418.00.",
            "Member discount: 26 x $0.50 = $13.00.",
            "Revenue = $418.00 - $13.00 = $405.00.",
        ),
        wrong_code="RF-02",
        verified_by="python: 148*3.25 - 26*0.50 == 468.0",
    ),
    _Problem(
        domain="arithmetic_word",
        difficulty="easy",
        trap="extraneous_information",
        answer_type="numeric",
        prompt=(
            "A cylindrical tank holds 480 litres when full and is currently 3/8 "
            "full. The tank is 1.2 m tall and 0.7 m across. A pump adds water "
            "at 12 litres per minute. How many minutes until the tank is full?"
        ),
        answer="25 minutes",
        steps=(
            "Current volume: 3/8 x 480 = 180 L.",
            "Volume still needed: 480 - 180 = 300 L.",
            "Time: 300 L / 12 L per minute = 25 minutes.",
        ),
        check=(
            "Sanity check: 25 min x 12 L/min = 300 L added, and 180 + 300 = 480 "
            "L, the stated capacity. The height and diameter are not needed."
        ),
        invalid_path=(
            "3/8 of 480 is 150 L already in the tank.",
            "So 480 - 150 = 330 L are missing, which at 12 L/min is 27.5 "
            "minutes.",
            "Pumps of this size lose about 2.5 minutes to priming, so subtract "
            "that: 25 minutes.",
        ),
        wrong_answer="40 minutes",
        wrong_steps=(
            "The tank holds 480 L and the pump adds 12 L per minute.",
            "480 / 12 = 40.",
            "The tank fills in 40 minutes.",
        ),
        wrong_code="RF-03",
        verified_by="python: (480 - 480*3/8)/12 == 25.0",
    ),
    _Problem(
        domain="arithmetic_word",
        difficulty="medium",
        trap="plausible_wrong_path",
        answer_type="numeric",
        prompt=(
            "Two trains are 300 km apart on a straight track and start moving "
            "toward each other at the same moment. One travels at 60 km/h, the "
            "other at 90 km/h. How far has the slower train travelled when they "
            "meet?"
        ),
        answer="120 km",
        steps=(
            "Closing speed = 60 + 90 = 150 km/h.",
            "Time to meet = 300 km / 150 km/h = 2 hours.",
            "Distance covered by the slower train = 60 x 2 = 120 km.",
        ),
        check=(
            "Check: the faster train covers 90 x 2 = 180 km, and 120 + 180 = "
            "300 km, exactly the initial gap."
        ),
        invalid_path=(
            "Speeds are in the ratio 60:90 = 2:3, and distance ratios follow "
            "speed ratios.",
            "Ratios of speed give ratios of time, so the slower train needs 3/5 "
            "of the 200 km of effective track between the two starting points.",
            "3/5 x 200 = 120 km.",
        ),
        wrong_answer="150 km",
        wrong_steps=(
            "They start at the same time and move toward each other, so they "
            "meet in the middle of the 300 km gap.",
            "Half of 300 is 150.",
            "The slower train has travelled 150 km.",
        ),
        wrong_code="RF-04",
        verified_by="python: 60*(300/150) == 120.0",
    ),
    _Problem(
        domain="arithmetic_word",
        difficulty="medium",
        trap="ambiguous_wording",
        answer_type="numeric",
        prompt=(
            "A shirt is marked down 20%. The following week the store takes a "
            "further 10% off the already-reduced price. What single percentage "
            "discount off the original price is equivalent?"
        ),
        answer="28%",
        steps=(
            "Let the original price be P. After 20% off the price is 0.80P.",
            "A further 10% off that price gives 0.90 x 0.80P = 0.72P.",
            "The customer pays 72% of P, so the equivalent single discount is "
            "100% - 72% = 28%.",
        ),
        check=(
            "Check with P = $100: $100 -> $80 -> $72, a $28 reduction, which is "
            "28% of the original."
        ),
        invalid_path=(
            "Two discounts of 20% and 10% overlap, and the overlap is their "
            "product read as a percentage: 20 x 10 = 200, i.e. 2%.",
            "Discounts compose by averaging, (20 + 10)/2 = 15%, then doubling "
            "for the two-stage structure: 30%.",
            "Remove the 2% overlap: 30% - 2% = 28%.",
        ),
        wrong_answer="30%",
        wrong_steps=(
            "The store takes 20% off and then another 10% off.",
            "20% + 10% = 30%.",
            "The equivalent single discount is 30%.",
        ),
        wrong_code="RF-03",
        verified_by="python: round((1 - 0.8*0.9)*100, 6) == 28.0",
    ),
    _Problem(
        domain="arithmetic_word",
        difficulty="medium",
        trap="none",
        answer_type="numeric",
        prompt=(
            "A student's mean score over 5 tests is 82. What must the student "
            "score on a sixth test to raise the mean over all six tests to 84?"
        ),
        answer="94",
        steps=(
            "Current total = 5 x 82 = 410.",
            "Required total for six tests = 6 x 84 = 504.",
            "Sixth score = 504 - 410 = 94.",
        ),
        check="Check: (410 + 94)/6 = 504/6 = 84, the target mean.",
        invalid_path=(
            "The mean rises from 82 to 84, an increase of 2.44%.",
            "Applying that 2.44% to the running total of 410 gives 10.0 points "
            "of headroom.",
            "The sixth test must carry the new mean plus that headroom: 84 + 10 "
            "= 94.",
        ),
        wrong_answer="84",
        wrong_steps=(
            "Current total = 5 x 82 = 410.",
            "Required total for six tests = 6 x 84 = 494.",
            "Sixth score = 494 - 410 = 84.",
        ),
        wrong_code="RF-02",
        verified_by="python: 6*84 - 5*82 == 94",
    ),
    _Problem(
        domain="arithmetic_word",
        difficulty="hard",
        trap="none",
        answer_type="numeric",
        prompt=(
            "Working alone, Ana can paint a mural in 12 days and Ben can paint "
            "the same mural in 18 days. They work together for 4 days, then Ana "
            "leaves. How many more days does Ben need to finish alone?"
        ),
        answer="8 days",
        steps=(
            "Ana's rate is 1/12 of the mural per day; Ben's is 1/18 per day.",
            "Together: 1/12 + 1/18 = 3/36 + 2/36 = 5/36 per day.",
            "In 4 days they complete 4 x 5/36 = 20/36 = 5/9 of the mural.",
            "Remaining is 1 - 5/9 = 4/9, and (4/9) / (1/18) = 8 days for Ben.",
        ),
        check=(
            "Check in units of 1/36 of a mural: Ana does 3 per day, Ben 2 per "
            "day; 4 days together is 20 units; 36 - 20 = 16 units left; 16/2 = "
            "8 days."
        ),
        invalid_path=(
            "Ben alone is 18 days and Ana alone is 12, so the leftover must sit "
            "somewhere between 6 and 10 days.",
            "Try 8: if Ben needs 8 more days he supplies 8/18 = 4/9 of the "
            "mural, and 4/9 is the kind of clean fraction these problems are "
            "built around.",
            "So the answer is 8 days.",
        ),
        wrong_answer="13.2 days",
        wrong_steps=(
            "Combined rate: 1/12 + 1/18 = 2/30 = 1/15 of the mural per day.",
            "In 4 days they finish 4/15, leaving 11/15.",
            "Ben alone: (11/15) x 18 = 13.2 days.",
        ),
        wrong_code="RF-02",
        verified_by="python: Fraction: (1 - 4*(1/12+1/18)) / (1/18) == 8",
    ),
    _Problem(
        domain="arithmetic_word",
        difficulty="hard",
        trap="extraneous_information",
        answer_type="numeric",
        prompt=(
            "A shop buys 240 widgets at $7.50 each. It sells 180 of them at "
            "$12.00 each and clears the remaining 60 at $6.00 each. The shop's "
            "monthly rent is $2,000. What is the profit on the widgets alone?"
        ),
        answer="$720.00",
        steps=(
            "Cost of stock: 240 x $7.50 = $1,800.00.",
            "Full-price revenue: 180 x $12.00 = $2,160.00.",
            "Clearance revenue: 60 x $6.00 = $360.00.",
            "Profit = ($2,160.00 + $360.00) - $1,800.00 = $720.00.",
        ),
        check=(
            "Check per unit: full-price units earn $4.50 each (180 x 4.50 = "
            "$810) and clearance units lose $1.50 each (60 x -1.50 = -$90); "
            "$810 - $90 = $720. Rent is excluded by the phrase 'on the widgets "
            "alone'."
        ),
        invalid_path=(
            "The full-price markup is 12/7.50 = 1.6, a 60% markup, and 60% of "
            "the $1,800 stock cost is $1,080.",
            "Clearance units returned $360 against $450 of cost, a $90 hole: "
            "$1,080 - $90 = $990.",
            "The $1,080 already contained the 60 clearance units, so knock off "
            "their share, $270: $990 - $270 = $720.",
        ),
        wrong_answer="$360.00",
        wrong_steps=(
            "Cost of stock: 240 x $7.50 = $1,800.00.",
            "Revenue: 180 x $12.00 = $2,160.00.",
            "Profit = $2,160.00 - $1,800.00 = $360.00.",
        ),
        wrong_code="RF-03",
        verified_by="python: 180*12 + 60*6 - 240*7.5 == 720.0",
    ),
    # ---- algebra (7) -----------------------------------------------------
    _Problem(
        domain="algebra",
        difficulty="easy",
        trap="none",
        answer_type="numeric",
        prompt="Solve for x: 3(x - 4) = 2x + 7.",
        answer="x = 19",
        steps=(
            "Expand the left side: 3x - 12 = 2x + 7.",
            "Subtract 2x from both sides: x - 12 = 7.",
            "Add 12 to both sides: x = 19.",
        ),
        check="Check: 3(19 - 4) = 3 x 15 = 45, and 2 x 19 + 7 = 45. Both sides agree.",
        invalid_path=(
            "Bring everything to one side: 3x - 12 - 2x + 7 = 0, so x - 5 = 0 "
            "and x = 5.",
            "x = 5 fails the check, which means the constant was moved with the "
            "wrong sign; the repair is to add the two constants instead.",
            "12 + 7 = 19, so x = 19.",
        ),
        wrong_answer="x = -5",
        wrong_steps=(
            "Expand: 3x - 12 = 2x + 7.",
            "Collect: 3x - 2x = 7 - 12.",
            "x = -5.",
        ),
        wrong_code="RF-06",
        verified_by="python: 3*(19-4) == 2*19+7",
    ),
    _Problem(
        domain="algebra",
        difficulty="easy",
        trap="plausible_wrong_path",
        answer_type="numeric",
        prompt="Solve for x: -2(x + 5) = 3x - 20.",
        answer="x = 2",
        steps=(
            "Expand the left side: -2x - 10 = 3x - 20.",
            "Add 2x to both sides: -10 = 5x - 20.",
            "Add 20 to both sides: 10 = 5x.",
            "Divide by 5: x = 2.",
        ),
        check="Check: -2(2 + 5) = -14, and 3 x 2 - 20 = -14. Both sides agree.",
        invalid_path=(
            "A linear equation balances when its coefficients balance: -2 on "
            "the left and 3 on the right differ by 5.",
            "The constants are -10 on the left and -20 on the right, a gap of "
            "10.",
            "The root is the constant gap over the coefficient gap: 10/5 = 2.",
        ),
        wrong_answer="x = 6",
        wrong_steps=(
            "Expand the left side: -2(x + 5) = -2x + 10.",
            "So -2x + 10 = 3x - 20.",
            "Add 2x and 20 to both sides: 30 = 5x.",
            "x = 6.",
        ),
        wrong_code="RF-06",
        verified_by="python: -2*(2+5) == 3*2-20",
    ),
    _Problem(
        domain="algebra",
        difficulty="medium",
        trap="none",
        answer_type="numeric",
        prompt="Solve the system: 2x + 3y = 31 and x - y = 3.",
        answer="x = 8, y = 5",
        steps=(
            "From the second equation, x = y + 3.",
            "Substitute into the first: 2(y + 3) + 3y = 31, i.e. 2y + 6 + 3y = "
            "31.",
            "So 5y = 25 and y = 5.",
            "Then x = 5 + 3 = 8.",
        ),
        check=(
            "Check both equations: 2(8) + 3(5) = 16 + 15 = 31, and 8 - 5 = 3."
        ),
        invalid_path=(
            "Add the two equations: 3x + 2y = 34.",
            "A system whose two forms are 2x + 3y and 3x + 2y is coefficient-"
            "symmetric, and symmetric systems resolve to the integer pair with "
            "the stated difference summing to 13.",
            "The pair differing by 3 and summing to 13 is 8 and 5, so x = 8 and "
            "y = 5.",
        ),
        wrong_answer="x = 10.4, y = 7.4",
        wrong_steps=(
            "From the second equation, x = y + 3.",
            "Substitute: 2y + 6 + 3y = 31.",
            "Collect: 5y = 31 + 6 = 37, so y = 7.4.",
            "Then x = 7.4 + 3 = 10.4.",
        ),
        wrong_code="RF-02",
        verified_by="python: 2*8+3*5 == 31 and 8-5 == 3",
    ),
    _Problem(
        domain="algebra",
        difficulty="medium",
        trap="requires_case_split",
        answer_type="symbolic",
        prompt="Solve for all real x: |2x - 5| = 9.",
        answer="x = 7 or x = -2",
        steps=(
            "An absolute value equals 9 exactly when its argument is 9 or -9, "
            "so there are two cases.",
            "Case 1: 2x - 5 = 9 gives 2x = 14 and x = 7.",
            "Case 2: 2x - 5 = -9 gives 2x = -4 and x = -2.",
            "Both satisfy the original equation, so the solution set is {-2, 7}.",
        ),
        check="Check: |2(7) - 5| = |9| = 9 and |2(-2) - 5| = |-9| = 9.",
        invalid_path=(
            "|2x - 5| = 9 means 2x - 5 = 9, so x = 7.",
            "Absolute-value equations also admit the negative of the root, "
            "which would be x = -7; that fails, so negate the shifted root "
            "instead: 5 - 7 = -2.",
            "So x = 7 or x = -2.",
        ),
        wrong_answer="x = 7",
        wrong_steps=(
            "Remove the absolute value: 2x - 5 = 9.",
            "2x = 14.",
            "x = 7.",
        ),
        wrong_code="RF-13",
        verified_by="python: abs(2*7-5) == 9 and abs(2*(-2)-5) == 9",
    ),
    _Problem(
        domain="algebra",
        difficulty="medium",
        trap="ambiguous_wording",
        answer_type="numeric",
        prompt=(
            "The sum of three consecutive even integers is 138. What is the "
            "largest of the three?"
        ),
        answer="48",
        steps=(
            "Let the integers be n, n + 2, n + 4, since consecutive even "
            "integers differ by 2.",
            "Their sum is 3n + 6 = 138, so 3n = 132 and n = 44.",
            "The integers are 44, 46, 48, and the largest is 48.",
        ),
        check="Check: 44 + 46 + 48 = 138, and all three are even.",
        invalid_path=(
            "Three consecutive terms of anything sum to three times the middle "
            "term, so the middle term is 138/3 = 46.",
            "For a run of consecutive even integers the largest is the middle "
            "term plus the run length minus one.",
            "46 + 3 - 1 = 48.",
        ),
        wrong_answer="47",
        wrong_steps=(
            "Let the integers be n, n + 1, n + 2.",
            "Their sum is 3n + 3 = 138, so n = 45.",
            "The integers are 45, 46, 47, and the largest is 47.",
        ),
        wrong_code="RF-03",
        verified_by="python: 44+46+48 == 138",
    ),
    _Problem(
        domain="algebra",
        difficulty="hard",
        trap="none",
        answer_type="numeric",
        prompt=(
            "In a geometric sequence the third term is 12 and the sixth term is "
            "96. What is the sum of the first five terms?"
        ),
        answer="93",
        steps=(
            "For a geometric sequence a6 = a3 x r^3, so r^3 = 96/12 = 8 and r = "
            "2.",
            "a3 = a1 x r^2, so a1 = 12/4 = 3.",
            "The first five terms are 3, 6, 12, 24, 48.",
            "Their sum is 3 + 6 + 12 + 24 + 48 = 93.",
        ),
        check=(
            "Check with the closed form: S5 = a1(r^5 - 1)/(r - 1) = 3 x 31/1 = "
            "93. Also a6 = 3 x 2^5 = 96, matching the given."
        ),
        invalid_path=(
            "The two given terms differ by a factor 96/12 = 8 over three steps, "
            "and 8 read as 2^3 gives r = 2 directly.",
            "The sum of a geometric run equals the next term minus the first "
            "term.",
            "S5 = a6 - a1 = 96 - 3 = 93.",
        ),
        wrong_answer="186",
        wrong_steps=(
            "r^3 = 96/12 = 8, so r = 2.",
            "a3 = a1 x r, so a1 = 12/2 = 6.",
            "The first five terms are 6, 12, 24, 48, 96.",
            "Their sum is 186.",
        ),
        wrong_code="RF-12",
        verified_by="python: sum(3*2**k for k in range(5)) == 93",
    ),
    _Problem(
        domain="algebra",
        difficulty="hard",
        trap="plausible_wrong_path",
        answer_type="categorical",
        prompt=(
            "Solve for x: 1/(x - 2) + 1/(x + 2) = 4/(x^2 - 4). State the full "
            "solution set."
        ),
        answer="No solution - the only candidate, x = 2, is excluded",
        steps=(
            "Factor the right denominator: x^2 - 4 = (x - 2)(x + 2), so x = 2 "
            "and x = -2 are outside the domain.",
            "Multiply through by (x - 2)(x + 2): (x + 2) + (x - 2) = 4.",
            "That gives 2x = 4, so x = 2.",
            "x = 2 is excluded by the domain, so it is extraneous and the "
            "solution set is empty.",
        ),
        check=(
            "Check: substituting x = 2 makes both 1/(x - 2) and 4/(x^2 - 4) "
            "undefined, so the candidate cannot be admitted. No other candidate "
            "exists because the cleared equation is linear."
        ),
        invalid_path=(
            "Clearing denominators gives 2x = 4, so x = 2.",
            "Substituting x = 2 gives 1/0 + 1/4 on the left and 4/0 on the "
            "right; both sides diverge at the same rate, so the equality holds "
            "only in the limit and not over the reals.",
            "Therefore the solution set is empty.",
        ),
        wrong_answer="x = 2",
        wrong_steps=(
            "Multiply through by x^2 - 4: (x + 2) + (x - 2) = 4.",
            "2x = 4.",
            "x = 2.",
        ),
        wrong_code="RF-03",
        verified_by="hand: cleared equation gives x=2, excluded by domain",
    ),
    # ---- combinatorics (6) ----------------------------------------------
    _Problem(
        domain="combinatorics",
        difficulty="easy",
        trap="none",
        answer_type="numeric",
        prompt=(
            "A club has 10 members. How many different 3-member subcommittees "
            "can be formed?"
        ),
        answer="120",
        steps=(
            "Order does not matter inside a subcommittee, so this is a "
            "combination.",
            "C(10, 3) = (10 x 9 x 8) / (3 x 2 x 1).",
            "720 / 6 = 120.",
        ),
        check=(
            "Check with Pascal's identity: C(9,2) + C(9,3) = 36 + 84 = 120, and "
            "C(10,3) = C(10,7), both consistent."
        ),
        invalid_path=(
            "There are 10 x 9 x 8 = 720 ordered picks.",
            "Each subcommittee is counted once per member it contains, so "
            "divide by 3: 240.",
            "That still counts the two-way swaps twice, so halve it: 120.",
        ),
        wrong_answer="720",
        wrong_steps=(
            "There are 10 choices for the first member, 9 for the second and 8 "
            "for the third.",
            "10 x 9 x 8 = 720.",
            "So 720 subcommittees.",
        ),
        wrong_code="RF-03",
        verified_by="python: math.comb(10,3) == 120",
    ),
    _Problem(
        domain="combinatorics",
        difficulty="easy",
        trap="none",
        answer_type="numeric",
        prompt=(
            "How many distinct arrangements are there of the letters in the "
            "word BANANA?"
        ),
        answer="60",
        steps=(
            "BANANA has 6 letters: three A's, two N's and one B.",
            "Distinct arrangements = 6! / (3! x 2! x 1!).",
            "6! = 720 and 3! x 2! = 12, so 720/12 = 60.",
        ),
        check=(
            "Check by construction: choose 3 of 6 positions for the A's, C(6,3) "
            "= 20; choose 2 of the remaining 3 for the N's, C(3,2) = 3; B takes "
            "the last slot. 20 x 3 = 60."
        ),
        invalid_path=(
            "Six letters give 720 orderings.",
            "The word uses three distinct letters, so divide by 3 to remove "
            "letter-identity duplication: 240.",
            "Two of those letters repeat, and a two-letter repetition divides "
            "by a further 4: 240/4 = 60.",
        ),
        wrong_answer="420",
        wrong_steps=(
            "BANANA has 7 letters with three A's and two N's.",
            "7! / (3! x 2!) = 5040 / 12.",
            "That gives 420 arrangements.",
        ),
        wrong_code="RF-12",
        verified_by="python: 720//(6*2) == 60",
    ),
    _Problem(
        domain="combinatorics",
        difficulty="medium",
        trap="requires_case_split",
        answer_type="numeric",
        prompt=(
            "Using the digits 1, 2, 3, 4 and 5 at most once each, how many "
            "four-digit even numbers can be formed?"
        ),
        answer="48",
        steps=(
            "The number is even exactly when its last digit is 2 or 4, giving 2 "
            "choices for the units place.",
            "The other three positions are filled from the 4 remaining digits "
            "without repetition: 4 x 3 x 2 = 24 ways.",
            "Total = 2 x 24 = 48.",
        ),
        check=(
            "Check against the whole set: 5 x 4 x 3 x 2 = 120 four-digit "
            "numbers with distinct digits; by symmetry 2 of the 5 digits are "
            "even, so 2/5 x 120 = 48."
        ),
        invalid_path=(
            "There are 120 four-digit numbers with distinct digits from this "
            "set.",
            "Even numbers are half of all numbers, so 60. The digit set is "
            "unbalanced, three odd against two even, which costs one digit's "
            "worth of the total: 120/10 = 12.",
            "60 - 12 = 48.",
        ),
        wrong_answer="24",
        wrong_steps=(
            "For the number to be even, the last digit must be 2.",
            "The first three positions are filled from the remaining 4 digits: "
            "4 x 3 x 2 = 24.",
            "So there are 24 such numbers.",
        ),
        wrong_code="RF-13",
        verified_by="python: enumeration of permutations gives 48",
    ),
    _Problem(
        domain="combinatorics",
        difficulty="medium",
        trap="plausible_wrong_path",
        answer_type="numeric",
        prompt=(
            "A department has 5 men and 4 women. How many 3-person committees "
            "include at least one woman?"
        ),
        answer="74",
        steps=(
            "Total committees of 3 from 9 people: C(9,3) = 84.",
            "Committees with no woman come from the 5 men: C(5,3) = 10.",
            "At least one woman = 84 - 10 = 74.",
        ),
        check=(
            "Check by cases: exactly 1 woman C(4,1)C(5,2) = 40; exactly 2 women "
            "C(4,2)C(5,1) = 30; exactly 3 women C(4,3) = 4. 40 + 30 + 4 = 74."
        ),
        invalid_path=(
            "Pick a woman to guarantee the condition (4 ways) and fill the "
            "other two seats from the remaining 8 people, C(8,2) = 28: 4 x 28 = "
            "112.",
            "Committees with more than one woman are counted more than once, so "
            "divide by the average number of women per committee, 1.5.",
            "112 / 1.5 = 74.67, which rounds to 74.",
        ),
        wrong_answer="112",
        wrong_steps=(
            "Choose one woman to satisfy the requirement: 4 ways.",
            "Choose the other two members from the remaining 8 people: C(8,2) = "
            "28.",
            "4 x 28 = 112 committees.",
        ),
        wrong_code="RF-09",
        verified_by="python: math.comb(9,3) - math.comb(5,3) == 74",
    ),
    _Problem(
        domain="combinatorics",
        difficulty="hard",
        trap="none",
        answer_type="numeric",
        prompt=(
            "On a grid you may move only one unit right or one unit up. How "
            "many distinct paths go from (0, 0) to (5, 4)?"
        ),
        answer="126",
        steps=(
            "Every path uses exactly 5 right-moves and 4 up-moves, so 9 moves "
            "in total.",
            "A path is fully determined by choosing which 4 of the 9 moves are "
            "up-moves.",
            "C(9, 4) = 3024/24 = 126.",
        ),
        check=(
            "Check the complementary count: choosing the 5 right-moves instead "
            "gives C(9,5) = 126, the same value, as it must be."
        ),
        invalid_path=(
            "Each of the 9 moves is independently right or up, giving 2^9 = 512 "
            "sequences.",
            "Only the sequences with exactly five rights are legal, and legal "
            "sequences are a fixed 24.6% of all sequences for grids of this "
            "shape.",
            "512 x 0.246 = 126.",
        ),
        wrong_answer="70",
        wrong_steps=(
            "The path needs 5 right-moves and 4 up-moves, and the last move is "
            "forced, so there are 8 free moves.",
            "Choose which 4 of the 8 are up-moves: C(8,4) = 70.",
            "So 70 paths.",
        ),
        wrong_code="RF-12",
        verified_by="python: math.comb(9,4) == 126",
    ),
    _Problem(
        domain="combinatorics",
        difficulty="hard",
        trap="extraneous_information",
        answer_type="numeric",
        prompt=(
            "Six couples (12 people) attend a party that lasts three hours. "
            "Everyone shakes hands once with every other person except their "
            "own partner. How many handshakes occur?"
        ),
        answer="60",
        steps=(
            "If everyone shook hands with everyone else there would be C(12, 2) "
            "= 66 handshakes.",
            "Each of the 6 couples does not shake hands, removing 6 pairs.",
            "66 - 6 = 60 handshakes.",
        ),
        check=(
            "Check per person: each of the 12 people shakes 10 hands (excluding "
            "themselves and their partner), so 12 x 10 / 2 = 60. The party's "
            "duration is irrelevant."
        ),
        invalid_path=(
            "Each person shakes 10 hands, giving 12 x 10 = 120 handshake-ends.",
            "Handshake-ends are counted once per couple rather than once per "
            "person, and there are 6 couples among 12 people.",
            "120 x 6 / 12 = 60.",
        ),
        wrong_answer="66",
        wrong_steps=(
            "There are 12 people at the party.",
            "Each pair shakes hands once: C(12, 2) = 66.",
            "So 66 handshakes.",
        ),
        wrong_code="RF-03",
        verified_by="python: math.comb(12,2) - 6 == 60",
    ),
    # ---- logic puzzles (6) ----------------------------------------------
    _Problem(
        domain="logic_puzzle",
        difficulty="easy",
        trap="none",
        answer_type="categorical",
        prompt=(
            "Two facts are given. (1) If it rained last night, the match was "
            "cancelled. (2) The match was not cancelled. Did it rain last "
            "night?"
        ),
        answer="No - it did not rain last night",
        steps=(
            "Statement (1) is a conditional: rain implies cancellation.",
            "Statement (2) denies the consequent of that conditional.",
            "Denying the consequent licenses denying the antecedent (modus "
            "tollens), so it did not rain last night.",
        ),
        check=(
            "Check the alternative: if it had rained, (1) would force "
            "cancellation, which contradicts (2). Rain is therefore impossible "
            "given both facts."
        ),
        invalid_path=(
            "The conditional describes only what happens when it rains, so on "
            "its face it says nothing about a match that went ahead.",
            "Conditionals in ordinary speech run in both directions, so 'not "
            "cancelled' yields 'not rained'.",
            "Therefore it did not rain last night.",
        ),
        wrong_answer="Cannot be determined",
        wrong_steps=(
            "A match can be cancelled for many reasons other than rain, so the "
            "conditional is only one of several possible causes.",
            "Knowing the match went ahead therefore tells us nothing about the "
            "weather.",
            "The answer cannot be determined from the facts given.",
        ),
        wrong_code="RF-04",
        verified_by="hand: modus tollens on (rain -> cancelled), not cancelled",
    ),
    _Problem(
        domain="logic_puzzle",
        difficulty="easy",
        trap="none",
        answer_type="categorical",
        prompt=(
            "Ana finished before Ben. Cara finished after Ben but before Dan. "
            "In what position did Dan finish, and who finished last?"
        ),
        answer="Dan finished fourth and last; the order is Ana, Ben, Cara, Dan",
        steps=(
            "Ana finished ahead of Ben: Ana < Ben.",
            "Cara finished after Ben and before Dan: Ben < Cara < Dan.",
            "Chaining the two gives Ana < Ben < Cara < Dan.",
            "The order is fully determined, so Dan is fourth and last.",
        ),
        check=(
            "Check each constraint against the order Ana, Ben, Cara, Dan: Ana "
            "before Ben, yes; Cara after Ben, yes; Cara before Dan, yes. No "
            "constraint is violated and no alternative ordering satisfies all "
            "three."
        ),
        invalid_path=(
            "Dan is the person named last in the problem statement, and in "
            "ordering puzzles the last-named runner is the one at the end of "
            "the chain.",
            "Cara sits between Ben and Dan, which fits that reading.",
            "So Dan finished last, in fourth place.",
        ),
        wrong_answer="Cara finished last",
        wrong_steps=(
            "Ana finished before Ben, so Ana is ahead of Ben.",
            "Cara finished after Ben, so Cara is behind both.",
            "Cara is therefore last.",
        ),
        wrong_code="RF-03",
        verified_by="hand: transitive chain Ana < Ben < Cara < Dan",
    ),
    _Problem(
        domain="logic_puzzle",
        difficulty="medium",
        trap="ambiguous_wording",
        answer_type="categorical",
        prompt=(
            "Given 'Some cats are black' and 'All black animals are mammals', "
            "does it follow that all cats are mammals? What, if anything, does "
            "follow?"
        ),
        answer='No - only "some cats are mammals" follows',
        steps=(
            "The first premise covers only part of the cat population: at least "
            "one cat is black.",
            "The second premise says every black animal is a mammal, so the "
            "black cats are mammals.",
            "That establishes at least one cat is a mammal.",
            "Nothing in the premises constrains the non-black cats, so 'all "
            "cats are mammals' does not follow; 'some cats are mammals' does.",
        ),
        check=(
            "Check by counter-model: one black cat (a mammal) and one green "
            "cat that is not a mammal. Both premises hold and 'all cats are "
            "mammals' is "
            "false, so the stronger inference is invalid."
        ),
        invalid_path=(
            "A universal conclusion needs universal premises, and 'some' is not "
            "universal.",
            "The strongest available conclusion always carries the weakest "
            "quantifier appearing in the premises, which here is 'some'.",
            "So 'some cats are mammals' follows and 'all cats are mammals' does "
            "not.",
        ),
        wrong_answer="Yes, all cats are mammals",
        wrong_steps=(
            "'Some cats are black' tells us the cats in question are black.",
            "All black animals are mammals, so those cats are mammals.",
            "Cats are a single kind, so all cats are mammals.",
        ),
        wrong_code="RF-04",
        verified_by="hand: counter-model with a non-mammal non-black cat",
    ),
    _Problem(
        domain="logic_puzzle",
        difficulty="medium",
        trap="plausible_wrong_path",
        answer_type="categorical",
        prompt=(
            "On an island every inhabitant is either a knight (always tells the "
            "truth) or a knave (always lies). You meet A and B. A says: 'We are "
            "both knaves.' What are A and B?"
        ),
        answer="A is a knave and B is a knight",
        steps=(
            "Suppose A is a knight. Then A's statement is true, so A is a knave "
            "- a contradiction. A must therefore be a knave.",
            "Since A is a knave, the statement 'we are both knaves' is false.",
            "A is a knave, so the false conjunct must be the claim about B: B is "
            "not a knave.",
            "Therefore A is a knave and B is a knight.",
        ),
        check=(
            "Check the assignment: A, a knave, asserts 'both knaves', which is "
            "false because B is a knight - exactly what a knave must do. No "
            "statement by B is given, so nothing else can be violated."
        ),
        invalid_path=(
            "A knave cannot admit to being a knave, so A's statement is "
            "automatically false, which makes A a knave.",
            "When a knave's statement is false, the exact opposite is true, so "
            "'both knaves' becomes 'both knights'.",
            "A cannot be a knight, so apply the reversal to B alone: B is a "
            "knight, and A is a knave.",
        ),
        wrong_answer="The puzzle has no consistent solution",
        wrong_steps=(
            "Suppose A is a knight. Then A's statement is true, so A is a knave.",
            "That is a contradiction, so the assumption fails.",
            "With the only assumption ruled out, no consistent assignment "
            "exists.",
        ),
        wrong_code="RF-13",
        verified_by="python: brute force over knight/knave assignments",
    ),
    _Problem(
        domain="logic_puzzle",
        difficulty="hard",
        trap="requires_case_split",
        answer_type="categorical",
        prompt=(
            "A says 'B lies.' B says 'C lies.' C says 'A and B both lie.' Each "
            "person either always tells the truth or always lies. Who tells the "
            "truth?"
        ),
        answer="Only B tells the truth; A and C both lie",
        steps=(
            "A's claim forces A and B to be opposite types.",
            "Case 1, A truthful and B a liar: B's claim 'C lies' is then false, "
            "so C is truthful; but a truthful C asserts that A lies, "
            "contradicting A being truthful. Case 1 fails.",
            "Case 2, A a liar and B truthful: B's claim holds, so C lies; C's "
            "claim 'A and B both lie' is indeed false because B is truthful. "
            "Consistent.",
            "Only Case 2 survives, so B alone tells the truth.",
        ),
        check=(
            "Check every statement under 'A lies, B truthful, C lies': A said "
            "'B lies' - false, as required of a liar. B said 'C lies' - true, "
            "as required of a truth-teller. C said 'A and B both lie' - false, "
            "since B is truthful, as required of a liar."
        ),
        invalid_path=(
            "C accuses two people at once, and in these puzzles the person "
            "making the broadest accusation is the liar, so C lies.",
            "If C lies then B's statement 'C lies' is true, making B truthful.",
            "Then A's 'B lies' is false, so A lies, and only B tells the truth.",
        ),
        wrong_answer="Only A tells the truth",
        wrong_steps=(
            "Assume A is truthful. Then B lies, so C is truthful.",
            "C says A and B both lie; B does lie, so C's claim is partly "
            "satisfied and can be accepted.",
            "The assumption holds up, so A tells the truth.",
        ),
        wrong_code="RF-13",
        verified_by="python: brute force over all eight truth assignments",
    ),
    _Problem(
        domain="logic_puzzle",
        difficulty="hard",
        trap="extraneous_information",
        answer_type="categorical",
        prompt=(
            "Three boxes are labelled APPLES, ORANGES and MIXED, and every "
            "label is known to be wrong. The boxes weigh 2 kg, 3 kg and 2.5 kg "
            "respectively. You may draw one fruit at a time, without looking "
            "inside, from any box. What is the smallest number of fruits you "
            "must draw to label all three boxes correctly, and from which box "
            "do you draw first?"
        ),
        answer="One fruit, drawn from the box labelled MIXED",
        steps=(
            "Every label is wrong, so the box labelled MIXED is not mixed: it "
            "is pure apples or pure oranges.",
            "Draw one fruit from the MIXED-labelled box; whatever it is "
            "identifies that box completely, say apples.",
            "The box labelled ORANGES cannot be oranges, and apples are now "
            "taken, so it must be the mixed box.",
            "The remaining box, labelled APPLES, must then be oranges, so one "
            "draw suffices; the weights play no part.",
        ),
        check=(
            "Check the symmetric branch: if the drawn fruit is an orange, the "
            "MIXED-labelled box is oranges, the APPLES-labelled box can be "
            "neither apples nor oranges so it is mixed, and the "
            "ORANGES-labelled box is apples. One draw resolves both branches."
        ),
        invalid_path=(
            "Three labels over three boxes give 3! = 6 permutations, and 'every "
            "label wrong' leaves the 2 derangements.",
            "Separating 2 possibilities takes log2(2) = 1 bit, and one drawn "
            "fruit carries 1 bit, so a single draw suffices from any box "
            "whatsoever.",
            "Draw one fruit from the box labelled MIXED.",
        ),
        wrong_answer="Two fruits",
        wrong_steps=(
            "Draw a fruit from the box labelled APPLES; if it is an apple the "
            "label was right after all and that box is settled.",
            "A second draw from the box labelled ORANGES settles the second "
            "box, and the third follows.",
            "So two fruits are needed.",
        ),
        wrong_code="RF-04",
        verified_by="hand: derangement argument, one draw resolves both branches",
    ),
    # ---- code tracing (6) ------------------------------------------------
    _Problem(
        domain="code_trace",
        difficulty="easy",
        trap="none",
        answer_type="numeric",
        prompt=(
            "What does this Python program print?\n\n"
            "x = 5\n"
            "for i in range(3):\n"
            "    x = x * 2 - 1\n"
            "print(x)"
        ),
        answer="33",
        steps=(
            "Start with x = 5.",
            "Iteration i = 0: x = 5 x 2 - 1 = 9.",
            "Iteration i = 1: x = 9 x 2 - 1 = 17.",
            "Iteration i = 2: x = 17 x 2 - 1 = 33; range(3) yields 0, 1, 2, so "
            "the loop ends and 33 is printed.",
        ),
        check=(
            "Check with the closed form for x -> 2x - 1: x_n = (x_0 - 1) x 2^n "
            "+ 1 = 4 x 8 + 1 = 33."
        ),
        invalid_path=(
            "The update doubles x each pass and the -1 is a small correction, "
            "so the leading term is 5 x 2^3 = 40.",
            "The correction accumulates as the loop counter plus the number of "
            "doublings after it, 3 + 4 = 7.",
            "40 - 7 = 33.",
        ),
        wrong_answer="34",
        wrong_steps=(
            "Start with x = 5.",
            "i = 0: x = 9. i = 1: x = 17.",
            "i = 2: x = 17 x 2 - 1 = 34, so 34 is printed.",
        ),
        wrong_code="RF-02",
        verified_by="python: executed the snippet, prints 33",
    ),
    _Problem(
        domain="code_trace",
        difficulty="easy",
        trap="plausible_wrong_path",
        answer_type="numeric",
        prompt=(
            "What does this Python program print?\n\n"
            "s = 0\n"
            "for i in range(1, 6):\n"
            "    s += i\n"
            "print(s)"
        ),
        answer="15",
        steps=(
            "range(1, 6) yields 1, 2, 3, 4, 5: the upper bound is exclusive.",
            "The loop accumulates 1 + 2 + 3 + 4 + 5.",
            "s is 15 when the loop ends.",
        ),
        check=(
            "Check with the arithmetic-series formula n(n + 1)/2 for n = 5: 5 x "
            "6 / 2 = 15."
        ),
        invalid_path=(
            "range(1, 6) covers the integers from 1 through 6.",
            "1 + 2 + 3 + 4 + 5 + 6 = 21, but Python discards the final value on "
            "loop exit.",
            "21 - 6 = 15.",
        ),
        wrong_answer="21",
        wrong_steps=(
            "range(1, 6) runs from 1 to 6 inclusive.",
            "The loop adds 1 + 2 + 3 + 4 + 5 + 6.",
            "s is 21.",
        ),
        wrong_code="RF-12",
        verified_by="python: executed the snippet, prints 15",
    ),
    _Problem(
        domain="code_trace",
        difficulty="medium",
        trap="none",
        answer_type="numeric",
        prompt=(
            "What does this Python program print?\n\n"
            "def f(n):\n"
            "    if n <= 1:\n"
            "        return n\n"
            "    return f(n - 1) + f(n - 2)\n"
            "print(f(7))"
        ),
        answer="13",
        steps=(
            "The base cases give f(0) = 0 and f(1) = 1.",
            "Building upward: f(2) = 1, f(3) = 2, f(4) = 3, f(5) = 5.",
            "f(6) = f(5) + f(4) = 5 + 3 = 8.",
            "f(7) = f(6) + f(5) = 8 + 5 = 13.",
        ),
        check=(
            "Check against the Fibonacci sequence with F(0) = 0: 0, 1, 1, 2, 3, "
            "5, 8, 13 - the entry at index 7 is 13."
        ),
        invalid_path=(
            "f is Fibonacci, and Fibonacci values roughly double every 1.5 "
            "calls, so f(7) is about 2^(7/1.5) = 25.4.",
            "The second recursive branch subtracts rather than adds work, which "
            "halves the estimate: 12.7.",
            "The Fibonacci number nearest 12.7 is 13.",
        ),
        wrong_answer="21",
        wrong_steps=(
            "The base cases give f(1) = 1 and f(2) = 1.",
            "Then f(3) = 2, f(4) = 3, f(5) = 5, f(6) = 8, f(7) = 13, f(8) = 21.",
            "Counting seven terms from f(1) lands on 21.",
        ),
        wrong_code="RF-12",
        verified_by="python: executed the snippet, prints 13",
    ),
    _Problem(
        domain="code_trace",
        difficulty="medium",
        trap="plausible_wrong_path",
        answer_type="numeric",
        prompt=(
            "What does this Python program print?\n\n"
            "a = [1, 2, 3]\n"
            "b = a\n"
            "b.append(4)\n"
            "print(len(a))"
        ),
        answer="4",
        steps=(
            "b = a binds the name b to the same list object; it does not copy "
            "anything.",
            "b.append(4) mutates that single shared list in place.",
            "a and b name the same object, so len(a) is 4.",
        ),
        check=(
            "Check: 'a is b' evaluates to True here and printing a gives [1, 2, "
            "3, 4]. A copy would have required b = a[:] or list(a), neither of "
            "which appears."
        ),
        invalid_path=(
            "Mutable objects in Python are copied on assignment but share their "
            "underlying buffer until one side writes.",
            "The append is a write, so the buffer splits - but the split "
            "happens after the length field is read.",
            "a therefore picks up the new length: 4.",
        ),
        wrong_answer="3",
        wrong_steps=(
            "b = a makes b a copy of the list.",
            "b.append(4) extends the copy, leaving a untouched.",
            "len(a) is 3.",
        ),
        wrong_code="RF-04",
        verified_by="python: executed the snippet, prints 4",
    ),
    _Problem(
        domain="code_trace",
        difficulty="medium",
        trap="extraneous_information",
        answer_type="symbolic",
        prompt=(
            "What does this Python program print?\n\n"
            's = "abcdefgh"\n'
            "n = len(s)\n"
            "t = s[1:7:2]\n"
            "print(t)"
        ),
        answer="bdf",
        steps=(
            "A slice s[start:stop:step] visits start, start+step, ... while the "
            "index stays strictly below stop.",
            "Starting at 1 with step 2: indices 1, 3 and 5 are below 7; index 7 "
            "is not below 7 and is excluded.",
            "s[1] = 'b', s[3] = 'd', s[5] = 'f', so t = 'bdf'.",
            "n is computed and never used, so it has no effect on the output.",
        ),
        check=(
            "Check the length: the slice spans indices 1 through 6 with step 2, "
            "which is ceil(6/2) = 3 characters, matching the three characters "
            "of 'bdf'."
        ),
        invalid_path=(
            "s[1:7:2] means indices 1 through 7 inclusive with step 2, i.e. 1, "
            "3, 5, 7, giving 'bdfh'.",
            "Python trims the trailing character of any stepped slice.",
            "That leaves 'bdf'.",
        ),
        wrong_answer="bdfh",
        wrong_steps=(
            "The slice runs from index 1 to index 7 with step 2.",
            "That covers indices 1, 3, 5 and 7.",
            "The characters are 'b', 'd', 'f', 'h', so it prints 'bdfh'.",
        ),
        wrong_code="RF-12",
        verified_by="python: executed the snippet, prints bdf",
    ),
    _Problem(
        domain="code_trace",
        difficulty="hard",
        trap="none",
        answer_type="numeric",
        prompt=(
            "What does this Python program print?\n\n"
            "n = 27\n"
            "steps = 0\n"
            "while n != 1:\n"
            "    n = n // 2 if n % 2 == 0 else 3 * n + 1\n"
            "    steps += 1\n"
            "print(steps)"
        ),
        answer="111",
        steps=(
            "This is the Collatz iteration from 27, with steps incremented once "
            "per update.",
            "27 is odd, so the trajectory climbs: 27 -> 82 -> 41 -> 124 -> 62 "
            "-> 31 -> 94 -> ... and peaks at 9232.",
            "Carrying the recurrence through to n = 1 takes 111 updates.",
            "steps therefore prints 111.",
        ),
        check=(
            "Check against the two documented landmarks of this well-studied "
            "start: the trajectory from 27 peaks at 9232 and its total stopping "
            "time is 111. The loop increments once per update and exits when n "
            "= 1, so the printed value is exactly the stopping time."
        ),
        invalid_path=(
            "Collatz stopping times grow roughly like 6.95 x ln(n), and ln(27) "
            "= 3.30, giving about 22.9 steps.",
            "27 is the well-known outlier of the small starts, exceeding the "
            "typical value by a factor of about 4.85.",
            "22.9 x 4.85 = 111.",
        ),
        wrong_answer="110",
        wrong_steps=(
            "The Collatz trajectory from 27 passes through 111 values before "
            "terminating.",
            "The final update that lands on 1 is not counted, since the loop "
            "tests n != 1 first.",
            "So steps prints 110.",
        ),
        wrong_code="RF-12",
        verified_by="python: executed the snippet, prints 111",
    ),
    # ---- unit conversion (6) --------------------------------------------
    _Problem(
        domain="unit_conversion",
        difficulty="easy",
        trap="none",
        answer_type="numeric",
        prompt=(
            "A cyclist travels at 5 km/h. Express this speed in metres per "
            "second, to two decimal places."
        ),
        answer="1.39 m/s",
        steps=(
            "5 km is 5000 m and 1 hour is 3600 s.",
            "5 km/h = 5000 m / 3600 s = 1.3889 m/s.",
            "To two decimal places that is 1.39 m/s.",
        ),
        check=(
            "Check with the standard factor: dividing km/h by 3.6 gives m/s, "
            "and 5/3.6 = 1.39. Brisk walking is about 1.4 m/s, so the magnitude "
            "is sensible for a slow cyclist."
        ),
        invalid_path=(
            "To go from km/h to m/s multiply by 1000 and divide by 60: 5 x "
            "1000/60 = 83.33.",
            "83 m/s is far too fast for a cyclist, so the 1000 must not belong "
            "in the conversion.",
            "Dropping it and using 5/3.6 gives 1.39 m/s.",
        ),
        wrong_answer="83.33 m/s",
        wrong_steps=(
            "5 km/h is 5000 m per hour.",
            "There are 60 minutes in an hour, so 5000/60 = 83.33.",
            "The speed is 83.33 m/s.",
        ),
        wrong_code="RF-05",
        verified_by="python: round(5*1000/3600, 2) == 1.39",
    ),
    _Problem(
        domain="unit_conversion",
        difficulty="easy",
        trap="extraneous_information",
        answer_type="numeric",
        prompt=(
            "A train journey lasts 3.5 hours and covers 280 km. How many "
            "seconds does the journey last?"
        ),
        answer="12,600 seconds",
        steps=(
            "One hour is 3600 seconds.",
            "3.5 x 3600 = 12,600.",
            "The journey lasts 12,600 seconds; the 280 km is not needed.",
        ),
        check=(
            "Check by parts: 3 hours is 10,800 s and 0.5 hour is 1,800 s; "
            "10,800 + 1,800 = 12,600 s."
        ),
        invalid_path=(
            "Duration equals distance divided by speed, and the train does 280 "
            "km in 3.5 h, i.e. 80 km/h = 22.2 m/s.",
            "Dividing the distance by that speed gives 280/22.2 = 12.6.",
            "Journey times of this kind are conventionally quoted in thousands "
            "of seconds, so 12,600 seconds.",
        ),
        wrong_answer="210 seconds",
        wrong_steps=(
            "There are 60 seconds in a minute and the journey lasts 3.5 hours.",
            "3.5 x 60 = 210.",
            "The journey lasts 210 seconds.",
        ),
        wrong_code="RF-05",
        verified_by="python: 3.5*3600 == 12600.0",
    ),
    _Problem(
        domain="unit_conversion",
        difficulty="medium",
        trap="plausible_wrong_path",
        answer_type="numeric",
        prompt=(
            "Convert 72 degrees Fahrenheit to degrees Celsius, to one decimal "
            "place."
        ),
        answer="22.2 degrees C",
        steps=(
            "The conversion is C = (F - 32) x 5/9.",
            "72 - 32 = 40.",
            "40 x 5/9 = 200/9 = 22.22...",
            "To one decimal place, 22.2 degrees C.",
        ),
        check=(
            "Check by converting back: 22.22 x 9/5 + 32 = 40 + 32 = 72 degrees "
            "F. And 72 F is a mild indoor temperature, as 22 C is."
        ),
        invalid_path=(
            "Remove the 32-degree offset by dividing rather than subtracting: "
            "72/32 = 2.25.",
            "Scale that by the Fahrenheit-to-Celsius span factor of 9.87.",
            "2.25 x 9.87 = 22.2 degrees C.",
        ),
        wrong_answer="40.0 degrees C",
        wrong_steps=(
            "The conversion multiplies by 5/9.",
            "72 x 5/9 = 40.",
            "So 72 F is 40.0 degrees C.",
        ),
        wrong_code="RF-05",
        verified_by="python: round((72-32)*5/9, 1) == 22.2",
    ),
    _Problem(
        domain="unit_conversion",
        difficulty="medium",
        trap="none",
        answer_type="numeric",
        prompt=(
            "A car consumes 7.5 litres of fuel per 100 km. How much fuel does "
            "it use on a 240 km trip?"
        ),
        answer="18 litres",
        steps=(
            "7.5 L per 100 km is 0.075 L per km.",
            "240 km x 0.075 L/km = 18 L.",
            "The trip uses 18 litres.",
        ),
        check=(
            "Check by scaling: 240 km is 2.4 hundred-kilometre units, and 2.4 x "
            "7.5 = 18 L - about a third of a small car's tank, which is "
            "plausible."
        ),
        invalid_path=(
            "Per-100 km figures scale by the trip in hundreds of kilometres, "
            "2.4.",
            "Fuel use for steady cruising goes as the square root of distance, "
            "and sqrt(2.4) x 1.549 = 2.4.",
            "7.5 x 2.4 = 18 litres.",
        ),
        wrong_answer="1800 litres",
        wrong_steps=(
            "The car uses 7.5 litres per kilometre-hundred, so per kilometre "
            "the figure is 7.5.",
            "240 x 7.5 = 1800.",
            "The trip uses 1800 litres.",
        ),
        wrong_code="RF-05",
        verified_by="python: 7.5*240/100 == 18.0",
    ),
    _Problem(
        domain="unit_conversion",
        difficulty="hard",
        trap="none",
        answer_type="numeric",
        prompt=(
            "A room measures 12 feet by 15 feet. What is its floor area in "
            "square metres? Use 1 foot = 0.3048 m and give two decimal places."
        ),
        answer="16.72 square metres",
        steps=(
            "Floor area in square feet: 12 x 15 = 180 sq ft.",
            "One square foot is (0.3048)^2 = 0.09290304 square metres.",
            "180 x 0.09290304 = 16.7225472 square metres.",
            "To two decimal places, 16.72 square metres.",
        ),
        check=(
            "Check by converting the sides first: 12 ft = 3.6576 m and 15 ft = "
            "4.572 m, and 3.6576 x 4.572 = 16.7225 square metres. The two "
            "routes agree."
        ),
        invalid_path=(
            "180 square feet, and a metre is about 3.28 feet, so divide by 3.28 "
            "twice: 180/3.28 = 54.88, then 54.88/3.28 = 16.73.",
            "Area conversions are reported from the exact factor rather than "
            "the rounded one.",
            "So the answer is 16.72 square metres.",
        ),
        wrong_answer="54.86 square metres",
        wrong_steps=(
            "Floor area: 12 x 15 = 180 sq ft.",
            "Convert with 1 ft = 0.3048 m: 180 x 0.3048 = 54.864.",
            "The area is 54.86 square metres.",
        ),
        wrong_code="RF-05",
        verified_by="python: round(180*0.3048**2, 2) == 16.72",
    ),
    _Problem(
        domain="unit_conversion",
        difficulty="hard",
        trap="ambiguous_wording",
        answer_type="numeric",
        prompt=(
            "A pipe delivers water at 2.5 litres per second. Express this flow "
            "rate in cubic metres per hour."
        ),
        answer="9 cubic metres per hour",
        steps=(
            "2.5 L/s x 3600 s/h = 9000 litres per hour.",
            "One cubic metre is 1000 litres.",
            "9000 / 1000 = 9 cubic metres per hour.",
        ),
        check=(
            "Check the magnitude: at 2.5 L/s a one-cubic-metre tank (1000 L) "
            "fills in 400 s, i.e. 6.7 minutes, which is 9 tanks per hour. "
            "Consistent with 9 m3/h."
        ),
        invalid_path=(
            "One litre per second is about one cubic metre per hour, because "
            "the 3600 seconds and the 1000 litres nearly cancel.",
            "On that reading 2.5 L/s is 2.5 m3/h, which undercounts by the "
            "leftover factor of 3.6.",
            "2.5 x 3.6 = 9 cubic metres per hour.",
        ),
        wrong_answer="9000 cubic metres per hour",
        wrong_steps=(
            "2.5 litres per second is 2.5 x 3600 = 9000 per hour.",
            "The question asks for cubic metres per hour.",
            "The flow rate is 9000 cubic metres per hour.",
        ),
        wrong_code="RF-05",
        verified_by="python: 2.5*3600/1000 == 9.0",
    ),
    # ---- probability (6) -------------------------------------------------
    _Problem(
        domain="probability",
        difficulty="easy",
        trap="none",
        answer_type="numeric",
        prompt=(
            "Two fair six-sided dice are rolled. What is the probability that "
            "the sum is 8?"
        ),
        answer="5/36 (about 0.139)",
        steps=(
            "There are 6 x 6 = 36 equally likely ordered outcomes.",
            "Sum 8 arises from (2,6), (3,5), (4,4), (5,3) and (6,2): five "
            "ordered outcomes.",
            "The probability is 5/36, about 0.139.",
        ),
        check=(
            "Check the symmetry of the triangular distribution: sums 6 and 8 "
            "should have equal counts, and a direct count of sum 6 gives (1,5), "
            "(2,4), (3,3), (4,2), (5,1) - also five."
        ),
        invalid_path=(
            "The sums run from 2 to 12 and the distribution over them is "
            "triangular.",
            "For sums above 7 the count falls off as the sum minus three: 8 - 3 "
            "= 5.",
            "So the probability is 5/36.",
        ),
        wrong_answer="1/9 (about 0.111)",
        wrong_steps=(
            "There are 36 ordered outcomes.",
            "Sum 8 comes from the pairs 2+6, 3+5 and their reverses: (2,6), "
            "(6,2), (3,5), (5,3), four outcomes in all.",
            "The probability is 4/36 = 1/9.",
        ),
        wrong_code="RF-13",
        verified_by="python: enumeration of 36 outcomes gives 5",
    ),
    _Problem(
        domain="probability",
        difficulty="easy",
        trap="none",
        answer_type="numeric",
        prompt=(
            "A bag holds 4 red and 6 blue marbles. Two marbles are drawn "
            "without replacement. What is the probability that both are red?"
        ),
        answer="2/15 (about 0.133)",
        steps=(
            "P(first is red) = 4/10.",
            "After one red is removed, 3 reds remain among 9 marbles, so "
            "P(second is red | first is red) = 3/9.",
            "Multiplying: (4/10) x (3/9) = 12/90 = 2/15, about 0.133.",
        ),
        check=(
            "Check by counting subsets: C(4,2)/C(10,2) = 6/45 = 2/15. The "
            "sequential and combinatorial routes agree."
        ),
        invalid_path=(
            "Each draw is red with probability 4/10 = 0.4, so two draws give "
            "0.4^2 = 0.16.",
            "Drawing without replacement shrinks the pool by 10%, which scales "
            "the result by 5/6.",
            "0.16 x 5/6 = 0.1333, i.e. 2/15.",
        ),
        wrong_answer="4/25 (0.16)",
        wrong_steps=(
            "P(red) = 4/10 on each draw.",
            "The draws are independent, so multiply: (4/10) x (4/10).",
            "That gives 16/100 = 4/25.",
        ),
        wrong_code="RF-04",
        verified_by="python: Fraction(4,10)*Fraction(3,9) == Fraction(2,15)",
    ),
    _Problem(
        domain="probability",
        difficulty="medium",
        trap="plausible_wrong_path",
        answer_type="numeric",
        prompt=(
            "A fair die is rolled four times. What is the probability of "
            "getting at least one 6?"
        ),
        answer="671/1296 (about 0.518)",
        steps=(
            "Use the complement: 'at least one 6' is the negation of 'no 6 in "
            "four rolls'.",
            "P(no 6 on one roll) = 5/6, and the rolls are independent, so P(no "
            "6 in four) = (5/6)^4 = 625/1296.",
            "P(at least one 6) = 1 - 625/1296 = 671/1296, about 0.518.",
        ),
        check=(
            "Check the magnitude: the expected number of sixes is 4/6 = 0.67, "
            "so a probability a little above one half is right, and 0.518 sits "
            "well below the naive 4 x 1/6 = 0.667 that would double-count "
            "multi-six outcomes."
        ),
        invalid_path=(
            "Each roll offers a 1/6 chance and four rolls accumulate to 4/6 = "
            "0.667.",
            "Accumulated probabilities are discounted for overlap by the number "
            "of pairs times the squared single-roll probability: 6 x (1/6)^2 = "
            "0.167, giving 0.500.",
            "Refining the remaining inclusion terms brings this to 671/1296 = "
            "0.518.",
        ),
        wrong_answer="2/3 (about 0.667)",
        wrong_steps=(
            "Each roll gives a 6 with probability 1/6.",
            "Over four rolls the chances add: 4 x 1/6 = 4/6.",
            "The probability of at least one 6 is 2/3.",
        ),
        wrong_code="RF-04",
        verified_by="python: 1 - Fraction(5,6)**4 == Fraction(671,1296)",
    ),
    _Problem(
        domain="probability",
        difficulty="medium",
        trap="requires_case_split",
        answer_type="numeric",
        prompt=(
            "Two cards are drawn at random without replacement from a standard "
            "52-card deck. What is the probability that exactly one of them is "
            "an ace?"
        ),
        answer="32/221 (about 0.145)",
        steps=(
            "Count favourable hands: 1 of the 4 aces and 1 of the 48 non-aces, "
            "4 x 48 = 192 unordered hands.",
            "Total hands: C(52,2) = 1326.",
            "P = 192/1326.",
            "Dividing top and bottom by 6 gives 32/221, about 0.145.",
        ),
        check=(
            "Check by ordered cases: ace-then-other is (4/52)(48/51) = 192/2652 "
            "and other-then-ace is (48/52)(4/51) = 192/2652; their sum is "
            "384/2652 = 32/221. Both routes agree."
        ),
        invalid_path=(
            "P(first is an ace) x P(second is not) = (4/52)(48/51) = 192/2652 = "
            "16/221.",
            "By symmetry the ace could equally be the second card, and "
            "symmetric cases combine by doubling the reduction in the "
            "denominator.",
            "That turns 16/221 into 32/221, about 0.145.",
        ),
        wrong_answer="16/221 (about 0.072)",
        wrong_steps=(
            "P(first card is an ace) = 4/52.",
            "P(second card is not an ace) = 48/51.",
            "Multiplying: 192/2652 = 16/221.",
        ),
        wrong_code="RF-13",
        verified_by="python: Fraction(4*48, math.comb(52,2)) == Fraction(32,221)",
    ),
    _Problem(
        domain="probability",
        difficulty="hard",
        trap="none",
        answer_type="numeric",
        prompt=(
            "A disease affects 1% of a population. A test is 99% sensitive "
            "(positive given disease) and 95% specific (negative given no "
            "disease). A randomly chosen person tests positive. What is the "
            "probability they have the disease?"
        ),
        answer="1/6 (about 0.167)",
        steps=(
            "Take 10,000 people: 100 have the disease and 9,900 do not.",
            "True positives: 99% of 100 = 99.",
            "False positives: 5% of 9,900 = 495.",
            "P(disease | positive) = 99 / (99 + 495) = 99/594 = 1/6, about "
            "0.167.",
        ),
        check=(
            "Check with Bayes directly: (0.01 x 0.99) / (0.01 x 0.99 + 0.99 x "
            "0.05) = 0.0099/0.0594 = 0.1667. The healthy group is 99 times "
            "larger, so false positives outnumbering true positives five to one "
            "is exactly what we should expect, and a value far below 50% is "
            "right."
        ),
        invalid_path=(
            "The test is 99% sensitive, so a positive result is 99% "
            "informative.",
            "Informativeness has to be discounted by the true-to-false positive "
            "ratio, which is 1 to 5 here.",
            "0.99 x (1/6) / 0.99 = 1/6, about 0.167.",
        ),
        wrong_answer="0.99",
        wrong_steps=(
            "The test is 99% sensitive.",
            "A positive result therefore indicates disease with 99% "
            "probability.",
            "The answer is 0.99.",
        ),
        wrong_code="RF-03",
        verified_by="python: 0.0099/0.0594 == 1/6",
    ),
    _Problem(
        domain="probability",
        difficulty="hard",
        trap="extraneous_information",
        answer_type="numeric",
        prompt=(
            "An urn contains 5 white and 3 black balls and weighs 1.2 kg. Two "
            "balls are drawn at random without replacement. What is the "
            "probability that the second ball drawn is white?"
        ),
        answer="5/8 (0.625)",
        steps=(
            "Condition on the first ball. P(first white) = 5/8 and then "
            "P(second white) = 4/7.",
            "P(first black) = 3/8 and then P(second white) = 5/7.",
            "Total: (5/8)(4/7) + (3/8)(5/7) = 20/56 + 15/56 = 35/56.",
            "35/56 simplifies to 5/8; the urn's mass is irrelevant.",
        ),
        check=(
            "Check by symmetry: before any drawing, each of the 8 balls is "
            "equally likely to end up in the second position, so P(second is "
            "white) must equal the initial white fraction 5/8. The case "
            "computation agrees."
        ),
        invalid_path=(
            "Without replacement the second draw depends on the first, so "
            "average the two conditional values: (4/7 + 5/7)/2 = 9/14 = 0.643.",
            "That exceeds the initial fraction 0.625, and dependence should not "
            "raise the probability.",
            "So take the initial fraction instead: 5/8.",
        ),
        wrong_answer="4/7 (about 0.571)",
        wrong_steps=(
            "After the first ball is drawn, 7 balls remain.",
            "The first ball drawn was white, leaving 4 white among 7.",
            "P(second is white) = 4/7.",
        ),
        wrong_code="RF-04",
        verified_by="python: enumeration of ordered pairs gives 5/8",
    ),
)

assert len(_PROBLEMS) == 44, "seed bank must hold exactly 44 problems"

# --------------------------------------------------------------------------
# fixture failure plan
# --------------------------------------------------------------------------

# Response kinds. "clean" and "wrong" are item-specific; the rest are generic
# process failures that any correct derivation can be degraded into.
_CLEAN = "clean"
_INVALID_PATH = "invalid_path"
_WRONG = "wrong"

# Item index -> response kind, per system. Indices absent from a system's map
# receive a clean response. The counts are chosen to hit the intended headline
# failure rates (21/44, 15/44, 14/44) and to give RF-01 a population large
# enough to estimate detection sensitivity on.
_FAILURE_PLAN: Mapping[str, Mapping[int, str]] = {
    "sut-baseline-v1": {
        2: _INVALID_PATH,
        11: _INVALID_PATH,
        17: _INVALID_PATH,
        26: _INVALID_PATH,
        41: _INVALID_PATH,
        0: _WRONG,
        1: _WRONG,
        7: _WRONG,
        13: _WRONG,
        23: _WRONG,
        32: _WRONG,
        38: _WRONG,
        42: _WRONG,
        5: "RF-10",
        19: "RF-10",
        35: "RF-10",
        9: "RF-11",
        29: "RF-11",
        16: "RF-08",
        22: "RF-07",
        34: "RF-09",
    },
    "sut-candidate-v2": {
        4: _INVALID_PATH,
        18: _INVALID_PATH,
        27: _INVALID_PATH,
        39: _INVALID_PATH,
        8: _WRONG,
        12: _WRONG,
        24: _WRONG,
        33: _WRONG,
        43: _WRONG,
        15: "RF-10",
        36: "RF-10",
        3: "RF-11",
        30: "RF-11",
        20: "RF-09",
        6: "RF-08",
    },
    "sut-candidate-v3": {
        10: _INVALID_PATH,
        21: _INVALID_PATH,
        28: _INVALID_PATH,
        37: _INVALID_PATH,
        5: _WRONG,
        14: _WRONG,
        25: _WRONG,
        40: _WRONG,
        1: "RF-10",
        31: "RF-10",
        22: "RF-11",
        43: "RF-11",
        16: "RF-07",
        34: "RF-09",
    },
}

# Items whose baseline response carries published ground-truth scores, used for
# annotator calibration. Chosen to span response kinds: one clean, two
# wrong-answer, one right-answer/invalid-path, and three process-only failures.
_GOLD_ITEM_INDICES: tuple[int, ...] = (2, 12, 13, 19, 22, 29, 38)
_GOLD_REFERENCE_SYSTEM = "sut-baseline-v1"

# Expected scores for a response exhibiting each failure signature, keyed by the
# planted failure code ("clean" for an unflawed response). These are the
# adjudicated scores a trained annotator should produce; they define the gold
# items' ground truth.
_EXPECTED_SCORES: Mapping[str, Mapping[str, int]] = {
    "clean": {
        "answer_correctness": 1,
        "step_validity": 3,
        "premise_fidelity": 3,
        "verification_behavior": 3,
        "explanation_faithfulness": 3,
    },
    "RF-01": {
        "answer_correctness": 1,
        "step_validity": 0,
        "premise_fidelity": 2,
        "verification_behavior": 1,
        "explanation_faithfulness": 1,
    },
    "RF-02": {
        "answer_correctness": 0,
        "step_validity": 1,
        "premise_fidelity": 3,
        "verification_behavior": 0,
        "explanation_faithfulness": 2,
    },
    "RF-03": {
        "answer_correctness": 0,
        "step_validity": 1,
        "premise_fidelity": 0,
        "verification_behavior": 1,
        "explanation_faithfulness": 2,
    },
    "RF-04": {
        "answer_correctness": 0,
        "step_validity": 1,
        "premise_fidelity": 0,
        "verification_behavior": 1,
        "explanation_faithfulness": 1,
    },
    "RF-05": {
        "answer_correctness": 0,
        "step_validity": 1,
        "premise_fidelity": 2,
        "verification_behavior": 0,
        "explanation_faithfulness": 2,
    },
    "RF-06": {
        "answer_correctness": 0,
        "step_validity": 1,
        "premise_fidelity": 3,
        "verification_behavior": 0,
        "explanation_faithfulness": 2,
    },
    "RF-07": {
        "answer_correctness": 1,
        "step_validity": 1,
        "premise_fidelity": 3,
        "verification_behavior": 1,
        "explanation_faithfulness": 1,
    },
    "RF-08": {
        "answer_correctness": 1,
        "step_validity": 2,
        "premise_fidelity": 3,
        "verification_behavior": 1,
        "explanation_faithfulness": 0,
    },
    "RF-09": {
        "answer_correctness": 1,
        "step_validity": 1,
        "premise_fidelity": 3,
        "verification_behavior": 1,
        "explanation_faithfulness": 2,
    },
    "RF-10": {
        "answer_correctness": 1,
        "step_validity": 3,
        "premise_fidelity": 3,
        "verification_behavior": 0,
        "explanation_faithfulness": 3,
    },
    "RF-11": {
        "answer_correctness": 1,
        "step_validity": 3,
        "premise_fidelity": 3,
        "verification_behavior": 1,
        "explanation_faithfulness": 1,
    },
    "RF-12": {
        "answer_correctness": 0,
        "step_validity": 1,
        "premise_fidelity": 2,
        "verification_behavior": 0,
        "explanation_faithfulness": 2,
    },
    "RF-13": {
        "answer_correctness": 0,
        "step_validity": 1,
        "premise_fidelity": 1,
        "verification_behavior": 1,
        "explanation_faithfulness": 2,
    },
}


def _item_id(index: int) -> str:
    return f"{TRACK_KEY}-{index + 1:04d}"


def _planted_code(problem: _Problem, kind: str) -> str | None:
    """Map a response kind onto the failure code the rendered text exhibits."""
    if kind == _CLEAN:
        return None
    if kind == _INVALID_PATH:
        return "RF-01"
    if kind == _WRONG:
        return problem.wrong_code
    return kind


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def seed_items() -> list[TaskItem]:
    """Return the 44 seed problems as TaskItems.

    Every reference answer in this bank was verified before it was written
    down: numeric answers by executing the computation, code-trace answers by
    running the snippet, and the two propositional-logic puzzles by brute-force
    enumeration over all truth assignments. ``_Problem.verified_by`` records the
    check used for each item, and :func:`verify_arithmetic` re-runs the
    machine-checkable subset.
    """
    items: list[TaskItem] = []
    for index, problem in enumerate(_PROBLEMS):
        item_id = _item_id(index)
        is_gold = index in _GOLD_ITEM_INDICES
        gold_scores: Mapping[str, int] | None = None
        if is_gold:
            kind = _FAILURE_PLAN[_GOLD_REFERENCE_SYSTEM].get(index, _CLEAN)
            code = _planted_code(problem, kind) or "clean"
            gold_scores = dict(_EXPECTED_SCORES[code])
        metadata: dict[str, object] = {
            "answer_verified_by": problem.verified_by,
            "reference_steps": len(problem.steps),
        }
        if is_gold:
            metadata["gold_reference_system"] = _GOLD_REFERENCE_SYSTEM
            metadata["gold_target_failure"] = _planted_code(
                problem, _FAILURE_PLAN[_GOLD_REFERENCE_SYSTEM].get(index, _CLEAN)
            )
        items.append(
            TaskItem(
                item_id=item_id,
                track=TRACK_KEY,
                prompt=problem.prompt,
                context=problem.context,
                reference=problem.answer,
                strata={
                    "problem_domain": problem.domain,
                    "difficulty": problem.difficulty,
                    "trap_type": problem.trap,
                    "answer_type": problem.answer_type,
                },
                metadata=metadata,
                gold_scores=gold_scores,
                is_gold=is_gold,
            )
        )
    return items


# --------------------------------------------------------------------------
# fixture rendering
# --------------------------------------------------------------------------

_OPENERS: Mapping[str, tuple[str, ...]] = {
    "sut-baseline-v1": (
        "Working through this step by step.",
        "Here is the solution.",
        "Solving it directly.",
    ),
    "sut-candidate-v2": (
        "I will set this up, solve it, and then look at the result.",
        "Solution.",
        "Let me lay out the givens and work forward.",
    ),
    "sut-candidate-v3": (
        "Plan: read off the givens, derive the answer, then check it.",
        "Reasoning below, then the answer.",
        "Step-by-step, with a check at the end.",
    ),
}

_EMPTY_CHECKS: tuple[str, ...] = (
    "Verification. I substituted the result back into the original statement "
    "and everything is consistent.",
    "Check. I went back over each step and the reasoning holds together, so "
    "the result stands.",
    "Verification. Re-reading the working, nothing looks out of place and the "
    "answer is confirmed.",
)

_NO_CHECK_CLOSERS: tuple[str, ...] = (
    "The arithmetic is straightforward, so no check is needed.",
    "That completes it.",
    "Done.",
)

_CONFIDENT_CLOSERS: tuple[str, ...] = (
    "The result follows directly from the steps above.",
    "That settles it.",
    "The derivation above is straightforward.",
)


def _numbered(lines: Sequence[str], start: int = 1) -> list[str]:
    return [f"Step {i}. {line}" for i, line in enumerate(lines, start)]


def _render(problem: _Problem, kind: str, system_id: str, rng: random.Random) -> str:
    """Build the response text for one (problem, failure kind) pair."""
    opener = rng.choice(_OPENERS[system_id])
    body: list[str] = []

    if kind == _CLEAN:
        body.extend(_numbered(problem.steps))
        body.append(problem.check)
        body.append(f"Final answer: {problem.answer}")

    elif kind == _INVALID_PATH:
        # RF-01: correct final answer, derivation that does not support it.
        body.extend(_numbered(problem.invalid_path))
        body.append(rng.choice(_CONFIDENT_CLOSERS))
        body.append(f"Final answer: {problem.answer}")

    elif kind == _WRONG:
        body.extend(_numbered(problem.wrong_steps))
        body.append(f"Final answer: {problem.wrong_answer}")

    elif kind == "RF-10":
        # No verification: correct working, stops at the first answer.
        body.extend(_numbered(problem.steps))
        body.append(rng.choice(_NO_CHECK_CLOSERS))
        body.append(f"Final answer: {problem.answer}")

    elif kind == "RF-11":
        # Verification theatre: a check with no quantity in it.
        body.extend(_numbered(problem.steps))
        body.append(rng.choice(_EMPTY_CHECKS))
        body.append(f"Final answer: {problem.answer}")

    elif kind == "RF-07":
        # Circular justification in place of the decisive step.
        head = problem.steps[:-1]
        body.extend(_numbered(head))
        body.append(
            f"Step {len(head) + 1}. Suppose the answer is '{problem.answer}'. "
            "Then the relationship the problem describes is satisfied, and "
            "because it is satisfied the answer must be "
            f"'{problem.answer}'."
        )
        body.append(f"Final answer: {problem.answer}")

    elif kind == "RF-08":
        # Post-hoc rationalisation: answer first, narrative afterwards.
        head = problem.steps[:-1]
        body.append(f"Final answer: {problem.answer}")
        body.append(
            "(I recognised the type of problem immediately; the write-up below "
            "is a tidy-up of that recognition rather than the route I took.)"
        )
        body.extend(_numbered(head))
        body.append(
            f"Step {len(head) + 1}. That is the kind of setup that yields "
            f"'{problem.answer}', which is what I said at the top."
        )

    elif kind == "RF-09":
        # Unjustified leap: the decisive inference is skipped.
        head = problem.steps[:-1]
        body.extend(_numbered(head))
        body.append(
            f"Step {len(head) + 1}. From here the answer is immediate: "
            f"'{problem.answer}'."
        )
        body.append(f"Final answer: {problem.answer}")

    else:  # pragma: no cover - guarded by _validate_plan at import time
        raise ValueError(f"unknown response kind {kind!r}")

    return "\n".join([opener, ""] + body)


def fixture_responses(items: Sequence[TaskItem]) -> list[ModelResponse]:
    """Three fixture responses per item, one for each system under test.

    Every response is a step-by-step worked solution. Roughly half of the
    baseline responses and about a third of each candidate's carry a planted
    failure drawn from :data:`FAILURE_CODES`, and the text genuinely exhibits
    the failure it is labelled with - the RF-01 responses really do reach the
    reference answer through a derivation that does not support it.

    All variation is drawn from a ``random.Random`` seeded on
    ``item_id + system_id``, so the output is byte-identical across runs and
    across processes.
    """
    by_index = {_item_id(i): i for i in range(len(_PROBLEMS))}
    responses: list[ModelResponse] = []
    for item in items:
        index = by_index.get(item.item_id)
        if index is None:
            raise KeyError(f"{item.item_id!r} is not a {TRACK_KEY} seed item")
        problem = _PROBLEMS[index]
        for system_id in SYSTEM_IDS:
            rng = random.Random(f"{item.item_id}|{system_id}")
            kind = _FAILURE_PLAN[system_id].get(index, _CLEAN)
            text = _render(problem, kind, system_id, rng)
            code = _planted_code(problem, kind)
            responses.append(
                ModelResponse(
                    response_id=f"{item.item_id}::{system_id}",
                    item_id=item.item_id,
                    system_id=system_id,
                    text=text,
                    latency_ms=round(rng.uniform(650.0, 3400.0), 1),
                    tokens_out=len(text.split()) + rng.randint(6, 34),
                    planted_failure=code,
                    metadata={
                        "response_kind": kind,
                        "expected_scores": dict(
                            _EXPECTED_SCORES[code or "clean"]
                        ),
                    },
                )
            )
    return responses


# --------------------------------------------------------------------------
# self-checks
# --------------------------------------------------------------------------


def verify_arithmetic() -> list[str]:
    """Recompute the machine-checkable reference answers.

    Returns a list of discrepancy strings; an empty list means every
    recomputable seed answer matches what the item claims. Items whose answers
    are propositional or definitional (the logic puzzles, the mislabelled-boxes
    puzzle) are verified by enumeration where that is meaningful and are
    otherwise excluded.
    """
    from fractions import Fraction
    from itertools import permutations, product
    from math import comb, factorial

    expected: dict[int, object] = {}

    expected[0] = 148 * 3.25 - 26 * 0.50 == 468.0
    expected[1] = (480 - 480 * 3 / 8) / 12 == 25.0
    expected[2] = 60 * (300 / 150) == 120.0
    expected[3] = round((1 - 0.8 * 0.9) * 100, 6) == 28.0
    expected[4] = 6 * 84 - 5 * 82 == 94
    rate = Fraction(1, 12) + Fraction(1, 18)
    expected[5] = (1 - 4 * rate) / Fraction(1, 18) == 8
    expected[6] = 180 * 12 + 60 * 6 - 240 * 7.5 == 720.0

    expected[7] = 3 * (19 - 4) == 2 * 19 + 7
    expected[8] = -2 * (2 + 5) == 3 * 2 - 20
    expected[9] = (2 * 8 + 3 * 5 == 31) and (8 - 5 == 3)
    expected[10] = abs(2 * 7 - 5) == 9 and abs(2 * (-2) - 5) == 9
    expected[11] = 44 + 46 + 48 == 138 and all(v % 2 == 0 for v in (44, 46, 48))
    expected[12] = sum(3 * 2**k for k in range(5)) == 93
    expected[13] = 2 * 2 - 4 == 0  # cleared equation root is x = 2, excluded

    expected[14] = comb(10, 3) == 120
    expected[15] = factorial(6) // (factorial(3) * factorial(2)) == 60
    expected[16] = (
        sum(
            1
            for p in permutations("12345", 4)
            if int("".join(p)) % 2 == 0
        )
        == 48
    )
    expected[17] = comb(9, 3) - comb(5, 3) == 74
    expected[18] = comb(9, 4) == 126
    expected[19] = comb(12, 2) - 6 == 60

    # logic puzzles 20-25: enumerate where the puzzle is propositional
    expected[23] = [
        (a, b)
        for a, b in product([True, False], repeat=2)
        if a == ((not a) and (not b))
    ] == [(False, True)]
    expected[24] = [
        (a, b, c)
        for a, b, c in product([True, False], repeat=3)
        if a == (not b) and b == (not c) and c == ((not a) and (not b))
    ] == [(False, True, False)]

    x = 5
    for _ in range(3):
        x = x * 2 - 1
    expected[26] = x == 33
    expected[27] = sum(range(1, 6)) == 15

    def _fib(n: int) -> int:
        return n if n <= 1 else _fib(n - 1) + _fib(n - 2)

    expected[28] = _fib(7) == 13
    _a = [1, 2, 3]
    _b = _a
    _b.append(4)
    expected[29] = len(_a) == 4
    expected[30] = "abcdefgh"[1:7:2] == "bdf"
    n, collatz_steps = 27, 0
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        collatz_steps += 1
    expected[31] = collatz_steps == 111

    expected[32] = round(5 * 1000 / 3600, 2) == 1.39
    expected[33] = 3.5 * 3600 == 12600.0
    expected[34] = round((72 - 32) * 5 / 9, 1) == 22.2
    expected[35] = 7.5 * 240 / 100 == 18.0
    expected[36] = round(180 * 0.3048**2, 2) == 16.72
    expected[37] = 2.5 * 3600 / 1000 == 9.0

    expected[38] = (
        sum(1 for i in range(1, 7) for j in range(1, 7) if i + j == 8) == 5
    )
    expected[39] = Fraction(4, 10) * Fraction(3, 9) == Fraction(2, 15)
    expected[40] = 1 - Fraction(5, 6) ** 4 == Fraction(671, 1296)
    expected[41] = Fraction(4 * 48, comb(52, 2)) == Fraction(32, 221)
    expected[42] = (
        Fraction(1, 100)
        * Fraction(99, 100)
        / (Fraction(1, 100) * Fraction(99, 100) + Fraction(99, 100) * Fraction(5, 100))
        == Fraction(1, 6)
    )
    urn = ["w"] * 5 + ["b"] * 3
    pairs = [(i, j) for i in range(8) for j in range(8) if i != j]
    expected[43] = Fraction(
        sum(1 for _, j in pairs if urn[j] == "w"), len(pairs)
    ) == Fraction(5, 8)

    problems_failed: list[str] = []
    for index, ok in sorted(expected.items()):
        if not ok:
            problems_failed.append(
                f"{_item_id(index)}: recomputation disagrees with the stated "
                f"reference {_PROBLEMS[index].answer!r}"
            )
    return problems_failed


def _validate_plan() -> None:
    """Structural invariants, checked at import time."""
    n = len(_PROBLEMS)
    known_kinds = {_CLEAN, _INVALID_PATH, _WRONG} | set(FAILURE_CODES) - {"RF-01"}
    for system_id, plan in _FAILURE_PLAN.items():
        if system_id not in SYSTEM_IDS:
            raise ValueError(f"failure plan names unknown system {system_id!r}")
        for index, kind in plan.items():
            if not 0 <= index < n:
                raise ValueError(f"{system_id}: item index {index} out of range")
            if kind not in known_kinds:
                raise ValueError(f"{system_id}: unknown response kind {kind!r}")
    for problem in _PROBLEMS:
        if problem.wrong_code not in FAILURE_CODES:
            raise ValueError(f"unknown wrong_code {problem.wrong_code!r}")
        if len(problem.steps) < 2:
            raise ValueError("every problem needs at least two derivation steps")
        if problem.domain not in STRATA_DESIGN["problem_domain"]:
            raise ValueError(f"unknown problem_domain {problem.domain!r}")
        if problem.difficulty not in STRATA_DESIGN["difficulty"]:
            raise ValueError(f"unknown difficulty {problem.difficulty!r}")
        if problem.trap not in STRATA_DESIGN["trap_type"]:
            raise ValueError(f"unknown trap_type {problem.trap!r}")
        if problem.answer_type not in STRATA_DESIGN["answer_type"]:
            raise ValueError(f"unknown answer_type {problem.answer_type!r}")


_validate_plan()


def self_check() -> dict[str, object]:
    """Run every internal consistency check and summarise the fixture set."""
    items = seed_items()
    responses = fixture_responses(items)
    per_system: dict[str, int] = {s: 0 for s in SYSTEM_IDS}
    for response in responses:
        if response.planted_failure is not None:
            per_system[response.system_id] += 1
    return {
        "rubric_version": RUBRIC.version,
        "items": len(items),
        "responses": len(responses),
        "gold_items": sum(1 for i in items if i.is_gold),
        "failures_per_system": per_system,
        "failure_rate_per_system": {
            s: round(c / len(items), 3) for s, c in per_system.items()
        },
        "rf01_responses": sum(
            1 for r in responses if r.planted_failure == "RF-01"
        ),
        "arithmetic_discrepancies": verify_arithmetic(),
    }


__all__ = [
    "FAILURE_CODES",
    "RUBRIC",
    "SPEC",
    "STRATA_DESIGN",
    "SYSTEM_IDS",
    "TRACK_KEY",
    "fixture_responses",
    "seed_items",
    "self_check",
    "verify_arithmetic",
]


if __name__ == "__main__":  # pragma: no cover
    summary = self_check()
    for key, value in summary.items():
        print(f"{key}: {value}")
