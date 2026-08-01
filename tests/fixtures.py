"""Golden fixtures from spec section 4.1.

All three were cross-verified by three independent implementations; RTP is an
exact Fraction equality with 19/20, not an approximation.

Fixture A MUST NOT BE REMOVED even though its win_rate looks degenerate.
It is the only fixture with n1 != 0 (n1 = 324, and its N = 396 is not
divisible by 5), so it is the only one that catches a solver which silently
assumes n1 = 0. It is also the only fixture with win_rate = 1. B and C both
have 5 | N and n1 = 0 and would let that regression through.
See spec section 4.3.

Symbol coverage is ALSO deliberately uneven across the three, and this is
load-bearing for tests/test_verify.py's all_symbols_used gate tests: A uses
all five declared symbols {0,1,2,3,4}; B never uses 1 or 4; C never uses 0.
Do not "complete" B or C's symbol coverage without updating those tests --
they specifically exercise "hits RTP/win-rate exactly but a symbol is
unused" using B and C as the real, pre-existing data for that case.
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
