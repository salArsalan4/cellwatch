output "query_url" {
  description = "Base URL for the query/admin API (routes are appended, e.g. .../cells)."
  value       = aws_api_gateway_stage.this.invoke_url
}

output "query_api_key_id" {
  description = "ID of the query/admin API key (fetch the value with: aws apigateway get-api-key --api-key <id> --include-value --query value --output text)."
  value       = aws_api_gateway_api_key.query_client.id
}

output "migrate_function_name" {
  description = "Invoke this once after RDS comes up: aws lambda invoke --function-name <name> --payload '{}' out.json"
  value       = aws_lambda_function.migrate.function_name
}

output "db_endpoint" {
  description = "RDS Postgres endpoint address."
  value       = aws_db_instance.this.address
}

output "db_secret_arn" {
  description = "Secrets Manager ARN holding the RDS master credentials (AWS-managed, never in code)."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "alerter_dlq_url" {
  description = "SQS DLQ for alerts SNS deliveries that failed to write to RDS."
  value       = aws_sqs_queue.alerter_dlq.id
}

output "alerter_dlq_name" {
  value = aws_sqs_queue.alerter_dlq.name
}

output "alerter_function_name" {
  value = aws_lambda_function.alerter.function_name
}

output "query_function_name" {
  value = aws_lambda_function.query.function_name
}

output "db_instance_id" {
  # .identifier ("cellwatch-db"), NOT .id -- in this provider version .id is
  # the dbi-resource-id (db-XXXX), but CloudWatch's DBInstanceIdentifier
  # dimension is tagged with the instance identifier. Using .id left the RDS
  # dashboard widget and the rds-cpu/rds-connections alarms querying a
  # nonexistent dimension value (No data / permanent INSUFFICIENT_DATA).
  value = aws_db_instance.this.identifier
}
