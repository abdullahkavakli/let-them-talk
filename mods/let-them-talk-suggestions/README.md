# let-them-talk

The Claude Code plugin of [Let Them Talk](https://github.com/abdullahkavakli/let-them-talk), a visual board for your Claude Code sessions. It does three things:

- **`/let-them-talk`**, typed in any chat, starts Let Them Talk with `uvx let-them-talk` and opens it in your browser. It needs [uv](https://docs.astral.sh/uv/). The board keeps running after that chat ends; if it already runs, the command only opens it.
- It passes Claude Code's suggested next prompt on to the board, so the Send box of a terminal chat shows the same grey suggestion as the chat's own prompt box.
- It runs a **Chat in IDE** started from the board on the model you picked in **New agent**.

It runs no command in your chats by itself, so nothing of its own appears in their terminals. The suggestion and the model need Let Them Talk running on port 8765, the default. It talks only to the app on your own machine, and does nothing when the app isn't running.

## Install

```
claude plugin marketplace add abdullahkavakli/let-them-talk
claude plugin install let-them-talk@let-them-talk
```

Or, inside a chat: `/plugin install let-them-talk --marketplace abdullahkavakli/let-them-talk`.

It was called `let-them-talk-suggestions` before. If you installed it under that name, remove the old one: `claude plugin uninstall let-them-talk-suggestions@let-them-talk`.

The plugin is the mod of the latest release, the same release as the app `uvx let-them-talk` runs, so the two match. A change made to the mod since then reaches you with the next release.

Chats started before the plugin was installed show no suggestion and have no `/let-them-talk` until they are restarted.

More, including how to load it from a copy of the repository (which then follows that copy, not the release), how to stop a board started with `/let-them-talk`, and what to do if the app runs on another port: [Configuration](https://github.com/abdullahkavakli/let-them-talk/blob/main/docs/configuration.md#claude-code-plugin).
