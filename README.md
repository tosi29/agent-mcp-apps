# 構造化データ探索エージェント PoC

Strands Agents + さくらAI Engine + 通常のPythonツール + DuckDBで、
自然言語によるデータ探索を検証する。Pythonの構成管理は **uv**。

```text
app/        Next.js + CopilotKit チャット、TypeScript Runtime、AG-UI接続
agent/      PythonのCLI / AG-UIサーバー、uv.lock、自動テスト、技術調査
terraform/  AWS IaC 用（現在は配置先のみ。リソース未作成）
```

調査開始時は空ディレクトリで、既存コード・IaC・Git管理はなかった。
ADK・MCP Server・MCP Appsは実装していない。

## 現在できること

- 架空の不動産取引360行を再現可能なParquetとして生成し、DuckDBでスキーマ確認・検索・集計。
- Strandsの通常のPythonツールとして登録し、さくら向け `OpenAIModel` に接続するCLI。
- テキスト・ツール開始/終了・構造化結果を独立イベントとしてJSONLまたはSSE形式で標準出力。
- LLMへ返す最大3行のサンプルと、UI用最大20行のプレビュー、最大200行の保存結果を分離。
- 外部HTTPを模擬した、実際のStrandsとOpenAIプロバイダーを通るローカル自動テスト。
- Next.js + CopilotKitからAG-UI経由で質問し、文章と進捗・結果表を別に表示する画面。
- `ag-ui-strands` によるローカルFastAPIサーバーと、外部API不要の固定シナリオ検証モード。

**さくら実環境では `preview/Kimi-K2.7-Code` で認証・モデル応答・tool calling + streamingが1質問成功。**
`gpt-oss-120b` は未検証。結果と測定条件は [agent/SAKURA_SMOKE_RESULT.md](agent/SAKURA_SMOKE_RESULT.md) を参照。
Next.js → CopilotKit Runtime → Python AG-UI → さくら → DuckDB のHTTP経路も、
別の1質問で3モデル呼び出し・2ツール実行・エラー0を確認した。
ブラウザの自動画面操作は許可されず、描画の自動検証は未実施。AWS配備も未実装。
CLIの `--sse` は標準出力の形式であり、ブラウザまでのストリーミングを証明しない。

## ローカルで実行

```sh
cd agent
uv sync --locked
uv run explore prepare-sample
uv run explore inspect
uv run explore query-demo
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

この範囲はキー不要・推論API呼び出しなし。
`prepare-sample` は既存ファイルを上書きしないため、2回目以降は省略する。

チャット画面は次の2プロセスで起動する（各ディレクトリで依存導入済みの場合）:

```sh
# ターミナル1
cd agent
uv run --locked --env-file .env explore-server
```

```sh
# ターミナル2
cd app
npm run dev
```

<http://127.0.0.1:3000> を開く。APIなしの場合はPython側に `--model fixture` を指定する。
APIキーは `agent/.env` にだけ設定する。Node側のtelemetryはnpmスクリプトで無効化する。
詳しい初期セットアップ・画面/HTTP検証・telemetryは [app/README.md](app/README.md)、
さくらの設定とCLI疎通手順は [agent/README.md](agent/README.md) を参照。
公式仕様・実現性・未検証リスク・今後の実装順は
[agent/TECHNICAL_REVIEW.md](agent/TECHNICAL_REVIEW.md) に記録している。

クラウド作成・有料API利用・公開、データセットやUI等の重要な設計変更は事前相談する。
