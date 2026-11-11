import assert from "node:assert/strict";
import { test } from "node:test";
import { App } from "@modelcontextprotocol/ext-apps";
import { AppBridge } from "@modelcontextprotocol/ext-apps/app-bridge";

function transports() {
  const host = { start: async () => {}, close: async () => {} };
  const view = { start: async () => {}, close: async () => {} };
  host.send = async (message) => {
    queueMicrotask(() => view.onmessage?.(structuredClone(message)));
  };
  view.send = async (message) => {
    queueMicrotask(() => host.onmessage?.(structuredClone(message)));
  };
  return [host, view];
}

test("official Apps SDK handshake delivers UI-only metadata and denies server tools", async () => {
  const [host, view] = transports();
  const bridge = new AppBridge(null, { name: "test host", version: "1" }, {});
  const app = new App({ name: "test view", version: "1" }, {}, { autoResize: false });
  const results = [];
  const inputs = [];
  app.ontoolresult = (result) => results.push(result);
  app.ontoolinput = (input) => inputs.push(input);
  try {
    await bridge.connect(host);
    await app.connect(view);
    await bridge.sendToolInput({ arguments: { group_by: "year" } });
    await bridge.sendToolResult({
      content: [{ type: "text", text: "3区分を集計" }],
      _meta: { preview: { preview_rows: [{ year: 2023, transaction_count: 40 }] } },
    });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(inputs[0].arguments.group_by, "year");
    assert.equal(results[0]._meta.preview.preview_rows[0].transaction_count, 40);
    await assert.rejects(app.callServerTool({ name: "search_transactions", arguments: {} }));
  } finally {
    await app.close();
    await bridge.close();
  }
});
