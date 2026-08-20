# Architecture decisions

This document records decisions that materially affect MPV Enhancer's runtime
architecture. Decisions are append-only: a later decision may supersede an
earlier one, but accepted history remains visible.

## ADR-0001: Embed mpv as a supervised process with JSON IPC

- **Status:** Accepted
- **Date:** 2026-08-20
- **Decision:** Use a supervised mpv process plus JSON IPC. On Windows, pass a
  native Qt video-host handle through mpv's `--wid` option and use a unique
  named pipe for commands and events.

### Context

MPV Enhancer needs embedded playback without giving untrusted media paths to a
shell. The two practical approaches were a separately supervised mpv process
or an in-process libmpv integration. A process boundary provides simpler crash
isolation and cleanup, while JSON IPC is a documented mpv control surface.
Embedding still needed a real Windows proof before this architecture could be
accepted.

### Evidence

A repeatable probe in `scripts/windows_embedding_spike.py` starts mpv with
`QProcess`, a structured argument list, `--no-config`, and a generated lavfi
test source. It does not invoke a command shell or read user mpv configuration.

The probe passed on an interactive Windows 11 host (build 10.0.22631) with Qt
6.11.1 and the official mpv CI build 0.41.0-dev-gf4d13e1c2:

| Check | Result |
| --- | --- |
| Native handle | Qt host handle represented safely as the Windows `uint32` expected by `--wid` |
| Parent relationship | The mpv window was a direct child of the Qt video host |
| Initial coverage | Host 800 x 520; child 800 x 520 |
| Resize coverage | Host 1100 x 680; child 1100 x 680 |
| Full-screen coverage | Host 3440 x 1440; child 3440 x 1440 |
| Window restoration | Returned from full-screen while coverage remained synchronized |
| Process health | mpv remained running through all transitions |
| Shutdown | The owned process stopped within the bounded termination sequence |

The tested archive was downloaded from mpv's official GitHub release workflow
and verified before extraction with SHA-256
`ecbac93878aaba79cab62105e5186f93701deeacb14b95a3afa70d0369cb1ba9`.
The binary and machine-local JSON evidence remain in ignored build directories;
neither is committed or distributed by this project. Contributors can rerun
the probe against their own trusted `mpv.exe`:

```powershell
uv run python scripts/windows_embedding_spike.py --mpv C:\path\to\mpv.exe
```

### Consequences

- The application owns exactly one mpv child process and can bound startup,
  shutdown, and recovery without taking ownership of unrelated mpv processes.
- All executable and media paths are passed as discrete arguments; no shell
  command is assembled.
- Playback commands and observed state cross a unique local named pipe using
  newline-delimited JSON.
- The UI remains responsible for the native video host, resize behavior, and
  user-facing recovery state; domain code remains independent of Qt and mpv.

### Risks

- `--wid` behavior is platform- and video-output-specific, so Windows and GPU
  combinations outside the tested environment may expose driver defects.
- Native window handles and named-pipe lifetimes require careful ownership;
  stale handles or pipe messages must never mutate a newer playback session.
- A child process can exit or hang independently of the UI.
- mpv JSON IPC is asynchronous, so commands, replies, and property events may
  arrive out of order during rapid media changes.

Mitigations are a forced native Qt host, generation-tagged playback state,
bounded process and pipe timeouts, one controlled restart after unexpected
exit, explicit child-only cleanup, and Windows CI coverage for logic that does
not require an interactive desktop.

### Rollback point

Revisit this decision before the embedded host is released if supported
Windows hardware cannot pass the same parent, resize, full-screen, and clean
shutdown checks, or if reliable JSON IPC recovery cannot be demonstrated. The
fallback is an in-process libmpv adapter behind the same playback interfaces;
adopting it requires a superseding ADR that records packaging, crash-isolation,
and licensing consequences.
