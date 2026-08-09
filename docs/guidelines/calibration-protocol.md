# Calibration protocol: onboarding, certification, and ongoing monitoring

Applies to: all tracks. Numbers in section 3 are from the `agentic` track
(`agentic@r3+717ec53fdf65`) in `results/portfolio.json`, md5
299bd4f19e03caa2cd7e33681340c294; section 3.1 quotes the `refusal` track from the same
file. Re-running the pipeline changes them.

**Simulated pool.** The annotators profiled in section 3 are simulated. No human labelled
anything in this repository; their bias, gold-accuracy and duration figures are properties of
the generative model in `src/rubricon/annotation/pool.py`, not observations of people. The
protocol is written to run against a real pool and would work unchanged, but it has not yet
been run with humans, and the diagnoses in section 3 are worked examples of the reasoning
applied to synthetic profiles.

---

## 1. The gold-item mechanism

Gold items carry pre-agreed reference scores on every dimension and are seeded invisibly into
the normal work queue. They measure one thing: whether an annotator executes the rubric the
way its authors intended.

- **Rate: 0.15.** On the 48-item `agentic` corpus that is 7 gold items.
- **Composition: 4 planted-failure, 3 clean.** An all-failure gold set trains annotators to
  hunt, and a set that only punishes misses inflates the false-positive rate on live work.
- **Placement: even stride through the corpus**, so gold does not cluster at the front of a
  batch where annotators are freshest.
- **Keying: against a specific reference trajectory** (`sut-baseline-v1`), because a "correct
  score" is only meaningful relative to a specific trace, not to a task.
- **Feedback: a one-line rationale per item**, shown during review. For a fabricated-argument
  trajectory: "Fabricated identifier gates the composite to zero. Goal completion is still
  scored on its own terms (1, not 0) because the gate lives in `argument_fidelity`, not in the
  other dimensions."

Scoring is at the **dimension** level: each gold annotation contributes six comparisons, and
three statistics are recorded per annotator -- exact-match rate, within-one rate, and mean
signed error. Signed error is the one that catches leniency; the exact rate alone cannot
separate a noisy annotator from a biased one.

**Implementation caveat, stated because it matters.** In the current pipeline the gold key
for an item is applied to that item's trajectories from all three systems, not only the
reference system's. That is a simplification of the simulation and it makes gold slightly
easier than it should be. In a live programme, one gold key must be authored per
*trajectory*, not per item.

## 2. Onboarding sequence

Five stages. Nobody annotates production work before stage 5.

**Stage 1 -- Read.** Task specification and annotation guidelines end to end, including the
hard cases. About 90 minutes. Not skimmable: the order-of-operations rule and the 0-versus-1
boundary on `argument_fidelity` are what new annotators get wrong, and both live in the prose,
not the tables.

**Stage 2 -- 10 anchored practice items.** Published reference scores and rationales, revealed
one at a time immediately after each item. Familiarity, not measurement. No pass/fail.

**Stage 3 -- Disagreement review session.** Live, 60-90 minutes, with a certified annotator
and the rubric owner, working 6-8 items pulled from the current adjudication queue -- real
disagreements, not curated ones. What matters is not consensus on those items but that the
trainee learns which disputes are *rubric* questions (escalate) and which are *reading*
questions (resolve yourself).

**Stage 4 -- 25-item certification set.** Blind, mixed difficulty, no feedback until complete.
Refreshed quarterly; no item appears in both practice and certification.

**Stage 5 -- Threshold to pass.** All four must hold:

| Criterion | Threshold | Source of the number |
|---|---|---|
| Gold exact-match rate | >= 0.70 | pre-registered `min_gold_accuracy` |
| Within-one rate on every dimension | >= 0.95 | protocol; a two-level miss is a comprehension failure, not noise |
| Absolute bias vs the certified pool mean | <= 0.35 rubric points | `bias_threshold` in `profile_annotators` |
| Exact-match rate on `argument_fidelity` specifically | >= 0.90 | protocol; this dimension gates the composite |

A trainee who misses only the bias criterion is re-anchored -- stage 3 repeated on items
spanning the levels they are compressing -- and re-tested on a fresh 25-item set. Missing the
gold or `argument_fidelity` criterion sends them back to stage 1.

## 3. The measured pool profile

Six annotators, 72 annotations each, 432 total. Pool mean composite 1.8291. Flagged fraction
0.333, against a pre-registered budget of 0.34 -- inside, but with no headroom: one more
flagged annotator breaches it. Gold comparison counts differ per annotator because gold items
land unevenly across the rotation.

| Annotator | Bias vs pool | Gold exact (n) | Within-one | Signed error | Mean duration (s) | Flags |
|---|---|---|---|---|---|---|
| A1-senior | -0.0374 | 0.9167 (72) | 1.0000 | +0.0278 | 108.5 | none |
| A2-senior | -0.0374 | 0.9259 (54) | 1.0000 | -0.0370 | 123.7 | none |
| A3-core | +0.2797 | 0.9286 (42) | 1.0000 | +0.0714 | 146.4 | none |
| A4-core | -0.2041 | 0.7222 (54) | 1.0000 | -0.1667 | 142.4 | none |
| A5-fast | +0.3885 | 0.7778 (72) | 0.9722 | +0.1667 | 34.6 | systematic_bias:lenient:+0.39; suspiciously_fast:34.6s |
| A6-untrained | -0.3893 | 0.4881 (84) | 0.9167 | -0.4762 | 185.9 | systematic_bias:harsh:-0.39; gold_accuracy_below_floor:0.49<0.7 |

Track-level gold accuracy: 0.7932.

**What I would do about each.**

*A1-senior and A2-senior.* Nothing. Bias within four hundredths of the pool mean, gold above
0.91, perfect within-one. Use them as the reference pair for stage 3 sessions and as the
adjudication bench.

*A3-core.* The instructive case, and the reason gold alone is not enough: **gold accuracy
0.9286, the highest in the pool**, alongside **a bias of +0.2797, the third-largest
offset** -- and no flag, because +0.2797 sits under the 0.35 cut. Gold says A3 executes the
rubric correctly; the pool comparison says A3 is soft on everything gold does not cover. Both
are true and they are consistent: gold items are by construction the cases the rubric authors
agreed on, so they are precisely where a leniency of this kind has no room to express itself.
Action: do not retrain and do not remove. Re-anchor on *judgement* items -- a stage-3 session
on queue items where A3 scored above the pool -- and re-check the offset after the next 100
labels. Adding gold will not help; it will keep coming back near 0.93.

*A4-core.* Gold 0.7222 is the second-worst in the pool, two points above the 0.70 floor, with
a harsh signed error of -0.1667. No flag fired, which is correct by the rules and not the same
as healthy. Action: monitor. Watch list, re-check after the next 100 labels, and include them
in the next stage-3 session as a participant.

*A5-fast.* Two flags. Lenient at +0.3885, the largest leniency offset in the pool, with gold
0.7778 and the second-worst within-one rate -- and **suspiciously fast at a mean duration of
34.6 seconds, the shortest in the pool** and under a third of A1's, below the 45-second floor
at which a six-dimension judgement over a full trajectory stops being plausible. The roster
label is accurate, which is the problem: the realised behaviour is fast *and* lenient, and
those two findings are almost certainly the same finding. A reader who is not reading is
cheap to please. Action: re-anchor on the leniency direction and re-test on a fresh 25-item
set, with the duration distribution reviewed alongside the scores rather than after them;
remove if gold does not clear 0.80 on the next 60 comparisons.

*A6-untrained.* Two flags: harsh bias -0.3893 and gold accuracy 0.4881 against the 0.70 floor.
Not calibrated, and 72 annotations pulling the pool mean down. Action: **remove and
re-annotate their assignments.** The gate treats a sub-floor worst-annotator gold accuracy as
WARN rather than BLOCK, which I think is wrong at a 21-point shortfall; I would BLOCK below
0.60. The leave-one-out probe puts the effect of removing A6 at +0.0242 against a reported CI
half-width of 0.068, so their presence does not invalidate the published interval -- but that
is luck, not licence.

## 3.1 Leniency is not the same as a value position, and this protocol once confused them

Section 3 is the easy track. `agentic` has no contested dimensions, so an annotator's offset
from the pool mean is unambiguously leniency and the flag means what it says. On `refusal`
that stopped being true, and for a while this protocol printed a diagnosis that was wrong in
the most damaging possible way.

**What it used to say.** Four of six annotators flagged on `refusal`, a flagged fraction of
0.667 against the 0.34 budget, including **both seniors** -- A1-senior flagged harsh at
-0.487 and A2-senior flagged lenient at +0.4315. On the face of it, a pool falling apart on
the hardest track, and a re-anchoring session for the two best annotators in the roster.

**Why it was wrong.** Their leniency was computed as the raw offset from the pool mean over
*all* dimensions, and three of `refusal`'s five dimensions are contested. A1-senior and
A2-senior hold the roster's two most extreme `value_position` traits. What the detector was
measuring on those two was not how soft or harsh they are; it was where they stand on
whether a given refusal was appropriate. **The bias detector was reporting a value position
as a quality defect, on the one track where separating those two things is the entire
argument.** Worse, it was doing so symmetrically: two annotators who disagree with each
other about the construct both look miscalibrated, and the pool looks broken precisely when
it is functioning as designed.

**The fix.** `profile_annotators` now decomposes the offset. `bias_vs_pool_uncontested` is
computed over the non-contested dimensions only and is the only thing that can raise
`systematic_bias`. `contested_position` is the residual offset on the contested dimensions,
net of that leniency, and is reported as a position -- it does not count toward the flagged
fraction and it is explicitly not remediable by retraining.

| Annotator (`refusal`) | Raw offset | Leniency (uncontested) | Contested position | Gold exact (n) | Flags |
|---|---|---|---|---|---|
| A1-senior | -0.4870 | +0.1065 | -0.9892 | 0.8250 (40) | none |
| A2-senior | +0.4315 | -0.0231 | +0.7577 | 0.9000 (40) | none |
| A3-core | -0.1907 | -0.0046 | -0.3102 | 0.8545 (55) | none |
| A4-core | +0.1611 | -0.1806 | +0.5694 | 0.7000 (50) | none |
| A5-fast | +0.4389 | +0.3009 | +0.2299 | 0.7400 (50) | suspiciously_fast:31.1s |
| A6-untrained | -0.3537 | -0.1991 | -0.2577 | 0.6857 (35) | gold_accuracy_below_floor:0.69<0.7 |

Both seniors' leniency sits well inside the 0.35 cut once the value position is removed, and
neither is flagged. The flagged fraction fell from 0.667 to 0.333 -- the same figure this
roster produces on `agentic`, `grounding` and `reasoning`, which is the sanity check that the
old number was an artifact rather than a track-specific pool failure. Three of six annotators
are recorded as divergent on the contested dimensions (A1-senior, A2-senior, A4-core, at
+/- 0.35 or more), and none of them is thereby miscalibrated.

**What to do about each, under the corrected profile.** Nothing for A1-senior, A2-senior,
A3-core or A4-core: their leniency is in range and their gold sits between 0.7000 and 0.9000.
A5-fast keeps its duration flag at a 31.1s mean, and it is the same finding as on `agentic`.
A6-untrained keeps its gold flag at 0.6857 against the 0.70 floor -- close, but the rule is
the rule, and the action is the one in section 3: remove and re-annotate.

**Three rules that follow, and they are the point of this subsection.**

- **Never compute a leniency statistic across contested and uncontested dimensions
  together.** The two components have opposite remedies. Leniency is an execution defect and
  retraining fixes it. A value position is not a defect at all and retraining will either
  fail or, worse, succeed -- producing agreement by teaching people to suppress a judgement
  they actually hold.
- **A pool that looks broken on exactly one track is a hypothesis about the instrument, not
  about the pool.** The same six people annotate all four tracks here. When the flagged
  fraction doubles on one of them, the first suspect is the statistic.
- **Report contested positions; do not flag them.** They belong in the record, because a
  pool split down the middle on a construct is the most decision-relevant thing a
  calibration report can say. They do not belong in a remediation queue.

## 4. Ongoing monitoring

**Cadence.** Recompute the pool profile, per-dimension agreement, and drift at the end of
every batch, and re-audit reliability **every 500 labels**.

**Drift test.** Permutation test on the range of batch means, 2000 permutations, batch labels
shuffled across annotations. Drift is reported only when the range is both statistically
distinguishable from that null (p < 0.05) **and** materially large (>= 0.20). A
significance-only rule flags trivial movement at large n; a threshold-only rule fires
constantly at annotation-programme sample sizes. Current run: 5 batches, range 0.1003,
p = 0.917, slope 0.0282 per batch. No drift.

Valid **only if item difficulty mix is constant across batches.** The pipeline enforces that
with serpentine difficulty-stratified dealing within each system, and by splitting each
response's replicates across batches. Do not run this statistic on convenience-ordered
batches; the permutation null does not rescue a mix confound.

**Triggers that pause collection.** Any of the following halts new labelling until resolved:

| Trigger | Threshold | Action |
|---|---|---|
| Drift detected | p < 0.05 and range >= 0.20 | Pause. Re-anchor the pool and re-annotate a bridge sample spanning the affected batches. Longitudinal claims across those batches are void. |
| Any dimension alpha below the blocking floor | < 0.50 (production) | Pause reporting on that dimension. More data does not fix a definition problem. |
| Flagged-annotator fraction | > 0.34 | Pause. Re-anchor or replace, then bridge-sample. Count leniency and gold flags only; contested positions are not defects (section 3.1). |
| Rubric-gap rate | > 0.15 | Pause. The instrument, not the pool, is the bottleneck; retraining against an ambiguous rubric does not converge. |
| Worst-annotator gold accuracy | < 0.70 | Do not pause the pool; remove that annotator and re-annotate their assignments. |
| Mean annotation duration below the floor | < 45 s | Suspect straightlining. Investigate before crediting the labels. |
| Score SD below 0.15 with n >= 10 | -- | Straightlining flag. Same treatment. |

## 5. Re-anchoring after a rubric revision

Rubric versions are content-addressed, so **changing a single anchor changes the hash and
invalidates pooling with prior labels.** That is deliberate: the most common silent failure in
an annotation programme is pooling labels collected under two definitions of the same task.

Procedure:

1. **Bump the revision and publish the changelog entry.** The `agentic` rubric is at r3; r2
   split `state_tracking` out of `error_recovery`, r3 moved the `argument_fidelity` critical
   threshold from 1 to 0 and added a counter-example to every anchor.
2. **Re-run stage 3 for the whole pool**, on items that exercise the changed anchors. One
   session, all annotators together.
3. **Bridge sample: re-annotate 40 items x 3 annotators = 120 labels** under the new revision.
   The 40 come from the *existing* corpus, span every level of every factor, and include at
   least three items the revision was intended to move.
4. **Compare old and new labels on the bridge.** The revision succeeded if targeted items
   moved and untargeted ones largely did not. If everything moved, the revision changed the
   construct rather than clarifying it, and the two label sets cannot be pooled at all.
5. **Gate before scaling:** bridge rubric-gap rate below 0.15, and per-dimension alpha no
   worse than pre-revision.
6. **Never mix revisions in one reliability computation.** Even a successful bridge does not
   make prior labels poolable; they are historical.

## 6. What gold items cannot tell you

This is the most important section in the document, and it is the mechanism the decision
engine relies on.

Gold items are, by construction, **the cases the rubric authors agreed on** -- that is what
makes a reference score authorable. So gold is systematically drawn from the uncontested part
of the item space.

Gold therefore verifies **execution**: can this annotator read the anchors and apply them to a
case with a defensible answer? It cannot verify **agreement on the hard items**, because the
selection criterion excludes them. A pool can be excellent on gold and irreconcilably split on
the judgement tail. A3-core is the miniature: 0.9286 on gold, +0.2797 biased elsewhere, and
not flagged by anything.

The pipeline turns the limitation into a diagnostic. Gold accuracy upper-bounds how well a
pool *can* execute the rubric; if it executes well and still disagrees, the residual is about
the construct, and rubric refinement does not converge value disagreement. The estimated
irreducible share is 0.503 on `agentic` and 0.666 on `refusal`. Gold accuracy enters the
decision engine as a **precondition** (>= 0.70, establishing the pool is competent at all)
rather than as an indicator, because without it low agreement is just a bad pool and the right
action is retraining. On `refusal` -- gold 0.7842, mean alpha 0.3548, best dimension 0.489,
rubric-gap rate 0.69 -- that combination produced the portfolio's only STOP.

Three corollaries:

- **Do not respond to low agreement by adding gold.** It will come back high and tell you
  nothing.
- **Do not report gold accuracy as a track quality figure.** It is about the pool, on the easy
  items.
- **Perfect on gold and split on judgement items is not a training problem.** It is either a
  rubric problem (measurable via the rubric-gap rate) or a contested construct (not fixable by
  measurement at all). Section 3.1 is the worked example of getting this wrong: the split
  showed up as a leniency flag on both seniors, and the remedy that diagnosis implied --
  re-anchor the two best annotators in the pool -- would have been actively harmful.

**One caveat on the STOP that rests on this mechanism.** Which dimensions count as contested
is set by hand in `annotation/effects.py`, not inferred. `results/sensitivity.json` re-runs
the pipeline with those flags perturbed and finds that clearing `refusal`'s three returns
ITERATE rather than STOP. The mechanism described in this section is sound; the input it
consumes is a judgement, and the verdict it produces should be quoted with that condition
attached.
