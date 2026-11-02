# Terraform

東京リージョン（`ap-northeast-1`）のECR・IAM実行ロール・AgentCore Runtime V2を定義する。
Terraform本体はルートの `.terraform-version` と `versions.tf` で1.9.7に固定する。
AWS providerは6.71.0に固定し、`.terraform.lock.hcl` をコミットする。
AWS認証は標準の認証情報チェーンを使用する。account ID変数は不要。

RuntimeはAG-UIとIAM認証を使う。コンテナはfixture専用で、さくらAPI・API Gateway・Lambda中継は含まない。
`network_mode = "PUBLIC"` はIAM認証を無効にする設定ではない。

## ローカル検証

リポジトリ直下で実行する。`test` はmock providerを使い、AWSへ接続しない。

```sh
export CHECKPOINT_DISABLE=1
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform test
```

## 配備

`apply` とECRへのpushはAWSリソース・保存料金に関わる操作。実行前にplanを確認する。
stateはローカルに保存し、Gitへ含めない。

最初はイメージダイジェスト未指定で、ECRとIAMだけを作成する。

```sh
terraform -chdir=terraform plan -out=bootstrap.tfplan
terraform -chdir=terraform apply bootstrap.tfplan
```

ARM64イメージをビルドしてECRへpushする。

```sh
AGENT_REPO="$(terraform -chdir=terraform output -raw agent_repository_url)"
AGENT_TAG="$(git rev-parse --short HEAD)"
aws ecr get-login-password --region ap-northeast-1 | docker login --username AWS --password-stdin "${AGENT_REPO%%/*}"
docker build --platform linux/arm64 -t "$AGENT_REPO:$AGENT_TAG" agent
docker push "$AGENT_REPO:$AGENT_TAG"
```

pushしたイメージのダイジェストを取得する。

```sh
aws ecr describe-images --region ap-northeast-1 --repository-name agent-mcp-apps/agent --image-ids imageTag="$AGENT_TAG" --query 'imageDetails[0].imageDigest' --output text
```

取得した値を `terraform/terraform.tfvars` の `agent_image_digest` に保存し、Runtimeを作成する。
タグではなく `sha256:...` を指定する。tfvarsはGitへ含めない。

```sh
terraform -chdir=terraform plan -out=runtime.tfplan
terraform -chdir=terraform apply runtime.tfplan
terraform -chdir=terraform output -raw agent_runtime_arn
```

V2の初期化完了とスナップショット復元、実際のIAM呼び出しはAWS上で検証する必要がある。
Runtimeの誤削除を防ぐため `prevent_destroy` を設定している。削除時は明示的に解除してplanを確認する。
ECRもイメージを残したまま強制削除しない。
