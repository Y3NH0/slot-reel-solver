from pathlib import Path

import pytest

SKILLS = [
    "slot-math-model",
    "reel-strip-solver",
    "slot-config-verifier",
    "slot-solution-explorer",
]


@pytest.mark.parametrize("name", SKILLS)
def test_skill_file_exists(name):
    assert Path(f".claude/skills/{name}/SKILL.md").is_file()


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_frontmatter_with_matching_name(name):
    text = Path(f".claude/skills/{name}/SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    header = text.split("---", 2)[1]
    assert f"name: {name}" in header
    assert "description:" in header


@pytest.mark.parametrize("name", SKILLS)
def test_skill_documents_a_runnable_command(name):
    text = Path(f".claude/skills/{name}/SKILL.md").read_text(encoding="utf-8")
    assert "slotmath " in text


@pytest.mark.parametrize("name", SKILLS)
def test_skill_states_an_output_contract(name):
    text = Path(f".claude/skills/{name}/SKILL.md").read_text(encoding="utf-8")
    assert "Output Contract" in text


def test_no_skill_uses_the_banned_vocabulary():
    """The project renamed these deliberately; drift here causes real bugs."""
    for name in SKILLS:
        text = Path(f".claude/skills/{name}/SKILL.md").read_text(encoding="utf-8")
        assert "hit_rate" not in text
        assert "pattern_bonus" not in text


def test_verifier_skill_states_the_exit_code_contract():
    text = Path(".claude/skills/slot-config-verifier/SKILL.md").read_text(encoding="utf-8")
    for code in ("0", "1", "2"):
        assert code in text
    assert "exit" in text.lower()


def test_solver_skill_records_the_diophantine_limitation():
    text = Path(".claude/skills/reel-strip-solver/SKILL.md").read_text(encoding="utf-8")
    assert "not a closed form" in text or "finite search" in text
