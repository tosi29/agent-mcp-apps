import { randomUUID } from "node:crypto";
import type {
  InvokeAgentRuntimeCommandInput,
  InvokeAgentRuntimeCommandOutput,
} from "@aws-sdk/client-bedrock-agentcore";

type Invoke = (
  input: InvokeAgentRuntimeCommandInput,
  signal?: AbortSignal,
) => Promise<InvokeAgentRuntimeCommandOutput>;

const MCP_RUNTIME_ARN = /^arn:aws:bedrock-agentcore:ap-northeast-1:\d{12}:runtime\/[A-Za-z0-9_-]+$/;

export function validMcpRuntimeArn(arn: string): string {
  if (!MCP_RUNTIME_ARN.test(arn)) throw new Error("Invalid MCP Runtime ARN");
  return arn;
}

// A fetch for the MCP client that sends each Streamable HTTP POST through InvokeAgentRuntime.
// IAM signing stays in the AWS SDK. With user authentication (OAuth inbound on the Runtime),
// this is the place to send the user's MCP-audience token instead.
export function mcpRuntimeFetch(arn: string, invoke: Invoke) {
  return async (_url: string | URL, init?: RequestInit): Promise<Response> => {
    if ((init?.method ?? "GET") !== "POST" || typeof init?.body !== "string") {
      // No server-to-client stream or session DELETE: the server answers each POST with JSON.
      return new Response(null, { status: 405 });
    }
    const headers = new Headers(init.headers);
    // AgentCore routes by MCP session; any session works because results live in S3.
    const sessionId = headers.get("mcp-session-id") ?? randomUUID();
    try {
      const output = await invoke(
        {
          agentRuntimeArn: arn,
          qualifier: "DEFAULT",
          contentType: headers.get("content-type") ?? undefined,
          accept: headers.get("accept") ?? undefined,
          mcpSessionId: sessionId,
          mcpProtocolVersion: headers.get("mcp-protocol-version") ?? undefined,
          payload: new TextEncoder().encode(init.body),
        },
        init.signal ?? undefined,
      );
      const status = output.statusCode ?? 200;
      const body = (await output.response?.transformToString()) || null;
      const responseHeaders = new Headers({ "mcp-session-id": output.mcpSessionId ?? sessionId });
      if (output.contentType) responseHeaders.set("content-type", output.contentType);
      if (output.mcpProtocolVersion) {
        responseHeaders.set("mcp-protocol-version", output.mcpProtocolVersion);
      }
      return new Response(body, {
        status,
        headers: responseHeaders,
      });
    } catch (error) {
      const status = (error as { $metadata?: { httpStatusCode?: number } }).$metadata
        ?.httpStatusCode;
      return new Response(null, { status: status ?? 502 });
    }
  };
}
