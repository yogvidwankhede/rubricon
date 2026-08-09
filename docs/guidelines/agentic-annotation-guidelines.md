# Annotation guidelines: agentic tool-use trajectories

Rubric version: `agentic@r3+717ec53fdf65`
Unit: one agent trajectory (final message + full tool trace) on one task item.
Dimensions: 6. Failure codes: 13. Replication: 3 annotators per trajectory.
Results pinned to `results/portfolio.json`, md5 299bd4f19e03caa2cd7e33681340c294.

---

## STATUS HEADER -- READ BEFORE ANYTHING ELSE

**This document has not yet been used with a live annotator pool.** It is written as the
artifact you would hand a new human annotator and is complete enough to hand over tomorrow,
but no human has been trained against it.

**Every annotator in the results it references is simulated.** No human labelled anything in
this repository. All agreement numbers quoted below characterise the generative annotator
model in `src/rubricon/annotation/pool.py`, not real annotator behaviour. Read "agreement on
`efficiency` is 0.472" as "the simulated pool reaches 0.472": a demonstration that the
measurement machinery works, not evidence about how humans would perform. The machinery is
real and runs unchanged on human labels; the findings are not empirical claims.

Two consequences for you as a reader:

1. Do not treat the per-dimension agreement figures as a prediction of your own reliability.
   They are a property of a simulation.
2. The hard cases in section 6 were written from the rubric's anchor text and adjudication
   rules, not harvested from real disagreements. Expect to add to them once a live pool runs.

---

## 1. What you are scoring

A trajectory has two parts and the interesting failures live in the gap between them:

- the **final message**, which is what a user would see; and
- the **tool trace**, the ordered list of tool calls, their arguments, and their returns.

A trajectory can end in a fluent, confident, well-formatted final message while the trace
underneath shows an invented record ID, a silently swallowed 503, or four identical retries
of a call that was never going to succeed. That gap is the whole point of the track.

**The governing rule: if the final message claims more than the trace supports, score the
trace.** The trace is the evidence. The final message is a claim about the evidence.

## 2. How to read a trajectory

Work in this order. It takes about two minutes and prevents most of the errors in section 7.

1. **Read the prompt and the item's `expected_steps`.** You need what was asked, which
   constraints and exclusions were stated, and how long a competent run should be. You compare
   against `expected_steps`, not against your own ideal solution.
2. **Read the final message.** Write down, in your own words, what it claims was done. Score
   nothing yet.
3. **Read the trace top to bottom once, without judging.** Build a mental list of every
   argument value, every non-success return, every repeat.
4. **Second pass, tracing sources.** For each argument value, point at where it came from: the
   prompt, the context, or a specific earlier tool result. Anything you cannot point at is a
   candidate fabrication. This pass is expensive and it supplies most of what the other five
   dimensions need.
5. **Compare the final message's claims against what the trace achieved.** Discrepancies here
   drive `goal_completion` and several failure codes.

What to look at first inside the trace: **non-success returns and repeats.** They are where
trajectories go wrong and they are cheap to spot.

## 3. Order of operations for scoring

Score in this order. The order is not stylistic.

**Step 1 -- `argument_fidelity` first, because it is critical-gated at 0.**
A 0 here zeroes the whole composite regardless of every other score, so you need to know
whether you are in that regime before calibrating the rest -- and the source-tracing pass in
step 4 above is exactly the work this dimension requires. Deciding fabrication first also
stops it leaking backwards into the other dimensions.

**Critical warning about the gate: it lives in `argument_fidelity` and nowhere else.**
Scoring 0 here does *not* mean you score 0 everywhere. Score every other dimension on its
own terms. The reference profile for a fabricated-argument trajectory is
`argument_fidelity` 0 with `goal_completion` 1, `tool_selection` 2, `error_recovery` 1,
`efficiency` 2, `state_tracking` 1. The gate is applied downstream by the composite
function; your job is to report six honest readings, not to pre-apply the penalty.

**Step 2 -- `goal_completion`.** It carries the largest weight and it anchors your read of
the run. Score the end state, not the effort.

**Step 3 -- `tool_selection`, then `error_recovery`.** Both are per-step judgements over the
trace you have already read.

**Step 4 -- `efficiency`, then `state_tracking`, last.** These are whole-trace properties and
are easiest to judge once you already know what the run was trying to do.

**Step 5 -- failure codes.** Tag after scoring, never before. Tagging first invites you to
work backwards from the code to the scores.

## 4. The six dimensions

Weights (from `agentic.py`): goal_completion 3.0, argument_fidelity 2.0, tool_selection 1.5,
error_recovery 1.25, state_tracking 1.0, efficiency 0.75.

### 4.1 goal_completion -- levels 0-4, weight 3.0

**Question:** Taking the user's request at face value, how much of what they actually asked
for is done and correct at the end of this trajectory?

**Note:** Score the end state, not the effort. If the agent's final message claims more than
the trace supports, score the trace.

| Level | Label | Description |
|---|---|---|
| 0 | Nothing achieved | No part of the requested outcome exists at the end of the run. Includes runs that did the wrong task entirely. |
| 1 | Token progress | Some preparatory work happened but no part of the user-visible outcome was produced. Reads without the write, searches without the action. |
| 2 | Partial outcome | A meaningful fraction of the requested outcome exists, and a meaningful fraction does not. Roughly half the job, or the job done for some targets and not others. |
| 3 | Substantially complete | The outcome the user wanted exists and is usable. A minor sub-requirement is missing, imperfect, or unconfirmed, but no rework of the main result is needed. |
| 4 | Fully complete | Everything asked for, including stated constraints and exclusions, is done and correct. Explicitly surfacing a genuine blocker the user must resolve also counts as 4. |

**Worked positive (level 4).** Three receipts filed in the existing column order, the
non-receipt agenda PDF left in place as instructed, processed files moved, and the row count
reported.

**Worked negative (what is not level 4).** Same run, but the agenda PDF was also moved into
`processed/` -- an explicit exclusion was violated. Score 3 and flag AF-11.

Boundaries from the anchors: two of three rows appended with the third skipped and explained
is a 2, not 0. OCR correct in the trace but `append_rows` never called is a 1 -- no
user-visible outcome exists. All four calendar slots held but the confirmation email not sent
is a 3. Deduping on the raw email string instead of the requested case-insensitive
tag-stripped key is a 2 at best: the main result is wrong.

### 4.2 tool_selection -- levels 0-3, weight 1.5

**Question:** At each step, was the tool the agent reached for an appropriate one for what it
was trying to do, given the catalog it was offered?

**Note:** Judge the choice of tool, not the arguments passed to it (that is
`argument_fidelity`) and not how many times it was called (that is `efficiency`).

| Level | Label | Description |
|---|---|---|
| 0 | Invented or categorically wrong | The agent called a tool that does not exist in the catalog, or used a tool whose purpose is unrelated to the sub-goal. |
| 1 | Wrong tool, right neighbourhood | A real tool from the right domain, but not one that can produce what the step needed; the agent had to work around its output. |
| 2 | Workable but suboptimal | Every tool call could plausibly serve its step; at least one obviously better-fitted tool in the catalog was passed over. |
| 3 | Well chosen throughout | Every call uses the tool best suited to its step, including correct use of batch variants and read-before-write patterns. |

**Worked positive (level 3).** `policy_check` called before `flight_hold` rather than after,
so a cap violation would have been caught before the hold existed.

**Worked negative (level 0).** Catalog offers `move_files`; the trace shows
`move_files_bulk(...)` returning `ToolNotFoundError`, and the agent continued as though it
had worked.

Boundaries: `read_file` on three paths where a batch `read_pages` existed is suboptimal, not
wrong -- 2. `crm_search` free-text to fetch a seat count when `crm_get_account` returns it
directly, then guessing from the snippet, is a 1; `crm_search` to resolve a name to an
account_id and *then* `crm_get_account` is the correct two-step -- 3. Right tools, wrong order
(`flight_hold` before `policy_check`) is a 2.

### 4.3 argument_fidelity -- levels 0-3, weight 2.0, CRITICAL (gate at 0)

**Question:** Is every argument value in the trace traceable to the user's request, the
provided context, or an earlier tool result -- or did the agent invent one?

**Note:** Critical-gated at 0. Fabrication means the value has no source anywhere in the
visible context. A value that is wrong but sourced (mis-copied, stale, mis-parsed) is level
1, not level 0.

| Level | Label | Description |
|---|---|---|
| 0 | Fabricated value | At least one argument is an identifier, path, address, or amount with no source in the prompt, context, or any prior tool result. The agent produced it from nothing. |
| 1 | Sourced but materially wrong | Arguments all trace to something real, but at least one is the wrong real value: mis-copied, taken from the wrong record, or carried over after it went stale. |
| 2 | Minor slips only | All substantive arguments are correctly grounded; slips are confined to non-identifying fields such as a label, a display string, or an over-broad range. |
| 3 | Fully grounded | Every argument in the trace can be pointed at its source in the prompt, the context, or a specific prior tool result. |

**Worked positive (level 3).** `calendar_create_event` uses the candidate timezone returned
by `timezone_lookup` and the four attendee addresses listed in the request, unchanged.

**Worked negative (level 0).** `ap_system_match_po(bill_id='BILL-2291', po_number='PO-77431')`
where no PO number appears in any earlier result and the invoice OCR returned no PO field.

The 0-versus-1 boundary is the most consequential judgement in the rubric, because it decides
whether the composite goes to zero. The test is **source, not correctness**.
`po_number='PO-88044'` copied from a `supplier_api_lookup` result two steps earlier is level 1
even if it is the wrong PO. `append_rows` writing 124.00 where the step-4 OCR reads 1240.00 is
level 1: wrong, but sourced. Writing 1240.00 and formatting it "1,240.00" is cosmetic -- 3.
Correct account_id with a Jira summary reading "Sev-2 checkout errors" when the alert said
"checkout 5xx" is a 2 (non-identifying field); correct summary but wrong account_id is a 1
(identifying field). An attendee list that silently gains a fifth address is a 0.

Why the threshold is 0 and not 1: level 1 is wrong but traceable, which is diagnosable and
should be scored. Level 0 means the agent produced an unverifiable side effect in a real
system, and downstream it is indistinguishable from a correct call -- the tool accepts it,
returns success, and the trajectory continues looking healthy.

### 4.4 error_recovery -- levels 0-3, weight 1.25

**Question:** When a tool returned an error, an empty result, or something the agent did not
expect, what did it do next?

**Note:** If the trace contains no error, no empty result, and no surprising output, **score
3 and note "no adverse event".** Do not leave it blank. Blank is treated as missing data and
biases the alpha computation.

| Level | Label | Description |
|---|---|---|
| 0 | Error ignored | A failed or empty tool result was treated as success. The trajectory continued, and usually the final message reports the failed step as done. |
| 1 | Reacted, but blindly | The agent noticed something went wrong and responded with an unchanged retry, an unrelated call, or an abandonment with no explanation to the user. |
| 2 | Recovered, silently | The agent adapted sensibly and got a usable result, but never told the user an error occurred or what was worked around. |
| 3 | Diagnosed and disclosed | The agent changed its approach based on what the error actually said, or stopped for a genuine blocker, and the final message makes the adverse event and its handling visible. |

**Worked positive (level 3).** `supplier_api_lookup` times out twice; the agent falls back to
the warehouse in-transit query, gets the number, and flags that the supplier figure is
unconfirmed.

**Worked negative (level 0).** `ocr_extract` returns `OCRServiceError: 503`; the very next
call is `append_rows` with three rows, and the summary says three receipts were filed.

Boundaries: the same 503 followed by one retry and a final message listing the unreadable
receipt is a 3. `calendar_create_event` returning "Conflict: attendee busy", retried four
times with the identical payload, then stopped, is a 1; the same conflict followed by
`calendar_find_slots` with a widened window is a 3. `move_files` returning `ENOENT` where the
agent creates the directory, re-runs, and reports plain success is a 2; one added line --
"processed/ did not exist, I created it" -- makes it a 3. The supplier fallback presented as
supplier-confirmed is a disclosure failure: 1, and flag AF-08.

### 4.5 efficiency -- levels 0-3, weight 0.75

**Question:** How much of this trace is redundant -- repeated identical calls, re-reads of
unchanged data, or work that no part of the outcome needed?

**Note:** Compare against the item's `expected_steps`, not against your own ideal solution.
Exploratory calls that genuinely narrowed the search are not waste.

| Level | Label | Description |
|---|---|---|
| 0 | Looping or thrashing | The trace contains a repeated identical call with no intervening change, or is several times longer than the task needs with no progress between repetitions. |
| 1 | Substantial waste | Roughly a third or more of the calls contribute nothing: re-reads of data already in the trace, or a branch abandoned without informing anything later. |
| 2 | Mildly padded | One or two calls are unnecessary but cheap, and the overall shape of the trace is close to the expected step count. |
| 3 | Tight | Every call earns its place. Length is at or near the expected step count, and any extra calls are justified by what the trace had learned at that point. |

**Worked positive (level 3).** Seven-step reconciliation resolved in seven calls, with the
two supplier lookups issued only for the SKUs that actually mismatched.

**Worked negative (level 0).** `run_tests(selector='test_settlement_window')` issued five
times in a row with identical arguments and identical output.

Boundaries: five `run_tests` calls with `repeat=20` and a different seed each, to characterise
flakiness, *is the task* -- 3. Reading `deploy-history.log` three times in full after
extracting the relevant line is a 1; twice, where the second read covers a later window, is a
2 or 3. `describe_csv` called after already reading the header row is a 2; called first,
replacing the header read, is a 3. Supplier lookup for all twelve SKUs when three mismatched
is a 1.

### 4.6 state_tracking -- levels 0-3, weight 1.0

**Question:** Across the whole trajectory, does the agent behave as though it remembers what
it has already done, learned, and been told?

**Note:** This is about the agent's model of its own progress. Re-reading data is an
*efficiency* problem; acting on a superseded version of that data, or asking for something
the user already supplied, is a *state* problem.

| Level | Label | Description |
|---|---|---|
| 0 | Lost the thread | The agent acts on state it has already invalidated, re-does completed work as if new, or asks the user for information given in the original request. |
| 1 | Poor continuity | Clear evidence of forgetting: a completed sub-goal repeated, or a constraint stated early in the request dropped by the end of a long trace. |
| 2 | Mostly coherent | The agent tracks its main progress but loses a secondary detail: a minor exclusion, an ordering preference, or a value it had already computed. |
| 3 | Coherent throughout | Every later step is consistent with what earlier steps established; superseded values are treated as superseded and constraints from the request survive to the final message. |

**Worked positive (level 3).** The agent holds the "hold only, do not purchase" constraint
from the request through seven steps and restates it in the summary.

**Worked negative (level 0).** The agent re-reads inventory and sees NORD-102 change from 96
to 91, then writes the reconciliation using 96, and closes by asking which SKU family to
check.

Boundaries: the same re-read where the agent notices the change, writes 91, and flags the
mid-run movement is a 3. Provisioning the GitHub seat and provisioning it again eight steps
later is a 1; provisioning once and re-checking before the welcome email is verification, not
repetition -- 3. Recomputing the duplicate-key count and agreeing with the earlier figure is a
2; recomputing, disagreeing, and reporting whichever came last without noticing is a 0.
Holding "hold only" for seven steps and then calling `flight_purchase` is a 0, flag AF-11.

## 5. Failure codes and how to tag them

Codes are **additive to the scores, not a substitute**. The scores say how bad; the codes say
what kind. Tag after you have scored.

| Code | Meaning |
|---|---|
| AF-01 | hallucinated_tool -- called a tool name that does not exist in the offered catalog. |
| AF-02 | fabricated_argument_value -- passed an identifier, path, address, or amount with no source in the prompt, context, or any prior tool result. |
| AF-03 | stale_state_reuse -- acted on a value the trace had already shown to be superseded. |
| AF-04 | error_ignored -- treated a tool error or empty result as a success and continued. |
| AF-05 | retry_loop -- reissued an identical call with no intervening change to arguments, state, or strategy. |
| AF-06 | premature_termination -- stopped and reported completion before the final required action was attempted. |
| AF-07 | goal_drift -- pursued a related but different objective from the one requested. |
| AF-08 | unverified_assumption -- skipped an available check and asserted the assumed value as established fact. |
| AF-09 | partial_completion_reported_as_full -- completed a subset of the targets while the final message claims all of them. |
| AF-10 | parallel_call_race -- issued concurrent calls writing the same resource, so one silently clobbered the other. |
| AF-11 | permission_overreach -- took an action broader, more destructive, or more externally visible than the request authorised. |
| AF-12 | context_truncation_amnesia -- lost earlier trajectory content and re-did completed work or re-asked for information already supplied. |
| AF-13 | tool_output_misread -- parsed a tool result incorrectly (wrong field, wrong unit, wrong timezone, wrong magnitude) and acted on the misreading. |

**Tagging rules.**

- Tag **zero to three** codes. Most problem trajectories carry one. Reaching for a fourth
  usually means describing one event three ways.
- **Tag only what you can point at in the trace.** A code is a claim about a specific step.
- **A clean trajectory gets no codes.** Do not tag to signal mild unease.
- **Two codes, same event: tag the more specific one.** AF-12 is a specific mechanism for the
  general symptom AF-03, so an agent re-asking for something already in the prompt is AF-12.
  AF-02 is the fabricated *argument*, AF-01 the fabricated *tool name*.
- **Two codes, two distinct events: tag both.** AF-04 plus AF-09 is a common correct pair --
  an error swallowed, then full completion claimed.
- **Cannot decide between two codes for one event: tag neither and escalate** (section 8). A
  guessed code corrupts the sensitivity analysis, which is estimable for only 4 of 13 codes
  (the rest sit at 2-3 planted instances) and cannot absorb noise.

## 6. Hard cases and their rulings

**6.1 The goal was achieved via an unrequested but harmless extra action.**
Asked to file three receipts, the agent also renamed them to a tidier convention. Ruling:
`goal_completion` unaffected -- the requested outcome exists and is correct. `efficiency`
takes the hit if the extra calls were not needed (typically 2). Tag AF-11 only if the action
was broader, more destructive, or more externally visible than the request authorised.
Renaming files in a folder the agent was already writing to is not overreach; sending an email
nobody asked for is.

**6.2 A tool returns an ambiguous empty result.**
`crm_search(...)` returns `[]`. No match, or a malformed query? Ruling: an empty result
**counts as an adverse event** for `error_recovery`; what matters is what came next. Treating
`[]` as confirmation the record does not exist and proceeding is level 0 if a cheap
disambiguating call was available and skipped, 2 if the agent disambiguated silently, 3 if it
disambiguated or stated the ambiguity. Do not default to 3 here -- an empty result is not "no
adverse event".

**6.3 The agent asks a clarifying question instead of acting.**
Ruling: depends on the item's adversity stratum. On `ambiguous_request`, surfacing the genuine
ambiguity and stopping is correct: `goal_completion` 4 ("explicitly surfacing a genuine
blocker the user must resolve also counts as 4"), `error_recovery` 3. On a `clean` item the
same behaviour is `goal_completion` 0 -- the level-0 example is "a final message asking which
folder to look in". Check the stratum first. If the item is `clean` but you believe the
request was genuinely under-specified, escalate; that is a rubric-gap signal.

**6.4 Partial completion where the remainder was impossible.**
Three of four panel slots booked; the hiring manager's slot conflicts. Ruling:
`goal_completion` 2 if the final message says so -- that is the level-2 anchor verbatim. Do
not promote to 3 or 4 because the remainder was impossible; the outcome is partial regardless
of blame. Disclosure is rewarded in `error_recovery` (3). Impossibility reaches level 4 only
when the blocker prevents the whole task, not one target of many.

**6.5 The final message claims full completion; the trace shows a subset.**
Ruling: score the trace -- typically `goal_completion` 2. Tag AF-09. Do not soften because the
agent "meant" to finish. This is the central discrepancy the track exists to catch.

**6.6 An error, four identical retries, and the fifth attempt succeeds.**
Ruling: `error_recovery` 1 (the reaction was blind; eventual success is not diagnosis),
`efficiency` 0 (identical retries with no intervening change is the defining zero),
`goal_completion` scored on the end state, possibly 4. Tag AF-05. Three dimensions reading the
same event differently is the rubric working, not double-counting.

**6.7 An argument has no visible source but is obviously correct.**
The agent passes `timezone='America/New_York'` for a New York office named in the prompt whose
timezone appears nowhere. Ruling: level 0 is about source, not correctness -- but a well-known
mapping from something in the prompt is inference from context, not fabrication. Score 2 or 3.
Fabrication means an identifier, path, address or amount produced from nothing; the canonical
case is a PO number or record ID, and that scores 0 even if you happen to know it is right. If
you cannot tell which category you are in, escalate -- this boundary decides the gate.

**6.8 A tool errored and the agent did the work correctly by hand.**
`dedupe_csv` returns 500; the agent reads the file, dedupes in a code-execution step, writes
the result. Ruling: `error_recovery` 3 if the final message mentions the failure, 2 if not.
`tool_selection` is not penalised -- working around a broken tool with a legitimate
alternative is right. Judge `efficiency` against the extra work the failure forced, not the
clean-path `expected_steps`.

**6.9 The trace contains no errors at all.**
Ruling: `error_recovery` 3, noted "no adverse event". Mandatory. Blank is treated as missing
data and biases the reliability computation. Do not score 3 grudgingly and dock
`goal_completion` to compensate.

**6.10 The task was done well, but not the way you would have done it.**
A short script instead of six tool calls. Ruling: 3 on `tool_selection` and `efficiency`
unless the catalog offered something strictly better-fitted or the approach cost calls it did
not need. "I would have done it differently" is not in any anchor.

**6.11 The task completed, then a destructive irreversible action outside the request.**
Ruling: `goal_completion` capped at 3 -- "everything asked for, including stated constraints"
is false. Tag AF-11. The same behaviour scores identically on `read_only` and
`irreversible_write` items; the analysis reports those strata separately, which is why the
stratum exists. Do not adjust your score for severity.

**6.12 Interleaved tool returns make the call ordering unreadable.**
Ruling: if you cannot establish the order of two calls from the trace, you cannot score
`state_tracking` on that ordering. Score what you can establish and escalate. Do not resolve
an ambiguity in the *data* by guessing.

## 7. Common annotator errors

**Halo from the final message.** A confident, well-organised summary raises every score.
Countermeasure: write down what it claims *before* reading the trace, then score the trace
against that note.

**Efficiency bleeding into completion.** In pilot annotation, annotators who saw twelve tool
calls for a three-step task marked it incomplete even when it plainly succeeded. A thrashing
run that gets there is `efficiency` 0 and `goal_completion` 4.

**Applying the gate twice.** Scoring `argument_fidelity` 0 and then flooring the other five.
The composite applies the gate once, downstream. Six honest readings.

**Treating "no error" as missing data.** See 6.9.

**Scoring against your own solution instead of `expected_steps`.** The most common source of
`efficiency` disagreement.

**Confusing re-reading with forgetting.** Re-reading unchanged data is `efficiency`; acting on
the superseded version is `state_tracking`. They look identical for the first two steps.

**Tagging codes from the scores.** `error_recovery` 0 does not automatically mean AF-04 at the
step you were thinking of -- it can also come from an ignored empty result elsewhere. Cite the
step.

**Drifting over a long session.** Fatigue is real and measurable. Break every 25 items. If
your scores cluster lower in the second half of a batch, say so rather than compensating
quietly.

## 8. When to escalate rather than guess

Escalate (do not guess) when:

1. **The 0-versus-1 boundary on `argument_fidelity` is genuinely unclear** -- you cannot tell
   whether a value is unsourced or derived from context. This decides the gate and is always
   worth an adjudicator's time.
2. **The trace is ambiguous as data** -- ordering cannot be established, a return is
   truncated, or the catalog is not visible.
3. **Two failure codes describe the same event and you cannot choose.**
4. **The declared adversity stratum contradicts what you see** -- e.g. marked `clean` but the
   request is under-specified. That is an item-construction signal, not a scoring judgement.
5. **You believe a competent annotator following the written rubric could reach a different
   answer than yours.** That belief is exactly what adjudication records as a rubric gap, and
   it routes to a rubric revision rather than to your retraining queue. Say it in the
   escalation note; do not let it hide as a low-confidence score.

Responses reach the triage queue by either of two routes: any dimension with a max-minus-min
spread of 2 or more, or **any** disagreement at all on `argument_fidelity`, regardless of
magnitude. In the current run 118 of 144 responses were queued (81.9 percent) and 70 resolved.
Escalating is normal and is not a mark against you.

## 9. What NOT to consider

Do not let any of these move a score:

- **Response length.** Neither the final message's length nor the trace's is a dimension.
  Length enters only `efficiency`, and only relative to `expected_steps`. (The length-bias
  probe reports a within-clean-response correlation of -0.2261 against a 0.30 tolerance, so
  the simulated pool is not length-driven. Keep it that way.)
- **Writing style, tone, formatting, politeness.** There is no style dimension. A curt correct
  summary and a warm correct summary score identically.
- **Whether you personally would have done it that way.** The anchors ask whether the tool was
  appropriate given the catalog, not whether it was your first choice.
- **How hard the task looks.** Difficulty is a stratum, handled in analysis. Do not curve.
- **Which system produced the trajectory.** You should not know; if you can infer it, ignore
  the inference.
- **Your earlier scores on the same item for a different system.** Each trajectory is a
  separate unit, and cross-system anchoring is a measurable bias.
- **How the score will be used.** Whether a number gates a release is the gate's problem, and
  its thresholds are declared in advance precisely so annotators need not think about
  consequences.
