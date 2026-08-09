# Task specification: agentic tool-use track

Track key: `agentic`
Rubric version: `agentic@r3+717ec53fdf65`
Depth tier: `production`
Status of this document: current. Reflects the run recorded in `results/portfolio.json`
(md5 299bd4f19e03caa2cd7e33681340c294). Re-running the pipeline changes these figures; check
the hash before quoting them. Statements about how far a verdict depends on a hand-set
parameter come from `results/sensitivity.json` (`make sensitivity`).

**Annotator provenance.** All labels behind every number in this document were produced by
the simulated annotator pool in `src/rubricon/annotation/pool.py`. No human labelled
anything. Agreement, bias, and gold-accuracy figures characterise that generative model,
not a real annotator pool. The measurement machinery is real and would run unchanged on
human labels; the findings are demonstrations, not empirical claims about language models.

**Provenance of numbers.** Results figures (agreement, coverage, intervals, power) come
from `results/portfolio.json`. Instrument structure (dimension weights, level counts,
failure-code list, declared strata) comes from `src/rubricon/tracks/agentic.py`. Threshold
values come from `GatePolicy` defaults in `src/rubricon/gates/signal.py`.

---

## 1. Purpose and the decision this informs

The track exists to answer two coupled questions: where multi-step tool-using agents break,
and which of those failure modes annotators can identify with agreement high enough to
support a release decision. The second half is not decoration. A failure taxonomy that
nobody applies consistently is a vocabulary, not a measurement.

The decision it feeds is a release gate: whether a candidate agent build may replace the
current baseline. The track is registered at `production` depth, whose contract is "may report
measurements, system rankings, and may act as a release gate, provided all signal-gate checks
pass." The qualifying clause does real work. In the current run 12 claims were submitted for
this track: 1 passed, 8 warned, 3 were blocked (block rate 0.25). One block is a ranking;
two are dimensions whose reliability fell below the blocking floor.

Secondary consumer: the failure-code counts feed a triage backlog for agent engineering.
That use is descriptive and survives even when a ranking claim is blocked.

## 2. Unit of analysis

One annotation covers **one agent trajectory -- the final message plus the full tool trace
-- on one task item, scored against all six rubric dimensions in a single sitting.**

Precisely:

- The unit is the *trajectory*, not the task and not the final message. The same task item
  scored on three different systems is three units.
- An annotator sees the final message first, then the tool trace, always in that order,
  and may revise after reading the trace. The rubric is deliberately built so several
  dimensions cannot be answered from the final message alone.
- All six dimensions are scored together. Partial annotations are not accepted; a
  dimension-at-a-time workflow would break the ordering rule in section 3 of the
  annotation guidelines.
- Failure codes are tagged on the same unit and are additive to the scores, not a
  substitute: the scores say how bad, the codes say what kind.
- The composite is a weighted mean over normalised dimension scores, with
  `argument_fidelity` critical-gated at 0.

Current corpus: 48 items, 3 systems, 144 responses, 432 annotations, mean replication 3.00
annotations per response.

## 3. Population and sampling frame

The target population is knowledge-work agent tasks with a tool catalog, a checkable end
state, and between two and roughly a dozen tool calls.

The realised frame is narrower and the gap is load-bearing:

- Trajectories are synthetic fixtures with hand-planted failures, not captured runs of a
  live agent. Failure co-occurrence is unrealistically clean; real traces routinely carry
  three failure modes at once.
- Every item is single-turn. The user states the task once and never intervenes.
- The tool catalog is stylised. Real catalogs carry dozens of near-duplicate tools with
  inconsistent argument naming.
- English only, US/EU knowledge-work scenarios (SaaS billing, engineering on-call,
  corporate travel).

Sampling is purposive within strata, not random from a production log. Nothing in this
corpus supports a base-rate claim about how often agents fail in the wild.

## 4. Stratification design

Four factors, 15 declared levels, 180 designed full-factorial cells. Realised marginal
counts over the 48 items:

| Factor | Level | Realised n | Observed failure rate |
|---|---|---|---|
| task_family | code_execution | 12 | 0.333 |
| task_family | data_lookup | 9 | 0.370 |
| task_family | file_ops | 9 | 0.370 |
| task_family | multi_api_orchestration | 9 | 0.222 |
| task_family | scheduling | 9 | 0.407 |
| horizon | short_2_3_steps | 9 | 0.407 |
| horizon | medium_4_6_steps | 18 | 0.352 |
| horizon | long_7_plus | 21 | 0.302 |
| adversity | clean | 12 | 0.194 |
| adversity | tool_error_injected | 12 | 0.500 |
| adversity | ambiguous_request | 12 | 0.361 |
| adversity | missing_precondition | 12 | 0.306 |
| side_effects | read_only | 12 | 0.389 |
| side_effects | reversible_write | 12 (see note) | 0.333 |
| side_effects | irreversible_write | 9 | 0.296 |

Note on `reversible_write`: its realised marginal is **27**, not 12. That is the single
worst balance in the design. Per-factor balance ratios (min level n divided by max level n)
are: adversity 1.000, task_family 0.750, horizon 0.429, side_effects 0.333.

Coverage verdict from the current run: 43 of 180 full-factorial cells populated
(76.1 percent empty); 15 of 15 declared levels populated at n >= 4; marginal gap fraction
0.000; worst balance ratio 0.333; no absent levels; no thin levels.

Full-factorial emptiness at 76 percent is expected and is not the governing figure.
Full-factorial coverage grows multiplicatively, so any hand-annotatable corpus is
overwhelmingly empty by construction, and gating on it would teach designers to declare
fewer factors. The operative check is marginal: a declared level with no data drops
silently out of every aggregate.

The `side_effects` imbalance has a direct reporting consequence. An unweighted mean over
this design is dominated by `reversible_write`. Report per-level breakdowns, or weighted
means, not the raw grand mean, whenever `side_effects` is the axis of interest.

## 5. Inclusion and exclusion criteria

Include an item if it has: a stated user goal that can be checked against an end state; a
declared tool catalog; a declared `expected_steps` count; and an assignment to exactly one
level of each of the four factors.

Exclude:

- Tasks whose success is a matter of taste (drafting, summarising, ranking) -- those belong
  to the open-ended-response track.
- Tasks scorable from the final message alone. If the trace adds nothing, the item is not
  measuring what this track measures.
- Trajectories that were truncated by harness failure rather than by agent decision. These
  are infrastructure noise and are dropped before annotation, not scored as incomplete.
- Any item soliciting operational harm content. Adversity here means injected tool errors,
  ambiguity, and missing preconditions -- not unsafe requests.

## 6. Replication and gold-item policy

Replication is 3 annotators per response, realised at mean 3.00. Assignment rotates the
annotator window by a stride of 1 over a fixed roster of 6, so every pair co-occurs and no
batch draws from a distinct sub-pool. A response's three annotations are deliberately
**split across batches** rather than kept together; that overlap is what makes the drift
statistic identifiable at all.

Gold rate is 0.15, giving 7 gold items of 48. Gold items are chosen roughly half from
trajectories carrying a planted failure and half from clean ones -- an all-failure gold set
trains annotators to hunt and inflates false positives on the live pool. Gold items are
spread by even stride through the corpus so they do not cluster where annotators are
freshest. Gold keys are defined relative to a specific reference trajectory
(`sut-baseline-v1`), because a "correct score" is only meaningful against a specific trace.

Gold accuracy in the current run: 0.7932 across the pool, against a pre-registered floor of
0.70 on the worst annotator. The worst annotator came in at 0.4881, which is below the floor
and produced a WARN, not a BLOCK, by policy.

## 7. What this eval does not measure

Stated generously, because every one of these has been read into an eval like this one:

- **Base rates.** No claim of the form "agents fail X percent of the time." The corpus is
  purposive and the adversity levels are imposed at 25 percent each by design.
- **Recovery in an interactive product.** Every item is single-turn, which removes the
  largest real recovery channel: a user noticing and correcting mid-run. `error_recovery`
  scores here are not recovery rates.
- **Real-catalog tool confusion.** The stylised catalog under-represents the near-duplicate
  tool names that drive AF-01 and AF-02 in production.
- **Cost, latency, or token efficiency.** `efficiency` counts redundant *calls* against the
  item's `expected_steps`. It says nothing about wall-clock or spend.
- **Safety.** `permission_overreach` (AF-11) is a scope judgement against the request, not
  a harm judgement. This track has no safety claim in it.
- **Multi-agent or human-in-the-loop settings.** Not represented at all.
- **Anything outside English / US-EU knowledge work.**
- **Separation of the two candidate systems.** Planted failure rates for v2 and v3 differ
  by 2 points, deliberately below the noise floor at n=48. Any ordering between them is to
  be reported as indistinguishable.
- **Detection sensitivity for 9 of 13 failure codes.** Only 4 codes (AF-04, AF-06, AF-08,
  AF-09) reached the 4-instance minimum for an estimable sensitivity, at 6, 4, 7 and 7 planted
  instances. The other 9 sit at 2-3 instances and are reported as underpowered, not as
  undetected. Conflating those two would blame the rubric for a sampling gap.
- **Pairwise or side-by-side judging.** See section 8: the fragility analysis says pairwise
  reporting on this track requires full order counterbalancing, which was not run.

## 8. Pre-registered analysis plan

The following were declared as `GatePolicy` defaults before results existed. They are data,
not code, so a reviewer can disagree with any of them and see exactly what changes.

| Quantity | Method | Pre-registered threshold |
|---|---|---|
| Reliability | Krippendorff alpha, ordinal metric, per dimension | BLOCK below 0.50; WARN below 0.667; firm at 0.800 |
| Kappa paradox check | Fleiss kappa and Gwet AC1 alongside raw agreement | diagnostic, no threshold |
| Precision | Cluster bootstrap over items, 2000 resamples | 95 percent CI half-width <= 0.075 |
| Ranking | Paired difference must exceed MDE and the CI must exclude zero | MDE safety margin 1.0 |
| Multiplicity | Bonferroni and Benjamini-Hochberg | applied; 2 tests, Bonferroni 0.025 |
| Coverage | Marginal level coverage, not full-factorial | no absent levels; marginal gap <= 0.20; min n per level 5 |
| Replication | Mean annotations per response | >= 2 |
| Pool health | Flagged-annotator fraction | <= 0.34 |
| Gold | Worst-annotator exact accuracy | >= 0.70 |
| Rubric gaps | Share of adjudications attributed to rubric ambiguity | <= 0.15 |
| Drift | Permutation test on batch-mean range, 2000 permutations | significant at 0.05 AND range >= 0.20 |
| Red team | 5 probes: length bias (0.30), lazy baseline (0.75), rubric shortcut (0.93), position-bias fragility (vs largest real effect), leave-one-out (vs reported CI half-width) | any failure caveats or withholds dependent findings |

Realised against those thresholds:

- Alpha by dimension: goal_completion 0.7193, error_recovery 0.6254, state_tracking 0.6181,
  argument_fidelity 0.5704, tool_selection 0.4990, efficiency 0.4721. Mean 0.5841, min 0.4721.
  One dimension passes, three warn, and **two block**: `tool_selection` and `efficiency` both
  fall below the 0.500 floor.
- System means: baseline 0.4610 [0.3906, 0.5302], v2 0.5853 [0.5158, 0.6550], v3 0.6182
  [0.5507, 0.6801]. CI half-widths 0.0698, 0.0696, 0.0646 (mean 0.068), inside the 0.075
  budget.
- Reliability: the quantity the rankings are computed on is the per-item mean of the
  weighted composite over 3 annotators, not any single dimension. Its single-rater
  reliability is rho_1 = 0.7497 and the Spearman-Brown value for the 3-rater mean is
  rho_3 = 0.8999. The reliability tax at that value is n_eff = 43.2 against n = 48, a
  10 percent precision loss. The MDE is reported on the observed scale at plain n, because
  the observed SD already contains the measurement error; `mde_true_scale` is reported
  separately and the two are never compounded. Detecting a 0.05 difference needs between
  n >= 172 and n >= 276 depending on the contrast, against the 48 in hand.
- Rankings: v3 vs baseline, difference 0.1573, CI [0.0851, 0.2313], permutation p = 0.0003,
  MDE 0.1075 -- exceeds MDE, WARN. v2 vs baseline, 0.1243, CI [0.0414, 0.2115], p = 0.0049,
  MDE 0.1199 -- exceeds MDE, WARN. v2 vs v3, -0.0329, CI [-0.1000, 0.0320] contains zero,
  MDE 0.0944 -- BLOCKED on both counts.
- **The v2-vs-baseline row was BLOCKED in an earlier run, on an MDE of 0.1569, and the
  block was an arithmetic error.** The power calculation was passing the mean
  per-dimension alpha (0.5841) in place of the composite's reliability *and* applying the
  n-to-n_eff shrinkage on top of an observed SD that already carried measurement error.
  The second of those inflates the MDE by 1/sqrt(rho) for nothing. A significant,
  adequately-powered effect was withheld by a gate doing exactly what it was told. See
  `docs/engineering-log.md`.
- Drift: batch-mean range 0.1003 across 5 batches, permutation p = 0.917, slope 0.0282 per
  batch. No drift.
- Adjudication: 118 of 144 responses queued (queue rate 0.819), 70 resolved (59.3 percent of
  the queue), 0 attributed to rubric ambiguity. Rubric-gap rate 0.000.
- Red team: 4 of 5 probes pass. `position_bias_fragility` fails: judgement noise alone
  (sigma 0.106) already reverses 25 percent of the 144 pairwise comparisons, and the order
  advantage that would add a further 10 percentage points of flips on top of that floor is
  0.1508 composite points against a largest real between-system effect of 0.1573. An artifact
  smaller than the real effect could reorder results. `rubric_shortcut` passes at 0.7718
  against a 0.93 tolerance. That statistic is each dimension's correlation with the
  **leave-one-out** composite -- the composite recomputed with that dimension's own weight
  zeroed -- and the worst offender is `argument_fidelity`. The part-whole figure, against a
  composite that includes the dimension itself, is 0.853 for `argument_fidelity` and 0.89 for
  `goal_completion`; part of that is arithmetic, since `goal_completion` carries the largest
  weight in the rubric and would correlate substantially with a composite containing it even
  if it were independent of every other dimension. The leave-one-out value is the one gated
  on, and the gap between the two is inflation, not evidence.

## 9. Promotion and re-certification criteria

The track currently sits at `production`. These criteria are not a one-time gate; they are
re-evaluated every run, and failing them demotes the reporting depth for that run.

To hold `production`:

1. Worst-dimension alpha >= 0.667 and mean alpha >= 0.667.
2. Mean CI half-width <= 0.075.
3. No absent declared strata levels; marginal gap fraction <= 0.20.
4. Mean replication >= 2; gold accuracy >= 0.70 pool-wide.
5. Rubric-gap rate <= 0.15.
6. No detected drift.
7. Zero failed red-team probes, or an explicit written withholding of every finding that
   depends on the failed mechanism.
8. Detection sensitivity estimable on at least half the declared failure codes.

Current standing: criteria 2, 3, 4, 5 and 6 hold. Criterion 1 does **not** -- five of six
dimensions sit below 0.667, and `tool_selection` (0.4990) and `efficiency` (0.4721) are below
the 0.500 blocking floor entirely. Criterion 7 does **not** -- `position_bias_fragility` fails
here, and `agentic` is the only track in the portfolio it fails on: this track's real
between-system effect is the largest in the portfolio, so it is the one an order artifact of
plausible size could actually reorder. Criterion 8 does **not** -- 4 of 13 codes are estimable.

The honest reading is that this track is production-depth for *scalar composite reporting
against a single baseline* and is not production-depth for pairwise or per-dimension ranking.
Two dimensions currently cannot be reported at all. The portfolio recommendation is `invest`,
with an estimated irreducible disagreement share of 0.503 -- about half the observed
disagreement is not attributable to demonstrated execution error and will not be fixed by
retraining.

**And that recommendation is FRAGILE.** `results/sensitivity.json` classifies this track's
INVEST as the least stable verdict in the portfolio, for one reason: removing either
`A2-senior` or `A3-core` from the roster turns it into ITERATE, dropping mean alpha to
0.5246 and 0.5262 respectively. A recommendation that rests on one annotator out of six is
a recommendation about the roster as much as about the instrument. Three further
dependencies are recorded there: marking this track's own dimensions contested turns
INVEST into ITERATE, a random reassignment of the portfolio's five contested flags
preserves INVEST in only 6 of 20 seeds, and a global judgement-noise multiplier above 0.91
flips it. Anyone quoting the `invest` verdict should quote the FRAGILE label with it.

Named next steps, in the order they buy the most:

1. Rebuild or drop `efficiency` (0.4721) and `tool_selection` (0.4990). Both are below the
   blocking floor, and including them imports their noise into the composite.
2. Extend coverage into `adversity=tool_error_injected`, which shows the highest failure rate
   at 0.500.
3. Raise planted-instance counts to at least 4 for the 9 underpowered failure codes.
4. Rebalance `side_effects` toward the 12/12/12 that `adversity` already achieves.
5. Either run counterbalanced pairwise judging or state permanently that this track does not
   produce pairwise results.
