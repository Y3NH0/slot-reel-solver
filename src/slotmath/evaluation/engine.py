"""Signature-aggregating evaluator.

Pattern matching decomposes per column: a pattern only observes whether its
cells within one column are all the same symbol, and which. So each reel can
be collapsed from L positions into a histogram over distinct signatures, and
the enumeration runs over signature combinations with integer weights. The
result is exact, not an approximation -- probabilities are count ratios.

Cost drops from prod(L_c) to prod(|Sig_c|).

The combine logic below duplicates naive.py and montecarlo.py on purpose.
See the note in naive.py.
"""

from __future__ import annotations

from itertools import product
from math import prod
from typing import Sequence

from slotmath.models.spec import GameSpec
from slotmath.evaluation.windows import (
    ColumnPlan,
    column_plans,
    reel_windows,
    window_signature,
)


class SignatureBudgetExceeded(Exception):
    def __init__(self, sizes: list[tuple[int, int]], total: int, budget: int):
        self.sizes = sizes
        self.total = total
        self.budget = budget
        detail = ", ".join(f"column {c}: {n} signatures" for c, n in sizes)
        super().__init__(
            f"signature space is {total} combinations, over the budget of {budget} "
            f"({detail}). Shrink the grid, the pattern set, or the symbol count."
        )


def signature_histograms(
    spec: GameSpec, reels: Sequence[Sequence[int]]
) -> list[dict[tuple[int | None, ...], int]]:
    plans = column_plans(spec)
    histograms = []
    for plan, reel in zip(plans, reels):
        hist: dict[tuple[int | None, ...], int] = {}
        for window in reel_windows(reel, spec.grid.rows):
            sig = window_signature(window, plan)
            hist[sig] = hist.get(sig, 0) + 1
        histograms.append(hist)
    return histograms


def _payout_units(
    spec: GameSpec,
    plans: list[ColumnPlan],
    signatures: tuple[tuple[int | None, ...], ...],
) -> int:
    # For each pattern, collect the symbol each touched column reports.
    claims: dict[int, list[int | None]] = {i: [] for i in range(len(spec.patterns))}
    for plan, sig in zip(plans, signatures):
        for (pattern_index, _), symbol in zip(plan.entries, sig):
            claims[pattern_index].append(symbol)

    wins: list[int] = []
    for index, reported in claims.items():
        if not reported or reported[0] is None:
            continue
        if all(s == reported[0] for s in reported):
            wins.append(spec.payout_units(reported[0], spec.patterns[index]))
    if not wins:
        return 0
    return max(wins) if spec.combine == "max" else sum(wins)


def evaluate(
    spec: GameSpec, reels: Sequence[Sequence[int]], budget: int = 5_000_000
) -> dict[int, int]:
    if len(reels) != spec.grid.cols:
        raise ValueError(f"expected {spec.grid.cols} reels, got {len(reels)}")
    for reel in reels:
        unknown = set(reel) - set(spec.symbols)
        if unknown:
            raise ValueError(f"reel contains undeclared symbols: {sorted(unknown)}")

    plans = column_plans(spec)
    histograms = signature_histograms(spec, reels)

    sizes = [(col, len(h)) for col, h in enumerate(histograms)]
    total = prod(n for _, n in sizes)
    if total > budget:
        raise SignatureBudgetExceeded(sizes, total, budget)

    dist: dict[int, int] = {}
    keys = [list(h) for h in histograms]
    for combo in product(*keys):
        weight = prod(h[sig] for h, sig in zip(histograms, combo))
        units = _payout_units(spec, plans, combo)
        dist[units] = dist.get(units, 0) + weight
    return dist
