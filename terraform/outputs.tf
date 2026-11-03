output "mcp_repository_url" {
  description = "MCP用ARM64イメージのpush先。"
  value       = aws_ecr_repository.mcp.repository_url
}

output "mcp_runtime_arn" {
  description = "IAM認証で接続するMCP Runtime ARN。イメージ未指定時はnull。"
  value       = one(aws_bedrockagentcore_agent_runtime.mcp[*].agent_runtime_arn)
}

output "agent_repository_url" {
  description = "AgentCore用ARM64イメージのpush先。"
  value       = aws_ecr_repository.agent.repository_url
}

output "agent_runtime_arn" {
  description = "IAM認証で呼び出すAgentCore Runtime ARN。イメージ未指定時はnull。"
  value       = one(aws_bedrockagentcore_agent_runtime.agent[*].agent_runtime_arn)
}

output "web_url" {
  description = "アクセス元IPを制限したNext.jsのブラウザURL。イメージ未指定時はnull。"
  value       = length(aws_bedrockagentcore_agent_runtime.agent) > 0 ? "${aws_api_gateway_stage.agent[0].invoke_url}/" : null
}

output "mcp_apps_sandbox_url" {
  description = "チャットとは別オリジン・同じIP制限のMCP Apps sandbox URL。Lambdaへ自動設定する。"
  value       = local.sandbox_url
}
