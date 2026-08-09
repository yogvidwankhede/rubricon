"""Failure taxonomy: detection sensitivity and coverage.

Two questions this module answers, both of which most eval reports skip.

**Does the rubric detect the failures it was written to detect?**
The corpus carries planted failure labels. For each code we can compute, from
annotations alone, whether the dimensions that code is supposed to depress
actually came in lower on the affected responses than on clean ones. A code with
a large planted population and no measurable score depression is a hole in the
instrument: the failure is happening and the eval scores it as fine. That is a
strictly worse outcome than a noisy measurement, because it produces confident
false assurance.

**Where is the design blind?**
Coverage is computed over the declared strata design, not over the data that
happens to exist. The distinction matters: reporting "we covered 34 cells" when
the design has 60 hides the 26 you never sampled. Aggregates over a partially
sampled design are weighted averages with undocumented weights.

Sensitivity is reported as a per-code effect size (Cliff's delta) rather than a
mean difference, because rubric scores are ordinal and bounded, and because
Cliff's delta is interpretable without assuming a distribution.
"""

from __future__ import annotations

import math
import statistics
import sys
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..core.schema import ModelResponse, TaskItem, TrackSpec
from ..annotation.effects import effects_for


#: Track keys already warned about for a missing effects table, so the warning
#: fires once per process rather than once per call. Module-level state is
#: acceptable here because the condition it tracks is module-level configuration.
_WARNED_MISSING_EFFECTS: set[str] = set()


def cliffs_delta(a: Sequence[float], b: Sequence[float]) -> float:
    """Non-parametric effect size in [-1, 1]. P(a>b) - P(a<b).

    Magnitude bands (Romano et al. 2006): 0.147 small, 0.33 medium, 0.474 large.
    """
    if not a or not b:
        return float("nan")
    gt = lt = 0
    for x in a:
        for y in b:
            if x > y:
                gt += 1
            elif x < y:
                lt += 1
    return (gt - lt) / (len(a) * len(b))


def delta_magnitude(d: float) -> str:
    if math.isnan(d):
        return "undefined"
    ad = abs(d)
    if ad < 0.147:
        return "negligible"
    if ad < 0.33:
        return "small"
    if ad < 0.474:
        return "medium"
    return "large"


@dataclass
class CodeSensitivity:
    code: str
    description: str
    n_planted: int
    n_clean: int
    target_dimensions: list[str]
    delta_by_dimension: dict[str, float]
    best_dimension: str
    best_delta: float
    magnitude: str
    coder_recall: float          # fraction of planted cases any annotator tagged
    coder_precision: float       # of all tags for this code, fraction on planted cases
    detected: bool
    diagnosis: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "description": self.description,
            "n_planted": self.n_planted,
            "n_clean": self.n_clean,
            "target_dimensions": self.target_dimensions,
            "delta_by_dimension": {k: round(v, 3) for k, v in self.delta_by_dimension.items()},
            "best_dimension": self.best_dimension,
            "best_delta": round(self.best_delta, 3) if not math.isnan(self.best_delta) else None,
            "magnitude": self.magnitude,
            "coder_recall": round(self.coder_recall, 3),
            "coder_precision": round(self.coder_precision, 3),
            "detected": self.detected,
            "diagnosis": self.diagnosis,
        }


def detection_sensitivity(
    spec: TrackSpec,
    responses: Sequence[ModelResponse],
    annotations: Sequence[Mapping],
    min_planted: int = 4,
    delta_floor: float = 0.33,
) -> dict:
    """Per-code: does the instrument register this failure?"""
    planted_by_resp = {r.response_id: r.planted_failure for r in responses}
    dims = list(spec.rubric.dimension_keys)
    eff = effects_for(spec.key)

    # A track with no effects table has no declared target dimensions for ANY of
    # its codes, so the "did the rubric's own targets move?" question below has
    # no targets to ask about and falls back to every dimension. That fallback
    # reliably produces BLIND SPOT verdicts, and they are fabrications: they
    # record that nobody wrote down what the failure should depress, not that
    # the rubric fails to detect it. The two are indistinguishable in the output
    # unless the output says so, which is what the flag below is for. Track
    # discovery makes this reachable -- a newly dropped-in track module gets an
    # empty effects table by default -- so it is checked here rather than assumed
    # away.
    effects_table_missing = not eff
    if effects_table_missing and spec.key not in _WARNED_MISSING_EFFECTS:
        # Once per track key per process. The condition is a property of the
        # configuration, not of the call, so repeating it on every invocation
        # buries the first (useful) copy under identical noise.
        _WARNED_MISSING_EFFECTS.add(spec.key)
        message = (
            f"track '{spec.key}' has no entry in rubricon.annotation.effects.EFFECTS. "
            "Every failure code will be reported as a BLIND SPOT because no code "
            "declares a target dimension. Those blind spots are artifacts of the "
            "missing effects table and are NOT findings about the rubric."
        )
        print(f"WARNING [rubricon.taxonomy] {message}", file=sys.stderr)
        warnings.warn(message, RuntimeWarning, stacklevel=2)

    # Mean score per response per dimension (average across annotators).
    scores: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    tags: dict[str, list[str]] = defaultdict(list)
    for a in annotations:
        rid = a["response_id"]
        for d, v in a["scores"].items():
            scores[rid][d].append(int(v))
        for c in a.get("failure_codes") or ():
            tags[rid].append(c)

    mean_scores: dict[str, dict[str, float]] = {
        rid: {d: statistics.fmean(vs) for d, vs in dv.items()} for rid, dv in scores.items()
    }

    clean_ids = [rid for rid, code in planted_by_resp.items() if not code and rid in mean_scores]
    results: list[CodeSensitivity] = []

    for code, desc in spec.failure_codes.items():
        planted_ids = [
            rid for rid, c in planted_by_resp.items() if c == code and rid in mean_scores
        ]
        targets = sorted(eff.get(code, {}).keys())

        deltas: dict[str, float] = {}
        for d in dims:
            a = [mean_scores[r][d] for r in planted_ids if d in mean_scores[r]]
            b = [mean_scores[r][d] for r in clean_ids if d in mean_scores[r]]
            if a and b:
                # Direction: for over_refusal_cost, higher is worse, so flip.
                sign = -1.0 if d == "over_refusal_cost" else 1.0
                deltas[d] = sign * cliffs_delta(b, a)  # positive = planted scored lower

        # Restrict the headline to the dimensions the code is SUPPOSED to move.
        candidate = {d: v for d, v in deltas.items() if d in targets} or deltas
        best_dim = max(candidate, key=lambda k: candidate[k]) if candidate else ""
        best = candidate.get(best_dim, float("nan"))

        n_tagged_on_planted = sum(1 for r in planted_ids if code in tags.get(r, []))
        total_tags = sum(1 for r, cs in tags.items() for c in cs if c == code)
        recall = n_tagged_on_planted / len(planted_ids) if planted_ids else float("nan")
        precision = n_tagged_on_planted / total_tags if total_tags else float("nan")

        underpowered = len(planted_ids) < min_planted
        detected = (not underpowered) and (not math.isnan(best)) and best >= delta_floor

        if underpowered:
            diagnosis = (
                f"Underpowered: only {len(planted_ids)} planted instances "
                f"(need >= {min_planted}). Sensitivity is not estimable; this is a "
                "sampling gap, not evidence the rubric misses the failure."
            )
        elif detected:
            diagnosis = (
                f"Detected: responses carrying {code} score materially lower on "
                f"'{best_dim}' (Cliff's delta {best:.2f}, {delta_magnitude(best)})."
            )
        else:
            diagnosis = (
                f"BLIND SPOT: {len(planted_ids)} responses carry {code}, but the "
                f"rubric's own target dimension(s) {targets or dims} show at most "
                f"delta={best:.2f} ({delta_magnitude(best)}). The instrument scores "
                "these responses as acceptable. Add or sharpen a dimension, or "
                "retire the code as unmeasurable."
            )

        results.append(
            CodeSensitivity(
                code=code, description=desc, n_planted=len(planted_ids),
                n_clean=len(clean_ids), target_dimensions=targets,
                delta_by_dimension=deltas, best_dimension=best_dim, best_delta=best,
                magnitude=delta_magnitude(best),
                coder_recall=recall if not math.isnan(recall) else 0.0,
                coder_precision=precision if not math.isnan(precision) else 0.0,
                detected=detected, diagnosis=diagnosis,
            )
        )

    results.sort(key=lambda r: (r.detected, r.best_delta if not math.isnan(r.best_delta) else -9))
    estimable = [r for r in results if r.n_planted >= min_planted]
    blind = [r for r in estimable if not r.detected]

    # Emitted only when the table is actually missing, so a correctly configured
    # track's output is unchanged and downstream diffs stay clean. Consumers
    # should test with ``.get("effects_table_missing")``.
    missing_flag: dict = {}
    if effects_table_missing:
        missing_flag = {
            "effects_table_missing": True,
            "effects_table_warning": (
                f"No effects table is declared for track '{spec.key}'. The "
                f"{len(blind)} blind spot(s) reported here are artifacts of that "
                "omission, not evidence that the rubric misses these failures. "
                "Add an entry to rubricon.annotation.effects.EFFECTS (and to "
                "DIMENSION_PROPERTIES) before quoting any number from this block."
            ),
        }

    return {
        **missing_flag,
        "n_codes": len(results),
        "n_estimable": len(estimable),
        "n_detected": sum(1 for r in estimable if r.detected),
        "n_blind_spots": len(blind),
        "sensitivity_rate": round(
            sum(1 for r in estimable if r.detected) / len(estimable), 3
        ) if estimable else float("nan"),
        "mean_coder_recall": round(
            statistics.fmean([r.coder_recall for r in estimable]), 3
        ) if estimable else None,
        "blind_spot_codes": [r.code for r in blind],
        "codes": [r.to_dict() for r in results],
        "method_note": (
            "Cliff's delta compares mean-across-annotators scores on responses carrying "
            "the code against clean responses. Positive delta means the code depresses "
            "the score, i.e. the instrument registers it. Codes with fewer than "
            f"{min_planted} planted instances are reported as underpowered rather than "
            "undetected -- conflating those two would blame the rubric for a sampling gap."
        ),
    }


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------


def coverage(spec: TrackSpec, items: Sequence[TaskItem],
             responses: Sequence[ModelResponse] | None = None) -> dict:
    """Marginal and full-factorial coverage against the DECLARED design."""
    factors = {k: list(v) for k, v in spec.strata_design.items()}

    marginals: dict[str, dict[str, int]] = {}
    for f, levels in factors.items():
        c = Counter(str(i.strata.get(f, "<missing>")) for i in items)
        marginals[f] = {lv: c.get(lv, 0) for lv in levels}
        extra = {k: v for k, v in c.items() if k not in levels}
        if extra:
            marginals[f]["<undeclared>"] = sum(extra.values())

    designed_cells = 1
    for levels in factors.values():
        designed_cells *= max(1, len(levels))

    observed = Counter(
        "|".join(str(i.strata.get(f, "<missing>")) for f in factors) for i in items
    )
    populated = len(observed)
    empty_fraction = (designed_cells - populated) / designed_cells if designed_cells else 1.0

    # Per-factor gaps: which single levels are thin or absent.
    thin: list[str] = []
    absent: list[str] = []
    for f, counts in marginals.items():
        for lv, n in counts.items():
            if lv.startswith("<"):
                continue
            if n == 0:
                absent.append(f"{f}={lv}")
            elif n < 4:
                thin.append(f"{f}={lv} (n={n})")

    failure_by_stratum: dict[str, dict[str, float]] = {}
    if responses:
        by_item = {i.item_id: i for i in items}
        for f in factors:
            agg: dict[str, list[int]] = defaultdict(list)
            for r in responses:
                it = by_item.get(r.item_id)
                if it is None:
                    continue
                agg[str(it.strata.get(f, "<missing>"))].append(1 if r.planted_failure else 0)
            failure_by_stratum[f] = {
                k: round(statistics.fmean(v), 3) for k, v in sorted(agg.items()) if v
            }

    # Marginal coverage is the metric that actually governs whether an aggregate
    # is defensible. Full-factorial coverage grows multiplicatively and is
    # unreachable by design: 4 factors x ~4 levels is 180+ cells, so a 48-item
    # corpus is "75% empty" no matter how well balanced it is. Gating on that
    # number would block every honestly-designed study, which is why the gate
    # and the decision engine consume the marginal figures below instead.
    total_levels = sum(len(lv) for lv in factors.values())
    populated_levels = sum(
        1 for f, counts in marginals.items()
        for lv, n in counts.items() if not lv.startswith("<") and n > 0
    )
    adequate_levels = sum(
        1 for f, counts in marginals.items()
        for lv, n in counts.items() if not lv.startswith("<") and n >= 4
    )
    marginal_gap_fraction = (
        (total_levels - adequate_levels) / total_levels if total_levels else 1.0
    )

    # Balance: worst-case ratio of the least- to most-sampled level per factor.
    balance = {}
    for f, counts in marginals.items():
        real = [n for lv, n in counts.items() if not lv.startswith("<")]
        balance[f] = round(min(real) / max(real), 3) if real and max(real) else 0.0

    return {
        "n_items": len(items),
        "factors": {f: len(lv) for f, lv in factors.items()},
        "designed_cells": designed_cells,
        "populated_cells": populated,
        "empty_cells": designed_cells - populated,
        "empty_cell_fraction": round(empty_fraction, 4),
        "total_declared_levels": total_levels,
        "populated_levels": populated_levels,
        "adequate_levels": adequate_levels,
        "marginal_gap_fraction": round(marginal_gap_fraction, 4),
        "balance_ratio_by_factor": balance,
        "worst_balance_ratio": round(min(balance.values()), 3) if balance else 0.0,
        "marginals": marginals,
        "absent_levels": absent,
        "thin_levels": thin,
        "cell_counts": dict(observed),
        "failure_rate_by_stratum": failure_by_stratum,
        "interpretation": (
            f"{populated}/{designed_cells} full-factorial cells are populated "
            f"({empty_fraction:.0%} empty), which is expected and not by itself a defect: "
            "full-factorial coverage grows multiplicatively and is not the operative target. "
            f"The governing figure is marginal coverage: {adequate_levels}/{total_levels} "
            f"declared strata levels reach n>=4 ({marginal_gap_fraction:.0%} short), with a "
            f"worst-factor balance ratio of {min(balance.values()) if balance else 0:.2f}. "
            "Absent levels are excluded from every aggregate silently, so they are listed above."
        ),
    }


def investment_recommendations(cov: dict, sens: dict, top_k: int = 5) -> list[str]:
    """Where to spend the next collection budget, ranked."""
    recs: list[str] = []
    for lv in cov.get("absent_levels", [])[:top_k]:
        recs.append(f"COLLECT: stratum level '{lv}' has no items; the design claims it but the data does not cover it.")
    for lv in cov.get("thin_levels", [])[:top_k]:
        recs.append(f"COLLECT: {lv} is too thin to report separately; oversample to n>=8.")
    for code in sens.get("blind_spot_codes", [])[:top_k]:
        recs.append(f"INSTRUMENT: failure code {code} is planted but not registered by any rubric dimension; sharpen the rubric or retire the code.")
    for c in sens.get("codes", []):
        if c["n_planted"] < 4:
            recs.append(f"COLLECT: only {c['n_planted']} instances of {c['code']}; sensitivity is not estimable.")
    # Highest-failure strata are where the signal is.
    for factor, rates in (cov.get("failure_rate_by_stratum") or {}).items():
        if rates:
            worst = max(rates, key=lambda k: rates[k])
            if rates[worst] >= 0.45:
                recs.append(
                    f"EXPAND: {factor}={worst} shows the highest failure rate ({rates[worst]:.0%}); "
                    "this is where additional items buy the most information."
                )
    seen, out = set(), []
    for r in recs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


__all__ = [
    "CodeSensitivity",
    "cliffs_delta",
    "coverage",
    "delta_magnitude",
    "detection_sensitivity",
    "investment_recommendations",
]
