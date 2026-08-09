# ADR 0004: Depth tiers as a declared contract on what a track may claim

Date: 2026-05-21 (reconstructed from working notes; the repository carries no commit history)

Results pinned to `results/portfolio.json`, md5 299bd4f19e03caa2cd7e33681340c294. Re-running the pipeline changes
every figure quoted below; check the hash before quoting them.

**Annotators are simulated.** No human labelled anything in this repository. Every
agreement and block-count figure below is a property of the generative annotator model in
`src/rubricon/annotation/pool.py`. The depth-contract mechanism this ADR decides does not
read the annotator traits and would run unchanged on human labels; the numbers used to
illustrate it are demonstrations, not empirical claims about any language model.

## Status

Accepted. Implemented in `src/rubricon/tracks/__init__.py` (`DEPTH_ORDER`, `DEPTH_CONTRACT`)
and enforced in `SignalGate.check_depth_contract`.

## Context

Tracks are built at different levels of rigour, and that is correct -- a hypothesis-generating
probe should not cost what a release gate costs. The problem is that the difference is
implicit. A track built in two days produces numbers that look identical to those from a track
built over two months with a powered sampling design. Both render as a mean and an interval.

What follows is predictable. The exploratory track shows System A ahead of System B, somebody
puts it on a slide, and the caveat -- "this was never powered for a between-system comparison"
-- lives in the analyst's head or in a paragraph nobody read.

Rigour is a property of the *design*, fixed before collection; claims are made *after*, when
the design is no longer visible. Post-hoc caution does not work, because once a number exists
the burden falls on whoever wants to withhold it.

## Decision

Every track declares a `depth` at registration: `exploratory`, `pilot`, or `production`. The
depth carries a written contract on what claims the track may support, and the gate enforces
it mechanically.

Registration is discovery, not an import list: `tracks/__init__.py` walks
`pkgutil.iter_modules` and registers every sibling module exposing the `SPEC` /
`seed_items` / `fixture_responses` protocol. Adding a track requires no harness edit, and
the declared depth therefore travels with the track module rather than with a central
table somebody has to remember to update. `results/sensitivity.json` records what
discovery found on this run: all four tracks, none skipped, none missing an effects-table
entry.

| Depth | Contract |
|---|---|
| exploratory | Hypothesis generation only. May report descriptive statistics and qualitative failure examples. May NOT report system rankings, deltas between systems, or any claim framed as a measurement. |
| pilot | May report measurements with intervals and an explicit MDE. May report system deltas ONLY when the interval excludes zero and the delta exceeds the MDE. May not be used as a release gate. |
| production | May report measurements, system rankings, and may act as a release gate, provided all signal-gate checks pass. |

Enforcement is a numeric comparison. Claim kinds map to required levels -- `descriptive` 0,
`measurement` 1, `ranking` and `release_gate` 2 -- checked against `DEPTH_ORDER`. A track below
the required level is BLOCKed regardless of how good its statistics are.

Depth also selects the gate policy. `EXPLORATORY_POLICY` loosens the reliability floor to 0.30,
the warn threshold to 0.50, the CI half-width budget to 0.15 and the minimum cell count to 3,
waives the MDE requirement, and disables drift blocking. Its existence is the point: it makes
"we relaxed the bar here" explicit and reviewable rather than something that happens by
omission.

The portfolio's four tracks sit at: `agentic` production, `grounding` pilot, `reasoning`
pilot, `refusal` exploratory.

## Why an exploratory track is mechanically barred from ranking

Because the bar is not about the numbers. It is about the design that produced them.

An exploratory track's sampling frame was never built to support a between-system comparison:
n is chosen for coverage, not power; strata for variety, not balance; and items are frequently
selected *because* they looked interesting, which is the definition of a biased sample for
estimating a difference. None of that is visible in the output -- an interval computed on a
purposive sample looks exactly like one computed on a powered design.

So the gate does not infer design quality from results. It reads the declared depth and blocks.
This is deliberately blunt: an exploratory track with unexpectedly good agreement is still
blocked from ranking, and the right response is to promote it through the re-certification
criteria, not to argue that this particular result is fine.

`refusal` is the working example. Its depth-contract check blocks all three measurement claims
and all three ranking claims before any statistical check runs. Those claims then also fail on
their own merits -- the rubric-gap rate is 0.69 against a 0.15 budget, and one ranking interval
contains zero -- but the depth block fires first and would have fired even if they had not. Of
11 claims on that track, 8 are blocked. Two dimensions, `over_refusal_cost` (alpha 0.2864) and
`tone_respect` (alpha 0.2640), are additionally blocked for falling below even the relaxed 0.30
exploratory floor.

## Consequences

**Good.**

- The caveat travels with the track, in the registration, rather than in an analyst's memory.
- Promotion becomes an explicit event with criteria, not a gradual drift in how seriously a
  number is taken.
- The contract text is written in claim language ("may NOT report system rankings"), so it can
  be pasted into a report where a claim is withheld. Readers get the reason, not the absence.
- It gives cheap work a legitimate home. Without tiers the pressure is to make every track
  production-grade or not build it, which kills exploration.

**Costly.**

- The tier is self-declared. Nothing stops an author registering an underpowered track as
  `production`; the re-certification criteria are the intended control, and they are a review
  process, not a mechanism.
- Three tiers is coarse. `agentic` satisfies production criteria for scalar reporting against a
  single baseline but not for pairwise or per-dimension ranking -- five of six dimensions below
  0.667, two below the 0.500 blocking floor, and the position-bias fragility probe fails. One
  tier cannot express that, so the split lives in prose in the task spec, which is the "caveat
  in a paragraph" failure this ADR was written against.
- Demotion is socially expensive in a way promotion is not, and the mechanism does not help.

## Alternatives considered

**Infer permitted claims from the statistics alone.** Rejected: statistics cannot see
sampling-frame bias, and a purposive sample can produce a tight interval around a meaningless
quantity.

**A single quality score per track.** Rejected: it collapses independent failure modes
(reliability, coverage, power, pool health) whose remedies differ. The gate reports them
separately for the same reason.

**Continuous depth (0 to 1).** Rejected as false precision, and it would invite arguing a
track from 0.68 to 0.71 rather than meeting a criterion.

**No tiers; rely on report prose.** Rejected. That is the status quo this ADR replaces, and the
`refusal` track -- 8 of 11 claims blocked, mean alpha 0.3548, STOP recommendation -- is what it
looks like when prose is the only defence.
