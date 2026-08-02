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
from dataclasses import dataclass
from typing import Iterable, Iterator

from pydantic import BaseModel

from slotmath.evaluation import engine
from slotmath.evaluation.coverage import (
    cross_check_coverage,
    minimum_reel_length,
    missing_symbols_per_reel,
)
from slotmath.solving.diophantine import (
    _run_composition,
    affordable_core_symbols,
    search_last_reel,
)
from slotmath.models.metrics import build_metrics, exact_rtp, exact_win_rate
from slotmath.models.spec import GameSpec
from slotmath.solving.feasibility import (
    Diagnostic,
    SolveStatus,
    precheck,
    prove_bounded_coverage_infeasible,
)
from slotmath.verification.verify import ReelConfig

VERSION = "0.1.0"


class SolverOptions(BaseModel):
    seed: int = 20260731
    min_len: int = 3
    max_len: int = 16
    prefer_length_mod: int | None = None    # None -> derive from the spec
    max_candidates: int = 40_000
    signature_budget: int = 5_000_000
    max_seeds: int = 400
    # Attempts get multiplied by this when spec.coverage is active. Two
    # measured effects pull the same way. Each attempt became far cheaper
    # (search_last_reel rejects a fixed-reel pair with no existence route
    # before sampling any strip, and most coverage-shaped pairs have none:
    # ~400 attempts on the homework spec went from ~200s to ~9s). And each
    # attempt is likelier to fail, because the constraint rules out the
    # uniform strips that solve the unconstrained cases immediately. More
    # attempts, each cheaper. Multiplied rather than floored so an explicit
    # small max_seeds still means a small search.
    coverage_attempt_multiplier: int = 100
    # The path the GameSpec was actually loaded from, so the returned
    # ReelConfig.spec and solver.command can reference it truthfully instead
    # of guessing configs/<spec.name>.json. None only when a caller
    # constructs a GameSpec in memory with no backing file (e.g. tests);
    # the CLI always sets this to the real input path (see _cmd_solve /
    # _cmd_explore in slotmath/cli/app.py).
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


def coverage_lower_bounds(spec: GameSpec) -> dict[int, int] | None:
    """Per-symbol minimum occupancy implied by spec.coverage, or None.

    Only `each_reel_all_symbols` produces a bound the generator can honour
    directly (one position per symbol). A symbol_pattern requirement needs
    specific *relative* positions, not a raw count, so it is enforced by the
    exact post-check rather than smuggled in as a bigger number here.
    """
    if not spec.coverage.each_reel_all_symbols:
        return None
    return {symbol: 1 for symbol in sorted(spec.symbols)}


def candidate_length_tuples(
    spec: GameSpec, options: SolverOptions, rng: random.Random | None = None
) -> Iterator[tuple[int, ...]]:
    lo = max(options.min_len, spec.grid.rows)
    hi = options.max_len
    # A reel too short to hold the constraint cannot be rescued by search, so
    # those lengths never enter the stochastic loop at all.
    lo = max(lo, max(minimum_reel_length(spec, c) for c in range(spec.grid.cols)))
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
    rest = [t for t in every if t not in seen]

    # Under a coverage constraint the order is sampled rather than walked in
    # lexicographic order. The candidate space grows as (hi - lo + 1) ** cols
    # while the attempt budget does not, so a lexicographic walk only ever
    # reaches a prefix of it -- fine when short reels are as good as long
    # ones, but they are not here. Every symbol must fit on every reel, so the
    # shortest lengths are almost entirely consumed by the required symbols,
    # leaving no room for the runs that patterns spanning several cells of a
    # column need. Those tuples are legal, reachable first, and nearly always
    # hopeless, so a lexicographic budget is spent before it arrives anywhere
    # useful. Shuffling is still deterministic given the solver's seed.
    #
    # Only under a constraint: with none, the lexicographic order is what the
    # existing seeds reproduce, and changing it would silently invalidate
    # every recorded solve command.
    if rng is not None and spec.coverage.is_active():
        rng.shuffle(preferred)
        rng.shuffle(rest)

    yield from preferred
    yield from rest


@dataclass(frozen=True)
class SolveOutcome:
    """What the solver did, not merely what it returned.

    `config is None` alone cannot distinguish "no such configuration exists"
    from "the budget ran out", which is the single easiest way to turn a
    search result into a false impossibility claim. `status` keeps them apart.
    """

    status: SolveStatus
    config: ReelConfig | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    attempts: int = 0

    def render(self) -> str:
        lines = [f"status: {self.status.value}", f"attempts: {self.attempts}"]
        lines.extend(f"  - {d}" for d in self.diagnostics)
        return "\n".join(lines)


def solve_with_status(spec: GameSpec, options: SolverOptions) -> SolveOutcome:
    """solve(), plus why it ended the way it did."""
    low = max(options.min_len, spec.grid.rows)
    finding = precheck(spec, low, options.max_len)
    if finding.proved():
        return SolveOutcome(status=finding.status, diagnostics=finding.diagnostics)

    # A symbol_pattern requirement often pins reels near their minimum length,
    # which leaves few enough realizable strips to settle the question exactly
    # instead of sampling it. Only decides when the enumeration completes
    # within its caps; otherwise it returns UNKNOWN and the search runs as
    # normal. Never consulted without such a constraint -- the unconstrained
    # strip space is far too large to enumerate.
    if spec.coverage.symbol_pattern != "none":
        bounded = prove_bounded_coverage_infeasible(spec, low, options.max_len)
        if bounded.status is SolveStatus.BOUNDED_EXHAUSTED:
            return SolveOutcome(
                status=SolveStatus.BOUNDED_EXHAUSTED,
                diagnostics=(bounded.diagnostic(),),
            )

    config, attempts = _search(spec, options)
    if config is not None:
        return SolveOutcome(
            status=SolveStatus.PROVEN_FEASIBLE, config=config, attempts=attempts
        )

    diagnostics = [
        Diagnostic(
            "heuristic_budget_exhausted",
            f"the stochastic search made {attempts} attempts without finding a "
            f"configuration. This is a statement about the budget, not about "
            f"existence -- raise --max-seeds, or widen --max-len",
        )
    ]
    return SolveOutcome(
        status=SolveStatus.HEURISTIC_EXHAUSTED,
        diagnostics=tuple(diagnostics),
        attempts=attempts,
    )


def solve(spec: GameSpec, options: SolverOptions) -> ReelConfig | None:
    """The configuration, or None. Use solve_with_status() to learn why."""
    return solve_with_status(spec, options).config


def _search(
    spec: GameSpec, options: SolverOptions
) -> tuple[ReelConfig | None, int]:
    rng = random.Random(options.seed)
    symbols = sorted(spec.symbols)
    lower_bounds = coverage_lower_bounds(spec)
    core_pool = affordable_core_symbols(spec) if lower_bounds else None
    attempt_budget = options.max_seeds * (
        options.coverage_attempt_multiplier if spec.coverage.is_active() else 1
    )
    attempts = 0

    for lengths in candidate_length_tuples(spec, options, rng):
        for _ in range(4):
            if attempts >= attempt_budget:
                return None, attempts
            attempts += 1

            fixed = [
                _run_composition(rng, symbols, n, lower_bounds, core_pool)
                for n in lengths[:-1]
            ]
            last = search_last_reel(
                spec,
                fixed,
                min_len=max(options.min_len, spec.grid.rows),
                max_len=options.max_len,
                seed=rng.randrange(2**31),
                max_candidates=options.max_candidates,
                lower_bounds=lower_bounds,
                core_pool=core_pool,
            )
            if last is None:
                continue

            reels = [*fixed, last]
            # _run_composition and search_last_reel each sample independently
            # from the full symbol set, so a symbol can end up unused by pure
            # chance -- especially with short reels or many symbols. Nothing
            # in the RTP/win-rate math requires every symbol to appear, so
            # this must be its own filter: a declared symbol that never
            # appears anywhere is dead weight in the paytable, not a
            # reasonable output. Checked before the (comparatively expensive)
            # engine.evaluate call so a doomed candidate is skipped cheaply.
            if {s for reel in reels for s in reel} != set(spec.symbols):
                continue
            # Generation guarantees the per-reel bounds, so this is an
            # assertion of that guarantee rather than the mechanism enforcing
            # it -- and it is the only thing standing behind the constraint if
            # a future generator regresses. Cheap: no evaluation involved.
            if spec.coverage.each_reel_all_symbols and any(
                missing_symbols_per_reel(spec, reels)
            ):
                continue
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
            # Exact post-check for the symbol_pattern tier. Left until last
            # because it is the most expensive test here, and a candidate that
            # misses RTP is already dead.
            if spec.coverage.symbol_pattern != "none":
                if not cross_check_coverage(spec, reels).fully_covers(
                    spec.coverage.symbol_pattern
                ):
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
            ), attempts
    return None, attempts
