# Cross-referencing rules (Lambda -> RDS, RDS -> Lambda) are split into
# standalone aws_security_group_rule resources rather than inline ingress/
# egress blocks: two SGs whose inline rules reference each other's ID create
# a dependency cycle Terraform can't resolve. Standalone rules attach after
# both (empty) SGs already exist, so there's no cycle.

data "aws_region" "current" {}

# Gateway VPC endpoints (S3, DynamoDB) aren't attached to an ENI, so there's
# no security group to reference for them the way there is for interface
# endpoints -- they're a route-table prefix-list redirect instead. Egress
# has to be permitted against that prefix list directly, or traffic to them
# has no matching egress rule and just hangs until the Lambda times out
# (exactly what happened testing /cells/{id}/health: it hung 15s on the
# DynamoDB call with no egress rule allowing it, RDS-only routes were fine).
data "aws_prefix_list" "dynamodb" {
  name = "com.amazonaws.${data.aws_region.current.name}.dynamodb"
}

resource "aws_security_group" "lambda" {
  name        = "${var.project_name}-control-plane-lambda-sg"
  description = "Query/migrate Lambda: egress to RDS and VPC interface endpoints only"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.project_name}-control-plane-lambda-sg"
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "RDS Postgres: ingress from the control-plane Lambda security group only"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.project_name}-rds-sg"
  }
}

resource "aws_security_group_rule" "lambda_egress_rds" {
  type                     = "egress"
  security_group_id        = aws_security_group.lambda.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.rds.id
  description              = "Postgres to RDS"
}

resource "aws_security_group_rule" "lambda_egress_vpc_endpoints" {
  type                     = "egress"
  security_group_id        = aws_security_group.lambda.id
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  source_security_group_id = var.vpc_endpoints_security_group_id
  description              = "HTTPS to Secrets Manager / X-Ray interface endpoints"
}

resource "aws_security_group_rule" "lambda_egress_dynamodb" {
  type              = "egress"
  security_group_id = aws_security_group.lambda.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  prefix_list_ids   = [data.aws_prefix_list.dynamodb.id]
  description       = "HTTPS to DynamoDB via the gateway VPC endpoint"
}

resource "aws_security_group_rule" "rds_ingress_lambda" {
  type                     = "ingress"
  security_group_id        = aws_security_group.rds.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.lambda.id
  description              = "Postgres from control-plane Lambda"
}
