"""Single-source media extension policy for queue admission."""

from dataclasses import dataclass
from pathlib import Path

DEFAULT_SUPPORTED_MEDIA_EXTENSIONS = frozenset(
    {
        ".3gp",
        ".aac",
        ".ac3",
        ".aiff",
        ".alac",
        ".ape",
        ".avi",
        ".dts",
        ".flac",
        ".flv",
        ".m2ts",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".mts",
        ".ogg",
        ".ogv",
        ".opus",
        ".ts",
        ".vob",
        ".wav",
        ".webm",
        ".wma",
        ".wmv",
    }
)


@dataclass(frozen=True, slots=True)
class SupportedExtensionPolicy:
    """Case-insensitive allowlist for local media file suffixes."""

    extensions: frozenset[str]

    def __post_init__(self) -> None:
        if not self.extensions:
            raise ValueError("The supported extension policy cannot be empty.")
        normalized = frozenset(extension.casefold() for extension in self.extensions)
        if any(
            not extension.startswith(".")
            or len(extension) < 2
            or "/" in extension
            or "\\" in extension
            for extension in normalized
        ):
            raise ValueError("Supported extensions must be dot-prefixed suffixes.")
        object.__setattr__(self, "extensions", normalized)

    def supports(self, path: str | Path) -> bool:
        """Return whether a path has one allowlisted final suffix."""
        return Path(path).suffix.casefold() in self.extensions


SUPPORTED_MEDIA_POLICY = SupportedExtensionPolicy(DEFAULT_SUPPORTED_MEDIA_EXTENSIONS)


def is_supported_media_path(path: str | Path) -> bool:
    """Apply the application-wide queue admission policy to one path."""
    return SUPPORTED_MEDIA_POLICY.supports(path)
