"""Optional spec.coverage constraints: validation, gates, search, statuses."""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from slotmath.evaluation import engine, naive
from slotmath.evaluation.coverage import (
    cross_check_coverage,
    minimum_reel_length,
    missing_symbols_per_reel,
)
from slotmath.models.metrics import build_metrics, exact_rtp, exact_win_rate
from slotmath.models.spec import GameSpec, load_spec
from slotmath.solving.diophantine import _run_composition, affordable_core_symbols
from slotmath.solving.feasibility import (
    SolveStatus,
    precheck,
    prove_bounded_coverage_infeasible,
)
from slotmath.solving.solver import (
    SolverOptions,
    candidate_length_tuples,
    coverage_lower_bounds,
    solve_with_status,
)
from slotmath.verification.verify import ReelConfig, verify
from tests.fixtures import GOLDEN
from tests.test_naive import hw

# The per-reel-coverage solution, under the homework's combine="sum" rule. Its
# reels are the fixture; every number below is recomputed from them by the
# repository's own evaluators, never read from a file, so the test would catch
# a solution that was edited to look correct.
PER_REEL_REELS = [
    [0, 2, 2, 2, 2, 4, 1, 2, 2, 3],
    [1, 4, 2, 2, 2, 2, 2, 2, 3, 2, 2, 2, 2, 0, 2, 2],
    [1, 2, 2, 0, 2, 2, 2, 4, 2, 2, 3, 2, 2, 2, 0],
]


def coverage_spec(**coverage) -> GameSpec:
    raw = json.loads(Path("configs/homework-3x3.json").read_text(encoding="utf-8"))
    raw["coverage"] = coverage
    return GameSpec.model_validate(raw)


def config_for(reels, spec) -> ReelConfig:
    metrics = build_metrics(spec, engine.evaluate(spec, reels, budget=5_000_000))
    return ReelConfig(spec="configs/homework-3x3.json", reels=reels, metrics=metrics)


# --------------------------------------------------------------------------
# spec validation and backward compatibility
# --------------------------------------------------------------------------


def test_a_spec_without_a_coverage_block_is_unconstrained():
    """Every spec written before this feature must behave exactly as before."""
    spec = load_spec("configs/homework-3x3.json")
    assert spec.coverage.each_reel_all_symbols is False
    assert spec.coverage.symbol_pattern == "none"
    assert spec.coverage.is_active() is False
    assert coverage_lower_bounds(spec) is None
    assert all(minimum_reel_length(spec, c) == 0 for c in range(spec.grid.cols))


def test_unconstrained_spec_gains_no_coverage_gates():
    spec = load_spec("configs/homework-3x3.json")
    report = verify(spec, config_for(GOLDEN[0].reels, spec), mc_spins=20_000)
    names = {g.name for g in report.gates}
    assert "per_reel_symbol_coverage" not in names
    assert "symbol_pattern_coverage" not in names


def test_an_unknown_symbol_pattern_tier_is_rejected_at_the_boundary():
    with pytest.raises(Exception):
        coverage_spec(symbol_pattern="sometimes")


def test_coverage_constraints_round_trip_from_a_real_config_file():
    spec = load_spec("configs/homework-3x3-per-reel-coverage.json")
    assert spec.coverage.each_reel_all_symbols is True
    assert spec.coverage.is_active() is True


# --------------------------------------------------------------------------
# the per-reel gate
# --------------------------------------------------------------------------


def test_per_reel_gate_passes_when_every_reel_holds_every_symbol():
    spec = coverage_spec(each_reel_all_symbols=True)
    report = verify(spec, config_for(PER_REEL_REELS, spec), mc_spins=20_000)
    gate = next(g for g in report.gates if g.name == "per_reel_symbol_coverage")
    assert gate.passed, gate.detail
    assert report.passed, report.render()


def test_per_reel_gate_names_the_reel_and_the_symbol_it_is_missing():
    """'coverage failed' does not tell an author which strip to edit."""
    spec = coverage_spec(each_reel_all_symbols=True)
    reels = [list(r) for r in PER_REEL_REELS]
    reels[1] = [s if s != 4 else 2 for s in reels[1]]  # drop symbol 4 from reel 1
    report = verify(spec, config_for(reels, spec), mc_spins=20_000)
    gate = next(g for g in report.gates if g.name == "per_reel_symbol_coverage")
    assert not gate.passed
    assert "reel 1" in gate.detail
    assert "symbol 4" in gate.detail
    assert not report.passed


def test_the_committed_homework_solution_fails_the_stricter_constraint():
    """It satisfies its own spec, which asks only for the union. Under the
    stronger constraint it does not, and the gate must say so."""
    spec = coverage_spec(each_reel_all_symbols=True)
    reels = json.loads(
        Path("solutions/homework-3x3.json").read_text(encoding="utf-8")
    )["reels"]
    report = verify(spec, config_for(reels, spec), mc_spins=20_000)
    gate = next(g for g in report.gates if g.name == "per_reel_symbol_coverage")
    assert not gate.passed
    assert "reel 0" in gate.detail


def test_missing_symbols_per_reel_is_index_aligned():
    spec = hw()
    reels = [[2, 2, 2], [0, 1, 2, 3, 4], [3, 3, 3]]
    assert missing_symbols_per_reel(spec, reels) == [[0, 1, 3, 4], [], [0, 1, 2, 4]]


# --------------------------------------------------------------------------
# the regression solution
# --------------------------------------------------------------------------


def test_per_reel_solution_has_the_exact_expected_metrics():
    """Recomputed from the reels by both exact evaluators. The numbers are
    pinned so a change in payout logic cannot quietly move them."""
    spec = coverage_spec(each_reel_all_symbols=True)
    assert [len(r) for r in PER_REEL_REELS] == [10, 16, 15]

    naive_dist = naive.evaluate(spec, PER_REEL_REELS)
    engine_dist = engine.evaluate(spec, PER_REEL_REELS, budget=5_000_000)
    assert naive_dist == engine_dist

    metrics = build_metrics(spec, naive_dist)
    assert metrics.spin_count == 2400
    assert metrics.win_count == 1356
    assert metrics.total_payout_units == 45600
    # The 40/60/180 buckets only exist because payouts sum: 40 is two 2x2
    # patterns at once, 180 is all four plus FULL (4x20 + 100). Under "max"
    # this distribution would collapse onto 20 and 100 alone.
    assert {b.payout_units: b.combo_count for b in metrics.payout_distribution} == {
        0: 1044,
        20: 744,
        40: 444,
        60: 144,
        180: 24,
    }
    assert exact_rtp(metrics) == Fraction(19, 20)
    assert exact_win_rate(metrics) == Fraction(113, 200)
    assert all(not m for m in missing_symbols_per_reel(spec, PER_REEL_REELS))


def test_the_submitted_solution_verifies():
    spec = load_spec("configs/homework-3x3-per-reel-coverage.json")
    data = json.loads(
        Path("solutions/homework-3x3-per-reel-coverage.json").read_text(
            encoding="utf-8"
        )
    )
    report = verify(spec, ReelConfig(**data), mc_spins=200_000)
    assert report.passed, report.render()
    assert all(not m for m in missing_symbols_per_reel(spec, data["reels"]))


def test_the_bare_requirements_solution_verifies():
    """Kept alongside the submitted solution for comparison: its spec has no
    coverage block, so it is judged on RTP and win rate alone. The contrast is
    what justifies submitting the stricter one -- see the README."""
    spec = load_spec("configs/homework-3x3.json")
    data = json.loads(
        Path("solutions/homework-3x3.json").read_text(encoding="utf-8")
    )
    assert [len(r) for r in data["reels"]] == [3, 10, 16]
    report = verify(spec, ReelConfig(**data), mc_spins=200_000)
    assert report.passed, report.render()


# --------------------------------------------------------------------------
# search: bounds, generation, pruning
# --------------------------------------------------------------------------


def test_lower_bounds_are_guaranteed_by_generation_not_by_rejection():
    import random

    spec = coverage_spec(each_reel_all_symbols=True)
    bounds = coverage_lower_bounds(spec)
    rng = random.Random(0)
    for _ in range(200):
        strip = _run_composition(rng, sorted(spec.symbols), 9, bounds)
        assert len(strip) == 9
        assert set(strip) == set(spec.symbols)


def test_generation_refuses_bounds_that_cannot_fit():
    import random

    with pytest.raises(ValueError, match="lower bounds need"):
        _run_composition(random.Random(0), [0, 1, 2], 2, {0: 1, 1: 1, 2: 1})


def test_length_tuples_below_the_coverage_floor_are_pruned():
    spec = coverage_spec(each_reel_all_symbols=True)
    options = SolverOptions(min_len=3, max_len=8)
    tuples = list(candidate_length_tuples(spec, options))
    assert tuples, "coverage must not prune the space empty"
    assert all(all(n >= len(spec.symbols) for n in t) for t in tuples)


def test_affordable_core_excludes_symbols_that_break_the_win_rate():
    """RTP/min_win_rate caps the average win at 19/11 -> 34.5 payout units.
    Symbols 3 (60 units) and 4 (100) exceed it and cannot dominate a reel."""
    spec = coverage_spec(each_reel_all_symbols=True)
    affordable = affordable_core_symbols(spec)
    assert 3 not in affordable and 4 not in affordable
    assert affordable[0] == 2, "the dearest affordable symbol should come first"


def test_no_win_rate_floor_means_every_symbol_is_an_affordable_core():
    raw = json.loads(Path("configs/homework-3x3.json").read_text(encoding="utf-8"))
    raw["targets"] = {"rtp": 0.95}
    spec = GameSpec.model_validate(raw)
    assert affordable_core_symbols(spec) == sorted(spec.symbols)


# --------------------------------------------------------------------------
# solve statuses
# --------------------------------------------------------------------------


def test_solve_reports_proven_feasible_with_a_config():
    spec = load_spec("configs/homework-3x3.json")
    outcome = solve_with_status(spec, SolverOptions(seed=500))
    assert outcome.status is SolveStatus.PROVEN_FEASIBLE
    assert outcome.config is not None


def test_solve_finds_a_per_reel_covering_configuration():
    spec = load_spec("configs/homework-3x3-per-reel-coverage.json")
    outcome = solve_with_status(spec, SolverOptions(seed=500))
    assert outcome.status is SolveStatus.PROVEN_FEASIBLE, outcome.render()
    config = outcome.config
    assert config is not None
    assert all(not m for m in missing_symbols_per_reel(spec, config.reels))
    assert exact_rtp(config.metrics) == spec.targets.rtp
    assert exact_win_rate(config.metrics) >= spec.targets.min_win_rate


def test_an_exhausted_budget_is_never_reported_as_infeasible():
    """The distinction the whole status enum exists for."""
    spec = load_spec("configs/homework-3x3.json")
    outcome = solve_with_status(
        spec, SolverOptions(seed=3, max_seeds=1, max_candidates=1)
    )
    assert outcome.status is SolveStatus.HEURISTIC_EXHAUSTED
    assert outcome.config is None
    text = outcome.render()
    assert "budget" in text
    assert "infeasible" not in text


def test_a_coverage_floor_above_max_len_is_bounded_not_proven():
    """A length bound is a configuration choice, so it can only ever justify
    a bounded claim -- raising max_len may well fix it."""
    spec = coverage_spec(each_reel_all_symbols=True)
    finding = precheck(spec, 3, 4)  # 5 symbols cannot fit on a length-4 reel
    assert finding.status is SolveStatus.BOUNDED_EXHAUSTED
    assert any(
        d.code == "minimum_reel_length_exceeds_bound" for d in finding.diagnostics
    )


def test_a_zero_payout_symbol_blocks_winning_coverage_at_every_length():
    raw = json.loads(Path("configs/homework-3x3.json").read_text(encoding="utf-8"))
    raw["symbols"]["0"] = 0
    raw["coverage"] = {"symbol_pattern": "winning"}
    spec = GameSpec.model_validate(raw)
    finding = precheck(spec, 3, 16)
    assert finding.status is SolveStatus.PROVEN_INFEASIBLE
    assert any(d.code == "non_positive_paytable_entry" for d in finding.diagnostics)


# --------------------------------------------------------------------------
# bounded exhaustive proof
# --------------------------------------------------------------------------


def test_ideal_symbol_pattern_coverage_is_bounded_infeasible_up_to_16():
    """FULL needs a cyclic run of 3 per symbol on every reel, so a reel needs
    >= 15 positions and only lengths 15 and 16 remain under max_len=16. Every
    realizable strip is enumerated exactly; none reaches the targets."""
    spec = coverage_spec(each_reel_all_symbols=True, symbol_pattern="raw")
    result = prove_bounded_coverage_infeasible(spec, 3, 16)
    assert result.status is SolveStatus.BOUNDED_EXHAUSTED
    assert result.lengths_considered == (15, 16)
    assert result.histogram_combinations == 343
    assert result.best_win_rate_at_exact_rtp is None
    assert "not about longer reels" in result.detail


def test_the_bounded_proof_never_claims_more_than_it_proved():
    spec = coverage_spec(each_reel_all_symbols=True, symbol_pattern="raw")
    detail = prove_bounded_coverage_infeasible(spec, 3, 16).detail
    assert "under reel length bounds" in detail
    assert "mathematically impossible" not in detail


def test_solve_upgrades_ideal_coverage_to_a_bounded_proof():
    spec = coverage_spec(each_reel_all_symbols=True, symbol_pattern="raw")
    outcome = solve_with_status(spec, SolverOptions(seed=1, max_len=16))
    assert outcome.status is SolveStatus.BOUNDED_EXHAUSTED
    assert outcome.attempts == 0, "no sampling should happen once it is decided"


def test_bounded_prover_declines_rather_than_guessing_on_gapped_masks():
    """A non-contiguous column footprint breaks the block decomposition, so
    the prover must return UNKNOWN instead of enumerating the wrong set."""
    raw = json.loads(Path("configs/homework-3x3.json").read_text(encoding="utf-8"))
    raw["patterns"] = [
        {"name": "GAP", "cells": [[0, 0], [0, 2], [1, 0], [1, 2], [2, 0], [2, 2]]}
    ]
    raw["coverage"] = {"symbol_pattern": "raw"}
    spec = GameSpec.model_validate(raw)
    result = prove_bounded_coverage_infeasible(spec, 3, 16)
    assert result.status is SolveStatus.UNKNOWN
    assert "contiguous" in result.detail


def test_symbol_pattern_gate_reports_the_structural_reason():
    spec = coverage_spec(symbol_pattern="raw")
    report = verify(spec, config_for(PER_REEL_REELS, spec), mc_spins=20_000)
    gate = next(g for g in report.gates if g.name == "symbol_pattern_coverage")
    assert not gate.passed
    # every reel holds every symbol, yet only symbol 2 can complete a pattern
    assert "never reaches raw coverage" in gate.detail
    covered = {
        e.symbol
        for e in cross_check_coverage(spec, PER_REEL_REELS).entries
        if e.covers("raw")
    }
    assert covered == {2}


# --------------------------------------------------------------------------
# the golden fixtures stay exactly as they were
# --------------------------------------------------------------------------


def test_golden_fixtures_keep_their_deliberate_symbol_gaps():
    """B and C are load-bearing for the all_symbols_used tests. Nothing in the
    coverage work may quietly 'complete' them."""
    assert {s for r in GOLDEN[0].reels for s in r} == {0, 1, 2, 3, 4}
    assert {s for r in GOLDEN[1].reels for s in r} == {0, 2, 3}
    assert {s for r in GOLDEN[2].reels for s in r} == {1, 2, 3, 4}
