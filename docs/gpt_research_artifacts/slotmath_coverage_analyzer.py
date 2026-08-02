#!/usr/bin/env python3
"""Exact Symbol × Pattern coverage analyzer for slot-reel-solver.

Run from the repository root:
    PYTHONPATH=src python slotmath_coverage_analyzer.py \
        configs/homework-3x3.json solutions/homework-3x3.json

The analyzer never uses Monte Carlo for coverage correctness.  It reports:

* raw_count: pattern geometry matches symbol, regardless of payout.
* winning_count: raw match with strictly positive payout units.
* max_eligible_count: under combine="max", the pattern is one of the tied
  argmax matches.  This is an analyzer attribution rule; the existing payout
  engines still emit only one scalar payout.
* unique_credit_count: the pattern is the unique argmax match.

All probabilities are exact Fraction strings.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from fractions import Fraction
from itertools import product
from pathlib import Path
from typing import Sequence

from slotmath.evaluation.windows import reel_windows
from slotmath.models.spec import GameSpec, load_spec


def local_cyclic_match_count(
    reel: Sequence[int], rows: Sequence[int], symbol: int
) -> int:
    """Count stops whose requested row offsets all show ``symbol``."""
    length = len(reel)
    return sum(
        all(reel[(stop + row) % length] == symbol for row in rows)
        for stop in range(length)
    )


def raw_match_count_factorized(
    spec: GameSpec,
    reels: Sequence[Sequence[int]],
    pattern_index: int,
    symbol: int,
) -> int:
    """Exact raw-match count using independence of reel stops.

    For touched column c, let m_c be the local cyclic-mask count.  Untouched
    columns contribute all L_c stops.  The global count is their product.
    """
    pattern = spec.patterns[pattern_index]
    total = 1
    for col, reel in enumerate(reels):
        rows = sorted(row for c, row in pattern.cells if c == col)
        total *= (
            local_cyclic_match_count(reel, rows, symbol)
            if rows
            else len(reel)
        )
    return total


def analyze_exact(
    spec: GameSpec, reels: Sequence[Sequence[int]]
) -> dict[str, object]:
    if len(reels) != spec.grid.cols:
        raise ValueError(f"expected {spec.grid.cols} reels, got {len(reels)}")

    spin_count = 1
    for reel in reels:
        spin_count *= len(reel)

    raw = defaultdict(int)
    winning = defaultdict(int)
    max_eligible = defaultdict(int)
    unique_credit = defaultdict(int)

    per_column = [reel_windows(reel, spec.grid.rows) for reel in reels]
    for columns in product(*per_column):
        matched: list[tuple[int, int, int]] = []
        for pattern_index, pattern in enumerate(spec.patterns):
            first_col, first_row = pattern.cells[0]
            symbol = columns[first_col][first_row]
            if all(columns[col][row] == symbol for col, row in pattern.cells):
                units = spec.payout_units(symbol, pattern)
                raw[(symbol, pattern_index)] += 1
                if units > 0:
                    winning[(symbol, pattern_index)] += 1
                    matched.append((pattern_index, symbol, units))

        if not matched:
            continue

        if spec.combine == "max":
            final_units = max(units for _, _, units in matched)
            top = [item for item in matched if item[2] == final_units]
        else:
            # Under sum, every positive matched pattern contributes.
            top = matched

        for pattern_index, symbol, _ in top:
            max_eligible[(symbol, pattern_index)] += 1
        if len(top) == 1:
            pattern_index, symbol, _ = top[0]
            unique_credit[(symbol, pattern_index)] += 1

    entries = []
    for symbol in sorted(spec.symbols):
        for pattern_index, pattern in enumerate(spec.patterns):
            key = (symbol, pattern_index)
            factorized = raw_match_count_factorized(
                spec, reels, pattern_index, symbol
            )
            assert factorized == raw[key], (
                key,
                factorized,
                raw[key],
            )
            payout_units = spec.payout_units(symbol, pattern)
            reasons = []
            if raw[key] == 0:
                for col, reel in enumerate(reels):
                    rows = sorted(
                        row for c, row in pattern.cells if c == col
                    )
                    if rows and local_cyclic_match_count(reel, rows, symbol) == 0:
                        reasons.append(
                            {
                                "kind": "missing_cyclic_mask",
                                "column": col,
                                "rows": rows,
                                "symbol": symbol,
                            }
                        )
            elif payout_units <= 0:
                reasons.append({"kind": "non_positive_payout"})
            elif max_eligible[key] == 0:
                reasons.append({"kind": "always_dominated"})
            elif unique_credit[key] == 0:
                reasons.append({"kind": "tie_only"})

            entries.append(
                {
                    "symbol": symbol,
                    "pattern_index": pattern_index,
                    "pattern": pattern.name,
                    "payout_units": payout_units,
                    "raw_count": raw[key],
                    "raw_probability": str(Fraction(raw[key], spin_count)),
                    "winning_count": winning[key],
                    "winning_probability": str(
                        Fraction(winning[key], spin_count)
                    ),
                    "max_eligible_count": max_eligible[key],
                    "max_eligible_probability": str(
                        Fraction(max_eligible[key], spin_count)
                    ),
                    "unique_credit_count": unique_credit[key],
                    "unique_credit_probability": str(
                        Fraction(unique_credit[key], spin_count)
                    ),
                    "reasons": reasons,
                }
            )

    return {
        "spin_count": spin_count,
        "combine": spec.combine,
        "credit_semantics": {
            "max_eligible": "all tied argmax patterns receive attribution",
            "unique_credit": "only a sole argmax receives attribution",
            "note": (
                "The repository's payout evaluators return only a scalar payout "
                "and do not currently attribute max ties to pattern identities."
            ),
        },
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("solution")
    parser.add_argument("--output")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    data = json.loads(Path(args.solution).read_text(encoding="utf-8"))
    report = analyze_exact(spec, data["reels"])
    rendered = json.dumps(report, indent=2)

    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
