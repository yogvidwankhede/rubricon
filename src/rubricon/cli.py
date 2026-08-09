"""Command line interface.

    rubricon tracks                 list registered tracks and their depth tier
    rubricon run [--track K]        full pipeline; writes results/
    rubricon gate [--track K]       show the claim ledger with verdicts
    rubricon decide                 portfolio invest/iterate/stop table
    rubricon report                 render the markdown report and HTML dashboard
    rubricon rubric K               print a rubric with all anchors
    rubricon validate               self-check statistics against reference values
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(results: Path) -> dict:
    p = results / "portfolio.json"
    if not p.exists():
        print(f"No results at {p}. Run 'rubricon run' first.", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_tracks(args) -> int:
    from .tracks import DEPTH_CONTRACT, all_tracks

    for t in all_tracks():
        s = t.spec
        print(f"{s.key:12s} [{s.depth:12s}] n={s.target_n:3d} x{s.replication} "
              f"dims={len(s.rubric.dimensions)} codes={len(s.failure_codes):2d}  {s.name}")
        print(f"{'':14s}Q: {s.research_question}")
        print(f"{'':14s}Contract: {DEPTH_CONTRACT.get(s.depth, '')[:100]}")
    return 0


def cmd_run(args) -> int:
    from .pipeline import run_all

    out = run_all(args.results, tracks=[args.track] if args.track else None)
    s = out["summary"]
    print(f"\n{s['simulation_notice']}\n")
    print(f"tracks={s['n_tracks']} items={s['n_items']} responses={s['n_responses']} "
          f"annotations={s['n_annotations']} dimensions={s['n_dimensions']}")
    print(f"claims submitted={s['claims_submitted']} blocked={s['claims_blocked']} "
          f"({s['block_rate']:.0%})")
    print()
    for k, t in out["tracks"].items():
        print(f"  {k:12s} alpha={t['alpha_mean']:.3f}  gold={t['gold_accuracy']:.3f}  "
              f"-> {t['decision']['recommendation'].upper()}")
    print(f"\nArtifacts written to {args.results}/")
    return 0


def cmd_gate(args) -> int:
    data = _load(Path(args.results))
    tracks = {args.track: data["tracks"][args.track]} if args.track else data["tracks"]
    icon = {"pass": "PASS ", "warn": "WARN ", "block": "BLOCK"}
    for k, t in tracks.items():
        print(f"\n=== {k} [{t['depth']}] "
              f"{t['gate']['summary']['by_verdict']} ===")
        for c in t["gate"]["claims"]:
            print(f"  [{icon[c['verdict']]}] {c['text']}")
            for r in c["blocking_reasons"]:
                print(f"           BLOCKED: {r}")
            if args.verbose:
                for w in c["warnings"]:
                    print(f"           warn:    {w}")
    return 0


def cmd_decide(args) -> int:
    data = _load(Path(args.results))
    print(f"{'TRACK':12s} {'DEPTH':13s} {'ALPHA':>6s} {'GOLD':>6s} {'IRRED':>6s}  RECOMMENDATION")
    print("-" * 96)
    for k, t in data["tracks"].items():
        d = t["decision"]
        irr = d["irreducible_share"]
        print(f"{k:12s} {t['depth']:13s} {t['alpha_mean']:6.3f} "
              f"{(t['gold_accuracy'] or 0):6.3f} {(irr if irr is not None else 0):6.3f}  "
              f"{d['recommendation'].upper()}")
        print(f"  {d['headline']}")
        for a in d["next_actions"]:
            print(f"    - {a}")
        print()
    return 0


def cmd_report(args) -> int:
    from .report.render import render_all

    data = _load(Path(args.results))
    paths = render_all(data, Path(args.results))
    for p in paths:
        print(f"wrote {p}")
    return 0


def cmd_rubric(args) -> int:
    from .tracks import get

    spec = get(args.track).spec
    r = spec.rubric
    print(f"{r.name}  ({r.version})")
    print(f"{r.description}\n")
    for d in r.dimensions:
        crit = "  [CRITICAL, gate<=%s]" % d.critical_threshold if d.critical else ""
        print(f"--- {d.key}  ({d.scale.value}, levels {list(d.levels)}, w={d.weight}){crit}")
        print(f"    Q: {d.question}")
        for a in d.anchors:
            print(f"      {a.value} = {a.label}: {a.description}")
            if a.example:
                print(f"          e.g. {a.example[:150]}")
        if d.notes:
            print(f"    note: {d.notes}")
        print()
    return 0


def cmd_validate(args) -> int:
    """Self-check the statistics against published reference values."""
    from .stats.agreement import krippendorff_alpha

    obs = {
        "A": [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None],
        "B": [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3],
        "C": [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None],
        "D": [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None],
    }
    data = {
        str(u): {a: v[u] for a, v in obs.items() if v[u] is not None} for u in range(12)
    }
    expected = {"nominal": 0.743, "ordinal": 0.815, "interval": 0.849, "ratio": 0.797}
    ok = True
    print("Krippendorff (2011) reference dataset, 12 units x 4 observers with missing data:")
    for metric, exp in expected.items():
        got = krippendorff_alpha(data, metric).value
        good = abs(got - exp) < 0.002
        ok &= good
        print(f"  {metric:9s} computed={got:.4f}  published={exp:.3f}  "
              f"{'OK' if good else 'MISMATCH'}")
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("rubricon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", default="results", help="results directory")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tracks", help="list registered tracks").set_defaults(fn=cmd_tracks)

    r = sub.add_parser("run", help="run the full pipeline")
    r.add_argument("--track", help="limit to one track")
    r.set_defaults(fn=cmd_run)

    g = sub.add_parser("gate", help="show the claim ledger")
    g.add_argument("--track")
    g.add_argument("-v", "--verbose", action="store_true")
    g.set_defaults(fn=cmd_gate)

    sub.add_parser("decide", help="portfolio recommendations").set_defaults(fn=cmd_decide)
    sub.add_parser("report", help="render report + dashboard").set_defaults(fn=cmd_report)

    rb = sub.add_parser("rubric", help="print a rubric with anchors")
    rb.add_argument("track")
    rb.set_defaults(fn=cmd_rubric)

    sub.add_parser("validate", help="check stats against published values").set_defaults(
        fn=cmd_validate
    )

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
