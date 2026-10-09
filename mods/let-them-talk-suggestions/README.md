# let-them-talk-suggestions

A Claude Code plugin for [Let Them Talk](https://github.com/abdullahkavakli/let-them-talk), a visual board for your Claude Code sessions. It does three things:

- It passes Claude Code's suggested next prompt on to the board, so the Send box of a terminal chat shows the same grey suggestion as the chat's own prompt box.
- It runs a **Chat in IDE** started from the board on the model you picked in **New agent**.
- In a background agent, after an ultracode switch made while it works, it runs `/effort status` so the board can read the switch.

It needs Let Them Talk running on port 8765, the default. It talks only to the app on your own machine, and does nothing when the app isn't running.

## Install

```
claude plugin marketplace add abdullahkavakli/let-them-talk
claude plugin install let-them-talk-suggestions@let-them-talk
```

Or, inside a chat: `/plugin install let-them-talk-suggestions --marketplace abdullahkavakli/let-them-talk`.

Chats started before the plugin was installed show no suggestion until they are restarted.

More, including how to load it from a copy of the repository and what to do if the app runs on another port: [Configuration](https://github.com/abdullahkavakli/let-them-talk/blob/main/docs/configuration.md#suggestions-mod).
