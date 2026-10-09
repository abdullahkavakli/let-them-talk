# Configuration

Let Them Talk runs without setup; these settings and the optional
suggestions mod change how it runs.

## Environment settings

Set these for the server before you start it.

- `LTT_PORT`: the port it listens on (default `8765`). The Windows `.bat`
  always opens the page on port 8765; for the suggestions mod, see
  [below](#suggestions-mod).
- `LTT_DATA`: the folder where the app keeps its boards and logs. By
  default the app's own folder when you run `./start.sh` or
  `python3 server.py` from a copy of the repository, and
  `$XDG_DATA_HOME/let-them-talk` (`~/.local/share/let-them-talk` if that isn't
  set, on macOS too) when you installed it with `uvx` or `pipx`. It is also the
  folder the app's own short `claude -p` runs start in. To carry boards over
  to another folder, copy `boards/` and `logs/` there. See
  [What is stored where](how-it-works.md#what-is-stored-where).
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

The mod in `mods/let-them-talk-suggestions` does three things: it passes on
Claude Code's reply suggestion for terminal chats (see
[Reply suggestions](how-it-works.md#reply-suggestions)), it runs a
**Chat in IDE** on the model picked in **New agent** (see
[The model of a Chat in IDE](how-it-works.md#the-model-of-a-chat-in-ide)),
and in a background agent, after an ultracode switch made while it works,
it runs `/effort status` so the app can read the switch (see
[Ultracode](how-it-works.md#ultracode)). In other chats it runs nothing
for ultracode.

To install it, add this repository as a plugin marketplace and install the
plugin from it:

```
claude plugin marketplace add abdullahkavakli/let-them-talk
claude plugin install let-them-talk-suggestions@let-them-talk
```

Or, in a chat:
`/plugin install let-them-talk-suggestions --marketplace abdullahkavakli/let-them-talk`.

The plugin is the mod of the latest release, the same release as the app
`uvx let-them-talk` runs, so the two always match. A new release brings both:
update the plugin with
`claude plugin update let-them-talk-suggestions@let-them-talk`.

If you run a copy of the repository and want the mod to follow it, load it
from there instead. To load it in every chat started from then on, add its
absolute path to the `env` block of `~/.claude/settings.json`:

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/let-them-talk/mods/let-them-talk-suggestions" } }
```

For a single chat:
`claude --plugin-dir /path/to/let-them-talk/mods/let-them-talk-suggestions`.

A copy loaded this way (`CLAUDE_CODE_PLUGIN_DIRS` or `--plugin-dir`) takes the
place of an installed one with the same name, so having both is fine.

- Chats started before the mod was loaded show no suggestion until
  restarted, and an ultracode switch made while they work shows only at
  their next prompt.
- A **Chat in IDE** gets the picked model only where the mod is loaded: a
  Cursor or VS Code connected to WSL reads the same `~/.claude/settings.json`;
  one on Windows has its own.
- It talks to port 8765. If you changed `LTT_PORT`, edit `APP` in
  `mods/let-them-talk-suggestions/hooks/register.ts` to match, in a copy of the
  repository loaded as above: Claude Code keeps an installed copy itself and
  may replace it when the plugin updates.
