import copy
import pytest

from slotmath import naive
from slotmath.metrics import build_metrics
from slotmath.verify import ReelConfig, verify
from tests.fixtures import GOLDEN
from tests.test_naive import hw

MC = dict(mc_spins=20_000, mc_seed=20260731)


def config_for(g, **over):
    spec = hw()
    metrics = build_metrics(spec, naive.evaluate(spec, g.reels))
    data = {
        "spec": "configs/homework-3x3.json",
        "reels": g.reels,
        "metrics": metrics.model_dump(),
        "solver": {"version": "0.1.0", "seed": 1, "command": "x"},
    }
    data.update(over)
    return ReelConfig.model_validate(data)


@pytest.mark.parametrize("g", GOLDEN, ids=[g.name for g in GOLDEN])
def test_golden_configs_pass_every_gate(g):
    report = verify(hw(), config_for(g), **MC)
    assert report.passed, report.render()


def test_undeclared_symbol_fails():
    g = GOLDEN[2]
    bad = copy.deepcopy(g.reels)
    bad[0][0] = 99
    report = verify(hw(), config_for(g, reels=bad), **MC)
    assert not report.passed
    assert any("undeclared" in gate.detail for gate in report.gates if not gate.passed)


def test_spin_count_not_matching_reel_lengths_fails():
    g = GOLDEN[2]
    cfg = config_for(g)
    cfg.metrics.spin_count += 1
    report = verify(hw(), cfg, **MC)
    assert not report.passed
    assert any(gate.name == "file_consistency" and not gate.passed for gate in report.gates)


def test_combo_counts_not_summing_to_spin_count_fails():
    g = GOLDEN[2]
    cfg = config_for(g)
    cfg.metrics.payout_distribution[0].combo_count += 3
    report = verify(hw(), cfg, **MC)
    assert not report.passed
    assert any(gate.name == "file_consistency" and not gate.passed for gate in report.gates)


def test_stale_metrics_fail_with_recompute_message_not_engine_bug_message():
    """Engines agree with each other but not with the file: that is a stale
    artifact, not a program bug. The two must be reported differently.

    The fabricated distribution shifts one combo between the two *non-zero*
    buckets (20 and 100 units) so the zero bucket -- and therefore
    win_count, which is derived from it -- stays untouched. Running it
    through build_metrics() (rather than hand-editing individual Metrics
    fields) makes every derived float (rtp, volatility, total_payout_units)
    self-consistent with the fabricated counts, so Layer 1's file_consistency
    gate -- which now checks those floats too (see verify.py) -- must NOT
    fire; only the comparison against a fresh recompute from the actual
    reels should fail (Layer 2). Hand-editing total_payout_units alone
    without also updating rtp/volatility would (correctly, post-fix) trip
    file_consistency before Layer 2 is ever reached, conflating a stale
    artifact with a corrupted one -- which is exactly why this test builds a
    self-consistent fabrication instead.
    """
    g = GOLDEN[2]
    spec = hw()
    fabricated = dict(g.distribution)
    fabricated[20] += 1
    fabricated[100] -= 1
    metrics = build_metrics(spec, fabricated)
    cfg = ReelConfig.model_validate({
        "spec": "configs/homework-3x3.json",
        "reels": g.reels,
        "metrics": metrics.model_dump(),
    })
    report = verify(spec, cfg, **MC)
    failed = {gate.name for gate in report.gates if not gate.passed}
    assert "file_consistency" not in failed
    assert "file_matches_recompute" in failed
    assert "engine_matches_naive" not in failed


def test_rtp_off_target_fails_even_when_very_close():
    """0.95042... must fail. No tolerance band exists."""
    spec = hw()
    reels = [
        [4, 4, 4, 3, 3, 2, 2, 2, 2, 0, 0, 0],
        [0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 2, 2],
        [2, 2, 2, 2, 2, 2, 2, 2, 4],
    ]
    metrics = build_metrics(spec, naive.evaluate(spec, reels))
    cfg = ReelConfig.model_validate({
        "spec": "configs/homework-3x3.json",
        "reels": reels,
        "metrics": metrics.model_dump(),
    })
    report = verify(spec, cfg, **MC)
    assert not report.passed
    assert any(gate.name == "rtp_exact" and not gate.passed for gate in report.gates)


def test_win_rate_below_minimum_fails():
    spec = hw()
    reels = [[0, 1, 2], [1, 2, 0], [2, 0, 1]]     # never wins
    metrics = build_metrics(spec, naive.evaluate(spec, reels))
    cfg = ReelConfig.model_validate({
        "spec": "x", "reels": reels, "metrics": metrics.model_dump()
    })
    report = verify(spec, cfg, **MC)
    assert any(gate.name == "min_win_rate" and not gate.passed for gate in report.gates)
    assert report.passed is False


def test_win_rate_of_one_produces_a_warning_but_still_passes():
    """Fixture A: the player never comes up empty. Legal, commercially odd."""
    report = verify(hw(), config_for(GOLDEN[0]), **MC)
    assert report.passed
    assert any(gate.severity == "warn" and not gate.passed for gate in report.gates)


@pytest.mark.parametrize("mutation", [None, "delete", "garbage"])
def test_solver_block_is_non_authoritative(mutation):
    """Deleting or corrupting the solver block must not change the verdict
    bit for bit. See spec 6.3."""
    g = GOLDEN[2]
    baseline = verify(hw(), config_for(g), **MC).model_dump()

    if mutation == "delete":
        cfg = config_for(g, solver=None)
    elif mutation == "garbage":
        cfg = config_for(g, solver={"version": "LIES", "seed": -1, "extra": [1, 2]})
    else:
        cfg = config_for(g)

    assert verify(hw(), cfg, **MC).model_dump() == baseline
