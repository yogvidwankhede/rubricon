"""Track registry.

A track is a self-contained evaluation: a research question, a rubric, a
sampling design, and a corpus. Tracks are registered rather than hard-coded so
that adding a fifth domain requires no change to the harness -- which is the
claim the four-track portfolio is meant to substantiate.

Tracks declare a ``depth`` and the harness enforces what that depth permits.
An ``exploratory`` track cannot emit a production claim no matter how good its
numbers look, because its sampling design was never powered for one.

Discovery
---------
Registration is by **discovery**, not by an import list. ``_load()`` walks
``pkgutil.iter_modules(__path__)`` and registers every sibling module in this
package that exposes the track protocol -- ``SPEC``, ``seed_items``, and
``fixture_responses``. Dropping ``src/rubricon/tracks/mytrack.py`` into the
package is the whole of the work; nothing in the harness is edited.

This is not cosmetic. An earlier version hard-coded
``from . import agentic, grounding, reasoning, refusal``, which meant the
documented claim ("adding a fifth domain requires no change to the harness")
was false: a reviewer who added a track had to edit this file, and a reviewer
who *forgot* to edit this file got a silently absent track rather than an
error. A claim about extensibility that the code contradicts is worse than no
claim, because it is the kind of thing readers take on trust.

Modules that do not expose the protocol are skipped with an explicit message
rather than crashing the harness, because a half-written track under
development should not take the other four offline.

Effects-table guard
-------------------
Discovery introduces a second failure mode that the hard-coded list masked.
``annotation.effects`` keys its penalty tables by track, and
``effects_for(unknown_track)`` returns ``{}``. An auto-discovered track with no
entry there therefore annotates cleanly but has no declared target dimensions,
so ``taxonomy.induce.detection_sensitivity`` compares planted responses against
an empty target set and reports every failure code as a BLIND SPOT. Those blind
spots are artifacts of a missing configuration file, not findings about the
instrument -- and they are indistinguishable from real ones in the output.

``registration_report()`` records which registered tracks lack an effects
table, the registry emits a loud warning at import time, and
``detection_sensitivity`` stamps ``effects_table_missing: true`` on its own
output so no downstream consumer can read fabricated blind spots as real.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import warnings
from types import ModuleType
from typing import Callable

from ..core.schema import ModelResponse, TaskItem, TrackSpec

#: Attributes a module must expose to be registered as a track.
TRACK_PROTOCOL: tuple[str, ...] = ("SPEC", "seed_items", "fixture_responses")


class MissingEffectsTableWarning(UserWarning):
    """A registered track has no entry in ``annotation.effects.EFFECTS``.

    Raised as a warning rather than an exception on purpose: the track is still
    runnable and its agreement statistics are still meaningful. What is *not*
    meaningful is its detection-sensitivity output, and that is exactly the
    number a reader is most likely to quote.
    """

DEPTH_ORDER = {"exploratory": 0, "pilot": 1, "production": 2}

# What each maturity tier is allowed to support.
DEPTH_CONTRACT = {
    "exploratory": (
        "Hypothesis generation only. May report descriptive statistics and "
        "qualitative failure examples. May NOT report system rankings, deltas "
        "between systems, or any claim framed as a measurement."
    ),
    "pilot": (
        "May report measurements with intervals and an explicit MDE. May report "
        "system deltas ONLY when the interval excludes zero and the delta exceeds "
        "the MDE. May not be used as a release gate."
    ),
    "production": (
        "May report measurements, system rankings, and may act as a release gate, "
        "provided all signal-gate checks pass."
    ),
}


class Track:
    """Lazy handle on a track module."""

    def __init__(
        self,
        spec: TrackSpec,
        seed_fn: Callable[[], list[TaskItem]],
        fixture_fn: Callable[[list[TaskItem]], list[ModelResponse]],
    ) -> None:
        self.spec = spec
        self._seed_fn = seed_fn
        self._fixture_fn = fixture_fn
        self._items: list[TaskItem] | None = None

    @property
    def key(self) -> str:
        return self.spec.key

    def items(self) -> list[TaskItem]:
        if self._items is None:
            self._items = list(self._seed_fn())
        return self._items

    def responses(self) -> list[ModelResponse]:
        return list(self._fixture_fn(self.items()))

    def permits(self, claim_kind: str) -> bool:
        d = self.spec.depth
        if claim_kind == "descriptive":
            return True
        if claim_kind == "measurement":
            return DEPTH_ORDER.get(d, 0) >= 1
        if claim_kind in ("ranking", "release_gate"):
            return DEPTH_ORDER.get(d, 0) >= 2
        return False

    def __repr__(self) -> str:
        return f"<Track {self.spec.key} depth={self.spec.depth} n={self.spec.target_n}>"


def _module_is_track(mod: ModuleType) -> list[str]:
    """Return the protocol attributes ``mod`` is missing (empty list = a track)."""
    return [attr for attr in TRACK_PROTOCOL if not hasattr(mod, attr)]


def _loud(message: str) -> None:
    """Write to stderr unconditionally.

    ``warnings.warn`` alone is not enough here: the default filter shows a given
    warning once per location per process, and pytest / library callers routinely
    suppress UserWarning entirely. A misconfigured track produces plausible-looking
    numbers, so the failure mode is silent-and-wrong rather than loud-and-broken.
    Both channels are used: stderr so a human sees it, ``warnings`` so a test can
    assert on it.
    """
    print(f"WARNING [rubricon.tracks] {message}", file=sys.stderr)


def _load() -> dict[str, Track]:
    """Discover and register every track module in this package.

    Iteration order is sorted by module name so the registry dict has a stable
    insertion order across platforms and filesystems. That matters downstream:
    ``all_tracks()`` sorts by depth with Python's stable sort, so dict order is
    the tiebreak, and the tiebreak decides the order tracks appear in
    ``portfolio.json``. Leaving it to filesystem enumeration order would make
    the "same numbers on any machine" claim quietly false.
    """
    from ..annotation.effects import has_effects_table

    registry: dict[str, Track] = {}
    discovered: list[str] = []
    skipped: list[dict] = []
    missing_effects: list[str] = []

    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_") or info.ispkg:
            continue
        dotted = f"{__name__}.{info.name}"
        try:
            mod = importlib.import_module(dotted)
        except Exception as exc:  # pragma: no cover - defensive
            # A broken module under development must not take the portfolio
            # offline, but it must also not vanish without trace.
            skipped.append({"module": info.name, "reason": f"import failed: {exc!r}"})
            _loud(f"module '{dotted}' failed to import and was NOT registered: {exc!r}")
            continue

        missing = _module_is_track(mod)
        if missing:
            skipped.append({
                "module": info.name,
                "reason": "does not expose the track protocol",
                "missing_attributes": missing,
            })
            continue

        spec = mod.SPEC
        key = spec.key
        if key in registry:
            raise RuntimeError(
                f"duplicate track key {key!r}: module '{dotted}' collides with an "
                "already-registered track. Track keys index every results artifact, "
                "so a collision would silently overwrite one track's output with "
                "another's."
            )
        registry[key] = Track(spec, mod.seed_items, mod.fixture_responses)
        discovered.append(key)

        if not has_effects_table(key):
            missing_effects.append(key)
            msg = (
                f"track '{key}' is registered but has no entry in "
                "rubricon.annotation.effects.EFFECTS / DIMENSION_PROPERTIES. Its "
                "planted failures carry no declared target dimensions, so "
                "detection_sensitivity will report EVERY failure code for this "
                "track as a blind spot. Those blind spots are artifacts of the "
                "missing effect table, not findings. Add an effects table before "
                "quoting any sensitivity number for this track."
            )
            _loud(msg)
            warnings.warn(msg, MissingEffectsTableWarning, stacklevel=2)

    global _REGISTRATION_REPORT
    _REGISTRATION_REPORT = {
        "discovered": discovered,
        "skipped": skipped,
        "tracks_missing_effects_table": missing_effects,
        "protocol": list(TRACK_PROTOCOL),
    }
    return registry


_REGISTRY: dict[str, Track] | None = None
_REGISTRATION_REPORT: dict = {
    "discovered": [],
    "skipped": [],
    "tracks_missing_effects_table": [],
    "protocol": list(TRACK_PROTOCOL),
}


def registry() -> dict[str, Track]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _load()
    return _REGISTRY


def registration_report() -> dict:
    """What discovery found, what it skipped, and what is misconfigured.

    Exposed so that reporting tools can surface a skipped or effects-table-less
    track instead of letting it be inferred from a track's absence from a table.
    """
    registry()
    return dict(_REGISTRATION_REPORT)


def reload_registry() -> dict[str, Track]:
    """Force re-discovery. Used by tests that add or remove a track module."""
    global _REGISTRY
    _REGISTRY = None
    return registry()


def get(key: str) -> Track:
    reg = registry()
    if key not in reg:
        raise KeyError(f"unknown track {key!r}; available: {sorted(reg)}")
    return reg[key]


def all_tracks() -> list[Track]:
    return [registry()[k] for k in sorted(registry(), key=lambda k: -DEPTH_ORDER.get(registry()[k].spec.depth, 0))]


def keys() -> list[str]:
    return sorted(registry())


def scales_for(spec: TrackSpec) -> dict[str, str]:
    """Map dimension key -> agreement metric name for that dimension's scale."""
    return {d.key: d.scale.value for d in spec.rubric.dimensions}


__all__ = [
    "DEPTH_CONTRACT",
    "DEPTH_ORDER",
    "MissingEffectsTableWarning",
    "TRACK_PROTOCOL",
    "Track",
    "all_tracks",
    "get",
    "keys",
    "registration_report",
    "registry",
    "reload_registry",
    "scales_for",
]
