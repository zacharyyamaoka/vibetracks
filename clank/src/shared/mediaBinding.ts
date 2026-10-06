// The media URL a viewer hands out, bound to the projection that viewer shows. Kept free of runtime imports (types
// only) so a node:test check can load it as is (mediaBinding.check.mjs).
//
// WHY bound to a projection and never to a backend (Codex audit 2026-10-05 round 4, finding 1): the revision used to
// live in one mutable value per backend, written by whichever useProjection rendered last. Two viewers of one .vtdash
// (a Clank split) share one backend, so the viewer that rendered last decided the other's links: an older viewer,
// still showing projection OLD, handed out `?rev=NEW` for a file it never listed, or no revision at all while the
// newer viewer was still loading. The revision now travels with the projection object a viewer rendered; there is no
// backend-wide "current revision" to read, so nothing another viewer does can change it.

import type { PluginBackend } from '@clank/api'
import type { Projection } from './model'

/** The media revision a projection answer carries (`media_rev`, added by the backend), or null when it has none. */
export function mediaRevision(projection: Projection | null | undefined): string | null {
  const value = (projection as { media_rev?: unknown } | null | undefined)?.media_rev
  return typeof value === 'string' && value ? value : null
}

/** The URL a `<video src>`, `<iframe src>` or `<a href>` uses for one media id, under one projection's revision.
 *
 * WHY it carries the revision (audit 2026-10-05 round 2, sibling of finding 1): the backend serves a media id only
 * from the files recorded under the projection the page was given, so a poll or another tab that sees a retargeted
 * alias cannot change what this page's URL opens. A URL with no revision (`revision` null) is refused (409): the page
 * must reload. The revision is a required argument on purpose: there is no default to fall back on. */
export function mediaUrl(backend: Pick<PluginBackend, 'baseUrl'>, id: string, revision: string | null): string {
  const base = `${backend.baseUrl}/media/${encodeURIComponent(id)}`
  return revision ? `${base}?rev=${encodeURIComponent(revision)}` : base
}

/** `mediaUrl(id)` for one viewer, bound to the revision of the projection it shows (`mediaRevision(projection)`):
 * every URL it returns carries that revision for as long as it lives. A viewer rebinds when its projection's revision
 * changes (Dashboard.tsx memoises on backend + revision); nothing outside the call can change what it returns. */
export function bindMediaUrl(backend: Pick<PluginBackend, 'baseUrl'>, revision: string | null): (id: string) => string {
  return (id: string) => mediaUrl(backend, id, revision)
}
