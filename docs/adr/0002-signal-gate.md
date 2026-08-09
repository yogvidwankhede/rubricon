# ADR 0002: A pre-registered signal gate between measurements and claims

Date: 2026-05-06 (reconstructed from working notes; the repository carries no commit history)

Results pinned to `results/portfolio.json`, md5 299bd4f19e03caa2cd7e33681340c294. Re-running the pipeline changes
every figure quoted below; check the hash before quoting them.

**Annotators are simulated.** No human labelled anything in this repository. Every
agreement, gold and block-rate figure below is a property of the generative annotator
model in `src/rubricon/annotation/pool.py`, not of a real pool. The gate itself is real
and would run unchanged on human labels; the numbers it produces here are a demonstration
that the machinery works, not an empirical claim about any language model.

## Status

Accepted. Implemented in `src/rubricon/gates/signal.py`. Applied to every claim in every
track.

## Context

Evaluation numbers escape. They leave the notebook, enter a deck, then a roadmap, then a
customer conversation, and nobody on that path checks whether the measurement can support the
sentence built on it. By the time the claim is public, questioning it is a political act
rather than a technical one.

The specific gap is that a number and a claim are different objects and only the number gets
scrutiny. "System v2 scores 0.585" and "system v2 is better than the baseline" need completely
different evidence: the first an interval, the second an interval excluding zero, an effect
above the design's noise floor, a multiplicity correction, and a reliability high enough that
the composite means anything.

There is also a timing problem. Thresholds chosen after seeing results are not thresholds,
they are rationalisations.

## Decision

Introduce a `Claim` object -- a sentence someone wants to publish, plus its evidence -- and a
`SignalGate` that evaluates claims against a `GatePolicy` of thresholds **declared before
results exist**. Each claim gets a verdict of PASS, WARN, or BLOCK.

Four design rules:

1. **Checks are independent and all run.** "This claim has four problems" is more useful to
   whoever fixes it than "this claim has one problem".
2. **A BLOCK is not advisory.** `ClaimLedger.publishable()` filters blocked claims out of the
   report, which renders the block reason where the number would have been.
3. **A blocked claim is still recorded.** Suppressing it would hide that someone wanted to make
   the claim. The ledger is the audit trail.
4. **Thresholds are data, not code.** A reviewer can disagree with 0.667 and see what changes.

Defaults follow Krippendorff (alpha >= 0.800 firm, >= 0.667 tentative) rather than the more
permissive Landis-Koch bands, because eval numbers get quoted as if they were firm. Production
policy: block below alpha 0.50, warn below 0.667; CI half-width <= 0.075; effect must exceed
the MDE; no absent strata levels, marginal gap <= 0.20; replication >= 2; flagged-annotator
fraction <= 0.34; rubric-gap rate <= 0.15; gold accuracy >= 0.70; block on drift; correct for
multiplicity.

## Consequences

**It bites, which is the test of whether it is real.** Across the portfolio, 45 claims were
submitted and 23 were blocked -- a block rate of 0.511. On the flagship `agentic` track, 12
claims: 1 pass, 8 warn, 3 block.

Two of the agentic blocks are dimensions whose reliability fell below the 0.500 floor
(`efficiency` at 0.4721, `tool_selection` at 0.4990). The third is a ranking:

- `sut-candidate-v2` vs `sut-candidate-v3`: -0.0329 against an MDE of 0.0944, CI
  [-0.1000, 0.0320] containing zero. Blocked on both counts, as intended -- the candidates'
  planted failure rates differ by 2 points by construction, below what n=48 can resolve.

Both baseline contrasts survive. v3 vs baseline, 0.1573, CI [0.0851, 0.2313], p = 0.0003,
MDE 0.1075 -- clears both checks and still carries a WARN, because five of six dimensions
sit below the 0.667 reliability threshold. v2 vs baseline, 0.1243, CI [0.0414, 0.2115],
p = 0.0049, MDE 0.1199 -- also clears, also WARN.

**That second row used to be a BLOCK, and the block was wrong.** An earlier version of
the power calculation applied the reliability correction twice, shrinking n to an
effective n *and* computing the MDE against an observed SD that already contained the
measurement error. It reported an MDE of 0.1569 for that contrast, and the gate withheld
a real, significant, adequately-powered effect. The consequence for this ADR is
uncomfortable and belongs in it: **the gate is only as trustworthy as the statistics it
gates on, and a false BLOCK is the most expensive kind of failure it can have.** A false
WARN is noise. A false BLOCK suppresses a true finding while looking like rigour, and
nobody downstream can tell the difference, because the whole design of the mechanism is
that the reader sees the block reason instead of the number. The corrective is not
"loosen the gate" -- it is that every threshold's *input* needs the same scrutiny as the
threshold itself, and the engineering log now carries that defect as the most
consequential one in the project.

**Costs.**

- A high block rate reads as failure to stakeholders who have not internalised what is being
  blocked. Half the portfolio's claims cannot be published, and that needs explaining every
  time.
- WARN carries too much load: 8 of 12 agentic claims. There is a real risk it becomes visual
  noise, recreating the problem the gate exists to solve. Unsolved; the current mitigation is
  printing the warning inline with the number rather than in a footnote.
- The gate cannot check whether a claim's *sentence* matches its evidence. Claim kind
  approximates this; someone can still attach a strong sentence to a descriptive claim.
- Some thresholds are arguably wrong. A worst-annotator gold accuracy of 0.4881 against a 0.70
  floor currently produces WARN, not BLOCK. I think that is too lenient.
- **Several thresholds sit close enough to the observed data that the value, not the
  evidence, decides the outcome.** `results/sensitivity.json` sweeps all of them: 12 of 96
  threshold-by-track pairs are FRAGILE, and `max_flagged_annotator_fraction` -- set to 0.34
  against an observed 0.333 -- flips at 0.332969 on all four tracks, a 2.1% margin. The
  answer to "a reviewer can disagree with 0.667 and see what changes" is now a published
  artifact rather than an invitation.
- The reliability check now reports its own uncertainty. `argument_fidelity` has alpha
  0.5704 with a bootstrap interval of [0.4696, 0.6476], which does not exclude the 0.500
  blocking floor, so the check says in as many words that which side of the floor the
  dimension falls on is not established by these data. That is honest and it makes the
  WARN load worse, because a point estimate that used to read as a verdict now reads as a
  verdict plus a hedge.

## Alternatives considered

**Reviewer checklist.** Rejected: it runs when someone remembers, which is not when it
matters, and its output is not machine-readable.

**Block on p-value only.** Rejected. A p-value says the sign is unlikely to be noise; it
says nothing about whether the design could resolve an effect of that size, and the
`sut-candidate-v2`-vs-`sut-candidate-v3` case above is what a p-value-only gate waves
through in the other direction.

**Warn on everything, block on nothing.** Rejected: a gate that never stops anything trains
readers to ignore it. This is the same failure mode documented for the pre-permutation drift
detector in the engineering log.

**Set thresholds per track after seeing results.** Rejected as circular. The legitimate
variant survives as ADR 0004's depth tiers: a looser `EXPLORATORY_POLICY` exists, but it is
selected by declared depth in advance, which makes "we relaxed the bar here" an explicit,
reviewable act.
