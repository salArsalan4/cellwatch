output "ingest_url" {
  description = "Full URL for POST /kpi."
  value       = "${aws_api_gateway_stage.this.invoke_url}/kpi"
}

output "ingest_api_key_id" {
  description = "ID of the generator's API key (fetch the value with: aws apigateway get-api-key --api-key <id> --include-value)."
  value       = aws_api_gateway_api_key.generator.id
}

output "ingest_queue_url" {
  description = "SQS queue URL the ingest Lambda enqueues to."
  value       = aws_sqs_queue.ingest.id
}

output "ingest_dlq_url" {
  description = "SQS DLQ URL for poison messages."
  value       = aws_sqs_queue.ingest_dlq.id
}

output "kpi_table_name" {
  description = "DynamoDB hot KPI time-series table name."
  value       = aws_dynamodb_table.kpi.name
}

output "raw_archive_bucket" {
  description = "S3 bucket holding raw KPI archive + rollups."
  value       = aws_s3_bucket.raw.bucket
}

output "deps_layer_arn" {
  description = "ARN of the shared dependency layer (powertools/pydantic/xray-sdk + services/common), reused by the control-plane module instead of duplicating it."
  value       = aws_lambda_layer_version.deps.arn
}

output "alerts_topic_arn" {
  description = "SNS topic ARN for anomaly alerts, consumed by the control-plane alerter Lambda subscription."
  value       = aws_sns_topic.alerts.arn
}

output "ingest_api_name" {
  value = aws_api_gateway_rest_api.ingest.name
}

output "ingest_stage_name" {
  value = aws_api_gateway_stage.this.stage_name
}

output "ingest_queue_name" {
  value = aws_sqs_queue.ingest.name
}

output "ingest_dlq_name" {
  value = aws_sqs_queue.ingest_dlq.name
}

output "ingest_function_name" {
  value = aws_lambda_function.ingest.function_name
}

output "processor_function_name" {
  value = aws_lambda_function.processor.function_name
}
