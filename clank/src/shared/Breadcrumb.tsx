// The path back up the levels: "Agent work / Kinsim curriculum loop / Rungs green or done / W3".
// Every crumb but the last is a button (G2: no fake controls); the last is where the reader is.

import { Fragment } from 'react'

export interface Crumb {
  label: string
  /** Absent on the current (last) crumb. */
  onClick?: () => void
  title?: string
}

export function Breadcrumb({ items, className }: { items: Crumb[]; className?: string }) {
  return (
    <nav className={`vt-crumbs ${className ?? ''}`} aria-label="Breadcrumb" data-testid="vt-breadcrumb">
      {items.map((crumb, index) => (
        <Fragment key={`${index}-${crumb.label}`}>
          {index > 0 ? <span aria-hidden="true">/</span> : null}
          {crumb.onClick && index < items.length - 1 ? (
            <button type="button" className="vt-btn" onClick={crumb.onClick} title={crumb.title}>
              {crumb.label}
            </button>
          ) : (
            <span className="vt-crumb-here" aria-current="page" title={crumb.title}>
              {crumb.label}
            </span>
          )}
        </Fragment>
      ))}
    </nav>
  )
}
