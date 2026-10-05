import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import { fixturesForTrack } from '../backend'
import { RoadmapHarness } from '../harness'

const FIXTURE = 'stories/fixtures/roadmap/kinsim.json'

const meta = {
  title: 'Roadmap/Focus card',
  component: RoadmapHarness,
  tags: ['autodocs'],
  args: { track: 'kinsim', density: 'full', onOpenRung: fn(), onOpenEvidence: fn() },
  parameters: {
    fixtures: (args: { track?: unknown }) => fixturesForTrack(String(args.track)),
    docs: {
      description: {
        component:
          `FocusPanel (src/roadmap/FocusPanel.tsx), open on a picked rung inside the full board it grows out of (it measures its anchor card, so it is shown in place, not alone). Fixture ${FIXTURE}; the proof tab's run renders come from stories/fixtures/art.`,
      },
    },
  },
} satisfies Meta<typeof RoadmapHarness>

export default meta
type Story = StoryObj<typeof meta>

const about = (what: string) => ({ docs: { description: { story: `${what} Source src/roadmap/FocusPanel.tsx; fixture ${FIXTURE}.` } } })

export const ProofBT1: Story = {
  name: 'Proof · BT1',
  args: { initialState: { lens: 'ladder', sel: 'BT1', tab: 'proof' } },
  parameters: about('BT1 picked, Proof tab: the loop\'s claim, the judged evidence and the latest run.'),
}
export const ProofRB0: Story = {
  name: 'Proof · RB0',
  args: { initialState: { lens: 'ladder', sel: 'RB0', tab: 'proof' } },
  parameters: about('RB0 picked, Proof tab.'),
}
export const LineageBT1: Story = {
  name: 'Lineage · BT1',
  args: { initialState: { lens: 'depth', sel: 'BT1', tab: 'lineage' } },
  parameters: about('BT1 picked on the Depth lens, Lineage tab: what it needs and what it unlocks, lines lit.'),
}
export const DetailsBT1: Story = {
  name: 'Details · BT1',
  args: { initialState: { lens: 'ladder', sel: 'BT1', tab: 'details' } },
  parameters: about('BT1 picked, Details tab: done-when, criteria, KPIs, notes.'),
}
export const ProofBT1Rich: Story = {
  name: 'Proof · BT1 (rich cards)',
  args: { initialState: { lens: 'ladder', card: 'rich', sel: 'BT1', tab: 'proof' } },
  parameters: about('BT1 picked with Rich cards.'),
}
