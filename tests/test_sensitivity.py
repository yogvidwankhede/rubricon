"""Verdict-sensitivity machinery.

Class of regression protected here: a sensitivity analysis that has quietly
stopped measuring the thing it claims to measure. That failure is invisible in
the output -- the JSON still looks full of numbers -- and it is uniquely
damaging, because the whole purpose of the analysis is to be the artifact a
skeptical reader trusts when they no longer trust the headline.

Three mechanisms carry that risk and each is pinned below.

``make_observe`` is a hand-copy of ``pool._observe`` with the two multipliers
lifted out. If anyone edits the production formula, the noise sweep silently
starts measuring a formula the pipeline does not use.
``test_observe_replica_matches_production`` is the check that turns that into a
loud failure; it is also called at the top of every real run.

``discover_decision_cuts`` parses ``decision.py`` rather than hard-coding its
magic numbers, precisely so that a newly added cut cannot escape the sweep. The
tests here assert it finds the cuts that exist today and that a recompiled
engine reproduces the production verdict when nothing is substituted.

``Chain.regate`` replays cached evidence under a new policy. If it silently
stopped responding to the policy, every threshold would be reported as perfectly
stable -- the most reassuring possible wrong answer.
"""

from __future__ import annotations

import dataclasses

import pytest

from rubricon.annotation import pool as pool_mod
from rubricon.annotation.effects import (
    DIMENSION_PROPERTIES,
    contested_dimensions,
    properties_for,
    property_overrides,
)
from rubricon.gates import sensitivity as S
from rubricon.gates.decision import recommend
from rubricon.gates.signal import policy_for_depth


# --------------------------------------------------------------------------
# the _observe replica
# --------------------------------------------------------------------------


def test_observe_replica_matches_production():
    """The noise sweep is only meaningful if its replica IS the production formula."""
    assert S.verify_observe_replica("refusal") is True


def test_observe_replica_actually_responds_to_its_multipliers():
    """A replica that ignored its arguments would pass the equality check above
    and make every noise sweep look perfectly flat."""
    from rubricon.tracks import get

    track = get("refusal")
    items, responses = track.items(), track.responses()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pool_mod, "_observe", S.make_observe(1.6, 2.60))
        noisy = [a.to_dict()["scores"] for a in pool_mod.annotate(track.spec, items, responses)]
    quiet = [a.to_dict()["scores"] for a in pool_mod.annotate(track.spec, items, responses)]
    assert noisy != quiet


# --------------------------------------------------------------------------
# contested-flag overrides
# --------------------------------------------------------------------------


def test_property_overrides_are_scoped_and_restore_the_default():
    baseline = contested_dimensions("refusal")
    assert baseline, "refusal is expected to have contested dimensions by default"
    with property_overrides(S.properties_with_contested([])):
        assert contested_dimensions("refusal") == []
        assert properties_for("refusal")["calibration"]["contested"] is False
    assert contested_dimensions("refusal") == baseline


def test_property_overrides_restore_after_an_exception():
    """A leaked override would silently contaminate every later analysis."""
    baseline = contested_dimensions("refusal")
    with pytest.raises(RuntimeError):
        with property_overrides(S.properties_with_contested([])):
            raise RuntimeError("boom")
    assert contested_dimensions("refusal") == baseline


def test_properties_with_contested_preserves_noise_values():
    """The contested sweep must isolate the flag; perturbing noise at the same
    time would confound two assumptions with different remedies."""
    table = S.properties_with_contested([])
    for track, dims in DIMENSION_PROPERTIES.items():
        for dim, props in dims.items():
            assert table[track][dim]["noise"] == props["noise"]
            assert table[track][dim]["contested"] is False


def test_random_configurations_hold_the_contested_count_constant():
    n = len(S.baseline_contested_slots())
    configs = S.contested_configurations(n_seeds=5)
    for name, table in configs.items():
        if not name.startswith("random_"):
            continue
        total = sum(
            1 for dims in table.values() for p in dims.values() if p["contested"]
        )
        assert total == n, f"{name} changed the number of contested flags"


def test_contested_configurations_include_the_reviewers_edit():
    configs = S.contested_configurations(n_seeds=1)
    swap = configs["reviewer_swap"]
    assert not any(p["contested"] for p in swap["refusal"].values())
    assert sum(1 for p in swap["agentic"].values() if p["contested"]) == 3


# --------------------------------------------------------------------------
# decision-engine cut discovery
# --------------------------------------------------------------------------


def test_discovers_the_documented_decision_cuts():
    values = {c.value for c in S.discover_decision_cuts()}
    # The cuts named in the review: alpha_max, alpha_mean/irreducible, rubric
    # gap, gold precondition, broken dimension.
    for expected in (0.60, 0.55, 0.30, 0.70, 0.40):
        assert expected in values, f"cut {expected} was not discovered in decision.py"


def test_discovered_cuts_are_uniquely_addressable():
    cuts = S.discover_decision_cuts()
    positions = [(c.lineno, c.col_offset) for c in cuts]
    assert len(positions) == len(set(positions))
    assert len({c.cut_id for c in cuts}) == len(cuts)


def test_zero_valued_guards_are_not_swept():
    """A relative sweep around zero is undefined, and ``> 0`` is a degeneracy
    guard rather than a tunable threshold."""
    assert all(c.value != 0 for c in S.discover_decision_cuts())


def test_recompiled_engine_reproduces_production_at_the_configured_value(chain_and_evidence):
    _, evidence = chain_and_evidence
    production = recommend(evidence.decision_input).recommendation
    for cut in S.discover_decision_cuts():
        module = S._decision_module_with(cut, cut.value)
        assert module.recommend(evidence.decision_input).recommendation == production, (
            f"recompiling decision.py with cut {cut.cut_id} at its own value "
            "changed the verdict; the sweep is not measuring the real engine"
        )


def test_recompiling_does_not_replace_the_production_module():
    import sys

    cut = S.discover_decision_cuts()[0]
    S._decision_module_with(cut, cut.value * 0.5)
    assert not [n for n in sys.modules if "_decision_swept" in n]
    from rubricon.gates import decision

    assert sys.modules["rubricon.gates.decision"] is decision


# --------------------------------------------------------------------------
# re-gating from cached evidence
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chain_and_evidence():
    chain = S.Chain()
    return chain, chain.baseline("refusal")


def test_regate_reproduces_the_production_ledger(chain_and_evidence):
    chain, evidence = chain_and_evidence
    counts = chain.regate(evidence, policy_for_depth(evidence.depth))
    assert counts["claims"] == list(evidence.verdict_tuple())
    assert sum(counts["checks"]) > sum(counts["claims"])


def test_regate_responds_to_the_policy(chain_and_evidence):
    """A regate that ignored the policy would report every threshold as stable."""
    chain, evidence = chain_and_evidence
    base = policy_for_depth(evidence.depth)
    strict = chain.regate(evidence, dataclasses.replace(base, alpha_block_below=0.99))
    loose = chain.regate(evidence, dataclasses.replace(base, alpha_block_below=0.001))
    assert strict["claims"][2] > loose["claims"][2]


def test_check_level_counts_expose_a_flip_that_claim_counts_hide(chain_and_evidence):
    """The 0.34-versus-0.333 case: lowering the flagged-annotator budget moves
    checks inside claims that are already blocked, so a claim-level-only
    outcome would call the threshold perfectly stable."""
    chain, evidence = chain_and_evidence
    base = policy_for_depth(evidence.depth)
    high = chain.regate(evidence, dataclasses.replace(base, max_flagged_annotator_fraction=0.90))
    low = chain.regate(evidence, dataclasses.replace(base, max_flagged_annotator_fraction=0.01))
    assert high["checks"] != low["checks"]


# --------------------------------------------------------------------------
# sweep grid and flip location
# --------------------------------------------------------------------------


def test_sweep_values_cover_the_required_relative_steps():
    values = S.sweep_values(0.34)
    for pct in (-0.30, -0.20, -0.10, 0.10, 0.20, 0.30):
        assert any(abs(v - 0.34 * (1 + pct)) < 1e-6 for v in values), pct
    assert 0.34 in values
    assert 0.35 in values, "nearby round numbers must be included"
    assert values == sorted(values)


def test_sweep_values_are_integral_for_integral_thresholds():
    values = S.sweep_values(5, integral=True)
    assert all(isinstance(v, int) for v in values)
    assert 5 in values and min(values) >= 0


def test_sweep_values_do_not_clip_a_ratio_above_one():
    """``mde_safety_margin`` defaults to 1.0 and is meaningful above it."""
    assert max(S.sweep_values(1.0)) > 1.0


def test_bisect_finds_a_known_boundary():
    step = lambda x: "high" if x >= 0.333 else "low"  # noqa: E731
    found = S._bisect_flip(step, 0.40, 0.20, integral=False)
    assert abs(found - 0.333) <= 1e-3


def test_analyse_threshold_flags_a_near_boundary_as_fragile():
    """A threshold set at 0.34 against a boundary at 0.333 is 2% away and must
    come back FRAGILE -- this is the exact case the review raised."""
    def evaluate(value: float) -> dict:
        ok = 0.3333 <= value
        return {
            "claim_verdicts": [1, 0, 0] if ok else [0, 1, 0],
            "check_verdicts": [3, 0, 0] if ok else [2, 1, 0],
            "recommendation": "invest",
        }

    result = S._analyse_threshold(
        name="GatePolicy.max_flagged_annotator_fraction", source="test",
        default=0.34, track="demo", evaluate=evaluate, integral=False,
        grid=S.sweep_values(0.34),
    )
    assert result.fragile is True
    assert result.nearest_flip is not None
    assert abs(result.nearest_flip - 0.3333) < 1e-2
    assert result.relative_distance_to_flip < S.FRAGILITY_BAND
    assert "FRAGILE" in result.note


def test_analyse_threshold_reports_a_distant_boundary_as_stable():
    def evaluate(value: float) -> dict:
        ok = value >= 0.10
        return {
            "claim_verdicts": [1, 0, 0] if ok else [0, 0, 1],
            "check_verdicts": [1, 0, 0] if ok else [0, 0, 1],
            "recommendation": "invest",
        }

    result = S._analyse_threshold(
        name="demo", source="test", default=0.80, track="demo",
        evaluate=evaluate, integral=False, grid=S.sweep_values(0.80),
    )
    assert result.fragile is False
    assert result.stable_lo is not None and result.stable_lo <= 0.80


# --------------------------------------------------------------------------
# end to end, small
# --------------------------------------------------------------------------


def test_run_sensitivity_produces_a_classified_payload(tmp_path):
    """One track, two seeds: enough to exercise every analysis and the writer."""
    payload = S.run_sensitivity(
        results_dir=tmp_path, track_keys=["refusal"], n_contested_seeds=2,
        write=True, verbose=False,
    )
    assert (tmp_path / "sensitivity.json").exists()
    for block in (
        "classification", "contested_flag_sensitivity", "threshold_sensitivity",
        "noise_sensitivity", "leave_one_annotator_out", "limitations",
    ):
        assert block in payload

    cls = payload["classification"]["refusal"]
    assert cls["classification"] in {"ROBUST", "CONDITIONAL", "FRAGILE"}
    assert cls["recommendation"] == "stop"

    contested = payload["contested_flag_sensitivity"]["per_track"]["refusal"]
    assert contested["baseline_recommendation"] == "stop"
    assert set(contested["named_variants"]) >= {"all_off", "all_on", "refusal_off"}

    loo = payload["leave_one_annotator_out"]
    assert set(loo["per_annotator"]) == {a.annotator_id for a in pool_mod.ROSTER}


def test_null_store_writes_nothing(tmp_path):
    store = S.NullStore()
    store.write_json("a/b.json", {"x": 1})
    store.write_jsonl("a/c.jsonl", [{"y": 2}])
    assert not (tmp_path / "a").exists()
    assert not S.NullStore().root.exists()
