"""Full-enumeration evaluator. The trust anchor.

This module is deliberately dumb: it expands the board, compares cells
directly, and does not use the signature abstraction in windows.py. It is
too slow for the solver's inner loop and is only called by the verifier and
the tests. Its job is to be obviously correct, not fast.

The combine logic below is duplicated in engine.py and montecarlo.py on
purpose -- three independent copies is how a mistake in one of them becomes
visible instead of silent. Do not factor it out.
"""

from __future__ import annotations

from itertools import product
from typing import Sequence

from slotmath.models.spec import GameSpec
from slotmath.evaluation.windows import reel_windows


def grid_payout_units(spec: GameSpec, columns: Sequence[tuple[int, ...]]) -> int:
    """columns[col][row] -> symbol. Returns payout in 1/D units."""
    wins: list[int] = []
    for pattern in spec.patterns:
        first_col, first_row = pattern.cells[0]
        symbol = columns[first_col][first_row]
        if all(columns[c][r] == symbol for c, r in pattern.cells):
            wins.append(spec.payout_units(symbol, pattern))
    if not wins:
        return 0
    return max(wins) if spec.combine == "max" else sum(wins)


def evaluate(spec: GameSpec, reels: Sequence[Sequence[int]]) -> dict[int, int]:
    """Full cycle: every combination of stop positions counted exactly once."""
    if len(reels) != spec.grid.cols:
        raise ValueError(f"expected {spec.grid.cols} reels, got {len(reels)}")
    for reel in reels:
        unknown = set(reel) - set(spec.symbols)
        if unknown:
            raise ValueError(f"reel contains undeclared symbols: {sorted(unknown)}")

    per_column = [reel_windows(reel, spec.grid.rows) for reel in reels]
    dist: dict[int, int] = {}
    for columns in product(*per_column):
        units = grid_payout_units(spec, columns)
        dist[units] = dist.get(units, 0) + 1
    return dist
