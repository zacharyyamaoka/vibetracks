// The focus panel (Zach, Oct 3: "that card should come into focus... so I can continue to learn more"; "when I click
// an item and it says it's done I want to see proof"). The clicked card grows into this panel (FLIP), which opens on
// the proof the document records; Lineage walks needs and unlocks as cards with a breadcrumb trail.
// Ported from the kinsim dashboard (src/roadmap/FocusPanel.tsx @ 69e91af). What changed: the Proof tab reads the
// bam-roadmap/1 rung's typed fields (derived status and reason, the loop's own word, criteria with targets and
// evidence, blockers, history) instead of scraping free text (proof.ts, retired); an evidence link or a run is handed
// to the dashboard (onOpenEvidence / onOpenRung), which routes it to its L3 views, so the in-panel file reader is gone.

import { Fragment, type ReactNode, useLayoutEffect, useRef } from 'react'
import { ArrowLeft, ExternalLink, FileCode2, X } from 'lucide-react'
import { type Art, ArtView, artUrl } from './art'
import type { RoadmapEvidence, RoadmapHistoryRow, RoadmapLink, RoadmapRung, RoadmapTarget } from './doc'
import { type RoadModel, bucket, criticalPath } from './graph'
import { Dot, STATUS_WORD } from './RoadmapBoard'
import { runRef } from './runRef'
import type { FocusTab, RoadView } from './state'

export interface EvidenceRef {
  path: string
  line?: number
}

const TABS: Array<[FocusTab, string]> = [['proof', 'Proof'], ['lineage', 'Lineage'], ['details', 'Details']]

export function FocusPanel({ model, view, onView, art, artNames, artBase, anchorFor, onOpenEvidence, onOpenRung }: {
  model: RoadModel
  view: RoadView
  onView: (next: Partial<RoadView>) => void
  art: (id: string) => Art
  artNames: ReadonlySet<string>
  artBase: string
  /** The card the panel grows out of, looked up when the panel lays out (Codex A12/B12). */
  anchorFor: () => HTMLElement | null
  onOpenEvidence: (ref: EvidenceRef) => void
  onOpenRung: (rungId: string) => void
}) {
  const id = view.sel!
  const rung = model.byId.get(id)!
  const panel = useRef<HTMLDivElement>(null)
  const opened = useRef(false)

  // FLIP: start the panel exactly over the clicked card, then let it grow into place (first open only; moving
  // between rungs inside the panel swaps its content in place).
  // WHY look the card up here and wait for it (Codex A12/B12): a selection restored before the document loads mounts
  // the panel in the same commit as the board's cards, so a card looked up during render is not there yet, and marking
  // the panel opened anyway skipped its one grow for good. Layout effects run after the board's card refs attach.
  useLayoutEffect(() => {
    if (opened.current || !panel.current) return
    const anchor = anchorFor()
    if (!anchor) return
    const to = panel.current.getBoundingClientRect()
    if (!to.width || !to.height) return  // not laid out yet: try again next render (Codex D05)
    opened.current = true
    // WHY scroll first: the roadmap often sits below the KPI view, and a panel that grows below the fold is a click
    // that seems to do nothing.
    panel.current.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
    if (typeof panel.current.animate !== 'function') return
    const from = anchor.getBoundingClientRect()
    panel.current.animate(
      [
        { transformOrigin: '0 0', transform: `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${from.width / to.width}, ${from.height / to.height})`, opacity: 0.35 },
        { transformOrigin: '0 0', transform: 'none', opacity: 1 },
      ],
      { duration: 340, easing: 'cubic-bezier(.3,.7,.2,1)' },
    )
  })

  const go = (next: string) => {
    if (next === id || !model.byId.has(next)) return
    onView({ sel: next, trail: [...view.trail, id].slice(-8) })
  }
  const back = () => {
    const trail = [...view.trail]
    const previous = trail.pop() ?? null
    onView({ sel: previous, trail })
  }
  const close = () => onView({ sel: null, trail: [] })
  const axis = model.axes[model.axisIndex.get(rung.axis)!]
  const parents = model.parents.get(id)!
  const children = model.children.get(id)!

  return (
    <div
      ref={panel}
      data-testid="vt-roadmap-focus"
      className="vt-rm-focus"
      onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); close() } }}
    >
      <div className="vt-rm-focus-bar">
        {view.trail.length ? (
          <button type="button" className="vt-btn vt-rm-icon-btn" data-testid="vt-roadmap-focus-back" title={`back to ${view.trail[view.trail.length - 1]}`} onClick={back}><ArrowLeft size={14} /></button>
        ) : null}
        <div data-testid="vt-roadmap-focus-trail" className="vt-rm-trail">
          {view.trail.map((crumb, i) => (
            <span key={`${crumb}-${i}`}>
              <button type="button" className="vt-btn vt-rm-crumb" onClick={() => onView({ sel: crumb, trail: view.trail.slice(0, i) })}>{crumb}</button>
              <span className="vt-faint">›</span>
            </span>
          ))}
          <b>{id}</b>
        </div>
        <button type="button" className="vt-btn vt-rm-icon-btn vt-rm-close" data-testid="vt-roadmap-focus-close" title="close (Esc)" onClick={close}><X size={15} /></button>
      </div>

      <div className="vt-rm-focus-head">
        <span className="vt-rm-focus-art" data-status={rung.status}>
          <ArtView art={art(id)} size={104} artBase={artBase} />
        </span>
        <div className="vt-rm-min0">
          <div className="vt-rm-focus-id">{id}</div>
          <div className="vt-rm-focus-title">{rung.title}</div>
          <div className="vt-rm-focus-tags">
            <span className="vt-rm-inline"><Dot status={rung.status} />{STATUS_WORD[rung.status] ?? rung.status}</span>
            {rung.frontier ? <span className="vt-rm-tag">frontier</span> : null}
            {rung.triage.map((t) => <span key={t} className="vt-rm-tag vt-rm-tag-risk">triage {t}</span>)}
          </div>
          <div className="vt-faint vt-rm-xs">{axis.title} · {bucket(model, id).replace('ready', 'ready now')} · {parents.length} needs · {children.length} unlocks</div>
        </div>
      </div>

      <div role="tablist" aria-label="Rung" className="vt-rm-tabs">
        {TABS.map(([tab, label]) => (
          <button key={tab} type="button" role="tab" className="vt-btn" aria-selected={view.tab === tab} data-testid={`vt-roadmap-focus-tab-${tab}`} onClick={() => onView({ tab })}>
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="vt-rm-focus-body">
        {view.tab === 'proof' ? <ProofTab rung={rung.rung} artNames={artNames} artBase={artBase} onGo={go} onOpenEvidence={onOpenEvidence} onOpenRung={onOpenRung} /> : null}
        {view.tab === 'lineage' ? <LineageTab model={model} id={id} art={art} artBase={artBase} onGo={go} /> : null}
        {view.tab === 'details' ? <DetailsTab model={model} id={id} art={art} onOpenEvidence={onOpenEvidence} /> : null}
      </div>
    </div>
  )
}

const Section = ({ children }: { children: ReactNode }) => <div className="vt-rm-section">{children}</div>

const shortTs = (ts: string | null) => (ts ? ts.replace('T', ' ').slice(0, 16) : '')
const shortSha = (sha: string | null) => (sha ? sha.slice(0, 8) : null)

/** A link the dashboard can open (it exists now: `abs`), else an honest label saying why not. */
export function LinkButton({ link, label, onOpen }: { link: RoadmapLink; label?: string; onOpen: (ref: EvidenceRef) => void }) {
  const text = `${label ?? link.label ?? link.path ?? link.kind}${link.line ? `:${link.line}` : ''}`
  // WHY not clickable when it does not resolve (Codex A02): a button that 404s is worse than an honest label.
  if (!link.abs) {
    return (
      <span className="vt-rm-link vt-rm-link-dead" title={link.why_unresolved ?? `${link.path ?? text}: not found`}>
        <FileCode2 size={12} />{text}
      </span>
    )
  }
  const abs = link.abs
  return (
    <button type="button" className="vt-btn vt-rm-link" data-testid="vt-roadmap-evidence-link" data-path={abs} title={`open ${abs}${link.line ? ` at line ${link.line}` : ''}`}
      onClick={() => onOpen(link.line ? { path: abs, line: link.line } : { path: abs })}>
      <FileCode2 size={12} />{text}
    </button>
  )
}

/** What a criterion names. A rung hops to it inside the panel; a target with no path (a gate, an audit, a package) is a
 * plain label, not a file link that cannot open; anything with a path is a LinkButton. */
function TargetLabel({ target, onGo, onOpen }: { target: RoadmapTarget; onGo: (id: string) => void; onOpen: (ref: EvidenceRef) => void }) {
  if (target.kind === 'rung' && target.label) {
    return <button type="button" className="vt-btn vt-rm-chip" title={`go to ${target.label}`} onClick={() => onGo(target.label!)}>{target.label}</button>
  }
  if (!target.path && !target.abs) return <span className="vt-rm-sm"><span className="vt-faint vt-rm-xs">{target.kind}</span> {target.label}</span>
  return <LinkButton link={target} onOpen={onOpen} />
}

function ProofTab({ rung, artNames, artBase, onGo, onOpenEvidence, onOpenRung }: {
  rung: RoadmapRung
  artNames: ReadonlySet<string>
  artBase: string
  onGo: (id: string) => void
  onOpenEvidence: (ref: EvidenceRef) => void
  onOpenRung: (rungId: string) => void
}) {
  const evidence = new Map(rung.evidence.map((item) => [item.id, item]))
  const loopDiffers = rung.claimed_status !== rung.status
  const runs = rung.support?.runs ?? []
  return (
    <div data-testid="vt-roadmap-proof" className="vt-rm-proof">
      <div className="vt-rm-verdict" data-status={rung.status}>
        <div className="vt-rm-inline"><Dot status={rung.status} /><b>{STATUS_WORD[rung.status] ?? rung.status}</b>
          {loopDiffers ? (
            <span className="vt-muted" data-testid="vt-roadmap-loop-says">
              {' · '}the loop says{' '}
              {rung.claimed_by?.source?.abs
                ? <button type="button" className="vt-btn vt-rm-textlink" title={`${rung.claimed_by.source.label ?? rung.claimed_by.source.path} ${rung.claimed_by.source.pointer}`} onClick={() => onOpenEvidence({ path: rung.claimed_by.source!.abs!, ...(rung.claimed_by.source!.line ? { line: rung.claimed_by.source!.line } : {}) })}>{rung.claimed_status}</button>
                : <b>{rung.claimed_status}</b>}
            </span>
          ) : null}
        </div>
        {rung.status_reason ? <div className="vt-muted vt-rm-sm">{rung.status_reason}</div> : null}
        {runs.length ? (
          <button type="button" className="vt-btn vt-rm-textlink vt-rm-sm" data-testid="vt-roadmap-latest-run" onClick={() => onOpenRung(rung.id)}>
            <ExternalLink size={12} /> see the latest run
          </button>
        ) : null}
      </div>

      {rung.blockers.map((blocker) => (
        <div key={blocker.id} className="vt-rm-blocker">
          <b>Blocked by triage {blocker.id}</b> · {blocker.title}
          {blocker.default ? <div className="vt-muted vt-rm-sm">Default if unanswered{blocker.default_applies_after_wave != null ? ` after wave ${blocker.default_applies_after_wave}` : ''}: {blocker.default}</div> : null}
          {blocker.source ? <div className="vt-rm-links"><LinkButton link={blocker.source} onOpen={onOpenEvidence} /></div> : null}
        </div>
      ))}

      {rung.alias_of ? (
        <div>Proof lives on <button type="button" className="vt-btn vt-rm-chip" onClick={() => onGo(rung.alias_of!)}>{rung.alias_of}</button>, whose evidence promotes this rung too.</div>
      ) : null}

      {rung.criteria.length ? (
        <>
          <Section>Done when · {rung.criteria.filter((c) => c.verdict === 'met').length} of {rung.criteria.length} met</Section>
          <ol className="vt-rm-criteria">
            {rung.criteria.map((criterion) => (
              <li key={criterion.id} data-verdict={criterion.verdict}>
                <div className="vt-rm-crit-head"><span className="vt-rm-verdict-word" data-verdict={criterion.verdict}>{criterion.verdict}</span><b>{criterion.title}</b></div>
                <div className="vt-faint vt-rm-xs">{[criterion.method ?? criterion.kind, criterion.strength ? `${criterion.strength} strength` : null].filter(Boolean).join(' · ')}</div>
                {criterion.reason ? <div className="vt-muted vt-rm-sm">{criterion.reason}</div> : null}
                {criterion.targets.map((target, i) => (
                  <div key={`${target.path ?? target.label}-${i}`} className="vt-rm-target">
                    <div className="vt-rm-links">
                      <TargetLabel target={target} onGo={onGo} onOpen={onOpenEvidence} />
                      <span className="vt-rm-verdict-word" data-verdict={target.verdict}>{target.verdict}</span>
                      {target.note ? <span className="vt-faint vt-rm-xs">{target.note}</span> : null}
                    </div>
                    {target.evidence.map((eid) => evidence.get(eid)).filter((item): item is RoadmapEvidence => Boolean(item)).map((item) => (
                      <EvidenceRow key={item.id} item={item} artNames={artNames} artBase={artBase} onOpenEvidence={onOpenEvidence} />
                    ))}
                  </div>
                ))}
              </li>
            ))}
          </ol>
        </>
      ) : null}

      {rung.history.length ? (
        <>
          <Section>Status history · loop_events.jsonl</Section>
          <ol className="vt-rm-history">
            {[...rung.history].reverse().map((row, i) => (
              <HistoryItem key={`${row.event?.line ?? row.ts}-${i}`} row={row} evidence={evidence} artNames={artNames} artBase={artBase} onOpenEvidence={onOpenEvidence} />
            ))}
          </ol>
        </>
      ) : null}

      {!rung.criteria.length && !rung.history.length && !rung.blockers.length && !rung.alias_of ? (
        <div className="vt-muted">Nothing recorded for this rung yet: no criterion and no status event.</div>
      ) : null}
    </div>
  )
}

function HistoryItem({ row, evidence, artNames, artBase, onOpenEvidence }: {
  row: RoadmapHistoryRow
  evidence: Map<string, RoadmapEvidence>
  artNames: ReadonlySet<string>
  artBase: string
  onOpenEvidence: (ref: EvidenceRef) => void
}) {
  const current = row.superseded_by == null
  const items = row.evidence.map((eid) => evidence.get(eid)).filter((item): item is RoadmapEvidence => Boolean(item))
  return (
    <li data-current={current || undefined}>
      <span className="vt-rm-history-dot"><Dot status={row.status ?? 'unknown'} /></span>
      <div className="vt-rm-history-meta">
        <b>{row.status ?? row.kind ?? 'event'}</b><span>{shortTs(row.ts)}</span>
        {current ? <span className="vt-rm-tag">current</span> : <span className="vt-rm-tag vt-faint" title={`replaced by the event on line ${row.superseded_by}`}>superseded</span>}
        {row.wave != null ? <span>wave {row.wave}</span> : null}
        {row.commit ? <span>commit <code>{shortSha(row.commit)}</code></span> : null}
        {row.event?.abs ? <button type="button" className="vt-btn vt-rm-textlink" title={`${row.event.path}:${row.event.line}`} onClick={() => onOpenEvidence({ path: row.event.abs!, line: row.event.line })}>line {row.event.line}</button> : null}
      </div>
      {row.detail ? <div className="vt-rm-wrap">{row.detail}</div> : null}
      {items.map((item) => <EvidenceRow key={item.id} item={item} artNames={artNames} artBase={artBase} onOpenEvidence={onOpenEvidence} />)}
      {row.evidence_text ? (
        <details className="vt-rm-details" open={current && row.status === 'green'}>
          <summary>Evidence text</summary>
          <div className="vt-muted vt-rm-sm vt-rm-wrap">{row.evidence_text}</div>
        </details>
      ) : null}
    </li>
  )
}

/** One evidence item: what it is, its result and strength, its role in the status, and the way to open it. Every item,
 * a named run included, opens as a file (onOpenEvidence) at its own recorded path and line. */
function EvidenceRow({ item, artNames, artBase, onOpenEvidence }: {
  item: RoadmapEvidence
  artNames: ReadonlySet<string>
  artBase: string
  onOpenEvidence: (ref: EvidenceRef) => void
}) {
  // The art API's names are lowercase only (GET /roadmap/art/<name>); run ids carry T and Z, so the still is lowercased.
  const runOpen = runRef(item)
  const still = item.kind === 'run' && item.run_id ? `episode_${item.run_id.toLowerCase()}.png` : null
  return (
    <div className="vt-rm-evidence" data-role={item.role} data-testid="vt-roadmap-evidence">
      {still && artNames.has(still) ? <img src={artUrl(artBase, still)} alt={`episode still from ${item.run_id}`} className="vt-rm-still" /> : null}
      <div className="vt-rm-links">
        <span className="vt-faint vt-rm-xs">{item.kind}</span>
        {item.kind === 'run' && item.run_id ? (
          // WHY this run's own evidence and not onOpenRung (Codex V11): onOpenRung selects the rung's LATEST run, so every
          // named run opened the same one. "see the latest run" (ProofTab) keeps onOpenRung. A run with no absolute path
          // has nothing to open: it is a plain label saying why, never a button that opens some other run.
          runOpen ? (
            <button type="button" className="vt-btn vt-rm-link" data-testid="vt-roadmap-open-run" data-path={runOpen.path} title={`open ${runOpen.path}${runOpen.line ? ` at line ${runOpen.line}` : ''}`} onClick={() => onOpenEvidence(runOpen)}>
              <ExternalLink size={12} />{item.run_id}
            </button>
          ) : (
            <span className="vt-rm-link vt-rm-link-dead" data-testid="vt-roadmap-run-label" title={item.why_unresolved ?? `${item.run_id}: no recorded evidence file to open`}>
              <ExternalLink size={12} />{item.run_id}
            </span>
          )
        ) : item.path || item.abs ? <LinkButton link={item} onOpen={onOpenEvidence} /> : <span className="vt-rm-xs">{item.label ?? item.id}</span>}
        <span className="vt-rm-xs">{[item.result, item.strength, item.role !== 'supports' ? item.role : null].filter(Boolean).join(' · ')}</span>
        {item.commit ? <code className="vt-faint vt-rm-xs">{shortSha(item.commit)}</code> : null}
      </div>
    </div>
  )
}

function MiniCard({ model, id, art, artBase, onGo, strong }: { model: RoadModel; id: string; art: (id: string) => Art; artBase: string; onGo: (id: string) => void; strong?: boolean }) {
  const rung = model.byId.get(id)!
  return (
    <button type="button" data-testid={`vt-roadmap-lineage-${id}`} title={`${rung.title} — ${rung.status}`} onClick={() => onGo(id)}
      className={`vt-btn vt-rm-mini${strong ? ' vt-rm-mini-strong' : ''}`}>
      <ArtView art={art(id)} size={34} artBase={artBase} />
      <span className="vt-rm-min0">
        <b className="vt-rm-mono">{id}</b>{strong ? null : <> {rung.title}</>}
        <span className="vt-rm-inline vt-faint"><Dot status={rung.status} />{rung.status}</span>
      </span>
    </button>
  )
}

function LineageTab({ model, id, art, artBase, onGo }: { model: RoadModel; id: string; art: (id: string) => Art; artBase: string; onGo: (id: string) => void }) {
  const cp = criticalPath(model, id)
  const parents = model.parents.get(id)!
  const children = model.children.get(id)!
  return (
    <div data-testid="vt-roadmap-lineage">
      <div className="vt-rm-lineage">
        <div className="vt-rm-col">
          <div className="vt-rm-section vt-rm-needs">Needs · {parents.length}</div>
          {parents.length ? parents.map((p) => <MiniCard key={p} model={model} id={p} art={art} artBase={artBase} onGo={onGo} />) : <span className="vt-muted">nothing: a root</span>}
        </div>
        <div className="vt-rm-col vt-rm-col-mid vt-faint">→<MiniCard model={model} id={id} art={art} artBase={artBase} onGo={() => undefined} strong />→</div>
        <div className="vt-rm-col">
          <div className="vt-rm-section vt-rm-unlocks">Unlocks · {children.length}</div>
          {children.length ? children.map((c) => <MiniCard key={c} model={model} id={c} art={art} artBase={artBase} onGo={onGo} />) : <span className="vt-muted">nothing yet: a leaf</span>}
        </div>
      </div>
      <Section>Critical path to here · {cp.total} est. wave{cp.total === 1 ? '' : 's'} still to climb</Section>
      <div className="vt-rm-links">
        {cp.total > 0 ? cp.path.map((p, i) => (
          <span key={p} className="vt-rm-inline">
            {i ? <span className="vt-faint">→</span> : null}
            <button type="button" className="vt-btn vt-rm-chip" onClick={() => onGo(p)}><Dot status={model.byId.get(p)!.status} />{p}</button>
          </span>
        )) : <span className="vt-muted">everything upstream is proven</span>}
      </div>
      <div className="vt-faint vt-rm-xs" style={{ marginTop: 8 }}>{model.up.get(id)!.size} rungs upstream in all, {model.down.get(id)!.size} downstream.</div>
    </div>
  )
}

function DetailsTab({ model, id, art, onOpenEvidence }: { model: RoadModel; id: string; art: (id: string) => Art; onOpenEvidence: (ref: EvidenceRef) => void }) {
  const roadRung = model.byId.get(id)!
  const rung = roadRung.rung
  const facts: Array<[string, ReactNode]> = [
    ['Adds', rung.adds ?? '—'],
    ['Done when', rung.done_when?.text || '—'],
    ['Planned', `wave ${roadRung.wave ?? '—'}${roadRung.est ? ` · est ${roadRung.est} wave${roadRung.est === 1 ? '' : 's'}` : ''}`],
  ]
  return (
    <div data-testid="vt-roadmap-details">
      <dl className="vt-rm-facts">
        {facts.map(([k, v]) => <Fragment key={k}><dt className="vt-muted">{k}</dt><dd className="vt-rm-wrap">{v}</dd></Fragment>)}
      </dl>
      {rung.done_when?.source || rung.claimed_by?.source ? (
        <>
          <Section>Source</Section>
          <div className="vt-rm-links">
            {rung.done_when?.source ? <LinkButton link={rung.done_when.source} label={`done when: ${rung.done_when.source.label ?? rung.done_when.source.path}`} onOpen={onOpenEvidence} /> : null}
            {rung.claimed_by?.source ? <LinkButton link={rung.claimed_by.source} label={`the loop's word: ${rung.claimed_by.source.label ?? rung.claimed_by.source.path}`} onOpen={onOpenEvidence} /> : null}
          </div>
        </>
      ) : null}
      {rung.kpis.length ? (
        <>
          <Section>KPIs</Section>
          <dl className="vt-rm-facts">
            {rung.kpis.map((kpi) => <Fragment key={kpi.name}><dt className="vt-muted">{kpi.name}</dt><dd>{kpi.value ?? '—'}{kpi.unit ? ` ${kpi.unit}` : ''}{kpi.run ? <span className="vt-faint"> · {kpi.run}</span> : null}</dd></Fragment>)}
          </dl>
        </>
      ) : null}
      {rung.notes.length ? <><Section>Notes</Section>{rung.notes.map((note, i) => <p key={i} className="vt-rm-wrap vt-rm-sm">{note}</p>)}</> : null}
      <Section>Card art</Section>
      <div className="vt-faint vt-rm-xs">{art(id).caption}</div>
    </div>
  )
}
