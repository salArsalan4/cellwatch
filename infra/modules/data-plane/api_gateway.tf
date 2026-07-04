# Ingest API: POST /kpi, API-key gated, request body validated against the
# same schema (schemas/kpi_sample.schema.json) the ingest Lambda re-validates
# with Pydantic — edge validation plus defense in depth (§7.2 Security).

resource "aws_api_gateway_rest_api" "ingest" {
  name = "${var.project_name}-ingest"
}

resource "aws_api_gateway_resource" "kpi" {
  rest_api_id = aws_api_gateway_rest_api.ingest.id
  parent_id   = aws_api_gateway_rest_api.ingest.root_resource_id
  path_part   = "kpi"
}

resource "aws_api_gateway_model" "kpi_sample" {
  rest_api_id  = aws_api_gateway_rest_api.ingest.id
  name         = "KpiSample"
  content_type = "application/json"
  schema       = file("${path.root}/../services/common/schemas/kpi_sample.schema.json")
}

resource "aws_api_gateway_request_validator" "body" {
  rest_api_id           = aws_api_gateway_rest_api.ingest.id
  name                  = "validate-body"
  validate_request_body = true
}

resource "aws_api_gateway_method" "post_kpi" {
  rest_api_id      = aws_api_gateway_rest_api.ingest.id
  resource_id      = aws_api_gateway_resource.kpi.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true

  request_validator_id = aws_api_gateway_request_validator.body.id
  request_models = {
    "application/json" = aws_api_gateway_model.kpi_sample.name
  }
}

resource "aws_api_gateway_integration" "post_kpi" {
  rest_api_id             = aws_api_gateway_rest_api.ingest.id
  resource_id             = aws_api_gateway_resource.kpi.id
  http_method             = aws_api_gateway_method.post_kpi.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.ingest.invoke_arn
}

resource "aws_lambda_permission" "apigw_invoke_ingest" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.ingest.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "ingest" {
  rest_api_id = aws_api_gateway_rest_api.ingest.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.kpi.id,
      aws_api_gateway_model.kpi_sample.id,
      aws_api_gateway_method.post_kpi.id,
      aws_api_gateway_integration.post_kpi.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "this" {
  rest_api_id   = aws_api_gateway_rest_api.ingest.id
  deployment_id = aws_api_gateway_deployment.ingest.id
  stage_name    = var.environment
}

resource "aws_api_gateway_usage_plan" "ingest" {
  name = "${var.project_name}-ingest-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.ingest.id
    stage  = aws_api_gateway_stage.this.stage_name
  }

  throttle_settings {
    # NFR (§4.2) is actually two numbers: sustain 100 rps, *and* absorb a
    # 500 rps burst with zero sample loss. A tight burst_limit here would
    # mean API Gateway itself 429s most of that burst before it ever
    # reaches SQS -- which would hide the exact behavior this architecture
    # is supposed to demonstrate (SQS buffering above the 10-Lambda
    # ceiling). rate_limit/burst_limit are raised to admit the full 500
    # rps target; the 10-Lambda ceiling is still the real constraint
    # downstream, enforced by the queue, not by throttling at the edge.
    rate_limit  = 500
    burst_limit = 1000
  }
}

resource "aws_api_gateway_api_key" "generator" {
  name = "${var.project_name}-generator-key"
}

resource "aws_api_gateway_usage_plan_key" "generator" {
  key_id        = aws_api_gateway_api_key.generator.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.ingest.id
}
