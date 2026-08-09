"""Track discovery, and the guard against silently misconfigured tracks.

Class of regression protected here: the README claims "adding a fifth domain
requires no change to the harness". Before discovery existed, ``tracks/_load()``
hard-coded four imports and that claim was simply false -- a reviewer who added a
track had to edit the registry, and one who forgot got a silently absent track.
The first test in this file is the executable form of the claim: it writes a
track module into the package, reloads the registry, and asserts the track shows
up with no edit to ``tracks/__init__.py`` anywhere in the process.

The second class of regression is subtler and was created by fixing the first.
Discovery makes it easy to add a track and forget to give it an entry in
``annotation/effects.py``. A track with no effects table has no declared target
dimension for any of its failure codes, so ``detection_sensitivity`` reports
every code as a BLIND SPOT. Those blind spots are fabrications, and they are
formatted identically to real ones. The tests below pin the three places that
must say so out loud: the registration report, the warning, and the
``effects_table_missing`` flag on the sensitivity payload itself.
"""

from __future__ import annotations

import importlib
import warnings
from pathlib import Path

import pytest

import rubricon.tracks as tracks_pkg
from rubricon.annotation.effects import has_effects_table
from rubricon.taxonomy.induce import detection_sensitivity

TRACKS_DIR = Path(tracks_pkg.__file__).resolve().parent
REAL_TRACKS = {"agentic", "grounding", "reasoning", "refusal"}

FIFTH_TRACK_SOURCE = '''\
"""Throwaway track written by the test suite; deleted in teardown."""

from __future__ import annotations

from rubricon.core.schema import (
    Anchor, Dimension, ModelResponse, Rubric, ScaleType, TaskItem, TrackSpec,
)

__all__ = ["SPEC", "seed_items", "fixture_responses"]

_DIM = Dimension(
    key="clarity", name="Clarity", question="Is the answer clear?",
    scale=ScaleType.ORDINAL, levels=(0, 1, 2, 3), weight=1.0,
    anchors=tuple(
        Anchor(value=v, label=f"{v} = level {v}", description=f"Clarity level {v} of 3.")
        for v in (0, 1, 2, 3)
    ),
)

SPEC = TrackSpec(
    key="__TRACK_KEY__", name="Discovery Probe Track",
    research_question="Does registration discover a new module with no harness edit?",
    depth="exploratory", target_n=12, replication=3,
    unit_of_analysis="response",
    rubric=Rubric(key="__TRACK_KEY__", name="Probe rubric",
                  description="Minimal rubric for a discovery test.",
                  dimensions=(_DIM,)),
    gold_rate=0.25,
    strata_design={"style": ("terse", "verbose")},
    failure_codes={"ZF-01": "Answer is vague."},
    known_limitations=("Test fixture only.",),
)


def seed_items() -> list[TaskItem]:
    return [
        TaskItem(
            item_id=f"__TRACK_KEY__-{i:03d}", track=SPEC.key,
            prompt=f"Explain topic {i}.", context="",
            strata={"style": "terse" if i % 2 else "verbose"},
            is_gold=(i % 4 == 0),
            gold_scores={"clarity": 2} if i % 4 == 0 else {},
        )
        for i in range(12)
    ]


def fixture_responses(items: list[TaskItem]) -> list[ModelResponse]:
    out = []
    for sysid in ("sut-baseline-v1", "sut-candidate-v2", "sut-candidate-v3"):
        for i, item in enumerate(items):
            out.append(ModelResponse(
                response_id=f"{item.item_id}::{sysid}",
                item_id=item.item_id, system_id=sysid,
                text=f"A response to {item.item_id}.",
                planted_failure="ZF-01" if i % 3 == 0 else None,
            ))
    return out
'''

NON_TRACK_SOURCE = '''\
"""A module in the tracks package that is NOT a track."""

HELPER_CONSTANT = 3


def helper() -> int:
    return HELPER_CONSTANT
'''


def _write_module(name: str, source: str) -> Path:
    path = TRACKS_DIR / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return path


def _cleanup(paths: list[Path]) -> None:
    for p in paths:
        p.unlink(missing_ok=True)
        cached = p.parent / "__pycache__"
        for pyc in cached.glob(f"{p.stem}.*.pyc"):
            pyc.unlink(missing_ok=True)
    importlib.invalidate_caches()
    tracks_pkg.reload_registry()


@pytest.fixture
def probe_track():
    """Write a fifth track module, reload the registry, and clean up after."""
    key = "discoveryprobe"
    path = _write_module(key, FIFTH_TRACK_SOURCE.replace("__TRACK_KEY__", key))
    importlib.invalidate_caches()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            registry = tracks_pkg.reload_registry()
        yield key, registry, caught
    finally:
        _cleanup([path])


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def test_the_four_real_tracks_are_discovered():
    registry = tracks_pkg.reload_registry()
    assert REAL_TRACKS.issubset(set(registry))


def test_registry_order_is_deterministic_and_sorted():
    """Insertion order decides tie-breaks in ``all_tracks()``, which decides
    the order tracks appear in portfolio.json. Filesystem order would make the
    'same numbers on any machine' claim quietly false."""
    keys = list(tracks_pkg.reload_registry())
    assert keys == sorted(keys)


def test_new_track_module_is_registered_with_no_harness_edit(probe_track):
    key, registry, _ = probe_track
    assert key in registry, "a module exposing the track protocol was not discovered"
    assert REAL_TRACKS.issubset(set(registry)), "discovery dropped an existing track"
    assert tracks_pkg.get(key).spec.key == key
    assert key in tracks_pkg.registration_report()["discovered"]

    # The claim under test is specifically that no harness file changed.
    harness = (TRACKS_DIR / "__init__.py").read_text(encoding="utf-8")
    assert key not in harness


def test_module_without_the_protocol_is_skipped_with_a_reason():
    path = _write_module("notatrack", NON_TRACK_SOURCE)
    try:
        importlib.invalidate_caches()
        registry = tracks_pkg.reload_registry()
        assert "notatrack" not in registry
        report = tracks_pkg.registration_report()
        skipped = {s["module"]: s for s in report["skipped"]}
        assert "notatrack" in skipped
        assert set(skipped["notatrack"]["missing_attributes"]) == set(tracks_pkg.TRACK_PROTOCOL)
        assert REAL_TRACKS.issubset(set(registry))
    finally:
        _cleanup([path])


def test_broken_module_does_not_take_the_other_tracks_offline():
    path = _write_module("brokentrack", "raise RuntimeError('deliberately broken')\n")
    try:
        importlib.invalidate_caches()
        registry = tracks_pkg.reload_registry()
        assert REAL_TRACKS.issubset(set(registry))
        reasons = {s["module"]: s["reason"] for s in tracks_pkg.registration_report()["skipped"]}
        assert "brokentrack" in reasons
        assert "import failed" in reasons["brokentrack"]
    finally:
        _cleanup([path])


# --------------------------------------------------------------------------
# the missing-effects-table guard
# --------------------------------------------------------------------------


def test_missing_effects_table_warns_at_registration(probe_track):
    key, _, caught = probe_track
    assert not has_effects_table(key)
    assert key in tracks_pkg.registration_report()["tracks_missing_effects_table"]
    messages = [
        str(w.message) for w in caught
        if issubclass(w.category, tracks_pkg.MissingEffectsTableWarning)
    ]
    assert messages, "no MissingEffectsTableWarning was raised for a track with no effects table"
    assert key in messages[0]
    assert "blind spot" in messages[0].lower()


def test_missing_effects_table_marks_the_sensitivity_output(probe_track):
    """The flag exists so a fabricated blind spot cannot be read as a real one."""
    key, _, _ = probe_track
    track = tracks_pkg.get(key)
    items = track.items()
    responses = track.responses()

    from rubricon.annotation.pool import annotate

    rows = [a.to_dict() for a in annotate(track.spec, items, responses)]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sens = detection_sensitivity(track.spec, responses, rows)

    assert sens.get("effects_table_missing") is True
    assert key in sens["effects_table_warning"]
    assert any("BLIND SPOT" in str(w.message) for w in caught)


def test_configured_tracks_do_not_carry_the_missing_effects_flag():
    """The flag is emitted only when the table is absent, so a correctly
    configured track's payload -- and therefore portfolio.json -- is unchanged."""
    tracks_pkg.reload_registry()
    track = tracks_pkg.get("refusal")
    from rubricon.annotation.pool import annotate

    rows = [a.to_dict() for a in annotate(track.spec, track.items(), track.responses())]
    sens = detection_sensitivity(track.spec, track.responses(), rows)
    assert "effects_table_missing" not in sens
    assert "effects_table_warning" not in sens
