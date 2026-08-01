import random
from fractions import Fraction

import pytest

from slotmath.evaluation import engine, naive
from slotmath.models.metrics import build_metrics, exact_rtp, exact_win_rate
from tests.fixtures import GOLDEN
from tests.test_naive import hw

IDS = [g.name for g in GOLDEN]


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_naive_reproduces_golden_distribution(g):
    assert naive.evaluate(hw(), g.reels) == g.distribution


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_engine_reproduces_golden_distribution(g):
    assert engine.evaluate(hw(), g.reels) == g.distribution


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_golden_rtp_is_exactly_nineteen_twentieths(g):
    m = build_metrics(hw(), naive.evaluate(hw(), g.reels))
    assert m.spin_count == g.spin_count
    assert exact_rtp(m) == g.rtp == Fraction(19, 20)
    assert exact_win_rate(m) == g.win_rate


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_golden_meets_min_win_rate(g):
    assert g.win_rate >= Fraction(11, 20)


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_mod5_invariant_holds_for_golden(g):
    """n1 = combos whose max payout is exactly 11 units (0.55 x bet).
    Necessary condition for RTP = 19/20: n1 = 4N (mod 5). See spec 4.2."""
    n1 = g.distribution.get(11, 0)
    assert n1 % 5 == (4 * g.spin_count) % 5


def test_fixture_a_is_the_only_one_exercising_nonzero_n1():
    """Guard against someone deleting fixture A as redundant. See spec 4.3."""
    nonzero = [g.name for g in GOLDEN if g.distribution.get(11, 0) != 0]
    assert nonzero == ["A"]


def test_mod5_invariant_rules_out_configs_that_violate_it():
    """Contrapositive of the invariant: if n1 is in the wrong residue class,
    RTP cannot be 19/20. Written this way because the forward direction is
    unreachable -- random reels essentially never land on an exact 19/20, so a
    test guarded by `if rtp == 19/20` would be dead code that always passes.
    """
    spec = hw()
    exercised = 0
    for seed in range(40):
        rng = random.Random(1000 + seed)
        reels = [
            [rng.randint(0, 4) for _ in range(rng.randint(3, 8))]
            for _ in range(3)
        ]
        dist = naive.evaluate(spec, reels)
        m = build_metrics(spec, dist)
        if dist.get(11, 0) % 5 != (4 * m.spin_count) % 5:
            exercised += 1
            assert exact_rtp(m) != Fraction(19, 20)
    assert exercised >= 10, f"only {exercised}/40 seeds exercised the assertion"
