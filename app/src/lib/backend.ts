import "server-only";

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
  return !origin || ["http://127.0.0.1:3000", "http://localhost:3000"].includes(origin);
}
