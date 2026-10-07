# Configuration

Let Them Talk runs without setup; these settings and the optional
suggestions mod change how it runs.

## Environment settings

Set these for the server before you start it.

- `LTT_PORT`: the port it listens on (default `8765`). The Windows `.bat`
  always opens the page on port 8765; for the suggestions mod, see
  [below](#suggestions-mod).
- `LTT_MODEL`: the model for notes and TL;DRs (default `haiku`).
- `LTT_CLAUDE`: the path to the `claude` binary. By default `claude` on the
  PATH, else `~/.local/bin/claude`.
- `LTT_WINDOWS_HOME`: your Windows user folder as a WSL path, e.g.
  `/mnt/c/Users/you`, whose `.claude` holds Windows sessions. By default the
  app asks Windows for `%USERPROFILE%`.
- `CLAUDE_CONFIG_DIR`: if you run Claude Code with it, set it for the server
  too. It then reads sessions, transcripts and background agents from there
  instead of `~/.claude`.

The older `ORGANIZER_*` names (such as `ORGANIZER_PORT`) still work.

## Suggestions mod

The mod in `mods/let-them-talk-suggestions` does two things: it passes on
Claude Code's reply suggestion for terminal chats (see
[Reply suggestions](how-it-works.md#reply-suggestions)), and it runs a
**Chat in IDE** on the model picked in **New agent** (see
[The model of a Chat in IDE](how-it-works.md#the-model-of-a-chat-in-ide)).

To load it in every chat started from then on, add its absolute path to the
`env` block of `~/.claude/settings.json`:

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/agent-organizer/mods/let-them-talk-suggestions" } }
```

For a single chat:
`claude --plugin-dir /path/to/agent-organizer/mods/let-them-talk-suggestions`.

- Chats started before the mod was loaded show no suggestion until
  restarted.
- A **Chat in IDE** gets the picked model only where the mod is loaded: a
  Cursor or VS Code connected to WSL reads the same `~/.claude/settings.json`;
  one on Windows has its own.
- It talks to port 8765. If you changed `LTT_PORT`, edit `APP` in
  `mods/let-them-talk-suggestions/hooks/register.ts` to match.
