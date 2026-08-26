/* Vibe Tracks frontend — ink-on-paper rebuild.
   Vanilla JS: one state object, render functions over state.project,
   delegated events. Codes against docs/api.md; the Markdown files on
   disk remain the database, this page is a lens plus three narrow,
   revision-fenced writes (status, dependencies, comment). */

/* A `running` note whose file has not changed in this many minutes is a
   claim nobody is backing up any more — the panel says so rather than
   rendering it identically to work that is genuinely in flight. */
const STALE_RUNNING_MINUTES = 15;
const VIEWS = new Set(["graph", "kanban", "focus"]);

const state = {
  project: null,
  view: localStorage.getItem("vibetracks.view") || "graph",
  selectedId: null,
  detailOpen: false,
  query: "",
  area: "all",
  showArchived: false,
  busy: false,
  feedbackDrafts: {},
  /* Liveness. The panel cannot watch an agent; it can only watch the files
     the agent leaves behind. These three make that watching visible. */
  freshOnly: false,      // filter down to "changed since I last looked"
  lastSeen: undefined,   // epoch ms, resolved from localStorage on first load
  clockSkewMs: 0,        // browser clock − server clock, so ages use file time
};

const $ = (selector) => document.querySelector(selector);
const stage = $("#view-stage");
const detail = $("#detail-panel");

/* ---------- small helpers ---------- */

function esc(value) {
  const replacements = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return String(value ?? "").replace(/[&<>"']/g, (character) => replacements[character]);
}

function isExternalUrl(path) {
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(String(path || ""));
}

/* External URLs (a CI run, a hosted report) pass through untouched;
   everything else is a project-relative file served by /api/media. */
function mediaUrl(path) {
  if (isExternalUrl(path)) return path;
  return `/api/media?path=${encodeURIComponent(path)}`;
}

/* ---------- liveness: ages, staleness, and what is new ---------- */

/* Ages are measured against the machine that owns the files. The snapshot
   carries the server's clock; the difference is held as a skew so ages keep
   ticking between polls instead of freezing at snapshot time. */
function noteServerClock(iso) {
  const serverNow = Date.parse(iso);
  if (Number.isFinite(serverNow)) state.clockSkewMs = Date.now() - serverNow;
}

function ageMs(iso) {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return null;
  return Math.max(0, Date.now() - state.clockSkewMs - at);
}

function ageMinutes(iso) {
  const ms = ageMs(iso);
  return ms === null ? null : Math.floor(ms / 60000);
}

/* Compact form for cards — "3m", "2h", "4d". */
function shortAge(iso) {
  const minutes = ageMinutes(iso);
  if (minutes === null) return "";
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

/* Sentence form for the header pulse. */
function longAge(iso) {
  const minutes = ageMinutes(iso);
  if (minutes === null) return "unknown";
  if (minutes < 1) return "seconds ago";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/* `touched` is the file's mtime — the one timestamp the agent claiming to be
   busy cannot write by hand. Prefer it; fall back to the declared value. */
function itemTime(item) {
  return item.touched || item.updated;
}

function seenKey() {
  return `vibetracks.lastSeen.${state.project?.id || "project"}`;
}

function isFresh(item) {
  if (!state.lastSeen) return false; // first visit: nothing is "new" yet
  const at = Date.parse(itemTime(item));
  return Number.isFinite(at) && at > state.lastSeen;
}

/* Minutes of silence behind a `running` claim, or 0 when the claim is fresh
   (or the item is not claiming to run at all). */
function staleRunningMinutes(item) {
  if (item.status !== "running") return 0;
  const minutes = ageMinutes(itemTime(item));
  return minutes !== null && minutes >= STALE_RUNNING_MINUTES ? minutes : 0;
}

function markBoardSeen() {
  state.lastSeen = Date.now() - state.clockSkewMs;
  try {
    localStorage.setItem(seenKey(), String(state.lastSeen));
  } catch (error) {
    /* private-mode storage failure must not break the board */
  }
  state.freshOnly = false;
  render();
}

function statusGlyph(status) {
  const glyphs = {
    backlog: "·",
    ready: "→",
    running: "↻",
    waiting: "…",
    review: "!",
    frontier: "?",
    done: "✓",
    archived: "○",
  };
  return glyphs[status] || "·";
}

/* The status line carries three facts, not one: the claim, how old the claim
   is, and whether it changed since you last marked the board seen. */
function statusMark(item) {
  const stale = staleRunningMinutes(item);
  const staleTag = stale
    ? `<span class="stale-tag" title="Status says running, but this note has not changed in ${stale} minutes.">stale</span>`
    : "";
  const freshTag = isFresh(item)
    ? `<span class="fresh-dot" title="Changed since you last marked the board seen."></span>`
    : "";
  const age = shortAge(itemTime(item));
  const ageTag = age
    ? `<span class="age" title="Note file last changed ${esc(itemTime(item))}">${esc(age)}</span>`
    : "";
  return `<span class="status-row"><span class="status-line st-${esc(item.status)}${stale ? " stale" : ""}">${statusGlyph(item.status)} ${esc(item.status)}</span>${staleTag}${ageTag}${freshTag}</span>`;
}

function priorityRank(priority) {
  const ranks = { urgent: 0, high: 1, medium: 2, low: 3, none: 4 };
  return ranks[priority] ?? 4;
}

function itemById(id) {
  if (!state.project) return null;
  return state.project.items.find((item) => item.id === id) || null;
}

function areaDescription(name) {
  const catalog = state.project?.areaCatalog || [];
  const entry = catalog.find((area) => area.name === name);
  return entry && entry.description ? entry.description : "";
}

function areaChipMarkup(name, extraClass = "") {
  const description = areaDescription(name);
  const tooltip = description ? ` title="${esc(description)}"` : "";
  return `<button class="area-chip${extraClass}" data-area="${esc(name)}"${tooltip}>${esc(name)}</button>`;
}

function filteredItems() {
  if (!state.project) return [];
  const query = state.query.trim().toLowerCase();
  return state.project.items.filter((item) => {
    if (!state.showArchived && item.archived) return false;
    if (state.freshOnly && !isFresh(item)) return false;
    if (state.area !== "all" && !item.areas.includes(state.area)) return false;
    if (query) {
      const haystack = `${item.id} ${item.title} ${item.description} ${item.areas.join(" ")}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    toast.className = "toast";
  }, 3000);
}

function setSync(message, isError = false) {
  $("#sync-label").textContent = message;
  $(".sync-state").classList.toggle("error", isError);
}

/* ---------- data loading ---------- */

function ensureSelection() {
  if (state.selectedId && itemById(state.selectedId)) return;
  const firstReview = state.project.items.find((item) => item.status === "review");
  state.selectedId = firstReview?.id || state.project.items[0]?.id || null;
}

/* Responses can complete out of order (the 3 s poll racing a post-write
   forced reload); a sequence number keeps an older snapshot from
   overwriting a newer one. */
let loadSequence = 0;
let appliedSequence = 0;

async function loadProject(force = false) {
  const sequence = ++loadSequence;
  try {
    const knownRevision = !force && state.project ? state.project.revision : null;
    const url = knownRevision
      ? `/api/project?known=${encodeURIComponent(knownRevision)}`
      : "/api/project";
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    if (sequence < appliedSequence) return; // a newer response already landed
    appliedSequence = sequence;
    if (payload.now) noteServerClock(payload.now);
    if (payload.unchanged) {
      setSync("files current");
      renderPulse(); // ages keep moving even when nothing changed
      return;
    }
    state.project = payload;
    if (state.lastSeen === undefined) {
      const stored = Number(localStorage.getItem(seenKey()));
      state.lastSeen = Number.isFinite(stored) && stored > 0 ? stored : 0;
    }
    ensureSelection();
    renderUnlessTyping();
    setSync("files current");
  } catch (error) {
    setSync("read failed", true);
    if (!state.project) {
      stage.innerHTML = `<div class="empty"><div><b>Could not load this track.</b><p>${esc(error.message)}</p></div></div>`;
    }
  }
}

/* ---------- header, filters, feature rail ---------- */

/* The trust line. A board that renders a 45-minute-old claim exactly like a
   live one cannot be told apart from a static document, so this says out
   loud when the files stopped moving, when a `running` claim has gone quiet,
   and how much changed since the last time you looked. */
function renderPulse() {
  const host = $("#board-pulse");
  if (!host || !state.project) return;
  const items = state.project.items.filter((item) => !item.archived);
  const times = items
    .map((item) => Date.parse(itemTime(item)))
    .filter((value) => Number.isFinite(value));
  const newest = times.length ? new Date(Math.max(...times)).toISOString() : null;
  const running = items.filter((item) => item.status === "running");
  const stale = running.filter((item) => staleRunningMinutes(item));
  const fresh = items.filter(isFresh);
  const quietMinutes = newest === null ? null : ageMinutes(newest);
  const cold = quietMinutes !== null && quietMinutes >= STALE_RUNNING_MINUTES;

  const parts = [];
  if (newest === null) {
    parts.push(`<span class="pulse-item">no feature notes yet</span>`);
  } else {
    parts.push(
      `<span class="pulse-item${cold ? " cold" : " warm"}" title="Newest change across every feature note in this track.">`
      + `<span class="pulse-dot" aria-hidden="true"></span>files changed ${esc(longAge(newest))}</span>`);
  }
  if (stale.length) {
    parts.push(
      `<button class="pulse-item alarm" data-pulse="stale" title="These notes say running but have not changed in ${STALE_RUNNING_MINUTES}+ minutes. Nobody is reporting on them.">`
      + `${stale.length} stale running</button>`);
  } else if (!running.length && cold) {
    parts.push(
      `<span class="pulse-item alarm" title="No note claims to be running and none has changed recently. Whatever the agents are doing, they are not writing it here.">`
      + `nothing is reporting work</span>`);
  }
  if (fresh.length) {
    parts.push(
      `<button class="pulse-item news${state.freshOnly ? " active" : ""}" data-pulse="fresh" title="Filter the board down to notes that changed since you last marked it seen.">`
      + `${fresh.length} new since you looked</button>`);
    parts.push(`<button class="pulse-item quiet" data-pulse="seen" title="Clear the new markers and start a fresh window.">mark seen</button>`);
  }
  host.innerHTML = parts.join("");
}

function renderHeader() {
  const project = state.project;
  document.title = `${project.title} — Vibe Tracks`;
  const descriptorName = project.descriptor.split(/[\\/]/).pop() || project.descriptor;
  $("#descriptor-label").textContent = descriptorName;
  $("#descriptor-label").title = project.descriptor;
  $("#project-title").textContent = project.title;
  $("#project-title").title = project.description || project.title;
  $("#project-description").textContent = project.description;
  const activeItems = project.items.filter((item) => !item.archived);
  const runningItems = activeItems.filter((item) => item.status === "running");
  const needsYouItems = activeItems.filter(
    (item) => item.status === "review" || item.status === "frontier");
  const staleRunning = runningItems.filter((item) => staleRunningMinutes(item)).length;
  const metrics = [
    [activeItems.length, "active", ""],
    [runningItems.length, staleRunning ? `running · ${staleRunning} stale` : "running",
      staleRunning ? " warn" : ""],
    [needsYouItems.length, "need you", ""],
  ];
  $("#project-metrics").innerHTML = metrics
    .map(([value, label, extra]) =>
      `<div class="metric${extra}"><b>${value}</b><span>${esc(label)}</span></div>`)
    .join("");
  renderPulse();
  document.querySelectorAll("[data-view]").forEach((button) => {
    const isActive = button.dataset.view === state.view;
    button.classList.toggle("active", isActive);
    if (isActive) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function renderFilters() {
  const names = (state.project.areaCatalog || []).map((area) => area.name);
  for (const item of state.project.items) {
    for (const area of item.areas) {
      if (!names.includes(area)) names.push(area);
    }
  }
  const allChip = `<button class="area-chip${state.area === "all" ? " active" : ""}" data-area="all">All areas</button>`;
  const areaChips = names.map((name) =>
    areaChipMarkup(name, state.area === name ? " active" : ""));
  $("#area-filters").innerHTML = [allChip, ...areaChips].join("");
  $("#show-archived").checked = state.showArchived;
}

function renderFeatureRail(items) {
  $("#visible-count").textContent = items.length;
  if (!items.length) {
    $("#feature-list").innerHTML = `<div class="empty"><div><b>No matching features.</b><p>Change the area or search filter.</p></div></div>`;
    return;
  }
  $("#feature-list").innerHTML = items.map((item) => {
    const stale = staleRunningMinutes(item);
    const age = shortAge(itemTime(item));
    const suffix = stale ? `${age} · stale` : age;
    return `
    <button class="feature-row${item.id === state.selectedId ? " selected" : ""}${isFresh(item) ? " fresh" : ""}" data-feature="${esc(item.id)}">
      <span class="row-glyph st-${esc(item.status)}" aria-hidden="true">${statusGlyph(item.status)}</span>
      <span class="row-text"><b>${esc(item.title)}</b><small>${esc(item.id)} · ${esc(item.status)}${suffix ? ` · ${esc(suffix)}` : ""}</small></span>
    </button>`;
  }).join("");
}

/* ---------- shared view pieces ---------- */

function viewHeading(title, description) {
  return `<div class="view-heading"><h2>${esc(title)}</h2><p>${esc(description)}</p></div>`;
}

function cardMarkup(item, className, extra = "") {
  const selected = item.id === state.selectedId ? " selected" : "";
  return `<button class="${className}${selected}" data-feature="${esc(item.id)}">
    ${statusMark(item)}
    <b>${esc(item.id)} · ${esc(item.title)}</b>
    <small>${esc(item.description || "No summary yet.")}</small>${extra}
  </button>`;
}

/* ---------- graph view ---------- */

const GRAPH = {
  nodeWidth: 190,
  columnGap: 244,
  rowGap: 172, // > max clamped node height, so stacked nodes never overlap
  marginX: 30,
  marginY: 40,
  anchorY: 46,
};

function graphLayout(items) {
  const visibleIds = new Set(items.map((item) => item.id));
  const byId = new Map(items.map((item) => [item.id, item]));
  const layerMemo = new Map();

  function layerOf(id, stack = new Set()) {
    if (layerMemo.has(id)) return layerMemo.get(id);
    if (stack.has(id)) return 0; // dependency cycle guard
    stack.add(id);
    const visibleDependencies = (byId.get(id)?.dependencies || [])
      .filter((dependencyId) => visibleIds.has(dependencyId));
    const layer = visibleDependencies.length
      ? Math.max(...visibleDependencies.map((dependencyId) => layerOf(dependencyId, new Set(stack)))) + 1
      : 0;
    layerMemo.set(id, layer);
    return layer;
  }

  const columns = new Map();
  for (const item of items) {
    const layer = layerOf(item.id);
    if (!columns.has(layer)) columns.set(layer, []);
    columns.get(layer).push(item);
  }

  const positions = new Map();
  let maxRows = 1;
  for (const [layer, column] of columns) {
    column.sort((a, b) =>
      priorityRank(a.priority) - priorityRank(b.priority) || a.title.localeCompare(b.title));
    maxRows = Math.max(maxRows, column.length);
    column.forEach((item, row) => {
      positions.set(item.id, {
        x: GRAPH.marginX + layer * GRAPH.columnGap,
        y: GRAPH.marginY + row * GRAPH.rowGap,
      });
    });
  }

  const columnCount = Math.max(0, ...columns.keys()) + 1;
  return {
    positions,
    width: Math.max(680, columnCount * GRAPH.columnGap + GRAPH.marginX),
    height: Math.max(560, maxRows * GRAPH.rowGap + GRAPH.marginY + 20),
  };
}

function renderGraph(items) {
  const heading = viewHeading(
    "Dependency graph",
    "Arrows run from prerequisite to dependent. Prerequisites hidden by the current filter appear as cues on the node.");
  if (!items.length) {
    stage.innerHTML = `${heading}<div class="empty"><div><b>No matching features.</b><p>Change the area or search filter.</p></div></div>`;
    return;
  }
  const layout = graphLayout(items);
  const visibleIds = new Set(items.map((item) => item.id));

  const edges = items.flatMap((item) =>
    item.dependencies
      .filter((dependencyId) => visibleIds.has(dependencyId))
      .map((dependencyId) => {
        const from = layout.positions.get(dependencyId);
        const to = layout.positions.get(item.id);
        const startX = from.x + GRAPH.nodeWidth;
        const startY = from.y + GRAPH.anchorY;
        const endX = to.x;
        const endY = to.y + GRAPH.anchorY;
        const path = `M${startX} ${startY} C${startX + 28} ${startY},${endX - 28} ${endY},${endX} ${endY}`;
        const critical = item.status === "review" || item.status === "waiting" ? ' class="critical"' : "";
        return `<path${critical} d="${path}" marker-end="url(#arrow)"/>`;
      })).join("");

  const nodes = items.map((item) => {
    const position = layout.positions.get(item.id);
    const hiddenCount = item.dependencies.filter((dependencyId) => !visibleIds.has(dependencyId)).length
      + item.unresolved_dependencies.length;
    const areasLine = item.areas.length
      ? `<span class="node-areas">${esc(item.areas.slice(0, 3).join(" · "))}</span>`
      : "";
    const hiddenCue = hiddenCount
      ? `<span class="hidden-edge">+ ${hiddenCount} hidden prerequisite${hiddenCount === 1 ? "" : "s"}</span>`
      : "";
    return `<button class="graph-node${item.id === state.selectedId ? " selected" : ""}" data-feature="${esc(item.id)}" style="left:${position.x}px;top:${position.y}px">
      ${statusMark(item)}
      <b>${esc(item.id)} · ${esc(item.title)}</b>
      <small>${esc(item.description || "No summary yet.")}</small>
      ${areasLine}${hiddenCue}
    </button>`;
  }).join("");

  stage.innerHTML = `${heading}
  <div class="graph-scroll"><div class="graph-canvas" style="width:${layout.width}px;height:${layout.height}px">
    <svg class="graph-edges" viewBox="0 0 ${layout.width} ${layout.height}" aria-hidden="true">
      <defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path class="arrowhead" d="M0 0L10 5L0 10Z"/></marker></defs>
      ${edges}
    </svg>
    ${nodes}
  </div></div>`;
}

/* ---------- kanban view ---------- */

function renderKanban(items) {
  const statuses = state.project.statuses.filter(
    (status) => state.showArchived || status !== "archived");
  const columns = statuses.map((status) => {
    const group = items.filter((item) => item.status === status);
    const cards = group.map((item) => cardMarkup(item, "ticket")).join("")
      || `<p class="column-empty">empty</p>`;
    return `<section class="kanban-column">
      <div class="column-head"><span>${statusGlyph(status)} ${esc(status)}</span><span>${group.length}</span></div>
      ${cards}
    </section>`;
  });
  stage.innerHTML = `${viewHeading("Kanban", "One column per status, over the same feature files.")}<div class="kanban">${columns.join("")}</div>`;
}

/* ---------- focus view ---------- */

function renderFocus(items) {
  const needsYou = items
    .filter((item) => item.status === "review" || item.status === "frontier")
    .sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority));
  const readyToDispatch = items
    .filter((item) => item.status === "ready")
    .sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority));
  const workingQuietly = items.filter(
    (item) => item.status === "running" || item.status === "waiting");

  const needsYouCards = needsYou.map((item, index) => {
    const note = item.status === "review"
      ? `${item.dependents.length} downstream feature${item.dependents.length === 1 ? "" : "s"}`
      : "Open question — the decision can wait for you.";
    return cardMarkup(
      item,
      `focus-card${index === 0 ? " primary" : ""}`,
      `<span class="card-note">${esc(note)}</span>`);
  }).join("") || `<div class="empty"><div><b>Nothing needs you.</b><p>The dispatcher can keep moving.</p></div></div>`;

  const dispatchCards = readyToDispatch.map((item) => cardMarkup(item, "focus-card")).join("")
    || `<p class="column-empty">nothing is ready</p>`;
  const quietCards = workingQuietly.map((item) => cardMarkup(item, "focus-card")).join("")
    || `<p class="column-empty">nothing running</p>`;

  stage.innerHTML = `${viewHeading("Focus", "Reviews first, then work that is ready to dispatch.")}
  <div class="focus-grid">
    <section class="focus-lane">
      <h3 class="rule-head"><span>Needs you</span><span>${needsYou.length}</span></h3>
      <p class="lane-note">Review and frontier items, sorted by priority.</p>
      ${needsYouCards}
      <h3 class="rule-head"><span>Next to dispatch</span><span>${readyToDispatch.length}</span></h3>
      ${dispatchCards}
    </section>
    <section class="focus-lane quiet">
      <h3 class="rule-head"><span>Working quietly</span><span>${workingQuietly.length}</span></h3>
      <p class="lane-note">Running and waiting work stays compressed.</p>
      ${quietCards}
    </section>
  </div>`;
}

/* ---------- markdown rendering (escaped first, styled second) ---------- */

function inlineMarkdown(text) {
  return esc(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (match, target, alias) =>
      `<span class="wikilink">${alias || target}</span>`);
}

/* Obsidian-style callouts — `> [!quote] 👦 Feedback — …` — are the human/agent
   conversation, so they get first-class rendering instead of raw quote lines. */
function calloutMarkup(quoteLines) {
  const header = quoteLines[0].match(/^\[!([a-zA-Z]+)\][+-]?\s*(.*)$/);
  const bodyLines = header ? quoteLines.slice(1) : quoteLines;
  const body = bodyLines.map((line) => `<p>${inlineMarkdown(line)}</p>`).join("");
  if (!header) return `<blockquote>${body}</blockquote>`;
  const kind = header[1].toLowerCase();
  const title = header[2] || kind;
  return `<div class="callout callout-${esc(kind)}"><div class="callout-title">${inlineMarkdown(title)}</div>${body}</div>`;
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  let html = "";
  let inList = false;
  let inFence = false;
  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trim();
    if (line.startsWith("```")) {
      if (!inFence && inList) { html += "</ul>"; inList = false; }
      html += inFence ? "</code></pre>" : "<pre><code>";
      inFence = !inFence;
      continue;
    }
    if (inFence) {
      html += `${esc(rawLine)}\n`;
      continue;
    }
    if (line.startsWith(">")) {
      if (inList) { html += "</ul>"; inList = false; }
      const quoteLines = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        const stripped = lines[index].trim().replace(/^>\s?/, "");
        if (stripped) quoteLines.push(stripped);
        index += 1;
      }
      index -= 1; // the loop increment moves past the block's last line
      if (quoteLines.length) html += calloutMarkup(quoteLines);
      continue;
    }
    if (/^!\[\[/.test(line) || /^!\[[^\]]*\]\(/.test(line)) continue; // embeds render in the media grid
    const heading = rawLine.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      if (inList) { html += "</ul>"; inList = false; }
      const level = heading[1].length;
      html += `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
      continue;
    }
    const listItem = rawLine.match(/^\s*[-*]\s+(.+)$/) || rawLine.match(/^\s*\d+[.)]\s+(.+)$/);
    if (listItem) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inlineMarkdown(listItem[1])}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    if (line) html += `<p>${inlineMarkdown(line)}</p>`;
  }
  if (inList) html += "</ul>";
  if (inFence) html += "</code></pre>";
  return html;
}

/* ---------- detail panel ---------- */

function relationButtons(ids) {
  if (!ids.length) return `<span class="detail-meta">None</span>`;
  return ids.map((id) => {
    const related = itemById(id);
    const label = related ? `${related.id} · ${related.title}` : id;
    return `<button class="relation-chip" data-feature="${esc(id)}">${esc(label)}</button>`;
  }).join("");
}

function detailHeaderMarkup(item) {
  const openLink = item.obsidian_uri
    ? `<a href="${esc(item.obsidian_uri)}">Open in Obsidian ↗</a>`
    : `<a href="${esc(mediaUrl(item.path))}" target="_blank" rel="noopener">Open raw Markdown ↗</a>`;
  return `<div class="detail-kicker">feature · ${esc(item.id)}</div>
  <div class="detail-title-row"><h2>${esc(item.title)}</h2><span class="detail-status st-${esc(item.status)}">${statusGlyph(item.status)} ${esc(item.status)}</span></div>
  <p class="detail-description">${esc(item.description || "No summary yet.")}</p>
  <div class="detail-actions">${openLink}<button class="button" id="close-detail">Close</button></div>`;
}

function statusEditorMarkup(item) {
  const options = state.project.statuses
    .map((status) => `<option value="${esc(status)}"${status === item.status ? " selected" : ""}>${esc(status)}</option>`)
    .join("");
  const reviewActions = item.status === "review"
    ? `<div class="review-actions">
        <button data-outcome="done">Approve → done</button>
        <button data-outcome="ready">Changes → ready</button>
        <button data-outcome="frontier">Question → frontier</button>
      </div>`
    : "";
  return `<div class="status-editor"><select id="status-select" aria-label="Status">${options}</select><button class="button primary" id="apply-status">Apply</button></div>${reviewActions}`;
}

function areasSectionMarkup(item) {
  const chips = item.areas.map((area) => areaChipMarkup(area)).join("")
    || `<span class="detail-meta">Unclassified</span>`;
  return `<section class="detail-section"><h3>Areas</h3><div class="relation-list">${chips}</div></section>`;
}

function dependenciesSectionMarkup(item) {
  const resolvedRows = item.dependencies.map((dependencyId) => {
    const dependency = itemById(dependencyId);
    const label = dependency ? `${dependency.id} · ${dependency.title}` : dependencyId;
    return `<div class="dep-row">
      <button class="dep-link" data-feature="${esc(dependencyId)}">${esc(label)}</button>
      <button class="dep-remove" data-remove-dependency="${esc(dependencyId)}" title="Remove this dependency" aria-label="Remove dependency ${esc(dependencyId)}">×</button>
    </div>`;
  });
  const unresolvedRows = item.unresolved_dependencies.map((token) => `<div class="dep-row unresolved">
      <span class="dep-link" title="Did not resolve to a feature note">${esc(token)}</span>
      <button class="dep-remove" data-remove-dependency="${esc(token)}" title="Remove this entry" aria-label="Remove dependency ${esc(token)}">×</button>
    </div>`);
  const rows = [...resolvedRows, ...unresolvedRows].join("")
    || `<span class="detail-meta">None</span>`;

  const candidates = state.project.items.filter((other) =>
    other.id !== item.id && !other.archived && !item.dependencies.includes(other.id));
  const addControl = candidates.length
    ? `<div class="dep-add"><select id="add-dependency" aria-label="Add dependency">
        <option value="">add dependency…</option>
        ${candidates.map((candidate) => `<option value="${esc(candidate.id)}">${esc(candidate.id)} · ${esc(candidate.title)}</option>`).join("")}
      </select></div>`
    : "";
  return `<section class="detail-section"><h3>Dependencies</h3><div class="dep-list">${rows}</div>${addControl}</section>`;
}

function downstreamSectionMarkup(item) {
  return `<section class="detail-section"><h3>Downstream</h3><div class="relation-list">${relationButtons(item.dependents)}</div></section>`;
}

function mediaSectionMarkup(item) {
  const paths = [...new Set([item.preview, ...item.media.map((media) => media.path)].filter(Boolean))];
  if (!paths.length) return "";
  const cells = paths.map((path) =>
    `<a href="${esc(mediaUrl(path))}" target="_blank" rel="noopener"><img src="${esc(mediaUrl(path))}" alt="${esc(item.title)} media" loading="lazy" /></a>`);
  return `<section class="detail-section"><h3>Media</h3><div class="media-grid">${cells.join("")}</div></section>`;
}

function reviewPacketMarkup(item) {
  if (!item.review_packet) return "";
  if (isExternalUrl(item.review_packet)) {
    return `<section class="detail-section"><h3>Review packet</h3>
      <a class="evidence-link" href="${esc(item.review_packet)}" target="_blank" rel="noopener">${esc(item.review_packet)} ↗</a>
    </section>`;
  }
  return `<section class="detail-section"><h3>Review packet</h3>
    <iframe class="review-frame" sandbox="" src="${esc(mediaUrl(item.review_packet))}" title="Review packet for ${esc(item.title)}"></iframe>
    <div class="detail-actions"><a href="${esc(mediaUrl(item.review_packet))}" target="_blank" rel="noopener">Open full report ↗</a></div>
  </section>`;
}

function evidenceSectionMarkup(item) {
  if (!item.evidence.length) return "";
  const links = item.evidence.map((path) =>
    `<a class="evidence-link" href="${esc(mediaUrl(path))}" target="_blank" rel="noopener">${esc(path)} ↗</a>`);
  return `<section class="detail-section"><h3>Evidence</h3>${links.join("")}</section>`;
}

function bodySectionMarkup(item) {
  return `<section class="detail-section"><h3>Feature context</h3><div class="markdown">${renderMarkdown(item.body)}</div></section>`;
}

function runsSectionMarkup(item) {
  if (!item.runs.length) return "";
  const rows = item.runs.map((run) => `<div class="evidence-link">${esc(run)}</div>`);
  return `<section class="detail-section"><h3>Worker runs</h3>${rows.join("")}</section>`;
}

function feedbackSectionMarkup(item) {
  const draft = state.feedbackDrafts[item.id] || "";
  return `<section class="detail-section feedback-box"><h3>Feedback</h3>
    <textarea id="feedback-text" placeholder="Written into the note — the dispatcher reads it there.">${esc(draft)}</textarea>
    <div class="detail-actions"><button class="button primary" id="send-feedback">Send feedback</button></div>
  </section>`;
}

function footerMetaMarkup(item) {
  const stale = staleRunningMinutes(item);
  const staleNote = stale
    ? ` · <span class="stale-tag">running claim is ${stale} min stale</span>`
    : "";
  return `<p class="detail-meta">${esc(item.path)}<br />revision ${esc(item.revision)} · file changed ${esc(longAge(itemTime(item)))}${staleNote}</p>`;
}

function renderDetail() {
  const item = itemById(state.selectedId);
  if (!item) {
    detail.innerHTML = `<div class="empty"><div><b>Select a feature.</b><p>Its context, relations, and review packet open here.</p></div></div>`;
    detail.classList.remove("open");
    syncDetailAccessibility();
    return;
  }
  const sections = [
    detailHeaderMarkup(item),
    statusEditorMarkup(item),
    areasSectionMarkup(item),
    dependenciesSectionMarkup(item),
    downstreamSectionMarkup(item),
    mediaSectionMarkup(item),
    reviewPacketMarkup(item),
    evidenceSectionMarkup(item),
    bodySectionMarkup(item),
    runsSectionMarkup(item),
    feedbackSectionMarkup(item),
    footerMetaMarkup(item),
  ].filter(Boolean);
  detail.innerHTML = `<div class="detail-inner">${sections.join("")}</div>`;
  detail.classList.toggle("open", state.detailOpen);
  syncDetailAccessibility();
}

function syncDetailAccessibility() {
  const hiddenOverlay = window.matchMedia("(max-width: 1180px)").matches && !state.detailOpen;
  detail.toggleAttribute("inert", hiddenOverlay);
  detail.setAttribute("aria-hidden", String(hiddenOverlay));
}

window.addEventListener("resize", syncDetailAccessibility);

/* ---------- writes (all revision-fenced against docs/api.md) ---------- */

async function postFeatureEdit(featureId, action, body, successMessage) {
  if (state.busy) return false;
  state.busy = true;
  try {
    const response = await fetch(`/api/features/${encodeURIComponent(featureId)}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      payload = {};
    }
    if (response.status === 409) {
      showToast("The file changed on disk — reloaded the latest version.", true);
      return false;
    }
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    if (successMessage) showToast(successMessage);
    return true;
  } catch (error) {
    showToast(error.message, true);
    return false;
  } finally {
    // Reload BEFORE clearing busy: until the fresh snapshot lands, any
    // second gesture would carry the pre-write revision and 409.
    await loadProject(true);
    state.busy = false;
  }
}

async function changeStatus(nextStatus) {
  const item = itemById(state.selectedId);
  if (!item || nextStatus === item.status) return;
  await postFeatureEdit(item.id, "status", {
    status: nextStatus,
    expectedRevision: item.revision,
  }, `${item.id} → ${nextStatus}. Markdown updated.`);
}

/* The dependencies endpoint replaces the FULL depends-on list, so every
   edit must resend resolved ids plus unresolved tokens — otherwise a
   remove would silently drop the unresolved entries. */
function fullDependencyList(item) {
  return [...item.dependencies, ...item.unresolved_dependencies];
}

async function removeDependency(token) {
  const item = itemById(state.selectedId);
  if (!item) return;
  const dependsOn = fullDependencyList(item).filter((entry) => entry !== token);
  await postFeatureEdit(item.id, "dependencies", {
    dependsOn,
    expectedRevision: item.revision,
  }, `${item.id} no longer depends on ${token}.`);
}

async function addDependency(newDependencyId) {
  const item = itemById(state.selectedId);
  if (!item || !newDependencyId) return;
  const dependsOn = [...fullDependencyList(item), newDependencyId];
  await postFeatureEdit(item.id, "dependencies", {
    dependsOn,
    expectedRevision: item.revision,
  }, `${item.id} now depends on ${newDependencyId}.`);
}

async function sendFeedback() {
  const item = itemById(state.selectedId);
  if (!item) return;
  const text = ($("#feedback-text")?.value || "").trim();
  if (!text) {
    showToast("Write the feedback first.", true);
    return;
  }
  delete state.feedbackDrafts[item.id]; // clear before the reload re-renders
  const sent = await postFeatureEdit(item.id, "comment", {
    text,
    expectedRevision: item.revision,
  }, "Feedback written into the note");
  if (!sent) {
    state.feedbackDrafts[item.id] = text; // keep the draft on failure
    renderDetail();
  }
}

/* ---------- render root ---------- */

/* A poll-triggered re-render would destroy in-progress input state — the
   feedback textarea's caret, an open status/dependency select — so rendering
   defers while any stateful detail-panel control has focus, and resumes when
   it blurs. The blur-triggered render runs on a macrotask so a click that
   caused the blur lands on the element it was aimed at first. */
let pendingRender = false;

function isStatefulControlFocused() {
  const active = document.activeElement;
  if (!active) return false;
  const holdsInputState = active.tagName === "SELECT" || active.tagName === "TEXTAREA";
  return holdsInputState && detail.contains(active);
}

function renderUnlessTyping() {
  if (isStatefulControlFocused()) {
    pendingRender = true;
    return;
  }
  render();
}

document.addEventListener("focusout", (event) => {
  const wasStateful = event.target.tagName === "SELECT" || event.target.tagName === "TEXTAREA";
  if (wasStateful && pendingRender) {
    setTimeout(() => {
      if (pendingRender && !isStatefulControlFocused()) {
        pendingRender = false;
        render();
      }
    }, 0);
  }
});

function render() {
  if (!state.project) return;
  renderHeader();
  renderFilters();
  const items = filteredItems();
  renderFeatureRail(items);
  if (state.view === "kanban") renderKanban(items);
  else if (state.view === "focus") renderFocus(items);
  else renderGraph(items);
  renderDetail();
}

/* ---------- deep links ---------- */

/* `#kanban` or `#graph/whiteboard` — a view, optionally scoped to one area.
   This is what `vibetracks track <area>` hands a per-track agent, and what
   makes a board state pasteable into a note or a chat. */
let applyingHash = false;

function applyHash() {
  const raw = (location.hash || "").replace(/^#/, "");
  if (!raw) return false;
  const [rawView, rawArea] = raw.split("/");
  let changed = false;
  const view = decodeURIComponent(rawView || "").toLowerCase();
  if (VIEWS.has(view) && view !== state.view) {
    state.view = view;
    localStorage.setItem("vibetracks.view", view);
    changed = true;
  }
  // A link with no area segment means "this view, unfiltered" — otherwise
  // `#kanban` would silently inherit whatever area was left selected and the
  // link would not describe the board it opens.
  const area = rawArea ? decodeURIComponent(rawArea) : "all";
  if (area !== state.area) {
    state.area = area;
    changed = true;
  }
  return changed;
}

function writeHash() {
  applyingHash = true;
  const suffix = state.area && state.area !== "all" ? `/${encodeURIComponent(state.area)}` : "";
  location.hash = `${state.view}${suffix}`;
  setTimeout(() => { applyingHash = false; }, 0);
}

window.addEventListener("hashchange", () => {
  if (applyingHash) return;
  if (applyHash()) render();
});

/* ---------- events ---------- */

document.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    state.view = viewButton.dataset.view;
    localStorage.setItem("vibetracks.view", state.view);
    writeHash();
    render();
    return;
  }
  const pulseButton = event.target.closest("[data-pulse]");
  if (pulseButton) {
    const action = pulseButton.dataset.pulse;
    if (action === "seen") markBoardSeen();
    else if (action === "fresh") { state.freshOnly = !state.freshOnly; render(); }
    else if (action === "stale") {
      const first = state.project.items.find((item) => staleRunningMinutes(item));
      if (first) { state.selectedId = first.id; state.detailOpen = true; render(); }
    }
    return;
  }
  const removeButton = event.target.closest("[data-remove-dependency]");
  if (removeButton) {
    removeDependency(removeButton.dataset.removeDependency);
    return;
  }
  const featureButton = event.target.closest("[data-feature]");
  if (featureButton) {
    state.selectedId = featureButton.dataset.feature;
    state.detailOpen = true;
    render();
    return;
  }
  const areaButton = event.target.closest("[data-area]");
  if (areaButton) {
    state.area = areaButton.dataset.area;
    writeHash();
    render();
    return;
  }
  const outcomeButton = event.target.closest("[data-outcome]");
  if (outcomeButton) {
    changeStatus(outcomeButton.dataset.outcome);
    return;
  }
  if (event.target.closest("#apply-status")) {
    changeStatus($("#status-select").value);
    return;
  }
  if (event.target.closest("#send-feedback")) {
    sendFeedback();
    return;
  }
  if (event.target.closest("#close-detail")) {
    state.detailOpen = false;
    renderDetail();
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id === "add-dependency" && event.target.value) {
    addDependency(event.target.value);
  }
});

document.addEventListener("input", (event) => {
  if (event.target.id === "feedback-text" && state.selectedId) {
    state.feedbackDrafts[state.selectedId] = event.target.value;
  }
});

$("#search").addEventListener("input", (event) => {
  state.query = event.target.value;
  render();
});

$("#show-archived").addEventListener("change", (event) => {
  state.showArchived = event.target.checked;
  render();
});

/* ---------- boot: full load once, then cheap 3 s polling ---------- */

applyHash();
loadProject(true);
setInterval(() => loadProject(false), 3000);
/* Ages are the whole point of the pulse, so it re-renders on its own clock
   rather than waiting for a file to change. Only the pulse repaints — a full
   re-render on a timer would fight the graph's scroll position. */
setInterval(renderPulse, 20000);
