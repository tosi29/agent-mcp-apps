variable "mcp_image_digest" {
  description = "ECRへpushしたARM64 MCPイメージのsha256ダイジェスト。未指定ならMCP用ECRとIAMのみ作成する。"
  type        = string
  default     = null

  validation {
    condition     = var.mcp_image_digest == null ? true : can(regex("^sha256:[0-9a-f]{64}$", var.mcp_image_digest))
    error_message = "mcp_image_digestはsha256:に続く64桁の小文字16進数で指定してください。"
  }
}

variable "agent_image_digest" {
  description = "ECRにpushしたARM64エージェントイメージのsha256ダイジェスト。未指定ならECRとIAMだけを作成する。"
  type        = string
  default     = null

  validation {
    condition     = var.agent_image_digest == null ? true : can(regex("^sha256:[0-9a-f]{64}$", var.agent_image_digest))
    error_message = "agent_image_digestはsha256:に続く64桁の小文字16進数で指定してください。"
  }
}

variable "sakura_api_key_parameter_name" {
  description = "事前作成したさくらAPIキーのSecureStringパラメータ名。値はTerraformで取得・管理しない。未指定ならfixture。"
  type        = string
  default     = null

  validation {
    condition     = var.sakura_api_key_parameter_name == null ? true : can(regex("^/?[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$", var.sakura_api_key_parameter_name))
    error_message = "SSMパラメータ名を指定してください。ARN、ワイルドカード、空文字は使えません。"
  }
}

variable "sakura_model_id" {
  description = "さくらAI Engineで使用するモデルID。APIキーのパラメータ名と併せて指定する。"
  type        = string
  default     = null

  validation {
    condition     = var.sakura_model_id == null ? true : length(trimspace(var.sakura_model_id)) > 0 && var.sakura_model_id == trimspace(var.sakura_model_id)
    error_message = "sakura_model_idには空白を含まない有効なモデルIDを指定してください。"
  }
}

variable "tavily_api_key_parameter_name" {
  description = "事前作成したTavily APIキーのSecureStringパラメータ名。値はTerraformで取得・管理しない。"
  type        = string
  default     = "/agent-mcp-apps/tavily-api-key"

  validation {
    condition     = can(regex("^/?[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$", var.tavily_api_key_parameter_name))
    error_message = "SSMパラメータ名を指定してください。ARN、ワイルドカード、空文字は使えません。"
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
