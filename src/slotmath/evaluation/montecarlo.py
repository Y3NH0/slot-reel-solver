"""Layer 3: an independent simulation path.

Layers 1 and 2 both rest on one shared assumption -- that the translation
from GameSpec to pattern matching is correct. If that translation is wrong
(the classic case being (col, row) written as (row, col)), naive.py and
engine.py are wrong together and cross-checking them stays silent.

So this module deliberately shares nothing with them: it spins for real,
indexes the strips directly, builds the board itself, and compares grid
cells with its own copy of the matching logic. It does not import windows.py
or engine.py -- there is a test that enforces this.

Because the seed is fixed, the check is deterministic (passing today means
passing forever), which is what makes it usable as a hard gate rather than a
warning nobody reads.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction
from math import sqrt
from typing import Sequence

from slotmath.models.spec import GameSpec


@dataclass(frozen=True)
class SimResult:
    spins: int
    total_units: int
    win_count: int


def _board_payout_units(spec: GameSpec, board: list[list[int]]) -> int:
    """board[col][row]. Independent copy of the combine logic -- see module docstring."""
    wins: list[int] = []
    for pattern in spec.patterns:
        cells = pattern.cells
        symbol = board[cells[0][0]][cells[0][1]]
        matched = True
        for col, row in cells:
            if board[col][row] != symbol:
                matched = False
                break
        if matched:
            wins.append(spec.payout_units(symbol, pattern))
    if not wins:
        return 0
    return max(wins) if spec.combine == "max" else sum(wins)


def simulate(
    spec: GameSpec, reels: Sequence[Sequence[int]], spins: int, seed: int
) -> SimResult:
    rng = random.Random(seed)
    rows = spec.grid.rows
    lengths = [len(reel) for reel in reels]
    total_units = 0
    win_count = 0

    for _ in range(spins):
        board = []
        for reel, length in zip(reels, lengths):
            stop = rng.randrange(length)
            board.append([reel[(stop + k) % length] for k in range(rows)])
        units = _board_payout_units(spec, board)
        total_units += units
        if units:
            win_count += 1

    return SimResult(spins=spins, total_units=total_units, win_count=win_count)


def sigma_deviation(
    spec: GameSpec,
    reels: Sequence[Sequence[int]],
    sim: SimResult,
    exact_distribution: dict[int, int],
) -> float:
    """How many standard errors the simulated mean sits from the exact mean.

    The variance comes from the true payout distribution, not an assumption.
    """
    denominator = spec.payout_unit_denominator()
    spin_count = sum(exact_distribution.values())
    exact_mean = Fraction(
        sum(u * c for u, c in exact_distribution.items()), denominator * spin_count
    )
    variance = sum(
        c * (Fraction(u, denominator) - exact_mean) ** 2
        for u, c in exact_distribution.items()
    ) / spin_count

    if variance == 0:
        observed = Fraction(sim.total_units, denominator * sim.spins)
        return 0.0 if observed == exact_mean else float("inf")

    standard_error = sqrt(float(variance) / sim.spins)
    observed = sim.total_units / (denominator * sim.spins)
    return (observed - float(exact_mean)) / standard_error
