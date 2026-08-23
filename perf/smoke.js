// Pry - k6 performance SMOKE scenario (10 VUs x 30s).
// Exercises the free control-plane surface: health, readiness, pricing,
// OpenAPI docs. Paid scrape endpoints are intentionally excluded here —
// they hit live upstreams and belong in staging load tests.
//
// Thresholds are regression catchers, not SLAs:
//   p95 < 500ms, error rate < 2%, no threshold = green CI.

import { check, sleep } from "k6";
import http from "k6/http";
import { Trend } from "k6/metrics";

const BASE = __ENV.PRY_BASE_URL || "http://127.0.0.1:8005";

const healthLatency = new Trend("pry_health_latency_ms");

export const options = {
	vus: 10,
	duration: "30s",
	thresholds: {
		http_req_failed: ["rate<0.02"],
		http_req_duration: ["p(95)<500"],
		// /live is an in-process liveness probe; 300ms p95 catches gross
		// regressions while tolerating shared-host noise (observed 130-270ms
		// p95 on a busy multi-tenant box).
		pry_health_latency_ms: ["p(95)<300"],
	},
};

const HEADERS = __ENV.PRY_API_KEY
	? { Authorization: `Bearer ${__ENV.PRY_API_KEY}` }
	: {};

export default function () {
	// /health is intentionally excluded: it legitimately returns 503 when
	// optional deps (redis/ollama) are absent, which would poison the
	// failure-rate threshold. /live covers process liveness.
	const responses = http.batch([
		{ method: "GET", url: `${BASE}/live`, params: { headers: HEADERS } },
		{
			method: "GET",
			url: `${BASE}/v1/x402/pricing`,
			params: { headers: HEADERS },
		},
		{
			method: "GET",
			url: `${BASE}/openapi.json`,
			params: { headers: HEADERS },
		},
	]);
	check(responses[0], {
		"live 200": (r) => r.status === 200,
	});
	check(responses[1], {
		"pricing 200": (r) => r.status === 200,
	});
	healthLatency.add(responses[0].timings.duration);
	sleep(1);
}
