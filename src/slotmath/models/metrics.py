"""Derive reportable metrics from an integer payout distribution.

The integer counts are the source of truth. Every float in Metrics is a
convenience view for human readers; nothing in the system may make a
decision from them. Use exact_rtp() / exact_win_rate() for decisions.
"""

from __future__ import annotations

from fractions import Fraction
from math import sqrt
from typing import Sequence

from pydantic import BaseModel

from slotmath.models.spec import GameSpec

# Shared cap on prod(len(reel) for reel in reels) -- the cost driver for a
# full cyclic enumeration (naive.evaluate, and anything that recomputes from
# it, e.g. `slotmath report`). Living here rather than in
# slotmath.verification.verify or slotmath.cli.app lets every caller reach it
# without importing the evaluator modules just for a size check. Not derived
# from engine.evaluate's signature-space budget (a different, usually much
# smaller, cost axis) -- matched to it by convention only.
NAIVE_BUDGET = 5_000_000


class BoardTooLargeError(ValueError):
    """Raised by check_board_budget() when a full enumeration would be
    unsafe to run. A ValueError subclass so callers that already catch
    ValueError from reel-shape problems (e.g. undeclared symbols) catch this
    too without an extra except clause, if they choose to."""

    def __init__(self, board_size: int, budget: int):
        self.board_size = board_size
        self.budget = budget
        super().__init__(
            f"full enumeration would need {board_size} board combinations, "
            f"over the safety budget of {budget}; refusing to run naive "
            "enumeration. This is not a verdict on the artifact -- rerun "
            "deliberately with a raised budget if you need to evaluate a "
            "config this large."
        )


def check_board_budget(
    reels: Sequence[Sequence[int]], budget: int = NAIVE_BUDGET
) -> int:
    """Returns prod(len(reel) for reel in reels); raises BoardTooLargeError
    if that exceeds `budget`. Call this before any full enumeration
    (naive.evaluate) on reels that came from untrusted input -- a hook
    invocation or a CLI command run against an arbitrary file -- so an
    oversized artifact fails fast instead of grinding for minutes."""
    board_size = 1
    for reel in reels:
        board_size *= len(reel)
    if board_size > budget:
        raise BoardTooLargeError(board_size, budget)
    return board_size


class PayoutBucket(BaseModel):
    payout_units: int
    payout: float
    combo_count: int


class Metrics(BaseModel):
    spin_count: int
    win_count: int
    win_rate: float
    total_payout_units: int
    payout_unit_denominator: int
    rtp: float
    volatility: float
    max_win: float
    payout_distribution: list[PayoutBucket]


def build_metrics(spec: GameSpec, distribution: dict[int, int]) -> Metrics:
    if not distribution:
        raise ValueError("payout distribution is empty")

    denominator = spec.payout_unit_denominator()
    spin_count = sum(distribution.values())
    if spin_count == 0:
        raise ValueError("payout distribution has zero total spins")
    win_count = spin_count - distribution.get(0, 0)
    total_units = sum(units * count for units, count in distribution.items())

    rtp = Fraction(total_units, denominator * spin_count)
    variance = sum(
        count * (Fraction(units, denominator) - rtp) ** 2
        for units, count in distribution.items()
    ) / spin_count

    return Metrics(
        spin_count=spin_count,
        win_count=win_count,
        win_rate=win_count / spin_count,
        total_payout_units=total_units,
        payout_unit_denominator=denominator,
        rtp=float(rtp),
        volatility=sqrt(float(variance)),
        max_win=max(distribution) / denominator,
        payout_distribution=[
            PayoutBucket(
                payout_units=units,
                payout=units / denominator,
                combo_count=distribution[units],
            )
            for units in sorted(distribution)
        ],
    )


def exact_rtp(metrics: Metrics) -> Fraction:
    return Fraction(
        metrics.total_payout_units,
        metrics.payout_unit_denominator * metrics.spin_count,
    )


def exact_win_rate(metrics: Metrics) -> Fraction:
    return Fraction(metrics.win_count, metrics.spin_count)
