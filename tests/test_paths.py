from pathlib import Path

from mpv_enhancer.infrastructure.paths import AppDataPaths


def test_windows_runtime_paths_use_appdata_roots(tmp_path: Path) -> None:
    roaming_root = tmp_path / "roaming"
    local_root = tmp_path / "local"

    paths = AppDataPaths.for_current_user(
        environment={
            "APPDATA": str(roaming_root),
            "LOCALAPPDATA": str(local_root),
        },
        platform="win32",
        home=tmp_path / "home",
    )

    assert paths.data_dir == roaming_root / "MPV Enhancer"
    assert paths.autosave_dir == paths.data_dir / "Autosaves"
    assert paths.cache_dir == local_root / "MPV Enhancer" / "Cache"
    assert paths.log_dir == local_root / "MPV Enhancer" / "Logs"
    assert paths.crash_dump_dir == local_root / "MPV Enhancer" / "CrashReports"


def test_runtime_directories_are_created(tmp_path: Path) -> None:
    paths = AppDataPaths.from_roots(
        data_root=tmp_path / "data-root",
        local_root=tmp_path / "local-root",
    )

    paths.ensure_directories()

    for directory in paths.runtime_directories:
        assert directory.is_dir()


def test_default_runtime_paths_are_outside_the_repository() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    paths = AppDataPaths.for_current_user()

    assert all(
        not directory.is_relative_to(repository_root)
        for directory in paths.runtime_directories
    )
