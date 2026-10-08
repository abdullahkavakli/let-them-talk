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
  popWire: null,         // arrow id shown in the pop-up (opened from a chat's Connections)
  popAgents: null,       // {sid, sub, pane}: the open chat's agents in their pop-up (sub: the agent picked; pane: "list" or "detail", what a narrow pop-up shows)
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

// Puts new contents into a panel that every poll redraws (the details, the
// Add agents list, Activity), but only when they differ from what it shows: a
// rebuild drops keyboard focus and any text selected in it. While text in it
// is selected with the mouse, it waits for a later poll. When it does change,
// focus goes back to the same control: by id, else by kind and label. When
// only clocks that tick (a duration, "12s ago": marked .tick) differ, their
// text is changed in place and nothing is rebuilt, so what is hovered,
// focused or turning there stays as it is.
function swapChildren(box, children) {
  const next = el("div", {}, children);
  if (next.innerHTML === box.innerHTML || retime(box, next)) return;
  const active = document.activeElement, picked = document.getSelection();
  const inBox = active && active !== box && box.contains(active);
  if (picked && !picked.isCollapsed && box.contains(picked.anchorNode) && !inBox) return;
  const keep = inBox ? focusKey(box, active) : null;
  box.replaceChildren(...next.childNodes);
  if (keep) refocus(box, keep);
}

function retime(box, next) {
  const shown = [...box.querySelectorAll(".tick")], fresh = [...next.querySelectorAll(".tick")];
  if (!shown.length || shown.length !== fresh.length) return false;
  const bare = (root) => {
    const copy = root.cloneNode(true);
    for (const t of copy.querySelectorAll(".tick")) t.textContent = "";
    return copy.innerHTML;
  };
  if (bare(box) !== bare(next)) return false;
  shown.forEach((t, i) => { if (t.textContent !== fresh[i].textContent) t.textContent = fresh[i].textContent; });
  return true;
}

const focusLabel = (e) => e.getAttribute("aria-label") || e.textContent.trim();
function focusKey(box, e) {
  if (e.id) return { id: e.id, start: e.selectionStart, end: e.selectionEnd };
  const same = [...box.querySelectorAll(e.tagName)].filter((x) => focusLabel(x) === focusLabel(e));
  return { tag: e.tagName, label: focusLabel(e), nth: same.indexOf(e) };
}
function refocus(box, k) {
  const e = k.id ? document.getElementById(k.id)
    : [...box.querySelectorAll(k.tag)].filter((x) => focusLabel(x) === k.label)[k.nth];
  if (!e) return;
  e.focus({ preventScroll: true });
  if (k.id) try { e.setSelectionRange(k.start, k.end); } catch { /* not a text box */ }
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
  // No reply at all (the server stopped or is restarting) is marked here, so
  // only that reads as "can't reach", not a bug in the code using a reply.
  const res = await fetch(path, opts).catch((e) => { throw Object.assign(e, { unreachable: true }); });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// What a failed request says: the server's reason, or that no reply came.
const failText = (e) => e?.unreachable
  ? "Couldn't reach Let Them Talk; it may have stopped or be restarting." : e.message;

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

// A drop-down drawn as glass, in place of a native <select> (the browser draws
// that list flat and square). `button` opens it and keeps the focus: ↑ ↓ Home
// End move through the rows, Enter or Space picks, Esc or a click elsewhere
// closes. fill() sets the rows: items ({ value, text, sub, title, current };
// sub is a quiet second line, a folder wrapping between its names; picking the
// current one only closes the list) and, under a thin divider, actions
// ({ text, run }). onpick(value) gets the item picked.
function dropMenu(button, onpick) {
  const menu = el("div", { id: `${button.id}-menu`, class: "menu", role: "listbox", popover: "auto" });
  button.setAttribute("popovertarget", menu.id);
  document.body.append(menu);
  let list = [], rows = [], active = -1, shape = "", lensed = false, spaceKept = false;
  const isOpen = () => menu.matches(":popover-open");
  const mark = (i) => {
    active = i;
    rows.forEach((row, k) => row.classList.toggle("active", k === i));
    if (rows[i]) button.setAttribute("aria-activedescendant", rows[i].id);
    else button.removeAttribute("aria-activedescendant");
  };
  const pick = (i) => {
    menu.hidePopover();
    if (!list[i].current) list[i].pick();
  };
  menu.addEventListener("beforetoggle", (e) => {
    button.setAttribute("aria-expanded", String(e.newState === "open"));
    if (e.newState !== "open") return;
    if (!lensed) { lensed = true; glass(menu, { scale: 14, blur: 6 }); }
    const r = button.getBoundingClientRect();
    menu.style.minWidth = `${Math.round(r.width)}px`;
    menu.style.display = "block";  // measured before it is drawn, to keep it on screen
    const w = menu.offsetWidth;
    menu.style.display = "";
    menu.style.left = `${Math.max(12, Math.min(r.left, innerWidth - w - 12))}px`;
    menu.style.top = `${Math.round(r.bottom + 8)}px`;
    mark(Math.max(0, list.findIndex((o) => o.current)));
  });
  menu.addEventListener("toggle", (e) => {
    if (e.newState === "open") rows[active]?.scrollIntoView({ block: "nearest" });
    else mark(-1);
  });
  button.setAttribute("aria-expanded", "false");
  button.addEventListener("keydown", (e) => {
    if (e.isComposing || e.altKey || e.ctrlKey || e.metaKey) return;
    const open = isOpen();
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) menu.showPopover();
      else if (rows.length) mark((active + (e.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length);
    } else if (open && (e.key === "Home" || e.key === "End")) {
      e.preventDefault();
      mark(e.key === "Home" ? 0 : rows.length - 1);
    } else if (open && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();  // not a press of the button, which would close it unpicked
      spaceKept = e.key === " ";
      if (rows[active]) pick(active);
      else menu.hidePopover();
    } else if (open && e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();  // closes the list only, not the details behind it
      menu.hidePopover();
    } else if (open && e.key === "Tab") {
      menu.hidePopover();
    }
  });
  button.addEventListener("keyup", (e) => {
    if (e.key === " " && spaceKept) { spaceKept = false; e.preventDefault(); }  // a Space press clicks on release
  });
  addEventListener("resize", () => { if (isOpen()) menu.hidePopover(); });
  return {
    fill({ items, actions = [] }) {
      list = [...items.map((o) => ({ ...o, pick: () => onpick(o.value) })), ...actions.map((o) => ({ ...o, pick: o.run, action: true }))];
      const next = JSON.stringify([items, actions.map((o) => o.text)]);
      if (next === shape) return;  // a refresh that changes nothing leaves the open list as it is
      shape = next;
      menu.replaceChildren(...list.flatMap((o, i) => [
        ...(o.action && i > 0 && !list[i - 1].action ? [el("div", { class: "menu-sep", role: "separator" })] : []),
        el("div", {
          id: `${menu.id}-${i}`, role: "option", class: `menu-item${o.current ? " current" : ""}${o.action ? " action" : ""}`,
          title: o.title, "aria-selected": String(!!o.current),
          onpointerdown: (e) => e.preventDefault(),  // the focus stays on the button
          onpointermove: () => { if (active !== i) mark(i); },
          onclick: () => pick(i),
        }, el("span", { text: o.text }), o.sub && el("span", { class: "menu-sub" }, pathNodes(o.sub))),
      ]));
      rows = [...menu.querySelectorAll(".menu-item")];
      if (active >= 0) mark(Math.min(active, rows.length - 1));
    },
  };
}

// The top bar's Board picker: the boards (the current one ticked) and, under
// them, New board….
const boardMenu = dropMenu($("#board-select"), (id) => selectBoard(id));

function fillBoardSelect(boards) {
  $("#board-name").textContent = boards.find((b) => b.id === state.boardId)?.title || "";
  $("#board-select").disabled = boards.length === 0;
  boardMenu.fill({
    items: boards.map((b) => ({ value: b.id, text: b.title, sub: b.folder, title: b.folder, current: b.id === state.boardId })),
    actions: [{ text: "New board…", run: newBoard }],
  });
}

function selectBoard(id) {
  state.boardId = id;
  state.view = null;  // the old board's; drawn now, it would use up the new one's re-centre and save its pan
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
    // A reply that comes after you switched boards is for the old one: dropped
    // (the switch started its own poll).
    const id = state.boardId;
    let view;
    try {
      view = await api(`/api/state?board=${encodeURIComponent(id)}${state.showSubs ? "&subagents=1" : ""}`);
    } catch (e) {
      console.warn("poll failed", e);
      if (e.unreachable) reachable(false);
    }
    if (state.boardId !== id) return;
    if (view) {
      state.view = view;
      reachable(true);
      try {
        render();
        if (state.selected?.type === "node") loadDetails(state.selected.id);
        else if (state.selected?.type === "sub") loadSub(state.selected);
        else if (state.selected?.type === "wire") loadTalk(state.selected.id);
        if (state.popWire && state.popWire !== state.selected?.id) loadTalk(state.popWire);
        if (state.popAgents?.sub) loadPopSub();
        state.drawError = null;
      } catch (e) {
        drawFailed(e);
      }
    }
  }
  state.pollTimer = setTimeout(poll, POLL_MS);
}

// A bug while drawing the board: the server did answer, so it's said as what
// it is, once (not on every poll), and never as "can't reach".
function drawFailed(e) {
  console.error("drawing the board failed", e);
  if (state.drawError === e.message) return;
  state.drawError = e.message;
  toast(`Part of the board couldn't be drawn (${e.message}). Reloading the page may help.`, "error");
}

// Whether the server answers. fetch() throws a TypeError when no reply comes
// (an error status means the server is up). After two polls in a row without
// one, a banner says so and the board, which may be out of date, fades.
function reachable(ok, text) {
  state.misses = ok ? 0 : (state.misses || 0) + 1;
  const down = !ok && (state.misses >= 2 || !!text);
  document.body.classList.toggle("offline", down);
  $("#offline").hidden = !down;
  if (down) $("#offline").textContent = text ||
    "Can't reach Let Them Talk. Trying again; the board may be out of date until it answers.";
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
  renderBoardFolderButton();
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
  placeHint();
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
        el("span", { class: `badge state ${{ needs: "warn", waiting: "warn", failed: "danger" }[st.dot] || ""}`, text: st.text,
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

// An arrow each way between two cards (a team's master and an agent): the two
// run side by side between the cards' facing edges, the one from the card on
// the left above, each with its label, instead of one looping round the cards.
const PAIR_GAP = 10;
function pairWire(a, b) {
  const back = nodePos(a).x > nodePos(b).x || (nodePos(a).x === nodePos(b).x && a.sessionId > b.sessionId);
  const dy = back ? PAIR_GAP : -PAIR_GAP, at = (pt) => ({ x: pt.x, y: pt.y + dy });
  if (!back) {
    const p = at(anchor(a, "out")), q = at(anchor(b, "in")), mid = midpoint(p, q);
    return { p, q, d: curve(p, q), mid: { x: mid.x, y: mid.y - 6 } };
  }
  const p = at(anchor(a, "in")), q = at(anchor(b, "out"));
  const dx = Math.max(20, Math.abs(p.x - q.x) / 2), down = -bend(p, q);
  return { p, q, d: `M${p.x} ${p.y} C${p.x - dx} ${p.y + down}, ${q.x + dx} ${q.y + down}, ${q.x} ${q.y}`,
    mid: { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 + 0.75 * down + 6 } };
}

function renderWires() {
  const layer = $("#wire-layer");
  const labels = $("#labels");
  // Labels are rebuilt on every render; keep keyboard focus on the same one.
  const focused = labels.contains(document.activeElement) ? document.activeElement.dataset.id : null;
  layer.replaceChildren();
  labels.replaceChildren();
  const arrows = new Set(state.view.board.connections.map((c) => `${c.from}>${c.to}`));
  for (const c of state.view.board.connections) {
    const a = nodeById(c.from), b = nodeById(c.to);
    if (!a || !b) continue;
    const pair = arrows.has(`${c.to}>${c.from}`) && pairWire(a, b);
    const p = pair ? pair.p : anchor(a, "out"), q = pair ? pair.q : anchor(b, "in");
    const d = pair ? pair.d : curve(p, q);
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
    const mid = pair ? pair.mid : midpoint(p, q);
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

// Details are asked for on every poll, and replies can come back out of order:
// one older than what is already shown is dropped.
let asked = 0;
const shown = {};  // what -> number of the newest request shown
function newest(what) {
  const n = ++asked;
  return () => n > (shown[what] || 0) && (shown[what] = n);
}

async function loadSub(sel) {
  const key = `${sel.parent}:${sel.id}`, current = newest(`sub:${key}`);
  const data = await api(`/api/subagent?session=${encodeURIComponent(sel.parent)}&agent=${encodeURIComponent(sel.id)}`)
    .catch((e) => ({ error: e.message }));
  if (!current()) return;
  state.subInfo[key] = data;
  if (state.selected?.type === "sub" && state.selected.id === sel.id) renderDrawer();
}

const ago = (ms) => ms ? `${fmtDur(Math.max(0, Date.now() - ms))} ago` : null;

// Claude writes Markdown; a bubble shows it lightly: **bold**, `code` and code
// blocks, headings as bold lines, list items with •, a table as rows of cells
// (its |---| line goes), [links](…) as their words. Built from text nodes,
// never HTML, and all inline, so a folded bubble still cuts off by lines.
function richText(text) {
  const out = [];
  const line = (...nodes) => { if (out.length) out.push("\n"); out.push(...nodes); };
  let fence = false;
  for (const raw of String(text).split("\n")) {
    if (/^\s*```/.test(raw)) { fence = !fence; continue; }
    if (fence) { line(el("code", { text: raw })); continue; }
    if (/^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*(:?-{3,}:?)?\s*$/.test(raw) || /^\s*([-*_])(\s*\1){2,}\s*$/.test(raw)) continue;
    const head = raw.match(/^\s*#{1,6}\s+(.*)$/), row = raw.match(/^\s*\|(.*)\|\s*$/);
    if (head) line(el("strong", {}, inlineMd(head[1])));
    else if (row) line(...inlineMd(row[1].split("|").map((cell) => cell.trim()).join("  ·  ")));
    else line(...inlineMd(raw.replace(/^(\s*)[-*+]\s+/, "$1• ")));
  }
  return out;
}

function inlineMd(s) {
  return s.split(/(`[^`]+`)/).flatMap((part) => /^`[^`]+`$/.test(part)
    ? [el("code", { text: part.slice(1, -1) })]
    : part.replace(/\[([^\]]+)\]\([^)\s]+\)/g, "$1").split(/(\*\*[^*]+\*\*|__[^_]+__)/)
      .map((b) => /^(\*\*|__).+\1$/.test(b) ? el("strong", { text: b.slice(2, -2) }) : b))
    .filter((x) => x !== "");
}

function foldBubble(key, text) {
  const open = !!state.chatOpen[key];
  const long = text.length > FOLD_CHARS || text.split("\n").length > FOLD_LINES;
  return [el("div", { class: "bubble" + (long && !open ? " folded" : "") }, richText(text)),
    long && el("button", { class: "fold", text: open ? "Show less" : "Show all",
      onclick: () => { state.chatOpen[key] = !open; renderDrawer(); } })];
}

// An agent's details: its name and state, a short list of facts, its steps as
// a timeline, what it said and the task it was given. What its row in the
// chat's list knows (state, model, time, tokens, tool calls, workflow) shows at
// once, the rest when its details come. back: {text, label, go} for the
// button at the top (in the panel: back to the chat that started it; in a
// pop-up too narrow for the list beside it: back to the list); toChat: what
// clicking that chat's name does.
function subDetails(sel, back, toChat) {
  const key = `${sel.parent}:${sel.id}`, d = state.subInfo[key], n = nodeById(sel.parent);
  toChat ||= () => select_({ type: "node", id: n.sessionId });
  back ||= n && { text: display(n), label: `Back to ${display(n)}`, go: toChat };
  const known = d && !d.error ? Object.fromEntries(Object.entries(d).filter(([, v]) => v != null)) : {};
  const a = { ...listedAgent(sel.parent, sel.id), ...known };
  const head = [back && el("button", { class: "btn back", title: back.label, "aria-label": back.label, onclick: back.go },
    el("span", { class: "back-text", text: back.text })),
  el("h3", { text: a.label || sel.label || "Subagent" }), a.state && el("p", { class: "sub-state" }, stateBadge(a.state))];
  if (d?.error) return [...head, el("p", { class: "error small", text: d.error })];
  const fact = (name, value, cls) => value ? el("div", {}, el("dt", { text: name }), el("dd", { class: cls }, value)) : null;
  const facts = el("dl", { class: "facts" }, ...[
    fact("Model", modelName(a.model)), fact("Duration", fmtDur(a.durationMs), "tick"),
    a.tokens != null && fact("Tokens", fmtCount(a.tokens)), a.toolCalls != null && fact("Tool calls", String(a.toolCalls)),
    fact("Started by", n ? el("button", { class: "chip-link", type: "button", title: `Show ${display(n)}`, onclick: toChat },
      el("span", { class: `dot ${cardStatus(n).dot}` }), el("span", { text: display(n) })) : "a chat that isn't on this board"),
    fact("Workflow", a.workflow && [a.workflow, a.phase].filter(Boolean).join(" · ")),
    fact("Type", !a.workflow && a.kind)].filter(Boolean));
  if (!d) return [...head, facts, el("p", { class: "muted small", text: "Loading…" })];
  const running = d.state === "running", steps = [...d.steps].reverse();
  return [
    ...head,
    facts,
    ...subActions(sel, d, n),
    el("h2", { text: running ? "Doing now" : "Recent steps" }),
    steps.length ? el("div", { class: "sub-steps" }, ...steps.map((s, i) => el("div", { class: `sub-step${i ? "" : " now"}${running ? " running" : ""}` },
      el("span", { class: "mono", text: s.text }), el("span", { class: "when tick", text: ago(s.at) }))))
      : el("p", { class: "muted small", text: running ? "Getting started…" : "It took no steps." }),
    el("h2", { text: running ? "Latest message" : "Final message" }),
    ...(d.said ? [el("div", { class: "msg-meta tick", text: ago(d.said.at) }), ...foldBubble(`${key}:said`, d.said.text)]
      : [el("p", { class: "muted small", text: running ? "It hasn't written anything yet; it reports when it finishes." : "None." })]),
    el("h2", { text: "Its task" }),
    ...(d.task ? foldBubble(`${key}:task`, d.task) : [el("p", { class: "muted small", text: "Not recorded." })]),
  ];
}

// A subagent runs inside the chat that started it, and only that chat can
// reach it: your message goes to the chat, which passes it on (SendMessage),
// and its terminal is that chat's, where Claude Code lists it under the prompt
// box (↑/↓ picks it). Shown wherever its details are (panel or pop-up).
const subDrafts = {}, subSent = {};  // "parent:agent" -> text in its box / when a message last went
const redrawSub = () => { renderDrawer(); renderAgentsPop(); };

function subActions(sel, d, n) {
  if (!n?.live) return [];
  const key = `${sel.parent}:${sel.id}`, name = d.label || sel.label || "it";
  const attach = n.background && n.jobId && n.resumable !== false && el("button", {
    class: "btn", text: "Open in terminal", title: `${display(n)}'s terminal: pick "${name}" with ↑/↓ under its prompt box`,
    onclick: () => agentAction(n, "agent-attach", (r) => r.opened
      ? toast(`Opened ${display(n)}'s terminal: pick "${name}" with ↑/↓ under its prompt box.`, "ok")
      : toast(`Run this in a terminal: ${r.command}`, "info", 0)),
  });
  const inside = !attach && (n.editor ? `It runs inside ${display(n)} in ${n.editor}.`
    : n.entrypoint === "cli" ? `It runs inside ${display(n)}'s terminal window: pick it there with ↑/↓ under the prompt box.` : "");
  const terminal = [attach && el("div", { class: "drawer-actions" }, attach), inside && el("p", { class: "muted small", text: inside })];
  if (!canReach(n)) return terminal;
  // The same box as a chat's Send box (sendSection): text and images, Enter sends.
  const images = state.images[key] || [];
  const ready = () => !!(box.value.trim() || (state.images[key] || []).length);
  const box = el("textarea", {
    id: "sub-box", rows: 1, class: "send-box", placeholder: "Your message",
    oninput: (e) => { subDrafts[key] = e.target.value; composer.classList.toggle("ready", ready()); },
    onpaste: (e) => {  // a screenshot goes in as an image; copied text pastes as text
      const files = [...(e.clipboardData?.files || [])];
      if (!files.length || e.clipboardData.getData("text/plain")) return;
      e.preventDefault();
      addImages(key, files, redrawSub);
    },
    onkeydown: (e) => {
      if (e.isComposing || e.key !== "Enter" || e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
      e.preventDefault();
      if (ready()) button.click();
    },
  });
  box.value = subDrafts[key] || "";
  const sending = subSent[key] === "sending", label = sending ? "Sending…" : "Send message";
  const button = el("button", {
    class: "composer-send", disabled: sending, "aria-label": label, title: label,
    onclick: async () => {
      const text = box.value.trim(), sent = state.images[key] || [];
      if (!ready()) return box.focus();
      subSent[key] = "sending";
      subDrafts[key] = "";
      state.images[key] = [];
      redrawSub();
      try {
        await api(`/api/board/${state.boardId}/send-subagent`, { sessionId: sel.parent, agentId: sel.id, label: name,
          text, images: sent.map((i) => ({ data: i.data })) });
        subSent[key] = Date.now() / 1000;
        sent.forEach((i) => URL.revokeObjectURL(i.url));
      } catch (e) {
        delete subSent[key];
        // back into the box to fix and resend, unless something new was added meanwhile
        if (!(subDrafts[key] || "").trim()) subDrafts[key] = text;
        if (!(state.images[key] || []).length) state.images[key] = sent;
        toast(failText(e), "error");
      }
      redrawSub();
    },
  }, sendIcon());
  const composer = el("div", { class: `composer${box.value.trim() || images.length ? " ready" : ""}` },
    images.length > 0 && el("div", { class: "composer-images" }, ...imageThumbs(key, redrawSub)),
    el("div", { class: "composer-row" }, box, button));
  const last = subSent[key];
  return [
    el("h2", { text: "Send it a message" }),
    composer,
    el("p", { class: "composer-hint", text: [`It goes to ${display(n)}, which passes it on to this agent.`,
      typeof last === "number" && `Last one went at ${clock(last)}.`,
      "Enter sends; Shift+Enter adds a line. Paste or drop images to send them too."].filter(Boolean).join(" ") }),
    ...terminal,
  ];
}

// A drawn "+", so it sits in the middle of its round button whatever the font.
function plusIcon() {
  const icon = svg("svg", { width: 12, height: 12, viewBox: "0 0 12 12", "aria-hidden": "true" });
  icon.append(svg("path", { d: "M6 1.5v9M1.5 6h9", stroke: "currentColor", "stroke-width": 1.6, "stroke-linecap": "round" }));
  return icon;
}

function renderAvailable() {
  const box = $("#available");
  const groups = {};
  for (const s of state.view.available) (groups[where(s)] ||= []).push(s);
  const folders = Object.keys(groups).sort();
  if (folders.length === 0) {
    swapChildren(box, [el("p", { class: "muted small", text: "Every running session is already on this board." })]);
    return;
  }
  swapChildren(box, folders.map((cwd) => el("div", { class: "folder-group" },
    el("div", { class: "folder-head" },
      el("p", { class: "folder-name path", title: cwd }, pathNodes(cwd)),
      el("button", { class: "btn new-here", text: "+ New agent", title: `Start a new agent in ${cwd}`,
        "aria-label": `New agent in ${cwd}`, onclick: () => openNewAgent(cwd) })),
    ...groups[cwd].map((s) => el("div", { class: "avail-row" },
      el("span", { class: `dot ${s.status}`, title: s.status, role: "img", "aria-label": s.status }),
      el("span", { class: "name", text: display(s), title: [s.name && `@${s.name}`, onWindows(s) ? "Windows" : "WSL", opener(s), s.status].filter(Boolean).join(" · ") }),
      el("button", { class: "btn add", title: "Add to this board", "aria-label": `Add ${display(s)} to this board`,
        onclick: () => addNode(s.sessionId) }, plusIcon()))))));
}

function renderActivity() {
  const items = state.view.board.activity.slice(0, 30);
  $("#activity-count").textContent = items.length ? `(${state.view.board.activity.length})` : "";
  swapChildren($("#activity"), items.length ? items.map((a) =>
    el("li", { class: a.level }, el("time", { text: clock(a.t) }), a.text)) :
    [el("li", { class: "muted", text: "Nothing yet." })]);
}

// Activity is folded away unless you open it; the choice is remembered.
$("#activity-box").open = store("ltt.activityOpen") === true;
$("#activity-box").addEventListener("toggle", () => store("ltt.activityOpen", $("#activity-box").open));

// ------------------------------------------------------------------- drawer

function select_(sel) {
  if (!(sel.type === "node" && sel.id === state.renaming)) state.renaming = null;
  // What focus goes back to when the details close (one opened from inside them keeps the first).
  if (!$("#drawer").contains(document.activeElement)) state.opener = { el: document.activeElement, sel };
  state.selected = sel;
  render();
  renderDrawer();
  // The details may open over the card: the board moves it out from under them.
  const card = sel.type === "node" && $(`#nodes [data-id="${sel.id}"]`);
  if (card && !$("#drawer").hidden) reveal(card);
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
  else if (state.popWire === id) renderWirePop();
}

async function loadDetails(sid) {
  const get = (path, more = "") => api(`${path}?session=${encodeURIComponent(sid)}${more}`).catch((e) => ({ error: e.message }));
  const current = newest(`node:${sid}`);
  // watch=1: this drawer is open, so the chat's mod may make it a suggestion
  const [agents, chat] = await Promise.all([get("/api/agents"), get("/api/chat", "&watch=1")]);
  if (!current()) return;
  [state.agents[sid], state.chat[sid]] = [agents, chat];
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
    const i = mine.findIndex((m) => m.at >= o.at - 30 && (m.via === "app" || imageTags(m.text).trim() === o.text));
    if (i < 0) return true;
    mine.splice(i, 1);
    return false;
  });
}

function closeDrawer() {
  // Focus in the details goes back to what opened them, not to the page.
  const back = $("#drawer").contains(document.activeElement) && state.opener;
  state.selected = null;
  state.renaming = null;
  $("#drawer").hidden = true;
  if (state.view) render();
  if (back) returnFocus(back);
}

function returnFocus({ el, sel }) {
  const target = el?.isConnected && el !== document.body ? el
    : sel.type === "node" ? $(`#nodes [data-id="${sel.id}"]`)
    : sel.type === "wire" ? $(`#labels [data-id="${sel.id}"]`)
    : $(`#subagents [data-agent="${sel.id}"]`);
  (target || $("#canvas")).focus({ preventScroll: true });
}

function renderDrawer() {
  renderWirePop();
  renderAgentsPop();
  const body = $("#drawer-body");
  const sel = state.selected;
  if (!sel) return;
  // A click needs the same button under the press and the release, so while
  // a mouse button is held in the panel it is redrawn only after the release.
  if (state.pressing) {
    state.redrawAfterPress = true;
    return;
  }
  drawDrawer(body, sel);
}

function drawDrawer(body, sel) {
  if (sel.type === "wire") {
    const c = connById(sel.id);
    if (!c) return closeDrawer();
    swapChildren(body, wireDetails(c).filter(Boolean));
  } else if (sel.type === "sub") {
    swapChildren(body, subDetails(sel).filter(Boolean));
  } else {
    const n = nodeById(sel.id);
    if (!n) return closeDrawer();
    swapChildren(body, nodeDetails(n).filter(Boolean));
  }
  $("#drawer").hidden = false;
}

$("#drawer").addEventListener("pointerdown", () => { state.pressing = true; });
$("#wire-pop").addEventListener("pointerdown", () => { state.pressing = true; });

// A connection clicked in a chat's Connections opens in a pop-up over the
// board, so the chat's details stay underneath. Redrawn with the panel.
function openWirePop(id) {
  closeAgentsPop();  // one pop-up at a time
  state.popWire = id;
  loadTalk(id);
  renderWirePop();
  if (!$("#wire-pop").open) $("#wire-pop").showModal();
}

function renderWirePop() {
  if (!state.popWire) return;
  if (state.pressing) {
    state.redrawAfterPress = true;
    return;
  }
  const c = connById(state.popWire);
  if (!c) return closeWirePop();
  swapChildren($("#wire-pop-body"), wireDetails(c, closeWirePop).filter(Boolean));
}

function closeWirePop() {
  state.popWire = null;
  if ($("#wire-pop").open) $("#wire-pop").close();
}

$("#wire-pop").addEventListener("close", () => { state.popWire = null; });
$("#wire-pop-close").addEventListener("click", closeWirePop);
$("#wire-pop").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeWirePop(); });  // its backdrop

// A chat's agents open in a pop-up over the board from the row in its
// details, which stay underneath; it goes with them (closed when they close or
// show something else). It has two panes: the agents on the left, and on the
// right the details of the one picked, with the list staying where it is (a
// narrow pop-up shows one pane at a time, with a way back to the list).
// Redrawn with the panel.
$("#agents-pop").addEventListener("pointerdown", () => { state.pressing = true; });

// It opens on what is running now, if anything (its card unfolds, if you had
// folded it), with the keyboard on that row.
function openAgentsPop(sid) {
  closeWirePop();  // one pop-up at a time
  const data = state.agents[sid], first = data && !data.error && everyAgent(data).find((a) => a.state === "running");
  state.popAgents = { sid, sub: first ? { id: first.id, label: first.label || first.description } : null, pane: "list" };
  if (first) {
    state.runOpen[data.workflows.find((r) => r.agents.includes(first))?.runId || `direct:${sid}`] = true;
    loadPopSub();
  }
  renderAgentsPop();
  if (!$("#agents-pop").open) $("#agents-pop").showModal();
  $('#agents-pop-list .agent-row[tabindex="0"]')?.focus();
}

function renderAgentsPop() {
  const p = state.popAgents;
  if (!p) return;
  if (state.pressing) {
    state.redrawAfterPress = true;
    return;
  }
  const n = state.selected?.type === "node" && state.selected.id === p.sid && nodeById(p.sid);
  if (!n) return closeAgentsPop();
  const data = state.agents[n.sessionId];
  const { count, running } = data && !data.error ? agentCounts(data) : {};
  const moveFocusTo = data && !data.error ? leaveGone(p, data) : undefined;
  // the title above the list stays; under it the chat, how many agents and how many run
  const note = [display(n), count != null && `${count} agent${count === 1 ? "" : "s"}`, running && `${running} running`]
    .filter(Boolean).join(" · ");
  if ($("#agents-pop-note").textContent !== note) $("#agents-pop-note").textContent = note;
  $("#agents-pop").dataset.pane = p.pane;
  swapChildren($("#agents-pop-list"), agentsPopList(n).filter(Boolean));
  swapChildren($("#agents-pop-detail"), agentsPopDetail(data).filter(Boolean));
  if (moveFocusTo != null) {
    (moveFocusTo ? document.getElementById(`agent-row-${moveFocusTo}`) : $("#agents-pop-list"))?.focus({ preventScroll: true });
  }
}

// An agent that has dropped out of its chat's list (a workflow retried it) can't
// stay picked or hold the keyboard: the pick and the focus go to the next row in
// view, else the one before. With none left, nothing is picked and the focus goes
// to the list (the arrows go on from there). Returns the id of the row the focus
// should go to after the redraw ("" for the list), or nothing when it needn't move.
function leaveGone(p, data) {
  const listed = new Set(everyAgent(data).map((a) => a.id));
  const held = document.activeElement?.closest?.("#agents-pop-list .agent-row")?.dataset.agent;
  const pickGone = p.sub && !listed.has(p.sub.id), heldGone = held && !listed.has(held);
  if (!pickGone && !heldGone) return;
  const left = [...document.querySelectorAll("#agents-pop-list .agent-row")]
    .filter((r) => listed.has(r.dataset.agent) && !r.closest("details:not([open])"));
  const near = (id) => {
    const gone = document.getElementById(`agent-row-${id}`);
    const side = (bit) => left.filter((r) => gone?.compareDocumentPosition(r) & bit);
    return side(Node.DOCUMENT_POSITION_FOLLOWING)[0] || side(Node.DOCUMENT_POSITION_PRECEDING).at(-1);
  };
  if (pickGone) {
    const to = near(p.sub.id);
    clearTimeout(p.loadTimer);  // a pick by key may still be waiting to ask for it
    p.sub = to ? { id: to.dataset.agent, label: to.querySelector(".agent-label").textContent } : null;
    if (to) loadPopSub();
    else p.pane = "list";
  }
  if (heldGone) return near(held)?.dataset.agent ?? "";
}

function closeAgentsPop() {
  state.popAgents = null;
  if ($("#agents-pop").open) $("#agents-pop").close();
}

function agentsPopList(n) {
  const cards = agentsList(n, openPopSub);
  // One row in view is in the tab order, the picked one (else the first):
  // Tab enters the list there and the arrows go on.
  const shown = cards.flatMap((c) => [...c.querySelectorAll(".agent-row")]).filter((r) => !r.closest("details:not([open])"));
  const stop = shown.find((r) => r.hasAttribute("aria-current")) || shown[0];
  if (stop) stop.tabIndex = 0;
  return cards;
}

function agentsPopDetail(data) {
  const p = state.popAgents;
  if (!p.sub) return popNothingPicked(data);
  return subDetails({ parent: p.sid, ...p.sub }, { text: "All agents", label: "Back to all agents", go: backToAgents },
    closeAgentsPop);
}

// The right pane before an agent is picked.
function popNothingPicked(data) {
  const none = !data || data.error || !agentCounts(data).count;
  const icon = svg("svg", { class: "empty-icon", width: 44, height: 44, viewBox: "0 0 44 44", "aria-hidden": "true" });
  icon.append(svg("rect", { x: 5, y: 8, width: 34, height: 28, rx: 6 }), svg("path", { d: "M17 8v28M9.5 15h4M9.5 20h4M9.5 25h4" }));
  return [el("div", { class: "pop-empty" }, icon,
    el("p", { class: "pop-empty-title", text: none ? "No agents to show" : "No agent picked" }),
    !none && el("p", { class: "muted small", text: "Pick one on the left to see its steps, its latest message and its task. " +
      "↑ and ↓ move between agents." }))];
}

// Picks an agent: its details show on the right, the list stays as it is. A
// pick by the arrow keys asks for them a moment later, so a key held down
// doesn't ask for every row it passes.
function pickPopSub(id, label, byKey) {
  const p = state.popAgents;
  if (p.sub?.id === id) return;
  p.sub = { id, label };
  $("#agents-pop-detail").scrollTop = 0;
  clearTimeout(p.loadTimer);
  if (byKey) p.loadTimer = setTimeout(() => { if (state.popAgents === p) loadPopSub(); }, 120);
  else loadPopSub();
  renderAgentsPop();
}

// A click (or Enter) on a row: picks it, and a narrow pop-up swaps the list for its details.
function openPopSub(id, label) {
  pickPopSub(id, label);
  state.popAgents.pane = "detail";
  renderAgentsPop();
  document.getElementById(`agent-row-${id}`)?.focus({ preventScroll: true });  // some browsers don't focus a clicked button
  $("#agents-pop-detail .back")?.focus({ preventScroll: true });  // only shown in a narrow pop-up
}

function backToAgents() {
  const p = state.popAgents;
  p.pane = "list";
  renderAgentsPop();
  document.getElementById(`agent-row-${p.sub?.id}`)?.focus({ preventScroll: true });
}

// ↑ and ↓ move the pick through the rows in view (Home and End to the first
// and last), as in a list in Finder. On a card's header or its button, ↓ and ↑
// go to the next row that way.
$("#agents-pop-list").addEventListener("keydown", (e) => {
  const rows = [...e.currentTarget.querySelectorAll(".agent-row")].filter((r) => !r.closest("details:not([open])"));
  if (!rows.length || !["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key) || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  const from = document.activeElement, on = rows.indexOf(from);
  const after = rows.findIndex((r) => from.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING);
  if (e.key === "ArrowDown" && on < 0 && after < 0) return;  // a header below the last row: nowhere further down
  const at = on >= 0 ? on : (after < 0 ? rows.length : after) - (e.key === "ArrowDown" ? 1 : 0);
  const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: rows.length - 1 }[e.key];
  e.preventDefault();
  const row = rows[Math.min(Math.max(to, 0), rows.length - 1)];
  pickPopSub(row.dataset.agent, row.querySelector(".agent-label").textContent, true);
  document.getElementById(row.id).focus();  // the pick redraws the list: its row is a new element
});

async function loadPopSub() {
  const p = state.popAgents, data = p && state.agents[p.sid];
  // not for an agent that is no longer in its chat's list
  if (!p?.sub || (data && !data.error && !everyAgent(data).some((a) => a.id === p.sub.id))) return;
  await loadSub({ parent: p.sid, ...p.sub });
  renderAgentsPop();
}

$("#agents-pop").addEventListener("close", () => {
  state.popAgents = null;
  // focus goes back to the line that opened it, even if a redraw replaced it
  if (document.activeElement === document.body) $("#drawer .agents-line")?.focus({ preventScroll: true });
});
$("#agents-pop-close").addEventListener("click", closeAgentsPop);
$("#agents-pop").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeAgentsPop(); });  // its backdrop
new MutationObserver(() => { if ($("#drawer").hidden) closeAgentsPop(); })
  .observe($("#drawer"), { attributes: true, attributeFilter: ["hidden"] });

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

function wireDetails(c, close = closeDrawer) {
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
    // a team's arrow (New workflow with agents) sends no notes: its ends know each other from their first prompts
    c.team ? el("p", { class: "muted small", text: `No notes: both know each other from their first prompts, as team "${c.team}".` })
      : group(`notes:${c.id}`, failed, [el("span", { class: "run-name", text: "Notes sent when connected" })], notes),
    el("div", { class: "drawer-actions" },
      failed && el("button", { class: "btn", text: "Resend failed notes", onclick: () => act("resend", { id: c.id }) }),
      !c.team && !c.notes.from.enabled && a?.live && el("button", {
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
          if (await act("disconnect", { id: c.id, notify: notify.checked })) close();
        },
      })),
  ];
}

function nodeDetails(n) {
  const conns = state.view.board.connections.filter((c) => c.from === n.sessionId || c.to === n.sessionId);
  // In the card's words (a background agent's own state: working, needs you, done …).
  const status = n.live ? cardStatus(n).text : "session ended";
  // A background agent that can't go on without you (asking you, or needing a
  // restart) shows that first, above its messages.
  const stuck = n.background && (n.resumable === false || n.agentState === "blocked");
  return [
    ...nameHeading(n),
    // The facts fold into one line; the choice is remembered.
    el("details", {
      class: "info", open: store("ltt.infoOpen") === true,
      ontoggle: (e) => store("ltt.infoOpen", e.target.open),
    }, el("summary", { class: "muted small",
      text: [status, n.model && modelName(n.model), n.live && opener(n)]
        .filter(Boolean).join(" · ") }),
    el("dl", {},
      n.alias && n.title && [el("dt", { text: "Title" }), el("dd", { text: n.title })],
      el("dt", { text: "Address" }), el("dd", { class: "mono small", text: `@${n.name}` }),
      el("dt", { text: "Status" }), el("dd", { text: n.waitingFor ? `${status} (waiting for: ${n.waitingFor})` : status }),
      el("dt", { text: "Runs on" }), el("dd", { text: onWindows(n) ? "Windows" : hostLabel() }),
      el("dt", { text: "Folder" }), el("dd", { class: "small path" }, pathNodes(where(n))),
      n.messageBlock && [el("dt", { text: "Notes" }), el("dd", { class: "small", text: `Can't receive notes. ${n.messageBlock}` })],
      n.live && [el("dt", { text: "Opened in" }), el("dd", { text: opener(n) || "?" })],
      n.model && [el("dt", { text: "Model" }), el("dd", { text: modelName(n.model) })],
      el("dt", { text: "Session" }), el("dd", { class: "mono small", text: n.sessionId }))),
    (n.editor || continuable(n)) && el("div", { class: "drawer-actions" }, n.editor && el("button", {
      class: "btn primary", text: n.live ? "Open in IDE" : "Reopen in IDE",
      title: `Shows this chat in ${n.editor}`,
      onclick: () => { window.location.href = editorLink(n.editor, { session: n.sessionId }); },
    }), n.editor && !onWindows(n) && terminalButton(n),
    continuable(n) && conversationButton(n, "Continue in", "btn primary")),
    ...(stuck ? backgroundSection(n) : []),
    ...chatSection(n),
    ...sendSection(n),
    ...(n.background && !stuck ? backgroundSection(n) : []),
    ...agentsSection(n),
    // Its arrows fold away (the choice is remembered); one opens in a pop-up.
    ...(conns.length ? [el("details", {
      class: "conns", open: store("ltt.connsOpen") === true,
      ontoggle: (e) => store("ltt.connsOpen", e.target.open),
    }, el("summary", {}, el("h2", { text: `Connections (${conns.length})` })),
    el("ul", { class: "conn-list" }, ...conns.map((c) => {
      const other = nodeById(c.from === n.sessionId ? c.to : c.from), why = c.reason.trim();
      const name = other ? display(other) : "?", dir = c.from === n.sessionId ? "→" : "←";
      return el("li", {}, el("button", {
        class: "conn-row", type: "button", title: `${dir} ${name}${why ? `: ${why}` : ""}`,
        onclick: () => openWirePop(c.id),
      }, el("span", { class: "dir", text: dir }), el("span", { class: "name", text: name }),
      why && el("span", { class: "why", text: why })));
    })))] : [el("h2", { text: "Connections" }), el("p", { class: "muted small", text: n.messageBlock
      ? "None. This session can't be connected until it can receive notes."
      : "None. Drag the blue handle onto another agent to connect them." })]),
    // what can be done with the card itself, apart from the rest
    el("div", { class: "drawer-foot" },
      handoffable(n) && el("div", { class: "drawer-actions" }, handoffButton(n)),
      handoffNote(n),
      endControls(n),
      n.background && deleteControls(n),
      removeControls(n, conns)),
  ];
}

// A chat's conversation in the editor's Claude panel. The panel finds a
// conversation only in a window on its folder, and the link goes to the
// editor window in front, so the server opens the folder first (or brings its
// window forward) and the link a moment later. A chat that isn't running and
// has no editor of its own gets "Continue in" at the top of its details; a
// background agent gets "Open in" in its own section. A running one holds its
// conversation, and Claude Code lets nothing else go on with it (the editor's
// "Open here anyway" included), so after a yes it ends here first.
const editorBusy = {};  // sessionId, or "board" -> a folder is being opened (kept across redraws)
const trustNote = (editor) =>
  `If ${editor} asks whether you trust the folder, say yes: in Restricted Mode, Claude Code is off there.`;

async function openInEditor(key, body, done) {
  editorBusy[key] = true;
  if (state.view) render();
  try {
    const res = await api(`/api/board/${state.boardId}/open-folder`, body);
    if (done) done(res.result || {});
  } catch (e) {
    toast(failText(e), "error");
  } finally {
    delete editorBusy[key];
    if (state.view) render();
  }
}

const continuable = (n) => !n.background && !n.editor && where(n) && !(n.live && n.running !== false) &&
  n.resumable !== false;

function conversationButton(n, verb, cls) {
  const editor = n.editor || defaultEditor(), busy = editorBusy[n.sessionId];
  const end = !!(n.background && n.running);
  return el("button", {
    class: cls, text: busy ? "Opening…" : `${verb} IDE`, disabled: !!busy,
    title: `Opens its folder in ${editor}, then this conversation in ${editor}'s Claude panel there, where you ` +
      `go on with it.${end ? " It ends here first (you're asked)." : ""} ${trustNote(editor)}`,
    onclick: () => {
      if (end && !confirm(endHereText(n, editor))) return;
      openInEditor(n.sessionId, { sessionId: n.sessionId, editor, continue: true, end },
        (r) => r.ended && toast(`Ended ${display(n)} here; it goes on in ${editor}.`, "ok"));
    },
  });
}

// What ending a running background agent closes, so you can go on with it in the IDE.
function endHereText(n, editor) {
  const midway = n.status === "busy" ? ", in the middle of what it is doing" : "";
  const shown = n.shownIn ? `its ${n.shownIn === "Terminal" ? "terminal" : n.shownIn} window and any other ` +
    "terminal showing it close" : "any terminal window showing it closes";
  return `Go on with ${display(n)} in ${editor}?\n\nOnly one place can run a conversation, so it ends here ` +
    `first: it stops running in the background${midway}, and ${shown}. Then it opens in ${editor}, where you ` +
    "go on with it. Its card stays on the board.";
}

// An editor chat moved to a terminal. Only one place can run a conversation, so
// one open in the editor is closed there first, after a yes; one that isn't
// open there just opens in the terminal.
function terminalButton(n) {
  const busy = editorBusy[n.sessionId];
  return el("button", {
    class: "btn", text: busy ? "Opening…" : "Open in terminal", disabled: !!busy,
    title: n.live ? `Closes this chat in ${n.editor} (you're asked), then opens it in a terminal window`
      : "Opens this chat in a terminal window",
    onclick: async () => {
      if (n.live && !confirm(moveToTerminalText(n))) return;
      editorBusy[n.sessionId] = true;
      if (state.view) render();
      try {
        const { result } = await api(`/api/board/${state.boardId}/open-terminal`, { sessionId: n.sessionId, end: n.live });
        if (!result.opened) toast(`Run this in a terminal: ${result.command}`, "info", 0);
        else toast(result.closed ? `Closed ${display(n)} in ${n.editor}; it is open in a terminal now.`
          : `Opened ${display(n)} in a terminal.`, "ok");
      } catch (e) {
        toast(failText(e), "error");
      } finally {
        delete editorBusy[n.sessionId];
        if (state.view) render();
      }
      poll();
    },
  });
}

// What moving an editor chat to a terminal closes: the chat, and the agents it
// runs inside its own process.
function moveToTerminalText(n) {
  const midway = n.status === "busy" ? " It stops what it is doing." : "";
  const data = state.agents[n.sessionId], running = data && !data.error ? agentCounts(data).running : 0;
  const agents = running ? ` Its ${running} running agent${running === 1 ? "" : "s"} stop${running === 1 ? "s" : ""} too.` : "";
  return `Open ${display(n)} in a terminal?\n\nOnly one place can run a conversation, so the chat closes in ` +
    `${n.editor} first.${midway}${agents} Then it opens in a terminal window.`;
}

// The board's own folder in an editor window (the sidebar's Board folder).
function renderBoardFolderButton() {
  const btn = $("#open-board-folder"), editor = defaultEditor();
  const text = editorBusy.board ? "Opening…" : "Open in IDE";
  if (btn.textContent !== text) btn.textContent = text;
  btn.disabled = !!editorBusy.board || !state.view;
  btn.title = `Opens a ${editor} window on this board's folder, or brings forward the one already there ` +
    `(Settings, the gear, picks the IDE). ${trustNote(editor)}`;
}
$("#open-board-folder").addEventListener("click", () => {
  if (state.view && !editorBusy.board) openInEditor("board", { board: true, editor: defaultEditor() });
});

// Rename: a running background agent is renamed itself (the server types
// /rename into it), so Claude Code, its address and every board follow. Any
// other chat gets a name of its own on this board; it keeps its title and
// its address, so notes and messages still find it.
const renamesItself = (n) => n.background && n.running;

function nameHeading(n) {
  if (state.renaming !== n.sessionId) {
    return [el("div", { class: "name-head" },
      el("h3", { text: display(n), title: "Double-click to rename", ondblclick: () => startRename(n) }),
      el("button", { class: "icon-btn rename", text: "✎", "aria-label": "Rename", title: "Rename (F2)",
        onclick: () => startRename(n) }))];
  }
  const box = el("input", {
    id: "rename-box", class: "rename-box", maxlength: 60, "aria-label": renamesItself(n) ? "Name" : "Name on this board",
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
    el("p", { class: "muted small", text: renamesItself(n)
      ? "This renames the agent itself: in Claude Code, on every board, and in messages to it."
      : `Only this board shows this name. Messages still reach it as @${n.name}. To rename the chat itself, run /rename in it.` }),
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
        toast(failText(e), "error");
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
  // the button on a line of its own, the choice that goes with it right under it
  return [el("div", { class: "drawer-actions" },
    el("button", {
      class: "btn danger",
      text: conns.length ? `Remove from board with ${arrows}` : "Remove from board",
      onclick: async () => {
        if (conns.length && !confirm(`Remove ${display(n)} and ${arrows} from the board?`)) return;
        if (await act("remove", { sessionId: n.sessionId, notify: liveEnds > 0 && notify.checked })) closeDrawer();
      },
    })),
  liveEnds > 0 && el("label", { class: "small check" }, notify, " Tell connected agents")];
}

// ------------------------------------------------------ agents in a chat

const fmtDur = (ms) => {
  if (ms == null) return null;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
};
const fmtCount = (n) => n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;

function modelName(m) {
  const hit = /claude-(opus|sonnet|haiku|fable)-(\d+)-(\d+)/.exec(m || "");
  if (!hit) return m || null;
  return `${hit[1][0].toUpperCase()}${hit[1].slice(1)} ${hit[2]}.${hit[3]}`;
}

// How a state of an agent or a workflow looks: its icon, its badge and its
// words. A state not listed (not run, skipped, unknown) is an empty ring.
const STATE_KIND = { running: "running", done: "done", completed: "done", failed: "failed",
  stopped: "stopped", killed: "stopped", queued: "queued" };
const stateKind = (s) => STATE_KIND[s] || "idle";
function stateLabel(s) {
  const text = { completed: "done", killed: "stopped" }[s] || String(s || "unknown");
  return text[0].toUpperCase() + text.slice(1);
}

// A drawn icon for a state (see .state-icon in style.css): a turning ring while
// it runs, a check, a cross, a stop square, a clock, or an empty ring.
function stateIcon(state) {
  const kind = stateKind(state);
  const icon = svg("svg", { class: `state-icon ${kind}`, width: 16, height: 16, viewBox: "0 0 16 16", "aria-hidden": "true" });
  const draw = (tag, cls, attrs) => icon.append(svg(tag, { class: cls, ...attrs }));
  const ring = (cls) => draw("circle", cls, { cx: 8, cy: 8, r: 6.2 });
  if (kind === "running") {
    ring("ring faint");
    draw("path", "ring arc", { d: "M8 1.8a6.2 6.2 0 0 1 6.2 6.2" });
  } else if (kind === "done" || kind === "failed") {
    draw("circle", "disc", { cx: 8, cy: 8, r: 7 });
    draw("path", "glyph", { d: kind === "done" ? "M4.7 8.2 7 10.4l4.3-4.8" : "M5.7 5.7l4.6 4.6m0-4.6-4.6 4.6" });
  } else if (kind === "stopped") {
    ring("ring");
    draw("rect", "disc", { x: 5.6, y: 5.6, width: 4.8, height: 4.8, rx: 1 });
  } else if (kind === "queued") {
    ring("ring");
    draw("path", "ring", { d: "M8 4.9V8l2.1 1.3" });
  } else {
    ring("ring dashed");
  }
  return icon;
}

const stateBadge = (state) => el("span", { class: `state-badge ${stateKind(state)}`, title: stateLabel(state) },
  stateIcon(state), el("span", { class: "state-word", text: stateLabel(state) }));

// One agent as a row of the pop-up's list: its state, its name and, quietly at
// the right, how long it ran (what it is doing now is in its tooltip).
// open(id, label) picks it; the picked row is blue.
function agentRow(a, labelText, picked, open) {
  const title = [a.agentType ? `${labelText} (${a.agentType})` : labelText, stateLabel(a.state).toLowerCase(),
    a.lastTool && `now: ${a.lastTool}`].filter(Boolean).join(" · ");
  return el("button", { class: "agent-row", type: "button", id: `agent-row-${a.id}`, "data-agent": a.id,
    "aria-current": a.id === picked && "true", tabindex: -1, title, onclick: () => open(a.id, labelText) },
  stateIcon(a.state),
  el("span", { class: "agent-label", text: labelText }),
  el("span", { class: "agent-time tick", text: fmtDur(a.durationMs) }));
}

// A fold of the pop-up's list (and the arrow's notes). A card you open or shut
// redraws the list: which row the keyboard enters at depends on what is in view.
function group(key, openByDefault, summary, body) {
  const d = el("details", { class: "run", open: state.runOpen[key] ?? openByDefault },
    el("summary", { id: `fold-${key}` }, ...summary), ...body);
  d.addEventListener("toggle", () => {
    if (d.open === (state.runOpen[key] ?? openByDefault)) return;
    state.runOpen[key] = d.open;
    renderAgentsPop();
  });
  return d;
}

// The rest of a card's header: how a workflow (or the chat's own subagents)
// stands, how long it has gone on and, in words, how far it got; under them a
// thin bar of the agents that are done (failed ones in red).
function runStatus(agents, status, time) {
  const count = (kind) => agents.filter((a) => stateKind(a.state) === kind).length;
  const done = count("done"), failed = count("failed");
  const width = (k) => `width: ${(100 * k / agents.length).toFixed(1)}%`;
  return el("span", { class: "run-status" },
    el("span", { class: "run-line" }, stateBadge(status), time && el("span", { class: "run-time tick", text: time }),
      agents.length > 0 && el("span", { class: "run-count", text: `${done} of ${agents.length} done${failed ? ` · ${failed} failed` : ""}` })),
    agents.length > 0 && el("span", { class: `bar ${stateKind(status)}` },
      done > 0 && el("i", { style: width(done) }), failed > 0 && el("i", { class: "bad", style: width(failed) })));
}

// open(id, label): picks an agent; picked: the id of the one picked
function runGroup(r, n, open, picked) {
  const phases = [...r.phases];
  for (const a of r.agents) if (a.phase && !phases.includes(a.phase)) phases.push(a.phase);
  const body = [];
  for (const phase of [...phases, null]) {
    const inPhase = r.agents.filter((a) => (a.phase || null) === phase);
    if (!inPhase.length) continue;
    const counts = {};
    for (const a of inPhase) {
      const word = stateLabel(a.state).toLowerCase();
      counts[word] = (counts[word] || 0) + 1;
    }
    body.push(el("div", { class: "phase-title" }, el("span", { text: phase || "Other" }),
      el("span", { class: "phase-counts", text: Object.entries(counts).map(([s, k]) => `${k} ${s}`).join(" · ") })));
    body.push(...inPhase.map((a) => agentRow(a, a.label, picked, open)));
  }
  if (!r.agents.length) body.push(el("p", { class: "muted small", text: "No agents recorded yet." }));
  // what can be asked of it: the chat gets a message saying so
  const ask = !(n && canReach(n)) ? null : r.status === "running"
    ? ["Ask to stop", "Ask it to stop this workflow", `Please stop the workflow "${r.name}" (run ${r.runId}) now and tell me where it got to.`]
    : ["killed", "stopped", "failed"].includes(r.status)
      ? ["Ask to resume", "Ask it to resume this workflow", `Please resume the workflow "${r.name}" (run ${r.runId}) from where it stopped.`]
      : null;
  return group(r.runId, r.status === "running", [
    el("span", { class: "run-name", text: r.name, title: r.summary || r.name }),
    ask && el("button", { class: "btn run-action", type: "button", text: ask[0], title: ask[1],
      onclick: async () => { if (await sendTo(n, ask[2])) toast(`Asked ${display(n)}.`, "ok"); } }),  // no bubble shows it
    runStatus(r.agents, r.status, fmtDur(r.durationMs)),
  ], body);
}

const everyAgent = ({ workflows, direct }) => [...workflows.flatMap((r) => r.agents), ...direct];

// An agent's row in its chat's list, once that is loaded, as its details would
// have it (a subagent's description is its name, its type its kind; a workflow
// agent has its workflow's name): it knows its tool calls, which they don't.
function listedAgent(sid, id) {
  const data = state.agents[sid];
  if (!data || data.error) return null;
  const all = [...data.direct.map((a) => ({ ...a, label: a.description, kind: a.agentType })),
    ...data.workflows.flatMap((r) => r.agents.map((a) => ({ ...a, workflow: r.name })))];
  return all.find((a) => a.id === id) || null;
}

// How many agents a chat started (in its workflows and on its own), and how many run now.
function agentCounts(data) {
  const all = everyAgent(data);
  return { count: all.length, running: all.filter((a) => a.state === "running").length };
}

// In a chat's details its agents take one row; it opens them in a pop-up.
function agentsSection(n) {
  const data = state.agents[n.sessionId];
  const head = el("h2", { text: "Agents in this chat" });
  if (!data) return [head, el("p", { class: "muted small", text: "Loading…" })];
  if (data.error) return [head, el("p", { class: "error small", text: data.error })];
  if (!data.workflows.length && !data.direct.length) {
    return [head, el("p", { class: "muted small", text: "No subagents or workflows yet." })];
  }
  const { count, running } = agentCounts(data);
  return [el("button", {
    class: "agents-line", "aria-haspopup": "dialog", title: "Show its workflows and subagents",
    onclick: () => openAgentsPop(n.sessionId),
  }, el("span", { class: "agents-main" }, "Agents in this chat", el("span", { class: "count", text: count })),
  running > 0 && el("span", { class: "running-now" }, el("i"), `${running} running`))];
}

// The workflows and subagents a chat started (the pop-up's list); open(id,
// label) picks one agent.
function agentsList(n, open) {
  const data = state.agents[n.sessionId], picked = state.popAgents?.sub?.id;
  if (!data) return [el("p", { class: "muted small", text: "Loading…" })];
  if (data.error) return [el("p", { class: "error small", text: data.error })];
  const { workflows: runs, direct } = data;
  if (!runs.length && !direct.length) return [el("p", { class: "muted small", text: "No subagents or workflows yet." })];
  const out = runs.map((r) => runGroup(r, n, open, picked));
  if (direct.length) {
    const status = direct.some((a) => a.state === "running") ? "running" : "done";
    out.push(group(`direct:${n.sessionId}`, true, [
      el("span", { class: "run-name", text: "Subagents" }), runStatus(direct, status),
    ], direct.map((a) => agentRow(a, a.description, picked, open))));
  }
  return out;
}

// A board action. A failure is a notice that stays until closed; the caller
// learns whether it worked (Disconnect and Remove close the details only then).
async function act(action, body) {
  try {
    await api(`/api/board/${state.boardId}/${action}`, body);
    return true;
  } catch (e) {
    toast(failText(e), "error");
    return false;
  } finally {
    poll();
  }
}

function addNode(sessionId) {
  const r = $("#canvas").getBoundingClientRect();
  const count = state.view?.nodes.length || 0;
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
  } catch (e) {
    toast(`Couldn't save where you moved the card, so it went back. ${failText(e)}`, "error");
  } finally {
    delete state.localPos[d.id];
  }
});

document.addEventListener("keydown", (evt) => {
  if (evt.key !== "Escape") return;
  if (document.querySelector(":popover-open")) return;  // this Esc closes the popover (Appearance) only
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
    const before = state.selected;
    if (sub) openSubCard(sub);
    else select_(node ? { type: "node", id: node.dataset.id } : { type: "wire", id: label.dataset.id });
    // Opened from the keyboard: focus moves into the details (Tab goes on from there).
    if (state.selected && state.selected !== before) $("#drawer").focus({ preventScroll: true });
  });
  layer.addEventListener("focusin", (evt) => revealFocused(evt.target));
}

// Pan a card or label reached with the keyboard fully into view, clear of the
// glass panels. (The canvas clips instead of scrolling, so the browser can't
// scroll it there itself.)
function revealFocused(target) {
  if (target.matches(":focus-visible")) reveal(target);
}

// Pan the board just enough to bring an element fully into the part the
// panels leave uncovered (e.g. a card the details just opened over).
function reveal(target) {
  const c = canvas.getBoundingClientRect(), v = viewBox(), b = target.getBoundingClientRect();
  // No room for it beside the panels (a narrow window, the details open): the board stays put.
  if (v.right - v.left < b.width + 80 || v.bottom - v.top < b.height + 80) return;
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
    cd.error.textContent = failText(e);
    cd.error.hidden = false;
  } finally {
    cd.submit.disabled = false;
  }
});

// ------------------------------------------------------------ board dialog

// The two dialogs that ask for a folder share one browser and one drop-down.
const pickers = {
  board: { input: $("#b-folder"), toggle: $("#b-folder-toggle"), list: $("#b-folder-list"),
    box: $("#b-browser"), error: $("#b-error") },
  agent: { input: $("#n-folder"), toggle: $("#n-folder-toggle"), list: $("#n-folder-list"),
    box: $("#n-browser"), error: $("#n-error") },
};

// A folder box's drop-down (a native datalist filters by the text in the
// box, so a full path lists only itself): its chevron, ↓ or an empty box lists every
// folder in ui.choices, typing narrows the list, and it opens in place,
// pushing what is below it down. A pick, Esc or a click elsewhere closes it.
function folderCombo(ui) {
  const { input, toggle, list } = ui;
  ui.choices = [];
  let shown = [], active = -1;
  const expanded = (on) => {
    for (const e of [input, toggle]) e.setAttribute("aria-expanded", String(on));
  };
  const mark = () => {
    list.querySelectorAll(".combo-item").forEach((li, i) => {
      li.classList.toggle("active", i === active);
      li.setAttribute("aria-selected", String(i === active));
    });
    const li = active >= 0 && list.children[active];
    if (li) {
      input.setAttribute("aria-activedescendant", li.id);
      li.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };
  const close = () => {
    list.hidden = true;
    active = -1;
    expanded(false);
    input.removeAttribute("aria-activedescendant");
  };
  const pick = (folder) => {
    input.value = folder;
    close();
    ui.box.hidden = true;
    ui.error.hidden = true;
    input.focus();
  };
  const open = (filter = "") => {
    const q = filter.trim().toLowerCase();
    shown = ui.choices.filter((f) => !q || f.toLowerCase().includes(q));
    active = -1;
    list.replaceChildren(...(shown.length
      ? shown.map((f, i) => el("li", {
        id: `${list.id}-${i}`, role: "option", class: "combo-item mono", text: f, title: f,
        "aria-selected": "false",
        onpointerdown: (e) => e.preventDefault(),  // keeps the focus in the box
        onclick: () => pick(f),
      }))
      : [el("li", { class: "combo-empty muted small", text: ui.choices.length
        ? "No folder here matches; type the whole path or use Browse…."
        : ui.none || "No folders with running chats; type one or use Browse…." })]));
    list.hidden = false;
    expanded(true);
    mark();
  };
  ui.close = close;
  toggle.addEventListener("click", () => {
    if (list.hidden) open();
    else close();
    input.focus();
  });
  // typing narrows the list (a value set by the app doesn't open it)
  input.addEventListener("input", (e) => { if (e.isTrusted) open(input.value); });
  input.addEventListener("focus", () => { if (!input.value.trim() && list.hidden) open(); });
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (list.hidden) open();
      if (!shown.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length;
      mark();
    } else if (e.key === "Enter" && !list.hidden && active >= 0) {
      e.preventDefault();
      pick(shown[active]);
    } else if (e.key === "Escape" && !list.hidden) {
      e.preventDefault();  // closes the list, not the dialog
      e.stopPropagation();
      close();
    } else if (e.key === "Tab") {
      close();
    }
  });
  // Closed by a click elsewhere once that click is done: closed on the press,
  // the list's room would go and the button under the pointer move away.
  document.addEventListener("click", (e) => {
    if (!list.hidden && !input.parentElement.contains(e.target) && !list.contains(e.target)) close();
  });
}
for (const ui of Object.values(pickers)) folderCombo(ui);

// Folders suggested for a board or an agent leave out other chats' worktrees
// (.claude/worktrees/<name>): those come and go with each chat's work. Typing
// a path or Browse… still reaches them.
const ownFolders = (folders) => folders.filter((f) => !/\/\.claude\/worktrees\/[^/]/.test(f.replace(/\\/g, "/")));

const placeButtons = (places, ui) => places.map((pl) => el("button", {
  type: "button", class: "btn place", text: pl.label, title: pl.path, onclick: () => browse(pl.path, ui),
}));

// New board, or with a board: Change folder, which points that board at
// another folder (its cards and arrows stay).
let movingBoard = null;

function openBoardDialog(folders, boards, places = [], board = null) {
  movingBoard = board;
  $("#b-title").textContent = board ? "Change board folder" : "New board";
  $("#b-note").textContent = board
    ? "Sessions running in the new folder (or below it) join the board automatically. " +
      "Cards already on the board stay, with their arrows."
    : "A board belongs to a folder. Sessions running in that folder (or below it) join the board " +
      "automatically; you can add sessions from other folders by hand.";
  $("#b-submit").textContent = board ? "Change" : "Create";
  folders = ownFolders(folders);
  const have = new Set(boards.map((b) => b.folder));
  const free = folders.filter((f) => !have.has(f));
  pickers.board.choices = free;  // a folder that has a board would only open that board
  pickers.board.none = folders.length ? "Every folder with running chats already has a board; type another or use Browse…." : null;
  pickers.board.close();
  $("#b-places").replaceChildren(...placeButtons(places, pickers.board));
  $("#b-suggest").replaceChildren(
    ...(free.length ? [el("span", { class: "small muted", text: "Folders with running sessions:" })] : []),
    ...free.map((f) => el("button", {
      type: "button", class: "btn mono", text: f,
      onclick: () => { $("#b-folder").value = f; $("#b-browser").hidden = true; },
    })));
  $("#b-folder").value = board?.folder || "";
  $("#b-browser").hidden = true;
  $("#b-error").hidden = true;
  $("#board-dialog").showModal();
  $("#b-folder").focus();
}

// Folder browser: click a folder to go into it; the box above always holds
// the folder you are in, so Create (or Start agent) uses it.
async function browse(path, ui = pickers.board) {
  const { input, box, error } = ui;
  ui.close();
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
    error.textContent = failText(e);
    error.hidden = false;
  }
}

$("#b-browse").addEventListener("click", () => browse($("#b-folder").value.trim()));
$("#n-browse").addEventListener("click", () => browse(nd.folder.value.trim(), pickers.agent));

// New board: the top bar's button, and the Board picker's last row.
async function newBoard() {
  try {
    const data = await api("/api/state");
    openBoardDialog(data.folders, data.boards, data.places);
  } catch (e) {
    toast(failText(e), "error");
  }
}
$("#new-board").addEventListener("click", newBoard);

$("#change-folder").addEventListener("click", async () => {
  const board = state.view?.board;
  if (!board) return;
  try {
    const data = await api("/api/state");
    openBoardDialog(data.folders, data.boards, data.places, board);
  } catch (e) {
    toast(failText(e), "error");
  }
});

$("#board-form").addEventListener("submit", async (evt) => {
  if (evt.submitter?.value !== "ok") return;
  evt.preventDefault();
  const folder = $("#b-folder").value.trim();
  try {
    if (movingBoard) {
      const res = await api(`/api/board/${movingBoard.id}/folder`, { folder });
      $("#board-dialog").close();
      if (res.result.folder !== movingBoard.folder) toast(`This board now uses ${res.result.folder}.`, "ok");
      poll();
      return;
    }
    const res = await api("/api/boards", { folder });
    $("#board-dialog").close();
    if (state.view?.boards.some((b) => b.id === res.id)) toast("That folder already has a board, so it's open.", "ok");
    selectBoard(res.id);
  } catch (e) {
    $("#b-error").textContent = failText(e);
    $("#b-error").hidden = false;
  }
});

for (const btn of document.querySelectorAll("[data-close]")) {
  btn.addEventListener("click", () => btn.closest("dialog").close());
}

// The server may not be up yet: say so and keep trying until it answers.
function boot() {
  start().then(() => reachable(true), (e) => {
    reachable(false, e.unreachable ? "Can't reach Let Them Talk. Trying again…"
      : `Let Them Talk couldn't load the board: ${e.message} Trying again…`);
    setTimeout(boot, POLL_MS * 2);
  });
}
boot();

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

// The connect hint sits on the top bar's first row where it fits. Where it
// would wrap onto a second one (a narrower window), it shows there only while
// the board has no arrows yet, so a first-timer still learns how; with the
// details panel open it hides.
const hint = $(".topbar .hint");
function placeHint() {
  hint.style.display = "";
  const wraps = hint.offsetTop > $(".topbar .board-pick").offsetTop + 10;
  if (wraps && (state.view?.board.connections.length || !$("#drawer").hidden)) hint.style.display = "none";
}
new ResizeObserver(placeHint).observe($(".topbar"));

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
  try {
    localStorage.removeItem(`ltt.pan.${board.id}`);
    localStorage.removeItem(`ltt.zoom.${board.id}`);
  } catch { /* storage off */ }
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
  const MIN = 180, MAX = 720, STEP = 16;
  const set = (w) => {
    const px = Math.round(Math.min(MAX, Math.max(MIN, w)));
    document.documentElement.style.setProperty(cssVar, `${px}px`);
    handle.setAttribute("aria-valuenow", px);
  };
  handle.setAttribute("aria-valuemin", MIN);
  handle.setAttribute("aria-valuemax", MAX);
  handle.setAttribute("aria-valuenow", store(key) || def);
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
  const reset = () => { set(def); store(key, def); };
  handle.addEventListener("dblclick", reset);
  // from the keyboard: ← → move the edge, Enter resets
  handle.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: -STEP, ArrowRight: STEP }[e.key];
    if (e.key === "Enter") reset();
    else if (step) {
      set(panel.getBoundingClientRect().width + dir * step);
      store(key, Math.round(panel.getBoundingClientRect().width));
    } else return;
    e.preventDefault();
  });
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

// The IDE picked under Settings (the gear); until one is, the one most of the
// board's chats run in. Open in IDE, Chat in IDE and the details' Open in /
// Continue in buttons all use it (New agent can pick another for one chat).
function defaultEditor() {
  const saved = store("ltt.editor");
  if (saved && EDITOR_SCHEMES[saved]) return saved;
  const counts = {};
  for (const n of state.view?.nodes || []) if (n.editor) counts[n.editor] = (counts[n.editor] || 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "VS Code";
}

const idePick = $("#ide-pick");
idePick.replaceChildren(...Object.keys(EDITOR_SCHEMES).map((e) => el("option", { value: e, text: e })));
$("#appearance").addEventListener("toggle", () => { idePick.value = defaultEditor(); });
idePick.addEventListener("change", () => {
  store("ltt.editor", idePick.value);
  if (state.view) render();
});

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
  agents: $("#n-agents"), terminal: $("#n-terminal"), ultra: $("#n-ultra"), note: $("#n-note"), error: $("#n-error"),
  submit: $("#n-submit"), workflow: false,
  team: $("#n-team"), count: $("#n-team-count"), teamList: $("#n-team-list"), sections: [],
  teamModel: $("#n-team-model"), teamEffort: $("#n-team-effort"),
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

// With agents, New workflow starts a team instead (start_team in server.py):
// a master that runs your prompt, and agents that wait for the task it sends
// each one. Each agent is a section that folds, with its role and prompt; one
// a lower count takes off is kept, so a higher count brings back its text.
const TEAM_MAX = 8, ROLE_MAX = 24, MASTER_MAX = 30;
const NAME_CHARS = /^[\p{L}\p{N}_ -]+$/u;  // in a role or the master's name (the server's NAME_RE)
const teamSize = () => nd.workflow ? Math.max(0, Math.min(TEAM_MAX, parseInt(nd.count.value, 10) || 0)) : 0;

// Each agent's model and effort, and the master's (at the top): Opus and
// Claude Code's own effort unless you pick others. All four models take every
// level (Claude Code itself lowers one a model lacks to high).
const EFFORTS = { "": "Default", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max" };
const fillModels = (sel) => sel.replaceChildren(...Object.entries(WF_MODELS).map(([v, text]) =>
  el("option", { value: v, text, selected: v === "opus" })));
const fillEfforts = (sel) => sel.replaceChildren(...Object.entries(EFFORTS).map(([v, text]) => el("option", { value: v, text })));
fillModels(nd.teamModel);
fillEfforts(nd.teamEffort);

function agentSection(i) {
  // its title says its role; folded, a model or effort other than Opus and
  // Default ("on Haiku, low effort") and the start of its prompt too
  const head = el("span"), runs = el("span", { class: "n-agent-model" }), peek = el("span", { class: "n-agent-peek muted" });
  const task = el("textarea", { id: `n-task-${i}`, class: "n-task", rows: 3,
    placeholder: "Its part of the work; the master sends it this as its task",
    oninput: () => { peek.textContent = task.value.trim().split("\n")[0]; } });
  const role = el("input", { id: `n-role-${i}`, class: "n-role", maxlength: ROLE_MAX, autocomplete: "off",
    placeholder: "e.g. tester", oninput: () => { head.textContent = role.value.trim() && ` · ${role.value.trim()}`; },
    // Enter goes on to its prompt, as it would start the team otherwise
    onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); task.focus(); } } });
  const showRuns = () => {
    runs.textContent = model.value === "opus" && !effort.value ? "" : ` · on ${model.selectedOptions[0].text}` +
      (effort.value ? `, ${effort.selectedOptions[0].text.toLowerCase()} effort` : "");
  };
  const model = el("select", { id: `n-model-${i}`, class: "n-team-model",
    onchange: () => { showRuns(); refreshAgentDialog(); } });  // Haiku's note
  const effort = el("select", { id: `n-effort-${i}`, class: "n-team-effort", onchange: showRuns });
  fillModels(model);
  fillEfforts(effort);
  showRuns();
  const field = (label, box) => el("div", {}, el("label", { for: box.id, text: label }), box);
  return el("details", { class: "n-agent", open: true },
    el("summary", {}, el("strong", { text: `Agent ${i + 1}` }), head, runs, peek),
    el("div", { class: "n-agent-body" },
      el("div", { class: "n-agent-row" }, field("Role", role), field("Model", model), field("Effort", effort)),
      el("label", { for: task.id, text: "Prompt" }), task));
}

function renderTeam() {
  const n = teamSize();
  while (nd.sections.length < n) nd.sections.push(agentSection(nd.sections.length));
  nd.sections.forEach((s, i) => { if (i >= n) s.remove(); else if (!s.isConnected) nd.teamList.append(s); });
  for (const [btn, off] of [[$("#n-team-less"), n === 0], [$("#n-team-more"), n === TEAM_MAX]]) {
    if (off && document.activeElement === btn) nd.count.focus();  // a button turned off drops the focus to the page
    btn.disabled = off;
  }
  $("#n-team-note").textContent = n
    ? "Each one starts in the background and waits; the master sends it the prompt you write here as its task, and it reports back."
    : "Add agents to have a master hand each one its part.";
}

// The stepper stays under the pointer when its number changes, though the
// fields above it hide (or show) and a section comes (or goes) below: the
// dialog scrolls by as much, and when it can't, the dialog itself moves (one
// that fits sits in the middle of the window, so it moves as it grows).
function keepStepperStill(change) {
  const d = nd.dialog, at = () => $("#n-team-more").getBoundingClientRect().top, before = at();
  change();
  let off = at() - before;
  if (Math.abs(off) < 1) return;
  const scrolled = d.scrollTop;
  d.scrollTop = scrolled + off;
  off -= d.scrollTop - scrolled;
  if (Math.abs(off) < 1) return;
  const y = Math.max(8, d.getBoundingClientRect().top - off);
  Object.assign(d.style, { marginTop: `${y}px`, marginBottom: "auto", maxHeight: `calc(100% - ${y}px - 1em)` });
  d.scrollTop += at() - before;  // it may have had to get shorter
}
const changeCount = () => keepStepperStill(refreshAgentDialog);

function refreshAgentDialog() {
  const bg = whereTo() === "background", wf = nd.workflow, team = teamSize() > 0;
  renderTeam();
  const haiku = team ? [nd.teamModel, ...nd.sections.slice(0, teamSize()).map((s) => s.querySelector(".n-team-model"))]
    .some((e) => e.value === "haiku") : /haiku/i.test(nd.model.value);
  $("#n-title").textContent = wf ? "New workflow" : "New agent";
  $("#n-prompt-label").textContent = team ? "What should the master do?" : wf ? "What should the workflow do?" : "What should it do?";
  nd.prompt.placeholder = team ? "e.g. Build the sign-up page: split the work among your agents and check what they send back"
    : wf ? "e.g. Review every file in src/ for bugs and fix them" : "e.g. Run the test suite and fix whatever fails";
  $("#n-where-box").hidden = wf;
  nd.name.placeholder = team ? "optional; the master's name, else the prompt's first words"
    : wf ? "optional; \"workflow\" and the task's first words" : "optional; taken from the prompt";
  $("#n-agents-label").hidden = nd.agents.hidden = !wf || team;
  $("#n-model-label").hidden = nd.model.hidden = team;  // a team's master has its own, with its effort
  for (const id of ["#n-team-model-label", "#n-team-model", "#n-team-effort-label", "#n-team-effort"]) $(id).hidden = !team;
  if (team) nd.name.maxLength = MASTER_MAX;
  else nd.name.removeAttribute("maxlength");
  nd.team.hidden = !wf;
  $("#n-editor-box").hidden = bg;
  // A Chat in IDE takes a name (its card's, on this board) and a model (the
  // mod runs it on that), not permissions: an editor link can't carry them.
  $("#n-bg-box").hidden = false;
  for (const id of ["#n-mode-label", "#n-mode", "#n-terminal-gap", "#n-terminal-row", "#n-ultra-gap", "#n-ultra-row"]) $(id).hidden = !bg;
  if (team) $("#n-terminal-gap").hidden = $("#n-terminal-row").hidden = true;  // a team starts in the background only
  if (!bg) nd.name.placeholder = "optional; its card's name on this board";
  nd.submit.textContent = team ? "Start team" : wf ? "Start workflow" : bg ? "Start agent" : `Open in ${nd.editor.value}`;
  nd.note.textContent = [
    team ? "The master and its agents start in the background in this folder with the settings above, each on its " +
      "own model and effort; each agent is named after the master and its role, and an arrow each way links it with the master."
      : wf && "A new background agent starts in this folder and runs your task as a Claude Code workflow; " +
      "the model you pick runs it and its agents, which show under Subagents.",
    bg && haiku && nd.mode.value === "auto"
      ? `With Haiku, auto mode may not be available; ${team ? "the master or an agent on it" : "the agent"} then asks before it acts.`
      : bg && "Claude Code must already trust the folder (run claude there once and accept).",
    !bg && `${nd.editor.value} must trust the folder: in Restricted Mode, Claude Code is off there and no chat opens.`,
    !bg && nd.model.value && `Let Them Talk's mod runs it on ${nd.model.selectedOptions[0].text} ` +
      `(${nd.editor.value}'s model menu still shows its own); it starts with its usual permissions.`,
  ].filter(Boolean).join(" ");
}

// The folders New agent's drop-down lists: the board's, then those of the running
// chats in the sidebar, then those of the board's running cards. Typing,
// Browse… and the places below still reach any folder.
function workingFolders() {
  const v = state.view;
  if (!v) return [];
  const cwds = (list) => list.map((s) => s.cwd).filter(Boolean).sort();
  return ownFolders([...new Set([v.board.folder, ...cwds(v.available), ...cwds(v.nodes.filter((n) => n.live)),
    ...(v.folders || [])].filter(Boolean))]);
}

// The folder box starts on the folder given (a "+ New agent" in the sidebar),
// else the board's; both an editor chat and a background agent start there.
// With workflow, it starts a workflow (always a background agent).
function openNewAgent(folder, workflow = false) {
  nd.workflow = workflow;
  if (!nd.agents.options.length) {
    nd.agents.replaceChildren(...WF_AGENTS.map((v) => el("option", { value: v, text: v || "Its choice" })));
  }
  const pick = defaultEditor();
  nd.editor.replaceChildren(...Object.keys(EDITOR_SCHEMES).map((e) =>
    el("option", { value: e, text: e, selected: e === pick })));
  pickers.agent.choices = workingFolders();
  pickers.agent.close();
  nd.folder.value = folder || state.view?.board.folder || "";
  pickers.agent.box.hidden = true;
  api("/api/state").then((d) => $("#n-places").replaceChildren(...placeButtons(d.places || [], pickers.agent)))
    .catch(() => {});
  nd.error.hidden = true;
  refreshAgentDialog();
  renderAgentImages();  // any still there from a dialog closed without starting
  nd.dialog.showModal();
  nd.prompt.focus();
}
$("#new-chat").addEventListener("click", () => openNewAgent());
$("#new-workflow").addEventListener("click", () => openNewAgent(null, true));

// Images go with the new agent's first prompt, as with a chat's Send box:
// pasted into the prompt box or dropped anywhere on the dialog. The server
// saves them where the agent reads them and names them in the prompt.
const NEW_AGENT = "new-agent";  // their key in state.images
function renderAgentImages() {
  const images = state.images[NEW_AGENT] || [];
  $("#n-images").hidden = !images.length;
  $("#n-images").replaceChildren(...imageThumbs(NEW_AGENT, renderAgentImages));
}

// A thumbnail with × for each image going with the next text under key.
function imageThumbs(key, redraw) {
  return (state.images[key] || []).map((img, i) => el("div", { class: "thumb" },
    el("img", { src: img.url, alt: `Image ${i + 1}` }),
    el("button", { type: "button", class: "thumb-x", text: "×", "aria-label": `Remove image ${i + 1}`, title: "Remove",
      onclick: () => {
        URL.revokeObjectURL(img.url);
        state.images[key] = state.images[key].filter((x) => x !== img);
        redraw();
      } })));
}
function clearAgentImages() {
  for (const img of state.images[NEW_AGENT] || []) URL.revokeObjectURL(img.url);
  state.images[NEW_AGENT] = [];
  renderAgentImages();
}
nd.prompt.addEventListener("paste", (e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (!files.length || e.clipboardData.getData("text/plain")) return;  // copied text pastes as text
  e.preventDefault();
  addImages(NEW_AGENT, files, renderAgentImages);
});
nd.dialog.addEventListener("dragover", (e) => {
  if (!draggingFiles(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  nd.dialog.classList.add("dropping");
});
nd.dialog.addEventListener("dragleave", (e) => {
  if (!nd.dialog.contains(e.relatedTarget)) nd.dialog.classList.remove("dropping");
});
nd.dialog.addEventListener("drop", (e) => {
  nd.dialog.classList.remove("dropping");
  if (!e.dataTransfer.files.length) return;
  e.preventDefault();
  addImages(NEW_AGENT, [...e.dataTransfer.files], renderAgentImages);
});

for (const e of [nd.editor, nd.mode, nd.model, nd.teamModel, ...document.querySelectorAll('input[name="n-where"]')]) {
  e.addEventListener("change", refreshAgentDialog);
  e.addEventListener("input", refreshAgentDialog);
}
nd.count.addEventListener("input", changeCount);
nd.count.addEventListener("change", () => { nd.count.value = teamSize(); });  // 12 reads 8, "" reads 0
// A digit typed replaces the number, wherever the cursor is (8 at most: one
// digit is all it takes); it shows selected for that. Enter applies it, as
// it would start the team otherwise.
for (const type of ["focus", "click"]) nd.count.addEventListener(type, () => nd.count.select());
nd.count.addEventListener("beforeinput", (e) => {
  if (e.inputType !== "insertText") return;
  e.preventDefault();
  if (!/^\d+$/.test(e.data || "")) return;
  nd.count.value = Math.min(TEAM_MAX, Number(e.data));
  changeCount();
  nd.count.select();
});
nd.count.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  nd.count.value = teamSize();
  changeCount();
});
for (const [id, by] of [["#n-team-less", -1], ["#n-team-more", 1]]) {
  $(id).addEventListener("click", () => {
    nd.count.value = Math.max(0, Math.min(TEAM_MAX, teamSize() + by));
    changeCount();
  });
}
nd.dialog.addEventListener("close", () => {  // the next one opens in the middle again (see keepStepperStill)
  Object.assign(nd.dialog.style, { marginTop: "", marginBottom: "", maxHeight: "" });
});

$("#chat-form").addEventListener("submit", async (evt) => {
  if (evt.submitter?.value !== "ok") return;
  evt.preventDefault();
  const prompt = nd.prompt.value.trim();
  const images = (state.images[NEW_AGENT] || []).map((i) => ({ data: i.data }));
  const fail = (msg) => { nd.error.textContent = msg; nd.error.hidden = false; nd.submit.disabled = false; };
  nd.submit.disabled = true;
  try {
    if (teamSize()) {
      const agents = nd.sections.slice(0, teamSize()).map((s) =>
        ({ role: s.querySelector(".n-role").value.trim(), prompt: s.querySelector(".n-task").value.trim(),
          model: s.querySelector(".n-team-model").value, effort: s.querySelector(".n-team-effort").value }));
      // The server checks it all again; these show where.
      const there = (box, msg) => { box.focus(); return fail(msg); };
      if (!prompt) return there(nd.prompt, "Say what the master should do.");
      const name = nd.name.value.trim();
      if (name.length > MASTER_MAX) return there(nd.name, `Keep the master's name to ${MASTER_MAX} characters.`);
      if (name && !NAME_CHARS.test(name)) return there(nd.name, "The master's name can have only letters, digits, spaces, - and _.");
      const key = (role) => role.toLowerCase().split(/\s+/).join(" ");
      for (const [i, a] of agents.entries()) {
        const open = (sel, msg) => { nd.sections[i].open = true; return there(nd.sections[i].querySelector(sel), msg); };
        const same = agents.findIndex((b) => key(b.role) === key(a.role));
        if (!a.role) return open(".n-role", `Agent ${i + 1} needs a role.`);
        if (!NAME_CHARS.test(a.role)) return open(".n-role", `Agent ${i + 1}'s role can have only letters, digits, spaces, - and _.`);
        if (same < i) return open(".n-role", `Agents ${same + 1} and ${i + 1} are both "${a.role}"; give each its own role.`);
        if (!a.prompt) return open(".n-task", `Agent ${i + 1} needs a prompt.`);
      }
      // it starts in the server's own time; its notices say how it goes (see renderLaunches)
      await api(`/api/board/${state.boardId}/launch-team`, {
        prompt, images, agents, folder: nd.folder.value.trim(), name: nd.name.value.trim(),
        permissionMode: nd.mode.value, ultracode: nd.ultra.checked, model: nd.teamModel.value, effort: nd.teamEffort.value,
      });
      nd.ultra.checked = false;
      nd.teamModel.value = "opus";
      nd.teamEffort.value = "";
      nd.count.value = 0;
      nd.sections = [];
      nd.teamList.replaceChildren();
    } else if (whereTo() === "background") {
      const wf = nd.workflow;
      if (wf ? !prompt : !prompt && !images.length) {
        return fail(wf ? "Say what the workflow should do." : "A background agent needs a prompt to start with.");
      }
      const model = nd.model.value.trim();
      const res = await api(`/api/board/${state.boardId}/launch-background`, {
        prompt: wf ? workflowPrompt({ task: prompt, agents: nd.agents.value, model }) : prompt, images,
        folder: nd.folder.value.trim(), name: nd.name.value.trim() || (wf ? workflowName(prompt) : ""),
        permissionMode: nd.mode.value, model, openTerminal: nd.terminal.checked, ultracode: nd.ultra.checked,
      });
      nd.ultra.checked = false;  // it costs more: the next agent asks again
      toast(`Started ${wf ? "workflow" : "background agent"} "${res.result.name}". ` +
        "It will appear on this board in a moment.", "ok");
    } else {
      const editor = nd.editor.value;
      // With a folder, the server opens it in the editor and then the new chat
      // there; without one, this link opens the chat in the window you used last.
      // The server sends the prompt either way.
      const res = await api(`/api/board/${state.boardId}/launch-editor`, {
        prompt, images, editor, folder: nd.folder.value.trim(), name: nd.name.value.trim(), model: nd.model.value.trim(),
      });
      if (!res.result?.opensChat) window.location.href = editorLink(editor, {});
    }
    nd.dialog.close();
    nd.prompt.value = "";
    nd.name.value = "";
    clearAgentImages();
    poll();
  } catch (e) {
    fail(failText(e));
  } finally {
    nd.submit.disabled = false;
    // turned off while it waited, it dropped the focus to the page: back on it, by the server's answer
    if (nd.dialog.open && document.activeElement === document.body) nd.submit.focus();
  }
});

// ------------------------------------------------------------------ toasts

const toasts = $("#toasts");
// A failure stays until closed (×); other notices go after a few seconds.
function toast(text, level = "info", ms = level === "error" ? 0 : 5000) {
  const t = el("div", { class: `toast ${level}` }, el("span", { text }),
    el("button", { class: "icon-btn", text: "×", "aria-label": "Dismiss", onclick: () => t.remove() }));
  toasts.append(t);
  if (ms) setTimeout(() => t.remove(), ms);
  return t;
}

// Editor chats started from here: show how handing over the prompt went.
// Handoffs and teams report each step the same way. The server lists them for 10
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
state.images = {};  // sessionId -> [{url, data}] images going with its next text (url: the thumbnail)

// Images are pasted, dropped or added into the Send box, and the server
// checks them again (see _read_images in server.py).
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const IMAGE_MB = 10, IMAGE_COUNT = 5;
// The line the server adds for each image, shown as Claude Code shows one you paste.
const imageTags = (text) => { let i = 0; return text.replace(/^\[Image: source: [^\]\n]+\]$/gm, () => `[Image #${++i}]`); };

// A chat can take text from here if it is running and can receive messages,
// or if it is a background agent (which wakes up with a prompt).
const canReach = (n) => n.live && (n.background || !n.messageBlock);
const promptable = (n) => n.background && n.agentState !== "working" && n.status !== "busy";

// Sends a chat your text. Sent is said by the caller (the Send box's bubble);
// only a copy started instead, or a failure, gets a notice here.
async function sendTo(n, text, how, images = []) {
  try {
    const res = await api(`/api/board/${state.boardId}/send`,
      { sessionId: n.sessionId, text, how, images: images.map((i) => ({ data: i.data })) });
    if (res.result.copy) toast(`Claude Code started a copy (${res.result.copy}) instead of waking it.`, "error");
    return true;
  } catch (e) {
    // A dropped connection (e.g. the server restarted) says nothing about delivery.
    toast(e.unreachable
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
    el("div", { class: "bubble" + (long && !open ? " folded" : "") }, richText(m.text)),
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
      el("div", { class: "bubble" + (long && !open ? " folded" : ""), text: imageTags(m.text) }),
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
    el("div", { class: "bubble" + (done ? "" : " typing") }, richText(text)),
    fold && toggle(fold));
}

function sendSection(n) {
  if (!canReach(n)) return [];
  const asPrompt = promptable(n);
  // A likely reply, grey like Claude Code's own suggestion. On the empty box Tab
  // (or →) takes it and a second Tab moves on as usual. Enter sends,
  // Shift+Enter adds a line, and an empty box sends nothing.
  const sid = n.sessionId;
  const sg = !(state.outbox[sid] || []).length && state.chat[sid]?.suggest;
  const suggest = sg?.text;
  const images = state.images[sid] || [];
  // Images can go alone, as in Claude Code; then there's something to send.
  const ready = () => !!(box.value.trim() || (state.images[sid] || []).length);
  const box = el("textarea", {
    id: "send-box", rows: 1, class: "send-box",
    placeholder: suggest ? `${suggest}  (Tab or →)` : sg?.pending ? "Suggesting a reply…"
      : asPrompt ? "Its next prompt" : "Your message",
    oninput: (e) => { state.drafts[sid] = e.target.value; composer.classList.toggle("ready", ready()); },
    // A screenshot pasted (Ctrl+V) goes in as an image; copied text pastes as text.
    onpaste: (e) => {
      const files = [...(e.clipboardData?.files || [])];
      if (!files.length || e.clipboardData.getData("text/plain")) return;
      e.preventDefault();
      addImages(sid, files);
    },
    onkeydown: (e) => {
      if (e.isComposing) return;
      const plain = !e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey;
      if (e.key === "Enter" && plain) {
        e.preventDefault();
        if (ready()) button.click();
        return;
      }
      if (!((e.key === "Tab" && plain) || e.key === "ArrowRight") || !suggest || box.value) return;
      e.preventDefault();
      box.value = state.drafts[sid] = suggest;
      composer.classList.add("ready");
    },
  });
  box.value = state.drafts[sid] || "";
  // The drawer is redrawn every poll, so "sending" lives in state, not on this button.
  const sending = state.sending.has(sid);
  // Asking you something in its terminal: nothing can be typed there until you answer.
  const asking = n.background && n.running && n.agentState === "blocked";
  const label = sending ? "Sending…" : asPrompt ? "Send prompt" : "Send message";
  const button = el("button", {
    class: "composer-send", disabled: sending, "aria-label": label, title: label,
    onclick: () => {
      const text = box.value.trim(), sent = state.images[sid] || [];
      if (!ready()) return box.focus();
      state.drafts[sid] = "";
      state.images[sid] = [];
      // Back into the box to fix and resend, unless something new was added meanwhile.
      sendAsBubble(n, text, () => {
        if (!(state.drafts[sid] || "").trim()) state.drafts[sid] = text;
        if (!(state.images[sid] || []).length) state.images[sid] = sent;
      }, sent);
    },
  }, sendIcon());
  // Messages-style: the images over the text, the round Send on the right.
  // Images come in by paste, or dropped anywhere on the details (see below).
  const composer = el("div", {
    class: `composer${box.value.trim() || images.length ? " ready" : ""}${asking ? " asking" : ""}`,
  },
  images.length > 0 && el("div", { class: "composer-images" }, ...images.map((img, i) => el("div", { class: "thumb" },
    el("img", { src: img.url, alt: `Image ${i + 1}` }),
    el("button", { class: "thumb-x", text: "×", "aria-label": `Remove image ${i + 1}`, title: "Remove",
      onclick: () => {
        URL.revokeObjectURL(img.url);
        state.images[sid] = state.images[sid].filter((x) => x !== img);
        renderDrawer();
      } })))),
  el("div", { class: "composer-row" }, box, button));
  return [
    el("h2", { text: asPrompt ? "Send a prompt" : "Send a message" }),
    composer,
    el("p", { class: "composer-hint", text: (asking
      ? "It's asking you something in its terminal, so a prompt can't be typed there until you answer it."
      : asPrompt ? "It wakes up with this as your next prompt, as if you had typed it."
      : "It arrives as a message from Let Them Talk and is read between its steps.") +
      " Enter sends; Shift+Enter adds a line. Paste or drop images to send them too." }),
  ];
}

// An up arrow for the round Send button, drawn like plusIcon.
function sendIcon() {
  const icon = svg("svg", { width: 14, height: 14, viewBox: "0 0 14 14", "aria-hidden": "true" });
  icon.append(svg("path", { d: "M7 12V2.5M2.75 6.5 7 2.25l4.25 4.25", fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" }));
  return icon;
}

// Adds images (pasted or dropped) to what goes with a chat's next text (key:
// its sessionId) or a new agent's first prompt (NEW_AGENT), with a thumbnail
// each; others are refused with a notice. redraw shows them.
async function addImages(sid, files, redraw = renderDrawer) {
  const take = [], refused = new Set();
  for (const f of files) {
    if (!IMAGE_TYPES.includes(f.type)) refused.add("Only PNG, JPEG, GIF and WebP images can be sent.");
    else if (f.size > IMAGE_MB << 20) refused.add(`${f.name || "That image"} is over ${IMAGE_MB} MB; send a smaller one.`);
    else if ((state.images[sid] || []).length + take.length >= IMAGE_COUNT) refused.add(`Send at most ${IMAGE_COUNT} images at a time.`);
    else take.push(f);
  }
  refused.forEach((why) => toast(why, "error"));
  const read = (f) => new Promise((done, fail) => {
    const r = new FileReader();
    r.onload = () => done(r.result.slice(r.result.indexOf(",") + 1));  // base64, without "data:...,"
    r.onerror = () => fail(r.error);
    r.readAsDataURL(f);
  });
  try {
    for (const f of take) {
      const data = await read(f);  // the list may have been sent meanwhile: add to the current one
      (state.images[sid] ||= []).push({ url: URL.createObjectURL(f), data });
    }
  } catch (e) {
    toast(`An image couldn't be read: ${e?.message || e}`, "error");
  }
  redraw();
}

// Images dropped anywhere on a chat's (or a subagent's) details go into its
// Send box, so they needn't hit the box itself. The cue is a class on the
// drawer, which the polls don't redraw (they redraw what is in it).
const draggingFiles = (e) => !!e.dataTransfer?.types.includes("Files");
const dropsInto = () => {
  const sel = state.selected;
  if (sel?.type === "node" && $("#drawer-body #send-box")) return sel.id;
  return sel?.type === "sub" && $("#drawer-body #sub-box") ? `${sel.parent}:${sel.id}` : null;  // its key (subActions)
};
$("#drawer").addEventListener("dragover", (e) => {
  if (!draggingFiles(e) || !dropsInto()) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  $("#drawer").classList.add("dropping");
});
$("#drawer").addEventListener("dragleave", (e) => {
  if (!$("#drawer").contains(e.relatedTarget)) $("#drawer").classList.remove("dropping");
});
$("#drawer").addEventListener("drop", (e) => {
  $("#drawer").classList.remove("dropping");
  const sid = dropsInto();
  if (!sid || !e.dataTransfer.files.length) return;
  e.preventDefault();
  addImages(sid, [...e.dataTransfer.files]);
});
// A file dropped anywhere else is turned away: the browser would open it in
// place of the app. Only file drags: other drags are left alone. The cue goes
// too, should the details have missed the drag leaving them.
for (const type of ["dragover", "drop"]) {
  window.addEventListener(type, (e) => {
    if (!draggingFiles(e) || e.defaultPrevented) return;
    $("#drawer").classList.remove("dropping");
    e.preventDefault();
    e.dataTransfer.dropEffect = "none";
  });
}

// Sends text (and images) to a chat, shown in it at once as your bubble, like
// a phone; the bubble gives way to the real message once the chat has read
// it (see settleOutbox). If sending fails, the bubble goes and failed() runs.
async function sendAsBubble(n, text, failed, images = []) {
  const sid = n.sessionId, shown = [text, images.map((_, i) => `[Image #${i + 1}]`).join("\n")].filter(Boolean);
  const out = { text: shown.join("\n\n"), at: Date.now() / 1000, state: "sending" };
  (state.outbox[sid] ||= []).push(out);
  state.sending.add(sid);
  renderDrawer();
  try {
    if (await sendTo(n, text, undefined, images)) {
      out.state = "sent";
      images.forEach((i) => URL.revokeObjectURL(i.url));
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
    toast(failText(e), "error");
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
      !restart && where(n) && conversationButton(n, "Open in", "btn"),
      !restart && el("button", { class: "btn",
        text: state.logs[n.sessionId] ? "Hide its screen" : blocked ? "What is it asking?" : "Show its screen",
        onclick: () => state.logs[n.sessionId]
          ? (delete state.logs[n.sessionId], renderDrawer())
          : agentAction(n, "agent-logs", (r) => { state.logs[n.sessionId] = r.text; renderDrawer(); }) }),
      !restart && compactButton(n),
      n.running && n.status !== "idle" && el("button", { class: "btn", text: "Stop",
        onclick: () => confirm(`Stop ${display(n)}? It stops whatever it is doing now, as Esc does ` +
          "in its terminal. It keeps running, and its terminal stays open.")
          && agentAction(n, "agent-stop", () => toast(`Stopped ${display(n)}. It's waiting for you.`, "ok")) })),
    state.logs[n.sessionId] && el("pre", { class: "logs mono", text: state.logs[n.sessionId] }),
    ...(restart ? [] : ultracodeRow(n)),
  ];
}

// Ultracode: it runs a workflow for every bigger task without being asked each
// time. The server types /effort ultracode on|off into a running background
// agent, as you would in its terminal, and reads its state from its
// conversation; after a restart, while these details are open, it looks in
// the agent's /effort panel once ("checking…"). If that can't tell, it is
// unknown until its next prompt, so both buttons show then.
state.ultra = {};  // sessionId -> "on" | "off" being switched (kept across redraws)
function ultracodeRow(n) {
  if (!n.running) return [el("p", { class: "muted small", text: "Ultracode can be turned on or off while it runs." })];
  const chat = state.chat[n.sessionId], on = chat?.ultracode, busy = state.ultra[n.sessionId];
  const checking = on == null && chat?.ultracodeChecking;
  const button = (want) => el("button", { class: "btn", disabled: !!busy || checking,
    text: busy === want ? `Turning ${want}…` : `Turn ${want}`,
    title: `Types /effort ultracode ${want} into it, as in its terminal (until it ends)`,
    onclick: () => setUltracode(n, want) });
  return [
    el("div", { class: "drawer-actions ultracode" },
      el("span", { text: on === true ? "Ultracode is on" : on === false ? "Ultracode is off"
        : checking ? "Ultracode: checking…" : "Ultracode: unknown" }),
      on !== true && button("on"), on !== false && button("off")),
    el("p", { class: "muted small", text: "With ultracode on, it runs a workflow (a team of agents) for every bigger task." +
      (checking ? " To find out, the app opens /effort in it and closes it again, changing nothing."
        : on == null ? " Whether it's on shows after its next prompt." : "") }),
  ];
}

async function setUltracode(n, want) {
  state.ultra[n.sessionId] = want;
  renderDrawer();
  try {
    const res = await api(`/api/board/${state.boardId}/ultracode`, { sessionId: n.sessionId, on: want === "on" });
    if (state.chat[n.sessionId]) state.chat[n.sessionId].ultracode = res.result.ultracode;
    toast(`${display(n)}: ${res.result.said}`, "ok");  // Claude Code's own answer
  } catch (e) {
    toast(failText(e), "error");
  } finally {
    delete state.ultra[n.sessionId];
    renderDrawer();
    poll();
  }
}

// Compact: Claude Code sums up a background agent's conversation so far (its
// /compact), so it goes on with its context freed. The server types /compact
// into it, or wakes an ended one with it, and watches its conversation; the
// notices say how it went (see renderLaunches). Not while it works or asks
// you something. Other chats only get messages: type /compact in them.
state.compacting = new Set();  // sessionIds whose Compact request is on its way
const compacting = (n) => state.compacting.has(n.sessionId) || (state.view?.launches || [])
  .some((l) => l.kind === "compact" && l.from === n.sessionId && l.state === "compacting");

function compactButton(n) {
  const busy = compacting(n), wakes = !n.running ? " It wakes up for it." : "";
  const waits = !n.running ? null : n.status === "busy" || n.agentState === "working"
    ? "It can be compacted once it's idle." : n.status === "waiting" || n.agentState === "blocked"
      ? "It can be compacted once you've answered it." : null;
  return el("button", {
    class: "btn", text: busy ? "Compacting…" : "Compact", disabled: busy || !!waits,
    title: waits || "Types /compact into it, as in its terminal: Claude Code sums up its conversation so far, " +
      `so it goes on with its context freed.${wakes}`,
    onclick: async () => {
      if (!confirm(`Compact ${display(n)}? Claude Code replaces its conversation so far with a summary: its ` +
        `context is freed, but details the summary leaves out are gone for it.${wakes}`)) return;
      state.compacting.add(n.sessionId);
      renderDrawer();
      try {
        await api(`/api/board/${state.boardId}/compact`, { sessionId: n.sessionId });
        await poll();  // its launch says it is compacting from now on
      } catch (e) {
        toast(failText(e), "error");
      } finally {
        state.compacting.delete(n.sessionId);
        renderDrawer();
      }
    },
  });
}

// Deleting a background agent can't be undone, so it sits at the bottom with
// the other ways a card goes, not beside Open in terminal and Stop.
// End: it stops and its terminals close, but it stays (a prompt wakes it), as
// End this chat for a chat in a terminal. Delete: it is gone from the list.
function deleteControls(n) {
  return el("div", { class: "drawer-actions" },
    n.running && el("button", { class: "btn", text: "End agent",
      title: "claude stop: it stops and its terminal windows close; it stays here, and a prompt wakes it",
      onclick: () => {
        const midway = n.status === "busy" ? " It stops in the middle of what it is doing." : "";
        if (confirm(`End ${display(n)}?${midway} It stops and its terminal windows close. ` +
          "It stays on the board: send it a prompt to wake it.")) {
          agentAction(n, "agent-end", () => toast(`Ended ${display(n)}. Send it a prompt to wake it.`, "ok"));
        }
      } }),
    el("button", { class: "btn danger", text: "Delete agent",
      title: "claude rm: removes it from Claude Code's list, with its own worktree if it has one (its conversation stays on disk)",
      onclick: () => confirm(`Delete the background agent ${display(n)}? It's removed for good, with its own ` +
        "worktree if it has one. Its conversation stays on disk.")
        && agentAction(n, "agent-delete", () => { toast(`Deleted ${display(n)}.`, "ok"); closeDrawer(); }) }));
}
