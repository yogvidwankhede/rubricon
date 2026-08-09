"""Uncertainty, power, and the reliability tax.

The central idea of this module
-------------------------------
An evaluation's headline number is worthless without knowing what difference it
could have detected. Most eval reports quote a point estimate and stop, which
lets a 1.8-point "improvement" masquerade as progress when the measurement floor
was 6 points.

Two corrections are applied here that are routinely skipped:

**Cluster bootstrap.** Multiple annotations of the same response are not
independent observations. Resampling annotations instead of *items* shrinks the
interval by roughly sqrt(replication) and produces confidently wrong error bars.
We resample items (clusters) and carry their annotations along.

**The reliability tax, applied exactly once.** Measurement error attenuates
observed effects. With reliability rho, the effective sample size for detecting
a *true* difference is approximately ``n_eff = n * rho`` (Spearman 1904
attenuation; see also Cohen 1988 §11): a 400-item eval at rho=0.55 has the
resolving power of a 220-item eval at rho=1.0. Reporting n=400 without noting
that overstates precision by ~35%.

The trap on the other side is charging for it twice. That identity holds when
the effect is in TRUE-score units and the SD is the observed one. If the SD you
feed in is already the observed spread -- which contains the measurement error
-- then shrinking n to n_eff as well inflates the MDE by 1/sqrt(rho) for no
reason. ``minimum_detectable_effect`` therefore computes the MDE at plain n
against the observed SD, and reports ``n_effective`` and ``mde_true_scale``
alongside as separate, non-compounded figures. Its docstring states the
convention in full.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Sequence

# Standard normal quantiles for the tails we actually use. Avoids a hard scipy
# dependency in the statistical core (scipy is used only for optional extras).
_Z = {0.80: 0.8416, 0.90: 1.2816, 0.95: 1.6449, 0.975: 1.9600, 0.99: 2.3263, 0.995: 2.5758}


def z(p: float) -> float:
    if p in _Z:
        return _Z[p]
    # Acklam's inverse-normal approximation; |error| < 1.15e-9.
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# --------------------------------------------------------------------------
# bootstrap
# --------------------------------------------------------------------------


@dataclass
class Interval:
    point: float
    lo: float
    hi: float
    level: float = 0.95
    method: str = "cluster_bootstrap_percentile"
    n_clusters: int = 0
    n_boot: int = 0

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def half_width(self) -> float:
        return self.width / 2.0

    def excludes(self, value: float) -> bool:
        return value < self.lo or value > self.hi

    def to_dict(self) -> dict:
        return {
            "point": round(self.point, 4),
            "lo": round(self.lo, 4),
            "hi": round(self.hi, 4),
            "width": round(self.width, 4),
            "level": self.level,
            "method": self.method,
            "n_clusters": self.n_clusters,
            "n_boot": self.n_boot,
        }


def cluster_bootstrap(
    clusters: Sequence[Sequence[float]],
    statistic: Callable[[list[float]], float] = None,
    n_boot: int = 2000,
    level: float = 0.95,
    seed: int = 0,
) -> Interval:
    """Percentile bootstrap resampling whole clusters (items), not observations.

    ``clusters`` is a list of lists: one inner list per item, containing that
    item's observations (e.g. one score per annotator).
    """
    stat = statistic or (lambda xs: sum(xs) / len(xs) if xs else float("nan"))
    clusters = [list(c) for c in clusters if len(c) > 0]
    if not clusters:
        return Interval(float("nan"), float("nan"), float("nan"), level, n_clusters=0, n_boot=0)

    flat = [x for c in clusters for x in c]
    point = stat(flat)
    if len(clusters) == 1:
        return Interval(point, float("nan"), float("nan"), level, n_clusters=1, n_boot=0)

    rng = random.Random(seed)
    k = len(clusters)
    draws = []
    for _ in range(n_boot):
        sample = [x for _ in range(k) for x in clusters[rng.randrange(k)]]
        if sample:
            draws.append(stat(sample))
    draws.sort()
    a = (1 - level) / 2
    lo = draws[max(0, int(a * len(draws)) - 1)]
    hi = draws[min(len(draws) - 1, int((1 - a) * len(draws)))]
    return Interval(point, lo, hi, level, n_clusters=k, n_boot=len(draws))


def bootstrap_statistic(
    units: Sequence, fn: Callable[[Sequence], float], n_boot: int = 1000,
    level: float = 0.95, seed: int = 0,
) -> Interval:
    """Generic cluster bootstrap over arbitrary units (e.g. for alpha itself)."""
    units = list(units)
    if len(units) < 2:
        return Interval(float("nan"), float("nan"), float("nan"), level)
    rng = random.Random(seed)
    point = fn(units)
    draws = []
    for _ in range(n_boot):
        sample = [units[rng.randrange(len(units))] for _ in range(len(units))]
        try:
            v = fn(sample)
        except Exception:
            continue
        if v is not None and not math.isnan(v):
            draws.append(v)
    if len(draws) < 20:
        return Interval(point, float("nan"), float("nan"), level, n_clusters=len(units), n_boot=len(draws))
    draws.sort()
    a = (1 - level) / 2
    return Interval(
        point,
        draws[max(0, int(a * len(draws)) - 1)],
        draws[min(len(draws) - 1, int((1 - a) * len(draws)))],
        level,
        "cluster_bootstrap_percentile",
        len(units),
        len(draws),
    )


# --------------------------------------------------------------------------
# power / MDE
# --------------------------------------------------------------------------


@dataclass
class PowerResult:
    n: int
    n_effective: float
    reliability: float
    sd: float
    mde_absolute: float
    mde_observed_scale: float
    mde_true_scale: float
    mde_relative: float | None
    alpha_level: float
    power: float
    paired: bool
    n_required_for_target: int | None = None
    target_effect: float | None = None
    convention: str = "observed_scale"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "n_effective": round(self.n_effective, 1),
            "reliability": round(self.reliability, 4),
            "sd": round(self.sd, 4),
            "mde_absolute": round(self.mde_absolute, 4),
            "mde_observed_scale": round(self.mde_observed_scale, 4),
            "mde_true_scale": round(self.mde_true_scale, 4),
            "mde_relative": None if self.mde_relative is None else round(self.mde_relative, 4),
            "alpha_level": self.alpha_level,
            "power": self.power,
            "paired": self.paired,
            "n_required_for_target": self.n_required_for_target,
            "target_effect": self.target_effect,
            "convention": self.convention,
            "notes": self.notes,
        }


def minimum_detectable_effect(
    n: int,
    sd: float,
    reliability: float = 1.0,
    alpha_level: float = 0.05,
    power: float = 0.80,
    paired: bool = True,
    baseline: float | None = None,
    target_effect: float | None = None,
) -> PowerResult:
    """Smallest difference this design can detect, without double-counting noise.

    For a paired design (same items scored under both systems), the standard
    error of the mean difference is ``sd_diff / sqrt(n)``. For two independent
    groups of size n it is ``sd * sqrt(2/n)``.

    Which convention this function uses, and why
    --------------------------------------------
    ``sd`` here is the standard deviation of the OBSERVED per-item differences.
    It already contains measurement error: noisy labels are exactly what makes
    the observed differences spread out. Shrinking the sample size to
    ``n_eff = n * rho`` *and* feeding in that observed SD charges the same
    measurement error twice, and inflates the MDE by ``1/sqrt(rho)`` for no
    defensible reason. The ``n_eff = n * rho`` identity holds when the effect is
    expressed in TRUE-score units and compared against the observed SD -- you
    shrink n or you inflate the SD, never both.

    This module therefore reports the **observed-scale MDE** as the headline
    ``mde_absolute``: ``(z_{1-a/2} + z_power) * sd_observed / sqrt(n)`` at plain
    n. That is the quantity that is comparable to an observed effect, which is
    what every caller actually holds, and it is the quantity consistent with the
    permutation test run alongside it -- a gate that blocks an effect with
    p=0.005 for being "under the MDE" is reporting its own arithmetic error, not
    a fact about the data.

    Two further figures are reported but NOT used for gating:

    * ``mde_true_scale`` -- the observed-scale MDE divided by ``sqrt(rho)``, the
      attenuation correction. Use it when the effect you care about is stated in
      true-score units rather than in observed rubric points.
    * ``n_effective = n * rho`` -- kept as an interpretive figure: how many
      perfectly-reliable items this design is worth. It is deliberately NOT fed
      back into the MDE, because that is the double count described above.

    ``reliability`` should be the reliability of the quantity being compared --
    for a per-item mean over k annotators, the Spearman-Brown-corrected
    ``rho_k``, not a single-rater per-dimension coefficient.
    """
    notes: list[str] = []
    reliability = max(1e-6, min(1.0, reliability))
    n_eff = max(1.0, n * reliability)

    z_a = z(1 - alpha_level / 2)
    z_b = z(power)
    se_unit = 1.0 / math.sqrt(n) if paired else math.sqrt(2.0 / n)
    mde_obs = (z_a + z_b) * sd * se_unit
    mde_true = mde_obs / math.sqrt(reliability)

    if reliability < 0.999:
        notes.append(
            f"Reliability tax (interpretive): n={n} at rho={reliability:.2f} carries the "
            f"information of n_eff={n_eff:.0f} perfectly-reliable items "
            f"({(1 - n_eff / max(n,1)) * 100:.0f}% precision loss)."
        )
        notes.append(
            f"MDE is reported on the OBSERVED scale ({mde_obs:.4f}) at plain n, because the "
            f"supplied SD already contains measurement error; applying n_eff on top would "
            f"charge that error twice. True-score-scale MDE is {mde_true:.4f} "
            f"(= observed / sqrt(rho))."
        )

    n_req = None
    if target_effect and target_effect > 0:
        mult = 1.0 if paired else 2.0
        n_req = int(math.ceil(mult * ((z_a + z_b) * sd / target_effect) ** 2))
        if n_req > n:
            notes.append(
                f"To detect a {target_effect:g} observed difference you need n>={n_req}; "
                f"you have {n}. Shortfall {n_req - n}."
            )
        else:
            notes.append(f"Current n={n} is sufficient to detect {target_effect:g} (need {n_req}).")

    return PowerResult(
        n=n,
        n_effective=n_eff,
        reliability=reliability,
        sd=sd,
        mde_absolute=mde_obs,
        mde_observed_scale=mde_obs,
        mde_true_scale=mde_true,
        mde_relative=(mde_obs / baseline) if baseline else None,
        alpha_level=alpha_level,
        power=power,
        paired=paired,
        n_required_for_target=n_req,
        target_effect=target_effect,
        convention=(
            "observed_scale: MDE computed at plain n against the observed SD; "
            "n_effective and mde_true_scale reported separately, never compounded"
        ),
        notes=notes,
    )


def attenuated_correlation(observed_r: float, rel_x: float, rel_y: float) -> float:
    """Spearman's disattenuation: the true correlation implied by noisy measures.

    Useful when checking whether an automated judge tracks human labels: an
    observed r of 0.62 between a judge and humans whose own reliability is 0.70
    implies a true correlation near the ceiling, not a mediocre judge.
    """
    denom = math.sqrt(max(1e-9, rel_x) * max(1e-9, rel_y))
    return min(1.0, observed_r / denom)


def multiple_comparison_threshold(n_tests: int, alpha_level: float = 0.05) -> dict:
    """Bonferroni and Benjamini-Hochberg thresholds.

    A track with 6 dimensions x 4 systems is 24 implicit tests. Quoting p<0.05
    per cell means an expected 1.2 false positives before any real effect exists.
    """
    return {
        "n_tests": n_tests,
        "uncorrected": alpha_level,
        "bonferroni": alpha_level / max(1, n_tests),
        "bh_smallest_threshold": alpha_level / max(1, n_tests),
        "bh_largest_threshold": alpha_level,
        "expected_false_positives_uncorrected": round(n_tests * alpha_level, 2),
    }


def benjamini_hochberg(pvals: Sequence[float], alpha_level: float = 0.05) -> list[bool]:
    """BH step-up procedure. Returns a rejection mask aligned to ``pvals``."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    keep = [False] * m
    max_k = -1
    for rank, idx in enumerate(order, start=1):
        if pvals[idx] <= alpha_level * rank / m:
            max_k = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= max_k:
            keep[idx] = True
    return keep


def paired_permutation_test(
    a: Sequence[float], b: Sequence[float], n_perm: int = 10000, seed: int = 0
) -> dict:
    """Two-sided paired permutation test on the mean difference.

    Preferred over a t-test here because rubric composites are bounded in [0,1]
    and visibly non-normal at the ceiling.
    """
    if len(a) != len(b):
        raise ValueError("paired test requires equal-length sequences")
    diffs = [x - y for x, y in zip(a, b)]
    n = len(diffs)
    if n == 0:
        return {"observed": float("nan"), "p_value": float("nan"), "n": 0}
    observed = sum(diffs) / n
    rng = random.Random(seed)
    count = 0
    for _ in range(n_perm):
        s = sum(d if rng.random() < 0.5 else -d for d in diffs) / n
        if abs(s) >= abs(observed) - 1e-12:
            count += 1
    return {
        "observed": round(observed, 5),
        "p_value": round((count + 1) / (n_perm + 1), 5),
        "n": n,
        "n_perm": n_perm,
    }


__all__ = [
    "Interval",
    "PowerResult",
    "attenuated_correlation",
    "benjamini_hochberg",
    "bootstrap_statistic",
    "cluster_bootstrap",
    "minimum_detectable_effect",
    "multiple_comparison_threshold",
    "paired_permutation_test",
    "z",
]
