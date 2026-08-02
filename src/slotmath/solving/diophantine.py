"""Exact RTP as a homogeneous linear Diophantine equation.

Fix every reel but the last. For each signature s the last column could show,
let v_s be the total payout (in 1/D units) summed over every stop combination
of the fixed reels. Write

    w_s = rtp_den * v_s - rtp_num * D * prod(L_fixed)

Then RTP equals the target exactly iff

    sum_s n_s * w_s = 0

where n_s counts the positions in the last reel carrying signature s. The
last reel's length is sum_s n_s -- it is solved for, not guessed.

Existence has two independent routes, and neither is guaranteed:

1. Mixed signs. If some w_p > 0 and some w_q < 0, a nonzero non-negative
   solution exists: take n_p = |w_q|, n_q = w_p.
2. A zero weight. If some w_z == 0, put the entire last reel on signature z,
   at any length -- a uniform strip already solves the equation.

Neither route is guaranteed to be present. It is possible for every w_s to
share a sign with no zero among them, in which case that particular choice of
fixed reels admits no solution and a caller must move on (try different fixed
reels) rather than keep searching -- an unbounded search over a pair with no
solution will never terminate.

In practice both routes show up across the golden fixtures: fixtures A and B
have no positive weight at all (mixed_signs is False) and are solved via
route 2, because their last reel is uniform and that single signature's
weight happens to be zero; fixture C has both a positive and a negative
weight (mixed_signs is True) and is solved via route 1. search_last_reel
tries uniform strips first specifically because that is a cheap, direct probe
of route 2 -- which is why it finds A- and B-shaped solutions almost
immediately.

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

from slotmath.models.spec import GameSpec
from slotmath.evaluation.windows import column_plans, reel_windows, window_signature


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


def affordable_core_symbols(spec: GameSpec) -> list[int]:
    """Symbols cheap enough to dominate a reel without breaking the win rate.

    A spin either pays or it does not, so

        RTP = win_rate * (average payout per winning spin)

    which pins the average winning payout at exactly RTP / win_rate. Requiring
    win_rate >= min_win_rate therefore caps the average win at
    RTP / min_win_rate -- a hard consequence of the two targets, not a
    heuristic. A symbol that fills most of a reel supplies most of the wins,
    so its own payout has to sit under that cap or the win rate cannot reach
    the target no matter how the rest of the strip is arranged.

    Returns the symbols meeting the cap, cheapest last: among affordable
    symbols the dearer ones reach the RTP target with fewer winning spins, so
    they are the ones worth trying first. Falls back to every symbol when
    min_win_rate is 0 (no cap exists) or when nothing clears the cap (in which
    case the caller has a harder problem than core choice can fix).
    """
    symbols = sorted(spec.symbols)
    if spec.targets.min_win_rate <= 0:
        return symbols

    denominator = spec.payout_unit_denominator()
    cap = spec.targets.rtp / spec.targets.min_win_rate * denominator
    cheapest_win = {
        symbol: min(
            (
                spec.payout_units(symbol, pattern)
                for pattern in spec.patterns
                if spec.payout_units(symbol, pattern) > 0
            ),
            default=0,
        )
        for symbol in symbols
    }
    affordable = [s for s in symbols if cheapest_win[s] and cheapest_win[s] <= cap]
    if not affordable:
        return symbols
    return sorted(affordable, key=lambda s: cheapest_win[s], reverse=True)


def _run_composition(
    rng: random.Random,
    symbols: list[int],
    length: int,
    lower_bounds: dict[int, int] | None = None,
    core_pool: Sequence[int] | None = None,
) -> list[int]:
    """Build a strip out of runs, which is what makes 2x2 blocks possible.

    `lower_bounds` maps a symbol to the minimum number of positions it must
    occupy. Those positions are laid down first and the remainder is filled
    with the ordinary random runs, so a required symbol is guaranteed by
    construction rather than by rejecting finished candidates. Rejection
    sampling collapses here: the chance that five independently sampled runs
    happen to cover five symbols is small, and it falls off fast as the symbol
    count grows -- a coverage-constrained search that filters at the end
    spends nearly all of its budget discarding work.

    Raises ValueError if the bounds cannot fit in `length`; callers are
    expected to have pruned such lengths already (see
    coverage.minimum_reel_length).
    """
    required: list[int] = []
    if lower_bounds:
        for symbol, count in sorted(lower_bounds.items()):
            required.extend([symbol] * count)
    if len(required) > length:
        raise ValueError(
            f"lower bounds need {len(required)} positions but the strip is "
            f"only {length} long"
        )

    # Under lower bounds the filler draws from a narrow randomly-chosen core
    # rather than the whole alphabet. Spreading the filler evenly across every
    # symbol is what an unconstrained search wants, but it is the wrong shape
    # here: the required symbols already supply breadth, and a filler that
    # adds more of it leaves every symbol with a short, broken-up footprint.
    # That drives the last column into using all of its signatures at once,
    # which is precisely the case where the linear form has neither a zero
    # weight nor mixed signs and the pair admits no solution at all. A narrow
    # core keeps long runs of one symbol -- the shape that leaves the
    # Diophantine routes open -- and lets the required symbols sit in it as
    # isolated singletons.
    filler_pool = symbols
    if required:
        pool = list(core_pool) if core_pool else symbols
        core_size = rng.randint(1, min(2, len(pool)))
        # `core_pool` arrives best-first (see affordable_core_symbols), so
        # sampling it uniformly would spend most attempts on its weakest
        # entries. Weight by descending rank instead: still reachable, just
        # proportionally rarer.
        weights = [len(pool) - i for i in range(len(pool))]
        filler_pool = []
        while len(filler_pool) < core_size:
            pick = rng.choices(pool, weights=weights, k=1)[0]
            if pick not in filler_pool:
                filler_pool.append(pick)

    filler: list[int] = []
    while len(filler) < length - len(required):
        filler.extend([rng.choice(filler_pool)] * rng.choice([1, 2, 2, 3, 3, 4]))
    filler = filler[: length - len(required)]

    if not required:
        return filler

    # Scatter the required symbols instead of leaving them as one contiguous
    # prefix, which would bias every candidate into the same shape. Scattered
    # single occurrences are also the useful shape: an isolated symbol adds
    # presence without creating the runs that drive payout up.
    rng.shuffle(required)
    slots = set(rng.sample(range(length), len(required)))
    required_iter = iter(required)
    filler_iter = iter(filler)
    return [
        next(required_iter) if i in slots else next(filler_iter)
        for i in range(length)
    ]


def search_last_reel(
    spec: GameSpec,
    fixed_reels: Sequence[Sequence[int]],
    min_len: int,
    max_len: int,
    seed: int,
    max_candidates: int = 200_000,
    lower_bounds: dict[int, int] | None = None,
    core_pool: Sequence[int] | None = None,
) -> list[int] | None:
    """Search realizable strips, scored exactly by the linear form.

    `lower_bounds` forwards per-symbol minimum occupancy to the generator, so
    a coverage-constrained search never spends its budget on strips that are
    structurally disqualified.
    """
    weights = signature_weights(spec, fixed_reels)
    symbols = sorted(spec.symbols)
    rows = spec.grid.rows
    rng = random.Random(seed)

    lo = max(min_len, rows)
    if lower_bounds:
        lo = max(lo, sum(lower_bounds.values()))
    if lo > max_len:
        return None

    # Neither existence route is present: every weight shares a sign and none
    # is zero. Then sum_s n_s w_s = 0 with every n_s >= 0 and sum_s n_s = L > 0
    # is impossible -- the sum inherits that sign and cannot vanish. No strip
    # of any length solves this pair, so sampling one is pure waste. The
    # module docstring has always said a caller must move on here; this makes
    # the function do it rather than trusting each caller to remember.
    if not has_mixed_signs(weights) and all(w != 0 for w in weights.values()):
        return None

    # Uniform strips first: cheap, and they produced golden fixtures A and B
    # (both solved via route 2, a zero weight -- see the module docstring).
    # Fixture C's last reel is not uniform ([4,3,2,2,1,3,2,2,2,2]); it is
    # solved via route 1 (mixed signs) further down, in the random search.
    #
    # Skipped entirely under lower bounds: a uniform strip carries one symbol,
    # so any bound naming a second one rules it out before it is scored. Left
    # in place otherwise, because it is what finds A- and B-shaped solutions
    # almost immediately.
    if not lower_bounds:
        for length in range(lo, max_len + 1):
            for symbol in symbols:
                candidate = [symbol] * length
                if score(spec, weights, candidate) == 0:
                    return candidate

    for _ in range(max_candidates):
        length = rng.randint(lo, max_len)
        candidate = _run_composition(
            rng, symbols, length, lower_bounds, core_pool
        )
        if score(spec, weights, candidate) == 0:
            return candidate
    return None
