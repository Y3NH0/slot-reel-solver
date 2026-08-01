import random
import pytest
from slotmath import engine, naive
from slotmath.spec import GameSpec
from tests.test_naive import hw


def test_engine_matches_naive_on_homework_fixture_c():
    spec = hw()
    reels = [
        [2, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1],
        [2, 2, 2, 2, 3, 2],
        [4, 3, 2, 2, 1, 3, 2, 2, 2, 2],
    ]
    assert engine.evaluate(spec, reels) == naive.evaluate(spec, reels)


def _random_spec(rng: random.Random) -> GameSpec:
    cols = rng.randint(1, 3)
    rows = rng.randint(2, 4)
    n_symbols = rng.randint(2, 4)
    every = [(c, r) for c in range(cols) for r in range(rows)]
    patterns = []
    for i in range(rng.randint(1, 3)):
        size = rng.randint(1, len(every))
        patterns.append({
            "name": f"P{i}",
            "cells": rng.sample(every, size),
            "pattern_multiplier": rng.choice([1, 2, 5]),
        })
    return GameSpec.model_validate({
        "name": "rnd",
        "grid": {"cols": cols, "rows": rows},
        "symbols": {str(s): rng.choice([0.25, 0.55, 1, 3, 5]) for s in range(n_symbols)},
        "patterns": patterns,
        "combine": rng.choice(["max", "sum"]),
        "targets": {"rtp": 0.95},
    })


@pytest.mark.parametrize("seed", range(30))
def test_engine_equals_naive_on_random_specs(seed):
    """The highest-value test in the suite: it covers the correctness of the
    signature reduction across grid shapes, pattern masks and combine modes."""
    rng = random.Random(seed)
    spec = _random_spec(rng)
    symbols = sorted(spec.symbols)
    reels = [
        [rng.choice(symbols) for _ in range(rng.randint(spec.grid.rows, spec.grid.rows + 5))]
        for _ in range(spec.grid.cols)
    ]
    assert engine.evaluate(spec, reels) == naive.evaluate(spec, reels)


def test_histogram_counts_sum_to_reel_length():
    spec = hw()
    reels = [[2, 2, 2, 3, 0], [1, 1, 1, 1], [4, 4, 4, 4, 4, 0]]
    hists = engine.signature_histograms(spec, reels)
    assert [sum(h.values()) for h in hists] == [5, 4, 6]


def test_budget_exceeded_reports_offending_columns():
    spec = hw()
    # NOTE: a strip that cycles through `range(5)` with no adjacent repeats
    # (as in the task brief's draft) collapses to exactly one signature per
    # homework column -- every pattern entry only ever observes mismatched
    # cells, so the signature is always (None, ...). That can never exceed
    # any positive budget. Runs of each symbol are used instead so that the
    # "all-same" and "pair-only" signature classes documented in
    # tests/test_windows.py::test_distinct_signature_count_for_homework_column_is_16
    # actually get exercised, driving each column's histogram past 1 entry.
    strip = [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4]
    reels = [strip, strip, strip]
    with pytest.raises(engine.SignatureBudgetExceeded) as exc:
        engine.evaluate(spec, reels, budget=10)
    assert len(exc.value.sizes) == 3
    assert all(isinstance(col, int) and count > 0 for col, count in exc.value.sizes)
    assert "column" in str(exc.value)
