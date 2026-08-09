"""Guards the core data model and its provenance guarantees.

Class of regression protected here: silent pooling of labels collected under
two different instruments. ``Rubric.version_hash`` is the only thing standing
between "we changed one anchor" and "we averaged incomparable annotations", so
it must change whenever any dimension or anchor text changes and must be stable
across identical reconstructions.

Also covered: the constructor invariants that make a rubric usable at all
(complete anchoring, critical dimensions carrying a threshold, non-empty
levels), the critical-gate and weighting semantics of ``composite()``, and
exact JSON round-tripping of the two corpus record types.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from rubricon.core.schema import (
    Anchor,
    Dimension,
    ModelResponse,
    ScaleType,
    TaskItem,
)

from .conftest import make_dimension, make_rubric


# --------------------------------------------------------------------------
# version hashing
# --------------------------------------------------------------------------


def _anchored_rubric(description_suffix=""):
    dim = Dimension(
        key="claim_support",
        name="Claim support",
        question="Is every claim supported?",
        scale=ScaleType.ORDINAL,
        levels=(0, 1, 2, 3),
        anchors=tuple(
            Anchor(value=lv, label=f"L{lv}", description=f"anchor {lv}{description_suffix}")
            for lv in (0, 1, 2, 3)
        ),
    )
    return make_rubric(dimensions=(dim,), key="grounding")


def test_version_hash_is_stable_across_identical_reconstructions():
    a = _anchored_rubric()
    b = _anchored_rubric()
    assert a is not b
    assert a.version_hash == b.version_hash
    assert a.version == b.version
    # And stable across repeated access on the same object.
    assert a.version_hash == a.version_hash


def test_version_hash_changes_when_anchor_text_changes():
    baseline = _anchored_rubric()
    edited = _anchored_rubric(description_suffix=" (clarified)")
    assert baseline.version_hash != edited.version_hash, (
        "editing an anchor must invalidate the rubric version, otherwise labels "
        "collected under two definitions pool silently"
    )


def test_version_hash_changes_when_a_dimension_changes():
    base = make_rubric(dimensions=(make_dimension(key="d1"),))

    renamed = make_rubric(dimensions=(make_dimension(key="d1_renamed"),))
    assert base.version_hash != renamed.version_hash

    reweighted = make_rubric(dimensions=(make_dimension(key="d1", weight=2.0),))
    assert base.version_hash != reweighted.version_hash

    rescaled = make_rubric(dimensions=(make_dimension(key="d1", levels=(0, 1, 2, 3, 4)),))
    assert base.version_hash != rescaled.version_hash

    added = make_rubric(
        dimensions=(make_dimension(key="d1"), make_dimension(key="d2"))
    )
    assert base.version_hash != added.version_hash

    requestioned = make_rubric(
        dimensions=(replace(make_dimension(key="d1"), question="A different question?"),)
    )
    assert base.version_hash != requestioned.version_hash


def test_version_hash_ignores_rubric_metadata_but_version_string_does_not():
    """The hash is over the instrument; the revision number is provenance."""
    r1 = make_rubric(dimensions=(make_dimension(),), revision=1)
    r2 = make_rubric(dimensions=(make_dimension(),), revision=2)
    assert r1.version_hash == r2.version_hash
    assert r1.version != r2.version
    assert r2.version.startswith("mini@r2+")


# --------------------------------------------------------------------------
# dimension invariants
# --------------------------------------------------------------------------


def test_partial_anchors_raise():
    with pytest.raises(ValueError) as exc:
        Dimension(
            key="partial",
            name="Partial",
            question="?",
            scale=ScaleType.ORDINAL,
            levels=(0, 1, 2, 3),
            anchors=(Anchor(value=0, label="floor", description="worst"),),
        )
    assert "partial anchors" in str(exc.value)
    assert "missing" in str(exc.value)


def test_complete_anchors_are_accepted():
    dim = make_dimension(anchored=True)
    assert len(dim.anchors) == len(dim.levels)


def test_critical_dimension_without_threshold_raises():
    with pytest.raises(ValueError) as exc:
        Dimension(
            key="argument_fidelity",
            name="Argument fidelity",
            question="?",
            scale=ScaleType.ORDINAL,
            levels=(0, 1, 2, 3),
            critical=True,
        )
    assert "critical" in str(exc.value)
    assert "critical_threshold" in str(exc.value)


def test_dimension_with_no_levels_raises():
    with pytest.raises(ValueError) as exc:
        Dimension(
            key="empty",
            name="Empty",
            question="?",
            scale=ScaleType.NOMINAL,
            levels=(),
        )
    assert "no levels" in str(exc.value)


def test_is_failing_only_fires_for_critical_dimensions():
    plain = make_dimension(key="plain", levels=(0, 1, 2, 3))
    assert plain.is_failing(0) is False

    critical = make_dimension(
        key="crit", levels=(0, 1, 2, 3), critical=True, critical_threshold=1
    )
    assert critical.is_failing(0) is True
    assert critical.is_failing(1) is True    # "at or below"
    assert critical.is_failing(2) is False


# --------------------------------------------------------------------------
# composite scoring
# --------------------------------------------------------------------------


def test_composite_is_one_at_all_max():
    rubric = make_rubric(
        dimensions=(
            make_dimension(key="a", levels=(0, 1, 2, 3)),
            make_dimension(key="b", levels=(0, 1)),
        )
    )
    assert rubric.composite({"a": 3, "b": 1}) == 1.0
    assert rubric.composite({"a": 0, "b": 0}) == 0.0


def test_composite_zeroes_on_a_failing_critical_dimension():
    rubric = make_rubric(
        dimensions=(
            make_dimension(key="quality", levels=(0, 1, 2, 3), weight=5.0),
            make_dimension(
                key="fidelity",
                levels=(0, 1, 2, 3),
                critical=True,
                critical_threshold=1,
            ),
        )
    )
    # Excellent everywhere else, but the critical dimension is at the threshold.
    assert rubric.composite({"quality": 3, "fidelity": 1}) == 0.0
    assert rubric.composite({"quality": 3, "fidelity": 0}) == 0.0
    # One point above the threshold and the gate opens.
    assert rubric.composite({"quality": 3, "fidelity": 2}) > 0.0


def test_composite_weighting_is_computed_by_hand():
    # dim_a: levels 0..3, weight 3 ; dim_b: levels 0..1, weight 1
    #
    #   scores a=2, b=0
    #   norm_a = (2 - 0) / (3 - 0) = 2/3
    #   norm_b = (0 - 0) / (1 - 0) = 0
    #   composite = (2/3 * 3 + 0 * 1) / (3 + 1) = 2 / 4 = 0.5
    rubric = make_rubric(
        dimensions=(
            make_dimension(key="dim_a", levels=(0, 1, 2, 3), weight=3.0),
            make_dimension(key="dim_b", levels=(0, 1), weight=1.0),
        )
    )
    assert abs(rubric.composite({"dim_a": 2, "dim_b": 0}) - 0.5) < 1e-12

    #   scores a=1, b=1
    #   norm_a = 1/3 ; norm_b = 1
    #   composite = (1/3 * 3 + 1 * 1) / 4 = 2 / 4 = 0.5
    assert abs(rubric.composite({"dim_a": 1, "dim_b": 1}) - 0.5) < 1e-12

    #   scores a=3, b=0 -> (1 * 3 + 0) / 4 = 0.75
    assert abs(rubric.composite({"dim_a": 3, "dim_b": 0}) - 0.75) < 1e-12


def test_composite_ignores_dimensions_absent_from_the_score_map():
    rubric = make_rubric(
        dimensions=(
            make_dimension(key="a", levels=(0, 1, 2, 3), weight=3.0),
            make_dimension(key="b", levels=(0, 1), weight=1.0),
        )
    )
    # Only 'a' scored: the composite is the normalised value of 'a' alone.
    assert abs(rubric.composite({"a": 2}) - 2.0 / 3.0) < 1e-12
    assert rubric.composite({}) == 0.0


# --------------------------------------------------------------------------
# rubric lookups
# --------------------------------------------------------------------------


def test_dimension_lookup_and_keys():
    rubric = make_rubric(
        dimensions=(make_dimension(key="a"), make_dimension(key="b"))
    )
    assert rubric.dimension_keys == ("a", "b")
    assert rubric.dimension("b").key == "b"
    with pytest.raises(KeyError):
        rubric.dimension("nope")


def test_rubric_to_dict_carries_the_version():
    rubric = _anchored_rubric()
    d = rubric.to_dict()
    assert d["version_hash"] == rubric.version_hash
    assert d["version"] == rubric.version
    assert len(d["dimensions"]) == 1
    assert d["dimensions"][0]["scale"] == "ordinal"


# --------------------------------------------------------------------------
# round-tripping
# --------------------------------------------------------------------------


def test_task_item_round_trips_exactly():
    item = TaskItem(
        item_id="grn-0007",
        track="grounding",
        prompt="Summarise the passage.",
        context="Some retrieved context.",
        reference="Gold summary.",
        strata={"difficulty": "hard", "domain": "legal"},
        metadata={"source": "authored", "n_tokens": 412},
        gold_scores={"claim_support": 3, "citation_validity": 2},
        is_gold=True,
    )
    restored = TaskItem.from_dict(item.to_dict())
    assert restored == item
    assert restored.to_dict() == item.to_dict()


def test_task_item_round_trips_with_defaults():
    item = TaskItem(item_id="x1", track="mini", prompt="p")
    restored = TaskItem.from_dict(item.to_dict())
    assert restored == item
    assert restored.gold_scores is None
    assert restored.is_gold is False


def test_model_response_round_trips_exactly():
    resp = ModelResponse(
        response_id="grn-0007::sut-candidate-v2",
        item_id="grn-0007",
        system_id="sut-candidate-v2",
        text="A grounded answer [1].",
        trace=({"step": 1, "tool": "search"}, {"step": 2, "tool": "read"}),
        latency_ms=1234.5,
        tokens_out=88,
        planted_failure="GF-03",
        metadata={"temperature": 0.0},
    )
    restored = ModelResponse.from_dict(resp.to_dict())
    assert restored == resp
    assert restored.to_dict() == resp.to_dict()


def test_model_response_round_trips_with_defaults():
    resp = ModelResponse(
        response_id="r1", item_id="i1", system_id="s1", text="hello"
    )
    restored = ModelResponse.from_dict(resp.to_dict())
    assert restored == resp
    assert restored.planted_failure is None
    assert restored.trace == ()
