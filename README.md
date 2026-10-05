# Let Them Talk

An agent organizer for Claude Code: a local board for your running sessions.
Each session is a card; drag an arrow from one card to another, say why, and
both get a note from `@let-them-talk` telling them who they are connected to
and why.

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
- **Connect:** drag the blue handle on a card onto another card and write the
  reason. You can edit or switch off either note before sending. The chat the
  arrow starts from goes first; the other replies.
- **Arrows:** click one to see whether its notes arrived, resend failed ones
  or disconnect.
- **New agent:** type a prompt, then open it as a chat in your editor (Cursor,
  VS Code …; press Enter there) or start it as a **background agent** in a
  folder Claude Code already trusts, with its permissions and model.
- **Cards** show each chat's title and `@address` (notes use the address),
  where it runs (*Terminal*, *Cursor*, *VS Code* …, *Background*) and the
  model of its latest reply.
- **Details:** click a card.
  - **Recent messages:** the last 3 messages, like a phone: your prompts as
    typed (including ones sent while it worked), notes from other sessions,
    and Claude's finished replies as a short TL;DR (**Full reply** shows all
    of it). While it works, a *now* line shows its current step; a question
    it asks you shows with its options, and *Waiting for you…* means it needs
    your permission.
  - **Send a message:** your text shows at once as your bubble (*sending…*,
    then *sent, not read yet*, then *You, from here* once the chat reads it).
    A running chat reads it between steps; an idle background agent wakes up
    with it as its next prompt. If sending fails, the text goes back into
    the box.
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
  and kept in memory until the server restarts.
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

## Settings

Environment variables: `LTT_PORT` (default `8765`), `LTT_MODEL` (model for
notes and TL;DRs, default `haiku`), `LTT_CLAUDE` (path to the `claude`
binary). The older `ORGANIZER_*` names still work.

## License

Licensed under the [Apache License 2.0](LICENSE).
