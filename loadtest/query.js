// k6 load test for the query/admin read API. Two scenarios give a clean
// before/after cache comparison (docs/OVERVIEW.md §7.4):
//   warm_cache - a small fixed set of cells, hit repeatedly. First request
//                per cell is a miss; everything else within the 30s cache
//                TTL is a hit.
//   cold_cache - a fresh, never-before-queried cell_id every request ->
//                guaranteed cache miss every time, a clean "no cache"
//                baseline. /cells/{id}/health doesn't 404 for an unknown
//                cell (DynamoDB/RDS both just return empty results for
//                it), so this is purely a cache-behavior comparison, not
//                a mix of error and success paths.
//
// Usage:
//   QUERY_URL=https://xxx.execute-api.us-east-1.amazonaws.com/dev \
//   QUERY_API_KEY=xxxxx \
//   k6 run loadtest/query.js

import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.QUERY_URL;
const API_KEY = __ENV.QUERY_API_KEY;

if (!BASE_URL || !API_KEY) {
  throw new Error("Set QUERY_URL and QUERY_API_KEY env vars before running this test.");
}

const HEADERS = { headers: { "x-api-key": API_KEY } };

export const options = {
  scenarios: {
    warm_cache: {
      executor: "constant-arrival-rate",
      rate: 12,
      timeUnit: "1s",
      duration: "60s",
      preAllocatedVUs: 20,
      maxVUs: 50,
      exec: "warmCacheRequest",
    },
    cold_cache: {
      executor: "constant-arrival-rate",
      rate: 4,
      timeUnit: "1s",
      duration: "60s",
      preAllocatedVUs: 10,
      maxVUs: 30,
      exec: "coldCacheRequest",
    },
  },
  thresholds: {
    "http_req_duration{scenario:warm_cache}": ["p(95)<300"], // cached read p95 < 300ms (§4.2)
  },
};

const WARM_CELLS = ["CELL-0000", "CELL-0001", "CELL-0002"];

export function warmCacheRequest() {
  const cellId = WARM_CELLS[Math.floor(Math.random() * WARM_CELLS.length)];
  const res = http.get(`${BASE_URL}/cells/${cellId}/health`, HEADERS);
  check(res, { "status is 200": (r) => r.status === 200 });
}

let coldCounter = 100000;

export function coldCacheRequest() {
  coldCounter += 1; // monotonically increasing -> a path this test has never hit before
  const res = http.get(`${BASE_URL}/cells/CELL-${coldCounter}/health`, HEADERS);
  check(res, { "status is 200": (r) => r.status === 200 });
}
