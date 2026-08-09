#!/usr/bin/env python3
"""Run the verdict-sensitivity analysis and print a readable summary.

    make sensitivity
    PYTHONPATH=src python3 scripts/sensitivity_report.py [--results results]
                                                         [--seeds 20]
                                                         [--track KEY]...
                                                         [--reuse]

What this is for
----------------
``results/sensitivity.json`` is complete but unreadable: several thousand lines
of swept thresholds. This script is the human-facing view of it, and it exists
because the analysis is worthless if nobody reads it. The whole point of running
a sensitivity analysis is that a reviewer should be able to see, in one screen,
which of the portfolio's conclusions are load-bearing and which are artifacts of
a hand-set parameter.

This is a REPORTING tool, not a gate. It exits 0 even when every conclusion is
FRAGILE. That is deliberate. A sensitivity analysis wired to fail a build
creates an incentive to make the analysis weaker -- fewer perturbations, wider
fragility bands -- and an honest measurement that nobody can suppress is worth
more than a check that everybody games. The gate for publishable claims is
``gates/signal.py``; this tells you how much to trust the gate's inputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from rubricon.gates.sensitivity import FRAGILITY_BAND, run_sensitivity  # noqa: E402

RULE = "=" * 100
THIN = "-" * 100

# Printed next to a classification so the label is self-explanatory in a
# terminal, without the reader having to find the module docstring.
LABEL_GLOSS = {
    "ROBUST": "survives every perturbation applied",
    "CONDITIONAL": "survives small perturbations; moves under a named structural one",
    "FRAGILE": "moves under a perturbation small enough that the parameter, not the data, decides",
}


def _load_or_run(args: argparse.Namespace) -> dict:
    path = Path(args.results) / "sensitivity.json"
    if args.reuse and path.exists():
        print(f"reusing existing {path} (--reuse)", file=sys.stderr)
        return json.loads(path.read_text(encoding="utf-8"))
    return run_sensitivity(
        results_dir=args.results,
        track_keys=args.track or None,
        n_contested_seeds=args.seeds,
        write=True,
        verbose=not args.quiet,
    )


def _print_header(data: dict) -> None:
    print()
    print(RULE)
    print("VERDICT SENSITIVITY -- which conclusions survive their assumptions")
    print(RULE)
    print(
        f"tracks: {', '.join(data['tracks'])}   "
        f"pipeline runs: {data['n_pipeline_runs']}   "
        f"elapsed: {data['elapsed_seconds']}s"
    )
    reg = data.get("track_registration") or {}
    if reg.get("tracks_missing_effects_table"):
        print(
            "WARNING: no effects table for "
            f"{', '.join(reg['tracks_missing_effects_table'])} -- their "
            "detection-sensitivity blind spots are artifacts, not findings."
        )
    if reg.get("skipped"):
        for s in reg["skipped"]:
            print(f"NOTE: module '{s['module']}' not registered ({s['reason']}).")


def _print_classification(data: dict) -> None:
    print()
    print("CONCLUSION ROBUSTNESS BY TRACK")
    print(THIN)
    print(f"{'TRACK':12s} {'VERDICT':10s} {'CLASS':13s} WHY")
    print(THIN)
    order = {"FRAGILE": 0, "CONDITIONAL": 1, "ROBUST": 2}
    rows = sorted(
        data["classification"].items(),
        key=lambda kv: (order.get(kv[1]["classification"], 9), kv[0]),
    )
    for track, c in rows:
        reasons = c["fragile_because"] or c["conditional_because"]
        first = reasons[0] if reasons else LABEL_GLOSS[c["classification"]]
        print(f"{track:12s} {c['recommendation'].upper():10s} {c['classification']:13s} {first}")
        for r in reasons[1:]:
            print(f"{'':36s}{r}")
    print(THIN)
    for label, gloss in LABEL_GLOSS.items():
        print(f"  {label:12s} = {gloss}")


def _print_contested(data: dict) -> None:
    c = data["contested_flag_sensitivity"]
    print()
    print("1. CONTESTED-FLAG SENSITIVITY  (the decisive assumption)")
    print(THIN)
    print(f"baseline contested dimensions: {', '.join(c['baseline_contested_slots'])}")
    print()
    for line in c["headline"]:
        print(f"  * {line}")
    print()
    variant_names = sorted(
        {n for t in c["per_track"].values() for n in t["named_variants"]}
    )
    head = f"{'TRACK':12s} {'BASELINE':10s}" + "".join(f"{n[:15]:16s}" for n in variant_names)
    print(head)
    print(THIN)
    for track, t in sorted(c["per_track"].items()):
        row = f"{track:12s} {t['baseline_recommendation'].upper():10s}"
        for n in variant_names:
            v = t["named_variants"].get(n, "-")
            mark = " " if v == t["baseline_recommendation"] else "*"
            row += f"{mark + v.upper():16s}"
        print(row)
    print("  (* = differs from the baseline verdict)")
    print()
    print(f"{'TRACK':12s} {'RANDOM REASSIGNMENT OF THE SAME NUMBER OF FLAGS':60s} PRESERVED")
    print(THIN)
    for track, t in sorted(c["per_track"].items()):
        dist = t["random_reassignment"]
        spread = ", ".join(f"{k}={v}" for k, v in dist["counts"].items())
        frac = t["fraction_of_random_seeds_preserving_baseline"]
        print(f"{track:12s} {spread:60s} {frac:.0%} of {dist['n_seeds']}")


def _print_thresholds(data: dict) -> None:
    t = data["threshold_sensitivity"]
    print()
    print("2. THRESHOLD SENSITIVITY")
    print(THIN)
    print(
        f"{t['n_threshold_track_pairs']} threshold x track sweeps; "
        f"{t['n_fragile']} FRAGILE (configured value within "
        f"{FRAGILITY_BAND:.0%} of a flip point)."
    )
    if not t["fragile"]:
        print("  No threshold sits inside its fragility band.")
    else:
        print()
        print(f"{'THRESHOLD':46s} {'TRACK':11s} {'SET':>9s} {'FLIPS AT':>9s} {'GAP':>7s}  CHANGES")
        print(THIN)
        for f in t["fragile"]:
            print(
                f"{f['threshold'][:45]:46s} {f['track']:11s} "
                f"{f['configured_value']:9.4f} {f['flips_at']:9.4f} "
                f"{f['relative_distance']:6.1%}  {','.join(f['changed'])}"
            )
    rec_flippers = t["thresholds_that_can_flip_a_recommendation"]
    print()
    if rec_flippers:
        print("Thresholds that can flip a RECOMMENDATION somewhere in their swept range:")
        for name, track in rec_flippers:
            entry = next(
                (r for r in t["results"] if r["threshold"] == name and r["track"] == track), None
            )
            if entry is None:  # pragma: no cover - defensive
                continue
            print(
                f"  {name[:52]:53s} {track:11s} set={entry['configured_value']} "
                f"flips at {entry['recommendation_flip_at']} "
                f"({entry['recommendation_flip_distance']:.0%} away): "
                f"{entry['baseline_outcome']['recommendation']} -> "
                f"{entry['recommendation_flip_to']}"
            )
    else:
        print("No swept threshold flips any track's recommendation.")


def _print_noise(data: dict) -> None:
    n = data["noise_sensitivity"]
    print()
    print("3. NOISE MULTIPLIER SENSITIVITY  (annotation/pool.py::_observe)")
    print(THIN)
    for param in ("global_noise_multiplier", "contested_multiplier"):
        block = n[param]
        print(
            f"{param} (configured {block['configured_value']}, swept "
            f"{block['grid'][0]}..{block['grid'][-1]})"
        )
        for track, st in sorted(block["stability"].items()):
            if st["stable_over_full_range"]:
                print(f"  {track:12s} {st['baseline_recommendation'].upper():9s} "
                      "stable across the whole range")
            else:
                trans = "; ".join(
                    f"{x['from']}->{x['to']} between {x['between'][0]} and {x['between'][1]}"
                    for x in st["transitions"]
                )
                print(f"  {track:12s} {st['baseline_recommendation'].upper():9s} {trans}")
        print()


def _print_loo(data: dict) -> None:
    loo = data["leave_one_annotator_out"]
    print("4. LEAVE-ONE-ANNOTATOR-OUT AT THE VERDICT LEVEL")
    print(THIN)
    print(f"reference run uses n_batches={loo['n_batches']} (see method note in the JSON).")
    deps = loo["single_annotator_dependencies"]
    if not deps:
        print("  No track's recommendation depends on any single annotator.")
    else:
        for d in deps:
            print(
                f"  {d['track']:12s} drops to {d['recommendation_without'].upper()} "
                f"(from {d['recommendation_with_full_roster'].upper()}) without "
                f"{d['annotator']}; alpha {d['alpha_mean_with']} -> {d['alpha_mean_without']}"
            )


def _print_limitations(data: dict) -> None:
    print()
    print("LIMITATIONS OF THIS ANALYSIS")
    print(THIN)
    for lim in data["limitations"]:
        print(f"  - {lim}")
    print()
    print(RULE)
    print(
        "This is a reporting tool and always exits 0. FRAGILE is not a failure; "
        "it is a statement\nabout how much weight a number can carry."
    )
    print(RULE)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default="results", help="results directory (default: results)")
    ap.add_argument("--seeds", type=int, default=20,
                    help="random contested-flag reassignments (default: 20)")
    ap.add_argument("--track", action="append", default=[],
                    help="restrict to a track key; repeatable")
    ap.add_argument("--reuse", action="store_true",
                    help="read an existing sensitivity.json instead of recomputing")
    ap.add_argument("--quiet", action="store_true", help="suppress progress logging")
    args = ap.parse_args(argv)

    data = _load_or_run(args)

    _print_header(data)
    _print_classification(data)
    _print_contested(data)
    _print_thresholds(data)
    _print_noise(data)
    _print_loo(data)
    _print_limitations(data)
    print(f"\nFull detail: {Path(args.results) / 'sensitivity.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
