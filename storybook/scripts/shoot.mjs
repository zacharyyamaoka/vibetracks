// Screenshots every story of the static build (storybook-static/), dark and light, at desktop width (and phone width
// with --phone), into a folder, and fails on any console error or page error. The visual proof for a report; the
// pass/fail gate is `npm test`.
//
//   node /home/bam/vibetracks-storybook/storybook/scripts/shoot.mjs --out /home/bam/vibetracks/reports/media/<name>/shots
//   node …/shoot.mjs --only viz-map --themes dark          (a subset)
//
// It serves storybook-static on a free 127.0.0.1 port of its own and stops it when done.
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../storybook-static');
const arg = (name, def) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : def; };
const out = path.resolve(arg('--out', path.join(here, '../.shots')));
const only = arg('--only', '');
const themes = arg('--themes', 'dark,light').split(',');
const widths = process.argv.includes('--phone') ? [1280, 390] : [1280];
const exe = arg('--chrome', process.env.VT_CHROME || '');

const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.png': 'image/png' };
const srv = http.createServer((q, r) => {
  let f = path.join(root, decodeURIComponent(new URL(q.url, 'http://x').pathname));
  if (!f.startsWith(root)) { r.writeHead(403).end(); return; }
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
  if (!fs.existsSync(f)) { r.writeHead(404).end(); return; }
  r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(r);
});
await new Promise((d) => srv.listen(0, '127.0.0.1', d));
const base = `http://127.0.0.1:${srv.address().port}`;
const index = JSON.parse(fs.readFileSync(path.join(root, 'index.json'), 'utf8'));
const stories = Object.values(index.entries).filter((e) => e.type === 'story' && e.id.includes(only));
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const results = [];
try {
  for (const width of widths) {
    const page = await browser.newPage({ viewport: { width, height: 860 }, deviceScaleFactor: 1 });
    let errs = [];
    page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    page.on('pageerror', (e) => errs.push(String(e)));
    for (const s of stories) {
      for (const theme of themes) {
        errs = [];
        await page.goto(`${base}/iframe.html?id=${s.id}&viewMode=story&globals=theme:${theme}`, { waitUntil: 'load' });
        // settle: the home's documents arrive, maps go idle, rAF re-renders finish
        await page.waitForFunction(() => {
          const r = document.querySelector('#storybook-root');
          if (!r || !r.firstElementChild) return false;
          if (/Reading (the|KPIs|sessions)/.test(r.textContent)) return false;
          return [...document.querySelectorAll('vt-map')].every((m) => m.dataset.state === 'ready' || m.dataset.state === 'error');
        }, null, { timeout: 30000 }).catch(() => errs.push('did not settle in 30 s'));
        await page.waitForTimeout(400);
        const name = `${s.id}--${theme}${width < 600 ? '--phone' : ''}.png`;
        await page.screenshot({ path: path.join(out, name), fullPage: true });
        results.push({ id: s.id, title: `${s.title} / ${s.name}`, theme, width, file: name, errors: errs.slice() });
        console.log(`${errs.length ? 'ERR ' : 'ok  '} ${name}${errs.length ? '  ' + errs.join(' | ').slice(0, 300) : ''}`);
      }
    }
    await page.close();
  }
} finally {
  await browser.close();
  srv.close();
}
fs.writeFileSync(path.join(out, 'shots.json'), JSON.stringify(results, null, 1));
const bad = results.filter((r) => r.errors.length);
console.log(`${results.length} screenshots, ${bad.length} with console/page errors -> ${out}`);
process.exit(bad.length ? 1 : 0);
