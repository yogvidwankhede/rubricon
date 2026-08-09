"""Core data model for Rubricon.

Every artifact in the pipeline is a frozen, hashable, JSON-round-trippable
dataclass. Two design rules drive this module:

1. **Provenance is not optional.** Any object that ends up in a reported number
   carries enough identifiers to trace it back to the item, the rubric version,
   the model build, and the annotator who produced it. If you cannot answer
   "where did this number come from" you cannot defend it.

2. **Rubric versions are content-addressed.** A rubric's ``version_hash`` is
   derived from its dimensions and anchors. Change a single anchor and the hash
   changes, which invalidates downstream agreement statistics. This prevents the
   most common silent failure in annotation programs: pooling labels collected
   under two different definitions of the same task.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

# --------------------------------------------------------------------------
# enums
# --------------------------------------------------------------------------


class ScaleType(str, Enum):
    """Measurement scale of a rubric dimension.

    The scale type is not cosmetic: it selects the distance metric used by
    Krippendorff's alpha. Scoring an ordinal dimension with a nominal metric
    throws away the information that 1-vs-2 is a smaller disagreement than
    1-vs-4, and systematically *understates* agreement.
    """

    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    INTERVAL = "interval"
    BINARY = "binary"


class Verdict(str, Enum):
    """Outcome of a signal gate check."""

    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class Recommendation(str, Enum):
    """Portfolio decision for an evaluation category."""

    INVEST = "invest"
    ITERATE = "iterate"
    HOLD = "hold"
    STOP = "stop"


class AnnotationSource(str, Enum):
    HUMAN = "human"
    LLM_JUDGE = "llm_judge"
    GOLD = "gold"
    ADJUDICATED = "adjudicated"
    SYNTHETIC = "synthetic"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _canonical(obj: Any) -> str:
    """Deterministic JSON for hashing. Sorted keys, no incidental whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(obj: Any, length: int = 12) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()[:length]


# --------------------------------------------------------------------------
# rubric
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    """A concrete worked example pinning one point on a rubric scale.

    Anchors are the difference between a rubric and a wish. An unanchored
    "rate helpfulness 1-5" produces annotator-specific scales that look like
    disagreement but are really unit mismatch.
    """

    value: int | str
    label: str
    description: str
    example: str = ""
    counter_example: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Dimension:
    """One independently-scored axis of a rubric."""

    key: str
    name: str
    question: str
    scale: ScaleType
    levels: tuple[int | str, ...]
    anchors: tuple[Anchor, ...] = ()
    weight: float = 1.0
    # If True, a failing score on this dimension zeroes the item regardless of
    # other dimensions. Models the real asymmetry where one fabricated citation
    # invalidates an otherwise excellent answer.
    critical: bool = False
    critical_threshold: int | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.levels:
            raise ValueError(f"dimension {self.key!r} has no levels")
        if self.critical and self.critical_threshold is None:
            raise ValueError(
                f"dimension {self.key!r} is critical but defines no critical_threshold"
            )
        anchored = {a.value for a in self.anchors}
        missing = [lv for lv in self.levels if lv not in anchored]
        if self.anchors and missing:
            raise ValueError(
                f"dimension {self.key!r} has partial anchors; missing {missing}. "
                "Partial anchoring is worse than none: annotators over-apply the "
                "anchored levels."
            )

    def is_failing(self, value: int | str) -> bool:
        if not self.critical or self.critical_threshold is None:
            return False
        try:
            return float(value) <= float(self.critical_threshold)
        except (TypeError, ValueError):
            return False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scale"] = self.scale.value
        d["levels"] = list(self.levels)
        d["anchors"] = [a.to_dict() for a in self.anchors]
        return d


@dataclass(frozen=True)
class Rubric:
    """A versioned, content-addressed scoring instrument."""

    key: str
    name: str
    description: str
    dimensions: tuple[Dimension, ...]
    revision: int = 1
    changelog: tuple[str, ...] = ()

    @property
    def version_hash(self) -> str:
        return content_hash([d.to_dict() for d in self.dimensions])

    @property
    def version(self) -> str:
        return f"{self.key}@r{self.revision}+{self.version_hash}"

    def dimension(self, key: str) -> Dimension:
        for d in self.dimensions:
            if d.key == key:
                return d
        raise KeyError(f"{self.key}: no dimension {key!r}")

    @property
    def dimension_keys(self) -> tuple[str, ...]:
        return tuple(d.key for d in self.dimensions)

    def composite(self, scores: Mapping[str, int | str]) -> float:
        """Weighted composite in [0, 1], with critical-dimension gating.

        Normalisation is per-dimension min-max over that dimension's declared
        levels, so dimensions with different ranges combine sensibly.
        """
        total_w = 0.0
        acc = 0.0
        for dim in self.dimensions:
            if dim.key not in scores:
                continue
            raw = scores[dim.key]
            if dim.is_failing(raw):
                return 0.0
            numeric_levels = [float(x) for x in dim.levels]
            lo, hi = min(numeric_levels), max(numeric_levels)
            norm = 0.0 if hi == lo else (float(raw) - lo) / (hi - lo)
            acc += norm * dim.weight
            total_w += dim.weight
        return acc / total_w if total_w else 0.0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "revision": self.revision,
            "version": self.version,
            "version_hash": self.version_hash,
            "changelog": list(self.changelog),
            "dimensions": [d.to_dict() for d in self.dimensions],
        }


# --------------------------------------------------------------------------
# items and responses
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskItem:
    """One unit of evaluation input.

    ``strata`` is the field that makes coverage analysis possible. Every item
    declares which cells of the design it occupies (difficulty, domain, planted
    failure mode, ...) so we can detect which cells are under-sampled rather
    than discovering it after the fact.
    """

    item_id: str
    track: str
    prompt: str
    context: str = ""
    reference: str = ""
    strata: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # Ground truth for gold/trap items, used for annotator calibration.
    gold_scores: Mapping[str, int] | None = None
    is_gold: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["strata"] = dict(self.strata)
        d["metadata"] = dict(self.metadata)
        d["gold_scores"] = dict(self.gold_scores) if self.gold_scores else None
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "TaskItem":
        return TaskItem(
            item_id=d["item_id"],
            track=d["track"],
            prompt=d["prompt"],
            context=d.get("context", ""),
            reference=d.get("reference", ""),
            strata=dict(d.get("strata") or {}),
            metadata=dict(d.get("metadata") or {}),
            gold_scores=dict(d["gold_scores"]) if d.get("gold_scores") else None,
            is_gold=bool(d.get("is_gold", False)),
        )


@dataclass(frozen=True)
class ModelResponse:
    """A system-under-test output, with everything needed to reproduce it."""

    response_id: str
    item_id: str
    system_id: str
    text: str
    trace: tuple[Mapping[str, Any], ...] = ()
    latency_ms: float = 0.0
    tokens_out: int = 0
    # Planted failure mode, present only in fixture/seeded data. Never consulted
    # by annotators; used solely to measure detection sensitivity of the eval.
    planted_failure: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["trace"] = [dict(t) for t in self.trace]
        d["metadata"] = dict(self.metadata)
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "ModelResponse":
        return ModelResponse(
            response_id=d["response_id"],
            item_id=d["item_id"],
            system_id=d["system_id"],
            text=d["text"],
            trace=tuple(dict(t) for t in d.get("trace") or ()),
            latency_ms=float(d.get("latency_ms", 0.0)),
            tokens_out=int(d.get("tokens_out", 0)),
            planted_failure=d.get("planted_failure"),
            metadata=dict(d.get("metadata") or {}),
        )


# --------------------------------------------------------------------------
# annotations
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Annotation:
    """One annotator's judgement of one response under one rubric version."""

    annotation_id: str
    response_id: str
    item_id: str
    annotator_id: str
    rubric_version: str
    scores: Mapping[str, int]
    source: AnnotationSource = AnnotationSource.HUMAN
    failure_codes: tuple[str, ...] = ()
    rationale: str = ""
    confidence: float = 1.0
    duration_s: float = 0.0
    batch: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source"] = self.source.value
        d["scores"] = dict(self.scores)
        d["failure_codes"] = list(self.failure_codes)
        d["metadata"] = dict(self.metadata)
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "Annotation":
        return Annotation(
            annotation_id=d["annotation_id"],
            response_id=d["response_id"],
            item_id=d["item_id"],
            annotator_id=d["annotator_id"],
            rubric_version=d["rubric_version"],
            scores={k: int(v) for k, v in d["scores"].items()},
            source=AnnotationSource(d.get("source", "human")),
            failure_codes=tuple(d.get("failure_codes") or ()),
            rationale=d.get("rationale", ""),
            confidence=float(d.get("confidence", 1.0)),
            duration_s=float(d.get("duration_s", 0.0)),
            batch=int(d.get("batch", 0)),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass(frozen=True)
class Adjudication:
    """Resolution of a flagged disagreement.

    ``triage_reason`` records *why* the item entered the queue. Adjudicating
    only high-variance items and then computing agreement on the full pool
    inflates the statistic; keeping the reason lets us report pre- and
    post-adjudication agreement separately, which is the honest presentation.
    """

    response_id: str
    item_id: str
    final_scores: Mapping[str, int]
    adjudicator_id: str
    triage_reason: str
    original_annotations: tuple[str, ...] = ()
    notes: str = ""
    rubric_gap_flagged: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["final_scores"] = dict(self.final_scores)
        d["original_annotations"] = list(self.original_annotations)
        return d


# --------------------------------------------------------------------------
# track specification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackSpec:
    """Everything that defines one evaluation track.

    ``depth`` is deliberately explicit. A portfolio of evaluations always has
    tiers of maturity, and pretending otherwise is how a pilot's numbers end up
    quoted as if they were production measurements.
    """

    key: str
    name: str
    research_question: str
    depth: str  # "production" | "pilot" | "exploratory"
    rubric: Rubric
    unit_of_analysis: str
    strata_design: Mapping[str, Sequence[str]]
    target_n: int
    replication: int  # annotations per response
    gold_rate: float  # fraction of items that are calibration traps
    failure_codes: Mapping[str, str] = field(default_factory=dict)
    known_limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "research_question": self.research_question,
            "depth": self.depth,
            "rubric": self.rubric.to_dict(),
            "unit_of_analysis": self.unit_of_analysis,
            "strata_design": {k: list(v) for k, v in self.strata_design.items()},
            "target_n": self.target_n,
            "replication": self.replication,
            "gold_rate": self.gold_rate,
            "failure_codes": dict(self.failure_codes),
            "known_limitations": list(self.known_limitations),
        }


__all__ = [
    "Adjudication",
    "Anchor",
    "Annotation",
    "AnnotationSource",
    "Dimension",
    "ModelResponse",
    "Recommendation",
    "Rubric",
    "ScaleType",
    "TaskItem",
    "TrackSpec",
    "Verdict",
    "content_hash",
    "replace",
]
