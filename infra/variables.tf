variable "aws_region" {
  description = "AWS region. Learner Lab supports us-east-1 and us-west-2; pin to us-east-1 for consistency."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name (e.g. dev)."
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name used as a resource-naming prefix."
  type        = string
  default     = "cellwatch"
}

variable "vpc_cidr" {
  description = "CIDR block for the CellWatch VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "az_count" {
  description = "Number of AZs to span (one public + one private subnet each)."
  type        = number
  default     = 2
}

variable "alert_email" {
  description = "NOC email address for anomaly alerts. SNS sends a confirmation link here after apply -- alerts won't deliver until it's clicked. Set via -var, a *.auto.tfvars file, or TF_VAR_alert_email."
  type        = string
}
