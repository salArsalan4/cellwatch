variable "project_name" {
  type = string
}

variable "alarm_topic_arn" {
  description = "SNS topic ARN alarms notify on state change (reuses the same NOC alerts topic rather than requiring a second email confirmation)."
  type        = string
}

variable "ingest_api_name" {
  type = string
}

variable "ingest_stage_name" {
  type = string
}

variable "ingest_queue_name" {
  type = string
}

variable "ingest_dlq_name" {
  type = string
}

variable "alerter_dlq_name" {
  type = string
}

variable "ingest_function_name" {
  type = string
}

variable "processor_function_name" {
  type = string
}

variable "query_function_name" {
  type = string
}

variable "alerter_function_name" {
  type = string
}

variable "kpi_table_name" {
  type = string
}

variable "db_instance_id" {
  type = string
}
