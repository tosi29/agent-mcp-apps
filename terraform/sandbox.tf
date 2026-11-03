locals {
  # Depend only on the API ID, not its deployment/stage: the Lambda is shared.
  sandbox_url = length(aws_bedrockagentcore_agent_runtime.agent) > 0 ? "https://${aws_api_gateway_rest_api.sandbox[0].id}.execute-api.ap-northeast-1.amazonaws.com/poc/sandbox" : null
}

resource "aws_api_gateway_rest_api" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name        = "agent-mcp-apps-sandbox"
  description = "IP-restricted MCP Apps sandbox on a separate origin, sharing the Next.js Lambda"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_rest_api_policy" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.sandbox[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Deny"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "${aws_api_gateway_rest_api.sandbox[0].execution_arn}/*"
        Condition = { NotIpAddress = { "aws:SourceIp" = var.allowed_source_cidrs } }
      },
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "${aws_api_gateway_rest_api.sandbox[0].execution_arn}/poc/GET/sandbox"
      }
    ]
  })

  lifecycle {
    precondition {
      condition     = length(var.allowed_source_cidrs) > 0
      error_message = "sandboxのアクセス元をallowed_source_cidrsで制限してください。"
    }
  }
}

resource "aws_api_gateway_resource" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.sandbox[0].id
  parent_id   = aws_api_gateway_rest_api.sandbox[0].root_resource_id
  path_part   = "sandbox"
}

resource "aws_api_gateway_method" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id   = aws_api_gateway_rest_api.sandbox[0].id
  resource_id   = aws_api_gateway_resource.sandbox[0].id
  http_method   = "GET"
  authorization = "NONE" # The resource policy enforces the same IP restriction as the chat.
}

resource "aws_api_gateway_integration" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id             = aws_api_gateway_rest_api.sandbox[0].id
  resource_id             = aws_api_gateway_resource.sandbox[0].id
  http_method             = aws_api_gateway_method.sandbox[0].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  # Match the existing Lambda Web Adapter's response_stream output format.
  uri                    = "arn:${local.partition}:apigateway:ap-northeast-1:lambda:path/2021-11-15/functions/${aws_lambda_function.web[0].arn}/response-streaming-invocations"
  response_transfer_mode = "STREAM"
  timeout_milliseconds   = 29000
}

resource "aws_lambda_permission" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  statement_id_prefix = "AllowApiGatewaySandbox-"
  action              = "lambda:InvokeFunction"
  function_name       = aws_lambda_function.web[0].function_name
  principal           = "apigateway.amazonaws.com"
  source_account      = local.account_id
  source_arn          = "${aws_api_gateway_rest_api.sandbox[0].execution_arn}/poc/GET/sandbox"
}

resource "aws_api_gateway_deployment" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.sandbox[0].id
  triggers = {
    redeployment = sha256(jsonencode({
      resource      = aws_api_gateway_integration.sandbox[0].resource_id
      method        = aws_api_gateway_integration.sandbox[0].http_method
      authorization = aws_api_gateway_method.sandbox[0].authorization
      uri           = aws_api_gateway_integration.sandbox[0].uri
      mode          = aws_api_gateway_integration.sandbox[0].response_transfer_mode
      timeout       = aws_api_gateway_integration.sandbox[0].timeout_milliseconds
      policy        = aws_api_gateway_rest_api_policy.sandbox[0].policy
    }))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [aws_lambda_permission.sandbox]
}

resource "aws_api_gateway_stage" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id   = aws_api_gateway_rest_api.sandbox[0].id
  deployment_id = aws_api_gateway_deployment.sandbox[0].id
  stage_name    = "poc"
}

resource "aws_api_gateway_method_settings" "sandbox" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.sandbox[0].id
  stage_name  = aws_api_gateway_stage.sandbox[0].stage_name
  method_path = "*/*"

  settings {
    throttling_burst_limit = 30
    throttling_rate_limit  = 10
    caching_enabled        = false
    data_trace_enabled     = false
    logging_level          = "OFF"
    metrics_enabled        = false
  }
}
