'use strict';

// The actual Aurora handlers with isolated HTTP/DOM doubles. This is not a
// Windows, live authentication, distinct-person or end-to-end verification.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const {createDom, inlineScript, response, drain, deferred} = require('./helpers/inline_dom.cjs');

const EMPTY_IDENTITY = 'Brak zweryfikowanej sesji.';
const validSession = (compact = false) => ({
  authenticated: true,
  tenant_id: compact ? '83ef66c54e0241b6a1107826de1a22b0' : '83ef66c5-4e02-41b6-a110-7826de1a22b0',
  credential_id: compact ? 'd2675149c5f140a5aa7b328d3dc329df' : 'd2675149-c5f1-40a5-aa7b-328d3dc329df',
  scope: 'OLA_CORE',
});

function createConsole(authenticate = () => response(validSession())) {
  const {el, document} = createDom();
  const requests = [];
  el('toast').classList.add('hidden');
  const fetch = (url, options) => {
    if (url === '/health') return Promise.resolve(response({status: 'ok'}));
    assert.equal(url, '/auth/session', 'identity verification must use the real auth endpoint');
    requests.push(options);
    return Promise.resolve(authenticate(options, requests.length));
  };
  vm.runInNewContext(inlineScript('const session='), {
    document, fetch, AbortController,
    window: {innerWidth: 1280, location: {hostname: 'example.invalid', protocol: 'http:'}},
    setTimeout: () => 0, clearTimeout() {}, setInterval() {},
  }, {filename: 'web/index.html:operator-session-identity'});
  return {
    el, requests,
    async verify(key = 'isolated-core-key') {
      el('apiKey').value = key;
      el('verifyApiKey').dispatch('click');
      await drain();
    },
    identity() { return el('operatorIdentity').textContent; },
    logs() { return el('statusLog').children.map(item => item.textContent).join('\n'); },
  };
}

test('SETTINGS exposes an initially empty accessible identity output', () => {
  const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
  assert.ok(/<pre\b[^>]*\bid="operatorIdentity"[^>]*\baria-live="polite"[^>]*>Brak zweryfikowanej sesji\.<\/pre>/.test(html),
    'SETTINGS needs an accessible identity output with an unverified default');
  const ui = createConsole();
  assert.equal(ui.identity(), EMPTY_IDENTITY);
  assert.equal(ui.requests.length, 0, 'identifiers must not be guessed before authentication');
});

for (const [compact, uppercase] of [[false, false], [true, false], [false, true], [true, true]]) {
  test(`authenticated ${uppercase ? 'uppercase' : 'lowercase'} ${compact ? 'compact' : 'hyphenated'} UUID identifiers are complete and allowlisted`, async () => {
    const session = validSession(compact);
    if (uppercase) {
      session.tenant_id = session.tenant_id.toUpperCase();
      session.credential_id = session.credential_id.toUpperCase();
    }
    const data = {...session, key_hash: 'never-render-hash', api_key: 'never-render-key',
      nested: {secret: 'never-render-nested'}, display_name: '<img src=x onerror=alert(1)>'};
    const ui = createConsole(() => response(data));
    await ui.verify('request-secret-never-render');
    assert.equal(ui.el('keyState').textContent, 'UWIERZYTELNIONY');
    assert.deepEqual(JSON.parse(ui.identity()), {
      tenant_id: data.tenant_id, credential_id: data.credential_id, scope: 'OLA_CORE',
    });
    assert.equal(ui.requests[0].headers['X-API-Key'], 'request-secret-never-render');
    assert.equal(ui.requests[0].method, 'GET');
    for (const output of [ui.identity(), ui.logs(), ui.el('toast').textContent]) {
      assert.doesNotMatch(output, /request-secret-never-render|never-render|<img|key_hash|api_key|nested/);
    }
    assert.equal(ui.el('operatorIdentity').children.length, 0, 'identity output must remain plain text');
    assert.equal(ui.el('operatorIdentity').innerHTML, undefined);
  });
}

const malformed = [
  ['missing credential', (() => { const data = validSession(); delete data.credential_id; return data; })()],
  ['null credential', {...validSession(), credential_id: null}],
  ['numeric credential', {...validSession(), credential_id: 42}],
  ['object credential', {...validSession(), credential_id: {value: 'not-an-id'}}],
  ['XSS credential', {...validSession(), credential_id: '<img src=x onerror=alert(1)>'}],
  ['empty tenant', {...validSession(), tenant_id: ''}],
  ['numeric tenant', {...validSession(), tenant_id: 123}],
  ['XSS tenant', {...validSession(), tenant_id: '<script>alert(1)</script>'}],
  ['malformed UUID hyphens', {...validSession(), credential_id: 'd2675149-c5f140a5-aa7b-328d3dc329df'}],
  ['UUID with trailing newline', {...validSession(), credential_id: validSession().credential_id + '\n'}],
  ['UUID with trailing space', {...validSession(), tenant_id: validSession().tenant_id + ' '}],
  ['wrong scope', {...validSession(), scope: 'OLA_ADMIN'}],
  ['missing scope', (() => { const data = validSession(); delete data.scope; return data; })()],
  ['unconfirmed authentication', {...validSession(), authenticated: false}],
  ['string authentication', {...validSession(), authenticated: 'true'}],
  ['null response', null],
  ['array response', []],
];
for (const [name, data] of malformed) {
  test(`malformed session is rejected: ${name}`, async () => {
    const ui = createConsole(() => response(data));
    await ui.verify();
    assert.equal(ui.el('keyState').textContent, 'ODRZUCONY');
    assert.equal(ui.identity(), EMPTY_IDENTITY);
    assert.doesNotMatch(ui.logs(), /AUTHENTICATED/);
    assert.equal(ui.el('verifyApiKey').disabled, false);
  });
}

for (const action of ['edit', 'forget']) {
  test(`${action} removes previously verified identifiers immediately`, async () => {
    const ui = createConsole();
    await ui.verify();
    assert.equal(JSON.parse(ui.identity()).scope, 'OLA_CORE');
    if (action === 'edit') {
      ui.el('apiKey').value = 'new-unverified-key';
      ui.el('apiKey').dispatch('input');
    } else ui.el('forgetKey').dispatch('click');
    assert.equal(ui.identity(), EMPTY_IDENTITY);
    assert.equal(ui.el('keyState').textContent, action === 'edit' ? 'NIEZWERYFIKOWANY' : 'NIEPODANY');
  });
}

test('reverification clears old identifiers before waiting and keeps them cleared on failure', async () => {
  const pending = deferred();
  const ui = createConsole((options, attempt) => attempt === 1 ? response(validSession()) : pending.promise);
  await ui.verify();
  assert.equal(JSON.parse(ui.identity()).scope, 'OLA_CORE');
  ui.el('verifyApiKey').dispatch('click');
  assert.equal(ui.el('keyState').textContent, 'SPRAWDZANIE');
  assert.equal(ui.identity(), EMPTY_IDENTITY);
  pending.resolve(response({detail: 'credential revoked'}, 401));
  await drain();
  assert.equal(ui.el('keyState').textContent, 'ODRZUCONY');
  assert.equal(ui.identity(), EMPTY_IDENTITY);
});

for (const outcome of ['success', 'error']) {
  test(`stale authentication ${outcome} cannot restore identifiers or overwrite a reset session`, async () => {
    const pending = deferred();
    const ui = createConsole(() => pending.promise);
    ui.el('apiKey').value = 'old-session-key';
    ui.el('verifyApiKey').dispatch('click');
    assert.equal(ui.requests.length, 1);
    ui.el('apiKey').value = 'new-session-key';
    ui.el('apiKey').dispatch('input');
    assert.equal(ui.requests[0].signal.aborted, true);
    if (outcome === 'success') pending.resolve(response(validSession()));
    else pending.reject(new Error('stale authentication failure'));
    await drain();
    assert.equal(ui.identity(), EMPTY_IDENTITY);
    assert.equal(ui.el('keyState').textContent, 'NIEZWERYFIKOWANY');
    assert.doesNotMatch(ui.logs(), /AUTHENTICATED|BLOCK|stale authentication failure/);
    assert.equal(ui.el('toast').classList.contains('hidden'), true);
    assert.equal(ui.el('verifyApiKey').disabled, false);
  });
}
