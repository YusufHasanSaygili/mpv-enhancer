"""Parse external local-file drops at the Qt UI boundary."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMimeData

from mpv_enhancer.domain.validation import (
    SUPPORTED_MEDIA_POLICY,
    SupportedExtensionPolicy,
)


@dataclass(frozen=True, slots=True)
class ExternalFileDrop:
    """Supported local files and the number of rejected MIME entries."""

    accepted_paths: tuple[Path, ...]
    rejected_count: int


def parse_external_file_drop(
    mime_data: QMimeData,
    policy: SupportedExtensionPolicy = SUPPORTED_MEDIA_POLICY,
) -> ExternalFileDrop:
    """Keep supported local files in URL order and count all other URLs."""
    if not mime_data.hasUrls():
        return ExternalFileDrop((), 0)

    accepted_paths: list[Path] = []
    rejected_count = 0
    for url in mime_data.urls():
        if not url.isLocalFile():
            rejected_count += 1
            continue
        path = Path(url.toLocalFile())
        if not path.is_file() or not policy.supports(path):
            rejected_count += 1
            continue
        accepted_paths.append(path)

    return ExternalFileDrop(tuple(accepted_paths), rejected_count)
