# 構造化データ探索エージェント PoC

自然言語で表形式データを検索・集計するPoC。
対象は東京都心のオフィス市況（地区別・月次の平均空室率と平均賃料）。
Strands AgentsがMCPの探索ツールを呼び、MCPサーバー内のDuckDBでParquetを読み取る。
Next.jsのチャットに回答を逐次表示し、検索・集計結果を別のイベントで届ける。
クラウドではAPI GatewayからWeb Adapter＋Next.jsのLambdaへ接続し、Next.jsがAgentCoreを呼び出す。

```text
Browser / Next.js + CopilotKit
  → AG-UI / FastAPI
    → Strands Agents → さくらAI Engine
      ├─ MCPツール → DuckDB → ローカルParquet
      ├─ Pythonツール → echo_text（接続検証サンプル）、web_search・web_fetch（任意・Tavily）
      └─ リモートMCP（任意） → AWS Knowledge・Microsoft Learnの公開ドキュメント
```

| ディレクトリ | 役割 |
| --- | --- |
| `app/` | Next.jsのチャット画面、CopilotKit Runtime、AG-UI接続。npmで管理 |
| `agent/` | Strands・AG-UIサーバー、Pythonツールのechoサンプル。uvで管理 |
| `mcp/` | スキーマ確認・検索・集計・数値比較のMCP、MCP Appsのダッシュボード、DuckDB。uvで管理（`mcp/ui/` はnpm） |
| `terraform/` | AgentCore Runtime V2・ECR・IAMと、API Gateway＋Web Adapter＋Next.jsのLambda配備 |

## セットアップ

Node.js（[.node-version](.node-version) のバージョン）、npm、Python 3.12、uvを用意する。
リポジトリ直下から実行する。

```sh
npm --prefix mcp/ui ci --ignore-scripts
npm --prefix mcp/ui run build
cd mcp
uv sync --locked
uv run --locked explore-mcp prepare-sample
cd ../agent
uv sync --locked
cd ../app
npm ci --ignore-scripts
cd ..
```

`prepare-sample` は架空の月次データ216行（6地区×2023〜2025年）を `mcp/data/office-market.parquet` に生成する。
地区名は実在するが、空室率・賃料は架空であり、市況の判断には使えない。生成済みなら省略する。

実データを使う場合は、公表元のサイトから東京ビジネス地区の月次Excel（地区別の平均空室率・平均賃料）を
手動でダウンロードし、`mcp/` で次を実行する。同じパスのParquetを置き換える。

```sh
uv run --locked explore-mcp import-excel ダウンロードしたファイル.xlsx
```

表の形式（地区名・項目名・年月）を検査し、値と項目名は変更せずに格納する。
プログラムによる自動取得は行わない。実データ（`mcp/data/`）はコミットしない。
Parquetには合成か実データかの印を持たせ、ツール結果の `synthetic` で区別する。

## チャットを起動する

それぞれリポジトリ直下から、別々のターミナルで実行する。

```sh
# ターミナル1：MCPサーバー
cd mcp
uv run --locked explore-mcp
```

```sh
# ターミナル2：モデルAPI不要の接続検証モード
cd agent
uv run --locked explore-server --model fixture --mcp-url http://127.0.0.1:8001/mcp
```

```sh
# ターミナル3
cd app
NEXT_PUBLIC_MCP_APPS_SANDBOX_URL=http://127.0.0.1:3001/sandbox npm run dev
```

```sh
# ターミナル4：MCP Appsの別オリジンsandbox
cd app
npm run dev:sandbox
```

<http://127.0.0.1:3000> を開く。終了は各ターミナルでCtrl+C。
fixtureモードは千代田区の2023〜2025年の年別集計を実行する固定シナリオで、
自然言語の理解やモデルの回答品質を検証するものではない。
「ダッシュボード」または「グラフ」を含む質問では、MCP Apps表示用の固定シナリオに切り替わる。

さくらAI Engineで質問する場合は、[agentの接続設定](agent/README.md#さくらai-engineへの接続)を行い、
ターミナル2を次のコマンドに置き換える。

```sh
cd agent
uv run --locked --env-file .env explore-server --mcp-url http://127.0.0.1:8001/mcp
```

ローカルのAPIキーは `agent/.env` に置く。AWSでは事前作成したParameter StoreのSecureString名を指定する。
質問・会話履歴・ツール結果の要約が推論APIへ送られる。
TavilyのAPIキーを設定した場合はWeb検索とWebページの取得が有効になり、検索クエリと取得するURLがTavilyへ送られる。詳細は [Web検索](agent/README.md#web検索tavily) を参照。
モデルの利用可否・無償枠は利用者のアカウントで確認する。

## 制約と詳細

エージェントとMCPのログ・トレース・メトリクスは有効。
通常のローカル起動ではstderr、AgentCoreではADOT経由でCloudWatchへ出す。
質問・回答・ツール引数・結果も記録対象。詳細は [ログ設定](agent/README.md#ログとテレメトリ) を参照。

AWS向けのビルド・pushは [TerraformのREADME](terraform/README.md#ビルド) を参照。
Lambda用ZIPは `npm --prefix app run build:lambda`、エージェント・MCP両方のECR pushは
`node scripts/push-images.mjs all` で実行する。片方なら引数を `agent` または `mcp` にする。
ECRスクリプトはダイジェストのJSONを更新する。配備は別途plan・applyで行う。

探索・比較4ツールはMCPで公開する。MCP未接続時に利用できる通常のPythonツールはecho_textと、キー設定時のweb_search・web_fetch。
加えて `show_office_market_dashboard` がMCP AppsのUIを提供する。構成と起動方法は [mcp/README.md](mcp/README.md) を参照。
クラウドのsandboxは専用API Gatewayの `/poc/sandbox` から配信する。
チャットと同じNext.js Lambdaを共用し、別オリジンと同じ送信元IP制限を使う。
URLはTerraformがLambdaへ自動設定する。配備は [TerraformのREADME](terraform/README.md#mcp-appsのsandbox配備) を参照。

ローカルでは合成データと、手動で取得した実データのExcelを変換したParquetを使える。
AgentCore向けイメージには合成データだけを含める。S3対応、チャットの認証・会話の永続化は未実装。
実データを使うと、質問・ツール結果の要約（最大3行の抜粋を含む）が推論APIへ送られる。
モデルから任意SQLは受け付けない。AWSでは送信元IPを制限し、SSMのキーでさくらを使用する。fixtureはローカル専用。
結果はMCP側に最大200行を一時保存し、画面へ最大20行、LLMへ最大3行のサンプルを渡す。

- [app：画面、AG-UI接続、HTTP疎通テスト](app/README.md)
- [agent：接続設定、ツール、実行制約、自動テスト](agent/README.md)
- [mcp：探索ツール、MCP Apps、検索と結果の制約](mcp/README.md)
- [terraform：AgentCoreへの配備](terraform/README.md)
