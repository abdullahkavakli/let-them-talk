# Using Let Them Talk

What each part of the board does, from boards and arrows to a chat's details.

## Boards

- **Boards belong to folders.** Sessions running in the board's folder (or
  below it) appear on their own. Ones from other folders are listed under
  *Add agents*, where a row's **+** puts it on the board and **+ New agent**
  next to a folder opens [New agent](#new-agent) on that folder.
- **New board** takes any existing folder (`C:\...`, `/mnt/c/...`, `~/...`),
  typed or picked with **Browse…**, or picked from its ▾ list of folders with
  running sessions. It suggests those that have no board yet (other chats'
  worktrees left out). A folder has one board, so **New board** on a folder
  that has one opens it.
- Switch boards with **Board** in the top bar.
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
failed, and grey and dotted once either chat has ended. Click one (its line
or its label) to see why and when it was connected, and:

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

The folder box's ▾ lists the folders you're working in: the board's, the
sidebar's and those of the board's running chats (typing narrows the list).
It leaves out other chats' worktrees (`.claude/worktrees/…`). Typing a path,
**Browse…** and the place buttons still reach any folder.

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

## Cards

- *name shared* on a card means another running session has the same name
  (see [Sessions are addressed by name](limits.md#sessions-are-addressed-by-name)).
- A card that has ended or can't receive notes has no handle.

## Subagents

**Subagents** (top bar) shows the subagents and workflow agents each chat is
running now, as small cards linked to it; each goes away when it finishes.
Past six, the first five show and the rest fold into *+N more running*; click
it to show them all (**Show fewer** folds them again).

Click one (or its row under [Agents in this chat](#agents-in-this-chat)) to
see what it is doing: its state, model, time and tokens, its latest steps,
its latest message, the task it was given, its workflow and phase (or its
type) and the chat that started it. The **←** button at the top, with that
chat's name, goes back to its details.

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

**Agents in this chat (N)** is one line, with how many are running. Click it
to open the workflows and subagents the chat started in a pop-up over the
board, with their state, model, time and tokens, and a running one's current
step. Click one to see what it is doing in the pop-up (**← All agents** goes
back).

A workflow has **Ask it to stop this workflow** while it runs and **Ask it to
resume this workflow** once it stopped or failed; each sends the chat a
message asking for that. The chat's details stay underneath; ×, Esc or a
click outside closes the pop-up.

### Continue in IDE

**Continue in IDE** (an ended chat with no editor of its own; the IDE picked
under [Settings](#settings)) opens its folder, then the conversation in
Cursor's Claude panel there, since Cursor finds a chat only in a window on
its folder. The editor must
[trust the folder](limits.md#the-editor-must-trust-the-folder). If the editor
can't be asked, the notice says what to run instead (`cursor "<folder>"`).

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
`/config`, or a model without ultracode.

It lasts until the agent ends. One started with **Ultracode** ticked in
[New agent](#new-agent) starts with it again when woken.

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
it. Chats in an editor are closed there.

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

The sidebar, the top bar, the details and the dialogs are glass over the
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
