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
         "agentStateText": None, "x": x, "y": y}
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
        card(B, "beta", 640, 120, agentState="blocked", agentStateText="needs you", status="waiting",
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
    a, run = next(x for x in flat if x[0]["id"] == aid)
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
        self.posts = []
        self.asked = 0
        self.ultracode = None   # what the server reads off a running background agent
        self.checking = False   # it is looking in that agent's /effort panel
        self.suggest = None     # alpha's suggested reply
        self.arrows = []        # more arrows on the project board
        self.agents = None      # every chat's agents (like AGENTS above); none by default

    def chat(self, sid):
        self.asked += 1
        msgs = [{"id": "u1", "role": "user", "at": 1, "text": "Fix the tests", "done": True},
                {"id": "r1", "role": "claude", "at": 2, "done": True,
                 "text": "## Done\n- **All green** now\n- ran `npm test`\n\n| a | b |\n|---|---|\n| 1 | 2 |"}]
        return {"sessionId": sid, "messages": msgs, "asking": None, "plan": None, "queued": [],
                "suggest": {"text": self.suggest} if self.suggest and sid == A else None,
                "working": self.vary and sid == A, "doing": f"Step {self.asked}" if self.vary else None,
                "ultracode": self.ultracode if sid == B else None, "ultracodeChecking": self.checking and sid == B}

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
            return route.fulfill(status=self.post_status, content_type="application/json", body=json.dumps(body))
        if path == "/api/state":
            if "board" not in q:
                data = {"boards": BOARDS, "folders": [FOLDER, OTHER], "places": [{"label": "Home", "path": "/home/you"}]}
            elif q["board"] in self.hold:
                return self.held.append((route, view(q["board"])))
            else:
                data = view(q["board"])
                data["board"]["connections"] += self.arrows if q["board"] == "b1" else []
        elif path == "/api/chat":
            data = self.chat(q.get("session"))
        elif path == "/api/agents":
            data = self.agents or {"sessionId": q.get("session"), "live": True, "direct": [], "workflows": []}
        elif path == "/api/subagent":
            data = subagent(self.agents, q.get("agent")) if self.agents else {
                "id": q.get("agent"), "sessionId": q.get("session"), "label": "Fable judge", "kind": "general-purpose",
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


def open_page(browser, width=1440, height=900, scheme="light"):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
    page = ctx.new_page()
    page.set_default_timeout(5000)
    page.api = FakeAPI()
    page.errors, page.dialogs = [], []
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


def open_agents(page, sid=B, agents=None):
    """A chat's details with the made-up agents (AGENTS, or the ones given), then the pop-up that lists them."""
    page.api.agents = copy.deepcopy(agents or AGENTS)
    open_card(page, sid)
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
        page.locator("#drawer-body button", has_text="End agent").click()  # the confirm is accepted
        page.wait_for_timeout(200)
        sent = [b for p, b in page.api.posts if p.endswith("/agent-end")]
        check(name, ended == 0 and "confirm" in page.dialogs and sent == [{"jobId": "abcdef12"}])

    name = "details: Open in IDE ends a running background agent only after a yes, an asleep one isn't asked"
    with step(page, name):
        asked = len(page.dialogs)
        open_card(page, C)  # gamma: its process ended
        page.locator("#drawer-body button", has_text="Open in IDE").click()
        page.wait_for_timeout(200)
        quiet = len(page.dialogs) == asked
        open_card(page, B)  # beta: running; the confirm is accepted
        page.locator("#drawer-body button", has_text="Open in IDE").click()
        page.wait_for_timeout(200)
        sent = [(b["sessionId"], b["end"]) for p, b in page.api.posts if p.endswith("/open-folder")]
        check(name, quiet and page.dialogs[asked:] == ["confirm"] and sent == [(C, False), (B, True)], sent)

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
        check(name, msg == [{"sessionId": B, "agentId": "a1b2c3", "label": "Fable judge", "text": "stop and report"}]
              and att and att[-1].get("jobId") == "abcdef12" and "Open in terminal" not in term
              and "terminal window" in term and ended, (msg, att, ended))
        page.evaluate("state.outbox = {}")

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

    name = "ultracode: a running agent shows its state with the one button that changes it, and asks the server"
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
              and "Ultracode on (this session only)" in page.inner_text("#toasts"), (shown, sent))

    name = "ultracode: unknown shows both buttons; a stopped agent has none"
    with step(page, name):
        open_card(page, B)
        both = page.locator("#drawer-body .ultracode button").all_inner_texts()
        open_card(page, C)
        check(name, both == ["Turn on", "Turn off"] and page.locator("#drawer-body .ultracode").count() == 0
              and "while it runs" in page.inner_text("#drawer-body"), both)

    name = "ultracode: while the app looks in its /effort panel, the line says checking and the buttons wait"
    with step(page, name):
        page.api.checking = True
        open_card(page, B)
        row = page.locator("#drawer-body .ultracode")
        shown, waiting = row.inner_text(), row.locator("button:disabled").count()
        said = "opens /effort in it and closes it again" in page.inner_text("#drawer-body")
        page.api.checking, page.api.ultracode = False, True
        poll(page)
        check(name, "Ultracode: checking…" in shown and waiting == 2 and said
              and row.inner_text().startswith("Ultracode is on") and row.locator("button:enabled").all_inner_texts() == ["Turn off"],
              (shown, waiting, said, row.inner_text()))

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
        side, main = page.locator("#agents-pop-list").bounding_box(), page.locator("#agents-pop-detail").bounding_box()
        check(name, first == "review:perf" and before == rows.count() == 7 and is_open(page, "#agents-pop-list")
              and main["x"] >= side["x"] + side["width"] - 1 and picked_agent(page) == "verify:app.js"
              and "Failed" in page.inner_text("#agents-pop-detail"), (first, before, side, main))

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
        page.wait_for_timeout(100)
        check(name, (start, down, up, end) == ("review:perf", "review:security", "review:perf", "Find the old marker")
              and keys == ["verify:app.js", "review:bugs"] and not page.evaluate("document.querySelector('#agents-pop').open"),
              (start, down, up, end, keys))

    name = "agents: Tab, and ↑ ↓ from a card's header, reach a row in view, with the picked agent's card folded too"
    with step(page, name):
        open_agents(page)
        page.locator("#agents-pop details.run > summary").first.click()  # folds review-changes, which holds the pick
        page.wait_for_timeout(200)
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

    name = "agents: a card folded earlier unfolds for the running agent the pop-up opens on, and the keyboard is there"
    with step(page, name):
        page.api.agents = copy.deepcopy(AGENTS)
        open_card(page, B)
        page.evaluate("state.runOpen = { r1: false }")
        page.locator("#drawer-body .agents-line").click()
        page.wait_for_selector("#agents-pop[open] .agent-row")
        page.wait_for_timeout(100)
        check(name, page.evaluate("document.querySelector('#agents-pop details.run').open")
              and page.evaluate("document.activeElement.id") == "agent-row-a2")

    name = "agents: with nothing running the pop-up opens on an empty details pane, and a row fills it"
    with step(page, name):
        quiet = copy.deepcopy(AGENTS)
        for a in [x for r in quiet["workflows"] for x in r["agents"]] + quiet["direct"]:
            a["state"] = "done" if a["state"] == "running" else a["state"]
        quiet["workflows"][0]["status"] = "completed"
        open_agents(page, agents=quiet)
        empty = page.locator("#agents-pop-detail .pop-empty").count() == 1 and not page.locator("#agents-pop .agent-row[aria-current]").count()
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
        page.wait_for_timeout(300)
        row = page.evaluate("document.activeElement.id")
        page.locator("#agents-pop details.run > summary").first.focus()
        page.api.agents["workflows"][0]["agents"][2]["state"] = "done"  # the card's count changes again
        poll(page, 2)
        page.wait_for_timeout(300)
        check(name, before == "agent-row-a3" == row and page.evaluate("document.activeElement.id") == "fold-r1", (before, row))

    name = "agents: a clock that ticks changes in place, so the list isn't rebuilt under the pointer and keyboard"
    with step(page, name):
        open_agents(page)
        page.evaluate("""() => { window.__swaps = 0; new MutationObserver(m => window.__swaps += m.length)
            .observe(document.querySelector('#agents-pop-list'), { childList: true }); }""")
        time = page.locator("#agents-pop .agent-row", has_text="review:security").locator(".agent-time")
        before = time.inner_text()
        page.api.agents["workflows"][0]["agents"][2]["durationMs"] += 7000  # the next polls show it longer
        poll(page, 2)
        page.wait_for_timeout(300)
        check(name, time.inner_text() != before and page.evaluate("window.__swaps") == 0, (before, time.inner_text()))

    name = "agents: a row has a hover fill, and a focus ring from the keyboard, so it's plain it can be clicked"
    with step(page, name):
        open_agents(page)
        row = page.locator("#agents-pop .agent-row", has_text="review:bugs")
        fill = lambda: row.evaluate("e => getComputedStyle(e).backgroundColor")
        idle = fill()
        row.hover()
        page.wait_for_timeout(300)
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
        page.wait_for_timeout(300)
        sent = [b for p, b in page.api.posts if p.endswith("/send")]
        check(name, card.locator(".run-count").inner_text() == "1 of 5 done · 1 failed" and bar == "20%"
              and card.locator("summary .state-badge").inner_text() == "Running" and card.get_attribute("open") is not None
              and card.locator("summary .run-action").inner_text() == "Ask to stop"
              and len(sent) == 1 and "stop the workflow" in sent[0]["text"] and "Asked beta." in page.inner_text("#toasts"),
              (bar, sent))

    name = "agents: \"Started by\" is a chip in the app's style, not the browser's blue underlined link"
    with step(page, name):
        open_agents(page)
        chip = page.locator("#agents-pop-detail .chip.link")
        look = chip.evaluate("e => { const s = getComputedStyle(e); return [e.tagName, s.textDecorationLine, s.color, e.textContent]; }")
        chip.click()
        page.wait_for_timeout(100)
        check(name, look[0] == "BUTTON" and look[1] == "none" and look[2] != "rgb(0, 0, 238)" and look[3] == "beta"
              and not page.evaluate("document.querySelector('#agents-pop').open") and is_open(page, "#drawer"), look)

    name = "folds: no browser marker is left on any fold, and each chevron is the same drawn one"
    with step(page, name):
        open_agents(page)
        marks = """() => [...document.querySelectorAll('summary')].map(s => { const c = getComputedStyle(s), b = getComputedStyle(s, '::before');
            return [c.display === 'list-item' || c.listStyleType !== 'none', b.width, b.height, b.backgroundImage.startsWith('url(')]; })"""
        found = page.evaluate(marks)  # the chat's status line and Connections, the sidebar's Activity, the pop-up's cards
        page.evaluate("openWirePop('c1')")  # an arrow's notes fold
        found += page.evaluate(marks)
        text = page.inner_text("body")
        check(name, len(found) >= 8 and not any(m[0] for m in found) and {tuple(m[1:]) for m in found} == {("12px", "12px", True)}
              and "▸" not in text and "▾" not in text, found)

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

    name = "dropdowns: still native selects, drawn as the app's fields with its chevron and a focus ring"
    with step(page, name):
        looks = page.evaluate("""() => ['board-select', 'ide-pick', 'n-editor', 'n-model'].map(id => { const e = document.getElementById(id), s = getComputedStyle(e);
            return [e.tagName, s.appearance, s.backgroundImage.startsWith('url(')]; })""")
        page.locator("#new-chat").focus()
        page.keyboard.press("Shift+Tab")  # back to the Board picker, from the keyboard
        ring = page.evaluate("[document.activeElement.id, getComputedStyle(document.activeElement).boxShadow]")
        check(name, looks == [["SELECT", "none", True]] * 4 and ring[0] == "board-select" and ring[1] != "none", (looks, ring))

    name = "details: buttons in a chat's rows are one height, and the four of Background agent sit in two even columns"
    with step(page, name):
        open_card(page, B)
        rows = page.evaluate("""() => [...document.querySelectorAll('#drawer-body .drawer-actions:not(.ultracode)')].map(r =>
            [...r.querySelectorAll('.btn')].map(b => { const k = b.getBoundingClientRect(); return [Math.round(k.left), Math.round(k.width), Math.round(k.height)]; }))""")
        every, bg = [b for r in rows for b in r], rows[0]
        check(name, len({h for _, _, h in every}) == 1 and len(bg) == 4 and len({w for _, w, _ in bg}) == 1
              and len({x for x, _, _ in bg}) == 2, rows)

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

    name = "failures: a failed Disconnect leaves a notice and the details open, no alert()"
    with step(page, name):
        page.api.post_status = 500
        page.locator(".wire-label").first.click()
        page.wait_for_function("!document.querySelector('#drawer').hidden")
        page.get_by_role("button", name="Disconnect").click()
        page.wait_for_timeout(400)
        check(name, page.locator("#toasts .toast.error").count() == 1 and is_open(page, "#drawer")
              and "alert" not in page.dialogs)

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

    name = "new workflow: what you type in a section stays when the number changes; its title shows the role"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("3")
        page.locator("#n-role-0").fill("tester")
        page.locator("#n-task-0").fill("Test the login page")
        page.locator("#n-role-1").fill("writer")
        page.locator("#n-team-count").fill("1")
        one = sections().count() == 1 and page.input_value("#n-task-0") == "Test the login page"
        page.locator("#n-team-less").click()
        page.locator("#n-team-more").click()
        page.locator("#n-team-more").click()
        check(name, one and sections().count() == 2 and page.input_value("#n-role-0") == "tester"
              and page.input_value("#n-role-1") == "writer"
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

    name = "new workflow: with agents it sends the team (your prompt, each role and prompt), then starts clean"
    with step(page, name):
        page.api.post_result = {"launchId": "t1", "name": "Fix the login", "agents": []}
        page.locator("#new-workflow").click()
        page.locator("#n-prompt").fill("Fix the login")
        page.locator("#n-team-count").fill("2")
        for i, (role, task) in enumerate((("tester", "Test it"), ("writer", "Document it"))):
            page.locator(f"#n-role-{i}").fill(f" {role} ")
            page.locator(f"#n-task-{i}").fill(task)
        page.locator("#n-submit").click()
        page.wait_for_timeout(300)
        closed = not page.evaluate("document.querySelector('#chat-dialog').open")
        page.locator("#new-workflow").click()
        check(name, team_posts() == [{"prompt": "Fix the login", "images": [], "folder": FOLDER, "name": "",
                                      "permissionMode": "auto", "ultracode": False,
                                      "agents": [{"role": "tester", "prompt": "Test it"},
                                                 {"role": "writer", "prompt": "Document it"}]}]
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

    name = "new workflow: a folded section's title shows the role and the start of its prompt"
    with step(page, name):
        page.locator("#new-workflow").click()
        page.locator("#n-team-count").fill("1")
        page.locator("#n-role-0").fill("tester")
        page.locator("#n-task-0").fill("Test the login page\nthen the sign-up page")
        page.locator("details.n-agent summary").first.click()
        text = page.inner_text("details.n-agent summary >> nth=0")
        check(name, "Agent 1 · tester" in text and "Test the login page" in text and "sign-up" not in text, text)

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
        name = f"narrow {w} px: no sideways scrolling"
        with step(page, name):
            check(name, page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        # the agents pop-up: its list and the details beside it, or (too narrow for both) one at a time
        side_by_side = w > 720
        name = f"narrow {w} px: the agents pop-up shows " + ("its list and details side by side" if side_by_side
                                                            else "the list, then the agent picked, and ← All agents goes back")
        with step(page, name):
            open_agents(page, A)
            list_in, detail_in = (lambda: is_open(page, "#agents-pop-list")), (lambda: is_open(page, "#agents-pop-detail"))
            if side_by_side:
                check(name, list_in() and detail_in())
            else:
                list_first = list_in() and not detail_in()
                page.locator("#agents-pop .agent-row", has_text="verify:app.js").click()
                detail_then = detail_in() and not list_in() and "verify:app.js" in page.inner_text("#agents-pop-detail h3")
                page.locator("#agents-pop-detail .back").click()
                check(name, list_first and detail_then and list_in() and not detail_in())
        page.context.close()


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
