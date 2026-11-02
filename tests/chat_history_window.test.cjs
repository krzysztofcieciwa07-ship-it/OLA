'use strict';

// Executes the actual inline chat handler against a bounded API double.
// Isolated UI tests: no provider inference, HTTP server, Windows or E2E claim.
const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const {createDom, inlineScript, response, drain, deferred} = require('./helpers/inline_dom.cjs');

// /chat currently accepts at most 20 messages (app/chat_runtime.py).
const API_MAX_HISTORY = 20;

function createChat(answer = messages => ({
  status: 'VERIFIED', scope: 'CHAT_ONLY', message: 'Odpowiedź: ' + messages.at(-1).content,
})) {
  const {el, document} = createDom();
  const requests = [];
  el('toast').classList.add('hidden');
  const fetch = (url, options) => {
    if (url === '/health') return Promise.resolve(response({status: 'ok'}));
    assert.equal(url, '/chat', 'this check must not invoke another operation');
    const messages = JSON.parse(options.body).messages;
    requests.push({messages, token: options.headers['X-API-Key'], signal: options.signal});
    if (messages.length > API_MAX_HISTORY) {
      return Promise.resolve(response({status: 'BLOCK', reason: 'invalid or excessive chat history'}));
    }
    return Promise.resolve(answer(messages, requests.length, options)).then(response);
  };
  vm.runInNewContext(inlineScript('const session='), {
    document, fetch, AbortController,
    window: {innerWidth: 1280, location: {hostname: 'example.invalid', protocol: 'http:'}},
    setTimeout: () => 0, clearTimeout() {}, setInterval() {},
  }, {filename: 'web/index.html:chat-history'});
  el('apiKey').value = 'isolated-operator';
  return {
    el, requests,
    async send(text) {
      el('chatInput').value = text;
      el('chatForm').dispatch('submit');
      await drain();
      return requests.at(-1);
    },
  };
}

function expectedWindow(turn) {
  const expected = [];
  for (let previous = Math.max(1, turn - 9); previous < turn; previous++) {
    expected.push({role: 'user', content: 'Pytanie ' + previous});
    expected.push({role: 'assistant', content: 'Odpowiedź: Pytanie ' + previous});
  }
  expected.push({role: 'user', content: 'Pytanie ' + turn});
  return expected;
}

test('30 chat turns keep complete recent pairs and the latest question within the API limit', async () => {
  const ui = createChat();
  for (let turn = 1; turn <= 30; turn++) {
    const request = await ui.send('Pytanie ' + turn);
    assert.ok(request.messages.length <= API_MAX_HISTORY, `turn ${turn} exceeds the API history limit`);
    assert.deepEqual(request.messages, expectedWindow(turn), `turn ${turn} must retain nine complete pairs and the latest question`);
    assert.equal(request.messages[0].role, 'user');
    assert.equal(request.messages.at(-1).role, 'user');
    assert.equal(ui.el('chatInput').value, '', `turn ${turn} should complete successfully`);
    assert.equal(ui.el('chatSend').disabled, false);
  }
  assert.equal(ui.requests.length, 30);
  assert.equal(ui.el('chatMessages').children.length, 60, 'the visible conversation must retain all accepted turns');
  assert.equal(ui.el('chatMessages').children[0].textContent, 'Ty: Pytanie 1');
  assert.equal(ui.el('chatMessages').children.at(-1).textContent, 'NINA: Odpowiedź: Pytanie 30');
});

test('BLOCK can be retried without inserting a failed exchange into the accepted history', async () => {
  const ui = createChat((messages, attempt) => attempt === 3
    ? {status: 'BLOCK', reason: 'provider unavailable'}
    : {status: 'VERIFIED', scope: 'CHAT_ONLY', message: 'Odpowiedź: ' + messages.at(-1).content});
  await ui.send('Pytanie 1');
  await ui.send('Pytanie 2');
  const blocked = await ui.send('Pytanie 3');
  assert.deepEqual(blocked.messages, expectedWindow(3));
  assert.equal(ui.el('chatInput').value, 'Pytanie 3');
  assert.equal(ui.el('chatSend').disabled, false);
  assert.equal(ui.el('chatMessages').children.at(-1).textContent, 'NINA BLOCK: provider unavailable');
  const retried = await ui.send('Pytanie 3');
  assert.deepEqual(retried.messages, blocked.messages, 'retry must reuse only previously accepted exchanges');
  assert.equal(ui.el('chatInput').value, '');
  const next = await ui.send('Pytanie 4');
  assert.deepEqual(next.messages, expectedWindow(4), 'the successful retry must appear exactly once');
});

test('changing the API key clears a full history window before the next question', async () => {
  const ui = createChat();
  for (let turn = 1; turn <= 10; turn++) await ui.send('Pytanie ' + turn);
  ui.el('apiKey').value = 'next-isolated-operator';
  ui.el('apiKey').dispatch('input');
  const request = await ui.send('Nowa rozmowa');
  assert.equal(request.token, 'next-isolated-operator');
  assert.deepEqual(request.messages, [{role: 'user', content: 'Nowa rozmowa'}]);
  assert.equal(ui.el('chatMessages').children.some(item => item.textContent.includes('Pytanie')), false);
  assert.equal(ui.el('chatInput').value, '');
});

test('a late answer after an API key reset cannot repopulate the new chat context', async () => {
  const pending = deferred();
  const ui = createChat((messages, attempt) => attempt === 2 ? pending.promise
    : {status: 'VERIFIED', scope: 'CHAT_ONLY', message: 'Odpowiedź: ' + messages.at(-1).content});
  await ui.send('Pytanie 1');
  ui.el('chatInput').value = 'Stare pytanie w toku';
  ui.el('chatForm').dispatch('submit');
  assert.equal(ui.requests.length, 2);
  ui.el('apiKey').value = 'new-chat-operator';
  ui.el('apiKey').dispatch('input');
  assert.equal(ui.requests[1].signal.aborted, true);
  pending.resolve({status: 'VERIFIED', scope: 'CHAT_ONLY', message: 'Stara odpowiedź'});
  await drain();
  assert.equal(ui.el('chatMessages').children.some(item => item.textContent.includes('Stara odpowiedź')), false);
  const request = await ui.send('Pytanie nowej sesji');
  assert.equal(request.token, 'new-chat-operator');
  assert.deepEqual(request.messages, [{role: 'user', content: 'Pytanie nowej sesji'}]);
  assert.equal(ui.el('chatMessages').children.some(item => item.textContent.includes('Pytanie 1')), false);
});
