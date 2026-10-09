# Using Let Them Talk

What each part of the board does, from boards and arrows to a chat's details.

## Boards

- **Boards belong to folders.** Sessions running in the board's folder (or
  below it) appear on their own. Ones from other folders are listed under
  *Add agents*, where a row's **+** puts it on the board and **+ New agent**
  next to a folder opens [New agent](#new-agent) on that folder.
- **New board** takes any existing folder (`C:\...`, `/mnt/c/...`, `~/...`),
  typed or picked with **Browse…**, or picked from its drop-down list of
  folders with running sessions. The list and the suggestions under it are
  the folders that have no board yet (other chats' worktrees left out); when
  every folder with running sessions has one, it says so, and **Browse…** or
  a typed path reaches any other. A folder has one board, so **New board**
  on a folder that has one opens that board and says so.
- Switch boards with **Board** in the top bar: it opens a list of the boards,
  the current one ticked, each with its folder under its name. Click a board,
  or move with ↑ ↓ and press Enter; Esc or a click elsewhere closes the list.
  **New board…**, under the list, and the **New board** button beside **Fit
  view** both open the New board dialog.
- Under *Board folder*:
  - **Change folder** points the board at another folder: sessions there
    join it, and the cards and arrows already on it stay.
  - **Open in IDE** (the IDE picked under [Settings](#settings)) opens a
    window on the board's folder, or brings forward the one already there.
  - **Delete this board** removes the board with its cards and arrows, after
    asking. The sessions keep running and no agent is told.

## Connect two chats

Drag the blue handle on a card onto another card (or click the handle, then
the card). A reason is optional: without one, the two tell each other what
they work on. You can edit or switch off either note before sending.

- The chat the arrow starts from goes first; the other replies. If you switch
  off the first chat's note, the other one is told to go first instead, and
  the arrow's details offer **Ask … to start the conversation** while the
  first chat runs.
- There is one arrow per direction: dropping onto a card you already point to
  opens that arrow.

## Arrows

Arrows are labelled with their reason (or *connected*). An arrow is dashed
and moving while its notes are sent, red with *! not delivered* if one
failed, and grey and dotted once either chat has ended. Two cards with an
arrow each way have the two side by side between them, the one from the card
on the left above, each with its own label. Click one (its line or its label)
to see why and when it was connected, and:

- **Conversation:** what the two chats sent each other with `SendMessage`, in
  both directions: the chat the arrow starts from on the left, the other on
  the right, the app's own notes in between. Messages from before the arrow
  are faded, above an *Arrow connected* line; one the other chat hasn't read
  yet says *not read yet*. Long ones fold (**Show all**), and **Show …
  earlier** loads older ones.
- **Notes sent when connected** (open when one failed): each note with its
  state, *sent*, *sent, reworded* (with what was actually sent), *failed* or
  *not sent*. **Resend failed notes** sends the failed ones again.
- **Disconnect** asks first. With **Tell both agents** ticked (the default),
  each end that is still running gets a note from `@let-them-talk` saying the
  connection was removed and to stop messaging for it.

## New agent

Type a prompt and pick a folder (the board's to start with), then pick how it
runs:

- **Chat in IDE** opens it as a new chat tab in Cursor, VS Code … (picked
  under **Editor**). The editor's command-line tool (`cursor`, `code` …)
  opens that folder, or brings up the window that has it, before the chat
  opens there. The editor must
  [trust the folder](limits.md#the-editor-must-trust-the-folder). With the
  folder box empty, the chat opens in the editor window you used last.
  - The chat gets your prompt as a message from Let Them Talk. A notice says
    whether it arrived (with **Copy prompt** if not).
  - **Name** is its card's name on the board; its tab in the editor keeps its
    own title.
  - **Model** is the model its replies run on (see
    [The model of a Chat in IDE](how-it-works.md#the-model-of-a-chat-in-ide)).
    The editor's model menu still shows its own, and a model you pick there
    wins.
  - It starts with its usual permissions: an editor link can't carry them.
- **Terminal/background agent** starts a background agent there, in a folder
  Claude Code already trusts, with the permissions and model you pick. Its
  terminal opens unless you untick that. With **Ultracode** ticked, it starts
  with ultracode on (see [Ultracode](#ultracode)), also each time a prompt
  wakes it later.

The folder box's drop-down (its chevron) lists the folders you're working
in: the board's, the sidebar's and those of the board's running chats (typing
narrows the list). It leaves out other chats' worktrees
(`.claude/worktrees/…`). Typing a path, **Browse…** and the place buttons
still reach any folder.

Images go with the prompt as they do in a chat's
[Send box](#send-a-message): paste them into the prompt box or drop them on
the dialog. A background agent or workflow gets them in its first prompt, a
Chat in IDE in the message with your prompt, once it has opened.

A new agent goes on the board you started it from.

## New workflow

**New workflow** (top bar): say what it should do, and optionally how many
agents and which model. It starts a background agent of its own, not tied to
any chat, in the folder you pick, whose first prompt is *Use a workflow to do
this: …*. The model you pick runs it and its agents, which show under
[Subagents](#subagents). Its card is named *workflow* and the task's first
words unless you name it.

Or build a team: scroll down to **Team**, pick **How many agents?** (up to 8)
and give each agent a **Role** (*tester*, *writer* …) and a **Prompt**, its
part of the work, in its own section (click its title to fold it; folded, it
shows the role, the model and effort unless they are Opus and Default (*on
Haiku, low effort*), and the start of the prompt). The prompt at the top then
goes to the master. The master and its agents are background agents in
that folder, with the permissions (and **Ultracode**, if ticked) you picked,
and none opens a terminal. Each one has its own **Model** (Fable, Opus,
Sonnet or Haiku) and **Effort** (low to max, or **Default**: Claude Code's
own): the master's at the top, each agent's beside its role. Unless you pick
others, all run on Opus with the default effort. On Haiku, auto mode may not
be available, and one on it then asks before it acts.

- The agents start first and wait: each one's first prompt says its role,
  that it is on a team, the master's name, and to wait for the master's
  message with its task, then report back to the master.
- Then the master starts, with your prompt (and any images you added, which
  only the master gets) and the plan: each agent's name, role, model (and
  effort, if picked) and prompt, to send each one its prompt in full as its
  task and gather their reports.
- The master is named as you name it (up to 30 characters; else after the
  prompt's first words that fit, e.g. *Fix the login*), each agent after the
  master and its role (*Fix the login - tester*), with a number added to the
  master's name if a running chat, or a team still starting, has one of those
  names (messages find chats by name). Roles and names take letters, digits,
  spaces, - and _.
- Their cards go side by side, the agents in a column right of the master,
  and an arrow each way links the master with each agent (*task* and
  *report*; none between agents). These arrows send no notes, as the first
  prompts already introduce them; click one to follow what the two send each
  other.
- Every role and prompt is checked before anything starts (the box that needs
  a fix gets the cursor). Notices and Activity say how it goes: one that
  didn't start (and why) is named, one that doesn't come up running within 90
  seconds is removed, and the master is told to do its part itself; an agent
  whose arrow back can't be made keeps no arrow at all, and the notice says
  why.

## Cards

- *name shared* on a card means another running session has the same name
  (see [Sessions are addressed by name](limits.md#sessions-are-addressed-by-name)).
- A card that has ended or can't receive notes has no handle.

## Subagents

**Subagents** (top bar) shows the subagents and workflow agents each chat is
running now, as small cards linked to it; each goes away when it finishes.
Past six, the first five show and the rest fold into *+N more running*; click
it to show them all (**Show fewer** folds them again).

Click one (or its row in the [Agents in this chat](#agents-in-this-chat)
pop-up) to see what it is doing: its state, a short list of facts (model,
time, tokens, its workflow and phase or its type, and the chat that started
it, a button with that chat's dot, as on its card, that goes back to the
chat), its latest steps as a timeline, its latest message and the task it was
given. The button at the top (a chevron and that chat's name) goes back to
its details.

A subagent runs inside the chat that started it, and only that chat can reach
it. While that chat runs:

- **Send it a message:** the same box as a chat's Send box, under its facts:
  type and press Enter (or the round send button); paste or drop images to
  send them too. It goes to the chat that started it, which passes it on word
  for word (with `SendMessage`, images included) and tells you if it can't.
  The line under the box says when the last one went.
- **Open in terminal** (a background agent's subagent): opens that agent's
  terminal (`claude attach`), where Claude Code lists its subagents under the
  prompt box; pick this one with ↑/↓ to watch it or type to it. A subagent of
  a chat in a terminal or in Cursor says where it runs instead.

While it is on, the button shows how many are running. If nothing is running
when you turn it on, a note says so.

## Rename a card

Double-click it, press F2 on it, or click ✎ beside the name in its details.
Type a name and press Enter (Esc cancels).

- A running background agent is renamed itself: the app types `/rename` into
  it, so Claude Code, every board and messages to it use the new name.
- Any other chat gets the name on this board only, Activity included. It
  keeps its own title and `@address`, so notes and messages still reach it
  (run `/rename` in the chat to rename it itself).
- **Use its title** (or an empty name) goes back to the chat's title.

## Details

Click a card to open its details.

### Recent messages

The last 3 messages, like a phone: your prompts as typed (including ones sent
while it worked; ones typed in its own window while it works show as *queued*
until it reads them), and Claude's finished replies and notes from other
sessions as a short TL;DR when they are long (**Full reply** / **Show all**
shows the whole text). While it works, a *now* line shows its current step.

A question it asks you shows with its options, and so does a plan waiting for
your approval (for a background agent also a permission prompt, read off its
screen). A button answers it: **Open its terminal to answer** for a
background agent, **Answer in Cursor** (or your editor) for an editor chat. A
chat in a terminal is answered in that terminal.

### Send a message

Your text shows at once as your bubble: *sending…*, then *sent, not read
yet*, then *You, from here* once the chat reads it. A running chat reads it
between steps.

An idle background agent gets it as its next prompt (the box then says
**Send a prompt**, and your bubble ends as *You*). While its process runs, it
is typed into its prompt box as if you typed it there, so it keeps running
and its open terminal stays and shows it. If you have unsent text in that
terminal, or it is asking you something there, nothing is typed. One whose
process has ended is woken with it.

Images go with it as in Claude Code: paste a screenshot (Ctrl+V) or drop
image files anywhere on the chat's details (the panel shows where they go).
Each shows as a thumbnail; × takes it out. PNG, JPEG, GIF or WebP, up to 5 at
a time, 10 MB each; images can go without text.

If sending fails, the text and images go back into the box. When the chat
waits for you, the box shows a likely reply in grey (see
[Reply suggestions](how-it-works.md#reply-suggestions)); press Tab (or →) to
use it. Enter sends, Shift+Enter adds a line.

### Agents in this chat

**Agents in this chat** is one row, with how many agents there are and how
many run now. Click it to open the workflows and subagents the chat started
in a pop-up over the board. The pop-up has two panes: the agents on the left,
under a title that stays while the list scrolls, and the one picked on the
right.

- On the left, each workflow is a card: its name, its state (*Running*,
  *Done*, *Failed*, *Stopped* …), how long it has gone on, how far it got
  (*3 of 5 done*, as words and as a thin bar, failed ones in red) and its
  agents under their phases. In a narrow card the state shows by its icon
  alone. The chat's own subagents are a card too. Each
  agent has an icon for its state (a turning ring while it runs, a check, a
  cross, a clock while it waits) and, quietly at the right, how long it ran;
  what a running one is doing now is in its tooltip. A card folds and
  unfolds.
- Click an agent to see it on the right while the list stays where it is: its
  state, model, time, tokens and tool calls (when the server knows them), the
  chat that started it (click it to go back to that chat), its steps as a
  timeline, its latest message and the task it was given. What the list
  knows of it shows at once, the rest when its details come. The pop-up opens
  on the first agent that is running (its card unfolds if you had folded it),
  or with *No agent picked* if none runs.
- A narrow window shows one pane at a time: **All agents** (with a chevron)
  goes back to the list.

A workflow has **Ask to stop** in its card while it runs and **Ask to
resume** once it stopped or failed; each sends the chat a message asking for
that. The chat's details stay underneath; ×, Esc or a click outside closes
the pop-up.

With the keyboard: Tab enters the list at the picked row, ↑ and ↓ move the
pick (also from a card's header or its button), Home and End go to the first
and last row in view, and Enter or Space pick the row in focus. If the agent
picked (or the one in focus) drops out of the list, say because a workflow
started it over, the pick and the focus move to the next agent, else the one
before, and the arrows go on from there.

### Continue in IDE

**Continue in IDE** (an ended chat with no editor of its own; the IDE picked
under [Settings](#settings)) opens its folder, then the conversation in
Cursor's Claude panel there, since Cursor finds a chat only in a window on
its folder. The editor must
[trust the folder](limits.md#the-editor-must-trust-the-folder). If the editor
can't be asked, the notice says what to run instead (`cursor "<folder>"`).

### Open in terminal (an editor chat)

An editor chat's details have **Open in terminal** beside **Open in IDE**:
`claude --resume <id>` in a new terminal window, in the chat's folder. Only
one place can run a conversation (Claude Code lets a second one start, and
both then write to it), so a chat that is open in the editor asks first, then
closes there, and opens in the terminal; one that isn't open in the editor
(its card has ended) opens at once. The agents a chat runs (subagents and
workflows) run inside it and stop with it, so the question says how many are
running (*Its 2 running agents stop too.*), and leaves that out when none
are. See
[Moving an editor chat to a terminal](how-it-works.md#moving-an-editor-chat-to-a-terminal)
for how it is closed and what the editor shows. The card then shows a chat in
a terminal. A chat with no saved conversation yet can't be continued in a
terminal; it is refused before anything closes. If no terminal can be opened,
the notice says what to run (`claude --resume <id>`); a chat running on
Windows has no button.

## Background agents

A background agent's details have these buttons:

- **Open in terminal**: `claude attach <id>` in a new window.
- **Open in IDE**: its folder, then its conversation in the IDE's Claude
  panel, as [Continue in IDE](#continue-in-ide) does, to go on with it there.
  Only one place can run a conversation, so a running agent asks first, then
  ends here with `claude stop`, its terminal windows closing, and its card
  turns into the IDE's chat.
- **Show its screen** (click again to hide). It reads **What is it asking?**
  while the agent waits for you.
- **Compact**: Claude Code's `/compact`, after asking you. Claude Code
  replaces its conversation so far with a summary, so it goes on with its
  context freed (its conversation file keeps every message). The app types
  `/compact` into its prompt box, as you would in its terminal; one whose
  process has ended is woken with it. Not while it works or asks you
  something (the button waits). Meanwhile the button says *Compacting…*; a
  notice and Activity say when it's done, with its context before and after
  (*from 120k to 6k tokens*), or Claude Code's answer if it didn't compact
  (*Not enough messages to compact.*). In any other chat, type `/compact`
  yourself. How it works: [Compacting](how-it-works.md#compacting).
- **Stop** (while it works or shows a permission prompt or a question): Esc
  through `claude attach`, so it stops what it is doing, or declines the
  prompt, and waits for you. It keeps running and its terminal stays open.
- **End agent** (while it runs): `claude stop`. It exits and its terminal
  windows close, as [End this chat](#end-this-chat) does for a chat in a
  terminal. Its card stays, and a prompt wakes it. It is refused until the
  agent's first reply is saved: ended before that, it could only be
  restarted.
- **Delete agent**: `claude rm`, which removes it from Claude Code's list,
  with its worktree if it has one. Its conversation file stays.
- **Restart in terminal**: an agent whose process ended before its first
  reply finished (`claude stop`, a crash) has no saved conversation and can't
  be woken; its card says *needs restart*. This button runs
  `claude respawn <id>` in a terminal, where Claude Code can ask you to trust
  its folder.

## Ultracode

In a running background agent's details. With ultracode on, the agent runs a
workflow (a team of agents) for every bigger task without being asked each
time.

The line says *Ultracode is on* or *off*, as its conversation shows it, with
**Turn off** or **Turn on**. The app types `/effort ultracode off` (or `on`)
into its prompt box, as you would in its terminal, also while it works. A
notice shows Claude Code's answer, or why it can't: workflows off under
`/config`, or a model without ultracode. The app keeps what it switched, also
across a restart of the app.

It lasts until the agent ends. One started with **Ultracode** ticked in
[New agent](#new-agent) starts with it again when woken.

Switching it in the agent's own terminal counts too: `/effort ultracode on`
(or `off`), or Tab and Enter in its Effort panel. While the agent is idle,
the line follows at once. While it works, Claude Code shows its answer only
on that screen, so the line keeps what it said until Claude Code tells:

- With the [suggestions mod](configuration.md#suggestions-mod) loaded in the
  agent, once its turn ends: the mod then runs `/effort status` in it, and
  the app reads its answer. You see that line in the agent's terminal, not
  in its messages here.
- Without the mod, at its next prompt.

A switch Claude Code turns down, and the panel opened only to look and closed
with Esc, change nothing.

After a restart its conversation doesn't tell yet, so while its details are
open the app finds out, once, when it is idle (if it is working, as soon as
it stops). It types `/effort` into its prompt box, reads *Ultracode on* (or
*off*) in the effort panel that opens, and closes the panel with Esc,
changing nothing. Meanwhile the line says *Ultracode: checking…*. Claude Code
notes the cancelled `/effort` in the conversation; the board doesn't show it.
If the panel has no Ultracode line (a model without it), the line says
*Ultracode: unknown* until its next prompt, with both buttons.

In any other chat, type `/effort ultracode on` (or `off`) yourself.

## A chat sent to the background

A chat you send to the background keeps its card: the card, with its arrows,
moves to the background agent that goes on with it.

## Remove from board

In a card's details. Its arrows go too (the button says how many, and you are
asked first). With **Tell connected agents** ticked (the default), the
running ends of those arrows get the same note as with **Disconnect** (see
[Arrows](#arrows)). A session that is still running goes back under *Add
agents*.

## End this chat

For a chat in a terminal: its Claude Code exits as if you closed the window,
which stays open. The conversation is kept; `claude --resume <id>` continues
it. Chats in an editor are closed there (or moved to a terminal with
[Open in terminal](#open-in-terminal-an-editor-chat)).

## Hand off to a new agent

In a card's details. A copy of the chat writes a handoff with the `/handoff`
skill that comes with the app (nothing to install). Then a new background
agent in the chat's folder, with its model and permissions, starts by reading
it; its card appears beside the chat's and its terminal opens. The chat
itself is left as it is: end it, or let it go on. Works for ended chats too.
How the handoff is written:
[Handoffs](how-it-works.md#handoffs).

The new agent gets exactly the chat's permission mode, as its transcript last
notes it; if that can't be read, nothing is handed off. A bypass-mode chat
needs Claude Code's bypass warning accepted once
(`claude --dangerously-skip-permissions`).

## Keyboard

- Tab reaches cards, arrow labels and subagent cards (the board moves to show
  the one in focus). Enter or Space opens it, with focus in its details (Tab
  goes on from there), and F2 renames a card.
- When the details close, focus goes back to the card or arrow they were
  opened from.
- Esc cancels an arrow you are drawing. Esc or a click on the empty board
  closes the details. Esc in **Settings** closes only that.

## Notices

Notices (bottom right) say how an action went. Most go after a few seconds.
These stay until you close them (×): a command to run in a terminal, the
resume command after **End this chat**, a new editor chat that didn't get
your prompt, and anything that failed. A failed **Disconnect** or **Remove
from board** leaves the details open.

If the server stops answering, a banner at the bottom says so and the board
fades until it answers again. A fault in the page itself shows as a notice
instead (once), so the banner only ever means the server.

## Settings

**Settings** (the gear next to *Let Them Talk*) holds:

- The **IDE** that **Open in IDE**, **Chat in IDE** and a chat's **Open in** /
  **Continue in** use (Cursor, VS Code …). Until you pick one, it is the one
  most of the board's chats run in. **New agent** can pick another for one
  chat.
- The theme: **System**, **Light** or **Dark**.
- The **Glass** slider, from *Clear* to *Tinted* (see
  [Glass and fonts](#glass-and-fonts)).

## Glass and fonts

The sidebar, the top bar, the Board list, the details and the dialogs are glass over the
board. In Chromium browsers (Chrome, Edge …) the board bends at each panel's
edge; other browsers show a plain blur. With reduced transparency on in your
system the panels are solid (in browsers that report that setting, such as
Chrome and Edge).

Text uses your system's font: Segoe UI Variable on Windows 11, Segoe UI on
Windows 10 (Segoe UI Variable once you
[install it from Microsoft](https://aka.ms/SegoeUIVariable)), SF Pro on a
Mac, and elsewhere (e.g. Linux) Selawik, which comes with the app.

## What the page remembers

In this browser, the page remembers:

- the board you had open, panel widths, and each board's pan and zoom;
- whether Activity, the line under a chat's title and a chat's Connections
  list are open;
- your Settings and Subagents choices;
- the notices about new editor chats and handoffs you have already seen, so a
  reload doesn't show them again.
