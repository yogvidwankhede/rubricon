# ADR 0005: Measure and publish assumption-dependence rather than present verdicts as findings

Date: 2026-08-06 (reconstructed from working notes; the repository carries no commit history)

Results pinned to `results/portfolio.json`, md5 299bd4f19e03caa2cd7e33681340c294, and to
`results/sensitivity.json`. Re-running either changes every figure quoted below; check the
hashes before quoting them.

**Annotators are simulated.** No human labelled anything in this repository. Every figure
below characterises the generative annotator model in `src/rubricon/annotation/pool.py`.
That cuts both ways here: this ADR is about how sensitive the verdicts are to hand-set
parameters, and the whole annotator model is itself the largest hand-set parameter of all.

## Status

Accepted. Implemented in `src/rubricon/gates/sensitivity.py`, run by `make sensitivity`,
output at `results/sensitivity.json`. Deliberately **not** part of `make all`.

## Context

The portfolio ends in four recommendations -- `agentic` invest, `grounding` iterate,
`reasoning` iterate, `refusal` stop -- and they read like findings. Several are readouts of
parameters I chose.

The clearest case is a dictionary in `annotation/effects.py` marking five of the
portfolio's 21 dimensions `contested: True`. That flag switches on the `value_position`
term -- the one component of annotator error replication cannot reduce -- so the dimensions
carrying it are guaranteed to agree worst. Three of the five sit on `refusal`, the track
that gets STOP. An adversarial reviewer put it bluntly: flip three booleans and the
headline verdict inverts. They were right. Three more families of the same problem:
`gates/decision.py` cuts sit close to observed values and the engineering log records one
being loosened *after* it declined to produce the expected verdict; `gates/signal.py` sets
`max_flagged_annotator_fraction = 0.34` against an observed 0.333; and two simulator
multipliers set how much disagreement exists at all.

The tempting responses are all bad. Arguing the flags are correct restates the assumption.
Removing them removes the mechanism the project exists to demonstrate. A caveat paragraph
is the "caveat nobody read" failure ADR 0004 was written against. A conclusion that depends
on an assumption is not thereby worthless -- every conclusion does -- but a conclusion whose
dependence is *undisclosed* is, because the reader cannot price it.

## Decision

Perturb every assumption we can name, re-run the whole pipeline under each perturbation,
and publish which conclusions move. Four analyses, in decreasing order of how much they
threaten the portfolio: contested flags, gate and decision thresholds, simulator noise, and
leave-one-annotator-out. **196 pipeline runs**, about 473 seconds. Three design rules:

1. **No forked copy of the chain.** Every perturbed run goes through the real
   `pipeline.run_track`. A lighter reimplementation would drift from production, and an
   analysis that measures a stale replica is worse than none.
2. **No forked copy of the decision cuts.** They are inline literals, so
   `discover_decision_cuts` parses `decision.py`, finds every numeric literal used in a
   comparison inside `recommend()`, and recompiles the module with one substituted. The
   swept engine is always the real engine. Twenty-five literals are not reachable as
   comparison cuts, and that count is published rather than omitted.
3. **Classify, do not score.** Each conclusion is labelled ROBUST, CONDITIONAL or FRAGILE.
   None is a pass or a fail: FRAGILE is a statement about how much weight a number can
   carry, not an accusation.

Verdicts are reported with their label attached, everywhere they appear.

## Consequences

**It found what it was built to find, and the results are not flattering.** No conclusion is
ROBUST. `agentic` is FRAGILE -- removing either `A2-senior` or `A3-core` turns INVEST into
ITERATE. The other three are CONDITIONAL. Clearing `refusal`'s three contested flags turns
STOP into ITERATE; random reassignment of the same five flags across all 21 dimensions
preserves STOP in 11 of 20 seeds, INVEST on `agentic` in 6, ITERATE on `reasoning` in 5, and
ITERATE on `grounding` in 16. Twelve of 96 threshold-by-track pairs are FRAGILE, with
`max_flagged_annotator_fraction` flipping at 0.332969 against a configured 0.34 -- a
2.1 percent margin, on all four tracks at once.

**The headline finding is downgraded, on purpose.** The `refusal` STOP is now stated
conditionally: *if* those three judgements are genuinely contested, *then* the construct is
not measurable as a scalar with this pool. That is a weaker sentence and a more useful one,
because it tells a reader what to disagree with.

**Costs.** It is slow, hence outside `make all` -- and a check outside the default build
gets skipped. It always exits 0, so it informs rather than gates. It is one-at-a-time, so
it can understate fragility and never overstate it. And it cannot perturb what is not a
parameter: the annotator model's own structure -- additive bias, a single value-position
axis, gold uncontested by construction -- is a far larger assumption than anything swept.

## Alternatives considered

**Argue the flags are right.** Rejected: it restates the assumption louder and gives the
reader nothing to check.

**Drop the contested mechanism.** Rejected: it is the distinction between an imprecise
instrument and one measuring a quantity with no agreed referent, which is the project's
central claim. Removing it to avoid the criticism would remove the finding.

**A single robustness score per track.** Rejected for the reason ADR 0004 rejected a single
quality score: it collapses independent dependencies -- an assumption, a threshold, a
roster, a noise level -- whose remedies differ entirely.

**Gate on fragility.** Rejected for now. Blocking a FRAGILE verdict needs a pre-registered
budget for how fragile is too fragile, and setting that after seeing this output would
repeat the mistake in the engineering log that this ADR is partly a response to.
