"""Why a solve failed: proven impossible, or merely not found.

`solve()` returning None conflates two completely different facts. "No reel
configuration exists" is a theorem. "The search did not find one" is a
statement about the budget. Reporting them the same way is how a search
result gets written up as a mathematical impossibility -- so the statuses
here keep them apart, and nothing in this module may promote a budget
exhaustion into a proof.

  PROVEN_FEASIBLE      a configuration was found and verified
  PROVEN_INFEASIBLE    no configuration exists, by an argument that holds at
                       every length -- an arithmetic obstruction, or a
                       paytable entry the constraint needs and cannot have
  BOUNDED_EXHAUSTED    every configuration within the *configured length
                       bounds* was enumerated exactly; none works. Says
                       nothing about longer reels
  HEURISTIC_EXHAUSTED  the stochastic search ran out of budget. Says nothing
                       at all about existence
  UNKNOWN              no check applied

The distinction between PROVEN_INFEASIBLE and BOUNDED_EXHAUSTED matters and
is not pedantry: the second is routinely fixed by raising max_len.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from itertools import permutations, product
from math import prod
from typing import Sequence

from slotmath.evaluation.coverage import (
    minimum_reel_length,
    pattern_row_offsets,
)
from slotmath.evaluation.windows import column_plans, reel_windows, window_signature
from slotmath.models.spec import GameSpec


class SolveStatus(str, Enum):
    PROVEN_FEASIBLE = "proven_feasible"
    PROVEN_INFEASIBLE = "proven_infeasible"
    BOUNDED_EXHAUSTED = "bounded_exhausted"
    HEURISTIC_EXHAUSTED = "heuristic_exhausted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class FeasibilityFinding:
    """A pre-solve verdict. `status` is UNKNOWN when nothing was proved."""

    status: SolveStatus = SolveStatus.UNKNOWN
    diagnostics: tuple[Diagnostic, ...] = ()

    def proved(self) -> bool:
        return self.status in (
            SolveStatus.PROVEN_INFEASIBLE,
            SolveStatus.BOUNDED_EXHAUSTED,
        )


# ---------------------------------------------------------------------------
# cheap obstructions, checked before any search
# ---------------------------------------------------------------------------


def _rtp_reachable_at(spec: GameSpec, spin_count: int) -> bool:
    """Whether the RTP target needs a whole number of payout units here."""
    total = spec.targets.rtp * spec.payout_unit_denominator() * spin_count
    return total.denominator == 1


def check_rtp_divisibility(
    spec: GameSpec, min_len: int, max_len: int, cols: int
) -> Diagnostic | None:
    """RTP must land on an integer number of payout units for some reachable
    spin count. If no length tuple in range gives one, no arrangement can:
    the total payout is an integer by construction.
    """
    for lengths in product(range(min_len, max_len + 1), repeat=cols):
        if _rtp_reachable_at(spec, prod(lengths)):
            return None
    return Diagnostic(
        "rtp_divisibility_failure",
        f"target RTP {spec.targets.rtp} needs a non-integral number of "
        f"1/{spec.payout_unit_denominator()} payout units at every spin count "
        f"reachable with reel lengths {min_len}..{max_len}",
    )


def check_minimum_length(spec: GameSpec, max_len: int) -> Diagnostic | None:
    """A coverage constraint can demand more positions than max_len allows."""
    for col in range(spec.grid.cols):
        needed = minimum_reel_length(spec, col)
        if needed > max_len:
            return Diagnostic(
                "minimum_reel_length_exceeds_bound",
                f"column {col} needs at least {needed} positions to satisfy "
                f"spec.coverage, but max_len is {max_len}",
            )
    return None


def check_paytable_supports_coverage(spec: GameSpec) -> Diagnostic | None:
    """A winning-or-better coverage tier needs a positive payout for every
    (symbol, pattern). A zero entry makes that unreachable at any length.
    """
    tier = spec.coverage.symbol_pattern
    if tier in ("none", "raw"):
        return None
    dead = [
        (symbol, pattern.name)
        for symbol in sorted(spec.symbols)
        for pattern in spec.patterns
        if spec.payout_units(symbol, pattern) <= 0
    ]
    if not dead:
        return None
    listed = ", ".join(f"symbol {s} under {p}" for s, p in dead[:6])
    return Diagnostic(
        "non_positive_paytable_entry",
        f"coverage tier {tier!r} requires a positive payout for every "
        f"(symbol, pattern), but these pay nothing: {listed}"
        + (f" (+{len(dead) - 6} more)" if len(dead) > 6 else ""),
    )


def check_cyclic_mask_possible(spec: GameSpec, max_len: int) -> Diagnostic | None:
    """A pattern's per-column mask must fit inside a single window.

    Row offsets are read within one `rows`-tall window, so a mask is always
    satisfiable by a long enough strip unless the grid itself forbids it.
    Catches a pattern whose column footprint exceeds the number of rows.
    """
    for pattern in spec.patterns:
        for col in range(spec.grid.cols):
            rows = pattern_row_offsets(pattern, col)
            if rows and max(rows) >= spec.grid.rows:
                return Diagnostic(
                    "impossible_cyclic_mask",
                    f"pattern {pattern.name!r} needs row {max(rows)} of column "
                    f"{col}, but the grid is only {spec.grid.rows} rows tall",
                )
    return None


def precheck(
    spec: GameSpec, min_len: int, max_len: int
) -> FeasibilityFinding:
    """Obstructions provable without searching. UNKNOWN means "nothing ruled
    out", never "feasible"."""
    diagnostics: list[Diagnostic] = []
    for found in (
        check_cyclic_mask_possible(spec, max_len),
        check_paytable_supports_coverage(spec),
        check_minimum_length(spec, max_len),
        check_rtp_divisibility(spec, min_len, max_len, spec.grid.cols),
    ):
        if found is not None:
            diagnostics.append(found)

    if not diagnostics:
        return FeasibilityFinding()

    # A length bound is a configuration choice, not a fact about the game, so
    # it can only ever justify BOUNDED_EXHAUSTED. The others hold at every
    # length and are genuine impossibility proofs.
    bounded_only = {"minimum_reel_length_exceeds_bound", "rtp_divisibility_failure"}
    status = (
        SolveStatus.BOUNDED_EXHAUSTED
        if all(d.code in bounded_only for d in diagnostics)
        else SolveStatus.PROVEN_INFEASIBLE
    )
    return FeasibilityFinding(status=status, diagnostics=tuple(diagnostics))


# ---------------------------------------------------------------------------
# bounded exhaustive enumeration for run-shaped coverage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundedCoverageResult:
    status: SolveStatus
    detail: str
    lengths_considered: tuple[int, ...] = ()
    strips_enumerated: int = 0
    histogram_combinations: int = 0
    witness: tuple[tuple[int, ...], ...] | None = None
    best_win_rate_at_exact_rtp: Fraction | None = None

    def diagnostic(self) -> Diagnostic:
        return Diagnostic(
            "bounded_exhaustive_search"
            if self.status is SolveStatus.BOUNDED_EXHAUSTED
            else self.status.value,
            self.detail,
        )


def required_run_length(spec: GameSpec, col: int) -> int | None:
    """The cyclic run of one symbol that column `col` needs, or None.

    Returns None when some pattern's footprint in this column is not a
    contiguous block of rows: then the requirement is a gapped mask rather
    than a run, the block decomposition below does not describe the strip
    space, and this module must decline to enumerate rather than enumerate
    the wrong set.
    """
    span = 0
    for pattern in spec.patterns:
        rows = pattern_row_offsets(pattern, col)
        if not rows:
            continue
        if rows != tuple(range(rows[0], rows[-1] + 1)):
            return None
        span = max(span, len(rows))
    return span


def _canonical_rotation(strip: tuple[int, ...]) -> tuple[int, ...]:
    return min(strip[i:] + strip[:i] for i in range(len(strip)))


def _has_run(strip: tuple[int, ...], symbol: int, k: int) -> bool:
    length = len(strip)
    return any(
        all(strip[(t + i) % length] == symbol for i in range(k))
        for t in range(length)
    )


def enumerate_run_covering_strips(
    symbols: Sequence[int], run: int, length: int, cap: int
) -> list[tuple[int, ...]] | None:
    """Every cyclic strip of `length` giving each symbol a run of >= `run`.

    Complete by a counting argument, not by sampling. The required runs are
    disjoint (they carry different symbols), so they occupy at least
    len(symbols) * run positions and the strip has
    slack = length - len(symbols) * run spare ones. Every valid strip is
    therefore one block per symbol plus `slack` extra single positions, in
    some cyclic order -- an extra position landing beside its own block just
    lengthens that block, which is why blocks longer than `run` need no
    separate case. Enumerating every arrangement of those units and filtering
    on the run requirement enumerates exactly the valid strips.

    Returns None if the enumeration would exceed `cap`, so a caller never
    mistakes a truncated walk for a complete one.
    """
    slack = length - len(symbols) * run
    if slack < 0:
        return []

    units: list[tuple[int, ...]] = [(s,) * run for s in symbols]
    found: set[tuple[int, ...]] = set()
    for extras in product(symbols, repeat=slack):
        all_units = units + [(e,) for e in extras]
        for order in permutations(range(len(all_units))):
            strip = tuple(x for i in order for x in all_units[i])
            if len(found) > cap:
                return None
            if all(_has_run(strip, s, run) for s in symbols):
                found.add(_canonical_rotation(strip))
    return sorted(found)


def prove_bounded_coverage_infeasible(
    spec: GameSpec,
    min_len: int,
    max_len: int,
    strip_cap: int = 20_000,
    combination_cap: int = 5_000_000,
) -> BoundedCoverageResult:
    """Exhaustively decide raw symbol x pattern coverage within length bounds.

    Enumerates every coverage-satisfying cyclic strip per column and length,
    collapses each to its exact signature histogram (payout depends on nothing
    else), and checks every combination for exact RTP and the minimum win
    rate. All integer arithmetic -- no float, no sampling, no tolerance.

    A negative result is BOUNDED_EXHAUSTED, never PROVEN_INFEASIBLE: it is a
    complete statement about lengths min_len..max_len and says nothing about
    longer reels.
    """
    symbols = sorted(spec.symbols)
    plans = column_plans(spec)
    rows = spec.grid.rows

    runs = [required_run_length(spec, c) for c in range(spec.grid.cols)]
    if any(r is None for r in runs):
        return BoundedCoverageResult(
            SolveStatus.UNKNOWN,
            "a pattern's column footprint is not a contiguous row block, so "
            "the run decomposition does not describe the strip space; "
            "declining to enumerate rather than enumerate the wrong set",
        )

    floor = max(len(symbols) * r for r in runs)  # type: ignore[arg-type]
    lengths = [n for n in range(max(min_len, floor), max_len + 1)]
    if not lengths:
        return BoundedCoverageResult(
            SolveStatus.BOUNDED_EXHAUSTED,
            f"raw coverage needs at least {floor} positions per reel, which "
            f"exceeds max_len={max_len}; no configuration exists within these "
            "bounds",
            lengths_considered=(),
        )

    # signature domain and the exact payout of every signature combination
    sig_domains = [
        sorted({window_signature(w, plan) for w in product(symbols, repeat=rows)},
               key=repr)
        for plan in plans
    ]
    sig_index = [{s: i for i, s in enumerate(dom)} for dom in sig_domains]

    payout: dict[tuple[int, ...], int] = {}
    for combo_idx in product(*(range(len(d)) for d in sig_domains)):
        sigs = tuple(sig_domains[c][combo_idx[c]] for c in range(len(plans)))
        claims: dict[int, list[int | None]] = {
            i: [] for i in range(len(spec.patterns))
        }
        for plan, sig in zip(plans, sigs):
            for (pattern_index, _r), symbol in zip(plan.entries, sig):
                claims[pattern_index].append(symbol)
        wins = [
            spec.payout_units(reported[0], spec.patterns[i])
            for i, reported in claims.items()
            if reported
            and reported[0] is not None
            and all(s == reported[0] for s in reported)
        ]
        payout[combo_idx] = (
            0 if not wins else (max(wins) if spec.combine == "max" else sum(wins))
        )

    # realizable signature histograms per (column, length)
    strips_total = 0
    histograms: dict[tuple[int, int], list[tuple[int, ...]]] = {}
    witnesses: dict[tuple[int, int], list[tuple[int, ...]]] = {}
    for col in range(spec.grid.cols):
        run = runs[col]
        for length in lengths:
            strips = enumerate_run_covering_strips(
                symbols, run, length, strip_cap  # type: ignore[arg-type]
            )
            if strips is None:
                return BoundedCoverageResult(
                    SolveStatus.UNKNOWN,
                    f"enumeration for column {col} at length {length} would "
                    f"exceed the strip cap of {strip_cap}; no claim is made",
                )
            strips_total += len(strips)
            unique: dict[tuple[int, ...], tuple[int, ...]] = {}
            for strip in strips:
                counts = [0] * len(sig_domains[col])
                for window in reel_windows(strip, rows):
                    counts[sig_index[col][window_signature(window, plans[col])]] += 1
                unique.setdefault(tuple(counts), strip)
            histograms[col, length] = list(unique.keys())
            witnesses[col, length] = list(unique.values())

    denominator = spec.payout_unit_denominator()
    rtp = spec.targets.rtp
    min_win = spec.targets.min_win_rate

    combinations = 0
    best_win: Fraction | None = None
    for lengths_tuple in product(lengths, repeat=spec.grid.cols):
        spin_count = prod(lengths_tuple)
        # exact: total_units / (D * N) == rtp  <=>  total_units * rtp.den == rtp.num * D * N
        target_units = Fraction(rtp * denominator * spin_count)
        if target_units.denominator != 1:
            continue
        target = int(target_units)

        per_col = [histograms[c, lengths_tuple[c]] for c in range(spec.grid.cols)]
        combinations += prod(len(h) for h in per_col)
        if combinations > combination_cap:
            return BoundedCoverageResult(
                SolveStatus.UNKNOWN,
                f"histogram combinations exceeded the cap of {combination_cap}; "
                "no claim is made",
            )
        for choice in product(*(range(len(h)) for h in per_col)):
            hists = [per_col[c][choice[c]] for c in range(spec.grid.cols)]
            total = 0
            wins = 0
            for combo_idx in product(*(range(len(d)) for d in sig_domains)):
                weight = prod(hists[c][combo_idx[c]] for c in range(spec.grid.cols))
                if not weight:
                    continue
                units = payout[combo_idx]
                total += weight * units
                if units:
                    wins += weight
            if total != target:
                continue
            win_rate = Fraction(wins, spin_count)
            best_win = win_rate if best_win is None else max(best_win, win_rate)
            if win_rate >= min_win:
                return BoundedCoverageResult(
                    SolveStatus.PROVEN_FEASIBLE,
                    f"exact solution exists at lengths {lengths_tuple} with "
                    f"win rate {win_rate}",
                    lengths_considered=tuple(lengths),
                    strips_enumerated=strips_total,
                    histogram_combinations=combinations,
                    witness=tuple(
                        witnesses[c, lengths_tuple[c]][choice[c]]
                        for c in range(spec.grid.cols)
                    ),
                    best_win_rate_at_exact_rtp=win_rate,
                )

    reached = (
        f"; the best win rate among exact-RTP configurations was {best_win}"
        if best_win is not None
        else "; no configuration reached the exact RTP target at all"
    )
    return BoundedCoverageResult(
        SolveStatus.BOUNDED_EXHAUSTED,
        f"proven infeasible under reel length bounds {min_len}..{max_len}: "
        f"enumerated {strips_total} coverage-satisfying strips and "
        f"{combinations} exact histogram combinations, none meeting both "
        f"RTP {rtp} and win rate {min_win}{reached}. This is a complete "
        "statement about these bounds only, not about longer reels",
        lengths_considered=tuple(lengths),
        strips_enumerated=strips_total,
        histogram_combinations=combinations,
        best_win_rate_at_exact_rtp=best_win,
    )
