# Contributing

Bugs go in [Issues](https://github.com/abdullahkavakli/let-them-talk/issues). Questions and ideas go in [Discussions](https://github.com/abdullahkavakli/let-them-talk/discussions). To change something yourself, fork the repo, make a branch and open a pull request.

## Run it

`./start.sh`, then open <http://localhost:8765>. It needs Python 3.12+ and Claude Code (on Windows, both inside WSL). `LTT_PORT` changes the port. A copy you run sees your real Claude Code sessions, so be careful what you send from it while testing.

## Checks

One-time setup for the page checks: `tests/setup.sh`. It installs Playwright and a headless browser, about 150 MB, into `tests/.venv`, outside git.

Run all checks (about 35 seconds):

```
env -u DBUS_SESSION_BUS_ADDRESS -u DISPLAY -u WAYLAND_DISPLAY tests/check.sh
```

The `env -u` part keeps the headless browser from opening a keyring window on your screen. The server checks alone: `python3 -I tests/check_server.py`. If you change the suggestions mod: `claude plugin test mods/let-them-talk-suggestions`.

## Rules

- `server.py` uses only Python's standard library (3.12+). Add no packages.
- UI text is in plain words, with no jargon and no version numbers. Editor chats are named after their real editor (Cursor, for example); a button that works for any editor says "IDE".
- A fix comes with a check for it, in `tests/check_server.py` or `tests/check_page.py`. Each check covers something that broke once.
- A change to what people see also updates `docs/usage.md`.
- The arrow notes' wording stays identical in `server.py` (`default_notes()` and `who()`) and `static/app.js` (`defaultNotes()` and `who`).

The full rules are in [AGENTS.md](AGENTS.md). It is written for coding agents: the parts about worktrees, other chats, merging and port 8765 are the maintainer's own setup, not something you need.
