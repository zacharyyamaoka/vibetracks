// Storybook for the Vibe Tracks dashboard's React components, one at a time (stories/**). Run from clank/:
// `npm run storybook` serves http://127.0.0.1:6006 without opening a browser; `npm run build-storybook` builds the
// static site to storybook-static/ (gitignored).
// WHY the stories live in stories/ and not beside the components: src/variants/** and src/needs/** belong to another
// lane, and a story file there would be an edit to its folder; stories only import from src/.
// WHY React's plugin is added here: @storybook/react-vite adds docgen but no JSX transform of its own, and this package
// has no vite.config (Clank's build compiles it inside the host); @vitejs/plugin-react is the version Clank's build uses.

import { existsSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import type { StorybookConfig } from '@storybook/react-vite'
import { mergeConfig } from 'vite'

// The captured art (stories/fixtures/README.md). WHY looked up here: the fixtures are local only and may be absent,
// and Storybook refuses to start on a staticDirs entry that does not exist; the stories learn which PNGs exist from
// STORY_ART_FILES and say "Fixture missing" instead of drawing broken images. A new capture needs a Storybook restart.
const ART_DIR = fileURLToPath(new URL('../stories/fixtures/art', import.meta.url))
const ART_FILES = existsSync(ART_DIR) ? readdirSync(ART_DIR).filter((name) => name.endsWith('.png')).sort() : []

const config: StorybookConfig = {
  stories: ['../stories/**/*.stories.@(ts|tsx)'],
  framework: { name: '@storybook/react-vite', options: {} },
  // WHY the art is served at the backend's own path: an <img> on a rich card loads `${backend.baseUrl}/roadmap/art/<name>`
  // (roadmap/art.tsx), and the fixture backend's baseUrl is the one Clank gives the plugin, so the real URLs resolve.
  staticDirs: existsSync(ART_DIR) ? [{ from: '../stories/fixtures/art', to: '/api/plugins/vibetracks/roadmap/art' }] : [],
  core: { disableTelemetry: true },
  async viteFinal(viteConfig) {
    return mergeConfig(viteConfig, {
      plugins: [react()],
      define: { 'import.meta.env.STORY_ART_FILES': JSON.stringify(ART_FILES) },
      // One React: the components run inside Clank's React in production, and two copies break hooks.
      resolve: { dedupe: ['react', 'react-dom', 'lucide-react'] },
    })
  },
}

export default config
