import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const requestFailure = new Rate('ola_tls_request_failure');
const tlsHandshake = new Trend('ola_tls_handshake_ms');
const startedAt = Date.now();
const faultAfterMs = Number(__ENV.FAULT_AFTER_SECONDS || 9) * 1000;
const faultEndMs = faultAfterMs + Number(__ENV.FAULT_DURATION_SECONDS || 11) * 1000;

export const options = {
  noConnectionReuse: true,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'p(99)'],
  thresholds: {},
};

export default function () {
  const elapsed = Date.now() - startedAt;
  const phase = elapsed < faultAfterMs ? 'baseline' : (elapsed < faultEndMs ? 'fault' : 'recovery');
  const response = http.get(__ENV.BASE_URL || 'https://127.0.0.1:8443/health', {
    headers: {
      'X-OLA-Scenario-Run': __ENV.RUN_ID || '',
      'X-OLA-Scenario-Challenge': __ENV.CHALLENGE || '',
      'Connection': 'close',
    },
    timeout: '3s',
    tags: { phase: phase },
  });
  const healthy = response.status === 200;
  requestFailure.add(!healthy, { phase: phase });
  if (response.timings && Number.isFinite(response.timings.tls_handshaking)) {
    tlsHandshake.add(response.timings.tls_handshaking, { phase: phase });
  }
  check(response, { 'strict TLS health endpoint returned 200': () => healthy }, { phase: phase });
  sleep(0.2);
}
