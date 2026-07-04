variable "project_name" {
  description = "Project name used as a resource-naming prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment name, also used as the API Gateway stage name."
  type        = string
}

variable "lab_role_name" {
  description = "Name of the pre-baked AWS Academy Learner Lab execution role (IAM role creation is blocked in the lab, so every Lambda attaches this)."
  type        = string
  default     = "LabRole"
}

variable "alert_email" {
  description = "NOC email address for anomaly alerts. SNS will send a confirmation link to this address after apply -- alerts won't be delivered until it's clicked."
  type        = string
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key for at-rest encryption of DynamoDB, S3, and SQS."
  type        = string
}
