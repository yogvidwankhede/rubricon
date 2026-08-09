# ADR 0001: Content-addressed rubric versions

Date: 2026-04-27 (reconstructed from working notes; the repository carries no commit history)

Results pinned to `results/portfolio.json`, md5 299bd4f19e03caa2cd7e33681340c294. Re-running the pipeline changes
every figure quoted below; check the hash before quoting them.

**Annotators are simulated.** No human labelled anything in this repository. The one
agreement figure quoted below is a property of the generative annotator model in
`src/rubricon/annotation/pool.py`, not an observation of people. The versioning mechanism
this ADR decides is independent of that and would run unchanged on human labels.

## Status

Accepted. Implemented in `src/rubricon/core/schema.py`. In force for all four tracks.

## Context

An annotation programme accumulates labels over months, and the rubric changes during that
time: an anchor gets a counter-example, a dimension is split, a critical threshold moves. Each
change alters what a score *means*.

The resulting failure is silent. Labels collected under two definitions get pooled into one
reliability computation, one mean, one system comparison, and nothing errors. Either agreement
comes back lower and gets blamed on annotator quality -- so the programme retrains people
against a rubric that was never the problem -- or it comes back fine because the change was
small, and the mean quietly mixes two measurement scales.

Manual version strings do not solve this. A human-maintained `rubric_version = "v2"` depends
on somebody remembering to bump it in the same commit that changed the anchor text, which is
exactly the discipline that fails under deadline.

## Decision

A rubric's version string is `{key}@r{revision}+{hash}`, where the hash is a SHA-256 digest,
truncated to 12 hex characters, over the canonical JSON serialisation of **every dimension
and every anchor**, including descriptions, examples, and counter-examples.

The current agentic rubric is `agentic@r3+717ec53fdf65`.

Consequences of the design:

- `revision` is human-curated and carries the changelog. It communicates intent.
- The hash is machine-derived and carries the truth. Change one word of one
  counter-example and the hash changes.
- Every `Annotation` record stores the version string it was produced under. Provenance is
  per-label, not per-run.
- The version is a property of the whole rubric. Labels from two versions are never poolable,
  even for unchanged dimensions.

The `agentic` changelog records the three revisions:

- r1: initial five-dimension draft, no `state_tracking`.
- r2: `state_tracking` split out of `error_recovery` after pilot annotators conflated
  "forgot" with "failed to recover". (The changelog records alpha 0.31 on the merged
  dimension. That figure lives in the rubric changelog in `agentic.py` and is *not*
  reproducible from `results/portfolio.json`, which only contains the current revision.)
- r3: `argument_fidelity` critical threshold moved from 1 to 0, so that sourced-but-wrong
  values are scored rather than gated, and every anchor gained an explicit counter-example.

Note that r3's threshold change alone would alter the composite for a large fraction of the
corpus while leaving every dimension score identical. That is precisely the kind of change a
manual version string gets wrong.

## Consequences

**Good.**

- Pooling across definitions becomes impossible by accident. It can still be done
  deliberately, and then it is visible in the data.
- The re-anchoring procedure in the calibration protocol has a hard trigger: hash changed,
  bridge sample required.
- A report can assert "these numbers came from this exact instrument" and the assertion is
  checkable by anyone with the JSONL, without access to the code.

**Costly.**

- Rubric edits are expensive. Fixing a typo in a counter-example invalidates pooling with every
  prior label. This has produced a batching discipline -- edits collected and applied at a
  revision boundary -- which is a good outcome, but it does slow obvious corrections.
- No partial credit: a cosmetic change and a semantic one invalidate identically. We considered
  excluding example text from the hash as merely illustrative and rejected it, because the r3
  change was *entirely* counter-examples and it materially changed how anchors read.
- Historical labels become archival. The bridge sample is the only path forward, at 120 labels
  per revision.

## Alternatives considered

**Manual semantic versioning.** Rejected: depends on discipline at exactly the moment
discipline fails, and gives no way to detect a missed bump after the fact.

**Per-dimension hashes with partial pooling.** Rejected: annotators score the rubric as a
whole, and the r2 split is the counter-example -- moving `state_tracking` out of
`error_recovery` changed the meaning of `error_recovery` scores without editing a single
`error_recovery` anchor.

**Git commit SHA as the version.** Rejected: it changes when unrelated code changes, so it
over-invalidates, and it is unavailable to anyone reading exported JSONL without the repo.

**No versioning; rely on run directories.** Rejected. This is the industry default and it is
the source of the failure mode described in the context section.
