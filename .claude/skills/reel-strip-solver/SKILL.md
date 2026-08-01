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
