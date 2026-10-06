# Working in this repo

Several Claude Code chats often work on this repo at once, and the running
app on :8765 serves the main folder's files live. So:

1. **Never edit files in the main folder** (the repo root). A half-finished
   edit there breaks the open page. Build in your own worktree:
   `git worktree add .claude/worktrees/<name> -b <name> main`.
   Read-only work (reading, tests on a copy, a test server on a free port)
   needs no worktree.
2. **Main moves forward only when the user says so.** Right before, check
   `git log` (main moves often), rebase your branch onto the latest main,
   then run `git merge --ff-only <branch>` from the main folder. Never reset
   or force main, and commit only your own changes.
3. **One merge at a time.** After merging, tell the other chats the new hash
   (SendMessage, by chat name). Before editing a file another chat is working
   on, tell it.
4. **Restarting the server:** if `server.py` changed, restart :8765 from the
   main folder, and only while it has no child processes (`pgrep -P <pid>`);
   a restart mid-request breaks what the user is doing.
   `nohup ./start.sh > /dev/null 2>&1 &`. Static files are served fresh, so
   they only need a page refresh.
5. **Clean up:** remove your worktree and branch once they're merged and you
   are done (`git worktree remove`, `git branch -d`). Never remove another
   chat's worktree; it may be that chat's working folder.

The backup is the private GitHub repo `origin`; push main there after merging.
