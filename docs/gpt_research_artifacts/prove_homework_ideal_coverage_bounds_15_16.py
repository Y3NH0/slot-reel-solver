#!/usr/bin/env python3
"""Bounded exhaustive proof for ideal A/B coverage on homework-3x3.

Assumptions proved/used:
* Five declared symbols.
* FULL requires a cyclic s,s,s window on every reel for every symbol.
* Therefore every reel has length at least 15.
* With max_len=16, only lengths 15 and 16 remain.
* Every valid length-15 strip is five symbol triples.
* Every valid length-16 strip is five triples plus one extra occurrence.
The script enumerates all such cyclic strips up to rotation, collapses them
to exact realizable signature histograms, and checks all 2^3 length tuples
and all histogram combinations for exact RTP and minimum win rate.

Requires NumPy and the repository package on PYTHONPATH.
"""

from itertools import permutations, product
from collections import defaultdict
import numpy as np
from fractions import Fraction
from slotmath.models.spec import load_spec
from slotmath.evaluation.windows import column_plans, reel_windows, window_signature

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--spec", default="configs/homework-3x3.json")
args = parser.parse_args()
spec=load_spec(args.spec)


def independent_payout_units(spec, plans, signatures):
    """Independent scalar payout reconstruction for a signature combination."""
    claims = {i: [] for i in range(len(spec.patterns))}
    for plan, signature in zip(plans, signatures):
        for (pattern_index, _rows), symbol in zip(plan.entries, signature):
            claims[pattern_index].append(symbol)
    wins = []
    for pattern_index, reported in claims.items():
        if not reported or reported[0] is None:
            continue
        if all(symbol == reported[0] for symbol in reported):
            wins.append(spec.payout_units(reported[0], spec.patterns[pattern_index]))
    if not wins:
        return 0
    return max(wins) if spec.combine == "max" else sum(wins)

plans=column_plans(spec)
syms=tuple(sorted(spec.symbols))

def has_triple(strip,s):
    L=len(strip)
    return any(all(strip[(t+k)%L]==s for k in range(3)) for t in range(L))

def canon_rot(strip):
    # canonical tuple among rotations; rotations have same hist anyway
    t=tuple(strip);L=len(t)
    return min(t[i:]+t[:i] for i in range(L))

# L15: five blocks length 3. Generate all orders and canonicalize.
strips={15:set(),16:set()}
for order in permutations(syms):
    strip=tuple(x for s in order for x in (s,s,s))
    strips[15].add(canon_rot(strip))
# L16 complete structural generation: five triple blocks + one singleton e,
# allowing adjacency (run4) as well. Any valid strip has this unit decomposition.
for e in syms:
    units=[(s,s,s) for s in syms]+[(e,)]
    # distinguish triple(e) and singleton(e) by tuple length; all units unique otherwise
    for order in permutations(range(6)):
        strip=tuple(x for idx in order for x in units[idx])
        if all(has_triple(strip,s) for s in syms):
            strips[16].add(canon_rot(strip))
print('strip counts', {L:len(v) for L,v in strips.items()})
# sanity count expected 24 and 480

# Build full candidate signature domains independent of strips
sig_domains=[]
for plan in plans:
    dom={window_signature(w,plan) for w in product(syms, repeat=spec.grid.rows)}
    sig_domains.append(sorted(dom,key=repr))
print('sig domains',list(map(len,sig_domains)))
U=np.zeros(tuple(map(len,sig_domains)),dtype=np.int64)
W=np.zeros_like(U)
for inds in product(*(range(len(d)) for d in sig_domains)):
    sigs=tuple(sig_domains[c][inds[c]] for c in range(3))
    u=independent_payout_units(spec,plans,sigs)
    U[inds]=u;W[inds]=1 if u else 0

# unique hist vectors for each (col,length), retain witness strip
H={}
Witness={}
for c,plan in enumerate(plans):
    idx={s:i for i,s in enumerate(sig_domains[c])}
    for L in (15,16):
        d={}
        for strip in strips[L]:
            a=[0]*len(idx)
            for w in reel_windows(strip,spec.grid.rows):
                a[idx[window_signature(w,plan)]]+=1
            key=tuple(a)
            d.setdefault(key,strip)
        arr=np.asarray(list(d.keys()),dtype=np.int64)
        H[c,L]=arr;Witness[c,L]=list(d.values())
        print('unique hists col',c,'L',L,len(arr))

found=[]
closest=[]
for lens in product((15,16),repeat=3):
    H0,H1,H2=(H[c,lens[c]] for c in range(3))
    N=lens[0]*lens[1]*lens[2]
    target=19*N
    count_checked=0
    exact_count=0
    maxwin=Fraction(0)
    for i in range(len(H0)):
      # batch over all H1: contractions shape (n1,sig2)
      # einsum a, jb, abc -> jc
      TV=np.einsum('a,jb,abc->jc',H0[i],H1,U,optimize=True)
      WV=np.einsum('a,jb,abc->jc',H0[i],H1,W,optimize=True)
      totals=TV@H2.T # n1,n2
      wins=WV@H2.T
      count_checked += totals.size
      mask=totals==target
      exact_count += int(mask.sum())
      feas=np.argwhere(mask & (wins*20>=11*N))
      if feas.size:
        j,k=map(int,feas[0])
        found.append((lens,i,j,k,int(wins[j,k])))
        print('FOUND',lens,'hidx',i,j,k,'win',Fraction(int(wins[j,k]),N))
        print(list(Witness[0,lens[0]][i]));print(list(Witness[1,lens[1]][j]));print(list(Witness[2,lens[2]][k]))
        raise SystemExit
      # closest track by absolute units; retain max win among exact
      flat=np.argmin(np.abs(totals-target));j,k=np.unravel_index(flat,totals.shape)
      closest.append((abs(int(totals[j,k]-target)),int(totals[j,k]-target),Fraction(int(wins[j,k]),N),lens,i,int(j),int(k)))
      if mask.any():
        maxw=int(wins[mask].max()); maxwin=max(maxwin,Fraction(maxw,N))
    print('lens',lens,'checked',count_checked,'exactRTP hist combos',exact_count,'max exact win',maxwin)
print('NO FEASIBLE')
for x in sorted(closest,key=lambda x:x[0])[:20]:print('closest',x)
