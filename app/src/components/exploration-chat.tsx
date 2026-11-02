"use client";

import { CopilotChat, CopilotKitProvider, useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useRef, useState } from "react";
import { appPath } from "../lib/paths";
import { resultHistorySubscriber, type DataResult, type ResultRun } from "../lib/result-history";

const toolNames: Record<string, string> = {
  describe_dataset: "データ項目を確認",
  search_transactions: "条件に合う取引を検索",
  aggregate_transactions: "取引データを集計",
  compare_values: "差分・増減率を計算（MCP）",
};
const columnNames: Record<string, string> = {
  year: "年", municipality: "地域", quarter: "四半期", transaction_id: "取引ID",
  transaction_count: "件数", average_price_yen: "平均取引総額（円）",
  min_price_yen: "最小取引総額（円）", max_price_yen: "最大取引総額（円）",
  price_yen: "取引総額（円）", area_m2: "面積（㎡）",
  baseline: "基準値", current: "比較値", difference: "差分", percent_change: "増減率（%）",
};

function ChatWorkspace() {
  const { agent, isReady } = useAgent({ agentId: "explorer" });
  const [runs, setRuns] = useState<ResultRun[]>([]);
  const [error, setError] = useState("");
  const historyRef = useRef<HTMLDivElement>(null);
  const followResults = useRef(true);

  useEffect(() => {
    const history = resultHistorySubscriber(setRuns);
    const subscription = agent.subscribe({
      ...history,
      onRunStartedEvent: params => {
        setError("");
        return history.onRunStartedEvent?.(params);
      },
      onRunErrorEvent: params => {
        setError("処理に失敗しました。接続や実行上限を確認してください。");
        return history.onRunErrorEvent?.(params);
      },
      onRunFailed: params => {
        setError("接続に失敗しました。エージェントの起動状態を確認してください。");
        return history.onRunFailed?.(params);
      },
    });
    return () => subscription.unsubscribe();
  }, [agent]);

  useEffect(() => {
    if (followResults.current && historyRef.current) {
      historyRef.current.scrollTop = historyRef.current.scrollHeight;
    }
  }, [runs]);

  return <>
    {error && <div className="error-banner" role="alert">{error}</div>}
    <div className="exploration-workspace">
    <section className="chat-card" aria-label="チャット">
      <div className="chat-toolbar">
        <span className="toolbar-label"><span className={`status-dot ${isReady ? "connected" : ""}`} />
          {isReady ? "チャット" : "接続を準備中"}</span>
      </div>
      <CopilotChat
        agentId="explorer"
        className="explorer-chat"
        inspectorTools={false}
        welcomeScreen={false}
        input={{ showDisclaimer: false }}
        labels={{
          chatInputPlaceholder: "例：新宿区を年別に集計して、件数と平均取引総額を教えて",
          chatInputToolbarSendButtonLabel: "送信",
          chatInputToolbarStopButtonLabel: "停止",
          chatScrollToBottomLabel: "最新の回答へ",
          assistantMessageToolbarCopyMessageLabel: "回答をコピー",
          userMessageToolbarCopyMessageLabel: "質問をコピー",
          assistantMessageToolbarRegenerateLabel: "再実行",
          userMessageToolbarEditMessageLabel: "質問を編集",
        }}
        onError={() => setError("チャットに接続できません。エージェントの起動状態を確認してください。")}
      />
    </section>
    <section className="result-card" aria-label="ツールの実行結果">
      <div className="result-heading"><h2>ツールの実行結果</h2>
        {runs.length > 0 && <span className="small-note">{runs.length}件の質問</span>}</div>
      <div className="result-history" ref={historyRef} onScroll={event => {
        const panel = event.currentTarget;
        followResults.current = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 48;
      }} tabIndex={0} role="region" aria-label="実行結果の履歴">
      {runs.length === 0 ? <div className="empty-result">
        <span aria-hidden="true" className="table-symbol">▤</span>
        <p>結果はまだありません。</p>
      </div> : runs.map((run, index) => <article className="result-run" key={run.runId} data-status={run.status}>
        <div className="run-heading">
          <div><span className="run-number">質問 {index + 1}</span><h3>{run.question}</h3></div>
          <span className="run-status" role="status">{run.status === "running" ? "実行中" : run.status === "success" ? "完了" : run.status === "error" ? "失敗" : "中断"}</span>
        </div>
        {run.tools.length > 0 && <ol className="tool-progress" aria-label={`質問${index + 1}の処理の進捗`}>
          {run.tools.map(tool => <li key={tool.id} data-status={tool.status}>
            <span className="progress-icon">{tool.status === "success" ? "✓" : tool.status === "running" ? "◌" : "!"}</span>
            {toolNames[tool.name] ?? tool.name}
            <span className="small-note">{tool.status === "success" ? "完了" : tool.status === "running" ? "実行中" : "中断・失敗"}</span>
          </li>)}
        </ol>}
        {run.results.map(result => <ResultTable key={result.result_id} result={result}
          label={toolNames[run.tools.find(tool => tool.id === result.tool_call_id)?.name ?? ""] ?? "検索・集計結果"} />)}
        {run.results.length === 0 && <p className="run-placeholder">{run.status === "running"
          ? "検索・集計結果を待っています…" : "この質問の検索・集計結果はありません。"}</p>}
        {run.metrics && <div className="run-summary">ツール実行 {run.metrics.tool_calls}回</div>}
      </article>)}
      </div>
    </section>
    </div>
  </>;
}

function ResultTable({ result, label }: { result: DataResult; label: string }) {
  const columns = result.preview_rows.length ? Object.keys(result.preview_rows[0]) : [];
  return <div className="result-table" data-testid="data-result">
    <h4 className="result-tool-title">{label}</h4>
    <p className="result-count">該当 {result.total_count.toLocaleString("ja-JP")}
      {result.count_unit === "groups" ? "グループ" : "件"}
      <span className="small-note"> · {result.preview_rows.length}行を表示</span></p>
    {columns.length > 0 ? <div className="table-scroll"><table>
      <thead><tr>{columns.map(column => <th key={column}>{columnNames[column] ?? column}</th>)}</tr></thead>
      <tbody>{result.preview_rows.map((row, index) => <tr key={index}>
        {columns.map(column => <td key={column}>{typeof row[column] === "number"
          ? row[column].toLocaleString("ja-JP", { useGrouping: column !== "year" })
          : row[column] ?? "—"}</td>)}
      </tr>)}</tbody>
    </table></div> : <p>条件に合うデータはありませんでした。</p>}
    {(result.truncated || result.preview_truncated) && <p className="small-note">
      一部を表示しています。条件を絞り込んで確認してください。</p>}
  </div>;
}

export function ExplorationChat() {
  const [mode, setMode] = useState("connecting");
  useEffect(() => {
    fetch(appPath("/api/agent-status")).then(async response => {
      const status = await response.json();
      setMode(status.connected ? status.mode : "offline");
    }).catch(() => setMode("offline"));
  }, []);

  return <main className="page-shell">
    <header className="site-header">
      <a className="brand" href={appPath("/")} aria-label="データ探索室 ホーム"><span className="brand-mark" aria-hidden="true">▦</span>データ探索室</a>
      <div className="header-badges">
        <span className="environment-badge">POC</span>
        {mode === "fixture" && <span className="stub-badge"
          title="質問にかかわらず、新宿区の年別集計を実行します。外部APIは使用しません。">Stub APIモード</span>}
      </div>
    </header>
    <div className="dataset-line">360件 · 千代田区 / 新宿区 / 渋谷区 · 2023–2025年</div>
    {mode === "offline" && <div className="error-banner" role="alert">エージェントに接続できません。接続先の状態を確認してから再読み込みしてください。</div>}
    <CopilotKitProvider runtimeUrl={appPath("/api/copilotkit")} agentId="explorer" useSingleEndpoint={false} enableInspector={false}>
      <ChatWorkspace />
    </CopilotKitProvider>
    <footer className="site-footer">Strands + AG-UI + CopilotKit</footer>
  </main>;
}
