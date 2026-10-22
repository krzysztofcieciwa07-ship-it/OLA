'use strict';

// Browser-facing integration behaviors of the real inline page scripts.
// The DOM and fetch boundary are isolated doubles; no Windows/LLM claim.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const {createDom, response, drain} = require('./helpers/inline_dom.cjs');

const html = fs.readFileSync(process.env.OLA_UI_TEST_HTML || path.join(__dirname, '../web/index.html'), 'utf8');

function consolePage({protocol = 'http:', width = 1280, reducedMotion = false} = {}) {
  const dom = createDom(html);
  const calls = [];
  const location = {protocol, hostname: protocol === 'file:' ? '' : '127.0.0.1', port: '18081'};
  const context = vm.createContext({
    document: dom.document, location,
    window: {location, innerWidth: width, confirm: () => true},
    matchMedia: () => ({matches: reducedMotion}),
    MutationObserver: class { observe() {} },
    Option: function Option(text, value) { this.text = text; this.value = value; },
    AbortController, setTimeout: () => 0, clearTimeout() {}, setInterval() {},
    fetch(url, options) {
      calls.push({url, options});
      if (url === '/health') return Promise.resolve(response({status: 'ok'}));
      if (url === '/openapi.json') return Promise.resolve(response({paths: {'/evidence/{id}': {get: {}}}}));
      throw new Error('Unexpected network request: ' + url);
    },
  });
  for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)) {
    vm.runInContext(match[1], context, {filename: 'web/index.html:frontend-integration'});
  }
  return {...dom, calls};
}

test('file preview makes no relative API calls and refuses credentials before network use', async () => {
  const ui = consolePage({protocol: 'file:'});
  await drain();
  assert.deepEqual(ui.calls, [], 'file preview must not issue health or OpenAPI requests');
  assert.equal(ui.el('runtimeGuidance').hidden, false);
  assert.equal(ui.el('healthStatus').textContent, 'UNKNOWN');
  assert.equal(ui.el('localConnect').disabled, true);

  ui.el('apiKey').value = 'must-not-be-transmitted';
  ui.el('verifyApiKey').dispatch('click');
  await drain();
  assert.deepEqual(ui.calls, [], 'verification in file preview must stay local');
  assert.equal(ui.el('keyState').textContent, 'ODRZUCONY');
  assert.match(ui.el('toast').textContent, /file:\/\//);
});

test('HTTP runtime retains health and OpenAPI discovery without file-preview warning', async () => {
  const ui = consolePage();
  await drain();
  assert.deepEqual(ui.calls.map(call => call.url), ['/health', '/openapi.json']);
  assert.equal(ui.el('runtimeGuidance').hidden, true);
  assert.equal(ui.el('healthStatus').textContent, 'ONLINE');
  assert.equal(ui.el('ccEvidence').textContent, 'ROUTE READY');
});

for (const reducedMotion of [false, true]) {
  test(`navigation updates aria-current and respects reduced-motion=${reducedMotion}`, async () => {
    const ui = consolePage({width: 375, reducedMotion});
    await drain();
    const buttons = ui.document.querySelectorAll('.nav-btn');
    const settings = buttons.find(button => button.dataset.view === 'settings');
    const chat = buttons.find(button => button.dataset.view === 'chat');
    settings.dispatch('click');
    assert.equal(settings.getAttribute('aria-current'), 'page');
    assert.equal(ui.el('panel-settings').hidden, false);
    assert.equal(ui.el('panel-chat').hidden, true);
    chat.dispatch('click');
    assert.equal(settings.getAttribute('aria-current'), null);
    assert.equal(chat.getAttribute('aria-current'), 'page');
    assert.equal(ui.el('panel-settings').hidden, true);
    assert.equal(ui.el('panel-chat').hidden, false);
    assert.equal(ui.el('workspacePanel').scrolls.at(-1).behavior, reducedMotion ? 'auto' : 'smooth');
  });
}

test('Escape dismisses the current error toast', async () => {
  const ui = consolePage();
  await drain();
  ui.el('searchInput').value = 'zzzz';
  ui.el('searchForm').dispatch('submit');
  assert.equal(ui.el('toast').classList.contains('hidden'), false);
  ui.document.dispatch('keydown', {key: 'Escape'});
  assert.equal(ui.el('toast').classList.contains('hidden'), true);
  assert.equal(ui.el('toast').textContent, '');
});
