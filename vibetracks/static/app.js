const state = {
  project: null,
  view: localStorage.getItem("vibetracks.view") || "graph",
  selectedId: null,
  query: "",
  area: "all",
  showArchived: false,
  busy: false,
};

const $ = (selector) => document.querySelector(selector);
const stage = $("#view-stage");
const detail = $("#detail-panel");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

function titleCase(value) {
  return String(value || "").replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function mediaUrl(path) {
  return `/api/media?path=${encodeURIComponent(path)}`;
}

function statusIcon(status) {
  return ({ done: "✓", running: "↻", review: "!", frontier: "?", ready: "→", waiting: "⏸", archived: "○", backlog: "·" })[status] || "·";
}

function priorityRank(value) {
  return ({ urgent: 0, high: 1, medium: 2, low: 3, none: 4 })[value] ?? 4;
}

function itemById(id) {
  return state.project?.items.find((item) => item.id === id) || null;
}

function filteredItems() {
  if (!state.project) return [];
  const query = state.query.trim().toLowerCase();
  return state.project.items.filter((item) => {
    if (!state.showArchived && item.archived) return false;
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
  showToast.timer = setTimeout(() => { toast.className = "toast"; }, 2600);
}

function setSync(message, error = false) {
  $("#sync-label").textContent = message;
  $(".sync-state").classList.toggle("error", error);
}

async function loadProject(force = false) {
  try {
    const response = await fetch("/api/project", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    if (!force && state.project?.revision === payload.revision) {
      setSync("Files current");
      return;
    }
    state.project = payload;
    if (!state.selectedId || !itemById(state.selectedId)) {
      state.selectedId = payload.items.find((item) => item.status === "review")?.id || payload.items[0]?.id || null;
    }
    render();
    setSync("Files current");
  } catch (error) {
    setSync("Read failed", true);
    if (!state.project) stage.innerHTML = `<div class="empty"><div><b>Could not load this track.</b><p>${esc(error.message)}</p></div></div>`;
  }
}

function renderHeader() {
  const project = state.project;
  $("#descriptor-label").textContent = project.descriptor;
  $("#project-title").textContent = project.title;
  $("#project-description").textContent = project.description;
  const active = project.items.filter((item) => !item.archived);
  const review = active.filter((item) => ["review", "frontier"].includes(item.status));
  const running = active.filter((item) => item.status === "running");
  $("#project-metrics").innerHTML = [
    [active.length, "active"], [running.length, "running"], [review.length, "need you"]
  ].map(([value, label]) => `<div class="metric"><b>${value}</b><span>${label}</span></div>`).join("");
  document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === state.view));
}

function renderFilters() {
  const areas = [...new Set(state.project.items.flatMap((item) => item.areas))].sort();
  $("#area-filters").innerHTML = ["all", ...areas].map((area) => `<button class="area-chip${state.area === area ? " active" : ""}" data-area="${esc(area)}">${area === "all" ? "All areas" : esc(area)}</button>`).join("");
  $("#show-archived").checked = state.showArchived;
}

function renderFeatureRail(items) {
  $("#visible-count").textContent = items.length;
  $("#feature-list").innerHTML = items.length ? items.map((item) => `
    <button class="feature-row${item.id === state.selectedId ? " selected" : ""}" data-feature="${esc(item.id)}">
      <span class="dot ${esc(item.status)}"></span><span><b>${esc(item.title)}</b><small>${esc(item.id)} · ${esc(titleCase(item.status))}</small></span>
    </button>`).join("") : `<div class="empty"><div><b>No matching features.</b><p>Change the area or search filter.</p></div></div>`;
}

function viewHeading(title, description) {
  return `<div class="view-heading"><div><h2>${esc(title)}</h2><p>${esc(description)}</p></div><div class="view-key"><span style="color:var(--blue)">running</span><span style="color:var(--amber)">review</span><span style="color:var(--green)">done</span></div></div>`;
}

function cardMarkup(item, className, extra = "") {
  return `<button class="${className}${item.id === state.selectedId ? " selected" : ""}" data-feature="${esc(item.id)}">
    <span class="status-line ${esc(item.status)}">${statusIcon(item.status)} ${esc(titleCase(item.status))}</span>
    <b>${esc(item.id)} · ${esc(item.title)}</b>
    <small>${esc(item.description || "No summary yet.")}</small>${extra}
  </button>`;
}

function graphLayout(items) {
  const visible = new Set(items.map((item) => item.id));
  const byId = new Map(items.map((item) => [item.id, item]));
  const memo = new Map();
  function layer(id, stack = new Set()) {
    if (memo.has(id)) return memo.get(id);
    if (stack.has(id)) return 0;
    stack.add(id);
    const dependencies = (byId.get(id)?.dependencies || []).filter((dependency) => visible.has(dependency));
    const value = dependencies.length ? Math.max(...dependencies.map((dependency) => layer(dependency, new Set(stack)))) + 1 : 0;
    memo.set(id, value);
    return value;
  }
  const groups = new Map();
  for (const item of items) {
    const depth = layer(item.id);
    if (!groups.has(depth)) groups.set(depth, []);
    groups.get(depth).push(item);
  }
  const positions = new Map();
  let maxRows = 1;
  for (const [depth, group] of groups) {
    group.sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority) || a.title.localeCompare(b.title));
    maxRows = Math.max(maxRows, group.length);
    group.forEach((item, index) => positions.set(item.id, { x: 35 + depth * 235, y: 45 + index * 132 }));
  }
  return { positions, width: Math.max(680, (Math.max(0, ...groups.keys()) + 1) * 235 + 30), height: Math.max(600, maxRows * 132 + 50) };
}

function renderGraph(items) {
  const { positions, width, height } = graphLayout(items);
  const visible = new Set(items.map((item) => item.id));
  const edges = items.flatMap((item) => item.dependencies.filter((dependency) => visible.has(dependency)).map((dependency) => {
    const from = positions.get(dependency), to = positions.get(item.id);
    const d = `M${from.x + 184} ${from.y + 49} C${from.x + 210} ${from.y + 49},${to.x - 26} ${to.y + 49},${to.x} ${to.y + 49}`;
    const critical = ["review", "waiting"].includes(item.status) ? " critical" : "";
    return `<path class="${critical}" d="${d}" marker-end="url(#arrow)"/>`;
  })).join("");
  const nodes = items.map((item) => {
    const position = positions.get(item.id);
    const hidden = item.dependencies.filter((dependency) => !visible.has(dependency)).length + item.unresolved_dependencies.length;
    const chips = item.areas.slice(0, 2).map((area) => `<span class="mini-chip">${esc(area)}</span>`).join("");
    return `<button class="graph-node${item.id === state.selectedId ? " selected" : ""}" data-feature="${esc(item.id)}" style="left:${position.x}px;top:${position.y}px">
      <span class="status-line ${esc(item.status)}">${statusIcon(item.status)} ${esc(titleCase(item.status))}</span><b>${esc(item.id)} · ${esc(item.title)}</b><small>${esc(item.description || "No summary yet.")}</small><span class="node-areas">${chips}</span>${hidden ? `<span class="hidden-edge">+ ${hidden} hidden prerequisite${hidden === 1 ? "" : "s"}</span>` : ""}</button>`;
  }).join("");
  stage.innerHTML = `${viewHeading("Dependency graph", "Causal topology. Filters collapse hidden prerequisites into visible boundary cues.")}<div class="graph-scroll"><div class="graph-canvas" style="width:${width}px;height:${height}px"><svg class="graph-edges" viewBox="0 0 ${width} ${height}" aria-hidden="true"><defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path class="arrowhead" d="M0 0L10 5L0 10Z"/></marker></defs>${edges}</svg>${nodes}</div></div>`;
}

function renderKanban(items) {
  const statuses = state.project.statuses.filter((status) => state.showArchived || status !== "archived");
  stage.innerHTML = `${viewHeading("Kanban", "A fast state sweep over the same feature identities and files.")}<div class="kanban">${statuses.map((status) => {
    const group = items.filter((item) => item.status === status);
    return `<section class="kanban-column"><div class="column-head"><span>${esc(titleCase(status))}</span><span>${group.length}</span></div>${group.map((item) => cardMarkup(item, "ticket")).join("") || `<small>Empty</small>`}</section>`;
  }).join("")}</div>`;
}

function renderFocus(items) {
  const needsYou = items.filter((item) => ["review", "frontier"].includes(item.status)).sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority));
  const next = items.filter((item) => item.status === "ready").sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority));
  const quiet = items.filter((item) => ["running", "waiting"].includes(item.status));
  stage.innerHTML = `${viewHeading("Focus", "The attention frontier: reviews first, then work that is ready to dispatch.")}<div class="focus-grid"><section class="focus-lane"><h3>NEEDS YOU · ${needsYou.length}</h3><p>Review and frontier items, sorted by priority.</p>${needsYou.map((item, index) => cardMarkup(item, `focus-card${index === 0 ? " primary" : ""}`, `<em>${item.status === "review" ? `${item.dependents.length} downstream feature${item.dependents.length === 1 ? "" : "s"}` : "Decision can remain deferred"}</em>`)).join("") || `<div class="empty"><div><b>Nothing needs you.</b><p>The dispatcher can keep moving.</p></div></div>`}<h3>NEXT TO DISPATCH · ${next.length}</h3>${next.map((item) => cardMarkup(item, "focus-card")).join("")}</section><section class="focus-lane quiet"><h3>WORKING QUIETLY · ${quiet.length}</h3><p>Healthy running and waiting work stays compressed.</p>${quiet.map((item) => cardMarkup(item, "focus-card")).join("")}</section></div>`;
}

function inlineMarkdown(value) {
  return esc(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_match, target, alias) =>
      `<span class="wikilink">${alias || target}</span>`
    );
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  let html = "", list = false, fence = false;
  for (const raw of lines) {
    if (raw.trim().startsWith("```")) {
      html += fence ? "</code></pre>" : "<pre><code>";
      fence = !fence;
      continue;
    }
    if (fence) { html += `${esc(raw)}\n`; continue; }
    if (/^!\[\[/.test(raw.trim()) || /^!\[[^\]]*\]\(/.test(raw.trim())) continue;
    const heading = raw.match(/^(#{1,3})\s+(.+)$/);
    if (heading) { if (list) { html += "</ul>"; list = false; } const level = heading[1].length; html += `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`; continue; }
    const item = raw.match(/^\s*[-*]\s+(.+)$/);
    if (item) { if (!list) { html += "<ul>"; list = true; } html += `<li>${inlineMarkdown(item[1])}</li>`; continue; }
    if (list) { html += "</ul>"; list = false; }
    if (raw.trim()) html += `<p>${inlineMarkdown(raw.trim())}</p>`;
  }
  if (list) html += "</ul>";
  if (fence) html += "</code></pre>";
  return html;
}

function relationButtons(ids) {
  return ids.length ? ids.map((id) => {
    const item = itemById(id);
    return `<button data-feature="${esc(id)}">${esc(item ? `${item.id} · ${item.title}` : id)}</button>`;
  }).join("") : `<span class="detail-meta">None</span>`;
}

function renderDetail() {
  const item = itemById(state.selectedId);
  if (!item) {
    detail.innerHTML = `<div class="empty"><div><b>Select a feature.</b><p>Its durable context, relations, and review packet open here.</p></div></div>`;
    detail.classList.remove("open");
    return;
  }
  const mediaPaths = [...new Set([item.preview, ...item.media.map((media) => media.path)].filter(Boolean))];
  const openLink = item.obsidian_uri
    ? `<a href="${esc(item.obsidian_uri)}">Open in Obsidian ↗</a>`
    : `<a href="${mediaUrl(item.path)}" target="_blank">Open raw Markdown ↗</a>`;
  const review = item.review_packet ? `<section class="detail-section"><h3>Review packet</h3><iframe class="review-frame" sandbox="" src="${mediaUrl(item.review_packet)}" title="Review packet for ${esc(item.title)}"></iframe><div class="detail-actions"><a href="${mediaUrl(item.review_packet)}" target="_blank">Open full report ↗</a></div></section>` : "";
  detail.innerHTML = `<div class="detail-inner"><div class="detail-kicker">Feature conversation · ${esc(item.id)}</div><div class="detail-title-row"><h2>${esc(item.title)}</h2><span class="status-badge">${statusIcon(item.status)} ${esc(titleCase(item.status))}</span></div><p class="detail-description">${esc(item.description || "No summary yet.")}</p><div class="detail-actions">${openLink}<button class="button" id="close-detail">Close</button></div><div class="status-editor"><select id="status-select">${state.project.statuses.map((status) => `<option value="${esc(status)}"${status === item.status ? " selected" : ""}>${esc(titleCase(status))}</option>`).join("")}</select><button class="button primary" id="apply-status">Apply state</button></div>${item.status === "review" ? `<div class="review-actions"><button data-outcome="done">Approve → Done</button><button data-outcome="ready">Changes → Ready</button><button data-outcome="frontier">Question → Frontier</button></div>` : ""}<section class="detail-section"><h3>Areas</h3><div class="relation-list">${item.areas.map((area) => `<button data-area="${esc(area)}">${esc(area)}</button>`).join("") || `<span class="detail-meta">Unclassified</span>`}</div></section><section class="detail-section"><h3>Dependencies</h3><div class="relation-list">${relationButtons(item.dependencies)}</div>${item.unresolved_dependencies.length ? `<p class="detail-meta">Unresolved: ${esc(item.unresolved_dependencies.join(", "))}</p>` : ""}</section><section class="detail-section"><h3>Downstream</h3><div class="relation-list">${relationButtons(item.dependents)}</div></section>${mediaPaths.length ? `<section class="detail-section"><h3>Media</h3><div class="media-grid">${mediaPaths.map((path) => `<a href="${mediaUrl(path)}" target="_blank"><img src="${mediaUrl(path)}" alt="${esc(item.title)} evidence" /></a>`).join("")}</div></section>` : ""}${review}${item.evidence.length ? `<section class="detail-section"><h3>Evidence</h3>${item.evidence.map((path) => `<a class="evidence-link" href="${mediaUrl(path)}" target="_blank">${esc(path)} ↗</a>`).join("")}</section>` : ""}<section class="detail-section"><h3>Feature context</h3><div class="markdown">${renderMarkdown(item.body)}</div></section>${item.runs.length ? `<section class="detail-section"><h3>Worker runs</h3>${item.runs.map((run) => `<div class="evidence-link">${esc(run)}</div>`).join("")}</section>` : ""}<p class="detail-meta">${esc(item.path)}<br/>revision ${esc(item.revision)} · updated ${esc(item.updated)}</p></div>`;
  detail.classList.add("open");
}

async function changeStatus(status) {
  const item = itemById(state.selectedId);
  if (!item || state.busy || status === item.status) return;
  state.busy = true;
  try {
    const response = await fetch(`/api/features/${encodeURIComponent(item.id)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, expectedRevision: item.revision }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    showToast(`${item.id} moved to ${titleCase(status)}. Markdown updated.`);
    await loadProject(true);
  } catch (error) {
    showToast(error.message, true);
    await loadProject(true);
  } finally {
    state.busy = false;
  }
}

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

document.addEventListener("click", (event) => {
  const view = event.target.closest("[data-view]");
  if (view) { state.view = view.dataset.view; localStorage.setItem("vibetracks.view", state.view); render(); return; }
  const feature = event.target.closest("[data-feature]");
  if (feature) { state.selectedId = feature.dataset.feature; render(); return; }
  const area = event.target.closest("[data-area]");
  if (area) { state.area = area.dataset.area; render(); return; }
  const outcome = event.target.closest("[data-outcome]");
  if (outcome) { changeStatus(outcome.dataset.outcome); return; }
  if (event.target.closest("#apply-status")) { changeStatus($("#status-select").value); return; }
  if (event.target.closest("#close-detail")) { detail.classList.remove("open"); }
});

$("#search").addEventListener("input", (event) => { state.query = event.target.value; render(); });
$("#show-archived").addEventListener("change", (event) => { state.showArchived = event.target.checked; render(); });

loadProject(true);
setInterval(() => loadProject(false), 3000);
