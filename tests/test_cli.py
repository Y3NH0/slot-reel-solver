import json
import os
import stat

import pytest

from slotmath.evaluation import naive
from slotmath.cli import main
from slotmath.models.metrics import build_metrics
from tests.fixtures import GOLDEN
from tests.test_naive import hw

MC = ["--mc-spins", "20000"]


def write_config(tmp_path, g, spec_path, **over):
    spec = hw()
    metrics = build_metrics(spec, naive.evaluate(spec, g.reels))
    data = {
        "spec": str(spec_path),
        "reels": g.reels,
        "metrics": json.loads(metrics.model_dump_json()),
    }
    data.update(over)
    path = tmp_path / "sol.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_spec_subcommand_validates_and_reports(capsys):
    assert main(["spec", "configs/homework-3x3.json"]) == 0
    out = capsys.readouterr().out
    assert "payout_unit_denominator" in out and "20" in out


def test_spec_subcommand_returns_2_on_missing_file(capsys):
    assert main(["spec", "configs/nope.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_spec_subcommand_returns_2_on_malformed_json(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["spec", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "invalid JSON" in err


def test_spec_subcommand_returns_2_on_directory_path(tmp_path, capsys):
    assert main(["spec", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert str(tmp_path) in err


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permission bits are not enforceable on Windows or as root",
)
def test_spec_subcommand_returns_2_on_unreadable_file(tmp_path, capsys):
    bad = tmp_path / "unreadable.json"
    bad.write_text('{"a": 1}', encoding="utf-8")
    bad.chmod(0)
    try:
        assert main(["spec", str(bad)]) == 2
        err = capsys.readouterr().err
        assert "Traceback" not in err
        assert str(bad) in err
    finally:
        bad.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_main_returns_2_for_unknown_subcommand(capsys):
    assert main(["bogus-subcommand"]) == 2


def test_verify_returns_0_for_a_golden_config(tmp_path, capsys):
    # Fixture A: the only golden fixture using all five declared symbols (B
    # and C each omit one -- see tests/test_verify.py), so it's the one that
    # passes the all_symbols_used gate and every other gate outright.
    cfg = write_config(tmp_path, GOLDEN[0], "configs/homework-3x3.json")
    assert main(["verify", str(cfg), *MC]) == 0
    assert "PASS" in capsys.readouterr().out


def test_verify_returns_1_for_a_failing_config(tmp_path, capsys):
    cfg = write_config(tmp_path, GOLDEN[2], "configs/homework-3x3.json")
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["metrics"]["spin_count"] += 1
    cfg.write_text(json.dumps(data), encoding="utf-8")
    assert main(["verify", str(cfg), *MC]) == 1


def test_verify_returns_2_when_referenced_spec_is_missing(tmp_path):
    cfg = write_config(tmp_path, GOLDEN[2], tmp_path / "missing.json")
    assert main(["verify", str(cfg), *MC]) == 2


def test_report_prints_payout_table(tmp_path, capsys):
    cfg = write_config(tmp_path, GOLDEN[2], "configs/homework-3x3.json")
    assert main(["report", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "19/20" in out
    assert "474" in out and "42" in out


def test_report_refuses_an_oversized_artifact_instead_of_grinding(tmp_path, capsys):
    """`report` recomputes from the reels (finding 2's fix), which made it a
    full enumeration -- naive.evaluate -- with no bound of its own. A
    regression from that fix: report on an artifact whose board size is
    prod(len(reel)) = 200**3 = 8_000_000 (over the shared NAIVE_BUDGET of
    5_000_000) used to take ~15s; it must now refuse immediately instead.
    The reels here are just three length-200 lists of a declared symbol --
    building them is instant; it is *enumerating their cross product* that
    the old code did unboundedly and the new guard refuses before it ever
    starts, so this test stays fast."""
    spec = hw()
    reels = [[0] * 200 for _ in range(3)]
    metrics = build_metrics(spec, naive.evaluate(spec, [[0, 0, 0]] * 3))
    data = {
        "spec": "configs/homework-3x3.json",
        "reels": reels,
        "metrics": json.loads(metrics.model_dump_json()),
    }
    path = tmp_path / "oversized.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert main(["report", str(path)]) == 2
    err = capsys.readouterr().err
    assert "over the safety budget" in err
    assert "Traceback" not in err


# --------------------------------------------------------------------------
# coverage and feasibility subcommands
# --------------------------------------------------------------------------


def test_coverage_command_prints_exact_counts(capsys):
    code = main(
        [
            "coverage",
            "configs/homework-3x3.json",
            "solutions/homework-3x3-per-reel-coverage.json",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "spin_count: 2400" in out
    assert "raw: 5/25 pairs covered" in out


def test_coverage_command_emits_json_with_fraction_probabilities(capsys):
    import json as _json

    code = main(
        [
            "coverage",
            "configs/homework-3x3.json",
            "solutions/homework-3x3-per-reel-coverage.json",
            "--json",
        ]
    )
    assert code == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["spin_count"] == 2400
    entry = next(
        e for e in payload["entries"] if e["symbol"] == 2 and e["pattern"] == "FULL"
    )
    # probabilities are exact rationals rendered as strings, never floats
    assert "/" in entry["raw_probability"] or entry["raw_probability"] == "0"


def test_coverage_command_exits_1_when_a_required_tier_is_unmet(capsys):
    code = main(
        [
            "coverage",
            "configs/homework-3x3.json",
            "solutions/homework-3x3-per-reel-coverage.json",
            "--require",
            "raw",
        ]
    )
    assert code == 1


def test_feasibility_reports_a_bounded_proof_not_an_impossibility(tmp_path, capsys):
    import json as _json
    from pathlib import Path as _Path

    raw = _json.loads(
        _Path("configs/homework-3x3.json").read_text(encoding="utf-8")
    )
    raw["coverage"] = {"each_reel_all_symbols": True, "symbol_pattern": "raw"}
    spec_path = tmp_path / "ideal.json"
    spec_path.write_text(_json.dumps(raw), encoding="utf-8")

    code = main(["feasibility", str(spec_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "bounded_exhausted" in out
    assert "under reel length bounds" in out
    assert "mathematically impossible" not in out


def test_solve_failure_explains_which_kind_of_failure_it_was(tmp_path, capsys):
    code = main(
        [
            "solve",
            "configs/homework-3x3.json",
            "--max-seeds",
            "1",
            "--max-candidates",
            "1",
            "--seed",
            "3",
        ]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "heuristic_exhausted" in err
    assert "not about existence" in err


def test_explore_runs_a_real_solve_round(tmp_path, capsys):
    """Regression: explore has its own solver call site, and a change to the
    one in `solve` once left this path referencing a name it no longer
    imported. Only an end-to-end round catches that."""
    portfolio = tmp_path / "portfolio.json"
    code = main(
        [
            "explore",
            "configs/homework-3x3.json",
            "--seed",
            "1",
            "--rounds",
            "1",
            "--portfolio",
            str(portfolio),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert portfolio.exists()
    assert "round 0" in out
