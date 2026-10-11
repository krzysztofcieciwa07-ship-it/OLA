import test from 'node:test';
import assert from 'node:assert/strict';
import {api, evidenceIds, summarize, scopedReport, safeOrigin} from '../../web/model.mjs';
function fixture() {
  const tenant = 'tenant-a', run_id = 'run-a', task = 'calculate 17*23', commit = 'a'.repeat(40);
  const provenance = {status: 'VERIFIED', commit, source_commit: commit, provider: 'local', model: 'deterministic-runtime-v1', invocation_type: 'local_deterministic_model'};
  const roles = ['codeact', 'react', 'agentic_rag', 'mcp_tool_use', 'self_reflection', 'multi_agent'];
  const records = roles.map((role, i) => ({id: `record-${i}`, tenant_id: tenant, record_type: `agent.${role}`,
    payload: {...provenance, run_id, agent: role, task, tool_output: '391', final_result: '391'}}));
  const data = {run_id, status: 'REVIEW', provenance, nina: {status: 'VERIFIED'}, igor: {status: 'VERIFIED'},
    replay_verification: {status: 'VERIFIED'}, status_fields: {HUMAN_GATE: 'REVIEW', POLICY: 'VERIFIED', EXECUTION_ALLOWED: 'REVIEW'},
    policy: {status: 'VERIFIED'}, human_gate: {status: 'BLOCK'},
    decision_report: {run_id, task, evidence_ids: records.map(r => r.id), report_sha256: 'original-seal', replay: {events: [{run_id}, {run_id: 'other'}]}},
    replay: [{run_id}, {run_id: 'other'}]};
  return {data, records, tenant, task};
}
const view = f => summarize(f.data, f.records, f.tenant, f.task);
test('deterministic result remains REVIEW and never claims a real LLM', () => {
  const result = view(fixture()); assert.equal(result.result, '391'); assert.equal(result.decision, 'REVIEW');
  assert.equal(result.mode, 'Lokalne wykonanie deterministyczne');
});
for (const [name, mutate] of [
  ['foreign tenant', f => f.records[0].tenant_id = 'other'],
  ['foreign run', f => f.records[0].payload.run_id = 'other'],
  ['wrong task', f => f.records[0].payload.task = 'other'],
  ['wrong source', f => f.records[0].payload.source_commit = 'b'.repeat(40)],
  ['wrong provider', f => f.records[0].payload.provider = 'ollama'],
  ['wrong model', f => f.records[0].payload.model = 'other'],
  ['missing agent', f => f.records.pop()],
  ['duplicate evidence', f => f.records[1] = f.records[0]],
  ['mismatched result', f => f.records[5].payload.final_result = '392'],
  ['missing source', f => { delete f.data.provenance.commit; delete f.data.provenance.source_commit; }],
]) test(`${name} cannot be shown as complete evidence`, () => {
  const f = fixture(); mutate(f); const result = view(f);
  assert.equal(result.result, null); assert.equal(result.decision, 'UNKNOWN'); assert.ok(result.issues.length);
});
test('forged terminal VERIFIED does not replace pending human review', () => {
  const f = fixture(); f.data.status = 'VERIFIED'; assert.equal(view(f).decision, 'UNKNOWN');
});
test('explicit server BLOCK is preserved with missing proof', () => {
  const f = fixture(); f.data.status = 'BLOCK'; f.records.pop(); assert.equal(view(f).decision, 'BLOCK');
});
test('bad record identifiers cannot become arbitrary request paths', () => {
  const f = fixture(); f.data.decision_report.evidence_ids = ['//evil.test']; assert.throws(() => evidenceIds(f.data));
});
test('export scopes replay and discards the seal invalidated by scoping', () => {
  const f = fixture(), result = scopedReport(f.data, f.records, view(f));
  assert.equal(result.response.replay.length, 1); assert.equal(result.response.decision_report.replay.events.length, 1);
  assert.equal(result.response.decision_report.report_sha256, undefined);
  assert.equal(f.data.decision_report.report_sha256, 'original-seal');
});
test('keys are allowed only over HTTPS or loopback HTTP', () => {
  assert.equal(safeOrigin({protocol: 'https:', hostname: 'ola.example'}), true);
  assert.equal(safeOrigin({protocol: 'http:', hostname: '127.0.0.1'}), true);
  assert.equal(safeOrigin({protocol: 'http:', hostname: 'ola.example'}), false);
  assert.equal(safeOrigin({protocol: 'file:', hostname: ''}), false);
});
test('API transport sends key in header and refuses redirects and caching', async () => {
  await api('/nina-run', {key: 'test-key', body: {task: 'calculate 1+1'}}, async (path, options) => {
    assert.equal(path, '/nina-run'); assert.equal(options.headers['X-API-Key'], 'test-key');
    assert.equal(options.redirect, 'error'); assert.equal(options.cache, 'no-store');
    assert.equal(options.credentials, 'omit'); assert.equal(options.method, 'POST');
    return new Response('{}', {headers: {'Content-Type': 'application/json'}});
  });
});
test('network failures do not retry an execution', async () => {
  let requests = 0; await assert.rejects(api('/nina-run', {body: {task: 'x'}}, async () => {requests++; throw new Error('offline');}));
  assert.equal(requests, 1);
});
test('401 and non-JSON pages are errors, even when the page says success', async () => {
  await assert.rejects(api('/console/session', {}, async () => new Response('VERIFIED', {status: 401})), e => e.code === 401);
  await assert.rejects(api('/nina-run', {}, async () => new Response('<html>VERIFIED</html>', {headers: {'Content-Type': 'text/html'}})));
});
test('absolute destinations are rejected before any request', async () => {
  let called = false;
  await assert.rejects(api('https://elsewhere.test', {key: 'test-key'}, async () => {called = true;}));
  assert.equal(called, false);
});
