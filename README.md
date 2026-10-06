# Let Them Talk

An agent organizer for Claude Code: a local board for your running sessions.
Each session is a card; drag an arrow from one card to another, say why, and
both get a note from `@let-them-talk` telling them who they are connected to
and why. Use it to set up simple multi-agent work by hand: start agents,
connect them, and say who hands what to whom.

## Start

Needs Python 3 and Claude Code (`claude`). On Windows, both must be
installed inside WSL, where the server runs.

- Windows: double-click `Start Let Them Talk.bat`; it starts the server
  in WSL and opens the page.
- macOS, Linux or WSL: `./start.sh`, then open <http://localhost:8765>.

## Use

- **Boards belong to folders.** Sessions running in the board's folder (or
  below it) appear on their own; ones from other folders are listed under
  *Add agents*. **New board** takes any existing folder (`C:\...`,
  `/mnt/c/...`, `~/...`), typed or picked with **Browse…**.
- **Connect:** drag the blue handle on a card onto another card; a reason is
  optional (without one, the two tell each other what they work on). You can
  edit or switch off either note before sending. The chat the arrow starts
  from goes first; the other replies.
- **Arrows:** click one to see whether its notes arrived, resend failed ones
  or disconnect.
- **New agent:** type a prompt, then open it as a chat in your editor (Cursor,
  VS Code …; press Enter there) or start a **terminal/background agent** in a
  folder Claude Code already trusts, with its permissions and model (its
  terminal opens unless you untick that).
- **Cards** show each chat's title and `@address` (notes use the address),
  where it runs (*Terminal*, *Cursor*, *VS Code* …, *Background*) and the
  model of its latest reply.
- **Subagents** (top bar): shows the subagents and workflow agents each chat
  is running now, as small cards linked to it; each goes away when it
  finishes. Click one to open its chat. Your choice is remembered.
- **Details:** click a card.
  - **Recent messages:** the last 3 messages, like a phone: your prompts as
    typed (including ones sent while it worked), and Claude's finished
    replies and notes from other sessions as a short TL;DR when they are
    long (**Full reply** / **Show all** shows the whole text). While it
    works, a *now* line shows its current step. A question it asks you shows
    with its options (for a background agent also a permission prompt or a
    plan to approve, read off its screen), with a button that opens where you
    answer it.
  - **Send a message:** your text shows at once as your bubble (*sending…*,
    then *sent, not read yet*, then *You, from here* once the chat reads it).
    A running chat reads it between steps; an idle background agent wakes up
    with it as its next prompt. If sending fails, the text goes back into
    the box. When the chat waits for you, the box shows a likely reply in
    grey; press Tab (or →) to use it. Enter sends, Shift+Enter adds a line.
  - **Agents in this chat:** the workflows and subagents it started, with
    their state, model, time and tokens.
  - **Open in Cursor** (or your editor) shows the chat there.
- **Background agents:** **Open in terminal**, **Show its screen** (click
  again to hide), **Stop**, **Delete agent** (`claude rm`: removes it from
  Claude Code's list, with its worktree if it has one; its conversation file
  stays). An agent stopped before its first reply finished has no saved
  conversation and can't be woken: its card says *needs restart*, and
  **Restart in terminal** runs `claude respawn <id>` in a terminal, where
  Claude Code can ask you to trust its folder.
- A chat you send to the background keeps its card: the card, with its
  arrows, moves to the background agent that goes on with it.
- **Remove from board:** in a card's details; its arrows go too (you are
  asked first). A session that is still running goes back under *Add agents*.
- **Arrange:** drag cards and the background; drag a panel's inner edge to
  resize it (double-click resets). **Fit view** brings every card into sight.
  Esc cancels an arrow or closes the details.

## How it works

- Live sessions come from `~/.claude/sessions/*.json`; a card greys out when
  its session ends. Titles, models, recent messages and a chat's agents are
  read from its transcript in `~/.claude/projects/`.
- Notes are delivered by a short headless run, `claude -p --model haiku
  --name let-them-talk`, whose only tool is `SendMessage` (about 8 s). Each
  note is marked *sent*, *sent, reworded* or *failed*.
- A TL;DR is written by `claude -p --model haiku` with no tools (about 7 s),
  once per finished reply of 280+ characters, only when you open that chat,
  and kept in memory until the server restarts. The grey suggested reply is
  made the same way, once per last reply.
- Boards are stored in `boards/`, every delivery in `logs/relay.jsonl`.

## Limits

- A note arrives as a message from another session: it cannot approve
  permission prompts or change settings, and it starts a turn in an idle
  agent. A session running with bypassed permissions holds it for approval.
- An arrow tells agents who to talk to and why; it does not stop other
  sessions from messaging each other.
- Only whole sessions are cards; subagents inside one can't be reached from
  outside, so connect their parent session.
- Sessions are addressed by name. If two running sessions share a name,
  `/rename` one of them first.
- **Windows sessions** (Claude Code on native Windows) are shown with a
  *Windows* badge. Messaging them needs Claude Code 2.1.234 or later on
  Windows, and a WSL session and a Windows session can never message each
  other.
- A folder on a drive WSL hasn't mounted (e.g. Google Drive's `G:`) can't be
  used; mount it with `sudo mount -t drvfs G: /mnt/g`.

## Claude Code's own suggestion (optional)

The Send box shows the same grey suggestion as the chat's own prompt box.
For a background agent the app reads it off the agent's screen (`claude
logs`, the dim text on the prompt line), with no setup. Claude Code saves it
nowhere else, so for chats in a terminal or an editor the mod in
`mods/let-them-talk-suggestions` sends it to the app:

- When Claude Code makes its own (only while the chat's window is focused),
  the mod passes it on.
- When it doesn't (the window is in the background, or a background agent has
  none) and the app has that chat's details open, the mod makes one the way
  Claude Code does: one tool-less reply of the chat's own model over its
  cached conversation, about a tenth of a turn's input. It goes into the chat's
  prompt box too, so both still match. Nothing is made for chats nobody has open
  (it keeps checking for 5 minutes after the reply), and at most one per turn.

Chats with the mod show that suggestion or nothing; chats without it get a
haiku guess. To load it in every chat started from then on, add its absolute
path to the `env` block of `~/.claude/settings.json` (it talks to port 8765;
edit `hooks/register.ts` if you changed `LTT_PORT`):

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/agent-organizer/mods/let-them-talk-suggestions" } }
```

For a single chat: `claude --plugin-dir mods/let-them-talk-suggestions`.

## Settings

Environment variables: `LTT_PORT` (default `8765`), `LTT_MODEL` (model for
notes and TL;DRs, default `haiku`), `LTT_CLAUDE` (path to the `claude`
binary). The older `ORGANIZER_*` names still work.

## License

Licensed under the [Apache License 2.0](LICENSE).
