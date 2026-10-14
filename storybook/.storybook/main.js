// The Vibe Tracks storyboard (Zach, Oct 10: "start a storyboard so we can ensure we are taking a component based
// approach … get the map working once and then we can reuse it"). Storybook 10 with the html renderer, because the
// home is plain strings and DOM (vibetracks/home/static), and a story renders exactly that: the real files, loaded
// unchanged, no React wrapper, no copy. The React Clank plugin keeps its own Storybook (clank/.storybook, :6006).
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(here, '../..');
const HOME = join(REPO, 'vibetracks/home/static');

// Anthropic Sans, from the same local folders vibetracks/home/api.py reads (FONT_DIRS). WHY never committed: the face
// is Anthropic's, extracted from Claude Desktop on this machine; without a copy the page falls back to system-ui,
// exactly like the live home.
const FONT_DIRS = [process.env.VIBETRACKS_HOME_FONT_DIR || '', join(process.env.HOME || '', '.local/share/vibetracks/fonts'),
  '/home/bam/claude-transcript-viewer/web/public/fonts', '/home/bam/claude-hub-sidebar/app/public/fonts'];
const FONTS = { 'anthropic-sans.woff2': 'DDVos-BJ.woff2', 'anthropic-sans-italic.woff2': 'CJtkx3-S.woff2' };
function fontFile(name) {
  for (const dir of FONT_DIRS) {
    if (!dir || !existsSync(dir)) continue;
    if (existsSync(join(dir, name))) return join(dir, name);
    const hit = readdirSync(dir).find((f) => f.endsWith('-' + FONTS[name]));
    if (hit) return join(dir, hit);
  }
  return null;
}
/** Serves /font/<name> in dev and emits font/<name> in the build: tokens.css asks for ../font/<name>. */
function homeFonts() {
  return {
    name: 'vt-home-fonts',
    configureServer(server) {
      server.middlewares.use('/font/', (req, res, next) => {
        const name = decodeURIComponent((req.url || '').split('?')[0].replace(/^\//, ''));
        const file = FONTS[name] ? fontFile(name) : null;
        if (!file) return next();
        res.setHeader('Content-Type', 'font/woff2');
        res.end(readFileSync(file));
      });
    },
    generateBundle() {
      for (const name of Object.keys(FONTS)) {
        const file = fontFile(name);
        if (file) this.emitFile({ type: 'asset', fileName: `font/${name}`, source: readFileSync(file) });
      }
    },
  };
}

export default {
  stories: ['../stories/**/*.stories.js'],
  framework: { name: '@storybook/html-vite', options: {} },
  addons: ['@storybook/addon-a11y', '@storybook/addon-vitest'],
  core: { disableTelemetry: true },
  // Optional: show the React Clank plugin's Storybook in the same sidebar (only when it runs; a dead ref is an error).
  refs: process.env.VT_SB_REFS === '1' ? { clank: { title: 'Clank plugin (React)', url: 'http://127.0.0.1:6006' } } : {},
  async viteFinal(config) {
    const { mergeConfig } = await import('vite');
    return mergeConfig(config, {
      // WHY dedupe: vt-map.js lives in the home's folder, outside this package, so 'maplibre-gl' must resolve from here.
      resolve: { alias: { '@home': HOME }, dedupe: ['maplibre-gl'] },
      server: { fs: { allow: [HOME, here, resolve(here, '..')] } },
      plugins: [homeFonts()],
    });
  },
};
