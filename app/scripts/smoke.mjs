// Exercise the same CopilotKit Runtime / AG-UI HTTP route as the browser.
// No browser rendering is tested here. Live inference requires --live explicitly.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { HttpAgent } from "@ag-ui/client";
import { McpUiToolResultNotificationSchema } from "@modelcontextprotocol/ext-apps/app-bridge";

const live = process.argv.includes("--live");
const apps = process.argv.includes("--apps");
const origin = (process.env.SMOKE_URL ?? "http://127.0.0.1:3000").replace(/\/$/, "");
const status = await fetch(`${origin}/api/agent-status`).then(r => r.json());
assert.equal(status.connected, true, "Python backend is not running");
assert.equal(status.mode, live ? "sakura" : "fixture",
  "Mode mismatch. An actual Sakura request needs --live; otherwise start --model fixture.");
const info = await fetch(`${origin}/api/copilotkit/info`).then(r => r.json());
assert.equal(info.telemetryDisabled, true, "CopilotKit telemetry must be disabled");
assert.ok(info.agents.explorer);
const page = await fetch(`${origin}/`);
assert.equal(page.status, 200);
const html = await page.text();
assert.ok(html.includes("データ探索室"));
const asset = html.match(/(?:src|href)="([^" ]*\/_next\/static\/[^" ]+)"/)?.[1];
assert.ok(asset, "Missing Next.js static asset");
assert.equal((await fetch(new URL(asset.replaceAll("&amp;", "&"), origin))).status, 200,
  "Next.js static assets must be reachable through the same endpoint");

const agent = new HttpAgent({
  url: `${origin}/api/copilotkit/agent/explorer/run`,
  threadId: crypto.randomUUID(),
  headers: { Origin: new URL(origin).origin },
});
agent.addMessage({ id: crypto.randomUUID(), role: "user",
  content: apps ? "新宿区の年別ダッシュボードを表示して" : "項目を確認してから、新宿区を年別に集計し、件数と平均取引総額を教えて" });
const started = performance.now();
const observations = [];
await agent.runAgent({}, {
  onEvent({ event }) {
    observations.push({ elapsed_ms: Math.round((performance.now() - started) * 100) / 100, event });
  },
});
const events = observations.map(item => item.event);
assert.equal(events.filter(e => e.type === "RUN_FINISHED").length, 1);
assert.equal(events.filter(e => e.type === "RUN_ERROR").length, 0);
assert.equal(events.at(-1).type, "RUN_FINISHED");
const custom = events.filter(e => e.type === "CUSTOM");
const data = custom.find(e => e.name === "data_result")?.value;
assert.ok(data, "Missing independent data_result event");
assert.equal(data.total_count, 3);
assert.deepEqual(data.preview_rows.map(row => row.year), [2023, 2024, 2025]);
assert.deepEqual(data.preview_rows.map(row => row.transaction_count), [40, 40, 40]);
assert.deepEqual(data.preview_rows.map(row => row.average_price_yen), [42500000, 42500000, 42500000]);
if (apps) {
  assert.equal(data.app?.mimeType, "text/html;profile=mcp-app");
  assert.ok(data.app.html.includes("取引データのダッシュボード"));
  assert.equal(data.app.toolResult._meta.preview.preview_rows.length, 3);
  McpUiToolResultNotificationSchema.parse({ method: "ui/notifications/tool-result", params: data.app.toolResult });
  assert.ok(!JSON.stringify(agent.messages).includes("<html"));
  assert.ok(!JSON.stringify(agent.messages).includes("preview_rows"));
}
const metrics = custom.find(e => e.name === "run_metrics")?.value;
assert.ok(metrics.model_calls <= 4);
assert.equal(metrics.tool_errors, 0);
const text = agent.messages.filter(m => m.role === "assistant").map(m => m.content ?? "").join("");
assert.ok(text.includes("合成データ"));
const timing = predicate => observations.find(item => predicate(item.event))?.elapsed_ms;
const textEvents = observations.filter(item => item.event.type === "TEXT_MESSAGE_CONTENT");
// The fixture deliberately spaces chunks out. Real models may finish within 200ms.
if (!live) {
  assert.ok(textEvents.length >= 2);
  assert.ok(textEvents.at(-1).elapsed_ms - textEvents[0].elapsed_ms >= 200,
    "Text must arrive incrementally instead of being buffered until completion");
  const reasoning = events.filter(e => e.type === "REASONING_MESSAGE_CONTENT");
  assert.ok(reasoning.length >= 2, "Missing incremental fixture reasoning");
  assert.ok(reasoning.map(e => e.delta).join("").includes("接続検証用サンプル"));
  assert.ok(agent.messages.some(m => m.role === "reasoning"),
    "Reasoning must remain in the client message history for rendering");
  const followupEvents = [];
  agent.addMessage({ id: crypto.randomUUID(), role: "user", content: "同じ条件でもう一度集計して" });
  await agent.runAgent({}, {
    onEvent({ event }) { followupEvents.push(event); },
  });
  assert.equal(followupEvents.filter(e => e.type === "RUN_ERROR").length, 0);
  assert.equal(followupEvents.at(-1).type, "RUN_FINISHED",
    "A follow-up containing reasoning history must succeed");
}
const summary = {
  mode: status.mode, metrics, events: events.length,
  first_text_ms: timing(e => e.type === "TEXT_MESSAGE_CONTENT"),
  data_result_ms: timing(e => e.type === "CUSTOM" && e.name === "data_result"),
  done_ms: observations.at(-1).elapsed_ms,
  dataset: data.dataset,
  note: "Next.js Runtime / AG-UI transport check; browser rendering not verified",
};
await mkdir("../agent/results", { recursive: true });
await writeFile(`../agent/results/agui-${status.mode}-smoke.json`, JSON.stringify({ summary, observations }, null, 2));
console.log(JSON.stringify(summary, null, 2));
