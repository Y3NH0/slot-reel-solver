import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("scripts/hooks").resolve()))
import verify_on_write  # noqa: E402

from slotmath.evaluation import naive
from slotmath.models.metrics import build_metrics
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
    code, err = verify_on_write.main(payload("src/slotmath/evaluation/engine.py"))
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


def test_directory_path_exits_two_not_traceback(tmp_path):
    target = tmp_path / "solutions"
    target.mkdir()
    adir = target / "adir.json"
    adir.mkdir()
    code, err = verify_on_write.main(payload(adir))
    assert code == 2
    assert "Traceback" not in err
    assert str(adir) in err


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_hook_runs_as_a_subprocess_through_the_configured_command():
    """The 13 other tests in this file all call verify_on_write.main()
    directly, which never exercises the actual command string configured in
    .claude/settings.json -- that command is what really runs on every
    write. Finding 1 was exactly this gap: the configured command
    ('python3 scripts/hooks/verify_on_write.py') pointed at a pyenv shim
    with no slotmath installed, so every real hook invocation died with
    ModuleNotFoundError before any of main()'s logic ran, and none of the
    in-process tests could ever have caught it. Run the literal configured
    command as a subprocess and confirm it actually works."""
    settings = json.loads((REPO_ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    command = command.replace("${CLAUDE_PROJECT_DIR}", str(REPO_ROOT))
    result = subprocess.run(
        command,
        shell=True,
        cwd=str(REPO_ROOT),
        input=payload(REPO_ROOT / "configs/homework-3x3.json"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr


def test_hook_degrades_readably_when_the_evaluation_stack_cannot_import():
    """Deterministically reproduces 'the hook's interpreter lacks slotmath'
    without depending on any particular system python3's site-packages:
    running under -S disables site-packages initialisation entirely, so the
    lazily-imported pydantic/slotmath fail exactly the way they would under
    a bare interpreter. main() must turn that into a readable exit-2
    message, per finding 1's fix, not let a raw traceback escape."""
    result = subprocess.run(
        [sys.executable, "-S", str(REPO_ROOT / "scripts/hooks/verify_on_write.py")],
        cwd=str(REPO_ROOT),
        input=payload(REPO_ROOT / "configs/homework-3x3.json"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "slotmath" in result.stderr.lower()


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permission bits are not enforceable on Windows or as root",
)
def test_unreadable_file_exits_two_not_traceback(tmp_path):
    target = tmp_path / "solutions"
    target.mkdir()
    bad = target / "unreadable.json"
    bad.write_text('{"a": 1}', encoding="utf-8")
    bad.chmod(0)
    try:
        code, err = verify_on_write.main(payload(bad))
        assert code == 2
        assert "Traceback" not in err
        assert str(bad) in err
    finally:
        bad.chmod(stat.S_IRUSR | stat.S_IWUSR)
