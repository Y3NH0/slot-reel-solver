"""Exact Symbol x Pattern coverage: shared vocabulary and cross-checking.

Coverage asks a different question than the payout evaluators do. `naive.py`,
`engine.py` and `montecarlo.py` answer "how much does a spin pay?" and return
a single scalar per spin. Coverage asks "which (symbol, pattern) pairs can
ever actually happen, and how often?" -- which needs *attribution*: knowing
that a spin paid 20 units is not the same as knowing which pattern earned it.

The existing evaluators deliberately do not attribute, and this module does
not change them. Payout results are untouched; attribution lives here.

Four nested notions, each strictly narrower than the last:

  raw            the pattern's cells all show the symbol. Geometry only --
                 payout is not consulted, so a zero-payout symbol still
                 counts as raw-covered.
  winning        a raw match whose payout_units is strictly positive.
  max_eligible   under combine="max", the pattern is one of the argmax
                 winning matches on that spin. Ties are inclusive: if two
                 patterns tie for the top payout, BOTH are max-eligible.
                 Under combine="sum" every winning match is max-eligible,
                 because under sum every match really does contribute.
  unique_credit  the pattern is the *sole* argmax winning match, so it alone
                 accounts for the spin's payout.

raw >= winning >= max_eligible >= unique_credit, pointwise, always.

Two independent analyzers compute these counts:

  coverage_naive.py    expands the board and compares cells directly
  coverage_engine.py   aggregates over per-column signature histograms

They share this module's *types* and this module's cyclic-geometry helper,
but not one line of match-or-attribution logic -- that is reimplemented in
each, exactly as naive.py/engine.py/montecarlo.py duplicate the combine rule.
Cross-checking two copies of the same function proves nothing; the whole
value of `cross_check_coverage` depends on the two paths being written
separately. Do not factor their inner loops together.

`raw_match_count_factorized` below is a *third*, cheaper witness for the raw
dimension only, resting on a small theorem: reel stops are independent, so a
raw match count factorizes into a product of per-column cyclic-mask counts.
It is used to assert against the two full analyzers.

Monte Carlo has no role here. Coverage support is an exact structural
property -- a simulation that never happens to land on a rare combination
cannot distinguish "impossible" from "unlikely", so it must never be used to
decide coverage. It stays a sanity check on payout only.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import prod
from typing import Iterable, Literal, Sequence

from slotmath.models.spec import GameSpec, Pattern

CoverageKind = Literal["raw", "winning", "max_eligible", "unique_credit"]

COVERAGE_KINDS: tuple[CoverageKind, ...] = (
    "raw",
    "winning",
    "max_eligible",
    "unique_credit",
)

ReasonKind = Literal[
    "missing_cyclic_mask",
    "non_positive_payout",
    "always_dominated",
    "tie_only",
]


def pattern_row_offsets(pattern: Pattern, col: int) -> tuple[int, ...]:
    """The rows `pattern` occupies in `col`, ascending. Empty if untouched.

    This is the general R[p,c] of the coverage condition. Nothing here assumes
    the rows are contiguous, or that a column contributes at most one cell --
    a pattern touching rows (0, 2) of a column is handled the same as one
    touching (0, 1).
    """
    return tuple(sorted(row for c, row in pattern.cells if c == col))


def local_cyclic_match_count(
    reel: Sequence[int], row_offsets: Sequence[int], symbol: int
) -> int:
    """Number of cyclic stops t with reel[(t + row) % L] == symbol for all rows.

    The reel is a cyclic strip, so every one of its L stops is a legal spin
    outcome and wrap-around windows count exactly like interior ones. With
    `row_offsets` empty this returns L (a vacuous requirement is met by every
    stop), which is what makes the factorization theorem below come out right
    for columns the pattern never touches.
    """
    length = len(reel)
    if length == 0:
        raise ValueError("reel strip must not be empty")
    return sum(
        all(reel[(stop + row) % length] == symbol for row in row_offsets)
        for stop in range(length)
    )


def raw_match_count_factorized(
    spec: GameSpec,
    reels: Sequence[Sequence[int]],
    pattern_index: int,
    symbol: int,
) -> int:
    """Exact raw-match count as a product of per-column cyclic-mask counts.

    Reel stops are independent, and a raw match is a conjunction of
    independent per-column conditions, so the joint count is the product of
    the per-column counts. Untouched columns impose nothing and contribute
    their full length via `local_cyclic_match_count`'s empty-offsets case.

    O(sum L_c) instead of O(prod L_c), which is what makes it usable as an
    assertion inside the analyzers rather than only in tests.
    """
    pattern = spec.patterns[pattern_index]
    return prod(
        local_cyclic_match_count(reel, pattern_row_offsets(pattern, col), symbol)
        for col, reel in enumerate(reels)
    )


def raw_coverage_possible(
    spec: GameSpec, reels: Sequence[Sequence[int]], pattern_index: int, symbol: int
) -> bool:
    """Whether (symbol, pattern) can raw-match at all.

    The necessary-and-sufficient condition, stated directly: for every column
    the pattern touches there must exist at least one stop showing `symbol` at
    all of that column's required rows. Equivalent to a positive factorized
    count, but short-circuits on the first empty column.
    """
    pattern = spec.patterns[pattern_index]
    for col, reel in enumerate(reels):
        rows = pattern_row_offsets(pattern, col)
        if not rows:
            continue
        if local_cyclic_match_count(reel, rows, symbol) == 0:
            return False
    return True


def minimum_reel_length(spec: GameSpec, col: int) -> int:
    """A provable lower bound on reel `col`'s length under spec.coverage.

    Two independent floors, whichever binds harder:

    * `each_reel_all_symbols` needs one position per declared symbol.
    * A symbol_pattern requirement needs, for the widest pattern touching this
      column, that many cells of the *same* symbol visible at one stop. Window
      offsets are distinct strip positions (a window is `rows` consecutive
      cells and reel_windows already refuses L < rows), so those cells are
      distinct positions, and distinct symbols cannot share them. That gives
      |symbols| * max_p |R[p,c]|.

    Necessary, not sufficient: clearing this bound does not mean a strip of
    that length exists. Used for pruning and diagnostics, never as a verdict.
    """
    floor = 0
    if spec.coverage.each_reel_all_symbols:
        floor = len(spec.symbols)
    if spec.coverage.symbol_pattern != "none":
        widest = max(
            (len(pattern_row_offsets(p, col)) for p in spec.patterns),
            default=0,
        )
        floor = max(floor, len(spec.symbols) * widest)
    return floor


def missing_symbols_per_reel(
    spec: GameSpec, reels: Sequence[Sequence[int]]
) -> list[list[int]]:
    """Per reel, the declared symbols it never shows. Index-aligned to reels."""
    declared = set(spec.symbols)
    return [sorted(declared - set(reel)) for reel in reels]


@dataclass(frozen=True)
class MissingReason:
    """Why a (symbol, pattern) pair fails to reach some coverage tier."""

    kind: ReasonKind
    column: int | None = None
    row_offsets: tuple[int, ...] | None = None
    symbol: int | None = None

    def describe(self) -> str:
        if self.kind == "missing_cyclic_mask":
            return (
                f"no cyclic stop in column {self.column} shows symbol "
                f"{self.symbol} at rows {list(self.row_offsets or ())}"
            )
        if self.kind == "non_positive_payout":
            return "the paytable gives this symbol/pattern a payout of 0"
        if self.kind == "always_dominated":
            return "every matching spin is outpaid by another matching pattern"
        return "matches only ever tie for top payout, never win outright"

    def to_dict(self) -> dict:
        out: dict = {"kind": self.kind}
        if self.column is not None:
            out["column"] = self.column
        if self.row_offsets is not None:
            out["row_offsets"] = list(self.row_offsets)
        if self.symbol is not None:
            out["symbol"] = self.symbol
        out["detail"] = self.describe()
        return out


@dataclass(frozen=True)
class CoverageCounts:
    """The four raw integer counts an analyzer produces for one pair."""

    raw: int = 0
    winning: int = 0
    max_eligible: int = 0
    unique_credit: int = 0

    def get(self, kind: CoverageKind) -> int:
        return getattr(self, kind)


@dataclass(frozen=True)
class CoverageEntry:
    symbol: int
    pattern_index: int
    pattern: str
    payout_units: int
    counts: CoverageCounts
    spin_count: int
    reasons: tuple[MissingReason, ...] = ()

    def count(self, kind: CoverageKind) -> int:
        return self.counts.get(kind)

    def probability(self, kind: CoverageKind) -> Fraction:
        """Exact count/spin_count. A Fraction, never a float -- these feed
        comparisons, and the whole project's rule is that decisions run on
        exact rationals."""
        return Fraction(self.count(kind), self.spin_count)

    def covers(self, kind: CoverageKind) -> bool:
        return self.count(kind) > 0

    def to_dict(self) -> dict:
        out: dict = {
            "symbol": self.symbol,
            "pattern_index": self.pattern_index,
            "pattern": self.pattern,
            "payout_units": self.payout_units,
        }
        for kind in COVERAGE_KINDS:
            out[f"{kind}_count"] = self.count(kind)
            out[f"{kind}_probability"] = str(self.probability(kind))
        out["reasons"] = [r.to_dict() for r in self.reasons]
        return out


@dataclass(frozen=True)
class CoverageReport:
    spin_count: int
    combine: str
    entries: tuple[CoverageEntry, ...]

    def entry(self, symbol: int, pattern_index: int) -> CoverageEntry:
        for e in self.entries:
            if e.symbol == symbol and e.pattern_index == pattern_index:
                return e
        raise KeyError(f"no coverage entry for symbol {symbol}, pattern {pattern_index}")

    def uncovered(self, kind: CoverageKind) -> tuple[CoverageEntry, ...]:
        return tuple(e for e in self.entries if not e.covers(kind))

    def fully_covers(self, kind: CoverageKind) -> bool:
        return all(e.covers(kind) for e in self.entries)

    def counts_signature(self) -> dict[tuple[int, int], CoverageCounts]:
        """The bare counts, for equality-comparing two analyzers."""
        return {(e.symbol, e.pattern_index): e.counts for e in self.entries}

    def to_dict(self) -> dict:
        return {
            "spin_count": self.spin_count,
            "combine": self.combine,
            "credit_semantics": {
                "raw": "pattern geometry shows the symbol; payout ignored",
                "winning": "raw match with strictly positive payout units",
                "max_eligible": (
                    "all tied argmax winning patterns receive attribution"
                    if self.combine == "max"
                    else "under combine=sum every winning match contributes"
                ),
                "unique_credit": "only a sole argmax winning pattern receives attribution",
                "note": (
                    "Attribution is computed here only. The payout evaluators "
                    "return a scalar per spin and are unchanged by this report."
                ),
            },
            "entries": [e.to_dict() for e in self.entries],
        }


def _reasons_for(
    spec: GameSpec,
    reels: Sequence[Sequence[int]],
    symbol: int,
    pattern_index: int,
    payout_units: int,
    counts: CoverageCounts,
) -> tuple[MissingReason, ...]:
    """Explain the first tier this pair fails to reach.

    Reported as a chain that stops at the first real obstruction, because the
    later ones are consequences: a pair that can never raw-match is trivially
    also never max-eligible, and saying so three times helps nobody.
    """
    if counts.raw == 0:
        pattern = spec.patterns[pattern_index]
        found = []
        for col, reel in enumerate(reels):
            rows = pattern_row_offsets(pattern, col)
            if rows and local_cyclic_match_count(reel, rows, symbol) == 0:
                found.append(
                    MissingReason(
                        kind="missing_cyclic_mask",
                        column=col,
                        row_offsets=rows,
                        symbol=symbol,
                    )
                )
        return tuple(found)
    if payout_units <= 0:
        return (MissingReason(kind="non_positive_payout", symbol=symbol),)
    if counts.max_eligible == 0:
        return (MissingReason(kind="always_dominated", symbol=symbol),)
    if counts.unique_credit == 0:
        return (MissingReason(kind="tie_only", symbol=symbol),)
    return ()


def build_report(
    spec: GameSpec,
    reels: Sequence[Sequence[int]],
    counts: dict[tuple[int, int], CoverageCounts],
    spin_count: int,
) -> CoverageReport:
    """Assemble analyzer counts into a report, asserting the raw dimension
    against the independent factorization theorem as it goes.

    Assembly and explanation are shared by both analyzers on purpose -- they
    are presentation, not attribution. The counts themselves arrive already
    computed by two separately written code paths.
    """
    entries = []
    for symbol in sorted(spec.symbols):
        for pattern_index, pattern in enumerate(spec.patterns):
            got = counts.get((symbol, pattern_index), CoverageCounts())
            factorized = raw_match_count_factorized(spec, reels, pattern_index, symbol)
            if factorized != got.raw:
                raise AssertionError(
                    f"raw coverage disagreement for symbol {symbol}, pattern "
                    f"{pattern.name!r}: analyzer counted {got.raw}, the "
                    f"per-column factorization says {factorized}. One of them "
                    "is wrong -- this is a program bug, not a bad artifact."
                )
            if not (got.raw >= got.winning >= got.max_eligible >= got.unique_credit):
                raise AssertionError(
                    f"coverage tiers are not nested for symbol {symbol}, "
                    f"pattern {pattern.name!r}: {got}"
                )
            payout_units = spec.payout_units(symbol, pattern)
            entries.append(
                CoverageEntry(
                    symbol=symbol,
                    pattern_index=pattern_index,
                    pattern=pattern.name,
                    payout_units=payout_units,
                    counts=got,
                    spin_count=spin_count,
                    reasons=_reasons_for(
                        spec, reels, symbol, pattern_index, payout_units, got
                    ),
                )
            )
    return CoverageReport(
        spin_count=spin_count, combine=spec.combine, entries=tuple(entries)
    )


def cross_check_coverage(
    spec: GameSpec, reels: Sequence[Sequence[int]]
) -> CoverageReport:
    """Run both analyzers and require exact agreement on every count.

    This is the coverage analogue of verify.py's engine_matches_naive gate:
    a disagreement here is a program bug, not a bad artifact, and is raised
    rather than reported so it can never be mistaken for a coverage verdict.
    """
    from slotmath.evaluation import coverage_engine, coverage_naive

    naive_report = coverage_naive.analyze(spec, reels)
    engine_report = coverage_engine.analyze(spec, reels)
    if naive_report.counts_signature() != engine_report.counts_signature():
        diff = []
        naive_counts = naive_report.counts_signature()
        engine_counts = engine_report.counts_signature()
        for key in sorted(set(naive_counts) | set(engine_counts)):
            a = naive_counts.get(key)
            b = engine_counts.get(key)
            if a != b:
                diff.append(f"symbol {key[0]} pattern {key[1]}: naive={a} engine={b}")
        raise AssertionError(
            "COVERAGE ANALYZERS DISAGREE -- this is a program bug, not a bad "
            "artifact. " + "; ".join(diff)
        )
    return naive_report
