# agent — Strandsエージェント

Strands・さくらAI Engine・AG-UIを接続するPythonプロジェクト。Python 3.12・uvで管理する。
データ探索は別のMCPサーバーを呼び出す。DuckDB・Parquet・検索結果の保存は `mcp/` 側に置く。

## ツール

| ツール | 提供元 | 機能 |
| --- | --- | --- |
| `echo_text` | 通常のPython関数 | 200文字以内の入力をそのまま返す接続検証サンプル |
| `web_search` | 通常のPython関数（任意） | TavilyでWebを検索し、タイトル・URL・短い抜粋を返す |
| `web_fetch` | 通常のPython関数（任意） | 指定したURLのページ本文をTavilyで取得して返す |
| `describe_dataset` | MCP | 項目・単位・地域候補・件数の確認 |
| `search_transactions` | MCP | 地域・年・価格範囲で検索 |
| `aggregate_transactions` | MCP | 地域・年・四半期で集計 |
| `compare_values` | MCP | 差分・増減率の計算 |
| `show_transaction_dashboard` | MCP Apps | 棒グラフと表のダッシュボードを表示 |

通常のPythonツールの例は `src/exploration_agent/tools/echo.py` の `echo_text`。
MCP未接続でも使用でき、外部通信・ファイル操作・状態変更は行わない。
MCPに接続できないと実行を開始しない。ローカル関数へのフォールバックはない。
`web_search` と `web_fetch` はAPIキーの参照先を設定したときだけ登録する。詳細は [Web検索](#web検索tavily) を参照。
AWS・Azureの公開ドキュメント用ツールは [リモートMCP](#awsazureのドキュメント用mcp) を参照。

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
モデル呼び出しの回数は制限せず、各回 `max_tokens=2048`、HTTPタイムアウト60秒、1質問全体で300秒。
Strands・OpenAIクライアントの自動再試行と、有料モデルへの自動フォールバックは無効。
CLIの `--no-stream` はモデルの非ストリーム動作、`--sse` は標準出力の形式を切り替える。

## ディレクトリ構成

```text
src/exploration_agent/
├── agent.py             # プロンプトとツールの組み立て。全入口で共通のエージェント定義
├── hooks.py             # 実行回数の集計とツールイベント
├── model.py             # さくらのモデル設定
├── fixture_model.py     # 外部API不要の固定応答
├── secure_parameter.py  # Parameter Storeの遅延読み込み
├── observability.py     # ログ・トレース・メトリクス
├── entrypoints/         # 起動の入口：server（AG-UI）、agui（イベント変換）、agentcore、cli
├── tools/               # 通常のPythonツール：echo、web（web_search・web_fetch）
└── mcp_clients/         # MCPへの接続：exploration、apps、docs、agentcore（SigV4署名）
```

## Web検索（Tavily）

ローカルでは `.env` の `TAVILY_API_KEY`、AgentCoreでは `TAVILY_API_KEY_PARAMETER_NAME` で指定した
SecureStringからキーを読む。両方あればパラメータを優先する。どちらもなければツールを登録しない。
キーは初回利用時に取得してメモリに保持し、起動時スナップショットやエージェントの状態へ含めない。変更は再起動で反映する。
キーの取得や検索に失敗してもそのツール呼び出しだけが失敗し、モデルには固定の失敗メッセージを返す。

モデルが指定できるのは400文字以内の `query` だけで、URLや検索オプションは指定できない。
`search_depth=basic`（1回1クレジット）、最大5件、1runあたり最大3回、HTTPタイムアウト20秒で、リダイレクトは追わない。
モデルへ返すのはhttp(s)のURLと、タイトル200文字・抜粋500文字まで。Tavilyの生成回答は取得しない。

`web_fetch` は `web_search` と同時に登録し、ページ本文をTavily Extractで取得する。検索を経由せず単独でも呼べる。
モデルが指定できるのは500文字以内のhttp(s)の `url` だけで、取得先のサイトは制限しない。
エージェントから対象サイトへは直接通信しない。
`extract_depth=basic`（成功5件で1クレジット）、1回1URL、1runあたり最大3回、HTTPタイムアウト20秒で、リダイレクトは追わない。
モデルへ返す本文は5000文字までで、超えた場合は `truncated` が真になる。

検索クエリと取得するURLはTavilyへ送られ、検索結果とページ本文はモデルAPIへ送られる。実データの導入前に送信範囲を確認する。
検索結果とページ本文は未検証の外部情報として扱い、文中の指示に従わず、合成データの集計と分けて回答するようモデルへ指示している。
これはモデルへの指示であり、不正な指示や取引データのクエリ・URLへの混入を確実に防ぐものではない。
特に `web_fetch` のURLは任意のサイトへ届くため、ページ内の不正な指示に従うとデータが外部へ送られる可能性がある。実データの導入前に制限を見直す。

## AWS・Azureのドキュメント用MCP

`DOCS_MCP_ENABLED=true` のとき、質問ごとに次の公開リモートMCPへ接続する。認証とキーは不要で、読み取り専用。
未設定なら接続しない。fixtureの手順は `.env` を読まないため、外部へ接続しない。

| 対象 | エンドポイント | 許可するツール |
| --- | --- | --- |
| AWS | `https://knowledge-mcp.global.api.aws` | `aws___search_documentation`・`aws___read_documentation`・`aws___list_regions`・`aws___get_regional_availability` |
| Azure | `https://learn.microsoft.com/api/mcp` | `microsoft_docs_search`・`microsoft_docs_fetch`・`microsoft_code_sample_search` |

URLとツールはコードで固定し、モデルや環境変数から変更できない。上記以外のツールはモデルへ公開しない。
AWS MCP Server等の実環境を操作するMCPは接続しない。
接続は5秒、ツール実行は20秒でタイムアウトし、別オリジンへのリダイレクトは追わない。
2サーバー合計で1runあたり最大5回、モデルへ返す本文は1回8000文字まで。`structuredContent` とメタデータは除去する。
接続に失敗したサーバーはそのrunで使わず、警告ログを残して他のツールで続行する。

検索語と取得するURLはAWS・Microsoftへ送られ、結果はモデルAPIへ送られる。実データの導入前に送信範囲を確認する。
取得先URLの制限は各サーバーの許可リストに任せ、エージェント側では検査しない。
結果とツールの説明文は外部から受け取るため、不正な指示の混入を確実には防げない。
結果には未検証である旨を付け、文中の指示に従わないようモデルへ指示している。

## 結果とイベント

MCPの `content` はモデル用の要約と最大3行、`structuredContent` は画面用の最大20行を返す。
`MCPPreviewHook` が表示用データを独立した `data_result` イベントへ変換し、
`structuredContent` とMCPメタデータをモデルの会話状態へ入る前に取り除く。
検索結果の全量（上限200行）はMCP側に一時保存する。エージェントは保存しない。
MCP Appsツールでは結果の `_meta.preview` をUIへ送り、モデルの会話状態から取り除く。
UIが必要になったときだけ、Apps capabilityを明示した別のリソース専用MCP接続でHTMLを取得する。
同じrun内ではHTMLを再利用する。取得するのはコードで固定した `ui://` リソース1つだけ。
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
SSM SecureStringの値は初回のrunで取得してメモリに保持し、起動時スナップショットへ含めない。変更は再起動で反映する。
Web検索のキーは `TAVILY_API_KEY_PARAMETER_NAME` で指定する。Terraform配備では常に設定される。

MCPは `MCP_RUNTIME_ARN` で東京リージョンのRuntimeを指定する。
IAM署名と一時認証情報の取得は各HTTPリクエストで行い、接続中はMCPセッションIDを引き継ぐ。
起動・`/ping` ではMCPへ接続しない。コードで固定したドキュメント用以外の外部MCP URLやHTTPリダイレクトは許可しない。
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
ローカルサーバーを起動し、別プロセス間で実通信する。AWS・モデルAPI・Tavilyは呼ばない。

```sh
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

通常の `echo_text` のfunction calling、MCP検索・集計、モデル用要約とUIデータの分離、
推論表示、後続質問、上限・異常終了を検査する。ブラウザ描画と実モデルの品質は対象外。
