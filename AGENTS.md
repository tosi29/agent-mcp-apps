# 開発エージェント向け指示

このリポジトリは、表形式データを自然言語で検索・集計するPoC。
ユーザーの最新の明示的な指示を優先し、既に合意した作業範囲について確認を繰り返さない。

## 構成と採用方針

- `app/`：Next.js・TypeScript・CopilotKitの画面とTypeScript Runtime。構成管理はnpm。
- `agent/`：Strands Agents・Pythonツールのechoサンプル・AG-UIサーバー。構成管理はuv。
- `mcp/`：探索4ツール・MCP AppsのダッシュボードとDuckDB・Parquet・結果保存を持つMCPサーバー。Python・uvで管理し、`mcp/ui/` のHTMLビルドはnpmで管理する。
- `terraform/`：AgentCore Runtime V2・ECR・IAMと、Web Adapter＋Next.jsを動かすLambda・API GatewayのIaC。
- Terraformには有効・無効を切り替える条件分岐を新たに足さない。新しいリソースは常に作成し、値は変数の既定値で与える。`terraform test` のテストは書かない。
- 画面とPythonの接続はAG-UI。統合には `ag-ui-strands` を使い、HTTPエンドポイントは標準の `add_strands_fastapi_endpoint` に任せる。
- MCP Serverは `mcp/` に分け、エージェントから接続する。項目確認・検索・集計・比較はMCP側へ集約する。データ探索のツールをPython側へ増やさない。
- クラウドのsandbox配備や構成の重要な変更は相談する。sandboxは同じ送信元IP制限と別オリジンを維持し、HTML・中継処理はローカルproxyと共用して、起動・ビルドスクリプトを増やさない。
- `app/` を変更するときは、同ディレクトリの `AGENTS.md` も読む。Next.jsが生成する指示ブロックを保持する。

## データ探索の境界

- モデルには検索・集計の関数と構造化された引数を公開する。任意SQLを受け付けるツールを追加する場合は事前に相談する。
- テーブル・列・集計操作・ファイルの参照先はアプリケーション側で制限する。モデルから任意の識別子やパスを受け取って実行しない。
- 検索・集計はDuckDBのRelational APIとExpression APIで構築する。条件値は `lit()`、列は `col()` で表し、動的な列は許可リストから選ぶ。ユーザー入力をSQL文字列や `sql_expr()` に渡さない。
- 検索処理はエージェントSDKや表示処理から分離する。取得行数・実行時間・メモリ等の制約を維持する。
- クエリビルダーを使っても、アクセス制御や検索パターンの扱いが自動で解決するとはみなさない。

## モデルと画面のデータ経路

- LLM向けの件数・要約・少数サンプルと、画面向けの構造化結果・プレビュー・参照IDを分離する。
- 画面用プレビューや大量の生データを、会話メッセージやモデル向けの共有状態へ戻さない。後続質問での再送にも注意する。
- MCP AppのHTML・結果の `_meta` はUI専用とし、LLMへ渡さない。別オリジンのsandboxとCSPを維持する。Appからのツール実行・チャット送信・モデルコンテキスト更新は現在許可しない。
- データの投影上限は実装とREADMEを参照し、変更する場合は両方を整合させる。
- AG-UIの `TOOL_CALL_END` をツール実行の完了と同一視しない。実行の成否は対応する結果・状態イベントで扱う。
- 合成データと実データを明確に区別する。合成データの値を実際の不動産取引や市場価格として説明しない。

## 秘密情報・外部通信・相談が必要な操作

- 推論APIキーはローカルでは `agent/.env`、AgentCoreでは事前作成したParameter StoreのSecureStringを使う。Next.js側やブラウザへコピーしない。
- Parameter Storeの値をTerraformで取得・管理しない。AgentCore V2の起動時スナップショットへ含めないよう、キーは初回利用時に取得してメモリに保持する。プロセスの環境変数やファイルへコピーしない。キーの変更は再起動で反映する。
- TavilyのAPIキーも同じ扱いで、ローカルは `agent/.env`、AgentCoreはSecureStringを使う。
- Web検索とリモートMCPの仕様は [agent/README.md](agent/README.md) を参照し、変更する場合は実装と整合させる。外部から取得した内容は未検証データとして扱う。
- `.env`、実データ、実行ログ、Terraform state等をコミットしない。キーや認証ヘッダーをログ・ツール出力・資料へ表示しない。
- エージェントとMCPのログ・トレース・メトリクスは有効にする。通常のローカル起動ではstderr、AgentCoreではADOT経由でCloudWatchへ出す。質問・回答・ツール引数・結果も記録対象とするが、キーや認証ヘッダーは記録しない。
- フロントの利用状況テレメトリ無効化は維持し、起動・ビルドにはnpmスクリプトを使う。
- 通常の検証は外部API不要のテストとfixtureモードを使う。fixtureの固定応答をモデルの推論結果として扱わない。
- 実API試験は事前に合意したモデル・利用プラン・呼び出し回数の範囲で行う。追加試験や有料APIへの切り替えは相談する。
- 推論時は質問・会話履歴・ツール結果の要約が外部モデルAPIへ送られることを踏まえ、実データの導入前に送信範囲を確認する。
- クラウドリソース作成、費用が発生する操作、公開は実行前に相談する。既に許可された調査・ローカル実装・検証は進める。
- ローカルサーバーのループバック限定を維持する。公開配備では認証・アクセス制限を別途設計する。
- 任意の外部MCP URLは許可しない。実環境を操作するMCPや接続先の追加は相談する。

## 依存関係と仕様の確認

- Pythonは `agent/pyproject.toml` と `agent/uv.lock`、フロントは `app/package.json` と `app/package-lock.json` を併せて管理する。
- 最新版という理由だけで依存を個別に更新しない。CopilotKitとAG-UIクライアントの組み合わせ等、互換性を確認する。
- SDKやクラウド機能のAPI名・対応範囲は、採用バージョンの公式仕様・型定義・実コードで確認する。
- 採用バージョンはmanifestとlockファイルを参照する。このファイルへ重複して固定しない。

## ドキュメントの役割

- READMEには現在の仕様・セットアップ・使い方・必要な制約を書く。変更履歴、作業日時、PR単位の経緯、単発の測定値やテスト成功記録を追記しない。
- 変更理由と実施した検証結果はPR・コミットにまとめる。
- 作業ログのMarkdownは明示的に依頼された場合だけ作成する。既存ドキュメントは履歴を積み上げず、現在の状態が分かるよう更新する。

## 検証と報告

変更した範囲に応じて、必要な検証を実行する。文書だけの変更では、内容・参照先・差分を確認する。

Pythonの変更は対象プロジェクトの `agent/` または `mcp/` で実行する。
MCP AppのHTMLは先に `npm --prefix mcp/ui ci --ignore-scripts` と `npm --prefix mcp/ui run build` で生成する。

```sh
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

フロントの変更は `app/` で実行する。

```sh
npm run typecheck
npm run build
```

- AG-UIの接続やイベントを変更した場合は、Pythonをfixtureモードで起動し、Next.js経由の `npm run smoke` も確認する。起動手順は `app/README.md` を参照する。
- `npm run smoke -- --live` は実際の推論APIを呼ぶ。外部API不要のテストと混同しない。
- 確認済み・未検証・仮定を分けて報告する。HTTP疎通、ブラウザ描画、モデルの回答品質、クラウド動作をそれぞれ区別する。

## Git運用と参照資料

- 変更を意味のある小さな単位に分け、日本語のメッセージでコミットする。
- コミット前に対象差分を確認する。pushはユーザーから依頼された範囲で行い、既存の履歴を強制的に上書きしない。
- セットアップと現状は [README.md](README.md)、[app/README.md](app/README.md)、[agent/README.md](agent/README.md) を読む。
