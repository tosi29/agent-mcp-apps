import assert from "node:assert/strict";
import { once } from "node:events";
import { PassThrough, Readable, Writable } from "node:stream";
import { test } from "node:test";
import { createBridge } from "../bridge.mjs";

const run = { threadId: "thread-1", runId: "run-1", messages: [{ role: "user", id: "user-1", content: "新宿区を年別に集計して" }] };
const start = { type: "RUN_STARTED", threadId: run.threadId, runId: run.runId };
const finish = { type: "RUN_FINISHED", threadId: run.threadId, runId: run.runId };
const data = { type: "CUSTOM", name: "data_result", value: { result_id: "result-1", preview_rows: [{ year: 2023, transaction_count: 40 }] } };
const encode = event => `data: ${JSON.stringify(event)}\n\n`;
const request = overrides => ({ httpMethod: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(run), ...overrides });
const upstream = source => ({ statusCode: 200, contentType: "text/event-stream; charset=utf-8", response: source });

function sink() {
  const chunks = [];
  const stream = new Writable({ write(chunk, _encoding, callback) { chunks.push(Buffer.from(chunk)); callback(); } });
  // Simulate HttpResponseStream.from's metadata and eight-null-byte delimiter.
  const respond = (raw, metadata) => {
    raw.write(JSON.stringify(metadata));
    raw.write(Buffer.alloc(8));
    return raw;
  };
  const contents = () => {
    const bytes = Buffer.concat(chunks);
    const boundary = bytes.indexOf(Buffer.alloc(8));
    return { metadata: JSON.parse(bytes.subarray(0, boundary)), body: bytes.subarray(boundary + 8).toString() };
  };
  return { stream, respond, contents };
}

const context = { getRemainingTimeInMillis: () => 150_000 };
const decode = body => body.trim().split(/\r?\n\r?\n/).map(frame => JSON.parse(frame.replace(/^data: /, "")));

test("forwards the first event before upstream completion and preserves the separate data event", async () => {
  const source = new PassThrough();
  const out = sink();
  let observedPayload;
  const handle = createBridge({ invoke: async payload => { observedPayload = payload; return upstream(source); }, respond: out.respond });
  const completed = handle(request(), out.stream, context);
  const forwarded = once(out.stream, "pipe");
  await forwarded;
  source.write(encode(start));
  // Wait for a real forwarded write, without waiting for the end of the stream.
  while (!out.contents().body.includes("RUN_STARTED")) await new Promise(resolve => setImmediate(resolve));
  assert.equal(out.stream.writableEnded, false);
  source.end(encode(data) + encode(finish));
  await completed;
  assert.deepEqual(JSON.parse(observedPayload), run);
  assert.equal(out.contents().metadata.statusCode, 200);
  assert.match(out.contents().metadata.headers["Content-Type"], /^text\/event-stream/);
  assert.deepEqual(decode(out.contents().body), [start, data, finish]);
});

test("handles UTF-8 and CRLF frames split across byte boundaries, including base64 requests", async () => {
  const text = { type: "TEXT_MESSAGE_CONTENT", messageId: "a", delta: "合成データ" };
  const bytes = Buffer.from([start, text, finish].map(encode).join("").replaceAll("\n", "\r\n"));
  const source = Readable.from(Array.from(bytes, byte => Buffer.from([byte])));
  const out = sink();
  const handle = createBridge({ invoke: async () => upstream(source), respond: out.respond });
  await handle(request({ body: Buffer.from(JSON.stringify(run)).toString("base64"), isBase64Encoded: true }), out.stream, context);
  assert.deepEqual(decode(out.contents().body), [start, text, finish]);
});

test("rejects invalid requests without invoking AgentCore", async t => {
  for (const [name, override, expected] of [
    ["method", { httpMethod: "GET" }, 405],
    ["browser origin", { headers: { origin: "https://untrusted.invalid" } }, 403],
    ["media type", { headers: { "content-type": "text/plain" } }, 415],
    ["JSON", { body: "{bad" }, 400],
    ["AG-UI IDs", { body: JSON.stringify({ ...run, runId: null }) }, 400],
    ["body limit", { body: JSON.stringify({ ...run, padding: "あ".repeat(50_000) }) }, 413],
  ]) await t.test(name, async () => {
    const out = sink();
    const handle = createBridge({ invoke: async () => assert.fail("must not invoke"), respond: out.respond });
    await handle(request(override), out.stream, context);
    assert.equal(out.contents().metadata.statusCode, expected);
  });
});

test("sanitizes upstream exceptions and does not retry", async () => {
  let calls = 0;
  const out = sink();
  const handle = createBridge({ invoke: async () => { calls++; throw new Error("SECRET upstream trace"); }, respond: out.respond });
  await handle(request(), out.stream, context);
  assert.equal(calls, 1);
  assert.equal(out.contents().metadata.statusCode, 502);
  assert.doesNotMatch(out.contents().body, /SECRET/);
});

test("preserves throttling status and rejects non-SSE upstream responses", async t => {
  await t.test("throttling", async () => {
    const out = sink();
    const handle = createBridge({ invoke: async () => { throw { $metadata: { httpStatusCode: 429 } }; }, respond: out.respond });
    await handle(request(), out.stream, context);
    assert.equal(out.contents().metadata.statusCode, 429);
  });
  await t.test("non-SSE", async () => {
    const out = sink();
    const source = Readable.from(["private response"]);
    const handle = createBridge({ invoke: async () => ({ ...upstream(source), contentType: "text/plain" }), respond: out.respond });
    await handle(request(), out.stream, context);
    assert.equal(out.contents().metadata.statusCode, 502);
    assert.equal(source.destroyed, true);
  });
});

test("converts truncation, malformed events, and duplicate start into one sanitized terminal error", async t => {
  for (const [name, content] of [
    ["EOF", encode(start)],
    ["incomplete frame", encode(start) + "data: {"],
    ["invalid JSON", encode(start) + "data: SECRET\n\n"],
    ["duplicate start", encode(start) + encode(start)],
    ["wrong run", encode({ ...start, runId: "another-run" })],
    ["no start", encode(data)],
  ]) await t.test(name, async () => {
    const out = sink();
    const handle = createBridge({ invoke: async () => upstream(Readable.from([Buffer.from(content)])), respond: out.respond });
    await handle(request(), out.stream, context);
    const events = decode(out.contents().body);
    assert.equal(events.filter(e => e.type === "RUN_STARTED").length, 1);
    assert.equal(events.filter(e => e.type === "RUN_ERROR").length, 1);
    assert.equal(events.at(-1).type, "RUN_ERROR");
    assert.doesNotMatch(out.contents().body, /SECRET/);
  });
});

test("stops at the first terminal event without forwarding duplicates", async () => {
  const out = sink();
  const handle = createBridge({ invoke: async () => upstream(Readable.from([Buffer.from(encode(start) + encode(finish) + encode(finish))])), respond: out.respond });
  await handle(request(), out.stream, context);
  assert.deepEqual(decode(out.contents().body), [start, finish]);
});

test("times out while waiting for upstream headers", async () => {
  const out = sink();
  const handle = createBridge({
    invoke: (_payload, signal) => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason), { once: true })),
    respond: out.respond, timeoutMs: 20,
  });
  await handle(request(), out.stream, context);
  assert.equal(out.contents().metadata.statusCode, 504);
});

test("a stalled stream ends with RUN_ERROR before the Lambda deadline", async () => {
  const out = sink();
  const source = new PassThrough();
  source.write(encode(start));
  const handle = createBridge({ invoke: async () => upstream(source), respond: out.respond, timeoutMs: 20 });
  await handle(request(), out.stream, context);
  assert.equal(decode(out.contents().body).at(-1).code, "BRIDGE_TIMEOUT");
  assert.equal(source.destroyed, true);
});

test("a downstream disconnect aborts the local upstream connection", async () => {
  const out = sink();
  const source = new PassThrough();
  let signal;
  const handle = createBridge({ invoke: async (_payload, s) => { signal = s; return upstream(source); }, respond: out.respond });
  const completed = handle(request(), out.stream, context);
  await once(out.stream, "pipe");
  out.stream.destroy();
  await completed;
  assert.equal(signal.aborted, true);
  assert.equal(source.destroyed, true);
});
