# Third-Party Notices

MPV Enhancer is distributed under the MIT License, but it depends on software
made available under separate licenses. Those licenses and copyright notices
remain the property of their respective authors.

## Runtime dependencies

- Python — Python Software Foundation License.
- PySide6 and Shiboken6 — Qt for Python components distributed under the terms
  offered by The Qt Company, including LGPL/GPL and commercial options.
- Qt libraries installed with PySide6 — licensed separately by their authors.

## External application

MPV Enhancer discovers and controls a user-provided installation of
[mpv](https://mpv.io/). The project does not bundle mpv in the current release.
mpv and its own dependencies are separate works under their respective
licenses.

## Development dependencies

The complete, reproducible dependency set is recorded in `uv.lock`. Development
and CI tools listed there are not incorporated into MPV Enhancer's runtime
wheel. Their own distributions contain the authoritative license texts and
notices.

This notice is informational and is not a substitute for the license files
shipped by each dependency.
