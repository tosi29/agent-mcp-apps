import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

const MAX_BODY_BYTES = 128 * 1024;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_FRAME_CHARS = 256 * 1024;
const sse = event => `data: ${JSON.stringify(event)}\n\n`;

class HttpError extends Error {
  constructor(status) {
    super("bridge request failed");
    this.status = status;
  }
}

function parseRequest(event) {
  if (event.httpMethod !== "POST") throw new HttpError(405);
  const headers = Object.fromEntries(Object.entries(event.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
  // This endpoint is for signed server-to-server calls, not browser CORS access.
  if (headers.origin) throw new HttpError(403);
  if (headers["content-type"]?.split(";")[0].trim().toLowerCase() !== "application/json") {
    throw new HttpError(415);
  }
  if (typeof event.body !== "string") throw new HttpError(400);
  if (event.body.length > MAX_BODY_BYTES * 2) throw new HttpError(413);
  const payload = Buffer.from(event.body, event.isBase64Encoded ? "base64" : "utf8");
  if (payload.length > MAX_BODY_BYTES) throw new HttpError(413);
  let run;
  try { run = JSON.parse(payload.toString("utf8")); } catch { throw new HttpError(400); }
  if (!run || ![run.threadId, run.runId].every(id => typeof id === "string" && id.length > 0 && id.length <= 128)
      || !Array.isArray(run.messages) || run.messages.length === 0 || run.messages.length > 40) {
    throw new HttpError(400);
  }
  return { payload, run };
}

async function* frames(source) {
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let pending = "";
  let bytes = 0;
  for await (const chunk of source) {
    bytes += chunk.length;
    if (bytes > MAX_RESPONSE_BYTES) throw new Error("response limit");
    pending += decoder.decode(chunk, { stream: true });
    let match;
    while ((match = /\r?\n\r?\n/.exec(pending))) {
      if (match.index > MAX_FRAME_CHARS) throw new Error("frame limit");
      const raw = pending.slice(0, match.index + match[0].length);
      pending = pending.slice(raw.length);
      const data = raw.split(/\r?\n/).filter(line => line.startsWith("data:"))
        .map(line => line.slice(5).replace(/^ /, "")).join("\n");
      yield { raw, event: data ? JSON.parse(data) : null };
    }
    if (pending.length > MAX_FRAME_CHARS) throw new Error("frame limit");
  }
  pending += decoder.decode();
  if (pending.trim()) throw new Error("incomplete SSE frame");
}

async function* relay(source, run, signal) {
  let started = false;
  try {
    for await (const { raw, event } of frames(source)) {
      if (signal.aborted) throw signal.reason;
      if (event) {
        if (typeof event.type !== "string") throw new Error("invalid AG-UI event");
        if (!started && event.type !== "RUN_STARTED") throw new Error("missing run start");
        if (event.type === "RUN_STARTED") {
          if (started || event.threadId !== run.threadId || event.runId !== run.runId) {
            throw new Error("invalid run start");
          }
          started = true;
        }
        if (event.type === "RUN_FINISHED" && (event.threadId !== run.threadId || event.runId !== run.runId)) {
          throw new Error("invalid run finish");
        }
      }
      yield raw;
      // Stop after the first terminal event, including on a faulty/repeating upstream.
      if (event && ["RUN_FINISHED", "RUN_ERROR"].includes(event.type)) return;
    }
    throw new Error("missing terminal event");
  } catch {
    if (!started) yield sse({ type: "RUN_STARTED", threadId: run.threadId, runId: run.runId });
    yield sse({
      type: "RUN_ERROR",
      code: signal.aborted ? "BRIDGE_TIMEOUT" : "UPSTREAM_STREAM_FAILED",
      message: "応答の受信に失敗しました。時間をおいて再実行してください。",
    });
  } finally {
    source.destroy?.();
  }
}

function errorStatus(error, signal) {
  if (error instanceof HttpError) return error.status;
  if (signal.aborted) return 504;
  const status = error?.$metadata?.httpStatusCode;
  return [400, 413, 422, 429].includes(status) ? status : 502;
}

export function createBridge({ invoke, respond, timeoutMs = 130_000 }) {
  return async (event, rawStream, context) => {
    const controller = new AbortController();
    const duration = Math.max(1, Math.min(timeoutMs, context.getRemainingTimeInMillis() - 5_000));
    const timer = setTimeout(() => controller.abort(new Error("bridge deadline")), duration);
    const disconnected = () => controller.abort(new Error("downstream closed"));
    rawStream.on("close", disconnected);
    let output;
    let upstream;
    try {
      const { payload, run } = parseRequest(event);
      const response = await invoke(payload, controller.signal);
      upstream = response.response;
      if (response.statusCode !== 200 || !response.contentType?.startsWith("text/event-stream")
          || !upstream?.[Symbol.asyncIterator]) {
        throw new Error("invalid upstream response");
      }
      output = respond(rawStream, {
        statusCode: 200,
        headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store, no-transform" },
      });
      // Abort a stalled read too, after the SDK has already returned response headers.
      const abortSource = () => upstream.destroy?.(controller.signal.reason);
      controller.signal.addEventListener("abort", abortSource, { once: true });
      try {
        if (controller.signal.aborted) abortSource();
        await pipeline(Readable.from(relay(upstream, run, controller.signal)), output);
      } finally {
        controller.signal.removeEventListener("abort", abortSource);
      }
    } catch (error) {
      if (!output && !rawStream.destroyed) {
        output = respond(rawStream, {
          statusCode: errorStatus(error, controller.signal),
          headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
        });
        await pipeline(Readable.from([JSON.stringify({ error: "リクエストを処理できませんでした。" })]), output);
      }
      // Once streaming starts, relay emits RUN_ERROR. A closed client cannot receive it.
    } finally {
      clearTimeout(timer);
      rawStream.off("close", disconnected);
      controller.abort();
      upstream?.destroy?.();
    }
  };
}
