"""Property-based tests: invariants the agreement statistics and the noise model must satisfy
for every input, not just the published reference datasets."""
import math
import random

from hypothesis import given, settings, strategies as st

from rubricon.gates.attenuation import attenuation, eta_from_disagreement, eta_majority
from rubricon.stats.agreement import krippendorff_alpha, percent_agreement

units = st.lists(
    st.lists(st.sampled_from(["a", "b", "c"]), min_size=2, max_size=6), min_size=3, max_size=40)


def _matrix(rows, relabel=None, shuffle_seed=None):
    m = {}
    order = list(range(len(rows)))
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(order)
    for i in order:
        m[f"u{i}"] = {f"r{j}": (relabel[v] if relabel else v) for j, v in enumerate(rows[i])}
    return m


@given(units, st.integers(0, 10**6))
@settings(max_examples=200, deadline=None)
def test_alpha_invariant_to_unit_order_and_label_names(rows, seed):
    a = krippendorff_alpha(_matrix(rows), "nominal").value
    b = krippendorff_alpha(_matrix(rows, relabel={"a": "x", "b": "y", "c": "z"}, shuffle_seed=seed), "nominal").value
    if math.isnan(a):
        assert math.isnan(b)
    else:
        assert abs(a - b) < 1e-12


@given(units)
@settings(max_examples=200, deadline=None)
def test_alpha_is_at_most_one_and_one_under_perfect_agreement(rows):
    a = krippendorff_alpha(_matrix(rows), "nominal").value
    assert math.isnan(a) or a <= 1 + 1e-12
    perfect = [[r[0]] * len(r) for r in rows]
    p = krippendorff_alpha(_matrix(perfect), "nominal").value
    assert math.isnan(p) or abs(p - 1) < 1e-12   # nan only when a single category is used
    assert percent_agreement(_matrix(perfect)).value == 1.0


@given(st.floats(0, 0.4999), st.integers(1, 9))
def test_majority_error_behaviour(eta, k):
    e = eta_majority(eta, k)
    assert 0 <= e <= 0.5 + 1e-12
    if k % 2 == 1 and k > 1:
        assert e <= eta + 1e-12            # an odd majority never makes labels worse
    assert abs(attenuation(e) - (1 - 2 * e)) < 1e-15


@given(st.floats(0, 0.4999))
def test_eta_round_trips_through_disagreement(eta):
    assert abs(eta_from_disagreement(2 * eta * (1 - eta)) - eta) < 1e-9
