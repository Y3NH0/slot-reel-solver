"""Diversity bookkeeping for the exploration loop.

The point of the loop is not to approach the RTP target -- that is
deterministic computation inside the solver. The point is to collect several
configurations that all satisfy the targets but feel different to play.

The feature vector is computed entirely from Metrics, so admitting a
candidate costs nothing beyond what the solver already produced.

entropy is in the vector because win_rate and volatility alone would treat a
three-payout game and a five-payout game with coincidentally matching moments
as duplicates, when they are different games to the player.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from slotmath.metrics import Metrics
from slotmath.verify import ReelConfig

FEATURE_NAMES = ("win_rate", "volatility", "log_max_win", "payout_entropy", "spin_count")


class Portfolio(BaseModel):
    entries: list[ReelConfig]
    calibration: dict | None = None


def entropy_of(distribution: dict[int, int]) -> float:
    total = sum(distribution.values())
    if total == 0:
        return 0.0
    acc = 0.0
    for count in distribution.values():
        if count <= 0:
            continue
        p = count / total
        acc -= p * math.log(p)
    return acc


def features(metrics: Metrics) -> tuple[float, float, float, float, float]:
    distribution = {
        b.payout_units: b.combo_count for b in metrics.payout_distribution
    }
    return (
        metrics.win_rate,
        metrics.volatility,
        math.log(1 + metrics.max_win),
        entropy_of(distribution),
        float(metrics.spin_count),
    )


def normalise(vectors: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
    if not vectors:
        return []
    dims = len(vectors[0])
    lows = [min(v[d] for v in vectors) for d in range(dims)]
    highs = [max(v[d] for v in vectors) for d in range(dims)]
    spans = [h - l if h > l else 1.0 for l, h in zip(lows, highs)]
    return [
        tuple((v[d] - lows[d]) / spans[d] for d in range(dims)) for v in vectors
    ]


def min_distance(
    candidate: tuple[float, ...], existing: list[tuple[float, ...]]
) -> float:
    if not existing:
        return float("inf")
    return min(
        math.sqrt(sum((a - b) ** 2 for a, b in zip(candidate, other)))
        for other in existing
    )


def should_admit(
    portfolio: Portfolio, candidate: Metrics, distance_threshold: float
) -> bool:
    if not portfolio.entries:
        return True
    vectors = [features(e.metrics) for e in portfolio.entries] + [features(candidate)]
    normalised = normalise(vectors)
    return min_distance(normalised[-1], normalised[:-1]) >= distance_threshold


def calibrate(distances: list[float]) -> float:
    """Derive a threshold from what the feature space actually looks like.

    The median pairwise distance halved: loose enough to admit genuinely
    different configs, tight enough to reject near-duplicates.
    """
    if not distances:
        return 0.25
    ordered = sorted(distances)
    median = ordered[len(ordered) // 2]
    return max(0.05, median / 2)
