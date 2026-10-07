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
  *Add agents*, where **Add** puts one on the board and **+ New agent** next
  to a folder starts a terminal/background agent there. **New board** takes
  any existing folder (`C:\...`, `/mnt/c/...`, `~/...`), typed or picked with
  **Browse…**, or picked from its ▾ list of folders with running sessions,
  and suggests those that have no board yet (other chats' worktrees left
  out). A folder has one board, so **New board** on a folder that has one
  opens it. Switch boards with **Board** in the top bar. **Change folder**
  (under *Board folder*) points the board at another folder: sessions there
  join it, and the cards and arrows already on it stay. **Open in Cursor**
  (under *Board folder*; the editor you last picked) opens a window on the
  board's folder, or brings forward the one already there. **Delete this
  board** (under *Board folder*) removes the board with its cards and
  arrows, after asking; the sessions keep running and no agent is told.
- **Connect:** drag the blue handle on a card onto another card (or click
  the handle, then the card); a reason is optional (without one, the two
  tell each other what they work on). You can edit or switch off either note
  before sending. The chat the arrow starts from goes first; the other
  replies. If you switch off the first chat's note, the other one is told to
  go first instead, and the arrow's details offer **Ask … to start the
  conversation** while the first chat runs. There is one arrow per
  direction: dropping onto a card you already point to opens that arrow.
- **Arrows** are labelled with their reason (or *connected*). An arrow is
  dashed while its notes are sent, red with *! not delivered* if one failed,
  and grey and dotted once either chat has ended. Click one (its line or its
  label) to see why and when it was connected, and:
  - **Conversation:** what the two chats sent each other with `SendMessage`,
    in both directions: the chat the arrow starts from on the left, the
    other on the right, the app's own notes in between. Messages from before
    the arrow are faded, above an *Arrow connected* line; one the other chat
    hasn't read yet says *not read yet*. Long ones fold (**Show all**), and
    **Show … earlier** loads older ones.
  - **Notes sent when connected** (open when one failed): each note with its
    state, *sent*, *sent, reworded* (with what was actually sent), *failed*
    or *not sent*. **Resend failed notes** sends the failed ones again.
  - **Disconnect** asks first. With **Tell both agents** ticked (the
    default), each end that is still running gets a note from
    `@let-them-talk` saying the connection was removed and to stop
    messaging for it.
- **New agent:** type a prompt and pick a folder (the board's to start
  with), then either open it as a new chat tab (**Chat in IDE**) in Cursor,
  VS Code … (picked under **Editor**), whose command-line tool (`cursor`,
  `code` …) opens that folder, or brings up the window that has it, before
  the chat opens there (the editor must trust the folder: in Restricted
  Mode, Claude Code is off), or start a **Terminal/background agent** there (a
  folder Claude Code already trusts), with its permissions and model (its
  terminal opens unless you untick that). With the folder box empty, the
  chat opens in the editor window you used last. The folder box's ▾ lists
  the folders you're working in (the board's, the sidebar's and those of
  the board's running chats; typing narrows the list), leaving out other
  chats' worktrees (`.claude/worktrees/…`); typing a path, **Browse…** and
  the place buttons still reach any folder.
  The editor chat gets your prompt as a message from Let Them Talk; a
  notice says whether it arrived (with **Copy prompt** if not). A new agent
  goes on the board you started it from.
- **New workflow** (top bar): say what it should do, and optionally how many
  agents and which model. It starts a background agent of its own, not tied
  to any chat, in the folder you pick, whose first prompt is *Use a workflow
  to do this: …*; the model you pick runs it and its agents, which show
  under **Subagents**. Its card is named *workflow* and the task's first
  words unless you name it.
- **Cards** show each chat's title (or the name you gave its card),
  `@address` (notes use the address) and
  folder, where it runs (*Terminal*, *Cursor*, *VS Code* …, *Background*),
  the model of its latest reply and its state: *busy*, *idle* or *waiting*
  for a chat, a background agent's own (*working*, *idle*, *needs you*,
  *done*, *stopped* …), or *ended*. *name shared* means another running session has
  the same name. A card that has ended or can't receive notes has no handle.
- **Subagents** (top bar): shows the subagents and workflow agents each chat
  is running now, as small cards linked to it; each goes away when it
  finishes. Past six, the first five show and the rest fold into *+N more
  running*; click it to show them all (**Show fewer** folds them again).
  Click one (or its row under *Agents in this chat*) to see what it is
  doing: its state, model, time and tokens, its latest steps, its latest
  message, the task it was given, its workflow and phase (or its type) and
  the chat that started it; the **←** button at the top, with that chat's
  name, goes back to its details. While it is on, the button shows how
  many are running; if nothing is running when you turn it on, a note says
  so.
- **Details:** click a card. The line under its title folds out to its
  address, folder, model and session id (and the chat's own title once you
  renamed the card).
- **Rename a card:** double-click it, press F2 on it, or click ✎ beside the
  name in its details; type a name and press Enter (Esc cancels). Only this
  board shows the name, Activity included; the chat keeps its own title and
  `@address`, so notes and messages still reach it. **Use its title** (or an
  empty name) goes back to the chat's title.
  - **Recent messages:** the last 3 messages, like a phone: your prompts as
    typed (including ones sent while it worked; ones typed in its own window
    while it works show as *queued* until it reads them), and Claude's
    finished replies and notes from other sessions as a short TL;DR when
    they are long (**Full reply** / **Show all** shows the whole text).
    While it works, a *now* line shows its current step. A question it asks
    you shows with its options, and so does a plan waiting for your approval
    (for a background agent also a permission prompt, read off its screen),
    with a button to answer it: **Open its terminal to answer** for a
    background agent, **Answer in Cursor** (or your editor) for an editor
    chat. A chat in a terminal is answered in that terminal.
  - **Send a message:** your text shows at once as your bubble (*sending…*,
    then *sent, not read yet*, then *You, from here* once the chat reads it).
    A running chat reads it between steps. An idle background agent gets it
    as its next prompt (the box then says **Send a prompt**, and your bubble
    ends as *You*): while its process runs, it is typed into its prompt box
    as if you typed it there, so it keeps running and its open terminal stays
    and shows it (if you have unsent text in that terminal, or it is asking
    you something there, nothing is typed); one whose process has ended is
    woken with it. If sending fails, the text goes back into
    the box. When the chat waits for you, the box shows a likely reply in
    grey; press Tab (or →) to use it. Enter sends, Shift+Enter adds a line.
  - **Agents in this chat (N)** is one line, with how many are running;
    click it to open the workflows and subagents the chat started in a
    pop-up over the board, with their state, model, time and tokens, and a
    running one's current step. Click one to see what it is doing in the
    pop-up (**← All agents** goes back). A workflow has **Ask it to stop
    this workflow** while it runs and **Ask it to resume this workflow** once
    it stopped or failed; each sends the chat a message asking for that. The
    chat's details stay underneath; ×, Esc or a click outside closes it.
  - **Connections (N)** folds open to list its arrows (your choice is
    remembered); click one to open it in a pop-up over the board, with the
    same details as clicking the arrow. The chat's details stay underneath;
    ×, Esc or a click outside closes it.
  - **Open in Cursor** (or your editor) shows the chat there (**Reopen in
    Cursor** once it has ended).
  - **Continue in Cursor** (an ended chat with no editor of its own; the
    editor you last picked) opens its folder, then the conversation in
    Cursor's Claude panel there, since Cursor finds a chat only in a window
    on its folder. The editor must trust the folder (in Restricted Mode,
    Claude Code is off); if the editor can't be asked, the notice says what
    to run instead (`cursor "<folder>"`).
- **Background agents:** **Open in terminal** (`claude attach <id>` in a new
  window), **Open in Cursor** (its folder, then its conversation in
  Cursor's Claude panel, as **Continue in Cursor** does; also while it runs,
  and then both write to the same conversation), **Show its screen** (click again to hide; it reads **What is it
  asking?** while the agent waits for you), **Stop** (while it works or
  shows a permission prompt or a question: Esc through `claude attach`, so
  it stops what it is doing, or declines the prompt, and waits for you; it
  keeps running and its terminal stays open),
  **Delete agent** (`claude rm`: removes it from Claude Code's list, with
  its worktree if it has one; its conversation file stays). An agent whose
  process ended before its first reply finished (`claude stop`, a crash)
  has no saved conversation and can't be woken: its card says *needs
  restart*, and
  **Restart in terminal** runs `claude respawn <id>` in a terminal, where
  Claude Code can ask you to trust its folder.
- A chat you send to the background keeps its card: the card, with its
  arrows, moves to the background agent that goes on with it.
- **Remove from board:** in a card's details; its arrows go too (the button
  says how many, and you are asked first). With **Tell connected agents**
  ticked (the default), the running ends of those arrows get the same note
  as with **Disconnect**. A session that is still running goes back under
  *Add agents*.
- **End this chat** (a chat in a terminal): its Claude Code exits as if you
  closed the window, which stays open. The conversation is kept;
  `claude --resume <id>` continues it. Chats in an editor are closed there.
- **Hand off to a new agent** (in a card's details): a copy of the chat
  writes a handoff with your `/handoff` skill, then a new background agent in
  the chat's folder, with its model and permissions, starts by reading it;
  its card appears beside the chat's and its terminal opens. The chat itself
  is left as it is: end it, or let it go on. Works for ended chats too. The
  new agent gets exactly the chat's permission mode, as its transcript last
  notes it; if that can't be read, nothing is handed off. (A bypass-mode
  chat needs Claude Code's bypass warning accepted once: `claude
  --dangerously-skip-permissions`.)
- **Arrange:** drag cards and the background; the mouse wheel zooms (down to
  zoom out, up to zoom in) around the pointer; drag a panel's inner edge to
  resize it (a line shows there as you point at it; double-click resets; or
  Tab to it, then ← → resize and Enter resets). **Fit view** brings every
  card into sight.
  Esc cancels an arrow; Esc or a click on the empty board closes the details.
- **Keyboard:** Tab reaches cards, arrow labels and subagent cards (the board
  moves to show the one in focus); Enter or Space opens it, with focus in its
  details (Tab goes on from there), and F2 renames a card. When the details
  close, focus goes back to the card or arrow they were opened from. Esc in
  **Appearance** closes only that.
- **Activity** (bottom of the sidebar, folded until you open it): the latest
  30 things that happened on this board, newest first, with the time: arrows
  connected and removed, notes and messages sent or failed, prompts sent,
  agents started, chats ended and cards removed.
- **Notices** (bottom right) say how an action went. Most go after a few
  seconds; a command to run in a terminal, the resume command after **End
  this chat**, a new editor chat that didn't get your prompt and anything
  that failed stay until you close them (×). A failed **Disconnect** or
  **Remove from board** leaves the details open. If the server stops
  answering, a banner at the bottom says so and the board fades until it
  answers again.
- **Appearance** (the gear next to *Let Them Talk*): the theme (**System**,
  **Light** or **Dark**) and the **Glass** slider, from *Clear* to *Tinted*.
  The sidebar, the top bar, the details and the dialogs are glass over the
  board: in Chromium browsers (Chrome, Edge …) the board bends at each
  panel's edge, other browsers show a plain blur, and with reduced
  transparency on in your system the panels are solid (in browsers that
  report that setting, such as Chrome and Edge). Text uses your system's
  font: Segoe UI Variable on Windows 11, Segoe UI on Windows 10 (Segoe UI
  Variable once you [install it from Microsoft](https://aka.ms/SegoeUIVariable)),
  SF Pro on a Mac, and elsewhere (e.g. Linux) Selawik, which comes with the
  app.
- The page remembers, in this browser, the board you had open, panel widths,
  each board's pan and zoom, whether Activity and the line under a chat's
  title are open, the editor you last picked in **New agent**, and your
  Appearance and Subagents choices.

## How it works

- Live sessions come from `~/.claude/sessions/*.json`; background agents
  that aren't running come from `claude agents --json --all`. A card greys
  out when its session ends, and leaves the board about two minutes later
  unless it has arrows. Titles, models and recent messages are read from its
  transcript in `~/.claude/projects/`, and a chat's agents from the subagent
  and workflow files next to it. Inside WSL, sessions of Claude Code on
  native Windows are read from `%USERPROFILE%\.claude` while their
  `claude.exe` runs.
- Notes are delivered by a short headless run, `claude -p --model haiku
  --name let-them-talk`, whose only tool is `SendMessage` (about 8 s). Each
  note is marked *sent*, *sent, reworded* or *failed*; until then its arrow
  is dotted. If the server restarts meanwhile, the run carries on without
  it, and the arrow is settled from the chats' transcripts: *sent* once the
  note shows up there, *failed* if it hasn't within 3½ minutes. A message you send to
  a chat goes the same way, as *[Let Them Talk] Message from your user:*, and
  a new editor chat's prompt as *[Let Them Talk] Your user started this chat
  from Let Them Talk with this prompt:*. An idle background agent gets yours
  as a prompt instead: typed into its prompt box through `claude attach`
  while its process runs, or with `claude --resume <id> --bg` once that has
  ended.
- An arrow's **Conversation** is read from both chats' transcripts: a message
  belongs to it when its message id is in one chat's `SendMessage` call and
  in the other's transcript, or when it went to the other chat's own socket
  (*not read yet* until it shows up there). Matching by name is a last
  resort, used only when one side's transcript is gone (*read state unknown*
  if it was the receiver's). A→B and B→A arrows show the same messages
  between the two chats, each with its own notes.
- A TL;DR is written by `claude -p --model haiku` with no tools (about 7 s),
  once per finished reply of 280+ characters, only when you open that chat,
  and kept in memory until the server restarts.
- A handoff is written by `claude -p --resume <id> --fork-session` on the
  chat's own model, running `/handoff` over the whole conversation (a few
  seconds to minutes; it costs about one reply of that chat). The fork is not
  saved. Nobody can answer it, so it edits files without asking
  (`acceptEdits`), in the chat's folder and in the handoff folder,
  `let-them-talk-handoffs` in the system's temp folder (`/tmp` on Linux and
  WSL). It is told only to write the handoff there; nothing else stops it
  from editing the chat's files.
- The server listens only on 127.0.0.1 and answers only requests addressed
  to `localhost` or `127.0.0.1` on its port. It takes commands only with its
  own request header, which other web pages can't send, and tells browsers
  never to show it in a frame.
- Boards are stored in `boards/` (a card's name too), every note and message sent through the
  headless run in `logs/relay.jsonl`, and the mod's latest suggestions in
  `logs/suggestions.json` (kept for a day).

## Limits

- A note arrives as a message from another session: it cannot approve
  permission prompts or change settings, and it starts a turn in an idle
  agent. A session running with bypassed permissions holds it for approval.
- An arrow tells agents who to talk to and why; it does not stop other
  sessions from messaging each other.
- Only sessions can be connected; subagents (the small cards under
  **Subagents**) can't be reached from outside, so connect their parent
  session.
- Sessions are addressed by name. If two sessions share a name (background
  agents that aren't running count too), `/rename` one of them first;
  renaming its card on the board doesn't change its address.
- **Windows sessions** (Claude Code on native Windows) are shown with a
  *Windows* badge, but the app can't connect them or send them messages yet
  (their details say why). A WSL session and a Windows session can never
  message each other.
- An arrow's **Conversation** shows the latest 50 messages; **Show …
  earlier** loads 50 more at a time, up to 500. A message addressed by name
  rather than to the chat's socket shows only once the other chat has read
  it.
- Terminals open in Windows Terminal (or a console window) from WSL, in
  Terminal on macOS and through `x-terminal-emulator` on Linux. Without one,
  **Open in terminal** shows the command to run instead, and a new agent's
  terminal doesn't open.
- A folder on a drive WSL hasn't mounted (e.g. Google Drive's `G:`) can't be
  used; mount it with `sudo mount -t drvfs G: /mnt/g`.

## Claude Code's own suggestion

The Send box shows the same grey suggestion as the chat's own prompt box, or
nothing:

- **A background agent that ends its turn waiting on you:** Claude Code saves
  its suggestion in `~/.claude/jobs/<id>/state.json` (the one `claude agents`
  offers with Tab), and the app reads it there. No setup, any agent.
- **Terminal chats, and background turns that don't wait on you:** Claude Code
  saves the suggestion nowhere, so the mod in `mods/let-them-talk-suggestions`
  passes it on as it is shown. When Claude Code makes none (the window isn't
  focused, or nobody is attached) and the app has that chat's details open,
  the mod makes one the way Claude Code does (one tool-less reply of the chat's
  own model over its cached conversation) and puts it in the chat's prompt box
  too, so both match. It first waits about 12 s for Claude Code's own. At
  most one per turn, none for chats nobody has open, and none once the reply
  is more than 5 minutes old (its conversation may no longer be cached).
  While the app waits for one (up to about 45 s after the reply, or after
  you open the chat), the Send box says *Suggesting a reply…*.
- **Chats in Cursor or VS Code** show none, like their own composer: the
  extension doesn't ask Claude Code for suggestions.
- **Chats started before the mod was loaded** show none until restarted.

To load the mod in every chat started from then on, add its absolute path to
the `env` block of `~/.claude/settings.json` (it talks to port 8765; edit
`hooks/register.ts` if you changed `LTT_PORT`):

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/agent-organizer/mods/let-them-talk-suggestions" } }
```

For a single chat: `claude --plugin-dir /path/to/agent-organizer/mods/let-them-talk-suggestions`.
The job file isn't an official Claude Code interface; if an update moves it,
those agents show nothing rather than wrong text.

## Settings

Environment variables: `LTT_PORT` (default `8765`), `LTT_MODEL` (model for
notes and TL;DRs, default `haiku`), `LTT_CLAUDE` (path to the `claude`
binary; by default `claude` on the PATH, else `~/.local/bin/claude`),
`LTT_WINDOWS_HOME` (your Windows user folder as a WSL path, e.g.
`/mnt/c/Users/you`, whose `.claude` holds Windows sessions; by default the
app asks Windows for `%USERPROFILE%`). The older `ORGANIZER_*` names still
work. If you run Claude Code with `CLAUDE_CONFIG_DIR`, set it for the server
too: it then reads sessions, transcripts and background agents from there
instead of `~/.claude`.

## License

Licensed under the [Apache License 2.0](LICENSE). The Selawik font files in
`static/fonts/` are Microsoft's, unmodified, under the SIL Open Font License
1.1 (`static/fonts/LICENSE-Selawik.txt`).
