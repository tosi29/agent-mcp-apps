# app — Next.js + CopilotKit

データ探索用のチャット。左に会話、右にツールの実行状況と検索・集計結果を表示する。
結果は質問ごとに右側の履歴へ追加し、ページを開いている間は過去の結果も残す。左右は個別にスクロールでき、狭い画面では上下に並ぶ。
ローカルまたはWeb Adapterを使うLambdaで動かす。
Node.jsのバージョンは [../.node-version](../.node-version)、依存関係は
[package.json](package.json) と [package-lock.json](package-lock.json) で管理する。

```text
Browser / CopilotKit React v2
  → Next.js /api/copilotkit/*（CopilotKit TypeScript Runtime v2）
    → HttpAgent / AG-UI SSE
      → Python /invocations → Strands → さくらAI Engine
                                 → MCPサーバー → DuckDB
```

CopilotKit RuntimeはNext.js内で動く。CopilotKitのクラウド契約やAPIキーは不要。
推論APIキーはPython側にだけ置き、Next.jsやブラウザへ渡さない。

## 起動

[ルートのセットアップ](../README.md#セットアップ)でPythonの依存と合成データを用意する。
以下はそれぞれリポジトリ直下から、別々のターミナルで実行する。

```sh
# ターミナル1：MCPサーバー
cd mcp
uv run --locked explore-mcp
```

```sh
# ターミナル2：モデルAPI不要の固定シナリオ
cd agent
uv run --locked explore-server --model fixture --mcp-url http://127.0.0.1:8001/mcp
```

```sh
# ターミナル3
cd app
npm ci --ignore-scripts
NEXT_PUBLIC_MCP_APPS_SANDBOX_URL=http://127.0.0.1:3001/sandbox npm run dev
```

```sh
# ターミナル4：MCP Appsの別オリジンsandbox
cd app
npm run dev:sandbox
```

<http://127.0.0.1:3000> を開く。MCPは127.0.0.1:8001、Pythonは127.0.0.1:8000、Next.jsは127.0.0.1:3000で待ち受ける。
終了は各ターミナルでCtrl+C。ポートが使用中なら、既存プロセスを確認してから起動する。

さくらを使う場合は、[agentの接続設定](../agent/README.md#さくらai-engineへの接続)を行い、
ターミナル2のコマンドを `uv run --locked --env-file .env explore-server --mcp-url http://127.0.0.1:8001/mcp` に変更する。
質問送信と実API用の疎通テストは推論APIを呼び出す。

本番ビルドで起動する場合は、開発サーバーを停止し、`app/` で実行する。

```sh
npm run build
npm run start
```

## 設定

通常のチャットのローカル接続では、Next.js側の環境ファイルは不要。
接続先を変更する場合のみ `.env.example` を `.env.local` にコピーし、`AGENT_URL` を設定する。
既定値は `http://127.0.0.1:8000/invocations`。localhostまたは127.0.0.1のHTTPだけを許可する。

AgentCoreへ直接接続する場合は、サーバー側に `AGENT_RUNTIME_ARN` を設定する。`AGENT_URL` より優先する。
東京リージョンのRuntimeに接続し、AWS認証は標準チェーンを使う。Lambdaでは実行ロールから取得する。
`InvokeAgentRuntime` と `GetAgentRuntime` の権限が必要。接続モードはRuntimeの `EXPLORER_MODEL_MODE` から取得する。
モードが未設定なら `unknown` とし、fixtureとみなさない。

## MCP Appsの表示

「新宿区の年別ダッシュボードを表示して」と質問すると、MCPが提供するHTMLを右ペインに表示する。
平均取引総額・取引件数を切り替えられる。fixtureモードではこの語句に対応する固定シナリオを実行する。
元の検索結果表と同様に質問ごとの履歴へ残す。

ホストには公式 `@modelcontextprotocol/ext-apps` の `AppBridge` を使う。
MCPから取得したHTMLを直接Next.jsのDOMへ挿入せず、別オリジンのsandbox proxyと、その内側のiframeで描画する。
`NEXT_PUBLIC_MCP_APPS_SANDBOX_URL` はブラウザに公開されるURLであり、秘密情報を含めない。
クラウドではTerraformが `MCP_APPS_SANDBOX_URL` をLambdaの実行時環境変数へ自動設定する。
サーバーがリクエストごとに画面へ渡す公開URLであり、APIキー等を含めない。実行時指定を優先する。
未設定なら設定不足を表示する。画面と同じオリジンは拒否し、クラウドではHTTPSが必要。

ローカルproxyは `npm run dev:sandbox` で127.0.0.1:3001の `/sandbox` を提供する。
ホストとして127.0.0.1:3000・localhost:3000を許可する。`APP_ORIGIN` 指定時はそのOriginだけに制限する。
親・子ウィンドウのsourceとoriginを照合し、CSPで外部通信・外部アセット・フォーム・追加iframeを禁止する。
proxy自身は認証情報や業務データの取得APIを持たず、ホストからHTMLとツール結果を受け取る。
ホストはAppからのツール実行・チャット送信・モデルコンテキスト更新・外部リンクを許可しない。
UI用HTMLを含むAG-UIイベントに対応するため、AgentCoreからの中継上限は1イベント2MiB・応答全体8MiB。
これはアプリケーション側の受信ガードであり、AWSやMCPの仕様上限ではない。

クラウドでは専用API Gatewayの `GET /poc/sandbox` を既存Lambdaへ接続し、Next.jsの `/sandbox` から配信する。
チャットとsandboxは別オリジンで、同じ `allowed_source_cidrs` に制限する。
追加のLambdaや起動・ビルドスクリプトは使わず、既存の `npm run build:lambda` でZIPを作る。
`APP_ORIGIN` を親画面の許可リストとCSPに使い、未設定・不正な値では `/sandbox` は503を返す。
クラウドのAPIはこのGETだけを公開し、チャットAPIや他のパスを公開しない。
`MCP_APPS_SANDBOX_URL` を使う場合、sandbox URLの変更だけならZIPの再ビルドは不要。
`NEXT_PUBLIC_*` で指定する場合はビルド時に固定されるため、配備先URLを決めてからLambda用ZIPを作り直す。
ZIPビルド時も `NEXT_PUBLIC_MCP_APPS_SANDBOX_URL` を環境変数で渡すと、ビルドスクリプトがDockerへ引き継ぐ。

MCP Appsの通信を含むHTTP疎通は `npm run smoke -- --apps` で確認する。
これはブラウザ描画の検証ではない。画面ではiframeの表示・指標切り替え・履歴の開閉を確認する。

## Lambdaへの配備

[Terraformの配備手順](../terraform/README.md)に従う。API Gatewayが画面とチャットAPIを同じOriginで配信し、
Web AdapterがHTTPをNext.jsのstandaloneサーバーへ渡す。Next.jsからAgentCoreを直接呼ぶ。

Lambda用ZIPは `Dockerfile.lambda` でLinux ARM64向けにビルドする。Web Adapterのreadiness確認は
`/api/health` を使い、起動確認でエージェントを実行しない。
ブラウザ向けURLの接頭辞 `NEXT_PUBLIC_BASE_PATH=/poc` をビルド時に設定する。
API GatewayがLambdaへ渡すパスからステージ名を除くため、Next.jsのルート自体は `/` に保ち、
JS/CSSには `assetPrefix`、画面内のAPI・ホームURLには `appPath()` で接頭辞を付ける。
静的ファイルを `public/` に追加する場合も、画面からの参照に `appPath()` を使う。

`APP_ORIGIN` にはAPI Gatewayの公開Originを設定し、それ以外のOriginからのチャットAPI呼び出しを拒否する。
ブラウザのアクセス制限はAPI Gatewayの送信元IPポリシーで行う。ユーザーごとの認証は未実装。

## 画面の確認

質問例：「項目を確認してから、新宿区を年別に集計し、件数と平均取引総額を教えて」

- 回答文が逐次表示され、完了後に再び送信できる。
- ツールの実行状況と、回答文から独立した結果表が右側に表示される。
- 続けて質問すると、前の結果を残したまま新しい結果が下へ追加される。過去の結果を読んでいる間はスクロール位置を維持する。
- 合成データの年別集計は2023〜2025年の3行で、各年40件・平均42,500,000円。
- 停止・エラー表示と、狭い画面での入力・表の横スクロールを確認する。

fixtureモードは固定シナリオで動く。「ダッシュボード」「グラフ」を含む場合だけApps表示に切り替わる。
合成データの値は、実際の市場価格を示すものではない。

## テスト

`app/` で型チェックとビルドを実行する。

```sh
npm run typecheck
npm test
npm run build
```

MCPを起動し、Pythonを `--model fixture --mcp-url http://127.0.0.1:8001/mcp`、
Next.jsを開発または本番モードで起動した状態でHTTP疎通を確認する。

```sh
npm run smoke
```

配備先のHTTP経路を確認する場合は、末尾 `/poc/` まで含むURLを指定する。

```sh
SMOKE_URL=https://example.execute-api.ap-northeast-1.amazonaws.com/poc/ npm run smoke
```

Next.js RuntimeからPythonツールまでを通し、静的ファイルの取得、ストリーム、独立した結果イベント、
合成データの期待値、正常終端、テレメトリ無効設定を検査する。
ブラウザ描画とモデルの推論品質は対象外。

実APIで同じ経路を試す場合は、Pythonをさくらモードで起動して明示的に指定する。
1質問で複数回のモデルAPI呼び出しを消費する。回数の上限はなく、全体のタイムアウトは300秒。

```sh
npm run smoke -- --live
```

AWS側がさくらモードの場合は `SMOKE_URL` と `-- --live` を併用する。実API検証は利用者の許可後に実行する。
実モデルでは応答が短時間で完了する場合があるため、固定200ms間隔の検査はfixtureだけに適用する。

指定とバックエンドのモードが一致しない場合は、推論前に停止する。
結果はGit除外対象の `agent/results/agui-<mode>-smoke.json` に保存する。

## イベントと履歴

標準AG-UIイベントに加え、次の `CUSTOM` イベントを受け取る。

| name | 用途 |
| --- | --- |
| `data_result` | result_id / tool_call_id、件数、最大20行のプレビュー |
| `tool_status` | ツール実行の成功・失敗 |

`TOOL_CALL_END` は引数生成の終端で、実行完了は `tool_status` で扱う。
プレビューはrun IDごとにReactの画面状態へ保持し、共有stateや会話メッセージへ追加しない。
画面の結果履歴はリロードでリセットする。実行失敗・中断時も、それまでに取得した結果は残す。
後続の質問で会話を再送するときも、画面用プレビューをモデルへ送り直さない。
モデルへ返すツール結果は件数・最大3行のサンプル・参照ID。

会話はInMemoryAgentRunnerに一時保持する。上限は10スレッド、各5run、保持済みイベント約8MB。
実行中イベント全体の厳密なメモリ上限ではない。
会話が長くなった場合はページを再読み込みして新しい会話を始める。
認証・永続化・ユーザーごとの履歴管理は未実装。

## テレメトリ

`npm run dev/build/start/typecheck` は `NEXT_TELEMETRY_DISABLED=1`、
`COPILOTKIT_TELEMETRY_DISABLED=true`、`DO_NOT_TRACK=1` を設定する。
`.npmrc` の `ignore-scripts=true` で依存のインストールスクリプトも無効にする。
`DO_NOT_TRACK` は対応ライブラリが尊重する設定で、外部通信全体の遮断機能ではない。
さくらへの質問・会話履歴・ツール結果の要約送信は推論に必要な別経路。
仕様は [Next.js](https://nextjs.org/telemetry) と [CopilotKit](https://docs.copilotkit.ai/telemetry) を参照。

## 依存関係の互換性

CopilotKit 1.83.0は `@ag-ui/client` 1.0.2を固定参照しており、直接依存の1.0.3と混在すると
`HttpAgent` と `AbstractAgent` のprivateメンバーの宣言元が異なるため型エラーになる。
`overrides` に `$@ag-ui/client` を指定し、間接依存のクライアントも直接依存と同じ版に揃える。
全AG-UIパッケージの一括上書きではない。更新時は型チェック・ビルド・fixture疎通で互換性を確認する。
Next.jsの標準CLI型チェックでTypeScript 7を使用する。
仕様は [npm公式ドキュメント](https://docs.npmjs.com/cli/v11/configuring-npm/package-json/#overrides) を参照。
