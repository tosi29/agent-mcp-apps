import { Readable } from "node:stream";

export type Run = { threadId: string; runId: string };
type Event = { type: string; threadId?: string; runId?: string };
const sse = (event: Event & Record<string, unknown>) => `data: ${JSON.stringify(event)}\n\n`;

// Bound the stream and preserve AG-UI's explicit terminal events on upstream failure.
export async function* relay(source: Readable, run: Run, signal: AbortSignal, cleanup: () => void) {
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let pending = "";
  let bytes = 0;
  let started = false;
  const abort = () => source.destroy(new Error("upstream aborted"));
  signal.addEventListener("abort", abort, { once: true });
  try {
    if (signal.aborted) abort();
    for await (const chunk of source) {
      bytes += chunk.length;
      if (bytes > 8 * 1024 * 1024) throw new Error("response limit");
      pending += decoder.decode(chunk, { stream: true });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(pending))) {
        if (Buffer.byteLength(pending.slice(0, match.index), "utf8") > 2 * 1024 * 1024) throw new Error("frame limit");
        const frame = pending.slice(0, match.index + match[0].length);
        pending = pending.slice(frame.length);
        const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
          .map(line => line.slice(5).replace(/^ /, "")).join("\n");
        const event: Event | null = data ? JSON.parse(data) : null;
        if (event) {
          if (typeof event.type !== "string" || (!started && event.type !== "RUN_STARTED")) {
            throw new Error("invalid event");
          }
          if (event.type === "RUN_STARTED") {
            if (started || event.runId !== run.runId || event.threadId !== run.threadId) throw new Error("invalid start");
            started = true;
          }
          if (event.type === "RUN_FINISHED" && (event.runId !== run.runId || event.threadId !== run.threadId)) {
            throw new Error("invalid finish");
          }
        }
        yield frame;
        if (event && ["RUN_FINISHED", "RUN_ERROR"].includes(event.type)) return;
      }
      if (Buffer.byteLength(pending, "utf8") > 2 * 1024 * 1024) throw new Error("frame limit");
    }
    throw new Error("missing terminal event");
  } catch {
    if (!started) yield sse({ type: "RUN_STARTED", ...run });
    yield sse({ type: "RUN_ERROR", code: signal.aborted ? "AGENT_TIMEOUT" : "AGENT_STREAM_FAILED",
      message: "応答の受信に失敗しました。時間をおいて再実行してください。" });
  } finally {
    signal.removeEventListener("abort", abort);
    source.destroy();
    cleanup();
  }
}
