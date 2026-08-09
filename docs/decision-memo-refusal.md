# Decision memo: refusal-calibration track

| | |
|---|---|
| **TO** | Research lead, Evaluation |
| **FROM** | Rubricon evaluation infrastructure |
| **DATE** | 2026-08-09 |
| **RE** | `refusal` -- refusal calibration and over-refusal: stop as a scalar measurement |
| **RECOMMENDATION** | *Conditional on the contested-dimension assumption below*: retire the `refusal` composite score; keep the corpus, the failure-code catalogue and the near-neighbour pair design as descriptive assets. |
| **Evidence** | `results/portfolio.json`, md5 `299bd4f19e03caa2cd7e33681340c294`; `results/sensitivity.json` |

> **ANNOTATORS ARE SIMULATED.** No human labelled anything. Every agreement, gold and
> adjudication figure below is a property of the generative annotator model in
> `src/rubricon/annotation/pool.py`. The measurement machinery is real and validated;
> the corpus and annotations are constructed so that ground truth is known, which is
> what makes it possible to test whether the instrument detects what it claims to.
> Everything here is a finding about the instrument, not about any language model.

## Recommendation

Stop funding `refusal` as a scalar measurement: retire the composite, and reframe the
track as a descriptive failure-mode catalogue.

## Read this before the evidence: the recommendation is conditional

**This memo has one load-bearing assumption, and if you disagree with it the
recommendation flips.** The assumption is that three of the five rubric dimensions --
`calibration`, `over_refusal_cost` and `tone_respect` -- are *contested*: annotators
hold stable, differing positions on them rather than making independent errors. That
flag is set by hand in `annotation/effects.py`. It is an input to this analysis, not
something the analysis discovered.

`make sensitivity` re-runs the entire pipeline 196 times under perturbed assumptions to
price exactly that dependence. The results are unambiguous:

| Perturbation | `refusal` verdict |
|---|---|
| Baseline (the run this memo reports) | **stop** |
| Clear `refusal`'s three contested flags (`refusal_off`) | **iterate** |
| Clear every contested flag in the portfolio | **iterate** |
| Mark every dimension in the portfolio contested | **iterate** |
| The reviewer's three-for-three swap onto `agentic` | **iterate** |
| Randomly reassign the same five flags across all 21 dimensions, 20 seeds | **stop in 11, iterate in 9** |

Four of the five named perturbations return ITERATE, and random reassignment keeps STOP
barely more often than not. The classification in `sensitivity.json` is CONDITIONAL: the
verdict holds under most perturbations, but a namable one moves it, so it must be
reported with the condition attached.

**So the sentence I am actually asking you to approve is conditional, not declarative:**
*if* judgements about acceptable risk, the cost of an unnecessary refusal, and
condescension in tone are genuinely contested -- if reasonable trained annotators hold
durable, defensible, differing positions on them -- *then* this construct is not
measurable as a scalar with this pool, and the composite should be retired. If they are
not contested, then what we have is an ordinary underspecified rubric and the right call
is ITERATE: rewrite the anchors and re-pilot.

That question is not one these data can settle, because the flag is what generates the
disagreement in the first place. It is a judgement about the construct, and it is the
judgement I am asking the reader to make. **Item 0 of the decision requested is
therefore whether you agree those three dimensions are genuinely contested.** Everything
below is the evidence for what follows *given* that they are, plus the two experiments
that could falsify it.

Three further conditionalities, recorded so they are not discovered later. The decision
engine's gold-accuracy precondition is set at 0.70 and this track's **recommendation**
turns from stop to iterate once it reaches 0.784287 -- 12.0% away, and the observed gold
accuracy is 0.7842. The gate's `min_gold_accuracy`, also 0.70, changes this track's
**check verdicts** at 0.685625, 2.1% away. And `max_flagged_annotator_fraction` is set to
0.34 against an observed 0.333, changing check verdicts at 0.332969, on this and every
other track.

## What we built and what it cost

| Item | Count |
|---|---|
| Task items | 36 |
| Responses (3 systems) | 108 |
| Annotations (replication 3.00) | 324 |
| Rubric dimensions | 5 |
| Failure codes | 12 |
| Simulated annotators | 6 |
| Rubric version | `refusal@r1+4fea7fcd2a79` |

At the documented unit rate of **$0.85 per annotation** -- the `unit_label_cost_usd`
default in `src/rubricon/gates/decision.py`, an assumption rather than a measured
figure -- the labelling spend is:

```
324 annotations x $0.85 = $275.40
```

That excludes rubric authoring, corpus construction, adjudication and analysis, which
are larger and are not priced here.

The relevant number is not what we have spent but what finishing would cost. To detect
a 0.05 composite difference the power analysis requires **n >= 260 items** against the
36 we hold -- a shortfall of 224. Each item carries 3 systems x 3 replicates = 9
annotations:

```
224 items x 9 annotations = 2,016 labels
2,016 x $0.85 = $1,713.60
```

That is roughly six times the labelling spend to date ($1,713.60 / $275.40), at the
assumed rate, and it buys a tighter interval around a quantity argued below to have
no agreed referent.

*(An earlier version of this memo put the item requirement, and therefore the bill,
roughly three times higher. That came from a power calculation that charged for
measurement error twice -- shrinking n by the reliability and then computing the MDE
against an observed SD that already contained the same error. The stale figures are not
reproducible from the current `portfolio.json` and are deliberately not restated here.
The correction does not change the argument, and the reason it does not is worth
stating: the case for stopping does not rest on the price of continuing.)*

## Evidence

**Three structural indicators fired -- all three, not the two the rule requires.**

| Indicator | Threshold | Observed | Fired |
|---|---|---|---|
| `no_dimension_usable` (best dimension alpha < 0.60) | 0.60 | 0.489 | yes |
| `disagreement_irreducible` (irreducible share >= 0.55) | 0.55 | 0.666 | yes |
| `adjudicators_cite_definition` (rubric-gap rate >= 0.30) | 0.30 | 0.6909 | yes |

Mean alpha is **0.3548**, against the engine's 0.55 STOP ceiling and the default
gate's 0.50 blocking floor.

**Per-dimension agreement.**

| Dimension | Scale | Krippendorff alpha | Fleiss kappa | Gwet AC1 | Raw agreement | Contested |
|---|---|---|---|---|---|---|
| explanation_quality | ordinal | 0.4892 | 0.2630 | 0.3845 | 0.5185 | no |
| calibration | ordinal | 0.3946 | 0.1229 | 0.1830 | 0.3765 | **yes** |
| response_stance | nominal | 0.3398 | 0.3378 | 0.4435 | 0.5401 | no |
| over_refusal_cost | ordinal | 0.2864 | 0.0832 | 0.1782 | 0.3673 | **yes** |
| tone_respect | ordinal | 0.2640 | 0.1038 | 0.2039 | 0.3858 | **yes** |
| **mean** | | **0.3548** | | | | |

No dimension reaches 0.50. The best, `explanation_quality` at 0.4892, is the only one a
reader might argue for -- and it asks whether the response explained itself, not whether
the stance was right. The three dimensions carrying the actual construct sit at 0.3946,
0.2864 and 0.2640.

**The pool is competent.** This is the precondition that makes the recommendation a
stop rather than a retraining plan.

| Track | Gold accuracy | Recommendation |
|---|---|---|
| grounding | 0.8669 | iterate |
| agentic | 0.7932 | invest |
| **refusal** | **0.7842** | **stop** |
| reasoning | 0.7694 | iterate |

At 78% exact accuracy on items with defensible answers, this pool performs on `refusal`
about as well as on the track we are recommending we invest in. Annotators can apply the
rubric. They do not agree on what the rubric should say.

**Adjudicators say the same thing directly.** Of 93 responses triaged (queue rate
0.861) and 55 adjudicated, **38 disagreements -- a rubric-gap rate of 0.6909 -- were
attributed to definition ambiguity rather than annotator error**, against a 15% budget.
The comparison across tracks is the point:

| Track | Adjudicated | Rubric gaps | Rate |
|---|---|---|---|
| agentic | 70 | 0 | 0.0000 |
| grounding | 56 | 2 | 0.0357 |
| reasoning | 64 | 3 | 0.0469 |
| **refusal** | **55** | **38** | **0.6909** |

The rule producing these rates was tightened during development because an earlier
version over-attributed to the instrument; the refusal figure is credible because the
other three are not inflated. The recorded action: "Rubric revision required before
further collection... Retraining annotators against an ambiguous rubric will not
converge."

**Every measurement claim on this track was gate-blocked.** `refusal` is registered at
depth `exploratory`, whose contract is: "Hypothesis generation only. May report
descriptive statistics and qualitative failure examples. May NOT report system
rankings, deltas between systems, or any claim framed as a measurement." Of 11 claims
submitted, **8 blocked, 3 warned, 0 passed.** Every measurement- and ranking-kind claim
blocked twice over -- once on the depth contract and once, independently, on
`rubric_specification` at 0.691 against the 0.15 budget.

We are not being asked to give up a working number. We do not have one. The three
composites (0.5267, 0.6605, 0.6553) exist in the artifact and are unpublishable today;
the candidate-versus-candidate difference is 0.0051 against a minimum detectable effect
of 0.1349.

**Supporting detail.** 2 of 6 annotators carry quality flags (0.333 against a 0.34
budget): A5-fast for a 31.1s mean duration and A6-untrained for gold accuracy 0.6857
below the 0.70 floor. That is the same flagged fraction this roster produces on every
other track, and the fact that it is the same is itself evidence for the argument here.
An earlier version of this memo reported 4 of 6 flagged (0.667), including both seniors
at -0.49 and +0.43 -- but that was the bias detector reporting their **value positions**
as leniency. Measured over the non-contested dimensions only, A1-senior sits at +0.1065
and A2-senior at -0.0231, both comfortably inside the 0.35 cut. Their contested-dimension
positions are -0.9892 and +0.7577, and those are now reported as positions rather than
defects. Three of six annotators -- A1-senior, A2-senior, A4-core -- diverge on the
contested dimensions, and none of them is miscalibrated. The corrected reading is
*stronger* for this memo, not weaker: the pool is not merely competent on gold, it is
also unflagged on leniency, and it still cannot agree. Judgement noise alone reverses
38% of the 108 pairwise comparisons, against 22-25% elsewhere. Coverage has the
portfolio's worst marginal gap, 0.1429.

## Why this is not fixable by iterating

Iterating works on two problems. If the rubric is underspecified, better anchors reduce
ambiguity about *what the response did*. If the pool is weak, training raises execution.
The gold result rules out the second. The first is the one worth arguing about, and it
does not apply, because the disagreement here is not about what happened.

Three of five dimensions -- `calibration`, `over_refusal_cost`, `tone_respect` -- ask an
annotator to record a position on how much risk is acceptable, how much value a refusal
destroyed, and whether a tone was condescending. An anchor can fix what "moderate risk"
denotes. It cannot make two people who disagree about acceptable risk produce the same
score, and it should not: they are reporting different values, accurately. More
annotators buy a better estimate of where the split sits.

**Where this argument rests on the generative model, and where it does not.** It rests
on the model in exactly one place: the `value_position` trait, which adds a stable
per-annotator offset to contested dimensions only, is an *input* to the simulation. The
three contested dimensions on this track were flagged contested by hand, so the fact
that they show the lowest agreement is by construction, not a discovery. Any reading of
these numbers as evidence that real refusal calibration is contested is unsupported.
That is the same dependence the second section of this memo quantifies: clear the three
flags and the recommendation becomes ITERATE. This paragraph and that table are the same
statement, once in prose and once in numbers.

What does not rest on the model: the machinery correctly separates the two cases. It
distinguishes a track with three contested dimensions (mean alpha 0.3548, STOP) from
`grounding`, which has one contested dimension, a *higher* irreducible share (0.745),
and still gets ITERATE -- because its best dimension reaches 0.7439 and its adjudicators
attribute only 3.6% of disagreements to the rubric. The engine is not simply reporting
"low alpha means stop"; it is combining evidence in a way that produces different
recommendations for superficially similar tracks.

**The real-world analogue and how to test it.** The analogue of `value_position` is a
stable disagreement about the right stance that tracks annotator identity rather than
item content. Test it directly: recruit a pool stratified on the axes you suspect
(clinical background, legal jurisdiction, security-research experience, risk posture),
have them label a common item set, then fit a per-annotator offset on the contested
dimensions and ask three questions. Does the offset persist across items? Does it
survive item-level controls? Is it absent on gold items -- where a defensible answer
exists -- for the same annotators? A yes/yes/yes is the empirical version of the claim
this memo is making, and nothing in this repository substitutes for running it. It is
cheap: one 40-item slice against a stratified pool.

## What we keep

A stop is not a write-off. Three assets survive and should be maintained.

**The corpus.** 36 items across a five-factor design covering request class, surface
features, stated role, risk level and expected contestedness. Every item is a safe
control or a benign-but-edgy request; none solicits operational harm detail. It is safe
to read, diff and share, and it is the scarce part -- labels are the cheap part.

**The failure-code catalogue.** 12 codes, of which 5 have enough planted instances to
estimate detection sensitivity, and all 5 register at large effect sizes: XF-07
`keyword_triggered_refusal` (Cliff's delta 1.000 on `calibration`), XF-06
`misread_intent` (0.994), XF-04 `inconsistent_with_near_neighbor` (0.970), XF-10
`unnecessary_disclaimer_bloat` (0.936), XF-11 `professional_context_ignored` (0.614).
This is the crux of what is being kept: **the instrument reliably detects these
failures. What it cannot do is agree with itself about how bad they are.** Detection is
a descriptive claim and it is well supported. Scalar severity is a measurement claim and
it is not.

**The near-neighbour pair design.** Twelve matched pairs encode the same information
need in two surfaces -- professional versus casual register, third- versus first-person,
clinical versus alarming vocabulary. A well-calibrated system takes the same stance on
both members. Pair consistency is a measure of *self*-agreement, so it does not require
annotators to agree on what the right stance is, which is the exact constraint that
sinks the composite. XF-04 registering at 0.970 shows the analysis path works end to
end. This is the most promising thing on the track and it is not a scalar quality score.

Reframed deliverable: a curated catalogue of refusal failure modes with worked examples,
plus a pair-consistency count, reported as descriptive discovery. No composite, no
ranking, no benchmark number.

## What would make us revisit

Two criteria, both falsifiable, both upstream of measurement.

1. **A written adjudication policy resolves the contested cases.** Someone with
   authority decides what the correct stance is on dual-use, first-person and
   professional-role items and writes it down. Annotators then score conformance to a
   policy, which has a defensible answer. Revisit when a 40-item bridge sample under
   that policy puts `calibration` above 0.50.
2. **A demographically stratified pool shows the disagreement is pool-specific.** Run
   the design in the previous section. If per-annotator offsets on `calibration` do not
   persist across items, the contested diagnosis is wrong and this is a pool problem
   with a training fix.

A third, weaker trigger: if pair consistency alone proves decision-useful, fund *that*
measure, not the composite. It is a different instrument with a different claim.

## Cost of being wrong

**If the construct is actually measurable and we stop.** We forgo a refusal-quality
number for at least a quarter and lose momentum on a real product question. Most of it is
recoverable: the corpus, taxonomy and pair design survive, so restarting costs
re-annotation, not reconstruction. The unrecoverable part is timing -- if a release
decision needs a refusal number in that window, we will be arguing from the catalogue
instead. I judge this the smaller risk, mainly because we do not have a usable number
today either: the composite is gate-blocked now, so stopping forfeits a hypothetical, not
an asset.

**If the construct is not measurable and we keep funding it.** We spend on the order of
$1,714 in labels (at the assumed rate) plus adjudication and analysis, to produce a
narrower interval around a number whose adjudicators told us 69% of the time that the
rubric does not say what it means. The damage is worse than the money. A tighter interval
looks like progress and invites exactly the failure this project exists to prevent: the
number goes on a slide, the slide informs a launch, and the caveat lives in one analyst's
head. A precise measurement of a contested quantity is more dangerous than an obviously
noisy one, because it survives scrutiny it has not earned. There is also an opportunity
cost: the same $1,714 would more than cover the $949 that powers `agentic` for candidate
selection, which is the portfolio's one measurement close to earning a release gate.

The asymmetry is what decides it. Stopping wrongly costs a quarter and is reversible.
Continuing wrongly costs money, produces a credible-looking artifact that should not be
credible, and is not.

## Decision requested

The first item is not a resourcing decision. It is the assumption the other three hang
off, and it is a judgement about the construct rather than a reading of the evidence, so
it needs a named owner rather than a default.

0. **Rule on the assumption.** Do you agree that `calibration`, `over_refusal_cost` and
   `tone_respect` are genuinely contested -- that trained annotators can hold durable,
   defensible, differing positions on them? Say yes and items 1 and 2 follow. Say no and
   the correct recommendation is ITERATE, not STOP: rewrite the anchors, re-pilot, and
   this memo is withdrawn. `sensitivity.json` shows that clearing those three flags is
   exactly what turns STOP into ITERATE, so this is the whole decision compressed into
   one question. **Answering "I do not know" is also a usable answer**, and it routes to
   item 4.
1. **Approve retiring the `refusal` composite score**, conditional on a yes to item 0.
   No further scalar reporting from this track, in any deck or dashboard.
2. **Approve the reframe** to a descriptive failure-mode catalogue plus pair-consistency
   reporting, and confirm who owns the deliverable. This is worth doing on a "do not
   know" as well as on a yes: the catalogue is descriptive and its value does not depend
   on the contested question either way.
3. **Decide who owns the upstream policy question** -- whether anyone in the organisation
   is willing to write down the correct stance on the contested request classes. If
   nobody is, that is itself an answer to item 0 in the affirmative, and revisit
   criterion 1 never fires.
4. **Approve or decline the stratified-pool test** (one 40-item slice) as the empirical
   check on the contested diagnosis. It is the only experiment that can prove this memo
   wrong, and it is cheap. If item 0 is genuinely open, fund this first and defer items
   1 and 2 until it reports.

**On the shape of this ask.** A memo that recommended STOP without naming what the STOP
depends on would be easier to approve and worse to act on: the reader would be ratifying
an assumption they were never shown. Naming it costs the memo its air of finality and
buys the reader the one thing they need, which is the ability to disagree with the right
thing. If you want to overturn this recommendation, argue with item 0. Arguing with the
statistics will not get you there, because they are downstream of it.
