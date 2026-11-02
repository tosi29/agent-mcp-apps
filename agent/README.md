# agent — ローカル最小PoC

Python 3.12 + uv。`uv.lock` をコミット対象とし、`uv sync --locked` で再現する。
Strands `1.63.0`、DuckDB `2.0.0` を直接依存として固定した。
Pythonは実機で3.12.11を使用。Pythonパッチ版そのものの完全固定はしていない。

## 構成

```text
src/exploration_agent/
  data.py       SDK非依存。合成Parquet生成、入力検証、固定SQLによる検索・集計
  results.py    上限付き結果保存、UI用プレビュー、LLM用要約
  runtime.py    通常のPythonツール、Strandsフック、イベント変換、さくらモデル設定
  cli.py        ローカル操作とJSONL/SSE出力
  server.py     ローカルFastAPI / AG-UI、リクエスト制約、独立した結果イベント
  fixture_model.py  API不要の固定シナリオ（自然言語推論はしない）
tests/          DuckDB実行、結果分離、実SDK + 模擬HTTPでの結合テスト
```

## セットアップとAPI不要の検証

リポジトリの `agent/` を作業ディレクトリにする。

```sh
uv sync --locked
uv run explore prepare-sample
uv run explore inspect
uv run explore query-demo
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

`prepare-sample` は360行、約3KiBの架空データを `data/synthetic.parquet` に生成する。
実在の取引をもとにしていない。地域名は実在するが、価格・面積・時期は架空。
列は `transaction_id / municipality / year / quarter / price_yen / area_m2`。
**国交省のCSVスキーマとは異なる。実データ取り込み機能はまだない。**

`query-demo` は新宿区について2023〜2025年を集計し、各年40件、平均42,500,000円を返す。
これは固定フィクスチャの期待値で、市場価格に関する情報ではない。

## さくらへの接続

2026-11-02、利用者が設定した `preview/Kimi-K2.7-Code` で実環境の1質問が成功した。
3回の推論API呼び出しでスキーマ確認・年別集計・最終回答まで完了し、ツールエラー0。
初回テキスト約2.02秒、構造化結果約3.00秒、完了約5.91秒（ローカルCLIでの単発測定）。
詳細は [SAKURA_SMOKE_RESULT.md](SAKURA_SMOKE_RESULT.md) を参照。
`gpt-oss-120b`、他モデル、実環境の非streamモードは未検証。

基盤モデル無償プランの契約、利用可能モデル、残枠をコントロールパネルで確認する。
キーはチャットに貼らず、ローカルファイルへ設定する。

```sh
cp .env.example .env
chmod 600 .env
# エディタで .env を開き、以下を設定する
# SAKURA_API_KEY=<アカウントトークン>
# SAKURA_MODEL_ID=<利用可能なモデルID>
# SAKURA_FREE_PLAN_CONFIRMED=true
uv run --env-file .env explore ask '項目を確認してから、新宿区を年別に集計し、件数と平均取引総額を教えて'
```

`.env.example` の `gpt-oss-120b` は公式掲載モデルをもとにした初回検証候補。
モデルを確定したものではなく、実際のアカウントで利用できるかを確認する必要がある。
`SAKURA_FREE_PLAN_CONFIRMED=true` は利用者による確認の宣言であり、
プログラムが契約や残枠を照会したり費用を保証したりする仕組みではない。
未設定ではモデル呼び出し前に停止する。自動的な有料モデル・Bedrockへのフォールバックはない。

APIは `https://api.ai.sakura.ad.jp/v1/chat/completions`。
最大4モデル呼び出し/質問、各回 `max_tokens=2048`、OpenAIクライアント再試行0、
Strandsモデル再試行無効、HTTPタイムアウト60秒、質問全体の処理時間上限120秒。
1質問で複数APIリクエストを消費する。SDKが送る `stream_options.include_usage` 等の
さくら側の受理は今回の `preview/Kimi-K2.7-Code` の経路で成功した。
他モデルや全パラメータの互換性を保証するものではない。

切り分け用の非stream実行とSSEフレーム出力:

```sh
uv run --env-file .env explore ask '新宿区の2024年の取引を検索して' --no-stream
uv run --env-file .env explore ask '地域別の件数と平均取引総額を教えて' --sse
```

両方とも推論APIを使うため、疎通承認の回数上限には別々に数える。
CLIの終了コードは `done.status=success` で0、設定エラーや実行エラーで1。
ツール失敗後にモデルが説明して正常終了する場合は `tool_errors` に失敗数が残る。
認証エラー・レート制限・異常終了は詳細なAPI本文やキーを出力しない。
ライブラリのログもCLIでは抑止し、アプリケーションイベントを観測する。

疎通の合格条件:

1. `describe_dataset` と検索/集計の `tool_start` があり、`arguments` を確認できる。
2. 同じ `tool_call_id` の `data_result` と、成功した `tool_end` がある。
3. `text_delta` に実際のツール結果にもとづく合成データの説明がある。
4. 最後に `done` が1回、`status=success`、`tool_errors=0` である。
5. `elapsed_ms` で最初のテキスト/ツール/結果と終了時刻を記録する。

自然言語の曖昧さ、表記揺れ、0件、大量結果の回答品質は実モデルで未評価。
例えば「新宿の安い物件」は地域・価格条件を確認する想定だが、
プロンプトだけで遵守を保証していない。

## イベントとデータ経路

イベントは実験用 `version: 1`、質問ごとの `request_id`、単調増加 `seq`、
リクエスト開始からの `elapsed_ms`、`type` を持つ。

| type | 内容 |
| --- | --- |
| `text_delta` | `text`。モデルの生成文断片。推論過程は転送しない |
| `tool_start` | `tool_call_id`, `name`, `arguments`。実際に実行するツール入力 |
| `tool_end` | `tool_call_id`, `name`, `status`。成功/失敗 |
| `data_result` | `tool_call_id`, `result_id`, 件数、最大20行の `preview_rows`、打ち切り情報 |
| `error` | 詳細本文を除いたエラー種別と利用者向けメッセージ |
| `done` | `status`, `model_calls`, `tool_calls`, `tool_errors`。終端 |

```text
DuckDBの検索/集計結果（最大200行）
  ├─ ローカルJSON保存 → results/<request_id>/<result_id>.json
  ├─ UI向けdata_result → 最大20行のプレビュー + result_id
  └─ モデル向けtool result → 件数 + 最大3行のsample_rows + result_id
```

`total_count` は検索時は該当取引数、集計時はグループ数。
`truncated` は保存結果の打ち切り、`preview_truncated` は保存結果からUI表示への省略、
`sample_truncated` はLLMへ返すサンプルの省略を表す。
モデルには全行のツール結果やSDKイベントを返さない。
集計もグループが3つを超える場合はLLMには抜粋となるため、
特定グループの値が必要なら条件を絞って再集計する。

保存済みの上限付き結果は次で取得できる:

```sh
uv run explore result <request_id> <result_id>
```

この参照IDはローカルCLI用。認証付き別取得HTTP API、ページング、全量エクスポート、
保存期限/削除ポリシー、ユーザーごとの所有権検証は未実装。
生成結果はローカルディスクに残るため、容量管理は次段階で設計する。
`data/`、`results/`、`.env` はGit対象から除外している。

## SQLと実行制約

モデルにはSQL・テーブル名・パスを受け取るツールを渡さない。
地域・年・価格はパラメータバインド、集計列は許可リスト、取得は最大200行。
金額・年・上限値はPython側で検証する。

クエリごとに接続を作り、Parquet1ファイルだけを `allowed_paths` で許可し、
`enable_external_access=false`、拡張の自動取得/ロード無効、設定ロックを適用。
DuckDBは1スレッド、`memory_limit=256MB`、ディスクspill不可、
SQL実行は5秒で `interrupt()` する。

これはOSによる隔離やプロセス全体のメモリ上限ではない。
信頼できる合成Parquetの小規模PoCを対象とする。
任意SQLや不審なParquetを受け付ける場合は別途プロセス/コンテナ隔離を検討する。
非同期ツールはスレッドへDuckDB処理を委譲する。接続は共有しない。
キャンセル時も既に開始したスレッドは即座に強制終了されず、クエリ上限まで動き得る。

## 自動テストの範囲

現在22テスト成功（初回CLI16件、AG-UI関連6件）。DuckDBの値・0件・上限・不正入力・並行接続、
許可外ファイルアクセスの拒否、SQL中断、結果の3/20/200行分離を確認。
実Strands + 実OpenAIプロバイダー + 模擬HTTPで、ストリーミング/非stream両方の
ツール循環、分割されたツール引数、429、呼び出し上限、タイムアウト、
終端、ツールエラー、SSEフレームを確認。
遅延する模擬HTTPの終了前に `text_delta` を受け取れることも確認している。

これらはさくらの実レスポンス、モデルのツール選択精度、ネットワークの遅延、
ブラウザやAWS中継のバッファリングを検証したものではない。

## AG-UIサーバー

```sh
uv run --locked --env-file .env explore-server
# APIなしの検証用
uv run --locked explore-server --model fixture
```

127.0.0.1:8000 の `GET /ping`、`POST /invocations` を提供する。
`ag-ui-strands==1.0.2` / `ag-ui-protocol==1.0.0` / FastAPI 0.162.0 / uvicorn 0.54.0。
Strands本体ではなくAG-UIプロジェクトが保守する統合パッケージを使う。

標準AG-UI入力の会話を受け付け、毎回新しいAgentと最大4モデル呼び出しの予算を作る。
Next.jsが一時保持した会話をリプレイする。クライアントのsystem/developerメッセージ、
ファイル入力、クライアント定義ツール、共有stateや任意のforwardedPropsは採用しない。
初期PoCは同時1runのみ。処理中の追加リクエストは429、全体120秒上限。

`RequestHooks` はAG-UIラッパーに渡す。テンプレートAgentだけに設定しても
アダプターが生成するAgentへフックが引き継がれないため。
アダプターの `ToolBehavior.custom_result_handler` で、ツール本体が保存したプレビューを
`CUSTOM data_result` として出す。ツールの戻り値と会話スナップショットには最大3行だけを残す。
実行完了は `CUSTOM tool_status`、回数は `CUSTOM run_metrics` で観測する。

FastAPIネイティブのOpenTelemetry自動設定・トレース・メトリクス・ログ記録は無効化した。
Strandsの外部トレースexporterはこのアプリから設定していない。
ライブラリログは起動時に抑止する。HTTPイベントはブラウザへ届けるための別経路。

AG-UIのHTTPテストでは型付き入力/終端、ツール実行、3/20行分離、
クライアントstateの非モデル化、入力/Origin拒否、呼び出し上限、タイムアウト、
後続質問での履歴の単一リプレイを確認している。
Next.js側の実行手順と実API経路の測定は [../app/README.md](../app/README.md) を参照。
