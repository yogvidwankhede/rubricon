"""Claim checks that propagate gold-label noise into a comparison (gate v2).

Why this module exists
----------------------
``signal.SignalGate`` blocks a comparison when Krippendorff's alpha is below a
fixed floor. A known-truth simulation (hatexplain-label-audit, ``gate_sim.py``)
showed that floor costs power without buying fewer false claims: at a matched
false-claim rate, a plain stricter significance test publishes more real gaps.
The reason is structural. For a binary label, noise in the gold label does not
create a spurious gap between two systems; it *shrinks* the real one.

The identity behind that
------------------------
Let a system be correct against the truth with indicator ``C`` and let the gold
label be wrong with probability ``eta_g``, independently of the system. The
system agrees with gold exactly when (C == gold correct), so two systems' observed
correctness differs exactly when their true correctness differs. Hence:

* the item-level disagreement rate of two systems is unchanged by label noise;
* the expected observed accuracy gap is ``(1 - 2 * eta_g) * true gap``.

``eta_g`` for a majority of ``k`` raters, each wrong independently with rate
``eta``, is a binomial tail. ``eta`` is estimated from how often two raters
disagree on an item: ``P(disagree) = 2 * eta * (1 - eta)`` for symmetric noise,
whatever the prevalence.

What the checks do
------------------
* ``check_direction`` -- the only BLOCKing check: the paired z statistic of the
  observed gap must exceed ``z_star``. This is a significance test with a
  stricter-than-conventional threshold, and it is labelled as that.
* ``attenuation_report`` -- never blocks. Converts the observed gap and the
  observed-scale MDE to the true-label scale so a reader sees what the labels can
  resolve. It WARNs when the requested effect is below the true-scale MDE.
* ``check_contested_consistency`` -- WARN/BLOCK when the gap has opposite signs
  on items the raters agreed on and items they split on, and the difference is
  itself significant. That pattern means the ranking depends on how contested
  items are resolved.

Assumptions (stated, because they are where this can be wrong): binary labels,
symmetric rater noise, rater errors independent of each other and of the
systems' errors. The simulation reports how far results move when noise is
concentrated on hard items.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Sequence

from ..core.schema import Verdict
from .signal import Check

_N = NormalDist()


def z_quantile(p: float) -> float:
    return _N.inv_cdf(p)


# --------------------------------------------------------------------------
# noise model
# --------------------------------------------------------------------------


def eta_from_disagreement(pairwise_disagreement: float) -> float:
    """Single-rater error rate from the pairwise disagreement rate (symmetric noise).

    Solves ``2 * eta * (1 - eta) = d`` for the root below 0.5. ``d >= 0.5`` means
    raters agree no more than chance would allow under this model; returns 0.5.
    """
    d = pairwise_disagreement
    if d < 0 or d > 1:
        raise ValueError("disagreement must be in [0, 1]")
    if d >= 0.5:
        return 0.5
    return (1.0 - math.sqrt(1.0 - 2.0 * d)) / 2.0


def eta_majority(eta: float, k: int) -> float:
    """P(the majority of k raters is wrong); even-k ties are broken by a fair coin."""
    if k < 1:
        raise ValueError("k >= 1")
    wrong = 0.0
    for j in range(k + 1):
        p = math.comb(k, j) * eta**j * (1 - eta) ** (k - j)
        if 2 * j > k:
            wrong += p
        elif 2 * j == k:
            wrong += 0.5 * p
    return wrong


def attenuation(eta_gold: float) -> float:
    """Factor by which gold noise shrinks an expected accuracy gap."""
    return 1.0 - 2.0 * eta_gold


# --------------------------------------------------------------------------
# paired comparison summary
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PairedGap:
    n: int
    gap: float          # mean of per-item (A correct) - (B correct), against gold
    sd: float           # SD of the per-item differences
    disagreement: float  # fraction of items where exactly one system is correct

    @property
    def se(self) -> float:
        return self.sd / math.sqrt(self.n)

    @property
    def z(self) -> float:
        return self.gap / self.se if self.se > 0 else math.copysign(math.inf, self.gap)

    @classmethod
    def from_correctness(cls, a: Sequence[int], b: Sequence[int]) -> "PairedGap":
        if len(a) != len(b) or len(a) < 2:
            raise ValueError("need two equal-length sequences with n >= 2")
        d = [x - y for x, y in zip(a, b)]
        n = len(d)
        m = sum(d) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
        return cls(n, m, sd, sum(1 for x in d if x != 0) / n)


def mde_observed(n: int, sd: float, alpha_level: float = 0.05, power: float = 0.80,
                 z_star: float | None = None) -> float:
    """Observed-scale paired MDE; ``z_star`` replaces the two-sided critical value."""
    za = z_star if z_star is not None else z_quantile(1 - alpha_level / 2)
    return (za + z_quantile(power)) * sd / math.sqrt(n)


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def check_direction(pg: PairedGap, z_star: float = 2.58) -> Check:
    ok = pg.gap > 0 and pg.z > z_star
    return Check(
        "direction", Verdict.PASS if ok else Verdict.BLOCK, round(pg.z, 3), z_star,
        f"Paired z = {pg.z:.2f} for an observed gap of {pg.gap:+.4f} (n={pg.n}); "
        + ("exceeds" if ok else "does NOT exceed") + f" the pre-set z* = {z_star:.2f}.",
        "" if ok else "State the comparison as unresolved at this n; do not claim a direction.",
    )


def attenuation_report(pg: PairedGap, rater_disagreement: float, k_raters: int,
                       requested_effect: float | None = None, z_star: float = 2.58,
                       power: float = 0.80) -> Check:
    eta = eta_from_disagreement(rater_disagreement)
    eta_g = eta_majority(eta, k_raters)
    att = attenuation(eta_g)
    mde_o = mde_observed(pg.n, pg.sd, z_star=z_star, power=power)
    mde_t = mde_o / att if att > 0 else math.inf
    gap_t = pg.gap / att if att > 0 else math.nan
    msg = (f"Rater disagreement {rater_disagreement:.3f} implies single-rater error "
           f"{eta:.3f} and gold error {eta_g:.3f} for a {k_raters}-rater majority, so "
           f"observed gaps are shrunk by a factor {att:.3f}. Observed gap {pg.gap:+.4f} "
           f"is {gap_t:+.4f} on the true-label scale; the smallest true gap this design "
           f"resolves at {power:.0%} power is {mde_t:.4f}.")
    verdict = Verdict.PASS
    remedy = ""
    if requested_effect is not None and requested_effect < mde_t:
        verdict = Verdict.WARN
        remedy = (f"A true gap of {requested_effect:g} is below the resolvable "
                  f"{mde_t:.4f}; enlarge n or improve gold labels before powering a claim about it.")
    return Check("attenuation", verdict, round(att, 4), None, msg, remedy)


def check_contested_consistency(diff_unanimous: Sequence[float], diff_split: Sequence[float],
                                z_block: float = 2.58, z_warn: float = 1.96) -> Check:
    """Does the gap reverse between items raters agreed on and items they split on?"""
    def mean_se(xs):
        n = len(xs)
        if n < 2:
            return math.nan, math.nan
        m = sum(xs) / n
        v = sum((x - m) ** 2 for x in xs) / (n - 1)
        return m, v / n

    gu, vu = mean_se(diff_unanimous)
    gs, vs = mean_se(diff_split)
    if math.isnan(gu) or math.isnan(gs) or vu + vs == 0:
        return Check("contested_consistency", Verdict.WARN, None, z_block,
                     "Too few unanimous or split items to compare.", "")
    z = (gu - gs) / math.sqrt(vu + vs)
    opposite = gu * gs < 0
    if opposite and abs(z) > z_block:
        v, tail = Verdict.BLOCK, "reverses sign and the difference is significant"
    elif abs(z) > z_warn:
        v, tail = Verdict.WARN, "differs significantly between the two item types"
    else:
        v, tail = Verdict.PASS, "is consistent across item types"
    return Check("contested_consistency", v, round(z, 3), z_block,
                 f"Gap on unanimous items {gu:+.4f} vs split items {gs:+.4f}: the gap {tail} "
                 f"(z = {z:.2f}).",
                 "" if v is Verdict.PASS else
                 "Report the gap separately by item type; the ranking depends on how contested "
                 "items are resolved.")


__all__ = [
    "PairedGap", "attenuation", "attenuation_report", "check_contested_consistency",
    "check_direction", "eta_from_disagreement", "eta_majority", "mde_observed", "z_quantile",
]
