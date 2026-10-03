// k6 API load test: 50 orgs reading their dashboard data concurrently, plus a trickle of
// imports — the traffic shape of "everyone opens Stockcast at 9am after the nightly run".
//
//   k6 run -e API_URL=https://api-staging.stockcast.app -e ORG_IDS=$(cat orgs.txt | paste -sd,) loadtest/k6/api.js
//   (header auth: run against a staging API with AUTH_MODE=header, or pass -e TOKEN=<clerk jwt>)
//
// Thresholds encode the SLOs from docs/RUNBOOK.md.
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const API = __ENV.API_URL || "http://localhost:8000";
const ORGS = (__ENV.ORG_IDS || "00000000-0000-0000-0000-00000000d3a0").split(",");
const TOKEN = __ENV.TOKEN || "";

export const options = {
  scenarios: {
    dashboards: {
      executor: "ramping-vus",
      startVUs: 5,
      stages: [
        { duration: "1m", target: 50 },
        { duration: "3m", target: 50 },
        { duration: "30s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{name:recommendations}": ["p(95)<800"],
    "http_req_duration{name:forecast}": ["p(95)<600"],
    "http_req_duration{name:products}": ["p(95)<500"],
    checks: ["rate>0.99"],
  },
};

const recTrend = new Trend("recommendations_ms");

function headers(org) {
  const h = { "Content-Type": "application/json" };
  if (TOKEN) h.Authorization = `Bearer ${TOKEN}`;
  else h["X-Org-Id"] = org;
  return h;
}

export default function () {
  const org = ORGS[__VU % ORGS.length];
  const h = headers(org);
  const recs = http.get(`${API}/recommendations?limit=200`, { headers: h, tags: { name: "recommendations" } });
  recTrend.add(recs.timings.duration);
  check(recs, { "recommendations 200": (r) => r.status === 200 });
  const products = http.get(`${API}/products?limit=100`, { headers: h, tags: { name: "products" } });
  check(products, { "products 200": (r) => r.status === 200 });
  const list = products.json();
  if (list && list.length) {
    const p = list[Math.floor(Math.random() * list.length)];
    const fc = http.get(`${API}/forecasts?product_id=${p.id}&days=90`, { headers: h, tags: { name: "forecast" } });
    check(fc, { "forecast 200/404": (r) => r.status === 200 || r.status === 404 });
  }
  http.get(`${API}/planning-runs?limit=5`, { headers: h, tags: { name: "runs" } });
  sleep(Math.random() * 2 + 1);
}
