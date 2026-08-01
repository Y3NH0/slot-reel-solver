"""Cyclic reel windows and per-column pattern signatures.

A reel is a cyclic strip. A spin stops at position r and the column shows
`rows` consecutive symbols starting at r, wrapping at the end of the strip.

A *signature* is the projection of a window onto what the patterns can
observe in that column: for each pattern touching the column, either the
symbol that fills all of the pattern's cells in that column, or None.
Two windows with the same signature are interchangeable for every payout
calculation, which is what makes the aggregation in engine.py exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from slotmath.spec import GameSpec


def reel_windows(strip: Sequence[int], rows: int) -> list[tuple[int, ...]]:
    length = len(strip)
    if length < rows:
        raise ValueError(f"reel strip must hold at least {rows} symbols, got {length}")
    return [tuple(strip[(r + k) % length] for k in range(rows)) for r in range(length)]


@dataclass(frozen=True)
class ColumnPlan:
    """Which patterns observe this column, and through which rows."""

    col: int
    entries: tuple[tuple[int, tuple[int, ...]], ...]


def column_plans(spec: GameSpec) -> list[ColumnPlan]:
    plans: list[ColumnPlan] = []
    for col in range(spec.grid.cols):
        entries = []
        for idx, pattern in enumerate(spec.patterns):
            rows = tuple(sorted(r for c, r in pattern.cells if c == col))
            if rows:
                entries.append((idx, rows))
        plans.append(ColumnPlan(col=col, entries=tuple(entries)))
    return plans


def window_signature(
    window: tuple[int, ...], plan: ColumnPlan
) -> tuple[int | None, ...]:
    out: list[int | None] = []
    for _, rows in plan.entries:
        first = window[rows[0]]
        out.append(first if all(window[r] == first for r in rows) else None)
    return tuple(out)
