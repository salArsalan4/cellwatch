# SNS-triggered, VPC-bound consumer that writes the RDS alert row for each
# anomaly the processor publishes (see services/alerter's module docstring
# for why this is a separate Lambda from the processor). SNS retries failed
# deliveries on its own schedule and redrives to alerter_dlq after that --
# no custom retry logic needed here.

resource "aws_sqs_queue" "alerter_dlq" {
  name                      = "${var.project_name}-alerter-dlq"
  message_retention_seconds = 1209600 # 14 days
  kms_master_key_id         = var.kms_key_arn

  tags = {
    Name = "${var.project_name}-alerter-dlq"
  }
}

data "archive_file" "alerter" {
  type        = "zip"
  source_dir  = "${path.root}/build/alerter"
  output_path = "${path.root}/build/alerter.zip"
}

resource "aws_lambda_function" "alerter" {
  function_name    = "${var.project_name}-alerter"
  filename         = data.archive_file.alerter.output_path
  source_code_hash = data.archive_file.alerter.output_base64sha256
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
      POWERTOOLS_SERVICE_NAME      = "alerter"
      POWERTOOLS_METRICS_NAMESPACE = "CellWatch"
    }
  }

  tags = {
    Name = "${var.project_name}-alerter"
  }
}

resource "aws_lambda_permission" "sns_invoke_alerter" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alerter.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = var.alerts_topic_arn
}

resource "aws_sns_topic_subscription" "alerter" {
  topic_arn = var.alerts_topic_arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.alerter.arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.alerter_dlq.arn
  })
}
