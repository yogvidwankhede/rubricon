"""End-to-end pipeline.

Stages, in order, each writing its artifact to the run directory:

    generate -> annotate -> triage -> adjudicate -> score -> probe -> gate -> decide

The ordering is not arbitrary. Gating happens *last*, after every piece of
evidence exists, and the claims submitted to it are constructed from the
evidence rather than written by hand. That is what makes the gate a control
rather than a formality: nobody gets to phrase the claim before seeing whether
it survives.

Everything is deterministic. Same code, same corpus, same numbers, on any
machine, with no network.
"""

from __future__ import annotations

import os
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .annotation.adjudicate import (
    adjudicate,
    adjudication_summary,
    post_adjudication_agreement,
    triage,
)
from .annotation.effects import contested_dimensions
from .annotation.pool import SIMULATION_NOTICE, annotate, pool_description
from .core.schema import TrackSpec, content_hash
from .core.store import Store
from .gates.decision import DecisionInput, recommend
from .gates.signal import Claim, ClaimLedger, SignalGate, policy_for_depth
from .models.client import GenerationConfig, build_client
from .redteam import probes as redteam
from .stats.agreement import composite_reliability, per_dimension_agreement
from .stats.drift import detect_drift, profile_annotators, rubric_gap_signals
from .stats.precision import (
    cluster_bootstrap,
    minimum_detectable_effect,
    multiple_comparison_threshold,
    paired_permutation_test,
)
from .taxonomy.induce import coverage, detection_sensitivity, investment_recommendations
from .tracks import DEPTH_CONTRACT, Track, all_tracks, get, scales_for

SYSTEMS = ("sut-baseline-v1", "sut-candidate-v2", "sut-candidate-v3")
REFERENCE_SYSTEM = "sut-baseline-v1"


def _stable_seed(*parts: str) -> int:
    """Process-independent bootstrap seed.

    The builtin ``hash()`` is salted per interpreter (PEP 456), so seeding a
    resampler with ``hash(system_id)`` makes every interval move between runs.
    That silently breaks the reproducibility claim this module documents, and it
    does so in the one place nobody looks: the seed argument.
    """
    return int(content_hash("::".join(parts), length=8), 16) % 10_000


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


def score_track(spec: TrackSpec, annotations: Sequence[Mapping],
                response_system: Mapping[str, str]) -> dict:
    """Per-system composites with cluster-bootstrapped intervals."""
    by_system_item: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for a in annotations:
        sysid = response_system.get(a["response_id"])
        if sysid is None:
            continue
        by_system_item[sysid][a["item_id"]].append(spec.rubric.composite(a["scores"]))

    out: dict[str, dict] = {}
    for sysid, per_item in sorted(by_system_item.items()):
        clusters = [v for v in per_item.values() if v]
        ci = cluster_bootstrap(clusters, n_boot=2000, seed=_stable_seed(sysid))
        flat = [x for c in clusters for x in c]
        out[sysid] = {
            "n_items": len(clusters),
            "n_annotations": len(flat),
            "mean_composite": round(ci.point, 4),
            "sd": round(statistics.stdev(flat), 4) if len(flat) > 1 else 0.0,
            "ci": ci.to_dict(),
            "per_item_mean": {k: round(statistics.fmean(v), 4) for k, v in sorted(per_item.items())},
        }
    return out


def compare_systems(spec: TrackSpec, scores: Mapping[str, dict], reliability: float,
                    reference: str = REFERENCE_SYSTEM) -> dict:
    """Paired comparisons against the reference, with MDE and multiplicity.

    ``reliability`` must be the reliability OF THE COMPARED QUANTITY: the
    Spearman-Brown-corrected ``rho_k`` of the composite over the k annotators
    whose mean is being differenced. It is not the mean of the per-dimension
    single-rater alphas -- that is a different statistic about a different
    quantity, and it happens to be much smaller, which quietly inflated every
    MDE in the report.
    """
    ref = scores.get(reference)
    if not ref:
        return {}
    comparisons = {}
    others = [s for s in scores if s != reference]
    # Count EVERY contrast that will be reported, including the candidate-vs-
    # candidate one added below. Correcting for only the reference contrasts
    # understates the family size and quietly loosens the corrected threshold.
    n_contrasts = len(others) + (1 if len(others) >= 2 else 0)
    mc = multiple_comparison_threshold(n_contrasts)

    for sysid in sorted(others):
        cand = scores[sysid]
        shared = sorted(set(ref["per_item_mean"]) & set(cand["per_item_mean"]))
        a = [cand["per_item_mean"][k] for k in shared]
        b = [ref["per_item_mean"][k] for k in shared]
        diffs = [x - y for x, y in zip(a, b)]
        if not diffs:
            continue
        sd_diff = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
        ci = cluster_bootstrap([[d] for d in diffs], n_boot=2000,
                               seed=_stable_seed(sysid, reference))
        power = minimum_detectable_effect(
            n=len(shared), sd=sd_diff or 1e-6, reliability=max(0.01, reliability),
            baseline=ref["mean_composite"], target_effect=0.05,
        )
        perm = paired_permutation_test(a, b, n_perm=10000,
                                       seed=_stable_seed(sysid))
        effect = statistics.fmean(diffs)
        comparisons[f"{sysid}_vs_{reference}"] = {
            "system": sysid,
            "reference": reference,
            "n_paired_items": len(shared),
            "mean_difference": round(effect, 4),
            "sd_difference": round(sd_diff, 4),
            "ci": ci.to_dict(),
            "permutation_test": perm,
            "power": power.to_dict(),
            "exceeds_mde": abs(effect) >= power.mde_absolute,
            "significant_uncorrected": perm["p_value"] < 0.05,
            "significant_bonferroni": perm["p_value"] < mc["bonferroni"],
        }

    # Candidate-vs-candidate, the comparison that usually cannot be made.
    cands = sorted(s for s in scores if s != reference)
    if len(cands) >= 2:
        s1, s2 = cands[0], cands[1]
        shared = sorted(set(scores[s1]["per_item_mean"]) & set(scores[s2]["per_item_mean"]))
        a = [scores[s1]["per_item_mean"][k] for k in shared]
        b = [scores[s2]["per_item_mean"][k] for k in shared]
        diffs = [x - y for x, y in zip(a, b)]
        if diffs:
            sd_diff = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
            ci = cluster_bootstrap([[d] for d in diffs], n_boot=2000, seed=4242)
            power = minimum_detectable_effect(
                n=len(shared), sd=sd_diff or 1e-6, reliability=max(0.01, reliability),
                baseline=scores[s2]["mean_composite"], target_effect=0.05,
            )
            effect = statistics.fmean(diffs)
            perm = paired_permutation_test(a, b, n_perm=10000, seed=99)
            comparisons[f"{s1}_vs_{s2}"] = {
                "system": s1, "reference": s2, "n_paired_items": len(shared),
                "mean_difference": round(effect, 4), "sd_difference": round(sd_diff, 4),
                "ci": ci.to_dict(),
                "permutation_test": perm,
                "power": power.to_dict(),
                "exceeds_mde": abs(effect) >= power.mde_absolute,
                # Derived from the p-value that was just computed, exactly as in
                # the reference-contrast branch above. These were previously
                # hardcoded False, so a candidate-vs-candidate difference could
                # carry p=0.004 and still be reported as not significant.
                "significant_uncorrected": perm["p_value"] < 0.05,
                "significant_bonferroni": perm["p_value"] < mc["bonferroni"],
            }
    return {"multiplicity": mc, "comparisons": comparisons}


# --------------------------------------------------------------------------
# claim construction
# --------------------------------------------------------------------------


def build_claims(track: Track, agreement: dict, scores: dict, comparison: dict,
                 cov: dict, pool: dict, drift: dict, gaps: dict,
                 mean_replication: float, gate: SignalGate,
                 composite_rel: dict | None = None) -> ClaimLedger:
    """Construct the claims a stakeholder would want, then test each one.

    These are written as the sentences someone would actually put in a deck.
    The gate decides which survive.
    """
    ledger = ClaimLedger()
    spec = track.spec
    alphas = {d: agreement[d]["krippendorff_alpha"]["value"] for d in agreement}
    numeric = [v for v in alphas.values() if v is not None]
    alpha_mean = statistics.fmean(numeric) if numeric else float("nan")

    min_gold = None
    ga = [a["gold_exact"] for a in pool["annotators"] if a["gold_exact"] is not None]
    if ga:
        min_gold = min(ga)

    pool_checks = gate.check_pool_health(
        pool["flagged_fraction"], drift["drift_detected"], gaps["rubric_gap_rate"], min_gold
    )
    cov_check = gate.check_coverage(cov)
    rep_check = gate.check_replication(mean_replication)

    # -- Claim 1: per-dimension reliability is adequate --------------------
    for dim, rep in sorted(agreement.items()):
        a = rep["krippendorff_alpha"]["value"]
        c = Claim(
            claim_id=f"{spec.key}.dim.{dim}",
            track=spec.key,
            text=f"Dimension '{dim}' of the {spec.name} rubric produces reliable measurements.",
            # Descriptive: reporting the reliability of your own instrument is a
            # fact about the data collected, not a claim about the world, so it
            # is permitted at every depth tier. Withholding it would be perverse
            # -- an exploratory track must still be able to publish the evidence
            # that it is exploratory.
            kind="descriptive",
            evidence={"alpha": a, "alpha_ci": rep.get("ci"), "scale": rep["scale"],
                      "kappa_paradox": rep["kappa_paradox_detected"],
                      "percent_agreement": rep["percent_agreement"]["value"]},
        )
        checks = [gate.check_depth_contract("descriptive"),
                  gate.check_reliability(a, dim, ci=rep.get("ci")), rep_check]
        ledger.submit(gate.evaluate(c, checks))

    # -- Claim 2: per-system score -----------------------------------------
    for sysid, s in sorted(scores.items()):
        c = Claim(
            claim_id=f"{spec.key}.score.{sysid}",
            track=spec.key,
            text=(f"{sysid} scores {s['mean_composite']:.3f} "
                  f"[{s['ci']['lo']:.3f}, {s['ci']['hi']:.3f}] on {spec.name}."),
            kind="measurement",
            evidence={"mean": s["mean_composite"], "ci": s["ci"], "n_items": s["n_items"]},
        )
        checks = [
            gate.check_depth_contract("measurement"),
            gate.check_reliability(alpha_mean),
            gate.check_precision(s["ci"]["width"] / 2.0),
            cov_check, rep_check, *pool_checks,
        ]
        ledger.submit(gate.evaluate(c, checks))

    # -- Claim 3: system rankings ------------------------------------------
    for name, comp in sorted((comparison.get("comparisons") or {}).items()):
        direction = "outperforms" if comp["mean_difference"] > 0 else "underperforms"
        c = Claim(
            claim_id=f"{spec.key}.rank.{name}",
            track=spec.key,
            text=(f"{comp['system']} {direction} {comp['reference']} on {spec.name} "
                  f"by {abs(comp['mean_difference']):.3f} composite points."),
            kind="ranking",
            evidence={"effect": comp["mean_difference"], "ci": comp["ci"],
                      "mde": comp["power"]["mde_absolute"],
                      "mde_observed_scale": comp["power"]["mde_observed_scale"],
                      "mde_true_scale": comp["power"]["mde_true_scale"],
                      "mde_convention": comp["power"]["convention"],
                      "p_value": comp["permutation_test"]["p_value"],
                      "composite_reliability_rho_k":
                          (composite_rel or {}).get("rho_k"),
                      "n_effective": comp["power"]["n_effective"]},
        )
        checks = [
            gate.check_depth_contract("ranking"),
            gate.check_reliability(alpha_mean),
            gate.check_effect_vs_mde(comp["mean_difference"], comp["power"]["mde_absolute"]),
            gate.check_interval_excludes_zero(comp["ci"]["lo"], comp["ci"]["hi"]),
            cov_check, rep_check, *pool_checks,
        ]
        ledger.submit(gate.evaluate(c, checks))

    return ledger


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


@dataclass
class TrackResult:
    key: str
    payload: dict


def run_track(track: Track, store: Store, adjudication_capacity_frac: float = 0.6) -> dict:
    spec = track.spec
    items = track.items()
    responses = track.responses()

    # Generation goes through the client interface even for fixtures, so the
    # swap to a live client is a one-line change and the provenance record is
    # produced the same way in both cases.
    #
    # RUBRICON_CLIENT selects the backend. It defaults to "fixture", which is the
    # only setting that produces the reproducible offline run this repository
    # documents; anything else is opt-in live generation and is neither cached
    # nor verified here. The variable was previously named in an error message
    # and read nowhere, so setting it did nothing.
    kind = os.environ.get("RUBRICON_CLIENT", "fixture").strip().lower() or "fixture"
    cfg = GenerationConfig(model=kind, temperature=0.0, seed=0)
    clients = {s: build_client(kind, s, fixtures=responses) for s in SYSTEMS}
    provenance = {s: c.provenance() for s, c in sorted(clients.items())}
    regenerated = [c.generate(i, cfg) for s, c in clients.items() for i in items]
    if kind == "fixture":
        assert len(regenerated) == len(responses), "client replay lost responses"
    else:
        responses = regenerated

    annotations = annotate(spec, items, responses)
    rows = [a.to_dict() for a in annotations]

    queue = triage(rows, spec)
    adjudications = adjudicate(
        queue, rows, spec, capacity=int(len(queue) * adjudication_capacity_frac)
    )
    adj_rows = [a.to_dict() for a in adjudications]

    scales = scales_for(spec)
    agreement = per_dimension_agreement(rows, spec.rubric.dimension_keys, scales)
    alphas = {d: agreement[d]["krippendorff_alpha"]["value"] for d in agreement}
    numeric = [v for v in alphas.values() if v is not None]
    alpha_mean = statistics.fmean(numeric) if numeric else float("nan")
    alpha_min = min(numeric) if numeric else float("nan")

    # The reliability that the power calculation needs is the reliability of the
    # quantity being compared -- the per-item mean of the composite over k
    # annotators -- not the mean of the per-dimension single-rater alphas.
    mean_rep = len(rows) / len(responses) if responses else 0.0
    k_raters = max(1, round(mean_rep))
    composite_rel = composite_reliability(spec, rows, k=k_raters, n_boot=600)

    contested = contested_dimensions(spec.key)
    gold = {i.item_id: dict(i.gold_scores) for i in items if i.is_gold and i.gold_scores}
    pool = profile_annotators(rows, spec.rubric.dimension_keys, gold,
                              contested_dimensions=contested)
    drift = detect_drift(rows, spec.rubric.dimension_keys)
    gaps = rubric_gap_signals(adj_rows)
    post_adj = post_adjudication_agreement(adjudications, rows, spec)

    response_system = {r.response_id: r.system_id for r in responses}
    scores = score_track(spec, rows, response_system)
    comparison = compare_systems(
        spec, scores, composite_rel["rho_k"] if composite_rel["rho_k"] else 0.01
    )

    cov = coverage(spec, items, responses)
    sens = detection_sensitivity(spec, responses, rows)

    mean_ci_half = statistics.fmean(
        [s["ci"]["width"] / 2 for s in scores.values()]
    ) if scores else float("nan")
    largest_effect = max(
        (abs(c["mean_difference"]) for c in (comparison.get("comparisons") or {}).values()),
        default=0.0,
    )
    probe_results = redteam.run_all(
        spec, responses, rows,
        ci_half_width=mean_ci_half, reference_effect=largest_effect,
    )

    gate = SignalGate(policy_for_depth(spec.depth), depth=spec.depth)
    ledger = build_claims(track, agreement, scores, comparison, cov, pool, drift, gaps,
                          mean_rep, gate, composite_rel=composite_rel)

    gold_acc = [a["gold_exact"] for a in pool["annotators"] if a["gold_exact"] is not None]
    mde = min(
        (c["power"]["mde_absolute"] for c in (comparison.get("comparisons") or {}).values()),
        default=float("inf"),
    )

    decision = recommend(DecisionInput(
        track=spec.key, depth=spec.depth,
        alpha_mean=alpha_mean, alpha_min=alpha_min,
        alpha_by_dimension={k: (v if v is not None else 0.0) for k, v in alphas.items()},
        gold_accuracy=statistics.fmean(gold_acc) if gold_acc else float("nan"),
        ci_half_width=mean_ci_half,
        mde=mde if mde != float("inf") else 1.0,
        largest_effect=largest_effect,
        rubric_gap_rate=gaps["rubric_gap_rate"],
        coverage_marginal_gap=cov["marginal_gap_fraction"],
        n_items=len(items), n_annotations=len(rows),
        detection_sensitivity=sens.get("sensitivity_rate"),
        flagged_annotator_fraction=pool["flagged_fraction"],
    ))

    # Persist raw artifacts.
    store.write_jsonl(f"{spec.key}/items.jsonl", items)
    store.write_jsonl(f"{spec.key}/responses.jsonl", responses)
    store.write_jsonl(f"{spec.key}/annotations.jsonl", annotations)
    store.write_jsonl(f"{spec.key}/adjudications.jsonl", adjudications)
    store.write_json(f"{spec.key}/spec.json", spec.to_dict())

    payload = {
        "track": spec.key,
        "name": spec.name,
        "depth": spec.depth,
        "depth_contract": DEPTH_CONTRACT.get(spec.depth, ""),
        "research_question": spec.research_question,
        "rubric_version": spec.rubric.version,
        "unit_of_analysis": spec.unit_of_analysis,
        "known_limitations": list(spec.known_limitations),
        "contested_dimensions": contested_dimensions(spec.key),
        "n_items": len(items),
        "n_responses": len(responses),
        "n_annotations": len(rows),
        "mean_replication": round(mean_rep, 2),
        "agreement": agreement,
        "composite_reliability": composite_rel,
        "alpha_mean": round(alpha_mean, 4),
        "alpha_min": round(alpha_min, 4),
        "gold_accuracy": round(statistics.fmean(gold_acc), 4) if gold_acc else None,
        "annotator_pool": pool,
        "drift": drift,
        "triage": {
            "queue": [t.to_dict() for t in queue[:40]],
            "summary": adjudication_summary(queue, adjudications, len(responses)),
            "post_adjudication_label_quality": post_adj,
        },
        "rubric_gaps": gaps,
        "scores": scores,
        "comparison": comparison,
        "coverage": cov,
        "sensitivity": sens,
        "investment": investment_recommendations(cov, sens),
        "redteam": probe_results,
        "gate": {"policy": gate.policy.to_dict(), **ledger.to_dict()},
        "decision": decision.to_dict(),
        "client_provenance": provenance,
    }
    store.write_json(f"{spec.key}/results.json", payload)
    return payload


def run_all(results_dir: str | Path = "results", tracks: Sequence[str] | None = None) -> dict:
    store = Store(Path(results_dir))
    selected = [get(k) for k in tracks] if tracks else all_tracks()

    per_track = {}
    for t in selected:
        per_track[t.key] = run_track(t, store)

    # Portfolio roll-up.
    total_claims = sum(p["gate"]["summary"]["n_claims"] for p in per_track.values())
    total_blocked = sum(p["gate"]["summary"]["by_verdict"]["block"] for p in per_track.values())
    recs = {k: p["decision"]["recommendation"] for k, p in per_track.items()}

    summary = {
        "simulation_notice": SIMULATION_NOTICE,
        "n_tracks": len(per_track),
        "n_items": sum(p["n_items"] for p in per_track.values()),
        "n_responses": sum(p["n_responses"] for p in per_track.values()),
        "n_annotations": sum(p["n_annotations"] for p in per_track.values()),
        "n_dimensions": sum(len(p["agreement"]) for p in per_track.values()),
        "n_failure_codes": sum(p["sensitivity"]["n_codes"] for p in per_track.values()),
        "claims_submitted": total_claims,
        "claims_blocked": total_blocked,
        "block_rate": round(total_blocked / total_claims, 3) if total_claims else 0.0,
        "recommendations": recs,
        "alpha_by_track": {k: p["alpha_mean"] for k, p in per_track.items()},
        "gold_accuracy_by_track": {k: p["gold_accuracy"] for k, p in per_track.items()},
        "blind_spots_by_track": {
            k: p["sensitivity"]["blind_spot_codes"] for k, p in per_track.items()
        },
        "redteam_failures_by_track": {
            k: p["redteam"]["failed_probes"] for k, p in per_track.items()
        },
        "annotator_pool": pool_description(),
    }
    store.write_json("summary.json", summary)
    store.write_json("portfolio.json", {"summary": summary, "tracks": per_track})
    return {"summary": summary, "tracks": per_track}


__all__ = ["REFERENCE_SYSTEM", "SYSTEMS", "build_claims", "compare_systems",
           "run_all", "run_track", "score_track"]
