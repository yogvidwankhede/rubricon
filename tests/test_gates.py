"""Guards the signal gate.

Class of regression protected here: a number escaping into a deck that the
measurement cannot support. The gate is the only mechanical control between
"someone wants to say this" and "the report says this", so its verdict logic
has to be exact:

* thresholds must map to BLOCK / WARN / PASS in the right bands, and an
  undefined alpha must BLOCK rather than pass through as a missing value;
* the depth contract must actually stop an exploratory track from emitting a
  ranking or a measurement;
* a claim's verdict must be the WORST of its checks, never the first or the
  last one evaluated;
* and blocked claims must stay in the ledger. A report that silently omits its
  failures is indistinguishable from one that had none.
"""

from __future__ import annotations

import math

from rubricon.core.schema import Verdict
from rubricon.gates.signal import (
    DEFAULT_POLICY,
    EXPLORATORY_POLICY,
    Check,
    Claim,
    ClaimLedger,
    GatePolicy,
    SignalGate,
    policy_for_depth,
)


def _gate(depth="pilot", policy=None):
    return SignalGate(policy, depth=depth)


# --------------------------------------------------------------------------
# reliability
# --------------------------------------------------------------------------


def test_check_reliability_bands():
    gate = _gate()
    p = DEFAULT_POLICY

    below_floor = gate.check_reliability(p.alpha_block_below - 0.01)
    assert below_floor.verdict is Verdict.BLOCK
    assert "below the blocking floor" in below_floor.message
    assert below_floor.remedy

    between = gate.check_reliability((p.alpha_block_below + p.alpha_warn_below) / 2)
    assert between.verdict is Verdict.WARN

    just_under_warn = gate.check_reliability(p.alpha_warn_below - 0.001)
    assert just_under_warn.verdict is Verdict.WARN

    tentative = gate.check_reliability(p.alpha_warn_below + 0.001)
    assert tentative.verdict is Verdict.PASS

    firm = gate.check_reliability(0.91)
    assert firm.verdict is Verdict.PASS
    assert "firm conclusions" in firm.message


def test_check_reliability_blocks_on_nan_and_none():
    gate = _gate()
    assert gate.check_reliability(float("nan")).verdict is Verdict.BLOCK
    assert gate.check_reliability(None).verdict is Verdict.BLOCK
    assert "undefined" in gate.check_reliability(float("nan")).message


def test_reliability_check_labels_the_dimension():
    check = _gate().check_reliability(0.2, dimension="calibration")
    assert check.name == "reliability:calibration"


def test_exploratory_policy_moves_the_reliability_floor():
    strict = _gate(depth="pilot").check_reliability(0.40)
    loose = _gate(depth="exploratory").check_reliability(0.40)
    assert strict.verdict is Verdict.BLOCK
    assert loose.verdict is Verdict.WARN


# --------------------------------------------------------------------------
# depth contract
# --------------------------------------------------------------------------


def test_exploratory_depth_permits_only_descriptive_claims():
    gate = _gate(depth="exploratory")
    assert gate.check_depth_contract("descriptive").verdict is Verdict.PASS
    for kind in ("measurement", "ranking", "release_gate"):
        check = gate.check_depth_contract(kind)
        assert check.verdict is Verdict.BLOCK, f"{kind} must be blocked at exploratory"
        assert "does NOT permit" in check.message
        assert check.remedy


def test_pilot_depth_permits_measurement_but_not_ranking():
    gate = _gate(depth="pilot")
    assert gate.check_depth_contract("descriptive").verdict is Verdict.PASS
    assert gate.check_depth_contract("measurement").verdict is Verdict.PASS
    assert gate.check_depth_contract("ranking").verdict is Verdict.BLOCK


def test_production_depth_permits_everything():
    gate = _gate(depth="production")
    for kind in ("descriptive", "measurement", "ranking", "release_gate"):
        assert gate.check_depth_contract(kind).verdict is Verdict.PASS


def test_policy_for_depth_selects_the_documented_policies():
    assert policy_for_depth("exploratory") is EXPLORATORY_POLICY
    assert policy_for_depth("pilot") is DEFAULT_POLICY
    assert policy_for_depth("production") is DEFAULT_POLICY


# --------------------------------------------------------------------------
# effect vs MDE
# --------------------------------------------------------------------------


def test_effect_below_mde_blocks():
    check = _gate().check_effect_vs_mde(effect=0.018, mde=0.060)
    assert check.verdict is Verdict.BLOCK
    assert "is BELOW" in check.message
    assert "noise floor" in check.remedy


def test_effect_above_mde_passes():
    check = _gate().check_effect_vs_mde(effect=0.120, mde=0.060)
    assert check.verdict is Verdict.PASS
    assert "exceeds" in check.message


def test_effect_check_uses_absolute_value():
    assert _gate().check_effect_vs_mde(effect=-0.12, mde=0.06).verdict is Verdict.PASS


def test_effect_check_is_waived_under_the_exploratory_policy():
    gate = SignalGate(EXPLORATORY_POLICY, depth="exploratory")
    assert EXPLORATORY_POLICY.require_effect_exceeds_mde is False
    check = gate.check_effect_vs_mde(effect=0.0001, mde=0.9)
    assert check.verdict is Verdict.PASS
    assert "waived by policy" in check.message


def test_mde_safety_margin_is_respected():
    strict = SignalGate(GatePolicy(mde_safety_margin=2.0))
    assert strict.check_effect_vs_mde(effect=0.10, mde=0.06).verdict is Verdict.BLOCK
    assert strict.check_effect_vs_mde(effect=0.13, mde=0.06).verdict is Verdict.PASS


# --------------------------------------------------------------------------
# interval excludes zero
# --------------------------------------------------------------------------


def test_interval_straddling_zero_blocks():
    check = _gate().check_interval_excludes_zero(-0.02, 0.05)
    assert check.verdict is Verdict.BLOCK
    assert "CONTAINS" in check.message
    assert "tie" in check.remedy


def test_interval_excluding_zero_passes():
    assert _gate().check_interval_excludes_zero(0.01, 0.09).verdict is Verdict.PASS
    assert _gate().check_interval_excludes_zero(-0.09, -0.01).verdict is Verdict.PASS


def test_interval_touching_zero_blocks():
    assert _gate().check_interval_excludes_zero(0.0, 0.09).verdict is Verdict.BLOCK


def test_missing_interval_blocks():
    assert _gate().check_interval_excludes_zero(None, None).verdict is Verdict.BLOCK
    nan = float("nan")
    assert _gate().check_interval_excludes_zero(nan, nan).verdict is Verdict.BLOCK


# --------------------------------------------------------------------------
# precision, replication, coverage
# --------------------------------------------------------------------------


def test_precision_check_warns_over_budget_and_blocks_when_missing():
    gate = _gate()
    assert gate.check_precision(0.02).verdict is Verdict.PASS
    assert gate.check_precision(0.5).verdict is Verdict.WARN
    assert gate.check_precision(float("nan")).verdict is Verdict.BLOCK


def test_replication_below_minimum_blocks():
    gate = _gate()
    assert gate.check_replication(3.0).verdict is Verdict.PASS
    assert gate.check_replication(1.0).verdict is Verdict.BLOCK


def test_coverage_blocks_on_absent_levels_and_warns_on_thin_ones():
    gate = _gate()
    absent = gate.check_coverage(
        {"marginal_gap_fraction": 0.1, "absent_levels": ["domain=legal"],
         "thin_levels": [], "worst_balance_ratio": 0.9}
    )
    assert absent.verdict is Verdict.BLOCK

    thin = gate.check_coverage(
        {"marginal_gap_fraction": 0.5, "absent_levels": [],
         "thin_levels": ["domain=legal (n=2)"], "worst_balance_ratio": 0.9}
    )
    assert thin.verdict is Verdict.WARN

    ok = gate.check_coverage(
        {"marginal_gap_fraction": 0.0, "absent_levels": [], "thin_levels": [],
         "worst_balance_ratio": 0.9, "total_declared_levels": 8}
    )
    assert ok.verdict is Verdict.PASS


# --------------------------------------------------------------------------
# claim composition
# --------------------------------------------------------------------------


def _claim(checks):
    return Claim(
        claim_id="t.c1", track="t", text="a sentence", kind="measurement", checks=list(checks)
    )


def _check(verdict, name="c"):
    return Check(name, verdict, 0.0, 0.0, f"{name} says {verdict.value}")


def test_claim_verdict_is_block_if_any_check_blocks():
    claim = _claim([
        _check(Verdict.PASS, "a"),
        _check(Verdict.WARN, "b"),
        _check(Verdict.BLOCK, "c"),
        _check(Verdict.PASS, "d"),
    ])
    assert claim.verdict is Verdict.BLOCK
    assert claim.blocking_reasons == ["c says block"]
    assert claim.warnings == ["b says warn"]


def test_claim_verdict_is_warn_when_a_check_warns_and_none_block():
    claim = _claim([_check(Verdict.PASS, "a"), _check(Verdict.WARN, "b")])
    assert claim.verdict is Verdict.WARN
    assert claim.blocking_reasons == []


def test_claim_verdict_is_pass_when_everything_passes():
    claim = _claim([_check(Verdict.PASS, "a"), _check(Verdict.PASS, "b")])
    assert claim.verdict is Verdict.PASS


def test_claim_with_no_checks_passes_vacuously():
    assert _claim([]).verdict is Verdict.PASS


def test_all_checks_run_rather_than_short_circuiting():
    """Four problems must be reported as four problems, not as one."""
    claim = _claim([_check(Verdict.BLOCK, f"c{i}") for i in range(4)])
    assert len(claim.blocking_reasons) == 4


def test_gate_evaluate_attaches_checks():
    gate = _gate()
    claim = Claim(claim_id="x", track="t", text="t", kind="descriptive")
    checks = [gate.check_reliability(0.9), gate.check_depth_contract("descriptive")]
    evaluated = gate.evaluate(claim, checks)
    assert evaluated is claim
    assert len(claim.checks) == 2
    assert claim.verdict is Verdict.PASS


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------


def test_ledger_publishable_excludes_blocked_but_blocked_retains_them():
    ledger = ClaimLedger()
    passing = _claim([_check(Verdict.PASS, "a")])
    passing.claim_id = "pass"
    warning = _claim([_check(Verdict.WARN, "a")])
    warning.claim_id = "warn"
    blocked = _claim([_check(Verdict.BLOCK, "a")])
    blocked.claim_id = "block"

    for c in (passing, warning, blocked):
        ledger.submit(c)

    publishable_ids = {c.claim_id for c in ledger.publishable()}
    assert publishable_ids == {"pass", "warn"}

    blocked_ids = {c.claim_id for c in ledger.blocked()}
    assert blocked_ids == {"block"}

    # Nothing is dropped: the ledger is the audit trail.
    assert len(ledger.claims) == 3
    assert {c.claim_id for c in ledger.claims} == {"pass", "warn", "block"}


def test_ledger_summary_counts_and_block_rate():
    ledger = ClaimLedger()
    for _ in range(3):
        ledger.submit(_claim([_check(Verdict.PASS, "a")]))
    ledger.submit(_claim([_check(Verdict.BLOCK, "a")]))
    summary = ledger.summary()
    assert summary["n_claims"] == 4
    assert summary["by_verdict"]["pass"] == 3
    assert summary["by_verdict"]["block"] == 1
    assert abs(summary["block_rate"] - 0.25) < 1e-9


def test_empty_ledger_summary_is_safe():
    summary = ClaimLedger().summary()
    assert summary["n_claims"] == 0
    assert summary["block_rate"] == 0.0


def test_ledger_to_dict_renders_blocked_claims_with_reasons():
    ledger = ClaimLedger()
    ledger.submit(_claim([_check(Verdict.BLOCK, "reliability")]))
    d = ledger.to_dict()
    assert d["summary"]["by_verdict"]["block"] == 1
    assert d["claims"][0]["verdict"] == "block"
    assert d["claims"][0]["blocking_reasons"] == ["reliability says block"]


def test_check_to_dict_nulls_out_nan_observations():
    check = Check("x", Verdict.BLOCK, float("nan"), 0.5, "msg")
    assert check.to_dict()["observed"] is None
    assert math.isnan(check.observed)


# --------------------------------------------------------------------------
# annotator pool escalation
# --------------------------------------------------------------------------


def _pool_check(fraction, policy=None):
    gate = _gate(policy=policy)
    checks = gate.check_pool_health(fraction, False, 0.05, 0.85)
    return next(c for c in checks if c.name == "annotator_pool")


def test_annotator_pool_escalates_from_pass_through_warn_to_block():
    """A check that can only ever WARN is not a control.

    Budget 0.34, blocking escalation at 2x = 0.68. Below budget passes, between
    budget and 2x warns, above 2x blocks: at that point the majority of the
    instrument is flagged and nothing built on it is defensible.
    """
    budget = DEFAULT_POLICY.max_flagged_annotator_fraction
    block_at = budget * DEFAULT_POLICY.flagged_annotator_block_multiple

    assert _pool_check(budget - 0.01).verdict is Verdict.PASS
    assert _pool_check(budget).verdict is Verdict.PASS
    assert _pool_check(budget + 0.01).verdict is Verdict.WARN
    assert _pool_check(block_at).verdict is Verdict.WARN
    assert _pool_check(block_at + 0.01).verdict is Verdict.BLOCK
    assert _pool_check(1.0).verdict is Verdict.BLOCK


def test_annotator_pool_block_states_the_escalation_rule_and_a_remedy():
    check = _pool_check(0.90)
    assert "twice" in check.message
    assert "68%" in check.message
    assert check.remedy


def test_annotator_pool_escalation_multiple_is_policy_data():
    strict = GatePolicy(max_flagged_annotator_fraction=0.20,
                        flagged_annotator_block_multiple=1.5)
    assert _pool_check(0.29, policy=strict).verdict is Verdict.WARN
    assert _pool_check(0.31, policy=strict).verdict is Verdict.BLOCK


# --------------------------------------------------------------------------
# alpha uncertainty is surfaced without moving the verdict
# --------------------------------------------------------------------------


def test_reliability_ci_straddling_a_threshold_is_disclosed():
    """The interval does not change the verdict; it changes what is said.

    At n=36-48 units the bootstrap interval for alpha is roughly +/-0.15, so a
    point estimate sitting 0.02 above the blocking floor is not evidence that
    the dimension clears it. The classification stays keyed on the point
    estimate -- letting a noisier estimate buy a softer verdict would be worse --
    but the message has to say the side of the line is not established.
    """
    gate = _gate()
    floor = DEFAULT_POLICY.alpha_block_below

    straddling = gate.check_reliability(
        floor + 0.02, "d1", ci={"lo": floor - 0.14, "hi": floor + 0.18}
    )
    assert straddling.verdict is Verdict.WARN  # unchanged band
    assert "not" in straddling.message.lower()
    assert "does not exclude" in straddling.message
    assert "UNCERTAINTY" in straddling.message

    excluding = gate.check_reliability(
        floor + 0.02, "d1", ci={"lo": floor + 0.01, "hi": floor + 0.05}
    )
    assert excluding.verdict is Verdict.WARN
    assert "UNCERTAINTY" not in excluding.message


def test_reliability_verdict_is_identical_with_and_without_an_interval():
    gate = _gate()
    for alpha in (0.20, 0.45, 0.55, 0.70, 0.85):
        wide = {"lo": alpha - 0.30, "hi": alpha + 0.30}
        assert (gate.check_reliability(alpha).verdict
                is gate.check_reliability(alpha, ci=wide).verdict)


def test_reliability_ci_of_none_or_nan_is_tolerated():
    gate = _gate()
    assert gate.check_reliability(0.55, ci=None).verdict is Verdict.WARN
    nan_ci = {"lo": float("nan"), "hi": float("nan")}
    assert gate.check_reliability(0.55, ci=nan_ci).verdict is Verdict.WARN
    assert "UNCERTAINTY" not in gate.check_reliability(0.55, ci=nan_ci).message
