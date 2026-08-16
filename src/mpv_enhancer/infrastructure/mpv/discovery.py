"""Safe mpv executable discovery and version validation."""

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

MPV_PATH_ENVIRONMENT_VARIABLE = "MPV_ENHANCER_MPV_PATH"
_VERSION_PATTERN = re.compile(r"^mpv(?:\.exe)?\s+v?([^\s]+)", re.IGNORECASE)


class MpvDiagnosticsStatus(StrEnum):
    """Outcome of executable discovery and validation."""

    AVAILABLE = "available"
    NOT_FOUND = "not_found"
    INVALID = "invalid"


class MpvDiscoverySource(StrEnum):
    """Source that supplied an mpv executable candidate."""

    SELECTED = "selected"
    ENVIRONMENT = "environment"
    PATH = "path"
    STANDARD = "standard"


@dataclass(frozen=True, slots=True)
class MpvValidationResult:
    """Result of probing one executable candidate."""

    is_valid: bool
    version: str | None
    error: str | None

    @classmethod
    def valid(cls, version: str) -> "MpvValidationResult":
        return cls(is_valid=True, version=version, error=None)

    @classmethod
    def invalid(cls, error: str) -> "MpvValidationResult":
        return cls(is_valid=False, version=None, error=error)


@dataclass(frozen=True, slots=True)
class MpvDiagnostics:
    """UI-safe summary of mpv discovery without command output or logs."""

    status: MpvDiagnosticsStatus
    source: MpvDiscoverySource | None
    executable: Path | None
    version: str | None
    message: str

    @property
    def is_available(self) -> bool:
        return self.status is MpvDiagnosticsStatus.AVAILABLE


class MpvDiscoverer(Protocol):
    """Interface consumed by the Preferences UI."""

    def discover(self, selected_path: Path | None = None) -> MpvDiagnostics: ...


MpvValidator = Callable[[Path], MpvValidationResult]
ExecutableFinder = Callable[[str, str | None], str | None]


class MpvDiscoveryService:
    """Discover the first valid mpv executable in the documented order."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        which: ExecutableFinder | None = None,
        validator: MpvValidator | None = None,
        standard_candidates: Sequence[Path] | None = None,
    ) -> None:
        self._environment = dict(os.environ if environment is None else environment)
        self._which = _find_on_path if which is None else which
        self._validator = validate_mpv_executable if validator is None else validator
        self._standard_candidates = tuple(
            _standard_install_candidates(self._environment)
            if standard_candidates is None
            else standard_candidates
        )

    def discover(self, selected_path: Path | None = None) -> MpvDiagnostics:
        first_invalid: MpvDiagnostics | None = None
        seen: set[str] = set()

        for source, candidate in self._candidates(selected_path):
            executable = candidate.expanduser().resolve()
            identity = os.path.normcase(str(executable))
            if identity in seen:
                continue
            seen.add(identity)

            if executable.is_file():
                validation = self._validator(executable)
            else:
                validation = MpvValidationResult.invalid(
                    "The configured executable does not exist."
                )

            if validation.is_valid:
                version = validation.version or "unknown"
                return MpvDiagnostics(
                    status=MpvDiagnosticsStatus.AVAILABLE,
                    source=source,
                    executable=executable,
                    version=version,
                    message=f"mpv {version} is ready.",
                )
            if first_invalid is None:
                first_invalid = MpvDiagnostics(
                    status=MpvDiagnosticsStatus.INVALID,
                    source=source,
                    executable=executable,
                    version=None,
                    message=(
                        "The configured mpv executable is not valid. "
                        "Open Preferences and choose a working mpv.exe."
                    ),
                )

        if first_invalid is not None:
            return first_invalid
        return MpvDiagnostics(
            status=MpvDiagnosticsStatus.NOT_FOUND,
            source=None,
            executable=None,
            version=None,
            message=(
                "mpv was not found. Install mpv or open Preferences and choose mpv.exe."
            ),
        )

    def _candidates(
        self,
        selected_path: Path | None,
    ) -> Sequence[tuple[MpvDiscoverySource, Path]]:
        candidates: list[tuple[MpvDiscoverySource, Path]] = []
        if selected_path is not None:
            candidates.append((MpvDiscoverySource.SELECTED, selected_path))

        environment_path = self._environment.get(MPV_PATH_ENVIRONMENT_VARIABLE)
        if environment_path:
            candidates.append((MpvDiscoverySource.ENVIRONMENT, Path(environment_path)))

        path_match = self._which("mpv.exe", self._environment.get("PATH"))
        if path_match:
            candidates.append((MpvDiscoverySource.PATH, Path(path_match)))

        candidates.extend(
            (MpvDiscoverySource.STANDARD, path) for path in self._standard_candidates
        )
        return candidates


def validate_mpv_executable(executable: Path) -> MpvValidationResult:
    """Launch an executable without a shell and verify its mpv version output."""
    resolved = executable.expanduser().resolve()
    if not resolved.is_file():
        return MpvValidationResult.invalid("The executable does not exist.")

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [str(resolved), "--version"],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return MpvValidationResult.invalid(
            f"The version probe failed: {type(error).__name__}."
        )

    output = completed.stdout.strip() or completed.stderr.strip()
    first_line = output.splitlines()[0] if output else ""
    match = _VERSION_PATTERN.match(first_line)
    if completed.returncode != 0 or match is None:
        return MpvValidationResult.invalid(
            "The executable did not return a valid mpv version."
        )
    return MpvValidationResult.valid(match.group(1))


def _find_on_path(command: str, search_path: str | None) -> str | None:
    return shutil.which(command, path=search_path)


def _standard_install_candidates(environment: Mapping[str, str]) -> tuple[Path, ...]:
    candidates: list[Path] = []
    program_files = environment.get("ProgramFiles")
    if program_files:
        candidate = Path(program_files) / "mpv" / "mpv.exe"
        if candidate.is_file():
            candidates.append(candidate)
    local_app_data = environment.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Programs" / "mpv" / "mpv.exe"
        if candidate.is_file():
            candidates.append(candidate)
    return tuple(candidates)
