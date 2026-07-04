# Zips infra/build/{db-layer,query,migrate} produced by
# infra/scripts/build_lambda_artifacts.sh. Both functions also take the
# shared data-plane layer (var.shared_layer_arn) so services/common and
# powertools/pydantic aren't duplicated per module.

data "aws_iam_role" "lab" {
  name = var.lab_role_name
}

data "archive_file" "db_layer" {
  type        = "zip"
  source_dir  = "${path.root}/build/db-layer"
  output_path = "${path.root}/build/db-layer.zip"
}

resource "aws_lambda_layer_version" "db_deps" {
  layer_name          = "${var.project_name}-db-deps"
  filename            = data.archive_file.db_layer.output_path
  source_code_hash    = data.archive_file.db_layer.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

data "archive_file" "query" {
  type        = "zip"
  source_dir  = "${path.root}/build/query"
  output_path = "${path.root}/build/query.zip"
}

resource "aws_lambda_function" "query" {
  function_name    = "${var.project_name}-query"
  filename         = data.archive_file.query.output_path
  source_code_hash = data.archive_file.query.output_base64sha256
  handler          = "handler.handler"
  runtime          = "python3.12"
  role             = data.aws_iam_role.lab.arn
  layers           = [var.shared_layer_arn, aws_lambda_layer_version.db_deps.arn]
  timeout          = 15
  memory_size      = 256

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      DB_HOST                      = aws_db_instance.this.address
      DB_PORT                      = tostring(aws_db_instance.this.port)
      DB_NAME                      = aws_db_instance.this.db_name
      DB_SECRET_ARN                = aws_db_instance.this.master_user_secret[0].secret_arn
      KPI_TABLE_NAME               = var.kpi_table_name
      POWERTOOLS_SERVICE_NAME      = "query"
      POWERTOOLS_METRICS_NAMESPACE = "CellWatch"
      CORS_ALLOW_ORIGIN            = var.cors_allow_origin
    }
  }

  tags = {
    Name = "${var.project_name}-query"
  }
}

data "archive_file" "migrate" {
  type        = "zip"
  source_dir  = "${path.root}/build/migrate"
  output_path = "${path.root}/build/migrate.zip"
}

# Not on any request path -- invoke manually once RDS is up:
#   aws lambda invoke --function-name cellwatch-migrate --payload '{}' out.json
# (see services/migrate/handler.py for why this has to be a Lambda: RDS has
# no NAT/bastion path from outside the VPC.)
resource "aws_lambda_function" "migrate" {
  function_name    = "${var.project_name}-migrate"
  filename         = data.archive_file.migrate.output_path
  source_code_hash = data.archive_file.migrate.output_base64sha256
  handler          = "handler.handler"
  runtime          = "python3.12"
  role             = data.aws_iam_role.lab.arn
  layers           = [var.shared_layer_arn, aws_lambda_layer_version.db_deps.arn]
  timeout          = 30
  memory_size      = 256

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DB_HOST                 = aws_db_instance.this.address
      DB_PORT                 = tostring(aws_db_instance.this.port)
      DB_NAME                 = aws_db_instance.this.db_name
      DB_SECRET_ARN           = aws_db_instance.this.master_user_secret[0].secret_arn
      POWERTOOLS_SERVICE_NAME = "migrate"
    }
  }

  tags = {
    Name = "${var.project_name}-migrate"
  }
}
