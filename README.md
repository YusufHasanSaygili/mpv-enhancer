# MPV Enhancer

[![CI](https://github.com/YusufHasanSaygili/mpv-enhancer/actions/workflows/ci.yml/badge.svg)](https://github.com/YusufHasanSaygili/mpv-enhancer/actions/workflows/ci.yml)

MPV Enhancer is a Windows-first desktop playlist controller and playback shell
for [mpv](https://mpv.io/). It is currently in early development.

The project will provide an ordered visual queue, per-item playback settings,
embedded mpv playback, and a clear transition between queue items. The desktop
application will use Python, PySide6, and Qt Widgets.

## Project status

The v0.4 per-item settings slice is available as a public pre-release. The
repository contains a runnable three-region desktop shell, persistent mpv
preferences, safe local paths and rotating diagnostics, automated tests, and a
Windows CI quality gate. The application includes an ordered queue, Explorer
file drop, embedded mpv video, basic transport controls, progress, full-screen,
and recoverable playback failures. Queue items can be reordered by dragging or
with `Alt+Up` and `Alt+Down`. Selected items can receive validated speed,
pan-and-scan, volume, mute, and subtitle-visibility overrides with inherited,
explicit, and mixed states. Ctrl selects non-adjacent queue items, Shift
selects ranges, and Ctrl+A selects the full queue.
Selected items can be removed with Delete, the full queue can be cleared after
confirmation, and queue edits support Undo and Redo.
Queue rows provide accessible labels, elide long titles, and show compact
override badges. Starter presets cover reset-to-default, 1.2× playback,
fill-display, and subtitle visibility.

See [CHANGELOG.md](CHANGELOG.md) and the [v0.4 release notes](docs/releases/v0.4.md)
for compatibility details, assets, known limitations, and the immutable Slice
04 fork point. The [v0.3 release](docs/releases/v0.3.md) remains available as
the verified embedded-playback fork point.

## Contributing

Please use the issue templates to report a bug or propose an enhancement. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the complete development, testing,
privacy, and pull request workflow. Security vulnerabilities must be reported
privately as described in [SECURITY.md](SECURITY.md).

## Development setup

MPV Enhancer uses Python 3.12. The recommended workflow uses
[uv](https://docs.astral.sh/uv/):

```powershell
uv sync --extra dev --locked
uv run python -c "import mpv_enhancer; print(mpv_enhancer.__version__)"
uv run pytest
uv run mpv-enhancer
```

Run the complete local quality gate with one command:

```powershell
uv run python scripts/quality.py
```

The gate verifies Ruff formatting and linting, strict Mypy checks, the complete
pytest/pytest-qt suite with coverage, and a tracked-source secret scan.

Contributors who use standard `pip` can create and populate a virtual
environment instead:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
```

The current application opens an English three-region desktop shell. Supported
local media files can be dropped into the queue while invalid entries from the
same drop are skipped with a status message. Reordering preserves each item's
identity and metadata. Double-click an item or select it and press Play to load
it in the embedded video host. Use the left panel to edit selected queue items;
changes to the current item are applied live when supported by mpv.

## mpv setup

MPV Enhancer validates mpv by running `mpv.exe --version` without a shell. It
checks a path selected under **Settings > Preferences**, the development-only
`MPV_ENHANCER_MPV_PATH` environment variable, `mpv.exe` on `PATH`, and standard
Windows install locations, in that order. If mpv is missing or invalid, the app
opens an English setup and diagnostics dialog instead of crashing.

## Local data and privacy

MPV Enhancer keeps runtime data outside the source repository. On Windows,
application data is stored below `%APPDATA%\MPV Enhancer`, while caches, logs,
and crash-report directories are stored below `%LOCALAPPDATA%\MPV Enhancer`.

Normal logs are size-limited, rotating JSON Lines files. Absolute paths passed
as logging arguments are replaced with `<redacted-path>` so media and user
profile locations are not written to normal diagnostics. The application does
not send telemetry or upload logs.

## License

MPV Enhancer is available under the [MIT License](LICENSE). See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency notices.
