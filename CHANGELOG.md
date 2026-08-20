# Changelog

All notable changes to MPV Enhancer are documented in this file. The project
uses public minor release tags such as `v0.1`; the Python package uses the
corresponding three-part version such as `0.1.0`.

## [Unreleased]

## [0.4.0] - 2026-08-20

### Added

- Typed, validated per-item settings for playback speed, pan-and-scan, volume,
  mute, and subtitle visibility with deterministic inheritance and defaults.
- A scrollable selected-item settings panel with inherited, explicit, and mixed
  states, per-field reset, reset-all confirmation, and English tooltips.
- Multi-item editing that updates only selected UUIDs and preserves unrelated
  overrides.
- Allowlisted mpv property application with managed-property resets before
  every file and live updates for the current item.
- Default, 1.2× Playback, Fill Display, Subtitles On, and Subtitles Off presets
  with generated patch previews.
- Compact queue-row override badges and an end-to-end episodes 2/4/6 scenario.

## [0.3.0] - 2026-08-20

### Added

- Embedded mpv video in a stable native Qt host with resize, minimize/restore,
  and full-screen support.
- A supervised, shell-free mpv child process with bounded shutdown and one
  automatic restart after an unexpected exit.
- A random per-session Windows named-pipe transport using cancellable,
  overlapped duplex I/O.
- A line-framed JSON IPC client with request IDs, deadlines, late-reply guards,
  events, and property observation.
- Previous, Play/Pause, Stop, Next, absolute seek, duration, and progress
  controls backed by safe JSON commands.
- An explicit playback state machine and load generations that prevent stale
  file events from changing or advancing the current queue item.
- Path-free English playback errors with Retry and Stop recovery actions.
- Opt-in real-mpv recovery coverage and a clean-environment release playback
  smoke test using a synthetic Unicode, leading-hyphen local filename.

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

[Unreleased]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.4...HEAD
[0.4.0]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.3...v0.4
[0.3.0]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.2...v0.3
[0.2.0]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.1.1...v0.2
[0.1.1]: https://github.com/YusufHasanSaygili/mpv-enhancer/compare/v0.1...v0.1.1
[0.1.0]: https://github.com/YusufHasanSaygili/mpv-enhancer/releases/tag/v0.1
