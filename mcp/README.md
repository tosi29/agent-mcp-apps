# MCPツール

独立したPython・uvプロジェクト。公式MCP Python SDKで `compare_values` を公開する。
既存のDuckDBツールは `agent/` に残し、このサーバーでは数値の比較だけを行う。

## 起動

以下の `cd` はリポジトリ直下を起点にする。

```sh
cd mcp
uv sync --locked
uv run --locked explore-mcp
```

接続先は `http://127.0.0.1:8001/mcp`。Streamable HTTPを使い、各リクエストには単一のJSONで応答する。
SSEの購読や永続セッションは使わない。ポートは `--port` で変更できる。
APIキーは不要で、外部API・LLM・データベースには接続しない。
このコマンドはループバック限定・認証なしのローカル検証用。

## ツール

`compare_values(baseline, current)` に同じ単位の数値を渡す。

| 戻り値 | 意味 |
| --- | --- |
| `baseline` / `current` | 入力した基準値と比較値 |
| `difference` | 比較値 − 基準値 |
| `percent_change` | `(比較値 − 基準値) / 基準値 × 100`。小数点以下6桁 |

基準値が0の場合、増減率は `null`。非有限値や計算結果のオーバーフローはツールエラーにする。
数値は入力値をそのまま使い、単位の推定や変換は行わない。

## エージェントと接続する

MCPサーバーとは別のターミナルで起動する。

```sh
cd agent
uv sync --locked
uv run --locked explore-server --model fixture --mcp-url http://127.0.0.1:8001/mcp
```

さらに `app/` で `npm run dev` を実行し、<http://127.0.0.1:3000> を開く。
fixtureは質問内容にかかわらず、既存の項目確認・年別集計と、MCPによる平均取引総額の比較を実行する。
右側に既存の集計表とMCPの比較結果が別々に追加される。推論APIは呼ばない。
MCP接続先を指定しないエージェントはMCPに接続しない。

さくらを使う場合は `--model fixture` を外し、`uv run --locked --env-file .env explore-server --mcp-url ...` で起動する。
実際の質問送信は推論APIを呼ぶ。

## AgentCoreへの配備

`Dockerfile` はAgentCore向けのARM64コンテナを作る。専用のエントリーポイントは
`0.0.0.0:8000/mcp` と `GET /ping` を提供する。ローカル起動の設定とは分けている。

```sh
# リポジトリ直下で実行
docker build --platform linux/arm64 -t agent-mcp-apps-mcp:local mcp
docker run --rm -p 127.0.0.1:18001:8000 agent-mcp-apps-mcp:local
```

このローカル起動ではAgentCoreのIAM認証は付かないため、ポート公開はループバック限定にする。
クラウドではAgentCoreがIAM認証を行う。内部Hostを受け入れる専用設定でも、Origin付きのブラウザ直接アクセスは拒否する。
プラットフォームの `Mcp-Session-Id` を受け入れ、ツール処理自体はstatelessのJSON応答を維持する。
外部APIや認証情報は起動時に取得せず、`/ping` でもツールを実行しない。

[TerraformのMCP配備手順](../terraform/README.md#mcpの配備)に従い、MCP用ECR・IAM・Runtime V2を作る。
イメージはダイジェストで指定し、既存エージェントもMCP接続対応版へ更新する。
ECRへのpush、apply、AgentCoreの実呼び出しは料金が発生し得るため、対象を確認してから行う。

配備後、AWS認証情報の標準チェーンが使える端末から、ローカルのfixtureエージェントで接続を確認できる。

```sh
cd agent
uv run --locked explore-server --model fixture --mcp-runtime-arn '東京リージョンのMCP Runtime ARN'
```

これはモデルAPIを呼ばないが、MCP用AgentCoreには接続する。
`--mcp-url` と `--mcp-runtime-arn` は同時に指定できない。
AWS上のエージェントでは、Terraformが `MCP_RUNTIME_ARN` を設定する。
呼び出し側の実行ロールに対象MCP Runtimeの `bedrock-agentcore:InvokeAgentRuntime` を付与する。

IAM署名は各HTTPリクエストで生成し、一時認証情報も都度取得する。
接続ごとに新しいセッションIDを使い、AgentCoreから返る `Mcp-Session-Id` を後続リクエストへ引き継ぐ。
署名先はARNから組み立てた東京のエンドポイントに固定し、HTTPリダイレクトを追跡しない。

ローカルテストはコンテナ起動と模擬AWS入口での署名・ツール実行を確認する。
実際のIAM認可、V2復元後の動作、クラウドの遅延は、配備後に別途確認が必要。

仕様：[AgentCore MCP契約](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.html)、
[IAM認証](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)。

## テスト

`mcp/` で実行する。

```sh
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

HTTPテストはJSON応答・入力エラー・Host/Origin制約を確認する。
Strandsとの実HTTP接続・AG-UI結果イベント・モデル履歴との分離は `agent/` の `uv run --locked pytest -q` で確認する。
