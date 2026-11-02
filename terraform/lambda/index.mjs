import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from "@aws-sdk/client-bedrock-agentcore";
import { randomUUID } from "node:crypto";
import { createBridge } from "./bridge.mjs";

// Bundle this SDK with the ZIP rather than depending on the runtime-included version.
const client = new BedrockAgentCoreClient({ maxAttempts: 1 });

export const handler = awslambda.streamifyResponse(createBridge({
  invoke: (payload, signal) => client.send(new InvokeAgentRuntimeCommand({
    agentRuntimeArn: process.env.AGENT_RUNTIME_ARN,
    qualifier: "DEFAULT",
    // The full conversation is in AG-UI messages. Do not share a VM between callers.
    runtimeSessionId: randomUUID(),
    contentType: "application/json",
    accept: "text/event-stream",
    payload,
  }), { abortSignal: signal }),
  respond: (stream, metadata) => awslambda.HttpResponseStream.from(stream, metadata),
}));
