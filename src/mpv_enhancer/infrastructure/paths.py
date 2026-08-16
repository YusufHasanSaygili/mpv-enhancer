"""Application-owned runtime data locations."""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APPLICATION_DIRECTORY_NAME = "MPV Enhancer"


@dataclass(frozen=True, slots=True)
class AppDataPaths:
    """Resolved directories for local data that must stay outside the repository."""

    data_dir: Path
    autosave_dir: Path
    cache_dir: Path
    log_dir: Path
    crash_dump_dir: Path

    @classmethod
    def from_roots(
        cls,
        *,
        data_root: Path,
        local_root: Path,
    ) -> "AppDataPaths":
        """Build application-specific paths from trusted absolute base directories."""
        resolved_data_root = _resolved_root(data_root, Path.home())
        resolved_local_root = _resolved_root(local_root, Path.home())
        data_dir = resolved_data_root / APPLICATION_DIRECTORY_NAME
        local_dir = resolved_local_root / APPLICATION_DIRECTORY_NAME
        return cls(
            data_dir=data_dir,
            autosave_dir=data_dir / "Autosaves",
            cache_dir=local_dir / "Cache",
            log_dir=local_dir / "Logs",
            crash_dump_dir=local_dir / "CrashReports",
        )

    @classmethod
    def for_current_user(
        cls,
        *,
        environment: Mapping[str, str] | None = None,
        platform: str | None = None,
        home: Path | None = None,
    ) -> "AppDataPaths":
        """Resolve platform-appropriate per-user runtime directories."""
        current_environment = os.environ if environment is None else environment
        current_platform = sys.platform if platform is None else platform
        home_dir = (Path.home() if home is None else home).expanduser().resolve()

        if current_platform == "win32":
            data_root = _environment_root(
                current_environment,
                "APPDATA",
                home_dir / "AppData" / "Roaming",
            )
            local_root = _environment_root(
                current_environment,
                "LOCALAPPDATA",
                home_dir / "AppData" / "Local",
            )
        elif current_platform == "darwin":
            data_root = home_dir / "Library" / "Application Support"
            local_root = home_dir / "Library"
        else:
            data_root = _environment_root(
                current_environment,
                "XDG_DATA_HOME",
                home_dir / ".local" / "share",
            )
            local_root = _environment_root(
                current_environment,
                "XDG_CACHE_HOME",
                home_dir / ".cache",
            )

        return cls.from_roots(data_root=data_root, local_root=local_root)

    @property
    def runtime_directories(self) -> tuple[Path, ...]:
        """Return every directory owned and created by the application."""
        return (
            self.data_dir,
            self.autosave_dir,
            self.cache_dir,
            self.log_dir,
            self.crash_dump_dir,
        )

    def ensure_directories(self) -> None:
        """Create all application-owned runtime directories when absent."""
        for directory in self.runtime_directories:
            directory.mkdir(parents=True, exist_ok=True)


def _environment_root(
    environment: Mapping[str, str],
    variable_name: str,
    fallback: Path,
) -> Path:
    value = environment.get(variable_name)
    return _resolved_root(Path(value) if value else fallback, fallback)


def _resolved_root(candidate: Path, fallback: Path) -> Path:
    expanded = candidate.expanduser()
    if not expanded.is_absolute():
        expanded = fallback.expanduser()
    return expanded.resolve()
