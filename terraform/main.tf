data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  agent_name = "agent_mcp_apps_poc"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  logs_arn   = "arn:${local.partition}:logs:ap-northeast-1:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${local.agent_name}-*"
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
      }
    ]
  })
}

resource "aws_bedrockagentcore_agent_runtime" "agent" {
  count = var.agent_image_digest == null ? 0 : 1

  agent_runtime_name = local.agent_name
  description        = "Strands and DuckDB AG-UI fixture PoC"
  role_arn           = aws_iam_role.agent.arn
  platform_version   = "V2"

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
  }

  depends_on = [aws_iam_role_policy.agent]
}
