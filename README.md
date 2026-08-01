# slotmath

A toolkit for finding slot-machine reel configurations whose Return To
Player (RTP) equals a target **exactly** -- not approximately, not within a
tolerance band, but as an exact rational number -- while also meeting a
minimum win-rate requirement. It exists because RTP claims in this domain
need to be provable, not eyeballed from a simulation.

Every payout is tracked as an exact integer count of "payout units"
(`Fraction`-typed internally; the smallest common denominator across the
paytable). RTP and win-rate are compared as exact `Fraction` equality/
inequality against the target -- never as floating point with an epsilon.
Floats only ever appear as a display convenience layered on top of the
integer counts, never as the basis for a pass/fail decision.

## How correctness is enforced

- **Three independent evaluators** compute the payout distribution for a
  set of reels and are required to agree exactly:
  - `naive.py` -- full board enumeration, deliberately slow and simple. The
    trust anchor.
  - `engine.py` -- a fast signature-aggregating evaluator used by the
    solver's inner loop.
  - `montecarlo.py` -- an independent simulation path that shares no code
    with the other two, so a shared translation bug (e.g. a transposed
    grid axis) in `naive`/`engine` doesn't silently agree with itself.

  The combine-logic (how multiple winning patterns on one spin add up) is
  intentionally duplicated across all three modules rather than factored
  into a shared helper -- a bug in one becomes a visible disagreement
  instead of a silent shared mistake.

- **Three verification layers** (`slotmath verify`), run in order and all
  required to pass:
  1. **File consistency** -- the artifact's own integer counts (and the
     derived display floats: `rtp`, `win_rate`, `volatility`, `max_win`)
     are checked against each other. Zero external computation.
  2. **Engine vs naive vs file** -- both evaluators are recomputed from the
     reels and required to agree with each other and with the file.
  3. **Independent Monte Carlo** -- a fixed-seed simulation confirms the
     exact result is not an artifact of a shared assumption in the other
     two layers.

- A **PostToolUse hook** (`scripts/hooks/verify_on_write.py`) runs
  verification automatically whenever a file under `configs/` or
  `solutions/` is written, so a bad artifact is reported back immediately
  instead of discovered later.

## The accepted deliverable

`solutions/homework-3x3.json` holds a genuine solution to
`configs/homework-3x3.json` (a 3x3 grid, target RTP 0.95, minimum win rate
0.55):

| | |
|---|---|
| Reels | `[2,2,2]`, `[3,3,3,2,2,2,1,1]`, `[3,3,3,3,4,3,3,3,3,0,0,0,4,4,3]` |
| RTP | exactly `19/20` (0.95) |
| Win rate | exactly `17/30` (~0.567), above the 0.55 minimum |
| Max win | 3x |
| Symbols used | all five (0-4) |
| Spin count | 360 (`3 x 8 x 15`) |
| Payout distribution | `{0: 156, 1x: 135, 3x: 69}` |

This is entry 0 of `solutions/portfolio.json` (produced by
`slotmath explore configs/homework-3x3.json --seed 500`) and is
independently reproduced by `slotmath solve configs/homework-3x3.json
--seed 500` -- the `solver.command` recorded in the artifact is that
literal, runnable command.

An earlier version of this file held a *degenerate* configuration -- two
symbols, win rate exactly 1 -- that met the RTP and win-rate targets only
by making it impossible for the player to lose. It was legal under the
letter of the spec but not a real answer, and was replaced with the
configuration above.

## Install

Requires Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## The commands

```bash
# 1. Validate a GameSpec and print a summary (grid, symbols, targets, ...)
slotmath spec configs/homework-3x3.json

# 2. Search for reels meeting the spec's RTP and win-rate targets
slotmath solve configs/homework-3x3.json --seed 500 --out solutions/homework-3x3.json

# 3. Verify a solution against its spec through all three layers
slotmath verify solutions/homework-3x3.json

# 4. Print a human-readable payout table for a solution
slotmath report solutions/homework-3x3.json
```

A fifth command, `slotmath explore`, runs `solve` repeatedly and keeps a
diverse *portfolio* of solutions (rejecting near-duplicates by a calibrated
distance threshold over win rate, volatility, max win, payout entropy and
spin count):

```bash
slotmath explore configs/homework-3x3.json --seed 500 --rounds 6 \
  --portfolio solutions/portfolio.json
```

Exit codes are a contract across every command: `0` means it passed (or
succeeded), `1` means verification did not pass, `2` means the tool itself
could not run (missing file, malformed JSON, a schema violation) -- exit 2
says nothing about whether a solution is correct.

## Verifying the deliverable yourself

```bash
.venv/bin/slotmath verify solutions/homework-3x3.json
```

should print eight `PASS` gates (one is a warning-severity gate that also
passes here, since this configuration's win rate is below 1) and exit 0.
Widen the Monte Carlo layer for a more thorough independent check:

```bash
.venv/bin/slotmath verify solutions/homework-3x3.json --mc-spins 20000000
```

## Tests

```bash
.venv/bin/python -m pytest -v
```
