import subprocess
import sys
import tomllib
from pathlib import Path

from mpv_enhancer import __version__

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_v02_release_version_is_consistent() -> None:
    configuration = tomllib.loads(_read("pyproject.toml"))

    assert __version__ == "0.2.0"
    assert configuration["project"]["version"] == __version__


def test_v02_release_documentation_exists() -> None:
    changelog = _read("CHANGELOG.md")
    release_notes = _read("docs/releases/v0.2.md")

    assert "## [0.2.0] - 2026-08-20" in changelog
    assert "S02-T01" in release_notes
    assert "S02-T08" in release_notes
    assert "20 mixed media files" in release_notes
    assert "No media playback" in release_notes


def test_tag_workflow_builds_and_verifies_public_release_assets() -> None:
    workflow = _read(".github/workflows/release.yml")

    required_fragments = (
        "windows-latest",
        '- "v*"',
        "uv run pip-audit",
        "uv export --format cyclonedx1.5",
        "uv build --wheel",
        "gh release create",
        "--draft",
        "gh release edit",
        "--draft=false",
        "--prerelease",
        "gh release download",
        "Get-FileHash",
        "scripts/release_smoke.py",
    )
    for fragment in required_fragments:
        assert fragment in workflow

    assert "gh release upload" not in workflow
    assert "AppendAllLines" not in workflow
    assert "Out-File" in workflow
    assert workflow.count("-not $_.Name.StartsWith('.')") >= 2
    assert (REPOSITORY_ROOT / "scripts" / "release_smoke.py").is_file()


def test_manual_workflow_reverifies_an_immutable_public_release() -> None:
    workflow = _read(".github/workflows/verify-release.yml")

    required_fragments = (
        "workflow_dispatch:",
        "windows-latest",
        "gh release download",
        "Get-FileHash",
        "--require-hashes",
        "scripts/release_smoke.py",
        "Out-File",
    )
    for fragment in required_fragments:
        assert fragment in workflow


def test_public_tag_matches_the_release_version() -> None:
    script = REPOSITORY_ROOT / "scripts" / "release_version.py"

    valid = subprocess.run(
        [sys.executable, str(script), "v0.2"],
        check=False,
        capture_output=True,
        text=True,
    )
    invalid = subprocess.run(
        [sys.executable, str(script), "v0.1.1"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert valid.returncode == 0
    assert invalid.returncode == 1
    assert "expected 'v0.2'" in invalid.stderr


def test_release_smoke_covers_the_twenty_file_queue_workflow() -> None:
    smoke_test = _read("scripts/release_smoke.py")

    required_fragments = (
        "QUEUE_SMOKE_FILE_COUNT = 20",
        "dropEvent",
        "select_item_ids",
        "move_item",
        "undo_stack.undo",
    )
    for fragment in required_fragments:
        assert fragment in smoke_test
