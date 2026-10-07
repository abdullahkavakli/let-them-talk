#!/usr/bin/env python3
"""Checks the page (static/) in a headless browser against a made-up board.

Every /api reply is faked here: no server, no sessions and no personal data are
involved, and nothing the page tries to send goes anywhere. Each check is
something that broke once (see the git log); a check that fails names it.

Run it with the venv from tests/setup.sh:  tests/.venv/bin/python tests/check_page.py
LTT_STATIC=<folder> checks another copy of static/ (e.g. an older one).
Exit 0: all passed. 1: a check failed. 2: the browser couldn't run (skipped).
"""
import json
import os
import sys
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
        self.suggest = None     # alpha's suggested reply

    def chat(self, sid):
        self.asked += 1
        msgs = [{"id": "u1", "role": "user", "at": 1, "text": "Fix the tests", "done": True},
                {"id": "r1", "role": "claude", "at": 2, "done": True,
                 "text": "## Done\n- **All green** now\n- ran `npm test`\n\n| a | b |\n|---|---|\n| 1 | 2 |"}]
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
            return route.fulfill(status=self.post_status, content_type="application/json", body=json.dumps(body))
        if path == "/api/state":
            if "board" not in q:
                data = {"boards": BOARDS, "folders": [FOLDER, OTHER], "places": [{"label": "Home", "path": "/home/you"}]}
            elif q["board"] in self.hold:
                return self.held.append((route, view(q["board"])))
            else:
                data = view(q["board"])
        elif path == "/api/chat":
            data = self.chat(q.get("session"))
        elif path == "/api/agents":
            data = {"sessionId": q.get("session"), "live": True, "direct": [], "workflows": []}
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
        name = f"narrow {w} px: no sideways scrolling"
        with step(page, name):
            check(name, page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
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
