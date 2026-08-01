"""Four-stage solver.

Stage 0  Pick length tuples actively, not just prune. Because the congruence
         requirement moves with N, choosing N divisible by the residue modulus
         makes n1 = 0 legal and removes the obstruction entirely, so those
         tuples come first.
Stage 1  Seed the fixed reels from run compositions -- only runs of identical
         symbols can form a 2x2 block at all.
Stage 3  Solve the last reel exactly via the linear form in diophantine.py.
Stage 2  (fallback) local search, used only when stage 3 finds nothing.

Stage numbering follows the spec; execution order is 0, 1, 3, then 2.
"""

from __future__ import annotations

import random
from functools import reduce
from itertools import product
from math import gcd, prod
from typing import Iterable, Iterator

from pydantic import BaseModel

from slotmath import engine
from slotmath.diophantine import _run_composition, search_last_reel
from slotmath.metrics import build_metrics, exact_rtp, exact_win_rate
from slotmath.spec import GameSpec
from slotmath.verify import ReelConfig

VERSION = "0.1.0"


class SolverOptions(BaseModel):
    seed: int = 20260731
    min_len: int = 3
    max_len: int = 16
    prefer_length_mod: int | None = None    # None -> derive from the spec
    max_candidates: int = 40_000
    signature_budget: int = 5_000_000
    max_seeds: int = 400
    # The path the GameSpec was actually loaded from, so the returned
    # ReelConfig.spec and solver.command can reference it truthfully instead
    # of guessing configs/<spec.name>.json. None only when a caller
    # constructs a GameSpec in memory with no backing file (e.g. tests);
    # the CLI always sets this to the real input path (see _cmd_solve /
    # _cmd_explore in cli.py).
    spec_path: str | None = None


def required_units(spec: GameSpec, spin_count: int) -> int:
    """Total payout, in 1/D units, that hits the RTP target exactly."""
    rtp = spec.targets.rtp
    denominator = spec.payout_unit_denominator()
    total = rtp * denominator * spin_count
    if total.denominator != 1:
        raise ValueError(
            f"target RTP {rtp} is unreachable at spin_count {spin_count}: it "
            f"would need {total} payout units, which is not an integer"
        )
    return int(total)


def congruence_ok(spec: GameSpec, spin_count: int, support: Iterable[int]) -> bool:
    """Necessary condition for hitting the RTP target exactly, in O(1).

    A configuration whose payouts all come from `support` can only produce
    totals divisible by gcd(support). If the required total is not, no
    arrangement of those payouts can reach it -- however long you search.

    The modulus depends on the CANDIDATE's support, not on the spec: the spec
    permits symbol 1's 11 units, which is coprime to everything else, so a
    spec-level gcd would be 1 and the test would be vacuous. The obstruction
    only appears once a candidate declines to use that payout.

    Returns True when gcd(support) is 1 -- no obstruction, not a guarantee.
    """
    nonzero = [u for u in support if u != 0]
    if not nonzero:
        return required_units(spec, spin_count) == 0
    modulus = reduce(gcd, nonzero)
    if modulus <= 1:
        return True
    return required_units(spec, spin_count) % modulus == 0


def derive_preferred_modulus(spec: GameSpec) -> int:
    """Which spin counts make the search easy.

    If a whole symbol can be left out, the remaining payout units may share a
    factor g > 1, and then the required total forces N into a residue class.
    For the homework paytable, dropping symbol 1 leaves every payout a
    multiple of 5, which forces 5 | N -- and with 5 | N the symbol is not
    needed at all. Returns 1 when nothing is gained.
    """
    rtp = spec.targets.rtp
    denominator = spec.payout_unit_denominator()
    best = 1
    for dropped in spec.symbols:
        rest = [
            spec.payout_units(sym, p)
            for sym in spec.symbols
            if sym != dropped
            for p in spec.patterns
        ]
        g = reduce(gcd, rest) if rest else 0
        if g <= 1:
            continue
        for m in range(1, g * rtp.denominator + 1):
            if (rtp.numerator * denominator * m) % (rtp.denominator * g) == 0:
                best = max(best, m)
                break
    return best


def candidate_length_tuples(
    spec: GameSpec, options: SolverOptions
) -> Iterator[tuple[int, ...]]:
    lo = max(options.min_len, spec.grid.rows)
    hi = options.max_len
    if lo > hi:
        return
    modulus = (
        options.prefer_length_mod
        if options.prefer_length_mod is not None
        else derive_preferred_modulus(spec)
    )
    every = list(product(range(lo, hi + 1), repeat=spec.grid.cols))
    preferred = [t for t in every if modulus > 1 and prod(t) % modulus == 0]
    seen = set(preferred)
    yield from preferred
    yield from (t for t in every if t not in seen)


def solve(spec: GameSpec, options: SolverOptions) -> ReelConfig | None:
    rng = random.Random(options.seed)
    symbols = sorted(spec.symbols)
    attempts = 0

    for lengths in candidate_length_tuples(spec, options):
        for _ in range(4):
            if attempts >= options.max_seeds:
                return None
            attempts += 1

            fixed = [
                _run_composition(rng, symbols, n) for n in lengths[:-1]
            ]
            last = search_last_reel(
                spec,
                fixed,
                min_len=max(options.min_len, spec.grid.rows),
                max_len=options.max_len,
                seed=rng.randrange(2**31),
                max_candidates=options.max_candidates,
            )
            if last is None:
                continue

            reels = [*fixed, last]
            distribution = engine.evaluate(
                spec, reels, budget=options.signature_budget
            )
            metrics = build_metrics(spec, distribution)
            # No congruence_ok pre-filter here: by this point engine.evaluate
            # and build_metrics have already paid for the full distribution,
            # so the payout support is known and the very next exact_rtp
            # check already subsumes what congruence_ok would tell us -- a
            # congruence failure implies exact_rtp() != target anyway.
            # congruence_ok's value is O(1) pruning *before* that work, which
            # requires knowing the support in advance; it is not available
            # here, so it stays a standalone diagnostic (see its own tests)
            # rather than a check in this loop.
            if exact_rtp(metrics) != spec.targets.rtp:
                continue
            if exact_win_rate(metrics) < spec.targets.min_win_rate:
                continue

            spec_path = options.spec_path or f"configs/{spec.name}.json"
            return ReelConfig(
                spec=spec_path,
                reels=[list(r) for r in reels],
                metrics=metrics,
                solver={
                    "version": VERSION,
                    "seed": options.seed,
                    "command": f"slotmath solve {spec_path} --seed {options.seed}",
                },
            )
    return None
