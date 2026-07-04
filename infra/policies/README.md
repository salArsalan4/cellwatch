# Intended least-privilege IAM policies

The Learner Lab blocks creating or attaching IAM roles/policies (§8 of
`docs/OVERVIEW.md`) — every Lambda in this repo attaches the pre-baked
`LabRole`, which is far broader than any single function needs. These JSON
files are **not applied anywhere**; they're the scoped, per-function policy
each Lambda *would* get in production, kept here as the evidence the report
asks for under Security §7.2 ("least privilege designed and documented but
not enforced").

`ACCOUNT_ID` and `REGION` are placeholders for the deploying account/region
(substitute the real values, e.g. via `terraform output` + `aws sts
get-caller-identity`, if these were ever turned into real policies).

| File | Attaches to | Scope |
|---|---|---|
| `ingest-lambda-policy.json` | `cellwatch-ingest` | `sqs:SendMessage` on the ingest queue only |
| `processor-lambda-policy.json` | `cellwatch-processor` | Write raw archive (S3), upsert hot KPI + stats items (DynamoDB), publish anomalies (SNS) |
| `query-lambda-policy.json` | `cellwatch-query` | Read KPI table (DynamoDB), read RDS secret, VPC ENI + X-Ray |
| `migrate-lambda-policy.json` | `cellwatch-migrate` | Read RDS secret, VPC ENI (no X-Ray -- not on any request path) |
| `alerter-lambda-policy.json` | `cellwatch-alerter` | Read RDS secret, VPC ENI + X-Ray |

Every policy also gets the standard CloudWatch Logs statement
(`CreateLogGroup`/`CreateLogStream`/`PutLogEvents` scoped to its own log
group) that `AWSLambdaBasicExecutionRole` provides — included inline here
rather than referencing the managed policy, since these are meant to be
self-contained evidence of the *complete* intended permission set.
