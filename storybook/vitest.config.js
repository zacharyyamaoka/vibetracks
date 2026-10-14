// `npm test`: every story renders in headless Chromium, every play function runs, and axe runs at 'error'.
// The browser is Playwright's cached chromium (PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 at install).
import { defineConfig } from 'vitest/config';
import { storybookTest } from '@storybook/addon-vitest/vitest-plugin';
import { playwright } from '@vitest/browser-playwright';

export default defineConfig({
  test: {
    projects: [{
      extends: true,
      plugins: [storybookTest({ configDir: '.storybook' })],
      test: {
        name: 'storybook',
        testTimeout: 30000,
        browser: { enabled: true, headless: true, provider: playwright(), instances: [{ browser: 'chromium', viewport: { width: 1280, height: 800 } }] },
      },
    }],
  },
});
