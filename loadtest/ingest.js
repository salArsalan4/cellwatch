// k6 load test for POST /kpi, sized around docs/OVERVIEW.md §4.2's ingest
// NFR: sustain 100 rps, absorb a 500 rps burst with zero sample loss. Two
// scenarios back that up:
//   sustained - steady 100 rps for 2 minutes (ack p95 < 500ms per NFR)
//   burst     - ramps 100 -> 500 -> 100 rps to prove the burst gets
//               *admitted* (202, not 429) and accepted end-to-end; SQS is
//               what actually absorbs it downstream of the 10-Lambda
//               ceiling, not this script -- pair this with
//               scripts/poll_ingest_queue_depth.sh in another terminal to
//               see the queue fill and drain.
//
// Usage:
//   INGEST_URL=https://xxx.execute-api.us-east-1.amazonaws.com/dev/kpi \
//   INGEST_API_KEY=xxxxx \
//   k6 run loadtest/ingest.js

import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = __ENV.INGEST_URL;
const API_KEY = __ENV.INGEST_API_KEY;

if (!BASE_URL || !API_KEY) {
  throw new Error("Set INGEST_URL and INGEST_API_KEY env vars before running this test.");
}

const accepted = new Counter("samples_accepted");
const rejected = new Counter("samples_rejected");

export const options = {
  scenarios: {
    sustained: {
      executor: "constant-arrival-rate",
      rate: 100,
      timeUnit: "1s",
      duration: "2m",
      preAllocatedVUs: 50,
      maxVUs: 150,
      exec: "postSample",
      startTime: "0s",
    },
    burst: {
      executor: "ramping-arrival-rate",
      startRate: 100,
      timeUnit: "1s",
      stages: [
        { target: 500, duration: "10s" }, // ramp up
        { target: 500, duration: "20s" }, // hold at peak
        { target: 100, duration: "10s" }, // ramp back down
      ],
      preAllocatedVUs: 100,
      maxVUs: 600,
      exec: "postSample",
      startTime: "2m15s", // after `sustained` finishes, +15s gap so the queue can visibly drain first
    },
  },
  thresholds: {
    "http_req_duration{scenario:sustained}": ["p(95)<500"], // ingest ack p95 < 500ms (§4.2)
    samples_rejected: ["count==0"], // zero sample loss
  },
};

function randomCellId() {
  const n = Math.floor(Math.random() * 1000);
  return `CELL-${String(n).padStart(4, "0")}`;
}

function randomSample() {
  return {
    cell_id: randomCellId(),
    timestamp: Date.now(),
    prb_utilization_dl: Math.random() * 100,
    prb_utilization_ul: Math.random() * 100,
    rrc_connected_users: Math.floor(Math.random() * 200),
    dl_throughput_mbps: Math.random() * 300,
    ul_throughput_mbps: Math.random() * 100,
    rsrp_dbm: -140 + Math.random() * 96, // [-140, -44]
    rsrq_db: -19.5 + Math.random() * 16.5, // [-19.5, -3]
    sinr_db: -20 + Math.random() * 50, // [-20, 30]
    handover_success_rate: Math.random() * 100,
    call_drop_rate: Math.random() * 100,
    prach_attempts: Math.floor(Math.random() * 500),
  };
}

export function postSample() {
  const res = http.post(BASE_URL, JSON.stringify(randomSample()), {
    headers: { "Content-Type": "application/json", "x-api-key": API_KEY },
  });

  const ok = check(res, { "status is 202": (r) => r.status === 202 });
  if (ok) {
    accepted.add(1);
  } else {
    rejected.add(1);
  }
}
