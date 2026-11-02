"use client";

import { CopilotChat, CopilotKitProvider, useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useState } from "react";

type Row = Record<string, string | number | null>;
type Result = {
  result_id: string;
  tool_call_id: string;
  total_count: number;
  count_unit: string;
  returned_count: number;
  truncated: boolean;
  preview_truncated: boolean;
  preview_rows: Row[];
};
type ToolProgress = { id: string; name: string; status: string };
const toolNames: Record<string, string> = {
  describe_dataset: "データ項目を確認",
  search_transactions: "条件に合う取引を検索",
  aggregate_transactions: "取引データを集計",
};
const columnNames: Record<string, string> = {
  year: "年", municipality: "地域", quarter: "四半期", transaction_id: "取引ID",
  transaction_count: "件数", average_price_yen: "平均取引総額（円）",
  min_price_yen: "最小取引総額（円）", max_price_yen: "最大取引総額（円）",
  price_yen: "取引総額（円）", area_m2: "面積（㎡）",
};

function ChatWorkspace() {
  const { agent, isReady } = useAgent({ agentId: "explorer" });
  const [tools, setTools] = useState<ToolProgress[]>([]);
  const [results, setResults] = useState<Result[]>([]);
  const [error, setError] = useState("");
  const [metrics, setMetrics] = useState<{ model_calls: number; tool_calls: number } | null>(null);

  useEffect(() => {
    const subscription = agent.subscribe({
      onRunStartedEvent: () => {
        setTools([]); setResults([]); setMetrics(null); setError("");
      },
      onToolCallStartEvent: ({ event }) => {
        setTools(previous => [...previous, {
          id: event.toolCallId, name: event.toolCallName, status: "running",
        }]);
      },
      onCustomEvent: ({ event }) => {
        if (event.name === "data_result") {
          const value = event.value as Result;
          if (typeof value?.result_id === "string" && Array.isArray(value.preview_rows)) {
            setResults(previous => [...previous.filter(r => r.result_id !== value.result_id), value]);
          }
        } else if (event.name === "tool_status") {
          const value = event.value as { tool_call_id: string; status: string };
          setTools(previous => previous.map(tool => tool.id === value.tool_call_id
            ? { ...tool, status: value.status } : tool));
        } else if (event.name === "run_metrics") {
          setMetrics(event.value as { model_calls: number; tool_calls: number });
        }
      },
      onRunErrorEvent: () => setError("処理に失敗しました。接続や実行上限を確認してください。"),
      onRunFailed: () => setError("接続に失敗しました。エージェントの起動状態を確認してください。"),
      onRunFinalized: () => setTools(previous => previous.map(tool =>
        tool.status === "running" ? { ...tool, status: "stopped" } : tool)),
    });
    return () => subscription.unsubscribe();
  }, [agent]);

  return <>
    <section className="chat-card" aria-label="データ探索チャット">
      <div className="chat-toolbar">
        <span className="toolbar-label"><span className={`status-dot ${isReady ? "connected" : ""}`} />
          {isReady ? "探索チャット" : "接続を準備中"}</span>
        <span className="session-note">履歴は一時保存・再起動でリセット</span>
      </div>
      <CopilotChat
        agentId="explorer"
        className="explorer-chat"
        inspectorTools={false}
        welcomeScreen={false}
        labels={{
          chatInputPlaceholder: "例：新宿区を年別に集計して、件数と平均取引総額を教えて",
          chatInputToolbarSendButtonLabel: "送信",
          chatInputToolbarStopButtonLabel: "停止",
          chatScrollToBottomLabel: "最新の回答へ",
          assistantMessageToolbarCopyMessageLabel: "回答をコピー",
          userMessageToolbarCopyMessageLabel: "質問をコピー",
          assistantMessageToolbarRegenerateLabel: "再実行",
          userMessageToolbarEditMessageLabel: "質問を編集",
          chatDisclaimerText: "合成データを使用しています。結果は実際の市場価格を示しません。",
        }}
        onError={() => setError("チャットに接続できません。エージェントの起動状態を確認してください。")}
      />
    </section>
    {error && <div className="error-banner" role="alert">{error}</div>}
    <section className="result-card" aria-label="検索・集計結果">
      <div className="result-heading"><h2>検索・集計結果</h2>
        <span className="small-note">直近の質問</span></div>
      {tools.length > 0 && <ol className="tool-progress" aria-label="処理の進捗">
        {tools.map(tool => <li key={tool.id} data-status={tool.status}>
          <span className="progress-icon">{tool.status === "success" ? "✓" : tool.status === "running" ? "◌" : "!"}</span>
          {toolNames[tool.name] ?? tool.name}
          <span className="small-note">{tool.status === "success" ? "完了" : tool.status === "running" ? "実行中" : "中断・失敗"}</span>
        </li>)}
      </ol>}
      {results.length === 0 ? <div className="empty-result">
        <span aria-hidden="true" className="table-symbol">▤</span>
        <p>検索・集計をすると、ここに結果が表示されます。</p>
        <span className="small-note">回答文とは別に、数値や明細を確認できます。</span>
      </div> : results.map(result => <ResultTable key={result.result_id} result={result} />)}
      {metrics && <div className="run-summary" aria-live="polite">
        処理が完了しました · ツール実行 {metrics.tool_calls}回 · モデル呼び出し {metrics.model_calls}回
      </div>}
    </section>
  </>;
}

function ResultTable({ result }: { result: Result }) {
  const columns = result.preview_rows.length ? Object.keys(result.preview_rows[0]) : [];
  return <div className="result-table" data-testid="data-result">
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
    fetch("/api/agent-status").then(async response => {
      const status = await response.json();
      setMode(status.connected ? status.mode : "offline");
    }).catch(() => setMode("offline"));
  }, []);

  return <main className="page-shell">
    <header className="site-header">
      <a className="brand" href="/" aria-label="データ探索室 ホーム"><span className="brand-mark" aria-hidden="true">▦</span>データ探索室</a>
      <span className="environment-badge">LOCAL POC</span>
    </header>
    <div className="introduction">
      <p className="eyebrow">STRUCTURED DATA EXPLORER</p>
      <h1>データに、聞いてみる。</h1>
      <p className="description">地域や期間、価格の条件を伝えて、不動産データを検索・集計できます。</p>
      <div className="dataset-line"><span className="dataset-tag">合成データ</span>
        <span>360件 · 千代田区 / 新宿区 / 渋谷区 · 2023–2025年</span></div>
    </div>
    {mode === "fixture" && <div className="mode-banner">接続検証モード：質問にかかわらず、新宿区の年別集計を実行します。外部APIは使用しません。</div>}
    {mode === "offline" && <div className="error-banner" role="alert">エージェントが起動していません。Pythonサーバーを起動してから再読み込みしてください。</div>}
    <CopilotKitProvider runtimeUrl="/api/copilotkit" agentId="explorer" useSingleEndpoint={false} enableInspector={false}>
      <ChatWorkspace />
    </CopilotKitProvider>
    <footer className="site-footer"><span>架空の取引データを使用したプロトタイプです。実際の市場価格を示すものではありません。</span>
      <span>Strands + AG-UI + CopilotKit</span></footer>
  </main>;
}
