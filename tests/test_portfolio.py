import math

import pytest

from slotmath.evaluation import naive
from slotmath.models.metrics import Metrics, PayoutBucket, build_metrics
from slotmath.solving.portfolio import (
    FEATURE_NAMES,
    Portfolio,
    build_calibration,
    calibrate,
    entropy_of,
    features,
    maybe_calibrate,
    min_distance,
    normalise,
    recalibrate,
    should_admit,
)
from slotmath.verification.verify import ReelConfig
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


def _metrics(win_rate, volatility, max_win, distribution, spin_count):
    """Build a Metrics object with independently controllable feature
    dimensions, so should_admit tests can isolate exactly one dimension
    at a time instead of relying on whichever values a real GameSpec
    happens to produce."""
    return Metrics(
        spin_count=spin_count,
        win_count=round(win_rate * spin_count),
        win_rate=win_rate,
        total_payout_units=0,
        payout_unit_denominator=20,
        rtp=0.95,
        volatility=volatility,
        max_win=max_win,
        payout_distribution=[
            PayoutBucket(payout_units=units, payout=units / 20, combo_count=count)
            for units, count in distribution.items()
        ],
    )


def _config(m):
    return ReelConfig(spec="configs/homework-3x3.json", reels=[[0]], metrics=m)


# Generous fixed ranges covering both the synthetic metrics below and the
# GOLDEN fixtures' real metrics, in FEATURE_NAMES order: win_rate,
# volatility, log_max_win, payout_entropy, spin_count.
CALIBRATION = {
    "distance": 0.25,
    "ranges": [
        (0.0, 1.0),
        (0.0, 5.0),
        (0.0, math.log(1001)),
        (0.0, 3.0),
        (0.0, 2000.0),
    ],
}


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


def test_should_admit_rejects_a_near_duplicate_against_a_one_entry_portfolio():
    """This is the case the sample-relative normalisation bug hid: with
    exactly one existing entry, deriving low/high from the live portfolio
    instead of a fixed calibrated scale stretches any dimension that
    differs at all to exactly 0 and 1, so a near-duplicate looks maximally
    distant and gets wrongly admitted. Against the pre-fix should_admit
    (which ignores calibration and always normalises against whatever is
    currently being compared), this assertion fails: the two points differ
    only in win_rate, so that one dimension gets stretched to {0, 1} and
    the distance comes out as 1.0 -- comfortably over the 0.25 threshold,
    wrongly admitting the near-duplicate."""
    existing = _metrics(0.90, 1.0, 50, {0: 50, 20: 50}, 500)
    near_duplicate = _metrics(0.905, 1.0, 50, {0: 50, 20: 50}, 500)
    p = Portfolio(entries=[_config(existing)], calibration=CALIBRATION)
    assert not should_admit(p, near_duplicate, 0.25)


def test_should_admit_rejects_a_bit_identical_duplicate():
    p = Portfolio(entries=[], calibration=CALIBRATION)
    a, b, c = GOLDEN
    # admitting the very same config twice must fail the second time
    assert should_admit(p, metrics_for(c), 0.25)
    p.entries.append(_stub_config(c))
    assert not should_admit(p, metrics_for(c), 0.25)


def test_should_admit_accepts_a_clearly_different_config():
    existing = _metrics(0.90, 1.0, 50, {0: 50, 20: 50}, 500)
    distinct = _metrics(0.10, 0.2, 3, {0: 900, 20: 100}, 500)
    p = Portfolio(entries=[_config(existing)], calibration=CALIBRATION)
    assert should_admit(p, distinct, 0.25)


def test_should_admit_without_calibration_admits_everything():
    """Before calibration exists there is no meaningful scale to normalise
    against, so should_admit honestly admits every candidate instead of
    running a filter that only pretends to work -- including a
    bit-identical duplicate, which is correct here, not a regression."""
    p = Portfolio(entries=[], calibration=None)
    a, b, c = GOLDEN
    assert should_admit(p, metrics_for(c), 0.25)
    p.entries.append(_stub_config(c))
    assert should_admit(p, metrics_for(c), 0.25)


def test_normalisation_of_a_single_candidate_does_not_depend_on_call_order():
    """What IS order-independent (module docstring, narrowed claim): each
    candidate's normalisation uses the fixed calibrated ranges, never ranges
    derived from whatever else is currently under comparison. So a single
    vector normalises to the same point regardless of what other vectors
    happen to be passed alongside it in the same `normalise` call."""
    a = _metrics(0.30, 2.5, 50, {0: 50, 20: 50}, 500)
    b = _metrics(0.55, 2.5, 50, {0: 50, 20: 50}, 500)
    ranges = CALIBRATION["ranges"]
    solo = normalise([features(a)], ranges=ranges)[0]
    alongside = normalise([features(a), features(b)], ranges=ranges)[0]
    assert solo == pytest.approx(alongside)


def test_greedy_admission_is_order_dependent_despite_fixed_calibration():
    """The caveat the module docstring narrows down to: fixing the
    normalisation scale does NOT make the overall admission *decisions*
    order-independent, because should_admit is greedy against whatever is
    already in the portfolio. A and B are near-duplicates of each other; C
    is far from A but close enough to B to be blocked by it. Offering them
    as A, B, C admits {A, C} (A blocks B; C clears A). Offering the same
    three as B, A, C admits only {B} (B blocks both A and C). Same
    candidates, same fixed calibration, different admitted sets -- this is
    the counterexample the module docstring now documents instead of
    (wrongly) claiming order never matters."""
    a = _metrics(0.30, 2.5, 50, {0: 50, 20: 50}, 500)
    b = _metrics(0.55, 2.5, 50, {0: 50, 20: 50}, 500)
    c = _metrics(0.5132, 3.888, 50, {0: 50, 20: 50}, 500)
    threshold = 0.30

    def admitted(order, names):
        p = Portfolio(entries=[], calibration=CALIBRATION)
        result = []
        for m, name in zip(order, names):
            if should_admit(p, m, threshold):
                p.entries.append(_config(m))
                result.append(name)
        return result

    assert admitted([a, b, c], ["A", "B", "C"]) == ["A", "C"]
    assert admitted([b, a, c], ["B", "A", "C"]) == ["B"]


def test_calibrate_returns_a_threshold_inside_the_observed_range():
    distances = [0.1, 0.4, 0.6, 0.9]
    d = calibrate(distances)
    assert 0.0 < d < 0.9


def test_calibrate_of_empty_distances_returns_the_default_threshold():
    assert calibrate([]) == 0.25


def test_maybe_calibrate_admits_unconditionally_below_the_calibration_size():
    """Below the requested size, maybe_calibrate must not compute anything
    yet -- the portfolio is still in its unfiltered calibration-collection
    phase, and calibration stays None so should_admit keeps admitting
    everything (see test_should_admit_without_calibration_admits_everything)."""
    reference = _metrics(0.90, 1.0, 50, {0: 50, 20: 50}, 500)
    distinct_a = _metrics(0.10, 0.2, 3, {0: 900, 20: 100}, 500)
    p = Portfolio(entries=[_config(reference), _config(distinct_a)], calibration=None)
    assert maybe_calibrate(p, 3) is False
    assert p.calibration is None


def test_maybe_calibrate_populates_ranges_and_distance_at_the_threshold():
    reference = _metrics(0.90, 1.0, 50, {0: 50, 20: 50}, 500)
    distinct_a = _metrics(0.10, 0.2, 3, {0: 900, 20: 100}, 500)
    distinct_b = _metrics(0.50, 0.6, 10, {0: 250, 5: 250, 20: 250, 60: 250}, 1000)
    p = Portfolio(
        entries=[_config(reference), _config(distinct_a), _config(distinct_b)],
        calibration=None,
    )
    assert maybe_calibrate(p, 3) is True
    assert p.calibration is not None
    assert "distance" in p.calibration
    assert "ranges" in p.calibration
    assert len(p.calibration["ranges"]) == len(FEATURE_NAMES)
    # calling again is a no-op: calibration already exists
    frozen = p.calibration
    assert maybe_calibrate(p, 3) is False
    assert p.calibration == frozen


def test_calibration_derived_from_entries_then_genuinely_filters():
    """The whole point of this round: once maybe_calibrate has fired, the
    filter is actually engaged rather than perpetually taking the
    admit-everything branch. A near-duplicate of one of the calibrating
    entries is rejected; a config clearly outside the observed spread on
    every dimension is admitted."""
    reference = _metrics(0.90, 1.0, 50, {0: 50, 20: 50}, 500)
    distinct_a = _metrics(0.10, 0.2, 3, {0: 900, 20: 100}, 500)
    distinct_b = _metrics(0.50, 0.6, 10, {0: 250, 5: 250, 20: 250, 60: 250}, 1000)
    near_duplicate = _metrics(0.905, 1.0, 50, {0: 50, 20: 50}, 500)
    genuinely_different = _metrics(
        0.99, 4.5, 500, {0: 1, 5: 1, 20: 1, 60: 1, 300: 1}, 100
    )

    p = Portfolio(
        entries=[_config(reference), _config(distinct_a), _config(distinct_b)],
        calibration=None,
    )
    assert maybe_calibrate(p, 3) is True
    threshold = p.calibration["distance"]

    assert not should_admit(p, near_duplicate, threshold)
    assert should_admit(p, genuinely_different, threshold)


def test_recalibrate_replaces_an_existing_calibration():
    reference = _metrics(0.90, 1.0, 50, {0: 50, 20: 50}, 500)
    distinct_a = _metrics(0.10, 0.2, 3, {0: 900, 20: 100}, 500)
    distinct_b = _metrics(0.50, 0.6, 10, {0: 250, 5: 250, 20: 250, 60: 250}, 1000)
    stale = {"distance": 0.5, "ranges": [(0.0, 1.0)] * len(FEATURE_NAMES)}
    p = Portfolio(
        entries=[_config(reference), _config(distinct_a), _config(distinct_b)],
        calibration=stale,
    )
    assert recalibrate(p) is True
    assert p.calibration is not None
    assert p.calibration != stale
    assert p.calibration == build_calibration(p.entries)


def test_recalibrate_on_an_empty_portfolio_clears_rather_than_keeps_stale_calibration():
    stale = {"distance": 0.5, "ranges": [(0.0, 1.0)] * len(FEATURE_NAMES)}
    p = Portfolio(entries=[], calibration=stale)
    assert recalibrate(p) is False
    assert p.calibration is None


def test_portfolio_round_trips_through_json(tmp_path):
    p = Portfolio(entries=[_stub_config(GOLDEN[2])], calibration={"distance": 0.3})
    path = tmp_path / "portfolio.json"
    path.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    back = Portfolio.model_validate_json(path.read_text(encoding="utf-8"))
    assert back.entries[0].reels == p.entries[0].reels
    assert back.calibration == {"distance": 0.3}
