# agent — Strands + DuckDB

Strands AgentsからPythonツールを呼び、合成Parquetを検索・集計する。
Python 3.12とuvを使用し、依存関係は `pyproject.toml` と `uv.lock` で管理する。

## セットアップとCLI

以下のコマンドは `agent/` で実行する。

```sh
uv sync --locked
uv run --locked explore prepare-sample
uv run --locked explore inspect
uv run --locked explore query-demo
```

この範囲はAPIキー不要で、推論APIを呼ばない。
`prepare-sample` は360行の架空データを `data/synthetic.parquet` に生成する。
既存ファイルを上書きしないため、生成済みなら省略する。
列は `transaction_id / municipality / year / quarter / price_yen / area_m2`。
地域名は実在するが、価格・面積・時期は架空。国交省の実データとはスキーマも異なる。
`query-demo` は新宿区を年別集計し、2023〜2025年の各年40件・平均42,500,000円を返す。
これは合成データの期待値であり、市場価格には使えない。

## AG-UIサーバー

```sh
uv run --locked explore-server --model fixture
```

127.0.0.1:8000の `GET /ping` と `POST /invocations` を提供する。終了はCtrl+C。
fixtureは実際のStrandsツールとDuckDBを動かすが、モデルは固定応答。
質問内容にかかわらずスキーマ確認と新宿区の年別集計を行い、外部APIは呼ばない。
Next.jsの起動・HTTP疎通テストは [appのREADME](../app/README.md) を参照。

## AgentCore用コンテナ

リポジトリ直下でARM64イメージをビルドする。

```sh
docker build --platform linux/arm64 -t agent-mcp-apps-agent:poc agent
docker run --rm -p 127.0.0.1:8080:8080 agent-mcp-apps-agent:poc
```

コンテナはAgentCore用の `0.0.0.0:8080` で待ち受ける。既定はfixtureで、Terraformの設定によりさくらへ接続する。
Strands・DuckDB・合成Parquetを含み、`.env`・APIキー・実データは含めない。
`/ping` がhealthyになる前にデータを検証し、接続・結果ID・リクエスト状態は操作ごとに作る。
IAM認証はAgentCore側で行う。既存のローカル起動コマンドはループバック限定を維持する。
配備方法は [TerraformのREADME](../terraform/README.md) を参照。

AgentCoreでさくらを使う場合は、`EXPLORER_MODEL_MODE=sakura`、`SAKURA_API_KEY_PARAMETER_NAME`、
`SAKURA_MODEL_ID` を設定する。Terraformが名前と設定だけを渡す。
APIキーは事前作成したSSM SecureStringの値に保存し、各runで `GetParameter(WithDecryption=True)` から取得する。
起動・`/ping` では取得しないため、キーを起動時スナップショットに固定しない。キー更新は次のrunから反映する。
SSM取得や設定の失敗時にfixtureへ切り替えることはない。
SSMの実権限とさくらの接続は、デプロイ後の実API検証が必要。

## さくらAI Engineへの接続

利用するモデル、基盤モデル無償プランの契約、残枠をコントロールパネルで確認する。
使用モデルはtool callingとstreamingに対応している必要があり、互換性はモデルごとに確認する。
初回のみ環境ファイルを作り、エディタで設定する。

```sh
cp .env.example .env
chmod 600 .env
```

| 環境変数 | 値 |
| --- | --- |
| `SAKURA_API_KEY` | 利用者のAPIキー |
| `SAKURA_MODEL_ID` | アカウントで利用可能なモデルID |

`.env.example` のモデルIDは設定例で、利用可否や互換性を保証するものではない。
APIキーとモデルIDが未設定なら起動しない。
APIキーはPython側で管理し、Next.jsやブラウザへ渡さない。

チャット画面向けのサーバーを起動する。

```sh
uv run --locked --env-file .env explore-server
```

CLIから直接質問する場合は次を使う。

```sh
uv run --locked --env-file .env explore ask '項目を確認してから、新宿区を年別に集計し、件数と平均取引総額を教えて'
```

質問・会話履歴・ツール結果の要約が `https://api.ai.sakura.ad.jp/v1/chat/completions` へ送られる。
上限は1質問4回のモデルAPI呼び出し、各回 `max_tokens=2048`、HTTPタイムアウト60秒、質問全体120秒。
OpenAIクライアントとStrandsの自動再試行は無効。有料モデルやBedrockへの自動フォールバックはない。

切り分け用オプションも同じ推論APIを使用する。

```sh
uv run --locked --env-file .env explore ask '新宿区の2024年の取引を検索して' --no-stream
uv run --locked --env-file .env explore ask '地域別の件数と平均取引総額を教えて' --sse
```

`--sse` は標準出力の形式を変えるオプションで、HTTPサーバーを起動しない。
CLIは `done.status=success` で終了コード0、設定・実行エラーで1を返す。
ツールの失敗後にモデルが回答して正常終了する場合は、`tool_errors` に失敗数が残る。

## ツールとクエリの制約

| ツール | 機能 |
| --- | --- |
| `describe_dataset` | 列・単位・地域候補・行数を返す |
| `search_transactions` | 地域・年・価格範囲で検索する |
| `aggregate_transactions` | 同じ条件で絞り込み、地域・年・四半期のいずれかで集計する |

モデルから任意SQL・テーブル名・ファイルパスは受け付けない。
地域はNFKC正規化・前後空白除去後の完全一致で、`%`・`_` は通常の文字として扱う。
複数キーワード・部分一致・前方一致は未実装。
検索・集計・スキーマ取得はDuckDBのRelational APIとExpression APIで構築する。
条件値は `lit()`、列は `col()` で表し、集計列は許可リストから選ぶ。
金額・年・取得上限はPython側で検証し、最大200行を返す。
総件数・グループ数はLIMIT前に計算する。サンプル生成と接続設定には固定SQLを使う。

操作ごとにDuckDB接続を作り、次の制約を適用する。

- ローカルParquet1ファイルだけを `allowed_paths` で許可
- 外部アクセス、拡張の自動取得・ロードを無効化し、設定をロック
- 1スレッド、`memory_limit=256MB`、ディスクspill不可
- クエリ構築から `fetchall()` までを対象に、5秒で `interrupt()`

これらはOSによる隔離やプロセス全体のメモリ上限ではない。
処理はスレッドへ委譲し、接続を共有しない。キャンセルでも実行中のスレッドは即座には強制終了されない。

## 結果とイベント

```text
検索・集計結果（最大200行）
  ├─ ローカル保存：results/<request_id>/<result_id>.json
  ├─ UI：最大20行のプレビュー + result_id
  └─ LLM：件数 + 最大3行のサンプル + result_id
```

`total_count` は検索時は該当取引数、集計時はグループ数。
`truncated` は保存結果の打ち切り、`preview_truncated` はUIへの省略、
`sample_truncated` はモデル向けサンプルの省略を表す。
集計グループが3つを超える場合もモデルには抜粋を返すため、必要に応じて条件を絞って再集計する。

```sh
uv run --locked explore result <request_id> <result_id>
```

結果取得HTTP API、ページング、全量エクスポート、保存期限・所有権管理は未実装。
`data/`、`results/`、`.env` はGit対象外だが、生成したデータや結果はローカルに残る。

CLIのJSONL/SSEイベントは次の形式を持つ。

| type | 内容 |
| --- | --- |
| `text_delta` | 回答文の断片 |
| `tool_start` / `tool_end` | tool_call_id、ツール名、引数または実行結果の状態 |
| `data_result` | 件数、プレビュー、参照ID |
| `error` | エラー種別と利用者向けメッセージ |
| `done` | 終了状態、モデル・ツールの呼び出し回数、ツールエラー数 |

共通フィールドは `version: 1`、`request_id`、単調増加する `seq`、開始からの `elapsed_ms`。
AG-UIでは標準イベントと `CUSTOM data_result / tool_status / run_metrics` を使用する。
画面用プレビューを会話メッセージ・モデル向け共有stateに含めない。

## リクエストと履歴

Python側は毎回新しいAgentと実行予算を作り、受信した会話履歴を再構成する。
同時実行は1runで、処理中の追加要求には429を返す。
入力上限は128KiB・40メッセージ・最新の質問4,000文字。
クライアント指定のsystem/developerメッセージ、ファイル、ツール、共有state、任意のforwardedPropsは採用しない。
認証と永続セッションは未実装で、ローカル単独利用を対象とする。

FastAPIのOpenTelemetry自動設定・トレース・メトリクス・ログ記録は無効。
Strandsの外部トレースexporterは設定しない。ライブラリログは起動時に抑止する。

## 自動テスト

推論API不要のテストと静的チェックを実行する。

```sh
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

DuckDBの検索・集計値、0件・上限・不正入力・並行接続、許可外ファイルの拒否、
クエリ中断、結果の3/20/200行分離を検査する。
Strands/OpenAIプロバイダーに模擬HTTPを接続し、ツール循環、ストリーミング、
429、呼び出し上限、タイムアウト、異常終了を検査する。
AG-UIでは入力制限・イベント・履歴再送・UIプレビューの非モデル化も対象にする。
実モデルの回答品質、ブラウザ描画、AWS上の動作は対象外。

## コード構成

| ファイル | 役割 |
| --- | --- |
| `data.py` | SDK非依存のデータ生成・入力検証・検索・集計 |
| `results.py` | 結果保存、UI用プレビュー、LLM用要約 |
| `runtime.py` | Pythonツール、Strandsフック、さくらモデル設定 |
| `cli.py` | CLI、JSONL/SSE出力 |
| `server.py` | FastAPI・AG-UI、リクエスト制約 |
| `agentcore_server.py` | AgentCore用サーバーの起動設定と接続モード選択 |
| `parameter_store.py` | runごとのSecureString取得とさくらモデル生成 |
| `fixture_model.py` | API不要の固定シナリオ |

コードは `src/exploration_agent/` に配置する。
