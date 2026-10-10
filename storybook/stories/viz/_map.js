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
