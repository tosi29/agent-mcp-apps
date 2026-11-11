import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { allowedOrigin, backendAgent } from "../../../../lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const copilot = new CopilotRuntime({
  agents: {
    explorer: backendAgent(),
  },
  runner: new InMemoryAgentRunner({ maxThreads: 10, maxRunsPerThread: 5, maxBytes: 8_000_000 }),
});

const handler = createCopilotRuntimeHandler({ runtime: copilot, basePath: "/api/copilotkit" });

async function handle(request: Request) {
  if (!allowedOrigin(request)) {
    return Response.json({ error: "origin not allowed" }, { status: 403 });
  }
  try {
    return await handler(request);
  } catch {
    return Response.json(
      { error: "エージェントに接続できません。起動状態を確認してください。" },
      { status: 502 },
    );
  }
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
