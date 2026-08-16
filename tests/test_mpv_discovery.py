import subprocess
from pathlib import Path

from mpv_enhancer.infrastructure.mpv.discovery import (
    MPV_PATH_ENVIRONMENT_VARIABLE,
    MpvDiagnosticsStatus,
    MpvDiscoveryService,
    MpvDiscoverySource,
    MpvValidationResult,
    validate_mpv_executable,
)


def test_selected_path_has_highest_priority(tmp_path: Path) -> None:
    selected = _executable(tmp_path / "selected" / "mpv.exe")
    environment_path = _executable(tmp_path / "environment" / "mpv.exe")
    path_executable = _executable(tmp_path / "path" / "mpv.exe")
    checked: list[Path] = []
    service = _service(
        environment={MPV_PATH_ENVIRONMENT_VARIABLE: str(environment_path)},
        path_executable=path_executable,
        checked=checked,
    )

    result = service.discover(selected)

    assert result.status is MpvDiagnosticsStatus.AVAILABLE
    assert result.source is MpvDiscoverySource.SELECTED
    assert result.executable == selected.resolve()
    assert checked == [selected.resolve()]


def test_environment_override_precedes_path(tmp_path: Path) -> None:
    environment_path = _executable(tmp_path / "environment" / "mpv.exe")
    path_executable = _executable(tmp_path / "path" / "mpv.exe")
    service = _service(
        environment={MPV_PATH_ENVIRONMENT_VARIABLE: str(environment_path)},
        path_executable=path_executable,
    )

    result = service.discover()

    assert result.source is MpvDiscoverySource.ENVIRONMENT
    assert result.executable == environment_path.resolve()


def test_path_is_used_when_no_override_exists(tmp_path: Path) -> None:
    path_executable = _executable(tmp_path / "path" / "mpv.exe")
    service = _service(
        environment={"PATH": "synthetic"}, path_executable=path_executable
    )

    result = service.discover()

    assert result.status is MpvDiagnosticsStatus.AVAILABLE
    assert result.source is MpvDiscoverySource.PATH
    assert result.executable == path_executable.resolve()


def test_missing_executable_returns_helpful_diagnostics() -> None:
    service = _service(environment={}, path_executable=None)

    result = service.discover()

    assert result.status is MpvDiagnosticsStatus.NOT_FOUND
    assert result.executable is None
    assert "Preferences" in result.message


def test_invalid_selected_executable_is_reported(tmp_path: Path) -> None:
    selected = _executable(tmp_path / "invalid" / "mpv.exe")
    service = MpvDiscoveryService(
        environment={},
        which=lambda _command, _path: None,
        validator=lambda _path: MpvValidationResult.invalid(
            "The executable did not identify itself as mpv."
        ),
        standard_candidates=(),
    )

    result = service.discover(selected)

    assert result.status is MpvDiagnosticsStatus.INVALID
    assert result.source is MpvDiscoverySource.SELECTED
    assert result.executable == selected.resolve()
    assert "not valid" in result.message


def test_validation_launches_version_probe_without_a_shell(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = _executable(tmp_path / "mpv.exe")
    captured: dict[str, object] = {}

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "mpv v0.40.0\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = validate_mpv_executable(executable)

    assert result.is_valid
    assert result.version == "0.40.0"
    assert captured["command"] == [str(executable.resolve()), "--version"]
    assert captured["shell"] is False


def test_validation_rejects_non_mpv_output(tmp_path: Path, monkeypatch) -> None:
    executable = _executable(tmp_path / "mpv.exe")

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "another program\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = validate_mpv_executable(executable)

    assert not result.is_valid
    assert result.version is None


def _service(
    *,
    environment: dict[str, str],
    path_executable: Path | None,
    checked: list[Path] | None = None,
) -> MpvDiscoveryService:
    checked_paths = [] if checked is None else checked

    def validator(path: Path) -> MpvValidationResult:
        checked_paths.append(path)
        return MpvValidationResult.valid("0.40.0")

    return MpvDiscoveryService(
        environment=environment,
        which=lambda _command, _path: (
            str(path_executable) if path_executable is not None else None
        ),
        validator=validator,
        standard_candidates=(),
    )


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic executable", encoding="utf-8")
    return path
