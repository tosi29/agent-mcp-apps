import { backendStatus, allowedOrigin } from "../../../lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  if (!allowedOrigin(request)) {
    return Response.json({ error: "origin not allowed" }, { status: 403 });
  }
  try {
    const status = await backendStatus();
    return Response.json(status, { status: status.connected ? 200 : 503 });
  } catch {
    return Response.json({ connected: false }, { status: 503 });
  }
}
