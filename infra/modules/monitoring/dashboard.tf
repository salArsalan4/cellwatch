data "aws_region" "current" {}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 8, height = 6
        properties = {
          title  = "Ingest API - requests & errors"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiName", var.ingest_api_name, "Stage", var.ingest_stage_name, { stat = "Sum", label = "Requests" }],
            ["AWS/ApiGateway", "5XXError", "ApiName", var.ingest_api_name, "Stage", var.ingest_stage_name, { stat = "Sum", label = "5xx" }],
            ["AWS/ApiGateway", "4XXError", "ApiName", var.ingest_api_name, "Stage", var.ingest_stage_name, { stat = "Sum", label = "4xx" }],
          ]
        }
      },
      {
        type = "metric", x = 8, y = 0, width = 8, height = 6
        properties = {
          title  = "Queue depth"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.ingest_queue_name, { stat = "Maximum", label = "Ingest queue" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.ingest_dlq_name, { stat = "Maximum", label = "Ingest DLQ" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.alerter_dlq_name, { stat = "Maximum", label = "Alerter DLQ" }],
          ]
        }
      },
      {
        type = "metric", x = 16, y = 0, width = 8, height = 6
        properties = {
          title  = "Data-plane Lambdas"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.ingest_function_name, { stat = "Sum", label = "ingest invocations" }],
            ["AWS/Lambda", "Errors", "FunctionName", var.ingest_function_name, { stat = "Sum", label = "ingest errors" }],
            ["AWS/Lambda", "Invocations", "FunctionName", var.processor_function_name, { stat = "Sum", label = "processor invocations" }],
            ["AWS/Lambda", "Errors", "FunctionName", var.processor_function_name, { stat = "Sum", label = "processor errors" }],
            ["AWS/Lambda", "Duration", "FunctionName", var.processor_function_name, { stat = "p95", label = "processor duration p95 (ms)" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 8, height = 6
        properties = {
          title  = "Anomaly detection"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["CellWatch", "AnomaliesDetected", "service", "processor", { stat = "Sum" }],
            ["CellWatch", "AlertsWritten", "service", "alerter", { stat = "Sum" }],
          ]
        }
      },
      {
        type = "metric", x = 8, y = 6, width = 8, height = 6
        properties = {
          title  = "Control-plane Lambdas (query/alerter)"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.query_function_name, { stat = "Sum", label = "query invocations" }],
            ["AWS/Lambda", "Errors", "FunctionName", var.query_function_name, { stat = "Sum", label = "query errors" }],
            ["AWS/Lambda", "Duration", "FunctionName", var.query_function_name, { stat = "p95", label = "query duration p95 (ms)" }],
            ["AWS/Lambda", "Errors", "FunctionName", var.alerter_function_name, { stat = "Sum", label = "alerter errors" }],
          ]
        }
      },
      {
        type = "metric", x = 16, y = 6, width = 8, height = 6
        properties = {
          title  = "RDS"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_id, { stat = "Average", label = "CPU %" }],
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", var.db_instance_id, { stat = "Average", label = "Connections" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 12, width = 8, height = 6
        properties = {
          title  = "DynamoDB consumed capacity"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", var.kpi_table_name, { stat = "Sum" }],
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", var.kpi_table_name, { stat = "Sum" }],
          ]
        }
      },
    ]
  })
}
