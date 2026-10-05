import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import { fixturesForTrack } from '../backend'
import { RoadmapHarness } from '../harness'

const meta = {
  title: 'Roadmap/Calm head',
  component: RoadmapHarness,
  tags: ['autodocs'],
  args: { density: 'calm', onOpenRung: fn(), onOpenEvidence: fn() },
  argTypes: {
    track: { control: 'select', options: ['kinsim', 'rig', 'grasping', 'detection', 'pyblocks'] },
    density: { control: 'inline-radio', options: ['calm', 'full', 'both'] },
  },
  parameters: {
    fixtures: (args: { track?: unknown }) => fixturesForTrack(String(args.track)),
    docs: {
      description: {
        component:
          'RoadmapWidget (src/roadmap/index.tsx) at density "calm": the Roadmap section\'s head, one sentence (summary.ts) and the per-lane strip, loaded through useRoadmap from the captured /roadmap/doc of each track (stories/fixtures/roadmap/<track>.json).',
      },
    },
  },
} satisfies Meta<typeof RoadmapHarness>

export default meta
type Story = StoryObj<typeof meta>

const about = (track: string, fixture: string) => ({
  docs: { description: { story: `src/roadmap/index.tsx CalmAnswer for ${track}; fixture ${fixture}.` } },
})

export const Kinsim: Story = { args: { track: 'kinsim' }, parameters: about('kinsim', 'stories/fixtures/roadmap/kinsim.json') }
export const Rig: Story = { args: { track: 'rig' }, parameters: about('rig', 'stories/fixtures/roadmap/rig.json') }
export const Grasping: Story = { args: { track: 'grasping' }, parameters: about('grasping', 'stories/fixtures/roadmap/grasping.json') }
export const Detection: Story = { args: { track: 'detection' }, parameters: about('detection', 'stories/fixtures/roadmap/detection.json') }
export const PyblocksNoRoadmap: Story = {
  name: 'Pyblocks (404, no roadmap yet)',
  args: { track: 'pyblocks' },
  parameters: {
    docs: {
      description: {
        story:
          'src/roadmap/index.tsx empty state "No roadmap reported yet.": the backend\'s captured 404 for pyblocks (stories/fixtures/roadmap/pyblocks.404.json), which loader.ts treats as a calm state, not an error.',
      },
    },
  },
}
