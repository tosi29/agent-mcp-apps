locals {
  bridge_name = "agent-mcp-apps-streaming"
  bridge_zip  = "${path.module}/lambda/dist/bridge.zip"
}

resource "aws_cloudwatch_log_group" "bridge" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name              = "/aws/lambda/${local.bridge_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "bridge" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name = "${local.bridge_name}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "bridge" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name = "invoke_agent_and_logs"
  role = aws_iam_role.bridge[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["bedrock-agentcore:InvokeAgentRuntime"]
        Resource = [
          one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn),
          "${one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn)}/runtime-endpoint/DEFAULT",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.bridge[0].arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "bridge" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  function_name    = local.bridge_name
  description      = "AG-UI SSE bridge to the fixture AgentCore Runtime"
  role             = aws_iam_role.bridge[0].arn
  runtime          = "nodejs26.x"
  architectures    = ["arm64"]
  handler          = "index.handler"
  filename         = local.bridge_zip
  source_code_hash = fileexists(local.bridge_zip) ? filebase64sha256(local.bridge_zip) : null
  memory_size      = 256
  timeout          = 150

  environment {
    variables = {
      AGENT_RUNTIME_ARN = one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn)
      DO_NOT_TRACK      = "1"
    }
  }

  lifecycle {
    precondition {
      condition     = fileexists(local.bridge_zip)
      error_message = "terraform/lambda/でnpm ci --ignore-scriptsとnpm run buildを実行してください。"
    }
  }

  depends_on = [aws_iam_role_policy.bridge]
}

resource "aws_api_gateway_rest_api" "agent" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name        = local.bridge_name
  description = "IAM-authenticated AG-UI response streaming PoC"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "invocations" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.agent[0].id
  parent_id   = aws_api_gateway_rest_api.agent[0].root_resource_id
  path_part   = "invocations"
}

resource "aws_api_gateway_method" "invocations" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id   = aws_api_gateway_rest_api.agent[0].id
  resource_id   = aws_api_gateway_resource.invocations[0].id
  http_method   = "POST"
  authorization = "AWS_IAM"
}

resource "aws_api_gateway_integration" "invocations" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id             = aws_api_gateway_rest_api.agent[0].id
  resource_id             = aws_api_gateway_resource.invocations[0].id
  http_method             = aws_api_gateway_method.invocations[0].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:${local.partition}:apigateway:ap-northeast-1:lambda:path/2021-11-15/functions/${aws_lambda_function.bridge[0].arn}/response-streaming-invocations"
  response_transfer_mode  = "STREAM"
  timeout_milliseconds    = 155000
}

resource "aws_lambda_permission" "api_gateway" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  statement_id   = "AllowApiGatewayStream"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.bridge[0].function_name
  principal      = "apigateway.amazonaws.com"
  source_account = local.account_id
  source_arn     = "${aws_api_gateway_rest_api.agent[0].execution_arn}/poc/POST/invocations"
}

resource "aws_api_gateway_deployment" "agent" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.agent[0].id
  triggers = {
    redeployment = sha256(jsonencode({
      path          = aws_api_gateway_resource.invocations[0].path_part
      authorization = aws_api_gateway_method.invocations[0].authorization
      method        = aws_api_gateway_method.invocations[0].http_method
      uri           = aws_api_gateway_integration.invocations[0].uri
      transfer_mode = aws_api_gateway_integration.invocations[0].response_transfer_mode
      timeout       = aws_api_gateway_integration.invocations[0].timeout_milliseconds
    }))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [aws_lambda_permission.api_gateway]
}

resource "aws_api_gateway_stage" "agent" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id   = aws_api_gateway_rest_api.agent[0].id
  deployment_id = aws_api_gateway_deployment.agent[0].id
  stage_name    = "poc"
}

resource "aws_api_gateway_method_settings" "agent" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.agent[0].id
  stage_name  = aws_api_gateway_stage.agent[0].stage_name
  method_path = "*/*"

  settings {
    throttling_burst_limit = 2
    throttling_rate_limit  = 1
    caching_enabled        = false
    data_trace_enabled     = false
    logging_level          = "OFF"
    metrics_enabled        = false
  }
}
