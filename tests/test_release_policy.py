import subprocess
import sys
import tomllib
from pathlib import Path

from mpv_enhancer import __version__

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_v05_release_version_is_consistent() -> None:
    configuration = tomllib.loads(_read("pyproject.toml"))

    assert __version__ == "0.5.0"
    assert configuration["project"]["version"] == __version__


def test_v05_release_documentation_exists() -> None:
    changelog = _read("CHANGELOG.md")
    release_notes = _read("docs/releases/v0.5.md")

    assert "## [0.5.0] - 2026-08-20" in changelog
    assert "S05-T01" in release_notes
    assert "S05-T08" in release_notes
    assert "Episode 6" in release_notes
    assert "Episode 7" in release_notes
    assert "tr,tur,en" in release_notes
    assert "es,spa,en" in release_notes
    assert "no-leak" in release_notes
    assert "language" in release_notes


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
        "workflow_dispatch",
        "RELEASE_TAG",
        "verification-tooling",
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
        "verification-tooling",
        "Out-File",
    )
    for fragment in required_fragments:
        assert fragment in workflow


def test_public_tag_matches_the_release_version() -> None:
    script = REPOSITORY_ROOT / "scripts" / "release_version.py"

    valid = subprocess.run(
        [sys.executable, str(script), "v0.5"],
        check=False,
        capture_output=True,
        text=True,
    )
    invalid = subprocess.run(
        [sys.executable, str(script), "v0.4"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert valid.returncode == 0
    assert invalid.returncode == 1
    assert "expected 'v0.5'" in invalid.stderr


def test_release_smoke_covers_queue_settings_and_playback_workflows() -> None:
    smoke_test = _read("scripts/release_smoke.py")

    required_fragments = (
        "QUEUE_SMOKE_FILE_COUNT = 20",
        "dropEvent",
        "select_item_ids",
        "SETTING_SMOKE_SELECTED_EPISODES = (2, 4, 6)",
        '"speedControl"',
        '"panscanControl"',
        "SelectedSettingState.MIXED",
        "_verify_no_leak_playback_settings",
        "_verify_multilingual_track_selection",
        'LanguagePreferences.parse("tr,tur,en")',
        'LanguagePreferences.parse("es,spa,en")',
        "move_item",
        "undo_stack.undo",
        "- snow's 雪.wav",
        "progress_slider",
        "--mpv",
    )
    for fragment in required_fragments:
        assert fragment in smoke_test
    assert "play_pause_button.text()" not in smoke_test


def test_multilingual_fixture_generator_is_synthetic_and_shell_free() -> None:
    generator = _read("scripts/generate_multilingual_fixtures.py")

    for fragment in (
        'FixtureSpec("episode-06.mkv", ("eng", "tur"))',
        'FixtureSpec("episode-07.mkv", ("eng", "spa"))',
        '"color=c=black:s=320x180:r=24:d=2"',
        '"language=eng"',
        "subprocess.run(command, check=True, shell=False)",
    ):
        assert fragment in generator
