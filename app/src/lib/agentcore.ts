import "server-only";

import { relay, type Run } from "./agui-stream";

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

export async function runtimeStatus() {
  const arn = agentRuntimeArn();
  if (!arn) return { connected: false, mode: "unknown" };
  const response = await control.send(new GetAgentRuntimeCommand({
    agentRuntimeId: arn.slice(arn.lastIndexOf("/") + 1),
  }), { abortSignal: AbortSignal.timeout(5_000) });
  const configuredMode = response.environmentVariables?.EXPLORER_MODEL_MODE;
  // Unknown configuration must not let the fixture smoke command trigger live inference.
  const mode = configuredMode === "fixture" || configuredMode === "sakura" ? configuredMode : "unknown";
  return { connected: response.status === "READY", mode };
}


export async function fetchAgentCore(_url: string, init: RequestInit): Promise<Response> {
  if (typeof init.body !== "string") return Response.json({ error: "invalid body" }, { status: 400 });
  if (Buffer.byteLength(init.body) > 128 * 1024) return Response.json({ error: "request too large" }, { status: 413 });
  const input = JSON.parse(init.body) as Run;
  const run = { threadId: input.threadId, runId: input.runId };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 310_000);
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
