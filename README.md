# 構造化データ探索エージェント PoC

Strands Agents + さくらAI Engine + 通常のPythonツール + DuckDBで、
自然言語によるデータ探索を検証する。Pythonの構成管理は **uv**。

```text
app/        Next.js + TypeScript 用（現在は配置先のみ）
agent/      PythonのローカルPoC、uv.lock、自動テスト、技術調査
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

**さくら実環境では `preview/Kimi-K2.7-Code` で認証・モデル応答・tool calling + streamingが1質問成功。**
`gpt-oss-120b` は未検証。結果と測定条件は [agent/SAKURA_SMOKE_RESULT.md](agent/SAKURA_SMOKE_RESULT.md) を参照。
Next.js画面、HTTP/SSEサーバー、AWS配備も未実装であり、
引き継ぎ資料のMinimum Vertical Slice全体はまだ完了していない。
`--sse` は標準出力のフレーム形式であり、ブラウザまでのストリーミングを証明しない。

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

さくらの設定と疎通手順は [agent/README.md](agent/README.md) を参照。
公式仕様・実現性・未検証リスク・今後の実装順は
[agent/TECHNICAL_REVIEW.md](agent/TECHNICAL_REVIEW.md) に記録している。

クラウド作成・有料API利用・公開、データセットやUI等の重要な設計変更は事前相談する。
