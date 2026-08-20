# Repository Working Agreement

This file defines the public, repository-local rules for contributors and
automated coding agents. It does not replace the task or issue being worked on.

## Scope and language

- Keep each change focused on one issue or development task.
- Use English for source code, tests, documentation, commits, pull requests,
  and user-facing text.
- Do not implement behavior assigned to a later milestone.
- Preserve the Windows-first Python 3.12, PySide6, and Qt Widgets architecture.

## Required workflow

1. Create a focused branch from the latest `main`.
2. Add or update tests before completing behavior changes.
3. Run `uv sync --extra dev --locked`.
4. Run the complete gate with `uv run python scripts/quality.py`.
5. Review every staged file before opening a pull request.

The gate checks formatting, linting, strict typing, tests with coverage, and
tracked-source secrets. GitHub CI repeats the same gate on Windows and builds a
wheel.

## Privacy and repository hygiene

Never commit secrets, credentials, tokens, personal paths, private media,
playlists, logs, crash dumps, caches, screenshots with personal information, or
generated build output. Use synthetic names and data in tests. Redact absolute
paths and media details from diagnostics, examples, issues, and pull requests.

Runtime files belong in the application data, cache, or log directories, never
in the source tree. Do not add telemetry or network uploads without an explicit
approved task and a documented privacy review.

## Design boundaries

- Keep UI composition, application services, domain behavior, mpv integration,
  and persistence separated.
- Run external processes without a command shell and validate their results.
- Keep the app usable when mpv is absent; present actionable English guidance.
- Prefer small, reversible changes and deterministic tests.
