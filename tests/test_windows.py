import pytest
from slotmath.spec import GameSpec
from slotmath.windows import ColumnPlan, column_plans, reel_windows, window_signature


def test_windows_wrap_around_cyclically():
    assert reel_windows([1, 2, 3, 4], 3) == [
        (1, 2, 3), (2, 3, 4), (3, 4, 1), (4, 1, 2),
    ]


def test_window_count_equals_strip_length():
    assert len(reel_windows([0] * 7, 3)) == 7


def test_strip_length_equal_to_rows_wraps_onto_itself():
    assert reel_windows([1, 2, 3], 3) == [(1, 2, 3), (2, 3, 1), (3, 1, 2)]


def test_strip_shorter_than_rows_is_rejected():
    with pytest.raises(ValueError, match="at least 3"):
        reel_windows([1, 2], 3)


def _spec_3x3():
    return GameSpec.model_validate({
        "name": "t",
        "grid": {"cols": 3, "rows": 3},
        "symbols": {"0": 0.25, "1": 0.55, "2": 1, "3": 3, "4": 5},
        "patterns": [
            {"name": "TL", "cells": [[0, 0], [0, 1], [1, 0], [1, 1]]},
            {"name": "BL", "cells": [[0, 1], [0, 2], [1, 1], [1, 2]]},
            {"name": "FULL", "cells": "all", "pattern_multiplier": 5},
        ],
        "targets": {"rtp": 0.95},
    })


def test_column_plan_lists_only_patterns_touching_that_column():
    plans = column_plans(_spec_3x3())
    # column 2 is touched only by FULL (pattern index 2)
    assert [idx for idx, _ in plans[2].entries] == [2]
    # column 0 is touched by TL, BL, FULL
    assert [idx for idx, _ in plans[0].entries] == [0, 1, 2]


def test_column_plan_records_rows_used_in_that_column():
    plans = column_plans(_spec_3x3())
    entries = dict(plans[0].entries)
    assert entries[0] == (0, 1)          # TL uses rows 0,1 in column 0
    assert entries[1] == (1, 2)          # BL uses rows 1,2 in column 0
    assert entries[2] == (0, 1, 2)       # FULL uses all rows


def test_signature_is_symbol_when_all_rows_match_else_none():
    plan = column_plans(_spec_3x3())[0]
    # window (2,2,2): TL rows(0,1) all 2, BL rows(1,2) all 2, FULL all 2
    assert window_signature((2, 2, 2), plan) == (2, 2, 2)
    # window (2,2,3): TL matches on 2, BL does not, FULL does not
    assert window_signature((2, 2, 3), plan) == (2, None, None)
    # window (3,2,2): TL no, BL yes on 2, FULL no
    assert window_signature((3, 2, 2), plan) == (None, 2, None)
    # window (0,1,2): nothing matches
    assert window_signature((0, 1, 2), plan) == (None, None, None)


def test_column_plan_sorts_out_of_order_rows():
    """The sorted() call in column_plans is load-bearing: it handles cells
    given out of order. Pattern with cells [[0,2],[0,0]] should record rows
    (0, 2) in ascending order."""
    spec = GameSpec.model_validate({
        "name": "t",
        "grid": {"cols": 3, "rows": 3},
        "symbols": {"0": 0.25, "1": 0.55, "2": 1, "3": 3, "4": 5},
        "patterns": [
            {"name": "OutOfOrder", "cells": [[0, 2], [0, 0]]},
        ],
        "targets": {"rtp": 0.95},
    })
    plans = column_plans(spec)
    entries = dict(plans[0].entries)
    assert entries[0] == (0, 2)


def test_long_strip_cyclic_wrapping():
    """Cyclic wrapping with a strip much longer than rows.
    Tests both interior windows and wrap-around at the boundaries."""
    strip = list(range(100))
    windows = reel_windows(strip, 3)
    # Interior window: position 97 wraps within the strip
    assert windows[97] == (97, 98, 99)
    # Wrap around: position 99 wraps to start
    assert windows[99] == (99, 0, 1)
    # Wrap around: position 98 wraps to start
    assert windows[98] == (98, 99, 0)


def test_distinct_signature_count_for_homework_column_is_16():
    """5 all-same + 5 top-pair-only + 5 bottom-pair-only + 1 none = 16.

    (The brief's comment listing "20 top-pair" and "20 bottom-pair" describes
    the count of windows in each category, not distinct signatures. With the
    given patterns and 5 symbols, each category produces only 5 distinct
    signatures since the signature doesn't encode which non-matching position
    differs.)
    """
    plan = column_plans(_spec_3x3())[0]
    seen = {
        window_signature((a, b, c), plan)
        for a in range(5) for b in range(5) for c in range(5)
    }
    assert len(seen) == 16
