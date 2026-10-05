import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import { fixturesForTrack } from '../backend'
import { RoadmapHarness } from '../harness'

const FIXTURE = 'stories/fixtures/roadmap/kinsim.json'

const meta = {
  title: 'Roadmap/Freshness',
  component: RoadmapHarness,
  tags: ['autodocs'],
  args: { track: 'kinsim', density: 'both', onOpenRung: fn(), onOpenEvidence: fn() },
  parameters: {
    fixtures: (args: { track?: unknown }) => fixturesForTrack(String(args.track)),
    docs: {
      description: {
        component:
          `How current the document is (src/roadmap/freshness.ts, drawn by Freshness in src/roadmap/index.tsx), in both densities: the calm head over the full board, one document for both. Fixture ${FIXTURE}; the backend's answer per story is set by parameters.backend (stories/backend.ts).`,
      },
    },
  },
} satisfies Meta<typeof RoadmapHarness>

export default meta
type Story = StoryObj<typeof meta>

export const Fresh: Story = {
  parameters: {
    backend: { docs: { kinsim: 'fresh' } },
    docs: { description: { story: `The captured document as served: only the quiet "as of" time. Fixture ${FIXTURE}.` } },
  },
}

export const ServerStale: Story = {
  name: 'Server-stale (stored document served)',
  parameters: {
    backend: { docs: { kinsim: 'server-stale' } },
    docs: {
      description: {
        story: `The captured document with the warning vibetracks/roadmap/api.py prepends when a live projection fails and the stored document is served ("stale: projecting the kinsim loop live failed (…); this is the stored document, generated …"). The failure text in the parentheses is a story placeholder. Fixture ${FIXTURE}.`,
      },
    },
  },
}

export const RefreshFailed: Story = {
  name: 'Refresh failed (client)',
  args: { reloadAfterFirst: true },
  parameters: {
    backend: { docs: { kinsim: 'refresh-fails' } },
    docs: {
      description: {
        story: `The first /roadmap/doc answers with the captured document, the story then calls reload() and that request rejects (TypeError "Failed to fetch"); src/roadmap/loader.ts keeps the document and marks it not current. Fixture ${FIXTURE}.`,
      },
    },
  },
}

export const Loading: Story = {
  args: { density: 'calm' },
  parameters: {
    backend: { docs: { kinsim: 'loading' } },
    fixtures: [],
    docs: { description: { story: 'The first /roadmap/doc never answers: "Loading roadmap…" (src/roadmap/index.tsx), never the empty-state line.' } },
  },
}

export const NoRoadmap: Story = {
  name: 'No roadmap (404)',
  args: { density: 'calm' },
  parameters: {
    backend: { docs: { kinsim: 'missing' } },
    fixtures: ['roadmap/pyblocks.404.json'],
    docs: { description: { story: 'The backend answers the captured 404 (stories/fixtures/roadmap/pyblocks.404.json): "No roadmap reported yet."' } },
  },
}
