# Terraform

東京リージョン（`ap-northeast-1`）に、ブラウザから使うNext.jsと探索エージェントを配置する。

```text
Browser → API Gateway Regional REST API /poc/（送信元IP制限）
  → Lambda Node.js 26 / ARM64 ZIP
    → Web Adapter → Next.js / CopilotKit Runtime
      → AgentCore Runtime V2 / AG-UI → Strands
          └─ IAM SigV4 → MCP用AgentCore Runtime V2 → DuckDB / Parquet
```

Terraformは1.9.7、AWS providerは6.71.0に固定する。Web Adapterは1.1.0の公式ARM64 Layer（version 30）を使う。
AWS認証は標準の認証情報チェーンを使用し、account ID変数は設けない。
AgentCoreは既定でfixture。Parameter Storeのキー参照とモデルIDを指定した場合にさくらAPIを使用する。
Lambdaの実行ロールでAgentCoreを呼び、ブラウザにAWS認証情報は渡さない。

既存の中継LambdaはNext.jsを起動するLambdaへ更新する。`moved` ブロックでTerraform上のアドレスを移し、
既存の関数・実行ロール・ロググループ名は維持する。

## ビルド

Docker、Node.js、npm、Python 3.12、uv、Terraformを用意する。
Next.jsのZIPはLinux ARM64で作り、Macの `node_modules` は使わない。リポジトリ直下で実行する。

```sh
npm --prefix app run build:lambda
```

Amazon Linux 2023と、ルートの `.node-version` から読み取ったNode.js 26の固定版でビルドする。
成果物は `app/dist/web.zip`。Next.jsのstandaloneサーバー、必要な依存、静的ファイル、起動スクリプトを含む。
`.env` はDockerのコンテキストから除外し、ビルド中はAWS認証情報を渡さない。
ブラウザ向けURLの接頭辞 `/poc` はビルド時に設定する。
TerraformはビルドやECRへのpushを実行しない。LambdaはZIPのハッシュが変わった場合にコードを更新する。

## 初期セットアップ

最初はイメージダイジェスト未指定でエージェント・MCP用のECRとIAMだけを作る。
`apply` とECRへのpushは、実行前に対象とplanを確認する。

```sh
export CHECKPOINT_DISABLE=1
terraform -chdir=terraform init
terraform -chdir=terraform plan -out=bootstrap.tfplan
terraform -chdir=terraform apply bootstrap.tfplan
```

ECR作成後、エージェント・MCPのARM64イメージをビルドしてpushする。
リポジトリ直下から、共通のスクリプトを実行する。

```sh
node scripts/push-images.mjs all
```

片方だけ更新する場合は `all` を `agent` または `mcp` に置き換える。
AWS CLIの認証情報は標準チェーンを使い、push先はTerraformのoutputから取得する。
タグはGitコミットIDと実行時刻から作り、IMMUTABLEの同一タグを再利用しない。

ダイジェスト取得後、Git管理外の `terraform/images.auto.tfvars.json` を自動更新する。
標準出力にpush先・各ダイジェスト・JSONの更新先と内容を表示する。
片方だけ指定した場合は、JSON内のもう片方の値を保持する。同時に複数プロセスで実行しない。
指定した全対象が成功した時だけJSONを更新する。途中で失敗した場合はJSONを保持し、push済みのイメージはECRに残る。
スクリプトはplan・applyを実行しない。

## 設定とapply

Git除外対象の `terraform/terraform.tfvars` に、ブラウザを使う端末の送信元CIDR等を設定する。
イメージのダイジェストはスクリプトが生成した `images.auto.tfvars.json` から自動で読み込まれる。
既存の `terraform.tfvars` にもダイジェストがある場合は、自動生成ファイル側が優先される。
初回の `all` 実行成功後、重複する `agent_image_digest`・`mcp_image_digest` は `terraform.tfvars` から削除してよい。
自動生成ファイルを削除すると配備対象が変わるため、既存Runtimeの値を保持する。

```hcl
allowed_source_cidrs = ["自分のグローバルIPv4/32"]
```

グローバルIPv4は `curl -4 https://checkip.amazonaws.com` 等で確認する。
VPNやネットワークの変更でIPが変わるとアクセスできなくなる。共有NAT内の他の端末も同じIPになる。
CIDRが空、全インターネットを許可する `/0`、ZIPが未作成の場合は配備を拒否する。

```sh
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform plan -out=web.tfplan
terraform -chdir=terraform apply web.tfplan
terraform -chdir=terraform output -raw web_url
```

`web_url` の末尾 `/poc/` まで含むURLをブラウザで開く。画面から質問を送ると設定したモードで実行する。
state、tfvars、plan、ZIP、実行結果はGitに含めない。

## MCPの配備

探索・比較4ツールとMCP Appsツールを持つMCPを、エージェントと別のECR・実行ロール・AgentCore Runtime V2に配置する。
ParquetはMCPイメージのビルド時に生成し、エージェントには含めない。
プロトコルは `MCP`、認証はIAM SigV4。CognitoやOAuthのリソースは追加しない。
`mcp_image_digest` 未指定ならMCP用ECRとIAMのみ作成し、RuntimeやエージェントのMCP接続設定は作らない。

1. `mcp_image_digest` を省略したplanを確認し、MCP用ECRとIAMを作成する。
2. `mcp/` と `agent/` の両方のARM64イメージをビルドし、それぞれのECRへpushする。
3. スクリプトが `images.auto.tfvars.json` へ両方のダイジェストを書き込んだことを確認する。
4. planでMCP Runtimeの追加、エージェントのイメージ・環境変数・呼び出し権限の更新を確認してapplyする。

MCPとエージェントをまとめて更新する場合は、リポジトリ直下で実行する。
ECRへのpushとapplyは事前に確認する。

```sh
node scripts/push-images.mjs all
```

MCPだけを更新する場合は `node scripts/push-images.mjs mcp` を使う。
古いエージェントイメージのままでは `MCP_RUNTIME_ARN` を設定しても接続しない。
Terraform自身はビルド・pushを実行しない。

Terraformがエージェントに `MCP_RUNTIME_ARN` を渡し、その実行ロールへ対象RuntimeとDEFAULTエンドポイントの
`bedrock-agentcore:InvokeAgentRuntime` のみを追加する。MCP側のロールにはMCPイメージとログへの権限だけを付ける。
MCP Runtimeは `prevent_destroy` のため、作成後にダイジェストをnullへ戻して削除する操作は拒否される。

`mcp_runtime_arn` を使った接続確認は [MCPのREADME](../mcp/README.md#agentcoreへの配備)を参照。
ローカルのfixtureで接続すればモデルAPIは呼ばないが、AgentCoreの利用料金は発生し得る。
AWS上のIAM認可とV2復元後の動作は配備後に検証する。
MCP AppsのHTMLはMCPイメージに含むが、ブラウザ用の別オリジンsandbox配備はこのTerraformに含めない。
公開環境でのApps表示には、sandboxの配置とNext.jsのビルド時URL設定が別途必要。

## さくらのAPIキーを指定する

利用者がParameter Storeにパラメータを事前作成する。リージョンは東京、タイプは `SecureString`、
値はAPIキーそのものを指定する。標準パラメータと既定の暗号鍵 `alias/aws/ssm` を前提とする。
カスタマー管理KMSキーを使う場合は、対象キーへの復号権限を別途設計する。
パラメータ本体・値の登録はTerraformの管理対象にせず、値をstateへ取り込むデータソースも設けない。

`terraform.tfvars` には名前とモデルIDを設定する。

```hcl
sakura_api_key_parameter_name = "/agent-mcp-apps/sakura-api-key"
sakura_model_id               = "preview/Kimi-K2.7-Code"
```

モデルIDは設定例。使用するAPIキーの契約・モデルの利用可否・無償枠の残りを利用者が確認する。
名前とモデルIDを両方省略すればfixture、両方指定すればさくらとなる。
AgentCoreの実行ロールには、そのパラメータ1つの `ssm:GetParameter` だけを付与する。
起動・ページ表示ではキーを取得せず、AgentCoreが各runで復号取得する。Next.jsはキーを受け取らない。

SSM対応の新しいエージェントイメージを `node scripts/push-images.mjs agent` でpushしてから切り替える。
旧fixture専用イメージのまま設定だけを変更しない。Next.jsの接続モード表示も更新するため、Web用ZIPも再ビルド・配備する。
push・apply・実API検証は実行前に確認する。SSMの実権限とさくらの応答は、デプロイ後の検証が必要。

## 動作確認

ローカルの起動と型チェックは [app/README.md](../app/README.md) を参照する。
配備後のHTTP確認は、許可した送信元IPから実行する。以下はリポジトリ直下からのコマンド。

```sh
WEB_URL="$(terraform -chdir=terraform output -raw web_url)"
cd app
SMOKE_URL="$WEB_URL" npm run smoke
```

画面・静的ファイル・SSE・独立した結果イベント・合成データの期待値・正常終了を検査する。
ブラウザの描画確認は別途必要。Lambda、API Gateway、AgentCoreの利用料金は発生し得る。

## 制約

- `/` と `/{proxy+}` を同じLambdaへ中継し、画面・静的ファイル・チャットAPIを同じOriginで配信する。
- APIのリソースポリシーで指定CIDR以外を明示的に拒否する。OIDCとユーザー単位の認証は未実装。
- API Gatewayの `STREAM` とWeb Adapterの `response_stream` を併用し、Next.jsの圧縮は無効にする。
- AgentCore呼び出しは自動再試行せず、runごとに新しいセッションを使う。会話はAG-UIメッセージで渡す。
- 接続状態は `GetAgentRuntime` のREADY状態、モードは同APIの環境設定から判定する。推論品質やAPIキーの有効性を示すものではない。
- 入力は128KiB、Python側で40メッセージまで。上流SSEは2MiB・1フレーム256K文字まで。
- AgentCoreへの通信は130秒、Lambdaは150秒、API Gatewayは155秒で制限する。上流の異常終了は `RUN_ERROR` にする。
- APIは毎秒10件・バースト30件でスロットリングする。静的ファイル取得も対象で、費用の厳密な上限ではない。
- リクエスト本文のトレースは無効。質問・結果・認証ヘッダーをアプリログへ記録しない。Lambdaログは7日保持。
- ブラウザの切断がLambdaへ通知されることや、AgentCore内の実行・課金が即時停止することは保証しない。
- 会話履歴はLambdaプロセスのメモリ内。再起動や別の実行環境への振り分けで保持されない。結果ファイルもRuntimeの一時領域で、別取得・永続化は未実装。
- Runtimeは `prevent_destroy` を設定し、ECRもイメージを残したまま強制削除しない。

仕様：[Web Adapter ZIP構成](https://aws.github.io/aws-lambda-web-adapter/getting-started/zip-packages.html)、
[API GatewayのLambdaストリーミング統合](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode-lambda.html)。
