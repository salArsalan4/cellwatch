# The four alarm categories docs/OVERVIEW.md §7.1 calls out explicitly:
# ingest 5xx rate, DLQ depth > 0 (both DLQs), processing duration p95, RDS
# CPU/connections. All notify the same SNS topic the NOC alerts use --
# one already-confirmed email subscription covers both anomaly alerts and
# infra alarms rather than requiring a second confirmation click.

resource "aws_cloudwatch_metric_alarm" "ingest_5xx" {
  alarm_name          = "${var.project_name}-ingest-5xx"
  alarm_description   = "Ingest API Gateway is returning 5xx errors"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5XXError"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ApiName = var.ingest_api_name
    Stage   = var.ingest_stage_name
  }

  alarm_actions = [var.alarm_topic_arn]
  ok_actions    = [var.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "ingest_dlq_depth" {
  alarm_name          = "${var.project_name}-ingest-dlq-depth"
  alarm_description   = "Poison messages sitting in the ingest DLQ"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.ingest_dlq_name
  }

  alarm_actions = [var.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "alerter_dlq_depth" {
  alarm_name          = "${var.project_name}-alerter-dlq-depth"
  alarm_description   = "Alert notifications that failed to write to RDS"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.alerter_dlq_name
  }

  alarm_actions = [var.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "processor_duration_p95" {
  alarm_name          = "${var.project_name}-processor-duration-p95"
  alarm_description   = "Processor Lambda p95 duration approaching its 30s timeout"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 2
  threshold           = 20000 # ms -- ~66% of the processor's configured timeout
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.processor_function_name
  }

  alarm_actions = [var.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${var.project_name}-rds-cpu"
  alarm_description   = "RDS CPU utilization high (db.t3.micro is burstable -- sustained high usage exhausts CPU credits)"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBInstanceIdentifier = var.db_instance_id
  }

  alarm_actions = [var.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${var.project_name}-rds-connections"
  alarm_description   = "RDS connection count approaching db.t3.micro's practical ceiling"
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 60
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBInstanceIdentifier = var.db_instance_id
  }

  alarm_actions = [var.alarm_topic_arn]
}
