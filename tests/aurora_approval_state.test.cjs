'use strict';

// Exercises the actual inline Aurora script without a browser or backend.
// These isolated UI tests do not establish Windows or end-to-end readiness.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const script = html.match(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/i)?.[1];
assert.ok(script?.includes('const session='), 'Aurora session script must be present');

class Element {
  constructor(id = '') {
    this.id = id;
    this.value = '';
    this.textContent = '';
    this.disabled = false;
    this.children = [];
    this.listeners = new Map();
    const classes = new Set();
    this.classList = {
      add: value => classes.add(value),
      remove: value => classes.delete(value),
      contains: value => classes.has(value),
      toggle(value, enabled) {
        const active = enabled ?? !classes.has(value);
        if (active) classes.add(value); else classes.delete(value);
        return active;
      },
    };
  }
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  }
  dispatch(type) {
    for (const callback of this.listeners.get(type) || []) callback({preventDefault() {}});
  }
  replaceChildren(...children) { this.children = children; this.textContent = ''; }
  appendChild(child) { child.parent = this; this.children.push(child); }
  prepend(child) { child.parent = this; this.children.unshift(child); }
  get firstElementChild() { return this.children[0]; }
  get lastElementChild() { return this.children.at(-1); }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
}

const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  async json() { return body; },
});
const drain = () => new Promise(resolve => setImmediate(resolve));

function createConsole(approve) {
  const elements = new Map();
  for (const match of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]);
    element.disabled = /\sdisabled(?:\s|>|=)/.test(match[0]);
    elements.set(element.id, element);
  }
  const el = id => {
    assert.ok(elements.has(id), `Unknown DOM element ${id}`);
    return elements.get(id);
  };
  el('toast').classList.add('hidden');
  const calls = [];
  const fetch = (url, options) => {
    calls.push({url, options});
    if (url === '/health') return Promise.resolve(response({status: 'ok'}));
    if (url === '/auth/session') return Promise.resolve(response({
      authenticated: true,
      tenant_id: '1177d13f-1e08-40ce-a7fe-a2fd101fca83',
      credential_id: options.headers['X-API-Key'] === 'requesting-operator'
        ? '4efc4586-4ea8-4cf1-848f-c03bfa3d8ea7' : '97d61b88-fea7-4f44-9f85-a1c9fcab745f',
      scope: options.headers['X-API-Key'] === 'requesting-operator' ? 'OLA_CORE' : 'REVIEW_RESULT',
    }));
    if (url === '/nina-run/test-run/approval') return Promise.resolve(response({
      status: 'APPROVED', scope: 'review-result', assurance: 'UNKNOWN', production_eligible: false,
      reviewer_credential_status: 'ACTIVE',
    }));
    if (url === '/nina-run') return Promise.resolve(response({
      status: 'REVIEW',
      run_id: 'test-run',
      tip_hash: 'test-tip',
      status_fields: {HUMAN_GATE: 'REVIEW'},
      decision_report_v2: {report_sha256: 'test-report'},
    }));
    if (url === '/nina-run/test-run/approve') return approve(options);
    throw new Error(`Unexpected request: ${url}`);
  };
  vm.runInNewContext(script, {
    document: {getElementById: el, querySelectorAll: () => [], createElement: () => new Element(), addEventListener() {}},
    window: {innerWidth: 1280, location: {hostname: 'example.invalid', protocol: 'http:'}},
    fetch, AbortController,
    setTimeout: () => 0, clearTimeout() {}, setInterval() {},
  }, {filename: 'web/index.html:aurora-session'});
  return {
    el, calls,
    approvalCalls: () => calls.filter(call => call.url.endsWith('/approve')),
    async candidate() {
      el('apiKey').value = 'requesting-operator';
      el('runTask').value = 'Oblicz 17 * 23';
      el('runForm').dispatch('submit');
      await drain();
      assert.equal(el('approveSend').disabled, false, 'a real REVIEW response enables approval');
      el('approverKey').value = 'independent-operator';
    },
  };
}

test('APPROVED consumes the candidate and keeps approval disabled after busy finishes', async () => {
  const ui = createConsole(() => Promise.resolve(response({status: 'APPROVED'})));
  await ui.candidate();
  ui.el('approvalForm').dispatch('submit');
  await drain();
  assert.equal(ui.el('humanStatus').textContent, 'APPROVED — przegląd wyniku');
  assert.equal(ui.el('approveSend').disabled, true);
  assert.equal(ui.el('approveSend').classList.contains('loading'), false);
  ui.el('approvalForm').dispatch('submit');
  await drain();
  assert.equal(ui.approvalCalls().length, 1, 'a consumed candidate cannot submit a second approval');
});

test('an HTTP refusal preserves the candidate and allows retry with another reviewer key', async () => {
  let attempts = 0;
  const ui = createConsole(() => Promise.resolve(++attempts === 1
    ? response({detail: 'Reviewer key rejected'}, 403)
    : response({status: 'APPROVED'})));
  await ui.candidate();
  ui.el('approvalForm').dispatch('submit');
  await drain();
  assert.equal(ui.el('approveSend').disabled, false);
  assert.match(ui.el('toast').textContent, /HTTP 403/);
  ui.el('approverKey').value = 'replacement-reviewer';
  ui.el('approvalForm').dispatch('submit');
  await drain();
  assert.equal(ui.approvalCalls().length, 2);
  assert.equal(ui.approvalCalls()[1].options.headers.Authorization, 'Bearer replacement-reviewer');
  assert.equal(ui.el('approveSend').disabled, true);
});

test('a non-APPROVED policy result keeps the current candidate available for retry', async () => {
  const ui = createConsole(() => Promise.resolve(response({status: 'BLOCK'})));
  await ui.candidate();
  ui.el('approvalForm').dispatch('submit');
  await drain();
  assert.equal(ui.el('approveSend').disabled, false);
  assert.equal(JSON.parse(ui.el('approvalResult').textContent).status, 'BLOCK');
});

for (const outcome of ['aborted request', 'late successful response']) {
  test(`changing the API key during ${outcome} keeps approval disabled and suppresses stale output`, async () => {
    let finish;
    const ui = createConsole(options => new Promise((resolve, reject) => {
      finish = () => resolve(response({status: 'APPROVED'}));
      if (outcome === 'aborted request') options.signal.addEventListener('abort', () => {
        const error = new Error('Request aborted after changing tenant');
        error.name = 'AbortError';
        reject(error);
      }, {once: true});
    }));
    await ui.candidate();
    ui.el('approvalForm').dispatch('submit');
    await drain(); // Both read-only identity checks must complete before the POST is in flight.
    assert.equal(ui.el('approveSend').disabled, true);
    ui.el('apiKey').value = 'next-tenant-key';
    ui.el('apiKey').dispatch('input');
    finish();
    await drain();
    assert.equal(ui.el('approveSend').disabled, true);
    assert.equal(ui.el('approverKey').value, '');
    assert.equal(ui.el('approvalResult').textContent, 'Brak zatwierdzenia dla aktualnej sesji.');
    assert.equal(ui.el('humanStatus').textContent, 'UNKNOWN');
    assert.equal(ui.el('toast').classList.contains('hidden'), true, 'old request errors must not enter the new session');
    assert.equal(ui.el('statusLog').children.some(child => /BŁĄD|POST approval/.test(child.textContent)), false);
    ui.el('approvalForm').dispatch('submit');
    await drain();
    assert.equal(ui.approvalCalls().length, 1, 'reset must discard the old candidate');
  });
}
