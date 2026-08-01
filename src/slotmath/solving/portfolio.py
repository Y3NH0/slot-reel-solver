"""Diversity bookkeeping for the exploration loop.

The point of the loop is not to approach the RTP target -- that is
deterministic computation inside the solver. The point is to collect several
configurations that all satisfy the targets but feel different to play.

The feature vector is computed entirely from Metrics, so admitting a
candidate costs nothing beyond what the solver already produced.

entropy is in the vector because win_rate and volatility alone would treat a
three-payout game and a five-payout game with coincidentally matching moments
as duplicates, when they are different games to the player.

Normalise against a fixed, calibrated scale -- never against the live
portfolio
------------------------------------------------------------------------
An earlier version of `should_admit` derived each dimension's low/high from
whatever vectors happened to be under comparison at the time: the existing
portfolio entries plus the candidate. That is wrong whenever the portfolio is
small -- which is every fresh run's first couple of rounds, exactly the case
that matters most. With one existing entry, any dimension that differs at
all between it and the candidate is, by construction, a two-point sample:
min-max normalisation stretches those two points to exactly 0 and 1 no
matter how close the raw values actually were. A near-duplicate then looks
maximally distant on that dimension and gets admitted -- the filter is
silently inoperative right when it is needed most, and a bit-identical
duplicate is the only case that still gets caught (both points land on the
same value, span collapses to the zero-span guard, distance is exactly 0).

The fix: normalise against ranges observed once, during a calibration pass,
and stored in `Portfolio.calibration["ranges"]` -- one `(low, high)` pair per
feature dimension, in `FEATURE_NAMES` order -- alongside the distance
threshold in `Portfolio.calibration["distance"]`. `normalise` still derives
lows/highs from the sample when called with `ranges=None`; that is exactly
what a calibration pass wants (run with no filtering, so the real spread of
the feature space can be observed and then frozen). But `should_admit` must
never do that itself: it either uses the stored ranges, or -- if there are
none yet -- admits unconditionally. Before calibration exists there is no
meaningful scale to normalise against, so pretending to filter would just
reintroduce the same bug in a different shape. Admitting everything until
calibration exists is a documented, deliberate no-op, not a silent failure.

Because the stored ranges are fixed and do not depend on what else happens
to be in the portfolio at the time of the call, each individual comparison
uses a fixed scale: normalising a candidate never depends on which other
candidates happen to be under consideration alongside it, or on the order
`explore` happened to offer them in.

That is NOT the same as saying the overall admission *decisions* are
order-independent -- they are not. `should_admit` is greedy: it compares a
candidate against whatever is already in the portfolio at that moment, and
each admitted candidate becomes part of the "existing" set for every
candidate considered after it. Two candidates that are mutually too close
together (distance < threshold) but each individually far enough from a
third can end up admitting different subsets depending on which one arrives
first -- whichever is admitted first blocks the other, and the survivor
differs by order. Concretely, with three candidates A, B, C, a threshold of
0.30, and pairwise distances chosen so A and B are near-duplicates of each
other but each far from C: offering them as A, B, C admits {A, C} (A is
admitted first and blocks B; C is far from both); offering them as B, A, C
admits only {B} (B is admitted first and blocks both A and C, if C also
happens to sit within the threshold of B). The *scale* is fixed and
order-independent; the *greedy admission sequence* is not.

The calibration pass itself
----------------------------
Storing ranges only helps if something actually derives and stores them.
`maybe_calibrate` is that something: while a portfolio has no calibration
yet, every candidate is admitted unconditionally (see `should_admit`) --
this *is* the calibration pass, collecting an unfiltered sample. Once the
portfolio reaches a caller-chosen size, `maybe_calibrate` calls
`build_calibration` to freeze `feature_ranges` over the collected vectors
plus a distance threshold from `calibrate` over their pairwise normalised
distances, and stores both on `portfolio.calibration`. From that point on
`should_admit` is genuinely engaged. `recalibrate` discards whatever
calibration exists and derives a fresh one immediately from however many
entries are currently in the portfolio, for when the first batch turned out
to be unrepresentative.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from slotmath.models.metrics import Metrics
from slotmath.verification.verify import ReelConfig

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


def feature_ranges(vectors: list[tuple[float, ...]]) -> list[tuple[float, float]]:
    """Per-dimension (low, high) observed across `vectors`.

    This is what a calibration pass freezes into
    `Portfolio.calibration["ranges"]`: run enough rounds with no diversity
    filter (there being no calibration yet, `should_admit` admits
    everything), collect the resulting feature vectors, then call this once
    to capture the real spread of the feature space.
    """
    if not vectors:
        return []
    dims = len(vectors[0])
    return [
        (min(v[d] for v in vectors), max(v[d] for v in vectors))
        for d in range(dims)
    ]


def normalise(
    vectors: list[tuple[float, ...]],
    ranges: list[tuple[float, float]] | None = None,
) -> list[tuple[float, ...]]:
    """Scale each dimension of every vector into [0, 1].

    With `ranges=None`, the per-dimension low/high is derived from `vectors`
    itself -- appropriate only for a calibration pass, where the sample IS
    the population whose spread you are trying to learn. For any admission
    decision made after calibration, pass the ranges captured once at
    calibration time explicitly: deriving fresh low/high from whatever is
    currently being compared is exactly the bug described in the module
    docstring.
    """
    if not vectors:
        return []
    dims = len(vectors[0])
    if ranges is None:
        lows = [min(v[d] for v in vectors) for d in range(dims)]
        highs = [max(v[d] for v in vectors) for d in range(dims)]
    else:
        lows = [lo for lo, _ in ranges]
        highs = [hi for _, hi in ranges]
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
    """Should `candidate` be added to `portfolio`?

    Normalises against the ranges frozen in
    `portfolio.calibration["ranges"]`, never against ranges derived from the
    portfolio's current entries -- see the module docstring for why that
    distinction is the entire point of this function. If no calibration has
    been recorded yet, there is no meaningful scale to normalise against, so
    every candidate is admitted: an honest no-op rather than a filter that
    only pretends to work.
    """
    ranges = (portfolio.calibration or {}).get("ranges")
    if not ranges:
        return True
    ranges = [tuple(r) for r in ranges]
    vectors = [features(e.metrics) for e in portfolio.entries] + [features(candidate)]
    normalised = normalise(vectors, ranges=ranges)
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


def build_calibration(entries: list[ReelConfig]) -> dict:
    """Derive a calibration dict from a batch of entries collected with no
    diversity filter (i.e. exactly what the pre-calibration phase of
    `maybe_calibrate` produces).

    `ranges` is `feature_ranges` over the entries' feature vectors, in
    `FEATURE_NAMES` order. `distance` is `calibrate` applied to every
    pairwise normalised distance between those same vectors (normalised
    against the ranges just derived) -- the spread the feature space
    actually has, not a guess.
    """
    vectors = [features(e.metrics) for e in entries]
    ranges = feature_ranges(vectors)
    normalised = normalise(vectors, ranges=ranges)
    pairwise = [
        math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))
        for i, v1 in enumerate(normalised)
        for v2 in normalised[i + 1 :]
    ]
    return {"distance": calibrate(pairwise), "ranges": ranges}


def maybe_calibrate(portfolio: Portfolio, calibration_size: int) -> bool:
    """If `portfolio` has no calibration yet and has collected at least
    `calibration_size` entries, derive one and store it on
    `portfolio.calibration` in place.

    Returns True exactly when a calibration was just computed, so a caller
    (the `explore` CLI) knows to report the newly derived threshold and
    ranges. A no-op -- and returns False -- once a calibration already
    exists, or while the portfolio is still below the requested size.
    """
    if portfolio.calibration is not None:
        return False
    if not portfolio.entries or len(portfolio.entries) < calibration_size:
        return False
    portfolio.calibration = build_calibration(portfolio.entries)
    return True


def recalibrate(portfolio: Portfolio) -> bool:
    """Discard whatever calibration `portfolio` has and derive a fresh one
    immediately from every entry currently in the portfolio, regardless of
    how many there are.

    For when the first batch of entries turned out to be an unrepresentative
    sample of the feature space and the stored ranges/threshold need
    correcting without waiting for `calibration_size` new entries to arrive.
    Returns True if a fresh calibration was computed; False if the portfolio
    is empty, in which case there is nothing to derive from and the
    calibration is simply cleared.
    """
    if not portfolio.entries:
        portfolio.calibration = None
        return False
    portfolio.calibration = build_calibration(portfolio.entries)
    return True
