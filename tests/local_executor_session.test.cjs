'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const {createDom, inlineScript, response, drain, deferred} = require('./helpers/inline_dom.cjs');

const actions = {status: 'BRIDGE_ONLINE', actions: [{id: 'git-status', label: 'Git status', mode: 'read'}]};
const completed = {status: 'OK', action: 'git-status', exit_code: 0, output: 'output-from-session-A'};
function createBridge(handler) {
  const dom = createDom();
  const calls = [];
  vm.runInNewContext(inlineScript('AURORA local-host bridge'), {
    document: dom.document,
    location: {protocol: 'http:', hostname: '127.0.0.1', port: '18081'},
    Option: function Option(text, value) { this.text = text; this.value = value; },
    window: {confirm: () => true}, AbortController,
    setTimeout: () => 0, clearTimeout() {},
    fetch(url, options) { const call = {url, options}; calls.push(call); return handler(call); },
  }, {filename: 'web/index.html:local-executor'});
  return {...dom, calls,
    token(value) { dom.el('localToken').value = value; dom.el('localToken').dispatch('input'); },
    connect() { dom.el('localConnect').dispatch('click'); },
    run() { dom.el('localRun').dispatch('click'); },
  };
}
function assertDisconnected(ui) {
  assert.equal(ui.el('localState').textContent, 'NIEPODŁĄCZONE');
  assert.equal(ui.el('localState').classList.contains('connected'), false);
  assert.equal(ui.el('localRun').disabled, true);
  assert.equal(ui.el('localAction').disabled, true);
}

for (const change of ['replace', 'clear', 'disconnect']) {
  test(`${change} during first connection discards an old successful action list`, async () => {
    const pending = deferred();
    const ui = createBridge(() => pending.promise);
    ui.token('session-A'); ui.connect();
    assert.equal(ui.calls[0].options.headers.Authorization, 'Bearer session-A');
    if (change === 'disconnect') ui.el('localDisconnect').dispatch('click');
    else ui.token(change === 'clear' ? '' : 'session-B');
    const resetMessage = ui.el('localResult').textContent;
    pending.resolve(response(actions));
    await drain();
    assertDisconnected(ui);
    assert.equal(ui.calls[0].options.signal.aborted, true);
    assert.equal(ui.el('localResult').textContent, resetMessage);
    assert.equal(ui.el('localConnect').disabled, false);
  });
}

test('an old connection error cannot unlock or overwrite a new pending connection', async () => {
  const old = deferred(), current = deferred();
  const ui = createBridge(call => call.options.headers.Authorization === 'Bearer session-A' ? old.promise : current.promise);
  ui.token('session-A'); ui.connect();
  ui.token('session-B'); ui.connect();
  assert.equal(ui.calls.length, 2);
  old.reject(new Error('old connection failed'));
  await drain();
  assert.equal(ui.el('localConnect').disabled, true, 'current request must remain busy');
  assert.doesNotMatch(ui.el('localResult').textContent, /old connection failed/);
  current.resolve(response(actions));
  await drain();
  assert.equal(ui.el('localState').textContent, 'POŁĄCZONO Z ZBOOKIEM');
  assert.equal(ui.el('localRun').disabled, false);
});

test('changing a connected token removes the previous output and action options', async () => {
  const ui = createBridge(call => Promise.resolve(response(call.url.endsWith('/v1/actions') ? actions : completed)));
  ui.token('session-A'); ui.connect(); await drain();
  ui.run(); await drain();
  assert.match(ui.el('localResult').textContent, /output-from-session-A/);
  ui.token('session-B');
  assertDisconnected(ui);
  assert.doesNotMatch(ui.el('localResult').textContent, /output-from-session-A/);
  assert.equal(ui.el('localAction').children.some(option => option.value === 'git-status'), false);
});

for (const outcome of ['success', 'error']) {
  test(`late execution ${outcome} cannot enter the session of a replacement token`, async () => {
    const pending = deferred();
    const ui = createBridge(call => call.url.endsWith('/v1/actions') ? Promise.resolve(response(actions)) : pending.promise);
    ui.token('session-A'); ui.connect(); await drain();
    ui.run();
    ui.token('session-B');
    const resetMessage = ui.el('localResult').textContent;
    if (outcome === 'success') pending.resolve(response(completed));
    else pending.reject(new Error('old execution failed'));
    await drain();
    assertDisconnected(ui);
    assert.equal(ui.el('localResult').textContent, resetMessage);
    assert.equal(ui.calls[1].options.signal.aborted, true);
  });
}

test('a failed explicit reconnect disables previously registered actions', async () => {
  let requests = 0;
  const ui = createBridge(() => Promise.resolve(++requests === 1 ? response(actions) : response({error:'TOKEN_EXPIRED'}, 401)));
  ui.token('session-A'); ui.connect(); await drain();
  assert.equal(ui.el('localRun').disabled, false);
  ui.connect(); await drain();
  assertDisconnected(ui);
  assert.match(ui.el('localResult').textContent, /LOCAL 401/);
});

test('a connected session still runs a registered read action with its own token', async () => {
  const ui = createBridge(call => Promise.resolve(response(call.url.endsWith('/v1/actions') ? actions : completed)));
  ui.token('session-A'); ui.connect(); await drain();
  ui.run(); await drain();
  assert.equal(ui.calls.length, 2);
  assert.equal(ui.calls[1].options.headers.Authorization, 'Bearer session-A');
  assert.equal(JSON.parse(ui.calls[1].options.body).action, 'git-status');
  assert.match(ui.el('localResult').textContent, /output-from-session-A/);
  assert.equal(ui.el('localRun').disabled, false);
});
