# 技術調査・実現性評価

調査日: 2026-11-02。公式仕様とローカル実行を区別する。
作業先は空で、既存アプリ・IaC・README・AGENTS.md・Git管理はなかった。

## 判断

**ローカル構成を実装し、さくら実環境でツール実行・集計・ストリーミング回答が1質問成功した。**
StrandsとDuckDBの実コードによるローカル結合テストは通過した。
利用者が設定したモデルは `preview/Kimi-K2.7-Code`。`gpt-oss-120b` は未検証。
[疎通記録](SAKURA_SMOKE_RESULT.md) に単発測定と確認範囲を記載した。
AWS側にも必要な公式機能はあるため、構成を否定する仕様上の障害は現時点で見つかっていない。
ただし、本構成でのAWS配備・復元・中継を試しておらず、クラウド動作を確認済みとはしない。

## 確認済み／要検証／仮定

| 対象 | 確認済みの事実・根拠 | 要検証・リスク |
| --- | --- | --- |
| Strands | `strands-agents[openai]`、`from strands import Agent, tool`、`OpenAIModel(client_args=..., model_id=..., stream=...)`、`stream_async` が利用可能。固定した1.63.0でもimport・シグネチャ・実SDKの循環を確認。さくら実環境で1質問のツール・引数も確認 | 最新ドキュメントのAPIを過去版に流用しない。複数質問でのツール選択精度は未評価 |
| 接続先 | さくら公式は `https://api.ai.sakura.ad.jp/v1/chat/completions` を掲載。OpenAPIには `tools`, `tool_choice`, `stream` がある。`preview/Kimi-K2.7-Code` で実際のstream中tool callingと正常終了が1質問成功 | OpenAI互換は全パラメータの同等性を保証しない。他モデル、実環境の異常系、usageの記録/精度は未検証 |
| モデル・無償枠 | 公式料金表に `gpt-oss-120b` とChat completions月3,000リクエストの記載。無償/従量は別プランで自動切替なし。利用者が無償プランを確認し、設定した `preview/Kimi-K2.7-Code` の呼び出し3回が成功 | 契約・残枠をプログラムで照会してはいない。gpt-ossの枠をKimiに流用して見積もらない。RPM/同時実行制限の具体値は今回の一次情報で確定できず、未確認とする |
| Skills | 公式に `from strands import Agent, AgentSkills, Skill`、`AgentSkills(skills=...)`、`Agent(plugins=[...])` の説明。1.63.0でAgentSkillsのimportと初期化シグネチャを確認 | 実際のSKILL.mdロード/実行は未検証・未導入。SQLアクセス制御を担う機能ではない |
| AgentCore V2 | `platformVersion="V2"` を作成/更新時に指定。既定はV1。公式の対応リージョンに東京を含む5地域がある | デプロイ未実施。Terraform AWS providerのV2対応フィールドは未調査。リージョン/アカウントは未決定 |
| V2復元 | 公式は初期化後のスナップショットを復元。最初のhealthy pingまで120秒。作成/更新は数分でREADYを待つ | 期限付き認証・ソケット・乱数・時刻・DuckDB接続の復元後整合性は未検証。接続はリクエスト/操作内で作り直す方針を候補とする |
| Runtimeセッション | 公式ではセッションごとのmicroVM分離、既定のアイドル15分、最長8時間。終了後の同じIDは新環境になり得る | Runtimeのセッション維持はStrands会話の永続化を自動実装しない。ローカルPoCは1質問1Agent。永続セッションは未設計 |
| API Gateway | ストリーミング対応はREST API。`HTTP_PROXY`/`AWS_PROXY`、`responseTransferMode=STREAM` が対象。HTTP APIには適用しない | AWS・ブラウザを通したTTFB/チャンク遅延/切断動作は未計測 |
| Lambda統合 | `InvokeWithResponseStream` と `.../2021-11-15/functions/.../response-streaming-invocations` の統合URIが必要。通常のInvokeとは異なる | メタデータJSON + 8 null bytes + 本文という出力契約を守る必要。単にSSE文字列をreturnする実装では不十分 |
| DuckDB | 固定SQL・入力検証・バインド・許可パス・外部アクセス無効・設定ロックをローカル実行。別ファイル読取拒否/中断もテスト済み | memory_limitはOS上限ではない。大容量Parquet、S3、spill、プロセス隔離、実負荷時の並列性は未評価 |
| 結果分離 | ツール内部で上限付きデータを保存し別イベントへ投影。モデルには最大3行の要約だけを返す。実SDKが次のHTTPリクエストへ送る内容で確認 | 参照IDのHTTP取得、認証/所有権、TTL、全量取得、複数インスタンス間共有は未実装 |

Strandsの根拠:
[OpenAIModel API](https://strandsagents.com/docs/api/python/strands.models.openai/)、
[非同期ストリーミング](https://strandsagents.com/docs/user-guide/sdk/streaming/async-iterators/)、
[Skills](https://strandsagents.com/docs/user-guide/sdk/plugins/skills/)。
さくらの根拠:
[利用手順](https://manual.sakura.ad.jp/cloud/ai-engine/02-howto.html)、
[公式OpenAPI](https://manual.sakura.ad.jp/api/cloud/portal/openapis/ai-engine-inference-api.yaml)、
[料金・モデル](https://ai.sakura.ad.jp/sakura-ai/ai-engine/)、
[利用可能モデルの確認方法](https://manual.sakura.ad.jp/cloud/ai-engine/03-operation-guide.html)。
実装するAPIはChat Completionsであり、Responses APIへの同等性は仮定しない。

AWSの根拠:
[Runtime・V2・リージョン・セッション](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)、
[V2の復元時注意点](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-v2-optimize.html)、
[API Gatewayの制約](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode.html)、
[Lambda streaming統合の契約](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode-lambda.html)。
DuckDBの根拠:
[セキュリティ設定](https://duckdb.org/docs/preview/operations_manual/securing_duckdb/overview)、
[2.0設定一覧](https://duckdb.org/docs/2.0/configuration/overview)。
preview文書の記述だけには依存せず、採用した2.0.0で実際の設定適用をテストした。

## ストリーミング構成の評価

構成候補は引き継ぎどおり
`Next.js → REST API → Lambda streaming bridge → InvokeAgentRuntime → Strands`。
さくら向け推論APIはサーバー側に閉じ、APIキーをブラウザへ渡さない。
AgentCore呼び出しAPIの具体的なContent-Type/本文形式と、そのLambdaでの変換は次段階で確認する。
Lambdaの言語は未選定。Node.jsの標準streaming実装とPythonの実装方法を、
AgentCore応答の中継の容易さも含めて比較してから相談する。

公式のREST streaming上限は15分、Regional/privateのアイドル5分、edgeのアイドル30秒。
最初の10MB超は2MB/sの帯域制限があり、endpoint cache・VTLレスポンス変換等は非対応。
切断時もLambdaが動き続ける可能性がある。
これらは「中継すれば自動で低遅延になる」という保証ではない。
ブラウザまでの測定では、最初のヘッダー、最初のイベント、各イベント、終了時刻を分けて記録し、
heartbeat、逆圧、中断、タイムアウト、CORS、重複/欠落、終端を検証する。
AgentCoreの長時間セッションと単一HTTPストリームの上限も区別する。

## データ候補

| 候補 | 入手性・形式/容量 | 条件・列・探索タスク | 初期判断 |
| --- | --- | --- | --- |
| 合成不動産 | ローカル生成360行、約3KiBのParquet | 今回作った6列。外部データの許諾に依存せず、値の正解を固定できる。実際の表記揺れや欠損を代表しない | ユーザー了承のうえ、初手の配線/テストに採用 |
| 国交省 不動産情報ライブラリ | 公式にCSVダウンロード/APIの入口あり。地域・期間で絞る想定。今回は未取得で容量・実列・文字コードは未確認 | 日本語地名・取引時期・価格・面積による探索に適する見込み。利用規約・個別条件・出典/加工表示を確認し、取引価格と成約価格を混ぜない | 実データ第一候補。少地域/短期間のCSVで列・匿名化/丸め・欠損表現を確認後に取り込む |
| NYC Taxi | 公式が月別Parquetとデータ辞書を提供。今回未取得でファイル容量は未計測 | 時刻・距離・地域ID・料金等。大規模スキャンに適するが、日本語の条件解釈では国交省より課題が少ない見込み。精度/完全性の保証なし、年ごとの列追加あり。再配布条件の精査は未完了 | 性能試験の代替候補。今はダウンロードしない |
| 株価 | 提供元未選定、取得/API/容量/許諾とも未確認 | 調整後価格や企業行動、再配布・鮮度の確認が必要 | 今回は比較候補に留める |

国交省の根拠:
[CSV/APIの入口と出典表示](https://www.reinfolib.mlit.go.jp/help/contact/)、
[利用規約](https://www.reinfolib.mlit.go.jp/help/termsOfUse/)。
一部の他コンテンツには個別条件があるため、サイト全体を一律に自由再配布可とは扱わない。
NYCの根拠:
[TLCデータ・辞書・注意事項](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)。

## 最小構成と次の順序

1. **実装/検証済み:** `agent/` にuv管理のCLI、合成データ、DuckDBツール、モデル/UI投影、実SDK結合テスト。
2. **疎通済み:** 利用者が `.env` と無償プランを確認後、最大4推論API呼び出しの承認範囲で1質問を実行。
   実際は3回を消費し、スキーマ確認→年別集計→最終回答が成功した。
   モデル向けの投影内容はローカル実SDKの模擬HTTPテストで確認し、実APIへの送信本文は保存していない。
   非stream比較や追加モデル/質問の実API評価は、次の実施範囲を相談してから行う。
3. **相談して進める:** 国交省データの小サンプルを取得・正規化。列マッピング・出典表示・単位・欠損/丸めを確定。
4. **別の判断ゲート:** `app/` のNext.js UIとローカルHTTP/SSEアダプター。
   assistant-ui / AI SDK / 薄い独自UIを現行仕様で比較する。旧ADKアダプターは選定根拠にしない。
   必要ならUIを先にローカルで作って、クラウドより先にイベント統合を試す案を提案する。
5. **承認後のみ:** アカウント/リージョン/認証/費用とTerraform providerのV2対応を確認し、
   `terraform/` でAgentCore V2、次にREST API/Lambda bridgeを作る。復元とS3の測定を行う。
6. **任意:** Skills、Bedrock比較、評価セット。Bedrock呼び出しは別途課金承認が必要。

S3配置、永続セッション、認証製品、UIライブラリ、Lambda言語、AWSアカウント/リージョン、
HTTP結果取得APIは未確定。初期CLIでは1質問ごとにAgent・状態を作り、将来の複数ユーザーの
状態共有や復元を実装済みと扱わない。MCP化は検索ロジックを包む将来の選択肢であり、
今回そのサーバーやMCP Appsを実装する予定はない。
