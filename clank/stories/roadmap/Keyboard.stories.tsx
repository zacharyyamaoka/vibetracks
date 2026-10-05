import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, userEvent, waitFor, within } from 'storybook/test'
import { fixturesForTrack } from '../backend'
import { FIXTURE_MISSING_TESTID } from '../decorators'
import { RoadmapHarness } from '../harness'

const FIXTURE = 'stories/fixtures/roadmap/kinsim.json'

const meta = {
  title: 'Roadmap/Keyboard',
  component: RoadmapHarness,
  tags: ['autodocs'],
  args: { track: 'kinsim', density: 'full', initialState: { lens: 'ladder' }, onOpenRung: fn(), onOpenEvidence: fn() },
  parameters: {
    fixtures: (args: { track?: unknown }) => fixturesForTrack(String(args.track)),
    docs: {
      description: {
        component:
          `The board (src/roadmap/RoadmapBoard.tsx) is focusable (tabIndex 0): click it or Tab to it, then the arrow keys move the selection between rungs and Esc closes the focus card. Fixture ${FIXTURE}.`,
      },
    },
  },
} satisfies Meta<typeof RoadmapHarness>

export default meta
type Story = StoryObj<typeof meta>

const selected = (root: HTMLElement) => root.querySelector<HTMLElement>('[data-testid="vt-roadmap-canvas"] [data-role="sel"]')

/** Focus the board, step right twice, check that the selection and DOM focus both moved, then close with Esc. */
export const ArrowKeys: Story = {
  name: 'Arrow keys (played)',
  parameters: { docs: { description: { story: `The play function focuses the board, presses → twice and Esc, and asserts the selection and focus follow. Fixture ${FIXTURE}.` } } },
  play: async ({ canvasElement }) => {
    // Without captured fixtures the story is the one "Fixture missing" line; there is no board to drive.
    if (canvasElement.querySelector(`[data-testid="${FIXTURE_MISSING_TESTID}"]`)) return
    const canvas = within(canvasElement)
    const board = await canvas.findByTestId('vt-roadmap-canvas', {}, { timeout: 15_000 })
    board.focus()
    await expect(document.activeElement).toBe(board)
    await userEvent.keyboard('{ArrowRight}')
    await waitFor(() => expect(selected(canvasElement)).not.toBeNull())
    const first = selected(canvasElement)!.dataset.rung
    await userEvent.keyboard('{ArrowRight}')
    await waitFor(() => expect(selected(canvasElement)?.dataset.rung).not.toBe(first))
    const second = selected(canvasElement)!.dataset.rung
    await waitFor(() => expect((document.activeElement as HTMLElement | null)?.dataset.rung).toBe(second))
    await expect(canvas.getByTestId('vt-roadmap-focus')).toBeVisible()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(canvas.queryByTestId('vt-roadmap-focus')).toBeNull())
  },
}

/** The board alone, unplayed: focus it yourself and use the arrow keys. */
export const TryIt: Story = {
  name: 'Try it (unplayed)',
  parameters: { docs: { description: { story: `Click the board (or Tab to it) and use the arrow keys. Fixture ${FIXTURE}.` } } },
}
