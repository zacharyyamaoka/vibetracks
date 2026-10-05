// The frame every story renders in, and the fixture backend it hands down.
// The frame is the dashboard's own (Dashboard.tsx): `.vt-dash` > `.vt-scroll`, with calm.css loaded, because every
// selector in calm.css, roadmap.css and a.css starts at `.vt-dash`; a component outside it renders unstyled.
// The backend is one createFixtureBackend per story mount, configured by the story's `parameters.backend`.
// A story names the fixtures it needs in `parameters.fixtures` (a list, or a function of its args; every fixture when
// unset); when one was not captured, the story shows one line saying how to capture it instead of the component.

import { createContext, useContext, useMemo, type ReactNode } from 'react'
import type { Decorator } from '@storybook/react-vite'
import type { PluginBackend } from '@clank/api'
import '../src/shared/calm.css'
import { ALL_FIXTURES, createFixtureBackend, missingFixtures, type FixtureBackendOptions } from './backend'

/** `parameters.fixtures`: the fixture names (backend.ts) a story needs, or a function of its args giving them. */
export type FixtureNeeds = string[] | ((args: Record<string, unknown>) => string[])

const StoryBackend = createContext<PluginBackend | null>(null)

/** The fixture backend of the story being rendered. */
export function useStoryBackend(): PluginBackend {
  const backend = useContext(StoryBackend)
  if (!backend) throw new Error('useStoryBackend: the story is not inside withDashboardFrame')
  return backend
}

function Frame({ id, options, children }: { id: string; options: FixtureBackendOptions | undefined; children: ReactNode }) {
  // WHY keyed on the story id: a story's "refresh fails after the first success" counts requests, so a new story (or a
  // remount after an args change) must start from a fresh backend, never inherit the last one's count.
  const backend = useMemo(() => createFixtureBackend(options), [id, options])
  return (
    <StoryBackend.Provider value={backend}>
      <div className="vt-dash" data-testid="vt-dashboard" style={{ height: '100vh' }}>
        <div className="vt-scroll">{children}</div>
      </div>
    </StoryBackend.Provider>
  )
}

export const FIXTURE_MISSING_TESTID = 'story-fixture-missing'

export const withDashboardFrame: Decorator = (Story, context) => {
  const needs = (context.parameters.fixtures as FixtureNeeds | undefined) ?? ALL_FIXTURES
  const missing = missingFixtures(typeof needs === 'function' ? needs(context.args) : needs)
  return (
    <Frame id={context.id} options={context.parameters.backend as FixtureBackendOptions | undefined}>
      {missing.length ? (
        // WHY one line and not a crash: the fixtures are local-only BAM data (fixtures/README.md), absent on any fresh
        // checkout; the build must still pass and the story must say how to get them.
        <div className="vt-page">
          <p className="vt-muted" role="status" data-testid={FIXTURE_MISSING_TESTID} data-missing={missing.join(' ')} title={`missing: ${missing.join(', ')}`}>
            Fixture missing: run <code>python3 clank/stories/capture_fixtures.py</code> with the lane up
          </p>
        </div>
      ) : (
        <Story />
      )}
    </Frame>
  )
}
