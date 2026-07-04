# CellWatch Runbook

Operational playbooks for the NOC / on-call. Companion to `docs/OVERVIEW.md`
(architecture/design authority) — this doc is about *what to do when
something's wrong*, not why the system is built the way it is.

Resource names below match the live deployment (`terraform output` in
`infra/` for the exact values — queue URLs, function names, etc. — since
API keys and some ARNs are session-specific).

---

## 1. Sleeping-cell storm

**Symptom:** Multiple cells simultaneously report near-zero PRB
utilization, zero connected users, and near-zero throughput —
`alert_type = "sleeping_cell"` rows appearing in bulk. This is the specific
composite pattern `services/common/detection.py::check_sleeping_cell`
looks for: a cell that's still *reporting* (so it's not simply offline/not
posting), but reporting nothing being served.

**Detection:**
- CloudWatch dashboard (`dashboard_url` output) — "Anomaly detection"
  widget shows a spike in `AnomaliesDetected`.
- Multiple NOC alert emails within a short window, or:
  ```bash
  QUERY_URL=$(terraform -chdir=infra output -raw query_url)
  QUERY_KEY=$(aws apigateway get-api-key --api-key $(terraform -chdir=infra output -raw query_api_key_id) --include-value --query value --output text)
  curl -s -H "x-api-key: $QUERY_KEY" "$QUERY_URL/alerts" | jq '[.[] | select(.alert_type=="sleeping_cell")] | length'
  ```

**Diagnosis — is this real or an artifact?**
1. Check whether it's isolated to a handful of physically/logically
   related cells (real site/backhaul outage) or spread randomly across the
   fleet (more likely a generator/agent bug or a processor regression).
2. Confirm samples are actually still arriving for the affected cells
   (not just alert rows from *before* the cells went fully silent):
   ```bash
   curl -s -H "x-api-key: $QUERY_KEY" "$QUERY_URL/cells/<cell_id>/kpis?limit=5" | jq .
   ```
   If no new samples are landing at all, this is an ingest-path problem
   (check §2 below), not a sleeping-cell condition — the detector never
   even sees a "sleeping" sample if nothing arrives.
3. Check CloudWatch Logs for the processor (`/aws/lambda/cellwatch-processor`)
   around the same timestamps for anything unusual in the detection path.

**Response:** This is an MVP detection-and-notify system — there's no
auto-remediation. Confirm the alert is legitimate, escalate to whoever
owns the affected physical sites, and use `/cells/<id>/health` and
`/cells/<id>/kpis` to build the incident timeline for the postmortem.

---

## 2. DLQ backlog

**Symptom:** `cellwatch-ingest-dlq-depth` or `cellwatch-alerter-dlq-depth`
CloudWatch alarm in ALARM state (SNS notifies the same NOC topic as
anomaly alerts).

**Which DLQ, and what it means:**
- `cellwatch-ingest-dlq` — KPI samples the processor couldn't handle after
  3 delivery attempts (see `redrive_policy` on `cellwatch-ingest` in
  `infra/modules/data-plane/sqs.tf`). Usually a malformed payload that
  passed API Gateway's schema validation but failed Pydantic re-validation,
  or a bug in `services/processor/handler.py`.
- `cellwatch-alerter-dlq` — anomaly notifications SNS couldn't deliver to
  the alerter Lambda. Usually an RDS outage/timeout at the moment of
  delivery, or a bug in `services/alerter/handler.py`.

**Diagnosis:**
```bash
DLQ_URL=$(terraform -chdir=infra output -raw ingest_dlq_url)   # or alerter_dlq_url
aws sqs receive-message --queue-url "$DLQ_URL" --max-number-of-messages 5 \
  --attribute-names All --message-attribute-names All
```
Read the message bodies to find the common failure pattern. Cross-reference
with CloudWatch Logs for the consuming Lambda
(`/aws/lambda/cellwatch-processor` or `/aws/lambda/cellwatch-alerter`)
around the same timestamps for the actual exception.

**Response:**
- **Transient cause already resolved** (e.g. RDS was briefly down and is
  back): redrive the messages back to the source queue so they get
  reprocessed automatically —
  ```bash
  aws sqs start-message-move-task --source-arn <dlq-arn>
  ```
  (or via the SQS console: queue → DLQ redrive → source queue).
- **Genuinely poison messages** (bad payload, will never succeed): delete
  them from the DLQ after confirming they're not silently dropping real
  telemetry —
  ```bash
  aws sqs purge-queue --queue-url "$DLQ_URL"   # nukes the whole DLQ; only if ALL messages are confirmed poison
  ```
- **Root cause is a code bug:** fix it, deploy (`build_lambda_artifacts.sh`
  + `terraform apply`), *then* redrive — otherwise the same messages just
  fail again and land right back in the DLQ.

---

## 3. RDS snapshot / PITR restore

RDS in this deployment is single-AZ (Learner Lab constraint, §8 of
OVERVIEW.md) — there's no automatic failover, so recovery from an instance
failure or bad data is either a manual snapshot restore or point-in-time
recovery (PITR), both of which create a **new** RDS instance rather than
repairing the existing one in place.

**Manual snapshot (do this before any risky manual change, e.g. hand-editing data):**
```bash
aws rds create-db-snapshot \
  --db-instance-identifier cellwatch-db \
  --db-snapshot-identifier cellwatch-db-manual-$(date +%Y%m%d-%H%M)
```

**Point-in-time restore** (automated backups are enabled with a 7-day
retention window — see `backup_retention_period` in
`infra/modules/control-plane/rds.tf`):
```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier cellwatch-db \
  --target-db-instance-identifier cellwatch-db-restored \
  --restore-time 2026-07-03T12:00:00Z \
  --db-subnet-group-name cellwatch-db-subnet-group \
  --vpc-security-group-ids <cellwatch-rds-sg-id>
```
This is genuinely slow (RDS provisioning + backup replay, not the ~60-120s
failover of a Multi-AZ production setup — be honest about this gap in the
report, it's the direct tradeoff of single-AZ). Once it's up:
1. Point `DB_HOST` at the new instance (either update the Terraform
   `aws_db_instance` resource via `terraform import`, or, faster for a
   one-off drill, just update the Lambda env vars directly and swap back
   once satisfied).
2. Re-run the migrate Lambda if the schema itself needs reconciling:
   `aws lambda invoke --function-name cellwatch-migrate --payload '{}' out.json`.
3. Verify via `GET /cells` and `GET /alerts` that the restored data looks
   right before cutting traffic over.
4. Delete the old/broken instance once confirmed, and rename the restored
   one back to `cellwatch-db` (or update `DB_HOST` permanently) so
   Terraform state matches reality again.

**RPO/RTO, stated honestly (report material):**
- Telemetry (DynamoDB/S3): RPO ≈ 0 — a sample is durable in SQS + S3
  before the API even acknowledges it (§5 design principle), independent
  of RDS entirely.
- RDS (inventory/thresholds/alert history): RPO ~5 minutes via PITR; RTO
  is however long a fresh `db.t3.micro` provision + backup replay takes in
  this lab — tens of minutes, not seconds. In production, Multi-AZ gives
  ~60-120s RTO with the same RPO; that's a one-flag (`multi_az = true`)
  change once Multi-AZ isn't lab-restricted, since the DB subnet group
  already spans 2 AZs.

**Budget hygiene (§8):** stop or snapshot-and-delete `cellwatch-db` at the
end of a work session — a *stopped* instance auto-restarts after 7 days,
so for gaps longer than that, snapshot-and-delete is safer than stop:
```bash
aws rds create-db-snapshot --db-instance-identifier cellwatch-db --db-snapshot-identifier cellwatch-db-pre-teardown
aws rds delete-db-instance --db-instance-identifier cellwatch-db --skip-final-snapshot
```
Restore from that snapshot (`aws rds restore-db-instance-from-db-snapshot`)
or just `terraform apply` again to rebuild it fresh + re-run migrate.
