locals {
  mcp_name     = "agent_mcp_apps_comparison"
  mcp_logs_arn = "arn:${local.partition}:logs:ap-northeast-1:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${local.mcp_name}-*"
}

resource "aws_ecr_repository" "mcp" {
  name                 = "agent-mcp-apps/mcp"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_iam_role" "mcp" {
  name = "${local.mcp_name}_runtime"
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

resource "aws_iam_role_policy" "mcp" {
  name = "runtime_image_and_logs"
  role = aws_iam_role.mcp.id
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
        Resource = aws_ecr_repository.mcp.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups"]
        Resource = "arn:${local.partition}:logs:ap-northeast-1:${local.account_id}:log-group:*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:DescribeLogStreams", "logs:PutResourcePolicy"]
        Resource = local.mcp_logs_arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${local.mcp_logs_arn}:log-stream:*"
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

resource "aws_bedrockagentcore_agent_runtime" "mcp" {
  count = var.mcp_image_digest == null ? 0 : 1

  agent_runtime_name = local.mcp_name
  description        = "IAM-protected MCP numerical comparison tools"
  role_arn           = aws_iam_role.mcp.arn
  platform_version   = "V2"
  environment_variables = merge(local.runtime_observability, {
    OTEL_SERVICE_NAME = local.mcp_name
  })

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.mcp.repository_url}@${var.mcp_image_digest}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  # No JWT authorizer: AgentCore requires IAM SigV4 for inbound requests.
  protocol_configuration {
    server_protocol = "MCP"
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [aws_iam_role_policy.mcp]
}

resource "aws_iam_role_policy" "agent_mcp" {
  count = var.mcp_image_digest == null ? 0 : 1

  name = "invoke_comparison_mcp"
  role = aws_iam_role.agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock-agentcore:InvokeAgentRuntime"]
      Resource = [
        aws_bedrockagentcore_agent_runtime.mcp[0].agent_runtime_arn,
        "${aws_bedrockagentcore_agent_runtime.mcp[0].agent_runtime_arn}/runtime-endpoint/DEFAULT"
      ]
    }]
  })
}
