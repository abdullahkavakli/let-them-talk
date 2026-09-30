#!/usr/bin/env python3
"""Agent Organizer: a local board for connecting Claude Code sessions.

The server reads the session registry in ~/.claude/sessions/ to find live
sessions, keeps boards (nodes, arrows, reasons) as JSON files in boards/, and
delivers "the organizer connected you" notes through a short headless Claude
session, the relay, which calls SendMessage. Standard library only.

Run:  python3 server.py      then open http://localhost:8765
"""
import base64
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
BOARDS_DIR = APP_DIR / "boards"
LOG_FILE = APP_DIR / "logs" / "relay.jsonl"
REGISTRY_DIR = Path.home() / ".claude" / "sessions"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def win_to_wsl(path):
    """C:\\Users\\x -> /mnt/c/Users/x; other paths are returned unchanged."""
    m = re.fullmatch(r"([A-Za-z]):[\\/]*(.*)", path or "")
    if not m:
        return path
    rest = m.group(2).replace("\\", "/").rstrip("/")
    return f"/mnt/{m.group(1).lower()}" + (f"/{rest}" if rest else "")


def _windows_home():
    """The Windows user folder as a WSL path, when this runs inside WSL."""
    if os.environ.get("ORGANIZER_WINDOWS_HOME"):
        return Path(os.environ["ORGANIZER_WINDOWS_HOME"])
    cmd = shutil.which("cmd.exe") or "/mnt/c/Windows/System32/cmd.exe"
    if not os.path.exists(cmd):
        return None
    try:
        out = subprocess.run([cmd, "/c", "echo %USERPROFILE%"], capture_output=True,
                             text=True, timeout=15, cwd="/mnt/c").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    home = Path(win_to_wsl(out))
    return home if out and (home / ".claude").is_dir() else None


# Claude Code on native Windows keeps its own registry and transcripts.
WIN_HOME = _windows_home()
WIN_REGISTRY_DIR = WIN_HOME / ".claude" / "sessions" if WIN_HOME else None
PROJECT_ROOTS = [PROJECTS_DIR] + ([WIN_HOME / ".claude" / "projects"] if WIN_HOME else [])
TASKLIST = shutil.which("tasklist.exe") or "/mnt/c/Windows/System32/tasklist.exe"
WIN_PID_TTL = 3
WIN_MESSAGING_MIN = (2, 1, 234)
win_pid_cache = {"at": 0.0, "pids": set()}

HOST = "127.0.0.1"
PORT = int(os.environ.get("ORGANIZER_PORT", "8765"))
RELAY_MODEL = os.environ.get("ORGANIZER_MODEL", "haiku")
CLAUDE_BIN = (os.environ.get("ORGANIZER_CLAUDE") or shutil.which("claude")
              or str(Path.home() / ".local" / "bin" / "claude"))
RELAY_NAME = "organizer"
RELAY_TIMEOUT = 180
PRUNE_AFTER = 120  # seconds an ended, unconnected session stays on a board
ACTIVITY_KEEP = 60

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
}

lock = threading.RLock()
relay_pids = set()
title_lock = threading.Lock()
title_cache = {}  # sessionId -> transcript path, read offset, latest titles
TITLE_READ_BLOCK = 4 << 20
TITLE_RETRY = 10  # seconds before looking again for a transcript not found yet


# ---------------------------------------------------------------- sessions

def session_title(sid):
    """The title Claude Code shows for a session: a custom title (set by a
    rename or a fork) if there is one, else the latest AI-generated title.
    Both are records in the transcript ~/.claude/projects/<dir>/<sid>.jsonl;
    only bytes appended since the last call are read."""
    with title_lock:
        c = title_cache.setdefault(sid, {"path": None, "offset": 0, "custom": None,
                                         "ai": None, "looked": 0.0})
        if c["path"] is None:
            if time.time() - c["looked"] < TITLE_RETRY:
                return c["custom"] or c["ai"]
            c["looked"] = time.time()
            hits = [p for root in PROJECT_ROOTS for p in root.glob(f"*/{sid}.jsonl")]
            if not hits:
                return c["custom"] or c["ai"]
            c["path"] = max(hits, key=lambda p: p.stat().st_mtime)
        try:
            size = c["path"].stat().st_size
            if size < c["offset"]:  # transcript replaced: read it again
                c.update(offset=0, custom=None, ai=None)
            with c["path"].open("rb") as f:
                f.seek(c["offset"])
                while c["offset"] < size:
                    block = f.read(min(TITLE_READ_BLOCK, size - c["offset"]))
                    if not block:
                        break
                    end = block.rfind(b"\n") + 1
                    if end == 0:
                        if len(block) < TITLE_READ_BLOCK:
                            break  # a line still being written; finish it next time
                        c["offset"] += len(block)  # one huge line with no title in it
                        continue
                    for line in block[:end].splitlines():
                        if b'-title"' not in line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if rec.get("type") == "custom-title" and rec.get("customTitle"):
                            c["custom"] = str(rec["customTitle"])
                        elif rec.get("type") == "ai-title" and rec.get("aiTitle"):
                            c["ai"] = str(rec["aiTitle"])
                    c["offset"] += end
                    f.seek(c["offset"])
        except OSError:
            c["path"] = None
        return c["custom"] or c["ai"]


model_cache = {}  # transcript path -> ((mtime_ns, size), model)
MODEL_TAIL = 512 << 10


def session_model(sid):
    """The model of the chat's latest reply (e.g. claude-opus-5-5), read from
    the end of its transcript and cached until the file changes."""
    path = title_cache.get(sid, {}).get("path")  # found by session_title()
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = model_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    model = hit[1] if hit else None  # keep the last known one if the tail has none
    try:
        with path.open("rb") as f:
            f.seek(max(0, st.st_size - MODEL_TAIL))
            tail = f.read().splitlines()
    except OSError:
        tail = []
    for raw in reversed(tail):
        if b'"model"' not in raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        found = (rec.get("message") or {}).get("model") if rec.get("type") == "assistant" else None
        if found and not found.startswith("<"):  # skip "<synthetic>" error replies
            model = found
            break
    model_cache[path] = (key, model)
    return model


def label(s):
    """How the board names a session in text: its title, else its address."""
    return f"\"{s['title']}\"" if s.get("title") else f"@{s['name']}"


# ------------------------------------------------------ agents in a session
#
# Claude Code keeps a session's helpers next to its transcript:
#   <dir>/<sid>/subagents/agent-<id>.jsonl + .meta.json    Agent-tool subagents
#   <dir>/<sid>/workflows/<runId>.json                     Workflow runs, with
#       a per-agent "workflowProgress" list (label, phase, state, tokens, ...)

SID_RE = re.compile(r"[0-9a-fA-F-]{8,64}")
AGENT_TAIL = 256 << 10   # bytes read from the end of a subagent transcript
AGENT_STALE = 20 * 60    # an unfinished subagent silent this long counts as stopped
AGENT_STATES = {"progress": "running", "running": "running", "done": "done",
                "completed": "done", "queued": "queued", "error": "failed",
                "failed": "failed", "skipped": "skipped"}


def session_dir(sid):
    hits = [p for root in PROJECT_ROOTS for p in root.glob(f"*/{sid}") if p.is_dir()]
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def _ms(ts):
    """ISO timestamp from a transcript record -> epoch milliseconds."""
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except (AttributeError, ValueError):
        return None


def _tool_summary(block):
    inp = block.get("input") or {}
    text = (inp.get("description") or inp.get("command") or inp.get("file_path")
            or inp.get("pattern") or inp.get("query") or "")
    text = " ".join(str(text).split())
    return f"{block.get('name')}: {text[:90]}" if text else str(block.get("name"))


info_cache = {}  # transcript path -> ((mtime_ns, size), info)


def subagent_info(path):
    """Model, tokens, timing and finished-or-not from the ends of a transcript,
    re-read only when the file has changed."""
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    hit = info_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    info = _read_subagent(path)
    info["mtime"] = st.st_mtime
    info_cache[path] = (key, info)
    return info


def _read_subagent(path):
    with path.open("rb") as f:
        first = f.readline()
        size = f.seek(0, 2)
        f.seek(max(0, size - AGENT_TAIL))
        tail = f.read().splitlines()
    info = {"startedAt": None, "lastAt": None, "model": None, "tokens": None,
            "finished": False, "lastTool": None}
    try:
        info["startedAt"] = _ms(json.loads(first).get("timestamp"))
    except ValueError:
        pass
    resumed = False
    for raw in reversed(tail):
        try:
            rec = json.loads(raw)
        except ValueError:
            continue  # the partial first line of the tail, or a line being written
        if info["lastAt"] is None:
            info["lastAt"] = _ms(rec.get("timestamp"))
        if rec.get("type") == "user":
            resumed = True  # input after the last reply: a tool result or a new prompt
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        usage = msg.get("usage") or {}
        info["model"] = msg.get("model")
        info["tokens"] = sum(usage.get(k) or 0 for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
            "output_tokens")) or None
        info["finished"] = msg.get("stop_reason") == "end_turn" and not resumed
        tools = [c for c in msg.get("content") or [] if c.get("type") == "tool_use"]
        if tools:
            info["lastTool"] = _tool_summary(tools[-1])
        break
    return info


def direct_agents(sdir, live):
    agents = []
    now = int(time.time() * 1000)
    for meta_path in (sdir / "subagents").glob("agent-*.meta.json"):
        aid = meta_path.name[len("agent-"):-len(".meta.json")]
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        try:
            info = subagent_info(meta_path.with_name(f"agent-{aid}.jsonl"))
        except OSError:
            continue
        if info["finished"]:
            state = "done"
        elif live and time.time() - info["mtime"] < AGENT_STALE:
            state = "running"
        else:
            state = "stopped"
        end = now if state == "running" else info["lastAt"]
        agents.append({
            "id": aid,
            "description": meta.get("description") or aid,
            "agentType": meta.get("agentType"),
            "background": meta.get("requestShape") == "background",
            "depth": meta.get("spawnDepth", 1),
            "model": info["model"], "tokens": info["tokens"], "state": state,
            "startedAt": info["startedAt"],
            "durationMs": end - info["startedAt"] if end and info["startedAt"] else None,
            "lastTool": info["lastTool"] if state == "running" else None,
        })
    agents.sort(key=lambda a: (a["state"] != "running", -(a["startedAt"] or 0)))
    return agents


RESTART_GAP = 5 * 60  # an unfinished attempt silent this long, with a newer
                      # attempt of the same label, was replaced by a retry/resume


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_journal(path):
    events = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            pass  # the line being written
    return events


def workflow_run(sdir, run_id, live, now):
    """One Workflow run. Its summary file (workflows/<runId>.json) is written
    when the run ends, so a live run is read from its journal (one line per
    agent start and result) and each agent's own transcript."""
    summary_path = sdir / "workflows" / f"{run_id}.json"
    run_dir = sdir / "subagents" / "workflows" / run_id
    d = _read_json(summary_path) or {}
    written = summary_path.stat().st_mtime if d else None
    progress = {e.get("agentId"): e for e in d.get("workflowProgress") or []
                if e.get("type") == "workflow_agent" and e.get("agentId")}
    journal = _read_journal(run_dir / "journal.jsonl")
    ended = {ev["agentId"]: ("done" if ev.get("type") == "result" else "failed")
             for ev in journal if ev.get("agentId") and ev.get("type") != "started"}
    starts = [ev for ev in journal if ev.get("type") == "started" and ev.get("agentId")]
    if not starts:  # no journal: take the agent list from the summary
        starts = [{"agentId": aid, "label": e.get("label"), "phase": e.get("phaseTitle")}
                  for aid, e in progress.items()]
    agents, replaced = [], 0
    for i, ev in enumerate(starts):
        aid, e = ev["agentId"], progress.get(ev["agentId"], {})
        info = None
        if aid not in ended or not e:  # finished agents in the summary need no read
            try:
                info = subagent_info(run_dir / f"agent-{aid}.jsonl")
            except OSError:
                pass
        silent = time.time() - info["mtime"] if info else None
        newer = any(o.get("label") == ev.get("label") for o in starts[i + 1:])
        if aid in ended:
            state = ended[aid]
        elif newer and (silent is None or silent > RESTART_GAP):
            replaced += 1  # a retry or resume started this label again
            continue
        elif e and written and d.get("status") != "running" and (info is None or info["mtime"] <= written + 15):
            # the summary was written after this agent's last activity
            state = AGENT_STATES.get(e.get("state"), e.get("state") or "unknown")
            state = {"running": "stopped", "queued": "not run"}.get(state, state)
        elif live and silent is not None and silent < AGENT_STALE:
            state = "running"
        else:
            state = "stopped"
        started_at = e.get("startedAt") or (info or {}).get("startedAt")
        if e.get("durationMs") is not None and state != "running":
            dur = e["durationMs"]
        elif started_at:
            end_at = now if state == "running" else (
                (info or {}).get("lastAt") or e.get("lastProgressAt") or now)
            dur = end_at - started_at
        else:
            dur = None
        last_tool = None
        if state == "running":
            last_tool = (info or {}).get("lastTool")
        agents.append({
            "id": aid, "label": ev.get("label") or aid, "phase": ev.get("phase"),
            "model": e.get("model") or (info or {}).get("model"), "state": state,
            "tokens": (info or {}).get("tokens") if state == "running" or not e.get("tokens")
            else e.get("tokens"),
            "toolCalls": e.get("toolCalls") if state != "running" else None,
            "startedAt": started_at, "durationMs": dur, "lastTool": last_tool,
        })
    active = any(a["state"] == "running" for a in agents)
    journal_path = run_dir / "journal.jsonl"
    if not active and live and journal_path.exists():
        jm = journal_path.stat().st_mtime
        active = (written is None or jm > written + 5) and time.time() - jm < 120
    if active:
        status = "running"
    elif d.get("status") and d["status"] != "running":
        status = d["status"]
    else:
        status = "stopped" if agents else "unknown"
    name = d.get("workflowName")
    if not name:
        for script in (sdir / "workflows" / "scripts").glob(f"*-{run_id}.js"):
            name = script.stem[: -len(run_id) - 1]
    starts_at = [a["startedAt"] for a in agents if a["startedAt"]]
    start = d.get("startTime") or (min(starts_at) if starts_at else None)
    if active or d.get("durationMs") is None:
        duration = (now - start) if active and start else d.get("durationMs")
    else:
        duration = d["durationMs"]
    tokens = [a["tokens"] for a in agents if a["tokens"]]
    return {
        "runId": run_id, "name": name or run_id, "summary": d.get("summary"),
        "status": status, "startTime": start, "durationMs": duration,
        "agentCount": len(agents), "restarted": replaced,
        "totalTokens": (sum(tokens) or None) if active or not d.get("totalTokens")
        else d["totalTokens"],
        "phases": [p.get("title") for p in d.get("phases") or []],
        "agents": agents,
    }


def workflow_runs(sdir, live):
    now = int(time.time() * 1000)
    ids = {p.stem for p in (sdir / "workflows").glob("wf_*.json")}
    ids |= {p.name for p in (sdir / "subagents" / "workflows").glob("wf_*") if p.is_dir()}
    runs = [workflow_run(sdir, run_id, live, now) for run_id in ids
            if re.fullmatch(r"wf_[\w-]+", run_id)]
    runs.sort(key=lambda r: -(r["startTime"] or 0))
    return runs


def session_agents(sid):
    """The subagents and workflow runs a session has started."""
    if not SID_RE.fullmatch(sid or ""):
        raise ValueError("bad session id")
    live = any(s["sessionId"] == sid for s in live_sessions())
    sdir = session_dir(sid)
    if sdir is None:
        return {"sessionId": sid, "live": live, "direct": [], "workflows": []}
    return {"sessionId": sid, "live": live,
            "direct": direct_agents(sdir, live), "workflows": workflow_runs(sdir, live)}


def _proc_start(pid):
    """Start time of a process (field 22 of /proc/<pid>/stat), or None."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat.rsplit(")", 1)[1].split()[19]


def windows_claude_pids():
    """PIDs of running Windows claude.exe processes (terminal and editor
    extensions alike), cached for a few seconds."""
    now = time.time()
    if now - win_pid_cache["at"] < WIN_PID_TTL:
        return win_pid_cache["pids"]
    pids = set()
    try:
        out = subprocess.run(
            [TASKLIST, "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq claude.exe"],
            capture_output=True, text=True, timeout=10, cwd="/mnt/c").stdout
        for row in csv.reader(out.splitlines()):
            if len(row) > 1 and row[1].isdigit():
                pids.add(int(row[1]))
    except (OSError, subprocess.SubprocessError):
        pass
    win_pid_cache.update(at=now, pids=pids)
    return pids


def _version(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def _read_registry(directory):
    for f in directory.glob("*.json"):
        try:
            reg = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(reg.get("pid"), int) and reg.get("sessionId"):
            yield reg


# The VS Code extension reports entrypoint "claude-vscode" in every VS Code
# fork; the editor shows in the path of the claude binary it launched.
EDITOR_PATHS = [("/.cursor-server/", "Cursor"), ("\\.cursor\\", "Cursor"),
                ("/.vscode-server-insiders/", "VS Code Insiders"),
                ("\\.vscode-insiders\\", "VS Code Insiders"),
                ("/.vscode-server/", "VS Code"), ("\\.vscode\\", "VS Code"),
                ("/.windsurf-server/", "Windsurf"), ("\\.windsurf\\", "Windsurf"),
                ("/.vscodium-server/", "VSCodium"), ("\\.vscode-oss\\", "VSCodium")]
POWERSHELL = (shutil.which("powershell.exe")
              or "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
exe_cache = {}      # (pid, procStart) -> binary path of a WSL session
win_exe_cache = {}  # pid -> binary path of a Windows claude.exe


def editor_from_path(path):
    low = (path or "").lower()
    return next((name for needle, name in EDITOR_PATHS if needle in low), None)


def wsl_exe(pid, proc_start):
    key = (pid, proc_start)
    if key not in exe_cache:
        try:
            exe_cache[key] = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            exe_cache[key] = ""
    return exe_cache[key]


def windows_exe(pid):
    """Binary path of a Windows claude.exe; one PowerShell query per new PID."""
    if pid not in win_exe_cache:
        script = ("Get-CimInstance Win32_Process -Filter \"Name = 'claude.exe'\" | "
                  "ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)\" }")
        enc = base64.b64encode(script.encode("utf-16-le")).decode()
        try:
            out = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                                 capture_output=True, text=True, timeout=30, cwd="/mnt/c").stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.splitlines():
            found, _, path = line.strip().partition("|")
            if found.isdigit():
                win_exe_cache[int(found)] = path
        win_exe_cache.setdefault(pid, "")
    return win_exe_cache[pid]


def _session(reg, platform, cwd, block, exe=""):
    return {
        "editor": editor_from_path(exe) if reg.get("entrypoint") == "claude-vscode" else None,
        "sessionId": reg["sessionId"],
        "name": reg.get("name") or "",
        "title": session_title(reg["sessionId"]),
        "model": session_model(reg["sessionId"]),
        "cwd": cwd,
        "winCwd": reg.get("cwd", "") if platform == "windows" else None,
        "platform": platform,
        "messageBlock": block,
        "status": reg.get("status", "unknown"),
        "kind": reg.get("kind", ""),
        "entrypoint": reg.get("entrypoint", ""),
        "version": reg.get("version", ""),
        "pid": reg["pid"],
        "startedAt": reg.get("startedAt"),
    }


def live_sessions():
    """Running sessions: WSL ones whose process is still the one that wrote
    the registry file, and Windows ones whose claude.exe PID is running."""
    sessions = []
    for reg in _read_registry(REGISTRY_DIR):
        pid = reg["pid"]
        if pid in relay_pids:
            continue
        started = _proc_start(pid)
        if started is None or (reg.get("procStart") and str(reg["procStart"]) != started):
            continue
        sock = reg.get("messagingSocketPath")
        if not sock or not os.path.exists(sock):
            continue
        name = reg.get("name") or ""
        if re.fullmatch(r"organizer(-[\w-]+)?", name) and reg.get("kind") != "interactive":
            continue  # a relay from this app or an earlier run
        sessions.append(_session(reg, "wsl", reg.get("cwd", ""), None, wsl_exe(pid, started)))
    if WIN_REGISTRY_DIR is not None:
        win_regs = list(_read_registry(WIN_REGISTRY_DIR))
        pids = windows_claude_pids() if win_regs else set()
        for reg in win_regs:
            if reg["pid"] not in pids:
                continue
            if _version(reg.get("version")) < WIN_MESSAGING_MIN:
                block = ("This Windows session's Claude Code is too old to receive messages; "
                         "update Claude Code on Windows.")
            else:
                block = "The organizer can't deliver notes to Windows sessions yet."
            exe = windows_exe(reg["pid"]) if reg.get("entrypoint") == "claude-vscode" else ""
            sessions.append(_session(reg, "windows", win_to_wsl(reg.get("cwd", "")), block, exe))
    counts = {}
    for s in sessions:
        key = (s["platform"], s["name"])
        counts[key] = counts.get(key, 0) + 1
    for s in sessions:
        s["ambiguous"] = bool(s["name"]) and counts[(s["platform"], s["name"])] > 1
    sessions.sort(key=lambda s: (s["cwd"], s["platform"], s["name"]))
    return sessions


def in_folder(cwd, folder):
    folder = folder.rstrip("/")
    return cwd == folder or cwd.startswith(folder + "/")


# ------------------------------------------------------------------ boards

def board_id_for(folder):
    base = re.sub(r"[^a-z0-9]+", "-", Path(folder).name.lower()).strip("-") or "root"
    return f"{base}-{hashlib.sha1(folder.encode()).hexdigest()[:6]}"


def board_path(bid):
    if not re.fullmatch(r"[a-z0-9-]+", bid or ""):
        raise ValueError("bad board id")
    return BOARDS_DIR / f"{bid}.json"


def load_board(bid):
    path = board_path(bid)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_board(board):
    path = board_path(board["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def list_boards():
    boards = []
    for f in sorted(BOARDS_DIR.glob("*.json")):
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        boards.append({"id": b["id"], "title": b["title"], "folder": b["folder"]})
    return boards


DIR_LIMIT = 1000


def normalize_folder(raw):
    """A folder typed or pasted by the user -> an existing WSL path.
    Accepts C:\\... and ~/... as well as /mnt/c/... ; quotes are ignored."""
    path = raw.strip().strip('"').strip("'").strip()
    path = win_to_wsl(path)
    if path.startswith("~"):
        path = os.path.expanduser(path)
    if not path.startswith("/"):
        raise ValueError("Give a full folder path, e.g. C:\\Users\\you\\project, "
                         "/mnt/c/Users/you/project or ~/project.")
    path = os.path.normpath(path)
    if not os.path.isdir(path):
        raise ValueError(f"No such folder: {path}")
    return path


def places():
    """Starting points for the folder browser."""
    out = []
    if WIN_HOME:
        out.append({"label": "Windows home", "path": str(WIN_HOME)})
        out.append({"label": "Windows Desktop", "path": str(WIN_HOME / "Desktop")})
    out.append({"label": "WSL home", "path": str(Path.home())})
    return [p for p in out if os.path.isdir(p["path"])]


def list_dirs(raw):
    """Subfolders of a folder, for the New board browser (dot folders hidden)."""
    path = normalize_folder(raw or (str(WIN_HOME / "Desktop") if WIN_HOME else str(Path.home())))
    names = []
    try:
        with os.scandir(path) as entries:
            for e in entries:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        names.append(e.name)
                except OSError:
                    continue
    except OSError as e:
        raise ValueError(f"Can't open {path}: {e.strerror or e}")
    names.sort(key=str.lower)
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else None,
            "dirs": names[:DIR_LIMIT], "truncated": len(names) > DIR_LIMIT}


def create_board(folder):
    folder = folder.rstrip("/") or "/"
    bid = board_id_for(folder)
    with lock:
        if load_board(bid) is None:
            save_board({
                "id": bid, "title": Path(folder).name or folder, "folder": folder,
                "nodes": {}, "hidden": [], "connections": [], "activity": [],
            })
    return bid


def add_activity(board, text, level="info"):
    board["activity"].insert(0, {"t": time.time(), "text": text, "level": level})
    del board["activity"][ACTIVITY_KEEP:]


CARD_W, CARD_H = 220, 120  # card footprint used to keep new cards apart


def overlaps(board, x, y):
    return any(abs(x - n["x"]) < CARD_W + 20 and abs(y - n["y"]) < CARD_H + 15
               for n in board["nodes"].values())


def free_slot(board):
    """The first grid spot that no card (moved or not) overlaps."""
    i = 0
    while True:
        x, y = 40 + (i % 4) * 270, 40 + (i // 4) * 150
        if not overlaps(board, x, y):
            return x, y
        i += 1


def new_node(s, x, y):
    node = {"x": x, "y": y, "name": s["name"], "cwd": s["cwd"], "platform": s["platform"],
            "winCwd": s["winCwd"], "lastSeen": time.time()}
    if s.get("title"):
        node["title"] = s["title"]
    return node


def sync_board(board, live):
    """Auto-add live sessions from the board folder, refresh cached names,
    prune ended sessions that have no arrows. Returns True if changed."""
    now = time.time()
    by_id = {s["sessionId"]: s for s in live}
    changed = False
    for s in live:
        sid = s["sessionId"]
        node = board["nodes"].get(sid)
        if node is None and in_folder(s["cwd"], board["folder"]) and sid not in board["hidden"]:
            x, y = free_slot(board)
            node = board["nodes"][sid] = {"x": x, "y": y}
            changed = True
        if node is not None:
            fresh = {"name": s["name"], "cwd": s["cwd"], "platform": s["platform"],
                     "winCwd": s["winCwd"]}
            if s["title"]:
                fresh["title"] = s["title"]
            if s["model"]:
                fresh["model"] = s["model"]
            if any(node.get(k) != v for k, v in fresh.items()):
                node.update(fresh)
                changed = True
            if now - node.get("lastSeen", 0) > 30:
                node["lastSeen"] = now
                changed = True
    linked = {c["from"] for c in board["connections"]} | {c["to"] for c in board["connections"]}
    for sid in list(board["nodes"]):
        node = board["nodes"][sid]
        if sid not in by_id and sid not in linked and now - node.get("lastSeen", 0) > PRUNE_AFTER:
            del board["nodes"][sid]
            changed = True
    return changed


def board_view(bid):
    live = live_sessions()
    with lock:
        board = load_board(bid)
        if board is None:
            return None
        if sync_board(board, live):
            save_board(board)
    by_id = {s["sessionId"]: s for s in live}
    nodes = []
    for sid, node in board["nodes"].items():
        s = by_id.get(sid)
        nodes.append({
            **(s or {"sessionId": sid, "name": node.get("name", sid[:8]),
                     "title": node.get("title"), "cwd": node.get("cwd", ""),
                     "platform": node.get("platform", "wsl"), "winCwd": node.get("winCwd"),
                     "model": node.get("model"),
                     "status": "ended"}),
            "x": node["x"], "y": node["y"], "live": s is not None,
        })
    others = [s for s in live if s["sessionId"] not in board["nodes"]]
    return {
        "board": {k: board[k] for k in ("id", "title", "folder", "connections", "activity")},
        "nodes": nodes, "available": others, "boards": list_boards(),
    }


# ------------------------------------------------------------------- notes

def who(s):
    """A session as the notes introduce it: title, address and folder."""
    if s.get("title"):
        return f"\"{s['title']}\" (@{s['name']}, folder: {s['cwd']})"
    return f"@{s['name']} (folder: {s['cwd']})"


# Keep in step with defaultNotes() in static/app.js, which previews them.
def default_notes(src, dst, reason, tell_src=True):
    """Notes for an arrow src -> dst: src starts the conversation and dst
    replies. If src is not told, dst gets the start instruction instead, so
    someone always goes first."""
    why = reason.strip() or "(no reason given)"
    start = lambda other: (f"Start now: send @{other['name']} your current view on this with "
                           f"SendMessage, then reply when it answers. No reply to the organizer is needed.")
    to_src = (
        f"[Agent organizer] Your user connected you to {who(dst)} and wants you two to talk.\n"
        f"Why: {why}\n" + start(dst)
    )
    to_dst = (
        f"[Agent organizer] Your user connected {who(src)} to you and wants you two to talk.\n"
        f"Why: {why}\n" + (
            f"@{src['name']} will message you about this. When it does, reply to @{src['name']} "
            f"with SendMessage. No reply to the organizer is needed." if tell_src else start(src))
    )
    return to_src, to_dst


def tag(s):
    """Title plus address, e.g. "R8 fixes" (@thesis-git-da)."""
    return f"\"{s['title']}\" (@{s['name']})" if s.get("title") else f"@{s['name']}"


def disconnect_note(src, dst, reason):
    why = f" ({reason.strip()})" if reason.strip() else ""
    return (
        f"[Agent organizer] Your user removed the connection "
        f"{tag(src)} -> {tag(dst)}{why}. Stop sending messages for that purpose. "
        f"No reply is needed."
    )


# ------------------------------------------------------------------- relay

RELAY_SYSTEM = (
    "You are the message relay of the user's Agent Organizer, a local tool the "
    "user runs to connect their own Claude Code sessions on this machine. Your "
    "only job is to deliver the messages you are given, verbatim, with the "
    "SendMessage tool."
)


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def relay_send(items):
    """Deliver [{"to": name, "text": str}, ...] through one headless Claude run.
    Returns (states, meta); states[i] = {"state": sent|altered|failed, "detail"}."""
    parts = [
        f"Deliver these {len(items)} messages. For each ITEM make exactly one "
        "SendMessage call with `to` set to the TO value and `message` set to the "
        "text between the BEGIN and END lines, copied character for character. "
        "Do not reword, shorten, summarize or add anything. Make no other tool "
        "calls. When all calls are done, reply with the single word done."
    ]
    for i, it in enumerate(items, 1):
        parts.append(f"ITEM {i}\nTO: {it['to']}\nBEGIN\n{it['text']}\nEND")
    cmd = [
        CLAUDE_BIN, "-p", "--model", RELAY_MODEL, "--name", RELAY_NAME,
        "--tools", "SendMessage", "--allowedTools", "SendMessage",
        "--no-session-persistence", "--output-format", "stream-json", "--verbose",
        "--append-system-prompt", RELAY_SYSTEM, "\n\n".join(parts),
    ]
    t0 = time.time()
    states = [{"state": "failed", "detail": "the relay made no SendMessage call"} for _ in items]
    meta = {"cost_usd": None, "seconds": None, "error": None}
    try:
        proc = subprocess.Popen(cmd, cwd=APP_DIR, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as e:
        meta["error"] = f"could not start claude: {e}"
        for s in states:
            s["detail"] = meta["error"]
        return states, meta
    relay_pids.add(proc.pid)
    try:
        out, err = proc.communicate(timeout=RELAY_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        meta["error"] = f"relay timed out after {RELAY_TIMEOUT}s"
    finally:
        relay_pids.discard(proc.pid)
    meta["seconds"] = round(time.time() - t0, 1)

    calls, results, final_text = {}, {}, ""
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use" and c.get("name") == "SendMessage":
                    calls[c["id"]] = c.get("input", {})
        elif ev.get("type") == "user":
            for c in ev["message"].get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    content = c.get("content")
                    if isinstance(content, list):
                        content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
                    results[c.get("tool_use_id")] = (bool(c.get("is_error")), str(content))
        elif ev.get("type") == "result":
            meta["cost_usd"] = ev.get("total_cost_usd")
            final_text = str(ev.get("result") or "")

    used = set()
    for i, it in enumerate(items):
        for cid, inp in calls.items():
            if cid in used or inp.get("to") != it["to"]:
                continue
            used.add(cid)
            is_err, res = results.get(cid, (True, "no tool result"))
            ok = False
            try:
                ok = not is_err and json.loads(res).get("success") is True
            except ValueError:
                pass
            if not ok:
                states[i] = {"state": "failed", "detail": res[:400]}
            elif _norm(inp.get("message")) != _norm(it["text"]):
                states[i] = {"state": "altered", "detail": "the relay changed the wording",
                             "sentText": inp.get("message")}
            else:
                states[i] = {"state": "sent", "detail": "queued in the agent's inbox"}
            break
        else:
            if meta["error"]:
                states[i]["detail"] = meta["error"]
            elif final_text:
                states[i]["detail"] = final_text[:400]
            elif proc.returncode:
                states[i]["detail"] = (err or "").strip()[:400] or f"claude exited {proc.returncode}"

    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"t": time.time(), "items": items, "states": states,
                              "meta": meta}, ensure_ascii=False) + "\n")
    return states, meta


def _summary(states):
    marks = {"sent": "sent", "altered": "sent (reworded)", "failed": "failed"}
    return ", ".join(marks[s["state"]] for s in states)


def deliver_connection(bid, conn_id, sides):
    """Send the stored notes of one connection for the given sides (from/to)."""
    with lock:
        board = load_board(bid)
        conn = next((c for c in board["connections"] if c["id"] == conn_id), None)
        if conn is None:
            return
        ends = {side: dict(board["nodes"][conn[side]]) for side in ("from", "to")}
        items = [{"side": side, "to": ends[side]["name"], "text": conn["notes"][side]["text"]}
                 for side in sides]
    states, meta = relay_send([{"to": it["to"], "text": it["text"]} for it in items])
    with lock:
        board = load_board(bid)
        conn = next((c for c in board["connections"] if c["id"] == conn_id), None)
        if conn is None:
            return
        for it, st in zip(items, states):
            conn["notes"][it["side"]].update(st, sentAt=time.time())
        note_states = [n["state"] for n in conn["notes"].values() if n.get("enabled")]
        conn["status"] = ("sent" if all(s in ("sent", "altered") for s in note_states)
                          else "sending" if "sending" in note_states else "failed")
        level = "ok" if conn["status"] == "sent" else "error"
        add_activity(board, f"{label(ends['from'])} → {label(ends['to'])}: notes {_summary(states)}"
                     f" ({meta['seconds']}s)", level)
        save_board(board)


def connect(bid, body):
    live = {s["sessionId"]: s for s in live_sessions()}
    src, dst = live.get(body.get("from")), live.get(body.get("to"))
    if not src or not dst:
        raise ValueError("both agents must be running to connect them")
    if src["sessionId"] == dst["sessionId"]:
        raise ValueError("an agent cannot be connected to itself")
    for s in (src, dst):
        if s.get("messageBlock"):
            raise ValueError(s["messageBlock"])
    if src.get("platform") != dst.get("platform"):
        raise ValueError("A WSL session and a Windows session can't message each other.")
    for s in (src, dst):
        if s["ambiguous"]:
            raise ValueError(f"two running sessions are named {s['name']}; "
                             f"run /rename in one of them first")
    reason = str(body.get("reason", ""))
    d_src, d_dst = default_notes(src, dst, reason, tell_src=bool(body.get("notifyFrom", True)))
    notes = {
        "from": {"enabled": bool(body.get("notifyFrom", True)),
                 "text": str(body.get("textFrom") or d_src)},
        "to": {"enabled": bool(body.get("notifyTo", True)),
               "text": str(body.get("textTo") or d_dst)},
    }
    for n in notes.values():
        n["state"] = "sending" if n["enabled"] else "skipped"
    sides = [side for side, n in notes.items() if n["enabled"]]
    with lock:
        board = load_board(bid)
        for c in board["connections"]:
            if c["from"] == src["sessionId"] and c["to"] == dst["sessionId"]:
                raise ValueError("these agents are already connected in this direction")
        for s in (src, dst):
            if s["sessionId"] not in board["nodes"]:
                x, y = free_slot(board)
                board["nodes"][s["sessionId"]] = new_node(s, x, y)
        conn = {
            "id": uuid.uuid4().hex[:10], "from": src["sessionId"], "to": dst["sessionId"],
            "reason": reason, "createdAt": time.time(),
            "status": "sending" if sides else "sent", "notes": notes,
        }
        board["connections"].append(conn)
        add_activity(board, f"Connected {label(src)} → {label(dst)}")
        save_board(board)
    if sides:
        threading.Thread(target=deliver_connection, args=(bid, conn["id"], sides),
                         daemon=True).start()
    return conn


def resend(bid, conn_id):
    with lock:
        board = load_board(bid)
        conn = next((c for c in board["connections"] if c["id"] == conn_id), None)
        if conn is None:
            raise ValueError("no such connection")
        live = {s["sessionId"] for s in live_sessions()}
        if conn["from"] not in live or conn["to"] not in live:
            raise ValueError("both agents must be running to resend")
        sides = [side for side, n in conn["notes"].items()
                 if n.get("enabled") and n.get("state") == "failed"]
        if not sides:
            raise ValueError("nothing to resend")
        for side in sides:
            conn["notes"][side]["state"] = "sending"
        conn["status"] = "sending"
        save_board(board)
    threading.Thread(target=deliver_connection, args=(bid, conn_id, sides), daemon=True).start()


def start_conversation(bid, conn_id):
    """Send the start note to the arrow's source chat (for arrows made
    without telling it, so nobody went first)."""
    live = {s["sessionId"]: s for s in live_sessions()}
    with lock:
        board = load_board(bid)
        conn = next((c for c in board["connections"] if c["id"] == conn_id), None)
        if conn is None:
            raise ValueError("no such connection")
        if conn["from"] not in live:
            raise ValueError("That chat is not running.")
        src = live[conn["from"]]
        dst = live.get(conn["to"]) or dict(board["nodes"].get(conn["to"], {"name": "?", "cwd": ""}))
        text, _ = default_notes(src, dst, conn.get("reason", ""))
        conn["notes"]["from"] = {"enabled": True, "text": text, "state": "sending"}
        conn["status"] = "sending"
        save_board(board)
    threading.Thread(target=deliver_connection, args=(bid, conn_id, ["from"]), daemon=True).start()


def disconnect(bid, body):
    conn_id, notify = body.get("id"), bool(body.get("notify", True))
    with lock:
        board = load_board(bid)
        conn = next((c for c in board["connections"] if c["id"] == conn_id), None)
        if conn is None:
            raise ValueError("no such connection")
        board["connections"].remove(conn)
        src = dict(board["nodes"].get(conn["from"], {"name": "?"}))
        dst = dict(board["nodes"].get(conn["to"], {"name": "?"}))
        add_activity(board, f"Disconnected {label(src)} → {label(dst)}")
        save_board(board)
    if notify:
        send_disconnect_notes(bid, [(conn, src, dst)])


def send_disconnect_notes(bid, removed):
    """Tell the running ends of removed arrows [(conn, src node, dst node)]."""
    live = {s["sessionId"] for s in live_sessions()}
    items, targets = [], []
    for conn, src, dst in removed:
        text = disconnect_note(src, dst, conn.get("reason", ""))
        for sid, n in ((conn["from"], src), (conn["to"], dst)):
            if sid in live:
                items.append({"to": n["name"], "text": text})
                targets.append(n)
    if not items:
        return

    def run():
        states, meta = relay_send(items)
        with lock:
            b = load_board(bid)
            ok = all(s["state"] != "failed" for s in states)
            add_activity(b, f"Disconnect notes to {', '.join(label(t) for t in targets)}: "
                            f"{_summary(states)}", "ok" if ok else "error")
            save_board(b)
    threading.Thread(target=run, daemon=True).start()


def update_layout(bid, body):
    with lock:
        board = load_board(bid)
        for sid, pos in body.get("positions", {}).items():
            if sid in board["nodes"]:
                board["nodes"][sid]["x"] = float(pos["x"])
                board["nodes"][sid]["y"] = float(pos["y"])
        save_board(board)


def add_node(bid, body):
    sid = body.get("sessionId")
    live = {s["sessionId"]: s for s in live_sessions()}
    if sid not in live:
        raise ValueError("that session is no longer running")
    with lock:
        board = load_board(bid)
        if sid in board["hidden"]:
            board["hidden"].remove(sid)
        if sid not in board["nodes"]:
            x, y = (float(body["x"]), float(body["y"])) if "x" in body else (None, None)
            if x is None or overlaps(board, x, y):
                x, y = free_slot(board)
            board["nodes"][sid] = new_node(live[sid], x, y)
        save_board(board)


def remove_node(bid, body):
    """Take a card off the board, together with its arrows."""
    sid, notify = body.get("sessionId"), bool(body.get("notify", False))
    with lock:
        board = load_board(bid)
        gone = [c for c in board["connections"] if sid in (c["from"], c["to"])]
        removed = [(c, dict(board["nodes"].get(c["from"], {"name": "?"})),
                    dict(board["nodes"].get(c["to"], {"name": "?"}))) for c in gone]
        board["connections"] = [c for c in board["connections"] if c not in gone]
        node = board["nodes"].pop(sid, None) or {"name": "?"}
        if sid not in board["hidden"]:
            board["hidden"].append(sid)
        arrows = f" and its {len(gone)} arrow{'s' if len(gone) != 1 else ''}" if gone else ""
        add_activity(board, f"Removed {label(node)}{arrows} from the board")
        save_board(board)
    if notify and removed:
        send_disconnect_notes(bid, removed)


# -------------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "AgentOrganizer/1"

    def log_message(self, fmt, *args):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"localhost:{PORT}", f"127.0.0.1:{PORT}")

    def _send(self, code, payload=None, ctype="application/json; charset=utf-8", raw=None):
        data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, {"error": "bad host"})
        url = urlparse(self.path)
        if url.path in STATIC_FILES:
            name, ctype = STATIC_FILES[url.path]
            return self._send(HTTPStatus.OK, ctype=ctype, raw=(STATIC_DIR / name).read_bytes())
        if url.path == "/api/agents":
            try:
                sid = parse_qs(url.query).get("session", [""])[0]
                return self._send(HTTPStatus.OK, session_agents(sid))
            except ValueError as e:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        if url.path == "/api/state":
            bid = parse_qs(url.query).get("board", [""])[0]
            if not bid:
                live = live_sessions()
                return self._send(HTTPStatus.OK, {
                    "boards": list_boards(),
                    "folders": sorted({s["cwd"] for s in live}),
                    "places": places(),
                })
            try:
                view = board_view(bid)
            except ValueError as e:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            if view is None:
                return self._send(HTTPStatus.NOT_FOUND, {"error": "no such board"})
            view["folders"] = sorted({s["cwd"] for s in live_sessions()})
            return self._send(HTTPStatus.OK, view)
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        # The custom header forces a CORS preflight, which this server never
        # answers, so other web pages cannot drive it.
        if not self._host_ok() or self.headers.get("X-Organizer") != "1":
            return self._send(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(HTTPStatus.BAD_REQUEST, {"error": "bad json"})
        parts = urlparse(self.path).path.strip("/").split("/")
        try:
            if parts == ["api", "boards"]:
                folder = normalize_folder(str(body.get("folder", "")))
                return self._send(HTTPStatus.OK, {"id": create_board(folder)})
            if parts == ["api", "dirs"]:
                return self._send(HTTPStatus.OK, list_dirs(str(body.get("path") or "")))
            if len(parts) == 4 and parts[:2] == ["api", "board"]:
                bid, action = parts[2], parts[3]
                if load_board(bid) is None:
                    return self._send(HTTPStatus.NOT_FOUND, {"error": "no such board"})
                handlers = {
                    "connect": lambda: connect(bid, body),
                    "disconnect": lambda: disconnect(bid, body),
                    "resend": lambda: resend(bid, body.get("id")),
                    "start": lambda: start_conversation(bid, body.get("id")),
                    "layout": lambda: update_layout(bid, body),
                    "add": lambda: add_node(bid, body),
                    "remove": lambda: remove_node(bid, body),
                }
                if action in handlers:
                    result = handlers[action]()
                    return self._send(HTTPStatus.OK, {"ok": True, "result": result})
        except ValueError as e:
            return self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})


def main():
    BOARDS_DIR.mkdir(exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Agent Organizer running at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
