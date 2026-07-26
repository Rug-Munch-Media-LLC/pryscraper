// Smoke test for Pryscraper — runs on every PR. 10 VUs for 30s.
// Fails if any critical endpoint is slow or errors.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const errorRate = new Rate('errors');

export const options = {
  vus: 10,
  duration: '30s',
  thresholds: {
    'errors': ['rate<0.01'],                 // <1% error rate
    'http_req_duration': ['p(95)<1000'],      // 95th percentile <1s
    'http_req_duration{endpoint:health}': ['p(95)<200'],
    'http_req_duration{endpoint:scrape}': ['p(95)<5000'],
  },
  summaryTrendStats: ['min', 'avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8005';

export default function () {
  // Health check — liveness probe
  const healthRes = http.get(`${BASE_URL}/live`, {
    tags: { endpoint: 'health' },
  });
  check(healthRes, {
    'health status 200': (r) => r.status === 200,
  }) || errorRate.add(1);
  sleep(1);

  // Readiness check
  const readyRes = http.get(`${BASE_URL}/ready`, {
    tags: { endpoint: 'ready' },
  });
  check(readyRes, {
    'ready status 200': (r) => r.status === 200,
  }) || errorRate.add(1);
  sleep(1);

  // Scrape endpoint — lightweight check with minimal payload
  const scrapeRes = http.post(`${BASE_URL}/v1/scrape`, JSON.stringify({
    url: 'https://example.com',
    max_pages: 1,
    timeout: 5,
  }), {
    headers: { 'Content-Type': 'application/json' },
    tags: { endpoint: 'scrape' },
  });
  check(scrapeRes, {
    'scrape responds': (r) => r.status === 200 || r.status === 401 || r.status === 422,
  }) || errorRate.add(1);
  sleep(2);
}

export function handleSummary(data) {
  return {
    'tests/k6/results/smoke-summary.json': JSON.stringify(data, null, 2),
    stdout: `
╔══════════════════════════════════════════╗
║   Pryscraper k6 Smoke Test Results      ║
╠══════════════════════════════════════════╣
║   Total Requests:  ${data.metrics.http_reqs.values.count}
║   Failed:         ${data.metrics.http_req_failed.values.passes || 0}
║   Error Rate:     ${(data.metrics.errors?.values.rate * 100 || 0).toFixed(2)}%
║   Avg Duration:   ${data.metrics.http_req_duration.values.avg.toFixed(2)}ms
║   p95 Duration:   ${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms
║   p99 Duration:   ${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms
╚══════════════════════════════════════════╝
`,
  };
}
