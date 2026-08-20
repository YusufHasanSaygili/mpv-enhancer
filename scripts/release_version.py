"""Validate that a release tag matches the public package version."""

import sys
from collections.abc import Sequence

from mpv_enhancer import __version__


def expected_tag(version: str) -> str:
    """Return the immutable public tag for a three-part package version."""
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("Release versions must contain three numeric parts.")
    major, minor, patch = parts
    if patch == "0":
        return f"v{major}.{minor}"
    return f"v{major}.{minor}.{patch}"


def main(argv: Sequence[str] | None = None) -> int:
    """Return success only when the supplied tag matches the package version."""
    arguments = list(argv if argv is not None else sys.argv[1:])
    if len(arguments) != 1:
        print("Usage: release_version.py <tag>", file=sys.stderr)
        return 2

    actual_tag = arguments[0]
    required_tag = expected_tag(__version__)
    if actual_tag != required_tag:
        print(
            f"Tag {actual_tag!r} does not match version {__version__!r}; "
            f"expected {required_tag!r}.",
            file=sys.stderr,
        )
        return 1
    print(f"Validated release {actual_tag} for package version {__version__}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
