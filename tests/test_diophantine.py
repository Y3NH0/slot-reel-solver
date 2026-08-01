from fractions import Fraction

import pytest

from slotmath import engine
from slotmath.diophantine import (
    has_mixed_signs,
    score,
    search_last_reel,
    signature_weights,
)
from slotmath.metrics import build_metrics, exact_rtp
from tests.fixtures import GOLDEN
from tests.test_naive import hw


def test_score_is_zero_exactly_when_rtp_is_on_target():
    spec = hw()
    for g in GOLDEN:
        weights = signature_weights(spec, g.reels[:-1])
        assert score(spec, weights, g.reels[-1]) == 0


def test_score_is_nonzero_for_an_off_target_reel():
    spec = hw()
    g = GOLDEN[2]
    weights = signature_weights(spec, g.reels[:-1])
    off = list(g.reels[-1]) + [4, 4, 4]
    assert score(spec, weights, off) != 0
    # and the engine agrees it is off target
    m = build_metrics(spec, engine.evaluate(spec, [*g.reels[:-1], off]))
    assert exact_rtp(m) != Fraction(19, 20)


def test_weights_have_both_signs_so_a_solution_exists():
    """There is always an almost-always-winning signature and an
    almost-never-winning one, so positives and negatives coexist."""
    spec = hw()
    weights = signature_weights(spec, GOLDEN[2].reels[:-1])
    assert has_mixed_signs(weights)


def test_mixed_signs_is_not_guaranteed_across_golden_fixed_reels():
    """Existence has two independent routes: mixed signs (fixture C) or a
    zero weight reached by a uniform last reel (fixtures A and B, whose
    weights are all <= 0 with none positive -- has_mixed_signs is False).
    Pins the real sign structure so a change to signature_weights that
    silently drops route 2 would be caught here."""
    spec = hw()
    expected = {"A": False, "B": False, "C": True}
    for g in GOLDEN:
        weights = signature_weights(spec, g.reels[:-1])
        assert has_mixed_signs(weights) == expected[g.name]


def test_all_same_signature_outweighs_a_dead_signature():
    spec = hw()
    weights = signature_weights(spec, GOLDEN[2].reels[:-1])
    all_twos = weights[(2, 2, 2)] if (2, 2, 2) in weights else None
    dead = weights.get((None, None, None))
    assert dead is not None and dead < 0
    if all_twos is not None:
        assert all_twos > dead


def test_search_finds_a_last_reel_that_lands_exactly_on_target():
    spec = hw()
    fixed = GOLDEN[2].reels[:-1]
    found = search_last_reel(
        spec, fixed, min_len=3, max_len=14, seed=20260731, max_candidates=40_000
    )
    assert found is not None
    m = build_metrics(spec, engine.evaluate(spec, [*fixed, found]))
    assert exact_rtp(m) == Fraction(19, 20)


def test_search_returns_none_instead_of_hanging_when_no_candidate_fits():
    spec = hw()
    # a single symbol reel pair leaves too little freedom within 3..4
    fixed = [[4] * 3, [4] * 3]
    assert search_last_reel(
        spec, fixed, min_len=3, max_len=4, seed=1, max_candidates=500
    ) is None
