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

# Saved tool results, shared by every MCP session so a later resources/read can find them.
# Only the MCP execution role reads or writes it; clients go through MCP, never to S3.
resource "aws_s3_bucket" "results" {
  bucket_prefix = "agent-mcp-apps-results-"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "results" {
  bucket                  = aws_s3_bucket.results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "results" {
  bucket = aws_s3_bucket.results.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "results" {
  bucket = aws_s3_bucket.results.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "results" {
  bucket = aws_s3_bucket.results.id
  rule {
    id     = "expire-results"
    status = "Enabled"
    filter {
      prefix = "results/"
    }
    expiration {
      days = var.results_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_policy" "results" {
  bucket = aws_s3_bucket.results.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.results.arn, "${aws_s3_bucket.results.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.results]
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
  name = "runtime_image_logs_and_results"
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
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.results.arn}/results/*"
      },
      {
        # Without it, S3 answers a missing key with AccessDenied instead of NoSuchKey.
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = aws_s3_bucket.results.arn
        Condition = { StringLike = { "s3:prefix" = "results/*" } }
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
    OTEL_SERVICE_NAME  = local.mcp_name
    MCP_RESULTS_BUCKET = aws_s3_bucket.results.id
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
