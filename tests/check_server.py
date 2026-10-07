#!/usr/bin/env python3
"""Checks parts of server.py without a server: where new cards go, New
agent → Chat in IDE in a folder, renaming a card, images sent with a prompt and switching
ultracode or looking it up. Every program launch, session list and message is faked, so nothing opens and
nothing is sent. Needs only Python.

Run:  python3 tests/check_server.py      Exit 0: all passed. 1: a check failed.
"""
import json
import os
import sys
import tempfile
import threading
import time
import types
from datetime import datetime, timezone
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
real_popen = S.subprocess.Popen
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


real_press_keys, S._press_keys = S._press_keys, press
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

# ------------------------------------- Ultracode on/off (typing and transcript faked)

root = Path(tempfile.mkdtemp())
(root / "proj").mkdir()
S.PROJECT_ROOTS = [root]
UC = "0c0c0c0c-0000-4000-8000-00000000000c"
log = root / "proj" / f"{UC}.jsonl"
log.write_text("")


def note(rec, at):  # one transcript record, written as Claude Code writes them (no spaces)
    rec["timestamp"] = datetime.fromtimestamp(at, timezone.utc).isoformat().replace("+00:00", "Z")
    with log.open("a") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


prompt = lambda text, at: note({"type": "user", "message": {"role": "user", "content": text}}, at)
remind = lambda kind, at: note({"type": "attachment", "attachment": {"type": f"ultra_effort_{kind}"}}, at)
answer = lambda text, at: prompt(f"<local-command-stdout>{text}</local-command-stdout>", at)  # a command's output
t0 = time.time() - 100
uc = {"sessionId": UC, "name": "uc", "platform": "wsl", "background": True, "running": True,
      "jobId": "abcdef12", "startedAt": t0 * 1000}
prompt("fix it", t0 + 1)
check("ultracode: a chat that never had it reads off", S.ultracode_state(uc) is False)
answer("Ultracode on (this session only): dynamic workflows on every task. Effort stays high.", t0 + 2)
prompt("go on", t0 + 3); remind("enter", t0 + 3)
prompt("and more", t0 + 4)  # still on: Claude Code notes nothing new
check("ultracode: on once switched on, and still on at later prompts", S.ultracode_state(uc) is True)
answer("Ultracode off. Effort stays high.", t0 + 5)
check("ultracode: off once its /effort answer says so, before any prompt", S.ultracode_state(uc) is False)
restarted = {**uc, "startedAt": (t0 + 10) * 1000}
check("ultracode: not known after a restart until its next prompt", S.ultracode_state(restarted) is None)
prompt("woken", t0 + 11)  # started without it: the last reminder (enter) stands, nothing new
check("ultracode: after a restart, at its next prompt it reads from the last reminder",
      S.ultracode_state(restarted) is True)
note({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text":
     "<local-command-stdout>Ultracode off</local-command-stdout>"}]}}, t0 + 12)
check("ultracode: a reply quoting an answer isn't a switch", S.ultracode_state(restarted) is True)

typed[:] = []
board = {"nodes": {UC: {}}, "activity": []}
sessions[:] = [uc]
rules = "─" * 40


def press_uc(job, keys, check=None):  # the agent answers in its transcript, as when idle
    typed.append("".join(k for k, _ in keys))
    word = typed[-1].split()[-1]
    real_sleep(0.1)  # typing takes a moment, so the answer comes after it started
    answer({"on": "Ultracode on (this session only): dynamic workflows on every task. Effort stays high.",
            "off": "Ultracode off. Effort stays high."}[word], time.time())
    return ""


S._press_keys, S.ULTRA_WAIT = press_uc, 0.5
r = S.set_ultracode("b", {"sessionId": UC, "on": True})
check("ultracode: Turn on types /effort ultracode on and passes on Claude Code's answer",
      typed == ["/effort ultracode on\r"] and r["ultracode"] is True and r["said"].startswith("Ultracode on (this session only)")
      and board["activity"][-1] == "Ultracode on for @uc", (typed, r, board["activity"]))
# while it works the answer only shows above its prompt box; no transcript record
S._press_keys = lambda job, keys, check=None: (typed.append("".join(k for k, _ in keys))
                                               or f"✽ Working… (3s)\r\n   Ultracode off. Effort stays high.\r\n{rules}\r\n❯ \r\n{rules}\r\n")
r = S.set_ultracode("b", {"sessionId": UC, "on": False})
check("ultracode: while it works, the answer is read off its screen, and the state follows",
      r["said"] == "Ultracode off. Effort stays high." and S.ultracode_state(uc) is False, r)
S._press_keys = lambda job, keys, check=None: real_sleep(0.1) or answer(
    "Ultracode isn't available on claude-haiku-4-5. Valid options are: low, medium, high, auto", time.time()) or ""
try:
    S.set_ultracode("b", {"sessionId": UC, "on": True})
    check("ultracode: a model without it is reported with Claude Code's own words", False)
except ValueError as e:
    check("ultracode: a model without it is reported with Claude Code's own words", "isn't available" in str(e), str(e))
S._press_keys = lambda job, keys, check=None: ""
try:
    S.set_ultracode("b", {"sessionId": UC, "on": True})
    check("ultracode: no answer in time is reported", False)
except ValueError as e:
    check("ultracode: no answer in time is reported", "hasn't answered" in str(e), str(e))
sessions[:] = [{**uc, "running": False}]
try:
    S.set_ultracode("b", {"sessionId": UC, "on": True})
    check("ultracode: an asleep agent isn't typed into", False)
except ValueError:
    check("ultracode: an asleep agent isn't typed into", True)

# ------------- Ultracode unknown: the app looks in its /effort panel (screen faked)

box = lambda text: f"{rules}\r\n❯ {text}\r\n{rules}\r\n  ⏵⏵ auto mode on\r\n"
panel = lambda line: ("▔" * 40 + "\r\n   Effort\r\n\r\n      Faster          Smarter\r\n"
                      f"      ──────▲─────      {line}\r\n      low  high  xhigh  max      Tab to toggle\r\n"
                      "      Ultracode: dynamic workflows on every task\r\n\r\n"
                      "   ←/→ to adjust · Enter to confirm · s for this session only · Esc to cancel\r\n")
tui = {"panel": panel("Ultracode  on"), "typing": True, "hold": None}
pressed, started = [], {}


def press_look(job, keys, check=None):
    """`claude attach`, faked: the box shows what is typed, Enter on /effort opens
    the panel, and Esc closes it with "Cancelled" noted, as Claude Code does when idle."""
    screen, text = box(""), ""
    if check:
        check(screen)
    if tui["hold"]:
        tui["hold"].wait(5)
    pressed.append([])
    keys = list(keys)
    while keys:
        key = keys.pop(0)
        if callable(key):
            keys[:0] = key(screen)
            continue
        key = key[0]
        pressed[-1] += [key] if key else []
        if key == "\r" and text == "/effort" and tui["panel"]:
            screen = tui["panel"]
        elif key == "\x1b" and screen == tui["panel"]:
            screen, text = box(""), ""
            for rec in ("<command-name>/effort</command-name>\n<command-args></command-args>",
                        "<local-command-stdout>Cancelled</local-command-stdout>"):
                prompt(rec, time.time())
        elif key not in ("", "\r") and tui["typing"]:
            text += key
            screen = box(text)
    return screen


def look(run, status="idle", details=True, listed=None):
    """The drawer's poll for a woken agent (process run) whose registry says status
    (`claude agents`: listed, else the same), and what the look then pressed."""
    pressed.clear()
    s = {**uc, "pid": run, "startedAt": started.setdefault(run, time.time() * 1000), "status": status}
    sessions[:] = [s]
    S.background_rows = lambda fresh=False: [{"id": uc["jobId"], "sessionId": UC, "pid": run,
                                              "status": listed or status}]
    first = S.session_chat(UC, look=details)
    end = time.time() + 5
    while (S.ultra_peeks.get(UC) or (0, 0, 0))[2] is None and time.time() < end:
        real_sleep(0.02)
    return first, pressed[-1] if pressed else None, S.session_chat(UC, look=details)


# the real _press_keys, a function among its keys, on a tiny `claude attach` in a terminal
attach = Path(tempfile.mkdtemp()) / "claude"
attach.write_text(f"#!{sys.executable}\n" + r'''
import os, tty
from pathlib import Path
tty.setraw(0)
rules, typed, panel, got = "─" * 40, "", False, Path(__file__).with_suffix(".keys")
show = lambda *rows: os.write(1, ("\x1b[2J\x1b[H" + "\r\n".join(rows) + "\r\n").encode())
show(rules, "❯ ", rules)
while True:
    keys = os.read(0, 1024).decode()
    with got.open("a") as f:
        f.write(keys)
    for k in keys:
        if panel and k == "\x1b":
            panel, typed = False, ""
            show(rules, "❯ ", rules)
        elif not panel and k == "\r" and typed == "/effort":
            panel = True
            show("▔" * 40, "   Effort", "   ───▲───      Ultracode  off", "   Esc to cancel")
        elif not panel and k != "\r":
            typed += k
            show(rules, "❯ " + typed, rules)
''')
attach.chmod(0o700)
fake_popen, real_claude = S.subprocess.Popen, S.CLAUDE_BIN
S.subprocess.Popen, S.CLAUDE_BIN, S.PEEK_CLOSE = real_popen, str(attach), 0.1
began, found = time.time(), {}
drawn = S.render_screen(real_press_keys("abcdef12", S._effort_keys(found)))
took = time.time() - began
S.subprocess.Popen, S.CLAUDE_BIN = fake_popen, real_claude
got = attach.with_suffix(".keys").read_bytes()
S.shutil.rmtree(attach.parent)
check("ultracode look: in a real terminal, /effort opens the panel, its line is read, and Esc closes it",
      found.get("on") is False and got == b"/effort\r\x1b" and "❯" in drawn and "Effort" not in drawn
      and took < 3, (found, got, drawn, took))

S._press_keys, S.PEEK_OPEN = press_look, 0.1
S.screen_question = lambda job: None  # what one shows when its status says waiting
real_sleep(0.01)  # the transcript's last record is older than the next process
first, keys, then = look(101)
check("ultracode look: unknown after a restart, the open details' poll says checking and starts a look",
      first["ultracode"] is None and first["ultracodeChecking"] is True, first)
check("ultracode look: /effort typed, Enter once the box holds it, Esc once the panel is open, nothing else",
      keys == ["/effort", "\r", "\x1b"], keys)
check("ultracode look: its Ultracode line is read, and its cancelled /effort isn't taken for a switch",
      then["ultracode"] is True and not then["ultracodeChecking"], then)
S.session_chat(UC, look=True)
check("ultracode look: a known state is never looked up again", len(pressed) == 1, pressed)
tui["panel"] = panel("Ultracode  off")
check("ultracode look: off reads off", look(102)[2]["ultracode"] is False)
tui["panel"] = panel("")
_, keys, then = look(103)
again = look(103)
check("ultracode look: a panel without the line (a model without it) is closed, stays unknown, and isn't opened again",
      keys == ["/effort", "\r", "\x1b"] and then["ultracode"] is None and not then["ultracodeChecking"]
      and again[1] is None and not again[0]["ultracodeChecking"], (keys, then, again))
tui["panel"] = panel("Ultracode  on")
check("ultracode look: a new process is looked at again", look(104)[2]["ultracode"] is True)
tui["panel"] = None
_, keys, then = look(105)
check("ultracode look: no Esc when the panel doesn't open (Esc could stop its work), and no retry",
      keys == ["/effort", "\r"] and then["ultracode"] is None and look(105)[1] is None, keys)
tui.update(panel=panel("Ultracode  on"), typing=False)
_, keys, _ = look(106)
check("ultracode look: no Enter when the box doesn't show /effort (something else took the keys)", keys == ["/effort"], keys)
tui["typing"] = True
for run, why, kw in ((107, "while it works", {"status": "busy"}), (108, "while it shows a question", {"status": "waiting"}),
                     (109, "when its details aren't open", {"details": False})):
    first, keys, _ = look(run, **kw)
    check(f"ultracode look: nothing typed, and no checking, {why}",
          keys is None and first["ultracode"] is None and not first["ultracodeChecking"], (first, keys))
check("ultracode look: once a working one is idle, the next poll looks at once", look(107)[2]["ultracode"] is True)
first, keys, _ = look(113, listed="busy")
check("ultracode look: nothing typed when Claude Code's own fresh list says it works",
      keys is None and first["ultracodeChecking"], (first, keys))


def refuse(screen):
    raise ValueError("Its terminal has unsent text in its prompt box")


S._box_check = lambda job: refuse
first, keys, _ = look(110)
retry = look(110)[1]
check("ultracode look: nothing typed when its box isn't ready, and no new try right away",
      keys is None and retry is None and S.ultra_peeks[UC][2] is False, (keys, retry))
S._box_check = lambda job: None
S.ultra_peeks[UC] = (S.ultra_peeks[UC][0], time.time() - S.PEEK_RETRY - 1, False)
check("ultracode look: a minute later it tries again", look(110)[2]["ultracode"] is True)
sessions[:] = [{**uc, "pid": 111, "startedAt": time.time() * 1000, "running": False}]
check("ultracode look: an asleep agent isn't looked at",
      S.session_chat(UC, look=True)["ultracodeChecking"] is False and S.ultra_peeks[UC][0][0] == 110)
tui["hold"] = threading.Event()  # the look's attach waits until this check lets it go on
sessions[:] = [{**uc, "pid": 112, "startedAt": time.time() * 1000, "status": "idle"}]
S.background_rows = lambda fresh=False: [{"id": uc["jobId"], "sessionId": UC, "pid": 112, "status": "idle"}]
began = time.time()
first, second = S.session_chat(UC, look=True), S.session_chat(UC, look=True)
took = time.time() - began
tui["hold"].set()
end = time.time() + 5
while S.ultra_peeks[UC][2] is None and time.time() < end:
    real_sleep(0.02)
check("ultracode look: the poll never waits for the look, and says checking until it is done",
      first["ultracodeChecking"] and second["ultracodeChecking"] and took < 1
      and S.session_chat(UC, look=True)["ultracode"] is True, (first, second, took))
tui["hold"] = None
pressed.clear()
sessions[:] = [{**uc, "pid": 114, "startedAt": time.time() * 1000, "status": "idle"}]
S.background_rows = lambda fresh=False: [{"id": uc["jobId"], "sessionId": UC, "pid": 114, "status": "idle"}]
with S.type_lock:  # the look waits for the typing lock while a prompt is typed and tells it
    first = S.session_chat(UC, look=True)
    prompt("go on", time.time() + 0.01); remind("exit", time.time() + 0.01)
end = time.time() + 5
while S.ultra_peeks[UC][2] is None and time.time() < end:
    real_sleep(0.02)
check("ultracode look: known by the time it has the typing lock, nothing is typed (no stray /effort)",
      first["ultracodeChecking"] and not pressed and S.session_chat(UC, look=True)["ultracode"] is False, pressed)

ran = []
S.run_claude = lambda args, **kw: ran.append(args) or types.SimpleNamespace(
    stdout="backgrounded · abcdef12 · x\n", stderr="", returncode=0)
S.start_background("b", {"prompt": "hi", "folder": folder, "ultracode": True})
S.start_background("b", {"prompt": "hi", "folder": folder})
starts = [a for a in ran if "--bg" in a]
check("ultracode: New agent with Ultracode ticked starts it with the ultracode setting, only then",
      starts[0][starts[0].index("--settings") + 1] == '{"ultracode": true}' and "--settings" not in starts[1], ran)

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

# ------------------------------------- New agent: images with its first prompt

starts = lambda: [a for a in woken if a[:1] == ["--bg"]]
S.start_background("b", {"prompt": "what's this", "folder": folder, "images": [{"data": b64(PNG)}]})
first = starts()[-1][-1] if starts() else ""
named = S.re.search(r"\[Image: source: (\S+)\]", first)
check("new agent: a background agent's first prompt names the image, saved in its folder's project temp folder",
      first.startswith("what's this\n\n") and named and Path(named.group(1)).read_bytes() == PNG
      and Path(named.group(1)).parent == S.CLAUDE_TMP / S.re.sub(r"[^A-Za-z0-9]", "-", folder) / S.IMAGE_DIR, first)
S.start_background("b", {"prompt": "", "folder": folder, "images": [{"data": b64(PNG)}]})
check("new agent: images alone start one", starts()[-1][-1].startswith("[Image: source: "), starts()[-1])
for body, why in (({"prompt": ""}, "nothing to start with"),
                  ({"prompt": "x", "images": [{"data": b64(b"<svg/>")}]}, "something that isn't an image")):
    count = len(starts())
    try:
        S.start_background("b", {"folder": folder, **body})
        check(f"new agent: refused: {why}", False)
    except ValueError as e:
        check(f"new agent: refused: {why}", len(starts()) == count, str(e))
sent.clear()
r = S.start_editor_chat("b", {"prompt": "explain", "editor": "VS Code", "images": [{"data": b64(PNG)}]})
check("new agent: an IDE chat's launch, which the page is sent, holds no image data",
      "images" not in S.launches[r["launchId"]])
sessions.append(fake("fresh", folder))
job = finish(r["launchId"])
note = sent[-1][0]["text"] if sent else ""
named = S.re.search(r"\[Image: source: (\S+)\]", note)
check("new agent: an IDE chat gets the image in the message with its prompt, once it has opened",
      job["state"] == "done" and "explain\n\n[Image: source: " in note and named
      and Path(named.group(1)).read_bytes() == PNG, job["detail"])
sessions.pop()
S.shutil.rmtree(S.CLAUDE_TMP.parent)

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{f'  ({detail})' if detail and not ok else ''}")
print(f"server checks: {len(results) - len(failed)} of {len(results)} passed")
sys.exit(1 if failed else 0)
