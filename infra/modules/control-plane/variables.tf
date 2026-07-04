variable "project_name" {
  description = "Project name used as a resource-naming prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment name, also used as the API Gateway stage name."
  type        = string
}

variable "lab_role_name" {
  description = "Name of the pre-baked AWS Academy Learner Lab execution role."
  type        = string
  default     = "LabRole"
}

variable "vpc_id" {
  description = "VPC to place RDS and the control-plane Lambdas in."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs (one per AZ) for the DB subnet group and VPC-bound Lambdas."
  type        = list(string)
}

variable "vpc_endpoints_security_group_id" {
  description = "Security group attached to the Secrets Manager / X-Ray interface VPC endpoints."
  type        = string
}

variable "shared_layer_arn" {
  description = "ARN of the shared dependency layer (powertools/pydantic/xray-sdk + services/common) built for the data plane, reused here instead of duplicating it."
  type        = string
}

variable "kpi_table_name" {
  description = "DynamoDB hot KPI table name (query Lambda reads it directly)."
  type        = string
}

variable "enable_cache" {
  description = "Provision an API Gateway cache cluster on the read stage. Costs ~$0.02/hr while running -- set false to skip during idle stretches."
  type        = bool
  default     = true
}

variable "alerts_topic_arn" {
  description = "SNS topic ARN (from the data-plane module) the alerter Lambda subscribes to."
  type        = string
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key for at-rest encryption of RDS storage and the alerter DLQ."
  type        = string
}

variable "cors_allow_origin" {
  description = "Value of Access-Control-Allow-Origin for the query API, for the browser-based static dashboard (frontend/). '*' is fine here: every route is read-side and still gated by the query API key."
  type        = string
  default     = "*"
}
