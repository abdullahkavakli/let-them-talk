#!/usr/bin/env python3
"""Checks parts of server.py without a server: where new cards go, New
agent → Chat in IDE in a folder, renaming a card, images sent with a prompt, switching
ultracode, looking it up or hearing it from the suggestions mod, compacting a background
agent, moving an editor chat to a terminal, and New workflow's teams.
Every program launch, session list and message is faked, so nothing opens and
nothing is sent. Needs only Python.

Run:  python3 tests/check_server.py      Exit 0: all passed. 1: a check failed.
"""
import http.client
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

S.ULTRA_FILE = Path(tempfile.mkdtemp()) / "ultracode.json"  # switches kept on disk: never the app's own
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
answer("Current effort level: high (Comprehensive implementation with extensive testing)", t0 + 13)
status_off = S.ultracode_state(restarted)
answer("Effort level: auto (currently high) · Ultracode on", t0 + 14)
check("ultracode: /effort status (as the mod runs it) reads off without Ultracode in it, on with it",
      status_off is False and S.ultracode_state(restarted) is True, status_off)

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
kept = json.loads(S.ULTRA_FILE.read_text()) if S.ULTRA_FILE.exists() else {}


def restart_server():  # memory gone; what the server kept on disk read again
    S.ultra_switched.clear()
    getattr(S, "load_ultracode", lambda: None)()


restart_server()
check("ultracode: Turn off while it works (in no transcript) is kept on disk and still read after a server restart",
      kept.get(UC, [None])[0] is False and S.ultracode_state(uc) is False, (kept, S.ultra_switched.get(UC)))


def press_late(job, keys, check=None):  # it works; its turn ends, and the mod's /effort status lands first
    typed.append("".join(k for k, _ in keys))
    real_sleep(0.05)
    answer("Current effort level: high (Comprehensive implementation with extensive testing) · Ultracode on",
           time.time())
    return f"✽ Working… (3s)\r\n   Ultracode on (this session only): dynamic workflows.\r\n{rules}\r\n❯ \r\n{rules}\r\n"


S._press_keys = press_late
try:
    r = S.set_ultracode("b", {"sessionId": UC, "on": True})
except ValueError as e:
    r = {"error": str(e)}
check("ultracode: Turn on while it works passes on its own answer, not another command's that lands first",
      r.get("said") == "Ultracode on (this session only): dynamic workflows." and S.ultracode_state(uc) is True, r)
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

# ------------------ Ultracode told by the suggestions mod (its reports faked)

me = os.getpid()
real_sleep(0.01)  # the transcript's last record is older than this process
here = {**uc, "pid": me, "startedAt": time.time() * 1000, "status": "busy"}
sessions[:] = [here]


def told(**body):
    """The mod's report of an answer, as POST /api/mod/ultracode takes it; the error, if refused."""
    body = {"sessionId": UC, "pid": me, "procStart": S._proc_start(me), "at": time.time() * 1000, **body}
    try:
        S.take_mod_ultracode(body)
    except (ValueError, AttributeError) as e:
        return str(e) or type(e).__name__
    return None


unknown = S.ultracode_state(here)
error = told(on=True)
check("ultracode mod: a switch it reports (one answered on its screen only, while it works) is read at once",
      unknown is None and error is None and S.ultracode_state(here) is True, (unknown, error))
refusals = [told(on=False, pid=os.getppid(), procStart=S._proc_start(os.getppid())),  # another process
            told(on=False, procStart="1"),  # its pid, but another process's start (a pid used again)
            told(on=False, sessionId="not an id"), told(on="off")]
check("ultracode mod: a report from another process, or without a session or on, is refused",
      all(refusals) and S.ultracode_state(here) is True, refusals)
told(on=False, at=(time.time() - 60) * 1000)
check("ultracode mod: a report older than the newest switch (one sent late) changes nothing",
      S.ultracode_state(here) is True)
told(on=False)
restart_server()
after_restart = S.ultracode_state(here)
prompt("next", time.time() + 0.01); remind("enter", time.time() + 0.01)
check("ultracode mod: what it told is kept across a server restart, until a later prompt's reminder tells",
      after_restart is False and S.ultracode_state(here) is True, after_restart)
fresh = {**here, "sessionId": "0c0c0c0c-0000-4000-8000-0000000000ff"}  # no transcript yet
sessions[:] = [fresh]
told(on=True, sessionId=fresh["sessionId"])
check("ultracode mod: one told before its chat has a transcript is read too", S.ultracode_state(fresh) is True)


def rec(text, at, **extra):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text},
                       "timestamp": datetime.fromtimestamp(at, timezone.utc).isoformat(), **extra})


done = json.dumps({"type": "assistant", "timestamp": datetime.fromtimestamp(t0 + 2, timezone.utc).isoformat(),
                   "message": {"id": "m1", "role": "assistant", "stop_reason": "end_turn",
                               "content": [{"type": "text", "text": "Done."}]}})
mod = {"origin": {"kind": "plugin", "name": "let-them-talk-suggestions"}}
enqueue = json.dumps({"type": "queue-operation", "operation": "enqueue", "content": "/effort status",
                      "timestamp": datetime.fromtimestamp(t0 + 1.5, timezone.utc).isoformat()})
_, _, _, _, waiting, _ = S._chat_messages([rec("fix it", t0 + 1, origin={"kind": "human"}), enqueue])
msgs, working, *_ = S._chat_messages([
    rec("fix it", t0 + 1, origin={"kind": "human"}), enqueue, done,
    rec("<local-command-caveat>The command below was run directly in Claude Code</local-command-caveat>", t0 + 3,
        isMeta=True, **mod),
    rec("<command-name>/effort</command-name>\n<command-message>effort</command-message>\n"
        "<command-args>status</command-args>", t0 + 3, **mod),
    rec("<local-command-stdout>Current effort level: high · Ultracode on</local-command-stdout>", t0 + 3, **mod)])
check("ultracode mod: its /effort status isn't shown as yours, queued while it works, nor as working once it ran",
      waiting == [] and not working and [m["text"] for m in msgs] == ["fix it", "Done."], (waiting, working, msgs))
sessions[:] = [uc]

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
ran.clear()
S.start_background("b", {"prompt": "hi", "folder": folder, "effort": "low"})
try:
    S.start_background("b", {"prompt": "hi", "folder": folder, "effort": "huge"})
    refused = ""
except ValueError as e:
    refused = str(e)
starts = [a for a in ran if "--bg" in a]
check("new agent: an effort given goes on to claude; an unknown one is refused before claude runs",
      len(starts) == 1 and starts[0][starts[0].index("--effort") + 1] == "low" and refused == "Unknown effort: huge",
      (ran, refused))

# --------------------------- Compact: /compact typed or woken, its result read

CP = "0c0c0c0c-0000-4000-8000-0000000000cc"
cp_log = root / "proj" / f"{CP}.jsonl"
cp_log.write_text("")


def cp_note(rec, at=None, path=cp_log):  # as Claude Code writes them
    rec["timestamp"] = datetime.fromtimestamp(at or time.time(), timezone.utc).isoformat().replace("+00:00", "Z")
    with path.open("a") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


cp_user = lambda text, **kw: cp_note({"type": "user", "message": {"role": "user", "content": text}, **kw})
cp_asked = lambda: cp_user("<command-name>/compact</command-name>\n            <command-message>compact</command-message>"
                           "\n            <command-args></command-args>")


def cp_done(pre=39266, post=2563):  # what a real /compact wrote, in its order
    cp_note({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
             "compactMetadata": {"trigger": "manual", "preTokens": pre, "postTokens": post}})
    cp_user("This session is being continued from a previous conversation …", isCompactSummary=True)
    cp_user("<local-command-caveat>The command below was run directly in Claude Code …</local-command-caveat>", isMeta=True)
    cp_asked()
    cp_user("<local-command-stdout>\x1b[2mCompacted (ctrl+o to see full summary)\x1b[22m</local-command-stdout>")


cp = {"took": True, "typing": True}
cp_agent = {"sessionId": CP, "name": "cp", "platform": "wsl", "background": True, "running": True, "jobId": "cdcdcdcd",
            "status": "idle", "agentState": "idle", "resumable": True, "cwd": folder}
cp_rows = [{"id": "cdcdcdcd", "sessionId": CP, "pid": 9, "status": "busy"}]


def press_cp(job, keys, check=None):
    """`claude attach`, faked: the box shows what is typed; Enter sends it, and
    Claude Code notes the typed /compact at once."""
    screen, text = box(""), ""
    if check:
        check(screen)
    pressed.append([])
    keys = list(keys)
    while keys:
        key = keys.pop(0)
        if callable(key):
            keys[:0] = key(screen)
            continue
        key = key[0]
        pressed[-1] += [key] if key else []
        if key == "\r" and cp["took"]:
            cp_user(text)
            screen, text = box(""), ""
        elif key and key != "\r" and cp["typing"]:
            text += key
            screen = box(text)
    return screen


def cp_wait(lid):
    end = time.time() + 5
    while time.time() < end and S.launches[lid]["state"] == "compacting":
        real_sleep(0.02)
    return S.launches[lid]


typing = {}


def press_twice(job, keys, check=None):  # a second click comes while /compact is typed
    typing["listed"] = any(l.get("from") == CP for l in S.launches.values())
    try:
        S.start_compact("b", {"sessionId": CP})
        typing["second"] = "went"
    except ValueError as e:
        typing["second"] = str(e)
    return press_cp(job, keys, check)


S._press_keys, S._box_check = press_twice, (lambda job: None)
S.background_rows = lambda fresh=False: cp_rows
board = {"nodes": {CP: {"alias": "Compactor"}}, "activity": []}
sessions[:] = [cp_agent]
pressed.clear()
lid = S.start_compact("b", {"sessionId": CP})["launchId"]
S._press_keys = press_cp
first = dict(S.launches[lid])
check("compact: while /compact is typed a second Compact is refused, and nothing is listed until it is sent",
      "already" in typing.get("second", "") and typing.get("listed") is False, typing)
try:
    S.start_compact("b", {"sessionId": CP})
    check("compact: a second Compact while one runs is refused", False)
except ValueError as e:
    check("compact: a second Compact while one runs is refused", "already" in str(e) and len(pressed) == 1, str(e))
check("compact: an idle running background agent gets /compact typed, Enter once its box shows it",
      pressed == [["/compact", "\r"]] and first["kind"] == "compact" and first["state"] == "compacting"
      and first["from"] == CP and first["board"] == "b", (pressed, first))
real_sleep(0.1)
cp_done()
job = cp_wait(lid)
check("compact: done once its transcript has the compact boundary; notice and Activity give its context before and after",
      job["state"] == "done" and job["detail"] == 'Compacted "Compactor": its context went from 39k to 3k tokens.'
      and board["activity"][-1] == job["detail"], (job, board["activity"][-1:]))

pressed.clear()
lid = S.start_compact("b", {"sessionId": CP})["launchId"]
real_sleep(0.1)
cp_asked()  # a conversation too short: Claude Code answers in a system record
cp_note({"type": "system", "subtype": "local_command", "commandRun": {"command": "compact", "args": ""},
         "content": "<local-command-stdout>Not enough messages to compact.</local-command-stdout>"})
job = cp_wait(lid)
check("compact: Claude Code's answer when it doesn't compact is the notice, and an earlier compaction isn't taken for this one",
      job["state"] == "failed" and job["detail"] == '"Compactor" wasn\'t compacted: Not enough messages to compact.'
      and board["activity"][-1] == job["detail"], job)

S.COMPACT_GRACE, cp_rows[0]["status"] = 0.1, "idle"
lid = S.start_compact("b", {"sessionId": CP})["launchId"]
job = cp_wait(lid)
check("compact: one that is neither busy nor done after a while (Esc in its terminal, or it ended) is reported",
      job["state"] == "failed" and "stopped before it was done" in job["detail"], job)
S.COMPACT_GRACE, cp_rows[0]["status"] = 15, "busy"

pressed.clear()
cp["typing"] = False  # something else takes the keys: the box never shows /compact
launched_before = set(S.launches)
try:
    S.start_compact("b", {"sessionId": CP})
    check("compact: no Enter when its box doesn't show /compact, and nothing is left waiting", False)
except ValueError as e:
    check("compact: no Enter when its box doesn't show /compact, and nothing is left waiting",
          pressed == [["/compact"]] and set(S.launches) == launched_before and "Enter wasn't pressed" in str(e), (pressed, str(e)))
cp["typing"] = True
for stray in set(S.launches) - launched_before:  # had it gone on, the checks below still run
    S.launches.pop(stray)

pressed.clear()
for kw, why in (({"status": "busy", "agentState": "working"}, "a busy one"),
                ({"status": "waiting", "agentState": "blocked"}, "one asking you something"),
                ({"background": False, "jobId": None, "entrypoint": "cli"}, "a chat in a terminal"),
                ({"background": False, "jobId": None, "entrypoint": "claude-vscode"}, "an editor chat"),
                ({"running": False, "status": "asleep", "resumable": False}, "one with no saved conversation")):
    sessions[:] = [{**cp_agent, **kw}]
    try:
        S.start_compact("b", {"sessionId": CP})
        check(f"compact: refused, nothing typed or started: {why}", False)
    except ValueError as e:
        check(f"compact: refused, nothing typed or started: {why}",
              not pressed and set(S.launches) == launched_before, str(e))

woke = []
S.run_claude = lambda args, **kw: woke.append(args) or types.SimpleNamespace(
    stdout="backgrounded · cdcdcdcd\n", stderr="note: woke session cdcdcdcd with its saved options (--model).", returncode=0)
sessions[:] = [{**cp_agent, "running": False, "status": "asleep", "agentState": "done"}]
lid = S.start_compact("b", {"sessionId": CP})["launchId"]
real_sleep(0.1)
cp_user("/compact")
cp_done(969833, 14454)
job = cp_wait(lid)
check("compact: an asleep one is woken with /compact as its prompt, nothing typed, and its result read the same way",
      woke == [["--resume", CP, "--bg", "--", "/compact"]] and not pressed and job["state"] == "done"
      and "from 970k to 14k tokens" in job["detail"], (woke, job))
S.run_claude = lambda args, **kw: types.SimpleNamespace(
    stdout="backgrounded · 0123abcd\n", returncode=0,
    stderr="note: session cdcdcdcd is already running in the background, so this started a copy as 0123abcd.")
launched_before = set(S.launches)
try:
    S.start_compact("b", {"sessionId": CP})
    check("compact: a copy started instead of waking it is reported, and its card added", False)
except ValueError as e:
    check("compact: a copy started instead of waking it is reported, and its card added",
          "copy (0123abcd)" in str(e) and board.get("adopt") == ["0123abcd"] and set(S.launches) == launched_before, str(e))

S.launches["look"] = {"id": "look", "board": "b", "at": time.time(), "kind": "compact", "from": UC, "state": "compacting"}
idle_uc = {**uc, "pid": 120, "startedAt": time.time() * 1000, "status": "idle"}
check("compact: the ultracode look waits while it compacts (it would type /effort meanwhile)",
      S.look_up_ultracode(idle_uc) is False and S.ultra_peeks[UC][0][0] != 120)
del S.launches["look"]

UK = "0c0c0c0c-0000-4000-8000-0000000000dd"
uk_log = root / "proj" / f"{UK}.jsonl"
t1 = time.time() - 50
cp_note({"type": "user", "message": {"role": "user", "content": "fix it"}}, t1, uk_log)
cp_note({"type": "attachment", "attachment": {"type": "ultra_effort_enter"}}, t1, uk_log)
cp_note({"type": "user", "message": {"role": "user", "content":
         "<local-command-stdout>Ultracode off. Effort stays high.</local-command-stdout>"}}, t1 + 1, uk_log)
cp_note({"type": "user", "message": {"role": "user", "content": "/compact"}}, t1 + 2, uk_log)
cp_note({"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": "This session is …"}},
        t1 + 3, uk_log)
check("ultracode: a typed /compact and its summary aren't prompts, so a switch made before them still stands",
      S.ultracode_state({"sessionId": UK, "startedAt": (t1 - 10) * 1000}) is False)

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

# ------------------------------- Open in terminal: an editor chat closes first

TC = "0d0d0d0d-0000-4000-8000-0000000000e1"
ide_names = ("load_board", "add_activity", "_proc_start", "open_terminal", "IDE_CLOSE_WAIT", "has_transcript",
             "_read_registry", "wsl_exe")
ide_saved, real_kill = {n: getattr(S, n) for n in ide_names}, S.os.kill
alive, order, notes = {5}, [], []
ide_chat = {"sessionId": TC, "name": "it", "entrypoint": "claude-vscode", "editor": "Cursor", "platform": "wsl",
            "background": False, "kind": "interactive", "cwd": home, "pid": 5}
S.load_board = lambda bid: {"nodes": {TC: {"cwd": home, "name": "it", "editor": "Cursor"}}, "activity": []}
S.add_activity = lambda board, text, level: notes.append((text, level))
S.has_transcript = lambda sid: True
S._proc_start = lambda pid: "1" if pid in alive else None


def fake_kill(pid, sig):
    order.append(f"kill {pid} {S.signal.Signals(sig).name}")
    alive.discard(pid)  # it exits, as Claude Code does on SIGINT


S.os.kill = fake_kill
S.open_terminal = lambda job, cwd=None, command=None: order.append(f"terminal {cwd} {command}") or \
    {"opened": True, "command": command}


def move(**body):
    order.clear(); notes.clear(); alive.add(5)
    try:
        return S.terminal_chat("b", {"sessionId": TC, **body})
    except ValueError as e:
        return str(e)


try:
    sessions[:] = [ide_chat]
    r = move()
    check("open in terminal: an editor chat open in the IDE isn't closed without your yes",
          isinstance(r, str) and "open in Cursor" in r and order == [], (r, order))
    r = move(end=True)
    check("open in terminal: after your yes it gets SIGINT (not SIGTERM), then the terminal resumes it",
          order == ["kill 5 SIGINT", f"terminal {home} claude --resume {TC}"] and r["closed"] and r["opened"]
          and r["editor"] == "Cursor" and "Closed @it in Cursor and opened it in a terminal" in notes[0][0], (order, r, notes))
    S.IDE_CLOSE_WAIT = 0.1
    S.os.kill = lambda pid, sig: order.append(f"kill {pid}")  # it ignores the signal
    r = move(end=True)
    check("open in terminal: one that stays open in the IDE is reported, and no terminal opens on top of it",
          isinstance(r, str) and "still open in Cursor" in r and order == ["kill 5"], (r, order))
    S.IDE_CLOSE_WAIT = ide_saved["IDE_CLOSE_WAIT"]
    S.os.kill = lambda pid, sig: (_ for _ in ()).throw(PermissionError(1, "Operation not permitted"))
    r = move(end=True)
    check("open in terminal: a chat that can't be signalled is reported, and no terminal opens",
          isinstance(r, str) and "Couldn't close it in Cursor" in r and order == [], (r, order))
    S.os.kill = fake_kill
    S.open_terminal = lambda job, cwd=None, command=None: order.append("terminal") or {"opened": False, "command": command}
    r = move(end=True)
    check("open in terminal: when no terminal opens, the command comes back and Activity says so as an error",
          r["closed"] and not r["opened"] and r["command"] == f"claude --resume {TC}"
          and notes[0][1] == "error" and f"run claude --resume {TC}" in notes[0][0], (r, notes))
    S.open_terminal = lambda job, cwd=None, command=None: order.append(f"terminal {cwd} {command}") or \
        {"opened": True, "command": command}
    sessions[:] = []  # its card has ended: not open in the IDE
    r = move()
    check("open in terminal: a chat not open in the IDE opens in the terminal with nothing closed",
          order == [f"terminal {home} claude --resume {TC}"] and not r["closed"] and r["editor"] == "Cursor"
          and notes[0] == ("Opened @it in a terminal", "info"), (order, r, notes))
    sessions[:] = [{**ide_chat, "entrypoint": "cli", "editor": None}]
    r = move(end=True)
    check("open in terminal: a chat that already runs in a terminal isn't closed or opened again",
          isinstance(r, str) and "already runs in a terminal" in r and order == [], (r, order))
    sessions[:] = [ide_chat]
    S.has_transcript = lambda sid: False
    r = move(end=True)
    check("open in terminal: one with no saved conversation is refused before the IDE one is closed",
          isinstance(r, str) and "no saved conversation" in r and order == [], (r, order))
    S.has_transcript = lambda sid: True
    sessions[:] = [{**ide_chat, "platform": "windows"}]
    r = move(end=True)
    check("open in terminal: a chat on Windows is refused", isinstance(r, str) and "Windows" in r and order == [], (r, order))
    check("open in terminal: only a real session id is taken (it goes into a shell command)",
          move(sessionId="x; rm -rf ~") == "That isn't a chat's session id." and order == [])
    # once the IDE's process is gone and the terminal's has registered, the card is a terminal chat
    reg_cli = {**reg, "sessionId": TC, "entrypoint": "cli", "pid": 6, "cwd": home}
    S._read_registry = lambda d: [dict(reg_cli)]
    S.wsl_exe = lambda pid, started: "/home/you/.local/share/claude/versions/current"
    rows[:] = []
    alive.add(6)
    now_term = next(s for s in real_live_sessions() if s["sessionId"] == TC)
    check("open in terminal: once its terminal registers, the card is a terminal chat (no editor)",
          now_term["editor"] is None and now_term["entrypoint"] == "cli" and not now_term["background"], now_term)
finally:
    for n, value in ide_saved.items():
        setattr(S, n, value)
    S.os.kill = real_kill
    sessions[:] = []

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

# --------------------------- A message for a subagent goes through its chat

sent.clear()
S.send_to_subagent("b", {"sessionId": "chat", "agentId": "a1b2c3", "label": "Fable judge", "text": "stop and report"})
note = sent[-1][0]["text"] if sent else ""
check("subagent message: its chat gets it, asked to pass it on word for word with SendMessage to the agent id",
      sent and sent[-1][0]["to"] == "chat" and 'subagent "Fable judge" (agent id a1b2c3) with SendMessage (to: "a1b2c3")'
      in note and note.endswith("stop and report"), note)
S.send_to_subagent("b", {"sessionId": "bg", "agentId": "a1b2c3", "label": "x", "text": "hello"})
check("subagent message: an idle background agent gets it as a prompt, typed in",
      prompts and "(to: \"a1b2c3\")" in prompts[-1] and prompts[-1].endswith("hello"), prompts[-1:])
for body, why in (({"agentId": "../x", "text": "hi"}, "an id that isn't one"), ({"agentId": "a1", "text": "  "}, "no text"),
                  ({"sessionId": "gone", "agentId": "a1", "text": "hi"}, "a chat that isn't running")):
    count = len(sent)
    try:
        S.send_to_subagent("b", {"sessionId": "chat", **body})
        check(f"subagent message: refused: {why}", False)
    except ValueError as e:
        check(f"subagent message: refused: {why}", len(sent) == count, str(e))
S.CLAUDE_TMP = Path(tempfile.mkdtemp()) / "claude-test"  # the images section removed the last one
S.send_to_subagent("b", {"sessionId": "chat", "agentId": "a1b2c3", "label": "x", "text": "", "images": [{"data": b64(PNG)}]})
note = sent[-1][0]["text"] if sent else ""
named = S.re.search(r"\[Image: source: (\S+)\]", note)
check("subagent message: images go too, saved where its chat (and so the subagent) reads them, their lines passed on",
      "including any image lines at its end" in note and named and Path(named.group(1)).read_bytes() == PNG, note[-160:])
S.shutil.rmtree(S.CLAUDE_TMP.parent)

# ------------------------- New workflow with agents: a master and its team (faked)

S.CLAUDE_TMP = Path(tempfile.mkdtemp()) / "claude-test"  # the master's images go here, not in the real temp folder
team_runs, team_cli = [], []


def team_claude(fails=lambda name: False, hidden=lambda name: False, rm_fails=False):
    """claude --bg: a new job, whose session shows up running unless
    hidden(name); claude stop and rm: noted (rm fails if rm_fails)."""
    def run(args, **kw):
        if args[0] in ("stop", "rm"):
            team_cli.append(args)
            no = rm_fails and args[0] == "rm"
            return types.SimpleNamespace(stdout="", stderr="no such agent" if no else "", returncode=int(no))
        team_runs.append(args)
        name = args[args.index("--name") + 1]
        if fails(name):
            return types.SimpleNamespace(stdout="", stderr="boom: it broke", returncode=1)
        job = f"{len(team_runs):08x}"
        if not hidden(name):
            sessions.append({"sessionId": f"s-{job}", "name": name, "jobId": job, "running": True,
                             "messageBlock": None, "platform": "wsl", "cwd": folder, "winCwd": None,
                             "title": None, "model": None, "editor": None, "ambiguous": False, "background": True})
        return types.SimpleNamespace(stdout=f"backgrounded · {job} · {name}\n", stderr="", returncode=0)
    return run


TEAM = [{"role": "tester", "prompt": "Test the login page"}, {"role": "writer", "prompt": "Write its help page"}]
BODY = {"prompt": "Fix the login", "folder": folder, "permissionMode": "acceptEdits", "agents": TEAM}


def settled(lid):
    end = time.time() + 10
    while time.time() < end and S.launches[lid]["state"] in S.TEAM_STARTING:
        real_sleep(0.02)
    return S.launches[lid]


def start_team(body=None, nodes=None, **fake):
    """A team started on a fresh board (with nodes, if given); returns
    (launch, the --bg runs, the board)."""
    global board
    board = {"folder": folder, "nodes": dict(nodes or {}), "connections": [], "activity": [], "hidden": []}
    team_runs.clear()
    team_cli.clear()
    S.run_claude = team_claude(**fake)
    r = S.start_team("b", body or BODY)
    return settled(r["launchId"]), list(team_runs), board


bg_name = lambda args: args[args.index("--name") + 1]
arrows = lambda b: {(b["nodes"][c["from"]]["name"], b["nodes"][c["to"]]["name"]) for c in b["connections"]}
apart = lambda spots: all(abs(p[0] - q[0]) >= S.CARD_W + 20 or abs(p[1] - q[1]) >= S.CARD_H + 15
                          for i, p in enumerate(spots) for q in spots[i + 1:])
sessions[:] = []
# none picked: one agent as the page sends it (Opus, Default), one without them
job, runs, b = start_team({**BODY, "model": "opus", "effort": "", "agents": [{**TEAM[0], "model": "opus", "effort": ""}, TEAM[1]]})
names = [bg_name(a) for a in runs]
check("team: the agents start first, then the master, each in the background with the permissions picked; "
      "none picked (Default, or nothing sent): on Opus, with Claude Code's own effort",
      names == ["Fix the login - tester", "Fix the login - writer", "Fix the login"]
      and all(a[:1] == ["--bg"] and a[a.index("--model") + 1] == "opus" and "--effort" not in a
              and a[a.index("--permission-mode") + 1] == "acceptEdits" and "--settings" not in a for a in runs), names)
waits = [a[-1] for a in runs[:2]]
check("team: each agent's first prompt names it, its role and the master, and says to wait for its task",
      all(f'"Fix the login - {r}"' in w and f"the {r} in a team" in w and '(to: "Fix the login")' in w
          and "Don't start any work yet" in w and t["prompt"] not in w for w, r, t in zip(waits, ("tester", "writer"), TEAM)),
      waits)
plan = runs[2][-1]
check("team: the master's first prompt is your prompt, then the plan: each agent's name, role, model and prompt, sent in full",
      plan.startswith("Fix the login\n\n")
      and '- "Fix the login - tester", the tester, on Opus: Test the login page' in plan
      and '- "Fix the login - writer", the writer, on Opus: Write its help page' in plan and "couldn't be started" not in plan
      and "its prompt above, in full" in plan and "[Image:" not in plan, plan)
check("team: an arrow each way between the master and each agent, none between agents, no notes sent",
      arrows(b) == {("Fix the login", "Fix the login - tester"), ("Fix the login - tester", "Fix the login"),
                    ("Fix the login", "Fix the login - writer"), ("Fix the login - writer", "Fix the login")}
      and all(c["team"] == "Fix the login" and c["status"] == "sent"
              and not any(n["enabled"] for n in c["notes"].values()) for c in b["connections"]), b["connections"])
spots = {n["name"]: (n["x"], n["y"]) for n in b["nodes"].values()}
mx, my = spots["Fix the login"]
check("team: the agents' cards in a column right of the master's, which sits level with its middle",
      spots["Fix the login - tester"] == (mx + 360, my - 75) and spots["Fix the login - writer"] == (mx + 360, my + 75), spots)
check("team: done, and Activity says so", job["state"] == "done" and "the master and its 2 agents" in job["detail"]
      and "linked both ways" in job["detail"] and b["activity"][-1] == job["detail"], job["detail"])
check("team: no stray claude stop or rm when all went well", not team_cli, team_cli)

sessions[:] = []
job, runs, b = start_team({**BODY, "agents": TEAM[:1]})
check("team: one agent reads as one, not \"1 agents\"", job["state"] == "done"
      and "the master and its agent (tester)" in job["detail"] and "1 agents" not in job["detail"], job["detail"])

sessions[:] = []
job, runs, b = start_team({**BODY, "model": " Fable", "effort": "MAX",
                           "agents": [{**TEAM[0], "model": "sonnet", "effort": "low"}, {**TEAM[1], "model": "haiku"},
                                      {"role": "reviewer", "prompt": "Review it", "effort": "xhigh"}]})
picked = [(bg_name(a), a[a.index("--model") + 1], "--effort" in a and a[a.index("--effort") + 1]) for a in runs]
check("team: each agent and the master run on the model and effort picked for it, in any case "
      "(none picked: Opus, Claude Code's own effort)",
      picked == [("Fix the login - tester", "sonnet", "low"), ("Fix the login - writer", "haiku", False),
                 ("Fix the login - reviewer", "opus", "xhigh"), ("Fix the login", "fable", "max")]
      and job["state"] == "done", picked)
check("team: the plan names each agent's model, and its effort if picked, in the dialog's words",
      '- "Fix the login - tester", the tester, on Sonnet at low effort: Test the login page' in runs[-1][-1]
      and '- "Fix the login - writer", the writer, on Haiku: Write its help page' in runs[-1][-1]
      and '- "Fix the login - reviewer", the reviewer, on Opus at extra high effort: Review it' in runs[-1][-1], runs[-1][-1])

sessions[:] = []
job, runs, b = start_team({**BODY, "images": [{"data": b64(PNG)}], "ultracode": True})
plan = runs[-1][-1]
named = S.re.search(r"\[Image: source: (\S+)\]", plan)
check("team: images go to the master only, right after your prompt, saved where it reads them",
      plan.startswith("Fix the login\n\n[Image: source: ") and named and Path(named.group(1)).read_bytes() == PNG
      and "The images are yours" in plan and not any("[Image:" in a[-1] for a in runs[:-1]), plan)
check("team: Ultracode goes to the master and to every agent",
      len(runs) == 3 and all(a[a.index("--settings") + 1] == '{"ultracode": true}' for a in runs if "--settings" in a)
      and all("--settings" in a for a in runs), runs)

long_task = "x" * 17_500
for body, why, says in (
        ({"agents": TEAM}, "no prompt for the master", "master"),
        ({"prompt": "x", "agents": []}, "no agents", "1 to 8"),
        ({"prompt": "x", "agents": TEAM * 5}, "more than 8 agents", "1 to 8"),
        ({"prompt": "x", "agents": [TEAM[0], {"role": " ", "prompt": "y"}]}, "an agent without a role", "Agent 2 needs a role"),
        ({"prompt": "x", "agents": [{"role": "tester", "prompt": ""}]}, "an agent without a prompt", "Agent 1 (tester) needs a prompt"),
        ({"prompt": "x", "agents": [TEAM[0], {"role": "Tester", "prompt": "y"}]}, "two agents with one role", "both"),
        ({"prompt": "x", "agents": [{"role": "r" * 25, "prompt": "y"}]}, "a role too long for a name", "too long"),
        ({"prompt": "x", "agents": [{"role": 'QA "lead" [1a2b]', "prompt": "y"}]}, "a role with quotes or brackets",
         "only letters, digits"),
        ({"prompt": "x", "name": "x" * 31, "agents": TEAM}, "a master's name over 30 characters", "30 characters"),
        ({"prompt": "x", "name": "Crew [a1]", "agents": TEAM}, "a master's name with brackets", "only letters, digits"),
        ({"prompt": "x", "agents": TEAM, "permissionMode": "yolo"}, "an unknown permission mode", "Unknown"),
        ({"prompt": "x", "agents": [TEAM[0], {**TEAM[1], "model": "gpt"}]}, "an agent's unknown model",
         "Agent 2's model can be only Fable, Opus, Sonnet or Haiku."),
        ({"prompt": "x", "agents": [{**TEAM[0], "effort": "huge"}]}, "an agent's unknown effort",
         "Agent 1's effort can be only low, medium, high, extra high or max."),
        ({"prompt": "x", "agents": TEAM, "model": "claude-opus-5-5 --x"}, "the master's unknown model",
         "The master's model can be only"),
        ({"prompt": "x", "agents": TEAM, "effort": ["max"]}, "the master's effort that isn't one", "The master's effort can be only"),
        ({"prompt": "x", "agents": TEAM, "images": [{"data": b64(b"<svg/>")}]}, "something that isn't an image", "Only PNG"),
        ({"prompt": "x", "agents": [{"role": f"r{i}", "prompt": long_task} for i in range(8)]},
         "prompts too long together for one command line", "too long together")):
    team_runs.clear()
    try:
        S.start_team("b", {"folder": folder, **body})
        check(f"team: refused before anything starts: {why}", False)
    except ValueError as e:
        check(f"team: refused before anything starts: {why}", says in str(e) and not team_runs, str(e))

check("team: unnamed, the master takes the prompt's first words, whole ones that fit in 30 characters",
      S._team_plan({**BODY, "prompt": "Say hello as a team"})["base"] == "Say hello as a team"
      and S._team_plan({**BODY, "prompt": "Fix the login, with tests and docs for every page"})["base"]
      == "Fix the login with tests and", S._team_plan({**BODY, "prompt": "Say hello as a team"})["base"])

sessions[:] = [{"sessionId": "x", "name": "fix the LOGIN", "platform": "wsl", "running": True, "cwd": elsewhere}]
job, runs, b = start_team()
check("team: names no running chat has (in any case): the master's gets a number, its agents follow",
      [bg_name(a) for a in runs] == ["Fix the login 2 - tester", "Fix the login 2 - writer", "Fix the login 2"], runs)
sessions[:] = []
job, runs, b = start_team({**BODY, "name": "Login crew"})
check("team: the name you give is the master's", bg_name(runs[-1]) == "Login crew" and job["state"] == "done")
job, runs, b = start_team({**BODY, "name": 5})
check("team: a name that isn't text doesn't break it", bg_name(runs[-1]) == "5" and job["state"] == "done", job["detail"])

sessions[:] = [{"sessionId": "x", "name": "x" * 30, "platform": "wsl", "running": True, "cwd": elsewhere}]
job, runs, b = start_team({**BODY, "name": "x" * 30, "agents": [{"role": "r" * 24, "prompt": "y"}]})
agent_name = bg_name(runs[0])
check("team: the longest names fit in 60 and are the same in the prompts as in --name",
      agent_name == "x" * 30 + " 2 - " + "r" * 24 and len(agent_name) <= 60 and f'"{agent_name}"' in runs[0][-1]
      and f'"{agent_name}"' in runs[-1][-1] and f'"{bg_name(runs[-1])}"' in runs[-1][-1], runs)

# Two teams started together: the second can't take the names (or the places)
# of the first, whose master shows up only once its agents run.
sessions[:] = []
board = {"folder": folder, "nodes": {}, "connections": [], "activity": [], "hidden": []}
team_runs.clear()
S.TEAM_WAIT, team_wait = 0.5, S.TEAM_WAIT
S.run_claude = team_claude(hidden=lambda name: True)
first = S.start_team("b", {**BODY, "prompt": "Fix the login page"})
second = S.start_team("b", {**BODY, "prompt": "fix the login page"})
held = [S.launches[r["launchId"]]["spots"] for r in (first, second)]
for r in (first, second):
    settled(r["launchId"])
check("team: two teams started together get names of their own, and places of their own",
      first["name"] == "Fix the login page" and second["name"] == "fix the login page 2"
      and second["agents"] == ["fix the login page 2 - tester", "fix the login page 2 - writer"]
      and apart(held[0] + held[1]), (first, second, held))

sessions[:] = []
job, runs, b = start_team(fails=lambda name: name.endswith("writer"))
plan = runs[-1][-1]
check("team: an agent that doesn't start is named with why, and the master does its part",
      job["state"] == "failed" and '"Fix the login - writer" didn\'t start: boom: it broke.' in job["detail"]
      and "running with 1 of 2 agents" in job["detail"] and "The master does its part itself." in job["detail"]
      and "couldn't be started, so do their part yourself:\n- the writer: Write its help page" in plan
      and '"Fix the login - writer"' not in plan, job["detail"])
check("team: arrows only for the agents that run", arrows(b) == {("Fix the login", "Fix the login - tester"),
                                                                ("Fix the login - tester", "Fix the login")}, arrows(b))

sessions[:] = []
job, runs, b = start_team(hidden=lambda name: name.endswith("tester"))
late = f"{1:08x}"  # the tester's job: the first run
check("team: an agent that never shows up running is stopped and removed (only it), loses its place, and gets no arrows",
      job["state"] == "failed" and '"Fix the login - tester" didn\'t come up within 0.5 seconds, so it was removed.'
      in job["detail"] and team_cli == [["stop", late], ["rm", late]]
      and late not in b.get("adopt", []) and late not in b.get("spots", {})
      and arrows(b) == {("Fix the login", "Fix the login - writer"), ("Fix the login - writer", "Fix the login")},
      (job["detail"], team_cli, b.get("adopt"), b.get("spots")))
sessions[:] = []
job, runs, b = start_team(hidden=lambda name: name.endswith("tester"), rm_fails=True)
check("team: one that can't be removed is named as started, with what to do if it shows up",
      "\"Fix the login - tester\" didn't come up within 0.5 seconds and couldn't be removed: no such agent."
      in job["detail"] and "Delete its card if it shows up." in job["detail"], job["detail"])
sessions[:] = []
job, runs, b = start_team(fails=lambda name: " - " in name)
check("team: with no agent running, the master isn't started", job["state"] == "failed"
      and [bg_name(a) for a in runs] == ["Fix the login - tester", "Fix the login - writer"]
      and "the master wasn't started" in job["detail"]
      and '"Fix the login - tester" and "Fix the login - writer" didn\'t start: boom: it broke.' in job["detail"]
      and not b["connections"], job["detail"])
sessions[:] = []
job, runs, b = start_team(hidden=lambda name: " - " in name)
check("team: with no agent up in time, all are removed and the master isn't started", job["state"] == "failed"
      and len(runs) == 2 and [a[0] for a in team_cli] == ["stop", "rm", "stop", "rm"]
      and "they were removed" in job["detail"] and not b["connections"], job["detail"])
sessions[:] = []
job, runs, b = start_team(fails=lambda name: name == "Fix the login")
check("team: a master that doesn't start is reported; its agents wait, with no arrows",
      job["state"] == "failed" and "didn't start: boom: it broke." in job["detail"]
      and "Its 2 agents are running and wait for it" in job["detail"] and not b["connections"], job["detail"])
sessions[:] = []
job, runs, b = start_team(hidden=lambda name: " - " not in name)
check("team: a master that never shows up running is reported, with no arrows", job["state"] == "failed"
      and "didn't show up running" in job["detail"] and not b["connections"] and not team_cli, job["detail"])
S.TEAM_WAIT = team_wait

sessions[:] = []
other = {"name": "other", "platform": "wsl", "cwd": elsewhere, "lastSeen": time.time()}  # ended, but kept a while
spot = S.free_slot({"nodes": {"o": {"x": 40, "y": 40}}})
job, runs, b = start_team(nodes={"o": {"x": 40, "y": 40, **other}, "p": {"x": spot[0], "y": spot[1], **other}})
check("team: on a board with cards where its first place would be, its cards go where none overlaps",
      job["state"] == "done" and len(b["nodes"]) == 5 and apart([(n["x"], n["y"]) for n in b["nodes"].values()]),
      {k: (n["x"], n["y"]) for k, n in b["nodes"].items()})

sessions[:] = []
real_connect = S.connect


def one_way_only(bid, body):  # the writer's arrow back to the master can't be made
    if next(s["name"] for s in sessions if s["sessionId"] == body["from"]).endswith("writer"):
        raise ValueError("two running sessions are named that")
    return real_connect(bid, body)


S.connect = one_way_only
job, runs, b = start_team()
S.connect = real_connect
check("team: an agent whose arrow back can't be made keeps no half pair, and the notice and Activity say why",
      job["state"] == "failed" and arrows(b) == {("Fix the login", "Fix the login - tester"),
                                                 ("Fix the login - tester", "Fix the login")}
      and "\"Fix the login - writer\" isn't linked with the master: two running sessions" in job["detail"]
      and any(a.startswith('Removed the arrow "Fix the login" → "Fix the login - writer" again') for a in b["activity"]),
      (arrows(b), job["detail"], b["activity"]))

# The page posts a team, with images, to the server; a body that size gets through.
taken_bodies = []
S.start_team, real_start_team = (lambda bid, body: taken_bodies.append(body) or {"launchId": "t"}), S.start_team
server = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
S.PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()


def post(action, body, send=True):
    """The answer's status; send=False sends the headers only (one refused for
    its size is answered at once, before its body would be read)."""
    conn = http.client.HTTPConnection("127.0.0.1", S.PORT, timeout=10)
    data = json.dumps(body).encode()
    conn.putrequest("POST", f"/api/board/b/{action}")
    for k, v in (("Content-Type", "application/json"), (S.CSRF_HEADER, "1"), ("Content-Length", str(len(data)))):
        conn.putheader(k, v)
    conn.endheaders(data if send else None)
    return conn.getresponse().status


big = {**BODY, "images": [{"data": "A" * (2 << 20)}]}
check("team: the server takes a team from the page at /launch-team, images and all",
      post("launch-team", big) == 200 and taken_bodies and taken_bodies[-1]["agents"] == TEAM
      and post("no-such-thing", big, send=False) == 413, taken_bodies[-1:] and taken_bodies[-1]["prompt"])


def post_mod(body, header=True):  # the suggestions mod's report, as it sends it
    conn = http.client.HTTPConnection("127.0.0.1", S.PORT, timeout=10)
    conn.request("POST", "/api/mod/ultracode", json.dumps(body),
                 {"Content-Type": "application/json", **({S.CSRF_HEADER: "1"} if header else {})})
    return conn.getresponse().status


sessions[:] = [{**uc, "startedAt": time.time() * 1000}]
real_sleep(0.01)
statuses = (post_mod({"sessionId": UC, "on": False}, header=False), post_mod({"sessionId": UC, "on": False}))
check("ultracode mod: the server takes its report at /api/mod/ultracode, with the app's own header only",
      statuses == (403, 200) and S.ultracode_state(sessions[0]) is False, (statuses, S.ultra_switched.get(UC)))
server.shutdown()
S.start_team = real_start_team
S.shutil.rmtree(S.CLAUDE_TMP.parent)

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{f'  ({detail})' if detail and not ok else ''}")
print(f"server checks: {len(results) - len(failed)} of {len(results)} passed")
sys.exit(1 if failed else 0)
