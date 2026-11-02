variable "agent_image_digest" {
  description = "ECRにpushしたARM64エージェントイメージのsha256ダイジェスト。未指定ならECRとIAMだけを作成する。"
  type        = string
  default     = null

  validation {
    condition     = var.agent_image_digest == null ? true : can(regex("^sha256:[0-9a-f]{64}$", var.agent_image_digest))
    error_message = "agent_image_digestはsha256:に続く64桁の小文字16進数で指定してください。"
  }
}

variable "allowed_source_cidrs" {
  description = "ブラウザ検証を許可する送信元CIDR。terraform.tfvarsで利用端末のグローバルIPv4/32等を指定する。"
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for cidr in var.allowed_source_cidrs :
      can(cidrhost(cidr, 0)) && !can(regex("/0+$", cidr))
    ])
    error_message = "allowed_source_cidrsには有効なCIDRを指定してください。全インターネットを許可する/0は使えません。"
  }
}
