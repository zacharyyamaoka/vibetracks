import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import { fixturesForTrack } from '../backend'
import { RoadmapHarness } from '../harness'

const FIXTURE = 'stories/fixtures/roadmap/kinsim.json'

const meta = {
  title: 'Roadmap/Full board',
  component: RoadmapHarness,
  tags: ['autodocs'],
  args: { track: 'kinsim', density: 'full', onOpenRung: fn(), onOpenEvidence: fn() },
  argTypes: {
    track: { control: 'select', options: ['kinsim', 'rig', 'grasping', 'detection'] },
    density: { control: 'inline-radio', options: ['calm', 'full', 'both'] },
  },
  parameters: {
    fixtures: (args: { track?: unknown }) => fixturesForTrack(String(args.track)),
    docs: {
      description: {
        component:
          `RoadmapWidget (src/roadmap/index.tsx) at density "full": the lens bar, legend and the swimlane board (src/roadmap/RoadmapBoard.tsx, layout in graph.ts), on the kinsim document (${FIXTURE}). The lens, direction and card size are the widget's controlled state, so the lens bar works inside the story.`,
      },
    },
  },
} satisfies Meta<typeof RoadmapHarness>

export default meta
type Story = StoryObj<typeof meta>

const about = (what: string) => ({ docs: { description: { story: `${what} Source src/roadmap/RoadmapBoard.tsx; fixture ${FIXTURE}.` } } })

export const Ladder: Story = { args: { initialState: { lens: 'ladder' } }, parameters: about('Ladder lens: authored rung order, one row per axis, compact cards.') }
export const Depth: Story = { args: { initialState: { lens: 'depth' } }, parameters: about('Depth lens: x is dependency depth, all dependency lines drawn.') }
export const NowNextLater: Story = {
  name: 'Now · Next · Later',
  args: { initialState: { lens: 'board' } },
  parameters: about('Now · Next · Later lens (lens key "board"): the lanes by distance from climbable.'),
}
export const Waves: Story = { args: { initialState: { lens: 'waves' } }, parameters: about('Waves lens: x is the wave the roadmap plans for each rung.') }
export const CompactCards: Story = {
  name: 'Compact cards (Depth)',
  args: { initialState: { lens: 'depth', card: 'compact' } },
  parameters: about('Card size Compact on the Depth lens: a status dot and the rung id.'),
}
export const RichCards: Story = {
  name: 'Rich cards (Depth)',
  args: { initialState: { lens: 'depth', card: 'rich' } },
  parameters: about('Card size Rich on the Depth lens: art (catalog renders served from stories/fixtures/art, else an icon), title and the status line.'),
}
export const TopDown: Story = {
  name: 'Top down (Ladder ↓)',
  args: { initialState: { lens: 'ladder', orient: 'td' } },
  parameters: about('Direction ↓ on the Ladder lens.'),
}
