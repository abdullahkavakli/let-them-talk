# Limits

What the app can't do, and what to do instead.

## A note is only a message

A note arrives as a message from another session: it cannot approve
permission prompts or change settings, and it starts a turn in an idle agent.
A session running with bypassed permissions holds it for approval.

## Arrows don't block other messages

An arrow tells agents who to talk to and why; it does not stop other sessions
from messaging each other.

## Subagents can't be connected

Only sessions can be connected. Subagents (the small cards under
[Subagents](usage.md#subagents)) can't be reached from outside, so connect
their parent session. A message you send a subagent from its details goes the
same way: to its chat, which passes it on.

## Sessions are addressed by name

If two sessions share a name (background agents that aren't running count
too), `/rename` one of them first (renaming only the card isn't enough: see
[Rename a card](usage.md#rename-a-card)).

## Windows sessions

Sessions of Claude Code on native Windows are shown with a *Windows* badge.
Two of them can be connected and get each other's notes. A WSL session and a
Windows session can never message each other, so such an arrow can't be made.

Only the notes of an arrow reach a Windows session. Text typed in the Send
box, a new chat's prompt, images, Hand off, Open in terminal and End this chat
don't work for them.

The notes need `claude.exe` (Claude Code on Windows) and a Windows Claude
Code recent enough to receive messages. When either is missing, the chat's
details say so, and it can't be connected until that is fixed (see
[`LTT_WIN_CLAUDE`](configuration.md#environment-settings)).

## Conversation length

An arrow's **Conversation** shows the latest 50 messages; **Show … earlier**
loads 50 more at a time, up to 500. A message addressed by name rather than
to the chat's socket shows only once the other chat has read it.

## Terminals

Terminals open in Windows Terminal (or a console window) from WSL, in
Terminal on macOS and through `x-terminal-emulator` on Linux. Without one,
**Open in terminal** shows the command to run instead, and a new agent's
terminal doesn't open.

## The editor must trust the folder

A **Chat in IDE** and **Continue in IDE** need the editor to trust the
folder: in Restricted Mode, Claude Code is off.

## Unmounted drives

A folder on a drive WSL hasn't mounted (e.g. Google Drive's `G:`) can't be
used. Mount it first: `sudo mount -t drvfs G: /mnt/g`.
