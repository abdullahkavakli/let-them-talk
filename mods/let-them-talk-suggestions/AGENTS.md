# AGENTS.md (suggestions mod)

- The user's settings load this mod live from the main folder (`CLAUDE_CODE_PLUGIN_DIRS`), so a change here reaches every Claude Code chat they start.
- It talks to `http://localhost:8765` (`APP`, hard-coded in `hooks/register.ts`), so a test copy on another port gets no mod traffic.
- `WINDOW_MS` in `hooks/register.ts` (milliseconds) must be the same length of time as `MOD_WINDOW` in `server.py` (seconds).
- Validate, from the repo root: `claude plugin validate mods/let-them-talk-suggestions`. Its warning that `CLAUDE.md` isn't loaded as plugin context is expected: that file is for chats editing this folder, so keep it. (Its tests are in the root `AGENTS.md`.)
- `tsconfig.json` and `.claude-plugin/types/` are written by Claude Code when it loads the mod (gitignored): don't edit or commit them.
- People install it from the repo's plugin marketplace (`.claude-plugin/marketplace.json` at the repo root, which lists this mod only: the app loads the handoff mod itself). Validate it from the repo root: `claude plugin validate .`. The marketplace fetches this folder from the latest release's tag, not from main, so a change here reaches people who installed the plugin only with the next release (see Release in the root `AGENTS.md`). `version` in `plugin.json` is that release's number: don't bump it on its own.
