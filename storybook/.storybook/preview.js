// The home's real files, unchanged, in index.html's order. app.js (the boot and the 10 s poll) is left out on
// purpose: lib/home.js mounts pages per story instead.
// WHY side-effect imports work: every home file is a 'use strict' IIFE that publishes only through window.VT, so an
// ES-module import runs it exactly as index.html's classic <script> does. Keep that shape: a top-level declaration
// meant as a global would work on the page and break here (or the other way round).
import '@home/tokens.css';
import '@home/home.css';
import '@home/pages.css';
import '@home/core.js';
import '@home/rename.js';
import '@home/sidebar.js';
import '@home/views.js';
import '@home/review.js';
import '@home/project.js';
import '@home/track.js';
// The shared viz parts (not loaded by the home yet): the map engine's CSS, the viz tokens and styles, <vt-map>.
import 'maplibre-gl/dist/maplibre-gl.css';
import '@home/viz.css';
import '@home/vt-map.js';
import '@home/kpi-panel.js';
// WHY the worker URL is set here: MapLibre derives its worker from its own file's URL, which a bundler renames.
// The vanilla home (vendored files side by side) needs no such line.
import { setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import './preview.css';
import { releaseClock } from '../lib/home.js';

setWorkerUrl(workerUrl);

export default {
  parameters: {
    layout: 'fullscreen',
    // Accessibility is a gate, not a report: axe violations fail `npm test`. A story may say 'todo' only with a reason.
    a11y: { test: 'error' },
    backgrounds: { disable: true },
  },
  globalTypes: {
    theme: { description: 'Theme (html[data-theme], as the home\'s own setting)', toolbar: { title: 'Theme', items: ['dark', 'light'], dynamicTitle: true } },
    data: { description: 'Fixture set: real (captured read-only from Stable, local only) or synthetic (committed)', toolbar: { title: 'Data', items: ['real', 'synthetic'], dynamicTitle: true } },
  },
  initialGlobals: { theme: 'dark', data: 'real' },
  decorators: [
    (story, ctx) => {
      const theme = ctx.globals.theme || 'dark';
      document.documentElement.dataset.theme = theme;
      if (!ctx.parameters.home) releaseClock();
      return story();
    },
  ],
};
