"""Guards annotator assignment, batching, triage and adjudication.

Class of regression protected here: an assignment scheme that manufactures the
statistic it is supposed to measure.

Three specific historical defects are pinned:

* **The stride bug.** Rotating the annotator window by ``k`` produced only two
  fixed triples, so pool composition became a function of batch and the drift
  detector reported drift that was purely an artifact. A contiguous window of
  size ``k`` has a subtler version of the same disease: antipodal annotator
  pairs never co-occur, so agreement is estimated over a subgraph of the pool.
  Both are caught by the pair-coverage test.
* **The systematic-sampling gradient.** Plain round-robin over a
  difficulty-sorted corpus guarantees a monotone difficulty gradient across
  batches, which is exactly the confound the drift statistic assumes away.
* **Batch/roster resonance.** A batch count sharing a factor with the roster
  size makes pool composition periodic in batch. That must raise, not warn.

Plus the triage rules (critical dimensions escalate on any disagreement) and
the adjudication capacity constraint that keeps "we adjudicated the top 60%"
stated rather than implied.
"""

from __future__ import annotations

import itertools
import statistics
from collections import Counter, defaultdict

import pytest

from rubricon.annotation.adjudicate import (
    adjudicate,
    adjudication_summary,
    post_adjudication_agreement,
    triage,
)
from rubricon.annotation.pool import ROSTER, annotate, item_difficulty
from rubricon.stats.drift import profile_annotators
from rubricon.tracks import get

from .conftest import annotation_row, make_dimension, make_rubric, make_spec

# The smallest real track; used because assignment balance is a property of the
# real corpus shape, not of a hand-built toy.
TRACK_KEY = "refusal"


@pytest.fixture(scope="module")
def track_fixture():
    track = get(TRACK_KEY)
    return track.spec, track.items(), track.responses()


@pytest.fixture(scope="module")
def annotations(track_fixture):
    spec, items, responses = track_fixture
    return annotate(spec, items, responses)


# --------------------------------------------------------------------------
# determinism and completeness
# --------------------------------------------------------------------------


def test_annotate_is_deterministic(track_fixture):
    spec, items, responses = track_fixture
    first = annotate(spec, items, responses)
    second = annotate(spec, items, responses)
    assert len(first) == len(second)
    assert first == second
    assert [a.to_dict() for a in first] == [a.to_dict() for a in second]


def test_every_response_gets_exactly_the_specified_replication(track_fixture, annotations):
    spec, _items, responses = track_fixture
    per_response = Counter(a.response_id for a in annotations)
    assert set(per_response) == {r.response_id for r in responses}
    assert set(per_response.values()) == {spec.replication}
    assert len(annotations) == len(responses) * spec.replication


def test_a_response_is_never_annotated_twice_by_the_same_annotator(annotations):
    seen = defaultdict(set)
    for a in annotations:
        assert a.annotator_id not in seen[a.response_id]
        seen[a.response_id].add(a.annotator_id)


def test_annotations_carry_the_rubric_version(track_fixture, annotations):
    spec, _items, _responses = track_fixture
    assert {a.rubric_version for a in annotations} == {spec.rubric.version}


# --------------------------------------------------------------------------
# assignment balance
# --------------------------------------------------------------------------


def test_annotator_workload_is_balanced(annotations):
    load = Counter(a.annotator_id for a in annotations)
    assert set(load) == {a.annotator_id for a in ROSTER}
    busiest, least = max(load.values()), min(load.values())
    assert busiest <= least * 1.25, (
        f"workload spread {load}: busiest {busiest} exceeds least busy {least} by "
        "more than 25%"
    )


def test_every_annotator_pair_co_occurs_at_least_once(annotations):
    """Regression: contiguous / stride-k windows leave pairs that never meet.

    A pair that never shares a response contributes nothing to any agreement
    coefficient, so alpha is computed over a proper subgraph of the pool while
    being reported as a property of the pool.
    """
    by_response = defaultdict(list)
    for a in annotations:
        by_response[a.response_id].append(a.annotator_id)

    observed = set()
    for assigned in by_response.values():
        for pair in itertools.combinations(sorted(assigned), 2):
            observed.add(pair)

    expected = set(
        itertools.combinations(sorted(a.annotator_id for a in ROSTER), 2)
    )
    missing = expected - observed
    assert not missing, f"annotator pairs that never co-occur: {sorted(missing)}"


def test_assignment_is_not_reducible_to_a_handful_of_fixed_teams():
    """The stride-k bug produced exactly two distinct triples."""
    track = get(TRACK_KEY)
    rows = annotate(track.spec, track.items(), track.responses())
    by_response = defaultdict(set)
    for a in rows:
        by_response[a.response_id].add(a.annotator_id)
    distinct_teams = {frozenset(v) for v in by_response.values()}
    assert len(distinct_teams) >= len(ROSTER), (
        f"only {len(distinct_teams)} distinct annotator teams were used"
    )


# --------------------------------------------------------------------------
# batching
# --------------------------------------------------------------------------


@pytest.mark.parametrize("track_key", ["refusal", "grounding", "reasoning", "agentic"])
def test_batches_carry_a_balanced_item_difficulty_mix(track_key):
    """Regression: plain round-robin over difficulty rank creates a gradient.

    The drift statistic is only interpretable if item difficulty mix is held
    constant across batches, so an unbalanced deal silently invalidates it.
    """
    track = get(track_key)
    items = track.items()
    rows = annotate(track.spec, items, track.responses())
    by_item = {i.item_id: i for i in items}

    per_batch = defaultdict(list)
    for a in rows:
        per_batch[a.batch].append(item_difficulty(by_item[a.item_id]))

    assert len(per_batch) >= 2
    overall = statistics.fmean([d for v in per_batch.values() for d in v])
    for batch, difficulties in sorted(per_batch.items()):
        deviation = abs(statistics.fmean(difficulties) - overall)
        assert deviation <= 0.10 * overall, (
            f"{track_key} batch {batch} mean difficulty deviates by {deviation:.4f} "
            f"from the overall mean {overall:.4f}"
        )


def test_batch_means_do_not_trend_monotonically_with_batch_index():
    """A monotone gradient is the signature of systematic sampling."""
    track = get(TRACK_KEY)
    items = track.items()
    rows = annotate(track.spec, items, track.responses())
    by_item = {i.item_id: i for i in items}
    per_batch = defaultdict(list)
    for a in rows:
        per_batch[a.batch].append(item_difficulty(by_item[a.item_id]))
    means = [statistics.fmean(per_batch[b]) for b in sorted(per_batch)]
    strictly_down = all(x > y for x, y in zip(means, means[1:]))
    strictly_up = all(x < y for x, y in zip(means, means[1:]))
    assert not strictly_down and not strictly_up, f"monotone batch means {means}"


def test_replicates_of_one_response_are_spread_across_batches(annotations):
    """What makes drift identifiable rather than confounded with response quality."""
    by_response = defaultdict(set)
    for a in annotations:
        by_response[a.response_id].add(a.batch)
    all_in_one_batch = sum(1 for v in by_response.values() if len(v) == 1)
    assert all_in_one_batch == 0


def test_non_coprime_batch_count_raises(track_fixture):
    spec, items, responses = track_fixture
    assert len(ROSTER) == 6
    with pytest.raises(ValueError) as exc:
        annotate(spec, items, responses, n_batches=4)  # gcd(4, 6) == 2
    assert "shares a factor" in str(exc.value)
    assert "coprime" in str(exc.value)

    with pytest.raises(ValueError):
        annotate(spec, items, responses, n_batches=6)  # gcd(6, 6) == 6

    # A coprime count is accepted.
    assert annotate(spec, items, responses, n_batches=7)


def test_replication_above_roster_size_raises(track_fixture):
    spec, items, responses = track_fixture
    with pytest.raises(ValueError) as exc:
        annotate(spec, items, responses, replication=len(ROSTER) + 1)
    assert "exceeds roster size" in str(exc.value)


# --------------------------------------------------------------------------
# triage
# --------------------------------------------------------------------------


def _critical_spec():
    rubric = make_rubric(
        dimensions=(
            make_dimension(key="fidelity", levels=(0, 1, 2, 3), weight=1.0,
                           critical=True, critical_threshold=0),
            make_dimension(key="style", levels=(0, 1, 2, 3), weight=1.0),
        )
    )
    return make_spec(rubric=rubric, key="mini-critical")


def test_triage_flags_any_disagreement_on_a_critical_dimension():
    spec = _critical_spec()
    rows = [
        # one point apart on the critical dimension, identical elsewhere
        annotation_row("r1", "A1", {"fidelity": 2, "style": 2}, item_id="i1"),
        annotation_row("r1", "A2", {"fidelity": 3, "style": 2}, item_id="i1"),
        # complete agreement: must not be queued
        annotation_row("r2", "A1", {"fidelity": 3, "style": 1}, item_id="i2"),
        annotation_row("r2", "A2", {"fidelity": 3, "style": 1}, item_id="i2"),
        # a one-point gap on a NON-critical dimension: below the spread threshold
        annotation_row("r3", "A1", {"fidelity": 2, "style": 1}, item_id="i3"),
        annotation_row("r3", "A2", {"fidelity": 2, "style": 2}, item_id="i3"),
    ]
    queue = triage(rows, spec, spread_threshold=2)
    queued = {t.response_id for t in queue}
    assert "r1" in queued, "a 1-point split on a critical dimension must escalate"
    assert "r2" not in queued
    assert "r3" not in queued

    item = next(t for t in queue if t.response_id == "r1")
    assert item.max_spread == 1
    assert "critical dimension fidelity" in item.reason


def test_triage_flags_large_spread_on_any_dimension():
    spec = _critical_spec()
    rows = [
        annotation_row("r1", "A1", {"fidelity": 3, "style": 0}, item_id="i1"),
        annotation_row("r1", "A2", {"fidelity": 3, "style": 3}, item_id="i1"),
    ]
    queue = triage(rows, spec, spread_threshold=2)
    assert len(queue) == 1
    assert "spread>=2 on style" in queue[0].reason


def test_triage_sorts_by_descending_priority():
    spec = _critical_spec()
    rows = []
    # r_low: one-point critical disagreement only
    rows += [
        annotation_row("r_low", "A1", {"fidelity": 2, "style": 2}, item_id="i1"),
        annotation_row("r_low", "A2", {"fidelity": 3, "style": 2}, item_id="i1"),
    ]
    # r_high: critical disagreement AND a wide style spread
    rows += [
        annotation_row("r_high", "A1", {"fidelity": 0, "style": 0}, item_id="i2"),
        annotation_row("r_high", "A2", {"fidelity": 3, "style": 3}, item_id="i2"),
    ]
    # r_mid: wide style spread only
    rows += [
        annotation_row("r_mid", "A1", {"fidelity": 2, "style": 0}, item_id="i3"),
        annotation_row("r_mid", "A2", {"fidelity": 2, "style": 3}, item_id="i3"),
    ]
    queue = triage(rows, spec, spread_threshold=2)
    priorities = [t.priority for t in queue]
    assert priorities == sorted(priorities, reverse=True)
    assert queue[0].response_id == "r_high"


def test_triage_skips_singly_annotated_responses():
    spec = _critical_spec()
    rows = [annotation_row("r1", "A1", {"fidelity": 0, "style": 0}, item_id="i1")]
    assert triage(rows, spec) == []


# --------------------------------------------------------------------------
# adjudication
# --------------------------------------------------------------------------


def _queue_and_rows(n=5):
    spec = _critical_spec()
    rows = []
    for i in range(n):
        rid = f"r{i}"
        rows += [
            annotation_row(rid, "A1", {"fidelity": 0, "style": 0}, item_id=f"i{i}"),
            annotation_row(rid, "A2", {"fidelity": 3, "style": 3}, item_id=f"i{i}"),
            annotation_row(rid, "A3", {"fidelity": 1, "style": 2}, item_id=f"i{i}"),
        ]
    return spec, rows, triage(rows, spec)


def test_adjudicate_respects_capacity():
    spec, rows, queue = _queue_and_rows(n=5)
    assert len(queue) == 5
    resolved = adjudicate(queue, rows, spec, capacity=2)
    assert len(resolved) == 2
    # Resolved in priority order.
    assert [a.response_id for a in resolved] == [t.response_id for t in queue[:2]]


def test_adjudicate_without_capacity_resolves_the_whole_queue():
    spec, rows, queue = _queue_and_rows(n=4)
    assert len(adjudicate(queue, rows, spec)) == len(queue)


def test_adjudication_uses_the_median_and_floors_critical_ties():
    spec = _critical_spec()
    rows = [
        annotation_row("r0", "A1", {"fidelity": 1, "style": 1}, item_id="i0"),
        annotation_row("r0", "A2", {"fidelity": 2, "style": 2}, item_id="i0"),
    ]
    queue = triage(rows, spec, spread_threshold=1)
    assert queue
    result = adjudicate(queue, rows, spec)[0]
    # median of (1, 2) is 1.5 -> critical dimensions floor, others round
    assert result.final_scores["fidelity"] == 1
    assert result.final_scores["style"] == 2


def test_adjudication_summary_reports_the_unresolved_remainder():
    spec, rows, queue = _queue_and_rows(n=5)
    resolved = adjudicate(queue, rows, spec, capacity=3)
    summary = adjudication_summary(queue, resolved, n_responses=10)
    assert summary["n_queued"] == 5
    assert summary["n_resolved"] == 3
    assert summary["n_unresolved"] == 2
    assert abs(summary["resolution_rate"] - 0.6) < 1e-9
    assert abs(summary["queue_rate"] - 0.5) < 1e-9
    assert "PRE-adjudication" in summary["accounting_note"]


def test_adjudication_is_deterministic():
    spec, rows, queue = _queue_and_rows(n=4)
    first = [a.to_dict() for a in adjudicate(queue, rows, spec)]
    second = [a.to_dict() for a in adjudicate(queue, rows, spec)]
    assert first == second


def test_rubric_gap_is_not_flagged_when_no_dimension_is_contested():
    """A custom track declares no contested dimensions, so nothing is a gap."""
    spec, rows, queue = _queue_and_rows(n=5)
    resolved = adjudicate(queue, rows, spec)
    assert all(not a.rubric_gap_flagged for a in resolved)
    assert all("annotator error" in a.notes for a in resolved)


# --------------------------------------------------------------------------
# annotator profiling: leniency bias vs. value position
# --------------------------------------------------------------------------


def _two_dimension_pool():
    """A pool where the only real defect is one lenient annotator.

    ``contested`` is a dimension the rubric does not determine: A1 sits at the
    bottom of it and A2 at the top, consistently, on every response, while both
    score ``settled`` exactly as the five neutral annotators do. Neither is
    lenient. A3 IS lenient -- it marks everything up by 2 points on BOTH
    dimensions, which is what a scoring-calibration defect actually looks like.

    An offset computed over both dimensions cannot tell A1/A2 apart from A3.
    That is the conflation this fixture exists to catch.

    Exact arithmetic, 8 annotators:
      settled  -- pool mean is shifted +2/8 = +0.25 by A3, so the seven others
                  sit at -0.25 and A3 at +1.75.
      contested-- values are 0, 4, 4 and 2 x five; mean 2.25. A1 is at -2.25,
                  A2 and A3 at +1.75, the neutrals at -0.25.
      position = contested offset - leniency offset:
                  A1 -2.00 , A2 +2.00 , A3 0.00 , neutrals 0.00.
    """
    neutral = ("A4", "A5", "A6", "A7", "A8")
    rows = []
    for i in range(21):
        rid, iid = f"r{i}", f"i{i}"
        settled = i % 3                     # 0..2, so +2 never clips the scale
        rows.append(annotation_row(rid, "A1", {"settled": settled, "contested": 0}, item_id=iid))
        rows.append(annotation_row(rid, "A2", {"settled": settled, "contested": 4}, item_id=iid))
        rows.append(annotation_row(rid, "A3",
                                   {"settled": settled + 2, "contested": 4}, item_id=iid))
        for aid in neutral:
            rows.append(annotation_row(rid, aid, {"settled": settled, "contested": 2},
                                       item_id=iid))
    return rows


def test_value_position_is_not_reported_as_leniency_bias():
    rows = _two_dimension_pool()
    profile = profile_annotators(
        rows, ["settled", "contested"], contested_dimensions=["contested"],
    )
    by_id = {a["annotator_id"]: a for a in profile["annotators"]}

    # A1 and A2 diverge sharply overall, purely through the contested dimension.
    assert abs(by_id["A1"]["bias_vs_pool"]) > 0.35
    assert abs(by_id["A2"]["bias_vs_pool"]) > 0.35
    # Their leniency, measured where the rubric determines the answer, is the
    # same -0.25 every non-lenient annotator shows (A3 drags the pool mean up),
    # and it is well inside the 0.35 flagging threshold.
    assert abs(by_id["A1"]["bias_vs_pool_uncontested"] + 0.25) < 1e-9
    assert abs(by_id["A2"]["bias_vs_pool_uncontested"] + 0.25) < 1e-9
    assert by_id["A1"]["bias_vs_pool_uncontested"] == by_id["A4"]["bias_vs_pool_uncontested"]
    # So neither is flagged for bias...
    for aid in ("A1", "A2"):
        assert not any(f.startswith("systematic_bias") for f in by_id[aid]["flags"])
    # ...and their positions are reported under a different, non-defect name.
    assert by_id["A1"]["positions"] == ["contested_position:-2.00"]
    assert by_id["A2"]["positions"] == ["contested_position:+2.00"]
    assert "A1" not in profile["flagged_annotators"]
    assert "A2" not in profile["flagged_annotators"]
    assert set(profile["divergent_on_contested"]) == {"A1", "A2"}


def test_genuine_leniency_is_still_flagged():
    rows = _two_dimension_pool()
    profile = profile_annotators(
        rows, ["settled", "contested"], contested_dimensions=["contested"],
    )
    by_id = {a["annotator_id"]: a for a in profile["annotators"]}
    flags = by_id["A3"]["flags"]
    assert any(f.startswith("systematic_bias:lenient") for f in flags)
    assert "A3" in profile["flagged_annotators"]
    # The flag quotes the uncontested figure, which is the leniency.
    assert f"{by_id['A3']['bias_vs_pool_uncontested']:+.2f}" in flags[0]


def test_positions_do_not_count_toward_the_flagged_fraction():
    """The gate escalates on the flagged fraction, so this must stay clean."""
    rows = _two_dimension_pool()
    profile = profile_annotators(
        rows, ["settled", "contested"], contested_dimensions=["contested"],
    )
    assert profile["flagged_fraction"] == 0.125           # A3 only, 1 of 8
    assert profile["divergent_on_contested_fraction"] == 0.25
    assert "not a quality defect" in profile["position_note"]


def test_without_contested_dimensions_bias_falls_back_to_the_overall_offset():
    rows = _two_dimension_pool()
    profile = profile_annotators(rows, ["settled", "contested"])
    by_id = {a["annotator_id"]: a for a in profile["annotators"]}
    # Same data, no contested declaration: A1 and A2 are flagged, as before.
    assert any(f.startswith("systematic_bias") for f in by_id["A1"]["flags"])
    assert any(f.startswith("systematic_bias") for f in by_id["A2"]["flags"])
    assert profile["contested_dimensions"] == []


# --------------------------------------------------------------------------
# post-adjudication label quality
# --------------------------------------------------------------------------


def test_post_adjudication_agreement_is_labelled_as_label_quality():
    """The docstring promises this figure. It must not be confusable with alpha."""
    track = get("agentic")
    spec = track.spec
    rows = [a.to_dict() for a in annotate(spec, track.items(), track.responses())]
    queue = triage(rows, spec)
    adjudications = adjudicate(queue, rows, spec, capacity=20)

    report = post_adjudication_agreement(adjudications, rows, spec)

    assert report["is_reliability_figure"] is False
    assert "NOT RELIABILITY" in report["note"]
    assert report["n_adjudicated_responses"] == 20
    assert 0.0 <= report["exact_match_with_final_label"] <= 1.0
    assert report["within_one_of_final_label"] >= report["exact_match_with_final_label"]
    assert abs(report["overrule_rate"] - (1 - report["exact_match_with_final_label"])) < 1e-9
    assert set(report["exact_match_by_dimension"]) <= set(spec.rubric.dimension_keys)


def test_post_adjudication_agreement_on_an_empty_queue():
    track = get("agentic")
    spec = track.spec
    rows = [a.to_dict() for a in annotate(spec, track.items(), track.responses())]
    report = post_adjudication_agreement([], rows, spec)
    assert report["n_adjudicated_responses"] == 0
    assert report["is_reliability_figure"] is False
