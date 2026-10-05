# Agent Organizer

A local board for connecting your running Claude Code sessions. Each session
is a card; drag an arrow from one card to another, say why, and both agents
get a note from `@let-them-talk` telling them who they are connected to and why.

## Start

- Windows: double-click `Start Agent Organizer.bat`.
- WSL: `./start.sh`, then open <http://localhost:8765>.

## Use

- **Boards belong to folders.** Sessions running in the board's folder (or
  below it) appear on their own. Sessions from other folders are listed under
  *Add agents*; click **Add** to bring one onto the board.
- **New board:** type or paste any folder (`C:\...`, `/mnt/c/...`, `/home/...`
  or `~/...`), or click **Browse…** (or *Windows home*, *Windows Desktop*,
  *WSL home*) and click through folders. The folder must exist; it does not
  need a running session.
- **Connect:** drag the blue handle on the right of a card onto another card,
  or click the handle and then click the target. Write the reason; the two
  notes update as you type and can be edited or switched off before sending.
  The chat the arrow starts from is told to go first ("Start now: send …
  your current view"); the other is told to reply. If you don't tell the
  first chat, the second one is told to start, so someone always does. An
  arrow made without telling its first chat shows **Ask … to start the
  conversation** in its details.
- **New agent:** type a prompt, then either open it as a chat in your editor
  (Cursor, VS Code …; it opens in the editor window you used last, and you
  press Enter there) or start it as a **background agent** in a folder you
  pick, with its permissions and model. Claude Code must already trust that
  folder. Either joins the board once it starts. **Open in Cursor** in a
  chat's details shows that chat in its editor; both use the extension's
  `<editor>://anthropic.claude-code/open` link, which the browser asks once
  to allow.
- **Names:** cards show the title Claude gave each chat (a rename or fork
  title wins over the AI title), with its `@address` underneath. Notes and
  replies use the address.
- **Agents in a chat:** click a card. The panel on the right lists the
  workflows the chat has run (by phase: running, done, stopped, with model,
  time, tokens and the tool a running agent is using) and the subagents it
  started. It refreshes every 2.5 s.
- **Recent messages:** the panel also shows the chat's last 3 messages, like a
  phone: your prompts as typed (including ones sent while it worked), notes
  from other sessions, and Claude's finished replies as a short TL;DR
  (**Full reply** shows all of it). While it works, a *now* line shows its
  current step; a question it asks you shows with its options, and
  *Waiting for you…* means it needs your permission.
- **Send a message:** your text shows at once as your bubble (*sending…*, then
  *sent, not read yet*, then *You, from here* once the chat reads it). A
  running chat reads it between steps; an idle background agent wakes up with
  it as its next prompt. If sending fails, the text goes back into the box.
- **Background agents:** **Open in terminal**, **Show its screen** (click
  again to hide), **Stop**, **Delete agent** (`claude rm`: removes it from
  Claude Code's list, with its worktree if it has one; its conversation file
  stays). An agent stopped before its first reply finished has no saved
  conversation and can't be woken: its card says *needs restart*, and
  **Restart in terminal** runs `claude respawn <id>` in a terminal, where
  Claude Code can ask you to trust its folder.
- **Arrows:** click an arrow or its label to see delivery status, resend
  failed notes or disconnect (with or without a "disconnected" note).
- **Remove a card:** click it, then *Remove from board*. Its arrows go with
  it (you are asked first), and running agents at the other end can be told.
  A removed session that is still running goes back under *Add agents*.
- **Model badge:** the model of the chat's latest reply (Opus 5.5, Fable 5.1,
  Sonnet 5.5 …), read from its transcript; subagent rows in the panel show
  their own model.
- **Editor badge:** *Cursor*, *VS Code*, *Windsurf* … comes from the path of
  the claude binary the editor launched (the registry says "claude-vscode"
  for every VS Code fork); *Terminal* for a `claude` started in a shell.
- Drag cards to arrange them and drag the background to pan. New cards are
  placed where they don't overlap an existing one. The left and right panels
  resize by dragging the grey grip on their inner edge (double-click resets).
  **Fit view** brings every
  card back into sight; a board that opens with all cards off-screen is
  re-centered on its own.
  Press Esc to cancel an arrow or close the details panel.

## How it works

- Live sessions are read from `~/.claude/sessions/*.json` (name, folder,
  idle/busy, inbox socket). A card greys out when its session ends.
- Notes are delivered by a short headless run, `claude -p --model haiku
  --name let-them-talk`, whose only tool is `SendMessage` (about 8 s per
  connection). The server checks each call and marks a note *sent*,
  *sent, reworded* (if the relay changed the text) or *failed*.
- Titles come from `custom-title` / `ai-title` records in each chat's
  transcript (`~/.claude/projects/<dir>/<session>.jsonl`), read incrementally.
- A chat's agents come from `<session>/subagents/agent-*.jsonl` + `.meta.json`
  and, for workflows, `<session>/subagents/workflows/<run>/journal.jsonl` plus
  each agent's transcript while it runs; `<session>/workflows/<run>.json` is
  only written when a run ends. Attempts replaced by a retry or resume are
  hidden and counted as restarted.
- Recent messages are read from the end of the transcript. A TL;DR is written
  once per finished reply of 280+ characters by `claude -p --model haiku`
  with no tools (about 7 s), only when you open that chat, and kept in memory
  until the server restarts.
- Boards are stored in `boards/`, every delivery in `logs/relay.jsonl`.

## Limits

- A note arrives as a message from another session: it cannot approve
  permission prompts or change settings, and it starts a turn in an idle
  agent. A session running with bypassed permissions holds it for approval.
- An arrow tells agents who to talk to and why; it does not stop other
  sessions from messaging each other.
- Only whole sessions are cards. Subagents and workflow agents inside a
  session cannot be reached from outside; connect their parent session.
- A folder on a drive WSL hasn't mounted (e.g. Google Drive's `G:` appearing
  after WSL started) can't be browsed or used; mount it with
  `sudo mount -t drvfs G: /mnt/g`.
- Sessions are addressed by name. If two running sessions share a name,
  `/rename` one of them first.
- **Windows sessions** (terminal, VS Code or Cursor on native Windows) are shown
  too, with a *Windows* badge and their `C:\` path; a board for a folder holds
  both kinds (Windows paths are matched to `/mnt/c/...`, and New board accepts
  `C:\...`). They can't be connected yet: messaging on native Windows needs
  Claude Code 2.1.234 or later, and a WSL session and a Windows session can
  never message each other.

## Settings

Environment variables: `LTT_PORT` (default `8765`), `LTT_MODEL` (model for
notes and TL;DRs, default `haiku`), `LTT_CLAUDE` (path to the `claude`
binary). The older `ORGANIZER_*` names still work.

## License

Licensed under the [Apache License 2.0](LICENSE).
