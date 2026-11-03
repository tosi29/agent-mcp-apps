import { sandboxDocument, sandboxHeaders } from "../../lib/mcp-apps-sandbox";

// Read APP_ORIGIN at invocation time, after Terraform configures the Lambda.
export const dynamic = "force-dynamic";

export function GET() {
  const origin = process.env.APP_ORIGIN;
  if (origin) {
    try {
      const origins = [origin];
      return new Response(sandboxDocument(origins), { headers: sandboxHeaders(origins) });
    } catch {
      // A missing/invalid allowlist must never become a wildcard frame-ancestors policy.
    }
  }
  return new Response("Sandbox host origin is not configured", {
    status: 503,
    headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}
