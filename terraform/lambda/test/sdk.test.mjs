import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { test } from "node:test";
import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from "@aws-sdk/client-bedrock-agentcore";

test("the pinned SDK exposes AgentCore's SSE as a readable body without buffering it", async () => {
  const arn = "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/test_agent";
  const body = Readable.from([Buffer.from("data: {\"type\":\"RUN_STARTED\"}\n\n")]);
  let sent;
  const client = new BedrockAgentCoreClient({
    region: "ap-northeast-1", maxAttempts: 1,
    credentials: { accessKeyId: "test-access-key", secretAccessKey: "test-secret-key" },
    requestHandler: {
      handle: async request => {
        sent = request;
        return { response: { statusCode: 200, headers: { "content-type": "text/event-stream" }, body } };
      },
    },
  });
  try {
    const response = await client.send(new InvokeAgentRuntimeCommand({
      agentRuntimeArn: arn, qualifier: "DEFAULT", runtimeSessionId: "00000000-0000-4000-8000-000000000000",
      contentType: "application/json", accept: "text/event-stream", payload: Buffer.from("{}"),
    }));
    assert.equal(response.statusCode, 200);
    assert.equal(response.contentType, "text/event-stream");
    assert.equal(response.response, body);
    assert.equal(body.readableEnded, false);
    assert.equal(sent.path, `/runtimes/${encodeURIComponent(arn)}/invocations`);
    assert.equal(sent.query.qualifier, "DEFAULT");
    assert.match(sent.headers.authorization, /^AWS4-HMAC-SHA256 /);
    assert.equal(sent.headers.accept, "text/event-stream");
  } finally {
    body.destroy();
    client.destroy();
  }
});
