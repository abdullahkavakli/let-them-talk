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

Sessions of Claude Code on native Windows are shown with a *Windows* badge,
but the app can't connect them or send them messages yet (their details say
why). A WSL session and a Windows session can never message each other.

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
