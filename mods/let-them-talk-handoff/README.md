# let-them-talk-handoff

The skill behind **Hand off to a new agent**. Let Them Talk loads this folder
as a plugin (`--plugin-dir`) only for the headless copy of the chat that writes
the handoff, and calls the skill as `/let-them-talk-handoff:handoff`. Nothing
is installed into your Claude Code, and your own `/handoff` skill, if you have
one, is left as it is.

`skills/handoff/SKILL.md` is Matt Pocock's `handoff` skill from
<https://github.com/mattpocock/skills> (`skills/productivity/handoff`),
unmodified apart from being an earlier revision of that file. It is under the
MIT License; see `skills/handoff/LICENSE`.
