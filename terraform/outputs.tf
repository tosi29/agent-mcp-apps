output "agent_repository_url" {
  description = "AgentCore用ARM64イメージのpush先。"
  value       = aws_ecr_repository.agent.repository_url
}

output "agent_runtime_arn" {
  description = "IAM認証で呼び出すAgentCore Runtime ARN。イメージ未指定時はnull。"
  value       = one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn)
}

output "agent_invocations_url" {
  description = "AWS_IAM認証のAG-UI SSEエンドポイント。イメージ未指定時はnull。"
  value       = length(aws_bedrockagentcore_agent_runtime.agent) > 0 ? "${aws_api_gateway_stage.agent[0].invoke_url}/invocations" : null
}

output "agent_api_invoke_arn" {
  description = "呼び出し元IAMにexecute-api:Invokeを許可する対象。イメージ未指定時はnull。"
  value       = length(aws_bedrockagentcore_agent_runtime.agent) > 0 ? "${aws_api_gateway_rest_api.agent[0].execution_arn}/poc/POST/invocations" : null
}
