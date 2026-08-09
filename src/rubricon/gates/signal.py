"""The signal gate.

This module exists because of one recurring organisational failure: evaluation
numbers escape into decks, roadmaps, and customer conversations without anyone
having checked whether the measurement could support the sentence built on top
of it. By the time the claim is public, questioning it is a political act rather
than a technical one.

The gate makes that check mechanical and pre-commitment-based. Thresholds are
declared in a policy object *before* results exist. The gate then evaluates a
claim against the evidence and returns PASS, WARN, or BLOCK. A BLOCK is not
advisory: ``ClaimLedger.publishable()`` excludes the claim from the set that may
be stated as a finding, and the report renders the block, and its reason, in
place of the number. Blocked claims are never silently dropped -- see the
``ClaimLedger`` docstring.

Design notes
------------
* **Checks are independent and all run.** We do not short-circuit on the first
  failure, because "this claim has four problems" is more useful to the person
  fixing it than "this claim has one problem".
* **A blocked claim is still recorded.** Suppressing the record would hide the
  fact that someone wanted to make the claim. The ledger is the audit trail.
* **Thresholds are arguable, and that is the point.** They are data, not code,
  so a reviewer can disagree with 0.67 and see exactly what changes. The
  defaults follow Krippendorff's guidance (alpha >= 0.800 for firm conclusions,
  >= 0.667 for tentative ones) rather than the more permissive Landis-Koch
  bands, because eval numbers get quoted as if they were firm.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from ..core.schema import Verdict


# --------------------------------------------------------------------------
# policy
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GatePolicy:
    """Pre-registered thresholds. Declared before results are computed."""

    # Reliability
    alpha_block_below: float = 0.50
    alpha_warn_below: float = 0.667
    alpha_firm_at: float = 0.800

    # Precision
    max_ci_half_width: float = 0.075          # on a 0-1 composite
    require_effect_exceeds_mde: bool = True
    mde_safety_margin: float = 1.0            # effect must exceed MDE * margin

    # Coverage
    min_n_per_cell: int = 5
    max_empty_cell_fraction: float = 0.20
    min_replication: int = 2

    # Pool health.
    #
    # ``annotator_pool`` escalates in two clearly-stated steps rather than being
    # WARN-only:
    #   flagged <= budget                      -> PASS
    #   budget < flagged <= budget * escalation-> WARN
    #   flagged  > budget * escalation         -> BLOCK
    # A check that can only ever WARN is not a control. At 2x the budget the
    # majority of the instrument is flagged, and every number produced by it
    # rests on annotators the pipeline's own quality machinery has rejected;
    # "note it and publish anyway" is not a defensible response to that.
    max_flagged_annotator_fraction: float = 0.34
    flagged_annotator_block_multiple: float = 2.0
    block_on_drift: bool = True
    max_rubric_gap_rate: float = 0.15
    min_gold_accuracy: float = 0.70

    # Multiplicity
    correct_for_multiplicity: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_POLICY = GatePolicy()

# A deliberately looser policy for exploratory work. Its existence is the point:
# it makes "we relaxed the bar for this track" an explicit, reviewable act
# rather than something that happens by omission.
EXPLORATORY_POLICY = GatePolicy(
    alpha_block_below=0.30,
    alpha_warn_below=0.50,
    max_ci_half_width=0.15,
    require_effect_exceeds_mde=False,
    min_n_per_cell=3,
    block_on_drift=False,
)


def policy_for_depth(depth: str) -> GatePolicy:
    return EXPLORATORY_POLICY if depth == "exploratory" else DEFAULT_POLICY


# --------------------------------------------------------------------------
# checks and claims
# --------------------------------------------------------------------------


def _straddles(ci: Any, threshold: float) -> bool:
    """True when a bootstrap interval fails to exclude ``threshold``."""
    if not ci:
        return False
    lo, hi = ci.get("lo"), ci.get("hi")
    if lo is None or hi is None:
        return False
    if isinstance(lo, float) and math.isnan(lo):
        return False
    if isinstance(hi, float) and math.isnan(hi):
        return False
    return lo <= threshold <= hi


@dataclass
class Check:
    name: str
    verdict: Verdict
    observed: Any
    threshold: Any
    message: str
    remedy: str = ""

    def to_dict(self) -> dict:
        obs = self.observed
        if isinstance(obs, float):
            obs = None if math.isnan(obs) else round(obs, 4)
        return {
            "name": self.name,
            "verdict": self.verdict.value,
            "observed": obs,
            "threshold": self.threshold,
            "message": self.message,
            "remedy": self.remedy,
        }


@dataclass
class Claim:
    """A sentence someone wants to publish, plus the evidence behind it."""

    claim_id: str
    track: str
    text: str
    kind: str  # descriptive | measurement | ranking | release_gate
    evidence: dict = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)

    @property
    def verdict(self) -> Verdict:
        if any(c.verdict is Verdict.BLOCK for c in self.checks):
            return Verdict.BLOCK
        if any(c.verdict is Verdict.WARN for c in self.checks):
            return Verdict.WARN
        return Verdict.PASS

    @property
    def blocking_reasons(self) -> list[str]:
        return [c.message for c in self.checks if c.verdict is Verdict.BLOCK]

    @property
    def warnings(self) -> list[str]:
        return [c.message for c in self.checks if c.verdict is Verdict.WARN]

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "track": self.track,
            "text": self.text,
            "kind": self.kind,
            "verdict": self.verdict.value,
            "checks": [c.to_dict() for c in self.checks],
            "blocking_reasons": self.blocking_reasons,
            "warnings": self.warnings,
            "evidence": self.evidence,
        }


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------


class SignalGate:
    def __init__(self, policy: GatePolicy | None = None, depth: str = "pilot") -> None:
        self.policy = policy or policy_for_depth(depth)
        self.depth = depth

    # -- individual checks -------------------------------------------------

    def check_depth_contract(self, kind: str) -> Check:
        from ..tracks import DEPTH_CONTRACT, DEPTH_ORDER

        needed = {"descriptive": 0, "measurement": 1, "ranking": 2, "release_gate": 2}.get(kind, 2)
        have = DEPTH_ORDER.get(self.depth, 0)
        ok = have >= needed
        return Check(
            "depth_contract",
            Verdict.PASS if ok else Verdict.BLOCK,
            self.depth,
            kind,
            f"Track depth '{self.depth}' "
            + ("permits" if ok else "does NOT permit")
            + f" a '{kind}' claim.",
            "" if ok else (
                f"Either reframe the claim as descriptive, or promote the track. "
                f"Contract for '{self.depth}': {DEPTH_CONTRACT.get(self.depth, '')}"
            ),
        )

    def check_reliability(self, alpha: float, dimension: str = "",
                          ci: dict | None = None) -> Check:
        """Classify alpha against the pre-registered bands.

        ``ci`` is the cluster-bootstrap interval for alpha. It does NOT move the
        verdict -- the pre-registered thresholds apply to the point estimate, and
        making the verdict depend on interval width would let a noisier estimate
        buy itself a softer classification. What it does is state, in the check
        message, when the interval fails to exclude the threshold the point
        estimate just crossed. At n=36-48 units the interval is roughly +/-0.15,
        so "alpha=0.52, above the 0.50 floor" and "alpha=0.48, below it" are
        routinely the same measurement, and a reader is entitled to know that the
        side of the line is not established.
        """
        p = self.policy
        label = f"reliability{':' + dimension if dimension else ''}"
        if alpha is None or (isinstance(alpha, float) and math.isnan(alpha)):
            return Check(label, Verdict.BLOCK, alpha, p.alpha_warn_below,
                         f"Agreement is undefined for {dimension or 'this measure'} "
                         "(degenerate label distribution or insufficient replication).",
                         "Collect replicated annotations, or oversample the rare category "
                         "so more than one level is actually used.")

        def caveat(threshold: float) -> str:
            if not _straddles(ci, threshold):
                return ""
            return (
                f" UNCERTAINTY: the 95% bootstrap interval for alpha "
                f"[{ci['lo']:.3f}, {ci['hi']:.3f}] does not exclude {threshold:.3f}, "
                "so which side of that threshold this dimension falls on is NOT "
                "established by these data; the classification is a point estimate, "
                "not a finding."
            )

        if alpha < p.alpha_block_below:
            return Check(label, Verdict.BLOCK, alpha, p.alpha_block_below,
                         f"alpha={alpha:.3f} is below the blocking floor of "
                         f"{p.alpha_block_below:.3f}. Annotators are not measuring the same "
                         f"construct.{caveat(p.alpha_block_below)}",
                         "Do not report this number. Revise the rubric definition or "
                         "split the dimension; more data will not fix a definition problem.")
        if alpha < p.alpha_warn_below:
            return Check(label, Verdict.WARN, alpha, p.alpha_warn_below,
                         f"alpha={alpha:.3f} is below Krippendorff's tentative-conclusion "
                         f"threshold of {p.alpha_warn_below:.3f}."
                         f"{caveat(p.alpha_warn_below) or caveat(p.alpha_block_below)}",
                         "Report with the interval and an explicit reliability caveat; "
                         "do not use for ranking.")
        if alpha < p.alpha_firm_at:
            return Check(label, Verdict.PASS, alpha, p.alpha_firm_at,
                         f"alpha={alpha:.3f} supports tentative conclusions "
                         f"(firm conclusions want >= {p.alpha_firm_at:.3f})."
                         f"{caveat(p.alpha_warn_below) or caveat(p.alpha_firm_at)}")
        return Check(label, Verdict.PASS, alpha, p.alpha_firm_at,
                     f"alpha={alpha:.3f} supports firm conclusions.{caveat(p.alpha_firm_at)}")

    def check_precision(self, half_width: float) -> Check:
        p = self.policy
        if half_width is None or math.isnan(half_width):
            return Check("precision", Verdict.BLOCK, half_width, p.max_ci_half_width,
                         "No confidence interval was computed for this estimate.",
                         "Run the cluster bootstrap before publishing a point estimate.")
        ok = half_width <= p.max_ci_half_width
        return Check(
            "precision", Verdict.PASS if ok else Verdict.WARN, half_width, p.max_ci_half_width,
            f"95% CI half-width {half_width:.3f} "
            + ("is within" if ok else "EXCEEDS")
            + f" the {p.max_ci_half_width:.3f} budget.",
            "" if ok else "Increase n or reduce measurement noise before quoting a point estimate.",
        )

    def check_effect_vs_mde(self, effect: float, mde: float) -> Check:
        p = self.policy
        if not p.require_effect_exceeds_mde:
            return Check("effect_vs_mde", Verdict.PASS, effect, mde,
                         "MDE check waived by policy for this depth tier.")
        ok = abs(effect) >= mde * p.mde_safety_margin
        return Check(
            "effect_vs_mde", Verdict.PASS if ok else Verdict.BLOCK, abs(effect), mde,
            f"Observed effect {abs(effect):.4f} "
            + ("exceeds" if ok else "is BELOW")
            + f" the minimum detectable effect {mde:.4f}.",
            "" if ok else (
                "This difference is inside the noise floor of the design. Reporting it "
                "as a real difference is not supportable. Either power the study for "
                f"this effect size or report 'no detectable difference (MDE={mde:.3f})'."
            ),
        )

    def check_interval_excludes_zero(self, lo: float, hi: float) -> Check:
        if lo is None or hi is None or math.isnan(lo) or math.isnan(hi):
            return Check("interval_excludes_zero", Verdict.BLOCK, None, 0.0,
                         "Interval unavailable for the difference.",
                         "Bootstrap the paired difference before claiming a direction.")
        excludes = not (lo <= 0.0 <= hi)
        return Check(
            "interval_excludes_zero", Verdict.PASS if excludes else Verdict.BLOCK,
            (round(lo, 4), round(hi, 4)), 0.0,
            f"95% CI [{lo:.4f}, {hi:.4f}] "
            + ("excludes" if excludes else "CONTAINS")
            + " zero.",
            "" if excludes else "Direction of the difference is not established. State it as a tie.",
        )

    def check_coverage(self, cov: dict) -> Check:
        """Coverage check on MARGINAL strata coverage, not full-factorial cells.

        Full-factorial emptiness is the wrong denominator: four factors with four
        levels each is 256 cells, so any corpus small enough to annotate by hand
        is 90%+ empty by construction. Gating on it would block every honest
        design and teach people to declare fewer factors, which is worse.

        What actually threatens an aggregate is a *level* with no data or too
        little: that level silently drops out of the average with no note.
        """
        p = self.policy
        gap = cov.get("marginal_gap_fraction", 1.0)
        absent = cov.get("absent_levels", [])
        thin = cov.get("thin_levels", [])
        balance = cov.get("worst_balance_ratio", 0.0)

        if absent:
            return Check("coverage", Verdict.BLOCK, len(absent), 0,
                         f"{len(absent)} declared strata level(s) have no data: "
                         + ", ".join(absent[:6]),
                         "The design claims these levels; the aggregate silently excludes them. "
                         "Either collect them or remove them from the declared design.")
        if gap > p.max_empty_cell_fraction:
            return Check("coverage", Verdict.WARN, round(gap, 3), p.max_empty_cell_fraction,
                         f"{gap:.0%} of declared strata levels fall below n={p.min_n_per_cell} "
                         f"(budget {p.max_empty_cell_fraction:.0%}). Thin: "
                         + ", ".join(thin[:5]),
                         "Do not report per-level breakdowns for the thin levels; "
                         "aggregate them or oversample.")
        if balance < 0.25:
            return Check("coverage", Verdict.WARN, balance, 0.25,
                         f"Worst-factor balance ratio {balance:.2f}: one level is sampled "
                         "at least four times more heavily than another in the same factor.",
                         "Unweighted aggregates over an unbalanced design are dominated by the "
                         "over-sampled level. Report weighted means or rebalance.")
        return Check("coverage", Verdict.PASS, round(gap, 3), p.max_empty_cell_fraction,
                     f"All {cov.get('total_declared_levels', 0)} declared strata levels are "
                     f"populated at n>={p.min_n_per_cell}; worst balance ratio {balance:.2f}.")

    def check_replication(self, mean_replication: float) -> Check:
        p = self.policy
        ok = mean_replication >= p.min_replication
        return Check("replication", Verdict.PASS if ok else Verdict.BLOCK,
                     round(mean_replication, 2), p.min_replication,
                     f"Mean annotations per response {mean_replication:.2f} "
                     + ("meets" if ok else "is BELOW")
                     + f" the minimum of {p.min_replication}.",
                     "" if ok else "Single-annotated data cannot support a reliability estimate, "
                                   "so no claim resting on it can be reliability-checked.")

    def check_pool_health(self, flagged_fraction: float, drift_detected: bool,
                          rubric_gap_rate: float, min_gold_accuracy: float | None) -> list[Check]:
        p = self.policy
        checks = []

        budget = p.max_flagged_annotator_fraction
        block_at = budget * p.flagged_annotator_block_multiple
        if flagged_fraction <= budget:
            verdict, tail, remedy = Verdict.PASS, "within budget.", ""
        elif flagged_fraction <= block_at:
            verdict = Verdict.WARN
            tail = (f"OVER the {budget:.0%} budget but at or below the {block_at:.0%} "
                    "blocking escalation.")
            remedy = "Re-anchor or replace flagged annotators and re-annotate a bridge sample."
        else:
            verdict = Verdict.BLOCK
            tail = (f"EXCEEDS {block_at:.0%}, twice the {budget:.0%} budget: most of the "
                    "instrument is flagged, so no number it produced is defensible.")
            remedy = (
                "Remediate the pool before reporting anything from it: replace or re-anchor "
                "the flagged annotators, re-annotate a bridge sample, and re-derive every "
                "statistic on it. Nothing on this track can be published in the meantime."
            )
        checks.append(Check(
            "annotator_pool", verdict,
            round(flagged_fraction, 3), budget,
            f"{flagged_fraction:.0%} of annotators carry quality flags "
            f"(budget {budget:.0%}, block above {block_at:.0%}) -- {tail}",
            remedy,
        ))

        if drift_detected:
            checks.append(Check(
                "drift", Verdict.BLOCK if p.block_on_drift else Verdict.WARN,
                True, False,
                "Annotator drift detected across batches at constant item mix.",
                "Longitudinal comparisons across these batches are not defensible. "
                "Re-anchor the pool and re-annotate a bridge sample spanning the batches.",
            ))
        else:
            checks.append(Check("drift", Verdict.PASS, False, False, "No batch-level drift detected."))

        gap_ok = rubric_gap_rate <= p.max_rubric_gap_rate
        checks.append(Check(
            "rubric_specification", Verdict.PASS if gap_ok else Verdict.BLOCK,
            round(rubric_gap_rate, 3), p.max_rubric_gap_rate,
            f"{rubric_gap_rate:.0%} of adjudications were attributed to rubric ambiguity "
            f"rather than annotator error (budget {p.max_rubric_gap_rate:.0%}).",
            "" if gap_ok else "The instrument is underspecified. Revise the rubric and re-collect; "
                              "annotator retraining against an ambiguous rubric does not converge.",
        ))

        if min_gold_accuracy is not None and not math.isnan(min_gold_accuracy):
            gok = min_gold_accuracy >= p.min_gold_accuracy
            checks.append(Check(
                "gold_calibration", Verdict.PASS if gok else Verdict.WARN,
                round(min_gold_accuracy, 3), p.min_gold_accuracy,
                f"Worst annotator gold accuracy {min_gold_accuracy:.0%} "
                + ("meets" if gok else "is below")
                + f" the {p.min_gold_accuracy:.0%} floor.",
                "" if gok else "Retrain or remove the annotator, then re-annotate their assignments.",
            ))
        return checks

    # -- composition -------------------------------------------------------

    def evaluate(self, claim: Claim, checks: Iterable[Check]) -> Claim:
        claim.checks = list(checks)
        return claim


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------


class ClaimLedger:
    """Append-only record of every claim submitted to the gate.

    ``publishable()`` is what the report generator consumes. Blocked claims stay
    in the ledger and are rendered as blocks, so the reader can see what was
    withheld and why -- an eval report that silently omits its failures is
    indistinguishable from one that had none.
    """

    def __init__(self) -> None:
        self._claims: list[Claim] = []

    def submit(self, claim: Claim) -> Claim:
        self._claims.append(claim)
        return claim

    @property
    def claims(self) -> list[Claim]:
        return list(self._claims)

    def publishable(self) -> list[Claim]:
        return [c for c in self._claims if c.verdict is not Verdict.BLOCK]

    def blocked(self) -> list[Claim]:
        return [c for c in self._claims if c.verdict is Verdict.BLOCK]

    def summary(self) -> dict:
        by = {v.value: 0 for v in Verdict}
        for c in self._claims:
            by[c.verdict.value] += 1
        return {
            "n_claims": len(self._claims),
            "by_verdict": by,
            "block_rate": round(by["block"] / len(self._claims), 3) if self._claims else 0.0,
        }

    def to_dict(self) -> dict:
        return {"summary": self.summary(), "claims": [c.to_dict() for c in self._claims]}


__all__ = [
    "Check",
    "Claim",
    "ClaimLedger",
    "DEFAULT_POLICY",
    "EXPLORATORY_POLICY",
    "GatePolicy",
    "SignalGate",
    "policy_for_depth",
]
