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

The repository intentionally contains only the importable package foundation
at this stage. A runnable desktop entry point will be added in the application
shell milestone.

## License

MPV Enhancer is available under the [MIT License](LICENSE).
