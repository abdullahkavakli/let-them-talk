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

A background agent whose process has ended has no inbox, so its note is its
prompt instead: it is woken with `claude --resume <id> --bg -- <note>`, as
**Send** wakes it (see below). That goes first, and the running chat's note
follows once the woken agent shows up running (up to 15 s), because that note
may tell the chat to message it. Which way a note goes is decided when it is
sent, so **Resend failed notes** reaches an agent that has started since by
message, not by waking it twice. A woken note is marked *sent* ("woke it with
the note as its prompt"). If Claude Code reports it started a copy instead of
waking the agent in place, the note is *failed*, and the copy's card is added.

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

## Compacting

**Compact** types `/compact` into a running background agent through
`claude attach`, as a prompt is typed, pressing Enter only once its prompt
box shows `/compact`. An ended one is woken with
`claude --resume <id> --bg -- /compact`, which Claude Code runs as the
command too. A chat in a terminal or an editor gets only messages, read
between steps, and a message can't run a command, so it has no **Compact**.

Claude Code writes the result into the agent's transcript once it is done
(seconds, or a minute or two for a long conversation): a compact boundary
with the context's size before and after, then `/compact`'s answer. The app
reads what the transcript gets after you click. It stops waiting after 8
minutes, or once the agent is neither busy nor done for a few seconds (Esc in
its terminal, or it ended).

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

## How an editor gets a folder and a chat

**Continue in IDE**, **Open in IDE** on a background agent and a **Chat in
IDE** in a folder first open the folder with the editor's command-line tool
(`cursor`, `code` …), wait a few seconds for its window, then hand the editor
a link, `<editor>://anthropic.claude-code/open?session=<id>`, which its Claude
extension turns into a conversation tab. The editor never answers whether it
did, so the page shows no notice once the link went out; a failure before
that (the folder or the editor's tool missing) gets one.

- **From WSL** the app reads the editor's link command from the Windows
  registry (`reg.exe`, `HKCU\Software\Classes\<scheme>\shell\open\command`,
  then `HKCR`), which for Cursor, VS Code and their forks is
  `"C:\…\Cursor.exe" --open-url -- "%1"`, and hands that program
  `--open-url -- <link>`, the link as one argument (no shell, so `&` and `%`
  stay as they are), through the program's own command-line script
  (`resources\app\out\cli.js` beside it, run the way the `cursor` command
  runs it), which starts the editor; the editor finds its running window and
  hands it the link. The script matters: a Windows program started from WSL
  gets the environment of the Windows program that started that WSL session,
  and when that is Cursor (its extension host), it carries
  `ELECTRON_RUN_AS_NODE=1`. Started with that, `Cursor.exe` is a bare Node,
  refuses `--open-url` and quits, and no window ever sees the link; the
  script starts the editor without it, as it does for the folder step. With
  no script there, the program is started straight. The program is found once
  and kept. If the registry can't be read, the command isn't of that shape or
  the program isn't there or won't start, the app asks Windows' own link
  handler (`rundll32.exe url.dll,FileProtocolHandler`) instead (which passes
  that same environment on); `explorer.exe` would drop the `?session=`.
- **On Linux and macOS** the link goes to `xdg-open` or `open`.
- **The editor's side:** Cursor routes an extension's link to one of its
  ordinary (not agents) windows, and the extension finds a conversation only
  in a window on its folder.

## The model of a Chat in IDE

An editor link can't name a model, so the
[suggestions mod](configuration.md#suggestions-mod) runs a **Chat in IDE**
started from the app on the model picked in
[New agent](usage.md#new-agent). The app tells the mod which model as the
chat's first turns start, and the mod names that model on the chat's own
requests, not its subagents'.

## Ultracode

Whether ultracode is on in a background agent (see
[Ultracode](usage.md#ultracode)) is read from its transcript: Claude Code
notes each `/effort` answered while the agent is idle ("Ultracode on …",
"Ultracode off …", or for an `/effort status` typed in its terminal a line
that names ultracode only while it is on), and at each prompt a reminder when
it changed since the last one. The newest of these counts, with what the app
saw itself: a **Turn on** or **Turn off**.

The app never types `/effort` into an agent to find out. The only `/effort`
it types is the one a **Turn on** or **Turn off** click sends, so nothing of
its own appears in the agent's terminal. The
[suggestions mod](configuration.md#suggestions-mod) runs no command in a chat
either.

- **While it works:** an `/effort` answers only on the agent's screen, and
  its transcript gets nothing, so the line keeps what it said until the
  agent's next prompt (or a **Turn on** or **Turn off** from here, below).
- **Unknown:** a process that has had no prompt and no switch yet (woken,
  restarted) leaves its conversation silent, so the line says *Ultracode:
  unknown*, with both buttons, until a switch or a prompt tells.
- **The app's own Turn on or off while it works:** the app reads Claude
  Code's answer off the agent's screen, so it is in no transcript. The app
  keeps it on disk, so a restart of the app loses nothing. If Claude Code
  queues the `/effort` instead of running it at once, nothing is on the
  screen: the app says it got no answer within 10 seconds, the line stays as
  it was, and once the agent is idle and runs it, its answer is in the
  transcript and the line follows.
- **Which process:** a switch the app keeps counts only while the process
  that had it (by its pid) runs the agent, and only from when that process
  started, so a later process that gets the same pid doesn't inherit it.
- **The panel opened and closed with Esc:** Claude Code notes "Cancelled",
  which changes nothing.
- **Older conversations:** an earlier version of the mod ran `/effort status`
  in a background agent. Its lines stay in those conversations, and the app
  doesn't show them as yours or as work.

## Moving an editor chat to a terminal

The editor's Claude panel runs a chat as a Claude Code process of its own
(entrypoint `claude-vscode`, in `~/.claude/sessions/<pid>.json`). Claude Code
doesn't stop a terminal from resuming a conversation that process still holds;
both would write its transcript. So **Open in terminal** first closes the one
in the editor, then opens `claude --resume <id>`.

- **How it is closed:** the process gets SIGINT, once you said yes. In the
  mode the extension runs it in, Claude Code answers by ending its turn,
  saving the conversation and exiting with code 0, which is what happens when
  the extension closes a chat itself (it ends the process's input). SIGTERM
  would exit with code 143, which the extension reports as an error in the
  panel, so it isn't used. The app waits up to 10 seconds for the process to
  go; if it stays, nothing opens in the terminal and the notice says to close
  the tab in the editor.
- **What the editor shows:** the extension sees the process end the way it
  does when you close the tab, with no error. Its panel keeps the
  conversation and is not started again by itself; a message typed there later
  starts it, and the extension, which reads the same session files, sees the
  terminal holds the chat and asks before taking it back.
- **Which chats:** a chat on this machine whose process was started by the
  editor. Windows chats can't be signalled from here.

## Security

The server listens only on 127.0.0.1 and answers only requests addressed to
`localhost` or `127.0.0.1` on its port. It takes commands only with its own
request header, which other web pages can't send, and tells browsers never to
show it in a frame.

## What is stored where

The first group lives in the app's *data folder*. Run from a copy of the
repository (`./start.sh`), that is the app's own folder. Installed with `uvx`
or `pipx`, it is `~/.local/share/let-them-talk` (`$XDG_DATA_HOME/let-them-talk`
if that is set; the same on macOS), so nothing is written next to the
installed code. [`LTT_DATA`](configuration.md#environment-settings) picks
another folder in both cases. The app's own short `claude -p` runs (notes,
TL;DRs, looking up a model's full id) start in the data folder too, and save
no conversation.

- `boards/`: the boards, a card's name included.
- `logs/relay.jsonl`: every note and message sent through the headless run.
- `logs/suggestions.json`: the mod's latest suggestions, kept for a day.
- `logs/models.json`: the model picked for each Chat in IDE, kept a week, so
  a chat resumed within a week still runs on it.
- `logs/ultracode.json`: each chat's latest ultracode switch the app made
  (Turn on or off), with the pid of the process that had it, kept 30 days.

Elsewhere:

- `let-them-talk-handoffs` in the system's temp folder (`/tmp` on Linux and
  WSL): the handoffs.
- Images you send: see [Images](#images).
- What the page keeps in your browser: see
  [What the page remembers](usage.md#what-the-page-remembers).
