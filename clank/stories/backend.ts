// A PluginBackend that answers the dashboard's backend calls from the captured fixtures (fixtures/README.md), so a
// story renders the real components on the real documents without the Python backend or Clank's plugin proxy.
// It answers exactly the paths the components ask for: GET /projection (shared/api.ts), GET /roadmap/doc?track=…
// and GET /roadmap/art (roadmap/index.tsx through roadmap/loader.ts). Art images are not fetched through it: an
// <img> loads `${baseUrl}/roadmap/art/<name>.png`, which .storybook/main.ts serves from fixtures/art (staticDirs).
// WHY the bodies are the captured bytes (`?raw`) and not re-serialised objects: the loader keys "nothing changed" on
// the body text, and a story should hand the component exactly what the lane's backend handed it.

import type { PluginBackend, PluginBackendStatus } from '@clank/api'

// WHY a glob and not static imports: the fixtures are captured locally and never committed (fixtures/README.md), so on
// a fresh checkout they are absent; a static import would fail the whole build, a glob just finds nothing and the
// story says which fixture is missing (decorators.tsx).
const RAW = import.meta.glob<string>('./fixtures/**/*.json', { eager: true, query: '?raw', import: 'default' })
/** The art files present on disk, listed by .storybook/main.ts at startup (they are served as static files, not imported). */
const ART_FILES = new Set<string>(import.meta.env.STORY_ART_FILES ?? [])

/** A captured fixture's body, by its path under fixtures/, or null when it was not captured. */
export const fixtureText = (name: string): string | null => RAW[`./fixtures/${name}`] ?? null

/** The same base Clank gives the plugin in Preview (`<api base>/plugins/<pluginId>`). */
export const BASE_URL = '/api/plugins/vibetracks'

/** The tracks whose roadmap documents are captured; any other track answers the captured 404 (pyblocks'). */
export const DOC_TRACKS = ['kinsim', 'rig', 'grasping', 'detection'] as const
const NOT_FOUND = 'roadmap/pyblocks.404.json'
const ART_LIST = 'roadmap/art.json'
/** Stands for "every PNG roadmap/art.json names is on disk". */
export const ART_FILES_FIXTURE = 'art/*.png'

/** The fixture a track's /roadmap/doc answers from: its document, or the captured 404. */
export const docFixture = (track: string) => ((DOC_TRACKS as readonly string[]).includes(track) ? `roadmap/${track}.json` : NOT_FOUND)

/** What one track's roadmap needs: its document (or the 404), the art list and the art. */
export const fixturesForTrack = (track: string): string[] => [docFixture(track), ART_LIST, ART_FILES_FIXTURE]

/** Every fixture the stories use. */
export const ALL_FIXTURES: string[] = ['projection.json', ...DOC_TRACKS.map(docFixture), NOT_FOUND, ART_LIST, ART_FILES_FIXTURE]

/** The names in `needed` that are not on disk. */
export function missingFixtures(needed: readonly string[]): string[] {
  return needed.filter((name) => {
    if (name !== ART_FILES_FIXTURE) return fixtureText(name) === null
    const list = fixtureText(ART_LIST)
    if (list === null) return true
    const entries = (JSON.parse(list) as { entries?: unknown }).entries
    return !Array.isArray(entries) || entries.some((entry) => typeof entry !== 'string' || !ART_FILES.has(entry))
  })
}

/** How one track's /roadmap/doc answers in a story.
 * - fresh: the captured document.
 * - server-stale: the captured document with the warning api.py:552 prepends when a live projection fails and the
 *   stored document is served instead. The failure inside the parentheses is a story placeholder, said as such.
 * - refresh-fails: the captured document once, then every later request rejects as a dropped connection does.
 * - loading: never answers (until the request is aborted).
 * - missing: the captured 404 "no roadmap reported yet". */
export type DocMode = 'fresh' | 'server-stale' | 'refresh-fails' | 'loading' | 'missing'

export interface FixtureBackendOptions {
  /** Per-track answer of /roadmap/doc; a track with a captured document defaults to 'fresh', any other to 'missing'. */
  docs?: Partial<Record<string, DocMode>>
}

/** The server's own stale warning (vibetracks/roadmap/api.py `_live_held`, the stored-document branch). */
export function serverStaleWarning(track: string, generatedAt: unknown): string {
  return `stale: projecting the ${track} loop live failed (ProjectionError: story fixture, no real failure was captured); this is the stored document, generated ${generatedAt}`
}

/** The captured document of `track` with the server's stale warning prepended, as api.py `_stale` does. */
export function serverStaleText(track: string): string {
  const document = JSON.parse(fixtureText(docFixture(track)) ?? '{}') as { generated_at?: unknown; warnings?: unknown }
  const warnings = Array.isArray(document.warnings) ? document.warnings : []
  return JSON.stringify({ ...document, warnings: [serverStaleWarning(track, document.generated_at), ...warnings] })
}

const json = (status: number, text: string) =>
  new Response(text, { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } })

const abortError = () => new DOMException('The operation was aborted.', 'AbortError')

/** Resolves with `value`, or rejects the way fetch does when `signal` aborts first. */
function settle<T>(value: () => T, signal: AbortSignal | null | undefined): Promise<T> {
  if (signal?.aborted) return Promise.reject(abortError())
  return Promise.resolve().then(() => {
    if (signal?.aborted) throw abortError()
    return value()
  })
}

/** A request that never answers: only an abort ends it. */
function pending(signal: AbortSignal | null | undefined): Promise<Response> {
  return new Promise((_, reject) => {
    if (signal?.aborted) reject(abortError())
    signal?.addEventListener('abort', () => reject(abortError()), { once: true })
  })
}

const RUNNING: PluginBackendStatus = { pluginId: 'vibetracks', declared: true, state: 'running', restarts: 0 }

export function createFixtureBackend(options: FixtureBackendOptions = {}): PluginBackend {
  const docRequests = new Map<string, number>()
  const modeOf = (track: string): DocMode => options.docs?.[track] ?? ((DOC_TRACKS as readonly string[]).includes(track) ? 'fresh' : 'missing')
  // A fixture that was not captured answers as the backend does for a path it cannot serve; the decorator normally
  // shows "Fixture missing" before any request is made, so this is only the fallback.
  const captured = (status: number, name: string) => {
    const text = fixtureText(name)
    return text === null ? json(404, JSON.stringify({ error: `fixture missing: ${name}` })) : json(status, text)
  }

  return {
    baseUrl: BASE_URL,
    fetch(path: string, init?: RequestInit): Promise<Response> {
      const signal = init?.signal
      const url = new URL(path, 'http://fixture.invalid')
      if (url.pathname === '/projection') return settle(() => captured(200, 'projection.json'), signal)
      if (url.pathname === '/roadmap/art') return settle(() => captured(200, ART_LIST), signal)
      if (url.pathname === '/roadmap/doc') {
        const track = url.searchParams.get('track') ?? ''
        const mode = modeOf(track)
        const count = (docRequests.get(track) ?? 0) + 1
        docRequests.set(track, count)
        if (mode === 'loading') return pending(signal)
        if (mode === 'missing' || docFixture(track) === NOT_FOUND) return settle(() => captured(404, NOT_FOUND), signal)
        if (mode === 'server-stale') return settle(() => json(200, serverStaleText(track)), signal)
        // WHY a TypeError: it is what fetch rejects with when the connection drops, so the loader sees the real shape.
        if (mode === 'refresh-fails' && count > 1) return settle(() => { throw new TypeError('Failed to fetch') }, signal)
        return settle(() => captured(200, docFixture(track)), signal)
      }
      // Anything else (a rename's POST, /needs) is outside these fixtures: answer as the backend does for an unknown path.
      return settle(() => json(404, JSON.stringify({ error: `not in the story fixtures: ${url.pathname}` })), signal)
    },
    websocketUrl: (path: string) => `ws://fixture.invalid${BASE_URL}${path}`,
    status: () => Promise.resolve(RUNNING),
    restart: () => Promise.resolve(RUNNING),
  }
}
