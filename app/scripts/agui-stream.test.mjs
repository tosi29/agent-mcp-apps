import assert from "node:assert/strict";
import { test } from "node:test";
import { Readable } from "node:stream";
import { relay } from "../src/lib/agui-stream.ts";

const run = { threadId: "thread", runId: "run" };
const frame = event => `data: ${JSON.stringify(event)}\n\n`;
const start = frame({ type: "RUN_STARTED", ...run });
const finish = frame({ type: "RUN_FINISHED", ...run });

async function forward(chunks) {
  let cleaned = false;
  const output = [];
  for await (const chunk of relay(Readable.from(chunks.map(chunk => Buffer.from(chunk))), run,
    new AbortController().signal, () => { cleaned = true; })) output.push(chunk);
  assert.ok(cleaned);
  return output.join("");
}

test("AgentCore relay preserves a large Apps event across chunks and Unicode boundaries", async () => {
  const event = frame({ type: "CUSTOM", name: "data_result", value: {
    app: { html: "<html>" + "<p>取引データ</p>".repeat(35_000) + "</html>" },
  } });
  const wire = Buffer.from(start + event + finish);
  const chunks = [];
  for (let at = 0; at < wire.length; at += 4093) chunks.push(wire.subarray(at, at + 4093));
  assert.equal(await forward(chunks), start + event + finish);
});

test("oversized events fail with one terminal error instead of forwarding partial HTML", async () => {
  const oversized = frame({ type: "CUSTOM", value: "x".repeat(2 * 1024 * 1024) });
  const output = await forward([start, oversized, finish]);
  assert.ok(output.includes('"type":"RUN_ERROR"'));
  assert.ok(!output.includes('"type":"RUN_FINISHED"'));
  assert.ok(!output.includes('"type":"CUSTOM"'));
});

test("a mismatched run or missing terminal event cannot finish successfully", async () => {
  for (const chunks of [[start], [start, frame({ type: "RUN_FINISHED", ...run, runId: "other" })]]) {
    const output = await forward(chunks);
    assert.equal(output.match(/"type":"RUN_ERROR"/g).length, 1);
    assert.ok(!output.includes('"type":"RUN_FINISHED"'));
  }
});
