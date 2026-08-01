# Slot Reel RTP Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一組可配置的 slot 數學工具，能對「給定盤面、中獎樣式、賠付表與目標指標，求出符合目標的捲軸配置」產出精確（非統計逼近）且可獨立驗證的解。

**Architecture:** 三層。核心是 `src/slotmath/` 的純計算模組——`naive.py`（全窮舉，信任錨點）、`engine.py`（signature 聚合，快）、`montecarlo.py`（獨立第三路徑）刻意寫三份互相驗證。中層是 `verify.py` 的三層 gate 與 `solver.py` 的四階段求解（含齊次線性丟番圖建構）。外層是四支 `.claude/skills/` 與一個 PostToolUse hook，把工具接上 agent。

**Tech Stack:** Python 3.11+、Pydantic v2、pytest。設定檔 JSON。無其他執行期依賴。

## Global Constraints

- 設計依據：`docs/superpowers/specs/2026-07-31-slot-reel-rtp-design.md`。本計畫中「spec §N」皆指該文件。
- **邊界收 float，內部一律 `Fraction`。** float → Fraction 一律經 `Fraction(repr(x))`，絕不用 `Fraction(x)`（後者會產生 `Fraction(2476979795053773, 4503599627370496)` 這種垃圾）。
- **所有內部賠付分佈以整數 `payout_units` 為鍵**，單位為 `1 / payout_unit_denominator`。禁止以 float 或 Fraction 當分佈鍵。
- **RTP 命中判定一律用 `Fraction` 真等號**，禁止 `abs(a-b) < eps`。
- 命名固定：`win_rate`、`min_win_rate`、`pattern_multiplier`、`spin_count`、`win_count`、`combo_count`、`total_payout_units`、`payout_unit_denominator`。禁用 `hit_rate`、`mult`、`pattern_bonus`。
- `combine` 預設 `"max"`。`pattern_multiplier` 預設 `Fraction(1)`。
- **combine 語意的實作刻意在 `naive.py` / `engine.py` / `montecarlo.py` 各寫一份**（三份共 15 行）。這不是待消除的重複，是交叉檢查的一部分；每份都要有註解說明。
- **不使用 hypothesis。** property-based 測試以 `random.Random(fixed_seed)` 的顯式迴圈實作，保持確定性。
- Python 3.11+（需 `math.lcm` 吃多引數、`Self` 型別）。
- 每個 task 結束時 `pytest` 全綠才 commit。

### 相對 spec 的一處精確化

spec §6.3 的 `payout_distribution` 只列 `payout`（float）。本計畫改為每個 bucket 同時存 `payout_units`（整數，權威）與 `payout`（float，僅供人讀），Layer 1 的一致性檢查全程走整數。理由：若以 float 相乘驗證整數總和，會把浮點誤差引進本來要保護的那條不變量。

---

## File Structure

| 檔案 | 職責 |
| --- | --- |
| `pyproject.toml` | 套件定義與依賴（pydantic、pytest） |
| `src/slotmath/spec.py` | Pydantic models、`Rational` 型別、載入與驗證。唯一的信任邊界 |
| `src/slotmath/windows.py` | 環狀 window 抽取、`ColumnPlan`、signature 化 |
| `src/slotmath/naive.py` | 全窮舉評估器。信任錨點，零抽象 |
| `src/slotmath/metrics.py` | `payout_units` 分佈 → `Metrics` |
| `src/slotmath/engine.py` | signature 聚合評估器 + 反爆炸護欄 |
| `src/slotmath/montecarlo.py` | 獨立第三路徑模擬。不 import `windows`/`engine` |
| `src/slotmath/verify.py` | `ReelConfig` model、三層驗證、gate 契約 |
| `src/slotmath/diophantine.py` | signature 盈虧權重 `w_s`、reel2 精確搜尋 |
| `src/slotmath/solver.py` | 四階段編排、長度候選、放棄條件 |
| `src/slotmath/portfolio.py` | 多樣性特徵向量、距離判準、校準 |
| `src/slotmath/cli.py` | `slotmath spec\|solve\|verify\|report\|explore` |
| `scripts/hooks/verify_on_write.py` | PostToolUse hook entry。薄，快 |
| `configs/homework-3x3.json` | 驗收例 GameSpec |
| `.claude/settings.json` | hook 註冊 |
| `.claude/skills/*/SKILL.md` | 四支 skill |
| `tests/` | 對應各模組 |

---

## Task 1：專案骨架與 GameSpec 模型

**Files:**
- Create: `pyproject.toml`
- Create: `src/slotmath/__init__.py`
- Create: `src/slotmath/spec.py`
- Create: `configs/homework-3x3.json`
- Test: `tests/test_spec.py`

**Interfaces:**
- Produces:
  - `Rational`（`Annotated[Fraction, ...]`，輸入吃 int/float/str，序列化為 float）
  - `Grid(cols: int, rows: int)`
  - `Pattern(name: str, cells: list[tuple[int,int]], pattern_multiplier: Rational)`
  - `Targets(rtp: Rational, min_win_rate: Rational)`
  - `GameSpec(name, grid, symbols: dict[int, Rational], patterns, combine, targets)`
  - `GameSpec.payout_unit_denominator() -> int`
  - `GameSpec.payout_units(symbol: int, pattern: Pattern) -> int`
  - `load_spec(path) -> GameSpec`

- [ ] **Step 1：建立 `pyproject.toml`**

```toml
[project]
name = "slotmath"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.6"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
slotmath = "slotmath.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2：寫失敗的測試**

`tests/test_spec.py`：

```python
from fractions import Fraction
import pytest
from pydantic import ValidationError
from slotmath.spec import GameSpec, load_spec


def _base():
    return {
        "name": "t",
        "grid": {"cols": 3, "rows": 3},
        "symbols": {"0": 0.25, "1": 0.55, "2": 1},
        "patterns": [{"name": "TL", "cells": [[0, 0], [0, 1], [1, 0], [1, 1]]}],
        "targets": {"rtp": 0.95, "min_win_rate": 0.55},
    }


def test_float_055_becomes_exact_eleven_twentieths():
    spec = GameSpec.model_validate(_base())
    assert spec.symbols[1] == Fraction(11, 20)


def test_string_rational_accepted():
    d = _base()
    d["symbols"]["2"] = "1/3"
    assert GameSpec.model_validate(d).symbols[2] == Fraction(1, 3)


def test_combine_defaults_to_max():
    assert GameSpec.model_validate(_base()).combine == "max"


def test_pattern_multiplier_defaults_to_one():
    spec = GameSpec.model_validate(_base())
    assert spec.patterns[0].pattern_multiplier == Fraction(1)


def test_cells_all_expands_to_every_cell():
    d = _base()
    d["patterns"] = [{"name": "FULL", "cells": "all", "pattern_multiplier": 5}]
    cells = GameSpec.model_validate(d).patterns[0].cells
    assert len(cells) == 9
    assert (2, 2) in cells and (0, 0) in cells


def test_out_of_bounds_cell_rejected():
    d = _base()
    d["patterns"] = [{"name": "X", "cells": [[3, 0]]}]
    with pytest.raises(ValidationError, match="out of bounds"):
        GameSpec.model_validate(d)


def test_duplicate_cell_rejected():
    d = _base()
    d["patterns"] = [{"name": "X", "cells": [[0, 0], [0, 0]]}]
    with pytest.raises(ValidationError, match="duplicate"):
        GameSpec.model_validate(d)


def test_payout_unit_denominator_is_lcm_of_all_payout_denominators():
    d = _base()
    d["patterns"] = [
        {"name": "TL", "cells": [[0, 0]]},
        {"name": "FULL", "cells": "all", "pattern_multiplier": 5},
    ]
    # payouts: 0.25,0.55,1 and x5 -> denominators 4,20,1 -> lcm 20
    assert GameSpec.model_validate(d).payout_unit_denominator() == 20


def test_payout_units_is_integer():
    spec = GameSpec.model_validate(_base())
    p = spec.patterns[0]
    assert spec.payout_units(1, p) == 11    # 0.55 * 20
    assert spec.payout_units(0, p) == 5     # 0.25 * 20


def test_homework_config_loads():
    spec = load_spec("configs/homework-3x3.json")
    assert spec.grid.cols == 3 and spec.grid.rows == 3
    assert len(spec.patterns) == 5
    assert spec.targets.rtp == Fraction(19, 20)
    assert spec.targets.min_win_rate == Fraction(11, 20)
    assert spec.payout_unit_denominator() == 20
```

- [ ] **Step 3：跑測試確認失敗**

Run: `pytest tests/test_spec.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.spec'`

- [ ] **Step 4：實作 `src/slotmath/spec.py`**

```python
"""GameSpec: the single trust boundary. All external input is validated here."""

from __future__ import annotations

import json
from fractions import Fraction
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

    def payout_unit_denominator(self) -> int:
        """Smallest D such that every reachable payout is an integer number of 1/D."""
        return lcm(
            *(
                (sym * p.pattern_multiplier).denominator
                for sym in self.symbols.values()
                for p in self.patterns
            )
        )

    def payout_units(self, symbol: int, pattern: Pattern) -> int:
        payout = self.symbols[symbol] * pattern.pattern_multiplier
        units = payout * self.payout_unit_denominator()
        assert units.denominator == 1, "payout_unit_denominator is wrong"
        return int(units)


def load_spec(path: str | Path) -> GameSpec:
    return GameSpec.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
```

- [ ] **Step 5：建立 `configs/homework-3x3.json`**

```json
{
  "name": "homework-3x3",
  "grid": { "cols": 3, "rows": 3 },
  "symbols": { "0": 0.25, "1": 0.55, "2": 1, "3": 3, "4": 5 },
  "patterns": [
    { "name": "TL",   "cells": [[0,0],[0,1],[1,0],[1,1]] },
    { "name": "TR",   "cells": [[1,0],[1,1],[2,0],[2,1]] },
    { "name": "BL",   "cells": [[0,1],[0,2],[1,1],[1,2]] },
    { "name": "BR",   "cells": [[1,1],[1,2],[2,1],[2,2]] },
    { "name": "FULL", "cells": "all", "pattern_multiplier": 5 }
  ],
  "targets": { "rtp": 0.95, "min_win_rate": 0.55 }
}
```

- [ ] **Step 6：建立 `src/slotmath/__init__.py`（空檔）並安裝**

Run: `pip install -e ".[dev]"`

- [ ] **Step 7：跑測試確認通過**

Run: `pytest tests/test_spec.py -v`
Expected: 全部 PASS

- [ ] **Step 8：Commit**

```bash
git add pyproject.toml src/slotmath/__init__.py src/slotmath/spec.py configs/homework-3x3.json tests/test_spec.py
git commit -m "feat: add GameSpec model with exact rational coercion"
```

---

## Task 2：環狀 window 抽取與 signature 化

**Files:**
- Create: `src/slotmath/windows.py`
- Test: `tests/test_windows.py`

**Interfaces:**
- Consumes: `GameSpec`, `Pattern`（Task 1）
- Produces:
  - `reel_windows(strip: Sequence[int], rows: int) -> list[tuple[int, ...]]`
  - `ColumnPlan`（frozen dataclass，欄位 `col: int`、`entries: tuple[tuple[int, tuple[int, ...]], ...]`，其中每個 entry 是 `(pattern_index, 該 pattern 在此欄用到的 row tuple)`）
  - `column_plans(spec: GameSpec) -> list[ColumnPlan]`
  - `window_signature(window: tuple[int, ...], plan: ColumnPlan) -> tuple[int | None, ...]`

- [ ] **Step 1：寫失敗的測試**

`tests/test_windows.py`：

```python
import pytest
from slotmath.spec import GameSpec
from slotmath.windows import ColumnPlan, column_plans, reel_windows, window_signature


def test_windows_wrap_around_cyclically():
    assert reel_windows([1, 2, 3, 4], 3) == [
        (1, 2, 3), (2, 3, 4), (3, 4, 1), (4, 1, 2),
    ]


def test_window_count_equals_strip_length():
    assert len(reel_windows([0] * 7, 3)) == 7


def test_strip_length_equal_to_rows_wraps_onto_itself():
    assert reel_windows([1, 2, 3], 3) == [(1, 2, 3), (2, 3, 1), (3, 1, 2)]


def test_strip_shorter_than_rows_is_rejected():
    with pytest.raises(ValueError, match="at least 3"):
        reel_windows([1, 2], 3)


def _spec_3x3():
    return GameSpec.model_validate({
        "name": "t",
        "grid": {"cols": 3, "rows": 3},
        "symbols": {"0": 0.25, "1": 0.55, "2": 1, "3": 3, "4": 5},
        "patterns": [
            {"name": "TL", "cells": [[0, 0], [0, 1], [1, 0], [1, 1]]},
            {"name": "BL", "cells": [[0, 1], [0, 2], [1, 1], [1, 2]]},
            {"name": "FULL", "cells": "all", "pattern_multiplier": 5},
        ],
        "targets": {"rtp": 0.95},
    })


def test_column_plan_lists_only_patterns_touching_that_column():
    plans = column_plans(_spec_3x3())
    # column 2 is touched only by FULL (pattern index 2)
    assert [idx for idx, _ in plans[2].entries] == [2]
    # column 0 is touched by TL, BL, FULL
    assert [idx for idx, _ in plans[0].entries] == [0, 1, 2]


def test_column_plan_records_rows_used_in_that_column():
    plans = column_plans(_spec_3x3())
    entries = dict(plans[0].entries)
    assert entries[0] == (0, 1)          # TL uses rows 0,1 in column 0
    assert entries[1] == (1, 2)          # BL uses rows 1,2 in column 0
    assert entries[2] == (0, 1, 2)       # FULL uses all rows


def test_signature_is_symbol_when_all_rows_match_else_none():
    plan = column_plans(_spec_3x3())[0]
    # window (2,2,2): TL rows(0,1) all 2, BL rows(1,2) all 2, FULL all 2
    assert window_signature((2, 2, 2), plan) == (2, 2, 2)
    # window (2,2,3): TL matches on 2, BL does not, FULL does not
    assert window_signature((2, 2, 3), plan) == (2, None, None)
    # window (3,2,2): TL no, BL yes on 2, FULL no
    assert window_signature((3, 2, 2), plan) == (None, 2, None)
    # window (0,1,2): nothing matches
    assert window_signature((0, 1, 2), plan) == (None, None, None)


def test_distinct_signature_count_for_homework_column_is_16():
    """5 all-same + 5 top-pair-only + 5 bottom-pair-only + 1 none = 16.

    The 20 windows with a top pair only all share the signature (a, None, None),
    so they collapse to 5 distinct values, not 20. That collapse is the whole
    point of signatures: 125 windows become 16 equivalence classes.
    """
    plan = column_plans(_spec_3x3())[0]
    seen = {
        window_signature((a, b, c), plan)
        for a in range(5) for b in range(5) for c in range(5)
    }
    assert len(seen) == 16
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_windows.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.windows'`

- [ ] **Step 3：實作 `src/slotmath/windows.py`**

```python
"""Cyclic reel windows and per-column pattern signatures.

A reel is a cyclic strip. A spin stops at position r and the column shows
`rows` consecutive symbols starting at r, wrapping at the end of the strip.

A *signature* is the projection of a window onto what the patterns can
observe in that column: for each pattern touching the column, either the
symbol that fills all of the pattern's cells in that column, or None.
Two windows with the same signature are interchangeable for every payout
calculation, which is what makes the aggregation in engine.py exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from slotmath.spec import GameSpec


def reel_windows(strip: Sequence[int], rows: int) -> list[tuple[int, ...]]:
    length = len(strip)
    if length < rows:
        raise ValueError(f"reel strip must hold at least {rows} symbols, got {length}")
    return [tuple(strip[(r + k) % length] for k in range(rows)) for r in range(length)]


@dataclass(frozen=True)
class ColumnPlan:
    """Which patterns observe this column, and through which rows."""

    col: int
    entries: tuple[tuple[int, tuple[int, ...]], ...]


def column_plans(spec: GameSpec) -> list[ColumnPlan]:
    plans: list[ColumnPlan] = []
    for col in range(spec.grid.cols):
        entries = []
        for idx, pattern in enumerate(spec.patterns):
            rows = tuple(sorted(r for c, r in pattern.cells if c == col))
            if rows:
                entries.append((idx, rows))
        plans.append(ColumnPlan(col=col, entries=tuple(entries)))
    return plans


def window_signature(
    window: tuple[int, ...], plan: ColumnPlan
) -> tuple[int | None, ...]:
    out: list[int | None] = []
    for _, rows in plan.entries:
        first = window[rows[0]]
        out.append(first if all(window[r] == first for r in rows) else None)
    return tuple(out)
```

- [ ] **Step 4：跑測試確認通過**

Run: `pytest tests/test_windows.py -v`
Expected: 全部 PASS，含 `test_distinct_signature_count_for_homework_column_is_16`

- [ ] **Step 5：Commit**

```bash
git add src/slotmath/windows.py tests/test_windows.py
git commit -m "feat: add cyclic window extraction and column signatures"
```

---

## Task 3：naive.py 全窮舉評估器（信任錨點）

`naive.py` 是整個系統的信任錨點，必須笨到不可能錯：直接把盤面展開、直接比對格子、不使用 `windows.py` 的 signature 抽象。它只被 verifier 與測試呼叫，不進 solver 內圈。

**Files:**
- Create: `src/slotmath/naive.py`
- Test: `tests/test_naive.py`

**Interfaces:**
- Consumes: `GameSpec`（Task 1）、`reel_windows`（Task 2）
- Produces:
  - `grid_payout_units(spec: GameSpec, columns: Sequence[tuple[int, ...]]) -> int`
  - `evaluate(spec: GameSpec, reels: Sequence[Sequence[int]]) -> dict[int, int]`（回傳 `payout_units -> combo_count`）

- [ ] **Step 1：寫失敗的測試**

`tests/test_naive.py`：

```python
import pytest
from slotmath.naive import evaluate, grid_payout_units
from slotmath.spec import GameSpec

HOMEWORK = {
    "name": "hw",
    "grid": {"cols": 3, "rows": 3},
    "symbols": {"0": 0.25, "1": 0.55, "2": 1, "3": 3, "4": 5},
    "patterns": [
        {"name": "TL", "cells": [[0, 0], [0, 1], [1, 0], [1, 1]]},
        {"name": "TR", "cells": [[1, 0], [1, 1], [2, 0], [2, 1]]},
        {"name": "BL", "cells": [[0, 1], [0, 2], [1, 1], [1, 2]]},
        {"name": "BR", "cells": [[1, 1], [1, 2], [2, 1], [2, 2]]},
        {"name": "FULL", "cells": "all", "pattern_multiplier": 5},
    ],
    "targets": {"rtp": 0.95, "min_win_rate": 0.55},
}


def hw(**over):
    return GameSpec.model_validate({**HOMEWORK, **over})


@pytest.mark.parametrize(
    "symbol,expected_units",
    [(0, 25), (1, 55), (2, 100), (3, 300), (4, 500)],
)
def test_uniform_reels_pay_full_board_for_every_symbol(symbol, expected_units):
    """Hand-computed: every stop shows 9 identical symbols, so FULL always wins
    and max-only picks it: payout = symbol_multiplier * 5, in 1/20 units."""
    spec = hw()
    reels = [[symbol] * 4, [symbol] * 5, [symbol] * 6]
    dist = evaluate(spec, reels)
    assert dist == {expected_units: 4 * 5 * 6}


def test_no_win_board_pays_zero():
    spec = hw()
    # every column is a strict cycle of 3 distinct symbols offset so no 2x2 forms
    reels = [[0, 1, 2], [1, 2, 0], [2, 0, 1]]
    dist = evaluate(spec, reels)
    assert set(dist) == {0}
    assert dist[0] == 27


def test_max_only_picks_the_largest_winning_pattern():
    spec = hw()
    grid = [(2, 2, 2), (2, 2, 2), (2, 2, 2)]   # all nine identical -> all 5 win
    # max is FULL: 1 * 5 = 5 -> 100 units (not the sum 9*20 = 180)
    assert grid_payout_units(spec, grid) == 100


def test_sum_combine_adds_every_winning_pattern():
    spec = hw(combine="sum")
    grid = [(2, 2, 2), (2, 2, 2), (2, 2, 2)]
    # TL+TR+BL+BR = 4*20, FULL = 100 -> 180
    assert grid_payout_units(spec, grid) == 180


def test_sum_combine_with_two_overlapping_patterns_only():
    spec = hw(combine="sum")
    # top 2x3 block of symbol 0, bottom row spoils BL/BR/FULL
    grid = [(0, 0, 3), (0, 0, 4), (0, 0, 3)]
    # TL = 5 units, TR = 5 units -> 10
    assert grid_payout_units(spec, grid) == 10


def test_max_combine_with_two_overlapping_patterns_only():
    spec = hw()
    grid = [(0, 0, 3), (0, 0, 4), (0, 0, 3)]
    assert grid_payout_units(spec, grid) == 5


def test_distribution_counts_sum_to_spin_count():
    spec = hw()
    reels = [[0, 1, 2, 2, 3], [1, 1, 2, 0], [2, 2, 2, 4, 1, 0]]
    dist = evaluate(spec, reels)
    assert sum(dist.values()) == 5 * 4 * 6
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_naive.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.naive'`

- [ ] **Step 3：實作 `src/slotmath/naive.py`**

```python
"""Full-enumeration evaluator. The trust anchor.

This module is deliberately dumb: it expands the board, compares cells
directly, and does not use the signature abstraction in windows.py. It is
too slow for the solver's inner loop and is only called by the verifier and
the tests. Its job is to be obviously correct, not fast.

The combine logic below is duplicated in engine.py and montecarlo.py on
purpose -- three independent copies is how a mistake in one of them becomes
visible instead of silent. Do not factor it out.
"""

from __future__ import annotations

from itertools import product
from typing import Sequence

from slotmath.spec import GameSpec
from slotmath.windows import reel_windows


def grid_payout_units(spec: GameSpec, columns: Sequence[tuple[int, ...]]) -> int:
    """columns[col][row] -> symbol. Returns payout in 1/D units."""
    wins: list[int] = []
    for pattern in spec.patterns:
        first_col, first_row = pattern.cells[0]
        symbol = columns[first_col][first_row]
        if all(columns[c][r] == symbol for c, r in pattern.cells):
            wins.append(spec.payout_units(symbol, pattern))
    if not wins:
        return 0
    return max(wins) if spec.combine == "max" else sum(wins)


def evaluate(spec: GameSpec, reels: Sequence[Sequence[int]]) -> dict[int, int]:
    """Full cycle: every combination of stop positions counted exactly once."""
    if len(reels) != spec.grid.cols:
        raise ValueError(f"expected {spec.grid.cols} reels, got {len(reels)}")
    for reel in reels:
        unknown = set(reel) - set(spec.symbols)
        if unknown:
            raise ValueError(f"reel contains undeclared symbols: {sorted(unknown)}")

    per_column = [reel_windows(reel, spec.grid.rows) for reel in reels]
    dist: dict[int, int] = {}
    for columns in product(*per_column):
        units = grid_payout_units(spec, columns)
        dist[units] = dist.get(units, 0) + 1
    return dist
```

- [ ] **Step 4：跑測試確認通過**

Run: `pytest tests/test_naive.py -v`
Expected: 全部 PASS。特別確認 5 個 `test_uniform_reels_pay_full_board_for_every_symbol` 參數化案例——這些是純手算、不依賴任何程式的錨點。

- [ ] **Step 5：Commit**

```bash
git add src/slotmath/naive.py tests/test_naive.py
git commit -m "feat: add naive full-enumeration evaluator as trust anchor"
```

---

## Task 4：metrics.py 指標推導

**Files:**
- Create: `src/slotmath/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `GameSpec`（Task 1）
- Produces:
  - `PayoutBucket(payout_units: int, payout: float, combo_count: int)`（Pydantic model）
  - `Metrics(spin_count, win_count, win_rate, total_payout_units, payout_unit_denominator, rtp, volatility, max_win, payout_distribution)`（Pydantic model；`win_rate`/`rtp`/`max_win` 為 float，`volatility` 為 float）
  - `build_metrics(spec: GameSpec, distribution: dict[int, int]) -> Metrics`
  - `exact_rtp(metrics: Metrics) -> Fraction`
  - `exact_win_rate(metrics: Metrics) -> Fraction`

- [ ] **Step 1：寫失敗的測試**

`tests/test_metrics.py`：

```python
from fractions import Fraction
from slotmath.metrics import build_metrics, exact_rtp, exact_win_rate
from tests.test_naive import hw


def test_fixture_c_metrics():
    """Fixture C from spec section 4.1: 0 x204, 1 x474, 5 x42 over N=720."""
    spec = hw()
    dist = {0: 204, 20: 474, 100: 42}      # 1 -> 20 units, 5 -> 100 units
    m = build_metrics(spec, dist)

    assert m.spin_count == 720
    assert m.win_count == 516
    assert m.payout_unit_denominator == 20
    assert m.total_payout_units == 474 * 20 + 42 * 100 == 13680
    assert exact_rtp(m) == Fraction(19, 20)
    assert exact_win_rate(m) == Fraction(43, 60)
    assert m.max_win == 5.0
    assert m.volatility == pytest.approx(1.1018923117377064)


def test_payout_buckets_are_sorted_and_carry_both_forms():
    spec = hw()
    m = build_metrics(spec, {100: 1, 0: 3, 11: 2})
    assert [b.payout_units for b in m.payout_distribution] == [0, 11, 100]
    assert [b.combo_count for b in m.payout_distribution] == [3, 2, 1]
    assert m.payout_distribution[1].payout == 0.55


def test_combo_counts_sum_to_spin_count():
    spec = hw()
    m = build_metrics(spec, {0: 10, 20: 5})
    assert sum(b.combo_count for b in m.payout_distribution) == m.spin_count == 15


def test_zero_payout_bucket_may_be_absent():
    spec = hw()
    m = build_metrics(spec, {20: 8})
    assert m.win_count == 8 and m.spin_count == 8
    assert exact_win_rate(m) == Fraction(1)


def test_empty_distribution_rejected():
    spec = hw()
    with pytest.raises(ValueError, match="empty"):
        build_metrics(spec, {})
```

（檔案頂端需 `import pytest`。）

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.metrics'`

- [ ] **Step 3：實作 `src/slotmath/metrics.py`**

```python
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
```

- [ ] **Step 4：跑測試確認通過**

Run: `pytest tests/test_metrics.py -v`
Expected: 全部 PASS

- [ ] **Step 5：Commit**

```bash
git add src/slotmath/metrics.py tests/test_metrics.py
git commit -m "feat: derive metrics from integer payout distribution"
```

---

## Task 5：engine.py signature 聚合與反爆炸護欄

**Files:**
- Create: `src/slotmath/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `GameSpec`（Task 1）、`column_plans`/`reel_windows`/`window_signature`（Task 2）、`naive.evaluate`（Task 3，僅測試用）
- Produces:
  - `SignatureBudgetExceeded(Exception)`（屬性 `sizes: list[tuple[int, int]]`，每項為 `(col, distinct_signature_count)`）
  - `signature_histograms(spec, reels) -> list[dict[tuple[int | None, ...], int]]`
  - `evaluate(spec: GameSpec, reels: Sequence[Sequence[int]], budget: int = 5_000_000) -> dict[int, int]`

- [ ] **Step 1：寫失敗的測試**

`tests/test_engine.py`：

```python
import random
import pytest
from slotmath import engine, naive
from slotmath.spec import GameSpec
from tests.test_naive import hw


def test_engine_matches_naive_on_homework_fixture_c():
    spec = hw()
    reels = [
        [2, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1],
        [2, 2, 2, 2, 3, 2],
        [4, 3, 2, 2, 1, 3, 2, 2, 2, 2],
    ]
    assert engine.evaluate(spec, reels) == naive.evaluate(spec, reels)


def _random_spec(rng: random.Random) -> GameSpec:
    cols = rng.randint(1, 3)
    rows = rng.randint(2, 4)
    n_symbols = rng.randint(2, 4)
    every = [(c, r) for c in range(cols) for r in range(rows)]
    patterns = []
    for i in range(rng.randint(1, 3)):
        size = rng.randint(1, len(every))
        patterns.append({
            "name": f"P{i}",
            "cells": rng.sample(every, size),
            "pattern_multiplier": rng.choice([1, 2, 5]),
        })
    return GameSpec.model_validate({
        "name": "rnd",
        "grid": {"cols": cols, "rows": rows},
        "symbols": {str(s): rng.choice([0.25, 0.55, 1, 3, 5]) for s in range(n_symbols)},
        "patterns": patterns,
        "combine": rng.choice(["max", "sum"]),
        "targets": {"rtp": 0.95},
    })


@pytest.mark.parametrize("seed", range(30))
def test_engine_equals_naive_on_random_specs(seed):
    """The highest-value test in the suite: it covers the correctness of the
    signature reduction across grid shapes, pattern masks and combine modes."""
    rng = random.Random(seed)
    spec = _random_spec(rng)
    symbols = sorted(spec.symbols)
    reels = [
        [rng.choice(symbols) for _ in range(rng.randint(spec.grid.rows, spec.grid.rows + 5))]
        for _ in range(spec.grid.cols)
    ]
    assert engine.evaluate(spec, reels) == naive.evaluate(spec, reels)


def test_histogram_counts_sum_to_reel_length():
    spec = hw()
    reels = [[2, 2, 2, 3, 0], [1, 1, 1, 1], [4, 4, 4, 4, 4, 0]]
    hists = engine.signature_histograms(spec, reels)
    assert [sum(h.values()) for h in hists] == [5, 4, 6]


def test_budget_exceeded_reports_offending_columns():
    """The strip must be built from runs. A strip with no adjacent repeats --
    list(range(5)) * 8, say -- collapses to exactly ONE signature per column
    (the all-None one), because no pattern can ever match, so it would never
    reach any budget."""
    spec = hw()
    runs = [s for s in range(5) for _ in range(4)] * 2   # 15 signatures/column
    reels = [runs, runs, runs]
    with pytest.raises(engine.SignatureBudgetExceeded) as exc:
        engine.evaluate(spec, reels, budget=10)
    assert len(exc.value.sizes) == 3
    assert all(isinstance(col, int) and count > 0 for col, count in exc.value.sizes)
    assert "column" in str(exc.value)
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.engine'`

- [ ] **Step 3：實作 `src/slotmath/engine.py`**

```python
"""Signature-aggregating evaluator.

Pattern matching decomposes per column: a pattern only observes whether its
cells within one column are all the same symbol, and which. So each reel can
be collapsed from L positions into a histogram over distinct signatures, and
the enumeration runs over signature combinations with integer weights. The
result is exact, not an approximation -- probabilities are count ratios.

Cost drops from prod(L_c) to prod(|Sig_c|).

The combine logic below duplicates naive.py and montecarlo.py on purpose.
See the note in naive.py.
"""

from __future__ import annotations

from itertools import product
from math import prod
from typing import Sequence

from slotmath.spec import GameSpec
from slotmath.windows import ColumnPlan, column_plans, reel_windows, window_signature


class SignatureBudgetExceeded(Exception):
    def __init__(self, sizes: list[tuple[int, int]], total: int, budget: int):
        self.sizes = sizes
        self.total = total
        self.budget = budget
        detail = ", ".join(f"column {c}: {n} signatures" for c, n in sizes)
        super().__init__(
            f"signature space is {total} combinations, over the budget of {budget} "
            f"({detail}). Shrink the grid, the pattern set, or the symbol count."
        )


def signature_histograms(
    spec: GameSpec, reels: Sequence[Sequence[int]]
) -> list[dict[tuple[int | None, ...], int]]:
    plans = column_plans(spec)
    histograms = []
    for plan, reel in zip(plans, reels):
        hist: dict[tuple[int | None, ...], int] = {}
        for window in reel_windows(reel, spec.grid.rows):
            sig = window_signature(window, plan)
            hist[sig] = hist.get(sig, 0) + 1
        histograms.append(hist)
    return histograms


def _payout_units(
    spec: GameSpec,
    plans: list[ColumnPlan],
    signatures: tuple[tuple[int | None, ...], ...],
) -> int:
    # For each pattern, collect the symbol each touched column reports.
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


def evaluate(
    spec: GameSpec, reels: Sequence[Sequence[int]], budget: int = 5_000_000
) -> dict[int, int]:
    if len(reels) != spec.grid.cols:
        raise ValueError(f"expected {spec.grid.cols} reels, got {len(reels)}")
    for reel in reels:
        unknown = set(reel) - set(spec.symbols)
        if unknown:
            raise ValueError(f"reel contains undeclared symbols: {sorted(unknown)}")

    plans = column_plans(spec)
    histograms = signature_histograms(spec, reels)

    sizes = [(col, len(h)) for col, h in enumerate(histograms)]
    total = prod(n for _, n in sizes)
    if total > budget:
        raise SignatureBudgetExceeded(sizes, total, budget)

    dist: dict[int, int] = {}
    keys = [list(h) for h in histograms]
    for combo in product(*keys):
        weight = prod(h[sig] for h, sig in zip(histograms, combo))
        units = _payout_units(spec, plans, combo)
        dist[units] = dist.get(units, 0) + weight
    return dist
```

- [ ] **Step 4：跑測試確認通過**

Run: `pytest tests/test_engine.py -v`
Expected: 全部 PASS，含 30 個隨機 spec 的等價案例

- [ ] **Step 5：Commit**

```bash
git add src/slotmath/engine.py tests/test_engine.py
git commit -m "feat: add signature-aggregating engine with explosion guard"
```

---

## Task 6：Golden fixtures 與 mod 5 不變量

**Files:**
- Create: `tests/fixtures.py`
- Create: `tests/test_golden.py`
- Test: 同上

**Interfaces:**
- Consumes: `naive.evaluate`、`engine.evaluate`、`build_metrics`、`exact_rtp`、`exact_win_rate`
- Produces: `tests/fixtures.py` 中的 `GOLDEN: list[Golden]`，`Golden(name, reels, spin_count, rtp, win_rate, distribution)`

- [ ] **Step 1：建立 `tests/fixtures.py`**

```python
"""Golden fixtures from spec section 4.1.

All three were cross-verified by three independent implementations; RTP is an
exact Fraction equality with 19/20, not an approximation.

Fixture A MUST NOT BE REMOVED even though its win_rate looks degenerate.
It is the only fixture with n1 != 0 (n1 = 324, and its N = 396 is not
divisible by 5), so it is the only one that catches a solver which silently
assumes n1 = 0. It is also the only fixture with win_rate = 1. B and C both
have 5 | N and n1 = 0 and would let that regression through.
See spec section 4.3.
"""

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Golden:
    name: str
    reels: list[list[int]]
    spin_count: int
    rtp: Fraction
    win_rate: Fraction
    distribution: dict[int, int]      # payout_units -> combo_count


GOLDEN = [
    Golden(
        name="A",
        reels=[[1, 0, 4, 1, 1, 1, 1, 0, 3, 2, 2], [1] * 6, [1] * 6],
        spin_count=396,
        rtp=Fraction(19, 20),
        win_rate=Fraction(1),
        distribution={11: 324, 55: 72},
    ),
    Golden(
        name="B",
        reels=[
            [2, 3, 3, 3, 3, 2, 2, 2, 2, 0, 0, 3, 3, 2, 2, 2],
            [2, 2, 2, 2, 3, 3, 2, 2, 0, 3],
            [2, 2, 2, 2, 2, 2],
        ],
        spin_count=960,
        rtp=Fraction(19, 20),
        win_rate=Fraction(13, 20),
        distribution={0: 336, 20: 528, 60: 48, 100: 48},
    ),
    Golden(
        name="C",
        reels=[
            [2, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1],
            [2, 2, 2, 2, 3, 2],
            [4, 3, 2, 2, 1, 3, 2, 2, 2, 2],
        ],
        spin_count=720,
        rtp=Fraction(19, 20),
        win_rate=Fraction(43, 60),
        distribution={0: 204, 20: 474, 100: 42},
    ),
]
```

- [ ] **Step 2：寫失敗的測試**

`tests/test_golden.py`：

```python
import random
from fractions import Fraction

import pytest

from slotmath import engine, naive
from slotmath.metrics import build_metrics, exact_rtp, exact_win_rate
from tests.fixtures import GOLDEN
from tests.test_naive import hw

IDS = [g.name for g in GOLDEN]


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_naive_reproduces_golden_distribution(g):
    assert naive.evaluate(hw(), g.reels) == g.distribution


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_engine_reproduces_golden_distribution(g):
    assert engine.evaluate(hw(), g.reels) == g.distribution


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_golden_rtp_is_exactly_nineteen_twentieths(g):
    m = build_metrics(hw(), naive.evaluate(hw(), g.reels))
    assert m.spin_count == g.spin_count
    assert exact_rtp(m) == g.rtp == Fraction(19, 20)
    assert exact_win_rate(m) == g.win_rate


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_golden_meets_min_win_rate(g):
    assert g.win_rate >= Fraction(11, 20)


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_mod5_invariant_holds_for_golden(g):
    """n1 = combos whose max payout is exactly 11 units (0.55 x bet).
    Necessary condition for RTP = 19/20: n1 = 4N (mod 5). See spec 4.2."""
    n1 = g.distribution.get(11, 0)
    assert n1 % 5 == (4 * g.spin_count) % 5


def test_fixture_a_is_the_only_one_exercising_nonzero_n1():
    """Guard against someone deleting fixture A as redundant. See spec 4.3."""
    nonzero = [g.name for g in GOLDEN if g.distribution.get(11, 0) != 0]
    assert nonzero == ["A"]


def test_mod5_invariant_rules_out_configs_that_violate_it():
    """Contrapositive of the invariant: if n1 is in the wrong residue class,
    RTP cannot be 19/20.

    Written this way because the forward direction is unreachable here --
    random reels essentially never land on an exact 19/20, so a test guarded
    by `if rtp == 19/20` would be dead code that always passes. The forward
    direction is covered by test_mod5_invariant_holds_for_golden, which runs
    on fixtures whose RTP really is 19/20.
    """
    spec = hw()
    exercised = 0
    for seed in range(40):
        rng = random.Random(1000 + seed)
        reels = [[rng.randint(0, 4) for _ in range(rng.randint(3, 8))] for _ in range(3)]
        dist = naive.evaluate(spec, reels)
        m = build_metrics(spec, dist)
        if dist.get(11, 0) % 5 != (4 * m.spin_count) % 5:
            exercised += 1
            assert exact_rtp(m) != Fraction(19, 20)
    # Guard against this test silently going vacuous again.
    assert exercised >= 10, f"only {exercised}/40 seeds exercised the assertion"
```

- [ ] **Step 3：跑測試確認失敗**

Run: `pytest tests/test_golden.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'tests.fixtures'`（若 fixtures.py 尚未建立）。建立後應全部 PASS——這些 fixture 的數值已驗證正確，故此 task 的「失敗」只來自檔案缺失。

- [ ] **Step 4：確保 `tests/__init__.py` 存在使 `tests.fixtures` 可 import**

Run: `touch tests/__init__.py`

- [ ] **Step 5：跑測試確認通過**

Run: `pytest tests/test_golden.py -v`
Expected: 全部 PASS

- [ ] **Step 6：Commit**

```bash
git add tests/__init__.py tests/fixtures.py tests/test_golden.py
git commit -m "test: add golden fixtures A/B/C and mod-5 invariant checks"
```

---

## Task 7：montecarlo.py 獨立第三路徑

**Files:**
- Create: `src/slotmath/montecarlo.py`
- Test: `tests/test_montecarlo.py`

**Interfaces:**
- Consumes: `GameSpec`（Task 1）。**不得 import `windows` 或 `engine`。**
- Produces:
  - `SimResult(spins: int, total_units: int, win_count: int)`（frozen dataclass）
  - `simulate(spec, reels, spins: int, seed: int) -> SimResult`
  - `sigma_deviation(spec, reels, sim: SimResult, exact_distribution: dict[int, int]) -> float`

- [ ] **Step 1：寫失敗的測試**

`tests/test_montecarlo.py`：

```python
import pytest
from slotmath import montecarlo, naive
from tests.fixtures import GOLDEN
from tests.test_naive import hw

IDS = [g.name for g in GOLDEN]


def test_simulate_is_deterministic_for_a_fixed_seed():
    spec, reels = hw(), GOLDEN[2].reels
    a = montecarlo.simulate(spec, reels, spins=20_000, seed=7)
    b = montecarlo.simulate(spec, reels, spins=20_000, seed=7)
    assert a == b


def test_different_seeds_give_different_results():
    spec, reels = hw(), GOLDEN[2].reels
    a = montecarlo.simulate(spec, reels, spins=20_000, seed=7)
    b = montecarlo.simulate(spec, reels, spins=20_000, seed=8)
    assert a != b


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_monte_carlo_agrees_with_exact_within_five_sigma(g):
    """Fixed seed makes this deterministic, so it is safe as a hard gate."""
    spec = hw()
    exact = naive.evaluate(spec, g.reels)
    sim = montecarlo.simulate(spec, g.reels, spins=200_000, seed=20260731)
    assert abs(montecarlo.sigma_deviation(spec, g.reels, sim, exact)) < 5.0


def test_zero_variance_config_gives_zero_sigma():
    """Uniform reels: every spin pays the same, so variance is 0 and the
    simulated mean must equal the exact mean bit for bit."""
    spec = hw()
    reels = [[2] * 4, [2] * 4, [2] * 4]
    exact = naive.evaluate(spec, reels)
    sim = montecarlo.simulate(spec, reels, spins=5_000, seed=1)
    assert montecarlo.sigma_deviation(spec, reels, sim, exact) == 0.0


def test_montecarlo_does_not_import_engine_or_windows():
    """Layer 3 must not share abstractions with layers 1 and 2. See spec 9.3."""
    source = (
        __import__("pathlib").Path(montecarlo.__file__).read_text(encoding="utf-8")
    )
    assert "from slotmath.engine" not in source
    assert "from slotmath.windows" not in source
    assert "import slotmath.engine" not in source
    assert "import slotmath.windows" not in source
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_montecarlo.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.montecarlo'`

- [ ] **Step 3：實作 `src/slotmath/montecarlo.py`**

```python
"""Layer 3: an independent simulation path.

Layers 1 and 2 both rest on one shared assumption -- that the translation
from GameSpec to pattern matching is correct. If that translation is wrong
(the classic case being (col, row) written as (row, col)), naive.py and
engine.py are wrong together and cross-checking them stays silent.

So this module deliberately shares nothing with them: it spins for real,
indexes the strips directly, builds the board itself, and compares grid
cells with its own copy of the matching logic. It does not import windows.py
or engine.py -- there is a test that enforces this.

Because the seed is fixed, the check is deterministic (passing today means
passing forever), which is what makes it usable as a hard gate rather than a
warning nobody reads.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction
from math import sqrt
from typing import Sequence

from slotmath.spec import GameSpec


@dataclass(frozen=True)
class SimResult:
    spins: int
    total_units: int
    win_count: int


def _board_payout_units(spec: GameSpec, board: list[list[int]]) -> int:
    """board[col][row]. Independent copy of the combine logic -- see module docstring."""
    wins: list[int] = []
    for pattern in spec.patterns:
        cells = pattern.cells
        symbol = board[cells[0][0]][cells[0][1]]
        matched = True
        for col, row in cells:
            if board[col][row] != symbol:
                matched = False
                break
        if matched:
            wins.append(spec.payout_units(symbol, pattern))
    if not wins:
        return 0
    return max(wins) if spec.combine == "max" else sum(wins)


def simulate(
    spec: GameSpec, reels: Sequence[Sequence[int]], spins: int, seed: int
) -> SimResult:
    rng = random.Random(seed)
    rows = spec.grid.rows
    lengths = [len(reel) for reel in reels]
    total_units = 0
    win_count = 0

    for _ in range(spins):
        board = []
        for reel, length in zip(reels, lengths):
            stop = rng.randrange(length)
            board.append([reel[(stop + k) % length] for k in range(rows)])
        units = _board_payout_units(spec, board)
        total_units += units
        if units:
            win_count += 1

    return SimResult(spins=spins, total_units=total_units, win_count=win_count)


def sigma_deviation(
    spec: GameSpec,
    reels: Sequence[Sequence[int]],
    sim: SimResult,
    exact_distribution: dict[int, int],
) -> float:
    """How many standard errors the simulated mean sits from the exact mean.

    The variance comes from the true payout distribution, not an assumption.
    """
    denominator = spec.payout_unit_denominator()
    spin_count = sum(exact_distribution.values())
    exact_mean = Fraction(
        sum(u * c for u, c in exact_distribution.items()), denominator * spin_count
    )
    variance = sum(
        c * (Fraction(u, denominator) - exact_mean) ** 2
        for u, c in exact_distribution.items()
    ) / spin_count

    if variance == 0:
        observed = Fraction(sim.total_units, denominator * sim.spins)
        return 0.0 if observed == exact_mean else float("inf")

    standard_error = sqrt(float(variance) / sim.spins)
    observed = sim.total_units / (denominator * sim.spins)
    return (observed - float(exact_mean)) / standard_error
```

- [ ] **Step 4：跑測試確認通過**

Run: `pytest tests/test_montecarlo.py -v`
Expected: 全部 PASS。若某個 golden fixture 的 5σ 檢查失敗，先確認 `sigma_deviation` 的變異數計算，不要直接放寬門檻。

- [ ] **Step 5：Commit**

```bash
git add src/slotmath/montecarlo.py tests/test_montecarlo.py
git commit -m "feat: add independent Monte Carlo cross-check path"
```

---

## Task 8：verify.py 三層驗證與 gate 契約

**Files:**
- Create: `src/slotmath/verify.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `GameSpec`、`Metrics`/`build_metrics`/`exact_rtp`/`exact_win_rate`、`naive.evaluate`、`engine.evaluate`、`montecarlo.simulate`/`sigma_deviation`
- Produces:
  - `ReelConfig(spec: str, reels: list[list[int]], metrics: Metrics, solver: dict | None = None)`（Pydantic model）
  - `Gate(name: str, passed: bool, severity: Literal["fail", "warn"], detail: str)`
  - `VerifyReport(gates: list[Gate], passed: bool)`，附 `VerifyReport.render() -> str`
  - `verify(spec, config, mc_spins=2_000_000, mc_seed=20260731, sigma_limit=5.0) -> VerifyReport`

- [ ] **Step 1：寫失敗的測試**

`tests/test_verify.py`：

```python
import copy
import pytest

from slotmath import naive
from slotmath.metrics import build_metrics
from slotmath.verify import ReelConfig, verify
from tests.fixtures import GOLDEN
from tests.test_naive import hw

MC = dict(mc_spins=20_000, mc_seed=20260731)


def config_for(g, **over):
    spec = hw()
    metrics = build_metrics(spec, naive.evaluate(spec, g.reels))
    data = {
        "spec": "configs/homework-3x3.json",
        "reels": g.reels,
        "metrics": metrics.model_dump(),
        "solver": {"version": "0.1.0", "seed": 1, "command": "x"},
    }
    data.update(over)
    return ReelConfig.model_validate(data)


@pytest.mark.parametrize("g", GOLDEN, ids=[g.name for g in GOLDEN])
def test_golden_configs_pass_every_gate(g):
    report = verify(hw(), config_for(g), **MC)
    assert report.passed, report.render()


def test_undeclared_symbol_fails():
    g = GOLDEN[2]
    bad = copy.deepcopy(g.reels)
    bad[0][0] = 99
    report = verify(hw(), config_for(g, reels=bad), **MC)
    assert not report.passed
    assert any("undeclared" in gate.detail for gate in report.gates if not gate.passed)


def test_spin_count_not_matching_reel_lengths_fails():
    g = GOLDEN[2]
    cfg = config_for(g)
    cfg.metrics.spin_count += 1
    report = verify(hw(), cfg, **MC)
    assert not report.passed
    assert any(gate.name == "file_consistency" and not gate.passed for gate in report.gates)


def test_combo_counts_not_summing_to_spin_count_fails():
    g = GOLDEN[2]
    cfg = config_for(g)
    cfg.metrics.payout_distribution[0].combo_count += 3
    report = verify(hw(), cfg, **MC)
    assert not report.passed
    assert any(gate.name == "file_consistency" and not gate.passed for gate in report.gates)


def test_stale_metrics_fail_with_recompute_message_not_engine_bug_message():
    """Engines agree with each other but not with the file: that is a stale
    artifact, not a program bug. The two must be reported differently.

    The shift is between the two *non-zero* buckets (20 and 100 units) so the
    zero bucket -- and therefore win_count, which is derived from it -- stays
    untouched. That keeps the mutated metrics internally self-consistent, so
    Layer 1 must NOT fire and only the comparison against a fresh recompute
    fails. Shifting a combo out of the zero bucket instead would desync
    win_count and trip file_consistency before Layer 2 is ever reached,
    conflating a stale artifact with a corrupted one.
    """
    g = GOLDEN[2]
    cfg = config_for(g)
    cfg.metrics.total_payout_units -= 80
    cfg.metrics.payout_distribution[1].combo_count += 1
    cfg.metrics.payout_distribution[2].combo_count -= 1
    report = verify(hw(), cfg, **MC)
    failed = {gate.name for gate in report.gates if not gate.passed}
    assert "file_matches_recompute" in failed
    assert "engine_matches_naive" not in failed


def test_rtp_off_target_fails_even_when_very_close():
    """0.95042... must fail. No tolerance band exists."""
    spec = hw()
    reels = [
        [4, 4, 4, 3, 3, 2, 2, 2, 2, 0, 0, 0],
        [0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 2, 2],
        [2, 2, 2, 2, 2, 2, 2, 2, 4],
    ]
    metrics = build_metrics(spec, naive.evaluate(spec, reels))
    cfg = ReelConfig.model_validate({
        "spec": "configs/homework-3x3.json",
        "reels": reels,
        "metrics": metrics.model_dump(),
    })
    report = verify(spec, cfg, **MC)
    assert not report.passed
    assert any(gate.name == "rtp_exact" and not gate.passed for gate in report.gates)


def test_win_rate_below_minimum_fails():
    spec = hw()
    reels = [[0, 1, 2], [1, 2, 0], [2, 0, 1]]     # never wins
    metrics = build_metrics(spec, naive.evaluate(spec, reels))
    cfg = ReelConfig.model_validate({
        "spec": "x", "reels": reels, "metrics": metrics.model_dump()
    })
    report = verify(spec, cfg, **MC)
    assert any(gate.name == "min_win_rate" and not gate.passed for gate in report.gates)


def test_win_rate_of_one_produces_a_warning_but_still_passes():
    """Fixture A: the player never comes up empty. Legal, commercially odd."""
    report = verify(hw(), config_for(GOLDEN[0]), **MC)
    assert report.passed
    assert any(gate.severity == "warn" and not gate.passed for gate in report.gates)


@pytest.mark.parametrize("mutation", [None, "delete", "garbage"])
def test_solver_block_is_non_authoritative(mutation):
    """Deleting or corrupting the solver block must not change the verdict
    bit for bit. See spec 6.3."""
    g = GOLDEN[2]
    baseline = verify(hw(), config_for(g), **MC).model_dump()

    if mutation == "delete":
        cfg = config_for(g, solver=None)
    elif mutation == "garbage":
        cfg = config_for(g, solver={"version": "LIES", "seed": -1, "extra": [1, 2]})
    else:
        cfg = config_for(g)

    assert verify(hw(), cfg, **MC).model_dump() == baseline
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_verify.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.verify'`

- [ ] **Step 3：實作 `src/slotmath/verify.py`**

```python
"""Three-layer verification.

Layer 1 reads the artifact and checks it against itself -- zero computation,
because the integer counts make contradictions visible on their own.
Layer 2 recomputes with both engines and requires exact Fraction agreement
between naive, engine and the file.
Layer 3 simulates along an independent path (montecarlo.py).

Failures in layer 2 must distinguish "the engines disagree with each other"
(a program bug) from "the engines agree but the file does not" (a stale or
edited artifact). Reporting both as "verification failed" is the same as not
reporting.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel

from slotmath import engine, montecarlo, naive
from slotmath.metrics import Metrics, build_metrics, exact_rtp, exact_win_rate
from slotmath.spec import GameSpec


class ReelConfig(BaseModel):
    spec: str
    reels: list[list[int]]
    metrics: Metrics
    solver: dict | None = None


class Gate(BaseModel):
    name: str
    passed: bool
    severity: Literal["fail", "warn"]
    detail: str


class VerifyReport(BaseModel):
    gates: list[Gate]
    passed: bool

    def render(self) -> str:
        lines = []
        for gate in self.gates:
            mark = "PASS" if gate.passed else gate.severity.upper()
            lines.append(f"[{mark:4}] {gate.name}: {gate.detail}")
        lines.append(f"verdict: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


def _distribution(metrics: Metrics) -> dict[int, int]:
    return {b.payout_units: b.combo_count for b in metrics.payout_distribution}


def verify(
    spec: GameSpec,
    config: ReelConfig,
    mc_spins: int = 2_000_000,
    mc_seed: int = 20260731,
    sigma_limit: float = 5.0,
) -> VerifyReport:
    gates: list[Gate] = []

    def add(name, passed, detail, severity="fail"):
        gates.append(Gate(name=name, passed=passed, severity=severity, detail=detail))

    # ---- symbols declared -------------------------------------------------
    unknown = sorted({s for reel in config.reels for s in reel} - set(spec.symbols))
    add(
        "symbols_declared",
        not unknown,
        "all reel symbols are declared" if not unknown
        else f"reels contain undeclared symbols: {unknown}",
    )
    if unknown:
        return VerifyReport(gates=gates, passed=False)

    # ---- Layer 1: file internal consistency -------------------------------
    m = config.metrics
    dist = _distribution(m)
    problems: list[str] = []

    expected_spins = 1
    for reel in config.reels:
        expected_spins *= len(reel)
    if m.spin_count != expected_spins:
        problems.append(
            f"spin_count {m.spin_count} != product of reel lengths {expected_spins}"
        )
    if sum(dist.values()) != m.spin_count:
        problems.append(
            f"combo_count sum {sum(dist.values())} != spin_count {m.spin_count}"
        )
    units = sum(u * c for u, c in dist.items())
    if units != m.total_payout_units:
        problems.append(
            f"sum(payout_units x combo_count) {units} != total_payout_units "
            f"{m.total_payout_units}"
        )
    if m.win_count != m.spin_count - dist.get(0, 0):
        problems.append(f"win_count {m.win_count} disagrees with the zero bucket")
    for bucket in m.payout_distribution:
        if bucket.payout_units / m.payout_unit_denominator != bucket.payout:
            problems.append(f"bucket {bucket.payout_units} payout float is inconsistent")

    add(
        "file_consistency",
        not problems,
        "artifact is internally consistent" if not problems else "; ".join(problems),
    )
    if problems:
        return VerifyReport(gates=gates, passed=False)

    # ---- Layer 2: engine vs naive vs file ---------------------------------
    naive_dist = naive.evaluate(spec, config.reels)
    engine_dist = engine.evaluate(spec, config.reels)

    engines_agree = naive_dist == engine_dist
    add(
        "engine_matches_naive",
        engines_agree,
        "signature engine agrees with full enumeration" if engines_agree
        else "ENGINES DISAGREE -- this is a program bug, not a bad artifact. "
             f"naive={naive_dist} engine={engine_dist}",
    )
    if not engines_agree:
        return VerifyReport(gates=gates, passed=False)

    file_agrees = naive_dist == dist
    add(
        "file_matches_recompute",
        file_agrees,
        "artifact metrics match recomputation" if file_agrees
        else "both engines agree with each other but not with the file -- the "
             "artifact is stale or was edited. Re-run the solver.",
    )
    if not file_agrees:
        return VerifyReport(gates=gates, passed=False)

    recomputed = build_metrics(spec, naive_dist)

    # ---- targets ----------------------------------------------------------
    actual_rtp = exact_rtp(recomputed)
    on_target = actual_rtp == spec.targets.rtp
    add(
        "rtp_exact",
        on_target,
        f"RTP is exactly {actual_rtp}" if on_target
        else f"RTP is {actual_rtp} ({float(actual_rtp):.10f}), target is "
             f"{spec.targets.rtp}. There is no tolerance band.",
    )

    actual_win_rate = exact_win_rate(recomputed)
    meets = actual_win_rate >= spec.targets.min_win_rate
    add(
        "min_win_rate",
        meets,
        f"win_rate {actual_win_rate} >= {spec.targets.min_win_rate}" if meets
        else f"win_rate {actual_win_rate} is below {spec.targets.min_win_rate}",
    )

    # ---- Layer 3: independent Monte Carlo ---------------------------------
    sim = montecarlo.simulate(spec, config.reels, spins=mc_spins, seed=mc_seed)
    sigma = montecarlo.sigma_deviation(spec, config.reels, sim, naive_dist)
    within = abs(sigma) < sigma_limit
    add(
        "monte_carlo",
        within,
        f"simulated RTP is {sigma:+.2f} sigma from exact "
        f"({mc_spins} spins, seed {mc_seed})",
    )

    # ---- warnings ---------------------------------------------------------
    never_loses = actual_win_rate == 1
    add(
        "win_rate_not_degenerate",
        not never_loses,
        "win_rate is below 1" if not never_loses
        else "win_rate is exactly 1: the player never comes up empty. Legal "
             "under the rules but commercially unusual.",
        severity="warn",
    )

    passed = all(g.passed for g in gates if g.severity == "fail")
    return VerifyReport(gates=gates, passed=passed)
```

- [ ] **Step 4：跑測試確認通過**

Run: `pytest tests/test_verify.py -v`
Expected: 全部 PASS。特別確認 `test_solver_block_is_non_authoritative` 的三個變體與 `test_stale_metrics_fail_with_recompute_message_not_engine_bug_message`。

- [ ] **Step 5：Commit**

```bash
git add src/slotmath/verify.py tests/test_verify.py
git commit -m "feat: add three-layer verification with gate contract"
```

---

## Task 9：cli.py 的 spec / verify / report

**Files:**
- Create: `src/slotmath/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_spec`、`ReelConfig`、`verify`
- Produces:
  - `main(argv: list[str] | None = None) -> int`
  - subcommands `spec`、`verify`、`report`（`solve`/`explore` 在 Task 11、12 加入）
  - exit code：`0` 全過、`1` 驗證不通過、`2` 執行錯誤

- [ ] **Step 1：寫失敗的測試**

`tests/test_cli.py`：

```python
import json
import pytest

from slotmath import naive
from slotmath.cli import main
from slotmath.metrics import build_metrics
from tests.fixtures import GOLDEN
from tests.test_naive import hw

MC = ["--mc-spins", "20000"]


def write_config(tmp_path, g, spec_path, **over):
    spec = hw()
    metrics = build_metrics(spec, naive.evaluate(spec, g.reels))
    data = {
        "spec": str(spec_path),
        "reels": g.reels,
        "metrics": json.loads(metrics.model_dump_json()),
    }
    data.update(over)
    path = tmp_path / "sol.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_spec_subcommand_validates_and_reports(capsys):
    assert main(["spec", "configs/homework-3x3.json"]) == 0
    out = capsys.readouterr().out
    assert "payout_unit_denominator" in out and "20" in out


def test_spec_subcommand_returns_2_on_missing_file(capsys):
    assert main(["spec", "configs/nope.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_spec_subcommand_returns_2_on_malformed_json(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["spec", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "invalid JSON" in err


def test_verify_returns_0_for_a_golden_config(tmp_path, capsys):
    cfg = write_config(tmp_path, GOLDEN[2], "configs/homework-3x3.json")
    assert main(["verify", str(cfg), *MC]) == 0
    assert "PASS" in capsys.readouterr().out


def test_verify_returns_1_for_a_failing_config(tmp_path, capsys):
    cfg = write_config(tmp_path, GOLDEN[2], "configs/homework-3x3.json")
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["metrics"]["spin_count"] += 1
    cfg.write_text(json.dumps(data), encoding="utf-8")
    assert main(["verify", str(cfg), *MC]) == 1


def test_verify_returns_2_when_referenced_spec_is_missing(tmp_path):
    cfg = write_config(tmp_path, GOLDEN[2], tmp_path / "missing.json")
    assert main(["verify", str(cfg), *MC]) == 2


def test_report_prints_payout_table(tmp_path, capsys):
    cfg = write_config(tmp_path, GOLDEN[2], "configs/homework-3x3.json")
    assert main(["report", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "19/20" in out
    assert "474" in out and "42" in out
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.cli'`

- [ ] **Step 3：實作 `src/slotmath/cli.py`**

```python
"""Command line entry point.

Exit codes are part of the contract, because the hook depends on them:
  0  everything passed
  1  verification did not pass
  2  the tool itself could not run (missing file, malformed JSON, bad schema)
Conflating 1 and 2 would make "the verifier crashed" read as "the solution
is wrong".
"""

from __future__ import annotations

import argparse
import json
from fractions import Fraction
from pathlib import Path

from pydantic import ValidationError

from slotmath.metrics import exact_rtp, exact_win_rate
from slotmath.spec import GameSpec, load_spec
from slotmath.verify import ReelConfig, verify


def _load_json(path: Path, stderr) -> dict:
    if not path.exists():
        print(f"{path}: not found", file=stderr)
        raise SystemExit(2)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}", file=stderr)
        raise SystemExit(2)


def _cmd_spec(args, out, err) -> int:
    data = _load_json(Path(args.path), err)
    try:
        spec = GameSpec.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid GameSpec\n{exc}", file=err)
        return 2
    print(f"name: {spec.name}", file=out)
    print(f"grid: {spec.grid.cols}x{spec.grid.rows}", file=out)
    print(f"symbols: {len(spec.symbols)}", file=out)
    print(f"patterns: {', '.join(p.name for p in spec.patterns)}", file=out)
    print(f"combine: {spec.combine}", file=out)
    print(f"target rtp: {spec.targets.rtp}", file=out)
    print(f"min_win_rate: {spec.targets.min_win_rate}", file=out)
    print(f"payout_unit_denominator: {spec.payout_unit_denominator()}", file=out)
    return 0


def _load_pair(args, err) -> tuple[GameSpec, ReelConfig]:
    data = _load_json(Path(args.path), err)
    try:
        config = ReelConfig.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid ReelConfig\n{exc}", file=err)
        raise SystemExit(2)
    spec_path = Path(config.spec)
    if not spec_path.exists():
        print(f"{config.spec}: referenced spec not found", file=err)
        raise SystemExit(2)
    return load_spec(spec_path), config


def _cmd_verify(args, out, err) -> int:
    spec, config = _load_pair(args, err)
    report = verify(spec, config, mc_spins=args.mc_spins, mc_seed=args.mc_seed)
    print(report.render(), file=out)
    return 0 if report.passed else 1


def _cmd_report(args, out, err) -> int:
    spec, config = _load_pair(args, err)
    m = config.metrics
    print(f"spec: {config.spec}", file=out)
    for i, reel in enumerate(config.reels):
        print(f"reel{i} (len {len(reel)}): {reel}", file=out)
    print(f"spin_count: {m.spin_count}", file=out)
    print(f"win_count: {m.win_count}  win_rate: {exact_win_rate(m)}", file=out)
    print(f"rtp: {exact_rtp(m)} = {m.rtp:.10f}", file=out)
    print(f"volatility: {m.volatility:.6f}  max_win: {m.max_win}", file=out)
    print("payout        combos   probability", file=out)
    for b in m.payout_distribution:
        prob = Fraction(b.combo_count, m.spin_count)
        print(
            f"{b.payout:>10}  {b.combo_count:>8}   {prob} = {float(prob):.6f}",
            file=out,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    import sys

    out, err = sys.stdout, sys.stderr
    parser = argparse.ArgumentParser(prog="slotmath")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("spec", help="validate and summarise a GameSpec")
    p.add_argument("path")
    p.set_defaults(func=_cmd_spec)

    p = sub.add_parser("verify", help="run all gates against a ReelConfig")
    p.add_argument("path")
    p.add_argument("--mc-spins", type=int, default=2_000_000)
    p.add_argument("--mc-seed", type=int, default=20260731)
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser("report", help="print a human readable payout table")
    p.add_argument("path")
    p.set_defaults(func=_cmd_report)

    args = parser.parse_args(argv)
    try:
        return args.func(args, out, err)
    except SystemExit as exc:
        return int(exc.code)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4：跑測試確認通過**

Run: `pytest tests/test_cli.py -v`
Expected: 全部 PASS

- [ ] **Step 5：Commit**

```bash
git add src/slotmath/cli.py tests/test_cli.py
git commit -m "feat: add CLI with spec/verify/report and contract exit codes"
```

---

## Task 10：diophantine.py signature 盈虧權重與 reel2 精確搜尋

固定前兩輪後，「RTP 恰為目標」化為一條齊次線性方程 `Σ n_s w_s = 0`，其中 `n_s` 是最後一輪貼上各 signature 的位置數。捲軸長度 `L_last = Σ n_s` 是解出來的，不是猜的。

**誠實記載的限制**：signature 直方圖並非任意可實現——一段長度 `k` 的 run 綁定產生 `k-2` 個三連 signature 加兩個邊界 signature。因此把方程的解轉回真實 strip 仍需有限搜尋。**這一步不是封閉解**，實作與註解都不得假裝它是。本 task 的做法是用 `w_s` 作為**精確的目標函數**（$O(|\text{Sig}|)$ 即可評分一個候選 strip，無需重新窮舉），在**保證可實現的** run-composition 空間中搜尋，兼得數學精確性與可實現性。

**Files:**
- Create: `src/slotmath/diophantine.py`
- Test: `tests/test_diophantine.py`

**Interfaces:**
- Consumes: `GameSpec`、`column_plans`/`reel_windows`/`window_signature`、`engine.evaluate`（測試用）
- Produces:
  - `signature_weights(spec, fixed_reels: Sequence[Sequence[int]]) -> dict[tuple[int | None, ...], int]`（回傳最後一欄各 signature 的 `w_s`）
  - `score(spec, weights, last_reel: Sequence[int]) -> int`（回傳 `Σ n_s w_s`；0 表示 RTP 恰為目標）
  - `has_mixed_signs(weights) -> bool`
  - `search_last_reel(spec, fixed_reels, min_len, max_len, seed, max_candidates) -> list[int] | None`

- [ ] **Step 1：寫失敗的測試**

`tests/test_diophantine.py`：

```python
from fractions import Fraction

import pytest

from slotmath import engine
from slotmath.diophantine import (
    has_mixed_signs,
    score,
    search_last_reel,
    signature_weights,
)
from slotmath.metrics import build_metrics, exact_rtp
from tests.fixtures import GOLDEN
from tests.test_naive import hw


def test_score_is_zero_exactly_when_rtp_is_on_target():
    spec = hw()
    for g in GOLDEN:
        weights = signature_weights(spec, g.reels[:-1])
        assert score(spec, weights, g.reels[-1]) == 0


def test_score_is_nonzero_for_an_off_target_reel():
    spec = hw()
    g = GOLDEN[2]
    weights = signature_weights(spec, g.reels[:-1])
    off = list(g.reels[-1]) + [4, 4, 4]
    assert score(spec, weights, off) != 0
    # and the engine agrees it is off target
    m = build_metrics(spec, engine.evaluate(spec, [*g.reels[:-1], off]))
    assert exact_rtp(m) != Fraction(19, 20)


def test_weights_have_both_signs_so_a_solution_exists():
    """There is always an almost-always-winning signature and an
    almost-never-winning one, so positives and negatives coexist."""
    spec = hw()
    weights = signature_weights(spec, GOLDEN[2].reels[:-1])
    assert has_mixed_signs(weights)


def test_all_same_signature_outweighs_a_dead_signature():
    spec = hw()
    weights = signature_weights(spec, GOLDEN[2].reels[:-1])
    all_twos = weights[(2, 2, 2, 2, 2)] if (2, 2, 2, 2, 2) in weights else None
    dead = weights.get((None, None, None, None, None))
    assert dead is not None and dead < 0
    if all_twos is not None:
        assert all_twos > dead


def test_search_finds_a_last_reel_that_lands_exactly_on_target():
    spec = hw()
    fixed = GOLDEN[2].reels[:-1]
    found = search_last_reel(
        spec, fixed, min_len=3, max_len=14, seed=20260731, max_candidates=40_000
    )
    assert found is not None
    m = build_metrics(spec, engine.evaluate(spec, [*fixed, found]))
    assert exact_rtp(m) == Fraction(19, 20)


def test_search_returns_none_instead_of_hanging_when_no_candidate_fits():
    spec = hw()
    # a single symbol reel pair leaves too little freedom within 3..4
    fixed = [[4] * 3, [4] * 3]
    assert search_last_reel(
        spec, fixed, min_len=3, max_len=4, seed=1, max_candidates=500
    ) is None
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_diophantine.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.diophantine'`

- [ ] **Step 3：實作 `src/slotmath/diophantine.py`**

```python
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
```

- [ ] **Step 4：跑測試確認通過**

Run: `pytest tests/test_diophantine.py -v`
Expected: 全部 PASS。若 `test_search_finds_a_last_reel_that_lands_exactly_on_target` 失敗，提高 `max_candidates` 前先確認 `score` 對 golden fixtures 回傳 0——那是正確性問題而非搜尋預算問題。

- [ ] **Step 5：Commit**

```bash
git add src/slotmath/diophantine.py tests/test_diophantine.py
git commit -m "feat: exact RTP via homogeneous linear Diophantine construction"
```

---

## Task 11：solver.py 四階段編排

**Files:**
- Create: `src/slotmath/solver.py`
- Modify: `src/slotmath/cli.py`（加入 `solve` subcommand）
- Test: `tests/test_solver.py`

**Interfaces:**
- Consumes: 全部前述模組
- Produces:
  - `SolverOptions(seed, min_len, max_len, prefer_length_mod, max_candidates, signature_budget, max_seeds)`（Pydantic model，皆有預設值；`prefer_length_mod: int | None = None` 表示由 spec 推導）
  - `required_units(spec, spin_count) -> int`
  - `congruence_ok(spec, spin_count, support: Iterable[int]) -> bool`
  - `derive_preferred_modulus(spec) -> int`
  - `candidate_length_tuples(spec, options) -> Iterator[tuple[int, ...]]`（優先產出使 `spin_count % modulus == 0` 者）
  - `solve(spec: GameSpec, options: SolverOptions) -> ReelConfig | None`

- [ ] **Step 1：寫失敗的測試**

`tests/test_solver.py`：

```python
from fractions import Fraction

import pytest

from slotmath.metrics import exact_rtp, exact_win_rate
from slotmath.solver import (
    SolverOptions,
    candidate_length_tuples,
    congruence_ok,
    derive_preferred_modulus,
    required_units,
    solve,
)
from slotmath.spec import load_spec
from slotmath.verify import verify
from tests.fixtures import GOLDEN
from tests.test_naive import hw


def test_required_units_is_nineteen_n():
    assert required_units(hw(), 720) == 19 * 720
    assert required_units(hw(), 1296) == 19 * 1296


def test_congruence_rejects_a_support_that_cannot_reach_the_target():
    """N=1296: T = 19*1296 = 24624. gcd{5,20,100} = 5 and 24624 % 5 = 4, so no
    arrangement of those payouts can total T. Rejected in O(1)."""
    assert not congruence_ok(hw(), 1296, {0, 5, 20, 100})


def test_congruence_accepts_every_golden_support():
    spec = hw()
    for g in GOLDEN:
        assert congruence_ok(spec, g.spin_count, set(g.distribution))


def test_support_without_symbol_one_requires_five_to_divide_n():
    """Every payout except symbol 1's 11 units is a multiple of 5. Drop symbol 1
    and N must be divisible by 5. This is why stage 0 prefers those lengths."""
    spec = hw()
    coarse = {0, 20, 100}
    assert congruence_ok(spec, 720, coarse)        # 5 | 720
    assert not congruence_ok(spec, 1296, coarse)   # 5 does not divide 1296


def test_congruence_is_vacuous_when_the_support_has_no_common_factor():
    """Support including 11 has gcd 1, so there is no O(1) obstruction."""
    assert congruence_ok(hw(), 1296, {0, 5, 11, 20, 100})


def test_preferred_modulus_is_derived_not_hardcoded():
    assert derive_preferred_modulus(hw()) == 5


def test_candidate_lengths_put_multiples_of_five_first():
    spec = hw()
    options = SolverOptions(min_len=3, max_len=6, prefer_length_mod=5)
    first_ten = [t for _, t in zip(range(10), candidate_length_tuples(spec, options))]
    products = [t[0] * t[1] * t[2] for t in first_ten]
    assert all(p % 5 == 0 for p in products)


def test_candidate_lengths_respect_bounds_and_row_minimum():
    spec = hw()
    options = SolverOptions(min_len=3, max_len=5)
    for _, t in zip(range(50), candidate_length_tuples(spec, options)):
        assert len(t) == 3
        assert all(3 <= n <= 5 for n in t)


def test_solve_produces_a_config_passing_every_gate():
    spec = load_spec("configs/homework-3x3.json")
    config = solve(spec, SolverOptions(seed=20260731))
    assert config is not None, "solver found nothing"
    report = verify(spec, config, mc_spins=50_000)
    assert report.passed, report.render()
    assert exact_rtp(config.metrics) == Fraction(19, 20)
    assert exact_win_rate(config.metrics) >= Fraction(11, 20)


def test_solve_is_reproducible_for_a_fixed_seed():
    spec = load_spec("configs/homework-3x3.json")
    a = solve(spec, SolverOptions(seed=99))
    b = solve(spec, SolverOptions(seed=99))
    assert a is not None and a.reels == b.reels


def test_solve_records_the_command_that_reproduces_it():
    spec = load_spec("configs/homework-3x3.json")
    config = solve(spec, SolverOptions(seed=1234))
    assert config is not None
    assert "1234" in config.solver["command"]
    assert config.solver["seed"] == 1234


def test_solve_returns_none_rather_than_hanging_on_an_impossible_target():
    spec = hw(targets={"rtp": 1000, "min_win_rate": 0.55})
    assert solve(spec, SolverOptions(seed=1, max_seeds=2, max_candidates=200)) is None
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_solver.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.solver'`

- [ ] **Step 3：實作 `src/slotmath/solver.py`**

```python
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
from typing import Iterable, Iterator, Sequence

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
            if not congruence_ok(spec, metrics.spin_count, distribution.keys()):
                continue
            if exact_rtp(metrics) != spec.targets.rtp:
                continue
            if exact_win_rate(metrics) < spec.targets.min_win_rate:
                continue

            return ReelConfig(
                spec=spec.name,
                reels=[list(r) for r in reels],
                metrics=metrics,
                solver={
                    "version": VERSION,
                    "seed": options.seed,
                    "command": (
                        f"slotmath solve configs/{spec.name}.json "
                        f"--seed {options.seed}"
                    ),
                },
            )
    return None
```

- [ ] **Step 4：跑測試確認失敗處並修正**

Run: `pytest tests/test_solver.py -v`

`test_solve_produces_a_config_passing_every_gate` 中 `verify` 會讀 `config.spec` 當路徑，但 `solve` 填的是 `spec.name`。修正：`solve` 改填 `f"configs/{spec.name}.json"`，使 artifact 內的 `spec` 一律是可解析的路徑。

- [ ] **Step 5：修正 `solve` 的 spec 欄位**

```python
            return ReelConfig(
                spec=f"configs/{spec.name}.json",
                reels=[list(r) for r in reels],
```

- [ ] **Step 6：在 `cli.py` 加入 `solve` subcommand**

在 `main()` 的 subparser 區塊加入：

```python
    p = sub.add_parser("solve", help="search for a reel config meeting the targets")
    p.add_argument("path")
    p.add_argument("--seed", type=int, default=20260731)
    p.add_argument("--min-len", type=int, default=3)
    p.add_argument("--max-len", type=int, default=16)
    p.add_argument("--out", default=None)
    p.set_defaults(func=_cmd_solve)
```

並加入：

```python
def _cmd_solve(args, out, err) -> int:
    from slotmath.solver import SolverOptions, solve

    data = _load_json(Path(args.path), err)
    try:
        spec = GameSpec.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid GameSpec\n{exc}", file=err)
        return 2

    config = solve(
        spec,
        SolverOptions(seed=args.seed, min_len=args.min_len, max_len=args.max_len),
    )
    if config is None:
        print("no configuration found within the search budget", file=err)
        return 1

    payload = json.loads(config.model_dump_json())
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.out}", file=out)
    else:
        print(json.dumps(payload, indent=2), file=out)
    return 0
```

- [ ] **Step 7：跑全部測試並產生實際解**

Run: `pytest -q`
Expected: 全綠

Run: `slotmath solve configs/homework-3x3.json --seed 20260731 --out solutions/homework-3x3.json`
Run: `slotmath verify solutions/homework-3x3.json`
Expected: exit 0，`rtp_exact` gate 顯示 `RTP is exactly 19/20`

- [ ] **Step 8：Commit**

```bash
git add src/slotmath/solver.py src/slotmath/cli.py tests/test_solver.py solutions/homework-3x3.json
git commit -m "feat: add four-stage solver and solve the homework acceptance case"
```

---

## Task 12：portfolio.py 多樣性與 explore

**Files:**
- Create: `src/slotmath/portfolio.py`
- Modify: `src/slotmath/cli.py`（加入 `explore`）
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `Metrics`、`ReelConfig`、`solve`
- Produces:
  - `features(metrics: Metrics) -> tuple[float, float, float, float, float]`（依序為 `win_rate`、`volatility`、`log(1+max_win)`、`entropy(payout_distribution)`、`spin_count`）
  - `normalise(vectors) -> list[tuple[float, ...]]`
  - `min_distance(candidate, existing) -> float`
  - `Portfolio(entries: list[ReelConfig], calibration: dict | None)`（Pydantic model，可存讀 JSON）
  - `should_admit(portfolio, candidate, distance_threshold) -> bool`
  - `calibrate(distances: list[float]) -> float`

- [ ] **Step 1：寫失敗的測試**

`tests/test_portfolio.py`：

```python
import math

import pytest

from slotmath import naive
from slotmath.metrics import build_metrics
from slotmath.portfolio import (
    Portfolio,
    calibrate,
    entropy_of,
    features,
    min_distance,
    normalise,
    should_admit,
)
from tests.fixtures import GOLDEN
from tests.test_naive import hw


def metrics_for(g):
    spec = hw()
    return build_metrics(spec, naive.evaluate(spec, g.reels))


def test_features_has_five_dimensions_in_documented_order():
    m = metrics_for(GOLDEN[2])
    f = features(m)
    assert len(f) == 5
    assert f[0] == pytest.approx(43 / 60)                 # win_rate
    assert f[1] == pytest.approx(m.volatility)            # volatility
    assert f[2] == pytest.approx(math.log(1 + 5))         # log(1 + max_win)
    assert f[4] == 720                                    # spin_count


def test_entropy_is_zero_when_every_spin_pays_the_same():
    assert entropy_of({100: 50}) == 0.0


def test_entropy_grows_with_more_distinct_payouts():
    two = entropy_of({0: 50, 20: 50})
    four = entropy_of({0: 25, 20: 25, 60: 25, 100: 25})
    assert four > two > 0


def test_entropy_separates_configs_that_share_win_rate_and_volatility():
    """The reason entropy is in the vector at all: fixture C has only three
    distinct payouts, and a five-payout config with coincidentally equal
    win_rate and volatility is a different game to the player."""
    coarse = entropy_of({0: 204, 20: 474, 100: 42})
    rich = entropy_of({0: 204, 5: 118, 11: 118, 20: 238, 100: 42})
    assert rich > coarse


def test_normalise_maps_each_dimension_into_zero_one():
    vectors = [features(metrics_for(g)) for g in GOLDEN]
    normalised = normalise(vectors)
    for dim in range(5):
        column = [v[dim] for v in normalised]
        assert min(column) == pytest.approx(0.0)
        assert max(column) == pytest.approx(1.0)


def test_identical_vectors_have_zero_distance():
    v = (0.5,) * 5
    assert min_distance(v, [v]) == pytest.approx(0.0)


def test_min_distance_against_empty_set_is_infinite():
    assert min_distance((0.5,) * 5, []) == float("inf")


def test_should_admit_rejects_a_near_duplicate():
    p = Portfolio(entries=[], calibration=None)
    a, b, c = GOLDEN
    # admitting the very same config twice must fail the second time
    assert should_admit(p, metrics_for(c), 0.25)
    p.entries.append(_stub_config(c))
    assert not should_admit(p, metrics_for(c), 0.25)


def test_should_admit_accepts_a_clearly_different_config():
    p = Portfolio(entries=[_stub_config(GOLDEN[2])], calibration=None)
    # fixture A has win_rate 1 and a completely different payout structure
    assert should_admit(p, metrics_for(GOLDEN[0]), 0.25)


def test_calibrate_returns_a_threshold_inside_the_observed_range():
    distances = [0.1, 0.4, 0.6, 0.9]
    d = calibrate(distances)
    assert 0.0 < d < 0.9


def test_portfolio_round_trips_through_json(tmp_path):
    p = Portfolio(entries=[_stub_config(GOLDEN[2])], calibration={"distance": 0.3})
    path = tmp_path / "portfolio.json"
    path.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    back = Portfolio.model_validate_json(path.read_text(encoding="utf-8"))
    assert back.entries[0].reels == p.entries[0].reels
    assert back.calibration == {"distance": 0.3}
```

在 `tests/test_portfolio.py` 頂端加入 helper：

```python
from slotmath.verify import ReelConfig


def _stub_config(g):
    return ReelConfig(
        spec="configs/homework-3x3.json",
        reels=g.reels,
        metrics=metrics_for(g),
    )
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_portfolio.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'slotmath.portfolio'`

- [ ] **Step 3：實作 `src/slotmath/portfolio.py`**

```python
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
```

- [ ] **Step 4：在 `cli.py` 加入 `explore` subcommand**

subparser：

```python
    p = sub.add_parser("explore", help="collect diverse valid configs")
    p.add_argument("path")
    p.add_argument("--portfolio", default="solutions/portfolio.json")
    p.add_argument("--seed", type=int, default=20260731)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--distance", type=float, default=None)
    p.set_defaults(func=_cmd_explore)
```

實作：

```python
def _cmd_explore(args, out, err) -> int:
    from slotmath.portfolio import Portfolio, features, min_distance, normalise, should_admit
    from slotmath.solver import SolverOptions, solve

    data = _load_json(Path(args.path), err)
    try:
        spec = GameSpec.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid GameSpec\n{exc}", file=err)
        return 2

    store = Path(args.portfolio)
    portfolio = (
        Portfolio.model_validate_json(store.read_text(encoding="utf-8"))
        if store.exists()
        else Portfolio(entries=[], calibration=None)
    )
    threshold = args.distance or (portfolio.calibration or {}).get("distance", 0.25)

    admitted = 0
    for round_index in range(args.rounds):
        config = solve(spec, SolverOptions(seed=args.seed + round_index))
        if config is None:
            print(f"round {round_index}: no config found", file=out)
            continue
        if should_admit(portfolio, config.metrics, threshold):
            portfolio.entries.append(config)
            admitted += 1
            print(f"round {round_index}: admitted (portfolio now {len(portfolio.entries)})", file=out)
        else:
            print(f"round {round_index}: rejected as too similar", file=out)

    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(portfolio.model_dump_json(indent=2), encoding="utf-8")
    print(f"admitted {admitted} of {args.rounds}; wrote {store}", file=out)
    return 0
```

- [ ] **Step 5：跑測試確認通過**

Run: `pytest tests/test_portfolio.py -v`
Expected: 全部 PASS

Run: `slotmath explore configs/homework-3x3.json --rounds 3 --seed 500`
Expected: exit 0，`solutions/portfolio.json` 產生

- [ ] **Step 6：Commit**

```bash
git add src/slotmath/portfolio.py src/slotmath/cli.py tests/test_portfolio.py
git commit -m "feat: add portfolio diversity metric and explore subcommand"
```

---

## Task 13：PostToolUse hook

**Files:**
- Create: `scripts/hooks/verify_on_write.py`
- Create: `.claude/settings.json`
- Test: `tests/test_hook.py`

**Interfaces:**
- Consumes: `ReelConfig`、`verify`、`load_spec`
- Produces: `scripts/hooks/verify_on_write.py` 的 `main(stdin_text: str) -> tuple[int, str]`（回傳 `(exit_code, stderr_text)`，讓測試不必開子行程）

- [ ] **Step 1：寫失敗的測試**

`tests/test_hook.py`：

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("scripts/hooks").resolve()))
import verify_on_write  # noqa: E402

from slotmath import naive
from slotmath.metrics import build_metrics
from tests.fixtures import GOLDEN
from tests.test_naive import hw


def payload(path):
    return json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(path)}})


def write_solution(tmp_path, g, **mutate):
    spec = hw()
    metrics = build_metrics(spec, naive.evaluate(spec, g.reels))
    data = {
        "spec": "configs/homework-3x3.json",
        "reels": g.reels,
        "metrics": json.loads(metrics.model_dump_json()),
    }
    for key, value in mutate.items():
        data["metrics"][key] = value
    target = tmp_path / "solutions"
    target.mkdir(exist_ok=True)
    path = target / "s.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_unrelated_path_exits_zero_silently():
    code, err = verify_on_write.main(payload("src/slotmath/engine.py"))
    assert code == 0 and err == ""


def test_unrelated_json_outside_watched_dirs_exits_zero():
    code, err = verify_on_write.main(payload("notes/scratch.json"))
    assert code == 0 and err == ""


def test_missing_file_path_in_payload_exits_zero():
    code, err = verify_on_write.main(json.dumps({"tool_name": "Write", "tool_input": {}}))
    assert code == 0 and err == ""


def test_valid_gamespec_exits_zero(capsys):
    code, err = verify_on_write.main(payload("configs/homework-3x3.json"))
    assert code == 0, err


def test_good_solution_exits_zero(tmp_path):
    path = write_solution(tmp_path, GOLDEN[2])
    code, err = verify_on_write.main(payload(path))
    assert code == 0, err


def test_bad_solution_exits_two_with_readable_report(tmp_path):
    path = write_solution(tmp_path, GOLDEN[2], spin_count=999)
    code, err = verify_on_write.main(payload(path))
    assert code == 2
    assert "file_consistency" in err
    assert "Traceback" not in err


def test_malformed_json_gives_a_message_not_a_traceback(tmp_path):
    target = tmp_path / "solutions"
    target.mkdir()
    path = target / "s.json"
    path.write_text("{ broken", encoding="utf-8")
    code, err = verify_on_write.main(payload(path))
    assert code == 2
    assert "invalid JSON" in err
    assert "Traceback" not in err


def test_hook_never_modifies_the_file(tmp_path):
    path = write_solution(tmp_path, GOLDEN[2], spin_count=999)
    before = path.read_bytes()
    verify_on_write.main(payload(path))
    assert path.read_bytes() == before
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_hook.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'verify_on_write'`

- [ ] **Step 3：實作 `scripts/hooks/verify_on_write.py`**

```python
#!/usr/bin/env python3
"""PostToolUse hook: verify solution artifacts the moment they are written.

Exit 2 hands stderr back to Claude, so a broken artifact is reported to the
agent that just wrote it and gets fixed without a human stepping in.

Two rules that must not be relaxed:

1. This hook never edits files. A hook that rewrites what the agent just
   wrote races against the agent's own edits and produces bugs that are
   almost impossible to trace. It only reports.
2. Malformed JSON produces a human-readable message, never a traceback.

The fast path -- a write to anything we do not watch -- must stay cheap, so
the path test happens before any heavy import.
"""

from __future__ import annotations

import json
import sys

WATCHED_PREFIXES = ("solutions/", "configs/")
HOOK_MC_SPINS = 100_000


def _is_watched(path: str) -> bool:
    if not path.endswith(".json"):
        return False
    normalised = path.replace("\\", "/")
    return any(f"/{p}" in f"/{normalised}" for p in WATCHED_PREFIXES)


def main(stdin_text: str) -> tuple[int, str]:
    try:
        event = json.loads(stdin_text)
    except json.JSONDecodeError:
        return 0, ""

    path = (event.get("tool_input") or {}).get("file_path")
    if not path or not _is_watched(str(path)):
        return 0, ""

    from pathlib import Path

    target = Path(path)
    if not target.exists():
        return 0, ""

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 2, f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}\n"

    from pydantic import ValidationError

    from slotmath.spec import GameSpec, load_spec
    from slotmath.verify import ReelConfig, verify

    # A GameSpec has "grid"; a ReelConfig has "reels".
    if "grid" in data and "reels" not in data:
        try:
            GameSpec.model_validate(data)
        except ValidationError as exc:
            return 2, f"{path}: invalid GameSpec\n{exc}\n"
        return 0, ""

    try:
        config = ReelConfig.model_validate(data)
    except ValidationError as exc:
        return 2, f"{path}: invalid ReelConfig\n{exc}\n"

    spec_path = Path(config.spec)
    if not spec_path.exists():
        return 2, f"{path}: referenced spec {config.spec} not found\n"

    report = verify(load_spec(spec_path), config, mc_spins=HOOK_MC_SPINS)
    if report.passed:
        return 0, ""
    return 2, f"{path} failed verification:\n{report.render()}\n"


if __name__ == "__main__":
    code, message = main(sys.stdin.read())
    if message:
        sys.stderr.write(message)
    raise SystemExit(code)
```

- [ ] **Step 4：建立 `.claude/settings.json`**

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 scripts/hooks/verify_on_write.py"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 5：跑測試確認通過**

Run: `pytest tests/test_hook.py -v`
Expected: 全部 PASS

- [ ] **Step 6：手動驗證 hook 真的會擋**

Run: `echo '{"tool_name":"Write","tool_input":{"file_path":"solutions/homework-3x3.json"}}' | python3 scripts/hooks/verify_on_write.py; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 7：Commit**

```bash
git add scripts/hooks/verify_on_write.py .claude/settings.json tests/test_hook.py
git commit -m "feat: verify solution artifacts on write via PostToolUse hook"
```

---

## Task 14：四支 skill

**Files:**
- Create: `.claude/skills/slot-math-model/SKILL.md`
- Create: `.claude/skills/reel-strip-solver/SKILL.md`
- Create: `.claude/skills/slot-config-verifier/SKILL.md`
- Create: `.claude/skills/slot-solution-explorer/SKILL.md`
- Create: `.claude/skills/reel-strip-solver/references/math-notes.md`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: 全部 CLI subcommands
- Produces: 四份 `SKILL.md`，各含 `name`/`description` frontmatter、工作流、可執行命令、輸出契約、執行規則

- [ ] **Step 1：寫失敗的測試**

`tests/test_skills.py`：

```python
from pathlib import Path

import pytest

SKILLS = [
    "slot-math-model",
    "reel-strip-solver",
    "slot-config-verifier",
    "slot-solution-explorer",
]


@pytest.mark.parametrize("name", SKILLS)
def test_skill_file_exists(name):
    assert Path(f".claude/skills/{name}/SKILL.md").is_file()


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_frontmatter_with_matching_name(name):
    text = Path(f".claude/skills/{name}/SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    header = text.split("---", 2)[1]
    assert f"name: {name}" in header
    assert "description:" in header


@pytest.mark.parametrize("name", SKILLS)
def test_skill_documents_a_runnable_command(name):
    text = Path(f".claude/skills/{name}/SKILL.md").read_text(encoding="utf-8")
    assert "slotmath " in text


@pytest.mark.parametrize("name", SKILLS)
def test_skill_states_an_output_contract(name):
    text = Path(f".claude/skills/{name}/SKILL.md").read_text(encoding="utf-8")
    assert "Output Contract" in text


def test_no_skill_uses_the_banned_vocabulary():
    """The project renamed these deliberately; drift here causes real bugs."""
    for name in SKILLS:
        text = Path(f".claude/skills/{name}/SKILL.md").read_text(encoding="utf-8")
        assert "hit_rate" not in text
        assert "pattern_bonus" not in text


def test_verifier_skill_states_the_exit_code_contract():
    text = Path(".claude/skills/slot-config-verifier/SKILL.md").read_text(encoding="utf-8")
    for code in ("0", "1", "2"):
        assert code in text
    assert "exit" in text.lower()


def test_solver_skill_records_the_diophantine_limitation():
    text = Path(".claude/skills/reel-strip-solver/SKILL.md").read_text(encoding="utf-8")
    assert "not a closed form" in text or "finite search" in text
```

- [ ] **Step 2：跑測試確認失敗**

Run: `pytest tests/test_skills.py -v`
Expected: FAIL，四個 `test_skill_file_exists` 皆 AssertionError

- [ ] **Step 3：建立 `.claude/skills/slot-math-model/SKILL.md`**

```markdown
---
name: slot-math-model
description: Turn slot game rules stated in prose into a validated GameSpec, and report the structural facts a solver can exploit. Use when starting from a rules document, when adding or changing winning patterns, when the paytable changes, or when you need to know whether a target RTP is reachable at all.
---

# Slot Math Model

Use this skill to get from "here are the rules" to a machine-checked model,
before anyone tries to solve anything.

## Workflow

1. Extract the model into a `GameSpec` JSON.
- `grid`, `symbols` (symbol multipliers), `patterns` (cell masks with
  `pattern_multiplier`, default 1), `targets` (`rtp`, `min_win_rate`).
- Cells are `[col, row]` with the origin top-left. `"all"` is shorthand for
  every cell.
- `combine` defaults to `"max"` (only the single highest-paying pattern pays).
  State it explicitly only when the rules say payouts add up.
- Numbers may be written as plain floats. They are coerced to exact
  rationals internally, so `0.55` becomes `11/20`, not a binary expansion.

2. Validate it.

```bash
slotmath spec configs/<name>.json
```

Exit 2 means the model is not well formed. Fix it before going further.

3. Report the structural facts.
- Does every pattern share a cell? If so, simultaneous wins must always be
  the same symbol, which collapses the multi-win case. Do not assume this
  holds for arbitrary pattern sets -- disjoint patterns can win on different
  symbols.
- `RTP = win_rate x E[payout | win]`. Since `win_rate <= 1`, the target RTP
  forces a floor on the average win. Report that floor: it is usually the
  binding constraint and it rules out intuitive designs.
- Compute the congruence obstruction. With `payout_unit_denominator = D`,
  every payout is an integer number of `1/D`. If all reachable payout unit
  values share a common factor `g` but the required total does not, that
  configuration can never hit the target exactly, regardless of search
  effort. Report the modulus and which symbol breaks it.

## Output Contract

Return:

1. `GameSpec`: the JSON, written to `configs/<name>.json`.
2. `Structural Facts`: shared cells, the average-win floor, the congruence
   modulus and which symbol provides the fine adjustment.
3. `Reachability`: whether the target looks attainable, with the reasoning.
4. `Assumptions`: anything the prose rules left unstated, marked explicitly.

## Execution Rules

- Never widen a rule to make the math easier. If the rules are ambiguous,
  state both readings and ask.
- Use `win_rate` and `min_win_rate`. Never `hit_rate`.
- Use `pattern_multiplier`. Never `mult` or `pattern_bonus` -- the value is
  multiplicative, and calling it a bonus invites an additive bug.
```

- [ ] **Step 4：建立 `.claude/skills/reel-strip-solver/SKILL.md`**

```markdown
---
name: reel-strip-solver
description: Search for a reel configuration whose RTP hits the target exactly and whose win rate clears the minimum. Use after a GameSpec exists, when a target changes, when the current solution fails a gate, or when you need a reproducible solve command for a report.
---

# Reel Strip Solver

Use this skill to orchestrate the solve. The convergence itself is
deterministic computation -- your job is choosing what to try and knowing
when to stop, not iterating toward the number by hand.

## Workflow

1. Confirm the model first.

```bash
slotmath spec configs/<name>.json
```

2. Solve.

```bash
slotmath solve configs/<name>.json --seed <seed> --out solutions/<name>.json
```

Exit 1 means nothing was found inside the budget. That is a search-budget
result, not a proof of impossibility. Before widening the budget, check the
congruence obstruction from `slot-math-model` -- if it is violated, no
budget will help.

3. Verify, always.

```bash
slotmath verify solutions/<name>.json
```

Never report a solution you have not verified. The solver and the verifier
are separate on purpose.

4. Read the payout structure before calling it good.

```bash
slotmath report solutions/<name>.json
```

An exactly-on-target RTP can still be a bad game: check whether the player
ever loses, whether one payout dominates, and whether `max_win` is sane.

## How the solve works

- **Stage 0** picks reel lengths actively rather than only pruning. The
  congruence requirement moves with `N`, so lengths making `N` divisible by
  the modulus are tried first -- that makes the awkward symbol unnecessary
  and removes the obstruction outright.
- **Stage 1** seeds the fixed reels from runs of identical symbols. Only runs
  can form a 2x2 block at all.
- **Stage 3** fixes every reel but the last and solves a homogeneous linear
  equation `sum_s n_s w_s = 0` over signature counts. The last reel's length
  falls out of the equation instead of being guessed. A solution always
  exists when the weights have both signs, which they do.
- **Limitation, stated plainly:** a signature histogram is not freely
  realizable. A run of `k` identical symbols forces `k-2` triple signatures
  plus two boundary signatures, so converting a solution back into a real
  cyclic strip still requires a finite search. This is not a closed form.
  Do not describe it as one.

## Output Contract

Return:

1. `Solution`: the reels and the path to `solutions/<name>.json`.
2. `Metrics`: `spin_count`, `win_count`, `win_rate`, exact RTP as a fraction,
   `volatility`, `max_win`, and the payout distribution.
3. `Verification`: the gate report, copied not summarised.
4. `Reproduction`: the exact command and seed.
5. `Residual Risks`: gates that only warn, and anything the search skipped.

## Execution Rules

- RTP is judged by exact fraction equality. There is no tolerance band. Never
  report `0.95004` as meeting a 0.95 target.
- If a solve fails, report it as a failure with the budget used. Do not
  quietly relax `min_win_rate` or the target.
- Keep the seed in the report. A solution nobody can reproduce is not a
  deliverable.

## References

- `references/math-notes.md`: the congruence invariant and the linear form.
```

- [ ] **Step 5：建立 `.claude/skills/reel-strip-solver/references/math-notes.md`**

```markdown
# Math Notes

## Congruence invariant

Write payouts in units of `1/D` where `D = payout_unit_denominator`. For the
homework paytable `D = 20` and the reachable unit values are

```
2x2 wins   : 5, 11, 20, 60, 100
full board : 25, 55, 100, 300, 500
```

Every value is a multiple of 5 except symbol 1's `11`. So with
`n1` = the number of stop combinations whose top payout is exactly `11` units,

```
sum(units) = 11 * n1 = n1  (mod 5)
```

and hitting `RTP = 19/20` requires `sum(units) = 19N`, giving

```
n1 = 4N  (mod 5)
```

**The right-hand side moves with N.** Choose `5 | N` and it becomes 0, so
`n1 = 0` is legal and symbol 1 is not needed at all. This is why stage 0
prefers those lengths instead of merely pruning.

General form: let `g` be the gcd of the payout unit values actually present.
The necessary condition is `rtp * D * N = 0 (mod g)`.

## The linear form

Fix every reel but the last. For each signature `s` the last column could
show, let `v_s` be the total payout in `1/D` units summed over every stop
combination of the fixed reels, and

```
w_s = rtp_den * v_s - rtp_num * D * prod(L_fixed)
```

Then RTP is exactly on target iff `sum_s n_s * w_s = 0`, where `n_s` counts
positions in the last reel carrying signature `s`. The last reel's length is
`sum_s n_s`.

Existence: pick `w_p > 0` and `w_q < 0`, set `n_p = |w_q|` and `n_q = w_p`.
Both signs always occur because there is always an almost-always-winning
signature and an almost-never-winning one.

Observed weights for one fixed pair of reels:

```
(2,2,2)  w = +579
(2,.,.)  w = -721
(0,0,0)  w = -1856
(.,0,.)  w = -1926
(4,4,4)  w = -2021
```

## Industry context

Lengthening reels to buy finer probability granularity is the virtual reels
technique, from Inge Telnaes, US Patent 4,448,419 (1984), later held by IGT.
The construction above is an exact-target version of the same idea. Computing
RTP and hit frequency over the full cycle corresponds to a PAR sheet
(Probability Accounting Report). Unequal reel lengths are normal in real
machines -- Lobstermania runs 47/46/48/50/50.

No dedicated literature was found for this specific combinatorial problem
(given a paytable and pattern set, find a reel configuration whose RTP equals
a target exactly). Recorded as not found, not as nonexistent.
```

- [ ] **Step 6：建立 `.claude/skills/slot-config-verifier/SKILL.md`**

```markdown
---
name: slot-config-verifier
description: Independently verify a reel configuration against its GameSpec and produce a sign-off. Use before reporting any solution, after editing a solution or spec by hand, when a gate report needs interpreting, or when a solution from another session needs re-checking.
---

# Slot Config Verifier

Use this skill to decide whether a configuration is actually correct. Never
take the solver's word for it.

## Workflow

1. Run every gate.

```bash
slotmath verify solutions/<name>.json
```

For a thorough pass, widen the simulation:

```bash
slotmath verify solutions/<name>.json --mc-spins 20000000
```

2. Read the exit code as a contract.

| exit | meaning | what to do |
| --- | --- | --- |
| 0 | every hard gate passed | proceed; still read the warnings |
| 1 | verification did not pass | fix the configuration or the spec |
| 2 | the verifier could not run | fix the input; this says nothing about the solution |

Never treat exit 2 as "the solution is wrong".

3. Interpret a layer 2 failure correctly. The two cases need opposite
   responses:

- `engine_matches_naive` failed: **the program has a bug.** The two
  evaluators disagree with each other. Stop and debug the code. Do not touch
  the artifact.
- `file_matches_recompute` failed: **the artifact is stale or was edited.**
  The evaluators agree with each other but not with the file. Re-run the
  solver.

4. Do not skip the warnings. A configuration can pass every hard gate and
   still be a bad game -- `win_rate = 1` means the player never comes up
   empty, which is legal under the rules and commercially strange.

## What the three layers cover

- **Layer 1** checks the artifact against itself using only the integer
  counts. Zero computation, catches truncated and hand-edited files.
- **Layer 2** recomputes with two independent evaluators and requires exact
  fraction agreement with each other and with the file.
- **Layer 3** simulates along a path that shares no abstraction with the
  other two. It exists because layers 1 and 2 rest on the same assumption --
  that the spec was translated into matching logic correctly. If that
  translation is wrong, both are wrong together and agree with each other.
  The seed is fixed, so the check is deterministic and safe as a hard gate.

## Output Contract

Return:

1. `Gate Report`: every gate with its verdict, copied verbatim.
2. `Verdict`: pass or fail, plus the exit code.
3. `Warnings`: gates that warn, with what they imply for the game.
4. `Diagnosis`: for any failure, which layer failed and therefore whether the
   bug is in the code or in the artifact.

## Execution Rules

- The `solver` block in a configuration is metadata and is not authoritative.
  Ignore it entirely. Never let a version string or a claim inside it change
  how you verify.
- RTP is checked by exact fraction equality. Never accept a near miss.
- Report failures as failures. Do not restate a failing run as "close".
```

- [ ] **Step 7：建立 `.claude/skills/slot-solution-explorer/SKILL.md`**

```markdown
---
name: slot-solution-explorer
description: Collect several valid reel configurations that feel different to play, not just one. Use when you want a portfolio of options to choose between, when comparing low-volatility against high-volatility designs at the same RTP, or when driven by /loop to sweep the design space.
---

# Slot Solution Explorer

Use this skill to build a portfolio of configurations that all satisfy the
targets but differ as games. This is the one part of the workflow where a
loop is justified -- and it is not for approaching the RTP target, which is
deterministic computation inside the solver.

## Workflow

Each round:

1. Read the current portfolio.

```bash
cat solutions/portfolio.json
```

2. **Choose where to explore next.** Look at which region of the feature
   space is empty and bias the solver toward it. This step is the reason an
   agent is in this loop at all: reading "I already have three high-win-rate
   low-volatility configs, so go find a high-volatility one" is something
   random seeding cannot do.

3. Solve and admit.

```bash
slotmath explore configs/<name>.json --rounds 1 --seed <new seed>
```

A candidate is admitted only if it passes every gate **and** its normalised
distance from every existing entry is at least the threshold.

4. Record what you tried, including the directions that produced nothing, so
   later rounds do not walk into the same wall.

5. Stop when the portfolio is full, or after K consecutive rounds with no new
   entry. Use consecutive-dry-rounds rather than a fixed round count -- the
   size of the feasible region is not known in advance.

## Diversity

The feature vector, all of it derived from metrics already computed:

```
win_rate, volatility, log(1 + max_win), entropy(payout_distribution), spin_count
```

`entropy` is in there deliberately. Without it, a three-payout game and a
five-payout game with coincidentally matching win rate and volatility count
as duplicates -- and they are different games to the player.

## Calibration

The distance threshold starts as a guess. On the first run, collect roughly
ten configurations with no diversity constraint, measure how far apart the
feature space actually spreads, and derive the threshold from that. Store it
in the portfolio's `calibration` field so later rounds are consistent.

## Output Contract

Return:

1. `Portfolio`: every admitted configuration with its metrics.
2. `Coverage`: which regions of the feature space are populated and which are
   empty.
3. `Rejected`: candidates turned away and why -- gate failure or too similar.
4. `Calibration`: the threshold in use and how it was derived.
5. `Stop Reason`: portfolio full, or K dry rounds.

## Execution Rules

- Verify every candidate before admitting it. A diverse portfolio of wrong
  answers is worthless.
- Never loosen the targets to increase diversity. Diversity is subordinate to
  correctness.
- If the loop produces nothing for K rounds, report that. Do not keep
  spinning.
```

- [ ] **Step 8：跑測試確認通過**

Run: `pytest tests/test_skills.py -v`
Expected: 全部 PASS

- [ ] **Step 9：跑全部測試**

Run: `pytest -q`
Expected: 全綠

- [ ] **Step 10：Commit**

```bash
git add .claude/skills tests/test_skills.py
git commit -m "feat: add four slot math skills wiring the toolkit to the agent"
```

---

## Self-Review

**1. Spec coverage**

| spec 章節 | 對應 task |
| --- | --- |
| §2 已定案決定 | Global Constraints + 各 task |
| §3.1 模型 | Task 2 |
| §3.2 結構性事實 | Task 3（不寫成硬假設）、slot-math-model skill |
| §3.3 RTP/win_rate 耦合 | slot-math-model skill 的 Structural Facts |
| §4.1 golden fixtures | Task 6 |
| §4.2 mod 5 不變量 | Task 6（property test）、Task 11（`congruence_ok`）、math-notes.md |
| §4.3 fixture A 不可刪 | Task 6 `test_fixture_a_is_the_only_one_exercising_nonzero_n1` |
| §5.1 檔案佈局 | File Structure |
| §5.2 職責邊界 | File Structure + 各 task docstring |
| §6.1 GameSpec | Task 1 |
| §6.2 SolverOptions | Task 11 |
| §6.3 ReelConfig | Task 8 |
| §7 signature 聚合 | Task 5 |
| §7.3 反爆炸護欄 | Task 5 `test_budget_exceeded_reports_offending_columns` |
| §8 Stage 0–3 | Task 10、Task 11 |
| §9.1–9.4 三層驗證與 gate | Task 8 |
| §10 hook | Task 13 |
| §11 探索 loop | Task 12、slot-solution-explorer skill |
| §12 skill 定義 | Task 14 |
| §13 測試策略 10 項 | Task 2–6、8、13 分別涵蓋 |
| §14 業界對照 | math-notes.md |
| §15 範圍外 | 無 task（正確：明確不做） |
| §16 殘餘風險 | 各 task 的限制註解 |

無缺口。

**2. Placeholder scan**

無 TBD / TODO / 「similar to Task N」/ 無程式碼的程式步驟。每個 test 步驟都有可執行的測試碼，每個實作步驟都有完整模組原始碼。

**3. Type consistency**

- 分佈型別全程 `dict[int, int]`（`payout_units -> combo_count`），`naive.evaluate`、`engine.evaluate`、`build_metrics`、`sigma_deviation`、`Golden.distribution` 一致。
- `grid_payout_units` / `_payout_units` / `_board_payout_units` 三份實作簽名不同名，刻意如此（Global Constraints 已說明）。
- `ReelConfig.spec` 全程是**路徑字串**：Task 11 Step 5 已修正 `solve` 填 `f"configs/{spec.name}.json"`，與 Task 8、9、13 的讀取方式一致。
- `SolverOptions` 欄位名與 Task 11 測試、`cli.py` flags 一致。
- `Metrics` 欄位名在 Task 4 定義，Task 8、9、12 使用一致；`exact_rtp` / `exact_win_rate` 簽名一致。
- `features()` 回傳 5-tuple，`FEATURE_NAMES` 順序與測試斷言的索引一致。
