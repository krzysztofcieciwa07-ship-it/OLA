// Browser plugin not available in the authoring environment. CI uses Playwright.
// Real backend calls only. No route mocks, injected results, or production credentials.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const {chromium} = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE_PATH).href);
let input = ''; for await (const chunk of process.stdin) input += chunk;
const {base, key, tenant, source} = JSON.parse(input);
const output = process.env.OLA_BROWSER_OUTPUT;
const report = {schema: 'ola.browser-proof.v1', source_commit: source,
  scope: 'isolated deterministic runtime; no deployment or real LLM claim', viewports: []};
const browser = await chromium.launch({headless: true});
try {
  for (const viewport of [{name: 'desktop', width: 1440, height: 1080}, {name: 'mobile', width: 390, height: 844}]) {
    const context = await browser.newContext({viewport: {width: viewport.width, height: viewport.height}, acceptDownloads: true});
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      // Chromium logs expected negative auth requests as network errors.
      if (['error', 'warning'].includes(message.type()) && !message.text().includes('401 (Unauthorized)'))
        errors.push(message.text());
    });
    page.on('request', request => requests.push({url: request.url(), method: request.method()}));
    try {
      await page.goto(base + '/');
      assert.equal(page.url(), base + '/');
      assert.equal(await page.title(), 'OLA di-OS · Zadania i dowody');
      await page.getByRole('heading', {name: 'Od zadania do sprawdzalnego wyniku.'}).waitFor();
      await page.waitForFunction(() => document.querySelector('#connection').textContent === 'API odpowiada');
      assert.equal(await page.locator('#run').isEnabled(), false);
      assert.equal(await page.locator('#decision').textContent(), 'UNKNOWN');
      await page.locator('#key').fill('deliberately-invalid-test-key');
      await page.getByRole('button', {name: 'Połącz', exact: true}).click();
      await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('nie został zaakceptowany'));
      assert.equal(await page.locator('#run').isEnabled(), false);
      await page.locator('#key').fill(key);
      await page.getByRole('button', {name: 'Połącz', exact: true}).click();
      await page.locator('#disconnect').waitFor();
      assert.ok((await page.locator('#access-info').textContent()).includes(tenant));
      await page.locator('#task').fill('calculate 17*23');
      await page.getByRole('button', {name: 'Wykonaj i sprawdź', exact: true}).click();
      await page.waitForFunction(() => document.querySelector('#result-text').textContent === '391');
      assert.equal(await page.locator('#decision').textContent(), 'REVIEW');
      assert.equal(await page.locator('#mode').textContent(), 'Lokalne wykonanie deterministyczne');
      const gates = await page.locator('#gates .badge').allTextContents();
      assert.deepEqual(gates, ['VERIFIED', 'VERIFIED', 'VERIFIED', 'VERIFIED', 'REVIEW']);
      const run = await page.locator('#run-id').textContent();
      assert.equal(await page.locator('.evidence-row').count(), 7);
      assert.equal(requests.filter(r => r.method === 'POST' && r.url === base + '/nina-run').length, 1);
      assert.ok(requests.every(r => new URL(r.url).origin === base), 'No external UI requests');
      assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const downloadEvent = page.waitForEvent('download');
      await page.getByRole('button', {name: 'Pobierz raport JSON', exact: true}).click();
      const download = await downloadEvent;
      const downloaded = await readFile(await download.path(), 'utf8');
      assert.ok(!downloaded.includes(key));
      const observation = JSON.parse(downloaded);
      assert.equal(observation.view.run, run);
      assert.equal(observation.view.source, source);
      assert.equal(observation.view.result, '391');
      assert.deepEqual(observation.view.issues, []);
      assert.ok(observation.records.every(r => r.tenant_id === tenant && r.payload.run_id === run));
      assert.ok(observation.response.replay.every(r => r.run_id === run));
      assert.equal(observation.response.decision_report.report_sha256, undefined);
      await page.screenshot({path: join(output, `${viewport.name}-result.png`), fullPage: true});
      await page.getByRole('button', {name: 'Odłącz i wyczyść kartę', exact: true}).click();
      assert.equal(await page.locator('#run').isEnabled(), false);
      assert.equal(await page.locator('#decision').textContent(), 'UNKNOWN');
      assert.equal(await page.locator('#export').isEnabled(), false);
      assert.equal(await page.locator('#raw').textContent(), 'Brak danych.');
      assert.equal(await page.locator('#task').inputValue(), '');
      assert.equal(await page.locator('#key').inputValue(), '');
      assert.equal(await page.locator('.evidence-row').count(), 0);
      assert.ok(!(await page.locator('body').textContent()).includes(run));
      assert.deepEqual(errors, []);
      report.viewports.push({name: viewport.name, width: viewport.width, height: viewport.height,
        run_id: run, result: '391', terminal_status: 'REVIEW', evidence_count: 7,
        invalid_key_rejected: true, logout_cleared: true, horizontal_overflow: false, console_errors: errors});
    } catch (error) {
      await page.screenshot({path: join(output, `${viewport.name}-failure.png`), fullPage: true}).catch(() => {});
      throw error;
    } finally { await context.close(); }
  }
  await writeFile(join(output, 'browser-proof.json'), JSON.stringify(report, null, 2));
} finally { await browser.close(); }
