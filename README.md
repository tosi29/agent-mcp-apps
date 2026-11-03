# 構造化データ探索エージェント PoC

自然言語で表形式データを検索・集計するPoC。
Strands AgentsがMCPの探索ツールを呼び、MCPサーバー内のDuckDBでParquetを読み取る。
Next.jsのチャットに回答を逐次表示し、検索・集計結果を別のイベントで届ける。
クラウドではAPI GatewayからWeb Adapter＋Next.jsのLambdaへ接続し、Next.jsがAgentCoreを呼び出す。

```text
Browser / Next.js + CopilotKit
  → AG-UI / FastAPI
    → Strands Agents → さくらAI Engine
      ├─ MCPツール → DuckDB → ローカルParquet
      └─ Pythonツール → echo_text（接続検証サンプル）
```

| ディレクトリ | 役割 |
| --- | --- |
| `app/` | Next.jsのチャット画面、CopilotKit Runtime、AG-UI接続。npmで管理 |
| `agent/` | Strands・CLI・AG-UIサーバー、Pythonツールのechoサンプル。uvで管理 |
| `mcp/` | スキーマ確認・検索・集計・数値比較のMCPとDuckDB。uvで管理 |
| `terraform/` | AgentCore Runtime V2・ECR・IAMと、API Gateway＋Web Adapter＋Next.jsのLambda配備 |

## セットアップ

Node.js（[.node-version](.node-version) のバージョン）、npm、Python 3.12、uvを用意する。
リポジトリ直下から実行する。

```sh
cd mcp
uv sync --locked
uv run --locked explore-mcp prepare-sample
cd ../agent
uv sync --locked
cd ../app
npm ci --ignore-scripts
cd ..
```

`prepare-sample` は架空の不動産取引360行を生成する。生成済みなら省略する。
地域名は実在するが、価格・面積・時期は架空であり、市場価格の判断には使えない。

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
npm run dev
```

<http://127.0.0.1:3000> を開く。終了は各ターミナルでCtrl+C。
fixtureモードは質問内容にかかわらず新宿区の年別集計を実行する固定シナリオで、
自然言語の理解やモデルの回答品質を検証するものではない。

さくらAI Engineで質問する場合は、[agentの接続設定](agent/README.md#さくらai-engineへの接続)を行い、
ターミナル2を次のコマンドに置き換える。

```sh
cd agent
uv run --locked --env-file .env explore-server --mcp-url http://127.0.0.1:8001/mcp
```

ローカルのAPIキーは `agent/.env` に置く。AWSでは事前作成したParameter StoreのSecureString名を指定する。
質問・会話履歴・ツール結果の要約が推論APIへ送られる。
モデルの利用可否・無償枠は利用者のアカウントで確認する。

## 制約と詳細

探索・比較4ツールはMCPで公開する。MCP未接続時に利用できる通常のPythonツールはecho_textのみ。
構成と起動方法は [mcp/README.md](mcp/README.md) を参照。MCP Appsは使用しない。

対象は合成Parquet。実データ取り込み、S3対応、チャットの認証・会話の永続化は未実装。
モデルから任意SQLは受け付けない。AWSでは送信元IPを制限し、既定はfixture、SSM参照を設定するとさくらを使用する。
結果はMCP側に最大200行を一時保存し、画面へ最大20行、LLMへ最大3行のサンプルを渡す。

- [app：画面、AG-UI接続、HTTP疎通テスト](app/README.md)
- [agent：接続設定、CLI、ツール、実行制約、自動テスト](agent/README.md)
- [terraform：AgentCoreへの配備](terraform/README.md)
