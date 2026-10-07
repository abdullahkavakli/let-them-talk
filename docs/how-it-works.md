# How it works

Where the board's data comes from, how notes reach a chat, and what the app
stores.

## Sessions and cards

- Live sessions come from `~/.claude/sessions/*.json`; background agents that
  aren't running come from `claude agents --json --all`. (With
  [`CLAUDE_CONFIG_DIR`](configuration.md#environment-settings) set, that
  folder takes the place of `~/.claude` here and below.)
- A card greys out when its session ends, and leaves the board about two
  minutes later unless it has arrows.
- Titles, models and recent messages are read from its transcript in
  `~/.claude/projects/`, and a chat's agents from the subagent and workflow
  files next to it.
- Inside WSL, sessions of Claude Code on native Windows are read from
  `%USERPROFILE%\.claude` while their `claude.exe` runs.

## Notes and messages

Notes are delivered by a short headless run,
`claude -p --model haiku --name let-them-talk`, whose only tool is
`SendMessage` (about 8 s); [`LTT_MODEL`](configuration.md#environment-settings)
picks another model.

Each note is then marked *sent*, *sent, reworded* or *failed*; until then its
arrow shows it is still sending (see [Arrows](usage.md#arrows)). If the
server restarts meanwhile, the run carries on without it, and the arrow is
settled from the chats' transcripts: *sent* once the note shows up there,
*failed* if it hasn't within 3½ minutes.

A message you send to a chat goes the same way, as *[Let Them Talk] Message
from your user:*, and a new editor chat's prompt as *[Let Them Talk] Your
user started this chat from Let Them Talk with this prompt:*. An idle
background agent gets yours as a prompt instead: typed into its prompt box
through `claude attach` while its process runs, or with
`claude --resume <id> --bg` once that has ended.

## Images

An image you send is saved under a random name, readable only by you, in the
chat's own folder in Claude Code's temporary folder
(`/tmp/claude-<uid>/<project>/let-them-talk-images/`). Your text gets a line
`[Image: source: <path>]` for it, the way Claude Code names an image you
paste. The chat opens it with its Read tool without asking, as it does its
own files there.

Images older than a week are deleted the next time an image is saved.

## An arrow's conversation

An arrow's **Conversation** is read from both chats' transcripts. A message
belongs to it when its message id is in one chat's `SendMessage` call and in
the other's transcript, or when it went to the other chat's own socket (*not
read yet* until it shows up there).

Matching by name is a last resort, used only when one side's transcript is
gone (*read state unknown* if it was the receiver's). A→B and B→A arrows show
the same messages between the two chats, each with its own notes.

## TL;DRs

A TL;DR is written by `claude -p` on the same model as notes, with no tools
(about 7 s). It is written once per finished reply of 280+ characters, only
when you open that chat, and kept in memory until the server restarts.

## Handoffs

A handoff is written by `claude -p --resume <id> --fork-session` on the
chat's own model, running the app's `/handoff` skill over the whole
conversation. The skill is loaded for that run only, with
`--plugin-dir mods/let-them-talk-handoff`; your own skills are left as they
are. It takes a few seconds to minutes and costs about one reply of that
chat. The fork is not saved.

Nobody can answer the fork, so it edits files without asking
(`acceptEdits`), in the chat's folder and in the handoff folder (see
[What is stored where](#what-is-stored-where)). It is told only to write the
handoff there; nothing else stops it from editing the chat's files.

## Reply suggestions

The Send box shows the same grey suggestion as the chat's own prompt box, or
nothing:

- **A background agent that ends its turn waiting on you:** Claude Code saves
  its suggestion in `~/.claude/jobs/<id>/state.json` (the one `claude agents`
  offers with Tab), and the app reads it there. No setup, any agent. This job
  file isn't an official Claude Code interface; if an update moves it, those
  agents show nothing rather than wrong text.
- **Terminal chats, and background turns that don't wait on you:** Claude
  Code saves the suggestion nowhere, so the
  [suggestions mod](configuration.md#suggestions-mod) passes it on as it is
  shown. When Claude Code makes none (the window isn't focused, or nobody is
  attached) and the app has that chat's details open, the mod makes one the
  way Claude Code does (one tool-less reply of the chat's own model over its
  cached conversation). It puts it in the chat's prompt box too, so both
  match.
  - It first waits about 12 s for Claude Code's own.
  - At most one per turn, none for chats nobody has open, and none once the
    reply is more than 5 minutes old (its conversation may no longer be
    cached).
  - While the app waits for one (up to about 45 s after the reply, or after
    you open the chat), the Send box says *Suggesting a reply…*.
- **Chats in Cursor or VS Code** show none, like their own composer: the
  extension doesn't ask Claude Code for suggestions.

## The model of a Chat in IDE

An editor link can't name a model, so the
[suggestions mod](configuration.md#suggestions-mod) runs a **Chat in IDE**
started from the app on the model picked in
[New agent](usage.md#new-agent). The app tells the mod which model as the
chat's first turns start, and the mod names that model on the chat's own
requests, not its subagents'.

## Security

The server listens only on 127.0.0.1 and answers only requests addressed to
`localhost` or `127.0.0.1` on its port. It takes commands only with its own
request header, which other web pages can't send, and tells browsers never to
show it in a frame.

## What is stored where

- `boards/` (in the app's folder): the boards, a card's name included.
- `logs/relay.jsonl`: every note and message sent through the headless run.
- `logs/suggestions.json`: the mod's latest suggestions, kept for a day.
- `logs/models.json`: the model picked for each Chat in IDE, kept a week, so
  a chat resumed within a week still runs on it.
- `let-them-talk-handoffs` in the system's temp folder (`/tmp` on Linux and
  WSL): the handoffs.
- Images you send: see [Images](#images).
- What the page keeps in your browser: see
  [What the page remembers](usage.md#what-the-page-remembers).
