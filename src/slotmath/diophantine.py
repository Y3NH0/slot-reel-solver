"""Exact RTP as a homogeneous linear Diophantine equation.

Fix every reel but the last. For each signature s the last column could show,
let v_s be the total payout (in 1/D units) summed over every stop combination
of the fixed reels. Write

    w_s = rtp_den * v_s - rtp_num * D * prod(L_fixed)

Then RTP equals the target exactly iff

    sum_s n_s * w_s = 0

where n_s counts the positions in the last reel carrying signature s. The
last reel's length is sum_s n_s -- it is solved for, not guessed.

Existence: whenever {w_s} contains both a positive and a negative value a
nonzero non-negative solution exists (take n_p = |w_q|, n_q = w_p). Both signs
always occur, because there is always an almost-always-winning signature and
an almost-never-winning one.

LIMITATION -- do not paper over this: a signature histogram is NOT freely
realizable. A run of k identical symbols forces k-2 triple signatures plus two
boundary signatures, so turning a solution of the equation back into a real
cyclic strip still needs a finite search. This is not a closed form.

What we exploit is that w_s makes scoring a candidate strip O(|Sig|) instead
of a full re-enumeration, so the search over *realizable* strips is cheap.
"""

from __future__ import annotations

import random
from itertools import product
from math import prod
from typing import Sequence

from slotmath.spec import GameSpec
from slotmath.windows import column_plans, reel_windows, window_signature


def _last_column_payout_units(
    spec: GameSpec,
    plans,
    fixed_signatures: tuple[tuple[int | None, ...], ...],
    last_signature: tuple[int | None, ...],
) -> int:
    signatures = (*fixed_signatures, last_signature)
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


def _candidate_signatures(spec: GameSpec, plan) -> list[tuple[int | None, ...]]:
    symbols = sorted(spec.symbols)
    seen = set()
    for window in product(symbols, repeat=spec.grid.rows):
        seen.add(window_signature(window, plan))
    return sorted(seen, key=repr)


def signature_weights(
    spec: GameSpec, fixed_reels: Sequence[Sequence[int]]
) -> dict[tuple[int | None, ...], int]:
    if len(fixed_reels) != spec.grid.cols - 1:
        raise ValueError(
            f"expected {spec.grid.cols - 1} fixed reels, got {len(fixed_reels)}"
        )
    plans = column_plans(spec)
    denominator = spec.payout_unit_denominator()
    rtp = spec.targets.rtp

    fixed_hists = []
    for plan, reel in zip(plans, fixed_reels):
        hist: dict[tuple[int | None, ...], int] = {}
        for window in reel_windows(reel, spec.grid.rows):
            sig = window_signature(window, plan)
            hist[sig] = hist.get(sig, 0) + 1
        fixed_hists.append(hist)

    fixed_product = prod(len(reel) for reel in fixed_reels)
    baseline = rtp.numerator * denominator * fixed_product

    weights: dict[tuple[int | None, ...], int] = {}
    for last_sig in _candidate_signatures(spec, plans[-1]):
        total = 0
        for combo in product(*(list(h) for h in fixed_hists)):
            weight = prod(h[s] for h, s in zip(fixed_hists, combo))
            total += weight * _last_column_payout_units(spec, plans, combo, last_sig)
        weights[last_sig] = rtp.denominator * total - baseline
    return weights


def score(
    spec: GameSpec,
    weights: dict[tuple[int | None, ...], int],
    last_reel: Sequence[int],
) -> int:
    """Sum of n_s * w_s. Zero means RTP is exactly on target."""
    plan = column_plans(spec)[-1]
    total = 0
    for window in reel_windows(last_reel, spec.grid.rows):
        total += weights[window_signature(window, plan)]
    return total


def has_mixed_signs(weights: dict[tuple[int | None, ...], int]) -> bool:
    values = list(weights.values())
    return any(v > 0 for v in values) and any(v < 0 for v in values)


def _run_composition(rng: random.Random, symbols: list[int], length: int) -> list[int]:
    """Build a strip out of runs, which is what makes 2x2 blocks possible."""
    strip: list[int] = []
    while len(strip) < length:
        strip.extend([rng.choice(symbols)] * rng.choice([1, 2, 2, 3, 3, 4]))
    return strip[:length]


def search_last_reel(
    spec: GameSpec,
    fixed_reels: Sequence[Sequence[int]],
    min_len: int,
    max_len: int,
    seed: int,
    max_candidates: int = 200_000,
) -> list[int] | None:
    """Search realizable strips, scored exactly by the linear form."""
    weights = signature_weights(spec, fixed_reels)
    symbols = sorted(spec.symbols)
    rows = spec.grid.rows
    rng = random.Random(seed)

    lo = max(min_len, rows)
    if lo > max_len:
        return None

    # Uniform strips first: cheap, and they produced golden fixtures B and C.
    for length in range(lo, max_len + 1):
        for symbol in symbols:
            candidate = [symbol] * length
            if score(spec, weights, candidate) == 0:
                return candidate

    for _ in range(max_candidates):
        length = rng.randint(lo, max_len)
        candidate = _run_composition(rng, symbols, length)
        if score(spec, weights, candidate) == 0:
            return candidate
    return None
