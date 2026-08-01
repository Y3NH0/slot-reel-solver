import json
import os
import stat

import pytest

from slotmath import naive
from slotmath.cli import main
from slotmath.metrics import build_metrics
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
    cfg = write_config(tmp_path, GOLDEN[2], "configs/homework-3x3.json")
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
