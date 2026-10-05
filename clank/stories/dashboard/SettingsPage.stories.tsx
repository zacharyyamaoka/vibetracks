import type { Meta, StoryObj } from '@storybook/react-vite'
import { SettingsPageHarness } from '../harness'

const meta = {
  title: 'Dashboard/Settings page',
  component: SettingsPageHarness,
  tags: ['autodocs'],
  parameters: {
    fixtures: [],
    docs: {
      description: {
        component:
          'The settings page the header gear opens (src/shared/SettingsView.tsx) with both sections Dashboard.tsx passes: DASHBOARD_SETTINGS_SECTION (src/shared/settings.ts) and ROADMAP_SETTINGS_SECTION (src/roadmap/settings.ts). Values live in story state, not localStorage. No fixture.',
      },
    },
  },
} satisfies Meta<typeof SettingsPageHarness>

export default meta
type Story = StoryObj<typeof meta>

export const Defaults: Story = {}
