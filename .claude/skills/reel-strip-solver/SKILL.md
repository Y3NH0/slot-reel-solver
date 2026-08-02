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
  falls out of the equation instead of being guessed.
- **Existence has two independent routes, and neither is guaranteed.** (a)
  Mixed signs: if some `w_p > 0` and some `w_q < 0`, take `n_p = |w_q|`,
  `n_q = w_p`. (b) A zero weight: if some `w_z == 0`, put the whole last reel
  on signature `z`, at any length. The golden fixtures show both shapes: A
  and B have no positive weight at all (15 negative, one zero) and are
  solved via route (b) with a uniform last reel; only C has a positive
  weight alongside negative ones and is solved via route (a). Both routes
  can be absent -- all weights the same sign with no zero -- in which case
  that particular pair of fixed reels has no solution at this length, and
  the search must move on to a different fixed-reel choice rather than keep
  searching the same one.
- **Limitation, stated plainly:** a signature histogram is not freely
  realizable. A run of `k` identical symbols forces `k-2` triple signatures
  plus two boundary signatures, so converting a solution back into a real
  cyclic strip still requires a finite search. This is not a closed form.
  Do not describe it as one.
- **Every accepted candidate uses every declared symbol at least once.**
  Nothing about RTP or win-rate requires this on its own -- a symbol can be
  sampled zero times by pure chance -- so the acceptance loop filters it
  explicitly, rejecting any candidate whose reels don't cover the full
  symbol set. `slotmath verify`'s `all_symbols_used` gate catches it too, in
  case a config was produced or edited some other way.
- **Per-reel symbol coverage IS achievable, and is supported.** Set
  `"coverage": {"each_reel_all_symbols": true}` in the spec; the solver then
  guarantees the bound during generation and `slotmath verify` adds a
  `per_reel_symbol_coverage` gate naming any reel/symbol that is missing.
  `configs/homework-3x3-per-reel-coverage.json` plus
  `solutions/homework-3x3-per-reel-coverage.json` are a worked example
  (RTP exactly 19/20, win rate 37/60, every reel carrying all five symbols).
  An earlier note here claimed this was in structural tension with the
  targets; that was wrong, and it was wrong in the specific way this file
  warns about everywhere else -- a stochastic search came back empty and the
  emptiness got written up as a property of the problem. The shape that works
  is one cheap symbol filling most of the strip with the rest sitting in it as
  isolated single positions.
- **Which symbol dominates a reel is forced, not a matter of taste.** RTP =
  win_rate x average payout per win, so requiring win_rate >= min_win_rate
  caps the average win at RTP / min_win_rate. For the homework paytable that
  is 19/11, i.e. 34.5 payout units: symbol 2 (20 units) can dominate a reel,
  symbols 3 (60) and 4 (100) cannot -- fill a reel with either and the win
  rate tops out near 0.32 and 0.19 respectively however long you search.
  `diophantine.affordable_core_symbols()` derives this from the spec.
- **Do not chase "every symbol wins via multiple patterns" as a hard
  requirement without re-reading this note first.** For the homework paytable
  this is now settled by exhaustive enumeration rather than by sampling: run
  `slotmath feasibility` on a spec with
  `"symbol_pattern": "raw"` and it reports `bounded_exhausted` over lengths
  15..16 (1512 strips, 343 histogram combinations, not one reaching exact
  RTP). Say "proven infeasible under reel length bounds 3..16", never
  "mathematically impossible" -- the bound is a configuration choice and
  longer reels are simply not covered by the enumeration.
  Why the geometry forces it: FULL spans all three rows of every column, so a
  symbol only completes it with a cyclic run of 3, and every symbol needing
  one on every reel puts the floor at 3 x 5 = 15 positions. With max_len=16
  just two lengths survive, and the strip space collapses to something small
  enough to settle exactly -- five blocks of three, plus at most one spare
  position. `solving/feasibility.py` enumerates it and finds no configuration
  reaching exact RTP at all, so the win-rate target never even comes into
  play. Raising max_len re-opens the question; the enumeration says nothing
  about longer reels, and the strip count grows fast once the slack does.

  An earlier revision of this note reported that such a construction had been
  found hitting RTP=19/20 with win_rate ~0.30. The enumeration contradicts
  that, and the enumeration is the thing that is checked -- treat the old
  figure as unverified and gone. Sampling-based claims about this paytable
  have been wrong more than once; prefer `slotmath feasibility` over
  recollection.

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
