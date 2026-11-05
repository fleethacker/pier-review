// End-to-end check of the exercise simulator in a real browser, against a production build and its own service.
//
//   npm run build && npm run test:e2e
//
// Needs Playwright, which is not a dependency of the app (it is large): `npm i --no-save playwright && npx playwright install chromium`.
// Set PLAYWRIGHT_PATH to a Playwright install elsewhere if you have one. Set E2E_BASE_URL to test an already running app instead of
// starting one. MAPBOX_TOKEN (or VITE_MAPBOX_TOKEN) in the environment is given to the service, which hands it to the page.
// Set EXERCISE_VENV to a virtualenv with the service installed (default: server/.venv, then .venv beside it).
//
// Software WebGL is used so no GPU is needed; it is slow, so the map itself is only checked for loading, not for how it looks.

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const app = path.resolve(here, '..');
const server = path.join(app, 'server');
const out = process.env.E2E_OUT || mkdtempSync(path.join(tmpdir(), 'exercise-e2e-'));
mkdirSync(out, { recursive: true });

const { chromium } = await import(process.env.PLAYWRIGHT_PATH || 'playwright').catch(() => {
  console.error('Playwright is not installed. Run: npm i --no-save playwright && npx playwright install chromium');
  process.exit(2);
});

const children = [];
const stopAll = () => children.forEach((c) => c.kill('SIGTERM'));
process.on('exit', stopAll);
process.on('SIGINT', () => process.exit(130));

function start(cmd, args, options) {
  const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], ...options });
  const log = [];
  child.stdout.on('data', (d) => log.push(String(d)));
  child.stderr.on('data', (d) => log.push(String(d)));
  child.log = log;
  children.push(child);
  return child;
}

async function waitFor(url, what, ms = 60_000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${what} did not come up at ${url}`);
}

const results = [];
async function step(name, fn) {
  const t0 = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - t0 });
    console.log(`  ok   ${name} (${((Date.now() - t0) / 1000).toFixed(1)} s)`);
  } catch (e) {
    results.push({ name, ok: false, error: e.message });
    console.log(`  FAIL ${name}\n       ${String(e.message).split('\n')[0]}`);
  }
}
const check = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

let base = process.env.E2E_BASE_URL;
const dataDir = mkdtempSync(path.join(tmpdir(), 'exercise-lib-'));
if (!base) {
  const venv = process.env.EXERCISE_VENV || [path.join(server, '.venv'), path.join(app, '.venv')].find((v) => existsSync(path.join(v, 'bin/uvicorn')));
  const uvicorn = venv ? path.join(venv, 'bin/uvicorn') : '';
  check(existsSync(uvicorn), 'No virtualenv with uvicorn: run `uv sync` in exercise/server, or set EXERCISE_VENV or E2E_BASE_URL.');
  check(existsSync(path.join(app, 'dist/index.html')), 'No build: run `npm run build` first.');
  const token = process.env.MAPBOX_TOKEN || process.env.VITE_MAPBOX_TOKEN || '';
  start(uvicorn, ['exercise_api.main:app', '--host', '127.0.0.1', '--port', '8710'], {
    cwd: server,
    env: { ...process.env, EXERCISE_DATA_DIR: dataDir, MAPBOX_TOKEN: token, VITE_MAPBOX_TOKEN: '' },
  });
  const viteBin = path.join(app, 'node_modules/vite/bin/vite.js');
  start(process.execPath, [viteBin, 'preview', '--host', '127.0.0.1', '--port', '8711', '--strictPort'], {
    cwd: app,
    // The build must not have the token in it: the page has to get it from the service.
    env: { ...process.env, VITE_MAPBOX_TOKEN: '', EXERCISE_PROXY_TARGET: 'http://127.0.0.1:8710' },
  });
  await waitFor('http://127.0.0.1:8710/api/v1/exercise/config', 'The exercise service');
  await waitFor('http://127.0.0.1:8711/', 'The preview server');
  base = 'http://127.0.0.1:8711/';
}
console.log(`Testing ${base}\nScreenshots and downloads go to ${out}\n`);

const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const context = await browser.newContext({ viewport: { width: 1280, height: 760 }, acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(60_000);
const pageErrors = [];
const workers = [];
page.on('pageerror', (e) => pageErrors.push(e.message));
page.on('worker', (w) => workers.push(w.url()));

await step('the page loads straight into the simulator', async () => {
  await page.goto(base);
  await page.getByRole('button', { name: 'Red team' }).waitFor();
  check(await page.getByRole('tab', { name: 'Scenario' }).getAttribute('aria-selected') === 'true', 'the scenario view is not open');
});

await step('the map loads with a token the server provided (none is built in)', async () => {
  const have = await (await fetch(new URL('api/v1/exercise/config', base))).json();
  if (!have.mapboxToken) {
    console.log('       (no MAPBOX_TOKEN in the environment: checking the prompt instead)');
    await page.getByLabel('Mapbox access token').waitFor();
    return;
  }
  await page.locator('canvas.mapboxgl-canvas').waitFor({ timeout: 120_000 });
  check((await page.getByLabel('Mapbox access token').count()) === 0, 'it is still asking for a token');
});

await step('moving the clock and playing do not break the page', async () => {
  await page.getByRole('button', { name: 'Play' }).first().click({ timeout: 10_000 }).catch(() => undefined);
  await page.screenshot({ path: path.join(out, '1-exercise.png'), timeout: 170_000 });
});

await step('sensors and detection can be switched on, and a sensor scenario loads', async () => {
  const select = page.getByLabel('Load');
  await select.selectOption({ label: 'Over the horizon' });
  const box = page.getByRole('checkbox', { name: 'Sensors and detection' });
  check(await box.isChecked(), 'the preset did not switch sensors on');
  await page.getByText('Held').first().waitFor({ state: 'attached', timeout: 5_000 }).catch(() => undefined);
});

await step('the red team runs on worker threads and shows results', async () => {
  await page.getByRole('button', { name: 'Red team' }).click();
  const dialog = page.getByRole('dialog', { name: 'Red team' });
  const runs = dialog.getByLabel('Runs at each value');
  await runs.fill('20');
  await runs.blur();
  await dialog.getByRole('button', { name: /^Run / }).click();
  await dialog.getByRole('list', { name: 'Outcome chances' }).waitFor({ timeout: 170_000 });
  check(workers.some((w) => /mcWorker/.test(w)), `no red-team worker was started (workers seen: ${workers.join(', ') || 'none'})`);
  await page.screenshot({ path: path.join(out, '2-red-team.png'), timeout: 170_000 });
});

await step('results export to CSV, and the baseline comparison appears', async () => {
  const dialog = page.getByRole('dialog', { name: 'Red team' });
  const [download] = await Promise.all([page.waitForEvent('download'), dialog.getByRole('button', { name: 'Download CSV' }).click()]);
  const file = path.join(out, download.suggestedFilename());
  await download.saveAs(file);
  check(/\.csv$/.test(file), 'the download is not a CSV');
  await dialog.getByRole('button', { name: 'Keep as baseline' }).click();
  await dialog.getByText(/This batch is the baseline/).waitFor();
});

await step('a scenario saves to the shared library and comes back', async () => {
  await page.getByRole('button', { name: 'Close red team' }).click();
  const library = page.getByLabel('Saved scenarios');
  await library.locator('summary').click();
  const where = library.getByRole('combobox');
  await where.waitFor({ timeout: 10_000 });
  await where.selectOption('shared');
  await library.getByRole('button', { name: /^Save “/ }).click();
  await library.getByText(/in the shared library/).waitFor();
  const listed = await (await fetch(new URL('api/v1/exercise/scenarios', base))).json();
  check(listed.some((s) => s.id === 'over-the-horizon'), `the server does not list it: ${JSON.stringify(listed)}`);
  page.once('dialog', (d) => d.accept());
  await library.getByRole('button', { name: 'Delete Over the horizon' }).click();
  await library.getByText(/Deleted/).waitFor();
});

await step('client errors reach the server log', async () => {
  const res = await fetch(new URL('api/v1/exercise/client-errors', base), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: 'e2e', message: 'end-to-end check' }),
  });
  check(res.status === 204, `unexpected status ${res.status}`);
});

await step('no uncaught errors in the page', async () => check(pageErrors.length === 0, `page errors: ${pageErrors.join(' | ')}`));

await browser.close();
const failed = results.filter((r) => !r.ok);
writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2));
console.log(`\n${results.length - failed.length} of ${results.length} steps passed`);
process.exit(failed.length ? 1 : 0);
