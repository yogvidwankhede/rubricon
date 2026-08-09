"""Markdown results report, generated from the run artifacts.

Generated rather than written, for one reason: a hand-written report goes stale
the first time someone re-runs the pipeline, and nobody notices until a reader
catches a number that no longer exists. Everything here is rendered from
``portfolio.json``, so the report cannot disagree with the run that produced it.

The prose that surrounds the numbers is deliberately spare. Interpretation lives
in ``docs/research-report.md``, which is written by a person and audited against
these artifacts by ``scripts/audit_numbers.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

BAR = "#" * 3


def _f(x: Any, nd: int = 3, dash: str = "n/a") -> str:
    if x is None:
        return dash
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def _pct(x: Any, nd: int = 0) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x) * 100:.{nd}f}%"
    except (TypeError, ValueError):
        return str(x)


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _band(alpha: float | None) -> str:
    if alpha is None:
        return "undefined"
    if alpha >= 0.80:
        return "firm"
    if alpha >= 0.667:
        return "tentative"
    if alpha >= 0.50:
        return "below tentative"
    return "BELOW BLOCK FLOOR"


def render_markdown(data: dict, out_path: Path) -> Path:
    s = data["summary"]
    tracks = data["tracks"]
    L: list[str] = []

    L.append("# Rubricon results\n")
    L.append("> **" + s["simulation_notice"] + "**\n")
    L.append(
        "_Generated from `results/portfolio.json`. Do not edit by hand; re-run "
        "`make report`. Interpretation and argument live in "
        "`docs/research-report.md`._\n"
    )

    # -- portfolio ---------------------------------------------------------
    L.append("\n## Portfolio\n")
    L.append(_table(
        ["metric", "value"],
        [
            ["tracks", s["n_tracks"]],
            ["items", s["n_items"]],
            ["responses", s["n_responses"]],
            ["annotations", s["n_annotations"]],
            ["rubric dimensions", s["n_dimensions"]],
            ["failure codes", s["n_failure_codes"]],
            ["claims submitted to the gate", s["claims_submitted"]],
            ["claims blocked", f"{s['claims_blocked']} ({_pct(s['block_rate'])})"],
        ],
    ))

    L.append("\n### Recommendations\n")
    L.append(_table(
        ["track", "depth", "mean alpha", "band", "gold accuracy", "recommendation"],
        [
            [
                k,
                t["depth"],
                _f(t["alpha_mean"]),
                _band(t["alpha_mean"]),
                _f(t["gold_accuracy"]),
                t["decision"]["recommendation"].upper(),
            ]
            for k, t in tracks.items()
        ],
    ))

    # -- per track ---------------------------------------------------------
    for key, t in tracks.items():
        L.append(f"\n---\n\n## {t['name']} (`{key}`)\n")
        L.append(f"**Depth tier:** `{t['depth']}` - {t['depth_contract']}\n")
        L.append(f"**Research question:** {t['research_question']}\n")
        L.append(f"**Unit of analysis:** {t['unit_of_analysis']}\n")
        L.append(f"**Rubric version:** `{t['rubric_version']}`\n")
        L.append(
            f"**Corpus:** {t['n_items']} items, {t['n_responses']} responses, "
            f"{t['n_annotations']} annotations (mean replication {t['mean_replication']}).\n"
        )

        # reliability
        L.append(f"\n{BAR} Reliability\n")
        rows = []
        for dim, rep in sorted(
            t["agreement"].items(),
            key=lambda kv: (kv[1]["krippendorff_alpha"]["value"] is None,
                            kv[1]["krippendorff_alpha"]["value"] or 0),
        ):
            a = rep["krippendorff_alpha"]["value"]
            contested = "yes" if dim in t.get("contested_dimensions", []) else ""
            ci = rep.get("ci")
            interval = (
                f"[{_f(ci['lo'])}, {_f(ci['hi'])}]" if ci else "n/a"
            )
            rows.append([
                f"`{dim}`", rep["scale"], _f(a), interval, _band(a),
                _f(rep["percent_agreement"]["value"]),
                _f(rep["fleiss_kappa"]["value"]),
                _f(rep["gwet_ac1"]["value"]),
                contested,
            ])
        L.append(_table(
            ["dimension", "scale", "alpha", "95% CI", "band", "raw agr.", "Fleiss k",
             "Gwet AC1", "contested"],
            rows,
        ))
        L.append(
            f"\nMean alpha {_f(t['alpha_mean'])}, worst dimension {_f(t['alpha_min'])}, "
            f"gold-item exact accuracy {_f(t['gold_accuracy'])}.\n"
        )
        L.append(
            "\nThe alpha interval is a cluster bootstrap over responses. Where it does not "
            "exclude a policy threshold, the band above is a point estimate and not an "
            "established classification; the gate's check message says so per dimension.\n"
        )
        rel = t.get("composite_reliability")
        if rel and rel.get("rho_1") is not None:
            ci1, cik = rel.get("ci_rho_1"), rel.get("ci_rho_k")
            L.append(
                f"\n**Reliability of the compared quantity.** The system comparisons are made "
                f"on the per-item mean of the weighted composite over {rel['k_raters']} "
                f"annotators, so neither an individual dimension's alpha nor the mean of them "
                f"is its reliability. The composite's own single-rater interval alpha is "
                f"rho_1 = {_f(rel['rho_1'])}"
                + (f" [{_f(ci1['lo'])}, {_f(ci1['hi'])}]" if ci1 else "")
                + f"; Spearman-Brown for the {rel['k_raters']}-rater mean gives "
                f"rho_k = {_f(rel['rho_k'])}"
                + (f" [{_f(cik['lo'])}, {_f(cik['hi'])}]" if cik else "")
                + ". rho_k is what the power calculation consumes.\n"
            )
        paradox = [d for d, r in t["agreement"].items() if r["kappa_paradox_detected"]]
        if paradox:
            L.append(
                f"\n> **Kappa paradox detected** on {', '.join(paradox)}. High raw "
                "agreement with low kappa indicates category prevalence skew, not "
                "annotator unreliability. Remedy is stratified oversampling of the "
                "rare level, not retraining.\n"
            )

        # pool health
        d = t["drift"]
        L.append(f"\n{BAR} Pool health\n")
        L.append(_table(
            ["check", "value"],
            [
                ["flagged annotators",
                 f"{', '.join(t['annotator_pool']['flagged_annotators']) or 'none'} "
                 f"({_pct(t['annotator_pool']['flagged_fraction'])})"],
                ["drift", f"{d['drift_detected']} (range {_f(d['span'])}, "
                          f"permutation p={_f(d.get('p_value'), 4)})"],
                ["adjudication queue",
                 f"{t['triage']['summary']['n_queued']} queued, "
                 f"{t['triage']['summary']['n_resolved']} resolved "
                 f"({_pct(t['triage']['summary']['resolution_rate'])})"],
                ["rubric-gap rate", _pct(t["rubric_gaps"]["rubric_gap_rate"], 1)],
            ],
        ))

        # scores
        L.append(f"\n{BAR} System scores\n")
        L.append(_table(
            ["system", "n items", "mean composite", "95% CI", "CI half-width"],
            [
                [sid, sc["n_items"], _f(sc["mean_composite"], 4),
                 f"[{_f(sc['ci']['lo'], 4)}, {_f(sc['ci']['hi'], 4)}]",
                 _f(sc["ci"]["width"] / 2, 4)]
                for sid, sc in t["scores"].items()
            ],
        ))

        comps = (t.get("comparison") or {}).get("comparisons") or {}
        if comps:
            L.append(f"\n{BAR} Between-system comparisons\n")
            L.append(_table(
                ["contrast", "effect", "95% CI", "MDE (observed)", "MDE (true-score)",
                 "exceeds MDE?", "perm p", "n_eff"],
                [
                    [
                        f"{c['system']} vs {c['reference']}",
                        _f(c["mean_difference"], 4),
                        f"[{_f(c['ci']['lo'], 4)}, {_f(c['ci']['hi'], 4)}]",
                        _f(c["power"]["mde_observed_scale"], 4),
                        _f(c["power"]["mde_true_scale"], 4),
                        "yes" if c["exceeds_mde"] else "**NO - inside the noise floor**",
                        _f(c["permutation_test"]["p_value"], 4),
                        _f(c["power"]["n_effective"], 1),
                    ]
                    for c in comps.values()
                ],
            ))
            mc = t["comparison"]["multiplicity"]
            L.append(
                f"\n{mc['n_tests']} pre-registered contrasts; Bonferroni threshold "
                f"{_f(mc['bonferroni'], 4)}. Expected false positives at an uncorrected "
                f"0.05: {mc['expected_false_positives_uncorrected']}.\n"
            )
            # The reliability tax, spelled out -- and charged exactly once.
            any_c = next(iter(comps.values()))
            pw = any_c["power"]
            L.append(
                f"\n**Reliability tax:** n={pw['n']} items at rho_k="
                f"{_f(pw['reliability'])} carries the information of "
                f"n_effective={_f(pw['n_effective'], 1)} perfectly-reliable items. That is "
                "an interpretive figure and is deliberately NOT fed back into the MDE: the "
                "SD in the MDE is the observed spread, which already contains the "
                "measurement error, so shrinking n to n_effective as well would charge for "
                "the same error twice. The MDE column is therefore the observed-scale "
                "figure at plain n, which is the one comparable to an observed effect. The "
                "true-score-scale figure, observed / sqrt(rho_k), is reported beside it.\n"
            )

        # sensitivity
        sens = t["sensitivity"]
        L.append(f"\n{BAR} Failure detection\n")
        L.append(
            f"{sens['n_detected']}/{sens['n_estimable']} estimable codes detected "
            f"(of {sens['n_codes']} declared); mean coder recall "
            f"{_f(sens.get('mean_coder_recall'))}. "
            f"Blind spots: {', '.join(sens['blind_spot_codes']) or 'none'}.\n"
        )
        L.append(_table(
            ["code", "n planted", "target dims", "best delta", "magnitude", "detected", "coder recall"],
            [
                [c["code"], c["n_planted"], ", ".join(c["target_dimensions"]) or "-",
                 _f(c["best_delta"]), c["magnitude"],
                 "yes" if c["detected"] else ("underpowered" if c["n_planted"] < 4 else "**NO**"),
                 _f(c["coder_recall"], 2)]
                for c in sens["codes"]
            ],
        ))

        # coverage
        cov = t["coverage"]
        L.append(f"\n{BAR} Coverage\n")
        L.append(
            f"{cov['adequate_levels']}/{cov['total_declared_levels']} declared strata "
            f"levels reach n>=4 (marginal gap {_pct(cov['marginal_gap_fraction'], 1)}); "
            f"worst-factor balance ratio {_f(cov['worst_balance_ratio'], 2)}. "
            f"Full-factorial: {cov['populated_cells']}/{cov['designed_cells']} cells "
            "populated, which is expected and not the operative metric.\n"
        )
        if cov["absent_levels"]:
            L.append(f"\n**Absent levels:** {', '.join(cov['absent_levels'])}\n")
        if cov["thin_levels"]:
            L.append(f"\n**Thin levels:** {', '.join(cov['thin_levels'])}\n")

        # redteam
        L.append(f"\n{BAR} Red-team probes\n")
        L.append(_table(
            ["probe", "statistic", "threshold", "result"],
            [
                [p["probe"], _f(p["statistic"], 4), _f(p["threshold"], 4),
                 "**FAIL**" if p["failed"] else "pass"]
                for p in t["redteam"]["probes"]
            ],
        ))
        for p in t["redteam"]["probes"]:
            if p["failed"]:
                L.append(f"\n- **{p['probe']}**: {p['interpretation']}\n")

        # gate
        gv = t["gate"]["summary"]["by_verdict"]
        L.append(f"\n{BAR} Signal gate\n")
        L.append(f"{gv['pass']} pass, {gv['warn']} warn, **{gv['block']} blocked** "
                 f"of {t['gate']['summary']['n_claims']} claims.\n")
        blocked = [c for c in t["gate"]["claims"] if c["verdict"] == "block"]
        if blocked:
            L.append("\nWithheld claims:\n")
            for c in blocked:
                L.append(f"\n- ~~{c['text']}~~")
                for r in c["blocking_reasons"]:
                    L.append(f"\n  - BLOCKED: {r}")
            L.append("\n")

        # decision
        dec = t["decision"]
        L.append(f"\n{BAR} Decision: **{dec['recommendation'].upper()}**\n")
        L.append(f"{dec['headline']}\n")
        L.append("\n**Rationale**\n")
        for r in dec["rationale"]:
            L.append(f"\n- {r}")
        L.append("\n\n**Next actions**\n")
        for a in dec["next_actions"]:
            L.append(f"\n- {a}")
        if dec["stop_criteria"]:
            L.append("\n\n**Stop criteria**\n")
            for c in dec["stop_criteria"]:
                L.append(f"\n- {c}")
        if dec.get("projected_cost_to_fix_usd"):
            L.append(f"\n\nProjected remediation cost: "
                     f"${dec['projected_cost_to_fix_usd']:,.2f} "
                     "(at the documented unit label cost assumption).\n")
        L.append("\n")

        if t["investment"]:
            L.append("\n**Where the next collection budget should go**\n")
            for r in t["investment"]:
                L.append(f"\n- {r}")
            L.append("\n")

        L.append("\n**Known limitations of this track**\n")
        for lim in t["known_limitations"]:
            L.append(f"\n- {lim}")
        L.append("\n")

    L.append("\n---\n\n## Reproduction\n")
    L.append("```\nmake all\n```\n")
    L.append(
        "\nRuns offline with no API key. The statistical core has no third-party "
        "dependencies. `make validate` checks Krippendorff's alpha against the "
        "published 2011 reference values before anything else runs.\n"
    )
    L.append("\n> " + s["simulation_notice"] + "\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L), encoding="utf-8")
    return out_path


__all__ = ["render_markdown"]
