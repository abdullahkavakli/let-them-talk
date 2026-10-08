# AGENTS.md (suggestions mod)

- The user's settings load this mod live from the main folder (`CLAUDE_CODE_PLUGIN_DIRS`), so a change here reaches every Claude Code chat they start.
- It talks to `http://localhost:8765` (`APP`, hard-coded in `hooks/register.ts`), so a test copy on another port gets no mod traffic.
- `WINDOW_MS` in `hooks/register.ts` (milliseconds) must be the same length of time as `MOD_WINDOW` in `server.py` (seconds).
- `ultracodeSaid` in `hooks/register.ts` reads an `/effort` answer as `ULTRA_SAID` and `EFFORT_STATUS` in `server.py` do (the transcript, for chats without the mod): change them together.
- Validate, from the repo root: `claude plugin validate mods/let-them-talk-suggestions`. Its warning that `CLAUDE.md` isn't loaded as plugin context is expected: that file is for chats editing this folder, so keep it. (Its tests are in the root `AGENTS.md`.)
- `tsconfig.json` and `.claude-plugin/types/` are written by Claude Code when it loads the mod (gitignored): don't edit or commit them.
