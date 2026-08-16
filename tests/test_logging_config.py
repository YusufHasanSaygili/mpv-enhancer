import json
from pathlib import Path

from mpv_enhancer.infrastructure.logging_config import (
    configure_logging,
    shutdown_logging,
)
from mpv_enhancer.infrastructure.paths import AppDataPaths


def test_normal_log_redacts_full_media_path(tmp_path: Path) -> None:
    paths = _test_paths(tmp_path)
    logger = configure_logging(paths, logger_name="mpv_enhancer.test.redaction")
    media_path = tmp_path / "Private Videos" / "Family Holiday.mkv"

    logger.info("media_opened path=%s", str(media_path))
    shutdown_logging(logger)

    log_text = (paths.log_dir / "mpv-enhancer.log").read_text(encoding="utf-8")
    payload = json.loads(log_text)
    assert str(media_path) not in log_text
    assert media_path.name not in log_text
    assert payload["message"] == "media_opened path=<redacted-path>"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "mpv_enhancer.test.redaction"


def test_logger_rotates_bounded_log_files(tmp_path: Path) -> None:
    paths = _test_paths(tmp_path)
    logger = configure_logging(
        paths,
        logger_name="mpv_enhancer.test.rotation",
        max_bytes=256,
        backup_count=2,
    )

    for index in range(30):
        logger.info("rotation_event index=%d payload=%s", index, "x" * 48)
    shutdown_logging(logger)

    assert (paths.log_dir / "mpv-enhancer.log").is_file()
    assert (paths.log_dir / "mpv-enhancer.log.1").is_file()
    assert len(list(paths.log_dir.glob("mpv-enhancer.log*"))) <= 3


def _test_paths(tmp_path: Path) -> AppDataPaths:
    return AppDataPaths.from_roots(
        data_root=tmp_path / "data-root",
        local_root=tmp_path / "local-root",
    )
