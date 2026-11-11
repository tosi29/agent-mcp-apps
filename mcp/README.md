# MCPツール

独立したPython・uvプロジェクト。公式MCP Python SDKで次の5ツールを公開する。

| ツール | 機能 |
| --- | --- |
| `describe_dataset` | データ項目・単位・地域候補・件数の確認 |
| `search_transactions` | 地域の完全一致・年・価格範囲で検索 |
| `aggregate_transactions` | 地域・年・四半期で件数・価格の平均／最小／最大を集計 |
| `compare_values` | 2数値の差分・増減率を計算 |
| `show_transaction_dashboard` | 集計結果をMCP Appsの棒グラフ・表で表示 |

DuckDB・Parquet・結果ファイルはこのプロジェクトが管理する。Strandsには依存しない。

## ローカル起動

以下の `cd` はリポジトリ直下を起点にする。

```sh
npm --prefix mcp/ui ci --ignore-scripts
npm --prefix mcp/ui run build
cd mcp
uv sync --locked
uv run --locked explore-mcp prepare-sample
uv run --locked explore-mcp
```

接続先は `http://127.0.0.1:8001/mcp`。Streamable HTTPを使い、各リクエストには単一のJSONで応答する。
SSEの購読や永続セッションは使わない。ポートは `--port` で変更できる。
APIキーとモデルAPIは不要。DuckDBで信頼済みのローカルParquetを検索する。
`prepare-sample` は360行の架空取引を `mcp/data/synthetic.parquet` に生成する。生成済みなら省略する。
地域は千代田区・新宿区・渋谷区、期間は2023〜2025年。価格・面積・時期は架空で、市場価格の判断に使えない。
`--data`／`MCP_DATA_PATH` はサーバー管理者が設定し、ツール引数にはパスを受け付けない。
このコマンドはループバック限定・認証なしのローカル検証用。

## MCP Apps

`show_transaction_dashboard` は `group_by`（地域・年・四半期）・`municipality`・`year` で集計する。
ツールの `_meta.ui.resourceUri` は `ui://exploration/transaction-dashboard-v1.html` を参照し、
`resources/read` で `text/html;profile=mcp-app` のHTMLを返す。公式Python SDKの `Apps` 拡張を使う。

`mcp/ui/` は公式Apps SDKを含む自己完結HTMLを生成する。成果物はGit管理外で、wheelには明示的に含める。
DockerビルドではNodeステージで生成し、Pythonイメージへコピーする。実行時にNodeや外部CDNは使わない。
画面では平均取引総額と取引件数を切り替えられる。追加のサーバー呼び出しは行わない。

モデル向けの `content`・`structuredContent` は最大3行の要約。画面用の最大20行は結果の `_meta.preview` に置く。
UI非対応クライアントでも同じテキスト要約を利用できる。通常の4ツールの戻り値は変更しない。
ホスト側のsandboxと起動方法は [appのREADME](../app/README.md#mcp-appsの表示) を参照。

## 検索と結果の制約

検索は `municipality / year / min_price_yen / max_price_yen` を使う。
列は `transaction_id / municipality / year / quarter / price_yen / area_m2`。
地域はNFKC正規化・前後空白除去後の完全一致。複数キーワード・部分一致モードは未実装。
集計単位は `municipality / year / quarter` の許可リストから選ぶ。

DuckDBのRelational API・Expression APIで条件を構築し、任意SQL・列・テーブル・パスを受け付けない。
各操作で接続を作り直し、信頼済みParquet以外の外部アクセス・拡張の自動取得を禁止する。
制約は取得最大200行・5秒・256MB・1スレッド。OSレベルの隔離を保証する制約ではない。

検索・集計の戻り値は明示的な `CallToolResult` で分離する。

- `content`：件数・要約・最大3行のサンプル。
- `structuredContent`：結果ID・件数・最大20行の画面用プレビュー。
- 保存ファイル：上限200行の結果。ローカルは `results/`、AgentCoreは `/tmp/results`。

単純な辞書の自動変換で表示用データを `content` に重複させない。
エージェント側は表示用データをAG-UIへ投影した後、会話状態から除去する。
保存結果は一時ファイルで、Runtimeセッションをまたぐ保持を保証しない。
全量を取得するWeb APIやMCPリソースは未実装。

以下は `mcp/` で実行する。結果IDは同じMCP環境で保存したものに限る。

```sh
uv run --locked explore-mcp inspect
uv run --locked explore-mcp query-demo
uv run --locked explore-mcp result 結果ID
```

## 数値比較

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

`Dockerfile` は合成ParquetとDuckDBを含むAgentCore向けのARM64コンテナを作る。専用のエントリーポイントは
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

ローカルテストはMCP実通信と模擬AWS入口での署名・ツール実行を確認する。
実際のIAM認可、V2復元後の動作、クラウドの遅延は、配備後に別途確認が必要。

仕様：[AgentCore MCP契約](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.html)、
[IAM認証](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)。

## ログとテレメトリ

通常の `uv run` 起動では、ログ・OTelトレース・メトリクスをstderrへ出し、外部へ送信しない。
ログレベルの既定はINFOで、`LOG_LEVEL` で変更する。
コンテナはADOTで計装し、単体のDocker起動ではconsole exporterを使う。
Terraform配備時はAWS exporterへ切り替え、CloudWatchへ送信する。
詳細は [エージェントのログ設定](../agent/README.md#ログとテレメトリ) を参照。

## テスト

`mcp/` で実行する。

```sh
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pyright src tests
uv run --locked pytest -q
```

HTTPテストは5ツールの公開・UIリソース取得・テキストフォールバック・モデル用3行／画面用20行の分離・入力エラー・Host/Origin制約を確認する。
Strandsとの実HTTP接続・AG-UI結果イベント・モデル履歴との分離は `agent/` の `uv run --locked pytest -q` で確認する。
UIの描画処理・指標切り替え・0件表示は `npm --prefix mcp/ui test`（リポジトリ直下）で検査する。
これは模擬DOM上のテストで、実ブラウザの描画・sandbox隔離の検証とは区別する。
