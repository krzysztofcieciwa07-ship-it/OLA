'use strict';

// Actual Aurora inline handlers with disposable DOM/fetch doubles.
// These tests establish neither human identity nor physical Windows readiness.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const {createDom, inlineScript, response, drain, deferred} = require('./helpers/inline_dom.cjs');

const TENANT = '1177d13f-1e08-40ce-a7fe-a2fd101fca83';
const OPERATOR_ID = '4efc4586-4ea8-4cf1-848f-c03bfa3d8ea7';
const REVIEWER_ID = '97d61b88-fea7-4f44-9f85-a1c9fcab745f';
const CORE_KEY = 'disposable-core-secret';
const REVIEW_KEY = 'disposable-review-secret';
const identity = (scope, credential_id) => ({authenticated: true, tenant_id: TENANT, credential_id, scope});
const current = status => ({status, scope: 'review-result', assurance: 'UNKNOWN', production_eligible: false,
  reviewer_credential_status: status === 'BLOCKED' ? 'REVOKED' : 'ACTIVE'});

function createConsole(options = {}) {
  const dom = createDom();
  const calls = [], intervals = [];
  let reviewState = 'APPROVED';
  const fetch = (url, request) => {
    const call = {url, request}; calls.push(call);
    if (url === '/health') return Promise.resolve(response({status: 'ok'}));
    if (url === '/auth/session') {
      const isCore = request.headers['X-API-Key'] === CORE_KEY;
      return Promise.resolve(options.auth ? options.auth(call, isCore) : response(
        isCore ? identity('OLA_CORE', OPERATOR_ID) : identity('REVIEW_RESULT', REVIEWER_ID)));
    }
    if (url === '/nina-run') return Promise.resolve(response({status: 'REVIEW', run_id: 'test-run', tip_hash: 'bound-tip',
      status_fields: {HUMAN_GATE: 'REVIEW'}, decision_report_v2: {report_sha256: 'bound-report'}}));
    if (url === '/nina-run/test-run/approve') return Promise.resolve(options.approve ? options.approve(call) : response({
      status: 'APPROVED', scope: 'review-result', assurance: 'UNKNOWN', production_eligible: false,
      approver_id: REVIEWER_ID, approved_tip_hash: 'bound-tip'}));
    if (url === '/nina-run/test-run/approval') return Promise.resolve(options.review ? options.review(call) : response(current(reviewState)));
    throw new Error('Unexpected request: ' + url);
  };
  vm.runInNewContext(inlineScript('const session='), {
    document: dom.document, fetch, AbortController,
    window: {innerWidth: 1280, location: {hostname: 'example.invalid', protocol: 'http:'}},
    setTimeout: () => 0, clearTimeout() {}, setInterval(callback, ms) { intervals.push({callback, ms}); },
  }, {filename: 'web/index.html:reviewer-credential'});
  return {...dom, calls,
    async candidate() {
      dom.el('apiKey').value = CORE_KEY;
      dom.el('runTask').value = 'Calculate 17 * 23';
      dom.el('runForm').dispatch('submit'); await drain();
      assert.equal(dom.el('approveSend').disabled, false);
      dom.el('approverKey').value = REVIEW_KEY;
    },
    async approve() { dom.el('approvalForm').dispatch('submit'); await drain(); },
    async poll(status) {
      if (status) reviewState = status;
      const poller = intervals.find(timer => timer.ms === 15000);
      assert.ok(poller, 'current review needs a 15-second read-only refresh');
      poller.callback(); await drain();
    },
    posts() { return calls.filter(call => call.url.endsWith('/approve')); },
    authCalls() { return calls.filter(call => call.url === '/auth/session'); },
    reviewCalls() { return calls.filter(call => call.url.endsWith('/approval')); },
  };
}

test('approval checks Core and REVIEW_RESULT identity before POST, then reads current state with Core', async () => {
  const ui = createConsole(); await ui.candidate(); await ui.approve();
  assert.deepEqual(ui.authCalls().map(call => call.request.headers['X-API-Key']), [CORE_KEY, REVIEW_KEY]);
  assert.equal(ui.posts().length, 1);
  assert.deepEqual(JSON.parse(ui.posts()[0].request.body), {tip_hash: 'bound-tip', report_sha256: 'bound-report',
    scope: 'review-result', reason: 'Manual result review from OLA Aurora console'});
  assert.equal(ui.posts()[0].request.headers.Authorization, 'Bearer ' + REVIEW_KEY);
  assert.equal(ui.reviewCalls()[0].request.headers.Authorization, 'Bearer ' + CORE_KEY);
  const shown = JSON.parse(ui.el('approvalResult').textContent);
  assert.equal(shown.status, 'APPROVED');
  assert.equal(shown.current_review.reviewer_credential_status, 'ACTIVE');
  assert.equal(shown.approved_tip_hash, 'bound-tip');
  assert.equal(ui.el('humanStatus').textContent, 'APPROVED — przegląd wyniku');
  assert.equal(ui.el('approveSend').disabled, true);
  assert.equal(ui.el('approverKey').value, '');
  assert.doesNotMatch(ui.el('approvalResult').textContent, /disposable-.*-secret/);
});

test('completed approval removes reviewer secret before the current-state read finishes', async () => {
  const pending = deferred();
  const ui = createConsole({review: () => pending.promise});
  await ui.candidate();
  ui.el('approvalForm').dispatch('submit');
  await drain();
  assert.equal(ui.posts().length, 1);
  assert.equal(ui.reviewCalls().length, 1);
  assert.equal(ui.el('approverKey').value, '', 'a slow read must not retain the completed POST credential');
  pending.resolve(response(current('APPROVED')));
  await drain();
  assert.equal(JSON.parse(ui.el('approvalResult').textContent).status, 'APPROVED');
});

for (const [label, reviewer] of [
  ['Core scope', identity('OLA_CORE', REVIEWER_ID)],
  ['another tenant', {...identity('REVIEW_RESULT', REVIEWER_ID), tenant_id: '2277d13f-1e08-40ce-a7fe-a2fd101fca83'}],
  ['same credential', identity('REVIEW_RESULT', OPERATOR_ID)],
  ['unconfirmed session', {...identity('REVIEW_RESULT', REVIEWER_ID), authenticated: false}],
]) {
  test(`reviewer precheck rejects ${label} without posting`, async () => {
    const ui = createConsole({auth: (_, isCore) => response(isCore ? identity('OLA_CORE', OPERATOR_ID) : reviewer)});
    await ui.candidate(); await ui.approve();
    assert.equal(ui.posts().length, 0);
    assert.equal(ui.el('approverKey').value, '');
    assert.equal(ui.el('approveSend').disabled, false);
    assert.equal(ui.el('toast').classList.contains('hidden'), false);
  });
}

test('review-only main credential cannot act as Core initiator', async () => {
  const ui = createConsole({auth: () => response(identity('REVIEW_RESULT', OPERATOR_ID))});
  await ui.candidate(); await ui.approve();
  assert.equal(ui.authCalls().length, 1);
  assert.equal(ui.posts().length, 0);
  assert.equal(ui.el('approverKey').value, '');
});

for (const failAt of ['auth', 'approve']) {
  test(`${failAt} refusal clears reviewer secret and preserves candidate for retry`, async () => {
    const ui = createConsole(failAt === 'auth'
      ? {auth: () => response({detail: 'credential revoked'}, 401)}
      : {approve: () => response({detail: 'review refused'}, 403)});
    await ui.candidate(); await ui.approve();
    assert.equal(ui.el('approverKey').value, '');
    assert.equal(ui.el('approveSend').disabled, false);
    assert.match(ui.el('toast').textContent, /HTTP (401|403)/);
  });
}

test('key reset during reviewer precheck prevents POST and preserves a new-session reviewer field', async () => {
  const pending = deferred();
  const ui = createConsole({auth: (_, isCore) => isCore ? response(identity('OLA_CORE', OPERATOR_ID)) : pending.promise});
  await ui.candidate(); ui.el('approvalForm').dispatch('submit'); await drain();
  assert.equal(ui.authCalls().length, 2);
  ui.el('apiKey').value = 'new-core'; ui.el('apiKey').dispatch('input');
  ui.el('approverKey').value = 'new-reviewer-entry';
  pending.resolve(response(identity('REVIEW_RESULT', REVIEWER_ID))); await drain();
  assert.equal(ui.posts().length, 0);
  assert.equal(ui.el('approverKey').value, 'new-reviewer-entry');
  assert.equal(ui.el('approveSend').disabled, true);
});

test('editing reviewer while precheck is pending prevents the old token from approving', async () => {
  const pending = deferred();
  const ui = createConsole({auth: (_, isCore) => isCore ? response(identity('OLA_CORE', OPERATOR_ID)) : pending.promise});
  await ui.candidate(); ui.el('approvalForm').dispatch('submit'); await drain();
  ui.el('approverKey').value = 'replacement-reviewer';
  pending.resolve(response(identity('REVIEW_RESULT', REVIEWER_ID))); await drain();
  assert.equal(ui.posts().length, 0);
  assert.equal(ui.el('approverKey').value, 'replacement-reviewer');
});

for (const status of ['STALE', 'BLOCKED', 'REVOKED']) {
  test(`current ${status} replaces historical APPROVED after polling without reviewer secret`, async () => {
    const ui = createConsole(); await ui.candidate(); await ui.approve(); await ui.poll(status);
    assert.equal(ui.posts().length, 1);
    assert.equal(ui.el('approverKey').value, '');
    assert.equal(JSON.parse(ui.el('approvalResult').textContent).status, status);
    assert.equal(ui.el('humanStatus').textContent, status + ' — przegląd wyniku');
    assert.equal(ui.reviewCalls().at(-1).request.headers.Authorization, 'Bearer ' + CORE_KEY);
  });
}

test('manual refresh reads current review and losing that read fails closed', async () => {
  let reads = 0;
  const ui = createConsole({review: () => ++reads === 1 ? response(current('APPROVED')) : response({detail: 'unauthorized'}, 401)});
  await ui.candidate(); await ui.approve();
  ui.el('refreshApproval').dispatch('click'); await drain();
  assert.equal(ui.reviewCalls().length, 2);
  assert.equal(JSON.parse(ui.el('approvalResult').textContent).status, 'UNKNOWN');
  assert.match(ui.el('humanStatus').textContent, /^UNKNOWN/);
});

for (const reviewerStatus of [undefined, 'REVOKED', 'INVALID_SCOPE']) {
  test(`current APPROVED with reviewer status ${reviewerStatus} is rejected as an incomplete contract`, async () => {
    const result = current('APPROVED');
    if (reviewerStatus === undefined) delete result.reviewer_credential_status;
    else result.reviewer_credential_status = reviewerStatus;
    const ui = createConsole({review: () => response(result)});
    await ui.candidate(); await ui.approve();
    assert.equal(JSON.parse(ui.el('approvalResult').textContent).status, 'UNKNOWN');
    assert.match(ui.el('humanStatus').textContent, /^UNKNOWN/);
  });
}

test('forget clears review state and polling cannot read an old tenant', async () => {
  const ui = createConsole(); await ui.candidate(); await ui.approve();
  const calls = ui.reviewCalls().length;
  ui.el('forgetKey').dispatch('click'); await ui.poll();
  assert.equal(ui.reviewCalls().length, calls);
  assert.equal(ui.el('refreshApproval').disabled, true);
  assert.equal(ui.el('approvalResult').textContent, 'Brak zatwierdzenia dla aktualnej sesji.');
  assert.equal(ui.el('humanStatus').textContent, 'UNKNOWN');
});

test('UI explains local key removal without claiming server revocation or independent human identity', () => {
  const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
  assert.match(html, /Usuń klucze z tej karty/);
  assert.match(html, /nie unieważnia.*na serwerze/);
  assert.doesNotMatch(html, /Zatwierdzanie przez niezależnego operatora/);
});

function createMonitor(options = {}) {
  const dom = createDom(), calls = [];
  let status = 'BLOCKED';
  dom.el('apiKey').value = CORE_KEY;
  dom.el('keyState').textContent = 'UWIERZYTELNIONY';
  dom.el('ccRunSelect').add = item => dom.el('ccRunSelect').appendChild(item);
  vm.runInNewContext(inlineScript('Authenticated monitor of existing evidence'), {
    document: dom.document, AbortController,
    Option: function Option(text, value) { this.text = text; this.value = value; },
    MutationObserver: class { observe() {} },
    setTimeout: () => 0, clearTimeout() {}, setInterval() {},
    fetch(url, request) {
      calls.push({url, request});
      if (url === '/control/overview') return Promise.resolve(response({schema: 'ola.command-center.v1', tenant_id: TENANT,
        evidence: {status: 'VERIFIED'}, runs: [{run_id: 'test-run', human_approval_recorded: true}]}));
      if (url === '/control/runs/test-run') return Promise.resolve(response({run_id: 'test-run', status: 'VERIFIED'}));
      if (url === '/nina-run/test-run/approval') return Promise.resolve(response(options.review || current(status)));
      throw new Error('Unexpected monitor request: ' + url);
    },
  }, {filename: 'web/index.html:current-review-monitor'});
  return {...dom, calls, state(value) { status = value; }};
}

test('Control Plane checks current review instead of presenting recorded approval as current permission', async () => {
  const ui = createMonitor(); ui.el('ccRefresh').dispatch('click'); await drain();
  const check = ui.calls.find(call => call.url === '/nina-run/test-run/approval');
  assert.ok(check, 'overview needs the current review state');
  assert.equal(check.request.headers.Authorization, 'Bearer ' + CORE_KEY);
  assert.equal(ui.el('ccL5').textContent, 'BLOCKED');
  assert.equal(JSON.parse(ui.el('ccMonitorDetails').textContent).current_review.status, 'BLOCKED');
});

test('inspecting a recorded run refreshes its review state after revocation', async () => {
  const ui = createMonitor(); ui.state('APPROVED');
  ui.el('ccRefresh').dispatch('click'); await drain();
  ui.el('ccRunSelect').value = 'test-run'; ui.state('REVOKED');
  ui.el('ccInspectRun').dispatch('click'); await drain();
  assert.equal(ui.el('ccL5').textContent, 'REVOKED');
  const shown = JSON.parse(ui.el('ccMonitorDetails').textContent);
  assert.equal(shown.run_id, 'test-run');
  assert.equal(shown.current_review.status, 'REVOKED');
});

for (const reviewerStatus of [undefined, 'REVOKED', 'INVALID_SCOPE']) {
  test(`Control Plane rejects APPROVED with reviewer status ${reviewerStatus}`, async () => {
    const result = current('APPROVED');
    if (reviewerStatus === undefined) delete result.reviewer_credential_status;
    else result.reviewer_credential_status = reviewerStatus;
    const ui = createMonitor({review: result});
    ui.el('ccRefresh').dispatch('click'); await drain();
    assert.equal(ui.el('ccL5').textContent, 'UNKNOWN');
    assert.match(ui.el('ccMonitorDetails').textContent, /INVALID_REVIEW_SCHEMA/);
  });
}
