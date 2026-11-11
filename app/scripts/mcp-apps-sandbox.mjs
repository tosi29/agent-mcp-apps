// Static sandbox proxy only. It has no MCP credentials or business-data endpoint.
import { createServer } from "node:http";
import { sandboxDocument, sandboxHeaders } from "../src/lib/mcp-apps-sandbox.ts";

export { sandboxDocument } from "../src/lib/mcp-apps-sandbox.ts";

export function createSandboxServer(
  hostOrigins = ["http://127.0.0.1:3000", "http://localhost:3000"],
) {
  const headers = sandboxHeaders(hostOrigins);
  return createServer((request, response) => {
    const hostname = (request.headers.host ?? "").split(":")[0];
    if (!["127.0.0.1", "localhost"].includes(hostname)) {
      response.writeHead(403).end();
      return;
    }
    if (!["GET", "HEAD"].includes(request.method) || request.url !== "/sandbox") {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, headers);
    response.end(request.method === "HEAD" ? undefined : sandboxDocument(hostOrigins));
  });
}

if (import.meta.main) {
  const port = Number(process.env.MCP_APPS_SANDBOX_PORT ?? "3001");
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid sandbox port");
  const origins = process.env.APP_ORIGIN ? [new URL(process.env.APP_ORIGIN).origin] : undefined;
  createSandboxServer(origins).listen(port, "127.0.0.1", () => {
    console.log(`MCP Apps sandbox: http://127.0.0.1:${port}/sandbox`);
  });
}
