import {api, safeOrigin, summarize, evidenceIds, scopedReport} from './model.mjs';
const $ = id => document.getElementById(id);
let sessionKey = '', tenant = '', epoch = 0, busy = false, exported = null, messages = [];
const controllers = new Set();
const labels = ['Wykonanie NINA', 'Dowody', 'Raport IGOR', 'Integralność replay', 'Zgoda człowieka'];
function badge(node, value) { node.textContent = value; node.dataset.state = value; }
function gates(values = {}) {
  $('gates').replaceChildren();
  for (const label of labels) {
    const card = document.createElement('div'), title = document.createElement('h3'), state = document.createElement('span');
    card.className = 'gate'; title.textContent = label; state.className = 'badge'; badge(state, values[label] ?? 'UNKNOWN');
    card.append(title, state); $('gates').append(card);
  }
}
function controls() {
  $('task-fields').disabled = $('chat-fields').disabled = !sessionKey || busy;
  $('access-form').hidden = !!sessionKey;
  $('disconnect').hidden = !sessionKey;
  $('export').disabled = !exported || busy;
}
function clearResult() {
  exported = null; badge($('decision'), 'UNKNOWN'); gates();
  $('result-text').textContent = 'Czeka na Twoje zadanie.';
  $('result-note').textContent = 'Brak uruchomienia. Brak dowodów.';
  for (const id of ['mode', 'model', 'run-id']) $(id).textContent = '—';
  $('raw').textContent = 'Brak danych.'; $('evidence').replaceChildren();
  $('proof-note').textContent = 'Dostępność API nie potwierdza działania modelu ani gotowości produkcyjnej.';
}
function disconnect(message = 'Odłączono. Dane tej karty zostały wyczyszczone.') {
  epoch++; for (const controller of controllers) controller.abort(); controllers.clear();
  sessionKey = ''; tenant = ''; messages = []; busy = false; $('key').value = '';
  $('task').value = ''; $('chat-input').value = ''; $('messages').replaceChildren();
  clearResult(); controls(); $('notice').textContent = message;
  $('access-info').textContent = 'Użyj istniejącego klucza API swojej organizacji. Klucz pozostaje tylko w pamięci tej karty.';
}
async function request(path, options = {}, timeout = 15000) {
  const controller = new AbortController(); controllers.add(controller);
  const timer = setTimeout(() => controller.abort(), timeout);
  try { return await api(path, {...options, signal: controller.signal}); }
  finally { clearTimeout(timer); controllers.delete(controller); }
}
function message(role, text) {
  const node = document.createElement('div'); node.className = 'message';
  node.textContent = `${role}: ${text}`; $('messages').append(node);
}
async function checkHealth() {
  try {
    const result = await request('/health');
    if (result.status !== 'ok') throw new Error('health');
    $('connection').textContent = 'API odpowiada'; $('connection').dataset.state = 'ok';
  } catch { $('connection').textContent = 'API niepotwierdzone'; $('connection').dataset.state = 'UNKNOWN'; }
}
$('access-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy) return;
  if (!safeOrigin(window.location)) { $('notice').textContent = 'Klucz można przesłać wyłącznie przez HTTPS lub lokalny adres loopback.'; return; }
  const candidate = $('key').value.trim(); if (!candidate) return;
  const generation = ++epoch; busy = true; $('connect').disabled = true;
  $('key').value = ''; $('notice').textContent = 'Backend sprawdza klucz…';
  try {
    const session = await request('/console/session', {key: candidate});
    if (generation !== epoch) return;
    if (typeof session.tenant_id !== 'string' || !session.tenant_id) throw new Error('Niepoprawna odpowiedź uwierzytelniania.');
    sessionKey = candidate; tenant = session.tenant_id;
    $('access-info').textContent = `Połączono z organizacją ${tenant}. Klucz nie jest zapisywany w przeglądarce.`;
    $('notice').textContent = 'Dostęp potwierdzony przez backend. Możesz wysłać zadanie.';
  } catch (error) { if (generation === epoch) $('notice').textContent = error.message; }
  finally { if (generation === epoch) { busy = false; $('connect').disabled = false; controls(); } }
});
$('disconnect').addEventListener('click', () => disconnect());
window.addEventListener('pagehide', () => disconnect());
$('task-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !sessionKey) return;
  const task = $('task').value.trim(); if (!task) return;
  const generation = epoch; busy = true; clearResult(); controls();
  $('result-text').textContent = 'Oczekiwanie na backend…';
  $('notice').textContent = 'Wysłano jedno żądanie. Oczekiwanie nie jest potwierdzeniem wykonania.';
  let response = null;
  try {
    response = await request('/nina-run', {key: sessionKey, body: {task, requested_tools: ['safe_expression']}}, 420000);
    if (generation !== epoch) return;
    if (['BLOCK', 'BLOCKED'].includes(response.status) && !response.run_id) {
      badge($('decision'), response.status);
      $('result-text').textContent = 'Wykonanie zablokowane.';
      $('result-note').textContent = response.nina?.reason ?? 'Backend nie zezwolił na wykonanie.';
      $('notice').textContent = 'Nie otrzymano identyfikatora wykonania ani dowodów.';
      return;
    }
    const ids = evidenceIds(response), records = [];
    for (const id of ids) {
      records.push(await request(`/evidence/${id}`, {key: sessionKey}));
      if (generation !== epoch) return;
    }
    const view = summarize(response, records, tenant, task);
    badge($('decision'), view.decision); gates(view.gates);
    $('result-text').textContent = view.result ?? 'Wynik niepotwierdzony.';
    $('result-note').textContent = view.issues.length ? view.issues.join(' ') : 'Wynik odczytany z dowodu tego wykonania. Decyzję o dalszym wykonaniu pokazuje osobny status.';
    $('mode').textContent = view.mode; $('model').textContent = view.model; $('run-id').textContent = view.run;
    $('proof-note').textContent = `Pobrano ${records.length} dowodów. Statusy IGOR i replay pochodzą z API. Ten raport nie potwierdza wdrożenia produkcyjnego.`;
    for (const record of records) {
      const row = document.createElement('div'), hash = document.createElement('code');
      row.className = 'evidence-row'; row.textContent = `${record.record_type} · ${record.id}`;
      hash.textContent = record.record_hash; row.append(hash); $('evidence').append(row);
    }
    exported = scopedReport(response, records, view); $('raw').textContent = JSON.stringify(exported, null, 2);
    $('notice').textContent = view.decision === 'REVIEW' ? 'Wykonanie zakończone. Dalszy krok wymaga niezależnej zgody człowieka.' : `Stan odpowiedzi: ${view.decision}.`;
  } catch (error) {
    if (generation !== epoch) return;
    if (error.code === 401) { disconnect('Klucz nie został zaakceptowany. Połącz się ponownie.'); return; }
    $('result-text').textContent = 'Wynik niepotwierdzony.';
    $('run-id').textContent = typeof response?.run_id === 'string' ? response.run_id : 'Nie otrzymano identyfikatora.';
    $('notice').textContent = `${error.message} Serwer mógł wykonać zadanie. Nie ponawiam go automatycznie; przed kolejną próbą sprawdź dowody.`;
    $('result-note').textContent = 'Nie uzyskano kompletnej odpowiedzi i dowodów. Status pozostaje UNKNOWN.';
  } finally { if (generation === epoch) { busy = false; controls(); } }
});
$('chat-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !sessionKey) return;
  const text = $('chat-input').value.trim(); if (!text) return;
  const generation = epoch, candidate = [...messages, {role: 'user', content: text}].slice(-19);
  busy = true; controls(); $('notice').textContent = 'NINA przygotowuje odpowiedź…';
  try {
    const data = await request('/chat', {key: sessionKey, body: {messages: candidate}}, 60000);
    if (generation !== epoch) return;
    if (data.status !== 'VERIFIED' || typeof data.message !== 'string') throw new Error('Czat nie zwrócił poprawnej odpowiedzi. Sprawdź konfigurację modelu.');
    messages = [...candidate, {role: 'assistant', content: data.message}];
    message('Ty', text); message('NINA', data.message); $('chat-input').value = '';
    $('notice').textContent = 'Otrzymano odpowiedź czatu. Nie zmienia ona statusów wykonania i dowodów.';
  } catch (error) {
    if (generation !== epoch) return;
    if (error.code === 401) { disconnect('Klucz nie został zaakceptowany. Połącz się ponownie.'); return; }
    $('notice').textContent = error.message;
  } finally { if (generation === epoch) { busy = false; controls(); } }
});
$('export').addEventListener('click', () => {
  if (!exported || busy) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], {type: 'application/json'}));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'ola-console-observation.json';
  document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
clearResult(); controls(); checkHealth();
