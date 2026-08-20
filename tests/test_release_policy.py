import subprocess
import sys
import tomllib
from pathlib import Path

from mpv_enhancer import __version__

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_v03_release_version_is_consistent() -> None:
    configuration = tomllib.loads(_read("pyproject.toml"))

    assert __version__ == "0.3.0"
    assert configuration["project"]["version"] == __version__


def test_v03_release_documentation_exists() -> None:
    changelog = _read("CHANGELOG.md")
    release_notes = _read("docs/releases/v0.3.md")

    assert "## [0.3.0] - 2026-08-20" in changelog
    assert "S03-T01" in release_notes
    assert "S03-T09" in release_notes
    assert "Unicode" in release_notes
    assert "leading-hyphen" in release_notes
    assert "embedded mpv playback" in release_notes


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
        "MPV_TEST_EXE",
        "--mpv",
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
        "MPV_TEST_EXE",
        "--mpv",
        "Out-File",
    )
    for fragment in required_fragments:
        assert fragment in workflow


def test_public_tag_matches_the_release_version() -> None:
    script = REPOSITORY_ROOT / "scripts" / "release_version.py"

    valid = subprocess.run(
        [sys.executable, str(script), "v0.3"],
        check=False,
        capture_output=True,
        text=True,
    )
    invalid = subprocess.run(
        [sys.executable, str(script), "v0.2"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert valid.returncode == 0
    assert invalid.returncode == 1
    assert "expected 'v0.3'" in invalid.stderr


def test_release_smoke_covers_the_twenty_file_queue_workflow() -> None:
    smoke_test = _read("scripts/release_smoke.py")

    required_fragments = (
        "QUEUE_SMOKE_FILE_COUNT = 20",
        "dropEvent",
        "select_item_ids",
        "move_item",
        "undo_stack.undo",
        "- snow's 雪.wav",
        "progress_slider",
        "--mpv",
    )
    for fragment in required_fragments:
        assert fragment in smoke_test
