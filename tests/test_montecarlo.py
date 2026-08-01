import pytest
from slotmath import montecarlo, naive
from tests.fixtures import GOLDEN
from tests.test_naive import hw

IDS = [g.name for g in GOLDEN]


def test_simulate_is_deterministic_for_a_fixed_seed():
    spec, reels = hw(), GOLDEN[2].reels
    a = montecarlo.simulate(spec, reels, spins=20_000, seed=7)
    b = montecarlo.simulate(spec, reels, spins=20_000, seed=7)
    assert a == b


def test_different_seeds_give_different_results():
    spec, reels = hw(), GOLDEN[2].reels
    a = montecarlo.simulate(spec, reels, spins=20_000, seed=7)
    b = montecarlo.simulate(spec, reels, spins=20_000, seed=8)
    assert a != b


@pytest.mark.parametrize("g", GOLDEN, ids=IDS)
def test_monte_carlo_agrees_with_exact_within_five_sigma(g):
    """Fixed seed makes this deterministic, so it is safe as a hard gate."""
    spec = hw()
    exact = naive.evaluate(spec, g.reels)
    sim = montecarlo.simulate(spec, g.reels, spins=200_000, seed=20260731)
    assert abs(montecarlo.sigma_deviation(spec, g.reels, sim, exact)) < 5.0


def test_zero_variance_config_gives_zero_sigma():
    """Uniform reels: every spin pays the same, so variance is 0 and the
    simulated mean must equal the exact mean bit for bit."""
    spec = hw()
    reels = [[2] * 4, [2] * 4, [2] * 4]
    exact = naive.evaluate(spec, reels)
    sim = montecarlo.simulate(spec, reels, spins=5_000, seed=1)
    assert montecarlo.sigma_deviation(spec, reels, sim, exact) == 0.0


def test_montecarlo_does_not_import_engine_or_windows():
    """Layer 3 must not share abstractions with layers 1 and 2. See spec 9.3."""
    source = (
        __import__("pathlib").Path(montecarlo.__file__).read_text(encoding="utf-8")
    )
    assert "from slotmath.engine" not in source
    assert "from slotmath.windows" not in source
    assert "import slotmath.engine" not in source
    assert "import slotmath.windows" not in source
