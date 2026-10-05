// The kit's own proof that the data reaches a proposal: every live item, grouped, with the fields a real page will
// fold (context, recommendation, default, blocks, evidence) and a working answer + Copy out. Each n1..n5 starts by
// rendering this; builders replace it. Kept deliberately plain so it never reads as a design.

import { CopyOut } from './CopyOut'
import { EvidenceLink } from './EvidenceLink'
import { StaleDraftNotice } from './StaleDraftNotice'
import type { NeedsProposalProps } from './proposal'
import { GROUP_LABEL, GROUP_ORDER, describeDefault, type Choice, type NeedsDoc, type NeedsItem } from './types'

export function PlaceholderList(props: NeedsProposalProps & { label: string }) {
  const { docs, loading, error, label } = props
  return (
    <div className="vt-page vt-needs-placeholder" data-testid="vt-needs-placeholder">
      <p className="vt-label">{label} · placeholder from the shared kit</p>
      <h1 className="vt-h1">Needs you</h1>
      {loading && !docs.length ? <p className="vt-muted">Reading the loops…</p> : null}
      {error ? <p className="vt-tone-risk">/needs did not answer: {error}</p> : null}
      {docs.map((doc) => (
        <TrackBlock key={doc.track} {...props} doc={doc} />
      ))}
      {docs.length ? <CopyOut docs={docs} answers={props.answers} /> : null}
    </div>
  )
}

function TrackBlock({ doc, ...props }: Omit<NeedsProposalProps, 'doc'> & { doc: NeedsDoc }) {
  const c = doc.counts
  return (
    <section className="vt-needs-track" data-testid={`vt-needs-track-${doc.track}`}>
      <h2 className="vt-h2">{doc.track_title}</h2>
      <p className="vt-small vt-muted">
        {c.blocking_now} blocking · {c.no_default} no default · {c.waiting} pending · {c.defaulting} defaulting without you · {c.open} open of {c.total}
        {doc.iteration ? ` · ${doc.iteration.unit} ${doc.iteration.n ?? '–'} ${doc.iteration.phase ?? ''}` : ''}
      </p>
      <p className="vt-small vt-faint">
        {doc.source.live ? 'live' : 'not live'} · {doc.source.note}
        {doc.source.commit ? ` · ${doc.source.commit}` : ''} · answers via {doc.answer_channel.kind}
      </p>
      {GROUP_ORDER.filter((group) => group !== 'done').map((group) => {
        const items = doc.items.filter((item) => item.group === group)
        if (!items.length) return null
        return (
          <div key={group} className="vt-needs-group">
            <h3 className="vt-h3">
              {GROUP_LABEL[group]} <span className="vt-faint">{items.length}</span>
            </h3>
            {items.map((item) => (
              <ItemRow key={item.id} {...props} doc={doc} item={item} />
            ))}
          </div>
        )
      })}
    </section>
  )
}

function ItemRow({ doc, item, answers, backend }: Omit<NeedsProposalProps, 'doc'> & { doc: NeedsDoc; item: NeedsItem }) {
  const draft = answers.get(doc.track, item.local_id)
  const choose = (choice: Choice) => answers.set(doc.track, item.local_id, { choice: draft?.choice === choice ? null : choice })
  return (
    <div className="vt-needs-item" data-testid="vt-needs-item" data-item={item.id}>
      <p>
        <span className="vt-faint vt-num">{item.local_id}</span> <span className="vt-strong">{item.title}</span>
      </p>
      <p className="vt-small vt-muted">
        {item.blocks.length ? `blocks ${item.blocks.map((block) => (block.label ? `${block.id} ${block.label}` : block.id)).join(', ')} · ` : ''}
        default {describeDefault(item)}
        {item.created.ts ? ` · opened ${item.created.ts.slice(0, 10)}` : item.created.iteration !== null ? ` · opened ${doc.iteration?.unit ?? 'wave'} ${item.created.iteration}` : ''}
      </p>
      {item.context_lead_md ? <p className="vt-small">{item.context_lead_md}</p> : null}
      <details>
        <summary className="vt-small vt-faint">Full context, recommendation and default</summary>
        <p className="vt-small vt-needs-pre">{item.context_md}</p>
        <p className="vt-small vt-needs-pre"><span className="vt-strong">Recommendation:</span> {item.recommendation_md}</p>
        <p className="vt-small vt-needs-pre"><span className="vt-strong">Default:</span> {item.default.text_md}</p>
      </details>
      {item.evidence.length ? (
        <p className="vt-small vt-needs-evidence-row">
          {item.evidence.map((_, index) => (
            <EvidenceLink key={index} backend={backend} doc={doc} item={item} index={index} />
          ))}
        </p>
      ) : null}
      <StaleDraftNotice answers={answers} doc={doc} item={item} />
      <p className="vt-small vt-needs-choices">
        {item.options.map((option) => (
          <button
            key={option.key}
            type="button"
            className="vt-btn vt-chip-btn"
            aria-pressed={draft?.choice === option.key}
            onClick={() => choose(option.key)}
          >
            {option.label}
          </button>
        ))}
      </p>
      <textarea
        className="vt-needs-note"
        placeholder="Note (a note alone answers as 'something else')"
        value={draft?.note ?? ''}
        rows={1}
        onChange={(event) => answers.set(doc.track, item.local_id, { note: event.target.value })}
      />
    </div>
  )
}
