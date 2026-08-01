import pytest
from slotmath.evaluation import montecarlo, naive
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


def test_montecarlo_shares_no_abstraction_with_the_exact_evaluators():
    """Layer 3's whole purpose is to reach the same numbers along a route that
    shares nothing with layers 1 and 2. Enforced by AST rather than by grepping
    for substrings, because `from slotmath import engine` and a function-local
    import both slip past a substring check.
    """
    import ast
    from pathlib import Path

    forbidden = {"engine", "windows", "naive"}
    source = Path(montecarlo.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            imported.add(base)
            for alias in node.names:
                imported.add(f"{base}.{alias.name}" if base else alias.name)
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in {"import_module", "__import__"}:
                raise AssertionError(
                    "dynamic import in montecarlo.py defeats the independence guard"
                )

    leaked = {
        target for target in imported
        if any(part in forbidden for part in target.split("."))
    }
    assert not leaked, f"montecarlo.py must not import {sorted(leaked)}"
