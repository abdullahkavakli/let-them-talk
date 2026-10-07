# AGENTS.md

More depth: `docs/usage.md` (what the app does), `docs/how-it-works.md`, `docs/configuration.md`, `docs/limits.md`.

## Commands

- Run: `./start.sh` (port `LTT_PORT`, default 8765).
- All checks: `env -u DBUS_SESSION_BUS_ADDRESS -u DISPLAY -u WAYLAND_DISPLAY tests/check.sh` (server + page, ~35 s; exit 1 only when a check fails).
- Server checks only: `python3 -I tests/check_server.py` (~1-3 s; plain Python, every launch and message faked).
- Page checks only: `env -u DBUS_SESSION_BUS_ADDRESS -u DISPLAY -u WAYLAND_DISPLAY "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/tests/.venv/bin/python" -I tests/check_page.py` (uses the main folder's venv, so it works from a worktree too; headless browser, every server reply faked; exit 2 = skipped; `LTT_STATIC=<folder>` checks another copy of `static/`).
- One-time setup for the page checks: `tests/setup.sh` (~150 MB venv in `tests/.venv`, outside git; worktrees use the main folder's). Mod tests: `claude plugin test mods/let-them-talk-suggestions`. Syntax: `python3 -m py_compile server.py`, `node --check static/app.js`. No way to run a single check; no build, lint, typecheck or CI.

## Rules

- Never edit the main folder (repo root): the live app on :8765 runs from it and serves `static/` fresh, so a half-finished edit breaks the open page. Work in your own worktree: `git worktree add .claude/worktrees/<name> -b <name> main`. Read-only work needs none (test servers: see below).
- Other Claude Code chats often work here at once: never commit in, edit or remove another chat's worktree (it may be that chat's working folder). Before editing a file another chat is working on, tell that chat. Commit only your own changes.
- Main moves only when the user says "merge" in the chat that merges. One merge at a time. Right before merging (main moves often), check `git log`, rebase onto the latest main, then `git merge --ff-only <branch>` from the main folder. Never reset or force main.
- After merging: tell the other chats the new hash (SendMessage, by chat name) and push main to `origin` (private GitHub backup). Once you are done, `git worktree remove` and `git branch -d` your own.
- If `git push` gets GitHub's "Internal Server Error": retry later; or, once the same commit has been pushed as a branch (so the hook checked it), move main with `gh api -X PATCH repos/<owner>/let-them-talk/git/refs/heads/main -f sha=<hash> -F force=false`. Never force.
- Never `git push --no-verify`. The local pre-push hook (untracked, this machine only) refuses any commit that contains the user's home-folder path or WSL user name (in lines, file names, messages or author), then runs `tests/check.sh`. Write paths as `~/...`.
- Restart :8765 only if `server.py` changed, only from the main folder, only while `pgrep -P <pid>` prints nothing (a restart mid-request breaks what the user is doing): `nohup ./start.sh > /dev/null 2>&1 &`. Static files need only a page refresh.
- Test servers run only from a worktree or a copy (`boards/` and `logs/` sit next to `server.py`), on a free port (`ss -ltnp`), with `LTT_PORT`, a fake claude (`LTT_CLAUDE`), `PATH=/usr/local/bin:/usr/bin:/bin` and scratch boards. Stop them by PID after checking `/proc/<pid>/cwd`; never `pkill -f` a pattern that appears in your own command line. A copy still sees the real sessions: never connect, message or prompt real chats from it, never let it open an editor or terminal, never test Chat in IDE on it (its watcher adopts any new editor chat). On a hand-made scratch board, an ended card needs `lastSeen` and `cwd` or it is pruned.
- A browser started by hand in WSL needs `--password-store=basic --use-mock-keychain` with `DBUS_SESSION_BUS_ADDRESS`, `DISPLAY` and `WAYLAND_DISPLAY` unset, or a keyring password box pops up on the user's screen (hence the `env -u` prefix on the checks above).
- Open `cursor://` links from WSL with `rundll32.exe url.dll,FileProtocolHandler`, not `explorer.exe` (it drops links with a `?query`). Each link pops a prompt in the user's Cursor: don't fire test links.
- UI text: plain words, no jargon, no version numbers. Editor chats are labelled by their real editor (Cursor), never "VS Code"; generic buttons say "IDE". No screen-reader-only changes (ARIA names, alert roles, heading order); ask before more keyboard or contrast work.
- A deliberate change to what a check looks at (`server.py` or `static/`) changes that check in the same commit; a UI change also updates `docs/usage.md`. Each check covers something that broke once.
- Arrow note wording stays identical in `server.py` `default_notes()`/`who()` and `static/app.js` `defaultNotes()`/`who`.
- Before merging, look for duplicate top-level definitions in `server.py` (Python silently keeps the last): `python3 -c "import ast,collections;t=ast.parse(open('server.py').read());c=collections.Counter(n.name for n in t.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)));print([k for k,v in c.items() if v>1])"`.
- `server.py` uses only Python's standard library (3.12+); add no packages.
- Third-party files keep their license files: `static/fonts/` holds only Selawik (Microsoft's, unmodified, SIL Open Font License 1.1; never bundle Segoe UI Variable); `mods/let-them-talk-handoff/skills/handoff/` is Matt Pocock's `/handoff` skill from mattpocock/skills (MIT).
