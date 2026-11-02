# app — Next.js + CopilotKit

ローカルのデータ探索チャット。Next.js 16.4.4 / React 19.3.1 / CopilotKit 1.83.0。
AG-UIクライアントはCopilotKitの依存に合わせて1.0.2に固定した。
Node.js 22、npm、Python側はuvを使う。

```text
Browser / CopilotKit React v2
  → Next.js /api/copilotkit/*（CopilotKit TypeScript Runtime v2）
    → HttpAgent / AG-UI SSE
      → agent/ のFastAPI :8000/invocations
        → ag-ui-strands → Strands → さくらAI Engine / DuckDB
```

TypeScript Runtimeはローカルの中継で、CopilotKitのクラウド契約やAPIキーは使っていない。
推論APIキーは `agent/.env` にだけ置く。Next.jsやブラウザへ渡さない。
`app/` のAGENT_URLはサーバー専用。現段階ではlocalhostのHTTPだけを許可する。
AWS経由に切り替える際は認証も含めて別途設計する。

## 起動

最初にPython側のサンプルを準備する。生成済みなら `prepare-sample` は省略する。

```sh
cd agent
uv sync --locked
uv run explore prepare-sample
```

ターミナル1（さくらAPIを使う）:

```sh
cd agent
uv run --locked --env-file .env explore-server
```

APIを使わず接続だけ確認する場合は、代わりに次を使う:

```sh
uv run --locked explore-server --model fixture
```

fixtureは本物のStrandsツールとDuckDBを実行するが、モデルは固定シナリオ。
質問内容にかかわらず、新宿区の年別集計を実行する。画面にもその旨を表示する。
自然言語の理解やモデル精度の検証には使わない。

ターミナル2:

```sh
cd app
npm ci --ignore-scripts
npm run dev
```

ブラウザで <http://127.0.0.1:3000> を開く。各プロセスはCtrl+Cで停止。
両方とも127.0.0.1にだけバインドする。3000/8000ポートが既に使用中なら、
既存プロセスを確認して停止してから起動する。

設定変更が必要な場合のみ `cp .env.example .env.local` を実行する。
既定のローカル接続には `app/.env.local` の作成は不要。

## 画面で確認すること

例: 「項目を確認してから、新宿区を年別に集計し、件数と平均取引総額を教えて」

- 送信後に文章が逐次表示され、最後に入力欄が送信可能へ戻る。
- スキーマ確認・集計の進捗と完了が表示される。
- 「検索・集計結果」に年別3行、各年40件、平均42,500,000円が表示される。
- 回答に合成データであることが明示される。
- 停止、エラー表示、狭い画面での入力・結果表の横スクロールを確認する。

これは架空データの期待値であり、実際の市場価格ではない。

## イベントと履歴

標準AG-UIの文章・ツールイベントに加え、次の `CUSTOM` イベントを受け取る:

| name | 用途 |
| --- | --- |
| `data_result` | request_id / result_id / tool_call_id、件数、最大20行のプレビュー |
| `tool_status` | 実際のツール実行の成功/失敗。TOOL_CALL_ENDとは別に扱う |
| `run_metrics` | モデル呼び出し回数、ツール実行回数、ツールエラー数 |

`TOOL_CALL_END` はAG-UIでは引数生成の終端であり、DuckDB処理の完了とは限らない。
実行の成否は `tool_status` で表示する。

プレビューはReactの画面状態にだけ保持し、AG-UIの `state` や会話メッセージへ追加しない。
LLMへのツール結果は従来どおり最大3行のサンプルと件数・参照ID。
次の質問では会話メッセージを再送するが、画面用プレビューをモデルへ送り直さない。
右ペインへ表示を移す場合も `data_result` を再利用できる。

履歴はCopilotKitのInMemoryAgentRunnerに置く。上限は10スレッド、各5run、
保持済みイベント約8MBを指定しているが、実行中イベント全体の厳密なメモリ上限ではない。
永続化やログイン・ユーザーごとの権限制御は未実装。ローカル単独利用が対象。
Python側は1リクエストごとにAgentと制約を生成し、受信会話をAG-UIアダプターで再構成する。
40メッセージ超や128KiB超のリクエストは拒否する。長い会話はページを再読み込みして始め直す。

## 検証

```sh
cd app
npm run typecheck
npm run build
```

APIなしのフル経路テスト（Python側をfixtureモードで起動）:

```sh
npm run smoke
```

さくらを使う明示的な疎通試験（実API呼び出しあり、最大4モデル呼び出し/質問）:

```sh
npm run smoke -- --live
```

`--live` の有無とバックエンドのモードが一致しない場合は、推論を実行する前に停止する。
標準AG-UIクライアントでNext.js RuntimeからPythonまでを通し、
テキスト・独立結果イベント・期待値・正常終端・telemetry無効状態を確認する。
証跡はGit除外対象の `agent/results/agui-<mode>-smoke.json`。
**このスクリプトはブラウザ描画を検証しない。**

初回実装では型チェック・production build・fixtureのフル経路を確認。
さくら実環境でも3モデル呼び出し・2ツール実行・エラー0で成功した。
最初の文章約1.99秒、独立結果約4.45秒、終端約6.19秒。
これはNext.js HTTP経路の単発測定であり、画面に描画される時刻ではない。
ブラウザ自動操作は環境で許可されなかったため、自動画面確認は未実施。

## テレメトリ

`npm run dev/build/start/typecheck` は `NEXT_TELEMETRY_DISABLED=1`、
`COPILOTKIT_TELEMETRY_DISABLED=true`、`DO_NOT_TRACK=1` を設定して起動する。
`/api/copilotkit/info` の `telemetryDisabled: true` も確認した。
`.npmrc` の `ignore-scripts=true` で依存パッケージのインストールスクリプトも実行しない。

未停止時のNext.jsの宛先は `telemetry.nextjs.org`、今回のCopilotKit v2 Runtime/Inspectorは
`telemetry.copilotkit.ai/ingest`。公式説明では前者は利用/ビルド情報、後者は
会話・状態・ツール内容を除く製品メタデータ。CopilotKitの依存には旧経路のSegmentコードもある。
DO_NOT_TRACKは対応ライブラリが尊重する環境変数であり、全通信を遮断する仕組みではない。
全依存のパケット監査は行っていない。さくらへの質問・会話・要約送信は推論に必要な別経路。

根拠:
[CopilotKit Runtime](https://docs.copilotkit.ai/strands/copilot-runtime)、
[AG-UI Strands](https://github.com/ag-ui-protocol/ag-ui/tree/main/integrations/aws-strands/python)、
[CopilotKit telemetry](https://docs.copilotkit.ai/telemetry)、
[Next.js telemetry](https://nextjs.org/telemetry)。
資料の例は旧APIを含むため、実装は導入済み1.83.0の型定義と動作確認を優先した。
