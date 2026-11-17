import "server-only";

import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from "@aws-sdk/client-bedrock-agentcore";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { mcpRuntimeFetch, validMcpRuntimeArn } from "./agentcore-mcp";
import { resultCsvFilename } from "./result-csv";

const agentCore = new BedrockAgentCoreClient({ region: "ap-northeast-1", maxAttempts: 1 });

export class ResourceUnavailableError extends Error {}

export function mcpUrl(): URL {
  const url = new URL(process.env.MCP_URL ?? "http://127.0.0.1:8001/mcp");
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error("MCP_URL must point to a local HTTP endpoint");
  }
  return url;
}

function transport(): { transport: StreamableHTTPClientTransport; timeout: number } {
  const arn = process.env.MCP_RUNTIME_ARN;
  if (arn) {
    // The deployed MCP Runtime; a new session may start a microVM, so allow a cold start.
    const runtimeArn = validMcpRuntimeArn(arn);
    return {
      transport: new StreamableHTTPClientTransport(new URL("http://agentcore.internal/mcp"), {
        fetch: mcpRuntimeFetch(runtimeArn, (input, signal) =>
          agentCore.send(new InvokeAgentRuntimeCommand(input), { abortSignal: signal }),
        ),
      }),
      timeout: 30_000,
    };
  }
  // With user authentication, pass the user's MCP-audience token (for example obtained
  // on behalf of the user) as authProvider: { token: async () => token }.
  return {
    transport: new StreamableHTTPClientTransport(mcpUrl(), { requestInit: { redirect: "error" } }),
    timeout: 10_000,
  };
}

export function mcpConfigured(): boolean {
  // In the cloud the local default does not exist; the Runtime ARN must be set.
  return Boolean(process.env.MCP_RUNTIME_ARN) || !process.env.AGENT_RUNTIME_ARN;
}

// The app reads MCP resources directly; only the agent calls tools. The destination is the
// fixed MCP server, never derived from the URI, which is a name inside that server.
export async function readResultCsv(uri: string): Promise<string> {
  if (!resultCsvFilename(uri)) throw new Error("unsupported resource URI");
  const client = new Client({ name: "exploration-app", version: "0.1.0" });
  const { transport: connection, timeout } = transport();
  try {
    await client.connect(connection, { timeout });
    let result: Awaited<ReturnType<Client["readResource"]>>;
    try {
      result = await client.readResource({ uri }, { timeout });
    } catch {
      // Unknown, expired and other users' results are indistinguishable by design.
      throw new ResourceUnavailableError();
    }
    const [contents] = result.contents;
    if (!contents || !("text" in contents) || contents.mimeType?.split(";")[0] !== "text/csv") {
      throw new Error("unexpected resource contents");
    }
    return contents.text;
  } finally {
    await client.close();
  }
}
