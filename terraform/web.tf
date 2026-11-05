locals {
  # Reuse the deployed Lambda, role and log group instead of replacing them by name.
  web_name = "agent-mcp-apps-streaming"
  web_zip  = "${path.module}/../app/dist/web.zip"
}

moved {
  from = aws_cloudwatch_log_group.bridge[0]
  to   = aws_cloudwatch_log_group.web[0]
}
moved {
  from = aws_iam_role.bridge[0]
  to   = aws_iam_role.web[0]
}
moved {
  from = aws_iam_role_policy.bridge[0]
  to   = aws_iam_role_policy.web[0]
}
moved {
  from = aws_lambda_function.bridge[0]
  to   = aws_lambda_function.web[0]
}

resource "aws_cloudwatch_log_group" "web" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name              = "/aws/lambda/${local.web_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "web" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name = "${local.web_name}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "web" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name = "invoke_agent_and_logs"
  role = aws_iam_role.web[0].id
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
        Action   = ["bedrock-agentcore:GetAgentRuntime"]
        Resource = one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn)
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.web[0].arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "web" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  function_name    = local.web_name
  description      = "Next.js and CopilotKit on Lambda Web Adapter"
  role             = aws_iam_role.web[0].arn
  runtime          = "nodejs26.x"
  architectures    = ["arm64"]
  handler          = "run.sh"
  filename         = local.web_zip
  source_code_hash = fileexists(local.web_zip) ? filebase64sha256(local.web_zip) : null
  layers           = ["arn:aws:lambda:ap-northeast-1:753240598075:layer:LambdaAdapterLayerArm64:30"] # Web Adapter 1.1.0
  memory_size      = 512
  timeout          = 330

  environment {
    variables = {
      AGENT_RUNTIME_ARN                      = one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn)
      APP_ORIGIN                             = "https://${aws_api_gateway_rest_api.agent[0].id}.execute-api.ap-northeast-1.amazonaws.com"
      MCP_APPS_SANDBOX_URL                   = local.sandbox_url
      AWS_LAMBDA_EXEC_WRAPPER                = "/opt/bootstrap"
      AWS_LWA_INVOKE_MODE                    = "response_stream"
      AWS_LWA_PORT                           = "8080"
      AWS_LWA_READINESS_CHECK_PATH           = "/api/health"
      AWS_LWA_READINESS_CHECK_HEALTHY_STATUS = "200"
      PORT                                   = "8080"
      HOSTNAME                               = "0.0.0.0"
      NEXT_TELEMETRY_DISABLED                = "1"
      COPILOTKIT_TELEMETRY_DISABLED          = "true"
      DO_NOT_TRACK                           = "1"
      RUST_LOG                               = "warn"
    }
  }

  lifecycle {
    precondition {
      condition     = fileexists(local.web_zip)
      error_message = "app/Dockerfile.lambdaでLinux ARM64用のapp/dist/web.zipをビルドしてください。"
    }
  }

  depends_on = [aws_iam_role_policy.web]
}

resource "aws_api_gateway_rest_api" "agent" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  name        = local.web_name
  description = "IP-restricted Next.js on Lambda Web Adapter with response streaming"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_rest_api_policy" "web" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.agent[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Deny"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "${aws_api_gateway_rest_api.agent[0].execution_arn}/*"
        Condition = { NotIpAddress = { "aws:SourceIp" = var.allowed_source_cidrs } }
      },
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "${aws_api_gateway_rest_api.agent[0].execution_arn}/*"
      }
    ]
  })

  lifecycle {
    precondition {
      condition     = length(var.allowed_source_cidrs) > 0
      error_message = "ブラウザ検証にはallowed_source_cidrsでアクセス元IPを指定してください。無制限には公開しません。"
    }
  }
}

resource "aws_api_gateway_resource" "proxy" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.agent[0].id
  parent_id   = aws_api_gateway_rest_api.agent[0].root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "web" {
  for_each = length(aws_bedrockagentcore_agent_runtime.agent) > 0 ? {
    root  = aws_api_gateway_rest_api.agent[0].root_resource_id
    proxy = aws_api_gateway_resource.proxy[0].id
  } : {}

  rest_api_id   = aws_api_gateway_rest_api.agent[0].id
  resource_id   = each.value
  http_method   = "ANY"
  authorization = "NONE" # Access is restricted by the REST API resource policy above.
}

resource "aws_api_gateway_integration" "web" {
  for_each = aws_api_gateway_method.web

  rest_api_id             = aws_api_gateway_rest_api.agent[0].id
  resource_id             = each.value.resource_id
  http_method             = each.value.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:${local.partition}:apigateway:ap-northeast-1:lambda:path/2021-11-15/functions/${aws_lambda_function.web[0].arn}/response-streaming-invocations"
  response_transfer_mode  = "STREAM"
  timeout_milliseconds    = 335000
}

resource "aws_lambda_permission" "api_gateway" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  statement_id_prefix = "AllowApiGatewayWeb-"
  action              = "lambda:InvokeFunction"
  function_name       = aws_lambda_function.web[0].function_name
  principal           = "apigateway.amazonaws.com"
  source_account      = local.account_id
  source_arn          = "${aws_api_gateway_rest_api.agent[0].execution_arn}/poc/*/*"
}

resource "aws_api_gateway_deployment" "agent" {
  count = length(aws_bedrockagentcore_agent_runtime.agent)

  rest_api_id = aws_api_gateway_rest_api.agent[0].id
  triggers = {
    redeployment = sha256(jsonencode({
      routes = { for k, v in aws_api_gateway_integration.web : k => {
        resource      = v.resource_id
        method        = v.http_method
        authorization = aws_api_gateway_method.web[k].authorization
        uri           = v.uri
        mode          = v.response_transfer_mode
        timeout       = v.timeout_milliseconds
      } }
      policy = aws_api_gateway_rest_api_policy.web[0].policy
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
    throttling_burst_limit = 30
    throttling_rate_limit  = 10
    caching_enabled        = false
    data_trace_enabled     = false
    logging_level          = "OFF"
    metrics_enabled        = false
  }
}
