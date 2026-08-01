import pytest
from fractions import Fraction
from slotmath.metrics import build_metrics, exact_rtp, exact_win_rate
from tests.test_naive import hw


def test_fixture_c_metrics():
    """Fixture C from spec section 4.1: 0 x204, 1 x474, 5 x42 over N=720."""
    spec = hw()
    dist = {0: 204, 20: 474, 100: 42}      # 1 -> 20 units, 5 -> 100 units
    m = build_metrics(spec, dist)

    assert m.spin_count == 720
    assert m.win_count == 516
    assert m.payout_unit_denominator == 20
    assert m.total_payout_units == 474 * 20 + 42 * 100 == 13680
    assert exact_rtp(m) == Fraction(19, 20)
    assert exact_win_rate(m) == Fraction(43, 60)
    assert m.max_win == 5.0
    assert m.volatility == pytest.approx(1.1018923117377064)


def test_payout_buckets_are_sorted_and_carry_both_forms():
    spec = hw()
    m = build_metrics(spec, {100: 1, 0: 3, 11: 2})
    assert [b.payout_units for b in m.payout_distribution] == [0, 11, 100]
    assert [b.combo_count for b in m.payout_distribution] == [3, 2, 1]
    assert m.payout_distribution[1].payout == 0.55


def test_combo_counts_sum_to_spin_count():
    spec = hw()
    m = build_metrics(spec, {0: 10, 20: 5})
    assert sum(b.combo_count for b in m.payout_distribution) == m.spin_count == 15


def test_zero_payout_bucket_may_be_absent():
    spec = hw()
    m = build_metrics(spec, {20: 8})
    assert m.win_count == 8 and m.spin_count == 8
    assert exact_win_rate(m) == Fraction(1)


def test_empty_distribution_rejected():
    spec = hw()
    with pytest.raises(ValueError, match="empty"):
        build_metrics(spec, {})
