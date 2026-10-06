import type { Meta, StoryObj } from '@storybook/react-vite'
import { useRoadmap } from '../../src/roadmap'
import { useProjection } from '../../src/shared/api'
import { trackById } from '../../src/shared/model'
import { ProgressCell } from '../../src/variants/a/TracksPage'
import '../../src/variants/a/a.css'
import { docFixture } from '../backend'
import { useStoryBackend } from '../decorators'

/** One Progress cell in a one-row copy of the tracks table, fed the way TrackRow feeds it (TracksPage.tsx). */
function ProgressCellHarness({ track, showDeltas = true }: { track: string; showDeltas?: boolean }) {
  const backend = useStoryBackend()
  const { projection } = useProjection(backend)
  const roadmap = useRoadmap(backend, track)
  const shown = projection ? trackById(projection, track) : null
  if (!shown) return <p className="vt-empty">{projection ? `No track ${track} in the projection.` : 'Loading the projection…'}</p>
  return (
    <div className="vt-a">
      <div className="vt-page vt-a-page">
        <table className="vt-table vt-a-tracks" aria-label="Progress cell" style={{ width: 320 }}>
          <thead>
            <tr>
              <th>Progress</th>
            </tr>
          </thead>
          <tbody>
            <tr className="vt-a-trackrow" data-track={track}>
              <td>
                <ProgressCell track={shown} showDeltas={showDeltas} roadmapDoc={roadmap.doc} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

const meta = {
  title: 'Dashboard/Progress cell',
  component: ProgressCellHarness,
  tags: ['autodocs'],
  args: { track: 'kinsim', showDeltas: true },
  argTypes: { track: { control: 'select', options: ['kinsim', 'rig', 'grasping', 'detection', 'pyblocks'] } },
  parameters: {
    fixtures: (args: { track?: unknown }) => ['projection.json', docFixture(String(args.track))],
    docs: {
      description: {
        component:
          'ProgressCell (src/variants/a/TracksPage.tsx): the north star, its trend and "· N proven" (proven.ts: the projector\'s green + done counts). Fixtures stories/fixtures/projection.json and stories/fixtures/roadmap/<track>.json.',
      },
    },
  },
} satisfies Meta<typeof ProgressCellHarness>

export default meta
type Story = StoryObj<typeof meta>

export const Fresh: Story = {
  name: 'Fresh · N proven',
  parameters: {
    backend: { docs: { kinsim: 'fresh' } },
    docs: { description: { story: 'kinsim, the captured document: "N proven", N = counts.by_status.done + green. Fixture stories/fixtures/roadmap/kinsim.json.' } },
  },
}

export const NotCurrent: Story = {
  name: 'Not current · N proven (not current)',
  parameters: {
    backend: { docs: { kinsim: 'server-stale' } },
    docs: {
      description: {
        story:
          'kinsim with the server\'s stale warning prepended (stories/backend.ts serverStaleText, the api.py format): "N proven (not current)". Fixture stories/fixtures/roadmap/kinsim.json.',
      },
    },
  },
}

export const NoRoadmap: Story = {
  name: 'No roadmap (pyblocks)',
  args: { track: 'pyblocks' },
  parameters: {
    docs: { description: { story: 'pyblocks has no roadmap (captured 404), so the cell carries no proven count at all. Fixture stories/fixtures/roadmap/pyblocks.404.json.' } },
  },
}
