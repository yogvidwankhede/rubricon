# Rubricon

**Evaluation signal infrastructure.** A harness for building evaluations whose numbers can be defended — versioned rubrics, replicated annotation, agreement statistics validated against published reference values, a programmatic gate that *blocks* claims the evidence does not support, and a sensitivity analysis that tells you which of your own conclusions would survive being wrong about your assumptions.

```
make all           # validate stats -> tests -> pipeline -> report -> audit every number
make sensitivity   # how much of the conclusion is the data, and how much is me?
```

Runs offline. No API key. No third-party dependencies in the statistical core.

> ### Read this before any number below
> **The annotators in this repository are simulated.** No human labelled anything. Every agreement coefficient characterises the generative annotator model in `src/rubricon/annotation/pool.py`, not real annotator behaviour.
>
> The *machinery* is real: the agreement math reproduces Krippendorff's published values to four decimal places, the gate logic is real, and pointing it at real labels requires setting one environment variable. The *findings* are demonstrations that the pipeline detects the conditions it was built to detect, on data whose ground truth is known by construction. They are not empirical claims about language models.

---

## The problem this attacks

Most evaluation work fails at the *last* step. The data gets collected, the rubric gets written, a number comes out — and then the number escapes into a deck, a roadmap, or a customer conversation without anyone having checked whether the measurement could support the sentence built on top of it. By the time the claim is public, questioning it is a political act rather than a technical one.

Rubricon makes that check mechanical. Thresholds are declared before results exist. Claims are constructed from evidence rather than written by hand. Each is returned `PASS`, `WARN`, or `BLOCK` — and a `BLOCK` is not advisory. The report renders the block reason where the number would have been.

**In this run the gate withheld 23 of 45 claims (51%),** including several I wanted to make.

---

## Start here: the conclusions are conditional, and I measured how conditional

This is the part I would want a reviewer to read first, because it is the part most portfolio projects hide.

The four recommendations below depend on assumptions I set by hand — most importantly a dictionary in `annotation/effects.py` that marks certain rubric dimensions as *contested* (annotators hold stable differing positions rather than making independent errors). Rather than hope nobody noticed, `make sensitivity` re-runs the entire pipeline 196 times under perturbed assumptions and reports which conclusions survive.

They mostly do not survive cleanly:

| Perturbation | Effect on the headline verdicts |
|---|---|
| Clear refusal's three contested flags | `refusal` STOP → **ITERATE** |
| Randomly reassign the same 5 flags across all 21 dimensions (20 seeds) | `refusal` keeps STOP in **11/20**; `agentic` keeps INVEST in **6/20** |
| Remove annotator A2-senior *or* A3-core | `agentic` INVEST → **ITERATE** |
| Global noise multiplier above 0.91 | `agentic` and `refusal` both flip |

`max_flagged_annotator_fraction` is set to 0.34 and flips at 0.333 — a **2.1% margin** from the observed value on all four tracks. The analysis labels that FRAGILE rather than waiting for someone else to find it.

So the honest form of the headline finding is conditional, not declarative: *if* calibration, over-refusal cost, and tone are genuinely contested judgements, *then* refusal is not measurable as a scalar with this pool. The sensitivity report classifies `agentic` FRAGILE, `grounding` and `reasoning` CONDITIONAL, and states plainly what would have to be true for each verdict to hold.

**The skill being demonstrated is not producing four clean verdicts. It is knowing that four clean verdicts would have been a lie, and building the thing that proves it.**

---

## What the run found

| Track | Depth | Mean α | ρ₁ / ρ₃ | Gold acc. | Decision | Stability |
|---|---|---:|---:|---:|---|---|
| `agentic` — tool-use failure | production | 0.584 | 0.750 / 0.900 | 0.793 | **INVEST** | FRAGILE |
| `reasoning` — process validity | pilot | 0.559 | 0.718 / 0.884 | 0.769 | **ITERATE** | CONDITIONAL |
| `grounding` — citation integrity | pilot | 0.479 | 0.760 / 0.905 | 0.867 | **ITERATE** | CONDITIONAL |
| `refusal` — refusal calibration | exploratory | 0.355 | 0.369 / 0.637 | 0.784 | **STOP** | CONDITIONAL |

Three substantive results:

**1. The eval cannot separate the two candidate systems, and saying so is the result.** On `agentic`, v3 beats the baseline by 0.157 against a minimum detectable effect of 0.108 — reportable. But v2 vs v3 differs by 0.033 against an MDE of 0.094, p = 0.33. That is inside the noise floor. On `reasoning`, *no* contrast clears its MDE. The gate blocks those ranking claims rather than letting a 3-point "improvement" onto a slide.

**2. Reliability is not one number, and using the wrong one moves a verdict.** The comparisons are made on the per-item mean of a weighted composite across three annotators — so neither an individual dimension's α nor the mean of them is its reliability. The composite's own single-rater α is 0.750 on `agentic`; Spearman-Brown for the 3-rater mean gives 0.900. An earlier version of this repo passed the mean per-dimension α (0.584) into the power calculation *and* applied the reliability correction on top of an SD that already carried measurement error. That double-count inflated the MDE from 0.120 to 0.157 and caused the gate to block a contrast with p = 0.0049. See `docs/engineering-log.md`.

**3. `grounding` has two detection blind spots.** GF-02 and GF-12 are planted in the corpus and the instrument scores those responses as acceptable. A blind spot is worse than a noisy measurement, because it produces confident false assurance. Naming them is only possible because the corpus carries planted ground truth.

[Full stop-work memo for `refusal` →](docs/decision-memo-refusal.md) · [Research report →](docs/research-report.md)

---

## What makes it more than a scoring script

**The signal gate** (`gates/signal.py`) — Pre-registered thresholds; eleven independent checks (reliability, precision, effect-vs-MDE, interval-excludes-zero, coverage, replication, drift, rubric specification, gold calibration, annotator pool, depth contract). All checks run; nothing short-circuits, because "this claim has four problems" is more useful than "this claim has one". Blocked claims stay in the ledger and render as blocks — a report that silently omits its failures is indistinguishable from one that had none.

**Depth tiers** (`tracks/__init__.py`) — Every track declares `exploratory` / `pilot` / `production`, and the harness enforces what that tier permits. An exploratory track is *mechanically barred* from emitting a ranking claim no matter how good its numbers look.

**Three agreement coefficients, not one** (`stats/agreement.py`) — Krippendorff's α (scale-aware, missing-data tolerant) as the headline, with cluster-bootstrapped intervals; Fleiss' κ because reviewers expect it; Gwet's AC1 to expose the *kappa paradox*, where prevalence skew collapses κ toward zero at 95% raw agreement. Confusing that with annotator unreliability triggers weeks of retraining for a sampling-design flaw. Both κ and AC1 use the same unit-averaged marginal estimator, so the two numbers printed side by side are comparable.

**Detection sensitivity** (`taxonomy/induce.py`) — Does the rubric register the failures it was *written* to detect? Per-code Cliff's delta against clean responses, with codes below the estimability floor reported as underpowered rather than as blind spots — conflating those two blames the rubric for a sampling gap.

**Red-teaming the eval itself** (`redteam/probes.py`) — Length bias, lazy baselines, position-bias fragility, leave-one-annotator-out against the *published CI* rather than an arbitrary constant, and a rubric-shortcut check computed against the **leave-one-out** composite so the correlation is not mechanically inflated by part-whole overlap.

**Invest / iterate / hold / stop** (`gates/decision.py`) — Separates *fixable* low agreement from *structural* low agreement, on a 2-of-3 indicator rule. `make sensitivity` reports how far each of those cuts is from flipping.

---

## Repository map

```
src/rubricon/
  core/schema.py        versioned, content-addressed rubrics; provenance-carrying records
  stats/agreement.py    Krippendorff alpha (+ bootstrap CIs), Fleiss kappa, Gwet AC1,
                        composite reliability with Spearman-Brown, kappa-paradox detection
  stats/precision.py    cluster bootstrap, MDE (observed and true scale), multiplicity
  stats/drift.py        leniency bias vs value position, permutation-tested drift, gold calibration
  gates/signal.py       the quality gate and claim ledger
  gates/decision.py     invest / iterate / hold / stop
  gates/sensitivity.py  which conclusions survive perturbing the assumptions
  annotation/           simulated pool, effect tables, triage and adjudication
  taxonomy/induce.py    detection sensitivity, coverage, investment recommendations
  redteam/probes.py     gameability probes against the rubric
  models/client.py      pluggable client; offline fixture replay is the default path
  tracks/               four tracks, auto-discovered (10.7k lines of rubrics and corpora)
  pipeline.py           generate -> annotate -> triage -> adjudicate -> score -> probe -> gate -> decide

docs/
  research-report.md              methods and findings
  decision-memo-refusal.md        the stop-work memo
  engineering-log.md              real bugs, root causes, and lessons
  specs/, guidelines/, adr/       task spec, annotation guidelines, calibration protocol, 5 ADRs
  rubricon-walkthrough.pptx       16-slide interview walkthrough

results/dashboard.html            self-contained interactive results explorer
results/sensitivity.json          196 pipeline runs under perturbed assumptions
scripts/audit_numbers.py          verifies every number in docs/ traces to results/
```

---

## Reproducibility

`make all` regenerates every artifact from source. The pipeline is deterministic: same code, same corpus, same numbers, on any machine, with no network. A test runs the whole portfolio in two subprocesses under different `PYTHONHASHSEED` values and compares bytes — added after Python's salted string `hash()` in bootstrap seeds silently broke exactly the determinism the module docstring promised.

`make audit` mechanically verifies that every number quoted in `docs/*.md` traces to `results/portfolio.json`, with an allowlist where each exemption carries a written justification. The script's own docstring documents what it *cannot* catch, which is how a wrong figure in an earlier draft of this README slipped past it.

**225 tests.** The most important asserts Krippendorff's α against the published 2011 reference dataset for all four distance metrics — nominal 0.7434, ordinal 0.8154, interval 0.8491, ratio 0.7974, matching to within 0.0004. Others check the cluster bootstrap against a naive observation-level bootstrap, the MDE against `statsmodels`, and Fleiss' κ against `statsmodels` and `irrCAC`.

---

## The engineering log is the most useful document here

[`docs/engineering-log.md`](docs/engineering-log.md) records the real defects found during development. The pattern in them is the point:

- Round-robin dealing over a difficulty-sorted list produces a monotone gradient *by construction*, not balance — so the drift detector faithfully reported drift that was an artifact of my own assignment scheme.
- Drift is not identifiable at all without cross-batch item overlap. Better item stratification cannot fix it; splitting each response's replicates across batches can.
- The drift detector itself used a fixed threshold with no null model and fired on healthy tracks.
- Coverage gating used full-factorial emptiness, which is unreachable by design and would have blocked every honestly-designed study.
- A red-team probe asserted a stipulated order effect and then reported pass/fail against it — circular, and it "failed" everywhere because the answer was baked into the input.
- The bias detector reported annotators' *value positions* as leniency bias, on the one track where separating those two things was the entire argument.

**Most of these produced false alarms in the quality machinery rather than missed problems.** A quality gate that cries wolf is worse than no gate, because people learn to ignore it — and then it fails silently on the case that mattered.

The log also records one decision I am least comfortable with: a STOP threshold was loosened *after* seeing that it declined to produce the expected verdict. That is exactly what pre-registration is supposed to prevent. `gates/sensitivity.py` exists partly because the right answer to "you moved a threshold" is to publish how much the conclusion depends on where it sits.

---

## Extending it

Tracks are auto-discovered via `pkgutil`. Drop a module in `src/rubricon/tracks/` exposing `SPEC: TrackSpec`, `seed_items()`, and `fixture_responses()` and it is picked up with no harness edit — verified by adding and removing a fifth track. If it has no entry in the effects table the pipeline emits a loud warning and stamps `effects_table_missing: true`, so absent penalties can never be mistaken for a real detection blind spot.

For real model outputs, set `RUBRICON_CLIENT=anthropic|openai|ollama`. The adapters are marked `verified_in_this_repo: false`, because claiming otherwise would be exactly the kind of unverified assertion this project is about.

---

MIT licensed. Built as a demonstration of evaluation methodology, not as a benchmark.
