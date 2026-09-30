"use strict";

const POLL_MS = 2500;
const NODE_W = 220;
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
  runOpen: {},           // runId (or "direct:<sid>") -> expanded in the drawer
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
    headers: { "Content-Type": "application/json", "X-Organizer": "1" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key));
    localStorage.setItem(key, JSON.stringify(value));
  } catch { return null; }
}

const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const folderName = (cwd) => (cwd || "").replace(/\/+$/, "").split("/").pop() || cwd || "?";
// The server reads the editor (Cursor, VS Code, ...) from the claude binary's path.
const opener = (n) => n.editor ||
  ({ "claude-vscode": "Editor", cli: "Terminal", "sdk-cli": "Headless" }[n.entrypoint] || n.entrypoint || "");
// Cards show the title Claude Code gave the session; @name is its address.
const display = (n) => n.title || (n.name ? `@${n.name}` : `session ${n.sessionId.slice(0, 8)}`);
const where = (n) => n.winCwd || n.cwd;  // Windows sessions keep their C:\ path
const onWindows = (n) => n.platform === "windows";
const nodeById = (id) => state.view?.nodes.find((n) => n.sessionId === id);
const connById = (id) => state.view?.board.connections.find((c) => c.id === id);

function nodePos(n) {
  return state.localPos[n.sessionId] || { x: n.x, y: n.y };
}

function toWorld(evt) {
  const r = $("#canvas").getBoundingClientRect();
  return { x: evt.clientX - r.left - state.pan.x, y: evt.clientY - r.top - state.pan.y };
}

// Same wording as who()/default_notes() in server.py, so the preview is what gets sent.
const who = (s) => s.title
  ? `"${s.title}" (@${s.name}, folder: ${s.cwd})`
  : `@${s.name} (folder: ${s.cwd})`;

function defaultNotes(src, dst, reason, tellSrc = true) {
  const why = reason.trim() || "(no reason given)";
  const start = (other) => `Start now: send @${other.name} your current view on this with ` +
    `SendMessage, then reply when it answers. No reply to the organizer is needed.`;
  return {
    from: `[Agent organizer] Your user connected you to ${who(dst)} and wants you two to talk.\n` +
      `Why: ${why}\n` + start(dst),
    to: `[Agent organizer] Your user connected ${who(src)} to you and wants you two to talk.\n` +
      `Why: ${why}\n` + (tellSrc
        ? `@${src.name} will message you about this. When it does, reply to @${src.name} ` +
          `with SendMessage. No reply to the organizer is needed.`
        : start(src)),
  };
}

// ------------------------------------------------------------------- boards

async function start() {
  const data = await api("/api/state");
  const wanted = new URLSearchParams(location.hash.slice(1)).get("board") || store("organizer.board");
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
  state.pan = store(`organizer.pan.${id}`) || { x: 0, y: 0 };
  state.fitPending = true;  // re-center once if the saved pan hides every card
  store("organizer.board", id);
  history.replaceState(null, "", `#board=${id}`);
  closeDrawer();
  poll();
}

async function poll() {
  clearTimeout(state.pollTimer);
  if (state.boardId) {
    try {
      state.view = await api(`/api/state?board=${encodeURIComponent(state.boardId)}`);
      render();
      if (state.selected?.type === "node") loadAgents(state.selected.id);
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
  $("#board-folder").textContent = v.board.folder;
  $("#board-folder").title = v.board.folder;
  $("#world").style.transform = `translate(${state.pan.x}px, ${state.pan.y}px)`;
  $("#empty").hidden = v.nodes.length > 0;
  renderNodes();
  if (state.fitPending && v.nodes.length) {
    state.fitPending = false;
    if (!anyCardInView()) fitView();
  }
  renderWires();
  renderAvailable();
  renderActivity();
  if (state.selected) renderDrawer();
}

function cardBox(n) {
  const pos = nodePos(n);
  const h = $(`#nodes [data-id="${n.sessionId}"]`)?.offsetHeight || 90;
  return { x0: pos.x, y0: pos.y, x1: pos.x + NODE_W, y1: pos.y + h };
}

function anyCardInView() {
  const r = $("#canvas").getBoundingClientRect();
  return state.view.nodes.some((n) => {
    const b = cardBox(n);
    return b.x1 + state.pan.x > 0 && b.x0 + state.pan.x < r.width &&
      b.y1 + state.pan.y > 0 && b.y0 + state.pan.y < r.height;
  });
}

// Pan so all cards are centered (or start at the top left if they don't fit).
function fitView() {
  const nodes = state.view?.nodes || [];
  if (!nodes.length) return;
  const r = $("#canvas").getBoundingClientRect();
  const boxes = nodes.map(cardBox);
  const x0 = Math.min(...boxes.map((b) => b.x0)), x1 = Math.max(...boxes.map((b) => b.x1));
  const y0 = Math.min(...boxes.map((b) => b.y0)), y1 = Math.max(...boxes.map((b) => b.y1));
  const place = (lo, hi, size) => (hi - lo > size - 80 ? 40 - lo : (size - (hi - lo)) / 2 - lo);
  state.pan = { x: Math.round(place(x0, x1, r.width)), y: Math.round(place(y0, y1, r.height)) };
  store(`organizer.pan.${state.boardId}`, state.pan);
  $("#world").style.transform = `translate(${state.pan.x}px, ${state.pan.y}px)`;
  renderWires();
}

function renderNodes() {
  const layer = $("#nodes");
  const seen = new Set();
  for (const n of state.view.nodes) {
    seen.add(n.sessionId);
    let node = layer.querySelector(`[data-id="${n.sessionId}"]`);
    if (!node) {
      node = el("div", { class: "node", "data-id": n.sessionId, "data-name": n.name });
      layer.append(node);
    }
    const status = n.live ? n.status : "ended";
    node.className = "node" + (n.live ? "" : " ended") +
      (state.selected?.type === "node" && state.selected.id === n.sessionId ? " selected" : "");
    const pos = nodePos(n);
    node.style.left = `${pos.x}px`;
    node.style.top = `${pos.y}px`;
    node.dataset.name = n.name;
    node.replaceChildren(
      el("span", { class: "port in" }),
      el("div", { class: "title" },
        el("span", { class: `dot ${status}`, title: status }),
        el("span", { class: "name", text: display(n), title: display(n) })),
      el("div", { class: "meta", text: `${n.name ? `@${n.name} · ` : ""}${folderName(where(n).replace(/\\/g, "/"))}`,
        title: `${n.name ? `Address: @${n.name}\n` : ""}Folder: ${where(n)}` }),
      el("div", { class: "meta badges" },
        el("span", { class: `badge ${onWindows(n) ? "win" : ""}`, text: onWindows(n) ? "Windows" : "WSL",
          title: n.messageBlock || "" }),
        opener(n) && el("span", { class: "badge", text: opener(n) }),
        n.model && el("span", { class: "badge model", text: modelName(n.model), title: n.model }),
        el("span", { class: "badge", text: status }),
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
    const mark = c.status === "sending" ? "… " : c.status === "failed" ? "! " : "";
    const label = el("div", {
      class: `wire-label ${c.status === "failed" ? "failed" : ""} ${selected ? "selected" : ""}`,
      text: mark + (c.reason.trim() || "no reason given"),
      title: c.reason,
      onpointerdown: (e) => { e.stopPropagation(); select(); },
    });
    const mid = midpoint(p, q);
    label.style.left = `${mid.x}px`;
    label.style.top = `${mid.y}px`;
    labels.append(label);
  }
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
    el("p", { class: "folder-name mono", text: cwd, title: cwd }),
    ...groups[cwd].map((s) => el("div", { class: "avail-row" },
      el("span", { class: `dot ${s.status}`, title: s.status }),
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
$("#activity-box").open = store("organizer.activityOpen") === true;
$("#activity-box").addEventListener("toggle", () => store("organizer.activityOpen", $("#activity-box").open));

// ------------------------------------------------------------------- drawer

function select_(sel) {
  state.selected = sel;
  render();
  renderDrawer();
  if (sel.type === "node") loadAgents(sel.id);
}

async function loadAgents(sid) {
  try {
    state.agents[sid] = await api(`/api/agents?session=${encodeURIComponent(sid)}`);
  } catch (e) {
    state.agents[sid] = { error: e.message };
  }
  if (state.selected?.type === "node" && state.selected.id === sid) renderDrawer();
}

function closeDrawer() {
  state.selected = null;
  $("#drawer").hidden = true;
  if (state.view) render();
}

function renderDrawer() {
  const body = $("#drawer-body");
  const sel = state.selected;
  if (!sel) return;
  if (sel.type === "wire") {
    const c = connById(sel.id);
    if (!c) return closeDrawer();
    body.replaceChildren(...wireDetails(c).filter(Boolean));
  } else {
    const n = nodeById(sel.id);
    if (!n) return closeDrawer();
    body.replaceChildren(...nodeDetails(n).filter(Boolean));
  }
  $("#drawer").hidden = false;
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
  const notify = el("input", { type: "checkbox", id: "d-notify", checked: true });
  const failed = Object.values(c.notes).some((n) => n.enabled && n.state === "failed");
  return [
    el("h3", { text: `${a ? display(a) : "?"} → ${b ? display(b) : "?"}` }),
    el("dl", {},
      el("dt", { text: "Why" }), el("dd", { text: c.reason.trim() || "no reason given" }),
      el("dt", { text: "Connected" }), el("dd", { text: new Date(c.createdAt * 1000).toLocaleString() }),
      el("dt", { text: "Status" }), el("dd", { text: c.status })),
    ...notes,
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
        onclick: async () => { await act("disconnect", { id: c.id, notify: notify.checked }); closeDrawer(); },
      })),
  ];
}

function nodeDetails(n) {
  const conns = state.view.board.connections.filter((c) => c.from === n.sessionId || c.to === n.sessionId);
  return [
    el("h3", { text: display(n) }),
    el("dl", {},
      el("dt", { text: "Address" }), el("dd", { class: "mono small", text: `@${n.name}` }),
      el("dt", { text: "Status" }), el("dd", { text: n.live ? n.status : "session ended" }),
      el("dt", { text: "Runs on" }), el("dd", { text: onWindows(n) ? "Windows" : "WSL" }),
      el("dt", { text: "Folder" }), el("dd", { class: "mono small", text: where(n) }),
      n.messageBlock && [el("dt", { text: "Notes" }), el("dd", { class: "small", text: `Can't receive notes. ${n.messageBlock}` })],
      n.live && [el("dt", { text: "Opened in" }), el("dd", { text: opener(n) || "?" })],
      n.model && [el("dt", { text: "Model" }), el("dd", { text: modelName(n.model) })],
      el("dt", { text: "Session" }), el("dd", { class: "mono small", text: n.sessionId })),
    ...agentsSection(n),
    el("h2", { text: "Connections" }),
    conns.length ? el("ul", {}, ...conns.map((c) => {
      const other = nodeById(c.from === n.sessionId ? c.to : c.from);
      const dir = c.from === n.sessionId ? "→" : "←";
      return el("li", {}, el("a", {
        href: "#", text: `${dir} ${other ? display(other) : "?"}: ${c.reason.trim() || "no reason given"}`,
        onclick: (e) => { e.preventDefault(); select_({ type: "wire", id: c.id }); },
      }));
    })) : el("p", { class: "muted small", text: n.messageBlock
      ? "None. This session can't be connected until it can receive notes."
      : "None. Drag the blue handle onto another agent to connect them." }),
    removeControls(n, conns),
  ];
}

// A card can always go; its arrows go with it. Agents still running at the
// other end of an arrow can be told, as with Disconnect.
function removeControls(n, conns) {
  const liveEnds = conns.filter((c) => {
    const other = nodeById(c.from === n.sessionId ? c.to : c.from);
    return other?.live || n.live;
  }).length;
  const notify = el("input", { type: "checkbox", id: "r-notify", checked: liveEnds > 0 });
  const arrows = conns.length === 1 ? "its arrow" : `its ${conns.length} arrows`;
  return el("div", { class: "drawer-actions" },
    liveEnds > 0 && el("label", { class: "small check" }, notify, " Tell connected agents"),
    el("button", {
      class: conns.length ? "btn danger" : "btn",
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

function agentRow(a, labelText) {
  return el("div", { class: "agent-row" },
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

function runGroup(r) {
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
    body.push(...inPhase.map((a) => agentRow(a, a.label)));
  }
  if (!r.agents.length) body.push(el("p", { class: "muted small", text: "No agents recorded yet." }));
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
  const out = [head, ...runs.map(runGroup)];
  if (direct.length) {
    const live = direct.filter((a) => a.state === "running").length;
    out.push(group(`direct:${n.sessionId}`, true, [
      el("span", { class: stateClass(live ? "running" : "done") }),
      el("div", { class: "run-head" },
        el("div", { class: "run-name", text: "Subagents" }),
        el("div", { class: "agent-meta", text: `${direct.length} started${live ? ` · ${live} running` : ""}` })),
    ], direct.map((a) => agentRow(a, a.agentType ? `${a.description} (${a.agentType})` : a.description))));
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
    x: r.width / 2 - state.pan.x - NODE_W / 2 + (count % 5) * 18,
    y: r.height / 3 - state.pan.y + (count % 5) * 18,
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
    state.drag = { kind: "pan", x0: evt.clientX, y0: evt.clientY, ox: state.pan.x, oy: state.pan.y, moved: false };
    canvas.classList.add("panning");
  }
  if (state.drag) canvas.setPointerCapture(evt.pointerId);
});

canvas.addEventListener("pointermove", (evt) => {
  if (state.connecting) return drawDraft(evt);
  const d = state.drag;
  if (!d) return;
  const dx = evt.clientX - d.x0, dy = evt.clientY - d.y0;
  if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
  if (!d.moved) return;
  if (d.kind === "node") {
    state.localPos[d.id] = { x: Math.round(d.ox + dx), y: Math.round(d.oy + dy) };
    const node = $(`#nodes [data-id="${d.id}"]`);
    node.style.left = `${state.localPos[d.id].x}px`;
    node.style.top = `${state.localPos[d.id].y}px`;
    renderWires();
  } else {
    state.pan = { x: d.ox + dx, y: d.oy + dy };
    $("#world").style.transform = `translate(${state.pan.x}px, ${state.pan.y}px)`;
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
    if (d.moved) store(`organizer.pan.${state.boardId}`, state.pan);
    else if (state.selected) closeDrawer();
    return;
  }
  if (!d.moved) return select_({ type: "node", id: d.id });
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

function openBoardDialog(folders, boards, places = []) {
  const have = new Set(boards.map((b) => b.folder));
  const free = folders.filter((f) => !have.has(f));
  $("#b-folders").replaceChildren(...folders.map((f) => el("option", { value: f })));
  $("#b-places").replaceChildren(...places.map((pl) => el("button", {
    type: "button", class: "btn place", text: pl.label, title: pl.path, onclick: () => browse(pl.path),
  })));
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
// the folder you are in, so Create uses it.
async function browse(path) {
  const box = $("#b-browser");
  try {
    const d = await api("/api/dirs", { path });
    $("#b-folder").value = d.path;
    $("#b-error").hidden = true;
    const into = (name) => `${d.path.replace(/\/+$/, "")}/${name}`;
    box.replaceChildren(
      el("div", { class: "browse-head" },
        el("button", { type: "button", class: "btn", text: "↑ Up", disabled: !d.parent, onclick: () => browse(d.parent) }),
        el("span", { class: "mono small", text: d.path, title: d.path })),
      el("div", { class: "browse-list" }, ...(d.dirs.length
        ? d.dirs.map((name) => el("button", { type: "button", class: "browse-item", text: name, onclick: () => browse(into(name)) }))
        : [el("p", { class: "muted small", text: "No subfolders here." })])),
      ...(d.truncated ? [el("p", { class: "muted small", text: "Showing the first 1000 folders." })] : []));
    box.hidden = false;
  } catch (e) {
    $("#b-error").textContent = e.message;
    $("#b-error").hidden = false;
  }
}

$("#b-browse").addEventListener("click", () => browse($("#b-folder").value.trim()));

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
  document.body.prepend(el("p", { class: "error", text: `Could not reach the organizer server: ${e.message}` }));
});

$("#fit-view").addEventListener("click", fitView);

// Side panels: drag the inner edge to resize, double-click it to reset; the
// width is remembered. dir is +1 when the edge is on the panel's right side.
function resizable(panel, handle, key, def, dir) {
  const MIN = 180, MAX = 720;
  const set = (w) => { panel.style.width = `${Math.min(MAX, Math.max(MIN, w))}px`; };
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
resizable($(".sidebar"), $("#sidebar-resizer"), "organizer.sidebarW", 280, +1);
resizable($("#drawer"), $("#drawer-resizer"), "organizer.drawerW", 360, -1);
