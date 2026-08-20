from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_windows_ci_runs_the_complete_gate_and_builds_a_wheel() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "windows-latest" in workflow
    assert "uv sync --extra dev --locked" in workflow
    assert "uv run python scripts/quality.py" in workflow
    assert "uv build --wheel" in workflow


def test_dependabot_covers_python_and_github_actions() -> None:
    configuration = _read(".github/dependabot.yml")

    assert 'package-ecosystem: "pip"' in configuration
    assert 'package-ecosystem: "github-actions"' in configuration


def test_public_contributor_files_exist_and_include_privacy_rules() -> None:
    required_files = (
        "AGENTS.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
    )

    for relative_path in required_files:
        assert (REPOSITORY_ROOT / relative_path).is_file()

    contributor_guide = " ".join(_read("CONTRIBUTING.md").lower().split())
    agent_guide = " ".join(_read("AGENTS.md").lower().split())
    for guide in (contributor_guide, agent_guide):
        assert "personal path" in guide
        assert "private media" in guide
        assert "secret" in guide
