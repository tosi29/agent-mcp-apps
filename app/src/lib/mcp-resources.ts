import "server-only";

import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { resultCsvFilename } from "./result-csv";

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

// The app reads MCP resources directly; only the agent calls tools. The destination is the
// fixed MCP server, never derived from the URI, which is a name inside that server.
export async function readResultCsv(uri: string): Promise<string> {
  if (!resultCsvFilename(uri)) throw new Error("unsupported resource URI");
  const client = new Client({ name: "exploration-app", version: "0.1.0" });
  // With user authentication, pass the user's MCP-audience token (for example obtained
  // on behalf of the user) as authProvider: { token: async () => token }.
  const transport = new StreamableHTTPClientTransport(mcpUrl(), {
    requestInit: { redirect: "error" },
  });
  try {
    await client.connect(transport, { timeout: 10_000 });
    let result: Awaited<ReturnType<Client["readResource"]>>;
    try {
      result = await client.readResource({ uri }, { timeout: 10_000 });
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
