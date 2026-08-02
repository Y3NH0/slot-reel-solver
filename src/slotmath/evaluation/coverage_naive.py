"""Coverage attribution by full board enumeration. The trust anchor.

Deliberately dumb, exactly like `naive.py`: expand every board, compare cells
directly, decide attribution in the open. Too slow for a solver loop; its job
is to be correct by inspection so `coverage_engine.py` has something honest to
be checked against.

The match-and-attribution loop below is reimplemented from scratch in
`coverage_engine.py`. That duplication is the point -- see the note in
`coverage.py`. Do not factor the two together.
"""

from __future__ import annotations

from itertools import product
from typing import Sequence

from slotmath.evaluation.coverage import (
    CoverageCounts,
    CoverageReport,
    build_report,
)
from slotmath.evaluation.windows import reel_windows
from slotmath.models.metrics import check_board_budget
from slotmath.models.spec import GameSpec


def analyze(
    spec: GameSpec, reels: Sequence[Sequence[int]], budget: int | None = None
) -> CoverageReport:
    if len(reels) != spec.grid.cols:
        raise ValueError(f"expected {spec.grid.cols} reels, got {len(reels)}")
    for reel in reels:
        unknown = set(reel) - set(spec.symbols)
        if unknown:
            raise ValueError(f"reel contains undeclared symbols: {sorted(unknown)}")

    spin_count = (
        check_board_budget(reels)
        if budget is None
        else check_board_budget(reels, budget)
    )

    raw: dict[tuple[int, int], int] = {}
    winning: dict[tuple[int, int], int] = {}
    max_eligible: dict[tuple[int, int], int] = {}
    unique_credit: dict[tuple[int, int], int] = {}

    per_column = [reel_windows(reel, spec.grid.rows) for reel in reels]
    for columns in product(*per_column):
        # (pattern_index, symbol, payout_units) for every positive-paying match
        earners: list[tuple[int, int, int]] = []
        for pattern_index, pattern in enumerate(spec.patterns):
            first_col, first_row = pattern.cells[0]
            symbol = columns[first_col][first_row]
            if not all(columns[c][r] == symbol for c, r in pattern.cells):
                continue
            key = (symbol, pattern_index)
            raw[key] = raw.get(key, 0) + 1
            units = spec.payout_units(symbol, pattern)
            if units > 0:
                winning[key] = winning.get(key, 0) + 1
                earners.append((pattern_index, symbol, units))

        if not earners:
            continue

        if spec.combine == "max":
            top_units = max(units for _, _, units in earners)
            top = [item for item in earners if item[2] == top_units]
        else:
            # Under "sum" every positive match really does contribute to the
            # payout, so every one of them is credited.
            top = earners

        for pattern_index, symbol, _ in top:
            key = (symbol, pattern_index)
            max_eligible[key] = max_eligible.get(key, 0) + 1
        if len(top) == 1:
            pattern_index, symbol, _ = top[0]
            key = (symbol, pattern_index)
            unique_credit[key] = unique_credit.get(key, 0) + 1

    counts = {
        key: CoverageCounts(
            raw=raw.get(key, 0),
            winning=winning.get(key, 0),
            max_eligible=max_eligible.get(key, 0),
            unique_credit=unique_credit.get(key, 0),
        )
        for key in set(raw) | set(winning) | set(max_eligible) | set(unique_credit)
    }
    return build_report(spec, reels, counts, spin_count)
