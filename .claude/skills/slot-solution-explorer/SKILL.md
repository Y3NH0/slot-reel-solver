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
distance from every existing entry is at least the calibrated threshold --
except during calibration itself (see below), when every gate-passing
candidate is admitted unconditionally.

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

`explore` has a calibration phase, not just a calibration aspiration. While
`portfolio.calibration` is unset, every candidate that passes the gates is
admitted unconditionally -- there is no threshold yet to filter against.
Once the portfolio reaches `--calibration-size` entries (default 6), the CLI
derives per-dimension feature ranges and a distance threshold from the
spread actually observed across that unfiltered sample, via
`build_calibration`, and stores both on `portfolio.calibration`. From that
point on, `should_admit` is genuinely engaged and filters on distance.

`--recalibrate` discards whatever calibration currently exists and derives a
fresh one immediately from however many entries are already in the
portfolio -- use it if the portfolio's shape has drifted enough that the old
ranges no longer reflect the feature space.

Do not describe calibration as something the agent must manually orchestrate
by counting to ten; the CLI does the counting and the derivation. The
agent's job is choosing where to explore next each round (step 2 above), not
managing when calibration kicks in.

## Output Contract

Return:

1. `Portfolio`: every admitted configuration with its metrics.
2. `Coverage`: which regions of the feature space are populated and which are
   empty.
3. `Rejected`: candidates turned away and why -- gate failure or too similar.
4. `Calibration`: whether the portfolio is still in the unfiltered
   calibration phase or has a derived threshold, and what that threshold and
   the per-dimension ranges are.
5. `Stop Reason`: portfolio full, or K dry rounds.

## Execution Rules

- Verify every candidate before admitting it. A diverse portfolio of wrong
  answers is worthless.
- Never loosen the targets to increase diversity. Diversity is subordinate to
  correctness.
- If the loop produces nothing for K rounds, report that. Do not keep
  spinning.
