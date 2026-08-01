import math

import pytest

from slotmath import naive
from slotmath.metrics import build_metrics
from slotmath.portfolio import (
    Portfolio,
    calibrate,
    entropy_of,
    features,
    min_distance,
    normalise,
    should_admit,
)
from slotmath.verify import ReelConfig
from tests.fixtures import GOLDEN
from tests.test_naive import hw


def metrics_for(g):
    spec = hw()
    return build_metrics(spec, naive.evaluate(spec, g.reels))


def _stub_config(g):
    return ReelConfig(
        spec="configs/homework-3x3.json",
        reels=g.reels,
        metrics=metrics_for(g),
    )


def test_features_has_five_dimensions_in_documented_order():
    m = metrics_for(GOLDEN[2])
    f = features(m)
    assert len(f) == 5
    assert f[0] == pytest.approx(43 / 60)                 # win_rate
    assert f[1] == pytest.approx(m.volatility)            # volatility
    assert f[2] == pytest.approx(math.log(1 + 5))         # log(1 + max_win)
    assert f[4] == 720                                    # spin_count


def test_entropy_is_zero_when_every_spin_pays_the_same():
    assert entropy_of({100: 50}) == 0.0


def test_entropy_grows_with_more_distinct_payouts():
    two = entropy_of({0: 50, 20: 50})
    four = entropy_of({0: 25, 20: 25, 60: 25, 100: 25})
    assert four > two > 0


def test_entropy_separates_configs_that_share_win_rate_and_volatility():
    """The reason entropy is in the vector at all: fixture C has only three
    distinct payouts, and a five-payout config with coincidentally equal
    win_rate and volatility is a different game to the player."""
    coarse = entropy_of({0: 204, 20: 474, 100: 42})
    rich = entropy_of({0: 204, 5: 118, 11: 118, 20: 238, 100: 42})
    assert rich > coarse


def test_normalise_maps_each_dimension_into_zero_one():
    vectors = [features(metrics_for(g)) for g in GOLDEN]
    normalised = normalise(vectors)
    for dim in range(5):
        column = [v[dim] for v in normalised]
        assert min(column) == pytest.approx(0.0)
        assert max(column) == pytest.approx(1.0)


def test_identical_vectors_have_zero_distance():
    v = (0.5,) * 5
    assert min_distance(v, [v]) == pytest.approx(0.0)


def test_min_distance_against_empty_set_is_infinite():
    assert min_distance((0.5,) * 5, []) == float("inf")


def test_should_admit_rejects_a_near_duplicate():
    p = Portfolio(entries=[], calibration=None)
    a, b, c = GOLDEN
    # admitting the very same config twice must fail the second time
    assert should_admit(p, metrics_for(c), 0.25)
    p.entries.append(_stub_config(c))
    assert not should_admit(p, metrics_for(c), 0.25)


def test_should_admit_accepts_a_clearly_different_config():
    p = Portfolio(entries=[_stub_config(GOLDEN[2])], calibration=None)
    # fixture A has win_rate 1 and a completely different payout structure
    assert should_admit(p, metrics_for(GOLDEN[0]), 0.25)


def test_calibrate_returns_a_threshold_inside_the_observed_range():
    distances = [0.1, 0.4, 0.6, 0.9]
    d = calibrate(distances)
    assert 0.0 < d < 0.9


def test_portfolio_round_trips_through_json(tmp_path):
    p = Portfolio(entries=[_stub_config(GOLDEN[2])], calibration={"distance": 0.3})
    path = tmp_path / "portfolio.json"
    path.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    back = Portfolio.model_validate_json(path.read_text(encoding="utf-8"))
    assert back.entries[0].reels == p.entries[0].reels
    assert back.calibration == {"distance": 0.3}
