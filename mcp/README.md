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
ループバック限定・認証なしのローカル検証用で、公開配備は未対応。

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
`--mcp-url` を省略したエージェントはMCPに接続しない。

さくらを使う場合は `--model fixture` を外し、`uv run --locked --env-file .env explore-server --mcp-url ...` で起動する。
実際の質問送信は推論APIを呼ぶ。AWS側のエージェントとTerraformにはMCPの接続設定を追加していない。

## テスト

`mcp/` で実行する。

```sh
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

HTTPテストはJSON応答・入力エラー・Host/Origin制約を確認する。
Strandsとの実HTTP接続・AG-UI結果イベント・モデル履歴との分離は `agent/` の `uv run --locked pytest -q` で確認する。
