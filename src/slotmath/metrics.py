"""Derive reportable metrics from an integer payout distribution.

The integer counts are the source of truth. Every float in Metrics is a
convenience view for human readers; nothing in the system may make a
decision from them. Use exact_rtp() / exact_win_rate() for decisions.
"""

from __future__ import annotations

from fractions import Fraction
from math import sqrt

from pydantic import BaseModel

from slotmath.spec import GameSpec


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
