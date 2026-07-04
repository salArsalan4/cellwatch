# Single-AZ db.t3.micro per docs/OVERVIEW.md §6/§8 (lab restricts Multi-AZ;
# Enhanced Monitoring must stay off). Subnet group still spans 2 AZs so
# promoting to Multi-AZ later is a one-flag change with no network rework.
#
# engine_version is resolved dynamically (AWS's current default for the
# engine) rather than hardcoded -- a pinned minor version risks not being
# offered in this account/region by apply time, and there's no requirement
# here that needs a specific one. It's referenced explicitly (rather than
# left for AWS to pick silently) only because the SSL-enforcement parameter
# group below needs a matching `family`, e.g. "postgres16".

data "aws_rds_engine_version" "postgres" {
  engine       = "postgres"
  default_only = true
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "${var.project_name}-db-subnet-group"
  }
}

# rds.force_ssl is a static parameter (needs a reboot to take effect on a
# live instance) -- applied here at creation time instead, so SSL is
# enforced from the instance's first boot with zero extra downtime.
resource "aws_db_parameter_group" "postgres_ssl" {
  name   = "${var.project_name}-pg-force-ssl"
  family = data.aws_rds_engine_version.postgres.parameter_group_family

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }

  tags = {
    Name = "${var.project_name}-pg-force-ssl"
  }
}

resource "aws_db_instance" "this" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = data.aws_rds_engine_version.postgres.version
  instance_class = "db.t3.micro"

  allocated_storage = 20
  storage_type      = "gp2"
  storage_encrypted = true
  kms_key_id        = var.kms_key_arn

  db_name                     = "cellwatch"
  username                    = "cellwatch_admin"
  manage_master_user_password = true # RDS creates + owns the secret; no plaintext password anywhere

  db_subnet_group_name    = aws_db_subnet_group.this.name
  parameter_group_name    = aws_db_parameter_group.postgres_ssl.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  publicly_accessible     = false
  multi_az                = false
  monitoring_interval     = 0 # Enhanced Monitoring must stay off (lab constraint)
  backup_retention_period = 7 # enables automated backups + PITR

  apply_immediately   = true
  skip_final_snapshot = true
  deletion_protection = false

  tags = {
    Name = "${var.project_name}-db"
  }
}

# NOTE: a kms_key_id change forces replacement, but with an unchanged
# `identifier` this provider version attempts create-before-destroy
# regardless of an explicit `lifecycle { create_before_destroy = false }`
# (tried it -- no effect), which fails with DBInstanceAlreadyExists since
# the old instance still holds the name. If this ever needs to happen
# again: `terraform state rm` the instance, delete it directly via
# `aws rds delete-db-instance`, wait for it to actually finish deleting,
# then `apply` again for a clean create with no replace ambiguity.
