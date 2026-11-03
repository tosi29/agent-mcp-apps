import type { AgentSubscriber } from "@ag-ui/client";

type Row = Record<string, string | number | null>;
export type McpAppResult = {
  resourceUri: string;
  mimeType: "text/html;profile=mcp-app";
  html: string;
  toolInput: Record<string, unknown>;
  toolResult: {
    content: { type: "text"; text: string }[];
    structuredContent?: Record<string, unknown>;
    _meta: Record<string, unknown>;
  };
};
export type DataResult = {
  result_id: string;
  tool_call_id: string;
  total_count: number;
  count_unit: string;
  returned_count: number;
  truncated: boolean;
  preview_truncated: boolean;
  preview_rows: Row[];
  app?: McpAppResult;
};
export type ResultRun = {
  runId: string;
  question: string;
  status: "running" | "success" | "error" | "stopped";
  tools: { id: string; name: string; status: string }[];
  results: DataResult[];
  metrics?: { model_calls: number; tool_calls: number };
};

// UI-only history. These previews must never be copied into agent messages or shared state.
export function resultHistorySubscriber(
  update: (change: (history: ResultRun[]) => ResultRun[]) => void,
): AgentSubscriber {
  const updateRun = (runId: string, change: (run: ResultRun) => ResultRun) =>
    update(history => history.map(run => run.runId === runId ? change(run) : run));

  return {
    onRunStartedEvent: ({ event, input }) => {
      const question = input.messages.findLast(message => message.role === "user")?.content;
      update(history => history.some(run => run.runId === event.runId) ? history : [...history, {
        runId: event.runId,
        question: typeof question === "string" ? question : "データ探索",
        status: "running", tools: [], results: [],
      }]);
    },
    onToolCallStartEvent: ({ event, input }) => updateRun(input.runId, run => ({
      ...run, tools: [...run.tools.filter(tool => tool.id !== event.toolCallId), {
        id: event.toolCallId, name: event.toolCallName, status: "running",
      }],
    })),
    onCustomEvent: ({ event, input }) => {
      if (event.name === "data_result") {
        const result = event.value as DataResult;
        if (typeof result?.result_id === "string" && Array.isArray(result.preview_rows)) {
          updateRun(input.runId, run => ({
            ...run, results: [...run.results.filter(item => item.result_id !== result.result_id), result],
          }));
        }
      } else if (event.name === "tool_status") {
        const value = event.value as { tool_call_id: string; status: string };
        updateRun(input.runId, run => ({
          ...run, tools: run.tools.map(tool => tool.id === value.tool_call_id
            ? { ...tool, status: value.status } : tool),
        }));
      } else if (event.name === "run_metrics") {
        updateRun(input.runId, run => ({ ...run, metrics: event.value }));
      }
    },
    onRunFinishedEvent: ({ input, outcome }) => updateRun(input.runId, run => ({
      ...run, status: outcome === "success" ? "success" : "stopped",
    })),
    onRunErrorEvent: ({ input }) => updateRun(input.runId, run => ({ ...run, status: "error" })),
    onRunFailed: ({ input }) => updateRun(input.runId, run => ({ ...run, status: "error" })),
    onRunFinalized: ({ input }) => updateRun(input.runId, run => ({
      ...run,
      status: run.status === "running" ? "stopped" : run.status,
      tools: run.tools.map(tool => tool.status === "running" ? { ...tool, status: "stopped" } : tool),
    })),
  };
}
