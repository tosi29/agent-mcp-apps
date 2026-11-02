import "server-only";

import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from "@aws-sdk/client-bedrock-agentcore";
import { BedrockAgentCoreControlClient, GetAgentRuntimeCommand } from "@aws-sdk/client-bedrock-agentcore-control";
import { randomUUID } from "node:crypto";
import { Readable } from "node:stream";

const client = new BedrockAgentCoreClient({ region: "ap-northeast-1", maxAttempts: 1 });
const control = new BedrockAgentCoreControlClient({ region: "ap-northeast-1", maxAttempts: 1 });

export function agentRuntimeArn(): string | undefined {
  const arn = process.env.AGENT_RUNTIME_ARN;
  if (arn && !/^arn:aws:bedrock-agentcore:ap-northeast-1:\d{12}:runtime\/[A-Za-z0-9_-]+$/.test(arn)) {
    throw new Error("Invalid AgentCore Runtime ARN");
  }
  return arn || undefined;
}

export async function runtimeReady(): Promise<boolean> {
  const arn = agentRuntimeArn();
  if (!arn) return false;
  const response = await control.send(new GetAgentRuntimeCommand({
    agentRuntimeId: arn.slice(arn.lastIndexOf("/") + 1),
  }), { abortSignal: AbortSignal.timeout(5_000) });
  return response.status === "READY";
}

type Run = { threadId: string; runId: string };
type Event = { type: string; threadId?: string; runId?: string };
const sse = (event: Event & Record<string, unknown>) => `data: ${JSON.stringify(event)}\n\n`;

// Bound the stream and preserve AG-UI's explicit terminal events on upstream failure.
async function* relay(source: Readable, run: Run, signal: AbortSignal, cleanup: () => void) {
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
      if (bytes > 2 * 1024 * 1024) throw new Error("response limit");
      pending += decoder.decode(chunk, { stream: true });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(pending))) {
        if (match.index > 256 * 1024) throw new Error("frame limit");
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
      if (pending.length > 256 * 1024) throw new Error("frame limit");
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

export async function fetchAgentCore(_url: string, init: RequestInit): Promise<Response> {
  if (typeof init.body !== "string") return Response.json({ error: "invalid body" }, { status: 400 });
  if (Buffer.byteLength(init.body) > 128 * 1024) return Response.json({ error: "request too large" }, { status: 413 });
  const input = JSON.parse(init.body) as Run;
  const run = { threadId: input.threadId, runId: input.runId };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 130_000);
  const signal = init.signal ? AbortSignal.any([init.signal, controller.signal]) : controller.signal;
  const cleanup = () => { clearTimeout(timer); controller.abort(); };
  let source: Readable | undefined;
  try {
    const response = await client.send(new InvokeAgentRuntimeCommand({
      agentRuntimeArn: agentRuntimeArn(), qualifier: "DEFAULT", runtimeSessionId: randomUUID(),
      contentType: "application/json", accept: "text/event-stream", payload: Buffer.from(init.body),
    }), { abortSignal: signal });
    source = response.response as Readable | undefined;
    if (response.statusCode !== 200 || !response.contentType?.startsWith("text/event-stream") || !source?.[Symbol.asyncIterator]) {
      throw new Error("invalid upstream response");
    }
    const body = Readable.toWeb(Readable.from(relay(source, run, signal, cleanup), { objectMode: false })) as ReadableStream<Uint8Array>;
    return new Response(body, { headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-store, no-transform" } });
  } catch {
    source?.destroy();
    const status = signal.aborted ? 504 : 502;
    cleanup();
    return Response.json({ error: "エージェントに接続できません。" }, { status });
  }
}
