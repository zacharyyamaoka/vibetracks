import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const docsDir = dirname(fileURLToPath(import.meta.url));
const specPath = join(docsDir, "track-layout-prototypes-2026-08-25.json");

const commonStyles = String.raw`<style>
  .tl-proto{--paper:#f8f6ef;--card:#fffefa;--ink:#211f1a;--muted:#777064;--line:#cfc9bc;--hair:#e7e2d7;--accent:#3d6b62;--blue:#5b7285;--ochre:#9a713d;--rose:#8c625f;min-height:390px;padding:12px;border:1px solid var(--hair);background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
  .tl-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:2px 2px 10px;border-bottom:1px solid var(--hair)}
  .tl-head b{font:600 14px Georgia,serif}.tl-head span,.tl-foot{color:var(--muted);font-size:10px}.tl-stage{margin-top:10px;overflow-x:auto}.tl-stage svg{display:block;width:100%;min-width:680px;height:auto}
  .tl-edge{fill:none;stroke:var(--line);stroke-width:1.4}.tl-edge.faint{stroke:var(--hair)}.tl-edge.strong{stroke:var(--accent);stroke-width:2.2}.tl-arrow{fill:var(--line)}
  .tl-node rect{fill:var(--card);stroke:var(--line);rx:4}.tl-node text{fill:var(--ink);font-size:10px}.tl-node .sub{fill:var(--muted);font-size:8px}.tl-node.selected rect{stroke:var(--accent);stroke-width:2}.tl-node.ghost{opacity:.25}.tl-node.ambiguous rect{stroke:var(--rose);stroke-dasharray:4 3}
  .tl-dot{r:3}.tl-done{fill:var(--accent)}.tl-running{fill:var(--blue)}.tl-ready{fill:var(--ochre)}.tl-waiting{fill:#a9a193}.tl-frontier{fill:var(--rose)}.tl-backlog{fill:#aaa49a}
  .tl-label{fill:var(--muted);font-size:9px;letter-spacing:.08em}.tl-note{fill:var(--muted);font-size:9px;font-style:italic}.tl-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:8px}.tl-foot .demo-button{font-size:10px}
  .tl-corridor{fill:none;stroke:#dfe8e4;stroke-width:14;stroke-linecap:round;stroke-linejoin:round}.tl-corridor.alt{stroke:#cbded8}.tl-segment-label{fill:var(--accent);font-size:8px;font-weight:700;letter-spacing:.06em}
  .tl-route{fill:none;stroke-width:7;stroke-linecap:round;stroke-linejoin:round;opacity:.68}.tl-route.model{stroke:var(--blue)}.tl-route.render{stroke:var(--accent)}.tl-route.agent{stroke:var(--ochre)}.tl-route.dim{opacity:.13}.tl-route.focus{opacity:.92;stroke-width:9}
  .tl-phase{fill:#fffdf8;stroke:var(--hair)}.tl-phase-title{fill:var(--muted);font-size:9px;letter-spacing:.11em}.tl-complete{fill:#eef3f0;stroke:var(--accent)}
  .tl-lane{fill:#fffdf8;stroke:var(--hair)}.tl-lane-title{fill:var(--muted);font-size:9px;letter-spacing:.1em}.tl-cross{fill:none;stroke:var(--rose);stroke-width:1.8;stroke-dasharray:4 3}
  @media(max-width:720px){.tl-proto{min-height:330px;padding:8px}.tl-stage svg{min-width:620px}.tl-head{align-items:flex-start;flex-direction:column;gap:3px}}
</style>`;

const node = (id, label, x, y, status, extra = "") => String.raw`<g class='tl-node ${extra}' transform='translate(${x} ${y})'><rect width='102' height='48'/><circle class='tl-dot tl-${status}' cx='10' cy='12'/><text x='18' y='15'>${id} · ${label}</text><text class='sub' x='10' y='34'>${status}</text></g>`;

const standardNodes = (classes = {}) => [
  node("10", "Intake", 12, 142, "done", classes["10"] || ""),
  node("11", "Frame", 128, 142, "done", classes["11"] || ""),
  node("12", "File model", 248, 34, "running", classes["12"] || ""),
  node("13", "Renderer", 248, 142, "running", classes["13"] || ""),
  node("14", "Dispatcher", 248, 250, "ready", classes["14"] || ""),
  node("15", "Snapshot", 382, 85, "waiting", classes["15"] || ""),
  node("16", "Live loop", 382, 205, "waiting", classes["16"] || ""),
  node("17", "Review", 516, 142, "frontier", classes["17"] || ""),
  node("18", "Obsidian", 652, 72, "backlog", classes["18"] || ""),
  node("19", "Providers", 652, 212, "backlog", classes["19"] || ""),
].join("");

const standardPaths = [
  "M114 166 C120 166 122 166 128 166",
  "M230 166 C238 166 240 58 248 58",
  "M230 166 H248",
  "M230 166 C238 166 240 274 248 274",
  "M350 58 C366 58 366 109 382 109",
  "M350 166 C366 166 366 109 382 109",
  "M350 166 C366 166 366 229 382 229",
  "M350 274 C366 274 366 229 382 229",
  "M484 109 C500 109 500 166 516 166",
  "M484 229 C500 229 500 166 516 166",
  "M618 166 C634 166 636 96 652 96",
  "M618 166 C634 166 636 236 652 236",
];

const edgeMarkup = (className = "tl-edge", paths = standardPaths) => paths.map((path) => `<path class='${className}' d='${path}' marker-end='url(#tl-arrow)'/>`).join("");
const defs = String.raw`<defs><marker id='tl-arrow' viewBox='0 0 10 10' refX='8' refY='5' markerWidth='5' markerHeight='5' orient='auto'><path class='tl-arrow' d='M0 0L10 5L0 10Z'/></marker></defs>`;

const shell = (name, thesis, svg, action, altAction, foot) => `${commonStyles}<div class='tl-proto'><div class='tl-head'><b>${name}</b><span>${thesis}</span></div><div class='tl-stage'>${svg}</div><div class='tl-foot'><span>${foot}</span><button class='demo-button' data-demo-toggle data-base-label='${action}' data-alt-label='${altAction}'>${action}</button></div></div>`;

const corridorsPreview = shell(
  "Confluence Corridors",
  "The DAG stays primary; whitespace and faint ribbons make local strands followable.",
  String.raw`<svg viewBox='0 0 770 330' role='img' aria-label='Soft derived corridors through a dependency graph'>${defs}
    <g>${standardPaths.map((path, index) => `<path class='tl-corridor${index > 7 ? " alt" : ""}' d='${path}'/>`).join("")}</g>
    <g>${edgeMarkup()}</g>${standardNodes()}
    <g class='demo-alt-only'><path class='tl-corridor alt' d='M484 229 C500 229 500 286 516 286'/><path class='tl-edge' d='M484 229 C500 229 500 286 516 286' marker-end='url(#tl-arrow)'/>${node("20", "Docs", 516, 262, "ready", "selected")}<text class='tl-segment-label' x='415' y='296'>NEW LOCAL STRAND</text></g>
    <text class='tl-note' x='14' y='320'>Forks end one corridor; joins begin another. Nothing here is stored as a causal fact.</text>
  </svg>`,
  "Add parallel task",
  "Remove added task",
  "The new branch fits locally; unrelated nodes keep their place."
);

const metroPreview = shell(
  "Area Metro",
  "Existing multi-valued areas become named routes laid over the same edges.",
  String.raw`<svg viewBox='0 0 770 330' role='img' aria-label='Area-colored metro routes through the same dependency graph'>${defs}
    <g class='demo-base-only'>
      <path class='tl-route model' d='M18 156 C122 156 140 58 254 58 C340 58 352 109 388 109 C486 109 494 166 522 166 C610 166 628 96 658 96'/>
      <path class='tl-route render' d='M18 166 H254 C338 166 350 109 388 109 C484 109 496 166 522 166 C610 166 628 96 658 96'/>
      <path class='tl-route agent' d='M18 176 C122 176 140 274 254 274 C340 274 352 229 388 229 C486 229 494 166 522 166 C610 166 628 236 658 236'/>
    </g>
    <g class='demo-alt-only'>
      <path class='tl-route model dim' d='M18 156 C122 156 140 58 254 58 C340 58 352 109 388 109 C486 109 494 166 522 166 C610 166 628 96 658 96'/>
      <path class='tl-route render focus' d='M18 166 H254 C338 166 350 109 388 109 C484 109 496 166 522 166 C610 166 628 96 658 96'/>
      <path class='tl-route agent dim' d='M18 176 C122 176 140 274 254 274 C340 274 352 229 388 229 C486 229 494 166 522 166 C610 166 628 236 658 236'/>
    </g>
    <text class='tl-label' x='12' y='124'>MODEL</text><text class='tl-label' x='72' y='195'>RENDERER</text><text class='tl-label' x='222' y='316'>AGENT</text>
    <g>${edgeMarkup("tl-edge")}</g>${standardNodes()}
    <text class='tl-note' x='512' y='318'>Routes overlap; a task still appears only once.</text>
  </svg>`,
  "Focus renderer route",
  "Show all routes",
  "Strong semantic labels, but multi-area work makes the map busier."
);

const lineagePreview = shell(
  "Lineage Lens",
  "The whole DAG rests quietly; selecting a node reveals one causal storyline.",
  String.raw`<svg viewBox='0 0 770 330' role='img' aria-label='General DAG with a selected causal lineage'>${defs}
    <g class='demo-base-only'>${edgeMarkup("tl-edge")}${standardNodes()}</g>
    <g class='demo-alt-only'>
      ${edgeMarkup("tl-edge faint")}
      <path class='tl-edge strong' d='M114 166 C120 166 122 166 128 166'/><path class='tl-edge strong' d='M230 166 C238 166 240 58 248 58'/><path class='tl-edge strong' d='M230 166 H248'/><path class='tl-edge strong' d='M350 58 C366 58 366 109 382 109'/><path class='tl-edge strong' d='M350 166 C366 166 366 109 382 109'/><path class='tl-edge strong' d='M484 109 C500 109 500 166 516 166'/><path class='tl-edge strong' d='M618 166 C634 166 636 96 652 96'/><path class='tl-edge strong' d='M618 166 C634 166 636 236 652 236'/>
      ${standardNodes({"14":"ghost","16":"ghost","15":"selected"})}
      <text class='tl-segment-label' x='384' y='78'>SELECTED LINEAGE</text>
    </g>
    <text class='tl-note' x='14' y='320'>Ancestors + descendants stay anchored; unrelated parallel work recedes.</text>
  </svg>`,
  "Follow Snapshot",
  "Show whole graph",
  "Best companion mode when the full project is too large to read at once."
);

const chaptersPreview = shell(
  "Chaptered DAG",
  "Drop the track metaphor; use topological phases, junctions, and whitespace.",
  String.raw`<svg viewBox='0 0 770 330' role='img' aria-label='Dependency graph organized into topological chapters'>${defs}
    <rect class='tl-phase' x='6' y='20' width='224' height='284' rx='8'/><rect class='tl-phase' x='238' y='20' width='248' height='284' rx='8'/><rect class='tl-phase' x='494' y='20' width='270' height='284' rx='8'/>
    <text class='tl-phase-title' x='18' y='38'>01 · FRAME</text><text class='tl-phase-title' x='250' y='38'>02 · PARALLEL + INTEGRATE</text><text class='tl-phase-title' x='506' y='38'>03 · REVIEW + RELEASE</text>
    <g class='demo-base-only'>${edgeMarkup("tl-edge")}${standardNodes()}</g>
    <g class='demo-alt-only'>
      <path class='tl-edge' d='M214 166 C230 166 234 58 248 58' marker-end='url(#tl-arrow)'/><path class='tl-edge' d='M214 166 H248' marker-end='url(#tl-arrow)'/><path class='tl-edge' d='M214 166 C230 166 234 274 248 274' marker-end='url(#tl-arrow)'/>${edgeMarkup("tl-edge", standardPaths.slice(4))}
      <g transform='translate(36 138)'><rect class='tl-complete' width='178' height='56' rx='5'/><text x='14' y='23' style='font-size:11px;fill:var(--ink)'>✓ 2 completed</text><text class='tl-note' x='14' y='41'>Intake + Frame</text></g>
      ${[node("12", "File model", 248, 34, "running"),node("13", "Renderer", 248, 142, "running"),node("14", "Dispatcher", 248, 250, "ready"),node("15", "Snapshot", 382, 85, "waiting"),node("16", "Live loop", 382, 205, "waiting"),node("17", "Review", 516, 142, "frontier"),node("18", "Obsidian", 652, 72, "backlog"),node("19", "Providers", 652, 212, "backlog")].join("")}
    </g>
  </svg>`,
  "Collapse completed chapter",
  "Expand completed chapter",
  "Most honest general view; continuity comes from routing rather than named tracks."
);

const laneNode = (id, label, x, y, status, extra = "") => node(id, label, x, y, status, extra);
const swimlanePreview = shell(
  "Hard Swimlanes",
  "Every feature must occupy one persistent named row.",
  String.raw`<svg viewBox='0 0 770 330' role='img' aria-label='Rigid explicit swimlanes with crossing dependencies'>${defs}
    <rect class='tl-lane' x='6' y='22' width='758' height='62'/><rect class='tl-lane' x='6' y='88' width='758' height='62'/><rect class='tl-lane' x='6' y='154' width='758' height='62'/><rect class='tl-lane' x='6' y='220' width='758' height='62'/>
    <text class='tl-lane-title' x='16' y='40'>SHARED</text><text class='tl-lane-title' x='16' y='106'>MODEL</text><text class='tl-lane-title' x='16' y='172'>RENDERER</text><text class='tl-lane-title' x='16' y='238'>AGENT</text>
    <g class='demo-base-only'>
      <path class='tl-edge' d='M114 58H128'/><path class='tl-cross' d='M230 58 C238 58 238 124 248 124'/><path class='tl-cross' d='M230 58 C238 58 238 190 248 190'/><path class='tl-cross' d='M230 58 C238 58 238 256 248 256'/><path class='tl-edge' d='M350 124H382'/><path class='tl-cross' d='M350 190 C366 190 366 124 382 124'/><path class='tl-cross' d='M350 190 C366 190 366 256 382 256'/><path class='tl-edge' d='M350 256H382'/><path class='tl-cross' d='M484 124 C500 124 500 190 516 190'/><path class='tl-cross' d='M484 256 C500 256 500 190 516 190'/><path class='tl-edge' d='M618 190H652'/><path class='tl-cross' d='M618 190 C634 190 634 256 652 256'/>
      ${laneNode("10", "Intake", 12, 34, "done")}${laneNode("11", "Frame", 128, 34, "done")}${laneNode("12", "File model", 248, 100, "running")}${laneNode("15", "Snapshot", 382, 100, "waiting")}${laneNode("13", "Renderer", 248, 166, "running")}${laneNode("17", "Review", 516, 166, "frontier", "ambiguous")}${laneNode("18", "Obsidian", 652, 166, "backlog")}${laneNode("14", "Dispatcher", 248, 232, "ready")}${laneNode("16", "Live loop", 382, 232, "waiting")}${laneNode("19", "Providers", 652, 232, "backlog")}
    </g>
    <g class='demo-alt-only'>
      <path class='tl-edge' d='M114 58H128'/><path class='tl-cross' d='M230 58 C238 58 238 124 248 124'/><path class='tl-cross' d='M230 58 C238 58 238 190 248 190'/><path class='tl-cross' d='M230 58 C238 58 238 256 248 256'/><path class='tl-edge' d='M350 124H382'/><path class='tl-cross' d='M350 190 C366 190 366 124 382 124'/><path class='tl-cross' d='M350 190 C366 190 366 256 382 256'/><path class='tl-edge' d='M350 256H382'/><path class='tl-cross' d='M484 124 C500 124 500 256 516 256'/><path class='tl-edge' d='M484 256H516'/><path class='tl-cross' d='M618 256 C634 256 634 190 652 190'/><path class='tl-edge' d='M618 256H652'/>
      ${laneNode("10", "Intake", 12, 34, "done")}${laneNode("11", "Frame", 128, 34, "done")}${laneNode("12", "File model", 248, 100, "running")}${laneNode("15", "Snapshot", 382, 100, "waiting")}${laneNode("13", "Renderer", 248, 166, "running")}${laneNode("18", "Obsidian", 652, 166, "backlog")}${laneNode("14", "Dispatcher", 248, 232, "ready")}${laneNode("16", "Live loop", 382, 232, "waiting")}${laneNode("17", "Review", 516, 232, "frontier", "ambiguous")}${laneNode("19", "Providers", 652, 232, "backlog")}
    </g>
    <text class='tl-note' x='474' y='312'>The join has no objectively correct exclusive lane.</text>
  </svg>`,
  "Move Review to Agent",
  "Move Review to Renderer",
  "Stable ownership view, but splits and joins turn placement into false semantics."
);

const spec = {
  schemaVersion: 2,
  title: "Five ways to make a work DAG read as tracks",
  kicker: "Vibe Tracks · Babble & Prune · 25 August 2026",
  brief: "Make parallel work individually followable and easy to extend while allowing strands to split, merge into a new strand, and split again—without letting visual grouping replace dependency truth.",
  count: 5,
  defaultId: "v1",
  defaultWhy: "Confluence Corridors is the provisional whole-graph default at 94.8/100: it delivers the track feeling Zach described without adding track entities or hard borders. Lineage Lens is a fragile co-leader at 93.6/100 and should be spliced in as the click-to-focus interaction.",
  decisionHinge: "The recommendation hinges on global continuity versus large-graph focus. Moving 6 weight points from layout stability/editability to density/focus flips the 1.2-point lead from Confluence Corridors to Lineage Lens. The practical splice is a Corridors resting view with Lineage Lens on selection.",
  invariants: [
    "Every direction renders the same ten-feature fork → two joins → review → re-split fixture and the same statuses.",
    "Dependency edges are the only causal truth; proximity, color, area, phase, or lane never creates an edge.",
    "A multi-area feature appears once, and filters must retain compact cues for hidden prerequisites.",
    "Paper-minimal styling, visible state words/symbols, and no production Vibe Tracks mutation in this exploration.",
  ],
  boundary: "These are standalone visual prototypes in the current Vibe Tracks paper vocabulary. Variant switching, demo toggles, pruning, feedback, splice selection, and export are real. File loading, automatic layout, saved hints, graph edits, cycle handling, and integration into the production renderer remain unimplemented and are not claimed as verified.",
  axes: [
    { name: "Mental model", values: ["derived corridors", "semantic metro", "selected storyline", "general phased DAG", "exclusive swimlanes"] },
    { name: "Grouping source", values: ["topology only", "existing areas", "selection", "topological rank", "required lane membership"] },
    { name: "Fork / join behavior", values: ["corridor ends and reforms", "routes overlap", "contextual highlight", "ordinary junction", "cross-lane reassignment"] },
    { name: "Persistence pressure", values: ["none", "none beyond areas", "none", "none", "per-feature lane state"] },
  ],
  requirements: [
    {
      id: "fr1", name: "Path continuity", weight: 32,
      why: "The graph earns the Tracks name only if Zach can visually follow one parallel strand without repeatedly reconstructing it from arrow endpoints.",
      passCondition: "A viewer can trace an upstream-to-downstream route across the shared fork/join fixture in one scan.",
      anchors: { "1": "Routes repeatedly jump rows or disappear into crossings.", "3": "The route is traceable but needs deliberate edge-following.", "5": "Whitespace, routing, or focus makes the route perceptually continuous at a glance." },
    },
    {
      id: "fr2", name: "Truthful forks and joins", weight: 24,
      why: "Tracks may split, merge, and reform; the view must not imply exclusive ownership or relationships absent from vibe-depends-on.",
      passCondition: "Forks and joins are explicit junctions and the downstream strand can begin anew without semantic ambiguity.",
      anchors: { "1": "Visual grouping invents or hides relationships.", "3": "Edges remain correct, but grouping makes a fork or join ambiguous.", "5": "Every split and merge is explicit, readable, and faithful to the DAG." },
    },
    {
      id: "fr3", name: "Low-authoring file-first fit", weight: 18,
      why: "Agents and humans should be able to add notes immediately; layout cannot become a second database that must be maintained.",
      passCondition: "Existing dependencies, areas, and statuses are sufficient; any later hint is sparse and optional.",
      anchors: { "1": "Every feature needs manual exclusive grouping.", "3": "Occasional grouping maintenance is required.", "5": "The view works automatically from current files and writes no inferred grouping back." },
    },
    {
      id: "fr4", name: "Stable and correctable", weight: 16,
      why: "A readable mental map compounds only if filters, refreshes, and one new task do not cause unrelated work to jump around.",
      passCondition: "The fixture stays stable through the demonstrated state change and supports a predictable correction path.",
      anchors: { "1": "Small changes broadly reshuffle the graph or cannot be corrected.", "3": "Mostly stable with some layout churn or limited control.", "5": "Deterministic placement, local change, and optional view-local correction are all clear." },
    },
    {
      id: "fr5", name: "Density and focus", weight: 10,
      why: "Whole-project graphs grow; the view needs a path from ten nodes toward dozens without becoming a wall of ribbons.",
      passCondition: "The same concept can suppress distant context, collapse history, or focus a selected lineage without losing boundary cues.",
      anchors: { "1": "The idea fails beyond the small fixture.", "3": "Works for a few dozen nodes with scrolling or filtering.", "5": "Progressive disclosure and stable focus are built into the mental model." },
    },
  ],
  hardGates: [
    { id: "g1", name: "Dependencies own causality", why: "No visual grouping may create, erase, or reinterpret a dependency edge." },
    { id: "g2", name: "No required second schema", why: "The winning direction must work on today's Markdown notes without required track metadata or a layout database." },
    { id: "g3", name: "Same truthful fixture", why: "All directions must preserve every shared fork, join, node, and status so content choice cannot masquerade as design quality." },
  ],
  variants: [
    {
      id: "v1", name: "Confluence Corridors",
      thesis: "Keep a general layered DAG, but make maximal path segments between junctions read as soft, borderless corridors.",
      accent: "#3d6b62",
      bestWhen: "You want the whole graph visible and the Tracks metaphor to emerge naturally from topology rather than stored membership.",
      losesWhen: "The visible horizon is so large or dense that any global graph needs aggressive focus and collapsing.",
      decisions: [
        { label: "Ontology", value: "A track is a renderer-derived corridor between fork/join junctions, never a durable entity." },
        { label: "Layout", value: "Stable layered ranks, crossing reduction, continuity bias, and faint wide under-strokes behind normal edges." },
        { label: "Adding work", value: "A new dependent branches locally; unrelated nodes retain their coordinates." },
      ],
      keepParts: ["junction-to-junction corridors", "stable local insertion", "faint neutral under-stroke"],
      proof: ["The preview renders the shared split/merge/re-split topology as continuous whitespace corridors.", "The Add parallel task toggle inserts one local branch without moving the existing graph."],
      scores: {
        fr1: { score: 5, evidence: "Wide neutral under-strokes and aligned nodes make each branch perceptually continuous through the whole fixture.", confidence: "high" },
        fr2: { score: 5, evidence: "Corridors visibly terminate and reform at the actual fork and join nodes; ordinary dependency edges remain on top.", confidence: "high" },
        fr3: { score: 5, evidence: "The concept derives entirely from dependencies, with areas available only as a soft ordering bias.", confidence: "high" },
        fr4: { score: 4, evidence: "The local-add demo preserves all existing positions; production stability still depends on an unimplemented deterministic layout pass.", confidence: "medium" },
        fr5: { score: 4, evidence: "Corridors can combine with collapse and selection, but the standalone preview does not prove a 50-node graph.", confidence: "medium" },
      },
      gateResults: {
        g1: { pass: true, evidence: "Thin arrowed edges remain the explicit causal layer above every corridor." },
        g2: { pass: true, evidence: "No track property or saved lane is needed; the added branch is derived from one new dependency." },
        g3: { pass: true, evidence: "All ten shared nodes, statuses, forks, joins, and outgoing review branches are visible." },
      },
      preview: corridorsPreview,
    },
    {
      id: "v2", name: "Area Metro",
      thesis: "Use existing multi-valued vibe-areas as named route lines that may overlap, diverge, and reconverge.",
      accent: "#5b7285",
      bestWhen: "The same semantic workstreams recur across many tasks and their names matter more than a quiet monochrome graph.",
      losesWhen: "Features span several areas, route color proliferates, or area affinity is weaker than the actual causal chain.",
      decisions: [
        { label: "Ontology", value: "Areas are durable non-exclusive facets; metro routes are their visual projection." },
        { label: "Join", value: "Several route strokes may pass through one task without duplicating that task." },
        { label: "Interaction", value: "Selecting a route dims other areas while retaining cross-route dependency edges." },
      ],
      keepParts: ["clickable workstream labels", "existing area vocabulary", "overlapping route treatment"],
      proof: ["The preview draws model, renderer, and agent routes over the identical causal fixture.", "The route-focus toggle isolates renderer while preserving all nodes and edges."],
      scores: {
        fr1: { score: 4, evidence: "Colored routes are easy to follow, but multiple strokes through shared tasks compete with status and edge detail.", confidence: "high" },
        fr2: { score: 4, evidence: "Overlapping routes preserve real joins, though route continuation after a join is partly a semantic-area judgment.", confidence: "medium" },
        fr3: { score: 4, evidence: "It reuses existing areas, but useful output depends on maintaining a reasonably consistent area vocabulary.", confidence: "high" },
        fr4: { score: 4, evidence: "Area names offer stable anchors and the focus action is predictable; multi-area changes can reroute the visual map.", confidence: "medium" },
        fr5: { score: 3, evidence: "Route focus helps, but many areas or dense overlap eventually creates metro-map clutter.", confidence: "high" },
      },
      gateResults: {
        g1: { pass: true, evidence: "Arrowed dependency edges remain visible independently of the colored area routes." },
        g2: { pass: true, evidence: "The route source is today's optional multi-valued vibe-areas, not a new required track field." },
        g3: { pass: true, evidence: "The same ten nodes and exact causal joins remain present while route emphasis changes." },
      },
      preview: metroPreview,
    },
    {
      id: "v3", name: "Lineage Lens",
      thesis: "Keep the global graph general and turn a selected feature's ancestors and descendants into the temporary track.",
      accent: "#486e65",
      bestWhen: "Zach usually thinks about one feature at a time and wants its complete causal neighborhood without losing spatial context.",
      losesWhen: "He needs to compare several unrelated parallel strands simultaneously without repeated selection.",
      decisions: [
        { label: "Ontology", value: "A track exists only for the current selection; no global workstream assignment is implied." },
        { label: "Interaction", value: "Clicking a node darkens its lineage, dims unrelated work, and keeps every node anchored." },
        { label: "Scale", value: "Distant completed ancestry can collapse into counted boundary stubs." },
      ],
      keepParts: ["ancestor/descendant focus", "anchored context", "boundary stubs"],
      proof: ["The preview starts with the same complete DAG.", "Follow Snapshot highlights only its causal lineage and dims the independent dispatcher/live-loop branch."],
      scores: {
        fr1: { score: 5, evidence: "The selected lineage becomes a single high-contrast route while unrelated nodes visibly recede.", confidence: "high" },
        fr2: { score: 5, evidence: "Highlight membership is computed from actual ancestors and descendants, so every fork and join stays causal.", confidence: "high" },
        fr3: { score: 5, evidence: "Selection plus dependencies is sufficient; no grouping metadata exists to maintain.", confidence: "high" },
        fr4: { score: 3, evidence: "Anchored positions are part of the proposal, but the preview does not demonstrate adding nodes or manual correction.", confidence: "medium" },
        fr5: { score: 5, evidence: "Progressive disclosure is the primary interaction, making it the strongest direction for large graphs.", confidence: "high" },
      },
      gateResults: {
        g1: { pass: true, evidence: "Only the true ancestor/descendant edges receive emphasis; no proximity-based relation is introduced." },
        g2: { pass: true, evidence: "The focus set is computed at render time from the existing snapshot." },
        g3: { pass: true, evidence: "The base state contains every shared node and the focus state dims rather than deletes off-lineage work." },
      },
      preview: lineagePreview,
    },
    {
      id: "v4", name: "Chaptered DAG",
      thesis: "Keep the graph fully general and improve readability with phases, junction geometry, bundling, and collapse—not tracks.",
      accent: "#777064",
      bestWhen: "The word track starts implying too much and topological stage is the most useful stable grouping.",
      losesWhen: "The central need is following several long-lived workstreams rather than seeing overall project progression.",
      decisions: [
        { label: "Ontology", value: "No track concept at all; the DAG is grouped only by derived topological chapter." },
        { label: "History", value: "Completed prefixes collapse into counted capsules while outgoing edges stay explicit." },
        { label: "Layout", value: "Crossing reduction and whitespace do the work that lane borders would otherwise do." },
      ],
      keepParts: ["completed-prefix capsules", "phase headings", "honest junction geometry"],
      proof: ["The preview uses the identical DAG without adding routes or memberships.", "The collapse toggle replaces the completed prefix with one counted capsule and preserves its outgoing dependencies."],
      scores: {
        fr1: { score: 3, evidence: "Clean ranks and edges remain traceable, but no persistent visual corridor carries the eye through the graph.", confidence: "high" },
        fr2: { score: 5, evidence: "Forks and joins are ordinary explicit graph junctions with no competing grouping semantics.", confidence: "high" },
        fr3: { score: 5, evidence: "Every phase and capsule is derived from topology and status; the files need no new metadata.", confidence: "high" },
        fr4: { score: 5, evidence: "Topological chapters are deterministic, and the demonstrated collapse changes density without moving downstream nodes.", confidence: "medium" },
        fr5: { score: 4, evidence: "Prefix collapse and phase focus scale better than a fully expanded DAG, though selected-lineage focus is still needed later.", confidence: "medium" },
      },
      gateResults: {
        g1: { pass: true, evidence: "The view renders only actual dependencies and status-derived collapse." },
        g2: { pass: true, evidence: "Ranks, phases, and completed capsules derive from current graph data." },
        g3: { pass: true, evidence: "Expanded state contains the complete fixture; collapsed state explicitly counts the hidden nodes." },
      },
      preview: chaptersPreview,
    },
    {
      id: "v5", name: "Hard Swimlanes",
      thesis: "Persist one exclusive named lane per feature and route dependencies across those fixed rows.",
      accent: "#8c625f",
      bestWhen: "Rows represent genuinely exclusive owners or resources whose stable responsibility matters more than causal flow.",
      losesWhen: "Work is multi-area, branches merge, or the join itself belongs to several conceptual threads—as in this product.",
      decisions: [
        { label: "Ontology", value: "Lane membership is durable and exclusive, so every feature must choose exactly one row." },
        { label: "Join", value: "A merge node is assigned to one lane even when several lanes causally produce it." },
        { label: "Interaction", value: "Moving a join between lanes changes presentation but cannot resolve the semantic ambiguity." },
      ],
      keepParts: ["stable left labels", "resource-ownership view", "manual row ordering"],
      proof: ["The preview forces all ten shared features into four explicit rows.", "Moving Review from Renderer to Agent merely swaps which downstream edge crosses lanes, exposing the arbitrary choice."],
      scores: {
        fr1: { score: 3, evidence: "Horizontal rows are easy to scan locally, but the causal route repeatedly crosses rows at every fork and merge.", confidence: "high" },
        fr2: { score: 2, evidence: "Dependency edges remain present, yet placing the shared Review join in one exclusive lane falsely privileges one stream.", confidence: "high" },
        fr3: { score: 1, evidence: "Every feature requires maintained exclusive lane membership, including intrinsically multi-area joins.", confidence: "high" },
        fr4: { score: 4, evidence: "Manual lanes are positionally stable and correctable, but correction is continual semantic housekeeping.", confidence: "high" },
        fr5: { score: 3, evidence: "Lane filtering is familiar, but cross-lane edges accumulate as the graph grows.", confidence: "medium" },
      },
      gateResults: {
        g1: { pass: true, evidence: "Explicit dependency lines still carry causality; lane proximity itself is not interpreted as an edge." },
        g2: { pass: false, evidence: "The direction requires a new persistent exclusive lane assignment for every feature, including ambiguous joins." },
        g3: { pass: true, evidence: "Every shared node and dependency remains visible in both demonstrated lane placements." },
      },
      preview: swimlanePreview,
    },
  ],
  checks: [
    "Exactly five structurally different directions",
    "Same fork, joins, re-split, statuses, and visual fidelity",
    "One meaningful state change in every prototype",
    "Five weighted criteria frozen before scoring and summing to 100%",
    "Every score carries evidence and confidence",
    "Hard gates separate causal truth from layout judgment",
    "Pick, shortlist, reject, feedback, splice, and Markdown export",
    "Prototype evidence is explicitly separated from production verification",
  ],
};

writeFileSync(specPath, `${JSON.stringify(spec, null, 2)}\n`, "utf8");
console.log(specPath);
