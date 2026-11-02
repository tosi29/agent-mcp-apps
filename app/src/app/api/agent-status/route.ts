import { agentUrl, allowedOrigin } from "../../../lib/backend";

export async function GET(request: Request) {
  if (!allowedOrigin(request)) {
    return Response.json({ error: "origin not allowed" }, { status: 403 });
  }
  try {
    const response = await fetch(new URL("/ping", agentUrl()), {
      cache: "no-store", signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) throw new Error("backend unavailable");
    const status = await response.json();
    return Response.json({ mode: status.mode, connected: true });
  } catch {
    return Response.json({ connected: false }, { status: 503 });
  }
}
