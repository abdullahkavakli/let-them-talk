# Security

## What the app can do

Let Them Talk runs on your own computer, next to Claude Code. It reads Claude Code's local session files and transcripts, starts agents, and sends messages to your running chats. Whoever can use the app can do all of that as you, so it is closed to everything but you:

- It listens only on 127.0.0.1, so other computers can't reach it.
- It answers only requests addressed to `localhost` or `127.0.0.1` on its own port, so a web page can't reach it by another name that points to your computer.
- Every request that sends a message, starts an agent or changes a board is a POST, and needs a custom header (`X-Let-Them-Talk`). A browser sends that header from another website only after asking the server first, and the server never says yes, so other websites can't send it commands.
- Its pages can't be put inside another site's frame.
- Images you send are saved in a folder only you can open, each readable only by you, under a random name.

It has no password or login: a program running on your computer can send the header too. The app itself makes no requests to the internet. The notes, summaries and handoffs it asks for are written by Claude Code runs it starts, and those go to Anthropic like any other Claude Code run.

## Report a problem

Please don't open a public issue for a security problem. On GitHub, open the **Security** tab, click **Report a vulnerability** and describe what you found and how to repeat it. The report stays private between you and the maintainer.

## Supported versions

The latest release and the `main` branch.
