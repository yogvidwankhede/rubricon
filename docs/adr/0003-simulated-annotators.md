# ADR 0003: Simulated annotators instead of human labels

Date: 2026-05-14 (reconstructed from working notes; the repository carries no commit history)

Results pinned to `results/portfolio.json`, md5 299bd4f19e03caa2cd7e33681340c294. Re-running the pipeline changes
every figure quoted below; check the hash before quoting them.

## Status

Accepted, with reservations recorded below. Implemented in
`src/rubricon/annotation/pool.py`. This is the most consequential and most attackable
decision in the project.

## Context

Nothing here can be tested without labels: agreement coefficients, adjudication triage, drift
detection, the power analysis, the gate and the decision engine all consume annotations.

Human labels require a pool, a budget, a training programme and weeks. Buying them *before* the
machinery that would evaluate them is validated means paying for labels that may be unusable --
the failure this project exists to prevent.

The alternative is to generate labels from a model of annotator behaviour: cheap, instant,
reproducible, with ground truth known by construction. It also produces numbers that are not
about anything real, and the risk a reader takes them as empirical is severe.

## Decision

Simulate. Six annotators on a fixed roster, each with four stable traits: `competence`
(scales judgement noise), `bias` (persistent leniency or harshness in rubric points),
`value_position` (a stance applied only to dimensions flagged contested), and `fatigue_rate`
(noise inflation across a session).

Two non-negotiable constraints:

**It must not beg the question.** If the annotator model drew scores from the gate's pass
region, the whole exercise would be circular. The model is specified in terms of annotator
psychology, and the reliability statistics fall out of it. Whether a track passes its gate is
not set anywhere in `pool.py`.

**The caveat is never buried.** The `SIMULATION_NOTICE` string is attached to the portfolio
summary, the pool description, and the header of every generated report; each annotation record
carries `source: SYNTHETIC` and `metadata: {simulated: true}`. A reader who misses the caveat
draws exactly the wrong conclusion.

The roster is deliberately heterogeneous -- A6-untrained is weak (competence 0.58), A5-fast is
both biased (+0.42) and quick (speed_factor 4.00) -- because if every simulated annotator were
good the pool-health checks would be untested decoration. The realised profile bears it out: A6
came in at gold accuracy 0.4881 with a harsh bias of -0.3893 and tripped both the harshness and
the gold-floor flag, and A5 tripped two of its own -- leniency at +0.3885 and suspiciously-fast
at a mean duration of 34.6 seconds against the 45-second floor.

## Consequences

**What it buys.**

- *Reproducibility.* The portfolio regenerates from a seed. `hashlib`-derived seeds replace
  `hash()` precisely because the builtin is salted per process and would silently change the
  corpus between runs.
- *No API key, no budget, no vendor.*
- *Known ground truth.* Planted failures are known, so detection sensitivity is measurable
  rather than assumed; latent scores are known, so annotator bias can be isolated. Neither is
  possible with human labels, where the truth is what you are trying to estimate.
- *Sensitivity analysis.* Traits are parameters, so "what would a pool without A6 look like"
  has an exact answer -- the leave-one-out probe reports +0.0242 on the agentic track mean
  against a CI half-width of 0.068.

**What it costs.**

- **No finding here is an empirical claim.** Krippendorff alpha of 0.584 on `agentic` is a
  property of the generative model. It is not evidence that humans would reach 0.584 on this
  rubric, nor evidence about any language model's agentic behaviour.
- Annotator error is **additive and well-behaved** -- Gaussian noise plus a constant offset,
  rescaled by span. Real annotators make structured errors: anchoring on the previous item,
  misreading one anchor consistently, shortcutting under time pressure. None is represented,
  and all of it degrades agreement in ways this model cannot produce.
- Failure-code tagging uses a detection probability linear in competence, so measured coder
  recall (1.00 mean on `agentic`) restates the parameters rather than finding anything.
- The model is smooth, so the corpus lacks the pathologies that make annotation programmes hard.
- Every document has to lead with the caveat, and skimmers will still misread the numbers.

**Exactly what changes if real labels are substituted.**

The interfaces do not change. `annotate()` returns `Annotation` objects; a real collection
pipeline emits the same objects with `source: HUMAN`. Nothing downstream -- agreement, triage,
adjudication, drift, precision, the gate, the decision engine -- reads the `simulated` flag or
the annotator traits.

What changes is what the numbers mean:

1. Every agreement coefficient becomes an empirical estimate rather than a model property, and
   should be expected to fall. The simulation applies a 0.70 multiplier to judgement noise
   because the pool is assumed anchored; an unanchored real pool sits at 1.0 or worse.
2. `value_position` -- the term that does not average out -- would have to be estimated rather
   than assigned. The irreducible-share estimate (0.503 on `agentic`, 0.666 on `refusal`)
   depends on that decomposition and is the figure most exposed to the swap.
3. Gold keys would need authoring per trajectory, not per item. The current implementation
   applies an item's key to all three systems' trajectories, making gold slightly easier.
4. Detection sensitivity would need a real planted-failure corpus or expert adjudication. Nine
   of thirteen agentic codes are already underpowered at 2-3 instances each.
5. The drift statistic would become interesting. In simulation nothing makes the pool drift, so
   the agentic p = 0.917 is near-guaranteed and the detector is untested.

## Alternatives considered

**A small human pilot (say 200 labels).** Rejected for now on cost and lead time, but it is the
right next step and the calibration protocol is written to receive it. It would validate points
1 and 5 above.

**Use an LLM as the annotator.** Rejected: labels neither strictly reproducible nor human, a key
required, and a correlated error structure across all "annotators" that would inflate agreement
-- the opposite of what we want to detect. Attractive as a *second* pass once human labels exist
to validate against, which is what the agentic decision's next actions propose.

**Hand-author a small fully-adjudicated corpus.** Rejected: too small to estimate agreement on,
and it makes the authors the annotators -- circularity in a different costume.
