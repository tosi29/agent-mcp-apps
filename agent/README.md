# agent — Strandsエージェント

Strands・さくらAI Engine・AG-UIを接続するPythonプロジェクト。Python 3.12・uvで管理する。
データ探索は別のMCPサーバーを呼び出す。DuckDB・Parquet・検索結果の保存は `mcp/` 側に置く。

## ツール

| ツール | 提供元 | 機能 |
| --- | --- | --- |
| `echo_text` | 通常のPython関数 | 200文字以内の入力をそのまま返す接続検証サンプル |
| `describe_dataset` | MCP | 項目・単位・地域候補・件数の確認 |
| `search_transactions` | MCP | 地域・年・価格範囲で検索 |
| `aggregate_transactions` | MCP | 地域・年・四半期で集計 |
| `compare_values` | MCP | 差分・増減率の計算 |
| `show_transaction_dashboard` | MCP Apps | 棒グラフと表のダッシュボードを表示 |

通常のPythonツールの例は `src/exploration_agent/tools.py` の `echo_text`。
MCP未接続でも使用でき、外部通信・ファイル操作・状態変更は行わない。
MCPが指定されている場合は、5ツールが揃わないと実行を開始しない。ローカル関数へのフォールバックはない。

## ローカル起動

先に [MCPのセットアップと起動](../mcp/README.md#ローカル起動)を行う。
別ターミナルで、リポジトリ直下から次を実行する。

```sh
cd agent
uv sync --locked
uv run --locked explore-server --model fixture --mcp-url http://127.0.0.1:8001/mcp
```

127.0.0.1:8000の `GET /ping` と `POST /invocations` を提供する。終了はCtrl+C。
fixtureは項目確認・新宿区の年別集計・数値比較を行う固定シナリオで、モデルAPIは呼ばない。
質問に「ダッシュボード」または「グラフ」が含まれると、集計をMCP Appsツールへ置き換えた固定シナリオになる。
推論表示にも、サンプルであることを明記した固定テキストを送る。
MCP接続先を省略したfixtureは `echo_text` だけを呼ぶ。検索結果は生成しない。
画面の起動方法は [appのREADME](../app/README.md) を参照。

## さくらAI Engineへの接続

利用するモデル・利用プラン・残枠はコントロールパネルで確認する。
以下は `agent/` で実行する。

```sh
cp .env.example .env
chmod 600 .env
```

`.env` に `SAKURA_API_KEY` と `SAKURA_MODEL_ID` を設定する。キーをブラウザへ渡さない。
モデルはtool callingとstreamingへの対応が必要。例示モデルの互換性を保証するものではない。

```sh
uv run --locked --env-file .env explore-server --mcp-url http://127.0.0.1:8001/mcp
uv run --locked --env-file .env explore ask '新宿区を年別に集計して' --mcp-url http://127.0.0.1:8001/mcp
```

通常のPythonツールだけを試す場合は、MCP接続先を省略して `こんにちはをecho_textで返して` と質問する。
実際の質問送信は、質問・会話履歴・ツール結果の要約をさくらの `/v1/chat/completions` へ送る。
1質問は最大4回のモデル呼び出し、各回 `max_tokens=2048`、HTTPタイムアウト60秒、全体120秒。
Strands・OpenAIクライアントの自動再試行と、有料モデルへの自動フォールバックは無効。
CLIの `--no-stream` はモデルの非ストリーム動作、`--sse` は標準出力の形式を切り替える。

## 結果とイベント

MCPの `content` はモデル用の要約と最大3行、`structuredContent` は画面用の最大20行を返す。
`MCPPreviewHook` が表示用データを独立した `data_result` イベントへ変換し、
`structuredContent` とMCPメタデータをモデルの会話状態へ入る前に取り除く。
検索結果の全量（上限200行）はMCP側に一時保存する。エージェントは保存しない。
MCP Appsツールでは結果の `_meta.preview` をUIへ送り、モデルの会話状態から取り除く。
UIが必要になったときだけ、Apps capabilityを明示した別のリソース専用MCP接続でHTMLを取得する。
同じrun内ではHTMLを再利用する。HTMLは最大768KiB、許可した `ui://` リソース1つに制限する。
HTML・ツール引数・UI専用結果は `data_result.app` に載せ、会話メッセージへコピーしない。
任意SQLを受け付けず、列・集計・条件値の制御はMCP側で行う。

推論テキストはAG-UIの `REASONING_*` で渡し、CopilotKitの開閉表示を使う。
次の質問の `reasoning` メッセージはモデル入力から除外する。
RAWと暗号化推論値は送信しない。推論の返却有無はモデルと設定に依存する。
クライアントから渡るツール・共有状態・A2UI設定はモデルへ取り込まない。

## AgentCoreへの配備

`Dockerfile` はエージェント用ARM64イメージを作る。ParquetとDuckDBは含めない。
既定はfixtureで、さくら接続時は `EXPLORER_MODEL_MODE=sakura`、
`SAKURA_API_KEY_PARAMETER_NAME`、`SAKURA_MODEL_ID` を設定する。
SSM SecureStringの値は各runで取得し、起動時スナップショットへ固定しない。

MCPは `MCP_RUNTIME_ARN` で東京リージョンのRuntimeを指定する。
IAM署名と一時認証情報の取得は各HTTPリクエストで行い、接続中はMCPセッションIDを引き継ぐ。
起動・`/ping` ではMCPへ接続しない。任意の外部MCP URLやHTTPリダイレクトは許可しない。
ローカルから同じMCPを試す場合は `--mcp-runtime-arn 'Runtime ARN'` を使う。
`--mcp-url` との同時指定はできない。fixtureでもAgentCoreへの実接続には料金が発生し得る。

配備手順は [TerraformのREADME](../terraform/README.md#mcpの配備)。
5ツールに対応するMCPとエージェントを両方更新する必要がある。クラウドの実動作は配備後に確認する。
MCP初期化失敗時、採用SDKの後処理から `RuntimeWarning` が出る場合がある。

## ログとテレメトリ

通常の `uv run` 起動では、Pythonログ・OTelトレース・メトリクスをstderrへ出す。
外部のOTel送信先は設定しない。CLIのJSON/SSEはstdoutへ出す。
既定のログレベルはINFOで、`LOG_LEVEL=DEBUG` などで変更できる。
質問・回答・ツールの引数と結果・例外も記録対象になる。APIキーや認証ヘッダーは記録しない。

コンテナは `opentelemetry-instrument` で起動する。単体のDocker起動ではconsole exporterを使い、
端末のコンテナ出力へ出す。Terraform配備時は環境変数でADOTのAWS exporterへ切り替える。
AgentCoreでは各RuntimeのCloudWatch Logsへログとスパン、CloudWatchへメトリクスを送る。
Transaction Searchの有効化が必要。送信権限・配備手順は [TerraformのREADME](../terraform/README.md) を参照。
`opentelemetry-instrument` などでproviderを事前設定した場合はその設定を使い、console exporterを重ねない。

## テスト

先に `mcp/` で `uv sync --locked` を行う。agentの統合テストはMCP用の仮想環境から
ローカルサーバーを起動し、別プロセス間で実通信する。AWS・モデルAPIは呼ばない。

```sh
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

通常の `echo_text` のfunction calling、MCP検索・集計、モデル用要約とUIデータの分離、
推論表示、後続質問、上限・異常終了を検査する。ブラウザ描画と実モデルの品質は対象外。
