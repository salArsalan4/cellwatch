variable "project_name" {
  type = string
}

variable "lab_role_name" {
  description = "Name of the pre-baked AWS Academy Learner Lab execution role."
  type        = string
  default     = "LabRole"
}
