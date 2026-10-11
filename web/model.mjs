// Presentation checks only. IGOR and replay verdicts are supplied by the backend.
const states = new Set(['VERIFIED', 'REVIEW', 'UNKNOWN', 'BLOCK', 'BLOCKED', 'FAILED']);
export const status = value => states.has(value) ? value : 'UNKNOWN';
const roles = ['codeact', 'react', 'agentic_rag', 'mcp_tool_use', 'self_reflection', 'multi_agent'];
export function evidenceIds(data) {
  const ids = data?.decision_report?.evidence_ids;
  if (!Array.isArray(ids) || !ids.length || ids.length > 64 ||
      ids.some(id => typeof id !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(id)) ||
      new Set(ids).size !== ids.length) throw new Error('Brak poprawnej listy dowodów wykonania.');
  return ids;
}
export function summarize(data, records, tenant, task) {
  const issues = [];
  let ids = [];
  try { ids = evidenceIds(data); } catch (error) { issues.push(error.message); }
  const run = data?.run_id;
  if (!run || data?.decision_report?.run_id !== run || data?.decision_report?.task !== task)
    issues.push('Odpowiedź nie jest powiązana z wysłanym zadaniem i wykonaniem.');
  if (!Array.isArray(records)) records = [];
  if (records.length !== ids.length || new Set(records.map(r => r.id)).size !== records.length ||
      records.some(r => !ids.includes(r.id) || r.tenant_id !== tenant || r.payload?.run_id !== run))
    issues.push('Niekompletne dowody lub niezgodny właściciel albo identyfikator wykonania.');
  const agents = records.filter(r => r.record_type?.startsWith('agent.'));
  const source = data?.provenance?.source_commit ?? data?.provenance?.commit;
  if (!/^[a-f0-9]{40}$/.test(source ?? '')) issues.push('Brak pełnego identyfikatora źródła.');
  if (agents.length !== roles.length || roles.some(role => agents.filter(r => r.record_type === `agent.${role}` && r.payload?.agent === role).length !== 1))
    issues.push('Brak kompletu dowodów sześciu agentów.');
  if (agents.some(r => r.payload.task !== task || (r.payload.source_commit ?? r.payload.commit) !== source ||
      (r.payload.commit != null && r.payload.commit !== source) ||
      r.payload.provider !== data?.provenance?.provider || r.payload.model !== data?.provenance?.model ||
      r.payload.invocation_type !== data?.provenance?.invocation_type))
    issues.push('Niespójne źródło, zadanie lub model w dowodach.');
  const final = agents.find(r => r.record_type === 'agent.multi_agent')?.payload?.final_result;
  const tool = agents.find(r => r.record_type === 'agent.codeact')?.payload?.tool_output;
  if (final == null || tool == null || String(final) !== String(tool)) issues.push('Brak zgodnego wyniku w dowodach.');
  const fields = data?.status_fields ?? {};
  const gates = {
    'Wykonanie NINA': status(data?.nina?.status),
    'Dowody': issues.length ? 'UNKNOWN' : status(data?.provenance?.status),
    'Raport IGOR': status(data?.igor?.status),
    'Integralność replay': status(data?.replay_verification?.status),
    'Zgoda człowieka': status(fields.HUMAN_GATE),
  };
  let decision = status(data?.status);
  if (issues.length && decision !== 'BLOCK' && decision !== 'BLOCKED') decision = 'UNKNOWN';
  if (decision === 'REVIEW' && Object.entries(gates).some(([name, state]) => name !== 'Zgoda człowieka' && state !== 'VERIFIED')) {
    issues.push('Stan REVIEW nie jest poparty kompletem pozytywnych bramek.'); decision = 'UNKNOWN';
  }
  // Never let an isolated success flag imply human approval or complete proof.
  if (decision === 'VERIFIED' && (Object.values(gates).some(s => s !== 'VERIFIED') ||
      fields.EXECUTION_ALLOWED !== 'VERIFIED' || fields.POLICY !== 'VERIFIED' ||
      data?.policy?.status !== 'VERIFIED' || data?.human_gate?.status !== 'VERIFIED')) {
    issues.push('Deklaracja sukcesu jest sprzeczna z wymaganymi bramkami.'); decision = 'UNKNOWN';
  }
  const invocation = data?.provenance?.invocation_type;
  return { decision, gates, issues, result: issues.length ? null : String(final), source,
    mode: invocation === 'real_llm' ? `LLM: ${data.provenance.provider ?? 'nieznany'}` :
      invocation === 'local_deterministic_model' ? 'Lokalne wykonanie deterministyczne' : 'Tryb niepotwierdzony',
    model: data?.provenance?.model ?? '—', run: run ?? '—' };
}
export function scopedReport(data, records, view) {
  // The API may include replay metadata from other runs in this tenant.
  const report = structuredClone(data);
  if (Array.isArray(report.replay)) report.replay = report.replay.filter(e => e.run_id === data.run_id);
  if (Array.isArray(report.decision_report?.replay?.events))
    report.decision_report.replay.events = report.decision_report.replay.events.filter(e => e.run_id === data.run_id);
  // Scoping changes the original decision report; do not retain its old seal.
  if (report.decision_report) delete report.decision_report.report_sha256;
  return { schema: 'ola.console-observation.v1', observed_at: new Date().toISOString(),
    scope: 'backend_response_and_fetched_evidence; not a production attestation',
    view, response: report, records };
}
export class ApiError extends Error {
  constructor(message, code) { super(message); this.code = code; }
}
export function safeOrigin(location) {
  return location.protocol === 'https:' || (location.protocol === 'http:' &&
    ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname));
}
export async function api(path, {key, body, signal} = {}, fetcher = globalThis.fetch) {
  if (!['/health', '/console/session', '/nina-run', '/chat'].includes(path) &&
      !/^\/evidence\/[a-zA-Z0-9-]{1,80}$/.test(path)) throw new ApiError('Niedozwolona ścieżka API.');
  const response = await fetcher(path, {method: body === undefined ? 'GET' : 'POST',
    headers: {...(body === undefined ? {} : {'Content-Type': 'application/json'}), ...(key ? {'X-API-Key': key} : {})},
    body: body === undefined ? undefined : JSON.stringify(body),
    signal, redirect: 'error', credentials: 'omit', cache: 'no-store'});
  if (!response.ok) {
    const message = ({401: 'Klucz nie został zaakceptowany. Połącz się ponownie.',
      403: 'Brak uprawnień do tej operacji.', 404: 'Dowód lub endpoint nie jest dostępny.',
      429: 'Limit żądań. Operacja nie będzie automatycznie ponawiana.'})[response.status];
    throw new ApiError(message ?? `Błąd API (${response.status}).`, response.status);
  }
  if (!response.headers.get('content-type')?.includes('application/json')) throw new ApiError('API zwróciło odpowiedź inną niż JSON.');
  const data = await response.json();
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new ApiError('Nieprawidłowy format odpowiedzi API.');
  return data;
}
