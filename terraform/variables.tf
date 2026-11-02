variable "agent_image_digest" {
  description = "ECRにpushしたARM64エージェントイメージのsha256ダイジェスト。未指定ならECRとIAMだけを作成する。"
  type        = string
  default     = null

  validation {
    condition     = var.agent_image_digest == null ? true : can(regex("^sha256:[0-9a-f]{64}$", var.agent_image_digest))
    error_message = "agent_image_digestはsha256:に続く64桁の小文字16進数で指定してください。"
  }
}
