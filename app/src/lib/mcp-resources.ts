import "server-only";

import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from "@aws-sdk/client-bedrock-agentcore";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { mcpRuntimeFetch, validMcpRuntimeArn } from "./agentcore-mcp";

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

// A new AgentCore session may start a microVM, so allow for a cold start.
const TIMEOUT_MS = 30_000;

function transport(): StreamableHTTPClientTransport {
  const arn = process.env.MCP_RUNTIME_ARN;
  if (arn) {
    return new StreamableHTTPClientTransport(new URL("http://agentcore.internal/mcp"), {
      fetch: mcpRuntimeFetch(validMcpRuntimeArn(arn), (input, signal) =>
        agentCore.send(new InvokeAgentRuntimeCommand(input), { abortSignal: signal }),
      ),
    });
  }
  // With user authentication, pass the user's MCP-audience token (for example obtained
  // on behalf of the user) as authProvider: { token: async () => token }.
  return new StreamableHTTPClientTransport(mcpUrl(), { requestInit: { redirect: "error" } });
}

// The app reads MCP resources directly; only the agent calls tools. The destination is the
// fixed MCP server, never derived from the URI, which is a name inside that server.
// The caller validates the URI against the result CSV template.
export async function readResultCsv(uri: string): Promise<string> {
  const client = new Client({ name: "exploration-app", version: "0.1.0" });
  try {
    await client.connect(transport(), { timeout: TIMEOUT_MS });
    let result: Awaited<ReturnType<Client["readResource"]>>;
    try {
      result = await client.readResource({ uri }, { timeout: TIMEOUT_MS });
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
