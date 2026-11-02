mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }
}

run "bootstrap_without_runtime" {
  command = plan

  assert {
    condition     = length(aws_bedrockagentcore_agent_runtime.agent) == 0 && output.agent_runtime_arn == null
    error_message = "イメージ未指定のbootstrapでRuntimeを作成してはいけません。"
  }

  assert {
    condition     = aws_ecr_repository.agent.image_tag_mutability == "IMMUTABLE" && !aws_ecr_repository.agent.force_delete
    error_message = "ECRのタグ上書きやイメージの強制削除を有効にしてはいけません。"
  }

  assert {
    condition     = jsondecode(aws_iam_role.agent.assume_role_policy).Statement[0].Condition.StringEquals["aws:SourceAccount"] == "123456789012"
    error_message = "実行ロールの引受元を現在のアカウントに制限する必要があります。"
  }
}

run "v2_agui_runtime" {
  command = plan

  variables {
    agent_image_digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }

  assert {
    condition     = length(aws_bedrockagentcore_agent_runtime.agent) == 1 && aws_bedrockagentcore_agent_runtime.agent[0].platform_version == "V2"
    error_message = "AgentCore Runtime V2を明示する必要があります。"
  }

  assert {
    condition     = aws_bedrockagentcore_agent_runtime.agent[0].protocol_configuration[0].server_protocol == "AGUI" && length(aws_bedrockagentcore_agent_runtime.agent[0].authorizer_configuration) == 0
    error_message = "初期構成はAG-UIと既定のIAM認証を使用します。"
  }
}

run "reject_mutable_image_tag" {
  command = plan

  variables {
    agent_image_digest = "latest"
  }

  expect_failures = [var.agent_image_digest]
}
