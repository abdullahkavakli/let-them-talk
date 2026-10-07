#!/usr/bin/env python3
"""Checks parts of server.py without a server: where new cards go, New
agent → Chat in IDE in a folder, renaming a card, and images sent with a prompt. Every
program launch, session list and message is faked, so nothing opens and nothing is sent.
Needs only Python.

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
real_live_sessions, S.live_sessions = S.live_sessions, lambda: list(sessions)
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

# ------------------------------------------------ Rename a card (typing faked)

typed, board = [], {"nodes": {"bg": {"alias": "mine"}, "ide": {}, "nap": {}}, "activity": []}
S.load_board = lambda bid: board
S.add_activity = lambda board, text, level="info": board["activity"].append(text)
S._box_check = lambda job: None
agent = {"sessionId": "bg", "name": "old name", "title": "old name", "platform": "wsl",
         "background": True, "running": True, "jobId": "j1"}


def press(job, keys, check=None):  # Claude Code takes the new name, in a fresh registry read
    typed.append("".join(k for k, _ in keys))
    sessions[0] = {**agent, "name": typed[-1].removeprefix("/rename ").rstrip("\r")}


S._press_keys = press
sessions[:] = [agent,
               {"sessionId": "ide", "name": "ide-1", "platform": "wsl", "background": False, "running": True},
               {"sessionId": "nap", "name": "nap", "platform": "wsl", "background": True, "running": False},
               {"sessionId": "x", "name": "Taken", "platform": "wsl", "background": False, "running": True}]
r = S.rename_node("b", {"sessionId": "bg", "name": "  new   name "})
check("rename: a running background agent gets /rename typed into it",
      typed == ["/rename new name\r"] and r["renamed"] == "new name", typed)
check("rename: its card drops the board's own name, and Activity says so",
      "alias" not in board["nodes"]["bg"] and board["activity"][-1] == 'Renamed "mine" to "new name"', board)
typed.clear()
for sid in ("ide", "nap"):
    S.rename_node("b", {"sessionId": sid, "name": "Card only"})
check("rename: a chat in a terminal or an editor, or an asleep agent, gets the name on this board only",
      not typed and board["nodes"]["ide"]["alias"] == board["nodes"]["nap"]["alias"] == "Card only")
sessions[0] = agent
try:
    S.rename_node("b", {"sessionId": "bg", "name": "taken"})
    check("rename: a name another running chat has is refused", False)
except ValueError:
    check("rename: a name another running chat has is refused", not typed)
S._press_keys, S.RENAME_WAIT = (lambda job, keys, check=None: None), 0.2
try:
    S.rename_node("b", {"sessionId": "bg", "name": "never taken"})
    check("rename: a name that doesn't change in time is reported", False)
except ValueError as e:
    check("rename: a name that doesn't change in time is reported", "hasn't changed" in str(e), str(e))

# ------------------------------- Open in IDE: a running background agent ends first

home = tempfile.mkdtemp()
board = {"folder": home, "nodes": {"s1": {"cwd": home}}, "activity": []}
order, rows = [], [{"id": "j1", "sessionId": "s1", "pid": 7}]
S.background_rows = lambda fresh=False: rows
S.has_transcript = lambda sid: True
S.run_claude = lambda args, **kw: order.append(" ".join(["claude", *args])) or types.SimpleNamespace(
    returncode=0, stdout="", stderr="")
S.open_in_editor = lambda editor, folder: order.append("folder") or {"opened": True, "command": ""}
S.open_editor_link = lambda editor, **params: order.append(f"link {params['session']}") or True
r = S.open_folder("b", {"sessionId": "s1", "editor": "Cursor", "continue": True, "end": True})
check("open in IDE: a running background agent ends (claude stop) once its folder opens, before the link",
      order == ["folder", "claude stop j1", "link s1"] and r["ended"] == "j1", order)
order.clear()
S.open_folder("b", {"sessionId": "s1", "editor": "Cursor", "continue": True})
check("open in IDE: without your yes it isn't ended", order == ["folder", "link s1"], order)
order.clear()
S.has_transcript = lambda sid: False
try:
    S.open_folder("b", {"sessionId": "s1", "editor": "Cursor", "continue": True, "end": True})
    check("open in IDE: one without its first reply saved is refused before anything opens", False)
except ValueError:
    check("open in IDE: one without its first reply saved is refused before anything opens", order == [], order)

sock = os.path.join(home, "sock")
Path(sock).touch()
reg = {"pid": 5, "sessionId": "s1", "kind": "interactive", "entrypoint": "claude-vscode", "name": "it",
       "messagingSocketPath": sock, "cwd": home}
S._read_registry, S._proc_start, S.WIN_REGISTRY_DIR = (lambda d: [dict(reg)]), (lambda pid: ""), None
S.wsl_exe = lambda pid, started: "/x/.cursor-server/extensions/anthropic.claude-code-1/resources/native-binary/claude"
S.session_title = S.session_model = lambda sid: None
rows[:] = [{"id": "j1", "sessionId": "s1", "pid": None, "state": "done"}]
took = next(s for s in real_live_sessions() if s["sessionId"] == "s1")
check("open in IDE: once the IDE goes on with it, its card is that chat, not the ended agent",
      not took["background"] and not took["jobId"] and took["editor"] == "Cursor", took)

# ------------------------------------------- Images with a prompt or message

S.CLAUDE_TMP = Path(tempfile.mkdtemp()) / "claude-test"  # not the real temp folder
S.session_title = lambda sid: None  # no transcript: the folder is named from the chat's folder
S.background_rows = lambda fresh=False: []
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
b64 = lambda data: S.base64.b64encode(data).decode()
prompts, woken, sessions[:] = [], [], [
    {"sessionId": "chat", "name": "chat", "platform": "wsl", "cwd": "/home/you/my app", "background": False,
     "running": True, "messageBlock": None, "status": "idle"},
    {"sessionId": "bg", "name": "bg", "platform": "wsl", "cwd": "/home/you/proj", "background": True,
     "running": True, "jobId": "j1", "status": "idle"},
    {"sessionId": "nap", "name": "nap", "platform": "wsl", "cwd": "/home/you/proj", "background": True,
     "running": False, "jobId": "j2", "status": "asleep"},
    {"sessionId": "win", "name": "win", "platform": "windows", "cwd": "/mnt/c/x", "background": False,
     "running": True, "messageBlock": None, "status": "idle"}]
S._type_prompt = lambda s, text: prompts.append(text)
S.run_claude = lambda args, **kw: woken.append(args) or types.SimpleNamespace(
    stdout="backgrounded · 0123abcd\n", stderr="", returncode=0)
saved = lambda: sorted(S.CLAUDE_TMP.glob(f"*/{S.IMAGE_DIR}/*"))

sent.clear()
S.send_to_session("b", {"sessionId": "chat", "text": "look", "images": [{"data": b64(PNG)}]})
files = saved()
note = sent[-1][0]["text"] if sent else ""
check("images: a message gets a line naming the saved image, as Claude Code names a pasted one",
      len(files) == 1 and note.endswith(f"look\n\n[Image: source: {files[0]}]"), note)
check("images: saved in the chat's own project temp folder, under a new random name",
      files and files[0].parent == S.CLAUDE_TMP / "-home-you-my-app" / S.IMAGE_DIR
      and S.re.fullmatch(r"[0-9a-f]{16}\.png", files[0].name) and files[0].read_bytes() == PNG, files)
check("images: the file and its folders are private (0600, 0700)",
      files and files[0].stat().st_mode & 0o777 == 0o600 and files[0].parent.stat().st_mode & 0o777 == 0o700
      and S.CLAUDE_TMP.stat().st_mode & 0o777 == 0o700)
S.send_to_session("b", {"sessionId": "bg", "text": "", "images": [{"data": b64(PNG)}, {"data": b64(b"GIF89a" + PNG)}]})
check("images: a running background agent gets them typed with its prompt, and images alone can go",
      prompts and S.re.fullmatch(r"\[Image: source: \S+\.png\]\n\[Image: source: \S+\.gif\]", prompts[-1]), prompts)
S.send_to_session("b", {"sessionId": "nap", "text": "and this", "images": [{"data": b64(PNG)}]})
check("images: an asleep one is woken with them in its prompt",
      woken and woken[-1][:4] == ["--resume", "nap", "--bg", "--"] and "and this\n\n[Image: source: " in woken[-1][4])
S.send_to_session("b", {"sessionId": "nap", "text": "just text"})
check("images: text alone goes as before", woken[-1][4] == "just text")

before = saved()
for body, why, says in (
        ({"images": [{"data": b64(b"<svg onload=alert(1)>")}]}, "something that isn't an image", "Only PNG"),
        ({"images": [{"data": b64(PNG + b"\0" * S.IMAGE_MAX)}]}, "an image over the size cap", "over"),
        ({"images": [{"data": b64(PNG)}] * (S.IMAGE_COUNT + 1)}, "more images than the cap", "at most"),
        ({"images": [{"data": "not base64!"}]}, "data that isn't base64", "didn't come through"),
        ({"images": ["x"]}, "a list of something else", "didn't come through"),
        ({"sessionId": "win", "images": [{"data": b64(PNG)}]}, "a chat running on Windows", "Windows")):
    try:
        S.send_to_session("b", {"sessionId": "chat", "text": "x", **body})
        check(f"images: refused: {why}", False)
    except ValueError as e:
        check(f"images: refused: {why}", says in str(e) and saved() == before, str(e))

old = S.CLAUDE_TMP / "-elsewhere" / S.IMAGE_DIR / "0000000000000000.png"
old.parent.mkdir(parents=True)
old.write_bytes(PNG)
os.utime(old, (time.time() - S.IMAGE_KEEP - 60,) * 2)
S.send_to_session("b", {"sessionId": "chat", "text": "new", "images": [{"data": b64(PNG)}]})
check("images: ones sent over a week ago are deleted, newer ones kept",
      not old.exists() and set(before) < set(saved()))
link = S.CLAUDE_TMP / "-home-you-proj" / S.IMAGE_DIR
for f in link.iterdir():
    f.unlink()
link.rmdir()
link.symlink_to(tempfile.mkdtemp())
try:
    S.send_to_session("b", {"sessionId": "bg", "text": "x", "images": [{"data": b64(PNG)}]})
    check("images: a link where the image folder goes is refused", False)
except ValueError as e:
    check("images: a link where the image folder goes is refused", not list(link.iterdir()), str(e))
S.shutil.rmtree(S.CLAUDE_TMP.parent)

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{f'  ({detail})' if detail and not ok else ''}")
print(f"server checks: {len(results) - len(failed)} of {len(results)} passed")
sys.exit(1 if failed else 0)
