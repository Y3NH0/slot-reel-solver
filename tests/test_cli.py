import json
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
