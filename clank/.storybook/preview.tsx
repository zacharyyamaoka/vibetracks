import type { Preview } from '@storybook/react-vite'
import { withDashboardFrame } from '../stories/decorators'

const preview: Preview = {
  decorators: [withDashboardFrame],
  parameters: {
    // WHY fullscreen: the frame is the dashboard's own `.vt-dash` scroller and pages carry their own padding.
    layout: 'fullscreen',
    options: { storySort: { order: ['Roadmap', ['Calm head', 'Full board', 'Focus card', 'Freshness', 'Settings', 'Keyboard'], 'Dashboard'] } },
  },
}

export default preview
