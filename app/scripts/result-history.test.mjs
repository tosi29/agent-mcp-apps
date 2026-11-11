import assert from "node:assert/strict";
import { test } from "node:test";
import { HttpAgent } from "@ag-ui/client";
import { resultHistorySubscriber } from "../src/lib/result-history.ts";

const result = (value) => ({
  result_id: "same-result-id",
  tool_call_id: "tool",
  total_count: 1,
  count_unit: "rows",
  returned_count: 1,
  truncated: false,
  preview_truncated: false,
  preview_rows: [{ municipality: value }],
  app: {
    resourceUri: "ui://test/view",
    html: `<html>ui-only-${value}</html>`,
    toolResult: { _meta: { private: value } },
  },
});

test("two runs keep both results and never resend UI previews to the model", async () => {
  let history = [];
  const outgoing = [];
  const agent = new HttpAgent({
    url: "http://fixture.invalid/invocations",
    threadId: "history-test",
    fetch: async (_url, init) => {
      const input = JSON.parse(init.body);
      outgoing.push(input);
      const toolCallId = `tool-${input.runId}`;
      const events = [
        { type: "RUN_STARTED", threadId: input.threadId, runId: input.runId },
        { type: "TOOL_CALL_START", toolCallId, toolCallName: "search_transactions" },
        { type: "TOOL_CALL_ARGS", toolCallId, delta: "{}" },
        { type: "TOOL_CALL_END", toolCallId },
        {
          type: "TOOL_CALL_RESULT",
          messageId: `message-${input.runId}`,
          toolCallId,
          content: '{"count":1}',
        },
        {
          type: "CUSTOM",
          name: "data_result",
          value: { ...result(`preview-only-${outgoing.length}`), tool_call_id: toolCallId },
        },
        {
          type: "CUSTOM",
          name: "tool_status",
          value: { tool_call_id: toolCallId, status: "success" },
        },
        { type: "RUN_FINISHED", threadId: input.threadId, runId: input.runId },
      ];
      return new Response(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""), {
        headers: { "Content-Type": "text/event-stream" },
      });
    },
  });
  agent.subscribe(
    resultHistorySubscriber((change) => {
      history = change(history);
    }),
  );
  for (const content of ["新宿区を検索", "渋谷区も検索"]) {
    agent.addMessage({ id: crypto.randomUUID(), role: "user", content });
    await agent.runAgent();
  }
  assert.deepEqual(
    history.map((run) => run.question),
    ["新宿区を検索", "渋谷区も検索"],
  );
  assert.deepEqual(
    history.map((run) => run.results[0].preview_rows[0].municipality),
    ["preview-only-1", "preview-only-2"],
  );
  assert.ok(history.every((run) => run.status === "success" && run.tools[0].status === "success"));
  assert.ok(!JSON.stringify(outgoing[1]).includes("preview-only-1"));
  assert.ok(history[0].results[0].app.html.includes("ui-only-"));
  assert.ok(!JSON.stringify(outgoing).includes("<html>"));
  assert.deepEqual(agent.state, {});
});

test("failed or stopped runs keep earlier and partial results", () => {
  let history = [];
  const subscriber = resultHistorySubscriber((change) => {
    history = change(history);
  });
  for (const runId of ["completed", "failed", "stopped"]) {
    const context = { input: { runId, messages: [{ role: "user", content: runId }] } };
    subscriber.onRunStartedEvent({ ...context, event: { runId } });
    subscriber.onToolCallStartEvent({
      ...context,
      event: { toolCallId: "tool", toolCallName: "search_transactions" },
    });
    subscriber.onCustomEvent({ ...context, event: { name: "data_result", value: result(runId) } });
    if (runId === "completed") {
      subscriber.onCustomEvent({
        ...context,
        event: { name: "tool_status", value: { tool_call_id: "tool", status: "success" } },
      });
      subscriber.onRunFinishedEvent({ ...context, outcome: "success" });
    } else if (runId === "failed") {
      subscriber.onRunErrorEvent(context);
    }
    subscriber.onRunFinalized(context);
  }
  assert.deepEqual(
    history.map((run) => run.status),
    ["success", "error", "stopped"],
  );
  assert.deepEqual(
    history.map((run) => run.results[0].preview_rows[0].municipality),
    ["completed", "failed", "stopped"],
  );
  assert.deepEqual(
    history.map((run) => run.tools[0].status),
    ["success", "stopped", "stopped"],
  );
});
