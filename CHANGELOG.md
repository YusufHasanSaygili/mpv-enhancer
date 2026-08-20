# Changelog

All notable changes to MPV Enhancer are documented in this file. The project
uses public minor release tags such as `v0.1`; the Python package uses the
corresponding three-part version such as `0.1.0`.

## [Unreleased]

## [0.1.1] - 2026-08-20

### Fixed

- Excluded unshipped hidden build metadata from the public checksum manifest so
  every listed file can be downloaded and verified.

This recovery patch changes release metadata and verification only. Application
behavior is identical to v0.1.

## [0.1.0] - 2026-08-20

### Added

- Public MIT-licensed repository foundation and contributor-safe governance.
- Python 3.12 and PySide6 application bootstrap with a three-region English
  desktop shell.
- Windows application-data paths and rotating structured logs with absolute
  path redaction.
- Safe, shell-free mpv discovery with persistent executable preferences and an
  actionable missing-mpv diagnostics dialog.
- Local formatting, linting, strict typing, test coverage, and secret checks.
- Required Windows CI, Dependabot configuration, and a tag-driven pre-release
  workflow with dependency audit, SBOM, checksums, and public-asset smoke test.

[Unreleased]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.1...v0.1.1
[0.1.0]: https://github.com/YusufHasanSaygili/mpv-enhancer/releases/tag/v0.1
