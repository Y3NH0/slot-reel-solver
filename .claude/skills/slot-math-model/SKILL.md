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
- Compute the congruence obstruction, but only against the payout support a
  real candidate would actually use, not the full spec. With
  `payout_unit_denominator = D`, every payout is an integer number of `1/D`.
  A spec-level gcd over every reachable payout value is typically 1 (the
  paytable usually has at least one payout coprime to the rest), which makes
  a spec-wide modulus check vacuous. The real obstruction only appears once a
  candidate's reels decline to use one of those payouts -- e.g. dropping the
  `11`-unit payout from the reachable set leaves `gcd({5, 20, 100}) == 5`,
  which then rejects any spin count whose required total is not a multiple
  of 5 (`N = 1296` is rejected this way for the homework paytable). Report
  which payout values are in play and what their gcd is.

## Output Contract

Return:

1. `GameSpec`: the JSON, written to `configs/<name>.json`.
2. `Structural Facts`: shared cells, the average-win floor, the congruence
   modulus (computed over the payout support actually in play) and which
   symbol provides the fine adjustment.
3. `Reachability`: whether the target looks attainable, with the reasoning.
4. `Assumptions`: anything the prose rules left unstated, marked explicitly.

## Execution Rules

- Never widen a rule to make the math easier. If the rules are ambiguous,
  state both readings and ask.
- Use `win_rate` and `min_win_rate`. The industry-standard "hit rate" naming
  was rejected for this project -- do not reintroduce it as a field name.
- Use `pattern_multiplier`. Never `mult`, and never describe it as a bonus --
  the value is multiplicative, and "bonus" invites an additive bug.
