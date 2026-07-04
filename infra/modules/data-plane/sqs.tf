# Buffer between API Gateway and the processing Lambda. This is what absorbs
# bursts above the lab's 10-concurrent-execution ceiling (§4.1) and what keeps
# an accepted sample durable even if processing/RDS is down (§7.3).

resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${var.project_name}-ingest-dlq"
  message_retention_seconds = 1209600 # 14 days — max time to investigate/redrive poison messages
  kms_master_key_id         = var.kms_key_arn

  tags = {
    Name = "${var.project_name}-ingest-dlq"
  }
}

resource "aws_sqs_queue" "ingest" {
  name                       = "${var.project_name}-ingest"
  visibility_timeout_seconds = 60     # >= processor Lambda timeout (30s) with headroom for batch processing
  message_retention_seconds  = 345600 # 4 days
  kms_master_key_id          = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name = "${var.project_name}-ingest"
  }
}
