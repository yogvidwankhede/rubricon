# Engineering log

A post-hoc record of the defects found and fixed while building Rubricon. Every entry
happened; the fix and its reasoning are documented in the source at the cited location.

**Dates are reconstructed from working notes.** The repository carries no commit history, so
the ordering is reliable and the exact days are approximate.

**Simulated pool.** Where an entry cites an agreement, drift, or gold figure, the underlying
labels came from the simulated pool in `src/rubricon/annotation/pool.py`. No human labelled
anything. The bugs are real; the data they were found on is synthetic. Current-run figures are
from `results/portfolio.json`, md5 299bd4f19e03caa2cd7e33681340c294, and from
`results/sensitivity.json`; a few historical figures survive only in source comments and are
marked where they appear.

## The theme

Twelve of the seventeen defects below produced **false alarms** in the quality machinery. Not
wrong answers -- alarms. A drift detector that fired on healthy tracks. A coverage gate that
would have blocked every honest study. An adjudication rule that blamed the rubric for
disagreements the rubric did not cause. A red-team probe that failed on every track because
the answer was baked into its input. A bias detector that reported two annotators' value
positions as leniency.

This is the failure mode I watch for hardest, because it conceals itself. A gate that blocks
a real claim gets argued about immediately. A gate that fires constantly gets a workaround:
people stop reading it, then stop running it, then delete it. **A quality gate that cries
wolf is worse than no gate, because it spends the credibility a real alarm would need.**
Three of the fixes below were prompted by someone saying "ignore that one, it always does
that."

**The counter-theme, added late and more important than I expected.** Two of the seventeen
are the opposite failure: a check that stayed quiet when it should have spoken. The power
calculation blocked a *true* effect, and `make audit` passed a *wrong* figure. Those cost
more per occurrence than any false alarm on this list, because a false alarm eventually
annoys somebody into looking at it, and a silent pass never does. Both are dated 2026-07-16
and 2026-08-05 below. The first of them is the most consequential defect in the project: it
changed a gate verdict on the flagship track.

---

**2026-05-02 -- Range restriction read as annotator disagreement.**
*`pool.py`, `latent_scores`.* Agreement collapsed on every dimension of every track at once.
Latent scores had no shared response-quality factor, so each dimension was near-degenerate
and alpha collapsed from range restriction rather than from disagreement. Fixed by adding a
single shared "how well did this system do on this item" term with per-dimension loadings,
sized as the dominant variance component. Lesson: low agreement has causes with opposite
remedies, and a corpus with no between-item variance produces low alpha however good the
annotators are. This is the confound the kappa-paradox check exists to catch, and I missed it
in my own generative model.

**2026-05-05 -- Annotator traits applied in absolute rubric points.**
*`pool.py`, `_observe`.* Binary and 0-1 dimensions showed coin-flip disagreement on
near-objective judgements. `bias` and noise were added in absolute points regardless of scale
span, so a +0.42 leniency -- a rounding nudge on 0-4 -- parked half the items of a 0-1
dimension on the rounding boundary. Fixed by calibrating traits against a reference 0-3 scale
and rescaling by `(hi - lo) / 3`. Lesson: "half a point soft" is not scale-free. Any parameter
expressed in score units must be normalised to the scale in front of the annotator.

**2026-05-11 -- Annotator window rotation strided by k.**
*`pool.py`, `annotate`.* Drift alarms on tracks with no drift mechanism. The window rotated by
the replication count; with 6 annotators and k=3 that yields exactly two triples,
`{A1,A2,A3}` and `{A4,A5,A6}`, alternating with index parity. Batch was also a function of the
index, so pool composition correlated with batch and the detector faithfully reported an
assignment artifact. Fixed with a stride of 1, producing all six windows so every pair
co-occurs. Lesson: two schedules derived from the same index are not independent.

**2026-05-11 -- Batch count sharing a factor with roster size.**
*`pool.py`, the `math.gcd` guard.* The same false drift survived the stride fix. Four batches
against six annotators (gcd 2) makes pool composition periodic in batch: batches 0 and 2 draw
from one half of the roster, 1 and 3 from the other. `annotate` now raises unless
`gcd(n_batches, len(annotators)) == 1`; the portfolio runs five batches over six annotators.
Lesson: where a periodicity bug is possible, assert against it rather than commenting. It
took a spurious drift BLOCK on the flagship track to notice, which means it was missable.

**2026-05-18 -- Round-robin dealing over a difficulty-sorted list.**
*`pool.py`, the serpentine comment.* Batch means declined monotonically with batch index on
two tracks. Round-robin over a sorted list does not equalise, it *guarantees a gradient*:
batch j gets ranks j, j+B, j+2B, each exactly j positions harder than batch 0's counterpart.
Fixed with serpentine dealing (0,1,2,3,4,4,3,2,1,0,...), applied per system so system
composition is fixed on the same margin. Lesson: round-robin is a balance heuristic only over
an unordered list. Calling a procedure "stratified" does not make it balanced.

**2026-05-24 -- Drift detection with a fixed threshold and no null model.**
*`stats/drift.py`, `detect_drift`.* Constant drift alarms on healthy tracks. The rule flagged
drift when the range of batch means exceeded a constant. At ~86 observations per batch and a
within-batch SD near 0.75, the standard error of a batch mean is about 0.08, so the expected
range of five means under *no drift at all* is roughly 0.19 -- most of the way to a fixed 0.25
threshold before anything has gone wrong, and past it on any track whose null happens to
spread. Replaced with a permutation test over shuffled batch labels (2000
permutations), requiring both statistical distinguishability (p < 0.05) and materiality
(range >= 0.20). The evidence is in today's results: `grounding` has a batch-mean range of
0.2806 at p = 0.068, above the old 0.25 threshold and not distinguishable from noise. The old
detector would be blocking that track's longitudinal claims right now for no reason. Lesson:
no threshold on a sample statistic means anything without a null distribution.

**2026-05-27 -- Drift not identifiable without cross-batch item overlap.**
*`pool.py`, the batch comment in `annotate`.* Two tracks reported drift that survived every
stratification fix. Each response's replicates all landed in one batch, so batch means
differed for two inseparable reasons: the annotators changed, or the responses were harder.
Item-feature stratification partly controls the second, but response *quality* is not knowable
in advance -- you cannot stratify on how well the model happened to do -- so a residual
confound always survives. Fixed by splitting each response's three annotations across three
batches, the same logic a real programme implements with a re-annotated bridge sample.
Lesson: better stratification cannot fix an identification problem; the design has to break
the tie.

**2026-06-03 -- Coverage gating on full-factorial emptiness.**
*`gates/signal.py`, `check_coverage`.* The check blocked all four tracks. It gated the fraction
of empty full-factorial cells against a 0.20 budget, but full-factorial coverage grows
multiplicatively -- the agentic design has 180 cells -- so any hand-annotatable corpus is
overwhelmingly empty by construction. Today's figures are 0.7611, 0.8000, 0.8698 and 0.9630;
all four would block, permanently. Switched to marginal coverage: no declared level absent,
and the share of levels below the minimum count under budget. Agentic now reports a marginal
gap of 0.000 across all 15 declared levels, with a balance-ratio warning at 0.333. Lesson: a
gate nobody can pass teaches people to declare fewer factors, which loses the analysis, not
just the check. Pick the denominator that matches the actual threat.

**2026-06-14 -- The rubric-gap rule over-attributing to the instrument.**
*`annotation/adjudicate.py`.* Rubric-gap rates above 60 percent on tracks with a single
contested dimension, blocking claims against the 0.15 budget. The rule flagged a gap whenever
*any* contested dimension appeared among the disputed ones -- but triage selects
high-disagreement responses, and those almost always include the contested dimension
somewhere. It was measuring triage selection, not ambiguity. Tightened to require the
contested dimension be the primary driver: at least 50 percent of weighted spread. Rates are
now 0.000 (agentic), 0.0357 (grounding), 0.0469 (reasoning) and 0.6909 (refusal), and the
refusal figure is credible precisely because the other three are not inflated. Lesson: a
statistic computed over a selected subsample inherits the selection rule.

**2026-06-21 -- The STOP rule as a four-way conjunction.**
*`gates/decision.py`.* The engine declined to recommend STOP on a track where every substantive
signal said stop. All four conditions had to hold, and the refusal track's gold accuracy came
in at 0.725 against a 0.75 cut -- one threshold two points low vetoed the call, while its best
dimension sat at 0.59, its irreducible share at 0.57 and adjudicators attributed 58 percent of
disagreements to definitional ambiguity. (Those four figures are the ones recorded in the
source comment, from the run on which the bug was found. The current run puts the same track at
gold 0.7842, best dimension 0.489, irreducible 0.666 and a rubric-gap rate of 0.6909, so the
anecdote's exact numbers are no longer reproducible from `portfolio.json`.) Replaced with two
of three independent indicators, and gold accuracy demoted to a precondition at the
pre-registered 0.70 floor because it answers a different question -- is the pool competent at
all. Refusal now fires 3 of 3 and returns STOP. Lesson: a conjunction of thresholds is brittle
in the wrong direction. Separate preconditions from indicators, and count indicators.

**The uncomfortable part, kept here rather than tidied away.** A threshold was loosened
*after* seeing that it declined to produce the expected verdict. That is exactly what
pre-registration exists to prevent, and the reasoning above -- that gold accuracy answers a
different question from the indicators and belongs in a different role -- is a good argument
that I nonetheless would not have gone looking for if the engine had said STOP the first
time. I cannot separate the two motives from the inside and I am not going to pretend
otherwise.

`gates/sensitivity.py` was built partly as the answer to this entry. The right response to
"you moved a threshold" is not a better argument for the new value; it is to publish how far
the conclusion depends on where the threshold sits, and let the reader price it. It does
that now, every cut, mechanically: the gold precondition this entry moved sits at 0.70, and
`refusal`'s recommendation turns from stop to iterate once it is raised to 0.784287 -- 12.0
percent away, against an observed gold accuracy of 0.7842, so the cut is doing real work and
the sweep says exactly how much. The gate's own `min_gold_accuracy`, also 0.70, changes
`refusal`'s check verdicts at 0.685625, 2.1 percent away. The two-of-three indicator rule
flips the recommendation at 4.0 indicators on `refusal` and at 1.0 on `grounding`. Twelve of
96 threshold-by-track pairs are FRAGILE. None of that vindicates the
edit. It does mean the edit is no longer invisible, which is the most a post-hoc fix can
honestly buy. Lesson, separate from the technical one: when you change a threshold after
seeing results, the durable remedy is instrumentation, not justification.

**2026-07-02 -- A circular red-team probe.**
*`redteam/probes.py`, `position_bias`.* The probe failed on every track. It stipulated an
order effect, simulated flips under that stipulation, and reported pass/fail against it --
the answer was baked into the input. Rewritten as a sensitivity analysis that solves for the
smallest order advantage which would flip 10 percent of pairwise comparisons, given the
observed score distribution and the pool's measured judgement sigma, then compares that to
the largest real between-system difference. The first rewrite still failed on all four tracks,
with a solved critical effect of 0.000 every time, against reference effects of 0.1573, 0.1469,
0.0497 and 0.1337. Zero meant even a zero order advantage flips 10 percent of pairs -- a
statement about pool noise on near-tied comparisons, not about position bias, because the flip
rate at zero order effect is not zero and on close systems already exceeds 10 percent. Fixed by
solving for the EXCESS flip rate an order effect adds *on top of the measured noise floor*
rather than the absolute flip rate. Critical effects are now 0.1508, 0.1569, 0.1574 and 0.2144
against the same reference effects, so the probe fails on `agentic` alone -- the track whose
real between-system effect (0.1573) is the largest in the portfolio and therefore the one an
order artifact of plausible size could actually reorder. Lesson: if a probe cannot fail for the right reason, it cannot pass for the right
reason either -- and a statistic that has to be measured against a noise floor must have that
floor subtracted, not assumed away.

**2026-07-09 -- Leave-one-out probe with a fixed absolute tolerance.**
*`redteam/probes.py`, `annotator_leave_one_out`.* The probe fired on every track. It compared
the leave-one-out shift in the track mean against a fixed constant unrelated to the width of
the published interval. The tolerance is now the reported CI half-width, which is the right
comparison: if removing one annotator moves the mean further than the uncertainty you
published, that interval does not cover a source of variation you already know about. Current
shifts are 0.0267, 0.0338, 0.0268 and 0.0532 against half-widths of 0.0680, 0.0867, 0.0758 and
0.0832 -- all pass. **Caveat:** I cannot reproduce the original constant. The surviving fallback
is 0.03, against which `grounding` (0.0338) and `refusal` (0.0532) would fire today, not all
four; "fired on every track" is the account in the source docstring, on data I no longer have.
Lesson: a tolerance must be expressed in the same currency as the claim it guards.

**2026-07-16 -- The reliability tax charged twice, against the wrong reliability, blocking a
true effect.** *`stats/precision.py`, `minimum_detectable_effect`; `stats/agreement.py`,
`composite_reliability`.* **The most consequential defect in this project, and the only one
that changed a published verdict.** The `agentic` v2-vs-baseline ranking was BLOCKED on an
MDE of 0.1569 despite a difference of 0.1243, a permutation p of 0.0049, a 95 percent CI of
[0.0414, 0.2115] excluding zero, and significance after Bonferroni. The correct MDE is
0.1199 and the claim now WARNs. Two independent errors, both pushing the same way.

*Wrong reliability.* The power calculation was fed the mean of the per-dimension
single-rater alphas -- 0.5841 on `agentic`. That is not the reliability of anything the
comparison touches. The compared quantity is the per-item mean of a **weighted composite,
averaged over three annotators**, so its reliability is the composite's own alpha stepped up
by Spearman-Brown for a 3-rater mean. `composite_reliability` now computes both:
rho_1 = 0.7497 and rho_3 = 0.8999. Using 0.5841 in place of 0.8999 understated the
information in the design by a wide margin, and it did so systematically, because a mean of
per-dimension alphas is always below the reliability of a weighted sum of those dimensions.

*Double count.* The identity `n_eff = n * rho` is for effects expressed in **true-score**
units. The SD being fed in was the **observed** SD, which already contains the measurement
error. Shrinking n to n_eff on top of that charges for the same error twice and inflates the
MDE by exactly 1/sqrt(rho). `minimum_detectable_effect` now computes the MDE at plain n
against the observed SD, ships it as `mde_observed_scale`, and reports `n_effective` (43.2
on `agentic`) and `mde_true_scale` (0.1264 for that contrast) alongside as separate figures
that are never compounded. The docstring states the convention in full, because the trap
here is that both halves are individually defensible and only the combination is wrong.

The portfolio's block count fell by one, to 23 of 45. That single claim is the whole point.
**A gate that blocks a true positive is worse than no gate**, and it is worse in a way the
false-alarm failures on this list are not: an over-firing gate gets ignored, which is
recoverable, while a wrongly-withheld finding leaves no trace at all. The reader sees a
block reason where a number would have been and has no way to tell a correct suppression
from an arithmetic error. Two years of this and the programme would conclude, correctly by
its own evidence, that it is never powered for anything.

A secondary consequence worth recording: the reliability tax turned out to be far smaller
than the earlier figures implied. Averaging three annotators buys most of it back, so the
losses are 10, 12, 10 and 36 percent rather than the 42 to 65 percent previously reported.
Only `refusal` pays a large one, at rho_1 = 0.3686, rho_3 = 0.6365 and n_eff = 22.9 -- which
is the right answer, because a value position does not average out over annotators the way
independent noise does. Lesson: a correction can be applied to the wrong quantity and in the
wrong place at the same time, and both mistakes will look like conservatism.

**2026-07-21 -- The bias detector reporting value positions as leniency.**
*`stats/drift.py`, `profile_annotators`.* Four of six annotators flagged on `refusal` -- a
flagged fraction of 0.667 against a 0.34 budget -- including both seniors, A1-senior at
-0.487 and A2-senior at +0.4315. Their configured leniency traits are +0.03 and -0.06. The
offset was computed against the pool mean over *all* dimensions, and three of `refusal`'s
five are contested, so what the detector measured on those two was their `value_position`
leaking through: the term that is added to contested dimensions only, in the same direction,
every time. The detector was reporting a value position as a quality defect on the one track
where separating those two things is the entire argument -- and symmetrically, so two people
who disagree with each other both looked miscalibrated and the pool looked broken exactly
when it was behaving as designed. Fixed by decomposing the offset:
`bias_vs_pool_uncontested` is computed over the non-contested dimensions only and is the
only thing that can raise `systematic_bias`, while `contested_position` reports the residual
on the contested dimensions as a position that does not count toward the flagged fraction.
A1-senior and A2-senior now come in at +0.1065 and -0.0231 leniency, inside the 0.35 cut,
with contested positions of -0.9892 and +0.7577. The flagged fraction on `refusal` fell from
0.667 to 0.333, the same value the same roster produces on the other three tracks. Lesson:
the tell was that one track's pool health collapsed while the roster was identical
everywhere. When a pool statistic moves and the pool does not, suspect the statistic.

**2026-07-27 -- A part-whole correlation reported as a shortcut statistic.**
*`redteam/probes.py`, `rubric_shortcut`.* The probe asked whether one dimension can
reconstruct the composite, and answered it by correlating each dimension against a composite
**containing that dimension**. Part of the resulting r is arithmetic rather than evidence:
`goal_completion` carries the largest weight in the `agentic` rubric, so it would correlate
substantially with the composite even if it were statistically independent of every other
dimension. The consequence was a probe drifting toward a false failure -- `grounding`'s
`citation_validity` read 0.9225 against a 0.93 tolerance, which is the narrowest pass in the
portfolio and was being treated as a genuine near-miss. Rewritten to correlate each dimension
against the **leave-one-out** composite, recomputed with that dimension's own weight zeroed,
which is the question the probe was always asking. `citation_validity` is 0.8498 on that
basis; `agentic`'s worst is `argument_fidelity` at 0.7718 against a part-whole 0.853, and
`goal_completion` drops from 0.89 to 0.7481. The part-whole value is retained as
`correlation_to_composite_part_whole` and the gap published as `part_whole_inflation`
(0.0727 for `citation_validity`, 0.1419 for `goal_completion`), because removing an
inflation silently is indistinguishable from having tuned the probe until it passed. Lesson:
if a statistic has an arithmetic floor, report the floor next to the statistic.

**2026-08-01 -- Fleiss kappa and Gwet AC1 printed side by side under two different chance
models.** *`stats/agreement.py`, `fleiss_kappa`.* Kappa took category prevalence from the
rating-weighted marginal, `sum_i r_ik / sum_i r_i`, while AC1 in the same module used the
unit-averaged marginal, `(1/n) * sum_i r_ik/r_i`. The two coincide exactly when every unit
has the same number of raters, which is why the equal-rater reference checks against
`statsmodels` could not tell them apart -- and diverge under unequal raters, where the
rating-weighted form lets heavily-rated units dominate the chance model. So the alpha/kappa
and kappa/AC1 gaps, which this project treats as the diagnostic for the kappa paradox, were
being read off two coefficients that did not share a definition of chance. Not an alarm and
not a wrong verdict: a wrong number in the one comparison the module docstring says is
informative. Fleiss now uses the unit-averaged marginal, matching AC1, verified against
`irrCAC` on an unequal-rater set. Lesson: two statistics reported for the purpose of being
compared must be computed against the same null, and a test suite built on balanced data
cannot check that.

**2026-08-05 -- A wrong figure passing `make audit` on a coincidental half-value.**
*`scripts/audit_numbers.py`.* The audit is set membership, not provenance: it asks whether a
number quoted in the docs exists anywhere in the results, not whether it means what the
sentence says. To that set it adds each value's percentage form and its **halved** form,
because intervals are recorded as full widths and quoted as half-widths. That is a large
expansion of the target, and it let a stale figure through. When the reliability tax was
corrected, an earlier draft of the README and of the research report still carried
`n_eff = 28.0` at a 42 percent loss for `agentic`. Both passed: 28.0 is exactly half of the
56 adjudicated responses on `grounding`, and 42 is exactly half of A6-untrained's 84 gold
comparisons on `agentic`. Neither quantity has anything to do with statistical power. The
figures were caught by reading, not by the check that exists to make reading unnecessary.

Three things came out of this. The docstring now states the limit plainly -- roughly 80
percent of the three-decimal grid on [0,1] is occupied once derived forms are included, so a
two- or three-decimal figure can pass by coincidence, and precision is the defence. The audit
now also loads `results/sensitivity.json`, so the newest figures in the repository are
checked rather than allowlisted. And the standing instruction is to quote four decimals
wherever the results record four. Lesson: a checker with a known false-negative rate is
still worth running, but only if the rate is written down where the people trusting it will
read it. A silent pass is the most expensive output any check can produce, and this one is
the check that guards every other number in this log.

---

## What I would do differently

Write the null model first. Six of the seventeen entries are the same mistake in different
costumes: a threshold applied to a statistic whose behaviour under "nothing is wrong" was
never characterised. The permutation test, the marginal coverage denominator, the CI-relative
leave-one-out tolerance, the leave-one-out shortcut composite and the two-of-three indicator
rule are all one correction -- ask what the number does when the system is healthy, then set
the bar above that.

Check the inputs to a threshold as hard as the threshold. The 2026-07-16 entry is the one I
would most want back. Every review of the gate went to the cut -- is 0.50 the right blocking
floor, is the MDE requirement too strict -- and none went to whether the MDE being compared
against was computed correctly. A pre-registered threshold applied to a wrong statistic is
not rigour; it is rigour-shaped.

And instrument the alarms. The cheapest signal that a gate is broken is its firing rate across
tracks. Four-out-of-four is not a finding, it is a bug report about the check. That heuristic
would have caught the coverage gate, the old drift detector, the old leave-one-out tolerance,
the circular position-bias probe and its first rewrite -- which still fired on all four tracks
and is the entry that stayed open longest. It fires on one track now, which is what a working
probe looks like.
