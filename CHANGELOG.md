# Changelog

All notable changes to MPV Enhancer are documented in this file. The project
uses public minor release tags such as `v0.1`; the Python package uses the
corresponding three-part version such as `0.1.0`.

## [Unreleased]

## [0.2.0] - 2026-08-20

### Added

- Ordered queue domain models with stable UUID identity and duplicate-path
  support.
- Explorer file drop with centralized media-extension filtering, insertion
  feedback, and partial rejection messages.
- Internal drag reorder and `Alt+Up`/`Alt+Down` keyboard movement without
  copying item metadata.
- Ctrl/Shift extended selection, Ctrl+A, and an accessible selection summary.
- Selected-item removal, confirmed queue clearing, current-item safeguards,
  and exact Undo/Redo for queue edits.
- Accessible empty-state instructions, drag handles, title elision, and an
  override-status placeholder.
- A clean-environment release smoke test covering a 20-file queue workflow.

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

[Unreleased]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.2...HEAD
[0.2.0]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.1.1...v0.2
[0.1.1]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.1...v0.1.1
[0.1.0]: https://github.com/YusufHasanSaygili/mpv-enhancer/releases/tag/v0.1
