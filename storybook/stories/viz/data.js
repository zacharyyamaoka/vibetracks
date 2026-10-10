// The open data the viz stories show, read from the files as published (fixtures/public, each with a .source.json),
// turned into <vt-map>'s tidy rows. Nothing is invented here; the one judgement call is named below.
import cesiCsv from '../../fixtures/public/cesi-diversion-by-province.csv?raw';
import cesiSrc from '../../fixtures/public/cesi-diversion-by-province.source.json';
import bcCsv from '../../fixtures/public/bc-msw-disposal.csv?raw';
import bcSrc from '../../fixtures/public/bc-msw-disposal.source.json';
import admin0 from '@home/geo-ne-admin0.json?url';
import admin1 from '@home/geo-ne-admin1-can-usa.json?url';
import bcUnits from '@home/geo-bc-waste-units.json?url';

/** A small CSV reader (quoted fields, BOM); the files are a few KB. */
export function parseCsv(text) {
  const rows = [];
  let row = [], cell = '', q = false;
  text = text.replace(/^﻿/, '');
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') q = false; else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ',') { row.push(cell); cell = ''; }
    else if (ch === '\n' || ch === '\r') { if (ch === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += ch;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

const PROVINCE = { 'Newfoundland and Labrador': 'CA-NL', 'Prince Edward Island': 'CA-PE', 'Nova Scotia': 'CA-NS', 'New Brunswick': 'CA-NB',
  Quebec: 'CA-QC', Ontario: 'CA-ON', Manitoba: 'CA-MB', Saskatchewan: 'CA-SK', Alberta: 'CA-AB', 'British Columbia': 'CA-BC' };
const CESI = 'ECCC CESI, solid waste diversion (fig. 5), Open Government Licence – Canada';
const CESI_METHOD = 'diverted ÷ (diverted + disposed); burning counts as disposed';

/** CESI figure 5: Canada (country level) and 10 provinces, 2002 and 2022. "n/a" (suppressed) stays absent: No data. */
export function cesiRows() {
  const out = [];
  const lines = parseCsv(cesiCsv);
  const head = lines.findIndex((r) => r[0] === 'Jurisdiction');
  const years = lines[head].slice(1).map((h) => (h.match(/\d{4}/) || [])[0]);
  for (const r of lines.slice(head + 1)) {
    const name = (r[0] || '').replace(/\s*\[[A-Z]\]\s*$/, '').trim();
    const key = name === 'Canada' ? 'CAN' : PROVINCE[name];
    if (!key) continue;
    years.forEach((year, i) => {
      const v = r[i + 1];
      if (!year || v == null || v === '' || v === 'n/a') return;
      out.push({ level: key === 'CAN' ? 'country' : 'province', key, period: year, value: Number(v), source: CESI, method: CESI_METHOD });
    });
  }
  return out;
}

/** BC disposal per person by reporting unit, 1990–2024.
 *  JUDGEMENT CALL (stated, not silent): a year reporting 0 t disposed is a missing report, not zero waste (Central
 *  Coast 2024 reads 0 t after ~1,600 t a year; the 1990s rows read 0 t and no population). It becomes a no-data row
 *  that carries that note, so the map says "No data" and the tooltip and table say why. */
export function bcRows() {
  const [head, ...lines] = parseCsv(bcCsv);
  const ix = Object.fromEntries(head.map((h, i) => [h, i]));
  const SRC = 'BC Municipal Solid Waste Disposal Rates, BC Data Catalogue, OGL-BC';
  return lines.filter((r) => r.length > 1).map((r) => {
    const tonnes = Number(r[ix.Total_Disposed_Tonnes]), kg = r[ix.Disposal_Rate_kg];
    const base = { level: 'district', key: r[ix.Regional_District], period: r[ix.Year], source: SRC, method: 'kg disposed per person' };
    if (!tonnes || kg === '' || kg == null) return Object.assign(base, { value: null, note: `the source reports ${tonnes ? 'no rate' : '0 t disposed'}: read as a missing report` });
    return Object.assign(base, { value: Number(kg) });
  });
}

export const SOURCES = { cesi: cesiSrc, bc: bcSrc };

/** The three levels every waste map shares: countries, provinces/states, BC's waste reporting units. */
export const LEVELS = [
  { id: 'country', label: 'World', noun: 'country', boundary: admin0 },
  { id: 'province', label: 'Provinces', noun: 'province or state', boundary: admin1 },
  { id: 'district', label: 'Regional districts', noun: 'regional district', boundary: bcUnits,
    // BC publishes disposal per person by district, not a diversion rate: a different measure, said in the legend
    metric: { label: 'Waste disposed per person', unit: 'kg/person', decimals: 0, better: 'lower', breaks: [400, 500, 600, 700], goal: null },
    sources: ['Boundaries: BC Data Catalogue (ABMS regional districts), OGL-BC; Comox Valley + Strathcona report together'] },
];
export const DIVERSION = { label: 'Waste diverted', unit: '%', decimals: 1, better: 'higher', breaks: [20, 40, 60, 80], goal: 100, goalLabel: '100% circularity' };
export const BOUNDARY_NOTE = 'Boundaries: Natural Earth 5.1.2 (public domain)';

/** Illustrative only: BAM has no deployed site (Oct 2026). Positions are public landmarks' areas, statuses made up. */
export const ILLUSTRATIVE_SITES = [
  { id: 'hospital-pilot', label: 'Hospital pilot (illustrative)', lon: -123.123, lat: 49.262, status: 'ok', size: 1.2, sizeLabel: 't/day', note: 'Illustrative point, not a real site' },
  { id: 'food-court', label: 'Food court cell (illustrative)', lon: -123.0, lat: 49.227, status: 'warn', size: 0.4, sizeLabel: 't/day', note: 'Illustrative point, not a real site' },
  { id: 'transfer-station', label: 'Transfer station line (illustrative)', lon: -123.02, lat: 49.306, status: 'idle', size: 6, sizeLabel: 't/day', note: 'Illustrative point, not a real site' },
  { id: 'victoria', label: 'Island pilot (illustrative)', lon: -123.37, lat: 48.43, status: 'fail', size: 0.8, sizeLabel: 't/day', note: 'Illustrative point, not a real site' },
];
