#!/usr/bin/env python3
"""Checks the page (static/) in a headless browser against a made-up board.

Every /api reply is faked here: no server, no sessions and no personal data are
involved, and nothing the page tries to send goes anywhere. Each check is
something that broke once (see the git log); a check that fails names it.

Run it with the venv from tests/setup.sh:  tests/.venv/bin/python tests/check_page.py
LTT_STATIC=<folder> checks another copy of static/ (e.g. an older one).
Exit 0: all passed. 1: a check failed. 2: the browser couldn't run (skipped).
"""
import copy
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC = Path(os.environ.get("LTT_STATIC") or Path(__file__).resolve().parent.parent / "static")
ORIGIN = "http://ltt.test"
FOLDER, OTHER = "/home/you/project", "/home/you/other"
A, B, C, D, E = (f"{c * 8}-{c * 4}-4{c * 3}-8{c * 3}-{c * 12}" for c in "abcde")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("page checks skipped: Playwright isn't installed (run tests/setup.sh)")
    sys.exit(2)


# ------------------------------------------------------------------ the board

def card(sid, title, x, y, **kw):
    n = {"sessionId": sid, "name": title, "title": title, "alias": None, "ambiguous": False,
         "background": False, "cwd": FOLDER, "winCwd": None, "editor": None, "entrypoint": "cli",
         "kind": "interactive", "jobId": None, "live": True, "messageBlock": None,
         "model": "claude-opus-5-5", "pid": 1, "platform": "wsl", "running": True, "startedAt": 0,
         "status": "idle", "version": "", "waitingFor": None, "agentState": None,
         "agentStateText": None, "needsAnswer": False, "x": x, "y": y}
    n.update(kw)
    return n


NOTE = {"enabled": True, "text": "hello", "state": "sent", "detail": "", "sentAt": 1}
BOARDS = [{"id": "b1", "title": "project board", "folder": FOLDER}, {"id": "b2", "title": "other", "folder": OTHER}]


def view(bid):
    """A board: alpha (idle chat), beta (background agent asking you), gamma
    (failed background agent), delta (ended chat), epsilon (near the right edge,
    where the details open), an arrow alpha → beta, and zeta waiting in the sidebar."""
    bg = dict(background=True, kind="bg", jobId="abcdef12", resumable=True)
    nodes = [
        card(A, "alpha", 340, 120),
        card(B, "beta", 640, 120, agentState="blocked", agentStateText="needs you", needsAnswer=True, status="waiting",
             waitingFor="permission to run a command", **bg),
        card(C, "gamma", 340, 320, agentState="failed", agentStateText="failed", running=False, **bg),
        card(D, "delta", 640, 320, live=False),
        card(E, "epsilon", 1150, 320),
    ] if bid == "b1" else []
    return {
        "board": {"id": bid, "title": "project board" if bid == "b1" else "other",
                  "folder": FOLDER if bid == "b1" else OTHER,
                  "connections": [{"id": "c1", "from": A, "to": B, "reason": "", "status": "sent",
                                   "createdAt": 1, "notes": {"from": NOTE, "to": NOTE}}] if bid == "b1" else [],
                  "activity": [{"t": 1, "level": "ok", "text": "Connected alpha → beta"}]},
        "nodes": nodes,
        "available": [card("f" * 8 + "-ffff-4fff-8fff-" + "f" * 12, "zeta", 0, 0, cwd=OTHER, status="waiting")],
        "boards": BOARDS, "folders": [FOLDER, OTHER], "host": "WSL", "launches": [],
    }


def not_on_board(c, title, **kw):
    """A session in Add agents (FakeAPI.avail), in the other folder."""
    return card(f"{c * 8}-{c * 4}-4{c * 3}-8{c * 3}-{c * 12}", title, 0, 0, cwd=OTHER, **kw)


# Sleeping background agents (Claude Code still lists them, no process runs), two with one name and one with no
# saved conversation; a running background agent; an editor chat.
ASLEEP_BG = dict(background=True, kind="bg", running=False, status="asleep", pid=None, resumable=True)
SLEEPY = not_on_board("1", "sleepy", jobId="0a5ee001", **ASLEEP_BG)
TWIN = not_on_board("2", "sleepy", jobId="0a5ee002", **ASLEEP_BG)
NO_REPLY = not_on_board("3", "restart me", jobId="0a5ee003", **{**ASLEEP_BG, "resumable": False})
RUNNING_BG = not_on_board("4", "busy bee", background=True, kind="bg", jobId="0a5ee004", status="busy")
EDITOR_CHAT = not_on_board("5", "cursor chat", entrypoint="claude-vscode", editor="Cursor")
avail_row = lambda s: f'#available .avail-row[data-sid="{s["sessionId"]}"]'


def agent(i, label, state, phase=None, **kw):
    a = {"id": f"a{i}", "label": label, "state": state, "model": "claude-sonnet-5-5", "phase": phase,
         "durationMs": 60000 + i * 1000, "tokens": 12000, "toolCalls": None if state == "running" else 5, "lastTool": None}
    a.update(kw)
    return a


# A chat's agents: a running workflow in two phases (one agent done, two running, one queued, one failed) and
# two subagents of its own (one running, one done).
AGENTS = {"sessionId": B, "live": True,
          "workflows": [{"runId": "r1", "name": "review-changes", "status": "running", "phases": ["Review", "Verify"],
                         "agentCount": 5, "totalTokens": 60000, "durationMs": 300000, "summary": "Review the diff",
                         "agents": [agent(1, "review:bugs", "done", "Review"), agent(2, "review:perf", "running", "Review"),
                                    agent(3, "review:security", "running", "Review"),
                                    agent(4, "verify:server.py", "queued", "Verify", durationMs=None),
                                    agent(5, "verify:app.js", "failed", "Verify")]}],
          "direct": [{"id": "d1", "description": "Fix the poll loop", "agentType": "general-purpose", "state": "running",
                      "model": "claude-opus-5-5", "durationMs": 90000, "tokens": 5000, "lastTool": None},
                     {"id": "d2", "description": "Find the old marker", "agentType": "Explore", "state": "done",
                      "model": "claude-haiku-5-5", "durationMs": 20000, "tokens": 3000, "lastTool": None}]}


def subagent(agents, aid):
    """What /api/subagent says about one of those agents."""
    flat = [(a, r) for r in agents["workflows"] for a in r["agents"]] + [(d, None) for d in agents["direct"]]
    a, run = next((x for x in flat if x[0]["id"] == aid), (None, None))
    if not a:
        return None  # the server says 404: no such agent
    now = int(time.time() * 1000)
    return {"id": aid, "label": a.get("label") or a["description"], "state": a["state"], "model": a["model"],
            "durationMs": a["durationMs"], "tokens": a["tokens"], "workflow": run and run["name"], "phase": a.get("phase"),
            "kind": a.get("agentType"), "startedAt": now - 60000,
            "steps": [{"text": "Read static/app.js", "at": now - 40000}, {"text": "Edit static/style.css", "at": now - 9000}],
            "said": {"at": now - 5000, "text": "Looking at the poll loop."}, "task": "Review the diff."}


class FakeAPI:
    def __init__(self):
        self.down = False       # every /api request fails as if the server were gone
        self.vary = False       # alpha's "now" line changes on every request
        self.hold = set()       # board ids whose replies wait in .held until the check sends them
        self.held = []
        self.post_status = 200  # what a POST gets
        self.post_result = {}
        self.new_board = "b3"   # the board /api/boards answers with (a folder that has one gets that one)
        self.posts = []
        self.asked = 0
        self.ultracode = None   # what the server reads off a running background agent
        self.suggest = None     # alpha's suggested reply
        self.arrows = []        # more arrows on the project board
        self.agents = None      # every chat's agents (like AGENTS above); none by default
        self.hold_sub = False   # an agent's details wait in .held until the check sends them
        self.sub_asked = []     # the agents whose details were asked for
        self.patch = {}         # sessionId -> fields of its card that differ
        self.launches = []      # what the server lists as under way
        self.says = None        # the text of Claude's reply in every chat (default: a short list)
        self.avail = []         # more sessions in Add agents; a deleted background agent leaves it
        self.hold_post = False  # a POST's reply waits in .held until the check sends it
        self.keep_deleted = False  # a deleted background agent is still listed (as by a poll sent before it went)

    def chat(self, sid):
        self.asked += 1
        msgs = [{"id": "u1", "role": "user", "at": 1, "text": "Fix the tests", "done": True},
                {"id": "r1", "role": "claude", "at": 2, "done": True,
                 "text": self.says or "## Done\n- **All green** now\n- ran `npm test`\n\n| a | b |\n|---|---|\n| 1 | 2 |"}]
        return {"sessionId": sid, "messages": msgs, "asking": None, "plan": None, "queued": [],
                "suggest": {"text": self.suggest} if self.suggest and sid == A else None,
                "working": self.vary and sid == A, "doing": f"Step {self.asked}" if self.vary else None,
                "ultracode": self.ultracode if sid == B else None}

    def reply(self, route, request):
        url = urlparse(request.url)
        path, q = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        files = {"/": "index.html", "/static/app.js": "app.js", "/static/style.css": "style.css"}
        if path in files or path.startswith("/static/fonts/"):
            f = STATIC / (files.get(path) or path[len("/static/"):])
            if not f.is_file():
                return route.fulfill(status=404, body="")
            kind = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}.get(f.suffix, "font/woff2")
            return route.fulfill(status=200, content_type=kind, body=f.read_bytes())
        if not path.startswith("/api/"):
            return route.fulfill(status=404, body="")
        if self.down:
            return route.abort("connectionrefused")
        if request.method != "GET":
            self.posts.append((path, request.post_data_json))
            body = {"ok": True, "result": self.post_result} if self.post_status == 200 else {"error": "It didn't work."}
            if path == "/api/boards":
                body["id"] = self.new_board
            if self.hold_post:
                return self.held.append((route, body))
            if path.endswith("/agent-delete") and self.post_status == 200 and not self.keep_deleted:
                self.avail = [s for s in self.avail if s.get("jobId") != request.post_data_json.get("jobId")]
            return route.fulfill(status=self.post_status, content_type="application/json", body=json.dumps(body))
        if path == "/api/state":
            if "board" not in q:
                data = {"boards": BOARDS, "folders": [FOLDER, OTHER], "places": [{"label": "Home", "path": "/home/you"}]}
            elif q["board"] in self.hold:
                return self.held.append((route, view(q["board"])))
            else:
                data = view(q["board"])
                data["board"]["connections"] += self.arrows if q["board"] == "b1" else []
                data["available"] += copy.deepcopy(self.avail)
                for n in data["nodes"]:
                    n.update(self.patch.get(n["sessionId"], {}))
                data["launches"] = self.launches
        elif path == "/api/chat":
            data = self.chat(q.get("session"))
        elif path == "/api/agents":
            data = self.agents or {"sessionId": q.get("session"), "live": True, "direct": [], "workflows": []}
        elif path == "/api/subagent":
            self.sub_asked.append(q.get("agent"))
            if self.agents:
                data = subagent(self.agents, q.get("agent"))
                if not data:
                    return route.fulfill(status=404, content_type="application/json", body=json.dumps({"error": "No such agent"}))
                if self.hold_sub:
                    return self.held.append((route, data))
            else:  # no made-up agents: the one fixed subagent
                data = {"id": q.get("agent"), "sessionId": q.get("session"), "label": "Fable judge", "kind": "general-purpose",
                        "workflow": None, "phase": None, "model": "claude-fable-5-1", "tokens": 1000, "state": "running",
                        "startedAt": 0, "lastAt": 0, "durationMs": 1000, "task": "Judge it", "steps": [], "said": None}
        elif path == "/api/talk":
            data = {"createdAt": 1, "total": 1, "messages": [{"id": "t1", "at": 2, "before": False, "from": A, "to": B,
                                                           "kind": "msg", "state": "read", "text": "**hi** `there`"}]}
        else:
            data = {}
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


# -------------------------------------------------------------------- helpers

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


@contextmanager
def step(page, name):
    """One check's setup and test; if it breaks (an element missing, a wait
    timing out), it fails alone and the page is put back for the next one."""
    try:
        yield
    except Exception as e:
        check(name, False, f"didn't run: {str(e).splitlines()[0]}")
    finally:
        page.api.__init__()
        page.evaluate("""() => { document.querySelectorAll('dialog[open]').forEach(d => d.close());
            document.querySelectorAll(':popover-open').forEach(p => p.hidePopover());
            document.querySelectorAll('#toasts .toast').forEach(t => t.remove());
            getSelection().removeAllRanges(); document.activeElement?.blur?.(); if (state.selected) closeDrawer(); }""")


def open_page(browser, width=1440, height=900, scheme="light", **kw):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, **kw)
    page = ctx.new_page()
    page.set_default_timeout(5000)
    page.api = FakeAPI()
    page.errors, page.dialogs, page.asked = [], [], []  # dialogs: the browser's own popups (the page uses none)
    page.route("**/*", page.api.reply)
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("dialog", lambda d: (page.dialogs.append(d.type), d.accept()))
    page.goto(ORIGIN + "/")
    page.wait_for_function("document.querySelectorAll('.node').length === 5")
    return page


def poll(page, times=1):
    for _ in range(times):
        page.evaluate("poll()")  # the page's own refresh, awaited
    page.wait_for_timeout(100)


def open_card(page, sid):
    page.wait_for_timeout(600)  # two clicks on a card close together rename it
    page.locator(f'.node[data-id="{sid}"] .name').click()
    page.wait_for_function("!document.querySelector('#drawer').hidden")
    poll(page)


def answer(page, yes=True):
    """The question the page is asking (its glass dialog `#ask`): what it says, then the button pressed."""
    page.wait_for_selector("#ask[open]")
    said = page.evaluate("""() => ({ title: document.querySelector('#ask-title').textContent,
        text: document.querySelector('#ask-text').textContent, ok: document.querySelector('#ask-yes').textContent,
        danger: document.querySelector('#ask-yes').classList.contains('danger'),
        focus: document.activeElement.id })""")
    page.click("#ask-yes" if yes else "#ask-no")
    page.wait_for_selector("#ask[open]", state="detached")
    page.asked.append(said)
    return said


def asking(page):
    """Whether the glass question is on screen."""
    return page.locator("#ask[open]").count() == 1


def open_agents(page, sid=B, agents=None):
    """A chat's details with the made-up agents (AGENTS, or the ones given), then the pop-up that lists them."""
    page.api.agents = copy.deepcopy(agents or AGENTS)
    open_card(page, sid)
    page.evaluate(f"loadDetails('{sid}')")  # the agents of this card, not those of the check before
    page.locator("#drawer-body .agents-line").click()
    page.wait_for_selector("#agents-pop[open] .agent-row")


def picked_agent(page):
    """The name of the agent picked in the pop-up's list."""
    return page.locator("#agents-pop .agent-row[aria-current] .agent-label").inner_text()


PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def paste(page, sel, kind, how="paste"):
    """A file pasted (Ctrl+V) into, or dragged over (how="dragover") or dropped
    on (how="drop"), what sel finds: a 1-pixel PNG, or text. True if the page
    took it (the browser's own handling was prevented)."""
    return page.evaluate("""([sel, b64, kind, how]) => {
        const bytes = kind.startsWith('image/') ? Uint8Array.from(atob(b64), c => c.charCodeAt(0)) : ['notes'];
        const dt = new DataTransfer(); dt.items.add(new File([bytes], 'file', { type: kind }));
        const init = { bubbles: true, cancelable: true };
        return !document.querySelector(sel).dispatchEvent(how === 'paste'
            ? new ClipboardEvent('paste', { ...init, clipboardData: dt }) : new DragEvent(how, { ...init, dataTransfer: dt })); }""",
        [sel, PNG_1PX, kind, how])


def is_open(page, sel):
    return page.evaluate(f"(e => !!e && !e.hidden && !!e.offsetHeight)(document.querySelector('{sel}'))")


def tip(page):
    """The glass tooltip (#tip): whether it shows, its words and where it is."""
    return page.evaluate("""() => { const t = document.querySelector('#tip'), r = t.getBoundingClientRect();
        return { open: t.matches(':popover-open'), text: t.textContent, left: r.left, top: r.top, right: r.right, bottom: r.bottom }; }""")


def park(page):
    """The pointer on a bare spot of the board, long enough for a label that was open to be well closed (a
    neighbour's shows at once for 300 ms after one closes)."""
    page.mouse.move(700, 700)
    page.wait_for_timeout(350)


def hover_tip(page, sel, waits=1500):
    """The pointer rests on what sel finds, from a bare spot of the board, until the tooltip shows."""
    park(page)
    page.hover(sel)
    page.wait_for_selector("#tip:popover-open", timeout=waits)
    return tip(page)


def title_of(page, sel):
    return page.evaluate("(s => document.querySelector(s).getAttribute('title'))", sel)


def fades_done(page, *sels):
    """Waits until the fades (CSS transitions) on what each selector finds are over: its own animations, not the
    page's (some pulse for good). A fixed wait can end mid-fade on a slow machine."""
    page.wait_for_function("ss => ss.every(s => document.querySelector(s).getAnimations().length === 0)", arg=list(sels))


def stray_share(page, box, colour="255, 0, 0"):
    """What share of the pixels in the box (a screenshot of it) is not the one solid colour it is painted in."""
    import base64
    png = base64.b64encode(page.screenshot(clip=box)).decode()
    return page.evaluate("""async ([b64, colour]) => {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        const img = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
        const c = new OffscreenCanvas(img.width, img.height), g = c.getContext('2d');
        g.drawImage(img, 0, 0);
        const d = g.getImageData(0, 0, img.width, img.height).data, want = colour.split(',').map(Number);
        let other = 0;
        for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - want[0]) + Math.abs(d[i + 1] - want[1]) + Math.abs(d[i + 2] - want[2]) > 12) other++;
        return other / (d.length / 4); }""", [png, colour])


# Text against the first background behind it, with any fading (opacity) on the
# way up mixed in, as the eye sees it.
CONTRAST = """(sel) => {
  const rgb = (c) => c.match(/[\\d.]+/g).slice(0, 3).map(Number);
  const lum = ([r, g, b]) => [r, g, b].map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; })
    .reduce((s, v, i) => s + v * [.2126, .7152, .0722][i], 0);
  const e = document.querySelector(sel); let p = e, bg, fade = 1;
  for (let q = e; q; q = q.parentElement) fade *= +getComputedStyle(q).opacity;
  while (p && /rgba\\(.*, 0\\)|transparent/.test(bg = getComputedStyle(p).backgroundColor)) p = p.parentElement;
  const back = rgb(p ? bg : 'rgb(255, 255, 255)'), text = rgb(getComputedStyle(e).color).map((v, i) => v * fade + back[i] * (1 - fade));
  const a = lum(text), b = lum(back);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}"""


# --------------------------------------------------------------------- checks

def checks_wide(browser):
    page = open_page(browser)

    name = "details: unchanged polls don't rebuild them"
    with step(page, name):
        open_card(page, A)
        page.evaluate("""() => { window.__swaps = 0; new MutationObserver(m => window.__swaps += m.length)
            .observe(document.querySelector('#drawer-body'), { childList: true }); }""")
        poll(page, 3)
        check(name, page.evaluate("window.__swaps") == 0)

    name = "details: a rebuild keeps keyboard focus on the same button"
    with step(page, name):
        open_card(page, A)
        page.locator("#drawer-body button:not([id])").first.focus()
        label = page.evaluate("document.activeElement.textContent")
        page.api.vary = True
        poll(page, 2)
        check(name, page.evaluate("document.activeElement.textContent") == label)

    name = "details: text selected with the mouse survives polls"
    with step(page, name):
        open_card(page, A)
        page.api.vary = True
        page.evaluate("""() => { const r = document.createRange();
            r.selectNodeContents(document.querySelector('#drawer-body .msg.claude .bubble'));
            getSelection().removeAllRanges(); getSelection().addRange(r); }""")
        picked = page.evaluate("getSelection().toString()")
        poll(page, 2)
        check(name, picked and page.evaluate("getSelection().toString()") == picked)

    name = "bubbles: Markdown shows as bold, code and bullets, not as ** or |---|"
    with step(page, name):
        open_card(page, A)
        bubble = page.locator("#drawer-body .msg.claude .bubble").first
        text = bubble.inner_text()
        check(name, bubble.locator("strong").count() >= 2 and bubble.locator("code").count() == 1
              and "**" not in text and "|---|" not in text and "• " in text)

    name = "bubbles: **bold** around `code` shows as bold, with no ** left over"
    with step(page, name):
        page.api.says = "1. **The `/effort` line:** a check\n2. **Cursor:** use `**` for bold and [a link](https://x.test)"
        open_card(page, A)
        page.wait_for_function("document.querySelector('#drawer-body .msg.claude .bubble').textContent.includes('Cursor')")
        bubble = page.locator("#drawer-body .msg.claude .bubble").first
        bold, words = bubble.locator("strong").all_inner_texts(), bubble.inner_text()
        check(name, bold == ["The /effort line:", "Cursor:"] and bubble.locator("strong code").count() == 1
              and bubble.locator("code").all_inner_texts() == ["/effort", "**"] and "a link" in words
              and "https" not in words and words.count("**") == 1, (bold, words))

    name = "details: they open at their top, a long name in full, however the last ones were scrolled"
    with step(page, name):
        page.set_viewport_size({"width": 1440, "height": 600})  # short enough that every chat's details scroll
        long_name = "you are a master of the handoff 2"
        page.api.patch = {B: {"title": long_name, "name": long_name}}
        poll(page)
        top = """() => { const b = document.querySelector('#drawer-body'), h = document.querySelector('#drawer-body h3');
            return { scrolled: b.scrollTop, room: b.scrollHeight - b.clientHeight, title: h.textContent,
                     above: h.getBoundingClientRect().top - b.getBoundingClientRect().top,
                     lines: Math.round(h.getBoundingClientRect().height / parseFloat(getComputedStyle(h).lineHeight)) }; }"""
        scroll = "document.querySelector('#drawer-body').scrollTop = 30"
        try:
            open_card(page, B)  # both chats are known now, so their details draw whole at once
            open_card(page, A)
            page.evaluate(scroll)
            open_card(page, B)  # another chat's details, scrolled down
            other = page.evaluate(top)
            page.evaluate(scroll)
            page.evaluate("closeDrawer()")
            open_card(page, B)  # its own, closed while scrolled down
            again = page.evaluate(top)
        finally:
            page.api.patch = {}
            poll(page)
            page.set_viewport_size({"width": 1440, "height": 900})
        check(name, all(r["scrolled"] == 0 and r["room"] > 30 and r["above"] >= 0 and r["lines"] == 2 and r["title"] == long_name
                        for r in (other, again)), (other, again))

    name = "details: what scrolls up under the top edge fades out there, not cut off flat"
    with step(page, name):
        open_card(page, A)
        check(name, "linear-gradient" in page.evaluate("getComputedStyle(document.querySelector('#drawer-body')).maskImage"))

    name = "dots: needs you / waiting and failed each differ from ended"
    with step(page, name):
        dot = lambda sel: page.evaluate(f"getComputedStyle(document.querySelector('{sel}')).backgroundColor")
        needs, failed, ended = (dot(f'.node[data-id="{s}"] .dot') for s in (B, C, D))
        check(name, len({needs, failed, ended}) == 3 and dot("#available .dot.waiting") == needs)

    name = "details: status in the card's words"
    with step(page, name):
        open_card(page, B)
        check(name, page.inner_text("#drawer-body details.info summary").startswith("needs you"))

    name = "details: an agent asking you shows that first"
    with step(page, name):
        open_card(page, B)
        check(name, page.eval_on_selector_all("#drawer-body h2", "hs => hs.map(h => h.textContent)")[:1] == ["Background agent"])

    # An agent Claude Code lists as blocked that only ended its turn (nothing asked, nothing open in its
    # process): the server words it "finished" and sends needsAnswer false. Beta, as such an agent.
    FINISHED = {B: {"status": "idle", "agentState": "blocked", "agentStateText": "finished", "needsAnswer": False,
                    "waitingFor": None}}
    bg_section = """() => {
        const d = document.querySelector('#drawer-body');
        const buttons = [...d.querySelectorAll('button')];
        const one = (t) => buttons.find((b) => b.textContent === t);
        return { first: d.querySelector('h2').textContent,
                 warn: [...d.querySelectorAll('p.warn-text')].map((p) => p.textContent),
                 primary: one('Open in terminal')?.classList.contains('primary'),
                 screen: buttons.map((b) => b.textContent).filter((t) => /screen|asking/.test(t)),
                 compact: one('Compact') ? !one('Compact').disabled : null,
                 hint: d.querySelector('.composer-hint')?.textContent || '',
                 composer: d.querySelector('.composer')?.classList.contains('asking') };
    }"""
    dot_look = lambda sid: page.evaluate(
        f"""() => {{ const s = getComputedStyle(document.querySelector('.node[data-id="{sid}"] .dot'));
                    return [s.backgroundColor, s.boxShadow]; }}""")

    name = ("background agent: one that needs an answer says needs you with the attention dot; its details warn, "
            "point to its terminal and its Compact waits")
    with step(page, name):
        open_card(page, B)
        got = page.evaluate(bg_section)
        badge = page.locator(f'.node[data-id="{B}"] .badge.state')
        ring = dot_look(B)[1]
        check(name, badge.inner_text() == "needs you" and "warn" in badge.get_attribute("class") and ring != "none"
              and got["first"] == "Background agent"
              and got["warn"] == ["It's waiting for you (permission to run a command). Open it in a terminal to answer."]
              and got["primary"] is True and got["screen"] == ["What is it asking?"] and got["compact"] is False
              and got["composer"] is True and "asking you something" in got["hint"], (badge.inner_text(), ring, got))

    name = ("background agent: one that finished its answer says finished with the calm idle dot, no warning, "
            "nothing emphasised, Compact open and the Send box as for an idle one")
    with step(page, name):
        page.api.patch = FINISHED
        poll(page)
        open_card(page, B)
        got = page.evaluate(bg_section)
        badge = page.locator(f'.node[data-id="{B}"] .badge.state')
        check(name, badge.inner_text() == "finished" and badge.get_attribute("class").split() == ["badge", "state"]
              and dot_look(B) == dot_look(A) and dot_look(B)[1] == "none"  # alpha is an idle chat: the same dot
              and page.inner_text("#drawer-body details.info summary").startswith("finished")
              and got["first"] == "Recent messages" and got["warn"] == [] and got["primary"] is False
              and got["screen"] == ["Show its screen"] and got["compact"] is True
              and got["composer"] is False and "asking you something" not in got["hint"],
              (badge.inner_text(), dot_look(B), dot_look(A), got))

    name = "background agent: one that finished its answer can be compacted, running or asleep"
    with step(page, name):
        page.api.patch = FINISHED
        poll(page)
        open_card(page, B)
        page.locator("#drawer-body button", has_text="Compact").click()
        said = answer(page)
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/compact")]
        page.api.patch = {B: {**FINISHED[B], "running": False, "status": "asleep"}}
        poll(page)
        asleep = page.evaluate(bg_section)
        check(name, said["ok"] == "Compact" and sent == [{"sessionId": B}] and asleep["compact"] is True
              and asleep["warn"] == []
              and page.locator(f'.node[data-id="{B}"] .badge.state').inner_text() == "finished", (said, sent, asleep))

    name = "details: Delete agent is apart from Open in terminal, below it"
    with step(page, name):
        open_card(page, B)
        rows = page.eval_on_selector_all("#drawer-body .drawer-actions",
                                         "rs => rs.map(r => [...r.querySelectorAll('button')].map(b => b.textContent))")
        flat = [b for r in rows for b in r]
        check(name, "Delete agent" in flat and not any("Delete agent" in r and "Open in terminal" in r for r in rows)
              and flat.index("Delete agent") > flat.index("Open in terminal"))

    name = "details: End agent on a running background agent only, and it asks for agent-end"
    with step(page, name):
        open_card(page, C)  # gamma: its process ended
        ended = page.locator("#drawer-body button", has_text="End agent").count()
        open_card(page, B)  # beta: running
        page.locator("#drawer-body button", has_text="End agent").click()
        said = answer(page)
        page.wait_for_timeout(200)
        sent = [b for p, b in page.api.posts if p.endswith("/agent-end")]
        check(name, ended == 0 and said["ok"] == "End agent" and sent == [{"jobId": "abcdef12"}], said)

    name = "details: Open in IDE ends a running background agent only after a yes, an asleep one isn't asked"
    with step(page, name):
        open_card(page, C)  # gamma: its process ended
        page.locator("#drawer-body button", has_text="Open in IDE").click()
        page.wait_for_timeout(200)
        quiet = not asking(page)
        open_card(page, B)  # beta: running
        page.locator("#drawer-body button", has_text="Open in IDE").click()
        said = answer(page)
        page.wait_for_timeout(200)
        sent = [(b["sessionId"], b["end"]) for p, b in page.api.posts if p.endswith("/open-folder")]
        check(name, quiet and said["title"].startswith("Go on with beta in ") and said["ok"].startswith("Open in ")
              and not said["danger"] and sent == [(C, False), (B, True)], (said, sent))

    name = "details: Open in IDE leaves no notice once the editor was asked; a failure still gets one"
    with step(page, name):
        page.api.post_result = {"ended": "abcdef12"}
        open_card(page, B)
        page.locator("#drawer-body button", has_text="Open in IDE").click()
        answer(page)
        page.wait_for_timeout(300)
        quiet = page.locator("#toasts .toast").all_inner_texts()
        page.api.post_status = 400  # the server says why
        page.locator("#drawer-body button", has_text="Open in IDE").click()
        answer(page)
        page.wait_for_timeout(300)
        check(name, not quiet and page.locator("#toasts .toast.error").count() == 1, (quiet, page.inner_text("#toasts")))

    name = "details: an editor chat has Open in terminal beside Open in IDE, and asks first only while it is open in the IDE; no notice once it opened"
    with step(page, name):
        open_card(page, A)  # alpha: a chat in a terminal
        terminal = page.locator("#drawer-body button", has_text="Open in terminal").count()
        ide = {"editor": "Cursor", "entrypoint": "claude-vscode"}
        page.api.patch = {A: ide, D: ide}  # alpha: open in Cursor; delta: a chat from Cursor that has ended
        page.api.post_result = {"closed": True, "opened": True, "editor": "Cursor", "command": f"claude --resume {A}"}
        poll(page)
        open_card(page, A)
        beside = page.locator("#drawer-body .drawer-actions", has_text="Open in IDE").locator("button").all_inner_texts()
        page.locator("#drawer-body button", has_text="Open in terminal").click()
        said = answer(page)
        page.wait_for_timeout(300)
        says = "closes in Cursor first" in said["text"] and "running agent" not in said["text"]  # it runs none
        toast = page.inner_text("#toasts")
        open_card(page, D)
        page.locator("#drawer-body button", has_text="Open in terminal").click()
        page.wait_for_timeout(300)
        quiet = not asking(page)
        sent = [b for p, b in page.api.posts if p.endswith("/open-terminal")]
        page.api.patch = {A: {**ide, "platform": "windows"}}
        poll(page)
        open_card(page, A)
        windows = page.locator("#drawer-body button", has_text="Open in terminal").count()
        check(name, beside == ["Open in IDE", "Open in terminal"] and says and quiet and terminal == windows == 0
              and sent == [{"sessionId": A, "end": True}, {"sessionId": D, "end": False}]
              and not toast.strip(), (beside, says, quiet, sent, terminal, windows, toast))

    name = "details: Open in terminal says when it failed, or what to run when no terminal could open"
    with step(page, name):
        page.api.patch = {D: {"editor": "Cursor", "entrypoint": "claude-vscode"}}
        poll(page)
        open_card(page, D)
        page.api.post_status = 400  # the server says why
        page.locator("#drawer-body button", has_text="Open in terminal").click()
        page.wait_for_timeout(300)
        failed = page.inner_text("#toasts")
        page.api.post_status, page.api.post_result = 200, {"opened": False, "command": f"claude --resume {D}"}
        page.evaluate("document.querySelectorAll('#toasts .toast').forEach((t) => t.remove())")
        page.locator("#drawer-body button", has_text="Open in terminal").click()
        page.wait_for_timeout(300)
        command = page.inner_text("#toasts")
        check(name, "It didn't work." in failed and f"Run this in a terminal: claude --resume {D}" in command,
              (failed, command))

    name = "details: Open in terminal's confirm says how many running agents stop with the chat, and nothing when none run"
    with step(page, name):
        page.api.patch = {A: {"editor": "Cursor", "entrypoint": "claude-vscode"}}  # alpha, open in Cursor
        page.api.post_result = {"closed": True, "opened": True, "editor": "Cursor", "command": f"claude --resume {A}"}
        texts = []
        for agents in (AGENTS,  # two workflow agents and a subagent run, a queued one and a failed one don't
                       {"sessionId": A, "live": True, "workflows": [], "direct": AGENTS["direct"][:1]},
                       {"sessionId": A, "live": True, "workflows": [], "direct": AGENTS["direct"][1:]}):  # the one that's done
            page.api.agents = copy.deepcopy(agents)
            poll(page)
            open_card(page, A)
            page.evaluate(f"loadDetails('{A}')")
            page.locator("#drawer-body button", has_text="Open in terminal").click()
            texts.append(answer(page)["text"])
            page.wait_for_timeout(300)
            page.evaluate("closeDrawer()")
        check(name, "Its 3 running agents stop too. Then it opens in a terminal window." in texts[0]
              and "Its 1 running agent stops too." in texts[1] and "running agent" not in texts[2], texts)

    foot_ide = '#drawer-body .drawer-foot button:text-is("Open in IDE")'  # a chat in a terminal's own, beside End this chat

    name = "details: a running chat in a terminal has Open in IDE beside End this chat; no other kind of card does"
    with step(page, name):
        cases = ((A, {}, 1, "a chat in a terminal"),
                 (B, {}, 0, "a background agent"),
                 (A, {"editor": "Cursor", "entrypoint": "claude-vscode"}, 0, "an editor chat"),
                 (A, {"platform": "windows"}, 0, "a chat on Windows"),
                 (D, {}, 0, "an ended chat"),
                 (A, {"movedTo": B}, 0, "one sent to the background"),
                 (A, {"hasTranscript": False}, 0, "one with no saved conversation"),
                 (A, {"pid": None}, 0, "one with no process"),
                 (A, {"hasTranscript": True}, 1, "one whose conversation is saved"))
        found = {}
        for sid, patch, _, why in cases:
            page.api.patch = {sid: patch}
            poll(page)
            open_card(page, sid)
            found[why] = page.locator(foot_ide).count()
            if why == "a chat in a terminal":
                look = page.locator("#drawer-body .drawer-foot .drawer-actions", has_text="End this chat").locator(
                    "button").evaluate_all("bs => bs.map(b => [b.textContent, b.className])")
            if why == "an ended chat":
                continued = page.locator("#drawer-body button", has_text="Continue in IDE").count()
            page.evaluate("closeDrawer()")
        check(name, all(found[why] == want for _, _, want, why in cases) and continued == 1
              and look == [["Open in IDE", "btn primary"], ["End this chat", "btn danger"]], (found, continued, look))

    name = "details: Open in IDE on a chat in a terminal says what closes (the busy sentence and the agents one only when they apply)"
    with step(page, name):
        page.evaluate("store('ltt.editor', 'Cursor')")
        one = {"sessionId": A, "live": True, "workflows": [], "direct": AGENTS["direct"][:1]}
        texts = []
        try:
            for status, agents in (("busy", AGENTS), ("idle", one), ("idle", {**one, "direct": []})):
                page.api.patch = {A: {"status": status}}
                page.api.agents = copy.deepcopy(agents)
                poll(page)
                open_card(page, A)
                page.evaluate(f"loadDetails('{A}')")
                page.locator(foot_ide).click()
                texts.append(answer(page, yes=False))
                page.evaluate("closeDrawer()")
        finally:
            page.evaluate("localStorage.removeItem('ltt.editor')")
        t = [x["text"] for x in texts]
        check(name, texts[0]["title"] == "Go on with alpha in Cursor?" and texts[0]["ok"] == "Open in Cursor"
              and not texts[0]["danger"]
              and "Only one place can run a conversation, so it ends in its terminal first: Claude Code in it exits "
              "and the window stays open." in t[0]
              and "It stops what it is doing. Its 3 running agents stop too. Then it opens in Cursor, where you go on "
              "with it." in t[0]
              and "stops what it is doing" not in t[1] and "Its 1 running agent stops too." in t[1]
              and "stops what it is doing" not in t[2] and "running agent" not in t[2]
              and t[2].endswith("Then it opens in Cursor, where you go on with it."), t)

    name = "details: Open in IDE on a chat in a terminal posts endChat only after a yes, says Opening… meanwhile, and leaves no notice"
    with step(page, name):
        page.evaluate("store('ltt.editor', 'Cursor')")
        held = []
        try:
            open_card(page, A)
            page.locator(foot_ide).click()
            answer(page, yes=False)
            page.wait_for_timeout(300)
            after_no = [b for p, b in page.api.posts if p.endswith("/open-folder")]
            page.route("**/open-folder", lambda route, request: held.append(route))  # the server is slow to answer
            page.locator(foot_ide).click()
            answer(page)
            page.wait_for_function("[...document.querySelectorAll('#drawer-body .drawer-foot button')]"
                                   ".some(b => b.textContent === 'Opening…' && b.disabled)")
            page.wait_for_timeout(300)  # the request goes out, and waits
            page.api.post_result = {"ended": True}
            held[0].fallback()
            page.wait_for_function("[...document.querySelectorAll('#drawer-body .drawer-foot button')]"
                                   ".filter(b => b.textContent === 'Open in IDE').length === 1")
            page.wait_for_timeout(300)
            said = page.locator("#toasts .toast").all_inner_texts()  # none: the card shows what happened
            sent = [b for p, b in page.api.posts if p.endswith("/open-folder")]
        finally:
            page.unroute("**/open-folder")
            page.evaluate("localStorage.removeItem('ltt.editor')")
        check(name, after_no == [] and sent == [{"sessionId": A, "editor": "Cursor", "continue": True, "endChat": True}]
              and not said, (after_no, sent, said))

    name = "details: Open in IDE on a chat in a terminal says why it failed, and the button is there again"
    with step(page, name):
        open_card(page, A)
        page.api.post_status = 400
        page.locator(foot_ide).click()
        answer(page)
        page.wait_for_function("document.querySelector('#toasts')?.textContent.includes('It didn')")
        page.wait_for_function("[...document.querySelectorAll('#drawer-body .drawer-foot button')]"
                               ".filter(b => b.textContent === 'Open in IDE').length === 1")
        said = page.inner_text("#toasts")
        check(name, "It didn't work." in said and page.locator("#toasts .toast.error").count() == 1, said)

    name = "send box: a pasted screenshot shows as a thumbnail and goes with the text"
    with step(page, name):
        open_card(page, B)
        page.evaluate("state.images = {}")
        paste(page, "#send-box", "image/png")
        page.wait_for_selector("#drawer-body .composer .thumb img")
        page.locator("#send-box").fill("what is wrong here?")
        page.locator("#drawer-body .composer-send").click()
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/send")]
        check(name, sent == [{"sessionId": B, "text": "what is wrong here?", "images": [{"data": PNG_1PX}]}]
              and page.locator("#drawer-body .composer .thumb").count() == 0
              and "[Image #1]" in page.inner_text("#drawer-body .msg.pending .bubble"), str(sent)[:200])

    name = "send box: no \"Sent the …\" notice after a send; its bubble shows it"
    with step(page, name):
        page.evaluate("document.querySelectorAll('#toasts .toast').forEach((t) => t.remove())")
        for result in ({"how": "message"}, {"how": "prompt", "copy": None}):
            page.api.post_result = result
            open_card(page, B)
            page.locator("#send-box").fill("hello")
            page.locator("#drawer-body .composer-send").click()
            page.wait_for_timeout(300)
        notes = page.locator("#toasts .toast").all_inner_texts()
        page.api.post_result = {}
        check(name, not any("Sent the" in t for t in notes), notes)

    name = "subagent: a message goes through its chat; its terminal opens for a background agent's subagent"
    with step(page, name):
        page.api.post_result = {"opened": True, "command": "claude attach abcdef12"}
        page.evaluate(f"openSub('{B}', 'a1b2c3', 'Fable judge')")  # beta: a background agent
        page.wait_for_selector("#drawer-body #sub-box")
        page.locator("#drawer-body #sub-box").fill("stop and report")
        page.locator("#drawer-body #sub-box").press("Enter")
        page.wait_for_timeout(300)
        page.get_by_role("button", name="Open in terminal").click()
        page.wait_for_timeout(300)
        msg = [b for p, b in page.api.posts if p.endswith("/send-subagent")]
        att = [b for p, b in page.api.posts if p.endswith("/agent-attach")]
        page.evaluate(f"openSub('{A}', 'a1b2c3', 'Fable judge')")  # alpha: a chat in a terminal
        page.wait_for_selector("#drawer-body #sub-box")
        term = page.inner_text("#drawer-body")
        page.evaluate(f"openSub('{D}', 'a1b2c3', 'Fable judge')")  # delta: ended
        page.wait_for_selector("#drawer-body h3")
        page.wait_for_timeout(200)
        ended = page.locator("#drawer-body #sub-box").count() == 0
        page.api.post_result = {}
        check(name, msg == [{"sessionId": B, "agentId": "a1b2c3", "label": "Fable judge", "text": "stop and report",
                             "images": []}]
              and att and att[-1].get("jobId") == "abcdef12" and "Open in terminal" not in term
              and "terminal window" in term and ended, (msg, att, ended))
        page.evaluate("state.outbox = {}")

    name = "subagent: its message box is a chat's (the round send inside); a click sends, images pasted or dropped go too"
    with step(page, name):
        page.evaluate("state.images = {}")
        page.evaluate(f"openSub('{B}', 'a1b2c3', 'Fable judge')")
        page.wait_for_selector("#drawer-body .composer #sub-box")
        same = page.locator("#drawer-body .composer .composer-send").count() == 1
        paste(page, "#drawer-body #sub-box", "image/png")
        dropped = (paste(page, "#drawer-body h3", "image/png", "dragover")
                   and paste(page, "#drawer-body h3", "image/png", "drop"))
        page.wait_for_selector("#drawer-body .composer .thumb img")
        page.wait_for_timeout(200)
        thumbs = page.locator("#drawer-body .composer .thumb").count()
        page.locator("#drawer-body #sub-box").fill("look at this")
        page.locator("#drawer-body .composer-send").click()
        page.wait_for_timeout(300)
        msg = [b for p, b in page.api.posts if p.endswith("/send-subagent")]
        cleared = page.locator("#drawer-body .composer .thumb").count() == 0
        check(name, same and dropped and thumbs == 2 and msg and msg[-1]["text"] == "look at this"
              and msg[-1]["images"] == [{"data": PNG_1PX}] * 2 and cleared,
              (same, dropped, thumbs, msg[-1:] and msg[-1]["text"], cleared))

    name = "send box: × takes an image out, a dropped non-image is refused, images alone can go"
    with step(page, name):
        open_card(page, B)
        page.evaluate("state.images = {}")
        paste(page, "#send-box", "image/png")
        paste(page, "#send-box", "image/png")
        page.wait_for_function("document.querySelectorAll('#drawer-body .thumb').length === 2")
        page.locator("#drawer-body .thumb-x").first.click()
        page.wait_for_timeout(100)
        one = page.locator("#drawer-body .thumb").count() == 1
        paste(page, "#drawer-body .composer", "text/plain", "drop")
        page.wait_for_timeout(100)
        refused = page.locator("#toasts .toast.error").count() == 1 and page.locator("#drawer-body .thumb").count() == 1
        page.locator("#send-box").press("Enter")
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/send")]
        check(name, one and refused and len(sent) == 1 and sent[0]["text"] == "" and len(sent[0]["images"]) == 1)
        page.evaluate("state.outbox = {}")

    name = "send box: no +; an image dropped anywhere on the details lands in the box, with a cue while dragged"
    with step(page, name):
        open_card(page, B)
        page.evaluate("state.images = {}")
        plain = (page.locator("#drawer-body .composer button").count() == 1
                 and page.locator("#drawer-body input[type=file]").count() == 0)
        dropping = "document.querySelector('#drawer').classList.contains('dropping')"
        taken = paste(page, "#drawer-body h3", "image/png", "dragover")
        cue = page.evaluate(dropping)
        paste(page, "#drawer-body h3", "image/png", "drop")
        page.wait_for_selector("#drawer-body .composer .thumb img")
        check(name, plain and taken and cue and not page.evaluate(dropping)
              and page.locator("#drawer-body .thumb").count() == 1, f"{plain} {taken} {cue}")
        page.evaluate("state.images = {}")

    name = "page: a file dropped off the details doesn't open in place of the app; other drags are left alone"
    with step(page, name):
        board = paste(page, "#canvas", "image/png", "dragover") and paste(page, "#canvas", "image/png", "drop")
        page.locator(".wire-label").first.click()  # an arrow's details: no Send box
        page.wait_for_function("!document.querySelector('#drawer').hidden")
        wire = (paste(page, "#drawer-body", "image/png", "dragover") and paste(page, "#drawer-body", "image/png", "drop")
                and not page.evaluate("document.querySelector('#drawer').classList.contains('dropping')"))
        text = page.evaluate("""() => { const dt = new DataTransfer(); dt.setData('text/plain', 'hi');
            return document.querySelector('#canvas').dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt })); }""")
        check(name, board and wire and text and not page.evaluate("Object.values(state.images).flat().length"),
              f"{board} {wire} {text}")

    name = "send box: a suggested reply says Tab or → takes it, and → does"
    with step(page, name):
        page.api.suggest = "Run the tests"
        open_card(page, A)
        hint = page.get_attribute("#send-box", "placeholder")
        page.locator("#send-box").press("ArrowRight")
        check(name, hint == "Run the tests  (Tab or →)" and page.input_value("#send-box") == "Run the tests", hint)
        page.evaluate("state.drafts = {}")

    name = "ultracode: a running agent shows its state with the one button that changes it, and asks the server; no notice once switched"
    with step(page, name):
        page.api.ultracode = False
        page.api.post_result = {"ultracode": True, "said": "Ultracode on (this session only): dynamic workflows on every task."}
        open_card(page, B)
        row = page.locator("#drawer-body .ultracode")
        shown = row.inner_text()
        row.get_by_role("button", name="Turn on").click()
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/ultracode")]
        check(name, "Ultracode is off" in shown and "Turn off" not in shown and sent == [{"sessionId": B, "on": True}]
              and page.locator("#toasts .toast").count() == 0, (shown, sent, page.inner_text("#toasts")))

    name = "ultracode: unknown says so, with both buttons and a note on when it shows, and the page sends nothing to find out; a stopped agent has none"
    with step(page, name):
        open_card(page, B)
        poll(page, 2)  # its details stay open while the page refreshes
        row = page.locator("#drawer-body .ultracode")
        shown, both, enabled = row.inner_text(), row.locator("button").all_inner_texts(), row.locator("button:enabled").count()
        note = "once you turn it on or off here, or after its next prompt" in page.inner_text("#drawer-body")
        sent = list(page.api.posts)
        open_card(page, C)
        check(name, shown.startswith("Ultracode: unknown") and both == ["Turn on", "Turn off"] and enabled == 2 and note
              and not sent and page.locator("#drawer-body .ultracode").count() == 0
              and "while it runs" in page.inner_text("#drawer-body"), (shown, both, enabled, note, sent))

    name = "compact: an idle background agent has Compact; it asks first, then asks the server"
    with step(page, name):
        page.api.patch = {B: {"status": "idle", "agentState": "idle", "needsAnswer": False, "waitingFor": None}}
        poll(page)
        open_card(page, B)
        page.locator("#drawer-body button", has_text="Compact").click()
        said = answer(page)
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/compact")]
        check(name, said["ok"] == "Compact" and sent == [{"sessionId": B}], (said, sent))

    name = "compact: while it compacts the button waits, saying so; no notice when it's done (Activity says it)"
    with step(page, name):
        page.api.patch = {B: {"status": "idle", "agentState": "idle", "needsAnswer": False, "waitingFor": None}}
        page.api.launches = [{"id": "k1", "board": "b1", "at": 1, "kind": "compact", "from": B, "state": "compacting",
                              "detail": "Compacting \"beta\" (/compact)…"}]
        poll(page)
        open_card(page, B)
        button = page.locator("#drawer-body button", has_text="Compact")
        during = (button.inner_text(), button.is_disabled())
        page.api.launches = [{**page.api.launches[0], "state": "done", "at": 2,
                              "detail": "Compacted \"beta\": its context went from 39k to 3k tokens."}]
        poll(page)
        check(name, during == ("Compacting…", True) and (button.inner_text(), button.is_disabled()) == ("Compact", False)
              and page.locator("#toasts .toast").count() == 0, (during, page.inner_text("#toasts")))

    name = "notices: a launch shows one only when it failed or came up other than asked, not its steps or a plain success"
    with step(page, name):
        def launch(i, **kw):
            return {"id": f"n{i}", "board": "b1", "at": 1, "kind": "editor", "prompt": "hi", **kw}
        page.api.launches = [launch(1, state="waiting", detail="Opening the folder in Cursor…"),
                             launch(2, state="done", detail="The new chat got your prompt."),
                             launch(3, state="done", warn=True, detail="The new chat got your prompt. Its model couldn't be set."),
                             launch(4, state="failed", detail="No new chat appeared.")]
        poll(page)
        shown = page.locator("#toasts .toast").all_inner_texts()
        check(name, len(shown) == 2 and "model couldn't be set" in shown[0] and "No new chat appeared" in shown[1]
              and "Copy prompt" in shown[1] and page.locator("#toasts .toast.error").count() == 1, shown)

    name = "compact: only background agents have it; it waits while one asks you, and an ended one is woken for it"
    with step(page, name):
        open_card(page, A)  # alpha: a chat in a terminal
        terminal = page.locator("#drawer-body button", has_text="Compact").count()
        page.api.patch = {A: {"editor": "Cursor", "entrypoint": "claude-vscode"}}  # alpha, as a chat in Cursor
        poll(page)
        editor = page.locator("#drawer-body button", has_text="Compact").count()
        open_card(page, B)  # beta: asking you something
        waits = page.locator("#drawer-body button", has_text="Compact").is_disabled()
        open_card(page, C)  # gamma: its process ended
        page.locator("#drawer-body button", has_text="Compact").click()
        said = answer(page)
        page.wait_for_timeout(300)
        woken = [b for p, b in page.api.posts if p.endswith("/compact")]
        page.api.patch = {C: {"resumable": False}}
        poll(page)
        restart = page.locator("#drawer-body button", has_text="Compact").count()
        check(name, terminal == editor == restart == 0 and waits and "It wakes up for it." in said["text"]
              and woken == [{"sessionId": C}], (terminal, editor, restart, waits, said, woken))

    name = "ultracode: New agent can start a background agent with it, not a Chat in IDE"
    with step(page, name):
        page.api.post_result = {"jobId": "abcdef12", "name": "x"}
        page.locator("#new-chat").click()
        ide = is_open(page, "#n-ultra")
        page.locator('input[name="n-where"][value="background"]').check()
        page.locator("#n-prompt").fill("Fix the tests")
        page.locator("#n-ultra").check()
        page.locator("#n-submit").click()
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/launch-background")]
        check(name, not ide and sent and sent[-1].get("ultracode") is True, sent)

    name = "notices: beside the open details, not over them"
    with step(page, name):
        open_card(page, B)
        page.evaluate("toast('A notice')")
        toast, drawer = page.locator("#toasts .toast").last.bounding_box(), page.locator("#drawer").bounding_box()
        check(name, toast["x"] + toast["width"] <= drawer["x"])

    name = "notices: glass panels with a round icon in the kind's colour (a tick, a mark, an i) and no stripe; solid with transparency reduced"
    with step(page, name):
        page.evaluate("toast('Done', 'ok', 0); toast('Broke', 'error', 0); toast('Run it', 'info', 0)")
        look = lambda: page.evaluate("""() => [...document.querySelectorAll('#toasts .toast')].map(t => {
            const s = getComputedStyle(t), i = getComputedStyle(t, '::before');
            return { blur: s.backdropFilter.includes('blur'), alpha: parseFloat(s.backgroundColor.split(',')[3]),
                     round: parseFloat(s.borderTopLeftRadius), edges: [s.borderLeftWidth, s.borderTopWidth].join(' '),
                     lit: s.boxShadow.includes('inset'), icon: i.backgroundColor,
                     mask: (i.maskImage || i.webkitMaskImage || 'none') !== 'none' }; })""")
        glass = look()
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]})
        try:
            solid = page.evaluate("(s => [s.backgroundColor, s.backdropFilter])(getComputedStyle(document.querySelector('#toasts .toast')))")
        finally:
            cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "no-preference"}]})
        check(name, all(g["blur"] and 0 < g["alpha"] < 1 and g["round"] >= 16 and g["edges"] == "1px 1px" and g["lit"] and g["mask"]
                        for g in glass)
              and [g["icon"] for g in glass] == ["rgb(31, 122, 53)", "rgb(215, 0, 21)", "rgb(0, 102, 204)"]
              and solid == ["rgb(255, 255, 255)", "none"], (glass, solid))

    name = "details: the clicked card moves out from under them"
    with step(page, name):
        open_card(page, E)
        box, drawer = page.locator(f'.node[data-id="{E}"]').bounding_box(), page.locator("#drawer").bounding_box()
        check(name, box["x"] + box["width"] <= drawer["x"])

    name = "keyboard: Enter opens the details with focus in them, Esc returns it to the card"
    with step(page, name):
        page.locator(f'.node[data-id="{A}"]').focus()
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)
        inside = page.evaluate("document.querySelector('#drawer').contains(document.activeElement)")
        page.keyboard.press("Escape")
        check(name, inside and page.evaluate(f"document.activeElement.dataset.id === '{A}'"))

    name = "keyboard: Esc in Settings leaves the details open"
    with step(page, name):
        open_card(page, A)
        page.locator(".gear").click()
        page.keyboard.press("Escape")
        check(name, not page.evaluate("!!document.querySelector(':popover-open')") and is_open(page, "#drawer"))

    name = "agents: the details have one row for them, with how many there are and how many run"
    with step(page, name):
        page.api.agents = copy.deepcopy(AGENTS)
        open_card(page, B)
        row = page.locator("#drawer-body .agents-line")
        check(name, row.locator(".count").inner_text() == "7" and "3 running" in row.locator(".running-now").inner_text())

    name = "agents: a row picked in the pop-up shows its details on the right, the list stays where it is"
    with step(page, name):
        open_agents(page)
        first = page.locator("#agents-pop-detail h3").inner_text()  # it opens on the first agent running
        rows = page.locator("#agents-pop .agent-row")
        before = rows.count()
        page.locator("#agents-pop .agent-row", has_text="verify:app.js").click()
        page.wait_for_function("document.querySelector('#agents-pop-detail h3')?.textContent === 'verify:app.js'")
        page.wait_for_selector("#agents-pop-detail .facts")  # and its state and facts, before its details come
        page.wait_for_function("document.querySelector('#agents-pop-detail .state-badge')?.textContent === 'Failed'")
        side, main = page.locator("#agents-pop-list").bounding_box(), page.locator("#agents-pop-detail").bounding_box()
        check(name, first == "review:perf" and before == rows.count() == 7 and is_open(page, "#agents-pop-list")
              and main["x"] >= side["x"] + side["width"] - 1 and picked_agent(page) == "verify:app.js",
              (first, before, side, main))

    name = "agents: what the list knows of an agent shows at once, with Loading… under it until its details come"
    with step(page, name):
        page.evaluate("state.subInfo = {}")  # nothing of it kept from an earlier look
        page.api.hold_sub = True
        open_agents(page)
        known = page.inner_text("#agents-pop-detail")
        page.api.hold_sub = False
        for route, data in page.api.held:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        page.wait_for_function("document.querySelector('#agents-pop-detail')?.textContent.includes('Doing now')")
        check(name, all(w in known for w in ("review:perf", "Running", "Model", "Sonnet 5.5", "Duration", "Tokens", "Started by",
                                             "Workflow", "review-changes", "Loading…")) and "Doing now" not in known, known)

    name = "agents: the title above the list stays put while the list scrolls"
    with step(page, name):
        many = copy.deepcopy(AGENTS)
        many["direct"] += [dict(AGENTS["direct"][1], id=f"x{i}", description=f"Subagent {i}") for i in range(30)]
        open_agents(page, agents=many)
        head = page.locator("#agents-pop .pop-head").bounding_box()
        page.evaluate("document.querySelector('#agents-pop-list').scrollTop = 400")
        page.wait_for_timeout(100)
        after = page.locator("#agents-pop .pop-head").bounding_box()
        scrolled = page.evaluate("document.querySelector('#agents-pop-list').scrollTop")
        check(name, scrolled > 100 and head == after and "Agents in this chat" in page.inner_text("#agents-pop .pop-head")
              and "37 agents" in page.inner_text("#agents-pop .pop-head"), (scrolled, head, after))

    name = "agents: ↑ and ↓ move the pick through the list, Enter and Space pick the row in focus, Esc closes"
    with step(page, name):
        open_agents(page)
        start = picked_agent(page)
        page.keyboard.press("ArrowDown")
        down = picked_agent(page)
        page.wait_for_function(f"document.querySelector('#agents-pop-detail h3')?.textContent === '{down}'")
        page.keyboard.press("ArrowUp")
        up = picked_agent(page)
        page.keyboard.press("End")
        end = picked_agent(page)
        keys = []
        for key, label in (("Enter", "verify:app.js"), ("Space", "review:bugs")):
            page.locator("#agents-pop .agent-row", has_text=label).focus()
            page.keyboard.press(key)
            keys.append(picked_agent(page))
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('#agents-pop').open")
        check(name, (start, down, up, end) == ("review:perf", "review:security", "review:perf", "Find the old marker")
              and keys == ["verify:app.js", "review:bugs"] and not page.evaluate("document.querySelector('#agents-pop').open"),
              (start, down, up, end, keys))

    name = "agents: Tab, and ↑ ↓ from a card's header, reach a row in view, with the picked agent's card folded too"
    with step(page, name):
        open_agents(page)
        page.locator("#agents-pop details.run > summary").first.click()  # folds review-changes, which holds the pick
        page.wait_for_function("""document.querySelector('#agents-pop details.run')?.open === false
            && document.querySelector('#agents-pop .agent-row[tabindex="0"]')?.id === 'agent-row-d1'""")
        stops = page.evaluate("""[...document.querySelectorAll('#agents-pop .agent-row')]
            .filter(r => r.getAttribute('tabindex') === '0' && r.offsetParent).map(r => r.id)""")
        page.locator("#agents-pop-close").focus()
        reached = ""
        for _ in range(8):
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.classList.contains('agent-row')"):
                reached = page.evaluate("document.activeElement.id")
                break
        page.locator("#agents-pop details.run > summary").nth(1).focus()  # the Subagents card's header
        page.keyboard.press("ArrowDown")
        down = picked_agent(page)
        check(name, stops == ["agent-row-d1"] == [reached] and down == "Fix the poll loop", (stops, reached, down))

    name = "agents: ↓ on the header of a folded last card leaves the pick where it is, ↑ goes to the row above"
    with step(page, name):
        page.evaluate("state.runOpen = {}")  # no card folded by an earlier check
        open_agents(page)
        page.locator("#agents-pop details.run > summary").nth(1).click()  # folds Subagents, the last card
        page.wait_for_function("document.querySelectorAll('#agents-pop details.run')[1].open === false")
        page.locator("#agents-pop details.run > summary").nth(1).focus()
        start = picked_agent(page)
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(300)  # longer than a pick by key waits to ask for details
        down = (picked_agent(page), page.evaluate("document.activeElement.tagName"))
        page.keyboard.press("ArrowUp")
        up = picked_agent(page)
        page.evaluate("state.runOpen = {}")
        check(name, start == down[0] == "review:perf" and down[1] == "SUMMARY" and up == "verify:app.js", (start, down, up))

    name = "agents: an agent that drops out of the list leaves its pick and its focus to the next row, else the one before, else the list"
    with step(page, name):
        page.evaluate("state.runOpen = {}")
        open_agents(page)  # picked and focused: review:perf
        page.wait_for_function("document.activeElement.id === 'agent-row-a2'")
        del page.api.agents["workflows"][0]["agents"][1]  # a workflow retried it
        poll(page)
        page.wait_for_function("document.activeElement.id === 'agent-row-a3'")
        page.wait_for_function("document.querySelector('#agents-pop-detail h3')?.textContent === 'review:security'")
        page.wait_for_timeout(200)  # the poll that found it gone may have asked once more
        page.api.sub_asked.clear()
        poll(page, 2)
        page.wait_for_timeout(200)
        asked = list(page.api.sub_asked)
        forward = (picked_agent(page), page.evaluate("document.activeElement.id"))
        page.keyboard.press("ArrowDown")  # the keys go on from there
        next_one = picked_agent(page)
        page.keyboard.press("End")  # the last row picked, then gone: the one before it
        del page.api.agents["direct"][1]
        poll(page)
        page.wait_for_function("document.activeElement.id === 'agent-row-d1'")
        before_last = picked_agent(page)
        page.api.agents["workflows"].clear()  # and the rest
        page.api.agents["direct"].clear()
        poll(page)
        page.wait_for_function("document.activeElement.id === 'agents-pop-list'")
        page.wait_for_function("document.querySelector('#agents-pop-detail')?.textContent.includes('No agents to show')")
        check(name, forward == ("review:security", "agent-row-a3") and set(asked) == {"a3"} and next_one == "verify:server.py"
              and before_last == "Fix the poll loop", (forward, asked, next_one, before_last))

    name = "agents: a card folded earlier unfolds for the running agent the pop-up opens on, and the keyboard is there"
    with step(page, name):
        page.api.agents = copy.deepcopy(AGENTS)
        open_card(page, B)
        page.evaluate("state.runOpen = { r1: false }")
        page.locator("#drawer-body .agents-line").click()
        page.wait_for_selector("#agents-pop[open] .agent-row")
        page.wait_for_function("document.activeElement.id === 'agent-row-a2'")
        check(name, page.evaluate("document.querySelector('#agents-pop details.run').open"))

    name = "agents: with nothing running the pop-up opens on an empty details pane, and a row fills it"
    with step(page, name):
        quiet = copy.deepcopy(AGENTS)
        for a in [x for r in quiet["workflows"] for x in r["agents"]] + quiet["direct"]:
            a["state"] = "done" if a["state"] == "running" else a["state"]
        quiet["workflows"][0]["status"] = "completed"
        open_agents(page, agents=quiet)
        empty = (page.locator("#agents-pop-detail .pop-empty .empty-icon").count() == 1
                 and "No agent picked" in page.inner_text("#agents-pop-detail")
                 and "↑ and ↓ move between agents" in page.inner_text("#agents-pop-detail")
                 and not page.locator("#agents-pop .agent-row[aria-current]").count())
        page.locator("#agents-pop .agent-row", has_text="Find the old marker").click()
        page.wait_for_function("document.querySelector('#agents-pop-detail h3')?.textContent === 'Find the old marker'")
        check(name, empty and not page.locator("#agents-pop-detail .pop-empty").count(), empty)

    name = "agents: keyboard focus stays on its row, or its card's header, when the list redraws"
    with step(page, name):
        open_agents(page)
        page.keyboard.press("ArrowDown")
        before = page.evaluate("document.activeElement.id")
        page.api.agents["workflows"][0]["agents"][1]["state"] = "done"  # a row and the card's count change
        poll(page, 2)
        page.wait_for_function("document.querySelector('#agents-pop .run-count')?.textContent.startsWith('2 of 5')")
        row = page.evaluate("document.activeElement.id")
        page.locator("#agents-pop details.run > summary").first.focus()
        page.api.agents["workflows"][0]["agents"][2]["state"] = "done"  # the card's count changes again
        poll(page, 2)
        page.wait_for_function("document.querySelector('#agents-pop .run-count')?.textContent.startsWith('3 of 5')")
        check(name, before == "agent-row-a3" == row and page.evaluate("document.activeElement.id") == "fold-r1", (before, row))

    name = "agents: a clock that ticks changes in place, so the list isn't rebuilt under the pointer and keyboard"
    with step(page, name):
        open_agents(page)
        page.evaluate("""() => { window.__swaps = 0; new MutationObserver(m => window.__swaps += m.length)
            .observe(document.querySelector('#agents-pop-list'), { childList: true }); }""")
        time = page.locator("#agent-row-a3 .agent-time")
        before = time.inner_text()
        page.api.agents["workflows"][0]["agents"][2]["durationMs"] += 7000  # the next polls show it longer
        poll(page, 2)
        page.wait_for_function("(b) => document.querySelector('#agent-row-a3 .agent-time').textContent !== b", arg=before)
        check(name, page.evaluate("window.__swaps") == 0, (before, time.inner_text()))

    name = "agents: a row has a hover fill, and a focus ring from the keyboard, so it's plain it can be clicked"
    with step(page, name):
        open_agents(page)
        row = page.locator("#agent-row-a1")  # review:bugs
        fill = lambda: row.evaluate("e => getComputedStyle(e).backgroundColor")
        idle = fill()
        row.hover()
        page.wait_for_function("(c) => getComputedStyle(document.querySelector('#agent-row-a1')).backgroundColor !== c", arg=idle)
        hover = fill()
        page.keyboard.press("ArrowUp")  # from the picked row, the one before it: review:bugs
        ring = page.evaluate("[document.activeElement.textContent, getComputedStyle(document.activeElement).outlineStyle]")
        check(name, idle == "rgba(0, 0, 0, 0)" and hover != idle and ring[1] == "solid" and "review:bugs" in ring[0], (idle, hover, ring))

    name = "agents: a workflow card shows how far it got and has its ask in the header, which doesn't fold it"
    with step(page, name):
        open_agents(page)
        card = page.locator("#agents-pop details.run").first
        bar = card.locator(".run-status .bar i").first.evaluate("e => e.style.width")
        card.locator("summary .run-action").click()
        page.wait_for_function("document.querySelector('#toasts')?.textContent.includes('Asked beta.')")
        sent = [b for p, b in page.api.posts if p.endswith("/send")]
        check(name, card.locator(".run-count").inner_text() == "1 of 5 done · 1 failed" and bar == "20%"
              and card.locator("summary .state-badge").inner_text() == "Running" and card.get_attribute("open") is not None
              and card.locator("summary .run-action").inner_text() == "Ask to stop"
              and len(sent) == 1 and "stop the workflow" in sent[0]["text"] and "Asked beta." in page.inner_text("#toasts"),
              (bar, sent))

    name = "agents: \"Started by\" is a chip in the app's style, not the browser's blue underlined link"
    with step(page, name):
        open_agents(page)
        chip = page.locator("#agents-pop-detail .chip-link")
        look = chip.evaluate("""e => { const s = getComputedStyle(e);
            return [e.tagName, s.textDecorationLine, s.color, e.textContent, e.querySelector('.dot')?.className]; }""")
        node = page.evaluate(f"document.querySelector('.node[data-id=\"{B}\"] .dot').className")  # its dot on the board
        chip.click()
        page.wait_for_function("!document.querySelector('#agents-pop').open")
        check(name, look[0] == "BUTTON" and look[1] == "none" and look[2] != "rgb(0, 0, 238)" and look[3] == "beta"
              and look[4] == node and not page.evaluate("document.querySelector('#agents-pop').open")
              and is_open(page, "#drawer"), (look, node))

    name = "folds: no browser marker is left on any fold, and each chevron is the same drawn one"
    with step(page, name):
        open_agents(page)
        # a marker is the browser's (a list item, or a list symbol) or a typed triangle in a pseudo-element
        marks = """() => [...document.querySelectorAll('summary')].map(s => { const c = getComputedStyle(s), b = getComputedStyle(s, '::before');
            return [c.display === 'list-item' || c.listStyleType !== 'none'
                    || /[▸▾▴◂]/.test(getComputedStyle(s, '::after').content + b.content),
                    b.width, b.height, b.backgroundImage.startsWith('url(')]; })"""
        found = page.evaluate(marks)  # the chat's status line and Connections, the sidebar's Activity, the pop-up's cards
        page.evaluate("openWirePop('c1')")  # an arrow's notes fold
        found += page.evaluate(marks)
        page.evaluate("document.querySelector('#wire-pop').close()")
        page.locator("#new-workflow").click()  # New workflow's agents fold
        page.locator("#n-team-more").click()
        page.locator("#n-team-more").click()
        found += page.evaluate(marks)
        count = page.locator("#chat-dialog details.n-agent").count()
        page.locator("#n-team-count").fill("0")  # the team is kept between looks: leave none
        text = page.inner_text("body")
        check(name, len(found) >= 10 and not any(m[0] for m in found) and {tuple(m[1:]) for m in found} == {("12px", "12px", True)}
              and "▸" not in text and "▾" not in text and count == 2, found)

    name = "motion: with reduced motion the running ring and the running dot stand still"
    with step(page, name):
        open_agents(page)
        spin = "[getComputedStyle(document.querySelector('#agents-pop .state-icon .arc')).animationName, " \
               "getComputedStyle(document.querySelector('#drawer .running-now i')).animationName]"
        moving = page.evaluate(spin)
        page.emulate_media(reduced_motion="reduce")
        try:
            still = page.evaluate(spin)
        finally:
            page.emulate_media(reduced_motion="no-preference")
        check(name, "none" not in moving and still == ["none", "none"], (moving, still))

    name = "dropdowns: the other ones are still native selects, drawn as the app's fields with its chevron and a focus ring"
    with step(page, name):
        looks = page.evaluate("""() => ['ide-pick', 'n-editor', 'n-model'].map(id => { const e = document.getElementById(id), s = getComputedStyle(e);
            return [e.tagName, s.appearance, s.backgroundImage.startsWith('url(')]; })""")
        check(name, looks == [["SELECT", "none", True]] * 3, looks)

    name = "board picker: the closed pill reads Board and the board's name, and takes the top bar's focus ring from the keyboard"
    with step(page, name):
        page.locator("#new-chat").focus()
        page.keyboard.press("Shift+Tab")  # back to the Board picker, from the keyboard
        ring = page.evaluate("""() => { const e = document.activeElement, s = getComputedStyle(e);
            return [e.id, s.outlineStyle, s.outlineWidth, s.outlineOffset,
                    e.tagName, getComputedStyle(e, '::after').backgroundImage.startsWith('url('), e.innerText.replace(/\\s+/g, ' ')]; }""")
        check(name, ring == ["board-select", "solid", "2px", "2px", "BUTTON", True, "Board project board"], ring)

    name = "details: buttons in a chat's rows are one height; Background agent's sit in two even columns, the odd last one across the row"
    with step(page, name):
        open_card(page, B)
        rows = page.evaluate("""() => [...document.querySelectorAll('#drawer-body .drawer-actions:not(.ultracode)')].map(r =>
            [...r.querySelectorAll('.btn')].map(b => { const k = b.getBoundingClientRect(); return [Math.round(k.left), Math.round(k.width), Math.round(k.height)]; }))""")
        every, bg = [b for r in rows for b in r], rows[0]
        pairs, last = bg[:4], bg[4:]
        check(name, len({h for _, _, h in every}) == 1 and len(bg) == 5 and len({w for _, w, _ in pairs}) == 1
              and len({x for x, _, _ in pairs}) == 2 and last[0][0] == pairs[0][0] and last[0][1] >= 2 * pairs[0][1], rows)

    name = "details: destructive buttons are red text on the normal fill, and Tell connected agents sits right under Remove"
    with step(page, name):
        open_card(page, B)
        look = page.evaluate("""() => { const b = [...document.querySelectorAll('#drawer-body .btn')];
            const by = (t) => b.find(x => x.textContent.startsWith(t)), css = (e) => getComputedStyle(e);
            const remove = by('Remove from board'), label = document.querySelector('#drawer-body .drawer-foot > label.check');
            return { fills: [css(by('End agent')).backgroundColor, css(by('Delete agent')).backgroundColor, css(remove).backgroundColor],
                     red: [css(by('Delete agent')).color, css(remove).color], plain: css(by('End agent')).color,
                     gap: label.getBoundingClientRect().top - remove.getBoundingClientRect().bottom,
                     under: label.textContent.includes('Tell connected agents') }; }""")
        check(name, len(set(look["fills"])) == 1 and look["red"][0] == look["red"][1] != look["plain"]
              and 0 <= look["gap"] <= 16 and look["under"], look)

    name = "contrast: an ended card's name is readable (4.5:1)"
    with step(page, name):
        check(name, page.evaluate(CONTRAST, f'.node[data-id="{D}"] .name') >= 4.5)

    name = "contrast: a message still sending isn't faded"
    with step(page, name):
        open_card(page, A)
        page.evaluate(f"() => {{ state.outbox['{A}'] = [{{ text: 'on its way', at: Date.now() / 1000, state: 'sending' }}]; renderDrawer(); }}")
        check(name, page.evaluate("(s => s.opacity === '1' && s.borderStyle === 'dashed')"
                                  "(getComputedStyle(document.querySelector('#drawer-body .msg.pending .bubble')))"))
        page.evaluate("state.outbox = {}")

    name = "settings: the board folder's button reads Open in IDE"
    with step(page, name):
        check(name, page.inner_text("#open-board-folder") == "Open in IDE")

    name = "settings: the IDE picked under the gear is the one every IDE button and New agent use"
    with step(page, name):
        page.locator(".gear").click()
        page.select_option("#ide-pick", "Cursor")
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        uses = "Cursor" in page.get_attribute("#open-board-folder", "title")
        page.locator("#new-chat").click()
        check(name, uses and page.input_value("#n-editor") == "Cursor" and page.evaluate("defaultEditor()") == "Cursor")

    name = "hint: shows on the top bar at 1440 px"
    with step(page, name):
        page.wait_for_timeout(200)
        check(name, page.evaluate("getComputedStyle(document.querySelector('.topbar .hint')).display") != "none")

    name = "dialogs: each is named by its heading"
    with step(page, name):
        check(name, all(page.evaluate(
            "(d => !!(d.getAttribute('aria-label') || document.getElementById(d.getAttribute('aria-labelledby'))?.textContent))"
            f"(document.querySelector('#{i}'))") for i in ("connect-dialog", "chat-dialog", "board-dialog")))

    # Connecting to an ended background agent wakes it. Gamma (an agent whose process has ended) is made one the
    # server lists as asleep, with a saved conversation (wakeable) or without one (restart it first).
    ASLEEP = {"running": False, "messageBlock": "This background agent isn't running right now. Send it a prompt to wake it."}
    NO_CHAT = {"running": False, "resumable": False, "wakeable": False,
               "messageBlock": "This background agent has no saved conversation, so it can't be woken; restart it first."}

    def drag_connect(page, src, dst):
        """Drag an arrow from src's handle onto dst's card, as a hand does; the Connect dialog opens."""
        page.wait_for_timeout(200)
        h = page.locator(f'.node[data-id="{src}"] .port.out').bounding_box()
        t = page.locator(f'.node[data-id="{dst}"] .name').bounding_box()
        page.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
        page.mouse.down()
        page.mouse.move(t["x"] + 10, t["y"] + 5, steps=8)
        page.mouse.up()
        page.wait_for_selector("#connect-dialog[open]")

    name = "connect: an ended background agent that can be woken has a handle to drag from; one with no saved conversation has none"
    with step(page, name):
        page.api.patch = {C: {**ASLEEP, "wakeable": True}}
        poll(page)
        woken = page.locator(f'.node[data-id="{C}"] .port.out').count()
        page.api.patch = {C: NO_CHAT}
        poll(page)
        check(name, woken == 1 and page.locator(f'.node[data-id="{C}"] .port.out').count() == 0)

    name = ("connect: dropping an arrow on an ended background agent that can be woken says it isn't running and that "
            "Connecting wakes it, with no error, Connect enabled and its note still editable")
    with step(page, name):
        page.api.patch = {C: {**ASLEEP, "wakeable": True}}
        page.api.post_result = {"id": "c1"}
        poll(page)
        drag_connect(page, A, C)
        line = page.inner_text("#c-wake")
        shown = is_open(page, "#c-wake") and not is_open(page, "#c-error")
        ready = page.locator("#c-submit").is_enabled() and page.locator("#c-text-to").is_enabled()
        page.locator("#c-text-to").fill("Wake up and talk to alpha.")
        page.locator("#c-submit").click()
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/connect")]
        check(name, line == "gamma isn't running. Connecting wakes it with its note as its first prompt."
              and shown and ready and sent and sent[-1]["from"] == A and sent[-1]["to"] == C
              and sent[-1]["notifyTo"] is True and sent[-1]["textTo"] == "Wake up and talk to alpha."
              and not page.evaluate("document.querySelector('#connect-dialog').open"), (line, shown, ready, sent))

    name = "connect: from an ended background agent too, and with its note switched off the line says it isn't woken"
    with step(page, name):
        page.api.patch = {C: {**ASLEEP, "wakeable": True}}
        poll(page)
        drag_connect(page, C, A)
        both = page.inner_text("#c-wake")
        page.locator("#c-notify-from").uncheck()
        off = page.inner_text("#c-wake")
        check(name, both == "gamma isn't running. Connecting wakes it with its note as its first prompt."
              and off == "gamma isn't running. Its note is off, so it isn't woken and the connection is only drawn."
              and page.locator("#c-text-from").is_disabled() and page.locator("#c-submit").is_enabled(), (both, off))

    name = "connect: an ended agent with no saved conversation still gets the red message, no wake line, Connect off"
    with step(page, name):
        page.api.patch = {C: NO_CHAT}
        poll(page)
        page.evaluate(f"openConnectDialog('{A}', '{C}')")  # it has no handle to drag from, but a card to drop on
        check(name, "restart it first" in page.inner_text("#c-error") and not is_open(page, "#c-wake")
              and page.locator("#c-submit").is_disabled())

    name = "failures: a failed Disconnect leaves a notice and the details open, no alert()"
    with step(page, name):
        page.api.post_status = 500
        page.locator(".wire-label").first.click()
        page.wait_for_function("!document.querySelector('#drawer').hidden")
        page.get_by_role("button", name="Disconnect").click()
        answer(page)
        page.wait_for_timeout(400)
        check(name, page.locator("#toasts .toast.error").count() == 1 and is_open(page, "#drawer")
              and "alert" not in page.dialogs)

    name = "asking first: a glass alert with two round buttons side by side; Cancel and Esc say no; one that can't be undone is red and starts on Cancel"
    with step(page, name):
        open_card(page, B)  # beta: running
        delete = page.locator("#drawer-body button", has_text="Delete agent")
        deleted = lambda: [1 for p, _ in page.api.posts if p.endswith("/agent-delete")]
        delete.click()
        page.wait_for_selector("#ask[open]")
        page.wait_for_function("document.querySelector('#ask').getAnimations().length === 0")
        look = page.evaluate("""() => {
            const box = (s) => document.querySelector(s).getBoundingClientRect(), css = (s) => getComputedStyle(document.querySelector(s));
            const no = box('#ask-no'), yes = box('#ask-yes'), alert = box('#ask');
            const [r, g] = css('#ask-yes').backgroundColor.match(/\\d+/g).map(Number);
            return { side: no.right <= yes.left && Math.abs(no.top - yes.top) < 1, equal: Math.abs(no.width - yes.width) < 1,
                     tall: no.height >= 44 && yes.height >= 44, small: alert.width <= 380 && alert.height < 400,
                     glass: css('#ask').backdropFilter !== 'none', red: r > 180 && g < 120,
                     centred: css('#ask-title').textAlign === 'center', focus: document.activeElement.id,
                     corners: css('#ask').borderTopLeftRadius === css('#connect-dialog').borderTopLeftRadius };  // as the other dialogs'
        }""")
        page.keyboard.press("Escape")
        page.wait_for_selector("#ask[open]", state="detached")
        esc = not deleted() and is_open(page, "#drawer")  # Esc doesn't close the details behind it
        delete.click()
        cancelled = answer(page, yes=False)
        delete.click()
        said = answer(page)
        page.wait_for_timeout(200)
        open_card(page, B)
        page.locator("#drawer-body button", has_text="End agent").click()
        plain = answer(page, yes=False)
        check(name, all(v for k, v in look.items() if k != "focus") and look["focus"] == "ask-no"
              and esc and cancelled["danger"] and len(deleted()) == 1 and said["ok"] == "Delete agent"
              and said["title"] == "Delete the background agent beta?" and plain["focus"] == "ask-yes" and not plain["danger"]
              and page.dialogs == [], (look, esc, cancelled, said, plain, page.dialogs))

    # Add agents: a sleeping background agent's row has a − that deletes it, as Delete agent on its card does.
    def onto_del(s):
        """The pointer onto a row, then onto its − (which takes the pointer only while its row is under it)."""
        park(page)
        page.hover(avail_row(s) + " .name")
        page.hover(avail_row(s) + " .del")

    name = ("add agents: only a sleeping background agent's row has a −, hidden at rest, shown under the pointer and when the "
            "keys reach it; red on the plain fill of the + beside it, as big, in light and dark")
    with step(page, name):
        page.api.avail = [SLEEPY, NO_REPLY, RUNNING_BG, EDITOR_CHAT]
        poll(page)
        park(page)
        has = page.eval_on_selector_all("#available .avail-row", "rs => rs.map(r => [r.querySelector('.name').textContent, !!r.querySelector('.del')])")
        def look():
            # Read once the fades are over, not after a fixed time: in dark, the − and the + take two fades (theirs starts
            # again while their row's colour fades), and on a slow machine 300 ms caught the − one step short of its red.
            fades_done(page, avail_row(SLEEPY) + " .del", avail_row(SLEEPY) + " .add", "#delete-board")
            return page.evaluate("""(sel) => {
                const d = document.querySelector(sel + ' .del'), a = document.querySelector(sel + ' .add'), s = getComputedStyle(d);
                const b = d.getBoundingClientRect(), p = a.getBoundingClientRect();
                return { shown: s.opacity === '1' && s.pointerEvents === 'auto', hidden: s.opacity === '0' && s.pointerEvents === 'none',
                         red: s.color === getComputedStyle(document.querySelector('#delete-board')).color, colour: s.color,
                         plain: s.backgroundColor === getComputedStyle(a).backgroundColor && s.backdropFilter === 'none',
                         pair: b.width === 26 && b.height === 26 && p.width === 26 && b.right <= p.left && p.left - b.right <= 6
                           && Math.abs(b.top - p.top) < 1,
                         title: d.getAttribute('title'), label: d.getAttribute('aria-label') }; }""", avail_row(SLEEPY))
        rest = look()
        page.hover(avail_row(SLEEPY) + " .name")
        hovered = look()
        park(page)
        page.focus(avail_row(SLEEPY) + " .add")
        page.keyboard.press("Shift+Tab")
        keys = look()["shown"] and page.evaluate("document.activeElement.matches('.del')")
        page.emulate_media(color_scheme="dark")
        try:
            dark = look()  # (with the keys on the −, the tooltip has its title off)
        finally:
            page.emulate_media(color_scheme="light")
        check(name, has == [["zeta", False], ["sleepy", True], ["restart me", True], ["busy bee", False], ["cursor chat", False]]
              and rest["hidden"] and rest["title"] == "Delete this background agent" and rest["label"] == "Delete sleepy"
              and all(v["red"] and v["plain"] and v["pair"] for v in (rest, dark)) and rest["colour"] != dark["colour"]
              and hovered["shown"] and keys, (has, rest, hovered, keys, dark))

    name = ("add agents: the − asks first in the words of Delete agent on a card; Cancel and Esc send nothing; a yes sends one "
            "delete for that agent (of two with one name, the one picked), its row goes without waiting for a poll and the "
            "keys go on to the row beside it")
    with step(page, name):
        open_card(page, B)
        page.locator("#drawer-body button", has_text="Delete agent").click()
        on_card = answer(page, yes=False)
        page.evaluate("closeDrawer()")
        page.api.avail = [SLEEPY, TWIN]
        poll(page)
        deletes = lambda: [b for p, b in page.api.posts if p.endswith("/agent-delete")]
        onto_del(TWIN)
        page.click(avail_row(TWIN) + " .del")
        cancelled = answer(page, yes=False)
        onto_del(TWIN)
        page.click(avail_row(TWIN) + " .del")
        page.wait_for_selector("#ask[open]")
        page.keyboard.press("Escape")
        page.wait_for_selector("#ask[open]", state="detached")
        none_sent = deletes() == []
        page.api.hold = {"b1"}  # no poll answers from here on: the row goes by itself
        park(page)
        page.focus(avail_row(TWIN) + " .add")
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Enter")
        said = answer(page)
        page.wait_for_selector(avail_row(TWIN), state="detached")  # once it has folded away
        kept = page.locator(avail_row(SLEEPY)).count()
        focus = page.evaluate("document.activeElement.closest('.avail-row')?.dataset.sid")
        page.api.hold = set()
        for route, data in page.api.held:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        check(name, on_card["title"] == "Delete the background agent beta?" and said["title"] == "Delete the background agent sleepy?"
              and all(said[k] == on_card[k] == cancelled[k] for k in ("text", "ok", "danger", "focus")) and said["danger"]
              and said["focus"] == "ask-no" and none_sent and deletes() == [{"jobId": TWIN["jobId"]}] and kept == 1
              and focus == SLEEPY["sessionId"], (on_card, cancelled, said, deletes(), kept, focus))

    name = ("add agents: while an agent is deleted its row fades, its − turns and takes no second click, and its + waits; a "
            "failure is a notice, and the row is as it was")
    with step(page, name):
        page.api.avail = [SLEEPY]
        poll(page)
        page.api.hold_post = True  # the server is still deleting it
        onto_del(SLEEPY)
        page.click(avail_row(SLEEPY) + " .del")
        answer(page)
        page.wait_for_selector(avail_row(SLEEPY) + ".deleting")
        fades_done(page, avail_row(SLEEPY) + " .del")
        now = lambda: page.evaluate("""(sel) => { const r = document.querySelector(sel), d = r.querySelector('.del');
            return { busy: r.classList.contains('deleting'), ring: !!d.querySelector('.state-icon.running'),
                     shown: getComputedStyle(d).opacity === '1', faded: getComputedStyle(r.querySelector('.name')).opacity === '0.5',
                     waits: r.querySelector('.add').disabled, title: d.getAttribute('title') }; }""", avail_row(SLEEPY))
        busy = now()
        page.click(avail_row(SLEEPY) + " .del")
        page.wait_for_timeout(200)
        again = asking(page)
        for route, _ in page.api.held:
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "It didn't work."}))
        page.wait_for_selector("#toasts .toast.error")
        after = now()
        sent = [b for p, b in page.api.posts if p.endswith("/agent-delete")]
        check(name, busy == {"busy": True, "ring": True, "shown": True, "faded": True, "waits": True, "title": "Deleting…"}
              and not again and sent == [{"jobId": SLEEPY["jobId"]}] and page.locator("#toasts .toast.error").count() == 1
              and not after["busy"] and not after["ring"] and not after["faded"] and not after["waits"], (busy, again, sent, after))

    name = "add agents: a poll that still lists a deleted agent doesn't bring its row back, and once one doesn't, nothing of it is kept"
    with step(page, name):
        page.api.avail = [SLEEPY]
        page.api.keep_deleted = True  # the server's list still has it, as a poll sent before it went does
        poll(page)
        onto_del(SLEEPY)
        page.click(avail_row(SLEEPY) + " .del")
        answer(page)
        page.wait_for_selector(avail_row(SLEEPY), state="detached")
        poll(page, 2)
        stale = page.locator(avail_row(SLEEPY)).count()
        page.api.avail = []
        poll(page)
        check(name, stale == 0 and page.evaluate("state.deleting.size") == 0 and page.locator("#available .avail-row").count() == 1)

    # The tooltip puts a title back as the last attribute for the poll's compare: one that wasn't last made the
    # list differ, so it was rebuilt under the pointer on every poll (and the − faded in again each time).
    name = "add agents: polls while the pointer rests on a row's − or + rebuild nothing, and the − and its label stay"
    with step(page, name):
        page.api.avail = [SLEEPY]
        poll(page)
        page.evaluate("""() => { window.__availSwaps = 0; new MutationObserver(m => window.__availSwaps += m.length)
            .observe(document.querySelector('#available'), { childList: true, subtree: true }); }""")
        onto_del(SLEEPY)
        page.wait_for_selector("#tip:popover-open", timeout=1500)
        poll(page, 3)
        label = tip(page)
        fades_done(page, avail_row(SLEEPY) + " .del")
        shown = page.evaluate(f"getComputedStyle(document.querySelector('{avail_row(SLEEPY)} .del')).opacity")
        page.hover(avail_row(SLEEPY) + " .add")
        page.wait_for_selector("#tip:popover-open", timeout=1500)
        poll(page, 2)
        swaps = page.evaluate("window.__availSwaps")
        check(name, swaps == 0 and shown == "1" and label["open"] and label["text"] == "Delete this background agent",
              (swaps, shown, label))

    name = "new agent: Chat in IDE has the folder box, on the board's folder"
    with step(page, name):
        page.locator("#new-chat").click()
        page.locator('input[name="n-where"][value="editor"]').check()
        check(name, is_open(page, "#n-folder") and page.input_value("#n-folder") == FOLDER)

    name = "new agent: one click on Open sends the folder, with the folder list open"
    with step(page, name):
        page.api.post_result = {"launchId": "x", "opensChat": True}
        page.locator("#new-chat").click()
        page.locator('input[name="n-where"][value="editor"]').check()
        page.locator("#n-folder").fill("")
        page.locator("#n-folder").type(OTHER[:9])  # the list opens as you type
        page.locator("#n-submit").click()           # one click, with the list open
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/launch-editor")]
        check(name, sent and sent[-1].get("folder") == OTHER[:9] and not page.evaluate("document.querySelector('#chat-dialog').open"))

    name = "new agent: images pasted or dropped go with the first prompt, either way it starts, then are cleared"
    with step(page, name):
        page.evaluate("state.images = {}")
        page.api.post_result = {"jobId": "abcdef12", "name": "x"}
        page.locator("#new-chat").click()
        taken = paste(page, "#n-prompt", "image/png") and paste(page, "#chat-form", "image/png", "drop")
        page.wait_for_timeout(200)
        two = page.locator("#n-images .thumb").count() == 2
        page.locator("#n-images .thumb-x").first.click()  # takes one out; doesn't submit the dialog
        still = page.evaluate("document.querySelector('#chat-dialog').open")
        page.locator('input[name="n-where"][value="background"]').check()
        page.locator("#n-prompt").fill("What is this?")
        page.locator("#n-submit").click()
        page.wait_for_timeout(300)
        bg = [b for p, b in page.api.posts if p.endswith("/launch-background")]
        page.api.post_result = {"launchId": "x", "opensChat": True}
        page.locator("#new-chat").click()
        cleared = page.locator("#n-images .thumb").count() == 0
        paste(page, "#n-prompt", "image/png")
        page.wait_for_timeout(200)
        page.locator('input[name="n-where"][value="editor"]').check()
        page.locator("#n-prompt").fill("Explain")
        page.locator("#n-submit").click()
        page.wait_for_timeout(300)
        ide = [b for p, b in page.api.posts if p.endswith("/launch-editor")]
        check(name, taken and two and still and cleared and bg and bg[-1].get("images") == [{"data": PNG_1PX}]
              and ide and ide[-1].get("images") == [{"data": PNG_1PX}], (taken, two, still, cleared))

    sections = lambda: page.locator("#n-team-list details.n-agent")
    team_posts = lambda: [b for p, b in page.api.posts if p.endswith("/launch-team")]

    name = "new workflow: the number shows that many agent sections, open, and each folds; New agent has none"
    with step(page, name):
        page.locator("#new-chat").click()
        plain = not is_open(page, "#n-team")
        page.evaluate("document.querySelector('#chat-dialog').close()")
        page.locator("#new-workflow").click()
        none = sections().count() == 0 and is_open(page, "#n-agents") and is_open(page, "#n-model")
        for _ in range(3):
            page.locator("#n-team-more").click()
        three = sections().count() == 3 and page.evaluate("[...document.querySelectorAll('.n-agent')].every(d => d.open)")
        team_only = (not is_open(page, "#n-agents") and not is_open(page, "#n-model") and not is_open(page, "#n-terminal")
                     and page.inner_text("#n-submit") == "Start team")
        page.locator("#n-team-count").fill("5")
        five = sections().count() == 5
        page.locator("details.n-agent summary").nth(1).click()
        folded = page.evaluate("document.querySelectorAll('.n-agent')[1].open") is False
        page.locator("details.n-agent summary").nth(1).click()
        check(name, plain and none and three and team_only and five and folded
              and page.evaluate("document.querySelectorAll('.n-agent')[1].open"), (plain, none, three, team_only, five, folded))

    name = "new workflow: each agent's section, and the master at the top, get a model (Opus) and an effort (Default)"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("0")
        none = not is_open(page, "#n-team-model") and not is_open(page, "#n-team-effort")
        page.locator("#n-team-count").fill("2")
        picks = page.evaluate("""['#n-team-model', '#n-team-effort', '#n-model-0', '#n-effort-0', '#n-model-1', '#n-effort-1']
            .map(s => { const e = document.querySelector(s);
                        return [e.offsetHeight > 0, e.value, [...e.options].map(o => o.text).join(',')]; })""")
        models, efforts = "Fable,Opus,Sonnet,Haiku", "Default,Low,Medium,High,Extra high,Max"
        check(name, none and picks == [[True, "opus", models], [True, "", efforts]] * 3, (none, picks))

    name = "new workflow: what you type in a section, and the master's picks, stay when the number changes; its title shows the role"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("3")
        page.locator("#n-team-model").select_option("fable")
        page.locator("#n-team-effort").select_option("low")
        page.locator("#n-role-0").fill("tester")
        page.locator("#n-task-0").fill("Test the login page")
        page.locator("#n-role-1").fill("writer")
        page.locator("#n-model-1").select_option("sonnet")
        page.locator("#n-effort-1").select_option("low")
        page.locator("#n-team-count").fill("1")
        one = sections().count() == 1 and page.input_value("#n-task-0") == "Test the login page"
        page.locator("#n-team-less").click()
        page.locator("#n-team-more").click()
        page.locator("#n-team-more").click()
        check(name, one and sections().count() == 2 and page.input_value("#n-role-0") == "tester"
              and page.input_value("#n-role-1") == "writer"
              and page.input_value("#n-model-1") == "sonnet" and page.input_value("#n-effort-1") == "low"
              and page.input_value("#n-team-model") == "fable" and page.input_value("#n-team-effort") == "low"
              and page.inner_text("details.n-agent summary >> nth=0").startswith("Agent 1 · tester"), one)

    name = "new workflow: with no agents it starts one workflow agent, as before"
    with step(page, name):
        page.api.post_result = {"jobId": "abcdef12", "name": "x"}
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("0")
        page.locator("#n-prompt").fill("Review src")
        page.locator("#n-submit").click()
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/launch-background")]
        check(name, sent and sent[-1]["prompt"].startswith("Use a workflow to do this: Review src") and not team_posts(), sent)

    name = "new workflow: with agents it sends the team (your prompt, each role, prompt, model and effort), then starts clean"
    with step(page, name):
        page.api.post_result = {"launchId": "t1", "name": "Fix the login", "agents": []}
        page.locator("#new-workflow").click()
        page.locator("#n-prompt").fill("Fix the login")
        page.locator("#n-team-count").fill("2")
        for i, (role, task) in enumerate((("tester", "Test it"), ("writer", "Document it"))):
            page.locator(f"#n-role-{i}").fill(f" {role} ")
            page.locator(f"#n-task-{i}").fill(task)
        # back from what the checks above picked, as a dialog closed without starting keeps it
        for sel, v in (("#n-team-model", "opus"), ("#n-team-effort", ""), ("#n-model-1", "opus"), ("#n-effort-1", "")):
            page.locator(sel).select_option(v)
        page.locator("#n-submit").click()
        page.wait_for_timeout(300)
        closed = not page.evaluate("document.querySelector('#chat-dialog').open")
        page.locator("#new-workflow").click()
        check(name, team_posts() == [{"prompt": "Fix the login", "images": [], "folder": FOLDER, "name": "",
                                      "permissionMode": "auto", "ultracode": False, "model": "opus", "effort": "",
                                      "agents": [{"role": "tester", "prompt": "Test it", "model": "opus", "effort": ""},
                                                 {"role": "writer", "prompt": "Document it", "model": "opus", "effort": ""}]}]
              and closed and page.input_value("#n-team-count") == "0" and sections().count() == 0, team_posts())

    name = "new workflow: an agent without a role isn't sent; its section opens there"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-prompt").fill("Fix the login")
        page.locator("#n-team-count").fill("2")
        page.locator("#n-role-0").fill("tester")
        page.locator("#n-task-0").fill("Test it")
        page.locator("details.n-agent summary").nth(1).click()  # folded
        page.locator("#n-submit").click()
        page.wait_for_timeout(200)
        check(name, not team_posts() and page.inner_text("#n-error") == "Agent 2 needs a role."
              and page.evaluate("document.activeElement.id") == "n-role-1", page.inner_text("#n-error"))

    name = "new workflow: an agent with a role but no prompt, or a role another has, isn't sent; the cursor goes there"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-prompt").fill("Fix the login")
        page.locator("#n-team-count").fill("2")
        page.locator("#n-role-0").fill("tester")
        page.locator("#n-task-0").fill("Test it")
        page.locator("#n-role-1").fill("writer")
        page.locator("details.n-agent summary").nth(1).click()  # folded
        page.locator("#n-submit").click()
        page.wait_for_timeout(200)
        no_prompt = (page.inner_text("#n-error") == "Agent 2 needs a prompt."
                     and page.evaluate("document.activeElement.id") == "n-task-1")
        page.locator("#n-role-1").fill(" Tester ")
        page.locator("#n-task-1").fill("Test it again")
        page.locator("details.n-agent summary").nth(1).click()  # folded again
        page.locator("#n-submit").click()
        page.wait_for_timeout(200)
        same = (page.inner_text("#n-error") == 'Agents 1 and 2 are both "Tester"; give each its own role.'
                and page.evaluate("document.activeElement.id") == "n-role-1"
                and page.evaluate("document.querySelectorAll('.n-agent')[1].open"))
        check(name, not team_posts() and no_prompt and same, (no_prompt, page.inner_text("#n-error")))

    name = "new workflow: a team without the master's prompt isn't sent; the cursor goes to the prompt"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-prompt").fill("")
        page.locator("#n-team-count").fill("1")
        page.locator("#n-role-0").fill("tester")
        page.locator("#n-task-0").fill("Test it")
        page.locator("#n-submit").click()
        page.wait_for_timeout(200)
        check(name, not team_posts() and page.inner_text("#n-error") == "Say what the master should do."
              and page.evaluate("document.activeElement.id") == "n-prompt", page.inner_text("#n-error"))

    name = "new workflow: the models and efforts picked go with the team, and are back at Opus and Default after"
    with step(page, name):
        page.api.post_result = {"launchId": "t1", "name": "Fix the login", "agents": []}
        page.locator("#new-workflow").click()
        page.locator("#n-prompt").fill("Fix the login")
        page.locator("#n-team-count").fill("2")
        page.locator("#n-team-model").select_option("sonnet")
        page.locator("#n-team-effort").select_option("xhigh")
        for i in range(2):
            page.locator(f"#n-role-{i}").fill(f"r{i}")
            page.locator(f"#n-task-{i}").fill("y")
        page.locator("#n-model-1").select_option("haiku")
        page.locator("#n-effort-1").select_option("max")
        page.locator("#n-submit").click()
        page.wait_for_timeout(300)
        sent = team_posts()
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("1")
        again = [page.input_value(s) for s in ("#n-team-model", "#n-team-effort", "#n-model-0", "#n-effort-0")]
        check(name, sent and (sent[-1]["model"], sent[-1]["effort"]) == ("sonnet", "xhigh")
              and [(a["model"], a["effort"]) for a in sent[-1]["agents"]] == [("opus", ""), ("haiku", "max")]
              and again == ["opus", "", "opus", ""], (sent, again))

    name = "new workflow: with the master or an agent on Haiku in auto mode, the note says it may ask before it acts"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("1")
        says = lambda: "auto mode may not be available; the master or an agent on it then asks" in page.inner_text("#n-note")
        before = says()
        page.locator("#n-model-0").select_option("haiku")
        agent = says()
        page.locator("#n-model-0").select_option("opus")
        page.locator("#n-team-model").select_option("haiku")
        master = says()
        page.locator("#n-mode").select_option("acceptEdits")
        asks = says()
        page.locator("#n-mode").select_option("auto")
        page.locator("#n-team-model").select_option("opus")
        check(name, not before and agent and master and not asks and not says(), (before, agent, master, asks))

    name = "new workflow: images and Ultracode go with the team, and are cleared after"
    with step(page, name):
        page.evaluate("state.images = {}")
        page.api.post_result = {"launchId": "t1", "name": "Fix the login", "agents": []}
        page.locator("#new-workflow").click()
        page.locator("#n-prompt").fill("Fix the login")
        paste(page, "#n-prompt", "image/png")
        page.wait_for_timeout(200)
        page.locator("#n-ultra").check()
        page.locator("#n-team-count").fill("1")
        page.locator("#n-role-0").fill("tester")
        page.locator("#n-task-0").fill("Test it")
        page.locator("#n-submit").click()
        page.wait_for_timeout(300)
        page.locator("#new-workflow").click()
        sent = team_posts()
        check(name, sent and sent[-1]["images"] == [{"data": PNG_1PX}] and sent[-1]["ultracode"] is True
              and page.locator("#n-images .thumb").count() == 0 and not page.is_checked("#n-ultra"), sent)

    name = "new workflow: + stops at 8 agents, and a typed 12 reads 8"
    with step(page, name):
        page.locator("#new-workflow").click()
        for _ in range(9):
            if page.locator("#n-team-more").is_enabled():
                page.locator("#n-team-more").click()
        eight = sections().count() == 8 and page.locator("#n-team-more").is_disabled()
        page.locator("#n-team-count").fill("0")
        page.locator("#n-team-count").fill("12")
        page.locator("#n-prompt").focus()
        check(name, eight and sections().count() == 8 and page.input_value("#n-team-count") == "8", sections().count())

    name = "new workflow: clicking + again where it was adds another agent: the stepper stays under the pointer"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("0")
        page.locator("#n-prompt").focus()
        page.locator("#n-team-more").scroll_into_view_if_needed()
        box = page.locator("#n-team-more").bounding_box()
        for _ in range(3):
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(50)
        check(name, page.input_value("#n-team-count") == "3" and sections().count() == 3, page.input_value("#n-team-count"))

    name = "new workflow: a digit typed in the number replaces it; Enter there (or in a Role) doesn't start the team"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-prompt").fill("Fix the login")
        page.locator("#n-team-count").click()  # its middle: the cursor would land before the 0
        page.keyboard.type("3")
        three = sections().count() == 3 and page.input_value("#n-team-count") == "3"
        page.keyboard.type("2")
        page.keyboard.press("Enter")
        two = sections().count() == 2 and page.evaluate("document.querySelector('#chat-dialog').open")
        for i in range(2):
            page.locator(f"#n-role-{i}").fill(f"r{i}")
            page.locator(f"#n-task-{i}").fill("y")
        page.locator("#n-role-0").press("Enter")
        on = page.evaluate("document.activeElement.id")
        page.locator("#n-team-count").press("Enter")
        page.wait_for_timeout(200)
        check(name, three and two and on == "n-task-0" and not team_posts()
              and page.evaluate("document.querySelector('#chat-dialog').open"), (three, two, on, team_posts()))

    name = "new workflow: the keyboard focus stays in the stepper at 8 agents and at none"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-team-more").focus()
        for _ in range(8):
            page.keyboard.press("Space")
        at8 = page.evaluate("document.activeElement.id")
        page.locator("#n-team-less").focus()
        for _ in range(8):
            page.keyboard.press("Space")
        check(name, at8 == "n-team-count" and page.evaluate("document.activeElement.id") == "n-team-count"
              and sections().count() == 0, (at8, page.evaluate("document.activeElement.id")))

    name = ("new workflow: a folded section's title shows the role, the model and effort unless they are Opus and Default, "
            "and the start of its prompt")
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("1")
        page.locator("#n-role-0").fill("tester")
        page.locator("#n-task-0").fill("Test the login page\nthen the sign-up page")
        page.locator("details.n-agent summary").first.click()
        text = page.inner_text("details.n-agent summary >> nth=0")
        page.locator("details.n-agent summary").first.click()
        page.locator("#n-model-0").select_option("sonnet")
        page.locator("#n-effort-0").select_option("xhigh")
        page.locator("details.n-agent summary").first.click()
        picked = page.inner_text("details.n-agent summary >> nth=0")
        page.locator("details.n-agent summary").first.click()
        page.locator("#n-role-0").fill("")
        page.locator("#n-model-0").select_option("haiku")
        page.locator("#n-effort-0").select_option("")
        page.locator("details.n-agent summary").first.click()
        no_role = page.inner_text("details.n-agent summary >> nth=0")
        check(name, text.startswith("Agent 1 · tester") and "Opus" not in text and "Test the login page" in text
              and "sign-up" not in text and picked.startswith("Agent 1 · tester · on Sonnet, extra high effort")
              and no_role.startswith("Agent 1 · on Haiku") and "effort" not in no_role, (text, picked, no_role))

    name = "arrows: an arrow each way runs side by side between the two cards, each label clear of the other"
    with step(page, name):
        page.api.arrows = [{"id": "c2", "from": B, "to": A, "reason": "report", "status": "sent", "createdAt": 2,
                            "team": "alpha", "notes": {"from": {**NOTE, "enabled": False, "state": "skipped"},
                                                       "to": {**NOTE, "enabled": False, "state": "skipped"}}}]
        poll(page)
        spans = page.evaluate("[...document.querySelectorAll('#wire-layer .wire')].map(p => { const b = p.getBBox(); return [b.x, b.x + b.width]; })")
        boxes = [page.locator(f'.wire-label[data-id="{c}"]').bounding_box() for c in ("c1", "c2")]
        apart = boxes[0]["y"] + boxes[0]["height"] <= boxes[1]["y"] or boxes[1]["y"] + boxes[1]["height"] <= boxes[0]["y"]
        page.locator('.wire-label[data-id="c2"]').click()
        page.wait_for_function("!document.querySelector('#drawer').hidden")
        body = page.inner_text("#drawer-body")
        check(name, len(spans) == 2 and all(560 - 5 <= x0 and x1 <= 640 + 5 for x0, x1 in spans) and apart
              and "No notes" in body and "start the conversation" not in body, (spans, boxes))

    name = "arrows: an arrow each way between cards far apart on a row, or stacked, keeps its two labels apart"
    with step(page, name):
        pair = lambda i, a, b: [{"id": f"p{i}", "from": a, "to": b, "reason": "task", "status": "sent", "createdAt": 2,
                                 "notes": {"from": NOTE, "to": NOTE}},
                                {"id": f"q{i}", "from": b, "to": a, "reason": "report", "status": "sent", "createdAt": 2,
                                 "notes": {"from": NOTE, "to": NOTE}}]
        page.api.arrows = pair(1, C, E) + pair(2, A, C)  # gamma and epsilon 810 px apart on a row; alpha above gamma
        poll(page)
        clear = []
        for i in (1, 2):
            p, q = (page.locator(f'.wire-label[data-id="{c}{i}"]').bounding_box() for c in "pq")
            clear.append(p["y"] + p["height"] <= q["y"] or q["y"] + q["height"] <= p["y"]
                         or p["x"] + p["width"] <= q["x"] or q["x"] + q["width"] <= p["x"])
        check(name, all(clear), clear)

    name = "offline: a banner while the server doesn't answer, gone when it does"
    with step(page, name):
        page.api.down = True
        poll(page, 2)
        banner = is_open(page, "#offline")
        page.api.down = False
        poll(page)
        check(name, banner and not is_open(page, "#offline"))

    name = "offline: a bug while drawing the board isn't shown as the server being down"
    with step(page, name):
        page.evaluate("""() => { window.__render = render;
            render = () => { throw new TypeError("Cannot read properties of undefined (reading 'x')"); }; }""")
        try:
            poll(page, 3)
            notices = page.locator("#toasts .toast.error").count()
        finally:
            page.evaluate("() => { render = window.__render; state.drawError = null; }")
        check(name, not is_open(page, "#offline") and notices == 1)

    name = "boards: a late reply for the old board doesn't come back after a switch"
    with step(page, name):
        page.api.hold = {"b1"}
        page.evaluate("() => { poll(); selectBoard('b2'); }")
        page.wait_for_function("state.view?.board.id === 'b2'")
        for route, data in page.api.held:  # the old board's reply comes in now, late
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        page.wait_for_timeout(300)
        check(name, page.evaluate("state.view?.board.id") == "b2")

    def on_board(bid):
        page.evaluate(f"selectBoard('{bid}')")
        page.wait_for_function(f"state.view?.board.id === '{bid}' && document.querySelectorAll('.node').length === {5 if bid == 'b1' else 0}")

    def menu_rows():
        return page.evaluate("""[...document.querySelectorAll('#board-select-menu .menu-item')].map(r => r.innerText.replace(/\\s+/g, ' '))""")

    def menu_open():
        return page.evaluate("document.querySelector('#board-select-menu').matches(':popover-open')")

    on_board("b1")
    name = "board picker: a glass list of the boards, the current one ticked, and New board… under a divider, in light and dark"
    with step(page, name):
        page.locator("#board-select").click()
        page.wait_for_selector("#board-select-menu:popover-open")
        look = lambda: page.evaluate("""() => { const m = document.querySelector('#board-select-menu'), s = getComputedStyle(m);
            const rows = [...m.querySelectorAll('.menu-item')], last = rows[rows.length - 1];
            return { rows: rows.map(r => r.innerText.replace(/\\s+/g, ' ')), current: rows.map(r => r.classList.contains('current')),
                     divider: last.previousElementSibling.classList.contains('menu-sep'), native: document.querySelectorAll('select#board-select').length,
                     round: parseFloat(s.borderTopLeftRadius), blur: s.backdropFilter.includes('blur') || s.backdropFilter.startsWith('url('),
                     alpha: parseFloat(s.backgroundColor.split(',')[3]), tint: s.backgroundColor.match(/\\d+/g).slice(0, 3).join(' '),
                     lit: s.boxShadow.includes('inset'), expanded: document.querySelector('#board-select').getAttribute('aria-expanded'),
                     tip: rows[0].title }; }""")
        light = look()
        page.emulate_media(color_scheme="dark")
        try:
            dark = look()
        finally:
            page.emulate_media(color_scheme="light")
        check(name, light["rows"] == ["project board /home/you/project", "other /home/you/other", "New board…"]
              and light["current"] == [True, False, False] and light["divider"] and light["native"] == 0 and light["tip"] == FOLDER
              and light["expanded"] == "true" and all(v["round"] >= 16 and v["blur"] and 0 < v["alpha"] < 1 and v["lit"] for v in (light, dark))
              and light["tint"] != dark["tint"], (light, dark))

    name = "board picker: with transparency reduced, the same list is drawn solid"
    with step(page, name):
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]})
        try:
            page.locator("#board-select").click()
            page.wait_for_selector("#board-select-menu:popover-open")
            solid = page.evaluate("(s => [s.backgroundColor, s.backdropFilter])(getComputedStyle(document.querySelector('#board-select-menu')))")
        finally:
            cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "no-preference"}]})
        check(name, solid == ["rgb(255, 255, 255)", "none"], solid)

    name = "board picker: a click on a board switches to it; the current one only closes the list"
    with step(page, name):
        page.locator("#board-select").click()
        page.locator("#board-select-menu .menu-item", has_text="project board").click()
        same = page.evaluate("state.boardId") == "b1" and not menu_open()
        page.locator("#board-select").click()
        page.locator("#board-select-menu .menu-item", has_text="other").click()
        page.wait_for_function("state.view?.board.id === 'b2'")
        check(name, same and not menu_open() and page.inner_text("#board-select").replace("\n", " ") == "Board other"
              and page.evaluate("location.hash") == "#board=b2" and page.evaluate("document.querySelector('#board-select').getAttribute('aria-expanded')") == "false")
        on_board("b1")

    name = "board picker: ↓ opens it on the current board, ↑ ↓ move, Enter picks; Esc closes it and the details stay"
    with step(page, name):
        page.locator("#board-select").focus()
        page.keyboard.press("ArrowDown")
        page.wait_for_selector("#board-select-menu:popover-open")
        marked = lambda: page.evaluate("[...document.querySelectorAll('#board-select-menu .menu-item')].map(r => r.classList.contains('active'))")
        opened = marked()
        page.keyboard.press("ArrowDown")
        down = marked()
        page.keyboard.press("ArrowDown")  # on to New board…
        last = marked()
        page.keyboard.press("ArrowDown")  # and round to the first
        wrapped = marked()
        page.keyboard.press("ArrowUp")  # and back round to the last
        back = marked()
        page.keyboard.press("ArrowUp")
        up = marked()
        page.keyboard.press("Enter")
        page.wait_for_function("state.view?.board.id === 'b2'")
        shut = not menu_open() and page.evaluate("document.activeElement.id") == "board-select"
        on_board("b1")
        open_card(page, A)  # the details are open; Esc on the list closes the list alone
        page.locator("#board-select").focus()
        page.keyboard.press("Enter")
        page.wait_for_selector("#board-select-menu:popover-open")
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        esc = not menu_open() and is_open(page, "#drawer")
        page.keyboard.press("Escape")  # the next one closes the details, as before
        page.wait_for_timeout(100)
        check(name, opened == [True, False, False] and down == [False, True, False] and last == [False, False, True]
              and wrapped == [True, False, False] and back == last and up == down and shut and esc and not is_open(page, "#drawer"),
              (opened, down, last, wrapped, back, up, shut, esc))

    name = "board picker: a click elsewhere closes it, and so does the pill again"
    with step(page, name):
        page.locator("#board-select").click()
        page.wait_for_selector("#board-select-menu:popover-open")
        page.mouse.click(700, 600)  # the board
        page.wait_for_timeout(100)
        outside = not menu_open()
        page.locator("#board-select").click()
        page.wait_for_selector("#board-select-menu:popover-open")
        page.locator("#board-select").click()
        page.wait_for_timeout(100)
        check(name, outside and not menu_open())

    name = "board picker: a refresh while it is open leaves it as it is, and a new board shows in it"
    with step(page, name):
        page.locator("#board-select").click()
        page.wait_for_selector("#board-select-menu:popover-open")
        page.mouse.move(420, 120)
        page.evaluate("window.__swaps = 0; new MutationObserver(m => window.__swaps += m.length).observe(document.querySelector('#board-select-menu'), { childList: true, subtree: true })")
        poll(page, 3)
        same = page.evaluate("window.__swaps") == 0 and menu_open()
        BOARDS.append({"id": "b3", "title": "third", "folder": "/home/you/third"})
        try:
            poll(page)
            rows = menu_rows()
        finally:
            BOARDS.pop()
        poll(page)
        check(name, same and rows[:3] == ["project board /home/you/project", "other /home/you/other", "third /home/you/third"]
              and rows[-1] == "New board…" and menu_rows()[-1] == "New board…" and len(menu_rows()) == 3, (same, rows))

    name = "board picker: New board… opens the New board dialog, and the top bar's button still does"
    with step(page, name):
        page.locator("#board-select").click()
        page.locator("#board-select-menu .menu-item", has_text="New board…").click()
        page.wait_for_selector("#board-dialog[open]")
        first = not menu_open() and page.inner_text("#b-title") == "New board" and page.evaluate("document.activeElement.id") == "b-folder"
        page.locator("#board-dialog [data-close]").click()
        page.locator("#new-board").click()
        page.wait_for_selector("#board-dialog[open]")
        check(name, first and page.inner_text("#b-title") == "New board")

    name = "new board: when every folder with running chats has a board, the dialog says so and the list leaves them out"
    with step(page, name):
        page.locator("#new-board").click()
        page.wait_for_selector("#board-dialog[open]")
        page.wait_for_selector("#b-folder-list:not([hidden])")
        text = page.inner_text("#b-folder-list")
        check(name, page.locator("#b-folder-list .combo-item").count() == 0 and "Every folder with running chats already has a board" in text
              and page.inner_text("#b-suggest") == "", text)

    name = "new board: Create on a folder that has a board opens it and says so; on a new folder it opens the new board"
    with step(page, name):
        on_board("b2")
        page.api.new_board = "b1"
        page.locator("#new-board").click()
        page.wait_for_selector("#board-dialog[open]")
        page.fill("#b-folder", FOLDER)
        page.locator("#b-submit").click()
        page.wait_for_function("state.view?.board.id === 'b1'")
        said = "already has a board" in page.inner_text("#toasts")
        page.evaluate("document.querySelectorAll('#toasts .toast').forEach(t => t.remove())")
        page.api.new_board = "b3"
        page.locator("#new-board").click()
        page.wait_for_selector("#board-dialog[open]")
        page.fill("#b-folder", "/home/you/fresh")
        page.locator("#b-submit").click()
        page.wait_for_function("state.view?.board.id === 'b3'")
        check(name, said and "already has a board" not in page.inner_text("#toasts")
              and [b for p, b in page.api.posts if p == "/api/boards"] == [{"folder": FOLDER}, {"folder": "/home/you/fresh"}])
        on_board("b1")

    name = "new board: the list and the suggestions offer the folders that have no board yet"
    with step(page, name):
        kept = BOARDS[:]
        BOARDS[:] = kept[:1]  # only the project board: its folder has one, the other doesn't
        try:
            page.locator("#new-board").click()
            page.wait_for_selector("#board-dialog[open]")
            page.wait_for_selector("#b-folder-list:not([hidden])")
            listed = page.locator("#b-folder-list .combo-item").all_inner_texts()
            suggested = page.locator("#b-suggest .btn").all_inner_texts()
        finally:
            BOARDS[:] = kept
        check(name, listed == [OTHER] and suggested == [OTHER], (listed, suggested))

    # A title is drawn as our own small glass label, not the browser's square box (tips in app.js). While the
    # pointer or the focus is on an item the browser's title is off (or its box would show too); it is back after.
    name = "tooltips: a title shows as a small glass label after a short hover, centred under it with its exact words; the browser's own title is off meanwhile and back after"
    with step(page, name):
        park(page)
        words = title_of(page, "#fit-view")
        page.hover("#fit-view")
        page.wait_for_timeout(250)
        early = tip(page)["open"]
        off = title_of(page, "#fit-view")
        page.wait_for_selector("#tip:popover-open")
        shown, anchor = tip(page), page.locator("#fit-view").bounding_box()
        page.mouse.move(700, 700)
        page.wait_for_function("!document.querySelector('#tip').matches(':popover-open')")
        check(name, words == "Bring every card into view" and not early and off is None and shown["text"] == words
              and 4 <= shown["top"] - (anchor["y"] + anchor["height"]) <= 12
              and abs((shown["left"] + shown["right"]) / 2 - (anchor["x"] + anchor["width"] / 2)) <= 2
              and title_of(page, "#fit-view") == words, (words, early, off, shown, anchor))

    name = "tooltips: the label is glass like the notices and the Board list, in light and dark, never takes the pointer, and is solid with transparency reduced"
    with step(page, name):
        hover_tip(page, "#fit-view")
        look = lambda: page.evaluate("""() => { const s = getComputedStyle(document.querySelector('#tip'));
            return { blur: s.backdropFilter.includes('blur'), alpha: parseFloat(s.backgroundColor.split(',')[3]),
                     tint: s.backgroundColor.match(/\\d+/g).slice(0, 3).join(' '), round: parseFloat(s.borderTopLeftRadius),
                     lit: s.boxShadow.includes('inset'), size: s.fontSize, wide: parseFloat(s.maxWidth), pointer: s.pointerEvents,
                     open: document.querySelector('#tip').matches(':popover-open') }; }""")
        light = look()
        page.emulate_media(color_scheme="dark")
        try:
            dark = look()
        finally:
            page.emulate_media(color_scheme="light")
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]})
        try:
            solid = page.evaluate("(s => [s.backgroundColor, s.backdropFilter])(getComputedStyle(document.querySelector('#tip')))")
        finally:
            cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "no-preference"}]})
        check(name, all(v["open"] and v["blur"] and 0 < v["alpha"] < 1 and v["round"] >= 12 and v["lit"] and v["size"] == "12px"
                        and v["wide"] <= 260 and v["pointer"] == "none" for v in (light, dark))
              and light["tint"] != dark["tint"] and solid == ["rgb(255, 255, 255)", "none"], (light, dark, solid))

    name = "tooltips: the label hides when the pointer leaves, on a click, on Esc and on scrolling; the title is back once the pointer has left"
    with step(page, name):
        park(page)
        words = title_of(page, "#fit-view")
        gone = lambda: not tip(page)["open"]
        hover_tip(page, "#fit-view")
        page.mouse.move(700, 700)
        page.wait_for_timeout(50)
        left = gone() and title_of(page, "#fit-view") == words
        hover_tip(page, "#fit-view")
        page.keyboard.press("Escape")
        esc = gone()
        page.mouse.move(700, 700)
        hover_tip(page, "#fit-view")
        page.mouse.wheel(0, 60)
        page.wait_for_timeout(50)
        wheel = gone()
        page.mouse.move(700, 700)
        hover_tip(page, "#fit-view")
        page.locator("#fit-view").click()
        page.wait_for_timeout(50)
        clicked = gone() and title_of(page, "#fit-view") is None  # still on it: no label, and no browser box either
        page.mouse.move(700, 700)
        page.wait_for_timeout(50)
        check(name, left and esc and wheel and clicked and title_of(page, "#fit-view") == words, (left, esc, wheel, clicked))

    name = "tooltips: the label of a neighbour shows at once after one closes, but only after the delay when none has just closed"
    with step(page, name):
        hover_tip(page, "#fit-view")
        page.hover("#show-subagents")
        page.wait_for_timeout(120)
        quick = tip(page)
        page.mouse.move(700, 700)
        page.wait_for_timeout(450)
        page.hover("#fit-view")
        page.wait_for_timeout(250)
        slow = tip(page)["open"]
        check(name, quick["open"] and quick["text"].startswith("Show the subagents") and not slow, (quick, slow))

    name = "tooltips: near the window's right and bottom edges the label stays inside the window, above the item when there is no room below"
    with step(page, name):
        page.evaluate("""() => { const add = (id, css) => { const b = document.createElement('button'); b.id = id; b.textContent = 'Edge';
              b.title = 'A long explanation that wraps over a few lines, because it is a lot longer than a label may be.\\nWith a second line and a folder: /home/you/some/very/long/path/name';
              b.style.cssText = 'position: fixed; z-index: 50; ' + css; document.body.append(b); };
            add('edge-corner', 'right: 0; bottom: 0'); add('edge-right', 'right: 0; top: 300px'); add('edge-left', 'left: 0; top: 600px'); }""")
        try:
            seen = {}
            for edge in ("edge-corner", "edge-right", "edge-left"):
                seen[edge] = (hover_tip(page, f"#{edge}"), page.locator(f"#{edge}").bounding_box())
            wh = page.evaluate("[innerWidth, innerHeight]")
        finally:
            page.evaluate("document.querySelectorAll('[id^=edge-]').forEach(b => b.remove())")
        inside = all(t["left"] >= 7.5 and t["top"] >= 7.5 and t["right"] <= wh[0] - 7.5 and t["bottom"] <= wh[1] - 7.5 and t["right"] - t["left"] <= 260.5
                     for t, _ in seen.values())
        corner, right = seen["edge-corner"], seen["edge-right"]
        check(name, inside and corner[0]["bottom"] <= corner[1]["y"] and right[0]["top"] >= right[1]["y"] + right[1]["height"],
              (seen, wh))

    name = "tooltips: the label shows above an open dialog"
    with step(page, name):
        page.locator("#new-chat").click()
        page.wait_for_selector("#chat-dialog[open]")
        # the dialog painted one solid colour: whatever isn't that colour over it is above it
        page.evaluate("""() => { const d = document.querySelector('#chat-dialog');
            d.style.setProperty('background', 'rgb(255, 0, 0)', 'important'); d.style.setProperty('backdrop-filter', 'none', 'important'); }""")
        try:
            t = hover_tip(page, "#chat-dialog .btn.place >> nth=0")
            clip = {"x": t["left"] + 2, "y": t["top"] + 2, "width": t["right"] - t["left"] - 4, "height": t["bottom"] - t["top"] - 4}
            above = stray_share(page, clip)
            page.evaluate("document.querySelector('#tip').hidePopover()")
            bare = stray_share(page, clip)  # the same spot without the label: the dialog's own fields and words
        finally:
            page.evaluate("""() => { const d = document.querySelector('#chat-dialog');
                d.style.removeProperty('background'); d.style.removeProperty('backdrop-filter'); }""")
        check(name, t["open"] and above > 0.9 and above > bare + 0.5, (t, above, bare))

    name = "tooltips: Tab onto an item shows its label after the delay, and moving on hides it; the title is off meanwhile and back after"
    with step(page, name):
        park(page)
        words = title_of(page, "#new-workflow")
        page.focus("#new-chat")
        page.keyboard.press("Tab")
        on = page.evaluate("document.activeElement.id")
        early = tip(page)["open"]
        page.wait_for_selector("#tip:popover-open")
        shown, off = tip(page), title_of(page, "#new-workflow")
        page.keyboard.press("Tab")
        page.wait_for_function("!document.querySelector('#tip').matches(':popover-open')")
        check(name, on == "new-workflow" and not early and shown["text"] == words and off is None
              and title_of(page, "#new-workflow") == words, (on, early, shown, off))

    name = "tooltips: a title with a line break keeps it, on two lines"
    with step(page, name):
        t = hover_tip(page, f'.node[data-id="{A}"] .meta >> nth=0')
        check(name, t["text"].startswith("Address: @alpha\nFolder: ") and t["bottom"] - t["top"] > 40, t)

    name = "tooltips: polls while the pointer rests on an item in the details keep the label, rebuild nothing and let no browser title back"
    with step(page, name):
        open_card(page, A)
        page.evaluate("""() => { window.__swaps = 0; new MutationObserver(m => window.__swaps += m.length)
            .observe(document.querySelector('#drawer-body'), { childList: true, subtree: true }); }""")
        hover_tip(page, "#drawer .rename")
        poll(page, 3)
        inside, off = tip(page), title_of(page, "#drawer .rename")
        swaps = page.evaluate("window.__swaps")
        # the board's folder gets its title set again on every poll
        hover_tip(page, "#board-folder")
        poll(page, 2)
        folder, folder_off = tip(page), title_of(page, "#board-folder")
        check(name, inside["open"] and inside["text"] == "Rename (F2)" and off is None and swaps == 0
              and folder["open"] and folder["text"] == FOLDER and folder_off is None, (inside, off, swaps, folder, folder_off))

    name = "tooltips: an item redrawn under the pointer keeps the label, with no title stuck off, and has its title back once the pointer leaves"
    with step(page, name):
        open_card(page, A)
        hover_tip(page, "#drawer h3")
        page.api.patch = {A: {"title": "alpha two", "name": "alpha"}}  # its heading is redrawn with other words
        poll(page)
        redrawn = page.evaluate("document.querySelector('#drawer h3').textContent")
        during = tip(page), title_of(page, "#drawer h3")
        page.mouse.move(700, 700)
        page.wait_for_timeout(100)
        check(name, redrawn == "alpha two" and during[0]["open"] and during[0]["text"] == "Double-click to rename" and during[1] is None
              and not tip(page)["open"] and title_of(page, "#drawer h3") == "Double-click to rename", (redrawn, during))

    name = "tooltips: when the details close under the pointer, the label goes and the title is back"
    with step(page, name):
        open_card(page, A)
        hover_tip(page, "#drawer .rename")
        page.evaluate("closeDrawer()")
        page.wait_for_function("!document.querySelector('#tip').matches(':popover-open')", timeout=3000)
        check(name, title_of(page, "#drawer .rename") == "Rename (F2)")

    name = "tooltips: Esc still closes the details while a label shows"
    with step(page, name):
        open_card(page, A)
        hover_tip(page, "#drawer .rename")
        page.keyboard.press("Escape")
        page.wait_for_timeout(50)
        check(name, not is_open(page, "#drawer") and not tip(page)["open"])

    check("page: no script errors", not page.errors, "; ".join(page.errors))
    page.context.close()


def checks_narrow(browser):
    for w, h in ((390, 844), (800, 800)):
        page = open_page(browser, w, h)
        name = f"narrow {w} px: the details' close button can be clicked"
        with step(page, name):
            open_card(page, A)
            check(name, page.evaluate("""(() => { const r = document.querySelector('#drawer-close').getBoundingClientRect();
                return !!document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest('#drawer-close'); })()"""))
        name = f"narrow {w} px: nothing covers the details' title"
        with step(page, name):
            open_card(page, A)
            check(name, page.evaluate("""(() => { const r = document.querySelector('#drawer-body h3').getBoundingClientRect();
                return !!document.elementFromPoint(r.x + 8, r.y + r.height / 2)?.closest('#drawer'); })()"""))
        name = f"narrow {w} px: clicking + again where it was adds another agent"
        with step(page, name):
            page.locator("#new-workflow").click()
            page.locator("#n-team-more").scroll_into_view_if_needed()
            box = page.locator("#n-team-more").bounding_box()
            for _ in range(3):
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.wait_for_timeout(50)
            check(name, page.input_value("#n-team-count") == "3", page.input_value("#n-team-count"))
        name = f"narrow {w} px: an agent's model and effort sit " + ("under its role, clear of it" if w <= 600 else "level with its role")
        with step(page, name):
            page.locator("#new-workflow").click()
            page.locator("#n-team-count").fill("1")
            role, role_end, model_label, effort_label, model = page.evaluate("""(() => {
                const at = (s) => document.querySelector(s).getBoundingClientRect();
                return [at('#n-role-0').top, at('#n-role-0').bottom, at('label[for="n-model-0"]').top,
                        at('label[for="n-effort-0"]').top, at('#n-model-0').top]; })()""")
            check(name, effort_label == model_label and (model_label >= role_end + 8 if w <= 600 else abs(model - role) < 1),
                  (role, role_end, model_label, effort_label, model))
        name = f"narrow {w} px: the top bar's New board button can be clicked" + (" with the details open" if w == 800 else "")
        with step(page, name):
            if w == 800:  # at phone width the details cover the top bar like a sheet
                open_card(page, A)
            page.locator("#new-board").click()  # fails if anything covers it
            page.wait_for_selector("#board-dialog[open]")
            check(name, True)
        name = f"narrow {w} px: the Board picker's list" + (" opens over the details, with New board… in reach" if w == 800 else " stays on the screen")
        with step(page, name):
            if w == 800:
                open_card(page, A)
            page.locator("#board-select").click()
            page.wait_for_selector("#board-select-menu:popover-open")
            box = page.evaluate("""(() => { const m = document.querySelector('#board-select-menu').getBoundingClientRect();
                const r = document.querySelector('#board-select-menu .menu-item.action').getBoundingClientRect();
                return [m.left >= 0 && m.right <= innerWidth && m.bottom <= innerHeight,
                        !!document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest('.menu-item.action')]; })()""")
            check(name, box == [True, True], box)
        name = f"narrow {w} px: no sideways scrolling"
        with step(page, name):
            check(name, page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        name = f"narrow {w} px: in Add agents a long name ends in … and a sleeping agent's − and + stay whole, inside the sidebar"
        with step(page, name):
            long = not_on_board("6", "a sleeping background agent with a name far too long for the sidebar", jobId="0a5ee006", **ASLEEP_BG)
            page.api.avail = [long]
            poll(page)
            page.hover(avail_row(long) + " .name")
            fades_done(page, avail_row(long) + " .del")  # the − fades in
            look = page.evaluate("""(sel) => { const r = document.querySelector(sel), n = r.querySelector('.name');
                const side = document.querySelector('.sidebar').getBoundingClientRect(), box = (s) => r.querySelector(s).getBoundingClientRect();
                return { cut: n.clientWidth > 0 && n.scrollWidth > n.clientWidth && getComputedStyle(n).textOverflow === 'ellipsis',
                         whole: [box('.del'), box('.add')].every(b => b.width === 26 && b.height === 26 && b.left >= side.left && b.right <= side.right),
                         shown: getComputedStyle(r.querySelector('.del')).opacity === '1' }; }""", avail_row(long))
            check(name, all(look.values()), look)
        # a workflow card too narrow for its state's word, name and numbers shows the state by its icon alone
        name = f"narrow {w} px: a workflow card's state badge " + ("shows by its icon alone" if w == 800 else "keeps its word")
        with step(page, name):
            open_agents(page, A)
            word = page.evaluate("""(() => { const e = document.querySelector('#agents-pop .run-line .state-word');
                return [getComputedStyle(e).display, Math.round(e.closest('details.run').getBoundingClientRect().width)]; })()""")
            check(name, (word[0] == "none") == (w == 800), word)
        # the agents pop-up: its list and the details beside it, or (too narrow for both) one at a time
        side_by_side = w > 720
        name = f"narrow {w} px: the agents pop-up shows " + ("its list and details side by side" if side_by_side
                                                            else "the list, then the agent picked, and ‹ All agents goes back")
        with step(page, name):
            open_agents(page, A)
            list_in, detail_in = (lambda: is_open(page, "#agents-pop-list")), (lambda: is_open(page, "#agents-pop-detail"))
            if side_by_side:
                check(name, list_in() and detail_in())
            else:
                list_first = list_in() and not detail_in()
                page.locator("#agents-pop .agent-row", has_text="verify:app.js").click()
                detail_then = detail_in() and not list_in() and "verify:app.js" in page.inner_text("#agents-pop-detail h3")
                back = page.locator("#agents-pop-detail .back")
                chevron = back.evaluate("e => getComputedStyle(e, '::before').backgroundImage.startsWith('url(')")
                words = back.inner_text()
                back.click()
                check(name, list_first and detail_then and list_in() and not detail_in() and chevron and words == "All agents",
                      (chevron, words))
        page.context.close()
    # On a touch screen nothing hovers: a sleeping background agent's − shows all the time.
    name = "touch screen: a sleeping background agent's − shows without a pointer on its row"
    touch = open_page(browser, 390, 844, has_touch=True)
    with step(touch, name):
        touch.api.avail = [SLEEPY]
        poll(touch)
        flips = touch.evaluate("matchMedia('(hover: none)').matches")
        shown = touch.evaluate(f"getComputedStyle(document.querySelector('{avail_row(SLEEPY)} .del')).opacity")
        rule = touch.evaluate("""() => [...document.styleSheets].flatMap(s => [...s.cssRules]).some(r => r.conditionText === '(hover: none)'
            && [...r.cssRules].some(x => x.selectorText === '.avail-row .btn.del' && x.style.opacity === '1'))""")
        check(name, shown == "1" if flips else rule, (flips, shown, rule))  # without touch emulation, the rule at least
    touch.context.close()


def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # no browser installed, or it can't start here
            print(f"page checks skipped: the browser didn't start ({str(e).splitlines()[0]})")
            return 2
        for group in (checks_wide, checks_narrow):
            try:
                group(browser)
            except Exception as e:  # the page itself didn't load
                check(f"{group.__name__}: the page loads", False, str(e).splitlines()[0])
        browser.close()
    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"{'ok  ' if ok else 'FAIL'} {name}{f'  ({detail})' if detail and not ok else ''}")
    print(f"page checks: {len(results) - len(failed)} of {len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
