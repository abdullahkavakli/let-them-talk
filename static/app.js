"use strict";

const POLL_MS = 2500;
const NODE_W = 220;
const DOUBLE_CLICK_MS = 500;  // two clicks on a card this close together rename it
const $ = (sel) => document.querySelector(sel);

const state = {
  boardId: null,
  view: null,            // last /api/state?board= response
  pan: { x: 0, y: 0 },
  localPos: {},          // sessionId -> {x, y} while a drag is unsaved
  selected: null,        // {type: "node" | "wire", id}
  drag: null,            // node drag or canvas pan in progress
  connecting: null,      // {from, click} while drawing an arrow
  pollTimer: null,
  agents: {},            // sessionId -> /api/agents response for the open drawer
  chat: {},              // sessionId -> /api/chat response for the open drawer
  runOpen: {},           // runId (or "direct:<sid>") -> expanded in the drawer
  chatOpen: {},          // message id -> shown in full in the drawer
  talk: {},              // arrow id -> /api/talk response (what its two chats sent each other)
  talkBusy: {},          // arrow id -> a /api/talk request is in flight
  talkLimit: {},         // arrow id -> how many messages to load ("Show earlier" raises it)
  notifyOff: {},         // arrow id -> "Tell both agents" unticked (kept across redraws)
  removeNotifyOff: {},   // sessionId -> "Tell connected agents" unticked (kept across redraws)
  showSubs: store("ltt.subagents") === true,  // running subagents drawn on the board
  subSpot: {},           // sessionId -> where its subagents sat, relative to its card
  subInfo: {},           // "sessionId:agentId" -> /api/subagent response for the open drawer
  subAll: {},            // sessionId -> all its subagents shown, not just the first five
  renaming: null,        // sessionId whose name is being edited in the drawer
  renameDraft: "",       // what is typed there (kept across redraws)
  lastClick: null,       // {id, at}: the last click on a card, to tell a double-click
};

// ------------------------------------------------------------------ helpers

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false && c !== "") node.append(c);
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Let-Them-Talk": "1" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// Saved UI state lives under "ltt."; values saved by earlier versions under
// "organizer." are still read.
function store(key, value) {
  try {
    if (value !== undefined) return localStorage.setItem(key, JSON.stringify(value));
    let raw = localStorage.getItem(key);
    if (raw === null && key.startsWith("ltt.")) raw = localStorage.getItem(`organizer.${key.slice(4)}`);
    return JSON.parse(raw);
  } catch { return null; }
}

const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
// The time, with the date in front when it isn't today (conversations span days).
const when = (t) => new Date(t * 1000).toDateString() === new Date().toDateString() ? clock(t)
  : `${new Date(t * 1000).toLocaleDateString([], { month: "short", day: "numeric" })} ${clock(t)}`;
const folderName = (cwd) => (cwd || "").replace(/\/+$/, "").split("/").pop() || cwd || "?";
// A path as one span per folder name (with its slash), kept together by CSS,
// so a long path wraps between folder names, never inside one.
const pathNodes = (path) => (String(path || "").match(/[^/\\]*[/\\]|[^/\\]+$/g) || [])
  .map((part) => el("span", { class: "seg", text: part }));
// The server reads the editor (Cursor, VS Code, ...) from the claude binary's path.
// A background agent shown in a terminal (or editor) says so; see shownIn in server.py.
const opener = (n) => n.background ? n.shownIn || "Background" : n.editor ||
  ({ "claude-vscode": "Editor", cli: "Terminal", "sdk-cli": "Headless" }[n.entrypoint] || n.entrypoint || "");
const hostLabel = () => state.view?.host || "WSL";
// Status of a card: busy/idle for chats; a background agent's own state.
const BG_DOT = { working: "busy", blocked: "needs", done: "idle", stopped: "ended", failed: "failed" };
function cardStatus(n) {
  if (!n.live) return { dot: "ended", text: "ended" };
  if (n.background && n.resumable === false) return { dot: "ended", text: "needs restart" };
  if (n.background) return { dot: BG_DOT[n.agentState] || (n.running ? n.status : "ended"),
    text: n.agentStateText || (n.running ? n.status : "asleep") };
  return { dot: n.status, text: n.status };
}
// Cards show the name you gave them on this board, else the title Claude
// Code gave the session; @name is its address.
const display = (n) => n.alias || n.title || (n.name ? `@${n.name}` : `session ${n.sessionId.slice(0, 8)}`);
const where = (n) => n.winCwd || n.cwd;  // Windows sessions keep their C:\ path
const onWindows = (n) => n.platform === "windows";
const nodeById = (id) => state.view?.nodes.find((n) => n.sessionId === id);
const connById = (id) => state.view?.board.connections.find((c) => c.id === id);

function nodePos(n) {
  return state.localPos[n.sessionId] || { x: n.x, y: n.y };
}

function toWorld(evt) {
  const r = $("#canvas").getBoundingClientRect();
  return { x: (evt.clientX - r.left - state.pan.x) / state.zoom, y: (evt.clientY - r.top - state.pan.y) / state.zoom };
}

// The board's view: pan in screen pixels, then zoom (the mouse wheel; see the
// wheel handler), both remembered per board.
const ZOOM_MIN = 0.25, ZOOM_MAX = 1.5;
function applyView() {
  $("#world").style.transform = `translate(${state.pan.x}px, ${state.pan.y}px) scale(${state.zoom})`;
}
function saveView() {
  store(`ltt.pan.${state.boardId}`, state.pan);
  store(`ltt.zoom.${state.boardId}`, state.zoom);
}

// Same wording as who()/default_notes() in server.py, so the preview is what gets sent.
const who = (s) => s.title
  ? `"${s.title}" (@${s.name}, folder: ${s.cwd})`
  : `@${s.name} (folder: ${s.cwd})`;

function defaultNotes(src, dst, reason, tellSrc = true) {
  const why = reason.trim();
  if (!why) {
    // No reason is fine: then the point is that each knows what the other is doing.
    const start = (other) => `Start now: send @${other.name} what you are doing, in a few lines, with ` +
      `SendMessage. No reply to Let Them Talk is needed.`;
    return {
      from: `[Let Them Talk] Your user wants you and ${who(dst)} to know what each other is doing.\n` + start(dst),
      to: `[Let Them Talk] Your user wants you and ${who(src)} to know what each other is doing.\n` + (tellSrc
        ? `@${src.name} will send you what it is doing. When it does, send @${src.name} what you are ` +
          `doing, in a few lines, with SendMessage. No reply to Let Them Talk is needed.`
        : start(src)),
    };
  }
  const whyLine = `Why: ${why}\n`;
  const start = (other) => `Start now: send @${other.name} your current view on this with ` +
    `SendMessage, then reply when it answers. No reply to Let Them Talk is needed.`;
  return {
    from: `[Let Them Talk] Your user connected you to ${who(dst)} and wants you two to talk.\n` +
      whyLine + start(dst),
    to: `[Let Them Talk] Your user connected ${who(src)} to you and wants you two to talk.\n` +
      whyLine + (tellSrc
        ? `@${src.name} will message you about this. When it does, reply to @${src.name} ` +
          `with SendMessage. No reply to Let Them Talk is needed.`
        : start(src)),
  };
}

// ------------------------------------------------------------------- boards

async function start() {
  const data = await api("/api/state");
  const wanted = new URLSearchParams(location.hash.slice(1)).get("board") || store("ltt.board");
  const ids = data.boards.map((b) => b.id);
  if (ids.length === 0) {
    fillBoardSelect([]);
    openBoardDialog(data.folders, [], data.places);
    return;
  }
  selectBoard(ids.includes(wanted) ? wanted : ids[0]);
}

function fillBoardSelect(boards) {
  const sel = $("#board-select");
  sel.replaceChildren(...boards.map((b) =>
    el("option", { value: b.id, text: b.title, title: b.folder, selected: b.id === state.boardId })));
  sel.disabled = boards.length === 0;
}

function selectBoard(id) {
  state.boardId = id;
  state.selected = null;
  state.localPos = {};
  state.pan = store(`ltt.pan.${id}`) || { x: 0, y: 0 };
  state.zoom = store(`ltt.zoom.${id}`) || 1;
  state.fitPending = true;  // re-center once if the saved pan hides every card
  store("ltt.board", id);
  history.replaceState(null, "", `#board=${id}`);
  closeDrawer();
  poll();
}

async function poll() {
  clearTimeout(state.pollTimer);
  if (state.boardId) {
    try {
      state.view = await api(`/api/state?board=${encodeURIComponent(state.boardId)}${state.showSubs ? "&subagents=1" : ""}`);
      render();
      if (state.selected?.type === "node") loadDetails(state.selected.id);
      else if (state.selected?.type === "sub") loadSub(state.selected);
      else if (state.selected?.type === "wire") loadTalk(state.selected.id);
    } catch (e) {
      console.warn("poll failed", e);
    }
  }
  state.pollTimer = setTimeout(poll, POLL_MS);
}

// ------------------------------------------------------------------- render

function render() {
  const v = state.view;
  if (!v) return;
  fillBoardSelect(v.boards);
  // Rebuilt only when it changes: a rebuild on every poll would drop a
  // selection of the path before it could be copied.
  const folderEl = $("#board-folder");
  if (folderEl.textContent !== v.board.folder) folderEl.replaceChildren(...pathNodes(v.board.folder));
  folderEl.title = v.board.folder;
  applyView();
  $("#empty").hidden = v.nodes.length > 0;
  renderNodes();
  if (state.fitPending && v.nodes.length) {
    state.fitPending = false;
    if (!anyCardInView()) fitView();
  }
  renderWires();
  renderSubagents();
  renderAvailable();
  renderActivity();
  renderLaunches();
  if (state.selected) renderDrawer();
}

function cardBox(n) {
  const pos = nodePos(n);
  const h = $(`#nodes [data-id="${n.sessionId}"]`)?.offsetHeight || 90;
  return { x0: pos.x, y0: pos.y, x1: pos.x + NODE_W, y1: pos.y + h };
}

// The board runs under the floating glass panels: the part of the canvas they
// leave uncovered, in canvas pixels.
function viewBox() {
  const c = $("#canvas").getBoundingClientRect(), drawer = $("#drawer");
  const right = drawer.hidden ? c.right : Math.min(c.right, drawer.getBoundingClientRect().left);
  return {
    left: Math.max(0, $(".sidebar").getBoundingClientRect().right - c.left),
    top: Math.max(0, $(".topbar").getBoundingClientRect().bottom - c.top),
    right: right - c.left, bottom: c.height,
  };
}

function anyCardInView() {
  const v = viewBox();
  return state.view.nodes.some((n) => {
    const b = cardBox(n);
    const z = state.zoom;
    return b.x1 * z + state.pan.x > v.left && b.x0 * z + state.pan.x < v.right &&
      b.y1 * z + state.pan.y > v.top && b.y0 * z + state.pan.y < v.bottom;
  });
}

// Zoom out (never past 100%) and pan so all cards (and subagents on show) are
// centered in the uncovered part of the board.
function fitView() {
  const nodes = state.view?.nodes || [];
  if (!nodes.length) return;
  const v = viewBox();
  const boxes = [...nodes.map(cardBox), ...subBoxes()];
  const x0 = Math.min(...boxes.map((b) => b.x0)), x1 = Math.max(...boxes.map((b) => b.x1));
  const y0 = Math.min(...boxes.map((b) => b.y0)), y1 = Math.max(...boxes.map((b) => b.y1));
  const z = state.zoom = Math.max(ZOOM_MIN, Math.min(1,
    (v.right - v.left - 80) / (x1 - x0 || 1), (v.bottom - v.top - 80) / (y1 - y0 || 1)));
  const place = (lo, hi, a, b) => ((hi - lo) * z > b - a - 80 ? a + 40 - lo * z : a + (b - a - (hi - lo) * z) / 2 - lo * z);
  state.pan = { x: Math.round(place(x0, x1, v.left, v.right)), y: Math.round(place(y0, y1, v.top, v.bottom)) };
  saveView();
  applyView();
  renderWires();
}

function renderNodes() {
  const layer = $("#nodes");
  const seen = new Set();
  for (const n of state.view.nodes) {
    seen.add(n.sessionId);
    let node = layer.querySelector(`[data-id="${n.sessionId}"]`);
    if (!node) {
      node = el("div", { class: "node", "data-id": n.sessionId, "data-name": n.name, tabindex: 0, role: "button" });
      layer.append(node);
    }
    const st = cardStatus(n);
    node.className = "node" + (n.live ? "" : " ended") +
      (state.selected?.type === "node" && state.selected.id === n.sessionId ? " selected" : "");
    node.setAttribute("aria-label", `${display(n)}, ${st.text}`);
    const pos = nodePos(n);
    node.style.left = `${pos.x}px`;
    node.style.top = `${pos.y}px`;
    node.dataset.name = n.name;
    node.replaceChildren(
      el("span", { class: "port in" }),
      el("div", { class: "title" },
        el("span", { class: `dot ${st.dot}`, title: st.text }),
        el("span", { class: "name", text: display(n), title: display(n) })),
      el("div", { class: "meta", text: `${n.name ? `@${n.name} · ` : ""}${folderName(where(n).replace(/\\/g, "/"))}`,
        title: `${n.name ? `Address: @${n.name}\n` : ""}Folder: ${where(n)}` }),
      el("div", { class: "meta badges" },
        // Every local card would say the same (WSL); only a Windows session is marked.
        onWindows(n) && el("span", { class: "badge win state", text: "Windows", title: n.messageBlock || "" }),
        opener(n) && el("span", { class: "badge", text: opener(n) }),
        n.model && el("span", { class: "badge model", text: modelName(n.model), title: n.model }),
        el("span", { class: `badge state ${st.dot === "needs" ? "warn" : ""}`, text: st.text,
          title: n.waitingFor ? `Waiting for: ${n.waitingFor}` : "" }),
        n.ambiguous && el("span", { class: "badge warn", text: "name shared", title: "Another running session has this name; /rename one of them" })),
      ...(n.live && !n.messageBlock ? [el("span", { class: "port out", title: "Drag onto another agent to connect" })] : []),
    );
  }
  for (const node of [...layer.children]) if (!seen.has(node.dataset.id)) node.remove();
}

function anchor(n, side) {
  const pos = nodePos(n);
  const node = $(`#nodes [data-id="${n.sessionId}"]`);
  const h = node ? node.offsetHeight : 80;
  return { x: pos.x + (side === "out" ? NODE_W : 0), y: pos.y + h / 2 };
}

// Arrows between cards on one row arc above it instead of running behind the
// cards in between.
function bend(a, b) {
  return Math.abs(b.y - a.y) < 60 && Math.abs(b.x - a.x) > NODE_W * 1.5
    ? -Math.min(140, Math.abs(b.x - a.x) * 0.25) : 0;
}

function curve(a, b) {
  const dx = Math.max(50, Math.abs(b.x - a.x) / 2), up = bend(a, b);
  return `M${a.x} ${a.y} C${a.x + dx} ${a.y + up}, ${b.x - dx} ${b.y + up}, ${b.x} ${b.y}`;
}

function midpoint(a, b) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 + 0.75 * bend(a, b) };
}

function renderWires() {
  const layer = $("#wire-layer");
  const labels = $("#labels");
  // Labels are rebuilt on every render; keep keyboard focus on the same one.
  const focused = labels.contains(document.activeElement) ? document.activeElement.dataset.id : null;
  layer.replaceChildren();
  labels.replaceChildren();
  for (const c of state.view.board.connections) {
    const a = nodeById(c.from), b = nodeById(c.to);
    if (!a || !b) continue;
    const p = anchor(a, "out"), q = anchor(b, "in");
    const d = curve(p, q);
    const selected = state.selected?.type === "wire" && state.selected.id === c.id;
    const ended = !a.live || !b.live;
    const cls = ["wire", c.status, ended ? "ended" : "", selected ? "selected" : ""].join(" ");
    const select = () => select_({ type: "wire", id: c.id });
    const hit = svg("path", { d, class: "wire-hit" });
    const path = svg("path", { d, class: cls, "marker-end": "url(#arrow)" });
    hit.addEventListener("pointerdown", (e) => { e.stopPropagation(); select(); });
    path.addEventListener("pointerdown", (e) => { e.stopPropagation(); select(); });
    layer.append(hit, path);
    const reason = c.reason.trim();
    const label = el("div", {
      class: `wire-label ${c.status === "failed" ? "failed" : ""} ${selected ? "selected" : ""}`,
      text: c.status === "failed" ? "! not delivered" : (c.status === "sending" ? "… " : "") + (reason || "connected"),
      title: c.reason,
      "data-id": c.id, tabindex: 0, role: "button",
      "aria-label": `${display(a)} to ${display(b)}${reason ? `: ${reason}` : ""}${c.status === "failed" ? " (not delivered)" : ""}`,
      onpointerdown: (e) => { e.stopPropagation(); select(); },
    });
    const mid = midpoint(p, q);
    label.style.left = `${mid.x}px`;
    label.style.top = `${mid.y}px`;
    labels.append(label);
    if (c.id === focused) label.focus({ preventScroll: true });
  }
}

// ------------------------------------------------------- running subagents
//
// With "Subagents" on, each chat's running subagents and workflow agents are
// small cards in a column next to it, joined to it by a thin line. A card
// goes away when its agent finishes.

// A subagent card is as wide as a chat card (.sub in style.css); its column
// is that plus the spine of the line beside it.
const SUB_SPINE = 16, SUB_W = NODE_W + SUB_SPINE, SUB_H = 40, SUB_GAP = 6, SUB_MAX = 6;

// The subagent cards on the board, for Fit view.
function subBoxes() {
  return [...$("#subagents").children].map((c) => {
    const x = parseFloat(c.style.left), y = parseFloat(c.style.top);
    return { x0: x, y0: y, x1: x + NODE_W, y1: y + SUB_H };
  });
}

const clear = (r, boxes) => !boxes.some((b) =>
  r.x0 < b.x1 + 16 && r.x1 > b.x0 - 16 && r.y0 < b.y1 + 16 && r.y1 > b.y0 - 16);

// Where a column h px tall goes next to card n: where it sat last time if
// that is still free, else the nearest free spot (below first, then beside,
// then above), else just below.
function subColumn(n, h, taken) {
  const b = cardBox(n), cardH = Math.round(b.y1 - b.y0);
  const at = (dx, dy) => ({ x0: b.x0 + dx, y0: b.y0 + dy, x1: b.x0 + dx + SUB_W, y1: b.y0 + dy + h, dx, dy });
  const last = state.subSpot[n.sessionId];
  if (last && clear(at(last.dx, last.dy), taken)) return at(last.dx, last.dy);
  const score = (r) => Math.hypot(Math.max(0, b.x0 - r.x1, r.x0 - b.x1), Math.max(0, b.y0 - r.y1, r.y0 - b.y1)) +
    (r.y1 <= b.y0 ? 40 : 0) + (r.x1 <= b.x0 ? 20 : 0) + Math.abs(r.x0 - b.x0) * 0.02 + Math.abs(r.y0 - b.y0) * 0.01;
  const spots = [];
  for (let i = -30; i <= 30; i++) {
    for (let j = -60; j <= 20; j++) {
      const r = at(20 * i, cardH + 20 + 20 * j);
      if (r.y1 > b.y0 - 340) spots.push(r);
    }
  }
  spots.sort((p, q) => score(p) - score(q));
  return spots.find((r) => clear(r, taken)) || at(0, cardH + 24);
}

function subChip(old, layer, item, n) {
  let chip = old.get(item.key);
  if (!chip) {
    chip = el("div", { class: "sub", "data-key": item.key, tabindex: 0, role: "button" },
      el("span", { class: "dot a-running" }),
      el("div", { class: "sub-main" }, el("div", { class: "sub-name" }), el("div", { class: "sub-meta" })));
    layer.append(chip);
  }
  const a = item.agent;
  const age = a?.startedAt ? fmtDur(Date.now() - a.startedAt) : null;
  const name = a ? a.label : item.more ? `+${item.more} more running` : "Show fewer";
  const meta = a ? [age, a.workflow ? `${a.workflow} · ${a.kind}` : a.kind].filter(Boolean).join(" · ")
    : item.more ? "Click to show them all" : `Only the first ${SUB_MAX - 1}`;
  chip.dataset.parent = n.sessionId;
  chip.dataset.agent = a ? a.id : "";
  chip.classList.toggle("more", !a);
  chip.classList.toggle("selected", !!a && state.selected?.type === "sub" &&
    state.selected.id === a.id && state.selected.parent === n.sessionId);
  if (chip.querySelector(".sub-name").textContent !== name) chip.querySelector(".sub-name").textContent = name;
  if (chip.querySelector(".sub-meta").textContent !== meta) chip.querySelector(".sub-meta").textContent = meta;
  chip.title = [a && a.label, a?.workflow && `Workflow: ${a.workflow}`, a && `Type: ${a.kind}`,
    a?.model && `Model: ${modelName(a.model)}`, age && `Running for ${age}`, a?.lastTool && `Now: ${a.lastTool}`,
    `Started by ${display(n)}`, a && "Click to see what it is doing"].filter(Boolean).join("\n");
  chip.setAttribute("aria-label", a ? `${name}, running, started by ${display(n)}` : `${name}, ${display(n)}`);
  return chip;
}

function renderSubagents() {
  const layer = $("#subagents"), lines = $("#sub-wire-layer");
  const old = new Map([...layer.children].map((c) => [c.dataset.key, c]));
  const seen = new Set();
  let running = 0;
  lines.replaceChildren();
  const nodes = state.showSubs && state.view ? state.view.nodes : [];
  const taken = nodes.map(cardBox);  // cards, then each column placed so far
  for (const n of nodes) {
    const subs = n.live && n.subagents || [];
    if (!subs.length) continue;
    running += subs.length;
    // Past SUB_MAX, the rest fold into "+N more", which unfolds them all
    // (and turns into "Show fewer"); same element, so focus stays on it.
    const fold = subs.length > SUB_MAX;
    if (!fold) delete state.subAll[n.sessionId];
    const cut = fold && !state.subAll[n.sessionId] ? SUB_MAX - 1 : subs.length;
    const items = subs.slice(0, cut).map((a) => ({ key: `${n.sessionId}:${a.id}`, agent: a }));
    if (fold) items.push({ key: `${n.sessionId}:fold`, more: subs.length - cut });
    const col = subColumn(n, items.length * SUB_H + (items.length - 1) * SUB_GAP, taken);
    taken.push(col);
    state.subSpot[n.sessionId] = { dx: col.dx, dy: col.dy };
    // The line runs from the card to a spine beside the column, which has a
    // short branch to each subagent; the spine is on the side facing the card.
    const b = cardBox(n), leftOfCard = (col.x0 + col.x1) / 2 < b.x0;
    const spine = leftOfCard ? col.x1 - SUB_SPINE / 2 : col.x0 + SUB_SPINE / 2;
    const edge = leftOfCard ? col.x1 - SUB_SPINE : col.x0 + SUB_SPINE;
    const mids = items.map((item, i) => {
      const y = col.y0 + i * (SUB_H + SUB_GAP);
      const chip = subChip(old, layer, item, n);
      chip.style.left = `${leftOfCard ? col.x0 : edge}px`;
      chip.style.top = `${y}px`;
      seen.add(item.key);
      return y + SUB_H / 2;
    });
    // (it leaves the card near its bottom, clear of the connect handles)
    const top = mids[0], bottom = mids[mids.length - 1];
    const ty = Math.min(Math.max(b.y1 - 14, top), bottom);
    const px = Math.min(Math.max(spine, b.x0), b.x1), py = Math.min(Math.max(ty, b.y0), b.y1);
    let d = `M${px} ${py} L${spine} ${ty} M${spine} ${top} L${spine} ${bottom}`;
    for (const m of mids) d += ` M${spine} ${m} L${edge} ${m}`;
    lines.append(svg("path", { d, class: "sub-wire" }));
  }
  for (const [key, chip] of old) if (!seen.has(key)) chip.remove();
  const btn = $("#show-subagents");
  btn.textContent = running ? `Subagents · ${running}` : "Subagents";
  btn.setAttribute("aria-pressed", state.showSubs);
}

// A subagent's own details: what it is doing, its state, its task. The
// "+N more" / "Show fewer" card unfolds or folds the column instead.
function openSubCard(chip) {
  const parent = chip.dataset.parent;
  if (!nodeById(parent)) return;
  if (chip.dataset.agent) return openSub(parent, chip.dataset.agent, chip.querySelector(".sub-name").textContent);
  if (state.subAll[parent]) delete state.subAll[parent];
  else state.subAll[parent] = true;
  renderSubagents();
}

function openSub(parent, id, label) {
  select_({ type: "sub", parent, id, label });
}

async function loadSub(sel) {
  const data = await api(`/api/subagent?session=${encodeURIComponent(sel.parent)}&agent=${encodeURIComponent(sel.id)}`)
    .catch((e) => ({ error: e.message }));
  state.subInfo[`${sel.parent}:${sel.id}`] = data;
  if (state.selected?.type === "sub" && state.selected.id === sel.id) renderDrawer();
}

const ago = (ms) => ms ? `${fmtDur(Math.max(0, Date.now() - ms))} ago` : null;

function foldBubble(key, text) {
  const open = !!state.chatOpen[key];
  const long = text.length > FOLD_CHARS || text.split("\n").length > FOLD_LINES;
  return [el("div", { class: "bubble" + (long && !open ? " folded" : ""), text }),
    long && el("button", { class: "fold", text: open ? "Show less" : "Show all",
      onclick: () => { state.chatOpen[key] = !open; renderDrawer(); } })];
}

function subDetails(sel) {
  const key = `${sel.parent}:${sel.id}`, d = state.subInfo[key], n = nodeById(sel.parent);
  const head = el("h3", { text: d?.label || sel.label || "Subagent" });
  if (!d) return [head, el("p", { class: "muted small", text: "Loading…" })];
  if (d.error) return [head, el("p", { class: "error small", text: d.error })];
  const running = d.state === "running", steps = [...d.steps].reverse();
  return [
    head,
    el("p", { class: "sub-state" }, el("span", { class: stateClass(d.state), title: d.state }),
      el("span", { text: [AGENT_STATE_TEXT[d.state] || d.state, modelName(d.model), fmtDur(d.durationMs),
        fmtTok(d.tokens)].filter(Boolean).join(" · ") })),
    el("dl", {},
      el("dt", { text: "Started by" }), el("dd", {}, n ? el("a", {
        href: "#", text: display(n), onclick: (e) => { e.preventDefault(); select_({ type: "node", id: n.sessionId }); },
      }) : "a chat that isn't on this board"),
      d.workflow && [el("dt", { text: "Workflow" }), el("dd", { text: [d.workflow, d.phase].filter(Boolean).join(" · ") })],
      !d.workflow && d.kind && [el("dt", { text: "Type" }), el("dd", { text: d.kind })]),
    el("h2", { text: running ? "Doing now" : "Last step" }),
    steps.length ? el("div", { class: "sub-steps" }, ...steps.map((s, i) => el("div", { class: `sub-step${i ? "" : " now"}` },
      el("span", { class: "mono", text: s.text }), el("span", { class: "muted small", text: ago(s.at) }))))
      : el("p", { class: "muted small", text: running ? "Getting started…" : "It took no steps." }),
    el("h2", { text: running ? "Latest message" : "Final message" }),
    ...(d.said ? [el("div", { class: "msg-meta", text: ago(d.said.at) }), ...foldBubble(`${key}:said`, d.said.text)]
      : [el("p", { class: "muted small", text: running ? "It hasn't written anything yet; it reports when it finishes." : "None." })]),
    el("h2", { text: "Its task" }),
    ...(d.task ? foldBubble(`${key}:task`, d.task) : [el("p", { class: "muted small", text: "Not recorded." })]),
  ];
}

function renderAvailable() {
  const box = $("#available");
  const groups = {};
  for (const s of state.view.available) (groups[where(s)] ||= []).push(s);
  const folders = Object.keys(groups).sort();
  if (folders.length === 0) {
    box.replaceChildren(el("p", { class: "muted small", text: "Every running session is already on this board." }));
    return;
  }
  box.replaceChildren(...folders.map((cwd) => el("div", { class: "folder-group" },
    el("div", { class: "folder-head" },
      el("p", { class: "folder-name path", title: cwd }, pathNodes(cwd)),
      el("button", { class: "btn new-here", text: "+ New agent", title: `Start a new agent in ${cwd}`,
        "aria-label": `New agent in ${cwd}`, onclick: () => openNewAgent(cwd) })),
    ...groups[cwd].map((s) => el("div", { class: "avail-row" },
      el("span", { class: `dot ${s.status}`, title: s.status, role: "img", "aria-label": s.status }),
      el("span", { class: "name", text: display(s), title: [s.name && `@${s.name}`, onWindows(s) ? "Windows" : "WSL", opener(s), s.status].filter(Boolean).join(" · ") }),
      el("button", { class: "btn", text: "Add", onclick: () => addNode(s.sessionId) }))))));
}

function renderActivity() {
  const items = state.view.board.activity.slice(0, 30);
  $("#activity-count").textContent = items.length ? `(${state.view.board.activity.length})` : "";
  $("#activity").replaceChildren(...(items.length ? items.map((a) =>
    el("li", { class: a.level }, el("time", { text: clock(a.t) }), a.text)) :
    [el("li", { class: "muted", text: "Nothing yet." })]));
}

// Activity is folded away unless you open it; the choice is remembered.
$("#activity-box").open = store("ltt.activityOpen") === true;
$("#activity-box").addEventListener("toggle", () => store("ltt.activityOpen", $("#activity-box").open));

// ------------------------------------------------------------------- drawer

function select_(sel) {
  if (!(sel.type === "node" && sel.id === state.renaming)) state.renaming = null;
  state.selected = sel;
  render();
  renderDrawer();
  if (sel.type === "node") loadDetails(sel.id);
  else if (sel.type === "sub") loadSub(sel);
  else if (sel.type === "wire") loadTalk(sel.id);
}

// An arrow's conversation: what its two chats sent each other.
async function loadTalk(id) {
  if (state.talkBusy[id]) return;
  state.talkBusy[id] = true;
  const limit = state.talkLimit[id] || 50;
  try {
    state.talk[id] = await api(`/api/talk?board=${encodeURIComponent(state.boardId)}` +
      `&conn=${encodeURIComponent(id)}&limit=${limit}`).catch((e) => ({ error: e.message }));
  } finally {
    state.talkBusy[id] = false;
  }
  if (state.selected?.type === "wire" && state.selected.id === id) renderDrawer();
}

async function loadDetails(sid) {
  const get = (path, more = "") => api(`${path}?session=${encodeURIComponent(sid)}${more}`).catch((e) => ({ error: e.message }));
  // watch=1: this drawer is open, so the chat's mod may make it a suggestion
  [state.agents[sid], state.chat[sid]] = await Promise.all([get("/api/agents"), get("/api/chat", "&watch=1")]);
  settleOutbox(sid);
  if (state.selected?.type === "node" && state.selected.id === sid) renderDrawer();
}

// Drop sent messages the chat now shows itself (or that have scrolled past
// its last few messages). Each shown message settles one sent one.
function settleOutbox(sid) {
  const out = state.outbox[sid], msgs = state.chat[sid]?.messages;
  if (!out?.length || !msgs) return;
  const mine = msgs.filter((m) => m.role === "user");
  state.outbox[sid] = out.filter((o) => {
    if (msgs.length && msgs[0].at > o.at) return false;
    const i = mine.findIndex((m) => m.at >= o.at - 30 && (m.via === "app" || m.text.trim() === o.text));
    if (i < 0) return true;
    mine.splice(i, 1);
    return false;
  });
}

function closeDrawer() {
  state.selected = null;
  state.renaming = null;
  $("#drawer").hidden = true;
  if (state.view) render();
}

function renderDrawer() {
  const body = $("#drawer-body");
  const sel = state.selected;
  if (!sel) return;
  // A click needs the same button under the press and the release, so while
  // a mouse button is held in the panel it is redrawn only after the release.
  if (state.pressing) {
    state.redrawAfterPress = true;
    return;
  }
  const active = document.activeElement;
  const keep = active?.id && body.contains(active)
    ? { id: active.id, start: active.selectionStart, end: active.selectionEnd } : null;
  try { drawDrawer(body, sel); } finally {
    const e = keep && document.getElementById(keep.id);
    if (e) { e.focus(); try { e.setSelectionRange(keep.start, keep.end); } catch { /* not a text box */ } }
  }
}

function drawDrawer(body, sel) {
  if (sel.type === "wire") {
    const c = connById(sel.id);
    if (!c) return closeDrawer();
    body.replaceChildren(...wireDetails(c).filter(Boolean));
  } else if (sel.type === "sub") {
    body.replaceChildren(...subDetails(sel).filter(Boolean));
  } else {
    const n = nodeById(sel.id);
    if (!n) return closeDrawer();
    body.replaceChildren(...nodeDetails(n).filter(Boolean));
  }
  $("#drawer").hidden = false;
}

$("#drawer").addEventListener("pointerdown", () => { state.pressing = true; });
for (const type of ["pointerup", "pointercancel"]) {
  window.addEventListener(type, () => {
    if (!state.pressing) return;
    state.pressing = false;
    if (!state.redrawAfterPress) return;
    state.redrawAfterPress = false;
    setTimeout(renderDrawer);  // after the click this release makes
  }, true);
}

const STATE_TEXT = { sent: "✓ sent", altered: "⚠ sent, reworded", failed: "✗ failed", sending: "sending…", skipped: "not sent" };

function wireDetails(c) {
  const a = nodeById(c.from), b = nodeById(c.to);
  const notes = [["from", a], ["to", b]].map(([side, n]) => {
    const note = c.notes[side];
    return el("div", { class: "note-card" },
      el("header", {},
        el("strong", { text: `Note to ${n ? display(n) : "?"}` }),
        el("span", { class: `state-${note.state}`, text: STATE_TEXT[note.state] || note.state })),
      note.enabled && el("pre", { class: "mono", text: note.text }),
      note.state === "failed" && note.detail && el("p", { class: "error small", text: note.detail }),
      note.state === "altered" && note.sentText && el("div", {},
        el("p", { class: "small muted", text: "What the relay actually sent:" }),
        el("pre", { class: "mono", text: note.sentText })));
  });
  // its state lives in `state`: the drawer is redrawn on every poll
  const notify = el("input", { type: "checkbox", id: "d-notify", checked: !state.notifyOff[c.id],
    onchange: (e) => { state.notifyOff[c.id] = !e.target.checked; } });
  const failed = Object.values(c.notes).some((n) => n.enabled && n.state === "failed");
  return [
    el("h3", { text: `${a ? display(a) : "?"} → ${b ? display(b) : "?"}` }),
    el("dl", {},
      el("dt", { text: "Why" }), el("dd", { text: c.reason.trim() || "no reason given" }),
      el("dt", { text: "Connected" }), el("dd", { text: new Date(c.createdAt * 1000).toLocaleString() }),
      el("dt", { text: "Status" }), el("dd", { text: c.status })),
    ...talkSection(c),
    group(`notes:${c.id}`, failed, [el("span", { class: "run-name", text: "Notes sent when connected" })], notes),
    el("div", { class: "drawer-actions" },
      failed && el("button", { class: "btn", text: "Resend failed notes", onclick: () => act("resend", { id: c.id }) }),
      !c.notes.from.enabled && a?.live && el("button", {
        class: "btn primary", text: `Ask ${display(a)} to start the conversation`,
        title: "It wasn't told about this arrow, so nobody went first",
        onclick: () => act("start", { id: c.id }),
      }),
      el("label", { class: "small check" }, notify, " Tell both agents"),
      el("button", {
        class: "btn danger", text: "Disconnect",
        onclick: async () => {
          const told = notify.checked ? " Both agents will be told." : "";
          if (!confirm(`Disconnect ${a ? display(a) : "?"} → ${b ? display(b) : "?"}?${told}`)) return;
          await act("disconnect", { id: c.id, notify: notify.checked });
          closeDrawer();
        },
      })),
  ];
}

function nodeDetails(n) {
  const conns = state.view.board.connections.filter((c) => c.from === n.sessionId || c.to === n.sessionId);
  // Agents this one can still be connected to, for connecting without dragging.
  const targets = n.live && !n.messageBlock ? state.view.nodes.filter((o) =>
    o.sessionId !== n.sessionId && o.live && !o.messageBlock &&
    !conns.some((c) => c.from === n.sessionId && c.to === o.sessionId)) : [];
  return [
    ...nameHeading(n),
    // The facts fold into one line; the choice is remembered.
    el("details", {
      class: "info", open: store("ltt.infoOpen") === true,
      ontoggle: (e) => store("ltt.infoOpen", e.target.open),
    }, el("summary", { class: "muted small",
      text: [n.live ? n.status : "session ended", n.model && modelName(n.model), n.live && opener(n)]
        .filter(Boolean).join(" · ") }),
    el("dl", {},
      n.alias && n.title && [el("dt", { text: "Title" }), el("dd", { text: n.title })],
      el("dt", { text: "Address" }), el("dd", { class: "mono small", text: `@${n.name}` }),
      el("dt", { text: "Status" }), el("dd", { text: n.live ? n.status : "session ended" }),
      el("dt", { text: "Runs on" }), el("dd", { text: onWindows(n) ? "Windows" : hostLabel() }),
      el("dt", { text: "Folder" }), el("dd", { class: "small path" }, pathNodes(where(n))),
      n.messageBlock && [el("dt", { text: "Notes" }), el("dd", { class: "small", text: `Can't receive notes. ${n.messageBlock}` })],
      n.live && [el("dt", { text: "Opened in" }), el("dd", { text: opener(n) || "?" })],
      n.model && [el("dt", { text: "Model" }), el("dd", { text: modelName(n.model) })],
      el("dt", { text: "Session" }), el("dd", { class: "mono small", text: n.sessionId }))),
    n.editor && el("div", { class: "drawer-actions" }, el("button", {
      class: "btn primary", text: n.live ? `Open in ${n.editor}` : `Reopen in ${n.editor}`,
      title: `Shows this chat in ${n.editor}`,
      onclick: () => { window.location.href = editorLink(n.editor, { session: n.sessionId }); },
    })),
    ...chatSection(n),
    ...sendSection(n),
    ...(n.background ? backgroundSection(n) : []),
    ...agentsSection(n),
    el("h2", { text: "Connections" }),
    conns.length ? el("ul", {}, ...conns.map((c) => {
      const other = nodeById(c.from === n.sessionId ? c.to : c.from);
      const dir = c.from === n.sessionId ? "→" : "←";
      return el("li", {}, el("a", {
        href: "#", text: `${dir} ${other ? display(other) : "?"}${c.reason.trim() ? `: ${c.reason.trim()}` : ""}`,
        onclick: (e) => { e.preventDefault(); select_({ type: "wire", id: c.id }); },
      }));
    })) : el("p", { class: "muted small", text: n.messageBlock
      ? "None. This session can't be connected until it can receive notes."
      : targets.length ? "None. Drag the blue handle onto another agent, or pick one below."
      : "None. Drag the blue handle onto another agent to connect them." }),
    targets.length > 0 && el("div", { class: "drawer-actions connect-to" },
      el("span", { class: "small muted", text: "Connect to" }),
      ...targets.map((o) => el("button", {
        class: "btn", id: `connect-${o.sessionId}`, text: display(o),
        onclick: () => openConnectDialog(n.sessionId, o.sessionId),
      }))),
    handoffable(n) && el("div", { class: "drawer-actions" }, handoffButton(n)),
    handoffNote(n),
    endControls(n),
    removeControls(n, conns),
  ];
}

// Rename: a name of your own for a card, kept with the board. The chat keeps
// its title and its address, so notes and messages still find it.
function nameHeading(n) {
  if (state.renaming !== n.sessionId) {
    return [el("div", { class: "name-head" },
      el("h3", { text: display(n), title: "Double-click to rename", ondblclick: () => startRename(n) }),
      el("button", { class: "icon-btn rename", text: "✎", "aria-label": "Rename", title: "Rename (F2)",
        onclick: () => startRename(n) }))];
  }
  const box = el("input", {
    id: "rename-box", class: "rename-box", maxlength: 60, "aria-label": "Name on this board",
    placeholder: n.title || `@${n.name}`,
    oninput: (e) => { state.renameDraft = e.target.value; },
    onkeydown: (e) => {
      if (e.isComposing) return;
      if (e.key === "Enter") { e.preventDefault(); saveRename(n, box.value); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); stopRename(); }
    },
  });
  box.value = state.renameDraft;
  return [
    box,
    el("div", { class: "drawer-actions" },
      el("button", { class: "btn primary", text: "Save", onclick: () => saveRename(n, box.value) }),
      el("button", { class: "btn", text: "Cancel", onclick: stopRename }),
      n.alias && el("button", { class: "btn", text: n.title ? "Use its title" : "Use its address",
        title: n.title || `@${n.name}`, onclick: () => saveRename(n, "") })),
    el("p", { class: "muted small", text: `Only this board shows this name. Messages still reach it as @${n.name}.` }),
  ];
}

function startRename(n) {
  state.renaming = n.sessionId;
  state.renameDraft = n.alias || n.title || "";
  if (state.selected?.type === "node" && state.selected.id === n.sessionId) renderDrawer();
  else select_({ type: "node", id: n.sessionId });
  const box = $("#rename-box");
  if (box) { box.focus(); box.select(); }
}

function stopRename() {
  state.renaming = null;
  renderDrawer();
}

async function saveRename(n, text) {
  const name = text.trim().replace(/\s+/g, " ");
  // The title it already shows needs no name of its own (and would stop following the title).
  if (name === (n.alias || n.title || "")) return stopRename();
  state.renaming = null;
  n.alias = name || null;  // shown now; the next poll confirms it
  render();
  renderDrawer();
  await act("rename", { sessionId: n.sessionId, name });
}

// Hand off: a copy of the chat writes a handoff (/handoff), and a new
// background agent in its folder starts by reading it. The chat itself is
// left as it is, so it can still be ended (or go on) afterwards.
const handoffable = (n) => !onWindows(n) && !n.movedTo;
const lastHandoff = (n) => (state.view.launches || [])
  .filter((l) => l.kind === "handoff" && l.from === n.sessionId).at(-1);

function handoffButton(n) {
  const busy = ["writing", "starting"].includes(lastHandoff(n)?.state);
  return el("button", {
    class: "btn", text: busy ? "Handing off…" : "Hand off to a new agent", disabled: busy,
    title: "A copy of this chat writes a handoff with /handoff; a new background agent in its folder " +
      "starts by reading it. This chat is left as it is.",
    onclick: async (e) => {
      e.currentTarget.disabled = true;
      try {
        await api(`/api/board/${state.boardId}/handoff`, { sessionId: n.sessionId });
      } catch (err) {
        toast(err.message, "error", 0);
      }
      poll();
    },
  });
}

function handoffNote(n) {
  const last = handoffable(n) && lastHandoff(n);
  return last && el("p", { class: last.state === "failed" ? "error small" : "muted small", text: last.detail });
}

// A chat in a terminal here can be ended: its Claude Code exits as when its
// window is closed. (An editor chat is closed in the editor; a background
// agent has Stop.)
const endable = (n) => n.live && !n.background && !onWindows(n) && !n.movedTo &&
  n.kind === "interactive" && n.entrypoint === "cli";

function endControls(n) {
  if (!endable(n)) return null;
  return el("div", { class: "drawer-actions" }, el("button", {
    class: "btn danger", text: "End this chat", title: "Its Claude Code exits; the terminal window stays open",
    onclick: async () => {
      const midway = n.status === "busy" ? " It stops in the middle of what it is doing." : "";
      if (!confirm(`End ${display(n)}?${midway} Claude Code in its terminal exits; the window stays open. ` +
        `The conversation is kept: claude --resume ${n.sessionId} continues it.`)) return;
      try {
        const { result } = await api(`/api/board/${state.boardId}/end`, { sessionId: n.sessionId });
        if (result.ended) toast(`Ended ${display(n)}. To continue it: ${result.resume}`, "ok", 0);
        else toast(`${display(n)} hasn't ended yet; close its terminal window instead.`, "error");
      } catch (e) {
        toast(e.message, "error", 0);
      }
      poll();
    },
  }));
}

// A card can always go; its arrows go with it. Agents still running at the
// other end of an arrow can be told, as with Disconnect.
function removeControls(n, conns) {
  const liveEnds = conns.filter((c) => {
    const other = nodeById(c.from === n.sessionId ? c.to : c.from);
    return other?.live || n.live;
  }).length;
  // its state lives in `state`: the drawer is redrawn on every poll
  const notify = el("input", { type: "checkbox", id: "r-notify", checked: liveEnds > 0 && !state.removeNotifyOff[n.sessionId],
    onchange: (e) => { state.removeNotifyOff[n.sessionId] = !e.target.checked; } });
  const arrows = conns.length === 1 ? "its arrow" : `its ${conns.length} arrows`;
  return el("div", { class: "drawer-actions" },
    liveEnds > 0 && el("label", { class: "small check" }, notify, " Tell connected agents"),
    el("button", {
      class: "btn danger",
      text: conns.length ? `Remove from board with ${arrows}` : "Remove from board",
      onclick: async () => {
        if (conns.length && !confirm(`Remove ${display(n)} and ${arrows} from the board?`)) return;
        await act("remove", { sessionId: n.sessionId, notify: liveEnds > 0 && notify.checked });
        closeDrawer();
      },
    }));
}

// ------------------------------------------------------ agents in a chat

const fmtDur = (ms) => {
  if (ms == null) return null;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
};
const fmtTok = (n) => n == null ? null
  : n >= 1e6 ? `${(n / 1e6).toFixed(2)}M tokens` : n >= 1000 ? `${(n / 1000).toFixed(1)}k tokens` : `${n} tokens`;

function modelName(m) {
  const hit = /claude-(opus|sonnet|haiku|fable)-(\d+)-(\d+)/.exec(m || "");
  if (!hit) return m || null;
  return `${hit[1][0].toUpperCase()}${hit[1].slice(1)} ${hit[2]}.${hit[3]}`;
}

const AGENT_STATE_TEXT = { running: "running", done: "done", stopped: "stopped", failed: "failed",
  queued: "queued", "not run": "not run", skipped: "skipped", completed: "completed", killed: "killed" };
const stateClass = (s) => `dot a-${String(s).replace(/\s+/g, "-")}`;

// open: shows the agent's own details when the row is clicked
function agentRow(a, labelText, open) {
  const press = open && ((e) => {
    if (e.type === "click" || e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
  });
  return el("div", { class: "agent-row", role: open && "button", tabindex: open && 0,
    title: open && "Show what it is doing", onclick: press, onkeydown: press },
    el("span", { class: stateClass(a.state), title: a.state }),
    el("div", { class: "agent-main" },
      el("div", { class: "agent-label", text: labelText, title: labelText }),
      el("div", { class: "agent-meta", text: [
        AGENT_STATE_TEXT[a.state] || a.state, modelName(a.model), fmtDur(a.durationMs),
        fmtTok(a.tokens), a.toolCalls != null ? `${a.toolCalls} tool calls` : null,
      ].filter(Boolean).join(" · ") }),
      a.lastTool && el("div", { class: "agent-last mono", text: a.lastTool, title: a.lastTool })));
}

function group(key, openByDefault, summary, body) {
  const d = el("details", { class: "run", open: state.runOpen[key] ?? openByDefault },
    el("summary", {}, ...summary), ...body);
  d.addEventListener("toggle", () => { state.runOpen[key] = d.open; });
  return d;
}

function runGroup(r, n) {
  const phases = [...r.phases];
  for (const a of r.agents) if (a.phase && !phases.includes(a.phase)) phases.push(a.phase);
  const body = [];
  for (const phase of [...phases, null]) {
    const inPhase = r.agents.filter((a) => (a.phase || null) === phase);
    if (!inPhase.length) continue;
    const counts = {};
    for (const a of inPhase) counts[a.state] = (counts[a.state] || 0) + 1;
    body.push(el("div", { class: "phase-title", text:
      `${phase || "Other"} · ${Object.entries(counts).map(([s, k]) => `${k} ${s}`).join(", ")}` }));
    body.push(...inPhase.map((a) => agentRow(a, a.label, n && (() => openSub(n.sessionId, a.id, a.label)))));
  }
  if (!r.agents.length) body.push(el("p", { class: "muted small", text: "No agents recorded yet." }));
  if (n && canReach(n)) {
    const ask = r.status === "running"
      ? ["Ask it to stop this workflow", `Please stop the workflow "${r.name}" (run ${r.runId}) now and tell me where it got to.`]
      : ["killed", "stopped", "failed"].includes(r.status)
        ? ["Ask it to resume this workflow", `Please resume the workflow "${r.name}" (run ${r.runId}) from where it stopped.`]
        : null;
    if (ask) body.unshift(el("div", { class: "drawer-actions run-actions" }, el("button", {
      class: "btn", text: ask[0], onclick: () => sendTo(n, ask[1]) })));
  }
  return group(r.runId, r.status === "running", [
    el("span", { class: stateClass(r.status), title: r.status }),
    el("div", { class: "run-head" },
      el("div", { class: "run-name", text: r.name, title: r.summary || r.name }),
      el("div", { class: "agent-meta", text: [
        `workflow ${r.status}`, `${r.agentCount} agents`, fmtTok(r.totalTokens), fmtDur(r.durationMs),
      ].filter(Boolean).join(" · ") })),
  ], body);
}

function agentsSection(n) {
  const data = state.agents[n.sessionId];
  const head = el("h2", { text: "Agents in this chat" });
  if (!data) return [head, el("p", { class: "muted small", text: "Loading…" })];
  if (data.error) return [head, el("p", { class: "error small", text: data.error })];
  const { workflows: runs, direct } = data;
  if (!runs.length && !direct.length) {
    return [head, el("p", { class: "muted small", text: "This chat hasn't started any subagents or workflows." })];
  }
  const running = direct.filter((a) => a.state === "running").length +
    runs.reduce((k, r) => k + r.agents.filter((a) => a.state === "running").length, 0);
  if (running) head.textContent = `Agents in this chat · ${running} running`;
  const out = [head, ...runs.map((r) => runGroup(r, n))];
  if (direct.length) {
    const live = direct.filter((a) => a.state === "running").length;
    out.push(group(`direct:${n.sessionId}`, true, [
      el("span", { class: stateClass(live ? "running" : "done") }),
      el("div", { class: "run-head" },
        el("div", { class: "run-name", text: "Subagents" }),
        el("div", { class: "agent-meta", text: `${direct.length} started${live ? ` · ${live} running` : ""}` })),
    ], direct.map((a) => agentRow(a, a.agentType ? `${a.description} (${a.agentType})` : a.description,
      () => openSub(n.sessionId, a.id, a.description)))));
  }
  return out;
}

async function act(action, body) {
  try {
    await api(`/api/board/${state.boardId}/${action}`, body);
  } catch (e) {
    alert(e.message);
  }
  poll();
}

function addNode(sessionId) {
  const r = $("#canvas").getBoundingClientRect();
  const count = state.view.nodes.length;
  act("add", {
    sessionId,
    x: Math.round((r.width / 2 - state.pan.x) / state.zoom - NODE_W / 2 + (count % 5) * 18),
    y: Math.round((r.height / 3 - state.pan.y) / state.zoom + (count % 5) * 18),
  });
}

// --------------------------------------------------------- pointer handling

function nodeAt(evt) {
  const hit = document.elementFromPoint(evt.clientX, evt.clientY);
  const node = hit && hit.closest(".node");
  return node ? node.dataset.id : null;
}

function drawDraft(evt) {
  const src = nodeById(state.connecting.from);
  if (!src) return;
  $("#draft-wire").setAttribute("d", curve(anchor(src, "out"), toWorld(evt)));
  const over = nodeAt(evt);
  for (const node of document.querySelectorAll(".node")) {
    node.classList.toggle("drop-target", node.dataset.id === over && over !== state.connecting.from);
  }
}

function stopConnecting() {
  state.connecting = null;
  document.body.classList.remove("connecting");
  $("#draft-wire").setAttribute("d", "");
  for (const node of document.querySelectorAll(".drop-target")) node.classList.remove("drop-target");
}

function finishConnect(targetId) {
  const from = state.connecting.from;
  stopConnecting();
  if (!targetId || targetId === from) return;
  const existing = state.view.board.connections.find((c) => c.from === from && c.to === targetId);
  if (existing) return select_({ type: "wire", id: existing.id });
  openConnectDialog(from, targetId);
}

const canvas = $("#canvas");

canvas.addEventListener("pointerdown", (evt) => {
  if (evt.button !== 0) return;
  const target = evt.target;
  // second click of click-to-connect
  if (state.connecting?.click) {
    evt.preventDefault();
    return finishConnect(nodeAt(evt));
  }
  if (target.closest(".port.out")) {
    evt.preventDefault();
    state.connecting = { from: target.closest(".node").dataset.id, x0: evt.clientX, y0: evt.clientY, click: false };
    document.body.classList.add("connecting");
    canvas.setPointerCapture(evt.pointerId);
    drawDraft(evt);
    return;
  }
  const nodeEl = target.closest(".node");
  if (nodeEl) {
    const n = nodeById(nodeEl.dataset.id);
    const pos = nodePos(n);
    state.drag = { kind: "node", id: n.sessionId, x0: evt.clientX, y0: evt.clientY, ox: pos.x, oy: pos.y, moved: false };
  } else if (!target.closest(".wire-label")) {
    // a subagent card pans the board too; a click on it shows its details
    state.drag = { kind: "pan", x0: evt.clientX, y0: evt.clientY, ox: state.pan.x, oy: state.pan.y, moved: false,
      sub: target.closest(".sub") };
    canvas.classList.add("panning");
  }
  if (state.drag) canvas.setPointerCapture(evt.pointerId);
});

// The mouse wheel zooms around the pointer, like a map: down zooms out.
canvas.addEventListener("wheel", (evt) => {
  evt.preventDefault();
  const r = canvas.getBoundingClientRect(), cx = evt.clientX - r.left, cy = evt.clientY - r.top;
  const step = evt.deltaMode === 1 ? evt.deltaY * 16 : evt.deltaMode === 2 ? evt.deltaY * r.height : evt.deltaY;
  const z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, state.zoom * Math.exp(-step * 0.0015)));
  if (z === state.zoom) return;
  const wx = (cx - state.pan.x) / state.zoom, wy = (cy - state.pan.y) / state.zoom;
  state.zoom = z;
  state.pan = { x: cx - wx * z, y: cy - wy * z };
  applyView();
  clearTimeout(state.viewSave);
  state.viewSave = setTimeout(saveView, 300);
}, { passive: false });

canvas.addEventListener("pointermove", (evt) => {
  if (state.connecting) return drawDraft(evt);
  const d = state.drag;
  if (!d) return;
  const dx = evt.clientX - d.x0, dy = evt.clientY - d.y0;
  if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
  if (!d.moved) return;
  if (d.kind === "node") {
    state.localPos[d.id] = { x: Math.round(d.ox + dx / state.zoom), y: Math.round(d.oy + dy / state.zoom) };
    const node = $(`#nodes [data-id="${d.id}"]`);
    node.style.left = `${state.localPos[d.id].x}px`;
    node.style.top = `${state.localPos[d.id].y}px`;
    renderWires();
    renderSubagents();
  } else {
    state.pan = { x: d.ox + dx, y: d.oy + dy };
    applyView();
  }
});

canvas.addEventListener("pointerup", async (evt) => {
  if (state.connecting) {
    const moved = Math.abs(evt.clientX - state.connecting.x0) + Math.abs(evt.clientY - state.connecting.y0) > 6;
    if (moved) finishConnect(nodeAt(evt));
    else state.connecting.click = true; // click the handle, then click the target
    return;
  }
  const d = state.drag;
  state.drag = null;
  canvas.classList.remove("panning");
  if (!d) return;
  if (d.kind === "pan") {
    if (d.moved) saveView();
    else if (d.sub) openSubCard(d.sub);
    else if (state.selected) closeDrawer();
    return;
  }
  if (!d.moved) {
    // A second click on the card soon after renames it. (The press captured
    // the pointer, so the browser's dblclick goes to the canvas, not the card.)
    const again = state.lastClick?.id === d.id && evt.timeStamp - state.lastClick.at < DOUBLE_CLICK_MS;
    state.lastClick = again ? null : { id: d.id, at: evt.timeStamp };
    return again ? startRename(nodeById(d.id)) : select_({ type: "node", id: d.id });
  }
  const pos = state.localPos[d.id];
  try {
    await api(`/api/board/${state.boardId}/layout`, { positions: { [d.id]: pos } });
    const n = nodeById(d.id);
    if (n) Object.assign(n, pos);
  } finally {
    delete state.localPos[d.id];
  }
});

document.addEventListener("keydown", (evt) => {
  if (evt.key !== "Escape") return;
  if (state.connecting) stopConnecting();
  else if (state.selected && !document.querySelector("dialog[open]")) closeDrawer();
});
$("#drawer-close").addEventListener("click", closeDrawer);

// Keyboard: Tab reaches cards, subagents and arrow labels; Enter or Space
// opens them, and F2 renames a card.
for (const layer of [$("#nodes"), $("#subagents"), $("#labels")]) {
  layer.addEventListener("keydown", (evt) => {
    const card = evt.key === "F2" && evt.target.closest(".node");
    if (card) {
      evt.preventDefault();
      return startRename(nodeById(card.dataset.id));
    }
    if (evt.key !== "Enter" && evt.key !== " ") return;
    const node = evt.target.closest(".node"), label = evt.target.closest(".wire-label");
    const sub = evt.target.closest(".sub");
    if (!node && !label && !sub) return;
    evt.preventDefault();
    if (sub) openSubCard(sub);
    else select_(node ? { type: "node", id: node.dataset.id } : { type: "wire", id: label.dataset.id });
  });
  layer.addEventListener("focusin", (evt) => revealFocused(evt.target));
}

// Pan a card or label reached with the keyboard fully into view, clear of the
// glass panels. (The canvas clips instead of scrolling, so the browser can't
// scroll it there itself.)
function revealFocused(target) {
  if (!target.matches(":focus-visible")) return;
  const c = canvas.getBoundingClientRect(), v = viewBox(), b = target.getBoundingClientRect();
  const r = { left: c.left + v.left, right: c.left + v.right, top: c.top + v.top, bottom: c.top + v.bottom };
  const dx = b.left < r.left ? r.left - b.left + 40 : b.right > r.right ? r.right - b.right - 40 : 0;
  const dy = b.top < r.top ? r.top - b.top + 40 : b.bottom > r.bottom ? r.bottom - b.bottom - 40 : 0;
  if (!dx && !dy) return;
  state.pan = { x: Math.round(state.pan.x + dx), y: Math.round(state.pan.y + dy) };
  applyView();
  saveView();
}

// ---------------------------------------------------------- connect dialog

const cd = {
  dialog: $("#connect-dialog"), reason: $("#c-reason"),
  textFrom: $("#c-text-from"), textTo: $("#c-text-to"),
  notifyFrom: $("#c-notify-from"), notifyTo: $("#c-notify-to"),
  error: $("#c-error"), submit: $("#c-submit"),
  pair: null, edited: { from: false, to: false },
};

function openConnectDialog(fromId, toId) {
  const src = nodeById(fromId), dst = nodeById(toId);
  cd.pair = { src, dst };
  cd.edited = { from: false, to: false };
  $("#c-from").textContent = display(src);
  $("#c-to").textContent = display(dst);
  $("#c-from").title = `@${src.name}`;
  $("#c-to").title = `@${dst.name}`;
  $("#c-from-2").textContent = display(src);
  $("#c-to-2").textContent = display(dst);
  cd.reason.value = "";
  cd.notifyFrom.checked = cd.notifyTo.checked = true;
  refreshNotes();
  let problem = "";
  if (!src.live || !dst.live) problem = "Both agents must be running to connect them.";
  else if (src.messageBlock || dst.messageBlock) problem = (src.messageBlock || dst.messageBlock);
  else if (src.platform !== dst.platform) problem = "A WSL session and a Windows session can't message each other.";
  else if (src.ambiguous || dst.ambiguous) problem = "Two running sessions share one of these names. Run /rename in one of them first.";
  cd.error.textContent = problem;
  cd.error.hidden = !problem;
  cd.submit.disabled = Boolean(problem);
  cd.dialog.showModal();
  cd.reason.focus();
}

function refreshNotes() {
  const notes = defaultNotes(cd.pair.src, cd.pair.dst, cd.reason.value, cd.notifyFrom.checked);
  if (!cd.edited.from) cd.textFrom.value = notes.from;
  if (!cd.edited.to) cd.textTo.value = notes.to;
  cd.textFrom.disabled = !cd.notifyFrom.checked;
  cd.textTo.disabled = !cd.notifyTo.checked;
}

cd.reason.addEventListener("input", refreshNotes);
cd.notifyFrom.addEventListener("change", refreshNotes);
cd.notifyTo.addEventListener("change", refreshNotes);
cd.textFrom.addEventListener("input", () => { cd.edited.from = true; });
cd.textTo.addEventListener("input", () => { cd.edited.to = true; });

$("#connect-form").addEventListener("submit", async (evt) => {
  if (evt.submitter?.value !== "ok") return;
  evt.preventDefault();
  cd.submit.disabled = true;
  try {
    const res = await api(`/api/board/${state.boardId}/connect`, {
      from: cd.pair.src.sessionId, to: cd.pair.dst.sessionId, reason: cd.reason.value,
      notifyFrom: cd.notifyFrom.checked, notifyTo: cd.notifyTo.checked,
      textFrom: cd.textFrom.value, textTo: cd.textTo.value,
    });
    cd.dialog.close();
    state.selected = { type: "wire", id: res.result.id };
    poll();
  } catch (e) {
    cd.error.textContent = e.message;
    cd.error.hidden = false;
  } finally {
    cd.submit.disabled = false;
  }
});

// ------------------------------------------------------------ board dialog

// The two dialogs that ask for a folder share one browser.
const pickers = {
  board: { input: $("#b-folder"), box: $("#b-browser"), error: $("#b-error") },
  agent: { input: $("#n-folder"), box: $("#n-browser"), error: $("#n-error") },
};

const placeButtons = (places, ui) => places.map((pl) => el("button", {
  type: "button", class: "btn place", text: pl.label, title: pl.path, onclick: () => browse(pl.path, ui),
}));

function openBoardDialog(folders, boards, places = []) {
  const have = new Set(boards.map((b) => b.folder));
  const free = folders.filter((f) => !have.has(f));
  $("#b-folders").replaceChildren(...folders.map((f) => el("option", { value: f })));
  $("#b-places").replaceChildren(...placeButtons(places, pickers.board));
  $("#b-suggest").replaceChildren(
    ...(free.length ? [el("span", { class: "small muted", text: "Folders with running sessions:" })] : []),
    ...free.map((f) => el("button", {
      type: "button", class: "btn mono", text: f,
      onclick: () => { $("#b-folder").value = f; $("#b-browser").hidden = true; },
    })));
  $("#b-folder").value = "";
  $("#b-browser").hidden = true;
  $("#b-error").hidden = true;
  $("#board-dialog").showModal();
  $("#b-folder").focus();
}

// Folder browser: click a folder to go into it; the box above always holds
// the folder you are in, so Create (or Start agent) uses it.
async function browse(path, ui = pickers.board) {
  const { input, box, error } = ui;
  try {
    const d = await api("/api/dirs", { path });
    input.value = d.path;
    error.hidden = true;
    const into = (name) => `${d.path.replace(/\/+$/, "")}/${name}`;
    box.replaceChildren(
      el("div", { class: "browse-head" },
        el("button", { type: "button", class: "btn", text: "↑ Up", disabled: !d.parent, onclick: () => browse(d.parent, ui) }),
        el("span", { class: "mono small", text: d.path, title: d.path })),
      el("div", { class: "browse-list" }, ...(d.dirs.length
        ? d.dirs.map((name) => el("button", { type: "button", class: "browse-item", text: name, onclick: () => browse(into(name), ui) }))
        : [el("p", { class: "muted small", text: "No subfolders here." })])),
      ...(d.truncated ? [el("p", { class: "muted small", text: "Showing the first 1000 folders." })] : []));
    box.hidden = false;
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  }
}

$("#b-browse").addEventListener("click", () => browse($("#b-folder").value.trim()));
$("#n-browse").addEventListener("click", () => browse(nd.folder.value.trim(), pickers.agent));

$("#new-board").addEventListener("click", async () => {
  const data = await api("/api/state");
  openBoardDialog(data.folders, data.boards, data.places);
});

$("#board-form").addEventListener("submit", async (evt) => {
  if (evt.submitter?.value !== "ok") return;
  evt.preventDefault();
  try {
    const res = await api("/api/boards", { folder: $("#b-folder").value.trim() });
    $("#board-dialog").close();
    selectBoard(res.id);
  } catch (e) {
    $("#b-error").textContent = e.message;
    $("#b-error").hidden = false;
  }
});

$("#board-select").addEventListener("change", (evt) => selectBoard(evt.target.value));
for (const btn of document.querySelectorAll("[data-close]")) {
  btn.addEventListener("click", () => btn.closest("dialog").close());
}

start().catch((e) => {
  document.body.prepend(el("p", { class: "error", text: `Could not reach the Let Them Talk server: ${e.message}` }));
});

$("#fit-view").addEventListener("click", fitView);

// Subagents on or off; the choice is remembered.
// Turned on while nothing runs, the board would look unchanged: say so.
$("#show-subagents").addEventListener("click", async () => {
  state.showSubs = !state.showSubs;
  store("ltt.subagents", state.showSubs);
  renderSubagents();
  if (!state.showSubs) return;
  await poll();
  if (state.showSubs && !$("#subagents .sub")) {
    toast("No chat on this board is running a subagent right now. They show up here when one starts.");
  }
});

// The connect hint stays on the top bar's first row: where it would wrap
// onto a second one (a narrow window, the details panel open), it hides.
const hint = $(".topbar .hint");
new ResizeObserver(() => {
  hint.style.display = "";
  if (hint.offsetTop > $(".topbar .board-pick").offsetTop + 10) hint.style.display = "none";
}).observe($(".topbar"));

// Delete the board on screen, then show another (or ask for a new one).
$("#delete-board").addEventListener("click", async () => {
  const board = state.view?.board;
  if (!board || !confirm(`Delete the board "${board.title}"? Its cards and arrows go; ` +
    "the sessions keep running and no agent is told.")) return;
  try {
    await api(`/api/board/${board.id}/delete`, {});
  } catch (e) {
    return toast(`Could not delete the board: ${e.message}`, "error");
  }
  try { localStorage.removeItem(`ltt.pan.${board.id}`); } catch { /* storage off */ }
  toast(`Deleted the board "${board.title}".`, "ok");
  // Clear it off the page first: if it was the last board, start() only opens
  // New board, and the old cards (and polling) must not linger behind it.
  clearTimeout(state.pollTimer);
  Object.assign(state, { boardId: null, view: null, selected: null });
  $("#drawer").hidden = true;
  for (const layer of ["#nodes", "#labels", "#wire-layer"]) $(layer).replaceChildren();
  $("#board-folder").textContent = "—";
  start();
});

// Side panels: drag the inner edge to resize, double-click it to reset; the
// width is remembered. dir is +1 when the edge is on the panel's right side.
// The width goes into a CSS variable, since the top bar sits beside the panels.
function resizable(panel, handle, key, def, dir, cssVar) {
  const MIN = 180, MAX = 720;
  const set = (w) => document.documentElement.style.setProperty(cssVar, `${Math.min(MAX, Math.max(MIN, w))}px`);
  if (store(key)) set(store(key));
  handle.addEventListener("pointerdown", (evt) => {
    evt.preventDefault();
    const x0 = evt.clientX, w0 = panel.getBoundingClientRect().width;
    handle.setPointerCapture(evt.pointerId);
    handle.classList.add("active");
    const move = (e) => set(w0 + dir * (e.clientX - x0));
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.classList.remove("active");
      store(key, Math.round(panel.getBoundingClientRect().width));
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
  handle.addEventListener("dblclick", () => { set(def); store(key, def); });
}
resizable($(".sidebar"), $("#sidebar-resizer"), "ltt.sidebarW", 280, +1, "--side-w");
resizable($("#drawer"), $("#drawer-resizer"), "ltt.drawerW", 360, -1, "--drawer-w");

// ------------------------------------------------------------ Liquid Glass
// The glass panels bend what is behind them at their rim, as Apple's Liquid
// Glass does: each gets an SVG filter whose displacement map pulls the
// backdrop toward the middle near the edge. Chromium only; other browsers,
// and reduced transparency, keep the plain CSS blur.
const LENS = Boolean(navigator.userAgentData?.brands?.some((b) => b.brand === "Chromium")) &&
  !matchMedia("(prefers-reduced-transparency: reduce)").matches;
const lensDefs = svg("svg", { width: 0, height: 0, "aria-hidden": "true", style: "position: absolute" });
document.body.append(lensDefs);

// R and G hold the x and y pull (128 = none): strongest at the rim and gone
// `bezel` px in, so a rounded panel acts like a thick convex lens.
function lensMap(w, h, radius, bezel) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d"), img = ctx.createImageData(w, h), px = img.data;
  for (let i = 0; i < px.length; i += 4) { px[i] = px[i + 1] = 128; px[i + 3] = 255; }
  for (let y = 0; y < h; y++) {
    const band = y < bezel || y >= h - bezel;
    for (let x = 0; x < w; x++) {
      if (!band && x === bezel) x = w - bezel;  // the middle of the row stays untouched
      const qx = Math.abs(x + 0.5 - w / 2) - (w / 2 - radius), qy = Math.abs(y + 0.5 - h / 2) - (h / 2 - radius);
      const ox = Math.max(qx, 0), oy = Math.max(qy, 0), out = Math.hypot(ox, oy);
      const d = out + Math.min(Math.max(qx, qy), 0) - radius;  // distance to the edge, negative inside
      if (d > 0 || -d > bezel) continue;
      let nx = out > 0 ? ox / out : qx > qy ? 1 : 0, ny = out > 0 ? oy / out : qx > qy ? 0 : 1;
      if (x + 0.5 < w / 2) nx = -nx;
      if (y + 0.5 < h / 2) ny = -ny;
      const m = (1 + d / bezel) ** 2, i = (y * w + x) * 4;
      px[i] = 128 - nx * m * 127;
      px[i + 1] = 128 - ny * m * 127;
    }
  }
  ctx.putImageData(img, 0, 0);
  return c.toDataURL();
}

// Give a glass element its lens; the map is redrawn when the element resizes.
// bezel: how far in from the edge the glass bends (all the way in makes a
// small control one lens). spread: red bent a little more and blue a little
// less, the faint rainbow at a glass edge (three passes, so small things only).
function glass(target, { scale = 18, blur = 4, bezel = (w, h) => Math.min(24, w / 4, h / 3), spread = 0 } = {}) {
  if (!LENS) return;
  const id = `lens-${lensDefs.children.length}`;
  const map = svg("feImage", { x: 0, y: 0, preserveAspectRatio: "none", result: "map" });
  const filter = svg("filter", { id, x: 0, y: 0, width: "100%", height: "100%", "color-interpolation-filters": "sRGB" });
  const bend = (s, result) => svg("feDisplacementMap", { in: "soft", in2: "map", scale: s,
    xChannelSelector: "R", yChannelSelector: "G", result });
  filter.append(map, svg("feGaussianBlur", { in: "SourceGraphic", stdDeviation: blur, result: "soft" }));
  if (spread) {
    const only = ["1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0", "0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0",
      "0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0"];
    [1 + spread, 1, 1 - spread].forEach((k, i) => filter.append(bend(scale * k, `d${i}`),
      svg("feColorMatrix", { in: `d${i}`, type: "matrix", values: only[i], result: `c${i}` })));
    filter.append(
      svg("feComposite", { in: "c0", in2: "c1", operator: "arithmetic", k2: 1, k3: 1, result: "c01" }),
      svg("feComposite", { in: "c01", in2: "c2", operator: "arithmetic", k2: 1, k3: 1, result: "bent" }));
  } else {
    filter.append(bend(scale, "bent"));
  }
  filter.append(svg("feColorMatrix", { in: "bent", type: "saturate", values: 1.8 }));
  lensDefs.append(filter);
  let size = "";
  new ResizeObserver(() => {
    const w = target.offsetWidth, h = target.offsetHeight;
    if (!w || !h || `${w}x${h}` === size) return;
    size = `${w}x${h}`;
    const radius = Math.min(parseFloat(getComputedStyle(target).borderTopLeftRadius) || 0, w / 2, h / 2);
    map.setAttribute("href", lensMap(w, h, radius, Math.max(1, Math.floor(bezel(w, h)))));
    map.setAttribute("width", w);
    map.setAttribute("height", h);
    target.style.backdropFilter = `url(#${id})`;
  }).observe(target);
}
glass($(".sidebar"), { scale: 26 });
glass($("#drawer"), { scale: 26 });
// The top bar's pills are clear glass: each one lens, bending what is under it.
for (const item of document.querySelectorAll(".topbar .board-pick, .topbar .seg, .topbar .hint")) {
  glass(item, { scale: 16, blur: 1.5, bezel: (w, h) => h / 2, spread: 0.06 });
}
for (const dialog of document.querySelectorAll("dialog")) glass(dialog, { scale: 24, blur: 10 });
glass($("#appearance"), { scale: 14, blur: 6 });

// Appearance: the theme (system, light or dark) and how tinted the glass is,
// from clear to tinted like iOS 27's Liquid Glass setting. Both are remembered.
function applyAppearance() {
  const theme = store("ltt.theme") || "system", tint = store("ltt.tint") ?? 50;
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  document.documentElement.style.setProperty("--ga", (0.12 + 0.68 * tint / 100).toFixed(3));
  const pick = document.querySelector(`input[name="theme"][value="${theme}"]`);
  if (pick) pick.checked = true;
  $("#glass-tint").value = tint;
}
for (const pick of document.querySelectorAll('input[name="theme"]')) {
  pick.addEventListener("change", () => { store("ltt.theme", pick.value); applyAppearance(); });
}
$("#glass-tint").addEventListener("input", (e) => { store("ltt.tint", Number(e.target.value)); applyAppearance(); });
applyAppearance();

// ------------------------------------------------ open chats in the editor
//
// The Claude extension handles <editor>://anthropic.claude-code/open with
// ?prompt= (a new chat, prompt typed in but not sent) or ?session= (that chat).

const EDITOR_SCHEMES = { "Cursor": "cursor", "VS Code": "vscode",
  "VS Code Insiders": "vscode-insiders", "Windsurf": "windsurf", "VSCodium": "vscodium" };

function editorLink(editor, params) {
  // The editor decodes the link once before the extension reads its query,
  // so each value is encoded twice to arrive intact (&, +, %, ş ...).
  const query = Object.entries(params).filter(([, v]) => v)
    .map(([k, v]) => `${k}=${encodeURIComponent(encodeURIComponent(v))}`).join("&");
  return `${EDITOR_SCHEMES[editor] || "vscode"}://anthropic.claude-code/open${query ? `?${query}` : ""}`;
}

function defaultEditor() {
  const saved = store("ltt.editor");
  if (saved && EDITOR_SCHEMES[saved]) return saved;
  const counts = {};
  for (const n of state.view?.nodes || []) if (n.editor) counts[n.editor] = (counts[n.editor] || 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "VS Code";
}

// ------------------------------------------------------------- New agent
//
// Chat in the editor: the server watches for the new chat and hands it the
// prompt as a message. Background agent: `claude --bg` with the prompt as its
// real first prompt, in a folder you pick. New workflow is the same dialog
// for a background agent of its own whose first prompt asks for a workflow;
// it doesn't go through any chat.

const nd = {
  dialog: $("#chat-dialog"), prompt: $("#n-prompt"), editor: $("#n-editor"),
  folder: $("#n-folder"), name: $("#n-name"), mode: $("#n-mode"), model: $("#n-model"),
  agents: $("#n-agents"), terminal: $("#n-terminal"), note: $("#n-note"), error: $("#n-error"),
  submit: $("#n-submit"), workflow: false,
};
const whereTo = () => nd.workflow ? "background"
  : document.querySelector('input[name="n-where"]:checked').value;

// Its first prompt asks for a workflow in your words (the Workflow tool needs
// that); only the task is needed. Its card's name when you don't give one:
// "workflow" and the task's first words.
const WF_AGENTS = ["", "2", "3", "4", "6", "8"];
const WF_MODELS = { fable: "Fable", opus: "Opus", sonnet: "Sonnet", haiku: "Haiku" };
const workflowPrompt = ({ task, agents, model }) => [`Use a workflow to do this: ${task.trim()}`,
  agents && `Use ${agents} agents.`, model && `Run its agents on ${WF_MODELS[model] || model}.`].filter(Boolean).join("\n");
const workflowName = (task) =>
  ["workflow", ...task.replace(/[^\p{L}\p{N}\s_-]/gu, "").split(/\s+/).filter(Boolean).slice(0, 5)].join(" ").slice(0, 50);

function refreshAgentDialog() {
  const bg = whereTo() === "background", wf = nd.workflow;
  $("#n-title").textContent = wf ? "New workflow" : "New agent";
  $("#n-prompt-label").textContent = wf ? "What should the workflow do?" : "What should it do?";
  nd.prompt.placeholder = wf ? "e.g. Review every file in src/ for bugs and fix them"
    : "e.g. Run the test suite and fix whatever fails";
  $("#n-where-box").hidden = wf;
  nd.name.placeholder = wf ? "optional; \"workflow\" and the task's first words" : "optional; taken from the prompt";
  $("#n-agents-label").hidden = nd.agents.hidden = !wf;
  $("#n-editor-box").hidden = bg;
  $("#n-bg-box").hidden = !bg;
  for (const e of document.querySelectorAll(".n-editor-name")) e.textContent = nd.editor.value;
  nd.submit.textContent = wf ? "Start workflow" : bg ? "Start agent" : `Open in ${nd.editor.value}`;
  nd.note.textContent = [
    wf && "A new background agent starts in this folder and runs your task as a Claude Code workflow; " +
      "the model you pick runs it and its agents, which show under Subagents.",
    bg && /haiku/i.test(nd.model.value) && nd.mode.value === "auto"
      ? "With Haiku, auto mode may not be available; the agent then asks before it acts."
      : bg && "Claude Code must already trust the folder (run claude there once and accept).",
  ].filter(Boolean).join(" ");
}

// With a folder (a "+ New agent" in the sidebar), the dialog starts on a
// background agent in that folder; an editor chat can't be sent to a folder.
// With workflow, it starts a workflow (always a background agent).
function openNewAgent(folder, workflow = false) {
  nd.workflow = workflow;
  if (!nd.agents.options.length) {
    nd.agents.replaceChildren(...WF_AGENTS.map((v) => el("option", { value: v, text: v || "Its choice" })));
  }
  const pick = defaultEditor();
  nd.editor.replaceChildren(...Object.keys(EDITOR_SCHEMES).map((e) =>
    el("option", { value: e, text: e, selected: e === pick })));
  const folders = [state.view?.board.folder, ...(state.view?.folders || [])].filter(Boolean);
  $("#n-folders").replaceChildren(...[...new Set(folders)].map((f) => el("option", { value: f })));
  nd.folder.value = folder || state.view?.board.folder || "";
  if (folder) document.querySelector('input[name="n-where"][value="background"]').checked = true;
  pickers.agent.box.hidden = true;
  api("/api/state").then((d) => $("#n-places").replaceChildren(...placeButtons(d.places || [], pickers.agent)))
    .catch(() => {});
  nd.error.hidden = true;
  refreshAgentDialog();
  nd.dialog.showModal();
  nd.prompt.focus();
}
$("#new-chat").addEventListener("click", () => openNewAgent());
$("#new-workflow").addEventListener("click", () => openNewAgent(null, true));

for (const e of [nd.editor, nd.mode, nd.model, ...document.querySelectorAll('input[name="n-where"]')]) {
  e.addEventListener("change", refreshAgentDialog);
  e.addEventListener("input", refreshAgentDialog);
}

$("#chat-form").addEventListener("submit", async (evt) => {
  if (evt.submitter?.value !== "ok") return;
  evt.preventDefault();
  const prompt = nd.prompt.value.trim();
  const fail = (msg) => { nd.error.textContent = msg; nd.error.hidden = false; nd.submit.disabled = false; };
  nd.submit.disabled = true;
  try {
    if (whereTo() === "background") {
      const wf = nd.workflow;
      if (!prompt) return fail(wf ? "Say what the workflow should do." : "A background agent needs a prompt to start with.");
      const model = nd.model.value.trim();
      const res = await api(`/api/board/${state.boardId}/launch-background`, {
        prompt: wf ? workflowPrompt({ task: prompt, agents: nd.agents.value, model }) : prompt,
        folder: nd.folder.value.trim(), name: nd.name.value.trim() || (wf ? workflowName(prompt) : ""),
        permissionMode: nd.mode.value, model, openTerminal: nd.terminal.checked,
      });
      toast(`Started ${wf ? "workflow" : "background agent"} "${res.result.name}". ` +
        "It will appear on this board in a moment.", "ok");
    } else {
      const editor = nd.editor.value;
      store("ltt.editor", editor);
      await api(`/api/board/${state.boardId}/launch-editor`, { prompt, editor });
      window.location.href = editorLink(editor, {});  // opens an empty chat; the server sends the prompt
    }
    nd.dialog.close();
    nd.prompt.value = "";
    nd.name.value = "";
    poll();
  } catch (e) {
    fail(e.message);
  } finally {
    nd.submit.disabled = false;
  }
});

// ------------------------------------------------------------------ toasts

const toasts = $("#toasts");
function toast(text, level = "info", ms = level === "error" ? 7000 : 5000) {
  const t = el("div", { class: `toast ${level}` }, el("span", { text }),
    el("button", { class: "icon-btn", text: "×", "aria-label": "Dismiss", onclick: () => t.remove() }));
  toasts.append(t);
  if (ms) setTimeout(() => t.remove(), ms);
  return t;
}

// Editor chats started from here: show how handing over the prompt went.
// Handoffs report each step the same way. The server lists them for 10
// minutes, so each step's notice is remembered across reloads too: a reload
// doesn't show it again, except a failed one you haven't closed yet.
const LAUNCH_LISTED = 600;  // seconds the server lists a launch
const launchShown = {};     // launch id -> state shown on this page
const launchSeen = store("ltt.launchSeen") || {};  // launch id -> [state, at], notice gone
function renderLaunches() {
  const now = Date.now() / 1000;
  for (const [id, [, at]] of Object.entries(launchSeen)) {
    if (now - at > LAUNCH_LISTED + 60) delete launchSeen[id];
  }
  for (const l of state.view?.launches || []) {
    if (launchShown[l.id] === l.state || launchSeen[l.id]?.[0] === l.state) continue;
    launchShown[l.id] = l.state;
    const seen = () => { launchSeen[l.id] = [l.state, l.at || now]; store("ltt.launchSeen", launchSeen); };
    const level = l.state === "done" ? "ok" : l.state === "failed" ? "error" : "info";
    const t = toast(l.detail, level, l.state === "failed" ? 0 : 7000);
    if (l.state === "failed") t.querySelector(".icon-btn").addEventListener("click", seen);
    else seen();
    if (l.state === "failed" && l.prompt) {
      t.insertBefore(el("button", { class: "btn", text: "Copy prompt",
        onclick: () => navigator.clipboard?.writeText(l.prompt) }), t.lastChild);
    }
  }
}

// ------------------------------------------------ managing a chat from here

state.drafts = {};  // sessionId -> text typed into its Send box
state.sending = new Set();  // sessionIds with a Send in flight
state.outbox = {};  // sessionId -> [{text, at, state}] sent from here, not yet in its chat
state.logs = {};    // sessionId -> last screen of a background agent

// A chat can take text from here if it is running and can receive messages,
// or if it is a background agent (which wakes up with a prompt).
const canReach = (n) => n.live && (n.background || !n.messageBlock);
const promptable = (n) => n.background && n.agentState !== "working" && n.status !== "busy";

async function sendTo(n, text, how) {
  try {
    const res = await api(`/api/board/${state.boardId}/send`, { sessionId: n.sessionId, text, how });
    toast(res.result.how === "prompt"
      ? (res.result.copy ? `Claude Code started a copy (${res.result.copy}) instead of waking it.` : `Sent the prompt to ${display(n)}.`)
      : `Sent the message to ${display(n)}.`, res.result.copy ? "error" : "ok");
    return true;
  } catch (e) {
    // A dropped connection (e.g. the server restarted) says nothing about delivery.
    toast(e instanceof TypeError
      ? "Lost the connection to Let Them Talk while sending (the server may have restarted). " +
        "Check the chat before sending again."
      : e.message, "error", 0);
    return false;
  }
}

// The chat's last messages, phone style: prompts as typed, Claude's replies
// as a TL;DR the server writes once the reply is finished.
const FOLD_CHARS = 400, FOLD_LINES = 8, PREVIEW_CHARS = 200;
const preview = (text) => text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS).trimEnd()}…` : text;

function chatSection(n) {
  const data = state.chat[n.sessionId];
  const head = el("h2", { text: "Recent messages" });
  if (!data) return [head, el("p", { class: "muted small", text: "Loading…" })];
  if (data.error) return [head, el("p", { class: "error small", text: data.error })];
  const msgs = data.messages, outbox = state.outbox[n.sessionId] || [];
  if (!msgs.length && !outbox.length) return [head, el("p", { class: "muted small", text: "No messages yet." })];
  // A turn that hasn't ended may be waiting on you: a question, or a permission prompt.
  const asking = n.live && data.asking;
  const activity = !(n.live && data.working) ? ""
    : asking || n.status === "waiting" || n.agentState === "blocked" ? "waiting for you" : "working…";
  // A plan written in plan mode waits for approval in its own window.
  const planToApprove = !asking && data.plan && activity === "waiting for you";
  // What it is doing right now (its latest tool call), so the chat never sits on an old line.
  const now = activity && !asking && !planToApprove;
  return [head, el("div", { class: "chat" },
    ...msgs.map((m) => chatMessage(m, activity)),
    ...outbox.map((o) => el("div", { class: "msg user pending" },
      el("div", { class: "msg-meta", text: `You · ${o.state === "sending" ? "sending…" : "sent, not read yet"}` }),
      el("div", { class: "bubble", text: o.text }))),
    // Typed in its own window while it works; it reads them between steps.
    ...(n.live && data.queued || []).map((q) => el("div", { class: "msg user pending" },
      el("div", { class: "msg-meta", text: `You · ${clock(q.at)} · queued` }),
      el("div", { class: "bubble", text: q.text }))),
    (asking || planToApprove) && el("div", { class: "msg claude" },
      el("div", { class: "msg-meta", text: asking ? "Claude · asking you" : "Claude · plan to approve" }),
      el("div", { class: "bubble asking" },
        data.plan && planBlock(n, data.plan),
        ...(asking || []).map((q) => el("div", { class: "question" },
          q.question && el("div", { text: q.question }),
          q.options.length && el("ul", {}, ...q.options.map((o) => el("li", { text: o })))))),
      answerButton(n)),
    now && el("div", { class: "msg claude" },
      el("div", { class: "msg-meta", text: `Claude · now · ${activity}` }),
      el("div", { class: "bubble typing",
        text: data.doing || (activity === "waiting for you" ? "Waiting for you…" : "Working…") })))];
}

// The app can't answer for you; this opens where you can.
function answerButton(n) {
  if (n.background && n.running) return el("button", {
    class: "fold", text: "Open its terminal to answer",
    onclick: () => agentAction(n, "agent-attach", (r) => r.opened
      ? toast("Opened a terminal window attached to it.", "ok")
      : toast(`Run this in a terminal: ${r.command}`, "info", 0)),
  });
  if (n.editor) return el("button", {
    class: "fold", text: `Answer in ${n.editor}`,
    onclick: () => { window.location.href = editorLink(n.editor, { session: n.sessionId }); },
  });
  return el("div", { class: "msg-meta", text: "Answer it in its terminal." });
}

function planBlock(n, plan) {
  const key = `plan:${n.sessionId}`, open = !!state.chatOpen[key];
  const lines = plan.text.split("\n"), long = lines.length > 8;
  return el("div", { class: "plan" },
    el("div", { class: "plan-text", text: open || !long ? plan.text : `${lines.slice(0, 8).join("\n")}\n…` }),
    long && el("button", {
      class: "fold", text: open ? "Hide the plan" : "Show the whole plan",
      onclick: () => { state.chatOpen[key] = !open; renderDrawer(); },
    }));
}

const TALK_MAX = 500;  // the server's cap on one conversation load
const TALK_STATE = { unread: "not read yet", unknown: "read state unknown" };

// An arrow's conversation: its first chat on the left, the other on the right,
// the app's own notes in between; messages from before the arrow are faded.
function talkSection(c) {
  const data = state.talk[c.id];
  const head = el("h2", { text: "Conversation" });
  if (!data) return [head, el("p", { class: "muted small", text: "Loading…" })];
  if (data.error) return [head, el("p", { class: "error small", text: data.error })];
  if (!data.messages.length) return [head, el("p", { class: "muted small", text: "They haven't messaged each other yet." })];
  const items = [];
  let marked = !data.messages[0].before;  // no divider when nothing came before the arrow
  for (const m of data.messages) {
    if (!marked && !m.before) {
      items.push(el("p", { class: "talk-divider", text: `Arrow connected · ${when(data.createdAt)}` }));
      marked = true;
    }
    items.push(talkMessage(m, c));
  }
  const earlier = data.total - data.messages.length, limit = state.talkLimit[c.id] || 50;
  return [head,
    earlier > 0 && limit < TALK_MAX && el("button", { class: "fold", text: `Show ${Math.min(earlier, 50)} earlier`,
      onclick: () => { state.talkLimit[c.id] = limit + 50; loadTalk(c.id); } }),
    el("div", { class: "chat talk" }, ...items)];
}

function talkMessage(m, c) {
  const name = (id) => { const n = nodeById(id); return n ? display(n) : "an earlier chat"; };
  const open = !!state.chatOpen[m.id];
  const long = m.text.length > FOLD_CHARS || m.text.split("\n").length > FOLD_LINES;
  const side = m.kind === "app" ? "sys" : m.from === c.from ? "left" : "right";
  const meta = m.kind === "app"
    ? `Let Them Talk → ${name(m.to)} · ${when(m.at)}${m.state ? ` · ${STATE_TEXT[m.state] || m.state}` : ""}`
    : `${name(m.from)} · ${when(m.at)}${TALK_STATE[m.state] ? ` · ${TALK_STATE[m.state]}` : ""}`;
  return el("div", { class: `msg ${side}${m.before ? " before" : ""}` },
    el("div", { class: "msg-meta", text: meta }),
    el("div", { class: "bubble" + (long && !open ? " folded" : ""), text: m.text }),
    long && el("button", { class: "fold", text: open ? "Show less" : "Show all",
      onclick: () => { state.chatOpen[m.id] = !open; renderDrawer(); } }));
}

function chatMessage(m, activity) {
  const open = !!state.chatOpen[m.id];
  const toggle = (label) => el("button", {
    class: "fold", text: label,
    onclick: () => { state.chatOpen[m.id] = !open; renderDrawer(); },
  });
  if (m.role === "user") {
    const long = m.text.length > FOLD_CHARS || m.text.split("\n").length > FOLD_LINES;
    return el("div", { class: "msg user" },
      el("div", { class: "msg-meta", text: `${m.via === "app" ? "You, from here" : "You"} · ${clock(m.at)}` }),
      el("div", { class: "bubble" + (long && !open ? " folded" : ""), text: m.text }),
      long && toggle(open ? "Show less" : "Show all"));
  }
  // Claude's replies, and notes from other sessions (Claude writes those too),
  // show as a TL;DR when long.
  const peer = m.role === "peer", done = peer || m.done, tldr = m.tldr;
  let text = m.text, note = "", fold = null;
  if (!done) {
    text = preview(m.text);
    note = activity || "stopped";
  } else if (tldr && !open) {
    text = tldr.state === "done" ? tldr.text : preview(m.text);
    note = { done: "TL;DR", pending: "summarizing…", failed: "no TL;DR" }[tldr.state];
    fold = peer ? "Show all" : "Full reply";
  } else if (tldr) {
    fold = tldr.state === "done" ? "TL;DR" : "Show less";
  }
  return el("div", { class: `msg ${m.role}` },
    el("div", { class: "msg-meta",
      text: [peer ? `@${m.from || "another session"}` : "Claude", clock(m.at), note].filter(Boolean).join(" · ") }),
    el("div", { class: "bubble" + (done ? "" : " typing"), text }),
    fold && toggle(fold));
}

function sendSection(n) {
  if (!canReach(n)) return [];
  const asPrompt = promptable(n);
  // A likely reply, grey like Claude Code's own suggestion. On the empty box Tab
  // (or →) takes it and a second Tab moves on as usual. Enter sends,
  // Shift+Enter adds a line, and an empty box sends nothing.
  const sg = !(state.outbox[n.sessionId] || []).length && state.chat[n.sessionId]?.suggest;
  const suggest = sg?.text;
  const box = el("textarea", {
    id: "send-box", rows: 3, class: "send-box",
    placeholder: suggest ? `${suggest}  (Tab to use)` : sg?.pending ? "Suggesting a reply…"
      : asPrompt ? "Its next prompt" : "Your message",
    oninput: (e) => { state.drafts[n.sessionId] = e.target.value; },
    onkeydown: (e) => {
      if (e.isComposing) return;
      const plain = !e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey;
      if (e.key === "Enter" && plain) {
        e.preventDefault();
        if (box.value.trim()) button.click();
        return;
      }
      if (!((e.key === "Tab" && plain) || e.key === "ArrowRight") || !suggest || box.value) return;
      e.preventDefault();
      box.value = state.drafts[n.sessionId] = suggest;
    },
  });
  box.value = state.drafts[n.sessionId] || "";
  // The drawer is redrawn every poll, so "sending" lives in state, not on this button.
  const sending = state.sending.has(n.sessionId);
  const button = el("button", {
    class: "btn primary", disabled: sending,
    text: sending ? "Sending…" : asPrompt ? "Send prompt" : "Send message",
    onclick: () => {
      const sid = n.sessionId, text = box.value.trim();
      if (!text) return box.focus();
      state.drafts[sid] = "";
      // Back into the box to fix and resend, unless something new was typed meanwhile.
      sendAsBubble(n, text, () => { if (!(state.drafts[sid] || "").trim()) state.drafts[sid] = text; });
    },
  });
  return [
    el("h2", { text: asPrompt ? "Send a prompt" : "Send a message" }),
    box,
    el("p", { class: "muted small", text: (asPrompt
      ? "It wakes up with this as your next prompt, as if you had typed it."
      : "It arrives as a message from Let Them Talk and is read between its steps.") +
      " Enter sends; Shift+Enter adds a line." }),
    el("div", { class: "drawer-actions" }, button),
  ];
}

// Sends text to a chat, shown in it at once as your bubble, like a phone; the
// bubble gives way to the real message once the chat has read it (see
// settleOutbox). If sending fails, the bubble goes and failed() runs.
async function sendAsBubble(n, text, failed) {
  const sid = n.sessionId, out = { text, at: Date.now() / 1000, state: "sending" };
  (state.outbox[sid] ||= []).push(out);
  state.sending.add(sid);
  renderDrawer();
  try {
    if (await sendTo(n, text)) {
      out.state = "sent";
    } else {
      state.outbox[sid] = state.outbox[sid].filter((o) => o !== out);
      failed();
    }
  } finally {
    state.sending.delete(sid);
    renderDrawer();
    poll();
  }
}

async function agentAction(n, action, done) {
  try {
    const res = await api(`/api/board/${state.boardId}/${action}`, { jobId: n.jobId });
    done?.(res.result);
  } catch (e) {
    toast(e.message, "error", 0);
  }
  poll();
}

function backgroundSection(n) {
  // No saved conversation: whatever state it last reported, Claude Code can
  // only restart it, and only in a terminal (see attach_background).
  const restart = n.resumable === false;
  const blocked = !restart && n.agentState === "blocked";
  return [
    el("h2", { text: "Background agent" }),
    restart && el("p", { class: "small warn-text",
      text: "It has no saved conversation (it was stopped before its first reply finished), so it can't be " +
        "woken or answered. Restart it in a terminal first, then send it a prompt. Claude Code may ask " +
        "you there to trust its folder." }),
    blocked && el("p", { class: "small warn-text",
      text: `It's waiting for you (${n.waitingFor || "an answer"}). Open it in a terminal to answer.` }),
    el("div", { class: "drawer-actions" },
      el("button", { class: blocked || restart ? "btn primary" : "btn", text: restart ? "Restart in terminal" : "Open in terminal",
        onclick: () => agentAction(n, "agent-attach", (r) => r.opened
          ? toast(restart ? `Opened a terminal that restarts it (${r.command}).` : "Opened a terminal window attached to it.", "ok")
          : toast(`Run this in a terminal: ${r.command}`, "info", 0)) }),
      !restart && el("button", { class: "btn",
        text: state.logs[n.sessionId] ? "Hide its screen" : blocked ? "What is it asking?" : "Show its screen",
        onclick: () => state.logs[n.sessionId]
          ? (delete state.logs[n.sessionId], renderDrawer())
          : agentAction(n, "agent-logs", (r) => { state.logs[n.sessionId] = r.text; renderDrawer(); }) }),
      n.running && (n.status !== "idle" || blocked) && el("button", { class: "btn", text: "Stop",
        onclick: () => confirm(`Stop ${display(n)}? It stops whatever it is doing now, as Esc does ` +
          "in its terminal. It keeps running, and its terminal stays open.")
          && agentAction(n, "agent-stop", () => toast(`Stopped ${display(n)}. It's waiting for you.`, "ok")) }),
      el("button", { class: "btn danger", text: "Delete agent",
        onclick: () => confirm(`Delete the background agent ${display(n)}? Its conversation stays on disk.`)
          && agentAction(n, "agent-delete", () => { toast(`Deleted ${display(n)}.`, "ok"); closeDrawer(); }) })),
    state.logs[n.sessionId] && el("pre", { class: "logs mono", text: state.logs[n.sessionId] }),
  ];
}
