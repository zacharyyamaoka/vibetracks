import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, within } from 'storybook/test'
import { fixturesForTrack } from '../backend'
import { FIXTURE_MISSING_TESTID } from '../decorators'
import { RoadmapSettingsHarness } from '../harness'

const FIXTURE = 'stories/fixtures/roadmap/kinsim.json'

const meta = {
  title: 'Roadmap/Settings',
  component: RoadmapSettingsHarness,
  tags: ['autodocs'],
  // WHY no picked rung: a picked rung opens the focus card and the board brings it into view, which scrolled the page
  // past the settings section on first paint. With none picked, the Depth lens still draws every dependency line.
  args: { track: 'kinsim', initialState: { lens: 'depth' }, onOpenRung: fn(), onOpenEvidence: fn() },
  play: async ({ canvasElement }) => {
    if (canvasElement.querySelector(`[data-testid="${FIXTURE_MISSING_TESTID}"]`)) return
    const canvas = within(canvasElement)
    await canvas.findByTestId('vt-roadmap-canvas', {}, { timeout: 15_000 })
    const scroller = canvasElement.ownerDocument.querySelector<HTMLElement>('.vt-scroll')!
    const section = canvas.getByTestId('vt-settings-section-roadmap')
    // WHY watch for a while and not read once: the scroll this guards against was a smooth scroll that starts after
    // the board's mount (measured: a single read two frames in still saw 0 with a rung picked). Any scroll at all in
    // the first 2 s after the board appears fails the story.
    let furthest = scroller.scrollTop
    const onScroll = () => { furthest = Math.max(furthest, scroller.scrollTop) }
    scroller.addEventListener('scroll', onScroll)
    await new Promise((resolve) => setTimeout(resolve, 2000))
    scroller.removeEventListener('scroll', onScroll)
    await expect(Math.max(furthest, scroller.scrollTop)).toBe(0)
    const box = section.getBoundingClientRect()
    const view = scroller.getBoundingClientRect()
    // The whole Roadmap settings section is inside the scroller's visible box.
    await expect(box.top).toBeGreaterThanOrEqual(view.top)
    await expect(box.bottom).toBeLessThanOrEqual(view.bottom)
    await expect(box.height).toBeGreaterThan(0)
  },
  parameters: {
    fixtures: (args: { track?: unknown }) => fixturesForTrack(String(args.track)),
    docs: {
      description: {
        component:
          `The Roadmap section of the settings page (ROADMAP_SETTINGS_SECTION in src/roadmap/settings.ts, drawn by src/shared/SettingsView.tsx), live above the board it governs (src/roadmap/RoadmapBoard.tsx, Depth lens, which draws every dependency line). The play function measures that the settings section is fully visible at first paint. Change "Lines" and the board redraws. Fixture ${FIXTURE}.`,
      },
    },
  },
} satisfies Meta<typeof RoadmapSettingsHarness>

export default meta
type Story = StoryObj<typeof meta>

export const CurvedLines: Story = {
  name: 'Lines · Curved',
  args: { initialEdges: 'curve' },
  parameters: { docs: { description: { story: `Lines: Curved (the default). Fixture ${FIXTURE}.` } } },
}
export const ElbowLines: Story = {
  name: 'Lines · Elbow',
  args: { initialEdges: 'elbow' },
  parameters: { docs: { description: { story: `Lines: Elbow. Fixture ${FIXTURE}.` } } },
}
