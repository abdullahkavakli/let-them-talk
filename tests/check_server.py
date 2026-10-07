#!/usr/bin/env python3
"""Checks parts of server.py without a server: where new cards go, and New
agent → Chat in IDE in a folder. Every program launch, session list and
message is faked, so nothing opens and nothing is sent. Needs only Python.

Run:  python3 tests/check_server.py      Exit 0: all passed. 1: a check failed.
"""
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server as S  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


# ------------------------------------------------------------ where cards go

def board_of(*spots):
    return {"nodes": {f"s{i}": {"x": x, "y": y} for i, (x, y) in enumerate(spots)}}


group = board_of((-900, -880), (-630, -880), (-900, -730), (-630, -730), (-360, -800))
x, y = S.free_slot(group)
check("cards: a new card doesn't overlap any", not S.overlaps(group, x, y))
near = min(abs(x - n["x"]) + abs(y - n["y"]) for n in group["nodes"].values())
check("cards: a new card goes beside the group, even one dragged far from 0,0", near <= 300, f"went to {x}, {y}")
check("cards: an empty board starts at the top left", S.free_slot({"nodes": {}}) == (40, 40))

# --------------------------------------------- Chat in IDE in a folder (faked)

launched, sent, sessions = [], [], []
S.subprocess.Popen = lambda args, **kw: launched.append(list(args)) or types.SimpleNamespace(wait=lambda timeout=None: 0)
S.shutil.which = lambda name: {"code": "/bin/code", "cursor": "/bin/cursor", "rundll32.exe": "/win/rundll32.exe",
                               "cmd.exe": "/win/cmd.exe", "xdg-open": "/bin/xdg-open"}.get(name)
S.relay_send = lambda items: (sent.append(items) or [{"state": "sent", "detail": ""}], None)
S.load_board = lambda bid: {"nodes": {}, "activity": []}
S.save_board = lambda board: None
S.add_activity = lambda board, text, level: None
S.live_sessions = lambda: list(sessions)
S.FOLDER_SETTLE = 0.05
S.LAUNCH_WAIT = 6
real_sleep = time.sleep
quick = types.SimpleNamespace(**{k: getattr(time, k) for k in ("time", "monotonic", "strftime")},
                              sleep=lambda s: real_sleep(min(s, 0.02)))
S.time = quick  # the watcher's 1.5 s polls, made quick (this module's own sleeps stay real)

folder, elsewhere = tempfile.mkdtemp(), tempfile.mkdtemp()
fake = lambda sid, cwd: {"sessionId": sid, "name": sid, "entrypoint": "claude-vscode", "cwd": cwd,
                         "startedAt": time.time() * 1000}


def finish(lid, at_least=0.0):
    end = time.time() + 5
    while time.time() < end and S.launches[lid]["state"] in ("waiting", "sending"):
        real_sleep(0.02)
    return S.launches[lid]


launched.clear(); sessions.clear()
r = S.start_editor_chat("b", {"prompt": "hi", "editor": "VS Code", "folder": folder})
sessions[:] = [fake("other", elsewhere), fake("mine", folder)]
job = finish(r["launchId"])
check("IDE chat: the folder opens in the editor, then the chat link, from the server",
      r["opensChat"] and launched[:1] == [["/bin/code", folder]] and "anthropic.claude-code/open" in " ".join(launched[1]))
check("IDE chat: the chat in that folder gets the prompt, not one elsewhere",
      job["session"] and job["session"]["sessionId"] == "mine" and sent and sent[-1][0]["to"] == "mine", job["detail"])

launched.clear(); sessions.clear()
r = S.start_editor_chat("b", {"prompt": "", "editor": "VS Code"})
sessions[:] = [fake("plain", elsewhere)]
job = finish(r["launchId"])
check("IDE chat: no folder means the page opens the link, as before",
      not r["opensChat"] and not launched and job["session"]["sessionId"] == "plain")

launched.clear(); sessions.clear()
r = S.start_editor_chat("b", {"prompt": "", "editor": "Cursor", "folder": folder})
sessions[:] = [fake("stray", elsewhere)]
S.launches[r["launchId"]]["at"] -= S.LAUNCH_WAIT / 3 + 1
job = finish(r["launchId"])
check("IDE chat: one that opens in another folder is kept, and the notice says where",
      job["session"]["sessionId"] == "stray" and elsewhere in job["detail"], job["detail"])

for body, why in (({"editor": "Windsurf", "folder": folder}, "its tool missing"),
                  ({"editor": "Notepad", "folder": folder}, "an unknown editor"),
                  ({"editor": "VS Code", "folder": os.path.join(folder, "missing")}, "a missing folder")):
    try:
        S.start_editor_chat("b", body)
        check(f"IDE chat: refused up front with {why}", False)
    except ValueError:
        check(f"IDE chat: refused up front with {why}", True)

launched.clear()
check("open_in_editor: a Windows folder cmd would split (&) isn't run", not S.open_in_editor("VS Code", "C:\\R&D")["opened"])
S.open_editor_link("VS Code", session="a b&c")
check("open_editor_link: values encoded twice, like the page", launched and launched[-1][-1].endswith("?session=a%2520b%2526c"))
S.ON_WSL, on_wsl = True, S.ON_WSL
S.open_editor_link("Cursor", session="x")
S.ON_WSL = on_wsl
check("open_editor_link: from WSL through Windows' link handler, which keeps ?session= (explorer.exe drops it)",
      launched[-1] == ["/win/rundll32.exe", "url.dll,FileProtocolHandler", "cursor://anthropic.claude-code/open?session=x"])

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{f'  ({detail})' if detail and not ok else ''}")
print(f"server checks: {len(results) - len(failed)} of {len(results)} passed")
sys.exit(1 if failed else 0)
