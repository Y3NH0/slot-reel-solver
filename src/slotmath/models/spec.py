"""GameSpec: the single trust boundary. All external input is validated here."""

from __future__ import annotations

import json
from fractions import Fraction
from functools import cached_property
from math import lcm
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    model_validator,
)


def _coerce_fraction(value: Any) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a valid rational")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        # repr() round-trips to the shortest decimal, so 0.55 -> Fraction(11, 20)
        # exactly. Fraction(0.55) would give the binary expansion instead.
        return Fraction(repr(value))
    if isinstance(value, str):
        return Fraction(value)
    raise TypeError(f"cannot coerce {type(value).__name__} to Fraction")


Rational = Annotated[
    Fraction,
    BeforeValidator(_coerce_fraction),
    PlainSerializer(float, return_type=float),
]


class Grid(BaseModel):
    cols: int = Field(ge=1)
    rows: int = Field(ge=1)


class Pattern(BaseModel):
    name: str
    cells: list[tuple[int, int]] | Literal["all"]
    pattern_multiplier: Rational = Fraction(1)


class Targets(BaseModel):
    rtp: Rational
    min_win_rate: Rational = Fraction(0)

    @model_validator(mode="after")
    def _check(self):
        if self.rtp <= 0:
            raise ValueError("targets.rtp must be > 0")
        if not (0 <= self.min_win_rate <= 1):
            raise ValueError("targets.min_win_rate must be within [0, 1]")
        return self


class GameSpec(BaseModel):
    name: str
    grid: Grid
    symbols: dict[int, Rational]
    patterns: list[Pattern] = Field(min_length=1)
    combine: Literal["max", "sum"] = "max"
    targets: Targets

    @model_validator(mode="after")
    def _resolve_and_check(self):
        if not self.symbols:
            raise ValueError("symbols must not be empty")
        every = [(c, r) for c in range(self.grid.cols) for r in range(self.grid.rows)]
        for p in self.patterns:
            if p.cells == "all":
                p.cells = list(every)
            if not p.cells:
                raise ValueError(f"pattern {p.name!r} has no cells")
            if len(set(p.cells)) != len(p.cells):
                raise ValueError(f"pattern {p.name!r} has duplicate cells")
            for col, row in p.cells:
                if not (0 <= col < self.grid.cols and 0 <= row < self.grid.rows):
                    raise ValueError(
                        f"pattern {p.name!r} cell ({col}, {row}) is out of bounds "
                        f"for grid {self.grid.cols}x{self.grid.rows}"
                    )
        return self

    @cached_property
    def _payout_unit_denominator(self) -> int:
        return lcm(
            *(
                (sym * p.pattern_multiplier).denominator
                for sym in self.symbols.values()
                for p in self.patterns
            )
        )

    def payout_unit_denominator(self) -> int:
        """Smallest D such that every reachable payout is an integer number of 1/D.

        Computed once and memoized via functools.cached_property: GameSpec is
        immutable after validation (patterns/symbols never change post-init),
        so recomputing the lcm on every call would be pure waste. Safe to call
        from hot loops (e.g. once per pattern per stop combination).
        """
        return self._payout_unit_denominator

    def payout_units(self, symbol: int, pattern: Pattern) -> int:
        """Return the exact integer payout of `symbol` under `pattern`, in
        units of 1 / payout_unit_denominator().

        Contract: `pattern` must be drawn from `self.patterns` (or otherwise
        have a `pattern_multiplier` whose denominator was already folded into
        `payout_unit_denominator()`'s lcm). An ad-hoc `Pattern` not part of
        that computation can produce a non-integer result and trip the
        assertion below.
        """
        payout = self.symbols[symbol] * pattern.pattern_multiplier
        units = payout * self.payout_unit_denominator()
        assert units.denominator == 1, "payout_unit_denominator is wrong"
        return int(units)


def load_spec(path: str | Path) -> GameSpec:
    return GameSpec.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
