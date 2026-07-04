# Local state on purpose: this is a solo, time-boxed term project running against
# AWS Academy Learner Lab, which persists resources (and therefore a local state
# file stays valid) across sessions on the same dev machine. An S3+DynamoDB remote
# backend would need its own bootstrap and buys nothing without a second collaborator.
# Production note: swap this for an S3 backend with state locking before any team use.
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
