// Vibe Tracks hub app: three hash routes (#/ tracks, #/track/<id>, #/machines) over /api/state and /api/track/<id>,
// kept live by Server-Sent Events (/api/events) with a 10 s poll as the fallback. Plain DOM, no build step.
// Refresh (the header button, or the r key) POSTs /api/refresh: the hub checks the share and rebuilds now.
// Truthful rendering: titles and labels go in as textContent, never trimmed; an ellipsis is CSS only, with the full
// text in the title attribute.
"use strict";

const view = document.getElementById("view");
const liveBadge = document.getElementById("live");
const refreshButton = document.getElementById("refresh");
const checkedLine = document.getElementById("checked");
const POLL_MS = 10000;
let checking = false;
let refreshFailed = null;

let state = null;
let detail = null;
let lastSignatures = new Map();
let pollTimer = null;
let source = null;

// ------------------------------------------------------------------------------------------------ helpers

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clipped(tag, cls, text) {
  // An ellipsis may only be geometry's: the full text stays one hover away.
  const value = text === null || text === undefined ? "" : String(text);
  return el(tag, { class: cls + " clip", title: value, text: value });
}

function parseTime(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

function ago(iso) {
  const t = parseTime(iso);
  if (t === null) return null;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} days ago`;
}

function ageSpan(iso, prefix, fallback) {
  // Ticks client-side once a second (see tickAges); the timestamp is the server's.
  const span = el("span", { "data-ts": iso || "", "data-prefix": prefix || "", title: iso || "" });
  span.textContent = iso ? `${prefix || ""}${ago(iso)}` : (fallback || "");
  return span;
}

function tickAges() {
  for (const span of document.querySelectorAll("[data-ts]")) {
    const iso = span.getAttribute("data-ts");
    if (iso) span.textContent = `${span.getAttribute("data-prefix") || ""}${ago(iso)}`;
  }
}

function formatValue(value, unit) {
  if (value === null || value === undefined) return el("span", { class: "value faint", text: "—" });
  return el("span", { class: "value" }, String(value), unit ? el("span", { class: "unit", text: unit }) : null);
}

function sparkline(values) {
  const nums = (values || []).filter((v) => typeof v === "number" && Number.isFinite(v));
  if (nums.length < 2) return null;
  const ns = "http://www.w3.org/2000/svg";
  const w = 64, h = 20, pad = 2;
  const min = Math.min(...nums), max = Math.max(...nums);
  const span = max - min || 1;
  const points = nums.map((v, i) => {
    const x = pad + (i * (w - 2 * pad)) / (nums.length - 1);
    const y = max === min ? h / 2 : h - pad - ((v - min) * (h - 2 * pad)) / span;
    return [x, y];
  });
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "spark");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("aria-hidden", "true");
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "));
  svg.append(line);
  const [lx, ly] = points[points.length - 1];
  const dot = document.createElementNS(ns, "circle");
  dot.setAttribute("cx", lx.toFixed(1));
  dot.setAttribute("cy", ly.toFixed(1));
  dot.setAttribute("r", "1.8");
  svg.append(dot);
  return svg;
}

function hostStatus(name) {
  const host = (state && state.hosts || []).find((h) => h.host === name);
  return host ? host.status : null;
}

function hostList(hosts) {
  const out = [];
  (hosts || []).forEach((name, i) => {
    if (i) out.push(", ");
    const offline = hostStatus(name) === "offline";
    out.push(el("span", { class: offline ? "exception" : null, title: offline ? `${name} is offline` : null },
      offline ? `${name} (offline)` : name));
  });
  return out;
}

function exceptions(track) {
  const chips = [];
  const fresh = track.freshness || {};
  if (fresh.stale === true || (track.state && track.state.tone === "stale")) {
    chips.push(el("span", { class: "chip", title: fresh.note || "", text: "stalled" }));
  }
  const needs = track.needs_you_count || {};
  if (typeof needs.open === "number" && needs.open > 0) {
    const blocking = typeof needs.blocking === "number" && needs.blocking > 0 ? ` · ${needs.blocking} blocking` : "";
    chips.push(el("span", { class: "chip", text: `needs you · ${needs.open} open${blocking}` }));
  }
  return chips;
}

function signature(track) {
  const copy = JSON.parse(JSON.stringify(track));
  if (copy.freshness) delete copy.freshness.age_h;
  return JSON.stringify(copy);
}

// ------------------------------------------------------------------------------------------------ views

function renderHome() {
  const tracks = state.tracks || [];
  const hosts = state.hosts || [];
  // WHY the hub counts: it runs the tracks whose files live on it (here, most of them), so "1 of 2 machines online"
  // read as if most of the work were down. The hub is online by definition while this page answers.
  const hubName = (state.hub || {}).host_name;
  const hubListed = hosts.some((h) => h.host === hubName);
  const total = hosts.length + (hubName && !hubListed ? 1 : 0);
  const online = hosts.filter((h) => h.status === "online").length + (hubName && !hubListed ? 1 : 0);
  const needing = tracks.filter((t) => t.needs_you_count && typeof t.needs_you_count.open === "number"
    && t.needs_you_count.open > 0).length;
  const parts = [`${tracks.length} ${tracks.length === 1 ? "track" : "tracks"}`];
  parts.push(`${online} of ${total} ${total === 1 ? "machine" : "machines"} online`);
  if (needing) parts.push(`${needing} ${needing === 1 ? "needs" : "need"} you`);
  const status = el("p", { class: "status", text: parts.join(" · ") });
  const agentsLive = liveAgents();
  if (agentsLive) {
    status.append(" · ", el("a", { href: "#/machines", text: `${agentsLive} ${agentsLive === 1 ? "agent" : "agents"} live` }));
  }
  const out = [status];
  out.push(...hubAlerts());

  if (!tracks.length) {
    out.push(el("p", { class: "empty", text: state.hub && state.hub.build_error ? "No projection yet." : "Building the first projection…" }));
    return out;
  }
  const list = el("div", { class: "rows" });
  const next = new Map();
  for (const track of tracks) {
    const sig = signature(track);
    next.set(track.id, sig);
    const head = track.headline;
    const side = el("div", { class: "row-side" });
    if (head) {
      side.append(el("div", {}, formatValue(head.latest, head.unit),
        el("span", { class: "value-label clip", title: head.label, text: head.label })));
      const spark = sparkline(head.values);
      if (spark) side.append(spark);
    }
    const fresh = track.freshness || {};
    const meta = el("div", { class: "row-meta" }, "on ", ...hostList(track.hosts), " · ",
      fresh.newest ? ageSpan(fresh.newest, "updated ") : (fresh.note || "liveness unknown"));
    const live = (track.sessions || []).filter((s) => s.live).length;
    if (live) meta.append(` · ${live} ${live === 1 ? "agent" : "agents"} live`);
    // The title and the exception chips get the full row width; the headline sits beside the meta line.
    const row = el("a", { class: "row", href: `#/track/${encodeURIComponent(track.id)}` },
      clipped("span", "row-title row-span", track.title),
      el("div", { class: "row-main" }, meta),
      side);
    const chips = exceptions(track);
    if (chips.length) row.append(el("div", { class: "row-span" }, ...chips));
    if (lastSignatures.has(track.id) && lastSignatures.get(track.id) !== sig) row.classList.add("flash");
    list.append(row);
  }
  lastSignatures = next;
  out.push(list);
  return out;
}

function liveAgents() {
  // Every session card counts, with or without a track: they come per machine (hosts[].sessions).
  return ((state && state.hosts) || []).reduce((n, h) => n + (h.sessions || []).filter((s) => s.live).length, 0);
}

function hubAlerts() {
  const hub = (state && state.hub) || {};
  const out = [];
  if (hub.pull_error) out.push(el("p", { class: "alert", text: `sync error: ${hub.pull_error}` }));
  if (hub.build_error) out.push(el("p", { class: "alert", text: `build error (showing the last good build): ${hub.build_error}` }));
  return out;
}

function agentCard(card) {
  const who = [card.host, card.account, card.model || "model unknown"].filter(Boolean).join(" · ");
  const seen = card.ended ? "ended " : "last seen ";
  const node = el("div", { class: "agent" },
    el("div", { class: "agent-title", text: who }),
    el("div", { class: "agent-line" }, card.live ? "live · " : "", ageSpan(card.last_seen, seen, "never seen"),
      card.cwd ? el("span", { title: card.cwd }, ` · ${card.cwd}`) : null));
  if (card.url && card.demo) {
    node.append(el("span", { class: "demo-link", title: card.url, text: "demo link · not a real session" }));
  } else if (card.url) {
    node.append(el("a", { class: "talk", href: card.url, target: "_blank", rel: "noopener noreferrer" }, "Talk to agent ↗"));
  } else {
    node.append(el("div", { class: "agent-line faint", text: "no Remote Control link" }));
  }
  return node;
}

function renderTrack(track) {
  const out = [el("a", { class: "back", href: "#/", text: "← All tracks" })];
  out.push(el("h1", { text: track.title }));
  const fresh = track.freshness || {};
  out.push(el("div", { class: "row-meta" }, "on ", ...hostList(track.hosts), " · ",
    fresh.newest ? ageSpan(fresh.newest, "updated ") : (fresh.note || "liveness unknown")));
  const stateLine = track.state ? [track.state.word, track.state.detail].filter(Boolean).join(" · ") : "";
  if (stateLine) out.push(el("div", { class: "row-meta" + (["warn", "risk", "stale"].includes(track.state.tone) ? " exception" : ""), text: stateLine }));
  out.push(el("div", {}, ...exceptions(track)));
  out.push(...hubAlerts());
  if (track.summary) out.push(el("p", { class: "summary", text: track.summary }));

  out.push(el("h2", { text: "KPIs" }));
  if (!(track.kpis || []).length) out.push(el("p", { class: "empty", text: "This track reports no KPIs." }));
  for (const kpi of track.kpis || []) {
    const sub = [];
    if (kpi.status && kpi.status.word) sub.push(kpi.status.word);
    if (kpi.target && kpi.target.label) sub.push(`target: ${kpi.target.label}`);
    const side = el("div", { class: "row-side" }, formatValue(kpi.latest, kpi.unit));
    const spark = sparkline(kpi.values);
    if (spark) side.prepend(spark);
    out.push(el("div", { class: "kpi" },
      el("div", { class: "row-main" }, el("div", { text: kpi.label }),
        sub.length ? el("div", { class: "kpi-sub" + (kpi.status && ["warn", "risk", "stale"].includes(kpi.status.tone) ? " exception" : ""), text: sub.join(" · ") }) : null),
      side));
  }

  out.push(el("h2", { text: "Agents on this track" }));
  const cards = track.sessions || [];
  const live = cards.filter((c) => c.live);
  const earlier = cards.filter((c) => !c.live).slice(0, 5);
  if (!cards.length) out.push(el("p", { class: "empty", text: "No session has reported for this track." }));
  live.forEach((c) => out.push(agentCard(c)));
  if (earlier.length) {
    if (live.length) out.push(el("div", { class: "agent-line faint", style: null, text: "Earlier" }));
    earlier.forEach((c) => out.push(agentCard(c)));
  }

  out.push(el("h2", { text: "Where the data comes from" }));
  const sources = fresh.sources || [];
  if (!sources.length) out.push(el("p", { class: "empty", text: "No sources declared." }));
  for (const src of sources) {
    out.push(el("div", { class: "source" },
      el("div", {}, el("span", { text: src.key }), el("span", { class: "muted" }, ` · ${src.host || "?"} · `,
        src.modified ? ageSpan(src.modified, "changed ") : (src.note || "missing"))),
      src.path ? clipped("div", "source-path", src.path) : null));
  }
  out.push(el("a", { class: "back", href: "#/", text: "← All tracks" }));
  return out;
}

function renderMachines() {
  const hub = state.hub || {};
  const out = [el("p", { class: "status" }, `${hub.host_name || "this machine"} is the hub`,
    hub.share_head ? ` · share at ${hub.share_head}` : "", hub.last_pull ? " · pulled " : "",
    hub.last_pull ? ageSpan(hub.last_pull, "") : "")];
  out.push(...hubAlerts());
  const hosts = state.hosts || [];
  if (!hosts.length) out.push(el("p", { class: "empty", text: "No machine has synced into the share yet." }));
  for (const host of hosts) {
    const bad = host.status === "offline" || !!host.error;
    const main = el("div", { class: "machine-main" },
      el("div", { class: "row-title" }, host.host,
        el("span", { class: "muted small" + (host.status === "offline" ? " exception" : "") }, ` · ${host.status}`)),
      el("div", { class: "row-meta" }, host.last_sync ? ageSpan(host.last_sync, "synced ") : "never synced",
        ` · ${host.sessions_live} ${host.sessions_live === 1 ? "session" : "sessions"} live · ${host.files} ${host.files === 1 ? "file" : "files"} mirrored`),
      host.platform ? clipped("div", "row-meta faint", host.platform) : null);
    for (const skip of host.skipped || []) {
      main.append(el("div", { class: "row-meta", title: skip.path || "", text: `skipped ${skip.key}: ${skip.reason}` }));
    }
    if (host.error) main.append(el("div", { class: "alert", text: `error: ${host.error}` }));
    const agents = machineAgents(host);
    if (agents.length) main.append(el("div", { class: "m-agents" }, ...agents));
    out.push(el("div", { class: "machine" }, el("span", { class: "dot" + (bad ? " bad" : ""), title: host.status }), main));
  }
  return out;
}

function machineAgents(host) {
  // Live first, then up to 5 recent others under a faint "Earlier" (the hub sends live + at most 10 others).
  const cards = host.sessions || [];
  const live = cards.filter((c) => c.live);
  const earlier = cards.filter((c) => !c.live).slice(0, 5);
  const out = live.map((c) => machineAgent(c, true));
  if (earlier.length) {
    out.push(el("div", { class: "earlier", text: "Earlier" }));
    earlier.forEach((c) => out.push(machineAgent(c, false)));
  }
  return out;
}

function machineAgent(card, live) {
  // One line: project · track (if any) · model · account · last seen; then how to reach it.
  const what = [card.project || "no folder", card.track, card.model || "model unknown", card.account].filter(Boolean);
  const seen = card.ended ? "ended " : live ? "seen " : "last seen ";
  const node = el("div", { class: "m-agent" + (live ? "" : " m-agent-earlier") },
    el("div", { class: "m-agent-line", title: card.cwd || "" }, what.join(" · "), " · ",
      el("span", { class: "muted" }, ageSpan(card.last_seen, seen, "never seen"))));
  if (card.url && card.demo) {
    node.append(el("span", { class: "demo-link", title: card.url, text: "demo link" }));
  } else if (card.url && live) {
    node.append(el("a", { class: "talk", href: card.url, target: "_blank", rel: "noopener noreferrer" }, "Talk to agent ↗"));
  } else if (card.url && !card.ended) {
    // WHY still offered: a session idle for 30 min is not "live" but its Remote Control link may well still answer.
    node.append(el("a", { class: "talk-quiet", href: card.url, target: "_blank", rel: "noopener noreferrer" }, "Talk to agent ↗"));
  } else if (!card.url && live) {
    node.append(el("div", { class: "agent-line faint", text: "no Remote Control link" }));
  }
  return node;
}

// ------------------------------------------------------------------------------------------------ routing + data

function route() {
  const hash = location.hash || "#/";
  const match = hash.match(/^#\/track\/(.+)$/);
  if (match) return { name: "track", id: decodeURIComponent(match[1]) };
  if (hash === "#/machines") return { name: "machines" };
  return { name: "home" };
}

function paintChecked() {
  if (refreshFailed) {
    checkedLine.replaceChildren(el("span", { class: "exception", title: refreshFailed, text: "refresh failed" }));
    return;
  }
  const iso = state && state.hub && state.hub.last_check;
  checkedLine.replaceChildren(iso ? ageSpan(iso, "checked ") : "");
}

function paint() {
  paintChecked();
  const r = route();
  for (const tab of document.querySelectorAll("[data-tab]")) {
    const current = (r.name === "machines") === (tab.dataset.tab === "machines");
    if (current) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  if (!state) return;
  let nodes;
  if (r.name === "machines") nodes = renderMachines();
  else if (r.name === "track") {
    nodes = detail && detail.id === r.id ? renderTrack(detail)
      : [el("a", { class: "back", href: "#/", text: "← All tracks" }), el("p", { class: "empty", text: detail === false ? `No track “${r.id}”.` : "Loading…" })];
  } else nodes = renderHome();
  view.replaceChildren(...nodes);
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    const error = new Error(`${url}: HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

let refreshing = null;
async function refresh() {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      state = await getJSON("/api/state");
      const r = route();
      if (r.name === "track") {
        try {
          detail = (await getJSON(`/api/track/${encodeURIComponent(r.id)}`)).track;
        } catch (error) {
          detail = error.status === 404 ? false : detail;
        }
      }
      paint();
    } catch (error) {
      setLive("reconnecting");
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function refreshNow() {
  // The hub answers when its check (and rebuild) is done; a second press while one runs is ignored here and joined
  // on the server.
  if (checking) return;
  checking = true;
  refreshButton.disabled = true;
  refreshButton.querySelector(".refresh-label").textContent = "Checking…";
  try {
    const response = await fetch("/api/refresh", {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const reply = await response.json().catch(() => ({}));
    refreshFailed = response.ok ? null : (reply.error || `HTTP ${response.status}`);
  } catch (error) {
    refreshFailed = "the hub did not answer";
  } finally {
    checking = false;
    refreshButton.disabled = false;
    refreshButton.querySelector(".refresh-label").textContent = "Refresh";
  }
  await refresh();
  paintChecked();
}

function setLive(mode) {
  liveBadge.dataset.state = mode;
  liveBadge.textContent = mode === "live" ? "live" : mode === "reconnecting" ? "reconnecting…" : "connecting…";
}

function startPolling() {
  if (!pollTimer) pollTimer = setInterval(refresh, POLL_MS);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

function connect() {
  if (!("EventSource" in window)) {
    startPolling();
    return;
  }
  source = new EventSource("/api/events");
  source.addEventListener("open", () => { setLive("live"); stopPolling(); });
  source.addEventListener("revision", (event) => {
    setLive("live");
    if (!state || event.data !== state.revision) refresh();
  });
  source.addEventListener("check", (event) => {
    // A check that found nothing keeps the revision; only "checked … ago" moves.
    if (state && state.hub) {
      state.hub.last_check = event.data || null;
      refreshFailed = null;
      paintChecked();
    }
  });
  source.addEventListener("error", () => {
    // EventSource retries by itself; the poll keeps the page current meanwhile.
    setLive("reconnecting");
    startPolling();
  });
}

window.addEventListener("hashchange", () => {
  detail = null;
  window.scrollTo(0, 0);
  paint();
  refresh();
});

refreshButton.addEventListener("click", refreshNow);
document.addEventListener("keydown", (event) => {
  if (event.key !== "r" || event.metaKey || event.ctrlKey || event.altKey || event.repeat) return;
  const target = event.target;
  if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
  event.preventDefault();
  refreshNow();
});

setInterval(tickAges, 1000);
refresh();
connect();
