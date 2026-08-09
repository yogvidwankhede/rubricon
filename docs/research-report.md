# Rubricon: measuring whether an evaluation can support the sentence built on top of it

**Methods and findings report**

| | |
|---|---|
| Data source | `results/portfolio.json` |
| md5 | `299bd4f19e03caa2cd7e33681340c294` |
| Assumption-dependence | `results/sensitivity.json` (`make sensitivity`) |
| Reproduce | `make all` |
| Scope | 4 tracks, 168 items, 504 responses, 1512 annotations, 21 dimensions, 50 failure codes |

> **ANNOTATORS ARE SIMULATED. No human labelled anything in this repository.**
> Every agreement, drift and gold statistic below is a property of the generative
> annotator model in `src/rubricon/annotation/pool.py`. The corpora are authored
> fixtures, not captured model output.
>
> This is the design, not a disclaimer. The measurement machinery is real and
> validated; the corpus and annotations are constructed so that ground truth is
> known, which is what makes it possible to ask whether the instrument detects what
> it claims to detect. **Every finding here is a finding about the instrument. None
> is an empirical claim about a language model.** Where the text says "the eval
> cannot separate v2 from v3", it means the measurement lacks resolving power -- the
> systems are fixtures with stipulated failure rates.

---

## 1. Summary

Rubricon builds four rubric-based evaluation tracks end to end -- corpus, rubric,
annotation, adjudication, agreement statistics, power analysis, red-team probes, a
publication gate and a decision engine -- then turns the machinery on itself to ask
which tracks produce numbers strong enough to act on.

| Track | Depth | Mean alpha | rho_1 / rho_3 | Gold accuracy | Recommendation | Stability |
|---|---|---|---|---|---|---|
| `agentic` -- Agentic tool-use failure evaluation | production | 0.5841 | 0.7497 / 0.8999 | 0.7932 | **invest** | FRAGILE |
| `reasoning` -- Reasoning process quality | pilot | 0.5589 | 0.7177 / 0.8841 | 0.7694 | **iterate** | CONDITIONAL |
| `grounding` -- Grounding and citation integrity | pilot | 0.4791 | 0.7600 / 0.9047 | 0.8669 | **iterate** | CONDITIONAL |
| `refusal` -- Refusal calibration and over-refusal | exploratory | 0.3548 | 0.3686 / 0.6365 | 0.7842 | **stop** | CONDITIONAL |

**Read the Stability column before the Recommendation column.** It comes from
`results/sensitivity.json`, which re-runs the whole pipeline 196 times under perturbed
assumptions and reports which verdicts move. None of the four is ROBUST. Section 7 gives
the method and the results in full; the one-line version is that clearing `refusal`'s
three contested-dimension flags turns its STOP into an ITERATE, and that those flags are
an input I set by hand. **The four recommendations below are conditional findings, not
discoveries**, and the useful output of this project is the instrument that measures how
conditional they are rather than the verdicts themselves.

- **`agentic`: invest.** Mean alpha 0.584 over six dimensions, worst 0.472, gold 79%.
  Mean 95% CI half-width 0.068, smallest MDE 0.094, largest observed between-system
  effect 0.157. Detection sensitivity 4 of 4 estimable codes. The only track whose
  depth contract permits a release-gate claim and the only one close to earning it --
  and the only one the sensitivity analysis classifies FRAGILE, because removing either
  `A2-senior` or `A3-core` from the roster turns INVEST into ITERATE.
- **`reasoning`: iterate.** Four of five dimensions usable;
  `explanation_faithfulness` at 0.2414 drags the mean down. Drop it and re-measure.
  Projected cost to fix $102.00.
- **`grounding`: iterate.** Same shape, worse: `abstention_appropriateness` 0.1592
  and `completeness` 0.3678 against `claim_support` 0.7439. Also the only track with
  measured detection blind spots (GF-12, GF-02). Projected cost to fix $102.00.
- **`refusal`: stop** as a scalar measurement. Three of three structural indicators
  fired: best dimension 0.489, irreducible disagreement share 67%, and 69% of
  adjudicated disagreements attributed to rubric ambiguity rather than annotator
  error. Gold accuracy 78% says the pool is competent, so this is not an execution
  problem. Section 6. **Conditional on the contested flags**: with them cleared this
  track reads ITERATE, and a random reassignment of the same five flags across the
  portfolio's 21 dimensions reproduces STOP in 11 of 20 seeds.

Portfolio-wide, **45 claims were submitted to the signal gate and 23 blocked -- a
block rate of 0.511.** A pipeline that publishes everything it computes is not a
measurement pipeline, it is a rendering pipeline.

Two further results. The **candidate-versus-candidate contrast sits inside the
minimum detectable effect on all four tracks**: the eval cannot separate
`sut-candidate-v2` from `sut-candidate-v3` anywhere, and saying so is the result.
And the **reliability tax is real but much smaller than an earlier draft of this
report claimed**: the composite the comparisons are computed on is a 3-annotator mean,
whose reliability is rho_3 = 0.8999 on `agentic`, so n=48 resolves like 43.2
perfectly-reliable items -- a 10% precision loss, not the 42% a double-counted
correction produced. Only `refusal`, at rho_3 = 0.6365, pays a large one: n=36
resolving like 22.9 items, a 36% loss. The arithmetic error and the gate verdict it
flipped are in `docs/engineering-log.md`.

---

## 2. Problem framing: signal, not coverage

The default answer to "our evals are not good enough" is more evals -- more tasks,
domains, languages, adversarial slices. Coverage is legible and produces a chart
that goes up. It is rarely the binding constraint. The binding constraint is
**signal**: whether the numbers a suite already produces can bear the sentences
built on them.

The specific failure is narrow:

1. An analyst runs an eval. Candidate v2 scores 0.585; candidate v3 scores 0.618.
2. It goes on a slide as "v3 is ahead of v2".
3. Nobody computes the minimum detectable effect. On this track it is 0.0944; the
   observed difference is 0.0329 -- about a quarter of it -- with a 95% interval of
   [-0.100, 0.032] straddling zero and a permutation p of 0.331.
4. Three weeks later the slide is an artifact. Questioning it is a political act,
   because the number exists and the burden has shifted to whoever wants to withhold
   it.

Those are the real `agentic` figures. The eval did not lie; the sentence did.
Nothing in a conventional report catches this, because the template has a column for
the mean and no column for the resolution.

Three commitments follow. **Rigour is a property of the design, declared before
collection**: each track declares a depth tier carrying a written contract on what
claims it may support, enforced numerically at gate time rather than by an analyst's
memory. **Claims are the unit of governance, not numbers**: a number is not right or
wrong, a sentence built on one is. **A stop recommendation must be reachable**:
agreement can always be nudged and nobody is fired for collecting more labels, so
"stop" must be a mechanical output rather than an act of courage.

---

## 3. Method

### 3.1 Rubric design

Rubrics are versioned and content-addressed (`track@rN+<hash>`, hashed over dimensions
and anchors), so a silent anchor edit cannot masquerade as the same instrument and
labels under different hashes are not poolable.

**Every level of every anchored dimension must be anchored**; the schema raises on
partial anchoring. An unanchored scale produces annotator-specific units, which look
like disagreement but are unit mismatch. Partial anchoring is worse, because it creates
gravity wells: annotators facing an unanchored level reach for the nearest described
one, so anchored levels absorb mass from their neighbours. That distortion is invisible
to the agreement statistic, because annotators now agree -- on the wrong partition.

Dimensions carry weights; some are **critical-gated**, where a failing score zeroes
the composite regardless of the rest -- the asymmetry where one fabricated citation
invalidates an otherwise excellent answer. Composites are weighted means in [0,1],
critical gating first. Two `refusal` dimensions carry weight 0.0 and are excluded by
design, `response_stance` because it is a classification rather than a quality
judgement.

### 3.2 Sampling and stratification

Each track declares a strata design before items exist. The declared design, not the
realised data, is the coverage denominator.

| Track | Factors | Declared levels | Items | Full-factorial cells |
|---|---|---|---|---|
| `agentic` | 4 (`task_family`, `horizon`, `adversity`, `side_effects`) | 15 | 48 | 180 |
| `grounding` | 3 (`domain`, `question_type`, `evidence_condition`) | 15 | 40 | 125 |
| `reasoning` | 4 (`problem_domain`, `difficulty`, `trap_type`, `answer_type`) | 18 | 44 | 315 |
| `refusal` | 5 (`request_class`, `surface_features`, `stated_role`, `risk_level`, `expected_contested`) | 21 | 36 | 864 |

Replication is 3 on every track (`mean_replication` 3.00): 504 responses, 1512
annotations. The declared gold-item rate is 0.15 on all four tracks -- from the track
specifications in `src/rubricon/tracks/`, not from `portfolio.json`.

Two scheduling details matter more than they look. Each response's three annotations
are **split across three batches**, because otherwise batch means differ for two
inseparable reasons -- the annotators changed, or the responses were harder -- and drift
is not identifiable. Batches are dealt **serpentine** within each system over a
difficulty-sorted list, because round-robin over a sorted list does not equalise, it
guarantees a gradient.

### 3.3 Annotation model -- simulated, described honestly

Six simulated annotators, one fixed roster reused across all four tracks, recorded in
full in `portfolio.json`:

| Annotator | competence | bias | value_position | speed_factor | fatigue_rate |
|---|---|---|---|---|---|
| A1-senior | 0.93 | +0.03 | -0.75 | 1.30 | 0.004 |
| A2-senior | 0.90 | -0.06 | +0.80 | 1.20 | 0.005 |
| A3-core | 0.84 | +0.11 | -0.35 | 1.00 | 0.007 |
| A4-core | 0.81 | -0.14 | +0.45 | 1.00 | 0.008 |
| A5-fast | 0.72 | +0.42 | +0.15 | 4.00 | 0.011 |
| A6-untrained | 0.58 | -0.31 | -0.20 | 0.75 | 0.016 |

Trait definitions as recorded: **competence** scales down judgement noise (1.0 would be
a perfect reader of the rubric); **bias** is a persistent leniency (+) or harshness (-)
offset in rubric points; **fatigue_rate** is noise inflation per item within a session;
**speed_factor** is relative pace (<1 is slower than reference); **value_position** is
a stable stance applied ONLY to dimensions marked contested.

**The contested mechanism is the crux.** On an uncontested dimension, deviation from
the latent value is mean-zero noise scaled by competence and fatigue. On a contested
dimension an additional term proportional to that annotator's `value_position` is
added -- the same term, the same direction, every time. That separates an instrument
which is imprecise from one measuring a quantity with no agreed referent. Independent
noise shrinks with replication by roughly sqrt(3) at k=3; a stable value position does
not shrink at all. A1-senior at -0.75 and A2-senior at +0.80 disagree on the same
contested items forever while both stay accurate on items with a defensible answer. A
hundredth annotator buys precision around the location of a split, not convergence
toward a truth.

| Track | Contested dimensions |
|---|---|
| `agentic` | none |
| `grounding` | `abstention_appropriateness` |
| `reasoning` | `explanation_faithfulness` |
| `refusal` | `calibration`, `over_refusal_cost`, `tone_respect` |

Gold items are by construction cases the rubric authors agreed on, so value positions
are switched off on them -- realistic, and a real limitation (Section 8). The model is
specified in terms of annotator psychology and the reliability statistics fall out of
it; whether a track passes its gate is not set anywhere in `pool.py`. If the pool drew
scores from the gate's pass region, the exercise would be circular.

### 3.4 Statistics

**Krippendorff's alpha** is primary, via the coincidence-matrix formulation with a
scale-appropriate metric: ordinal for graded dimensions, binary for
`answer_correctness`, nominal for `response_stance`; the scale is recorded per
dimension. The implementation is validated against Krippendorff's published 2011 worked example
for all four metrics. *(Reference values 0.743 nominal / 0.815 ordinal / 0.849
interval / 0.797 ratio, and the 12-unit 4-observer fixture, come from
`tests/conftest.py`, which encodes the published table; they are not fields of
`portfolio.json`.)* It reproduces them well inside the 0.002 test tolerance -- 0.7434,
0.8154, 0.8491, 0.7974. This is the credibility anchor: a reader who distrusts the
annotation model can still verify to four decimal places that the agreement
mathematics is correct, on data neither this project nor its author chose.

**Fleiss' kappa and Gwet's AC1 are reported alongside** on every dimension. When one
category dominates, kappa collapses toward zero even at high raw agreement -- the kappa
paradox. A dimension at kappa 0.11 / AC1 0.79 / raw 0.94 has a prevalence problem, not
an annotator problem, and the fix is stratified sampling, not retraining; getting that
wrong buys weeks of retraining for a design flaw. The alpha/kappa gap is itself
diagnostic: `grounding`'s `claim_support` shows alpha 0.7439 against kappa 0.4468,
which is ordinal structure kappa discards. Both kappa and AC1 take chance agreement
from the **unit-averaged** category marginal rather than the rating-weighted one, so
the two coefficients printed side by side use the same definition of chance and the gap
between them means what the paragraph above says it means.

**Cluster bootstrap.** Repeated annotations of one response are not independent. All
intervals resample items and carry their annotations along: 2000 resamples, percentile
method. Resampling annotations instead would shrink intervals by roughly
sqrt(replication) and produce confidently wrong error bars. Every per-dimension alpha
also carries a cluster-bootstrapped interval, and the gate's reliability check reports
explicitly when that interval fails to exclude the policy threshold -- `argument_fidelity`
at alpha 0.5704 with a 95% interval of [0.4696, 0.6476] straddles the 0.500 blocking
floor, so which side of the floor it sits on is not established by these data.

**Reliability is a property of the compared quantity, not of a dimension.** System
comparisons are computed on the per-item mean of a weighted composite across three
annotators. Neither an individual dimension's alpha nor the mean of them is the
reliability of that quantity. `composite_reliability` therefore computes Krippendorff's
interval alpha of the per-annotator composite (`rho_1`) and steps it up to the 3-rater
mean by Spearman-Brown (`rho_3` = 0.8999, 0.9047, 0.8841 and 0.6365 on `agentic`,
`grounding`, `reasoning` and `refusal`). That is what the power calculation consumes.

**The reliability tax, charged once.** Measurement error attenuates effects, so the
effective sample size for detecting a *true* difference is approximately
`n_eff = n * rho`: 43.2, 36.2, 38.9 and 22.9 against 48, 40, 44 and 36 items. The MDE is
nevertheless reported on the **observed** scale, at plain n against the observed SD,
because that SD already contains the measurement error -- shrinking n to n_eff as well
would charge for the same error twice and inflate the MDE by 1/sqrt(rho). The
true-score-scale MDE is reported separately as `mde_true_scale`. An earlier version of
this pipeline compounded the two, and the resulting MDE blocked a contrast it should
have passed (Finding 3, and the engineering log).

**MDE and multiplicity.** Each comparison reports an MDE at 80% power and alpha 0.05
plus an `n_required_for_target` for a 0.05 difference. Three comparisons per track
gives a Bonferroni threshold of 0.0167 and 0.15 expected false positives uncorrected;
both verdicts are recorded. **Drift** is a permutation test over shuffled batch labels
(2000 permutations) requiring both distinguishability (p < 0.05) and materiality
(range >= 0.20).

### 3.5 The signal gate

Thresholds are declared before results exist; the full table is in 10.3. Two policies
exist -- the default used by `agentic`, `grounding` and `reasoning`, and a relaxed
exploratory policy used by `refusal`. The second one's existence is the point: it
makes "we relaxed the bar here" explicit and reviewable rather than something that
happens by omission.

Checks are independent and all run -- "this claim has four problems" is more useful than
"this claim has one". A claim blocks if any check blocks. The **claim ledger** records
every submitted claim including blocked ones, because suppressing the record would hide
that someone wanted to make the claim.

### 3.6 The decision engine

The engine separates *fixable-with-effort* (underspecified rubric, thin coverage,
uncalibrated pool) from *structurally limited* (genuine disagreement about what the
right answer is). STOP requires mean alpha below 0.55, a competent pool as a **precondition** (gold
accuracy >= the pre-registered 0.70 floor), and **two of three indicators**:
`no_dimension_usable` (best dimension alpha < 0.60), `disagreement_irreducible`
(irreducible share >= 0.55), `adjudicators_cite_definition` (rubric-gap rate >= 0.30).

Two-of-three rather than all-of-three, because a conjunction is brittle in the wrong
direction: one borderline value vetoes the call regardless of how strongly everything
else points. Gold accuracy is a precondition, not an indicator, because it answers a
different question -- is the pool competent at all? Without that, low agreement is just
a bad pool, and the fix is retraining.

The **irreducible share is a heuristic, labelled as one everywhere, and is not
causally identified.** Gold accuracy upper-bounds how well a pool *can* execute the
rubric; disagreement that demonstrated execution error can account for is reducible,
and the remainder is attributed to the construct. For `refusal`:

```
total disagreement    = 1 - alpha          = 1 - 0.3548 = 0.6452
reducible (execution) = 1 - gold accuracy  = 1 - 0.7842 = 0.2158
irreducible share     = (0.6452 - 0.2158) / 0.6452 = 0.666
```

The decomposition assumes gold and judgement items are exchangeable except for
contestedness. They are not (Section 8). It orders tracks sensibly; that is all that
is claimed for it.

---

## 4. Results by track

### 4.1 `agentic` -- Agentic tool-use failure evaluation

**Question.** Where do multi-step tool-using agents break, and which failure modes
can annotators identify with agreement high enough to support release decisions?
**Depth** `production` -- may report measurements, rankings, and act as a release gate
if all gate checks pass. **Unit** one agent trajectory (final message plus full tool
trace) on one item. 48 items, 144 responses, 432 annotations.

| Dimension | Scale | alpha | Fleiss kappa | Gwet AC1 | Raw | Band |
|---|---|---|---|---|---|---|
| goal_completion | ordinal | 0.7193 | 0.3008 | 0.3067 | 0.4444 | tentative |
| error_recovery | ordinal | 0.6254 | 0.3079 | 0.3333 | 0.4954 | moderate |
| state_tracking | ordinal | 0.6181 | 0.2962 | 0.3167 | 0.4838 | moderate |
| argument_fidelity | ordinal | 0.5704 | 0.3203 | 0.3776 | 0.5231 | fair |
| tool_selection | ordinal | 0.4990 | 0.2794 | 0.3456 | 0.4977 | fair |
| efficiency | ordinal | 0.4721 | 0.2138 | 0.2653 | 0.4398 | fair |
| **mean** | | **0.5841** | | | | |

Gold accuracy 0.7932; no contested dimensions. Kappa never exceeds 0.33 while alpha
reaches 0.72 -- ordinal structure kappa discards, not a hidden problem.

| System | Composite | 95% CI | SD |
|---|---|---|---|
| sut-baseline-v1 | 0.4610 | [0.3906, 0.5302] | 0.2743 |
| sut-candidate-v2 | 0.5853 | [0.5158, 0.6550] | 0.2629 |
| sut-candidate-v3 | 0.6182 | [0.5507, 0.6801] | 0.2566 |

| Contrast | Diff | 95% CI | p | MDE | Exceeds MDE | Bonferroni sig |
|---|---|---|---|---|---|---|
| v2 vs baseline | +0.1243 | [0.0414, 0.2115] | 0.0049 | 0.1199 | **yes** | yes |
| v3 vs baseline | +0.1573 | [0.0851, 0.2313] | 0.0003 | 0.1075 | **yes** | yes |
| v2 vs v3 | -0.0329 | [-0.1000, 0.0320] | 0.3310 | 0.0944 | no | no |

Both baseline contrasts clear their MDE and survive Bonferroni; the
candidate-versus-candidate contrast clears neither. The v2-vs-baseline row is the one
worth dwelling on, because in an earlier run of this pipeline it was **blocked**, on an
MDE of 0.1569 that was wrong. The power calculation was applying the reliability
correction twice -- shrinking n to an effective n *and* using an SD that already carried
measurement error -- which inflated the MDE by 1/sqrt(rho) and pushed a real, significant,
adequately-powered effect below the floor. The gate did exactly what it was told to do;
what it was told was arithmetically wrong. That is the most consequential defect in the
engineering log, and it is a false BLOCK on a true positive, which is the failure mode a
quality gate is least likely to be forgiven for.

**Detection sensitivity.** 13 codes, 4 estimable (>= 4 planted), 4 detected -- rate
1.000, no blind spots: AF-04 `error_ignored` (Cliff's delta 0.968 on
`error_recovery`), AF-06 `premature_termination` (0.968), AF-09
`partial_completion_reported_as_full` (0.959), AF-08 `unverified_assumption` (0.671).
The other nine carry 2-3 planted instances and are reported as **underpowered, not
undetected** -- conflating those would blame the rubric for a sampling gap.

**Coverage.** 43 of 180 cells populated (76% empty) -- expected, since full-factorial
coverage grows multiplicatively and is not the operative target. Marginal coverage
governs: 15 of 15 levels at n >= 4, marginal gap 0.000, worst balance ratio 0.333
(`side_effects`); highest-failure stratum `adversity=tool_error_injected` at 0.500.
**Drift** not detected: range 0.1003, p = 0.917.

**Red-team.** 5 probes, 1 failure. `length_bias` -0.2261 within clean responses
(tolerance 0.30); `lazy_baseline` 0.3981 (0.75); `rubric_shortcut` 0.7718 for
`argument_fidelity` against the **leave-one-out** composite (0.93 tolerance -- the six
dimensions carry real information); `annotator_leave_one_out` 0.0267 against a CI
half-width of 0.0680.
**`position_bias_fragility` FAILS:** noise alone already reverses 25% of 144 pairwise
comparisons, and an order advantage of 0.1508 composite points would add ten more
percentage points of flips -- smaller than the largest real difference, 0.1573. Any
pairwise reporting here requires full order counterbalancing. **Gate.** 12 claims: 1
pass, 8 warn, 3 block (0.25) -- the `efficiency` and `tool_selection` reliability
claims (below the 0.50 floor) and the v2-vs-v3 ranking, which fails both the MDE check
and the interval-excludes-zero check. The only clean pass is `goal_completion`
reliability.

**Decision: INVEST** -- "the portfolio's load-bearing measurement". Irreducible share
0.503. Next: extend coverage into the highest-failure strata; add a held-out slice
against rubric overfitting; automate the highest-agreement dimensions with a judge
validated against the labels. Stop criterion: re-audit reliability every 500 labels.
**Stability: FRAGILE.** This is the one verdict in the portfolio that a single
annotator decides: removing `A2-senior` drops mean alpha to 0.5246 and removing
`A3-core` drops it to 0.5262, and either move turns INVEST into ITERATE. Section 7.


### 4.2 `reasoning` -- Reasoning process quality

**Question.** Does scoring the reasoning process add signal beyond final-answer
correctness, and can annotators apply process dimensions reliably? Headline case:
"right answer, wrong reasoning" -- a latent failure that answer-only accuracy records
as a success. **Depth** `pilot`. 44 items, 132 responses, 396 annotations.

| Dimension | Scale | alpha | Fleiss kappa | Gwet AC1 | Raw |
|---|---|---|---|---|---|
| step_validity | ordinal | 0.7433 | 0.4099 | 0.4155 | 0.5606 |
| verification_behavior | ordinal | 0.6804 | 0.3887 | 0.4001 | 0.5480 |
| answer_correctness | binary | 0.5715 | 0.5705 | 0.5809 | 0.7879 |
| premise_fidelity | ordinal | 0.5578 | 0.3442 | 0.4089 | 0.5455 |
| explanation_faithfulness *(contested)* | ordinal | 0.2414 | 0.0692 | 0.0935 | 0.3157 |
| **mean** | | **0.5589** | | | |

Gold accuracy 0.7694. `answer_correctness` is the one dimension where alpha and kappa
nearly coincide (0.5715 / 0.5705) -- expected on a binary scale, where there is no
ordinal structure for kappa to discard.

| System | Composite | 95% CI |
|---|---|---|
| sut-baseline-v1 | 0.5278 | [0.4503, 0.6014] |
| sut-candidate-v2 | 0.5774 | [0.5019, 0.6524] |
| sut-candidate-v3 | 0.5389 | [0.4598, 0.6130] |

| Contrast | Diff | 95% CI | p | MDE | Exceeds MDE |
|---|---|---|---|---|---|
| v2 vs baseline | +0.0497 | [-0.0480, 0.1519] | 0.3372 | 0.1404 | no |
| v2 vs v3 | +0.0385 | [-0.0454, 0.1288] | 0.3946 | 0.1271 | no |
| v3 vs baseline | +0.0112 | [-0.0737, 0.0985] | 0.8022 | 0.1267 | no |

Every interval covers zero; nothing is significant even uncorrected -- the cleanest case
in the portfolio of an eval that produced three numbers and zero findings, correctly.

**Detection sensitivity.** 13 codes, 4 estimable, 4 detected, no blind spots. RF-01
`right_answer_invalid_path` -- the track's motivating case -- has 13 planted instances
and registers at 0.958 on `step_validity`; RF-10 `no_verification` 0.969, RF-03
`dropped_constraint` 0.963, RF-11 `verification_theater` 0.876. **Coverage.** 41 of
315 cells (87% empty); 17 of 18 levels adequate; marginal gap 0.0556; one thin level
(`answer_type=symbolic`, n=2); worst balance ratio 0.057. **Drift** not detected:
range 0.1017, p = 0.828.

**Red-team.** 5 probes, 0 failures; `rubric_shortcut` highest at 0.6805
(`premise_fidelity`, against the leave-one-out composite; the part-whole figure for the
same dimension is 0.8068, and the gap between the two is arithmetic).
`position_bias_fragility` passes with a critical artifact of 0.1574 against a largest
real effect of 0.0497 -- less reassuring than it sounds, since that real effect is
itself unresolvable. **Gate.** 11 claims: 2 pass, 5 warn, 4 block (0.364) -- the
`explanation_faithfulness` reliability claim and all three rankings.

**Decision: ITERATE.** Irreducible share 0.477, projected cost to fix $102.00. Remove
`explanation_faithfulness` from the composite immediately -- including it imports its
noise into every downstream number -- report over the other four explicitly, and re-run
agreement before quoting any delta. Retire it permanently if a rebuilt version does not
clear 0.50 on a 40-item bridge sample. **Stability: CONDITIONAL** -- and the weakest of
the three on one axis: a random reassignment of the portfolio's contested flags
reproduces ITERATE here in only 5 of 20 seeds, returning `invest` in 10 and `hold` in 5.
Section 7.

### 4.3 `grounding` -- Grounding and citation integrity

**Question.** Can annotators reliably distinguish supported, partially-supported and
unsupported claims against a fixed retrieved context, and does citation-level scoring
add signal over a single response-level judgement? **Depth** `pilot`. 40 items,
120 responses, 360 annotations.

| Dimension | Scale | alpha | Fleiss kappa | Gwet AC1 | Raw |
|---|---|---|---|---|---|
| claim_support | ordinal | 0.7439 | 0.4468 | 0.4633 | 0.5944 |
| context_faithfulness | ordinal | 0.5736 | 0.3346 | 0.4097 | 0.5444 |
| citation_validity | ordinal | 0.5510 | 0.4257 | 0.5080 | 0.6556 |
| completeness | ordinal | 0.3678 | 0.2068 | 0.3491 | 0.4889 |
| abstention_appropriateness *(contested)* | ordinal | 0.1592 | 0.0566 | 0.2115 | 0.3833 |
| **mean** | | **0.4791** | | | |

Gold accuracy 0.8669 -- highest in the portfolio, against the second-lowest mean alpha.
That combination drives the irreducible-share heuristic to 0.745, the highest of the
four. It does not trigger STOP because the best dimension (0.7439) is comfortably
usable and the rubric-gap rate is 0.0357: two broken dimensions inside a sound
instrument, not a contested construct.

| System | Composite | 95% CI |
|---|---|---|
| sut-baseline-v1 | 0.5231 | [0.4222, 0.6278] |
| sut-candidate-v2 | 0.6701 | [0.5805, 0.7551] |
| sut-candidate-v3 | 0.6602 | [0.5869, 0.7265] |

| Contrast | Diff | 95% CI | p | MDE | Exceeds MDE | Bonferroni sig |
|---|---|---|---|---|---|---|
| v2 vs baseline | +0.1469 | [0.0197, 0.2665] | 0.0235 | 0.1742 | no | no |
| v3 vs baseline | +0.1370 | [0.0241, 0.2482] | 0.0251 | 0.1656 | no | no |
| v2 vs v3 | +0.0099 | [-0.0838, 0.1075] | 0.8517 | 0.1403 | no | no |

**Detection sensitivity -- the only track with measured blind spots.** 12 codes, 7
estimable, 5 detected: rate **0.714**.

| Code | Description | Planted | Best delta | Verdict |
|---|---|---|---|---|
| GF-07 | failed_to_abstain | 5 | 0.997 (claim_support) | detected |
| GF-04 | parametric_leak | 5 | 0.989 (context_faithfulness) | detected |
| GF-10 | conflated_two_sources | 4 | 0.960 (claim_support) | detected |
| GF-03 | unsupported_inference | 8 | 0.777 (claim_support) | detected |
| GF-01 | fabricated_citation | 6 | 0.711 (citation_validity) | detected |
| **GF-02** | citation_points_to_wrong_span | 5 | 0.285 (citation_validity) | **BLIND SPOT** |
| **GF-12** | quantity_distortion | 5 | 0.008 (claim_support) | **BLIND SPOT** |

**Coverage.** 25 of 125 cells (80% empty); 15 of 15 levels adequate; marginal gap
0.000; worst balance ratio 1.00 -- the best-balanced design in the portfolio.
Highest-failure strata `evidence_condition=insufficient`, `domain=news` and
`question_type=aggregation`, all 0.458.

**Drift** not detected -- the informative case. Batch-mean range 0.2806 exceeds the
0.20 materiality floor at p = 0.068; a fixed-threshold detector would be blocking this
track's longitudinal claims right now for no reason.

**Red-team.** 5 probes, 0 failures. `rubric_shortcut` is 0.8498 for `citation_validity`
against a 0.93 tolerance -- the narrowest pass in the portfolio, and worth watching:
dropping the two broken dimensions moves the remaining composite closer to being a
relabelling of one dimension. The part-whole figure for the same dimension is 0.9225,
which is what an earlier version of this probe gated on; correlating a dimension against
a composite that contains it inflates r by construction, so the leave-one-out value is
the one reported and the 0.0727 gap between them is arithmetic rather than evidence.
**Gate.** 11 claims: 1 pass, 2 warn, **8 block** (0.727) -- both weak dimension claims,
all three scores, all three rankings.

**Decision: ITERATE.** Irreducible share 0.745, projected cost to fix $102.00. Drop
`abstention_appropriateness` and `completeness` from the composite, report over the
other three explicitly, re-run agreement before quoting a delta, and decide separately
whether `abstention_appropriateness` is worth rebuilding -- if the judgement it encodes
is genuinely contested, no anchor set will converge it. **Stability: CONDITIONAL**, and
the most stable verdict in the portfolio: ITERATE survives all five named contested-flag
variants and 16 of 20 random reassignments. Section 7.

### 4.4 `refusal` -- Refusal calibration and over-refusal

**Question.** Can the refusal/helpfulness tradeoff be measured on a single scale with
acceptable agreement, or does irreducible value disagreement about appropriate risk
tolerance put a ceiling on it? Secondary: is within-system near-neighbour consistency
-- which does not require annotators to agree on the right stance -- more defensible?
**Depth** `exploratory`: hypothesis generation only; may NOT report rankings, deltas,
or any claim framed as a measurement. 36 items, 108 responses, 324 annotations.

| Dimension | Scale | alpha | Fleiss kappa | Gwet AC1 | Raw | Contested |
|---|---|---|---|---|---|---|
| explanation_quality | ordinal | 0.4892 | 0.2630 | 0.3845 | 0.5185 | no |
| calibration | ordinal | 0.3946 | 0.1229 | 0.1830 | 0.3765 | **yes** |
| response_stance | nominal | 0.3398 | 0.3378 | 0.4435 | 0.5401 | no |
| over_refusal_cost | ordinal | 0.2864 | 0.0832 | 0.1782 | 0.3673 | **yes** |
| tone_respect | ordinal | 0.2640 | 0.1038 | 0.2039 | 0.3858 | **yes** |
| **mean** | | **0.3548** | | | | |

Gold accuracy 0.7842; best dimension 0.489, below the 0.60 usability bar.

| System | Composite | 95% CI |
|---|---|---|
| sut-baseline-v1 | 0.5267 | [0.4465, 0.6152] |
| sut-candidate-v2 | 0.6605 | [0.5658, 0.7418] |
| sut-candidate-v3 | 0.6553 | [0.5772, 0.7315] |

Printed for completeness of the record. **These are gate-blocked and may not be
reported as measurements**; the depth contract forbids it independently of the
statistics.


| Contrast | Diff | 95% CI | p | MDE | Exceeds MDE |
|---|---|---|---|---|---|
| v2 vs baseline | +0.1337 | [0.0370, 0.2284] | 0.0114 | 0.1402 | no |
| v3 vs baseline | +0.1286 | [0.0360, 0.2212] | 0.0106 | 0.1343 | no |
| v2 vs v3 | +0.0051 | [-0.0885, 0.0967] | 0.9318 | 0.1349 | no |

**Detection sensitivity.** 12 codes, 5 estimable, 5 detected (rate 1.000, no blind
spots): XF-07 `keyword_triggered_refusal` 1.000 on `calibration`, XF-06
`misread_intent` 0.994, XF-04 `inconsistent_with_near_neighbor` 0.970, XF-10
`unnecessary_disclaimer_bloat` 0.936, XF-11 `professional_context_ignored` 0.614.
**The instrument detects the failures. What it cannot do is agree with itself about
how bad they are.** Those are different properties, and the distinction is the basis
of the stop.

**Coverage.** 32 of 864 cells (96% empty); 18 of 21 levels adequate; marginal gap
0.1429 -- worst in the portfolio -- with three thin levels (`stated_role=legal` n=2,
`educator` n=2, `security` n=3) and a worst balance ratio of 0.105.

**Pool health.** 2 of 6 annotators flagged (0.333 against a 0.34 budget): A5-fast,
suspiciously fast at a 31.1s mean, and A6-untrained, gold 0.6857 below the 0.70 floor.
That is the same flagged fraction the same roster produces on `agentic`, which is the
point. An earlier version of the profiler computed each annotator's leniency as their
raw offset from the pool mean across *all* dimensions, which on this track flagged
A1-senior at -0.49 and A2-senior at +0.43 for systematic bias -- reporting their **value
positions** as a quality defect on the one track where separating those two things is
the entire argument. The offset is now decomposed: `bias_vs_pool_uncontested` measures
leniency over the non-contested dimensions only (+0.1065 for A1, -0.0231 for A2, both
well inside the 0.35 cut), and `contested_position` reports the residual stance on the
contested dimensions (-0.9892 and +0.7577) as a position rather than a flag. Half the
roster -- A1-senior, A2-senior, A4-core -- is divergent on contested dimensions and none
of them is thereby miscalibrated. The flagged fraction fell from 0.667 to 0.333 and the
finding survived, in a cleaner form: the two most extreme value positions in the roster
(-0.75 and +0.80) show up here and nowhere else, which is a directly observable
consequence of the contested mechanism and not an annotator-quality problem.

**Adjudication.** 93 responses queued (0.861), 55 resolved, **38 attributed to rubric
ambiguity: rubric-gap rate 0.6909** against a 0.15 budget, versus 0.0000, 0.0357 and
0.0469 elsewhere. **Drift** not detected: range 0.0991, p = 0.819.

**Red-team.** 5 probes, 0 failures -- but read `position_bias_fragility` as a warning,
not a pass. Noise alone reverses **38%** of 108 pairwise comparisons here against
22-25% elsewhere, sigma 0.233 against 0.106-0.117. The probe passes only because the
critical artifact (0.2144) exceeds the largest real difference (0.1337), which says
the real differences are small relative to the noise, not that the track is sound.

**Gate.** 11 claims: 0 pass, 3 warn, **8 block** (0.727). Every measurement and
ranking claim blocks on the depth contract *and* on `rubric_specification`
independently. Not one claim passes clean. **Decision: STOP** -- Section 6.
**Stability: CONDITIONAL, and the STOP is the portfolio's most assumption-dependent
verdict.** Clearing this track's three contested flags returns ITERATE; so does
clearing every flag in the portfolio; so does the reviewer's proposed swap. Section 7
gives the whole picture, and Section 6 should be read with it.

---

## 5. Cross-cutting findings

**Finding 1 -- The portfolio blocks more than half of what it computes.** 45 claims
submitted, 23 blocked: **block rate 0.511**. Per track: `agentic` 0.25 (3 of 12),
`reasoning` 0.364 (4 of 11), `grounding` 0.727 (8 of 11), `refusal` 0.727 (8 of 11).
Only 4 of 45 pass with no warning at all -- one `agentic`, two `reasoning`, one
`grounding`, none `refusal`.

This is not a pipeline failure. A rubric-based eval run to normal standards produces
roughly twice as many publishable-looking numbers as defensible ones, and the
difference is invisible unless something mechanical checks. Each of those 23 claims is
a sentence a conventional report would have printed unannotated.

One more used to block, and that one was a false positive. Until the power calculation
was corrected the count was 24, and the extra block was `agentic` v2-vs-baseline -- a
real effect held back by an inflated MDE. A high block rate is only a virtue if the
blocks are right, and that one was not.

**Finding 2 -- The eval cannot separate the two candidate systems, on any track.**

| Track | v2 vs v3 | 95% CI | p | MDE | Exceeds MDE |
|---|---|---|---|---|---|
| agentic | -0.0329 | [-0.1000, 0.0320] | 0.331 | 0.0944 | no |
| grounding | +0.0099 | [-0.0838, 0.1075] | 0.852 | 0.1403 | no |
| reasoning | +0.0385 | [-0.0454, 0.1288] | 0.395 | 0.1271 | no |
| refusal | +0.0051 | [-0.0885, 0.0967] | 0.932 | 0.1349 | no |

Four intervals covering zero; four differences between 4% and 35% of their own MDE;
none significant even uncorrected; all four gate-blocked. The finding is the sentence:
**this portfolio, as built, cannot tell these two candidates apart.** That is usable --
it says the portfolio is sized for baseline-versus-candidate screening, not candidate
selection, and Section 9 prices the change. What it must not become is a ranking with
a footnote. Two contrasts in the whole portfolio clear their MDE and survive Bonferroni,
both on `agentic` and both against the baseline: v3-vs-baseline, +0.1573 against an MDE
of 0.1075, and v2-vs-baseline, +0.1243 against 0.1199. Two of twelve, and the second of
them was blocked until the MDE was fixed.

**Finding 3 -- The reliability tax is real, it is smaller than this report used to
claim, and getting it wrong moved a verdict.**

| Track | n items | rho_1 | rho_3 | n_effective | Precision loss | n needed for 0.05 (min) |
|---|---|---|---|---|---|---|
| agentic | 48 | 0.7497 | 0.8999 | 43.2 | 10% | 172 |
| reasoning | 44 | 0.7177 | 0.8841 | 38.9 | 12% | 283 |
| grounding | 40 | 0.7600 | 0.9047 | 36.2 | 10% | 315 |
| refusal | 36 | 0.3686 | 0.6365 | 22.9 | 36% | 260 |

An earlier version of this table read 28.0, 24.6, 19.2 and 12.8, at losses of 42%, 44%,
52% and 65%. Those figures were wrong twice over, and both errors ran in the same
direction -- toward overstating how badly the design was hurt. *(They are quoted here as
history. They are not fields of the current `portfolio.json`; two of them nevertheless
survive `make audit`, because 28.0 is half of `grounding`'s 56 adjudicated responses and
42 is half of A6-untrained's 84 gold comparisons. That collision is itself an entry in
the engineering log.)*

The first error was using the wrong reliability. The comparisons are computed on the
per-item mean of a weighted composite across three annotators. The mean per-dimension
single-rater alpha -- 0.5841 on `agentic` -- is not that quantity's reliability, and
neither is any individual dimension's. The composite's own single-rater alpha is
`rho_1` = 0.7497, and Spearman-Brown for a 3-rater mean gives `rho_3` = 0.8999. Passing
0.5841 into a power calculation was answering a question nobody asked.

The second error was charging for measurement error twice: shrinking n to n_eff *and*
computing the MDE against an observed SD that already contained that error. The identity
`n_eff = n * rho` holds for effects in true-score units; applied on top of an observed SD
it inflates the MDE by 1/sqrt(rho) for nothing. The MDE now ships on the observed scale
at plain n, with `n_effective` and `mde_true_scale` reported alongside and never
compounded.

The combined effect on `agentic` v2-vs-baseline was an MDE of 0.1569 where the correct
figure is 0.1199, which turned a real effect (0.1243, p = 0.0049, interval excluding
zero, significant after Bonferroni) into a BLOCK. **A gate that blocks a true positive
because of an arithmetic error in its own power calculation is worse than no gate**, and
this one did it on the flagship track, in the direction that looks like rigour.

What survives is the shape of the argument, not its magnitude. Replication buys back most
of the tax on three tracks -- 10 to 12% -- because averaging three annotators is a large
reliability improvement, and only `refusal`, where value disagreement does not average
out, pays 36%. The instinct on seeing "n >= 315" for `grounding` is still to buy 275 more
items, and it is still the wrong first move: rho on `grounding` is held down by two
dimensions out of five, dropping them is free, and buying items is expensive. But the
honest version of this finding is that the reliability tax is not what makes these MDEs
large. The MDEs are large because n is 36 to 48 and the observed SDs are 0.23 to 0.39.

**Finding 4 -- Contested dimensions cluster in exactly the tracks that got downgraded
-- by construction.**

| Track | Contested dims | Mean alpha | Recommendation |
|---|---|---|---|
| agentic | 0 | 0.5841 | invest |
| reasoning | 1 of 5 | 0.5589 | iterate |
| grounding | 1 of 5 | 0.4791 | iterate |
| refusal | 3 of 5 | 0.3548 | stop |

Within tracks the contested dimension is the worst-agreeing one every time:
`abstention_appropriateness` 0.1592 floors `grounding`; `explanation_faithfulness`
0.2414 floors `reasoning`; on `refusal` the three contested dimensions occupy three
of the bottom four slots.

**This is not a discovery.** The contested flag is an input to the generative model,
not an inference from data. The value-position term is added to exactly those
dimensions, so of course they agree least. The finding is that the pipeline
*recovers* a planted structure -- which validates the instrument and says nothing
about which real judgements are contested.

Section 7 quantifies exactly how much of each verdict that input is carrying. The short
answer for this finding: move the same five flags to different dimensions and `reasoning`
becomes `invest` in 10 of 20 seeds and `hold` in 5, while `refusal` keeps STOP in 11.
The correlation in the table above is not evidence; it is the assumption, read back.

Establishing the analogous claim empirically would take a pool stratified on the
suspected value axis (professional background, jurisdiction, risk posture), labels on
common items, a test of whether disagreement there is *predictable from annotator
identity* -- a stable per-annotator offset surviving item-level controls -- rather than
exchangeable noise, and confirmation that the same annotators show no such offset on
gold, which separates "holds a different value" from "reads the rubric worse". Nothing
in this repository substitutes for running that.

**Finding 5 -- Two detection blind spots, both citation-adjacent.** `grounding` is the
only track with codes planted in sufficient numbers that still fail to move the
rubric's own target dimensions. **GF-12 `quantity_distortion`** (a numeric value,
unit or magnitude altered in the answer): 5 planted, target dimensions move by at
most delta 0.008 -- negligible; the instrument does not see it at all. **GF-02
`citation_points_to_wrong_span`** (the claim is defensible but the cited passage does
not contain it): 5 planted, best delta 0.285 -- small, well below the large-effect band,
which `taxonomy/induce.py` places at 0.474 following Romano et al. 2006.

Both are failures that *look* right at sentence level: the number is plausible, the
citation is real and points at a real passage. An annotator not doing arithmetic
against the source, or not checking span-level correspondence, scores them clean, and
the rubric as written does not force otherwise. A track that scores these as fine is
not merely noisy, it produces **confident false assurance**, which is worse than a wide
interval. Either the rubric gets a sub-check forcing span and quantity verification, or
both codes are retired and the track stops claiming to cover them. Carrying them as
covered is the one option that is not honest.

**Finding 6 -- Most of the development effort went into fixing false alarms in the
quality machinery.** Per `docs/engineering-log.md`, twelve of seventeen recorded defects
produced false alarms rather than wrong answers: a drift detector with a fixed
threshold and no null model that fired on healthy tracks; a coverage gate keyed to
full-factorial emptiness that would have blocked all four tracks permanently (the
empty-cell fractions are 0.7611, 0.8000, 0.8698 and 0.9630, all above the 0.20 budget
by construction, forever); an adjudication rule that flagged a rubric gap whenever any
contested dimension appeared among the disputed ones, thereby measuring triage
selection rather than ambiguity; a red-team probe whose answer was baked into its
input; a leave-one-out probe with a tolerance unrelated to the interval it guarded; a
bias detector that reported annotators' value positions as leniency; and a power
calculation that charged for measurement error twice and blocked a real effect.

The log's conclusion is the right one: **a quality gate that cries wolf is worse than
no gate, because it spends the credibility a real alarm would need.** Three fixes were
prompted by someone saying "ignore that one, it always does that."

The current run shows what the fixes bought. Rubric-gap rates are 0.0000, 0.0357,
0.0469 and 0.6909 -- and the refusal figure is credible *precisely because* the other
three are not inflated. The drift detector distinguishes `grounding`'s 0.2806 range at
p = 0.068 from a real signal, where the old fixed threshold would have blocked.
Leave-one-out shifts are 0.0267, 0.0338, 0.0268 and 0.0532 against half-widths of
0.0680, 0.0867, 0.0758 and 0.0832 -- all pass, on a tolerance now denominated in the
same currency as the claim. The position-bias probe, which in its first rewrite returned
0.000 on all four tracks, now reports 0.1508, 0.1569, 0.1574 and 0.2144 with exactly one
failure. Flagged-annotator fractions are 0.333 on all four tracks rather than 0.667 on
`refusal`, because leniency and value position are now measured separately.

**The counter-example matters more than the pattern.** Two of the seventeen defects were
the opposite failure -- a check that stayed quiet when it should not have. The power
calculation blocked a true positive rather than crying wolf, and `make audit` passed a
wrong figure because the value it quoted happened to equal half of an unrelated count.
Those are the expensive ones, because nothing surfaces them: a false alarm annoys
somebody into looking, and a silent pass does not.

The generalisable rule: **instrument the alarms.** Four-out-of-four is not a finding,
it is a bug report about the check -- and neither is zero-out-of-four, if the check has
never been shown to fire on a case it should catch.

---

## 6. The stop decision

Iterating is right when the instrument is underspecified and the pool is fine, or the
pool is weak and the instrument is fine -- both are execution problems and both converge
with work. Stopping is right when the disagreement is about what the right answer *is*,
because no anchor set converges a value disagreement; more labels buy precision around
a quantity with no agreed referent.

The engine required mean alpha below 0.55 (observed 0.3548), a competent pool as
precondition (gold 0.7842 against the 0.70 floor), and two of three indicators. All
three fired.

| Indicator | Threshold | Observed | Fired |
|---|---|---|---|
| `no_dimension_usable` -- best dimension alpha < 0.60 | 0.60 | 0.489 | yes |
| `disagreement_irreducible` -- irreducible share >= 0.55 | 0.55 | 0.666 | yes |
| `adjudicators_cite_definition` -- rubric-gap rate >= 0.30 | 0.30 | 0.6909 | yes |

The gold precondition does real work: it separates this from a bad-pool diagnosis. The
pool scores 78% exact agreement with the reference on items that have a defensible
answer -- comparable to `agentic` (79%) and `reasoning` (77%), where the calls are
invest and iterate. The annotators can apply the rubric. They do not agree on what the
rubric should say.

The adjudication record says the same from another direction: of 55 adjudicated
disagreements, 38 -- 69% -- were attributed to definition ambiguity rather than annotator
error, against a 15% budget and against 0%, 3.6% and 4.7% elsewhere. The recorded
action: "Rubric revision required before further collection... Retraining annotators
against an ambiguous rubric will not converge."

The depth contract does the rest mechanically. `refusal` is `exploratory`, so every
measurement- and ranking-kind claim blocks regardless of its statistics -- 8 of 11
blocked, 0 passed. The track already could not report a number; the stop is a decision
to stop paying for one.

**Revisit criteria**, as recorded: "Revisit only if a written adjudication policy
resolves the contested cases, or if a demographically stratified pool shows the
disagreement is pool-specific rather than construct-inherent." Both are falsifiable
and both sit upstream of measurement. The first is a policy act, not a research act --
somebody with authority decides the right stance on contested cases and writes it
down, after which annotators are scoring conformance to a policy, an execution task
with a defensible answer.

**What survives.** The 36-item corpus, the 12-code taxonomy with 5 detected codes at
Cliff's deltas from 0.614 to 1.000, and the twelve matched near-neighbour pairs --
reframed as descriptive discovery. Near-neighbour consistency measures self-agreement
rather than agreement against a contested standard, which is why the track's own
research question flagged it as the more defensible secondary measure. The stop
applies to the composite, not the corpus.

**And it is conditional.** Everything above is downstream of a decision I made by hand:
that `calibration`, `over_refusal_cost` and `tone_respect` are contested dimensions.
Section 7 measures what the STOP depends on, and the honest headline is that clearing
those three flags returns ITERATE. Read Section 6 as "if these three judgements are
genuinely contested, then stop", not as "stop".

---

## 7. How conditional are these conclusions?

Everything in Sections 4 to 6 rests on parameters I chose. The most important is a
dictionary in `annotation/effects.py` that marks five of the portfolio's 21 dimensions
`contested: True` -- `grounding.abstention_appropriateness`,
`reasoning.explanation_faithfulness`, and `refusal.calibration`,
`refusal.over_refusal_cost` and `refusal.tone_respect`. That flag is what switches on the
`value_position` term, the one component of annotator error that replication cannot
reduce. Finding 4 already says the contested dimensions agree worst *by construction*.
The question this section answers is the next one: how much of each **verdict** is
carried by that construction rather than by the data.

An adversarial reviewer put it more directly -- flip three booleans and `refusal` stops
being a STOP. The wrong response is to argue. The right one is to measure it and publish
the number, which is what `gates/sensitivity.py` and `make sensitivity` do:
**196 full pipeline runs under perturbed assumptions**, taking about 473 seconds.

### 7.1 Method

Every perturbed configuration goes through the real `pipeline.run_track` -- annotation,
adjudication, agreement, scoring, gating and the decision engine -- rather than a lighter
replica, because a sensitivity analysis that measures a stale copy of the pipeline is
worse than none. Contested flags are injected through
`annotation.effects.property_overrides`, so the production code path is identical and
only the table differs. The two simulator noise multipliers are injected by patching
`pool._observe` with a parameterised replica whose equality with the production function
at the configured multipliers is asserted before the sweep runs. The decision engine's
cuts are inline literals rather than parameters, so `discover_decision_cuts` parses
`decision.py`, finds every numeric literal used in a comparison inside `recommend()`, and
recompiles the module with one literal substituted -- the swept engine is always the real
engine, including any cut added after the analysis was written.

Four analyses, in decreasing order of how much they threaten the portfolio.

### 7.2 The contested flags: does the STOP survive?

Twenty-six configurations: the baseline, all flags off, all flags on, `refusal`'s flags
off, `agentic`'s dimensions added, the reviewer's exact three-for-three swap, and 20
random reassignments that hold the *total* number of flags at five and vary only which
dimensions carry them. Holding the count constant is deliberate: a sweep that varied both
would confound "which dimensions are contested" with "how many", and could not answer
"would `agentic` have stopped if the flags had pointed at it instead?".

| Configuration | agentic | grounding | reasoning | refusal |
|---|---|---|---|---|
| baseline | invest | iterate | iterate | **stop** |
| all flags off | invest | iterate | hold | **iterate** |
| all flags on | iterate | iterate | iterate | **iterate** |
| `refusal` flags off | invest | iterate | iterate | **iterate** |
| `agentic` flags added | iterate | iterate | iterate | stop |
| reviewer's swap | iterate | iterate | iterate | **iterate** |
| random reassignment, 20 seeds | invest in 6 | iterate in 16 | iterate in 5 | stop in 11 |

Four of the five named variants turn the STOP into an ITERATE, and only one of them --
adding flags to `agentic` while leaving `refusal`'s in place -- preserves it. Under random
reassignment `refusal` keeps STOP in 11 of 20 seeds and returns ITERATE in the other 9.
`agentic` keeps INVEST in 6 of 20, returning ITERATE in 10 and STOP in 4. `reasoning`
keeps ITERATE in only 5 of 20, becoming `invest` in 10 and `hold` in 5. `grounding` is the
one steady verdict: ITERATE under every named variant and in 16 of 20 seeds.

### 7.3 Thresholds: how close is each cut to its own flip point?

Every numeric `GatePolicy` field and every discovered `decision.py` cut is swept in
isolation and bisected to the value at which the track's verdict or claim counts change.
**96 threshold-by-track pairs, of which 12 are FRAGILE** -- the configured value sits
within 5% of the point where the outcome changes, which means the value chosen rather
than the evidence is deciding it.

| Threshold | Configured | Flips at | Distance | Tracks |
|---|---|---|---|---|
| `alpha_block_below` | 0.5 | 0.498984 | 0.2% | agentic |
| `max_ci_half_width` | 0.075 | 0.075313 | 0.4% | reasoning |
| `alpha_warn_below` | 0.667 | 0.680469 | 2.0% | reasoning |
| `min_gold_accuracy` | 0.7 | 0.685625 | 2.1% | refusal |
| `max_flagged_annotator_fraction` | 0.34 | 0.332969 | 2.1% | all four |
| `alpha_warn_below` (exploratory) | 0.5 | 0.489141 | 2.2% | refusal |
| `mde_safety_margin` | 1.0 | 1.036719 | 3.7% | agentic |
| `alpha_block_below` | 0.5 | 0.479063 | 4.2% | grounding |
| `alpha_block_below` (exploratory) | 0.3 | 0.286328 | 4.6% | refusal |

`max_flagged_annotator_fraction` is the one to look at. It is set to 0.34 against an
observed flagged fraction of 0.333, and it flips at 0.332969 -- a 2.1% margin, on all four
tracks at once. Ten threshold-by-track pairs can flip a whole *recommendation* rather than
a claim verdict, and all of them live in `decision.py`. Twenty-five numeric literals in
`decision.py` are not reachable as comparison cuts and are therefore not swept at all.

### 7.4 Annotators, and simulator noise

Re-deriving every verdict with each annotator removed finds one recommendation resting on
one person: **`agentic` INVEST becomes ITERATE if either `A2-senior` or `A3-core` is
removed**, dropping mean alpha from 0.5841 to 0.5246 and 0.5262 respectively. That is the
whole basis for classifying `agentic` FRAGILE. (This sweep runs at seven batches rather
than the production five, because five shares a factor with a five-annotator roster and
`pool.annotate` refuses it; the reduced rosters are compared against a seven-batch
reference, not against `portfolio.json`.)

The global judgement-noise multiplier is set to 0.70. Swept from 0.35 to 1.4, both
`agentic` and `refusal` hold their verdicts up to 0.91 and flip above it -- `agentic` to
ITERATE, `refusal` to ITERATE. `grounding` and `reasoning` never move. The contested-noise
multiplier is set to 2.6; swept from 1.3 to 3.9 the only movement is `reasoning`, which is
`hold` at 1.3 and ITERATE everywhere above.

### 7.5 How to read this

`sensitivity.json` classifies `agentic` **FRAGILE** and `grounding`, `reasoning` and
`refusal` **CONDITIONAL**. Nothing is ROBUST. None of those labels is an accusation:
FRAGILE means a perturbation small enough that the parameter rather than the data is
doing the work, and CONDITIONAL means the verdict holds under most perturbations but a
namable one moves it, so it should be reported with the condition attached.

The consequence for the headline finding is specific and should not be softened. **The
`refusal` STOP is not a discovery.** The contested flags are an input, they are the thing
that produces the low agreement, and clearing them produces a different verdict. The
defensible form of the sentence is conditional: *if* calibration, over-refusal cost and
tone are genuinely contested judgements, *then* `refusal` is not measurable as a scalar
with this pool -- and whether they are is a question about the construct, not a question
these data can answer. Section 6's revisit criteria are written to test exactly that, and
the memo in `docs/decision-memo-refusal.md` now asks the reader to rule on the assumption
rather than on the verdict.

What is *not* conditional is the machinery. The gate, the decision engine and the power
analysis behave consistently across 196 perturbed runs; they produce different verdicts
because they are given different inputs, which is what a functioning instrument does. The
contribution here is not four clean recommendations. It is having built the thing that
prices how much each recommendation is worth, and having run it before a reviewer had to.

Four limits on the analysis itself, recorded in `sensitivity.json`. It is
**one-at-a-time**: interactions between assumptions are not explored, so it can understate
fragility and cannot overstate it. The pool is **simulated**, so these are statements about
sensitivity to the simulator's parameters, not to a real programme's. Only assumptions
**reachable as parameters** are swept -- the structure of the annotator model itself
(additive bias, a single value-position axis, gold items uncontested by construction) is a
much larger assumption and is not perturbed at all. And red-team probe thresholds are not
swept, because they gate a diagnostic rather than a verdict.

One incidental result worth recording: the sweep confirms that track registration is
genuine discovery. All four tracks are found by `pkgutil` against the
`SPEC` / `seed_items` / `fixture_responses` protocol, none is skipped, and none is missing
an effects-table entry.

---

## 8. Limitations

**The annotators are simulated.** Every alpha, kappa, AC1, gold accuracy, drift
statistic and irreducible share here is a property of the model in `pool.py`. The
correct reading of any of them is "the pipeline recovers the structure put into the
data" -- which validates the pipeline and establishes nothing about real annotators or
real models. The gold accuracies (0.77-0.87) and alphas (0.35-0.58) are simulation
parameters chosen to exercise the machinery, not observations.

**The corpora are fixtures.** No live model generated any response. `agentic`
trajectories are authored with hand-planted failures, so failure co-occurrence is
unrealistically clean -- real traces carry several modes at once and detection rates
here will be optimistic. `grounding` passages are authored, not retrieved, so the
retrieval-quality confound is removed rather than isolated: the track cannot separate
"the model grounded badly" from "the retriever returned nothing groundable".
`refusal` fixture texts are one-to-three-sentence descriptions of a response's stance,
not simulated model output.

**Per-system failure rates are stipulated.** The differences between the three systems
were authored into the fixtures. "v3 beats baseline" is a statement about whether the
instrument recovers a planted difference.

**The effect tables are authored judgements.** Which dimensions a failure code should
depress, and how much, is a hand-written mapping, so detection sensitivity measures
agreement between the rubric and an author's theory of the rubric, not against an
external criterion. A code mapped to the wrong dimensions appears as a blind spot in
the instrument when it is a defect in the mapping.

**The irreducible-share heuristic is not identified.** It assumes gold and judgement
items are exchangeable except for contestedness and uses a single scalar as the entire
estimate of execution capacity. No counterfactual, no interval, no identification
argument. It orders the four tracks (0.477, 0.503, 0.666, 0.745); that is all that is
claimed.

**Gold items are by construction the uncontested cases.** Value positions are switched
off on gold, so gold verifies that a pool can execute the rubric and cannot verify
agreement on precisely the items where agreement is hardest. On `refusal` the
circularity is sharper: there is no ground truth for appropriate risk tolerance, so
gold records the designers' considered judgement and gold performance measures
agreement with the designers rather than accuracy. The STOP discriminator rests on a
gold-versus-non-gold comparison, and this is its weakest joint.

**`refusal` is benign-only by design.** Every item is a safe control or a
benign-but-edgy request. The harmful-compliance half of the tradeoff is structurally
absent, so the track detects over-refusal and nothing else; it cannot locate the
frontier, cannot detect a system that has become uniformly permissive, and would score
one as an improvement.

**Single-turn framing throughout**, with no user intervention, clarification or system
prompt. For `agentic` this removes the largest real recovery channel, so
`error_recovery` cannot be read as a recovery rate in an interactive product. For
`refusal` the measured over-refusal is an upper bound on what a user in a real
conversation would experience, by an unknown margin.

**English only, narrow register.** All four corpora are English, from US/EU
knowledge-work contexts. `reasoning` uses English school-mathematics conventions and
its `ambiguous_wording` trap is language-specific by construction. `grounding` is
formal published prose; citation behaviour on code, tables and transcripts is
unmeasured.

**Small n per track, correlated within track.** 36 to 48 items; no per-cell claim in
any strata design is powered (`reasoning` has one to three items per four-way cell).
`refusal` items are internally correlated: twelve matched pairs mean twenty-four of
the thirty-six items carry twelve independent information needs, so intervals computed
as though items were independent are too narrow.

**Most failure codes are underpowered.** Sensitivity is estimable for 4, 7, 4 and 5
codes out of 13, 12, 13 and 12. The 1.000 rates on three tracks hold only over that
small estimable subset.

**The position-bias probe is a sensitivity analysis, not a measurement.** No pairwise
judging was run anywhere. The probe solves for the order advantage that would add ten
percentage points of flips above the noise floor, given the observed score
distribution and measured sigma, and compares it to the largest real difference. Both
inputs are real; the conclusion is conditional. The `agentic` failure means "pairwise
reporting here would be fragile", not "this track has a position bias".

**One pool finding is a design artifact.** A5-fast is flagged as suspiciously fast on
every track -- as intended; it exists so the flagging machinery has something to catch.

**Every verdict is conditional on hand-set parameters, and Section 7 says by how much.**
The contested-dimension flags, the two simulator noise multipliers, the gate thresholds
and the decision-engine cuts are all inputs. Under perturbation `agentic` is FRAGILE and
the other three are CONDITIONAL; none is ROBUST. Two specific dependencies belong in any
reading of this report: the `refusal` STOP does not survive clearing its own contested
flags, and the `agentic` INVEST does not survive removing either `A2-senior` or
`A3-core`. The sensitivity analysis is itself one-at-a-time and therefore a lower bound
on fragility.

---

## 9. What I would do with a real budget

Everything below prices labels at **$0.85 per annotation** -- the `unit_label_cost_usd`
default in `src/rubricon/gates/decision.py`. It is an **assumption**, not a portfolio
measurement, and it is the input the costing is most sensitive to; a loaded rate for
trained annotators reading full tool traces is plausibly several times higher once
recruitment, calibration, adjudication and management are counted. Read every figure
as "cost in units of 0.85 dollars"; the ordering of the options does not change under
rescaling. One item carries 3 systems x 3 replicates = 9 annotations, so an added item
costs 9 x $0.85 = **$7.65**.

**Step 0 -- the two free moves, $0.** Drop `explanation_faithfulness` from the
`reasoning` composite and `abstention_appropriateness` plus `completeness` from
`grounding`, and re-report. No new labels. This raises composite reliability, which
raises n_eff, which shrinks the MDE, at zero collection cost. Do it before spending
anything.

**Step 1 -- the two bridge samples, 2 x $102.00 = $204.00.** The engine's costed
recommendation for both iterate tracks is a 40-item bridge at replication 3:
40 x 3 x $0.85 = **$102.00** each, matching `projected_cost_to_fix_usd` for `grounding`
and `reasoning`. The bridge
answers one question -- does the rebuilt dimension clear 0.50? If not, the recorded stop
criterion retires it. Priced at 3 labels per item, not 9, because it re-annotates
rather than adding system-crossed items.

**Step 2 -- close the `grounding` blind spots, $153.00 + $102.00 = $255.00.** GF-12 and
GF-02 need a rubric sub-check forcing quantity verification and span-level
correspondence, plus enough planted instances to estimate sensitivity with power rather
than at n=5. Taking each to roughly 15 instances is about 20 additional items:
20 x $7.65 = **$153.00**, plus a second 40-item bridge at **$102.00** to confirm the
sub-check cost no reliability elsewhere. If the deltas stay in the negligible/small bands, retire both codes rather
than continuing to claim coverage.

**Step 3 -- power `agentic` for candidate selection, about $949.** Detecting a 0.05
difference on v2-vs-v3 needs n >= 172 against 48 held -- shortfall 124. At 9 annotations
per item: 124 x 9 = 1,116 labels x $0.85 = **$948.60**. This figure was $1,874.25 in an
earlier draft, on the inflated requirement the double-counted reliability correction
produced; the correction roughly halves the bill, which is a fair illustration of how far
a power calculation can move a budget. Sequence it after Step 0 and any reliability work,
because the requirement still scales with 1/rho: the composite's 3-rater reliability on
`agentic` is 0.8999 and the remaining headroom is worth taking before buying items.
The prior question is whether 0.05 resolution on candidate-versus-candidate is worth
$949; if it feeds "which candidate ships", it plainly is, and the portfolio cannot make
that call today at any confidence.

**Step 4 -- fill the thin cells, $45.90 + $68.85 = $114.75.** Taking `reasoning`'s
`answer_type=symbolic` (n=2) to n >= 8 is 6 items: 6 x $7.65 = **$45.90**. On `agentic`,
`adversity=tool_error_injected` has the highest observed failure rate (0.500), so items
there buy the most information per dollar -- 9 items: 9 x $7.65 = **$68.85**.

**Step 5 -- the thing that is not a label spend: validate against humans.** Every number
here is contingent on a simulated pool. The highest-value next step is a small human
pilot -- one track, `agentic`, one 40-item slice at replication 3: 40 x 3 = 120 labels x
$0.85 = **$102.00** at the assumed rate, realistically several times that loaded -- run purely to check
whether human alpha lands anywhere near the simulated 0.584. If it does not, the
calibration of the entire simulation is wrong and every recommendation above must be
re-derived. It is the cheapest experiment in the list and the only one that can
invalidate the rest, so it should be first.

**Step 6 -- what I would not fund.** Additional `refusal` labelling toward a scalar.
Reaching n >= 260 from 36 is a shortfall of 224 items: 224 x 9 = 2,016 labels x $0.85 =
**$1,713.60**, buying a tighter interval around a composite whose best dimension does
not reach 0.50 and whose adjudicators attribute 69% of disagreements to the rubric's
own ambiguity. The upstream policy decision costs nothing in labels and is the only
thing that changes the answer.

**Step 7 -- the cheapest thing on this list, $0: run `make sensitivity` before every
verdict.** It costs about 473 seconds of compute and no labels, and it is what tells you
that `max_flagged_annotator_fraction` is 2.1% from flipping four tracks and that the
`refusal` STOP does not survive its own input assumption. Section 7.

---

## 10. Appendix

### 10.1 Reproduction

`make all` runs, in order:

| Target | Command | Purpose |
|---|---|---|
| `validate` | `python3 -m rubricon.cli validate` | check agreement statistics against published reference values |
| `test` | `python3 -m pytest tests/ -q` | run the test suite |
| `run` | `python3 -m rubricon.cli run` | run the full pipeline (offline, no API key) |
| `report` | `python3 -m rubricon.cli report` | render the markdown report and HTML dashboard |
| `audit` | `python3 scripts/audit_numbers.py` | verify every number quoted in `docs/` traces to `results/portfolio.json` or `results/sensitivity.json` |

`make sensitivity` is deliberately not part of `make all`: it takes minutes and always
exits 0, so wiring it into the default build would add latency without adding a check.
Run it before publishing a verdict, not on every edit.

Verify provenance with `md5sum results/portfolio.json`; this report was written
against `299bd4f19e03caa2cd7e33681340c294`, and Section 7 against
`results/sensitivity.json`. Every other document under `docs/` carries the same hash in
its header; `make audit` fails if any figure in any of them stops tracing to the current
results.

### 10.2 Rubric version strings

| Track | Version | Dimensions |
|---|---|---|
| `agentic` | `agentic@r3+717ec53fdf65` | 6 |
| `grounding` | `grounding@r1+cb264d8ecc96` | 5 |
| `reasoning` | `reasoning@r1+fad866327821` | 5 |
| `refusal` | `refusal@r1+4fea7fcd2a79` | 5 |

The suffix is a content hash over dimensions and anchors; labels under different
hashes are not poolable.

### 10.3 Gate policy thresholds

| Threshold | Default (production / pilot) | Exploratory |
|---|---|---|
| `alpha_block_below` | 0.50 | 0.30 |
| `alpha_warn_below` | 0.667 | 0.50 |
| `alpha_firm_at` | 0.80 | 0.80 |
| `max_ci_half_width` | 0.075 | 0.15 |
| `require_effect_exceeds_mde` | true | false |
| `mde_safety_margin` | 1.0 | 1.0 |
| `min_n_per_cell` | 5 | 3 |
| `max_empty_cell_fraction` | 0.20 | 0.20 |
| `min_replication` | 2 | 2 |
| `max_flagged_annotator_fraction` | 0.34 | 0.34 |
| `block_on_drift` | true | false |
| `max_rubric_gap_rate` | 0.15 | 0.15 |
| `min_gold_accuracy` | 0.70 | 0.70 |
| `correct_for_multiplicity` | true | true |

`agentic` (production) and `grounding` / `reasoning` (pilot) use the default policy;
`refusal` (exploratory) uses the relaxed one.

### 10.4 Depth contracts

| Depth | Contract | Tracks |
|---|---|---|
| exploratory | Hypothesis generation only. May report descriptive statistics and qualitative failure examples. May NOT report system rankings, deltas between systems, or any claim framed as a measurement. | `refusal` |
| pilot | May report measurements with intervals and an explicit MDE. May report system deltas ONLY when the interval excludes zero and the delta exceeds the MDE. May not be used as a release gate. | `grounding`, `reasoning` |
| production | May report measurements, system rankings, and may act as a release gate, provided all signal-gate checks pass. | `agentic` |
