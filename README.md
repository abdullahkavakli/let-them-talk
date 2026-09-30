# Agent Organizer

A local board for connecting your running Claude Code sessions. Each session
is a card; drag an arrow from one card to another, say why, and both agents
get a note from `@organizer` telling them who they are connected to and why.

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
- **Names:** cards show the title Claude gave each chat (a rename or fork
  title wins over the AI title), with its `@address` underneath. Notes and
  replies use the address.
- **Agents in a chat:** click a card. The panel on the right lists the
  workflows the chat has run (by phase: running, done, stopped, with model,
  time, tokens and the tool a running agent is using) and the subagents it
  started. It refreshes every 2.5 s.
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
  --name organizer`, whose only tool is `SendMessage` (about 8 s per
  connection). The server checks each call and marks a note *sent*,
  *sent, reworded* (if the relay changed the text) or *failed*.
- Titles come from `custom-title` / `ai-title` records in each chat's
  transcript (`~/.claude/projects/<dir>/<session>.jsonl`), read incrementally.
- A chat's agents come from `<session>/subagents/agent-*.jsonl` + `.meta.json`
  and, for workflows, `<session>/subagents/workflows/<run>/journal.jsonl` plus
  each agent's transcript while it runs; `<session>/workflows/<run>.json` is
  only written when a run ends. Attempts replaced by a retry or resume are
  hidden and counted as restarted.
- Boards are stored in `boards/`, every delivery in `logs/relay.jsonl`.

## Limits

- A note arrives as a message from another session: it cannot approve
  permission prompts or change settings, and it starts a turn in an idle
  agent. A session running with bypassed permissions holds it for approval.
- An arrow tells agents who to talk to and why; it does not stop other
  sessions from messaging each other.
- Only whole sessions are cards. Subagents and workflow agents inside a
  session cannot be reached from outside; connect their parent session.
- Sessions are addressed by name. If two running sessions share a name,
  `/rename` one of them first.
- **Windows sessions** (terminal, VS Code or Cursor on native Windows) are shown
  too, with a *Windows* badge and their `C:\` path; a board for a folder holds
  both kinds (Windows paths are matched to `/mnt/c/...`, and New board accepts
  `C:\...`). They can't be connected yet: messaging on native Windows needs
  Claude Code 2.1.234 or later, and a WSL session and a Windows session can
  never message each other.

## Settings

Environment variables: `ORGANIZER_PORT` (default `8765`),
`ORGANIZER_MODEL` (relay model, default `haiku`), `ORGANIZER_CLAUDE`
(path to the `claude` binary).
