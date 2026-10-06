import type { Meta, StoryObj } from '@storybook/react-vite'
import { VariantAHarness } from '../harness'

const meta = {
  title: 'Dashboard/Variant A',
  component: VariantAHarness,
  tags: ['autodocs'],
  parameters: {
    docs: {
      description: {
        component:
          'Variant A, "Drill-down pages" (src/variants/a/index.tsx), mounted as Dashboard.tsx mounts it: the projection through useProjection from the captured /projection (stories/fixtures/projection.json), and each track\'s roadmap through useRoadmap from stories/fixtures/roadmap/<track>.json. The route lives in story state, so clicking a row or a breadcrumb navigates inside the story.',
      },
    },
  },
} satisfies Meta<typeof VariantAHarness>

export default meta
type Story = StoryObj<typeof meta>

export const TracksPage: Story = {
  name: 'Tracks page (L1)',
  args: { initialRoute: {} },
  parameters: {
    docs: {
      description: {
        story:
          'src/variants/a/TracksPage.tsx: one row per work track, with the Progress cell\'s "· N proven" and the roadmap calm answer in the rung cell. Fixtures stories/fixtures/projection.json and stories/fixtures/roadmap/*.json (pyblocks answers the captured 404).',
      },
    },
  },
}

export const TrackPageKinsim: Story = {
  name: 'Track page · kinsim (L2)',
  args: { initialRoute: { track: 'kinsim' } },
  parameters: {
    docs: {
      description: {
        story:
          'src/variants/a/TrackPage.tsx for kinsim: state line, north star with "· N proven", the KPI rows (Scorecard.tsx) and the Roadmap section at its calm head (Expand opens the board). Fixtures stories/fixtures/projection.json and stories/fixtures/roadmap/kinsim.json.',
      },
    },
  },
}

export const TrackPageKinsimRoadmapOpen: Story = {
  name: 'Track page · kinsim, roadmap expanded',
  args: { initialRoute: { track: 'kinsim', rmopen: '1' } },
  parameters: {
    docs: {
      description: {
        story:
          'The same page with the Roadmap section expanded (route key rmopen=1): the full board in place under the KPI rows. Fixtures stories/fixtures/projection.json and stories/fixtures/roadmap/kinsim.json.',
      },
    },
  },
}
