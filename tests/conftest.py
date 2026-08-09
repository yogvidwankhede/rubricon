"""Shared fixtures and tiny synthetic builders.

Unit tests build their own miniature rubrics, items, responses and annotation
rows here so that no unit test depends on the shape of the real four-track
corpus. Only tests/test_pipeline.py touches a real track.
"""

from __future__ import annotations

import pytest

from rubricon.core.schema import (
    Anchor,
    Annotation,
    AnnotationSource,
    Dimension,
    ModelResponse,
    Rubric,
    ScaleType,
    TaskItem,
    TrackSpec,
)

# --------------------------------------------------------------------------
# Krippendorff (2011) reference reliability data
# --------------------------------------------------------------------------
#
# 12 units, 4 observers, None = missing. Published alpha values:
#   nominal 0.743, ordinal 0.815, interval 0.849, ratio 0.797
KRIPPENDORFF_2011_COLUMNS = {
    "A": [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None],
    "B": [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3],
    "C": [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None],
    "D": [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None],
}

KRIPPENDORFF_2011_EXPECTED = {
    "nominal": 0.743,
    "ordinal": 0.815,
    "interval": 0.849,
    "ratio": 0.797,
}


def columns_to_reliability_data(columns):
    """{observer: [value per unit]} -> {unit_id: {observer: value}}, dropping None."""
    n_units = len(next(iter(columns.values())))
    data = {}
    for u in range(n_units):
        row = {obs: col[u] for obs, col in columns.items() if col[u] is not None}
        data[f"u{u:02d}"] = row
    return data


@pytest.fixture
def krippendorff_reference():
    return columns_to_reliability_data(KRIPPENDORFF_2011_COLUMNS)


# --------------------------------------------------------------------------
# synthetic rubric / spec builders
# --------------------------------------------------------------------------


def make_dimension(
    key="quality",
    levels=(0, 1, 2, 3),
    weight=1.0,
    critical=False,
    critical_threshold=None,
    scale=ScaleType.ORDINAL,
    anchored=False,
    anchor_suffix="",
):
    anchors = ()
    if anchored:
        anchors = tuple(
            Anchor(value=lv, label=f"L{lv}", description=f"level {lv}{anchor_suffix}")
            for lv in levels
        )
    return Dimension(
        key=key,
        name=key.replace("_", " ").title(),
        question=f"How does the response score on {key}?",
        scale=scale,
        levels=tuple(levels),
        anchors=anchors,
        weight=weight,
        critical=critical,
        critical_threshold=critical_threshold,
    )


def make_rubric(dimensions=None, key="mini", revision=1):
    dims = tuple(dimensions or (make_dimension(),))
    return Rubric(
        key=key,
        name="Mini rubric",
        description="Synthetic rubric used by the unit tests.",
        dimensions=dims,
        revision=revision,
    )


def make_spec(
    rubric=None,
    key="mini",
    depth="pilot",
    strata_design=None,
    failure_codes=None,
    replication=3,
    target_n=12,
):
    return TrackSpec(
        key=key,
        name="Mini track",
        research_question="Does the harness behave?",
        depth=depth,
        rubric=rubric or make_rubric(),
        unit_of_analysis="response",
        strata_design=strata_design or {"difficulty": ["easy", "hard"]},
        target_n=target_n,
        replication=replication,
        gold_rate=0.1,
        failure_codes=failure_codes or {},
    )


def make_item(item_id, strata=None, gold_scores=None):
    return TaskItem(
        item_id=item_id,
        track="mini",
        prompt=f"prompt for {item_id}",
        strata=dict(strata or {}),
        gold_scores=dict(gold_scores) if gold_scores else None,
        is_gold=bool(gold_scores),
    )


def make_response(response_id, item_id, system_id="sut-a", text="answer", planted=None):
    return ModelResponse(
        response_id=response_id,
        item_id=item_id,
        system_id=system_id,
        text=text,
        planted_failure=planted,
    )


def annotation_row(response_id, annotator_id, scores, item_id=None, codes=(), batch=0):
    """A plain dict annotation row, the shape every downstream module consumes."""
    return Annotation(
        annotation_id=f"{response_id}::{annotator_id}",
        response_id=response_id,
        item_id=item_id or response_id.split("::")[0],
        annotator_id=annotator_id,
        rubric_version="mini@r1+deadbeef",
        scores=dict(scores),
        source=AnnotationSource.SYNTHETIC,
        failure_codes=tuple(codes),
        batch=batch,
    ).to_dict()


@pytest.fixture
def mini_rubric():
    return make_rubric()


@pytest.fixture
def mini_spec():
    return make_spec()
