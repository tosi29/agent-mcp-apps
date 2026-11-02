// Web Adapter readiness must not invoke the agent or depend on AWS API latency.
export function GET() {
  return Response.json({ status: "Healthy" });
}
