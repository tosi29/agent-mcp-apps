output "agent_repository_url" {
  description = "AgentCore用ARM64イメージのpush先。"
  value       = aws_ecr_repository.agent.repository_url
}

output "agent_runtime_arn" {
  description = "IAM認証で呼び出すAgentCore Runtime ARN。イメージ未指定時はnull。"
  value       = one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn)
}
