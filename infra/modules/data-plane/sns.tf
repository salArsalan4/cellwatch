# Anomaly alerts. Two subscribers: the NOC's email (the actual alert) and
# the control-plane's alerter Lambda (writes the audit-trail row to RDS --
# see services/alerter's module docstring for why that's a separate,
# VPC-bound consumer rather than the processor writing to RDS directly).

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
