"use client";

import {
  CopilotChat,
  CopilotChatReasoningMessage,
  CopilotKitProvider,
  useAgent,
  useDefaultRenderTool,
} from "@copilotkit/react-core/v2";
import { type ComponentProps, useEffect, useRef, useState } from "react";
import { appPath } from "../lib/paths";
import { type DataResult, type ResultRun, resultHistorySubscriber } from "../lib/result-history";
import { McpAppResultView } from "./mcp-app-result";

const toolNames: Record<string, string> = {
  echo_text: "入力を返す（Pythonサンプル）",
  web_search: "Webを検索（Tavily）",
  web_fetch: "Webページを取得（Tavily）",
  aws___search_documentation: "AWSドキュメントを検索",
  aws___read_documentation: "AWSドキュメントを取得",
  aws___list_regions: "AWSリージョンを確認",
  aws___get_regional_availability: "AWSのリージョン対応を確認",
  microsoft_docs_search: "Microsoftドキュメントを検索",
  microsoft_docs_fetch: "Microsoftドキュメントを取得",
  microsoft_code_sample_search: "Microsoftのコード例を検索",
  describe_dataset: "データ項目を確認",
  search_office_market: "空室率・賃料を検索",
  aggregate_office_market: "空室率・賃料を集計",
  compare_values: "差分・増減率を計算（MCP）",
  show_office_market_dashboard: "市況ダッシュボードを表示（MCP Apps）",
};
const columnNames: Record<string, string> = {
  year: "年",
  month: "月",
  area: "地区",
  vacancy_rate_pct: "平均空室率（％）",
  rent_yen_per_tsubo: "平均賃料（円/坪）",
  month_count: "月数",
  mean_vacancy_rate_pct: "平均空室率の平均（％）",
  min_vacancy_rate_pct: "平均空室率の最小（％）",
  max_vacancy_rate_pct: "平均空室率の最大（％）",
  mean_rent_yen_per_tsubo: "平均賃料の平均（円/坪）",
  min_rent_yen_per_tsubo: "平均賃料の最小（円/坪）",
  max_rent_yen_per_tsubo: "平均賃料の最大（円/坪）",
  baseline: "基準値",
  current: "比較値",
  difference: "差分",
  percent_change: "増減率（%）",
};

function ReasoningHeader(props: ComponentProps<typeof CopilotChatReasoningMessage.Header>) {
  return (
    <CopilotChatReasoningMessage.Header
      {...props}
      label={
        props.isStreaming
          ? "考え中…"
          : props.elapsedSeconds === undefined
            ? "推論内容"
            : `推論 ${props.elapsedSeconds}秒`
      }
    />
  );
}

function ChatWorkspace({ sandboxUrl }: { sandboxUrl?: string }) {
  const { agent, isReady } = useAgent({ agentId: "explorer" });
  useDefaultRenderTool();
  const [runs, setRuns] = useState<ResultRun[]>([]);
  const [error, setError] = useState("");
  const historyRef = useRef<HTMLDivElement>(null);
  const followResults = useRef(true);

  useEffect(() => {
    const history = resultHistorySubscriber(setRuns);
    const subscription = agent.subscribe({
      ...history,
      onRunStartedEvent: (params) => {
        setError("");
        return history.onRunStartedEvent?.(params);
      },
      onRunErrorEvent: (params) => {
        setError("処理に失敗しました。接続や実行上限を確認してください。");
        return history.onRunErrorEvent?.(params);
      },
      onRunFailed: (params) => {
        setError("接続に失敗しました。エージェントの起動状態を確認してください。");
        return history.onRunFailed?.(params);
      },
    });
    return () => subscription.unsubscribe();
  }, [agent]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: 結果が増えたときに末尾へ追従するためrunsを契機にする
  useEffect(() => {
    if (followResults.current && historyRef.current) {
      historyRef.current.scrollTop = historyRef.current.scrollHeight;
    }
  }, [runs]);

  return (
    <>
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      <div className="exploration-workspace">
        <section className="chat-card" aria-label="チャット">
          <div className="chat-toolbar">
            <span className="toolbar-label">
              <span className={`status-dot ${isReady ? "connected" : ""}`} />
              {isReady ? "チャット" : "接続を準備中"}
            </span>
          </div>
          <CopilotChat
            agentId="explorer"
            className="explorer-chat"
            inspectorTools={false}
            welcomeScreen={false}
            messageView={{ toolCallDisplay: "line", reasoningMessage: { header: ReasoningHeader } }}
            input={{ showDisclaimer: false }}
            labels={{
              chatInputPlaceholder:
                "例：千代田区の2020年以降を年別に集計して、平均空室率と平均賃料を教えて",
              chatInputToolbarSendButtonLabel: "送信",
              chatInputToolbarStopButtonLabel: "停止",
              chatScrollToBottomLabel: "最新の回答へ",
              assistantMessageToolbarCopyMessageLabel: "回答をコピー",
              userMessageToolbarCopyMessageLabel: "質問をコピー",
              assistantMessageToolbarRegenerateLabel: "再実行",
              userMessageToolbarEditMessageLabel: "質問を編集",
            }}
            onError={() =>
              setError("チャットに接続できません。エージェントの起動状態を確認してください。")
            }
          />
        </section>
        <section className="result-card" aria-label="ツールの実行結果">
          <div className="result-heading">
            <h2>ツールの実行結果</h2>
            {runs.length > 0 && <span className="small-note">{runs.length}件の質問</span>}
          </div>
          <section
            className="result-history"
            ref={historyRef}
            onScroll={(event) => {
              const panel = event.currentTarget;
              followResults.current =
                panel.scrollHeight - panel.scrollTop - panel.clientHeight < 48;
            }}
            // biome-ignore lint/a11y/noNoninteractiveTabindex: スクロール領域をキーボードで操作できるようにする
            tabIndex={0}
            aria-label="実行結果の履歴"
          >
            {runs.length === 0 ? (
              <div className="empty-result">
                <span aria-hidden="true" className="table-symbol">
                  ▤
                </span>
                <p>結果はまだありません。</p>
              </div>
            ) : (
              runs.map((run, index) => (
                <details className="result-run" key={run.runId} data-status={run.status} open>
                  <summary className="run-heading">
                    <span className="run-heading-text">
                      <span className="run-number">質問 {index + 1}</span>
                      <span className="run-question">{run.question}</span>
                    </span>
                    <span className="run-status" role="status">
                      {run.status === "running"
                        ? "実行中"
                        : run.status === "success"
                          ? "完了"
                          : run.status === "error"
                            ? "失敗"
                            : "中断"}
                    </span>
                  </summary>
                  {run.tools.length > 0 && (
                    <ol className="tool-progress" aria-label={`質問${index + 1}の処理の進捗`}>
                      {run.tools.map((tool) => (
                        <li key={tool.id} data-status={tool.status}>
                          <span className="progress-icon">
                            {tool.status === "success"
                              ? "✓"
                              : tool.status === "running"
                                ? "◌"
                                : "!"}
                          </span>
                          {toolNames[tool.name] ?? tool.name}
                          <span className="small-note">
                            {tool.status === "success"
                              ? "完了"
                              : tool.status === "running"
                                ? "実行中"
                                : "中断・失敗"}
                          </span>
                        </li>
                      ))}
                    </ol>
                  )}
                  {run.results.map((result) =>
                    result.app ? (
                      <McpAppResultView
                        key={result.result_id}
                        app={result.app}
                        sandboxUrl={sandboxUrl}
                      />
                    ) : (
                      <ResultTable
                        key={result.result_id}
                        result={result}
                        label={
                          toolNames[
                            run.tools.find((tool) => tool.id === result.tool_call_id)?.name ?? ""
                          ] ?? "検索・集計結果"
                        }
                      />
                    ),
                  )}
                  {run.results.length === 0 && (
                    <p className="run-placeholder">
                      {run.status === "running"
                        ? "検索・集計結果を待っています…"
                        : "この質問の検索・集計結果はありません。"}
                    </p>
                  )}
                  {run.status === "success" && (
                    <div className="run-summary">ツール実行 {run.tools.length}回</div>
                  )}
                </details>
              ))
            )}
          </section>
        </section>
      </div>
    </>
  );
}

function ResultTable({ result, label }: { result: DataResult; label: string }) {
  const columns = result.preview_rows.length ? Object.keys(result.preview_rows[0]) : [];
  return (
    <div className="result-table" data-testid="data-result">
      <h4 className="result-tool-title">{label}</h4>
      <p className="result-count">
        該当 {result.total_count.toLocaleString("ja-JP")}
        {result.count_unit === "groups" ? "グループ" : "件"}
        <span className="small-note"> · {result.preview_rows.length}行を表示</span>
      </p>
      {columns.length > 0 ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{columnNames[column] ?? column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.preview_rows.map((row, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: プレビュー行は一意なIDを持たず、表示中に並び替えない
                <tr key={index}>
                  {columns.map((column) => (
                    <td key={column}>
                      {typeof row[column] === "number"
                        ? row[column].toLocaleString("ja-JP", { useGrouping: column !== "year" })
                        : (row[column] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>条件に合うデータはありませんでした。</p>
      )}
      {(result.truncated || result.preview_truncated) && (
        <p className="small-note">一部を表示しています。条件を絞り込んで確認してください。</p>
      )}
    </div>
  );
}

export function ExplorationChat({ sandboxUrl }: { sandboxUrl?: string }) {
  const [mode, setMode] = useState("connecting");
  useEffect(() => {
    fetch(appPath("/api/agent-status"))
      .then(async (response) => {
        const status = await response.json();
        setMode(status.connected ? status.mode : "offline");
      })
      .catch(() => setMode("offline"));
  }, []);

  return (
    <main className="page-shell">
      <header className="site-header">
        <a className="brand" href={appPath("/")} aria-label="データ探索室 ホーム">
          <span className="brand-mark" aria-hidden="true">
            ▦
          </span>
          データ探索室
        </a>
        <div className="header-badges">
          <span className="environment-badge">POC</span>
          {mode === "fixture" && (
            <span
              className="stub-badge"
              title="質問にかかわらず固定シナリオを実行します。外部のモデルAPIは使用しません。"
            >
              Stub APIモード
            </span>
          )}
        </div>
      </header>
      <div className="dataset-line">
        オフィス市況 · 東京ビジネス地区・都心5区 · 月次の平均空室率・平均賃料
      </div>
      {mode === "offline" && (
        <div className="error-banner" role="alert">
          エージェントに接続できません。接続先の状態を確認してから再読み込みしてください。
        </div>
      )}
      <CopilotKitProvider
        runtimeUrl={appPath("/api/copilotkit")}
        agentId="explorer"
        useSingleEndpoint={false}
        enableInspector={false}
      >
        <ChatWorkspace sandboxUrl={sandboxUrl} />
      </CopilotKitProvider>
      <footer className="site-footer">Strands + AG-UI + CopilotKit</footer>
    </main>
  );
}
