# 構造化データ探索エージェント PoC

自然言語で表形式データを検索・集計するローカルPoC。
Strands AgentsがPythonツールを呼び、DuckDBでParquetを読み取る。
Next.jsのチャットに回答を逐次表示し、検索・集計結果を別のイベントで届ける。

```text
Browser / Next.js + CopilotKit
  → AG-UI / FastAPI
    → Strands Agents → さくらAI Engine
      └─ Pythonツール → DuckDB → ローカルParquet
```

| ディレクトリ | 役割 |
| --- | --- |
| `app/` | Next.jsのチャット画面、CopilotKit Runtime、AG-UI接続。npmで管理 |
| `agent/` | PythonのCLI・AG-UIサーバー、検索・集計ツール。uvで管理 |
| `terraform/` | AgentCore Runtime V2・ECR・IAMと、Lambda＋API Gatewayのストリーミング中継 |

## セットアップ

Node.js（[.node-version](.node-version) のバージョン）、npm、Python 3.12、uvを用意する。
リポジトリ直下から実行する。

```sh
cd agent
uv sync --locked
uv run --locked explore prepare-sample
cd ../app
npm ci --ignore-scripts
cd ..
```

`prepare-sample` は架空の不動産取引360行を生成する。生成済みなら省略する。
地域名は実在するが、価格・面積・時期は架空であり、市場価格の判断には使えない。

## チャットを起動する

それぞれリポジトリ直下から、別々のターミナルで実行する。

```sh
# ターミナル1：外部API不要の接続検証モード
cd agent
uv run --locked explore-server --model fixture
```

```sh
# ターミナル2
cd app
npm run dev
```

<http://127.0.0.1:3000> を開く。終了は各ターミナルでCtrl+C。
fixtureモードは質問内容にかかわらず新宿区の年別集計を実行する固定シナリオで、
自然言語の理解やモデルの回答品質を検証するものではない。

さくらAI Engineで質問する場合は、[agentの接続設定](agent/README.md#さくらai-engineへの接続)を行い、
ターミナル1を次のコマンドに置き換える。

```sh
cd agent
uv run --locked --env-file .env explore-server
```

APIキーは `agent/.env` にだけ置く。質問・会話履歴・ツール結果の要約が推論APIへ送られる。
モデルの利用可否・無償枠は利用者のアカウントで確認する。

## 制約と詳細

対象は合成Parquet。実データ取り込み、S3対応、チャットの認証・会話の永続化は未実装。
ローカル単独利用を前提とし、モデルから任意SQLは受け付けない。AWS向け構成はfixture検証用。
結果は最大200行を保存し、画面へ最大20行、LLMへ最大3行のサンプルを渡す。

- [app：画面、AG-UI接続、HTTP疎通テスト](app/README.md)
- [agent：接続設定、CLI、ツール、実行制約、自動テスト](agent/README.md)
- [terraform：AgentCoreへの配備](terraform/README.md)
