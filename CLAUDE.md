# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`slotmath` is a toolkit for finding slot-machine reel configurations whose Return To Player (RTP) equals a target **exactly** (as a rational number, not a float within tolerance) while also meeting a minimum win-rate. Payouts are tracked as exact integer "payout units" (`Fraction`-typed internally); RTP/win-rate comparisons against targets are always exact `Fraction` equality/inequality, never floating point with an epsilon. Floats appear only as a display layer over the integer counts, never as the basis for a pass/fail decision.

The accepted deliverable is `solutions/homework-3x3.json`, solving `configs/homework-3x3.json` per `docs/DS-HomeWork.md`.

## Commands

```bash
# install (editable, with dev deps)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# run full test suite
.venv/bin/python -m pytest -v

# run a single test file / test
.venv/bin/python -m pytest tests/test_solver.py -v
.venv/bin/python -m pytest tests/test_solver.py::test_name -v

# the CLI (also installed as console script `slotmath` inside the venv)
slotmath spec configs/homework-3x3.json                     # validate + summarize a GameSpec
slotmath solve configs/homework-3x3.json --seed 500 --out solutions/homework-3x3.json
slotmath verify solutions/homework-3x3.json                  # 3-layer verification
slotmath verify solutions/homework-3x3.json --mc-spins 20000000
slotmath report solutions/homework-3x3.json                  # human-readable payout table
slotmath explore configs/homework-3x3.json --seed 500 --rounds 6 --portfolio solutions/portfolio.json
```

Exit-code contract, held everywhere (CLI and hook): `0` = passed, `1` = verification failed, `2` = the tool itself couldn't run (missing file, malformed JSON, schema violation) — exit 2 says nothing about solution correctness.

Always invoke the project's own interpreter (`.venv/bin/python` / `.venv/bin/slotmath`), not a bare `python3` — a bare `python3` may resolve to an unrelated interpreter without `slotmath` installed (this exact bug once left the PostToolUse hook silently broken; see `.claude/settings.json`).

## Architecture

### The trust chain: three independent evaluators must agree

`src/slotmath/naive.py`, `engine.py`, and `montecarlo.py` all compute a payout distribution for a set of reels, and are cross-checked rather than trusted individually:

- **`naive.py`** — full board enumeration (`grid_payout_units`, `evaluate`), deliberately slow and simple. This is the trust anchor: correct by inspection, not by performance.
- **`engine.py`** — the fast evaluator the solver's inner loop actually uses. Instead of enumerating every reel-stop combination, it collapses each reel into a histogram over distinct per-column "signatures" (`signature_histograms`) — what a touching pattern would see in that column: a matching symbol or `None` — since pattern-matching decomposes per column. This turns `O(prod(len(reel_i)))` into `O(prod(|signatures_c|))`, while remaining exact. Raises `SignatureBudgetExceeded` if the signature space would exceed budget, guarding against unbounded enumeration on oversized artifacts.
- **`montecarlo.py`** — an independent simulation sharing zero abstractions with the other two. This independence is enforced by `tests/test_montecarlo.py`'s AST-based test, which walks the module's import statements rather than grepping for substrings (a grep-based check previously missed `from slotmath import engine`-style imports).

The combine-logic (how multiple winning patterns on one spin add up — see `Pattern.combine`, default `"max"`: only the single highest-paying pattern pays) is intentionally re-implemented in all three modules rather than factored into one shared helper, so a bug in one becomes a visible disagreement instead of a silent shared mistake. When changing payout logic, all three must be updated in lockstep and re-verified against each other and against `tests/fixtures.py`'s golden fixtures (A/B/C).

### Data flow

```
GameSpec (configs/*.json)              ReelConfig (solutions/*.json)
  spec.py: load_spec, payout_units()     verify.py: ReelConfig model
        |                                       |
        v                                       v
  windows.py: reel_windows (cyclic),    verify(): 3-layer check
  column_plans, window_signature          1. file self-consistency (metrics.py)
        |                                  2. naive vs engine vs file
        v                                  3. fixed-seed montecarlo vs file
  naive.py / engine.py: distribution           |
        |                                       v
        v                                 cli.py: verify/report subcommands
  metrics.py: build_metrics, exact_rtp, exact_win_rate
        |
        v
  solver.py + diophantine.py: search for reels hitting an exact RTP target
        |
        v
  portfolio.py: diversity-filtered collection of solved configs (explore)
```

- **`spec.py`** is the single trust boundary — all external input (`GameSpec`, `Pattern`, `Grid`, `Targets`) is validated here via Pydantic v2. A `Rational` type coerces probabilities/multipliers to `Fraction` via `Fraction(repr(x))` — never `Fraction(x)` directly, which produces binary-expansion garbage for values like `0.55`. `payout_unit_denominator()` (cached) is the smallest common denominator across the whole paytable; `payout_units(symbol, pattern)` converts a payout to an exact integer count of those units.
- **`windows.py`** treats a reel as a cyclic strip; a spin's window is `rows` consecutive symbols wrapping around. `column_plans` derives, per grid column, which patterns touch which cells; `window_signature` collapses a window to what those patterns would actually see.
- **`solver.py`** orchestrates a multi-stage search: Stage 0 actively *prefers* reel-length tuples divisible by a derived modulus (`derive_preferred_modulus`, `congruence_ok`) rather than merely pruning bad ones — this is a real mod-N congruence invariant over reachable payout-unit sums, not a heuristic. Later stages fall back to run-composition seeding and local search.
- **`diophantine.py`** implements the exact "fix all reels but the last" construction: for each possible last-column signature, compute an integer weight (`signature_weights`); a solution exists via either mixed-sign weights (`has_mixed_signs`) or a lone zero-weight signature — **neither route is guaranteed to exist for a given fixed-reel choice**; if both are absent, the caller must try a different fixed-reel pair. Converting an abstract signature histogram back into a real cyclic strip is a finite search (`search_last_reel`, `_run_composition`), not a closed form — a run of `k` identical symbols forces specific signature counts.
- **`verify.py`** runs the three layers described above and produces a `VerifyReport` of named `Gate`s; `ReelConfig.solver` is non-authoritative metadata (a reproducibility hint), never trusted for the actual verdict.
- **`portfolio.py`** admits new solved configs into a diverse set using a 5-dimension feature vector (win_rate, volatility, log(1+max_win), payout-distribution entropy, spin_count). Distance thresholds and per-dimension ranges are frozen during an explicit calibration phase (`maybe_calibrate`, default calibration size 6) rather than recomputed live per comparison — recomputing live against a tiny existing set was tried and rejected (two-point min-max makes any two candidates look maximally distant).
- **`cli.py`** wires everything into subcommands (`spec`, `solve`, `verify`, `report`, `explore`); `main(argv) -> int` is the single entry point, used both by the installed console script and in-process by tests and the hook.

### The PostToolUse hook

`scripts/hooks/verify_on_write.py` (registered in `.claude/settings.json` on `Write|Edit`) runs verification automatically whenever a file under `configs/` or `solutions/` is written, distinguishing a `GameSpec` (has `"grid"`, no `"reels"`) from a `ReelConfig` by shape. It deliberately carries its own copy of the read-and-parse guard rather than importing `cli.py`'s (to keep the hook's fast path light) — if you fix a JSON-loading edge case in one, check the other; each references the other with a cross-comment.

### Skills

`.claude/skills/{slot-math-model,reel-strip-solver,slot-config-verifier,slot-solution-explorer}/SKILL.md` document the workflow for building a `GameSpec`, solving it, verifying a solution, and running the diversity-exploration loop, respectively — each command they document is verified against real `--help` output rather than aspirational.

## Working conventions

- **Never use `Fraction(x)` on a float or a spec value that started as a float/JSON number.** Use `Fraction(repr(x))` (see `spec.py:_coerce_fraction`) or work from the already-validated `Rational`-typed field.
- **Any change touching payout computation must be applied to `naive.py`, `engine.py`, and `montecarlo.py` together**, then checked against `tests/fixtures.py`'s golden fixtures (A/B/C) and against each other — this triple-cross-check is the project's actual correctness mechanism, not the 190+ passing tests in isolation.
- **RTP/win-rate targets are compared with exact `Fraction` equality**, never `math.isclose` or a tolerance band. The one sanctioned float tolerance in the codebase is `verify.py`'s `_FLOAT_RTOL = 1e-9`, confined strictly to checking the four *display* floats (`rtp`, `win_rate`, `volatility`, `max_win`) round-trip consistently from the integer counts — it must never leak into a target comparison.
- Full design rationale and the complete history of what was tried and rejected live in `docs/superpowers/specs/2026-07-31-slot-reel-rtp-design.md` and `docs/superpowers/plans/2026-07-31-slot-reel-rtp-toolkit.md`.
