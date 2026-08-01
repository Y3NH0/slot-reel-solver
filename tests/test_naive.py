import pytest
from slotmath.evaluation.naive import evaluate, grid_payout_units
from slotmath.models.spec import GameSpec

HOMEWORK = {
    "name": "hw",
    "grid": {"cols": 3, "rows": 3},
    "symbols": {"0": 0.25, "1": 0.55, "2": 1, "3": 3, "4": 5},
    "patterns": [
        {"name": "TL", "cells": [[0, 0], [0, 1], [1, 0], [1, 1]]},
        {"name": "TR", "cells": [[1, 0], [1, 1], [2, 0], [2, 1]]},
        {"name": "BL", "cells": [[0, 1], [0, 2], [1, 1], [1, 2]]},
        {"name": "BR", "cells": [[1, 1], [1, 2], [2, 1], [2, 2]]},
        {"name": "FULL", "cells": "all", "pattern_multiplier": 5},
    ],
    "targets": {"rtp": 0.95, "min_win_rate": 0.55},
}


def hw(**over):
    return GameSpec.model_validate({**HOMEWORK, **over})


@pytest.mark.parametrize(
    "symbol,expected_units",
    [(0, 25), (1, 55), (2, 100), (3, 300), (4, 500)],
)
def test_uniform_reels_pay_full_board_for_every_symbol(symbol, expected_units):
    """Hand-computed: every stop shows 9 identical symbols, so FULL always wins
    and max-only picks it: payout = symbol_multiplier * 5, in 1/20 units."""
    spec = hw()
    reels = [[symbol] * 4, [symbol] * 5, [symbol] * 6]
    dist = evaluate(spec, reels)
    assert dist == {expected_units: 4 * 5 * 6}


def test_no_win_board_pays_zero():
    spec = hw()
    # every column is a strict cycle of 3 distinct symbols offset so no 2x2 forms
    reels = [[0, 1, 2], [1, 2, 0], [2, 0, 1]]
    dist = evaluate(spec, reels)
    assert set(dist) == {0}
    assert dist[0] == 27


def test_max_only_picks_the_largest_winning_pattern():
    spec = hw()
    grid = [(2, 2, 2), (2, 2, 2), (2, 2, 2)]   # all nine identical -> all 5 win
    # max is FULL: 1 * 5 = 5 -> 100 units (not the sum 9*20 = 180)
    assert grid_payout_units(spec, grid) == 100


def test_sum_combine_adds_every_winning_pattern():
    spec = hw(combine="sum")
    grid = [(2, 2, 2), (2, 2, 2), (2, 2, 2)]
    # TL+TR+BL+BR = 4*20, FULL = 100 -> 180
    assert grid_payout_units(spec, grid) == 180


def test_sum_combine_with_two_overlapping_patterns_only():
    spec = hw(combine="sum")
    # top 2x3 block of symbol 0, bottom row spoils BL/BR/FULL
    grid = [(0, 0, 3), (0, 0, 4), (0, 0, 3)]
    # TL = 5 units, TR = 5 units -> 10
    assert grid_payout_units(spec, grid) == 10


def test_max_combine_with_two_overlapping_patterns_only():
    spec = hw()
    grid = [(0, 0, 3), (0, 0, 4), (0, 0, 3)]
    assert grid_payout_units(spec, grid) == 5


def test_distribution_counts_sum_to_spin_count():
    spec = hw()
    reels = [[0, 1, 2, 2, 3], [1, 1, 2, 0], [2, 2, 2, 4, 1, 0]]
    dist = evaluate(spec, reels)
    assert sum(dist.values()) == 5 * 4 * 6
