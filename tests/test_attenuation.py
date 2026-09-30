"""Gate v2 noise model: identities checked against exact enumeration and simulation."""
import math
import random

import pytest

from rubricon.core.schema import Verdict
from rubricon.gates import attenuation as T


def test_eta_inverts_pairwise_disagreement():
    for eta in (0.0, 0.05, 0.2, 0.35, 0.49):
        assert T.eta_from_disagreement(2 * eta * (1 - eta)) == pytest.approx(eta, abs=1e-12)
    assert T.eta_from_disagreement(0.6) == 0.5


def test_majority_error_matches_enumeration():
    import itertools
    for k in (1, 2, 3, 4, 5):
        eta = 0.23
        tot = 0.0
        for wrongs in itertools.product((0, 1), repeat=k):
            p = math.prod(eta if w else 1 - eta for w in wrongs)
            s = sum(wrongs)
            tot += p * (1.0 if 2 * s > k else 0.5 if 2 * s == k else 0.0)
        assert T.eta_majority(eta, k) == pytest.approx(tot, abs=1e-12)


def test_observed_gap_is_attenuated_by_one_minus_two_eta_gold():
    rng = random.Random(0)
    n, eta_g = 200_000, 0.18
    ca = [rng.random() < 0.80 for _ in range(n)]
    cb = [rng.random() < 0.75 for _ in range(n)]
    gold_ok = [rng.random() > eta_g for _ in range(n)]
    oa = [int(a == g) for a, g in zip(ca, gold_ok)]
    ob = [int(b == g) for b, g in zip(cb, gold_ok)]
    true_gap = (sum(ca) - sum(cb)) / n
    pg = T.PairedGap.from_correctness(oa, ob)
    assert pg.gap == pytest.approx(T.attenuation(eta_g) * true_gap, abs=0.004)
    true_disc = sum(a != b for a, b in zip(ca, cb)) / n
    assert pg.disagreement == pytest.approx(true_disc, abs=1e-12)


def test_direction_and_report_and_consistency():
    pg = T.PairedGap(n=2000, gap=0.03, sd=math.sqrt(0.2 - 0.03**2), disagreement=0.2)
    assert T.check_direction(pg).verdict is Verdict.PASS
    assert T.check_direction(T.PairedGap(500, 0.01, 0.44, 0.2)).verdict is Verdict.BLOCK
    rep = T.attenuation_report(pg, rater_disagreement=0.3, k_raters=3, requested_effect=0.01)
    assert rep.verdict is Verdict.WARN and rep.observed < 1
    up = [1] * 60 + [0] * 340
    down = [-1] * 60 + [0] * 340
    assert T.check_contested_consistency(up, down).verdict is Verdict.BLOCK
    assert T.check_contested_consistency(up, up).verdict is Verdict.PASS
