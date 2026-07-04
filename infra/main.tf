# Data plane (API GW, SQS, Lambda, DynamoDB, S3, SNS) is intentionally NOT in the
# VPC — see docs/OVERVIEW.md §5. Only the control/read plane (RDS, cache, query/
# admin Lambda) needs the network below. VPC module lands first since RDS and the
# VPC-bound Lambdas in later phases both depend on its subnet/endpoint outputs.

module "vpc" {
  source = "./modules/vpc"

  project_name = var.project_name
  vpc_cidr     = var.vpc_cidr
  az_count     = var.az_count
}

module "kms" {
  source = "./modules/kms"

  project_name = var.project_name
}

module "data_plane" {
  source = "./modules/data-plane"

  project_name = var.project_name
  environment  = var.environment
  alert_email  = var.alert_email
  kms_key_arn  = module.kms.key_arn
}

module "control_plane" {
  source = "./modules/control-plane"

  project_name                    = var.project_name
  environment                     = var.environment
  vpc_id                          = module.vpc.vpc_id
  private_subnet_ids              = module.vpc.private_subnet_ids
  vpc_endpoints_security_group_id = module.vpc.vpc_endpoints_security_group_id
  shared_layer_arn                = module.data_plane.deps_layer_arn
  kpi_table_name                  = module.data_plane.kpi_table_name
  alerts_topic_arn                = module.data_plane.alerts_topic_arn
  kms_key_arn                     = module.kms.key_arn
}

module "monitoring" {
  source = "./modules/monitoring"

  project_name            = var.project_name
  alarm_topic_arn         = module.data_plane.alerts_topic_arn
  ingest_api_name         = module.data_plane.ingest_api_name
  ingest_stage_name       = module.data_plane.ingest_stage_name
  ingest_queue_name       = module.data_plane.ingest_queue_name
  ingest_dlq_name         = module.data_plane.ingest_dlq_name
  alerter_dlq_name        = module.control_plane.alerter_dlq_name
  ingest_function_name    = module.data_plane.ingest_function_name
  processor_function_name = module.data_plane.processor_function_name
  query_function_name     = module.control_plane.query_function_name
  alerter_function_name   = module.control_plane.alerter_function_name
  kpi_table_name          = module.data_plane.kpi_table_name
  db_instance_id          = module.control_plane.db_instance_id
}
