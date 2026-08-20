# Contributing to MPV Enhancer

Thank you for helping improve MPV Enhancer. Bug reports, focused feature
proposals, documentation fixes, and tested code changes are welcome.

## Before you start

Use an issue to describe a substantial change before investing in it. Keep one
task per branch and pull request. Work from the latest `main`, and use English
for code, tests, documentation, commits, pull requests, and user-facing text.

MPV Enhancer targets Python 3.12 on Windows. Install
[uv](https://docs.astral.sh/uv/), then prepare the locked environment:

```powershell
uv sync --extra dev --locked
```

Run the app with `uv run mpv-enhancer`. A local mpv installation is optional
for shell and setup-dialog development.

## Quality gate

Add or update tests for behavior changes. Before opening a pull request, run:

```powershell
uv run python scripts/quality.py
uv build --wheel
```

The first command checks Ruff formatting and linting, strict Mypy typing, the
pytest suite with coverage, and tracked-source secrets. GitHub repeats these
checks on a clean Windows runner.

## Privacy and safe test data

Review every staged file. Do not commit a secret, credential, token, personal
path, private media detail, playlist, log, dump, cache, screenshot with personal
information, or build artifact. Test data must be synthetic and safe for anyone
to redistribute. Redact absolute paths and media titles from bug reports and
diagnostics.

## Pull requests

Explain the user-visible outcome, identify the task or issue, and list the
checks you ran. Complete the privacy checklist in the pull request template.
All required CI checks must pass, and review conversations must be resolved,
before merge.

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
