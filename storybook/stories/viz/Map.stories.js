// <vt-map> (vibetracks/home/static/vt-map.js): the one map component, built once. Every play MEASURES what was
// drawn: pixels read back from the WebGL canvas against the viz tokens, fitted bounds, the breadcrumb's text.
import { expect } from 'storybook/test';
import { mountMap, mapOf, ready, pixelAt, near, colorIs, colorAround, until } from './_map.js';
import { cesiRows, bcRows, LEVELS, DIVERSION, BOUNDARY_NOTE, ILLUSTRATIVE_SITES } from './data.js';

export default { title: 'Viz/Map', parameters: { home: false } };

const PUBLIC = () => cesiRows().concat(bcRows());
const spec = (extra) => Object.assign({ metric: DIVERSION, levels: LEVELS, values: PUBLIC(), sources: [BOUNDARY_NOTE] }, extra);
// interior points, away from borders
const AT = { BC: [-123.5, 54.5], NT: [-119, 64], NS: [-63.3, 45.2], AB: [-114.5, 54.5], CAN: [-100, 58], FRA: [2.5, 46.6],
  METRO: [-122.95, 49.25], PEACE: [-121.5, 56.5] };
const click = (el, lonlat) => {
  const c = el.map.getCanvas(), r = c.getBoundingClientRect(), p = el.map.project(lonlat);
  const o = { bubbles: true, cancelable: true, clientX: r.left + p.x, clientY: r.top + p.y, button: 0 };
  c.dispatchEvent(new MouseEvent('mousedown', o)); c.dispatchEvent(new MouseEvent('mouseup', o)); c.dispatchEvent(new MouseEvent('click', o));
};
const keyAt = (el, lonlat) => (el.map.queryRenderedFeatures(el.map.project(lonlat), { layers: ['vtm-fill'] })[0] || { properties: {} }).properties.key;

/** Story (a): real public data. ECCC's provincial diversion rate, 2022 (2002 one click away). */
export const DiversionByProvince = {
  name: 'Diversion by province · ECCC CESI 2022',
  render: () => mountMap(spec({ view: { level: 'province', focus: 'CAN' } })),
  play: async ({ canvasElement }) => {
    const el = await ready(mapOf(canvasElement));
    await expect(el.dataset.renderer).toBe('gl');
    await expect([el.dataset.level, el.dataset.focus, el.dataset.period]).toEqual(['province', 'CAN', '2022']);
    // BC 38.4 % sits in the 20–40 class; Nova Scotia 42.9 % in 40–60; Alberta 19.6 % below 20: the pixel is the class
    await expect(keyAt(el, AT.BC)).toBe('CA-BC');
    // the high Arctic is inside the frame: Canada's northernmost land (Ellesmere, 83.1° N) is not cropped at the top edge
    const north = el.map.getBounds().getNorth(), top = el.map.project([-75, 83.1]).y;
    await expect(north).toBeGreaterThan(83.1);
    await expect(top).toBeGreaterThan(0);
    await expect(colorIs(el, AT.BC, '--viz-seq-2')).toBe(true);
    await expect(colorAround(el, AT.NS, '--viz-seq-3')).toBe(true);
    await expect(colorIs(el, AT.AB, '--viz-seq-1')).toBe(true);
    // the territories are suppressed in the source (n/a): drawn as No data, never as the lowest class (and never 0)
    await expect(keyAt(el, AT.NT)).toBe('CA-NT');
    await expect(colorIs(el, AT.NT, '--viz-nodata')).toBe(true);
    // PEI too, too small to sample at this zoom: its table row says so
    el.querySelector('.vtm-tbtn').click();
    await expect(el.querySelector('.vtm-table tr[data-key="CA-PE"]').textContent).toMatch(/No data/);
    el.querySelector('.vtm-tbtn').click();
    // the legend says which classes are on the map, plus No data and the 100 % goal
    await expect(el.querySelector('.vtm-step[data-class="nodata"]')).not.toBeNull();
    await expect(el.querySelector('.vtm-goal').textContent).toMatch(/100% circularity/);
    // 2002 is one click away: Nova Scotia was 33 % then, still the 20–40 class, BC 31.2 %
    el.querySelector('.vtm-period button[data-period="2002"]').click();
    await until(() => el.dataset.period === '2002' && el.dataset.state === 'ready', 'period 2002');
    await el.whenReady();
    await expect(colorAround(el, AT.NS, '--viz-seq-2')).toBe(true);
  },
};

/** Drill-down: World → Canada → British Columbia (its waste reporting units), and back up by the breadcrumb. */
export const DrillDown = {
  name: 'Drill-down · World → Canada → BC',
  render: () => mountMap(spec({ view: { level: 'country' } })),
  play: async ({ canvasElement }) => {
    const el = await ready(mapOf(canvasElement));
    // the world level: only Canada has a value from this source (27.1 %); France has none, so it is No data
    await expect(colorIs(el, AT.CAN, '--viz-seq-2')).toBe(true);
    await expect(colorIs(el, AT.FRA, '--viz-nodata')).toBe(true);
    const crumb = () => [...el.querySelectorAll('.vtm-crumb > *:not([aria-hidden])')].map((n) => n.textContent).join(' / ');
    await expect(crumb()).toBe('World');
    const drills = [];
    el.addEventListener('vt-map-drill', (e) => drills.push(e.detail));
    click(el, AT.CAN);
    await until(() => el.dataset.level === 'province' && el.dataset.state === 'ready', 'the province level');
    await el.whenReady();
    await expect(crumb()).toBe('World / Canada');
    await expect(drills[0]).toEqual({ from: 'country', to: 'province', focus: 'CAN' });
    const zoomCanada = el.map.getZoom();
    // centred on Canada, not pinned to 0° (MapLibre pins the centre when the world is narrower than the canvas)
    await expect(el.map.getCenter().lng).toBeLessThan(-60);
    click(el, AT.BC);
    await until(() => el.dataset.level === 'district' && el.dataset.state === 'ready', 'BC\'s districts');
    await el.whenReady();
    await expect(crumb()).toBe('World / Canada / British Columbia');
    // fitted to BC: the camera centre sits inside BC and the zoom is deeper than Canada's
    const ctr = el.map.getCenter();
    await expect(ctr.lng > -135 && ctr.lng < -114 && ctr.lat > 48 && ctr.lat < 60).toBe(true);
    await expect(el.map.getZoom()).toBeGreaterThan(zoomCanada);
    // a different measure below the province: the legend and footer say so
    await expect(el.querySelector('.vtm-legend .lt').textContent).toMatch(/disposed per person/);
    await expect(el.querySelector('.vtm-foot').textContent).toMatch(/different measure/i);
    // back up one level by the breadcrumb
    el.querySelector('.vtm-crumb button[data-level="1"]').click();
    await until(() => el.dataset.level === 'province' && el.dataset.state === 'ready', 'back to provinces');
    await expect(crumb()).toBe('World / Canada');
  },
};

/** BC's districts over 35 years: a slider when there are many periods. Lower is better here. */
export const DisposalByDistrict = {
  name: 'BC districts · disposal per person 1990–2024',
  render: () => mountMap(spec({ view: { level: 'district', focus: 'CA-BC' } })),
  play: async ({ canvasElement }) => {
    const el = await ready(mapOf(canvasElement));
    await expect(el.dataset.period).toBe('2024');
    await expect(keyAt(el, AT.METRO)).toBe('Metro-Vancouver');
    // Metro Vancouver 422 kg/person in 2024 → the 400–500 class; Peace River 763 → ≥ 700
    await expect(colorIs(el, AT.METRO, '--viz-seq-2')).toBe(true);
    await expect(colorIs(el, AT.PEACE, '--viz-seq-5')).toBe(true);
    // Central Coast reports 0 t for 2024: shown as No data with the reason in the table, never as 0 kg
    el.querySelector('.vtm-tbtn').click();
    const cc = await until(() => el.querySelector('.vtm-table tr[data-key="Central Coast"]'), 'the Central Coast row');
    await expect(cc.textContent).toMatch(/No data/);
    await expect(cc.textContent).toMatch(/missing report/);
    // slide to 2010: Metro Vancouver's class changes with the data
    const range = el.querySelector('.vtm-period input[type=range]');
    const i2010 = [...Array(+range.max + 1).keys()].find((i) => el._periods[i] === '2010');
    range.value = String(i2010);
    range.dispatchEvent(new Event('input', { bubbles: true }));
    await until(() => el.dataset.period === '2010' && el.dataset.state === 'ready', 'period 2010');
    await el.whenReady();
    const row = bcRowsFor('Metro-Vancouver', '2010');
    const cls = row.value >= 700 ? 5 : row.value >= 600 ? 4 : row.value >= 500 ? 3 : row.value >= 400 ? 2 : 1;
    await expect(colorIs(el, AT.METRO, `--viz-seq-${cls}`)).toBe(true);
  },
};
const bcRowsFor = (key, period) => bcRows().find((r) => r.key === key && r.period === period);

/** Story (b): BAM's sites as points, ILLUSTRATIVE (BAM has no deployed site yet), over Metro Vancouver. */
export const SitesIllustrative = {
  name: 'BAM sites · illustrative points',
  render: () => mountMap(spec({ view: { level: 'district', focus: 'CA-BC', bounds: [-123.9, 48.25, -122.3, 49.55] }, points: ILLUSTRATIVE_SITES,
    pointsLabel: 'BAM sites (illustrative)', pointsNote: 'Illustrative: BAM has no deployed site yet (Oct 2026). Positions and statuses are made up to show the layer.' })),
  play: async ({ canvasElement }) => {
    const el = await ready(mapOf(canvasElement));
    const site = ILLUSTRATIVE_SITES[0];
    const hit = el.map.queryRenderedFeatures(el.map.project([site.lon, site.lat]), { layers: ['vtm-pt'] })[0];
    await expect(hit && hit.properties.id).toBe(site.id);
    // its status colour, measured at its centre (status "ok" → --viz-good)
    await expect(colorIs(el, [site.lon, site.lat], '--viz-good', 10)).toBe(true);
    const picked = [];
    el.addEventListener('vt-map-select', (e) => picked.push(e.detail));
    click(el, [site.lon, site.lat]);
    await until(() => picked.length, 'the select event');
    await expect(picked[0]).toMatchObject({ kind: 'point', id: site.id });
    await expect(el.querySelector('.vtm-foot').textContent).toMatch(/Illustrative/);
    await expect(el.querySelector('.vtm-sites').textContent).toMatch(/illustrative/);
  },
};

/** Story (c): BAM's own diversion by city: nothing measured yet, so every region is No data and the map says why. */
export const NotMeasured = {
  name: 'BAM diversion · not measured yet',
  render: () => mountMap({ metric: Object.assign({}, DIVERSION, { label: 'Material diverted at BAM sites' }), levels: [LEVELS[0], LEVELS[1], Object.assign({}, LEVELS[2], { metric: null })],
    values: [], view: { level: 'district', focus: 'CA-BC' }, sources: [BOUNDARY_NOTE],
    empty: { title: 'Not measured yet', hint: 'BAM has no deployed site. To draw this, record per site and month: tonnes received, tonnes leaving in accepted bales, tonnes sent to disposal (weigh-scale tickets).' } }),
  play: async ({ canvasElement }) => {
    const el = await ready(mapOf(canvasElement));
    await expect(el.dataset.empty).toBe('1');
    await expect(el.querySelector('.vtm-empty').hidden).toBe(false);
    await expect(el.querySelector('.vtm-empty').textContent).toMatch(/Not measured yet/);
    await expect(colorIs(el, AT.METRO, '--viz-nodata')).toBe(true);
    await expect(el.querySelector('.vtm-period').children.length).toBe(0);
  },
};

/** No WebGL: the same values as a table, drill-down included (also the keyboard and screen-reader path). */
export const TableFallback = {
  name: 'No WebGL · table',
  render: () => mountMap(spec({ view: { level: 'province', focus: 'CAN' } }), { renderer: 'table' }),
  play: async ({ canvasElement }) => {
    const el = await ready(mapOf(canvasElement));
    await expect(el.dataset.renderer).toBe('table');
    await expect(el.map).toBeNull();
    const rows = el.querySelectorAll('.vtm-table tbody tr');
    await expect(rows.length).toBe(13);
    await expect(el.querySelector('tr[data-key="CA-PE"]').textContent).toMatch(/No data/);
    await expect(el.querySelector('tr[data-key="CA-BC"]').textContent).toMatch(/38\.4%/);
    el.querySelector('tr[data-key="CA-BC"] button').click();
    await until(() => el.dataset.level === 'district' && el.querySelectorAll('.vtm-table tbody tr').length === 28, 'BC\'s 28 waste reporting units');
  },
};

/** Theme: the map follows html[data-theme] live (paint can't read CSS variables, so it re-reads the tokens). */
export const ThemeFollows = {
  name: 'Theme flip repaints',
  render: () => mountMap(spec({ view: { level: 'province', focus: 'CAN' } })),
  play: async ({ canvasElement }) => {
    const el = await ready(mapOf(canvasElement));
    const html = document.documentElement, was = html.dataset.theme;
    const before = pixelAt(el, ...AT.BC);
    html.dataset.theme = was === 'light' ? 'dark' : 'light';
    try {
      await until(() => !near(pixelAt(el, ...AT.BC), before, 2), 'a repaint after the theme flip');
      await expect(colorIs(el, AT.BC, '--viz-seq-2')).toBe(true);
    } finally {
      html.dataset.theme = was;
    }
  },
};
