# MPV Enhancer

MPV Enhancer is a Windows-first desktop playlist controller and playback shell
for [mpv](https://mpv.io/). It is currently in early development.

The project will provide an ordered visual queue, per-item playback settings,
embedded mpv playback, and a clear transition between queue items. The desktop
application will use Python, PySide6, and Qt Widgets.

## Project status

The public repository foundation is available. The Python project bootstrap is
the next planned development milestone; installation and usage instructions
will be added with the first runnable development version.

## Contributing

Please use the issue templates to report a bug or propose an enhancement.
Development commands are documented below; a full contributor guide will be
added in a later foundation milestone.

## Development setup

MPV Enhancer uses Python 3.12. The recommended workflow uses
[uv](https://docs.astral.sh/uv/):

```powershell
uv sync --extra dev
uv run python -c "import mpv_enhancer; print(mpv_enhancer.__version__)"
uv run pytest
uv run mpv-enhancer
```

Contributors who use standard `pip` can create and populate a virtual
environment instead:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
```

The current application opens an English three-region desktop shell. Playback,
queue behavior, and per-item settings will be added in later milestones.

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

MPV Enhancer is available under the [MIT License](LICENSE).
