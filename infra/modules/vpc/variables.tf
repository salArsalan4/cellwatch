variable "project_name" {
  description = "Project name used as a resource-naming prefix."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
}

variable "az_count" {
  description = "Number of AZs to span (one public + one private subnet each)."
  type        = number
  default     = 2
}
