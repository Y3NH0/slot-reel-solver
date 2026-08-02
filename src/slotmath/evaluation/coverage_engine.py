"""Coverage attribution by signature-histogram aggregation. The fast path.

Two windows with the same column signature are interchangeable for
attribution, not merely for payout: a signature already records, per pattern
touching the column, exactly which symbol that column reports to it (or None
when the column's cells disagree). Whether a pattern matches, and with which
symbol, is a function of nothing else. So the same collapse that makes
`engine.py` exact makes this exact too, and the enumeration runs over
prod(|Sig_c|) signature combinations with integer weights instead of
prod(L_c) boards.

The match-and-attribution loop below is written independently of
`coverage_naive.py`'s -- that one reads board cells, this one reads
signatures. See the note in `coverage.py`; do not factor them together.
"""

from __future__ import annotations

from itertools import product
from math import prod
from typing import Sequence

from slotmath.evaluation.coverage import (
    CoverageCounts,
    CoverageReport,
    build_report,
)
from slotmath.evaluation.engine import SignatureBudgetExceeded, signature_histograms
from slotmath.evaluation.windows import column_plans
from slotmath.models.spec import GameSpec


def analyze(
    spec: GameSpec, reels: Sequence[Sequence[int]], budget: int = 5_000_000
) -> CoverageReport:
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

    spin_count = prod(len(reel) for reel in reels)

    raw: dict[tuple[int, int], int] = {}
    winning: dict[tuple[int, int], int] = {}
    max_eligible: dict[tuple[int, int], int] = {}
    unique_credit: dict[tuple[int, int], int] = {}

    keys = [list(h) for h in histograms]
    for combo in product(*keys):
        weight = prod(h[sig] for h, sig in zip(histograms, combo))

        # Each column reports, per pattern touching it, the symbol filling that
        # pattern's cells in this column -- or None if they disagree.
        reported: dict[int, list[int | None]] = {
            i: [] for i in range(len(spec.patterns))
        }
        for plan, sig in zip(plans, combo):
            for (pattern_index, _rows), symbol in zip(plan.entries, sig):
                reported[pattern_index].append(symbol)

        earners: list[tuple[int, int, int]] = []
        for pattern_index, claims in reported.items():
            if not claims or claims[0] is None:
                continue
            if any(s != claims[0] for s in claims):
                continue
            symbol = claims[0]
            key = (symbol, pattern_index)
            raw[key] = raw.get(key, 0) + weight
            units = spec.payout_units(symbol, spec.patterns[pattern_index])
            if units > 0:
                winning[key] = winning.get(key, 0) + weight
                earners.append((pattern_index, symbol, units))

        if not earners:
            continue

        if spec.combine == "max":
            top_units = max(units for _, _, units in earners)
            top = [item for item in earners if item[2] == top_units]
        else:
            top = earners

        for pattern_index, symbol, _ in top:
            key = (symbol, pattern_index)
            max_eligible[key] = max_eligible.get(key, 0) + weight
        if len(top) == 1:
            pattern_index, symbol, _ = top[0]
            key = (symbol, pattern_index)
            unique_credit[key] = unique_credit.get(key, 0) + weight

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
