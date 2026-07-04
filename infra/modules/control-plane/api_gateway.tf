# Query/admin API: a {proxy+} integration in front of one Lambda, routed
# internally by Powertools' APIGatewayRestResolver (see
# services/query/handler.py) -- one Terraform integration instead of one
# per endpoint, unlike the ingest API which validates a single fixed shape.
#
# GET is split into its own method (instead of routing everything through
# ANY) specifically so caching can be scoped to it alone. API Gateway can
# only enable per-method-settings caching via an exact "{resource_path}/
# {http_method}" override or "*/*" for everything in the stage -- there's
# no "GET on any resource" wildcard. Caching the ANY method would mean
# caching POST/PUT/DELETE too, which is actively wrong (a POST could get
# cached and served back to a later GET). With GET defined explicitly,
# API Gateway routes GET requests to it and everything else falls through
# to ANY, so only GET responses ever enter the cache.

resource "aws_api_gateway_rest_api" "query" {
  name = "${var.project_name}-query"
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.query.id
  parent_id   = aws_api_gateway_rest_api.query.root_resource_id
  path_part   = "{proxy+}"
}

# {proxy+} means API Gateway has no per-route knowledge of query strings
# (all routing happens inside the Lambda's Powertools resolver) -- so every
# query param used by any GET route has to be declared here and added to
# the integration's cache_key_parameters below. Otherwise the cache key is
# path-only, and e.g. /cells/X/kpis?limit=10 would wrongly serve the cached
# response for a prior ?limit=100 request on the same path.
locals {
  proxy_query_params = ["limit", "from", "to", "cell_id", "active"]
}

resource "aws_api_gateway_method" "proxy_get" {
  rest_api_id      = aws_api_gateway_rest_api.query.id
  resource_id      = aws_api_gateway_resource.proxy.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true

  request_parameters = merge(
    { "method.request.path.proxy" = true },
    # Origin is declared (and added to the integration's cache_key_parameters
    # below) so the GET cache keys on it. Powertools only emits CORS headers
    # when the request carries an Origin, so without this a CORS-less response
    # from a no-Origin caller (curl, a health check) could be cached and then
    # served to a browser request within the TTL -- breaking the dashboard's
    # Live mode intermittently. Keying on Origin gives browser requests (which
    # always send one) their own CORS-headed cache entries.
    { "method.request.header.Origin" = false },
    { for p in local.proxy_query_params : "method.request.querystring.${p}" => false }
  )
}

resource "aws_api_gateway_integration" "proxy_get" {
  rest_api_id             = aws_api_gateway_rest_api.query.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.query.invoke_arn
  cache_key_parameters = concat(
    ["method.request.path.proxy", "method.request.header.Origin"],
    [for p in local.proxy_query_params : "method.request.querystring.${p}"]
  )
}

resource "aws_api_gateway_method" "proxy_any" {
  rest_api_id      = aws_api_gateway_rest_api.query.id
  resource_id      = aws_api_gateway_resource.proxy.id
  http_method      = "ANY"
  authorization    = "NONE"
  api_key_required = true

  request_parameters = {
    "method.request.path.proxy" = true
  }
}

resource "aws_api_gateway_integration" "proxy_any" {
  rest_api_id             = aws_api_gateway_rest_api.query.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy_any.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.query.invoke_arn
}

# Browser CORS preflight (see frontend/README.md). A preflight OPTIONS
# request never carries the x-api-key header, so it can't go through
# proxy_any (api_key_required = true) -- it would 403 before Lambda ever
# runs. This is a dedicated MOCK integration that answers the preflight
# directly in API Gateway, and it's the one method on this resource with
# api_key_required = false.
resource "aws_api_gateway_method" "proxy_options" {
  rest_api_id      = aws_api_gateway_rest_api.query.id
  resource_id      = aws_api_gateway_resource.proxy.id
  http_method      = "OPTIONS"
  authorization    = "NONE"
  api_key_required = false

  request_parameters = {
    "method.request.path.proxy" = true
  }
}

resource "aws_api_gateway_integration" "proxy_options" {
  rest_api_id = aws_api_gateway_rest_api.query.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "proxy_options" {
  rest_api_id = aws_api_gateway_rest_api.query.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = true
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
  }
}

resource "aws_api_gateway_integration_response" "proxy_options" {
  rest_api_id = aws_api_gateway_rest_api.query.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  status_code = aws_api_gateway_method_response.proxy_options.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = "'${var.cors_allow_origin}'"
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,x-api-key'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS'"
  }
}

resource "aws_lambda_permission" "apigw_invoke_query" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.query.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.query.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "query" {
  rest_api_id = aws_api_gateway_rest_api.query.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.proxy.id,
      aws_api_gateway_method.proxy_get.id,
      aws_api_gateway_integration.proxy_get.id,
      aws_api_gateway_method.proxy_any.id,
      aws_api_gateway_integration.proxy_any.id,
      aws_api_gateway_method.proxy_options.id,
      aws_api_gateway_integration.proxy_options.id,
      aws_api_gateway_integration_response.proxy_options.id,
      # Config values (not just IDs) so an in-place cache-key/param change
      # forces a redeploy -- the resource IDs above don't change when only
      # request_parameters/cache_key_parameters are edited.
      aws_api_gateway_method.proxy_get.request_parameters,
      aws_api_gateway_integration.proxy_get.cache_key_parameters,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "this" {
  rest_api_id   = aws_api_gateway_rest_api.query.id
  deployment_id = aws_api_gateway_deployment.query.id
  stage_name    = var.environment

  cache_cluster_enabled = var.enable_cache
  cache_cluster_size    = var.enable_cache ? "0.5" : null
}

resource "aws_api_gateway_method_settings" "get_caching" {
  count       = var.enable_cache ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.query.id
  stage_name  = aws_api_gateway_stage.this.stage_name
  method_path = "${trimprefix(aws_api_gateway_resource.proxy.path, "/")}/GET"

  settings {
    caching_enabled      = true
    cache_ttl_in_seconds = 30
  }
}

resource "aws_api_gateway_usage_plan" "query" {
  name = "${var.project_name}-query-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.query.id
    stage  = aws_api_gateway_stage.this.stage_name
  }

  throttle_settings {
    rate_limit  = 20 # NFR: ~20 read RPS steady state (§4.1)
    burst_limit = 50
  }
}

resource "aws_api_gateway_api_key" "query_client" {
  name = "${var.project_name}-query-client-key"
}

resource "aws_api_gateway_usage_plan_key" "query_client" {
  key_id        = aws_api_gateway_api_key.query_client.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.query.id
}
