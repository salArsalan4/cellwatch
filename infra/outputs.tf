output "vpc_id" {
  description = "ID of the CellWatch VPC."
  value       = module.vpc.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet IDs (one per AZ)."
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Private subnet IDs (one per AZ) — RDS, cache, and VPC-bound Lambdas live here."
  value       = module.vpc.private_subnet_ids
}

output "ingest_url" {
  description = "Full URL for POST /kpi (feed this to the generator's --endpoint)."
  value       = module.data_plane.ingest_url
}

output "ingest_api_key_id" {
  description = "API key ID; fetch the value with: aws apigateway get-api-key --api-key <id> --include-value --query value --output text"
  value       = module.data_plane.ingest_api_key_id
}

output "ingest_queue_url" {
  value = module.data_plane.ingest_queue_url
}

output "ingest_dlq_url" {
  value = module.data_plane.ingest_dlq_url
}

output "kpi_table_name" {
  value = module.data_plane.kpi_table_name
}

output "raw_archive_bucket" {
  value = module.data_plane.raw_archive_bucket
}

output "query_url" {
  description = "Base URL for the query/admin API."
  value       = module.control_plane.query_url
}

output "query_api_key_id" {
  description = "API key ID; fetch the value with: aws apigateway get-api-key --api-key <id> --include-value --query value --output text"
  value       = module.control_plane.query_api_key_id
}

output "migrate_function_name" {
  description = "Invoke once after RDS is up: aws lambda invoke --function-name <name> --payload '{}' out.json"
  value       = module.control_plane.migrate_function_name
}

output "db_endpoint" {
  value = module.control_plane.db_endpoint
}

output "db_secret_arn" {
  value = module.control_plane.db_secret_arn
}

output "alerts_topic_arn" {
  description = "Confirm the email subscription (check your inbox after apply) before alerts will actually deliver."
  value       = module.data_plane.alerts_topic_arn
}

output "alerter_dlq_url" {
  value = module.control_plane.alerter_dlq_url
}

output "dashboard_url" {
  description = "CloudWatch dashboard for the whole system."
  value       = "https://console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${module.monitoring.dashboard_name}"
}
