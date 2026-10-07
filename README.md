# Let Them Talk

An agent organizer for Claude Code: a local board where each running session
is a card, and an arrow from one card to another tells both, in a note from
`@let-them-talk`, who they are connected to and why.

## Install

Needs Python 3.12 or newer and Claude Code (`claude`). On Windows, both must
be installed inside WSL, where the server runs. Nothing else to install: the
server uses only Python's standard library.

## Start

- Windows: double-click `Start Let Them Talk.bat`; it starts the server in
  WSL and opens the page.
- macOS, Linux or WSL: `./start.sh`, then open <http://localhost:8765>.

## Try it

1. Start two Claude Code chats in the same folder, e.g. `~/my-project`.
2. On the page, click **New board** and pick that folder. Sessions running in
   it (or below it) appear on their own, one card each.
3. Drag the blue handle on one card onto the other card. Say why if you like
   (without a reason, the two tell each other what they work on), then
   **Connect**. Both chats get a note; the one the arrow starts from goes
   first, the other replies.
4. Click the arrow to see what the two send each other.

That is the whole idea: start agents, connect them, and say who hands what to
whom.

## More

- [Using it](docs/usage.md): boards, arrows, new agents and workflows, a
  chat's details, background agents, handoffs, settings.
- [How it works](docs/how-it-works.md): where sessions come from, how notes
  are sent, what is stored where, and how the server stays local.
- [Configuration](docs/configuration.md): environment settings and the
  optional mod behind reply suggestions.
- [Limits](docs/limits.md): what it can't do yet.

## License

[Apache License 2.0](LICENSE). The Selawik font files in `static/fonts/` are
Microsoft's, unmodified, under the SIL Open Font License 1.1
(`static/fonts/LICENSE-Selawik.txt`). The `/handoff` skill in
`mods/let-them-talk-handoff/skills/handoff/` is Matt Pocock's, from
[mattpocock/skills](https://github.com/mattpocock/skills), under the MIT
License (`mods/let-them-talk-handoff/skills/handoff/LICENSE`).
