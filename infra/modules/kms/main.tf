# One customer-managed key for at-rest encryption across DynamoDB, S3, SQS,
# and RDS (docs/OVERVIEW.md §7.2) -- an owned, auditable CMK is stronger
# evidence than each service's default SSE key. Key *policies* (unlike IAM
# policies) attach directly to the resource, so this works fine even though
# the lab blocks creating/attaching IAM policies to LabRole.

data "aws_caller_identity" "current" {}

data "aws_iam_role" "lab" {
  name = var.lab_role_name
}

resource "aws_kms_key" "this" {
  description             = "${var.project_name} CMK for DynamoDB/S3/SQS/RDS at-rest encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowLabRoleUsage"
        Effect    = "Allow"
        Principal = { AWS = data.aws_iam_role.lab.arn }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
          "kms:CreateGrant",
        ]
        Resource = "*"
      },
    ]
  })

  tags = {
    Name = "${var.project_name}-cmk"
  }
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.project_name}"
  target_key_id = aws_kms_key.this.key_id
}
