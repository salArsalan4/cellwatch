#!/usr/bin/env bash
# Polls the ingest SQS queue depth once a second and prints a CSV
# (timestamp,visible,in_flight) to stdout. Run this in a second terminal
# while loadtest/ingest.js's burst scenario is active to capture the
# queue filling above the 10-Lambda ceiling and then draining -- that
# curve is the actual evidence for the "SQS absorbs the burst" NFR
# (docs/OVERVIEW.md §4.2), not the k6 output alone.
#
# Usage:
#   ./loadtest/poll_ingest_queue_depth.sh > queue_depth.csv
#   (Ctrl+C to stop once the queue has visibly drained back to ~0)
set -euo pipefail

QUEUE_URL=$(terraform -chdir=infra output -raw ingest_queue_url)

echo "timestamp,visible,in_flight"
while true; do
  attrs=$(aws sqs get-queue-attributes \
    --queue-url "$QUEUE_URL" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query "Attributes")
  visible=$(echo "$attrs" | jq -r '.ApproximateNumberOfMessages')
  in_flight=$(echo "$attrs" | jq -r '.ApproximateNumberOfMessagesNotVisible')
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ),$visible,$in_flight"
  sleep 1
done
