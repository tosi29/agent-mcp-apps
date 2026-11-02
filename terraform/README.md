# Terraform

東京リージョン（`ap-northeast-1`）のECR・IAM実行ロール・AgentCore Runtime V2・Lambda・API Gateway REST APIを定義する。
Terraform本体はルートの `.terraform-version` と `versions.tf` で1.9.7に固定する。
AWS providerは6.71.0に固定し、`.terraform.lock.hcl` をコミットする。
AWS認証は標準の認証情報チェーンを使用する。account ID変数は不要。

RuntimeはAG-UIとIAM認証を使う。コンテナはfixture専用で、さくらAPIは呼ばない。
`network_mode = "PUBLIC"` はIAM認証を無効にする設定ではない。

```text
署名付きHTTPクライアント
  → API Gateway Regional REST API /poc/invocations（AWS_IAM）
    → Lambda Node.js 26 / ARM64 ZIP（response streaming）
      → AgentCore Runtime V2 / AG-UI → Strands fixture → DuckDB
```

中継はサーバー間通信向けで、ブラウザ向けCORSや無認証のFunction URLは設定しない。
Next.jsの接続先はまだローカルPythonのまま。クラウド接続にはNext.js側でのSigV4署名が別途必要。

## ローカル検証

まずLambdaの依存を導入し、テストとZIPのビルドを行う。
Node.jsはルートの `.node-version` に合わせる。ビルドには `zip` コマンドも必要。

```sh
cd terraform/lambda
npm ci --ignore-scripts
npm test
npm run build
cd ../..
```

続いてリポジトリ直下で実行する。`test` はmock providerを使い、AWSへ接続しない。

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

取得した値を `terraform/terraform.tfvars` の `agent_image_digest` に保存する。
LambdaのZIPもビルドしたうえで、Runtime・Lambda・API Gatewayを作成する。
既にRuntimeを配備済みの場合は、同じダイジェストを維持して中継を追加する。
タグではなく `sha256:...` を指定する。tfvarsはGitへ含めない。

```sh
terraform -chdir=terraform plan -out=runtime.tfplan
terraform -chdir=terraform apply runtime.tfplan
terraform -chdir=terraform output -raw agent_runtime_arn
```

Terraformはビルド・ECRへのpushを実行しない。Lambdaも `npm run build` で作った
`lambda/dist/bridge.zip` をアップロードし、そのハッシュが変わった場合にコードを更新する。
AWS SDKもZIPへ同梱し、Lambda同梱SDKのバージョンには依存しない。

## 中継の動作確認

呼び出し元には、`agent_api_invoke_arn` 出力のARNに対する `execute-api:Invoke` 権限が必要。
既存ユーザー・ロールへの権限追加はこのTerraformでは行わない。
fixture用の検証コマンドを、リポジトリ直下から実行する。

```sh
uv run --project agent --locked python terraform/scripts/smoke_streaming.py
```

未署名リクエストが403で拒否されることを確認してから、SigV4署名付きで1回実行する。
イベントの到着時刻を標準出力へ表示し、逐次受信・ツール2回の成功・独立した結果イベント・
合成データの期待値・正常終了を検査する。署名・認証情報・会話本文は出力しない。
Lambda、API Gateway、AgentCoreの利用料金は発生し得る。さくらの推論APIは呼ばない。
この検証はHTTP経路が対象で、ブラウザ描画やLLMの回答品質は対象外。

## 中継の制約

- POST `/poc/invocations` のみ。入力は128KiB・40メッセージまで。AG-UIの詳細な入力検査はPython側で行う。
- 応答は2MiB、1つのSSEフレームは256K文字まで。結果の大量転送用APIではない。
- AgentCore呼び出しの自動再試行はしない。runごとに新しいRuntimeセッションを使い、会話はAG-UIメッセージで渡す。
- 中継は130秒で打ち切り、Lambdaは150秒、API Gatewayは155秒に設定する。途中終了や不正な終端は `RUN_ERROR` に変換する。
- 開始前の失敗はHTTPエラー、ストリーム開始後の失敗はAG-UIエラーとして返す。上流の例外詳細は返さない。
- CORSは許可せず、Origin付きのリクエストは拒否する。アクセスにはIAM認証が必要。
- APIのスロットリングは毎秒1件・バースト2件。厳密な同時実行数や費用の上限ではない。
- リクエスト本文のトレースは無効。Lambdaログの保持は7日。質問・ツール結果・認証ヘッダーをアプリログへ記録しない。
- 接続断をLambda側で観測できた場合は上流の通信を中断する。ただしAPI Gatewayでのクライアント切断がLambdaへ通知される保証や、AgentCore内の処理・課金停止の保証はない。
- 結果ファイルは各Runtimeの一時領域。別runからの取得・永続化は未対応。

設定とローカルテストだけでは、AWS上のストリーミングや認可の動作確認にはならない。
apply後に上記のHTTP検証を実行する。
Runtimeの誤削除を防ぐため `prevent_destroy` を設定している。削除時は明示的に解除してplanを確認する。
ECRもイメージを残したまま強制削除しない。

仕様：[API GatewayのLambdaストリーミング統合](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode-lambda.html)、
[Lambdaのストリーミング実装](https://docs.aws.amazon.com/lambda/latest/dg/config-rs-write-functions.html)、
[RuntimeとエンドポイントのIAM認可](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html)。
