// Builds the map's boundary files (vibetracks/home/static/geo-*.json) and refreshes the open waste data the map
// stories show (fixtures/public/). Downloads go to .geo-cache/ (gitignored); outputs are small simplified GeoJSON.
//
//   node /home/bam/vibetracks-storybook/storybook/scripts/build_geo.mjs            (uses the cache when present)
//   node /home/bam/vibetracks-storybook/storybook/scripts/build_geo.mjs --refresh  (downloads everything again)
//
// Sources and licences (every one commercially usable; noted in each output's sidecar and the map's footer):
//   Natural Earth 5.1.2 admin-0 110m countries, admin-1 50m states/provinces: public domain.
//   BC regional districts + Northern Rockies Regional Municipality (BC Data Catalogue, ABMS, WFS): OGL-BC.
//   ECCC CESI solid waste diversion, figure 5 (2002, 2022): Open Government Licence – Canada.
//   BC Municipal Solid Waste Disposal Rates (BC Data Catalogue, 1990–2024): OGL-BC.
// NOT used: GADM (non-commercial only); StatCan's boundary files (its download sits behind a bot check, which this
// script does not try to get past).
// WHY admin-0 is keyed on ADM0_A3 and not ISO_A3: Natural Earth sets ISO_A3 to -99 for France, Norway and three
// disputed areas, so five features would share one id and France could never be joined to a value.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import mapshaper from 'mapshaper';

const here = dirname(fileURLToPath(import.meta.url));
const SB = resolve(here, '..');
const CACHE = join(SB, '.geo-cache');
const OUT = resolve(SB, '../vibetracks/home/static');
const DATA = join(SB, 'fixtures/public');
const refresh = process.argv.includes('--refresh');
const today = new Date().toISOString().slice(0, 10);

const WFS = 'https://openmaps.gov.bc.ca/geo/pub/wfs?service=WFS&version=2.0.0&request=GetFeature&outputFormat=json&srsName=EPSG:4326&typeName=';
const SOURCES = {
  ne0: { url: 'https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@v5.1.2/geojson/ne_110m_admin_0_countries.geojson', file: 'ne_110m_admin_0_countries.geojson' },
  ne1: { url: 'https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@v5.1.2/geojson/ne_50m_admin_1_states_provinces.geojson', file: 'ne_50m_admin_1_states_provinces.geojson' },
  bcrd: { url: WFS + 'pub:WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_REGIONAL_DISTRICTS_SP', file: 'bc_rd.json' },
  bcnr: { url: WFS + 'pub:WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_MUNICIPALITIES_SP&CQL_FILTER=' + encodeURIComponent("ADMIN_AREA_NAME='Northern Rockies Regional Municipality'"), file: 'bc_nrrm.json' },
  cesi: { url: 'https://www.canada.ca/content/dam/eccc/documents/csv/cesindicators/solid-waste/2024-nov/figure-5-en.csv', file: 'cesi-figure-5-en.csv' },
  bcmsw: { url: 'https://catalogue.data.gov.bc.ca/dataset/d21ed158-0ac7-4afd-a03b-ce22df0096bc/resource/d2648733-e484-40f2-b589-48192c16686b/download/bc_municipal_solid_waste_disposal.csv', file: 'bc_municipal_solid_waste_disposal.csv' },
};

async function fetchTo(key) {
  const s = SOURCES[key];
  const path = join(CACHE, s.file);
  if (existsSync(path) && !refresh) return path;
  const r = await fetch(s.url);
  if (!r.ok) throw new Error(`${r.status} ${s.url}`);
  const body = Buffer.from(await r.arrayBuffer());
  if (/^\s*<!doctype html|^\s*<html/i.test(body.subarray(0, 200).toString())) throw new Error(`${s.url} answered an HTML page, not data`);
  writeFileSync(path, body);
  console.log(`downloaded ${s.file} (${(body.length / 1e6).toFixed(2)} MB)`);
  return path;
}

// BC's disposal table names each reporting unit its own way; the boundary layer uses legal names. One row each.
// Comox Valley and Strathcona report together ("Comox-Strathcona"), so their polygons are dissolved into one unit;
// Northern Rockies is a regional municipality, outside every regional district, so it comes from the municipal layer.
const BC_UNITS = {
  'Alberni-Clayoquot': ['Regional District of Alberni-Clayoquot'], 'Bulkley-Nechako': ['Regional District of Bulkley-Nechako'],
  Capital: ['Capital Regional District'], Cariboo: ['Cariboo Regional District'], 'Central Coast': ['Central Coast Regional District'],
  'Central Kootenay': ['Regional District of Central Kootenay'], 'Central Okanagan': ['Regional District of Central Okanagan'],
  'Columbia-Shuswap': ['Columbia Shuswap Regional District'], 'Comox-Strathcona': ['Comox Valley Regional District', 'Strathcona Regional District'],
  'Cowichan Valley': ['Cowichan Valley Regional District'], 'East Kootenay': ['Regional District of East Kootenay'],
  'Fraser Valley': ['Fraser Valley Regional District'], 'Fraser-Fort George': ['Regional District of Fraser-Fort George'],
  'Kitimat-Stikine': ['Regional District of Kitimat-Stikine'], 'Kootenay Boundary': ['Regional District of Kootenay Boundary'],
  'Metro-Vancouver': ['Metro Vancouver Regional District'], 'Mount Waddington': ['Regional District of Mount Waddington'],
  Nanaimo: ['Regional District of Nanaimo'], 'North Coast': ['North Coast Regional District'], 'North Okanagan': ['Regional District of North Okanagan'],
  'Northern Rockies': ['Northern Rockies Regional Municipality'], 'Okanagan-Similkameen': ['Regional District of Okanagan-Similkameen'],
  'Peace River': ['Peace River Regional District'], 'Squamish-Lillooet': ['Squamish-Lillooet Regional District'],
  'Sunshine Coast': ['Sunshine Coast Regional District'], 'Thompson-Nicola': ['Thompson-Nicola Regional District'], qathet: ['qathet Regional District'],
  // no row in the disposal table: drawn, and shown as "No data"
  'Stikine Region': ['Stikine Region (Unincorporated)'],
};
const DISPLAY = { 'Comox-Strathcona': 'Comox Valley + Strathcona', 'Metro-Vancouver': 'Metro Vancouver', 'Stikine Region': 'Stikine Region (unincorporated)' };

async function run(cmd) { await mapshaper.runCommands(cmd); }
function sidecar(file, meta) { writeFileSync(join(OUT, file.replace(/\.json$/, '.source.json')), JSON.stringify(meta, null, 1) + '\n'); }
const size = (file) => (readFileSync(join(OUT, file)).length / 1024).toFixed(0) + ' KB';

async function main() {
  mkdirSync(CACHE, { recursive: true });
  mkdirSync(DATA, { recursive: true });
  const p = {};
  for (const key of Object.keys(SOURCES)) p[key] = await fetchTo(key);

  // countries: everything but Antarctica (it dominates a Mercator frame and holds no one's waste)
  await run(`-i "${p.ne0}" -filter "ADM0_A3 != 'ATA'" -each "key=ADM0_A3, name=NAME" -filter-fields key,name -o "${join(OUT, 'geo-ne-admin0.json')}" precision=0.01 format=geojson`);
  sidecar('geo-ne-admin0.json', { level: 'country', source: 'Natural Earth 5.1.2, admin-0 countries 1:110m', url: SOURCES.ne0.url, licence: 'Public domain (naturalearthdata.com/about/terms-of-use)', key: 'ADM0_A3', retrieved: today, simplified: 'precision 0.01°' });

  // provinces and states: Canada and the US (the drill-down below a country)
  await run(`-i "${p.ne1}" -filter "adm0_a3 == 'CAN' || adm0_a3 == 'USA'" -each "key=iso_3166_2, name=name, parent=adm0_a3" -filter-fields key,name,parent -simplify 25% keep-shapes -o "${join(OUT, 'geo-ne-admin1-can-usa.json')}" precision=0.01 format=geojson`);
  sidecar('geo-ne-admin1-can-usa.json', { level: 'province', source: 'Natural Earth 5.1.2, admin-1 states and provinces 1:50m (CAN, USA)', url: SOURCES.ne1.url, licence: 'Public domain', key: 'iso_3166_2 (e.g. CA-BC)', parent: 'adm0_a3', retrieved: today, simplified: 'Visvalingam 25% kept, keep-shapes, precision 0.01°' });

  // BC's waste reporting units: regional districts (+ Northern Rockies), keyed by the disposal table's own names
  const byLegal = {};
  for (const [unit, names] of Object.entries(BC_UNITS)) for (const n of names) byLegal[n] = unit;
  const features = [];
  for (const file of [p.bcrd, p.bcnr]) {
    for (const f of JSON.parse(readFileSync(file, 'utf8')).features) {
      const unit = byLegal[f.properties.ADMIN_AREA_NAME];
      if (!unit) throw new Error(`no BC reporting unit for "${f.properties.ADMIN_AREA_NAME}": add it to BC_UNITS`);
      features.push({ type: 'Feature', geometry: f.geometry, properties: { key: unit, name: DISPLAY[unit] || unit, parent: 'CA-BC' } });
    }
  }
  const missing = Object.entries(BC_UNITS).flatMap(([u, ns]) => ns.filter((n) => !features.some((f) => f.properties.key === u)).map((n) => `${u}: ${n}`));
  if (missing.length) throw new Error(`boundary layer lacks: ${missing.join('; ')}`);
  const tmp = join(CACHE, 'bc_units.json');
  writeFileSync(tmp, JSON.stringify({ type: 'FeatureCollection', features }));
  await run(`-i "${tmp}" -simplify 4% keep-shapes -dissolve key copy-fields=name,parent -o "${join(OUT, 'geo-bc-waste-units.json')}" precision=0.001 format=geojson`);
  sidecar('geo-bc-waste-units.json', { level: 'district', source: 'BC Data Catalogue: Regional Districts and Municipalities, Legally Defined Administrative Areas of BC (ABMS), via openmaps.gov.bc.ca WFS', url: [SOURCES.bcrd.url, SOURCES.bcnr.url], licence: 'Open Government Licence – British Columbia', attribution: 'Contains information licensed under the Open Government Licence – British Columbia', key: 'the BC disposal table\'s Regional_District name; Comox Valley + Strathcona dissolved (they report together)', parent: 'CA-BC', retrieved: today, simplified: 'Visvalingam 4% kept (the coast stays readable at Metro Vancouver zoom), keep-shapes, precision 0.001°' });

  // the open data the stories show, copied as published (raw), each with its sidecar
  writeFileSync(join(DATA, 'cesi-diversion-by-province.csv'), readFileSync(p.cesi));
  writeFileSync(join(DATA, 'cesi-diversion-by-province.source.json'), JSON.stringify({
    title: 'Solid waste diversion rate from all sources by jurisdiction, Canada, 2002 and 2022 (CESI, figure 5)',
    publisher: 'Environment and Climate Change Canada, Canadian Environmental Sustainability Indicators', url: SOURCES.cesi.url,
    page: 'https://www.canada.ca/en/environment-climate-change/services/environmental-indicators/solid-waste-diversion-disposal.html',
    licence: 'Open Government Licence – Canada', attribution: 'Contains information licensed under the Open Government Licence – Canada',
    definition: 'diverted / (diverted + disposed); disposal includes landfill, incineration and energy-from-waste, so burning never counts as diverted',
    caveats: ['n/a cells are suppressed by Statistics Canada (PEI, the territories): no data, never 0', 'two periods only, 2002 and 2022'], retrieved: today,
  }, null, 1) + '\n');
  writeFileSync(join(DATA, 'bc-msw-disposal.csv'), readFileSync(p.bcmsw));
  writeFileSync(join(DATA, 'bc-msw-disposal.source.json'), JSON.stringify({
    title: 'BC Municipal Solid Waste Disposal Rates, by regional district, 1990–2024', publisher: 'Government of British Columbia, BC Data Catalogue',
    url: SOURCES.bcmsw.url, page: 'https://catalogue.data.gov.bc.ca/dataset/d21ed158-0ac7-4afd-a03b-ce22df0096bc',
    licence: 'Open Government Licence – British Columbia', attribution: 'Contains information licensed under the Open Government Licence – British Columbia',
    definition: 'kg of municipal solid waste disposed per person per year (Disposal_Rate_kg); a disposal rate, NOT a diversion rate, and lower is better',
    caveats: ['a year with 0 tonnes disposed is a missing report, not zero waste (Central Coast 2024: 0 t after ~1,600 t a year; 1990s rows: 0 t and no population): the stories read it as no data and say so',
      'Comox-Strathcona and Northern Rockies are reporting units, not regional districts (see geo-bc-waste-units.source.json)'], retrieved: today,
  }, null, 1) + '\n');

  for (const f of ['geo-ne-admin0.json', 'geo-ne-admin1-can-usa.json', 'geo-bc-waste-units.json']) console.log(f, size(f));
}
main().catch((e) => { console.error(e.message || e); process.exit(1); });
