"""Rubricon: evaluation signal infrastructure.

A harness for building evaluations whose numbers can be defended: versioned
rubrics, replicated annotation, agreement statistics validated against published
reference values, a programmatic quality gate that blocks unsupportable claims,
and an invest/iterate/stop decision engine.
"""

__version__ = "0.4.0"

from .core.schema import (  # noqa: F401
    Annotation, Dimension, ModelResponse, Recommendation, Rubric, ScaleType,
    TaskItem, TrackSpec, Verdict,
)

__all__ = [
    "Annotation", "Dimension", "ModelResponse", "Recommendation", "Rubric",
    "ScaleType", "TaskItem", "TrackSpec", "Verdict", "__version__",
]
