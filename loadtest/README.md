# Load tests

Two k6 scripts sized around the NFRs in `docs/OVERVIEW.md` §4.2, plus a
poller for the evidence k6 itself can't capture (queue depth).

## Ingest: `ingest.js`

Sustained 100 rps for 2 minutes, then a ramp to a 500 rps burst and back
down. Checks: ack p95 < 500ms during the sustained phase, zero rejected
samples throughout.

```bash
INGEST_URL=$(terraform -chdir=infra output -raw ingest_url)
INGEST_API_KEY=$(aws apigateway get-api-key --api-key $(terraform -chdir=infra output -raw ingest_api_key_id) --include-value --query value --output text)

# In one terminal, start polling queue depth (leave running through the burst):
./loadtest/poll_ingest_queue_depth.sh > queue_depth.csv

# In another terminal:
INGEST_URL="$INGEST_URL" INGEST_API_KEY="$INGEST_API_KEY" k6 run loadtest/ingest.js
```

The queue depth CSV is the actual evidence for "SQS absorbs the burst above
the 10-Lambda ceiling": expect `visible` to climb during the burst (since
the queue can only actually drain at ~10 concurrent Lambda executions'
worth of throughput, however fast that is) and drain back to ~0 afterward,
with the k6 run showing 202s and low ack latency throughout regardless.

## Query: `query.js`

Two scenarios for a clean before/after cache comparison: `warm_cache` hits
the same 3 seeded cells repeatedly (mostly cache hits after the first),
`cold_cache` hits a fresh never-seen cell_id every time (guaranteed
misses). Check: warm-cache read p95 < 300ms.

```bash
QUERY_URL=$(terraform -chdir=infra output -raw query_url)
QUERY_API_KEY=$(aws apigateway get-api-key --api-key $(terraform -chdir=infra output -raw query_api_key_id) --include-value --query value --output text)

QUERY_URL="$QUERY_URL" QUERY_API_KEY="$QUERY_API_KEY" k6 run loadtest/query.js
```

k6's summary breaks out `http_req_duration{scenario:warm_cache}` vs
`{scenario:cold_cache}` separately -- that p95 gap is the report's
before/after cache number.
