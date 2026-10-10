// Helpers for the map stories: mount a <vt-map>, and MEASURE what it drew (pixels, not DOM presence).
import { until } from '../../lib/home.js';

export { until };
export function mountMap(spec, attrs, frameStyle) {
  const wrap = document.createElement('div');
  wrap.className = 'sb-pad';
  wrap.style.cssText = frameStyle || 'max-width: 1000px';
  const el = document.createElement('vt-map');
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  el.spec = spec;
  wrap.append(el);
  return wrap;
}
export const mapOf = (root) => root.querySelector('vt-map');
export async function ready(el, what = 'the map') {
  await until(() => el.dataset.state === 'ready' || el.dataset.state === 'error', what, 20000);
  if (el.dataset.state === 'error') throw new Error(el.querySelector('.vtm-note').textContent);
  await el.whenReady();
  return el;
}
/** The rendered colour at a lon/lat, read back from the WebGL canvas (preserveDrawingBuffer is on). */
export function pixelAt(el, lon, lat) {
  const map = el.map, gl = map.getCanvas();
  const p = map.project([lon, lat]);
  const k = gl.width / gl.clientWidth;
  const c = document.createElement('canvas');
  c.width = gl.width; c.height = gl.height;
  const g = c.getContext('2d');
  g.drawImage(gl, 0, 0);
  const d = g.getImageData(Math.round(p.x * k), Math.round(p.y * k), 1, 1).data;
  return [d[0], d[1], d[2]];
}
export function tokenRGB(el, name) {
  const hex = getComputedStyle(el).getPropertyValue(name).trim().replace('#', '');
  return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
}
export const near = (a, b, tol = 6) => a.every((v, i) => Math.abs(v - b[i]) <= tol);
/** Throws with both colours when the pixel at lon/lat is not the token's colour. */
export function colorIs(el, lonlat, token, tol = 6) {
  const got = pixelAt(el, lonlat[0], lonlat[1]), want = tokenRGB(el, token);
  if (!near(got, want, tol)) throw new Error(`pixel at ${lonlat} is rgb(${got}) but ${token} is rgb(${want})`);
  return true;
}

/** REAL input for a play function: Chromium's own mouse and keyboard through the browser-mode provider (CDP), not
 *  `.value =` and synthetic events. Resolves null where there is no Vitest browser (the Storybook UI), so the story
 *  still renders there and can be driven by hand; under Vitest a failed import is an error, never a silent pass.
 *  WHY: the period slider shipped a drag bug (the control was rebuilt on every update) that every synthetic test missed. */
export async function realInput() {
  let browser;
  try { browser = await import('vitest/browser'); } catch (e) {
    if (globalThis.__vitest_browser__ || (import.meta.env && import.meta.env.VITEST)) throw e;
    return null;
  }
  const { userEvent, cdp } = browser;
  // the story runs in an iframe of the Vitest page, CDP coordinates are the top page's: offset and scale by the frame
  const toPage = (x, y) => {
    const f = window.frameElement, r = f ? f.getBoundingClientRect() : { left: 0, top: 0, width: innerWidth };
    const k = f && f.clientWidth ? r.width / f.clientWidth : 1;
    return { x: r.left + x * k, y: r.top + y * k };
  };
  const send = (type, x, y, extra) => cdp().send('Input.dispatchMouseEvent', Object.assign({ type, ...toPage(x, y), button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1 }, extra));
  let at = { x: 0, y: 0 };
  return {
    userEvent,
    /** Moves the real pointer to viewport (x, y) in `steps` mouse moves; the button state is kept. */
    async move(x, y, steps = 1, held = false) {
      for (let i = 1; i <= steps; i++) {
        const px = at.x + ((x - at.x) * i) / steps, py = at.y + ((y - at.y) * i) / steps;
        await send('mouseMoved', px, py, { buttons: held ? 1 : 0 });
        await new Promise((r) => requestAnimationFrame(r));
      }
      at = { x, y };
    },
    async down() { await send('mousePressed', at.x, at.y); },
    async up() { await send('mouseReleased', at.x, at.y); },
    async click(x, y) { await this.move(x, y); await this.down(); await this.up(); },
    /** Viewport position of a lon/lat on the map's canvas. */
    lonLat(el, lonlat) {
      const r = el.map.getCanvas().getBoundingClientRect(), p = el.map.project(lonlat);
      return [r.left + p.x, r.top + p.y];
    },
  };
}
