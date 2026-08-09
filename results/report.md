# Rubricon results

> **SIMULATED ANNOTATORS. No human labels were collected. Agreement statistics characterise the generative annotator model in rubricon.annotation.pool, not real annotator behaviour. The measurement machinery is real; the findings are demonstrations, not empirical claims about language models.**

_Generated from `results/portfolio.json`. Do not edit by hand; re-run `make report`. Interpretation and argument live in `docs/research-report.md`._


## Portfolio

| metric | value |
|---|---|
| tracks | 4 |
| items | 168 |
| responses | 504 |
| annotations | 1512 |
| rubric dimensions | 21 |
| failure codes | 50 |
| claims submitted to the gate | 45 |
| claims blocked | 23 (51%) |

### Recommendations

| track | depth | mean alpha | band | gold accuracy | recommendation |
|---|---|---|---|---|---|
| agentic | production | 0.584 | below tentative | 0.793 | INVEST |
| grounding | pilot | 0.479 | BELOW BLOCK FLOOR | 0.867 | ITERATE |
| reasoning | pilot | 0.559 | below tentative | 0.769 | ITERATE |
| refusal | exploratory | 0.355 | BELOW BLOCK FLOOR | 0.784 | STOP |

---

## Agentic tool-use failure evaluation (`agentic`)

**Depth tier:** `production` - May report measurements, system rankings, and may act as a release gate, provided all signal-gate checks pass.

**Research question:** Where do multi-step tool-using agents break, and which of those failure modes can be identified by trained annotators with inter-annotator agreement high enough to support release decisions?

**Unit of analysis:** one agent trajectory (final message + full tool trace) on one task item

**Rubric version:** `agentic@r3+717ec53fdf65`

**Corpus:** 48 items, 144 responses, 432 annotations (mean replication 3.0).


### Reliability

| dimension | scale | alpha | 95% CI | band | raw agr. | Fleiss k | Gwet AC1 | contested |
|---|---|---|---|---|---|---|---|---|
| `efficiency` | ordinal | 0.472 | [0.360, 0.565] | BELOW BLOCK FLOOR | 0.440 | 0.214 | 0.265 |  |
| `tool_selection` | ordinal | 0.499 | [0.391, 0.603] | BELOW BLOCK FLOOR | 0.498 | 0.279 | 0.346 |  |
| `argument_fidelity` | ordinal | 0.570 | [0.470, 0.648] | below tentative | 0.523 | 0.320 | 0.378 |  |
| `state_tracking` | ordinal | 0.618 | [0.516, 0.693] | below tentative | 0.484 | 0.296 | 0.317 |  |
| `error_recovery` | ordinal | 0.625 | [0.537, 0.695] | below tentative | 0.495 | 0.308 | 0.333 |  |
| `goal_completion` | ordinal | 0.719 | [0.639, 0.777] | tentative | 0.444 | 0.301 | 0.307 |  |

Mean alpha 0.584, worst dimension 0.472, gold-item exact accuracy 0.793.


The alpha interval is a cluster bootstrap over responses. Where it does not exclude a policy threshold, the band above is a point estimate and not an established classification; the gate's check message says so per dimension.


**Reliability of the compared quantity.** The system comparisons are made on the per-item mean of the weighted composite over 3 annotators, so neither an individual dimension's alpha nor the mean of them is its reliability. The composite's own single-rater interval alpha is rho_1 = 0.750 [0.671, 0.816]; Spearman-Brown for the 3-rater mean gives rho_k = 0.900 [0.860, 0.930]. rho_k is what the power calculation consumes.


### Pool health

| check | value |
|---|---|
| flagged annotators | A5-fast, A6-untrained (33%) |
| drift | False (range 0.100, permutation p=0.9170) |
| adjudication queue | 118 queued, 70 resolved (59%) |
| rubric-gap rate | 0.0% |

### System scores

| system | n items | mean composite | 95% CI | CI half-width |
|---|---|---|---|---|
| sut-baseline-v1 | 48 | 0.4610 | [0.3906, 0.5302] | 0.0698 |
| sut-candidate-v2 | 48 | 0.5853 | [0.5158, 0.6550] | 0.0696 |
| sut-candidate-v3 | 48 | 0.6182 | [0.5507, 0.6801] | 0.0646 |

### Between-system comparisons

| contrast | effect | 95% CI | MDE (observed) | MDE (true-score) | exceeds MDE? | perm p | n_eff |
|---|---|---|---|---|---|---|---|
| sut-candidate-v2 vs sut-baseline-v1 | 0.1243 | [0.0414, 0.2115] | 0.1199 | 0.1264 | yes | 0.0049 | 43.2 |
| sut-candidate-v2 vs sut-candidate-v3 | -0.0329 | [-0.1000, 0.0320] | 0.0944 | 0.0995 | **NO - inside the noise floor** | 0.3310 | 43.2 |
| sut-candidate-v3 vs sut-baseline-v1 | 0.1573 | [0.0851, 0.2313] | 0.1075 | 0.1133 | yes | 0.0003 | 43.2 |

3 pre-registered contrasts; Bonferroni threshold 0.0167. Expected false positives at an uncorrected 0.05: 0.15.


**Reliability tax:** n=48 items at rho_k=0.900 carries the information of n_effective=43.2 perfectly-reliable items. That is an interpretive figure and is deliberately NOT fed back into the MDE: the SD in the MDE is the observed spread, which already contains the measurement error, so shrinking n to n_effective as well would charge for the same error twice. The MDE column is therefore the observed-scale figure at plain n, which is the one comparable to an observed effect. The true-score-scale figure, observed / sqrt(rho_k), is reported beside it.


### Failure detection

4/4 estimable codes detected (of 13 declared); mean coder recall 1.000. Blind spots: none.

| code | n planted | target dims | best delta | magnitude | detected | coder recall |
|---|---|---|---|---|---|---|
| AF-13 | 3 | error_recovery, goal_completion, state_tracking | 0.818 | large | underpowered | 1.00 |
| AF-12 | 3 | efficiency, goal_completion, state_tracking | 0.937 | large | underpowered | 1.00 |
| AF-10 | 2 | efficiency, goal_completion, state_tracking | 0.947 | large | underpowered | 1.00 |
| AF-11 | 3 | argument_fidelity, goal_completion, tool_selection | 0.958 | large | underpowered | 1.00 |
| AF-03 | 2 | argument_fidelity, goal_completion, state_tracking | 0.968 | large | underpowered | 1.00 |
| AF-07 | 3 | goal_completion, tool_selection | 0.972 | large | underpowered | 1.00 |
| AF-05 | 3 | efficiency, error_recovery | 0.993 | large | underpowered | 1.00 |
| AF-01 | 3 | argument_fidelity, goal_completion, tool_selection | 1.000 | large | underpowered | 1.00 |
| AF-02 | 3 | argument_fidelity, goal_completion | 1.000 | large | underpowered | 1.00 |
| AF-08 | 7 | error_recovery, goal_completion, state_tracking | 0.671 | large | yes | 1.00 |
| AF-09 | 7 | goal_completion, state_tracking | 0.959 | large | yes | 1.00 |
| AF-04 | 6 | error_recovery, goal_completion | 0.968 | large | yes | 1.00 |
| AF-06 | 4 | goal_completion, state_tracking | 0.968 | large | yes | 1.00 |

### Coverage

15/15 declared strata levels reach n>=4 (marginal gap 0.0%); worst-factor balance ratio 0.33. Full-factorial: 43/180 cells populated, which is expected and not the operative metric.


### Red-team probes

| probe | statistic | threshold | result |
|---|---|---|---|
| length_bias | -0.2261 | 0.3000 | pass |
| lazy_baseline | 0.3981 | 0.7500 | pass |
| rubric_shortcut | 0.7718 | 0.9300 | pass |
| position_bias_fragility | 0.1508 | 0.1573 | **FAIL** |
| annotator_leave_one_out | 0.0267 | 0.0680 | pass |

- **position_bias_fragility**: Judgement noise alone (sigma=0.106) already reverses 25% of 144 pairwise comparisons. An order advantage of 0.151 composite points would add a further 10 percentage points of flips on top of that floor. The largest real between-system difference on this track is 0.157, which is LARGER than the artifact needed to reorder results, so pairwise reporting here requires full order counterbalancing.


### Signal gate

1 pass, 8 warn, **3 blocked** of 12 claims.


Withheld claims:


- ~~Dimension 'efficiency' of the Agentic tool-use failure evaluation rubric produces reliable measurements.~~

  - BLOCKED: alpha=0.472 is below the blocking floor of 0.500. Annotators are not measuring the same construct. UNCERTAINTY: the 95% bootstrap interval for alpha [0.360, 0.565] does not exclude 0.500, so which side of that threshold this dimension falls on is NOT established by these data; the classification is a point estimate, not a finding.

- ~~Dimension 'tool_selection' of the Agentic tool-use failure evaluation rubric produces reliable measurements.~~

  - BLOCKED: alpha=0.499 is below the blocking floor of 0.500. Annotators are not measuring the same construct. UNCERTAINTY: the 95% bootstrap interval for alpha [0.391, 0.603] does not exclude 0.500, so which side of that threshold this dimension falls on is NOT established by these data; the classification is a point estimate, not a finding.

- ~~sut-candidate-v2 underperforms sut-candidate-v3 on Agentic tool-use failure evaluation by 0.033 composite points.~~

  - BLOCKED: Observed effect 0.0329 is BELOW the minimum detectable effect 0.0944.

  - BLOCKED: 95% CI [-0.1000, 0.0320] CONTAINS zero.



### Decision: **INVEST**

Continue investing in 'agentic'; it is the portfolio's load-bearing measurement.


**Rationale**


- Mean alpha across dimensions 0.584 (worst dimension 0.472); gold accuracy 79%.

- 95% CI half-width 0.068; MDE 0.094; largest observed between-system effect 0.157.

- Reliability, coverage, and power all clear their thresholds; the measurement supports the claims being made on it.

- Detection sensitivity on planted failures is 100%: the eval finds the failures it was designed to find.


**Next actions**


- Extend coverage into the strata with the highest observed failure rates.

- Add a held-out slice to guard against overfitting the rubric to known failures.

- Automate the highest-agreement dimensions with an LLM judge validated against the human labels, reserving human effort for the contested ones.


**Stop criteria**


- Re-audit reliability every 500 labels; drift invalidates longitudinal claims.



**Where the next collection budget should go**


- COLLECT: only 3 instances of AF-13; sensitivity is not estimable.

- COLLECT: only 3 instances of AF-12; sensitivity is not estimable.

- COLLECT: only 2 instances of AF-10; sensitivity is not estimable.

- COLLECT: only 3 instances of AF-11; sensitivity is not estimable.

- COLLECT: only 2 instances of AF-03; sensitivity is not estimable.

- COLLECT: only 3 instances of AF-07; sensitivity is not estimable.

- COLLECT: only 3 instances of AF-05; sensitivity is not estimable.

- COLLECT: only 3 instances of AF-01; sensitivity is not estimable.

- COLLECT: only 3 instances of AF-02; sensitivity is not estimable.

- EXPAND: adversity=tool_error_injected shows the highest failure rate (50%); this is where additional items buy the most information.



**Known limitations of this track**


- Trajectories in this corpus are synthetic fixtures with hand-planted failures, not captured runs of a live agent. Failure co-occurrence is therefore unrealistically clean: real traces routinely carry three failure modes at once, and detection rates measured here will be optimistic relative to production traces.

- Every item is a single-turn framing: the user states the task once and never intervenes. This removes the largest real-world recovery channel (the user noticing and correcting mid-run), so error_recovery scores here cannot be read as recovery rates in an interactive product.

- The tool catalog is stylised. Real catalogs have dozens of near-duplicate tools with inconsistent argument naming, which is a major driver of AF-01 and AF-02 in production and is under-represented here by construction.

- English only, and all scenarios are drawn from US/EU knowledge-work contexts (SaaS billing, engineering on-call, corporate travel). Nothing in this corpus speaks to agent behaviour in other languages or operational cultures.

- n=48 items x 3 systems is sized to exercise the pipeline and to estimate agreement, not to separate the two candidate systems. The planted rates for v2 and v3 differ by 2 points, which is well below the minimum detectable effect at this n; any observed ordering between them should be reported as indistinguishable.



---

## Grounding and citation integrity (`grounding`)

**Depth tier:** `pilot` - May report measurements with intervals and an explicit MDE. May report system deltas ONLY when the interval excludes zero and the delta exceeds the MDE. May not be used as a release gate.

**Research question:** Can annotators reliably distinguish supported, partially-supported and unsupported claims against a fixed retrieved context, and does citation-level scoring add signal over a single response-level grounding judgement?

**Unit of analysis:** one generated answer with its citation set, judged against a fixed retrieved context

**Rubric version:** `grounding@r1+cb264d8ecc96`

**Corpus:** 40 items, 120 responses, 360 annotations (mean replication 3.0).


### Reliability

| dimension | scale | alpha | 95% CI | band | raw agr. | Fleiss k | Gwet AC1 | contested |
|---|---|---|---|---|---|---|---|---|
| `abstention_appropriateness` | ordinal | 0.159 | [0.041, 0.275] | BELOW BLOCK FLOOR | 0.383 | 0.057 | 0.211 | yes |
| `completeness` | ordinal | 0.368 | [0.250, 0.469] | BELOW BLOCK FLOOR | 0.489 | 0.207 | 0.349 |  |
| `citation_validity` | ordinal | 0.551 | [0.427, 0.661] | below tentative | 0.656 | 0.426 | 0.508 |  |
| `context_faithfulness` | ordinal | 0.574 | [0.436, 0.673] | below tentative | 0.544 | 0.335 | 0.410 |  |
| `claim_support` | ordinal | 0.744 | [0.656, 0.813] | tentative | 0.594 | 0.447 | 0.463 |  |

Mean alpha 0.479, worst dimension 0.159, gold-item exact accuracy 0.867.


The alpha interval is a cluster bootstrap over responses. Where it does not exclude a policy threshold, the band above is a point estimate and not an established classification; the gate's check message says so per dimension.


**Reliability of the compared quantity.** The system comparisons are made on the per-item mean of the weighted composite over 3 annotators, so neither an individual dimension's alpha nor the mean of them is its reliability. The composite's own single-rater interval alpha is rho_1 = 0.760 [0.669, 0.835]; Spearman-Brown for the 3-rater mean gives rho_k = 0.905 [0.859, 0.938]. rho_k is what the power calculation consumes.


### Pool health

| check | value |
|---|---|
| flagged annotators | A5-fast, A6-untrained (33%) |
| drift | False (range 0.281, permutation p=0.0680) |
| adjudication queue | 94 queued, 56 resolved (60%) |
| rubric-gap rate | 3.6% |

### System scores

| system | n items | mean composite | 95% CI | CI half-width |
|---|---|---|---|---|
| sut-baseline-v1 | 40 | 0.5231 | [0.4222, 0.6278] | 0.1028 |
| sut-candidate-v2 | 40 | 0.6701 | [0.5805, 0.7551] | 0.0873 |
| sut-candidate-v3 | 40 | 0.6602 | [0.5869, 0.7265] | 0.0698 |

### Between-system comparisons

| contrast | effect | 95% CI | MDE (observed) | MDE (true-score) | exceeds MDE? | perm p | n_eff |
|---|---|---|---|---|---|---|---|
| sut-candidate-v2 vs sut-baseline-v1 | 0.1469 | [0.0197, 0.2665] | 0.1742 | 0.1832 | **NO - inside the noise floor** | 0.0235 | 36.2 |
| sut-candidate-v2 vs sut-candidate-v3 | 0.0099 | [-0.0838, 0.1075] | 0.1403 | 0.1475 | **NO - inside the noise floor** | 0.8517 | 36.2 |
| sut-candidate-v3 vs sut-baseline-v1 | 0.1370 | [0.0241, 0.2482] | 0.1656 | 0.1741 | **NO - inside the noise floor** | 0.0251 | 36.2 |

3 pre-registered contrasts; Bonferroni threshold 0.0167. Expected false positives at an uncorrected 0.05: 0.15.


**Reliability tax:** n=40 items at rho_k=0.905 carries the information of n_effective=36.2 perfectly-reliable items. That is an interpretive figure and is deliberately NOT fed back into the MDE: the SD in the MDE is the observed spread, which already contains the measurement error, so shrinking n to n_effective as well would charge for the same error twice. The MDE column is therefore the observed-scale figure at plain n, which is the one comparable to an observed effect. The true-score-scale figure, observed / sqrt(rho_k), is reported beside it.


### Failure detection

5/7 estimable codes detected (of 12 declared); mean coder recall 1.000. Blind spots: GF-12, GF-02.

| code | n planted | target dims | best delta | magnitude | detected | coder recall |
|---|---|---|---|---|---|---|
| GF-12 | 5 | citation_validity, claim_support | 0.008 | negligible | **NO** | 1.00 |
| GF-09 | 2 | claim_support, completeness, context_faithfulness | 0.240 | small | underpowered | 1.00 |
| GF-02 | 5 | citation_validity, claim_support | 0.285 | small | **NO** | 1.00 |
| GF-08 | 2 | abstention_appropriateness, completeness | 0.467 | medium | underpowered | 1.00 |
| GF-05 | 1 | claim_support, context_faithfulness | 0.987 | large | underpowered | 1.00 |
| GF-06 | 1 | claim_support, context_faithfulness | 1.000 | large | underpowered | 1.00 |
| GF-11 | 1 | citation_validity, claim_support, context_faithfulness | 1.000 | large | underpowered | 1.00 |
| GF-01 | 6 | citation_validity, claim_support | 0.711 | large | yes | 1.00 |
| GF-03 | 8 | claim_support, context_faithfulness | 0.777 | large | yes | 1.00 |
| GF-10 | 4 | citation_validity, claim_support, context_faithfulness | 0.960 | large | yes | 1.00 |
| GF-04 | 5 | claim_support, context_faithfulness | 0.989 | large | yes | 1.00 |
| GF-07 | 5 | abstention_appropriateness, claim_support | 0.997 | large | yes | 1.00 |

### Coverage

15/15 declared strata levels reach n>=4 (marginal gap 0.0%); worst-factor balance ratio 1.00. Full-factorial: 25/125 cells populated, which is expected and not the operative metric.


### Red-team probes

| probe | statistic | threshold | result |
|---|---|---|---|
| length_bias | -0.0890 | 0.3000 | pass |
| lazy_baseline | 0.4972 | 0.7500 | pass |
| rubric_shortcut | 0.8498 | 0.9300 | pass |
| position_bias_fragility | 0.1569 | 0.1469 | pass |
| annotator_leave_one_out | 0.0338 | 0.0867 | pass |

### Signal gate

1 pass, 2 warn, **8 blocked** of 11 claims.


Withheld claims:


- ~~Dimension 'abstention_appropriateness' of the Grounding and citation integrity rubric produces reliable measurements.~~

  - BLOCKED: alpha=0.159 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

- ~~Dimension 'completeness' of the Grounding and citation integrity rubric produces reliable measurements.~~

  - BLOCKED: alpha=0.368 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

- ~~sut-baseline-v1 scores 0.523 [0.422, 0.628] on Grounding and citation integrity.~~

  - BLOCKED: alpha=0.479 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

- ~~sut-candidate-v2 scores 0.670 [0.581, 0.755] on Grounding and citation integrity.~~

  - BLOCKED: alpha=0.479 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

- ~~sut-candidate-v3 scores 0.660 [0.587, 0.727] on Grounding and citation integrity.~~

  - BLOCKED: alpha=0.479 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

- ~~sut-candidate-v2 outperforms sut-baseline-v1 on Grounding and citation integrity by 0.147 composite points.~~

  - BLOCKED: Track depth 'pilot' does NOT permit a 'ranking' claim.

  - BLOCKED: alpha=0.479 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

  - BLOCKED: Observed effect 0.1469 is BELOW the minimum detectable effect 0.1742.

- ~~sut-candidate-v2 outperforms sut-candidate-v3 on Grounding and citation integrity by 0.010 composite points.~~

  - BLOCKED: Track depth 'pilot' does NOT permit a 'ranking' claim.

  - BLOCKED: alpha=0.479 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

  - BLOCKED: Observed effect 0.0099 is BELOW the minimum detectable effect 0.1403.

  - BLOCKED: 95% CI [-0.0838, 0.1075] CONTAINS zero.

- ~~sut-candidate-v3 outperforms sut-baseline-v1 on Grounding and citation integrity by 0.137 composite points.~~

  - BLOCKED: Track depth 'pilot' does NOT permit a 'ranking' claim.

  - BLOCKED: alpha=0.479 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

  - BLOCKED: Observed effect 0.1370 is BELOW the minimum detectable effect 0.1656.



### Decision: **ITERATE**

Drop or rebuild the failing dimension(s) of 'grounding'; keep the rest.


**Rationale**


- Mean alpha across dimensions 0.479 (worst dimension 0.159); gold accuracy 87%.

- 95% CI half-width 0.087; MDE 0.140; largest observed between-system effect 0.147.

- Reliability is not uniform: 3 dimension(s) reach usable agreement while 2 sit below 0.40 (abstention_appropriateness=0.16, completeness=0.37). This is a dimension-level defect, not a failure of the construct.


**Next actions**


- Remove abstention_appropriateness, completeness from the reported composite immediately -- including them imports their noise into every downstream number.

- Report the composite over claim_support, citation_validity, context_faithfulness only, and say so explicitly.

- Decide separately whether abstention_appropriateness is worth rebuilding: if the judgement it encodes is genuinely contested, no anchor set will converge it.

- Re-run agreement on the reduced composite before quoting any system delta.


**Stop criteria**


- Retire abstention_appropriateness permanently if a rebuilt version does not clear 0.50 on a 40-item bridge sample.


Projected remediation cost: $102.00 (at the documented unit label cost assumption).




**Where the next collection budget should go**


- INSTRUMENT: failure code GF-12 is planted but not registered by any rubric dimension; sharpen the rubric or retire the code.

- INSTRUMENT: failure code GF-02 is planted but not registered by any rubric dimension; sharpen the rubric or retire the code.

- COLLECT: only 2 instances of GF-09; sensitivity is not estimable.

- COLLECT: only 2 instances of GF-08; sensitivity is not estimable.

- COLLECT: only 1 instances of GF-05; sensitivity is not estimable.

- COLLECT: only 1 instances of GF-06; sensitivity is not estimable.

- COLLECT: only 1 instances of GF-11; sensitivity is not estimable.

- EXPAND: domain=news shows the highest failure rate (46%); this is where additional items buy the most information.

- EXPAND: evidence_condition=insufficient shows the highest failure rate (46%); this is where additional items buy the most information.

- EXPAND: question_type=aggregation shows the highest failure rate (46%); this is where additional items buy the most information.



**Known limitations of this track**


- Passages are authored for the eval, not retrieved by a real retriever. Evidence conditions are therefore clean by construction, which is exactly what makes them measurable and exactly why grounding rates measured here will not transfer to a production corpus.

- Contexts are 2-4 short passages. Production RAG contexts run to thousands of tokens across many chunks, where attention dilution and mid-context loss dominate. Nothing here probes that regime.

- The retrieval-quality confound is removed rather than isolated. Because the retriever is not in the loop, this track cannot separate 'the model grounded badly' from 'the retriever returned nothing groundable', and results must not be quoted as end-to-end RAG quality.

- English only, and written in a register close to formal published prose. Citation behaviour on code, tables, non-English sources and conversational transcripts is unmeasured.

- Fixture responses carry planted failures generated from templates. They are adequate for measuring annotator detection sensitivity and rubric coverage; they are not a sample of any real system's error distribution, and the per-system rates below are stipulated, not observed.



---

## Reasoning process quality (`reasoning`)

**Depth tier:** `pilot` - May report measurements with intervals and an explicit MDE. May report system deltas ONLY when the interval excludes zero and the delta exceeds the MDE. May not be used as a release gate.

**Research question:** Does scoring the reasoning process add signal beyond final-answer correctness, and can annotators apply process dimensions reliably? The headline case is 'right answer, wrong reasoning': a model that reaches the correct result through an invalid derivation is a latent failure that answer-only accuracy records as a success.

**Unit of analysis:** one worked solution, scored on both outcome and process

**Rubric version:** `reasoning@r1+fad866327821`

**Corpus:** 44 items, 132 responses, 396 annotations (mean replication 3.0).


### Reliability

| dimension | scale | alpha | 95% CI | band | raw agr. | Fleiss k | Gwet AC1 | contested |
|---|---|---|---|---|---|---|---|---|
| `explanation_faithfulness` | ordinal | 0.241 | [0.117, 0.336] | BELOW BLOCK FLOOR | 0.316 | 0.069 | 0.093 | yes |
| `premise_fidelity` | ordinal | 0.558 | [0.447, 0.656] | below tentative | 0.545 | 0.344 | 0.409 |  |
| `answer_correctness` | binary | 0.572 | [0.461, 0.674] | below tentative | 0.788 | 0.571 | 0.581 |  |
| `verification_behavior` | ordinal | 0.680 | [0.593, 0.750] | tentative | 0.548 | 0.389 | 0.400 |  |
| `step_validity` | ordinal | 0.743 | [0.667, 0.803] | tentative | 0.561 | 0.410 | 0.415 |  |

Mean alpha 0.559, worst dimension 0.241, gold-item exact accuracy 0.769.


The alpha interval is a cluster bootstrap over responses. Where it does not exclude a policy threshold, the band above is a point estimate and not an established classification; the gate's check message says so per dimension.


**Reliability of the compared quantity.** The system comparisons are made on the per-item mean of the weighted composite over 3 annotators, so neither an individual dimension's alpha nor the mean of them is its reliability. The composite's own single-rater interval alpha is rho_1 = 0.718 [0.628, 0.796]; Spearman-Brown for the 3-rater mean gives rho_k = 0.884 [0.835, 0.921]. rho_k is what the power calculation consumes.


### Pool health

| check | value |
|---|---|
| flagged annotators | A5-fast, A6-untrained (33%) |
| drift | False (range 0.102, permutation p=0.8281) |
| adjudication queue | 108 queued, 64 resolved (59%) |
| rubric-gap rate | 4.7% |

### System scores

| system | n items | mean composite | 95% CI | CI half-width |
|---|---|---|---|---|
| sut-baseline-v1 | 44 | 0.5278 | [0.4503, 0.6014] | 0.0756 |
| sut-candidate-v2 | 44 | 0.5774 | [0.5019, 0.6524] | 0.0752 |
| sut-candidate-v3 | 44 | 0.5389 | [0.4598, 0.6130] | 0.0766 |

### Between-system comparisons

| contrast | effect | 95% CI | MDE (observed) | MDE (true-score) | exceeds MDE? | perm p | n_eff |
|---|---|---|---|---|---|---|---|
| sut-candidate-v2 vs sut-baseline-v1 | 0.0497 | [-0.0480, 0.1519] | 0.1404 | 0.1494 | **NO - inside the noise floor** | 0.3372 | 38.9 |
| sut-candidate-v2 vs sut-candidate-v3 | 0.0385 | [-0.0454, 0.1288] | 0.1271 | 0.1351 | **NO - inside the noise floor** | 0.3946 | 38.9 |
| sut-candidate-v3 vs sut-baseline-v1 | 0.0112 | [-0.0737, 0.0985] | 0.1267 | 0.1347 | **NO - inside the noise floor** | 0.8022 | 38.9 |

3 pre-registered contrasts; Bonferroni threshold 0.0167. Expected false positives at an uncorrected 0.05: 0.15.


**Reliability tax:** n=44 items at rho_k=0.884 carries the information of n_effective=38.9 perfectly-reliable items. That is an interpretive figure and is deliberately NOT fed back into the MDE: the SD in the MDE is the observed spread, which already contains the measurement error, so shrinking n to n_effective as well would charge for the same error twice. The MDE column is therefore the observed-scale figure at plain n, which is the one comparable to an observed effect. The true-score-scale figure, observed / sqrt(rho_k), is reported beside it.


### Failure detection

4/4 estimable codes detected (of 13 declared); mean coder recall 1.000. Blind spots: none.

| code | n planted | target dims | best delta | magnitude | detected | coder recall |
|---|---|---|---|---|---|---|
| RF-12 | 1 | answer_correctness, step_validity | -0.549 | large | underpowered | 1.00 |
| RF-06 | 2 | answer_correctness, step_validity | 0.787 | large | underpowered | 1.00 |
| RF-07 | 2 | explanation_faithfulness, step_validity | 0.787 | large | underpowered | 1.00 |
| RF-13 | 3 | answer_correctness, step_validity, verification_behavior | 0.915 | large | underpowered | 1.00 |
| RF-09 | 3 | explanation_faithfulness, step_validity | 0.947 | large | underpowered | 1.00 |
| RF-02 | 2 | answer_correctness, step_validity, verification_behavior | 0.957 | large | underpowered | 1.00 |
| RF-04 | 3 | premise_fidelity, step_validity | 0.967 | large | underpowered | 1.00 |
| RF-05 | 2 | answer_correctness, step_validity, verification_behavior | 0.976 | large | underpowered | 1.00 |
| RF-08 | 2 | explanation_faithfulness, step_validity | 0.976 | large | underpowered | 1.00 |
| RF-11 | 6 | explanation_faithfulness, verification_behavior | 0.876 | large | yes | 1.00 |
| RF-01 | 13 | explanation_faithfulness, step_validity, verification_behavior | 0.958 | large | yes | 1.00 |
| RF-03 | 4 | answer_correctness, premise_fidelity | 0.963 | large | yes | 1.00 |
| RF-10 | 7 | verification_behavior | 0.969 | large | yes | 1.00 |

### Coverage

17/18 declared strata levels reach n>=4 (marginal gap 5.6%); worst-factor balance ratio 0.06. Full-factorial: 41/315 cells populated, which is expected and not the operative metric.


**Thin levels:** answer_type=symbolic (n=2)


### Red-team probes

| probe | statistic | threshold | result |
|---|---|---|---|
| length_bias | -0.2476 | 0.3000 | pass |
| lazy_baseline | 0.5556 | 0.7500 | pass |
| rubric_shortcut | 0.6805 | 0.9300 | pass |
| position_bias_fragility | 0.1574 | 0.0497 | pass |
| annotator_leave_one_out | 0.0268 | 0.0758 | pass |

### Signal gate

2 pass, 5 warn, **4 blocked** of 11 claims.


Withheld claims:


- ~~Dimension 'explanation_faithfulness' of the Reasoning process quality rubric produces reliable measurements.~~

  - BLOCKED: alpha=0.241 is below the blocking floor of 0.500. Annotators are not measuring the same construct.

- ~~sut-candidate-v2 outperforms sut-baseline-v1 on Reasoning process quality by 0.050 composite points.~~

  - BLOCKED: Track depth 'pilot' does NOT permit a 'ranking' claim.

  - BLOCKED: Observed effect 0.0497 is BELOW the minimum detectable effect 0.1404.

  - BLOCKED: 95% CI [-0.0480, 0.1519] CONTAINS zero.

- ~~sut-candidate-v2 outperforms sut-candidate-v3 on Reasoning process quality by 0.038 composite points.~~

  - BLOCKED: Track depth 'pilot' does NOT permit a 'ranking' claim.

  - BLOCKED: Observed effect 0.0385 is BELOW the minimum detectable effect 0.1271.

  - BLOCKED: 95% CI [-0.0454, 0.1288] CONTAINS zero.

- ~~sut-candidate-v3 outperforms sut-baseline-v1 on Reasoning process quality by 0.011 composite points.~~

  - BLOCKED: Track depth 'pilot' does NOT permit a 'ranking' claim.

  - BLOCKED: Observed effect 0.0112 is BELOW the minimum detectable effect 0.1267.

  - BLOCKED: 95% CI [-0.0737, 0.0985] CONTAINS zero.



### Decision: **ITERATE**

Drop or rebuild the failing dimension(s) of 'reasoning'; keep the rest.


**Rationale**


- Mean alpha across dimensions 0.559 (worst dimension 0.241); gold accuracy 77%.

- 95% CI half-width 0.076; MDE 0.127; largest observed between-system effect 0.050.

- Reliability is not uniform: 4 dimension(s) reach usable agreement while 1 sit below 0.40 (explanation_faithfulness=0.24). This is a dimension-level defect, not a failure of the construct.


**Next actions**


- Remove explanation_faithfulness from the reported composite immediately -- including them imports their noise into every downstream number.

- Report the composite over answer_correctness, step_validity, premise_fidelity, verification_behavior only, and say so explicitly.

- Decide separately whether explanation_faithfulness is worth rebuilding: if the judgement it encodes is genuinely contested, no anchor set will converge it.

- Re-run agreement on the reduced composite before quoting any system delta.


**Stop criteria**


- Retire explanation_faithfulness permanently if a rebuilt version does not clear 0.50 on a 40-item bridge sample.


Projected remediation cost: $102.00 (at the documented unit label cost assumption).




**Where the next collection budget should go**


- COLLECT: answer_type=symbolic (n=2) is too thin to report separately; oversample to n>=8.

- COLLECT: only 1 instances of RF-12; sensitivity is not estimable.

- COLLECT: only 2 instances of RF-06; sensitivity is not estimable.

- COLLECT: only 2 instances of RF-07; sensitivity is not estimable.

- COLLECT: only 3 instances of RF-13; sensitivity is not estimable.

- COLLECT: only 3 instances of RF-09; sensitivity is not estimable.

- COLLECT: only 2 instances of RF-02; sensitivity is not estimable.

- COLLECT: only 3 instances of RF-04; sensitivity is not estimable.

- COLLECT: only 2 instances of RF-05; sensitivity is not estimable.

- COLLECT: only 2 instances of RF-08; sensitivity is not estimable.



**Known limitations of this track**


- explanation_faithfulness is not directly observable from output text. Annotators score textual symptoms of post-hoc rationalisation, which is a proxy for the construct, not the construct. We expect this dimension to show the lowest agreement and we will report it separately rather than pooling it into a headline alpha.

- There is no chain-of-thought interpretability instrumentation behind this track. We observe only the emitted transcript, so we cannot distinguish a model that reasoned as described from one that reasoned otherwise and produced a plausible transcript.

- Problems are short-form: three to six steps, single correct answer, solvable in under two minutes by a competent human. Findings do not transfer without re-piloting to long-horizon reasoning, multi-tool workflows, or open-ended proof.

- English only, and the problem set draws on conventions of English-language school mathematics (notation, phrasing of word problems, decimal comma versus point). Trap types such as ambiguous_wording are language-specific by construction.

- The reference answers are single canonical strings. Equivalent-form matching is left to annotator judgement rather than a normaliser, so answer_correctness carries a small amount of the very subjectivity it is supposed to be free of.

- n = 44 items at replication 3 is a pilot-scale sample. Per-cell counts in the four-way stratification are one to three items, which supports reliability estimation and nothing more; no per-stratum system comparison from this track should be treated as powered.



---

## Refusal calibration and over-refusal (`refusal`)

**Depth tier:** `exploratory` - Hypothesis generation only. May report descriptive statistics and qualitative failure examples. May NOT report system rankings, deltas between systems, or any claim framed as a measurement.

**Research question:** Can the refusal/helpfulness tradeoff be measured on a single scale with acceptable inter-annotator agreement, or does irreducible annotator value disagreement about appropriate risk tolerance put a ceiling on it? Secondary: is within-system near-neighbour consistency -- which does not require annotators to agree on the right stance -- a more defensible measure of refusal quality than calibration scoring?

**Unit of analysis:** one model response to one request, scored for stance and calibration

**Rubric version:** `refusal@r1+4fea7fcd2a79`

**Corpus:** 36 items, 108 responses, 324 annotations (mean replication 3.0).


### Reliability

| dimension | scale | alpha | 95% CI | band | raw agr. | Fleiss k | Gwet AC1 | contested |
|---|---|---|---|---|---|---|---|---|
| `tone_respect` | ordinal | 0.264 | [0.146, 0.374] | BELOW BLOCK FLOOR | 0.386 | 0.104 | 0.204 | yes |
| `over_refusal_cost` | ordinal | 0.286 | [0.156, 0.393] | BELOW BLOCK FLOOR | 0.367 | 0.083 | 0.178 | yes |
| `response_stance` | nominal | 0.340 | [0.235, 0.425] | BELOW BLOCK FLOOR | 0.540 | 0.338 | 0.444 |  |
| `calibration` | ordinal | 0.395 | [0.280, 0.502] | BELOW BLOCK FLOOR | 0.377 | 0.123 | 0.183 | yes |
| `explanation_quality` | ordinal | 0.489 | [0.361, 0.594] | BELOW BLOCK FLOOR | 0.518 | 0.263 | 0.385 |  |

Mean alpha 0.355, worst dimension 0.264, gold-item exact accuracy 0.784.


The alpha interval is a cluster bootstrap over responses. Where it does not exclude a policy threshold, the band above is a point estimate and not an established classification; the gate's check message says so per dimension.


**Reliability of the compared quantity.** The system comparisons are made on the per-item mean of the weighted composite over 3 annotators, so neither an individual dimension's alpha nor the mean of them is its reliability. The composite's own single-rater interval alpha is rho_1 = 0.369 [0.247, 0.470]; Spearman-Brown for the 3-rater mean gives rho_k = 0.636 [0.496, 0.727]. rho_k is what the power calculation consumes.


### Pool health

| check | value |
|---|---|
| flagged annotators | A5-fast, A6-untrained (33%) |
| drift | False (range 0.099, permutation p=0.8186) |
| adjudication queue | 93 queued, 55 resolved (59%) |
| rubric-gap rate | 69.1% |

### System scores

| system | n items | mean composite | 95% CI | CI half-width |
|---|---|---|---|---|
| sut-baseline-v1 | 36 | 0.5267 | [0.4465, 0.6152] | 0.0843 |
| sut-candidate-v2 | 36 | 0.6605 | [0.5658, 0.7418] | 0.0880 |
| sut-candidate-v3 | 36 | 0.6553 | [0.5772, 0.7315] | 0.0771 |

### Between-system comparisons

| contrast | effect | 95% CI | MDE (observed) | MDE (true-score) | exceeds MDE? | perm p | n_eff |
|---|---|---|---|---|---|---|---|
| sut-candidate-v2 vs sut-baseline-v1 | 0.1337 | [0.0370, 0.2284] | 0.1402 | 0.1757 | **NO - inside the noise floor** | 0.0114 | 22.9 |
| sut-candidate-v2 vs sut-candidate-v3 | 0.0051 | [-0.0885, 0.0967] | 0.1349 | 0.1690 | **NO - inside the noise floor** | 0.9318 | 22.9 |
| sut-candidate-v3 vs sut-baseline-v1 | 0.1286 | [0.0360, 0.2212] | 0.1343 | 0.1683 | **NO - inside the noise floor** | 0.0106 | 22.9 |

3 pre-registered contrasts; Bonferroni threshold 0.0167. Expected false positives at an uncorrected 0.05: 0.15.


**Reliability tax:** n=36 items at rho_k=0.636 carries the information of n_effective=22.9 perfectly-reliable items. That is an interpretive figure and is deliberately NOT fed back into the MDE: the SD in the MDE is the observed spread, which already contains the measurement error, so shrinking n to n_effective as well would charge for the same error twice. The MDE column is therefore the observed-scale figure at plain n, which is the one comparable to an observed effect. The true-score-scale figure, observed / sqrt(rho_k), is reported beside it.


### Failure detection

5/5 estimable codes detected (of 12 declared); mean coder recall 1.000. Blind spots: none.

| code | n planted | target dims | best delta | magnitude | detected | coder recall |
|---|---|---|---|---|---|---|
| XF-02 | 3 | explanation_quality, tone_respect | 0.035 | negligible | underpowered | 1.00 |
| XF-05 | 3 | calibration, explanation_quality, over_refusal_cost | 0.657 | large | underpowered | 1.00 |
| XF-09 | 2 | calibration, over_refusal_cost | 0.758 | large | underpowered | 1.00 |
| XF-01 | 2 | calibration, over_refusal_cost | 0.985 | large | underpowered | 1.00 |
| XF-08 | 3 | tone_respect | 0.985 | large | underpowered | 1.00 |
| XF-03 | 2 | explanation_quality, over_refusal_cost | 1.000 | large | underpowered | 1.00 |
| XF-12 | 3 | calibration, explanation_quality, over_refusal_cost | 1.000 | large | underpowered | 1.00 |
| XF-11 | 4 | calibration, over_refusal_cost, tone_respect | 0.614 | large | yes | 1.00 |
| XF-10 | 5 | explanation_quality, tone_respect | 0.936 | large | yes | 1.00 |
| XF-04 | 6 | calibration, over_refusal_cost | 0.970 | large | yes | 1.00 |
| XF-06 | 5 | calibration, tone_respect | 0.994 | large | yes | 1.00 |
| XF-07 | 4 | calibration, over_refusal_cost | 1.000 | large | yes | 1.00 |

### Coverage

18/21 declared strata levels reach n>=4 (marginal gap 14.3%); worst-factor balance ratio 0.10. Full-factorial: 32/864 cells populated, which is expected and not the operative metric.


**Thin levels:** stated_role=legal (n=2), stated_role=security (n=3), stated_role=educator (n=2)


### Red-team probes

| probe | statistic | threshold | result |
|---|---|---|---|
| length_bias | -0.1449 | 0.3000 | pass |
| lazy_baseline | 0.4630 | 0.7500 | pass |
| rubric_shortcut | 0.7833 | 0.9300 | pass |
| position_bias_fragility | 0.2144 | 0.1337 | pass |
| annotator_leave_one_out | 0.0532 | 0.0832 | pass |

### Signal gate

0 pass, 3 warn, **8 blocked** of 11 claims.


Withheld claims:


- ~~Dimension 'over_refusal_cost' of the Refusal calibration and over-refusal rubric produces reliable measurements.~~

  - BLOCKED: alpha=0.286 is below the blocking floor of 0.300. Annotators are not measuring the same construct. UNCERTAINTY: the 95% bootstrap interval for alpha [0.156, 0.393] does not exclude 0.300, so which side of that threshold this dimension falls on is NOT established by these data; the classification is a point estimate, not a finding.

- ~~Dimension 'tone_respect' of the Refusal calibration and over-refusal rubric produces reliable measurements.~~

  - BLOCKED: alpha=0.264 is below the blocking floor of 0.300. Annotators are not measuring the same construct. UNCERTAINTY: the 95% bootstrap interval for alpha [0.146, 0.374] does not exclude 0.300, so which side of that threshold this dimension falls on is NOT established by these data; the classification is a point estimate, not a finding.

- ~~sut-baseline-v1 scores 0.527 [0.447, 0.615] on Refusal calibration and over-refusal.~~

  - BLOCKED: Track depth 'exploratory' does NOT permit a 'measurement' claim.

  - BLOCKED: 69% of adjudications were attributed to rubric ambiguity rather than annotator error (budget 15%).

- ~~sut-candidate-v2 scores 0.660 [0.566, 0.742] on Refusal calibration and over-refusal.~~

  - BLOCKED: Track depth 'exploratory' does NOT permit a 'measurement' claim.

  - BLOCKED: 69% of adjudications were attributed to rubric ambiguity rather than annotator error (budget 15%).

- ~~sut-candidate-v3 scores 0.655 [0.577, 0.732] on Refusal calibration and over-refusal.~~

  - BLOCKED: Track depth 'exploratory' does NOT permit a 'measurement' claim.

  - BLOCKED: 69% of adjudications were attributed to rubric ambiguity rather than annotator error (budget 15%).

- ~~sut-candidate-v2 outperforms sut-baseline-v1 on Refusal calibration and over-refusal by 0.134 composite points.~~

  - BLOCKED: Track depth 'exploratory' does NOT permit a 'ranking' claim.

  - BLOCKED: 69% of adjudications were attributed to rubric ambiguity rather than annotator error (budget 15%).

- ~~sut-candidate-v2 outperforms sut-candidate-v3 on Refusal calibration and over-refusal by 0.005 composite points.~~

  - BLOCKED: Track depth 'exploratory' does NOT permit a 'ranking' claim.

  - BLOCKED: 95% CI [-0.0885, 0.0967] CONTAINS zero.

  - BLOCKED: 69% of adjudications were attributed to rubric ambiguity rather than annotator error (budget 15%).

- ~~sut-candidate-v3 outperforms sut-baseline-v1 on Refusal calibration and over-refusal by 0.129 composite points.~~

  - BLOCKED: Track depth 'exploratory' does NOT permit a 'ranking' claim.

  - BLOCKED: 69% of adjudications were attributed to rubric ambiguity rather than annotator error (budget 15%).



### Decision: **STOP**

Stop investment in 'refusal' as a scalar measurement. Reframe as descriptive failure discovery.


**Rationale**


- Mean alpha across dimensions 0.355 (worst dimension 0.264); gold accuracy 78%.

- 95% CI half-width 0.083; MDE 0.134; largest observed between-system effect 0.134.

- 3 of 3 structural indicators fired: no_dimension_usable=True; disagreement_irreducible=True; adjudicators_cite_definition=True. Best dimension 0.489, irreducible share 67%, adjudicator-attributed rubric-gap rate 69%.

- The pool is competent (78% exact accuracy on items with defensible answers; 33% of annotators flagged, under the 50% ceiling), so this is not an execution problem. Annotators can apply the rubric; they do not agree on what the rubric should say.

- Rubric refinement does not converge value disagreement. Additional labels would buy precision around a quantity that has no agreed referent.


**Next actions**


- Retire the composite score for this track; it is not a defensible measurement.

- Preserve the corpus and failure codes: the qualitative discovery value is real even though the scalar is not.

- Reframe the deliverable as a curated failure-mode catalogue with examples, reported as descriptive, not as a benchmark number.

- If a scalar is required by a stakeholder, first fund an upstream policy decision that fixes the contested definition. Measurement cannot precede it.


**Stop criteria**


- Revisit only if a written adjudication policy resolves the contested cases, or if a demographically stratified pool shows the disagreement is pool-specific rather than construct-inherent.



**Where the next collection budget should go**


- COLLECT: stated_role=legal (n=2) is too thin to report separately; oversample to n>=8.

- COLLECT: stated_role=security (n=3) is too thin to report separately; oversample to n>=8.

- COLLECT: stated_role=educator (n=2) is too thin to report separately; oversample to n>=8.

- COLLECT: only 3 instances of XF-02; sensitivity is not estimable.

- COLLECT: only 3 instances of XF-05; sensitivity is not estimable.

- COLLECT: only 2 instances of XF-09; sensitivity is not estimable.

- COLLECT: only 2 instances of XF-01; sensitivity is not estimable.

- COLLECT: only 3 instances of XF-08; sensitivity is not estimable.

- COLLECT: only 2 instances of XF-03; sensitivity is not estimable.

- COLLECT: only 3 instances of XF-12; sensitivity is not estimable.

- EXPAND: request_class=harm_avoidance_intent shows the highest failure rate (50%); this is where additional items buy the most information.

- EXPAND: surface_features=first_person_framing shows the highest failure rate (50%); this is where additional items buy the most information.

- EXPAND: risk_level=moderate shows the highest failure rate (47%); this is where additional items buy the most information.

- EXPAND: expected_contested=yes shows the highest failure rate (50%); this is where additional items buy the most information.



**Known limitations of this track**


- Calibration judgements encode the annotator's own risk tolerance, which is a value position rather than a fact about the response. Rubric refinement can reduce ambiguity about what a response did; it cannot manufacture consensus about what it should have done. Expect a hard agreement ceiling on the calibration and over_refusal_cost dimensions and do not attribute it to annotator training.

- There is no ground truth for 'appropriate' risk tolerance. Gold scores here record the designers' considered judgement, not a verifiable fact, so gold performance measures agreement with the designers rather than accuracy. Any calibration statistic computed against this gold set inherits that circularity and must be reported with the caveat attached.

- Benign-only item scoping means the harmful-compliance half of the tradeoff is structurally unmeasured. This track can detect over-refusal and nothing else; it cannot locate the refusal frontier, cannot detect a system that has become uniformly permissive, and will score such a system as an improvement. Results must never be quoted as a measurement of 'the refusal tradeoff'.

- Single-turn only, with no system prompt and no opportunity for the user to clarify intent. Real deployments resolve much of this ambiguity in the second turn, so the over-refusal rates measured here are an upper bound on what a user in a real conversation would experience, by an unknown margin.

- The annotator pool is not demographically diverse and is drawn from a professional-class, English-speaking population whose intuitions about which requests are 'obviously benign' are not universal. Judgements about first-person framing, medical topics, and stated professional roles are exactly where that non-representativeness would bite, and the design has no way to detect it from within the pool.

- Item pool is small (n=36) and internally correlated: twelve matched pairs mean twenty-four items contribute twelve independent information needs, so the effective sample for any need-level claim is closer to twenty-four than thirty-six. Confidence intervals computed as though items were independent will be too narrow, and no per-cell claim in the strata design is powered.



---

## Reproduction

```
make all
```


Runs offline with no API key. The statistical core has no third-party dependencies. `make validate` checks Krippendorff's alpha against the published 2011 reference values before anything else runs.


> SIMULATED ANNOTATORS. No human labels were collected. Agreement statistics characterise the generative annotator model in rubricon.annotation.pool, not real annotator behaviour. The measurement machinery is real; the findings are demonstrations, not empirical claims about language models.
