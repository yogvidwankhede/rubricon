"""Verdict sensitivity: which conclusions survive their assumptions.

Why this module exists
======================

An adversarial reviewer read this repository and found the weakness that
matters most: several headline conclusions are readouts of hand-set parameters.

* ``annotation/effects.py`` marks three ``refusal`` dimensions ``contested:
  True`` by hand. Flipping those three booleans to ``False``, and setting three
  ``agentic`` dimensions to ``True``, moved ``refusal`` from STOP to ITERATE and
  ``agentic`` from INVEST to ITERATE. Two headline verdicts invert on six
  characters of source.
* ``gates/decision.py`` cuts sit close to observed values, and the engineering
  log records one cut being loosened *after* it declined to produce the expected
  verdict.
* ``gates/signal.py`` sets ``max_flagged_annotator_fraction = 0.34`` against an
  observed 0.333, and ``redteam/probes.py`` sets a shortcut threshold of 0.93
  against an observed maximum of 0.9225.

The wrong response is to hide any of that. A conclusion that depends on an
assumption is not thereby worthless -- every conclusion depends on assumptions --
but a conclusion whose dependence is *undisclosed* is worthless, because the
reader cannot price it. The professional response is to perturb every assumption
we can name, publish which conclusions move, and label the ones that move as
conditional rather than established.

Four analyses, in decreasing order of how much they threaten the portfolio:

1. :func:`contested_flag_sensitivity` -- the decisive assumption. Re-runs the
   whole annotation chain under perturbed ``contested`` flags. This is the one
   that answers "is the STOP verdict a finding or a construction?".
2. :func:`threshold_sensitivity` -- sweeps every numeric ``GatePolicy`` field and
   every hard-coded comparison cut in ``gates/decision.py``, locating the exact
   value at which each track's verdict flips, and flagging any cut sitting within
   5% of its own flip point as FRAGILE.
3. :func:`noise_sensitivity` -- sweeps the two simulator multipliers (the global
   0.70 and the contested 2.60) that set how much disagreement exists at all.
4. :func:`leave_one_annotator_out` -- re-derives every verdict with each
   annotator removed, to find recommendations resting on one person.

Design constraints honoured here
--------------------------------

**No forked copy of the chain.** Every perturbed run goes through the real
``pipeline.run_track``. The alternative -- a lighter reimplementation of
annotate/agree/gate/decide -- would drift from production the first time anyone
touched either copy, and a sensitivity analysis that measures a stale replica is
worse than none. The cost is roughly 0.7s per track-run, which the caching here
keeps inside a few minutes for the whole suite.

**No forked copy of the decision cuts.** The cuts in ``gates/decision.py`` are
inline literals, so they cannot be swept by passing a parameter. Rather than
transcribe the engine's control flow into this module (which would silently rot),
:func:`discover_decision_cuts` parses ``decision.py``, finds every numeric literal
used in a comparison inside ``recommend()``, and :func:`_decision_module_with`
recompiles the module with one literal substituted. The swept engine is therefore
always the real engine, including any cut added after this file was written.

**Evidence is captured, not recomputed.** ``threshold_sensitivity`` needs to
re-gate a track under hundreds of policies. Re-running the chain each time would
be absurd, and rebuilding the gate inputs by hand would duplicate
``pipeline.run_track``. Instead :class:`Chain` wraps ``pipeline.build_claims``
and ``pipeline.recommend`` during a single baseline run and keeps the exact
arguments they were called with, so re-gating is a pure function of cached
evidence.

Interpreting the output
-----------------------

``results/sensitivity.json`` classifies each conclusion as:

* **ROBUST** -- unchanged under every perturbation applied here.
* **CONDITIONAL** -- unchanged under most, but a namable perturbation moves it.
  Report it with the condition attached.
* **FRAGILE** -- moves under a perturbation small enough that the choice of
  parameter, rather than the data, is doing the work. Do not report it as a
  finding.

None of these labels is a pass or a fail. FRAGILE is not an accusation of bad
faith; it is a statement about how much weight a number can carry.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import importlib.util
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from unittest import mock

from ..annotation import pool as pool_mod
from ..annotation.effects import DIMENSION_PROPERTIES, property_overrides
from ..core.store import Store
from .decision import DecisionInput
from .signal import GatePolicy, SignalGate, policy_for_depth

# The simulator multipliers this analysis sweeps. These MUST match the literals
# in ``annotation/pool.py::_observe``; :func:`verify_observe_replica` asserts it
# by comparing a full annotation pass against the unpatched function.
DEFAULT_GLOBAL_NOISE_MULTIPLIER = 0.70
DEFAULT_CONTESTED_MULTIPLIER = 2.60

#: Bisection tolerance when locating a flip point on a continuous threshold.
FLIP_TOLERANCE = 1e-4

#: A cut whose flip point sits within this relative distance of its configured
#: value is FRAGILE: the value chosen, not the evidence, decides the verdict.
FRAGILITY_BAND = 0.05


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------


_T0 = time.time()
_VERBOSE = True


def log(message: str) -> None:
    """Progress line on stderr.

    Sensitivity runs are minutes long and mostly silent; a run that prints
    nothing is indistinguishable from a run that hung, and the usual response to
    that is to kill it and never find out what it would have said.
    """
    if _VERBOSE:
        print(f"[sensitivity {time.time() - _T0:7.1f}s] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# a store that writes nothing
# --------------------------------------------------------------------------


class NullStore(Store):
    """A :class:`Store` that discards writes.

    A sensitivity suite performs several hundred pipeline runs. Each one writes
    about a megabyte of JSONL that nobody will ever read, and writing it would
    both dominate the runtime and risk clobbering the real ``results/``
    directory if a path were ever passed in by mistake. Reads are not supported
    because nothing in the chain reads back what it wrote.
    """

    def __init__(self) -> None:  # noqa: D107 - deliberately bypasses mkdir
        self.root = Path("/dev/null-sensitivity")

    def write_jsonl(self, name: str, rows: Iterable[Any]) -> Path:  # type: ignore[override]
        for _ in rows:  # consume generators so laziness cannot hide an error
            pass
        return self.root / name

    def write_json(self, name: str, obj: Any) -> Path:  # type: ignore[override]
        return self.root / name


# --------------------------------------------------------------------------
# parameterised replica of pool._observe
# --------------------------------------------------------------------------


def make_observe(
    global_noise_multiplier: float = DEFAULT_GLOBAL_NOISE_MULTIPLIER,
    contested_multiplier: float = DEFAULT_CONTESTED_MULTIPLIER,
) -> Callable[..., int]:
    """Build a drop-in replacement for ``pool._observe`` with injectable multipliers.

    ``pool._observe`` hard-codes two numbers that jointly set how much
    disagreement the simulated pool exhibits: a global 0.70 noise scale ("this
    pool has been anchored and read the anchors") and a 2.60 contested scale
    ("how far apart stable value positions push two annotators"). Neither is
    estimated from anything. Both deserve a sweep.

    They are replicated here rather than parameterised in ``pool.py`` because
    this analysis must not perturb the module it is measuring. The replica is
    kept honest by :func:`verify_observe_replica`, which patches it in at the
    default multipliers and asserts the resulting annotations are identical --
    every score, every response, every annotator -- to the unpatched run. If
    anyone edits ``_observe``, that check fails loudly instead of this module
    quietly measuring a formula production no longer uses.
    """

    def _observe(
        latent: float,
        dim_lo: float,
        dim_hi: float,
        noise: float,
        contested: bool,
        ann: Any,
        rng: random.Random,
        position_in_batch: int,
        is_gold: bool,
    ) -> int:
        span_factor = (dim_hi - dim_lo) / 3.0
        sigma = (
            global_noise_multiplier * noise * (1.6 - ann.competence)
            + ann.fatigue_rate * position_in_batch
        )
        draw = (
            latent
            + rng.gauss(0.0, max(0.03, sigma * span_factor))
            + ann.bias * span_factor
        )
        if contested and not is_gold:
            draw += ann.value_position * noise * contested_multiplier * span_factor
        return int(max(dim_lo, min(dim_hi, round(draw))))

    return _observe


def verify_observe_replica(track_key: str = "refusal") -> bool:
    """Assert the replica reproduces ``pool._observe`` exactly at default settings.

    Returns True on success and raises otherwise. Called once at the top of every
    sensitivity run so that a drifted replica fails the run rather than silently
    poisoning the noise sweep.
    """
    from ..tracks import get

    track = get(track_key)
    items = track.items()
    responses = track.responses()
    reference = [a.to_dict() for a in pool_mod.annotate(track.spec, items, responses)]
    with mock.patch.object(pool_mod, "_observe", make_observe()):
        replica = [a.to_dict() for a in pool_mod.annotate(track.spec, items, responses)]
    if reference != replica:
        raise AssertionError(
            "gates.sensitivity.make_observe no longer reproduces "
            "annotation.pool._observe at the default multipliers "
            f"({DEFAULT_GLOBAL_NOISE_MULTIPLIER}, {DEFAULT_CONTESTED_MULTIPLIER}). "
            "The noise sweep would be measuring a formula the pipeline does not "
            "use. Re-sync make_observe with pool._observe before trusting any "
            "noise-sensitivity output."
        )
    return True


# --------------------------------------------------------------------------
# contested-flag perturbations
# --------------------------------------------------------------------------


def _all_dimension_slots() -> list[tuple[str, str]]:
    """Every (track, dimension) pair, in a deterministic order."""
    return [
        (track, dim)
        for track in sorted(DIMENSION_PROPERTIES)
        for dim in sorted(DIMENSION_PROPERTIES[track])
    ]


def baseline_contested_slots() -> list[tuple[str, str]]:
    return [
        (t, d)
        for (t, d) in _all_dimension_slots()
        if DIMENSION_PROPERTIES[t][d].get("contested")
    ]


def properties_with_contested(slots: Iterable[tuple[str, str]]) -> dict:
    """A full ``DIMENSION_PROPERTIES`` table whose contested set is exactly ``slots``.

    Noise values are untouched: this isolates the contested flag, which is the
    variable under test. Perturbing noise at the same time would confound "the
    verdict depends on which dimensions we called contested" with "the verdict
    depends on how noisy we said they were", and those have different remedies.
    """
    wanted = set(slots)
    table = copy.deepcopy(DIMENSION_PROPERTIES)
    for track, dims in table.items():
        for dim, props in dims.items():
            props["contested"] = (track, dim) in wanted
    return table


def contested_configurations(n_seeds: int = 20, seed0: int = 20260808) -> dict[str, dict]:
    """The perturbed contested-flag tables to evaluate, keyed by configuration name.

    Includes the reviewer's exact edit (``reviewer_swap``) alongside the extreme
    configurations and the randomised ones. The randomisation holds the TOTAL
    number of contested flags constant across the portfolio, so the comparison
    isolates *which* dimensions were called contested from *how many* were -- a
    sweep that also varied the count would confound the two and could not answer
    "would agentic have stopped if we had pointed the flags at it instead?".
    """
    slots = _all_dimension_slots()
    base = baseline_contested_slots()
    n_contested = len(base)

    configs: dict[str, dict] = {
        "baseline": properties_with_contested(base),
        "all_off": properties_with_contested([]),
        "all_on": properties_with_contested(slots),
        "refusal_off": properties_with_contested([s for s in base if s[0] != "refusal"]),
        "agentic_all_on": properties_with_contested(
            base + [s for s in slots if s[0] == "agentic"]
        ),
    }

    # The reviewer's edit, reproduced: refusal's three flags cleared, three
    # agentic dimensions set. The three agentic dimensions chosen are the three
    # highest-noise ones, because those are the ones a reviewer arguing "these
    # are contested too" would reach for -- efficiency ("redundant is partly
    # taste"), error_recovery, and state_tracking.
    agentic_by_noise = sorted(
        DIMENSION_PROPERTIES["agentic"],
        key=lambda d: (-float(DIMENSION_PROPERTIES["agentic"][d]["noise"]), d),
    )[:3]
    configs["reviewer_swap"] = properties_with_contested(
        [s for s in base if s[0] != "refusal"]
        + [("agentic", d) for d in agentic_by_noise]
    )

    for i in range(n_seeds):
        rng = random.Random(seed0 + i)
        configs[f"random_{i:02d}"] = properties_with_contested(
            rng.sample(slots, n_contested)
        )
    return configs


# --------------------------------------------------------------------------
# cached pipeline runs
# --------------------------------------------------------------------------


@dataclass
class RunEvidence:
    """One perturbed pipeline run, reduced to what the analyses consume."""

    track: str
    depth: str
    recommendation: str
    alpha_mean: float
    alpha_min: float
    gold_accuracy: float | None
    verdicts: dict[str, int]
    contested_dimensions: list[str]
    decision_input: DecisionInput
    build_claims_args: tuple[tuple, dict]

    def verdict_tuple(self) -> tuple[int, int, int]:
        return (
            int(self.verdicts.get("pass", 0)),
            int(self.verdicts.get("warn", 0)),
            int(self.verdicts.get("block", 0)),
        )

    def summary(self) -> dict:
        return {
            "track": self.track,
            "recommendation": self.recommendation,
            "alpha_mean": round(self.alpha_mean, 4) if not math.isnan(self.alpha_mean) else None,
            "alpha_min": round(self.alpha_min, 4) if not math.isnan(self.alpha_min) else None,
            "gold_accuracy": self.gold_accuracy,
            "verdicts": dict(self.verdicts),
            "contested_dimensions": list(self.contested_dimensions),
        }


class Chain:
    """Runs (and caches) the real pipeline under a named perturbation.

    Caching is the difference between a ten-minute suite and an hour-long one:
    the contested, noise, and leave-one-out analyses all want the unperturbed
    baseline, several want the same track twice, and ``threshold_sensitivity``
    wants the baseline evidence hundreds of times.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple, RunEvidence] = {}
        self.n_runs = 0

    # -- the one place a pipeline run happens ------------------------------

    def run(
        self,
        track_key: str,
        *,
        properties: Mapping | None = None,
        properties_id: str = "default",
        global_noise_multiplier: float = DEFAULT_GLOBAL_NOISE_MULTIPLIER,
        contested_multiplier: float = DEFAULT_CONTESTED_MULTIPLIER,
        drop_annotator: str | None = None,
        n_batches: int = 5,
    ) -> RunEvidence:
        key = (
            track_key,
            properties_id,
            round(global_noise_multiplier, 6),
            round(contested_multiplier, 6),
            drop_annotator,
            n_batches,
        )
        if key in self._cache:
            return self._cache[key]

        from .. import pipeline
        from ..tracks import get

        track = get(track_key)
        captured: dict[str, Any] = {}

        real_build_claims = pipeline.build_claims
        real_recommend = pipeline.recommend
        real_annotate = pipeline.annotate

        def _capture_build_claims(*args, **kwargs):
            captured["build_claims"] = (args, kwargs)
            return real_build_claims(*args, **kwargs)

        def _capture_recommend(*args, **kwargs):
            for candidate in list(args) + list(kwargs.values()):
                if isinstance(candidate, DecisionInput):
                    captured["decision_input"] = candidate
                    break
            return real_recommend(*args, **kwargs)

        def _restricted_annotate(spec, items, responses, **kwargs):
            roster = [a for a in pool_mod.ROSTER if a.annotator_id != drop_annotator]
            kwargs.setdefault("annotators", roster)
            kwargs.setdefault("n_batches", n_batches)
            return real_annotate(spec, items, responses, **kwargs)

        patches = [
            mock.patch.object(pipeline, "build_claims", _capture_build_claims),
            mock.patch.object(pipeline, "recommend", _capture_recommend),
            mock.patch.object(
                pool_mod,
                "_observe",
                make_observe(global_noise_multiplier, contested_multiplier),
            ),
        ]
        if drop_annotator is not None or n_batches != 5:
            patches.append(mock.patch.object(pipeline, "annotate", _restricted_annotate))

        with property_overrides(properties):
            for p in patches:
                p.start()
            try:
                payload = pipeline.run_track(track, NullStore())
            finally:
                for p in reversed(patches):
                    p.stop()

        self.n_runs += 1
        evidence = RunEvidence(
            track=track_key,
            depth=payload["depth"],
            recommendation=payload["decision"]["recommendation"],
            alpha_mean=float(payload["alpha_mean"]),
            alpha_min=float(payload["alpha_min"]),
            gold_accuracy=payload.get("gold_accuracy"),
            verdicts=dict(payload["gate"]["summary"]["by_verdict"]),
            contested_dimensions=list(payload.get("contested_dimensions") or []),
            decision_input=captured.get("decision_input"),
            build_claims_args=captured.get("build_claims", ((), {})),
        )
        self._cache[key] = evidence
        return evidence

    def baseline(self, track_key: str) -> RunEvidence:
        return self.run(track_key)

    # -- cheap re-derivations from cached evidence -------------------------

    def regate(self, evidence: RunEvidence, policy: GatePolicy) -> dict[str, list[int]]:
        """Re-run the claim ledger under a different policy. No re-annotation.

        Replays ``pipeline.build_claims`` with the exact arguments the real run
        used, substituting only the :class:`SignalGate`. Because the gate object
        is located by type rather than by position, this keeps working if the
        signature of ``build_claims`` changes.

        Returns BOTH claim-level and check-level verdict counts, and the
        distinction is load-bearing. A claim's verdict is the worst of its
        checks, so a threshold change that moves one check from PASS to WARN
        inside a claim that some other check already BLOCKs is invisible at the
        claim level. ``max_flagged_annotator_fraction = 0.34`` against an
        observed 0.333 is exactly that case: lowering it flips the
        ``annotator_pool`` check on every measurement and ranking claim, and not
        one claim verdict moves. Measuring only claim verdicts would report that
        threshold as perfectly stable, which is the opposite of true.
        """
        from .. import pipeline
        from ..core.schema import Verdict

        args, kwargs = evidence.build_claims_args
        new_gate = SignalGate(policy, depth=evidence.depth)
        args = tuple(new_gate if isinstance(a, SignalGate) else a for a in args)
        kwargs = {k: (new_gate if isinstance(v, SignalGate) else v) for k, v in kwargs.items()}
        ledger = pipeline.build_claims(*args, **kwargs)
        by = ledger.summary()["by_verdict"]
        checks = {"pass": 0, "warn": 0, "block": 0}
        for claim in ledger.claims:
            for check in claim.checks:
                v = check.verdict.value if isinstance(check.verdict, Verdict) else str(check.verdict)
                checks[v] = checks.get(v, 0) + 1
        return {
            "claims": [int(by["pass"]), int(by["warn"]), int(by["block"])],
            "checks": [checks["pass"], checks["warn"], checks["block"]],
        }


# --------------------------------------------------------------------------
# decision-engine cut discovery
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionCut:
    """A numeric literal used as a comparison cut inside ``decision.recommend``."""

    cut_id: str
    expression: str
    value: float
    lineno: int
    col_offset: int
    end_col_offset: int

    @property
    def is_integral(self) -> bool:
        return isinstance(self.value, int) and not isinstance(self.value, bool)


def _decision_source_path() -> Path:
    from . import decision

    return Path(decision.__file__)


def discover_decision_cuts() -> list[DecisionCut]:
    """Find every hard-coded comparison cut in ``decision.recommend``.

    Parsing beats transcription here. The alternative is a hand-maintained list
    of the engine's magic numbers, which is wrong the moment somebody adds one --
    and adding one is exactly the event a sensitivity analysis needs to notice.
    Anything compared against a numeric literal inside ``recommend()`` is a cut,
    including literals nested in generator expressions (the ``< 0.40`` broken-
    dimension test) and in boolean conjunctions.

    Two spellings of a cut are found:

    * a numeric literal used directly as a comparison operand
      (``inp.rubric_gap_rate > 0.15``);
    * a local named constant bound to a numeric literal and then compared
      against (``POOL_FLAG_CEILING = 0.50`` ... ``frac > POOL_FLAG_CEILING``).
      Missing the second spelling would mean a cut silently drops out of the
      analysis the moment somebody does the good thing and names it.

    Numeric literals that are NOT comparison operands (list slices, the ``8 *
    n_items`` HOLD multiple, cost arithmetic) are deliberately out of scope: they
    do not define a verdict boundary, so "the value at which the verdict flips"
    is not meaningful for them. They are reported under ``unswept_literals`` in
    the output rather than silently dropped. Cuts whose configured value is zero
    are also skipped: a relative sweep around zero is undefined, and a
    ``> 0`` guard is a degeneracy check rather than a tunable threshold.
    """
    tree = ast.parse(_decision_source_path().read_text(encoding="utf-8"))
    target = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "recommend":
            target = node
            break
    if target is None:  # pragma: no cover - decision.py always defines recommend
        raise RuntimeError("gates/decision.py no longer defines recommend()")

    cuts: list[DecisionCut] = []
    seen: set[tuple[int, int]] = set()

    def _add(const: ast.Constant, expr: str) -> None:
        if not isinstance(const.value, (int, float)) or isinstance(const.value, bool):
            return
        if const.value == 0:
            return
        pos = (const.lineno, const.col_offset)
        if pos in seen:
            return
        seen.add(pos)
        cuts.append(
            DecisionCut(
                cut_id=f"decision.L{const.lineno}:{expr}",
                expression=expr,
                value=const.value,
                lineno=const.lineno,
                col_offset=const.col_offset,
                end_col_offset=const.end_col_offset or const.col_offset,
            )
        )

    # Names compared against anywhere in the function.
    compared_names: set[str] = set()
    for node in ast.walk(target):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if isinstance(operand, ast.Name):
                    compared_names.add(operand.id)

    for node in ast.walk(target):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if isinstance(operand, ast.Constant):
                    _add(operand, ast.unparse(node))
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            for name in names:
                if name in compared_names:
                    _add(node.value, f"{name} = {ast.unparse(node.value)}")

    return sorted(cuts, key=lambda c: (c.lineno, c.col_offset))


def unswept_decision_literals() -> list[dict]:
    """Numeric literals in ``recommend()`` that are not comparison cuts.

    Reported for transparency. A reader who wonders "did they sweep the 8x HOLD
    multiple?" should be able to answer it from the output rather than from the
    source.
    """
    tree = ast.parse(_decision_source_path().read_text(encoding="utf-8"))
    target = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "recommend"), None
    )
    if target is None:  # pragma: no cover
        return []
    in_compare: set[tuple[int, int]] = set()
    for node in ast.walk(target):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if isinstance(operand, ast.Constant):
                    in_compare.add((operand.lineno, operand.col_offset))
    out = []
    for node in ast.walk(target):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            if (node.lineno, node.col_offset) in in_compare:
                continue
            out.append({"line": node.lineno, "value": node.value})
    return out


class _ConstantSwap(ast.NodeTransformer):
    def __init__(self, lineno: int, col_offset: int, new_value: float) -> None:
        self.lineno = lineno
        self.col_offset = col_offset
        self.new_value = new_value
        self.hits = 0

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # noqa: N802
        if node.lineno == self.lineno and node.col_offset == self.col_offset:
            self.hits += 1
            return ast.copy_location(ast.Constant(value=self.new_value), node)
        return node


_DECISION_MODULE_CACHE: dict[tuple[str, float], Any] = {}
_DECISION_CACHE_LIMIT = 256
_DECISION_SOURCE_CACHE: dict[str, ast.Module] = {}
_SWEPT_MODULE_COUNTER = [0]


def _decision_module_with(cut: DecisionCut, new_value: float):
    """Recompile ``gates/decision.py`` with one cut replaced.

    This is what makes the decision-cut sweep faithful: the swept engine is the
    production engine with a single literal changed, not a paraphrase of it.

    The recompiled module is registered in ``sys.modules`` only for the duration
    of its own execution, under a unique throwaway name. That registration is
    unavoidable rather than incidental: ``@dataclass`` resolves annotations via
    ``sys.modules[cls.__module__]`` while the class body is being processed, and
    a module absent from ``sys.modules`` raises there. It is removed immediately
    afterwards so the production ``rubricon.gates.decision`` remains the only
    decision engine any other caller can reach.
    """
    cache_key = (cut.cut_id, round(float(new_value), 12))
    cached = _DECISION_MODULE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    path = _decision_source_path()
    source_key = str(path)
    if source_key not in _DECISION_SOURCE_CACHE:
        _DECISION_SOURCE_CACHE[source_key] = ast.parse(path.read_text(encoding="utf-8"))
    tree = copy.deepcopy(_DECISION_SOURCE_CACHE[source_key])

    swapper = _ConstantSwap(cut.lineno, cut.col_offset, new_value)
    tree = swapper.visit(tree)
    if swapper.hits != 1:
        raise RuntimeError(
            f"expected exactly one literal at {path.name}:{cut.lineno}:{cut.col_offset} "
            f"for cut {cut.cut_id!r}, replaced {swapper.hits}"
        )
    ast.fix_missing_locations(tree)

    _SWEPT_MODULE_COUNTER[0] += 1
    name = f"rubricon.gates._decision_swept_{_SWEPT_MODULE_COUNTER[0]}"
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "rubricon.gates"
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        exec(compile(tree, str(path), "exec"), module.__dict__)  # noqa: S102
    finally:
        sys.modules.pop(name, None)

    if len(_DECISION_MODULE_CACHE) >= _DECISION_CACHE_LIMIT:
        # Plain FIFO eviction. Bisection walks monotonically toward a boundary,
        # so recently compiled values are the ones about to be reused; anything
        # older is a value the search has already moved past.
        for k in list(_DECISION_MODULE_CACHE)[: _DECISION_CACHE_LIMIT // 2]:
            _DECISION_MODULE_CACHE.pop(k, None)
    _DECISION_MODULE_CACHE[cache_key] = module
    return module


# --------------------------------------------------------------------------
# sweep machinery
# --------------------------------------------------------------------------


def sweep_values(default: float, *, integral: bool = False,
                 lo_clip: float | None = None, hi_clip: float | None = None) -> list[float]:
    """Candidate threshold values: relative steps plus nearby round numbers.

    The relative steps (+/- 10/20/30%) answer "is this cut in a stable region?".
    The round numbers answer a different and more pointed question: "would a
    reasonable person have picked a different value?". 0.34 and 0.35 are equally
    defensible a priori; if the verdict differs between them, the verdict is
    about the choice and not about the pool.
    """
    if integral:
        span = max(1, int(round(abs(default) * 0.5)))
        cands = {int(default) + d for d in range(-max(2, span), max(2, span) + 1)}
        cands = {c for c in cands if c >= 0}
        if lo_clip is not None:
            cands = {c for c in cands if c >= lo_clip}
        if hi_clip is not None:
            cands = {c for c in cands if c <= hi_clip}
        cands.add(int(default))
        return sorted(cands)

    cands: set[float] = {float(default)}
    for pct in (-0.30, -0.20, -0.10, 0.10, 0.20, 0.30):
        cands.add(round(default * (1.0 + pct), 6))
    # Round numbers: 0.05 granularity out to +/-50%, 0.01 granularity within +/-10%.
    step_specs = ((0.05, 0.5), (0.01, 0.12))
    for step, reach in step_specs:
        span = max(step, abs(default) * reach)
        k_lo = int(math.floor((default - span) / step))
        k_hi = int(math.ceil((default + span) / step))
        for k in range(k_lo, k_hi + 1):
            v = round(k * step, 6)
            if v > 0:
                cands.add(v)
    if lo_clip is not None:
        cands = {c for c in cands if c >= lo_clip}
    if hi_clip is not None:
        cands = {c for c in cands if c <= hi_clip}
    cands.add(float(default))
    return sorted(cands)


def _bisect_flip(evaluate: Callable[[float], Any], same: float, different: float,
                 integral: bool) -> float:
    """Locate the boundary between two threshold values with different outcomes.

    Returns the value on the ``different`` side of the boundary: the first value,
    to tolerance, at which the outcome is no longer the one observed at ``same``.
    """
    base = evaluate(same)
    lo, hi = same, different
    if integral:
        while abs(hi - lo) > 1:
            mid = int(round((lo + hi) / 2.0))
            if mid == lo or mid == hi:
                break
            if evaluate(mid) == base:
                lo = mid
            else:
                hi = mid
        return float(hi)
    for _ in range(60):
        if abs(hi - lo) <= FLIP_TOLERANCE:
            break
        mid = (lo + hi) / 2.0
        if evaluate(mid) == base:
            lo = mid
        else:
            hi = mid
    return round(hi, 6)


@dataclass
class ThresholdResult:
    name: str
    source: str
    default: float
    track: str
    baseline_outcome: dict
    stable_lo: float | None
    stable_hi: float | None
    flips: list[dict] = field(default_factory=list)
    fragile: bool = False
    nearest_flip: float | None = None
    relative_distance_to_flip: float | None = None
    recommendation_flip_at: float | None = None
    recommendation_flip_to: str | None = None
    recommendation_flip_distance: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "threshold": self.name,
            "source": self.source,
            "configured_value": self.default,
            "track": self.track,
            "baseline_outcome": self.baseline_outcome,
            "stable_range": [self.stable_lo, self.stable_hi],
            "flips": self.flips,
            "fragile": self.fragile,
            "nearest_flip_value": self.nearest_flip,
            "relative_distance_to_flip": (
                None if self.relative_distance_to_flip is None
                else round(self.relative_distance_to_flip, 4)
            ),
            "recommendation_flip_at": self.recommendation_flip_at,
            "recommendation_flip_to": self.recommendation_flip_to,
            "recommendation_flip_distance": (
                None if self.recommendation_flip_distance is None
                else round(self.recommendation_flip_distance, 4)
            ),
            "note": self.note,
        }


def _analyse_threshold(
    *,
    name: str,
    source: str,
    default: float,
    track: str,
    evaluate: Callable[[float], dict],
    integral: bool,
    grid: Sequence[float],
) -> ThresholdResult:
    """Sweep one threshold for one track and locate its flip points."""
    baseline = evaluate(float(default))
    key = lambda o: (  # noqa: E731
        tuple(o["claim_verdicts"]), tuple(o["check_verdicts"]), o["recommendation"]
    )

    outcomes = [(v, evaluate(float(v))) for v in grid]

    flips: list[dict] = []
    for (v_lo, o_lo), (v_hi, o_hi) in zip(outcomes, outcomes[1:]):
        if key(o_lo) == key(o_hi):
            continue
        boundary = _bisect_flip(lambda x: key(evaluate(x)), v_lo, v_hi, integral)
        changed = []
        if o_lo["claim_verdicts"] != o_hi["claim_verdicts"]:
            changed.append("claim_verdicts")
        if o_lo["check_verdicts"] != o_hi["check_verdicts"]:
            changed.append("check_verdicts")
        if o_lo["recommendation"] != o_hi["recommendation"]:
            changed.append("recommendation")
        flips.append({
            "at_value": boundary,
            "changed": changed,
            "from": o_lo,
            "to": o_hi,
        })

    # -- stable range and fragility ---------------------------------------
    #
    # Both are derived from the contiguous run of grid points around the
    # configured value that reproduce the baseline outcome, then (for continuous
    # thresholds) refined by bisection to the actual boundary.
    #
    # Deriving the fragility distance from the run rather than from the raw
    # boundary list matters for INTEGER cuts. Bisection on integers returns the
    # first differing integer, which for a cut like ``n_indicators >= 2`` is 2
    # itself -- the configured value IS the boundary, because the outcome differs
    # at 1. Measuring "distance to the boundary" then reports 0% and calls the
    # cut fragile, which is wrong twice over: nothing about the data is on a
    # knife edge, and one integer step is the smallest change an integer cut can
    # possibly sustain, so every integer cut would be fragile by construction.
    # The honest measure is the distance to the nearest value that produces a
    # DIFFERENT outcome: 1, i.e. 50% of the configured 2. Requiring one
    # structural indicator instead of two is a policy change, not a nudge.
    idx = min(range(len(grid)), key=lambda i: abs(float(grid[i]) - float(default)))
    lo_i = idx
    while lo_i - 1 >= 0 and key(outcomes[lo_i - 1][1]) == key(baseline):
        lo_i -= 1
    hi_i = idx
    while hi_i + 1 < len(grid) and key(outcomes[hi_i + 1][1]) == key(baseline):
        hi_i += 1

    candidates: list[float] = []  # nearest values producing a different outcome
    stable_lo = float(grid[lo_i])
    stable_hi = float(grid[hi_i])
    if lo_i > 0:
        below = float(grid[lo_i - 1])
        stable_lo = (
            below if integral
            else _bisect_flip(lambda x: key(evaluate(x)), float(grid[lo_i]), below, integral)
        )
        candidates.append(below if integral else stable_lo)
    if hi_i + 1 < len(grid):
        above = float(grid[hi_i + 1])
        stable_hi = (
            above if integral
            else _bisect_flip(lambda x: key(evaluate(x)), float(grid[hi_i]), above, integral)
        )
        candidates.append(above if integral else stable_hi)

    nearest_flip: float | None = None
    relative: float | None = None
    if candidates:
        nearest_flip = min(candidates, key=lambda v: abs(v - float(default)))
        relative = abs(nearest_flip - float(default)) / max(abs(float(default)), 1e-9)
    fragile = relative is not None and relative <= FRAGILITY_BAND

    changed_at_nearest: list[str] = []
    if nearest_flip is not None and flips:
        near = min(flips, key=lambda f: abs(f["at_value"] - nearest_flip))
        changed_at_nearest = near["changed"]

    note = ""
    if fragile:
        note = (
            f"FRAGILE: the configured value {default} sits {relative:.1%} away from "
            f"{nearest_flip}, at which "
            f"{', '.join(changed_at_nearest) or 'the outcome'} changes. The observed "
            "data is effectively on the threshold; the value chosen, not the "
            "evidence, is deciding this outcome."
        )
    elif not flips:
        note = "No flip anywhere in the swept range; this outcome does not depend on this cut."

    # The recommendation is the thing a stakeholder acts on, so its own distance
    # to a flip is tracked separately from the gate-verdict distance above. A
    # threshold can be fragile at the check level and nowhere near moving the
    # recommendation, and conflating the two would overstate the damage.
    rec_base = baseline["recommendation"]
    rec_differing = [float(v) for v, o in outcomes if o["recommendation"] != rec_base]
    rec_at: float | None = None
    rec_to: str | None = None
    rec_distance: float | None = None
    if rec_differing:
        nv = min(rec_differing, key=lambda v: abs(v - float(default)))
        rec_to = next(
            o["recommendation"] for v, o in outcomes if float(v) == nv
        )
        if integral:
            # One step is the smallest change an integer cut can take, so the
            # nearest differing integer IS the answer; bisecting would return
            # the configured value itself and report a spurious 0% distance.
            rec_at = nv
        else:
            # ``default`` is known to produce the baseline recommendation and
            # ``nv`` is known not to, so bisecting between them lands on a real
            # boundary regardless of what happens further out.
            rec_at = _bisect_flip(
                lambda x: evaluate(x)["recommendation"], float(default), nv, integral
            )
        rec_distance = abs(rec_at - float(default)) / max(abs(float(default)), 1e-9)

    return ThresholdResult(
        name=name, source=source, default=default, track=track,
        baseline_outcome=baseline, stable_lo=stable_lo, stable_hi=stable_hi,
        flips=flips, fragile=fragile,
        nearest_flip=nearest_flip, relative_distance_to_flip=relative,
        recommendation_flip_at=rec_at, recommendation_flip_to=rec_to,
        recommendation_flip_distance=rec_distance,
        note=note,
    )


# --------------------------------------------------------------------------
# ANALYSIS 1: threshold sensitivity
# --------------------------------------------------------------------------


#: ``GatePolicy`` fields that are numeric and therefore sweepable. Booleans are
#: excluded: a two-valued switch has no "range over which the verdict is
#: stable", and flipping it is a policy change rather than a threshold nudge.
def _numeric_policy_fields(policy: GatePolicy) -> list[tuple[str, float, bool]]:
    out = []
    for f in dataclasses.fields(policy):
        v = getattr(policy, f.name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out.append((f.name, v, isinstance(v, int)))
    return out


def threshold_sensitivity(chain: Chain, track_keys: Sequence[str]) -> dict:
    """Sweep every gate threshold and every decision cut; find what flips.

    Two families of threshold, swept the same way but reached differently:

    * ``GatePolicy`` fields are ordinary dataclass fields, so a swept policy is
      ``dataclasses.replace(base, field=value)`` and the ledger is rebuilt from
      cached evidence. Each track is swept against ITS OWN base policy --
      ``refusal`` is exploratory and runs under ``EXPLORATORY_POLICY``, so
      sweeping the default 0.50 alpha floor against it would measure a threshold
      that never applies to it.
    * ``decision.py`` cuts are inline literals, reached by recompiling the module
      (see :func:`_decision_module_with`).

    The output flags a threshold FRAGILE when its configured value sits within
    5% of a flip point. That is the honest way to surface the
    0.34-versus-observed-0.333 problem: state it in the report before a reviewer
    finds it, with the exact flip value attached.
    """
    log("ANALYSIS 1/4: threshold sensitivity")
    results: list[dict] = []

    # -- gate policy thresholds --------------------------------------------
    for track_key in track_keys:
        ev = chain.baseline(track_key)
        base_policy = policy_for_depth(ev.depth)
        rec = ev.recommendation
        for fname, default, integral in _numeric_policy_fields(base_policy):
            def evaluate(value: float, _f=fname, _e=ev, _p=base_policy, _r=rec) -> dict:
                v = int(round(value)) if isinstance(getattr(_p, _f), int) else float(value)
                counts = chain.regate(_e, dataclasses.replace(_p, **{_f: v}))
                # The decision engine does not read GatePolicy, so the
                # recommendation is invariant here by construction. It is carried
                # through anyway so the outcome tuple has one shape everywhere and
                # so the invariance is visible in the output rather than assumed.
                return {
                    "claim_verdicts": counts["claims"],
                    "check_verdicts": counts["checks"],
                    "recommendation": _r,
                }

            grid = sweep_values(
                default, integral=integral,
                lo_clip=0 if integral else 0.0,
                hi_clip=1.0 if (not integral and default < 1.0) else None,
            )
            results.append(_analyse_threshold(
                name=f"GatePolicy.{fname}", source="gates/signal.py",
                default=default, track=track_key, evaluate=evaluate,
                integral=integral, grid=grid,
            ).to_dict())
        log(f"  gate policy thresholds swept for {track_key}")

    # -- decision engine cuts ----------------------------------------------
    cuts = discover_decision_cuts()
    log(f"  discovered {len(cuts)} comparison cuts in gates/decision.py")
    for cut in cuts:
        integral = isinstance(cut.value, int)
        grid = sweep_values(
            cut.value, integral=integral,
            lo_clip=0, hi_clip=1.0 if (not integral and cut.value < 1.0) else None,
        )
        for track_key in track_keys:
            ev = chain.baseline(track_key)
            if ev.decision_input is None:  # pragma: no cover - defensive
                continue
            base_counts = chain.regate(ev, policy_for_depth(ev.depth))

            def evaluate(value: float, _c=cut, _e=ev, _b=base_counts) -> dict:
                v = int(round(value)) if isinstance(_c.value, int) else float(value)
                mod = _decision_module_with(_c, v)
                decision = mod.recommend(_e.decision_input)
                # Gate verdicts do not read the decision engine, so they are
                # invariant across this sweep, by the same logic as above.
                return {
                    "claim_verdicts": _b["claims"],
                    "check_verdicts": _b["checks"],
                    "recommendation": decision.recommendation.value,
                }

            results.append(_analyse_threshold(
                name=cut.cut_id, source="gates/decision.py",
                default=cut.value, track=track_key, evaluate=evaluate,
                integral=integral, grid=grid,
            ).to_dict())
        log(f"  swept cut {cut.expression!r} (line {cut.lineno})")

    fragile = [r for r in results if r["fragile"]]
    rec_flips = [r for r in results if r.get("recommendation_flip_at") is not None]
    return {
        "n_threshold_track_pairs": len(results),
        "n_fragile": len(fragile),
        "fragile": sorted(
            (
                {
                    "threshold": r["threshold"],
                    "track": r["track"],
                    "configured_value": r["configured_value"],
                    "flips_at": r["nearest_flip_value"],
                    "relative_distance": r["relative_distance_to_flip"],
                    "changed": sorted({c for f in r["flips"] for c in f["changed"]}),
                    "note": r["note"],
                }
                for r in fragile
            ),
            key=lambda d: (d["relative_distance"] if d["relative_distance"] is not None else 9),
        ),
        "thresholds_that_can_flip_a_recommendation": sorted(
            {(r["threshold"], r["track"]) for r in rec_flips}
        ),
        "unswept_literals": unswept_decision_literals(),
        "results": results,
        "method_note": (
            "Each threshold is swept in isolation, holding every other threshold "
            "at its configured value. Interactions between thresholds are NOT "
            "explored: the space is too large to enumerate and one-at-a-time "
            "sweeps are the standard first-order analysis. A one-at-a-time sweep "
            "can therefore understate fragility, never overstate it."
        ),
    }


# --------------------------------------------------------------------------
# ANALYSIS 2: contested-flag sensitivity
# --------------------------------------------------------------------------


def contested_flag_sensitivity(chain: Chain, track_keys: Sequence[str],
                               n_seeds: int = 20) -> dict:
    """Re-run the whole chain under perturbed ``contested`` flags.

    This is the analysis the project most needs and least wants. The ``refusal``
    STOP verdict is the portfolio's flagship result -- the framework was built to
    be able to say "stop" -- and the flags that produce it were typed by hand into
    a dictionary. If STOP evaporates when they are cleared, then the honest
    statement of the finding is not "refusal is a contested construct" but "IF
    calibration, over-refusal cost, and tone are contested judgements, THEN
    refusal cannot be measured as a scalar" -- a conditional, with the antecedent
    stated as an assumption rather than smuggled in as a result.

    That conditional is still worth publishing. It is a statement about what
    follows from a premise a reader can evaluate. What is not worth publishing is
    the unconditional version.

    Randomised reassignment holds the total flag count fixed at its baseline
    value, so the distribution answers "how special is the assignment we chose?"
    rather than "what happens with more flags?" -- the latter is what ``all_on``
    is for.
    """
    log(f"ANALYSIS 2/4: contested-flag sensitivity ({n_seeds} random seeds)")
    configs = contested_configurations(n_seeds=n_seeds)
    per_config: dict[str, dict] = {}

    for i, (name, table) in enumerate(configs.items(), start=1):
        row: dict[str, Any] = {}
        for track_key in track_keys:
            if name == "baseline":
                # Identical to an unperturbed run by construction; reuse the
                # cached one rather than paying for four more pipeline passes.
                ev = chain.baseline(track_key)
            else:
                ev = chain.run(track_key, properties=table, properties_id=f"contested::{name}")
            row[track_key] = ev.summary()
        per_config[name] = row
        if i % 5 == 0 or i == len(configs):
            log(f"  {i}/{len(configs)} contested configurations evaluated")

    baseline = per_config["baseline"]
    random_names = [n for n in per_config if n.startswith("random_")]

    def _dist(track: str) -> dict:
        counts: dict[str, int] = {}
        for n in random_names:
            r = per_config[n][track]["recommendation"]
            counts[r] = counts.get(r, 0) + 1
        return {
            "n_seeds": len(random_names),
            "counts": dict(sorted(counts.items())),
            "fraction": {
                k: round(v / len(random_names), 3) for k, v in sorted(counts.items())
            },
        }

    per_track_summary = {}
    for track_key in track_keys:
        base_rec = baseline[track_key]["recommendation"]
        variants = {
            name: per_config[name][track_key]["recommendation"]
            for name in per_config
            if name != "baseline" and not name.startswith("random_")
        }
        dist = _dist(track_key)
        n_agree = sum(
            1 for n in random_names if per_config[n][track_key]["recommendation"] == base_rec
        )
        per_track_summary[track_key] = {
            "baseline_recommendation": base_rec,
            "baseline_alpha_mean": baseline[track_key]["alpha_mean"],
            "baseline_contested_dimensions": baseline[track_key]["contested_dimensions"],
            "named_variants": variants,
            "random_reassignment": dist,
            "fraction_of_random_seeds_preserving_baseline": round(
                n_agree / len(random_names), 3
            ) if random_names else None,
            "survives_all_named_variants": all(v == base_rec for v in variants.values()),
        }

    headline: list[str] = []
    if "refusal" in per_track_summary:
        s = per_track_summary["refusal"]
        off = s["named_variants"].get("all_off")
        roff = s["named_variants"].get("refusal_off")
        headline.append(
            f"refusal baseline={s['baseline_recommendation'].upper()}; with its own contested "
            f"flags cleared it is {str(roff).upper()}; with every flag in the portfolio "
            f"cleared it is {str(off).upper()}. Random reassignment of the same number of "
            f"flags reproduces the baseline verdict in "
            f"{s['fraction_of_random_seeds_preserving_baseline']:.0%} of "
            f"{s['random_reassignment']['n_seeds']} seeds."
        )
    if "agentic" in per_track_summary:
        s = per_track_summary["agentic"]
        headline.append(
            f"agentic baseline={s['baseline_recommendation'].upper()}; with all six of its "
            f"dimensions marked contested it is "
            f"{str(s['named_variants'].get('agentic_all_on')).upper()}; under the reviewer's "
            f"three-flag swap it is {str(s['named_variants'].get('reviewer_swap')).upper()}."
        )

    return {
        "n_configurations": len(configs),
        "baseline_contested_slots": [f"{t}.{d}" for t, d in baseline_contested_slots()],
        "headline": headline,
        "per_track": per_track_summary,
        "per_configuration": per_config,
        "method_note": (
            "Every configuration re-runs annotation, adjudication, agreement, "
            "scoring, gating, and the decision engine end to end. The contested "
            "flag is injected through annotation.effects.property_overrides, so "
            "the code path is identical to production; only the table differs. "
            "Noise values are held at their configured levels throughout, so the "
            "contrast isolates the contested flag."
        ),
    }


# --------------------------------------------------------------------------
# ANALYSIS 3: noise sensitivity
# --------------------------------------------------------------------------


def noise_sensitivity(chain: Chain, track_keys: Sequence[str]) -> dict:
    """Sweep the two simulator multipliers that set how much disagreement exists.

    ``pool._observe`` contains two numbers with no empirical provenance:

    * a global 0.70 scale on judgement noise, justified in a comment as
      representing "an anchored pool";
    * a 2.60 scale on the contested value-position term, justified nowhere.

    Every agreement coefficient in the portfolio -- and therefore every verdict --
    is a monotone function of these. A reader is entitled to know how far the
    conclusions travel when they move. The sweep is one-at-a-time: the global
    multiplier is varied with the contested multiplier held at 2.60, and vice
    versa, because a joint grid at useful resolution costs more runs than the
    runtime budget allows and adds little beyond the marginals.
    """
    log("ANALYSIS 3/4: noise multiplier sensitivity")
    global_grid = [0.35, 0.49, 0.56, 0.63, 0.70, 0.77, 0.84, 0.91, 1.40]
    contested_grid = [1.30, 1.82, 2.08, 2.34, 2.60, 2.86, 3.12, 3.38, 3.90]

    global_sweep: list[dict] = []
    for g in global_grid:
        row = {"global_noise_multiplier": g, "tracks": {}}
        for track_key in track_keys:
            ev = chain.run(track_key, global_noise_multiplier=g)
            row["tracks"][track_key] = {
                "recommendation": ev.recommendation,
                "alpha_mean": ev.summary()["alpha_mean"],
                "verdicts": ev.verdicts,
            }
        global_sweep.append(row)
        log(f"  global multiplier {g:.2f} done")

    contested_sweep: list[dict] = []
    for c in contested_grid:
        row = {"contested_multiplier": c, "tracks": {}}
        for track_key in track_keys:
            ev = chain.run(track_key, contested_multiplier=c)
            row["tracks"][track_key] = {
                "recommendation": ev.recommendation,
                "alpha_mean": ev.summary()["alpha_mean"],
                "verdicts": ev.verdicts,
            }
        contested_sweep.append(row)
        log(f"  contested multiplier {c:.2f} done")

    def _stability(sweep: list[dict], param: str) -> dict:
        out = {}
        for track_key in track_keys:
            recs = [(r[param], r["tracks"][track_key]["recommendation"]) for r in sweep]
            base = dict(recs)[
                DEFAULT_GLOBAL_NOISE_MULTIPLIER if param == "global_noise_multiplier"
                else DEFAULT_CONTESTED_MULTIPLIER
            ]
            unchanged = [v for v, r in recs if r == base]
            out[track_key] = {
                "baseline_recommendation": base,
                "distinct_recommendations": sorted({r for _, r in recs}),
                "values_preserving_baseline": unchanged,
                "stable_over_full_range": len({r for _, r in recs}) == 1,
                "transitions": [
                    {"between": [a, b], "from": ra, "to": rb}
                    for (a, ra), (b, rb) in zip(recs, recs[1:]) if ra != rb
                ],
            }
        return out

    return {
        "global_noise_multiplier": {
            "configured_value": DEFAULT_GLOBAL_NOISE_MULTIPLIER,
            "source": "annotation/pool.py::_observe",
            "grid": global_grid,
            "sweep": global_sweep,
            "stability": _stability(global_sweep, "global_noise_multiplier"),
        },
        "contested_multiplier": {
            "configured_value": DEFAULT_CONTESTED_MULTIPLIER,
            "source": "annotation/pool.py::_observe",
            "grid": contested_grid,
            "sweep": contested_sweep,
            "stability": _stability(contested_sweep, "contested_multiplier"),
        },
        "method_note": (
            "Multipliers are injected by patching annotation.pool._observe with a "
            "parameterised replica whose equality with the production function at "
            "the configured multipliers is asserted before the sweep runs "
            "(gates.sensitivity.verify_observe_replica)."
        ),
    }


# --------------------------------------------------------------------------
# ANALYSIS 4: leave-one-annotator-out at the verdict level
# --------------------------------------------------------------------------


#: Batch count used for the leave-one-out analysis.
#:
#: ``pool.annotate`` refuses a batch count sharing a factor with the roster size,
#: because pool composition would then correlate with batch and manufacture
#: spurious drift. The default of 5 batches is coprime with the full roster of 6
#: but NOT with a five-annotator roster, so leave-one-out cannot use it. 7 is
#: coprime with both, which lets the reference run and the reduced runs share a
#: batch count -- without that, the comparison would confound "we removed an
#: annotator" with "we re-batched the corpus".
LOO_N_BATCHES = 7


def leave_one_annotator_out(chain: Chain, track_keys: Sequence[str]) -> dict:
    """Re-derive every verdict with each annotator removed.

    ``redteam.probes.annotator_leave_one_out`` already asks whether removing an
    annotator moves the *score*. This asks the question that actually matters to
    a decision-maker: does it move the *recommendation*? A portfolio verdict that
    rests on one of six simulated people is not a finding about the construct, it
    is a finding about that person -- and in a real programme it is a staffing
    risk, because that person will eventually leave.
    """
    log("ANALYSIS 4/4: leave-one-annotator-out at the verdict level")
    roster_ids = [a.annotator_id for a in pool_mod.ROSTER]

    reference: dict[str, dict] = {}
    for track_key in track_keys:
        ev = chain.run(track_key, n_batches=LOO_N_BATCHES)
        reference[track_key] = ev.summary()
    log(f"  reference (full roster, {LOO_N_BATCHES} batches) computed")

    per_annotator: dict[str, dict] = {}
    for aid in roster_ids:
        row = {}
        for track_key in track_keys:
            ev = chain.run(track_key, drop_annotator=aid, n_batches=LOO_N_BATCHES)
            row[track_key] = ev.summary()
        per_annotator[aid] = row
        log(f"  dropped {aid}")

    dependencies: list[dict] = []
    for track_key in track_keys:
        ref_rec = reference[track_key]["recommendation"]
        for aid in roster_ids:
            rec = per_annotator[aid][track_key]["recommendation"]
            if rec != ref_rec:
                dependencies.append({
                    "track": track_key,
                    "annotator": aid,
                    "recommendation_with_full_roster": ref_rec,
                    "recommendation_without": rec,
                    "alpha_mean_with": reference[track_key]["alpha_mean"],
                    "alpha_mean_without": per_annotator[aid][track_key]["alpha_mean"],
                })

    return {
        "n_batches": LOO_N_BATCHES,
        "reference": reference,
        "per_annotator": per_annotator,
        "single_annotator_dependencies": dependencies,
        "any_recommendation_depends_on_one_annotator": bool(dependencies),
        "method_note": (
            f"Run at n_batches={LOO_N_BATCHES} for both the reference and the "
            "reduced rosters, because the production value of 5 shares a factor "
            "with a 5-annotator roster and pool.annotate rejects it. The reference "
            "row is therefore NOT the production run and its verdicts may differ "
            "from results/portfolio.json; compare reduced rosters against this "
            "reference, not against the portfolio."
        ),
    }


# --------------------------------------------------------------------------
# classification and orchestration
# --------------------------------------------------------------------------


def classify_conclusions(threshold: dict, contested: dict, noise: dict,
                         loo: dict, track_keys: Sequence[str]) -> dict:
    """Label each track's recommendation ROBUST / CONDITIONAL / FRAGILE.

    The rule is deliberately blunt, because a subtle rule invites argument about
    the rule instead of about the evidence:

    * FRAGILE if any single perturbation from the smallest family -- a threshold
      inside its 5% fragility band, or the removal of one annotator -- changes
      the recommendation.
    * CONDITIONAL if the recommendation survives those but changes under a named
      structural perturbation (contested flags, noise multipliers).
    * ROBUST if nothing tried here changes it.
    """
    out: dict[str, dict] = {}
    for track_key in track_keys:
        reasons_fragile: list[str] = []
        reasons_conditional: list[str] = []

        for r in threshold["results"]:
            if r["track"] != track_key:
                continue
            dist = r.get("recommendation_flip_distance")
            if dist is None:
                continue
            msg = (
                f"{r['threshold']} flips the recommendation at "
                f"{r['recommendation_flip_at']} (configured {r['configured_value']}, "
                f"{dist:.1%} away): "
                f"{r['baseline_outcome']['recommendation']} -> {r['recommendation_flip_to']}"
            )
            (reasons_fragile if dist <= FRAGILITY_BAND else reasons_conditional).append(msg)

        for dep in loo["single_annotator_dependencies"]:
            if dep["track"] == track_key:
                reasons_fragile.append(
                    f"removing annotator {dep['annotator']} changes the recommendation "
                    f"{dep['recommendation_with_full_roster']} -> {dep['recommendation_without']}"
                )

        c = contested["per_track"][track_key]
        for name, rec in c["named_variants"].items():
            if rec != c["baseline_recommendation"]:
                reasons_conditional.append(
                    f"contested-flag configuration '{name}' changes the recommendation "
                    f"{c['baseline_recommendation']} -> {rec}"
                )
        frac = c["fraction_of_random_seeds_preserving_baseline"]
        if frac is not None and frac < 1.0:
            reasons_conditional.append(
                f"random reassignment of the same number of contested flags preserves the "
                f"baseline recommendation in only {frac:.0%} of seeds"
            )

        for param in ("global_noise_multiplier", "contested_multiplier"):
            st = noise[param]["stability"][track_key]
            if not st["stable_over_full_range"]:
                reasons_conditional.append(
                    f"{param} sweep produces {st['distinct_recommendations']} over "
                    f"{noise[param]['grid'][0]}..{noise[param]['grid'][-1]}"
                )

        if reasons_fragile:
            label = "FRAGILE"
        elif reasons_conditional:
            label = "CONDITIONAL"
        else:
            label = "ROBUST"

        out[track_key] = {
            "recommendation": contested["per_track"][track_key]["baseline_recommendation"],
            "classification": label,
            "fragile_because": reasons_fragile,
            "conditional_because": reasons_conditional,
        }
    return out


def run_sensitivity(
    results_dir: str | Path = "results",
    track_keys: Sequence[str] | None = None,
    n_contested_seeds: int = 20,
    write: bool = True,
    verbose: bool = True,
) -> dict:
    """Run every analysis and (optionally) write ``results/sensitivity.json``."""
    global _VERBOSE, _T0
    _VERBOSE = verbose
    _T0 = time.time()

    from ..tracks import all_tracks, registration_report

    keys = list(track_keys) if track_keys else [t.key for t in all_tracks()]
    log(f"tracks under analysis: {', '.join(keys)}")

    verify_observe_replica()
    log("pool._observe replica verified identical at configured multipliers")

    reg = registration_report()
    if reg["tracks_missing_effects_table"]:
        log(
            "WARNING: tracks with no effects table (their detection-sensitivity "
            f"output is not interpretable): {reg['tracks_missing_effects_table']}"
        )

    chain = Chain()
    for k in keys:
        ev = chain.baseline(k)
        log(f"baseline {k}: alpha={ev.alpha_mean:.3f} -> {ev.recommendation.upper()}")

    contested = contested_flag_sensitivity(chain, keys, n_seeds=n_contested_seeds)
    threshold = threshold_sensitivity(chain, keys)
    noise = noise_sensitivity(chain, keys)
    loo = leave_one_annotator_out(chain, keys)
    classification = classify_conclusions(threshold, contested, noise, loo, keys)

    payload = {
        "generated_by": "rubricon.gates.sensitivity.run_sensitivity",
        "purpose": (
            "Quantify how far each portfolio conclusion depends on hand-set "
            "parameters rather than on the data. Every number here is a "
            "statement about the robustness of a verdict, not about a system."
        ),
        "tracks": keys,
        "n_pipeline_runs": chain.n_runs,
        "elapsed_seconds": round(time.time() - _T0, 1),
        "track_registration": reg,
        "classification": classification,
        "contested_flag_sensitivity": contested,
        "threshold_sensitivity": threshold,
        "noise_sensitivity": noise,
        "leave_one_annotator_out": loo,
        "limitations": [
            "One-at-a-time perturbation. Interactions between assumptions are not "
            "explored, so this analysis can understate fragility and cannot "
            "overstate it.",
            "The annotator pool is simulated. These results characterise how "
            "sensitive the verdicts are to the SIMULATOR's parameters; they say "
            "nothing about how sensitive a real programme's verdicts would be to "
            "a real pool.",
            "Only assumptions that are reachable as parameters are swept. The "
            "structure of the annotator model itself -- additive bias, a single "
            "value-position axis, gold items being uncontested by construction -- "
            "is a much larger assumption and is not perturbed here at all.",
            "Redteam probe thresholds (for example the 0.93 rubric-shortcut cut) "
            "are not swept: they gate a diagnostic rather than a verdict, so a "
            "flip changes what is reported, not what is recommended.",
        ],
    }

    if write:
        out = Path(results_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "sensitivity.json"
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        log(f"wrote {path}")
    log(f"done: {chain.n_runs} pipeline runs in {time.time() - _T0:.1f}s")
    return payload


__all__ = [
    "Chain",
    "DecisionCut",
    "FRAGILITY_BAND",
    "LOO_N_BATCHES",
    "NullStore",
    "RunEvidence",
    "ThresholdResult",
    "baseline_contested_slots",
    "classify_conclusions",
    "contested_configurations",
    "contested_flag_sensitivity",
    "discover_decision_cuts",
    "leave_one_annotator_out",
    "log",
    "make_observe",
    "noise_sensitivity",
    "properties_with_contested",
    "run_sensitivity",
    "sweep_values",
    "threshold_sensitivity",
    "unswept_decision_literals",
    "verify_observe_replica",
]
