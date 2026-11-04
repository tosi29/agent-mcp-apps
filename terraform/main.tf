data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  agent_name     = "agent_mcp_apps_poc"
  account_id     = data.aws_caller_identity.current.account_id
  partition      = data.aws_partition.current.partition
  logs_arn       = "arn:${local.partition}:logs:ap-northeast-1:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${local.agent_name}-*"
  sakura_enabled = var.sakura_api_key_parameter_name != null
  runtime_observability = {
    AGENT_OBSERVABILITY_ENABLED                        = "true"
    OTEL_PYTHON_DISTRO                                 = "aws_distro"
    OTEL_PYTHON_CONFIGURATOR                           = "aws_configurator"
    OTEL_TRACES_EXPORTER                               = "otlp"
    OTEL_LOGS_EXPORTER                                 = "otlp"
    OTEL_METRICS_EXPORTER                              = "awsemf"
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT = "true"
    UNIFIED_TRACES_DESTINATION_ENABLED                 = "true"
  }
}

resource "aws_ecr_repository" "agent" {
  name                 = "agent-mcp-apps/agent"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_iam_role" "agent" {
  name = "${local.agent_name}_runtime"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:bedrock-agentcore:ap-northeast-1:${local.account_id}:*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "agent" {
  name = "runtime_image_and_logs"
  role = aws_iam_role.agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = aws_ecr_repository.agent.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups"]
        Resource = "arn:${local.partition}:logs:ap-northeast-1:${local.account_id}:log-group:*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:DescribeLogStreams", "logs:PutResourcePolicy"]
        Resource = local.logs_arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${local.logs_arn}:log-stream:*"
      },
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments", "xray:PutTelemetryRecords",
          "xray:GetSamplingRules", "xray:GetSamplingTargets"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = { "cloudwatch:namespace" = "bedrock-agentcore" }
        }
      }
    ]
  })
}

resource "aws_bedrockagentcore_agent_runtime" "agent" {
  count = var.agent_image_digest == null ? 0 : 1

  agent_runtime_name = local.agent_name
  description        = "Strands and DuckDB AG-UI exploration PoC"
  role_arn           = aws_iam_role.agent.arn
  platform_version   = "V2"
  environment_variables = merge(
    local.runtime_observability,
    {
      EXPLORER_MODEL_MODE = local.sakura_enabled ? "sakura" : "fixture"
      OTEL_SERVICE_NAME   = local.agent_name

      TAVILY_API_KEY_PARAMETER_NAME = var.tavily_api_key_parameter_name
    },
    local.sakura_enabled ? {
      SAKURA_API_KEY_PARAMETER_NAME = var.sakura_api_key_parameter_name
      SAKURA_MODEL_ID               = var.sakura_model_id == null ? "" : var.sakura_model_id
    } : {},
    var.mcp_image_digest != null ? {
      MCP_RUNTIME_ARN = aws_bedrockagentcore_agent_runtime.mcp[0].agent_runtime_arn
    } : {}
  )

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}@${var.agent_image_digest}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "AGUI"
  }

  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = local.sakura_enabled == (var.sakura_model_id != null)
      error_message = "さくら接続はsakura_api_key_parameter_nameとsakura_model_idを両方指定してください。"
    }
  }

  depends_on = [aws_iam_role_policy.agent, aws_iam_role_policy.sakura_parameter, aws_iam_role_policy.tavily_parameter, aws_iam_role_policy.agent_mcp]
}

resource "aws_iam_role_policy" "tavily_parameter" {
  name = "read_tavily_api_key_parameter"
  role = aws_iam_role.agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = "arn:${local.partition}:ssm:ap-northeast-1:${local.account_id}:parameter/${trimprefix(var.tavily_api_key_parameter_name, "/")}"
    }]
  })
}

resource "aws_iam_role_policy" "sakura_parameter" {
  count = local.sakura_enabled ? 1 : 0

  name = "read_sakura_api_key_parameter"
  role = aws_iam_role.agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = "arn:${local.partition}:ssm:ap-northeast-1:${local.account_id}:parameter/${trimprefix(var.sakura_api_key_parameter_name, "/")}"
    }]
  })
}
