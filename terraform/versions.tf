terraform {
  required_version = "= 1.16.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.71.0"
    }
  }

  backend "s3" {
    bucket       = "agent-mcp-apps-tfstate-33415a34"
    key          = "agent-mcp-apps/terraform.tfstate"
    region       = "ap-northeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
