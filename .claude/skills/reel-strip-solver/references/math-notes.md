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

General form: let `g` be the gcd of the payout unit values *actually present
in a candidate's payout support*, not every value the spec permits. This
distinction matters: the full spec-level gcd across `{5, 11, 20, 25, 55, 60,
100, 300, 500}` is 1, because `11` is coprime to the rest, and a check
against that modulus would be vacuous -- it would never reject anything. The
obstruction only shows up once a candidate's reels decline to use the `11`
payout: with support `{5, 20, 100}`, `g = 5`. The necessary condition is
`rtp * D * N = 0 (mod g)`. For the homework paytable, `N = 1296` gives a
required total of `19 * 1296 = 24624`, and `24624 mod 5 = 4 != 0`, so
`gcd({5, 20, 100}) == 5` rejects `N = 1296` outright -- no amount of search
at that spin count can land on target once the `11` payout is off the table.

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

Existence has two distinct routes, and an implementation must recognise both:

1. **Mixed signs** -- pick `w_p > 0` and `w_q < 0`, set `n_p = |w_q|` and
   `n_q = w_p`.
2. **A zero weight** -- if some `w_z == 0`, put the whole last reel on
   signature `z`, at any length.

Mixed signs do NOT always occur. Golden fixtures A and B have 15 negative
weights and one zero, no positives at all; they reach the target by route 2
with a uniform last reel (`[1]*6` and `[2]*6`) whose single signature has
weight 0. Only fixture C has mixed signs (1 positive, 15 negative).

Both routes can be absent -- all weights the same sign with no zero -- in
which case that pair of fixed reels has no solution and the solver must move
on. `search_last_reel` trying uniform strips first is a cheap probe of route 2.

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
