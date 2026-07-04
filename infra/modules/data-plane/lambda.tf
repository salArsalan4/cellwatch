# Zips infra/build/{layer,ingest,processor} produced by
# infra/scripts/build_lambda_artifacts.sh. Run that script (or re-run it
# after touching services/common or the layer's pinned deps) before
# `terraform plan` — Terraform only sees the zip hash, not the source.

data "archive_file" "layer" {
  type        = "zip"
  source_dir  = "${path.root}/build/layer"
  output_path = "${path.root}/build/layer.zip"
}

resource "aws_lambda_layer_version" "deps" {
  layer_name          = "${var.project_name}-deps"
  filename            = data.archive_file.layer.output_path
  source_code_hash    = data.archive_file.layer.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

data "aws_iam_role" "lab" {
  name = var.lab_role_name
}

data "archive_file" "ingest" {
  type        = "zip"
  source_dir  = "${path.root}/build/ingest"
  output_path = "${path.root}/build/ingest.zip"
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${var.project_name}-ingest"
  filename         = data.archive_file.ingest.output_path
  source_code_hash = data.archive_file.ingest.output_base64sha256
  handler          = "handler.handler"
  runtime          = "python3.12"
  role             = data.aws_iam_role.lab.arn
  layers           = [aws_lambda_layer_version.deps.arn]
  timeout          = 10
  memory_size      = 256

  # Load testing (100 rps sustained) showed heavy throttling on THIS
  # function even though its own execution duration was tiny (14-33ms avg
  # per CloudWatch's Duration metric -- confirmed via GetMetricStatistics,
  # not guessed). Bumping memory to 512MB didn't help (made p95 worse, if
  # anything) because duration was never the bottleneck. Root cause: the
  # lab's 10-concurrent-execution ceiling is account-wide, shared with
  # processor, and processor's SQS-triggered concurrency scales up to
  # drain any backlog -- happily consuming most/all of the shared pool
  # while ingest (synchronous, client waiting on it) starves. Reserving
  # concurrency here guarantees ingest a protected minimum regardless of
  # how busy processor is; leaving processor unreserved still gives it the
  # remaining ~6 slots, generous given batch_size=100 per invocation.
  # 4 reserved x ~20-30ms duration => a ~150-200 rps ceiling for ingest
  # alone, comfortably above the 100 rps sustained target -- so 256MB is
  # plenty; the fix was concurrency isolation, not more CPU.
  reserved_concurrent_executions = 4

  environment {
    variables = {
      INGEST_QUEUE_URL             = aws_sqs_queue.ingest.id
      POWERTOOLS_SERVICE_NAME      = "ingest"
      POWERTOOLS_METRICS_NAMESPACE = "CellWatch"
    }
  }

  tags = {
    Name = "${var.project_name}-ingest"
  }
}

data "archive_file" "processor" {
  type        = "zip"
  source_dir  = "${path.root}/build/processor"
  output_path = "${path.root}/build/processor.zip"
}

resource "aws_lambda_function" "processor" {
  function_name    = "${var.project_name}-processor"
  filename         = data.archive_file.processor.output_path
  source_code_hash = data.archive_file.processor.output_base64sha256
  handler          = "handler.handler"
  runtime          = "python3.12"
  role             = data.aws_iam_role.lab.arn
  layers           = [aws_lambda_layer_version.deps.arn]
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      RAW_ARCHIVE_BUCKET           = aws_s3_bucket.raw.bucket
      KPI_TABLE_NAME               = aws_dynamodb_table.kpi.name
      ALERTS_TOPIC_ARN             = aws_sns_topic.alerts.arn
      POWERTOOLS_SERVICE_NAME      = "processor"
      POWERTOOLS_METRICS_NAMESPACE = "CellWatch"
    }
  }

  tags = {
    Name = "${var.project_name}-processor"
  }
}

# processor stays unreserved deliberately -- it should be free to use
# whatever's left of the account's 10-execution pool (up to ~6, given
# ingest's reservation above) to drain SQS backlogs as fast as possible;
# capping it further would just slow down recovery from a burst.
resource "aws_lambda_event_source_mapping" "processor_from_sqs" {
  event_source_arn                   = aws_sqs_queue.ingest.arn
  function_name                      = aws_lambda_function.processor.arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]
}
