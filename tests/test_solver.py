import time
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


def test_solve_terminates_on_an_impossible_target_near_the_cli_defaults():
    """The CLI's real defaults are max_seeds=400, max_candidates=40_000 (see
    SolverOptions and the `solve` subcommand); the test above only proves
    termination at max_seeds=2, max_candidates=200, which is nowhere near
    that path. 20/3_000 is two orders of magnitude below the real defaults on
    both axes -- still nowhere near the actual budget -- but it is the
    largest size that reliably finishes in a bit over a second on this
    machine (measured ~1.2s locally), which keeps the suite fast while still
    exercising the "many attempts, each doing real search_last_reel work"
    shape that a hang would actually come from, rather than the near-instant
    2/200 case. The wall-clock bound below is generous (10s) to avoid
    flakiness on slower CI machines while still catching a real hang."""
    spec = hw(targets={"rtp": 1000, "min_win_rate": 0.55})
    start = time.monotonic()
    result = solve(spec, SolverOptions(seed=1, max_seeds=20, max_candidates=3000))
    elapsed = time.monotonic() - start
    assert result is None
    assert elapsed < 10.0, f"solve took {elapsed:.2f}s, expected a quick None"
