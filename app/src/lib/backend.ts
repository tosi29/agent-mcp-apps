import "server-only";
import { HttpAgent } from "@ag-ui/client";
import { agentRuntimeArn, fetchAgentCore, runtimeReady } from "./agentcore";

export function backendAgent(): HttpAgent {
  return agentRuntimeArn()
    ? new HttpAgent({ url: "http://agentcore.internal/invocations", fetch: fetchAgentCore })
    : new HttpAgent({ url: agentUrl().toString() });
}

export async function backendStatus() {
  if (agentRuntimeArn()) {
    return { connected: await runtimeReady(), mode: "fixture" };
  }
  const response = await fetch(new URL("/ping", agentUrl()), {
    cache: "no-store", signal: AbortSignal.timeout(3_000),
  });
  if (!response.ok) throw new Error("backend unavailable");
  const status = await response.json();
  return { connected: true, mode: status.mode };
}

export function agentUrl(): URL {
  const url = new URL(process.env.AGENT_URL ?? "http://127.0.0.1:8000/invocations");
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(url.hostname) ||
    url.username || url.password || url.search || url.hash
  ) {
    throw new Error("AGENT_URL must point to a local HTTP endpoint");
  }
  return url;
}

export function allowedOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const allowed = process.env.APP_ORIGIN
    ? [new URL(process.env.APP_ORIGIN).origin]
    : ["http://127.0.0.1:3000", "http://localhost:3000"];
  return !origin || allowed.includes(origin);
}
