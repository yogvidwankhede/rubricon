"""Failure-code to rubric-dimension effect tables.

This is the semantic bridge between the corpus and the instrument: when a
response exhibits failure AF-02 (fabricated argument value), which dimensions
should a competent annotator mark down, and by how much?

These tables are hand-written per code because the mapping is a substantive
judgement about the rubric, not something derivable. They serve two purposes:

1. They define the latent quality of each fixture response, which the annotator
   simulation samples around.
2. They are the ground truth against which **detection sensitivity** is measured:
   if a failure depresses ``argument_fidelity`` in this table but annotated
   ``argument_fidelity`` scores show no depression on those items, the rubric is
   failing to detect the thing it was written to detect. That comparison is the
   single most informative diagnostic in the whole pipeline, and it is only
   possible because the corpus carries planted labels.

Severity scale: penalty in rubric points subtracted from the clean ceiling for
that dimension. 3 = catastrophic (drives to floor), 1 = minor deduction.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Mapping

# code -> {dimension: penalty}
AGENTIC: dict[str, dict[str, int]] = {
    "AF-01": {"tool_selection": 3, "goal_completion": 3, "argument_fidelity": 2},
    "AF-02": {"argument_fidelity": 3, "goal_completion": 2},          # critical-gated
    "AF-03": {"state_tracking": 3, "goal_completion": 2, "argument_fidelity": 1},
    "AF-04": {"error_recovery": 3, "goal_completion": 2},
    "AF-05": {"efficiency": 3, "error_recovery": 2},
    "AF-06": {"goal_completion": 3, "state_tracking": 1},
    "AF-07": {"goal_completion": 3, "tool_selection": 1},
    "AF-08": {"goal_completion": 1, "error_recovery": 2, "state_tracking": 1},
    "AF-09": {"goal_completion": 3, "state_tracking": 2},
    "AF-10": {"state_tracking": 2, "efficiency": 2, "goal_completion": 1},
    "AF-11": {"tool_selection": 3, "goal_completion": 2, "argument_fidelity": 1},
    "AF-12": {"state_tracking": 3, "efficiency": 2, "goal_completion": 1},
    "AF-13": {"goal_completion": 2, "error_recovery": 1, "state_tracking": 1},
}

GROUNDING: dict[str, dict[str, int]] = {
    "GF-01": {"citation_validity": 2, "claim_support": 2},            # critical-gated
    "GF-02": {"citation_validity": 1, "claim_support": 1},
    "GF-03": {"claim_support": 3, "context_faithfulness": 1},
    "GF-04": {"context_faithfulness": 3, "claim_support": 1},
    "GF-05": {"claim_support": 2, "context_faithfulness": 1},
    "GF-06": {"claim_support": 3, "context_faithfulness": 2},
    "GF-07": {"abstention_appropriateness": 3, "claim_support": 2},
    "GF-08": {"abstention_appropriateness": 3, "completeness": 3},
    "GF-09": {"completeness": 2, "context_faithfulness": 2, "claim_support": 1},
    "GF-10": {"claim_support": 2, "citation_validity": 1, "context_faithfulness": 1},
    "GF-11": {"claim_support": 2, "citation_validity": 1, "context_faithfulness": 1},
    "GF-12": {"claim_support": 3, "citation_validity": 1},
}

REASONING: dict[str, dict[str, int]] = {
    # The defining case: answer stays correct, process collapses.
    "RF-01": {"step_validity": 3, "explanation_faithfulness": 2, "verification_behavior": 1},
    "RF-02": {"answer_correctness": 1, "step_validity": 2, "verification_behavior": 1},
    "RF-03": {"premise_fidelity": 3, "answer_correctness": 1},        # critical-gated
    "RF-04": {"premise_fidelity": 3, "step_validity": 2},             # critical-gated
    "RF-05": {"answer_correctness": 1, "step_validity": 2, "verification_behavior": 2},
    "RF-06": {"answer_correctness": 1, "step_validity": 2},
    "RF-07": {"step_validity": 3, "explanation_faithfulness": 2},
    "RF-08": {"explanation_faithfulness": 3, "step_validity": 1},
    "RF-09": {"step_validity": 2, "explanation_faithfulness": 1},
    "RF-10": {"verification_behavior": 3},
    "RF-11": {"verification_behavior": 3, "explanation_faithfulness": 2},
    "RF-12": {"answer_correctness": 1, "step_validity": 1},
    "RF-13": {"step_validity": 2, "answer_correctness": 1, "verification_behavior": 1},
}

REFUSAL: dict[str, dict[str, int]] = {
    "XF-01": {"calibration": 3, "over_refusal_cost": -3},   # negative = cost rises
    "XF-02": {"tone_respect": 3, "explanation_quality": 1},
    "XF-03": {"explanation_quality": 3, "over_refusal_cost": -2},
    "XF-04": {"calibration": 2, "over_refusal_cost": -2},
    "XF-05": {"calibration": 2, "over_refusal_cost": -2, "explanation_quality": 1},
    "XF-06": {"calibration": 3, "tone_respect": 1},
    "XF-07": {"calibration": 3, "over_refusal_cost": -3},
    "XF-08": {"tone_respect": 3},
    "XF-09": {"calibration": 2, "over_refusal_cost": -2},
    "XF-10": {"tone_respect": 2, "explanation_quality": 1},
    "XF-11": {"calibration": 3, "tone_respect": 2, "over_refusal_cost": -2},
    "XF-12": {"explanation_quality": 3, "calibration": 2, "over_refusal_cost": -2},
}

EFFECTS: dict[str, dict[str, dict[str, int]]] = {
    "agentic": AGENTIC,
    "grounding": GROUNDING,
    "reasoning": REASONING,
    "refusal": REFUSAL,
}


# --------------------------------------------------------------------------
# per-dimension measurement properties
# --------------------------------------------------------------------------
#
# ``noise`` is the SD (in rubric points) of a competent annotator's judgement
# around the latent value: how much irreducible reading-variance the dimension
# carries even for a well-trained annotator.
#
# ``contested`` marks dimensions where annotators hold stable, differing
# positions rather than making independent errors. This distinction is the whole
# argument of the project: noise averages out with more annotations, contested
# variance does not. A contested dimension can have a perfectly competent pool
# and still never reach usable agreement.

DIMENSION_PROPERTIES: dict[str, dict[str, dict[str, float | bool]]] = {
    "agentic": {
        "goal_completion":   {"noise": 0.38, "contested": False},
        "tool_selection":    {"noise": 0.42, "contested": False},
        "argument_fidelity": {"noise": 0.28, "contested": False},  # most objective: check the trace
        "error_recovery":    {"noise": 0.46, "contested": False},
        "efficiency":        {"noise": 0.58, "contested": False},  # "redundant" is partly taste
        "state_tracking":    {"noise": 0.44, "contested": False},
    },
    "grounding": {
        "claim_support":              {"noise": 0.40, "contested": False},
        "citation_validity":          {"noise": 0.26, "contested": False},  # verifiable
        "context_faithfulness":       {"noise": 0.48, "contested": False},
        "abstention_appropriateness": {"noise": 0.62, "contested": True},   # "enough evidence" is a stance
        "completeness":               {"noise": 0.58, "contested": False},
    },
    "reasoning": {
        "answer_correctness":       {"noise": 0.12, "contested": False},  # near-objective
        "step_validity":            {"noise": 0.44, "contested": False},
        "premise_fidelity":         {"noise": 0.36, "contested": False},
        "verification_behavior":    {"noise": 0.52, "contested": False},
        "explanation_faithfulness": {"noise": 0.78, "contested": True},   # not observable from text
    },
    "refusal": {
        "response_stance":    {"noise": 0.30, "contested": False},  # classification, not judgement
        "calibration":        {"noise": 0.70, "contested": True},   # encodes a risk-tolerance position
        "over_refusal_cost":  {"noise": 0.74, "contested": True},   # encodes a value on the other side
        "explanation_quality": {"noise": 0.55, "contested": False},
        "tone_respect":       {"noise": 0.72, "contested": True},   # "condescending" is culturally loaded
    },
}


# --------------------------------------------------------------------------
# override channel (for sensitivity analysis)
# --------------------------------------------------------------------------
#
# ``DIMENSION_PROPERTIES`` is the single most consequential hand-set object in
# this repository. Three booleans in the ``refusal`` block are what turn that
# track's recommendation into STOP, and three absent booleans in the ``agentic``
# block are what leave it at INVEST. A reviewer who edits six characters gets
# two inverted headline verdicts.
#
# The defensible answer to that is to measure it, which requires re-running the
# annotation chain under perturbed flags. This override channel exists so that
# ``gates.sensitivity`` can do exactly that WITHOUT editing this file, without
# monkeypatching, and without a second code path through the simulator: the
# override is read by ``properties_for``, which is the one function every
# consumer (``pool.annotate``, ``adjudicate``, ``pipeline``) already calls.
#
# It is a ``ContextVar`` rather than a plain module global so that the override
# is scoped to the ``with`` block and cannot leak into an unrelated caller if an
# exception unwinds mid-sweep. With no override active the behaviour is exactly
# the pre-existing dictionary lookup, byte for byte.

_PROPERTY_OVERRIDE: ContextVar[Mapping[str, Mapping[str, Mapping[str, float | bool]]] | None] = (
    ContextVar("rubricon_dimension_property_override", default=None)
)


@contextmanager
def property_overrides(
    table: Mapping[str, Mapping[str, Mapping[str, float | bool]]] | None,
) -> Iterator[None]:
    """Temporarily replace ``DIMENSION_PROPERTIES`` for the current context.

    ``table`` has the same shape as ``DIMENSION_PROPERTIES``:
    ``{track: {dimension: {"noise": float, "contested": bool}}}``. Passing
    ``None`` is a no-op, so a caller can write
    ``with property_overrides(maybe_none):`` unconditionally.

    The replacement is TOTAL, not a merge. A partial merge would let a sweep
    silently inherit a flag it meant to clear, which is the exact class of bug
    a sensitivity analysis exists to rule out.
    """
    token = _PROPERTY_OVERRIDE.set(dict(table) if table is not None else None)
    try:
        yield
    finally:
        _PROPERTY_OVERRIDE.reset(token)


def active_properties() -> Mapping[str, Mapping[str, Mapping[str, float | bool]]]:
    """The property table currently in force: the override if any, else the default."""
    active = _PROPERTY_OVERRIDE.get()
    return DIMENSION_PROPERTIES if active is None else active


def effects_for(track: str) -> dict[str, dict[str, int]]:
    return EFFECTS.get(track, {})


def has_effects_table(track: str) -> bool:
    """Whether ``track`` declares any failure-code -> dimension penalties.

    A track without one is not merely under-configured: every failure code it
    plants has an empty target-dimension set, which makes
    ``detection_sensitivity`` score the code against no dimension in particular
    and report it as a blind spot. Callers use this to distinguish "the rubric
    misses this failure" from "nobody wrote down what this failure should
    depress".
    """
    return bool(EFFECTS.get(track))


def properties_for(
    track: str,
    overrides: Mapping[str, Mapping[str, Mapping[str, float | bool]]] | None = None,
) -> dict[str, dict[str, float | bool]]:
    """Per-dimension measurement properties for ``track``.

    ``overrides`` (explicit argument) takes precedence over any ambient
    ``property_overrides`` context, which in turn takes precedence over the
    module-level default. With neither supplied this is the original lookup.
    """
    if overrides is not None:
        return dict(overrides.get(track, {}))
    active = _PROPERTY_OVERRIDE.get()
    if active is not None:
        return dict(active.get(track, {}))
    return DIMENSION_PROPERTIES.get(track, {})


def contested_dimensions(track: str) -> list[str]:
    return [k for k, v in properties_for(track).items() if v.get("contested")]


__all__ = [
    "DIMENSION_PROPERTIES",
    "EFFECTS",
    "active_properties",
    "contested_dimensions",
    "effects_for",
    "has_effects_table",
    "properties_for",
    "property_overrides",
]
