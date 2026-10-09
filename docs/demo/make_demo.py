#!/usr/bin/env python3
"""Re-records the demo at the top of the README: docs/demo/demo.gif, demo.mp4
and board.png. Everything on screen is made up.

The script builds a scratch home with a few fake Claude Code chats and their
transcripts, starts a copy of the real server on a free port against it (with
fake_claude.py in place of `claude`, so nothing real is ever called or
messaged), drives the real page in a headless browser with a drawn pointer,
and turns the recording into the files. It stops what it started (by PID) and
deletes the scratch folder when it is done.

Run it from the repo (or a worktree) with the venv that tests/setup.sh makes
(that venv lives in the main folder), and a scratch folder in TMPDIR:

  env -u DBUS_SESSION_BUS_ADDRESS -u DISPLAY -u WAYLAND_DISPLAY \\
      TMPDIR=<some scratch folder> <main folder>/tests/.venv/bin/python -I docs/demo/make_demo.py

  --out DIR   where the files go (default: this folder)
  --keep      keep the scratch folder (and its raw frames, in gif/ and mp4/)
  --still     only the board.png still, no recording
  --shot      only shot.png, the starting board (to check the layout)

Needs Linux with `unshare` and `nsenter` (they make the made-up home show as
/home/you) and a full `ffmpeg` (with libx264) for the GIF and the MP4: on PATH,
or set LTT_FFMPEG=<path>. Without one, e.g.:
  <venv>/bin/pip install --target <folder> imageio-ffmpeg
  LTT_FFMPEG=<folder>/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-<version>
"""
import argparse
import base64
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Playwright isn't installed here: run this with the venv from tests/setup.sh")

FOLDER = "/home/you/shop-app"          # the board's folder, as it shows on screen
VIEW = (1440, 900)                     # browser window, in CSS pixels
GIF_WIDTH, GIF_FPS, MP4_FPS = 1200, 12.5, 30
SCRUB = ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY")  # keeps a keyring box off the screen

# The made-up chats. kind: terminal | cursor | background.
CHATS = [
    dict(key="api", sid="3f2a9c10-5b7e-4d21-9a60-1c8e47d5b001", title="Orders API", kind="terminal", state="busy",
         pos=(760, 370), model="claude-opus-5-5",
         ask="Add a POST /orders endpoint to the shop API. Check every item against the catalog and return the new order's id.",
         said="POST /orders is in routes/orders.js. It checks each item against the catalog, rejects an empty basket "
              "and answers 201 with the order's id. I added three tests and I'm running them now.",
         doing="Run the orders tests"),
    dict(key="web", sid="3f2a9c10-5b7e-4d21-9a60-1c8e47d5b002", title="Checkout page", kind="cursor", state="idle",
         pos=(340, 560), model="claude-sonnet-5-5",
         ask="Build the checkout page: the basket, a coupon box and a Pay button.",
         said="The checkout page is ready: the basket summary, a coupon box and a Pay button that stays off while the "
              "basket is empty. Pay doesn't call anything yet, because the orders endpoint doesn't exist."),
    dict(key="tests", sid="3f2a9c10-5b7e-4d21-9a60-1c8e47d5b003", title="Checkout tests", kind="background",
         state="busy", job="a1b2c3d4", pos=(790, 640), model="claude-sonnet-5-5",
         ask="Run the checkout tests whenever the page changes and tell me what breaks.",
         doing="Run the checkout tests"),
    dict(key="docs", sid="3f2a9c10-5b7e-4d21-9a60-1c8e47d5b004", title="API docs", kind="background",
         state="idle", job="e5f6a7b8", pos=(340, 200), model="claude-haiku-5-5",
         ask="Keep the API docs in step with the routes.",
         said="The docs cover GET /products and GET /cart. I'll add POST /orders as soon as it exists."),
]
# The talk after the new arrow (web starts, as the arrow points from it).
TALK = [
    ("web", "Hi! The Pay button needs your new /orders endpoint. What should I send, and when will it be ready?"),
    ("api", "POST /orders takes { items: [{ sku, qty }], coupon? } and answers { id }. It's passing locally; "
            "I'll merge it in about ten minutes."),
    ("web", "Perfect, I'll call it from Pay. Tell me when it's in."),
    ("api", "Merged. It's live on main now."),
]
REASON = "needs the /orders endpoint"
FIRST_ARROW = ("docs", "api", "keep the API docs in sync")


def say(*a):
    print(*a, flush=True)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


# ------------------------------------------------------------------ the world

class World:
    """The scratch home, the dummy chat processes and the server, all inside
    one private mount namespace in which the scratch home is /home."""

    def __init__(self, root):
        self.root = Path(root)
        self.home = self.root / "home"           # becomes /home
        self.you = self.home / "you"
        self.procs = {}                          # name -> Popen
        self.pids = {}                           # chat key -> pid of its dummy process
        self.port = free_port()
        self.board = None
        self.log = {}                            # chat key -> its transcript path
        self.ns = None

    # -- files
    def write(self, path, text, mode=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if mode:
            path.chmod(mode)

    def append(self, key, rec, at):
        rec = {**rec, "timestamp": iso(at), "sessionId": next(c["sid"] for c in CHATS if c["key"] == key),
               "cwd": FOLDER, "uuid": f"{random.Random(at).getrandbits(96):024x}"}
        with self.log[key].open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")

    def build(self):
        now = time.time()
        for sub in ("shop-app", ".claude/sessions", ".claude/projects/-home-you-shop-app", ".claude/sock", "bin", "ltt"):
            (self.you / sub).mkdir(parents=True, exist_ok=True)
        (self.home / "winhome").mkdir(exist_ok=True)          # an empty "Windows home": none of the user's sessions
        shutil.copy(REPO / "server.py", self.you / "ltt" / "server.py")
        shutil.copytree(REPO / "static", self.you / "ltt" / "static")
        shutil.copy(HERE / "fake_claude.py", self.you / "bin" / "claude")
        (self.you / "bin" / "claude").chmod(0o755)
        self.write(self.you / "relay-delay", "0")
        for i, c in enumerate(CHATS):
            sid, key = c["sid"], c["key"]
            self.log[key] = self.you / ".claude/projects/-home-you-shop-app" / f"{sid}.jsonl"
            t = now - (40 - 6 * i) * 60
            self.append(key, {"type": "user", "message": {"role": "user", "content": c["ask"]}}, t)
            if c.get("said"):
                self.append(key, {"type": "assistant", "message": {
                    "id": f"msg_{key}1", "role": "assistant", "model": c["model"], "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": c["said"]}]}}, t + 90)
            if c.get("doing"):
                self.append(key, {"type": "assistant", "message": {
                    "id": f"msg_{key}2", "role": "assistant", "model": c["model"], "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "id": f"toolu_{key}", "name": "Bash",
                                 "input": {"command": "npm test", "description": c["doing"]}}]}}, t + 120)
            self.append(key, {"type": "ai-title", "aiTitle": c["title"]}, t + 130)

    # -- processes
    def start_namespace(self):
        script = f'mount --bind "{self.home}" /home && exec sleep 7200'
        holder = subprocess.Popen(["unshare", "-rm", "sh", "-c", script], env=self.clean_env())
        self.procs["holder"] = holder
        self.ns = ["nsenter", "-t", str(holder.pid), "-U", "-m", "--preserve-credentials"]
        for _ in range(100):
            if subprocess.run(self.ns + ["test", "-d", "/home/you/ltt"], env=self.clean_env(),
                                                   stderr=subprocess.DEVNULL).returncode == 0:
                return
            time.sleep(0.05)
        raise RuntimeError("the private /home didn't come up")

    @staticmethod
    def clean_env(**more):
        env = {k: v for k, v in os.environ.items() if k not in SCRUB and not k.startswith(("CLAUDE", "LTT_", "ORGANIZER_"))}
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        env.update(more)
        return env

    def start_chats(self):
        """One dummy process (a copy of `sleep`) per chat, started in the
        namespace so the server reads the same /proc paths a real chat has,
        plus the registry file and socket file Claude Code writes for it."""
        now = time.time()
        for i, c in enumerate(CHATS):
            if c["kind"] == "cursor":
                exe = "/home/you/.cursor-server/extensions/anthropic.claude-code-2.1.150-linux-x64/resources/native-binary/claude"
            else:
                exe = "/home/you/.local/share/claude/versions/2.1.150"
            (self.home / exe[len("/home/"):]).parent.mkdir(parents=True, exist_ok=True)
            if not (self.home / exe[len("/home/"):]).exists():
                shutil.copy(shutil.which("sleep"), self.home / exe[len("/home/"):])
            p = subprocess.Popen(self.ns + [exe, "7200"], env=self.clean_env(), stdout=subprocess.DEVNULL)
            self.procs[f"chat-{c['key']}"] = p
            self.pids[c["key"]] = p.pid
            sock = f"/home/you/.claude/sock/{p.pid}.sock"
            self.write(self.home / sock[len("/home/"):], "")
            reg = {"pid": p.pid, "sessionId": c["sid"], "cwd": FOLDER, "name": c["key"],
                   "startedAt": int((now - 45 * 60) * 1000), "version": "2.1.150", "status": c["state"],
                   "kind": "bg" if c["kind"] == "background" else "interactive",
                   "entrypoint": {"cursor": "claude-vscode", "terminal": "cli", "background": "cli"}[c["kind"]],
                   "messagingSocketPath": sock}
            if c.get("job"):
                reg["jobId"] = c["job"]
            self.write(self.you / ".claude/sessions" / f"{p.pid}.json", json.dumps(reg))
        rows = [{"kind": "background", "id": c["job"], "sessionId": c["sid"], "name": c["key"], "cwd": FOLDER,
                 "state": "working", "status": c["state"], "pid": self.pids[c["key"]],
                 "startedAt": int((now - 45 * 60) * 1000)} for c in CHATS if c["kind"] == "background"]
        self.write(self.you / "agents.json", json.dumps(rows))

    def start_server(self):
        env = self.clean_env(HOME="/home/you", CLAUDE_CONFIG_DIR="/home/you/.claude", LTT_PORT=str(self.port),
                             LTT_CLAUDE="/home/you/bin/claude", LTT_WINDOWS_HOME="/home/winhome",
                             LTT_DEMO_AGENTS="/home/you/agents.json", LTT_DEMO_DELAY="/home/you/relay-delay",
                             LANG="C.UTF-8", PYTHONUNBUFFERED="1")
        out = (self.root / "server.log").open("w")
        p = subprocess.Popen(self.ns + ["python3", "/home/you/ltt/server.py"], env=env, stdout=out, stderr=out)
        self.procs["server"] = p
        for _ in range(100):
            try:
                self.get("/api/state")
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("the server didn't start; see " + str(self.root / "server.log"))

    # -- the server's API
    def url(self, path=""):
        return f"http://localhost:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=10) as r:
            return json.load(r)

    def post(self, path, body):
        req = urllib.request.Request(self.url(path), json.dumps(body).encode(), {
            "Content-Type": "application/json", "X-Let-Them-Talk": "1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def set_board(self):
        """The board for the folder, the cards where the story wants them, and
        the arrow that is already there."""
        self.board = self.post("/api/boards", {"folder": FOLDER})["id"]
        for _ in range(50):
            nodes = {n["sessionId"]: n for n in self.get(f"/api/state?board={self.board}")["nodes"]}
            if len(nodes) == len(CHATS):
                break
            time.sleep(0.1)
        self.post(f"/api/board/{self.board}/layout",
                  {"positions": {c["sid"]: {"x": c["pos"][0], "y": c["pos"][1]} for c in CHATS}})
        a, b, why = FIRST_ARROW
        sid = {c["key"]: c["sid"] for c in CHATS}
        self.post(f"/api/board/{self.board}/connect", {"from": sid[a], "to": sid[b], "reason": why})
        for _ in range(100):
            conns = self.get(f"/api/state?board={self.board}")["board"]["connections"]
            if conns and all(c["status"] == "sent" for c in conns):
                return
            time.sleep(0.1)
        raise RuntimeError("the first arrow's notes weren't sent")

    # -- the chats talk (as SendMessage does, in both transcripts)
    def talk(self, n):
        """Message n of TALK: a SendMessage call in the sender's transcript,
        and the message arriving in the receiver's."""
        key, text = TALK[n]
        to = next(c["key"] for c in CHATS if c["key"] == ("api" if key == "web" else "web"))
        mid, now = f"msg_demo{n + 1}", time.time()
        model = next(c["model"] for c in CHATS if c["key"] == key)
        call = f"toolu_talk{n + 1}"
        self.append(key, {"type": "assistant", "message": {
            "id": f"msg_talk{n + 1}", "role": "assistant", "model": model, "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": call, "name": "SendMessage", "input": {"to": to, "message": text}}]}}, now)
        self.append(key, {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call, "content": "Message sent"}]},
            "toolUseResult": {"success": True, "msg_id": mid}}, now + 0.2)
        self.append(to, {"type": "user", "origin": {"kind": "peer", "msg_id": mid, "name": key}, "message": {
            "role": "user", "content": f'<cross-session-message from-name="{key}" msg-id="{mid}">{text}</cross-session-message>'}},
            now + 0.4)

    def stop(self):
        for name in ("server", *[n for n in self.procs if n.startswith("chat-")], "holder"):
            p = self.procs.pop(name, None)
            if p is None:
                continue
            if p.poll() is None:       # our own child, not yet reaped: its PID can't belong to anything else
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        for _ in range(50):
            if port_free(self.port):
                break
            time.sleep(0.1)




# ------------------------------------------------------------------- recording

POINTER_JS = r"""
(() => {
  const host = document.createElement('div');
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
    <style>
      .p { position: fixed; inset: auto; left: 0; top: 0; margin: 0; padding: 0; border: 0; background: none;
           width: 28px; height: 32px; overflow: visible; pointer-events: none; opacity: 0; transition: opacity .25s; }
      .p::backdrop, .ring::backdrop { display: none; }
      svg { position: absolute; left: 0; top: 0; filter: drop-shadow(0 1px 1.5px rgba(0,0,0,.45)); }
      .ring { position: fixed; inset: auto; left: 0; top: 0; margin: 0; padding: 0; border: 0; background: none;
              width: 0; height: 0; overflow: visible; pointer-events: none; }
      .ring i { position: absolute; left: -22px; top: -22px; width: 44px; height: 44px; border-radius: 50%;
                border: 3px solid rgba(20, 110, 245, .75); animation: pulse .5s ease-out forwards; }
      @keyframes pulse { from { transform: scale(.25); opacity: 1; } to { transform: scale(1); opacity: 0; } }
    </style>
    <div class="p" popover="manual" id="p"><svg width="28" height="32" viewBox="0 0 28 32">
      <path d="M4 2.5 L4 24.5 L9.6 19.4 L13.6 28.6 L17.4 27 L13.5 18 L21.2 17.6 Z" fill="#fff" stroke="#16181d"
            stroke-width="1.6" stroke-linejoin="round"/></svg></div>
    <div class="ring" popover="manual" id="r"></div>`;
  const p = root.getElementById('p'), r = root.getElementById('r');
  let x = -80, y = -80, shown = false;
  const place = () => { p.style.transform = `translate(${x}px, ${y}px)`; };
  const show = () => {
    for (const e of [r, p]) { try { e.hidePopover(); } catch {} try { e.showPopover(); } catch {} }
    place();
  };
  const start = () => { document.documentElement.append(host); show(); shown = true; };
  if (document.documentElement) start(); else addEventListener('DOMContentLoaded', start);
  addEventListener('pointermove', (e) => { x = e.clientX; y = e.clientY; p.style.opacity = 1; place(); }, true);
  addEventListener('pointerdown', (e) => {
    r.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
    r.replaceChildren(document.createElement('i'));
  }, true);
  // A dialog opened later sits above anything shown before it: show the pointer again, on top.
  new MutationObserver(() => { if (shown) show(); }).observe(document, { subtree: true, attributes: true, attributeFilter: ['open'] });
  addEventListener('toggle', () => { if (shown) show(); }, true);
})();
"""


class Screencast:
    """Chromium's own screencast: every frame it paints, with its time."""

    def __init__(self, page):
        self.cdp = page.context.new_cdp_session(page)
        self.frames = []
        self.cdp.on("Page.screencastFrame", self.got)

    def got(self, ev):
        # Stamped when it arrives, by the monotonic clock: the browser's own stamps follow the wall
        # clock, and WSL's steps forward now and then, which froze the recording for a few seconds.
        self.frames.append((time.monotonic(), base64.b64decode(ev["data"])))
        self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})

    def start(self):
        self.cdp.send("Page.startScreencast", {"format": "png", "everyNthFrame": 1})

    def stop(self):
        self.cdp.send("Page.stopScreencast")

    def report(self, since):
        """Where the screencast went quiet while the page was changing (debugging)."""
        stamps = sorted(f[0] for f in self.frames)
        gaps = [(b - a, a - since) for a, b in zip(stamps, stamps[1:]) if b - a > 0.3]
        say("screencast:", len(stamps), "frames; gaps over 0.3 s (length, at):",
            ", ".join(f"{g:.1f} s at {t:.1f}" for g, t in gaps))

    def save(self, folder, fps, end):
        """Frames at a steady rate as folder/%05d.png: each tick shows the
        latest frame painted by then, from the first frame to `end` (the
        screencast sends nothing while the page is still). Returns how many."""
        folder.mkdir(parents=True, exist_ok=True)
        frames = sorted(self.frames, key=lambda f: f[0])
        t0 = frames[0][0]
        count, last, written = int((end - t0) * fps), 0, {}
        for k in range(count):
            t = t0 + k / fps
            while last + 1 < len(frames) and frames[last + 1][0] <= t:
                last += 1
            if last not in written:
                written[last] = folder / f"src{last:05d}.png"
                written[last].write_bytes(frames[last][1])
            os.link(written[last], folder / f"{k:05d}.png")
        for path in written.values():
            path.unlink()
        return count


class Pointer:
    """The mouse, moved smoothly (the page draws the pointer: see POINTER_JS)."""

    def __init__(self, page):
        self.page, self.x, self.y = page, None, None

    def jump(self, x, y):
        self.page.mouse.move(x, y)
        self.x, self.y = x, y

    def move(self, x, y, seconds=0.8, arc=0.0):
        """Slow at both ends, along a slight arc (arc: its height as a share of the distance).
        It takes `seconds` by the clock, however long each step takes."""
        x0, y0 = self.x, self.y
        dx, dy = x - x0, y - y0
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        nx, ny = -dy / length, dx / length
        began = time.monotonic()
        while True:
            u = min(1.0, (time.monotonic() - began) / seconds)
            e = u * u * (3 - 2 * u)
            bend = arc * length * 4 * e * (1 - e) * 0.25
            self.page.mouse.move(x0 + dx * e + nx * bend, y0 + dy * e + ny * bend)
            if u >= 1.0:
                break
            self.page.wait_for_timeout(10)
        self.x, self.y = x, y

    def to(self, locator, seconds=0.8, at=(0.5, 0.5), arc=0.0):
        box = locator.bounding_box()
        self.move(box["x"] + box["width"] * at[0], box["y"] + box["height"] * at[1], seconds, arc)


def type_like_a_person(page, text, rng):
    for ch in text:
        page.keyboard.type(ch)
        page.wait_for_timeout(rng.uniform(35, 70) + (60 if ch == " " else 0))


# ---------------------------------------------------------------------- the story

def open_board(browser, world, scale=1, pointer=True):
    # An afternoon on the page's clock, whenever this runs (whole-hour zones only).
    shift = (15 - datetime.now(timezone.utc).hour) % 24
    shift = shift - 24 if shift > 12 else shift
    zone = "UTC" if shift == 0 else f"Etc/GMT{'-' if shift > 0 else '+'}{abs(shift)}"
    ctx = browser.new_context(viewport={"width": VIEW[0], "height": VIEW[1]}, device_scale_factor=scale,
                              locale="en-US", timezone_id=zone, color_scheme="light")
    if pointer:
        ctx.add_init_script(POINTER_JS)
    page = ctx.new_page()
    page.goto(world.url(f"/#board={world.board}"))
    page.wait_for_selector(".node .port.out")
    page.wait_for_selector(".wire-label")
    page.wait_for_timeout(600)
    return ctx, page


def scroll_drawer(page, ptr=None):
    """Scroll the details just far enough to show the newest message (if they don't already)."""
    room = lambda: page.evaluate("""() => {
        const body = document.querySelector('#drawer-body'), last = [...body.querySelectorAll('.chat.talk .msg')].pop();
        return Math.ceil(last.getBoundingClientRect().bottom - body.getBoundingClientRect().bottom + 24);
    }""")
    if room() <= 0:
        return
    if ptr is None:       # no pointer to show: just scroll
        page.locator("#drawer-body").evaluate("(el, d) => { el.scrollTop += d; }", room())
        return
    ptr.move(1250, 500, 0.6)
    while room() > 0:
        page.mouse.wheel(0, min(room(), 60))
        page.wait_for_timeout(30)


def wait_until_sent(world, page=None):
    for _ in range(200):
        conns = world.get(f"/api/state?board={world.board}")["board"]["connections"]
        if conns and all(c["status"] == "sent" for c in conns):
            return
        # while recording, the page's events (and so the recording) run only while we wait on the page
        page.wait_for_timeout(100) if page else time.sleep(0.1)
    raise RuntimeError("the new arrow's notes weren't sent")


def play(page, world):
    began = time.monotonic()
    mark = lambda what: say(f"  {time.monotonic() - began:5.1f} s  {what}")
    ptr, rng = Pointer(page), random.Random(11)
    node = lambda key: page.locator(f'.node[data-name="{key}"]')
    page.wait_for_timeout(1300)                               # 1. the board, a moment to take it in
    ptr.jump(900, 540)
    mark("pointer in")
    ptr.to(node("web").locator(".port.out"), 1.1)             # 2. drag the blue handle from web onto api
    page.wait_for_timeout(200)
    page.mouse.down()
    ptr.to(node("api"), 1.0, at=(0.3, 0.5), arc=0.25)
    page.wait_for_timeout(200)
    page.mouse.up()
    page.wait_for_selector("#connect-dialog[open]")
    mark("dialog open")
    ptr.move(1030, 340, 0.7)                                  # the Connect dialog: why are they talking?
    page.wait_for_timeout(200)
    type_like_a_person(page, REASON, rng)
    page.wait_for_timeout(700)
    ptr.to(page.locator("#c-submit"), 0.8)
    page.wait_for_timeout(150)
    world.write(world.you / "relay-delay", "3.0")             # the notes take a few seconds to send
    page.mouse.down()
    page.wait_for_timeout(100)
    page.mouse.up()
    page.wait_for_selector("#connect-dialog:not([open])", state="attached")
    mark("connected")
    page.wait_for_timeout(700)                                # 3. the arrow sends its notes...
    empty = (950, 250)                                        # a click on the empty board closes the details
    if page.evaluate("([x, y]) => document.elementFromPoint(x, y).closest('.node, .wire-label, .sub, .panel, #drawer, .sidebar')",
                     empty):
        raise RuntimeError("the spot to click is not empty board: move it")
    ptr.move(*empty, 0.8)
    page.mouse.down()
    page.wait_for_timeout(90)
    page.mouse.up()
    page.wait_for_selector("#drawer", state="hidden")
    wait_until_sent(world, page)
    mark("notes sent")
    for n in range(len(TALK)):                                # ...while the two chats start talking
        world.talk(n)
        page.wait_for_timeout(350)
    page.evaluate("poll()")
    page.wait_for_timeout(1400)                               # ...and it settles with its label
    label = page.locator(".wire-label", has_text=REASON)
    ptr.to(label, 0.9)                                        # 4. click the arrow: its conversation
    page.wait_for_timeout(150)
    page.mouse.down()
    page.wait_for_timeout(90)
    page.mouse.up()
    page.wait_for_selector("#drawer .chat.talk .msg.right")
    mark("conversation open")
    scroll_drawer(page, ptr)                                  # to the newest message, if it is out of sight
    ptr.move(720, 540, 0.8)                                   # and out of the way of the label
    page.wait_for_timeout(2600)                               # 5. hold the last frame
    mark("done")


def shoot_still(browser, world, path):
    ctx, page = open_board(browser, world, scale=2, pointer=False)
    page.locator(".wire-label", has_text=REASON).click()
    page.wait_for_selector("#drawer .chat.talk .msg.right")
    page.mouse.move(900, 800)
    page.wait_for_timeout(500)
    scroll_drawer(page)
    page.wait_for_timeout(400)
    page.screenshot(path=str(path))
    ctx.close()


# ------------------------------------------------------------------ conversion

def ffmpeg():
    return os.environ.get("LTT_FFMPEG") or shutil.which("ffmpeg")


def make_gif(frames, out, colors=256):
    graph = (f"scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors={colors}:stats_mode=full[p];"
             f"[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle")
    subprocess.run([ffmpeg(), "-y", "-v", "error", "-framerate", str(GIF_FPS), "-i", str(frames / "%05d.png"),
                    "-vf", graph, "-loop", "0", str(out)], check=True)


def make_mp4(frames, out):
    subprocess.run([ffmpeg(), "-y", "-v", "error", "-framerate", str(MP4_FPS), "-i", str(frames / "%05d.png"),
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=HERE, help="where the files go (default: this folder)")
    ap.add_argument("--keep", action="store_true", help="keep the scratch folder and the raw frames")
    ap.add_argument("--still", action="store_true", help="only board.png, no recording")
    ap.add_argument("--shot", action="store_true", help="debug: one screenshot of the starting board")
    args = ap.parse_args()
    if not (args.still or args.shot) and not ffmpeg():
        sys.exit("No ffmpeg: put one on the PATH or set LTT_FFMPEG=<path> (see the top of this file).")
    args.out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="ltt-demo-"))
    world = World(root)
    try:
        say("building the scratch home in", root)
        world.build()
        world.start_namespace()
        world.start_chats()
        world.start_server()
        world.set_board()
        say("server on port", world.port)
        env = World.clean_env(HOME=str(root / "browser-home"))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, env=env, args=["--password-store=basic", "--use-mock-keychain"])
            if args.shot:
                ctx, page = open_board(browser, world)
                page.screenshot(path=str(args.out / "shot.png"))
                ctx.close()
            elif args.still:
                sid = {c["key"]: c["sid"] for c in CHATS}
                world.post(f"/api/board/{world.board}/connect", {"from": sid["web"], "to": sid["api"], "reason": REASON})
                wait_until_sent(world)
                for n in range(len(TALK)):
                    world.talk(n)
                    time.sleep(0.3)
                shoot_still(browser, world, args.out / "board.png")
            else:
                ctx, page = open_board(browser, world)
                cast = Screencast(page)
                cast.start()
                page.wait_for_timeout(300)
                since = time.monotonic()
                play(page, world)
                end = time.monotonic()
                cast.stop()
                cast.report(since)
                ctx.close()
                say("recorded; the frames run", round(end - cast.frames[0][0], 1), "s")
                n = cast.save(root / "gif", GIF_FPS, end)
                say("gif frames", n, "=", round(n / GIF_FPS, 1), "s")
                make_gif(root / "gif", args.out / "demo.gif")
                cast.save(root / "mp4", MP4_FPS, end)
                make_mp4(root / "mp4", args.out / "demo.mp4")
                shoot_still(browser, world, args.out / "board.png")
            browser.close()
    finally:
        world.stop()
        if args.keep:
            say("kept", root)
        else:
            shutil.rmtree(root, ignore_errors=True)
    say("port free:", port_free(world.port))


if __name__ == "__main__":
    main()
