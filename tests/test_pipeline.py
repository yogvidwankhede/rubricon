"""End-to-end pipeline and client integration.

Class of regression protected here: loss of bit-level reproducibility, which is
the repository's headline claim ("same code, same corpus, same numbers, on any
machine, with no network").

``test_full_pipeline_is_byte_reproducible_across_processes`` runs the whole
portfolio twice in two SEPARATE interpreters with different ``PYTHONHASHSEED``
values and compares ``results.json`` byte for byte. Running twice inside one
process would not test anything interesting: the string hash salt is fixed for
the life of an interpreter, so a seed derived from ``hash(system_id)`` looks
perfectly stable in-process and moves on every real re-run. That defect existed
and this test is what pins the fix.

Also covered: the fixture client must raise on a missing item rather than
quietly shrinking n, and the cache must actually be consulted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rubricon.core.store import Store
from rubricon.models.client import (
    CachedClient,
    FixtureClient,
    GenerationConfig,
    build_client,
)
from rubricon.pipeline import SYSTEMS, run_track
from rubricon.tracks import get, keys

from .conftest import make_item, make_response

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

# The smallest track: 36 items, 108 responses.
SMALLEST_TRACK = "refusal"


# --------------------------------------------------------------------------
# run_track
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def track_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("track_run")
    store = Store(out)
    payload = run_track(get(SMALLEST_TRACK), store)
    return payload, out


def test_run_track_produces_every_expected_key(track_run):
    payload, _out = track_run
    expected = {
        "track", "name", "depth", "depth_contract", "research_question",
        "rubric_version", "unit_of_analysis", "known_limitations",
        "contested_dimensions", "n_items", "n_responses", "n_annotations",
        "mean_replication", "agreement", "alpha_mean", "alpha_min",
        "gold_accuracy", "annotator_pool", "drift", "triage", "rubric_gaps",
        "scores", "comparison", "coverage", "sensitivity", "investment",
        "redteam", "gate", "decision", "composite_reliability",
        "client_provenance",
    }
    missing = expected - set(payload)
    assert not missing, f"run_track payload is missing {sorted(missing)}"
    assert payload["track"] == SMALLEST_TRACK
    assert payload["n_items"] == 36
    assert payload["n_responses"] == 108
    assert payload["n_annotations"] == 108 * 3
    assert payload["mean_replication"] == 3.0


def test_run_track_writes_all_artifacts(track_run):
    _payload, out = track_run
    for name in ("items.jsonl", "responses.jsonl", "annotations.jsonl",
                 "adjudications.jsonl", "spec.json", "results.json"):
        path = out / SMALLEST_TRACK / name
        assert path.exists(), f"missing artifact {name}"
        assert path.stat().st_size > 0

    manifest = Store(out).manifest()
    assert f"{SMALLEST_TRACK}/results.json" in manifest
    assert manifest[f"{SMALLEST_TRACK}/annotations.jsonl"]["records"] == 324
    assert manifest[f"{SMALLEST_TRACK}/items.jsonl"]["records"] == 36


def test_run_track_results_json_matches_the_returned_payload(track_run):
    payload, out = track_run
    on_disk = json.loads((out / SMALLEST_TRACK / "results.json").read_text())
    assert on_disk == json.loads(json.dumps(payload, sort_keys=True, default=str))


def test_gate_and_decision_are_populated(track_run):
    payload, _out = track_run
    gate = payload["gate"]
    assert gate["summary"]["n_claims"] > 0
    assert set(gate["summary"]["by_verdict"]) == {"pass", "warn", "block"}
    assert payload["decision"]["recommendation"] in (
        "invest", "iterate", "hold", "stop"
    )


def test_exploratory_track_blocks_its_ranking_claims(track_run):
    """The depth contract must bite on the exploratory track."""
    payload, _out = track_run
    assert payload["depth"] == "exploratory"
    ranking_claims = [c for c in payload["gate"]["claims"] if c["kind"] == "ranking"]
    assert ranking_claims
    assert all(c["verdict"] == "block" for c in ranking_claims)
    assert any(
        "does NOT permit" in reason
        for c in ranking_claims
        for reason in c["blocking_reasons"]
    )


# --------------------------------------------------------------------------
# reproducibility
# --------------------------------------------------------------------------


_RUN_SCRIPT = """
import sys
from rubricon.pipeline import run_all
run_all(sys.argv[1])
"""


def _run_pipeline_in_subprocess(out_dir: Path, hash_seed: str) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        [sys.executable, "-c", _RUN_SCRIPT, str(out_dir)],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stderr[-4000:]


def test_full_pipeline_is_byte_reproducible_across_processes(tmp_path):
    first = tmp_path / "run_a"
    second = tmp_path / "run_b"
    _run_pipeline_in_subprocess(first, hash_seed="0")
    _run_pipeline_in_subprocess(second, hash_seed="12345")

    track_keys = keys()
    assert track_keys, "no tracks registered"

    divergences = []
    for key in track_keys:
        a = (first / key / "results.json").read_bytes()
        b = (second / key / "results.json").read_bytes()
        if a != b:
            divergences.append((key, _first_difference(a, b)))
    assert not divergences, "results.json diverged: " + "; ".join(
        f"{k}: {d}" for k, d in divergences
    )

    # The portfolio roll-up must be reproducible too.
    assert (first / "summary.json").read_bytes() == (second / "summary.json").read_bytes()


def _first_difference(a: bytes, b: bytes) -> str:
    """Locate the first differing JSON leaf so a failure is actionable."""
    try:
        da, db = json.loads(a), json.loads(b)
    except json.JSONDecodeError:
        return "unparseable JSON"

    def walk(x, y, path=""):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                found = walk(x.get(k), y.get(k), f"{path}.{k}")
                if found:
                    return found
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                return f"{path}: length {len(x)} vs {len(y)}"
            for i, (xi, yi) in enumerate(zip(x, y)):
                found = walk(xi, yi, f"{path}[{i}]")
                if found:
                    return found
        elif x != y:
            return f"{path}: {x!r} vs {y!r}"
        return None

    return walk(da, db) or "byte-level difference outside parsed JSON"


def test_run_track_is_stable_within_a_process(tmp_path):
    a = run_track(get(SMALLEST_TRACK), Store(tmp_path / "a"))
    b = run_track(get(SMALLEST_TRACK), Store(tmp_path / "b"))
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(
        b, sort_keys=True, default=str
    )


# --------------------------------------------------------------------------
# clients
# --------------------------------------------------------------------------


def test_fixture_client_replays_the_corpus():
    items = [make_item("i1"), make_item("i2")]
    responses = [
        make_response("r1", "i1", system_id="sut-a", text="one"),
        make_response("r2", "i2", system_id="sut-a", text="two"),
        make_response("r3", "i1", system_id="sut-b", text="other system"),
    ]
    client = FixtureClient(responses, "sut-a")
    cfg = GenerationConfig()
    assert client.generate(items[0], cfg).text == "one"
    assert client.generate(items[1], cfg).text == "two"
    assert [r.response_id for r in client.generate_batch(items, cfg)] == ["r1", "r2"]
    assert client.provenance()["n_fixtures"] == 2
    assert client.provenance()["is_live"] is False


def test_fixture_client_raises_on_a_missing_item():
    """A missing fixture must not silently reduce n."""
    client = FixtureClient([make_response("r1", "i1", system_id="sut-a")], "sut-a")
    with pytest.raises(KeyError) as exc:
        client.generate(make_item("i-absent"), GenerationConfig())
    message = str(exc.value)
    assert "i-absent" in message
    assert "silently reduce n" in message


def test_cached_client_hits_the_cache_on_the_second_call(tmp_path):
    responses = [make_response("r1", "i1", system_id="sut-a", text="cached text")]
    inner = FixtureClient(responses, "sut-a")
    client = CachedClient(inner, cache_dir=tmp_path / "cache")
    item = make_item("i1")
    cfg = GenerationConfig()

    first = client.generate(item, cfg)
    assert (client.hits, client.misses) == (0, 1)

    second = client.generate(item, cfg)
    assert (client.hits, client.misses) == (1, 1)
    assert second == first
    assert second.text == "cached text"

    prov = client.provenance()
    assert prov["cache_hits"] == 1 and prov["cache_misses"] == 1


def test_cache_key_separates_different_decoding_parameters(tmp_path):
    responses = [make_response("r1", "i1", system_id="sut-a", text="t")]
    client = CachedClient(FixtureClient(responses, "sut-a"), cache_dir=tmp_path / "c")
    item = make_item("i1")

    client.generate(item, GenerationConfig(temperature=0.0))
    client.generate(item, GenerationConfig(temperature=1.0))
    assert client.misses == 2, "a temperature change is a different experiment"
    assert client.hits == 0

    client.generate(item, GenerationConfig(temperature=1.0))
    assert client.hits == 1


# --------------------------------------------------------------------------
# RUBRICON_CLIENT
# --------------------------------------------------------------------------


def test_rubricon_client_env_var_selects_the_backend(monkeypatch, tmp_path):
    """The documented env var must actually be read.

    ``RUBRICON_CLIENT`` was named in a LiveClient error message and read
    nowhere, so setting it did nothing at all and the default fixture path was
    the only path. It now selects the client, and the choice is recorded in the
    provenance block of every track payload.
    """
    monkeypatch.delenv("RUBRICON_CLIENT", raising=False)
    payload = run_track(get(SMALLEST_TRACK), Store(tmp_path / "default"))
    prov = payload["client_provenance"]
    assert set(prov) == set(SYSTEMS)
    for entry in prov.values():
        assert entry["client"] == "FixtureClient"
        assert entry["is_live"] is False

    monkeypatch.setenv("RUBRICON_CLIENT", "FIXTURE")
    again = run_track(get(SMALLEST_TRACK), Store(tmp_path / "explicit"))
    assert again["client_provenance"] == prov
    assert again["scores"] == payload["scores"]


def test_rubricon_client_rejects_an_unknown_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("RUBRICON_CLIENT", "not-a-client")
    with pytest.raises(ValueError) as exc:
        run_track(get(SMALLEST_TRACK), Store(tmp_path / "bad"))
    assert "not-a-client" in str(exc.value)


def test_build_client_returns_the_requested_implementation():
    responses = [make_response("r1", "i1", system_id="sut-a")]
    assert isinstance(build_client("fixture", "sut-a", fixtures=responses), FixtureClient)
    assert isinstance(build_client("", "sut-a", fixtures=responses), FixtureClient)
    with pytest.raises(ValueError):
        build_client("fixture", "sut-a", fixtures=None)
