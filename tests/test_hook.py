import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("scripts/hooks").resolve()))
import verify_on_write  # noqa: E402

from slotmath import naive
from slotmath.metrics import build_metrics
from tests.fixtures import GOLDEN
from tests.test_naive import hw


def payload(path):
    return json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(path)}})


def write_solution(tmp_path, g, **mutate):
    spec = hw()
    metrics = build_metrics(spec, naive.evaluate(spec, g.reels))
    data = {
        "spec": "configs/homework-3x3.json",
        "reels": g.reels,
        "metrics": json.loads(metrics.model_dump_json()),
    }
    for key, value in mutate.items():
        data["metrics"][key] = value
    target = tmp_path / "solutions"
    target.mkdir(exist_ok=True)
    path = target / "s.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_unrelated_path_exits_zero_silently():
    code, err = verify_on_write.main(payload("src/slotmath/engine.py"))
    assert code == 0 and err == ""


def test_unrelated_json_outside_watched_dirs_exits_zero():
    code, err = verify_on_write.main(payload("notes/scratch.json"))
    assert code == 0 and err == ""


def test_missing_file_path_in_payload_exits_zero():
    code, err = verify_on_write.main(json.dumps({"tool_name": "Write", "tool_input": {}}))
    assert code == 0 and err == ""


def test_valid_gamespec_exits_zero(capsys):
    code, err = verify_on_write.main(payload("configs/homework-3x3.json"))
    assert code == 0, err


def test_good_solution_exits_zero(tmp_path):
    path = write_solution(tmp_path, GOLDEN[2])
    code, err = verify_on_write.main(payload(path))
    assert code == 0, err


def test_bad_solution_exits_two_with_readable_report(tmp_path):
    path = write_solution(tmp_path, GOLDEN[2], spin_count=999)
    code, err = verify_on_write.main(payload(path))
    assert code == 2
    assert "file_consistency" in err
    assert "Traceback" not in err


def test_malformed_json_gives_a_message_not_a_traceback(tmp_path):
    target = tmp_path / "solutions"
    target.mkdir()
    path = target / "s.json"
    path.write_text("{ broken", encoding="utf-8")
    code, err = verify_on_write.main(payload(path))
    assert code == 2
    assert "invalid JSON" in err
    assert "Traceback" not in err


def test_hook_never_modifies_the_file(tmp_path):
    path = write_solution(tmp_path, GOLDEN[2], spin_count=999)
    before = path.read_bytes()
    verify_on_write.main(payload(path))
    assert path.read_bytes() == before
