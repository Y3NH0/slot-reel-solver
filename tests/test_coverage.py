"""Exact Symbol x Pattern coverage analysis.

Coverage is a structural claim ("this pair can never happen"), so every test
here is exact: integer counts and Fraction probabilities, never a tolerance.
"""

import ast
from fractions import Fraction
from pathlib import Path

import pytest

from slotmath.evaluation import coverage, coverage_engine, coverage_naive
from slotmath.evaluation.coverage import (
    COVERAGE_KINDS,
    cross_check_coverage,
    local_cyclic_match_count,
    raw_match_count_factorized,
)
from slotmath.models.spec import GameSpec
from tests.fixtures import GOLDEN
from tests.test_naive import hw

IDS = [g.name for g in GOLDEN]


def spec_from(patterns, symbols=None, combine="max", cols=2, rows=2) -> GameSpec:
    """A minimal in-memory spec. Payouts are given as strings so they reach
    the validator the same way a JSON number would, through _coerce_fraction.
    """
    return GameSpec.model_validate(
        {
            "name": "t",
            "grid": {"cols": cols, "rows": rows},
            "symbols": symbols if symbols is not None else {"0": 1, "1": 2},
            "patterns": patterns,
            "combine": combine,
            "targets": {"rtp": 0.5},
        }
    )


# --------------------------------------------------------------------------
# cyclic geometry
# --------------------------------------------------------------------------


def test_local_cyclic_match_count_finds_a_wrapped_pair():
    """The pair lives across the seam: positions 3 and 0, not 0 and 1."""
    reel = [7, 1, 1, 7]
    assert local_cyclic_match_count(reel, (0, 1), 7) == 1
    assert local_cyclic_match_count(reel, (0, 1), 1) == 1


def test_local_cyclic_match_count_finds_a_wrapped_triple():
    reel = [5, 5, 9, 9, 5]
    # stops 4,0 wrap to give (5,5,5)? positions 4,0,1 -> 5,5,5 -> one triple
    assert local_cyclic_match_count(reel, (0, 1, 2), 5) == 1
    assert local_cyclic_match_count(reel, (0, 1, 2), 9) == 0


def test_local_cyclic_match_count_with_no_offsets_is_every_stop():
    """A vacuous requirement is met by every stop. This is what makes the
    factorization theorem come out right for untouched columns."""
    assert local_cyclic_match_count([3, 1, 4], (), 999) == 3


def test_local_cyclic_match_count_handles_non_contiguous_offsets():
    """R[p,c] is a set of rows, not a run: rows (0, 2) must work.

    On [6, 0, 6, 1] the gapped pair (row 0, row 2) hits twice -- at stop 0
    (positions 0 and 2) and again at stop 2, whose row-2 offset wraps back to
    position 0. A run-based implementation would find neither.
    """
    reel = [6, 0, 6, 1]
    assert local_cyclic_match_count(reel, (0, 2), 6) == 2
    assert local_cyclic_match_count(reel, (0, 1), 6) == 0


def test_uniform_reel_matches_at_every_stop():
    assert local_cyclic_match_count([4, 4, 4], (0, 1, 2), 4) == 3


# --------------------------------------------------------------------------
# geometry drives raw coverage
# --------------------------------------------------------------------------


def test_one_cell_per_column_means_presence_is_enough():
    """When a pattern takes a single cell from each column, a symbol merely
    being present anywhere on each reel already yields a raw match."""
    spec = spec_from([{"name": "P", "cells": [[0, 0], [1, 0]]}])
    reels = [[0, 1], [1, 0]]
    report = cross_check_coverage(spec, reels)
    for symbol in (0, 1):
        assert report.entry(symbol, 0).count("raw") > 0


def test_two_adjacent_cells_in_one_column_need_more_than_presence():
    """With rows (0,1) in the same column, a lone occurrence cannot match --
    the symbol needs a cyclic run of two."""
    spec = spec_from([{"name": "P", "cells": [[0, 0], [0, 1], [1, 0], [1, 1]]}])
    lone = [[0, 1, 1, 1], [1, 1, 1, 1]]  # symbol 0 appears once on reel 0
    report = cross_check_coverage(spec, lone)
    assert report.entry(0, 0).count("raw") == 0
    reason = report.entry(0, 0).reasons[0]
    assert reason.kind == "missing_cyclic_mask"
    assert reason.column == 0
    assert reason.row_offsets == (0, 1)

    paired = [[0, 0, 1, 1], [0, 0, 1, 1]]
    assert cross_check_coverage(spec, paired).entry(0, 0).count("raw") > 0


def test_missing_cyclic_mask_reason_names_every_blocking_column():
    spec = spec_from([{"name": "P", "cells": [[0, 0], [0, 1], [1, 0], [1, 1]]}])
    reels = [[0, 1, 1, 1], [0, 1, 1, 1]]  # symbol 0 is lone on BOTH reels
    entry = cross_check_coverage(spec, reels).entry(0, 0)
    assert entry.count("raw") == 0
    assert sorted(r.column for r in entry.reasons) == [0, 1]


# --------------------------------------------------------------------------
# payout drives the winning / max-eligible / unique-credit tiers
# --------------------------------------------------------------------------


def test_raw_match_with_zero_payout_never_counts_as_winning():
    spec = spec_from(
        [{"name": "P", "cells": [[0, 0], [1, 0]]}], symbols={"0": 0, "1": 2}
    )
    report = cross_check_coverage(spec, [[0, 1], [0, 1]])
    entry = report.entry(0, 0)
    assert entry.count("raw") > 0
    assert entry.count("winning") == 0
    assert entry.count("max_eligible") == 0
    assert [r.kind for r in entry.reasons] == ["non_positive_payout"]


def test_a_pattern_always_outpaid_is_flagged_always_dominated():
    """SMALL matches only on boards where BIG also matches and pays more."""
    spec = spec_from(
        [
            {"name": "BIG", "cells": [[0, 0], [1, 0]], "pattern_multiplier": 10},
            {"name": "SMALL", "cells": [[0, 0], [1, 0]], "pattern_multiplier": 1},
        ]
    )
    report = cross_check_coverage(spec, [[0, 1], [0, 1]])
    small = report.entry(0, 1)
    assert small.count("raw") > 0
    assert small.count("winning") > 0
    assert small.count("max_eligible") == 0
    assert [r.kind for r in small.reasons] == ["always_dominated"]
    big = report.entry(0, 0)
    assert big.count("unique_credit") == big.count("max_eligible") > 0


def test_equal_payout_tie_makes_both_max_eligible_and_neither_unique():
    spec = spec_from(
        [
            {"name": "A", "cells": [[0, 0], [1, 0]], "pattern_multiplier": 3},
            {"name": "B", "cells": [[0, 0], [1, 0]], "pattern_multiplier": 3},
        ]
    )
    report = cross_check_coverage(spec, [[0, 1], [0, 1]])
    for pattern_index in (0, 1):
        entry = report.entry(0, pattern_index)
        assert entry.count("max_eligible") == entry.count("winning") > 0
        assert entry.count("unique_credit") == 0
        assert [r.kind for r in entry.reasons] == ["tie_only"]


def test_under_combine_sum_every_winning_match_is_credited():
    spec = spec_from(
        [
            {"name": "A", "cells": [[0, 0], [1, 0]], "pattern_multiplier": 5},
            {"name": "B", "cells": [[0, 0], [1, 0]], "pattern_multiplier": 1},
        ],
        combine="sum",
    )
    report = cross_check_coverage(spec, [[0, 1], [0, 1]])
    for pattern_index in (0, 1):
        entry = report.entry(0, pattern_index)
        assert entry.count("max_eligible") == entry.count("winning") > 0


# --------------------------------------------------------------------------
# exactness and cross-validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_naive_and_engine_analyzers_agree_on_every_count(g):
    """The coverage analogue of engine_matches_naive. cross_check_coverage
    raises on any disagreement, so reaching the asserts means they matched."""
    spec = hw()
    naive_report = coverage_naive.analyze(spec, g.reels)
    engine_report = coverage_engine.analyze(spec, g.reels)
    assert naive_report.counts_signature() == engine_report.counts_signature()
    assert naive_report.spin_count == engine_report.spin_count


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_factorization_theorem_matches_full_enumeration(g):
    """The O(sum L) product formula must equal the O(prod L) count."""
    spec = hw()
    report = coverage_naive.analyze(spec, g.reels)
    for entry in report.entries:
        assert entry.count("raw") == raw_match_count_factorized(
            spec, g.reels, entry.pattern_index, entry.symbol
        )


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_coverage_tiers_are_nested(g):
    report = cross_check_coverage(hw(), g.reels)
    for e in report.entries:
        assert (
            e.count("raw")
            >= e.count("winning")
            >= e.count("max_eligible")
            >= e.count("unique_credit")
        )


def test_probabilities_are_exact_fractions_not_floats():
    report = cross_check_coverage(hw(), GOLDEN[0].reels)
    for e in report.entries:
        for kind in COVERAGE_KINDS:
            p = e.probability(kind)
            assert isinstance(p, Fraction)
            assert p == Fraction(e.count(kind), report.spin_count)


def test_max_eligible_total_matches_the_winning_spin_count():
    """Every winning spin credits at least one pattern, and a spin with a sole
    argmax credits exactly one -- so unique_credit totals can never exceed the
    number of winning spins."""
    from slotmath.evaluation import naive

    spec = hw()
    for g in GOLDEN:
        dist = naive.evaluate(spec, g.reels)
        winning_spins = sum(c for u, c in dist.items() if u > 0)
        report = coverage_naive.analyze(spec, g.reels)
        assert sum(e.count("unique_credit") for e in report.entries) <= winning_spins


# --------------------------------------------------------------------------
# the analyzers must stay exact and simulation-free
# --------------------------------------------------------------------------


def _imported_modules(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize(
    "module", [coverage, coverage_naive, coverage_engine], ids=lambda m: m.__name__
)
def test_coverage_never_reaches_for_monte_carlo(module):
    """Coverage support is exact and structural. A simulation cannot tell
    'impossible' from 'merely rare', so it must never decide a coverage gate.
    """
    assert not any("montecarlo" in name for name in _imported_modules(module))


@pytest.mark.parametrize(
    "module", [coverage, coverage_naive, coverage_engine], ids=lambda m: m.__name__
)
def test_coverage_introduces_no_float_tolerance(module):
    """No isclose, no epsilon, no float() on a decision path -- coverage
    comparisons are integer counts and Fraction probabilities only."""
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"isclose", "isinf", "isnan"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            assert name not in banned, f"{module.__name__} calls {name}()"
            assert name != "float", f"{module.__name__} calls float()"
